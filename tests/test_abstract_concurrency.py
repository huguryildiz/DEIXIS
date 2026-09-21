"""Slice 09 Task 5: an sw run sends its abstract screening calls through the run's shared limiter.

What is checked here is workflow behavior: how many calls are in flight at once, that concurrent sending writes the
decisions sequential sending writes, that a pause stops new submissions while the calls already sent finish and
record their steps, that the budget never sends half a batch, and that a rate-limited answer lowers the limit.
The pool, the titles and the abstracts are SYNTHETIC and from two fields, every transport is mocked and the model
is scripted: passing says nothing about how a real model labels an abstract.
"""

import json
from types import SimpleNamespace

from deixis.domain.rules import ABSTRACT_BATCH, ABSTRACT_RUNS
from deixis.models.adapter import ModelStepResult
from deixis.workflow import flow as flow_module
from deixis.workflow.flow import ResearchFlow
from fakes import FakeAdapter, envelope, valid_response
from test_abstract_flow import (Pool, app_for, client_of, codes_of, discover, records_of, responder,
                                selections_of, shown_titles, step_output, wait, work)

# Three batches of the standard read limit: 20, 20 and 4 works, so six calls go out for one run.
SIZE = 2 * ABSTRACT_BATCH + 4


def abstract_calls(adapter):
    return [si for si in adapter.calls if si["task_type"] == "abstract_screening"]


def screening_steps(store, run_id):
    return {s["operation_key"]: s["status"] for s in store.run_steps(run_id)
            if s["kind"] == "model:abstract_screening"}


def proposal_rows(store, rid):
    return store.conn.execute(
        "SELECT COUNT(*) FROM model_proposals WHERE research_id = ? AND stage = 'abstract'", (rid,)).fetchone()[0]


def screened(path, monkeypatch, concurrency, size=SIZE, effort="standard", adapter=None):
    """One sw discovery over a SYNTHETIC pool, read back after the run settles."""
    adapter = adapter or FakeAdapter(responder(), delay=0.01)
    app = app_for(path, monkeypatch, Pool([work(n) for n in range(size)]), adapter=adapter, concurrency=concurrency)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client, effort=effort)
        store = app.state.store
        return SimpleNamespace(run=run, adapter=adapter, plan=step_output(store, run_id, "abstract_stage"),
                               codes=codes_of(store, rid), selections=selections_of(store, rid),
                               titles=shown_titles(store, run_id), proposals=proposal_rows(store, rid),
                               steps=screening_steps(store, run_id))
    finally:
        client.__exit__(None, None, None)


# ---- the limit bounds the calls, and the decisions are the sequential ones ----------------------

def test_the_limit_bounds_the_calls_in_flight_and_the_decisions_are_the_sequential_ones(tmp_path, monkeypatch):
    sequential = screened(tmp_path / "seq", monkeypatch, concurrency=1)
    concurrent = screened(tmp_path / "con", monkeypatch, concurrency=3)

    assert sequential.adapter.max_concurrent == 1
    assert 1 < concurrent.adapter.max_concurrent <= 3
    assert len(abstract_calls(concurrent.adapter)) == len(abstract_calls(sequential.adapter)) == 6
    # Same plan, same batches, same records in front of the model, same decision table. (The stored plan names
    # each research's own record identifiers, so the batches are compared by what the model was shown.)
    assert concurrent.plan | {"batches": None} == sequential.plan | {"batches": None}
    assert [len(b) for b in concurrent.plan["batches"]] == [len(b) for b in sequential.plan["batches"]]
    assert sorted(concurrent.titles) == sorted(sequential.titles)  # the same works, each read twice
    assert concurrent.codes == sequential.codes and concurrent.selections == sequential.selections
    assert concurrent.proposals == sequential.proposals
    assert concurrent.steps == sequential.steps == {f"abstract_screening:{n}:{r}": "succeeded"
                                                    for n in range(3) for r in (1, 2)}


# ---- a pause while calls are in flight ----------------------------------------------------------

def test_a_pause_stops_new_submissions_and_the_calls_in_flight_write_their_steps(tmp_path, monkeypatch):
    """The calls already sent finish and record their steps; no batch is closed, and resuming calls only the rest."""
    holder, seen = {}, []

    def before(si):
        if si["task_type"] != "abstract_screening":
            return
        seen.append(si["step_id"])
        if len(seen) == 4:
            holder["store"].update_run(si["run_id"], event="run_pause_requested", status="pause_requested",
                                       pause_reason="user_requested")

    adapter = FakeAdapter(responder(), delay=0.02, before=before)
    app = app_for(tmp_path, monkeypatch, Pool([work(n) for n in range(SIZE)]), adapter=adapter, concurrency=4)
    client = client_of(app)
    try:
        store = holder["store"] = app.state.store
        rid, run_id, view, run = discover(client, effort="standard")
        paused_steps, paused_proposals = screening_steps(store, run_id), proposal_rows(store, rid)
        paused_calls = len(abstract_calls(adapter))
        client.post(f"/api/runs/{run_id}/resume")
        view, run = wait(client, rid, run_id)
        resumed_steps, codes = screening_steps(store, run_id), codes_of(store, rid)
        resumed_calls = len(abstract_calls(adapter))
    finally:
        client.__exit__(None, None, None)
    assert (run["status"], run["pause_reason"]) == ("completed", None)
    # The pause arrived during the fourth call: the four in flight finished and recorded their steps, and nothing
    # else was submitted. No batch was closed, so no record was decided from an answer the run did not keep.
    assert paused_calls == 4 and list(paused_steps.values()) == ["succeeded"] * 4
    assert paused_proposals == 0
    # Resuming called only the two missing runs: the four stored steps were read back, not asked again.
    assert resumed_calls == 6 and len(resumed_steps) == 6
    assert set(codes.values()) == {"runs_agree_candidate"}


# ---- the budget never sends half a batch --------------------------------------------------------

def test_the_budget_stops_before_a_batch_it_cannot_read_twice(tmp_path, monkeypatch):
    """Rule K3: a batch is read twice or not at all, and what the budget does not reach stays unread, not dropped."""
    original = ResearchFlow._abstract_stage

    async def one_batch_only(self, run, scope, vocabulary, order):
        # The run keeps every call it has already spent and is left room for exactly one batch.
        spent = self.store.run(run["id"])["usage"].get("model_calls", 0)
        run["budget"] = run["budget"] | {"max_model_calls": spent + ABSTRACT_RUNS}
        return await original(self, run, scope, vocabulary, order)

    monkeypatch.setattr(ResearchFlow, "_abstract_stage", one_batch_only)
    adapter = FakeAdapter(responder(), delay=0.01)
    app = app_for(tmp_path, monkeypatch, Pool([work(n) for n in range(SIZE)]), adapter=adapter, concurrency=4)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client, effort="standard")
        store = app.state.store
        plan, codes = step_output(store, run_id, "abstract_stage"), codes_of(store, rid)
        steps = screening_steps(store, run_id)
        failures = [s["error_code"] for s in store.run_steps(run_id) if s["status"] == "failed"]
        by_svid = {svid: key for key, svid in records_of(store, rid).items()}
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed" and "budget_exhausted" not in failures
    # Exactly one batch went out, both of its runs; the two batches behind it were not half-sent.
    assert len(abstract_calls(adapter)) == ABSTRACT_RUNS
    assert steps == {f"abstract_screening:0:{r}": "succeeded" for r in (1, 2)}
    read = {by_svid[svid] for svid in plan["batches"][0]}
    unread = {by_svid[svid] for later in plan["batches"][1:] for svid in later}
    assert {codes[key] for key in read} == {"runs_agree_candidate"}
    assert {codes[key] for key in unread} == {"abstract_not_read"}


# ---- one invalid run, and a rate-limited answer --------------------------------------------------

def test_one_invalid_run_closes_its_own_batch_and_leaves_the_others_decided(tmp_path, monkeypatch):
    """An invalid answer in flight beside three others costs its batch a decision, not the run."""
    def invalid_second_batch(si):
        if si["task_type"] != "abstract_screening":
            return valid_response(si)
        if si["screening_target"]["run"] == 1 and len(si["candidates"]) == ABSTRACT_BATCH and not spoiled:
            spoiled.append(si["step_id"])
            return json.dumps(envelope(si, "deixis.abstract_screening.v1") | {"records": [
                {"candidate_id": "cnd_C9999999", "label": "nonsense", "quote": "", "rationale": ""}]})
        return responder()(si)

    spoiled: list = []
    result = screened(tmp_path, monkeypatch, concurrency=4,
                      adapter=FakeAdapter(invalid_second_batch, delay=0.01))
    assert result.run["status"] == "completed"
    assert sorted(result.steps.values()) == ["failed"] + ["succeeded"] * 5
    unread = [key for key, code in result.codes.items() if code == "abstract_not_proposed"]
    assert len(unread) == ABSTRACT_BATCH
    assert {code for key, code in result.codes.items() if key not in unread} == {"runs_agree_candidate"}


def test_a_rate_limited_abstract_call_lowers_the_limit_and_is_resent(tmp_path, monkeypatch):
    monkeypatch.setattr(flow_module, "RATE_LIMIT_BACKOFF_SECONDS", 0)
    attempts = {"n": 0}

    def fail(si):
        if si["task_type"] != "abstract_screening":
            return None
        attempts["n"] += 1
        return ModelStepResult("failed", error="HTTP 429: Too Many Requests") if attempts["n"] == 1 else None

    adapter = FakeAdapter(responder(), fail=fail)
    app = app_for(tmp_path, monkeypatch, Pool([work(n) for n in range(SIZE)]), adapter=adapter, concurrency=4)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client, effort="standard")
        store = app.state.store
        codes = codes_of(store, rid)
        limit = app.state.worker.flow.deps.limiter.limit
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed"
    # The rate-limited call was resent under a lower ceiling instead of pausing the run.
    assert attempts["n"] == 7 and limit == 2
    assert set(codes.values()) == {"runs_agree_candidate"}
