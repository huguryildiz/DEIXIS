"""Synthetic small-batch settlement atomicity and shared crash/fetch test helpers."""

import asyncio
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.providers.registry import CONNECTORS
from deixis.workflow import fulltext
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.flow import ResearchFlow
from fakes import FakeAdapter
from test_abstract_flow import OFF_ABSTRACT, OFF_TOPIC, ON_TOPIC, QUESTION, client_of, records_of, responder
from test_fulltext_flow import Fetcher, Transport, named_pdf, ok, work

SETTLED = ("completed", "failed", "paused", "cancelled")
CODE_WORKS = range(1, 7)       # both gate blocks in the title: code keeps them, so they are safe at the code step
MODEL_WORKS = range(101, 125)  # the model reads these, in two batches


def url(n):
    return f"https://example.org/w{n}.pdf"


def library(code_works=CODE_WORKS, model_works=MODEL_WORKS):
    works = ([work(n, pdf_url=url(n), title=ON_TOPIC) for n in code_works]
             + [work(n, pdf_url=url(n)) for n in model_works])
    return works, {url(n): ok(named_pdf(f"10.1/oa.{n}")) for n in [*code_works, *model_works]}


class SlowFetcher(Fetcher):
    """A fetcher that takes `delay` seconds per request, so works are in flight while other things happen."""

    def __init__(self, answers, delay=0.0, hook=None):
        super().__init__(answers, hook)
        self.delay = delay

    async def __call__(self, url):
        answer = await super().__call__(url)
        if self.delay:
            await asyncio.sleep(self.delay)
        return answer


def app_for(tmp_path, monkeypatch, transport, fetcher, *, adapter=None, reading="off", approval="as_proposed",
            start_worker=True):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", "sw")
    monkeypatch.setenv("DEIXIS_CONTACT_EMAIL", "synthetic@example.org")
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_query="code",
                               protocol_approval=approval, fulltext_fetch="auto", fulltext_adjudication=reading),
                      adapters={"fake": adapter or FakeAdapter(responder(), delay=0.05)},
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)), fetcher=fetcher,
                      extra_hosts=("testserver",), trusted_clients=("testclient",), start_worker=start_worker)


def wait(client, rid, run_id, statuses=SETTLED):
    deadline = time.time() + 30
    while time.time() < deadline:
        view = client.get(f"/api/researches/{rid}").json()
        run = next(r for r in view["runs"] if r["id"] == run_id)
        if run["status"] in statuses:
            return view, run
        time.sleep(0.02)
    raise AssertionError("the run did not settle")


def research(client, effort="quick"):
    return client.post("/api/researches", json={"question": QUESTION, "model_connection": "fake",
                                               "requested_model": "fake-model", "effort": effort}).json()["research"]["id"]


def discover(client, effort="quick"):
    rid = research(client, effort)
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    view, run = wait(client, rid, run_id)
    return rid, run_id, view, run


def output(store, run_id, key):
    row = store.conn.execute("SELECT output_json FROM run_steps WHERE run_id = ? AND operation_key = ?",
                             (run_id, key)).fetchone()
    return None if row is None or row[0] is None else json.loads(row[0])


def work_steps(store, run_id):
    return [dict(row) | {"output": json.loads(row["output_json"] or "{}")} for row in store.conn.execute(
        "SELECT * FROM run_steps WHERE run_id = ? AND kind = 'code:fulltext_work' ORDER BY rowid", (run_id,))]


def fulltext_codes(store, rid):
    decisions = DecisionStore(store)
    return {key: (decisions.current(rid, svid, "fulltext") or {}).get("reason_code")
            for key, svid in sorted(records_of(store, rid).items())}


def events(store, rid, type_=None):
    return [dict(row) | {"payload": json.loads(row["payload_json"])} for row in store.conn.execute(
        "SELECT * FROM events WHERE research_id = ? ORDER BY id", (rid,)) if type_ is None or row["type"] == type_]


def test_a_settled_work_has_its_step_its_event_and_its_code_together(tmp_path, monkeypatch):
    works, answers = library(code_works=range(1, 4), model_works=range(101, 104))
    answers[url(2)] = ok(b"%PDF-1.4 SYNTHETIC not a readable file")
    app = app_for(tmp_path, monkeypatch, Transport(works), Fetcher(answers))
    client = client_of(app)
    try:
        rid, run_id, _, run = discover(client)
        store = app.state.store
        steps = [s for s in work_steps(store, run_id) if s["status"] == "succeeded"]
        settled = {e["payload"]["step_id"]: e for e in events(store, rid, "fulltext_work_settled")}
        decisions = DecisionStore(store)
        rows = {s["id"]: decisions.current(rid, s["output"]["read_version"], "fulltext") for s in steps}
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed" and steps and set(settled) == {s["id"] for s in steps}
    for step in steps:
        event = settled[step["id"]]["payload"]
        assert event == {"run_id": run_id, "work_id": step["output"]["work_id"], "head": step["output"]["head"],
                         "read_version": step["output"]["read_version"], "code": step["output"]["code"],
                         "asset_id": step["output"]["asset_id"], "step_id": step["id"]}
        assert step["output"]["code_written"] is True and step["output"]["held_by"] is None
        assert step["output"]["claim"]["claimed_at"] and step["operation_key"] == f"fulltext_work:{step['output']['work_id']}"
        assert rows[step["id"]]["reason_code"] == step["output"]["code"] and rows[step["id"]]["step_id"] == step["id"]


def test_a_rolled_back_settlement_leaves_no_event_no_code_and_no_finished_step(tmp_path, monkeypatch):
    """The three are one transaction: a failure while writing them leaves none of them behind."""
    works, answers = library(code_works=range(1, 2), model_works=range(101, 102))
    app = app_for(tmp_path, monkeypatch, Transport(works), Fetcher(answers))
    original = ResearchFlow._write_fulltext_codes

    def broken(self, run, step_id, writes):
        written = original(self, run, step_id, writes)
        if step_id and self.store.existing_step(run["id"], "small_batch:v1:list"):
            raise RuntimeError("SYNTHETIC failure after the code was written")
        return written
    monkeypatch.setattr(ResearchFlow, "_write_fulltext_codes", broken)
    client = client_of(app)
    try:
        rid, run_id, _, run = discover(client)
        store = app.state.store
        succeeded = [s for s in work_steps(store, run_id) if s["status"] == "succeeded"]
        settled = events(store, rid, "fulltext_work_settled")
        codes = {v for v in fulltext_codes(store, rid).values() if v}
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "failed"
    assert succeeded == [] and settled == [] and codes == set()


class Crash(BaseException):
    """The process dying: nothing below catches it, and the run's rows stay as the crash left them."""


def run_until_crash(client, app, run_id):
    """Run the run on the app's own loop as the worker would, until it ends or crashes; then start over as a restart
    does (`Worker.recover`: running steps become `outcome_unknown`, the run `paused`), and queue it again."""
    store, flow = app.state.store, app.state.worker.flow
    store.update_run(run_id, event="run_started", status="running", pause_reason=None, error_json=None)

    async def until_crash():
        try:
            await flow.execute(run_id)
            return False
        except Crash:
            # A dead process runs nothing more: the run's tasks the crash left behind are stopped where they stand.
            left = [task for task in asyncio.all_tasks() if task.get_coro().__name__ in ("_overlap_work", "fetch_arm", "model_arm")]
            for task in left:
                task.cancel()
            await asyncio.gather(*left, return_exceptions=True)
            return True
    crashed = client.portal.call(until_crash)
    if crashed:
        app.state.worker.recover()
        if store.run(run_id)["pause_reason"] == "backend_restarted":
            store.update_run(run_id, status="queued")  # the user's resume after the restart
    return crashed


def after_the_file(app, fetcher, monkeypatch):
    store = app.state.store
    original, done = store.add_asset_with_pages, []

    def add(*args, **kwargs):
        asset = original(*args, **kwargs)
        if not done:
            done.append(asset)
            raise Crash
        return asset
    store.add_asset_with_pages = add
    return lambda: setattr(store, "add_asset_with_pages", original)
