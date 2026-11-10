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
    budget["fast_path"] = fast_path.freeze_budget(budget, effort, date_scope=years)
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
    view = views.date_scope_view(lib.run, {"fast_path_search": plan, "compiled_queries": queries})
    assert (view["from_year"], view["to_year"], view["origin"]) == (2020, None, "question")
    assert view["planned"]["applied"] >= 3
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
