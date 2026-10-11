"""Library-owned items (UI parity S19a, F14): save works, upload a PDF into the Library, export a bibliography for any
set of works, and start a research over a set. The application middleware enforces loopback, Origin and CSRF.

Versions are never merged: a saved item is one source version, an exported entry is one stored record, and a new
research gets the one version per work that adding a Library work to a research already picks (D41).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from fastapi import File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from deixis.api.app import CreateResearch, disk_full_refused, store_upload
from deixis.config import Settings
from deixis.documents import pdf
from deixis.workflow import bibliography, file_restore, intent, library_items, text_retry
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
        library_items.save(store, [svid], "upload")
        return {"source_version_id": svid, "work_id": store.source(svid)["work_id"], "library": library_view(store),
                "file_restore": store.file_restore_view(placement.operation_id) if placement.operation_id else None}

    @app.post("/api/library/bibliography")
    async def export_bibliography(body: BibliographyRequest, request: Request) -> Response:
        if not body.work_ids and not body.source_version_ids:
            raise HTTPException(422, "Choose at least one work")
        records = _export_records(store_of(request), body)
        text = bibliography.to_bibtex(records) if body.format == "bibtex" else bibliography.to_ris(records)
        name = f"deixis-library.{'bib' if body.format == 'bibtex' else 'ris'}"
        return Response(text, media_type=bibliography.MEDIA_TYPES[body.format],
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.post("/api/library/researches", status_code=201)
    async def new_research_from_set(body: NewResearchFromSet, request: Request) -> dict[str, Any]:
        store = store_of(request)
        works = [_library_work(store, work_id) for work_id in dict.fromkeys(body.work_ids)]
        # The research itself is created by the one create route, so model and scope checks stay in one place.
        create = next(route.endpoint for route in request.app.router.routes
                      if getattr(route, "path", None) == "/api/researches" and "POST" in (getattr(route, "methods", None) or ()))
        created = await create(CreateResearch(**body.model_dump(exclude={"work_ids"})), request)
        rid = created["research"]["id"]
        added = []
        for work in works:
            version = library_version_to_add(work)
            store.add_to_corpus(rid, version["source_version_id"], "library", selection_state="included",
                                selection_origin="user")
            added.append(version["source_version_id"])
        intent.attached_ingested(store, rid)
        return research_view(store, rid) | {"added_source_version_ids": added}
