"""Discovery across several providers through the API: dispatch, DOI merge and request accounting (mocked HTTP).

The two planned providers are OpenAlex and bioRxiv, which OpenAlex serves under a source filter: both answer on the
same mocked host, and a provider that is only asked about a known DOI is not planned at all (D87).
"""

import json
import time

import httpx
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents.fetch import FetchResult
from deixis.providers import biorxiv as biorxiv_module
from deixis.providers.registry import CONNECTORS, available_providers
from fakes import FakeAdapter, valid_response

def work(number, doi, title):
    return {"id": f"https://openalex.org/W{number}", "doi": f"https://doi.org/{doi}", "display_name": title,
            "publication_year": 2021, "type": "article", "authorships": [],
            "abstract_inverted_index": {"We": [0], "schedule.": [1]}}


OPENALEX = {"meta": {"count": 1}, "results": [work(1, "10.1/a", "SYNTHETIC diffusion channel scheduling")]}
# bioRxiv is searched through OpenAlex under its own source filter, so the two connectors answer separately. The first
# record is the same work with its DOI in upper case, which merges into one source.
BIORXIV = {"meta": {"count": 2}, "results": [work(2, "10.1/A", "SYNTHETIC diffusion channel scheduling"),
                                             work(3, "10.1/b", "SYNTHETIC relay energy budget")]}


def routed(request):
    if request.url.host != "api.openalex.org":
        return httpx.Response(404)
    biorxiv = biorxiv_module.SOURCE_ID in (request.url.params.get("filter") or "")
    return httpx.Response(200, json=BIORXIV if biorxiv else OPENALEX)


def two_provider_plan(si):
    if si["task_type"] != "search_plan":
        return valid_response(si)
    output = json.loads(valid_response(si))
    output["search_plan"].update(providers=["openalex", "biorxiv"], concepts=[
        {"label": "diffusion channel", "role": "core", "synonyms": ["diffusion channel"]},
        {"label": "scheduling", "role": "method", "synonyms": ["scheduling"]}])
    return json.dumps(output)


async def no_fetch(url):
    return FetchResult("http_error", final_url=url, http_status=404)


def discover(tmp_path, monkeypatch, handler, adapter, before_resume=None, retry_failed=False):
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
        view, run = wait(client, rid, run_id)
        if before_resume and run["status"] == "paused":
            before_resume(app.state.store, run_id)
            client.post(f"/api/runs/{run_id}/resume")
            view, run = wait(client, rid, run_id)
        if retry_failed:
            response = client.post(f"/api/runs/{run_id}/retry_failed")
            assert response.status_code == 200, response.text
            view, run = wait(client, rid, run_id)
    return view, run


def wait(client, rid, run_id):
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
    # Crossref is in the scope for the records whose DOI is already known, and is not offered as a place to search.
    assert "crossref" in view["scope"]["providers"]
    assert adapter.calls[0]["enabled_providers"] == available_providers() == [
        p for p in view["scope"]["providers"] if p != "crossref"]
    assert [(s["provider"], s["result_count"]) for s in view["search_runs"]] == [("openalex", 1), ("biorxiv", 2)]
    assert [s["kind"] for s in run["steps"] if s["operation_key"].startswith("search:")] == ["provider_search:openalex", "provider_search:biorxiv"]
    assert run["usage"]["provider_requests"] == 2 and view["counts"]["unique"] == 2
    merged = next(s for s in view["sources"] if s["doi"] == "10.1/a")
    assert merged["provider_records"] == ["biorxiv", "openalex"] and merged["suspected_duplicates"] == []


def test_a_failed_provider_search_is_kept_and_the_other_searches_go_on(tmp_path, monkeypatch):
    def biorxiv_limited(request):
        if biorxiv_module.SOURCE_ID in (request.url.params.get("filter") or ""):
            return httpx.Response(429, headers={"retry-after": "60"})
        return routed(request)

    view, run = discover(tmp_path, monkeypatch, biorxiv_limited, FakeAdapter(two_provider_plan))
    assert (run["status"], run["pause_reason"]) == ("completed", None), run
    assert [(s["provider"], s["status"]) for s in view["search_runs"]] == [("openalex", "completed"), ("biorxiv", "rate_limited")]
    assert [s["status"] for s in run["steps"] if s["operation_key"].startswith("search:")] == ["succeeded", "failed"]
    assert view["counts"]["unique"] == 1 and any(s["operation_key"] == "screening" for s in run["steps"])


def test_failed_provider_searches_can_be_retried_without_repeating_the_plan(tmp_path, monkeypatch):
    attempts = {"biorxiv": 0}

    def biorxiv_once(request):
        if biorxiv_module.SOURCE_ID in (request.url.params.get("filter") or ""):
            attempts["biorxiv"] += 1
            if attempts["biorxiv"] == 1:
                return httpx.Response(429, headers={"retry-after": "60"})
        return routed(request)

    adapter = FakeAdapter(two_provider_plan)
    view, run = discover(tmp_path, monkeypatch, biorxiv_once, adapter, retry_failed=True)
    assert run["status"] == "completed", run
    assert [s["status"] for s in view["search_runs"]] == ["completed", "rate_limited", "completed"]
    assert [c["task_type"] for c in adapter.calls].count("search_plan") == 1


def test_compiled_queries_are_stored_with_the_plan_and_a_resumed_run_searches_them_again(tmp_path, monkeypatch):
    down = {"openalex": True}

    def handler(request):  # bioRxiv stays down, OpenAlex answers once the run is resumed
        if biorxiv_module.SOURCE_ID in (request.url.params.get("filter") or "") or down["openalex"]:
            return httpx.Response(503)
        return routed(request)

    def edit_stored_query(store, run_id):
        # Stands in for a compiler change between pause and resume: the stored queries, not a new compilation, are searched.
        step = store.step(run_id, "search_plan", "model:search_plan")
        assert step["output"]["query_compiler"] == "deixis.query_compiler.v2"
        assert [q["query_text"] for q in step["output"]["queries"]] == ['"diffusion channel" AND scheduling'] * 2
        step["output"]["queries"] = step["output"]["queries"][:1]
        store.set_step_output(step["id"], step["output"])
        down["openalex"] = False

    adapter = FakeAdapter(two_provider_plan)
    view, run = discover(tmp_path, monkeypatch, handler, adapter, before_resume=edit_stored_query)
    assert run["status"] == "completed", run
    assert [c["task_type"] for c in adapter.calls].count("search_plan") == 1
    assert [q["query_text"] for q in run["plan"]["queries"]] == ['"diffusion channel" AND scheduling']
    assert [(s["provider"], s["status"]) for s in view["search_runs"]][-1] == ("openalex", "completed")


def test_a_search_plan_v1_from_before_d44_still_shows_its_model_written_queries(tmp_path, monkeypatch):
    def v1_plan(store, run_id):
        step = store.step(run_id, "search_plan", "model:search_plan")
        result = step["output"]["result"] | {"schema_version": "deixis.search_plan.v1", "queries": [
            {"provider_id": "openalex", "query_text": '"diffusion channel" AND scheduling', "rationale": "SYNTHETIC v1 rationale"}]}
        del result["providers"]
        store.set_step_output(step["id"], {k: v for k, v in step["output"].items() if k not in ("queries", "query_compiler")} | {"result": result})

    view, run = discover(tmp_path, monkeypatch, lambda request: httpx.Response(503), FakeAdapter(two_provider_plan), before_resume=v1_plan)
    assert [(q["query_text"], q["rationale"]) for q in run["plan"]["queries"]] == [('"diffusion channel" AND scheduling', "SYNTHETIC v1 rationale")]
    # Resumed, the v1 run searches the queries its model wrote.
    assert [s["query_text"] for s in view["search_runs"]][-1] == '"diffusion channel" AND scheduling'
