"""Semantic Scholar's bulk endpoint for sw searches, and the relevance search a legacy query keeps (slice 14, D93).

Since the clean start (slice 3a) discovery sends Semantic Scholar one bulk request on Deep only (the fast path's
`s2_bulk` slot); a stored query that names no endpoint is dropped from discovery (`openalex_only`), so the run-level
test of the relevance search was removed. The connector keeps both endpoints, tested below.

Records, queries and provider answers are SYNTHETIC and from two fields; every transport is mocked. Passing shows what
is requested, in which syntax, and how a read pages — not what Semantic Scholar really returns, how often it answers
429, or which records a sort keeps.
"""

from __future__ import annotations

import asyncio
import httpx
import pytest

from deixis.providers import common, query_compiler, query_rules, semantic_scholar
from deixis.providers.registry import endpoint_options, reading
from deixis.workflow import flow
from test_query_compiler import _blocks
from test_search_paging import keyword_plan, keyword_reader, library, read_pages  # noqa: F401  (library is a fixture)


def paper(i: int) -> dict:
    return {"paperId": f"s2-{i}", "externalIds": {"DOI": f"10.7/s2.{i}"}, "title": f"SYNTHETIC s2 record {i}",
            "abstract": None, "year": 2024, "venue": None, "publicationTypes": None, "authors": []}


def run(coro):
    return asyncio.run(coro)


# ---- the query syntax -------------------------------------------------------------------------------------------


def test_a_bulk_query_quotes_phrases_joins_a_block_with_or_and_the_blocks_with_and():
    blocks = _blocks(["body area networks", "implant links"], ["frame length", "payload"])
    (query,) = query_compiler.compile_block_queries(blocks, ["semantic_scholar"], 8)
    assert query["query_text"] == '("body area networks" | "implant links") + ("frame length" | payload)'
    assert query["dropped_terms"] == []


def test_a_one_term_block_has_no_parentheses_and_a_hyphenated_word_is_quoted():
    blocks = _blocks(["SYNTHETIC saline soils"], ["no-till", "biochar"])
    (query,) = query_compiler.compile_block_queries(blocks, ["semantic_scholar"], 8)
    assert query["query_text"] == '"SYNTHETIC saline soils" + ("no-till" | biochar)'


def test_a_bulk_query_names_its_endpoint_and_sort_and_no_other_query_does():
    blocks = _blocks(["arid soils"], ["nitrogen uptake"])
    by_provider = {q["provider_id"]: q for q in query_compiler.compile_block_queries(
        blocks, ["openalex", "semantic_scholar", "pubmed"], 8)}
    assert (by_provider["semantic_scholar"]["endpoint"], by_provider["semantic_scholar"]["sort"]) == (
        semantic_scholar.BULK_ENDPOINT, semantic_scholar.BULK_SORT)
    assert "endpoint" not in by_provider["openalex"] and "endpoint" not in by_provider["pubmed"]
    assert endpoint_options(by_provider["semantic_scholar"]) == {"endpoint": "bulk", "sort": semantic_scholar.BULK_SORT}
    assert endpoint_options(by_provider["openalex"]) == {}


def test_bulk_rules_accept_the_compiled_shape_and_refuse_what_bulk_would_read_as_an_operator():
    assert query_rules.query_issues("semantic_scholar", '("a b" | c) + d', "bulk") == []
    assert query_rules.query_issues("semantic_scholar", '("a b" | c + d', "bulk")  # unbalanced
    assert query_rules.query_issues("semantic_scholar", "reef + -bleaching", "bulk")  # negation
    assert query_rules.query_issues("semantic_scholar", "reef* + coral", "bulk")  # prefix
    assert query_rules.query_issues("semantic_scholar", '"reef | coral" + x', "bulk")  # operator inside a phrase
    # The relevance search's rule is unchanged for a query that names no endpoint.
    assert query_rules.query_issues("semantic_scholar", '("a b" | c) + d')


# ---- the connector ----------------------------------------------------------------------------------------------


def transport(answers, seen):
    def handler(request):
        seen.append(request)
        return answers.pop(0)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_a_legacy_request_is_the_relevance_search_byte_for_byte():
    seen = []
    client = transport([httpx.Response(200, json={"total": 1, "data": [paper(0)]})], seen)
    outcome = run(semantic_scholar.search(client, "reef restoration", 25, "SYNTHETIC-key"))
    request = seen[0]
    assert str(request.url).split("?")[0] == semantic_scholar.SEARCH_URL
    assert dict(request.url.params) == {"query": "reef restoration", "limit": "25", "fields": semantic_scholar.FIELDS}
    assert outcome.request_description == (f"GET {semantic_scholar.SEARCH_URL} query='reef restoration' limit=25"
                                           " access=api_key")


def test_a_bulk_read_pages_by_token_and_reads_the_estimated_total():
    seen = []
    client = transport([httpx.Response(200, json={"total": "2500", "token": "T1", "data": [paper(i) for i in range(3)]}),
                        httpx.Response(200, json={"total": "2500", "data": [paper(i) for i in range(3, 5)]})], seen)
    first = run(semantic_scholar.search(client, "a + b", 1000, cursor=common.FIRST_PAGE, endpoint="bulk",
                                        sort="paperId"))
    assert str(seen[0].url).split("?")[0] == semantic_scholar.BULK_URL
    assert dict(seen[0].url.params) == {"query": "a + b", "fields": semantic_scholar.FIELDS, "sort": "paperId"}
    assert (first.status, len(first.records), first.provider_total, first.next_cursor) == ("completed", 3, 2500, "T1")
    second = run(semantic_scholar.search(client, "a + b", 1000, cursor="T1", endpoint="bulk", sort="paperId"))
    assert seen[1].url.params["token"] == "T1"
    assert (len(second.records), second.next_cursor) == (2, None)


def test_a_bulk_batch_larger_than_the_limit_is_cut_and_ends_the_read():
    seen = []
    client = transport([httpx.Response(200, json={"total": "5", "token": "T1", "data": [paper(i) for i in range(5)]})],
                       seen)
    outcome = run(semantic_scholar.search(client, "a + b", 3, cursor=common.FIRST_PAGE, endpoint="bulk"))
    assert [r.provider_record_id for r in outcome.records] == ["s2-0", "s2-1", "s2-2"]
    assert outcome.next_cursor == semantic_scholar.CUT
    with pytest.raises(ValueError):
        run(semantic_scholar.search(client, "a + b", 3, cursor=semantic_scholar.CUT, endpoint="bulk"))


def test_a_bulk_request_passes_the_semantic_scholar_gate_and_its_bounded_429_retries(monkeypatch):
    gated = []
    real_run = common.SEMANTIC_SCHOLAR_PACER.run

    async def recording(factory):
        gated.append(True)
        return await real_run(factory)

    async def no_sleep(seconds):
        return None

    monkeypatch.setattr(common.SEMANTIC_SCHOLAR_PACER, "run", recording)
    monkeypatch.setattr(common.SEMANTIC_SCHOLAR_PACER, "interval_seconds", 0.0)
    monkeypatch.setattr(common.asyncio, "sleep", no_sleep)
    seen = []
    client = transport([httpx.Response(429, text="SYNTHETIC"), httpx.Response(429, text="SYNTHETIC"),
                        httpx.Response(429, text="SYNTHETIC")], seen)
    outcome = run(semantic_scholar.search(client, "a + b", 1000, endpoint="bulk", max_rate_limit_retries=2))
    assert len(gated) == 3 and len(seen) == 3  # the first request and two retries, each through the gate
    assert (outcome.status, outcome.retries) == ("rate_limited", 2)


def test_a_bulk_query_is_read_as_one_cursor_page_of_up_to_a_thousand():
    query = {"provider_id": "semantic_scholar", "query_text": "a + b", "endpoint": "bulk", "sort": "paperId"}
    shape = reading(query)
    assert (shape.paging, shape.max_results, shape.max_reachable) == ("cursor", 1000, None)
    old = reading({"provider_id": "semantic_scholar", "query_text": "a b"})
    assert (old.paging, old.max_results, old.max_reachable) == ("offset", 100, 1000)
    per_page = 1 + flow.PROVIDER_WAIT["detailed"] + flow.MAX_TRANSIENT_NETWORK_RETRIES
    assert flow.page_allowance(query, "detailed", {}) == per_page
    assert flow.page_allowance({"provider_id": "semantic_scholar", "query_text": "a b"}, "detailed", {}) == 10 * per_page


# ---- through a discovery run -------------------------------------------------------------------------------------


class Scholar:
    """Semantic Scholar answering both endpoints, every request recorded by path."""

    def __init__(self, total=30):
        self.total, self.requests = total, []

    def __call__(self, request):
        if request.url.host != "api.semanticscholar.org":
            return httpx.Response(404)
        params = request.url.params
        if not request.url.path.startswith("/graph/v1/paper/search"):
            return httpx.Response(404)  # an abstract lookup (slice 05), not a search
        self.requests.append((request.url.path, dict(params)))
        if request.url.path.endswith("/bulk"):
            return httpx.Response(200, json={"total": str(self.total), "data": [paper(i) for i in range(self.total)]})
        offset, limit = int(params.get("offset") or 0), int(params["limit"])
        end = min(offset + limit, self.total)
        return httpx.Response(200, json={"total": self.total, **({"next": end} if end < self.total else {}),
                                         "data": [paper(i) for i in range(offset, end)]})


def test_a_deep_run_reads_semantic_scholar_through_bulk_with_the_query_s_sort(library, tmp_path, monkeypatch):
    """The compiled bulk query, in the fast path's Deep `s2_bulk` slot, reaches the bulk endpoint with its sort and
    no limit, and is read as one page (D93, D252)."""
    monkeypatch.setattr("deixis.providers.common.SEMANTIC_SCHOLAR_PACER.interval_seconds", 0.0)
    (s2,) = query_compiler.compile_block_queries(_blocks(["arid soils"], ["nitrogen uptake"]), ["semantic_scholar"], 8)
    scholar = Scholar()
    research_flow, scope = keyword_reader(library, tmp_path, scholar)
    plan = keyword_plan(library, scope, ()) | {"s2_bulk": s2, "s2_bulk_index": 0, "s2_reserved": 500}
    rows = read_pages(research_flow, library, scope, plan)
    assert [path for path, _ in scholar.requests] == ["/graph/v1/paper/search/bulk"]
    params = scholar.requests[0][1]
    assert params["sort"] == semantic_scholar.BULK_SORT and "limit" not in params
    assert [(r["provider"], r["result_count"], r["stop_reason"]) for r in rows] == [("semantic_scholar", 30, "single_page")]
