"""Source routing before the approval card: one field distribution request, a table of OpenAlex fields, and the
queries compiled for the sources it chooses (slice 14, D93).

Distributions, questions and records are SYNTHETIC and from more than one field; every transport is mocked. Passing
shows which sources the rule chooses for a given distribution and that the run asks for it once — not that the share
or the table are right for any real question (neither was measured), nor what a real distribution looks like.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from deixis.domain.rules import ROUTE_SHARE
from deixis.providers import openalex as openalex_module
from deixis.workflow import routing
from deixis.workflow.flow import ResearchFlow
import test_expansion_flow as expansion_flow
from test_approval_flow import app_for as approval_app, approve, client_of as approval_client
from test_search_query import proposal
from test_vocabulary_flow import QUESTION, WORK, wait

SCOPE = ["openalex", "semantic_scholar", "arxiv", "biorxiv", "pubmed", "ieee_xplore"]


def distribution(**counts):
    """A SYNTHETIC field distribution: display name (underscores for spaces) → count; the total is their sum."""
    rows = [{"field": name.replace("_", " "), "key": f"https://openalex.org/fields/{i}", "count": n}
            for i, (name, n) in enumerate(counts.items())]
    return {"total": sum(counts.values()), "fields": rows}


@pytest.fixture
def ieee_configured(monkeypatch):
    monkeypatch.setenv("IEEE_API_KEY", "SYNTHETIC-key")


def chosen(record):
    return [row["provider_id"] for row in record["chosen"]]


def reasons(record):
    return {row["provider_id"]: row["reason"] for row in record["left_out"]}


# ---- the rule -----------------------------------------------------------------------------------------------------


def test_an_engineering_distribution_routes_to_ieee_and_arxiv(ieee_configured):
    record = routing.route(SCOPE, "q", distribution(Computer_Science=70, Engineering=25, Medicine=5), "read")
    assert record["providers"] == ["openalex", "semantic_scholar", "arxiv", "ieee_xplore"]
    assert reasons(record)["pubmed"] == "share_below" and reasons(record)["biorxiv"] == "share_below"
    ieee = next(row for row in record["chosen"] if row["provider_id"] == "ieee_xplore")
    assert ieee["share"] == 0.95 and ieee["fields"] == ["Computer Science", "Engineering"]


def test_a_clinical_distribution_routes_to_pubmed_and_biorxiv(ieee_configured):
    record = routing.route(SCOPE, "q", distribution(Medicine=80, Nursing=6, Immunology_and_Microbiology=4,
                                                      Engineering=10), "read")
    assert record["providers"] == ["openalex", "semantic_scholar", "biorxiv", "pubmed"]
    assert {provider: reason for provider, reason in reasons(record).items() if provider in ("arxiv", "ieee_xplore")} \
        == {"arxiv": "share_below", "ieee_xplore": "share_below"}


def test_a_mixture_near_the_share_is_decided_by_the_share_alone(ieee_configured):
    # 26 % life science, 24 % Computer Science, 1 % Physics: arXiv's fields hold exactly the share, IEEE's just below.
    record = routing.route(SCOPE, "q", distribution(Medicine=26, Computer_Science=24, Physics_and_Astronomy=1,
                                                      Social_Sciences=49), "read")
    shares = {row["provider_id"]: row["share"] for row in record["chosen"] + record["left_out"] if "share" in row}
    assert shares == {"arxiv": 0.25, "biorxiv": 0.26, "pubmed": 0.26, "ieee_xplore": 0.24}
    assert ROUTE_SHARE == 0.25
    assert chosen(record) == ["openalex", "semantic_scholar", "arxiv", "biorxiv", "pubmed"]
    assert reasons(record)["ieee_xplore"] == "share_below"


def test_a_source_outside_the_scope_or_without_its_key_is_never_chosen(monkeypatch):
    monkeypatch.delenv("IEEE_API_KEY", raising=False)  # another test's credential lookup may have set it
    record = routing.route(["openalex", "semantic_scholar", "arxiv", "ieee_xplore"], "q",
                           distribution(Medicine=90, Computer_Science=10), "read")
    left = reasons(record)
    assert left["pubmed"] == "not_in_scope" and left["biorxiv"] == "not_in_scope"
    assert left["ieee_xplore"] == "not_configured"  # no IEEE key in tests
    # CORE, SerpApi and Scopus are searched by a legacy research only.
    assert left["core"] == left["serpapi"] == left["scopus"] == "not_in_sw_search"
    assert record["providers"] == ["openalex", "semantic_scholar"]


def test_an_unread_distribution_routes_to_every_usable_domain_source_and_says_so(ieee_configured):
    record = routing.route(SCOPE, "q", None, "unavailable")
    assert record["providers"] == ["openalex", "semantic_scholar", "arxiv", "biorxiv", "pubmed", "ieee_xplore"]
    assert {row["reason"] for row in record["chosen"][2:]} == {"distribution_unavailable"}
    assert record["total"] is None and record["fields"] == []


def test_a_read_distribution_with_no_records_or_no_fields_is_taken_as_unread(ieee_configured):
    """Review of slice 14 (2026-09-23): with no shares to route by, every domain source was left out."""
    for empty in ({"total": 0, "fields": []}, {"total": 40, "fields": []}):
        record = routing.route(SCOPE, "q", empty, "read")
        assert record["status"] == "unavailable"
        assert record["providers"] == ["openalex", "semantic_scholar", "arxiv", "biorxiv", "pubmed", "ieee_xplore"]


def test_the_unrounded_share_is_compared_with_the_threshold():
    # 6,249 of 25,000 is 24.996 %: shown as 0.25, below the share all the same (review of slice 14).
    record = routing.route(SCOPE, "q", distribution(Computer_Science=6249, Social_Sciences=18751), "read")
    arxiv = next(row for row in record["left_out"] if row["provider_id"] == "arxiv")
    assert arxiv["reason"] == "share_below" and arxiv["share"] == 0.25


def test_with_no_usable_domain_source_nothing_needs_to_be_asked(monkeypatch):
    monkeypatch.delenv("IEEE_API_KEY", raising=False)
    assert not routing.needs_distribution(["openalex", "semantic_scholar", "ieee_xplore"])  # IEEE has no key
    assert routing.needs_distribution(["openalex", "pubmed"])


def test_the_gate_query_is_each_block_s_searched_forms_in_one_or_group():
    vocabulary = {"terms": [
        {"phrase": "rail networks", "block": "setting", "root": "rail", "in_query": "root", "dropped": None},
        {"phrase": "tram lines", "block": "setting", "root": "tram", "in_query": "phrase", "dropped": None},
        {"phrase": "timetabling", "block": "task", "root": "timetabling", "in_query": "root", "dropped": None},
        {"phrase": "SYNTHETIC gone", "block": "task", "root": "gone", "in_query": "root", "dropped": "zero_results"}]}
    assert routing.gate_query(vocabulary) == '(rail OR "tram lines") AND (timetabling)'


def test_quick_s_three_queries_search_no_domain_source_under_the_routed_order():
    built = proposal()  # a model-written query with the code's beside it (D92)
    _, queries = ResearchFlow._compiled(None, built, ["openalex", "semantic_scholar", "arxiv", "pubmed"],
                                        {"max_provider_requests": 3})
    assert [(q["provider_id"], q["origin"]) for q in queries] == [
        ("openalex", "model"), ("openalex", "code"), ("semantic_scholar", "model")]
    _, eight = ResearchFlow._compiled(None, built, ["openalex", "semantic_scholar", "arxiv", "pubmed"],
                                      {"max_provider_requests": 8})
    assert [q["provider_id"] for q in eight] == ["openalex"] * 2 + ["semantic_scholar"] * 2 + ["arxiv"] * 2 + ["pubmed"] * 2
    assert all(q.get("endpoint") == "bulk" for q in eight if q["provider_id"] == "semantic_scholar")


@pytest.mark.field_distribution
def test_the_distribution_request_reads_the_grouped_answer():
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"meta": {"count": 50}, "group_by": [
            {"key": "https://openalex.org/fields/27", "key_display_name": "Medicine", "count": 40}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    got = asyncio.run(openalex_module.field_distribution(client, '("a") AND ("b")'))
    assert seen == [{"search.title_and_abstract": '("a") AND ("b")', "group_by": "primary_topic.field.id"}]
    assert (got["total"], got["fields"]) == (50, [{"field": "Medicine", "key": "https://openalex.org/fields/27",
                                                   "count": 40}])
    broken = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"meta": {"count": 5}})))
    assert asyncio.run(openalex_module.field_distribution(broken, "q")) is None


# ---- through a discovery run --------------------------------------------------------------------------------------


class Grouping:
    """OpenAlex answering counts, searches and the grouped routing request, every grouped query recorded."""

    def __init__(self, groups=None, fail=False):
        self.groups = groups if groups is not None else [("Medicine", 90), ("Engineering", 10)]
        self.fail, self.grouped, self.searches = fail, [], []

    def __call__(self, request):
        if request.url.host != "api.openalex.org":
            return httpx.Response(404)
        params = request.url.params
        query = params.get("search.title_and_abstract")
        if params.get("group_by"):
            self.grouped.append(query)
            if self.fail:
                return httpx.Response(500, text="SYNTHETIC server error")
            return httpx.Response(200, json={"meta": {"count": sum(n for _, n in self.groups)}, "group_by": [
                {"key": f"https://openalex.org/fields/{i}", "key_display_name": name, "count": n}
                for i, (name, n) in enumerate(self.groups)]})
        if params.get("per_page") == "1" and params.get("select") == "id":
            return httpx.Response(200, json={"meta": {"count": 40}, "results": []})
        self.searches.append(query)
        return httpx.Response(200, json={"meta": {"count": 1}, "results": [WORK]})


def start(client, effort="standard"):
    body = {"question": QUESTION, "model_connection": "fake", "requested_model": "fake-model", "effort": effort}
    rid = client.post("/api/researches", json=body).json()["research"]["id"]
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    return rid, run_id


def searched(run):
    return sorted({s["kind"].split(":")[1] for s in run["steps"] if s["kind"].startswith("provider_search:")})


@pytest.mark.field_distribution
def test_a_clinical_distribution_searches_pubmed_and_biorxiv_and_the_card_and_body_say_why(tmp_path, monkeypatch):
    openalex = Grouping()
    client = approval_client(approval_app(tmp_path, monkeypatch, openalex, approval="as_proposed"))
    try:
        rid, run_id = start(client)
        view, run = wait(client, rid, run_id)
        store = client.app.state.store
        body = store.current_protocol(rid, 1)["body"]
    finally:
        client.__exit__(None, None, None)
    assert len(openalex.grouped) == 1
    assert "arxiv" not in searched(run) and "openalex" in searched(run)
    assert run["approval"]["routing"]["providers"] == ["openalex", "semantic_scholar", "biorxiv", "pubmed"]
    routed = body["source_routing"]
    assert routed["status"] == "read" and routed["total"] == 100 and routed["query"] == openalex.grouped[0]
    assert {row["provider_id"]: row["reason"] for row in routed["left_out"]}["arxiv"] == "share_below"
    assert body["providers"] == ["biorxiv", "openalex", "pubmed", "semantic_scholar"]
    s2 = [q for q in body["compiled_queries"] if q["provider_id"] == "semantic_scholar"]
    assert s2 and all(q["endpoint"] == "bulk" for q in s2)


@pytest.mark.field_distribution
def test_an_unreadable_distribution_searches_every_domain_source_in_scope(tmp_path, monkeypatch):
    openalex = Grouping(fail=True)
    client = approval_client(approval_app(tmp_path, monkeypatch, openalex, approval="as_proposed"))
    try:
        rid, run_id = start(client)
        view, run = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    record = run["approval"]["routing"]
    assert record["status"] == "unavailable"
    assert record["providers"] == ["openalex", "semantic_scholar", "arxiv", "biorxiv", "pubmed"]


@pytest.mark.field_distribution
def test_a_resumed_run_does_not_ask_again_and_a_correction_asks_once_for_its_new_gate_query(tmp_path, monkeypatch):
    openalex = Grouping(groups=[("Computer Science", 60), ("Engineering", 40)])
    client = approval_client(approval_app(tmp_path, monkeypatch, openalex))
    try:
        rid, run_id = start(client)
        view, run = wait(client, rid, run_id)
        assert run["pause_reason"] == "protocol_approval_needed" and len(openalex.grouped) == 1
        before = run["approval"]["routing"]
        assert before["providers"] == ["openalex", "semantic_scholar", "arxiv"]
        # An added setting term changes the gate query: the distribution is read once more, for the new query.
        approve(client, run_id, terms=[{"op": "add", "phrase": "SYNTHETIC mesh radios", "block": "setting"}])
        view, run = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert len(openalex.grouped) == 2 and openalex.grouped[1] != openalex.grouped[0]
    assert "synthetic" in openalex.grouped[1].casefold()  # the code vocabulary enters the phrase by its rarest word
    assert run["approval"]["routing"]["query"] == openalex.grouped[1]
    assert searched(run) == ["arxiv", "openalex", "semantic_scholar"]


@pytest.mark.field_distribution
def test_an_approval_without_a_correction_reads_the_distribution_once(tmp_path, monkeypatch):
    openalex = Grouping(groups=[("Computer Science", 60), ("Engineering", 40)])
    client = approval_client(approval_app(tmp_path, monkeypatch, openalex))
    try:
        rid, run_id = start(client)
        wait(client, rid, run_id)
        approve(client, run_id)
        view, run = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert run["status"] in ("completed", "paused") and run["pause_reason"] != "protocol_approval_needed"
    assert len(openalex.grouped) == 1


@pytest.mark.field_distribution
def test_a_chosen_source_the_query_limit_leaves_without_a_query_is_not_called_searched(tmp_path, monkeypatch):
    """Review of slice 14 (2026-09-23): `quick`'s three queries go to OpenAlex, Semantic Scholar and arXiv, and IEEE,
    chosen by the distribution, was listed as searched on the card and in the body."""
    openalex = Grouping(groups=[("Computer Science", 60), ("Engineering", 40)])
    app = approval_app(tmp_path, monkeypatch, openalex)
    monkeypatch.setenv("IEEE_API_KEY", "SYNTHETIC-key")
    client = approval_client(app)
    try:
        rid, run_id = start(client, effort="quick")
        view, run = wait(client, rid, run_id)
        card = run["approval"]["routing"]
        approve(client, run_id)
        view, run = wait(client, rid, run_id)
        body = client.app.state.store.current_protocol(rid, 1)["body"]
    finally:
        client.__exit__(None, None, None)
    assert card["providers"] == ["openalex", "semantic_scholar", "arxiv", "ieee_xplore"]
    assert card["queried"] == ["openalex", "semantic_scholar", "arxiv"]
    queried = {q["provider_id"] for q in body["compiled_queries"]}
    assert sorted(body["providers"]) == sorted(p for p in card["providers"] if p in queried)
    assert body["source_routing"]["chosen_not_queried"] == [p for p in card["providers"] if p not in queried]
    assert "ieee_xplore" in [row["provider_id"] for row in body["source_routing"]["chosen"]]


def pre_routing_card(client, rid, run_id):
    """Make this run's waiting card one shown before D93: no routing step, no routing in the proposal."""
    store = client.app.state.store
    store.conn.execute("DELETE FROM run_steps WHERE run_id = ? AND operation_key = 'source_routing'", (run_id,))
    step = store.approval_step(run_id)
    output = step["output"]
    output["proposal"].pop("routing", None)
    store.set_step_output(step["id"], output)


def pre_routing_run(tmp_path, monkeypatch, terms=()):
    """A detailed run with CORE in scope whose card is made a pre-D93 one before it is approved. The expansion's
    SYNTHETIC field gives the run a second round; the distribution is not read (no marker), which changes nothing
    here, as the routing is removed before the approval."""
    app = approval_app(tmp_path, monkeypatch, expansion_flow.Field())
    monkeypatch.setenv("CORE_API_KEY", "SYNTHETIC-key")
    client = approval_client(app)
    try:
        body = {"question": expansion_flow.QUESTION, "model_connection": "fake", "requested_model": "fake-model",
                "effort": "detailed"}
        rid = client.post("/api/researches", json=body).json()["research"]["id"]
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, run_id)
        pre_routing_card(client, rid, run_id)
        approve(client, run_id, terms=terms)
        view, run = wait(client, rid, run_id)
        store = client.app.state.store
        card = store.approval_step(run_id)["output"]
        expansion = store.existing_step(run_id, "vocabulary_expansion")
        body = store.current_protocol(rid, 1)["body"]
    finally:
        client.__exit__(None, None, None)
    return card, expansion, body


def test_a_card_shown_before_routing_and_corrected_keeps_the_query_semantics_it_showed(tmp_path, monkeypatch):
    """Review of slice 14 (2026-09-23): a correction on a card shown before D93 recompiled the queries with the
    routing-era compiler, moving Semantic Scholar to the bulk endpoint and dropping CORE in the old scope revision."""
    card, _, body = pre_routing_run(
        tmp_path, monkeypatch, terms=[{"op": "add", "phrase": "SYNTHETIC mesh radios", "block": "setting"}])
    approved = card["approved"]["queries"]
    s2 = [q for q in approved if q["provider_id"] == "semantic_scholar"]
    assert s2 and all("endpoint" not in q for q in s2)
    assert "core" in {q["provider_id"] for q in approved}
    assert card["approved"].get("routing") is None and "source_routing" not in body
    assert "core" in body["providers"]


def test_a_run_from_before_routing_compiles_its_second_round_as_its_first(tmp_path, monkeypatch):
    """Review of slice 14 (2026-09-23): an old run's fresh second round took the bulk endpoint and left CORE out."""
    _, expansion, _ = pre_routing_run(tmp_path, monkeypatch)
    assert expansion is not None and expansion["status"] == "succeeded"
    second = expansion["output"]["queries"]
    assert second, "the SYNTHETIC expansion compiled no second-round query"
    assert all("endpoint" not in q for q in second)
    assert "core" in {q["provider_id"] for q in second}
