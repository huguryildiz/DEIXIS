"""The years a research searches in: read from the person's own question, frozen, and sent with the requests.

Synthetic throughout — no live app, provider or model. What is guarded here is that code alone reads the date
condition, that a bound names a year and includes the year it names, that a condition finer than a year or one the
table cannot resolve stops the run instead of widening it, that the scope is frozen with the rest of the policy
before the first request opens, and that every request whose route takes the bound carries it **with** the search
while every request that cannot is recorded as unbounded rather than reading as one that lost it.
"""

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.domain.rules import TEST_EFFORT_BUDGETS
from deixis.providers import biorxiv, facade, openalex
from deixis.providers.registry import CONNECTORS, date_filter_providers
from deixis.runtime.config import Settings
from deixis.storage import db
from deixis.workflow.run import fast_path, views
from deixis.workflow.run.store import Store
from deixis.workflow.search import date_scope, fast_chain, search as fast_search, small_batch
from test_fast_path_clock import FakeClock

QUESTION = "SYNTHETIC underwater routing question since 2020"
QUERIES = [{"provider_id": "openalex", "query_text": "SYNTHETIC alpha", "origin": "model"},
           {"provider_id": "pubmed", "query_text": "SYNTHETIC gamma", "origin": "model"}]
SOURCES = ["openalex", "semantic_scholar", "pubmed"]
THIS_YEAR = 2026


# --- what the table reads, and what it refuses to read ---------------------------------------------------------

@pytest.mark.parametrize("question, bounds", [
    ("SYNTHETIC routing since 2020", (2020, None)),
    ("SYNTHETIC routing after 2019", (2019, None)),          # the named year is inside the span
    ("SYNTHETIC routing from 2018 onwards", (2018, None)),
    ("SYNTHETIC routing 2019-2024", (2019, 2024)),
    ("SYNTHETIC routing 2019 to 2024", (2019, 2024)),
    ("SYNTHETIC routing before 2015", (None, 2015)),
    ("SYNTHETIC routing up to 2015", (None, 2015)),
    # A relative phrase freezes both sides against the run's own starting year, so the span is exact and no
    # provider is asked for years that have not happened.
    ("SYNTHETIC routing in the last 5 years", (2022, 2026)),
    ("SYNTHETIC yönlendirme son 5 yıl", (2022, 2026)),
    # Every condition the question states holds, so two of them are intersected.
    ("SYNTHETIC routing between 2019 and 2024 and before 2020", (2019, 2020)),
    ("SYNTHETIC routing since 2020 and before 2024", (2020, 2024)),
    ("SYNTHETIC routing in the last 5 years and the last 2 years", (2025, 2026)),
    ("SYNTHETIC yönlendirme 2020 sonrası", (2020, None)),
    ("SYNTHETIC yönlendirme 2020'den sonra", (2020, None)),
    ("SYNTHETIC yönlendirme 2020'ten beri", (2020, None)),
    ("SYNTHETIC yönlendirme 2015'ten önce", (None, 2015)),
    ("SYNTHETIC yönlendirme 2018 öncesine", (None, 2018)),
])
def test_the_question_s_own_words_are_read_by_code_and_include_the_year_they_name(question, bounds):
    """Whichever phrasing the person used, the span is the years they named, boundary year included."""
    years = date_scope.read(question, THIS_YEAR)
    assert (years["from_year"], years["to_year"]) == bounds
    assert years["rule"] == date_scope.RULE and years["origin"] == "question"
    assert years["basis"].strip()  # the words it was read from, so the reading can be checked rather than guessed


@pytest.mark.parametrize("question", [
    "SYNTHETIC routing in 2019",                 # a question *about* a year states no condition
    "SYNTHETIC quantum switch scheduling",
    "SYNTHETIC routing with 1500 nodes and 2000 packets",
    "SYNTHETIC May 2020 workshop on routing",     # a date without a condition word is not a condition either
    "SYNTHETIC routing after 3 rounds of review",  # a number that is not a year is not one
])
def test_a_date_with_no_condition_word_is_not_a_date_condition(question):
    assert date_scope.read(question, THIS_YEAR) is None


@pytest.mark.parametrize("question, reason", [
    ("SYNTHETIC routing since January 2020", "day_precision_not_supported"),
    ("SYNTHETIC routing since 2020-03-01", "day_precision_not_supported"),
    ("SYNTHETIC routing since 2020.03.01", "day_precision_not_supported"),
    # A malformed date is finer than a year too, so it is refused rather than read as the year it starts with.
    ("SYNTHETIC routing since 2020-13-01", "day_precision_not_supported"),
    # Two conditions that leave no year stop the run instead of searching one of them.
    ("SYNTHETIC routing between 2019 and 2024 but before 2015", "bounds_cross"),
    ("SYNTHETIC routing 2019-2024 and the last 2 years", "bounds_cross"),
    # A condition left unread beside one that was read stops the run too: searching only the readable one would
    # search years the question asked to leave out.
    ("SYNTHETIC routing since 2020 and before 1200", "year_not_plausible"),
    ("SYNTHETIC yönlendirme 1200 sonrası", "year_not_plausible"),
    ("SYNTHETIC routing since 2020-130-01", "day_precision_not_supported"),
    ("SYNTHETIC routing in recent years", "no_year_named"),
    ("SYNTHETIC yönlendirme son yıllarda", "no_year_named"),
    ("SYNTHETIC routing since 1200", "year_not_plausible"),
    ("SYNTHETIC routing 2024-2019", "year_span_not_read"),
])
def test_a_condition_the_table_cannot_resolve_stops_the_run_instead_of_widening_it(question, reason):
    """A search that quietly ignored the condition, or rounded a day to a whole year, would report a scope it did
    not apply; the reason and the words it was read from travel with the refusal."""
    with pytest.raises(date_scope.Unreadable) as raised:
        date_scope.read(question, THIS_YEAR)
    assert raised.value.reason == reason and raised.value.basis.strip()


def test_the_two_openalex_routes_are_bounded_at_the_one_granularity_they_share():
    """The keyword route takes the publication dates and the semantic route only the year, so a year bound reaches
    both as the same span: the named years inside it, in each route's own syntax."""
    span = date_scope.read("SYNTHETIC routing 2019-2024", THIS_YEAR)
    assert date_scope.openalex_filter(span) == "from_publication_date:2019-01-01,to_publication_date:2024-12-31"
    assert date_scope.openalex_semantic_filter(span) == "publication_year:>2018,publication_year:<2025"
    lower = date_scope.read("SYNTHETIC routing since 2020", THIS_YEAR)
    assert date_scope.openalex_filter(lower) == "from_publication_date:2020-01-01"
    assert date_scope.openalex_semantic_filter(lower) == "publication_year:>2019"
    # A bound joins any filter the request already carries with OpenAlex's own AND, so both hold.
    assert date_scope.with_filter("cites:W1", date_scope.openalex_filter(lower)) \
        == "cites:W1,from_publication_date:2020-01-01"


def test_a_measurement_s_own_cutoff_is_a_scope_of_its_own_origin():
    """A frozen benchmark question cannot carry the condition in its words — its text is hashed — so the cutoff
    arrives with the run and is recorded as supplied, not as read from a question."""
    years = date_scope.given(None, 2016)
    assert (years["from_year"], years["to_year"], years["origin"]) == (None, 2016, "given")
    with pytest.raises(ValueError):
        date_scope.given(None, None)
    with pytest.raises(ValueError):
        date_scope.given(2020, 2010)


# --- freezing: with the policy, before the first request opens --------------------------------------------------

def _budget(effort="standard", years=None):
    budget = small_batch.freeze_budget(TEST_EFFORT_BUDGETS[effort].__dict__, effort, "off")
    budget["fast_path"] = fast_path.freeze_budget(budget, effort, date_scope=years, uniform_search=False)
    return budget


def test_the_scope_is_frozen_inside_the_policy_hash_and_read_back_from_it():
    """The run searches the years it was queued with: a policy whose hash did not cover the scope could be read
    back as a different search than the one that was paid for."""
    years = date_scope.read(QUESTION, THIS_YEAR)
    bounded, unbounded = _budget(years=years), _budget()
    assert fast_path.date_scope(bounded) == years
    assert fast_path.date_scope(unbounded) is None  # and so does every run queued before the rule
    assert bounded["fast_path"]["policy_hash"] != unbounded["fast_path"]["policy_hash"]


@pytest.mark.parametrize("years", [
    {"rule": "other_rule_v9", "from_year": 2020, "to_year": None, "basis": "x", "origin": "question"},
    {"rule": date_scope.RULE, "from_year": None, "to_year": None, "basis": "x", "origin": "question"},
    {"rule": date_scope.RULE, "from_year": "2020", "to_year": None, "basis": "x", "origin": "question"},
])
def test_a_scope_the_policy_does_not_know_is_refused_rather_than_frozen(years):
    with pytest.raises(ValueError):
        fast_path.freeze_budget(_budget(), "standard", date_scope=years)


# --- the plan: every request bounded where its route takes a bound ----------------------------------------------

def _library(tmp_path, question=QUESTION, effort="standard", years=None):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    clock = FakeClock()
    store = Store(conn, clock)
    clock.store = store
    rid = store.create_research(question, "academic", effort, list(SOURCES), "fake", "fake-model", "en")
    run = store.create_run(rid, "discovery", _budget(effort, years), None)
    store.update_run(run["id"], status="running")
    return SimpleNamespace(store=store, conn=conn, clock=clock, rid=rid, run=store.run(run["id"]))


def test_only_a_connector_that_takes_a_bound_with_the_search_is_given_one():
    """Filtering after the search cannot give back the places the out-of-scope records took on the first page, so
    a provider that takes no bound is searched unbounded and that is what the record says."""
    assert set(date_filter_providers()) == {"openalex", "biorxiv", "semantic_scholar", "pubmed"}
    # The route decides, not the provider: Semantic Scholar's bulk search takes a year range and its snippet
    # search is not known to take one, so only the route that was checked carries a bound.
    assert CONNECTORS["semantic_scholar"].date_filter is None
    assert CONNECTORS["semantic_scholar"].endpoints["bulk"].date_filter == "year_range"
    assert CONNECTORS["semantic_scholar"].endpoints["snippet"].date_filter is None
    assert CONNECTORS["scopus"].date_filter is None and CONNECTORS["ieee_xplore"].date_filter is None


def test_the_question_s_own_first_request_carries_the_frozen_bound(tmp_path):
    """It goes out before anything plans, so a bound read only at plan time would miss the one request every run
    sends."""
    lib = _library(tmp_path, years=date_scope.read(QUESTION, THIS_YEAR))
    first = fast_search.first_request_plan(lib.run, lib.store.scope(lib.rid))
    assert first["semantic"]["works_filter"] == "publication_year:>2019"
    assert first["semantic"]["endpoint"] == "semantic"
    # And the same request in the plan the protocol freezes, so the two cannot drift apart.
    plan = fast_search.build_plan(lib.store, lib.run, lib.store.scope(lib.rid), QUERIES)
    assert plan["semantic"]["works_filter"] == first["semantic"]["works_filter"]
    assert plan["date_scope"]["from_year"] == 2020


def test_the_backward_chain_and_an_unsupported_route_are_told_apart_in_the_record(tmp_path):
    """Three readings, never one: a request that carried the bound, a route that takes none, and a read by
    identifier that is no date search at all."""
    lib = _library(tmp_path, years=date_scope.read(QUESTION, THIS_YEAR))
    years = fast_path.date_scope(lib.run["budget"])
    assert fast_search.date_bound(years, QUERIES[0])["date_bound"] == "not_applied"
    assert fast_search.date_bound(years, fast_search.with_date_scope(QUERIES[0], years))["date_bound"] == "applied"
    assert fast_search.date_bound(years, {"provider_id": "crossref", "query_text": "x"})["date_bound"] \
        == "not_supported"


def test_a_run_that_bounds_no_years_sends_what_it_always_sent(tmp_path):
    lib = _library(tmp_path, question="SYNTHETIC routing question", years=None)
    plan = fast_search.build_plan(lib.store, lib.run, lib.store.scope(lib.rid), QUERIES)
    assert "works_filter" not in plan["semantic"] and "date_scope" not in plan
    assert all("date_bound" not in request for request in fast_search.sent_plan({"fast_path_search": plan,
                                                                                "compiled_queries": QUERIES}))


def test_the_keyword_route_is_bounded_by_dates_and_the_semantic_one_by_the_year(tmp_path):
    lib = _library(tmp_path, years=date_scope.read("SYNTHETIC routing 2019-2024", THIS_YEAR))
    plan = fast_search.build_plan(lib.store, lib.run, lib.store.scope(lib.rid), QUERIES)
    (keyword,) = plan["keywords"]
    assert keyword["query"]["works_filter"] == "from_publication_date:2019-01-01,to_publication_date:2024-12-31"
    assert plan["semantic"]["works_filter"] == "publication_year:>2018,publication_year:<2025"


def test_a_bound_joins_the_filter_a_query_already_carries(tmp_path):
    """A statement research's author filter and the date bound both hold: a comma is OpenAlex's own AND."""
    lib = _library(tmp_path, years=date_scope.read(QUESTION, THIS_YEAR))
    author = [{"provider_id": "openalex", "query_text": "SYNTHETIC alpha", "origin": "author",
               "works_filter": "authorships.author.id:A1"}]
    plan = fast_search.build_plan(lib.store, lib.run, lib.store.scope(lib.rid), author)
    (keyword,) = plan["keywords"]
    assert keyword["query"]["works_filter"] == "authorships.author.id:A1,from_publication_date:2020-01-01"


def test_every_planned_request_says_how_it_stood_to_the_bound(tmp_path):
    """So nothing reads a bound back that never left with one, and a provider that takes none is named."""
    lib = _library(tmp_path, effort="detailed", years=date_scope.read(QUESTION, THIS_YEAR))
    queries = [*QUERIES, {"provider_id": "semantic_scholar", "query_text": "SYNTHETIC delta", "origin": "model",
                          "endpoint": "bulk"}]
    plan = fast_search.build_plan(lib.store, lib.run, lib.store.scope(lib.rid), queries)
    sent = fast_search.sent_plan({"fast_path_search": plan, "compiled_queries": queries})
    by_arm = {request["arm"]: request for request in sent}
    assert by_arm["semantic"]["date_bound"] == "applied"
    assert by_arm["keyword"]["date_bound"] == "applied"
    # Semantic Scholar's bulk route takes a year range of its own, so the bulk request carries the same scope.
    assert by_arm["s2_bulk"]["date_bound"] == "applied" and by_arm["s2_bulk"]["year_range"] == "2020-2200"
    # The keyword row carries the filter it was really sent with, not the compiled query's own.
    assert by_arm["keyword"]["works_filter"] == "from_publication_date:2020-01-01"


def test_the_run_view_says_which_years_were_searched_and_what_could_not_carry_the_bound(tmp_path):
    lib = _library(tmp_path, effort="detailed", years=date_scope.read(QUESTION, THIS_YEAR))
    queries = [*QUERIES, {"provider_id": "semantic_scholar", "query_text": "SYNTHETIC delta", "origin": "model",
                          "endpoint": "bulk"}]
    plan = fast_search.build_plan(lib.store, lib.run, lib.store.scope(lib.rid), queries)
    view = views.date_scope_view(lib.store, lib.run, {"fast_path_search": plan, "compiled_queries": queries})
    assert (view["from_year"], view["to_year"], view["origin"]) == (2020, None, "question")
    assert view["planned"]["applied"] >= 3
    # Nothing was searched yet, so the record counts are all zero rather than absent: a reader can tell "none
    # found" from "not recorded".
    assert view["records"] == dict.fromkeys(date_scope.CLASSES, 0) and view["set_aside"] == 0
    # The words the scope was read from are shown, so a person can check the reading against their own question.
    assert view["basis"] == "since 2020"


# --- what really goes out ---------------------------------------------------------------------------------------

def test_the_semantic_route_sends_the_year_bound_as_its_own_filter():
    """OpenAlex's semantic-search help page (read 10 Nov 2026) lists `publication_year` among the filters the route
    works with, so the bound travels on the request rather than being applied to its answer."""
    requests = []

    async def execute():
        def transport(request):
            requests.append(request)
            return httpx.Response(200, json={"meta": {"count": 0}, "results": []})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            return await facade.dispatch_search("openalex", http, "SYNTHETIC question", 50, None, None,
                                                endpoint="semantic", works_filter="publication_year:>2019")
    asyncio.run(execute())
    assert requests[0].url.params["filter"] == "publication_year:>2019"


def test_the_forward_chain_is_bounded_and_the_backward_one_is_recorded_as_no_date_search():
    """Asking which works cite a seed is a search of the literature; asking for the records of the references a
    seed lists is a read by identifier, so it carries no bound and its step says which it was."""
    years = date_scope.read(QUESTION, THIS_YEAR)
    policy = {"backward_page_size": 2, "backward_requests": 1, "forward_requests": 1, "forward_page_size": 10,
              "date_scope": years}
    seeds = [{"openalex_id": "W1", "source_version_id": "sv1", "references": ["W9", "W8"]}]
    plan = fast_chain.request_plan(seeds, policy, held=())
    forward = next(spec for spec in plan["requests"] if spec["direction"] == "forward")
    backward = next(spec for spec in plan["requests"] if spec["direction"] == "backward")
    assert forward["works_filter"] == "from_publication_date:2020-01-01" and forward["date_bound"] == "applied"
    assert "works_filter" not in backward and backward["date_bound"] == "not_a_date_search"
    # A run that bounds no years records neither, so an older run's steps read exactly as they did.
    unbounded = fast_chain.request_plan(seeds, policy | {"date_scope": None}, held=())
    assert all("date_bound" not in spec for spec in unbounded["requests"])


def test_the_citing_route_sends_the_bound_beside_the_filter_that_selects_the_citing_works():
    requests = []

    async def execute():
        def transport(request):
            requests.append(request)
            return httpx.Response(200, json={"meta": {"count": 0}, "results": []})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            return await openalex.citing_works(http, "W1", "*", 10, None, None,
                                               works_filter="from_publication_date:2020-01-01")
    asyncio.run(execute())
    assert requests[0].url.params["filter"] == "cites:W1,from_publication_date:2020-01-01"


def test_a_source_whose_route_takes_no_bound_is_sent_unbounded(tmp_path):
    """Its records are searched without the years, which is why the request's own record says so."""
    lib = _library(tmp_path, years=date_scope.read(QUESTION, THIS_YEAR))
    years = fast_path.date_scope(lib.run["budget"])
    scopus = {"provider_id": "scopus", "query_text": "SYNTHETIC epsilon", "origin": "model"}
    assert fast_search.with_date_scope(scopus, years) == scopus
    assert fast_search.date_bound(years, scopus) == {"date_bound": "not_supported"}
    # And a route that does take one is labelled from what the request really carries, not from its provider.
    bounded = fast_search.with_date_scope(QUERIES[1], years)
    assert bounded["year_range"] == "2020-2200" and fast_search.date_bound(years, bounded)["date_bound"] == "applied"
    assert fast_search.date_bound(years, QUERIES[1])["date_bound"] == "not_applied"


def test_a_biorxiv_search_sends_the_bound_beside_the_filter_that_selects_the_repository():
    """bioRxiv is read through OpenAlex, so its own filter and the date bound are ANDed into one filter value."""
    requests = []

    async def execute():
        def transport(request):
            requests.append(request)
            return httpx.Response(200, json={"meta": {"count": 0}, "results": []})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            return await biorxiv.search(http, "SYNTHETIC query", 10,
                                        works_filter="from_publication_date:2020-01-01")
    asyncio.run(execute())
    sent = requests[0].url.params["filter"]
    assert biorxiv.WORKS_FILTER in sent and "from_publication_date:2020-01-01" in sent


# --- the API: what a run may be asked to search -----------------------------------------------------------------

def _app(tmp_path):
    from fakes import FakeAdapter
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, model_concurrency=1, fulltext_fetch="off"),
                      adapters={"fake": FakeAdapter()}, extra_hosts=("testserver",), trusted_clients=("testclient",))


def _session(client):
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    return client


def _research(client, question):
    body = {"question": question, "model_connection": "fake", "requested_model": "fake-model", "effort": "quick"}
    response = client.post("/api/researches", json=body)
    assert response.status_code == 201, response.text
    return response.json()["research"]["id"]


def test_a_question_whose_condition_cannot_be_read_never_starts_a_run(tmp_path):
    """The decision is made at run creation: a run that had started would already have sent its first request."""
    with TestClient(_app(tmp_path)) as client:
        _session(client)
        rid = _research(client, "SYNTHETIC routing since January 2020")
        response = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"})
        assert response.status_code == 422 and "day_precision_not_supported" in response.text


def test_a_measurement_s_cutoff_arrives_with_the_run_and_is_frozen_into_it(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        _session(client)
        rid = _research(client, "SYNTHETIC routing question")
        response = client.post(f"/api/researches/{rid}/runs",
                               json={"kind": "discovery", "date_scope": {"to_year": 2016}})
        assert response.status_code == 202, response.text
        run = client.get(f"/api/researches/{rid}").json()["runs"][0]
        assert run["date_scope"]["to_year"] == 2016 and run["date_scope"]["origin"] == "given"


def test_a_scope_is_named_only_for_a_search_run(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        _session(client)
        rid = _research(client, "SYNTHETIC routing question")
        response = client.post(f"/api/researches/{rid}/runs",
                               json={"kind": "answer", "date_scope": {"from_year": 2020}})
        assert response.status_code == 422


def test_two_runs_of_one_question_cannot_search_different_spans(tmp_path):
    """The candidate pool is read per research and scope revision, so a second run with another bound would mix
    records nothing searched for with records it did: the question is asked again instead."""
    with TestClient(_app(tmp_path)) as client:
        _session(client)
        rid = _research(client, "SYNTHETIC routing question")
        first = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery", "date_scope": {"to_year": 2016}})
        assert first.status_code == 202, first.text
        again = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery", "date_scope": {"to_year": 2018}})
        assert again.status_code == 409


# --- the other routes that take a bound of their own ------------------------------------------------------------

def test_the_bulk_route_sends_the_year_range_it_asks_for():
    """Semantic Scholar answers "'year' must be of the form <min>-<max>" to anything else, so both sides go."""
    requests = []

    async def execute():
        def transport(request):
            requests.append(request)
            return httpx.Response(200, json={"total": 0, "data": []})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            return await facade.dispatch_search("semantic_scholar", http, "SYNTHETIC query", 10, None, None,
                                                endpoint="bulk", year_range="2020-2200")
    asyncio.run(execute())
    assert requests[0].url.params["year"] == "2020-2200"


def test_the_relevance_route_refuses_a_bound_rather_than_dropping_it():
    """A route nobody has checked takes no bound, and a caller that sends one anyway is a mistake, not a search
    that silently went out unbounded."""
    from deixis.providers import semantic_scholar

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))) as http:
            return await semantic_scholar.search(http, "SYNTHETIC", 10, year_range="2020-2200")
    with pytest.raises(ValueError):
        asyncio.run(execute())


def test_pubmed_sends_its_own_date_range_and_leaves_the_query_text_alone():
    """Written into the query, the bound would change the text the plan froze and the record read back against it;
    and ESearch ignores a `mindate` with no `maxdate`, so both are sent."""
    requests = []

    async def execute():
        def transport(request):
            requests.append(request)
            return httpx.Response(200, json={"esearchresult": {"count": "0", "idlist": []}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            return await facade.dispatch_search("pubmed", http, "SYNTHETIC query", 10, None, None,
                                                year_range="2020-2200")
    asyncio.run(execute())
    params = requests[0].url.params
    assert params["datetype"] == "pdat" and params["mindate"] == "2020" and params["maxdate"] == "2200"
    assert params["term"] == "SYNTHETIC query"


# --- the other searches of the same question --------------------------------------------------------------------

def test_the_years_a_question_is_bounded_to_are_read_back_from_its_own_runs(tmp_path):
    """A later search of the same question — a follow-up, a citation-map walk, a watch — reads the span from the
    runs that searched it, so one question revision has one span."""
    lib = _library(tmp_path, years=date_scope.read(QUESTION, THIS_YEAR))
    assert fast_path.scope_years(lib.store, lib.rid, 1)["from_year"] == 2020
    unbounded = _library(tmp_path / "b", question="SYNTHETIC routing question", years=None)
    assert fast_path.scope_years(unbounded.store, unbounded.rid, 1) is None


def test_a_follow_up_search_stays_inside_the_question_s_years():
    """Its records join the same candidate pool, so a request outside those years would add work the question
    never asked for."""
    from deixis.workflow.search import followup_search
    blocks = {"setting": [{"term": "SYNTHETIC underwater"}], "task": [{"term": "SYNTHETIC routing"}],
              "setting_backup": [], "task_backup": []}
    years = date_scope.read(QUESTION, THIS_YEAR)
    plan = followup_search.request_plan("SYNTHETIC follow-up question", blocks, ["openalex"], years)
    semantic = next(r for r in plan["requests"] if r["origin"] == "semantic")
    assert semantic["works_filter"] == "publication_year:>2019"
    assert all(r["works_filter"] == "from_publication_date:2020-01-01"
               for r in plan["requests"] if r["origin"] == "keyword")
    # And a question that bounds no years sends what it always sent.
    plain = followup_search.request_plan("SYNTHETIC follow-up question", blocks, ["openalex"], None)
    assert all("works_filter" not in r for r in plain["requests"])


# --- which records a bounded run may rank, screen and read ------------------------------------------------------

@pytest.mark.parametrize("year, expected", [
    (2020, date_scope.IN_SPAN),      # the year the bound names is inside it
    (2026, date_scope.IN_SPAN),
    (2019, date_scope.BEFORE_SPAN),
    (1900, date_scope.BEFORE_SPAN),
    (None, date_scope.YEAR_UNKNOWN),
])
def test_a_record_is_judged_by_its_own_year_and_an_unknown_year_is_outside_the_bound(year, expected):
    """A provider that applies the bound itself answers the same way — OpenAlex's `publication_year:>2019` returns
    no work without a year — so a record whose year nobody recorded is outside a bounded span here too, and the two
    arms of a comparison are read under one condition."""
    scope = date_scope.read(QUESTION, THIS_YEAR)
    assert date_scope.year_class(scope, year) == expected
    assert date_scope.eligible(scope, year) is (expected == date_scope.IN_SPAN)


def test_an_upper_bound_puts_a_later_year_after_the_span():
    scope = date_scope.given(None, 2015)
    assert date_scope.year_class(scope, 2016) == date_scope.AFTER_SPAN
    assert date_scope.year_class(scope, 2015) == date_scope.IN_SPAN
    # A run that bounds no years judges nothing: every record is in its span.
    assert all(date_scope.year_class(None, year) == date_scope.IN_SPAN for year in (None, 1900, 2030))


def _record(number, year, title=None):
    from deixis.providers.common import ProviderRecord
    return ProviderRecord(
        provider_record_id=f"W{number}", title=title or f"SYNTHETIC record {number}", authors=[], year=year,
        venue=None, publication_type=None, doi=f"10.1/synth.{number}", landing_url=None, oa_pdf_url=None,
        oa_pdf_version=None, version_label="publishedVersion", abstract="SYNTHETIC abstract.",
        abstract_origin="provider", identifiers={}, raw={}, references=None, merge_by_doi=True)


def _search(lib, records, key="search:0", provider="openalex", date_bound="not_supported"):
    """Write one answered request of this run, as the flow writes one."""
    step = lib.store.step(lib.run["id"], key, f"provider_search:{provider}")
    lib.store.record_search(
        dict(research_id=lib.rid, run_id=lib.run["id"], step_id=step["id"],
             scope_revision=lib.run["scope_revision"], provider=provider,
             query_text="SYNTHETIC query", request_description="GET SYNTHETIC", access_mode="keyless",
             status="completed", delivery_class=None, result_count=len(records), provider_total=len(records),
             page_limit=200, error_json=None, raw_payload_path=None, date_bound=date_bound),
        provider, records, None, step["id"], "succeeded", step_output={"status": "completed"})
    return step


def test_a_record_outside_the_years_joins_the_research_and_is_not_a_candidate_of_it(tmp_path):
    """An unbounded route answers with every year, so the condition is applied to what it brought. The record is
    kept — nothing the question paid for is thrown away — but it takes no place in this revision's candidates, so
    no reader of them ranks, screens or reads it."""
    lib = _library(tmp_path, years=date_scope.read(QUESTION, THIS_YEAR))
    _search(lib, [_record(1, 2021), _record(2, 2015), _record(3, None)])
    candidates = {c["source_version_id"] for c in lib.store.candidates(lib.rid, 1)}
    inside, before, unknown = (lib.store.find_source_by_identifier("openalex", f"W{i}") for i in (1, 2, 3))
    assert inside in candidates and before not in candidates and unknown not in candidates
    # Still records of the research, with their own membership: the person can find them in Sources.
    members = {row[0] for row in lib.conn.execute(
        "SELECT source_version_id FROM corpus_memberships WHERE research_id = ? AND removed_at IS NULL", (lib.rid,))}
    assert {inside, before, unknown} <= members
    # And no hit row for a record that is not a candidate, so the query lists the window is chosen from hold none.
    hits = {row[0] for row in lib.conn.execute(
        "SELECT source_version_id FROM candidate_hits WHERE research_id = ?", (lib.rid,))}
    assert hits == {inside}


def test_the_run_writes_down_what_its_years_decided_about_each_record(tmp_path):
    """Written in the request's own transaction rather than worked out later: a reading of the library afterwards
    would judge these records against the years they store then, and an earlier run's decisions must not move."""
    lib = _library(tmp_path, years=date_scope.read(QUESTION, THIS_YEAR))
    _search(lib, [_record(1, 2021), _record(2, 2015), _record(3, None)])
    rows = {row["source_version_id"]: row for row in lib.store.date_scope_admissions(lib.rid, 1)}
    classes = {row["year_class"] for row in rows.values()}
    assert classes == {date_scope.IN_SPAN, date_scope.BEFORE_SPAN, date_scope.YEAR_UNKNOWN}
    assert sum(row["year_eligible"] for row in rows.values()) == 1
    assert {row["date_bound"] for row in rows.values()} == {"not_supported"}  # the route took no bound
    assert all(row["sent_year"] is None for row in rows.values())  # no provider disagreed with a stored year
    assert lib.store.set_aside_for_year(lib.rid, 1) == {
        lib.store.find_source_by_identifier("openalex", f"W{i}") for i in (2, 3)}
    # A run that bounds no years writes none of this and sets nothing aside.
    plain = _library(tmp_path / "b", question="SYNTHETIC routing question", years=None)
    _search(plain, [_record(1, 2015)], date_bound=None)
    assert plain.store.date_scope_admissions(plain.rid, 1) == []
    assert plain.store.set_aside_for_year(plain.rid, 1) == set()


def test_a_record_set_aside_for_its_year_is_not_ranked_and_not_offered_for_reading(tmp_path):
    """The bound must not come back in through the work: the version map every signal, batch item, abstract read
    and full-text read is built from leaves it out."""
    from deixis.workflow.search import ranking
    lib = _library(tmp_path, years=date_scope.read(QUESTION, THIS_YEAR))
    _search(lib, [_record(1, 2021), _record(2, 2015)])
    inside, before = (lib.store.find_source_by_identifier("openalex", f"W{i}") for i in (1, 2))
    versions, _, pool = ranking.pool_rows(lib.store, lib.rid, 1)
    assert inside in versions and before not in versions
    assert [row["id"] for row in pool] == [inside]
    # Without a question revision the map is every record, because a caller comparing it against a frozen map has
    # to see them all to tell whether a source changed.
    assert before in ranking._versions(lib.store, lib.rid)


def test_a_source_the_person_added_is_never_set_aside_for_its_year(tmp_path):
    """The person's own authority outranks the run's years: a record no request judged is not in the set aside, so
    an upload, a seed PDF and anything they included stay where they are."""
    from deixis.workflow.search import ranking
    lib = _library(tmp_path, years=date_scope.read(QUESTION, THIS_YEAR))
    _search(lib, [_record(1, 2021)])
    their_own, _ = lib.store.upsert_provider_source("openalex", _record(9, 1999), None)
    lib.store.add_to_corpus(lib.rid, their_own, "user_upload", selection_state="included", selection_origin="user")
    assert their_own not in lib.store.set_aside_for_year(lib.rid, 1)
    assert their_own in ranking._versions(lib.store, lib.rid, 1)


def test_a_record_one_request_admitted_is_not_taken_back_by_another(tmp_path):
    """A second provider reporting the same record is not a second chance to drop it: once a request made it a
    candidate, the pool it was ranked in is the pool the run froze."""
    lib = _library(tmp_path, years=date_scope.read(QUESTION, THIS_YEAR))
    _search(lib, [_record(1, 2021)])
    # The same work from another route, whose own answer carries no year; the version keeps the year it stores.
    _search(lib, [_record(1, None)], key="search:1", provider="semantic_scholar")
    svid = lib.store.find_source_by_identifier("openalex", "W1")
    assert svid not in lib.store.set_aside_for_year(lib.rid, 1)
    rows = [row for row in lib.store.date_scope_admissions(lib.rid, 1) if row["source_version_id"] == svid]
    # Both requests' decisions are kept, and the one that disagreed with the stored year says so.
    assert {row["year_class"] for row in rows} == {date_scope.IN_SPAN}
    assert len(rows) == 2


def test_the_run_view_counts_the_records_its_years_set_aside(tmp_path):
    """The cost of bounding a search after the fact instead of in the request, per provider: a route that took the
    bound should set nothing aside, and one that could not shows what its unbounded pages brought."""
    lib = _library(tmp_path, years=date_scope.read(QUESTION, THIS_YEAR))
    _search(lib, [_record(1, 2021), _record(2, 2015), _record(3, None)])
    view = views.date_scope_view(lib.store, lib.run, None)
    assert view["records"] == {date_scope.IN_SPAN: 1, date_scope.BEFORE_SPAN: 1, date_scope.AFTER_SPAN: 0,
                               date_scope.YEAR_UNKNOWN: 1}
    assert view["outside_span"] == 2 and view["set_aside"] == 2 and view["year_disagreed"] == 0
    assert view["by_provider"]["openalex"] == {"records": 3, "outside_span": 2, "set_aside": 2,
                                                "date_bound": ["not_supported"]}


def test_a_set_aside_version_is_not_read_and_is_not_the_answer_s_version(tmp_path):
    """One work, two versions: the published record inside the span and the preprint outside it. The reading, the
    PDF fetch and the answer all work through the work's versions, so a version the years exclude would come back
    into the evidence through its work."""
    lib = _library(tmp_path, years=date_scope.read(QUESTION, THIS_YEAR))
    _search(lib, [_record(1, 2021), _record(2, 2015)])
    head = lib.store.find_source_by_identifier("openalex", "W1")
    other = lib.store.find_source_by_identifier("openalex", "W2")
    # Setup, not the subject: the two records are put in one work the way the identity rule would, after both
    # have been judged by the search — the published record inside the span, the preprint outside it.
    lib.conn.execute("UPDATE source_versions SET work_id = ?, version_label = 'submittedVersion' WHERE id = ?",
                     (lib.store.source(head)["work_id"], other))
    # Not offered for reading, and not a version the answer may read.
    assert other not in lib.store.work_versions(lib.rid, head)
    assert lib.store.answer_version(lib.rid, head) == head
    assert lib.store.answer_versions(lib.rid)[head] == head
    # Removing the work still takes it: a version left behind would belong to a work nobody holds.
    assert other in lib.store.work_versions(lib.rid, head, every=True)


def test_a_reply_after_the_cutoff_does_not_rescue_a_record_set_aside_for_its_year(tmp_path):
    """A late reply admits nothing, so its own year verdict is recorded and changes no list: otherwise a late arm
    could put a version back into the signals of a list the cutoff had already frozen."""
    lib = _library(tmp_path, years=date_scope.read(QUESTION, THIS_YEAR))
    _search(lib, [_record(1, None)])                      # no year: set aside
    svid = lib.store.find_source_by_identifier("openalex", "W1")
    assert svid in lib.store.set_aside_for_year(lib.rid, 1)
    step = lib.store.step(lib.run["id"], "search:late", "provider_search:openalex")
    lib.store.record_search(
        dict(research_id=lib.rid, run_id=lib.run["id"], step_id=step["id"], scope_revision=1, provider="openalex",
             query_text="SYNTHETIC late", request_description="GET SYNTHETIC", access_mode="keyless",
             status="completed", delivery_class=None, result_count=1, provider_total=1, page_limit=200,
             error_json=None, raw_payload_path=None, date_bound="applied"),
        "openalex", [_record(1, 2021)], None, step["id"], "succeeded",
        step_output={"status": "completed", "fast_path_request": {"late": True, "class": 1, "request_index": 1}})
    assert svid in lib.store.set_aside_for_year(lib.rid, 1)
    late = [row for row in lib.store.date_scope_admissions(lib.rid, 1) if row["late"]]
    assert len(late) == 1 and late[0]["year_eligible"] == 1  # its verdict is on the record, and changes nothing


def test_a_record_the_person_includes_is_no_longer_set_aside(tmp_path):
    """Their choice outranks the run's years: once they include a record the search set aside, it ranks and is
    read like any other."""
    from deixis.workflow.search import ranking
    lib = _library(tmp_path, years=date_scope.read(QUESTION, THIS_YEAR))
    _search(lib, [_record(1, 2021), _record(2, 2015)])
    before = lib.store.find_source_by_identifier("openalex", "W2")
    assert before in lib.store.set_aside_for_year(lib.rid, 1)
    lib.conn.execute("UPDATE selections SET state = 'included', origin = 'user' WHERE source_version_id = ?",
                     (before,))
    assert lib.store.set_aside_for_year(lib.rid, 1) == set()
    assert before in ranking._versions(lib.store, lib.rid, 1)
    # And it heads its own work, so it reaches the lists that are read by work: without that the record would be
    # included and still invisible, because a record the years kept out of the candidates heads nothing.
    work_id = lib.store.source(before)["work_id"]
    assert lib.store.work_heads(lib.rid)[work_id] == before
    assert work_id in {lib.store.source(svid)["work_id"] for svid in lib.store.included_works(lib.rid)}
    assert lib.store.answer_versions(lib.rid)[before] == before


def test_an_earlier_wider_revision_s_record_does_not_head_the_work_this_question_asked_about(tmp_path):
    """The run that bounds its years leaves the earlier revision's out-of-span record out of its candidates, so
    that record must not head the work either: the pool is read by head, and the work would drop out of it."""
    from deixis.workflow.search import ranking
    lib = _library(tmp_path, question="SYNTHETIC routing question", years=None)
    _search(lib, [_record(1, 2015)], date_bound=None)            # revision 1 asked about every year
    published = lib.store.find_source_by_identifier("openalex", "W1")
    # The same question asked again, now bounded, and a run of its own.
    lib.store.update_run(lib.run["id"], status="completed")
    revision = lib.store.revise_scope(lib.rid, lib.store.research(lib.rid)["version"], QUESTION, None)
    assert revision == 2
    run = lib.store.create_run(lib.rid, "discovery", _budget("standard", date_scope.read(QUESTION, THIS_YEAR)), None)
    lib.store.update_run(run["id"], status="running")
    lib.run = lib.store.run(run["id"])
    preprint = _record(2, 2021)
    _search(lib, [preprint], key="search:1")
    inside = lib.store.find_source_by_identifier("openalex", "W2")
    # Two versions of one work, as the identity rule would leave them.
    lib.conn.execute("UPDATE source_versions SET work_id = ? WHERE id = ?",
                     (lib.store.source(published)["work_id"], inside))
    work_id = lib.store.source(published)["work_id"]
    assert lib.store.work_heads(lib.rid)[work_id] == inside
    _, _, pool = ranking.pool_rows(lib.store, lib.rid, 2)
    assert [row["id"] for row in pool] == [inside]


def test_the_person_s_own_inclusion_heads_the_work_even_beside_another_version(tmp_path):
    """Their choice outranks code, including the published-record-first rule: otherwise the version they chose
    would be included and still never read, because the lists that are read go by the work's head."""
    lib = _library(tmp_path, years=date_scope.read(QUESTION, THIS_YEAR))
    _search(lib, [_record(1, 2021), _record(2, 2015)])
    published, before = (lib.store.find_source_by_identifier("openalex", f"W{i}") for i in (1, 2))
    lib.conn.execute("UPDATE source_versions SET work_id = ?, version_label = 'submittedVersion', doi = NULL"
                     " WHERE id = ?", (lib.store.source(published)["work_id"], before))
    work_id = lib.store.source(published)["work_id"]
    assert lib.store.work_heads(lib.rid)[work_id] == published     # the published record heads it to begin with
    lib.conn.execute("UPDATE selections SET state = 'included', origin = 'user' WHERE source_version_id = ?",
                     (before,))
    assert lib.store.work_heads(lib.rid)[work_id] == before
    assert lib.store.included_works(lib.rid) == [before]
