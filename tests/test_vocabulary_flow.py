"""An `sw` discovery run whose search words came from the question by code, driven through the API (SW2).

The model adapter here fails on every call, so the run's searches prove that nothing asks a model before the first
search. Records and questions are SYNTHETIC and OpenAlex is mocked: passing shows workflow behavior, not recall.
A `legacy` research is exercised too, because nothing about it may change.
"""

import json
import time

import httpx
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents.fetch import FetchResult
from deixis.models.adapter import ModelStepResult
from deixis.providers.registry import CONNECTORS
from deixis.storage import db
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
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_workflow=workflow),
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
    # OpenAlex answered and was recorded; the run stops at screening, the first step that needs a model.
    # The other providers are not mocked here and fail, which D18 lets the run carry on from.
    searched = {s["kind"]: s["status"] for s in run["steps"] if s["operation_key"].startswith("search:")}
    assert searched["provider_search:openalex"] == "succeeded", run["steps"]
    assert openalex.counts and openalex.searches
    assert [s["operation_key"] for s in run["steps"]][:2] == ["vocabulary", "protocol"]
    assert run["status"] == "paused" and run["pause_reason"] == "model_call_failed", run
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
    assert view["search_runs"]
    for search in view["search_runs"]:
        assert "integer programming" not in search["query_text"].lower()
        assert "survey" not in search["query_text"].lower()
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
    assert openalex.searches, run
    # The user's setting block gated the search; the claim group they wrote is in no query.
    assert all("wireless" in q for q in openalex.searches)
    assert all("integer programming" not in q and "survey" not in q for q in openalex.searches)


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
    assert body["vocabulary"] and all(term["origin"] == "question" for term in body["vocabulary"])
    assert body["code_version"].endswith("deixis.query_compiler.v4.blocks")

    stored = store.latest_step_output(rid, "vocabulary", 1)
    again = protocol.build_protocol(store.scope(rid, 1), store.run(store.conn.execute(
        "SELECT id FROM runs WHERE research_id = ?", (rid,)).fetchone()[0])["budget"], None, stored["queries"],
        body["skill_package_hash"], Settings(data_dir=None, search_workflow="sw"), vocabulary=stored["vocabulary"])
    assert sha256_hex(again) == rows[0]["body_sha256"]


def test_a_legacy_research_still_runs_its_search_plan_step_and_opens_no_vocabulary_step(tmp_path, monkeypatch):
    from test_provider_flow import routed, two_provider_plan

    adapter = FakeAdapter(two_provider_plan)
    with TestClient(app_for(tmp_path, monkeypatch, routed, adapter, workflow="legacy")) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, "How is diffusion channel scheduling optimized?")
        view, run = wait(client, rid, run_id)
    assert run["status"] == "completed", run
    keys = [s["operation_key"] for s in run["steps"]]
    assert "search_plan" in keys and "vocabulary" not in keys
    assert [c["task_type"] for c in adapter.calls].count("search_plan") == 1


def test_a_vocabulary_that_matches_nothing_stops_the_run_before_any_search(tmp_path, monkeypatch):
    openalex = CountingOpenAlex(count=0)
    with TestClient(app_for(tmp_path, monkeypatch, openalex, DeadAdapter())) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, QUESTION)
        view, run = wait(client, rid, run_id)
    assert (run["status"], run["pause_reason"]) == ("paused", "vocabulary_empty"), run
    assert not openalex.searches
    step = next(s for s in run["steps"] if s["operation_key"] == "vocabulary")
    assert step["status"] == "succeeded"  # the counts are kept, so resuming pays for none of them again


def test_one_block_of_terms_too_frequent_to_search_stops_the_run(tmp_path, monkeypatch):
    from deixis.workflow.vocabulary import VERY_LARGE_COUNT

    openalex = CountingOpenAlex(count=VERY_LARGE_COUNT + 1)
    with TestClient(app_for(tmp_path, monkeypatch, openalex, DeadAdapter())) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, "Which networks are reported?")
        view, run = wait(client, rid, run_id)
    assert (run["status"], run["pause_reason"]) == ("paused", "vocabulary_too_broad"), run
    assert not openalex.searches


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
