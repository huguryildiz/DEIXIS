"""Libraries as DEIXIS made them before D119, and stand-in schemas, for the schema and upgrade tests.

Before D119 the schema was a chain of SQL files run in order; those files are kept in tests/fixtures/storage/migrations
(0001 to 0016) and pre_squash_migrations (the 22 files before D75) only so a test can build a library at any older
version the way that DEIXIS did, and then open it with today's `db.migrate`. Libraries built here are SYNTHETIC.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from deixis.storage import db, upgrades

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "storage"
OLD_MIGRATIONS = FIXTURES / "migrations"
PRE_SQUASH = FIXTURES / "pre_squash_migrations"
FOREIGN_KEYS_OFF = "-- deixis:foreign-keys-off"


def version_of(path: Path) -> int:
    return int(path.name.split("_", 1)[0])


def apply_files(conn: sqlite3.Connection, paths) -> list[int]:
    """The migrate loop DEIXIS ran before D119: each file not yet recorded, in version order, in its own transaction,
    with foreign keys off for a file that starts with the marker, recorded in `schema_migrations` under its file name."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    done = []
    for path in sorted(paths, key=version_of):
        version = version_of(path)
        if version in applied:
            continue
        script = path.read_text(encoding="utf-8")
        keys_off = script.startswith(FOREIGN_KEYS_OFF)
        if keys_off:
            conn.execute("PRAGMA foreign_keys = OFF")
        try:
            with db.transaction(conn):
                for statement in db._split_sql(script):
                    conn.execute(statement)
                assert not (keys_off and conn.execute("PRAGMA foreign_key_check").fetchall()), path.name
                conn.execute("INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                             (version, path.name, db.now()))
        finally:
            if keys_off:
                conn.execute("PRAGMA foreign_keys = ON")
        done.append(version)
    return done


def old_files(through: int, folder: Path = OLD_MIGRATIONS) -> list[Path]:
    return [path for path in sorted(folder.glob("*.sql")) if version_of(path) <= through]


def old_library(path: Path, through: int, folder: Path = OLD_MIGRATIONS) -> sqlite3.Connection:
    """A library at version `through`, made by the old files up to it (from `folder`), open on a `db.connect` connection."""
    conn = db.connect(path)
    assert apply_files(conn, old_files(through, folder)) == [version_of(p) for p in old_files(through, folder)]
    return conn


def steps_through(version: int) -> dict[int, upgrades.Step]:
    """Today's upgrade steps up to `version`: set as `upgrades.STEPS` to stop an upgrade there."""
    return {v: step for v, step in upgrades.STEPS.items() if v <= version}


def stand_in_schema(monkeypatch, folder: Path, sql: str, version: int = 1, steps: dict | None = None) -> Path:
    """A schema.sql of `sql` at `version` in `folder`, and `steps` as the upgrade steps, in place of the real ones."""
    folder.mkdir(parents=True, exist_ok=True)
    schema = folder / "schema.sql"
    schema.write_text(f"{db.SCHEMA_VERSION_LINE}{version}\n{sql}", encoding="utf-8")
    monkeypatch.setattr(db, "SCHEMA", schema)
    monkeypatch.setattr(upgrades, "STEPS", dict(steps or {}))
    return schema


def master(conn: sqlite3.Connection) -> list[tuple]:
    """The schema as SQLite stores it, in creation order (`rowid`), without root pages."""
    return [tuple(row) for row in conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY rowid")]
