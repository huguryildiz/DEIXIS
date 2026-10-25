"""Record-level ranking inside an `sw` discovery run (SW7, SW8, slice 07).

What is checked here is workflow behavior: which candidate screening reads first, that the order deletes nothing and
decides nothing, that ranking runs with the model down, that a resumed run ranks once, and that a `legacy` research
gains none of it. Records, titles, reference lists and embeddings are SYNTHETIC and every transport is mocked:
passing shows that the step behaves as the slice says, not that the order finds relevant literature.
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
from deixis.workflow import ranking
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.store import Store
from fakes import FakeAdapter, valid_response

QUESTION = "What is the effect of packet size on energy consumption in wireless sensor networks?"
# The one record whose title answers the question. The provider returns it last, so the provider's own order and the
# ranking disagree about it, which is the whole point of the step.
STRONG = "SYNTHETIC packet size and energy consumption in wireless sensor networks"
BAKERY = "SYNTHETIC bakery logistics of a small town"
DECISION_TABLES = ("stage_decisions", "model_proposals", "record_flags", "record_links", "selections")


def work(number, title, abstract, references=None):
    inverted: dict[str, list[int]] = {}
    for position, word in enumerate(abstract.split()):
        inverted.setdefault(word, []).append(position)  # a repeated word keeps every one of its places
    payload = {"id": f"https://openalex.org/W{number}", "doi": f"https://doi.org/10.1/oa.{number}",
               "display_name": f"{title} {number}", "publication_year": 2024, "type": "article", "authorships": [],
               "abstract_inverted_index": inverted}
    if references is not None:
        payload["referenced_works"] = [f"https://openalex.org/{ref}" for ref in references]
    return payload


def pool(size=24):
    """`size` SYNTHETIC records of two fields; the last one answers the question, the rest are off topic.

    Each off-topic record repeats one of the question's words a different number of times, so no two records tie in
    BM25. A tie would be broken by the record identifier, which is generated per database, and the three runs of
    `test_the_four_code_signals_rank_the_same_...` compare three databases.
    """
    works = [work(number, BAKERY, "We deliver SYNTHETIC bread every morning to the market." + " energy" * (number + 1),
                  ["W900", "W901"]) for number in range(size - 1)]
    return works + [work(size - 1, STRONG,
                         "We choose the SYNTHETIC packet size that lowers the energy a sensor spends.",
                         ["W900", "W902"])]


class Pool:
    """OpenAlex answering every count probe and serving one page of records, plus the Gemini embedding endpoint.

    A probe holding `AND` is the expansion's field probe and is answered too low to accept a phrase, so this fixture
    reads one round. `embedding` names the record the mocked embedder puts first; without it every text is equally
    far from the question.
    """

    def __init__(self, works=None, embedding=None, embedding_status=200):
        self.works = pool() if works is None else works
        self.embedding, self.embedding_status = embedding, embedding_status
        self.probes, self.searches, self.embedded = [], [], []

    def __call__(self, request):
        if request.url.host == "generativelanguage.googleapis.com":
            return self._embed(request)
        if request.url.host != "api.openalex.org":
            return httpx.Response(404)  # the other providers are not mocked and fail, which D18 carries on from
        params = request.url.params
        query = params.get("search.title_and_abstract") or ""
        if params.get("per_page") == "1" and params.get("select") == "id":
            self.probes.append(query)
            return httpx.Response(200, json={"meta": {"count": 1 if " AND " in query else 40}, "results": []})
        self.searches.append((query, params.get("select")))
        return httpx.Response(200, json={"meta": {"count": len(self.works), "next_cursor": None},
                                         "results": self.works})

    def _embed(self, request):
        if self.embedding_status != 200:
            return httpx.Response(self.embedding_status)
        requests = json.loads(request.content)["requests"]
        texts = [row["content"]["parts"][0]["text"] for row in requests]
        # The question stands at [1, 0]; a record the fixture names stands there too and every other record at
        # [0, 1], so exactly one record has similarity 1 and the rest have 0.
        question = [row.get("taskType") == "RETRIEVAL_QUERY" for row in requests]
        self.embedded.extend(text for text, is_query in zip(texts, question) if not is_query)
        return httpx.Response(200, json={"embeddings": [
            {"values": [1.0, 0.0] if is_query or (self.embedding and self.embedding in text) else [0.0, 1.0]}
            for text, is_query in zip(texts, question)]})


async def no_fetch(url):
    return FetchResult("http_error", final_url=url, http_status=404)


def DeadAdapter():
    return FakeAdapter(fail=lambda si: ModelStepResult("failed", error="SYNTHETIC model connection is down"))


def app_for(tmp_path, monkeypatch, handler, workflow="sw", adapter=None, embedding=False):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    if embedding:
        monkeypatch.setenv("GEMINI_API_KEY", "SYNTHETIC-key")
    else:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", workflow)
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_query="code",
                               fulltext_fetch="off"),
                      adapters={"fake": adapter or FakeAdapter(valid_response)},
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), fetcher=no_fetch,
                      extra_hosts=("testserver",), trusted_clients=("testclient",))


def wait(client, rid, run_id):
    deadline = time.time() + 30
    while time.time() < deadline:
        view = client.get(f"/api/researches/{rid}").json()
        run = next(r for r in view["runs"] if r["id"] == run_id)
        if run["status"] in ("completed", "failed", "paused"):
            return view, run
        time.sleep(0.05)
    raise AssertionError("the run did not settle")


def client_of(app):
    client = TestClient(app)
    client.__enter__()
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    return client


def discover(client, question=QUESTION, effort="quick", **body):
    payload = {"question": question, "model_connection": "fake", "requested_model": "fake-model", "effort": effort,
               **body}
    rid = client.post("/api/researches", json=payload).json()["research"]["id"]
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    return rid, run_id, *wait(client, rid, run_id)


def step_output(store, run_id, key):
    from batch_outputs import stage_output
    return stage_output(store, run_id, key)


def decision_of(store, rid, svid):
    """The record's open abstract-stage decision."""
    return DecisionStore(store).current(rid, svid, "abstract") or {"reason_code": None}


def table_rows(store, rid):
    """Every row the slice must not write. `record_links` is library-wide, so it is read through the candidates."""
    where = {"record_links": "source_version_id IN (SELECT source_version_id FROM candidates WHERE research_id = ?)"}
    return {table: [dict(row) for row in store.conn.execute(
        f"SELECT * FROM {table} WHERE {where.get(table, 'research_id = ?')}", (rid,))] for table in DECISION_TABLES}


# ---- the order screening reads --------------------------------------------------------------


def test_the_ranking_step_writes_no_row_in_any_decision_table(tmp_path, monkeypatch):
    """The step orders and stores ranks; every decision this run holds was written by another step."""
    app = app_for(tmp_path, monkeypatch, Pool(), adapter=DeadAdapter())
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        rows = table_rows(store, rid)
        ranking_step = store.step(run_id, "ranking", "code:ranking")["id"]
        ranked = store.conn.execute("SELECT COUNT(*) FROM record_signal_ranks WHERE research_id = ?", (rid,)).fetchone()[0]
        step = step_output(store, run_id, "ranking")
    finally:
        client.__exit__(None, None, None)
    assert ranked > 0 and step["pool"] == 24
    # The abstract stage of slice 09 writes decisions in the same run; none of them came from this step, and with
    # the connection down no model proposed anything.
    assert all(row["step_id"] != ranking_step for row in rows["stage_decisions"])
    assert rows["model_proposals"] == [] and rows["record_flags"] == []
    assert {row["state"] for row in rows["selections"]} == {"pending"}
    assert all(row["proposal"] is None for row in rows["selections"])


# ---- the embedding has no authority ----------------------------------------------------------


# ---- a resumed run, a second run, and what the step does not repeat ---------------------------

def test_a_resumed_run_ranks_once_and_screens_the_same_records_in_the_same_order(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, Pool(), adapter=DeadAdapter())
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        first = DecisionStore(store).latest_ranking(rid, 1)
        rows = store.conn.execute("SELECT COUNT(*) FROM record_signal_ranks WHERE research_id = ?", (rid,)).fetchone()[0]
        client.post(f"/api/runs/{run_id}/resume")
        view, run = wait(client, rid, run_id)
        again = DecisionStore(store).latest_ranking(rid, 1)
        rows_again = store.conn.execute("SELECT COUNT(*) FROM record_signal_ranks WHERE research_id = ?", (rid,)).fetchone()[0]
        steps = [s for s in store.run_steps(run_id) if s["operation_key"] == "ranking"]
    finally:
        client.__exit__(None, None, None)
    assert first == again and rows == rows_again and len(steps) == 1


# ---- legacy is untouched ---------------------------------------------------------------------


# ---- the protocol -----------------------------------------------------------------------------


# ---- the pool and the seeds, read straight from the store --------------------------------------

def term(phrase, block):
    return {"phrase": phrase, "block": block, "origin": "question", "root": phrase, "in_query": "phrase",
            "phrase_count": 1, "root_count": 1, "and_only": False, "dropped": None}


VOCABULARY = {"terms": [term("wireless sensor networks", "setting"), term("packet size", "task")]}


def provider_record(number, title, abstract="SYNTHETIC abstract of a record.", references=None, doi=None,
                    version_label="publishedVersion", merge_by_doi=True, **identifiers):
    from deixis.providers.common import ProviderRecord
    return ProviderRecord(
        provider_record_id=f"W{number}", title=title, authors=[], year=2026, venue=None, publication_type=None,
        doi=doi or f"10.1/synth.{number}", landing_url=None, oa_pdf_url=None, oa_pdf_version=None,
        version_label=version_label, abstract=abstract, abstract_origin="provider" if abstract else None,
        identifiers=identifiers, raw={}, references=references, merge_by_doi=merge_by_doi)


def stored_research(tmp_path, records, workflow="sw"):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research(QUESTION, "academic", "standard", ["openalex"], "fake", "m", "en",
                                search_workflow=workflow)
    run = store.create_run(rid, "discovery", {"max_model_calls": 4, "max_provider_requests": 4, "max_candidates": 500,
                                              "max_answer_passages": 8}, None)
    step = store.step(run["id"], "search:0", "provider_search:openalex")
    store.record_search(
        dict(research_id=rid, run_id=run["id"], step_id=step["id"], scope_revision=1, provider="openalex",
             query_text="q", request_description="GET test", access_mode="keyless", status="completed",
             delivery_class=None, result_count=len(records), provider_total=len(records), page_limit=200,
             error_json=None, raw_payload_path=None),
        "openalex", records, None, step["id"], "succeeded", step_output={"status": "completed"})
    return store, rid, run


def rank(store, rid, run, embedding_model=None):
    return ranking.rank_records(store, run, store.scope(rid), VOCABULARY, embedding_model)


def test_a_record_the_user_included_becomes_a_seed_and_a_record_the_model_included_does_not(tmp_path):
    store, rid, run = stored_research(tmp_path, [provider_record(i, f"{BAKERY} {i}", references=("W900",))
                                                 for i in range(3)])
    chosen, other = (store.find_source_by_identifier("openalex", f"W{i}") for i in (0, 1))
    store.conn.execute("UPDATE selections SET state = 'included', origin = 'model_proposal' WHERE source_version_id = ?",
                       (other,))
    assert rank(store, rid, run)["signals"]["tfidf"]["ran"] is False  # a model proposal is not verification
    store.conn.execute("UPDATE selections SET state = 'included', origin = 'user' WHERE source_version_id = ?", (chosen,))
    store.update_run(run["id"], status="completed")
    run = store.create_run(rid, "discovery", run["budget"], None)
    output = rank(store, rid, run)
    assert output["signals"]["tfidf"]["ran"] is True
    assert [seed["kind"] for seed in output["seeds"] if seed["source_version_id"] == chosen] == ["verified"]
    # The record the user included is a seed and no longer a candidate the ranking reads: it is already decided.
    assert output["pool"] == 2
    store.conn.close()
