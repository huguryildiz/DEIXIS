"""An `sw` discovery run that widens its search from the records of its own first round (slice 04b, SW2.4).

The model adapter fails on every call, so a second round that still runs, ran without a model. Records, titles and
provider answers are SYNTHETIC and the transport is mocked: passing shows workflow behavior — which phrase enters
the second query, what the protocol records, what a resumed run repeats — not that the expansion finds better
literature. A `legacy` research is exercised too, because nothing about it may change.
"""

import json
import time
from dataclasses import replace

import httpx
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents.fetch import FetchResult
from deixis.models.adapter import ModelStepResult
from deixis.providers.registry import CONNECTORS
from deixis.domain.canonical import sha256_hex
from deixis.workflow import protocol
from fakes import FakeAdapter

QUESTION = "What is the effect of packet size on energy consumption in wireless sensor networks?"
CLAIM_QUESTION = ("Which packet size in wireless sensor networks, using integer programming, not surveys, "
                  "changes energy consumption?")
# The first round's records repeat "duty cycle", which the question never wrote; the second round's do not.
FIRST_TITLE = "SYNTHETIC duty cycle scheduling in a sensor node"
CLAIM_TITLE = "SYNTHETIC duty cycle scheduling by integer programming in a survey of nodes"
SECOND_TITLE = "SYNTHETIC duty cycle policy of a relay"
ACCEPTED = "duty cycle"
# The two count requests the field probe sends for the accepted phrase. The setting block entered the query as its
# root words, so the group is the one `build_vocabulary` chose: (energy OR wireless).
PHRASE_PROBE = f'"{ACCEPTED}"'
FIELD_PROBE = f'"{ACCEPTED}" AND (energy OR wireless)'
DEFAULT_COUNT = 8  # below the field probe's threshold, so an unlisted phrase is refused
PAGE = 2  # a small page keeps the fixtures small; real page sizes are checked in tests/test_providers.py


def DeadAdapter():
    """Every model call fails. An expansion and a second round that still run, ran without a model (SW2.3)."""
    return FakeAdapter(fail=lambda si: ModelStepResult("failed", error="SYNTHETIC model connection is down"))


def work(number, title):
    return {"id": f"https://openalex.org/W{number}", "doi": f"https://doi.org/10.1/oa.{number}",
            "display_name": f"{title} {number}", "publication_year": 2024, "type": "article",
            "authorships": [], "abstract_inverted_index": {"We": [0], "measure.": [1]}}


class Field:
    """OpenAlex answering count probes and serving one set of pages per round.

    A query that holds the accepted phrase is the second round's; anything else is the first round's. Every count
    probe and every page request is recorded, so a resumed run can be asked what it sent again.
    """

    def __init__(self, first=4, second=3, counts=None, first_title=FIRST_TITLE, probe_status=200,
                 second_status=200, fail_at=None):
        self.counts = {PHRASE_PROBE: 100, FIELD_PROBE: 40} if counts is None else counts
        self.first = [work(index, first_title) for index in range(first)]
        self.second = [work(100 + index, SECOND_TITLE) for index in range(second)]
        self.probe_status, self.second_status, self.fail_at = probe_status, second_status, fail_at
        self.probes, self.pages = [], []

    def __call__(self, request):
        if request.url.host != "api.openalex.org":
            return httpx.Response(404)  # the other providers are not mocked and fail, which D18 carries on from
        params = request.url.params
        query = params.get("search.title_and_abstract") or ""
        if params.get("per_page") == "1" and params.get("select") == "id":
            self.probes.append(query)
            if self.probe_status != 200:
                return httpx.Response(self.probe_status)
            return httpx.Response(200, json={"meta": {"count": self.counts.get(query, DEFAULT_COUNT)}, "results": []})
        second = ACCEPTED in query
        cursor, size = params.get("cursor"), int(params["per_page"])
        start = 0 if cursor in (None, "*") else int(cursor)
        self.pages.append((query, start))
        if second and self.second_status != 200:
            return httpx.Response(self.second_status)
        if (query, start) == self.fail_at:
            return httpx.Response(429, text="SYNTHETIC rate limit", headers={"retry-after": "0"})
        works = self.second if second else self.first
        end = min(start + size, len(works))
        return httpx.Response(200, json={
            "meta": {"count": len(works), "next_cursor": str(end) if end < len(works) else None},
            "results": works[start:end]})


async def no_fetch(url):
    return FetchResult("http_error", final_url=url, http_status=404)


def app_for(tmp_path, monkeypatch, handler, workflow="sw", adapter=None):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.setitem(CONNECTORS, "openalex", replace(CONNECTORS["openalex"], max_results=PAGE))
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", workflow)
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_workflow=workflow, search_query="code",
                               protocol_approval="as_proposed", fulltext_fetch="off"),
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
               **body}
    rid = client.post("/api/researches", json=payload).json()["research"]["id"]
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    return rid, run_id, *wait(client, rid, run_id)


def step_output(store, run_id, key):
    row = store.conn.execute("SELECT output_json FROM run_steps WHERE run_id = ? AND operation_key = ?",
                             (run_id, key)).fetchone()
    return None if row is None or row[0] is None else json.loads(row[0])


def protocols(store, rid):
    return [{"protocol_revision": row["protocol_revision"], "reason": row["reason"],
             "body": json.loads(row["body_json"]), "hash": row["body_sha256"]}
            for row in store.conn.execute(
                "SELECT * FROM protocol_records WHERE research_id = ? ORDER BY protocol_revision", (rid,))]


def openalex_rows(view):
    return [row for row in view["search_runs"] if row["provider"] == "openalex"]


def reached_screening(run):
    """Whether the run got past the search stage to the abstract stage, whatever it then did (slice 09).

    These tests run with the model connection down. Before slice 09 that always paused the run at the screening
    call; now the abstract stage's code half decides first, so a run whose records code can classify finishes.
    What each test here is about is that the search stage completed and the run went on, not which of the two.
    """
    assert "abstract_stage" in {s["operation_key"] for s in run["steps"]}, run
    assert run["status"] in ("paused", "completed") and run["pause_reason"] in (None, "model_call_failed"), run
    return True


def test_a_phrase_the_first_round_repeated_enters_a_second_round_query(tmp_path, monkeypatch):
    """The question never wrote "duty cycle"; the records it found did, and the field probe kept it."""
    field = Field()
    app = app_for(tmp_path, monkeypatch, field)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        expansion = step_output(store, run_id, "vocabulary_expansion")["expansion"]
        titles = [row[0] for row in store.conn.execute(
            "SELECT v.title FROM candidates c JOIN source_versions v ON v.id = c.source_version_id"
            " WHERE c.research_id = ?", (rid,))]
    finally:
        client.__exit__(None, None, None)
    assert ACCEPTED not in QUESTION
    assert expansion["terms"] == [ACCEPTED] and expansion["skipped"] is None
    accepted = next(row for row in expansion["candidates"] if row["phrase"] == ACCEPTED)
    assert (accepted["sources"], accepted["phrase_count"], accepted["field_count"]) == (["title"], 100, 40)
    # The second round is its own query, read on its own search rows, and its records are candidates like any other.
    second = [row for row in openalex_rows(view) if ACCEPTED in row["query_text"]]
    assert second and all(row["status"] == "completed" for row in second)
    assert [row["page_number"] for row in second] == [0, 1]
    assert sum(SECOND_TITLE in title for title in titles) == 3
    assert sum(FIRST_TITLE in title for title in titles) == 4


def test_the_expansion_runs_while_every_model_call_fails(tmp_path, monkeypatch):
    field = Field()
    client = client_of(app_for(tmp_path, monkeypatch, field))
    try:
        rid, run_id, view, run = discover(client)
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "paused" and run["pause_reason"] == "model_call_failed", run
    assert any(ACCEPTED in query for query, _ in field.pages)
    keys = [step["operation_key"] for step in run["steps"]]
    assert keys.index("vocabulary_expansion") > keys.index("search:0")  # after the first round, before screening
    assert keys.index("protocol_expansion") > keys.index("vocabulary_expansion")


def test_a_resumed_run_repeats_no_count_request_no_page_and_no_second_revision(tmp_path, monkeypatch):
    field = Field()
    app = app_for(tmp_path, monkeypatch, field)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        assert run["status"] == "paused"
        probed, read = list(field.probes), list(field.pages)
        frozen = protocols(app.state.store, rid)
        client.post(f"/api/runs/{run_id}/resume")
        view, run = wait(client, rid, run_id)
        again = protocols(app.state.store, rid)
    finally:
        client.__exit__(None, None, None)
    assert field.probes == probed and field.pages == read
    assert any(ACCEPTED in query for query in probed)
    # The expansion step had succeeded, so the second protocol revision is not frozen a second time either.
    assert len(again) == 2 and [row["hash"] for row in again] == [row["hash"] for row in frozen]


def test_no_query_and_no_probe_of_either_round_holds_a_claim_word(tmp_path, monkeypatch):
    """SW1.3: a phrase the records repeat is dropped when it holds the claim under test."""
    field = Field(first_title=CLAIM_TITLE, counts={PHRASE_PROBE: 100, FIELD_PROBE: 40})
    client = client_of(app_for(tmp_path, monkeypatch, field))
    try:
        rid, run_id, view, run = discover(client, CLAIM_QUESTION)
    finally:
        client.__exit__(None, None, None)
    asked = [query for query, _ in field.pages] + field.probes + [r["query_text"] for r in view["search_runs"]]
    assert asked
    for query in asked:
        assert "integer programming" not in query.lower() and "survey" not in query.lower()


def test_with_no_accepted_phrase_there_is_no_second_round_and_no_second_protocol_revision(tmp_path, monkeypatch):
    field = Field(counts={})  # every phrase falls under the field count
    app = app_for(tmp_path, monkeypatch, field)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        expansion = step_output(app.state.store, run_id, "vocabulary_expansion")
        frozen = protocols(app.state.store, rid)
    finally:
        client.__exit__(None, None, None)
    assert expansion["expansion"]["terms"] == [] and expansion["queries"] == []
    assert {row["reason"] for row in expansion["expansion"]["candidates"]} == {"below_field_count"}
    assert not any(ACCEPTED in query for query, _ in field.pages)
    assert [row["protocol_revision"] for row in frozen] == [1] and frozen[0]["reason"] is None
    assert "expansion" not in frozen[0]["body"] and frozen[0]["body"]["arms"] == ["keyword_search"]


def test_an_accepted_phrase_freezes_a_second_revision_and_leaves_the_first_alone(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, Field())
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        frozen = protocols(app.state.store, rid)
        stored = step_output(app.state.store, run_id, "vocabulary_expansion")
        first = step_output(app.state.store, run_id, "source_routing")  # the queries routing compiled (D93)
        rebuilt = protocol.build_protocol(
            app.state.store.scope(rid, 1), app.state.store.run(run_id)["budget"], None,
            first["queries"] + stored["queries"], app.state.package.package_hash,
            Settings(data_dir=tmp_path / "data", port=8765, search_workflow="sw", search_query="code"),
            vocabulary=first["vocabulary"], expansion=stored["expansion"],
            # The approval is an input of the body like the vocabulary, so the rebuild is given it too (slice 08a).
            approval=app.state.store.approval_step(run_id)["output"]["approval"], routing=first["routing"])
    finally:
        client.__exit__(None, None, None)
    assert [(row["protocol_revision"], row["reason"]) for row in frozen] == [(1, None), (2, "data_expansion")]
    first, second = frozen[0]["body"], frozen[1]["body"]
    assert "expansion" not in first and first["arms"] == ["keyword_search"]
    assert second["arms"] == ["keyword_search", "data_expansion"]
    assert second["expansion"]["terms"] == [ACCEPTED] and second["thresholds"]["expansion"]["min_field_count"] == 20
    # The first round's queries stay in the body and the second round's are added after them.
    assert [q["query_text"] for q in first["compiled_queries"]] == [
        q["query_text"] for q in second["compiled_queries"][: len(first["compiled_queries"])]]
    assert any(ACCEPTED in q["query_text"] for q in second["compiled_queries"])
    # The same stored step output builds the same body a second time (SW14.7).
    assert sha256_hex(rebuilt) == frozen[1]["hash"]


def test_a_count_probe_that_cannot_be_read_accepts_nothing_and_the_run_goes_on(tmp_path, monkeypatch):
    """A phrase from the data has nothing but its counts behind it, so an unknown count is not a small count."""
    app = app_for(tmp_path, monkeypatch, Field(probe_status=503))
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        expansion = step_output(app.state.store, run_id, "vocabulary_expansion")["expansion"]
    finally:
        client.__exit__(None, None, None)
    assert expansion["terms"] == []
    assert {row["reason"] for row in expansion["candidates"]} == {"count_unknown"}
    assert reached_screening(run)  # the second round refused every phrase and the run went on
    assert openalex_rows(view)


def test_a_second_round_provider_that_fails_leaves_the_first_round_standing(tmp_path, monkeypatch):
    field = Field(second_status=500)
    app = app_for(tmp_path, monkeypatch, field)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
    finally:
        client.__exit__(None, None, None)
    rows = openalex_rows(view)
    assert [row["status"] for row in rows if ACCEPTED in row["query_text"]] == ["failed"]
    assert [row["status"] for row in rows if ACCEPTED not in row["query_text"]] == ["completed", "completed"]
    # The run already had a search that succeeded, so a failed second round does not pause it (D18).
    assert run["pause_reason"] == "model_call_failed"


def test_the_request_allowance_covers_the_second_round_and_its_retries(tmp_path, monkeypatch):
    """The derived allowance is computed over both rounds; a retried page must not exhaust it (D75 review)."""
    field = Field(first=6, second=6, fail_at=(f'"{ACCEPTED}" AND (energy OR wireless)', 2))
    app = app_for(tmp_path, monkeypatch, field)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
    finally:
        client.__exit__(None, None, None)
    assert run["pause_reason"] == "model_call_failed", run  # never budget_exhausted
    assert run["usage"]["provider_requests"] > 3  # quick effort allows three provider requests
    assert any(ACCEPTED in row["query_text"] and row["status"] == "completed" for row in openalex_rows(view))


def test_a_legacy_research_opens_no_expansion_step(tmp_path, monkeypatch):
    from fakes import valid_response

    def one_provider_plan(si):
        if si["task_type"] != "search_plan":
            return valid_response(si)
        output = json.loads(valid_response(si))
        output["search_plan"].update(providers=["openalex"], concepts=[
            {"label": "packet size", "role": "core", "synonyms": ["packet size"]}])
        return json.dumps(output)

    app = app_for(tmp_path, monkeypatch, Field(), workflow="legacy", adapter=FakeAdapter(one_provider_plan))
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        frozen = protocols(app.state.store, rid)
    finally:
        client.__exit__(None, None, None)
    keys = [step["operation_key"] for step in run["steps"]]
    assert "vocabulary_expansion" not in keys and "protocol_expansion" not in keys
    assert [row["protocol_revision"] for row in frozen] == [1]
    assert frozen[0]["body"]["arms"] == ["keyword_search"] and "expansion" not in frozen[0]["body"]


def test_a_setting_synonym_takes_the_setting_blocks_place_and_the_task_block_stays(tmp_path, monkeypatch):
    """Slice 13g (D90): the first round's records repeat "sensor node", which shares a word with the setting block;
    the second round searches it as the setting block and keeps the task block, with "duty cycle" added to it."""
    synonym = "sensor node"
    field = Field(counts={PHRASE_PROBE: 100, FIELD_PROBE: 40, f'"{synonym}"': 100,
                          f'"{synonym}" AND (energy OR wireless)': 40})
    app = app_for(tmp_path, monkeypatch, field)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        stored = step_output(app.state.store, run_id, "vocabulary_expansion")
        first = step_output(app.state.store, run_id, "vocabulary")
    finally:
        client.__exit__(None, None, None)
    assert set(stored["expansion"]["terms"]) == {ACCEPTED, synonym}
    assert stored["expansion"]["second_round"] == {"setting_synonyms": [synonym], "task_additions": [ACCEPTED],
                                                   "setting_width": 2}
    (second,) = [q["query_text"] for q in stored["queries"] if q["provider_id"] == "openalex"]
    assert second == f'"{synonym}" AND (packet OR "{ACCEPTED}")'
    assert second not in [q["query_text"] for q in first["queries"]]
