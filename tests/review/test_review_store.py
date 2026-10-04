"""Direct SQLite guard tests and append-only owner decisions on synthetic records."""

import copy
import json
import sqlite3

import pytest

from deixis.storage import db
from deixis.domain.rules import RevisionConflict
from deixis.workflow.review.store import applied_matches_suggestion, resolve_finding, TARGET_KINDS, FOCUSES, DECISIONS
from tests.review_helpers import report_with_sections, review_lib, stored_review, snapshot, review_run, step_payload, rows
from tests.report.test_report_claim_links import edit, claim

TABLES = ("owner_review_snapshots", "owner_reviews", "owner_review_findings", "owner_review_decisions")
KEYS = [(TABLES[0], "id"), (TABLES[1], "id"), (TABLES[1], "run_id"), (TABLES[1], "idempotency_key"),
        (TABLES[2], "id"), (TABLES[2], "review_id,ordinal"), (TABLES[3], "id"), (TABLES[3], "finding_id,ordinal")]


def populated(lib):
    saved, review, payload, fid = stored_review(lib)
    lib["reviews"].add_decision(fid, "deferred")
    return saved, review, payload, fid


@pytest.mark.parametrize("blank", ["", " \t\r\n", "\u00a0\u2003"])
@pytest.mark.parametrize("field", ["owner_note", "reason"])
def test_sql_boundary_refuses_blank_notes_and_dismissal_reasons(review_lib, blank, field):
    lib = review_lib; saved, _, _, fid = stored_review(lib)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        if field == "owner_note":
            run = review_run(lib)
            lib["conn"].execute("INSERT INTO owner_reviews (id, research_id, snapshot_id, run_id, focus, owner_note, requested_connection, created_at)"
                                " VALUES (?, ?, ?, ?, 'source_support', ?, 'fake', 'now')",
                                (db.new_id("orv"), lib["rid"], saved["id"], run, blank))
        else:
            lib["conn"].execute("INSERT INTO owner_review_decisions (id, finding_id, ordinal, decision, reason, applied_ref, created_at) VALUES (?, ?, 1, 'dismissed', ?, NULL, 'now')",
                                (db.new_id("ord"), fid, blank))


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize("operation", ["update", "delete"])
def test_immutable_rows_and_frozen_review_identity_refuse_mutation(review_lib, table, operation):
    lib = review_lib; populated(lib); before = rows(lib["conn"], table)
    sql = f"DELETE FROM {table}" if operation == "delete" else f"UPDATE {table} SET id = 'changed'"
    with pytest.raises(sqlite3.IntegrityError): lib["conn"].execute(sql)
    assert rows(lib["conn"], table) == before


@pytest.mark.parametrize("table,key", KEYS)
@pytest.mark.parametrize("form", ["INSERT", "INSERT OR REPLACE", "UPSERT"])
def test_every_unique_key_blocks_conflicting_insert_replace_and_upsert(review_lib, table, key, form):
    lib = review_lib; saved, review, payload, fid = populated(lib); conn = lib["conn"]
    # REPLACE normally deletes without firing a delete trigger at this setting.
    # WITHOUT ROWID removes the hidden unique rowid bypass; sqlite_master below pins it.
    conn.execute("PRAGMA recursive_triggers = OFF")
    if key == "idempotency_key":
        other_run = review_run(lib)
        lib["reviews"].create_review(lib["rid"], saved["id"], other_run, focus="source_support", requested_connection="fake", idempotency_key="SYNTHETIC-key")
        original = dict(conn.execute("SELECT * FROM owner_reviews WHERE idempotency_key IS NOT NULL").fetchone())
    else: original = dict(conn.execute(f"SELECT * FROM {table} LIMIT 1").fetchone())
    before = rows(conn, table); new = copy.deepcopy(original)
    if key != "id": new["id"] = db.new_id("syn")
    if table == "owner_reviews":
        new["focus"] = "assumptions_and_consistency"
        if key != "run_id": new["run_id"] = review_run(lib)
        if key != "idempotency_key": new["idempotency_key"] = db.new_id("key")
    elif table == "owner_review_snapshots": new["target_id"] = "SYNTHETIC another target"
    elif table == "owner_review_findings":
        new["finding_json"] = '{"SYNTHETIC":"changed"}'
        if key == "id": new["ordinal"] += 1
    elif table == "owner_review_decisions":
        new["decision"] = "accepted"
        if key == "id": new["ordinal"] += 1
    statement = "INSERT" if form == "UPSERT" else form
    statement += f" INTO {table} ({','.join(new)}) VALUES ({','.join('?' for _ in new)})"
    if form == "UPSERT": statement += f" ON CONFLICT ({key}) DO UPDATE SET id = excluded.id"
    with pytest.raises(sqlite3.IntegrityError): conn.execute(statement, tuple(new.values()))
    assert rows(conn, table) == before


@pytest.mark.parametrize("column", ["research_id", "snapshot_id", "run_id", "focus", "owner_note", "requested_connection", "requested_model", "requested_effort", "idempotency_key", "created_at"])
def test_each_review_frozen_column_is_guarded(review_lib, column):
    lib = review_lib; populated(lib); before = rows(lib["conn"], "owner_reviews")
    with pytest.raises(sqlite3.IntegrityError): lib["conn"].execute(f"UPDATE owner_reviews SET {column} = 'changed'")
    assert rows(lib["conn"], "owner_reviews") == before


def test_only_failure_and_coverage_columns_are_mutable(review_lib):
    lib = review_lib; _, review, _, _ = populated(lib)
    lib["reviews"].set_failure(review["id"], "SYNTHETIC failure")
    lib["reviews"].set_not_reviewed(review["id"], [{"claim_ref": "III.1", "reason": "input_too_large"}])
    row = lib["reviews"].reviews_for_target(lib["rid"], "report", lib["report_id"])[0]
    assert row["failure_reason"] == "SYNTHETIC failure"
    assert json.loads(row["sections_not_reviewed_json"])[0]["reason"] == "input_too_large"


@pytest.mark.parametrize("case", ["wrong_kind", "wrong_research", "snapshot_research", "finding_step"])
def test_run_snapshot_and_step_guards(review_lib, case):
    lib = review_lib; saved = snapshot(lib)
    other = lib["store"].create_research("SYNTHETIC other", "attached", "quick", [], "fake", None, "en")
    rid = other if case == "snapshot_research" else lib["rid"]
    run_id = review_run(lib, kind="answer" if case == "wrong_kind" else "review", research_id=other if case in {"wrong_research", "snapshot_research"} else None)
    if case == "finding_step":
        review = lib["reviews"].create_review(rid, saved["id"], run_id, focus="source_support", requested_connection="fake")
        payload = step_payload(lib, saved)  # another review run
        with pytest.raises(sqlite3.IntegrityError):
            lib["reviews"].add_findings(review["id"], [resolve_finding(saved["content"], payload, {"target_ref": {"kind": "whole", "ref": None}})])
    else:
        with pytest.raises(sqlite3.IntegrityError):
            lib["reviews"].create_review(rid, saved["id"], run_id, focus="source_support", requested_connection="fake")


@pytest.mark.parametrize("table,column", [(TABLES[0], "research_id"), (TABLES[1], "research_id"), (TABLES[1], "snapshot_id"), (TABLES[1], "run_id"), (TABLES[2], "review_id"), (TABLES[2], "step_input_id"), (TABLES[3], "finding_id")])
def test_nonexistent_parent_is_rejected(review_lib, table, column):
    lib = review_lib; populated(lib); conn = lib["conn"]
    original = dict(conn.execute(f"SELECT * FROM {table} LIMIT 1").fetchone())
    original["id"] = db.new_id("syn"); original[column] = "missing"
    if "ordinal" in original: original["ordinal"] += 10
    if "run_id" in original and column != "run_id": original["run_id"] = review_run(lib)
    before = rows(conn, table)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(f"INSERT INTO {table} ({','.join(original)}) VALUES ({','.join('?' for _ in original)})", tuple(original.values()))
    assert rows(conn, table) == before


def test_review_request_idempotency_is_bound_to_fields(review_lib):
    lib = review_lib; saved = snapshot(lib); run = review_run(lib)
    args = dict(focus="source_support", requested_connection="fake", idempotency_key="SYNTHETIC")
    row = lib["reviews"].create_review(lib["rid"], saved["id"], run, **args)
    assert lib["reviews"].create_review(lib["rid"], saved["id"], run, **args) == row
    with pytest.raises(RevisionConflict):
        lib["reviews"].create_review(lib["rid"], saved["id"], run, **(args | {"owner_note": "different"}))


def test_decision_ordinals_override_timestamp_and_id_order(review_lib):
    lib = review_lib; saved, review, payload, fid = stored_review(lib); store = lib["reviews"]
    assert store.current_decision(fid) is None
    for id_, ordinal in (("ord_ZZZZZZZZ", 1), ("ord_AAAAAAAA", 2)):
        lib["conn"].execute("INSERT INTO owner_review_decisions (id, finding_id, ordinal, decision, reason, applied_ref, created_at) VALUES (?, ?, ?, 'deferred', NULL, NULL, 'same')", (id_, fid, ordinal))
    assert [r["ordinal"] for r in store.decisions(fid)] == [1, 2]
    assert store.current_decision(fid)["id"] == "ord_AAAAAAAA"
    assert store.add_decision(fid, "accepted")["ordinal"] == 3
    other = store.add_findings(review["id"], [resolve_finding(saved["content"], payload, {"target_ref": {"kind": "whole", "ref": None}})])[0]
    assert [store.add_decision(other, d, "SYNTHETIC reason")["ordinal"] for d in DECISIONS] == [1, 2, 3]


@pytest.mark.parametrize("decision,reason,applied", [("dismissed", None, None), ("dismissed", " \t\n", None), ("deferred", None, "revision"), ("invented", None, None)])
def test_decision_rules(review_lib, decision, reason, applied):
    lib = review_lib; _, _, _, fid = stored_review(lib)
    with pytest.raises(ValueError): lib["reviews"].add_decision(fid, decision, reason, applied)
    assert lib["reviews"].decisions(fid) == []


@pytest.mark.parametrize("case", ["missing", "wrong_claim", "wrong_kind", "too_early", "unchanged", "answer", "whole"])
def test_applied_ref_rejections(review_lib, monkeypatch, case):
    lib = review_lib; saved, review, _, fid = stored_review(lib, "answer" if case == "answer" else "report")
    if case == "whole":
        # A separate whole-target finding, since findings are immutable.
        payload = step_payload(lib, saved, review["run_id"])
        fid = lib["reviews"].add_findings(review["id"], [resolve_finding(saved["content"], payload, {"target_ref": {"kind": "whole", "ref": None}})])[0]
    target = next(c for c in saved["content"]["claims"] if c["claim_ref"] == saved["content"]["claims"][0]["claim_ref"])
    other = claim(lib, "III.1" if target["claim_ref"] == "abstract.1" else "abstract.1")
    revision_id = db.new_id("rcv")
    if case != "missing":
        lib["conn"].execute("INSERT INTO report_claim_revisions (id, claim_id, kind, text, created_at) VALUES (?, ?, ?, ?, ?)",
            (revision_id, other["id"] if case in {"wrong_claim", "answer"} else target["claim_id"],
             "human_edit", target["text"] if case == "unchanged" else "SYNTHETIC edit",
             "1900" if case == "too_early" else "2099"))
    if case == "wrong_kind":
        # The real SQL CHECK already restricts kinds. Exercise the store's own guard
        # through a reader proxy without weakening that CHECK or an immutable row.
        original = lib["reader"].report_claim_revisions
        monkeypatch.setattr(lib["reader"], "report_claim_revisions", lambda cid: [
            r | {"kind": "model"} for r in original(cid)])
    with pytest.raises(ValueError): lib["reviews"].add_decision(fid, "accepted", applied_ref=revision_id)
    assert lib["reviews"].decisions(fid) == []


@pytest.mark.parametrize("case", ["unrelated", "suggestion", "citations_only"])
def test_later_human_revision_is_recorded_without_claiming_editor_origin(review_lib, case):
    lib = review_lib; saved, review, _, fid = stored_review(lib)
    target = saved["content"]["claims"][0]
    request = {"link_ids": []} if case == "citations_only" else {"text": "SYNTHETIC suggested text." if case == "suggestion" else "SYNTHETIC unrelated human text."}
    revision = edit(lib, key=target["claim_ref"], **request)
    decision = lib["reviews"].add_decision(fid, "accepted", applied_ref=revision)
    assert decision["applied_ref"] == revision
    text = lib["conn"].execute("SELECT text FROM report_claim_revisions WHERE id = ?", (revision,)).fetchone()[0]
    assert applied_matches_suggestion(lib["reviews"].findings(review["id"])[0]["finding"], text) == (case == "suggestion")


@pytest.mark.parametrize("legacy", [False, True])
def test_applied_ref_reads_revision_citations_through_reader(review_lib, monkeypatch, legacy):
    lib = review_lib; saved, review, _, fid = stored_review(lib)
    target = saved["content"]["claims"][0]
    if legacy:
        revision = db.new_id("rcv")
        lib["conn"].execute("INSERT INTO report_claim_revisions (id, claim_id, kind, text, created_at)"
            " VALUES (?, ?, 'human_edit', 'SYNTHETIC legacy text', '2099')", (revision, target["claim_id"]))
    else:
        revision = edit(lib, key=target["claim_ref"], link_ids=[])
    calls = []
    for name in ("report_claim_revisions", "report_original_links"):
        original = getattr(lib["reader"], name)
        def read(cid, _name=name, _original=original):
            calls.append((_name, cid))
            return _original(cid)
        monkeypatch.setattr(lib["reader"], name, read)
    assert lib["reviews"].add_decision(fid, "accepted", applied_ref=revision)["applied_ref"] == revision
    assert calls == [("report_claim_revisions", target["claim_id"])] + (
        [("report_original_links", target["claim_id"])] if legacy else [])
