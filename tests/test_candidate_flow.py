"""Synthetic K3 plumbing, not evidence that a model reads a work correctly.

Only FakeAdapter, scripted connectors and mocked HTTP transports are used.
"""
import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.domain import contracts
from deixis.domain.rules import RevisionConflict
from deixis.models.adapter import ModelStepResult
from deixis.models import prompt
from deixis.providers.common import SearchOutcome
from deixis.providers.registry import CONNECTORS
from deixis.storage import db
from deixis.workflow.candidates import run as candidates, terms
from deixis.workflow.candidates.store import CandidateStore
from deixis.workflow.views import research_view
from deixis.workflow.worker import Worker
from fakes import FakeAdapter, valid_response
from test_api_flow import session
from test_candidate_store import provider_record, version as edit_version
from test_lineage_plan import attach, make_env


class Crash(BaseException):
    """A synthetic process death, outside the worker's ordinary error handler."""


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr("deixis.workflow.flow.RATE_LIMIT_BACKOFF_SECONDS", 0)
    lib = make_env(tmp_path, n=2)
    lib.conn.execute("UPDATE scope_revisions SET providers_json = ? WHERE research_id = ?", ('["openalex"]', lib.rid))
    lib.candidate_store = CandidateStore(lib.store)
    lib.candidate = lib.candidate_store.open_from_owner_text(lib.rid, "SYNTHETIC buffering reduces delay.")
    lib.adapter = FakeAdapter()
    lib.flow.deps.adapters["fake"] = lib.adapter
    lib.planner = candidates.KillSearchPlanner(lib.store, lib.flow.deps.package.package_hash)
    lib.worker = Worker(lib.store, lib.flow, tmp_path / "unused.lock")
    lib.requests = []

    def provider(pid="openalex", outcomes=None, records=None):
        answers = iter(outcomes) if outcomes else None
        async def search(client, query, limit, key, contact, **kw):
            lib.requests.append((pid, query, limit, kw))
            return next(answers) if answers else SearchOutcome("completed", None, "SYNTHETIC mock", "keyless",
                records=records if records is not None else [provider_record()], raw_payload={"SYNTHETIC": True})
        monkeypatch.setitem(CONNECTORS, pid, replace(CONNECTORS[pid], search=search))
    lib.provider = provider
    provider()
    yield lib
    assert lib.seen == []
    asyncio.run(lib.http.aclose())
    lib.conn.close()


def queue_decompose(lib, key=None):
    run = candidates.request_decomposition(lib.store, lib.rid, lib.candidate["id"], key,
                                           skill_package_hash=lib.flow.deps.package.package_hash)
    lib.store.update_run(run["id"], status="running")
    return lib.store.run(run["id"])


def queue_kill(lib, key=None):
    if not lib.candidate_store.candidate(lib.candidate["id"])["current_version"]:
        edit_version(lib, lib.candidate)
    plan = lib.planner.preview(lib.rid, lib.candidate["id"])
    run = lib.planner.request_run(lib.rid, lib.candidate["id"], plan["preview_fingerprint"], key)
    lib.store.update_run(run["id"], status="running")
    return lib.store.run(run["id"])


def execute(lib, run):
    asyncio.run(lib.flow.execute(run["id"]))
    return lib.store.run(run["id"])


def resume(lib, run):
    lib.store.resume_run(run["id"])
    lib.store.update_run(run["id"], status="running")
    return execute(lib, lib.store.run(run["id"]))


def search(lib, run):
    return lib.candidate_store.search_for_run(run["id"])


def summary(lib, run):
    return lib.store.existing_step(run["id"], "kill_search_summary")["output"]


def status(lib, run):
    return lib.candidate_store.search_status(search(lib, run)["id"])


def stop(lib, run, mode):
    if mode == "scope":
        lib.store.revise_scope(lib.rid, lib.store.research(lib.rid)["version"], "SYNTHETIC new scope?", None)
    else:
        lib.store.update_run(run["id"], status="pause_requested" if mode == "pause" else "cancelled")


def supported(si, whole=False):
    result = json.loads(valid_response(si))
    result["work_relevance"] = "related"
    quote = {"passage_id": si["passages"][0]["passage_id"], "quote": si["passages"][0]["text"]}
    for cell in result["cells"]:
        cell.update(relation="explicit_support", condition_alignment="aligned", evidence=[quote])
    result.update(states_whole_claim=whole, whole_claim_evidence=[quote] if whole else [])
    return json.dumps(result)


@pytest.mark.parametrize("origin", ["owner_text", "report_gap"])
def test_decomposition_once_stores_version_one_with_the_real_step_input(lib, origin):
    if origin == "report_gap":
        report, gap = db.new_id("rpt"), db.new_id("gap")
        lib.conn.execute("INSERT INTO reports (id, research_id, run_id, scope_revision, status, created_at, updated_at)"
                         " VALUES (?, ?, ?, 1, 'draft', 'now', 'now')", (report, lib.rid, lib.run))
        lib.conn.execute("INSERT INTO report_gaps (id, report_id, gap_id, kind, text, basis_json, provenance_json, created_at)"
                         " VALUES (?, ?, ?, 'corpus_absence', 'SYNTHETIC gap', ?, '{}', 'now')",
                         (gap, report, gap, db.dumps({"basis_passage_ids": [lib.passages["a"]]})))
        lib.candidate = lib.candidate_store.open_from_gap(lib.rid, report, gap)
    run = queue_decompose(lib, "once")
    assert run["stage"] == "candidate"
    assert execute(lib, run)["status"] == "completed"
    version = lib.candidate_store.versions(lib.candidate["id"])[0]
    assert version["version"] == 1 and version["origin"] == "model_decomposition" and version["step_input_id"]
    assert (version["nearest_simple_explanation"] is None) == (origin == "owner_text")
    assert candidates.request_decomposition(lib.store, lib.rid, lib.candidate["id"], "once",
        skill_package_hash=lib.flow.deps.package.package_hash)["id"] == run["id"]
    with pytest.raises(RevisionConflict):
        candidates.request_decomposition(lib.store, lib.rid, lib.candidate["id"],
                                         skill_package_hash=lib.flow.deps.package.package_hash)


def test_owner_edit_during_decomposition_refuses_publication_and_never_retries(lib):
    run = queue_decompose(lib)
    lib.adapter.before = lambda si: edit_version(lib, lib.candidate)
    assert execute(lib, run)["pause_reason"] == "candidate_version_changed"
    assert [v["origin"] for v in lib.candidate_store.versions(lib.candidate["id"])] == ["human_edit"]
    assert len(lib.adapter.calls) == 1


@pytest.mark.parametrize("task", ["claim_decomposition", "claim_assessment"])
@pytest.mark.parametrize("mode", ["pause", "cancel", "scope"])
def test_in_flight_stop_publishes_no_decomposition_or_assessment(lib, task, mode):
    run = queue_decompose(lib) if task == "claim_decomposition" else queue_kill(lib)
    lib.adapter.before = lambda si: stop(lib, run, mode) if si["task_type"] == task else None
    result = execute(lib, run)
    assert result["status"] == ("paused" if mode == "pause" else "cancelled")
    if task == "claim_decomposition":
        assert lib.candidate_store.versions(lib.candidate["id"]) == []
    else:
        assert lib.candidate_store.cells(search(lib, run)["id"]) == []
        assert search(lib, run)["outcome"] == ("paused" if mode == "pause" else "stopped")


def test_kill_search_end_to_end_freezes_and_assesses_without_touching_discovery(lib, monkeypatch):
    tables = ("corpus_memberships", "candidates", "search_runs", "selections", "report_gaps")
    before = {t: [tuple(r) for r in lib.conn.execute(f"SELECT * FROM {t}")] for t in tables}
    revision = lib.store.research(lib.rid)["selection_revision"]
    view_before = research_view(lib.store, lib.rid)
    other_steps = lib.store.run_steps(lib.run)
    def forbidden(*args, **kw):
        raise AssertionError("Candidate flow crossed the corpus boundary")
    for name in ("record_search", "add_search_run", "add_to_corpus"):
        monkeypatch.setattr(lib.store, name, forbidden)
    monkeypatch.setattr("deixis.workflow.links.link_records", forbidden)
    run = queue_kill(lib)
    assert execute(lib, run)["status"] == "completed"
    frozen = search(lib, run)
    assert frozen["outcome"] == "completed"
    assert json.loads(frozen["selection_json"]) == {k: run["target"][k] for k in ("model", "providers", "budget", "transport")}
    assert len(json.loads(frozen["rendered_queries_json"])) == len(lib.requests) == 1
    assert lib.requests[0][2:] == (20, {})
    assert lib.candidate_store.hits(frozen["id"])[0]["assessment_state"] == "assessed"
    assert status(lib, run)["status"] == "open"
    assert summary(lib, run)["hits"][0]["outcome"] == "assessed"
    assert lib.store.research(lib.rid)["selection_revision"] == revision
    assert {t: [tuple(r) for r in lib.conn.execute(f"SELECT * FROM {t}")] for t in tables} == before
    assert lib.store.run_steps(lib.run) == other_steps
    view_after = research_view(lib.store, lib.rid)
    assert view_after["counts"] == view_before["counts"]
    assert any(r["id"] == run["id"] for r in view_after["runs"])


@pytest.mark.parametrize("answers,expected,reason", [
    (["failed", "completed"], "open", "no_match_in_assessed_subset"),
    (["failed", "failed"], "undecided", "search_failed"),
    (["zero_results", "zero_results"], "open", "no_match_in_assessed_subset"),
    (["zero_results", "timeout"], "undecided", "query_outcome_unknown")])
def test_d18_failures_continue_and_unknown_delivery_cannot_become_open(lib, answers, expected, reason):
    lib.conn.execute("UPDATE scope_revisions SET providers_json = ? WHERE research_id = ?", ('["openalex", "pubmed"]', lib.rid))
    for pid, answer in zip(("openalex", "pubmed"), answers):
        lib.provider(pid, outcomes=[SearchOutcome(answer, "after_send_unknown" if answer == "timeout" else None,
                                                "SYNTHETIC", "keyless", raw_payload={"answer": answer})])
    run = queue_kill(lib)
    assert execute(lib, run)["status"] == "completed"
    assert len(lib.requests) == 2
    assert (status(lib, run)["status"], status(lib, run)["reason"]) == (expected, reason)
    if "timeout" in answers:
        q = lib.candidate_store.queries(search(lib, run)["id"])[1]
        assert q["status"] == "outcome_unknown" and q["error_code"] == "timeout" and q["record_count"] == 0
    if expected == "open":
        assert status(lib, run)["facts"]["unread"] == 0


def test_metadata_only_hit_is_insufficient_access_and_never_sent(lib):
    lib.provider(records=[provider_record(abstract=None)])
    run = queue_kill(lib)
    execute(lib, run)
    assert [c["task_type"] for c in lib.adapter.calls] == ["kill_search_query"]
    h = lib.candidate_store.hits(search(lib, run)["id"])[0]
    assert (h["reading_depth"], h["assessment_state"]) == ("metadata_only", "insufficient_access")
    assert status(lib, run)["status"] == "undecided"


@pytest.mark.parametrize("task", ["claim_decomposition", "kill_search_query", "claim_assessment"])
def test_terminal_invalid_output_has_one_repair_and_is_never_resent_on_resume(lib, task):
    lib.adapter.responder = lambda si: "{}" if si["task_type"] == task else valid_response(si)
    run = queue_decompose(lib) if task == "claim_decomposition" else queue_kill(lib)
    execute(lib, run)
    assert sum(c["task_type"] == task for c in lib.adapter.calls) == 2
    if task == "claim_assessment":
        assert status(lib, run)["status"] == "undecided"
        assert summary(lib, run)["hits"][0]["outcome"] == "invalid_output"
        assert lib.candidate_store.hits(search(lib, run)["id"])[0]["assessment_state"] == "pending"
        # Recreate the crash window before finish, so the terminal step is visited.
        return
    assert search(lib, run) is None
    lib.store.update_run(run["id"], status="paused")
    resume(lib, run)
    assert sum(c["task_type"] == task for c in lib.adapter.calls) == 2
    assert lib.store.run(run["id"])["pause_reason"] == ("invalid_model_output" if task == "claim_decomposition" else "query_terms_invalid")


@pytest.mark.parametrize("task", ["claim_decomposition", "kill_search_query", "claim_assessment"])
@pytest.mark.parametrize("mode", ["pause", "crash"])
def test_invalid_first_answer_resume_keeps_exactly_one_repair_total(lib, monkeypatch, task, mode):
    run = queue_decompose(lib) if task == "claim_decomposition" else queue_kill(lib)
    lib.adapter.responder = lambda si: "{}" if si["task_type"] == task and sum(c["task_type"] == task for c in lib.adapter.calls) == 1 else valid_response(si)
    original = lib.store.finish_model_session
    fired = False
    def finish(id_, **fields):
        nonlocal fired
        original(id_, **fields)
        if not fired and (fields.get("validation_json") or {}).get("ok") is False:
            fired = True
            if mode == "crash":
                raise Crash
            lib.store.update_run(run["id"], status="pause_requested")
    monkeypatch.setattr(lib.store, "finish_model_session", finish)
    if mode == "crash":
        with pytest.raises(Crash):
            execute(lib, run)
        lib.worker.recover()
        lib.candidate_store.sync_search_outcome(run["id"])
    else:
        assert execute(lib, run)["status"] == "paused"
    assert resume(lib, run)["status"] == "completed"
    assert sum(c["task_type"] == task for c in lib.adapter.calls) == 2


def test_transport_refusal_after_zero_results_is_durable_failed_and_not_open(lib):
    lib.conn.execute("UPDATE scope_revisions SET providers_json = ? WHERE research_id = ?", ('["openalex", "pubmed"]', lib.rid))
    lib.provider(outcomes=[SearchOutcome("zero_results", None, "SYNTHETIC", "keyless")])
    lib.provider("pubmed")
    run = queue_kill(lib)
    budget = dict(run["budget"], max_provider_requests=3)
    lib.conn.execute("UPDATE runs SET budget_json = ? WHERE id = ?", (db.dumps(budget), run["id"]))
    run = lib.store.run(run["id"])
    assert execute(lib, run)["pause_reason"] == "transport_budget"
    assert len(lib.requests) == 1
    assert search(lib, run)["outcome"] == "failed"
    assert status(lib, run)["status"] == "undecided"
    assert summary(lib, run)["failure_code"] == "transport_budget"


def test_before_send_retries_reserve_the_full_pubmed_attempt_but_never_refund(lib):
    lib.conn.execute("UPDATE scope_revisions SET providers_json = ? WHERE research_id = ?", ('["pubmed"]', lib.rid))
    failure = SearchOutcome("failed", "before_send", "SYNTHETIC connection failure", "keyless")
    success = SearchOutcome("zero_results", None, "SYNTHETIC", "keyless")
    lib.provider("pubmed", outcomes=[failure, failure, success])
    run = queue_kill(lib)
    result = execute(lib, run)
    assert result["usage"]["provider_requests"] == 6 * len(lib.requests)
    assert result["usage"]["provider_requests"] <= run["budget"]["max_provider_requests"]


def test_provider_reservation_survives_crash_before_any_response_write(lib):
    async def crash(*args, **kw):
        lib.requests.append("sent")
        raise Crash
    lib.provider()
    original = CONNECTORS["openalex"]
    CONNECTORS["openalex"] = replace(original, search=crash)
    try:
        run = queue_kill(lib)
        with pytest.raises(Crash):
            execute(lib, run)
        assert lib.store.run(run["id"])["usage"]["provider_requests"] == 3
        assert lib.candidate_store.queries(search(lib, run)["id"]) == []
        lib.worker.recover()
        lib.candidate_store.sync_search_outcome(run["id"])
        assert search(lib, run)["outcome"] == "paused"
        CONNECTORS["openalex"] = original
        assert resume(lib, run)["status"] == "completed"
        assert lib.requests == ["sent"]
        assert lib.candidate_store.queries(search(lib, run)["id"])[0]["status"] == "outcome_unknown"
        assert lib.store.run(run["id"])["usage"]["provider_requests"] == 3
    finally:
        CONNECTORS["openalex"] = original


@pytest.mark.parametrize("window", ["plan", "hits", "completed"])
def test_crash_windows_resume_without_recompiling_remerging_or_reopening(lib, monkeypatch, window):
    run = queue_kill(lib)
    cs = lib.candidate_store
    # Flow creates another store wrapper, so patch the class seam.
    method = "record_hits" if window in ("plan", "hits") else "finish_kill_search"
    original = getattr(CandidateStore, method)
    fired = False
    def die(self, *args, **kw):
        nonlocal fired
        if not fired:
            fired = True
            if window != "plan":
                original(self, *args, **kw)
            raise Crash
        return original(self, *args, **kw)
    monkeypatch.setattr(CandidateStore, method, die)
    with pytest.raises(Crash):
        execute(lib, run)
    frozen = search(lib, run)
    lib.worker.recover()
    cs.sync_search_outcome(run["id"])
    def forbidden(*args, **kw):
        raise AssertionError("A frozen plan was rebuilt")
    monkeypatch.setattr(terms, "compile_queries", forbidden)
    monkeypatch.setattr("deixis.workflow.candidates.hits.merge_and_cut", forbidden)
    assert resume(lib, run)["status"] == "completed"
    resumed = search(lib, run)
    assert [resumed[k] for k in ("selection_json", "rendered_queries_json", "skipped_terms_json")] == [frozen[k] for k in ("selection_json", "rendered_queries_json", "skipped_terms_json")]
    assert len(lib.requests) == 1
    assert len(cs.hits(frozen["id"])) == 1


@pytest.mark.parametrize("failure_code", ["no_query_compiled", "candidate_evidence_unlocated", "transport_budget", "skill_package_changed"])
def test_terminal_failed_search_resume_carries_exact_persisted_code(lib, monkeypatch, failure_code):
    run = queue_kill(lib)
    package = lib.flow.deps.package
    if failure_code == "no_query_compiled":
        monkeypatch.setattr(terms, "compile_queries", lambda *args: [])
    elif failure_code == "candidate_evidence_unlocated":
        lib.adapter.responder = lambda si: supported(si) if si["task_type"] == "claim_assessment" else valid_response(si)
        monkeypatch.setattr(contracts, "claim_assessment_evidence", lambda *args: None)
    elif failure_code == "skill_package_changed":
        original_query = CandidateStore.record_query
        def change_package(self, *args, **kw):
            result = original_query(self, *args, **kw)
            lib.flow.deps.package = replace(package, package_hash="sha256:" + "0" * 64)
            return result
        monkeypatch.setattr(CandidateStore, "record_query", change_package)
    else:
        lib.store.add_usage(run["id"], "provider_requests", run["budget"]["max_provider_requests"])
    original = CandidateStore.finish_kill_search
    def crash(self, id_, outcome):
        result = original(self, id_, outcome)
        assert lib.store.run(run["id"])["status"] == "running"
        assert summary(lib, run)["failure_code"] == failure_code
        raise Crash
    monkeypatch.setattr(CandidateStore, "finish_kill_search", crash)
    with pytest.raises(Crash):
        execute(lib, run)
    assert search(lib, run)["outcome"] == "failed"
    lib.worker.recover()
    lib.flow.deps.package = package
    sent = len(lib.adapter.calls), len(lib.requests)
    result = resume(lib, run)
    assert (result["status"], result["pause_reason"]) == ("failed", failure_code)
    assert (len(lib.adapter.calls), len(lib.requests)) == sent


def test_unlocated_evidence_fails_closed_for_the_whole_search(lib, monkeypatch):
    lib.adapter.responder = lambda si: supported(si) if si["task_type"] == "claim_assessment" else valid_response(si)
    monkeypatch.setattr(contracts, "claim_assessment_evidence", lambda *args: None)
    run = queue_kill(lib)
    assert execute(lib, run)["pause_reason"] == "candidate_evidence_unlocated"
    assert lib.candidate_store.cells(search(lib, run)["id"]) == []
    assert search(lib, run)["outcome"] == "failed"


def test_located_source_words_and_abstract_quote_kind_are_published(lib):
    lib.provider(records=[provider_record(abstract="SYNTHETIC: buffering increases delay under bounded arrivals.")])
    def response(si):
        if si["task_type"] != "claim_assessment":
            return valid_response(si)
        result = json.loads(supported(si, whole=True))
        for cell in result["cells"]:
            cell["evidence"][0]["quote"] = cell["evidence"][0]["quote"].replace("increases", "decreases")
        result["whole_claim_evidence"][0]["quote"] = result["whole_claim_evidence"][0]["quote"].replace("increases", "decreases")
        return json.dumps(result)
    lib.adapter.responder = response
    run = queue_kill(lib)
    execute(lib, run)
    evidence = lib.candidate_store.evidence(search(lib, run)["id"])
    assert evidence and all("increases" in e["quote"] and "decreases" not in e["quote"] for e in evidence)
    assert all(e["evidence_kind"] == "abstract" and e["passage_id"] is None for e in evidence)
    assert status(lib, run)["status"] == "closed"


def test_manual_resume_resends_an_unknown_model_step_once_with_existing_counter(lib):
    fired = False
    def fail(si):
        nonlocal fired
        if si["task_type"] == "claim_assessment" and not fired:
            fired = True
            return ModelStepResult("timeout", error="SYNTHETIC timeout", delivery_class="after_send_unknown")
    lib.adapter.fail = fail
    run = queue_kill(lib)
    assert execute(lib, run)["status"] == "paused"
    assert lib.store.run(run["id"])["usage"]["model_calls"] == 2
    assert resume(lib, run)["status"] == "completed"
    assert lib.store.run(run["id"])["usage"]["model_calls"] == 3
    assert len(lib.requests) == 1


@pytest.mark.parametrize("change", ["text", "gone"])
def test_changed_frozen_passage_invalidates_whole_unassessed_hit_and_keeps_depth(lib, monkeypatch, change):
    run = queue_kill(lib)
    original = CandidateStore.record_hits
    def pause(self, *args, **kw):
        original(self, *args, **kw)
        lib.store.update_run(run["id"], status="pause_requested")
    monkeypatch.setattr(CandidateStore, "record_hits", pause)
    assert execute(lib, run)["status"] == "paused"
    svid = lib.candidate_store.hits(search(lib, run)["id"])[0]["source_version_id"]
    pid = lib.store.passages_for(svid)[0]["id"]
    # Passage rows are immutable; simulate a changed/corrupt reader snapshot
    # rather than disabling the storage trigger to fabricate this failure.
    original_rows = lib.store.passages_for
    monkeypatch.setattr(lib.store, "passages_for", lambda sid: original_rows(sid) if sid != svid else
        [dict(p, text="SYNTHETIC changed") for p in original_rows(sid)] if change == "text" else [])
    assert resume(lib, run)["status"] == "completed"
    hit = lib.candidate_store.hits(search(lib, run)["id"])[0]
    assert (hit["reading_depth"], hit["assessment_state"]) == ("abstract", "insufficient_access")
    assert [c["task_type"] for c in lib.adapter.calls] == ["kill_search_query"]
    assert summary(lib, run)["frozen_reading_depth"] is True


def test_succeeded_assessment_is_published_from_stored_input_before_live_text_check(lib, monkeypatch):
    run = queue_kill(lib)
    lib.adapter.before = lambda si: stop(lib, run, "pause") if si["task_type"] == "claim_assessment" else None
    assert execute(lib, run)["status"] == "paused"
    hit = lib.candidate_store.hits(search(lib, run)["id"])[0]
    original_rows = lib.store.passages_for
    monkeypatch.setattr(lib.store, "passages_for", lambda sid: [dict(p, text="SYNTHETIC changed later") for p in original_rows(sid)])
    lib.adapter.before = None
    assert resume(lib, run)["status"] == "completed"
    assert len(lib.adapter.calls) == 2
    evidence = candidates.candidate_evidence(lib.store, lib.rid, lib.candidate["id"], search(lib, run)["id"], hit["source_version_id"])
    assert evidence["passages"][0]["text"] != "SYNTHETIC changed later"


def test_model_ceiling_54_mid_assessment_leaves_remaining_hits_pending_without_renewal(lib, monkeypatch):
    lib.provider(records=[provider_record(str(i)) for i in range(3)])
    run = queue_kill(lib)
    original = CandidateStore.record_hits
    def pause(self, *args, **kw):
        original(self, *args, **kw)
        lib.store.add_usage(run["id"], "model_calls", 52)
        lib.store.update_run(run["id"], status="pause_requested")
    monkeypatch.setattr(CandidateStore, "record_hits", pause)
    execute(lib, run)
    assert lib.store.run(run["id"])["usage"]["model_calls"] == 53
    result = resume(lib, run)
    assert result["usage"]["model_calls"] == 54 and result["status"] == "completed"
    kept = lib.candidate_store.hits(search(lib, run)["id"])
    assert [h["assessment_state"] for h in kept] == ["assessed", "pending", "pending"]
    assert [h["outcome"] for h in summary(lib, run)["hits"]] == ["assessed", "not_reached_budget", "not_reached_budget"]


def test_rate_limit_resend_guard_blocks_every_send_past_the_model_ceiling(lib):
    run = queue_kill(lib)
    def fail(si):
        if si["task_type"] == "claim_assessment":
            lib.store.add_usage(run["id"], "model_calls", 52)
            return ModelStepResult("failed", error="HTTP 429 rate limited", resolved_model="fake-model")
    lib.adapter.fail = fail
    execute(lib, run)
    assert len(lib.adapter.calls) == 2
    assert lib.store.run(run["id"])["usage"]["model_calls"] == 54
    assert lib.candidate_store.hits(search(lib, run)["id"])[0]["assessment_state"] == "pending"


@pytest.mark.parametrize("kind", ["claim_decomposition", "kill_search"])
def test_candidate_dispatch_never_reaches_table_columns(lib, monkeypatch, kind):
    async def forbidden(*args):
        raise AssertionError("Candidate dispatched as table columns")
    monkeypatch.setattr(lib.flow, "_table_columns", forbidden)
    run = queue_decompose(lib) if kind == "claim_decomposition" else queue_kill(lib)
    assert run["stage"] == "candidate" and execute(lib, run)["status"] == "completed"


@pytest.mark.parametrize("paused_kind,active_kind", [("answer", "kill_search"), ("lineage_links", "claim_decomposition"),
                                                     ("kill_search", "answer"), ("claim_decomposition", "lineage_links")])
def test_shared_api_resume_guard_refuses_a_second_active_run_in_both_directions(lib, paused_kind, active_kind):
    app = create_app(lib.flow.deps.settings, adapters={"fake": lib.adapter}, http_client=lib.http, start_worker=False,
                     trusted_clients=("testclient",))
    with TestClient(app, base_url="http://127.0.0.1:8872") as client:
        session(client)
        store = app.state.store
        rid = store.create_research("SYNTHETIC", "attached", "quick", [], "fake", "fake-model", "en")
        paused = store.create_run(rid, paused_kind, {"max_model_calls": 6, "max_provider_requests": 0}, None)
        store.update_run(paused["id"], status="paused")
        store.add_usage(paused["id"], "model_calls", 3)
        active = store.create_run(rid, active_kind, {"max_model_calls": 6, "max_provider_requests": 0}, None)
        assert client.post(f"/api/runs/{paused['id']}/resume").status_code == 409
        store.update_run(active["id"], status="cancelled")
        assert client.post(f"/api/runs/{paused['id']}/resume").status_code == 200
        assert store.run(paused["id"])["usage"]["model_calls"] == 3


def test_new_kill_search_refuses_paused_candidate_run_or_another_active_run(lib):
    run = queue_kill(lib)
    plan = run["target"]
    with pytest.raises(RevisionConflict):
        lib.planner.request_run(lib.rid, lib.candidate["id"], plan["preview_fingerprint"])
    lib.store.update_run(run["id"], status="paused")
    with pytest.raises(RevisionConflict):
        lib.planner.request_run(lib.rid, lib.candidate["id"], plan["preview_fingerprint"])


def test_candidate_read_sync_is_an_idempotent_write_after_worker_recovery(lib, monkeypatch):
    run = queue_kill(lib)
    original = CandidateStore.record_hits
    def die(self, *args, **kw):
        original(self, *args, **kw)
        raise Crash
    monkeypatch.setattr(CandidateStore, "record_hits", die)
    with pytest.raises(Crash):
        execute(lib, run)
    lib.worker.recover()
    assert search(lib, run)["outcome"] == "running"
    lib.candidate_store.sync_search_outcome(run["id"])
    events = lib.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    lib.candidate_store.sync_search_outcome(run["id"])
    assert lib.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == events
    assert search(lib, run)["outcome"] == "paused"


@pytest.mark.parametrize("kind", ["connection", "terms"])
def test_failure_before_query_freeze_writes_no_search_and_keeps_not_run(lib, monkeypatch, kind):
    run = queue_kill(lib)
    if kind == "connection":
        lib.adapter.ready = False
    else:
        def invalid(*args):
            raise terms.InvalidTerms("SYNTHETIC bad vocabulary")
        monkeypatch.setattr(terms, "block_vocabulary", invalid)
    result = execute(lib, run)
    assert result["status"] == "failed" and search(lib, run) is None
    version = lib.candidate_store.versions(lib.candidate["id"])[-1]
    assert lib.candidate_store.candidate_status(version["id"])["computed"]["status"] == "not_run"
    assert lib.requests == []


def test_abstract_alone_too_large_leaves_pending_hit_without_a_model_send(lib, monkeypatch):
    run = queue_kill(lib)
    original = prompt.step_message
    def oversized(payload):
        text = original(payload)
        return text + "x" * candidates.MAX_MESSAGE_CHARS if payload["task_type"] == "claim_assessment" else text
    monkeypatch.setattr(prompt, "step_message", oversized)
    result = execute(lib, run)
    assert result["status"] == "completed" and len(lib.adapter.calls) == 1
    hit = lib.candidate_store.hits(search(lib, run)["id"])[0]
    assert (hit["reading_depth"], hit["assessment_state"]) == ("abstract", "pending")
    assert summary(lib, run)["hits"][0]["outcome"] == "message_too_large"
    assert status(lib, run)["status"] == "undecided"


def test_oversized_repair_leaves_pending_and_is_never_resent_on_resume(lib, monkeypatch):
    run = queue_kill(lib)
    lib.adapter.responder = lambda si: "{}" if si["task_type"] == "claim_assessment" else valid_response(si)
    original = prompt.repair_message
    monkeypatch.setattr(prompt, "repair_message", lambda *args, **kw: original(*args, **kw) + "x" * candidates.MAX_MESSAGE_CHARS)
    original_finish = lib.flow._kill_search_finish
    fired = False
    def pause(*args, **kw):
        nonlocal fired
        if not fired:
            fired = True
            lib.store.update_run(run["id"], status="pause_requested")
        return original_finish(*args, **kw)
    monkeypatch.setattr(lib.flow, "_kill_search_finish", pause)
    assert execute(lib, run)["status"] == "paused"
    assert sum(c["task_type"] == "claim_assessment" for c in lib.adapter.calls) == 1
    assert resume(lib, run)["status"] == "completed"
    assert sum(c["task_type"] == "claim_assessment" for c in lib.adapter.calls) == 1
    assert summary(lib, run)["hits"][0]["outcome"] == "message_too_large"
    assert lib.candidate_store.hits(search(lib, run)["id"])[0]["assessment_state"] == "pending"


def test_terminal_invalid_assessment_is_not_sent_again_after_pause_before_finish(lib, monkeypatch):
    run = queue_kill(lib)
    lib.adapter.responder = lambda si: "{}" if si["task_type"] == "claim_assessment" else valid_response(si)
    original = lib.flow._kill_search_finish
    fired = False
    def pause(*args, **kw):
        nonlocal fired
        if not fired:
            fired = True
            lib.store.update_run(run["id"], status="pause_requested")
        return original(*args, **kw)
    monkeypatch.setattr(lib.flow, "_kill_search_finish", pause)
    assert execute(lib, run)["status"] == "paused"
    assert resume(lib, run)["status"] == "completed"
    assert sum(c["task_type"] == "claim_assessment" for c in lib.adapter.calls) == 2
    assert summary(lib, run)["hits"][0]["outcome"] == "invalid_output"


def test_pause_after_failed_provider_query_never_resends_it_and_uses_frozen_queries(lib, monkeypatch):
    lib.conn.execute("UPDATE scope_revisions SET providers_json = ? WHERE research_id = ?", ('["openalex", "pubmed"]', lib.rid))
    lib.provider(outcomes=[SearchOutcome("rate_limited", "rejected_not_executed", "SYNTHETIC", "keyless")])
    lib.provider("pubmed")
    run = queue_kill(lib)
    original = CandidateStore.record_query
    def pause(self, *args, **kw):
        result = original(self, *args, **kw)
        if kw["position"] == 1:
            lib.store.update_run(run["id"], status="pause_requested")
        return result
    monkeypatch.setattr(CandidateStore, "record_query", pause)
    assert execute(lib, run)["status"] == "paused"
    frozen = search(lib, run)
    monkeypatch.setattr(terms, "compile_queries", lambda *args: pytest.fail("Recompiled frozen query terms"))
    assert resume(lib, run)["status"] == "completed"
    assert [r[0] for r in lib.requests] == ["openalex", "pubmed"]
    assert search(lib, run)["rendered_queries_json"] == frozen["rendered_queries_json"]


def test_cancel_preserves_already_published_hits_and_never_publishes_late_results(lib):
    lib.provider(records=[provider_record(str(i)) for i in range(2)])
    run = queue_kill(lib)
    def before(si):
        if si["task_type"] == "claim_assessment" and sum(c["task_type"] == "claim_assessment" for c in lib.adapter.calls) == 2:
            lib.store.update_run(run["id"], status="cancelled")
    lib.adapter.before = before
    assert execute(lib, run)["status"] == "cancelled"
    assert search(lib, run)["outcome"] == "stopped"
    hits = lib.candidate_store.hits(search(lib, run)["id"])
    assert [h["assessment_state"] for h in hits] == ["assessed", "pending"]
    assert len(lib.candidate_store.cells(search(lib, run)["id"])) == 2


def test_endpoint_options_are_forwarded_but_paging_probe_and_enrichment_are_absent(lib):
    lib.conn.execute("UPDATE scope_revisions SET providers_json = ? WHERE research_id = ?", ('["semantic_scholar"]', lib.rid))
    lib.provider("semantic_scholar")
    run = queue_kill(lib)
    execute(lib, run)
    queries = json.loads(search(lib, run)["rendered_queries_json"])
    assert lib.requests[0][3] == {k: queries[0][k] for k in ("endpoint", "sort")}
    assert lib.requests[0][2] == 20


def test_real_openalex_connector_through_mocked_http_makes_only_one_request(lib):
    from deixis.providers import openalex
    calls = []
    def transport(request):
        calls.append(request)
        return httpx.Response(200, json={"results": [], "meta": {"count": 0}})
    CONNECTORS["openalex"] = replace(CONNECTORS["openalex"], search=openalex.search_works)
    asyncio.run(lib.http.aclose())
    lib.http = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    lib.flow.deps.http = lib.http
    run = queue_kill(lib)
    assert execute(lib, run)["status"] == "completed"
    assert len(calls) == 1 and "cursor" not in calls[0].url.params
    assert int(calls[0].url.params["per_page"]) == 20
    assert status(lib, run)["status"] == "open"


@pytest.mark.parametrize("mode", ["pause", "cancel", "scope"])
@pytest.mark.parametrize("answer", ["timeout", "zero_results"])
def test_provider_answer_during_stop_is_recorded_before_gate_and_never_resent(lib, monkeypatch, mode, answer):
    from deixis.providers import openalex, pubmed
    lib.conn.execute("UPDATE scope_revisions SET providers_json = ? WHERE research_id = ?",
                     ('["openalex", "pubmed"]', lib.rid))
    monkeypatch.setitem(CONNECTORS, "openalex", replace(CONNECTORS["openalex"], search=openalex.search_works))
    monkeypatch.setitem(CONNECTORS, "pubmed", replace(CONNECTORS["pubmed"], search=pubmed.search))
    run = queue_kill(lib)
    requests = []
    def transport(request):
        requests.append(request)
        if request.url.host == "api.openalex.org":
            stop(lib, run, mode)
            if answer == "timeout":
                raise httpx.ReadTimeout("SYNTHETIC uncertain delivery", request=request)
            return httpx.Response(200, json={"results": [], "meta": {"count": 0}})
        assert request.url.host == "eutils.ncbi.nlm.nih.gov"
        return httpx.Response(200, json={"esearchresult": {"count": "0", "idlist": []}})
    asyncio.run(lib.http.aclose())
    lib.http = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    lib.flow.deps.http = lib.http
    result = execute(lib, run)
    assert result["status"] == ("paused" if mode == "pause" else "cancelled")
    frozen = search(lib, run)
    queries = lib.candidate_store.queries(frozen["id"])
    expected = "outcome_unknown" if answer == "timeout" else "succeeded"
    assert len(queries) == 1 and queries[0]["status"] == expected
    step = lib.store.existing_step(run["id"], "search:1")
    assert step["status"] == expected
    assert step["delivery_class"] == ("after_send_unknown" if answer == "timeout" else None)
    assert len(requests) == 1
    assert frozen["outcome"] == ("paused" if mode == "pause" else "stopped")
    if mode == "pause":
        assert resume(lib, run)["status"] == "completed"
        assert [r.url.host for r in requests] == ["api.openalex.org", "eutils.ncbi.nlm.nih.gov"]
        assert [q["status"] for q in lib.candidate_store.queries(frozen["id"])] == [expected, "succeeded"]
        computed = status(lib, run)
        assert computed["status"] == ("undecided" if answer == "timeout" else "open")
        if answer == "timeout":
            assert computed["reason"] == "query_outcome_unknown"
    else:
        assert lib.store.existing_step(run["id"], "kill_search_plan") is None
        assert lib.candidate_store.hits(frozen["id"]) == []


def test_provider_answer_is_not_recorded_into_already_terminal_search(lib, monkeypatch):
    run = queue_kill(lib)
    async def terminal(*args, **kw):
        lib.requests.append("sent")
        stop(lib, run, "cancel")
        lib.candidate_store.sync_search_outcome(run["id"])
        return SearchOutcome("zero_results", None, "SYNTHETIC", "keyless", raw_payload={"SYNTHETIC": True})
    monkeypatch.setitem(CONNECTORS, "openalex", replace(CONNECTORS["openalex"], search=terminal))
    assert execute(lib, run)["status"] == "cancelled"
    assert search(lib, run)["outcome"] == "stopped"
    assert lib.candidate_store.queries(search(lib, run)["id"]) == []
    step = lib.store.existing_step(run["id"], "search:1")
    assert not (lib.flow.deps.settings.payloads_dir / f"{step['id']}.json").exists()
    assert lib.requests == ["sent"]


@pytest.mark.parametrize("kind", ["claim_decomposition", "kill_search"])
@pytest.mark.parametrize("window", ["before_send", "during_model", "resume"])
def test_changed_package_fails_candidate_run_without_further_sends(lib, kind, window):
    run = queue_decompose(lib) if kind == "claim_decomposition" else queue_kill(lib)
    assert run["target"]["skill_package_hash"] == lib.flow.deps.package.package_hash
    def change():
        lib.flow.deps.package = replace(lib.flow.deps.package, package_hash="sha256:" + "0" * 64)
    if window == "before_send":
        change()
        result = execute(lib, run)
        assert lib.adapter.calls == []
    elif window == "during_model":
        lib.adapter.before = lambda si: change()
        result = execute(lib, run)
        assert len(lib.adapter.calls) == 1
    else:
        lib.adapter.before = lambda si: stop(lib, run, "pause")
        assert execute(lib, run)["status"] == "paused"
        change()
        lib.adapter.before = None
        result = resume(lib, run)
        assert len(lib.adapter.calls) == 1
    assert result["status"] == "failed" and result["pause_reason"] == "skill_package_changed"
    assert lib.requests == []
    if kind == "claim_decomposition":
        assert lib.candidate_store.versions(lib.candidate["id"]) == []
    else:
        assert search(lib, run) is None


@pytest.mark.parametrize("kind", ["claim_decomposition", "kill_search"])
@pytest.mark.parametrize("reply", ["invalid", "rate_limited"])
def test_changed_package_blocks_model_repair_and_rate_limit_resend(lib, kind, reply):
    run = queue_decompose(lib) if kind == "claim_decomposition" else queue_kill(lib)
    def change(si):
        lib.flow.deps.package = replace(lib.flow.deps.package, package_hash="sha256:" + "0" * 64)
    lib.adapter.before = change
    if reply == "invalid":
        lib.adapter.responder = lambda si: "{}"
    else:
        lib.adapter.fail = lambda si: ModelStepResult("failed", error="429 SYNTHETIC rate limit",
                                                      delivery_class="rejected_not_executed")
    result = execute(lib, run)
    assert result["status"] == "failed" and result["pause_reason"] == "skill_package_changed"
    assert len(lib.adapter.calls) == result["usage"]["model_calls"] == 1
    assert lib.requests == []


@pytest.mark.parametrize("window", ["between_steps", "resume"])
def test_changed_package_finishes_frozen_search_failed_and_never_sends_assessment(lib, monkeypatch, window):
    run = queue_kill(lib)
    original = CandidateStore.record_query
    def after_query(self, *args, **kw):
        result = original(self, *args, **kw)
        if window == "resume":
            stop(lib, run, "pause")
        else:
            lib.flow.deps.package = replace(lib.flow.deps.package, package_hash="sha256:" + "0" * 64)
        return result
    monkeypatch.setattr(CandidateStore, "record_query", after_query)
    result = execute(lib, run)
    if window == "resume":
        assert result["status"] == "paused"
        lib.flow.deps.package = replace(lib.flow.deps.package, package_hash="sha256:" + "0" * 64)
        result = resume(lib, run)
    assert result["status"] == "failed" and result["pause_reason"] == "skill_package_changed"
    assert search(lib, run)["outcome"] == "failed"
    assert summary(lib, run)["failure_code"] == "skill_package_changed"
    assert len(lib.requests) == len(lib.adapter.calls) == 1
    assert lib.candidate_store.cells(search(lib, run)["id"]) == []


def test_frozen_plan_depth_follows_pages_actually_shown_after_message_drops(lib, monkeypatch):
    run = queue_kill(lib)
    original = CandidateStore.record_query
    def add_pages(self, *args, **kw):
        result = original(self, *args, **kw)
        svid = result[0]["source_version_id"]
        asset = attach(lib, svid, "SYNTHETIC page " + "a" * 4000)
        for n in range(2, 4):
            lib.store._insert_passage(svid, asset, "pdf_page", n, str(n), None, None, "SYNTHETIC-v1", "SYNTHETIC page " + "a" * 4000)
        return result
    monkeypatch.setattr(CandidateStore, "record_query", add_pages)
    original_message = prompt.step_message
    def oversized(payload):
        text = original_message(payload)
        return text + "a" * candidates.MAX_MESSAGE_CHARS if payload["task_type"] == "claim_assessment" and any(p["locator"]["kind"] == "pdf_page" for p in payload["passages"]) else text
    monkeypatch.setattr(prompt, "step_message", oversized)
    assert execute(lib, run)["status"] == "completed"
    hit = lib.candidate_store.hits(search(lib, run)["id"])[0]
    assert hit["reading_depth"] == "abstract"
    payload = lib.store.step_input_payload(hit["step_input_id"])
    assert len(payload["passages"]) == 1 and payload["passages"][0]["locator"]["kind"] == "abstract"
    plan = lib.store.existing_step(run["id"], "kill_search_plan")["output"]
    assert plan["hits"][0]["omitted"]["message_size"] == 3


def test_one_missing_frozen_page_invalidates_the_whole_hit_instead_of_sending_the_abstract(lib, monkeypatch):
    run = queue_kill(lib)
    original_query = CandidateStore.record_query
    def add_page(self, *args, **kw):
        result = original_query(self, *args, **kw)
        attach(lib, result[0]["source_version_id"], "SYNTHETIC page")
        return result
    monkeypatch.setattr(CandidateStore, "record_query", add_page)
    original_hits = CandidateStore.record_hits
    def pause(self, *args, **kw):
        original_hits(self, *args, **kw)
        lib.store.update_run(run["id"], status="pause_requested")
    monkeypatch.setattr(CandidateStore, "record_hits", pause)
    assert execute(lib, run)["status"] == "paused"
    original_rows = lib.store.passages_for
    monkeypatch.setattr(lib.store, "passages_for", lambda sid: [p for p in original_rows(sid) if p["kind"] != "pdf_page"])
    assert resume(lib, run)["status"] == "completed"
    hit = lib.candidate_store.hits(search(lib, run)["id"])[0]
    assert (hit["reading_depth"], hit["assessment_state"]) == ("stored_passages", "insufficient_access")
    assert len(lib.adapter.calls) == 1


def test_sync_external_failed_run_writes_failure_code_before_terminal_search(lib, monkeypatch):
    run = queue_kill(lib)
    original = CandidateStore.record_hits
    def pause(self, *args, **kw):
        original(self, *args, **kw)
        lib.store.update_run(run["id"], status="pause_requested")
    monkeypatch.setattr(CandidateStore, "record_hits", pause)
    execute(lib, run)
    lib.store.update_run(run["id"], status="failed", pause_reason="search_failed")
    lib.candidate_store.sync_search_outcome(run["id"])
    assert search(lib, run)["outcome"] == "failed"
    assert summary(lib, run)["failure_code"] == "search_failed"


def test_passage_disappearing_during_health_wait_is_not_sent_under_frozen_depth(lib, monkeypatch):
    run = queue_kill(lib)
    health = lib.adapter.health
    original_rows = lib.store.passages_for
    async def disappearing_health(*args, **kw):
        result = await health(*args, **kw)
        frozen = search(lib, run)
        if frozen and any(q["status"] == "succeeded" for q in lib.candidate_store.queries(frozen["id"])):
            monkeypatch.setattr(lib.store, "passages_for", lambda sid: [] if sid not in lib.ids.values() else original_rows(sid))
        return result
    monkeypatch.setattr(lib.adapter, "health", disappearing_health)
    assert execute(lib, run)["status"] == "completed"
    hit = lib.candidate_store.hits(search(lib, run)["id"])[0]
    assert hit["assessment_state"] == "insufficient_access" and len(lib.adapter.calls) == 1
    assert summary(lib, run)["hits"][0]["reason"] == "frozen_passage_unavailable"


@pytest.mark.parametrize("prior_usage,assessed", [(0, 8), (12, 6)])
def test_real_model_step_attempts_consume_the_54_ceiling_with_rate_limits_and_one_repair(lib, prior_usage, assessed):
    lib.provider(records=[provider_record(str(i)) for i in range(8)])
    run = queue_kill(lib)
    # Prior usage simulates calls of earlier manually resumed unknown outcomes.
    if prior_usage:
        lib.store.add_usage(run["id"], "model_calls", prior_usage)
    def ordinal(si):
        return sum(c["step_id"] == si["step_id"] for c in lib.adapter.calls)
    lib.adapter.fail = lambda si: ModelStepResult("failed", error="HTTP 429 rate limited") if ordinal(si) % 3 else None
    lib.adapter.responder = lambda si: "{}" if ordinal(si) == 3 else valid_response(si)
    result = execute(lib, run)
    assert result["status"] == "completed" and result["usage"]["model_calls"] == 54
    assert len(lib.adapter.calls) == 54 - prior_usage
    kept = lib.candidate_store.hits(search(lib, run)["id"])
    assert sum(h["assessment_state"] == "assessed" for h in kept) == assessed
    assert all(h["assessment_state"] == "pending" for h in kept[assessed:])
    assert lib.adapter.max_concurrent == 1
