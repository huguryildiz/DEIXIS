"""P9 H2 driver: the real launcher (`deixis.__main__.serve`) with scripted stand-ins, started as a child by the process tests.

Not a test module. `serve` builds the production `uvicorn.Config` and handles SIGINT and SIGTERM itself, so what a test
signals is the production shutdown. The model is `fixture_server.ScriptedCodex`, OpenAlex is its mocked handler and
the PDF fetcher is its fixed SYNTHETIC files; no request leaves the machine and a guard logs one that tries (`network`).

Controls by environment (all optional):
  P9_CALLS                path of the JSONL log (one fsynced line per event: model, fetch, provider, extract, held, network)
  P9_HOLD_TASK, P9_HOLD_NTH   the nth model call of that task type is logged and then held open (default 1st)
  P9_HOLD_FETCH_NTH       the nth PDF fetch is logged and then held open
  P9_HOLD_PAPER_WRITE_NTH the nth `Path.write_bytes` into <data>/papers/ for a `.pdf` or `.part` file writes the first
                          half of the bytes, syncs them and sleeps (a write cut by SIGKILL, on old and new code alike)
  P9_HOLD_EXTRACT_NTH     the nth `pdf.extract_pdf` call is logged and then held in its thread
  P9_GATE_DIR             a TEMP trigger calls `p9_gate()` when an asset's second passage is inserted; once
                          <dir>/armed exists it writes <dir>/reached and sleeps inside the open write transaction
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import json
import os
import pathlib
import socket
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "tests" / "acceptance"), str(REPO / "tests"), str(REPO / "backend")]

import fixture_server as fx  # noqa: E402
import httpx  # noqa: E402
from deixis import __main__ as deixis_main  # noqa: E402
from deixis.api.app import create_app  # noqa: E402
from deixis.config import Settings  # noqa: E402
from deixis.documents import fetch as fetch_module  # noqa: E402
from deixis.documents import pdf  # noqa: E402
from deixis.documents import pdf_files  # noqa: E402
from deixis.documents.fetch import FetchResult  # noqa: E402
from deixis.storage import db  # noqa: E402
from fakes import parse_step_input  # noqa: E402

REFUSED_PORTS = {8765, *range(8858, 8865)}
CALLS = Path(os.environ["P9_CALLS"]) if os.environ.get("P9_CALLS") else None
HOLD_TASK = os.environ.get("P9_HOLD_TASK")
HOLD_NTH = int(os.environ.get("P9_HOLD_NTH", "1"))
HOLD_FETCH_NTH = int(os.environ.get("P9_HOLD_FETCH_NTH", "0"))
HOLD_PAPER_WRITE_NTH = int(os.environ.get("P9_HOLD_PAPER_WRITE_NTH", "0"))
HOLD_EXTRACT_NTH = int(os.environ.get("P9_HOLD_EXTRACT_NTH", "0"))
GATE_DIR = Path(os.environ["P9_GATE_DIR"]) if os.environ.get("P9_GATE_DIR") else None

_log_lock = threading.Lock()
_counts: dict[str, int] = {}


def log(**fields) -> None:
    if CALLS is None:
        return
    fields.update(pid=os.getpid(), monotonic=time.monotonic())
    line = (json.dumps(fields) + "\n").encode()
    with _log_lock:
        fd = os.open(CALLS, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)


def bump(key: str) -> int:
    with _log_lock:
        _counts[key] = _counts.get(key, 0) + 1
        return _counts[key]


class RecordingCodex(fx.ScriptedCodex):
    async def run_step(self, base, developer, message, output_schema, requested_model, reasoning_effort=None):
        si = parse_step_input(message)
        task = si["task_type"]
        log(kind="model", task=task, run_id=si["run_id"])
        if HOLD_TASK == task and bump(f"model:{task}") == HOLD_NTH:
            log(kind="held", what="model", task=task, run_id=si["run_id"])
            await asyncio.sleep(3600)
        return await super().run_step(base, developer, message, output_schema, requested_model, reasoning_effort)


async def fetch(url: str) -> FetchResult:
    log(kind="fetch", url=url)
    if HOLD_FETCH_NTH and bump("fetch") == HOLD_FETCH_NTH:
        log(kind="held", what="fetch", url=url)
        await asyncio.sleep(3600)
    return await fx.fetch(url)


def openalex(request: httpx.Request) -> httpx.Response:
    log(kind="provider", host=request.url.host, path=request.url.path)
    return fx.openalex(request)


async def xml_fetcher(url: str) -> FetchResult:
    log(kind="xml_fetch", url=url)
    return FetchResult("http_error", final_url=url, http_status=404)


def guard_network() -> None:
    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex

    def local(address) -> bool:
        if isinstance(address, (str, bytes)):  # an AF_UNIX path
            return True
        return str(address[0]) in ("localhost", "::1") or str(address[0]).startswith("127.")

    def connect(self, address):
        if not local(address):
            log(kind="network", what="connect", address=str(address))
            raise OSError("P9 driver: network refused")
        return real_connect(self, address)

    def connect_ex(self, address):
        if not local(address):
            log(kind="network", what="connect_ex", address=str(address))
            raise OSError("P9 driver: network refused")
        return real_connect_ex(self, address)

    async def refused(url, *args, **kwargs):
        log(kind="network", what="fetch_file", url=url)
        raise OSError("P9 driver: fetch_file refused")

    socket.socket.connect, socket.socket.connect_ex = connect, connect_ex
    fetch_module.fetch_file = refused


def hold_paper_write(data_dir: Path) -> None:
    """Hold the Nth PDF write into papers/ at half its bytes. Since R2b (D192) every PDF is staged by
    pdf_files.stage_bytes into a papers/*.part file and then placed by os.replace in restore_file."""
    papers = os.path.realpath(data_dir / "papers")
    real_stage_bytes = pdf_files.stage_bytes

    def stage_bytes(path, data):
        path = Path(path)
        if os.path.realpath(path.parent) == papers and path.suffix in (".pdf", ".part") and bump("paper_write") == HOLD_PAPER_WRITE_NTH:
            data = bytes(data)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            os.write(fd, data[: len(data) // 2])
            os.fsync(fd)
            os.close(fd)
            log(kind="held", what="paper_write", file=path.name, written=len(data) // 2, total=len(data))
            time.sleep(3600)
        return real_stage_bytes(path, data)

    pdf_files.stage_bytes = stage_bytes


def hold_extract() -> None:
    real_extract = pdf.extract_pdf

    def extract(path, *args, **kwargs):
        log(kind="extract", file=Path(path).name)
        if bump("extract") == HOLD_EXTRACT_NTH:
            log(kind="held", what="extract", file=Path(path).name)
            time.sleep(3600)
        return real_extract(path, *args, **kwargs)

    pdf.extract_pdf = extract


def install_gate() -> None:
    real_migrate = db.migrate

    def gate() -> int:
        if (GATE_DIR / "armed").exists():
            (GATE_DIR / "reached").write_text(str(os.getpid()))
            time.sleep(3600)
        return 0

    def migrate(conn):
        done = real_migrate(conn)
        conn.create_function("p9_gate", 0, gate)
        conn.execute("DROP TRIGGER IF EXISTS temp.p9_gate_trigger")
        conn.execute("CREATE TEMP TRIGGER p9_gate_trigger AFTER INSERT ON main.passages"
                     " WHEN (SELECT COUNT(*) FROM main.passages WHERE asset_id = NEW.asset_id) = 2 BEGIN SELECT p9_gate(); END")
        return done

    db.migrate = migrate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if args.port in REFUSED_PORTS:
        sys.exit(f"P9 driver: port {args.port} is refused")
    guard_network()
    if HOLD_PAPER_WRITE_NTH:
        hold_paper_write(args.data_dir)
    if HOLD_EXTRACT_NTH:
        hold_extract()
    if GATE_DIR is not None:
        install_gate()
    settings = Settings(data_dir=args.data_dir, port=args.port, model_concurrency=1,
                        search_query="code", fulltext_fetch="off", fulltext_adjudication="off", arxiv_source="off")
    deixis_main.create_app = functools.partial(
        create_app, adapters={"codex": RecordingCodex()},
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(openalex)), fetcher=fetch, xml_fetcher=xml_fetcher)
    sys.exit(deixis_main.serve(settings, False, ()))


if __name__ == "__main__":
    main()
