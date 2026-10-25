"""The abstract stage inside a real `sw` discovery run, driven through the API (slice 09, D81).

What is checked here is workflow behavior: that code classifies every record, that the model is asked twice about
what code left open and never about the same record twice, that a quote is verified against the abstract the model
was shown, that nothing is included from an abstract, that no record is dropped by a failure or a limit, and that
a `legacy` research gains none of it. Records, titles and abstracts are SYNTHETIC and from two fields, every
transport is mocked and the model is scripted: passing shows the stage behaves as the slice says, not that a real
model labels abstracts well.
"""

import json
import time

import httpx
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents.fetch import FetchResult
from deixis.providers.registry import CONNECTORS
from deixis.workflow.screen.decisions import DecisionStore
from fakes import FakeAdapter, envelope, valid_response

# Two fields: the question is a greenhouse one, and the pool holds bakery-logistics records that answer nothing.
QUESTION = "How does irrigation scheduling affect marketable yield in greenhouse tomato production?"
ON_TOPIC = "SYNTHETIC irrigation scheduling in greenhouse tomato production"
HALF = "SYNTHETIC irrigation scheduling of an open field crop"
OFF_TOPIC = "SYNTHETIC bakery delivery rounds of a small town"
ON_ABSTRACT = "We vary the irrigation scheduling of a greenhouse tomato crop and report the marketable yield."
HALF_ABSTRACT = "We vary the irrigation scheduling of an open field crop and report the water it used."
OFF_ABSTRACT = "We measure the bread delivery rounds of a small town bakery and report the distance covered."


def work(number, title=HALF, abstract=HALF_ABSTRACT, doi=None):
    inverted: dict[str, list[int]] = {}
    for position, word in enumerate((abstract or "").split()):
        inverted.setdefault(word, []).append(position)
    return {"id": f"https://openalex.org/W{number}", "doi": f"https://doi.org/{doi or f'10.1/oa.{number}'}",
            "display_name": f"{title} {number}", "publication_year": 2024, "type": "article", "authorships": [],
            "abstract_inverted_index": inverted or None}


class Pool:
    """Mocked OpenAlex answering every count probe and serving one page of records; no other provider is mocked."""

    def __init__(self, works):
        self.works = works
        self.probes, self.searches = [], []

    def __call__(self, request):
        if request.url.host != "api.openalex.org":
            return httpx.Response(404)
        params = request.url.params
        query = params.get("search.title_and_abstract") or ""
        if params.get("per_page") == "1" and params.get("select") == "id":
            self.probes.append(query)
            return httpx.Response(200, json={"meta": {"count": 1 if " AND " in query else 40}, "results": []})
        self.searches.append(query)
        return httpx.Response(200, json={"meta": {"count": len(self.works), "next_cursor": None},
                                         "results": self.works})


async def no_fetch(url):
    return FetchResult("http_error", final_url=url, http_status=404)


def app_for(tmp_path, monkeypatch, handler, workflow="sw", adapter=None, concurrency=6):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", workflow)
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_query="code",
                               model_concurrency=concurrency, fulltext_fetch="off"),
                      adapters={"fake": adapter or FakeAdapter(valid_response)},
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), fetcher=no_fetch,
                      extra_hosts=("testserver",), trusted_clients=("testclient",))


def client_of(app):
    client = TestClient(app)
    client.__enter__()
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    return client


def wait(client, rid, run_id):
    deadline = time.time() + 30
    while time.time() < deadline:
        view = client.get(f"/api/researches/{rid}").json()
        run = next(r for r in view["runs"] if r["id"] == run_id)
        if run["status"] in ("completed", "failed", "paused"):
            return view, run
        time.sleep(0.05)
    raise AssertionError("the run did not settle")


def discover(client, question=QUESTION, effort="quick", **body):
    payload = {"question": question, "model_connection": "fake", "requested_model": "fake-model", "effort": effort,
               **body}
    rid = client.post("/api/researches", json=payload).json()["research"]["id"]
    return (rid, *rerun(client, rid))


def rerun(client, rid):
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    return (run_id, *wait(client, rid, run_id))


def step_output(store, run_id, key):
    from batch_outputs import stage_output
    return stage_output(store, run_id, key)


def records_of(store, rid):
    return {row[1].rsplit("/", 1)[-1]: row[0] for row in store.conn.execute(
        "SELECT m.source_version_id, m.value FROM identifier_mappings m JOIN candidates c"
        " ON c.source_version_id = m.source_version_id WHERE c.research_id = ? AND m.scheme = 'openalex'", (rid,))}


def codes_of(store, rid):
    """Every record's open abstract-stage reason code, by its OpenAlex identifier."""
    decisions = DecisionStore(store)
    return {key: (decisions.current(rid, svid, "abstract") or {}).get("reason_code")
            for key, svid in records_of(store, rid).items()}


def selections_of(store, rid):
    by_svid = {svid: key for key, svid in records_of(store, rid).items()}
    return {by_svid[row["source_version_id"]]: (row["state"], row["origin"]) for row in store.conn.execute(
        "SELECT source_version_id, state, origin FROM selections WHERE research_id = ?", (rid,))
        if row["source_version_id"] in by_svid}


def shown_titles(store, run_id):
    """Every title this run really put in front of the model, from the stored step inputs."""
    return [c["title"] for row in store.conn.execute(
        "SELECT i.payload_json FROM step_inputs i JOIN run_steps s ON s.id = i.step_id"
        " WHERE s.run_id = ? AND s.kind = 'model:abstract_screening' ORDER BY s.operation_key, i.rowid", (run_id,))
        for c in json.loads(row[0])["candidates"]]


def proposals_of(store, rid, svid):
    return [(row["run_no"], row["label"], bool(row["quote_verified"])) for row in store.conn.execute(
        "SELECT run_no, label, quote_verified FROM model_proposals WHERE research_id = ? AND source_version_id = ?"
        " AND stage = 'abstract' ORDER BY run_no", (rid, svid))]


def responder(label="candidate", quote=None, only=None):
    """A scripted model that gives every record it is shown one label and one quote from its own abstract."""
    def respond(si):
        if si["task_type"] != "abstract_screening":
            return valid_response(si)
        return json.dumps(envelope(si, "deixis.abstract_screening.v1") | {"records": [
            {"candidate_id": c["candidate_id"],
             "label": label if only is None or only in c["title"] else "candidate",
             "quote": quote if quote is not None else " ".join((c["abstract"] or "").split())[:60],
             "rationale": "SYNTHETIC one-sentence rationale."} for c in si["candidates"]]})
    return respond


# ---- nothing is included, and the model no longer writes a selection ---------------------------

def test_no_selection_becomes_included_and_the_run_opens_no_screening_step(tmp_path, monkeypatch):
    """SW1.2 and K2: until slice 12 an sw research includes nothing by itself; code writes what is written."""
    app = app_for(tmp_path, monkeypatch, Pool([work(n) for n in range(4)]))
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        selections = selections_of(store, rid)
        kinds = {s["kind"] for s in store.run_steps(run_id)}
        codes = codes_of(store, rid)
        funnel = client.get(f"/api/researches/{rid}").json()["counts"]["funnel"]
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed"
    # Every candidate was passed after a model read its abstract: none counts as passed on its title alone.
    assert (funnel["abstracts_read"], funnel["candidates"], funnel["candidates_by_title"]) == (4, 4, 0)
    assert set(selections.values()) == {("pending", "code_rule")}
    assert not [state for state, _ in selections.values() if state == "included"]
    assert "model:screening" not in kinds and "model:abstract_screening" in kinds
    assert set(codes.values()) == {"runs_agree_candidate"}


# ---- the read limit leaves the rest unread ------------------------------------------------------


def test_a_second_run_of_a_fully_read_research_asks_nothing_and_writes_no_row(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, Pool([work(n) for n in range(4)]))
    client = client_of(app)
    try:
        rid, first_run, view, run = discover(client)
        store = app.state.store
        before = store.conn.execute("SELECT COUNT(*) FROM stage_decisions WHERE research_id = ?", (rid,)).fetchone()[0]
        second_run, view, run = rerun(client, rid)
        after = store.conn.execute("SELECT COUNT(*) FROM stage_decisions WHERE research_id = ?", (rid,)).fetchone()[0]
        asked = shown_titles(store, second_run)
        plan = step_output(store, second_run, "abstract_stage")
    finally:
        client.__exit__(None, None, None)
    assert before == after == 4 and asked == [] and plan["works_needing_model"] == 0


# ---- what the two runs mean --------------------------------------------------------------------

def test_an_invented_quote_keeps_the_record_as_a_candidate(tmp_path, monkeypatch):
    """SW1.1: the quote must be the shown abstract's own words; a label without one does not drop the record."""
    app = app_for(tmp_path, monkeypatch, Pool([work(1, OFF_TOPIC, HALF_ABSTRACT)]),
                  adapter=FakeAdapter(responder("out_of_scope", quote="SYNTHETIC: a sentence no abstract holds.")))
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        codes, selections = codes_of(store, rid), selections_of(store, rid)
        proposals = proposals_of(store, rid, records_of(store, rid)["W1"])
    finally:
        client.__exit__(None, None, None)
    assert codes["W1"] == "quote_not_found_kept_as_candidate"
    assert selections["W1"] == ("pending", "code_rule")
    assert proposals == [(1, "out_of_scope", False), (2, "out_of_scope", False)]


# ---- the user's decision, and a revised question -----------------------------------------------

def test_a_record_the_user_excluded_keeps_the_user_s_own_selection(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, Pool([work(1), work(2)]))
    client = client_of(app)
    try:
        rid, first_run, view, run = discover(client)
        store = app.state.store
        svid = records_of(store, rid)["W1"]
        source = next(s for s in view["sources"] if s["source_version_id"] == svid)
        answer = client.patch(f"/api/researches/{rid}/selections/{svid}",
                              json={"state": "excluded", "expected_version": source["selection"]["version"],
                                    "reason": "SYNTHETIC: the user's own call"})
        assert answer.status_code == 200 and answer.json()["origin"] == "user"
        second_run, view, run = rerun(client, rid)
        selections, codes = selections_of(store, rid), codes_of(store, rid)
        asked = shown_titles(store, second_run)
    finally:
        client.__exit__(None, None, None)
    # The user's selection stands and the record is not read again: a work the user decided leaves the plan.
    assert selections["W1"] == ("excluded", "user")
    assert codes["W1"] == "runs_agree_candidate"  # the decision row the first run wrote is untouched
    assert not any(title.endswith(" 1") for title in asked)


# ---- slice 13d: the reads behind the stage are batched and the rows it writes do not move ---------

ARTIFACT_DOI = "10.5281/zenodo.900001"
SURVEY_TITLE = "SYNTHETIC survey of irrigation scheduling in greenhouse tomato production"
ARTIFACT_TITLE = "SYNTHETIC dataset for irrigation scheduling in greenhouse tomato production"
REVISED = "How does irrigation scheduling affect marketable yield in vertical farms?"


def names_of(store, rid):
    """A stable name for every record of the research: its OpenAlex identifier, and for a version opened for a
    lookup, the identifier of its work's record with the version label."""
    openalex = records_of(store, rid)
    of_work = {store.source(svid)["work_id"]: key for key, svid in openalex.items()}
    by_svid = {svid: key for key, svid in openalex.items()}
    return {row["id"]: by_svid.get(row["id"], f"{of_work.get(row['work_id'], '?')}:{row['version_label']}")
            for row in store.conn.execute(
                "SELECT v.id, v.work_id, v.version_label FROM corpus_memberships m"
                " JOIN source_versions v ON v.id = m.source_version_id WHERE m.research_id = ?", (rid,))}


def stage_snapshot(store, rid, run_id):
    """The stage's output and every decision and selection row the research holds, by record name.

    Identifiers and timestamps are left out: they differ between two runs of the same fixture anyway. What must
    not move is which record carries which decision and selection, under which question revision, and which of
    them is closed. The rows are sorted: the order two batches of the abstract stage close in is the order their
    model calls came back in, which is not this stage's to decide (D81).
    """

    def ordered(rows):
        return sorted(rows, key=lambda row: tuple("" if value is None else str(value) for value in row))

    names = names_of(store, rid)
    decisions = [(names.get(row["source_version_id"]), row["stage"], row["outcome"], row["reason_code"],
                  row["decided_by"], row["scope_revision"], row["superseded_at"] is not None)
                 for row in store.conn.execute(
                     "SELECT * FROM stage_decisions WHERE research_id = ? ORDER BY created_at, rowid", (rid,))]
    selections = [(names.get(row["source_version_id"]), row["state"], row["origin"], row["version"])
                  for row in store.conn.execute(
                      "SELECT * FROM selections WHERE research_id = ? ORDER BY source_version_id", (rid,))]
    history = [(names.get(row["source_version_id"]), row["old_state"], row["new_state"], row["origin"], row["reason"])
               for row in store.conn.execute(
                   "SELECT * FROM selection_history WHERE research_id = ? ORDER BY id", (rid,))]
    output = step_output(store, run_id, "abstract_stage")
    output["batches"] = [[names.get(svid) for svid in batch] for batch in output["batches"]]
    return {"output": output,
            "decisions": ordered(decisions), "selections": ordered(selections), "history": ordered(history),
            "selection_revision": store.selection_revision(rid)}


# What the stage wrote before its reads were batched, captured on the unchanged code (slice 13d, Task 2).
STAGE_ROWS_BEFORE_13D = {
    "output": {"decisions": {"artifact_of_paper": 1, "both_blocks_missing": 1}, "limit": 40, "batch": 20, "runs": 2,
               "batches": [["W1", "W2"]], "not_read": 0, "works_needing_model": 2},
    "decisions": [
        ("W1", "abstract", "candidate", "blocks_in_title", "code", 1, True),
        ("W1", "abstract", "candidate", "runs_agree_candidate", "model_agreement", 2, False),
        ("W2", "abstract", "candidate", "runs_agree_candidate", "model_agreement", 1, True),
        ("W2", "abstract", "candidate", "runs_agree_candidate", "model_agreement", 2, False),
        ("W3", "abstract", "out_of_scope", "both_blocks_missing", "code", 1, True),
        ("W3", "abstract", "out_of_scope", "both_blocks_missing", "code", 2, False),
        ("W4", "abstract", "unresolved", "survey_title_word", "code", 1, False),
        ("W5", "abstract", "candidate", "blocks_in_title", "code", 1, True),
        ("W5", "abstract", "out_of_scope", "artifact_of_paper", "code", 2, False),
        ("W6", "abstract", "candidate", "runs_agree_candidate", "model_agreement", 1, False),
        ("W6", "fulltext", "include", "human_include", "human", 1, False),
    ],
    "selections": [
        ("W1", "pending", "code_rule", 2), ("W2", "pending", "code_rule", 2),
        ("W2:acceptedVersion", "pending", "default", 1), ("W3", "excluded", "code_rule", 2),
        ("W4", "pending", "default", 1), ("W5", "excluded", "code_rule", 3), ("W6", "included", "user", 3),
    ],
    "history": [
        ("W1", None, "pending", "default", None),
        ("W1", "pending", "pending", "code_rule", "blocks_in_title"),
        ("W2", None, "pending", "default", None),
        ("W2", "pending", "pending", "code_rule", "runs_agree_candidate"),
        ("W2:acceptedVersion", None, "pending", "default", None),
        ("W3", None, "pending", "default", None),
        ("W3", "pending", "excluded", "code_rule", "both_blocks_missing"),
        ("W4", None, "pending", "default", None),
        ("W5", None, "pending", "default", None),
        ("W5", "pending", "excluded", "code_rule", "artifact_of_paper"),
        ("W5", "pending", "pending", "code_rule", "blocks_in_title"),
        ("W6", None, "pending", "default", None),
        ("W6", "pending", "included", "user", "SYNTHETIC: the user's own call"),
        ("W6", "pending", "pending", "code_rule", "runs_agree_candidate"),
    ],
    "selection_revision": 1,
}


def test_the_stage_writes_the_same_rows_when_its_reads_are_batched(tmp_path, monkeypatch):
    """Slice 13d: the stage reads the research in a few statements instead of a few per record, and writes its
    decisions and selections in one transaction. Nothing it writes may move.

    The pool holds the cases whose reads the batch has to keep apart: works with several versions, an artifact
    attached to a paper by an open link, a survey title word, a record the user decided, and decisions a revised
    question left stale. SYNTHETIC records from two fields; passing shows the rows are the ones the unbatched
    stage wrote, not that the screening is right.
    """
    from deixis.storage import db as storage_db

    pool = Pool([work(1, ON_TOPIC, ON_ABSTRACT), work(2), work(3, OFF_TOPIC, OFF_ABSTRACT),
                 work(4, SURVEY_TITLE, ON_ABSTRACT), work(5, ARTIFACT_TITLE, ON_ABSTRACT, doi=ARTIFACT_DOI),
                 work(6)])
    app = app_for(tmp_path, monkeypatch, pool)
    client = client_of(app)
    try:
        rid, first_run, view, run = discover(client)
        store = app.state.store
        svids = records_of(store, rid)
        # W1 and W5 pass on their title alone; the funnel tells them apart from the works a model read.
        assert view["counts"]["funnel"]["candidates_by_title"] == 2
        # A second version of one work, so the stage reads a work with more than one record.
        store.open_lookup_version(rid, svids["W2"], "acceptedVersion", None)
        # The artifact is this paper's data, by a link nobody undid.
        with storage_db.transaction(store.conn):
            store.conn.execute(
                "INSERT INTO record_links (id, source_version_id, other_source_version_id, link_kind, rule, source,"
                " author_agreement, merged, created_at) VALUES ('lnk_synthetic', ?, ?, 'artifact_of', 'title_prefix',"
                " 'text', 'agree', 0, '2026-09-22T00:00:00.000+00:00')",
                tuple(sorted((svids["W5"], svids["W1"]))))
        # A decision only the user may take back, and a selection the user set: neither is written over.
        DecisionStore(store).record(rid, svids["W6"], "human_include")
        source = next(s for s in view["sources"] if s["source_version_id"] == svids["W6"])
        client.patch(f"/api/researches/{rid}/selections/{svids['W6']}",
                     json={"state": "included", "expected_version": source["selection"]["version"],
                           "reason": "SYNTHETIC: the user's own call"})
        # A revised question: every decision made under the first one is now stale and is written again.
        client.post(f"/api/researches/{rid}/scope",
                    json={"question": REVISED, "expected_version": client.get(f"/api/researches/{rid}")
                          .json()["research"]["version"]})
        second_run, view, run = rerun(client, rid)
        snapshot = stage_snapshot(store, rid, second_run)
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed"
    assert snapshot == STAGE_ROWS_BEFORE_13D
