"""An `sw` discovery run whose search words came from the question by code, driven through the API (SW2).

The model adapter here fails on every call, so the run's searches prove that nothing asks a model before the first
search. Records and questions are SYNTHETIC and OpenAlex is mocked: passing shows workflow behavior, not recall.
A `legacy` research is exercised too, because nothing about it may change.
"""

import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents.fetch import FetchResult
from deixis.models.adapter import ModelStepResult
from deixis.providers.registry import CONNECTORS
from deixis.storage import db
from deixis.workflow.vocabulary import VERY_LARGE_COUNT
from deixis.workflow.store import Store
from fakes import FakeAdapter

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

    def __init__(self, count=40, search_hits=True):
        self.counts, self.searches, self.count_value, self.search_hits = [], [], count, search_hits

    def __call__(self, request):
        if request.url.host != "api.openalex.org":
            return httpx.Response(404)
        params = request.url.params
        query = params.get("search.title_and_abstract")
        if params.get("per_page") == "1" and params.get("select") == "id":
            self.counts.append(query)
            return httpx.Response(200, json={"meta": {"count": self.count_value}, "results": []})
        self.searches.append(query)
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
    deadline = time.time() + 15
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


def test_an_sw_discovery_searches_while_every_model_call_fails(tmp_path, monkeypatch):
    openalex, adapter = CountingOpenAlex(), DeadAdapter()
    with TestClient(app_for(tmp_path, monkeypatch, openalex, adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, QUESTION)
        view, run = wait(client, rid, run_id)
        store = client.app.state.store
        decisions = [(row[0], row[1]) for row in store.conn.execute(
            "SELECT reason_code, outcome FROM stage_decisions WHERE research_id = ? AND superseded_at IS NULL", (rid,))]
        selections = [(row[0], row[1]) for row in store.conn.execute(
            "SELECT state, origin FROM selections WHERE research_id = ?", (rid,))]
    # OpenAlex answered and was recorded. The other providers are not mocked here and fail, which D18 lets the
    # run carry on from.
    searched = {s["kind"]: s["status"] for s in run["steps"] if s["operation_key"].startswith("search:")}
    assert searched["provider_search:openalex"] == "succeeded", run["steps"]
    assert openalex.counts and openalex.searches
    # The vocabulary step opens first and the optional block labelling of slice 04d runs inside it; the criterion
    # proposal of slice 06 follows, the approval step of slice 08a closes without stopping in this setup, and the
    # protocol is frozen next, still before any search. The source routing of slice 14 (D93) sits between the
    # vocabulary and the criterion. The fast path's embedding step (`source_similarity`) opens when the run starts and
    # is left out of this order.
    assert [s["operation_key"] for s in run["steps"] if s["operation_key"] != "source_similarity"][:11] == [
        "vocabulary", "vocabulary_labels_1", "vocabulary_labels_2", "vocabulary_labels_3", "source_routing",
        "criterion", "criterion_proposal_1", "criterion_proposal_2", "criterion_proposal_3",
        "protocol_approval", "protocol"]
    # Since slice 09 the one record this fixture finds carries both concept blocks in its title, so the code stage
    # closes it as a candidate and the run needs no model at all: with every model call failing, a whole sw
    # discovery searches, ranks and decides. Nothing it decided is `included`.
    assert run["status"] == "completed" and run["pause_reason"] is None, run
    assert [s["operation_key"] for s in run["steps"]][-1] == "small_batch:v1:summary"
    assert not any(s["kind"] == "model:abstract_screening" for s in run["steps"])
    assert decisions == [("blocks_in_title", "candidate")] and selections == [("pending", "code_rule")]
    assert view["counts"]["unique"] == 1
    # No step input was ever built for a search plan: the words came from the question.
    assert not any(s["operation_key"] == "search_plan" for s in run["steps"])


def test_no_recorded_query_holds_a_claim_word_or_an_exclusion_word(tmp_path, monkeypatch):
    openalex = CountingOpenAlex()
    with TestClient(app_for(tmp_path, monkeypatch, openalex, DeadAdapter())) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, "Which packet size in wireless sensor networks, using integer programming, "
                                    "not surveys?")
        view, run = wait(client, rid, run_id)
    # The keyword queries: the fast path's semantic search sends the question's own sentence and is not one of them.
    keyword = [q for q in openalex.searches if q is not None]
    assert view["search_runs"] and keyword
    for query in keyword:
        assert "integer programming" not in query.lower()
        assert "survey" not in query.lower()
    for probe in openalex.counts:
        assert "integer programming" not in probe.lower() and "survey" not in probe.lower()


def test_a_resumed_run_repeats_no_count_request(tmp_path, monkeypatch):
    """The search fails on the first pass; resuming retries the search and must not probe the counts again."""
    openalex = CountingOpenAlex()
    down = {"now": True}

    def handler(request):
        params = request.url.params
        if down["now"] and not (params.get("per_page") == "1" and params.get("select") == "id"):
            return httpx.Response(503)
        return openalex(request)

    with TestClient(app_for(tmp_path, monkeypatch, handler, DeadAdapter())) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, QUESTION)
        view, run = wait(client, rid, run_id)
        assert run["status"] == "paused" and not openalex.searches
        probed = list(openalex.counts)
        assert probed
        down["now"] = False
        client.post(f"/api/runs/{run_id}/resume")
        view, run = wait(client, rid, run_id)
    assert openalex.searches, run
    assert openalex.counts == probed  # the stored step output was reused whole


def test_a_question_code_cannot_read_stops_for_key_terms_and_the_next_revision_searches(tmp_path, monkeypatch):
    openalex = CountingOpenAlex()
    app = app_for(tmp_path, monkeypatch, openalex, DeadAdapter())
    with TestClient(app) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, TURKISH)
        view, run = wait(client, rid, run_id)
        assert (run["status"], run["pause_reason"]) == ("paused", "key_terms_needed"), run
        assert not openalex.counts and not openalex.searches
        version = client.get(f"/api/researches/{rid}").json()["research"]["version"]
        revised = client.post(f"/api/researches/{rid}/scope",
                              json={"question": TURKISH, "expected_version": version, "key_terms": KEY_TERMS})
        assert revised.status_code == 200, revised.text
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        view, run = wait(client, rid, second)
    # The keyword queries (the semantic search and the chain carry no keyword query).
    keyword = [q for q in openalex.searches if q is not None]
    assert keyword, run
    # The user's setting block gated the search; the claim group they wrote is in no query.
    assert all("wireless" in q for q in keyword)
    assert all("integer programming" not in q and "survey" not in q for q in keyword)


def test_the_frozen_protocol_holds_the_concept_blocks_and_is_the_same_on_a_second_build(tmp_path, monkeypatch):
    with TestClient(app_for(tmp_path, monkeypatch, CountingOpenAlex(), DeadAdapter())) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
    from deixis.domain.canonical import sha256_hex
    from deixis.workflow import protocol

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

    # The queries searched are the ones the source routing compiled (D93), and its record is an input of the body.
    stored = store.latest_step_output(rid, "source_routing", 1)
    run_id = store.conn.execute("SELECT id FROM runs WHERE research_id = ?", (rid,)).fetchone()[0]
    again = protocol.build_protocol(store.scope(rid, 1), store.run(run_id)["budget"], None, stored["queries"],
        body["skill_package_hash"], Settings(data_dir=None, search_query="code"), vocabulary=stored["vocabulary"],
        approval=store.approval_step(run_id)["output"]["approval"], routing=stored["routing"],
        # The fast path's own inputs, frozen beside the others: the semantic search model and the search plan.
        embedding_model=next(s["model"] for s in body["signals"] if s["signal"] == "embedding"),
        fast_path_search=body["fast_path_search"])
    assert sha256_hex(again) == rows[0]["body_sha256"]




# A vocabulary that cannot be searched ends the run (clean start, decision B): no approval card is opened, nothing is
# searched, resuming is refused, and the way on is a new scope revision whose question can be searched.
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
    assert openalex.counts and not openalex.searches and not view["search_runs"]
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


@pytest.mark.parametrize("reason", sorted(UNSEARCHABLE))
def test_a_run_ended_for_its_vocabulary_cannot_be_resumed_and_a_revised_question_searches(tmp_path, monkeypatch, reason):
    count, question, revised = UNSEARCHABLE[reason]
    openalex = CountingOpenAlex(count=count)
    with TestClient(app_for(tmp_path, monkeypatch, openalex, DeadAdapter())) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, question)
        wait(client, rid, run_id)
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 409
        time.sleep(0.2)
        _, run = wait(client, rid, run_id)
        assert (run["status"], run["pause_reason"]) == ("failed", reason), run
        assert not openalex.searches
        # The user edits the question: a new scope revision, whose discovery run searches as any other does.
        openalex.count_value = 40
        version = client.get(f"/api/researches/{rid}").json()["research"]["version"]
        response = client.post(f"/api/researches/{rid}/scope", json={"question": revised, "expected_version": version})
        assert response.status_code == 200, response.text
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        view, run = wait(client, rid, second)
    assert (run["status"], run["pause_reason"]) == ("completed", None), run
    assert run["scope_revision"] == 2 and openalex.searches and view["search_runs"]
    assert run["approval"]["approved_by"] == "unattended"
    first = next(r for r in view["runs"] if r["id"] == run_id)
    assert (first["status"], first["pause_reason"]) == ("failed", reason)


def test_key_terms_survive_a_revision_that_does_not_name_them(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, CountingOpenAlex(), DeadAdapter())
    with TestClient(app) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, _ = start(client, TURKISH, key_terms=KEY_TERMS)
        version = client.get(f"/api/researches/{rid}").json()["research"]["version"]
        client.post(f"/api/researches/{rid}/scope", json={"question": TURKISH + " (v2)", "expected_version": version})
    store = store_at(tmp_path)
    assert store.scope(rid, 1)["key_terms"] == KEY_TERMS
    assert store.scope(rid, 2)["key_terms"] == KEY_TERMS
