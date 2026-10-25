"""D59: a model that a real step finds not served (404) or answered by another model is kept out of the model lists.
SYNTHETIC records and the fake adapter: these tests show what is recorded and offered, not provider behavior.
"""

import pytest
from fastapi.testclient import TestClient

from deixis.models import unusable
from deixis.models.adapter import ModelStepResult
from fakes import FakeAdapter
from test_api_flow import app_for, create, session
from test_table_extraction import execute, fill, library


@pytest.fixture(autouse=True)
def fake_learns(monkeypatch):
    monkeypatch.setattr(unusable, "LEARNS", unusable.LEARNS | {"fake"})  # the fake adapter stands in for a provider API


class Settings:
    def __init__(self, value=None):
        self.value = value

    def setting(self, key):
        return self.value

    def set_setting(self, key, value):
        self.value = value


def not_served(si):
    return ModelStepResult("failed", error="HTTP 404: API request failed", error_kind="model_unavailable", http_status=404)


def test_a_404_on_a_real_step_records_the_model_as_not_served(tmp_path):
    lib = library(tmp_path)
    lib.adapter.fail = not_served
    stopped = execute(lib, fill(lib))
    assert (stopped["status"], stopped["pause_reason"]) == ("paused", "model_call_failed")
    assert unusable.hidden(lib.store, "fake")["fake-model"]["reason"] == unusable.NOT_SERVED


def test_a_recorded_model_is_left_out_of_every_model_choice(tmp_path):
    adapter = FakeAdapter(models=["fake-model", "fake-model-2"])
    with TestClient(app_for(tmp_path, adapter)) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        unusable.record(raw.app.state.store, "fake", "fake-model-2", unusable.NOT_SERVED)

        listed = client.get("/api/connections").json()["models"]["fake"]
        assert [m["id"] for m in listed["models"]] == ["fake-model"]
        assert [(m["id"], m["reason"]) for m in listed["hidden_models"]] == [("fake-model-2", "not_served")]

        refused = client.post("/api/researches", json={"question": "How is molecule release scheduling optimized?",
            "model_connection": "fake", "requested_model": "fake-model-2", "effort": "quick"})
        assert refused.status_code == 422 and "not offered" in refused.text
        version = client.get(f"/api/researches/{rid}").json()["research"]["version"]
        moved = client.put(f"/api/researches/{rid}/models", json={"role": "answer", "connection": "fake",
            "model": "fake-model-2", "expected_version": version})
        assert moved.status_code == 422
        assert client.put("/api/settings/answer", json={"model_connection": "fake",
            "model": "fake-model-2"}).status_code == 422


