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
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_workflow=workflow,
                               protocol_approval="as_proposed"),
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
    row = store.conn.execute("SELECT output_json FROM run_steps WHERE run_id = ? AND operation_key = ?",
                             (run_id, key)).fetchone()
    return None if row is None or row[0] is None else json.loads(row[0])


def rank_rows(store, rid, signals=ranking.CODE_SIGNALS):
    """Every stored rank of the named signals, in an order no step id can change."""
    return sorted((row["signal"], store.source(row["source_version_id"])["title"], row["rank"], row["available"])
                  for row in store.conn.execute(
                      "SELECT signal, source_version_id, rank, available FROM record_signal_ranks WHERE research_id = ?",
                      (rid,)) if row["signal"] in signals)


def decision_of(store, rid, svid):
    """The record's open abstract-stage decision."""
    return DecisionStore(store).current(rid, svid, "abstract") or {"reason_code": None}


def ordered_titles(store, rid, revision=1):
    return [store.source(svid)["title"] for svid in DecisionStore(store).latest_ranking(rid, revision)]


def table_rows(store, rid):
    """Every row the slice must not write. `record_links` is library-wide, so it is read through the candidates."""
    where = {"record_links": "source_version_id IN (SELECT source_version_id FROM candidates WHERE research_id = ?)"}
    return {table: [dict(row) for row in store.conn.execute(
        f"SELECT * FROM {table} WHERE {where.get(table, 'research_id = ?')}", (rid,))] for table in DECISION_TABLES}


def screened_titles(store, run_id, key="abstract_screening:0:1"):
    """The candidate titles of one screening call, in the order the step input listed them.

    Since slice 09 an `sw` run screens through the abstract stage; the stored payload keeps the real record rows
    (the model itself was shown short handles).
    """
    row = store.conn.execute(
        "SELECT i.payload_json FROM step_inputs i JOIN run_steps s ON s.id = i.step_id"
        " WHERE s.run_id = ? AND s.operation_key = ? ORDER BY i.rowid LIMIT 1", (run_id, key)).fetchone()
    return [] if row is None else [c["title"] for c in json.loads(row[0])["candidates"]]


# ---- the order screening reads --------------------------------------------------------------

def test_the_screening_list_follows_the_inspection_order_and_not_the_provider_s(tmp_path, monkeypatch):
    """The provider returned the one record that answers the question last; the ranking puts it first."""
    handler = Pool()
    app = app_for(tmp_path, monkeypatch, handler)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        output = step_output(store, run_id, "ranking")
        plan = step_output(store, run_id, "abstract_stage")
        titles = ordered_titles(store, rid)
        screened = screened_titles(store, run_id)
        second_place = DecisionStore(store).latest_ranking(rid, 1)[1]
        provider_order = [store.source(c["source_version_id"])["title"] for c in store.candidates(rid, 1)]
    finally:
        client.__exit__(None, None, None)
    assert output["pool"] == 24 and output["signals"]["bm25"]["ran"] is True
    assert titles[0].startswith(STRONG), titles[:3]
    # The provider returned that record last; the ranking puts it first. Code closes it as a candidate before any
    # model is asked (both concept blocks stand in its title), so the batch the model reads starts at the order's
    # second place and follows it from there (slice 09).
    assert provider_order[-1].startswith(STRONG)
    assert plan["batches"][0][0] == second_place
    assert screened == [title for title in titles[1:] if not title.startswith(STRONG)][:len(screened)]


def test_the_read_limit_cuts_by_the_new_order_deletes_nothing_and_max_candidates_cuts_nothing(tmp_path, monkeypatch):
    """SW7.2 and slice 09: the read limit replaced `max_candidates` here, and what it leaves out stays unread.

    A pool of 45 at quick effort, whose read limit is 40 and whose `max_candidates` is 20: if the old limit still
    cut, 25 works would never be looked at.
    """
    app = app_for(tmp_path, monkeypatch, Pool(pool(45)))
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        candidates = store.candidates(rid, 1)
        order = DecisionStore(store).latest_ranking(rid, 1)
        plan = step_output(store, run_id, "abstract_stage")
        decided = {row["source_version_id"]: decision_of(store, rid, row["source_version_id"])
                   for row in candidates}
        states = {row["state"] for row in candidates}
    finally:
        client.__exit__(None, None, None)
    assert len(candidates) == 45 and len(order) == 45  # nothing was removed and everything was ranked
    assert plan["limit"] == 40 and sum(len(batch) for batch in plan["batches"]) + plan["not_read"] == 44
    # The read plan followed the order: the works left unread are the last ones in it, not the last found.
    unread = {svid for svid, row in decided.items() if row["reason_code"] == "abstract_not_read"}
    assert unread == set(order[-plan["not_read"]:])
    assert plan["not_read"] == 4 and states == {"pending"}


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


def test_ranking_runs_and_stores_its_ranks_while_every_model_call_fails(tmp_path, monkeypatch):
    """SW7 is code: with the connection down the run still searches, ranks and keeps every rank."""
    app = app_for(tmp_path, monkeypatch, Pool(), adapter=DeadAdapter())
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        output = step_output(store, run_id, "ranking")
        titles = ordered_titles(store, rid)
    finally:
        client.__exit__(None, None, None)
    assert (run["status"], run["pause_reason"]) == ("paused", "model_call_failed"), run
    statuses = {s["operation_key"]: s["status"] for s in run["steps"]}
    assert statuses["ranking"] == "succeeded"
    assert titles[0].startswith(STRONG)
    assert output["signals"]["tfidf"] == {"ran": False, "reason": "no_verified_seeds", "available": 0}


def test_the_reported_share_of_records_without_a_reference_list_counts_them(tmp_path, monkeypatch):
    """SW7.4 asks for this number with every ranking; more than half the measured pool had no list."""
    works = pool(size=4)
    works[0].pop("referenced_works")  # one record OpenAlex answered without the field
    works[1]["referenced_works"] = []  # and one it answered with an empty list
    app = app_for(tmp_path, monkeypatch, Pool(works), adapter=DeadAdapter())
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        output = step_output(app.state.store, run_id, "ranking")
    finally:
        client.__exit__(None, None, None)
    assert (output["pool"], output["no_reference_list"], output["no_reference_list_share"]) == (4, 2, 0.5)
    assert output["signals"]["graph"]["available"] == 2


# ---- the embedding has no authority ----------------------------------------------------------

def code_signal_rows(tmp_path, monkeypatch, **kwargs):
    app = app_for(tmp_path, monkeypatch, Pool(**kwargs), adapter=DeadAdapter(), embedding=bool(kwargs))
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        rows = rank_rows(app.state.store, rid)
        output = step_output(app.state.store, run_id, "ranking")
    finally:
        client.__exit__(None, None, None)
    return rows, output


def test_the_four_code_signals_rank_the_same_with_the_embedding_off_failing_or_on(tmp_path, monkeypatch):
    """SW8.5: without a model, with a failed call or with a working one, the code signals are the same ranks."""
    off, off_output = code_signal_rows(tmp_path / "off", monkeypatch)
    broken, broken_output = code_signal_rows(tmp_path / "broken", monkeypatch, embedding_status=503)
    on, on_output = code_signal_rows(tmp_path / "on", monkeypatch, embedding=STRONG)
    assert off == broken == on
    assert off_output["signals"]["embedding"] == {"ran": False, "reason": "embedding_off", "available": 0}
    assert broken_output["signals"]["embedding"] == {"ran": False, "reason": "no_stored_similarity", "available": 0}
    assert on_output["signals"]["embedding"]["ran"] is True
    assert (off_output["embedding_model"], on_output["embedding_model"]) == (None, "gemini-embedding-2")
    assert off_output["rescued"] == broken_output["rescued"] == []


def test_the_embedding_arm_lifts_a_record_the_code_signals_left_behind(tmp_path, monkeypatch):
    """SW8.1, with the arm's two limits lowered so the fixture stays small; the real 200 and 50 are unit-tested."""
    monkeypatch.setattr(ranking, "RESCUE_OUTSIDE_TOP", 5)
    monkeypatch.setattr(ranking, "RESCUE_EMBEDDING_TOP", 1)
    # The embedder puts one bakery record first; the code signals cannot tell it from the other bakery records.
    lifted = f"{BAKERY} 7"
    app = app_for(tmp_path, monkeypatch, Pool(embedding=lifted), adapter=DeadAdapter(), embedding=True)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        output = step_output(store, run_id, "ranking")
        titles = ordered_titles(store, rid)
        rescued = [store.source(svid)["title"] for svid in output["rescued"]]
    finally:
        client.__exit__(None, None, None)
    assert rescued == [lifted] and titles[0] == lifted
    # It was lifted, not included: the record is still `pending` and no decision was written for it.
    assert output["signals"]["embedding"]["ran"] is True


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


def test_a_second_discovery_run_of_the_same_scope_ranks_again_and_leaves_the_first_rows_alone(tmp_path, monkeypatch):
    handler = Pool()
    app = app_for(tmp_path, monkeypatch, handler, adapter=DeadAdapter())
    client = client_of(app)
    try:
        rid, first_run, view, run = discover(client)
        store = app.state.store
        first_step = next(s for s in store.run_steps(first_run) if s["operation_key"] == "ranking")
        second_run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, second_run)
        second_step = next(s for s in store.run_steps(second_run) if s["operation_key"] == "ranking")
        decisions = DecisionStore(store)
        steps = {row[0] for row in store.conn.execute(
            "SELECT DISTINCT ranking_step_id FROM record_signal_ranks WHERE research_id = ?", (rid,))}
        latest = decisions.latest_ranking(rid, 1)
        earlier = decisions.ranking_order(first_step["id"])
        newest = decisions.ranking_order(second_step["id"])
    finally:
        client.__exit__(None, None, None)
    assert first_step["id"] != second_step["id"]
    assert steps == {first_step["id"], second_step["id"]}  # the first run's rows are still there
    assert latest == newest and earlier == newest  # the same pool, so the same order, written twice


# ---- legacy is untouched ---------------------------------------------------------------------

def test_a_legacy_research_opens_no_ranking_step_and_scores_its_sources_where_it_always_did(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, Pool(), workflow="legacy", embedding=True)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        keys = [s["operation_key"] for s in store.run_steps(run_id)]
        body = json.loads(store.conn.execute(
            "SELECT body_json FROM protocol_records WHERE research_id = ?", (rid,)).fetchone()[0])
    finally:
        client.__exit__(None, None, None)
    assert "ranking" not in keys and "source_similarity" in keys
    assert keys.index("source_similarity") > keys.index("screening")  # after screening, as before this slice
    assert body["signals"] == [] and "ranking" not in body["thresholds"]


def test_an_sw_run_scores_the_whole_pool_before_it_ranks_and_not_again_after_screening(tmp_path, monkeypatch):
    handler = Pool(embedding=STRONG)
    app = app_for(tmp_path, monkeypatch, handler, embedding=True)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        keys = [s["operation_key"] for s in app.state.store.run_steps(run_id)]
    finally:
        client.__exit__(None, None, None)
    # Every record of the pool was embedded, not only the 20 the candidate limit screens.
    assert len([text for text in handler.embedded if text.startswith("SYNTHETIC")]) == 24
    assert keys.index("source_similarity") < keys.index("ranking") < keys.index("abstract_stage")


# ---- the protocol -----------------------------------------------------------------------------

def test_the_frozen_body_names_the_signals_and_the_expansion_revision_carries_them(tmp_path, monkeypatch):
    from test_expansion_flow import Field, app_for as expansion_app, client_of as expansion_client, discover as expand

    app = expansion_app(tmp_path, monkeypatch, Field())
    client = expansion_client(app)
    try:
        rid, run_id, view, run = expand(client)
        bodies = [json.loads(row["body_json"]) for row in app.state.store.conn.execute(
            "SELECT body_json FROM protocol_records WHERE research_id = ? ORDER BY protocol_revision", (rid,))]
    finally:
        client.__exit__(None, None, None)
    assert len(bodies) == 2
    for body in bodies:
        assert [s["signal"] for s in body["signals"]] == list(ranking.SIGNALS)
        assert body["thresholds"]["ranking"] == ranking.THRESHOLDS
    # Both revisions name the same embedding model, so the expansion revision never reads as "ordered without one".
    assert {json.dumps(body["signals"], sort_keys=True) for body in bodies} == {
        json.dumps(bodies[0]["signals"], sort_keys=True)}


def test_changing_the_embedding_setting_makes_no_decision_stale(tmp_path, monkeypatch):
    """`signals` is outside `CRITERION_FIELDS` on purpose: a setting is not a criterion (SW11.10)."""
    from deixis.workflow import protocol

    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC question?", "academic", "quick", ["openalex"], "fake", "m", "en",
                                search_workflow="sw")
    scope = store.scope(rid)
    settings = Settings(data_dir=tmp_path / "data", search_workflow="sw")
    criterion = {"criterion": "SYNTHETIC: the paper states a model.", "parts": [], "cue_phrases": [],
                 "exclusion_title_words": [], "origin": "consensus", "base_run": 1, "runs_ok": 3,
                 "dropped_exclusion_title_words": [], "sought_term_in_criterion": True}
    body = protocol.build_protocol(scope, {}, None, [], "pkg", settings, criterion=criterion, embedding_model=None)
    store.freeze_protocol(rid, 1, body)
    record = store.upsert_provider_source("openalex", _one_record(), None)[0]
    store.add_to_corpus(rid, record, "search", rank=0, scope_revision=1)
    decisions = DecisionStore(store)
    decision = decisions.record(rid, record, "blocks_in_title")
    assert decisions.is_stale(decision) is False
    changed = protocol.build_protocol(scope, {}, None, [], "pkg", settings, criterion=criterion,
                                      embedding_model="gemini-embedding-2")
    store.freeze_protocol(rid, 1, changed, reason="semantic search changed")
    assert changed["signals"][-1]["model"] == "gemini-embedding-2"
    assert decisions.is_stale(decision) is False
    conn.close()


def _one_record():
    from deixis.providers.common import ProviderRecord
    return ProviderRecord(provider_record_id="W1", title=STRONG, authors=[], year=2026, venue=None,
                          publication_type=None, doi="10.1/synth.1", landing_url=None, oa_pdf_url=None,
                          oa_pdf_version=None, version_label=None, abstract="SYNTHETIC abstract.",
                          abstract_origin="provider", identifiers={}, raw={})


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
    return ranking.rank_records(store, run, store.scope(rid), VOCABULARY, [], embedding_model)


def test_without_a_verified_seed_tfidf_does_not_run_at_all(tmp_path):
    """SW7.5: with unverified seeds the seed-based text signal is left out; the graph signal stays."""
    store, rid, run = stored_research(tmp_path, [provider_record(i, f"{BAKERY} {i}", references=("W900",))
                                                 for i in range(3)])
    output = rank(store, rid, run)
    assert output["signals"]["tfidf"] == {"ran": False, "reason": "no_verified_seeds", "available": 0}
    assert output["signals"]["graph"]["ran"] is True
    signals = {row[0] for row in store.conn.execute("SELECT DISTINCT signal FROM record_signal_ranks WHERE research_id = ?", (rid,))}
    assert "tfidf" not in signals and {"bm25", "blocks", "graph", "fused", "inspection"} <= signals
    store.conn.close()


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


def test_a_work_whose_reference_list_is_only_on_its_preprint_still_has_a_graph_signal(tmp_path):
    """The head is the published record; the preprint of the same work carries the list OpenAlex answered with."""
    arxiv_doi = "10.48550/arxiv.2601.00001"  # one DOI over several file versions, so the record never merges by it
    records = [provider_record(1, "SYNTHETIC one work, two records", doi=arxiv_doi, version_label="submittedVersion",
                               references=("W900", "W901"), merge_by_doi=False, published_doi="10.1/synth.2"),
               provider_record(2, "SYNTHETIC one work, two records", doi="10.1/synth.2", references=None),
               provider_record(3, f"{BAKERY} 3", references=("W900",))]
    store, rid, run = stored_research(tmp_path, records)
    preprint = store.find_source_by_identifier("openalex", "W1")
    head = store.work_heads(rid)[store.source(preprint)["work_id"]]
    output = rank(store, rid, run)
    assert head != preprint  # the published record heads the work and carries no list of its own
    assert store.conn.execute("SELECT references_read FROM source_versions WHERE id = ?", (head,)).fetchone()[0] == 0
    ranks = {row[0]: row[1] for row in store.conn.execute(
        "SELECT signal, available FROM record_signal_ranks WHERE source_version_id = ? AND signal = 'graph'", (head,))}
    assert ranks == {"graph": 1} and output["signals"]["graph"]["ran"] is True
    store.conn.close()


def test_a_record_held_back_from_screening_is_still_ranked(tmp_path):
    """Slice 05 keeps a record without an abstract away from the model; the order still places it (slice 15 reads it)."""
    records = [provider_record(1, "SYNTHETIC record with no abstract of its own", abstract=None),
               provider_record(2, f"{BAKERY} 2")]
    store, rid, run = stored_research(tmp_path, records)
    from deixis.workflow import lookups

    held = lookups.held_from_screening(store, rid, 1)
    output = rank(store, rid, run)
    step = store.step(run["id"], "ranking", "code:ranking")
    order = DecisionStore(store).ranking_order(step["id"])
    assert len(held) == 1 and held <= set(order)
    assert output["pool"] == 2 and output["no_abstract"] == 1
    store.conn.close()


def test_the_number_of_queries_does_not_grow_with_the_pool(tmp_path):
    """A pool ten times the size costs the same number of reads: nothing here asks per record (slice 05 review)."""
    counted = []

    def ranked(path, size):
        store, rid, run = stored_research(path, [provider_record(i, f"{BAKERY} {i}", references=("W900",))
                                                 for i in range(size)])
        queries = []
        store.conn.set_trace_callback(queries.append)
        try:
            rank(store, rid, run)
        finally:
            store.conn.set_trace_callback(None)
            store.conn.close()
        # Only the reads are counted: the one write is an `executemany` whose rows grow with the pool by design.
        return len([sql for sql in queries if sql.lstrip().upper().startswith("SELECT")])

    counted.append(ranked(tmp_path / "small", 20))
    counted.append(ranked(tmp_path / "large", 200))
    assert counted[0] == counted[1], counted


def test_a_run_paused_between_two_screening_batches_screens_the_next_places_of_the_order_when_it_resumes(tmp_path, monkeypatch):
    """The first batch's records now carry a decision; they must not push the rest of the order out of its batches.

    The read plan is frozen in the code step's output, so a resumed run finds the same batches under the same keys
    even though "the works still needing a model" is a shorter list by then.
    """
    from deixis.domain.rules import ABSTRACT_BATCH

    failed = []

    def fail_the_second_batch_once(si):
        if si["task_type"] != "abstract_screening":
            return None
        if not failed and si["screening_target"] == {"runs": 2, "run": 1} and len(screening_calls) == 2:
            failed.append(si)
            return ModelStepResult("failed", error="SYNTHETIC model connection dropped")
        screening_calls.append(si)
        return None

    screening_calls: list = []
    size = 3 * ABSTRACT_BATCH
    app = app_for(tmp_path, monkeypatch, Pool(pool(size)), adapter=FakeAdapter(valid_response, fail=fail_the_second_batch_once))
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client, effort="standard")
        assert run["status"] == "paused" and run["pause_reason"] == "model_call_failed", run
        store = app.state.store
        plan = step_output(store, run_id, "abstract_stage")
        client.post(f"/api/runs/{run_id}/resume")
        view, run = wait(client, rid, run_id)
        # The model is shown short handles, so what it saw is compared by title, which handles do not touch.
        read = [sorted(c["title"] for c in si["candidates"]) for si in screening_calls]
        planned = [sorted(store.source(svid)["title"] for svid in batch) for batch in plan["batches"]]
        resumed = step_output(store, run_id, "abstract_stage")
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed"
    # The stored plan is what the resumed run read, unchanged, and every batch was read twice and only twice.
    # The batches are compared without their order: the calls go out concurrently, so the one the dropped
    # connection cost is re-sent on resume, after batches that were already in flight when the run paused.
    assert resumed["batches"] == plan["batches"]
    assert sorted(read) == sorted(batch for batch in planned for _ in range(2))


def test_a_legacy_run_paused_between_two_screening_batches_screens_every_candidate_when_it_resumes(tmp_path, monkeypatch):
    """The same list on resume in the legacy workflow too: before, a batch's worth of candidates was never screened."""
    from deixis.workflow.flow import SCREENING_BATCH

    calls, failed = [], []

    def fail_the_second_batch_once(si):
        if si["task_type"] == "screening":
            if len(calls) == 1 and not failed:
                failed.append(si)
                return ModelStepResult("failed", error="SYNTHETIC model connection dropped")
            calls.append(si)
        return None

    size = 3 * SCREENING_BATCH
    app = app_for(tmp_path, monkeypatch, Pool(pool(size)), workflow="legacy",
                  adapter=FakeAdapter(valid_response, fail=fail_the_second_batch_once))
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client, effort="standard")
        assert run["status"] == "paused"
        client.post(f"/api/runs/{run_id}/resume")
        view, run = wait(client, rid, run_id)
        sent = [c["candidate_id"] for si in calls for c in si["candidates"]]
        unscreened = [c for c in app.state.store.candidates(rid, 1) if not c["proposed"]]
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed"
    assert len(sent) == len(set(sent)) == size and not unscreened
