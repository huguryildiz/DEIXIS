"""Local HTTP API. Loopback only, Host/Origin allowlist and double-submit CSRF token for mutations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import sqlite3
import tempfile
import time
from contextlib import asynccontextmanager, contextmanager, nullcontext
from pathlib import Path
from typing import Annotated, Any, Awaitable, Callable, Iterator, Literal

import httpx
from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from keyring.errors import KeyringError
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from deixis import credentials, local_tools
from deixis.config import Settings, load_settings
from deixis.documents import fetch as fetch_module
from deixis.documents import acquisition
from deixis.documents import embeddings
from deixis.documents import figures
from deixis.documents.identity import MATCH_TEXT_CHARS
from deixis.documents import local_embedding, math_reader
from deixis.documents import ocr
from deixis.documents import pdf
from deixis.domain import proxy, skill
from deixis.workflow import abstract_stage
from deixis.workflow import chaining, fast_path, small_batch
from deixis.workflow import file_restore, text_retry
from deixis.domain.rules import (ABSTRACT_BATCH, ABSTRACT_READ_LIMIT, ABSTRACT_RUNS, CHAIN_ABSTRACT_READ, CHAIN_PLAN_ROOM,
                                 CHAIN_REQUEST_LIMIT, CRITERION_CALLS, SEARCH_QUERY_CALLS,
                                 SUGGESTION_CALLS, ADVICE_CALLS, TEST_EFFORT_BUDGETS, RevisionConflict, effort_limits)
from deixis.models.adapter import CodexAdapter, ModelAdapter
from deixis.models.claude import ClaudeCodeAdapter
from deixis.models.deepseek import DeepSeekAdapter
from deixis.models.openai_compat import CONNECTIONS as COMPAT_CONNECTIONS, OpenAICompatAdapter
from deixis.models.gemini import GeminiAdapter
from deixis.providers import scopus
from deixis.providers import zotero
from deixis.providers.registry import CONNECTORS, configured_providers, provider_role
from deixis.storage import db
from deixis.workflow import approval as approval_rules
from deixis.workflow import adjudication, fulltext
from deixis.workflow import suggestions as suggestion_rules
from deixis.workflow import bibliography
from deixis.workflow import audit as audit_rules
from deixis.workflow import prisma_s
from deixis.workflow import queue as human_queue
from deixis.workflow import person_reading
from deixis.workflow import waiting as pdf_waiting
from deixis.workflow.concurrency import ModelCallLimiter
from deixis.workflow import english_question
from deixis.workflow.equations import EquationService, chunk_numbers, equation_state, equations_to_check, latex_numbers
from deixis.workflow.local_embedding_service import EmbeddingService, ServiceError
from deixis.workflow.flow import FlowDeps, ResearchFlow
from deixis.workflow import report_pipeline
from deixis.workflow.report.store import ReportStore
from deixis.workflow.report import export as report_export
from deixis.workflow.report import latex_export
from deixis.workflow.store import (COPIED_SELECTION_REASON, NotASource, NotFound, PdfInUse, RunInProgress, SameFile,
                                   SeedUnavailable, Store, LegacyInspectionPolicyRemoved,
                                   RequestConflict, RecoveryConflict, NotRetryable)
from deixis.workflow.tables import CELL_STATES, InvalidTableInput, TableStore
from deixis.workflow.lineage.run import LineagePlanner, stale_link_revisions
from deixis.workflow.lineage.store import InvalidLineageInput, LineageStore
from deixis.workflow.lineage.view import LineageView
from deixis.workflow.candidates.run import KillSearchPlanner, candidate_evidence, decompose_budget, request_decomposition
from deixis.workflow.candidates.store import CandidateStore, InvalidCandidateInput
from deixis.workflow.views import library_version_to_add, library_view, library_work_view, occurrence_view, passage_view, report_gaps_view, report_view, research_view
from deixis.workflow.worker import Worker
from deixis.workflow.review import run as review_run
from deixis.workflow.review.reader import ReviewReader
from deixis.workflow.review.snapshot import build_snapshot, NotReviewable
from deixis.workflow.review.stale import stale_reasons
from deixis.workflow.review.store import ReviewStore, ReviewRefusal, ReviewConflict, applied_matches_suggestion
from deixis.workflow import recovery_history
from deixis.workflow.report.review import REVIEW_BUDGET_TOKENS
from deixis.workflow.flow import CAPABILITIES
from deixis.domain.canonical import sha256_hex

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
    # Runs literature model steps. None: the research model runs them.
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
    provider: Literal["gemini", "builtin", "openai", "ollama", "lm_studio", "off"]
    model: str | None = Field(default=None, min_length=1, max_length=200)


class EnglishQuestion(BaseModel):
    """The built-in model's English sentence for the current scope revision (slice 21): the person's `text`, or
    `use_question` when the question is already English; the server then writes the question itself."""
    text: str | None = Field(default=None, max_length=english_question.MAX_CHARS)
    use_question: bool = False
    expected_version: int


class StartRun(BaseModel):
    kind: Literal["discovery", "answer", "pdf_collection", "research_title", "fulltext_fetch", "fulltext_adjudication"]


class ReviewPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_kind: Literal["answer", "report", "candidate"]
    target_id: str = Field(min_length=1, max_length=64)
    focus: Literal["source_support", "assumptions_and_consistency"]
    owner_note: str | None = Field(default=None, max_length=500)
    connection: str = Field(min_length=1, max_length=40)
    model: str = Field(min_length=1, max_length=120)
    reasoning_effort: str | None = Field(default=None, min_length=1, max_length=40)

    @field_validator("owner_note")
    @classmethod
    def nonblank_note(cls, value):
        if value is not None and not value.strip():
            raise ValueError("owner_note must be non-blank when supplied")
        return value


class ReviewStartRequest(ReviewPreviewRequest):
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    preview_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["accepted", "dismissed", "deferred"]
    reason: str | None = Field(default=None, max_length=2000)
    expected_ordinal: int = Field(ge=0)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value):
        if value is not None and not value.strip():
            raise ValueError("reason must be non-blank when supplied")
        return value


class ReviewApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str | None = Field(default=None, max_length=20_000)
    link_ids: list[str] | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=2000)
    expected_version: int = Field(ge=0)
    dependency_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class SelectionChange(BaseModel):
    state: Literal["included", "excluded", "pending"]
    expected_version: int
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("reason")
    @classmethod
    def _not_the_copy_marker(cls, value: str | None) -> str | None:
        # The copy a new head writes is told apart from a person's edit by this reason alone (slice 19): it is reserved.
        if value == COPIED_SELECTION_REASON:
            raise ValueError("this reason is reserved for a selection copied to a new head")
        return value


class QueueDecision(BaseModel):
    decision: Literal["include", "criterion_not_met", "not_sure", "pdf_wrong", "pdf_confirmed"]
    note: str | None = Field(default=None, max_length=1000)
    row_token: str = Field(max_length=200)


class QueueUndo(BaseModel):
    row_token: str = Field(max_length=200)


class AuditDecision(BaseModel):
    decision: Literal["include", "criterion_not_met", "not_sure", "pdf_wrong"]
    note: str | None = Field(default=None, max_length=1000)
    audit_token: str = Field(max_length=300)


class AuditUndo(BaseModel):
    audit_token: str = Field(max_length=300)


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
    continue_with_failed: bool = False


class ReportClaimEdit(BaseModel):
    text: str | None = Field(default=None, max_length=4000)
    link_ids: list[str] | None = Field(default=None, max_length=200)
    restore_from: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=1000)
    expected_version: int

    @field_validator("link_ids")
    @classmethod
    def link_ids_fit(cls, ids: list[str] | None) -> list[str] | None:
        if ids is not None and any(len(link_id) > 40 for link_id in ids):
            raise ValueError("Each link id has at most 40 characters")
        return ids


class ReportChangesAcknowledgement(BaseModel):
    change_keys: list[str] = Field(min_length=1, max_length=500)

    @field_validator("change_keys")
    @classmethod
    def keys_fit(cls, keys: list[str]) -> list[str]:
        if any(len(key) > 200 for key in keys):
            raise ValueError("Each change key has at most 200 characters")
        return keys


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


class LineageRunRequest(BaseModel):
    preview_fingerprint: str = Field(min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")
    retry_failed: bool = False


class CandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def candidate_safe_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise InvalidCandidateInput("Candidate text must be encodable as UTF-8") from None
    if not value.strip() or "\x00" in value:
        raise InvalidCandidateInput("Candidate text must be non-blank and contain no NUL")
    return value


# Reject surrogates before Pydantic can echo them in a validation-error response.
CandidateText = Annotated[str, BeforeValidator(candidate_safe_text)]


class OwnerTextCandidate(CandidateRequest):
    origin: Literal["owner_text"]
    text: CandidateText = Field(min_length=1, max_length=2000)


class GapCandidate(CandidateRequest):
    origin: Literal["report_gap"]
    report_id: str = Field(min_length=1, max_length=80)
    gap_row_id: str = Field(min_length=1, max_length=80)


class CandidateElement(CandidateRequest):
    text: CandidateText = Field(min_length=1, max_length=2000)
    kind: Literal["mechanism", "condition", "outcome", "parameter"]


class CandidateVersionRequest(CandidateRequest):
    claim_statement: CandidateText = Field(min_length=1, max_length=4000)
    conditions: list[Annotated[CandidateText, Field(min_length=1, max_length=2000)]] = Field(max_length=24)
    elements: list[CandidateElement] = Field(min_length=2, max_length=6)
    nearest_simple_explanation: CandidateText | None = Field(max_length=4000)
    critical_assumption: CandidateText = Field(max_length=4000)
    validation_plan: CandidateText = Field(max_length=4000)
    expected_version: int = Field(ge=0, strict=True)


class CandidateKillSearchRequest(CandidateRequest):
    preview_fingerprint: str = Field(min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")


class CandidateOwnerDecision(CandidateRequest):
    status: Literal["not_run", "undecided", "narrowed", "closed", "open"]
    reason: CandidateText = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must be non-blank")
        return value.strip()


class CandidateListItem(BaseModel):
    id: str
    origin: Literal["owner_text", "report_gap"]
    origin_report_id: str | None
    origin_gap_row_id: str | None
    gap_kind: str | None
    origin_changed: bool
    current_version: int
    trashed_at: str | None
    claim_statement: str | None
    status: dict[str, Any] | None
    owner: dict[str, Any] | None
    active_run_id: str | None


class CandidateCard(BaseModel):
    id: str
    research_id: str
    origin: Literal["owner_text", "report_gap"]
    origin_report_id: str | None
    origin_gap_row_id: str | None
    gap_kind: str | None
    origin_text: str
    origin_basis: dict[str, Any]
    origin_basis_view: dict[str, Any]
    origin_provenance: dict[str, Any]
    origin_fingerprint: str | None
    origin_changed: bool
    current_version: int
    trashed_at: str | None
    created_at: str
    versions: list[dict[str, Any]]
    current_version_id: str | None
    owner_decisions: list[dict[str, Any]]
    searches: list[dict[str, Any]]
    status: dict[str, Any] | None
    active_run: dict[str, Any] | None
    runs: list[dict[str, Any]]
    decompose_budget: dict[str, int]


class CandidateMatrix(BaseModel):
    search: dict[str, Any]
    queries: list[dict[str, Any]]
    counts: dict[str, int]
    hits: list[dict[str, Any]]
    cells: dict[str, dict[str, dict[str, Any]]]
    evidence: list[dict[str, Any]]
    summary: dict[str, Any] | None
    search_status: dict[str, Any]
    candidate_version_id: str
    version: int
    kill_search_id: str
    is_latest_search_of_version: bool


class CandidateEvidence(BaseModel):
    source: dict[str, Any]
    passages: list[dict[str, Any]]
    quotes: list[dict[str, Any]]


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


class LineageEvidence(BaseModel):
    passage_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class LineageLinkFields(BaseModel):
    relation: Literal["extends", "relaxes_assumption", "changes_method", "new_domain_or_condition",
                      "corrects_or_contradicts", "independent_parallel"]
    what_changed: str = Field(min_length=1, max_length=500)
    support_type: Literal["source_stated", "analyst_inference"]
    evidence: list[LineageEvidence] = Field(min_length=1, max_length=5)
    note: str | None = Field(default=None, max_length=2000)
    expected_version: int = Field(ge=0, strict=True)


class LineageLinkAdd(LineageLinkFields):
    from_source_version_id: str = Field(min_length=1)
    to_source_version_id: str = Field(min_length=1)


class LineageLinkEdit(LineageLinkFields):
    based_on_revision_id: str = Field(min_length=1)


class ExpectedVersion(BaseModel):
    expected_version: int


class TemplateApply(BaseModel):
    template_id: str = Field(max_length=40)
    expected_version: int


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    research_id: str = Field(max_length=40)
    table_id: str = Field(max_length=40)


class TextRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["retry_failed_or_partial"]
    expected_current_extraction_id: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{8,128}$")


class DiskFull(Exception):
    """The upload could not be written because the disk is full (`store_upload`)."""


@contextmanager
def disk_full_refused() -> Iterator[None]:
    """A write that fails because the disk is full is the same refusal an upload gets (507 `disk_full`), not a bare 500."""
    try:
        yield
    except OSError as exc:
        if db.describe_failure(exc):
            raise DiskFull from exc
        raise


class UploadRefused(Exception):
    """An upload `store_upload` refuses; `code` lets the page translate the sentence."""

    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


async def store_upload(file: UploadFile, papers_dir: Path) -> file_restore.Staged:
    """Stage and fsync an upload while hashing; the caller owns the returned partial file."""
    digest, size, head = hashlib.sha256(), 0, b""
    try:
        fd, partial = tempfile.mkstemp(dir=papers_dir, suffix=".partial")
    except OSError as exc:  # creating the file already fails on a full disk
        if db.describe_failure(exc):
            raise DiskFull from exc
        raise
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := await file.read(UPLOAD_CHUNK_BYTES):
                head = head or chunk[:5]
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise UploadRefused(413, "upload_too_large", "PDF larger than 50 MB")
                digest.update(chunk)
                if out.write(chunk) != len(chunk):
                    raise OSError(5, "Incomplete staged upload write")
            out.flush()
            os.fsync(out.fileno())
        if head != b"%PDF-":
            raise UploadRefused(422, "upload_not_pdf", "Only PDF files are supported")
        return file_restore.Staged(Path(partial), digest.hexdigest(), size)
    except OSError as exc:
        file_restore.cleanup(Path(partial))
        if db.describe_failure(exc):
            raise DiskFull from exc
        raise
    except BaseException:
        file_restore.cleanup(Path(partial))
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
    local_embedder: Any = None,
    xml_fetcher: Callable[[str], Awaitable[fetch_module.FetchResult]] | None = None,
    clock: fast_path.Clock | None = None,
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
        store = Store(conn, clock=clock)
        store.recovery_dir = settings.recovery_dir
        http = http_client or httpx.AsyncClient(headers={"User-Agent": fetch_module.user_agent()})
        adapter_map = adapters if adapters is not None else {
            "codex": CodexAdapter(codex_home=settings.codex_home, workspace=settings.data_dir / "codex-workspace"),
            "claude": ClaudeCodeAdapter(workspace=settings.data_dir / "claude-workspace"),
            "gemini": GeminiAdapter(client=http),
            "deepseek": DeepSeekAdapter(client=http),
            **{name: OpenAICompatAdapter(spec, client=http) for name, spec in COMPAT_CONNECTIONS.items()},
        }
        package = skill.load_skill_package()
        equations = equation_service if equation_service is not None else EquationService(
            store, math_reader.MathReader(math_reader.runtime_paths(settings.data_dir)), settings.papers_dir)
        if equation_service is None:
            equations.configure_arxiv_source(settings.arxiv_source, settings.data_dir)  # D104, off unless the flag says auto
        # The built-in embedding model (slice 21): a test injects its own embedder and never starts a real runner.
        builtin_paths = local_embedding.builtin_paths(settings.data_dir)
        embedder = local_embedder if local_embedder is not None else local_embedding.LocalEmbedder(builtin_paths)
        builtin = EmbeddingService(builtin_paths, embedder, http)
        await builtin.start()  # recovers an install a closed DEIXIS left running, then checks the files in full
        local_embedding.register(builtin.integrity)
        from deixis.workflow.background_fetch import FetchSlots
        flow = ResearchFlow(FlowDeps(settings, store, adapter_map, package, http, fetcher or fetch_module.fetch_pdf, equations,
                                     limiter=ModelCallLimiter(settings.model_concurrency), local_embedder=embedder,
                                     fetch_xml=xml_fetcher or acquisition.fetch_xml, clock=store.clock, fetch_slots=FetchSlots(12)))
        app.state.builtin = builtin
        worker = Worker(store, flow, settings.lock_path)
        owner = start_worker and worker.acquire()
        app.state.equations = equations
        if owner:
            equations.start()  # reads stored PDFs' equations in the background when the reader is installed (D52)
        app.state.store, app.state.worker, app.state.adapters = store, worker, adapter_map
        app.state.package, app.state.owner = package, owner
        app.state.http, app.state.fetch_pdf = http, fetcher or fetch_module.fetch_pdf
        app.state.fetch_xml = xml_fetcher or acquisition.fetch_xml  # Europe PMC's full text (SW21)
        app.state.institutional_access = None
        app.state.local_tools = local_tools.LocalTools(http)
        app.state.recovered = worker.recover() if owner else None
        app.state.reconciled = None
        async def reconcile_recovery() -> None:
            import logging
            from deixis.workflow import reconcile

            try:
                app.state.reconciled = await reconcile.reconcile_stale(store, settings.papers_dir, settings.recovery_dir)
            except Exception:
                logging.getLogger(__name__).exception("Recovery reconciliation failed at startup; continuing")

        if owner:
            await reconcile_recovery()

        from deixis.workflow.watch.scheduler import WatchScheduler
        scheduler_stop = asyncio.Event()
        scheduler_task = None

        def start_watch_scheduler():
            nonlocal scheduler_task
            app.state.watch_scheduler = WatchScheduler(store, worker.wake)
            scheduler_task = asyncio.create_task(app.state.watch_scheduler.run_forever(scheduler_stop))

        async def take_over_when_released() -> None:
            # A previous instance may still be shutting down and holding the lock; own the worker once it is released.
            while not worker.acquire():
                await asyncio.sleep(1.0)
            app.state.recovered = worker.recover()
            await reconcile_recovery()
            app.state.owner = True
            equations.start()
            start_watch_scheduler()
            await worker.run_forever()

        task = asyncio.create_task(worker.run_forever() if owner else take_over_when_released()) if start_worker else None
        if owner:
            # Start-up person readings must enter the queue before the first automatic tick.
            start_watch_scheduler()
        try:
            yield
        finally:
            scheduler_stop.set()
            if scheduler_task:
                await scheduler_task
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
            await builtin.stop()
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
                    return JSONResponse({"detail": "Upload size must be declared", "code": "upload_size_undeclared"},
                                        status_code=411)
                if int(length) > MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES:
                    return JSONResponse({"detail": "PDF larger than 50 MB", "code": "upload_too_large"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def store_of(request: Request) -> Store:
        return request.app.state.store

    @app.exception_handler(UploadRefused)
    async def upload_refused(_: Request, exc: UploadRefused):
        return JSONResponse({"detail": exc.detail, "code": exc.code}, status_code=exc.status)

    # A full disk and a busy, read-only or damaged library get one sentence and a code (P9 H3). Any other database
    # error is a code bug and stays the 500 it was.
    @app.exception_handler(DiskFull)
    @app.exception_handler(sqlite3.DatabaseError)
    async def storage_failed(request: Request, exc: Exception):
        failure = db.describe_failure(exc if isinstance(exc, sqlite3.DatabaseError) else exc.__cause__ or exc)
        if failure is None:
            raise exc
        code, status, detail = failure
        return JSONResponse({"detail": detail, "code": code}, status_code=status)

    @app.exception_handler(StarletteHTTPException)
    async def body_parse_failed(request: Request, exc: StarletteHTTPException):
        # FastAPI wraps multipart spool failures before an upload endpoint can handle them.
        # Only FastAPI's own 400 for a body that could not be read; any other HTTPException keeps its status, detail and headers.
        if exc.status_code == 400 and exc.detail == "There was an error parsing the body" \
                and (failure := db.describe_failure(exc.__cause__)) is not None:
            code, status, detail = failure
            return JSONResponse({"detail": detail, "code": code}, status_code=status)
        return await http_exception_handler(request, exc)

    @app.exception_handler(NotFound)
    async def not_found(_: Request, exc: NotFound):
        return JSONResponse({"detail": f"Not found: {exc}"}, status_code=404)

    @app.exception_handler(PdfInUse)
    async def pdf_in_use(_: Request, exc: PdfInUse):
        return JSONResponse({"detail": "This source already has a PDF in use; replace it instead"}, status_code=409)

    @app.exception_handler(RunInProgress)
    async def source_run_in_progress(_: Request, exc: RunInProgress):
        return JSONResponse({"detail": "A research using this source has a run in progress; try again when it has stopped"}, status_code=409)

    @app.exception_handler(RequestConflict)
    async def retry_request_conflict(_: Request, exc: RequestConflict):
        return JSONResponse({"detail": "This request key was used for a different text retry.", "code": "request_conflict"}, status_code=409)

    @app.exception_handler(RecoveryConflict)
    async def retry_conflict(_: Request, exc: RecoveryConflict):
        details = {"baseline_changed": "The current extraction changed; read it before retrying.",
                   "operation_running": "A text retry is already reserved for this asset.",
                   "operation_not_running": "This text retry is no longer running."}
        return JSONResponse({"detail": details.get(str(exc), "This text retry conflicts with the current recovery state."),
                             "code": str(exc)}, status_code=409)

    @app.exception_handler(NotRetryable)
    async def retry_not_retryable(_: Request, exc: NotRetryable):
        return JSONResponse({"detail": "This extraction is not eligible for a text retry.",
                             "code": "not_retryable", "reason": str(exc)}, status_code=422)

    @app.exception_handler(text_retry.FileBusy)
    async def retry_file_busy(_: Request, exc: text_retry.FileBusy):
        return JSONResponse({"detail": str(exc), "code": "file_busy"}, status_code=409)

    @app.exception_handler(file_restore.FileRestoreRefused)
    async def file_restore_refused(_: Request, exc: file_restore.FileRestoreRefused):
        return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=409)

    @app.exception_handler(text_retry.FileMissing)
    async def retry_file_missing(_: Request, exc: text_retry.FileMissing):
        return JSONResponse({"detail": "File missing"}, status_code=404)

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

    @app.exception_handler(ReviewRefusal)
    async def review_refusal(_: Request, exc: ReviewRefusal):
        return JSONResponse(exc.extra_fields | {"detail": exc.detail, "code": exc.code}, status_code=exc.status_code)

    from deixis.api.watch_routes import register_watch_routes
    from deixis.workflow.watch.store import WatchRefusal
    register_watch_routes(app)

    @app.exception_handler(WatchRefusal)
    async def watch_refusal(_: Request, exc: WatchRefusal):
        return JSONResponse({"detail": exc.detail, "code": exc.code}, status_code=exc.status)

    @app.exception_handler(LegacyInspectionPolicyRemoved)
    async def removed_inspection(_: Request, exc: LegacyInspectionPolicyRemoved):
        return JSONResponse({"detail": "legacy_inspection_policy_removed",
                             "code": "legacy_inspection_policy_removed",
                             "message": "This stored inspection policy was removed. Start a new discovery in this research.",
                             "next_action": "new_discovery"}, status_code=409)

    # The queue's 409 says why (slice 17): the row changed, or the reading of a confirmed PDF began. Other 409s keep
    # their one-sentence detail.
    @app.exception_handler(human_queue.QueueConflict)
    async def queue_conflict(_: Request, exc: human_queue.QueueConflict):
        return JSONResponse({"detail": {"reason": exc.reason, "message": str(exc)}}, status_code=409)

    # A confirmation of a dropped file says why it was refused (slice 18a), as the queue's 409 does.
    @app.exception_handler(pdf_waiting.AttachRefused)
    async def attach_refused(_: Request, exc: pdf_waiting.AttachRefused):
        return JSONResponse({"detail": {"reason": exc.reason, "message": str(exc)}}, status_code=409)

    @app.exception_handler(person_reading.RetryRefused)
    async def retry_refused(_: Request, exc: person_reading.RetryRefused):
        return JSONResponse({"detail": str(exc)}, status_code=409)

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
        from deixis.providers.facade import connectors
        descriptors = {p: f.descriptor for p, f in connectors().items()}
        models = {}
        for name, adapter in request.app.state.adapters.items():
            models[name] = await adapter.health(refresh=refresh)
        for name in ("grok", "copilot", "glm", "muse_spark", "muse_glimmer", "ollama"):
            models.setdefault(name, {"connection": name, "ready": False, "reason": "Adapter not implemented in this version"})
        return {
            "models": models,
            "providers": [
                {"id": p, "implemented": True, "access_mode": c.access_mode(), "supplementary": c.supplementary,
                 "key_env": c.key_env, "role": provider_role(c),
                 "contract_id": descriptors[p].contract_id, "adapter_revision": descriptors[p].adapter_revision,
                 "capabilities": sorted(descriptors[p].capabilities),
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
        async with (nullcontext(http_client) if http_client else httpx.AsyncClient(headers={"User-Agent": fetch_module.user_agent()})) as client:
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

    def unlink_orphans(store: Store, files: list[str], payloads: list[str]) -> list[str]:
        """Delete the files a purge orphaned; returns the ones that could not be removed from disk."""
        failures = []
        for root, paths in ((settings.papers_dir, files), (settings.payloads_dir, payloads)):
            safe_root = root.resolve()
            for relative in paths:
                if root == settings.papers_dir and recovery_history.RETAINED.fullmatch(relative):
                    if not recovery_history.remove_retained(store, root, relative):
                        failures.append(relative)
                    continue
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
        store = store_of(request)
        try:
            files, payloads = store.purge_research(research_id)
        except recovery_history.FrozenDependencyUnreadable as exc:
            return JSONResponse({"code": exc.code, "detail": exc.detail}, status_code=409)
        return {"deleted": True, "files_not_removed": unlink_orphans(store, files, payloads)}

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
                                    seed_mode=body.seed_mode,
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
            return JSONResponse(status_code=422, content={"code": "credential_test_failed",
                "detail": f"The key was not saved. {result['detail']}", "service": key.service,
                "kind": result.get("kind", "unknown"), "http_status": result.get("http_status"),
                "reset_at": result.get("reset_at")})
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
                "options": embeddings.options(await request.app.state.local_tools.snapshot(refresh),
                                              request.app.state.builtin.option())}

    @app.get("/api/semantic-search")
    async def get_semantic_search(request: Request) -> dict[str, Any]:
        return await semantic_search_view(request)

    @app.put("/api/semantic-search")
    async def put_semantic_search(body: SemanticChoice, request: Request) -> dict[str, Any]:
        """Save the embedding provider for later answers; a provider or model not offered now is refused, never replaced."""
        tools = await request.app.state.local_tools.snapshot(refresh=body.provider in ("ollama", "lm_studio"))
        option = next(o for o in embeddings.options(tools, request.app.state.builtin.option()) if o["provider"] == body.provider)
        if not option["available"]:
            raise HTTPException(422, option["reason"])
        model = None
        if body.provider != "off":
            model = body.model or (option["models"][0] if body.provider in ("gemini", "builtin", "openai") else None)
            if model is None:
                raise HTTPException(422, "Choose an embedding model")
            if model not in option["models"]:
                raise HTTPException(422, f"Model '{model}' is not offered by {body.provider}")
        store_of(request).set_setting("semantic_search", {"provider": body.provider, "model": model})
        return await semantic_search_view(request)

    # The built-in embedding model (slice 21, D103): install on request, cancel, remove; POSIX only in this slice.
    def service_error(exc: ServiceError) -> HTTPException:
        return HTTPException(409, {"reason": exc.code, "message": str(exc)})

    @app.get("/api/semantic-search/builtin")
    async def builtin_status(request: Request) -> dict[str, Any]:
        return await request.app.state.builtin.status()

    @app.post("/api/semantic-search/builtin/install", status_code=202)
    async def install_builtin(request: Request) -> dict[str, Any]:
        try:
            return {"job": await request.app.state.builtin.install()}
        except ServiceError as exc:
            raise service_error(exc) from exc

    @app.post("/api/semantic-search/builtin/cancel")
    async def cancel_builtin(request: Request) -> dict[str, Any]:
        try:
            return {"job": await request.app.state.builtin.cancel()}
        except ServiceError as exc:
            raise service_error(exc) from exc

    @app.delete("/api/semantic-search/builtin")
    async def remove_builtin(request: Request) -> dict[str, Any]:
        try:
            await request.app.state.builtin.remove()
        except ServiceError as exc:
            raise service_error(exc) from exc
        return await request.app.state.builtin.status()

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

    @app.put("/api/researches/{research_id}/english-question")
    async def save_english_question(research_id: str, body: EnglishQuestion, request: Request) -> dict[str, Any]:
        """The English sentence the built-in model reads for the current scope revision, written once (slice 21).

        No scope revision is opened and no decision goes stale. With `use_question` the server writes the question as
        it is, with no language check: the way out when the language rule reads an English question as not English."""
        store = store_of(request)
        scope = store.scope(research_id)
        if english_question.is_english(scope["question"], scope.get("language_hint")):
            # The built-in model reads an English question as written and would never read the sentence (D103).
            raise HTTPException(422, "The question is already read as English; the built-in model uses it as written")
        if body.use_question:
            if body.text is not None:
                raise HTTPException(422, "Send either the sentence or use_question, not both")
            store.save_english_question(research_id, body.expected_version, None)
        else:
            text = " ".join((body.text or "").split())
            if not text:
                raise HTTPException(422, "Write one English sentence")
            if not english_question.is_english(text):
                raise HTTPException(422, "The sentence does not read as English")
            store.save_english_question(research_id, body.expected_version, text)
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
        if body.kind in ("fulltext_fetch", "fulltext_adjudication"):
            raise LegacyInspectionPolicyRemoved("legacy_inspection_policy_removed")
        if body.kind == "discovery" and scope["source_scope"] == "attached":
            raise HTTPException(422, "Academic search is not part of this research's source scope")
        if body.kind == "discovery" and scope["seed_mode"] == "uploaded_seed":
            seed_status = store.seed_status(research_id, scope)
            if seed_status != "ready":
                raise HTTPException(422 if seed_status == "missing" else 409,
                                    "Choose a readable PDF seed before searching" if seed_status == "missing"
                                    else "The selected PDF changed; select it again before searching")
        if body.kind in ("answer", "pdf_collection") and not store.included_works(research_id):
            # A research whose search finished may still ask: its answer records that no work was included when
            # it started (SW22, D106). A PDF collection keeps the refusal.
            if not (body.kind == "answer" and store.discovery_completed(research_id)):
                raise HTTPException(422, "Include at least one source before generating an answer")
        budget = TEST_EFFORT_BUDGETS[scope["effort"]].__dict__
        if body.kind == "discovery":
            # The criterion proposal before the first search (D78) and the abstract stage's two runs over the
            # works the read limit reaches (D81) are given on top of the preset, so the preset itself — which an
            # answer run reads — is what it always was (slice 06 review).
            # SUGGESTION_CALLS is the one term-suggestion call the user may ask for on the approval card (D82); a
            # run that never asks spends none of it.
            extra = CRITERION_CALLS + SUGGESTION_CALLS + ADVICE_CALLS + abstract_stage.model_calls(
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
                          "chain_plan_room": CHAIN_PLAN_ROOM[scope["effort"]],
                          # D229: the rule version and the sources are frozen too; a run queued without them is v1, OpenAlex alone.
                          "chain_rule_version": chaining.RULE_VERSION, "chain_sources": list(chaining.SOURCES)}
            budget = budget | {"max_model_calls": budget["max_model_calls"] + extra} | chain
            if settings.fulltext_fetch == "auto":
                # The full text is fetched inside this run, beside its screening, with the room a retrieval run
                # would have had (slice 17a); the mode is frozen here, so a run keeps the path it was queued with.
                budget["fulltext_fetch"] = fulltext.overlap_budget(scope["effort"])
            budget = small_batch.freeze_budget(budget, scope["effort"], settings.fulltext_adjudication)
            budget["fast_path"] = fast_path.freeze_budget(budget, scope["effort"])
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
        elif body.kind == "answer":
            from deixis.workflow.fast_answer import answer_run_budget
            budget = answer_run_budget(store, research_id, scope)
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

    @app.post("/api/runs/{run_id}/skip-equations")
    async def skip_equation_reading(run_id: str, request: Request) -> dict[str, Any]:
        """"Answer now with PDF text": the answer run reads no further PDF's equations; its text layer is used."""
        store = store_of(request)
        run = store.run(run_id)
        if run["kind"] != "answer" or run["status"] not in ("running", "pause_requested") or run["stage"] != "inspection":
            raise HTTPException(409, "This run is not reading PDFs or equations now.")
        store.request_equation_skip(run_id)
        return store.run(run_id)

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
            # A queued run paused here never passes the worker; a person's waiting files are looked at from here
            # (slice 18b, decision 5). With a paused run in the research the helper opens nothing.
            worker.flow.queue_person_reading(run["research_id"])
        elif action == "resume" and status == "paused" and run["pause_reason"] == "protocol_approval_needed":
            # There is no resuming past the approval: the run would freeze a protocol the user never saw (SW2.6).
            raise HTTPException(409, "Approve or correct the proposed protocol before resuming this run")
        elif (action == "resume" and status == "paused" and run["pause_reason"] == "search_query_failed"
              and not (run.get("error") or {}).get("retries_left", 1)):
            # The model was asked as many times as a run allows; the way on is the code's query or a new revision.
            raise HTTPException(409, "The model has had its second try; search with the code's query or revise the scope")
        elif action == "resume" and status == "paused":
            run = store.resume_run(run_id)
            worker.wake()
        elif action == "cancel" and status in ("queued", "running", "pause_requested", "paused"):
            # The files this run held — those its plan took, or every waiting one while its plan was not frozen —
            # are `unread` from this same write and are not asked again until the person says so; a file added after
            # its plan froze was never the run's, and the queue opens its reading now (slice 18b, decision 5).
            run = store.update_run(run_id, event="run_cancelled", status="cancelled", pause_reason="user_cancelled")
            worker.flow.queue_person_reading(run["research_id"])
            worker.wake()
            if worker.current_run_id == run_id and run["kind"] not in ("table_fill", "lineage_links"):
                # Roles may use different connections; only the running step's connection has a call to interrupt.
                # Candidate decomposition and kill-search calls are sequential, so both kinds interrupt here.
                if run["kind"] == "kill_search":
                    CandidateStore(store).sync_search_outcome(run_id)
                for adapter in request.app.state.adapters.values():
                    await adapter.cancel()
        else:
            raise HTTPException(409, f"Cannot {action} a run in status {status}")
        if run["kind"] == "kill_search":
            CandidateStore(store).sync_search_outcome(run_id)
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

    # ---- the audit sample, the PRISMA-S export and the depth text of an sw research (slice 20) ------------------
    @app.get("/api/researches/{research_id}/audit")
    async def audit(research_id: str, request: Request) -> dict[str, Any]:
        store = store_of(request)
        store.research(research_id)
        return audit_rules.audit_view(store, research_id)

    @app.get("/api/researches/{research_id}/audit/{source_version_id}")
    async def audit_row(research_id: str, source_version_id: str, request: Request) -> dict[str, Any]:
        store = store_of(request)
        store.research(research_id)
        return audit_rules.audit_detail(store, research_id, source_version_id)

    @app.post("/api/researches/{research_id}/audit/{source_version_id}/decision")
    async def audit_decision(research_id: str, source_version_id: str, body: AuditDecision,
                             request: Request) -> dict[str, Any]:
        store = store_of(request)
        store.research(research_id)
        return human_queue.audit_decide(store, research_id, source_version_id, body.decision, body.note,
                                        body.audit_token)

    @app.post("/api/researches/{research_id}/audit/{source_version_id}/undo")
    async def audit_undo(research_id: str, source_version_id: str, body: AuditUndo, request: Request) -> dict[str, Any]:
        store = store_of(request)
        store.research(research_id)
        return human_queue.audit_undo(store, research_id, source_version_id, body.audit_token)

    @app.get("/api/researches/{research_id}/prisma-s")
    async def prisma_s_export(research_id: str, request: Request, format: Literal["md", "json"] = "json") -> Response:
        store = store_of(request)
        store.research(research_id)
        data = prisma_s.export(store, research_id)
        name = f"deixis-prisma-s-{research_id}-r{data['scope_revision']}"
        if format == "md":
            return Response(prisma_s.markdown(data), media_type="text/markdown; charset=utf-8",
                            headers={"Content-Disposition": f'attachment; filename="{name}.md"'})
        return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="{name}.json"'})

    @app.get("/api/researches/{research_id}/answers/{answer_id}/method")
    async def answer_method(research_id: str, answer_id: str, request: Request) -> dict[str, Any]:
        """The Method box under an answer: searches, selection, extraction, limits and evidence base, from stored rows."""
        from deixis.workflow import method_summary
        store = store_of(request)
        store.research(research_id)
        try:
            return method_summary.method_summary(store, research_id, answer_id)
        except method_summary.UnknownAnswer:
            raise HTTPException(404, "Answer not found") from None

    @app.get("/api/effort-limits")
    async def effort_limits_view() -> dict[str, Any]:
        return effort_limits()

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
        try:
            purged, files, payloads = store.purge_sources(research_id, body.source_version_ids)
        except recovery_history.FrozenDependencyUnreadable as exc:
            return JSONResponse({"code": exc.code, "detail": exc.detail}, status_code=409)
        return {"deleted": purged, "files_not_removed": unlink_orphans(store, files, payloads)}

    @app.post("/api/researches/{research_id}/uploads", status_code=201)
    async def upload(research_id: str, request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
        store = store_of(request)
        if store.scope(research_id)["source_scope"] == "academic":
            raise HTTPException(422, "Attached files are not part of this research's source scope")
        with disk_full_refused():
            settings.papers_dir.mkdir(parents=True, exist_ok=True)
            staged = await store_upload(file, settings.papers_dir)
            placement = await file_restore.restore_file(store, settings.papers_dir, settings.recovery_dir, staged,
                                                        caller="upload", research_id=research_id)
            sha, size, path = placement.sha256, placement.size, placement.path
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
            read = await text_retry.read_verified(store, settings.papers_dir, settings.recovery_dir,
                storage_path=path.name, sha256=sha, byte_size=size, lock=True)
            extraction = read.extraction
            title = re.sub(r"[_\s]+", " ", Path(filename).stem).strip()[:200] or "Uploaded PDF"
            svid = store.create_upload_source(title)
            store.add_asset_with_pages(svid, sha, size, path.name, "user_upload", None, filename,
                                       extraction, pdf.EXTRACTION_VERSION, pdf.chunk_page,
                                       input_observation=read.observation)
        store.add_to_corpus(research_id, svid, "user_upload", selection_state="included", selection_origin="user")
        return research_view(store, research_id) | {"uploaded_source_version_id": svid,
            "file_restore": store.file_restore_view(placement.operation_id) if placement.operation_id else None}

    @app.post("/api/researches/{research_id}/sources/{source_version_id}/uploads", status_code=201)
    async def upload_to_source(research_id: str, source_version_id: str, request: Request,
                               file: UploadFile = File(...)) -> dict[str, Any]:
        """Attach a user-selected PDF to an existing bibliographic source version."""
        store = store_of(request)
        store.research(research_id)
        if not store.is_active_member(research_id, source_version_id):
            raise HTTPException(404, "Source is not part of this research")
        with disk_full_refused():
            settings.papers_dir.mkdir(parents=True, exist_ok=True)
            staged = await store_upload(file, settings.papers_dir)
            placement = await file_restore.restore_file(store, settings.papers_dir, settings.recovery_dir, staged,
                                                        caller="source_upload", research_id=research_id)
            sha, size, path = placement.sha256, placement.size, placement.path
        if not store.conn.execute(
            "SELECT 1 FROM source_assets WHERE source_version_id = ? AND sha256 = ? AND removed_at IS NULL",
            (source_version_id, sha)
        ).fetchone():
            if store.has_asset(source_version_id):
                raise PdfInUse(source_version_id)
            read = await text_retry.read_verified(store, settings.papers_dir, settings.recovery_dir,
                storage_path=path.name, sha256=sha, byte_size=size, lock=True)
            extraction = read.extraction
            filename = Path(file.filename or "document.pdf").name
            flow = request.app.state.worker.flow
            with db.transaction(store.conn):
                asset_id = store.add_asset_with_pages(source_version_id, sha, size, path.name, "user_upload", None,
                                                      filename, extraction, pdf.EXTRACTION_VERSION, pdf.chunk_page,
                                                      input_observation=read.observation)
                # The same code, request and queue as a file confirmed from the waiting list (slice 18b,
                # decision 10), with the same check whether the work may be read at all.
                flow.attach_person_file(research_id, source_version_id, asset_id)
                flow.queue_person_reading(research_id)
            request.app.state.worker.wake()
        return research_view(store, research_id) | {
            "file_restore": store.file_restore_view(placement.operation_id) if placement.operation_id else None}

    @app.post("/api/researches/{research_id}/uploads/match")
    async def match_uploads(research_id: str, request: Request, files: list[UploadFile] = File(...)) -> dict[str, Any]:
        """Propose which included source each dropped PDF belongs to; nothing is attached until the user confirms (D49).

        An `sw` research proposes a work among those waiting for a PDF, the latest plan's and those included since,
        with its versions for the person to pick from and what the confirmation checks (slice 18a)."""
        store = store_of(request)
        store.research(research_id)
        return await match_waiting(store, research_id, files, request.app.state.worker.flow)

    async def match_waiting(store: Store, research_id: str, files: list[UploadFile], request_flow: Any) -> dict[str, Any]:
        revision = store.research(research_id)["current_scope_revision"]
        with disk_full_refused():
            settings.papers_dir.mkdir(parents=True, exist_ok=True)
        matches = []
        for file in files[:50]:
            staged = await store_upload(file, settings.papers_dir)
            sha = staged.sha256
            try:
                extraction = await text_retry.drained_thread(pdf.extract_pdf, staged.path, MATCH_TEXT_CHARS)
            finally:
                file_restore.cleanup(staged.path)
            # What the confirmation sends back and is checked against (decision 5): the file, the revision, the work.
            matches.append({"filename": Path(file.filename or "document.pdf").name, "sha256": sha, "scope_revision": revision,
                            "page_count": extraction.page_count or None,
                            "has_text_layer": None if extraction.status == "failed" else bool(extraction.pages),
                            **pdf_waiting.propose(store, research_id, "\n".join(p.text for p in extraction.pages))})
        # What a confirmation would lead to for each work shown, so the panel can say it before the person confirms.
        works = [w for m in matches for w in ([m["work"]] if m["work"] else m.get("candidates") or [])]
        outcomes = request_flow.attach_outcomes(research_id, sorted({w["work_id"] for w in works}))
        for work in works:
            for version in work["versions"]:
                version["after_attach"] = outcomes.get(work["work_id"], {}).get(version["source_version_id"],
                                                                                person_reading.NOT_ELIGIBLE)
        return {"matches": matches, "scope_revision": revision}

    # ---- the works of an sw research waiting for the person's PDF (slice 18a) ----------------------
    @app.get("/api/researches/{research_id}/waiting")
    async def waiting_list(research_id: str, request: Request) -> dict[str, Any]:
        store = store_of(request)
        store.research(research_id)
        view = pdf_waiting.waiting_view(store, research_id)
        # The files the person added and what became of each (slice 18b, decision 9).
        return view | {"files": person_reading.files_view(
            store, research_id, request.app.state.worker.flow.person_reading_on(research_id))}

    @app.post("/api/researches/{research_id}/waiting/uploads", status_code=201)
    async def attach_waiting_pdf(research_id: str, request: Request, file: UploadFile = File(...),
                                 work_id: str = Form(...), source_version_id: str = Form(...),
                                 scope_revision: int = Form(...), versions_digest: str = Form(...),
                                 sha256: str = Form(...)) -> dict[str, Any]:
        """Add a dropped file to the version the person picked, once what the match showed still holds (decision 5).

        The file is added as a person's upload always was, with the code and reading request slice 18b writes for it.
        Checked before the text is extracted, and again with the write, so nothing that moved meanwhile slips in."""
        store = store_of(request)
        store.research(research_id)
        with disk_full_refused():
            settings.papers_dir.mkdir(parents=True, exist_ok=True)
            staged = await store_upload(file, settings.papers_dir)
            try:
                bound = dict(work_id=work_id, source_version_id=source_version_id, scope_revision=scope_revision,
                             versions_digest=versions_digest, sha256=sha256, uploaded_sha256=staged.sha256)
                pdf_waiting.check_attach(store, research_id, **bound)
                placement = await file_restore.restore_file(store, settings.papers_dir, settings.recovery_dir, staged,
                                                            caller="waiting_upload", research_id=research_id)
            finally:
                file_restore.cleanup(staged.path)
            sha, size, path = placement.sha256, placement.size, placement.path
        read = await text_retry.read_verified(store, settings.papers_dir, settings.recovery_dir,
            storage_path=path.name, sha256=sha, byte_size=size, lock=True)
        extraction = read.extraction
        filename = Path(file.filename or "document.pdf").name
        flow = request.app.state.worker.flow
        with db.transaction(store.conn):
            pdf_waiting.check_attach(store, research_id, **bound)
            asset_id = store.add_asset_with_pages(source_version_id, sha, size, path.name, "user_upload", None,
                                                  filename, extraction, pdf.EXTRACTION_VERSION, pdf.chunk_page,
                                                  input_observation=read.observation)
            # The code on the chosen version and, when the work may be read, the reading request and its run, in the
            # same write as the file (slice 18b, decisions 1–5).
            reading = flow.attach_person_file(research_id, source_version_id, asset_id)
            store._event(research_id, "waiting_pdf_attached", {"source_version_id": source_version_id,
                                                               "work_id": work_id, "asset_id": asset_id,
                                                               "reading": reading})
            flow.queue_person_reading(research_id)
        request.app.state.worker.wake()
        return research_view(store, research_id) | {"attached": {"source_version_id": source_version_id,
                                                                  "asset_id": asset_id, "reading": reading},
            "file_restore": store.file_restore_view(placement.operation_id) if placement.operation_id else None}

    @app.post("/api/researches/{research_id}/waiting/requests/{request_id}/retry")
    async def retry_person_reading(research_id: str, request_id: str, request: Request) -> dict[str, Any]:
        """Read a person's file again after a reading that did not decide it (slice 18b, decision 6).

        The request waits again with its attempt counted, and the reading run is opened when nothing else holds the
        research; the view shows only the run that was opened."""
        store = store_of(request)
        store.research(research_id)
        person_reading.retry(store, research_id, request_id)
        run = request.app.state.worker.flow.queue_person_reading(research_id)
        request.app.state.worker.wake()
        return {"run": run}

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
                core_key=os.environ.get("CORE_API_KEY"), xml_fetcher=request.app.state.fetch_xml,
                recovery_dir=settings.recovery_dir,
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
        if candidate["provider"] == "europepmc":
            # Europe PMC's full text is XML drawn as a PDF by code (SW21); it is attached only by the version rule.
            raise HTTPException(422, "A Europe PMC full text is attached only when its version matches this record")
        if store.has_asset(source_version_id):
            raise HTTPException(409, "This source already has a PDF")
        result = await acquisition.attach_confirmed_candidate(store, source_version_id, candidate, settings.papers_dir,
                                                              request.app.state.fetch_pdf, research_id=research_id,
                                                              recovery_dir=settings.recovery_dir)
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
        payload_path = f"{db.new_id('zot')}.json"
        with disk_full_refused():
            settings.payloads_dir.mkdir(parents=True, exist_ok=True)
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
                notes.append({"title": item.record.title, "note": item.pdf_problem, "vars": item.pdf_problem_vars})
            if item.pdf_key is None or store.has_asset(svid):
                continue
            try:
                data = await zotero.pdf_bytes(http, library, item.pdf_key, request.app.state.fetch_pdf)
            except zotero.ZoteroError as exc:
                notes.append({"title": item.record.title, "note": "PDF not added: {reason}", "vars": {"reason": str(exc)}})
                continue
            sha = hashlib.sha256(data).hexdigest()
            try:
                with disk_full_refused():
                    settings.papers_dir.mkdir(parents=True, exist_ok=True)
                    placement = await file_restore.store_pdf_file(store, settings.papers_dir, settings.recovery_dir, data,
                                                                  caller="zotero_import", research_id=research_id)
                    read = await text_retry.read_verified(store, settings.papers_dir, settings.recovery_dir,
                        storage_path=placement.path.name, sha256=sha, byte_size=len(data), lock=True)
            except (text_retry.FileBusy, file_restore.FileRestoreRefused) as exc:
                notes.append({"title": item.record.title, "note": "PDF not added: {reason}", "vars": {"reason": str(exc)}})
                continue
            path = placement.path
            extraction = read.extraction
            # The file is the user's own copy from their library, like an upload; retrieved_from names the attachment.
            store.add_asset_with_pages(svid, sha, len(data), path.name, "user_upload", f"zotero:{library.source}:{item.pdf_key}",
                                       item.pdf_filename, extraction, pdf.EXTRACTION_VERSION, pdf.chunk_page,
                                       input_observation=read.observation)
            if read.observation is not None and read.observation["integrity"] != "verified":
                notes.append({"title": item.record.title, "note": "PDF input not verified: " + text_retry.INPUT_CHANGED})
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
                   if not store.has_pdf_text(store.answer_version(research_id, head) or head) and not store.has_asset(head)]
        added, notes = 0, []
        for svid in missing:
            source = store.source(svid)
            item = await zotero.find_pdf(http, library, source["doi"], source["title"])
            if item is None:
                continue
            if item.pdf_key is None:
                notes.append({"title": source["title"], "note": item.pdf_problem, "vars": item.pdf_problem_vars})
                continue
            try:
                data = await zotero.pdf_bytes(http, library, item.pdf_key, request.app.state.fetch_pdf)
            except zotero.ZoteroError as exc:
                notes.append({"title": source["title"], "note": "PDF not added: {reason}", "vars": {"reason": str(exc)}})
                continue
            sha = hashlib.sha256(data).hexdigest()
            try:
                with disk_full_refused():
                    settings.papers_dir.mkdir(parents=True, exist_ok=True)
                    placement = await file_restore.store_pdf_file(store, settings.papers_dir, settings.recovery_dir, data,
                                                                  caller="zotero_pdfs", research_id=research_id)
                    read = await text_retry.read_verified(store, settings.papers_dir, settings.recovery_dir,
                        storage_path=placement.path.name, sha256=sha, byte_size=len(data), lock=True)
            except (text_retry.FileBusy, file_restore.FileRestoreRefused) as exc:
                notes.append({"title": source["title"], "note": "PDF not added: {reason}", "vars": {"reason": str(exc)}})
                continue
            path = placement.path
            extraction = read.extraction
            store.add_asset_with_pages(svid, sha, len(data), path.name, "user_upload", f"zotero:{library.source}:{item.pdf_key}",
                                       item.pdf_filename, extraction, pdf.EXTRACTION_VERSION, pdf.chunk_page,
                                       input_observation=read.observation)
            if read.observation is not None and read.observation["integrity"] != "verified":
                notes.append({"title": source["title"], "note": "PDF input not verified: " + text_retry.INPUT_CHANGED})
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
        # A file restore replaces the bytes atomically under the same name (D208); no-cache makes the browser check the
        # ETag on every open, so a copy it read before the restore is never shown from its cache.
        return FileResponse(path, media_type="application/pdf", headers={"Content-Disposition": "inline", "Cache-Control": "no-cache"})

    @app.get("/api/researches/{research_id}/assets/{asset_id}/text")
    async def get_asset_text(research_id: str, asset_id: str, request: Request,
                             extraction_id: str | None = None) -> dict[str, Any]:
        store = store_of(request)
        store.research(research_id)
        asset = store.asset(asset_id)
        svid = asset["source_version_id"]
        cited = store.was_member(research_id, svid) and store.research_cites_asset(research_id, asset_id)
        accessible = asset["removed_at"] is None and (store.is_active_member(research_id, svid) or cited)
        if extraction_id is not None:
            accessible = (asset["removed_at"] is None and store.is_active_member(research_id, svid)) or (
                asset["removal_reason"] in (None, "replaced") and cited)
        if not accessible:
            raise HTTPException(404, "Asset is not part of this research")
        source = store.source(asset["source_version_id"])
        if extraction_id is None:
            extraction = store.conn.execute("SELECT * FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'",
                                            (asset_id,)).fetchone()
            passages = [p for p in store.passages_for(svid) if p["asset_id"] == asset_id]
        else:
            extraction = store.conn.execute(
                "SELECT * FROM asset_extractions WHERE id = ? AND asset_id = ? AND outcome IN ('current', 'superseded')",
                (extraction_id, asset_id),
            ).fetchone()
            if extraction is None:
                raise HTTPException(404, "Extraction is not part of this asset")
            passages = [dict(row) for row in store.conn.execute(
                "SELECT * FROM passages WHERE asset_id = ? AND extraction_version = ? ORDER BY kind, physical_page, rowid",
                (asset_id, extraction["extraction_version"]),
            )]
        version = extraction["extraction_version"] if extraction else asset["extraction_version"]
        to_check = equations_to_check(store, asset_id, version)
        source_numbers = {version: latex_numbers(store, asset_id, version)
                          for version in {p["extraction_version"] for p in passages if p["text_source"] == "latex_source"}}
        return {
            "occurrence": occurrence_view(store, asset, dict(extraction) if extraction else None, extraction_version=version),
            "asset": {k: asset[k] for k in ("id", "extraction_status", "page_count", "origin", "byte_size", "original_filename")}
            | {"rendition": store.asset_rendition(asset_id)},
            "passages": [{k: passage[k] for k in ("id", "kind", "text", "physical_page", "printed_label", "extraction_version", "payload_ref", "text_source")}
                         | {"equations_to_check": to_check.get(passage["physical_page"], 0) if passage["text_source"] == "marker" else 0,
                            "source_equations": chunk_numbers(source_numbers[passage["extraction_version"]], passage["physical_page"],
                                                              passage["payload_ref"]) if passage["text_source"] == "latex_source" else []}
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
        from deixis.workflow import recovery

        store = store_of(request)
        asset = asset_in_use(store, research_id, source_version_id, asset_id)
        current = store.conn.execute(
            "SELECT diagnostic_only, error FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'",
            (asset_id,)).fetchone()
        if current and current["diagnostic_only"] and current["error"] == pdf.ERROR_PASSWORD:
            raise HTTPException(422, "This PDF requires a password; OCR cannot read it")
        if asset["extraction_status"] == "succeeded":
            raise HTTPException(422, "Text was extracted from every page of this PDF")
        status = await asyncio.to_thread(ocr.tesseract_status)
        if not status["available"]:
            raise HTTPException(422, status["reason"])
        version = ocr.target_version(recovery.text_base(asset["extraction_version"]), status["version"], status["languages"])
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
        asset = asset_in_use(store, research_id, source_version_id, asset_id)
        with disk_full_refused():
            settings.papers_dir.mkdir(parents=True, exist_ok=True)
            staged = await store_upload(file, settings.papers_dir)
            placement = await file_restore.restore_file(store, settings.papers_dir, settings.recovery_dir, staged,
                                                        caller="replace_pdf", research_id=research_id)
            sha, size, path = placement.sha256, placement.size, placement.path
        if sha == asset["sha256"]:
            if placement.outcome == "reused":
                raise SameFile(asset_id)
            return research_view(store, research_id) | {"file_restore": store.file_restore_view(placement.operation_id)}
        read = await text_retry.read_verified(store, settings.papers_dir, settings.recovery_dir,
            storage_path=path.name, sha256=sha, byte_size=size, lock=True)
        extraction = read.extraction
        store.replace_asset(asset_id, sha, size, path.name, "user_upload", None, Path(file.filename or "document.pdf").name,
                            extraction, pdf.EXTRACTION_VERSION, pdf.chunk_page, input_observation=read.observation)
        return research_view(store, research_id) | {
            "file_restore": store.file_restore_view(placement.operation_id) if placement.operation_id else None}

    @app.post("/api/researches/{research_id}/sources/{source_version_id}/assets/{asset_id}/extractions")
    async def reextract_asset(research_id: str, source_version_id: str, asset_id: str, request: Request,
                              response: Response, body: TextRetryRequest | None = None) -> dict[str, Any]:
        """Extract the PDF in use again with the current extractor; it becomes current only if it loses no visible text (D45)."""
        store = store_of(request)
        asset = asset_in_use(store, research_id, source_version_id, asset_id)
        if body is not None:
            try:
                with disk_full_refused():
                    result = await text_retry.execute_text_retry(store, settings, asset_id=asset_id,
                        expected_extraction_id=body.expected_current_extraction_id, idempotency_key=body.idempotency_key,
                        research_id=research_id, source_version_id=source_version_id)
            except RunInProgress:
                return JSONResponse({"detail": "A research using this source has an active run; try again when it ends.",
                                     "code": "run_active"}, status_code=409)
            finally:
                request.app.state.worker.wake()
            response.status_code = 202 if result["lifecycle"] == "running" else 200
            return {**research_view(store, research_id), "recovery": result}
        text_retry.precheck(settings.papers_dir, asset["storage_path"])
        if (asset["extraction_version"] or "").split("+")[0] == pdf.EXTRACTION_VERSION:  # equations read on it too (D52)
            reason = {"succeeded": "already_current", "pending": "pending"}.get(asset["extraction_status"], "retry_available")
            return {**research_view(store, research_id), "reextraction": {"asset_id": asset_id, "outcome": "unchanged", "reason": reason}}
        root = settings.papers_dir.resolve()
        path = (root / asset["storage_path"]).resolve()
        if not path.is_relative_to(root) or not path.exists():
            raise HTTPException(404, "File missing")
        with disk_full_refused():
            with text_retry.file_lock(settings.recovery_dir, asset["sha256"]):
                read = await text_retry.read_verified(store, settings.papers_dir, settings.recovery_dir,
                    storage_path=asset["storage_path"], sha256=asset["sha256"], byte_size=asset["byte_size"], lock=False)
                if read.observation is not None and read.observation["integrity"] != "verified":
                    return JSONResponse({"code": "input_not_verified", "detail":
                        "The stored PDF does not match its recorded hash; upload it again to repair it, then extract its text again."},
                        status_code=409)
                report = store.reextract_asset(asset_id, read.extraction, pdf.EXTRACTION_VERSION, pdf.chunk_page,
                                              input_observation=read.observation)
        return {**research_view(store, research_id), "reextraction": report}

    @app.get("/api/researches/{research_id}/sources/{source_version_id}/assets/{asset_id}/text-retry")
    async def text_retry_capability(research_id: str, source_version_id: str, asset_id: str, request: Request) -> dict[str, Any]:
        from deixis.workflow.recovery_view import text_recovery

        store = store_of(request)
        store.flush_text_retry_interruptions()
        asset = asset_in_use(store, research_id, source_version_id, asset_id)
        return text_recovery(store, asset, source_version_id, settings.papers_dir)

    @app.get("/api/researches/{research_id}/sources/{source_version_id}/assets/{asset_id}/recovery-history")
    async def asset_recovery_history(research_id: str, source_version_id: str, asset_id: str, request: Request) -> dict[str, Any]:
        from deixis.workflow.recovery_view import recovery_history

        store = store_of(request)
        asset = asset_in_use(store, research_id, source_version_id, asset_id)
        return recovery_history(store, asset)

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

    # ---- owner-requested reviews --------------------------------------------------------------
    def review_stores(request):
        store = store_of(request)
        reader = ReviewReader(store, ReportStore(store))
        return store, reader, ReviewStore(store.conn, reader)

    def review_of(request, research_id, review_id):
        store, reader, reviews = review_stores(request)
        review = reviews._review(review_id)
        if review["research_id"] != research_id:
            raise NotFound(review_id)
        return store, reader, reviews, review, reviews.snapshot(review["snapshot_id"])

    def review_finding_of(request, research_id, review_id, finding_id):
        store, reader, reviews, review, saved = review_of(request, research_id, review_id)
        finding = next((f for f in reviews.findings(review_id) if f["id"] == finding_id), None)
        if finding is None:
            raise NotFound(finding_id)
        return store, reader, reviews, review, saved, finding

    async def review_model(request, body):
        adapter = request.app.state.adapters.get(body.connection)
        if adapter is None:
            raise HTTPException(422, f"Model connection '{body.connection}' is not available")
        health = await adapter.health()
        check_offered(health.get("models"), body.connection, body.model, body.reasoning_effort)
        return adapter, health

    def review_plan(request, research_id, body, adapter):
        _, reader, _ = review_stores(request)
        try:
            content, markers = build_snapshot(reader, research_id, body.target_kind, body.target_id)
        except NotReviewable as exc:
            raise ReviewRefusal(422, "not_reviewable", str(exc)) from exc
        model = (body.connection, body.model, body.reasoning_effort)
        plan = review_run.plan_groups("rvs_" + "0" * 20, content, body.focus, body.owner_note, model,
            request.app.state.package, CAPABILITIES, enforces_schema=adapter.enforces_schema,
            max_request_chars=REVIEW_BUDGET_TOKENS * 4)
        if not plan["groups"]:
            raise ReviewRefusal(422, "nothing_reviewable", "No claim fits the review input bounds.",
                                not_reviewed=plan["not_reviewed"])
        digest = sha256_hex(content)
        fingerprint = review_run.preview_fingerprint(digest, model, body.focus, body.owner_note,
                                                     request.app.state.package.package_hash, plan)
        return content, markers, plan, digest, fingerprint

    def review_card(request, research_id, review_id):
        store, reader, reviews, review, saved = review_of(request, research_id, review_id)
        run = store.run(review["run_id"])
        steps = [dict(r) | {"output": json.loads(r["output_json"]) if r["output_json"] else None}
                 for r in store.conn.execute("SELECT * FROM run_steps WHERE run_id = ? ORDER BY rowid", (run["id"],))]
        inputs = {r["id"]: json.loads(r["payload_json"]) for r in store.conn.execute(
            "SELECT id, payload_json FROM step_inputs WHERE run_id = ?", (run["id"],))}
        sessions = [dict(r) for r in store.conn.execute("SELECT * FROM model_sessions WHERE run_id = ? ORDER BY rowid", (run["id"],))]
        findings = reviews.findings(review_id)
        decisions = {f["id"]: reviews.decisions(f["id"]) for f in findings}
        content = saved["content"]
        live = (reader.report_claims(content["target_id"]) if content["target_kind"] == "report" else
                reader.answer_claims(content["target_id"]) if content["target_kind"] == "answer" else [])
        fingerprints = {}
        if content["target_kind"] == "report":
            fingerprints = {f["finding"]["target_ref"]["ref"]: review_run.dependency_fingerprint(reader, content, f["finding"]["target_ref"]["ref"])
                            for f in findings if f["finding"]["target_ref"]["kind"] == "claim"}
        return review_run.review_read_model(review, saved, run, steps, inputs, sessions, findings, decisions,
            stale_reasons(reader, saved), live_claims={c["id"]: c for c in live}, dependency_fingerprints=fingerprints)

    review_path = "/api/researches/{research_id}/reviews"
    finding_path = review_path + "/{review_id}/findings/{finding_id}"

    @app.post(review_path + "/preview")
    async def preview_owner_review(research_id: str, body: ReviewPreviewRequest, request: Request):
        adapter, health = await review_model(request, body)
        content, _, plan, digest, fingerprint = review_plan(request, research_id, body, adapter)
        return review_run.preview_numbers(content, plan) | {"snapshot_sha256": digest, "preview_fingerprint": fingerprint,
            "connection": body.connection, "connection_display_name": health.get("display_name", body.connection)}

    @app.post(review_path, status_code=202)
    async def start_owner_review(research_id: str, body: ReviewStartRequest, request: Request,
                                 idempotency_key: str = Header(min_length=1, max_length=200)):
        from datetime import datetime, timedelta
        store, _, reviews = review_stores(request)
        store.research(research_id)
        key = f"review:{research_id}:{idempotency_key}"
        digest = review_run.command_hash("start", research_id, body.target_kind, body.target_id, body.model_dump())

        def replay():
            old = store.conn.execute("SELECT id FROM runs WHERE idempotency_key = ?", (key,)).fetchone()
            if old is None:
                return None
            run = store.run(old["id"])
            if run["target"].get("request_hash") != digest:
                raise ReviewConflict("idempotency_key_reused", "This key was used for a different review request.")
            row = store.conn.execute("SELECT * FROM owner_reviews WHERE run_id = ?", (run["id"],)).fetchone()
            return {"review": dict(row), "run": run}

        if old := replay():
            return old
        adapter, _ = await review_model(request, body)
        with db.transaction(store.conn):
            if old := replay():
                return old
            if store.conn.execute("SELECT 1 FROM runs WHERE research_id = ? AND status IN ('queued','running','pause_requested')",
                                  (research_id,)).fetchone():
                raise ReviewConflict("run_active", "This research has an active run. Wait for it to stop before starting a review.")
            content, markers, plan, snapshot_hash, fingerprint = review_plan(request, research_id, body, adapter)
            if snapshot_hash != body.snapshot_sha256:
                raise ReviewConflict("target_changed", "The target changed after the preview. Preview it again.")
            if fingerprint != body.preview_fingerprint:
                raise ReviewConflict("preview_changed", "The review request or package changed after the preview. Preview it again.")
            deadline = (datetime.fromisoformat(db.now()) + timedelta(seconds=review_run.REVIEW_DEADLINE_SECONDS)).isoformat(timespec="milliseconds")
            run = store.create_run(research_id, "review", review_run.review_budget(len(plan["groups"])), key,
                {"snapshot_sha256": snapshot_hash, "preview_fingerprint": fingerprint, "request_hash": digest,
                 "plan": plan, "target_kind": body.target_kind, "target_id": body.target_id,
                 "skill_package_hash": request.app.state.package.package_hash, "deadline_at": deadline})
            snapshot_id = reviews.add_snapshot(content, markers)
            review = reviews.create_review(research_id, snapshot_id, run["id"], focus=body.focus, owner_note=body.owner_note,
                requested_connection=body.connection, requested_model=body.model, requested_effort=body.reasoning_effort, idempotency_key=key)
            reviews.set_not_reviewed(review["id"], plan["not_reviewed"])
        request.app.state.worker.wake()
        return {"review": reviews._review(review["id"]), "run": run}

    @app.get(review_path)
    async def list_owner_reviews(research_id: str, target_kind: str, target_id: str, request: Request):
        _, _, reviews = review_stores(request)
        cards = [review_card(request, research_id, r["id"]) for r in reviews.reviews_for_target(research_id, target_kind, target_id)]
        return [{k: card[k] for k in ("id", "run_id", "state", "pause_reason", "failure_reason", "outcome_unknown",
                                     "requested_model", "created_at", "finding_count", "open_finding_count")} for card in cards]

    @app.get(review_path + "/{review_id}")
    async def get_owner_review(research_id: str, review_id: str, request: Request):
        return review_card(request, research_id, review_id)

    @app.post(finding_path + "/decisions")
    async def decide_owner_review_finding(research_id: str, review_id: str, finding_id: str,
                                         body: ReviewDecisionRequest, request: Request,
                                         idempotency_key: str = Header(min_length=1, max_length=200)):
        store = store_of(request)
        if body.decision == "dismissed" and body.reason is None:
            raise HTTPException(422, "A dismissed finding needs a reason.")
        with db.transaction(store.conn):
            _, _, reviews, _, saved, _ = review_finding_of(request, research_id, review_id, finding_id)
            digest = review_run.command_hash("decision", research_id, saved["target_kind"], saved["target_id"],
                                             body.model_dump() | {"finding_id": finding_id})
            decision = reviews.add_decision(finding_id, body.decision, body.reason,
                idempotency_key=f"review-decision:{research_id}:{idempotency_key}", request_hash=digest, expected_ordinal=body.expected_ordinal)
        return {"decision": decision, "no_change_made": saved["target_kind"] in {"answer", "candidate"} and body.decision == "accepted"}

    @app.post(finding_path + "/apply")
    async def apply_owner_review_finding(research_id: str, review_id: str, finding_id: str,
                                        body: ReviewApplyRequest, request: Request,
                                        idempotency_key: str = Header(min_length=1, max_length=200)):
        store = store_of(request)
        key = f"review-apply:{finding_id}:{idempotency_key}"
        with db.transaction(store.conn):
            _, reader, reviews, _, saved, finding = review_finding_of(request, research_id, review_id, finding_id)
            ref = finding["finding"]["target_ref"]
            if saved["target_kind"] != "report" or ref["kind"] != "claim":
                raise ReviewRefusal(422, "not_applicable", "Only a report-claim finding can be applied through this editor.")
            digest = review_run.command_hash("apply", research_id, saved["target_kind"], saved["target_id"],
                                             body.model_dump() | {"finding_id": finding_id})
            decision = reviews.decision_request(key, digest)
            if decision is None:
                content = saved["content"]
                if review_run.dependency_fingerprint(reader, content, ref["ref"]) != body.dependency_fingerprint:
                    raise ReviewConflict("dependencies_changed", "The claim or its evidence dependencies changed. Reopen the editor before saving.")
                claim = next(c for c in content["claims"] if c["claim_ref"] == ref["ref"])
                revision_id = ReportStore(store).edit_claim(research_id, content["target_id"], claim["claim_id"],
                    text=body.text, restore_from=None, note=body.note, expected_version=body.expected_version,
                    idempotency_key=key, link_ids=body.link_ids)
                decision = reviews.add_decision(finding_id, "accepted", applied_ref=revision_id, idempotency_key=key, request_hash=digest)
            revision = next(r for r in reader.report_claim_revisions(finding["finding"]["target"]["record_id"]) if r["id"] == decision["applied_ref"])
        return {"decision": decision, "revision": revision,
                "applied_matches_suggestion": applied_matches_suggestion(finding["finding"], revision["text"])}

    # ---- evidence tables (P5, D37) -------------------------------------------------------------
    def tables_of(request: Request) -> TableStore:
        return TableStore(store_of(request))

    def reports_of(request: Request) -> ReportStore:
        return ReportStore(store_of(request))

    @app.exception_handler(InvalidTableInput)
    async def invalid_table_input(_: Request, exc: InvalidTableInput):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(InvalidLineageInput)
    async def invalid_lineage_input(_: Request, exc: InvalidLineageInput):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(InvalidCandidateInput)
    async def invalid_candidate_input(_: Request, exc: InvalidCandidateInput):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    def candidate_of(request: Request, research_id: str, candidate_id: str) -> tuple[CandidateStore, dict]:
        cs = CandidateStore(store_of(request))
        cs.store.research(research_id)
        candidate = cs._pair(research_id, candidate_id)
        # Read endpoints deliberately perform this idempotent write: worker
        # recovery or an outside-flow failure can leave a nonterminal search behind.
        for version in cs.versions(candidate_id):
            for search in cs.searches(version["id"]):
                cs.sync_search_outcome(search["run_id"])
        return cs, candidate

    def decoded_candidate_row(row: dict) -> dict:
        return {key.removesuffix("_json"): json.loads(value) if value is not None else None
                for key, value in row.items() if key.endswith("_json")} | {
                    key: value for key, value in row.items() if not key.endswith("_json") and key != "idempotency_key"}

    def candidate_run_view(run: dict) -> dict:
        return {key: run[key] for key in ("id", "kind", "status", "pause_reason")} | {
            "error_code": (run.get("error") or {}).get("code") or (run["pause_reason"] if run["status"] == "failed" else None)}

    def candidate_card(request: Request, research_id: str, candidate_id: str) -> dict:
        cs, candidate = candidate_of(request, research_id, candidate_id)
        versions = cs.versions(candidate_id)
        current = next((v for v in versions if v["version"] == candidate["current_version"]), None)
        searches = []
        for version in versions:
            for search in cs.searches(version["id"]):
                searches.append({key: search[key] for key in ("id", "candidate_version_id", "run_id", "outcome", "created_at")}
                                | {"version": version["version"], "counts": {k: search[k] for k in ("found", "kept", "rank_cut", "duplicates")}})
        active = cs.runs(candidate_id, active_only=True, limit=1)
        return decoded_candidate_row(candidate) | {
            "versions": [decoded_candidate_row(v) for v in versions],
            "current_version_id": current["id"] if current else None,
            "owner_decisions": cs.overrides(current["id"]) if current else [], "searches": searches,
            "status": cs.candidate_status(current["id"]) if current else None,
            "active_run": candidate_run_view(active[0]) if active else None,
            "runs": [candidate_run_view(r) for r in cs.runs(candidate_id)], "decompose_budget": decompose_budget()}

    def candidate_search_of(cs: CandidateStore, candidate_id: str, kill_search_id: str) -> tuple[dict, dict]:
        search = cs.kill_search(kill_search_id)
        version = cs.version(search["candidate_version_id"])
        if version["candidate_id"] != candidate_id:
            raise NotFound(kill_search_id)
        return search, version

    def candidate_planner(request: Request) -> KillSearchPlanner:
        return KillSearchPlanner(store_of(request), request.app.state.package.package_hash)

    candidates_path = "/api/researches/{research_id}/candidates"
    candidate_path = candidates_path + "/{candidate_id}"
    kill_search_path = candidate_path + "/kill-searches/{kill_search_id}"

    @app.post(candidates_path, status_code=201, response_model=CandidateCard)
    async def open_candidate(research_id: str,
                             body: Annotated[OwnerTextCandidate | GapCandidate, Field(discriminator="origin")],
                             request: Request, idempotency_key: str | None = Header(default=None, max_length=200)) -> dict:
        cs = CandidateStore(store_of(request))
        cs.store.research(research_id)
        if body.origin == "owner_text":
            candidate = cs.open_from_owner_text(research_id, body.text,
                f"{research_id}:{idempotency_key}" if idempotency_key else None)
        else:
            candidate = cs.open_from_gap(research_id, body.report_id, body.gap_row_id)
        return candidate_card(request, research_id, candidate["id"])

    @app.get(candidates_path, response_model=list[CandidateListItem])
    async def list_candidates(research_id: str, request: Request) -> list[dict]:
        cs = CandidateStore(store_of(request))
        result = []
        for candidate in cs.candidates(research_id):
            card = candidate_card(request, research_id, candidate["id"])
            current = next((v for v in card["versions"] if v["id"] == card["current_version_id"]), None)
            result.append({key: card[key] for key in ("id", "origin", "origin_report_id", "origin_gap_row_id",
                          "gap_kind", "origin_changed", "current_version", "trashed_at")} | {
                "claim_statement": current["claim_statement"] if current else None,
                "status": card["status"]["computed"] if card["status"] else None,
                "owner": card["status"]["owner"] if card["status"] else None,
                "active_run_id": card["active_run"]["id"] if card["active_run"] else None})
        return result

    @app.get(candidate_path, response_model=CandidateCard)
    async def get_candidate(research_id: str, candidate_id: str, request: Request) -> dict:
        return candidate_card(request, research_id, candidate_id)

    @app.post(candidate_path + "/versions", status_code=201, response_model=CandidateCard)
    async def edit_candidate(research_id: str, candidate_id: str, body: CandidateVersionRequest,
                             request: Request, idempotency_key: str | None = Header(default=None, max_length=200)) -> dict:
        cs, _ = candidate_of(request, research_id, candidate_id)
        cs.add_version(research_id, candidate_id, **body.model_dump(), origin="human_edit", step_input_id=None,
                       idempotency_key=f"{research_id}:{candidate_id}:{idempotency_key}" if idempotency_key else None)
        return candidate_card(request, research_id, candidate_id)

    @app.post(candidate_path + "/decompose", status_code=202)
    async def decompose_candidate(research_id: str, candidate_id: str, request: Request,
                                  body: CandidateRequest | None = None,
                                  idempotency_key: str | None = Header(default=None, max_length=200)) -> dict:
        store = store_of(request)
        store.research(research_id)
        # The Part A helper owns the decompose:<research>:<candidate>:<key> namespace.
        run = request_decomposition(store, research_id, candidate_id, idempotency_key,
                                    skill_package_hash=request.app.state.package.package_hash)
        request.app.state.worker.wake()
        return run

    @app.get(candidate_path + "/kill-search/plan")
    async def candidate_kill_search_plan(research_id: str, candidate_id: str, request: Request) -> dict:
        candidate_of(request, research_id, candidate_id)
        return candidate_planner(request).preview(research_id, candidate_id)

    @app.post(candidate_path + "/kill-search", status_code=202)
    async def start_candidate_kill_search(research_id: str, candidate_id: str, body: CandidateKillSearchRequest,
                                        request: Request,
                                        idempotency_key: str | None = Header(default=None, max_length=200)) -> dict:
        store_of(request).research(research_id)
        # The planner owns the killsearch:<research>:<candidate>:<key> namespace and replay check.
        run = candidate_planner(request).request_run(research_id, candidate_id, body.preview_fingerprint, idempotency_key)
        request.app.state.worker.wake()
        return run

    @app.get(kill_search_path, response_model=CandidateMatrix)
    async def candidate_matrix(research_id: str, candidate_id: str, kill_search_id: str, request: Request) -> dict:
        cs, _ = candidate_of(request, research_id, candidate_id)
        search, version = candidate_search_of(cs, candidate_id, kill_search_id)
        hits = []
        for hit in cs.hits(kill_search_id):
            if not hit["kept"]:
                continue
            source = cs.store.source(hit["source_version_id"])
            hits.append({key: hit[key] for key in ("source_version_id", "reading_depth", "assessment_state",
                         "work_relevance", "note")} | {"rank": hit["rank_key"],
                         "states_whole_claim": bool(hit["states_whole_claim"]) if hit["states_whole_claim"] is not None else None,
                         "source": {key: source[key] for key in ("title", "year", "venue", "doi", "version_label")}})
        cells = {}
        for cell in cs.cells(kill_search_id):
            cells.setdefault(cell["source_version_id"], {})[cell["element_id"]] = cell
        summary = cs.store.existing_step(search["run_id"], "kill_search_summary")
        return {"search": decoded_candidate_row(search),
                "queries": [{key: q[key] for key in ("position", "provider", "query_text", "status", "record_count", "error_code")}
                            for q in cs.queries(kill_search_id)],
                "counts": {key: search[key] for key in ("found", "kept", "rank_cut", "duplicates")},
                "hits": hits, "cells": cells, "evidence": cs.evidence(kill_search_id),
                "summary": summary["output"] if summary else None, "search_status": cs.search_status(kill_search_id),
                "candidate_version_id": version["id"], "version": version["version"], "kill_search_id": kill_search_id,
                "is_latest_search_of_version": cs.searches(version["id"])[-1]["id"] == kill_search_id}

    @app.get(kill_search_path + "/hits/{source_version_id}", response_model=CandidateEvidence)
    async def candidate_hit_evidence(research_id: str, candidate_id: str, kill_search_id: str,
                                     source_version_id: str, request: Request) -> dict:
        cs, _ = candidate_of(request, research_id, candidate_id)
        candidate_search_of(cs, candidate_id, kill_search_id)
        return candidate_evidence(cs.store, research_id, candidate_id, kill_search_id, source_version_id)

    @app.post(candidate_path + "/versions/{version_id}/owner-decision", status_code=201, response_model=CandidateCard)
    async def candidate_owner_decision(research_id: str, candidate_id: str, version_id: str,
                                       body: CandidateOwnerDecision, request: Request) -> dict:
        cs, _ = candidate_of(request, research_id, candidate_id)
        if cs.version(version_id)["candidate_id"] != candidate_id:
            raise NotFound(version_id)
        # Owner decisions are append-only; this route intentionally has no Idempotency-Key.
        cs.record_owner_decision(research_id, version_id, body.status, body.reason)
        return candidate_card(request, research_id, candidate_id)

    def lineage_of(request: Request) -> LineagePlanner:
        flow = request.app.state.worker.flow
        return LineagePlanner(store_of(request), flow.lineage_step_input, flow.lineage_message_chars,
                              flow.deps.package.package_hash)

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

    @app.post(table_path + "/lineage/columns")
    async def add_development_columns(research_id: str, table_id: str, body: ExpectedVersion, request: Request,
                                      idempotency_key: str | None = Header(default=None, max_length=200)) -> dict[str, Any]:
        tables = tables_of(request)
        tables.add_development_columns(research_id, table_id, body.expected_version, idempotency_key)
        return tables.table_view(research_id, table_id)

    @app.get(table_path + "/lineage/plan")
    async def lineage_plan(research_id: str, table_id: str, request: Request,
                           retry_failed: bool = False) -> dict[str, Any]:
        return lineage_of(request).preview(research_id, table_id, retry_failed)

    @app.post(table_path + "/lineage/runs", status_code=202)
    async def lineage_run(research_id: str, table_id: str, body: LineageRunRequest, request: Request,
                          idempotency_key: str | None = Header(default=None, max_length=200)) -> dict[str, Any]:
        run = lineage_of(request).request_run(research_id, table_id, body.preview_fingerprint,
                                              body.retry_failed, idempotency_key)
        request.app.state.worker.wake()
        return run

    @app.get(table_path + "/lineage")
    async def lineage_view(research_id: str, table_id: str, request: Request) -> dict[str, Any]:
        return LineageView(store_of(request)).view(research_id, table_id)

    @app.get(table_path + "/lineage/baseline")
    async def lineage_baseline(research_id: str, table_id: str, request: Request) -> dict[str, Any]:
        return LineageView(store_of(request)).baseline(research_id, table_id)

    @app.post(table_path + "/lineage/links", status_code=201)
    async def lineage_add_link(research_id: str, table_id: str, body: LineageLinkAdd, request: Request,
                               idempotency_key: str | None = Header(default=None, max_length=200)) -> dict[str, Any]:
        store = store_of(request)
        TableStore(store)._table(research_id, table_id)
        fields = body.model_dump(exclude={"from_source_version_id", "to_source_version_id"})
        LineageStore(store).add_link(research_id, table_id, body.from_source_version_id, body.to_source_version_id,
                                     **fields, idempotency_key=idempotency_key,
                                     stale_revisions=stale_link_revisions(store, table_id))
        return LineageView(store).view(research_id, table_id)

    @app.put(table_path + "/lineage/links/{link_id}")
    async def lineage_edit_link(research_id: str, table_id: str, link_id: str, body: LineageLinkEdit, request: Request,
                                idempotency_key: str | None = Header(default=None, max_length=200)) -> dict[str, Any]:
        store = store_of(request)
        TableStore(store)._table(research_id, table_id)
        LineageStore(store).edit_link(research_id, table_id, link_id, **body.model_dump(),
                                      idempotency_key=idempotency_key,
                                      stale_revisions=stale_link_revisions(store, table_id))
        return LineageView(store).view(research_id, table_id)

    @app.delete(table_path + "/lineage/links/{link_id}")
    async def lineage_remove_link(research_id: str, table_id: str, link_id: str, request: Request,
                                  expected_version: int = Query(ge=0), based_on_revision_id: str = Query(min_length=1),
                                  note: str | None = Query(default=None, max_length=2000),
                                  idempotency_key: str | None = Header(default=None, max_length=200)) -> dict[str, Any]:
        store = store_of(request)
        TableStore(store)._table(research_id, table_id)
        LineageStore(store).remove_link(research_id, table_id, link_id, note, based_on_revision_id,
                                        expected_version, idempotency_key)
        return LineageView(store).view(research_id, table_id)

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
        run = reports_of(request).request_report(research_id, body.table_id, idempotency_key,
                                                continue_with_failed=body.continue_with_failed)
        request.app.state.worker.wake()
        return run

    @app.post("/api/researches/{research_id}/study-table", status_code=202)
    async def start_study_table(research_id: str, request: Request,
                                idempotency_key: str | None = Header(default=None, max_length=200)) -> dict[str, Any]:
        """Manual rebuild of the study table: propose columns, add them and fill, as a chain of the usual runs."""
        run = report_pipeline.start(store_of(request), research_id, idempotency_key)
        request.app.state.worker.wake()
        return run

    @app.get("/api/researches/{research_id}/reports/{report_id}/gaps")
    async def get_report_gaps(research_id: str, report_id: str, request: Request) -> list[dict[str, Any]]:
        return report_gaps_view(store_of(request), research_id, report_id)

    @app.get("/api/researches/{research_id}/reports/{report_id}")
    async def get_report(research_id: str, report_id: str, request: Request) -> dict[str, Any]:
        return report_view(store_of(request), research_id, report_id)

    @app.post("/api/researches/{research_id}/reports/{report_id}/check-edits")
    async def check_report_edits(research_id: str, report_id: str, request: Request) -> dict[str, Any]:
        store = store_of(request)
        ReportStore(store).check_edits(research_id, report_id)
        return report_view(store, research_id, report_id)

    @app.get("/api/researches/{research_id}/reports/{report_id}/export")
    async def export_report(research_id: str, report_id: str, request: Request,
                            fmt: Literal["markdown", "latex"] = Query("markdown", alias="format")) -> Response:
        if fmt == "latex":
            data, name, notes = latex_export.export_latex(store_of(request), research_id, report_id)
            return Response(data, media_type=latex_export.MEDIA_TYPE,
                            headers={"Content-Disposition": f'attachment; filename="{name}"',
                                     "X-Deixis-Export-Notes": str(notes)})
        text, name = report_export.export_markdown(store_of(request), research_id, report_id)
        return Response(text, media_type=report_export.MEDIA_TYPES[fmt],
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/researches/{research_id}/reports")
    async def list_reports(research_id: str, request: Request) -> list[dict[str, Any]]:
        return research_view(store_of(request), research_id)["reportRuns"]

    @app.put("/api/researches/{research_id}/reports/{report_id}/claims/{claim_id}")
    async def edit_report_claim(research_id: str, report_id: str, claim_id: str, body: ReportClaimEdit,
                                request: Request,
                                idempotency_key: str | None = Header(default=None, max_length=200)) -> dict[str, Any]:
        store = store_of(request)
        ReportStore(store).edit_claim(research_id, report_id, claim_id, text=body.text, restore_from=body.restore_from,
                                      note=body.note, expected_version=body.expected_version,
                                      idempotency_key=idempotency_key, link_ids=body.link_ids)
        return report_view(store, research_id, report_id)

    @app.post("/api/researches/{research_id}/reports/{report_id}/sections/{section_id}/acknowledge-changes")
    async def acknowledge_report_changes(research_id: str, report_id: str, section_id: str,
                                         body: ReportChangesAcknowledgement, request: Request) -> dict[str, Any]:
        store = store_of(request)
        ReportStore(store).acknowledge_changes(research_id, report_id, section_id, body.change_keys)
        return report_view(store, research_id, report_id)

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
