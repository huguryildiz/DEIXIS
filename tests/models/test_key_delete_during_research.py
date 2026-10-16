"""Deleting a key while researches run (E13).

Nothing stops the delete. The confirmation asks `GET /api/credentials/{env}/in-use` how many researches are queued or
running with a model connection or source that reads the key. A step already sent finishes with the key it was sent
with; the next step finds the key gone (or the shell's key back) and a run stops there with a reason the timeline shows.

The keychain is the in-memory backend (conftest) and every API is a mocked httpx transport or a scripted adapter. These
show the application's handling, not that a real provider or keychain behaves the same.
"""

import asyncio
import os
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis import credentials
from deixis.api.app import create_app
from deixis.models import gemini
from fakes import FakeAdapter
from test_api_flow import attached_research, create, fake_fetch, openalex_client, session, sw_settings, wait_run

SAVED = "gemini-saved-key-0123456789"
SHELL = "gemini-shell-key-0123456789"


class KeyedAdapter(FakeAdapter):
    """Reads `GEMINI_API_KEY` the way the real Gemini connection does: when a check or a step starts, not when it ends."""

    connection = "gemini"

    def __init__(self, **kwargs):
        super().__init__(models=["fake-model"], **kwargs)
        self.keys_sent: list[str | None] = []

    async def health(self, refresh=False):
        key = os.environ.get("GEMINI_API_KEY")
        status = await super().health(refresh)
        return status | {"connection": "gemini", "ready": bool(key), "key_configured": bool(key)} | (
            {} if key else {"reason": "Add a Gemini API key in Settings", "reason_code": "needs_key"})

    async def run_step(self, *args, **kwargs):
        self.keys_sent.append(os.environ.get("GEMINI_API_KEY"))  # what this step is sent with
        return await super().run_step(*args, **kwargs)


def app_with(tmp_path, adapter):
    return create_app(sw_settings(tmp_path), adapters={"gemini": adapter}, http_client=openalex_client(200), fetcher=fake_fetch,
                      extra_hosts=("testserver",), trusted_clients=("testclient",))


def in_use(client, env):
    response = client.get(f"/api/credentials/{env}/in-use")
    assert response.status_code == 200, response.text
    return response.json()["running_researches"]


def wait_until(condition, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError("condition not reached")


def test_the_count_covers_researches_with_a_running_run_that_use_the_key(tmp_path, monkeypatch, memory_keychain):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    adapter = KeyedAdapter(delay=0.5)
    with TestClient(app_with(tmp_path, adapter)) as client:
        session(client)
        assert client.put("/api/credentials/GEMINI_API_KEY", json={"value": SAVED}).status_code == 200
        busy = create(client, model_connection="gemini")
        create(client, model_connection="gemini")  # a second research that never runs
        assert (in_use(client, "GEMINI_API_KEY"), in_use(client, "OPENALEX_API_KEY")) == (0, 0)  # nothing runs yet
        run = client.post(f"/api/researches/{busy}/runs", json={"kind": "discovery"}).json()
        wait_run(client, busy, run["id"], statuses=("running",))
        assert in_use(client, "GEMINI_API_KEY") == 1  # the idle research is not counted
        assert in_use(client, "OPENALEX_API_KEY") == 1  # a source the running research searches
        assert (in_use(client, "OPENAI_API_KEY"), in_use(client, "DEEPSEEK_API_KEY"), in_use(client, "SCOPUS_API_KEY")) == (0, 0, 0)
        assert client.get("/api/credentials/NOT_A_KEY/in-use").status_code == 404
        assert client.post(f"/api/runs/{run['id']}/cancel").status_code in (200, 202)
        wait_run(client, busy, run["id"], statuses=("cancelled",))
        assert in_use(client, "GEMINI_API_KEY") == 0 and in_use(client, "OPENALEX_API_KEY") == 0  # a finished run is not counted


def test_a_connection_that_shares_a_key_is_counted_for_that_key(tmp_path, monkeypatch, memory_keychain):
    """Muse Spark and Muse Glimmer read one key: a research on either counts."""
    from deixis.models import openai_compat
    adapters = {"muse_glimmer": FakeAdapter(models=["fake-model"], delay=0.5)}
    app = create_app(sw_settings(tmp_path), adapters=adapters, http_client=openalex_client(200), fetcher=fake_fetch,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    assert openai_compat.CONNECTIONS["muse_glimmer"].key_env == "MODEL_API_KEY"
    with TestClient(app) as client:
        session(client)
        rid = create(client, model_connection="muse_glimmer")
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        wait_run(client, rid, run["id"], statuses=("running",))
        assert in_use(client, "MODEL_API_KEY") == 1
        client.post(f"/api/runs/{run['id']}/cancel")
        wait_run(client, rid, run["id"], statuses=("cancelled",))


def answer_run(client, rid):
    return client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()


def test_a_step_already_sent_finishes_and_the_next_step_stops_the_run_without_the_key(tmp_path, monkeypatch, memory_keychain):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    adapter = KeyedAdapter(delay=1.0)
    with TestClient(app_with(tmp_path, adapter)) as client:
        session(client)
        assert client.put("/api/credentials/GEMINI_API_KEY", json={"value": SAVED}).status_code == 200
        rid = attached_research_on(client, "gemini")
        run = answer_run(client, rid)
        wait_until(lambda: adapter.keys_sent)  # the step is in flight
        assert in_use(client, "GEMINI_API_KEY") == 1
        removed = client.delete("/api/credentials/GEMINI_API_KEY")
        assert removed.status_code == 200 and removed.json()["key"]["configured"] is False
        view, finished = wait_run(client, rid, run["id"])
        # The step sent with the key it had; the run completed and its answer is kept.
        assert adapter.keys_sent == [SAVED]
        assert finished["status"] == "completed" and len(view["answers"]) == 1
        # The next step: no key and no shell key, so nothing is sent and the run stops with a reason the timeline shows.
        second = answer_run(client, rid)
        view, stopped = wait_run(client, rid, second["id"])
        assert (stopped["status"], stopped["pause_reason"]) == ("paused", "model_connection_not_ready")
        assert adapter.keys_sent == [SAVED]  # nothing was sent for the second run
        assert stopped["error"]["connection"] == "gemini" and stopped["error"]["error_kind"] == "needs_key"
        # Putting the key back lets the same run go on.
        assert client.put("/api/credentials/GEMINI_API_KEY", json={"value": SAVED}).status_code == 200
        client.post(f"/api/runs/{second['id']}/resume")
        view, resumed = wait_run(client, rid, second["id"])
        assert resumed["status"] == "completed" and adapter.keys_sent == [SAVED, SAVED]


def test_the_next_step_runs_with_the_shell_key_when_one_is_set(tmp_path, monkeypatch, memory_keychain):
    monkeypatch.setenv("GEMINI_API_KEY", SHELL)
    credentials.load_into_environment()  # remembers the shell's value as the one to go back to
    adapter = KeyedAdapter(delay=1.0)
    with TestClient(app_with(tmp_path, adapter)) as client:
        session(client)
        assert client.put("/api/credentials/GEMINI_API_KEY", json={"value": SAVED}).status_code == 200
        rid = attached_research_on(client, "gemini")
        run = answer_run(client, rid)
        wait_until(lambda: adapter.keys_sent)
        removed = client.delete("/api/credentials/GEMINI_API_KEY").json()["key"]
        assert (removed["source"], removed["configured"]) == ("environment", True)  # the shell's key is back
        wait_run(client, rid, run["id"])
        second = answer_run(client, rid)
        view, finished = wait_run(client, rid, second["id"])
        assert finished["status"] == "completed"
        assert adapter.keys_sent == [SAVED, SHELL]  # the step in flight kept its key; the next one was sent with the shell's


def attached_research_on(client, connection):
    rid = create(client, source_scope="attached", model_connection=connection)
    from helpers import make_pdf
    client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC molecule release schedule"]), "application/pdf")})
    return rid


# ---- the real Gemini connection: the key is read when the step starts -----------------------------------------------


def gemini_answer():
    return httpx.Response(200, json={"modelVersion": "gemini-3.8-flash", "responseId": "r1",
                                     "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "{}"}]}}]})


def test_the_gemini_connection_sends_its_step_with_the_key_it_had_and_the_next_without(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", SAVED)
    seen = []

    def handler(request):
        seen.append(request.headers["x-goog-api-key"])
        monkeypatch.delenv("GEMINI_API_KEY")  # deleted while this request is on the wire
        return gemini_answer()

    adapter = gemini.GeminiAdapter(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    async def go():
        first = await adapter.run_step("b", "d", "m", {}, "gemini-3.8-flash")
        second = await adapter.run_step("b", "d", "m", {}, "gemini-3.8-flash")
        return first, second

    first, second = asyncio.run(go())
    assert (first.status, seen) == ("completed", [SAVED])
    assert (second.status, second.error_kind, second.delivery_class) == ("unavailable", "needs_key", "before_send")
    assert "GEMINI_API_KEY is not set" in second.error and seen == [SAVED]  # no second request


def test_the_gemini_connection_uses_the_shell_key_for_the_next_step(monkeypatch, memory_keychain):
    monkeypatch.setenv("GEMINI_API_KEY", SHELL)
    credentials.load_into_environment()
    credentials.save("GEMINI_API_KEY", SAVED)
    seen = []

    def handler(request):
        seen.append(request.headers["x-goog-api-key"])
        if len(seen) == 1:
            credentials.delete("GEMINI_API_KEY")  # deleted while the first request is on the wire
        return gemini_answer()

    adapter = gemini.GeminiAdapter(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    async def go():
        return [await adapter.run_step("b", "d", "m", {}, "gemini-3.8-flash") for _ in range(2)]

    results = asyncio.run(go())
    assert [r.status for r in results] == ["completed", "completed"] and seen == [SAVED, SHELL]
