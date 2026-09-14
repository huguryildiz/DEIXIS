"""Consistent local backups: an SQLite backup-API snapshot plus the files it references, listed with hashes.

The model connection's home (sign-in credentials), its scratch workspace and the worker lock are not included.
A backup folder is complete only when its manifest exists; restore verifies every listed hash first.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deixis.config import Settings
from deixis.storage.db import now

FORMAT = "deixis-backup-v1"
MANIFEST = "manifest.json"
DB_NAME = "library.sqlite"
FILE_DIRS = {"papers": "papers_dir", "provider-payloads": "payloads_dir"}
NOT_INCLUDED = ["codex-home (model sign-in)", "codex-workspace", "worker.lock"]


class BackupError(Exception):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _referenced_files(conn: sqlite3.Connection) -> dict[str, dict[str, str | None]]:
    """File name -> recorded sha256 (None when the record has no hash), per backup subfolder."""
    papers = {row[0]: row[1] for row in conn.execute("SELECT storage_path, sha256 FROM source_assets")}
    # Abstract passages point at their source version's payload file; PDF passages hold character ranges, not files.
    payloads = {row[0]: None for row in conn.execute(
        "SELECT raw_payload_path FROM search_runs WHERE raw_payload_path IS NOT NULL"
        " UNION SELECT provider_payload_path FROM source_versions WHERE provider_payload_path IS NOT NULL")}
    refs = {"papers": papers, "provider-payloads": payloads}
    for folder, names in refs.items():
        for name in names:
            if Path(name).name != name or name in ("", ".", ".."):
                raise BackupError(f"unexpected file reference in {folder}: {name!r}")
    return refs


def create_backup(settings: Settings, destination: Path) -> Path:
    if not settings.db_path.exists():
        raise BackupError(f"no library found at {settings.db_path}")
    target = destination / f"deixis-backup-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    target.mkdir(parents=True)
    try:
        source = sqlite3.connect(settings.db_path, timeout=30)
        snapshot = sqlite3.connect(target / DB_NAME)
        try:
            source.backup(snapshot)  # consistent even while the server keeps writing
            snapshot.execute("PRAGMA journal_mode = DELETE")  # a single self-contained file
            if snapshot.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError("snapshot failed the SQLite integrity check")
            refs = _referenced_files(snapshot)
            schema = [row[0] for row in snapshot.execute("SELECT version FROM schema_migrations ORDER BY version")]
        finally:
            snapshot.close()
            source.close()

        files = [{"path": DB_NAME, "sha256": _sha256(target / DB_NAME), "bytes": (target / DB_NAME).stat().st_size}]
        for folder, names in refs.items():
            src_dir = getattr(settings, FILE_DIRS[folder])
            for name, recorded in sorted(names.items()):
                src = src_dir / name
                if not src.is_file():
                    raise BackupError(f"referenced file is missing: {folder}/{name}")
                (target / folder).mkdir(exist_ok=True)
                shutil.copyfile(src, target / folder / name)
                digest = _sha256(target / folder / name)
                if recorded is not None and digest != recorded:
                    raise BackupError(f"file does not match its recorded hash: {folder}/{name}")
                files.append({"path": f"{folder}/{name}", "sha256": digest, "bytes": (target / folder / name).stat().st_size})

        manifest = {"format": FORMAT, "created_at": now(), "schema_versions": schema, "files": files, "not_included": NOT_INCLUDED}
        partial = target / f"{MANIFEST}.partial"
        partial.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        partial.replace(target / MANIFEST)
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target


def restore_backup(backup: Path, settings: Settings) -> dict[str, Any]:
    """Restore into a data directory that has no library yet. Existing model sign-in data is left in place."""
    try:
        manifest = json.loads((backup / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError(f"not a complete DEIXIS backup: {exc}") from exc
    if manifest.get("format") != FORMAT:
        raise BackupError(f"unsupported backup format {manifest.get('format')!r}")

    db_path = settings.db_path
    if any(Path(f"{db_path}{suffix}").exists() for suffix in ("", "-wal", "-shm")):
        raise BackupError(f"a library already exists at {db_path}; restore only into an empty data directory")

    entries = manifest["files"]
    for entry in entries:
        parts = Path(entry["path"]).parts
        valid = parts == (DB_NAME,) or (len(parts) == 2 and parts[0] in FILE_DIRS and parts[1] not in ("", ".", ".."))
        if not valid:
            raise BackupError(f"unexpected path in manifest: {entry['path']!r}")
        file = backup / entry["path"]
        if not file.is_file() or _sha256(file) != entry["sha256"]:
            raise BackupError(f"backup file is missing or changed: {entry['path']}")
    if DB_NAME not in {e["path"] for e in entries}:
        raise BackupError("backup has no library database")

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        if entry["path"] == DB_NAME:
            continue
        folder, name = Path(entry["path"]).parts
        dest = getattr(settings, FILE_DIRS[folder]) / name
        if dest.exists():
            if _sha256(dest) != entry["sha256"]:
                raise BackupError(f"a different file already exists at {dest}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(backup / entry["path"], dest)

    staging = db_path.with_name(f"{DB_NAME}.restoring")
    shutil.copyfile(backup / DB_NAME, staging)
    conn = sqlite3.connect(staging)
    try:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise BackupError("restored database failed the SQLite integrity check")
        researches = conn.execute("SELECT COUNT(*) FROM researches").fetchone()[0]
    finally:
        conn.close()
    os.replace(staging, db_path)
    return {"files": len(entries), "researches": researches, "schema_versions": manifest["schema_versions"]}
