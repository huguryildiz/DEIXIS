"""P9 H4: compare two DEIXIS data directories (or a backup folder) table by table and file by file.

Not a test module. Every table in `sqlite_master` is enumerated (never a fixed list), so a table that a later
migration adds is compared without anyone remembering to add it. A table is its row count plus a canonical sha256
over all columns of all rows (each row as JSON with sorted keys, blobs as hex, rows sorted by that text).

A database without a `-wal` is opened with the `immutable` URI: a plain `mode=ro` open of a WAL-mode file creates
`-wal` and `-shm` next to it. A database that has a non-empty `-wal` (an app still has it open) is read through the
backup API into memory, which sees the committed rows of the `-wal` too.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

FILE_FOLDERS = ("papers", "provider-payloads")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def open_readonly(db_path: Path) -> sqlite3.Connection:
    wal = Path(f"{db_path}-wal")
    if wal.exists() and wal.stat().st_size > 0:
        memory = sqlite3.connect(":memory:")
        source = sqlite3.connect(db_path, timeout=30)
        try:
            source.backup(memory)
        finally:
            source.close()
        return memory
    return sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True, timeout=30)


def _cell(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"blob": bytes(value).hex()}
    return value


def _row_text(row: tuple) -> str:
    return json.dumps([_cell(v) for v in row], sort_keys=True, ensure_ascii=False)


def table_names(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def table_state(conn: sqlite3.Connection, name: str) -> tuple[int, str]:
    rows = sorted(_row_text(tuple(row)) for row in conn.execute(f'SELECT * FROM "{name}"'))  # noqa: S608 - names from sqlite_master
    digest = hashlib.sha256("\n".join(rows).encode()).hexdigest()
    return len(rows), digest


def tables_state(db_path: Path) -> dict[str, tuple[int, str]]:
    conn = open_readonly(db_path)
    try:
        return {name: table_state(conn, name) for name in table_names(conn)}
    finally:
        conn.close()


def files_state(folder: Path) -> tuple[dict[str, str], list[str]]:
    """({relative path: sha256} for every file under papers/ and provider-payloads/, names of `.restoring-*`/`.part` files)."""
    found: dict[str, str] = {}
    stray: list[str] = []
    for sub in FILE_FOLDERS:
        base = folder / sub
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(folder).as_posix()
            if path.name.startswith(".restoring-") or path.name.endswith(".part"):
                stray.append(rel)
            else:
                found[rel] = sha256_file(path)
    return found, stray


def library_state(folder: Path) -> dict[str, Any]:
    """The state of a data directory or of a backup folder (both hold `library.sqlite`, `papers/`, `provider-payloads/`)."""
    files, stray = files_state(folder)
    return {"tables": tables_state(folder / "library.sqlite"), "files": files, "stray": stray}


def compare_states(a: dict[str, Any], b: dict[str, Any], allow: tuple[str, ...] = ()) -> list[str]:
    """Differences between two `library_state` results; `allow` names tables whose differences are expected."""
    diffs: list[str] = []
    for name in sorted(set(a["tables"]) | set(b["tables"])):
        if name in allow:
            continue
        left, right = a["tables"].get(name), b["tables"].get(name)
        if left is None or right is None:
            diffs.append(f"table {name}: present on one side only")
        elif left[0] != right[0]:
            diffs.append(f"table {name}: {left[0]} rows vs {right[0]} rows")
        elif left[1] != right[1]:
            diffs.append(f"table {name}: same {left[0]} rows, different content")
    for path in sorted(set(a["files"]) | set(b["files"])):
        left, right = a["files"].get(path), b["files"].get(path)
        if left is None or right is None:
            diffs.append(f"file {path}: present on one side only")
        elif left != right:
            diffs.append(f"file {path}: different content")
    if a["stray"] or b["stray"]:
        diffs.append(f"leftover temporary files: {a['stray']} vs {b['stray']}")
    return diffs


def tree_snapshot(root: Path) -> dict[str, tuple[int, str]]:
    """Every file under `root` (hidden ones too) as {relative path: (size, sha256)}, plus directories as (-1, '')."""
    snap: dict[str, tuple[int, str]] = {}
    if not root.exists():
        return snap
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        snap[rel] = (path.stat().st_size, sha256_file(path)) if path.is_file() else (-1, "")
    return snap
