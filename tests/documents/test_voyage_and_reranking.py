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

from deixis.documents import builtin_catalog, embeddings, local_embedding, rerankers
from deixis.keys import credentials
from deixis.workflow import small_batch
from deixis.workflow.flow import RunStopped
from test_builtin_embedding_flow import BUILTIN, FakeLocal, Session

RER = "qwen3-reranker-0.6b"

KEY = "SYNTHETIC-voyage-key"


def voyage(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def vectors_reply(request, dimensions=embeddings.VOYAGE_DIMENSIONS, usage=7, reverse=False):
    body = json.loads(request.content)
    data = [{"index": i, "embedding": [1.0] + [0.0] * (dimensions - 1)} for i in range(len(body["input"]))]
    return httpx.Response(200, json={"data": data[::-1] if reverse else data, "usage": {"total_tokens": usage}})


# ---- Voyage embeddings -----------------------------------------------------------------------------

def test_voyage_sends_query_and_document_types_never_truncates_and_reports_its_tokens(monkeypatch):
    monkeypatch.setenv("VOYAGE_API_KEY", KEY)
    sent = []

    def handler(request):
        sent.append((str(request.url), request.headers["authorization"], json.loads(request.content)))
        return vectors_reply(request, reverse=True)
    embedder, report = embeddings.Embedder("voyage", embeddings.VOYAGE_MODEL), {}

    async def go():
        async with voyage(handler) as client:
            query = await embedder.embed(client, ["SYNTHETIC question"], "RETRIEVAL_QUERY", report=report)
            documents = await embedder.embed(client, ["SYNTHETIC a", "SYNTHETIC b"], "RETRIEVAL_DOCUMENT", report=report)
        return query, documents
    query, documents = asyncio.run(go())
    assert [s[0] for s in sent] == ["https://api.voyageai.com/v1/embeddings"] * 2
    assert sent[0][1] == f"Bearer {KEY}"
    assert [(s[2]["input_type"], s[2]["model"], s[2]["truncation"], s[2]["output_dimension"]) for s in sent] == [
        ("query", "voyage-4-lite", False, 1024), ("document", "voyage-4-lite", False, 1024)]
    assert len(query) == 1 and len(documents) == 2 and all(len(v) == 1024 for v in documents)
    assert report == {"provider_tokens": 14}


def test_voyage_batches_by_count_and_estimated_tokens():
    many = ["SYNTHETIC"] * (embeddings.VOYAGE_BATCH + 1)
    assert [len(b) for b in embeddings.voyage_batches(many)] == [embeddings.VOYAGE_BATCH, 1]
    long = "x" * (3 * embeddings.VOYAGE_REQUEST_TOKENS // 2)  # about half a request's token cap each
    batches = embeddings.voyage_batches([long, long, long])
    assert [len(b) for b in batches] == [1, 1, 1]
    assert all(sum(embeddings.estimated_tokens(t) for t in b) <= embeddings.VOYAGE_REQUEST_TOKENS for b in batches)


def test_voyage_waits_out_a_429_a_bounded_number_of_times(monkeypatch):
    monkeypatch.setenv("VOYAGE_API_KEY", KEY)
    waited, now = [], [0.0]

    async def no_sleep(seconds):  # the test's clock moves by what was asked; no real time passes
        waited.append(seconds)
        now[0] += seconds
    monkeypatch.setattr(embeddings, "_sleep", no_sleep)
    monkeypatch.setattr(embeddings, "_clock", lambda: now[0])
    answers = iter([httpx.Response(429, headers={"Retry-After": "2"}, json={"detail": "SYNTHETIC rate limited"})])

    def handler(request):
        return next(answers, None) or vectors_reply(request)
    budget = embeddings.RateBudget()

    async def go():
        async with voyage(handler) as client:
            return await embeddings.Embedder("voyage", embeddings.VOYAGE_MODEL).embed(client, ["SYNTHETIC"], "RETRIEVAL_DOCUMENT", budget)
    assert len(asyncio.run(go())) == 1 and budget.rate_limited_waits == 1 and sum(waited) >= 2

    always = lambda request: httpx.Response(429, json={"detail": "SYNTHETIC"})  # noqa: E731

    async def refused():
        async with voyage(always) as client:
            return await embeddings.Embedder("voyage", embeddings.VOYAGE_MODEL).embed(client, ["SYNTHETIC"], "RETRIEVAL_DOCUMENT",
                                                                                   embeddings.RateBudget())
    with pytest.raises(embeddings.EmbeddingError, match="429"):
        asyncio.run(refused())


@pytest.mark.parametrize("reply", [
    {"data": [{"index": 1, "embedding": [1.0] * 1024}]},  # an index that was not asked
    {"data": [{"index": 0, "embedding": [1.0] * 512}]},  # another dimension
    {"nothing": True},
])
def test_a_voyage_reply_that_is_not_what_was_asked_is_refused(monkeypatch, reply):
    monkeypatch.setenv("VOYAGE_API_KEY", KEY)

    async def go():
        async with voyage(lambda r: httpx.Response(200, json=reply)) as client:
            return await embeddings.Embedder("voyage", embeddings.VOYAGE_MODEL).embed(client, ["SYNTHETIC"], "RETRIEVAL_DOCUMENT")
    with pytest.raises(embeddings.EmbeddingError, match="bad_reply"):
        asyncio.run(go())


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

def test_each_provider_model_and_dimension_is_its_own_stored_identity():
    stored = {embeddings.Embedder(p, m).stored_model for p, m in [
        ("gemini", embeddings.MODEL), ("openai", embeddings.OPENAI_MODEL), ("voyage", embeddings.VOYAGE_MODEL),
        ("builtin", "qwen3-embedding-0.6b"), ("builtin", "bge-small-en-v1.5@aa8f8b0:256")]}
    assert len(stored) == 5
    assert embeddings.Embedder("voyage", embeddings.VOYAGE_MODEL).stored_model == "voyage:voyage-4-lite@1024"
    rebuilt = embeddings.Embedder.from_identity("voyage", "voyage:voyage-4-lite@1024")
    assert (rebuilt.provider, rebuilt.model) == ("voyage", "voyage-4-lite")


def test_a_saved_earlier_built_in_choice_stays_as_saved_and_voyage_is_never_chosen_by_itself(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("VOYAGE_API_KEY", KEY)
    assert embeddings.chosen({"provider": "builtin", "model": "bge-small-en-v1.5@aa8f8b0:256"}) == ("builtin", "bge-small-en-v1.5@aa8f8b0:256")
    assert embeddings.chosen(None)[0] != "voyage"  # a key alone turns on nothing
    assert embeddings.chosen({"provider": "voyage", "model": "voyage-4-lite"}) == ("voyage", "voyage-4-lite")


def test_a_step_frozen_with_the_earlier_built_in_model_embeds_nothing_under_its_name():
    local = FakeLocal()
    old = embeddings.Embedder.from_identity("builtin", "builtin:bge-small-en-v1.5@aa8f8b0:256:threads=4", local)
    with pytest.raises(embeddings.EmbeddingError, match="builtin_model_changed"):
        asyncio.run(old.embed(None, ["SYNTHETIC"], "RETRIEVAL_DOCUMENT"))
    assert local.calls == []


def test_voyage_is_offered_only_with_its_key(monkeypatch):
    tools = {"tools": [{"id": i, "name": i, "running": False, "installed": False, "models": []} for i in ("ollama", "lm_studio")]}
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    option = next(o for o in embeddings.options(tools) if o["provider"] == "voyage")
    assert (option["available"], option["reason"], option["models"]) == (False, "Add a Voyage API key", ["voyage-4-lite"])
    monkeypatch.setenv("VOYAGE_API_KEY", KEY)
    assert next(o for o in embeddings.options(tools) if o["provider"] == "voyage")["available"] is True


def test_the_voyage_key_test_embeds_one_query_word_and_reads_a_refusal(monkeypatch):
    sent = []

    def handler(request):
        sent.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200 if len(sent) == 1 else 401, json={"detail": "SYNTHETIC"})

    async def go():
        async with voyage(handler) as client:
            return await credentials.test(client, "VOYAGE_API_KEY", KEY), await credentials.test(client, "VOYAGE_API_KEY", KEY)
    ok, refused = asyncio.run(go())
    assert sent[0] == ("https://api.voyageai.com/v1/embeddings", {"model": "voyage-4-lite", "input": ["test"], "input_type": "query"})
    assert ok["status"] == "ok" and refused["status"] == "rejected"
    assert credentials.MANAGED_KEYS["VOYAGE_API_KEY"].testable


# ---- the reranker layer ----------------------------------------------------------------------------

def test_reranking_is_off_unless_turned_on():
    assert rerankers.chosen(None) is None
    assert rerankers.chosen({"enabled": False, "provider": "voyage"}) is None
    choice = rerankers.chosen({"enabled": True, "provider": "builtin"})
    assert (choice.provider, choice.model, choice.pool_factor) == ("builtin", builtin_catalog.NO_MODEL, 4.0)
    assert rerankers.chosen({"enabled": True, "provider": "builtin", "model": RER}).model == RER
    assert rerankers.chosen({"enabled": True, "provider": "voyage", "pool_factor": 3}).model == "rerank-3-lite"


def test_the_rerank_pool_is_the_papers_read_times_the_factor_so_the_cutoff_can_move():
    choice = rerankers.chosen({"enabled": True, "provider": "builtin"})
    assert [choice.pool_size(n) for n in (25, 50, 100)] == [100, 200, 400]  # quick, standard, detailed
    assert rerankers.chosen({"enabled": True, "provider": "builtin", "pool_factor": 1.5}).pool_size(25) == 38
    assert rerankers.chosen({"enabled": True, "provider": "builtin", "pool_factor": 4}).pool_size(150) == rerankers.MAX_CANDIDATES


def test_reorder_moves_only_the_reranked_records_among_their_own_places():
    automatic = ["a", "b", "c", "d", "e"]
    order = rerankers.reorder(automatic, ["a", "b", "c"], {"a": 0.1, "b": 0.9, "c": 0.1})
    assert order == ["b", "a", "c", "d", "e"]  # an equal score keeps the automatic order; d and e keep their places
    assert sorted(order) == sorted(automatic)


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


def test_the_built_in_rerank_goes_to_the_local_runner_and_maps_its_errors():
    class Local:
        async def rerank(self, model_id, query, documents, seconds):
            assert model_id == RER
            if documents == ["slow"]:
                raise local_embedding.LocalEmbeddingError("builtin_timeout", "SYNTHETIC")
            return [0.2, 0.8], [1]
    choice = rerankers.chosen({"enabled": True, "provider": "builtin", "model": RER})
    result = asyncio.run(rerankers.rerank(choice, None, Local(), "q", ["a", "b"]))
    assert result == {"scores": [0.2, 0.8], "truncated": 1, "provider_tokens": None}
    with pytest.raises(rerankers.RerankError) as timeout:
        asyncio.run(rerankers.rerank(choice, None, Local(), "q", ["slow"]))
    assert timeout.value.code == "reranker_timeout"
    with pytest.raises(rerankers.RerankError) as missing:
        asyncio.run(rerankers.rerank(choice, None, None, "q", ["a"]))
    assert missing.value.code == "reranker_unavailable"


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


def test_without_a_rerank_the_list_and_its_manifest_are_as_before(fixed_replay):
    listing = small_batch.build_list(manifest(["a", "b"], priority=["u"]))
    assert listing["order"] == ["u", "a", "b"] and "reranker" not in listing and "reranker" not in listing["manifest"]


@pytest.mark.parametrize("stored, reason", [
    ({"status": "failed", "provider": "voyage", "model": "rerank-3-lite", "candidate_ids": ["a", "b"], "scores": None,
      "error_code": "reranker_timeout"}, "reranker_timeout"),
    (applied(["b", "c"], {"b": 1.0, "c": 0.0}), "candidates_changed"),  # the list moved while the reranker ran
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


def test_the_rerank_step_scores_the_first_records_the_person_did_not_include_with_title_and_abstract(monkeypatch):
    seen = []

    class Local:
        async def rerank(self, model_id, query, documents, seconds):
            seen.append((query, documents))
            return [0.1, 0.9], []
    flow, store, _ = rerank_flow(monkeypatch, {"enabled": True, "provider": "builtin", "model": RER, "pool_factor": 2}, Local())
    asyncio.run(small_batch.rerank_list(flow, RUN, SCOPE, {}))
    step = store.steps[small_batch.RERANK_KEY]
    assert seen == [("SYNTHETIC research question", ["SYNTHETIC title a\n\nSYNTHETIC abstract a",
                                                     "SYNTHETIC title b\n\nSYNTHETIC abstract b"])]  # c is the person's
    assert step["status"] == "succeeded" and step["output"]["status"] == "applied"
    assert step["output"]["candidate_ids"] == ["a", "b"] and step["output"]["scores"] == {"a": 0.1, "b": 0.9}
    assert step["output"]["read_top"] == 1
    assert step["output"]["sent"] == {"query": "question", "documents": "title_and_abstract", "count": 2, "to": "this_computer"}
    # A rerank that ended is not asked again.
    asyncio.run(small_batch.rerank_list(flow, RUN, SCOPE, {}))
    assert len(seen) == 1


def test_off_writes_no_step_and_calls_nothing(monkeypatch):
    class Local:
        async def rerank(self, *args):
            raise AssertionError("not called")
    flow, store, _ = rerank_flow(monkeypatch, None, Local())
    asyncio.run(small_batch.rerank_list(flow, RUN, SCOPE, {}))
    assert store.steps == {}


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


def test_a_rerank_past_its_time_limit_is_stopped_and_recorded_as_a_timeout(monkeypatch):
    cancelled = []

    class Local:
        async def rerank(self, model_id, query, documents, seconds):
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise
    flow, store, _ = rerank_flow(monkeypatch, {"enabled": True, "provider": "builtin", "model": RER}, Local())
    monkeypatch.setattr(small_batch.fast_path, "stage_deadline",
                        lambda *args: __import__("datetime").datetime(2026, 1, 1, 0, 0, 1))
    store.clock = SimpleNamespace(now=lambda: __import__("datetime").datetime(2026, 1, 1, 0, 0, 0, 700_000))
    asyncio.run(asyncio.wait_for(small_batch.rerank_list(flow, RUN, SCOPE, {}), 5))
    step = store.steps[small_batch.RERANK_KEY]
    assert cancelled == [True] and step["status"] == "failed" and step["error_code"] == "reranker_timeout"


def test_a_pause_during_the_rerank_stops_it_and_the_run_and_the_step_is_asked_again(monkeypatch):
    cancelled, paused = [], []

    class Local:
        async def rerank(self, model_id, query, documents, seconds):
            paused.append(True)
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise
    flow, store, stopped = rerank_flow(monkeypatch, {"enabled": True, "provider": "builtin", "model": RER}, Local(),
                                       stop=lambda: bool(paused))
    with pytest.raises(RunStopped):
        asyncio.run(asyncio.wait_for(small_batch.rerank_list(flow, RUN, SCOPE, {}), 5))
    assert cancelled == [True] and stopped and store.steps[small_batch.RERANK_KEY]["status"] == "running"


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

def test_the_reranking_setting_is_off_by_default_and_refuses_a_reranker_that_cannot_run(tmp_path, monkeypatch):
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    s = Session(tmp_path, monkeypatch, setting=None)
    try:
        view = s.client.get("/api/reranking").json()
        refused = s.client.put("/api/reranking", json={"enabled": True, "provider": "voyage"})
        monkeypatch.setenv("VOYAGE_API_KEY", KEY)
        saved = s.client.put("/api/reranking", json={"enabled": True, "provider": "voyage", "pool_factor": 3}).json()
        too_many = s.client.put("/api/reranking", json={"enabled": True, "provider": "voyage", "pool_factor": 5})
        builtin = s.client.put("/api/reranking", json={"enabled": True, "provider": "builtin", "model": RER})
        semantic = s.client.get("/api/semantic-search").json()
    finally:
        s.close()
    assert (view["enabled"], view["provider"], view["pool_factor"], view["applies_to"]) == (False, None, 4.0, ["record_order"])
    assert refused.status_code == 422 and refused.json()["detail"] == "Add a Voyage API key"
    assert (saved["enabled"], saved["provider"], saved["pool_factor"]) == (True, "voyage", 3.0)
    assert too_many.status_code == 422
    assert builtin.status_code == 422  # the built-in model is not downloaded in this test
    assert semantic["provider"] != "voyage"  # a Voyage key turns on no embedding by itself


def test_settings_say_when_a_saved_built_in_choice_was_for_the_earlier_model(tmp_path, monkeypatch):
    s = Session(tmp_path, monkeypatch, setting={"provider": "builtin", "model": "bge-small-en-v1.5@aa8f8b0:256"})
    try:
        view = s.client.get("/api/semantic-search").json()
    finally:
        s.close()
    assert (view["provider"], view["model"]) == ("builtin", "bge-small-en-v1.5@aa8f8b0:256")  # never remapped
    assert view["builtin_model_changed"] == {"from": "bge-small-en-v1.5@aa8f8b0:256", "to": None}
