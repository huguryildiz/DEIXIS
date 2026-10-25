"""What each connector is for: a source a query is sent to, or a source asked about a record whose DOI is known (D87).

Crossref is the second kind. It is no longer given a search query; it still answers what a record's metadata and links
are, and both `record_lookup:crossref` and the DOI checks of `documents/acquisition.py` are untouched by that. The rule
is `Connector.searchable` alone, so neither the flow nor the query compiler names a provider (slice 05).

Records and questions are SYNTHETIC and every provider is mocked: passing shows workflow behavior, not recall.
"""


import httpx
from fastapi.testclient import TestClient

from deixis.providers.registry import verification_providers
from test_vocabulary_flow import QUESTION, CountingOpenAlex, DeadAdapter, app_for, start, wait


# ---- Task 1: the connector's role ------------------------------------------------------------


# ---- Task 2: query compiling and discovery ---------------------------------------------------


def block_vocabulary(*terms):
    return {"terms": [
        {"phrase": phrase, "block": block, "origin": "question", "root": phrase, "in_query": "phrase",
         "phrase_count": 10, "root_count": None, "and_only": False, "dropped": None}
        for phrase, block in terms]}


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
