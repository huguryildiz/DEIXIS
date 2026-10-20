"""The answer model's equation reading through the app (D113): its Settings route says which model reads equations or why
none does, and the switch and budget are saved. The Marker routes are gone.

The model connection is the test FakeAdapter, which takes no images; nothing is sent to any model here.
"""

import httpx
from fastapi.testclient import TestClient

from arxiv_helpers import no_network  # noqa: F401
from deixis.api.app import create_app
from deixis.config import Settings
from deixis.workflow import equations
from fakes import FakeAdapter
from test_api_flow import fake_fetch, openalex_client, session


def test_the_route_says_why_it_is_off_and_saves_the_switch_and_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(equations.EquationService, "start", lambda self: None)
    settings = Settings(data_dir=tmp_path / "data", port=8765, arxiv_source="off")
    app = create_app(settings, adapters={"fake": FakeAdapter()}, http_client=openalex_client(200),
                     fetcher=fake_fetch, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as raw:
        client = session(raw)
        status = client.get("/api/equation-model").json()
        assert status["switch"] == "on" and status["ready"] is False and status["reason"] == "no_answer_model"
        assert status["model"] is None and status["month_requests"] == 0 and status["month_cost"] == {"usd": 0.0, "calls_without_cost": 0}
        client.put("/api/settings/answer", json={"model_connection": "fake", "model": "fake-model", "reasoning_effort": None})
        status = client.get("/api/equation-model").json()
        assert status["reason"] == "model_no_images" and status["model"] == {"connection": "fake", "model": "fake-model",
                                                                              "reasoning_effort": None}
        status = client.put("/api/equation-model", json={"switch": "off", "monthly_budget": 200}).json()
        assert status["switch"] == "off" and status["reason"] == "switch_off" and status["monthly_budget"] == 200
        assert client.get("/api/equation-reader").status_code in (404, 405)
        assert client.get("/api/tool-updates/marker").status_code == 404
        assert "marker_present" not in client.get("/api/settings/preferences").json()
