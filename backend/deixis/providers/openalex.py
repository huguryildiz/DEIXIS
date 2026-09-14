"""OpenAlex works search adapter.

Verified on 2026-09-14 with a keyless request: `search=` is interpreted as full-text
search (poor topical precision), while `search.title_and_abstract=` searches titles
and abstracts; abstracts arrive as `abstract_inverted_index`; rate-limit and cost
headers are returned. Keyless and keyed modes have different daily budgets; the
actual mode and returned limit headers are recorded per call.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

PROVIDER_ID = "openalex"
WORKS_URL = "https://api.openalex.org/works"
SEARCH_PARAM = "search.title_and_abstract"
SELECT = ",".join(
    [
        "id", "doi", "ids", "display_name", "publication_year", "type", "authorships",
        "primary_location", "best_oa_location", "open_access", "abstract_inverted_index",
    ]
)
ABSTRACT_ORIGIN = "provider_openalex_inverted_index"
RATE_LIMIT_HEADERS = (
    "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset",
    "x-ratelimit-cost-usd", "x-ratelimit-remaining-usd", "retry-after",
)


@dataclass
class ProviderRecord:
    provider_record_id: str
    title: str
    authors: list[str]
    year: int | None
    venue: str | None
    publication_type: str | None
    doi: str | None
    landing_url: str | None
    oa_pdf_url: str | None
    oa_pdf_version: str | None
    version_label: str | None
    abstract: str | None
    abstract_origin: str | None
    identifiers: dict[str, str]
    raw: dict[str, Any] = field(repr=False)


@dataclass
class SearchOutcome:
    status: str
    delivery_class: str | None
    request_description: str
    access_mode: str
    records: list[ProviderRecord] = field(default_factory=list)
    provider_total: int | None = None
    http_status: int | None = None
    rate_limit: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    raw_payload: dict[str, Any] | None = None


def reconstruct_abstract(inverted: dict[str, list[int]] | None) -> str | None:
    """Rebuild word order from the inverted index. Punctuation/formatting may differ from the publisher text."""
    if not inverted:
        return None
    positions: dict[int, str] = {}
    for word, indexes in inverted.items():
        for index in indexes:
            positions[index] = word
    return " ".join(positions[i] for i in sorted(positions)) or None


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", value.strip(), flags=re.IGNORECASE).lower() or None


def _record(work: dict[str, Any]) -> ProviderRecord:
    primary = work.get("primary_location") or {}
    best_oa = work.get("best_oa_location") or {}
    ids = {k: str(v) for k, v in (work.get("ids") or {}).items() if v}
    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
    return ProviderRecord(
        provider_record_id=str(work["id"]).rsplit("/", 1)[-1],
        title=work.get("display_name") or "(untitled)",
        authors=[
            (a.get("author") or {}).get("display_name")
            for a in (work.get("authorships") or [])
            if (a.get("author") or {}).get("display_name")
        ],
        year=work.get("publication_year"),
        venue=(primary.get("source") or {}).get("display_name"),
        publication_type=work.get("type"),
        doi=normalize_doi(work.get("doi")),
        landing_url=primary.get("landing_page_url"),
        oa_pdf_url=best_oa.get("pdf_url") or None,
        oa_pdf_version=best_oa.get("version") if best_oa.get("pdf_url") else None,
        version_label=primary.get("version"),
        abstract=abstract,
        abstract_origin=ABSTRACT_ORIGIN if abstract else None,
        identifiers=ids,
        raw=work,
    )


async def search_works(
    client: httpx.AsyncClient,
    query: str,
    per_page: int,
    api_key: str | None = None,
    contact_email: str | None = None,
) -> SearchOutcome:
    params: dict[str, Any] = {SEARCH_PARAM: query, "per_page": per_page, "select": SELECT}
    if contact_email:
        params["mailto"] = contact_email
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    access_mode = "api_key" if api_key else "keyless"
    description = f"GET {WORKS_URL} {SEARCH_PARAM}={query!r} per_page={per_page} access={access_mode}"

    try:
        response = await client.get(WORKS_URL, params=params, headers=headers, timeout=30.0)
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        return SearchOutcome("failed", "before_send", description, access_mode, error=type(exc).__name__)
    except httpx.TimeoutException as exc:
        return SearchOutcome("timeout", "after_send_unknown", description, access_mode, error=type(exc).__name__)
    except httpx.HTTPError as exc:
        return SearchOutcome("failed", "after_send_unknown", description, access_mode, error=type(exc).__name__)

    rate = {h: response.headers[h] for h in RATE_LIMIT_HEADERS if h in response.headers}
    base = dict(request_description=description, access_mode=access_mode, http_status=response.status_code, rate_limit=rate)
    if response.status_code == 429:
        return SearchOutcome("rate_limited", "rejected_not_executed", **base, error="429 Too Many Requests")
    if response.status_code in (401, 403):
        status = "entitlement_missing" if api_key else "auth_required"
        return SearchOutcome(status, "rejected_not_executed", **base, error=response.text[:300])
    if response.status_code != 200:
        return SearchOutcome("failed", "after_send_unknown", **base, error=response.text[:300])
    try:
        payload = response.json()
        records = [_record(w) for w in payload["results"]]
        total = (payload.get("meta") or {}).get("count")
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        return SearchOutcome("parse_error", None, **base, error=str(exc)[:300])
    status = "zero_results" if not records else "completed"
    return SearchOutcome(status, None, **base, records=records, provider_total=total, raw_payload=payload)
