"""Synthetic R2a libraries and process ownership helpers; no live library or network."""

import hashlib
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents import pdf
from deixis.storage import db
from deixis.workflow.store import Store
from tests.helpers import make_pdf


PUBLIC_RETRY_FIELDS = {"operation_id", "asset_id", "lifecycle", "outcome", "reason", "decision_code",
                       "input_observation_id", "input_integrity", "candidate_status", "extraction_id",
                       "extraction_version", "baseline_extraction_id", "coverage", "created_at", "finished_at"}


def seed(store, settings, status="failed", version=None, data=None):
    rid = store.create_research("SYNTHETIC retry question?", "attached", "quick", [], "fake", "fake", None)
    svid = store.create_upload_source("SYNTHETIC retry source")
    store.add_to_corpus(rid, svid, "user_upload", selection_state="included", selection_origin="user")
    data = data or make_pdf(["SYNTHETIC relays on page one.", "SYNTHETIC relays on page two.", "SYNTHETIC relays on page three."])
    sha = hashlib.sha256(data).hexdigest()
    settings.papers_dir.mkdir(parents=True, exist_ok=True)
    path = settings.papers_dir / (sha + ".pdf")
    path.write_bytes(data)
    if status in ("succeeded", "partial"):
        candidate = pdf.extract_pdf(path)
        candidate.status = status
        if status == "partial":
            candidate.pages = [p for p in candidate.pages if p.physical_page != 3]
    else:
        candidate = pdf.Extraction(status, 0, [], error=pdf.ERROR_UNREADABLE if status == "failed" else None)
    aid = store.add_asset_with_pages(svid, sha, len(data), path.name, "user_upload", None, "synthetic.pdf",
                                     candidate, version or pdf.EXTRACTION_VERSION, pdf.chunk_page)
    return SimpleNamespace(store=store, conn=store.conn, settings=settings, rid=rid, svid=svid, aid=aid,
                           data=data, sha=sha, path=path, eid=head(store, aid)["id"])


def head(store, aid):
    row = store.conn.execute("SELECT * FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'", (aid,)).fetchone()
    return dict(row) if row else None


def body(lib, key="request_0001", eid=None):
    return {"mode": "retry_failed_or_partial", "expected_current_extraction_id": eid or lib.eid, "idempotency_key": key}


def url(lib, suffix="extractions"):
    return f"/api/researches/{lib.rid}/sources/{lib.svid}/assets/{lib.aid}/{suffix}"


def counts(store):
    return {t: store.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in
            ("asset_recovery_operations", "asset_file_observations", "asset_extractions", "passages", "events")}


def protected(store):
    return {t: hashlib.sha256(repr([tuple(r) for r in store.conn.execute(f"SELECT * FROM {t} ORDER BY rowid")]).encode()).hexdigest()
            for t in ("source_assets", "asset_extractions", "passages", "evidence_links")}


def sharing(lib):
    rid = lib.store.create_research("SYNTHETIC other research?", "attached", "quick", [], "fake", "fake", None)
    lib.store.add_to_corpus(rid, lib.svid, "user_upload")
    return rid


@contextmanager
def api_library(tmp_path, status="failed", version=None, raise_errors=False):
    settings = Settings(data_dir=tmp_path / "data")
    def forbidden(request):
        raise AssertionError("Retry sent an HTTP request")
    app = create_app(settings, start_worker=False, adapters={},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(forbidden)),
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app, raise_server_exceptions=raise_errors) as client:
        token = client.get("/api/session").json()["csrf_token"]
        client.headers["x-deixis-csrf"] = token
        lib = seed(app.state.store, settings, status, version)
        lib.app, lib.client, lib.token = app, client, token
        yield lib


@contextmanager
def store_library(tmp_path, status="failed"):
    settings = Settings(data_dir=tmp_path / "data")
    conn = db.connect(settings.db_path)
    db.migrate(conn)
    store = Store(conn)
    store.recovery_dir = getattr(settings, "recovery_dir", settings.data_dir / "recovery")
    try:
        yield seed(store, settings, status)
    finally:
        conn.close()


@contextmanager
def child_lock(lib):
    code = """import sys
from pathlib import Path
from deixis.workflow.text_retry import file_lock
with file_lock(Path(sys.argv[1]), sys.argv[2]):
    print('locked', flush=True)
    sys.stdin.readline()
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "backend")
    child = subprocess.Popen([sys.executable, "-c", code, str(lib.settings.recovery_dir), lib.sha],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        assert child.stdout.readline().strip() == "locked"
        yield child
    finally:
        child.communicate("release\n", timeout=15)
        assert child.returncode == 0
