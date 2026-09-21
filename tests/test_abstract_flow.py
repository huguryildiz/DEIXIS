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
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents.fetch import FetchResult
from deixis.domain.rules import ABSTRACT_BATCH, ABSTRACT_READ_LIMIT
from deixis.models.adapter import ModelStepResult
from deixis.providers.registry import CONNECTORS
from deixis.workflow.decisions import DecisionStore
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


def app_for(tmp_path, monkeypatch, handler, workflow="sw", adapter=None):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", workflow)
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_workflow=workflow,
                               protocol_approval="as_proposed"),
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
    row = store.conn.execute("SELECT output_json FROM run_steps WHERE run_id = ? AND operation_key = ?",
                             (run_id, key)).fetchone()
    return None if row is None or row[0] is None else json.loads(row[0])


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
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed"
    assert set(selections.values()) == {("pending", "code_rule")}
    assert not [state for state, _ in selections.values() if state == "included"]
    assert "model:screening" not in kinds and "model:abstract_screening" in kinds
    assert set(codes.values()) == {"runs_agree_candidate"}


def test_an_agreed_out_of_scope_excludes_by_code_rule_and_the_record_stays_in_the_list(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, Pool([work(1), work(2)]),
                  adapter=FakeAdapter(responder("out_of_scope")))
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        codes, selections = codes_of(store, rid), selections_of(store, rid)
        candidates = len(store.candidates(rid, 1))
    finally:
        client.__exit__(None, None, None)
    # Code left both records open (each title holds one concept block) and the two model runs agreed on them.
    assert codes == {"W1": "runs_agree_out_of_scope", "W2": "runs_agree_out_of_scope"}
    assert set(selections.values()) == {("excluded", "code_rule")}
    assert candidates == 2  # an excluded record is not deleted and not hidden


# ---- what code settles without asking anyone ---------------------------------------------------

def test_two_blocks_in_the_title_are_a_candidate_the_model_is_never_shown(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, Pool([work(1, ON_TOPIC, ON_ABSTRACT), work(2)]))
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        codes, titles = codes_of(store, rid), shown_titles(store, run_id)
        plan = step_output(store, run_id, "abstract_stage")
    finally:
        client.__exit__(None, None, None)
    assert codes["W1"] == "blocks_in_title" and plan["decisions"]["blocks_in_title"] == 1
    assert not any(title.startswith(ON_TOPIC) for title in titles)
    assert [title for title in titles if title.startswith(HALF)]


def test_neither_block_anywhere_is_excluded_by_code_and_the_record_is_still_a_candidate_row(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, Pool([work(1, OFF_TOPIC, OFF_ABSTRACT), work(2)]))
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        codes, selections, titles = codes_of(store, rid), selections_of(store, rid), shown_titles(store, run_id)
        candidates = {c["source_version_id"] for c in store.candidates(rid, 1)}
    finally:
        client.__exit__(None, None, None)
    assert codes["W1"] == "both_blocks_missing" and selections["W1"] == ("excluded", "code_rule")
    assert not any(title.startswith(OFF_TOPIC) for title in titles)  # code closed it; no model call was spent
    assert len(candidates) == 2


def test_a_record_without_an_abstract_is_never_out_of_scope_and_is_not_read(tmp_path, monkeypatch):
    """SW5.5: nobody could judge it, so nothing may drop it; slice 05's code stands."""
    app = app_for(tmp_path, monkeypatch, Pool([work(1, OFF_TOPIC, abstract=None), work(2)]))
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        codes, selections, titles = codes_of(store, rid), selections_of(store, rid), shown_titles(store, run_id)
    finally:
        client.__exit__(None, None, None)
    assert codes["W1"] in ("no_abstract", "abstract_not_found") and selections["W1"][0] == "pending"
    assert not any(title.startswith(OFF_TOPIC) for title in titles)


# ---- the read limit leaves the rest unread, and the next run reads on --------------------------

def test_a_work_outside_the_read_limit_is_unread_and_pending_not_dropped(tmp_path, monkeypatch):
    size = ABSTRACT_READ_LIMIT["quick"] + 6
    app = app_for(tmp_path, monkeypatch, Pool([work(n) for n in range(size)]))
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        plan = step_output(store, run_id, "abstract_stage")
        codes, selections = codes_of(store, rid), selections_of(store, rid)
        order = DecisionStore(store).latest_ranking(rid, 1)
        unread = {key for key, code in codes.items() if code == "abstract_not_read"}
        by_svid = {svid: key for key, svid in records_of(store, rid).items()}
    finally:
        client.__exit__(None, None, None)
    assert plan["limit"] == ABSTRACT_READ_LIMIT["quick"] and plan["not_read"] == 6
    assert len(unread) == 6 and {by_svid[svid] for svid in order[-6:]} == unread
    assert {selections[key] for key in unread} == {("pending", "code_rule")}
    assert len(store_candidates := codes) == size  # nothing was deleted


def test_a_second_discovery_run_reads_on_from_where_the_first_stopped(tmp_path, monkeypatch):
    """K3: the works the first run read are not asked about again; the next ones in the order are."""
    size = ABSTRACT_READ_LIMIT["quick"] + 6
    app = app_for(tmp_path, monkeypatch, Pool([work(n) for n in range(size)]))
    client = client_of(app)
    try:
        rid, first_run, view, run = discover(client)
        store = app.state.store
        first_titles = shown_titles(store, first_run)
        first_codes = codes_of(store, rid)
        second_run, view, run = rerun(client, rid)
        second_titles = shown_titles(store, second_run)
        second_plan = step_output(store, second_run, "abstract_stage")
        second_codes = codes_of(store, rid)
        rows = store.conn.execute("SELECT COUNT(*) FROM stage_decisions WHERE research_id = ?", (rid,)).fetchone()[0]
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed"
    unread = {key for key, code in first_codes.items() if code == "abstract_not_read"}
    assert len(unread) == 6 and second_plan["works_needing_model"] == 6
    # Not one record was put to the model twice: the second run read the six the first left, and only those.
    assert set(second_titles).isdisjoint(set(first_titles))
    assert len(set(second_titles)) == 6 and len(second_titles) == 12  # six works, each read by two runs
    assert not [key for key, code in second_codes.items() if code == "abstract_not_read"]
    # The second run rewrote nothing it had already decided: one row per record, plus the six it re-decided.
    assert rows == len(first_codes) + 6


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


# ---- pause, resume and a failed batch ----------------------------------------------------------

def test_a_run_resumed_between_two_batches_reads_the_stored_plan_and_skips_no_work(tmp_path, monkeypatch):
    """Slice 07's review: a resumed run must find the same batches, or the later places are never read."""
    failed = []

    def fail_the_second_batch_once(si):
        if si["task_type"] == "abstract_screening" and not failed and len(sent) == 2:
            failed.append(si)
            return ModelStepResult("failed", error="SYNTHETIC model connection dropped")
        if si["task_type"] == "abstract_screening":
            sent.append(si)
        return None

    sent: list = []
    size = 2 * ABSTRACT_BATCH + 4
    app = app_for(tmp_path, monkeypatch, Pool([work(n) for n in range(size)]),
                  adapter=FakeAdapter(valid_response, fail=fail_the_second_batch_once))
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client, effort="standard")
        assert (run["status"], run["pause_reason"]) == ("paused", "model_call_failed"), run
        store = app.state.store
        plan = step_output(store, run_id, "abstract_stage")
        client.post(f"/api/runs/{run_id}/resume")
        view, run = wait(client, rid, run_id)
        resumed = step_output(store, run_id, "abstract_stage")
        titles = shown_titles(store, run_id)
        codes = codes_of(store, rid)
        planned = {store.source(svid)["title"] for batch in plan["batches"] for svid in batch}
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed"
    assert resumed["batches"] == plan["batches"] and len(plan["batches"]) == 3
    # Every planned record reached the model and no other did; the retried call re-sent one batch, which is what a
    # failed connection has always cost, and it decided nothing twice.
    assert set(titles) == planned and len(titles) == 2 * len(planned) + ABSTRACT_BATCH
    assert set(codes.values()) == {"runs_agree_candidate"}


def test_an_invalid_batch_loses_no_record_and_is_not_asked_again_on_resume(tmp_path, monkeypatch):
    """An invalid output is not repaired and does not stop the run: its records stay unread for a later run."""
    def invalid_first_batch(si):
        if si["task_type"] != "abstract_screening":
            return valid_response(si)
        if si["screening_target"]["run"] == 1 and si["step_id"] not in seen:
            seen.add(si["step_id"])
            if len(seen) == 1:
                return json.dumps(envelope(si, "deixis.abstract_screening.v1") | {"records": [
                    {"candidate_id": "cnd_C9999999", "label": "nonsense", "quote": "", "rationale": ""}]})
        return responder()(si)

    seen: set = set()
    size = ABSTRACT_BATCH + 4
    app = app_for(tmp_path, monkeypatch, Pool([work(n) for n in range(size)]),
                  adapter=FakeAdapter(invalid_first_batch))
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client, effort="standard")
        store = app.state.store
        plan = step_output(store, run_id, "abstract_stage")
        codes = codes_of(store, rid)
        statuses = {s["operation_key"]: s["status"] for s in store.run_steps(run_id)
                    if s["kind"] == "model:abstract_screening"}
        calls_before = len([s for s in store.run_steps(run_id) if s["kind"] == "model:abstract_screening"])
        second_run, view, resumed = rerun(client, rid)
        again = {s["operation_key"]: s["status"] for s in store.run_steps(run_id)
                 if s["kind"] == "model:abstract_screening"}
        later = codes_of(store, rid)
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    assert statuses["abstract_screening:0:1"] == "failed" and statuses["abstract_screening:1:1"] == "succeeded"
    # The failed batch's records are unread, not dropped; the other batch decided normally.
    unread = {key for key, code in codes.items() if code == "abstract_not_proposed"}
    assert len(unread) == len(plan["batches"][0]) and calls_before == 4
    assert {code for key, code in codes.items() if key not in unread} == {"runs_agree_candidate"}
    # Resuming does not call the failed step again, and the next discovery run reads those records.
    assert again == statuses
    assert not [key for key, code in later.items() if code == "abstract_not_proposed"]


def test_a_dead_connection_pauses_the_run_with_the_code_decisions_already_written(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, Pool([work(1, OFF_TOPIC, OFF_ABSTRACT), work(2)]),
                  adapter=FakeAdapter(fail=lambda si: ModelStepResult("failed", error="SYNTHETIC down")))
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        codes = codes_of(store, rid)
        plan = step_output(store, run_id, "abstract_stage")
    finally:
        client.__exit__(None, None, None)
    assert (run["status"], run["pause_reason"]) == ("paused", "model_call_failed"), run
    assert codes["W1"] == "both_blocks_missing" and plan["works_needing_model"] == 1


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


def test_two_runs_that_disagree_keep_the_record_as_a_candidate(tmp_path, monkeypatch):
    """SW11.4: the cheap mistake is one more full text read, so disagreement keeps the record."""
    def disagree(si):
        if si["task_type"] != "abstract_screening":
            return valid_response(si)
        label = "candidate" if si["screening_target"]["run"] == 1 else "out_of_scope"
        return json.dumps(envelope(si, "deixis.abstract_screening.v1") | {"records": [
            {"candidate_id": c["candidate_id"], "label": label,
             "quote": " ".join((c["abstract"] or "").split())[:60], "rationale": "SYNTHETIC rationale."}
            for c in si["candidates"]]})

    app = app_for(tmp_path, monkeypatch, Pool([work(1)]), adapter=FakeAdapter(disagree))
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        codes, selections = codes_of(store, rid), selections_of(store, rid)
        proposals = proposals_of(store, rid, records_of(store, rid)["W1"])
    finally:
        client.__exit__(None, None, None)
    assert codes["W1"] == "runs_disagree_kept_as_candidate"
    assert selections["W1"] == ("pending", "code_rule")
    assert proposals == [(1, "candidate", True), (2, "out_of_scope", True)]


def test_two_unresolved_runs_leave_the_work_for_the_full_text(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, Pool([work(1)]), adapter=FakeAdapter(responder("unresolved", quote="")))
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        codes = codes_of(app.state.store, rid)
    finally:
        client.__exit__(None, None, None)
    assert codes["W1"] == "runs_agree_unresolved"


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


def test_a_revised_question_makes_the_old_decision_stale_and_the_record_is_read_again(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, Pool([work(1)]))
    client = client_of(app)
    try:
        rid, first_run, view, run = discover(client)
        store = app.state.store
        first = shown_titles(store, first_run)
        # The revision keeps the task block and changes the setting, so code still leaves the record open for the
        # model rather than closing it on either branch.
        client.post(f"/api/researches/{rid}/scope", json={
            "question": "How does irrigation scheduling affect marketable yield in vertical farms?",
            "expected_version": view["research"]["version"]})
        second_run, view, run = rerun(client, rid)
        second = shown_titles(store, second_run)
        history = store.conn.execute(
            "SELECT COUNT(*) FROM stage_decisions WHERE research_id = ?", (rid,)).fetchone()[0]
    finally:
        client.__exit__(None, None, None)
    assert first and second  # the record was read under the first question and again under the second
    assert history >= 2  # the earlier decision is closed, never deleted


# ---- legacy is untouched ------------------------------------------------------------------------

def test_a_legacy_research_screens_as_it_always_did_and_opens_no_abstract_stage(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, Pool([work(1, ON_TOPIC, ON_ABSTRACT), work(2)]), workflow="legacy")
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        keys = [s["operation_key"] for s in store.run_steps(run_id)]
        selections = selections_of(store, rid)
        decisions = store.conn.execute(
            "SELECT COUNT(*) FROM stage_decisions WHERE research_id = ?", (rid,)).fetchone()[0]
        body = json.loads(store.conn.execute(
            "SELECT body_json FROM protocol_records WHERE research_id = ?", (rid,)).fetchone()[0])
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed"
    assert "screening" in keys and "abstract_stage" not in keys
    # The model's include proposal still reaches the selection in a legacy research, and no decision row is written.
    assert set(selections.values()) == {("included", "model_proposal")} and decisions == 0
    assert "abstract_screening" not in body["thresholds"] and body["thresholds"]["screening_batch"] == 40


def test_the_sw_protocol_names_the_read_limit_of_its_own_effort(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, Pool([work(1)]))
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client, effort="standard")
        body = json.loads(app.state.store.conn.execute(
            "SELECT body_json FROM protocol_records WHERE research_id = ?", (rid,)).fetchone()[0])
    finally:
        client.__exit__(None, None, None)
    assert body["thresholds"]["abstract_screening"] == {"read_limit": ABSTRACT_READ_LIMIT["standard"],
                                                        "batch": ABSTRACT_BATCH, "runs": 2, "quote_min_chars": 12}


@pytest.mark.parametrize("effort, calls", [("quick", 4), ("standard", 10), ("detailed", 30)])
def test_the_run_budget_holds_the_abstract_stage_s_calls_on_top_of_the_preset(tmp_path, monkeypatch, effort, calls):
    from deixis.domain.rules import CRITERION_CALLS, TEST_EFFORT_BUDGETS

    app = app_for(tmp_path, monkeypatch, Pool([work(1)]))
    client = client_of(app)
    try:
        rid = client.post("/api/researches", json={"question": QUESTION, "model_connection": "fake",
                                                   "requested_model": "fake-model", "effort": effort}).json()["research"]["id"]
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        wait(client, rid, run["id"])
    finally:
        client.__exit__(None, None, None)
    preset = TEST_EFFORT_BUDGETS[effort].max_model_calls
    assert run["budget"]["max_model_calls"] == preset + CRITERION_CALLS + calls
