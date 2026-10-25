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
