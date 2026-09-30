"""What each connector is for: a source a query is sent to, or a source asked about a record whose DOI is known (D87).

Crossref is the second kind. It is no longer given a search query; it still answers what a record's metadata and links
are, and both `record_lookup:crossref` and the DOI checks of `documents/acquisition.py` are untouched by that. The rule
is `Connector.searchable` alone, so neither the flow nor the query compiler names a provider (slice 05).

Records and questions are SYNTHETIC and every provider is mocked: passing shows workflow behavior, not recall.
"""

from dataclasses import replace

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






def test_an_sw_vocabulary_compiles_no_scopus_query_and_a_legacy_plan_still_does():
    vocabulary = {"terms": [
        {"phrase": phrase, "block": block, "origin": "question", "root": phrase, "in_query": "phrase",
         "phrase_count": 10, "root_count": None, "and_only": False, "dropped": None}
        for phrase, block in (("tidal wetlands", "setting"), ("sediment accretion", "task"))]}
    sw = query_compiler.compile_block_queries(vocabulary, ["openalex", "scopus", "semantic_scholar"], 100)
    assert [q["provider_id"] for q in sw] == ["openalex", "semantic_scholar"]
    plan = {"concepts": [{"label": "diffusion channel", "role": "core", "synonyms": ["diffusion channel"]},
                         {"label": "scheduling", "role": "method", "synonyms": ["scheduling"]}],
            "providers": ["openalex", "scopus"]}
    legacy = query_compiler.compile_queries(plan, ["openalex", "scopus"], 100)
    assert [(q["provider_id"], q["query_text"]) for q in legacy] == [
        ("openalex", '"diffusion channel" AND scheduling'),
        ("scopus", 'TITLE-ABS-KEY("diffusion channel" AND scheduling)')]
    assert CONNECTORS["scopus"].searchable and not CONNECTORS["scopus"].sw_searchable


class ElsevierAndOpenAlex(CountingOpenAlex):
    """OpenAlex as `CountingOpenAlex` serves it, and Scopus refusing the complete view: no institutional network."""

    def __init__(self):
        super().__init__()
        self.elsevier = []

    def __call__(self, request):
        if request.url.host == "api.elsevier.com":
            self.elsevier.append(dict(request.url.params))
            return httpx.Response(401, json={"service-error": {"status": {"statusCode": "AUTHORIZATION_ERROR"}}})
        return super().__call__(request)


def test_an_sw_research_with_scopus_configured_neither_searches_it_nor_names_it_a_searched_source(tmp_path, monkeypatch):
    sources = ElsevierAndOpenAlex()
    app = app_for(tmp_path, monkeypatch, sources, DeadAdapter())
    monkeypatch.setenv("SCOPUS_API_KEY", "SYNTHETIC-scopus-key")
    with TestClient(app) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, QUESTION)
        view, run = wait(client, rid, run_id)
        store = client.app.state.store
        compiled = store.step(run_id, "vocabulary", "code:vocabulary")["output"]["queries"]
        body = store.current_protocol(rid, 1)["body"]
    assert "scopus" in view["scope"]["providers"]  # in scope, for the abstract lookup
    assert "scopus" not in view["scope"]["search_providers"]
    assert "scopus" not in [q["provider_id"] for q in compiled]
    assert "scopus" not in [s["provider"] for s in view["search_runs"]]
    assert "scopus" not in body["providers"] and "scopus" in body["verification_providers"]
    # The only Scopus request is the one access check of the lookup plan; no search went there.
    assert [params.get("view") for params in sources.elsevier] == ["COMPLETE"]
