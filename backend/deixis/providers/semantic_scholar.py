"""Semantic Scholar paper relevance search adapter.

Probed live on 2026-09-14 without a key: the shared keyless pool answered 429 (no retry-after header) to the first
requests and 200 after a short wait, so 429s are retried with a bounded backoff. `/paper/search` takes plain words and
supports no query syntax. A paper record groups a work's versions; its DOI names the published version. A record known
only from arXiv gets no DOI (arXiv's DOI would not say which version). The open-access PDF carries no version label, so
it is not attached.

Paging (Academic Graph API docs, relevance search, read 2026-09-21): `offset` and `limit` page the result set and
`offset + limit` may not exceed 1,000; the response names the next `offset` in `next` and leaves it out at the end.
Reading past 1,000 needs the bulk endpoint.

Bulk search (`/paper/search/bulk`, API description read 2026-09-23, `.local/sw-s2-bulk-probe-2026-09-23/swagger.json`):
the query is matched against title and abstract with `+` for AND, `|` for OR, `"` for a phrase and `( )` for
precedence; up to 1,000 papers come in one call and a `token` in the answer asks for the next batch; `total` is an
estimate. It does not order by relevance: `sort` is `paperId` (the default), `publicationDate` or `citationCount`, so
which records a read limit keeps is decided by the sort (D93). An sw query names this endpoint and its sort
(`endpoint`, `sort`); a legacy query, and an sw query stored before D93, names neither and goes to `/paper/search`.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from deixis.providers.common import (FIRST_PAGE, MAX_RATE_LIMIT_RETRIES, ProviderRecord, SearchOutcome, next_offset,
                                     normalize_doi, page_offset, send)

PROVIDER_ID = "semantic_scholar"
SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
BULK_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
BULK_ENDPOINT = "bulk"
BULK_MAX_RESULTS = 1000  # papers one bulk call returns
BULK_SORT = "citationCount:desc"  # chosen by slice 14's Task 1 (D93)
# Records past a read limit that a bulk page returned are dropped. Neither the answer's token nor anything else can ask
# for them, so the read ends there and this cursor is never sent (the read limit ends the query first).
CUT = "cut"
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
                 contact_email: str | None = None, cursor: str | None = None,
                 max_rate_limit_retries: int = MAX_RATE_LIMIT_RETRIES, endpoint: str | None = None,
                 sort: str | None = None) -> SearchOutcome:
    """One page of a relevance search, or of a bulk search when the query names that endpoint (D93)."""
    if endpoint == BULK_ENDPOINT:
        return await search_bulk(client, query, limit, api_key, contact_email, cursor, max_rate_limit_retries,
                                 sort or BULK_SORT)
    if endpoint is not None:
        raise ValueError(f"unknown Semantic Scholar endpoint: {endpoint!r}")
    count = min(limit, MAX_RESULTS)
    params: dict[str, Any] = {"query": query, "limit": count, "fields": FIELDS}
    offset = page_offset(cursor)
    if cursor is not None:
        params["offset"] = offset
    headers = {"x-api-key": api_key} if api_key else {}
    access_mode = "api_key" if api_key else "keyless"
    description = (f"GET {SEARCH_URL} query={query!r} limit={count}"
                   + (f" offset={offset}" if cursor is not None else "") + f" access={access_mode}")
    response, outcome = await send(client, SEARCH_URL, params, headers, description, access_mode, RATE_LIMIT_HEADERS, (api_key,),
                                   unstated_wait=UNSTATED_RATE_LIMIT_WAIT,
                                   max_rate_limit_retries=max_rate_limit_retries)
    if response is None:
        return outcome
    try:
        payload = response.json()
        outcome.records = [_record(p) for p in payload.get("data") or []]
        outcome.provider_total = payload["total"]
        # The response names the next offset itself and leaves it out once the reachable window (offset + limit ≤ 1000)
        # or the result set is spent.
        nxt = payload.get("next")
        outcome.next_cursor = str(nxt) if cursor is not None and nxt is not None else None
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        outcome.status, outcome.error, outcome.records = "parse_error", str(exc)[:300], []
        return outcome
    outcome.status = "zero_results" if not outcome.records else "completed"
    outcome.raw_payload = payload
    return outcome


async def search_bulk(client: httpx.AsyncClient, query: str, limit: int, api_key: str | None = None,
                      contact_email: str | None = None, cursor: str | None = None,
                      max_rate_limit_retries: int = MAX_RATE_LIMIT_RETRIES, sort: str = BULK_SORT) -> SearchOutcome:
    """One batch of a bulk search: up to 1,000 papers, of which the first `limit` are kept.

    The request goes through the same `send` as every other Semantic Scholar request, so the process-wide gate (D67)
    and the bounded 429 retries apply to it unchanged. The endpoint takes no page size; a batch larger than `limit` is
    cut there and its read ends (`CUT`).
    """
    if cursor == CUT:
        raise ValueError("a cut bulk batch has no next page")
    params: dict[str, Any] = {"query": query, "fields": FIELDS, "sort": sort}
    if cursor not in (None, FIRST_PAGE):
        params["token"] = cursor
    headers = {"x-api-key": api_key} if api_key else {}
    access_mode = "api_key" if api_key else "keyless"
    description = (f"GET {BULK_URL} query={query!r} sort={sort}" + (" token=<next>" if "token" in params else "")
                   + f" access={access_mode}")
    response, outcome = await send(client, BULK_URL, params, headers, description, access_mode, RATE_LIMIT_HEADERS, (api_key,),
                                   unstated_wait=UNSTATED_RATE_LIMIT_WAIT,
                                   max_rate_limit_retries=max_rate_limit_retries)
    if response is None:
        return outcome
    try:
        payload = response.json()
        papers = payload.get("data") or []
        outcome.records = [_record(p) for p in papers[:limit]]
        total = payload.get("total")
        outcome.provider_total = int(total) if total is not None else None  # an estimate, sent as a string
        token = payload.get("token")
        outcome.next_cursor = CUT if len(papers) > limit else (str(token) if token else None)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        outcome.status, outcome.error, outcome.records = "parse_error", str(exc)[:300], []
        return outcome
    outcome.status = "zero_results" if not outcome.records else "completed"
    outcome.raw_payload = payload
    return outcome
