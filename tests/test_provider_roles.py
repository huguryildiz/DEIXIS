"""What each connector is for: a source a query is sent to, or a source asked about a record whose DOI is known (D87).

Crossref is the second kind. It is no longer given a search query; it still answers what a record's metadata and links
are, and both `record_lookup:crossref` and the DOI checks of `documents/acquisition.py` are untouched by that. The rule
is `Connector.searchable` alone, so neither the flow nor the query compiler names a provider (slice 05).

Records and questions are SYNTHETIC and every provider is mocked: passing shows workflow behavior, not recall.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.providers import query_compiler
from deixis.providers.registry import (CONNECTORS, available_providers, configured_providers, provider_role,
                                       verification_providers)
from deixis.workflow import lookups
from fakes import FakeAdapter
from test_provider_flow import discover, routed, two_provider_plan
from test_vocabulary_flow import QUESTION, CountingOpenAlex, DeadAdapter, app_for, start, wait

VERIFICATION_ONLY = ("crossref",)


# ---- Task 1: the connector's role ------------------------------------------------------------


def test_a_verification_connector_is_configured_but_is_in_no_search_list():
    assert [pid for pid, c in CONNECTORS.items() if not c.searchable] == list(VERIFICATION_ONLY)
    assert set(available_providers()).isdisjoint(VERIFICATION_ONLY)
    assert set(verification_providers()) == set(VERIFICATION_ONLY) & set(configured_providers())
    # Every configured connector has exactly one of the two roles, and the scope is the two lists together.
    assert sorted(configured_providers()) == sorted(available_providers() + verification_providers())


@pytest.mark.parametrize("provider_id, expected", [("crossref", "verification"), ("openalex", "search"),
                                                   ("semantic_scholar", "search")])
def test_each_connector_reports_its_role(provider_id, expected):
    assert provider_role(CONNECTORS[provider_id]) == expected


def test_the_connection_view_gives_every_provider_its_role(tmp_path, monkeypatch):
    with TestClient(app_for(tmp_path, monkeypatch, routed, DeadAdapter())) as client:
        providers = client.get("/api/connections").json()["providers"]
    roles = {p["id"]: p["role"] for p in providers}
    assert roles["crossref"] == "verification"
    assert {role for pid, role in roles.items() if pid not in VERIFICATION_ONLY} == {"search"}


# ---- Task 2: query compiling and discovery ---------------------------------------------------


def test_the_compiler_sends_no_query_to_a_verification_connector():
    plan = {"concepts": [{"label": "diffusion channel", "role": "core", "synonyms": ["diffusion channel"]},
                         {"label": "scheduling", "role": "method", "synonyms": ["scheduling"]}],
            "providers": ["openalex", "crossref", "semantic_scholar"]}
    # The scope may still hold the connector; the compiler is what drops it, so no caller names a provider.
    queries = query_compiler.compile_queries(plan, ["openalex", "crossref", "semantic_scholar"], 100)
    assert {q["provider_id"] for q in queries} == {"openalex", "semantic_scholar"}


def test_a_new_research_keeps_the_verification_connector_in_its_scope_and_hides_it_from_the_model(tmp_path, monkeypatch):
    adapter = FakeAdapter(two_provider_plan)
    view, run = discover(tmp_path, monkeypatch, routed, adapter)
    assert run["status"] == "completed", run
    # In scope, so `record_lookup:crossref` is still asked about a record whose DOI is known.
    assert "crossref" in view["scope"]["providers"]
    assert lookups.in_scope({"providers": view["scope"]["providers"]}, "crossref") is True
    # Not offered to the model, which is why it can no longer name it in a plan.
    assert "crossref" not in adapter.calls[0]["enabled_providers"]


def test_an_sw_discovery_compiles_a_query_for_every_searchable_provider_and_none_for_crossref(tmp_path, monkeypatch):
    openalex, adapter = CountingOpenAlex(), DeadAdapter()
    with TestClient(app_for(tmp_path, monkeypatch, openalex, adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, QUESTION)
        view, run = wait(client, rid, run_id)
        store = client.app.state.store
        compiled = store.step(run_id, "vocabulary", "code:vocabulary")["output"]["queries"]
    assert run["status"] == "completed", run
    providers = [q["provider_id"] for q in compiled]
    assert "crossref" not in providers
    assert "openalex" in providers and "semantic_scholar" in providers
    # The effort's request budget cuts the list short; what it keeps is the scope's searchable providers in order.
    assert providers == [p for p in view["scope"]["providers"] if p != "crossref"][:len(providers)]
    assert "crossref" not in [s["provider"] for s in view["search_runs"]]


def test_a_stored_query_for_a_connector_that_is_no_longer_searched_is_skipped_and_the_run_goes_on(tmp_path, monkeypatch):
    down = {"openalex": True}

    def handler(request):  # nothing answers until the run has paused, so the stored plan is the one that is resumed
        return httpx.Response(503) if down["openalex"] else routed(request)

    def store_a_crossref_query(store, run_id):
        # A plan frozen before the connector's role changed. A resumed run reads its stored queries, so this is the
        # only way one can still name Crossref.
        step = store.step(run_id, "search_plan", "model:search_plan")
        step["output"]["queries"] = step["output"]["queries"] + [
            {"provider_id": "crossref", "query_text": "diffusion channel scheduling",
             "rationale": "SYNTHETIC plan stored before D87"}]
        store.set_step_output(step["id"], step["output"])
        down["openalex"] = False

    view, run = discover(tmp_path, monkeypatch, handler, FakeAdapter(two_provider_plan),
                         before_resume=store_a_crossref_query)
    assert run["status"] == "completed", run
    skipped = [s for s in run["steps"] if s["kind"] == "provider_search:crossref"]
    assert [(s["status"], s["error_code"]) for s in skipped] == [("cancelled", "provider_not_searchable")]
    # Nothing was requested and nothing was recorded as a search, and the queries that could be sent still were.
    assert "crossref" not in [s["provider"] for s in view["search_runs"]]
    assert [(s["provider"], s["status"]) for s in view["search_runs"]][-2:] == [
        ("openalex", "completed"), ("biorxiv", "completed")]
