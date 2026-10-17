"""0004_followup_search.sql (D92) on a library made by 0001 to 0003. Libraries here are SYNTHETIC."""

import shutil
import sqlite3

import pytest

from deixis.storage import db

TRIGGERS = ("kill_searches_run_guard", "owner_reviews_run_guard", "watch_checks_run_guard")
RUN = ("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
       " VALUES (?, 'res_1', 1, ?, 'queued', 'discovery', '{}', 'now', 'now')")


def schema(conn):
    return sorted(tuple(row) for row in conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master"))


def test_0004_adds_the_followup_search_kind_and_keeps_runs_triggers_and_index(tmp_path, monkeypatch):
    earlier = tmp_path / "migrations"
    earlier.mkdir()
    for name in ("0001_schema.sql", "0002_citation_check.sql", "0003_snowball.sql"):
        shutil.copy(db.MIGRATIONS_DIR / name, earlier)
    path = tmp_path / "library.sqlite"
    with monkeypatch.context() as patch:
        patch.setattr(db, "MIGRATIONS_DIR", earlier)
        conn = db.connect(path)
        assert db.migrate(conn) == [1, 2, 3]
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_1', 'SYNTHETIC', 'now', 'now')")
    conn.execute(RUN, ("run_1", "snowball"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(RUN, ("run_2", "followup_search"))
    conn.close()

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
    fresh = db.connect(tmp_path / "fresh.sqlite")
    assert db.migrate(fresh) == [1, 2, 3, 4]
    assert schema(conn) == schema(fresh)
