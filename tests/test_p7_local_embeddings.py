"""Ollama and LM Studio paths through mocked OpenAI-compatible transports."""
import asyncio
import json

import httpx
import pytest

from deixis.documents import embeddings as e


@pytest.mark.parametrize("provider", ["ollama", "lm_studio"])
@pytest.mark.parametrize("failure", ["refused", "429", "413"])
def test_mid_batch_failure(provider, failure, monkeypatch):
    monkeypatch.setattr(e, "BATCH", 1)
    calls, sent = [], []
    def handler(request):
        calls.append(request)
        assert str(request.url) == e.LOCAL_URLS[provider] + "/embeddings"
        assert "authorization" not in request.headers
        if len(calls) == 1:
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [3, 4]}]})
        if failure == "refused":
            raise httpx.ConnectError("SYNTHETIC refused", request=request)
        return httpx.Response(int(failure), json={"error": {"message": "SYNTHETIC request too large" if failure == "413" else "SYNTHETIC limited"}})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(e.EmbeddingError, match="ConnectError" if failure == "refused" else f"HTTP {failure}"):
        asyncio.run(e.Embedder(provider, "synthetic").embed(client, ["first", "second"], "RETRIEVAL_DOCUMENT", on_sent=lambda: sent.append(1)))
    assert len(calls) == 2 and len(sent) == (1 if failure == "refused" else 2)


@pytest.mark.parametrize("provider", ["ollama", "lm_studio"])
def test_429_retries_and_counts_requests(provider):
    calls, sent = [], []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": {"message": "SYNTHETIC"}})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    budget = e.RateBudget()
    with pytest.raises(e.EmbeddingError, match="rate limited 4 times"):
        asyncio.run(e.Embedder(provider, "synthetic").embed(client, ["text"], "RETRIEVAL_QUERY", budget, on_sent=lambda: sent.append(1)))
    assert len(calls) == len(sent) == 4 and budget.rate_limited_waits == 3


@pytest.mark.parametrize("provider", ["ollama", "lm_studio"])
def test_success_returns_normalized_vectors_in_input_order(provider):
    def handler(request):
        assert json.loads(request.content) == {"model": "synthetic", "input": ["a", "b"]}
        return httpx.Response(200, json={"data": [{"index": 1, "embedding": [0, 2]}, {"index": 0, "embedding": [3, 4]}]})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    vectors = asyncio.run(e.Embedder(provider, "synthetic").embed(client, ["a", "b"], "RETRIEVAL_DOCUMENT"))
    assert list(vectors[0]) == pytest.approx([.6, .8]) and list(vectors[1]) == [0, 1]


@pytest.mark.parametrize("provider", ["ollama", "lm_studio"])
def test_extra_unindexed_embedding_is_a_typed_bad_reply(provider):
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        "data": [{"index": 0, "embedding": [1, 0]}, {"embedding": [0, 1]}],
    })))
    with pytest.raises(e.EmbeddingError, match="bad_reply"):
        asyncio.run(e.Embedder(provider, "synthetic").embed(client, ["a"], "RETRIEVAL_QUERY"))
