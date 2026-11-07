"""DEIXIS local launcher: `python -m deixis serve`."""

from __future__ import annotations

import argparse
import asyncio
import copy
import dataclasses
import json
import logging
import logging.handlers
import os
import secrets
import socket
import sqlite3
import sys
import threading
import time
import webbrowser
from pathlib import Path
from uuid import uuid4

import uvicorn

from deixis.runtime import config
from deixis.keys import log_redaction
from deixis.storage import library_lock
from deixis.api.app import create_app
from deixis.runtime.config import Settings, load_settings
from deixis.storage import data_location
from deixis.storage.data_location import PointerDamaged, Postponed, apply_pending_move, data_dir_problem, read_pointer
from deixis.storage import backup, db
from deixis.storage.db import SchemaCheckUnreadable, UnknownSchemaError, check_schema_known
from deixis.runtime.system_trust import use_system_certificates
from deixis.tools import child_record


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


IDLE_CHECK_SECONDS = 30.0


class LastRequest:
    """ASGI wrapper that notes when the last HTTP request arrived (the UI polls every few seconds while a tab is open)."""

    def __init__(self, app):
        self.app = app
        self.at = time.monotonic()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            self.at = time.monotonic()
        await self.app(scope, receive, send)


def library_busy(db_path: Path) -> bool:
    """A run or a background fetch is queued or working. An unreadable library counts as busy: the server stays up."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        try:
            return conn.execute(
                "SELECT EXISTS(SELECT 1 FROM runs WHERE status IN ('queued', 'running', 'pause_requested'))"
                " OR EXISTS(SELECT 1 FROM fast_path_background_fetches WHERE status IN ('queued', 'running'))").fetchone()[0] == 1
        finally:
            conn.close()
    except sqlite3.Error:
        return True


def watch_idle(server, seconds: float, last_request, busy, cancel: threading.Event, check: float = IDLE_CHECK_SECONDS) -> None:
    """Ask the server to stop once no request came for `seconds` and nothing is working (`serve --idle-exit`, used by
    DEIXIS.app, whose launcher exits right after the start and so cannot stop the server when the browser tab closes)."""
    while not cancel.wait(check):
        if server.should_exit:
            return
        if time.monotonic() - last_request() >= seconds and not busy():
            print(f"No browser tab for {seconds / 60:g} min and nothing working; stopping", file=sys.stderr)
            server.should_exit = True
            return


def port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sys.platform != "win32":  # like uvicorn; lingering closed connections must not look like a running server
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def schema_refusal(db_path: Path) -> tuple[str, str] | None:
    """The startup code and sentence why the library at `db_path` must not be opened (written by a newer DEIXIS, or
    unreadable), or None. Writes nothing."""
    try:
        check_schema_known(db_path)
    except UnknownSchemaError as exc:
        return "schema_newer", str(exc)
    except SchemaCheckUnreadable as exc:
        return "schema_unreadable", str(exc)
    except sqlite3.DatabaseError:  # a damaged file: db.open_problem below names it in one sentence
        return None
    return None


def schema_problem(db_path: Path) -> str | None:
    """Why the library at `db_path` must not be opened (written by a newer DEIXIS, or unreadable), or None. Writes nothing."""
    refusal = schema_refusal(db_path)
    return refusal[1] if refusal else None


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


# `serve --desktop` (P10 M1): the packaged app's shell (Tauri) starts the backend and reads its stdout, which then carries
# only one-line JSON events: `listening` once the socket is bound and the app's lifespan start has passed, or
# `startup_failed` (a code and the same sentence a person reads on stderr) for every refusal. Human text stays on stderr.
DESKTOP_PORT_FILE = "desktop-port.json"
LOG_FILE_BYTES = 5 * 1024 * 1024
LOG_FILES = 5


EMITTED: list[str] = []  # the events this process has printed, so a start reports at most one outcome


def emit(event: dict) -> None:
    """One JSON line on stdout, flushed at once: the shell waits for it."""
    EMITTED.append(event["event"])
    sys.stdout.write(json.dumps(event) + "\n")  # ASCII only: the pipe's code page (cp1254 on a Turkish Windows) never garbles a path
    sys.stdout.flush()


def desktop_start(start) -> int:
    """The error boundary of a desktop start: an error no refusal names (a socket that cannot listen, a log folder that
    cannot be made, a setting with a bad value) still gives the shell one `startup_failed` line before the process ends
    as it does today (the exception and its traceback, exit 1). Nothing is printed once `listening` or a refusal was."""
    EMITTED.clear()  # one start per process
    try:
        return start()
    except (Exception, SystemExit) as exc:
        if not EMITTED and not (isinstance(exc, SystemExit) and exc.code in (0, None)):
            message = f"{type(exc).__name__}: {exc}" if not isinstance(exc, SystemExit) else f"exit {exc.code}"
            emit({"event": "startup_failed", "code": "start_error", "message": message})
        raise


def refusal(desktop: bool, code: str, message: str, exit_code: int = 2) -> int:
    """A start that stops: the sentence on stderr, as always; in desktop mode also a `startup_failed` line."""
    print(message, file=sys.stderr)
    if desktop:
        emit({"event": "startup_failed", "code": code, "message": str(message)})
    return exit_code


def saved_port(data_dir: Path) -> int | None:
    try:
        port = json.loads((data_dir / DESKTOP_PORT_FILE).read_text(encoding="utf-8")).get("port")
    except (OSError, ValueError, AttributeError):
        return None
    return port if isinstance(port, int) and 0 < port < 65536 else None


def save_port(data_dir: Path, port: int) -> None:
    target = data_dir / DESKTOP_PORT_FILE
    partial = target.with_name(target.name + ".partial")
    partial.write_text(json.dumps({"port": port}) + "\n", encoding="utf-8")
    os.replace(partial, target)


def bind_listener(host: str, port: int) -> socket.socket | None:
    """A socket bound to (host, port), handed to uvicorn as is: no probe-then-bind gap. None when the port is taken."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform != "win32":  # like uvicorn; lingering closed connections must not look like a running server
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError:
        sock.close()
        return None
    return sock


def desktop_listener(settings: Settings, given_port: int | None) -> socket.socket | None:
    """The preferred port (the one given, else the one saved in the data folder, else the configured one, 8765 by
    default), else any free port; the port bound is saved as the next start's preference."""
    saved = saved_port(settings.data_dir)
    sock = bind_listener(settings.host, given_port or saved or settings.port) or bind_listener(settings.host, 0)
    if sock is not None and (port := sock.getsockname()[1]) != saved:
        try:
            save_port(settings.data_dir, port)
        except OSError:
            pass  # the next start picks again
    return sock


def watch_stdin(server, read=None) -> None:
    """Desktop mode: the shell holds the backend's stdin open; at EOF (the shell quit or was killed) shut down gracefully.
    `watch_shutdown` still bounds the shutdown."""
    read = read or (lambda: os.read(sys.stdin.fileno(), 65536))
    try:
        while read():
            pass
    except (OSError, ValueError, AttributeError):
        pass
    server.should_exit = True  # first: with the shell gone, stderr may be a closed pipe and the print below fail
    try:
        print("stdin closed; stopping", file=sys.stderr)
    except (OSError, ValueError):
        pass


TOKEN_LINE_LIMIT = 4096


def read_stdin_token(read=None) -> str | None:
    """Desktop mode (P10 M2): the shell writes the control token as the first line on stdin, where `ps eww` cannot show
    it. Read byte by byte up to the newline, so nothing after it is taken from `watch_stdin`, which then waits for EOF.
    An empty line, EOF or an unreadable stdin means no token (the shutdown route stays off)."""
    read = read or (lambda: os.read(sys.stdin.fileno(), 1))
    line = b""
    try:
        while len(line) < TOKEN_LINE_LIMIT:
            byte = read()
            if not byte or byte == b"\n":
                break
            line += byte
    except (OSError, ValueError, AttributeError):
        return None
    return line.decode("utf-8", "replace").strip() or None


class LifespanFailure:
    """ASGI wrapper that keeps the last line of the lifespan start's failure (Starlette sends the traceback text)."""

    def __init__(self, app):
        self.app = app
        self.message: str | None = None

    def __getattr__(self, name):
        return getattr(self.app, name)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "lifespan":
            return await self.app(scope, receive, send)

        async def watched(message):
            if message.get("type") == "lifespan.startup.failed":
                lines = [line for line in str(message.get("message") or "").splitlines() if line.strip()]
                self.message = lines[-1].strip() if lines else "The app did not start."
            await send(message)

        await self.app(scope, receive, watched)


def desktop_server(config, on_started, on_failed):
    """A uvicorn server that calls `on_started` once its start (lifespan included) has passed and `on_failed` when the
    lifespan start fails (uvicorn then exits the process with its startup code)."""

    class DesktopServer(uvicorn.Server):
        async def startup(self, sockets=None):
            try:
                await super().startup(sockets=sockets)
            except SystemExit:
                on_failed()
                raise
            if self.started:
                on_started()

    return DesktopServer(config)


def desktop_log_config() -> dict:
    """uvicorn's logging setup with the access log on stderr: in desktop mode stdout carries only the JSON events."""
    config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    config["handlers"]["access"]["stream"] = "ext://sys.stderr"
    return config


def add_log_file(data_dir: Path) -> None:
    """Desktop mode: the app's and uvicorn's log lines also go to `logs/backend.log` in the data folder, rotated at 5 MB,
    five files kept. Keys are redacted when a record is made (`log_redaction`), before any handler sees it."""
    folder = data_dir / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(folder / "backend.log", maxBytes=LOG_FILE_BYTES,
                                                   backupCount=LOG_FILES - 1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
    if not root.handlers:  # keep warnings on stderr, where they went before a handler existed
        stream = logging.StreamHandler(sys.stderr)
        stream.setLevel(logging.WARNING)
        root.addHandler(stream)
    for logger in (root, logging.getLogger("uvicorn"), logging.getLogger("uvicorn.access")):
        logger.addHandler(handler)


def serve(settings: Settings, open_browser: bool, dev_hosts: tuple[str, ...], reread_location: bool = False,
          idle_exit: float | None = None, desktop: bool = False, control_token: str | None = None,
          given_port: int | None = None) -> int:
    """`reread_location`: the settings came from `load_settings`, so the location is read again under the folder lock (a caller
    that builds its own settings has no location to read). `idle_exit`: seconds without a request after which an idle
    server stops itself (see `watch_idle`); None keeps it running. `desktop`: started by the packaged app's shell (see
    `emit`); the port is chosen after the library checks, bound once and saved, `control_token` enables the shutdown
    route and stdin EOF stops the server."""
    def refuse(code: str, message: str, exit_code: int = 2) -> int:
        return refusal(desktop, code, message, exit_code)

    url = f"http://{settings.host}:{settings.port}/"
    if settings.host not in ("127.0.0.1", "localhost"):
        return refuse("host_not_loopback", "DEIXIS binds to loopback only; set DEIXIS_HOST=127.0.0.1.")
    if not desktop and not port_available(settings.host, settings.port):
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
            return refuse("move_refused", message)
        if problem := data_dir_problem(settings.data_dir):
            return refuse("data_dir_unusable", f"Cannot use the data directory {settings.data_dir}: it {problem}. "
                          "Set DEIXIS_DATA_DIR to a folder you can write to.")
        # The folder's shared lock is held from here, before the library is opened, until this process ends.
        if not library_lock.hold_shared(settings.data_dir):
            return refuse("library_locked", f"Another DEIXIS is moving the library in {settings.data_dir}. "
                          "Start DEIXIS again when it has finished.")
        if not reread_location or (changed := location_changed(wanted, postponed)) is None:
            break
        library_lock.release(settings.data_dir)
        if isinstance(changed, str):
            return refuse("pointer_damaged", changed)
        settings = dataclasses.replace(settings, data_dir=changed)
    else:
        return refuse("location_changing", "The data location kept changing while DEIXIS started. Start DEIXIS again.")
    if (schema := schema_refusal(settings.db_path)) is not None:
        return refuse(*schema)
    # P9 H3: a library that cannot be opened is one sentence and exit 2, not a traceback. H4's read-only precheck above
    # runs first because this block's db.connect creates -wal/-shm files and switches the journal mode. A failing
    # migration is its own case (E24): exit 4, a sentence that points at the backup.
    if (problem := db.open_problem(settings.db_path)) is not None:
        if getattr(problem, "code", None) == db.MigrationFailed.code:
            return refuse(db.MigrationFailed.code, problem, EXIT_MIGRATION_FAILED)
        return refuse("library_cannot_open", problem)
    if not settings.web_dist.exists():
        print("UI build not found (web/dist). The API will run; build the UI with `npm run build` in web.",
              file=sys.stderr if desktop else sys.stdout)
    listener = None
    if desktop:
        if (listener := desktop_listener(settings, given_port)) is None:
            return refuse("port_unavailable", f"No free port on {settings.host} for DEIXIS.")
        settings = dataclasses.replace(settings, port=listener.getsockname()[1])
    nonce = secrets.token_urlsafe(16) if desktop else None
    # P10 M2: every process started in a session of its own is recorded from here on; what a backend that ended left
    # running is stopped first, before this one starts any child.
    if desktop and os.environ.pop(child_record.ACK_ENV, None) == "1" and child_record.ON:
        # Started by the desktop watchdog: it learns the record's path, and says so, before any child can be recorded.
        print(json.dumps({"event": "child_record", "path": str(child_record.record_path(settings.data_dir))}), flush=True)
        if read_stdin_token() != "ack":
            return refuse("watchdog_gone", "The DEIXIS watchdog did not answer; DEIXIS did not start.")
    recovered = child_record.recover(child_record.configure(settings.data_dir))
    if recovered:
        print(f"Stopped {len(recovered)} processes left running by a DEIXIS that ended: {', '.join(recovered)}",
              file=sys.stderr)
    # Open event streams would otherwise hold graceful shutdown (and the port) until the browser disconnects.
    shutdown_holder: list = []
    if desktop:
        app = create_app(settings, extra_hosts=dev_hosts, control_token=control_token, start_nonce=nonce,
                         request_shutdown=lambda: setattr(shutdown_holder[0], "should_exit", True))
    else:
        app = create_app(settings, extra_hosts=dev_hosts)
    if postponed is not None:
        app.state.move_postponed = {"path": str(postponed.new), "busy": str(postponed.busy)}
    tracked = LastRequest(app)
    if desktop:
        watched = LifespanFailure(tracked)
        config = uvicorn.Config(watched, host=settings.host, port=settings.port, log_level="info",
                                timeout_graceful_shutdown=3, log_config=desktop_log_config())
        add_log_file(settings.data_dir)
        if recovered:
            logging.getLogger("deixis.child_record").warning("stopped %d processes left by a DEIXIS that ended: %s",
                                                             len(recovered), ", ".join(recovered))
        server = desktop_server(
            config,
            on_started=lambda: emit({"event": "listening", "port": settings.port, "pid": os.getpid(), "nonce": nonce,
                                     "data_dir": str(settings.data_dir)}),
            on_failed=lambda: refuse("lifespan_failed", watched.message or "The app did not start."))
        shutdown_holder.append(server)
        threading.Thread(target=watch_shutdown, args=(server, SHUTDOWN_EXIT_SECONDS, os._exit, threading.Event()), daemon=True).start()
        threading.Thread(target=watch_stdin, args=(server,), daemon=True).start()
        try:
            server.run(sockets=[listener])
        finally:
            listener.close()
        return 0
    server = uvicorn.Server(uvicorn.Config(tracked, host=settings.host, port=settings.port, log_level="info",
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
    if idle_exit is not None:
        threading.Thread(target=watch_idle, args=(server, idle_exit, lambda: tracked.at, lambda: library_busy(settings.db_path),
                                                  threading.Event()), daemon=True).start()
    server.run()
    return 0


def reextract(settings: Settings, dry_run: bool, retry: str | None = None, expected_extraction: str | None = None) -> int:
    """Extract every PDF in use again with the current extractor; one line per file, then a summary (D45, D47)."""
    from collections import Counter

    from deixis.documents import pdf
    from deixis.storage import db
    from deixis.workflow.run.store import RunInProgress, Store
    from deixis.workflow.read.text_retry import FileBusy, file_lock, read_verified_sync

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
    from deixis.workflow.read import text_retry
    from deixis.workflow.run.store import Store, NotFound, NotRetryable, RecoveryConflict, RequestConflict, RunInProgress

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
    from deixis.workflow.read import recovery, text_retry
    from deixis.workflow.run.store import Store, NotFound

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
    from deixis.workflow.read import reconcile, recovery_history
    from deixis.workflow.run.store import Store

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
    if given[:1] == ["--check-resources"]:  # read-only: the packaged app's files and modules, from inside the process (P10 M1)
        from deixis.runtime import resource_check
        return resource_check.main()
    # The packaged app's shell passes the shutdown token as the first stdin line (read below, P10 M2); the environment
    # is still read (tests, M1 smoke) and the name removed either way, so no child this process starts (the Claude SDK
    # copies os.environ) inherits it.
    control_token = os.environ.pop("DEIXIS_CONTROL_TOKEN", None) or None
    parser = argparse.ArgumentParser(prog="deixis")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("serve", help="Start the local API, worker and UI")
    run.add_argument("--port", type=int)
    run.add_argument("--no-browser", action="store_true")
    run.add_argument("--idle-exit", type=float, metavar="MINUTES",
                     help="Stop after this many minutes with no browser request and no run working")
    run.add_argument("--dev", action="store_true", help="Also accept requests proxied from the Vite dev server (port 5178)")
    run.add_argument("--desktop", action="store_true", help=argparse.SUPPRESS)  # only the packaged app's shell passes it
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
    if args.command == "serve" and args.desktop:
        if control_token is None:
            control_token = read_stdin_token()
        return desktop_start(lambda: run_command(args, parser, control_token))
    return run_command(args, parser, control_token)


def run_command(args: argparse.Namespace, parser: argparse.ArgumentParser, control_token: str | None) -> int:
    use_system_certificates()  # before any HTTP client is built (F1)
    log_redaction.install()  # E27
    if args.command == "reextract" and bool(args.retry) != bool(args.expected_extraction):
        parser.error("--retry and --expected-extraction must be supplied together")
    try:
        settings = load_settings()
    except PointerDamaged as exc:  # E23: never an empty default library in place of the one the pointer named
        return refusal(args.command == "serve" and args.desktop, "pointer_damaged", str(exc))
    if args.command == "restore":  # refused before the folder lock exists, so a refusal leaves the target as it was
        try:
            backup.check_restore(args.backup, settings)
        except backup.BackupError as exc:
            print(f"restore failed: {exc}", file=sys.stderr)
            return 1
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
    idle_exit = args.idle_exit * 60 if args.idle_exit else None
    if args.desktop:
        return serve(settings, False, dev_hosts, reread_location=True, desktop=True, control_token=control_token,
                     given_port=args.port)
    return serve(settings, not args.no_browser, dev_hosts, reread_location=True, idle_exit=idle_exit)


if __name__ == "__main__":
    sys.exit(main())
