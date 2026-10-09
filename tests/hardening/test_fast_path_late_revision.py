"""D255 synthetic workflow evidence; no live provider or model calls."""

import asyncio
import copy
import json
import shutil
from dataclasses import replace

import pytest

from deixis.storage import db
from deixis.storage.db import transaction
from deixis.workflow import fast_answer, late_revision, views
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.flow import RunStopped
from deixis.workflow.store import legacy_inspection_policy_removed
from deixis.workflow.worker import Worker
from test_fast_path_answer import setup, cutoff, answer_run, user
from test_criterion_passage_flow import body_with, TOPIC_PAGE, page_source


def prepared(tmp_path, *, old=False, no_evidence=False, pdfs=1):
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
        DecisionStore(lib.store).record(lib.rid, svid, "runs_agree_candidate", renew_stale=True)
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
    assert not legacy_inspection_policy_removed(lib.store, run)
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
    assert view["answers"][0]["report_version"] == lib.base["report_version"] + 1
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
    with pytest.raises(RuntimeError):
        late_revision.advance(lib.flow)
    assert row(lib)["status"] == "waiting_fetch" and row(lib)["read_run_id"] is None
    assert lib.store.conn.execute("SELECT COUNT(*) FROM runs WHERE kind = 'fulltext_adjudication'").fetchone()[0] == 0


def test_migration_preserves_existing_rows(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "upgrade.sqlite")
    original = db.MIGRATIONS_DIR
    old = tmp_path / "migrations"
    old.mkdir()
    for path in original.glob("*.sql"):
        if int(path.name[:4]) <= 76:
            shutil.copyfile(path, old / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", old)
    db.migrate(conn)
    from deixis.workflow.store import Store
    store = Store(conn)
    rid = store.create_research("SYNTHETIC migration", "attached", "quick", [], "fake", "fake-model", None)
    before = dict(store.research(rid))
    runs_sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'runs'").fetchone()[0]
    monkeypatch.setattr(db, "MIGRATIONS_DIR", original)
    assert db.migrate(conn) == [77]
    assert store.research(rid) == before
    assert conn.execute("SELECT sql FROM sqlite_master WHERE name = 'runs'").fetchone()[0] == runs_sql
    assert 77 in {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


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


@pytest.mark.parametrize("policy,table", [(False, True), (True, False), (False, False)])
def test_late_lane_does_not_query_table_without_policy_or_migration(tmp_path, policy, table):
    lib = setup(tmp_path, pdf=True)
    if not policy:
        lib.discovery["budget"]["fast_path"].pop("late_revision")
        lib.store.conn.execute("UPDATE runs SET budget_json = ? WHERE id = ?",
                               (json.dumps(lib.discovery["budget"]), lib.discovery["id"]))
    if not table:
        lib.store.conn.execute("DROP TABLE fast_path_late_revisions")
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
