"""Discovery across several providers through the API: dispatch, DOI merge and request accounting (mocked HTTP)."""

import json
import time

import httpx
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents.fetch import FetchResult
from deixis.providers.registry import CONNECTORS
from fakes import FakeAdapter, valid_response

OPENALEX = {"meta": {"count": 1}, "results": [{
    "id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/a", "display_name": "SYNTHETIC diffusion channel scheduling",
    "publication_year": 2021, "type": "article", "authorships": [], "abstract_inverted_index": {"We": [0], "schedule.": [1]}}]}
CROSSREF = {"message": {"total-results": 2, "items": [
    {"DOI": "10.1/A", "title": ["SYNTHETIC diffusion channel scheduling"], "type": "journal-article", "URL": "https://doi.org/10.1/a"},
    {"DOI": "10.1/b", "title": ["SYNTHETIC relay energy budget"], "type": "journal-article", "URL": "https://doi.org/10.1/b"},
]}}


def routed(request):
    payload = {"api.openalex.org": OPENALEX, "api.crossref.org": CROSSREF}.get(request.url.host)
    return httpx.Response(200, json=payload) if payload else httpx.Response(404)


def two_provider_plan(si):
    if si["task_type"] != "search_plan":
        return valid_response(si)
    output = json.loads(valid_response(si))
    output["search_plan"]["queries"] = [
        {"provider_id": "openalex", "query_text": '"diffusion channel" AND scheduling', "rationale": "fake"},
        {"provider_id": "crossref", "query_text": "diffusion channel scheduling", "rationale": "fake"},
    ]
    return json.dumps(output)


async def no_fetch(url):
    return FetchResult("http_error", final_url=url, http_status=404)


def discover(tmp_path, monkeypatch, handler, adapter):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters={"fake": adapter},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), fetcher=no_fetch,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        body = {"question": "How is diffusion channel scheduling optimized?", "model_connection": "fake",
                "requested_model": "fake-model", "effort": "quick"}
        rid = client.post("/api/researches", json=body).json()["research"]["id"]
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        deadline = time.time() + 15
        while time.time() < deadline:
            view = client.get(f"/api/researches/{rid}").json()
            run = next(r for r in view["runs"] if r["id"] == run_id)
            if run["status"] in ("completed", "failed", "paused"):
                break
            time.sleep(0.1)
    return view, run


def test_discovery_searches_each_planned_provider_and_merges_by_doi(tmp_path, monkeypatch):
    adapter = FakeAdapter(two_provider_plan)
    view, run = discover(tmp_path, monkeypatch, routed, adapter)
    assert run["status"] == "completed", run
    assert view["scope"]["providers"] == ["openalex", "semantic_scholar", "crossref", "arxiv", "biorxiv", "pubmed"]
    assert adapter.calls[0]["enabled_providers"] == view["scope"]["providers"]
    assert [(s["provider"], s["result_count"]) for s in view["search_runs"]] == [("openalex", 1), ("crossref", 2)]
    assert [s["kind"] for s in run["steps"] if s["operation_key"].startswith("search:")] == ["provider_search:openalex", "provider_search:crossref"]
    assert run["usage"]["provider_requests"] == 2 and view["counts"]["unique"] == 2
    merged = next(s for s in view["sources"] if s["doi"] == "10.1/a")
    assert merged["provider_records"] == ["crossref", "openalex"] and merged["suspected_duplicates"] == []


def test_a_failed_provider_search_is_kept_and_the_other_searches_go_on(tmp_path, monkeypatch):
    def crossref_limited(request):
        if request.url.host == "api.crossref.org":
            return httpx.Response(429, headers={"retry-after": "60"})
        return routed(request)

    view, run = discover(tmp_path, monkeypatch, crossref_limited, FakeAdapter(two_provider_plan))
    assert (run["status"], run["pause_reason"]) == ("completed", None), run
    assert [(s["provider"], s["status"]) for s in view["search_runs"]] == [("openalex", "completed"), ("crossref", "rate_limited")]
    assert [s["status"] for s in run["steps"] if s["operation_key"].startswith("search:")] == ["succeeded", "failed"]
    assert view["counts"]["unique"] == 1 and any(s["operation_key"] == "screening" for s in run["steps"])
