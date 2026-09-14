"""SerpApi Google Scholar adapter: supplementary discovery, never a fallback for another provider.

Probed live on 2026-09-14: `engine=google_scholar` returns at most 20 organic results with title, link, a
`publication_info.summary` line ("authors - venue, year - host") and a snippet, but no DOI and no abstract. The snippet
is a search-page excerpt, so it is kept in the raw payload only and never stored as an abstract. PDF links point to
copies of unknown version and are not attached. An invalid key answers 401; the free plan allows 250 searches a month,
so a 429 (searches exhausted) is not retried. The key travels as the `api_key` query parameter and is never recorded.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from deixis.providers.common import ProviderRecord, SearchOutcome, normalize_doi, send, year_of

PROVIDER_ID = "serpapi"
SEARCH_URL = "https://serpapi.com/search.json"
MAX_RESULTS = 20
NO_RESULTS = "hasn't returned any results"


def _record(result: dict[str, Any]) -> ProviderRecord:
    info = result.get("publication_info") or {}
    summary = info.get("summary") or ""
    parts = [p.strip() for p in summary.split(" - ")]
    venue = re.sub(r",?\s*(1[5-9]|20)\d\d$", "", parts[1]).strip(" ,…") if len(parts) > 2 else None
    link = result.get("link")
    doi = normalize_doi(urlparse(link).path.lstrip("/")) if link and urlparse(link).netloc.endswith("doi.org") else None
    return ProviderRecord(
        provider_record_id=str(result.get("result_id")),
        title=result.get("title") or "(untitled)",
        authors=[a["name"] for a in info.get("authors") or [] if a.get("name")] or ([parts[0]] if len(parts) > 1 and parts[0] else []),
        year=year_of(parts[1] if len(parts) > 1 else summary),
        venue=venue or None,
        publication_type=result.get("type"),
        doi=doi,
        landing_url=link,
        oa_pdf_url=None,
        oa_pdf_version=None,
        version_label=None,
        abstract=None,
        abstract_origin=None,
        identifiers={"google_scholar_result_id": str(result.get("result_id"))},
        raw=result,
    )


async def search(client: httpx.AsyncClient, query: str, limit: int, api_key: str | None = None,
                 contact_email: str | None = None) -> SearchOutcome:
    count = min(limit, MAX_RESULTS)
    params = {"engine": "google_scholar", "q": query, "num": count, "hl": "en", "api_key": api_key or ""}
    description = f"GET {SEARCH_URL} engine=google_scholar q={query!r} num={count} access=api_key"
    response, outcome = await send(client, SEARCH_URL, params, {}, description, "api_key", (), (api_key,), timeout=60.0,
                                   retry_rate_limit=False)
    if response is None:
        return outcome
    try:
        payload = response.json()
        results = payload.get("organic_results") or []
        error = payload.get("error")
        outcome.records = [_record(r) for r in results]
        outcome.provider_total = (payload.get("search_information") or {}).get("total_results")
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
        outcome.status, outcome.error, outcome.records = "parse_error", str(exc)[:300], []
        return outcome
    for key in ("search_parameters", "serpapi_pagination", "pagination", "search_metadata"):
        payload.pop(key, None)  # these repeat the request, including links that carry the key
    if error and not results and NO_RESULTS not in error:
        outcome.status, outcome.delivery_class, outcome.error = "failed", "rejected_not_executed", error[:300]
        return outcome
    outcome.status = "zero_results" if not outcome.records else "completed"
    outcome.raw_payload = json.loads(json.dumps(payload).replace(api_key, "<redacted>")) if api_key else payload
    return outcome
