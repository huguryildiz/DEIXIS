"""DEIXIS local launcher: `python -m deixis serve`."""

from __future__ import annotations

import argparse
import dataclasses
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from deixis.api.app import create_app
from deixis.config import Settings, load_settings
from deixis.storage import backup


def port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sys.platform != "win32":  # like uvicorn; lingering closed connections must not look like a running server
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def serve(settings: Settings, open_browser: bool, dev_hosts: tuple[str, ...]) -> int:
    url = f"http://{settings.host}:{settings.port}/"
    if settings.host not in ("127.0.0.1", "localhost"):
        print("DEIXIS binds to loopback only; set DEIXIS_HOST=127.0.0.1.", file=sys.stderr)
        return 2
    if not port_available(settings.host, settings.port):
        print(f"Port {settings.port} is in use. DEIXIS may already be running at {url} — "
              "open it, stop the other process, or set DEIXIS_PORT.", file=sys.stderr)
        return 2
    if not settings.web_dist.exists():
        print("UI build not found (apps/web/dist). The API will run; build the UI with `npm run build` in apps/web.")
    # Open event streams would otherwise hold graceful shutdown (and the port) until the browser disconnects.
    server = uvicorn.Server(uvicorn.Config(create_app(settings, extra_hosts=dev_hosts), host=settings.host,
                                           port=settings.port, log_level="info", timeout_graceful_shutdown=3))

    def open_when_ready() -> None:
        for _ in range(100):
            if server.started:
                print(f"DEIXIS is running at {url}")
                if open_browser:
                    webbrowser.open(url)
                return
            time.sleep(0.1)

    threading.Thread(target=open_when_ready, daemon=True).start()
    server.run()
    return 0


def reextract(settings: Settings, dry_run: bool) -> int:
    """Extract every PDF in use again with the current extractor; one line per file, then a summary (D45, D47)."""
    from collections import Counter

    from deixis.documents import pdf
    from deixis.storage import db
    from deixis.workflow.store import RunInProgress, Store

    conn = db.connect(settings.db_path)
    db.migrate(conn)
    store = Store(conn)
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
                report = store.reextract_asset(asset["id"], pdf.extract_pdf(path), pdf.EXTRACTION_VERSION, pdf.chunk_page, dry_run=dry_run)
                outcome, detail = report["outcome"], report.get("rejection_reason") or ""
            except RunInProgress:
                outcome, detail = "run_in_progress", ""
        outcomes[outcome] += 1
        print(f"{outcome:16} {asset['id']}  {asset['extraction_version'] or '-'}  {asset['title'][:60]}  {detail}")
    print(f"{'Dry run: ' if dry_run else ''}{len(assets)} PDFs, " + ", ".join(f"{n} {k}" for k, n in sorted(outcomes.items())))
    conn.close()
    return 0


def equations(settings: Settings, action: str) -> int:
    """Install, check or remove the optional equation reader (Marker) under the data directory (D52)."""
    from deixis.documents import math_reader

    paths = math_reader.runtime_paths(settings.data_dir)
    if action == "install":
        try:
            math_reader.install_runtime(paths)
        except (math_reader.MathReaderUnavailable, OSError, subprocess.CalledProcessError) as exc:
            print(f"install failed: {exc}", file=sys.stderr)
            return 1
        print(f"Marker installed in {paths.env}; its models (about 3.3 GB) download into {paths.models} on the first read.")
    elif action == "remove":
        math_reader.remove_runtime(paths)
        print(f"Removed {paths.env} and {paths.models}.")
    else:
        print(f"{'installed' if paths.installed() else 'not installed'}: {paths.env}")
    return 0


def main(argv: list[str] | None = None) -> int:
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
    eq = sub.add_parser("equations", help="Install, check or remove the optional equation reader (Marker, about 4.4 GB)")
    eq.add_argument("action", choices=("install", "status", "remove"))
    args = parser.parse_args(argv)
    settings = load_settings()
    if args.command == "equations":
        return equations(settings, args.action)
    if args.command == "reextract":
        return reextract(settings, args.dry_run)
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
        # Only the port moves; rebuilding Settings here dropped every other setting the environment had
        # asked for (workflow, approval, the two follow-on runs, query strategy, concurrency) — slice 13 smoke run.
        settings = dataclasses.replace(settings, port=args.port)
    dev_hosts = ("127.0.0.1:5178", "localhost:5178") if args.dev else ()
    return serve(settings, not args.no_browser, dev_hosts)


if __name__ == "__main__":
    sys.exit(main())
