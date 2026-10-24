"""A schema migration that fails at start-up (E24): its own code and sentence, and a library left as it was before the file.

The schema and upgrade steps are stand-ins injected through `db.SCHEMA` and `upgrades.STEPS`, never the real ones, and the
full disk is a connection stand-in that raises ENOSPC. They show the application's handling of those failures, not
what a real full disk does to a real SQLite file (the SQLITE_FULL case is in test_storage_launcher_regressions).
"""

import errno
import sqlite3

import pytest
from fastapi.testclient import TestClient

from deixis import __main__ as launcher
from deixis.api.app import create_app
from deixis.config import Settings
from deixis.storage import db, upgrades
from deixis.storage.upgrades import Step
from fakes import FakeAdapter
from old_library import stand_in_schema
from test_restore_matrix import fake_uvicorn, free_port, settings_for  # noqa: F401  (fake_uvicorn is a fixture)

FIRST = "CREATE TABLE first_table (value TEXT);\n"
HALF_APPLIED = "CREATE TABLE half_table (value TEXT);\nINSERT INTO no_such_table VALUES (1);\n"
TWO_TABLES = "CREATE TABLE half_table (value TEXT);\nCREATE TABLE after_table (value TEXT);\n"


def library_with_first_migration(tmp_path, monkeypatch):
    stand_in_schema(monkeypatch, tmp_path / "schema", FIRST)
    path = tmp_path / "data" / "library.sqlite"
    conn = db.connect(path)
    assert db.migrate(conn) == [1]
    conn.execute("INSERT INTO first_table VALUES ('SYNTHETIC row')")
    conn.close()
    return upgrades.STEPS, path


def snapshot(path):
    """Everything the library holds, as SQL text and rows, read through a fresh connection."""
    conn = sqlite3.connect(path)
    try:
        return (conn.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall(),
                conn.execute("SELECT version, name FROM schema_migrations").fetchall(),
                conn.execute("SELECT * FROM first_table").fetchall())
    finally:
        conn.close()


class FullDisk:
    """A connection that works until a statement mentions `trigger`, then reports a full disk the way the OS does."""

    def __init__(self, conn, trigger):
        self.conn, self.trigger = conn, trigger

    def execute(self, sql, *args):
        if self.trigger in sql:
            raise OSError(errno.ENOSPC, "SYNTHETIC no space left on device")
        return self.conn.execute(sql, *args)

    @property
    def in_transaction(self):
        return self.conn.in_transaction


def test_a_half_applied_migration_is_undone_and_reported_with_its_code(tmp_path, monkeypatch):
    steps, path = library_with_first_migration(tmp_path, monkeypatch)
    before = snapshot(path)
    steps[2] = Step("0002_half.sql", False, HALF_APPLIED)
    conn = db.connect(path)
    with pytest.raises(db.MigrationFailed) as caught:
        db.migrate(conn)
    conn.close()
    assert caught.value.code == "migration_failed" and caught.value.name == "0002_half.sql" and not caught.value.disk_full
    text = str(caught.value)
    assert "0002_half.sql" in text and "no such table" in text and "deixis restore" in text and "backup" in text
    assert "\n" not in text and "Traceback" not in text
    assert snapshot(path) == before  # half_table, created before the failing statement, is gone with the transaction


def test_a_failed_migration_with_foreign_keys_off_turns_them_back_on(tmp_path, monkeypatch):
    steps, path = library_with_first_migration(tmp_path, monkeypatch)
    before = snapshot(path)
    steps[2] = Step("0002_rebuild.sql", True, HALF_APPLIED)
    conn = db.connect(path)
    with pytest.raises(db.MigrationFailed):
        db.migrate(conn)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.close()
    assert snapshot(path) == before


def test_a_full_disk_during_a_migration_is_undone_and_says_to_free_space(tmp_path, monkeypatch):
    steps, path = library_with_first_migration(tmp_path, monkeypatch)
    before = snapshot(path)
    steps[2] = Step("0002_full.sql", False, TWO_TABLES)
    conn = db.connect(path)
    with pytest.raises(db.MigrationFailed) as caught:
        db.migrate(FullDisk(conn, "after_table"))
    conn.close()
    assert caught.value.code == "migration_failed" and caught.value.disk_full
    assert isinstance(caught.value.__cause__, OSError) and caught.value.__cause__.errno == errno.ENOSPC
    text = str(caught.value)
    assert "0002_full.sql" in text and "database or disk is full" in text
    assert "Free some disk space" in text and "Traceback" not in text
    assert snapshot(path) == before


def test_the_next_start_applies_the_migration_once_it_works(tmp_path, monkeypatch):
    steps, path = library_with_first_migration(tmp_path, monkeypatch)
    steps[2] = Step("0002_full.sql", False, TWO_TABLES)
    conn = db.connect(path)
    with pytest.raises(db.MigrationFailed):
        db.migrate(FullDisk(conn, "after_table"))
    assert db.migrate(conn) == [2]  # space came back: nothing was left half done
    conn.close()
    assert [row[0] for row in snapshot(path)[1]] == [1, 2]


def test_open_problem_names_a_failing_migration_with_its_code(tmp_path, monkeypatch):
    steps, path = library_with_first_migration(tmp_path, monkeypatch)
    steps[2] = Step("0002_half.sql", False, HALF_APPLIED)
    before = snapshot(path)
    problem = db.open_problem(path)
    assert problem is not None and problem.code == "migration_failed"
    assert str(path) in problem and "0002_half.sql" in problem and "did not start" in problem and "stays applied" in problem
    assert "deixis restore" in problem and "Traceback" not in problem
    assert snapshot(path) == before
    # Other problems keep their plain sentence and no code.
    del steps[2]
    assert db.open_problem(path) is None


def test_serve_exits_4_with_the_backup_sentence_when_a_migration_fails(tmp_path, monkeypatch, capsys, fake_uvicorn):
    steps, path = library_with_first_migration(tmp_path, monkeypatch)
    steps[2] = Step("0002_half.sql", False, HALF_APPLIED)
    before = snapshot(path)
    monkeypatch.setattr(launcher, "create_app", lambda *a, **k: pytest.fail("the app was created"))
    assert launcher.serve(settings_for(path.parent, free_port()), False, ()) == launcher.EXIT_MIGRATION_FAILED == 4
    err = capsys.readouterr().err
    assert "0002_half.sql" in err and "deixis restore" in err and "Traceback" not in err
    assert fake_uvicorn.instances == []
    assert snapshot(path) == before


def test_serve_keeps_exit_2_for_a_full_disk_that_is_not_a_migration(tmp_path, monkeypatch, capsys, fake_uvicorn):
    steps, path = library_with_first_migration(tmp_path, monkeypatch)
    monkeypatch.setattr(db, "open_problem", lambda p: "The library file could not be opened (SYNTHETIC), so DEIXIS did not start.")
    assert launcher.serve(settings_for(path.parent, free_port()), False, ()) == 2


def test_the_api_start_up_raises_the_migration_error_and_closes_the_library(tmp_path, monkeypatch):
    stand_in_schema(monkeypatch, tmp_path / "schema", HALF_APPLIED)
    opened = []
    real_connect = db.connect
    monkeypatch.setattr(db, "connect", lambda p: opened.append(real_connect(p)) or opened[-1])
    app = create_app(Settings(data_dir=tmp_path / "data", port=free_port()), adapters={"fake": FakeAdapter()},
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with pytest.raises(db.MigrationFailed) as caught:
        with TestClient(app):
            pass
    assert caught.value.code == "migration_failed" and "schema.sql" in str(caught.value)
    with pytest.raises(sqlite3.ProgrammingError):  # closed, so nothing holds the file
        opened[0].execute("SELECT 1")
