"""DEIXIS local launcher: `python -m deixis serve`."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import os
import socket
import sqlite3
import sys
import threading
import time
import webbrowser
from pathlib import Path
from uuid import uuid4

import uvicorn

from deixis import config
from deixis.keys import log_redaction
from deixis.storage import library_lock
from deixis.api.app import create_app
from deixis.config import Settings, load_settings
from deixis.storage import data_location
from deixis.storage.data_location import PointerDamaged, Postponed, apply_pending_move, data_dir_problem, read_pointer
from deixis.storage import backup, db
from deixis.storage.db import SchemaCheckUnreadable, UnknownSchemaError, check_schema_known
from deixis.system_trust import use_system_certificates


SHUTDOWN_EXIT_SECONDS = 6.0
FORCED_EXIT_CODE = 1


def watch_shutdown(server, seconds: float, exit_function, cancel: threading.Event) -> None:
    """Once the server is asked to stop (SIGINT, SIGTERM), give it `seconds` more, then end the process.

    A graceful shutdown waits for the worker, and the worker waits for a model call that can run for minutes; after a
    Ctrl-C the interpreter also waits for an extraction thread. Nothing is cancelled here: the state at a forced exit is
    the state after a SIGKILL, which the next start recovers (running steps `outcome_unknown`, runs `paused`)."""
    while not server.should_exit:
        if cancel.wait(0.1):
            return
    if cancel.wait(seconds):
        return
    try:
        sys.stderr.write(f"DEIXIS did not finish shutting down in {seconds:g} s; exiting\n")
        sys.stderr.flush()
    except Exception:
        pass  # A full disk or a closed diagnostic stream must not disable the shutdown bound.
    finally:
        exit_function(FORCED_EXIT_CODE)


def port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sys.platform != "win32":  # like uvicorn; lingering closed connections must not look like a running server
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def schema_problem(db_path: Path) -> str | None:
    """Why the library at `db_path` must not be opened (written by a newer DEIXIS, or unreadable), or None. Writes nothing."""
    try:
        check_schema_known(db_path)
    except (UnknownSchemaError, SchemaCheckUnreadable) as exc:
        return str(exc)
    except sqlite3.DatabaseError:  # a damaged file: db.open_problem below names it in one sentence
        return None
    return None


LOCATION_ATTEMPTS = 5
EXIT_MIGRATION_FAILED = 4  # the start-up code for a schema migration that did not apply (E24); every other refusal exits 2


def location_changed(wanted: Path, postponed: Postponed | None) -> Path | str | None:
    """Under the folder lock: None when the location is still what this start read, else the folder to start again with,
    or one sentence when the pointer is now damaged. `wanted` is the folder the start was after; `postponed` is the move
    it left for later, which must still be the pending one."""
    try:
        now = config.default_data_dir()
        pointer = None if data_location.set_outside_app() else read_pointer()
    except PointerDamaged as exc:
        return str(exc)
    if postponed is None:
        return None if now == wanted else now
    if now == wanted and pointer and pointer.get("move_from") == str(postponed.old) and not pointer.get("phase"):
        return None
    return now


def hold_current_folder(settings: Settings) -> Settings | str:
    """The shared folder lock for a command that does not move anything: the settings, with the folder re-read under the lock
    (as `serve` does), or one sentence when the folder is being moved. A folder that cannot hold a lock file is left to the command."""
    for _ in range(LOCATION_ATTEMPTS):
        try:
            if not library_lock.hold_shared(settings.data_dir):
                return f"Another DEIXIS is moving the library in {settings.data_dir}. Try again when it has finished."
        except OSError:
            return settings  # no lock file can be made in this folder; the command reports its own error about it
        if (changed := location_changed(settings.data_dir, None)) is None:
            return settings
        library_lock.release(settings.data_dir)
        if isinstance(changed, str):
            return changed
        settings = dataclasses.replace(settings, data_dir=changed)
    return "The data location kept changing while DEIXIS started. Try again."


def serve(settings: Settings, open_browser: bool, dev_hosts: tuple[str, ...], reread_location: bool = False) -> int:
    """`reread_location`: the settings came from `load_settings`, so the location is read again under the folder lock (a caller
    that builds its own settings has no location to read)."""
    url = f"http://{settings.host}:{settings.port}/"
    if settings.host not in ("127.0.0.1", "localhost"):
        print("DEIXIS binds to loopback only; set DEIXIS_HOST=127.0.0.1.", file=sys.stderr)
        return 2
    if not port_available(settings.host, settings.port):
        print(f"Port {settings.port} is in use. DEIXIS may already be running at {url} — "
              "open it, stop the other process, or set DEIXIS_PORT.", file=sys.stderr)
        return 2
    # A location chosen in Settings (D32) is moved into before anything opens the library, under both folders'
    # exclusive locks (E1). A DEIXIS on another port, or a child it started, holds its folder's shared lock: the move
    # is then postponed and this DEIXIS opens the old folder, saying why in Settings. Another DEIXIS may finish a move
    # between reading the location and taking the lock, so the location is read again under the lock and, when it
    # changed, the lock is let go and the start begins again with the new one.
    for _ in range(LOCATION_ATTEMPTS):
        wanted, postponed = settings.data_dir, None
        if isinstance(message := apply_pending_move(wanted), Postponed):
            postponed = message
            print(postponed.message(), file=sys.stderr)
            settings = dataclasses.replace(settings, data_dir=postponed.old)
        elif message is not None:
            print(message, file=sys.stderr)
            return 2
        if problem := data_dir_problem(settings.data_dir):
            print(f"Cannot use the data directory {settings.data_dir}: it {problem}. "
                  "Set DEIXIS_DATA_DIR to a folder you can write to.", file=sys.stderr)
            return 2
        # The folder's shared lock is held from here, before the library is opened, until this process ends.
        if not library_lock.hold_shared(settings.data_dir):
            print(f"Another DEIXIS is moving the library in {settings.data_dir}. Start DEIXIS again when it has finished.", file=sys.stderr)
            return 2
        if not reread_location or (changed := location_changed(wanted, postponed)) is None:
            break
        library_lock.release(settings.data_dir)
        if isinstance(changed, str):
            print(changed, file=sys.stderr)
            return 2
        settings = dataclasses.replace(settings, data_dir=changed)
    else:
        print("The data location kept changing while DEIXIS started. Start DEIXIS again.", file=sys.stderr)
        return 2
    if (message := schema_problem(settings.db_path)) is not None:
        print(message, file=sys.stderr)
        return 2
    # P9 H3: a library that cannot be opened is one sentence and exit 2, not a traceback. H4's read-only precheck above
    # runs first because this block's db.connect creates -wal/-shm files and switches the journal mode. A failing
    # migration is its own case (E24): exit 4, a sentence that points at the backup.
    if (problem := db.open_problem(settings.db_path)) is not None:
        print(problem, file=sys.stderr)
        return EXIT_MIGRATION_FAILED if getattr(problem, "code", None) == db.MigrationFailed.code else 2
    if not settings.web_dist.exists():
        print("UI build not found (apps/web/dist). The API will run; build the UI with `npm run build` in apps/web.")
    # Open event streams would otherwise hold graceful shutdown (and the port) until the browser disconnects.
    app = create_app(settings, extra_hosts=dev_hosts)
    if postponed is not None:
        app.state.move_postponed = {"path": str(postponed.new), "busy": str(postponed.busy)}
    server = uvicorn.Server(uvicorn.Config(app, host=settings.host, port=settings.port, log_level="info",
                                           timeout_graceful_shutdown=3))

    def open_when_ready() -> None:
        for _ in range(100):
            if server.started:
                print(f"DEIXIS is running at {url}")
                if open_browser:
                    webbrowser.open(url)
                return
            time.sleep(0.1)

    threading.Thread(target=open_when_ready, daemon=True).start()
    # Never cancelled here: the executor join it guards happens inside `asyncio.run`'s close, inside `server.run()`, so the
    # thread is simply left running (the cancel event exists for the unit test).
    threading.Thread(target=watch_shutdown, args=(server, SHUTDOWN_EXIT_SECONDS, os._exit, threading.Event()), daemon=True).start()
    server.run()
    return 0


def reextract(settings: Settings, dry_run: bool, retry: str | None = None, expected_extraction: str | None = None) -> int:
    """Extract every PDF in use again with the current extractor; one line per file, then a summary (D45, D47)."""
    from collections import Counter

    from deixis.documents import pdf
    from deixis.storage import db
    from deixis.workflow.store import RunInProgress, Store
    from deixis.workflow.text_retry import FileBusy, file_lock, read_verified_sync

    if retry is not None:
        return retry_text(settings, retry, expected_extraction, dry_run)

    if (message := schema_problem(settings.db_path)) is not None:
        print(message, file=sys.stderr)
        return 2
    conn = db.connect(settings.db_path)
    db.migrate(conn)
    store = Store(conn)
    store.recovery_dir = settings.recovery_dir
    assets = conn.execute(
        "SELECT a.id, a.storage_path, a.extraction_version, v.title FROM source_assets a JOIN source_versions v ON v.id = a.source_version_id"
        " WHERE a.removed_at IS NULL AND a.extraction_version IS NOT ? AND IFNULL(a.extraction_version, '') NOT LIKE ? || '+%'"
        " ORDER BY a.retrieved_at", (pdf.EXTRACTION_VERSION, pdf.EXTRACTION_VERSION)
    ).fetchall()
    outcomes: Counter[str] = Counter()
    for asset in assets:
        path = settings.papers_dir / asset["storage_path"]
        if not path.exists():
            outcome, detail = "file_missing", ""
        else:
            try:
                with file_lock(settings.recovery_dir, store.asset(asset["id"])["sha256"]):
                    stored = store.asset(asset["id"])
                    read = read_verified_sync(store, settings.papers_dir, settings.recovery_dir,
                        storage_path=stored["storage_path"], sha256=stored["sha256"], byte_size=stored["byte_size"])
                    if read.observation is not None and read.observation["integrity"] != "verified":
                        report = {"outcome": "input_not_verified"}
                    else:
                        report = store.reextract_asset(asset["id"], read.extraction, pdf.EXTRACTION_VERSION, pdf.chunk_page,
                                                      dry_run=dry_run, input_observation=read.observation)
                outcome, detail = report["outcome"], report.get("rejection_reason") or ""
            except FileBusy:
                outcome, detail = "file_busy", ""
            except RunInProgress:
                outcome, detail = "run_in_progress", ""
        outcomes[outcome] += 1
        print(f"{outcome:16} {asset['id']}  {asset['extraction_version'] or '-'}  {asset['title'][:60]}  {detail}")
    print(f"{'Dry run: ' if dry_run else ''}{len(assets)} PDFs, " + ", ".join(f"{n} {k}" for k, n in sorted(outcomes.items())))
    conn.close()
    return 0


def _storage_cause(exc: BaseException):
    failure = db.describe_failure(exc)
    while failure is None and exc.__cause__ is not None:
        exc = exc.__cause__
        failure = db.describe_failure(exc)
    return failure


def _retry_line(result: dict) -> None:
    print(f"{result['lifecycle']} {result['outcome'] or '-'} {result['reason'] or result['decision_code'] or '-'} "
          f"{result['operation_id']} {result['extraction_version'] or '-'}")


def retry_text(settings: Settings, asset_id: str, expected_extraction: str, dry_run: bool) -> int:
    from deixis.workflow import text_retry
    from deixis.workflow.store import Store, NotFound, NotRetryable, RecoveryConflict, RequestConflict, RunInProgress

    if dry_run:
        return plan_text_retry(settings, asset_id, expected_extraction)
    conn, store, key = None, None, "cli-" + uuid4().hex
    try:
        check_schema_known(settings.db_path)
        conn = db.connect(settings.db_path)
        db.migrate(conn)
        store = Store(conn)
        store.recovery_dir = settings.recovery_dir
        asset = store.asset(asset_id)
        result = asyncio.run(text_retry.execute_text_retry(store, settings, asset_id=asset_id,
            expected_extraction_id=expected_extraction, idempotency_key=key, research_id=None,
            source_version_id=asset["source_version_id"]))
        _retry_line(result)
        return 0 if result["lifecycle"] == "completed" else 1
    except (NotFound, NotRetryable, RecoveryConflict, RequestConflict, RunInProgress, text_retry.FileBusy,
            text_retry.FileMissing) as exc:
        print(f"Text retry refused: {type(exc).__name__} ({exc}).", file=sys.stderr)
        return 2
    except BaseException as exc:
        operation = None
        if store is not None:
            try:
                operation = store.text_retry_by_key(key)
            except Exception:
                pass
        if operation is not None or (store is not None and store.pending_text_retry_interruptions):
            if operation is not None:
                if operation["lifecycle"] == "running":
                    print("The text retry operation stays running until DEIXIS reconciles it (at its next start, while it runs, or at the next retry of this file).", file=sys.stderr)
                else:
                    try:
                        _retry_line(store.text_retry_view(operation["id"]))
                    except Exception:
                        # Reporting an interruption must not hide the error that caused it.
                        pass
            else:
                print("The text retry operation stays running until DEIXIS reconciles it (at its next start, while it runs, or at the next retry of this file).", file=sys.stderr)
            print(f"Text retry interrupted by {type(exc).__name__}.", file=sys.stderr)
            return 1
        if (failure := _storage_cause(exc)) is not None:
            print(failure[2], file=sys.stderr)
            return 3
        if isinstance(exc, (UnknownSchemaError, SchemaCheckUnreadable)):
            print(str(exc), file=sys.stderr)
            return 2
        raise
    finally:
        if conn is not None:
            conn.close()


def plan_text_retry(settings: Settings, asset_id: str, expected_extraction: str) -> int:
    import tempfile
    from deixis.documents import pdf
    from deixis.workflow import recovery, text_retry
    from deixis.workflow.store import Store, NotFound

    try:
        with text_retry.library_snapshot(settings.db_path) as conn:
            applied = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
            if applied != db.packaged_versions():
                print("this library needs a migration; start DEIXIS once or run without --dry-run", file=sys.stderr)
                return 2
            store = Store(conn)
            try:
                asset = store.asset(asset_id)
            except NotFound:
                print("would refuse asset_removed")
                return 0
            baseline = store._retry_baseline(asset_id)
            reason = None
            if asset["removed_at"] is not None:
                reason = "asset_removed"
            elif baseline is None or baseline["id"] != expected_extraction:
                reason = "baseline_changed"
            elif baseline["status"] in ("succeeded", "pending"):
                reason = "already_current" if baseline["status"] == "succeeded" else "pending"
            elif store._asset_run_active(asset["source_version_id"]):
                reason = "run_active"
            elif conn.execute("SELECT 1 FROM asset_recovery_operations WHERE asset_id = ? AND kind = 'text_retry'"
                               " AND lifecycle = 'running'", (asset_id,)).fetchone():
                reason = "operation_running"
            if reason:
                print(f"would refuse {reason}")
                return 0
            try:
                text_retry.precheck(settings.papers_dir, asset["storage_path"])
            except text_retry.FileMissing:
                print("would refuse file_missing")
                return 0
            with tempfile.TemporaryDirectory(prefix="deixis-retry-input-") as folder:
                copy_path = Path(folder) / "input.pdf"
                integrity, _, _ = text_retry.observe_copy(settings.papers_dir, asset["storage_path"],
                    asset["sha256"], asset["byte_size"], copy_path)
                if integrity != "verified":
                    print("would refuse " + ("file_missing" if integrity == "missing" else "file_mismatch"))
                    return 0
                try:
                    candidate = pdf.extract_pdf(copy_path)
                except Exception as exc:
                    print(f"Text retry planning parser failed with {type(exc).__name__}.", file=sys.stderr)
                    return 1
                decision = recovery.decide(baseline, {"status": candidate.status, "error": candidate.error,
                    "page_count": candidate.page_count, "extractor_profile": candidate.extraction_version,
                    "manifest": recovery.coverage_manifest(candidate, pdf.chunk_page)})
                print(f"would {'promote' if decision.promote else 'reject'} {decision.decision_code}")
                return 0
    except text_retry.SnapshotUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (OSError, SchemaCheckUnreadable) as exc:
        failure = _storage_cause(exc)
        print(failure[2] if failure else "Could not copy the library or extraction input for this dry run.", file=sys.stderr)
        return 3


def recovery_files(settings: Settings, delete: bool) -> int:
    from deixis.workflow import reconcile, recovery_history
    from deixis.workflow.store import Store

    if (message := schema_problem(settings.db_path)) is not None:
        print(message, file=sys.stderr)
        return 2
    conn = db.connect(settings.db_path)
    try:
        db.migrate(conn)
        store = Store(conn)
        store.recovery_dir = settings.recovery_dir
        asyncio.run(reconcile.reconcile_stale(store, settings.papers_dir, settings.recovery_dir))
        failed = False
        for name, size in recovery_history.unreferenced_retained(store, settings.papers_dir):
            if delete:
                removed = recovery_history.remove_retained(store, settings.papers_dir, name)
                failed |= not removed
                print(f"{'deleted' if removed else 'not removed'} {name} {size} bytes")
            else:
                print(f"{name} {size} bytes")
        return int(failed)
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    given = sys.argv[1:] if argv is None else argv
    if given[:1] == ["hold-folder"]:  # the Windows holder of a child's folder lock (library_lock.holder_main); not a user command
        return library_lock.holder_main(given[1:])
    parser = argparse.ArgumentParser(prog="deixis")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("serve", help="Start the local API, worker and UI")
    run.add_argument("--port", type=int)
    run.add_argument("--no-browser", action="store_true")
    run.add_argument("--dev", action="store_true", help="Also accept requests proxied from the Vite dev server (port 5178)")
    save = sub.add_parser("backup", help="Write a consistent backup of the local library (safe while serving)")
    save.add_argument("destination", type=Path, help="Folder in which a new dated backup folder is created")
    load = sub.add_parser("restore", help="Restore a backup into a data directory that has no library yet")
    load.add_argument("backup", type=Path, help="A backup folder created by `deixis backup`")
    again = sub.add_parser("reextract", help="Extract the text of every PDF in use again with the current extractor")
    again.add_argument("--dry-run", action="store_true", help="Report what would become current or be rejected; write nothing")
    again.add_argument("--retry", metavar="ASSET_ID", help="Retry one failed or partial text extraction")
    again.add_argument("--expected-extraction", metavar="EXTRACTION_ID", help="The retry's current extraction baseline")
    retained = sub.add_parser("recovery-files", help="List unreferenced retained recovery files")
    retained.add_argument("--delete", action="store_true", help="Delete listed files through the guarded recovery unlink")
    args = parser.parse_args(argv)
    use_system_certificates()  # before any HTTP client is built (F1)
    log_redaction.install()  # E27
    if args.command == "reextract" and bool(args.retry) != bool(args.expected_extraction):
        parser.error("--retry and --expected-extraction must be supplied together")
    try:
        settings = load_settings()
    except PointerDamaged as exc:  # E23: never an empty default library in place of the one the pointer named
        print(str(exc), file=sys.stderr)
        return 2
    if args.command != "serve":  # every process that opens the library holds its folder's shared lock (E1); `serve` takes it after a move
        if isinstance(held := hold_current_folder(settings), str):
            print(held, file=sys.stderr)
            return 2
        settings = held
    if args.command == "recovery-files":
        return recovery_files(settings, args.delete)
    if args.command == "reextract":
        return reextract(settings, args.dry_run, args.retry, args.expected_extraction)
    if args.command in ("backup", "restore"):
        try:
            if args.command == "backup":
                print(f"Backup written to {backup.create_backup(settings, args.destination)}")
            else:
                result = backup.restore_backup(args.backup, settings)
                print(f"Restored {result['researches']} researches and {result['files']} files into {settings.data_dir}")
        except backup.BackupError as exc:
            print(f"{args.command} failed: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.port:
        # Only the port moves; rebuilding Settings here dropped approval, follow-on run settings, query strategy
        # and concurrency requested by the environment (slice 13 smoke run).
        settings = dataclasses.replace(settings, port=args.port)
    dev_hosts = ("127.0.0.1:5178", "localhost:5178") if args.dev else ()
    return serve(settings, not args.no_browser, dev_hosts, reread_location=True)


if __name__ == "__main__":
    sys.exit(main())
