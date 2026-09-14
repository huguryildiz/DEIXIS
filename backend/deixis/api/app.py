"""Local HTTP API. Loopback only, Host/Origin allowlist and double-submit CSRF token for mutations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

import httpx
from fastapi import FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from deixis.config import Settings, load_settings
from deixis.documents import fetch as fetch_module
from deixis.documents import pdf
from deixis.domain import skill
from deixis.domain.rules import TEST_EFFORT_BUDGETS, RevisionConflict
from deixis.models.adapter import CodexAdapter, ModelAdapter
from deixis.providers import openalex
from deixis.storage import db
from deixis.workflow.flow import FlowDeps, ResearchFlow
from deixis.workflow.store import NotFound, Store
from deixis.workflow.views import passage_view, research_view
from deixis.workflow.worker import Worker

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MULTIPART_OVERHEAD_BYTES = 64 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
CSRF_COOKIE = "deixis_csrf"
CSRF_HEADER = "x-deixis-csrf"
IMPLEMENTED_PROVIDERS = {"openalex"}
ALL_PROVIDERS = ["semantic_scholar", "crossref", "arxiv", "openalex", "scopus", "ieee_xplore", "serpapi"]


class CreateResearch(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    source_scope: Literal["academic", "attached", "attached_and_academic"] = "academic"
    effort: Literal["quick", "standard", "detailed"] = "standard"
    model_connection: str = "codex"
    requested_model: str = Field(min_length=1, max_length=120)  # explicit: the connection never picks a model itself
    language_hint: str | None = Field(default=None, pattern=r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


class StartRun(BaseModel):
    kind: Literal["discovery", "answer"]


class SelectionChange(BaseModel):
    state: Literal["included", "excluded", "pending"]
    expected_version: int
    reason: str | None = Field(default=None, max_length=1000)


class ScopeRevision(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    steering: str | None = Field(default=None, max_length=2000)
    expected_version: int


async def store_upload(file: UploadFile, papers_dir: Path) -> tuple[str, int, Path]:
    """Copy an upload into the papers folder in chunks while hashing, without holding the whole file in memory."""
    digest, size, head = hashlib.sha256(), 0, b""
    fd, partial = tempfile.mkstemp(dir=papers_dir, suffix=".partial")
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := await file.read(UPLOAD_CHUNK_BYTES):
                head = head or chunk[:5]
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "PDF larger than 50 MB")
                digest.update(chunk)
                out.write(chunk)
        if head != b"%PDF-":
            raise HTTPException(422, "Only PDF files are supported")
        path = papers_dir / f"{digest.hexdigest()}.pdf"
        if path.exists():
            os.unlink(partial)
        else:
            os.replace(partial, path)
        return digest.hexdigest(), size, path
    except BaseException:
        Path(partial).unlink(missing_ok=True)
        raise


def create_app(
    settings: Settings | None = None,
    adapters: dict[str, ModelAdapter] | None = None,
    http_client: httpx.AsyncClient | None = None,
    fetcher: Callable[[str], Awaitable[fetch_module.FetchResult]] | None = None,
    start_worker: bool = True,
    extra_hosts: tuple[str, ...] = (),
    trusted_clients: tuple[str, ...] = (),
) -> FastAPI:
    settings = settings or load_settings()
    ports = {settings.port}
    allowed_hosts = {f"{h}:{p}" for h in ("127.0.0.1", "localhost") for p in ports} | set(extra_hosts)
    allowed_origins = {f"http://{h}" for h in allowed_hosts}
    local_clients = {"127.0.0.1", "::1", *trusted_clients}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if issues := skill.integrity_issues():
            raise RuntimeError(f"method package integrity failed: {issues}")
        conn = db.connect(settings.db_path)
        db.migrate(conn)
        store = Store(conn)
        http = http_client or httpx.AsyncClient(headers={"User-Agent": fetch_module.USER_AGENT})
        adapter_map = adapters if adapters is not None else {
            "codex": CodexAdapter(codex_home=settings.codex_home, workspace=settings.data_dir / "codex-workspace")
        }
        package = skill.load_skill_package()
        flow = ResearchFlow(FlowDeps(settings, store, adapter_map, package, http, fetcher or fetch_module.fetch_pdf))
        worker = Worker(store, flow, settings.lock_path)
        owner = start_worker and worker.acquire()
        app.state.store, app.state.worker, app.state.adapters = store, worker, adapter_map
        app.state.package, app.state.owner = package, owner
        app.state.recovered = worker.recover() if owner else None

        async def take_over_when_released() -> None:
            # A previous instance may still be shutting down and holding the lock; own the worker once it is released.
            while not worker.acquire():
                await asyncio.sleep(1.0)
            app.state.recovered = worker.recover()
            app.state.owner = True
            await worker.run_forever()

        task = asyncio.create_task(worker.run_forever() if owner else take_over_when_released()) if start_worker else None
        try:
            yield
        finally:
            if task:
                await worker.stop()
                if not app.state.owner:
                    task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            worker.release()
            if http_client is None:
                await http.aclose()
            for adapter in adapter_map.values():
                await adapter.close()
            conn.close()

    app = FastAPI(title="DEIXIS local API", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def local_guard(request: Request, call_next):
        # Loopback is enforced per request, not only by the launcher's bind address.
        if (request.client.host if request.client else "") not in local_clients:
            return JSONResponse({"detail": "Only local connections are accepted"}, status_code=403)
        if request.headers.get("host", "") not in allowed_hosts:
            return JSONResponse({"detail": "Host not allowed"}, status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin not in allowed_origins:
                return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
            cookie = request.cookies.get(CSRF_COOKIE, "")
            if not cookie or not secrets.compare_digest(cookie, request.headers.get(CSRF_HEADER, "")):
                return JSONResponse({"detail": "Missing or invalid CSRF token"}, status_code=403)
            if request.url.path.endswith("/uploads"):
                # Checked before the multipart body is read and spooled to disk.
                length = request.headers.get("content-length", "")
                if not length.isdigit():
                    return JSONResponse({"detail": "Upload size must be declared"}, status_code=411)
                if int(length) > MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES:
                    return JSONResponse({"detail": "PDF larger than 50 MB"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def store_of(request: Request) -> Store:
        return request.app.state.store

    @app.exception_handler(NotFound)
    async def not_found(_: Request, exc: NotFound):
        return JSONResponse({"detail": f"Not found: {exc}"}, status_code=404)

    @app.exception_handler(RevisionConflict)
    async def conflict(_: Request, exc: RevisionConflict):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.get("/api/health")
    async def health(request: Request) -> dict[str, Any]:
        return {"status": "ok", "worker": "owner" if request.app.state.owner else "not_owner",
                "recovered": request.app.state.recovered, "skill_package_hash": request.app.state.package.package_hash}

    @app.get("/api/session")
    async def session() -> JSONResponse:
        token = secrets.token_urlsafe(32)
        response = JSONResponse({"csrf_token": token})
        response.set_cookie(CSRF_COOKIE, token, httponly=True, samesite="strict", secure=False)
        return response

    @app.get("/api/connections")
    async def connections(request: Request, refresh: bool = False) -> dict[str, Any]:
        models = {}
        for name, adapter in request.app.state.adapters.items():
            models[name] = await adapter.health(refresh=refresh)
        for name in ("claude", "deepseek"):
            models.setdefault(name, {"connection": name, "ready": False, "reason": "Adapter not implemented in this version"})
        return {
            "models": models,
            "providers": [
                {"id": p, "implemented": p in IMPLEMENTED_PROVIDERS,
                 "access_mode": ("api_key" if settings.openalex_api_key else "keyless") if p == "openalex" else None,
                 "note": "Access and quota are recorded per request; not verified in advance." if p == "openalex" else "Not implemented in this version"}
                for p in ALL_PROVIDERS
            ],
        }

    @app.get("/api/researches")
    async def list_researches(request: Request) -> list[dict[str, Any]]:
        return store_of(request).list_researches()

    @app.get("/api/search")
    async def quick_search(request: Request, q: str = Query(max_length=200)) -> dict[str, Any]:
        if not q.strip():
            return {"researches": [], "sources": []}
        return store_of(request).quick_search(q.strip())

    @app.post("/api/researches", status_code=201)
    async def create_research(body: CreateResearch, request: Request) -> dict[str, Any]:
        adapter = request.app.state.adapters.get(body.model_connection)
        if adapter is None:
            raise HTTPException(422, f"Model connection '{body.model_connection}' is not available")
        listed = (await adapter.health()).get("models")
        if listed is not None and body.requested_model not in {m["id"] for m in listed}:
            raise HTTPException(422, f"Model '{body.requested_model}' is not offered by {body.model_connection}")
        providers = ["openalex"] if body.source_scope != "attached" else []
        store = store_of(request)
        rid = store.create_research(body.question, body.source_scope, body.effort, providers,
                                    body.model_connection, body.requested_model, body.language_hint)
        return research_view(store, rid)

    @app.get("/api/researches/{research_id}")
    async def get_research(research_id: str, request: Request) -> dict[str, Any]:
        return research_view(store_of(request), research_id)

    @app.post("/api/researches/{research_id}/scope")
    async def revise_scope(research_id: str, body: ScopeRevision, request: Request) -> dict[str, Any]:
        store = store_of(request)
        store.revise_scope(research_id, body.expected_version, body.question, body.steering)
        return research_view(store, research_id)

    @app.post("/api/researches/{research_id}/runs", status_code=202)
    async def start_run(research_id: str, body: StartRun, request: Request,
                        idempotency_key: str | None = Header(default=None, max_length=200)) -> dict[str, Any]:
        store = store_of(request)
        scope = store.scope(research_id)
        if body.kind == "discovery" and scope["source_scope"] == "attached":
            raise HTTPException(422, "Academic search is not part of this research's source scope")
        if body.kind == "answer" and not store.included_sources(research_id):
            raise HTTPException(422, "Include at least one source before generating an answer")
        budget = TEST_EFFORT_BUDGETS[scope["effort"]].__dict__
        key = f"{research_id}:{idempotency_key}" if idempotency_key else None
        run = store.create_run(research_id, body.kind, budget, key)
        request.app.state.worker.wake()
        return run

    @app.post("/api/runs/{run_id}/{action}")
    async def control_run(run_id: str, action: Literal["pause", "resume", "cancel"], request: Request) -> dict[str, Any]:
        store = store_of(request)
        run = store.run(run_id)
        status = run["status"]
        worker = request.app.state.worker
        if action == "pause" and status in ("queued", "running"):
            new = "paused" if status == "queued" else "pause_requested"
            run = store.update_run(run_id, event="run_pause_requested", status=new, pause_reason="user_requested")
        elif action == "resume" and status == "paused":
            run = store.update_run(run_id, event="run_resumed", status="queued", pause_reason=None, error_json=None)
            worker.wake()
        elif action == "cancel" and status in ("queued", "running", "pause_requested", "paused"):
            run = store.update_run(run_id, event="run_cancelled", status="cancelled", pause_reason="user_cancelled")
            if worker.current_run_id == run_id:
                scope = store.scope(run["research_id"], run["scope_revision"])
                adapter = request.app.state.adapters.get(scope["model_connection"])
                if adapter:
                    await adapter.cancel()
        else:
            raise HTTPException(409, f"Cannot {action} a run in status {status}")
        return run

    @app.patch("/api/researches/{research_id}/selections/{source_version_id}")
    async def change_selection(research_id: str, source_version_id: str, body: SelectionChange, request: Request) -> dict[str, Any]:
        store = store_of(request)
        return store.set_user_selection(research_id, source_version_id, body.state, body.expected_version, body.reason)

    @app.post("/api/researches/{research_id}/uploads", status_code=201)
    async def upload(research_id: str, request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
        store = store_of(request)
        if store.scope(research_id)["source_scope"] == "academic":
            raise HTTPException(422, "Attached files are not part of this research's source scope")
        settings.papers_dir.mkdir(parents=True, exist_ok=True)
        sha, size, path = await store_upload(file, settings.papers_dir)
        existing = store.conn.execute(
            "SELECT a.source_version_id FROM source_assets a JOIN source_versions s ON s.id = a.source_version_id"
            " WHERE a.sha256 = ? AND s.origin = 'user_upload' LIMIT 1", (sha,)
        ).fetchone()
        filename = Path(file.filename or "document.pdf").name
        if existing:
            svid = existing["source_version_id"]
        else:
            extraction = await asyncio.to_thread(pdf.extract_pdf, path)
            title = re.sub(r"[_\s]+", " ", Path(filename).stem).strip()[:200] or "Uploaded PDF"
            svid = store.create_upload_source(title)
            store.add_asset_with_pages(svid, sha, size, path.name, "user_upload", None, filename,
                                       extraction, pdf.EXTRACTION_VERSION, pdf.chunk_page)
        store.add_to_corpus(research_id, svid, "user_upload", selection_state="included", selection_origin="user")
        return research_view(store, research_id)

    @app.get("/api/researches/{research_id}/passages/{passage_id}")
    async def get_passage(research_id: str, passage_id: str, request: Request) -> dict[str, Any]:
        view = passage_view(store_of(request), research_id, passage_id)
        if view is None:
            raise HTTPException(404, "Passage is not part of this research")
        return view

    @app.get("/api/researches/{research_id}/assets/{asset_id}")
    async def get_asset(research_id: str, asset_id: str, request: Request) -> FileResponse:
        store = store_of(request)
        asset = store.asset(asset_id)
        if not store.is_member(research_id, asset["source_version_id"]):
            raise HTTPException(404, "Asset is not part of this research")
        root = settings.papers_dir.resolve()
        path = (root / asset["storage_path"]).resolve()
        if not path.is_relative_to(root) or not path.exists():
            raise HTTPException(404, "File missing")
        return FileResponse(path, media_type="application/pdf", headers={"Content-Disposition": "inline"})

    @app.get("/api/researches/{research_id}/events")
    async def events(research_id: str, request: Request, after: int = 0) -> list[dict[str, Any]]:
        store = store_of(request)
        store.research(research_id)
        return store.events_after(research_id, after)

    @app.get("/api/researches/{research_id}/events/stream")
    async def event_stream(research_id: str, request: Request, after: int = 0,
                           last_event_id: str | None = Header(default=None)) -> StreamingResponse:
        store = store_of(request)
        store.research(research_id)
        start = int(last_event_id) if last_event_id and last_event_id.isdigit() else after

        async def generate():
            cursor = start
            while not await request.is_disconnected():
                for event in store.events_after(research_id, cursor):
                    cursor = event["id"]
                    data = json.dumps({"type": event["type"], "run_id": event["run_id"], "payload": event["payload"]})
                    yield f"id: {event['id']}\ndata: {data}\n\n"
                yield ": keep-alive\n\n"
                await asyncio.sleep(0.7)

        return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})

    if settings.web_dist.exists():
        app.mount("/", StaticFiles(directory=settings.web_dist, html=True), name="web")

    return app
