"""Voyage embeddings, the reranker layer and the Qwen3 built-in identity (model-free, no paid call).

Voyage is a mocked endpoint (httpx.MockTransport); the built-in model and reranker are the injected fake local embedder;
no model is downloaded and no request leaves the test. Passing shows routing, request shapes, cache identities, how a
rerank maps back to its records and what happens on failure, timeout and pause. It does not show that Qwen3, Voyage or
any reranker orders records better: retrieval quality was not measured.
"""

import asyncio
import json
import sys
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest

from deixis.documents import embeddings, local_embedding, rerankers
from deixis.providers import pacing
from deixis.domain.rules import TEST_EFFORT_BUDGETS
from deixis.workflow.search import english_question, small_batch
from deixis.workflow.run.flow import RunStopped
from test_builtin_embedding_flow import BUILTIN, FakeLocal, Session
from test_lookup_flow import headers_back, headers_out, written
from test_ranking_flow import STRONG, Pool, pool, work
from windows_env import WAIT_FACTOR

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

    def __init__(self, setting, sentence=None):
        self.settings = {rerankers.SETTING: setting}
        self.sentence = sentence
        self.steps = {}
        self.clock = SimpleNamespace(now=lambda: None)

    def setting(self, key):
        return self.settings.get(key)

    def english_question(self, research_id, scope_revision):
        return self.sentence

    def existing_step(self, run_id, key):
        return self.steps.get(key)

    def step(self, run_id, key, kind):
        return self.steps.setdefault(key, {"id": key, "status": "pending", "output": None})

    def start_step(self, step_id):
        self.steps[step_id]["status"] = "running"

    def finish_step(self, step_id, status, output=None, error_code=None, error=None):
        self.steps[step_id].update(status=status, output=output, error_code=error_code)


def rerank_flow(monkeypatch, setting, local, http=None, stop=lambda: False, sentence=None):
    store = Steps(setting, sentence)
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


# A question in another language, with no English sentence stored for its revision.
OTHER_LANGUAGE_SCOPE = {"question": "Sualtı duyarga ağlarında yönlendirme protokolleri nasıl karşılaştırılıyor?",
                        "language_hint": "tr", "research_id": "res-1", "revision": 1}


def test_without_an_english_sentence_the_rerank_asks_no_reranker_and_the_list_keeps_the_fused_order(monkeypatch):
    # The reranker reads the revision's English sentence, never the question as written. Without one the step is
    # failed with that reason, no reranker is asked, and the delivered list stays in its fused order.
    asked = []

    class Local:
        async def rerank(self, model_id, query, documents, seconds):
            asked.append(query)
            return [0.0 for _ in documents]
    sent = []
    http = voyage(lambda r: sent.append(r) or httpx.Response(200))
    monkeypatch.setenv("VOYAGE_API_KEY", KEY)  # a key is in reach and is still not used
    flow, store, _ = rerank_flow(monkeypatch, {"enabled": True, "provider": "builtin", "model": RER}, Local(), http)
    asyncio.run(small_batch.rerank_list(flow, RUN, OTHER_LANGUAGE_SCOPE, {}))
    step = store.steps[small_batch.RERANK_KEY]
    assert step["status"] == "failed" and step["error_code"] == english_question.MISSING
    assert (step["output"]["status"], step["output"]["fallback"]) == ("failed", "fused_order")
    assert asked == [] and sent == []  # neither the built-in runner nor Voyage was asked
    # The list the person is given, built from that step as `freeze_list` builds it.
    stored = {key: step["output"].get(key)
              for key in ("status", "provider", "model", "candidate_ids", "scores", "error_code")}
    monkeypatch.setattr(small_batch, "replay", lambda m: {"fused": list(m["fused"]), "ranks": {}, "reasons": {}})
    listing = small_batch.build_list(manifest(["a", "b", "c"], reranker=stored))
    assert listing["order"] == ["a", "b", "c"]
    assert (listing["reranker"]["applied"], listing["reranker"]["reason"], listing["reranker"]["fallback"]) == (
        False, english_question.MISSING, "fused_order")


# The old chain-only hold, which a budget frozen with version 3 keeps.
RERANK_V3 = {"version": 3, "pool_factor": 8.0, "max_pool_factor": 8.0, "hold_without_abstract": "with_text_route"}


@pytest.mark.parametrize("rule, held", [(small_batch.RERANK_RULE, False), (RERANK_V3, True)])
def test_a_chain_only_record_is_reranked_since_d170_and_keeps_its_place_under_an_earlier_rule(monkeypatch, rule, held):
    # A record only citation chaining brought goes to the reranker like any other; a budget frozen with an
    # earlier rule keeps that hold (not sent, its fused place kept, `chained_only`). The rerank step only, with an
    # abstract present: the lookup before the rerank (which asks about chain-only records since version 4) is not
    # covered.
    flow, store, _ = rerank_flow(monkeypatch, {"enabled": True, "provider": "builtin", "model": RER, "pool_factor": 2},
                                 RerankingLocal())
    built = small_batch.manifest_for()
    monkeypatch.setattr(small_batch, "manifest_for", lambda *args: built | {"chain_heads": ["b"]})
    run = RUN | {"budget": RUN["budget"] | {"inspection": {"rerank": dict(rule)}}}
    asyncio.run(small_batch.rerank_list(flow, run, SCOPE, {}))
    output = store.steps[small_batch.RERANK_KEY]["output"]
    assert store.steps[small_batch.RERANK_KEY]["status"] == "succeeded"
    if held:
        assert (output["candidate_ids"], output["kept_in_place"], output["kept_reasons"]) == (["a"], ["b"], {"b": "chained_only"})
    else:
        assert (output["candidate_ids"], output["kept_in_place"], output["kept_reasons"]) == (["a", "b"], [], {})


# ---- the pre-selection of the window (rerank rule version 5) -----------------------------------------

# A run whose budget froze a rule that pre-selects (version 5 and later); the rules before it take the fused prefix.
PRESELECT_RUN = {**RUN, "budget": {**RUN["budget"], "inspection": {"rerank": dict(small_batch.RERANK_RULE)}}}


def ranked_list(query, places, focused=False):
    """One relevance-ordered query list, as `preselect.lists` would have grouped it."""
    return {"provider": "openalex", "query_text": query, "sort": None, "votes": True, "read_total": len(places),
            "members": sorted(places), "places": places, "size": len(places), "focused": focused}


def lists_manifest(built, *, lists, floors, chain=(), reserve=None):
    return built | {"chain_heads": list(chain), "query_lists": lists,
                    "preselect": {"rule": small_batch.preselect.RULE, "k": small_batch.preselect.K,
                                  "floors": floors, **({"fused_reserve": reserve} if reserve else {})}}


def test_the_query_lists_choose_the_window_and_a_floor_brings_in_what_no_list_ranked(monkeypatch):
    """The pool (a, b, d; c is the person's own) is larger than the window of two, so the lists decide who enters.
    "d" is the chain's own record and no list ranked it: without a floor it stays out, with one it is reranked."""
    flow, store, _ = rerank_flow(monkeypatch, {"enabled": True, "provider": "builtin", "model": RER, "pool_factor": 2},
                                 RerankingLocal())
    built = small_batch.manifest_for()
    lists = [ranked_list("SYNTHETIC main", {"a": 0, "b": 1})]
    monkeypatch.setattr(small_batch, "manifest_for",
                        lambda *args: lists_manifest(built, lists=lists, floors={"chain_only": 1}, chain=["d"]))
    asyncio.run(small_batch.rerank_list(flow, PRESELECT_RUN, SCOPE, {}))
    output = store.steps[small_batch.RERANK_KEY]["output"]
    assert sorted(output["candidate_ids"]) == ["a", "d"]
    told = output["preselect"]
    assert (told["ran"], told["pool"], told["window"]) == (True, 3, 2)
    assert told["floors_taken"] == {"chain_only": ["d"], "narrow_only": []}
    assert [part["rank"] for part in told["contributions"]["a"]] == [1] and told["contributions"]["d"] == []
    assert [entry["query_text"] for entry in told["lists"]] == ["SYNTHETIC main"]


def test_a_pool_that_fits_the_window_is_not_pre_selected_at_all(monkeypatch):
    flow, store, _ = rerank_flow(monkeypatch, {"enabled": True, "provider": "builtin", "model": RER, "pool_factor": 8},
                                 RerankingLocal())
    built = small_batch.manifest_for()
    lists = [ranked_list("SYNTHETIC main", {"d": 0})]
    monkeypatch.setattr(small_batch, "manifest_for",
                        lambda *args: lists_manifest(built, lists=lists, floors={"chain_only": 1}, chain=["a"]))
    asyncio.run(small_batch.rerank_list(flow, PRESELECT_RUN, SCOPE, {}))
    output = store.steps[small_batch.RERANK_KEY]["output"]
    # Every record the person did not include is in the window, in the fused order: nothing was chosen or dropped.
    assert output["candidate_ids"] == ["a", "b", "d"] and output["preselect"]["ran"] is False
    assert output["preselect"]["floors_taken"] == {}


def test_a_chain_record_a_query_list_also_ranked_spends_no_floor_place(monkeypatch):
    """The floor is for the records with no vote at all. "a" is the chain's and a list ranked it, so the one floor
    place goes to "d", which no list holds, and "a" takes its window place on its own votes."""
    flow, store, _ = rerank_flow(monkeypatch, {"enabled": True, "provider": "builtin", "model": RER, "pool_factor": 2},
                                 RerankingLocal())
    built = small_batch.manifest_for()
    lists = [ranked_list("SYNTHETIC main", {"a": 0, "b": 1})]
    monkeypatch.setattr(small_batch, "manifest_for",
                        lambda *args: lists_manifest(built, lists=lists, floors={"chain_only": 1}, chain=["a", "d"]))
    asyncio.run(small_batch.rerank_list(flow, PRESELECT_RUN, SCOPE, {}))
    output = store.steps[small_batch.RERANK_KEY]["output"]
    assert sorted(output["candidate_ids"]) == ["a", "d"]
    assert output["preselect"]["floors_taken"] == {"chain_only": ["d"], "narrow_only": []}


def test_a_record_the_person_included_takes_no_window_place_however_the_lists_voted(monkeypatch):
    # "c" is the person's own: it leads the list but is already first in the research's list, so the window's two
    # places go to the records the person did not include.
    flow, store, _ = rerank_flow(monkeypatch, {"enabled": True, "provider": "builtin", "model": RER, "pool_factor": 2},
                                 RerankingLocal())
    built = small_batch.manifest_for()
    lists = [ranked_list("SYNTHETIC main", {"c": 0, "d": 1})]
    monkeypatch.setattr(small_batch, "manifest_for", lambda *args: lists_manifest(built, lists=lists, floors={}))
    asyncio.run(small_batch.rerank_list(flow, PRESELECT_RUN, SCOPE, {}))
    output = store.steps[small_batch.RERANK_KEY]["output"]
    assert "c" not in output["candidate_ids"] and sorted(output["candidate_ids"]) == ["a", "d"]


def test_the_fused_order_s_first_records_enter_the_window_before_the_votes(monkeypatch):
    """Rerank rule version 6: the window's first places go to the leading records of the fused order, and the lists'
    votes fill only what is left. "a" leads the fused order and no list ranked it: it is read all the same, and the
    lists' first choice takes the one place left. Without the reserve the votes alone fill the window."""
    flow, store, _ = rerank_flow(monkeypatch, {"enabled": True, "provider": "builtin", "model": RER, "pool_factor": 2},
                                 RerankingLocal())
    built = small_batch.manifest_for()
    lists = [ranked_list("SYNTHETIC main", {"d": 0, "b": 1})]
    frozen = lists_manifest(built, lists=lists, floors={}, reserve=1)
    monkeypatch.setattr(small_batch, "manifest_for", lambda *args: frozen)
    asyncio.run(small_batch.rerank_list(flow, PRESELECT_RUN, SCOPE, {}))
    output = store.steps[small_batch.RERANK_KEY]["output"]
    assert output["candidate_ids"] == ["a", "d"]
    assert (output["preselect"]["ran"], output["preselect"]["fused_reserve"]) == (True, 1)
    # A manifest frozen without the reserve (version 5) keeps the window its votes chose.
    old = lists_manifest(built, lists=lists, floors={})
    assert small_batch.window_for(old, ["a", "b", "d"], 2)["window"] == ["d", "b"]


def test_the_delivered_order_fuses_the_fused_rank_with_the_reranker_rank(fixed_replay):
    """Rerank rule version 6: each record's place is `1 / (60 + fused rank) + 1 / (60 + reranker rank)`. "f", the
    reranker's first, rises past "e" and the unread "c" and "d", but not past "a", which leads the fused order; "b",
    kept in place without an abstract, keeps its slot; "c" and "d", never read, count at the unscored tail's middle.
    The person's own record stays first, and the list replays exactly. Under version 5 "f" would lead."""
    body = manifest(["a", "b", "c", "d", "e", "f"], priority=["u"],
                    reranker=applied(["a", "e", "f"], {"a": 0.1, "e": 0.5, "f": 0.9}) | {"kept_in_place": ["b"]})
    body |= {"chain_heads": [], "query_lists": [ranked_list("Q", {"e": 0, "f": 1})],
             "preselect": {"rule": small_batch.preselect.RULE, "k": small_batch.preselect.K, "floors": {},
                           "fused_reserve": 2},
             "rerank_merge": {"rule": small_batch.RERANK_MERGE, "k": 60}}
    listing = small_batch.build_list(body)
    assert listing["reranker"]["applied"] is True and listing["reranker"]["kept_in_place"] == 1
    assert listing["order"] == ["u", "a", "b", "f", "e", "c", "d"]
    assert small_batch.build_list(json.loads(json.dumps(body)))["order_hash"] == listing["order_hash"]
    # The same window and scores ordered in place, as a version 5 manifest is replayed.
    window = small_batch.window_for(body, ["a", "b", "c", "d", "e", "f"], 4)["window"]
    assert rerankers.reorder(small_batch.promoted(["a", "b", "c", "d", "e", "f"], window), ["a", "e", "f"],
                             {"a": 0.1, "e": 0.5, "f": 0.9})[0] == "f"


def test_the_fused_reserve_at_its_edges(fixed_replay):
    """Rerank rule version 6 at its edges. "u" is the person's own: it leads the fused order but takes no reserve
    place and stays first in the list. "b" is the chain's own and already inside the reserve, so it spends no floor
    place: the floor goes to "e", the next chain record. A window no larger than the reserve is the fused prefix, and
    a pool that fits the window is not chosen from at all."""
    body = manifest(["u", "a", "b", "c", "d", "e"], priority=["u"],
                    reranker=applied(["a", "b", "e", "d"], {"a": 0.1, "b": 0.2, "e": 0.3, "d": 0.4}))
    body |= {"chain_heads": ["b", "e"], "query_lists": [ranked_list("Q", {"d": 0})],
             "preselect": {"rule": small_batch.preselect.RULE, "k": small_batch.preselect.K,
                           "floors": {"chain_only": 1}, "fused_reserve": 2},
             "rerank_merge": {"rule": small_batch.RERANK_MERGE, "k": 60}}
    automatic = ["a", "b", "c", "d", "e"]
    chosen = small_batch.window_for(body, automatic, 4)
    assert chosen["window"] == ["a", "b", "e", "d"]
    assert chosen["floors"] == {"chain_only": ["e"], "narrow_only": []}
    # A window smaller than the reserve, or equal to it, is the fused order's own leading records.
    assert small_batch.window_for(body, automatic, 1)["window"] == ["a"]
    assert small_batch.window_for(body, automatic, 2)["window"] == ["a", "b"]
    # A pool that fits the window: every record, in fused order, no floor taken.
    assert small_batch.window_for(body, automatic, 5) == {"window": automatic, "floors": {}}
    listing = small_batch.build_list(body)
    assert listing["reranker"]["applied"] is True and listing["order"][0] == "u"
    assert sorted(listing["order"]) == ["a", "b", "c", "d", "e", "u"]


def test_a_version_5_list_replays_in_its_own_order(fixed_replay):
    """A list frozen under rerank rule version 5 (pre-selected, no fused reserve, no merge) is rebuilt as it was:
    the window first, its scored records in score order, the unread records after it in fused order. The same
    manifest with the version 6 merge added would give another order, so a frozen run never moves."""
    body = manifest(["a", "b", "c", "d"], reranker=applied(["c", "d"], {"c": 0.1, "d": 0.9}))
    body |= {"chain_heads": [], "query_lists": [ranked_list("Q", {"c": 0, "d": 1})],
             "preselect": {"rule": small_batch.preselect.RULE, "k": small_batch.preselect.K, "floors": {}}}
    listing = small_batch.build_list(body)
    assert listing["reranker"]["applied"] is True
    assert listing["order"] == ["d", "c", "a", "b"]
    assert small_batch.build_list(json.loads(json.dumps(body)))["order_hash"] == listing["order_hash"]
    assert small_batch.build_list(body | {"rerank_merge": {"rule": small_batch.RERANK_MERGE, "k": 60}})["order"] == [
        "a", "d", "c", "b"]


def test_a_rerank_read_after_the_list_was_frozen_never_moves_a_record(fixed_replay):
    # Quick's reranker scores a small group once the list is frozen. However the list is rebuilt, the scores stay a
    # record of the measurement and the order stays the fused one.
    stored = applied(["a", "b"], {"a": 0.1, "b": 0.9}) | {"point": "after_list"}
    listing = small_batch.build_list(manifest(["a", "b", "c"], reranker=stored))
    assert listing["order"] == ["a", "b", "c"]
    assert (listing["reranker"]["applied"], listing["reranker"]["reason"]) == (False, "read_after_list")


def test_a_stored_rerank_whose_window_the_lists_chose_still_applies_on_replay(fixed_replay):
    """`reranked` recomputes the window from the manifest. Under this rule it is not the first records of the fused
    order, so the check compares the set; a window that no longer matches keeps the fused order, as before."""
    lists = [ranked_list("Q", {"a": 0, "c": 1})]
    body = manifest(["a", "b", "c", "d"], reranker=applied(["c", "a"], {"c": 0.9, "a": 0.1}))
    body |= {"chain_heads": ["d"], "query_lists": lists,
             "preselect": {"rule": small_batch.preselect.RULE, "k": small_batch.preselect.K, "floors": {}}}
    listing = small_batch.build_list(body)
    assert listing["reranker"]["applied"] is True
    # The two records the lists chose take the window's places, highest score first; "b" and "d", which the
    # reranker never read, come after them in the fused order.
    assert listing["order"] == ["c", "a", "b", "d"]
    moved = dict(body)
    moved["query_lists"] = [ranked_list("Q", {"b": 0, "d": 1})]
    stale = small_batch.build_list(moved)
    assert (stale["reranker"]["applied"], stale["reranker"]["reason"]) == (False, "candidates_changed")
    assert stale["order"] == ["a", "b", "c", "d"]


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
    # Standard: the list waits for the reranker there, as Quick's now does (its own tests below).
    local = RerankingLocal(fail=fail)
    s = Session(tmp_path, monkeypatch, local=local, setting=BUILTIN)
    s.store.set_setting(rerankers.SETTING, {"enabled": True, "provider": "builtin", "model": RER, "pool_factor": 2, "timeout_seconds": 60})
    try:
        rid, run_id, view, run = s.discover(effort="standard")
        listing = s.store.existing_step(run_id, small_batch.LIST_KEY)["output"]
        step = s.store.existing_step(run_id, small_batch.RERANK_KEY)
        lookup = (s.store.existing_step(run_id, small_batch.PRERANK_LOOKUP_KEY) or {}).get("output") or {}
    finally:
        s.close()
    assert local.reranked, "the reranker was asked"
    # The lists the pre-selection reads are this run's own stored hits: provider, query text and the depth read.
    told = step["output"]["preselect"]
    assert told["rule"] == small_batch.preselect.RULE and told["k"] == small_batch.preselect.K
    assert [entry["provider"] for entry in told["lists"]] and all(
        entry["size"] > 0 and entry["query_text"] for entry in told["lists"])
    candidates = step["output"]["candidate_ids"]
    # The abstracts asked for before the rerank are the window's own records, not the fused order's first ones.
    assert set(lookup.get("asked") or []) <= set(candidates) | set(step["output"].get("kept_in_place") or [])
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
        # A new run freezes rerank rule version 6: the fused reserve in its window and the rank-fusion merge.
        assert listing["manifest"]["preselect"]["fused_reserve"] == small_batch.RERANK_RULE["fused_reserve"]
        assert listing["manifest"]["rerank_merge"] == {"rule": small_batch.RERANK_MERGE, "k": 60}
        rest = [rid for rid in automatic if rid not in priority]
        kept = set(step["output"].get("kept_in_place") or [])
        assert listing["order"][len(priority):] == small_batch.merged(rest, candidates, step["output"]["scores"], kept, 60)


def quick_run(tmp_path, monkeypatch, local, **saved):
    """One Quick discovery run with the built-in reranker; its listing, rerank step, lookup step and frozen rule."""
    s = Session(tmp_path, monkeypatch, local=local, setting=BUILTIN)
    s.store.set_setting(rerankers.SETTING, {"enabled": True, "provider": "builtin", "model": RER, "timeout_seconds": 60,
                                            **saved})
    try:
        rid, run_id, view, run = s.discover(effort="quick")
        listing = s.store.existing_step(run_id, small_batch.LIST_KEY)["output"]
        step = s.store.existing_step(run_id, small_batch.RERANK_KEY)
        lookup = s.store.existing_step(run_id, small_batch.PRERANK_LOOKUP_KEY)
        budget = s.store.run(run_id)["budget"]
    finally:
        s.close()
    return listing, step, lookup, budget


def test_quick_waits_for_the_reranker_and_its_list_is_in_reranked_order(tmp_path, monkeypatch):
    """A new Quick run freezes `before_list`, a 400-record window (16 x 25) and Standard's 3 s allowance; its lookup
    runs before the rerank, and the list it delivers is the reranked order, replayed identically from its manifest."""
    local = RerankingLocal()
    listing, step, lookup, budget = quick_run(tmp_path, monkeypatch, local)
    rule = budget["inspection"]["rerank"]
    assert (rule["point"], rule["pool_factor"], rule["max_pool_factor"]) == ("before_list", 16.0, 16.0)
    assert budget["fast_path"]["rerank_allowance"] == {"rule": "rerank_allowance_v1", "ms": 3000}
    assert lookup is not None and local.reranked
    assert step["status"] == "succeeded" and step["output"]["point"] == "before_list"
    assert (rule["version"], rule["fused_reserve"], rule["merge"]) == (6, 200, small_batch.RERANK_MERGE)
    candidates, priority = step["output"]["candidate_ids"], listing["manifest"]["user_priority"]
    assert listing["reranker"]["applied"] is True
    # The delivered order fuses each record's fused rank with the rank the reranker's scores give it.
    rest = [rid for rid in listing["automatic_order"] if rid not in priority]
    kept = set(step["output"].get("kept_in_place") or [])
    assert listing["order"][len(priority):] == small_batch.merged(rest, candidates, step["output"]["scores"], kept, 60)
    # The manifest names no point for a reranker that read before the list, so it replays in the same order.
    assert "point" not in listing["manifest"]["reranker"]
    assert small_batch.build_list(listing["manifest"])["order"] == listing["order"]


def test_a_quick_reranker_that_times_out_leaves_the_fused_order_and_says_why(tmp_path, monkeypatch):
    listing, step, lookup, budget = quick_run(tmp_path, monkeypatch, RerankingLocal(fail=True))
    assert step["status"] == "failed" and listing["reranker"]["applied"] is False
    assert listing["reranker"]["fallback"] == "fused_order"
    priority = listing["manifest"]["user_priority"]
    assert listing["order"][len(priority):] == [r for r in listing["automatic_order"] if r not in priority]


def test_a_factor_saved_lower_in_settings_still_wins_at_quick(tmp_path, monkeypatch):
    listing, step, lookup, budget = quick_run(tmp_path, monkeypatch, RerankingLocal(), pool_factor=2)
    assert step["output"]["pool_factor"] == 2.0 and len(step["output"]["candidate_ids"]) <= 2 * 25


def test_a_quick_run_frozen_before_the_change_keeps_after_list_and_replays_in_fused_order(tmp_path, monkeypatch):
    # The budget a Quick run was frozen with before its list waited for the reranker.
    from deixis.workflow.run import fast_path
    monkeypatch.setitem(fast_path.MODES, "quick", fast_path.MODES["quick"]._replace(
        rerank_pool=2.0, rerank_point="after_list", rerank_allowance=0))
    monkeypatch.setitem(small_batch.RERANK_RULE, "pool_factor", 8.0)
    monkeypatch.setitem(small_batch.RERANK_RULE, "max_pool_factor", 8.0)
    local = RerankingLocal()
    listing, step, lookup, budget = quick_run(tmp_path, monkeypatch, local)
    rule = budget["inspection"]["rerank"]
    assert (rule["point"], rule["pool_factor"], rule["max_pool_factor"]) == ("after_list", 2.0, 2.0)
    assert "rerank_allowance" not in budget["fast_path"]
    assert lookup is None, "the lookup before the rerank belongs to the runs whose list waits for it"
    assert local.reranked and step["status"] == "succeeded" and step["output"]["point"] == "after_list"
    # The frozen list is the fused order and holds no reranker: it was frozen before the step existed.
    assert listing["order"] == listing["automatic_order"] and "reranker" not in listing
    assert small_batch.build_list(listing["manifest"])["order"] == listing["order"]
    assert len(step["output"]["candidate_ids"]) <= 2 * step["output"]["read_top"]
    # Built again with that reranker's record, as freeze_list now copies it, the list still keeps the fused order.
    output = step["output"]
    again = listing["manifest"] | {"reranker": {key: output.get(key) for key in (
        "status", "provider", "model", "candidate_ids", "scores", "error_code")} | {"point": "after_list"}}
    rebuilt = small_batch.build_list(again)
    assert rebuilt["order"] == listing["order"] and rebuilt["reranker"]["reason"] == "read_after_list"


def test_quick_reads_a_real_400_record_window_and_standard_keeps_its_own(monkeypatch):
    # 500 records, N = 25: Quick's frozen rule takes 16 x 25 = 400, the reranker's own ceiling.
    flow, store, _ = rerank_flow(monkeypatch, {"enabled": True, "provider": "builtin", "model": RER}, RerankingLocal())
    pool = [{"id": f"r{i:03d}", "work_id": f"w-{i}", "title": f"SYNTHETIC title {i}", "abstract": f"SYNTHETIC {i}"}
            for i in range(500)]
    monkeypatch.setattr(small_batch, "manifest_for", lambda *args: {"pool": pool, "user_priority": [],
                                                                    "fused": [row["id"] for row in pool]})
    budgets = {}
    for effort in ("quick", "standard", "detailed"):
        budgets[effort] = small_batch.freeze_budget(TEST_EFFORT_BUDGETS[effort].__dict__, effort, "off")
    quick = {"id": "run-q", "scope_revision": 1, "budget": {"fast_path": {"N": 25},
                                                           "inspection": budgets["quick"]["inspection"]}}
    asyncio.run(small_batch.rerank_list(flow, quick, SCOPE, {}))
    output = store.steps[small_batch.RERANK_KEY]["output"]
    assert len(output["candidate_ids"]) == 400 and output["candidate_ids"] == [row["id"] for row in pool[:400]]
    # Standard and Detailed freeze what they froze before.
    for effort in ("standard", "detailed"):
        rule = budgets[effort]["inspection"]["rerank"]
        assert (rule["pool_factor"], rule["max_pool_factor"]) == (8.0, 8.0)


def test_a_candidate_set_that_moved_keeps_the_fused_order_and_says_not_applied():
    # The reranker answered, but the records it scored are no longer the window's: the list stays fused, so the
    # abstract stage's word rule reads "not applied" and works as before.
    manifest = {"user_priority": [], "reranker": {"status": "applied", "provider": "builtin", "model": RER,
                                                  "candidate_ids": ["b", "x"], "scores": [0.1, 0.9]}}
    order, told = small_batch.reranked(manifest, ["a", "b", "c"])
    assert order == ["a", "b", "c"] and told["applied"] is False and told["reason"] == "candidates_changed"


def test_a_run_queued_with_candidate_embedding_off_embeds_nothing_and_says_why(tmp_path, monkeypatch):
    """The pilot default: the reranker reads each record's title and abstract as text, so a run embeds no candidate.
    The signal is left out of the ranking and the run records the reason; the person can turn it on."""
    local = RerankingLocal()
    s = Session(tmp_path, monkeypatch, local=local, setting=BUILTIN)
    s.store.set_setting("candidate_embedding", "off")  # what an app with nothing saved does on its own
    s.store.set_setting(rerankers.SETTING, {"enabled": True, "provider": "builtin", "model": RER, "timeout_seconds": 60})
    try:
        rid, run_id, view, run = s.discover(effort="standard")
        similarity = s.store.existing_step(run_id, "source_similarity")["output"]
        listing = s.store.existing_step(run_id, small_batch.LIST_KEY)["output"]
        frozen = s.store.run(run_id)["budget"]["fast_path"]
    finally:
        s.close()
    assert frozen["candidate_embedding"] is False  # frozen when the run was queued, not read again later
    assert similarity["embedding_off_reason"] == "candidate_embedding_off" and similarity["provider"] == "off"
    assert local.documents() == 0, "no candidate was embedded"
    # The ranking left the signal out, and the list says so rather than ranking every record last in it.
    assert listing["manifest"]["embedding_model"] is None
    assert listing["signal_reasons"].get("embedding")


LOOKED_UP = "We SYNTHETIC measure the packet size that lowers the energy of a sensor node."
CROSSREF_ABSTRACT = "We SYNTHETIC report the energy a sensor node spends per packet."
# Four records without an abstract: Semantic Scholar holds 90 and 91, Crossref holds 92, nobody holds 93.
EMPTY = (90, 91, 92, 93)


class LookupPool(Pool):
    """The ranking fixture's OpenAlex, with four records that have no abstract, Semantic Scholar and Crossref.

    `delay` holds back Semantic Scholar's first answer that long (the lookup before the rerank runs out of time);
    `peak` is the most Crossref requests that were out at once. `filler` more records without an abstract, which no
    source holds, make the window wider than the 200 requests the read stage's lookup may send; OpenAlex then pages."""

    def __init__(self, delay=0.0, filler=0, refuse_s2=False, pdf=False):
        targets = [work(n, STRONG, "x") | {"abstract_inverted_index": None} for n in EMPTY]
        if pdf:  # 93, which no source holds, has an open PDF
            targets[-1] |= {"best_oa_location": {"pdf_url": "https://example.org/93.pdf", "version": "publishedVersion"}}
        self.refuse_s2 = refuse_s2
        unread = [work(1000 + n, "SYNTHETIC unread record", "x") | {"abstract_inverted_index": None} for n in range(filler)]
        super().__init__(works=pool(8) + targets + unread)
        self.delay, self.lookups, self.crossref, self.out, self.peak = delay, [], [], 0, 0
        self.wait = 0.01 if filler else 0.05
        self.slow = None  # version 4 cases: only the first `slow` Crossref requests take `wait`, the read stage's are quick

    def __call__(self, request):
        if request.url.host == "api.crossref.org":
            return self._crossref(request)
        params = request.url.params
        if (request.url.host == "api.openalex.org" and "search.semantic" not in params
                and not (params.get("per_page") == "1" and params.get("select") == "id")):
            start, size = int(params.get("cursor", "0").replace("*", "0")), int(params.get("per_page", "100"))
            more = start + size < len(self.works)
            return httpx.Response(200, json={"meta": {"count": len(self.works),
                                                      "next_cursor": str(start + size) if more else None},
                                             "results": self.works[start:start + size]})
        if request.url.host != "api.semanticscholar.org":
            return super().__call__(request)
        ids = json.loads(request.content)["ids"]
        self.lookups.append(ids)
        if self.refuse_s2:
            return written(request, httpx.Response(429, text="SYNTHETIC CloudFront refusal"))
        held = {"DOI:10.1/oa.90": LOOKED_UP, "DOI:10.1/oa.91": LOOKED_UP + " 91"}
        reply = httpx.Response(200, json=[{"paperId": f"s2-{i}", "externalIds": {"DOI": doi.removeprefix("DOI:")},
                                           "abstract": held.get(doi), "referenceCount": None} for i, doi in enumerate(ids)])
        if self.delay and len(self.lookups) == 1:
            async def late():
                await headers_out(request)
                await asyncio.sleep(self.delay)
                await headers_back(request)
                return reply
            return late()
        return written(request, reply)

    def _crossref(self, request):
        doi = request.url.path.removeprefix("/works/").replace("%2F", "/")
        self.crossref.append(doi)

        wait = self.wait if self.slow is None or len(self.crossref) <= self.slow else 0.01

        async def answer():
            await headers_out(request)  # its headers go out
            self.out += 1
            self.peak = max(self.peak, self.out)
            try:
                await asyncio.sleep(wait)
            finally:
                self.out -= 1
            await headers_back(request)
            if doi != "10.1/oa.92":
                return httpx.Response(404)
            return httpx.Response(200, json={"message": {"DOI": doi, "abstract": f"<jats:p>{CROSSREF_ABSTRACT}</jats:p>"}})
        return answer()


# The rules a budget froze before version 3 (version 2's), kept here to show such a run keeps them.
PRERANK_V2 = {"version": 2, "max_records": 400, "seconds": 8, "crossref_in_flight": 4, "max_requests": 419}
RERANK_V2 = {"version": 2, "pool_factor": 8.0, "max_pool_factor": 8.0, "hold_without_abstract": True}
# The version 3 lookup rule, kept to show such a run still holds every record no source answered, sent or not.
PRERANK_V3 = {"version": 3, "max_records": 400, "seconds": 8, "crossref_in_flight": 4, "s2_waits": 0, "s2_batch": 400,
              "s2_cooldown_skip": True, "max_requests": 418}
V3_CASES = ("v3", "text_route", "s2_refused", "window_above_200", "time_ceiling", "crossref_cut")
V4_CASES = ("never_sent", "never_sent_v3")


@pytest.mark.parametrize("case", [*V3_CASES, *V4_CASES, "v2", "first_rule", "before_first_rule"])
def test_missing_abstracts_are_looked_up_before_the_rerank_and_unfilled_records_keep_their_place(tmp_path, monkeypatch, case):
    # A record without an abstract reaches the reranker with the abstract a lookup source holds. Version 2: every such
    # record of the window is asked about (Semantic Scholar's batch, then Crossref 4 in flight), the window is 8x, and
    # one still without an abstract keeps its fused place instead of being scored on its title. Version 3: it keeps its
    # place only with a route to text or a lookup that did not settle, and a Semantic Scholar 429 fails at once, so
    # Crossref still asks within the round. Version 4: Crossref 8 in flight, and a lookup counts as open only for a
    # record a
    # request was really sent for. A budget frozen with version 3, 2 or the first rule, or before it, keeps what it did.
    freeze = small_batch.freeze_budget

    def frozen(*args):
        budget = freeze(*args)
        if case == "time_ceiling":
            budget["inspection"]["prerank_lookup"] |= {"seconds": 0.2 * WAIT_FACTOR}
        if case in ("crossref_cut", *V4_CASES):
            budget["inspection"]["prerank_lookup"] |= {"seconds": 0.5 * WAIT_FACTOR}
        if case == "never_sent_v3":
            budget["inspection"]["prerank_lookup"] = dict(PRERANK_V3) | {"seconds": 0.5 * WAIT_FACTOR}
        if case == "window_above_200" and sys.platform == "win32":
            # 200-odd lookups and their SQLite writes, in real time: on the loaded Windows runner they
            # took over 32 s (the whole test: 14 s alone in the Windows VM). The case is about every record being asked,
            # not about the ceiling, so Windows gets one it does not reach.
            budget["inspection"]["prerank_lookup"]["seconds"] = 180
        if case == "v2":
            budget["inspection"] |= {"prerank_lookup": dict(PRERANK_V2), "rerank": dict(RERANK_V2)}
        if case in ("first_rule", "before_first_rule"):
            budget["inspection"].pop("rerank")
            budget["inspection"]["prerank_lookup"] = {"max_records": 20, "seconds": 5}
        if case == "before_first_rule":
            budget["inspection"].pop("prerank_lookup")
        return budget
    monkeypatch.setattr(small_batch, "freeze_budget", frozen)
    if case == "s2_refused":  # the real cooldown, which the suite otherwise turns off
        monkeypatch.delattr(pacing.SEMANTIC_SCHOLAR_PACER, "cool_down")
    handler = LookupPool(delay=3.0 * WAIT_FACTOR if case == "time_ceiling" else 0.0,
                         filler=200 if case == "window_above_200" else 20 if case in V4_CASES else 0,
                         refuse_s2=case == "s2_refused", pdf=case == "text_route")
    if case in V4_CASES:
        handler.slow = 4  # the requests the round has out at once
    if case in ("crossref_cut", *V4_CASES):
        handler.wait = 3.0 * WAIT_FACTOR  # Semantic Scholar answers at once; Crossref is still out when the round's time ends
    local = RerankingLocal()
    s = Session(tmp_path, monkeypatch, handler=handler, local=local, setting=BUILTIN)
    # No factor saved: the run's frozen rule gives it (8 since rerank rule version 2, 4 before).
    s.store.set_setting(rerankers.SETTING, {"enabled": True, "provider": "builtin", "model": RER, "timeout_seconds": 60})
    try:
        # Standard throughout: the lookup before the rerank only runs where the list waits for the reranker.
        rid, run_id, view, run = s.discover(effort="standard")
        listing = s.store.existing_step(run_id, small_batch.LIST_KEY)["output"]
        step = s.store.existing_step(run_id, small_batch.PRERANK_LOOKUP_KEY)
        rerank = s.store.existing_step(run_id, small_batch.RERANK_KEY)["output"]
        prerank_steps = {row["operation_key"]: dict(row) for row in s.store.conn.execute(
            "SELECT operation_key, status, error_code FROM run_steps WHERE run_id = ? AND operation_key LIKE 'prerank:%'",
            (run_id,))}
        read_s2 = s.store.existing_step(run_id, "record_lookup:semantic_scholar:0")
        events = [json.loads(row[0]) for row in s.store.conn.execute(
            "SELECT payload_json FROM events WHERE run_id = ? AND type = 'step_finished'", (run_id,))]
    finally:
        s.close()
    heads = {n: next(r for r in listing["manifest"]["pool"] if r["title"] == f"{STRONG} {n}") for n in EMPTY}
    documents = local.reranked[0]
    automatic, order = listing["automatic_order"], listing["order"]
    assert sorted(order) == sorted(dict.fromkeys(listing["manifest"]["user_priority"] + automatic))
    assert rerank["pool_factor"] == (4.0 if case in ("first_rule", "before_first_rule") else 8.0)
    if case == "window_above_200":
        # Standard reads 50, so the window is 400 places: all 212 records, 204 of them without an abstract. Every one
        # is asked about: Semantic Scholar in one batch, Crossref about all 202 it left, beyond the read stage's
        # 200. Crossref answered every one it left, so none is held: they are scored on their titles.
        assert len(rerank["candidate_ids"]) + len(rerank["kept_in_place"]) == len(listing["manifest"]["pool"]) == 212
        assert step["output"]["status"] == "done" and len(step["output"]["asked"]) == 204
        assert step["output"]["rule"]["max_requests"] == 418 and step["output"]["lookup_open"] == []
        assert "unsettled" not in step["output"]
        assert [len(batch) for batch in handler.lookups] == [204]
        # Crossref's single requests 4 in flight again (8 under version 4), frozen in the run's rule.
        assert step["output"]["rule"]["crossref_in_flight"] == 4 and step["output"]["rule"]["version"] == 5
        assert len(handler.crossref) == len(set(handler.crossref)) == 202 and handler.peak == 4
        assert rerank["kept_reasons"] == {}
        return
    if case in V4_CASES:
        # Semantic Scholar answered all 24 at once (two with an abstract); Crossref had the other 22, and its 3 s
        # answers were still out when the 0.5 s round ended: the first requests went out, the rest never did (the read
        # stage asks after it, quickly, one at a time).
        versions = listing["manifest"]["versions"]
        by_doi = {versions[rid]["doi"].removeprefix("https://doi.org/").lower(): rid for rid in step["output"]["asked"]}
        sent = sorted(by_doi[doi.lower()] for doi in handler.crossref[:handler.peak])
        bare = [rid for rid in step["output"]["asked"] if rid not in step["output"]["filled"]]
        assert step["output"]["status"] == "time_ceiling" and len(bare) == 22
        if case == "never_sent_v3":
            # Version 3 (4 in flight) holds all 22, the 18 never sent among them.
            assert handler.peak == len(sent) == 4 and sorted(step["output"]["unsettled"]) == sorted(bare)
            assert "lookup_open" not in step["output"]
            assert rerank["kept_reasons"] == {rid: "no_abstract_lookup_open" for rid in bare}
            return
        # Only the 4 sent and unanswered keep their place; the 18 never asked go to the reranker on their title.
        assert handler.peak == len(sent) == 4 and sorted(step["output"]["lookup_open"]) == sent
        assert "unsettled" not in step["output"]
        assert rerank["kept_reasons"] == {rid: "no_abstract_lookup_open" for rid in sent}
        assert sorted(rid for rid in bare if rid not in sent) == sorted(rid for rid in rerank["candidate_ids"] if rid in bare)
        held = next(e for e in events if e["operation_key"] == small_batch.RERANK_KEY)
        assert held["held_no_abstract_lookup_open"] == 4
        return
    if case == "before_first_rule":
        assert step is None and not prerank_steps and "kept_reasons" not in rerank
        assert all(rerankers.document(f"{STRONG} {n}", None) in documents for n in EMPTY)
        return
    assert step["status"] == "succeeded" and sorted(step["output"]["asked"]) == sorted(h["id"] for h in heads.values())
    assert sorted(handler.lookups[0]) == [f"DOI:10.1/oa.{n}" for n in EMPTY]  # only the records without an abstract
    if case == "time_ceiling":
        assert (step["output"]["status"], step["output"]["filled"]) == ("time_ceiling", [])
        assert prerank_steps["prerank:record_lookup:semantic_scholar:0"]["error_code"] == "lookup_time_ceiling"
        assert all(heads[n]["abstract"] is None for n in EMPTY)
        # No source answered in time: every one keeps its place, because the read stage may still fill it.
        assert sorted(step["output"]["lookup_open"]) == sorted(h["id"] for h in heads.values())
        assert rerank["kept_reasons"] == {heads[n]["id"]: "no_abstract_lookup_open" for n in EMPTY}
        return
    if case == "crossref_cut":
        # Semantic Scholar answered all four (two without an abstract); Crossref was still out for those two when the
        # time ran out. Their requests went out and did not come back, so both keep their place, and the rerank's
        # event counts them.
        assert step["output"]["status"] == "time_ceiling"
        assert sorted(step["output"]["filled"]) == sorted(heads[n]["id"] for n in (90, 91))
        assert sorted(step["output"]["lookup_open"]) == sorted(heads[n]["id"] for n in (92, 93))
        assert rerank["kept_reasons"] == {heads[n]["id"]: "no_abstract_lookup_open" for n in (92, 93)}
        held = next(e for e in events if e["operation_key"] == small_batch.RERANK_KEY)
        assert held["held_no_abstract_lookup_open"] == 2
        return
    if case == "s2_refused":
        # One refused batch, no wait: Crossref asks about all four within the round and fills the one it holds.
        assert len(handler.lookups) == 1 and step["output"]["status"] == "done"
        assert sorted(handler.crossref) == [f"10.1/oa.{n}" for n in EMPTY]
        assert step["output"]["filled"] == [heads[92]["id"]] and step["output"]["lookup_open"] == []
        # The read stage's lookup came during the 429's cooldown: it sent Semantic Scholar nothing and says so.
        assert read_s2["output"]["skipped"] == "s2_cooldown" and read_s2["output"]["not_asked"] >= 1
        assert rerank["kept_reasons"] == {}
        return
    assert step["output"]["status"] == "done"
    assert sorted(step["output"]["filled"]) == sorted(heads[n]["id"] for n in (90, 91, 92))
    assert [heads[n]["abstract"] for n in EMPTY] == [LOOKED_UP, LOOKED_UP + " 91", CROSSREF_ABSTRACT, None]
    # Semantic Scholar filled two; Crossref was asked about the other two only, 4 in flight since version 2.
    assert sorted(handler.crossref) == ["10.1/oa.92", "10.1/oa.93"]
    assert handler.peak == (1 if case == "first_rule" else 2)
    for n, text in ((90, LOOKED_UP), (91, LOOKED_UP + " 91"), (92, CROSSREF_ABSTRACT)):
        assert rerankers.document(f"{STRONG} {n}", text) in documents
    if case in ("first_rule", "v3"):
        # The first rule, and version 3 for a record every source answered without an abstract and no file can reach,
        # send
        # it on its title alone.
        assert rerankers.document(f"{STRONG} 93", None) in documents
        assert rerank.get("kept_reasons", {}) == {}
        return
    # Version 2 holds 93 whatever; version 3 holds it for its open PDF. It is not sent, keeps its place, and the step
    # says why.
    assert not any(f"{STRONG} 93" in text for text in documents)
    assert rerank["kept_reasons"] == {heads[93]["id"]: "no_abstract" if case == "v2" else "no_abstract_text_route"}
    assert listing["reranker"]["applied"] is True
    assert order.index(heads[93]["id"]) == automatic.index(heads[93]["id"])


# ---- Settings ----------------------------------------------------------------------------------------


def test_with_nothing_saved_and_no_voyage_key_the_run_records_that_the_reranker_did_not_run(monkeypatch):
    # On by default with Voyage; without a key nothing is sent, the fused order stands and the step says why.
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    sent = []
    http = voyage(lambda r: sent.append(r) or httpx.Response(200))
    flow, store, _ = rerank_flow(monkeypatch, None, None, http)
    asyncio.run(small_batch.rerank_list(flow, RUN, SCOPE, {}))
    step = store.steps[small_batch.RERANK_KEY]
    assert step["status"] == "failed" and step["error_code"] == "reranker_unavailable" and sent == []
    assert (step["output"]["provider"], step["output"]["model"], step["output"]["fallback"]) == (
        "voyage", "rerank-3-lite", "fused_order")


# ---- the reranker's own allowance (`rerank_allowance_v1`) --------------------------------------------

class ClockLocal:
    """The fake built-in reranker, taking `seconds` of the run's clock and scoring the reverse of its order."""

    def __init__(self, clock, seconds):
        self.clock, self.seconds, self.reranked = clock, seconds, []

    async def rerank(self, model_id, query, documents, seconds):
        self.reranked.append(documents)
        self.clock.advance(self.seconds)
        return [i / len(documents) for i in range(len(documents))], []


def allowance_run(tmp_path, monkeypatch, plan_seconds, *, policy_edit=None, evidence=False):
    """A Standard discovery run on a fake clock whose plan took `plan_seconds` (its share is 8 s) and whose lookups
    before the rerank used all that was left of the ranking stage, with a reranker that takes 2 s. Without `evidence`
    the run is frozen as before the evidence minimum, whose debt-free carry these numbers do not assume."""
    from deixis.domain import canonical
    from deixis.domain.rules import TEST_EFFORT_BUDGETS
    from deixis.storage import db
    from deixis.workflow.run import fast_path
    from deixis.workflow.run.store import Store
    from test_fast_path_clock import FakeClock

    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    clock = FakeClock()
    store = Store(conn, clock)
    clock.store = store
    store.set_setting(rerankers.SETTING, {"enabled": True, "provider": "builtin", "model": RER, "timeout_seconds": 60})
    rid = store.create_research("SYNTHETIC allowance", "academic", "standard", ["openalex"], "fake", "fake-model", "en")
    budget = small_batch.freeze_budget(TEST_EFFORT_BUDGETS["standard"].__dict__, "standard", "off")
    policy = fast_path.freeze_budget(budget, "standard")
    if policy_edit or not evidence:
        policy = {k: v for k, v in policy.items() if k != "policy_hash"}
        if policy_edit:
            policy_edit(policy)
        if not evidence:
            policy.pop("evidence_minimum")
        policy["policy_hash"] = canonical.sha256_hex(policy)
    budget["fast_path"] = policy
    run = store.create_run(rid, "discovery", budget, None)
    store.update_run(run["id"], status="running")
    run = store.run(run["id"])
    for stage, seconds in (("plan", plan_seconds), ("search", 12)):
        fast_path.enter_stage(store, run, stage)
        clock.advance(seconds)
        fast_path.close_stage(store, run["id"], stage)
    fast_path.enter_stage(store, run, "ranking")
    # The lookups before the rerank stop at the stage cutoff, as they always did, and use all of it.
    clock.advance(max(0.0, (fast_path.stage_deadline(store, run, "ranking") - clock.now()).total_seconds()))
    local = ClockLocal(clock, 2)
    flow = SimpleNamespace(store=store, deps=SimpleNamespace(http=None, local_embedder=local),
                           _checkpoint=lambda *args: None, _stop_requested=lambda *args: False)
    pool = [{"id": rid_, "work_id": f"w-{rid_}", "title": f"SYNTHETIC title {rid_}",
             "abstract": f"SYNTHETIC abstract {rid_}"} for rid_ in ("a", "b", "c")]
    monkeypatch.setattr(small_batch, "manifest_for", lambda *args: {"pool": pool, "user_priority": [], "fused": ["a", "b", "c"]})
    monkeypatch.setattr(small_batch, "replay", lambda m: {"fused": list(m["fused"]), "ranks": {}, "reasons": {}})
    return SimpleNamespace(store=store, conn=conn, clock=clock, run=run, flow=flow, local=local, fast_path=fast_path)


def _rerank_then_read(lab):
    """Rerank, close the ranking stage, open the read stage; the step, the list and the read stage's ledger row."""
    asyncio.run(small_batch.rerank_list(lab.flow, lab.run, SCOPE, {}))
    step = lab.store.existing_step(lab.run["id"], small_batch.RERANK_KEY)
    stored = {key: step["output"].get(key) for key in ("status", "provider", "model", "candidate_ids", "scores",
                                                       "error_code")}
    listing = small_batch.build_list(manifest(["a", "b", "c"], reranker=stored))
    lab.fast_path.close_stage(lab.store, lab.run["id"], "ranking")
    lab.fast_path.enter_stage(lab.store, lab.run, "read")
    read = lab.conn.execute("SELECT * FROM fast_path_stages WHERE ledger_run_id = ? AND stage = 'read'",
                            (lab.run["id"],)).fetchone()
    return step, listing, dict(read)


def test_the_reranker_keeps_its_allowance_after_the_plan_overran_and_the_lookups_used_the_stage(tmp_path, monkeypatch):
    # The plan took 40 s of its 8, so ranking got its 4.25 s floor and the lookups used all of it; the reranker still
    # runs on its own 3 s and the list is in its order. Read is given back the 2 s the reranker ran past the cutoff.
    lab = allowance_run(tmp_path, monkeypatch, 40)
    try:
        step, listing, read = _rerank_then_read(lab)
        started = lab.fast_path.ledger_started_at(lab.store, lab.run)
        read_deadline = lab.fast_path.stage_deadline(lab.store, lab.run, "read")
    finally:
        lab.conn.close()
    assert lab.local.reranked and step["status"] == "succeeded"
    assert listing["reranker"]["applied"] is True and listing["order"] == ["c", "b", "a"]
    assert step["output"]["allowance"] == {"rule": lab.fast_path.RERANK_ALLOWANCE_RULE, "ms": 3000,
                                           "past_cutoff": "stage", "stage_left_ms": 0, "earlier_ms": 0,
                                           "past_cutoff_ms": 2000}
    # Read's allocation is the one it would have had had the reranker not run: 33 s, minus the plan's 32 s debt,
    # plus what ranking left of its 17 s base before the reranker (17 - 4.25).
    assert read["alloc_ms"] == 33000 - 32000 + (17000 - 4250)
    # The handover cap moves by the same 2 s, so the answer comes 2 s later instead of read losing them.
    assert read_deadline == started + timedelta(seconds=72)


def test_under_the_evidence_minimum_the_reranker_time_is_not_given_back_twice(tmp_path, monkeypatch):
    # No stage carries debt under the rule: the plan's 32 s overrun is not charged, ranking keeps its 17 s, and the
    # 2 s the reranker ran past the ranking cutoff are an overrun of ranking, so read gets its own base and no more.
    lab = allowance_run(tmp_path, monkeypatch, 40, evidence=True)
    try:
        step, listing, read = _rerank_then_read(lab)
        ranking = lab.conn.execute("SELECT * FROM fast_path_stages WHERE ledger_run_id = ? AND stage = 'ranking'",
                                   (lab.run["id"],)).fetchone()
    finally:
        lab.conn.close()
    assert step["status"] == "succeeded" and step["output"]["allowance"]["past_cutoff_ms"] == 2000
    assert (ranking["balance_before_ms"], ranking["alloc_ms"]) == (0, 17000)
    assert (read["balance_before_ms"], read["alloc_ms"]) == (0, 33000)


def test_the_reranker_keeps_its_allowance_when_the_handover_moment_has_already_passed(tmp_path, monkeypatch):
    lab = allowance_run(tmp_path, monkeypatch, 80)  # the plan alone ran past Standard's 70 s handover
    try:
        step, listing, _ = _rerank_then_read(lab)
        started = lab.fast_path.ledger_started_at(lab.store, lab.run)
        read_deadline = lab.fast_path.stage_deadline(lab.store, lab.run, "read")
        passed = lab.conn.execute("SELECT handover_passed_at FROM fast_path_ledgers").fetchone()[0]
    finally:
        lab.conn.close()
    assert step["status"] == "succeeded" and listing["order"] == ["c", "b", "a"]
    assert (step["output"]["allowance"]["past_cutoff"], step["output"]["allowance"]["past_cutoff_ms"]) == (
        "handover", 2000)
    # Read had nothing left before and has nothing now; the missed target is still recorded at the real moment.
    assert read_deadline == started + timedelta(seconds=72) < lab.clock.now()
    assert passed is not None


def test_a_run_frozen_before_the_allowance_gives_the_reranker_only_what_the_stage_left(tmp_path, monkeypatch):
    lab = allowance_run(tmp_path, monkeypatch, 40, policy_edit=lambda p: p.pop("rerank_allowance"))
    try:
        step, listing, read = _rerank_then_read(lab)
    finally:
        lab.conn.close()
    assert lab.local.reranked == [] and step["status"] == "failed" and step["error_code"] == "no_time_left"
    assert "allowance" not in step["output"] and listing["order"] == ["a", "b", "c"]
    assert read["alloc_ms"] == 33000 - 32000 + (17000 - 4250)


class PausingLocal:
    """A built-in reranker that takes 2 s of the run's clock and is then paused; asked again, it takes 1 s more and
    never answers."""

    def __init__(self, clock, stop):
        self.clock, self.stop, self.calls = clock, stop, 0

    async def rerank(self, model_id, query, documents, seconds):
        self.calls += 1
        self.clock.advance(2 if self.calls == 1 else 1)
        if self.calls == 1:
            self.stop.append(True)  # the person pauses the run while the reranker is out
        await asyncio.sleep(10)


def test_a_paused_rerank_keeps_the_allowance_it_used_and_resume_gets_only_the_rest(tmp_path, monkeypatch):
    lab = allowance_run(tmp_path, monkeypatch, 40)
    stop = []

    def checkpoint(run_id, revision):
        if stop:
            raise RunStopped
    local = PausingLocal(lab.clock, stop)
    lab.flow.deps.local_embedder, lab.flow._checkpoint = local, checkpoint
    lab.flow._stop_requested = lambda *args: bool(stop)
    try:
        with pytest.raises(RunStopped):
            asyncio.run(small_batch.rerank_list(lab.flow, lab.run, SCOPE, {}))
        paused = lab.store.existing_step(lab.run["id"], small_batch.RERANK_KEY)
        assert paused["status"] == "running" and paused["output"]["allowance"]["past_cutoff_ms"] == 2000
        stop.clear()  # resumed
        step, listing, read = _rerank_then_read(lab)
    finally:
        lab.conn.close()
    # The second attempt had the 1 s left of the 3 s allowance, not a fresh 3 s, and the list keeps the fused order.
    assert step["status"] == "failed" and step["error_code"] == "reranker_timeout"
    assert step["output"]["error"].endswith("within 1 s") and listing["order"] == ["a", "b", "c"]
    assert (step["output"]["allowance"]["earlier_ms"], step["output"]["allowance"]["past_cutoff_ms"]) == (2000, 3000)
    # Both attempts' 3 s are given back to read, whose allocation is the one it would have had.
    assert read["alloc_ms"] == 33000 - 32000 + (17000 - 4250)


class SpendingLocal:
    """A built-in reranker that takes the whole 3 s allowance of the run's clock and is then paused."""

    def __init__(self, clock, stop):
        self.clock, self.stop, self.calls = clock, stop, 0

    async def rerank(self, model_id, query, documents, seconds):
        self.calls += 1
        self.clock.advance(3)
        self.stop.append(True)  # the person pauses the run while the reranker is out
        await asyncio.sleep(10)


def test_a_rerank_resumed_after_its_whole_allowance_was_used_keeps_the_fused_order_and_the_record(tmp_path, monkeypatch):
    lab = allowance_run(tmp_path, monkeypatch, 40)
    stop = []

    def checkpoint(run_id, revision):
        if stop:
            raise RunStopped
    local = SpendingLocal(lab.clock, stop)
    lab.flow.deps.local_embedder, lab.flow._checkpoint = local, checkpoint
    lab.flow._stop_requested = lambda *args: bool(stop)
    try:
        with pytest.raises(RunStopped):
            asyncio.run(small_batch.rerank_list(lab.flow, lab.run, SCOPE, {}))
        paused = lab.store.existing_step(lab.run["id"], small_batch.RERANK_KEY)
        assert paused["output"]["allowance"]["past_cutoff_ms"] == 3000
        stop.clear()  # resumed with nothing left of the allowance and the stage cutoff passed
        step, listing, read = _rerank_then_read(lab)
    finally:
        lab.conn.close()
    # Nothing is asked again; the step fails with no time left and the list keeps its fused order.
    assert local.calls == 1 and step["status"] == "failed" and step["error_code"] == "no_time_left"
    assert step["output"]["fallback"] == "fused_order" and listing["order"] == ["a", "b", "c"]
    assert (step["output"]["allowance"]["earlier_ms"], step["output"]["allowance"]["past_cutoff_ms"]) == (3000, 3000)
    # The 3 s the first attempt used are given back to read once.
    assert read["alloc_ms"] == 33000 - 32000 + (17000 - 4250)
