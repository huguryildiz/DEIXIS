"""The full-text fetch that overlaps an `sw` discovery run, driven through the API and the flow (slice 17a).

What is checked here is workflow behavior: the fetch starts inside the discovery run after the abstract code step and
before the model's last batch closes; it fetches the works a separate retrieval run would; the reading run opens once
on either path; only the coordinator writes a stop, after both arms drained; a settled work's step, event and code
exist together; a person's full-text decision stands in a race; and a resumed run, after a pause or a crash at any of
four points, asks no settled work again and fetches the same set.

Records, titles and abstracts are SYNTHETIC and from two fields, every transport is mocked and the model is scripted.
Passing shows the run follows the slice, not that it is faster on a real library: how much earlier a real fetch
ends was replayed on stored libraries (`.local/sw-slice17a-plan-2026-09-24/`), not measured here.
"""

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
from test_fulltext_flow import app_for as separate_app_for
from test_fulltext_flow import wait_for_retrieval

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
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_workflow="sw", search_query="code",
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


def runs_of(client, rid, kind):
    return [r for r in client.get(f"/api/researches/{rid}").json()["runs"] if r["kind"] == kind]


def output(store, run_id, key):
    row = store.conn.execute("SELECT output_json FROM run_steps WHERE run_id = ? AND operation_key = ?",
                             (run_id, key)).fetchone()
    return None if row is None or row[0] is None else json.loads(row[0])


def work_steps(store, run_id):
    return [dict(row) | {"output": json.loads(row["output_json"] or "{}")} for row in store.conn.execute(
        "SELECT * FROM run_steps WHERE run_id = ? AND kind = 'code:fulltext_work' ORDER BY rowid", (run_id,))]


def fetched(store, rid, run_id):
    """The works this run fetched, by OpenAlex identifier, with the code each settled on (None: not settled)."""
    by_svid = {svid: key for key, svid in records_of(store, rid).items()}
    heads = store.work_heads(rid)
    out = {}
    for step in work_steps(store, run_id):
        key = step["operation_key"].split(":", 1)[1]
        head = step["output"].get("head") or heads.get(key, key)
        out[by_svid.get(head, head)] = step["output"].get("code") if step["status"] == "succeeded" else None
    return dict(sorted(out.items()))


def fulltext_codes(store, rid):
    decisions = DecisionStore(store)
    return {key: (decisions.current(rid, svid, "fulltext") or {}).get("reason_code")
            for key, svid in sorted(records_of(store, rid).items())}


def events(store, rid, type_=None):
    return [dict(row) | {"payload": json.loads(row["payload_json"])} for row in store.conn.execute(
        "SELECT * FROM events WHERE research_id = ? ORDER BY id", (rid,)) if type_ is None or row["type"] == type_]


def step_events(store, rid, kind, type_):
    return [e for e in events(store, rid, type_) if e["payload"].get("kind") == kind]


def separate(tmp_path, monkeypatch, transport, fetcher, **extra):
    """The same library through the path a run queued before 17a takes: a separate retrieval run afterwards."""
    app = separate_app_for(tmp_path, monkeypatch, transport, fetcher,
                           adapter=FakeAdapter(responder(), delay=0.05), overlap=False)
    client = client_of(app)
    try:
        rid = research(client)
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, run_id)
        _, retrieval = wait_for_retrieval(client, rid)
        store = app.state.store
        return {"fetched": fetched(store, rid, retrieval["id"]), "codes": fulltext_codes(store, rid),
                "plan": output(store, retrieval["id"], "fulltext_plan"), "baseline": output(store, run_id, "fetch_baseline"),
                "summary": output(store, retrieval["id"], "fulltext_summary")}
    finally:
        client.__exit__(None, None, None)


# ---- the fetch starts inside discovery, early, and fetches what a separate run would ---------------------

def test_the_fetch_starts_before_the_last_model_batch_closes_and_fetches_what_a_separate_run_would(tmp_path, monkeypatch):
    works, answers = library()
    app = app_for(tmp_path / "overlap", monkeypatch, Transport(works), SlowFetcher(answers, delay=0.01))
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        got, codes = fetched(store, rid, run_id), fulltext_codes(store, rid)
        plan, baseline = output(store, run_id, "fulltext_plan"), output(store, run_id, "fetch_baseline")
        summary = output(store, run_id, "fulltext_summary")
        by_svid = {svid: key for key, svid in records_of(store, rid).items()}
        at_code_step = step_events(store, rid, "model:abstract_screening", "step_started")[0]["id"]
        early_code = {by_svid[s["output"]["head"]] for s in work_steps(store, run_id)
                      if s["output"]["claim"]["early"] and next(e["id"] for e in step_events(
                          store, rid, "code:fulltext_work", "step_started") if e["payload"]["step_id"] == s["id"])
                      < at_code_step or by_svid[s["output"]["head"]] in {f"W{n}" for n in CODE_WORKS}}
        first_fetch = step_events(store, rid, "code:fulltext_work", "step_started")[0]["id"]
        last_batch = step_events(store, rid, "model:abstract_screening", "step_finished")[-1]["id"]
        keys = [s["operation_key"] for s in store.run_steps(run_id)]
        retrieval_runs = runs_of(client, rid, "fulltext_fetch")
        shown = next(r for r in view["runs"] if r["id"] == run_id)
    finally:
        client.__exit__(None, None, None)
    alone = separate(tmp_path / "separate", monkeypatch, Transport(works), SlowFetcher(answers))

    assert run["status"] == "completed" and retrieval_runs == []
    assert run["budget"]["fulltext_fetch"] == {"mode": "overlap", **fulltext.fetch_budget("quick")}
    assert keys.index("abstract_stage") < keys.index("fetch_baseline") < keys.index("fulltext_plan")
    assert first_fetch < last_batch  # a PDF was on its way while the model still read abstracts
    assert got == alone["fetched"] and codes == alone["codes"]
    assert set(got) == {f"W{n}" for n in [*CODE_WORKS, *MODEL_WORKS]} and set(got.values()) == {"not_read_yet"}
    assert plan["works"] and len(plan["work_ids"]) == len(plan["works"]) == len(alone["plan"]["works"])
    assert {key: plan[key] for key in ("limit", "not_reached", "already_text", "groups")} == {
        key: alone["plan"][key] for key in ("limit", "not_reached", "already_text", "groups")}
    # The code's candidates were certain at the code step; a model batch's works become certain as it closes.
    assert early_code == {f"W{n}" for n in CODE_WORKS} and len(plan["claimed_early"]) >= len(CODE_WORKS)
    assert plan["deviations"] == [] and plan["conditions_held"] is True
    assert plan["baseline_hash"] == baseline["hash"] and baseline["settled"] == [] and baseline["has_text"] == []
    assert summary == alone["summary"]
    # The discovery turn carries the retrieval steps its timeline shows.
    assert {"code:fetch_baseline", "code:fulltext_plan", "code:fulltext_summary"} <= {s["kind"] for s in shown["steps"]}


def test_a_run_queued_before_17a_takes_the_separate_path_and_takes_no_baseline(tmp_path, monkeypatch):
    works, answers = library(model_works=range(101, 103))
    app = separate_app_for(tmp_path, monkeypatch, Transport(works), Fetcher(answers), overlap=False)
    client = client_of(app)
    try:
        rid = research(client)
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, run = wait(client, rid, run_id)
        _, retrieval = wait_for_retrieval(client, rid)
        keys = [s["operation_key"] for s in app.state.store.run_steps(run_id)]
    finally:
        client.__exit__(None, None, None)
    assert "mode" not in run["budget"]["fulltext_fetch"] and retrieval["status"] == "completed"
    assert not [key for key in keys if key.startswith(("fetch_baseline", "fulltext_"))]


def test_the_setting_off_queues_no_mode_and_fetches_nothing(tmp_path, monkeypatch):
    works, answers = library(model_works=range(101, 103))
    fetcher = Fetcher(answers)
    app = separate_app_for(tmp_path, monkeypatch, Transport(works), fetcher, setting="off", overlap=True)
    client = client_of(app)
    try:
        rid = research(client)
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, run = wait(client, rid, run_id)
        keys = [s["operation_key"] for s in app.state.store.run_steps(run_id)]
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed" and "fulltext_fetch" not in run["budget"]
    assert fetcher.calls == [] and "fetch_baseline" not in keys


# ---- the reading run opens exactly once on either path ------------------------------------------------

def test_the_reading_run_opens_once_from_the_discovery_run_and_once_from_a_separate_run(tmp_path, monkeypatch):
    works, answers = library(code_works=range(1, 3), model_works=range(101, 103))
    app = app_for(tmp_path / "overlap", monkeypatch, Transport(works), Fetcher(answers), reading="auto")
    client = client_of(app)
    try:
        rid, run_id, _, run = discover(client)
        deadline = time.time() + 30
        while time.time() < deadline and not runs_of(client, rid, "fulltext_adjudication"):
            time.sleep(0.05)
        reading = runs_of(client, rid, "fulltext_adjudication")
        store = app.state.store
        key = store.conn.execute("SELECT idempotency_key FROM runs WHERE id = ?", (reading[0]["id"],)).fetchone()[0]
        # Asked again for the same discovery run, the queue answers with the run it already opened.
        flow = app.state.worker.flow
        again = flow._queue_fulltext_adjudication(store.run(run_id), store.scope(rid))
        count = len(runs_of(client, rid, "fulltext_adjudication"))
        fetch_runs = runs_of(client, rid, "fulltext_fetch")
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed" and fetch_runs == [] and again is None
    assert len(reading) == 1 == count and key == f"fulltext_adjudication:after:{run_id}"

    monkeypatch.setattr(fulltext, "overlap_budget", fulltext.fetch_budget)
    app = app_for(tmp_path / "separate", monkeypatch, Transport(works), Fetcher(answers), reading="auto")
    client = client_of(app)
    try:
        rid, run_id, _, _ = discover(client)
        _, retrieval = wait_for_retrieval(client, rid)
        deadline = time.time() + 30
        while time.time() < deadline and not runs_of(client, rid, "fulltext_adjudication"):
            time.sleep(0.05)
        keys = [row[0] for row in app.state.store.conn.execute(
            "SELECT idempotency_key FROM runs WHERE research_id = ? AND kind = 'fulltext_adjudication'", (rid,))]
    finally:
        client.__exit__(None, None, None)
    assert keys == [f"fulltext_adjudication:after:{retrieval['id']}"]


# ---- only the coordinator writes a stop, after both arms drained ------------------------------------------

def paused_on_fetch(app, n):
    def hook(fetcher, url):
        if len(fetcher.calls) == n:
            row = app.state.store.conn.execute(
                "SELECT id FROM runs WHERE kind = 'discovery' AND status = 'running'").fetchone()
            if row:
                app.state.store.update_run(row["id"], event="run_pause_requested", status="pause_requested",
                                           pause_reason="user_requested")
    return hook


def assert_drained_before_the_stop(store, rid, stop_event):
    """Every retrieval and model step that started finished before the run read as stopped, and one stop was written."""
    stops = events(store, rid, stop_event)
    assert len(stops) == 1
    started = {e["payload"]["step_id"] for e in events(store, rid, "step_started") if e["id"] < stops[0]["id"]
               and e["payload"]["kind"] in ("code:fulltext_work", "fetch_pdf", "model:abstract_screening")}
    finished = {e["payload"]["step_id"] for e in events(store, rid, "step_finished") if e["id"] < stops[0]["id"]}
    assert started and started <= finished


def test_a_user_pause_is_written_once_both_arms_drained_and_the_resumed_run_asks_no_settled_work_again(tmp_path, monkeypatch):
    works, answers = library()
    fetcher = SlowFetcher(answers, delay=0.05)
    app = app_for(tmp_path / "paused", monkeypatch, Transport(works), fetcher)
    fetcher.hook = paused_on_fetch(app, 2)
    client = client_of(app)
    try:
        rid = research(client)
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, paused = wait(client, rid, run_id, ("paused", "completed", "failed"))
        store = app.state.store
        assert_drained_before_the_stop(store, rid, "run_paused")
        settled_before = {s["operation_key"] for s in work_steps(store, run_id) if s["status"] == "succeeded"}
        calls_before = list(fetcher.calls)
        fetcher.hook = None
        client.post(f"/api/runs/{run_id}/resume")
        _, done = wait(client, rid, run_id, ("completed", "failed"))
        got = fetched(store, rid, run_id)
        again = [u for u in fetcher.calls[len(calls_before):] if u in calls_before]
        baseline_rows = store.conn.execute("SELECT COUNT(*) FROM run_steps WHERE run_id = ? AND operation_key ="
                                           " 'fetch_baseline'", (run_id,)).fetchone()[0]
        steps = {s["operation_key"]: s for s in work_steps(store, run_id)}
    finally:
        client.__exit__(None, None, None)
    alone = separate(tmp_path / "separate", monkeypatch, Transport(works), SlowFetcher(answers))
    assert paused["status"] == "paused" and paused["pause_reason"] == "user_requested"
    assert settled_before and done["status"] == "completed"
    assert again == []  # no link a settled or cut work already answered is asked a second time
    assert all(steps[key]["attempt"] == 1 for key in settled_before)
    assert got == alone["fetched"] and baseline_rows == 1


def test_a_pause_the_model_arm_asks_for_waits_for_the_fetch_in_flight(tmp_path, monkeypatch):
    """A connection that stops being ready is the model arm's pause; the fetch drains before it is written."""
    works, answers = library()
    adapter = FakeAdapter(responder(), delay=0.05)

    def before(si):
        if si["task_type"] == "abstract_screening":
            adapter.ready = False  # the next model step finds the connection not ready
    adapter.before = before
    app = app_for(tmp_path, monkeypatch, Transport(works), SlowFetcher(answers, delay=0.1), adapter=adapter)
    client = client_of(app)
    try:
        rid = research(client)
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, run = wait(client, rid, run_id)
        store = app.state.store
        assert_drained_before_the_stop(store, rid, "run_paused")
        in_flight = [s for s in work_steps(store, run_id) if s["status"] == "running"]
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "paused" and run["pause_reason"] == "model_connection_not_ready"
    assert in_flight == []


def test_no_call_under_the_overlap_writes_a_pause_itself(tmp_path, monkeypatch):
    """Item 7: only the coordinator calls `update_run` with `paused`; every call under it only reads the stop."""
    works, answers = library()
    fetcher = SlowFetcher(answers, delay=0.05)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher)
    fetcher.hook = paused_on_fetch(app, 1)
    writers = []
    original = ResearchFlow._overlap

    async def watched(self, *args):
        store = self.store
        real = store.update_run

        def update_run(run_id, event=None, **fields):
            if fields.get("status") in ("paused", "failed", "cancelled"):
                writers.append(bool(self._held.get(run_id)))
            return real(run_id, event=event, **fields)
        store.update_run = update_run
        try:
            return await original(self, *args)
        finally:
            store.update_run = real
    monkeypatch.setattr(ResearchFlow, "_overlap", watched)
    client = client_of(app)
    try:
        rid = research(client)
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, run = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "paused"
    assert writers == [False]  # one write, made after the overlap let go of the run


def test_an_unexpected_error_in_the_fetch_arm_stops_the_model_arm_and_fails_the_run(tmp_path, monkeypatch):
    works, answers = library()
    calls = []
    original = ResearchFlow._claim_safe

    def broken(self, *args):
        calls.append(1)
        if len(calls) == 1:  # the fetch arm's first look, while the model reads its first batch
            raise RuntimeError("SYNTHETIC failure in the fetch arm")
        return original(self, *args)
    monkeypatch.setattr(ResearchFlow, "_claim_safe", broken)
    app = app_for(tmp_path, monkeypatch, Transport(works), SlowFetcher(answers, delay=0.01))
    client = client_of(app)
    try:
        rid = research(client)
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, run = wait(client, rid, run_id)
        store = app.state.store
        running = [s for s in store.run_steps(run_id) if s["status"] == "running"]
        failed = events(store, rid, "run_failed")
        last_step = max(e["id"] for e in events(store, rid, "step_finished"))
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "failed" and run["pause_reason"] == "internal_error"
    assert "SYNTHETIC failure" in run["error"]["error"]
    assert running == [] and failed[0]["id"] > last_step


def test_a_question_revision_during_the_overlap_cancels_the_run_after_both_arms_drained(tmp_path, monkeypatch):
    works, answers = library()
    fetcher = SlowFetcher(answers, delay=0.05)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher)

    def revise(fetcher, url):
        if len(fetcher.calls) == 1:
            store = app.state.store
            rid = store.conn.execute("SELECT research_id FROM runs WHERE kind = 'discovery'").fetchone()[0]
            research_row = store.research(rid)
            store.revise_scope(rid, research_row["version"], QUESTION + " SYNTHETIC revised", None)
    fetcher.hook = revise
    client = client_of(app)
    try:
        rid = research(client)
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, run = wait(client, rid, run_id)
        store = app.state.store
        assert_drained_before_the_stop(store, rid, "run_cancelled")
        late = [s for s in work_steps(store, run_id) if s["error_code"] == "scope_revised"]
        new_revision = store.conn.execute("SELECT COUNT(*) FROM stage_decisions WHERE research_id = ? AND stage ="
                                          " 'fulltext' AND scope_revision = 2", (rid,)).fetchone()[0]
        settled = {e["payload"]["step_id"] for e in events(store, rid, "fulltext_work_settled")}
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "cancelled" and run["pause_reason"] == "scope_revised"
    # A file that arrived after the question changed decides nothing: no code under the new revision, no event.
    assert late and all(s["status"] == "cancelled" and s["output"]["code"] for s in late)
    assert new_revision == 0 and not settled & {s["id"] for s in late}


def test_a_work_stopped_between_two_routes_is_not_left_running_and_settles_on_resume(tmp_path, monkeypatch):
    """A pause read before a work's second route stops that work; its step is closed, not left `running`."""
    record = work(1, pdf_url=url(1), pdf_version="submittedVersion")  # the published record's own link is closed
    works, answers = library(code_works=range(2, 3), model_works=range(101, 102))
    app = app_for(tmp_path, monkeypatch, Transport([record, *works]), Fetcher(answers | {url(1): ok()}))
    original = ResearchFlow._acquire_pdf

    async def acquire(self, run, svid, downloads, limit, other_versions=False):
        got = await original(self, run, svid, downloads, limit, other_versions)
        if other_versions and records_of(self.store, run["research_id"]).get("W1") == svid:
            self.store.update_run(run["id"], event="run_pause_requested", status="pause_requested",
                                  pause_reason="user_requested")
        return got
    monkeypatch.setattr(ResearchFlow, "_acquire_pdf", acquire)
    client = client_of(app)
    try:
        rid = research(client)
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, paused = wait(client, rid, run_id)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        cut = [s for s in work_steps(store, run_id) if s["status"] not in ("succeeded", "failed", "pending")]
        monkeypatch.setattr(ResearchFlow, "_acquire_pdf", original)
        client.post(f"/api/runs/{run_id}/resume")
        _, done = wait(client, rid, run_id, ("completed", "failed"))
        step = next(s for s in work_steps(store, run_id) if s["output"].get("head") == head)
    finally:
        client.__exit__(None, None, None)
    assert paused["status"] == "paused"
    assert [(s["status"], s["error_code"]) for s in cut] == [("cancelled", "run_stopped")]
    assert done["status"] == "completed" and step["status"] == "succeeded" and step["attempt"] == 2
    assert step["output"]["route"] == "work_version" and step["output"]["code"] == "not_read_yet"


# ---- a settled work: step, event and code together; a person's decision stands -----------------------------

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
        if step_id and self.store.existing_step(run["id"], "fetch_baseline"):
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


def test_a_human_fulltext_decision_made_while_the_work_is_fetched_stands(tmp_path, monkeypatch):
    works, answers = library(code_works=range(1, 3), model_works=range(101, 102))
    fetcher = Fetcher(answers)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher)

    def decide(fetcher, fetched_url):
        if fetched_url == url(1):
            store = app.state.store
            rid = store.conn.execute("SELECT research_id FROM runs WHERE kind = 'discovery'").fetchone()[0]
            DecisionStore(store).record(rid, records_of(store, rid)["W1"], "human_not_sure", note="SYNTHETIC")
    fetcher.hook = decide
    client = client_of(app)
    try:
        rid, run_id, _, run = discover(client)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        step = next(s for s in work_steps(store, run_id) if s["output"].get("head") == head)
        event = next(e for e in events(store, rid, "fulltext_work_settled") if e["payload"]["step_id"] == step["id"])
        held = DecisionStore(store).current(rid, head, "fulltext")
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed" and step["status"] == "succeeded"
    assert step["output"]["code"] == "not_read_yet" and step["output"]["code_written"] is False
    assert step["output"]["held_by"] == "human" and event["payload"]["code"] is None
    assert held["decided_by"] == "human" and held["reason_code"] == "human_not_sure"


def test_an_early_work_a_person_excluded_meanwhile_stays_fetched_and_is_named_as_a_deviation(tmp_path, monkeypatch):
    """Decision 2's conditions: the claim is kept and counted, and the plan says the equal-set claim did not hold."""
    works, answers = library(code_works=range(1, 4), model_works=range(101, 125))
    monkeypatch.setattr(fulltext, "FULLTEXT_WORK_LIMIT", dict(fulltext.FULLTEXT_WORK_LIMIT, quick=10))
    fetcher = SlowFetcher(answers)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher)

    def exclude(fetcher, fetched_url):
        if fetched_url == url(1):
            store = app.state.store
            rid = store.conn.execute("SELECT research_id FROM runs WHERE kind = 'discovery'").fetchone()[0]
            svid = records_of(store, rid)["W1"]
            version = store.conn.execute("SELECT version FROM selections WHERE research_id = ? AND source_version_id = ?",
                                         (rid, svid)).fetchone()[0]
            store.set_user_selection(rid, svid, "excluded", version, "SYNTHETIC")
    fetcher.hook = exclude
    client = client_of(app)
    try:
        rid, run_id, _, run = discover(client)
        store = app.state.store
        plan = output(store, run_id, "fulltext_plan")
        claimed = work_steps(store, run_id)
        w1 = store.conn.execute("SELECT work_id FROM source_versions WHERE id = ?",
                                (records_of(store, rid)["W1"],)).fetchone()[0]
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed"
    assert plan["deviations"] == [{"work_id": w1, "reason": "user_selection"}] and plan["conditions_held"] is False
    assert w1 not in plan["work_ids"] and len(claimed) == 10  # the excluded work took one of the ten slots


# ---- a crash at four points, and three crashes in a row ---------------------------------------------------

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
            left = [task for task in asyncio.all_tasks() if task.get_coro().__name__ in ("_overlap_work", "_screening",
                                                                                         "_fetch_arm")]
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


def crashed_then_resumed(tmp_path, monkeypatch, works, answers, arm, between=None, adapter=None, reading="off"):
    """Crash once where `arm` says, then run to the end; returns what was fetched, the codes, and the requests.
    `between` is what a person does while the process is down."""
    fetcher = Fetcher(answers)
    monkeypatch.setattr(fulltext, "FULLTEXT_FETCH_PARALLEL", 1)  # one work in flight: the crash cuts exactly one
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, start_worker=False, adapter=adapter,
                  reading=reading)
    with TestClient(app) as client:
        disarm = arm(app, fetcher, monkeypatch)
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid = research(client)
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        crashed = run_until_crash(client, app, run_id)
        first_baseline = output(app.state.store, run_id, "fetch_baseline")
        disarm()
        if between is not None:
            between(app.state.store, rid)
        # A restart runs only what it finds queued: a run the crash left completed is not run again.
        while app.state.store.run(run_id)["status"] == "queued" and run_until_crash(client, app, run_id):
            pass
        store = app.state.store
        result = {"crashed": crashed, "status": store.run(run_id)["status"], "fetched": fetched(store, rid, run_id),
                  "codes": fulltext_codes(store, rid), "calls": list(fetcher.calls),
                  "baseline": output(store, run_id, "fetch_baseline"), "first_baseline": first_baseline,
                  "plans": store.conn.execute("SELECT COUNT(*) FROM run_steps WHERE run_id = ? AND operation_key ="
                                              " 'fulltext_plan'", (run_id,)).fetchone()[0],
                  "steps": {s["operation_key"]: s for s in work_steps(store, run_id)},
                  "plan": output(store, run_id, "fulltext_plan"),
                  "reading": [row[0] for row in store.conn.execute(
                      "SELECT idempotency_key FROM runs WHERE research_id = ? AND kind = 'fulltext_adjudication'", (rid,))]}
    return result


def before_the_answer(app, fetcher, monkeypatch):
    def hook(fetcher, fetched_url):
        if len(fetcher.calls) == 2:
            raise Crash
    fetcher.hook = hook
    return lambda: setattr(fetcher, "hook", None)


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


def after_the_code(app, fetcher, monkeypatch):
    original, done = ResearchFlow._overlap_work, []

    async def work(self, run, work_id):
        await original(self, run, work_id)
        if not done:
            done.append(work_id)
            raise Crash
    monkeypatch.setattr(ResearchFlow, "_overlap_work", work)
    return lambda: monkeypatch.setattr(ResearchFlow, "_overlap_work", original)


def before_the_plan(app, fetcher, monkeypatch):
    original = ResearchFlow._overlap_plan

    def plan(self, *args):
        raise Crash
    monkeypatch.setattr(ResearchFlow, "_overlap_plan", plan)
    return lambda: monkeypatch.setattr(ResearchFlow, "_overlap_plan", original)


@pytest.mark.parametrize("arm", [before_the_answer, after_the_file, after_the_code, before_the_plan])
def test_a_crash_at_any_of_four_points_resumes_to_the_same_set_and_asks_no_settled_work_again(tmp_path, monkeypatch, arm):
    works, answers = library(code_works=range(1, 5), model_works=range(101, 104))
    whole = crashed_then_resumed(tmp_path / "whole", monkeypatch, works, answers, lambda *a: (lambda: None))
    cut = crashed_then_resumed(tmp_path / "cut", monkeypatch, works, answers, arm)
    assert whole["crashed"] is False and cut["crashed"] is True
    assert cut["status"] == whole["status"] == "completed"
    assert cut["fetched"] == whole["fetched"] and cut["codes"] == whole["codes"] and cut["plans"] == 1
    # A work settled before the crash is not asked again; only the one request in flight when it came may go twice
    # (item 2: at least once). After the file or after the code nothing was in flight but the crashed work itself.
    repeated = {u for u in cut["calls"] if cut["calls"].count(u) > 1}
    assert len(repeated) <= (1 if arm in (before_the_answer, before_the_plan) else 0)
    assert all(cut["calls"].count(u) <= 2 for u in cut["calls"])
    assert all(s["status"] == "succeeded" for s in cut["steps"].values())


def test_three_crashes_in_one_work_close_it_as_not_settled_and_the_run_goes_on(tmp_path, monkeypatch):
    works, answers = library(code_works=range(1, 3), model_works=range(101, 102))

    def arm(app, fetcher, monkeypatch):
        def hook(fetcher, fetched_url):
            if fetched_url == url(1):
                raise Crash
        fetcher.hook = hook
        return lambda: None  # it crashes every time it is asked

    result = crashed_then_resumed(tmp_path, monkeypatch, works, answers, arm)
    step = next(s for s in result["steps"].values() if s["output"].get("claim") and url(1) in result["calls"]
                and s["status"] == "failed")
    assert result["status"] == "completed"
    assert result["calls"].count(url(1)) == fulltext.FULLTEXT_WORK_ATTEMPTS
    assert step["error_code"] == "fetch_not_settled" and step["attempt"] == fulltext.FULLTEXT_WORK_ATTEMPTS
    assert result["codes"]["W1"] is None and result["codes"]["W2"] == "not_read_yet"


def test_the_baseline_is_read_back_unchanged_by_a_resumed_run(tmp_path, monkeypatch):
    works, answers = library(code_works=range(1, 5), model_works=range(101, 104))
    cut = crashed_then_resumed(tmp_path, monkeypatch, works, answers, before_the_answer)
    assert cut["crashed"] and cut["first_baseline"] is not None
    assert cut["baseline"] == cut["first_baseline"]  # the as-of time too: it was read back, not taken again


def after_the_plan(app, fetcher, monkeypatch):
    original, done = ResearchFlow._overlap_plan, []

    def plan(self, *args):
        written = original(self, *args)
        if not done:
            done.append(1)
            raise Crash
        return written
    monkeypatch.setattr(ResearchFlow, "_overlap_plan", plan)
    return lambda: monkeypatch.setattr(ResearchFlow, "_overlap_plan", original)


def test_a_person_s_change_while_the_process_is_down_after_the_plan_opens_no_claim_outside_it(tmp_path, monkeypatch):
    """Item 5: once the final plan is written it is the only source of claims, on a resumed run too."""
    works, answers = library(code_works=range(1, 4), model_works=())
    works.append(work(201, pdf_url=url(201), title=OFF_TOPIC, abstract=OFF_ABSTRACT))  # out of scope by code
    answers[url(201)] = ok()
    monkeypatch.setattr(fulltext, "FULLTEXT_WORK_LIMIT", dict(fulltext.FULLTEXT_WORK_LIMIT, quick=5))

    def include_w201(store, rid):  # a person includes it while the process is down; the plan had room for it
        svid = records_of(store, rid)["W201"]
        version = store.conn.execute("SELECT version FROM selections WHERE research_id = ? AND source_version_id = ?",
                                     (rid, svid)).fetchone()[0]
        store.set_user_selection(rid, svid, "included", version, "SYNTHETIC")

    cut = crashed_then_resumed(tmp_path, monkeypatch, works, answers, after_the_plan, between=include_w201)
    assert cut["crashed"] and cut["status"] == "completed"
    assert set(cut["fetched"]) == {"W1", "W2", "W3"} and len(cut["plan"]["fetch"]) == 3
    assert url(201) not in cut["calls"]


def test_a_crash_while_the_run_completes_rolls_it_back_and_the_reading_opens_once_on_resume(tmp_path, monkeypatch):
    """Decision 5: completing the run and queueing its reading are one transaction."""
    works, answers = library(code_works=range(1, 3), model_works=range(101, 102))
    original = ResearchFlow._queue_fulltext_adjudication

    def arm(app, fetcher, monkeypatch):
        def queue(self, run, scope):
            raise Crash  # after the run was marked completed, before its reading was queued
        monkeypatch.setattr(ResearchFlow, "_queue_fulltext_adjudication", queue)
        return lambda: monkeypatch.setattr(ResearchFlow, "_queue_fulltext_adjudication", original)

    cut = crashed_then_resumed(tmp_path, monkeypatch, works, answers, arm, reading="auto")
    assert cut["crashed"] and cut["status"] == "completed"
    assert len(cut["reading"]) == 1 and cut["reading"][0].startswith("fulltext_adjudication:after:run_")
