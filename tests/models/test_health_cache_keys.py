"""A model connection's cached health belongs to the key it was made with (E7): deleting or changing the key never brings an
earlier 'ready' back, a fresh check that fails drops the old answer, and a check that began under an older key writes nothing
once a newer key is saved. Mocked httpx transports: these show the adapters' cache rules, not any provider's behavior."""

import asyncio
import os

import httpx
import pytest

from deixis import key_verification
from deixis.models import anthropic_api, deepseek, gemini, openai_api


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


@pytest.mark.parametrize("name", CASES)
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


@pytest.mark.parametrize("name", CASES)
def test_cached_answer_is_not_used_for_another_key(name, monkeypatch):
    adapter, server, env = build(name, monkeypatch)

    async def scenario():
        first = await adapter.health()
        monkeypatch.setenv(env, "bbb")
        second = await adapter.health()  # no refresh asked, but this is another key
        assert ids(first) != ids(second) and server.requests == 2
        assert await adapter.health() is second and server.requests == 2  # the new answer is cached for the new key

    asyncio.run(scenario())


@pytest.mark.parametrize("name", CASES)
def test_a_failed_fresh_check_replaces_the_old_ready(name, monkeypatch):
    adapter, server, env = build(name, monkeypatch)

    async def scenario():
        assert (await adapter.health())["ready"] is True
        server.status = 429
        assert (await adapter.health(refresh=True))["ready"] is False
        server.status = 200
        before = server.requests
        assert (await adapter.health())["ready"] is False  # the failed answer is the cached one, not the old ready
        assert server.requests == before
        assert (await adapter.health(refresh=True))["ready"] is True

    asyncio.run(scenario())


@pytest.mark.parametrize("name", CASES)
def test_a_check_begun_under_an_older_key_does_not_write_its_result(name, monkeypatch):
    adapter, server, env = build(name, monkeypatch, key="old")

    async def scenario():
        server.gate = asyncio.Event()
        slow = asyncio.create_task(adapter.health(refresh=True))  # waits inside the request, under the old key
        while server.requests == 0:
            await asyncio.sleep(0)
        monkeypatch.setenv(env, "new")  # a newer key is saved, and its check finishes first
        fresh = await adapter.health(refresh=True)
        server.gate.set()
        old_answer = await slow
        assert ids(old_answer) != ids(fresh)
        before = server.requests
        assert await adapter.health() is fresh and server.requests == before  # the older result did not overwrite it

    asyncio.run(scenario())


@pytest.mark.parametrize("name", CASES)
def test_answers_carry_no_key_fingerprint(name, monkeypatch):
    adapter, _, _ = build(name, monkeypatch)
    status = asyncio.run(adapter.health(refresh=True))
    assert key_verification.fingerprint("aaa") not in repr(status) and "fingerprint" not in repr(status)


@pytest.mark.parametrize("name", CASES)
def test_a_slow_success_with_the_same_key_does_not_cover_a_newer_refusal(name, monkeypatch):
    adapter, server, env = build(name, monkeypatch)

    async def scenario():
        server.gate = asyncio.Event()
        slow = asyncio.create_task(adapter.health(refresh=True))  # a check that will say ready, held inside its request
        while server.requests == 0:
            await asyncio.sleep(0)
        server.status = 401  # the key is refused; a newer check says so
        assert (await adapter.health(refresh=True))["ready"] is False
        server.gate.set()
        assert (await slow)["ready"] is False  # its caller gets the newer answer too (see the next test)
        before = server.requests
        assert (await adapter.health())["ready"] is False  # but the cache keeps the newer answer
        assert server.requests == before

    asyncio.run(scenario())


@pytest.mark.parametrize("name", CASES)
def test_a_check_that_lost_the_race_returns_the_newer_answer_to_its_caller(name, monkeypatch):
    adapter, server, env = build(name, monkeypatch)

    async def scenario():
        server.gate = asyncio.Event()
        slow = asyncio.create_task(adapter.health(refresh=True))  # says ready, held inside its request
        while server.requests == 0:
            await asyncio.sleep(0)
        server.status = 401
        newer = await adapter.health(refresh=True)
        assert newer["ready"] is False
        server.gate.set()
        assert await slow is newer  # not the stale "ready": a concurrent research must see the newest answer

    asyncio.run(scenario())


@pytest.mark.parametrize("name", CASES)
def test_key_changed_forgets_the_cached_answer_and_stops_a_check_under_way_from_writing(name, monkeypatch):
    adapter, server, env = build(name, monkeypatch)

    async def scenario():
        server.status = 429
        assert (await adapter.health())["ready"] is False  # cached for the key
        server.status = 200
        adapter.key_changed("SOME_OTHER_KEY")
        assert (await adapter.health())["ready"] is False  # another key's change leaves it alone
        adapter.key_changed(env)  # the same key saved again
        assert (await adapter.health())["ready"] is True
        server.gate, server.gated_once = asyncio.Event(), False
        asked = server.requests
        slow = asyncio.create_task(adapter.health(refresh=True))
        while server.requests == asked:
            await asyncio.sleep(0)
        adapter.key_changed(env)
        server.gate.set()
        await slow
        before = server.requests
        await adapter.health()
        assert server.requests == before + 1  # the check under way wrote nothing

    asyncio.run(scenario())
