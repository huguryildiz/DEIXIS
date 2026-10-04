"""Isolated SYNTHETIC libraries and bounded real-child boundaries for R2c."""

import asyncio
import json
import os
import select
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.documents import math_reader, ocr, pdf
from deixis.workflow import equations, text_retry

ROOT = Path(__file__).resolve().parents[1]


def forbid_calls(monkeypatch, *, parser=True):
    def forbidden(*args, **kwargs):
        raise AssertionError("Reconciliation invoked parsing, OCR, mathematics, a model or HTTP")
    if parser:
        monkeypatch.setattr(pdf, "extract_pdf", forbidden)
    monkeypatch.setattr(ocr, "read_page", forbidden)
    monkeypatch.setattr(math_reader.MathReader, "read", forbidden)
    monkeypatch.setattr(equations.EquationService, "read_asset", forbidden)
    from deixis.models import codex_rpc, claude, gemini, deepseek
    for module in (codex_rpc, claude, gemini, deepseek):
        # Every adapter exposes run_step through its concrete class.
        for item in vars(module).values():
            if isinstance(item, type) and item.__module__ == module.__name__ and hasattr(item, "run_step"):
                monkeypatch.setattr(item, "run_step", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)


@contextmanager
def child(lib, mode, boundary="parser", *, parked=False):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "backend") + os.pathsep + str(ROOT),
               DEIXIS_DATA_DIR=str(lib.settings.data_dir))
    code = "from tests.reextract_r2c_helpers import child_main; child_main()"
    process = subprocess.Popen([sys.executable, "-c", code, mode, boundary, lib.aid, lib.eid, lib.rid, lib.svid],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        ready, _, _ = select.select([process.stdout], [], [], 30)
        if not ready:
            process.kill()
            out, err = process.communicate(timeout=10)
            pytest.fail(f"R2c child handshake timed out: {out} {err}")
        line = process.stdout.readline().strip()
        if line != "boundary:" + boundary:
            if process.poll() is None:
                process.kill()
            out, err = process.communicate(timeout=10)
            pytest.fail(f"R2c child failed before boundary: {line} {out} {err}")
        if not parked:
            out, err = process.communicate(timeout=30)
            assert process.returncode == 137, (out, err)
        yield process
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def release_child(process):
    out, err = process.communicate("release\n", timeout=30)
    assert process.returncode == 0, (out, err)


@contextmanager
def child_lock(lib):
    with child(lib, "park_lock", "lock", parked=True) as process:
        try:
            yield process
        finally:
            release_child(process)


def events(store, kind, oid):
    return [json.loads(row[0]) for row in store.conn.execute("SELECT payload_json FROM events WHERE type = ?", (kind,))
            if json.loads(row[0]).get("operation_id") == oid]


@contextmanager
def startup(lib):
    def forbidden(request):
        raise AssertionError("Startup invoked HTTP")
    app = create_app(lib.settings, start_worker=True, adapters={},
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(forbidden)),
        extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        yield app, client


def child_main():
    from deixis.config import load_settings
    from deixis.storage import db
    from deixis.workflow import file_restore
    from deixis.workflow.store import Store

    mode, boundary, aid, eid, rid, svid = sys.argv[1:]
    settings = load_settings()
    conn = db.connect(settings.db_path)
    store = Store(conn)
    store.recovery_dir = settings.recovery_dir
    asset = store.asset(aid)
    target = settings.papers_dir / asset["storage_path"]

    def reached():
        print("boundary:" + boundary, flush=True)
        if mode.startswith("park_"):
            sys.stdin.readline()
        else:
            os._exit(137)

    def wrap(name, predicate=lambda *a, **k: True):
        real = getattr(store, name)
        def called(*args, **kwargs):
            result = real(*args, **kwargs)
            if predicate(*args, **kwargs):
                reached()
            return result
        setattr(store, name, called)

    if mode == "park_lock":
        with text_retry.file_lock(settings.recovery_dir, asset["sha256"]):
            reached()
    elif mode.endswith("text") or mode == "cli":
        if boundary == "reservation":
            wrap("reserve_text_retry")
        elif boundary == "input":
            wrap("record_text_retry_input")
        elif boundary == "parser":
            real = pdf.extract_pdf
            def parser(path):
                reached()
                return real(path)
            pdf.extract_pdf = parser
        elif boundary == "committed":
            wrap("complete_text_retry")
        else:
            def trace(sql):
                checks = {
                    "superseded": "INSERT INTO asset_extractions",
                    "candidate": "INSERT INTO passages",
                    "passages": "UPDATE source_assets SET extraction_version",
                    "mirrors": "UPDATE asset_recovery_operations SET lifecycle = 'completed'",
                    "event": "COMMIT",
                }
                if checks[boundary] in sql and finishing[0]:
                    reached()
            finishing = [False]
            real = store.complete_text_retry
            def complete(*args, **kwargs):
                finishing[0] = True
                conn.set_trace_callback(trace)
                return real(*args, **kwargs)
            store.complete_text_retry = complete
        if mode == "cli":
            from deixis.__main__ import main
            sys.exit(main(["reextract", "--retry", aid, "--expected-extraction", eid]))
        asyncio.run(text_retry.execute_text_retry(store, settings, asset_id=aid, expected_extraction_id=eid,
            idempotency_key="crashed_request", research_id=rid, source_version_id=svid))
    else:
        if boundary == "reservation":
            wrap("reserve_file_restore")
        elif boundary in ("before", "after"):
            wrap("record_file_restore_observation", lambda oid, kind, **kwargs: kind == boundary + "_restore")
        elif boundary in ("retained", "replace", "replacement_commit"):
            replaced = [False]
            real = os.replace
            def replace(source, dest):
                result = real(source, dest)
                if boundary == "retained" and Path(dest).name.startswith("retained-"):
                    reached()
                elif Path(dest) == target:
                    replaced[0] = True
                    if boundary == "replace":
                        reached()
                return result
            os.replace = replace
            if boundary == "replacement_commit":
                class CommitBoundary:
                    def __getattr__(self, key): return getattr(conn, key)
                    def execute(self, sql, *args):
                        result = conn.execute(sql, *args)
                        if sql == "COMMIT" and replaced[0]:
                            reached()
                        return result
                store.conn = CommitBoundary()
        elif boundary == "retention_copy":
            from deixis.documents import pdf_files
            real = pdf_files.inspect_file
            def inspect(path, copy_path=None, **kwargs):
                if copy_path is not None:
                    reached()
                return real(path, copy_path, **kwargs)
            pdf_files.inspect_file = inspect
        data = (settings.data_dir / "synthetic-full.pdf").read_bytes()
        asyncio.run(file_restore.store_pdf_file(store, settings.papers_dir, settings.recovery_dir,
            data, caller="upload", research_id=rid))
    conn.close()
