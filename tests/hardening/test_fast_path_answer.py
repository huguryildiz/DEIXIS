"""D253 synthetic evidence boundaries, publication ordering and legacy isolation."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.domain import canonical, skill
from deixis.domain.rules import TEST_EFFORT_BUDGETS
from deixis.providers.common import ProviderRecord
from deixis.storage.db import transaction
from deixis.workflow import fast_answer, fast_path, small_batch, views, report_pipeline
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.flow import FlowDeps, ResearchFlow, RunStopped
from fakes import FakeAdapter, valid_response
from test_criterion_passage_flow import library, page_source, TOPIC_PAGE
from test_fast_path_clock import FakeClock
from test_small_batch_flow import client_of
from test_fetch_overlap_flow import discover, wait
from test_fulltext_flow import Transport, work
from test_abstract_flow import ON_TOPIC
from test_answer_resplit import draft_for



def candidate(store, rid, name, abstract, *codes):
    """One SYNTHETIC search record with an abstract and these decisions, its selection derived from them."""
    record = ProviderRecord(provider_record_id=name, title=f"SYNTHETIC {name}", authors=[], year=None, venue=None,
                            publication_type=None, doi=None, landing_url=None, oa_pdf_url=None, oa_pdf_version=None,
                            version_label=None, abstract=abstract, abstract_origin="provider", identifiers={}, raw={})
    svid, _ = store.upsert_provider_source("known_list", record, None)
    store.add_to_corpus(rid, svid, "search")
    decisions = DecisionStore(store)
    for code in codes:
        decisions.record(rid, svid, code)
    decisions.derive_selection(rid, store.source(svid)["work_id"])
    return svid

def setup(tmp_path, n=1, codes=("runs_agree_candidate",), pdf=False):
    store, rid = library(tmp_path)
    sources = [candidate(store, rid, str(i), "SYNTHETIC exercise improves fatigue.", *codes) for i in range(n)]
    if pdf:
        sources += [page_source(store, rid, "pdf", [TOPIC_PAGE] * 3, "SYNTHETIC exercise.", included=False)]
        DecisionStore(store).record(rid, sources[-1], "runs_agree_candidate")
    budget = small_batch.freeze_budget(TEST_EFFORT_BUDGETS["quick"].__dict__, "quick", "off")
    budget["fast_path"] = fast_path.freeze_budget(budget, "quick")
    discovery = store.create_run(rid, "discovery", budget, None)
    store.update_run(discovery["id"], status="running")
    listing = {"policy": small_batch.POLICY, "order": sources, "order_hash": "synthetic",
        "manifest_hash": "synthetic", "manifest": {"scope_revision": 1,
        "versions": {svid: store.source(svid) for svid in sources}}, "items": [
        {"work_id": store.source(svid)["work_id"], "head": svid, "position": i + 1,
         "versions": [svid], "user_priority": False} for i, svid in enumerate(sources)]}
    step = store.step(discovery["id"], small_batch.LIST_KEY, "code:small_batch_list")
    store.finish_step(step["id"], "succeeded", output=listing)
    flow = ResearchFlow(FlowDeps(Settings(data_dir=tmp_path / "data", port=8878), store,
                                 {"fake": FakeAdapter(valid_response)}, skill.load_skill_package(), None))
    return SimpleNamespace(store=store, rid=rid, sources=sources, discovery=store.run(discovery["id"]),
                           listing=listing, flow=flow)


def cutoff(lib, unread=()):
    with transaction(lib.store.conn):
        return fast_answer.freeze_cutoff(lib.flow, lib.discovery, lib.listing,
            {"read_cutoff_at": fast_path.timestamp(lib.store.clock), "not_screened_at_cutoff": list(unread)})


def answer_run(lib):
    lib.store.update_run(lib.discovery["id"], status="completed")
    run = lib.store.create_run(lib.rid, "answer", fast_answer.answer_run_budget(lib.store, lib.rid, lib.store.scope(lib.rid)), None)
    lib.store.update_run(run["id"], status="running")
    return lib.store.run(run["id"])


def user(lib, svid, state):
    version = lib.store.conn.execute("SELECT version FROM selections WHERE research_id = ? AND source_version_id = ?",
                                   (lib.rid, svid)).fetchone()[0]
    lib.store.set_user_selection(lib.rid, svid, state, version, "SYNTHETIC override reason")


def test_new_policy_and_old_bindings(tmp_path):
    lib = setup(tmp_path)
    policy = lib.discovery["budget"]["fast_path"]
    assert policy["auto_answer"] and policy["approval_mode"] == "unattended"
    assert fast_path.enforces(lib.discovery["budget"], "answer")
    assert policy["policy_hash"] == canonical.sha256_hex({k: v for k, v in policy.items() if k != "policy_hash"})
    for stages in (None, ["read"]):
        policy.pop("enforced_stages", None)
        if stages:
            policy["enforced_stages"] = stages
        lib.store.conn.execute("UPDATE runs SET budget_json = ? WHERE id = ?", (json.dumps(lib.discovery["budget"]), lib.discovery["id"]))
        lib.store.update_run(lib.discovery["id"], status="completed")
        bound = fast_answer.answer_run_budget(lib.store, lib.rid, lib.store.scope(lib.rid))
        assert not fast_path.enforces(bound, "answer")


@pytest.mark.parametrize("code,reason", [("runs_agree_out_of_scope", "out_of_scope"),
    ("abstract_not_read", "not_screened_at_cutoff"), ("criterion_absent", "criterion_not_met")])
def test_cutoff_exclusions(tmp_path, code, reason):
    lib = setup(tmp_path, codes=("runs_agree_candidate", code))
    frozen = cutoff(lib)
    assert frozen["items"][0]["reason"] == reason
    assert frozen["excluded_reasons"] == {reason: 1}


def test_pdf_without_verified_read_falls_back_and_late_decisions_do_not_change_input(tmp_path):
    lib = setup(tmp_path, pdf=True)
    frozen = cutoff(lib)
    pdf = lib.sources[-1]
    assert frozen["items"][-1]["route"] == "abstract"
    DecisionStore(lib.store).record(lib.rid, pdf, "criterion_absent")
    DecisionStore(lib.store).derive_selection(lib.rid, lib.store.source(pdf)["work_id"])
    run = answer_run(lib)
    plan = fast_answer.input_plan(lib.flow, run, lib.store.scope(lib.rid))
    assert plan["breadth"] == 2
    assert all(lib.store.passage(pid)["kind"] == "abstract" for pid in plan["passage_ids"])
    assert fast_answer.input_plan(lib.flow, run, lib.store.scope(lib.rid)) == plan


def test_quick_represents_every_eligible_work_and_keeps_unread_out(tmp_path):
    lib = setup(tmp_path, 25)
    unread = lib.listing["items"][-1]["work_id"]
    cutoff(lib, [unread])
    run = answer_run(lib)
    plan = fast_answer.input_plan(lib.flow, run, lib.store.scope(lib.rid))
    assert len(plan["passage_ids"]) == plan["breadth"] == plan["limit"] == 24
    assert len({lib.store.passage(pid)["source_version_id"] for pid in plan["passage_ids"]}) == 24


def test_user_override_before_freeze_after_freeze_guard_and_reason(tmp_path):
    lib = setup(tmp_path, 2, codes=("runs_agree_out_of_scope",))
    cutoff(lib)
    user(lib, lib.sources[0], "included")
    run = answer_run(lib)
    plan = fast_answer.input_plan(lib.flow, run, lib.store.scope(lib.rid))
    assert plan["breadth"] == 1 and plan["items"][0]["override_reason"] == "SYNTHETIC override reason"
    assert plan["items"][0]["route"] == "abstract"
    user(lib, lib.sources[0], "excluded")
    with pytest.raises(RunStopped):
        asyncio.run(lib.flow._answer(run, lib.store.scope(lib.rid)))
    assert lib.store.run(run["id"])["pause_reason"] == "selection_changed"
    assert not lib.store.conn.execute("SELECT 1 FROM model_sessions").fetchone()


def test_no_evidence_does_not_call_model_and_records_terminal_outcome(tmp_path):
    lib = setup(tmp_path, codes=("runs_agree_out_of_scope",))
    cutoff(lib)
    run = answer_run(lib)
    asyncio.run(lib.flow.execute(run["id"]))
    answer = lib.store.conn.execute("SELECT * FROM answers WHERE run_id = ?", (run["id"],)).fetchone()
    assert answer["status"] == "no_evidence"
    assert json.loads(answer["validation_json"])["reason"] == "no_evidence_at_cutoff"
    assert lib.store.conn.execute("SELECT answer_outcome FROM fast_path_ledgers").fetchone()[0] == "no_evidence_at_cutoff"
    assert not lib.store.conn.execute("SELECT 1 FROM model_sessions").fetchone()
    assert lib.store.run(run["id"])["status"] == "completed"


def test_answer_avoids_inspection_embedding_and_in_run_review(tmp_path, monkeypatch):
    lib = setup(tmp_path)
    cutoff(lib)
    run = answer_run(lib)
    async def forbidden(*args, **kwargs):
        pytest.fail("Fast answer must not fetch, embed, read equations or review inline")
    for method in ("_inspect", "_semantic_ranking", "_read_equations", "_review"):
        monkeypatch.setattr(lib.flow, method, forbidden)
    asyncio.run(lib.flow.execute(run["id"]))
    assert lib.store.run(run["id"])["status"] == "completed"
    answer = views.research_view(lib.store, lib.rid)["answers"][0]
    assert answer["status"] == "structurally_valid"
    assert all(c["evidence_basis"] == "abstract" for c in answer["claims"])
    assert answer["abstract_only_sources"] == 1
    review = lib.store.next_queued_run()
    assert review["kind"] == "answer_review" and "fast_path" not in review["budget"]
    assert review["target"]["answer_id"] == answer["id"]
    ledger = dict(lib.store.conn.execute("SELECT * FROM fast_path_ledgers").fetchone())
    monkeypatch.setattr(lib.flow, "_review", ResearchFlow._review.__get__(lib.flow))
    lib.store.update_run(review["id"], status="running")
    asyncio.run(lib.flow.execute(review["id"]))
    assert lib.store.run(review["id"])["status"] == "completed"
    assert dict(lib.store.conn.execute("SELECT * FROM fast_path_ledgers").fetchone()) == ledger


def test_auto_answer_creation_is_atomic_idempotent_and_skips_old_scope(tmp_path):
    lib = setup(tmp_path)
    cutoff(lib)
    with pytest.raises(RuntimeError), transaction(lib.store.conn):
        lib.store.update_run(lib.discovery["id"], status="completed")
        fast_answer.auto_answer(lib.store, lib.discovery)
        raise RuntimeError("SYNTHETIC rollback")
    assert lib.store.run(lib.discovery["id"])["status"] == "running"
    assert lib.store.conn.execute("SELECT COUNT(*) FROM runs WHERE kind = 'answer'").fetchone()[0] == 0
    with transaction(lib.store.conn):
        lib.store.update_run(lib.discovery["id"], status="completed")
        fast_answer.auto_answer(lib.store, lib.discovery)
        fast_answer.auto_answer(lib.store, lib.discovery)
    queued = lib.store.next_queued_run()
    assert queued["kind"] == "answer"
    assert queued["budget"] == fast_answer.answer_run_budget(lib.store, lib.rid, lib.store.scope(lib.rid)) | {
        "trigger": "auto_after_discovery", "fast_path": queued["budget"]["fast_path"]}
    assert lib.store.conn.execute("SELECT COUNT(*) FROM runs WHERE kind = 'answer'").fetchone()[0] == 1


def test_end_to_end_unattended_auto_answer_and_backend_abstract_label(tmp_path):
    adapter = FakeAdapter(valid_response)
    app = create_app(Settings(data_dir=tmp_path, port=8879, fulltext_fetch="off",
        fulltext_adjudication="off", search_query="code"),
        adapters={"fake": adapter}, http_client=httpx.AsyncClient(transport=httpx.MockTransport(
            Transport([work(1, title=ON_TOPIC)]))), extra_hosts=("testserver",), trusted_clients=("testclient",))
    with client_of(app) as client:
        rid, discovery_id, _, discovery = discover(client)
        assert discovery["status"] == "completed"
        approval = app.state.store.approval_step(discovery_id)["output"]["approval"]
        assert approval["approved_by"] == "unattended" and approval["asked"] is False
        runs = app.state.store.conn.execute("SELECT id FROM runs WHERE research_id = ? AND kind = 'answer'", (rid,)).fetchall()
        assert len(runs) == 1
        answer_run_id = runs[0][0]
        _, result = wait(client, rid, answer_run_id)
        assert result["status"] == "completed", result
        view = client.get(f"/api/researches/{rid}").json()
        assert view["answers"][0]["status"] == "structurally_valid"
        assert view["answers"][0]["claims"][0]["evidence_basis"] == "abstract"


def inspected_pdf(lib):
    svid = lib.sources[-1]
    item = lib.flow._plan_item(svid, svid)
    plan = lib.store.step(lib.discovery["id"], "synthetic:adjudication_plan", "code:adjudication_plan")
    lib.store.finish_step(plan["id"], "succeeded", output={"works": [item]})
    target = {"source_id": svid, "criterion": "SYNTHETIC model", "parts": [
        {"name": "model", "definition": "SYNTHETIC model"}], "runs": 2, "run": 1}
    async def read():
        for n in (1, 2):
            await lib.flow._model_step(lib.discovery, lib.store.scope(lib.rid),
                f"fulltext_adjudication:{svid}:{n}", "fulltext_adjudication", source_ids=[svid],
                passage_rows=[p for p in lib.store.passages_for(svid) if p["kind"] == "pdf_page"],
                adjudication_target=target | {"run": n})
    asyncio.run(read())
    step = lib.store.existing_step(lib.discovery["id"], f"fulltext_adjudication:{svid}:2")
    DecisionStore(lib.store).record(lib.rid, svid, "all_parts_verified", step_id=step["id"])
    return svid, item


@pytest.mark.parametrize("defect", [None, "stale_scope", "stale_criterion", "replaced_file", "missing_peer"])
def test_fulltext_requires_same_file_two_reads_and_current_criterion(tmp_path, defect):
    lib = setup(tmp_path, pdf=True)
    svid, item = inspected_pdf(lib)
    if defect == "stale_scope":
        lib.store.conn.execute("UPDATE stage_decisions SET scope_revision = 0 WHERE stage = 'fulltext'")
    elif defect == "stale_criterion":
        lib.store.conn.execute("UPDATE stage_decisions SET criterion_hash = 'old' WHERE stage = 'fulltext'")
    elif defect == "replaced_file":
        lib.store.conn.execute("UPDATE source_assets SET removed_at = 'SYNTHETIC removed' WHERE id = ?", (item["asset_id"],))
    elif defect == "missing_peer":
        lib.store.conn.execute("UPDATE run_steps SET status = 'failed' WHERE operation_key = ?",
                               (f"fulltext_adjudication:{svid}:1",))
    frozen = cutoff(lib)
    row = frozen["items"][-1]
    assert row["route"] == ("fulltext" if defect is None else "abstract")
    run = answer_run(lib)
    plan = fast_answer.input_plan(lib.flow, run, lib.store.scope(lib.rid))
    if defect is None:
        assert plan["breadth"] == 2
        assert sum(lib.store.passage(pid)["kind"] == "pdf_page" for pid in plan["passage_ids"]) == 3
        assert row["asset_id"] == item["asset_id"]
    else:
        assert all(lib.store.passage(pid)["kind"] == "abstract" for pid in plan["passage_ids"])


def test_code_selection_revision_during_generation_is_ignored_but_source_change_stops(tmp_path):
    lib = setup(tmp_path)
    cutoff(lib)
    run = answer_run(lib)
    def responder(si):
        lib.store.conn.execute("UPDATE researches SET selection_revision = selection_revision + 1 WHERE id = ?", (lib.rid,))
        return valid_response(si)
    lib.flow.deps.adapters["fake"] = FakeAdapter(responder)
    asyncio.run(lib.flow.execute(run["id"]))
    assert lib.store.conn.execute("SELECT status FROM answers").fetchone()[0] == "structurally_valid"
    review = lib.store.next_queued_run()
    lib.store.update_run(review["id"], status="cancelled")
    again = answer_run(lib)
    fast_answer.input_plan(lib.flow, again, lib.store.scope(lib.rid))
    lib.store.conn.execute("UPDATE source_versions SET title = 'SYNTHETIC changed' WHERE id = ?", (lib.sources[0],))
    asyncio.run(lib.flow.execute(again["id"]))
    assert lib.store.run(again["id"])["pause_reason"] == "source_changed"


def test_d249_repairs_keep_cutoff_input_and_overrun(tmp_path):
    lib = setup(tmp_path, n=2)
    cutoff(lib)
    run = answer_run(lib)
    clock = FakeClock()
    lib.store.clock = clock
    calls = []
    def responder(si):
        if si["task_type"] != "grounded_answer":
            return valid_response(si)
        calls.append(si)
        clock.advance(80)
        return json.dumps(draft_for(si, "several" if len(calls) < 3 else "split"))
    lib.flow.deps.adapters["fake"] = FakeAdapter(responder)
    asyncio.run(lib.flow.execute(run["id"]))
    assert len(calls) == 3
    assert all(si["passages"] == calls[0]["passages"] for si in calls)
    answer = lib.store.conn.execute("SELECT status, validation_json FROM answers").fetchone()
    assert answer["status"] == "structurally_valid"
    assert json.loads(answer["validation_json"])["extra_repair"]["outcome"] == "published"
    stage = lib.store.conn.execute("SELECT used_ms, alloc_ms FROM fast_path_stages WHERE stage = 'answer'").fetchone()
    assert stage["used_ms"] == 240000 > stage["alloc_ms"]


def test_human_decision_after_cutoff_is_applied_before_input_freeze(tmp_path):
    lib = setup(tmp_path)
    cutoff(lib)
    DecisionStore(lib.store).record(lib.rid, lib.sources[0], "human_criterion_not_met", note="SYNTHETIC human exclusion")
    run = answer_run(lib)
    plan = fast_answer.input_plan(lib.flow, run, lib.store.scope(lib.rid))
    assert plan["passage_ids"] == []


def test_no_text_user_override_is_recorded_and_cannot_create_evidence(tmp_path):
    lib = setup(tmp_path, codes=("runs_agree_out_of_scope",))
    lib.store.conn.execute("DELETE FROM passages WHERE source_version_id = ?", (lib.sources[0],))
    user(lib, lib.sources[0], "included")
    frozen = cutoff(lib)
    assert frozen["items"][0]["reason"] == "user_included_no_text"
    assert frozen["items"][0]["override_reason"] == "SYNTHETIC override reason"


def test_mixed_claim_basis_comes_from_links_and_review_failure_leaves_answer_intact(tmp_path, monkeypatch):
    lib = setup(tmp_path, pdf=True)
    inspected_pdf(lib)
    cutoff(lib)
    run = answer_run(lib)
    def mixed(si):
        if si["task_type"] != "grounded_answer":
            return valid_response(si)
        draft = json.loads(valid_response(si))
        passages = [si["passages"][0], next(p for p in si["passages"] if p["locator"]["kind"] == "pdf_page")]
        draft["claims"][0].update(support_type="analyst_inference", passage_ids=[p["passage_id"] for p in passages])
        draft["citation_anchors"] = [{"claim_label": "c1", "passage_id": p["passage_id"], "quote": p["text"][:300]}
                                     for p in passages]
        return json.dumps(draft)
    lib.flow.deps.adapters["fake"] = FakeAdapter(mixed)
    asyncio.run(lib.flow.execute(run["id"]))
    answer = views.research_view(lib.store, lib.rid)["answers"][0]
    assert answer["claims"][0]["evidence_basis"] == "mixed"
    ledger = dict(lib.store.conn.execute("SELECT * FROM fast_path_ledgers").fetchone())
    review = lib.store.next_queued_run()
    continuation = []
    lib.flow.deps.settings = Settings(data_dir=tmp_path / "data", study_table="auto")
    async def failed_assessment(run, scope, answer_id, draft):
        lib.store.save_answer_review(answer_id, lib.rid, run["id"], None, None, "failed", None, "model_connection_not_ready")
    monkeypatch.setattr(lib.flow, "_review", failed_assessment)
    def table(store, original):
        assert store.run(review["id"])["status"] == "completed"
        continuation.append(original["id"])
    monkeypatch.setattr(report_pipeline, "after_answer", table)
    lib.store.update_run(review["id"], status="running")
    asyncio.run(lib.flow.execute(review["id"]))
    assert continuation == [run["id"]]
    assert lib.store.answer_review(answer["id"])["status"] == "failed"
    assert dict(lib.store.conn.execute("SELECT * FROM fast_path_ledgers").fetchone()) == ledger
    assert lib.store.conn.execute("SELECT status FROM answers").fetchone()[0] == "structurally_valid"


def test_old_scope_does_not_launch_auto_answer(tmp_path):
    lib = setup(tmp_path)
    cutoff(lib)
    lib.store.update_run(lib.discovery["id"], status="completed")
    lib.store.conn.execute("UPDATE researches SET current_scope_revision = 2 WHERE id = ?", (lib.rid,))
    fast_answer.auto_answer(lib.store, lib.discovery)
    assert not lib.store.next_queued_run()
    event = lib.store.conn.execute("SELECT payload_json FROM events WHERE type = 'auto_answer_skipped'").fetchone()
    assert json.loads(event[0])["reason"] == "scope_revised"


def test_top_n_bound_can_only_expand_through_recorded_user_choice(tmp_path):
    lib = setup(tmp_path, n=26)
    frozen = cutoff(lib)
    assert frozen["items"][-1]["reason"] == "outside_read_window"
    user(lib, lib.sources[-1], "included")
    run = answer_run(lib)
    plan = fast_answer.input_plan(lib.flow, run, lib.store.scope(lib.rid))
    assert plan["breadth"] == 26 and plan["limit"] == 26
    assert plan["items"][0]["source_version_id"] == lib.sources[-1]
    assert plan["items"][0]["override_reason"] == "SYNTHETIC override reason"


def test_scope_change_during_answer_generation_cannot_publish(tmp_path):
    lib = setup(tmp_path)
    cutoff(lib)
    run = answer_run(lib)
    def revised(si):
        lib.store.conn.execute("UPDATE researches SET current_scope_revision = 2 WHERE id = ?", (lib.rid,))
        return valid_response(si)
    lib.flow.deps.adapters["fake"] = FakeAdapter(revised)
    asyncio.run(lib.flow.execute(run["id"]))
    assert lib.store.run(run["id"])["status"] == "cancelled"
    assert lib.store.run(run["id"])["pause_reason"] == "scope_revised"
    assert not lib.store.conn.execute("SELECT 1 FROM answers").fetchone()


@pytest.mark.parametrize("change,reason", [
    ("removed", "removed_after_cutoff"),
    ("metadata", "source_changed_after_cutoff"),
    ("text_removed", "no_text_at_cutoff"),
])
def test_pre_freeze_changes_drop_only_affected_work_and_answer_finishes(tmp_path, change, reason):
    lib = setup(tmp_path, n=2)
    frozen = cutoff(lib)
    svid = lib.sources[0]
    if change == "removed":
        lib.store.conn.execute("UPDATE corpus_memberships SET removed_at = 'SYNTHETIC removed'"
                               " WHERE research_id = ? AND source_version_id = ?", (lib.rid, svid))
    elif change == "metadata":
        lib.store.conn.execute("UPDATE source_versions SET title = 'SYNTHETIC changed' WHERE id = ?", (svid,))
    else:
        lib.store.conn.execute("DELETE FROM passages WHERE source_version_id = ?", (svid,))
    run = answer_run(lib)
    plan = fast_answer.input_plan(lib.flow, run, lib.store.scope(lib.rid))
    assert [r["source_version_id"] for r in plan["items"]] == [lib.sources[1]]
    assert plan["excluded_reasons"] == {reason: 1}
    assert plan["excluded"] == [{"work_id": frozen["items"][0]["work_id"],
                                 "source_version_id": svid, "reason": reason}]
    fast_answer.check_input(lib.flow, run["id"], plan)
    assert fast_answer.input_plan(lib.flow, run, lib.store.scope(lib.rid)) == plan
    asyncio.run(lib.flow.execute(run["id"]))
    assert lib.store.run(run["id"])["status"] == "completed"
    assert lib.store.conn.execute("SELECT status FROM answers").fetchone()[0] == "structurally_valid"
    assert lib.store.existing_step(lib.discovery["id"], fast_answer.CUTOFF)["output"] == frozen


@pytest.mark.parametrize("before_freeze", [True, False])
def test_reextracted_pdf_never_adds_post_cutoff_text(tmp_path, before_freeze):
    lib = setup(tmp_path, pdf=True)
    svid, item = inspected_pdf(lib)
    frozen = cutoff(lib)
    run = answer_run(lib)
    if not before_freeze:
        plan = fast_answer.input_plan(lib.flow, run, lib.store.scope(lib.rid))
    lib.store.conn.execute("UPDATE source_assets SET extraction_version = 'SYNTHETIC new extraction' WHERE id = ?",
                           (item["asset_id"],))
    if before_freeze:
        plan = fast_answer.input_plan(lib.flow, run, lib.store.scope(lib.rid))
        assert plan["breadth"] == 2
        assert plan["items"][-1]["route"] == "abstract"
        assert plan["items"][-1]["decision_id"] == frozen["items"][-1]["abstract_decision_id"]
        assert all(lib.store.passage(pid)["kind"] == "abstract" for pid in plan["passage_ids"])
        assert set(plan["passage_ids"]) <= {pid for r in frozen["items"] for pid in r["abstract_ids"]}
        asyncio.run(lib.flow.execute(run["id"]))
        assert lib.store.run(run["id"])["status"] == "completed"
    else:
        with pytest.raises(RunStopped):
            fast_answer.check_input(lib.flow, run["id"], plan)
        assert lib.store.run(run["id"])["pause_reason"] == "source_changed"


@pytest.mark.parametrize("change", ["removed", "metadata", "text_removed"])
def test_post_freeze_source_changes_still_block_publication(tmp_path, change):
    lib = setup(tmp_path)
    cutoff(lib)
    run = answer_run(lib)
    plan = fast_answer.input_plan(lib.flow, run, lib.store.scope(lib.rid))
    svid = lib.sources[0]
    if change == "removed":
        lib.store.conn.execute("UPDATE corpus_memberships SET removed_at = 'SYNTHETIC removed'"
                               " WHERE research_id = ? AND source_version_id = ?", (lib.rid, svid))
    elif change == "metadata":
        lib.store.conn.execute("UPDATE source_versions SET year = 2025 WHERE id = ?", (svid,))
    else:
        lib.store.conn.execute("DELETE FROM passages WHERE source_version_id = ?", (svid,))
    with pytest.raises(RunStopped):
        fast_answer.check_input(lib.flow, run["id"], plan)
    assert lib.store.run(run["id"])["pause_reason"] == "source_changed"
    assert not lib.store.conn.execute("SELECT 1 FROM answers").fetchone()


@pytest.mark.parametrize("code,before_cutoff", [
    ("human_pdf_wrong", True), ("human_pdf_wrong", False),
    ("human_not_sure", True), ("human_not_sure", False),
])
def test_wrong_pdf_keeps_screened_abstract_and_not_sure_remains_pending(tmp_path, code, before_cutoff):
    lib = setup(tmp_path)
    decisions = DecisionStore(lib.store)
    if before_cutoff:
        decisions.record(lib.rid, lib.sources[0], code, note="SYNTHETIC user reason")
    cutoff(lib)
    if not before_cutoff:
        decisions.record(lib.rid, lib.sources[0], code, note="SYNTHETIC user reason")
    run = answer_run(lib)
    plan = fast_answer.input_plan(lib.flow, run, lib.store.scope(lib.rid))
    if code == "human_pdf_wrong":
        assert plan["breadth"] == 1 and plan["items"][0]["route"] == "abstract"
        assert plan["items"][0]["override_reason"] == "SYNTHETIC user reason"
        assert all(lib.store.passage(pid)["kind"] == "abstract" for pid in plan["passage_ids"])
    else:
        assert plan["breadth"] == 0 and plan["excluded_reasons"] == {"user_pending": 1}


@pytest.mark.parametrize("pdf", [False, True])
def test_cutoff_batches_pool_and_choice_queries_and_reads_source_once(tmp_path, monkeypatch, pdf):
    lib = setup(tmp_path, n=100, pdf=pdf)
    if pdf:
        inspected_pdf(lib)
    calls, queries = [], []
    original = lib.store.source
    def source(svid):
        calls.append(svid)
        return original(svid)
    monkeypatch.setattr(lib.store, "source", source)
    lib.store.conn.set_trace_callback(queries.append)
    try:
        frozen = cutoff(lib)
    finally:
        lib.store.conn.set_trace_callback(None)
    assert len(frozen["items"]) == len(lib.sources)
    assert calls == lib.sources
    selects = [q for q in queries if q.lstrip().upper().startswith("SELECT")]
    # One source lookup per row; the remaining choice/pool queries have fixed cost.
    assert len(selects) <= len(lib.sources) + 40


@pytest.mark.parametrize("before_cutoff", [True, False])
def test_wrong_previously_read_pdf_uses_its_screened_abstract_decision(tmp_path, before_cutoff):
    lib = setup(tmp_path, pdf=True)
    svid, _ = inspected_pdf(lib)
    if before_cutoff:
        DecisionStore(lib.store).record(lib.rid, svid, "human_pdf_wrong")
    frozen = cutoff(lib)
    if not before_cutoff:
        DecisionStore(lib.store).record(lib.rid, svid, "human_pdf_wrong")
    run = answer_run(lib)
    plan = fast_answer.input_plan(lib.flow, run, lib.store.scope(lib.rid))
    row = next(r for r in plan["items"] if r["source_version_id"] == svid)
    assert row["route"] == "abstract"
    assert row["decision_id"] == frozen["items"][-1]["abstract_decision_id"]
    assert all(lib.store.passage(pid)["kind"] == "abstract" for pid in plan["passage_ids"])


def test_d48_answer_reads_one_version_per_work_and_cites_the_version_it_read(tmp_path):
    # D48: a published record without text and its accepted manuscript with a PDF are one work. The answer reads the
    # manuscript only; the model input and the published evidence point at that version, never at both.
    store, rid = library(tmp_path)
    plain = candidate(store, rid, "plain", "SYNTHETIC exercise improves fatigue.", "runs_agree_candidate")
    record = ProviderRecord(provider_record_id="published", title="SYNTHETIC published letter", authors=[], year=2024,
                            venue=None, publication_type=None, doi="10.5555/synthetic.d48", landing_url=None,
                            oa_pdf_url=None, oa_pdf_version=None, version_label="publishedVersion",
                            abstract="SYNTHETIC exercise improves fatigue in the published abstract.",
                            abstract_origin="provider", identifiers={}, raw={})
    published, _ = store.upsert_provider_source("known_list", record, None)
    store.add_to_corpus(rid, published, "search")
    decisions = DecisionStore(store)
    decisions.record(rid, published, "runs_agree_candidate")
    manuscript = store.open_lookup_version(rid, published, "acceptedVersion", None)
    extraction = SimpleNamespace(status="succeeded", error=None, page_count=3, pages=[
        SimpleNamespace(text=TOPIC_PAGE, physical_page=n, printed_label=None) for n in (1, 2, 3)])
    store.add_asset_with_pages(manuscript, "sha-manuscript", 100, "manuscript.pdf", "user_upload", None,
                               "manuscript.pdf", extraction, "test", lambda t: [(0, len(t), t)])
    work_id = store.source(published)["work_id"]
    decisions.derive_selection(rid, work_id)
    assert store.source(manuscript)["work_id"] == work_id
    assert store.work_heads(rid)[work_id] == published  # the published record heads the work
    assert store.answer_versions(rid)[published] == manuscript  # but only the manuscript has text to read

    heads = [plain, published]
    budget = small_batch.freeze_budget(TEST_EFFORT_BUDGETS["quick"].__dict__, "quick", "off")
    budget["fast_path"] = fast_path.freeze_budget(budget, "quick")
    discovery = store.create_run(rid, "discovery", budget, None)
    store.update_run(discovery["id"], status="running")
    listing = {"policy": small_batch.POLICY, "order": heads, "order_hash": "synthetic", "manifest_hash": "synthetic",
               "manifest": {"scope_revision": 1, "versions": {svid: store.source(svid) for svid in heads}},
               "items": [{"work_id": store.source(plain)["work_id"], "head": plain, "position": 1,
                          "versions": [plain], "user_priority": False},
                         {"work_id": work_id, "head": published, "position": 2,
                          "versions": [published, manuscript], "user_priority": False}]}
    step = store.step(discovery["id"], small_batch.LIST_KEY, "code:small_batch_list")
    store.finish_step(step["id"], "succeeded", output=listing)
    sent = []
    def cite_manuscript(si):
        if si["task_type"] != "grounded_answer":
            return valid_response(si)
        sent.append(si)  # the model sees short handles (D12), so the version is told by its label
        handle = next(s["source_id"] for s in si["sources"] if s["version_label"] == "acceptedVersion")
        return valid_response(si | {"passages": [p for p in si["passages"] if p["source_id"] == handle]})
    flow = ResearchFlow(FlowDeps(Settings(data_dir=tmp_path / "data", port=8878), store,
                                 {"fake": FakeAdapter(cite_manuscript)}, skill.load_skill_package(), None))
    lib = SimpleNamespace(store=store, rid=rid, sources=[plain, manuscript], discovery=store.run(discovery["id"]),
                          listing=listing, flow=flow)
    inspected_pdf(lib)  # two full-text reads of the manuscript's file, then its full-text decision

    frozen = cutoff(lib)
    row = next(r for r in frozen["items"] if r["work_id"] == work_id)
    assert (row["head"], row["source_version_id"], row["route"]) == (published, manuscript, "fulltext")
    assert row["version"]["version_label"] == "acceptedVersion"
    run = answer_run(lib)
    asyncio.run(flow.execute(run["id"]))
    assert store.run(run["id"])["status"] == "completed", store.run(run["id"])

    # The model input, as stored before the call: one version per work, the manuscript's pages for this one.
    stored = json.loads(store.conn.execute(
        "SELECT i.payload_json FROM step_inputs i JOIN run_steps s ON s.id = i.step_id"
        " WHERE s.run_id = ? AND s.operation_key = 'grounded_answer' ORDER BY i.attempt DESC, i.rowid DESC",
        (run["id"],)).fetchone()[0])
    assert {s["source_id"] for s in stored["sources"]} == {plain, manuscript}
    assert [s["version_label"] for s in stored["sources"] if s["source_id"] == manuscript] == ["acceptedVersion"]
    by_source = {}
    for p in stored["passages"]:
        by_source.setdefault(p["source_id"], []).append(p)
    assert set(by_source) == {plain, manuscript}
    assert {p["locator"]["kind"] for p in by_source[manuscript]} == {"pdf_page"}
    assert {store.passage(p["passage_id"])["source_version_id"] for p in by_source[manuscript]} == {manuscript}
    assert [s["version_label"] for s in sent[-1]["sources"]].count("publishedVersion") == 0

    # The published answer: every citation resolves to the manuscript passage the model was given.
    answer = views.research_view(store, rid)["answers"][0]
    assert answer["status"] == "structurally_valid"
    evidence = [e for claim in answer["claims"] for e in claim["evidence"]]
    assert evidence and {e["source_version_id"] for e in evidence} == {manuscript}
    given = {p["passage_id"] for p in by_source[manuscript]}
    for e in evidence:
        assert e["passage_id"] in given and e["kind"] == "pdf_page"
        assert e["anchor_text"] and e["anchor_text"] in store.passage(e["passage_id"])["text"]
