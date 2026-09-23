"""OpenAlex works search adapter.

Verified on 2026-09-14 with a keyless request: `search=` is interpreted as full-text
search (poor topical precision), while `search.title_and_abstract=` searches titles
and abstracts; abstracts arrive as `abstract_inverted_index`; rate-limit and cost
headers are returned. Keyless and keyed modes have different daily budgets; the
actual mode and returned limit headers are recorded per call.

Paging (docs.openalex.org, "Paging", read 2026-09-21): `cursor=*` starts a cursor read, every answer carries
`meta.next_cursor` for the next page and a null one ends it; `per_page` goes up to 200 and cursor paging has no depth
limit, while basic paging stops at 10,000.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from deixis.providers.common import (MAX_RATE_LIMIT_RETRIES, OtherVersion, ProviderRecord, SearchOutcome,
                                     normalize_doi, send)

__all__ = ["OtherVersion", "ProviderRecord", "SearchOutcome", "citing_works", "count_works", "field_distribution",
           "normalize_doi", "reconstruct_abstract", "search_works", "works_by_ids"]

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
# Asked for only on an sw read (slices 05 and 07), so a legacy request keeps the `select` it always had.
REFERENCE_COUNT_FIELD = "referenced_works_count"
REFERENCES_FIELD = "referenced_works"
RATE_LIMIT_HEADERS = (
    "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset",
    "x-ratelimit-cost-usd", "x-ratelimit-remaining-usd",
)
MAX_RESULTS = 200
# A count needs no record. OpenAlex refuses per_page=0, so the smallest page is asked for and only meta.count read.
COUNT_PER_PAGE = 1
COUNT_SELECT = "id"
# The field of each work's primary topic, grouped over the whole result set (docs.openalex.org, "Group works", read
# 2026-09-23; probed live on three questions the same day, `.local/sw-slice14-fields-probe-2026-09-23/`).
FIELD_GROUP = "primary_topic.field.id"


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
        # Absent unless this read asked for the field; an absent count is unknown, never zero.
        reference_count=(work.get(REFERENCE_COUNT_FIELD)
                         if isinstance(work.get(REFERENCE_COUNT_FIELD), int) else None),
        # Same shape as `provider_record_id`, so a reference and a record are the same identifier. An absent field
        # is no list at all; a list the work really has empty is an empty one.
        references=(tuple(str(w).rsplit("/", 1)[-1] for w in work[REFERENCES_FIELD])
                    if isinstance(work.get(REFERENCES_FIELD), list) else None),
    )


async def search_works(
    client: httpx.AsyncClient,
    query: str,
    per_page: int,
    api_key: str | None = None,
    contact_email: str | None = None,
    works_filter: str | None = None,
    cursor: str | None = None,
    reference_count: bool = False,
    references: bool = False,
    max_rate_limit_retries: int = MAX_RATE_LIMIT_RETRIES,
) -> SearchOutcome:
    per_page = min(per_page, MAX_RESULTS)
    select = SELECT + "".join(f",{field}" for field, asked in
                              ((REFERENCE_COUNT_FIELD, reference_count), (REFERENCES_FIELD, references)) if asked)
    params: dict[str, Any] = {SEARCH_PARAM: query, "per_page": per_page, "select": select}
    if works_filter:
        params["filter"] = works_filter
    if contact_email:
        params["mailto"] = contact_email
    if cursor is not None:
        # Cursor paging: `*` asks for the first page and every answer carries the cursor of the next one.
        params["cursor"] = cursor
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    access_mode = "api_key" if api_key else "keyless"
    description = (f"GET {WORKS_URL} {SEARCH_PARAM}={query!r}" + (f" filter={works_filter}" if works_filter else "")
                   + f" per_page={per_page}" + (f" cursor={cursor}" if cursor is not None else "")
                   + f" access={access_mode}")
    response, outcome = await send(client, WORKS_URL, params, headers, description, access_mode, RATE_LIMIT_HEADERS,
                                   (api_key,), max_rate_limit_retries=max_rate_limit_retries)
    return _works_page(response, outcome, cursor)


def _works_page(response: httpx.Response | None, outcome: SearchOutcome, cursor: str | None) -> SearchOutcome:
    """A `/works` answer as a SearchOutcome: its records, its total and, for a cursor read, the next cursor."""
    if response is None:
        return outcome
    try:
        payload = response.json()
        outcome.records = [_record(w) for w in payload["results"]]
        meta = payload.get("meta") or {}
        outcome.provider_total = meta.get("count")
        # `next_cursor` is returned only for a cursor read, and is null on the last page.
        outcome.next_cursor = meta.get("next_cursor") if cursor is not None else None
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        outcome.status, outcome.error, outcome.records = "parse_error", str(exc)[:300], []
        return outcome
    outcome.status = "zero_results" if not outcome.records else "completed"
    outcome.raw_payload = payload
    return outcome


# The two requests of citation chaining (D95, slice 15). Both read the fields an sw search reads, the reference list
# included, so a chained record carries its own bibliography like any record an sw query found.
CHAIN_SELECT = SELECT + f",{REFERENCE_COUNT_FIELD},{REFERENCES_FIELD}"
MAX_IDS_PER_REQUEST = 100


async def citing_works(client: httpx.AsyncClient, work_id: str, cursor: str, per_page: int = MAX_RESULTS,
                       api_key: str | None = None, contact_email: str | None = None,
                       max_rate_limit_retries: int = MAX_RATE_LIMIT_RETRIES) -> SearchOutcome:
    """One page of the works that cite `work_id` (`filter=cites:W…`), read by cursor like an sw query's pages."""
    per_page = min(per_page, MAX_RESULTS)
    works_filter = f"cites:{work_id}"
    params: dict[str, Any] = {"filter": works_filter, "per_page": per_page, "select": CHAIN_SELECT, "cursor": cursor}
    if contact_email:
        params["mailto"] = contact_email
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    access_mode = "api_key" if api_key else "keyless"
    description = f"GET {WORKS_URL} filter={works_filter} per_page={per_page} cursor={cursor} access={access_mode}"
    response, outcome = await send(client, WORKS_URL, params, headers, description, access_mode, RATE_LIMIT_HEADERS,
                                   (api_key,), max_rate_limit_retries=max_rate_limit_retries)
    return _works_page(response, outcome, cursor)


async def works_by_ids(client: httpx.AsyncClient, ids: list[str], api_key: str | None = None,
                       contact_email: str | None = None,
                       max_rate_limit_retries: int = MAX_RATE_LIMIT_RETRIES) -> SearchOutcome:
    """The records of up to 100 OpenAlex works named by their short identifiers (`filter=openalex:W1|W2…`)."""
    if not 0 < len(ids) <= MAX_IDS_PER_REQUEST:
        raise ValueError(f"works_by_ids takes 1 to {MAX_IDS_PER_REQUEST} identifiers, not {len(ids)}")
    works_filter = "openalex:" + "|".join(ids)
    params: dict[str, Any] = {"filter": works_filter, "per_page": len(ids), "select": CHAIN_SELECT}
    if contact_email:
        params["mailto"] = contact_email
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    access_mode = "api_key" if api_key else "keyless"
    description = (f"GET {WORKS_URL} filter=openalex:{ids[0]}|… ({len(ids)} ids) per_page={len(ids)}"
                   f" access={access_mode}")
    response, outcome = await send(client, WORKS_URL, params, headers, description, access_mode, RATE_LIMIT_HEADERS,
                                   (api_key,), max_rate_limit_retries=max_rate_limit_retries)
    return _works_page(response, outcome, None)


async def count_works(client: httpx.AsyncClient, query: str, *, api_key: str | None = None,
                      mailto: str | None = None) -> int | None:
    """How many works the query matches, read from `meta.count` alone (SW2.2).

    Same search parameter, credentials and error handling as `search_works`. A failure, a timeout or a rate limit
    gives `None` and stops nothing: one unanswered probe must not stop the others, as one failed search does not
    stop a discovery run (D18). `None` means the count is unknown, never that it is zero.
    """
    params: dict[str, Any] = {SEARCH_PARAM: query, "per_page": COUNT_PER_PAGE, "select": COUNT_SELECT}
    if mailto:
        params["mailto"] = mailto
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    access_mode = "api_key" if api_key else "keyless"
    description = (f"GET {WORKS_URL} {SEARCH_PARAM}={query!r} per_page={COUNT_PER_PAGE} select={COUNT_SELECT}"
                   f" access={access_mode}")
    response, _ = await send(client, WORKS_URL, params, headers, description, access_mode, RATE_LIMIT_HEADERS, (api_key,))
    if response is None:
        return None
    try:
        count = (response.json().get("meta") or {}).get("count")
    except (json.JSONDecodeError, AttributeError, TypeError):
        return None
    return count if isinstance(count, int) else None


async def field_distribution(client: httpx.AsyncClient, query: str, *, api_key: str | None = None,
                             mailto: str | None = None) -> dict[str, Any] | None:
    """How the works the query matches spread over OpenAlex fields: the total and one row per field (D93).

    One request, grouped by the field of each work's primary topic, so it describes the whole result set and not a
    first page. A failure, a timeout, a rate limit or an answer without the grouping gives `None`, which means the
    distribution is unknown; nothing is retried here beyond `send`'s bounded 429 retries.
    """
    params: dict[str, Any] = {SEARCH_PARAM: query, "group_by": FIELD_GROUP}
    if mailto:
        params["mailto"] = mailto
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    access_mode = "api_key" if api_key else "keyless"
    description = f"GET {WORKS_URL} {SEARCH_PARAM}={query!r} group_by={FIELD_GROUP} access={access_mode}"
    response, _ = await send(client, WORKS_URL, params, headers, description, access_mode, RATE_LIMIT_HEADERS, (api_key,))
    if response is None:
        return None
    try:
        payload = response.json()
        total = payload["meta"]["count"]
        groups = payload["group_by"]
        fields = [{"field": str(group["key_display_name"]), "key": str(group["key"]), "count": int(group["count"])}
                  for group in groups]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
        return None
    if not isinstance(total, int) or isinstance(total, bool):
        return None
    return {"total": total, "fields": fields, "request": description}
