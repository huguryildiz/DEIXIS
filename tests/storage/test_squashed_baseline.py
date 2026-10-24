"""The 2026-10-16 squash (D75): 0001_schema.sql gives the schema the 22 files before it gave, and a library that ran
those files is folded into it once, then upgraded like any library at version 1. The old files are kept in
tests/fixtures/storage/pre_squash_migrations and 0001_schema.sql in tests/fixtures/storage/migrations only for tests
(D119); libraries here are SYNTHETIC."""

import sqlite3

import pytest

from deixis.storage import db
from old_library import OLD_MIGRATIONS, PRE_SQUASH as OLD, apply_files, old_library


def library(path, paths):
    conn = db.connect(path)
    apply_files(conn, paths)
    return conn


def schema(conn):
    return sorted(tuple(row) for row in conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master"))


def versions(conn):
    return [tuple(row) for row in conn.execute("SELECT version, name FROM schema_migrations ORDER BY version")]


def later_versions():
    return sorted(v for v in db.packaged_versions() if v > 1)


def test_the_old_files_are_the_ones_the_fold_names():
    assert {path.name for path in OLD.glob("*.sql")} == set(db.SQUASHED.values())
    assert sorted(path.name for path in OLD_MIGRATIONS.glob("*.sql"))[0] == db.SQUASHED_INTO == db.BASELINE_NAME
    assert not set(db.SQUASHED.values()) & {path.name for path in OLD_MIGRATIONS.glob("*.sql")}


def test_the_squashed_file_gives_the_schema_the_old_files_gave(tmp_path):
    old = library(tmp_path / "old.sqlite", OLD.glob("*.sql"))
    new = old_library(tmp_path / "new.sqlite", 1)
    assert schema(old) == schema(new)
    assert [v for v, _ in versions(old)] == list(db.SQUASHED) and versions(new) == [(1, db.SQUASHED_INTO)]


def test_a_library_that_ran_the_old_files_is_folded_once_and_keeps_its_rows(tmp_path):
    path = tmp_path / "library.sqlite"
    conn = library(path, OLD.glob("*.sql"))
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('r_1', 'SYNTHETIC', 'now', 'now')")
    conn.close()
    fresh = db.connect(tmp_path / "fresh.sqlite")
    db.migrate(fresh)

    db.check_schema_known(path)
    conn = db.connect(path)
    # Folded into 0001, then the upgrade steps after it apply as to any library made by 0001.
    assert db.migrate(conn) == later_versions()
    assert versions(conn)[0] == (1, db.SQUASHED_INTO) and [v for v, _ in versions(conn)] == [1, *later_versions()]
    assert schema(conn) == schema(fresh)
    assert [tuple(row) for row in conn.execute("SELECT id, title FROM researches")] == [("r_1", "SYNTHETIC")]
    assert db.migrate(conn) == [] and [v for v, _ in versions(conn)] == [1, *later_versions()]


@pytest.mark.parametrize("ran", [1, 21])
def test_a_library_that_stopped_part_way_through_the_old_files_is_refused_unchanged(tmp_path, ran):
    path = tmp_path / "library.sqlite"
    library(path, sorted(OLD.glob("*.sql"))[:ran]).close()
    before = path.read_bytes()

    with pytest.raises(db.UnknownSchemaError, match="before 16 October 2026") as caught:
        db.connect(path)
    assert db.SQUASHED[ran + 1] in str(caught.value)
    assert path.read_bytes() == before
    with sqlite3.connect(path) as conn:
        assert len(versions(conn)) == ran
