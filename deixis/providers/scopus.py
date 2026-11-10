"""Scopus Search API adapter (`X-ELS-APIKey` header; never written to records or logs).

Probed live on 2026-09-14 with the configured key: `view=STANDARD` works and returns title, first author, venue, cover
date, DOI and citation count but no abstract; `view=COMPLETE` (abstracts, all authors) answered 401
AUTHORIZATION_ERROR, so off an entitled network records carry no abstract. A malformed query answers 400
INVALID_INPUT. An empty result set is one entry holding an `error` field.

On 2026-09-15 the same key over a university VPN answered 200 for `view=COMPLETE`: Elsevier entitles that view by the
caller's IP range, so `complete_view_entitled` reports whether the current network has institutional access.

Paging (Elsevier Scopus Search API documentation, read 2026-09-21): `start` and `count` page the result set and
ordinary offset paging returns at most the first 5,000 records; `cursor` is needed beyond that and is not used here,
because the read limit stays below 5,000.
"""

from __future__ import annotations

import json
import socket
from typing import Any

import httpx

from deixis.providers.common import (MAX_RATE_LIMIT_RETRIES, ProviderRecord, SearchOutcome, next_offset,
                                     normalize_doi, page_offset, send, year_of)

PROVIDER_ID = "scopus"
SEARCH_URL = "https://api.elsevier.com/content/search/scopus"
# The sorting setting every Scopus search carries, whatever the query names: Scopus's own relevance order. Recorded
# with the search run, so a reader can tell this list is relevance-ordered without reading the adapter.
FIXED_SORT = "relevancy"
# The two views a search may ask for. STANDARD carries no abstract; COMPLETE does, and is entitled by the
# caller's IP range, so off an entitled network it answers 401 (`common.send`: `entitlement_missing`).
STANDARD_VIEW = "STANDARD"
COMPLETE_VIEW = "COMPLETE"
RATE_LIMIT_HEADERS = ("x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset")
MAX_RESULTS = 25
ABSTRACT_ORIGIN = "provider_scopus"


def _authors(entry: dict[str, Any]) -> list[str]:
    """Every author the entry names: the COMPLETE view's own list, or the one author the STANDARD view gives.

    An author the documented name fields do not carry is not read past. A name dropped here is dropped from the
    record and from every citation of it, so the whole page is refused instead (`parse_error`).
    """
    named = []
    for author in entry.get("author") or []:
        name = str(author.get("authname") or "").strip()
        if not name:
            # The view's own parts, in the order `authname` itself writes them.
            surname = str(author.get("surname") or "").strip()
            given = str(author.get("given-name") or author.get("initials") or "").strip()
            name = " ".join(part for part in (surname, given) if part)
        if not name:
            raise TypeError("Scopus entry.author holds an author no documented field names")
        named.append(name)
    return named or ([entry["dc:creator"]] if entry.get("dc:creator") else [])


def _record(entry: dict[str, Any]) -> ProviderRecord:
    abstract = (entry.get("dc:description") or "").strip() or None
    scopus_id = str(entry.get("dc:identifier") or entry.get("eid") or "").removeprefix("SCOPUS_ID:")
    doi = normalize_doi(entry.get("prism:doi"))
    landing = next((link.get("@href") for link in entry.get("link") or [] if link.get("@ref") == "scopus"), None)
    return ProviderRecord(
        provider_record_id=scopus_id,
        title=entry.get("dc:title") or "(untitled)",
        authors=_authors(entry),
        year=year_of(entry.get("prism:coverDate")),
        venue=entry.get("prism:publicationName"),
        publication_type=entry.get("subtypeDescription"),
        doi=doi,
        landing_url=landing,
        oa_pdf_url=None,
        oa_pdf_version=None,
        version_label="publishedVersion",
        # Only the COMPLETE view carries the abstract; the STANDARD view's records have none.
        abstract=abstract,
        abstract_origin=ABSTRACT_ORIGIN if abstract else None,
        identifiers={"scopus_id": scopus_id, "eid": str(entry.get("eid") or "")} | ({"doi": doi} if doi else {}),
        raw=entry,
    )


def route_source() -> str | None:
    """Local address the OS uses to reach Scopus; it changes when a VPN starts or stops routing that traffic.

    A UDP connect only selects the route, no packet is sent. None when the name does not resolve or no route exists.
    """
    try:
        family, _, _, _, address = socket.getaddrinfo(httpx.URL(SEARCH_URL).host, 443, type=socket.SOCK_DGRAM)[0]
        with socket.socket(family, socket.SOCK_DGRAM) as probe:
            probe.connect(address)
            return str(probe.getsockname()[0])
    except OSError:
        return None


async def complete_view_entitled(client: httpx.AsyncClient, api_key: str) -> bool | None:
    """One `view=COMPLETE` request: True on 200, False on 401 (not entitled), None when the answer says neither."""
    params = {"query": "TITLE(optimization)", "count": 1, "view": "COMPLETE"}
    try:
        response = await client.get(SEARCH_URL, params=params, headers={"X-ELS-APIKey": api_key, "Accept": "application/json"},
                                    timeout=10)
    except httpx.HTTPError:
        return None
    return {200: True, 401: False}.get(response.status_code)


async def search(client: httpx.AsyncClient, query: str, limit: int, api_key: str | None = None,
                 contact_email: str | None = None, cursor: str | None = None,
                 max_rate_limit_retries: int = MAX_RATE_LIMIT_RETRIES,
                 view: str = STANDARD_VIEW) -> SearchOutcome:
    """`view` is the record view asked for: STANDARD by default, COMPLETE where the caller wants abstracts and
    the network is entitled to them. An unentitled COMPLETE request answers 401 and nothing is sent again."""
    if not api_key:
        return SearchOutcome("not_configured", "before_send", f"GET {SEARCH_URL} access=not_configured", "not_configured")
    count = min(limit, MAX_RESULTS)
    offset = page_offset(cursor)
    if view not in (STANDARD_VIEW, COMPLETE_VIEW):
        raise ValueError(f"unknown Scopus view {view!r}")
    params: dict[str, Any] = {"query": query, "count": count, "view": view, "sort": FIXED_SORT}
    if cursor is not None:
        params["start"] = offset  # `start` reaches record 5,000; a deeper read would need Scopus's own cursor
    headers = {"X-ELS-APIKey": api_key or "", "Accept": "application/json"}
    description = (f"GET {SEARCH_URL} query={query!r} count={count}"
                   + (f" start={offset}" if cursor is not None else "") + f" view={view} sort={FIXED_SORT} access=api_key")
    response, outcome = await send(client, SEARCH_URL, params, headers, description, "api_key", RATE_LIMIT_HEADERS,
                                   (api_key,), max_rate_limit_retries=max_rate_limit_retries)
    if response is None:
        return outcome
    try:
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("Scopus root must be an object")
        results = payload["search-results"]
        if results.get("entry") is not None and (not isinstance(results["entry"], list)
                                   or any(not isinstance(e, dict) for e in results["entry"])):
            raise TypeError("Scopus search-results.entry must be a list of objects")
        # An author list whose entries are not objects is not read past: a name the reply holds in another shape
        # would be dropped from the record, and from every citation of it.
        for listed in ((e.get("author") if isinstance(e, dict) else None) for e in results.get("entry") or []):
            if listed is not None and (not isinstance(listed, list)
                                       or any(not isinstance(author, dict) for author in listed)):
                raise TypeError("Scopus entry.author must be a list of objects")
        outcome.records = [_record(e) for e in results.get("entry") or [] if "error" not in e]
        outcome.provider_total = int(results["opensearch:totalResults"])
        if cursor is not None:
            outcome.next_cursor = next_offset(offset, len(outcome.records), count, outcome.provider_total)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError) as exc:
        outcome.status, outcome.error, outcome.records = "parse_error", str(exc)[:300], []
        return outcome
    outcome.status = "zero_results" if not outcome.records else "completed"
    outcome.raw_payload = payload
    return outcome
