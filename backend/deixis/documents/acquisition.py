"""Auditable PDF discovery by DOI, followed by version-gated retrieval."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import quote, urlsplit

import httpx

from deixis.documents import fetch, pdf
from deixis.providers import core, crossref
from deixis.providers.common import ProviderRecord, normalize_doi
from deixis.storage import db
from deixis.workflow.store import Store

OPENALEX_URL = "https://api.openalex.org/works"
CROSSREF_URL = "https://api.crossref.org/works"
SERPAPI_URL = "https://serpapi.com/search.json"
UNPAYWALL_URL = "https://api.unpaywall.org/v2"
OPENALEX_SELECT = "doi,display_name,primary_location,best_oa_location,locations"
# Crossref's IEEE text-mining links redirect to the paywalled IEEE document page instead of a PDF: all 6 tried on
# 2026-09-15/16 ended as not_pdf. They are not listed as candidates.
CROSSREF_SKIPPED_HOSTS = {"xplorestaging.ieee.org"}


@dataclass(frozen=True)
class Candidate:
    provider: str
    url: str
    landing_url: str | None
    version_label: str | None
    license: str | None
    identity_status: str
    version_status: str


@dataclass(frozen=True)
class Lookup:
    status: str
    candidates: list[Candidate]
    http_status: int | None = None
    error_code: str | None = None
    record: ProviderRecord | None = None


def _version_status(candidate: str | None, source: str | None) -> str:
    if not candidate or not source:
        return "uncertain"
    return "match" if candidate == source else "different"


def _unique(candidates: list[Candidate]) -> list[Candidate]:
    return list({c.url: c for c in candidates if c.url}.values())


async def unpaywall_lookup(client: httpx.AsyncClient, doi: str, source_version: str | None,
                           contact_email: str | None) -> Lookup:
    if not contact_email:
        return Lookup("auth_required", [], error_code="missing_contact_email")
    try:
        response = await client.get(f"{UNPAYWALL_URL}/{quote(doi, safe='')}", params={"email": contact_email}, timeout=30)
    except httpx.TimeoutException:
        return Lookup("timeout", [], error_code="timeout")
    except httpx.HTTPError as exc:
        return Lookup("failed", [], error_code=type(exc).__name__)
    if response.status_code == 404:
        return Lookup("zero_results", [], 404)
    if response.status_code == 429:
        return Lookup("rate_limited", [], 429, "rate_limited")
    if response.status_code in (401, 403, 422):
        return Lookup("auth_required", [], response.status_code, "email_rejected")
    if response.status_code != 200:
        return Lookup("failed", [], response.status_code, f"http_{response.status_code}")
    try:
        item = response.json()
        identity = "doi_verified" if normalize_doi(item.get("doi")) == doi else "mismatch"
        locations = list(item.get("oa_locations") or [])
        best = item.get("best_oa_location") or {}
        if best.get("url_for_pdf") and not any(location.get("url_for_pdf") == best["url_for_pdf"] for location in locations):
            locations.insert(0, best)
        candidates = [Candidate(
            "unpaywall", location["url_for_pdf"], location.get("url"), location.get("version"),
            location.get("license"), identity, _version_status(location.get("version"), source_version),
        ) for location in locations if location.get("url_for_pdf")]
        return Lookup("completed" if candidates else "zero_results", _unique(candidates), 200)
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        return Lookup("parse_error", [], 200, type(exc).__name__)


async def openalex_lookup(client: httpx.AsyncClient, doi: str, source_version: str | None,
                          api_key: str | None = None, contact_email: str | None = None) -> Lookup:
    params: dict[str, str] = {"select": OPENALEX_SELECT}
    if contact_email:
        params["mailto"] = contact_email
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        response = await client.get(f"{OPENALEX_URL}/https://doi.org/{quote(doi, safe='/')}", params=params, headers=headers, timeout=30)
    except httpx.TimeoutException:
        return Lookup("timeout", [], error_code="timeout")
    except httpx.HTTPError as exc:
        return Lookup("failed", [], error_code=type(exc).__name__)
    if response.status_code == 404:
        return Lookup("zero_results", [], 404)
    if response.status_code == 429:
        return Lookup("rate_limited", [], 429, "rate_limited")
    if response.status_code in (401, 403):
        return Lookup("auth_required", [], response.status_code, "auth_required")
    if response.status_code != 200:
        return Lookup("failed", [], response.status_code, f"http_{response.status_code}")
    try:
        work = response.json()
        identity = "doi_verified" if normalize_doi(work.get("doi")) == doi else "mismatch"
        candidates = [Candidate(
            "openalex", location["pdf_url"], location.get("landing_page_url"), location.get("version"),
            location.get("license"), identity, _version_status(location.get("version"), source_version),
        ) for location in work.get("locations") or [] if location.get("pdf_url")]
        return Lookup("completed" if candidates else "zero_results", _unique(candidates), 200)
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        return Lookup("parse_error", [], 200, type(exc).__name__)


def crossref_version(value: str | None) -> str | None:
    return {"vor": "publishedVersion", "am": "acceptedVersion"}.get((value or "").lower())


async def crossref_lookup(client: httpx.AsyncClient, doi: str, source_version: str | None,
                          contact_email: str | None = None) -> Lookup:
    params = {"mailto": contact_email} if contact_email else {}
    try:
        response = await client.get(f"{CROSSREF_URL}/{quote(doi, safe='')}", params=params, timeout=30)
    except httpx.TimeoutException:
        return Lookup("timeout", [], error_code="timeout")
    except httpx.HTTPError as exc:
        return Lookup("failed", [], error_code=type(exc).__name__)
    if response.status_code == 404:
        return Lookup("zero_results", [], 404)
    if response.status_code == 429:
        return Lookup("rate_limited", [], 429, "rate_limited")
    if response.status_code in (401, 403):
        return Lookup("auth_required", [], response.status_code, "auth_required")
    if response.status_code != 200:
        return Lookup("failed", [], response.status_code, f"http_{response.status_code}")
    try:
        item = response.json()["message"]
        identity = "doi_verified" if normalize_doi(item.get("DOI")) == doi else "mismatch"
        landing = item.get("URL")
        candidates = []
        for link in item.get("link") or []:
            url = link.get("URL")
            media = (link.get("content-type") or "").lower()
            if not url or ("pdf" not in media and not url.lower().split("?", 1)[0].endswith(".pdf")):
                continue
            if (urlsplit(url).hostname or "").lower() in CROSSREF_SKIPPED_HOSTS:
                continue
            version = crossref_version(link.get("content-version"))
            candidates.append(Candidate("crossref", url, landing, version, None, identity,
                                        _version_status(version, source_version)))
        record = crossref.record_from_item(item) if identity == "doi_verified" else None
        return Lookup("completed" if candidates else "zero_results", _unique(candidates), 200, record=record)
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        return Lookup("parse_error", [], 200, type(exc).__name__)


async def core_lookup(client: httpx.AsyncClient, doi: str, api_key: str | None) -> Lookup:
    """CORE works with this DOI and their CORE-hosted PDFs. CORE labels no file version, so every candidate is uncertain."""
    if not api_key:
        return Lookup("auth_required", [], error_code="missing_core_key")
    try:
        response = await client.get(core.SEARCH_URL, params={"q": f'doi:"{doi}"', "limit": 10},
                                    headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
    except httpx.TimeoutException:
        return Lookup("timeout", [], error_code="timeout")
    except httpx.HTTPError as exc:
        return Lookup("failed", [], error_code=type(exc).__name__)
    if response.status_code == 429:
        return Lookup("rate_limited", [], 429, "rate_limited")
    if response.status_code in (401, 403):
        return Lookup("auth_required", [], response.status_code, "auth_required")
    if response.status_code != 200:
        return Lookup("failed", [], response.status_code, f"http_{response.status_code}")
    try:
        candidates = []
        for work in response.json()["results"]:
            if normalize_doi(work.get("doi")) != doi:
                continue  # the DOI search also ranks works that only share parts of the DOI
            urls = [work.get("downloadUrl"), *(item.get("url") for item in work.get("links") or [] if item.get("type") == "download")]
            candidates += [Candidate("core", url, core.link(work, "display"), None, None, "doi_verified", "uncertain")
                           for url in urls if url]
        return Lookup("completed" if candidates else "zero_results", _unique(candidates), 200)
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        return Lookup("parse_error", [], 200, type(exc).__name__)


def _title_key(text: str | None) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").casefold()))


def _web_pdf_links(result: dict[str, Any]) -> list[str]:
    links = [resource.get("link") for resource in result.get("resources") or []
             if resource.get("link") and "pdf" in (resource.get("file_format") or "").casefold()]
    direct = result.get("link")
    if direct and direct.lower().split("?", 1)[0].endswith(".pdf"):
        links.append(direct)
    return list(dict.fromkeys(links))


async def web_lookup(client: httpx.AsyncClient, doi: str, title: str, api_key: str | None) -> Lookup:
    if not api_key:
        return Lookup("auth_required", [], error_code="missing_serpapi_key")
    query = f'"{title}"'
    params = {"engine": "google_scholar", "q": query, "num": 20, "hl": "en", "api_key": api_key}
    try:
        response = await client.get(SERPAPI_URL, params=params, timeout=60)
    except httpx.TimeoutException:
        return Lookup("timeout", [], error_code="timeout")
    except httpx.HTTPError as exc:
        return Lookup("failed", [], error_code=type(exc).__name__)
    if response.status_code in (401, 403):
        return Lookup("auth_required", [], response.status_code, "auth_required")
    if response.status_code == 429:
        return Lookup("rate_limited", [], 429, "rate_limited")
    if response.status_code != 200:
        return Lookup("failed", [], response.status_code, f"http_{response.status_code}")
    try:
        payload = response.json()
        if payload.get("error") and not payload.get("organic_results"):
            return Lookup("failed", [], 200, str(payload["error"])[:200])
        expected = _title_key(title)
        candidates = []
        for result in payload.get("organic_results") or []:
            actual = _title_key(result.get("title"))
            identity = "title_verified" if actual == expected else "unverified"
            for url in _web_pdf_links(result):
                candidates.append(Candidate("web_search", url, result.get("link"), None, None, identity, "uncertain"))
        return Lookup("completed" if candidates else "zero_results", _unique(candidates), 200)
    except (json.JSONDecodeError, TypeError) as exc:
        return Lookup("parse_error", [], 200, type(exc).__name__)


async def acquire_for_source(store: Store, research_id: str, source_version_id: str, client: httpx.AsyncClient,
                             papers_dir: Any, contact_email: str | None, serpapi_key: str | None,
                             fetcher: Callable[[str], Awaitable[fetch.FetchResult]] = fetch.fetch_pdf,
                             core_key: str | None = None, web_search: bool = True) -> dict[str, Any]:
    source = store.source(source_version_id)
    doi = normalize_doi(source.get("doi"))
    if not doi:
        raise ValueError("A DOI is required for verified PDF acquisition")
    lookups: list[tuple[str, str, Lookup]] = []
    unpaywall = await unpaywall_lookup(client, doi, source.get("version_label"), contact_email)
    lookups.append(("unpaywall", doi, unpaywall))
    oa = await openalex_lookup(client, doi, source.get("version_label"), contact_email=contact_email)
    lookups.append(("openalex", doi, oa))
    cr = await crossref_lookup(client, doi, source.get("version_label"), contact_email=contact_email)
    lookups.append(("crossref", doi, cr))
    lookups.append(("core", doi, await core_lookup(client, doi, core_key)))
    for provider, query, lookup in lookups:
        run_id = store.record_pdf_discovery(research_id, source_version_id, provider, query, lookup)
        store.record_pdf_candidates(source_version_id, run_id, lookup.candidates)
    if cr.record is not None:
        store.enrich_source("crossref", source_version_id, cr.record)

    asset_id = None
    if not store.has_asset(source_version_id):
        attempted_urls: set[str] = set()
        for candidate in store.pdf_candidates(source_version_id):
            if candidate["identity_status"] != "doi_verified" or candidate["version_status"] != "match":
                continue
            if candidate["candidate_url"] in attempted_urls:
                continue
            attempted_urls.add(candidate["candidate_url"])
            result = await fetcher(candidate["candidate_url"])
            store.record_pdf_attempt(candidate["id"], result)
            if result.status != "ok":
                continue
            asset_id = await _attach_pdf(store, source_version_id, result.data, papers_dir, "download",
                                         result.final_url or candidate["candidate_url"])
            break

    # A listed URL is not a found PDF: it may be gated, dead, HTML, or a different version. Make the fallback explicit
    # and retain its uncertain-version candidates for manual review/upload; never silently attach them.
    if web_search and not store.has_asset(source_version_id):
        web_query = f'"{source["title"]}"'
        web = await web_lookup(client, doi, source["title"], serpapi_key)
        run_id = store.record_pdf_discovery(research_id, source_version_id, "web_search", web_query, web)
        store.record_pdf_candidates(source_version_id, run_id, web.candidates)
        lookups.append(("web_search", web_query, web))

    return {"source_version_id": source_version_id, "lookups": len(lookups), "asset_id": asset_id,
            "candidates": len(store.pdf_candidates(source_version_id)), "pdf_found": store.has_asset(source_version_id)}


async def _attach_pdf(store: Store, source_version_id: str, data: bytes, papers_dir: Any, origin: str,
                      retrieved_from: str | None) -> str:
    sha = hashlib.sha256(data).hexdigest()
    papers_dir.mkdir(parents=True, exist_ok=True)
    path = papers_dir / f"{sha}.pdf"
    if not path.exists():
        path.write_bytes(data)
    extraction = await asyncio.to_thread(pdf.extract_pdf, path)
    return store.add_asset_with_pages(source_version_id, sha, len(data), path.name, origin, retrieved_from, None,
                                      extraction, pdf.EXTRACTION_VERSION, pdf.chunk_page)


async def attach_confirmed_candidate(store: Store, source_version_id: str, candidate: dict[str, Any], papers_dir: Any,
                                     fetcher: Callable[[str], Awaitable[fetch.FetchResult]] = fetch.fetch_pdf) -> fetch.FetchResult:
    result = await fetcher(candidate["candidate_url"])
    store.record_pdf_attempt(candidate["id"], result)
    if result.status == "ok":
        # The version claim is the user's, not the provider's, so the file is recorded as their confirmed copy.
        await _attach_pdf(store, source_version_id, result.data, papers_dir, "user_upload",
                          result.final_url or candidate["candidate_url"])
    return result
