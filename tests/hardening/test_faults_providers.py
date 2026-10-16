"""P9 H3 fault injection, provider and guard classes (inventory P1, P2, P4, P5, O2, O3).

Model-free; every transport is mocked. Passing shows how the connectors and the fast-path discovery flow classify and
store a provider fault, and the wording of the guard refusals. It does not show live provider behavior.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from test_api_flow import create, fake_fetch, openalex_client, session, sw_settings, wait_run
from test_providers import ALL, key_for, run
from fakes import FakeAdapter

LABELS = (Path(__file__).parents[2] / "apps" / "web" / "src" / "labels.ts").read_text(encoding="utf-8")


def label_sentence(key):
    """The sentence `labels.ts` gives a pause reason. Checks presence in the source text, not rendering."""
    match = re.search(rf"^\s*{re.escape(key)}:\s*'(.+)',\s*$", LABELS, re.M)
    return match.group(1) if match else None


def faulty(mode):
    """Every request fails the same way: `timeout`, `malformed` (not JSON) or `server` (500)."""
    def answer(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("SYNTHETIC slow provider", request=request)
        if mode == "malformed":
            return httpx.Response(200, text="<html>SYNTHETIC not json</html>")
        return httpx.Response(500, text="SYNTHETIC server error")
    return httpx.AsyncClient(transport=httpx.MockTransport(answer))


def fault_run(tmp_path, mode):
    """One fast-path discovery run through the API whose every provider request fails as `mode` says."""
    app = create_app(sw_settings(tmp_path), adapters={"fake": FakeAdapter()}, http_client=faulty(mode),
                     fetcher=fake_fetch, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        session(client)
        rid = create(client, providers=["openalex"])
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        return wait_run(client, rid, run_id)


def step_statuses(run):
    return {s["operation_key"]: s["status"] for s in run["steps"] if s["operation_key"].startswith("search:")}


@pytest.mark.parametrize("provider", ALL)
def test_p5_empty_200_body_is_a_parse_error_for_every_provider(provider):
    """P5: HTTP 200 with an empty body is `parse_error` with no delivery class, never zero results."""
    outcome, _ = run(provider, lambda r: httpx.Response(200, content=b""), key=key_for(provider))
    assert (outcome.status, outcome.delivery_class) == ("parse_error", None)
    assert outcome.records == []


def test_p1_provider_timeout_stops_the_run_as_provider_timeout(tmp_path):
    """P1: every search times out -> search_runs `timeout`, run paused `provider_timeout`."""
    view, run = fault_run(tmp_path, "timeout")
    assert {s["status"] for s in view["search_runs"]} == {"timeout"}
    assert (run["status"], run["pause_reason"]) == ("paused", "provider_timeout"), run
    assert set(step_statuses(run).values()) == {"outcome_unknown"}
    assert label_sentence("provider_timeout")


def test_p4_malformed_json_body_stops_the_run_as_provider_parse_error(tmp_path):
    """P4: every search answers 200 with a body that is not JSON -> `parse_error`, run paused `provider_parse_error`."""
    view, run = fault_run(tmp_path, "malformed")
    assert {s["status"] for s in view["search_runs"]} == {"parse_error"}
    assert (run["status"], run["pause_reason"]) == ("paused", "provider_parse_error"), run
    assert label_sentence("provider_parse_error")


def test_p2_provider_5xx_is_failed_on_the_search_run_and_outcome_unknown_on_the_step(tmp_path):
    """P2: every search answers 500 -> search_runs `failed`, run paused `provider_failed`, step `outcome_unknown`
    (a 5xx after the request was sent leaves its delivery unknown)."""
    view, run = fault_run(tmp_path, "server")
    assert {s["status"] for s in view["search_runs"]} == {"failed"}
    assert (run["status"], run["pause_reason"]) == ("paused", "provider_failed"), run
    assert set(step_statuses(run).values()) == {"outcome_unknown"}
    assert label_sentence("provider_failed")


# ---- O2, O3: the wording of the guard refusals ----------------------------------------------------------------


def guard_app(tmp_path, **kwargs):
    return create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters={"fake": FakeAdapter()},
                      http_client=openalex_client(), fetcher=fake_fetch, extra_hosts=("testserver",), **kwargs)


BODY = {"question": "x question", "model_connection": "fake"}


def test_o2_missing_or_wrong_csrf_token_is_refused_with_one_sentence(tmp_path):
    """O2: a mutation without the CSRF header, or with a wrong one, is 403 with one sentence."""
    with TestClient(guard_app(tmp_path, trusted_clients=("testclient",))) as client:
        client.get("/api/session")  # sets the cookie; no header yet
        for headers in ({}, {"x-deixis-csrf": "wrong-token"}):
            response = client.post("/api/researches", json=BODY, headers=headers)
            assert (response.status_code, response.json()) == (403, {"detail": "Missing or invalid CSRF token"})


def test_o3_unknown_host_and_foreign_origin_are_refused_with_one_sentence(tmp_path):
    """O3: a Host outside the allowlist and a foreign Origin are each 403 with one sentence."""
    with TestClient(guard_app(tmp_path, trusted_clients=("testclient",))) as client:
        token = client.get("/api/session").json()["csrf_token"]
        response = client.get("/api/health", headers={"host": "evil.example"})
        assert (response.status_code, response.json()) == (403, {"detail": "Host not allowed"})
        response = client.post("/api/researches", json=BODY, headers={"x-deixis-csrf": token, "origin": "http://evil.example"})
        assert (response.status_code, response.json()) == (403, {"detail": "Origin not allowed"})


def test_o3_a_peer_that_is_not_loopback_is_refused_with_one_sentence(tmp_path):
    """O3: the test client's peer address is "testclient", which is not loopback unless trusted."""
    with TestClient(guard_app(tmp_path)) as client:
        response = client.get("/api/health")
        assert (response.status_code, response.json()) == (403, {"detail": "Only local connections are accepted"})
