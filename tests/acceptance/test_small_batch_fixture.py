"""Exercise the browser fixture's scripted provider/model without a listening socket."""

import httpx
import pytest
from fastapi.testclient import TestClient

from fixture_server import MODEL, ScriptedCodex, fetch, openalex
from deixis.api.app import create_app
from deixis.config import Settings
from test_fetch_overlap_flow import wait


@pytest.mark.parametrize("reading", ["off", "auto"])
def test_scripted_fixture_small_batch_discovery(tmp_path, monkeypatch, reading):
    monkeypatch.setenv("DEIXIS_SMALL_BATCH_INSPECTION", "on")
    app = create_app(
        Settings(data_dir=tmp_path, port=8877, model_concurrency=1,
                 protocol_approval="as_proposed", search_query="code",
                 fulltext_fetch="auto" if reading == "auto" else "off",
                 fulltext_adjudication=reading),
        adapters={"codex": ScriptedCodex(tmp_path)},
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(openalex)),
        fetcher=fetch, extra_hosts=("testserver",), trusted_clients=("testclient",),
    )
    with TestClient(app) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        response = client.post("/api/researches", json={
            "question": "How is molecule release scheduled with bisection in relay networks?",
            "model_connection": "codex", "requested_model": MODEL, "effort": "quick",
        })
        assert response.status_code == 201, response.text
        rid = response.json()["research"]["id"]
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, run = wait(client, rid, run_id)
        assert run["status"] == "completed", run
        assert run["budget"]["inspection"]["policy"] == "small_batch_fused_v1"
        assert run["inspection_progress"]["counts"]["processed"] > 0
