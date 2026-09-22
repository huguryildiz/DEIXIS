"""CORE search adapter: open-access works aggregated from repositories and journals (`Authorization: Bearer` key).

Probed live on 2026-09-15. The search path needs its trailing slash (`/v3/search/works` answers 301).
`"molecular communication" AND (scheduling OR "resource allocation")` matched 10 works; the same query with an unclosed
parenthesis matched 7 instead of failing, so query validation checks balance first. A quoted phrase without AND
(`"molecular communication"`, or two phrases joined by OR) answered HTTP 500 ("abstract is not a searchable field"),
while `"molecular communication" AND scheduling` matched 7. A field prefix does not restrict a phrase:
`title:"molecular communication"` matched 1,565,728 works, `("molecular communication")` 1,889. A key allows 150
requests per window and no key 10; 4 of 12 rapid keyless requests answered 429 with an `x-ratelimit-retry-after`
timestamp and no `Retry-After`, so the connector requires a key. Works carry a DOI, often an abstract and a CORE-hosted
PDF, but no version label, so no PDF is attached. `fullText` (930,022 characters in the largest of 1,000 probe results)
is dropped from the stored payload.

Paging (CORE API v3 documentation, read 2026-09-21): the search endpoint pages with `limit` and `offset`; the
commonly stated 10,000-record ceiling for offset paging is not restated in the current documentation, and the read
limit stays far below it either way.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from deixis.providers.common import (MAX_RATE_LIMIT_RETRIES, ProviderRecord, SearchOutcome, next_offset,
                                     normalize_doi, page_offset, send, year_of)

PROVIDER_ID = "core"
SEARCH_URL = "https://api.core.ac.uk/v3/search/works/"
ABSTRACT_ORIGIN = "provider_core"
RATE_HEADERS = ("x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-retry-after")
MAX_RESULTS = 100


def link(work: dict[str, Any], kind: str) -> str | None:
    return next((item["url"] for item in work.get("links") or [] if item.get("type") == kind and item.get("url")), None)


def _record(work: dict[str, Any]) -> ProviderRecord:
    number = str(work.get("id") or "")
    doi = normalize_doi(work.get("doi"))
    abstract = re.sub(r"\s+", " ", work.get("abstract") or "").strip() or None
    identifiers = {"core_work_id": number}
    if doi:
        identifiers["doi"] = doi
    if work.get("arxivId"):
        identifiers["arxiv"] = str(work["arxivId"])
    return ProviderRecord(
        provider_record_id=number,
        title=re.sub(r"\s+", " ", work.get("title") or "").strip() or "(untitled)",
        authors=[a["name"] for a in work.get("authors") or [] if a.get("name")],
        year=year_of(work.get("yearPublished") or work.get("publishedDate")),
        venue=next((j["title"] for j in work.get("journals") or [] if j.get("title")), None),
        publication_type=work.get("documentType"),
        doi=doi,
        landing_url=link(work, "display") or (f"https://core.ac.uk/works/{number}" if number else None),
        oa_pdf_url=None,
        oa_pdf_version=None,
        version_label=None,
        abstract=abstract,
        abstract_origin=ABSTRACT_ORIGIN if abstract else None,
        identifiers=identifiers,
        raw={k: v for k, v in work.items() if k != "fullText"},
    )


async def search(client: httpx.AsyncClient, query: str, limit: int, api_key: str | None = None,
                 contact_email: str | None = None, cursor: str | None = None,
                 max_rate_limit_retries: int = MAX_RATE_LIMIT_RETRIES) -> SearchOutcome:
    count = min(limit, MAX_RESULTS)
    offset = page_offset(cursor)
    params: dict[str, Any] = {"q": query, "limit": count}
    if cursor is not None:
        params["offset"] = offset  # offset + limit reaches 10,000, far above the read limit
    headers = {"Authorization": f"Bearer {api_key or ''}"}
    description = (f"GET {SEARCH_URL} q={query!r} limit={count}"
                   + (f" offset={offset}" if cursor is not None else "") + " access=api_key")
    response, outcome = await send(client, SEARCH_URL, params, headers, description, "api_key", RATE_HEADERS, (api_key,),
                                   max_rate_limit_retries=max_rate_limit_retries)
    if response is None:
        return outcome
    try:
        payload = response.json()
        outcome.records = [_record(w) for w in payload["results"]]
        outcome.provider_total = payload["totalHits"]
        if cursor is not None:
            outcome.next_cursor = next_offset(offset, len(outcome.records), count, outcome.provider_total)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        outcome.status, outcome.error, outcome.records = "parse_error", str(exc)[:300], []
        return outcome
    outcome.status = "zero_results" if not outcome.records else "completed"
    outcome.raw_payload = payload | {"results": [r.raw for r in outcome.records]}
    return outcome
