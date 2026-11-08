"""An `sw` discovery run whose search words came from the question by code, driven through the API (SW2).

The model adapter here fails on every call, so the run's searches prove that nothing asks a model before the first
search. Records and questions are SYNTHETIC and OpenAlex is mocked: passing shows workflow behavior, not recall.
A `legacy` research is exercised too, because nothing about it may change.
"""

import asyncio
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.runtime.config import Settings
from deixis.documents.fetch import FetchResult
from deixis.models.adapter import ModelStepResult
from deixis.providers.registry import CONNECTORS
from deixis.storage import db
from deixis.workflow.search import english_question
from deixis.workflow.search import search as fast_search
from deixis.workflow.search.vocabulary import VERY_LARGE_COUNT
from deixis.workflow.run.store import Store
from fakes import FakeAdapter
from windows_env import WAIT_FACTOR

QUESTION = "What is the effect of packet size on energy consumption in wireless sensor networks?"
TURKISH = "Kablosuz alıcı ağlarında paket boyu enerji tüketimini nasıl etkiler?"
KEY_TERMS = "wireless sensor networks; packet size; energy efficiency; claim: integer programming; not: survey"
WORK = {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/a",
        "display_name": "SYNTHETIC packet size selection for wireless sensor networks", "publication_year": 2024,
        "type": "article", "authorships": [], "abstract_inverted_index": {"We": [0], "choose": [1], "sizes.": [2]}}


def DeadAdapter():
    """A connection whose every model call fails. A search that still runs, ran without a model (SW2.3)."""
    return FakeAdapter(fail=lambda si: ModelStepResult("failed", error="SYNTHETIC model connection is down"))


class CountingOpenAlex:
    """Mocked OpenAlex that separates count probes from searches and can be told to stop answering counts."""

    def __init__(self, count=40, search_hits=True, events=None):
        self.counts, self.searches, self.semantic = [], [], []
        self.count_value, self.search_hits = count, search_hits
        # Every request kind in the order it arrived, shared with the model adapter where a test asks for the order.
        self.events = events if events is not None else []

    def __call__(self, request):
        if request.url.host != "api.openalex.org":
            return httpx.Response(404)
        params = request.url.params
        query = params.get("search.title_abstract_keywords")
        if params.get("per_page") == "1" and params.get("select") == "id":
            self.counts.append(query)
            self.events.append("count")
            return httpx.Response(200, json={"meta": {"count": self.count_value}, "results": []})
        if params.get("search.semantic"):
            self.semantic.append(params["search.semantic"])
            self.events.append("semantic")
        else:
            self.searches.append(query)
            self.events.append("keyword")
        return httpx.Response(200, json={"meta": {"count": 1}, "results": [WORK] if self.search_hits else []})


async def no_fetch(url):
    return FetchResult("http_error", final_url=url, http_status=404)


def app_for(tmp_path, monkeypatch, handler, adapter, workflow="sw"):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", workflow)
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_query="code",
                               fulltext_fetch="off"),
                      adapters={"fake": adapter},
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), fetcher=no_fetch,
                      extra_hosts=("testserver",), trusted_clients=("testclient",))


def wait(client, rid, run_id):
    deadline = time.time() + 15 * WAIT_FACTOR
    while time.time() < deadline:
        view = client.get(f"/api/researches/{rid}").json()
        run = next(r for r in view["runs"] if r["id"] == run_id)
        if run["status"] in ("completed", "failed", "paused"):
            return view, run
        time.sleep(0.05)
    raise AssertionError("the run did not settle")


def start(client, question, **body):
    payload = {"question": question, "model_connection": "fake", "requested_model": "fake-model",
               "effort": "quick", **body}
    response = client.post("/api/researches", json=payload)
    assert response.status_code == 201, response.text
    rid = response.json()["research"]["id"]
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    return rid, run_id


def client_of(app):
    client = TestClient(app)
    client.__enter__()
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    return client


def store_at(tmp_path):
    conn = db.connect(tmp_path / "data" / "library.sqlite")
    db.migrate(conn)
    return Store(conn)


def test_the_frozen_protocol_holds_the_concept_blocks_and_is_the_same_on_a_second_build(tmp_path, monkeypatch):
    with TestClient(app_for(tmp_path, monkeypatch, CountingOpenAlex(), DeadAdapter())) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
    from deixis.domain.canonical import sha256_hex
    from deixis.workflow.search import protocol

    store = store_at(tmp_path)
    rows = store.conn.execute("SELECT * FROM protocol_records WHERE research_id = ?", (rid,)).fetchall()
    assert len(rows) == 1
    body = json.loads(rows[0]["body_json"])
    assert body["search_workflow"] == "sw"
    assert body["concept_blocks"]["setting"] and body["concept_blocks"]["task"]
    assert body["claim_words"] == [] and body["exclusion_words"] == []
    assert body["thresholds"]["vocabulary"]["manageable_total"]
    # SW19: the labelling's hand-picked thresholds are written with the others.
    assert {k: body["thresholds"]["vocabulary"][k] for k in ("label_runs", "label_majority", "max_labelled_phrases")} \
        == {"label_runs": 3, "label_majority": 2, "max_labelled_phrases": 40}
    assert body["vocabulary"] and all(term["origin"] == "question" for term in body["vocabulary"])
    assert body["code_version"].endswith("deixis.query_compiler.v4.blocks")

    # The queries searched are the ones the source routing compiled, and its record is an input of the body.
    stored = store.latest_step_output(rid, "source_routing", 1)
    run_id = store.conn.execute("SELECT id FROM runs WHERE research_id = ?", (rid,)).fetchone()[0]
    again = protocol.build_protocol(store.scope(rid, 1), store.run(run_id)["budget"], None, stored["queries"],
        body["skill_package_hash"], Settings(data_dir=None, search_query="code"), vocabulary=stored["vocabulary"],
        approval=store.approval_step(run_id)["output"]["approval"], routing=stored["routing"],
        # The fast path's own inputs, frozen beside the others: the semantic search model and the search plan.
        embedding_model=next(s["model"] for s in body["signals"] if s["signal"] == "embedding"),
        fast_path_search=body["fast_path_search"])
    assert sha256_hex(again) == rows[0]["body_sha256"]


# A vocabulary that cannot be searched ends the run (clean start, decision B): no approval card is opened, no query
# the vocabulary would have written is searched, resuming is refused, and the way on is a new scope revision whose
# question can be searched. The question's own semantic request went out before the vocabulary step (P2), so the run
# ends with that one search behind it.
UNSEARCHABLE = {"vocabulary_empty": (0, QUESTION, "How does packet size change energy use in wireless sensor networks?"),
                "vocabulary_too_broad": (VERY_LARGE_COUNT + 1, "Which networks are reported?", QUESTION)}


@pytest.mark.parametrize("reason", sorted(UNSEARCHABLE))
def test_a_vocabulary_that_cannot_be_searched_ends_the_run_before_any_search(tmp_path, monkeypatch, reason):
    count, question, _ = UNSEARCHABLE[reason]
    openalex = CountingOpenAlex(count=count)
    with TestClient(app_for(tmp_path, monkeypatch, openalex, DeadAdapter())) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, question)
        view, run = wait(client, rid, run_id)
    assert (run["status"], run["pause_reason"]) == ("failed", reason), run
    assert openalex.counts and not openalex.searches
    # Only the question's own request, sent before anything planned, and it carries the question as written.
    assert openalex.semantic == [question]
    assert [r["query_text"] for r in view["search_runs"]] == [question]
    if reason == "vocabulary_too_broad":
        assert run["error"]["gate_count"] > VERY_LARGE_COUNT
    # No approval card waits for the user, and no protocol was frozen.
    assert run["approval"] is None
    keys = [s["operation_key"] for s in run["steps"]]
    assert "protocol_approval" not in keys and "protocol" not in keys
    step = next(s for s in run["steps"] if s["operation_key"] == "vocabulary")
    assert step["status"] == "succeeded"  # the counts it read are kept with the step
    # A failed discovery queues no answer.
    assert [r["kind"] for r in view["runs"]] == ["discovery"]


# ---- the question's own request comes before anything plans (P2) -------------------------------------------------

# The design's first step needs no translation, rewriting or model call, so the question's own semantic request is
# opened and started before any planning step asks a model, whatever the question's language. Its start is what is
# checked here, not the moment it reaches OpenAlex: a semantic request also waits at the provider's own start pacer
# (`openalex.SEMANTIC_PACER`), which has nothing to do with planning.
@pytest.mark.parametrize("language", ["english", "turkish"])
def test_the_questions_own_request_starts_before_the_first_planning_model_call(tmp_path, monkeypatch, language):
    question = QUESTION if language == "english" else TURKISH
    openalex = CountingOpenAlex()
    with TestClient(app_for(tmp_path, monkeypatch, openalex, FakeAdapter())) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, question)
        view, run = wait(client, rid, run_id)
    assert run["status"] == "completed", run
    assert openalex.semantic == [question]  # the question as written, once, in either language
    store = store_at(tmp_path)
    steps = [dict(row) for row in store.conn.execute(
        "SELECT operation_key, started_at, protocol_hash FROM run_steps WHERE run_id = ? ORDER BY rowid", (run_id,))]
    keys = [step["operation_key"] for step in steps]
    # Opened first of all the run's work; `source_similarity` opens with the run and sends nothing to a provider.
    assert keys[0] in ("search:fast:semantic", "source_similarity") and "search:fast:semantic" in keys[:2]
    first = next(step for step in steps if step["operation_key"] == "search:fast:semantic")
    model = next(step for step in steps if step["operation_key"].startswith("vocabulary_labels"))
    assert first["started_at"] <= model["started_at"]
    if language == "turkish":
        # The translation the vocabulary step asks for started after the request, so the request waited for none of it.
        translation = next(step for step in steps if step["operation_key"] == "question_translation")
        assert first["started_at"] <= translation["started_at"]
        assert keys.index("search:fast:semantic") < keys.index("question_translation")
    else:
        assert "question_translation" not in keys
    # The step opened before the protocol froze, so it carries no protocol hash, as the seed match's requests do (Ç1).
    hashes = {step["operation_key"]: step["protocol_hash"] for step in steps}
    assert hashes["search:fast:semantic"] is None and hashes["protocol"] is None
    assert hashes["search:0"] is not None  # a planned query's step opened after the freeze
    assert len(store.conn.execute("SELECT 1 FROM protocol_records WHERE research_id = ?", (rid,)).fetchall()) == 1


def test_a_question_in_another_language_with_key_terms_searches_and_ranks_without_a_sentence(tmp_path, monkeypatch):
    # The person's key terms give the search words, so no translation is asked and no English sentence is stored. The
    # run goes on: the question's own request is sent as written, the Boolean queries carry the key terms, and the
    # signals that need English read none and say so (`english_question_missing`) instead of stopping the run. The
    # rerank's side of that reason is `test_reranking`.
    openalex = CountingOpenAlex()
    adapter = FakeAdapter()
    with TestClient(app_for(tmp_path, monkeypatch, openalex, adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, TURKISH, key_terms=KEY_TERMS)
        view, run = wait(client, rid, run_id)
    assert run["status"] == "completed", run
    assert openalex.semantic == [TURKISH] and openalex.searches
    assert [si["task_type"] for si in adapter.calls].count("question_translation") == 0
    store = store_at(tmp_path)
    assert store.english_question(rid, 1) is None
    assert english_question.embedding_query(store, store.scope(rid, 1)) is None
    # The Boolean queries were written from the key terms, and none of them carries a word of the question.
    boolean = [query for query in openalex.searches if query]
    assert boolean == ["wireless AND packet"]
    assert not any("ağlarında" in query for query in boolean)


def test_a_failed_translation_still_stops_the_run(tmp_path, monkeypatch):
    # Moving the question's request ahead of the planning steps does not change this pause: a question that is not
    # English and has no key terms leaves code no words of its own, so a failed translation still stops the run with
    # `key_terms_needed` and no Boolean query is searched.
    openalex = CountingOpenAlex()
    with TestClient(app_for(tmp_path, monkeypatch, openalex, DeadAdapter())) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, TURKISH)
        view, run = wait(client, rid, run_id)
    assert (run["status"], run["pause_reason"]) == ("paused", "key_terms_needed"), run
    assert run["error"]["translation"]["reason"] == "model_call_failed"
    assert not openalex.searches and openalex.semantic in ([], [TURKISH])
    # The request's step is the run's first and it is not lost: a resume sends it, or reads back the page it brought.
    keys = [s["operation_key"] for s in run["steps"] if s["kind"].startswith("provider_search")]
    assert keys == ["search:fast:semantic"]


def test_a_question_request_that_cannot_be_built_raises_instead_of_leaving_the_planning_arm_waiting(monkeypatch):
    # The planning steps wait for the question's request to be on its way before they ask a model. If building that
    # request raises, the waiting arm must get the error, so the event is set on the way out whatever happens.
    monkeypatch.setattr(fast_search, "first_request_plan", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no plan")))

    async def call():
        sent = asyncio.Event()
        with pytest.raises(RuntimeError):
            await fast_search.first_semantic(None, {"id": 1}, {}, None, sent)
        return sent.is_set()

    assert asyncio.run(call())
