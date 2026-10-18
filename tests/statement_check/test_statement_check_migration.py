"""0009_statement_check.sql (reverse citation search, R1) on a library made up to 0008 and on a fresh one. Libraries
here are SYNTHETIC."""

import shutil
import sqlite3

import pytest

from deixis.storage import db

TRIGGERS = ("kill_searches_run_guard", "owner_reviews_run_guard", "watch_checks_run_guard")


def schema(conn):
    return sorted(tuple(row) for row in conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master"))


def test_a_library_made_up_to_0008_takes_0009_and_keeps_its_rows(tmp_path, monkeypatch):
    before = tmp_path / "migrations"
    before.mkdir()
    for path in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
        if int(path.name.split("_", 1)[0]) < 9:
            shutil.copy(path, before)
    path = tmp_path / "library.sqlite"
    with monkeypatch.context() as patch:
        patch.setattr(db, "MIGRATIONS_DIR", before)
        conn = db.connect(path)
        assert db.migrate(conn)[-1] == 8
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at, intent) VALUES ('res_1', 'SYNTHETIC', 'n', 'n', 'compare')")
    conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
                 " VALUES ('run_1', 'res_1', 1, 'snowball', 'completed', 'screening', '{}', 'n', 'n')")
    for statement in ("UPDATE researches SET intent = 'statement' WHERE id = 'res_1'",
                      "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at,"
                      " updated_at) VALUES ('run_2', 'res_1', 1, 'statement_check', 'queued', 'claim_check', '{}', 'n', 'n')"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(statement)
    conn.close()
    conn = db.connect(path)
    assert db.migrate(conn)[0] == 9  # later migrations (0010, D105) follow it
    assert [tuple(r) for r in conn.execute("SELECT id, intent, kind FROM researches")] == [("res_1", "compare", "research")]
    assert [tuple(r) for r in conn.execute("SELECT id, kind, status FROM runs")] == [("run_1", "snowball", "completed")]
    conn.execute("UPDATE researches SET intent = 'statement' WHERE id = 'res_1'")
    conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
                 " VALUES ('run_2', 'res_1', 1, 'statement_check', 'queued', 'claim_check', '{}', 'n', 'n')")
    assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")} >= set(TRIGGERS)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.execute("DELETE FROM runs WHERE id = 'run_2'")
    conn.execute("UPDATE researches SET intent = 'compare' WHERE id = 'res_1'")
    fresh = db.connect(tmp_path / "fresh.sqlite")
    db.migrate(fresh)
    assert schema(conn) == schema(fresh)


def test_items_keep_eligibility_status_and_result_apart_and_go_with_their_research(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at, intent) VALUES ('r', 't', 'n', 'n', 'statement')")
    check = ("INSERT INTO statement_checks (id, research_id, revision, request_id, sentence, sentence_sha256, scope_revision,"
             " discovery_run_id, cutoff_step_id, attachment_snapshot_json, user_signature, effort, work_cap, model_json,"
             " skill_package_hash, created_at) VALUES ('c', 'r', 1, ?, 'S.', 'h', 1, NULL, NULL, ?, 'u', 'quick', 12, '{}',"
             " 'p', 'n')")
    with pytest.raises(sqlite3.IntegrityError):  # frozen from a cutoff or from the attached files, never neither
        conn.execute(check, ("req", None))
    conn.execute(check, ("req", "{}"))
    item = ("INSERT INTO statement_check_items (id, check_id, ordinal, work_id, entry, eligibility, excluded_reason,"
            " status, result, plan_json) VALUES (?, 'c', ?, ?, 'reading', ?, ?, ?, ?, ?)")
    for row in (("listed", None, None, None, None),  # a listed work has a status
                ("out_of_cap", None, "planned", None, "{}"),  # and only a listed one
                ("excluded_reason", None, None, None, None),  # a reason-excluded work keeps its reason
                ("listed", None, "done", None, "{}"),  # `done` has a result
                ("listed", None, "could_not_check", "found_whole", "{}"),  # and only `done`
                ("listed", None, "done", "supports", "{}"),
                ("listed", None, "planned", None, None)):  # a planned work has a frozen plan
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(item, ("i", 1, "w", *row))
    conn.execute(item, ("i1", 1, "w1", "listed", None, "done", "found_partial", "{}"))
    conn.execute(item, ("i2", 2, "w2", "listed", None, "no_text", None, None))
    conn.execute(item, ("i3", 3, "w3", "excluded_reason", "outside_read_window", None, None, None))
    conn.execute(item, ("i4", 4, "w4", "person_excluded", None, None, None, None))
    with pytest.raises(sqlite3.IntegrityError):  # one item per work and revision
        conn.execute(item, ("i5", 5, "w1", "person_excluded", None, None, None, None))
    conn.execute("DELETE FROM researches WHERE id = 'r'")
    for table in ("statement_checks", "statement_check_items"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
