#!/usr/bin/env python3
"""P9 H4, row B02: today's code opens a restored copy of a library written by earlier code.

Three steps, each its own subcommand, none of which touches the live data directory beyond plain reads:

    upgrade_check.py copy-live LIVE_DIR WORK_DIR [--i-have-owner-consent]
    upgrade_check.py restore-copy WORK_DIR
    upgrade_check.py open-copy WORK_DIR
    upgrade_check.py --self-test

`copy-live` reads the live library and the files it references into WORK_DIR/live-copy. It never opens a live file with
SQLite in a way that can write: a read-only SQLite open of a WAL library changes `-shm` (or creates `-shm` and `-wal`),
so a library with a non-empty `-wal` (a running service) is copied byte by byte, and one without is read through the
`immutable` URI (which reads the main file only and creates nothing). The copy is checked and tried again when a checkpoint
tore it. `restore-copy` runs the product's own `create_backup` and `restore_backup` on the copy. `open-copy` opens the
restored folder with `create_app(start_worker=False)`, no model adapters and a transport that refuses every request, and
compares plain SQL counts before and after.

Path rules inspect names and file metadata before SQLite or backup writes. Output is counts and schema versions only:
no titles, no text, no ids. The owner's consent for a run on real data is the `--i-have-owner-consent` flag of `copy-live`;
nothing else accepts it as a relaxation. This script is never run on real data by the batch that wrote it.

Exit codes: 0 done, 1 a check failed, 2 refused, 3 not measured (the copy could not be made consistent).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import stat
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "backend")]

from deixis import config  # noqa: E402
from deixis.config import Settings  # noqa: E402
from deixis.storage import db  # noqa: E402
from deixis.storage.backup import BackupError, _referenced_files, create_backup, restore_backup  # noqa: E402

MARKER = ".p9-upgrade-copy"
COPY = "live-copy"
BACKUP = "backup"
RESTORED = "restored"
FILE_FOLDERS = ("papers", "provider-payloads")
ATTEMPTS = 3
CONSENT = "--i-have-owner-consent"
MODEL_KEYS = ("DEIXIS_CODEX_HOME", "GEMINI_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY")


class Refused(Exception):
    """A path rule forbids the call before SQLite or backup writes."""


class NotMeasured(Exception):
    """The copy could not be made consistent; no number is claimed."""


# ---- path rules ----------------------------------------------------------------------------------------------------


def _resolved(path: str | os.PathLike) -> Path:
    return Path(path).expanduser().resolve()


def inside(path: Path, parent: Path) -> bool:
    """`path` equals `parent` or is below it."""
    return path == parent or parent in path.parents


def protected_dirs() -> set[Path]:
    """The data directories that belong to the running product: the default one, the platform default with the environment
    variable ignored, and the folder DEIXIS_DATA_DIR names."""
    found = {_resolved(config.default_data_dir())}
    env = os.environ.pop("DEIXIS_DATA_DIR", None)
    try:
        found.add(_resolved(config.default_data_dir()))
    finally:
        if env is not None:
            os.environ["DEIXIS_DATA_DIR"] = env
    if env:
        found.add(_resolved(env))
    return found


def forbid_protected(path: Path, extra: tuple[Path, ...] = (), what: str = "it") -> None:
    for folder in protected_dirs() | set(extra):
        if inside(path, folder) or inside(folder, path):
            raise Refused(f"{what} is, contains or is inside a data directory the running product uses ({folder.name}); refused")


def check_copy_live_paths(live: str, work: str, consent: bool) -> tuple[Path, Path]:
    live_dir, work_dir = _resolved(live), _resolved(work)
    if not consent:
        for folder in protected_dirs():
            if live_dir == folder:
                raise Refused(f"LIVE_DIR is a data directory the running product uses; pass {CONSENT} only with the owner's consent")
    if inside(work_dir, live_dir) or inside(live_dir, work_dir):
        raise Refused("WORK_DIR equals, contains or is inside LIVE_DIR; never allowed")
    forbid_protected(work_dir, what="WORK_DIR")  # the copy is never written into the product's own data directory
    if work_dir.exists() and any(work_dir.iterdir()):
        raise Refused("WORK_DIR exists and is not empty")
    return live_dir, work_dir


def read_marker(work_dir: Path) -> Path:
    marker = work_dir / MARKER
    try:
        info = marker.lstat()
    except FileNotFoundError:
        info = None
    except OSError as exc:
        raise Refused(f"could not inspect {MARKER}; refused") from exc
    if info is not None and stat.S_ISLNK(info.st_mode):
        raise Refused(f"symlink at {MARKER}; refused")
    if info is not None and stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
        raise Refused(f"hard link at {MARKER}; refused")
    if info is None or not stat.S_ISREG(info.st_mode):
        raise Refused(f"{work_dir.name} is not a copy made by copy-live (no {MARKER})")
    return _resolved(marker.read_text(encoding="utf-8").strip())


def check_work_tree(work_dir: Path, live_dir: Path) -> None:
    """Refuse existing links and unreadable entries; this is not protection against a concurrent path swap."""
    work_dir, live_dir = work_dir.resolve(), live_dir.resolve()

    def walk(folder: Path, working: bool):
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    info = path.lstat()
                    if stat.S_ISLNK(info.st_mode):
                        if working:
                            raise Refused(f"symlink at {path.relative_to(work_dir).as_posix()}; refused")
                    elif stat.S_ISDIR(info.st_mode):
                        yield from walk(path, working)
                    elif stat.S_ISREG(info.st_mode):
                        yield path, info
        except OSError as exc:
            name = folder.relative_to(work_dir).as_posix() if working else "LIVE_DIR"
            raise Refused(f"could not scan {name}; refused") from exc

    live_files = {(info.st_dev, info.st_ino) for _, info in walk(live_dir, False)}
    for path, info in walk(work_dir, True):
        relative = path.relative_to(work_dir)
        if path.name.startswith("library.sqlite") or relative.parts[0] in (COPY, BACKUP, RESTORED):
            if (info.st_dev, info.st_ino) in live_files:
                raise Refused(f"live file identity at {relative.as_posix()}; refused")
        if info.st_nlink > 1:
            raise Refused(f"hard link at {relative.as_posix()}; refused")
    for name in (COPY, BACKUP, RESTORED):
        path = work_dir / name
        try:
            path.lstat()
        except FileNotFoundError:
            continue  # A not-yet-created output has no links to inspect.
        except OSError as exc:
            raise Refused(f"could not inspect {name}; refused") from exc
        resolved = path.resolve()
        if not inside(resolved, work_dir):
            raise Refused(f"{name} is outside WORK_DIR; refused")
        forbid_protected(resolved, (live_dir,), name)


# ---- reading ---------------------------------------------------------------------------------------------------------


def non_empty(path: Path) -> bool:
    try:
        return path.stat().st_size > 0
    except FileNotFoundError:
        return False


def immutable(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True, timeout=5)


def read_sql(db_path: Path, fn):
    """`fn(connection)` on a database of ours that no process holds open; a `-wal` is read through the backup API."""
    if non_empty(Path(f"{db_path}-wal")):
        memory = sqlite3.connect(":memory:")
        source = sqlite3.connect(db_path, timeout=30)
        try:
            source.backup(memory)
        finally:
            source.close()
        try:
            return fn(memory)
        finally:
            memory.close()
    conn = immutable(db_path)
    try:
        return fn(conn)
    finally:
        conn.close()


def sql_counts(db_path: Path) -> dict[str, int]:
    return read_sql(db_path, lambda c: {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: S608 - fixed names
                                        for t in ("researches", "source_versions", "passages")})


def applied_versions(db_path: Path) -> list[int]:
    return read_sql(db_path, lambda c: [r[0] for r in c.execute("SELECT version FROM schema_migrations ORDER BY version")])


def compact(versions: list[int]) -> str:
    """[1, 2, 3, 5] -> '1-3, 5'."""
    spans, start = [], None
    for index, v in enumerate(versions):
        if start is None:
            start = previous = v
        elif v == previous + 1:
            previous = v
        else:
            spans.append((start, previous))
            start = previous = v
        if index == len(versions) - 1:
            spans.append((start, previous))
    return ", ".join(f"{a}" if a == b else f"{a}-{b}" for a, b in spans) or "none"


# ---- copy-live -------------------------------------------------------------------------------------------------------


def _byte_copy(source: Path, target: Path) -> None:
    """Plain reads of `source`, writes only to `target`."""
    with source.open("rb") as reader, target.open("wb") as writer:
        for block in iter(lambda: reader.read(1024 * 1024), b""):
            writer.write(block)


def _copy_database(live_db: Path, folder: Path) -> Path:
    """One attempt: the live library (and its `-wal`) copied to `folder` without any SQLite open of a live file that could
    write. Returns the copy's path; raises sqlite3.DatabaseError or NotMeasured when the copy is torn."""
    copy = folder / "library.sqlite"
    for leftover in folder.glob("library.sqlite*"):
        leftover.unlink()
    wal = Path(f"{live_db}-wal")
    if non_empty(wal):
        before = live_db.stat()
        _byte_copy(live_db, copy)
        try:
            _byte_copy(wal, folder / "library.sqlite-wal")
        except FileNotFoundError:
            pass
        after = live_db.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise NotMeasured("the main file changed while it was copied")
    else:
        source = immutable(live_db)
        target = sqlite3.connect(copy)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
    return copy


def _consistent_copy(live_db: Path, folder: Path) -> Path:
    for attempt in range(1, ATTEMPTS + 1):
        try:
            copy = _copy_database(live_db, folder)
            conn = sqlite3.connect(copy)
            try:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok":
                    conn.execute("PRAGMA journal_mode = DELETE")
                    return copy
            finally:
                conn.close()
        except (sqlite3.DatabaseError, NotMeasured):
            pass
        print(f"copy-live: attempt {attempt} of {ATTEMPTS} did not give a consistent copy")
    raise NotMeasured(f"no consistent copy after {ATTEMPTS} attempts: not measured")


def copy_live(live: str, work: str, consent: bool = False) -> dict[str, int]:
    live_dir, work_dir = check_copy_live_paths(live, work, consent)
    names = sorted(os.listdir(live_dir))  # names only
    if "library.sqlite" not in names:
        raise Refused("LIVE_DIR holds no library.sqlite")
    folder = work_dir / COPY
    folder.mkdir(parents=True)
    copy = _consistent_copy(live_dir / "library.sqlite", folder)
    conn = sqlite3.connect(copy)
    try:
        refs = _referenced_files(conn)
    except BackupError as exc:
        raise NotMeasured(f"the library holds an unusable file reference: {exc}") from exc
    finally:
        conn.close()
    copied = missing = 0
    for sub in FILE_FOLDERS:
        for name in sorted(refs[sub]):
            source = live_dir / sub / name
            if not source.is_file():
                missing += 1
                continue
            (folder / sub).mkdir(exist_ok=True)
            _byte_copy(source, folder / sub / name)
            copied += 1
    (work_dir / MARKER).write_text(str(live_dir), encoding="utf-8")
    counts = sql_counts(copy)
    return {"files_copied": copied, "files_missing": missing, "listed_names": len(names), **counts}


# ---- restore-copy ----------------------------------------------------------------------------------------------------


def restore_copy(work: str) -> dict[str, int]:
    work_dir = _resolved(work)
    live_dir = read_marker(work_dir)
    forbid_protected(work_dir, (live_dir,), "WORK_DIR")
    check_work_tree(work_dir, live_dir)
    backup = create_backup(Settings(data_dir=work_dir / COPY), work_dir / BACKUP)
    check_work_tree(work_dir, live_dir)
    result = restore_backup(backup, Settings(data_dir=work_dir / RESTORED))
    return {"files": result["files"], "researches": result["researches"]}


# ---- open-copy -------------------------------------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _walk(value, name: str, found: set | None = None) -> set:
    found = set() if found is None else found
    if isinstance(value, dict):
        for key, item in value.items():
            if key == name and isinstance(item, str):
                found.add(item)
            _walk(item, name, found)
    elif isinstance(value, list):
        for item in value:
            _walk(item, name, found)
    return found


def check_open_paths(work: str) -> tuple[Path, Path]:
    work_dir = _resolved(work)
    live_dir = read_marker(work_dir)
    forbid_protected(work_dir, (live_dir,), "the folder to open")
    check_work_tree(work_dir, live_dir)
    restored = work_dir / RESTORED
    if not restored.is_dir():
        raise Refused(f"{work_dir.name} has no {RESTORED} folder; run restore-copy first")
    for path in (work_dir, restored.resolve()):
        forbid_protected(path, (live_dir,), "the folder to open")
    return work_dir, restored.resolve()


def open_copy(work: str) -> dict:
    """Open WORK_DIR/restored with no worker and no way out. Raises Refused, db.UnknownSchemaError or AssertionError."""
    import httpx
    from fastapi.testclient import TestClient

    from deixis.api.app import create_app

    work_dir, restored = check_open_paths(work)
    db_path = restored / "library.sqlite"
    db.check_schema_known(db_path)
    packaged = db.packaged_versions()
    applied_before = applied_versions(db_path)
    pending = sorted(packaged - set(applied_before))
    unknown = sorted(set(applied_before) - packaged)
    counts_before = sql_counts(db_path)

    outbound: list[str] = []

    def refuse_request(request: httpx.Request):
        outbound.append(request.url.host)
        raise RuntimeError(f"upgrade_check: a request left the app: {request.url.host}")

    async def refuse_fetch(url: str):
        outbound.append(url)
        raise RuntimeError("upgrade_check: a fetch left the app")

    app = create_app(Settings(data_dir=restored, port=_free_port()), adapters={}, start_worker=False,
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(refuse_request)), fetcher=refuse_fetch,
                     xml_fetcher=refuse_fetch, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        worker_started = bool(app.state.owner)
        listed = client.get("/api/researches").json()
        views = [client.get(f"/api/researches/{item['id']}").json() for item in listed]
        views_sources = sum(len(v.get("sources", [])) for v in views)
        views_passages = len(set().union(*[_walk(v, "passage_id") for v in views])) if views else 0
    counts_after = sql_counts(db_path)
    if counts_after != counts_before:
        raise AssertionError(f"opening the restored copy changed the counts: {counts_before} -> {counts_after}")
    applied_after = applied_versions(db_path)
    return {"applied_before": compact(applied_before), "pending": compact(pending), "unknown": compact(unknown),
            "applied_after": compact(applied_after), "applied_by_open": len(set(applied_after) - set(applied_before)),
            "sql_before": counts_before, "sql_after": counts_after,
            "worker_started": worker_started, "outbound_requests": len(outbound),
            "views": {"GET /api/researches": len(listed), "GET /api/researches/{id} sources": views_sources,
                      "distinct passage_id in those views": views_passages}}


# ---- command line ----------------------------------------------------------------------------------------------------


def isolate_environment() -> None:
    """No model sign-in, no key, no system keychain. Done in main(), never at import."""
    import keyring
    from keyring.backends import null

    keyring.set_keyring(null.Keyring())
    for name in MODEL_KEYS:
        os.environ.pop(name, None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="upgrade_check")
    parser.add_argument("--self-test", action="store_true")
    sub = parser.add_subparsers(dest="command")
    first = sub.add_parser("copy-live")
    first.add_argument("live_dir")
    first.add_argument("work_dir")
    first.add_argument(CONSENT, action="store_true", dest="consent")
    sub.add_parser("restore-copy").add_argument("work_dir")
    third = sub.add_parser("open-copy")
    third.add_argument("work_dir")
    third.add_argument(CONSENT, action="store_true", dest="consent", help="accepted and ignored: open-copy never relaxes a rule")
    args = parser.parse_args(argv)
    isolate_environment()
    try:
        if args.self_test:
            return self_test()
        if args.command == "copy-live":
            print("copy-live:", json.dumps(copy_live(args.live_dir, args.work_dir, args.consent)))
        elif args.command == "restore-copy":
            print("restore-copy:", json.dumps(restore_copy(args.work_dir)))
        elif args.command == "open-copy":
            print("open-copy:", json.dumps(open_copy(args.work_dir)))
        else:
            parser.print_usage()
            return 2
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except NotMeasured as exc:
        print(f"not measured: {exc}", file=sys.stderr)
        return 3
    except (db.UnknownSchemaError, db.SchemaCheckUnreadable) as exc:
        print(f"refused schema: {exc}", file=sys.stderr)
        return 1
    except (AssertionError, BackupError) as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 1
    return 0


# ---- self-test -------------------------------------------------------------------------------------------------------


def _tree(folder: Path) -> dict[str, tuple[int, str]]:
    return {p.relative_to(folder).as_posix(): (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in sorted(folder.rglob("*")) if p.is_file()}


def build_synthetic_library(base: Path) -> dict[str, int]:
    """SYNTHETIC library through the in-process app with the test-only FakeAdapter: two researches that share sources, an
    upload, a removed membership, a trashed research. Returns the SQL counts the library has when it is built."""
    sys.path[:0] = [str(REPO / "tests"), str(REPO)]
    from fastapi.testclient import TestClient
    from helpers import make_pdf
    from test_api_flow import app_for, create, session, wait_run

    app = app_for(base)
    with TestClient(app) as raw:
        client = session(raw)
        first, second = create(client), create(client)
        for rid in (first, second):
            run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
            wait_run(client, rid, run["id"])
        shared = ({s["source_version_id"] for s in client.get(f"/api/researches/{first}").json()["sources"]}
                  & {s["source_version_id"] for s in client.get(f"/api/researches/{second}").json()["sources"]})
        assert shared, "the two researches must share a source"
        client.post(f"/api/researches/{first}/uploads", files={"file": ("notes.pdf", make_pdf(["SYNTHETIC notes."]), "application/pdf")})
        removed = client.request("DELETE", f"/api/researches/{first}/sources",
                                 json={"source_version_ids": [sorted(shared)[0]], "note": "SYNTHETIC off topic"})
        assert removed.status_code == 200, removed.text
        trashed = create(client, source_scope="attached")
        assert client.delete(f"/api/researches/{trashed}").status_code == 200
        conn = app.state.store.conn
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("researches", "source_versions", "passages")}  # noqa: S608
        assert conn.execute("SELECT COUNT(*) FROM corpus_memberships WHERE removed_at IS NOT NULL").fetchone()[0] >= 1
        assert conn.execute("SELECT COUNT(*) FROM researches WHERE trashed_at IS NOT NULL").fetchone()[0] == 1
    return counts


def _run_self_test_case(root: Path, with_wal: bool) -> None:
    base = root / ("wal" if with_wal else "clean")
    counts = build_synthetic_library(base)
    live = base / "data"
    for decoy in ("codex-home/auth.json", ".env", "codex-workspace/scratch.txt", "papers/unreferenced.pdf"):
        (live / decoy).parent.mkdir(parents=True, exist_ok=True)
        (live / decoy).write_text("SYNTHETIC decoy: must never be copied")
    holder = None
    if not with_wal:
        assert not (live / "library.sqlite-wal").exists(), "the clean case must have no -wal"
    if with_wal:  # a held-open connection: `-wal` and `-shm` exist, like next to a running service
        holder = sqlite3.connect(live / "library.sqlite")
        holder.execute("PRAGMA journal_mode = WAL")
        holder.execute("PRAGMA wal_autocheckpoint = 0")
        holder.execute("INSERT INTO app_settings (key, value_json, updated_at) VALUES ('p9_selftest', '1', 'now')")
        holder.commit()
        assert non_empty(live / "library.sqlite-wal") and (live / "library.sqlite-shm").exists()
    before, names_before = _tree(live), sorted(p.relative_to(live).as_posix() for p in live.rglob("*"))
    work = base / "work"
    try:
        copied = copy_live(str(live), str(work))
        assert copied["files_missing"] == 0 and copied["files_copied"] >= 1, copied
        assert {k: copied[k] for k in counts} == counts, (copied, counts)
        in_copy = {p.relative_to(work / COPY).as_posix() for p in (work / COPY).rglob("*") if p.is_file()}
        assert "library.sqlite" in in_copy and not (work / COPY / "library.sqlite-wal").exists(), in_copy
        assert all(n == "library.sqlite" or n.split("/")[0] in FILE_FOLDERS for n in in_copy), in_copy
        assert "papers/unreferenced.pdf" not in in_copy and len(in_copy) - 1 == copied["files_copied"], in_copy
        assert not any("SYNTHETIC decoy" in (work / COPY / n).read_text(errors="ignore") for n in in_copy if n.endswith((".txt", ".json"))), in_copy
        restored = restore_copy(str(work))
        assert restored["researches"] == counts["researches"], restored
        opened = open_copy(str(work))
        assert opened["sql_before"] == opened["sql_after"] == counts, (opened, counts)
        # the live folder, every file of it (`-wal` and `-shm` included), is byte-identical and nothing was added to it
        assert _tree(live) == before, "the live folder changed"
        assert sorted(p.relative_to(live).as_posix() for p in live.rglob("*")) == names_before, "a file was created in the live folder"
        print(f"self-test {'wal' if with_wal else 'clean'}: {len(before)} live files unchanged; copy {copied}; restored {restored}; open {json.dumps(opened)}")
    finally:
        if holder is not None:
            holder.close()


def self_test() -> int:
    """Two cases on SYNTHETIC folders in a temp directory: a live folder with a held-open WAL connection, and a clean one.
    The default data directory is replaced by another temp path for the whole run, and the consent flag is never passed."""
    original = config.default_data_dir
    with tempfile.TemporaryDirectory(prefix="p9-upgrade-self-test-") as tmp:
        root = Path(tmp)
        config.default_data_dir = lambda: root / "pretend-default-data-dir"
        saved = os.environ.pop("DEIXIS_DATA_DIR", None)
        try:
            _run_self_test_case(root, with_wal=True)
            _run_self_test_case(root, with_wal=False)
        finally:
            config.default_data_dir = original
            if saved is not None:
                os.environ["DEIXIS_DATA_DIR"] = saved
    print("self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
