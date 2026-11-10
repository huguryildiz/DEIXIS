"""Semantic Scholar paper relevance search adapter.

Probed live on 2026-09-14 without a key: the shared keyless pool answered 429 (no retry-after header) to the first
requests and 200 after a short wait, so 429s are retried with a bounded backoff. `/paper/search` takes plain words and
supports no query syntax. A paper record groups a work's versions; its DOI names the published version. A record known
only from arXiv gets no DOI (arXiv's DOI would not say which version). The open-access PDF carries no version label, so
it is not attached.

Paging (Academic Graph API docs, relevance search, read 2026-09-21): `offset` and `limit` page the result set and
`offset + limit` may not exceed 1,000; the response names the next `offset` in `next` and leaves it out at the end.
Reading past 1,000 needs the bulk endpoint.

Bulk search (`/paper/search/bulk`, API description read 2026-09-23, `notes/archive/sw/sw-s2-bulk-probe-2026-09-23/swagger.json`):
the query is matched against title and abstract with `+` for AND, `|` for OR, `"` for a phrase and `( )` for
precedence; up to 1,000 papers come in one call and a `token` in the answer asks for the next batch; `total` is an
estimate. It does not order by relevance: `sort` is `paperId` (the default), `publicationDate` or `citationCount`, so
which records a read limit keeps is decided by the sort. An sw query names this endpoint and its sort
(`endpoint`, `sort`); a legacy query, and an sw query stored earlier, names neither and goes to `/paper/search`.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from deixis.providers.common import (FIRST_PAGE, MAX_RATE_LIMIT_RETRIES, ProviderRecord, SearchOutcome, next_offset,
                                     normalize_doi, page_offset, send)

PROVIDER_ID = "semantic_scholar"
SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
BULK_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
SNIPPET_URL = "https://api.semanticscholar.org/graph/v1/snippet/search"
BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
SNIPPET_ENDPOINT = "snippet"
# The snippet reply's own paper object carries only `corpusId`, `title`, `authors` and `openAccessInfo`: no DOI, no
# other external id, and no `fields` value adds them (API docs, read 2026-11-10). So the works those snippets came
# from are looked up once by `CorpusId:<id>`, and only then does a snippet reach the shared pool by DOI.
SNIPPET_MAX_RESULTS = 25
SNIPPET_KINDS = ("title", "abstract", "body")  # where in the paper a snippet stands
SNIPPET_FIELDS = ("snippet.text,snippet.snippetKind,snippet.section,snippet.snippetOffset,"
                  "snippet.annotations.refMentions,snippet.annotations.sentences")
# Ids one batch lookup takes. One snippet page names at most `SNIPPET_MAX_RESULTS` distinct works, well under this,
# so the path never needs a second batch request and its declared request count (2) is an upper bound.
BATCH_MAX_IDS = 500
BULK_ENDPOINT = "bulk"
BULK_MAX_RESULTS = 1000  # papers one bulk call returns
BULK_SORT = "citationCount:desc"  # chosen by slice 14's Task 1
# Records past a read limit that a bulk page returned are dropped. Neither the answer's token nor anything else can ask
# for them, so the read ends there and this cursor is never sent (the read limit ends the query first).
CUT = "cut"
FIELDS = "paperId,externalIds,title,abstract,year,venue,publicationTypes,authors,url"
ABSTRACT_ORIGIN = "provider_semantic_scholar"
RATE_LIMIT_HEADERS = ("x-ratelimit-limit", "x-ratelimit-remaining")
MAX_RESULTS = 100
# A short text from the question, which is what the relevance search is given when OpenAlex could not complete. The
# length is a pilot number: the endpoint documents no limit, and a whole question would mostly be stop words.
SEARCH_TEXT_MAX_CHARS = 300
# With a valid key, 3 s and 6 s retries still met three 429s in a row on 2026-09-15/16 (3 of 12 searches). The 429 carries
# no retry-after, so wait longer: 15 s, then 30 s.
UNSTATED_RATE_LIMIT_WAIT = 15.0


def query_text(text: str, limit: int = SEARCH_TEXT_MAX_CHARS) -> str:
    """A plain-text query for this provider: no syntax, no hyphens, no runs of space, cut at a word boundary.

    The relevance search documents that "hyphenated query terms yield no matches (replace it with space to find
    matches)" (API docs, read 2026-11-10), so a question that writes `depth-based routing` would find nothing at all.
    The hyphen becomes a space here rather than at the call site, so every text this provider is given is cut the same
    way and the stored query is the text that was really sent.
    """
    words = text.replace("-", " ").split()
    out: list[str] = []
    used = 0
    for word in words:
        step = len(word) + (1 if out else 0)
        if used + step > limit:
            break
        out.append(word)
        used += step
    # A first word longer than the limit still goes, cut: an empty query would read as "nothing was asked".
    return " ".join(out) if out else words[0][:limit] if words else ""


def _record(paper: dict[str, Any]) -> ProviderRecord:
    external = {k: str(v) for k, v in (paper.get("externalIds") or {}).items() if v}
    doi = normalize_doi(external.get("DOI"))
    abstract = (paper.get("abstract") or "").strip() or None
    return ProviderRecord(
        provider_record_id=str(paper["paperId"]),
        title=paper.get("title") or "(untitled)",
        authors=[a["name"] for a in paper.get("authors") or [] if a.get("name")],
        year=paper.get("year") if isinstance(paper.get("year"), int) else None,
        venue=paper.get("venue") or None,
        publication_type=(paper.get("publicationTypes") or [None])[0],
        doi=doi,
        landing_url=paper.get("url"),
        oa_pdf_url=None,
        oa_pdf_version=None,
        version_label=None,
        abstract=abstract,
        abstract_origin=ABSTRACT_ORIGIN if abstract else None,
        identifiers=external,
        raw=paper,
    )


async def search(client: httpx.AsyncClient, query: str, limit: int, api_key: str | None = None,
                 contact_email: str | None = None, cursor: str | None = None,
                 max_rate_limit_retries: int = MAX_RATE_LIMIT_RETRIES, endpoint: str | None = None,
                 sort: str | None = None, year_range: str | None = None) -> SearchOutcome:
    """One page of a relevance search, or of a bulk search when the query names that endpoint.

    `year_range` is the caller's publication-year bound, which only the bulk route takes (`search_bulk`).
    """
    if endpoint == BULK_ENDPOINT:
        return await search_bulk(client, query, limit, api_key, contact_email, cursor, max_rate_limit_retries,
                                 sort or BULK_SORT, year_range=year_range)
    if endpoint == SNIPPET_ENDPOINT:
        return await search_snippets(client, query, limit, api_key, contact_email, cursor, max_rate_limit_retries)
    if endpoint is not None:
        raise ValueError(f"unknown Semantic Scholar endpoint: {endpoint!r}")
    if year_range is not None:
        raise ValueError("the relevance route takes no publication-year bound")
    count = min(limit, MAX_RESULTS)
    params: dict[str, Any] = {"query": query, "limit": count, "fields": FIELDS}
    offset = page_offset(cursor)
    if cursor is not None:
        params["offset"] = offset
    headers = {"x-api-key": api_key} if api_key else {}
    access_mode = "api_key" if api_key else "keyless"
    description = (f"GET {SEARCH_URL} query={query!r} limit={count}"
                   + (f" offset={offset}" if cursor is not None else "") + f" access={access_mode}")
    response, outcome = await send(client, SEARCH_URL, params, headers, description, access_mode, RATE_LIMIT_HEADERS, (api_key,),
                                   unstated_wait=UNSTATED_RATE_LIMIT_WAIT,
                                   max_rate_limit_retries=max_rate_limit_retries)
    if response is None:
        return outcome
    try:
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("Semantic Scholar root must be an object")
        if payload.get("data") is not None and (not isinstance(payload["data"], list)
                                  or any(not isinstance(p, dict) for p in payload["data"])):
            raise TypeError("Semantic Scholar data must be a list of objects")
        outcome.records = [_record(p) for p in payload.get("data") or []]
        outcome.provider_total = payload["total"]
        # The response names the next offset itself and leaves it out once the reachable window (offset + limit ≤ 1000)
        # or the result set is spent.
        nxt = payload.get("next")
        outcome.next_cursor = str(nxt) if cursor is not None and nxt is not None else None
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
        outcome.status, outcome.error, outcome.records = "parse_error", str(exc)[:300], []
        return outcome
    outcome.status = "zero_results" if not outcome.records else "completed"
    outcome.raw_payload = payload
    return outcome


async def search_bulk(client: httpx.AsyncClient, query: str, limit: int, api_key: str | None = None,
                      contact_email: str | None = None, cursor: str | None = None,
                      max_rate_limit_retries: int = MAX_RATE_LIMIT_RETRIES, sort: str = BULK_SORT,
                      *, year_range: str | None = None) -> SearchOutcome:
    """One batch of a bulk search: up to 1,000 papers, of which the first `limit` are kept.

    The request goes through the same `send` as every other Semantic Scholar request, so the process-wide gate
    and the bounded 429 retries apply to it unchanged. The endpoint takes no page size; a batch larger than `limit` is
    cut there and its read ends (`CUT`).

    `year_range` is sent as this route's own `year`, which it takes as `<min>-<max>` and refuses in any other form
    ("'year' must be of the form <min>-<max>", answered 10 Nov 2026), so both sides are always written.
    """
    if cursor == CUT:
        raise ValueError("a cut bulk batch has no next page")
    params: dict[str, Any] = {"query": query, "fields": FIELDS, "sort": sort}
    if year_range:
        params["year"] = year_range
    if cursor not in (None, FIRST_PAGE):
        params["token"] = cursor
    headers = {"x-api-key": api_key} if api_key else {}
    access_mode = "api_key" if api_key else "keyless"
    description = (f"GET {BULK_URL} query={query!r} sort={sort}" + (f" year={year_range}" if year_range else "")
                   + (" token=<next>" if "token" in params else "") + f" access={access_mode}")
    response, outcome = await send(client, BULK_URL, params, headers, description, access_mode, RATE_LIMIT_HEADERS, (api_key,),
                                   unstated_wait=UNSTATED_RATE_LIMIT_WAIT,
                                   max_rate_limit_retries=max_rate_limit_retries)
    if response is None:
        return outcome
    try:
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("Semantic Scholar root must be an object")
        if payload.get("data") is not None and (not isinstance(payload["data"], list)
                                  or any(not isinstance(p, dict) for p in payload["data"])):
            raise TypeError("Semantic Scholar data must be a list of objects")
        papers = payload.get("data") or []
        outcome.records = [_record(p) for p in papers[:limit]]
        total = payload.get("total")
        outcome.provider_total = int(total) if total is not None else None  # an estimate, sent as a string
        token = payload.get("token")
        outcome.next_cursor = CUT if len(papers) > limit else (token if isinstance(token, str) and token else None)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError) as exc:
        outcome.status, outcome.error, outcome.records = "parse_error", str(exc)[:300], []
        return outcome
    outcome.status = "zero_results" if not outcome.records else "completed"
    outcome.raw_payload = payload
    return outcome


def _snippet(entry: dict[str, Any]) -> dict[str, Any] | None:
    """One snippet match as it is kept: where it stands in the paper, the paper's corpus id and the provider's marks.

    None for an entry with no text or no corpus id: a passage nothing can be attributed to is no evidence of
    anything. The reference mentions keep their spans and the works they point at, not only a count: the design's
    rule — an experiment mentioned by a citation is not the paper's own finding — is checked by a person reading
    them, and a count alone would lose what the citation pointed at.
    """
    snippet = entry.get("snippet") or {}
    paper = entry.get("paper") or {}
    text = (snippet.get("text") or "").strip()
    # Only a string or a number is a corpus id; anything else would be kept as its own repr and link to no work.
    raw_id = paper.get("corpusId")
    corpus_id = str(raw_id).strip() if isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool) else ""
    if not text or not corpus_id:
        return None
    offset = snippet.get("snippetOffset") or {}
    annotations = snippet.get("annotations") or {}
    kind = snippet.get("snippetKind")
    return {
        "corpus_id": corpus_id,
        "title": paper.get("title") or None,
        "snippet_kind": kind if kind in SNIPPET_KINDS else None,
        # Only a body snippet stands in a section; a title or abstract snippet has none.
        "section": snippet.get("section") or None,
        "text": text,
        "char_start": offset.get("start") if isinstance(offset.get("start"), int) else None,
        "char_end": offset.get("end") if isinstance(offset.get("end"), int) else None,
        "score": entry.get("score") if isinstance(entry.get("score"), (int, float)) else None,
        "ref_mentions": [{"start": m.get("start"), "end": m.get("end"),
                          "matched_corpus_id": str(m["matchedPaperCorpusId"]) if m.get("matchedPaperCorpusId") else None}
                         for m in annotations.get("refMentions") or [] if isinstance(m, dict)],
        "sentences": [{"start": s.get("start"), "end": s.get("end")}
                      for s in annotations.get("sentences") or [] if isinstance(s, dict)],
    }


def _corpus_id(paper: dict[str, Any]) -> str | None:
    """The corpus id a batch reply names for a paper, from either place it can stand."""
    value = paper.get("corpusId") or (paper.get("externalIds") or {}).get("CorpusId")
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return None
    return str(value).strip() or None


async def search_snippets(client: httpx.AsyncClient, query: str, limit: int, api_key: str | None = None,
                          contact_email: str | None = None, cursor: str | None = None,
                          max_rate_limit_retries: int = MAX_RATE_LIMIT_RETRIES) -> SearchOutcome:
    """A snippet search, then one batch lookup of the works those snippets came from.

    Four outcomes, and the caller records which: the snippet search itself failed (nothing is kept); it answered with
    no snippet, which is a valid zero and sends no second request; it answered and the batch lookup failed, which
    keeps the snippets and brings no record; or both answered, which keeps the snippets and brings the records of the
    works that could be looked up. A snippet whose work the batch did not answer for is kept with no record, so what
    the provider found is never lost to a failure of the second request.

    The search is single-page, as SerpApi's is: `cursor` is accepted and ignored, the one reply is read and
    `next_cursor` stays None. The endpoint takes no cursor of its own, so there is no second page to ask for.
    """
    del cursor
    count = min(limit, SNIPPET_MAX_RESULTS)
    params: dict[str, Any] = {"query": query, "limit": count, "fields": SNIPPET_FIELDS}
    headers = {"x-api-key": api_key} if api_key else {}
    access_mode = "api_key" if api_key else "keyless"
    description = f"GET {SNIPPET_URL} query={query!r} limit={count} access={access_mode}"
    response, outcome = await send(client, SNIPPET_URL, params, headers, description, access_mode, RATE_LIMIT_HEADERS,
                                   (api_key,), unstated_wait=UNSTATED_RATE_LIMIT_WAIT,
                                   max_rate_limit_retries=max_rate_limit_retries)
    if response is None:
        return outcome
    try:
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("Semantic Scholar root must be an object")
        data = payload.get("data")
        if data is not None and (not isinstance(data, list) or any(not isinstance(e, dict) for e in data)):
            raise TypeError("Semantic Scholar data must be a list of objects")
        snippets = [kept for entry in data or [] if (kept := _snippet(entry)) is not None]
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
        outcome.status, outcome.error, outcome.records = "parse_error", str(exc)[:300], []
        return outcome
    outcome.raw_payload = payload
    outcome.snippets = snippets
    if not snippets:
        # A valid zero: no snippet to look a work up for, so the second request is not sent.
        outcome.status = "zero_results"
        return outcome
    ids = list(dict.fromkeys(s["corpus_id"] for s in snippets))[:BATCH_MAX_IDS]
    batch_description = f"POST {BATCH_URL} ids={len(ids)} access={access_mode}"
    batch_response, batch_outcome = await send(client, BATCH_URL, {"fields": FIELDS}, headers, batch_description,
                                                access_mode, RATE_LIMIT_HEADERS, (api_key,),
                                                unstated_wait=UNSTATED_RATE_LIMIT_WAIT,
                                                max_rate_limit_retries=max_rate_limit_retries,
                                                json_body={"ids": [f"CorpusId:{cid}" for cid in ids]})
    if batch_response is None:
        # The snippets are what the provider really found and they are kept; the works are not reached, and the
        # request's own failure is what the row records.
        batch_outcome.snippets, batch_outcome.raw_payload = snippets, payload
        return batch_outcome
    try:
        batch = batch_response.json()
        if not isinstance(batch, list):
            raise TypeError("Semantic Scholar batch must be a list")
        wanted = set(ids)
        # Matched by the corpus id the reply itself names, never by its order: the endpoint answers `null` for an id
        # it does not know, and an entry for another work would otherwise be attached to this snippet.
        found = {cid: paper for paper in batch if isinstance(paper, dict)
                 and (cid := _corpus_id(paper)) is not None and cid in wanted}
        outcome.records = [_record(found[cid]) for cid in ids if cid in found]
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
        outcome.status, outcome.error, outcome.records = "parse_error", str(exc)[:300], []
        outcome.snippets = snippets
        return outcome
    # The request answered and brought what the provider had, so it completed even where no work could be looked up;
    # how many snippets reached a record is counted by the caller.
    outcome.status = "completed"
    outcome.provider_total = len(snippets)
    return outcome
