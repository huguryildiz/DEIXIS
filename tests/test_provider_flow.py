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
