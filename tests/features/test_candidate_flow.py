"""Synthetic K3 plumbing, not evidence that a model reads a work correctly.

Only FakeAdapter, scripted connectors and mocked HTTP transports are used.
"""
import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from deixis.domain import contracts
from deixis.domain.rules import RevisionConflict
from deixis.models.adapter import ModelStepResult
from deixis.providers.common import SearchOutcome
from deixis.providers.registry import CONNECTORS
from deixis.storage import db
from deixis.workflow.features.candidates import candidates_hits, candidates_run as candidates, candidates_terms as terms
from deixis.workflow.features.candidates.candidates_store import CandidateStore
from deixis.workflow.run.views import research_view
from deixis.workflow.run.worker import Worker
from fakes import FakeAdapter, valid_response
from test_candidate_store import provider_record, version as edit_version
from test_lineage_plan import make_env


class Crash(BaseException):
    """A synthetic process death, outside the worker's ordinary error handler."""


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr("deixis.workflow.run.flow.RATE_LIMIT_BACKOFF_SECONDS", 0)
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


def test_owner_edit_during_decomposition_refuses_publication_and_never_retries(lib):
    run = queue_decompose(lib)
    lib.adapter.before = lambda si: edit_version(lib, lib.candidate)
    assert execute(lib, run)["pause_reason"] == "candidate_version_changed"
    assert [v["origin"] for v in lib.candidate_store.versions(lib.candidate["id"])] == ["human_edit"]
    assert len(lib.adapter.calls) == 1


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
    monkeypatch.setattr("deixis.workflow.run.links.link_records", forbidden)
    run = queue_kill(lib)
    assert execute(lib, run)["status"] == "completed"
    frozen = search(lib, run)
    assert frozen["outcome"] == "completed"
    assert json.loads(frozen["selection_json"]) == {k: run["target"][k] for k in ("model", "providers", "budget", "transport")}
    assert len(json.loads(frozen["rendered_queries_json"])) == len(lib.requests) == 1
    assert lib.requests[0][2:] == (100, {})  # OpenAlex's single-request window (plan version 2)
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


@pytest.mark.parametrize("task", ["claim_assessment"])
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
    monkeypatch.setattr("deixis.workflow.features.candidates.candidates_hits.merge_and_cut", forbidden)
    assert resume(lib, run)["status"] == "completed"
    resumed = search(lib, run)
    assert [resumed[k] for k in ("selection_json", "rendered_queries_json", "skipped_terms_json")] == [frozen[k] for k in ("selection_json", "rendered_queries_json", "skipped_terms_json")]
    assert len(lib.requests) == 1
    assert len(cs.hits(frozen["id"])) == 1


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
    assert int(calls[0].url.params["per_page"]) == run["target"]["limits"]["records_by_provider"]["openalex"] == 100
    assert status(lib, run)["status"] == "open"


@pytest.mark.parametrize("mode", ["cancel"])
@pytest.mark.parametrize("answer", ["timeout"])
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


@pytest.mark.parametrize("kind", ["kill_search"])
@pytest.mark.parametrize("window", ["resume"])
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


import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from deixis.domain import contracts
from deixis.domain.rules import RevisionConflict
from deixis.providers.registry import CONNECTORS
from deixis.workflow.features.candidates import candidates_run as planning
from deixis.workflow.run.store import NotFound
from test_candidate_store import version as edit_version


def row(kind="abstract", text="SYNTHETIC text", n=1):
    return {"id": f"pas_{n:020d}", "source_version_id": "srv_00000000000000000001", "text": text, "kind": kind,
            "physical_page": n if kind == "pdf_page" else None, "printed_label": None, "abstract_origin": "provider" if kind == "abstract" else None}


def test_plan_fingerprint_is_stable_and_changes_with_version_provider_model_or_skill(lib):
    edit_version(lib, lib.candidate)
    p = lib.planner.preview(lib.rid, lib.candidate["id"])
    assert p == lib.planner.preview(lib.rid, lib.candidate["id"])
    assert p["budget"]["max_model_calls"] == 54
    edit_version(lib, lib.candidate)
    assert lib.planner.preview(lib.rid, lib.candidate["id"])["preview_fingerprint"] != p["preview_fingerprint"]
    for column, value in (("providers_json", '["pubmed"]'), ("requested_model", "fake-other-model")):
        old = lib.planner.preview(lib.rid, lib.candidate["id"])
        lib.conn.execute(f"UPDATE scope_revisions SET {column} = ? WHERE research_id = ?", (value, lib.rid))
        assert lib.planner.preview(lib.rid, lib.candidate["id"])["preview_fingerprint"] != old["preview_fingerprint"]
    old = lib.planner.preview(lib.rid, lib.candidate["id"])
    lib.planner.skill_package_hash = "sha256:different"
    assert lib.planner.preview(lib.rid, lib.candidate["id"])["preview_fingerprint"] != old["preview_fingerprint"]


def test_request_replay_precedes_edits_and_refuses_mismatched_fingerprint(lib):
    run = queue_kill(lib, "replay")
    edit_version(lib, lib.candidate)
    assert lib.planner.request_run(lib.rid, lib.candidate["id"], run["target"]["preview_fingerprint"], "replay")["id"] == run["id"]
    with pytest.raises(RevisionConflict):
        lib.planner.request_run(lib.rid, lib.candidate["id"], "0" * 64, "replay")
    lib.store.update_run(run["id"], status="completed")
    with pytest.raises(RevisionConflict):
        lib.planner.request_run(lib.rid, lib.candidate["id"], run["target"]["preview_fingerprint"])


def test_evidence_reader_returns_only_stored_input_not_live_passages_or_corpus(lib, monkeypatch):
    run = queue_kill(lib)
    execute(lib, run)
    s = search(lib, run)
    hit = lib.candidate_store.hits(s["id"])[0]
    payload = lib.store.step_input_payload(hit["step_input_id"])
    def forbidden(*args, **kw):
        raise AssertionError("Candidate evidence tried a corpus/live passage view")
    monkeypatch.setattr(lib.store, "passage_view", forbidden, raising=False)
    monkeypatch.setattr(lib.store, "passages_for", forbidden)
    view = planning.candidate_evidence(lib.store, lib.rid, lib.candidate["id"], s["id"], hit["source_version_id"])
    assert view["passages"] == payload["passages"]
    assert view["source"]["title"] == lib.store.source(hit["source_version_id"])["title"]
    with pytest.raises(NotFound):
        planning.candidate_evidence(lib.store, lib.rid, lib.candidate["id"], s["id"], "srv_unknown")


import json

import pytest

from deixis.providers.registry import CONNECTORS
from deixis.storage import db
from deixis.workflow.features.candidates import candidates_run as planning
from deixis.workflow.features.candidates.candidates_hits import merge_and_cut
from test_candidate_store import make_library, provider_record, query, start

CLAIM = {"text": "SYNTHETIC: depth-based routing delivers more packets than vector-based forwarding in underwater "
                 "sensor networks.",
         "setting": ["underwater sensor networks", "underwater acoustic sensor networks"],
         "task": ["depth-based routing", "vector-based forwarding"]}
TARGET = ("SYNTHETIC comparison of depth-based routing and vector-based forwarding in underwater sensor networks",
          "SYNTHETIC: we compare depth-based routing (DBR) and vector-based forwarding (VBF) in underwater sensor "
          "networks and report delivery ratio and energy.")


def records(provider, texts, start_at=0):
    return [{"provider": provider, "source_version_id": f"srv_{provider}_{n + start_at:03d}",
             "work_id": f"wrk_{provider}_{n + start_at:03d}", "_text": text} for n, text in enumerate(texts)]


def pool(*providers):
    per_query = [[{k: v for k, v in r.items() if k != "_text"} for r in group] for group in providers]
    documents = {r["source_version_id"]: {"title": r["_text"][0], "abstract": r["_text"][1]}
                 for group in providers for r in group}
    return per_query, documents


def test_flow_sends_one_request_per_provider_with_its_window_and_keeps_a_rank_18_target(lib):
    noise = [provider_record(f"SYNTHETIC-noise-{n}", abstract="SYNTHETIC: an unrelated scheduling note.",
                             title=f"SYNTHETIC unrelated record {n}") for n in range(20)]
    noise[17] = provider_record("SYNTHETIC-target", title="SYNTHETIC bounded delay in synthetic queues",
                                abstract="SYNTHETIC: buffering gives bounded delay in synthetic queues.")
    lib.conn.execute("UPDATE scope_revisions SET providers_json = ? WHERE research_id = ?",
                     ('["openalex", "arxiv"]', lib.rid))
    lib.provider("openalex", records=noise)
    lib.provider("arxiv", records=noise[:5])
    run = queue_kill(lib)
    assert execute(lib, run)["status"] == "completed"
    assert sorted((pid, limit) for pid, _, limit, _ in lib.requests) == [("arxiv", 100), ("openalex", 100)]
    found = search(lib, run)
    kept = [h for h in lib.candidate_store.hits(found["id"]) if h["kept"]]
    target = lib.conn.execute("SELECT source_version_id FROM kill_search_query_records WHERE kill_search_id = ?"
                              " AND position = 1 AND rank = 18", (found["id"],)).fetchone()[0]
    assert kept[0]["source_version_id"] == target
    assert found["found"] == found["kept"] + found["rank_cut"] + found["duplicates"] == 25
    assert found["kept"] == 8
    plan = lib.store.existing_step(run["id"], "kill_search_plan")["output"]["merged"]
    assert plan["ranking"]["task"] == ["bounded delay"] and plan["kept"][0]["round_robin_rank"] > 8


@pytest.fixture
def store_lib(tmp_path):
    lib = make_library(tmp_path / "library.sqlite")
    yield lib
    lib.conn.close()


def ranked_search(lib):
    s = start(lib, query_block={"setting": [{"term": "synthetic network"}], "task": [{"term": "bounded delay"}]})
    target = json.loads(lib.conn.execute("SELECT target_json FROM runs WHERE id = ?", (s["run_id"],)).fetchone()[0])
    lib.conn.execute("UPDATE runs SET target_json = ? WHERE id = ?", (db.dumps(target | {"plan_version": 2}), s["run_id"]))
    noise = [provider_record(f"SYNTHETIC-{n}", abstract="SYNTHETIC: unrelated text.") for n in range(10)]
    noise[9] = provider_record("SYNTHETIC-target", title="SYNTHETIC bounded delay in a synthetic network",
                               abstract="SYNTHETIC: bounded delay in a synthetic network.")
    records = query(lib, s, noise)
    return s, records
