"""The built-in model and batch-by-batch embedding inside runs (slice 21, D103, tasks 4 to 7).

Records are SYNTHETIC OpenAlex works served through httpx.MockTransport; the built-in model is an injected fake local
embedder (`create_app(local_embedder=...)`) and Gemini is a mocked endpoint; the clock of the 429 wait is replaced.
Passing shows how the steps store, stop, resume, wait and fall back, not that the similarity finds relevant work.
"""

import asyncio
import json
import time
from array import array
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents import embeddings, local_embedding
from deixis.documents.local_embedding import LocalEmbeddingError
from deixis.domain.vocabulary import detect_language
from deixis.providers.common import ProviderRecord
from deixis.providers.registry import CONNECTORS
from deixis.storage import db
from deixis.workflow import english_question
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.flow import ResearchFlow
from deixis.workflow.store import Store
from deixis.workflow.views import research_view
from builtin_helpers import fake_manifest, install_fake
from fakes import FakeAdapter, valid_response
from test_ranking_flow import STRONG, Pool, client_of, discover, no_fetch, rank_rows, step_output, wait
from test_semantic_retrieval import two_page_research

BUILTIN = {"provider": "builtin", "model": local_embedding.MODEL_ID}
GEMINI = {"provider": "gemini", "model": embeddings.MODEL}
BUILTIN_STORED = f"builtin:{local_embedding.MODEL_ID}"
TURKISH = "Kablosuz algılayıcı ağlarında paket boyutunun enerji tüketimine etkisi nedir?"
KEY_TERMS = "packet size; energy consumption; wireless sensor networks"
ENGLISH_SENTENCE = "The effect of packet size on energy consumption in wireless sensor networks."


def basis(index: int) -> array:
    values = array("f", [0.0] * local_embedding.DIMENSIONS)
    values[index] = 1.0
    return values


class FakeLocal:
    """The built-in model as the flow sees it: the query and records naming `target` at one place, the rest at another.

    `hook(calls, texts, kind)` runs before each answer (a pause, a setting change); `fail_on` makes that call (1-based)
    fail; `unavailable` fails every call as a model that is not installed does."""

    def __init__(self, target=STRONG, fail_on=None, unavailable=False, hook=None, integrity=None):
        self.target, self.fail_on, self.unavailable, self.hook = target, fail_on, unavailable, hook
        self.calls: list[tuple[str, int]] = []
        self.texts: list[str] = []
        self.integrity = integrity or local_embedding.Integrity(local_embedding.builtin_paths(Path("/nonexistent-deixis")))
        self.removing = self.installing = False
        self.runner = self.python = None

    async def embed(self, texts, kind):
        self.calls.append((kind, len(texts)))
        if self.hook:
            self.hook(len(self.calls), texts, kind)
        if self.unavailable:
            raise LocalEmbeddingError("builtin_unavailable", "SYNTHETIC the built-in model is not installed")
        if self.fail_on == len(self.calls):
            raise LocalEmbeddingError("builtin_stopped", "SYNTHETIC the runner stopped")
        self.texts += texts if kind == "document" else []
        return [basis(0) if kind == "query" or (self.target and self.target in text) else basis(1) for text in texts]

    async def close(self):
        pass

    def documents(self):
        return sum(n for kind, n in self.calls if kind == "document")


def make_app(tmp_path, monkeypatch, handler, local=None, workflow="sw", gemini_key=False, adapter=None):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    if gemini_key:
        monkeypatch.setenv("GEMINI_API_KEY", "SYNTHETIC-key")
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", workflow)
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_workflow=workflow, search_query="code",
                               protocol_approval="as_proposed", fulltext_fetch="off"),
                      adapters={"fake": adapter or FakeAdapter(valid_response)},
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), fetcher=no_fetch,
                      extra_hosts=("testserver",), trusted_clients=("testclient",), local_embedder=local or FakeLocal())


class Session:
    """An app with a client, its setting chosen before the first research."""

    def __init__(self, tmp_path, monkeypatch, handler=None, local=None, setting=BUILTIN, **kwargs):
        self.handler = handler or Pool()
        self.local = local or FakeLocal()
        self.app = make_app(tmp_path, monkeypatch, self.handler, self.local, **kwargs)
        self.client = client_of(self.app)
        self.store = self.app.state.store
        if setting is not None:
            self.store.set_setting("semantic_search", setting)

    def close(self):
        self.client.__exit__(None, None, None)

    def discover(self, **body):
        return discover(self.client, **body)

    def again(self, rid):
        run_id = self.client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        return run_id, *wait(self.client, rid, run_id)

    def settled(self, rid, run_id):
        deadline = time.time() + 30
        while time.time() < deadline:
            run = self.store.run(run_id)
            if run["status"] in ("completed", "failed", "paused", "cancelled"):
                return run
            time.sleep(0.05)
        raise AssertionError("the run did not settle")

    def resume(self, rid, run_id):
        self.client.post(f"/api/runs/{run_id}/resume")
        return wait(self.client, rid, run_id)

    def pause(self, run_id=None):
        """Ask the running run (by default the latest one) to pause, as the pause button does."""
        run_id = run_id or self.latest_run()
        self.store.update_run(run_id, event="run_pause_requested", status="pause_requested", pause_reason="user_requested")

    def latest_run(self):
        return self.store.conn.execute("SELECT id FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()[0]

    def latest_research(self):
        return self.store.conn.execute("SELECT id FROM researches ORDER BY rowid DESC LIMIT 1").fetchone()[0]

    def step(self, run_id, key="source_similarity"):
        return self.store.existing_step(run_id, key)


@pytest.fixture
def session(tmp_path, monkeypatch):
    opened = []

    def open_session(path=None, **kwargs):
        s = Session(tmp_path / (path or f"s{len(opened)}"), monkeypatch, **kwargs)
        opened.append(s)
        return s
    yield open_session
    for s in opened:
        s.close()


@pytest.fixture
def small_batches(monkeypatch):
    monkeypatch.setattr(local_embedding, "LOCAL_BATCH", 10)
    monkeypatch.setattr(embeddings, "BATCH", 10)


@pytest.fixture
def clock(monkeypatch):
    """The 429 wait's clock: each slice returns at once and is counted, and the fake monotonic clock moves by the slice
    times `lag` (1 by default; more is an event loop that wakes late); `on_slice` may act on it."""
    state = SimpleNamespace(slices=0, on_slice=None, now=0.0, lag=1.0)

    async def sleep(seconds):
        state.slices += 1
        state.now += seconds * state.lag
        if state.on_slice:
            state.on_slice(state.slices)
    monkeypatch.setattr(embeddings, "_sleep", sleep)
    monkeypatch.setattr(embeddings, "_clock", lambda: state.now)
    return state


class Gemini(Pool):
    """The ranking fixture's OpenAlex and Gemini, with a script of answers for the embedding requests: each item is a
    status and headers/body for one request, None answers normally. Requests past the script answer normally."""

    def __init__(self, script=(), **kwargs):
        super().__init__(embedding=STRONG, **kwargs)
        self.script, self.embedding_requests = list(script), []

    def _embed(self, request):
        requests = json.loads(request.content)["requests"]
        self.embedding_requests.append((requests[0].get("taskType"), len(requests)))
        answer = self.script.pop(0) if self.script else None
        if answer is not None:
            status, headers, body = answer
            return httpx.Response(status, headers=headers, json=body)
        return super()._embed(request)


def four_signals(tmp_path, monkeypatch, name, **kwargs):
    s = Session(tmp_path / name, monkeypatch, **kwargs)
    try:
        rid, run_id, view, run = s.discover()
        return rank_rows(s.store, rid), step_output(s.store, run_id, "ranking"), s.step(run_id), run
    finally:
        s.close()


# ---- task 4: the provider -------------------------------------------------------------------------

def test_options_list_the_built_in_model_second_and_refuse_it_until_it_is_installed(tmp_path, monkeypatch):
    fake_manifest(monkeypatch)
    paths = local_embedding.builtin_paths(tmp_path / "data")
    local = FakeLocal(integrity=local_embedding.Integrity(paths))
    app = make_app(tmp_path, monkeypatch, Pool(), local)
    client = client_of(app)
    try:
        view = client.get("/api/semantic-search").json()
        refused = client.put("/api/semantic-search", json={"provider": "builtin"})
        install_fake(paths)
        asyncio.run(app.state.builtin.start())  # the full check a start makes
        saved = client.put("/api/semantic-search", json={"provider": "builtin"}).json()
    finally:
        client.__exit__(None, None, None)
    assert [o["provider"] for o in view["options"]] == ["gemini", "builtin", "openai", "ollama", "lm_studio", "off"]
    builtin = view["options"][1]
    assert (builtin["available"], builtin["reason"], builtin["models"]) == (False, "Not downloaded", [local_embedding.MODEL_ID])
    assert refused.status_code == 422 and refused.json()["detail"] == "Not downloaded"
    assert (saved["provider"], saved["model"]) == ("builtin", "bge-small-en-v1.5@aa8f8b0:256")
    assert embeddings.Embedder("builtin", saved["model"]).stored_model == "builtin:bge-small-en-v1.5@aa8f8b0:256"
    # The built-in model is never chosen by itself.
    assert embeddings.chosen(None) == ("off", None)
    monkeypatch.setenv("GEMINI_API_KEY", "SYNTHETIC-key")
    assert embeddings.chosen(None) == ("gemini", embeddings.MODEL)


# ---- task 5: batches, partial results, pause, the frozen model --------------------------------------

def test_a_failed_third_batch_keeps_the_first_two_and_the_code_signals_rank_the_same(tmp_path, monkeypatch, small_batches):
    off, off_output, _, _ = four_signals(tmp_path, monkeypatch, "off", setting={"provider": "off", "model": None})
    partial, output, step, run = four_signals(tmp_path, monkeypatch, "partial", local=FakeLocal(fail_on=4))
    assert off == partial and run["status"] == "completed"
    assert (step["status"], step["error_code"]) == ("partial", "embedding_failed")
    assert (step["output"]["embedded"], step["output"]["missing"], step["output"]["sources"]) == (20, 4, 24)
    assert output["signals"]["embedding"] == {"ran": True, "available": 20}
    assert output["embedding_model"] == BUILTIN_STORED and output["embedding_this_run"] == 20


def test_a_pause_after_a_batch_stops_the_run_and_the_resumed_run_embeds_only_what_is_missing(session, small_batches):
    whole = session("whole")
    whole.discover()
    s = session("paused")

    def hook(calls, texts, kind):
        if calls == 3:  # the query, the first batch, then this second batch
            s.pause()
    s.local.hook = hook
    rid, run_id, view, run = s.discover()
    stored = len(s.store.source_similarities(rid, 1, BUILTIN_STORED))
    step = s.step(run_id)
    s.local.hook = None
    view, run = s.resume(rid, run_id)
    assert (run["status"], stored, step["status"]) == ("completed", 20, "running")
    assert (step["output"]["provider"], step["output"]["stored_model"], step["output"]["embedded"]) == ("builtin", BUILTIN_STORED, 20)
    # Every record was embedded once: the same document calls as the run that was never paused.
    assert s.local.documents() == whole.local.documents() == 24
    assert [c for c in s.local.calls if c[0] == "document"] == [c for c in whole.local.calls if c[0] == "document"]
    assert s.local.calls.count(("query", 1)) == 2  # the query is embedded again after the resume
    # The step counts across the resume: all 24 embedded by this step, none stored before it.
    assert (s.step(run_id)["output"]["embedded"], s.step(run_id)["output"]["from_store"], s.step(run_id)["status"]) == (24, 0, "succeeded")


def test_a_429_is_waited_out_and_the_same_batch_sent_again(session, small_batches, clock):
    s = session(handler=Gemini([None, (429, {"Retry-After": "2"}, {"error": {"message": "SYNTHETIC slow down"}})]),
                setting=GEMINI, gemini_key=True)
    rid, run_id, view, run = s.discover()
    step = s.step(run_id)
    assert step["status"] == "succeeded" and clock.slices == 2
    assert (step["output"]["rate_limited_waits"], step["output"]["waited_seconds"]) == (1, 2)
    requests = s.handler.embedding_requests
    assert requests[1] == requests[2] == ("RETRIEVAL_DOCUMENT", 10)  # the batch that was refused went again
    assert step["output"]["provider"] == "gemini" and step["output"]["stored_model"] == embeddings.MODEL


def test_a_429_asking_for_more_than_the_budget_is_not_waited_and_gemini_s_retry_delay_is_read(session, small_batches, clock):
    too_long = [None, None, (429, {"Retry-After": "500"}, {"error": {"message": "SYNTHETIC"}})]
    s = session("long", handler=Gemini(too_long), setting=GEMINI, gemini_key=True)
    rid, run_id, view, run = s.discover()
    step = s.step(run_id)
    assert (step["status"], clock.slices, step["output"]["embedded"]) == ("partial", 0, 10)
    assert "500 s would pass the step's 180 s limit" in step["error_json"]
    body = {"error": {"message": "SYNTHETIC", "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "3s"}]}}
    t = session("delay", handler=Gemini([None, (429, {}, body)]), setting=GEMINI, gemini_key=True)
    rid, run_id, view, run = t.discover()
    assert t.step(run_id)["output"]["waited_seconds"] == 3 and clock.slices == 3


def test_three_429s_on_one_batch_end_the_step_partial(session, small_batches, clock):
    limited = (429, {"Retry-After": "1"}, {"error": {"message": "SYNTHETIC"}})
    s = session(handler=Gemini([None, None, limited, limited, limited, limited]), setting=GEMINI, gemini_key=True)
    rid, run_id, view, run = s.discover()
    step = s.step(run_id)
    assert (step["status"], step["output"]["rate_limited_waits"], step["output"]["embedded"]) == ("partial", 3, 10)
    assert run["status"] == "completed"


def test_the_built_in_model_not_installed_fails_the_step_and_nothing_else(tmp_path, monkeypatch, small_batches):
    off, _, _, _ = four_signals(tmp_path, monkeypatch, "off", setting={"provider": "off", "model": None})
    down, output, step, run = four_signals(tmp_path, monkeypatch, "down", local=FakeLocal(unavailable=True))
    assert off == down and run["status"] == "completed"
    assert (step["status"], step["error_code"]) == ("failed", "embedding_failed")
    assert "builtin_unavailable" in step["error_json"]
    assert output["signals"]["embedding"]["reason"] == "no_stored_similarity"


def test_with_the_built_in_model_chosen_no_request_goes_to_gemini(session, monkeypatch):
    s = session(handler=Gemini(), gemini_key=True)  # a Gemini key is set, the built-in model is chosen
    rid, run_id, view, run = s.discover()
    assert s.handler.embedding_requests == [] and s.local.documents() == 24


def test_a_pause_during_a_429_wait_stops_within_a_second_and_the_batch_is_not_sent(session, small_batches, clock):
    s = session(handler=Gemini([None, (429, {"Retry-After": "60"}, {"error": {"message": "SYNTHETIC"}})]),
                setting=GEMINI, gemini_key=True)
    clock.on_slice = lambda n: n == 3 and s.pause()
    rid, run_id, view, run = s.discover()
    assert run["status"] == "paused" and clock.slices == 3
    assert len(s.handler.embedding_requests) == 2  # the refused batch was not sent again
    assert s.step(run_id)["output"]["waited_seconds"] == 3


def test_a_new_scope_revision_during_a_429_wait_cancels_the_run(session, small_batches, clock):
    s = session(handler=Gemini([None, (429, {"Retry-After": "60"}, {"error": {"message": "SYNTHETIC"}})]),
                setting=GEMINI, gemini_key=True)
    def revise(n):
        if n == 2:
            rid = s.latest_research()
            s.store.revise_scope(rid, s.store.research(rid)["version"], s.store.scope(rid)["question"] + " again", None)
    clock.on_slice = revise
    rid = s.client.post("/api/researches", json={"question": "What is the effect of packet size on energy?", "model_connection": "fake",
                                                 "requested_model": "fake-model", "effort": "quick"}).json()["research"]["id"]
    run_id = s.client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    run = s.settled(rid, run_id)
    assert (run["status"], run["pause_reason"], clock.slices) == ("cancelled", "scope_revised", 2)


def test_two_long_429s_share_the_step_s_budget(session, small_batches, clock):
    limited = (429, {"Retry-After": "100"}, {"error": {"message": "SYNTHETIC"}})
    s = session(handler=Gemini([None, limited, None, limited]), setting=GEMINI, gemini_key=True)
    rid, run_id, view, run = s.discover()
    step = s.step(run_id)
    assert (step["status"], step["output"]["waited_seconds"], step["output"]["embedded"]) == ("partial", 100, 10)


def test_a_setting_changed_during_the_embedding_does_not_change_this_run_s_model(session, small_batches):
    s = session(handler=Gemini(), setting=GEMINI, gemini_key=True)
    original_embed = s.handler._embed

    def embed(request):
        response = original_embed(request)
        if len(s.handler.embedding_requests) == 3:  # the query and two batches
            s.store.set_setting("semantic_search", BUILTIN)
            s.store.set_setting("semantic_search", {"provider": "off", "model": None})
        return response
    s.handler._embed = embed
    rid, run_id, view, run = s.discover()
    output = step_output(s.store, run_id, "ranking")
    step = s.step(run_id)
    assert (step["status"], step["output"]["provider"], step["output"]["embedded"]) == ("succeeded", "gemini", 24)
    assert output["embedding_model"] == embeddings.MODEL and output["signals"]["embedding"]["ran"] is True
    assert s.local.calls == []


def test_a_resumed_run_ends_with_the_model_its_step_opened_with(session, small_batches):
    s = session(handler=Gemini(), setting=GEMINI, gemini_key=True)
    original_embed = s.handler._embed

    def embed(request):
        response = original_embed(request)
        if len(s.handler.embedding_requests) == 2:
            s.pause()
        return response
    s.handler._embed = embed
    rid, run_id, view, run = s.discover()
    assert run["status"] == "paused"
    s.store.set_setting("semantic_search", BUILTIN)  # changed while paused
    view, run = s.resume(rid, run_id)
    step = s.step(run_id)
    assert (run["status"], step["output"]["provider"], step["output"]["stored_model"]) == ("completed", "gemini", embeddings.MODEL)
    assert step_output(s.store, run_id, "ranking")["embedding_model"] == embeddings.MODEL and s.local.calls == []


def test_stored_similarities_are_read_when_the_model_is_gone_and_nothing_new_is_embedded(session):
    s = session()
    rid, first, view, run = s.discover()
    s.local.unavailable = True  # the built-in model was removed
    calls = len(s.local.calls)
    run_id, view, run = s.again(rid)
    step, output = s.step(run_id), step_output(s.store, run_id, "ranking")
    assert len(s.local.calls) == calls  # no call at all, not even the query
    assert (step["status"], step["output"]["embedded"], step["output"]["from_store"]) == ("succeeded", 0, 24)
    assert output["signals"]["embedding"] == {"ran": True, "available": 24} and output["embedding_from_store"] == 24
    assert output["embedding_model"] == BUILTIN_STORED


def test_with_nothing_missing_the_step_still_opens_and_the_ranking_reads_the_fifth_signal(session):
    s = session()
    rid, first, view, run = s.discover()
    calls = len(s.local.calls)
    run_id, view, run = s.again(rid)
    step = s.step(run_id)
    assert len(s.local.calls) == calls and step["status"] == "succeeded"
    assert (step["output"]["embedded"], step["output"]["from_store"], step["output"]["provider"]) == (0, 24, "builtin")
    assert step_output(s.store, run_id, "ranking")["signals"]["embedding"]["ran"] is True


def test_every_finish_keeps_the_identity_and_an_old_step_takes_it_once_on_resume(session, small_batches, tmp_path, monkeypatch):
    for name, local, status in (("ok", FakeLocal(), "succeeded"), ("partial", FakeLocal(fail_on=3), "partial"),
                                ("failed", FakeLocal(unavailable=True), "failed")):
        s = session(name, local=local)
        rid, run_id, view, run = s.discover()
        step = s.step(run_id)
        assert step["status"] == status
        assert (step["output"]["provider"], step["output"]["stored_model"]) == ("builtin", BUILTIN_STORED)
    # A step opened before this slice (no output) and resumed takes the current setting once, marked.
    store = Store(db.connect(tmp_path / "old.sqlite"))
    db.migrate(store.conn)
    rid = store.create_research("What is SYNTHETIC routing?", "academic", "quick", ["openalex"], "fake", "m", None)
    run = store.create_run(rid, "discovery", {}, None)
    store.step(run["id"], "source_similarity", "similarity:gemini-embedding-2")
    store.set_setting("semantic_search", BUILTIN)
    flow = object.__new__(ResearchFlow)
    flow.store, flow.deps = store, SimpleNamespace(http=None, local_embedder=FakeLocal())
    asyncio.run(flow._source_similarity(run, store.scope(rid), []))
    output = store.existing_step(run["id"], "source_similarity")["output"]
    assert (output["identity_from"], output["provider"], output["stored_model"]) == ("resume", "builtin", BUILTIN_STORED)


def test_the_wait_budget_is_kept_across_a_pause_and_a_failed_step_keeps_its_waits(session, small_batches, clock):
    limited = lambda seconds: (429, {"Retry-After": str(seconds)}, {"error": {"message": "SYNTHETIC"}})
    # query, batch 1, batch 2 refused for 120 s (paused at 50); after the resume: query, batch 2 refused for 150 s.
    s = session("budget", handler=Gemini([None, None, limited(120), None, limited(150)]), setting=GEMINI, gemini_key=True)
    clock.on_slice = lambda n: n == 50 and s.pause()
    rid, run_id, view, run = s.discover()
    assert run["status"] == "paused" and s.step(run_id)["output"]["waited_seconds"] == 50
    clock.on_slice = None
    view, run = s.resume(rid, run_id)
    step = s.step(run_id)
    assert (step["status"], step["output"]["waited_seconds"], clock.slices) == ("partial", 50, 50)
    assert "130 s left" in step["error_json"] and step["output"]["provider"] == "gemini"
    # A step that failed after a wait keeps the wait and the identity.
    t = session("failed", handler=Gemini([limited(5), (503, {}, {"error": {"message": "SYNTHETIC down"}})]),
                setting=GEMINI, gemini_key=True)
    rid, run_id, view, run = t.discover()
    step = t.step(run_id)
    assert (step["status"], step["output"]["waited_seconds"], step["output"]["stored_model"]) == ("failed", 5, embeddings.MODEL)


# ---- passages: the answer and the table column ------------------------------------------------------

def english_research(tmp_path, question="How does depth-based routing change the energy use of sensor nodes?"):
    """`two_page_research` with an English question: one uploaded two-page PDF, one page on topic."""
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research(question, "attached", "quick", [], "fake", "m", None)
    record = ProviderRecord(provider_record_id="seed", title="SYNTHETIC routing paper", authors=[], year=None, venue=None,
                            publication_type=None, doi=None, landing_url=None, oa_pdf_url=None, oa_pdf_version=None,
                            version_label=None, abstract=None, abstract_origin=None, identifiers={}, raw={})
    svid, _ = store.upsert_provider_source("known_list", record, None)
    store.add_to_corpus(rid, svid, "search", selection_state="included", selection_origin="user")
    pages = ["SYNTHETIC. The bakery sells bread every morning.", "SYNTHETIC. Depth-based routing lowers the energy use of sensor nodes."]
    extraction = SimpleNamespace(status="succeeded", error=None, page_count=2,
                                 pages=[SimpleNamespace(text=text, physical_page=n, printed_label=None) for n, text in enumerate(pages, 1)])
    store.add_asset_with_pages(svid, "abc", 100, "abc.pdf", "user_upload", None, "a.pdf", extraction, "test", lambda t: [(0, len(t), t)])
    return store, rid, svid, store.create_run(rid, "answer", {}, None)


def rank_passages(store, rid, svid, run, local, handler=None, query_text=None, key="semantic_retrieval"):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler or (lambda r: httpx.Response(404)))) as client:
            flow = object.__new__(ResearchFlow)
            flow.store, flow.deps = store, SimpleNamespace(http=client, local_embedder=local)
            return await flow._semantic_ranking(run, store.scope(rid), [svid], query_text=query_text, key=key)
    return asyncio.run(go())


def test_a_failed_passage_batch_returns_the_passages_that_have_vectors_and_a_resume_embeds_the_rest(tmp_path, monkeypatch):
    monkeypatch.setattr(local_embedding, "LOCAL_BATCH", 1)
    store, rid, svid, run = english_research(tmp_path)
    store.set_setting("semantic_search", BUILTIN)
    local = FakeLocal(target="Depth-based", fail_on=3)  # the query, the first page, then the second fails
    ranked = rank_passages(store, rid, svid, run, local)
    step = store.existing_step(run["id"], "semantic_retrieval")
    assert [p["physical_page"] for p in ranked] == [1] and step["status"] == "partial"
    flow = object.__new__(ResearchFlow)
    flow.store = store
    given = flow._retrieve(rid, store.scope(rid), [svid], 2, ranked)
    assert sorted(p["physical_page"] for p in given) == [1, 2]  # the page without a vector comes from the lexical side
    again = FakeLocal(target="Depth-based")
    ranked = rank_passages(store, rid, svid, run, again)
    assert again.calls == [("query", 1), ("document", 1)] and "Depth-based" in ranked[0]["text"]
    assert store.existing_step(run["id"], "semantic_retrieval")["status"] == "succeeded"


def test_with_every_passage_vector_stored_only_the_query_is_embedded_or_the_passages_fall_back(tmp_path):
    store, rid, svid, run = english_research(tmp_path)
    store.set_setting("semantic_search", BUILTIN)
    rank_passages(store, rid, svid, run, FakeLocal(target="Depth-based"))
    ready = FakeLocal(target="Depth-based")
    ranked = rank_passages(store, rid, svid, run, ready)
    assert ready.calls == [("query", 1)] and "Depth-based" in ranked[0]["text"]
    assert store.existing_step(run["id"], "semantic_retrieval")["status"] == "succeeded"
    gone = FakeLocal(unavailable=True)
    assert rank_passages(store, rid, svid, run, gone) is None
    step = store.existing_step(run["id"], "semantic_retrieval")
    assert step["status"] == "failed" and "builtin_unavailable" in step["error_json"]
    assert len(store.passage_embeddings([p["id"] for p in store.passages_for(svid)], BUILTIN_STORED)) == 2  # kept
    # A table column's passages behave the same.
    column = rank_passages(store, rid, svid, run, FakeLocal(target="Depth-based"), query_text="energy use", key="semantic:col")
    assert column is not None and store.existing_step(run["id"], "semantic:col")["output"]["query_origin"] == "column"
    assert rank_passages(store, rid, svid, run, FakeLocal(unavailable=True), query_text="energy use", key="semantic:col2") is None


def test_the_uploaded_pdf_passages_sent_to_the_provider_are_counted_once(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "SYNTHETIC-key")
    store, rid, svid, run = two_page_research(tmp_path)  # its one PDF is a person's upload

    def handler(request):
        rows = json.loads(request.content)["requests"]
        return httpx.Response(200, json={"embeddings": [{"values": [1.0, 0.0]} for _ in rows]})
    rank_passages(store, rid, svid, run, None, handler)
    first = store.existing_step(run["id"], "semantic_retrieval")["output"]
    rank_passages(store, rid, svid, run, None, handler)  # the same step again, as a resumed answer run does
    again = store.existing_step(run["id"], "semantic_retrieval")["output"]
    store.update_run(run["id"], status="completed")
    later = store.create_run(rid, "answer", {}, None)
    rank_passages(store, rid, svid, later, None, handler)
    second = store.existing_step(later["id"], "semantic_retrieval")["output"]
    assert (first["uploaded_files_confirmed"], first["uploaded_passages_confirmed"]) == (1, 2)
    assert (again["uploaded_files_confirmed"], again["uploaded_passages_confirmed"]) == (1, 2)  # a file is counted once per step
    assert (second["uploaded_files_confirmed"], second["uploaded_passages_confirmed"], second["from_store"]) == (0, 0, 2)
    assert (first["uploaded_files_attempted"], first["uploaded_passages_attempted"]) == (1, 2)


# ---- task 6: the English sentence ---------------------------------------------------------------------

def test_an_english_question_is_the_query_itself_and_no_row_is_written(session):
    s = session()
    rid, run_id, view, run = s.discover()
    step = s.step(run_id)
    assert step["output"]["query_origin"] == "question" and s.store.english_question(rid, 1) is None
    assert step["output"]["query_sha256"] == english_question.query_sha256(s.store.scope(rid)["question"])


def test_a_turkish_question_without_a_sentence_leaves_the_built_in_arm_off_and_says_why(session):
    assert detect_language(TURKISH, None) == "other"
    s = session()
    rid, run_id, view, run = s.discover(question=TURKISH, key_terms=KEY_TERMS)
    output = step_output(s.store, run_id, "ranking")
    assert s.step(run_id) is None and s.local.calls == []
    assert output["signals"]["embedding"]["reason"] == "english_question_missing"
    assert view["semantic"]["arm"] == "english_question_missing" and view["semantic"]["needs_english_question"] is True
    # With the sentence saved, the next discovery run of the same revision embeds it.
    saved = s.client.put(f"/api/researches/{rid}/english-question",
                         json={"text": ENGLISH_SENTENCE, "expected_version": view["research"]["version"]})
    assert saved.status_code == 200 and saved.json()["semantic"]["english_question"] == {"text": ENGLISH_SENTENCE, "origin": "user"}
    assert saved.json()["research"]["current_scope_revision"] == view["research"]["current_scope_revision"]
    run_id, view, run = s.again(rid)
    step = s.step(run_id)
    assert (step["output"]["query_origin"], step["output"]["query_sha256"]) == (
        "english_question", english_question.query_sha256(ENGLISH_SENTENCE))
    assert s.local.calls[0] == ("query", 1)


def test_the_answer_s_passage_step_records_why_the_built_in_model_did_not_rank(tmp_path):
    store, rid, svid, run = two_page_research(tmp_path)  # a Turkish question
    store.set_setting("semantic_search", BUILTIN)
    local = FakeLocal()
    assert rank_passages(store, rid, svid, run, local) is None and local.calls == []
    step = store.existing_step(run["id"], "semantic_retrieval")
    assert step["status"] == "succeeded" and step["output"]["reason"] == "english_question_missing"
    assert step["output"]["skipped"] is True
    # A table column whose text is not English is ranked by words only under the built-in model.
    assert rank_passages(store, rid, svid, run, local, query_text="Enerji tüketimi ölçümü", key="semantic:c") is None
    assert store.existing_step(run["id"], "semantic:c")["output"]["reason"] == "column_not_english" and local.calls == []


def test_writing_the_sentence_is_checked_once_per_revision_and_raises_the_version(session):
    s = session()
    rid = s.client.post("/api/researches", json={"question": TURKISH, "model_connection": "fake", "requested_model": "m",
                                                 "effort": "quick", "key_terms": KEY_TERMS}).json()["research"]["id"]
    version = s.store.research(rid)["version"]
    put = lambda body: s.client.put(f"/api/researches/{rid}/english-question", json=body)
    assert put({"text": "Kablosuz ağlarda enerji tüketimi nasıl ölçülür?", "expected_version": version}).status_code == 422
    assert put({"text": "   ", "expected_version": version}).status_code == 422
    assert put({"text": "energy " * 90, "expected_version": version}).status_code == 422  # over 500 characters
    assert put({"text": ENGLISH_SENTENCE, "expected_version": version - 1}).status_code == 409
    stale_key = DecisionStore(s.store).staleness_key(rid)
    events = s.store.conn.execute("SELECT COUNT(*) FROM events WHERE research_id = ? AND type = 'english_question_saved'", (rid,)).fetchone()[0]
    assert put({"text": ENGLISH_SENTENCE, "expected_version": version}).status_code == 200
    assert s.store.research(rid)["version"] == version + 1
    assert put({"text": ENGLISH_SENTENCE, "expected_version": version + 1}).status_code == 409  # once per revision
    assert DecisionStore(s.store).staleness_key(rid) == stale_key and s.store.research(rid)["current_scope_revision"] == 1
    event = s.store.conn.execute("SELECT payload_json FROM events WHERE research_id = ? AND type = 'english_question_saved'",
                                 (rid,)).fetchall()
    assert events == 0 and [json.loads(e[0]) for e in event] == [{"scope_revision": 1, "origin": "user"}]


def test_the_question_is_already_english_writes_the_question_itself_without_a_language_check(session):
    named = "Öztürk, Müller and Çelik routing energy of Işıklı Şahinoğlu sensor networks"
    assert detect_language(named, None) == "other"  # the rule misreads this English question
    s = session()
    rid = s.client.post("/api/researches", json={"question": named, "model_connection": "fake", "requested_model": "m",
                                                 "effort": "quick", "key_terms": KEY_TERMS}).json()["research"]["id"]
    version = s.store.research(rid)["version"]
    both = s.client.put(f"/api/researches/{rid}/english-question",
                        json={"use_question": True, "text": "SYNTHETIC other text", "expected_version": version})
    assert both.status_code == 422  # no text from the client on this path
    view = s.client.put(f"/api/researches/{rid}/english-question", json={"use_question": True, "expected_version": version}).json()
    assert view["semantic"]["english_question"] == {"text": named, "origin": "question"}
    assert s.store.research(rid)["version"] == version + 1
    assert s.store.conn.execute("SELECT COUNT(*) FROM events WHERE research_id = ? AND type = 'english_question_saved'", (rid,)).fetchone()[0] == 1


def test_a_key_term_revision_keeps_the_sentence_and_a_new_question_does_not(session):
    s = session()
    rid = s.client.post("/api/researches", json={"question": TURKISH, "model_connection": "fake", "requested_model": "m",
                                                 "effort": "quick", "key_terms": KEY_TERMS}).json()["research"]["id"]
    s.store.save_english_question(rid, s.store.research(rid)["version"], ENGLISH_SENTENCE)
    s.store.revise_scope(rid, s.store.research(rid)["version"], TURKISH, None, key_terms="packet size; energy")
    assert s.store.english_question(rid, 2)["text"] == ENGLISH_SENTENCE
    s.store.revise_scope(rid, s.store.research(rid)["version"], TURKISH.replace("etkisi", "rolü"), None)
    assert s.store.english_question(rid, 3) is None


def test_gemini_takes_the_question_as_written_and_never_the_sentence(session, small_batches):
    s = session(handler=Gemini(), setting=GEMINI, gemini_key=True)
    texts = []
    original = s.handler._embed

    def embed(request):
        texts.extend(r["content"]["parts"][0]["text"] for r in json.loads(request.content)["requests"]
                     if r.get("taskType") == "RETRIEVAL_QUERY")
        return original(request)
    s.handler._embed = embed
    rid = s.client.post("/api/researches", json={"question": TURKISH, "model_connection": "fake", "requested_model": "m",
                                                 "effort": "quick", "key_terms": KEY_TERMS}).json()["research"]["id"]
    s.store.save_english_question(rid, s.store.research(rid)["version"], ENGLISH_SENTENCE)
    run_id, view, run = s.again(rid)
    assert texts == [TURKISH] and s.step(run_id)["output"]["query_origin"] == "question"


def test_a_legacy_research_follows_the_same_rule(session):
    s = session(workflow="legacy")
    rid, run_id, view, run = s.discover(question=TURKISH)
    assert s.step(run_id) is None and s.local.calls == []
    s.store.save_english_question(rid, s.store.research(rid)["version"], ENGLISH_SENTENCE)
    run_id, view, run = s.again(rid)
    assert s.step(run_id)["output"]["query_origin"] == "english_question" and s.local.calls[0] == ("query", 1)


def test_an_older_library_migrates_with_no_sentences(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    assert conn.execute("SELECT COUNT(*) FROM scope_english_questions").fetchone()[0] == 0
    assert max(int(row[0]) for row in conn.execute("SELECT version FROM schema_migrations")) == 53


# ---- task 7: the view, the uploaded-PDF line and the protocol ------------------------------------------

def test_the_semantic_field_names_each_arm_and_carries_no_count(tmp_path, monkeypatch):
    fake_manifest(monkeypatch)
    paths = local_embedding.builtin_paths(tmp_path / "data")
    local = FakeLocal(integrity=local_embedding.Integrity(paths))
    app = make_app(tmp_path, monkeypatch, Pool(), local)
    client = client_of(app)
    try:
        store = app.state.store
        english = client.post("/api/researches", json={"question": "What SYNTHETIC routing saves energy?", "model_connection": "fake",
                                                       "requested_model": "m", "effort": "quick"}).json()["research"]["id"]
        turkish = client.post("/api/researches", json={"question": TURKISH, "model_connection": "fake", "requested_model": "m",
                                                       "effort": "quick", "key_terms": KEY_TERMS}).json()["research"]["id"]
        arms = {}
        store.set_setting("semantic_search", {"provider": "off", "model": None})
        arms["off"] = client.get(f"/api/researches/{english}").json()["semantic"]
        store.set_setting("semantic_search", BUILTIN)
        arms["not_installed"] = client.get(f"/api/researches/{english}").json()["semantic"]
        arms["missing"] = client.get(f"/api/researches/{turkish}").json()["semantic"]
        install_fake(paths)
        asyncio.run(app.state.builtin.start())
        arms["on"] = client.get(f"/api/researches/{english}").json()["semantic"]
        monkeypatch.setenv("GEMINI_API_KEY", "SYNTHETIC-key")
        store.set_setting("semantic_search", GEMINI)
        arms["gemini"] = client.get(f"/api/researches/{turkish}").json()["semantic"]
    finally:
        client.__exit__(None, None, None)
    assert {k: v["arm"] for k, v in arms.items()} == {"off": "off", "not_installed": "not_installed",
                                                      "missing": "english_question_missing", "on": "on", "gemini": "on"}
    assert arms["on"] == {"provider": "builtin", "stored_model": BUILTIN_STORED, "arm": "on", "english_question": None,
                          "needs_english_question": False}
    assert arms["gemini"] == {"provider": "gemini", "stored_model": embeddings.MODEL, "arm": "on", "english_question": None,
                              "needs_english_question": False}  # the line under the buttons depends on the provider alone


def test_the_protocol_body_differs_between_gemini_and_the_built_in_model_only_in_the_model_string(tmp_path, monkeypatch):
    bodies = {}
    for name, setting, key in (("gemini", GEMINI, True), ("builtin", BUILTIN, False)):
        s = Session(tmp_path / name, monkeypatch, handler=Gemini(), setting=setting, gemini_key=key)
        try:
            rid, run_id, view, run = s.discover()
            bodies[name] = json.loads(s.store.conn.execute("SELECT body_json FROM protocol_records WHERE research_id = ?", (rid,)).fetchone()[0])
        finally:
            s.close()
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def differences(a, b, path=""):
        if isinstance(a, dict) and isinstance(b, dict):
            return [d for k in sorted(set(a) | set(b)) for d in differences(a.get(k), b.get(k), f"{path}.{k}")]
        if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            return [d for i, (x, y) in enumerate(zip(a, b)) for d in differences(x, y, f"{path}[{i}]")]
        return [] if a == b else [(path, a, b)]
    embedding = next(i for i, s in enumerate(bodies["gemini"]["signals"]) if s["signal"] == "embedding")
    assert differences(bodies["gemini"], bodies["builtin"]) == [(f".signals[{embedding}].model", embeddings.MODEL, BUILTIN_STORED)]


# ---- Sol review, round 1 (findings 1, 2, 5, 7, 8) ---------------------------------------------------

def test_a_late_waking_event_loop_is_charged_the_time_that_passed_and_a_pause_keeps_it(session, small_batches, clock):
    """The 429 budget counts real elapsed time, not the slices asked for (Sol r1, finding 5)."""
    limited = (429, {"Retry-After": "6"}, {"error": {"message": "SYNTHETIC"}})
    clock.lag = 3.0  # every one-second sleep takes three
    s = session("late", handler=Gemini([None, limited]), setting=GEMINI, gemini_key=True)
    rid, run_id, view, run = s.discover()
    step = s.step(run_id)
    assert step["status"] == "succeeded" and clock.slices == 2  # six seconds passed in two slices, not six
    assert (step["output"]["rate_limited_waits"], step["output"]["waited_seconds"]) == (1, 6)
    # Paused after the first late slice: the stored budget holds the three seconds that passed, and the resume keeps them.
    clock.slices = 0
    t = session("paused", handler=Gemini([None, limited]), setting=GEMINI, gemini_key=True)
    clock.on_slice = lambda n: n == 1 and t.pause()
    rid, run_id, view, run = t.discover()
    assert run["status"] == "paused" and t.step(run_id)["output"]["waited_seconds"] == 3
    clock.on_slice = None
    view, run = t.resume(rid, run_id)
    step = t.step(run_id)
    assert (step["status"], step["output"]["waited_seconds"]) == ("succeeded", 3)


def test_a_wait_a_late_loop_stretches_past_the_budget_stops_and_the_batch_is_not_sent_again(session, small_batches, clock):
    """The budget is checked after every wake; once past 180 s the refused batch is not resent (Sol r2, finding 5)."""
    limited = (429, {"Retry-After": "150"}, {"error": {"message": "SYNTHETIC"}})
    clock.lag = 100.0
    s = session(handler=Gemini([None, None, limited]), setting=GEMINI, gemini_key=True)
    rid, run_id, view, run = s.discover()
    step = s.step(run_id)
    # 150 s were allowed; two late slices took 200 s, which is what the step records, and the wait stops there.
    assert clock.slices == 2 and step["output"]["waited_seconds"] == 200 and step["status"] == "partial"
    assert "passed the step's 180 s limit" in step["error_json"] and run["status"] == "completed"
    documents = [n for kind, n in s.handler.embedding_requests if kind == "RETRIEVAL_DOCUMENT"]
    assert documents == [10, 10]  # batch 1, then batch 2 once: refused, and never sent again


@pytest.mark.parametrize("body", [
    {"embeddings": [{"values": [1.0, 0.0]}]},                              # one vector for two texts
    {"something": "else"},                                                 # no embeddings at all
    {"embeddings": [{"values": [1.0, 0.0]}, {"values": ["x", 0.0]}]},      # a value that is not a number
    {"embeddings": [{"values": [1.0, 0.0]}, {"values": [1.0, 0.0, 0.0]}]},  # two dimensions in one batch
    {"embeddings": [{"values": [1.0, 0.0]}, {"values": []}]},               # an empty vector
])
def test_a_malformed_gemini_reply_is_an_embedding_error(body):
    """A 200 whose vectors do not match the request is refused, never zipped short (Sol r1, finding 2)."""
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))) as client:
            return await embeddings.embed(client, "SYNTHETIC-key", ["a", "b"], "RETRIEVAL_DOCUMENT")
    with pytest.raises(embeddings.EmbeddingError, match="bad_reply"):
        asyncio.run(go())


@pytest.mark.parametrize("data", [
    [{"index": 0, "embedding": [1.0, 0.0]}],                                          # one vector for two texts
    [{"index": 0, "embedding": [1.0, 0.0]}, {"index": 0, "embedding": [0.0, 1.0]}],   # an index twice
    [{"index": 0, "embedding": [1.0, 0.0]}, {"index": 5, "embedding": [0.0, 1.0]}],   # an index out of range
    [{"index": 0, "embedding": [1.0, 0.0]}, {"embedding": [0.0, 1.0]}],               # no index
])
def test_a_malformed_openai_compatible_reply_is_an_embedding_error(data):
    async def go():
        handler = lambda r: httpx.Response(200, json={"data": data})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await embeddings.embed_openai_compatible(client, "http://127.0.0.1:1", None, "m", ["a", "b"])
    with pytest.raises(embeddings.EmbeddingError, match="bad_reply"):
        asyncio.run(go())


def test_a_well_formed_openai_reply_is_put_back_in_input_order():
    async def go():
        data = [{"index": 1, "embedding": [0.0, 2.0]}, {"index": 0, "embedding": [3.0, 0.0]}]
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": data}))) as client:
            return await embeddings.embed_openai_compatible(client, "http://127.0.0.1:1", None, "m", ["a", "b"])
    first, second = asyncio.run(go())
    assert list(first) == [1.0, 0.0] and list(second) == [0.0, 1.0]


def test_a_short_200_reply_fails_the_batch_and_stores_nothing_of_it(session, small_batches):
    short = (200, {}, {"embeddings": [{"values": [1.0, 0.0]}]})  # one vector for a batch of ten
    s = session(handler=Gemini([None, short]), setting=GEMINI, gemini_key=True)
    rid, run_id, view, run = s.discover()
    step = s.step(run_id)
    assert (step["status"], step["output"]["embedded"]) == ("failed", 0) and "bad_reply" in step["error_json"]
    assert s.store.source_similarities(rid, 1, embeddings.MODEL) == {} and run["status"] == "completed"


def test_uploaded_text_in_a_failed_request_is_counted_as_attempted_not_confirmed(tmp_path, monkeypatch, clock):
    """A request that was issued with an uploaded PDF's text counts as attempted, whether or not vectors came back;
    only vectors confirm it (Sol r1 finding 1, r2 finding 4)."""
    monkeypatch.setenv("GEMINI_API_KEY", "SYNTHETIC-key")
    store, rid, svid, run = two_page_research(tmp_path)  # its one PDF is a person's upload, two passages

    def failing(request):
        rows = json.loads(request.content)["requests"]
        if rows[0]["taskType"] == "RETRIEVAL_DOCUMENT":
            return httpx.Response(500, json={"error": {"message": "SYNTHETIC server error"}})
        return httpx.Response(200, json={"embeddings": [{"values": [1.0, 0.0]} for _ in rows]})
    assert rank_passages(store, rid, svid, run, None, failing) is None
    step = store.existing_step(run["id"], "semantic_retrieval")
    assert step["status"] == "failed"
    out = step["output"]
    assert (out["uploaded_files_attempted"], out["uploaded_passages_attempted"]) == (1, 2)
    assert (out["uploaded_files_confirmed"], out["uploaded_passages_confirmed"]) == (0, 0)
    # Refused once with a 429, then answered: attempted and confirmed.
    store.update_run(run["id"], status="completed")
    later = store.create_run(rid, "answer", {}, None)
    answers = iter([httpx.Response(429, headers={"Retry-After": "1"}, json={"error": {"message": "SYNTHETIC"}})])

    def limited(request):
        rows = json.loads(request.content)["requests"]
        if rows[0]["taskType"] == "RETRIEVAL_DOCUMENT" and (answer := next(answers, None)) is not None:
            return answer
        return httpx.Response(200, json={"embeddings": [{"values": [1.0, 0.0]} for _ in rows]})
    rank_passages(store, rid, svid, later, None, limited)
    out = store.existing_step(later["id"], "semantic_retrieval")["output"]
    assert (out["uploaded_files_attempted"], out["uploaded_passages_attempted"]) == (1, 2)
    assert (out["uploaded_files_confirmed"], out["uploaded_passages_confirmed"], out["rate_limited_waits"]) == (1, 2, 1)


def test_a_connection_never_made_sends_no_uploaded_text(tmp_path, monkeypatch):
    """A document request that fails before the connection is made is not counted as attempted (Sol r2, finding 4)."""
    monkeypatch.setenv("GEMINI_API_KEY", "SYNTHETIC-key")
    store, rid, svid, run = two_page_research(tmp_path)

    def unreachable(request):
        rows = json.loads(request.content)["requests"]
        if rows[0]["taskType"] == "RETRIEVAL_DOCUMENT":
            raise httpx.ConnectError("SYNTHETIC connection refused", request=request)
        return httpx.Response(200, json={"embeddings": [{"values": [1.0, 0.0]} for _ in rows]})
    assert rank_passages(store, rid, svid, run, None, unreachable) is None
    out = store.existing_step(run["id"], "semantic_retrieval")["output"]
    assert (out["uploaded_files_attempted"], out["uploaded_passages_attempted"], out["uploaded_passages_confirmed"]) == (0, 0, 0)


def test_a_batch_of_another_dimension_than_the_query_is_a_bad_reply(session, small_batches, tmp_path, monkeypatch):
    """Vectors are compared with the step's query dimension, so none are truncated into a similarity (Sol r2, finding 1)."""
    three = (200, {}, {"embeddings": [{"values": [1.0, 0.0, 0.0]} for _ in range(10)]})  # the query had two dimensions
    s = session(handler=Gemini([None, None, three]), setting=GEMINI, gemini_key=True)
    rid, run_id, view, run = s.discover()
    step = s.step(run_id)
    assert (step["status"], step["output"]["embedded"], step["output"]["dimensions"]) == ("partial", 10, 2)
    assert "bad_reply: vectors of 3 dimensions where the query had 2" in step["error_json"]
    assert len(s.store.source_similarities(rid, 1, embeddings.MODEL)) == 10 and run["status"] == "completed"
    # The passage path: the query has two dimensions, the passages three.
    monkeypatch.setenv("GEMINI_API_KEY", "SYNTHETIC-key")
    store, prid, svid, prun = two_page_research(tmp_path / "passages")

    def mixed(request):
        rows = json.loads(request.content)["requests"]
        size = 2 if rows[0]["taskType"] == "RETRIEVAL_QUERY" else 3
        return httpx.Response(200, json={"embeddings": [{"values": [1.0] + [0.0] * (size - 1)} for _ in rows]})
    assert rank_passages(store, prid, svid, prun, None, mixed) is None
    step = store.existing_step(prun["id"], "semantic_retrieval")
    assert step["status"] == "failed" and "bad_reply" in step["error_json"]
    assert store.passage_embeddings([p["id"] for p in store.passages_for(svid)], embeddings.MODEL) == {}


def test_a_sentence_for_a_question_read_as_english_is_refused(session):
    """The built-in model reads an English question as written, so a sentence it would never read is not saved
    (Sol r1, finding 7): the view and the query follow one rule."""
    s = session()
    rid = s.client.post("/api/researches", json={"question": "How does packet size change the energy use of sensor networks?",
                                                 "model_connection": "fake", "requested_model": "m", "effort": "quick",
                                                 "key_terms": KEY_TERMS}).json()["research"]["id"]
    version = s.store.research(rid)["version"]
    for body in ({"text": ENGLISH_SENTENCE, "expected_version": version}, {"use_question": True, "expected_version": version}):
        refused = s.client.put(f"/api/researches/{rid}/english-question", json=body)
        assert refused.status_code == 422 and "already read as English" in refused.text
    assert s.store.english_question(rid, 1) is None and s.store.research(rid)["version"] == version
    semantic = research_view(s.store, rid)["semantic"]
    assert (semantic["needs_english_question"], semantic["english_question"]) == (False, None)
    assert semantic["arm"] != english_question.MISSING


def test_the_step_records_whether_the_built_in_model_was_installed_when_it_ran(session):
    """The transcript reads this from the step, not from today's Settings (Sol r1, finding 8)."""
    s = session()
    rid, first, view, run = s.discover()
    s.local.unavailable = True
    run_id, view, run = s.again(rid)
    s.store.set_setting("semantic_search", GEMINI)  # Settings move on; the earlier step keeps what it saw
    assert s.step(run_id)["output"]["model_installed"] is False
    assert research_view(s.store, rid)["semantic"]["provider"] == "gemini"
    assert s.step(run_id)["output"]["model_installed"] is False


# ---- Sol review of the implementation, round 3 --------------------------------------------------------

def gemini_of(dimensions):
    def handler(request):
        rows = json.loads(request.content)["requests"]
        return httpx.Response(200, json={"embeddings": [{"values": [1.0] + [0.0] * (dimensions - 1)} for _ in rows]})
    return handler


def test_stored_passage_vectors_of_another_dimension_are_left_out_of_the_similarity(tmp_path, monkeypatch):
    """A stored vector is compared with this step's query only when their dimensions match (Sol r3, finding 1);
    `from_store` counts only the stored vectors used, and a step that could not compare them all is partial, or
    failed with the keyword order when none could (Sol r4, finding 1)."""
    monkeypatch.setenv("GEMINI_API_KEY", "SYNTHETIC-key")
    store, rid, svid, run = two_page_research(tmp_path)
    assert rank_passages(store, rid, svid, run, None, gemini_of(3)) is not None  # both pages stored with three dimensions
    store.update_run(run["id"], status="completed")
    later = store.create_run(rid, "answer", {}, None)
    assert rank_passages(store, rid, svid, later, None, gemini_of(2)) is None  # nothing comparable: keyword order
    step = store.existing_step(later["id"], "semantic_retrieval")
    out = step["output"]
    assert (step["status"], out["dimensions"], out["stored_other_dimension"], out["from_store"], out["embedded"]) == (
        "failed", 2, 2, 0, 0)
    assert "stored_other_dimension" in step["error_json"]
    # One page's stored vector gone: it is embedded at two dimensions, the other stays out, and the step is partial.
    first = store.passages_for(svid)[0]["id"]
    store.conn.execute("DELETE FROM passage_embeddings WHERE passage_id = ?", (first,))
    store.update_run(later["id"], status="completed")
    third = store.create_run(rid, "answer", {}, None)
    ranked = rank_passages(store, rid, svid, third, None, gemini_of(2))
    step = store.existing_step(third["id"], "semantic_retrieval")
    out = step["output"]
    assert [p["id"] for p in ranked] == [first]
    assert (step["status"], out["stored_other_dimension"], out["from_store"], out["embedded"]) == ("partial", 1, 0, 1)


def test_a_late_wake_that_pauses_past_the_budget_sends_nothing_after_the_resume(session, small_batches, clock):
    """The persisted budget is checked before every send: a pause taken by the late wake that passed 180 s does not
    let the resumed step send the refused batch again (Sol r3, finding 2)."""
    limited = (429, {"Retry-After": "150"}, {"error": {"message": "SYNTHETIC"}})
    clock.lag = 200.0
    s = session(handler=Gemini([None, None, limited]), setting=GEMINI, gemini_key=True)
    clock.on_slice = lambda n: n == 1 and s.pause()
    rid, run_id, view, run = s.discover()
    assert run["status"] == "paused" and s.step(run_id)["output"]["waited_seconds"] == 200
    clock.on_slice = None
    sent = list(s.handler.embedding_requests)
    view, run = s.resume(rid, run_id)
    step = s.step(run_id)
    assert s.handler.embedding_requests == sent  # neither the query nor the refused batch went out again
    assert step["status"] == "partial" and "passed the step's 180 s limit" in step["error_json"]
    assert step["output"]["waited_seconds"] == 200 and clock.slices == 1


def test_a_request_cancelled_in_flight_leaves_its_uploaded_text_attempted_with_the_outcome_unknown(tmp_path, monkeypatch):
    """The uploaded ids are written as pending before the request is awaited, so a task cancelled in the middle of it
    leaves them as unknown, apart from attempted (Sol r3, finding 3; r4, finding 2). A resume keeps them unknown when
    it cannot connect, and counts them as attempted and confirmed once they are sent and answered."""
    monkeypatch.setenv("GEMINI_API_KEY", "SYNTHETIC-key")
    store, rid, svid, run = two_page_research(tmp_path)

    async def go():
        entered = asyncio.Event()

        async def hanging(request):
            rows = json.loads(request.content)["requests"]
            if rows[0]["taskType"] == "RETRIEVAL_DOCUMENT":
                entered.set()
                await asyncio.Event().wait()  # the reply never comes
            return httpx.Response(200, json={"embeddings": [{"values": [1.0, 0.0]} for _ in rows]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(hanging)) as client:
            flow = object.__new__(ResearchFlow)
            flow.store, flow.deps = store, SimpleNamespace(http=client, local_embedder=None)
            task = asyncio.create_task(flow._semantic_ranking(run, store.scope(rid), [svid]))
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    asyncio.run(go())
    fields = ("uploaded_files_attempted", "uploaded_passages_attempted", "uploaded_passages_confirmed",
              "uploaded_files_unknown", "uploaded_passages_unknown")
    out = store.existing_step(run["id"], "semantic_retrieval")["output"]
    assert tuple(out[f] for f in fields) == (0, 0, 0, 1, 2) and len(out["uploaded_pending_passage_ids"]) == 2

    def unreachable(request):
        rows = json.loads(request.content)["requests"]
        if rows[0]["taskType"] == "RETRIEVAL_DOCUMENT":
            raise httpx.ConnectError("SYNTHETIC connection refused", request=request)
        return gemini_of(2)(request)
    rank_passages(store, rid, svid, run, None, unreachable)  # resumed, and the document request never connects
    out = store.existing_step(run["id"], "semantic_retrieval")["output"]
    assert tuple(out[f] for f in fields) == (0, 0, 0, 1, 2) and out["uploaded_pending_passage_ids"] == []
    rank_passages(store, rid, svid, run, None, gemini_of(2))  # resumed again, and answered
    out = store.existing_step(run["id"], "semantic_retrieval")["output"]
    assert tuple(out[f] for f in fields) == (1, 2, 2, 0, 0)
