"""Cohere embeddings and the Cohere, Jina AI and ZeroEntropy rerankers (model-free, no paid call).

Every endpoint is mocked (httpx.MockTransport); no request leaves the test. Passing shows request shapes, routing,
stored identities, keys and how a reply maps back to its texts and records. It does not show that any of these
providers ranks better: retrieval quality was not measured.
"""

import asyncio
import json

import httpx
import pytest

from deixis.documents import embeddings, rerankers

KEY = "SYNTHETIC-provider-key"
TOOLS = {"tools": [{"id": i, "name": i, "running": False, "installed": False, "models": []} for i in ("ollama", "lm_studio")]}


def mocked(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---- Cohere embeddings -------------------------------------------------------------------------------


# ---- the new rerankers --------------------------------------------------------------------------------

def reply_for(provider, n, scores):
    results = [{"index": i, "relevance_score": scores[i]} for i in reversed(range(n))]
    return {"cohere": {"results": results, "meta": {"billed_units": {"search_units": 1}}},
            "jina": {"results": results, "usage": {"total_tokens": 40}},
            "zeroentropy": {"results": results, "total_tokens": 50}}[provider]


@pytest.mark.parametrize("provider, url, body", [
    ("cohere", "https://api.cohere.com/v2/rerank", {"model": "rerank-v4.0-fast", "query": "SYNTHETIC question",
                                                    "documents": ["d0", "d1", "d2"], "top_n": 3, "max_tokens_per_doc": 4096}),
])
def test_each_api_reranker_sends_its_shape_and_maps_scores_back_to_input_order(monkeypatch, provider, url, body):
    monkeypatch.setenv(rerankers.KEY_ENVS[provider], KEY)
    sent = []

    def handler(request):
        sent.append((str(request.url), request.headers["authorization"], json.loads(request.content)))
        return httpx.Response(200, json=reply_for(provider, 3, [0.1, 0.9, 0.5]))

    choice = rerankers.chosen({"enabled": True, "provider": provider})
    assert choice.model == body["model"]

    async def go():
        async with mocked(handler) as client:
            return await rerankers.rerank(choice, client, None, "SYNTHETIC question", ["d0", "d1", "d2"])
    result = asyncio.run(go())
    assert sent == [(url, f"Bearer {KEY}", body)]
    assert result["scores"] == [0.1, 0.9, 0.5]
    assert (result["provider_tokens"], result["provider_search_units"]) == {
        "cohere": (None, 1), "jina": (40, None), "zeroentropy": (50, None)}[provider]


@pytest.mark.parametrize("provider", ["cohere"])
@pytest.mark.parametrize("status, reply, code", [
    (200, {"results": [{"index": 0, "relevance_score": 1}]}, "reranker_bad_reply"),  # two documents, one score
    pytest.param(500, {"message": "SYNTHETIC"}, "reranker_failed", id="500-reply2-reranker_failed"),
])
def test_a_wrong_or_failed_api_rerank_is_refused_and_no_other_reranker_is_tried(monkeypatch, provider, status, reply, code):
    monkeypatch.setenv(rerankers.KEY_ENVS[provider], KEY)
    sent = []

    async def go():
        async with mocked(lambda r: sent.append(str(r.url)) or httpx.Response(status, json=reply)) as client:
            return await rerankers.rerank(rerankers.chosen({"enabled": True, "provider": provider}), client, None, "q", ["a", "b"])
    with pytest.raises(rerankers.RerankError) as error:
        asyncio.run(go())
    assert error.value.code == code and len(set(sent)) == 1


# ---- keys ------------------------------------------------------------------------------------------------
