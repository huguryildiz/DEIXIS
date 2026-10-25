"""Voyage embeddings, the reranker layer and the Qwen3 built-in identity (model-free, no paid call).

Voyage is a mocked endpoint (httpx.MockTransport); the built-in model and reranker are the injected fake local embedder;
no model is downloaded and no request leaves the test. Passing shows routing, request shapes, cache identities, how a
rerank maps back to its records and what happens on failure, timeout and pause. It does not show that Qwen3, Voyage or
any reranker orders records better: retrieval quality was not measured.
"""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from deixis.documents import embeddings, local_embedding, rerankers
from deixis.workflow.search import small_batch
from deixis.workflow.run.flow import RunStopped
from test_builtin_embedding_flow import BUILTIN, FakeLocal, Session

RER = "qwen3-reranker-0.6b"

KEY = "SYNTHETIC-voyage-key"


def voyage(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---- Voyage embeddings -----------------------------------------------------------------------------


def test_voyage_without_a_key_sends_nothing(monkeypatch):
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    sent = []

    async def go():
        async with voyage(lambda r: sent.append(r) or httpx.Response(500)) as client:
            return await embeddings.Embedder("voyage", embeddings.VOYAGE_MODEL).embed(client, ["SYNTHETIC"], "RETRIEVAL_DOCUMENT")
    with pytest.raises(embeddings.EmbeddingError, match="VOYAGE_API_KEY is not set"):
        asyncio.run(go())
    assert sent == []


# ---- cache identity and the provider choice --------------------------------------------------------


# ---- the reranker layer ----------------------------------------------------------------------------


def test_voyage_rerank_maps_scores_back_to_input_order_and_refuses_a_wrong_reply(monkeypatch):
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        n = len(body["documents"])
        return httpx.Response(200, json={"data": [{"index": i, "relevance_score": i / 10} for i in reversed(range(n))],
                                         "usage": {"total_tokens": 30}})

    async def go(h):
        async with voyage(h) as client:
            return await rerankers.rerank_voyage(client, KEY, "SYNTHETIC question", ["d0", "d1", "d2"])
    result = asyncio.run(go(handler))
    assert result["scores"] == [0.0, 0.1, 0.2] and result["provider_tokens"] == 30
    assert sent == [{"query": "SYNTHETIC question", "documents": ["d0", "d1", "d2"], "model": "rerank-3-lite", "truncation": False}]
    with pytest.raises(rerankers.RerankError) as wrong:
        asyncio.run(go(lambda r: httpx.Response(200, json={"data": [{"index": 0, "relevance_score": 1}]})))
    assert wrong.value.code == "reranker_bad_reply"
    with pytest.raises(rerankers.RerankError) as failed:
        asyncio.run(go(lambda r: httpx.Response(500, json={"detail": "SYNTHETIC"})))
    assert failed.value.code == "reranker_failed"


# ---- the frozen list: what a stored rerank does to it ---------------------------------------------

def manifest(fused, priority=(), reranker=None):
    """A frozen list's manifest reduced to what `build_list` reads, with `replay` returning `fused`."""
    pool = [{"id": rid, "work_id": f"w-{rid}", "title": f"SYNTHETIC {rid}", "abstract": None} for rid in fused]
    return {"pool": pool, "priority_pool": [{"id": rid, "work_id": f"w-{rid}"} for rid in priority],
            "user_priority": list(priority), "versions": {rid: {"work_id": f"w-{rid}"} for rid in [*fused, *priority]},
            **({"reranker": reranker} if reranker else {}), "fused": list(fused)}


@pytest.fixture
def fixed_replay(monkeypatch):
    monkeypatch.setattr(small_batch, "replay", lambda m: {"fused": list(m["fused"]), "ranks": {}, "reasons": {}})


def applied(candidates, scores):
    return {"status": "applied", "provider": "builtin", "model": RER,
            "candidate_ids": candidates, "scores": scores, "error_code": None}


def test_a_stored_rerank_reorders_only_its_candidates_and_the_person_s_records_stay_first(fixed_replay):
    listing = small_batch.build_list(manifest(["a", "b", "c", "d"], priority=["u"],
                                              reranker=applied(["a", "b", "c"], {"a": 0.1, "b": 0.3, "c": 0.9})))
    assert listing["order"] == ["u", "c", "b", "a", "d"]
    assert listing["automatic_order"] == ["a", "b", "c", "d"]  # the fused order is kept beside it
    assert listing["reranker"]["applied"] is True and listing["reranker"]["reranked"] == 3
    assert [item["user_priority"] for item in listing["items"]] == [True, False, False, False, False]
    # The list replays exactly from its manifest.
    again = small_batch.build_list(manifest(["a", "b", "c", "d"], priority=["u"],
                                            reranker=applied(["a", "b", "c"], {"a": 0.1, "b": 0.3, "c": 0.9})))
    assert again["order_hash"] == listing["order_hash"] and again["manifest_hash"] == listing["manifest_hash"]


@pytest.mark.parametrize("stored, reason", [
    ({"status": "failed", "provider": "voyage", "model": "rerank-3-lite", "candidate_ids": ["a", "b"], "scores": None,
      "error_code": "reranker_timeout"}, "reranker_timeout"),
])
def test_a_failed_or_stale_rerank_keeps_the_fused_order_and_says_why(fixed_replay, stored, reason):
    listing = small_batch.build_list(manifest(["a", "b", "c"], reranker=stored))
    assert listing["order"] == ["a", "b", "c"]
    assert (listing["reranker"]["applied"], listing["reranker"]["reason"], listing["reranker"]["fallback"]) == (
        False, reason, "fused_order")


# ---- the rerank step ---------------------------------------------------------------------------------

class Steps:
    """The few store calls `rerank_list` makes, in memory."""

    def __init__(self, setting):
        self.settings = {rerankers.SETTING: setting}
        self.steps = {}
        self.clock = SimpleNamespace(now=lambda: None)

    def setting(self, key):
        return self.settings.get(key)

    def existing_step(self, run_id, key):
        return self.steps.get(key)

    def step(self, run_id, key, kind):
        return self.steps.setdefault(key, {"id": key, "status": "pending", "output": None})

    def start_step(self, step_id):
        self.steps[step_id]["status"] = "running"

    def finish_step(self, step_id, status, output=None, error_code=None, error=None):
        self.steps[step_id].update(status=status, output=output, error_code=error_code)


def rerank_flow(monkeypatch, setting, local, http=None, stop=lambda: False):
    store = Steps(setting)
    stopped = []

    def checkpoint(run_id, revision):
        if stop():
            stopped.append(True)
            raise RunStopped
    flow = SimpleNamespace(store=store, deps=SimpleNamespace(http=http, local_embedder=local), _checkpoint=checkpoint,
                           _stop_requested=lambda run_id, revision: stop())
    pool = [{"id": rid, "work_id": f"w-{rid}", "title": f"SYNTHETIC title {rid}", "abstract": f"SYNTHETIC abstract {rid}"}
            for rid in ("a", "b", "c", "d")]
    monkeypatch.setattr(small_batch, "manifest_for", lambda *args: {"pool": pool, "user_priority": ["c"], "fused": ["a", "b", "c", "d"]})
    monkeypatch.setattr(small_batch, "replay", lambda m: {"fused": m["fused"]})
    monkeypatch.setattr(small_batch.fast_path, "stage_deadline", lambda *args: None)
    return flow, store, stopped


RUN = {"id": "run-1", "scope_revision": 1, "budget": {"fast_path": {"N": 1}}}  # reads 1: with factor 2, 2 reranked
SCOPE = {"question": "SYNTHETIC research question"}


def test_a_failed_rerank_is_recorded_with_the_fused_order_as_its_fallback_and_no_other_reranker(monkeypatch):
    class Local:
        async def rerank(self, model_id, query, documents, seconds):
            raise local_embedding.LocalEmbeddingError("builtin_unavailable", "SYNTHETIC not installed")
    sent = []
    http = voyage(lambda r: sent.append(r) or httpx.Response(200))
    monkeypatch.setenv("VOYAGE_API_KEY", KEY)
    flow, store, _ = rerank_flow(monkeypatch, {"enabled": True, "provider": "builtin", "model": RER}, Local(), http)
    asyncio.run(small_batch.rerank_list(flow, RUN, SCOPE, {}))
    step = store.steps[small_batch.RERANK_KEY]
    assert step["status"] == "failed" and step["error_code"] == "reranker_failed"
    assert (step["output"]["status"], step["output"]["fallback"]) == ("failed", "fused_order")
    assert sent == []  # Voyage has a key here and was not asked instead


# ---- through a real discovery run (fake model, fake local runner) ------------------------------------

class RerankingLocal(FakeLocal):
    """The fake built-in model, with a reranker that scores the reverse of the order it is given (or fails)."""

    def __init__(self, fail=False, **kwargs):
        super().__init__(**kwargs)
        self.fail, self.reranked = fail, []

    async def rerank(self, model_id, query, documents, seconds):
        self.reranked.append(documents)
        if self.fail:
            raise local_embedding.LocalEmbeddingError("builtin_timeout", "SYNTHETIC no reply")
        return [i / len(documents) for i in range(len(documents))], []


@pytest.mark.parametrize("fail", [False, True])
def test_a_discovery_run_reranks_its_list_or_keeps_the_fused_order_and_says_so(tmp_path, monkeypatch, fail):
    local = RerankingLocal(fail=fail)
    s = Session(tmp_path, monkeypatch, local=local, setting=BUILTIN)
    s.store.set_setting(rerankers.SETTING, {"enabled": True, "provider": "builtin", "model": RER, "pool_factor": 2, "timeout_seconds": 60})
    try:
        rid, run_id, view, run = s.discover()
        listing = s.store.existing_step(run_id, small_batch.LIST_KEY)["output"]
        step = s.store.existing_step(run_id, small_batch.RERANK_KEY)
    finally:
        s.close()
    assert local.reranked, "the reranker was asked"
    candidates = step["output"]["candidate_ids"]
    automatic = listing["automatic_order"]
    priority = listing["manifest"]["user_priority"]
    assert candidates == [rid for rid in automatic if rid not in priority][:len(candidates)]
    assert len(candidates) == min(2 * step["output"]["read_top"], len([r for r in automatic if r not in priority]))
    assert sorted(listing["order"]) == sorted(dict.fromkeys(priority + automatic))  # nothing added or dropped
    if fail:
        assert step["status"] == "failed" and listing["reranker"]["applied"] is False
        assert listing["order"][len(priority):] == automatic
    else:
        assert step["status"] == "succeeded" and listing["reranker"]["applied"] is True
        # The fake scores the reverse of the order it was given: the candidates come back reversed, the rest in place.
        assert listing["order"][len(priority):len(priority) + len(candidates)] == candidates[::-1]
        assert listing["order"][len(priority) + len(candidates):] == automatic[len(candidates):]


# ---- Settings ----------------------------------------------------------------------------------------


def test_with_nothing_saved_and_no_voyage_key_the_run_records_that_the_reranker_did_not_run(monkeypatch):
    # D104: on by default with Voyage; without a key nothing is sent, the fused order stands and the step says why.
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    sent = []
    http = voyage(lambda r: sent.append(r) or httpx.Response(200))
    flow, store, _ = rerank_flow(monkeypatch, None, None, http)
    asyncio.run(small_batch.rerank_list(flow, RUN, SCOPE, {}))
    step = store.steps[small_batch.RERANK_KEY]
    assert step["status"] == "failed" and step["error_code"] == "reranker_unavailable" and sent == []
    assert (step["output"]["provider"], step["output"]["model"], step["output"]["fallback"]) == (
        "voyage", "rerank-3-lite", "fused_order")
