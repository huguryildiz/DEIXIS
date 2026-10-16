"""The 2026-10-16 squash (D75): 0001_schema.sql gives the schema the 22 files before it gave, and a library that ran
those files is folded into it once. The old files are kept in tests/fixtures/storage/pre_squash_migrations only for
these tests; libraries here are SYNTHETIC."""

import shutil
import sqlite3
from pathlib import Path

import pytest

from deixis.storage import db

OLD = Path(__file__).resolve().parents[1] / "fixtures" / "storage" / "pre_squash_migrations"


def library(path, folder, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(db, "MIGRATIONS_DIR", folder)
        conn = db.connect(path)
        db.migrate(conn)
    return conn


def schema(conn):
    return sorted(tuple(row) for row in conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master"))


def versions(conn):
    return [tuple(row) for row in conn.execute("SELECT version, name FROM schema_migrations ORDER BY version")]


def test_the_old_files_are_the_ones_the_fold_names():
    assert {path.name for path in OLD.glob("*.sql")} == set(db.SQUASHED.values())
    assert [path.name for path in db.MIGRATIONS_DIR.glob("*.sql")] == [db.SQUASHED_INTO]


def test_the_squashed_file_gives_the_schema_the_old_files_gave(tmp_path, monkeypatch):
    old = library(tmp_path / "old.sqlite", OLD, monkeypatch)
    new = db.connect(tmp_path / "new.sqlite")
    db.migrate(new)
    assert schema(old) == schema(new)
    assert [v for v, _ in versions(old)] == list(db.SQUASHED) and versions(new) == [(1, db.SQUASHED_INTO)]


def test_a_library_that_ran_the_old_files_is_folded_once_and_keeps_its_rows(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite"
    conn = library(path, OLD, monkeypatch)
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('r_1', 'SYNTHETIC', 'now', 'now')")
    conn.close()
    fresh = db.connect(tmp_path / "fresh.sqlite")
    db.migrate(fresh)

    db.check_schema_known(path)
    conn = db.connect(path)
    assert db.migrate(conn) == []
    assert versions(conn) == [(1, db.SQUASHED_INTO)]
    assert schema(conn) == schema(fresh)
    assert [tuple(row) for row in conn.execute("SELECT id, title FROM researches")] == [("r_1", "SYNTHETIC")]
    assert db.migrate(conn) == [] and versions(conn) == [(1, db.SQUASHED_INTO)]


@pytest.mark.parametrize("ran", [1, 21])
def test_a_library_that_stopped_part_way_through_the_old_files_is_refused_unchanged(tmp_path, monkeypatch, ran):
    folder = tmp_path / "old"
    folder.mkdir()
    for path in sorted(OLD.glob("*.sql"))[:ran]:
        shutil.copy(path, folder / path.name)
    path = tmp_path / "library.sqlite"
    library(path, folder, monkeypatch).close()
    before = path.read_bytes()

    with pytest.raises(db.UnknownSchemaError, match="before 16 October 2026") as caught:
        db.connect(path)
    assert db.SQUASHED[ran + 1] in str(caught.value)
    assert path.read_bytes() == before
    with sqlite3.connect(path) as conn:
        assert len(versions(conn)) == ran
