"""Auditable PDF discovery by DOI, followed by version-gated retrieval."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
import weakref
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote, urlsplit

import httpx

from deixis.documents import fetch, jats, pdf
from deixis.domain.limits import error_name
from deixis.providers import core, crossref
from deixis.providers.common import ProviderRecord, begin_request, normalize_doi, settle_request
from deixis.storage import db
from deixis.workflow.run import fast_path
from deixis.workflow.run.store import Store
from deixis.workflow.read import file_restore

OPENALEX_URL = "https://api.openalex.org/works"
CROSSREF_URL = "https://api.crossref.org/works"
SERPAPI_URL = "https://serpapi.com/search.json"
EUROPEPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EUROPEPMC_LANDING_URL = "https://europepmc.org/article/PMC/{pmcid}"
XML_MEDIA_TYPES = ("application/xml", "text/xml")
ELSEVIER_ARTICLE_URL = "https://api.elsevier.com/content/article/doi/{doi}"
# Elsevier's own DOI prefix: its article API is asked for these alone.
ELSEVIER_DOI_PREFIX = "10.1016/"
ELSEVIER_KEY_HEADER = "X-ELS-APIKey"
UNPAYWALL_URL = "https://api.unpaywall.org/v2"
OPENALEX_SELECT = "doi,display_name,primary_location,best_oa_location,locations"
# Crossref's IEEE text-mining links redirect to the paywalled IEEE document page instead of a PDF: all 6 tried on
# 2026-09-15/16 ended as not_pdf. They are not listed as candidates.
CROSSREF_SKIPPED_HOSTS = {"xplorestaging.ieee.org"}
# The `error_code` of an OpenAlex lookup that its daily budget refused (or that was not sent because it had been).
QUOTA_EXHAUSTED = "quota_exhausted"
# The lookups `acquire_for_source` always asks, in this order; a record with some but not all of them was interrupted.
REQUIRED_ROUTES = frozenset({"unpaywall", "openalex", "crossref", "core"})
# Which provider's copy is tried first (`candidate_order`), ahead of the order the answers happened to arrive in.
# Europe PMC's rendition and a web-search copy are tried by their own steps, after these, and keep their places.
PROVIDER_ORDER = ("unpaywall", "openalex", "crossref", "core", "elsevier", "europepmc", "web_search")
# Within one provider: a copy of this record's own version first, then one whose version the provider did not name.
VERSION_STATUS_ORDER = ("match", "different", "uncertain")
# And then how the identity was settled: a verified DOI before a title alone.
IDENTITY_ORDER = ("doi_verified", "title_verified", "unverified", "mismatch")


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
    # Web search only: results whose title is not this work's title. They are counted, not kept as candidates.
    other_title_count: int = 0
    # OpenAlex only, with `error_code == QUOTA_EXHAUSTED`: when the daily budget comes back (ISO, UTC), if it said.
    reset_at: str | None = None
    # This attempt's identity, whatever its outcome: made for OpenAlex when the request was about to be sent (or, for a
    # lookup the closed budget kept from being sent, when it was skipped), for the other routes when the answer is in
    # hand. Storing the same outcome twice stores it once.
    attempt_id: str | None = None


@dataclass
class OpenAlexBudget:
    """What a run knows about OpenAlex's daily budget; the flow keeps one per run, loaded from the store.

    `reset_at` is when a refusal said the budget returns. Until then no OpenAlex request can succeed, so the run's
    OpenAlex lookups are not sent: their rows say so (`QUOTA_EXHAUSTED`, no HTTP status) and the work is not settled
    without them. It ends by itself at `reset_at`; the counts live in the store (`openalex_budget_runs`).
    """

    reset_at: str | None = None

    @property
    def exhausted(self) -> bool:
        try:
            return self.reset_at is not None and datetime.fromisoformat(self.reset_at) > datetime.now(timezone.utc)
        except (ValueError, TypeError):
            return False

    def refresh(self, stored: str | None) -> None:
        """Take the later of what this run remembers and what the store holds: the budget is the key's, not a run's."""
        if stored and (self.reset_at is None or stored > self.reset_at):
            self.reset_at = stored


# One lock for OpenAlex's metered key, held while a request on it is in flight *and* while its refusal is recorded.
# A per-host gate cannot do this job: the metadata host and the content host are two hosts spending one key, and the
# host lock is released as soon as a response returns, so the next request would read a budget that still says the
# key is good. Kept per event loop for the reason `fetch.host_gate` is.
_budget_gates: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = weakref.WeakKeyDictionary()


def budget_gate() -> asyncio.Lock:
    """The lock a request that spends OpenAlex's daily budget holds, until its answer is stored."""
    loop = asyncio.get_running_loop()
    gate = _budget_gates.get(loop)
    if gate is None:
        gate = _budget_gates[loop] = asyncio.Lock()
    return gate


def _decimal(value: str | None) -> Decimal | None:
    """The exact finite number a header states, or None; no float, so a tiny balance never rounds to zero."""
    try:
        number = Decimal(value.strip()) if value is not None else None
    except (InvalidOperation, ValueError):
        return None
    return number if number is not None and number.is_finite() and not number.is_signed() else None


def openalex_quota_exhausted(headers: Any) -> bool:
    """Whether a 429 is OpenAlex's daily budget running out, read from its headers; anything unclear is False.

    The remaining daily dollars must be stated as exactly zero, and a prepaid balance, if stated, must be zero too:
    a refusal that leaves money to spend, or states none, is a rate limit like any other and keeps the short-wait handling.
    """
    remaining = _decimal(headers.get("x-ratelimit-remaining-usd"))
    if remaining is None or remaining != 0:
        return False
    prepaid = headers.get("x-ratelimit-prepaid-remaining-usd")
    return prepaid is None or _decimal(prepaid) == 0


def budget_reset_at(headers: Any) -> str:
    """When the budget returns: `x-ratelimit-reset` is delta seconds (OpenAlex's documentation); a missing, malformed
    or beyond-a-day value is ignored and the next midnight UTC, when the daily budget renews, is used instead."""
    now = datetime.now(timezone.utc)
    seconds = _decimal(headers.get("x-ratelimit-reset"))
    if seconds is not None and seconds <= 86400:
        return (now + timedelta(seconds=int(seconds))).isoformat(timespec="seconds")
    return (now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat(timespec="seconds")


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
        async with fetch.host_gate(UNPAYWALL_URL):  # one request per host at a time (slice 13e)
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


def attempted(lookup: Lookup) -> Lookup:
    """The lookup with an attempt identity: its own if it has one, else a new one."""
    return lookup if lookup.attempt_id else replace(lookup, attempt_id=uuid.uuid4().hex)


async def openalex_lookup(client: httpx.AsyncClient, doi: str, source_version: str | None,
                          api_key: str | None = None, contact_email: str | None = None, *,
                          budget: OpenAlexBudget | None = None) -> Lookup:
    """One OpenAlex lookup by DOI; with a `budget` it is not sent once the budget is exhausted, and learns of a refusal.

    The budget is read inside the host gate, so a lookup that waited behind the one the budget refused is not sent.
    Whatever the outcome of a request that was made, it carries the identity made just before the request.
    """
    made: list[str] = []
    lookup = await _openalex_request(client, doi, source_version, api_key, contact_email, budget, made)
    return lookup if lookup.attempt_id or not made else replace(lookup, attempt_id=made[0])


async def _openalex_request(client: httpx.AsyncClient, doi: str, source_version: str | None, api_key: str | None,
                            contact_email: str | None, budget: OpenAlexBudget | None, made: list[str]) -> Lookup:
    params: dict[str, str] = {"select": OPENALEX_SELECT}
    if contact_email:
        params["mailto"] = contact_email
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    begun = None
    try:
        async with fetch.host_gate(OPENALEX_URL):  # one request per host at a time (slice 13e)
            if budget is not None and budget.exhausted:  # no request is made: a skip, with no HTTP status
                return Lookup("rate_limited", [], None, QUOTA_EXHAUSTED, reset_at=budget.reset_at,
                              attempt_id=uuid.uuid4().hex)
            attempt_id = uuid.uuid4().hex
            made.append(attempt_id)
            begun = begin_request(OPENALEX_URL)  # stored before the client has it
            try:
                response = await client.get(f"{OPENALEX_URL}/https://doi.org/{quote(doi, safe='/')}", params=params,
                                            headers=headers, timeout=30)
            except asyncio.CancelledError:
                settle_request(begun, False, False, "cancelled", None, unknown=True)  # not known whether sent
                raise
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
        # Not sent: the connection never opened, or none came free from the pool.
        settle_request(begun, False, False, "before_send", None)
        return Lookup("timeout" if isinstance(exc, httpx.TimeoutException) else "failed", [],
                      error_code="timeout" if isinstance(exc, httpx.TimeoutException) else error_name(exc))
    except httpx.TimeoutException:
        settle_request(begun, True, False, "after_send_unknown", None)
        return Lookup("timeout", [], error_code="timeout")
    except httpx.HTTPError as exc:
        settle_request(begun, True, False, "after_send_unknown", None)
        return Lookup("failed", [], error_code=type(exc).__name__)
    # A 404 is an answer (OpenAlex holds no such DOI); any other 4xx, a 429 included, is a refusal.
    refused = 400 <= response.status_code < 500 and response.status_code != 404
    settle_request(begun, True, refused, "rejected_not_executed" if refused
                   else "after_send_unknown" if response.status_code >= 500 else None, response.status_code)
    if response.status_code == 404:
        return Lookup("zero_results", [], 404)
    if response.status_code == 429:
        if openalex_quota_exhausted(response.headers):
            reset_at = budget_reset_at(response.headers)
            if budget is not None:
                budget.reset_at = reset_at
            return Lookup("rate_limited", [], 429, QUOTA_EXHAUSTED, reset_at=reset_at, attempt_id=attempt_id)
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
        async with fetch.host_gate(CROSSREF_URL):  # one request per host at a time (slice 13e)
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
        async with fetch.host_gate(core.SEARCH_URL):  # one request per host at a time (slice 13e)
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


async def europepmc_lookup(client: httpx.AsyncClient, doi: str, source_version: str | None) -> Lookup:
    """This DOI's work in Europe PMC's open-access subset, as a `fullTextXML` candidate (SW21).

    Only a result whose DOI is the record's, with a PMCID, open access, in Europe PMC and not an author manuscript is
    a candidate: the subset holds the copy the publisher deposited (`publishedVersion`), `fullTextXML` gives nothing
    for an author manuscript, and an accepted manuscript's identity is another piece of work. The version check is
    the other lookups'.
    """
    try:
        async with fetch.host_gate(EUROPEPMC_SEARCH_URL):  # one request per host at a time (slice 13e)
            response = await client.get(EUROPEPMC_SEARCH_URL, params={
                "query": f'DOI:"{doi}"', "resultType": "core", "format": "json"}, timeout=30)
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
        candidates = []
        for result in response.json()["resultList"]["result"]:
            pmcid = result.get("pmcid") or ""
            if normalize_doi(result.get("doi")) != doi or not re.fullmatch(r"PMC\d+", pmcid):
                continue
            if (result.get("isOpenAccess"), result.get("inEPMC"), result.get("authMan")) != ("Y", "Y", "N"):
                continue
            candidates.append(Candidate("europepmc", jats.FULLTEXT_URL.format(pmcid=pmcid),
                                        EUROPEPMC_LANDING_URL.format(pmcid=pmcid), "publishedVersion",
                                        result.get("license"), "doi_verified",
                                        _version_status("publishedVersion", source_version)))
        return Lookup("completed" if candidates else "zero_results", _unique(candidates), 200)
    except (json.JSONDecodeError, TypeError, KeyError, AttributeError) as exc:
        return Lookup("parse_error", [], 200, type(exc).__name__)


async def elsevier_lookup(client: httpx.AsyncClient, doi: str, source_version: str | None, api_key: str | None) -> Lookup:
    """Elsevier's article API for a 10.1016 DOI, read with the Scopus key: a candidate only for an open-access article.

    Publisher sites answer a non-browser client with a bot check (403), while this API serves the publisher's own PDF to
    a key holder (measured 2026-10-24: 7 of 7 open-access ScienceDirect articles). Only a record whose DOI is this one
    and that Elsevier marks open access is a candidate: for any other article a key outside an entitled network can be
    given less than the whole file, so it is not asked. The candidate's address holds no key (`fetcher_for` sends
    it as a header, to this host alone). The copy is the publisher's (`publishedVersion`).
    """
    if not api_key:
        return Lookup("auth_required", [], error_code="missing_elsevier_key")
    url = ELSEVIER_ARTICLE_URL.format(doi=quote(doi, safe="/"))
    try:
        async with fetch.host_gate(url):  # one request per host at a time (slice 13e)
            response = await client.get(url, params={"view": "META"}, timeout=30,
                                        headers={ELSEVIER_KEY_HEADER: api_key, "Accept": "application/json"})
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
        record = response.json()["full-text-retrieval-response"]["coredata"]
        if normalize_doi(record.get("prism:doi")) != doi:
            return Lookup("zero_results", [], 200, "doi_mismatch")
        if not (record.get("openaccessArticle") is True or str(record.get("openaccess")) == "1"):
            return Lookup("zero_results", [], 200, "not_open_access")
        landing = next((link.get("@href") for link in record.get("link") or []
                        if isinstance(link, dict) and link.get("@rel") == "scidir"), None)
        candidate = Candidate("elsevier", f"{url}?httpAccept=application/pdf", landing, "publishedVersion",
                              record.get("openaccessUserLicense"), "doi_verified",
                              _version_status("publishedVersion", source_version))
        return Lookup("completed", [candidate], 200)
    except (json.JSONDecodeError, TypeError, KeyError, AttributeError) as exc:
        return Lookup("parse_error", [], 200, type(exc).__name__)


def required_routes(doi: str | None) -> frozenset[str]:
    """The lookups `acquire_for_source` asks for this DOI: the four, and Elsevier's for a 10.1016 DOI. A history without
    one of them (an interruption, or a record looked up before the Elsevier route existed) is asked again.

    A record with no DOI asks none of them: all five address the work by its DOI, so a history that holds none of
    them is complete for that record, not interrupted.
    """
    if not doi:
        return frozenset()
    return REQUIRED_ROUTES | {"elsevier"} if doi.startswith(ELSEVIER_DOI_PREFIX) else REQUIRED_ROUTES


def needs_readable_copy(store: Store, source_version_id: str) -> bool:
    """Whether this record still has no copy whose text can be read.

    The design keeps four states apart: the source found, the file downloaded, the version matched, and the text
    readable. A stored file is not the last of them — a scan, a failed extraction, a download that is a cover
    page. This asks for the last one, and the routes that can put a copy on **another row** of the work read it:
    a record whose own file holds no text used to block them, so the work was settled without text although a
    readable copy of another version was there to be had. The record's own row is not asked again, because a
    version holds at most one file in use (`source_assets_one_in_use`) and replacing it is the person's action.
    """
    return not store.has_asset(source_version_id) or not store.has_pdf_text(source_version_id)


def candidate_order(candidates: list[dict[str, Any]], rule: str | None = fast_path.ACQUIRE_RULE) -> list[dict[str, Any]]:
    """The order a download loop tries this record's candidates in, by the candidate's own fields alone.

    The stored rows are read in arrival order, which is a record of when each provider answered, not a judgement:
    the same candidate set could give a different file on a different day, and a provider that happened to answer
    first could win over a better copy. The order here is the named rule `fast_path.ACQUIRE_RULE` freezes into a
    run's budget: the provider's place in `PROVIDER_ORDER`, then a version the provider named as this record's own,
    then how the identity was settled, then the URL — unique per provider by the table's own key, so no two
    candidates of one record can tie.

    `rule` is what the caller's run froze. A run queued before the rule existed carries none, and `None` keeps the
    arrival order it would have downloaded under: a half-finished lookup it resumes picks the file it would have
    picked. A caller with no run of its own (the person's own "Find PDF") takes the rule.
    """
    if rule is None:
        return list(candidates)

    def key(candidate: dict[str, Any]) -> tuple[int, int, int, str]:
        provider = candidate["provider"]
        version, identity = candidate["version_status"], candidate["identity_status"]
        return (PROVIDER_ORDER.index(provider) if provider in PROVIDER_ORDER else len(PROVIDER_ORDER),
                VERSION_STATUS_ORDER.index(version) if version in VERSION_STATUS_ORDER else len(VERSION_STATUS_ORDER),
                IDENTITY_ORDER.index(identity) if identity in IDENTITY_ORDER else len(IDENTITY_ORDER),
                candidate["candidate_url"])

    return sorted(candidates, key=key)


def fetcher_for(candidate: dict[str, Any], fetcher: Callable[[str], Awaitable[fetch.FetchResult]],
                elsevier_key: str | None, contact_email: str | None) -> Callable[[str], Awaitable[fetch.FetchResult]]:
    """The fetch for this candidate: an Elsevier API copy through `fetch_pdf` with the key sent to its own https origin
    alone (`_fetch`), any other through `fetcher`."""
    if candidate["provider"] != "elsevier":
        return fetcher
    return lambda url: fetch.fetch_pdf(url, email=contact_email,
                                       headers={ELSEVIER_KEY_HEADER: elsevier_key} if elsevier_key else None)


def fetch_xml(url: str) -> Awaitable[fetch.FetchResult]:
    """Europe PMC's full text through `fetch_file`'s protections; an answer of another type comes back `wrong_type`."""
    return fetch.fetch_file(url, XML_MEDIA_TYPES)


async def _render_candidate(store: Store, candidate: dict[str, Any],
                            xml_fetcher: Callable[[str], Awaitable[fetch.FetchResult]]) -> bytes | None:
    """A Europe PMC candidate's XML fetched and drawn as a PDF, or None; the attempt is recorded either way.

    A refusal or a failed drawing is recorded on the candidate as `failed` with its own error code and never raises,
    so the caller goes on to the next candidate.
    """
    url = candidate["candidate_url"]
    result = await xml_fetcher(url)
    if result.status != "ok":
        store.record_pdf_attempt(candidate["id"], result)
        return None
    rendition = await asyncio.to_thread(jats.render_pdf, result.data)
    status, error = ("ok", None) if rendition.status == "ok" else ("failed", rendition.status)
    store.record_pdf_attempt(candidate["id"], fetch.FetchResult(status, final_url=result.final_url or url,
                                                                 http_status=result.http_status, error=error))
    return rendition.data if rendition.status == "ok" else None


async def _attach_rendition(store: Store, source_version_id: str, candidate: dict[str, Any], data: bytes,
                            papers_dir: Any, *, research_id: str | None = None,
                            recovery_dir: Path | None = None,
                            before_publish: Callable[[], Awaitable[None]] | None = None) -> str:
    # The asset names the fullTextXML address it was drawn from, not the address the XML finally came from, and the
    # file name code gives it, so the rendition is recognised on every surface (`jats.RENDITION_SQL`).
    url = candidate["candidate_url"]
    return await _attach_pdf(store, source_version_id, data, papers_dir, "download", url,
                             filename=jats.filename(url.rsplit("/", 2)[-2]), research_id=research_id,
                             recovery_dir=recovery_dir, before_publish=before_publish)


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
        candidates, other_titles = [], 0
        for result in payload.get("organic_results") or []:
            # Scholar also returns related papers for a quoted title; a PDF of another paper is not a copy of this one.
            if _title_key(result.get("title")) != expected:
                other_titles += 1
                continue
            for url in _web_pdf_links(result):
                candidates.append(Candidate("web_search", url, result.get("link"), None, None, "title_verified", "uncertain"))
        return Lookup("completed" if candidates else "zero_results", _unique(candidates), 200, other_title_count=other_titles)
    except (json.JSONDecodeError, TypeError) as exc:
        return Lookup("parse_error", [], 200, type(exc).__name__)


async def acquire_for_source(store: Store, research_id: str, source_version_id: str, client: httpx.AsyncClient,
                             papers_dir: Any, contact_email: str | None, serpapi_key: str | None,
                             fetcher: Callable[[str], Awaitable[fetch.FetchResult]] = fetch.fetch_pdf,
                             core_key: str | None = None, web_search: bool = True,
                             other_versions: bool = False,
                             xml_fetcher: Callable[[str], Awaitable[fetch.FetchResult]] = fetch_xml, *,
                             recovery_dir: Path | None = None,
                             openalex_budget: OpenAlexBudget | None = None,
                             workflow_run_id: str | None = None,
                             before_publish: Callable[[], Awaitable[None]] | None = None,
                             elsevier_key: str | None = None,
                             candidate_rule: str | None = fast_path.ACQUIRE_RULE) -> dict[str, Any]:
    """Look this record's DOI up in Unpaywall, OpenAlex, Crossref and CORE and retrieve a copy of its own version.

    A 10.1016 DOI is also looked up in Elsevier's article API (`elsevier_lookup`, with `elsevier_key`, the Scopus key);
    without the key that lookup is stored as `auth_required` and nothing is sent. Its PDF is tried with the others.

    When none of their verified copies gave a file, Europe PMC is asked once (SW21): its open-access full text
    is drawn as a PDF labelled as a rendition and attached by the same version rule.

    `other_versions` is the full-text retrieval run's one addition: when the record's own version gave no
    file, a verified copy of a *different declared* version opens its own row under the same work and is attached
    there, never onto the published record. Without it the function is what it has always been, and a copy of
    uncertain version still waits for the user in both.

    `openalex_budget` is a run's memory of OpenAlex's daily budget (see `OpenAlexBudget`): once it is exhausted the
    OpenAlex lookup is recorded as not sent, and a refusal met here exhausts it. Without it every record asks.
    `workflow_run_id` is the run the refusals are counted under (`Store.record_pdf_discovery`).

    A record with **no DOI** is not refused any more. All five lookups and Europe PMC address the work by its DOI,
    so none of them is asked; the record goes down the routes that do not need one, and what it could and could not
    ask is in the result rather than in an exception the caller had to avoid by not calling at all.
    """
    recovery_dir = file_restore.resolve_recovery_dir(store, papers_dir, recovery_dir)
    source = store.source(source_version_id)
    doi = normalize_doi(source.get("doi"))
    lookups: list[tuple[str, str, Lookup]] = []

    def record(provider: str, lookup: Lookup) -> None:
        # Each answer is stored the moment it is in hand, while the other routes are still in flight: an interruption
        # between two answers must not lose what OpenAlex's budget said.
        lookup = attempted(lookup)
        lookups.append((provider, doi, lookup))
        with db.transaction(store.conn):  # the answer and its candidates are stored together or not at all
            run_id = store.record_pdf_discovery(research_id, source_version_id, provider, doi, lookup, workflow_run_id)
            store.record_pdf_candidates(source_version_id, run_id, lookup.candidates)

    # The routes are asked together — they are five hosts, and one answering slowly no longer holds the others up —
    # and each answer is still stored the moment it is in hand. Which order the rows land in is a record of who
    # answered first and decides nothing: `candidate_order` settles which copy is downloaded.
    crossref_answer: list[Lookup] = []

    async def unpaywall_route() -> None:
        record("unpaywall", await unpaywall_lookup(client, doi, source.get("version_label"), contact_email))

    async def openalex_route() -> None:
        # The budget's lock is held across the request *and* its recording: a refusal must be stored before another
        # request on the same key may read the budget, or every route would meet the same refusal in turn.
        async with budget_gate():
            if openalex_budget is not None:
                openalex_budget.refresh(store.openalex_budget_reset())
            record("openalex", await openalex_lookup(client, doi, source.get("version_label"),
                                                     contact_email=contact_email, budget=openalex_budget))

    async def crossref_route() -> None:
        cr = await crossref_lookup(client, doi, source.get("version_label"), contact_email=contact_email)
        crossref_answer.append(cr)
        record("crossref", cr)

    async def core_route() -> None:
        record("core", await core_lookup(client, doi, core_key))

    async def elsevier_route() -> None:
        record("elsevier", await elsevier_lookup(client, doi, source.get("version_label"), elsevier_key))

    routes = [unpaywall_route(), openalex_route(), crossref_route(), core_route()] if doi else []
    if "elsevier" in required_routes(doi):
        routes.append(elsevier_route())
    tasks = [asyncio.create_task(route) for route in routes]

    async def stop(leftover: Any) -> None:
        for task in leftover:
            task.cancel()
        await asyncio.gather(*leftover, return_exceptions=True)

    # One route raising — an answer no parser expected, a stop — must not leave the others writing rows behind the
    # caller's back: the rest are cancelled and awaited before the failure leaves. A cancellation of the whole
    # acquisition takes them down the same way.
    if tasks:
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        except BaseException:
            await stop(tasks)
            raise
        await stop(pending)
        for task in done:
            task.result()  # the first failure, if there was one
    cr = crossref_answer[0] if crossref_answer else None
    if cr is not None and cr.record is not None:
        if before_publish is not None:
            await before_publish()
        store.enrich_source("crossref", source_version_id, cr.record)

    asset_id = None
    # A version holds at most one file in use (`source_assets_one_in_use`), so a record that already has one is
    # not given a second here even when no text could be read from it: replacing a file is the person's action.
    # What the unreadable file does not block any more is the *other* rows this work may have (below).
    if not store.has_asset(source_version_id):
        attempted_urls: set[str] = set()
        for candidate in candidate_order(store.pdf_candidates(source_version_id), candidate_rule):
            if candidate["identity_status"] != "doi_verified" or candidate["version_status"] != "match":
                continue
            if candidate["provider"] == "europepmc":
                continue  # an XML full text, tried below only when no PDF came
            if candidate["candidate_url"] in attempted_urls:
                continue
            attempted_urls.add(candidate["candidate_url"])
            result = await fetcher_for(candidate, fetcher, elsevier_key, contact_email)(candidate["candidate_url"])
            store.record_pdf_attempt(candidate["id"], result)
            if result.status != "ok":
                continue
            asset_id = await _attach_pdf(store, source_version_id, result.data, papers_dir, "download",
                                         result.final_url or candidate["candidate_url"], research_id=research_id,
                                         recovery_dir=recovery_dir, before_publish=before_publish)
            break

    # Europe PMC only for a record still without a readable file, after the four lookups and their verified
    # copies (SW21); it addresses the work by DOI, so a record without one does not ask.
    if doi and not store.has_asset(source_version_id):
        europepmc = await europepmc_lookup(client, doi, source.get("version_label"))
        europepmc = attempted(europepmc)
        run_id = store.record_pdf_discovery(research_id, source_version_id, "europepmc", doi, europepmc)
        store.record_pdf_candidates(source_version_id, run_id, europepmc.candidates)
        lookups.append(("europepmc", doi, europepmc))
        tried: set[str] = set()
        for candidate in candidate_order(store.pdf_candidates(source_version_id), candidate_rule):
            if (candidate["provider"] != "europepmc" or candidate["identity_status"] != "doi_verified"
                    or candidate["version_status"] != "match" or candidate["candidate_url"] in tried):
                continue
            tried.add(candidate["candidate_url"])
            if (data := await _render_candidate(store, candidate, xml_fetcher)) is not None:
                asset_id = await _attach_rendition(store, source_version_id, candidate, data, papers_dir,
                                                  research_id=research_id, recovery_dir=recovery_dir,
                                                  before_publish=before_publish)
                break

    lookup_version_id = None
    if other_versions and needs_readable_copy(store, source_version_id):
        asset_id, lookup_version_id = await _attach_other_version(
            store, research_id, source_version_id, papers_dir, fetcher, xml_fetcher, recovery_dir=recovery_dir,
            before_publish=before_publish, elsevier_key=elsevier_key, contact_email=contact_email,
            candidate_rule=candidate_rule)

    # A listed URL is not a found PDF: it may be gated, dead, HTML, or a different version. Make the fallback explicit
    # and retain its uncertain-version candidates for manual review/upload; never silently attach them.
    # The web search asks by title, not by DOI, so a record without one asks it too; what it finds keeps waiting
    # for the person as `title_verified` and `uncertain`, as it always has.
    if web_search and not store.has_asset(source_version_id):
        web_query = f'"{source["title"]}"'
        web = await web_lookup(client, doi or "", source["title"], serpapi_key)
        web = attempted(web)
        run_id = store.record_pdf_discovery(research_id, source_version_id, "web_search", web_query, web)
        store.record_pdf_candidates(source_version_id, run_id, web.candidates)
        lookups.append(("web_search", web_query, web))

    # Found, downloaded and readable are three states, not one: a record whose file holds no text is reported as
    # having a file and no text, and the routes a record with no DOI could not ask are named rather than implied.
    return {"source_version_id": source_version_id, "lookups": len(lookups), "asset_id": asset_id,
            "candidates": len(store.pdf_candidates(source_version_id)),
            "pdf_found": store.has_asset(source_version_id) or lookup_version_id is not None,
            "has_text": store.has_pdf_text(source_version_id),
            **({} if doi else {"doi_routes": "no_doi"}),
            **({"lookup_version_id": lookup_version_id} if lookup_version_id else {})}


# Which declared version is tried first when the record's own version gave nothing: the published file, then the
# accepted manuscript, then the submitted one. Named deviation from SW10.3, which orders by who hosts the copy
# (publisher, preprint server, author or institution): a candidate row carries the version label a provider
# declared, not its host. How much this order gains was not measured.
VERSION_ORDER = ("publishedVersion", "acceptedVersion", "submittedVersion")


async def _attach_other_version(store: Store, research_id: str, source_version_id: str, papers_dir: Any,
                                fetcher: Callable[[str], Awaitable[fetch.FetchResult]],
                                xml_fetcher: Callable[[str], Awaitable[fetch.FetchResult]] = fetch_xml, *,
                                recovery_dir: Path | None = None,
                                before_publish: Callable[[], Awaitable[None]] | None = None,
                                elsevier_key: str | None = None, contact_email: str | None = None,
                                candidate_rule: str | None = fast_path.ACQUIRE_RULE
                                ) -> tuple[str | None, str | None]:
    """Attach a verified copy of another declared version to its own row under the same work; (asset, row) or (None, None).

    Only a candidate whose DOI was verified and whose version the provider named is taken: an `uncertain` copy is
    never attached by code and keeps waiting for the user, and a `mismatch` is not this work at all. The row it
    lands on carries that version's label, so the passages say which version was read. A row opened by an
    earlier run is found again rather than opened twice, and its file is not fetched a second time.
    """
    wanted = [c for c in store.pdf_candidates(source_version_id)
              if c["identity_status"] == "doi_verified" and c["version_status"] == "different"
              and c["version_label"] in VERSION_ORDER]
    # The declared version decides first; within one version the same fixed candidate order as the main loop, so
    # neither path reads the arrival order or the row id. A run from before the rule keeps the row id it ordered by.
    ordered = (sorted(wanted, key=lambda c: (VERSION_ORDER.index(c["version_label"]), c["id"])) if candidate_rule is None
               else sorted(candidate_order(wanted, candidate_rule), key=lambda c: VERSION_ORDER.index(c["version_label"])))
    found: tuple[str | None, str | None] | None = None  # a copy attached whose text could not be read
    for candidate in ordered:
        existing = store.find_source_by_identifier("pdf_lookup_version", f"{source_version_id}:{candidate['version_label']}")
        if existing and store.has_asset(existing):
            if not store.has_pdf_text(existing):
                # That version's file is here and no text could be read from it, so it answers nothing: the next
                # candidate — another declared version — is tried instead. The file itself is left as it is.
                continue
            # Already fetched, perhaps by another research that holds the same record: the row joins this research
            # and the file is not asked for again.
            if before_publish is not None:
                await before_publish()
            store.open_lookup_version(research_id, source_version_id, candidate["version_label"], candidate["landing_url"])
            return None, existing
        if candidate["provider"] == "europepmc":
            # Europe PMC's copy under the same rule; its row is opened only for a drawing that succeeded.
            if (data := await _render_candidate(store, candidate, xml_fetcher)) is None:
                continue
            if before_publish is not None:
                await before_publish()
            version_id = store.open_lookup_version(research_id, source_version_id, candidate["version_label"],
                                                   candidate["landing_url"])
            return await _attach_rendition(store, version_id, candidate, data, papers_dir,
                                           research_id=research_id, recovery_dir=recovery_dir,
                                           before_publish=before_publish), version_id
        result = await fetcher_for(candidate, fetcher, elsevier_key, contact_email)(candidate["candidate_url"])
        store.record_pdf_attempt(candidate["id"], result)
        if result.status != "ok":
            continue
        if before_publish is not None:
            await before_publish()
        version_id = store.open_lookup_version(research_id, source_version_id, candidate["version_label"],
                                               candidate["landing_url"])
        asset_id = await _attach_pdf(store, version_id, result.data, papers_dir, "download",
                                     result.final_url or candidate["candidate_url"], research_id=research_id,
                                     recovery_dir=recovery_dir, before_publish=before_publish)
        if not store.has_pdf_text(version_id):
            # That version's file is here and no text could be read from it: the row and the file stay, recorded
            # with what the extraction found, and the next declared version is tried rather than the work being
            # settled without text.
            found = found or (asset_id, version_id)
            continue
        return asset_id, version_id
    # Nothing readable came. A file that was attached on the way is reported, so the caller knows a copy is in hand
    # even though its text could not be read.
    return found if found else (None, None)


async def _attach_pdf(store: Store, source_version_id: str, data: bytes, papers_dir: Any, origin: str,
                      retrieved_from: str | None, filename: str | None = None, *, research_id: str | None = None,
                      recovery_dir: Path | None = None,
                      before_publish: Callable[[], Awaitable[None]] | None = None) -> str:
    from deixis.workflow.read import text_retry

    recovery_dir = file_restore.resolve_recovery_dir(store, papers_dir, recovery_dir)
    placement = await file_restore.store_pdf_file(store, papers_dir, recovery_dir, data,
                                                 caller="acquisition", research_id=research_id)
    sha, path = placement.sha256, placement.path
    read = await text_retry.read_verified(store, papers_dir, recovery_dir, storage_path=path.name,
                                          sha256=sha, byte_size=len(data), lock=True)
    extraction = read.extraction
    if before_publish is not None:
        await before_publish()
    return store.add_asset_with_pages(source_version_id, sha, len(data), path.name, origin, retrieved_from, filename,
                                      extraction, pdf.EXTRACTION_VERSION, pdf.chunk_page,
                                      input_observation=read.observation)


async def attach_confirmed_candidate(store: Store, source_version_id: str, candidate: dict[str, Any], papers_dir: Any,
                                     fetcher: Callable[[str], Awaitable[fetch.FetchResult]] = fetch.fetch_pdf, *,
                                     research_id: str | None = None, recovery_dir: Path | None = None,
                                     elsevier_key: str | None = None, contact_email: str | None = None) -> fetch.FetchResult:
    recovery_dir = file_restore.resolve_recovery_dir(store, papers_dir, recovery_dir)
    result = await fetcher_for(candidate, fetcher, elsevier_key, contact_email)(candidate["candidate_url"])
    store.record_pdf_attempt(candidate["id"], result)
    if result.status == "ok":
        # The version claim is the user's, not the provider's, so the file is recorded as their confirmed copy.
        await _attach_pdf(store, source_version_id, result.data, papers_dir, "user_upload",
                          result.final_url or candidate["candidate_url"], research_id=research_id,
                          recovery_dir=recovery_dir)
    return result
