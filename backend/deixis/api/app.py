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
from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from keyring.errors import KeyringError
from pydantic import BaseModel, Field

from deixis import credentials, local_tools
from deixis.config import Settings, load_settings
from deixis.documents import fetch as fetch_module
from deixis.documents import acquisition
from deixis.documents import embeddings
from deixis.documents import figures
from deixis.documents.identity import MATCH_TEXT_CHARS, match_pdf_to_source
from deixis.documents import math_reader
from deixis.documents import ocr
from deixis.documents import pdf
from deixis.domain import proxy, skill
from deixis.workflow import abstract_stage
from deixis.domain.rules import (ABSTRACT_BATCH, ABSTRACT_READ_LIMIT, ABSTRACT_RUNS, CHAIN_ABSTRACT_READ, CHAIN_PLAN_ROOM,
                                 CHAIN_REQUEST_LIMIT, CRITERION_CALLS, SEARCH_QUERY_CALLS,
                                 SUGGESTION_CALLS, TEST_EFFORT_BUDGETS, RevisionConflict)
from deixis.models.adapter import CodexAdapter, ModelAdapter
from deixis.models.claude import ClaudeCodeAdapter
from deixis.models.deepseek import DeepSeekAdapter
from deixis.models.gemini import GeminiAdapter
from deixis.providers import scopus
from deixis.providers import zotero
from deixis.providers.registry import CONNECTORS, configured_providers, provider_role
from deixis.storage import db
from deixis.workflow import approval as approval_rules
from deixis.workflow import adjudication, fulltext
from deixis.workflow import suggestions as suggestion_rules
from deixis.workflow import bibliography
from deixis.workflow import queue as human_queue
from deixis.workflow import waiting as pdf_waiting
from deixis.workflow.concurrency import ModelCallLimiter
from deixis.workflow.equations import EquationService, equation_state, equations_to_check
from deixis.workflow.flow import FlowDeps, ResearchFlow
from deixis.workflow.report.store import ReportStore
from deixis.workflow.store import NotASource, NotFound, PdfInUse, RunInProgress, SameFile, SeedUnavailable, Store
from deixis.workflow.tables import CELL_STATES, InvalidTableInput, TableStore
from deixis.workflow.views import library_version_to_add, library_view, library_work_view, passage_view, report_view, research_view
from deixis.workflow.worker import Worker

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MULTIPART_OVERHEAD_BYTES = 64 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
CSRF_COOKIE = "deixis_csrf"
CSRF_HEADER = "x-deixis-csrf"
# The pauses an approval answers: the proposal itself, and a correction that left nothing searchable (slice 08a).
APPROVABLE_PAUSES = ("protocol_approval_needed", "vocabulary_empty", "vocabulary_too_broad")
INSTITUTIONAL_ACCESS_TTL_SECONDS = 600
INSTITUTIONAL_ACCESS_RETRY_SECONDS = 30


class CreateResearch(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    source_scope: Literal["academic", "attached", "attached_and_academic"] = "academic"
    seed_mode: Literal["question_only", "uploaded_seed"] = "question_only"
    effort: Literal["quick", "standard", "detailed"] = "standard"
    model_connection: str = "codex"
    requested_model: str = Field(min_length=1, max_length=120)  # explicit: the connection never picks a model itself
    reasoning_effort: str | None = Field(default=None, min_length=1, max_length=40)
    # Runs the search plan and screening. None: the research model runs them.
    literature_model: str | None = Field(default=None, min_length=1, max_length=120)
    literature_reasoning_effort: str | None = Field(default=None, min_length=1, max_length=40)
    # The connection that lists literature_model (D28). None: model_connection.
    literature_connection: str | None = Field(default=None, min_length=1, max_length=40)
    # 'default' follows the app-wide reviewer setting; 'custom' reviews with review_model; 'off' reviews nothing.
    review_mode: Literal["default", "custom", "off"] = "default"
    review_model: str | None = Field(default=None, min_length=1, max_length=120)
    review_connection: str | None = Field(default=None, min_length=1, max_length=40)  # None: model_connection
    review_reasoning_effort: str | None = Field(default=None, min_length=1, max_length=40)
    language_hint: str | None = Field(default=None, pattern=r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
    # The user's own English search terms, used by the sw workflow when code cannot read the question (SW2.1).
    key_terms: str | None = Field(default=None, max_length=500)


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


class KeyValue(BaseModel):
    value: str = Field(min_length=8, max_length=400, pattern=r"^\S+$")


class ProxyAddress(BaseModel):
    address: str | None = Field(default=None, max_length=4000)


class SemanticChoice(BaseModel):
    provider: Literal["gemini", "openai", "ollama", "lm_studio", "off"]
    model: str | None = Field(default=None, min_length=1, max_length=200)


class StartRun(BaseModel):
    kind: Literal["discovery", "answer", "pdf_collection", "research_title", "fulltext_fetch", "fulltext_adjudication"]


class SelectionChange(BaseModel):
    state: Literal["included", "excluded", "pending"]
    expected_version: int
    reason: str | None = Field(default=None, max_length=1000)


class QueueDecision(BaseModel):
    decision: Literal["include", "criterion_not_met", "not_sure", "pdf_wrong", "pdf_confirmed"]
    note: str | None = Field(default=None, max_length=1000)
    row_token: str = Field(max_length=200)


class QueueUndo(BaseModel):
    row_token: str = Field(max_length=200)


class ScopeRevision(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    steering: str | None = Field(default=None, max_length=2000)
    expected_version: int
    key_terms: str | None = Field(default=None, max_length=500)  # left out, the revision keeps the previous terms


class ProtocolApprovalSubmission(BaseModel):
    """The user's answer to the approval step; an empty body approves the proposal as it stands (slice 08a).

    The fields are loose on purpose: `approval.check_edits` reads them and names every fault at once, so the user
    is told what is wrong with the whole correction instead of the first line of it.
    """

    terms: list[dict[str, Any]] = Field(default_factory=list)
    criterion: dict[str, Any] | None = None
    note: str | None = None
    # Whether the code's own query is searched beside a model-written one (D92); null leaves the proposal's choice.
    code_query: Any = None


class ResearchTitleChange(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    expected_version: int


class SeedSelection(BaseModel):
    source_version_id: str = Field(pattern=r"^srv_[0-9A-Za-z]{8,40}$")
    expected_version: int


class LibraryAddition(BaseModel):
    work_id: str = Field(min_length=1, max_length=200)


class SourceRemoval(BaseModel):
    source_version_ids: list[str] = Field(min_length=1, max_length=500)
    note: str | None = Field(default=None, max_length=500)


class SourceRestore(BaseModel):
    source_version_ids: list[str] = Field(min_length=1, max_length=500)


class ZoteroSourceChoice(BaseModel):
    source: Literal["local", "web"]


class ZoteroImport(BaseModel):
    source: Literal["local", "web"]
    collection_key: str = Field(pattern=r"^[A-Z0-9]{8}$")


AnswerFormat = Literal["choice", "number_unit", "yes_no", "text"]


class CreateTable(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    template_id: str | None = Field(default=None, max_length=40)
    rows: list[str] | None = Field(default=None, max_length=500)  # None: the research's included sources


class StartReport(BaseModel):
    table_id: str


class TableTitle(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    expected_version: int


class TableRows(BaseModel):
    source_version_ids: list[str] = Field(min_length=1, max_length=500)
    expected_version: int


class ColumnOption(BaseModel):
    id: str | None = Field(default=None, pattern=r"^o[0-9]{1,3}$")  # None: a new option
    label: str = Field(min_length=1, max_length=120)


class ColumnCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    instruction: str = Field(min_length=1, max_length=2000)
    answer_format: AnswerFormat
    options: list[ColumnOption] | None = Field(default=None, max_length=20)
    allow_multiple: bool = False
    unit_hint: str | None = Field(default=None, max_length=40)
    suggestion_step_id: str | None = Field(default=None, max_length=40)  # set when the user adds a suggested column
    expected_version: int  # of the table


class FillRequest(BaseModel):
    column_ids: list[str] | None = Field(default=None, min_length=1, max_length=200)  # None: every active column
    include_stale: bool = False  # also ask again for values made under an earlier column revision; they come back as proposals
    expected_version: int  # of the table whose fill estimate the user saw


class ColumnChange(BaseModel):
    """Only the fields a request sets change; a changed definition becomes a new column revision."""
    name: str | None = Field(default=None, min_length=1, max_length=80)
    instruction: str | None = Field(default=None, min_length=1, max_length=2000)
    answer_format: AnswerFormat | None = None
    options: list[ColumnOption] | None = Field(default=None, max_length=20)
    allow_multiple: bool | None = None
    unit_hint: str | None = Field(default=None, max_length=40)
    position: int | None = Field(default=None, ge=0)
    expected_version: int  # of the column


class CellEdit(BaseModel):
    state: Literal[CELL_STATES]  # type: ignore[valid-type]
    value: dict[str, Any] | None = None
    note: str | None = Field(default=None, max_length=2000)
    keep_evidence_from: str | None = Field(default=None, max_length=40)  # a revision of this cell whose evidence the value keeps
    expected_version: int  # of the cell; 0 for a cell without revisions


class ExpectedVersion(BaseModel):
    expected_version: int


class TemplateApply(BaseModel):
    template_id: str = Field(max_length=40)
    expected_version: int


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    research_id: str = Field(max_length=40)
    table_id: str = Field(max_length=40)


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
    equation_service: Any = None,
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
        store.link_published_versions()  # preprints flagged beside their published record before D48
        store.assign_source_keys()  # works stored before D59
        http = http_client or httpx.AsyncClient(headers={"User-Agent": fetch_module.USER_AGENT})
        adapter_map = adapters if adapters is not None else {
            "codex": CodexAdapter(codex_home=settings.codex_home, workspace=settings.data_dir / "codex-workspace"),
            "claude": ClaudeCodeAdapter(workspace=settings.data_dir / "claude-workspace"),
            "gemini": GeminiAdapter(client=http),
            "deepseek": DeepSeekAdapter(client=http),
        }
        package = skill.load_skill_package()
        equations = equation_service if equation_service is not None else EquationService(
            store, math_reader.MathReader(math_reader.runtime_paths(settings.data_dir)), settings.papers_dir)
        flow = ResearchFlow(FlowDeps(settings, store, adapter_map, package, http, fetcher or fetch_module.fetch_pdf, equations,
                                     limiter=ModelCallLimiter(settings.model_concurrency)))
        worker = Worker(store, flow, settings.lock_path)
        owner = start_worker and worker.acquire()
        app.state.equations = equations
        if owner:
            equations.start()  # reads stored PDFs' equations in the background when the reader is installed (D52)
        app.state.store, app.state.worker, app.state.adapters = store, worker, adapter_map
        app.state.package, app.state.owner = package, owner
        app.state.http, app.state.fetch_pdf = http, fetcher or fetch_module.fetch_pdf
        app.state.institutional_access = None
        app.state.local_tools = local_tools.LocalTools(http)
        app.state.recovered = worker.recover() if owner else None

        async def take_over_when_released() -> None:
            # A previous instance may still be shutting down and holding the lock; own the worker once it is released.
            while not worker.acquire():
                await asyncio.sleep(1.0)
            app.state.recovered = worker.recover()
            app.state.owner = True
            equations.start()
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
            await equations.stop()
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

    @app.exception_handler(PdfInUse)
    async def pdf_in_use(_: Request, exc: PdfInUse):
        return JSONResponse({"detail": "This source already has a PDF in use; replace it instead"}, status_code=409)

    @app.exception_handler(RunInProgress)
    async def source_run_in_progress(_: Request, exc: RunInProgress):
        return JSONResponse({"detail": "A research using this source has a run in progress; try again when it has stopped"}, status_code=409)

    @app.exception_handler(NotASource)
    async def not_a_source(_: Request, exc: NotASource):
        return JSONResponse({"detail": f"Not a source of this research: {exc}"}, status_code=422)

    @app.exception_handler(SeedUnavailable)
    async def seed_unavailable(_: Request, exc: SeedUnavailable):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(SameFile)
    async def same_file(_: Request, exc: SameFile):
        return JSONResponse({"detail": "This file is already the PDF in use"}, status_code=422)

    @app.exception_handler(human_queue.QueueUnavailable)
    async def queue_unavailable(_: Request, exc: human_queue.QueueUnavailable):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(RevisionConflict)
    async def conflict(_: Request, exc: RevisionConflict):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    # The queue's 409 says why (slice 17): the row changed, or the reading of a confirmed PDF began. Other 409s keep
    # their one-sentence detail.
    @app.exception_handler(human_queue.QueueConflict)
    async def queue_conflict(_: Request, exc: human_queue.QueueConflict):
        return JSONResponse({"detail": {"reason": exc.reason, "message": str(exc)}}, status_code=409)

    # A confirmation of a dropped file says why it was refused (slice 18a), as the queue's 409 does.
    @app.exception_handler(pdf_waiting.AttachRefused)
    async def attach_refused(_: Request, exc: pdf_waiting.AttachRefused):
        return JSONResponse({"detail": {"reason": exc.reason, "message": str(exc)}}, status_code=409)

    @app.exception_handler(pdf_waiting.WaitingUnavailable)
    async def waiting_unavailable(_: Request, exc: pdf_waiting.WaitingUnavailable):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(proxy.ProxyRefused)
    async def proxy_refused(_: Request, exc: proxy.ProxyRefused):
        return JSONResponse({"detail": str(exc)}, status_code=422)

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
        for name in ("kimi", "grok", "copilot", "glm", "muse_spark", "muse_glimmer",
                     "ollama", "qwen", "mistral"):
            models.setdefault(name, {"connection": name, "ready": False, "reason": "Adapter not implemented in this version"})
        return {
            "models": models,
            "providers": [
                {"id": p, "implemented": True, "access_mode": c.access_mode(), "supplementary": c.supplementary,
                 "key_env": c.key_env, "role": provider_role(c),
                 "note": f"Add the key in Settings or set {c.key_env} in .env to enable it." if c.access_mode() == "not_configured"
                 else "Access and quota are recorded per request; not verified in advance."}
                for p, c in CONNECTORS.items()
            ],
        }

    @app.get("/api/connections/{connection}")
    async def model_connection(connection: str, request: Request, refresh: bool = False) -> dict[str, Any]:
        adapter = request.app.state.adapters.get(connection)
        if adapter is None:
            raise HTTPException(404, f"Model connection '{connection}' is not available")
        return await adapter.health(refresh=refresh)

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

    @app.get("/api/library")
    async def library(request: Request) -> dict[str, Any]:
        return library_view(store_of(request))

    @app.get("/api/library/works/{work_id}")
    async def library_work(work_id: str, request: Request) -> dict[str, Any]:
        view = library_work_view(store_of(request), work_id)
        if view is None:
            raise HTTPException(404, "Work is not in the library")
        return view

    @app.post("/api/researches/{research_id}/library-sources", status_code=201)
    async def add_library_source(research_id: str, body: LibraryAddition, request: Request) -> dict[str, Any]:
        """Add one Library work to a research as a source the user included (D41)."""
        store = store_of(request)
        store.research(research_id)
        work = library_work_view(store, body.work_id)
        if work is None:
            raise HTTPException(404, "Work is not in the library")
        if any(r["id"] == research_id for r in work["researches"]):
            raise HTTPException(409, "This work is already a source of that research")
        if removed := [v["source_version_id"] for v in work["versions"] if store.was_member(research_id, v["source_version_id"])]:
            # Adding one work on purpose undoes its removal; the versions come back as they were (D50).
            store.restore_sources(research_id, removed)
            svid = store.work_heads(research_id)[body.work_id]
            level = next(v["access_level"] for v in work["versions"] if v["source_version_id"] == svid)
            return {"work_id": body.work_id, "research_id": research_id, "source_version_id": svid, "access_level": level,
                    "restored": True, "library": library_view(store)}
        version = library_version_to_add(work)
        store.add_to_corpus(research_id, version["source_version_id"], "library", selection_state="included", selection_origin="user")
        return {"work_id": body.work_id, "research_id": research_id, "source_version_id": version["source_version_id"],
                "access_level": version["access_level"], "restored": False, "library": library_view(store)}

    @app.get("/api/trash")
    async def list_trash(request: Request) -> dict[str, list[dict[str, Any]]]:
        return store_of(request).trash()

    @app.post("/api/trash/{research_id}/restore")
    async def restore_research(research_id: str, request: Request) -> dict[str, bool]:
        store_of(request).restore_research(research_id)
        return {"restored": True}

    def unlink_orphans(files: list[str], payloads: list[str]) -> list[str]:
        """Delete the files a purge orphaned; returns the ones that could not be removed from disk."""
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
        return failures

    @app.delete("/api/trash/{research_id}")
    async def purge_research(research_id: str, request: Request) -> dict[str, Any]:
        files, payloads = store_of(request).purge_research(research_id)
        return {"deleted": True, "files_not_removed": unlink_orphans(files, payloads)}

    @app.get("/api/search")
    async def quick_search(request: Request, q: str = Query(max_length=200)) -> dict[str, Any]:
        if not q.strip():
            return {"researches": [], "sources": []}
        return store_of(request).quick_search(q.strip())

    @app.post("/api/researches", status_code=201)
    async def create_research(body: CreateResearch, request: Request) -> dict[str, Any]:
        if body.seed_mode == "uploaded_seed" and body.source_scope != "attached_and_academic":
            raise HTTPException(422, "A PDF seed requires Files + academic search")
        listed: dict[str, list[dict[str, Any]] | None] = {}

        async def check_role(connection: str, model: str, effort: str | None) -> None:
            if connection not in listed:
                adapter = request.app.state.adapters.get(connection)
                if adapter is None:
                    raise HTTPException(422, f"Model connection '{connection}' is not available")
                listed[connection] = (await adapter.health()).get("models")
            check_offered(listed[connection], connection, model, effort)

        # Each role's model must be listed by that role's own connection (D28).
        await check_role(body.model_connection, body.requested_model, body.reasoning_effort)
        literature_connection = review_connection = None
        if body.literature_model is not None:
            literature_connection = body.literature_connection or body.model_connection
            await check_role(literature_connection, body.literature_model, body.literature_reasoning_effort)
        elif body.literature_reasoning_effort is not None or body.literature_connection is not None:
            raise HTTPException(422, "A literature reasoning effort or connection needs a literature model")
        if body.review_mode == "custom":
            if body.review_model is None:
                raise HTTPException(422, "A custom reviewer needs a review model")
            review_connection = body.review_connection or body.model_connection
            await check_role(review_connection, body.review_model, body.review_reasoning_effort)
        elif body.review_model is not None or body.review_reasoning_effort is not None or body.review_connection is not None:
            raise HTTPException(422, f"A review model is only kept with review_mode 'custom', not '{body.review_mode}'")
        # Every connector with the access it needs is in scope; the model picks which of the searchable ones to
        # query, and a verification connector stays in scope for the records whose DOI is already known (D87).
        providers = configured_providers() if body.source_scope != "attached" else []
        store = store_of(request)
        rid = store.create_research(body.question, body.source_scope, body.effort, providers,
                                    body.model_connection, body.requested_model, body.language_hint, body.reasoning_effort,
                                    body.literature_model, body.literature_reasoning_effort,
                                    body.review_mode, body.review_model, body.review_reasoning_effort,
                                    literature_connection=literature_connection, review_connection=review_connection,
                                    seed_mode=body.seed_mode, search_workflow=settings.search_workflow,
                                    key_terms=body.key_terms)
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

    def managed_key(env: str) -> credentials.ManagedKey:
        if env not in credentials.MANAGED_KEYS:
            raise HTTPException(404, f"{env} is not a key DEIXIS manages")
        return credentials.MANAGED_KEYS[env]

    @app.get("/api/credentials")
    async def list_credentials() -> dict[str, Any]:
        name = credentials.keychain_name()
        return {"keychain": {"available": name is not None, "name": name},
                "keys": [credentials.status(env) for env in credentials.MANAGED_KEYS]}

    @app.put("/api/credentials/{env}")
    async def save_credential(env: str, body: KeyValue, request: Request) -> dict[str, Any]:
        """Test a model key with one short request, then store it in .env or the keychain; a key the API refuses is not stored."""
        key = managed_key(env)
        source = credentials.status(env)["source"]
        if source == "environment":
            raise HTTPException(409, f"{env} is set in the shell; change or remove it there")
        if source != "dotenv" and credentials.keychain_name() is None:
            raise HTTPException(503, "No system keychain is available; set the key in .env")
        result = await credentials.test(request.app.state.http, env, body.value) if key.testable else None
        if result and result["status"] in ("rejected", "failed"):
            raise HTTPException(422, f"The key was not saved. {result['detail']}")
        try:
            credentials.save(env, body.value)
        except credentials.KeySourceConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except KeyringError as exc:
            raise HTTPException(503, f"The keychain did not store the key ({type(exc).__name__})") from exc
        except OSError as exc:
            raise HTTPException(503, f".env could not be written ({type(exc).__name__})") from exc
        return {"key": credentials.status(env), "test": result}

    @app.delete("/api/credentials/{env}")
    async def delete_credential(env: str) -> dict[str, Any]:
        managed_key(env)
        try:
            credentials.delete(env)
        except credentials.KeySourceConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except KeyringError as exc:
            raise HTTPException(503, f"The keychain did not remove the key ({type(exc).__name__})") from exc
        except OSError as exc:
            raise HTTPException(503, f".env could not be written ({type(exc).__name__})") from exc
        return {"key": credentials.status(env)}

    @app.post("/api/credentials/{env}/test")
    async def test_credential(env: str, request: Request) -> dict[str, str]:
        key, value = managed_key(env), os.environ.get(env)
        if not key.testable:
            raise HTTPException(422, f"{env} is not tested in advance; access is recorded with each request")
        if not value:
            raise HTTPException(422, f"{env} is not set")
        return await credentials.test(request.app.state.http, env, value)

    @app.get("/api/local-tools")
    async def get_local_tools(request: Request, refresh: bool = False) -> dict[str, Any]:
        return await request.app.state.local_tools.snapshot(refresh)

    @app.post("/api/local-tools/{tool_id}/install", status_code=202)
    async def install_local_tool(tool_id: str, request: Request) -> dict[str, Any]:
        try:
            return {"job": await request.app.state.local_tools.install(tool_id)}
        except local_tools.ToolError as exc:
            raise HTTPException(exc.status, str(exc)) from exc

    @app.post("/api/local-tools/{tool_id}/cancel")
    async def cancel_local_tool_install(tool_id: str, request: Request) -> dict[str, Any]:
        try:
            return {"job": request.app.state.local_tools.cancel(tool_id)}
        except local_tools.ToolError as exc:
            raise HTTPException(exc.status, str(exc)) from exc

    @app.get("/api/equation-reader")
    async def equation_reader_status(request: Request) -> dict[str, Any]:
        """The optional equation reader (Marker, D52): installed or not, its size, its install job and the PDFs it has read."""
        return await request.app.state.equations.status()

    @app.post("/api/equation-reader/install", status_code=202)
    async def install_equation_reader(request: Request) -> dict[str, Any]:
        try:
            return {"job": request.app.state.equations.install()}
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/equation-reader/cancel")
    async def cancel_equation_reader_install(request: Request) -> dict[str, Any]:
        try:
            return {"job": request.app.state.equations.cancel_install()}
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.delete("/api/equation-reader")
    async def remove_equation_reader(request: Request) -> dict[str, Any]:
        try:
            await request.app.state.equations.remove()
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return await request.app.state.equations.status()

    async def semantic_search_view(request: Request, refresh: bool = False) -> dict[str, Any]:
        saved = store_of(request).setting("semantic_search")
        provider, model = embeddings.chosen(saved)
        return {"provider": provider, "model": model, "explicit": saved is not None,
                "options": embeddings.options(await request.app.state.local_tools.snapshot(refresh))}

    @app.get("/api/semantic-search")
    async def get_semantic_search(request: Request) -> dict[str, Any]:
        return await semantic_search_view(request)

    @app.put("/api/semantic-search")
    async def put_semantic_search(body: SemanticChoice, request: Request) -> dict[str, Any]:
        """Save the embedding provider for later answers; a provider or model not offered now is refused, never replaced."""
        tools = await request.app.state.local_tools.snapshot(refresh=body.provider in ("ollama", "lm_studio"))
        option = next(o for o in embeddings.options(tools) if o["provider"] == body.provider)
        if not option["available"]:
            raise HTTPException(422, option["reason"])
        model = None
        if body.provider != "off":
            model = body.model or (option["models"][0] if body.provider in ("gemini", "openai") else None)
            if model is None:
                raise HTTPException(422, "Choose an embedding model")
            if model not in option["models"]:
                raise HTTPException(422, f"Model '{model}' is not offered by {body.provider}")
        store_of(request).set_setting("semantic_search", {"provider": body.provider, "model": model})
        return await semantic_search_view(request)

    # The institution's proxy address (slice 18a): links open through it in the person's browser; DEIXIS never
    # sends a request through it. Empty means links open directly.
    @app.get("/api/institution-proxy")
    async def get_institution_proxy(request: Request) -> dict[str, Any]:
        return {"address": store_of(request).setting(proxy.SETTING)}

    @app.put("/api/institution-proxy")
    async def put_institution_proxy(body: ProxyAddress, request: Request) -> dict[str, Any]:
        address = proxy.validate(body.address)
        store_of(request).set_setting(proxy.SETTING, address)
        return {"address": address}

    @app.get("/api/researches/{research_id}")
    async def get_research(research_id: str, request: Request) -> dict[str, Any]:
        return research_view(store_of(request), research_id)

    @app.delete("/api/researches/{research_id}")
    async def trash_research(research_id: str, request: Request) -> dict[str, bool]:
        store_of(request).trash_research(research_id)
        return {"trashed": True}

    @app.post("/api/researches/{research_id}/title")
    async def revise_title(research_id: str, body: ResearchTitleChange, request: Request) -> dict[str, Any]:
        store = store_of(request)
        try:
            store.rename_research(research_id, body.expected_version, body.title)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return research_view(store, research_id)

    @app.post("/api/researches/{research_id}/scope")
    async def revise_scope(research_id: str, body: ScopeRevision, request: Request) -> dict[str, Any]:
        store = store_of(request)
        store.revise_scope(research_id, body.expected_version, body.question, body.steering, body.key_terms)
        return research_view(store, research_id)

    @app.post("/api/researches/{research_id}/seed")
    async def select_seed(research_id: str, body: SeedSelection, request: Request) -> dict[str, Any]:
        store = store_of(request)
        store.set_seed(research_id, body.expected_version, body.source_version_id)
        return research_view(store, research_id)

    @app.post("/api/researches/{research_id}/runs", status_code=202)
    async def start_run(research_id: str, body: StartRun, request: Request,
                        idempotency_key: str | None = Header(default=None, max_length=200)) -> dict[str, Any]:
        store = store_of(request)
        scope = store.scope(research_id)
        if body.kind == "discovery" and scope["source_scope"] == "attached":
            raise HTTPException(422, "Academic search is not part of this research's source scope")
        if body.kind == "discovery" and scope["seed_mode"] == "uploaded_seed":
            seed_status = store.seed_status(research_id, scope)
            if seed_status != "ready":
                raise HTTPException(422 if seed_status == "missing" else 409,
                                    "Choose a readable PDF seed before searching" if seed_status == "missing"
                                    else "The selected PDF changed; select it again before searching")
        if body.kind in ("answer", "pdf_collection") and not store.included_works(research_id):
            raise HTTPException(422, "Include at least one source before generating an answer")
        if body.kind == "fulltext_fetch" and scope.get("search_workflow") != "sw":
            raise HTTPException(422, "Full-text retrieval runs belong to the search workflow")
        if body.kind == "fulltext_adjudication" and scope.get("search_workflow") != "sw":
            raise HTTPException(422, "Full-text reading runs belong to the search workflow")
        budget = TEST_EFFORT_BUDGETS[scope["effort"]].__dict__
        if body.kind == "discovery" and scope.get("search_workflow") == "sw":
            # The criterion proposal before the first search (D78) and the abstract stage's two runs over the
            # works the read limit reaches (D81) are given on top of the preset, so the preset itself — which a
            # legacy run and an answer run read — is what it always was (slice 06 review).
            # SUGGESTION_CALLS is the one term-suggestion call the user may ask for on the approval card (D82); a
            # run that never asks spends none of it.
            extra = CRITERION_CALLS + SUGGESTION_CALLS + abstract_stage.model_calls(
                ABSTRACT_READ_LIMIT[scope["effort"]], ABSTRACT_BATCH, ABSTRACT_RUNS)
            # The model-written query and its repair and retry (D92); a run on the code's query alone makes no call.
            extra += SEARCH_QUERY_CALLS if settings.search_query == "model" else 0
            # Citation chaining (D95): the setting is frozen into the run here, with the chain's own abstract read and
            # its own request limit, which is not `max_provider_requests`: running out of it ends the chain, never the run.
            chain: dict[str, Any] = {"citation_chaining": settings.citation_chaining}
            if settings.citation_chaining == "auto":
                extra += abstract_stage.model_calls(CHAIN_ABSTRACT_READ[scope["effort"]], ABSTRACT_BATCH, ABSTRACT_RUNS)
                # The chain's read and plan room are frozen with it, so a run keeps the policy it was queued with.
                chain |= {"max_chain_requests": CHAIN_REQUEST_LIMIT,
                          "chain_abstract_read": CHAIN_ABSTRACT_READ[scope["effort"]],
                          "chain_plan_room": CHAIN_PLAN_ROOM[scope["effort"]]}
            budget = budget | {"max_model_calls": budget["max_model_calls"] + extra} | chain
            if settings.fulltext_fetch == "auto":
                # The full text is fetched inside this run, beside its screening, with the room a retrieval run
                # would have had (slice 17a); the mode is frozen here, so a run keeps the path it was queued with.
                budget["fulltext_fetch"] = fulltext.overlap_budget(scope["effort"])
        if body.kind == "research_title":
            # One title call and its single schema repair; nothing is searched.
            budget = {"max_model_calls": 2, "max_provider_requests": 0}
        elif body.kind == "pdf_collection":
            # Downloads and open-copy lookups only; no model is called and no search is run.
            budget = {"max_model_calls": 0, "max_provider_requests": 0}
        elif body.kind == "fulltext_fetch":
            # Downloads and open-copy lookups for the works the rank order reaches (D83). The same function the
            # flow's auto-queue calls, so neither route can give this run more room than the other.
            budget = fulltext.fetch_budget(scope["effort"])
        elif body.kind == "fulltext_adjudication":
            # Two model calls per work the read limit reaches (D85). The same function the flow's auto-queue calls.
            budget = adjudication.read_budget(scope["effort"])
        key = f"{research_id}:{idempotency_key}" if idempotency_key else None
        run = store.create_run(research_id, body.kind, budget, key)
        request.app.state.worker.wake()
        return run

    @app.post("/api/runs/{run_id}/protocol-approval")
    async def approve_protocol(run_id: str, body: ProtocolApprovalSubmission, request: Request) -> dict[str, Any]:
        """Approve or correct the vocabulary and criterion an sw discovery run stopped for (SW2.6, SW15.3).

        Declared before the generic run action so `protocol-approval` reaches it. The route validates, stores and
        queues; every count request the correction needs is sent by the worker.
        """
        store = store_of(request)
        run = store.run(run_id)
        store.research(run["research_id"])
        step = store.approval_step(run_id)
        if step is None or not step["output"]:
            raise HTTPException(409, "This run has not proposed a protocol to approve")
        if step["status"] == "succeeded":
            # The protocol of this run is frozen and its searches ran under it; a change is a new scope revision.
            raise HTTPException(409, "This run's protocol is already approved; revise the scope to change it")
        if run["status"] != "paused" or run["pause_reason"] not in APPROVABLE_PAUSES:
            raise HTTPException(409, f"Cannot approve a protocol on a run in status {run['status']}")
        edits = body.model_dump()
        if errors := approval_rules.check_edits(step["output"]["proposal"], edits):
            raise HTTPException(422, {"errors": errors})
        run = store.submit_approval(run_id, edits)
        request.app.state.worker.wake()
        return run

    @app.post("/api/runs/{run_id}/term-suggestions")
    async def suggest_terms(run_id: str, request: Request) -> dict[str, Any]:
        """Ask a model for other names of the terms on the approval card (SW2.5, slice 08c).

        Declared before the generic run action, like `protocol-approval`. The route validates, counts the request
        and queues the run; the model call and every count request are sent by the worker. Nothing the model
        proposes enters a query here or later unless the user adds it in their correction.
        """
        store = store_of(request)
        run = store.run(run_id)
        store.research(run["research_id"])
        step = store.approval_step(run_id)
        if step is None or not step["output"]:
            raise HTTPException(409, "This run has not proposed a protocol to suggest terms for")
        if step["status"] == "succeeded":
            # The protocol is frozen and its searches ran under it; a change is a new scope revision.
            raise HTTPException(409, "This run's protocol is already approved; revise the scope to change it")
        if run["status"] != "paused" or run["pause_reason"] not in APPROVABLE_PAUSES:
            raise HTTPException(409, f"Cannot ask for terms on a run in status {run['status']}")
        if not suggestion_rules.anchors(step["output"]["proposal"]["vocabulary"]):
            # With no searched term there is nothing to be another name for; the way out is a term or key terms.
            raise HTTPException(409, "This proposal has no searched term to suggest other names for")
        answered = any((row["output"] or {}).get("status") == "ready" for row in store.suggestion_steps(run_id))
        if answered or step["output"].get("carried_suggestions"):
            # SW2.6: the model is not asked twice for the same thing. Only a failed request may be repeated.
            raise HTTPException(409, "This card already has the model's suggestions")
        if store.suggestion_calls(run_id) >= SUGGESTION_CALLS:
            # The run was given SUGGESTION_CALLS on top of its preset for this. A started call is charged even when
            # it fails, so another one would be paid for out of the abstract screening's share.
            raise HTTPException(409, "This run has spent the model call it had for other names")
        run = store.request_term_suggestions(run_id)
        request.app.state.worker.wake()
        return run

    @app.post("/api/runs/{run_id}/search-query-choice")
    async def choose_code_query(run_id: str, request: Request) -> dict[str, Any]:
        """Search with the code's query alone after the model could not write one (D92).

        Declared before the generic run action, like `protocol-approval`. The other way out of the same pause is
        `resume`, which asks the model once more while an attempt is left.
        """
        store = store_of(request)
        run = store.run(run_id)
        store.research(run["research_id"])
        if run["status"] != "paused" or run["pause_reason"] != "search_query_failed":
            raise HTTPException(409, f"Cannot choose the code's query on a run in status {run['status']}")
        run = store.choose_code_query(run_id)
        request.app.state.worker.wake()
        return run

    @app.post("/api/runs/{run_id}/{action}")
    async def control_run(run_id: str, action: Literal["pause", "resume", "cancel", "retry_failed"], request: Request) -> dict[str, Any]:
        store = store_of(request)
        run = store.run(run_id)
        store.research(run["research_id"])
        status = run["status"]
        worker = request.app.state.worker
        if action == "retry_failed":
            run = store.queue_failed_search_retry(run_id)
            worker.wake()
        elif action == "pause" and status in ("queued", "running"):
            new = "paused" if status == "queued" else "pause_requested"
            run = store.update_run(run_id, event="run_pause_requested", status=new, pause_reason="user_requested")
        elif action == "resume" and status == "paused" and run["pause_reason"] == "protocol_approval_needed":
            # There is no resuming past the approval: the run would freeze a protocol the user never saw (SW2.6).
            raise HTTPException(409, "Approve or correct the proposed protocol before resuming this run")
        elif (action == "resume" and status == "paused" and run["pause_reason"] == "search_query_failed"
              and not (run.get("error") or {}).get("retries_left", 1)):
            # The model was asked as many times as a run allows; the way on is the code's query or a new revision.
            raise HTTPException(409, "The model has had its second try; search with the code's query or revise the scope")
        elif action == "resume" and status == "paused":
            run = store.update_run(run_id, event="run_resumed", status="queued", pause_reason=None, error_json=None)
            worker.wake()
        elif action == "cancel" and status in ("queued", "running", "pause_requested", "paused"):
            run = store.update_run(run_id, event="run_cancelled", status="cancelled", pause_reason="user_cancelled")
            if worker.current_run_id == run_id and run["kind"] != "table_fill":
                # Roles may use different connections; only the running step's connection has a call to interrupt.
                for adapter in request.app.state.adapters.values():
                    await adapter.cancel()
        else:
            raise HTTPException(409, f"Cannot {action} a run in status {status}")
        return run

    @app.patch("/api/researches/{research_id}/selections/{source_version_id}")
    async def change_selection(research_id: str, source_version_id: str, body: SelectionChange, request: Request) -> dict[str, Any]:
        store = store_of(request)
        store.research(research_id)
        return store.set_user_selection(research_id, source_version_id, body.state, body.expected_version, body.reason)

    # ---- the human queue of an sw research (slice 16, D96) ----------------------------------------
    @app.get("/api/researches/{research_id}/queue")
    async def queue(research_id: str, request: Request) -> dict[str, Any]:
        store = store_of(request)
        store.research(research_id)
        return human_queue.queue_rows(store, research_id)

    @app.get("/api/researches/{research_id}/queue/{source_version_id}")
    async def queue_row(research_id: str, source_version_id: str, request: Request) -> dict[str, Any]:
        store = store_of(request)
        store.research(research_id)
        return human_queue.row_detail(store, research_id, source_version_id)

    @app.post("/api/researches/{research_id}/queue/{source_version_id}/decision")
    async def queue_decision(research_id: str, source_version_id: str, body: QueueDecision,
                             request: Request) -> dict[str, Any]:
        store = store_of(request)
        store.research(research_id)
        return human_queue.decide(store, research_id, source_version_id, body.decision, body.note, body.row_token)

    @app.post("/api/researches/{research_id}/queue/{source_version_id}/undo")
    async def queue_undo(research_id: str, source_version_id: str, body: QueueUndo, request: Request) -> dict[str, Any]:
        store = store_of(request)
        store.research(research_id)
        return human_queue.undo(store, research_id, source_version_id, body.row_token)

    @app.delete("/api/researches/{research_id}/sources")
    async def remove_sources(research_id: str, body: SourceRemoval, request: Request) -> dict[str, Any]:
        """Remove sources from this research; the library record, its files and the evidence citing it stay (D50)."""
        store = store_of(request)
        removed = store.remove_sources(research_id, body.source_version_ids, body.note)
        return {**research_view(store, research_id), "changed_source_version_ids": removed}

    @app.post("/api/researches/{research_id}/sources/restore")
    async def restore_sources(research_id: str, body: SourceRestore, request: Request) -> dict[str, Any]:
        store = store_of(request)
        restored = store.restore_sources(research_id, body.source_version_ids)
        return {**research_view(store, research_id), "changed_source_version_ids": restored}

    @app.post("/api/researches/{research_id}/sources/purge")
    async def purge_sources(research_id: str, body: SourceRestore, request: Request) -> dict[str, Any]:
        """Delete removed sources for good; refused while an answer, table or report still cites one (D65)."""
        store = store_of(request)
        purged, files, payloads = store.purge_sources(research_id, body.source_version_ids)
        return {"deleted": purged, "files_not_removed": unlink_orphans(files, payloads)}

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
            if store.was_member(research_id, svid) and not store.is_active_member(research_id, svid):
                store.restore_sources(research_id, [svid])  # uploading the same file again undoes its removal (D50)
        else:
            extraction = await asyncio.to_thread(pdf.extract_pdf, path)
            title = re.sub(r"[_\s]+", " ", Path(filename).stem).strip()[:200] or "Uploaded PDF"
            svid = store.create_upload_source(title)
            store.add_asset_with_pages(svid, sha, size, path.name, "user_upload", None, filename,
                                       extraction, pdf.EXTRACTION_VERSION, pdf.chunk_page)
        store.add_to_corpus(research_id, svid, "user_upload", selection_state="included", selection_origin="user")
        return research_view(store, research_id) | {"uploaded_source_version_id": svid}

    @app.post("/api/researches/{research_id}/sources/{source_version_id}/uploads", status_code=201)
    async def upload_to_source(research_id: str, source_version_id: str, request: Request,
                               file: UploadFile = File(...)) -> dict[str, Any]:
        """Attach a user-selected PDF to an existing bibliographic source version."""
        store = store_of(request)
        store.research(research_id)
        if not store.is_active_member(research_id, source_version_id):
            raise HTTPException(404, "Source is not part of this research")
        settings.papers_dir.mkdir(parents=True, exist_ok=True)
        sha, size, path = await store_upload(file, settings.papers_dir)
        if not store.conn.execute(
            "SELECT 1 FROM source_assets WHERE source_version_id = ? AND sha256 = ? AND removed_at IS NULL",
            (source_version_id, sha)
        ).fetchone():
            if store.has_asset(source_version_id):
                raise PdfInUse(source_version_id)
            extraction = await asyncio.to_thread(pdf.extract_pdf, path)
            filename = Path(file.filename or "document.pdf").name
            store.add_asset_with_pages(source_version_id, sha, size, path.name, "user_upload", None, filename,
                                       extraction, pdf.EXTRACTION_VERSION, pdf.chunk_page)
        return research_view(store, research_id)

    @app.post("/api/researches/{research_id}/uploads/match")
    async def match_uploads(research_id: str, request: Request, files: list[UploadFile] = File(...)) -> dict[str, Any]:
        """Propose which included source each dropped PDF belongs to; nothing is attached until the user confirms (D49).

        An `sw` research proposes a work among those waiting for a PDF, the latest plan's and those included since,
        with its versions for the person to pick from and what the confirmation checks (slice 18a)."""
        store = store_of(request)
        store.research(research_id)
        if store.scope(research_id).get("search_workflow") == "sw":
            return await match_waiting(store, research_id, files)
        candidates = [store.source(svid) for head in store.included_works(research_id)
                      for svid in [head, *store.work_versions(research_id, head)]]
        settings.papers_dir.mkdir(parents=True, exist_ok=True)
        matches = []
        for file in files[:50]:
            _, _, path = await store_upload(file, settings.papers_dir)
            extraction = await asyncio.to_thread(pdf.extract_pdf, path, MATCH_TEXT_CHARS)
            svid, basis = match_pdf_to_source("\n".join(page.text for page in extraction.pages), candidates)
            matches.append({"filename": Path(file.filename or "document.pdf").name, "source_version_id": svid, "basis": basis})
        return {"matches": matches}

    async def match_waiting(store: Store, research_id: str, files: list[UploadFile]) -> dict[str, Any]:
        revision = store.research(research_id)["current_scope_revision"]
        settings.papers_dir.mkdir(parents=True, exist_ok=True)
        matches = []
        for file in files[:50]:
            sha, _, path = await store_upload(file, settings.papers_dir)
            extraction = await asyncio.to_thread(pdf.extract_pdf, path, MATCH_TEXT_CHARS)
            # What the confirmation sends back and is checked against (decision 5): the file, the revision, the work.
            matches.append({"filename": Path(file.filename or "document.pdf").name, "sha256": sha, "scope_revision": revision,
                            "page_count": extraction.page_count or None,
                            "has_text_layer": None if extraction.status == "failed" else bool(extraction.pages),
                            **pdf_waiting.propose(store, research_id, "\n".join(p.text for p in extraction.pages))})
        return {"matches": matches, "scope_revision": revision}

    # ---- the works of an sw research waiting for the person's PDF (slice 18a) ----------------------
    @app.get("/api/researches/{research_id}/waiting")
    async def waiting_list(research_id: str, request: Request) -> dict[str, Any]:
        store = store_of(request)
        store.research(research_id)
        return pdf_waiting.waiting_view(store, research_id)

    @app.post("/api/researches/{research_id}/waiting/uploads", status_code=201)
    async def attach_waiting_pdf(research_id: str, request: Request, file: UploadFile = File(...),
                                 work_id: str = Form(...), source_version_id: str = Form(...),
                                 scope_revision: int = Form(...), versions_digest: str = Form(...),
                                 sha256: str = Form(...)) -> dict[str, Any]:
        """Add a dropped file to the version the person picked, once what the match showed still holds (decision 5).

        The file is added as a person's upload always was; no code and no reading run is written for it (slice 18b).
        Checked before the text is extracted, and again with the write, so nothing that moved meanwhile slips in."""
        store = store_of(request)
        store.research(research_id)
        pdf_waiting.require_sw(store, research_id)
        settings.papers_dir.mkdir(parents=True, exist_ok=True)
        sha, size, path = await store_upload(file, settings.papers_dir)
        bound = dict(work_id=work_id, source_version_id=source_version_id, scope_revision=scope_revision,
                     versions_digest=versions_digest, sha256=sha256, uploaded_sha256=sha)
        pdf_waiting.check_attach(store, research_id, **bound)
        extraction = await asyncio.to_thread(pdf.extract_pdf, path)
        filename = Path(file.filename or "document.pdf").name
        with db.transaction(store.conn):
            pdf_waiting.check_attach(store, research_id, **bound)
            asset_id = store.add_asset_with_pages(source_version_id, sha, size, path.name, "user_upload", None,
                                                  filename, extraction, pdf.EXTRACTION_VERSION, pdf.chunk_page)
            store._event(research_id, "waiting_pdf_attached", {"source_version_id": source_version_id,
                                                               "work_id": work_id, "asset_id": asset_id})
        return research_view(store, research_id) | {"attached": {"source_version_id": source_version_id,
                                                                  "asset_id": asset_id}}

    @app.post("/api/researches/{research_id}/sources/{source_version_id}/pdf-discovery")
    async def discover_source_pdf(research_id: str, source_version_id: str, request: Request) -> dict[str, Any]:
        """Collect Unpaywall, OpenAlex, Crossref and CORE locations, retrieve verified versions, and use explicit web search only if none is retrieved."""
        store = store_of(request)
        store.research(research_id)
        if not store.is_active_member(research_id, source_version_id):
            raise HTTPException(404, "Source is not part of this research")
        source = store.source(source_version_id)
        if not source.get("doi"):
            raise HTTPException(422, "A DOI is required for verified PDF acquisition")
        try:
            await acquisition.acquire_for_source(
                store, research_id, source_version_id, request.app.state.http, settings.papers_dir,
                settings.contact_email, os.environ.get("SERPAPI_API_KEY"), request.app.state.fetch_pdf,
                core_key=os.environ.get("CORE_API_KEY"),
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return research_view(store, research_id)

    @app.post("/api/researches/{research_id}/sources/{source_version_id}/pdf-candidates/{candidate_id}/attach")
    async def attach_pdf_candidate(research_id: str, source_version_id: str, candidate_id: str, request: Request) -> dict[str, Any]:
        """Retrieve a version-uncertain PDF candidate after the user has checked that it is this source's version."""
        store = store_of(request)
        store.research(research_id)
        if not store.is_active_member(research_id, source_version_id):
            raise HTTPException(404, "Source is not part of this research")
        candidate = next((c for c in store.pdf_candidates(source_version_id) if c["id"] == candidate_id), None)
        if candidate is None:
            raise HTTPException(404, "PDF candidate is not listed for this source")
        if candidate["version_status"] != "uncertain" or candidate["identity_status"] not in ("doi_verified", "title_verified"):
            raise HTTPException(422, "Only a version-uncertain candidate whose DOI or title matches this source can be confirmed")
        if store.has_asset(source_version_id):
            raise HTTPException(409, "This source already has a PDF")
        result = await acquisition.attach_confirmed_candidate(store, source_version_id, candidate, settings.papers_dir,
                                                              request.app.state.fetch_pdf)
        if result.status != "ok":
            reason = f"HTTP {result.http_status}" if result.status == "http_error" else result.status.replace("_", " ")
            raise HTTPException(502, f"No PDF was retrieved from this link ({reason})")
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
            if not store.is_active_member(research_id, svid):
                # Importing a whole collection again does not undo a removal; the PDF is not attached either (D50).
                notes.append({"title": item.record.title,
                              "note": "Removed from this research earlier; not added back. Restore it to use it here."})
                continue
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

    @app.post("/api/researches/{research_id}/zotero-pdfs")
    async def zotero_pdfs(research_id: str, body: ZoteroSourceChoice, request: Request) -> dict[str, Any]:
        """Attach PDFs from the user's Zotero library to included works that have no PDF text yet (D49).

        An item matches by DOI or by title. The file is the user's own copy, attached like an upload to the work's record.
        """
        store = store_of(request)
        store.research(research_id)
        library, http = zotero.library(body.source), request.app.state.http
        missing = [head for head in store.included_works(research_id)
                   if not store.has_pdf_text(store.answer_version(research_id, head)) and not store.has_asset(head)]
        added, notes = 0, []
        for svid in missing:
            source = store.source(svid)
            item = await zotero.find_pdf(http, library, source["doi"], source["title"])
            if item is None:
                continue
            if item.pdf_key is None:
                notes.append({"title": source["title"], "note": item.pdf_problem})
                continue
            try:
                data = await zotero.pdf_bytes(http, library, item.pdf_key, request.app.state.fetch_pdf)
            except zotero.ZoteroError as exc:
                notes.append({"title": source["title"], "note": f"PDF not added: {exc}"})
                continue
            sha = hashlib.sha256(data).hexdigest()
            settings.papers_dir.mkdir(parents=True, exist_ok=True)
            path = settings.papers_dir / f"{sha}.pdf"
            if not path.exists():
                path.write_bytes(data)
            extraction = await asyncio.to_thread(pdf.extract_pdf, path)
            store.add_asset_with_pages(svid, sha, len(data), path.name, "user_upload", f"zotero:{library.source}:{item.pdf_key}",
                                       item.pdf_filename, extraction, pdf.EXTRACTION_VERSION, pdf.chunk_page)
            added += 1
        return {**research_view(store, research_id), "zotero_pdfs": {"checked": len(missing), "added": added, "notes": notes}}

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
        # A replaced file, or the file of a source removed from this research, still opens read-only in the viewer where
        # this research's evidence cites it (D45, D50).
        svid = asset["source_version_id"]
        cited = asset["removal_reason"] in (None, "replaced") and store.was_member(research_id, svid) and store.research_cites_asset(research_id, asset_id)
        in_use = asset["removed_at"] is None and store.is_active_member(research_id, svid)
        if not (in_use or cited):
            raise HTTPException(404, "Asset is not part of this research")
        root = settings.papers_dir.resolve()
        path = (root / asset["storage_path"]).resolve()
        if not path.is_relative_to(root) or not path.exists():
            raise HTTPException(404, "File missing")
        return FileResponse(path, media_type="application/pdf", headers={"Content-Disposition": "inline"})

    @app.get("/api/researches/{research_id}/assets/{asset_id}/text")
    async def get_asset_text(research_id: str, asset_id: str, request: Request) -> dict[str, Any]:
        store = store_of(request)
        store.research(research_id)
        asset = store.asset(asset_id)
        if asset["removed_at"] is not None or not (store.is_active_member(research_id, asset["source_version_id"]) or (
                store.was_member(research_id, asset["source_version_id"]) and store.research_cites_asset(research_id, asset_id))):
            raise HTTPException(404, "Asset is not part of this research")
        source = store.source(asset["source_version_id"])
        passages = [p for p in store.passages_for(asset["source_version_id"]) if p["asset_id"] == asset_id]
        to_check = equations_to_check(store, asset_id, asset["extraction_version"])
        return {
            "asset": {k: asset[k] for k in ("id", "extraction_status", "page_count", "origin", "byte_size", "original_filename")},
            "passages": [{k: passage[k] for k in ("id", "kind", "text", "physical_page", "printed_label", "extraction_version", "payload_ref", "text_source")}
                         | {"equations_to_check": to_check.get(passage["physical_page"], 0) if passage["text_source"] == "marker" else 0}
                         for passage in passages],
            "source": {k: source[k] for k in ("id", "work_id", "title", "authors", "year", "venue", "doi", "landing_url", "version_label", "origin",
                                                "cited_by_count", "cited_by_count_at")}
            | {"source_key": store.source_key(source["work_id"])},
        }

    figure_cache: dict[str, list[dict[str, Any]]] = {}  # by PDF sha256; figures are found again after a restart (D58)

    async def asset_figures(research_id: str, asset_id: str, request: Request) -> tuple[Path, list[dict[str, Any]]]:
        store = store_of(request)
        store.research(research_id)
        asset = store.asset(asset_id)
        if asset["removed_at"] is not None or not (store.is_active_member(research_id, asset["source_version_id"]) or (
                store.was_member(research_id, asset["source_version_id"]) and store.research_cites_asset(research_id, asset_id))):
            raise HTTPException(404, "Asset is not part of this research")
        root = settings.papers_dir.resolve()
        path = (root / asset["storage_path"]).resolve()
        if not path.is_relative_to(root) or not path.exists():
            raise HTTPException(404, "File missing")
        if asset["sha256"] not in figure_cache:
            try:
                found = await asyncio.to_thread(figures.find_figures, path)
            except Exception:  # noqa: BLE001 - a PDF MuPDF cannot read has no figures to show
                found = []
            if len(figure_cache) >= 64:
                figure_cache.pop(next(iter(figure_cache)))
            figure_cache[asset["sha256"]] = found
        return path, figure_cache[asset["sha256"]]

    @app.get("/api/researches/{research_id}/assets/{asset_id}/figures")
    async def get_asset_figures(research_id: str, asset_id: str, request: Request) -> dict[str, Any]:
        _, found = await asset_figures(research_id, asset_id, request)
        return {"figures": [{"page": f["page"], "label": f["label"], "width": round(f["bbox"][2] - f["bbox"][0]),
                             "height": round(f["bbox"][3] - f["bbox"][1])} for f in found]}

    @app.get("/api/researches/{research_id}/assets/{asset_id}/figures/{label}.png")
    async def get_asset_figure(research_id: str, asset_id: str, label: str, request: Request) -> Response:
        path, found = await asset_figures(research_id, asset_id, request)
        figure = next((f for f in found if f["label"] == label), None)
        if figure is None:
            raise HTTPException(404, "Figure not found")
        png = await asyncio.to_thread(figures.render_figure, path, figure["page"], figure["bbox"])
        return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})

    @app.delete("/api/researches/{research_id}/sources/{source_version_id}/assets/{asset_id}")
    async def remove_asset(research_id: str, source_version_id: str, asset_id: str, request: Request) -> dict[str, Any]:
        """Withdraw a mistaken PDF from future answers while retaining its audit record."""
        store = store_of(request)
        store.research(research_id)
        if not store.is_active_member(research_id, source_version_id):
            raise HTTPException(404, "Source is not part of this research")
        asset = store.asset(asset_id)
        if asset["source_version_id"] != source_version_id or asset["removed_at"] is not None:
            raise HTTPException(404, "Asset is not attached to this source")
        store.remove_asset(research_id, source_version_id, asset_id)
        return research_view(store, research_id)

    @app.post("/api/researches/{research_id}/sources/{source_version_id}/assets/{asset_id}/restore")
    async def restore_asset(research_id: str, source_version_id: str, asset_id: str, request: Request) -> dict[str, Any]:
        """Put a PDF removed as the wrong file back in use; 409 when another PDF is in use for the source (D50)."""
        store = store_of(request)
        store.research(research_id)
        if not store.is_active_member(research_id, source_version_id):
            raise HTTPException(404, "Source is not part of this research")
        store.restore_asset(research_id, source_version_id, asset_id)
        return research_view(store, research_id)

    def asset_in_use(store: Store, research_id: str, source_version_id: str, asset_id: str) -> dict[str, Any]:
        store.research(research_id)
        if not store.is_active_member(research_id, source_version_id):
            raise HTTPException(404, "Source is not part of this research")
        asset = store.asset(asset_id)
        if asset["source_version_id"] != source_version_id or asset["removed_at"] is not None:
            raise HTTPException(404, "Asset is not the PDF in use for this source")
        return asset

    @app.get("/api/ocr")
    async def ocr_status() -> dict[str, Any]:
        """The local Tesseract: installed or not, its version, the languages it can read and the install command (D51)."""
        return await asyncio.to_thread(ocr.tesseract_status)

    @app.post("/api/researches/{research_id}/sources/{source_version_id}/assets/{asset_id}/ocr", status_code=202)
    async def read_with_ocr(research_id: str, source_version_id: str, asset_id: str, request: Request) -> dict[str, Any]:
        """Start a `pdf_ocr` run that reads the PDF's scanned pages with the local Tesseract; no file leaves the machine (D51)."""
        store = store_of(request)
        asset = asset_in_use(store, research_id, source_version_id, asset_id)
        if asset["extraction_status"] == "succeeded":
            raise HTTPException(422, "Text was extracted from every page of this PDF")
        status = await asyncio.to_thread(ocr.tesseract_status)
        if not status["available"]:
            raise HTTPException(422, status["reason"])
        version = ocr.target_version(pdf.EXTRACTION_VERSION, status["version"], status["languages"])
        if store.conn.execute("SELECT 1 FROM asset_extractions WHERE asset_id = ? AND extraction_version = ?", (asset_id, version)).fetchone():
            raise HTTPException(409, "This PDF was already read with this OCR version and these languages")
        run = store.create_run(research_id, "pdf_ocr", {"max_model_calls": 0, "max_provider_requests": 0}, None,
                               target={"asset_id": asset_id, "source_version_id": source_version_id, "languages": status["languages"]})
        request.app.state.worker.wake()
        return run

    @app.get("/api/researches/{research_id}/sources/{source_version_id}/assets/{asset_id}/impact")
    async def asset_impact(research_id: str, source_version_id: str, asset_id: str, request: Request) -> dict[str, Any]:
        """What a replacement would leave pointing at the old file, across every research using the source."""
        store = store_of(request)
        asset_in_use(store, research_id, source_version_id, asset_id)
        return store.asset_impact(asset_id)

    @app.put("/api/researches/{research_id}/sources/{source_version_id}/assets/{asset_id}")
    async def replace_asset(research_id: str, source_version_id: str, asset_id: str, request: Request,
                            file: UploadFile = File(...)) -> dict[str, Any]:
        """Replace the PDF in use with another file; evidence citing the old file keeps its passages (D45)."""
        store = store_of(request)
        asset_in_use(store, research_id, source_version_id, asset_id)
        settings.papers_dir.mkdir(parents=True, exist_ok=True)
        sha, size, path = await store_upload(file, settings.papers_dir)
        if sha == store.asset(asset_id)["sha256"]:
            raise SameFile(asset_id)
        extraction = await asyncio.to_thread(pdf.extract_pdf, path)
        store.replace_asset(asset_id, sha, size, path.name, "user_upload", None, Path(file.filename or "document.pdf").name,
                            extraction, pdf.EXTRACTION_VERSION, pdf.chunk_page)
        return research_view(store, research_id)

    @app.post("/api/researches/{research_id}/sources/{source_version_id}/assets/{asset_id}/extractions")
    async def reextract_asset(research_id: str, source_version_id: str, asset_id: str, request: Request) -> dict[str, Any]:
        """Extract the PDF in use again with the current extractor; it becomes current only if it loses no visible text (D45)."""
        store = store_of(request)
        asset = asset_in_use(store, research_id, source_version_id, asset_id)
        if (asset["extraction_version"] or "").split("+")[0] == pdf.EXTRACTION_VERSION:  # equations read on it too (D52)
            return {**research_view(store, research_id), "reextraction": {"asset_id": asset_id, "outcome": "unchanged"}}
        root = settings.papers_dir.resolve()
        path = (root / asset["storage_path"]).resolve()
        if not path.is_relative_to(root) or not path.exists():
            raise HTTPException(404, "File missing")
        extraction = await asyncio.to_thread(pdf.extract_pdf, path)
        report = store.reextract_asset(asset_id, extraction, pdf.EXTRACTION_VERSION, pdf.chunk_page)
        return {**research_view(store, research_id), "reextraction": report}

    @app.post("/api/researches/{research_id}/sources/{source_version_id}/assets/{asset_id}/equations", status_code=202)
    async def reread_equations(research_id: str, source_version_id: str, asset_id: str, request: Request) -> dict[str, Any]:
        """Read a PDF's equations again in the background after a failed read (D52)."""
        store = store_of(request)
        asset_in_use(store, research_id, source_version_id, asset_id)
        service = request.app.state.equations
        if not service.available():
            raise HTTPException(409, "The equation reader is not installed")
        if equation_state(store, asset_id)["state"] != "failed":
            raise HTTPException(409, "Only a failed equation reading is read again")
        service.retry(asset_id)
        return research_view(store, research_id)

    # ---- evidence tables (P5, D37) -------------------------------------------------------------
    def tables_of(request: Request) -> TableStore:
        return TableStore(store_of(request))

    def reports_of(request: Request) -> ReportStore:
        return ReportStore(store_of(request))

    @app.exception_handler(InvalidTableInput)
    async def invalid_table_input(_: Request, exc: InvalidTableInput):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    table_path = "/api/researches/{research_id}/tables/{table_id}"
    cell_path = table_path + "/cells/{column_id}/{source_version_id}"

    @app.get("/api/researches/{research_id}/tables")
    async def list_tables(research_id: str, request: Request) -> list[dict[str, Any]]:
        return tables_of(request).tables(research_id)

    @app.post("/api/researches/{research_id}/tables", status_code=201)
    async def create_table(research_id: str, body: CreateTable, request: Request,
                           idempotency_key: str | None = Header(default=None, max_length=200)) -> dict[str, Any]:
        tables = tables_of(request)
        table_id = tables.create_table(research_id, body.title, body.rows, body.template_id, idempotency_key)
        return tables.table_view(research_id, table_id)

    @app.get(table_path)
    async def get_table(research_id: str, table_id: str, request: Request) -> dict[str, Any]:
        return tables_of(request).table_view(research_id, table_id)

    @app.patch(table_path)
    async def rename_table(research_id: str, table_id: str, body: TableTitle, request: Request) -> dict[str, Any]:
        tables = tables_of(request)
        tables.rename_table(research_id, table_id, body.title, body.expected_version)
        return tables.table_view(research_id, table_id)

    @app.delete(table_path)
    async def trash_table(research_id: str, table_id: str, request: Request, expected_version: int = Query()) -> dict[str, bool]:
        tables_of(request).trash_table(research_id, table_id, expected_version)
        return {"trashed": True}

    @app.post(table_path + "/restore")
    async def restore_table(research_id: str, table_id: str, body: ExpectedVersion, request: Request) -> dict[str, Any]:
        tables = tables_of(request)
        tables.restore_table(research_id, table_id, body.expected_version)
        return tables.table_view(research_id, table_id)

    @app.delete("/api/trash/tables/{table_id}")
    async def purge_table(table_id: str, request: Request) -> dict[str, Any]:
        return {"deleted": True, **tables_of(request).purge_table(table_id)}

    @app.post(table_path + "/rows")
    async def add_table_rows(research_id: str, table_id: str, body: TableRows, request: Request) -> dict[str, Any]:
        tables = tables_of(request)
        tables.add_rows(research_id, table_id, body.source_version_ids, body.expected_version)
        return tables.table_view(research_id, table_id)

    @app.delete(table_path + "/rows/{source_version_id}")
    async def remove_table_row(research_id: str, table_id: str, source_version_id: str, request: Request,
                               expected_version: int = Query()) -> dict[str, Any]:
        tables = tables_of(request)
        tables.remove_row(research_id, table_id, source_version_id, expected_version)
        return tables.table_view(research_id, table_id)

    @app.post(table_path + "/columns", status_code=201)
    async def add_table_column(research_id: str, table_id: str, body: ColumnCreate, request: Request,
                               idempotency_key: str | None = Header(default=None, max_length=200)) -> dict[str, Any]:
        tables = tables_of(request)
        spec = body.model_dump(exclude={"expected_version", "suggestion_step_id"})
        tables.add_column(research_id, table_id, spec, body.expected_version, idempotency_key,
                          origin="model_suggestion" if body.suggestion_step_id else "user", suggestion_step_id=body.suggestion_step_id)
        return tables.table_view(research_id, table_id)

    @app.post(table_path + "/template-columns", status_code=201)
    async def apply_table_template(research_id: str, table_id: str, body: TemplateApply, request: Request,
                                   idempotency_key: str | None = Header(default=None, max_length=200)) -> dict[str, Any]:
        tables = tables_of(request)
        tables.apply_template(research_id, table_id, body.template_id, body.expected_version, idempotency_key)
        return tables.table_view(research_id, table_id)

    @app.post(table_path + "/column-suggestions", status_code=202)
    async def suggest_table_columns(research_id: str, table_id: str, request: Request,
                                    idempotency_key: str | None = Header(default=None, max_length=200)) -> dict[str, Any]:
        run = tables_of(request).request_column_suggestions(research_id, table_id, idempotency_key)
        request.app.state.worker.wake()
        return run

    @app.post(table_path + "/fill", status_code=202)
    async def fill_table(research_id: str, table_id: str, body: FillRequest, request: Request,
                         idempotency_key: str | None = Header(default=None, max_length=200)) -> dict[str, Any]:
        run = tables_of(request).request_fill(research_id, table_id, body.column_ids, body.include_stale, body.expected_version,
                                              idempotency_key)
        request.app.state.worker.wake()
        return run

    @app.post("/api/researches/{research_id}/reports", status_code=202)
    async def start_report(research_id: str, body: StartReport, request: Request,
                           idempotency_key: str | None = Header(default=None, max_length=200)) -> dict[str, Any]:
        run = reports_of(request).request_report(research_id, body.table_id, idempotency_key)
        request.app.state.worker.wake()
        return run

    @app.get("/api/researches/{research_id}/reports/{report_id}")
    async def get_report(research_id: str, report_id: str, request: Request) -> dict[str, Any]:
        return report_view(store_of(request), research_id, report_id)

    @app.get("/api/researches/{research_id}/reports")
    async def list_reports(research_id: str, request: Request) -> list[dict[str, Any]]:
        return research_view(store_of(request), research_id)["reportRuns"]

    @app.patch(table_path + "/columns/{column_id}")
    async def revise_table_column(research_id: str, table_id: str, column_id: str, body: ColumnChange, request: Request) -> dict[str, Any]:
        tables = tables_of(request)
        changes = body.model_dump(exclude_unset=True, exclude={"expected_version", "position"})
        tables.revise_column(research_id, table_id, column_id, changes, body.position, body.expected_version)
        return tables.table_view(research_id, table_id)

    @app.delete(table_path + "/columns/{column_id}")
    async def remove_table_column(research_id: str, table_id: str, column_id: str, request: Request,
                                  expected_version: int = Query()) -> dict[str, Any]:
        tables = tables_of(request)
        tables.remove_column(research_id, table_id, column_id, expected_version)
        return tables.table_view(research_id, table_id)

    @app.post(table_path + "/columns/{column_id}/restore")
    async def restore_table_column(research_id: str, table_id: str, column_id: str, body: ExpectedVersion,
                                   request: Request) -> dict[str, Any]:
        tables = tables_of(request)
        tables.restore_column(research_id, table_id, column_id, body.expected_version)
        return tables.table_view(research_id, table_id)

    @app.get(cell_path)
    async def get_cell(research_id: str, table_id: str, column_id: str, source_version_id: str, request: Request) -> dict[str, Any]:
        return tables_of(request).cell_view(research_id, table_id, column_id, source_version_id)

    @app.put(cell_path)
    async def edit_cell(research_id: str, table_id: str, column_id: str, source_version_id: str, body: CellEdit, request: Request,
                        idempotency_key: str | None = Header(default=None, max_length=200)) -> dict[str, Any]:
        tables = tables_of(request)
        tables.edit_cell(research_id, table_id, column_id, source_version_id, body.state, body.value, body.note,
                         body.keep_evidence_from, body.expected_version, idempotency_key)
        return tables.cell_view(research_id, table_id, column_id, source_version_id)

    @app.post(cell_path + "/recheck", status_code=202)
    async def recheck_cell(research_id: str, table_id: str, column_id: str, source_version_id: str, body: ExpectedVersion,
                           request: Request, idempotency_key: str | None = Header(default=None, max_length=200)) -> dict[str, Any]:
        run = tables_of(request).request_recheck(research_id, table_id, column_id, source_version_id, body.expected_version,
                                                 idempotency_key)
        request.app.state.worker.wake()
        return run

    @app.post(cell_path + "/proposals/{revision_id}/{decision}")
    async def decide_cell_proposal(research_id: str, table_id: str, column_id: str, source_version_id: str, revision_id: str,
                                   decision: Literal["accept", "dismiss"], body: ExpectedVersion, request: Request,
                                   idempotency_key: str | None = Header(default=None, max_length=200)) -> dict[str, Any]:
        tables = tables_of(request)
        tables.decide_proposal(research_id, table_id, column_id, source_version_id, revision_id, decision == "accept",
                               body.expected_version, idempotency_key)
        return tables.cell_view(research_id, table_id, column_id, source_version_id)

    @app.get("/api/table-templates")
    async def list_table_templates(request: Request) -> list[dict[str, Any]]:
        return tables_of(request).templates()

    @app.post("/api/table-templates", status_code=201)
    async def create_table_template(body: TemplateCreate, request: Request,
                                    idempotency_key: str | None = Header(default=None, max_length=200)) -> dict[str, Any]:
        tables = tables_of(request)
        template_id = tables.create_template(body.research_id, body.table_id, body.name, idempotency_key)
        return next(t for t in tables.templates() if t["id"] == template_id)

    @app.delete("/api/table-templates/{template_id}")
    async def trash_table_template(template_id: str, request: Request) -> dict[str, bool]:
        tables_of(request).trash_template(template_id)
        return {"trashed": True}

    @app.post("/api/table-templates/{template_id}/restore")
    async def restore_table_template(template_id: str, request: Request) -> dict[str, bool]:
        tables_of(request).restore_template(template_id)
        return {"restored": True}

    @app.delete("/api/trash/templates/{template_id}")
    async def purge_table_template(template_id: str, request: Request) -> dict[str, Any]:
        return {"deleted": True, **tables_of(request).purge_template(template_id)}

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
