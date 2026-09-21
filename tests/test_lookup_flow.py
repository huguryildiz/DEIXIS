"""An `sw` discovery run that asks a second source for the abstracts it is missing, then labels what it found.

Records, titles and provider answers are SYNTHETIC and from two fields; the transport is mocked and the model is
scripted. Passing shows workflow behavior — who is asked, what is stored, what a resumed run repeats and which
records reach the screening model — not how often a second source really holds a missing abstract, and not that the
survey rule is right about real literature. A `legacy` research is exercised too, because nothing about it may change.
"""

import json
import time
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents.fetch import FetchResult
from deixis.models.adapter import ModelStepResult
from deixis.providers import common
from deixis.providers.registry import CONNECTORS
from deixis.workflow.decisions import DecisionStore
from fakes import FakeAdapter, envelope, valid_response

QUESTION = "What is the effect of packet size on energy consumption in wireless sensor networks?"
# A second field, so the fixtures are not one topic: the survey title is molecular, the rest is wireless sensing.
SURVEY_TITLE = "SYNTHETIC survey of molecular release scheduling"
PLAIN_TITLE = "SYNTHETIC relay scheduling in a sensor node"
ABSTRACT = "We measure SYNTHETIC packet sizes and report the energy each one costs a relay node."
SURVEY_ABSTRACT = "This review collects SYNTHETIC scheduling results and compares the energy figures they report."
PAGE = 20


@pytest.fixture(autouse=True)
def no_gate(monkeypatch):
    """Open the Semantic Scholar gate so a test does not wait two seconds for a mocked answer (D67).

    Only the gate: `asyncio.sleep` itself is left alone, because the worker loop runs on it. Every SYNTHETIC 429
    below names `retry-after: 0`, so the bounded backoff costs nothing either.
    """
    monkeypatch.setattr(common.SEMANTIC_SCHOLAR_PACER, "interval_seconds", 0.0)


def DeadAdapter():
    return FakeAdapter(fail=lambda si: ModelStepResult("failed", error="SYNTHETIC model connection is down"))


def excluding(step_input):
    """A scripted model that puts every record it is shown out of scope.

    It is the sharpest test of SW5.5: a record this model never sees cannot be excluded by it, and a record without
    an abstract must never be excluded by anything. Since slice 09 the model's word is a proposal only; the code
    stage turns two agreeing runs into the decision, so the quote is copied from the abstract it was shown.
    """
    if step_input["task_type"] == "abstract_screening":
        return json.dumps(envelope(step_input, "deixis.abstract_screening.v1") | {"records": [
            {"candidate_id": c["candidate_id"], "label": "out_of_scope",
             "quote": " ".join((c["abstract"] or "").split())[:60],
             "rationale": "SYNTHETIC: another setting."} for c in step_input["candidates"]]})
    if step_input["task_type"] != "screening":
        return valid_response(step_input)
    return json.dumps(envelope(step_input, "deixis.screening_proposal.v1") | {
        "decisions": [{"candidate_id": c["candidate_id"], "proposal": "exclude", "reason": "SYNTHETIC exclude",
                       "evidence_basis": "title_and_abstract"} for c in step_input["candidates"]],
        "notes": "SYNTHETIC screening notes.",
    })


def ExcludingAdapter():
    return FakeAdapter(responder=excluding)


def work(number, title=PLAIN_TITLE, abstract=None, doi=None, references=None):
    record = {"id": f"https://openalex.org/W{number}", "doi": f"https://doi.org/{doi or f'10.1/oa.{number}'}",
              "display_name": f"{title} {number}", "publication_year": 2024, "type": "article", "authorships": [],
              "abstract_inverted_index": None}
    if abstract:
        record["abstract_inverted_index"] = {word: [i] for i, word in enumerate(abstract.split())}
    if references is not None:
        record["referenced_works_count"] = references
    return record


class Sources:
    """OpenAlex serving one page of works, Semantic Scholar answering a batch, Crossref answering single DOIs.

    Every request is recorded, so a resumed run can be asked what it sent again. `s2` and `crossref` map a DOI to
    the answer that source gives for it; a DOI neither names is `not_found`.
    """

    def __init__(self, works, s2=None, crossref=None, s2_status=200, crossref_status=200):
        self.works, self.s2, self.crossref = works, s2 or {}, crossref or {}
        self.s2_status, self.crossref_status = s2_status, crossref_status
        self.pages, self.batches, self.lookups, self.probes = [], [], [], []

    def __call__(self, request):
        host = request.url.host
        params = request.url.params
        if host == "api.openalex.org":
            if params.get("per_page") == "1" and params.get("select") == "id":
                self.probes.append(params.get("search.title_and_abstract"))
                return httpx.Response(200, json={"meta": {"count": 8}, "results": []})
            self.pages.append(params.get("select"))
            return httpx.Response(200, json={"meta": {"count": len(self.works), "next_cursor": None},
                                             "results": self.works})
        if host == "api.semanticscholar.org":
            if not request.url.path.endswith("/batch"):
                return httpx.Response(200, json={"total": 0, "data": []})  # every record here comes from OpenAlex
            ids = json.loads(request.content)["ids"]
            self.batches.append(ids)
            if self.s2_status != 200:
                return httpx.Response(self.s2_status, text="SYNTHETIC rate limit", headers={"retry-after": "0"})
            return httpx.Response(200, json=[self.s2.get(_doi_of(paper_id)) for paper_id in ids])
        if host == "api.crossref.org":
            if "rows" in params:
                return httpx.Response(200, json={"message": {"total-results": 0, "items": []}})
            doi = request.url.raw_path.decode().split("?")[0][len("/works/"):].replace("%2F", "/").lower()
            self.lookups.append(doi)
            if self.crossref_status != 200:
                return httpx.Response(self.crossref_status, text="SYNTHETIC outage", headers={"retry-after": "0"})
            if doi not in self.crossref:
                return httpx.Response(404, text="Resource not found.")
            return httpx.Response(200, json={"status": "ok", "message": {"DOI": doi, **self.crossref[doi]}})
        return httpx.Response(404)


def _doi_of(paper_id):
    return paper_id.split(":", 1)[1].lower()


def paper(abstract=None, doi=None, references=None, paper_id="s2abc"):
    return {"paperId": paper_id, "externalIds": {"DOI": doi} if doi else {}, "abstract": abstract,
            "referenceCount": references}


async def no_fetch(url):
    return FetchResult("http_error", final_url=url, http_status=404)


def app_for(tmp_path, monkeypatch, handler, workflow="sw", adapter=None):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.setitem(CONNECTORS, "openalex", replace(CONNECTORS["openalex"], max_results=PAGE))
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", workflow)
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_workflow=workflow,
                               protocol_approval="as_proposed"),
                      adapters={"fake": adapter or DeadAdapter()},
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


def discover(client, question=QUESTION, **body):
    payload = {"question": question, "model_connection": "fake", "requested_model": "fake-model", "effort": "quick",
               "providers": ["openalex", "semantic_scholar", "crossref"], **body}
    rid = client.post("/api/researches", json=payload).json()["research"]["id"]
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    return rid, run_id, *wait(client, rid, run_id)


def step_output(store, run_id, key):
    row = store.conn.execute("SELECT output_json FROM run_steps WHERE run_id = ? AND operation_key = ?",
                             (run_id, key)).fetchone()
    return None if row is None or row[0] is None else json.loads(row[0])


def records_of(store, rid):
    """Every candidate of the research by its OpenAlex identifier."""
    return {row[1]: row[0] for row in store.conn.execute(
        "SELECT m.source_version_id, m.value FROM identifier_mappings m JOIN candidates c"
        " ON c.source_version_id = m.source_version_id WHERE c.research_id = ? AND m.scheme = 'openalex'", (rid,))}


def abstract_of(store, svid):
    row = store.conn.execute(
        "SELECT text, abstract_origin, payload_ref FROM passages WHERE source_version_id = ? AND kind = 'abstract'",
        (svid,)).fetchone()
    return None if row is None else dict(row)


def decision_of(store, rid, svid):
    return DecisionStore(store).current(rid, svid, "abstract")


def selection_of(store, rid, svid):
    row = store.conn.execute("SELECT state, origin, version FROM selections WHERE research_id = ?"
                             " AND source_version_id = ?", (rid, svid)).fetchone()
    return None if row is None else dict(row)


# ---- what a second source fills ------------------------------------------------------------


def test_semantic_scholar_fills_one_abstract_and_crossref_the_one_it_did_not(tmp_path, monkeypatch):
    """Acceptance 1: each filled abstract carries the origin of the source that gave it, and its payload file."""
    sources = Sources(
        works=[work(1, doi="10.1/a"), work(2, doi="10.1/b")],
        s2={"10.1/a": paper(abstract=ABSTRACT, doi="10.1/a"), "10.1/b": paper(doi="10.1/b")},
        crossref={"10.1/b": {"abstract": "<jats:p>We measure SYNTHETIC relay energy.</jats:p>"}})
    app = app_for(tmp_path, monkeypatch, sources)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        by_id = records_of(store, rid)
        first, second = abstract_of(store, by_id["W1"]), abstract_of(store, by_id["W2"])
        s2_step = step_output(store, run_id, "record_lookup:semantic_scholar:0")
        cr_step = step_output(store, run_id, "record_lookup:crossref:0")
        payloads = {path.name for path in (tmp_path / "data" / "provider-payloads").glob("*.json")}
    finally:
        client.__exit__(None, None, None)
    assert first["text"] == ABSTRACT and first["abstract_origin"] == "lookup_semantic_scholar"
    assert second["text"] == "We measure SYNTHETIC relay energy." and second["abstract_origin"] == "lookup_crossref_jats"
    assert first["payload_ref"] in payloads and second["payload_ref"] in payloads
    assert (s2_step["asked"], s2_step["abstracts_filled"]) == (2, 1)
    assert (cr_step["asked"], cr_step["abstracts_filled"]) == (1, 1)
    assert sources.lookups == ["10.1/b"]  # the record Semantic Scholar answered is not asked again


def test_only_an_abstract_a_second_source_gave_is_read_into_the_links_again(tmp_path, monkeypatch):
    """A search stores its payload under its step too; its abstracts were linked when they were found."""
    sources = Sources(works=[work(1, doi="10.1/a"), work(2, abstract=ABSTRACT, doi="10.1/b"),
                             work(3, abstract=ABSTRACT, doi="10.1/c")],
                      s2={"10.1/a": paper(abstract=ABSTRACT, doi="10.1/a")})
    app = app_for(tmp_path, monkeypatch, sources)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        links = step_output(app.state.store, run_id, "external_links")
    finally:
        client.__exit__(None, None, None)
    assert links["abstracts_reread"] == 1


def test_a_source_that_is_rate_limited_on_every_attempt_leaves_the_work_to_the_other(tmp_path, monkeypatch):
    """Acceptance 2: the run does not stop, does not pause, and Crossref is still asked (D18)."""
    sources = Sources(works=[work(1, doi="10.1/a")], s2_status=429,
                      crossref={"10.1/a": {"abstract": "<jats:p>We measure SYNTHETIC relay energy.</jats:p>"}})
    app = app_for(tmp_path, monkeypatch, sources)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        svid = records_of(store, rid)["W1"]
        filled = abstract_of(store, svid)
        rows = [dict(r) for r in store.conn.execute(
            "SELECT provider, status FROM record_lookups WHERE source_version_id = ? ORDER BY provider", (svid,))]
        usage = store.run(run_id)["usage"]
    finally:
        client.__exit__(None, None, None)
    # It stopped at screening, where the model is dead: the lookups themselves stopped nothing.
    assert run["pause_reason"] == "model_call_failed", run
    assert rows == [{"provider": "crossref", "status": "found"}, {"provider": "semantic_scholar", "status": "failed"}]
    assert filled["abstract_origin"] == "lookup_crossref_jats"
    # Three Semantic Scholar attempts (the first and two retries) and one Crossref request.
    assert usage["lookup_requests"] == 4


def test_a_crossref_failure_stops_that_record_only_and_the_chunk_goes_on(tmp_path, monkeypatch):
    sources = Sources(works=[work(1, doi="10.1/a"), work(2, doi="10.1/b")], crossref_status=500)
    app = app_for(tmp_path, monkeypatch, sources)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        statuses = dict(store.conn.execute(
            "SELECT source_version_id, status FROM record_lookups WHERE provider = 'crossref'"))
        by_id = records_of(store, rid)
    finally:
        client.__exit__(None, None, None)
    assert sources.lookups == ["10.1/a", "10.1/b"]  # the first failure did not end the chunk
    assert [statuses[by_id[key]] for key in ("W1", "W2")] == ["failed", "failed"]


def test_the_lookup_requests_have_their_own_counter_and_never_touch_the_search_allowance(tmp_path, monkeypatch):
    sources = Sources(works=[work(1, doi="10.1/a")], s2_status=429)
    app = app_for(tmp_path, monkeypatch, sources)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        usage = app.state.store.run(run_id)["usage"]
        searches = len([s for s in run["steps"] if s["kind"].startswith("provider_search")])
    finally:
        client.__exit__(None, None, None)
    # Retries are counted; the search counter sees only the searches this run really sent, and a count probe is not
    # one of them either (slice 04a).
    assert usage["lookup_requests"] == 4 and usage["provider_requests"] == searches


def test_a_resumed_run_asks_no_doi_twice(tmp_path, monkeypatch):
    """Acceptance 3: the stored plan and the stored answers together keep every request to one.

    One record carries an abstract, so the run reaches the screening model and pauses there; without it every
    record would be held and the run would finish with nothing to resume.
    """
    sources = Sources(works=[work(0, abstract=ABSTRACT, doi="10.1/0")]
                      + [work(i, doi=f"10.1/{i}") for i in range(1, 4)])
    app = app_for(tmp_path, monkeypatch, sources)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        assert run["status"] == "paused"
        asked_batches, asked_lookups = list(sources.batches), list(sources.lookups)
        client.post(f"/api/runs/{run_id}/resume")
        view, run = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert sources.batches == asked_batches and sources.lookups == asked_lookups
    assert len(asked_lookups) == 3


def test_a_second_discovery_run_asks_only_about_what_is_still_unanswered(tmp_path, monkeypatch):
    """A `not_found` is an answer and is not asked again; a `failed` one is."""
    sources = Sources(works=[work(1, doi="10.1/a"), work(2, doi="10.1/b")], crossref_status=500)
    app = app_for(tmp_path, monkeypatch, sources)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        first_batches, first_lookups = list(sources.batches), list(sources.lookups)
        sources.crossref_status = 200
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, second)
    finally:
        client.__exit__(None, None, None)
    # Semantic Scholar answered `not_found` for both, so the second run asks it nothing; Crossref failed, so it is
    # asked again about the same two records.
    assert sources.batches == first_batches
    assert sources.lookups == first_lookups + ["10.1/a", "10.1/b"]


def test_a_legacy_research_opens_no_lookup_step_and_sends_no_lookup_request(tmp_path, monkeypatch):
    sources = Sources(works=[work(1, doi="10.1/a")])
    app = app_for(tmp_path, monkeypatch, sources, workflow="legacy", adapter=FakeAdapter())
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        keys = [s["operation_key"] for s in run["steps"]]
        flags = store.conn.execute("SELECT COUNT(*) FROM record_flags").fetchone()[0]
        decisions = store.conn.execute("SELECT COUNT(*) FROM stage_decisions").fetchone()[0]
    finally:
        client.__exit__(None, None, None)
    assert not [key for key in keys if key.startswith(("lookup_plan", "record_lookup", "record_flags",
                                                       "external_links"))]
    assert sources.batches == [] and sources.lookups == []
    assert (flags, decisions) == (0, 0)
    # The legacy OpenAlex request is byte for byte what it was: no reference count in its `select`.
    assert all("referenced_works_count" not in select for select in sources.pages)


def test_an_sw_search_asks_openalex_for_the_reference_count_on_every_page(tmp_path, monkeypatch):
    sources = Sources(works=[work(1, doi="10.1/a", references=182)])
    app = app_for(tmp_path, monkeypatch, sources)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        counts = [row[0] for row in app.state.store.conn.execute(
            "SELECT reference_count FROM source_versions ORDER BY id")]
    finally:
        client.__exit__(None, None, None)
    assert sources.pages and all("referenced_works_count" in select for select in sources.pages)
    assert counts == [182]


# ---- the flags and what they route ------------------------------------------------------------


def test_a_record_without_an_abstract_never_reaches_the_screening_model_and_is_never_excluded(tmp_path, monkeypatch):
    """The acceptance case of the plan: a scripted model that excludes everything cannot exclude this record."""
    sources = Sources(works=[work(1, abstract=ABSTRACT, doi="10.1/a"), work(2, doi="10.1/b")])
    app = app_for(tmp_path, monkeypatch, sources, adapter=ExcludingAdapter())
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        by_id = records_of(store, rid)
        screened = _screened_records(store, run_id)
        without = by_id["W2"]
        decision, selection = decision_of(store, rid, without), selection_of(store, rid, without)
        with_abstract = selection_of(store, rid, by_id["W1"])
    finally:
        client.__exit__(None, None, None)
    assert without not in screened and by_id["W1"] in screened
    assert selection["state"] == "pending" and selection["origin"] == "default"
    assert decision["reason_code"] == "abstract_not_found" and decision["outcome"] == "unresolved"
    assert with_abstract["state"] == "excluded"  # the model's proposal still reaches a record it could read


def test_a_title_word_survey_leaves_the_screening_list_and_is_routed_to_the_seed_pool(tmp_path, monkeypatch):
    sources = Sources(works=[work(1, title=SURVEY_TITLE, abstract=ABSTRACT, doi="10.1/a"),
                             work(2, abstract=ABSTRACT, doi="10.1/b")])
    app = app_for(tmp_path, monkeypatch, sources, adapter=ExcludingAdapter())
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        by_id = records_of(store, rid)
        survey, decision = by_id["W1"], decision_of(store, rid, by_id["W1"])
        selection = selection_of(store, rid, survey)
        screened = _screened_records(store, run_id)
        flags = [dict(r) for r in store.conn.execute(
            "SELECT flag, evidence FROM record_flags WHERE source_version_id = ?", (survey,))]
    finally:
        client.__exit__(None, None, None)
    assert survey not in screened and by_id["W2"] in screened
    assert (decision["reason_code"], decision["outcome"], decision["next_step"]) == (
        "survey_title_word", "unresolved", "seed_pool")
    assert selection == {"state": "pending", "origin": "default", "version": 1}  # the selection is untouched
    assert flags == [{"flag": "survey_title_word", "evidence": "survey"}]


def test_an_abstract_phrase_and_a_reference_count_flag_a_record_that_is_still_screened(tmp_path, monkeypatch):
    """SW9.3 narrows SW5.4: only a title word takes a record off the list."""
    sources = Sources(works=[work(1, abstract=SURVEY_ABSTRACT, doi="10.1/a"),
                             work(2, abstract=ABSTRACT, doi="10.1/b", references=182)])
    app = app_for(tmp_path, monkeypatch, sources, adapter=ExcludingAdapter())
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        by_id = records_of(store, rid)
        screened = _screened_records(store, run_id)
        flags = {row[0]: row[1] for row in store.conn.execute(
            "SELECT source_version_id, flag FROM record_flags")}
        labelling = json.loads(store.conn.execute(
            "SELECT output_json FROM run_steps WHERE run_id = ? AND operation_key = 'record_flags'",
            (run_id,)).fetchone()[0])
        decisions = {key: decision_of(store, rid, by_id[key]) for key in ("W1", "W2")}
    finally:
        client.__exit__(None, None, None)
    assert flags == {by_id["W1"]: "survey_abstract_phrase", by_id["W2"]: "survey_reference_count"}
    assert by_id["W1"] in screened and by_id["W2"] in screened
    # A label, not a decision: the labelling step wrote none. What each record carries afterwards is the abstract
    # stage's own decision, taken from the two model runs (slice 09), not from the flag.
    assert labelling["decisions"] == {}
    assert {decisions[key]["reason_code"] for key in ("W1", "W2")} == {"runs_agree_out_of_scope"}


def test_a_second_run_of_the_same_scope_writes_no_second_flag_and_no_second_decision(tmp_path, monkeypatch):
    sources = Sources(works=[work(1, title=SURVEY_TITLE, abstract=ABSTRACT, doi="10.1/a"), work(2, doi="10.1/b")])
    app = app_for(tmp_path, monkeypatch, sources)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        counted = lambda table: store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        before = (counted("record_flags"), counted("stage_decisions"))
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, second)
        after = (counted("record_flags"), counted("stage_decisions"))
        open_rows = counted("stage_decisions WHERE superseded_at IS NULL")
    finally:
        client.__exit__(None, None, None)
    assert before == after == (1, 2) and open_rows == 2


def test_a_revised_question_that_uses_the_title_word_takes_the_survey_decision_back(tmp_path, monkeypatch):
    """The earlier revision's decision must not keep the record away from screening once the word is the subject."""
    sources = Sources(works=[work(1, title=SURVEY_TITLE, abstract=ABSTRACT, doi="10.1/a")])
    app = app_for(tmp_path, monkeypatch, sources)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        svid = records_of(store, rid)["W1"]
        first = decision_of(store, rid, svid)
        client.post(f"/api/researches/{rid}/scope", json={
            "question": "How does survey length affect response rates in sensor network user studies?",
            "expected_version": view["research"]["version"]})
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, second)
        protocol = store.current_protocol(rid, store.research(rid)["current_scope_revision"])
        later = decision_of(store, rid, svid)
        screened = _screened_records(store, second)
    finally:
        client.__exit__(None, None, None)
    assert first["reason_code"] == "survey_title_word"
    assert "survey" in protocol["body"]["survey"]["dropped_title_words"]
    assert later["reason_code"] == "abstract_not_proposed"
    assert svid in screened


def test_an_abstract_that_arrived_from_a_second_source_corrects_the_decision_it_was_written_under(tmp_path, monkeypatch):
    """The stored row must stop saying the record has no abstract once a lookup filled one."""
    sources = Sources(works=[work(1, doi="10.1/a")])
    app = app_for(tmp_path, monkeypatch, sources)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        svid = records_of(store, rid)["W1"]
        first = decision_of(store, rid, svid)
        # A later run finds the abstract this one could not.
        sources.crossref["10.1/a"] = {"abstract": "<jats:p>We measure SYNTHETIC relay energy.</jats:p>"}
        sources.s2["10.1/a"] = paper(abstract=ABSTRACT, doi="10.1/a")
        store.conn.execute("DELETE FROM record_lookups WHERE source_version_id = ?", (svid,))
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, second)
        later = decision_of(store, rid, svid)
        screened = _screened_records(store, second)
    finally:
        client.__exit__(None, None, None)
    assert first["reason_code"] == "abstract_not_found"
    assert later["reason_code"] == "abstract_not_proposed" and later["outcome"] == "unresolved"
    assert svid in screened  # with an abstract it is a candidate again


def test_a_record_the_user_included_keeps_its_selection_and_still_gets_its_decision(tmp_path, monkeypatch):
    sources = Sources(works=[work(1, title=SURVEY_TITLE, abstract=ABSTRACT, doi="10.1/a")])
    app = app_for(tmp_path, monkeypatch, sources)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        svid = records_of(store, rid)["W1"]
        answer = client.patch(f"/api/researches/{rid}/selections/{svid}",
                              json={"state": "included", "expected_version": 1,
                                    "reason": "SYNTHETIC user choice"})
        assert answer.status_code == 200, answer.text
        before = selection_of(store, rid, svid)
        store.conn.execute("DELETE FROM record_flags WHERE source_version_id = ?", (svid,))
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, second)
        after, decision = selection_of(store, rid, svid), decision_of(store, rid, svid)
        flags = store.conn.execute("SELECT COUNT(*) FROM record_flags WHERE source_version_id = ?",
                                   (svid,)).fetchone()[0]
    finally:
        client.__exit__(None, None, None)
    assert before == after and after["origin"] == "user" and after["state"] == "included"
    assert decision["reason_code"] == "survey_title_word" and flags == 1


def test_no_selection_of_the_run_was_written_by_a_code_rule(tmp_path, monkeypatch):
    """`derive_selection` is not called in this slice, so `code_rule` reaches no row and no API answer."""
    sources = Sources(works=[work(1, title=SURVEY_TITLE, abstract=ABSTRACT, doi="10.1/a"), work(2, doi="10.1/b")])
    app = app_for(tmp_path, monkeypatch, sources)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        origins = {row[0] for row in app.state.store.conn.execute("SELECT DISTINCT origin FROM selections")}
        history = {row[0] for row in app.state.store.conn.execute("SELECT DISTINCT origin FROM selection_history")}
    finally:
        client.__exit__(None, None, None)
    assert "code_rule" not in origins and "code_rule" not in history
    assert all(source["selection"]["origin"] != "code_rule" for source in view["sources"])


def test_a_work_whose_published_version_is_not_a_survey_is_still_screened(tmp_path, monkeypatch):
    """SW9.4: a flag on one version never drops the work, so the head is screened while the preprint is flagged."""
    published = work(1, abstract=ABSTRACT, doi="10.1/a")
    preprint = work(2, title=SURVEY_TITLE, abstract=ABSTRACT, doi="10.48550/arxiv.2601.00001")
    preprint["primary_location"] = {"version": "submittedVersion"}
    sources = Sources(works=[published, preprint],
                      s2={"2601.00001": paper(doi="10.1/a", paper_id="s2xyz")})
    app = app_for(tmp_path, monkeypatch, sources)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        by_id = records_of(store, rid)
        screened = _screened_records(store, run_id)
        head = store.work_heads(rid)[store.source(by_id["W1"])["work_id"]]
    finally:
        client.__exit__(None, None, None)
    assert head == by_id["W1"] and head in screened


def _screened_records(store, run_id):
    """Which records this run really put in front of the screening model, read from the stored step inputs.

    The step input names candidates, not records, so the candidate rows map them back; what was sent is what was
    stored, which is the only account of what the model saw. Since slice 09 an `sw` run's screening step is the
    abstract stage's, whose stored payload holds the record identifiers (the model itself saw short handles).
    """
    sent = set()
    for row in store.conn.execute(
        "SELECT i.payload_json FROM step_inputs i JOIN run_steps s ON s.id = i.step_id"
        " WHERE s.run_id = ? AND s.kind IN ('model:screening', 'model:abstract_screening')", (run_id,),
    ):
        sent |= {c["candidate_id"] for c in json.loads(row[0]).get("candidates", [])}
    if not sent:
        return set()
    marks = ", ".join("?" * len(sent))
    return {r[0] for r in store.conn.execute(
        f"SELECT source_version_id FROM candidates WHERE id IN ({marks})", tuple(sorted(sent)))}
