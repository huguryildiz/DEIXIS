"""Every model connection the app registers can be named in a StepInput, and the contract names no other."""

import copy
import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.domain.contracts import check_step_input
from test_settings_connections import paths, remote  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "contracts/research/step-input.schema.json").read_text())
STEP_INPUTS = json.loads((ROOT / "tests/fixtures/research/step-inputs.json").read_text())
TEST_ONLY = {"fake"}  # tests/support/fakes.py::FakeAdapter


def contract_connections():
    return set(SCHEMA["properties"]["model"]["properties"]["connection"]["enum"])


def registered_connections(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), start_worker=False,
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(remote)),
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app):
        return set(app.state.adapters)


def test_the_step_input_contract_names_exactly_the_registered_connections(tmp_path, paths):
    assert contract_connections() - TEST_ONLY == registered_connections(tmp_path)


def test_a_step_input_for_every_registered_connection_passes_the_contract(tmp_path, paths):
    for connection in sorted(registered_connections(tmp_path)):
        step_input = copy.deepcopy(STEP_INPUTS["A_answer"])
        step_input["model"] = {"connection": connection, "requested_model": "SYNTHETIC-model"}
        assert check_step_input(step_input) == [], connection


ADDED = ("anthropic", "openai", "copilot_cli", "gemini_cli", "local_server", "grok", "glm", "muse_spark",
         "muse_glimmer", "openrouter", "mimo")


def test_a_research_on_each_added_connection_runs_its_model_steps(tmp_path, monkeypatch):
    """16 Oct 2026: a research on the Anthropic API stopped at planning, every StepInput refused by the contract."""
    from test_abstract_flow import Pool, app_for, client_of, discover, work
    app = app_for(tmp_path, monkeypatch, Pool([work(n) for n in range(3)]))
    client = client_of(app)
    try:
        for connection in ADDED:
            app.state.adapters[connection] = app.state.adapters["fake"]
        outcomes = {}
        for connection in ADDED:
            _, _, _, run = discover(client, model_connection=connection)
            refused = app.state.store.conn.execute(
                "SELECT COUNT(*) FROM run_steps WHERE run_id = ? AND error_code = 'step_input_invalid'", (run["id"],)).fetchone()[0]
            outcomes[connection] = (run["status"], refused)
    finally:
        client.__exit__(None, None, None)
    assert outcomes == {connection: ("completed", 0) for connection in ADDED}
