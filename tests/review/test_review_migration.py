"""Migration 0064 preserves old rows, schema objects and foreign-key enforcement."""

import re
import shutil
import sqlite3
from types import SimpleNamespace

import pytest

from deixis.storage import db
from deixis.workflow.review.store import ReviewStore, TARGET_KINDS, FOCUSES, DECISIONS, purge_owner_reviews, snapshot_referenced_source_versions
from tests.review.review_helpers import make_answer, all_rows, review_run
from tests.report.test_report_assembly import report_with_sections
from tests.report.test_report_edit_check import finish


def objects(conn):
    return {(r["type"], r["name"]): (r["tbl_name"], r["sql"]) for r in conn.execute(
        "SELECT * FROM sqlite_master WHERE type IN ('trigger', 'index')")}


def dependencies(lib):
    from deixis.workflow.candidates.store import CandidateStore
    from deixis.workflow.lineage.store import LineageStore
    from tests.candidates.test_candidate_store import version, with_hits, publish, attach_asset
    conn = lib["conn"]; store = lib["store"]; rid = lib["rid"]
    table = conn.execute("SELECT table_id FROM report_snapshot").fetchone()[0]
    ns = SimpleNamespace(conn=conn, store=store, rid=rid, candidate_store=CandidateStore(store),
                         tid=table, ids={"a": lib["source_id"]}, passages={"a": lib["section_passage"]})
    asset, _ = attach_asset(ns, lib["source_id"])
    v = version(ns); search, records = with_hits(ns, v); publish(ns, search, records)
    aid = make_answer(lib)
    answer = dict(conn.execute("SELECT * FROM answers WHERE id = ?", (aid,)).fetchone())
    run, step, sti = answer["run_id"], answer["step_id"], answer["step_input_id"]
    conn.execute("INSERT INTO model_sessions (id, research_id, run_id, step_id, step_input_id, connection, status, started_at)"
                 " VALUES ('msn_SYNTHETIC', ?, ?, ?, ?, 'fake', 'completed', 'now')", (rid, run, step, sti))
    conn.execute("INSERT INTO search_runs (id, research_id, run_id, step_id, provider, query_text, request_description, access_mode, status, page_limit, retrieved_at)"
                 " VALUES ('src_SYNTHETIC', ?, ?, ?, 'openalex', 'SYNTHETIC', '{}', 'api', 'zero_results', 1, 'now')", (rid, run, step))
    conn.execute("INSERT INTO answer_reviews (id, answer_id, research_id, run_id, status, created_at) VALUES ('arv_SYNTHETIC', ?, ?, ?, 'completed', 'now')", (aid, rid, run))
    conn.execute("INSERT INTO person_pdf_requests (id, research_id, source_version_id, asset_id, scope_revision, status, run_id, created_at, updated_at)"
                 " VALUES ('ppr_SYNTHETIC', ?, ?, ?, 1, 'waiting', ?, 'now', 'now')", (rid, lib["source_id"], asset, run))
    conn.execute("INSERT INTO chain_links (research_id, scope_revision, run_id, seed_source_version_id, linked_openalex_id, direction, passed_filter)"
                 " VALUES (?, 1, ?, ?, 'SYNTHETIC-W2', 'forward', 1)", (rid, run, lib["source_id"]))
    other = store.create_upload_source("SYNTHETIC other lineage source")
    store.add_to_corpus(rid, other, "user_upload", selection_state="included", selection_origin="user")
    pair = LineageStore(store).ensure_link(table, lib["source_id"], other)
    conn.execute("INSERT INTO lineage_link_revisions (id, link_id, kind, author, decision, disposition, relation, what_changed, support_type, origin, run_id, created_at)"
        " VALUES ('llr_SYNTHETIC', ?, 'human_add', 'human', 'link', 'accepted', 'extends', 'SYNTHETIC change', 'source_stated', 'human', ?, 'now')", (pair["id"], run))


@pytest.mark.parametrize("populated", [True, False])
def test_review_migration_keeps_every_old_run_and_every_dependent_row(tmp_path, monkeypatch, populated):
    real = db.MIGRATIONS_DIR; old = tmp_path / "migrations"; old.mkdir()
    for path in real.glob("*.sql"):
        if int(path.name[:4]) <= 63: shutil.copy(path, old / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", old)
    fixture = None
    if populated:
        fixture = report_with_sections.__wrapped__(tmp_path); lib = next(fixture)
        lib["rid"] = finish(lib); lib["conn"] = lib["store"].conn
        conn = lib["conn"]; dependencies(lib)
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'runs'").fetchone()[0]
        kinds = re.findall(r"'([^']+)'", re.search(r"kind IN \(([^)]+)\)", sql).group(1))
        for n, kind in enumerate(kinds):
            conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, usage_json, version, target_json, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, 'claim_check', '{\"limit\":7}', '{\"used\":2}', ?, '{\"SYNTHETIC\":true}', ?, ?)",
                (db.new_id("run"), lib["rid"], n + 1, kind, ("queued", "running", "pause_requested", "paused", "completed", "failed", "cancelled")[n % 7], n + 2, f"created-{n}", f"updated-{n}"))
    else:
        conn = db.connect(tmp_path / "library.sqlite"); db.migrate(conn)
    try:
        before = all_rows(conn); before.pop("schema_migrations")
        old_objects = objects(conn)
        fks = {table: [tuple(r) for r in conn.execute(f'PRAGMA foreign_key_list("{table}")')] for table in before}
        if populated:
            dependent_tables = {table for table, keys in fks.items() if any(row[2] == "runs" for row in keys)}
            assert len(dependent_tables) == 12
            assert all(before[t] for t in dependent_tables)
        shutil.copy(real / "0064_owner_reviews.sql", old / "0064_owner_reviews.sql")
        assert db.migrate(conn) == [64]
        assert {t: all_rows(conn)[t] for t in before} == before
        after_objects = objects(conn)
        assert {key: after_objects[key] for key in old_objects} == old_objects
        assert all(name.startswith("owner_review") or name.startswith("sqlite_autoindex_owner_review") for _, name in after_objects.keys() - old_objects.keys())
        assert {table: [tuple(r) for r in conn.execute(f'PRAGMA foreign_key_list("{table}")')] for table in before} == fks
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("SELECT sql FROM sqlite_master WHERE name = 'runs_status'").fetchone()[0] == "CREATE INDEX runs_status ON runs(status, created_at)"
        if not populated:
            conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_SYNTHETIC', 'SYNTHETIC', 'now', 'now')")
            rid = "res_SYNTHETIC"
        else: rid = lib["rid"]
        for kind in ("review", "invented"):
            statement = "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at) VALUES (?, ?, 1, ?, 'completed', 'claim_check', '{}', 'now', 'now')"
            if kind == "invented":
                with pytest.raises(sqlite3.IntegrityError): conn.execute(statement, ("run_invented", rid, kind))
            else: conn.execute(statement, ("run_review", rid, kind))
        assert ReviewStore(conn).reviews_for_target(rid, "answer", "missing") == []
    finally:
        if fixture:
            with pytest.raises(StopIteration): next(fixture)
        else: conn.close()


def test_all_four_tables_have_no_hidden_rowid_and_explicit_foreign_keys(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite"); db.migrate(conn)
    expected = {"owner_review_snapshots": {("research_id", "researches", "id")},
                "owner_reviews": {("research_id", "researches", "id"), ("snapshot_id", "owner_review_snapshots", "id"), ("run_id", "runs", "id")},
                "owner_review_findings": {("review_id", "owner_reviews", "id"), ("step_input_id", "step_inputs", "id")},
                "owner_review_decisions": {("finding_id", "owner_review_findings", "id")}}
    try:
        for table, keys in expected.items():
            assert "WITHOUT ROWID" in conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()[0]
            assert {(r[3], r[2], r[4]) for r in conn.execute(f"PRAGMA foreign_key_list({table})")} == keys
            with pytest.raises(sqlite3.OperationalError, match="rowid"):
                conn.execute(f"INSERT OR REPLACE INTO {table} (rowid, id) VALUES (1, 'SYNTHETIC')")
    finally: conn.close()


def test_python_vocabularies_equal_sql_checks(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite"); db.migrate(conn)
    try:
        for table, column, values in (("owner_review_snapshots", "target_kind", TARGET_KINDS), ("owner_reviews", "focus", FOCUSES), ("owner_review_decisions", "decision", DECISIONS)):
            sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()[0]
            assert tuple(re.findall(r"'([^']+)'", re.search(rf'{column} IN \(([^)]+)\)', sql).group(1))) == values
    finally: conn.close()


def test_purge_helpers_explicitly_support_schema_without_review_tables(tmp_path, monkeypatch):
    old = tmp_path / "migrations"; old.mkdir()
    for p in db.MIGRATIONS_DIR.glob("*.sql"):
        if int(p.name[:4]) <= 62: shutil.copy(p, old / p.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", old)
    conn = db.connect(tmp_path / "library.sqlite"); db.migrate(conn)
    try:
        before = all_rows(conn)
        assert snapshot_referenced_source_versions(conn, ["SYNTHETIC"]) == set()
        purge_owner_reviews(conn, "SYNTHETIC")
        assert all_rows(conn) == before
    finally: conn.close()
