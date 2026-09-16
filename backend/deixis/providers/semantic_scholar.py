"""Semantic Scholar paper relevance search adapter.

Probed live on 2026-09-14 without a key: the shared keyless pool answered 429 (no retry-after header) to the first
requests and 200 after a short wait, so 429s are retried with a bounded backoff. `/paper/search` takes plain words and
supports no query syntax. A paper record groups a work's versions; its DOI names the published version. A record known
only from arXiv gets no DOI (arXiv's DOI would not say which version). The open-access PDF carries no version label, so
it is not attached.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from deixis.providers.common import ProviderRecord, SearchOutcome, normalize_doi, send

PROVIDER_ID = "semantic_scholar"
SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "paperId,externalIds,title,abstract,year,venue,publicationTypes,authors,url"
ABSTRACT_ORIGIN = "provider_semantic_scholar"
RATE_LIMIT_HEADERS = ("x-ratelimit-limit", "x-ratelimit-remaining")
MAX_RESULTS = 100
# With a valid key, 3 s and 6 s retries still met three 429s in a row on 2026-09-15/16 (3 of 12 searches). The 429 carries
# no retry-after, so wait longer: 15 s, then 30 s.
UNSTATED_RATE_LIMIT_WAIT = 15.0


def _record(paper: dict[str, Any]) -> ProviderRecord:
    external = {k: str(v) for k, v in (paper.get("externalIds") or {}).items() if v}
    doi = normalize_doi(external.get("DOI"))
    abstract = (paper.get("abstract") or "").strip() or None
    return ProviderRecord(
        provider_record_id=str(paper["paperId"]),
        title=paper.get("title") or "(untitled)",
        authors=[a["name"] for a in paper.get("authors") or [] if a.get("name")],
        year=paper.get("year") if isinstance(paper.get("year"), int) else None,
        venue=paper.get("venue") or None,
        publication_type=(paper.get("publicationTypes") or [None])[0],
        doi=doi,
        landing_url=paper.get("url"),
        oa_pdf_url=None,
        oa_pdf_version=None,
        version_label=None,
        abstract=abstract,
        abstract_origin=ABSTRACT_ORIGIN if abstract else None,
        identifiers=external,
        raw=paper,
    )


async def search(client: httpx.AsyncClient, query: str, limit: int, api_key: str | None = None,
                 contact_email: str | None = None) -> SearchOutcome:
    count = min(limit, MAX_RESULTS)
    params = {"query": query, "limit": count, "fields": FIELDS}
    headers = {"x-api-key": api_key} if api_key else {}
    access_mode = "api_key" if api_key else "keyless"
    description = f"GET {SEARCH_URL} query={query!r} limit={count} access={access_mode}"
    response, outcome = await send(client, SEARCH_URL, params, headers, description, access_mode, RATE_LIMIT_HEADERS, (api_key,),
                                   unstated_wait=UNSTATED_RATE_LIMIT_WAIT)
    if response is None:
        return outcome
    try:
        payload = response.json()
        outcome.records = [_record(p) for p in payload.get("data") or []]
        outcome.provider_total = payload["total"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        outcome.status, outcome.error, outcome.records = "parse_error", str(exc)[:300], []
        return outcome
    outcome.status = "zero_results" if not outcome.records else "completed"
    outcome.raw_payload = payload
    return outcome
