"""Asking one source about one record by DOI: the abstract it holds, its reference count and the versions it names.

This is not a search. A search asks a question and gets a ranked list; these two clients name a record the research
already has and ask a second source what it holds about it (SW5.5, SW6.4). The answer fills a missing abstract, a
missing reference count, and the DOIs the source says are another version of the same record — never a new candidate.

Endpoints verified against the provider documentation on 2026-09-21:

- Semantic Scholar Academic Graph API, `POST /graph/v1/paper/batch` (OpenAPI at
  `https://api.semanticscholar.org/graph/v1/swagger.json`): the body is `{"ids": [...]}`, `fields` is a single-value
  *query* parameter and not part of the body, at most 500 ids and 10 MB come back at a time, and the accepted id
  forms include `DOI:<doi>` and `ARXIV:<id>`. The spec does not state what an unknown id answers or that the answer
  keeps the input order. This module requires the requested length and binds answers by DOI/ArXiv identifier
  regardless of position. Repeated requests share an answer when every answer naming that identifier is JSON-equal.
  Conflicting answers fail; only an order-consistent null means not_found, and unbound answers fail.
- Crossref REST API, `GET /works/{doi}` (Swagger at `https://api.crossref.org/swagger-docs`): the work sits under
  `message`, `reference-count` is an integer, `relation` maps a relation type to a list of `{id, id-type,
  asserted-by}`, and a DOI that does not exist answers 404.

- Scopus Search API, `GET /content/search/scopus` with `query=DOI(<doi>)` and `view=COMPLETE`: the complete view
  carries the abstract as `dc:description` and is entitled by the caller's IP range (`scopus.complete_view_entitled`);
  an empty result set is one entry holding an `error` field (`providers/scopus.py`). Up to 25 DOIs go in one request,
  `query=DOI(a) OR DOI(b) OR ...` with `count=25`. Live probe, 4 Oct 2026, on an institutional VPN with a real key: a
  25-DOI OR query in the complete view answered 200 in 0.8 s with `totalResults` 22 and 22 entries; all 22 matched an
  asked DOI by `prism:doi`, all had `dc:description`, none named a foreign DOI, and five single-DOI requests showed
  the same abstract presence. That is one probe on one network, not a measured recall. A DOI with a character that
  has a meaning in Scopus query syntax (parentheses, quotes, braces, wildcards, whitespace; see `scopus_doi_is_safe`)
  is not put in an OR query; it is asked alone with `scopus_abstract`.

Every Semantic Scholar request goes through the shared `send`, so the process-wide one-request gate of D67 and the
bounded 429 retries apply here exactly as they do to a search. A failed lookup is an answer like any other: it is
recorded and the run goes on (D18).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from deixis.providers import crossref, scopus, semantic_scholar
from deixis.providers.common import MAX_RATE_LIMIT_RETRIES, SearchOutcome, normalize_doi, send

S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
S2_LOOKUP_FIELDS = "externalIds,abstract,referenceCount"
S2_LOOKUP_BATCH = 200  # ids per request; the endpoint takes up to 500
CROSSREF_WORK_URL = "https://api.crossref.org/works/"
SCOPUS_LOOKUP_BATCH = 25  # DOIs per OR query; also the page size (`count`) asked for
# A DOI that can sit inside `DOI(...)` of an OR query without meaning anything to Scopus's query parser. Everything
# outside this set (parentheses, quotes, braces, wildcards `*` `?`, whitespace, `&`, `<`, ...) is asked alone.
_SCOPUS_SAFE_DOI = re.compile(r"10\.[0-9]+/[A-Za-z0-9._;:/\-]+")
ARXIV_DOI_PREFIX = "10.48550/arxiv."
# The two directions of the Crossref preprint relation: the record's published version, and its preprint.
IS_PREPRINT_OF = "is-preprint-of"
HAS_PREPRINT = "has-preprint"


@dataclass
class LookupAnswer:
    status: str  # "found" | "not_found" | "failed"
    abstract: str | None = None
    reference_count: int | None = None
    linked_dois: list[str] = field(default_factory=list)  # DOIs the source names as another version of this record
    has_preprint: list[str] = field(default_factory=list)  # DOIs the source names as this record's preprint
    paper_id: str | None = None  # Semantic Scholar only


def s2_identifier(doi: str) -> str:
    """The form Semantic Scholar knows the record by: an arXiv DOI names an arXiv id, everything else is a DOI."""
    if doi.startswith(ARXIV_DOI_PREFIX):
        return f"ARXIV:{doi[len(ARXIV_DOI_PREFIX):]}"
    return f"DOI:{doi}"


async def semantic_scholar_batch(client: httpx.AsyncClient, dois: list[str], api_key: str | None = None,
                                 max_rate_limit_retries: int = MAX_RATE_LIMIT_RETRIES,
                                 ) -> tuple[dict[str, LookupAnswer], SearchOutcome]:
    """Ask Semantic Scholar about these DOIs in one request; every DOI comes back with an answer.

    One request carries the whole batch, so one failure leaves every record in it `failed` and the next source is
    asked about all of them. Its retries are inside `outcome.retries` and are requests the caller counts; how many
    it may make is the caller's effort (D88), down to none.
    """
    ids = [s2_identifier(doi) for doi in dois]
    headers = {"x-api-key": api_key} if api_key else {}
    access_mode = "api_key" if api_key else "keyless"
    description = f"POST {S2_BATCH_URL} ids={len(ids)} fields={S2_LOOKUP_FIELDS} access={access_mode}"
    response, outcome = await send(client, S2_BATCH_URL, {"fields": S2_LOOKUP_FIELDS}, headers, description,
                                   access_mode, semantic_scholar.RATE_LIMIT_HEADERS, (api_key,),
                                   unstated_wait=semantic_scholar.UNSTATED_RATE_LIMIT_WAIT,
                                   max_rate_limit_retries=max_rate_limit_retries, json_body={"ids": ids})
    if response is None:
        return _all_failed(dois), outcome
    try:
        payload = response.json()
        if not isinstance(payload, list) or len(payload) != len(ids):
            raise TypeError(f"expected {len(ids)} answers, got {type(payload).__name__} of "
                            f"{len(payload) if isinstance(payload, list) else '?'}")
    except (json.JSONDecodeError, TypeError) as exc:
        outcome.status, outcome.error = "parse_error", str(exc)[:300]
        return _all_failed(dois), outcome
    def arxiv(value):
        return re.sub(r"v\d+$", "", value.strip().casefold())

    def names(item, doi):
        external = item.get("externalIds") if isinstance(item, dict) else None
        if not isinstance(external, dict):
            return False
        value = external.get("ArXiv" if doi.startswith(ARXIV_DOI_PREFIX) else "DOI")
        if not isinstance(value, str) or not value.strip():
            return False
        return (arxiv(value) == arxiv(doi[len(ARXIV_DOI_PREFIX):]) if doi.startswith(ARXIV_DOI_PREFIX)
                else normalize_doi(value) == doi)

    positions = {}
    for i, doi in enumerate(dois):
        positions.setdefault(doi, []).append(i)
    named = [[doi for doi in positions if names(item, doi)] for item in payload]
    consistent = all(item is None or matches == [dois[i]] for i, (item, matches) in enumerate(zip(payload, named)))
    answers = {}
    ambiguous = 0
    for doi, requested_positions in positions.items():
        matches = [j for j, identifiers in enumerate(named) if doi in identifiers]
        # JSON comparison ignores object-key order without equating booleans with numbers.
        equal = matches and len({json.dumps(payload[j], sort_keys=True) for j in matches}) == 1
        if equal:
            answers[doi] = _s2_answer(doi, payload[matches[0]])
        elif not matches and consistent and all(payload[i] is None for i in requested_positions):
            answers[doi] = LookupAnswer("not_found")
        else:
            answers[doi] = LookupAnswer("failed")
            ambiguous += len(matches) if len(matches) > 1 else 0
    unbound = sum(not matches and (item is not None or not consistent) for item, matches in zip(payload, named))
    if unbound or ambiguous:
        outcome.error = f"unbound answers: {unbound}; ambiguous answers: {ambiguous}"
    outcome.status = "completed"
    outcome.raw_payload = {"ids": ids, "answers": payload}
    return answers, outcome


def _s2_answer(doi: str, item: Any) -> LookupAnswer:
    if not isinstance(item, dict):  # the documented answer for an id Semantic Scholar does not hold
        return LookupAnswer("not_found")
    external = {k: v for k, v in item["externalIds"].items() if isinstance(v, str) and v.strip()}
    named = normalize_doi(external.get("DOI"))
    count = item.get("referenceCount")
    return LookupAnswer(
        "found",
        abstract=(item.get("abstract") or "").strip() or None,
        reference_count=count if isinstance(count, int) else None,
        # A DOI other than the one asked about is the source saying this record has another version; the same DOI
        # says only that the source found what was asked for.
        linked_dois=[named] if named and named != doi else [],
        paper_id=str(item["paperId"]) if item.get("paperId") else None,
    )


async def crossref_work(client: httpx.AsyncClient, doi: str,
                        contact_email: str | None = None) -> tuple[LookupAnswer, SearchOutcome]:
    """Ask Crossref about one DOI. A DOI Crossref does not register is `not_found`, not a failure."""
    url = f"{CROSSREF_WORK_URL}{quote(doi, safe='')}"
    params: dict[str, Any] = {"mailto": contact_email} if contact_email else {}
    description = f"GET {CROSSREF_WORK_URL}<doi> doi={doi!r} access=keyless"
    response, outcome = await send(client, url, params, {}, description, "keyless", crossref.RATE_LIMIT_HEADERS)
    if response is None:
        # `send` classifies every non-200 that is not a rate limit or an auth refusal as `failed`; for a single
        # record, 404 is the registry's answer that it holds nothing, which is not the same as a failed request.
        if outcome.http_status == 404:
            outcome.status = "zero_results"
            return LookupAnswer("not_found"), outcome
        return LookupAnswer("failed"), outcome
    try:
        message = response.json()["message"]
        if not isinstance(message, dict):
            raise TypeError("message is not a work")
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        outcome.status, outcome.error = "parse_error", str(exc)[:300]
        return LookupAnswer("failed"), outcome
    count = message.get("reference-count")
    relation = message.get("relation") if isinstance(message.get("relation"), dict) else {}
    outcome.status = "completed"
    outcome.raw_payload = message
    return LookupAnswer(
        "found",
        abstract=crossref.strip_markup(message.get("abstract")),
        reference_count=count if isinstance(count, int) else None,
        linked_dois=_relation_dois(relation, IS_PREPRINT_OF, doi),
        has_preprint=_relation_dois(relation, HAS_PREPRINT, doi),
    ), outcome


async def scopus_abstract(client: httpx.AsyncClient, doi: str, api_key: str,
                          max_rate_limit_retries: int = MAX_RATE_LIMIT_RETRIES) -> tuple[LookupAnswer, SearchOutcome]:
    """Ask Scopus for one DOI's abstract in the complete view (D91). An empty result set is `not_found`."""
    params = {"query": f"DOI({doi})", "count": 1, "view": "COMPLETE"}
    description = f"GET {scopus.SEARCH_URL} query=DOI(<doi>) doi={doi!r} view=COMPLETE access=api_key"
    response, outcome = await send(client, scopus.SEARCH_URL, params,
                                   {"X-ELS-APIKey": api_key, "Accept": "application/json"}, description, "api_key",
                                   scopus.RATE_LIMIT_HEADERS, (api_key,), max_rate_limit_retries=max_rate_limit_retries)
    if response is None:
        return LookupAnswer("failed"), outcome
    try:
        entries = [entry for entry in response.json()["search-results"].get("entry") or [] if "error" not in entry]
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
        outcome.status, outcome.error = "parse_error", str(exc)[:300]
        return LookupAnswer("failed"), outcome
    outcome.status = "completed" if entries else "zero_results"
    outcome.raw_payload = response.json()
    if not entries:
        return LookupAnswer("not_found"), outcome
    # The abstract is written to the record that was asked about, so only an entry naming that DOI may give it; an
    # answer about another DOI is not this record's (review of 13g, 2026-09-23).
    asked = normalize_doi(doi)
    mine = [entry for entry in entries if normalize_doi(entry.get("prism:doi")) == asked]
    if not mine:
        outcome.error = "answer names another DOI: " + ", ".join(
            str(entry.get("prism:doi")) for entry in entries[:3])[:300]
        return LookupAnswer("not_found"), outcome
    return LookupAnswer("found", abstract=(mine[0].get("dc:description") or "").strip() or None), outcome


def scopus_doi_is_safe(doi: str) -> bool:
    """Whether this DOI may go into a Scopus OR query; any other is asked singly with `scopus_abstract`."""
    return isinstance(doi, str) and _SCOPUS_SAFE_DOI.fullmatch(doi) is not None


async def scopus_abstracts(client: httpx.AsyncClient, dois: list[str], api_key: str,
                           max_rate_limit_retries: int = MAX_RATE_LIMIT_RETRIES,
                           ) -> tuple[dict[str, LookupAnswer], SearchOutcome]:
    """Ask Scopus about up to 25 DOIs in one OR query in the complete view; every DOI comes back with an answer.

    An entry is given only to the asked DOI its `prism:doi` names; an entry naming another DOI is ignored and noted
    in `outcome.error`. An asked DOI with no entry is `not_found`, unless `opensearch:totalResults` says more
    entries exist than came back: then the missing ones were cut off, not absent, and are `failed`. One failed
    request leaves every DOI `failed`. A batch of one DOI (or of repeats of one) is the single-DOI request.
    """
    asked = list(dict.fromkeys(dois))
    if len(asked) == 1:
        answer, outcome = await scopus_abstract(client, asked[0], api_key, max_rate_limit_retries)
        return {asked[0]: answer}, outcome
    if not all(scopus_doi_is_safe(doi) for doi in asked):
        raise ValueError("a DOI that is not safe in a Scopus OR query must be asked alone")
    params = {"query": " OR ".join(f"DOI({doi})" for doi in asked), "count": SCOPUS_LOOKUP_BATCH, "view": "COMPLETE"}
    description = f"GET {scopus.SEARCH_URL} query=DOI(<doi>) OR ... dois={len(asked)} view=COMPLETE access=api_key"
    response, outcome = await send(client, scopus.SEARCH_URL, params,
                                   {"X-ELS-APIKey": api_key, "Accept": "application/json"}, description, "api_key",
                                   scopus.RATE_LIMIT_HEADERS, (api_key,), max_rate_limit_retries=max_rate_limit_retries)
    if response is None:
        return _all_failed(asked), outcome
    try:
        payload = response.json()
        results = payload["search-results"]
        entries = [entry for entry in results.get("entry") or [] if "error" not in entry]
        total = results.get("opensearch:totalResults")
        total = int(total) if total is not None else len(entries)
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError, ValueError) as exc:
        outcome.status, outcome.error = "parse_error", str(exc)[:300]
        return _all_failed(asked), outcome
    outcome.status = "completed" if entries else "zero_results"
    outcome.raw_payload = payload
    # Matched on the normalized DOI and answered under every key the caller spelled it with.
    wanted = {normalize_doi(doi) for doi in asked}
    by_doi: dict[str, dict[str, Any]] = {}
    foreign = []
    for entry in entries:
        named = normalize_doi(entry.get("prism:doi"))
        if named in wanted:
            by_doi.setdefault(named, entry)  # the first entry naming a DOI is its answer
        else:
            foreign.append(str(entry.get("prism:doi")))
    if foreign:
        outcome.error = "answer names another DOI: " + ", ".join(foreign[:3])[:300]
    truncated = total > len(entries)
    if truncated:
        outcome.error = ((outcome.error + "; ") if outcome.error else "") + (
            f"truncated: {len(entries)} of {total} entries returned")
    answers = {}
    for doi in asked:
        entry = by_doi.get(normalize_doi(doi))
        if entry is not None:
            answers[doi] = LookupAnswer("found", abstract=(entry.get("dc:description") or "").strip() or None)
        else:
            answers[doi] = LookupAnswer("failed" if truncated else "not_found")
    return answers, outcome


def _relation_dois(relation: dict[str, Any], kind: str, doi: str) -> list[str]:
    """The DOIs of one relation type, normalised, without repeats and without the record's own DOI."""
    found: dict[str, None] = {}
    for entry in relation.get(kind) or []:
        if not isinstance(entry, dict) or (entry.get("id-type") or "").lower() != "doi":
            continue
        value = normalize_doi(entry.get("id"))
        if value and value != doi:
            found.setdefault(value, None)
    return list(found)


def _all_failed(dois: list[str]) -> dict[str, LookupAnswer]:
    return {doi: LookupAnswer("failed") for doi in dois}
