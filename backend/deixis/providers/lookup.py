"""Asking one source about one record by DOI: the abstract it holds, its reference count and the versions it names.

This is not a search. A search asks a question and gets a ranked list; these two clients name a record the research
already has and ask a second source what it holds about it (SW5.5, SW6.4). The answer fills a missing abstract, a
missing reference count, and the DOIs the source says are another version of the same record — never a new candidate.

Endpoints verified against the provider documentation on 2026-09-21:

- Semantic Scholar Academic Graph API, `POST /graph/v1/paper/batch` (OpenAPI at
  `https://api.semanticscholar.org/graph/v1/swagger.json`): the body is `{"ids": [...]}`, `fields` is a single-value
  *query* parameter and not part of the body, at most 500 ids and 10 MB come back at a time, and the accepted id
  forms include `DOI:<doi>` and `ARXIV:<id>`. The spec does not state what an unknown id answers or that the answer
  keeps the input order; this module reads the documented example's list answer positionally and refuses a list whose
  length differs from the request, so a reordered or short answer is recorded as a failure rather than attached to
  the wrong record.
- Crossref REST API, `GET /works/{doi}` (Swagger at `https://api.crossref.org/swagger-docs`): the work sits under
  `message`, `reference-count` is an integer, `relation` maps a relation type to a list of `{id, id-type,
  asserted-by}`, and a DOI that does not exist answers 404.

Every Semantic Scholar request goes through the shared `send`, so the process-wide one-request gate of D67 and the
bounded 429 retries apply here exactly as they do to a search. A failed lookup is an answer like any other: it is
recorded and the run goes on (D18).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from deixis.providers import crossref, semantic_scholar
from deixis.providers.common import MAX_RATE_LIMIT_RETRIES, SearchOutcome, normalize_doi, send

S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
S2_LOOKUP_FIELDS = "externalIds,abstract,referenceCount"
S2_LOOKUP_BATCH = 200  # ids per request; the endpoint takes up to 500
CROSSREF_WORK_URL = "https://api.crossref.org/works/"
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
    answers = {doi: _s2_answer(doi, item) for doi, item in zip(dois, payload)}
    outcome.status = "completed"
    outcome.raw_payload = {"ids": ids, "answers": payload}
    return answers, outcome


def _s2_answer(doi: str, item: Any) -> LookupAnswer:
    if not isinstance(item, dict):  # the documented answer for an id Semantic Scholar does not hold
        return LookupAnswer("not_found")
    external = {k: str(v) for k, v in (item.get("externalIds") or {}).items() if v}
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
