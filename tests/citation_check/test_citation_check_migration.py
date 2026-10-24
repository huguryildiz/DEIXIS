"""Upgrade step 2 (0002_citation_check.sql, D86) on a library made by 0001 alone, and a fresh library. Libraries here are
SYNTHETIC."""

import sqlite3

import pytest

from deixis.storage import db, upgrades
from old_library import old_library, steps_through

TRIGGERS = ("kill_searches_run_guard", "owner_reviews_run_guard", "watch_checks_run_guard")


def schema(conn):
    return sorted(tuple(row) for row in conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master"))


def test_a_library_made_by_0001_alone_takes_0002_and_keeps_its_rows(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite"
    conn = old_library(path, 1)
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_1', 'SYNTHETIC', 'now', 'now')")
    conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
                 " VALUES ('run_1', 'res_1', 1, 'citation_map', 'completed', 'intake', '{}', 'now', 'now')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
                     " VALUES ('run_2', 'res_1', 1, 'citation_check', 'queued', 'intake', '{}', 'now', 'now')")
    conn.close()

    # Step 2 alone, as a later step (3) would rebuild `runs` again and is tested on its own.
    monkeypatch.setattr(upgrades, "STEPS", steps_through(2))
    conn = db.connect(path)
    assert db.migrate(conn) == [2]
    assert conn.execute("SELECT kind FROM researches WHERE id = 'res_1'").fetchone()[0] == "research"
    assert [tuple(r) for r in conn.execute("SELECT id, kind, status FROM runs")] == [("run_1", "citation_map", "completed")]
    conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
                 " VALUES ('run_2', 'res_1', 1, 'citation_check', 'queued', 'intake', '{}', 'now', 'now')")
    assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")} >= set(TRIGGERS)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.execute("DELETE FROM runs WHERE id = 'run_2'")
    assert schema(conn) == schema(old_library(tmp_path / "fresh.sqlite", 2))


def test_a_fresh_library_checks_kinds_results_and_cascades(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO researches (id, title, created_at, updated_at, kind) VALUES ('r', 't', 'n', 'n', 'other')")
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at, kind) VALUES ('r', 't', 'n', 'n', 'citation_check')")
    conn.execute("INSERT INTO citation_drafts (id, research_id, format, text_sha256, text, bibliography_origin, created_at)"
                 " VALUES ('d', 'r', 'md', 'h', 'A [1].', 'none', 'n')")
    conn.execute("INSERT INTO citation_markers (id, draft_id, ordinal, sentence, sentence_start, sentence_end, char_start,"
                 " char_end, raw, style, parse_status) VALUES ('m', 'd', 1, 'A [1].', 0, 6, 2, 5, '[1]', 'numeric', 'recognized')")
    with pytest.raises(sqlite3.IntegrityError):  # a pair with no entry is only unresolved or ambiguous
        conn.execute("INSERT INTO citation_pairs (id, draft_id, marker_id, target, ordinal, status, created_at)"
                     " VALUES ('p', 'd', 'm', '1', 1, 'planned', 'n')")
    conn.execute("INSERT INTO citation_pairs (id, draft_id, marker_id, target, ordinal, status, created_at)"
                 " VALUES ('p', 'd', 'm', '1', 1, 'unresolved', 'n')")
    for status, result in (("done", None), ("could_not_check", "found_whole"), ("done", "supported")):
        with pytest.raises(sqlite3.IntegrityError):  # a result belongs to `done` only, and `done` has one
            conn.execute("INSERT INTO citation_checks (id, pair_id, status, result, created_at) VALUES ('c', 'p', ?, ?, 'n')",
                         (status, result))
    conn.execute("INSERT INTO citation_checks (id, pair_id, status, result, created_at) VALUES ('c', 'p', 'done', 'found_partial', 'n')")
    conn.execute("DELETE FROM researches WHERE id = 'r'")
    for table in ("citation_drafts", "citation_markers", "citation_pairs", "citation_checks"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
