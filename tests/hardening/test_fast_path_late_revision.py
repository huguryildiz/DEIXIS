"""D255 synthetic workflow evidence; no live provider or model calls."""

import asyncio
import copy
import json
from dataclasses import replace

import pytest

from deixis.workflow import answer as fast_answer, late_revision, views
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.flow import RunStopped
from deixis.workflow.worker import Worker
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
        from deixis.workflow import small_batch
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


@pytest.mark.parametrize("code", ["abstract_not_found", "runs_agree_unresolved"])
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


@pytest.mark.parametrize("change,reason", [("scope", "scope_revised"), ("user", "selection_changed_by_user"),
    ("trash", "research_trashed"), ("newer", "newer_answer_exists"), ("source", "source_changed")])
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


@pytest.mark.parametrize("status", ["queued", "running", "pause_requested", "paused"])
def test_active_or_paused_run_blocks_revision(tmp_path, status):
    lib = prepared(tmp_path)
    run = lib.store.create_run(lib.rid, "research_title", {}, None)
    lib.store.update_run(run["id"], status=status)
    late_revision.advance(lib.flow)
    assert row(lib)["status"] == "waiting_fetch"
    lib.store.update_run(run["id"], status="cancelled")
    late_revision.advance(lib.flow)
    assert row(lib)["status"] == "reading"


@pytest.mark.parametrize("status", ["queued", "running"])
def test_queue_must_drain(tmp_path, status):
    lib = prepared(tmp_path)
    from deixis.workflow import background_fetch
    background_fetch.enqueue(lib.store, lib.discovery, lib.listing["items"][-1], "in_flight")
    lib.store.conn.execute("UPDATE fast_path_background_fetches SET status = ?", (status,))
    late_revision.advance(lib.flow)
    assert row(lib)["status"] == "waiting_fetch"
    lib.store.conn.execute("UPDATE fast_path_background_fetches SET status = 'succeeded'")
    late_revision.advance(lib.flow)
    late_revision.advance(lib.flow)
    assert row(lib)["status"] == "reading"
    assert lib.store.conn.execute("SELECT COUNT(*) FROM runs WHERE kind = 'fulltext_adjudication'").fetchone()[0] == 1


def test_no_pdf_and_unverified_read_do_not_publish(tmp_path):
    lib = prepared(tmp_path)
    lib.store.conn.execute("UPDATE source_assets SET removed_at = 'synthetic'")
    late_revision.advance(lib.flow)
    assert row(lib)["skip_reason"] == "no_new_fulltext"


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_failed_read_is_terminal(tmp_path, status):
    lib = prepared(tmp_path)
    late_revision.advance(lib.flow)
    lib.store.update_run(row(lib)["read_run_id"], status=status)
    late_revision.advance(lib.flow)
    assert row(lib)["skip_reason"] == f"read_run_{status}"
    assert row(lib)["answer_run_id"] is None


def test_missing_peer_prevents_upgrade(tmp_path):
    lib = prepared(tmp_path)
    run = read_late(lib)
    lib.store.conn.execute("UPDATE run_steps SET status = 'failed' WHERE run_id = ? AND operation_key LIKE '%:1'", (run["id"],))
    late_revision.advance(lib.flow)
    assert row(lib)["skip_reason"] == "no_fulltext_inclusion"


def test_no_evidence_base_can_gain_revision(tmp_path):
    lib = prepared(tmp_path, no_evidence=True)
    assert lib.base["status"] == "no_evidence"
    read_late(lib)
    late_revision.advance(lib.flow)
    drain(lib)
    assert row(lib)["status"] == "published"
    plan = lib.store.existing_step(row(lib)["answer_run_id"], late_revision.REVISION_INPUT)["output"]
    assert all(lib.store.passage(pid)["kind"] == "pdf_page" for pid in plan["passage_ids"])
    assert len(plan["passage_ids"]) <= plan["limit"]


@pytest.mark.parametrize("phase", ["reading", "answering"])
def test_checkpoint_and_publication_guards(tmp_path, phase):
    lib = prepared(tmp_path)
    if phase == "reading":
        late_revision.advance(lib.flow)
        run = lib.store.run(row(lib)["read_run_id"])
    else:
        read_late(lib)
        late_revision.advance(lib.flow)
        run = lib.store.run(row(lib)["answer_run_id"])
    lib.store.update_run(run["id"], status="running")
    user(lib, lib.sources[-1], "excluded")
    with pytest.raises(RunStopped):
        lib.flow._checkpoint(run["id"], 1)
    assert row(lib)["skip_reason"] == "selection_changed_by_user"
    assert row(lib)["revision_answer_id"] is None


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


def test_atomic_transition_rolls_back(tmp_path, monkeypatch):
    lib = prepared(tmp_path)
    original = lib.store.create_run
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("SYNTHETIC crash")
    monkeypatch.setattr(lib.store, "create_run", fail)
    late_revision.advance(lib.flow)  # the failure is logged for this row (W1); its transaction is rolled back
    assert row(lib)["status"] == "waiting_fetch" and row(lib)["read_run_id"] is None
    assert lib.store.conn.execute("SELECT COUNT(*) FROM runs WHERE kind = 'fulltext_adjudication'").fetchone()[0] == 0


@pytest.mark.parametrize("all_excluded", [False, True])
def test_read_exclusions_only_trigger_revision_with_an_inclusion(tmp_path, all_excluded):
    lib = prepared(tmp_path, pdfs=2)
    from fakes import FakeAdapter, valid_response
    excluded_source = lib.sources[-1]
    def respond(si):
        output = json.loads(valid_response(si))
        if si["task_type"] == "fulltext_adjudication" and (all_excluded or si["sources"][0]["title"] == lib.store.source(excluded_source)["title"]):
            for part in output["parts"]:
                part.update(label="absent", quote="", passage_id=None)
        return json.dumps(output)
    lib.flow.deps.adapters["fake"] = FakeAdapter(respond)
    read_late(lib)
    late_revision.advance(lib.flow)
    if all_excluded:
        assert row(lib)["skip_reason"] == "no_fulltext_inclusion" and row(lib)["answer_run_id"] is None
        assert views.research_view(lib.store, lib.rid)["answers"][0]["applicability"] == "stale_selection", json.dumps(json.loads(row(lib)["works_json"]))
    else:
        drain(lib)
        assert row(lib)["status"] == "published"
        plan = lib.store.existing_step(row(lib)["answer_run_id"], late_revision.REVISION_INPUT)["output"]
        assert plan["late_excluded"] == [lib.store.source(excluded_source)["work_id"]], json.dumps(json.loads(row(lib)["works_json"]))
        assert excluded_source not in {lib.store.passage(pid)["source_version_id"] for pid in plan["passage_ids"]}


def test_late_lane_does_not_query_table_without_policy(tmp_path):
    lib = setup(tmp_path, pdf=True)
    lib.discovery["budget"]["fast_path"].pop("late_revision")
    lib.store.conn.execute("UPDATE runs SET budget_json = ? WHERE id = ?",
                           (json.dumps(lib.discovery["budget"]), lib.discovery["id"]))
    statements = []
    lib.store.conn.set_trace_callback(statements.append)
    try:
        late_revision.advance(lib.flow)
        assert late_revision.answer_view(lib.store, "missing") == {}
        run = lib.discovery | {"target": {"late_revision_id": "missing"}}
        assert late_revision.row_for_run(lib.store, run) is None
    finally:
        lib.store.conn.set_trace_callback(None)
    assert not any("FROM fast_path_late_revisions" in sql for sql in statements)


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


def test_late_review_never_starts_table(tmp_path, monkeypatch):
    lib = prepared(tmp_path)
    read_late(lib)
    late_revision.advance(lib.flow)
    lib.flow.deps.settings = replace(lib.flow.deps.settings, study_table="auto")
    from deixis.workflow import report_pipeline
    monkeypatch.setattr(report_pipeline, "after_answer", lambda *a: pytest.fail("late revision must not refresh the table"))
    drain(lib)
    assert row(lib)["status"] == "published"


def test_publication_rechecks_guard_without_await(tmp_path):
    lib = prepared(tmp_path)
    read_late(lib)
    late_revision.advance(lib.flow)
    run_id = row(lib)["answer_run_id"]
    lib.store.update_run(run_id, status="running")
    user(lib, lib.sources[-1], "excluded")
    with pytest.raises(RunStopped):
        lib.store.save_answer(lib.rid, run_id, None, None, 1, "no_evidence", None, {})
    assert row(lib)["skip_reason"] == "selection_changed_by_user"
    assert not lib.store.conn.execute("SELECT 1 FROM answers WHERE run_id = ?", (run_id,)).fetchone()


@pytest.mark.parametrize("after_save", [False, True])
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


def test_new_answer_after_late_exclusion_leaves_the_excluded_work_out(tmp_path):
    # Abstract screening admitted the work; its late full text said it does not meet the criterion. The next answer
    # the person starts must not read it from its abstract again.
    lib = prepared(tmp_path, pdfs=2)
    from fakes import FakeAdapter, valid_response
    def respond(si):
        output = json.loads(valid_response(si))
        if si["task_type"] == "fulltext_adjudication":
            for part in output["parts"]:
                part.update(label="absent", quote="", passage_id=None)
        return json.dumps(output)
    lib.flow.deps.adapters["fake"] = FakeAdapter(respond)
    read_late(lib)
    late_revision.advance(lib.flow)
    excluded = {i["work_id"] for i in json.loads(row(lib)["works_json"]) if i["late_outcome"] in ("criterion_not_met", "out_of_scope")}
    assert excluded
    base_works = {i["work_id"] for i in lib.store.existing_step(lib.base_run["id"], fast_answer.INPUT)["output"]["items"]}
    assert excluded & base_works
    run = lib.store.create_run(lib.rid, "answer", fast_answer.answer_run_budget(lib.store, lib.rid, lib.store.scope(lib.rid)), None)
    lib.store.update_run(run["id"], status="running")
    plan = fast_answer.input_plan(lib.flow, lib.store.run(run["id"]), lib.store.scope(lib.rid))
    assert not excluded & {i["work_id"] for i in plan["items"]}


@pytest.mark.parametrize("rule", [None, "split_v1"])
def test_a_late_read_reads_by_its_discoverys_read_rule(tmp_path, rule):
    """D76: the late read copies its discovery's `read_rule`; a discovery queued before the rule keeps the old read."""
    lib = prepared(tmp_path)
    budget = lib.store.run(lib.discovery["id"])["budget"]
    budget.pop("read_rule", None)
    if rule:
        budget["read_rule"] = rule
    lib.store.conn.execute("UPDATE runs SET budget_json = ? WHERE id = ?", (json.dumps(budget), lib.discovery["id"]))
    run = read_late(lib)
    plan = lib.store.existing_step(run["id"], f"late:{lib.discovery['id']}:adjudication_plan")["output"]
    assert run["budget"].get("read_rule") == rule and plan.get("read_rule") == rule


def test_one_failing_late_row_holds_up_neither_the_other_rows_nor_the_queue(tmp_path, monkeypatch, caplog):
    # A code error on one row (here a KeyError from its guard) is logged; the next row still moves on, and the worker
    # still starts the run that row queued instead of ending its loop until a restart.
    lib = prepared(tmp_path)
    bad = row(lib)
    good = bad | {"id": "late-synthetic-second", "ledger_run_id": lib.base_run["id"]}
    lib.store.conn.execute(f"INSERT INTO fast_path_late_revisions ({', '.join(good)}) VALUES ({', '.join('?' * len(good))})",
                           tuple(good.values()))
    original = late_revision.guard_reason
    def guard(store, late):
        if late["id"] == bad["id"]:
            raise KeyError("SYNTHETIC missing field")
        return original(store, late)
    monkeypatch.setattr(late_revision, "guard_reason", guard)
    caplog.set_level("INFO")
    late_revision.advance(lib.flow)
    rows = {r["id"]: dict(r) for r in lib.store.conn.execute("SELECT * FROM fast_path_late_revisions")}
    assert rows[bad["id"]]["status"] == "waiting_fetch" and rows[good["id"]]["status"] == "reading"
    read_id = rows[good["id"]]["read_run_id"]
    assert lib.store.run(read_id)["status"] == "queued"

    async def execute(run_id):
        lib.store.update_run(run_id, event="run_completed", status="completed")
    monkeypatch.setattr(lib.flow, "execute", execute)

    async def main():
        worker = Worker(lib.store, lib.flow, tmp_path / "worker.lock")
        task = asyncio.create_task(worker._run_forever())
        deadline = asyncio.get_running_loop().time() + 5
        while lib.store.run(read_id)["status"] != "completed" and not task.done():
            assert asyncio.get_running_loop().time() < deadline, "the queued run never started"
            await asyncio.sleep(0.01)
        assert not task.done(), task.exception()
        await worker.stop()
        await asyncio.wait_for(task, 3)

    asyncio.run(main())
    assert lib.store.run(read_id)["status"] == "completed"
    assert any(bad["id"] in r.getMessage() for r in caplog.records)


def test_followup_pool_leaves_out_a_work_the_late_full_text_excluded(tmp_path):
    # The answer froze the work from its abstract; its late full text then found the criterion not met. A follow-up
    # must not read it again, as a new answer does not (`fast_answer.input_plan`).
    from deixis.workflow import followup
    from fakes import FakeAdapter, valid_response
    lib = prepared(tmp_path, pdfs=2)
    def respond(si):
        output = json.loads(valid_response(si))
        if si["task_type"] == "fulltext_adjudication":
            for part in output["parts"]:
                part.update(label="absent", quote="", passage_id=None)
        return json.dumps(output)
    lib.flow.deps.adapters["fake"] = FakeAdapter(respond)
    base_items = lib.store.existing_step(lib.base_run["id"], fast_answer.INPUT)["output"]["items"]
    before = followup.pool(lib.store, lib.rid, 1, lib.flow)
    read_late(lib)
    late_revision.advance(lib.flow)
    excluded = late_revision.excluded_works(lib.store, lib.rid, 1)
    gone = {i["source_version_id"] for i in base_items if i["work_id"] in excluded}
    assert gone and gone <= set(before["sources"])
    after = followup.pool(lib.store, lib.rid, 1, lib.flow)
    assert not gone & set(after["sources"]), json.dumps(after["sources"])
    assert not gone & set(after["reserve"]), json.dumps(after["reserve"])
    kept = {i["source_version_id"] for i in base_items if i["work_id"] not in excluded}
    assert kept <= set(after["sources"])


def test_an_unused_question_revision_leaves_the_waiting_late_revision_open(tmp_path):
    # D67: opening a revision and running nothing under it must not end the late revision of the one it was opened
    # from, nor write an event that refuses the withdrawal; once it is withdrawn, the late revision goes on.
    lib = prepared(tmp_path)
    lib.store.revise_scope(lib.rid, lib.store.research(lib.rid)["version"], "SYNTHETIC another question", None)
    asyncio.run(Worker(lib.store, lib.flow, tmp_path / "worker.lock")._turn())
    assert row(lib)["status"] == "waiting_fetch" and row(lib)["skip_reason"] is None
    assert lib.store.withdrawal(lib.rid)["allowed"], lib.store.withdrawal(lib.rid)
    research = lib.store.research(lib.rid)
    assert lib.store.withdraw_revision(lib.rid, research["version"], 2) == 1
    late_revision.advance(lib.flow)
    assert row(lib)["status"] == "reading"


def test_a_used_question_revision_still_ends_the_late_revision(tmp_path):
    lib = prepared(tmp_path)
    lib.store.revise_scope(lib.rid, lib.store.research(lib.rid)["version"], "SYNTHETIC another question", None)
    run = lib.store.create_run(lib.rid, "discovery", {}, None)
    assert run["scope_revision"] == 2
    late_revision.advance(lib.flow)
    assert row(lib)["status"] == "waiting_fetch"  # whether the revision is used is not known while its run is queued
    lib.store.update_run(run["id"], status="completed")
    late_revision.advance(lib.flow)
    assert row(lib)["status"] == "skipped" and row(lib)["skip_reason"] == "scope_revised"
    assert lib.store.withdrawal(lib.rid)["allowed"] is False


def test_a_paused_run_keeps_the_parent_late_revision_open_until_it_settles(tmp_path):
    # While a run of the research is paused the withdrawal cannot be decided (D67), so the late revision of the parent
    # revision waits with no event; once the newer revision's run settles, that revision is used and the row is skipped.
    lib = prepared(tmp_path)
    lib.store.revise_scope(lib.rid, lib.store.research(lib.rid)["version"], "SYNTHETIC another question", None)
    run = lib.store.create_run(lib.rid, "discovery", {}, None)
    lib.store.update_run(run["id"], status="paused", pause_reason="user")
    for _ in range(2):
        late_revision.advance(lib.flow)
    assert row(lib)["status"] == "waiting_fetch" and row(lib)["skip_reason"] is None
    assert not lib.store.conn.execute("SELECT 1 FROM events WHERE research_id = ? AND type = 'late_revision_skipped'",
                                      (lib.rid,)).fetchone()
    lib.store.update_run(run["id"], status="completed")
    late_revision.advance(lib.flow)
    assert row(lib)["status"] == "skipped" and row(lib)["skip_reason"] == "scope_revised"


def test_the_same_failing_row_is_logged_once_and_a_different_failure_again(tmp_path, monkeypatch, caplog):
    lib = prepared(tmp_path)
    late = row(lib)
    message = ["SYNTHETIC first failure"]
    def guard(store, row):
        raise KeyError(message[0])
    monkeypatch.setattr(late_revision, "guard_reason", guard)
    caplog.set_level("INFO", logger="deixis.late_revision")
    logged = lambda: len([r for r in caplog.records if late["id"] in r.getMessage()])
    for _ in range(3):
        late_revision.advance(lib.flow)
    assert logged() == 1
    message[0] = "SYNTHETIC second failure"
    for _ in range(2):
        late_revision.advance(lib.flow)
    assert logged() == 2


def test_two_unused_revisions_in_a_row_leave_the_late_revision_open(tmp_path):
    # Revisions 1 -> 2 -> 3, nothing run under 2 or 3: withdrawing 3 and then 2 brings revision 1 back, so its late
    # revision waits with no event, and goes on once the research is back on it.
    lib = prepared(tmp_path)
    for question in ("SYNTHETIC second question", "SYNTHETIC third question"):
        lib.store.revise_scope(lib.rid, lib.store.research(lib.rid)["version"], question, None)
    assert lib.store.scope(lib.rid)["revision"] == 3 and lib.store.scope(lib.rid)["parent_revision"] == 2
    late_revision.advance(lib.flow)
    assert row(lib)["status"] == "waiting_fetch" and row(lib)["skip_reason"] is None
    for revision in (3, 2):
        assert lib.store.withdrawal(lib.rid)["allowed"], lib.store.withdrawal(lib.rid)
        lib.store.withdraw_revision(lib.rid, lib.store.research(lib.rid)["version"], revision)
        late_revision.advance(lib.flow)
        assert row(lib)["status"] == ("waiting_fetch" if revision == 3 else "reading")
    assert lib.store.research(lib.rid)["current_scope_revision"] == 1


def test_a_used_revision_between_ends_the_late_revision(tmp_path):
    # 1 -> 2 (a search run under it) -> 3 (unused): withdrawing 3 would leave the research on 2, which stays, so
    # revision 1's late revision is skipped as before.
    lib = prepared(tmp_path)
    lib.store.revise_scope(lib.rid, lib.store.research(lib.rid)["version"], "SYNTHETIC second question", None)
    run = lib.store.create_run(lib.rid, "discovery", {}, None)
    lib.store.update_run(run["id"], status="completed")
    lib.store.revise_scope(lib.rid, lib.store.research(lib.rid)["version"], "SYNTHETIC third question", None)
    late_revision.advance(lib.flow)
    assert row(lib)["status"] == "skipped" and row(lib)["skip_reason"] == "scope_revised"
