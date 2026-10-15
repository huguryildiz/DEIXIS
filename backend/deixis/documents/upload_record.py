"""Which scholarly record an uploaded PDF is, so its source shows the paper's title, authors, year and abstract (D37).

The seed rule of D2/D3 read from the file's own first page: the DOIs the first two pages name are looked up first, and
a work counts only when its title (four words or more) stands in the head of page 1. When no DOI decides, one OpenAlex
meaning search with that head is asked. One change from the seed rule: a work whose title is part of another found
work's title ("Entanglement Routing Design over Quantum Networks" inside "Multi-Entanglement Routing Design over
Quantum Networks") gives way to the longer one, because the longer title also contains it. Two works with the same
title (a preprint and its published record) still decide nothing. Nothing is filled when no work passes.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from deixis.documents import identity
from deixis.providers import openalex
from deixis.providers.common import ProviderRecord
from deixis.workflow import seed_match
from deixis.workflow.store import title_key

PROVIDER = "openalex"


def page_text(store: Any, asset_id: str, extraction_version: str | None) -> tuple[str, str]:
    """The first two pages' text (for DOIs) and the head of page 1 (for the title); both empty without page-1 text."""
    head, title_region, _ = seed_match.first_pages(store, {"asset_id": asset_id, "extraction_version": extraction_version})
    return head, title_region


def pick(title_region: str, works: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The one work whose title stands in the head of page 1 once titles contained in a longer found title are set
    aside; None when no work or more than one remains."""
    body = f" {title_key(title_region)} "
    hits: dict[str, tuple[str, dict[str, Any]]] = {}
    for work in works:
        oid, key = seed_match.short_id(work.get("id")), title_key(work.get("display_name"))
        if oid and len(key.split()) >= identity.MIN_TITLE_WORDS and f" {key} " in body:
            hits.setdefault(oid, (key, work))
    keys = [key for key, _ in hits.values()]
    kept = [work for key, work in hits.values() if not any(other != key and f" {key} " in f" {other} " for other in keys)]
    return kept[0] if len(kept) == 1 else None


async def lookup(http: httpx.AsyncClient, head: str, title_region: str, api_key: str | None = None,
                 contact_email: str | None = None) -> tuple[ProviderRecord, str] | None:
    """The record the file names itself as and how it was found ("doi_title" or "title"), or None.

    A failed request is the same as no match: the upload keeps its file-name title and can be looked up again."""
    if not head:
        return None
    dois = seed_match.dois_in(head)
    if dois:
        found = await openalex.works_by_dois(http, dois, api_key=api_key, contact_email=contact_email,
                                             per_page=openalex.MAX_IDS_PER_REQUEST, max_rate_limit_retries=0)
        works = (found.raw_payload or {}).get("results") or [] if found.status == "completed" else []
        work = pick(title_region, [w for w in works if seed_match.doi_of(w) in dois])
        if work is not None:
            return openalex._record(work), "doi_title"
    found = await openalex.search_semantic(http, openalex.semantic_text(title_region), seed_match.SEMANTIC_PER_PAGE,
                                           api_key, contact_email, max_rate_limit_retries=0)
    if found.status != "completed":
        return None
    work = pick(title_region, (found.raw_payload or {}).get("results") or [])
    return (openalex._record(work), "title") if work is not None else None


def match_of(source: dict[str, Any]) -> dict[str, Any] | None:
    return json.loads(source["record_match_json"]) if source.get("record_match_json") else None


async def identify(store: Any, http: httpx.AsyncClient, svid: str, api_key: str | None = None,
                   contact_email: str | None = None) -> bool:
    """Look an uploaded source up once and fill it from the record it names itself as; True when it was filled."""
    source = store.source(svid)
    if source["origin"] != "user_upload" or source.get("record_match_json"):
        return False
    asset = store.conn.execute("SELECT id, extraction_version FROM source_assets WHERE source_version_id = ?"
                               " AND removed_at IS NULL", (svid,)).fetchone()
    if asset is None:
        return False
    head, title_region = page_text(store, asset["id"], asset["extraction_version"])
    try:
        found = await lookup(http, head, title_region, api_key, contact_email)
    except Exception:  # noqa: BLE001 - the upload stands without its record; the source panel can look it up again
        return False
    if found is None:
        return False
    store.fill_upload_record(svid, found[0], PROVIDER, found[1])
    return True
