"""Synthetic user-decision races through the small-batch coordinator and shared stages."""
import asyncio
from contextlib import contextmanager

import pytest

from deixis.models.adapter import ModelStepResult
from deixis.workflow.decisions import DecisionStore
from deixis.workflow import flow as flow_module
from fakes import FakeAdapter, valid_response
from test_abstract_flow import client_of, records_of, responder, work as abstract_work
from test_adjudication_flow import app_for, discover, wait, papers, adj_calls
from test_fulltext_flow import Transport
from test_queue_api import sent_records, sent_source

@contextmanager
def session(app):
    client = client_of(app)
    try:
        yield client
    finally:
        client.__exit__(None, None, None)



@pytest.mark.parametrize("race", ["limiter_wait", "rate_limit", "undo_before_close", "pause_undo_resume"])
def test_abstract_decision_races_preserve_supplied_inputs(tmp_path, monkeypatch, race):
    monkeypatch.setattr(flow_module, "RATE_LIMIT_BACKOFF_SECONDS", 0)
    holder = {}

    def before(si):
        store = holder["app"].state.store
        if si["task_type"] != "abstract_screening":
            if race == "limiter_wait" and "hold" not in holder:
                holder["release"] = asyncio.Event()
                limiter = holder["app"].state.worker.flow.deps.limiter
                holder["hold"] = asyncio.create_task(limiter.run("synthetic-hold", holder["release"].wait))
            return
        if "decided" in holder:
            return
        sent = sent_records(store, si)
        holder.update(decided=sent[0], first=sent, rid=si["research_id"])
        if race == "limiter_wait":
            limiter = holder["app"].state.worker.flow.deps.limiter
            holder["waiting"] = limiter._in_flight == 2 and len(limiter._by_key) >= 3
            holder["release"].set()
        DecisionStore(store).record(si["research_id"], sent[0], "human_include")
        if race == "pause_undo_resume":
            store.update_run(si["run_id"], event="run_pause_requested", status="pause_requested",
                             pause_reason="user_requested")

    def respond(si):
        if si["task_type"] == "abstract_screening" and race == "undo_before_close" and not holder.get("undone"):
            DecisionStore(holder["app"].state.store).undo_human(holder["rid"], holder["decided"], "fulltext")
            holder["undone"] = True
        return responder()(si)

    def fail(si):
        if si["task_type"] == "abstract_screening" and race == "rate_limit" and not holder.get("limited"):
            holder["limited"] = True
            return ModelStepResult("failed", error="429 Too Many Requests")
        return None

    adapter = FakeAdapter(respond, delay=0.05, before=before, fail=fail)
    app = app_for(tmp_path, monkeypatch, Transport([abstract_work(n) for n in range(3)]), papers(0)[1],
                  adapter=adapter, fetch="off", reading="off", concurrency=2)
    holder["app"] = app
    with session(app) as client:
        rid, run_id, _, stopped = discover(client)
        store = app.state.store
        decisions = DecisionStore(store)
        source = holder["decided"]
        calls = [c for c in adapter.calls if c["task_type"] == "abstract_screening"]
        sent = [sent_records(store, c) for c in calls]
        assert source in sent[0]
        assert not decisions.proposals(rid, source, "abstract")
        assert decisions.current(rid, source, "abstract") is None
        if race == "undo_before_close":
            assert holder["undone"]
            assert all(source not in batch for batch in sent[1:])
        assert stopped["status"] == "paused", stopped
        assert stopped["pause_reason"] == "selection_changed"
        if race == "limiter_wait":
            assert holder["waiting"]
            assert holder["hold"].done()
        if race == "pause_undo_resume":
            decisions.undo_human(rid, source, "fulltext")
        response = client.post(f"/api/runs/{run_id}/resume")
        assert response.status_code == 200, response.text
        _, completed = wait(client, rid, run_id)
        assert completed["status"] == "completed", completed
        later = [c for c in adapter.calls if c["task_type"] == "abstract_screening"][len(calls):]
        if race not in ("pause_undo_resume", "undo_before_close"):
            assert all(source not in sent_records(store, c) for c in later)
            assert not decisions.proposals(rid, source, "abstract")
        else:
            # A decision may be published only from the intersection of the stored inputs.
            steps = [s for s in store.run_steps(run_id) if s["kind"] == "model:abstract_screening"]
            inputs = [store.step_input_payload(store.last_step_input(s["id"])["id"])
                      for s in steps if s["status"] == "succeeded"]
            common = set.intersection(*(set(c["candidate_id"] for c in si["candidates"]) for si in inputs))
            candidate = next(c["candidate_id"] for c in store.candidates(rid) if c["source_version_id"] == source)
            assert bool(decisions.proposals(rid, source, "abstract")) == (candidate in common)


@pytest.mark.parametrize("resend", ["rate_limit", "turn_timeout", "schema_repair"])
def test_reading_decision_blocks_resend_and_late_publication(tmp_path, monkeypatch, resend):
    monkeypatch.setattr(flow_module, "RATE_LIMIT_BACKOFF_SECONDS", 0)
    holder = {}

    def before(si):
        if si["task_type"] == "fulltext_adjudication" and not holder.get("source"):
            store = holder["app"].state.store
            source = sent_source(store, si)
            holder["source"] = source
            DecisionStore(store).record(si["research_id"], source, "human_criterion_not_met")

    def fail(si):
        if si["task_type"] != "fulltext_adjudication" or holder.get("failed"):
            return None
        holder["failed"] = True
        if resend == "rate_limit":
            return ModelStepResult("failed", error="429 Too Many Requests")
        if resend == "turn_timeout":
            return ModelStepResult("failed", error="client_timeout", delivery_class="after_send_unknown")
        return ModelStepResult("completed", raw_text="{", resolved_model="fake-model")

    works, fetcher = papers(1)
    adapter = FakeAdapter(valid_response, before=before, fail=fail)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter)
    holder["app"] = app
    with session(app) as client:
        rid, run_id, _, run = discover(client)
        store = app.state.store
        assert (run["status"], run["pause_reason"]) == ("paused", "selection_changed")
        assert len(adj_calls(adapter, run_id)) == 1
        decisions = DecisionStore(store)
        assert decisions.current(rid, holder["source"], "fulltext")["reason_code"] == "human_criterion_not_met"
        assert decisions.proposals(rid, holder["source"], "fulltext") == []
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
        assert wait(client, rid, run_id)[1]["status"] == "completed"
        assert len(adj_calls(adapter, run_id)) == 1


@pytest.mark.parametrize("phase,boundary", [
    ("abstract_screening", "health"), ("fulltext_adjudication", "health"),
    ("abstract_screening", "empty_batch"), ("fulltext_adjudication", "other_work"),
    ("fulltext_adjudication", "late_response"), ("abstract_screening", "next_batch"),
])
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


@pytest.mark.parametrize("undo_when", ["before_close", "while_paused"])
def test_reading_unsent_call_reopens_after_undo_without_repeating_saved_read(tmp_path, monkeypatch, undo_when):
    holder = {}
    def before(si):
        if si["task_type"] == "fulltext_adjudication" and not holder.get("source"):
            store = holder["app"].state.store
            holder.update(source=sent_source(store, si), rid=si["research_id"])
    def respond(si):
        if si["task_type"] == "fulltext_adjudication" and undo_when == "before_close" and holder.get("decided"):
            DecisionStore(holder["app"].state.store).undo_human(holder["rid"], holder["source"], "fulltext")
        return valid_response(si)
    adapter = FakeAdapter(respond, before=before, delay=0.05)
    health = adapter.health
    async def checked(refresh=False):
        if holder.get("source") and not holder.get("decided"):
            holder["decided"] = True
            DecisionStore(holder["app"].state.store).record(holder["rid"], holder["source"], "human_criterion_not_met")
        return await health(refresh)
    adapter.health = checked
    works, fetcher = papers(1)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter, concurrency=2)
    holder["app"] = app
    with session(app) as client:
        rid, run_id, _, paused = discover(client)
        store = app.state.store
        assert (paused["status"], paused["pause_reason"]) == ("paused", "selection_changed")
        assert len(adj_calls(adapter, run_id)) == 1
        assert not DecisionStore(store).proposals(rid, holder["source"], "fulltext")
        if undo_when == "while_paused":
            DecisionStore(store).undo_human(rid, holder["source"], "fulltext")
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
        assert wait(client, rid, run_id)[1]["status"] == "completed"
        assert [c["adjudication_target"]["run"] for c in adj_calls(adapter, run_id)] == [1, 2]
        assert DecisionStore(store).current(rid, holder["source"], "fulltext")["reason_code"] == "all_parts_verified"


@pytest.mark.parametrize("phase", ["abstract_screening", "fulltext_adjudication"])
def test_connection_check_decision_before_first_send_opens_no_input(tmp_path, monkeypatch, phase):
    holder = {}
    adapter = FakeAdapter(valid_response)
    health = adapter.health
    async def checked(refresh=False):
        app = holder["app"]
        flow, store = app.state.worker.flow, app.state.store
        guard = getattr(flow, "_small_batch_guard", None)
        if guard and not holder.get("source"):
            plans = [s for s in store.run_steps(guard["run_id"]) if s["kind"] == "code:adjudication_plan"]
            if phase == "abstract_screening" or any(s["status"] == "succeeded" and s["output"]["works"] for s in plans):
                source = next(iter(records_of(store, guard["rid"]).values()))
                DecisionStore(store).record(guard["rid"], source, "human_include")
                holder["source"] = source
        return await health(refresh)
    adapter.health = checked
    if phase == "abstract_screening":
        works, fetcher = [abstract_work(n) for n in range(3)], papers(0)[1]
    else:
        works, fetcher = papers(1)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, adapter=adapter,
                  fetch="off" if phase == "abstract_screening" else "auto")
    holder["app"] = app
    with session(app) as client:
        rid, run_id, _, paused = discover(client)
        assert (paused["status"], paused["pause_reason"]) == ("paused", "selection_changed")
        assert holder["source"]
        assert not [c for c in adapter.calls if c["task_type"] == phase]
        assert not app.state.store.conn.execute("SELECT 1 FROM step_inputs WHERE run_id = ? AND task_type = ?", (run_id, phase)).fetchone()
        assert not DecisionStore(app.state.store).proposals(rid, holder["source"], "abstract" if phase == "abstract_screening" else "fulltext")
