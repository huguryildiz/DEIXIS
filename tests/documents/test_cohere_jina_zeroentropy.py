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
from deixis.keys import credentials

KEY = "SYNTHETIC-provider-key"
TOOLS = {"tools": [{"id": i, "name": i, "running": False, "installed": False, "models": []} for i in ("ollama", "lm_studio")]}


def mocked(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---- Cohere embeddings -------------------------------------------------------------------------------

def test_cohere_embeds_with_search_types_never_truncates_and_reports_billed_tokens(monkeypatch):
    monkeypatch.setenv("COHERE_API_KEY", KEY)
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append((str(request.url), request.headers["authorization"], body))
        vectors = [[3.0, 4.0] + [0.0] * (embeddings.COHERE_DIMENSIONS - 2) for _ in body["texts"]]
        return httpx.Response(200, json={"embeddings": {"float": vectors}, "meta": {"billed_units": {"input_tokens": 5}}})

    async def go():
        embedder = embeddings.Embedder("cohere", embeddings.COHERE_MODEL)
        report = {}
        async with mocked(handler) as client:
            query = await embedder.embed(client, ["q"], "RETRIEVAL_QUERY", report=report)
            docs = await embedder.embed(client, ["d"] * 100, "RETRIEVAL_DOCUMENT", report=report)
        return query, docs, report
    query, docs, report = asyncio.run(go())
    assert sent[0][0] == "https://api.cohere.com/v2/embed" and sent[0][1] == f"Bearer {KEY}"
    assert sent[0][2] == {"model": "embed-v5.0-fast", "texts": ["q"], "embedding_types": ["float"], "truncate": "NONE",
                          "input_type": "search_query", "output_dimension": embeddings.COHERE_DIMENSIONS}
    assert [b["input_type"] for _, _, b in sent[1:]] == ["search_document", "search_document"]
    assert [len(b["texts"]) for _, _, b in sent[1:]] == [96, 4]  # the API's 96 per call
    assert len(docs) == 100 and round(query[0][0], 3) == 0.6  # made unit length here
    assert report == {"provider_tokens": 15}


@pytest.mark.parametrize("reply", [
    {"embeddings": {"float": [[1.0] * embeddings.COHERE_DIMENSIONS]}},  # one vector for two texts
    {"embeddings": {"float": [[1.0] * 3, [1.0] * 3]}},  # another dimension
    {"embeddings": {}},
])
def test_a_cohere_reply_that_is_not_what_was_asked_is_refused(monkeypatch, reply):
    monkeypatch.setenv("COHERE_API_KEY", KEY)

    async def go():
        async with mocked(lambda r: httpx.Response(200, json=reply)) as client:
            return await embeddings.Embedder("cohere", embeddings.COHERE_MODEL).embed(client, ["a", "b"], "RETRIEVAL_DOCUMENT")
    with pytest.raises(embeddings.EmbeddingError, match="bad_reply"):
        asyncio.run(go())


def test_cohere_without_a_key_sends_nothing_and_is_offered_only_with_its_key(monkeypatch):
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    sent = []

    async def go():
        async with mocked(lambda r: sent.append(r) or httpx.Response(200)) as client:
            return await embeddings.Embedder("cohere", embeddings.COHERE_MODEL).embed(client, ["a"], "RETRIEVAL_QUERY")
    with pytest.raises(embeddings.EmbeddingError, match="COHERE_API_KEY is not set"):
        asyncio.run(go())
    assert sent == []
    option = next(o for o in embeddings.options(TOOLS) if o["provider"] == "cohere")
    assert (option["available"], option["reason"], option["models"]) == (False, "Add a Cohere API key", ["embed-v5.0-fast"])
    monkeypatch.setenv("COHERE_API_KEY", KEY)
    assert next(o for o in embeddings.options(TOOLS) if o["provider"] == "cohere")["available"] is True
    assert [o["provider"] for o in embeddings.options(TOOLS)][-1] == "off"


def test_cohere_has_its_own_stored_identity_with_its_dimension_and_is_never_chosen_by_itself(monkeypatch):
    embedder = embeddings.Embedder("cohere", "embed-v5.0-fast")
    assert embedder.stored_model == f"cohere:embed-v5.0-fast@{embeddings.COHERE_DIMENSIONS}"
    assert embeddings.Embedder.from_identity("cohere", embedder.stored_model) == embedder
    assert embeddings.Embedder("voyage", "voyage-4-lite").stored_model == "voyage:voyage-4-lite@1024"  # unchanged
    assert embedder.batch == 96
    monkeypatch.setenv("COHERE_API_KEY", KEY)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(embeddings.local_embedding, "model_available", lambda model_id: False)
    assert embeddings.chosen(None) == ("off", None)


# ---- the new rerankers --------------------------------------------------------------------------------

def reply_for(provider, n, scores):
    results = [{"index": i, "relevance_score": scores[i]} for i in reversed(range(n))]
    return {"cohere": {"results": results, "meta": {"billed_units": {"search_units": 1}}},
            "jina": {"results": results, "usage": {"total_tokens": 40}},
            "zeroentropy": {"results": results, "total_tokens": 50}}[provider]


@pytest.mark.parametrize("provider, url, body", [
    ("cohere", "https://api.cohere.com/v2/rerank", {"model": "rerank-v4.0-fast", "query": "SYNTHETIC question",
                                                    "documents": ["d0", "d1", "d2"], "top_n": 3, "max_tokens_per_doc": 4096}),
    ("jina", "https://api.jina.ai/v1/rerank", {"model": "jina-reranker-v3.5", "query": "SYNTHETIC question",
                                               "documents": ["d0", "d1", "d2"], "top_n": 3, "return_documents": False}),
    ("zeroentropy", "https://api.zeroentropy.dev/v1/models/rerank", {"model": "zerank-2", "query": "SYNTHETIC question",
                                                                     "documents": ["d0", "d1", "d2"], "top_n": 3}),
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


@pytest.mark.parametrize("provider", ["cohere", "jina", "zeroentropy"])
@pytest.mark.parametrize("status, reply, code", [
    (200, {"results": [{"index": 0, "relevance_score": 1}]}, "reranker_bad_reply"),  # two documents, one score
    (200, {"results": [{"index": 0, "relevance_score": "high"}, {"index": 1, "relevance_score": 0}]}, "reranker_bad_reply"),
    (500, {"message": "SYNTHETIC"}, "reranker_failed"),
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


def test_cohere_refuses_a_record_it_would_cut_and_sends_nothing(monkeypatch):
    monkeypatch.setenv("COHERE_API_KEY", KEY)
    sent = []

    async def go():
        async with mocked(lambda r: sent.append(r) or httpx.Response(200)) as client:
            return await rerankers.rerank(rerankers.chosen({"enabled": True, "provider": "cohere"}), client, None,
                                          "q", ["short", "x" * 13_000])
    with pytest.raises(rerankers.RerankError, match="longer than Cohere reads"):
        asyncio.run(go())
    assert sent == []


def test_zeroentropy_requests_are_split_by_its_byte_count():
    batches = rerankers.zeroentropy_batches("q", ["x" * 15_000] * 400)
    assert sum(len(b) for b in batches) == 400 and len(batches) == 2
    assert all(sum(150 + 1 + 15_000 for _ in b) <= rerankers.ZEROENTROPY_REQUEST_BYTES for b in batches)


def test_api_rerankers_are_offered_only_with_their_keys_and_say_where_text_goes(monkeypatch):
    for env in rerankers.KEY_ENVS.values():
        monkeypatch.delenv(env, raising=False)
    offered = rerankers.options(None)
    assert [o["provider"] for o in offered] == ["builtin"] * 4 + ["voyage", "cohere", "jina", "zeroentropy"]
    options = {o["provider"]: o for o in offered}
    assert [options[p]["reason"] for p in ("voyage", "cohere", "jina", "zeroentropy")] == [
        "Add a Voyage API key", "Add a Cohere API key", "Add a Jina API key", "Add a ZeroEntropy API key"]
    assert options["jina"]["sends"] == "The question and the title and abstract of each reranked record, to Jina AI"
    monkeypatch.setenv("JINA_API_KEY", KEY)
    assert {o["provider"]: o for o in rerankers.options(None)}["jina"]["available"] is True


# ---- keys ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("env, method, url", [
    ("COHERE_API_KEY", "GET", "https://api.cohere.com/v1/models?page_size=1"),
    ("JINA_API_KEY", "POST", "https://api.jina.ai/v1/rerank"),
    ("ZEROENTROPY_API_KEY", "POST", "https://api.zeroentropy.dev/v1/models/rerank"),
])
def test_each_new_key_is_managed_and_tested_with_one_small_request(env, method, url):
    sent = []

    def handler(request):
        sent.append((request.method, str(request.url)))
        return httpx.Response(200 if len(sent) == 1 else 401, json={"message": "SYNTHETIC"})

    async def go():
        async with mocked(handler) as client:
            return await credentials.test(client, env, KEY), await credentials.test(client, env, KEY)
    ok, refused = asyncio.run(go())
    assert sent[0] == (method, url)
    assert ok["status"] == "ok" and refused["status"] == "rejected"
    assert credentials.MANAGED_KEYS[env].testable and not credentials.MANAGED_KEYS[env].pair
