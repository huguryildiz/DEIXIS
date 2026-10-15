"""Library-owned items (UI parity S19a, F14): save works, upload a PDF into the Library, export a bibliography for any
set of works, and start a research over a set; import a Zotero collection or a BibTeX / RIS file into the Library
(S19b). The application middleware enforces loopback, Origin and CSRF.

Versions are never merged: a saved item is one source version, an exported entry is one stored record, and a new
research gets the one version per work that adding a Library work to a research already picks (D41).
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Literal

from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from deixis.api.app import (CreateResearch, UploadRefused, ZoteroImport, attach_zotero_pdf, checked_research_models,
                            create_research_row, disk_full_refused, store_upload)
from deixis.config import Settings
from deixis.documents import pdf, upload_record
from deixis.providers.registry import CONNECTORS
from deixis.imports import bibtex_ris
from deixis.providers import zotero
from deixis.storage.db import new_id
from deixis.workflow import bibliography, file_restore, intent, library_items, text_retry
from deixis.storage.db import transaction
from deixis.workflow.store import Store
from deixis.workflow.views import library_version_to_add, library_view, library_work_view, research_view

MAX_SET = 500


class SaveItems(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_version_ids: list[str] = Field(min_length=1, max_length=MAX_SET)


class BibliographyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["bibtex", "ris"] = "bibtex"
    # A Library row exports the record it shows; a source version exports itself.
    work_ids: list[str] = Field(default_factory=list, max_length=MAX_SET)
    source_version_ids: list[str] = Field(default_factory=list, max_length=MAX_SET)
    every_work: bool = False  # Settings → Data: the whole Library, with no selection


class NewResearchFromSet(CreateResearch):
    """A new research whose sources are these Library works, chosen by the person (scope `attached`)."""
    source_scope: Literal["attached"] = "attached"
    work_ids: list[str] = Field(min_length=1, max_length=MAX_SET)


def _library_work(store: Store, work_id: str) -> dict[str, Any]:
    work = library_work_view(store, work_id)
    if work is None:
        raise HTTPException(404, f"Work is not in the library: {work_id}")
    return work


def _export_records(store: Store, body: BibliographyRequest) -> list[dict[str, Any]]:
    svids: list[str] = []
    if body.work_ids:
        shown = {e["work_id"]: e for e in library_view(store)["entries"]}
        for work_id in body.work_ids:
            if work_id not in shown:
                raise HTTPException(404, f"Work is not in the library: {work_id}")
            svids.append(shown[work_id]["representative_source_version_id"])
    svids.extend(body.source_version_ids)
    records = []
    for svid in dict.fromkeys(svids):
        record = store.source(svid)
        arxiv = store.conn.execute("SELECT value FROM identifier_mappings WHERE source_version_id = ? AND scheme = 'arxiv'"
                                   " LIMIT 1", (svid,)).fetchone()
        records.append(record | {"arxiv_id": arxiv["value"] if arxiv else None})
    return records


def register_library_routes(app, settings: Settings) -> None:
    def store_of(request: Request) -> Store:
        return request.app.state.store

    @app.post("/api/library/items", status_code=201)
    async def save_items(body: SaveItems, request: Request) -> dict[str, Any]:
        store = store_of(request)
        added = library_items.save(store, body.source_version_ids, "saved")
        return {"saved": added, "already_saved": [s for s in dict.fromkeys(body.source_version_ids) if s not in added],
                "library": library_view(store)}

    @app.post("/api/library/uploads", status_code=201)
    async def upload(request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
        """A PDF into the Library only; no research holds it until the person adds it to one."""
        store = store_of(request)
        with disk_full_refused():
            settings.papers_dir.mkdir(parents=True, exist_ok=True)
            staged = await store_upload(file, settings.papers_dir)
            placement = await file_restore.restore_file(store, settings.papers_dir, settings.recovery_dir, staged,
                                                        caller="upload", research_id=None)
            sha, size, path = placement.sha256, placement.size, placement.path
        # The same file uploaded before (into a research or the Library) is the same uploaded record.
        existing = store.conn.execute(
            "SELECT a.source_version_id FROM source_assets a JOIN source_versions s ON s.id = a.source_version_id"
            " WHERE a.sha256 = ? AND a.removed_at IS NULL AND s.origin = 'user_upload' LIMIT 1", (sha,)
        ).fetchone()
        if existing:
            svid = existing["source_version_id"]
        else:
            filename = Path(file.filename or "document.pdf").name
            read = await text_retry.read_verified(store, settings.papers_dir, settings.recovery_dir,
                                                  storage_path=path.name, sha256=sha, byte_size=size, lock=True)
            title = re.sub(r"[_\s]+", " ", Path(filename).stem).strip()[:200] or "Uploaded PDF"
            svid = store.create_upload_source(title)
            store.add_asset_with_pages(svid, sha, size, path.name, "user_upload", None, filename,
                                       read.extraction, pdf.EXTRACTION_VERSION, pdf.chunk_page,
                                       input_observation=read.observation)
            await upload_record.identify(store, request.app.state.http, svid, CONNECTORS["openalex"].api_key(),
                                         settings.contact_email)
        # The same file saved before stays the item it was; the answer says so, so the screen never counts it as added.
        already_saved = not library_items.save(store, [svid], "upload")
        return {"source_version_id": svid, "work_id": store.source(svid)["work_id"], "already_saved": already_saved,
                "library": library_view(store),
                "file_restore": store.file_restore_view(placement.operation_id) if placement.operation_id else None}

    @app.post("/api/library/bibliography")
    async def export_bibliography(body: BibliographyRequest, request: Request) -> Response:
        if body.every_work:
            body = body.model_copy(update={"work_ids": [e["work_id"] for e in library_view(store_of(request))["entries"]]})
        if not body.work_ids and not body.source_version_ids:
            raise HTTPException(422, "The Library has no works" if body.every_work else "Choose at least one work")
        records = _export_records(store_of(request), body)
        text = bibliography.to_bibtex(records) if body.format == "bibtex" else bibliography.to_ris(records)
        name = f"deixis-library.{'bib' if body.format == 'bibtex' else 'ris'}"
        return Response(text, media_type=bibliography.MEDIA_TYPES[body.format],
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.post("/api/library/researches", status_code=201)
    async def new_research_from_set(body: NewResearchFromSet, request: Request) -> dict[str, Any]:
        store = store_of(request)
        work_ids = list(dict.fromkeys(body.work_ids))
        for work_id in work_ids:  # an unknown work is refused before the model lists are asked
            _library_work(store, work_id)
        connections = await checked_research_models(request.app.state.adapters, CreateResearch(
            **body.model_dump(exclude={"work_ids"})))
        # No await from here on: the works are read again (a purge may have run during the model checks), and the
        # research, its sources and its study table are written in one transaction, or nothing is.
        versions = [library_version_to_add(_library_work(store, work_id))["source_version_id"] for work_id in work_ids]
        with transaction(store.conn):
            rid = create_research_row(store, body, *connections)
            for svid in versions:
                store.add_to_corpus(rid, svid, "library", selection_state="included", selection_origin="user")
            intent.attached_ingested(store, rid)
        return research_view(store, rid) | {"added_source_version_ids": versions}

    @app.post("/api/library/zotero-imports", status_code=201)
    async def zotero_import(body: ZoteroImport, request: Request) -> dict[str, Any]:
        """One Zotero collection's items into the Library ("Items are added to All works"), each with the text of its
        first readable PDF. The records are Zotero's, so their metadata stays the person's own (`user_supplied`)."""
        store = store_of(request)
        library, http = zotero.library(body.source), request.app.state.http
        items, rows = await zotero.collection_items(http, library, body.collection_key)
        payload_path = f"{new_id('zot')}.json"
        with disk_full_refused():
            settings.payloads_dir.mkdir(parents=True, exist_ok=True)
            (settings.payloads_dir / payload_path).write_text(json.dumps(rows), encoding="utf-8")
        svids, saved, pdfs_added, notes = [], [], 0, []
        for item in items:
            # Stored and saved together, so a purge running during a PDF read cannot take the record.
            with transaction(store.conn):
                svid, _ = store.upsert_provider_source("zotero", item.record, payload_path)
                saved += library_items.save(store, [svid], "zotero_import")
            svids.append(svid)
            if item.pdf_problem:
                notes.append({"title": item.record.title, "note": item.pdf_problem, "vars": item.pdf_problem_vars})
            if item.pdf_key is None or store.has_asset(svid):
                continue
            added, pdf_notes = await attach_zotero_pdf(store, settings, http, library, item, svid,
                                                       request.app.state.fetch_pdf, None)
            notes += pdf_notes
            pdfs_added += added
        return {"library": library_view(store), "zotero_import": {
            "items": len(items), "pdfs_added": pdfs_added, "notes": notes, "saved": saved,
            "already_saved": [s for s in dict.fromkeys(svids) if s not in saved]}}

    @app.post("/api/library/reference-imports", status_code=201)
    async def reference_import(request: Request, file: UploadFile = File(...),
                               format: Literal["bibtex", "ris"] | None = Form(None)) -> Any:
        """A BibTeX or RIS file into the Library: every readable entry, with the entries that could not be read listed
        and left out. Nothing is stored when no entry can be read."""
        store = store_of(request)
        data = await file.read(bibtex_ris.MAX_FILE_BYTES + 1)
        try:
            # Off the event loop: parsing a large file is CPU work and touches no shared state.
            fmt, entries, errors = await asyncio.to_thread(bibtex_ris.read_file, data, file.filename, format)
        except bibtex_ris.ImportRefused as exc:
            raise UploadRefused(exc.status, exc.code, exc.detail) from None
        if not entries:
            return JSONResponse({"detail": "No entry in the file could be read", "code": "import_no_entries",
                                 "errors": [e.view() for e in errors]}, status_code=422)
        file_payload = f"{new_id('ref')}.{'bib' if fmt == 'bibtex' else 'ris'}"
        with disk_full_refused():
            settings.payloads_dir.mkdir(parents=True, exist_ok=True)
            (settings.payloads_dir / file_payload).write_bytes(data)
            result = await bibtex_ris.import_entries(store, request.app.state.http, settings.payloads_dir,
                                                     settings.contact_email, entries, fmt, file_payload)
        return {"library": library_view(store), "reference_import": {
            "format": fmt, "filename": Path(file.filename or "").name or None, **result,
            "errors": [e.view() for e in errors]}}

    @app.get("/api/library/assets/{asset_id}")
    async def get_asset(asset_id: str, request: Request) -> FileResponse:
        """The PDF in use of a saved item, read-only, for a version no research may hold."""
        store = store_of(request)
        asset = store.asset(asset_id)
        saved = store.conn.execute("SELECT 1 FROM library_items WHERE source_version_id = ?",
                                   (asset["source_version_id"],)).fetchone()
        if asset["removed_at"] is not None or saved is None:
            raise HTTPException(404, "Asset is not part of the library")
        root = settings.papers_dir.resolve()
        path = (root / asset["storage_path"]).resolve()
        if not path.is_relative_to(root) or not path.exists():
            raise HTTPException(404, "File missing")
        return FileResponse(path, media_type="application/pdf", headers={"Content-Disposition": "inline", "Cache-Control": "no-cache"})
