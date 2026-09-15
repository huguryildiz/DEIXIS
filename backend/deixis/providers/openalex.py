"""OpenAlex works search adapter.

Verified on 2026-09-14 with a keyless request: `search=` is interpreted as full-text
search (poor topical precision), while `search.title_and_abstract=` searches titles
and abstracts; abstracts arrive as `abstract_inverted_index`; rate-limit and cost
headers are returned. Keyless and keyed modes have different daily budgets; the
actual mode and returned limit headers are recorded per call.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from deixis.providers.common import OtherVersion, ProviderRecord, SearchOutcome, normalize_doi, send

__all__ = ["OtherVersion", "ProviderRecord", "SearchOutcome", "normalize_doi", "reconstruct_abstract", "search_works"]

PROVIDER_ID = "openalex"
WORKS_URL = "https://api.openalex.org/works"
SEARCH_PARAM = "search.title_and_abstract"
SELECT = ",".join(
    [
        "id", "doi", "ids", "display_name", "publication_year", "type", "authorships",
        "primary_location", "best_oa_location", "locations", "open_access", "abstract_inverted_index", "cited_by_count",
    ]
)
ABSTRACT_ORIGIN = "provider_openalex_inverted_index"
RATE_LIMIT_HEADERS = (
    "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset",
    "x-ratelimit-cost-usd", "x-ratelimit-remaining-usd",
)
MAX_RESULTS = 200


def reconstruct_abstract(inverted: dict[str, list[int]] | None) -> str | None:
    """Rebuild word order from the inverted index. Punctuation/formatting may differ from the publisher text."""
    if not inverted:
        return None
    positions: dict[int, str] = {}
    for word, indexes in inverted.items():
        for index in indexes:
            positions[index] = word
    return " ".join(positions[i] for i in sorted(positions)) or None


def _record(work: dict[str, Any]) -> ProviderRecord:
    primary = work.get("primary_location") or {}
    best_oa = work.get("best_oa_location") or {}
    # The overall best OA copy can be an accepted manuscript even when another location has a PDF of the record's
    # published version. Prefer the latter for this source version, without conflating versions.
    same_version_pdf = next((location for location in work.get("locations") or []
                             if location.get("is_oa") and location.get("pdf_url")
                             and primary.get("version") and location.get("version") == primary["version"]), None)
    chosen_pdf = same_version_pdf or best_oa
    ids = {k: str(v) for k, v in (work.get("ids") or {}).items() if v}
    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
    other_versions = []
    if best_oa.get("pdf_url") and best_oa.get("version") and best_oa["version"] != primary.get("version"):
        other_versions.append(OtherVersion(best_oa["version"], best_oa["pdf_url"], best_oa.get("landing_page_url"),
                                           (best_oa.get("source") or {}).get("display_name")))
    return ProviderRecord(
        provider_record_id=str(work["id"]).rsplit("/", 1)[-1],
        title=work.get("display_name") or "(untitled)",
        authors=[
            (a.get("author") or {}).get("display_name")
            for a in (work.get("authorships") or [])
            if (a.get("author") or {}).get("display_name")
        ],
        year=work.get("publication_year"),
        venue=(primary.get("source") or {}).get("display_name") or primary.get("raw_source_name"),
        publication_type=work.get("type"),
        doi=normalize_doi(work.get("doi")),
        landing_url=primary.get("landing_page_url"),
        oa_pdf_url=chosen_pdf.get("pdf_url") or None,
        oa_pdf_version=chosen_pdf.get("version") if chosen_pdf.get("pdf_url") else None,
        version_label=primary.get("version"),
        abstract=abstract,
        abstract_origin=ABSTRACT_ORIGIN if abstract else None,
        identifiers=ids,
        raw=work,
        other_versions=other_versions,
        cited_by_count=work.get("cited_by_count") if isinstance(work.get("cited_by_count"), int) else None,
    )


async def search_works(
    client: httpx.AsyncClient,
    query: str,
    per_page: int,
    api_key: str | None = None,
    contact_email: str | None = None,
    works_filter: str | None = None,
) -> SearchOutcome:
    per_page = min(per_page, MAX_RESULTS)
    params: dict[str, Any] = {SEARCH_PARAM: query, "per_page": per_page, "select": SELECT}
    if works_filter:
        params["filter"] = works_filter
    if contact_email:
        params["mailto"] = contact_email
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    access_mode = "api_key" if api_key else "keyless"
    description = (f"GET {WORKS_URL} {SEARCH_PARAM}={query!r}" + (f" filter={works_filter}" if works_filter else "")
                   + f" per_page={per_page} access={access_mode}")
    response, outcome = await send(client, WORKS_URL, params, headers, description, access_mode, RATE_LIMIT_HEADERS, (api_key,))
    if response is None:
        return outcome
    try:
        payload = response.json()
        outcome.records = [_record(w) for w in payload["results"]]
        outcome.provider_total = (payload.get("meta") or {}).get("count")
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        outcome.status, outcome.error, outcome.records = "parse_error", str(exc)[:300], []
        return outcome
    outcome.status = "zero_results" if not outcome.records else "completed"
    outcome.raw_payload = payload
    return outcome
