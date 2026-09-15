"""Local HTTP API. Loopback only, Host/Origin allowlist and double-submit CSRF token for mutations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import tempfile
import time
from contextlib import asynccontextmanager, nullcontext
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

import httpx
from fastapi import FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from deixis.config import Settings, load_settings
from deixis.documents import fetch as fetch_module
from deixis.documents import acquisition
from deixis.documents import pdf
from deixis.domain import skill
from deixis.domain.rules import TEST_EFFORT_BUDGETS, RevisionConflict
from deixis.models.adapter import CodexAdapter, ModelAdapter
from deixis.providers import scopus
from deixis.providers import zotero
from deixis.providers.registry import CONNECTORS, available_providers
from deixis.storage import db
from deixis.workflow import bibliography
from deixis.workflow.flow import FlowDeps, ResearchFlow
from deixis.workflow.store import NotFound, Store
from deixis.workflow.views import passage_view, research_view
from deixis.workflow.worker import Worker

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MULTIPART_OVERHEAD_BYTES = 64 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
CSRF_COOKIE = "deixis_csrf"
CSRF_HEADER = "x-deixis-csrf"
INSTITUTIONAL_ACCESS_TTL_SECONDS = 600
INSTITUTIONAL_ACCESS_RETRY_SECONDS = 30


class CreateResearch(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    source_scope: Literal["academic", "attached", "attached_and_academic"] = "academic"
    effort: Literal["quick", "standard", "detailed"] = "standard"
    model_connection: str = "codex"
    requested_model: str = Field(min_length=1, max_length=120)  # explicit: the connection never picks a model itself
    reasoning_effort: str | None = Field(default=None, min_length=1, max_length=40)
    # Runs the search plan and screening. None: the research model runs them.
    literature_model: str | None = Field(default=None, min_length=1, max_length=120)
    literature_reasoning_effort: str | None = Field(default=None, min_length=1, max_length=40)
    # 'default' follows the app-wide reviewer setting; 'custom' reviews with review_model; 'off' reviews nothing.
    review_mode: Literal["default", "custom", "off"] = "default"
    review_model: str | None = Field(default=None, min_length=1, max_length=120)
    review_reasoning_effort: str | None = Field(default=None, min_length=1, max_length=40)
    language_hint: str | None = Field(default=None, pattern=r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


MODEL_ROLES = ("answer", "literature", "reviewer")


class RoleModelSetting(BaseModel):
    """App-wide default model for one step role, set in Settings.

    Answer and literature defaults prefill the composer, and each research stores its own choice when it is created. The
    reviewer applies to every research whose reviewer setting is 'default'. No model: no default (no review, for the reviewer).
    """
    model_connection: str = "codex"
    model: str | None = Field(default=None, min_length=1, max_length=120)
    reasoning_effort: str | None = Field(default=None, min_length=1, max_length=40)


def check_offered(listed: list[dict[str, Any]] | None, connection: str, model: str, effort: str | None) -> None:
    """A model and reasoning effort must be listed by the connection; an unlisted choice is refused, never replaced."""
    if listed is None:
        return
    offered = next((m for m in listed if m["id"] == model), None)
    if offered is None:
        raise HTTPException(422, f"Model '{model}' is not offered by {connection}")
    if effort is not None and effort not in {e["id"] for e in offered.get("reasoning_efforts", [])}:
        raise HTTPException(422, f"Reasoning effort '{effort}' is not offered for {model}")


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


class ZoteroImport(BaseModel):
    source: Literal["local", "web"]
    collection_key: str = Field(pattern=r"^[A-Z0-9]{8}$")


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
        app.state.http, app.state.fetch_pdf = http, fetcher or fetch_module.fetch_pdf
        app.state.institutional_access = None
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

    @app.exception_handler(zotero.ZoteroError)
    async def zotero_failed(_: Request, exc: zotero.ZoteroError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

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
        for name in ("claude", "deepseek", "gemini", "kimi", "grok", "copilot", "glm", "muse_spark", "muse_glimmer",
                     "ollama", "qwen", "mistral"):
            models.setdefault(name, {"connection": name, "ready": False, "reason": "Adapter not implemented in this version"})
        return {
            "models": models,
            "providers": [
                {"id": p, "implemented": True, "access_mode": c.access_mode(), "supplementary": c.supplementary,
                 "note": f"Set {c.key_env} in .env to enable it." if c.access_mode() == "not_configured"
                 else "Access and quota are recorded per request; not verified in advance."}
                for p, c in CONNECTORS.items()
            ],
        }

    @app.get("/api/institutional-access")
    async def institutional_access(request: Request, refresh: bool = False) -> dict[str, Any]:
        # Scopus grants view=COMPLETE by the caller's IP range, which shows a campus network or university VPN without
        # inspecting network interfaces. Each check spends one Scopus request, so Scopus is asked again only when the
        # local route to it changed (a VPN started or stopped) or the answer expired; a failed check expires sooner.
        key = CONNECTORS["scopus"].api_key()
        if not key:
            return {"status": "not_checked", "reason": "SCOPUS_API_KEY is not configured"}
        route = await asyncio.to_thread(scopus.route_source)
        cached = request.app.state.institutional_access
        if cached and not refresh and cached[1] == route and time.monotonic() < cached[0]:
            return cached[2]
        # A fresh connection: a pooled one opened before the route changed could still answer over the old network.
        async with (nullcontext(http_client) if http_client else httpx.AsyncClient(headers={"User-Agent": fetch_module.USER_AGENT})) as client:
            entitled = await scopus.complete_view_entitled(client, key)
        result = {"status": {True: "institutional", False: "none", None: "unknown"}[entitled], "via": "scopus"}
        ttl = INSTITUTIONAL_ACCESS_TTL_SECONDS if entitled is not None else INSTITUTIONAL_ACCESS_RETRY_SECONDS
        request.app.state.institutional_access = (time.monotonic() + ttl, route, result)
        return result

    @app.get("/api/researches")
    async def list_researches(request: Request) -> list[dict[str, Any]]:
        return store_of(request).list_researches()

    @app.get("/api/trash")
    async def list_trash(request: Request) -> list[dict[str, Any]]:
        return store_of(request).list_trash()

    @app.post("/api/trash/{research_id}/restore")
    async def restore_research(research_id: str, request: Request) -> dict[str, bool]:
        store_of(request).restore_research(research_id)
        return {"restored": True}

    @app.delete("/api/trash/{research_id}")
    async def purge_research(research_id: str, request: Request) -> dict[str, Any]:
        files, payloads = store_of(request).purge_research(research_id)
        failures = []
        for root, paths in ((settings.papers_dir, files), (settings.payloads_dir, payloads)):
            safe_root = root.resolve()
            for relative in paths:
                path = (safe_root / relative).resolve()
                if not path.is_relative_to(safe_root) or path == safe_root:
                    failures.append(relative)
                    continue
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    failures.append(relative)
        return {"deleted": True, "files_not_removed": failures}

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
        check_offered(listed, body.model_connection, body.requested_model, body.reasoning_effort)
        if body.literature_model is not None:
            check_offered(listed, body.model_connection, body.literature_model, body.literature_reasoning_effort)
        elif body.literature_reasoning_effort is not None:
            raise HTTPException(422, "A literature reasoning effort needs a literature model")
        if body.review_mode == "custom":
            if body.review_model is None:
                raise HTTPException(422, "A custom reviewer needs a review model")
            check_offered(listed, body.model_connection, body.review_model, body.review_reasoning_effort)
        elif body.review_model is not None or body.review_reasoning_effort is not None:
            raise HTTPException(422, f"A review model is only kept with review_mode 'custom', not '{body.review_mode}'")
        # Every connector with the access it needs is enabled; the model picks which of them to query.
        providers = available_providers() if body.source_scope != "attached" else []
        store = store_of(request)
        rid = store.create_research(body.question, body.source_scope, body.effort, providers,
                                    body.model_connection, body.requested_model, body.language_hint, body.reasoning_effort,
                                    body.literature_model, body.literature_reasoning_effort,
                                    body.review_mode, body.review_model, body.review_reasoning_effort)
        return research_view(store, rid)

    @app.get("/api/settings")
    async def get_settings(request: Request) -> dict[str, Any]:
        store = store_of(request)
        return {role: store.setting(role) or RoleModelSetting().model_dump() for role in MODEL_ROLES}

    @app.put("/api/settings/{role}")
    async def put_model_default(role: Literal["answer", "literature", "reviewer"], body: RoleModelSetting, request: Request) -> dict[str, Any]:
        if body.model is None:
            if body.reasoning_effort is not None:
                raise HTTPException(422, "A reasoning effort needs a model")
        else:
            adapter = request.app.state.adapters.get(body.model_connection)
            if adapter is None:
                raise HTTPException(422, f"Model connection '{body.model_connection}' is not available")
            check_offered((await adapter.health()).get("models"), body.model_connection, body.model, body.reasoning_effort)
        store_of(request).set_setting(role, body.model_dump())
        return {role: body.model_dump()}

    @app.get("/api/researches/{research_id}")
    async def get_research(research_id: str, request: Request) -> dict[str, Any]:
        return research_view(store_of(request), research_id)

    @app.delete("/api/researches/{research_id}")
    async def trash_research(research_id: str, request: Request) -> dict[str, bool]:
        store_of(request).trash_research(research_id)
        return {"trashed": True}

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
        store.research(run["research_id"])
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
        store.research(research_id)
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
            " WHERE a.sha256 = ? AND a.removed_at IS NULL AND s.origin = 'user_upload' LIMIT 1", (sha,)
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

    @app.post("/api/researches/{research_id}/sources/{source_version_id}/uploads", status_code=201)
    async def upload_to_source(research_id: str, source_version_id: str, request: Request,
                               file: UploadFile = File(...)) -> dict[str, Any]:
        """Attach a user-selected PDF to an existing bibliographic source version."""
        store = store_of(request)
        store.research(research_id)
        if not store.is_member(research_id, source_version_id):
            raise HTTPException(404, "Source is not part of this research")
        settings.papers_dir.mkdir(parents=True, exist_ok=True)
        sha, size, path = await store_upload(file, settings.papers_dir)
        if not store.conn.execute(
            "SELECT 1 FROM source_assets WHERE source_version_id = ? AND sha256 = ? AND removed_at IS NULL",
            (source_version_id, sha)
        ).fetchone():
            extraction = await asyncio.to_thread(pdf.extract_pdf, path)
            filename = Path(file.filename or "document.pdf").name
            store.add_asset_with_pages(source_version_id, sha, size, path.name, "user_upload", None, filename,
                                       extraction, pdf.EXTRACTION_VERSION, pdf.chunk_page)
        return research_view(store, research_id)

    @app.post("/api/researches/{research_id}/sources/{source_version_id}/pdf-discovery")
    async def discover_source_pdf(research_id: str, source_version_id: str, request: Request) -> dict[str, Any]:
        """Collect OpenAlex and Crossref locations, use explicit web search only if both list no PDF, then retrieve verified versions."""
        store = store_of(request)
        store.research(research_id)
        if not store.is_member(research_id, source_version_id):
            raise HTTPException(404, "Source is not part of this research")
        source = store.source(source_version_id)
        if not source.get("doi"):
            raise HTTPException(422, "A DOI is required for verified PDF acquisition")
        try:
            await acquisition.acquire_for_source(
                store, research_id, source_version_id, request.app.state.http, settings.papers_dir,
                settings.contact_email, os.environ.get("SERPAPI_API_KEY"), request.app.state.fetch_pdf,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return research_view(store, research_id)

    @app.get("/api/zotero/collections")
    async def zotero_collections(request: Request, source: Literal["local", "web"] = "local") -> dict[str, Any]:
        return {"source": source, "collections": await zotero.collections(request.app.state.http, zotero.library(source))}

    @app.post("/api/researches/{research_id}/zotero-imports", status_code=201)
    async def zotero_import(research_id: str, body: ZoteroImport, request: Request) -> dict[str, Any]:
        """Add one collection's items as sources the user included, with the text of each item's first readable PDF."""
        store = store_of(request)
        if store.scope(research_id)["source_scope"] == "academic":
            raise HTTPException(422, "Attached files are not part of this research's source scope")
        library, http = zotero.library(body.source), request.app.state.http
        items, rows = await zotero.collection_items(http, library, body.collection_key)
        settings.payloads_dir.mkdir(parents=True, exist_ok=True)
        payload_path = f"{db.new_id('zot')}.json"
        (settings.payloads_dir / payload_path).write_text(json.dumps(rows), encoding="utf-8")
        pdfs_added, notes = 0, []
        for item in items:
            with db.transaction(store.conn):
                svid, _ = store.upsert_provider_source("zotero", item.record, payload_path)
                store.add_to_corpus(research_id, svid, "zotero_import", selection_state="included", selection_origin="user")
            if item.pdf_problem:
                notes.append({"title": item.record.title, "note": item.pdf_problem})
            if item.pdf_key is None or store.has_asset(svid):
                continue
            try:
                data = await zotero.pdf_bytes(http, library, item.pdf_key, request.app.state.fetch_pdf)
            except zotero.ZoteroError as exc:
                notes.append({"title": item.record.title, "note": f"PDF not added: {exc}"})
                continue
            sha = hashlib.sha256(data).hexdigest()
            settings.papers_dir.mkdir(parents=True, exist_ok=True)
            path = settings.papers_dir / f"{sha}.pdf"
            if not path.exists():
                path.write_bytes(data)
            extraction = await asyncio.to_thread(pdf.extract_pdf, path)
            # The file is the user's own copy from their library, like an upload; retrieved_from names the attachment.
            store.add_asset_with_pages(svid, sha, len(data), path.name, "user_upload", f"zotero:{library.source}:{item.pdf_key}",
                                       item.pdf_filename, extraction, pdf.EXTRACTION_VERSION, pdf.chunk_page)
            pdfs_added += 1
        return {**research_view(store, research_id), "zotero_import": {"items": len(items), "pdfs_added": pdfs_added, "notes": notes}}

    @app.get("/api/researches/{research_id}/bibliography")
    async def export_bibliography(research_id: str, request: Request,
                                  fmt: Literal["bibtex", "ris"] = Query("bibtex", alias="format"),
                                  sources: Literal["included", "cited"] = "included") -> Response:
        store = store_of(request)
        store.research(research_id)
        chosen = bibliography.export_sources(store, research_id, sources)
        if not chosen:
            raise HTTPException(422, "No source is included" if sources == "included" else "The latest answer cites no source")
        text = bibliography.to_bibtex(chosen) if fmt == "bibtex" else bibliography.to_ris(chosen)
        name = bibliography.filename(store.research(research_id)["title"], sources, fmt)
        return Response(text, media_type=bibliography.MEDIA_TYPES[fmt], headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/researches/{research_id}/passages/{passage_id}")
    async def get_passage(research_id: str, passage_id: str, request: Request) -> dict[str, Any]:
        store = store_of(request)
        store.research(research_id)
        view = passage_view(store, research_id, passage_id)
        if view is None:
            raise HTTPException(404, "Passage is not part of this research")
        return view

    @app.get("/api/researches/{research_id}/assets/{asset_id}")
    async def get_asset(research_id: str, asset_id: str, request: Request) -> FileResponse:
        store = store_of(request)
        store.research(research_id)
        asset = store.asset(asset_id)
        if asset["removed_at"] is not None or not store.is_member(research_id, asset["source_version_id"]):
            raise HTTPException(404, "Asset is not part of this research")
        root = settings.papers_dir.resolve()
        path = (root / asset["storage_path"]).resolve()
        if not path.is_relative_to(root) or not path.exists():
            raise HTTPException(404, "File missing")
        return FileResponse(path, media_type="application/pdf", headers={"Content-Disposition": "inline"})

    @app.delete("/api/researches/{research_id}/sources/{source_version_id}/assets/{asset_id}")
    async def remove_asset(research_id: str, source_version_id: str, asset_id: str, request: Request) -> dict[str, Any]:
        """Withdraw a mistaken PDF from future answers while retaining its audit record."""
        store = store_of(request)
        store.research(research_id)
        if not store.is_member(research_id, source_version_id):
            raise HTTPException(404, "Source is not part of this research")
        asset = store.asset(asset_id)
        if asset["source_version_id"] != source_version_id or asset["removed_at"] is not None:
            raise HTTPException(404, "Asset is not attached to this source")
        store.remove_asset(research_id, source_version_id, asset_id)
        return research_view(store, research_id)

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
