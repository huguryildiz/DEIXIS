"""SQLite connection, migrations and small helpers."""

from __future__ import annotations

import errno
import json
import secrets
import shutil
import sqlite3
import string
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
FOREIGN_KEYS_OFF = "-- deixis:foreign-keys-off"
_ALPHABET = string.digits + string.ascii_letters


def new_id(prefix: str) -> str:
    return f"{prefix}_{''.join(secrets.choice(_ALPHABET) for _ in range(20))}"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class UnknownSchemaError(RuntimeError):
    """The library records migrations this version of DEIXIS does not have: a newer version wrote it."""


class SchemaCheckUnreadable(RuntimeError):
    """The library could not be read well enough to compare its migrations with the packaged ones."""


def packaged_versions() -> set[int]:
    return {int(path.name.split("_", 1)[0]) for path in MIGRATIONS_DIR.glob("*.sql")}


def _applied_versions(conn: sqlite3.Connection) -> set[int] | None:
    try:
        return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return None
        raise


def _non_empty(path: Path) -> bool:
    try:
        return path.stat().st_size > 0
    except FileNotFoundError:
        return False


def _copy_live_files(path: Path, folder: Path) -> Path:
    """Plain reads of the library and its write-ahead log into `folder`; nothing is written next to the originals."""
    copy = folder / path.name
    shutil.copyfile(path, copy)
    wal = Path(f"{path}-wal")
    try:
        shutil.copyfile(wal, folder / wal.name)
    except FileNotFoundError:  # a checkpoint removed it; the main file is then compared below
        pass
    return copy


def _applied_versions_from_copy(path: Path) -> set[int] | None:
    """Versions committed in the library including its `-wal`, read from a copy, never from the live files.

    A read-only open of a live WAL library changes `-shm`, and `immutable=1` does not see rows that exist only in the
    `-wal`. A checkpoint between the two reads can tear the copy: the main file changing while it is copied, or a copy
    SQLite cannot read, is tried again."""
    for _ in range(3):
        with tempfile.TemporaryDirectory(prefix="deixis-schema-check-") as folder:
            before = path.stat()
            try:
                copy = _copy_live_files(path, Path(folder))
            except OSError as exc:
                raise SchemaCheckUnreadable(
                    f"DEIXIS could not copy the library to check which version wrote it ({exc}); "
                    "free some disk space or fix the permissions and try again.") from exc
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                continue
            try:
                conn = sqlite3.connect(copy, timeout=5)
                try:
                    return _applied_versions(conn)
                finally:
                    conn.close()
            except sqlite3.DatabaseError:
                continue
    raise SchemaCheckUnreadable(
        "DEIXIS could not read the library to check which version wrote it; try again with DEIXIS stopped.")


def check_schema_known(path: Path) -> None:
    """Refuse a library written by a newer DEIXIS, before anything is opened for writing.

    Every recorded migration id missing from the packaged set counts (not only a higher one). A library with no
    `-wal` is read with the `immutable` URI, which creates nothing; one with a `-wal` is read from a copy."""
    path = Path(path)
    if not _non_empty(path):
        return
    if _non_empty(Path(f"{path}-wal")):
        applied = _applied_versions_from_copy(path)
    else:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True, timeout=5)
        try:
            applied = _applied_versions(conn)
        finally:
            conn.close()
    if applied is None:
        return
    unknown = sorted(applied - packaged_versions())
    if unknown:
        shown = ", ".join(f"{v:04d}" for v in unknown[:5]) + (f" and {len(unknown) - 5} more" if len(unknown) > 5 else "")
        raise UnknownSchemaError(
            f"This library was written by a newer DEIXIS: it records {len(unknown)} schema migration"
            f"{'s' if len(unknown) != 1 else ''} this version does not have ({shown}); update DEIXIS or open it with the "
            "version that made it. Nothing was changed.")


def connect(path: Path) -> sqlite3.Connection:
    check_schema_known(path)  # before anything is created or written (journal_mode = WAL below writes)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    if conn.in_transaction:
        # Nested use joins the outer transaction, which commits or rolls back everything together.
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        # After a statement-level SQLITE_FULL SQLite has already rolled back; an unconditional ROLLBACK would raise
        # "no transaction is active" and hide the real error.
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


# SQLite primary result codes (the low byte of `sqlite_errorcode`) that DEIXIS names for the person.
_FAILURES = {
    13: ("disk_full", 507, "DEIXIS could not save because the disk is full. Free some space and try again."),
    5: ("database_busy", 503, "DEIXIS could not save because another process is using the library. Try again in a moment."),
    6: ("database_busy", 503, "DEIXIS could not save because another process is using the library. Try again in a moment."),
    8: ("database_readonly", 503,
        "DEIXIS could not save because the library file is read-only. Make it writable, or restore a copy, and try again."),
    11: ("database_damaged", 503, "DEIXIS cannot read its library because the file is damaged. Restore it from a backup."),
    26: ("database_damaged", 503, "DEIXIS cannot read its library because the file is damaged. Restore it from a backup."),
}


def describe_failure(exc: BaseException) -> tuple[str, int, str] | None:
    """(code, HTTP status, sentence) for a full disk, a busy, read-only or damaged library; None for anything else."""
    if isinstance(exc, OSError) and exc.errno in (errno.ENOSPC, errno.EDQUOT):
        return _FAILURES[13]
    if isinstance(exc, sqlite3.DatabaseError):
        code = getattr(exc, "sqlite_errorcode", None)
        if isinstance(code, int):
            return _FAILURES.get(code & 0xFF)
    return None


# What the launcher says before it starts when the library cannot be opened: what to do next, per code.
_STARTUP_ADVICE = {
    "disk_full": "free some space and start it again",
    "database_busy": "close the other DEIXIS or tool using it and start it again",
    "database_readonly": "make the file writable, or restore a copy, and start it again",
    "database_damaged": "restore it from a backup or move it aside",
}


def open_problem(path: Path) -> str | None:
    """Open the library as the app will (connect, migrate, close). One sentence if that fails in a way
    `describe_failure` names, None if it opens. A missing file is a first run, not a problem. Any other exception
    (a failing migration, an unwritable folder) is not caught."""
    conn = None
    try:
        conn = connect(path)
        migrate(conn)
    except (sqlite3.DatabaseError, OSError) as exc:
        failure = describe_failure(exc)
        if failure is None:
            raise
        reason = str(exc) if isinstance(exc, sqlite3.Error) else "database or disk is full"
        return (f"The library file {path} could not be opened ({reason}), so DEIXIS did not start and changed nothing; "
                f"{_STARTUP_ADVICE[failure[0]]}.")
    finally:
        if conn is not None:
            conn.close()
    return None


def migrate(conn: sqlite3.Connection) -> list[int]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    done = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = int(path.name.split("_", 1)[0])
        if version in applied:
            continue
        script = path.read_text(encoding="utf-8")
        # Rebuilding a table that other tables reference needs foreign keys off (SQLite's documented 12-step procedure).
        # The pragma cannot change inside a transaction, and the check runs before the commit.
        keys_off = script.startswith(FOREIGN_KEYS_OFF)
        if keys_off:
            conn.execute("PRAGMA foreign_keys = OFF")
        try:
            with transaction(conn):
                for statement in _split_sql(script):
                    conn.execute(statement)
                if keys_off and conn.execute("PRAGMA foreign_key_check").fetchall():
                    raise RuntimeError(f"foreign key check failed in {path.name}")
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (version, path.name, now()),
                )
        finally:
            if keys_off:
                conn.execute("PRAGMA foreign_keys = ON")
        done.append(version)
    if conn.execute("PRAGMA foreign_key_check").fetchall():
        raise RuntimeError("foreign key check failed after migration")
    return done


def _split_sql(script: str) -> list[str]:
    """Split on statement boundaries understood by sqlite3.complete_statement (handles triggers)."""
    statements, buffer = [], ""
    for line in script.splitlines(keepends=True):
        if not buffer and line.strip().startswith("--"):
            continue
        buffer += line
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        statements.append(buffer.strip())
    return statements


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None
