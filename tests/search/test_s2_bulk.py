"""Semantic Scholar bulk search in Detailed runs, and the one pacing gate all Semantic Scholar requests share.

Mocked transport; no real request. Passing shows what is sent and read, not live provider behavior.
"""

from __future__ import annotations

import asyncio
import httpx
from deixis.providers import common, query_compiler, query_rules, semantic_scholar
from test_query_compiler import _blocks
from test_search_paging import keyword_plan, keyword_reader, library, read_pages  # noqa: F401  (library is a fixture)
import time
from deixis.providers import common
from deixis.providers.pacing import SEMANTIC_SCHOLAR_PACER, SerialRequestPacer


# ---- from tests__providers__test_s2_bulk.py ------------------------------------------------------------

def paper(i: int) -> dict:
    return {"paperId": f"s2-{i}", "externalIds": {"DOI": f"10.7/s2.{i}"}, "title": f"SYNTHETIC s2 record {i}",
            "abstract": None, "year": 2024, "venue": None, "publicationTypes": None, "authors": []}


def run(coro):
    return asyncio.run(coro)


def test_bulk_rules_accept_the_compiled_shape_and_refuse_what_bulk_would_read_as_an_operator():
    assert query_rules.query_issues("semantic_scholar", '("a b" | c) + d', "bulk") == []
    assert query_rules.query_issues("semantic_scholar", '("a b" | c + d', "bulk")  # unbalanced
    assert query_rules.query_issues("semantic_scholar", "reef + -bleaching", "bulk")  # negation
    assert query_rules.query_issues("semantic_scholar", "reef* + coral", "bulk")  # prefix
    assert query_rules.query_issues("semantic_scholar", '"reef | coral" + x', "bulk")  # operator inside a phrase
    # The relevance search's rule is unchanged for a query that names no endpoint.
    assert query_rules.query_issues("semantic_scholar", '("a b" | c) + d')


def transport(answers, seen):
    def handler(request):
        seen.append(request)
        return answers.pop(0)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


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


# ---- from tests__providers__test_semantic_scholar_pacing.py ------------------------------------------------------------

def test_semantic_scholar_endpoints_share_one_gate_across_clients(monkeypatch):
    monkeypatch.setattr(common, "SEMANTIC_SCHOLAR_PACER", SerialRequestPacer(0.06))
    starts = []
    active = 0
    peak_active = 0

    async def handler(request):
        nonlocal active, peak_active
        starts.append((request.url.path, time.monotonic()))
        active += 1
        peak_active = max(peak_active, active)
        await asyncio.sleep(0.005)
        active -= 1
        return httpx.Response(200, json={})

    async def go():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as first, httpx.AsyncClient(transport=transport) as second:
            return await asyncio.gather(
                common.send(first, "https://api.semanticscholar.org/graph/v1/paper/search", {}, {}, "search", "keyless"),
                common.send(second, "https://api.semanticscholar.org/graph/v1/paper/DOI:example/references",
                            {}, {}, "references", "keyless"),
            )

    results = asyncio.run(go())
    assert [outcome.status for _, outcome in results] == ["completed", "completed"]
    assert {path.rsplit("/", 1)[-1] for path, _ in starts} == {"search", "references"}
    assert peak_active == 1
    assert starts[1][1] - starts[0][1] >= 0.055
