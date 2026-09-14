"""IEEE Xplore metadata search adapter (`apikey` query parameter; never written to records or logs).

Probed live on 2026-09-14: `querytext` accepts quoted phrases, AND/OR/NOT and parentheses; an unbalanced query is not
rejected but returns HTTP 200 with zero records, so query validation checks balance before a search is sent. Records
include abstracts. `pdf_url` is a sign-in stamp page, not a PDF, so no file is attached.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

import httpx

from deixis.providers.common import ProviderRecord, SearchOutcome, normalize_doi, send

PROVIDER_ID = "ieee_xplore"
SEARCH_URL = "https://ieeexploreapi.ieee.org/api/v1/search/articles"
ABSTRACT_ORIGIN = "provider_ieee_xplore"
ERROR_HEADERS = ("x-error-detail-header", "x-mashery-error-code")
MAX_RESULTS = 200


def _plain(text: str | None) -> str | None:
    if not text:
        return None
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip() or None


def _record(article: dict[str, Any]) -> ProviderRecord:
    number = str(article.get("article_number") or "")
    doi = normalize_doi(article.get("doi"))
    abstract = _plain(article.get("abstract"))
    year = str(article.get("publication_year") or "")
    return ProviderRecord(
        provider_record_id=number,
        title=_plain(article.get("title")) or "(untitled)",
        authors=[a["full_name"] for a in (article.get("authors") or {}).get("authors", []) if a.get("full_name")],
        year=int(year) if year.isdigit() else None,
        venue=article.get("publication_title"),
        publication_type=article.get("content_type"),
        doi=doi,
        landing_url=article.get("html_url") or (f"https://ieeexplore.ieee.org/document/{number}/" if number else None),
        oa_pdf_url=None,
        oa_pdf_version=None,
        version_label="publishedVersion",
        abstract=abstract,
        abstract_origin=ABSTRACT_ORIGIN if abstract else None,
        identifiers={"ieee_article_number": number} | ({"doi": doi} if doi else {}),
        raw=article,
    )


async def search(client: httpx.AsyncClient, query: str, limit: int, api_key: str | None = None,
                 contact_email: str | None = None) -> SearchOutcome:
    count = min(limit, MAX_RESULTS)
    params = {"querytext": query, "max_records": count, "start_record": 1, "format": "json", "apikey": api_key or ""}
    description = f"GET {SEARCH_URL} querytext={query!r} max_records={count} access=api_key"
    response, outcome = await send(client, SEARCH_URL, params, {}, description, "api_key", ERROR_HEADERS, (api_key,))
    if response is None:
        # IEEE reports exhausted per-second or per-day allowances as 403 with an error detail header.
        if outcome.http_status == 403 and "Over Queries" in outcome.rate_limit.get("x-error-detail-header", ""):
            outcome.status = "rate_limited"
        return outcome
    try:
        payload = response.json()
        outcome.records = [_record(a) for a in payload.get("articles") or []]
        outcome.provider_total = payload["total_records"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        outcome.status, outcome.error, outcome.records = "parse_error", str(exc)[:300], []
        return outcome
    outcome.status = "zero_results" if not outcome.records else "completed"
    outcome.raw_payload = payload
    return outcome
