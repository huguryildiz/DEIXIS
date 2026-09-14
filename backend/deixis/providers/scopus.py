"""Scopus Search API adapter (`X-ELS-APIKey` header; never written to records or logs).

Probed live on 2026-09-14 with the configured key: `view=STANDARD` works and returns title, first author, venue, cover
date, DOI and citation count but no abstract; `view=COMPLETE` (abstracts, all authors) answered 401
AUTHORIZATION_ERROR, so records carry no abstract. A malformed query answers 400 INVALID_INPUT. An empty result set is
one entry holding an `error` field.

On 2026-09-15 the same key over a university VPN answered 200 for `view=COMPLETE`: Elsevier entitles that view by the
caller's IP range, so `complete_view_entitled` reports whether the current network has institutional access.
"""

from __future__ import annotations

import json
import socket
from typing import Any

import httpx

from deixis.providers.common import ProviderRecord, SearchOutcome, normalize_doi, send, year_of

PROVIDER_ID = "scopus"
SEARCH_URL = "https://api.elsevier.com/content/search/scopus"
RATE_LIMIT_HEADERS = ("x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset")
MAX_RESULTS = 25


def _record(entry: dict[str, Any]) -> ProviderRecord:
    scopus_id = str(entry.get("dc:identifier") or entry.get("eid") or "").removeprefix("SCOPUS_ID:")
    doi = normalize_doi(entry.get("prism:doi"))
    landing = next((link.get("@href") for link in entry.get("link") or [] if link.get("@ref") == "scopus"), None)
    return ProviderRecord(
        provider_record_id=scopus_id,
        title=entry.get("dc:title") or "(untitled)",
        authors=[entry["dc:creator"]] if entry.get("dc:creator") else [],  # STANDARD view names the first author only
        year=year_of(entry.get("prism:coverDate")),
        venue=entry.get("prism:publicationName"),
        publication_type=entry.get("subtypeDescription"),
        doi=doi,
        landing_url=landing,
        oa_pdf_url=None,
        oa_pdf_version=None,
        version_label="publishedVersion",
        abstract=None,
        abstract_origin=None,
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
                 contact_email: str | None = None) -> SearchOutcome:
    count = min(limit, MAX_RESULTS)
    params = {"query": query, "count": count, "view": "STANDARD", "sort": "relevancy"}
    headers = {"X-ELS-APIKey": api_key or "", "Accept": "application/json"}
    description = f"GET {SEARCH_URL} query={query!r} count={count} view=STANDARD sort=relevancy access=api_key"
    response, outcome = await send(client, SEARCH_URL, params, headers, description, "api_key", RATE_LIMIT_HEADERS, (api_key,))
    if response is None:
        return outcome
    try:
        payload = response.json()
        results = payload["search-results"]
        outcome.records = [_record(e) for e in results.get("entry") or [] if "error" not in e]
        outcome.provider_total = int(results["opensearch:totalResults"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        outcome.status, outcome.error, outcome.records = "parse_error", str(exc)[:300], []
        return outcome
    outcome.status = "zero_results" if not outcome.records else "completed"
    outcome.raw_payload = payload
    return outcome
