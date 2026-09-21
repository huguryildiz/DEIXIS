"""Reading one `sw` query page by page, up to the read limit, and counting what stayed unread (slice 04c).

Records and provider answers are SYNTHETIC and the transport is mocked: passing shows workflow behavior — which page
is requested, what stops the read, how a failed page is carried — not live provider paging or recall. A `legacy`
research is exercised here too, because nothing about it may change.
"""

import json

import pytest

from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow.store import Store


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


def test_a_page_ranks_its_records_where_the_query_left_off(store):
    """Rank is the record's place in the query, not in its page, so a later page never outranks an earlier one."""
    rid, run_id = research(store)
    search(store, rid, run_id, "search:0", [record(i) for i in range(3)], first_rank=0)
    search(store, rid, run_id, "search:0:page:1", [record(i) for i in range(3, 6)], first_rank=3)
    assert ranks(store, rid) == [0, 1, 2, 3, 4, 5]


def test_a_search_that_names_no_first_rank_ranks_from_zero(store):
    rid, run_id = research(store)
    search(store, rid, run_id, "search:0", [record(i) for i in range(3)])
    assert ranks(store, rid) == [0, 1, 2]


def test_the_unread_count_follows_the_last_stopped_page_of_each_query(store):
    """A page read again replaces the earlier row of that query rather than adding its count to it."""
    from deixis.workflow import views

    rid, run_id = research(store)
    search(store, rid, run_id, "search:0", [record(i) for i in range(2)], first_rank=0,
           page_number=0, read_limit=4, read_total=2, stop_reason="read_limit", unread_count=40)
    assert views.research_view(store, rid)["counts"]["unread"] == 40
    # The same query read one page further: the count of the query is the later page's, not the sum.
    search(store, rid, run_id, "search:0:page:1", [record(i) for i in range(2, 4)], first_rank=2,
           page_number=1, read_limit=4, read_total=4, stop_reason="read_limit", unread_count=38)
    assert views.research_view(store, rid)["counts"]["unread"] == 38


def test_a_page_whose_provider_named_no_total_is_left_out_of_the_unread_count(store):
    from deixis.workflow import views

    rid, run_id = research(store)
    search(store, rid, run_id, "search:0", [record(0)], first_rank=0, page_number=0, read_limit=4, read_total=1,
           stop_reason="exhausted", unread_count=None)
    assert views.research_view(store, rid)["counts"]["unread"] == 0


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
from deixis.workflow import flow
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

    `fail_at` makes the page that starts at that record answer 429 until `recover` is set; everything else is a 404,
    so a provider that is not mocked fails on its first page and the run carries on (D18).
    """

    def __init__(self, openalex_total=450, crossref_total=0, fail_at=None, openalex_next_total=None):
        self.openalex_total, self.crossref_total = openalex_total, crossref_total
        self.fail_at, self.recover, self.openalex_next_total = fail_at, False, openalex_next_total
        self.openalex, self.crossref = [], []

    def __call__(self, request):
        params = request.url.params
        if request.url.host == "api.openalex.org":
            if params.get("per_page") == "1" and params.get("select") == "id":
                # Count probes. The number is below the field-probe threshold of slice 04b, so the expansion
                # accepts no phrase here and these tests stay about the paging of one round; the second round has
                # its own tests in test_expansion_flow.py.
                return httpx.Response(200, json={"meta": {"count": 8}, "results": []})
            cursor, size = params.get("cursor"), int(params["per_page"])
            start = 0 if cursor in (None, "*") else int(cursor)
            self.openalex.append((start, size))
            if start == self.fail_at and not self.recover:
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
    # page size and reachable depth are is checked against its documentation in tests/test_providers.py.
    for provider, size in (("openalex", 20), ("crossref", 10)):
        monkeypatch.setitem(CONNECTORS, provider, replace(CONNECTORS[provider], max_results=size))
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", workflow)
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_workflow=workflow,
                               protocol_approval="as_proposed"),
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


def test_a_query_whose_provider_holds_less_than_the_limit_is_read_whole(tmp_path, monkeypatch):
    """45 records over three pages: every record becomes a candidate, in query order, and nothing stays unread."""
    providers = PagedProviders(openalex_total=45)
    app = app_for(tmp_path, monkeypatch, providers)
    client = client_of(app)
    try:
        rid, _, view, run = discover(client)
        ranks = [r[0] for r in app.state.store.conn.execute(
            "SELECT rank FROM candidates WHERE research_id = ? ORDER BY rank", (rid,))]
    finally:
        client.__exit__(None, None, None)
    assert providers.openalex == [(0, 20), (20, 20), (40, 20)]
    rows = rows_of(view)
    assert [(r["page_number"], r["result_count"], r["stop_reason"]) for r in rows] == [
        (0, 20, None), (1, 20, None), (2, 5, "exhausted")]
    assert rows[-1]["read_total"] == 45 and rows[-1]["unread_count"] == 0
    assert [s["operation_key"] for s in run["steps"] if s["kind"] == "provider_search:openalex"] == [
        "search:0", "search:0:page:1", "search:0:page:2"]
    assert ranks == list(range(45))  # rank is the record's place in the query, not in its page


def test_a_query_stops_at_the_read_limit_and_counts_what_it_did_not_read(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, "SW_READ_LIMIT", 30)
    providers = PagedProviders(openalex_total=45)
    app = app_for(tmp_path, monkeypatch, providers)
    client = client_of(app)
    try:
        rid, _, view, run = discover(client)
        kept = app.state.store.conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE research_id = ?", (rid,)).fetchone()[0]
    finally:
        client.__exit__(None, None, None)
    # The last page asks only for what is left of the limit, so the read stops exactly on it.
    assert providers.openalex == [(0, 20), (20, 10)]
    rows = rows_of(view)
    assert [(r["page_number"], r["result_count"], r["stop_reason"]) for r in rows] == [(0, 20, None), (1, 10, "read_limit")]
    assert (rows[-1]["read_total"], rows[-1]["read_limit"], rows[-1]["unread_count"]) == (30, 30, 15)
    assert view["counts"]["unread"] == 15
    assert kept == 30  # the limit stops the reading; it drops no record that was read


def test_a_resumed_run_asks_for_no_page_twice(tmp_path, monkeypatch):
    providers = PagedProviders(openalex_total=45)
    client = client_of(app_for(tmp_path, monkeypatch, providers))
    try:
        rid, run_id, _, run = discover(client)
        assert run["status"] == "paused" and run["pause_reason"] == "model_call_failed", run
        read = list(providers.openalex)
        client.post(f"/api/runs/{run_id}/resume")
        view, run = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert providers.openalex == read  # every page came from its stored step
    assert len(rows_of(view)) == 3


def test_a_failed_page_stops_its_query_only_and_is_retried_on_request(tmp_path, monkeypatch):
    providers = PagedProviders(openalex_total=45, crossref_total=12, fail_at=20)
    client = client_of(app_for(tmp_path, monkeypatch, providers))
    try:
        rid, run_id, view, run = discover(client)
        # The first page's records stand, the failed page is recorded, and the other provider reads all of its own.
        assert run["status"] == "paused" and run["pause_reason"] == "model_call_failed", run
        rows = rows_of(view)
        assert [(r["page_number"], r["status"], r["stop_reason"]) for r in rows] == [
            (0, "completed", None), (1, "rate_limited", "page_failed")]
        assert [(r["page_number"], r["result_count"], r["stop_reason"]) for r in rows_of(view, "crossref")] == [
            (0, 10, None), (1, 2, "exhausted")]
        # A normal resume does not retry the failed page (D18).
        client.post(f"/api/runs/{run_id}/resume")
        view, run = wait(client, rid, run_id)
        assert [p for p in providers.openalex if p[0] == 20] == [(20, 20)]
        # "Search again" retries it, and the read continues from there.
        providers.recover = True
        client.post(f"/api/runs/{run_id}/retry_failed")
        view, run = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert providers.openalex == [(0, 20), (20, 20), (20, 20), (40, 20)]
    # The failed page keeps its own row; the successful retry is a second row beside it, not an edit of it (D18).
    assert [(r["page_number"], r["status"], r["stop_reason"]) for r in rows_of(view)] == [
        (0, "completed", None), (1, "rate_limited", "page_failed"), (1, "completed", None), (2, "completed", "exhausted")]
    assert view["counts"]["unread"] == 0  # the retried page is not counted twice


def test_semantic_scholar_stops_at_the_thousand_records_it_serves(tmp_path, monkeypatch):
    """The read stops at the provider's own reachable depth and says how many records it left behind."""
    monkeypatch.setattr(flow, "SW_READ_LIMIT", 2000)
    served = []

    def handler(request):
        if request.url.host != "api.semanticscholar.org":
            return httpx.Response(404)
        params = request.url.params
        offset, limit = int(params.get("offset") or 0), int(params["limit"])
        served.append((offset, limit))
        return httpx.Response(200, json={"total": 5000, "next": offset + limit, "data": [
            {"paperId": f"s2-{i}", "externalIds": {"DOI": f"10.3/s2.{i}"}, "title": f"SYNTHETIC s2 record {i}",
             "abstract": None, "year": 2024, "venue": None, "publicationTypes": None, "authors": []}
            for i in range(offset, offset + limit)]})

    monkeypatch.setattr("deixis.providers.common.SEMANTIC_SCHOLAR_PACER.interval_seconds", 0.0)
    app = app_for(tmp_path, monkeypatch, handler)
    # Scaled down from the 1,000 records Semantic Scholar really serves; the registry keeps the real number.
    monkeypatch.setitem(CONNECTORS, "semantic_scholar",
                        replace(CONNECTORS["semantic_scholar"], max_results=10, max_reachable=50))
    client = client_of(app)
    try:
        rid, _, view, run = discover(client)
    finally:
        client.__exit__(None, None, None)
    rows = rows_of(view, "semantic_scholar")
    assert len(served) == 5 and served[-1] == (40, 10)
    assert (rows[-1]["stop_reason"], rows[-1]["read_total"], rows[-1]["unread_count"]) == ("provider_cap", 50, 4950)


def test_a_first_page_with_no_records_is_exhausted_and_asks_for_no_second(tmp_path, monkeypatch):
    providers = PagedProviders(openalex_total=0)
    client = client_of(app_for(tmp_path, monkeypatch, providers))
    try:
        rid, _, view, run = discover(client)
    finally:
        client.__exit__(None, None, None)
    assert providers.openalex == [(0, 20)]
    rows = rows_of(view)
    assert [(r["status"], r["page_number"], r["stop_reason"], r["unread_count"]) for r in rows] == [
        ("zero_results", 0, "exhausted", 0)]


def test_a_provider_that_reports_no_total_leaves_the_unread_count_unknown(tmp_path, monkeypatch):
    """`unread_count` is NULL when the provider gave no total: unknown, never zero."""
    providers = PagedProviders(openalex_total=12)
    client = client_of(app_for(tmp_path, monkeypatch, _without_total(providers)))
    try:
        rid, _, view, run = discover(client)
    finally:
        client.__exit__(None, None, None)
    rows = rows_of(view)
    assert rows[-1]["stop_reason"] == "exhausted" and rows[-1]["unread_count"] is None
    assert view["counts"]["unread"] == 0  # nothing known to count, not a zero of its own


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


def test_a_paged_run_may_send_more_requests_than_max_provider_requests(tmp_path, monkeypatch):
    """The page allowance is derived from the read limit; the run does not stop with `budget_exhausted`."""
    monkeypatch.setattr(flow, "SW_READ_LIMIT", 80)
    providers = PagedProviders(openalex_total=200)
    client = client_of(app_for(tmp_path, monkeypatch, providers))
    try:
        rid, run_id, view, run = discover(client)
    finally:
        client.__exit__(None, None, None)
    assert len(providers.openalex) == 4 and run["pause_reason"] == "model_call_failed", run
    assert run["usage"]["provider_requests"] > 3  # quick effort allows three provider requests
    assert rows_of(view)[-1]["stop_reason"] == "read_limit"


def test_a_legacy_research_sends_one_request_and_stores_no_page(tmp_path, monkeypatch):
    from fakes import valid_response

    def one_provider_plan(si):
        if si["task_type"] != "search_plan":
            return valid_response(si)
        output = json.loads(valid_response(si))
        output["search_plan"].update(providers=["openalex"], concepts=[
            {"label": "packet size", "role": "core", "synonyms": ["packet size"]}])
        return json.dumps(output)

    providers = PagedProviders(openalex_total=45)
    client = client_of(app_for(tmp_path, monkeypatch, providers, workflow="legacy",
                               adapter=FakeAdapter(one_provider_plan)))
    try:
        rid, run_id, view, run = discover(client)
    finally:
        client.__exit__(None, None, None)
    assert providers.openalex == [(0, 10)]  # quick effort reads results_per_query records in one request
    rows = rows_of(view)
    assert len(rows) == 1
    assert [rows[0][k] for k in ("page_number", "read_limit", "read_total", "stop_reason", "unread_count")] == [None] * 5
    assert not [s for s in run["steps"] if ":page:" in s["operation_key"]]
    assert view["counts"]["unread"] == 0


class RateLimitedOnce(PagedProviders):
    """Every page answers 429 once and then serves: the read succeeds, and each page cost two requests."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.refused = set()

    def __call__(self, request):
        params = request.url.params
        page = (request.url.host, params.get("cursor") or params.get("offset"))
        counting = params.get("per_page") == "1" and params.get("select") == "id"
        if request.url.host in ("api.openalex.org", "api.crossref.org") and not counting and page not in self.refused:
            self.refused.add(page)
            return httpx.Response(429, text="SYNTHETIC rate limit", headers={"retry-after": "0"})
        return super().__call__(request)


def test_pages_that_each_needed_a_rate_limit_retry_do_not_exhaust_the_request_allowance(tmp_path, monkeypatch):
    """A retry is a request too. The allowance holds the retries every page may need, not one run's worth of them:
    otherwise a long read that succeeded on every page pauses with `budget_exhausted` and resuming pauses it again."""
    monkeypatch.setattr(flow, "SW_READ_LIMIT", 200)
    providers = RateLimitedOnce(openalex_total=200, crossref_total=200)
    client = client_of(app_for(tmp_path, monkeypatch, providers))
    try:
        rid, run_id, view, run = discover(client)
    finally:
        client.__exit__(None, None, None)
    assert run["pause_reason"] == "model_call_failed", run  # it read everything and stopped at screening
    assert rows_of(view)[-1]["stop_reason"] and rows_of(view, "crossref")[-1]["stop_reason"]
    assert sum(r["result_count"] for r in rows_of(view)) == 200 and sum(r["result_count"] for r in rows_of(view, "crossref")) == 200


def test_an_empty_page_that_still_carries_a_cursor_ends_the_read():
    from deixis.providers.common import SearchOutcome
    empty = SearchOutcome("zero_results", None, "SYNTHETIC", "keyless", records=[], next_cursor="SYNTHETIC-cursor")
    assert flow._stop_reason(CONNECTORS["openalex"], empty, True, 40) == "exhausted"
