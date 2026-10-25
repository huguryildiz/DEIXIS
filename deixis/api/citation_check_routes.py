"""Verify Citations, V1 (D86), V2 (D96) and V3 (D99): give a draft and its bibliography, read back the occurrences,
entries and pairs, look the entries up, attach the person's PDF to an entry, acquire each entry's text, freeze the
passage plan, preview it with its cost range, check the planned pairs with a model, export the result, delete the
draft. Only `POST …/check` calls a model. The application middleware enforces loopback, Origin, CSRF and the body size
(`upload_limit`; the entry upload ends in `/uploads`, so it has the PDF limit).

Resolution is an explicit `POST …/resolve`, not a run step: it is a handful of OpenAlex lookups with no model call,
like the Library's reference import, and it is idempotent by entry status (a resolved or unresolved entry is never
asked again), so it needs no run, scope revision or `operation_key` to avoid sending twice.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

from fastapi import File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from deixis.api.app import UploadRefused, disk_full_refused, store_upload
from deixis.config import Settings
from deixis.documents import draft_parse, pdf
from deixis.imports import bibtex_ris
from deixis.workflow.answer import citation_check
from deixis.workflow.read import file_restore, text_retry


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refreeze: bool = False  # only the person's explicit request writes a new plan revision


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_revision: int  # the frozen revision the person previewed; another one is refused
    connection: str | None = Field(None, max_length=100)
    model: str | None = Field(None, max_length=200)  # none: the literature model in Settings, as the preview prices
    reasoning_effort: str | None = Field(None, max_length=50)


def _parse(data: bytes | None, filename: str | None, text: str | None, bib: bytes | None, bib_name: str | None):
    fmt, body = draft_parse.read_draft(data, filename, text)
    draft = draft_parse.parse_draft(fmt, body)
    if bib is None:
        return draft, None
    bib_fmt, entries, errors = bibtex_ris.read_file(bib, bib_name)
    return draft, (bib_fmt, entries, [e.view() for e in errors], bib_name)


def register_citation_check_routes(app, settings: Settings,
                                   unlink: Callable[[Any, list[str], list[str]], list[str]] | None = None) -> None:
    def refused(exc: citation_check.PlanRefused) -> JSONResponse:
        return JSONResponse({"code": exc.code, "detail": exc.detail, **exc.extra}, status_code=409)

    @app.post("/api/citation-checks", status_code=201)
    async def create_check(request: Request, file: UploadFile | None = File(None), text: str | None = Form(None),
                           bibliography: UploadFile | None = File(None)) -> dict[str, Any]:
        """A draft (a file, or pasted text) and an optional BibTeX or RIS file: every marker, entry and pair stored,
        nothing looked up yet."""
        store = request.app.state.store
        data = await file.read(draft_parse.MAX_DRAFT_BYTES + 1) if file is not None else None
        bib = await bibliography.read(bibtex_ris.MAX_FILE_BYTES + 1) if bibliography is not None else None
        try:
            # Off the event loop: reading a large draft is CPU work and touches no shared state.
            draft, bib_read = await asyncio.to_thread(_parse, data, file.filename if file else None, text, bib,
                                                      bibliography.filename if bibliography else None)
        except draft_parse.DraftRefused as exc:
            raise UploadRefused(exc.status, exc.code, exc.detail) from None
        except bibtex_ris.ImportRefused as exc:
            raise UploadRefused(exc.status, exc.code, exc.detail) from None
        if bib_read is not None and not bib_read[1]:
            raise UploadRefused(422, "import_no_entries", "No entry in the reference file could be read")
        with disk_full_refused():
            draft_id = citation_check.create(store, draft, file.filename if file else None, bib_read)
        return citation_check.view(store, draft_id)

    @app.get("/api/citation-checks")
    async def list_checks(request: Request) -> list[dict[str, Any]]:
        """Every draft, newest first, so the Library tool can open an earlier check again."""
        return citation_check.drafts(request.app.state.store)

    @app.get("/api/citation-checks/{draft_id}")
    async def get_check(draft_id: str, request: Request) -> dict[str, Any]:
        return citation_check.view(request.app.state.store, draft_id)

    @app.post("/api/citation-checks/{draft_id}/resolve")
    async def resolve_check(draft_id: str, request: Request) -> dict[str, Any]:
        """Look up the entries not yet resolved; a second call asks only for the ones whose lookup failed."""
        store = request.app.state.store
        with disk_full_refused():
            counts = await citation_check.resolve(store, request.app.state.http, settings.payloads_dir,
                                                  settings.contact_email, draft_id)
        return {**citation_check.view(store, draft_id), "resolved_now": counts}

    @app.post("/api/citation-checks/{draft_id}/entries/{entry_id}/uploads", status_code=201)
    async def upload_entry_pdf(draft_id: str, entry_id: str, request: Request,
                               file: UploadFile = File(...)) -> dict[str, Any]:
        """The person's own PDF for one resolved entry, read first when the entry's text is acquired. The checks of
        every upload apply (size, `%PDF-`, extraction in the PDF child process), and `identity.check` reads its first
        pages against the entry's record: `unconfirmed` is kept and shown as a flag, never dropped or hidden."""
        store = request.app.state.store
        research_id = citation_check.draft_row(store, draft_id)["research_id"]
        entry = citation_check.entry_row(store, draft_id, entry_id)
        if entry["resolution_status"] != "resolved" or entry["resolved_source_version_id"] is None:
            raise UploadRefused(409, "entry_not_resolved", "Only an entry resolved to a record can take a PDF")
        with disk_full_refused():
            settings.papers_dir.mkdir(parents=True, exist_ok=True)
            staged = await store_upload(file, settings.papers_dir)
            try:
                placement = await file_restore.restore_file(store, settings.papers_dir, settings.recovery_dir, staged,
                                                            caller="upload", research_id=research_id)
            finally:
                file_restore.cleanup(staged.path)
            sha, size, path = placement.sha256, placement.size, placement.path
        existing = store.conn.execute(
            "SELECT a.source_version_id FROM source_assets a JOIN source_versions s ON s.id = a.source_version_id"
            " WHERE a.sha256 = ? AND a.removed_at IS NULL AND s.origin = 'user_upload' LIMIT 1", (sha,)).fetchone()
        if existing:
            svid = existing["source_version_id"]
        else:
            read = await text_retry.read_verified(store, settings.papers_dir, settings.recovery_dir,
                                                  storage_path=path.name, sha256=sha, byte_size=size, lock=True)
            filename = Path(file.filename or "document.pdf").name
            svid = store.create_upload_source(Path(filename).stem.strip()[:200] or "Uploaded PDF")
            store.add_asset_with_pages(svid, sha, size, path.name, "user_upload", None, filename, read.extraction,
                                       pdf.EXTRACTION_VERSION, pdf.chunk_page, input_observation=read.observation)
        checked = citation_check.pdf_identity(store, svid, entry["resolved_source_version_id"])
        citation_check.link_upload(store, draft_id, entry_id, svid, checked["result"] if checked else "unconfirmed")
        return citation_check.view(store, draft_id)

    @app.post("/api/citation-checks/{draft_id}/acquire")
    async def acquire_text(draft_id: str, request: Request) -> dict[str, Any]:
        """Decide the text of every resolved entry still pending: the person's PDF, else a stored PDF, else the open-access
        path research runs use, else the abstract. A spent OpenAlex budget pauses it and keeps what was decided."""
        state = request.app.state
        with disk_full_refused():
            outcome = await citation_check.acquire(state.store, state.http, settings, state.fetch_pdf, state.fetch_xml,
                                                   draft_id)
        return {**citation_check.view(state.store, draft_id), "acquired_now": outcome}

    @app.post("/api/citation-checks/{draft_id}/plan")
    async def freeze_plan(draft_id: str, request: Request, body: PlanRequest | None = None):
        """Freeze the passage plan the preview and the check read; a second call returns it unchanged unless the person
        asks to freeze again (`refreeze`), which keeps every pair's earlier plan."""
        store = request.app.state.store
        try:
            frozen = citation_check.freeze_plan(store, draft_id, refreeze=bool(body and body.refreeze))
        except citation_check.PlanRefused as exc:
            return refused(exc)
        return {**citation_check.view(store, draft_id), "frozen": frozen}

    @app.get("/api/citation-checks/{draft_id}/preview")
    async def preview(draft_id: str, request: Request, connection: str | None = Query(None, max_length=100),
                      model: str | None = Query(None, max_length=200),
                      reasoning_effort: str | None = Query(None, max_length=50)):
        """The frozen plan's selected and out-of-cap pairs, the counters and the V3 step's cost range for the model
        named here, else the literature default in Settings. Reading it freezes and changes nothing."""
        store = request.app.state.store
        if model is not None:
            choice = {"connection": connection, "model": model, "reasoning_effort": reasoning_effort}
        else:
            default = store.setting("literature") or {}
            choice = {"connection": default.get("model_connection"), "model": default.get("model"),
                      "reasoning_effort": default.get("reasoning_effort")}
        try:
            return citation_check.preview(store, draft_id, choice)
        except citation_check.PlanRefused as exc:
            return refused(exc)

    @app.post("/api/citation-checks/{draft_id}/check")
    async def run_check(draft_id: str, body: CheckRequest, request: Request):
        """Send each planned pair not checked yet, in draft order, to the named model (else the literature model in
        Settings), and store the code's verdict. Refused when the plan is not the previewed revision or went stale,
        and when no model is named anywhere. A provider failure or a person's stop pauses the run; the next call goes
        on from the first pair without a stored check and never sends a checked pair again."""
        store = request.app.state.store
        choice = {"connection": body.connection, "model": body.model, "reasoning_effort": body.reasoning_effort}
        try:
            outcome = await citation_check.check(store, request.app.state.worker.flow, draft_id, body.plan_revision,
                                                 choice if body.model is not None else None)
        except citation_check.PlanRefused as exc:
            return refused(exc)
        return {**citation_check.view(store, draft_id), "checked": outcome}

    @app.get("/api/citation-checks/{draft_id}/export")
    async def export_check(draft_id: str, request: Request, format: str = Query("csv", pattern="^(csv|md)$")):
        """One row per pair, the pairs that could not be checked included, as CSV or Markdown."""
        text = citation_check.export(request.app.state.store, draft_id, format)
        media = "text/csv" if format == "csv" else "text/markdown"
        return Response(text, media_type=f"{media}; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="citation-check-{draft_id}.{format}"'})

    @app.delete("/api/citation-checks/{draft_id}")
    async def delete_check(draft_id: str, request: Request) -> dict[str, Any]:
        store = request.app.state.store
        files, payloads = citation_check.delete(store, draft_id)
        return {"deleted": True, "files_not_removed": unlink(store, files, payloads) if unlink else files + payloads}
