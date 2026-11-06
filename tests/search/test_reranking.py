"""Voyage embeddings, the reranker layer and the Qwen3 built-in identity (model-free, no paid call).

Voyage is a mocked endpoint (httpx.MockTransport); the built-in model and reranker are the injected fake local embedder;
no model is downloaded and no request leaves the test. Passing shows routing, request shapes, cache identities, how a
rerank maps back to its records and what happens on failure, timeout and pause. It does not show that Qwen3, Voyage or
any reranker orders records better: retrieval quality was not measured.
"""

import asyncio
import json
import sys
from types import SimpleNamespace

import httpx
import pytest

from deixis.documents import embeddings, local_embedding, rerankers
from deixis.providers import pacing
from deixis.workflow.search import small_batch
from deixis.workflow.run.flow import RunStopped
from test_builtin_embedding_flow import BUILTIN, FakeLocal, Session
from test_lookup_flow import headers_back, headers_out, written
from test_ranking_flow import STRONG, Pool, pool, work

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
        if pdf:  # 93, which no source holds, has an open PDF (D155)
            targets[-1] |= {"best_oa_location": {"pdf_url": "https://example.org/93.pdf", "version": "publishedVersion"}}
        self.refuse_s2 = refuse_s2
        unread = [work(1000 + n, "SYNTHETIC unread record", "x") | {"abstract_inverted_index": None} for n in range(filler)]
        super().__init__(works=pool(8) + targets + unread)
        self.delay, self.lookups, self.crossref, self.out, self.peak = delay, [], [], 0, 0
        self.wait = 0.01 if filler else 0.05
        self.slow = None  # D156 cases: only the first `slow` Crossref requests take `wait`, the read stage's are quick

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
            await headers_out(request)  # its headers go out (D156)
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


# The rules a budget froze before D155 (D153's), kept here to show such a run keeps them.
PRERANK_V2 = {"version": 2, "max_records": 400, "seconds": 8, "crossref_in_flight": 4, "max_requests": 419}
RERANK_V2 = {"version": 2, "pool_factor": 8.0, "max_pool_factor": 8.0, "hold_without_abstract": True}
# D155's lookup rule, kept to show such a run still holds every record no source answered, sent or not.
PRERANK_V3 = {"version": 3, "max_records": 400, "seconds": 8, "crossref_in_flight": 4, "s2_waits": 0, "s2_batch": 400,
              "s2_cooldown_skip": True, "max_requests": 418}
D155 = ("d155", "text_route", "s2_refused", "window_above_200", "time_ceiling", "crossref_cut")
D156 = ("never_sent", "never_sent_v3")


@pytest.mark.parametrize("case", [*D155, *D156, "d153", "d152", "before_d152"])
def test_missing_abstracts_are_looked_up_before_the_rerank_and_unfilled_records_keep_their_place(tmp_path, monkeypatch, case):
    # D152: a record without an abstract reaches the reranker with the abstract a lookup source holds. D153: every such
    # record of the window is asked about (Semantic Scholar's batch, then Crossref 4 in flight), the window is 8x, and
    # one still without an abstract keeps its fused place instead of being scored on its title. D155: it keeps its
    # place only with a route to text or a lookup that did not settle, and a Semantic Scholar 429 fails at once, so
    # Crossref still asks within the round. D156: Crossref 8 in flight, and a lookup counts as open only for a record a
    # request was really sent for. A budget frozen with D155's, D153's or D152's rule, or before D152, keeps what it did.
    freeze = small_batch.freeze_budget

    def frozen(*args):
        budget = freeze(*args)
        if case == "time_ceiling":
            budget["inspection"]["prerank_lookup"] |= {"seconds": 0.2}
        if case in ("crossref_cut", *D156):
            budget["inspection"]["prerank_lookup"] |= {"seconds": 0.5}
        if case == "never_sent_v3":
            budget["inspection"]["prerank_lookup"] = dict(PRERANK_V3) | {"seconds": 0.5}
        if case == "window_above_200" and sys.platform == "win32":
            # 200-odd lookups and their SQLite writes, in real time: on the loaded Windows runner they
            # took over 32 s (the whole test: 14 s alone in the Windows VM). The case is about every record being asked,
            # not about the ceiling, so Windows gets one it does not reach.
            budget["inspection"]["prerank_lookup"]["seconds"] = 180
        if case == "d153":
            budget["inspection"] |= {"prerank_lookup": dict(PRERANK_V2), "rerank": dict(RERANK_V2)}
        if case in ("d152", "before_d152"):
            budget["inspection"].pop("rerank")
            budget["inspection"]["prerank_lookup"] = {"max_records": 20, "seconds": 5}
        if case == "before_d152":
            budget["inspection"].pop("prerank_lookup")
        return budget
    monkeypatch.setattr(small_batch, "freeze_budget", frozen)
    if case == "s2_refused":  # the real cooldown, which the suite otherwise turns off
        monkeypatch.delattr(pacing.SEMANTIC_SCHOLAR_PACER, "cool_down")
    handler = LookupPool(delay=3.0 if case == "time_ceiling" else 0.0,
                         filler=200 if case == "window_above_200" else 20 if case in D156 else 0,
                         refuse_s2=case == "s2_refused", pdf=case == "text_route")
    if case in D156:
        handler.slow = 8 if case == "never_sent" else 4  # the requests the round has out at once
    if case in ("crossref_cut", *D156):
        handler.wait = 3.0  # Semantic Scholar answers at once; Crossref is still out when the round's time ends
    local = RerankingLocal()
    s = Session(tmp_path, monkeypatch, handler=handler, local=local, setting=BUILTIN)
    # No factor saved: the run's frozen rule gives it (8 since D153, 4 before).
    s.store.set_setting(rerankers.SETTING, {"enabled": True, "provider": "builtin", "model": RER, "timeout_seconds": 60})
    try:
        rid, run_id, view, run = s.discover(**({"effort": "standard"} if case == "window_above_200" else {}))
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
    assert rerank["pool_factor"] == (4.0 if case in ("d152", "before_d152") else 8.0)
    if case == "window_above_200":
        # Standard reads 50, so the window is 400 places: all 212 records, 204 of them without an abstract. Every one
        # is asked about: Semantic Scholar in one batch (D155), Crossref about all 202 it left, beyond the read stage's
        # 200. Crossref answered every one it left, so none is held: they are scored on their titles.
        assert len(rerank["candidate_ids"]) + len(rerank["kept_in_place"]) == len(listing["manifest"]["pool"]) == 212
        assert step["output"]["status"] == "done" and len(step["output"]["asked"]) == 204
        assert step["output"]["rule"]["max_requests"] == 418 and step["output"]["lookup_open"] == []
        assert "unsettled" not in step["output"]
        assert [len(batch) for batch in handler.lookups] == [204]
        # D156: Crossref's single requests 8 in flight, frozen in the run's rule.
        assert step["output"]["rule"]["crossref_in_flight"] == 8 and step["output"]["rule"]["version"] == 4
        assert len(handler.crossref) == len(set(handler.crossref)) == 202 and handler.peak == 8
        assert rerank["kept_reasons"] == {}
        return
    if case in D156:
        # Semantic Scholar answered all 24 at once (two with an abstract); Crossref had the other 22, and its 3 s
        # answers were still out when the 0.5 s round ended: the first requests went out, the rest never did (the read
        # stage asks after it, quickly, one at a time).
        versions = listing["manifest"]["versions"]
        by_doi = {versions[rid]["doi"].removeprefix("https://doi.org/").lower(): rid for rid in step["output"]["asked"]}
        sent = sorted(by_doi[doi.lower()] for doi in handler.crossref[:handler.peak])
        bare = [rid for rid in step["output"]["asked"] if rid not in step["output"]["filled"]]
        assert step["output"]["status"] == "time_ceiling" and len(bare) == 22
        if case == "never_sent_v3":
            # D155's rule (frozen version 3, 4 in flight) holds all 22, the 18 never sent among them.
            assert handler.peak == len(sent) == 4 and sorted(step["output"]["unsettled"]) == sorted(bare)
            assert "lookup_open" not in step["output"]
            assert rerank["kept_reasons"] == {rid: "no_abstract_lookup_open" for rid in bare}
            return
        # D156: only the 8 sent and unanswered keep their place; the 14 never asked go to the reranker on their title.
        assert handler.peak == len(sent) == 8 and sorted(step["output"]["lookup_open"]) == sent
        assert "unsettled" not in step["output"]
        assert rerank["kept_reasons"] == {rid: "no_abstract_lookup_open" for rid in sent}
        assert sorted(rid for rid in bare if rid not in sent) == sorted(rid for rid in rerank["candidate_ids"] if rid in bare)
        held = next(e for e in events if e["operation_key"] == small_batch.RERANK_KEY)
        assert held["held_no_abstract_lookup_open"] == 8
        return
    if case == "before_d152":
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
    # Semantic Scholar filled two; Crossref was asked about the other two only, 4 in flight since D153's rule.
    assert sorted(handler.crossref) == ["10.1/oa.92", "10.1/oa.93"]
    assert handler.peak == (1 if case == "d152" else 2)
    for n, text in ((90, LOOKED_UP), (91, LOOKED_UP + " 91"), (92, CROSSREF_ABSTRACT)):
        assert rerankers.document(f"{STRONG} {n}", text) in documents
    if case in ("d152", "d155"):
        # D152's rule, and D155's for a record every source answered without an abstract and no file can reach, send
        # it on its title alone.
        assert rerankers.document(f"{STRONG} 93", None) in documents
        assert rerank.get("kept_reasons", {}) == {}
        return
    # D153 holds 93 whatever; D155 holds it for its open PDF. It is not sent, keeps its place, and the step says why.
    assert not any(f"{STRONG} 93" in text for text in documents)
    assert rerank["kept_reasons"] == {heads[93]["id"]: "no_abstract" if case == "d153" else "no_abstract_text_route"}
    assert listing["reranker"]["applied"] is True
    assert order.index(heads[93]["id"]) == automatic.index(heads[93]["id"])


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
