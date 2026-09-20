"""arXiv API search adapter (keyless Atom feed; at most one request every three seconds).

Probed live on 2026-09-14: a term without a field prefix, or an unquoted phrase after one, is not read as a phrase
(`abs:molecular communication` matched 199,262 records, `abs:"molecular communication"` 476); AND, OR and ANDNOT
combine prefixed terms; an unbalanced query returns HTTP 400. A record is one arXiv version (`2204.08636v1`). Its DOI
is arXiv's DataCite DOI, which names every version of the preprint, so it never merges records. A DOI the authors added
(`arxiv:doi`) names the published version; it is kept as `published_doi` and only flags a suspected duplicate.

Paging (arXiv API User's Manual, "start and max_results paging", read 2026-09-21): `start` is the 0-based record the
page begins at and the manual asks for a 3-second delay between consecutive requests.
"""

from __future__ import annotations

import asyncio
import re
import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from deixis.providers.common import ProviderRecord, SearchOutcome, next_offset, normalize_doi, page_offset, send

PROVIDER_ID = "arxiv"
QUERY_URL = "https://export.arxiv.org/api/query"
ABSTRACT_ORIGIN = "provider_arxiv_summary"
MAX_RESULTS = 100
MIN_INTERVAL_SECONDS = 3.0
UNSTATED_RATE_LIMIT_WAIT = 15.0  # the second bounded retry waits 30 s when Retry-After is absent
MAX_RATE_LIMIT_WAIT = 30.0  # do not block a run for an unbounded provider-supplied delay
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom",
      "opensearch": "http://a9.com/-/spec/opensearch/1.1/"}

_lock = asyncio.Lock()
_last_request = 0.0


def _text(entry: ET.Element, path: str) -> str | None:
    node = entry.find(path, NS)
    return re.sub(r"\s+", " ", node.text).strip() if node is not None and node.text else None


def _record(entry: ET.Element) -> ProviderRecord:
    abs_url = _text(entry, "a:id") or ""
    match = re.search(r"arxiv\.org/abs/(.+?)(v\d+)?$", abs_url)
    base, version = (match.group(1), match.group(2)) if match else (abs_url, None)
    label = f"arXiv {version}" if version else "arXiv"
    pdf = next((link.get("href") for link in entry.findall("a:link", NS) if link.get("title") == "pdf"), None)
    abstract = _text(entry, "a:summary")
    published_doi = normalize_doi(_text(entry, "arxiv:doi"))
    identifiers = {"arxiv": base, "arxiv_version": f"{base}{version or ''}"} | ({"published_doi": published_doi} if published_doi else {})
    return ProviderRecord(
        provider_record_id=f"{base}{version or ''}",
        title=_text(entry, "a:title") or "(untitled)",
        authors=[n for n in (_text(a, "a:name") for a in entry.findall("a:author", NS)) if n],
        year=int(published[:4]) if (published := _text(entry, "a:published")) and published[:4].isdigit() else None,
        venue="arXiv",
        publication_type="preprint",
        doi=f"10.48550/arxiv.{base.lower()}",
        landing_url=abs_url or None,
        oa_pdf_url=pdf,
        oa_pdf_version=label if pdf else None,
        version_label=label,
        abstract=abstract,
        abstract_origin=ABSTRACT_ORIGIN if abstract else None,
        identifiers=identifiers,
        raw={"id": abs_url, "published_doi": published_doi, "journal_ref": _text(entry, "arxiv:journal_ref")},
        merge_by_doi=False,
    )


async def search(client: httpx.AsyncClient, query: str, limit: int, api_key: str | None = None,
                 contact_email: str | None = None, cursor: str | None = None) -> SearchOutcome:
    global _last_request
    count = min(limit, MAX_RESULTS)
    offset = page_offset(cursor)  # the unpaged request already starts at 0
    params: dict[str, Any] = {"search_query": query, "start": offset, "max_results": count, "sortBy": "relevance", "sortOrder": "descending"}
    description = (f"GET {QUERY_URL} search_query={query!r} max_results={count}"
                   + (f" start={offset}" if cursor is not None else "") + " sortBy=relevance access=keyless")
    async with _lock:
        wait = MIN_INTERVAL_SECONDS - (time.monotonic() - _last_request)
        if wait > 0:
            await asyncio.sleep(wait)
        response, outcome = await send(client, QUERY_URL, params, {}, description, "keyless",
                                       unstated_wait=UNSTATED_RATE_LIMIT_WAIT, max_retry_wait=MAX_RATE_LIMIT_WAIT)
        _last_request = time.monotonic()
    if response is None:
        return outcome
    try:
        feed = ET.fromstring(response.content)
        entries = feed.findall("a:entry", NS)
        total = feed.find("opensearch:totalResults", NS)
        outcome.records = [_record(e) for e in entries]
        outcome.provider_total = int(total.text) if total is not None and total.text else None
        if cursor is not None:
            outcome.next_cursor = next_offset(offset, len(outcome.records), count, outcome.provider_total)
    except (ET.ParseError, ValueError) as exc:
        outcome.status, outcome.error, outcome.records = "parse_error", str(exc)[:300], []
        return outcome
    outcome.status = "zero_results" if not outcome.records else "completed"
    outcome.raw_payload = {"feed_total": outcome.provider_total, "entries": [r.raw | {"title": r.title} for r in outcome.records]}
    return outcome
