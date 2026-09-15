"""Crossref works search adapter (keyless; `mailto` selects the polite pool).

Probed live on 2026-09-14: `query=` ranks by loose term matching over bibliographic fields; double quotes and AND are
not interpreted (`"molecular communication" "resource allocation"` returned the same ranking as the bare words), and
a common phrase such as `resource allocation` fills the first results with unrelated records. Abstracts are present
only when the publisher deposited them, as JATS markup. Results are limited to journal articles, proceedings articles
and posted content (preprints).
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

import httpx

from deixis.providers.common import ProviderRecord, SearchOutcome, normalize_doi, send

PROVIDER_ID = "crossref"
WORKS_URL = "https://api.crossref.org/works"
SELECT = "DOI,title,author,issued,container-title,type,abstract,URL,link"
TYPES = "type:journal-article,type:proceedings-article,type:posted-content"
ABSTRACT_ORIGIN = "provider_crossref_jats"
RATE_LIMIT_HEADERS = ("x-rate-limit-limit", "x-rate-limit-interval", "x-concurrency-limit")
MAX_RESULTS = 100


def strip_markup(text: str | None) -> str | None:
    if not text:
        return None
    plain = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()
    return re.sub(r"^abstract\s*[:.]?\s*", "", plain, flags=re.IGNORECASE) or None


def _record(item: dict[str, Any]) -> ProviderRecord:
    doi = normalize_doi(item.get("DOI"))
    abstract = strip_markup(item.get("abstract"))
    parts = ((item.get("issued") or {}).get("date-parts") or [[None]])[0]
    authors = [" ".join(p for p in (a.get("given"), a.get("family")) if p) or a.get("name") for a in item.get("author") or []]
    kind = item.get("type")
    pdf_link = next((link for link in item.get("link") or []
                     if link.get("URL") and ("pdf" in (link.get("content-type") or "").lower()
                                             or link["URL"].lower().split("?", 1)[0].endswith(".pdf"))), None)
    pdf_version = {"vor": "publishedVersion", "am": "acceptedVersion"}.get(
        (pdf_link.get("content-version") or "").lower()) if pdf_link else None
    return ProviderRecord(
        provider_record_id=doi or str(item.get("URL")),
        title=strip_markup((item.get("title") or [None])[0]) or "(untitled)",
        authors=[a for a in authors if a],
        year=parts[0] if parts and isinstance(parts[0], int) else None,
        venue=(item.get("container-title") or [None])[0],
        publication_type=kind,
        doi=doi,
        landing_url=item.get("URL"),
        oa_pdf_url=pdf_link.get("URL") if pdf_link else None,
        oa_pdf_version=pdf_version,
        # A DOI registered for posted content names the preprint; other registered types name the published record.
        version_label="submittedVersion" if kind == "posted-content" else "publishedVersion",
        abstract=abstract,
        abstract_origin=ABSTRACT_ORIGIN if abstract else None,
        identifiers={"doi": doi} if doi else {},
        raw=item,
    )


async def search(client: httpx.AsyncClient, query: str, limit: int, api_key: str | None = None,
                 contact_email: str | None = None) -> SearchOutcome:
    rows = min(limit, MAX_RESULTS)
    params: dict[str, Any] = {"query": query, "rows": rows, "select": SELECT, "filter": TYPES}
    if contact_email:
        params["mailto"] = contact_email
    description = f"GET {WORKS_URL} query={query!r} rows={rows} filter={TYPES} access=keyless"
    response, outcome = await send(client, WORKS_URL, params, {}, description, "keyless", RATE_LIMIT_HEADERS)
    if response is None:
        return outcome
    try:
        payload = response.json()
        message = payload["message"]
        outcome.records = [_record(i) for i in message["items"]]
        outcome.provider_total = message.get("total-results")
    except (json.JSONDecodeError, KeyError, TypeError, IndexError) as exc:
        outcome.status, outcome.error, outcome.records = "parse_error", str(exc)[:300], []
        return outcome
    outcome.status = "zero_results" if not outcome.records else "completed"
    outcome.raw_payload = payload
    return outcome
