"""D255 synthetic workflow evidence; no live provider or model calls."""

import asyncio
import copy
import json
import pytest
from deixis.workflow.answer import answer as fast_answer, late_revision
from deixis.workflow.run import views
from deixis.workflow.screen.decisions import DecisionStore
from deixis.workflow.run.flow import RunStopped
from deixis.workflow.run.worker import Worker
from test_fast_path_answer import setup, cutoff, answer_run, user
from test_criterion_passage_flow import body_with, TOPIC_PAGE, page_source


def prepared(tmp_path, *, old=False, no_evidence=False, pdfs=1, last_code="runs_agree_candidate"):
    lib = setup(tmp_path, pdf=True)
    for n in range(1, pdfs):
        svid = page_source(lib.store, lib.rid, f"late-{n}", [TOPIC_PAGE] * 3, "SYNTHETIC exercise improves fatigue.", included=False)
        lib.sources.append(svid)
        lib.listing["order"].append(svid)
        lib.listing["manifest"]["versions"][svid] = lib.store.source(svid)
        lib.listing["items"].append({"work_id": lib.store.source(svid)["work_id"], "head": svid,
                                    "position": len(lib.sources), "versions": [svid], "user_priority": False})
    if pdfs > 1:
        from deixis.workflow.search import small_batch
        lib.store.finish_step(lib.store.existing_step(lib.discovery["id"], small_batch.LIST_KEY)["id"], "succeeded", output=lib.listing)
    scope = lib.store.scope(lib.rid)
    lib.store.freeze_protocol(lib.rid, 1, body_with(scope["question"], []))
    for svid in lib.sources:
        code = last_code if svid == lib.sources[-1] else "runs_agree_candidate"
        DecisionStore(lib.store).record(lib.rid, svid, code, renew_stale=True)
        lib.store.conn.execute("UPDATE selections SET origin = 'code_rule' WHERE research_id = ? AND source_version_id = ?", (lib.rid, svid))
    if old:
        lib.discovery["budget"]["fast_path"].pop("late_revision")
        lib.store.conn.execute("UPDATE runs SET budget_json = ? WHERE id = ?", (json.dumps(lib.discovery["budget"]), lib.discovery["id"]))
    if no_evidence:
        # A screened work with no stored abstract text is recoverable from the late PDF.
        for svid in lib.sources:
            lib.store.conn.execute("DELETE FROM passages WHERE source_version_id = ? AND kind = 'abstract'", (svid,))
    cutoff(lib)
    closure = lib.store.step(lib.discovery["id"], "synthetic:fast:close", "code:small_batch_close")
    lib.store.finish_step(closure["id"], "succeeded", output={"selected_work_ids": [lib.store.source(svid)["work_id"] for svid in lib.sources[1:]]})
    run = answer_run(lib)
    asyncio.run(lib.flow.execute(run["id"]))
    lib.base_run = run
    lib.base = dict(lib.store.conn.execute("SELECT * FROM answers WHERE run_id = ?", (run["id"],)).fetchone())
    if not old:
        assert row(lib) is not None, json.dumps({"binding": lib.store.run(run["id"])["budget"]["fast_path"], "policy": lib.store.run(lib.discovery["id"])["budget"]["fast_path"], "cutoff": lib.store.existing_step(lib.discovery["id"], fast_answer.CUTOFF)["output"]})
    drain(lib)
    return lib


def drain(lib):
    while (run := lib.store.next_queued_run()) is not None:
        lib.store.update_run(run["id"], status="running")
        asyncio.run(lib.flow.execute(run["id"]))


def row(lib):
    result = lib.store.conn.execute("SELECT * FROM fast_path_late_revisions").fetchone()
    return dict(result) if result else None


def read_late(lib):
    late_revision.advance(lib.flow, lib.rid)
    assert row(lib)["status"] == "reading"
    run = lib.store.run(row(lib)["read_run_id"])
    assert run["budget"]["max_provider_requests"] == 0
    lib.store.update_run(run["id"], status="running")
    asyncio.run(lib.flow.execute(run["id"]))
    assert lib.store.run(run["id"])["status"] == "completed"
    return run


def test_append_only_revision_own_review_and_ledger(tmp_path, monkeypatch):
    lib = prepared(tmp_path)
    base_input = copy.deepcopy(fast_answer.input_plan(lib.flow, lib.base_run, lib.store.scope(lib.rid)))
    ledger = dict(lib.store.conn.execute("SELECT * FROM fast_path_ledgers").fetchone())
    stages = [dict(r) for r in lib.store.conn.execute("SELECT * FROM fast_path_stages")]
    read = read_late(lib)
    assert lib.store.run(read["id"])["usage"]["model_calls"] == 2
    late_revision.advance(lib.flow, lib.rid)
    revision = lib.store.run(row(lib)["answer_run_id"])
    assert revision["budget"]["fast_path"]["role"] == "late_revision"
    async def forbidden(*args, **kwargs):
        pytest.fail("late answer must use stored evidence without fetch or embedding")
    for method in ("_inspect", "_semantic_ranking", "_read_equations"):
        monkeypatch.setattr(lib.flow, method, forbidden)
    lib.store.update_run(revision["id"], status="running")
    asyncio.run(lib.flow.execute(revision["id"]))
    assert row(lib)["status"] == "published"
    plan = lib.store.existing_step(revision["id"], late_revision.REVISION_INPUT)["output"]
    assert plan["limit"] == len(base_input["passage_ids"]) + 1
    unchanged = base_input["items"][0]
    assert [pid for pid in plan["passage_ids"] if lib.store.passage(pid)["source_version_id"] == unchanged["source_version_id"]] == unchanged["abstract_ids"]
    upgraded = plan["items"][-1]
    assert upgraded["route"] == "fulltext" and upgraded["abstract_ids"] == []
    assert 1 <= len(upgraded["passage_ids"]) <= 2
    assert dict(lib.store.conn.execute("SELECT * FROM answers WHERE id = ?", (lib.base["id"],)).fetchone()) == lib.base
    view = views.research_view(lib.store, lib.rid)
    # The update keeps the version it revises and counts up its revision (D57).
    assert view["answers"][0]["report_version"] == lib.base["report_version"]
    assert view["answers"][0]["report_revision"] == 1 and lib.base["report_revision"] == 0
    assert view["answers"][0]["late_revision"]["upgraded_sources"] == 1
    review = lib.store.next_queued_run()
    assert review["kind"] == "answer_review" and review["target"]["answer_id"] == row(lib)["revision_answer_id"]
    drain(lib)
    assert dict(lib.store.conn.execute("SELECT * FROM fast_path_ledgers").fetchone()) == ledger
    assert [dict(r) for r in lib.store.conn.execute("SELECT * FROM fast_path_stages")] == stages
    for _ in range(3):
        late_revision.advance(lib.flow)
    assert lib.store.conn.execute("SELECT COUNT(*) FROM fast_path_late_revisions").fetchone()[0] == 1
    assert lib.store.conn.execute("SELECT COUNT(*) FROM runs WHERE kind = 'answer'").fetchone()[0] == 2


@pytest.mark.parametrize("code", ["abstract_not_found"])
def test_unresolved_route_work_with_late_text_is_read_and_answered(tmp_path, code):
    """D60: a work the abstract stage sent to its full text (no abstract, or both runs unsure) that held a K slot and
    had no reading at the cutoff waits for its text; the late read reads it and the revision answers from it."""
    lib = prepared(tmp_path, last_code=code)
    late_work = lib.store.source(lib.sources[-1])["work_id"]
    frozen = {i["work_id"]: i for i in lib.store.existing_step(lib.discovery["id"], fast_answer.CUTOFF)["output"]["items"]}
    assert frozen[late_work]["reason"] == fast_answer.UNRESOLVED_WITHOUT_FULLTEXT
    base_input = fast_answer.input_plan(lib.flow, lib.base_run, lib.store.scope(lib.rid))
    assert late_work not in {i["work_id"] for i in base_input["items"]}
    assert [i["work_id"] for i in json.loads(row(lib)["works_json"])] == [late_work]
    read_late(lib)
    late_revision.advance(lib.flow, lib.rid)
    revision = lib.store.run(row(lib)["answer_run_id"])
    lib.store.update_run(revision["id"], status="running")
    asyncio.run(lib.flow.execute(revision["id"]))
    assert row(lib)["status"] == "published"
    plan = lib.store.existing_step(revision["id"], late_revision.REVISION_INPUT)["output"]
    assert plan["upgraded"] == [late_work]
    upgraded = next(i for i in plan["items"] if i["work_id"] == late_work)
    assert upgraded["route"] == "fulltext" and len(upgraded["passage_ids"]) == 1


def test_old_frozen_policy_keeps_answer_view_and_runs(tmp_path):
    lib = prepared(tmp_path, old=True)
    before = views.research_view(lib.store, lib.rid)
    late_revision.advance(lib.flow)
    assert row(lib) is None
    assert views.research_view(lib.store, lib.rid) == before
    assert all("late_revision" not in a and "late_revision_status" not in a for a in before["answers"])
    assert lib.store.conn.execute("SELECT COUNT(*) FROM runs WHERE kind = 'answer'").fetchone()[0] == 1


@pytest.mark.parametrize("change,reason", [("user", "selection_changed_by_user")])
def test_waiting_guards(tmp_path, change, reason):
    lib = prepared(tmp_path)
    if change == "scope":
        lib.store.conn.execute("UPDATE researches SET current_scope_revision = 2 WHERE id = ?", (lib.rid,))
    elif change == "user":
        user(lib, lib.sources[-1], "excluded")
    elif change == "trash":
        lib.store.conn.execute("UPDATE researches SET trashed_at = 'synthetic' WHERE id = ?", (lib.rid,))
    elif change == "source":
        lib.store.conn.execute("UPDATE source_versions SET title = 'SYNTHETIC changed' WHERE id = ?", (lib.sources[-1],))
    else:
        run = lib.store.create_run(lib.rid, "answer", {}, None)
        lib.store.save_answer(lib.rid, run["id"], None, None, 1, "no_evidence", None, {}, selection_revision=0)
        lib.store.update_run(run["id"], status="completed")
    late_revision.advance(lib.flow)
    assert row(lib)["status"] == "skipped" and row(lib)["skip_reason"] == reason
    assert row(lib)["read_run_id"] is None


@pytest.mark.parametrize("status", ["paused"])
def test_active_or_paused_run_blocks_revision(tmp_path, status):
    lib = prepared(tmp_path)
    run = lib.store.create_run(lib.rid, "research_title", {}, None)
    lib.store.update_run(run["id"], status=status)
    late_revision.advance(lib.flow)
    assert row(lib)["status"] == "waiting_fetch"
    lib.store.update_run(run["id"], status="cancelled")
    late_revision.advance(lib.flow)
    assert row(lib)["status"] == "reading"


def test_no_pdf_and_unverified_read_do_not_publish(tmp_path):
    lib = prepared(tmp_path)
    lib.store.conn.execute("UPDATE source_assets SET removed_at = 'synthetic'")
    late_revision.advance(lib.flow)
    assert row(lib)["skip_reason"] == "no_new_fulltext"


def test_missing_peer_prevents_upgrade(tmp_path):
    lib = prepared(tmp_path)
    run = read_late(lib)
    lib.store.conn.execute("UPDATE run_steps SET status = 'failed' WHERE run_id = ? AND operation_key LIKE '%:1'", (run["id"],))
    late_revision.advance(lib.flow)
    assert row(lib)["skip_reason"] == "no_fulltext_inclusion"


def test_source_changed_after_revision_input_pauses(tmp_path):
    lib = prepared(tmp_path)
    read_late(lib)
    late_revision.advance(lib.flow)
    run = lib.store.run(row(lib)["answer_run_id"])
    lib.store.update_run(run["id"], status="running")
    plan = late_revision.revision_plan(lib.flow, run, lib.store.scope(lib.rid))
    lib.flow._small_batch_guard = {"run_id": run["id"], "rid": lib.rid, "user_signature": plan["user_signature"], "fast_answer": True, "input": plan}
    lib.store.conn.execute("UPDATE source_assets SET removed_at = 'synthetic'")
    with pytest.raises(RunStopped):
        lib.flow._checkpoint(run["id"], 1)
    assert lib.store.run(run["id"])["pause_reason"] == "source_changed"


def test_recovery_respects_paused_then_resumes_without_duplicate_calls(tmp_path):
    lib = prepared(tmp_path)
    run = read_late(lib)
    count = lib.store.run(run["id"])["usage"]["model_calls"]
    late_revision.advance(lib.flow)
    answer_id = row(lib)["answer_run_id"]
    lib.store.update_run(answer_id, status="running")
    plan = late_revision.revision_plan(lib.flow, lib.store.run(answer_id), lib.store.scope(lib.rid))
    worker = Worker(lib.store, lib.flow, tmp_path / "worker.lock")
    worker.recover()
    late_revision.advance(lib.flow)
    assert lib.store.run(answer_id)["status"] == "paused"
    assert row(lib)["answer_run_id"] == answer_id
    lib.store.update_run(answer_id, status="running")
    assert late_revision.revision_plan(lib.flow, lib.store.run(answer_id), lib.store.scope(lib.rid)) == plan
    asyncio.run(lib.flow.execute(answer_id))
    assert row(lib)["status"] == "published"
    assert lib.store.run(run["id"])["usage"]["model_calls"] == count


@pytest.mark.parametrize("all_excluded", [True])
def test_late_reads_without_inclusion_revise_as_closest_works(tmp_path, all_excluded):
    """D137: a base answer that included no work is revised from late readings that read the file without including
    the work; they join as closest works, read from their pages, and are not counted as late exclusions. D145: a late
    reading that found no criterion part does not join, and leaves the answer as a late exclusion."""
    lib = prepared(tmp_path, pdfs=2)
    from fakes import FakeAdapter, valid_response
    excluded_source = lib.sources[-1]
    def respond(si):
        output = json.loads(valid_response(si))
        if si["task_type"] == "fulltext_adjudication" and (all_excluded or si["sources"][0]["title"] == lib.store.source(excluded_source)["title"]):
            partial = all_excluded and si["sources"][0]["title"] != lib.store.source(excluded_source)["title"]
            for part in output["parts"]:
                # One work's reading finds its parts on quotes that cannot be verified; the other's finds none.
                part.update(label="present", quote="SYNTHETIC words the page does not hold") if partial \
                    else part.update(label="absent", quote="", passage_id=None)
        return json.dumps(output)
    lib.flow.deps.adapters["fake"] = FakeAdapter(respond)
    read_late(lib)
    late_revision.advance(lib.flow)
    if all_excluded:
        drain(lib)
        assert row(lib)["status"] == "published", json.dumps(json.loads(row(lib)["works_json"]))
        plan = lib.store.existing_step(row(lib)["answer_run_id"], late_revision.REVISION_INPUT)["output"]
        partless = lib.store.source(excluded_source)["work_id"]
        assert plan["late_excluded"] == [partless] and plan["upgraded"]
        # A closest work read late never pushes the answer past its frozen budget.
        assert len(plan["passage_ids"]) <= lib.store.run(row(lib)["answer_run_id"])["budget"]["max_answer_passages"]
        assert {i["answer_role"] for i in plan["items"] if i.get("upgraded")} == {"closest"}
        assert partless not in plan["upgraded"]
        status = late_revision.answer_view(lib.store, row(lib)["base_answer_id"])["late_revision_status"]
        assert status["late_excluded"] == 1
        # Its file marked wrong, the part-less work comes back to the next answer from its abstract.
        DecisionStore(lib.store).record(lib.rid, excluded_source, "human_pdf_wrong", note="SYNTHETIC wrong file")
        lib.store.conn.execute("UPDATE runs SET status = 'completed' WHERE status IN ('queued', 'running')")
        back = fast_answer.input_plan(lib.flow, answer_run(lib), lib.store.scope(lib.rid))
        assert [r["route"] for r in back["items"] if r["source_version_id"] == excluded_source] == ["abstract"]
        given = {lib.store.passage(pid)["kind"] for pid in plan["passage_ids"]}
        assert "pdf_page" in given
        # The person marks a late file wrong: the next answer reads that work from its abstract, never from the file.
        wrong = next(i for i in plan["items"] if i.get("upgraded"))
        DecisionStore(lib.store).record(lib.rid, wrong["source_version_id"], "human_pdf_wrong", note="SYNTHETIC wrong file")
        lib.store.conn.execute("UPDATE runs SET status = 'completed' WHERE status IN ('queued', 'running')")
        later = fast_answer.input_plan(lib.flow, answer_run(lib), lib.store.scope(lib.rid))
        assert all(r["route"] == "abstract" for r in later["items"] if r["work_id"] == wrong["work_id"])
    else:
        drain(lib)
        assert row(lib)["status"] == "published"
        plan = lib.store.existing_step(row(lib)["answer_run_id"], late_revision.REVISION_INPUT)["output"]
        assert plan["late_excluded"] == [lib.store.source(excluded_source)["work_id"]], json.dumps(json.loads(row(lib)["works_json"]))
        assert excluded_source not in {lib.store.passage(pid)["source_version_id"] for pid in plan["passage_ids"]}


def test_unverified_revision_is_saved_without_published_label(tmp_path):
    lib = prepared(tmp_path)
    read_late(lib)
    late_revision.advance(lib.flow)
    from fakes import FakeAdapter
    lib.flow.deps.adapters["fake"] = FakeAdapter(lambda si: '{}')
    drain(lib)
    assert row(lib)["status"] == "failed" and row(lib)["skip_reason"] == "revision_unverified"
    answers = views.research_view(lib.store, lib.rid)["answers"]
    newest = answers[0]
    assert newest["status"] == "unverified_draft"
    assert row(lib)["revision_answer_id"] == newest["id"]
    assert newest["late_revision"]["base_answer_id"] == lib.base["id"]
    shown = next((a for a in answers if not (a.get("late_revision") and a["status"] != "structurally_valid")), answers[0])
    assert shown["id"] == lib.base["id"] and shown["status"] == "structurally_valid"
    assert not lib.store.conn.execute("SELECT 1 FROM events WHERE research_id = ? AND type = 'late_revision_published'", (lib.rid,)).fetchone()
    assert newest["review"] is None


@pytest.mark.parametrize("after_save", [True])
def test_crash_after_generation_or_publication_finishes_with_own_review(tmp_path, monkeypatch, after_save):
    lib = prepared(tmp_path)
    read_late(lib)
    late_revision.advance(lib.flow)
    run_id = row(lib)["answer_run_id"]
    lib.store.update_run(run_id, status="running")
    original = lib.store.save_answer
    def crash(*args, **kwargs):
        if after_save:
            original(*args, **kwargs)
        raise RuntimeError("SYNTHETIC crash between generation and completion")
    monkeypatch.setattr(lib.store, "save_answer", crash)
    with pytest.raises(RuntimeError):
        asyncio.run(lib.flow.execute(run_id))
    calls = lib.store.run(run_id)["usage"]["model_calls"]
    Worker(lib.store, lib.flow, tmp_path / "worker.lock").recover()
    monkeypatch.setattr(lib.store, "save_answer", original)
    lib.store.update_run(run_id, status="running")
    asyncio.run(lib.flow.execute(run_id))
    assert lib.store.run(run_id)["usage"]["model_calls"] == calls
    assert row(lib)["status"] == "published"
    assert lib.store.next_queued_run()["target"]["answer_id"] == row(lib)["revision_answer_id"]
    assert lib.store.conn.execute("SELECT COUNT(*) FROM answers WHERE run_id = ?", (run_id,)).fetchone()[0] == 1
