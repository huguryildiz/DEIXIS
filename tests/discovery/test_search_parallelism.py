"""What is left of the parallel search round of slice 13f (D89) on the fast path, and the request allowance each
query keeps as its own.

Since the clean start (slice 3a) discovery reads OpenAlex only (keyword pages, one semantic request, and one Semantic
Scholar bulk request on Deep), so the tests of hosts read side by side, of the host bound `SEARCH_PARALLEL_HOSTS` and of
the evidence the sequential five-query round wrote (`tests/fixtures/search_parallelism/`) were removed with that round.
What the fast path shares with it is tested here: a query's own request share (D89) ends its read, survives a retry,
and pauses a run whose every share was spent before it asked. `Hosts`, `Session` and `run_discovery` stay for the
provider-fault tests of tests/hardening/test_p9_faults_providers.py.

Records and provider answers are SYNTHETIC and every transport is mocked: passing shows workflow behavior — what is
requested and what ends a read — not live provider timing or how often a real provider answers 429.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import replace

import httpx
import pytest

from deixis.providers import biorxiv as biorxiv_module
from deixis.providers import common
from deixis.providers.registry import CONNECTORS
from deixis.workflow import flow
from test_search_paging import (ALPHA, BETA, PagedProviders, app_for, client_of, discover, keyword_plan, keyword_reader,
                                library, reached_screening, read_pages, wait)  # noqa: F401  (library is a fixture)

QUESTION = "What is the effect of packet size on energy consumption in wireless sensor networks?"

# Five first-round queries on three hosts: OpenAlex and bioRxiv share api.openalex.org, Semantic Scholar holds two
# queries, and SerpApi reads one page only. Two DOIs are found by two providers each, so which record heads the work
# depends on the order the searches are written in.
FIRST_ROUND = [("openalex", "SYNTHETIC packet size energy"), ("semantic_scholar", "SYNTHETIC diffusion channel release"),
               ("biorxiv", "SYNTHETIC sensor duty cycle"), ("semantic_scholar", "SYNTHETIC receiver sampling budget"),
               ("serpapi", "SYNTHETIC molecular relay energy")]
SECOND_ROUND = [("openalex", "SYNTHETIC transmit power control"), ("semantic_scholar", "SYNTHETIC drift turbulence coding"),
                ("biorxiv", "SYNTHETIC vascular relay hop")]
SHARED = {  # (provider, query, position) → the DOI another provider's record carries too
    ("openalex", "SYNTHETIC packet size energy", 13): "10.9/shared.one",
    ("semantic_scholar", "SYNTHETIC diffusion channel release", 0): "10.9/shared.one",
    ("biorxiv", "SYNTHETIC sensor duty cycle", 2): "10.9/shared.two",
    ("serpapi", "SYNTHETIC molecular relay energy", 1): "10.9/shared.two",
    ("openalex", "SYNTHETIC transmit power control", 4): "10.9/shared.three",
    ("semantic_scholar", "SYNTHETIC drift turbulence coding", 1): "10.9/shared.three",
}
TOTALS = {"SYNTHETIC packet size energy": 25, "SYNTHETIC diffusion channel release": 12, "SYNTHETIC sensor duty cycle": 8,
          "SYNTHETIC receiver sampling budget": 30, "SYNTHETIC molecular relay energy": 3,
          "SYNTHETIC transmit power control": 14, "SYNTHETIC drift turbulence coding": 6,
          "SYNTHETIC vascular relay hop": 4}
RATE_LIMITED = {("SYNTHETIC receiver sampling budget", 10)}  # (query, offset): this page answers 429


@pytest.fixture(autouse=True)
def no_gate(monkeypatch):
    """Open the Semantic Scholar gate so a test does not wait on it (D67)."""
    monkeypatch.setattr(common.SEMANTIC_SCHOLAR_PACER, "interval_seconds", 0.0)


def doi_of(provider, query, position):
    return SHARED.get((provider, query, position), f"10.{abs(hash_of(provider)) % 7 + 1}/{hash_of(query)}.{position}")


def title_of(source, query, i):
    """A title no other SYNTHETIC record comes close to, so no record is linked to another by its title alone."""
    digest = hashlib.sha256(f"{source} {query} {i}".encode()).hexdigest()
    return "SYNTHETIC " + " ".join(digest[k:k + 8] for k in range(0, 40, 8))


def hash_of(text):
    return sum(ord(c) * (i + 1) for i, c in enumerate(text))  # stable across processes, unlike hash()


class Hosts:
    """Three mocked hosts. Every search request is logged with its host, query, page and the time it was in flight.

    `delay` holds each host's answer back (seconds), so a test can make a later query's host answer first;
    `hold` maps a (query, start) page to a threading.Event its request waits on before it answers; `fail` is a set
    of hosts whose every search request answers 500.
    """

    def __init__(self, delay=None, fail=(), hold=None, rate_limited=RATE_LIMITED):
        self.delay, self.fail, self.hold, self.rate_limited = delay or {}, set(fail), hold or {}, rate_limited
        self.log = []
        self.in_flight = {}
        self.waiting = set()  # (query, start) of the requests a `hold` is keeping in flight
        self.most = {"hosts": 0}

    @property
    def transport_log(self):
        """Independent per-query request evidence; fault subclasses may have no such log."""
        return self.log

    async def __call__(self, request):
        host, params = request.url.host, request.url.params
        if host == "api.openalex.org" and params.get("per_page") == "1" and params.get("select") == "id":
            return httpx.Response(200, json={"meta": {"count": 8}, "results": []})
        search = (host == "api.openalex.org" and request.url.path == "/works") or (
            host == "api.semanticscholar.org" and request.url.path.endswith("/paper/search")) or host == "serpapi.com"
        if not search:
            return httpx.Response(404)  # a slice 05 lookup: these SYNTHETIC DOIs are in no registry
        entry = {"host": host, "started": time.monotonic()}
        self.in_flight[host] = self.in_flight.get(host, 0) + 1
        self.most[host] = max(self.most.get(host, 0), self.in_flight[host])
        self.most["hosts"] = max(self.most["hosts"], sum(1 for n in self.in_flight.values() if n))
        try:
            page = self.page(host, params)
            if page in self.hold:  # a threading.Event, set by the test thread
                self.waiting.add(page)
                while not self.hold[page].is_set():
                    await asyncio.sleep(0.01)
            if self.delay.get(host):
                await asyncio.sleep(self.delay[host])
            response = self.answer(host, params, entry)
        finally:
            self.in_flight[host] -= 1
        entry["finished"] = time.monotonic()
        self.log.append(entry)
        return response

    @staticmethod
    def page(host, params):
        if host == "api.openalex.org":
            return params.get("search.title_and_abstract"), 0 if params.get("cursor") in (None, "*") else int(params["cursor"])
        if host == "api.semanticscholar.org":
            return params["query"], int(params.get("offset") or 0)
        return params["q"], 0

    def answer(self, host, params, entry):
        if host == "api.openalex.org" and (params.get("search.title_and_abstract") not in TOTALS or "per_page" not in params):
            # The fast path's semantic request and the routing step's field distribution: not served here.
            entry |= {"provider": "openalex", "query": params.get("search.title_and_abstract"), "start": 0}
            return httpx.Response(404)
        if host == "api.openalex.org":
            provider = "biorxiv" if biorxiv_module.SOURCE_ID in (params.get("filter") or "") else "openalex"
            query = params.get("search.title_and_abstract")
            cursor, size = params.get("cursor"), int(params["per_page"])
            start = 0 if cursor in (None, "*") else int(cursor)
        elif host == "api.semanticscholar.org":
            provider, query = "semantic_scholar", params["query"]
            start, size = int(params.get("offset") or 0), int(params["limit"])
        else:
            provider, query, start, size = "serpapi", params["q"], 0, int(params["num"])
        entry |= {"provider": provider, "query": query, "start": start}
        if host in self.fail:
            return httpx.Response(500, text="SYNTHETIC server error")
        if (query, start) in self.rate_limited:
            return httpx.Response(429, text="SYNTHETIC rate limit", headers={"retry-after": "0"})
        total = TOTALS[query]
        end = min(start + size, total)
        if provider in ("openalex", "biorxiv"):
            return httpx.Response(200, json={"meta": {"count": total, "next_cursor": str(end) if end < total else None},
                                             "results": [openalex_work(provider, query, i) for i in range(start, end)]})
        if provider == "semantic_scholar":
            return httpx.Response(200, json={"total": total, **({"next": end} if end < total else {}),
                                             "data": [s2_paper(query, i) for i in range(start, end)]})
        return httpx.Response(200, json={"search_information": {"total_results": total},
                                         "organic_results": [serp_result(query, i) for i in range(start, end)]})

    def requests(self, host=None):
        return [(e["provider"], e["query"], e["start"]) for e in self.log if host is None or e["host"] == host]


def openalex_work(provider, query, i):
    return {"id": f"https://openalex.org/W{hash_of(provider + query)}{i:03d}", "doi": f"https://doi.org/{doi_of(provider, query, i)}",
            "display_name": title_of(provider, query, i), "publication_year": 2024, "type": "article",
            "authorships": [], "abstract_inverted_index": {"SYNTHETIC": [0], title_of("abstract", query, i): [1]}}


def s2_paper(query, i):
    return {"paperId": f"s2-{hash_of(query)}-{i}", "externalIds": {"DOI": doi_of("semantic_scholar", query, i)},
            "title": title_of("semantic_scholar", query, i), "abstract": None, "year": 2023, "venue": None,
            "publicationTypes": None, "authors": []}


def serp_result(query, i):
    return {"result_id": f"g-{hash_of(query)}-{i}", "title": title_of("serpapi", query, i),
            "link": f"https://doi.org/{doi_of('serpapi', query, i)}",
            "publication_info": {"summary": "A Author - SYNTHETIC Venue, 2022 - example.org"}}


def queries_of(rows):
    return [{"provider_id": provider, "query_text": text, "rationale": "SYNTHETIC fixed query", "dropped_terms": []}
            for provider, text in rows]


def setup(tmp_path, monkeypatch, hosts):
    """An sw app whose vocabulary compiles FIRST_ROUND, with small pages. The fast path searches its OpenAlex query
    only; the others are dropped from discovery (`openalex_only`)."""
    compiled = queries_of(FIRST_ROUND)
    monkeypatch.setattr(flow.query_compiler, "compile_block_queries", lambda *a, **k: [dict(q) for q in compiled])
    app = app_for(tmp_path, monkeypatch, hosts)
    for provider, size in (("openalex", 10), ("biorxiv", 10), ("semantic_scholar", 10)):
        monkeypatch.setitem(CONNECTORS, provider, replace(CONNECTORS[provider], max_results=size))
    monkeypatch.setenv("SERPAPI_API_KEY", "SYNTHETIC-key")
    return app


class Session:
    """One app and client for a test: a discovery, then any resume or retry, read before the client closes."""

    def __init__(self, tmp_path, monkeypatch, hosts):
        self.hosts = hosts
        self.app = setup(tmp_path, monkeypatch, hosts)
        self.client = client_of(self.app)
        self.store = self.app.state.store

    def discover(self, effort="quick"):
        self.rid, self.run_id, self.view, self.run = discover(self.client, QUESTION, effort=effort)
        return self

    def control(self, action):
        response = self.client.post(f"/api/runs/{self.run_id}/{action}")
        assert response.status_code == 200, response.text
        self.view, self.run = wait(self.client, self.rid, self.run_id)
        return self

    def close(self):
        self.client.__exit__(None, None, None)


def run_discovery(tmp_path, monkeypatch, hosts, effort="quick"):
    """A whole discovery against `hosts`: the run's search rows in write order, the research view and the run."""
    session = Session(tmp_path, monkeypatch, hosts)
    try:
        session.discover(effort)
        rows = [dict(r) for r in session.store.conn.execute(
            "SELECT * FROM search_runs WHERE research_id = ? ORDER BY rowid", (session.rid,))]
        return rows, session.view, session.run
    finally:
        session.close()


# ---- the request allowance is each query's own (D89) ----------------------------------------------------------


class RefusedOnce(PagedProviders):
    """Every page of `query` answers 429 once, with no wait, and then serves: each of its pages costs two requests."""

    def __init__(self, query, **kwargs):
        super().__init__(**kwargs)
        self.query, self.refused = query, []

    def __call__(self, request):
        params = request.url.params
        page = (params.get("search.title_and_abstract"), params.get("cursor"))
        if page[0] == self.query and page not in self.refused:
            self.refused.append(page)
            return httpx.Response(429, text="SYNTHETIC rate limit", headers={"retry-after": "0"})
        return super().__call__(request)


class AlwaysRefused(PagedProviders):
    """`fail_at` of `fail_query` answers 429 with a stated wait of zero, every time it is asked."""

    def __call__(self, request):
        response = super().__call__(request)
        if response.status_code == 429:
            return httpx.Response(429, text="SYNTHETIC rate limit", headers={"retry-after": "0"})
        return response


def small_allowances(monkeypatch, shares):
    """Give the named queries a share of `shares[query]` requests, plus what a retry action adds, and leave every
    other query the share the effort derives."""
    derived = flow.page_allowance

    def allowance(query, effort, budget):
        if query["query_text"] in shares:
            return shares[query["query_text"]] + budget.get("retry_provider_requests", 0)
        return derived(query, effort, budget)

    monkeypatch.setattr(flow, "page_allowance", allowance)


def test_a_query_that_uses_up_its_share_ends_its_own_read_and_the_other_query_goes_on(library, tmp_path, monkeypatch):
    """Each page of the first query needs a retry, so its share of three requests is spent on its second page: that
    page ends the read with `budget_exhausted` and counts what it left unread, and the other query is read whole."""
    small_allowances(monkeypatch, {ALPHA: 3})
    providers = RefusedOnce(ALPHA, openalex_total=25)
    research_flow, scope = keyword_reader(library, tmp_path, providers, effort="standard")
    rows = read_pages(research_flow, library, scope, keyword_plan(library, scope, (ALPHA, BETA), page_size=10))
    first = [r for r in rows if r["query_text"] == ALPHA]
    assert [(r["page_number"], r["stop_reason"], r["unread_count"]) for r in first] == [
        (0, None, None), (1, "budget_exhausted", 5)]
    assert providers.refused == [(ALPHA, "*"), (ALPHA, "10")]
    assert [p for p in providers.queries if p[0] == ALPHA] == [(ALPHA, 0), (ALPHA, 10)]
    assert library.store.run(library.run["id"])["usage"]["query_requests"]["search:0"] == 4
    # The other query reads as far as it does with no allowance at all.
    assert [(r["page_number"], r["stop_reason"]) for r in rows if r["query_text"] == BETA] == [
        (0, None), (1, None), (2, "exhausted")]
    step = library.store.existing_step(library.run["id"], "search:0:page:1")
    assert step["output"]["stop_reason"] == "budget_exhausted"


def test_a_retried_query_keeps_its_count(library, tmp_path, monkeypatch):
    """The second page of one query fails after its share is spent. Asked to search again, the run finds the count
    it stored for that query, sends nothing, and says on the page's step that the allowance ended the read."""
    small_allowances(monkeypatch, {ALPHA: 2})
    providers = AlwaysRefused(openalex_total=25, fail_at=10, fail_query=ALPHA)
    research_flow, scope = keyword_reader(library, tmp_path, providers, effort="standard")
    plan = keyword_plan(library, scope, (ALPHA,), page_size=10)
    read_pages(research_flow, library, scope, plan)
    # Page 0 is one request, the refused page 1 two (standard waits out one 429): three of a share of two.
    assert library.store.run(library.run["id"])["usage"]["query_requests"]["search:0"] == 3
    asked = list(providers.queries)
    library.run["budget"] |= {"retry_failed_searches_only": True, "retry_provider_requests": 1}  # the retry action
    read_pages(research_flow, library, scope, plan, retry_failed=True)
    assert providers.queries == asked  # nothing was sent again: 2 + 1 = 3 requests are spent already
    assert library.store.run(library.run["id"])["usage"]["query_requests"]["search:0"] == 3
    step = library.store.existing_step(library.run["id"], "search:0:page:1")
    assert (step["status"], step["error_code"]) == ("cancelled", "budget_exhausted")


def test_a_run_whose_every_share_was_spent_before_it_asked_pauses_instead_of_going_on(tmp_path, monkeypatch):
    """D18: with no successful search the run pauses, also when no search failed because every query's share was
    already spent (a run resumed after a crash). Asked to search again, the retry adds to every share and reads."""
    monkeypatch.setattr(flow, "page_allowance", lambda query, effort, budget: budget.get("retry_provider_requests", 0))
    providers = PagedProviders(openalex_total=45)
    client = client_of(app_for(tmp_path, monkeypatch, providers))
    try:
        rid, run_id, view, run = discover(client)
        assert (run["status"], run["pause_reason"]) == ("paused", "budget_exhausted"), run
        assert providers.openalex == [] and view["search_runs"] == []
        steps = {s["operation_key"]: (s["status"], s["error_code"]) for s in run["steps"]}
        assert steps["search:fast:semantic"] == steps["search:0"] == ("cancelled", "budget_exhausted")
        assert client.post(f"/api/runs/{run_id}/retry_failed").status_code == 200
        view, run = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert reached_screening(run)
    assert providers.openalex and {r["status"] for r in view["search_runs"] if r["provider"] == "openalex"} == {"completed"}


# ---- the connector's host -------------------------------------------------------------------------------------


def test_each_connector_names_the_host_its_requests_go_to():
    """Hosts are grouped by the name a request really goes to: bioRxiv is read through OpenAlex and shares its host."""
    seen = []

    def handler(request):
        seen.append(request.url.host)
        return httpx.Response(500)

    async def ask(connector):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await connector.search(client, "SYNTHETIC query", 5, "SYNTHETIC-key", None)

    for connector in CONNECTORS.values():
        seen.clear()
        asyncio.run(ask(connector))
        assert seen and set(seen) == {connector.host}, connector.provider_id
    assert CONNECTORS["biorxiv"].host == CONNECTORS["openalex"].host
    assert len({c.host for c in CONNECTORS.values()}) == len(CONNECTORS) - 1
