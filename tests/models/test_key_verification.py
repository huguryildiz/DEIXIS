"""Key verification: bad characters refused, refusal versus unchecked, a refused first step, per-key health caches and
a key deleted during a research.

In-memory keychain, mocked HTTP and FakeAdapter. Passing shows the stored key states, not live provider answers.
"""

import asyncio
import httpx
import json
import os
import pytest
import time
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.keys import credentials
from deixis.keys import key_verification
from deixis.models import anthropic_api
from deixis.models import deepseek
from deixis.models import gemini
from deixis.models import openai_api
from deixis.models import openai_compat
from fakes import FakeAdapter
from test_api_flow import app_for
from test_api_flow import create
from test_api_flow import fake_fetch
from test_api_flow import openalex_client
from test_api_flow import session
from test_api_flow import sw_settings
from test_api_flow import wait_run


GLM_LIST = openai_compat.GLM.list_url


BAD_KEYS = {"nul": "abcd\x00efgh1234", "zero-width": "abcd​efgh1234", "bom": "abcd﻿fgh12345", "s-cedilla": "abcdşefgh1234",
            "emoji": "abcd\U0001F600efgh12", "too-long": "a" * 401, "space": "abcd efgh1234", "newline": "abcdefgh12\n34",
            "tab": "abcdefgh12\t34"}


class Wire:
    """A mutable stand-in for the network: `answer` is called with each request and returns a response or raises."""

    def __init__(self):
        self.answer = lambda request: httpx.Response(200, json={"models": [], "data": []})
        self.urls: list[str] = []

    def __call__(self, request):
        self.urls.append(str(request.url))
        return self.answer(request)


@pytest.fixture
def wire():
    return Wire()


@pytest.fixture
def client(tmp_path, wire):
    adapters = {"fake": FakeAdapter(), "glm": openai_compat.OpenAICompatAdapter(
        openai_compat.GLM, client=httpx.AsyncClient(transport=httpx.MockTransport(wire)))}
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters=adapters,
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(wire)), start_worker=False,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as c:
        c.headers["x-deixis-csrf"] = c.get("/api/session").json()["csrf_token"]
        yield c


def fragment(value: str) -> str:
    return "".join(c for c in value if c.isalnum())[:8]


@pytest.mark.parametrize("env", ["GEMINI_API_KEY"])
@pytest.mark.parametrize("name", ["nul"])
def test_a_key_with_a_control_invisible_or_non_ascii_character_is_refused_before_anything_is_stored(
        client, memory_keychain, wire, monkeypatch, env, name):
    monkeypatch.delenv(env, raising=False)
    value = BAD_KEYS[name]
    response = client.put(f"/api/credentials/{env}", json={"value": value})
    assert response.status_code == 422
    assert not wire.urls and memory_keychain.items == {} and not os.environ.get(env)  # nothing sent, stored or exported
    assert value not in response.text and value.strip() not in response.text and "input" not in response.text  # E3: nothing echoed
    assert credentials.status(env)["configured"] is False


MATRIX = [  # what the test request met -> (stored, verification, test status)
    ("offline", lambda r: (_ for _ in ()).throw(httpx.ConnectError("offline", request=r)), True, "pending", "failed"),
    ("timeout", lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=r)), True, "pending", "failed"),
    ("500", lambda r: httpx.Response(500), True, "pending", "failed"),
    ("429", lambda r: httpx.Response(429, headers={"retry-after": "60"}, json={"error": {"code": "insufficient_quota"}}), True, "pending", "no_credit"),
    ("401", lambda r: httpx.Response(401), False, "rejected", "rejected"),
    ("403", lambda r: httpx.Response(403), False, "rejected", "rejected"),
    ("400", lambda r: httpx.Response(400), False, "rejected", "rejected"),
    ("200", lambda r: httpx.Response(200, json={}), True, "verified", "ok"),
]


@pytest.mark.parametrize("env", ["GEMINI_API_KEY"])
@pytest.mark.parametrize("name,answer,stored,verification,test_status", MATRIX[4:5] + MATRIX[7:], ids=[m[0] for m in MATRIX[4:5] + MATRIX[7:]])
def test_only_a_refusal_keeps_a_key_out_and_an_unchecked_key_is_saved_not_verified(
        client, memory_keychain, wire, monkeypatch, env, name, answer, stored, verification, test_status):
    monkeypatch.delenv(env, raising=False)
    wire.answer = answer
    response = client.put(f"/api/credentials/{env}", json={"value": "some-key-0123456789"})
    assert ("some-key-0123456789" in str(memory_keychain.items)) is stored
    if not stored:
        assert response.status_code == 422 and "some-key" not in response.text and not os.environ.get(env)
        return
    body = response.json()
    assert (body["test"]["status"], body["test"]["verification"], body["key"]["verification"]) == (test_status, verification, verification)
    assert body["key"]["configured"] is True
    if name == "429":  # the quota information is kept for the UI
        assert body["test"]["kind"] == "quota_exhausted" and body["test"]["http_status"] == 429 and body["test"]["reset_at"]


def adapter_on(wire):
    return openai_compat.OpenAICompatAdapter(openai_compat.GLM, client=httpx.AsyncClient(transport=httpx.MockTransport(wire)))


def glm_answer(chat):
    return lambda request: httpx.Response(404) if str(request.url) == GLM_LIST else chat(request)


def completion(request):
    return httpx.Response(200, json={"id": "c1", "model": "glm-5.1", "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]})


async def run_one(adapter):
    return await adapter.run_step("BASE", "DEV", "MSG", {"type": "object"}, "glm-5.1")


@pytest.mark.parametrize("code", [401])
def test_a_refused_first_step_marks_the_key_rejected(wire, monkeypatch, code):
    asyncio.run(_refused_step(wire, monkeypatch, code))


async def _refused_step(wire, monkeypatch, code):
    monkeypatch.setenv("ZAI_API_KEY", "glm-key-0123456789")
    wire.answer = glm_answer(lambda request: httpx.Response(code, json={"error": "no"}))
    adapter = adapter_on(wire)
    assert (await run_one(adapter)).status == "failed"
    after = await adapter.health(refresh=True)
    assert after["ready"] is False and after["verification"] == "rejected" and after["reason_code"] == "auth_failed"
    assert credentials.status("ZAI_API_KEY")["verification"] == "rejected"
    monkeypatch.setenv("ZAI_API_KEY", "glm-new-key-0123456")  # a new key starts over
    assert (await adapter.health(refresh=True))["verification"] == "pending"


MISTRAL = openai_compat.CONNECTIONS["mistral"]


OPENROUTER = openai_compat.CONNECTIONS["openrouter"]


def listed_and(chat, spec):
    """A provider whose model list answers 200 (and, for OpenRouter, to any key); `chat` answers the step."""
    return lambda request: (httpx.Response(200, json={"data": [{"id": "m-1", "supported_parameters": ["structured_outputs"]}]})
                            if str(request.url) == spec.list_url else chat(request))


def adapter_for(spec, wire):
    return openai_compat.OpenAICompatAdapter(spec, client=httpx.AsyncClient(transport=httpx.MockTransport(wire)))


async def _step(adapter, model="m-1"):
    return await adapter.run_step("BASE", "DEV", "MSG", {"type": "object"}, model)


def test_the_flow_refuses_a_connection_whose_key_a_step_refused(tmp_path, wire, monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-key-0123456789")
    chats: list[str] = []
    wire.answer = listed_and(lambda request: (chats.append(str(request.url)), httpx.Response(401))[1], MISTRAL)
    adapter = adapter_for(MISTRAL, wire)
    asyncio.run(_step(adapter))  # the refusal
    assert len(chats) == 1
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        rid = create(client, requested_model="m-1")
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        run = wait_run(client, rid, run["id"])[1]
    assert (run["status"], run["pause_reason"]) == ("paused", "model_connection_not_ready") and len(chats) == 1


def test_a_cached_answer_is_not_served_to_a_different_key(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "old-key-0123456789")
    list_started, release = asyncio.Event(), asyncio.Event()

    async def handler(request):
        if request.headers["authorization"] == "Bearer old-key-0123456789":
            list_started.set()
            await release.wait()  # the old key's list request is in flight while the key is changed
            return httpx.Response(200, json={"data": [{"id": "m-1"}]})
        return httpx.Response(401)

    adapter = adapter_for(MISTRAL, handler)

    async def go():
        old = asyncio.create_task(adapter.health(refresh=True))
        await list_started.wait()
        monkeypatch.setenv("MISTRAL_API_KEY", "new-key-0123456789")
        assert (await adapter.health())["ready"] is False
        release.set()
        assert (await old)["ready"] is True  # the answer was right for the key it was asked with
        assert (await adapter.health())["ready"] is False  # but it is cached for that key only
    asyncio.run(go())


def gemini_body(tag):
    return {"models": [{"name": f"models/gemini-3-{tag}", "supportedGenerationMethods": ["generateContent"]}]}


def anthropic_body(tag):
    return {"data": [{"id": f"claude-{tag}", "capabilities": {"structured_outputs": {"supported": True}}}]}


def openai_body(tag):
    return {"data": [{"id": f"gpt-5-{tag}"}]}


def deepseek_body(tag):
    return {"data": [{"id": f"deepseek-{tag}"}]}


# (adapter class, key variable, body of a model list for a key tag)
CASES = {
    "gemini": (gemini.GeminiAdapter, gemini.KEY_ENV, gemini_body),
    "anthropic": (anthropic_api.AnthropicAdapter, anthropic_api.KEY_ENV, anthropic_body),
    "openai": (openai_api.OpenAIAdapter, openai_api.KEY_ENV, openai_body),
    "deepseek": (deepseek.DeepSeekAdapter, deepseek.KEY_ENV, deepseek_body),
}


class Server:
    """A model-list endpoint whose answer names the key in the environment when the request arrived."""

    def __init__(self, env, body):
        self.env, self.body, self.requests, self.status = env, body, 0, 200
        self.gate: asyncio.Event | None = None
        self.gated_once = False

    async def __call__(self, request):
        self.requests += 1
        tag, status = os.environ.get(self.env, "none"), self.status  # what is true when the request arrives
        if self.gate is not None and not self.gated_once:
            self.gated_once = True
            await self.gate.wait()
        return httpx.Response(status, json=self.body(tag)) if status == 200 else httpx.Response(status, json={})


def build(name, monkeypatch, key="aaa"):
    cls, env, body = CASES[name]
    monkeypatch.setenv(env, key)
    server = Server(env, body)
    return cls(client=httpx.AsyncClient(transport=httpx.MockTransport(server))), server, env


def ids(status):
    return [m["id"] for m in status.get("models", [])]


@pytest.mark.parametrize("name", ["anthropic"])
def test_deleted_key_never_brings_the_old_ready_back(name, monkeypatch):
    adapter, server, env = build(name, monkeypatch)

    async def scenario():
        assert (await adapter.health())["ready"] is True
        monkeypatch.delenv(env)
        assert (await adapter.health())["reason_code"] == "needs_key"  # a plain read after the delete
        assert (await adapter.health(refresh=True))["ready"] is False
        before = server.requests
        monkeypatch.setenv(env, "aaa")  # the same key typed again: the cache was dropped by the check, so the service is asked
        assert (await adapter.health())["ready"] is True
        assert server.requests == before + 1

    asyncio.run(scenario())


@pytest.mark.parametrize("name", ["anthropic"])
def test_answers_carry_no_key_fingerprint(name, monkeypatch):
    adapter, _, _ = build(name, monkeypatch)
    status = asyncio.run(adapter.health(refresh=True))
    assert key_verification.fingerprint("aaa") not in repr(status) and "fingerprint" not in repr(status)


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


def attached_research_on(client, connection):
    rid = create(client, source_scope="attached", model_connection=connection)
    from helpers import make_pdf
    client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC molecule release schedule"]), "application/pdf")})
    return rid


