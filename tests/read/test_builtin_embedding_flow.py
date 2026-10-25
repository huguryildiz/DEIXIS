"""The built-in model and batch-by-batch embedding inside runs (slice 21, D103, tasks 4 to 7).

Records are SYNTHETIC OpenAlex works served through httpx.MockTransport; the built-in model is an injected fake local
embedder (`create_app(local_embedder=...)`) and Gemini is a mocked endpoint; the clock of the 429 wait is replaced.
Passing shows how the steps store, stop, resume, wait and fall back, not that the similarity finds relevant work.
"""

import asyncio
import json
import time
from array import array
from types import SimpleNamespace
import httpx
import pytest
from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents import builtin_catalog, embeddings, local_embedding
from deixis.documents.local_embedding import LocalEmbeddingError
from deixis.providers.common import ProviderRecord
from deixis.providers.registry import CONNECTORS
from deixis.storage import db
from deixis.workflow import english_question
from deixis.workflow.flow import ResearchFlow
from deixis.workflow.store import Store
from deixis.workflow.views import research_view
from builtin_helpers import ready
from fakes import FakeAdapter, valid_response
from test_ranking_flow import STRONG, Pool, client_of, discover, no_fetch, wait
from test_semantic_retrieval import two_page_research


EMB = "qwen3-embedding-0.6b"


BUILTIN = {"provider": "builtin", "model": EMB}


BUILTIN_STORED = "builtin:" + builtin_catalog.identity(builtin_catalog.get(EMB))


# A discovery run's queue consumer (D252) runs the built-in model with its frozen thread count, which is part of the
# stored identity: scores of capped and default threads are different cache rows.


TURKISH = "Kablosuz algılayıcı ağlarında paket boyutunun enerji tüketimine etkisi nedir?"


KEY_TERMS = "packet size; energy consumption; wireless sensor networks"


ENGLISH_SENTENCE = "The effect of packet size on energy consumption in wireless sensor networks."


def basis(index: int) -> array:
    values = array("f", [0.0] * 1024)
    values[index] = 1.0
    return values


class FakeLocal:
    """The built-in model as the flow sees it: the query and records naming `target` at one place, the rest at another.

    `hook(calls, texts, kind)` runs before each answer (a pause, a setting change); `fail_on` makes that call (1-based)
    fail; `unavailable` fails every call as a model that is not installed does."""

    def __init__(self, target=STRONG, fail_on=None, unavailable=False, hook=None, paths=None):
        self.target, self.fail_on, self.unavailable, self.hook = target, fail_on, unavailable, hook
        self.calls: list[tuple[str, int]] = []
        self.texts: list[str] = []
        self.paths = paths  # with paths: installed and checked as the real files under them say
        self.busy, self.client = {}, None
        self.models: list[str] = []

    def available(self, model_id):
        return self.paths is not None and local_embedding.LocalModels(self.paths).available(model_id)

    async def embed(self, model_id, texts, kind, report=None):
        self.models.append(model_id)
        self.calls.append((kind, len(texts)))
        if self.hook:
            self.hook(len(self.calls), texts, kind)
        if self.unavailable:
            raise LocalEmbeddingError("builtin_unavailable", "SYNTHETIC the built-in model is not installed")
        if self.fail_on == len(self.calls):
            raise LocalEmbeddingError("builtin_stopped", "SYNTHETIC the runner stopped")
        self.texts += texts if kind == "document" else []
        return [basis(0) if kind == "query" or (self.target and self.target in text) else basis(1) for text in texts]

    async def close(self, model_id=None):
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
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_query="code",
                               fulltext_fetch="off"),
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
        # Read through the API: the worker's runs (the fast path queues more of them) share the store's connection.
        deadline = time.time() + 30
        while time.time() < deadline:
            run = next(r for r in self.client.get(f"/api/researches/{rid}").json()["runs"] if r["id"] == run_id)
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


def test_with_the_built_in_model_chosen_no_request_goes_to_gemini(session, monkeypatch):
    s = session(handler=Gemini(), gemini_key=True)  # a Gemini key is set, the built-in model is chosen
    rid, run_id, view, run = s.discover()
    assert s.handler.embedding_requests == [] and s.local.documents() == 24


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


@pytest.mark.parametrize("body", [
    {"embeddings": [{"values": [1.0, 0.0]}]},                              # one vector for two texts
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
])
def test_a_malformed_openai_compatible_reply_is_an_embedding_error(data):
    async def go():
        handler = lambda r: httpx.Response(200, json={"data": data})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await embeddings.embed_openai_compatible(client, "http://127.0.0.1:1", None, "m", ["a", "b"])
    with pytest.raises(embeddings.EmbeddingError, match="bad_reply"):
        asyncio.run(go())


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
