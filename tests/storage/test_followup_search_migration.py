"""Upgrade step 4 (0004_followup_search.sql, D92) on a library made by 0001 to 0003. Libraries here are SYNTHETIC."""

import sqlite3

import pytest

from deixis.storage import db, upgrades
from old_library import old_library, steps_through

TRIGGERS = ("kill_searches_run_guard", "owner_reviews_run_guard", "watch_checks_run_guard")
RUN = ("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
       " VALUES (?, 'res_1', 1, ?, 'queued', 'discovery', '{}', 'now', 'now')")


def schema(conn):
    return sorted(tuple(row) for row in conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master"))


def test_0004_adds_the_followup_search_kind_and_keeps_runs_triggers_and_index(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite"
    conn = old_library(path, 3)
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_1', 'SYNTHETIC', 'now', 'now')")
    conn.execute(RUN, ("run_1", "snowball"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(RUN, ("run_2", "followup_search"))
    conn.close()

    # Step 4 alone, as later steps (5 on) are their own tests.
    monkeypatch.setattr(upgrades, "STEPS", steps_through(4))
    conn = db.connect(path)
    assert db.migrate(conn) == [4]
    assert [tuple(r) for r in conn.execute("SELECT id, kind FROM runs")] == [("run_1", "snowball")]
    conn.execute(RUN, ("run_2", "followup_search"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(RUN, ("run_3", "no_such_kind"))
    assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")} >= set(TRIGGERS)
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'runs_status'").fetchone()
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.execute("DELETE FROM runs WHERE id = 'run_2'")
    assert schema(conn) == schema(old_library(tmp_path / "fresh.sqlite", 4))
