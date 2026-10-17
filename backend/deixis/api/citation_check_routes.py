"""Verify Citations, V1 (D86): give a draft and its bibliography, read back the occurrences, entries and pairs, look the
entries up, delete the draft. No route here calls a model. The application middleware enforces loopback, Origin, CSRF
and the body size (`upload_limit`).

Resolution is an explicit `POST …/resolve`, not a run step: it is a handful of OpenAlex lookups with no model call,
like the Library's reference import, and it is idempotent by entry status (a resolved or unresolved entry is never
asked again), so it needs no run, scope revision or `operation_key` to avoid sending twice.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import File, Form, Request, UploadFile

from deixis.api.app import UploadRefused, disk_full_refused
from deixis.config import Settings
from deixis.documents import draft_parse
from deixis.imports import bibtex_ris
from deixis.workflow import citation_check


def _parse(data: bytes | None, filename: str | None, text: str | None, bib: bytes | None, bib_name: str | None):
    fmt, body = draft_parse.read_draft(data, filename, text)
    draft = draft_parse.parse_draft(fmt, body)
    if bib is None:
        return draft, None
    bib_fmt, entries, errors = bibtex_ris.read_file(bib, bib_name)
    return draft, (bib_fmt, entries, [e.view() for e in errors], bib_name)


def register_citation_check_routes(app, settings: Settings) -> None:
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

    @app.delete("/api/citation-checks/{draft_id}")
    async def delete_check(draft_id: str, request: Request) -> dict[str, bool]:
        citation_check.delete(request.app.state.store, draft_id)
        return {"deleted": True}
