"""Synthetic small-batch settlement atomicity and shared crash/fetch test helpers."""

import asyncio
import json
import time

import httpx

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.providers.registry import CONNECTORS
from deixis.workflow.screen.decisions import DecisionStore
from fakes import FakeAdapter
from test_abstract_flow import QUESTION, records_of, responder
from test_fulltext_flow import Fetcher

SETTLED = ("completed", "failed", "paused", "cancelled")


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


def app_for(tmp_path, monkeypatch, transport, fetcher, *, adapter=None, reading="off",
            start_worker=True):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", "sw")
    monkeypatch.setenv("DEIXIS_CONTACT_EMAIL", "synthetic@example.org")
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_query="code",
                               fulltext_fetch="auto", fulltext_adjudication=reading),
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


