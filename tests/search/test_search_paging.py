"""Reading one `sw` query page by page, up to the keyword cap, and counting what stayed unread (slice 04c).

Since the clean start (slice 3a) discovery reads OpenAlex keyword pages only, round robin over its queries up to the
frozen `keyword_cap` (fast path, D252); the old search round, which paged every provider to the effort's read limit,
was removed with its tests. The page behaviour it shared with the fast path is checked here through
`fast_search.execute` with a hand-built plan, the real `_send_search` and a mocked transport.

Records and provider answers are SYNTHETIC and the transport is mocked: passing shows workflow behavior — which page
is requested, what stops the read, how a failed page is carried — not live provider paging or recall.
"""

import json

import pytest

from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow.run.store import Store


@pytest.fixture
def store(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    yield Store(connection)
    connection.close()


def record(number):
    return ProviderRecord(
        provider_record_id=f"W{number}", title=f"SYNTHETIC record {number}", authors=[], year=2026, venue=None,
        publication_type=None, doi=f"10.1/synth.{number}", landing_url=None, oa_pdf_url=None, oa_pdf_version=None,
        version_label=None, abstract=None, abstract_origin=None, identifiers={}, raw={},
    )


def research(store, search_workflow="sw"):
    rid = store.create_research("SYNTHETIC question?", "academic", "standard", ["openalex"], "fake", "m", "en",
                                search_workflow=search_workflow)
    run = store.create_run(rid, "discovery", {"max_model_calls": 4, "max_provider_requests": 4, "max_candidates": 50,
                                              "max_answer_passages": 8}, None)
    return rid, run["id"]


def search(store, rid, run_id, key, records, first_rank=None, **fields):
    step = store.step(run_id, key, "provider_search:openalex")
    search_fields = dict(
        research_id=rid, run_id=run_id, step_id=step["id"], scope_revision=1, provider="openalex", query_text="q",
        request_description="GET test", access_mode="keyless", status="completed", delivery_class=None,
        result_count=len(records), provider_total=len(records), page_limit=25, error_json=None, raw_payload_path=None,
        **fields,
    )
    extra = {} if first_rank is None else {"first_rank": first_rank}
    store.record_search(search_fields, "openalex", records, None, step["id"], "succeeded",
                        step_output={"status": "completed"}, **extra)
    return step


def ranks(store, rid):
    return [r[0] for r in store.conn.execute(
        "SELECT rank FROM candidates WHERE research_id = ? ORDER BY rank", (rid,))]


# ---- a paged sw discovery through the API -------------------------------------------
import time

import httpx
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents.fetch import FetchResult
from deixis.models.adapter import ModelStepResult
from dataclasses import replace

from deixis.providers.registry import CONNECTORS
from fakes import FakeAdapter

QUESTION = "What is the effect of packet size on energy consumption in wireless sensor networks?"


def DeadAdapter():
    """Every model call fails, so the run reads all of its pages and then stops at screening (SW2.3)."""
    return FakeAdapter(fail=lambda si: ModelStepResult("failed", error="SYNTHETIC model connection is down"))


def work(number):
    return {"id": f"https://openalex.org/W{number}", "doi": f"https://doi.org/10.1/oa.{number}",
            "display_name": f"SYNTHETIC record {number}", "publication_year": 2024, "type": "article",
            "authorships": [], "abstract_inverted_index": {"We": [0], "measure.": [1]}}


def crossref_item(number):
    return {"DOI": f"10.2/cr.{number}", "title": [f"SYNTHETIC crossref record {number}"], "type": "journal-article",
            "URL": f"https://doi.org/10.2/cr.{number}"}


class PagedProviders:
    """OpenAlex served as cursor pages and Crossref as offset pages, with every page request recorded.

    `fail_at` makes the page that starts at that record answer 429 until `recover` is set, for every OpenAlex query
    or, with `fail_query`, for that query only; everything else is a 404, so a provider that is not mocked fails on its
    first page and the run carries on (D18). `queries` logs each OpenAlex page request with its query text.
    """

    def __init__(self, openalex_total=450, crossref_total=0, fail_at=None, openalex_next_total=None, fail_query=None):
        self.openalex_total, self.crossref_total = openalex_total, crossref_total
        self.fail_at, self.recover, self.openalex_next_total = fail_at, False, openalex_next_total
        self.fail_query = fail_query
        self.openalex, self.crossref, self.queries = [], [], []

    def __call__(self, request):
        params = request.url.params
        if request.url.host == "api.openalex.org":
            if params.get("per_page") == "1" and params.get("select") == "id":
                # Count probes. The number is below the field-probe threshold of slice 04b, so the expansion
                # accepts no phrase here and these tests stay about the paging of one round; the second round has
                # its own tests in test_expansion_flow.py.
                return httpx.Response(200, json={"meta": {"count": 8}, "results": []})
            if "per_page" not in params:
                # The routing step's field distribution (`group_by`): left unknown, so routing records "unavailable".
                return httpx.Response(404)
            cursor, size = params.get("cursor"), int(params["per_page"])
            start = 0 if cursor in (None, "*") else int(cursor)
            self.openalex.append((start, size))
            self.queries.append((params.get("search.title_and_abstract"), start))
            if start == self.fail_at and not self.recover and self.fail_query in (None, params.get("search.title_and_abstract")):
                return httpx.Response(429, text="SYNTHETIC rate limit", headers={"retry-after": "600"})
            end = min(start + size, self.openalex_total)
            total = self.openalex_total if self.openalex_next_total is None else self.openalex_next_total
            return httpx.Response(200, json={"meta": {"count": total, "next_cursor": str(end) if end < self.openalex_total else None},
                                             "results": [work(i) for i in range(start, end)]})
        if request.url.host == "api.crossref.org":
            if "rows" not in params:
                # A slice 05 DOI lookup, not a search: these SYNTHETIC DOIs are in no registry, and a record whose
                # abstract no source fills changes nothing about the paging these tests are for.
                return httpx.Response(404, text="Resource not found.")
            start, size = int(params.get("offset") or 0), int(params["rows"])
            self.crossref.append((start, size))
            end = min(start + size, self.crossref_total)
            return httpx.Response(200, json={"message": {"total-results": self.crossref_total,
                                                         "items": [crossref_item(i) for i in range(start, end)]}})
        return httpx.Response(404)


async def no_fetch(url):
    return FetchResult("http_error", final_url=url, http_status=404)


def app_for(tmp_path, monkeypatch, handler, workflow="sw", adapter=None):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    # Small pages keep the fixtures small. Paging is the same at 20 records a page as at 200; what a provider's real
    # page size and reachable depth are is checked against its documentation in tests/search/test_providers.py.
    # Crossref stands in for an offset-paged provider here and is made searchable for that: the product no longer
    # sends it a query (D87), and that is what tests/search/test_provider_roles.py is for.
    for provider, size in (("openalex", 20), ("crossref", 10)):
        monkeypatch.setitem(CONNECTORS, provider,
                            replace(CONNECTORS[provider], max_results=size, searchable=True))
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", workflow)
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_query="code",
                               fulltext_fetch="off"),
                      adapters={"fake": adapter or DeadAdapter()},
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), fetcher=no_fetch,
                      extra_hosts=("testserver",), trusted_clients=("testclient",))


def wait(client, rid, run_id):
    deadline = time.time() + 30
    while time.time() < deadline:
        view = client.get(f"/api/researches/{rid}").json()
        run = next(r for r in view["runs"] if r["id"] == run_id)
        if run["status"] in ("completed", "failed", "paused"):
            return view, run
        time.sleep(0.05)
    raise AssertionError("the run did not settle")


def discover(client, question=QUESTION, **body):
    payload = {"question": question, "model_connection": "fake", "requested_model": "fake-model", "effort": "quick",
               **body}
    rid = client.post("/api/researches", json=payload).json()["research"]["id"]
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    return rid, run_id, *wait(client, rid, run_id)


def client_of(app):
    client = TestClient(app)
    client.__enter__()
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    return client


def rows_of(view, provider="openalex"):
    return [s for s in view["search_runs"] if s["provider"] == provider]


# ---- keyword pages on the fast path (fast_search.execute) ------------------------------------------------------
import asyncio
from types import SimpleNamespace

from deixis.workflow.run import fast_path, views
from deixis.workflow.search import search as fast_search
from deixis.workflow.run.flow import ResearchFlow
from test_fast_path_clock import library  # noqa: F401  (a fixture: one quick fast-path discovery run on a FakeClock)

ALPHA, BETA = "SYNTHETIC packet size energy", "SYNTHETIC duty cycle relay"


def keyword_reader(lib, tmp_path, handler, effort=None):
    """A flow over `lib`'s discovery run whose provider transport is `handler`, and the scope it reads with.

    `effort` replaces the research's own in the scope: it is what the page allowance and the 429 waits are read from.
    """
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    research_flow = ResearchFlow(SimpleNamespace(store=lib.store, clock=lib.clock, local_embedder=None, http=http,
                                                 settings=Settings(data_dir=tmp_path / "data")))
    scope = lib.store.scope(lib.rid) | ({"effort": effort} if effort else {})
    fast_path.enter_stage(lib.store, lib.run, "search")
    return research_flow, scope


def keyword_plan(lib, scope, texts=(ALPHA,), page_size=20, cap=None):
    """The frozen plan of `texts` as OpenAlex keyword queries, with small pages and no semantic request."""
    plan = fast_search.build_plan(lib.store, lib.run, scope,
                                  [{"provider_id": "openalex", "query_text": text} for text in texts])
    plan["semantic"]["query_text"] = None  # these tests are about keyword pages; the semantic slot is closed unasked
    return plan | {"page_size": page_size} | ({"keyword_cap": cap} if cap is not None else {})


def read_pages(research_flow, lib, scope, plan, retry_failed=False, query=None):
    """Run the keyword read once and return the search rows written so far, of `query` only when one is named."""
    asyncio.run(fast_search.execute(research_flow, lib.run, scope, plan, retry_failed))
    return [dict(r) for r in lib.conn.execute("SELECT * FROM search_runs WHERE run_id = ? ORDER BY rowid",
                                               (lib.run["id"],)) if query is None or r["query_text"] == query]


def test_a_query_stops_at_the_keyword_cap_and_counts_what_it_did_not_read(library, tmp_path):
    providers = PagedProviders(openalex_total=45)
    research_flow, scope = keyword_reader(library, tmp_path, providers)
    rows = read_pages(research_flow, library, scope, keyword_plan(library, scope, cap=30))
    # The last page asks only for what is left of the cap, so the read stops exactly on it.
    assert providers.openalex == [(0, 20), (20, 10)]
    assert [(r["page_number"], r["result_count"], r["stop_reason"]) for r in rows] == [
        (0, 20, None), (1, 10, "record_cap")]
    assert (rows[-1]["read_total"], rows[-1]["read_limit"], rows[-1]["unread_count"]) == (30, 30, 15)
    assert views.research_view(library.store, library.rid)["counts"]["unread"] == 15
    kept = library.conn.execute("SELECT COUNT(*) FROM candidates WHERE research_id = ?", (library.rid,)).fetchone()[0]
    assert kept == 30  # the cap stops the reading; it drops no record that was read


def test_a_failed_page_stops_its_query_only_and_is_retried_on_request(library, tmp_path):
    providers = PagedProviders(openalex_total=45, fail_at=20, fail_query=ALPHA)
    research_flow, scope = keyword_reader(library, tmp_path, providers)
    plan = keyword_plan(library, scope, (ALPHA, BETA))
    # The first page's records stand, the failed page is recorded, and the other query reads all of its own (D18).
    rows = read_pages(research_flow, library, scope, plan, query=ALPHA)
    assert [(r["page_number"], r["status"], r["stop_reason"]) for r in rows] == [
        (0, "completed", None), (1, "rate_limited", "page_failed")]
    other = read_pages(research_flow, library, scope, plan, query=BETA)  # a normal resume: nothing is asked again
    assert [(r["page_number"], r["result_count"], r["stop_reason"]) for r in other] == [
        (0, 20, None), (1, 20, None), (2, 5, "exhausted")]
    assert [p for p in providers.queries if p[0] == ALPHA] == [(ALPHA, 0), (ALPHA, 20)]
    # "Search again" (`retry_failed_searches_only`) asks for the failed page once more, and for that page only.
    providers.recover = True
    rows = read_pages(research_flow, library, scope, plan, retry_failed=True, query=ALPHA)
    assert [p for p in providers.queries if p[0] == ALPHA] == [(ALPHA, 0), (ALPHA, 20), (ALPHA, 20)]
    assert [p for p in providers.queries if p[0] == BETA] == [(BETA, 0), (BETA, 20), (BETA, 40)]
    # The failed page keeps its own row; the successful retry is a second row beside it, not an edit of it (D18).
    assert [(r["page_number"], r["status"], r["stop_reason"]) for r in rows] == [
        (0, "completed", None), (1, "rate_limited", "page_failed"), (1, "completed", "retry_page_only")]
    assert rows[-1]["unread_count"] == 5


def test_a_provider_that_reports_no_total_leaves_the_unread_count_unknown(library, tmp_path):
    """`unread_count` is NULL when the provider gave no total: unknown, never zero."""
    research_flow, scope = keyword_reader(library, tmp_path, _without_total(PagedProviders(openalex_total=12)))
    rows = read_pages(research_flow, library, scope, keyword_plan(library, scope))
    assert rows[-1]["stop_reason"] == "exhausted" and rows[-1]["unread_count"] is None
    assert views.research_view(library.store, library.rid)["counts"]["unread"] == 0  # nothing known to count


def _without_total(providers):
    def handler(request):
        response = providers(request)
        if request.url.host == "api.openalex.org" and response.status_code == 200:
            payload = json.loads(response.content)
            if payload["results"] or "next_cursor" in payload["meta"]:
                payload["meta"].pop("count", None)
                return httpx.Response(200, json=payload)
        return response
    return handler


