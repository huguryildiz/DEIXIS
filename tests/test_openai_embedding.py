"""Authenticated embedding behavior on synthetic keys and mocked HTTP only."""

import asyncio
import json
import socket

import httpx
import pytest

from connector_baseline import deny_network
from deixis.documents import embeddings as em
from test_semantic_retrieval import screened_research, score_sources

KEY = "SYNTHETIC-p7f-embedding-key"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", deny_network)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", deny_network)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", deny_network)


def embed(provider, texts, handler, budget=None):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await em.Embedder(provider, em.OPENAI_MODEL if provider == "openai" else em.MODEL).embed(
                client, texts, "RETRIEVAL_DOCUMENT", budget)
    return asyncio.run(go())


def test_openai_authenticated_batches_truncation_and_order(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    texts = ["x" * (em.MAX_CHARS + 7)] + [f"SYNTHETIC {i}" for i in range(em.BATCH)]
    requests = []
    def handler(request):
        body = json.loads(request.content)
        requests.append(request)
        assert request.method == "POST" and str(request.url) == "https://api.openai.com/v1/embeddings"
        assert request.headers.get_list("authorization") == [f"Bearer {KEY}"]
        assert "x-goog-api-key" not in request.headers
        assert body == {"model": em.OPENAI_MODEL, "input": [t[:em.MAX_CHARS] for t in texts[(len(requests)-1)*em.BATCH:len(requests)*em.BATCH]]}
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [i + 1, 2]}
                                                 for i in reversed(range(len(body["input"])))]})
    vectors = embed("openai", texts, handler)
    assert [len(json.loads(r.content)["input"]) for r in requests] == [em.BATCH, 1]
    for i, vector in enumerate(vectors):
        assert list(vector) == pytest.approx(list(em.unit([i % em.BATCH + 1, 2])))
        assert em.similarity(vector, vector) == pytest.approx(1)


def test_openai_401_once_without_retry(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    requests = []
    def handler(request):
        requests.append(request)
        assert request.headers.get_list("authorization") == [f"Bearer {KEY}"]
        return httpx.Response(401, json={"error": {"message": "SYNTHETIC invalid credential"}})
    with pytest.raises(em.EmbeddingError, match="^HTTP 401:"):
        embed("openai", ["SYNTHETIC"], handler, em.RateBudget())
    assert len(requests) == 1


def test_openai_missing_key_sends_nothing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(em.EmbeddingError, match="OPENAI_API_KEY is not set"):
        embed("openai", ["SYNTHETIC"], deny_network)


@pytest.mark.parametrize("provider", ["ollama", "lm_studio"])
def test_local_shared_route_has_no_authorization(provider, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    requests = []
    def handler(request):
        requests.append(request)
        assert str(request.url) == em.LOCAL_URLS[provider] + "/embeddings"
        assert "authorization" not in request.headers and "x-goog-api-key" not in request.headers
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [3, 4]}]})
    assert list(embed(provider, ["SYNTHETIC"], handler)[0]) == pytest.approx([.6, .8])
    assert len(requests) == 1


@pytest.mark.parametrize("provider", ["openai", "gemini"])
@pytest.mark.parametrize("status,budget", [(401, False), (429, False), (429, True)])
def test_reply_errors_redact_only_sent_key(provider, status, budget, monkeypatch):
    monkeypatch.setenv(em.KEY_ENVS[provider], KEY)
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, headers={"retry-after": "0"},
                              json={"error": {"message": f"SYNTHETIC echo {KEY}; unrelated-secret-kept"}})
    with pytest.raises(em.EmbeddingError, match=f"^HTTP {status}:") as error:
        embed(provider, ["SYNTHETIC"], handler, em.RateBudget() if budget else None)
    assert KEY not in str(error.value)
    assert "<redacted>" in str(error.value) and "unrelated-secret-kept" in str(error.value)
    assert len(requests) == (em.EMBED_RATE_LIMIT_RETRIES + 1 if budget else 1)


@pytest.mark.parametrize("status", [200, 401])
def test_openai_workflow_stores_similarity_or_redacted_failure(tmp_path, monkeypatch, status):
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    store, rid, run = screened_research(tmp_path)
    store.set_setting("semantic_search", {"provider": "openai", "model": em.OPENAI_MODEL})
    requests = []
    def handler(request):
        requests.append(request)
        assert str(request.url) == em.OPENAI_URL + "/embeddings"
        assert request.headers.get_list("authorization") == [f"Bearer {KEY}"]
        body = json.loads(request.content)
        assert body["model"] == em.OPENAI_MODEL
        if status == 401:
            return httpx.Response(401, json={"error": {"message": "SYNTHETIC echo " + KEY}})
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [1, 0] if "energy" in text or "enerji" in text else [0, 1]}
                                                 for i, text in reversed(list(enumerate(body["input"])))]})
    score_sources(store, rid, run, handler)
    step = store.existing_step(run["id"], "source_similarity")
    model = "openai:text-embedding-3-small"
    assert step["output"]["stored_model"] == model
    if status == 200:
        similarities = store.source_similarities(rid, run["scope_revision"], model)
        assert sorted(similarities.values()) == [0.0, 1.0]
        assert step["status"] == "succeeded" and len(requests) == 2
    else:
        assert (step["status"], step["error_code"]) == ("failed", "embedding_failed")
        assert json.loads(step["error_json"])["error"].startswith("HTTP 401:")
        assert not store.source_similarities(rid, run["scope_revision"], model) and len(requests) == 1
    # Include events and every row/output, not merely the failed step's displayed error.
    tables = [r[0] for r in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for table in tables:
        for row in store.conn.execute('SELECT * FROM "' + table.replace('"', '""') + '"'):
            assert KEY not in repr(tuple(row)), table
    store.conn.close()
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert KEY.encode() not in path.read_bytes(), path
