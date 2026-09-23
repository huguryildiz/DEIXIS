"""Discovery searches read in parallel across hosts and written in query order, with the request allowance split per
query (slice 13f, D89).

The equality tests were written first, on the sequential code of slice 13e, and the evidence they recorded is the
fixture every later version has to give back row for row: the same `search_runs` rows, records, versions, candidates
and work heads, the same search step outputs, the same unread count and the same events, in the same write order.
Records and provider answers are SYNTHETIC and from two fields, and every transport is mocked: passing shows workflow
behavior — what is requested, when, and in which order it is written — not live provider timing, not how much wall
clock the parallel read saves, and not how often a real provider answers 429.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import threading
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from deixis.providers import biorxiv as biorxiv_module
from deixis.providers import common
from deixis.providers.registry import CONNECTORS
from deixis.workflow import flow, views
from test_search_paging import app_for, client_of, discover, read_limit, wait

FIXTURES = Path(__file__).parent / "fixtures" / "search_parallelism"
QUESTION = "What is the effect of packet size on energy consumption in wireless sensor networks?"
ID = re.compile(r"\b[a-z]{3}_[0-9A-Za-z]{20}\b")

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


def setup(tmp_path, monkeypatch, hosts, second_round=()):
    """An sw app whose vocabulary compiles FIRST_ROUND and whose expansion adds `second_round`, with small pages."""
    monkeypatch.setattr(flow, "SW_READ_LIMIT", read_limit(100))
    compiled = queries_of(FIRST_ROUND)
    monkeypatch.setattr(flow.query_compiler, "compile_block_queries", lambda *a, **k: [dict(q) for q in compiled])

    async def expansion(self, run, scope, vocabulary, queries, criterion=None, approval=None):
        return queries_of(second_round)

    monkeypatch.setattr(flow.ResearchFlow, "_expansion", expansion)
    app = app_for(tmp_path, monkeypatch, hosts)
    for provider, size in (("openalex", 10), ("biorxiv", 10), ("semantic_scholar", 10)):
        monkeypatch.setitem(CONNECTORS, provider, replace(CONNECTORS[provider], max_results=size))
    monkeypatch.setenv("SERPAPI_API_KEY", "SYNTHETIC-key")
    return app


class Session:
    """One app and client for a test: a discovery, then any resume or retry, read before the client closes."""

    def __init__(self, tmp_path, monkeypatch, hosts, second_round=()):
        self.app = setup(tmp_path, monkeypatch, hosts, second_round)
        self.client = client_of(self.app)
        self.store = self.app.state.store

    def start(self, effort="quick"):
        """Create the research and queue its discovery run without waiting for it."""
        body = {"question": QUESTION, "model_connection": "fake", "requested_model": "fake-model", "effort": effort}
        self.rid = self.client.post("/api/researches", json=body).json()["research"]["id"]
        self.run_id = self.client.post(f"/api/researches/{self.rid}/runs", json={"kind": "discovery"}).json()["id"]
        return self

    def discover(self, effort="quick"):
        self.rid, self.run_id, self.view, self.run = discover(self.client, QUESTION, effort=effort)
        return self

    def control(self, action):
        response = self.client.post(f"/api/runs/{self.run_id}/{action}")
        assert response.status_code == 200, response.text
        self.view, self.run = wait(self.client, self.rid, self.run_id)
        return self

    def evidence(self):
        return evidence(self.store, self.rid, self.run_id)

    def close(self):
        self.client.__exit__(None, None, None)


def run_discovery(tmp_path, monkeypatch, hosts, second_round=(), effort="quick"):
    session = Session(tmp_path, monkeypatch, hosts, second_round)
    try:
        session.discover(effort)
        return session.evidence(), session.view, session.run
    finally:
        session.close()


# ---- the evidence a run leaves, with random identifiers and clocks taken out ------------------------------------


class Labels:
    """Each random identifier becomes its prefix and the order it was first met in, so two runs compare row for row."""

    def __init__(self):
        self.seen = {}

    def __call__(self, value):
        if isinstance(value, str):
            return ID.sub(lambda m: self.seen.setdefault(m.group(0), f"{m.group(0)[:3]}#{len(self.seen)}"), value)
        if isinstance(value, dict):
            return {k: self(v) for k, v in value.items() if not k.endswith("_at")}
        if isinstance(value, (list, tuple)):
            return [self(v) for v in value]
        return value


def rows(store, sql, *args):
    return [dict(r) for r in store.conn.execute(sql, args)]


def evidence(store, rid, run_id):
    """What the search stage wrote, in write order. Only run steps' clocks and creation order are left out."""
    labels = Labels()
    steps = {s["id"]: s for s in rows(store, "SELECT * FROM run_steps WHERE run_id = ?", run_id)}
    for step in steps.values():  # a step is named by its operation key, which does not depend on when it was created
        labels.seen[step["id"]] = f"step:{step['operation_key']}"
    events = rows(store, "SELECT type, payload_json FROM events WHERE research_id = ? ORDER BY id", rid)
    searching = [i for i, e in enumerate(events) if '"provider_search:' in e["payload_json"] or e["type"] == "search_recorded"]
    events = [(e["type"], json.loads(e["payload_json"])) for e in events[searching[0]:searching[-1] + 1]]
    search_steps = {s["operation_key"]: {k: s[k] for k in ("kind", "status", "attempt", "error_code", "delivery_class")}
                    | {"output": json.loads(s["output_json"]) if s["output_json"] else None,
                       "error": json.loads(s["error_json"]) if s["error_json"] else None}
                    for s in steps.values() if s["kind"].startswith("provider_search:")}
    found = labels({
        "events": events,
        "search_runs": rows(store, "SELECT * FROM search_runs WHERE research_id = ? ORDER BY rowid", rid),
        "source_versions": rows(store, "SELECT id, work_id, title, doi, version_label FROM source_versions ORDER BY rowid"),
        "identifiers": rows(store, "SELECT source_version_id, scheme, value, provider FROM identifier_mappings ORDER BY rowid"),
        "candidates": rows(store, "SELECT id, search_run_id, source_version_id, rank FROM candidates"
                                  " WHERE research_id = ? ORDER BY rowid", rid),
        "memberships": rows(store, "SELECT * FROM corpus_memberships"
                                   " WHERE research_id = ? ORDER BY rowid", rid),
        "links": rows(store, "SELECT * FROM record_links ORDER BY rowid"),
        "heads": sorted(store.work_heads(rid).items()),
        "steps": dict(sorted(search_steps.items())),
        "unread": views.research_view(store, rid)["counts"]["unread"],
    })
    # Two rows that name a pair or a work by their random identifiers are ordered by them; the labels order them instead.
    for link in found["links"]:
        link["source_version_id"], link["other_source_version_id"] = sorted(
            (link["source_version_id"], link["other_source_version_id"]))
    found["links"] = sorted(found["links"], key=lambda link: json.dumps(link, sort_keys=True))
    found["heads"] = sorted(found["heads"])
    return found


def golden(name, value):
    """The fixture the sequential code wrote (slice 13f, Task 1); DEIXIS_WRITE_SEARCH_FIXTURES=1 writes it again."""
    path = FIXTURES / f"{name}.json"
    if os.environ.get("DEIXIS_WRITE_SEARCH_FIXTURES"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def same(value):
    return json.loads(json.dumps(value, sort_keys=True))


# ---- Task 1: equality, written on the sequential code ----------------------------------------------------------


def test_the_first_round_writes_the_evidence_the_sequential_read_wrote(tmp_path, monkeypatch):
    """Three hosts, five queries, paged reads, a DOI two providers share, a rate-limited page and a single-page
    provider: every row, output and event is the one the sequential code wrote, in the same order."""
    found, view, run = run_discovery(tmp_path, monkeypatch, Hosts())
    assert "abstract_stage" in {s["operation_key"] for s in run["steps"]}, run
    assert same(found) == golden("first_round", same(found))


def test_the_expansion_round_writes_the_evidence_the_sequential_read_wrote(tmp_path, monkeypatch):
    found, view, run = run_discovery(tmp_path, monkeypatch, Hosts(), SECOND_ROUND)
    assert "abstract_stage" in {s["operation_key"] for s in run["steps"]}, run
    assert [s["query_text"] for s in found["search_runs"]][-4:] == [
        "SYNTHETIC transmit power control", "SYNTHETIC transmit power control", "SYNTHETIC drift turbulence coding",
        "SYNTHETIC vascular relay hop"]
    assert same(found) == golden("second_round", same(found))


def test_a_host_that_fails_every_query_does_not_pause_the_run_while_another_succeeds(tmp_path, monkeypatch):
    """D18: a failed search is recorded and the others go on."""
    found, view, run = run_discovery(tmp_path, monkeypatch, Hosts(fail={"api.semanticscholar.org"}))
    assert "abstract_stage" in {s["operation_key"] for s in run["steps"]}, run
    statuses = {(s["provider"], s["status"]) for s in view["search_runs"]}
    assert ("semantic_scholar", "failed") in statuses and ("openalex", "completed") in statuses


def test_a_run_whose_every_search_fails_pauses(tmp_path, monkeypatch):
    hosts = Hosts(fail={"api.openalex.org", "api.semanticscholar.org", "serpapi.com"})
    found, view, run = run_discovery(tmp_path, monkeypatch, hosts)
    assert (run["status"], run["pause_reason"]) == ("paused", "provider_failed"), run
    assert {s["status"] for s in view["search_runs"]} == {"failed"}
    assert "vocabulary_expansion" not in {s["operation_key"] for s in run["steps"]}


# ---- Task 2: the request allowance is each query's own (D89) ---------------------------------------------------


class RefusedOnce(Hosts):
    """Every page of the named queries answers 429 once, with no wait, and then serves: each page costs two requests."""

    def __init__(self, queries, **kwargs):
        super().__init__(**kwargs)
        self.queries, self.refused = set(queries), set()

    @staticmethod
    def page(host, params):
        if host == "api.openalex.org":
            return params.get("search.title_and_abstract"), 0 if params.get("cursor") in (None, "*") else int(params["cursor"])
        if host == "api.semanticscholar.org":
            return params["query"], int(params.get("offset") or 0)
        return params["q"], 0

    def answer(self, host, params, entry):
        response = super().answer(host, params, entry)
        page = (entry["query"], entry["start"])
        if entry["query"] in self.queries and response.status_code == 200 and page not in self.refused:
            self.refused.add(page)
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


def test_a_query_that_uses_up_its_share_ends_its_own_read_and_the_run_goes_on(tmp_path, monkeypatch):
    """Each page of the first query needs a retry, so its share of three requests is spent on its second page: that
    page ends the read with `budget_exhausted` and counts what it left unread, every other query is read whole, and
    the run is not paused."""
    small_allowances(monkeypatch, {"SYNTHETIC packet size energy": 3})
    hosts = RefusedOnce({"SYNTHETIC packet size energy"})
    found, view, run = run_discovery(tmp_path, monkeypatch, hosts, effort="standard")
    assert "abstract_stage" in {s["operation_key"] for s in run["steps"]}, run
    assert run["pause_reason"] != "budget_exhausted"
    first = [r for r in view["search_runs"] if r["query_text"] == "SYNTHETIC packet size energy"]
    assert [(r["page_number"], r["stop_reason"], r["unread_count"]) for r in first] == [
        (0, None, None), (1, "budget_exhausted", 5)]
    assert [p for p in hosts.requests("api.openalex.org") if p[1] == "SYNTHETIC packet size energy"] == [
        ("openalex", "SYNTHETIC packet size energy", 0)] * 2 + [("openalex", "SYNTHETIC packet size energy", 10)] * 2
    assert run["usage"]["query_requests"]["search:0"] == 4
    # Every other query read as far as it does with no allowance at all.
    reads = {(r["query_text"], r["stop_reason"]) for r in view["search_runs"] if r["stop_reason"]}
    assert reads >= {("SYNTHETIC diffusion channel release", "exhausted"), ("SYNTHETIC sensor duty cycle", "exhausted"),
                     ("SYNTHETIC molecular relay energy", "single_page")}
    assert found["steps"]["search:0:page:1"]["output"]["stop_reason"] == "budget_exhausted"


def test_a_query_s_share_does_not_depend_on_which_host_answered_first(tmp_path, monkeypatch):
    small_allowances(monkeypatch, {"SYNTHETIC packet size energy": 3})
    found = []
    for delay in ({"api.openalex.org": 0.05}, {"api.semanticscholar.org": 0.05, "serpapi.com": 0.05}):
        path = tmp_path / str(len(found))
        found.append(same(run_discovery(path, monkeypatch, RefusedOnce({"SYNTHETIC packet size energy"}, delay=delay),
                                        effort="standard")[0]))
    assert found[0] == found[1]


def test_a_resumed_run_keeps_each_query_s_count(tmp_path, monkeypatch):
    """The second page of one query fails after its share is spent. Asked to search again, the run finds the count
    it stored for that query, sends nothing, and says on the page's step that the allowance ended the read."""
    small_allowances(monkeypatch, {"SYNTHETIC receiver sampling budget": 2})
    hosts = Hosts()
    session = Session(tmp_path, monkeypatch, hosts)
    try:
        session.discover(effort="standard")
        # Page 0 is one request, the refused page 1 two (standard waits out one 429): three of a share of two.
        assert session.run["usage"]["query_requests"]["search:3"] == 3
        asked = list(hosts.log)
        session.control("retry_failed")  # the retry action adds one request to every query's share: 2 + 1 = 3
        assert hosts.log == asked  # nothing was sent again
        assert session.run["usage"]["query_requests"]["search:3"] == 3
        step = next(s for s in session.run["steps"] if s["operation_key"] == "search:3:page:1")
        assert (step["status"], step["error_code"]) == ("cancelled", "budget_exhausted")
    finally:
        session.close()


# ---- Task 3: hosts side by side, one request per host, written in query order -------------------------------------


def overlapping(log, a, b):
    """Whether a request to host `a` and one to host `b` were in flight at the same time."""
    return any(x["started"] < y["finished"] and y["started"] < x["finished"]
               for x in log if x["host"] == a for y in log if y["host"] == b)


def test_hosts_are_read_side_by_side_and_each_host_one_request_at_a_time(tmp_path, monkeypatch):
    hosts = Hosts(delay={"api.openalex.org": 0.05, "api.semanticscholar.org": 0.05, "serpapi.com": 0.05})
    found, view, run = run_discovery(tmp_path, monkeypatch, hosts)
    assert overlapping(hosts.log, "api.openalex.org", "api.semanticscholar.org")
    assert overlapping(hosts.log, "api.openalex.org", "serpapi.com")
    # OpenAlex and bioRxiv share a host, so their queries are read one after the other, never at once.
    assert all(hosts.most[host] == 1 for host in ("api.openalex.org", "api.semanticscholar.org", "serpapi.com"))
    assert hosts.most["hosts"] == 3 <= flow.SEARCH_PARALLEL_HOSTS
    assert same(found) == golden("first_round", same(found))


def test_no_more_hosts_are_read_at_once_than_the_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, "SEARCH_PARALLEL_HOSTS", 2)
    hosts = Hosts(delay={"api.openalex.org": 0.05, "api.semanticscholar.org": 0.05, "serpapi.com": 0.05})
    found, view, run = run_discovery(tmp_path, monkeypatch, hosts)
    assert hosts.most["hosts"] == 2
    assert same(found) == golden("first_round", same(found))


@pytest.mark.parametrize("second_round", [False, True])
def test_a_later_query_whose_host_answers_first_is_still_written_in_query_order(tmp_path, monkeypatch, second_round):
    """OpenAlex holds every answer back, so Semantic Scholar and SerpApi have read their queries before the first
    query's pages arrive: the evidence is still the sequential read's, row for row."""
    hosts = Hosts(delay={"api.openalex.org": 0.08})
    found, view, run = run_discovery(tmp_path, monkeypatch, hosts, SECOND_ROUND if second_round else ())
    first_semantic = next(i for i, e in enumerate(hosts.log) if e["host"] == "api.semanticscholar.org")
    assert first_semantic < next(i for i, e in enumerate(hosts.log) if e["host"] == "api.openalex.org")
    name = "second_round" if second_round else "first_round"
    assert same(found) == golden(name, same(found))


def content(store, rid):
    """What a run found, named without its write order: each page by its step key, each record by its DOI."""
    keys = {r["id"]: r["operation_key"] for r in store.conn.execute("SELECT id, operation_key FROM run_steps")}
    pages = {keys[r["step_id"]]: {k: r[k] for k in ("provider", "query_text", "status", "result_count", "provider_total",
                                                     "page_limit", "page_number", "read_total", "stop_reason",
                                                     "unread_count", "payload_sha256")}
             for r in store.conn.execute("SELECT * FROM search_runs WHERE research_id = ?", (rid,))}
    dois = sorted(r[0] or "" for r in store.conn.execute(
        "SELECT v.doi FROM candidates c JOIN source_versions v ON v.id = c.source_version_id WHERE c.research_id = ?",
        (rid,)))
    return {"pages": pages, "dois": dois, "versions": store.conn.execute("SELECT COUNT(*) FROM source_versions").fetchone()[0],
            "unread": views.research_view(store, rid)["counts"]["unread"]}


def test_a_pause_lets_the_requests_in_flight_finish_writes_what_was_read_in_order_and_asks_nothing_twice(
        tmp_path, monkeypatch):
    """The first query's second page is in flight when the run is paused. It finishes and is written; so are the
    pages the other hosts had read, in query order; nothing more is asked. Resumed, the run asks for the rest only.

    What the resumed run holds is what an uninterrupted run holds, page for page and record for record. The order
    is not always the same (D89, Limits): the later queries' pages read before the pause were written before the
    rest of the first query, so a DOI two providers share can be first written by the other provider. The owner
    chose that over asking those pages again (2026-09-22).
    """
    uninterrupted = Session(tmp_path / "whole", monkeypatch, Hosts())
    try:
        whole = content(uninterrupted.discover().store, uninterrupted.rid)
    finally:
        uninterrupted.close()

    gate = threading.Event()
    hosts = Hosts(hold={("SYNTHETIC packet size energy", 10): gate})
    session = Session(tmp_path / "paused", monkeypatch, hosts).start()
    try:
        deadline = time.time() + 10
        while ("SYNTHETIC packet size energy", 10) not in hosts.waiting:  # the first query's second page is in flight
            assert time.time() < deadline
            time.sleep(0.01)
        assert session.client.post(f"/api/runs/{session.run_id}/pause").status_code == 200
        gate.set()
        session.view, session.run = wait(session.client, session.rid, session.run_id)
        assert (session.run["status"], session.run["pause_reason"]) == ("paused", "user_requested"), session.run
        # The page in flight finished and was written; the host was asked nothing after it, so bioRxiv's query,
        # which shares that host, was not started.
        assert hosts.requests("api.openalex.org") == [("openalex", "SYNTHETIC packet size energy", 0),
                                                      ("openalex", "SYNTHETIC packet size energy", 10)]
        order = {text: index for index, (_, text) in enumerate(FIRST_ROUND)}
        written = [(order[r["query_text"]], r["page_number"]) for r in session.store.conn.execute(
            "SELECT query_text, page_number FROM search_runs WHERE research_id = ? ORDER BY rowid", (session.rid,))]
        assert written[:2] == [(0, 0), (0, 1)] and written == sorted(written)
        # Resumed, the run asks for the pages it had not read and for none it had.
        session.control("resume")
        assert "abstract_stage" in {s["operation_key"] for s in session.run["steps"]}, session.run
        assert set(Counter(hosts.requests()).values()) == {1}
        assert content(session.store, session.rid) == whole
    finally:
        session.close()


def test_a_page_step_carries_the_time_of_its_request_not_the_time_it_was_written(tmp_path, monkeypatch):
    """Semantic Scholar's first query is read while OpenAlex's pages are still arriving, and written after them."""
    session = Session(tmp_path, monkeypatch, Hosts(delay={"api.openalex.org": 0.08}))
    try:
        session.discover()
        steps = {s["operation_key"]: s for s in session.store.run_steps(session.run_id)}
    finally:
        session.close()
    assert steps["search:1"]["started_at"] < steps["search:0:page:2"]["started_at"]
    assert steps["search:1"]["finished_at"] < steps["search:0:page:2"]["finished_at"]
    assert all(s["started_at"] <= s["finished_at"] for key, s in steps.items() if key.startswith("search:"))


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


# ---- review of 2026-09-23 (gpt-6-sol high) -----------------------------------------------------------------------


def test_a_first_round_whose_every_share_was_spent_before_it_asked_pauses_instead_of_going_on(tmp_path, monkeypatch):
    """D18: with no successful search the run pauses, also when no search failed because every query's share was
    already spent (a run resumed after a crash). Asked to search again, the retry adds to every share and reads."""
    small_allowances(monkeypatch, {text: 0 for _, text in FIRST_ROUND})
    hosts = Hosts()
    session = Session(tmp_path, monkeypatch, hosts)
    try:
        session.discover()
        assert (session.run["status"], session.run["pause_reason"]) == ("paused", "budget_exhausted"), session.run
        assert hosts.log == [] and "vocabulary_expansion" not in {s["operation_key"] for s in session.run["steps"]}
        session.control("retry_failed")
        assert "abstract_stage" in {s["operation_key"] for s in session.run["steps"]}, session.run
        assert hosts.requests("api.openalex.org")
    finally:
        session.close()


def test_a_query_resumed_past_a_lowered_read_limit_asks_for_nothing_more(tmp_path, monkeypatch):
    """A query read 20 records and was paused mid-read; the read limit is then lowered below what it has read (13g
    halved `detailed`). Resumed, it ends its read where it stands instead of asking for a page of minus records."""
    gate = threading.Event()
    hosts = Hosts(hold={("SYNTHETIC packet size energy", 10): gate})
    session = Session(tmp_path, monkeypatch, hosts).start()
    try:
        deadline = time.time() + 10
        while ("SYNTHETIC packet size energy", 10) not in hosts.waiting:
            assert time.time() < deadline
            time.sleep(0.01)
        assert session.client.post(f"/api/runs/{session.run_id}/pause").status_code == 200
        gate.set()
        session.view, session.run = wait(session.client, session.rid, session.run_id)
        assert session.run["pause_reason"] == "user_requested", session.run
        monkeypatch.setattr(flow, "SW_READ_LIMIT", read_limit(15))
        asked = len([p for p in hosts.requests("api.openalex.org") if p[1] == "SYNTHETIC packet size energy"])
        session.control("resume")
        assert "abstract_stage" in {s["operation_key"] for s in session.run["steps"]}, session.run
        assert len([p for p in hosts.requests("api.openalex.org") if p[1] == "SYNTHETIC packet size energy"]) == asked
    finally:
        session.close()


def test_a_pause_asked_while_a_query_waits_out_its_page_gap_sends_no_further_page(tmp_path, monkeypatch):
    """The stop is looked at again after the gap between two pages, not only before it (arXiv waits 3 s there)."""
    hosts = Hosts()
    session = Session(tmp_path, monkeypatch, hosts)
    monkeypatch.setitem(CONNECTORS, "openalex", replace(CONNECTORS["openalex"], page_gap=0.6))
    session.start()
    try:
        deadline = time.time() + 10
        while not any(e.get("query") == "SYNTHETIC packet size energy" for e in hosts.log):
            assert time.time() < deadline
            time.sleep(0.005)
        assert session.client.post(f"/api/runs/{session.run_id}/pause").status_code == 200
        session.view, session.run = wait(session.client, session.rid, session.run_id)
        assert session.run["pause_reason"] == "user_requested", session.run
        assert [p for p in hosts.requests("api.openalex.org") if p[1] == "SYNTHETIC packet size energy"] == [
            ("openalex", "SYNTHETIC packet size energy", 0)]
    finally:
        session.close()


def test_an_error_on_one_host_still_writes_what_the_other_hosts_had_read(tmp_path, monkeypatch):
    """Semantic Scholar's connector raises while OpenAlex is still reading: the run fails, but the pages OpenAlex
    read are written in query order, and OpenAlex is asked for nothing after the error."""
    session = Session(tmp_path, monkeypatch, Hosts(delay={"api.openalex.org": 0.15}))

    async def broken(*args, **kwargs):
        raise RuntimeError("SYNTHETIC parser bug")

    monkeypatch.setitem(CONNECTORS, "semantic_scholar", replace(CONNECTORS["semantic_scholar"], search=broken))
    try:
        session.discover()
        assert session.run["status"] == "failed", session.run
        order = {text: index for index, (_, text) in enumerate(FIRST_ROUND)}
        written = [(r[0], order[r[1]]) for r in session.store.conn.execute(
            "SELECT provider, query_text FROM search_runs WHERE research_id = ? ORDER BY rowid", (session.rid,))]
        assert ("openalex", 0) in written and "semantic_scholar" not in {p for p, _ in written}
        assert [i for _, i in written] == sorted(i for _, i in written)
    finally:
        session.close()


def test_a_pause_asked_while_a_failed_request_waits_to_be_sent_again_sends_nothing_more(tmp_path, monkeypatch):
    """A page whose request failed before it was sent waits before its retry; a pause asked in that wait sends no
    retry, leaves the page unwritten, and the resumed run asks for that page again (second review of 13f)."""
    hosts = Hosts()
    session = Session(tmp_path, monkeypatch, hosts)
    original, calls, flaky_on = CONNECTORS["openalex"].search, [], [True]

    async def flaky(client, query, limit, *args, cursor=None, **kwargs):
        outcome = await original(client, query, limit, *args, cursor=cursor, **kwargs)
        if query == "SYNTHETIC packet size energy" and cursor not in (None, "*"):
            calls.append(cursor)
            if flaky_on[0]:
                return replace(outcome, status="failed", delivery_class="before_send", records=[])
        return outcome

    monkeypatch.setitem(CONNECTORS, "openalex", replace(CONNECTORS["openalex"], search=flaky))
    session.start()
    try:
        deadline = time.time() + 10
        while not calls:
            assert time.time() < deadline
            time.sleep(0.005)
        assert session.client.post(f"/api/runs/{session.run_id}/pause").status_code == 200
        session.view, session.run = wait(session.client, session.rid, session.run_id)
        assert session.run["pause_reason"] == "user_requested", session.run
        assert len(calls) == 1
        assert rows(session.store, "SELECT 1 FROM search_runs WHERE research_id = ? AND query_text = ? AND page_number = 1",
                    session.rid, "SYNTHETIC packet size energy") == []
        flaky_on[0] = False
        session.control("resume")
        assert calls[1] == calls[0] and session.run["status"] == "completed", session.run
    finally:
        session.close()
