"""Synthetic user-decision races and crash recovery through the small-batch coordinator and shared stages."""
from contextlib import contextmanager

import pytest

from deixis.workflow.decisions import DecisionStore
from fakes import FakeAdapter, valid_response
from test_abstract_flow import client_of, records_of, work as abstract_work
from test_adjudication_flow import app_for, discover, wait, papers
from deixis.workflow import small_batch
from deixis.workflow.background_fetch import FetchSlots
from deixis.workflow.flow import ResearchFlow
from test_abstract_flow import ON_TOPIC, QUESTION
from test_fetch_overlap_flow import Crash, app_for as overlap_app_for, fulltext_codes, run_until_crash, work_steps
from test_fulltext_flow import Fetcher, Transport, named_pdf, ok, work
from batch_outputs import stage_output
from test_queue_api import sent_records, sent_source

@contextmanager
def session(app):
    client = client_of(app)
    try:
        yield client
    finally:
        client.__exit__(None, None, None)


@pytest.mark.parametrize("phase,boundary", [("fulltext_adjudication", "late_response")])
def test_user_decision_at_send_boundaries_stops_new_calls_and_publication(tmp_path, monkeypatch, phase, boundary):
    holder = {}

    def decide():
        store = holder["app"].state.store
        decisions = DecisionStore(store)
        for source in holder["targets"]:
            decisions.record(holder["rid"], source, "human_criterion_not_met")
        holder["decided"] = True

    def before(si):
        if si["task_type"] != phase or holder.get("armed"):
            return
        store = holder["app"].state.store
        holder.update(armed=True, rid=si["research_id"])
        sent = sent_records(store, si) if phase == "abstract_screening" else [sent_source(store, si)]
        targets = sent[:1]
        if boundary == "empty_batch":
            targets = sent
        elif boundary in ("other_work", "next_batch"):
            targets = [next(source for source in records_of(store, si["research_id"]).values() if source not in sent)]
        holder.update(targets=targets, first=sent)
        if boundary != "health":
            decide()

    adapter = FakeAdapter(valid_response, before=before, delay=0.03)
    health = adapter.health
    async def checked(refresh=False):
        if boundary == "health" and holder.get("armed") and not holder.get("decided"):
            decide()
        return await health(refresh)
    adapter.health = checked
    if phase == "abstract_screening":
        works = [abstract_work(n) for n in range(45 if boundary == "next_batch" else 3)]
        fetcher = papers(0)[1]
    else:
        works, fetcher = papers(2 if boundary == "other_work" else 1)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter, concurrency=1,
                  fetch="off" if phase == "abstract_screening" else "auto",
                  reading="off" if phase == "abstract_screening" else "auto")
    holder["app"] = app
    with session(app) as client:
        rid, run_id, _, paused = discover(client, effort="standard" if boundary == "next_batch" else "quick")
        assert (paused["status"], paused["pause_reason"]) == ("paused", "selection_changed")
        store = app.state.store
        calls = [c for c in adapter.calls if c["task_type"] == phase]
        assert len(calls) == 1
        decisions = DecisionStore(store)
        stage = "abstract" if phase == "abstract_screening" else "fulltext"
        for source in holder["targets"]:
            assert not decisions.proposals(rid, source, stage)
            assert decisions.current(rid, source, "fulltext")["reason_code"] == "human_criterion_not_met"
        assert not store.conn.execute("SELECT 1 FROM model_proposals WHERE research_id = ? AND stage = ?", (rid, stage)).fetchone()
        if boundary == "health":
            unsent = [s for s in store.run_steps(run_id) if s["kind"] == "model:" + phase and s["status"] != "succeeded"]
            assert all(store.last_step_input(s["id"]) is None for s in unsent)
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
        assert wait(client, rid, run_id)[1]["status"] == "completed"
        later = [c for c in adapter.calls if c["task_type"] == phase][len(calls):]
        for call in later:
            shown = sent_records(store, call) if phase == "abstract_screening" else [sent_source(store, call)]
            assert set(shown).isdisjoint(holder["targets"])


# ---- a crash and the restart (was test_small_batch_recovery.py) ------------------------------------------

def seeded_app(tmp_path, monkeypatch, n=3, **kwargs):
    records = [work(i, title=ON_TOPIC, pdf_url=f"https://example.org/w{i}.pdf") for i in range(1, n + 1)]
    fetcher = Fetcher({f"https://example.org/w{i}.pdf": ok(named_pdf(f"10.1/oa.{i}"))
                       for i in range(1, n + 1)})
    app = overlap_app_for(tmp_path, monkeypatch, Transport(records), fetcher, **kwargs)
    return app, fetcher


def serial(app):
    """One work fetched at a time: the fast read's fetch slots, not `FULLTEXT_FETCH_PARALLEL`, bound it."""
    app.state.worker.flow.deps.fetch_slots = FetchSlots(1)


def queue(client):
    rid = client.post("/api/researches", json={"question": QUESTION, "model_connection": "fake",
                                               "requested_model": "fake-model", "effort": "quick"}).json()["research"]["id"]
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    return rid, run_id


@pytest.mark.parametrize("point", ["after_code"])
def test_fetch_crash_recovery_preserves_settled_work_and_frozen_plan(tmp_path, monkeypatch, point):
    """A crash after a work's code step: the restart marks the run's running steps `outcome_unknown` and pauses the
    run (`run_until_crash` calls `Worker.recover`, then resumes it as the person would); the resumed run keeps the
    frozen list and baseline, reuses every settled work and fetches no file twice."""
    app, fetcher = seeded_app(tmp_path, monkeypatch, start_worker=False)
    with session(app) as client:
        serial(app)
        store = app.state.store
        armed = True
        dead = False

        def crash():
            nonlocal armed, dead
            if armed:
                armed = False
                dead = True
                raise Crash

        flow = app.state.worker.flow

        async def gate(run, wid):
            # The fast read drains its other fetch tasks before the crash leaves it; a dead process starts nothing.
            if dead:
                raise Crash
            return await type(flow)._overlap_work(flow, run, wid)
        flow._overlap_work = gate

        def restart():
            nonlocal dead
            crashed = run_until_crash(client, app, run_id)
            dead = False
            return crashed

        original = ResearchFlow._overlap_work
        async def after_code(self, run, wid):
            await original(self, run, wid)
            crash()
        monkeypatch.setattr(ResearchFlow, "_overlap_work", after_code)
        rid, run_id = queue(client)
        assert restart()
        listing = store.existing_step(run_id, small_batch.LIST_KEY)
        baseline = stage_output(store, run_id, "baseline")
        settled = {s["operation_key"] for s in work_steps(store, run_id) if s["status"] == "succeeded"}
        for _ in range(4):
            if not restart():
                break
        assert store.run(run_id)["status"] == "completed"
        assert store.existing_step(run_id, small_batch.LIST_KEY) == listing
        assert stage_output(store, run_id, "baseline") == baseline
        steps = work_steps(store, run_id)
        assert settled <= {s["operation_key"] for s in steps if s["status"] == "succeeded"}
        assert len(steps) == 3
        assert all(s["status"] == "succeeded" for s in steps), [(s["status"], s["attempt"]) for s in steps]
        assert set(fulltext_codes(store, rid).values()) == {"not_read_yet"}
        for i in (1, 2, 3):
            assert fetcher.calls.count(f"https://example.org/w{i}.pdf") == 1
