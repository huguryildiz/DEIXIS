"""Semantic passage retrieval (D27, D29): rank fusion, embedding requests, stored vectors and the chosen provider.

The embedding endpoints are mocked with keyword-derived vectors, so these tests show the plumbing, not retrieval quality.
"""

import asyncio
import hashlib
import json
from types import SimpleNamespace

import httpx

from deixis.documents import embeddings
from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow.flow import ResearchFlow, answer_source_order, fuse_rankings
from deixis.workflow.store import Store
from deixis.workflow.views import research_view


def test_rank_fusion_puts_passages_high_in_either_ranking_first():
    a, b, c, d = ({"id": name} for name in "abcd")
    assert [p["id"] for p in fuse_rankings([a, b, c], [c, a, d])] == ["a", "c", "b", "d"]


def test_semantic_rank_reorders_sources_that_lexical_terms_cannot_separate():
    facts = {s: (False, 1) for s in "ABC"}
    texts = {"A": "SYNTHETIC bakery", "B": "SYNTHETIC weather", "C": "SYNTHETIC routing energy"}
    assert answer_source_order(list("ABC"), facts, texts, ["enerji"]) == ["A", "B", "C"]  # a Turkish term matches nothing
    assert answer_source_order(list("ABC"), facts, texts, ["enerji"], {"C": 0, "A": 1, "B": 2}) == ["A", "C", "B"]


def test_embeddings_are_batched_unit_length_and_in_input_order(monkeypatch):
    monkeypatch.setattr(embeddings, "BATCH", 2)
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        assert request.headers["x-goog-api-key"] == "test-key"
        return httpx.Response(200, json={"embeddings": [{"values": [3.0 * len(r["content"]["parts"][0]["text"]), 4.0]}
                                                        for r in body["requests"]]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await embeddings.embed(client, "test-key", ["a", "bb", "ccc"], "RETRIEVAL_DOCUMENT")

    vectors = asyncio.run(run())
    assert [len(body["requests"]) for body in sent] == [2, 1]
    assert {r["taskType"] for body in sent for r in body["requests"]} == {"RETRIEVAL_DOCUMENT"}
    assert [round(embeddings.similarity(v, v), 5) for v in vectors] == [1.0, 1.0, 1.0]


def on_topic(text):
    return any(word in text for word in ("energy", "enerji"))


def two_page_research(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("Su altı ağlarında yönlendirmenin enerji verimliliği nedir?", "attached", "quick", [], "fake", "m", "tr")
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


def rank(store, rid, svid, run, handler):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            flow = object.__new__(ResearchFlow)
            flow.store, flow.deps = store, SimpleNamespace(http=client)
            return await flow._semantic_ranking(run, store.scope(rid), [svid])
    return asyncio.run(go())


def steps(store, run):
    return [tuple(row) for row in store.conn.execute("SELECT kind, status, error_code FROM run_steps WHERE run_id = ?", (run["id"],))]


def test_semantic_ranking_matches_across_languages_and_embeds_each_passage_once(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    store, rid, svid, run = two_page_research(tmp_path)
    batches = []

    def handler(request):
        body = json.loads(request.content)
        batches.append([r["taskType"] for r in body["requests"]])
        return httpx.Response(200, json={"embeddings": [{"values": [1.0, 0.0] if on_topic(r["content"]["parts"][0]["text"]) else [0.0, 1.0]}
                                                        for r in body["requests"]]})

    first = rank(store, rid, svid, run, handler)
    assert "Depth-based routing" in first[0]["text"]
    # Slice 21 (D103, decision 4): the query is embedded first, then the passages batch by batch; the step output
    # also carries the frozen identity, the query's origin and the wait and upload counts.
    assert batches == [["RETRIEVAL_QUERY"], ["RETRIEVAL_DOCUMENT", "RETRIEVAL_DOCUMENT"]]
    semantic_step = research_view(store, rid)["runs"][0]["steps"][0]
    question = store.scope(rid)["question"]
    upload = store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ?", (svid,)).fetchone()[0]
    assert semantic_step["output"] == {
        "model": "gemini-embedding-2", "passages": 2, "embedded": 2,
        "provider": "gemini", "stored_model": "gemini-embedding-2", "from_store": 0, "missing": 0,
        "query_origin": "question", "query_sha256": "sha256:" + hashlib.sha256(question.encode()).hexdigest(),
        "rate_limited_waits": 0, "waited_seconds": 0.0,
        # the person's uploaded PDF: a request carried its text, and vectors came back for both passages
        "uploaded_file_ids": [upload], "uploaded_confirmed_file_ids": [upload],
        "uploaded_passage_ids": sorted(p["id"] for p in store.passages_for(svid)),
        "uploaded_files_attempted": 1, "uploaded_passages_attempted": 2,
        "uploaded_files_confirmed": 1, "uploaded_passages_confirmed": 2, "dimensions": 2,
        "uploaded_pending_file_ids": [], "uploaded_pending_passage_ids": [], "stored_other_dimension": 0,
        "uploaded_unknown_file_ids": [], "uploaded_unknown_passage_ids": [], "uploaded_files_unknown": 0, "uploaded_passages_unknown": 0,
    }
    batches.clear()
    rank(store, rid, svid, run, handler)
    assert batches == [["RETRIEVAL_QUERY"]]  # stored passage vectors are reused


def test_a_chosen_local_embedding_model_ranks_passages_without_a_key(tmp_path):
    store, rid, svid, run = two_page_research(tmp_path)
    store.set_setting("semantic_search", {"provider": "ollama", "model": "nomic-embed-text"})
    seen = set()

    def handler(request):
        body = json.loads(request.content)
        seen.add((str(request.url), request.headers.get("authorization"), body["model"]))
        # Returned out of order: vectors are matched to inputs by index.
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [1.0, 0.0] if on_topic(text) else [0.0, 1.0]}
                                                  for i, text in reversed(list(enumerate(body["input"])))]})

    ranked = rank(store, rid, svid, run, handler)
    assert "Depth-based routing" in ranked[0]["text"]
    assert seen == {("http://127.0.0.1:11434/v1/embeddings", None, "nomic-embed-text")}
    assert steps(store, run) == [("embedding:ollama:nomic-embed-text", "succeeded", None)]


def test_semantic_search_turned_off_or_unable_to_run_leaves_lexical_retrieval(tmp_path):
    store, rid, svid, run = two_page_research(tmp_path)

    def handler(request):
        raise AssertionError("no embedding request is sent")

    store.set_setting("semantic_search", {"provider": "off", "model": None})
    assert rank(store, rid, svid, run, handler) is None and steps(store, run) == []
    store.set_setting("semantic_search", {"provider": "openai", "model": "text-embedding-3-small"})  # OPENAI_API_KEY is not set
    assert rank(store, rid, svid, run, handler) is None
    assert steps(store, run) == [("embedding:openai:text-embedding-3-small", "failed", "embedding_failed")]


def test_semantic_ranking_can_choose_a_source_passage_that_lexical_search_missed():
    bakery = {"id": "bakery", "source_version_id": "source", "kind": "pdf_page", "physical_page": 1, "text": "SYNTHETIC bakery."}
    routing = {"id": "routing", "source_version_id": "source", "kind": "pdf_page", "physical_page": 2, "text": "SYNTHETIC routing."}

    class RetrievalStore:
        def latest_step_output(self, *_): return None
        def search_passages(self, *_): return []
        def passages_for(self, *_): return [bakery, routing]
        def source(self, *_): return {"title": "SYNTHETIC source"}
        def answer_order_facts(self, *_): return {"source": (True, 0)}

    flow = object.__new__(ResearchFlow)
    flow.store = RetrievalStore()
    scope = {"question": "Yönlendirme enerjisi nedir?", "revision": 1}
    assert [p["id"] for p in flow._retrieve("research", scope, ["source"], 1)] == ["bakery"]
    assert [p["id"] for p in flow._retrieve("research", scope, ["source"], 1, [routing, bakery])] == ["routing"]


def screened_research(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("Su altı ağlarında yönlendirmenin enerji verimliliği nedir?", "attached", "quick", [], "fake", "m", "tr")
    for rank, (title, abstract) in enumerate([("SYNTHETIC bakery", "SYNTHETIC bread every morning."), ("SYNTHETIC routing energy", None)]):
        record = ProviderRecord(provider_record_id=f"seed{rank}", title=title, authors=[], year=None, venue=None,
                                publication_type=None, doi=None, landing_url=None, oa_pdf_url=None, oa_pdf_version=None,
                                version_label=None, abstract=abstract, abstract_origin="provider" if abstract else None, identifiers={}, raw={})
        svid, _ = store.upsert_provider_source("known_list", record, None)
        store.add_to_corpus(rid, svid, "search", rank=rank, scope_revision=store.scope(rid)["revision"])
    return store, rid, store.create_run(rid, "answer", {}, None)


def score_sources(store, rid, run, handler):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            flow = object.__new__(ResearchFlow)
            flow.store, flow.deps = store, SimpleNamespace(http=client)
            await flow._source_similarity(run, store.scope(rid), store.candidates(rid, run["scope_revision"]))
    asyncio.run(go())


def test_screened_sources_are_scored_once_and_shown_only_while_semantic_search_is_on(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    store, rid, run = screened_research(tmp_path)
    sent = []

    def handler(request):
        texts = [r["content"]["parts"][0]["text"] for r in json.loads(request.content)["requests"]]
        sent.extend(texts)
        return httpx.Response(200, json={"embeddings": [{"values": [1.0, 0.0] if on_topic(t) else [0.0, 1.0]} for t in texts]})

    score_sources(store, rid, run, handler)
    assert "SYNTHETIC bakery\n\nSYNTHETIC bread every morning." in sent  # title and abstract are embedded together
    assert {s["title"]: s["similarity"] for s in research_view(store, rid)["sources"]} == {"SYNTHETIC bakery": 0.0, "SYNTHETIC routing energy": 1.0}
    (step,) = [s for s in store.run_steps(run["id"]) if s["operation_key"] == "source_similarity"]
    assert step["output"]["sources"] == 2  # the transcript reads this count
    sent.clear()
    score_sources(store, rid, run, handler)
    assert sent == []  # a score is kept per source, question revision and model
    store.set_setting("semantic_search", {"provider": "off", "model": None})
    assert {s["similarity"] for s in research_view(store, rid)["sources"]} == {None}
