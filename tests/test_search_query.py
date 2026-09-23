"""The model-written sw query: the contract of one call, what code checks and counts, and the run around it (D92).

Every question, term and count here is SYNTHETIC and from more than one field, OpenAlex is mocked and the model is
the fake adapter, so passing shows workflow behavior: which call is made, what is counted, what is searched and what
is recorded. It says nothing about whether a model writes a good query; that was measured on three questions with
one model (`.local/sw-model-query-experiment-2026-09-24/result.md`) and nowhere else.
"""

import asyncio
import json
import time
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.domain import contracts
from deixis.domain.rules import LITERATURE_TASKS, SEARCH_QUERY_CALLS, TEST_EFFORT_BUDGETS, schema_repairs
from deixis.domain.skill import RUNTIME_FILES, integrity_issues, load_skill_package
from deixis.models.adapter import ModelStepResult
from deixis.providers.registry import CONNECTORS
from deixis.workflow import search_query
from deixis.workflow.expansion import searched_terms
from fakes import FakeAdapter, envelope, valid_response

FIXTURES = Path(__file__).parent / "fixtures" / "research"
STEP_INPUT = json.loads((FIXTURES / "step-inputs.json").read_text())["H_search_query"]


def term(phrase, kind="topic", why="SYNTHETIC reason"):
    return {"term": phrase, "kind": kind, "why": why}


def answer(setting, task, setting_backup=(), task_backup=()):
    return {"setting": [term(p) for p in setting], "task": [term(p) for p in task],
            "setting_backup": [{"term": p} for p in setting_backup], "task_backup": [{"term": p} for p in task_backup]}


def counter(counts, default=50):
    asked = []

    async def count(query):
        asked.append(query)
        return counts.get(query, default)
    return count, asked


# ---- the contract of one call -------------------------------------------------------------------------------

def test_the_task_is_registered_with_its_schema_its_method_file_and_one_repair():
    assert contracts.TASK_OUTPUTS["search_query"] == ("SearchQuery",)
    assert contracts.SCHEMA_VERSIONS["SearchQuery"] == "deixis.search_query.v1"
    assert RUNTIME_FILES["search_query"] == ("SKILL.md", "references/search-query.md")
    assert "search_query" in LITERATURE_TASKS  # the literature model writes the query, as it labels blocks
    assert schema_repairs("search_query") == 1
    assert contracts.strict_compatibility_issues(contracts.step_output_schema("search_query")) == []


def test_the_method_package_is_intact_and_names_no_field():
    assert integrity_issues() == []
    text = load_skill_package().runtime_text("search_query")
    assert "deixis.search_query.v1" in text
    # The rules are generic: none of the measurement's three questions reaches the instructions.
    assert not any(word in text.lower() for word in ("quantum", "packet", "sepsis", "entanglement", "neonatal"))


def test_the_fake_adapter_answers_the_task_with_a_valid_query():
    report = contracts.validate_model_output(STEP_INPUT, valid_response(STEP_INPUT))
    assert report.ok, [vars(i) for i in report.issues]


def test_a_block_left_empty_is_refused_by_the_schema():
    draft = json.loads(valid_response(STEP_INPUT)) | {"task": []}
    assert not contracts.validate_model_output(STEP_INPUT, draft).ok


# ---- what code checks and counts ----------------------------------------------------------------------------

def test_a_term_no_record_holds_alone_is_replaced_by_the_next_backup_of_its_block():
    count, _ = counter({'"coral transplant"': 0})
    checked = asyncio.run(search_query.check(
        answer(["degraded reefs"], ["coral transplant", "larval seeding"], task_backup=["coral gardening"]), count))
    queried = [(t["phrase"], t["block"]) for t in checked["terms"] if not t["dropped"]]
    assert queried == [("degraded reefs", "setting"), ("coral gardening", "task"), ("larval seeding", "task")]
    dropped = next(t for t in checked["terms"] if t["phrase"] == "coral transplant")
    assert dropped["dropped"] == "zero_results" and dropped["phrase_count"] == 0
    assert checked["meta"]["coral gardening"]["backup_for"] == "coral transplant"
    assert checked["backups_left"]["task"] == []
    assert checked["searchable"]


def test_a_term_that_finds_nothing_with_the_other_block_stays_and_carries_a_warning():
    count, _ = counter({'"rail freight" AND (timetable)': 0})
    checked = asyncio.run(search_query.check(answer(["rail freight", "rail network"], ["timetable"]), count))
    assert [t["phrase"] for t in checked["terms"] if not t["dropped"]] == ["rail freight", "rail network", "timetable"]
    assert checked["warnings"] == [{"phrase": "rail freight", "block": "setting",
                                    "warning": "no_records_with_other_block"}]


def test_a_very_large_count_removes_nothing_and_an_unknown_count_is_a_warning():
    count, _ = counter({'traffic': 5_000_000, 'timetable': None})
    checked = asyncio.run(search_query.check(answer(["traffic"], ["timetable"]), count))
    assert all(t["dropped"] is None and not t["and_only"] for t in checked["terms"])
    assert {"phrase": "timetable", "block": "task", "warning": "count_unknown"} in checked["warnings"]


def test_a_block_whose_every_term_and_backup_finds_nothing_cannot_be_searched():
    count, _ = counter({'"coral transplant"': 0, '"coral gardening"': 0})
    checked = asyncio.run(search_query.check(
        answer(["degraded reefs"], ["coral transplant"], task_backup=["coral gardening"]), count))
    assert not checked["searchable"] and checked["gate_count"] is None


def test_the_counts_stay_under_their_ceiling_and_none_is_asked_twice():
    count, asked = counter({})
    checked = asyncio.run(search_query.check(
        answer(["a one", "a two", "a three"], ["b one", "b two", "b three"]), count))
    assert len(asked) == len(set(asked)) <= search_query.MAX_COUNT_REQUESTS
    assert checked["probes_skipped"] == 0


def test_every_term_enters_the_query_as_its_whole_phrase():
    count, _ = counter({})
    checked = asyncio.run(search_query.check(answer(["degraded reefs"], ["coral restoration"]), count))
    assert all(t["in_query"] == "phrase" and t["root"] == t["phrase"] for t in checked["terms"])
    assert all(t["origin"] == "search_query" for t in checked["terms"])


# ---- the proposal, its queries and its correction ------------------------------------------------------------

def code_vocabulary(too_broad=False):
    return {"language": "en", "block_assignment": "rule",
            "terms": [{"phrase": "rail networks", "block": "setting", "origin": "question", "root": "rail",
                       "in_query": "root", "phrase_count": 90, "root_count": 900, "and_only": False, "dropped": None},
                      {"phrase": "timetabling", "block": "task", "origin": "question", "root": "timetabling",
                       "in_query": "root", "phrase_count": 80, "root_count": 80, "and_only": False, "dropped": None}],
            "claim_words": ["integer programming"], "exclusion_words": ["survey"], "outcome_terms": ["delay"],
            "gate_count": 40, "probes": [], "probes_skipped": 0, "too_broad": too_broad}


CODE_QUERIES = [{"provider_id": p, "query_text": f"{p}: rail AND timetabling", "rationale": "Concept blocks",
                 "dropped_terms": []} for p in ("openalex", "semantic_scholar")]


def proposal(model_answer=None, counts=None, too_broad=False):
    count, _ = counter(counts or {})
    checked = asyncio.run(search_query.check(model_answer or answer(["rail freight"], ["timetable", "integer programming"]),
                                             count))
    return search_query.vocabulary(code_vocabulary(too_broad), CODE_QUERIES, checked,
                                   {"status": "ready", "attempts": [], "step_input_id": "sti_x", "resolved_model": "m",
                                    "answer": {}})


def test_the_proposal_holds_the_model_terms_the_question_side_lists_and_the_code_query_whole():
    built = proposal()
    assert built["block_assignment"] == "search_query" and built["too_broad"] is False
    # A side-list phrase the model chose as a term is not in two blocks at once.
    assert built["claim_words"] == [] and built["exclusion_words"] == ["survey"] and built["outcome_terms"] == ["delay"]
    assert built["code_query"]["searched"] and built["code_query"]["vocabulary"]["terms"][0]["phrase"] == "rail networks"
    # What orders and closes records reads both queries' terms; the model's own list stays the model's.
    assert [t["phrase"] for t in searched_terms(built, "setting")] == ["rail freight", "rail networks"]


def test_a_code_query_too_broad_to_search_is_not_offered_beside_the_model_query():
    assert not proposal(too_broad=True)["code_query"]["searched"]


def test_the_first_round_pairs_the_two_queries_per_provider_within_the_limit():
    built = proposal()
    queries = search_query.compile_queries(built, ["openalex", "semantic_scholar", "crossref"], 3)
    assert [(q["provider_id"], q["origin"]) for q in queries] == [
        ("openalex", "model"), ("openalex", "code"), ("semantic_scholar", "model")]
    assert queries[0]["query_text"] == '"rail freight" AND (timetable OR "integer programming")'
    assert search_query.model_queries(queries) == [queries[0], queries[2]]


def test_a_code_query_identical_to_the_model_query_is_not_sent_twice_and_one_switched_off_is_not_sent():
    built = proposal()
    same = built | {"code_query": built["code_query"] | {"queries": [
        {"provider_id": "openalex", "query_text": '"rail freight" AND (timetable OR "integer programming")'}]}}
    assert [q["origin"] for q in search_query.compile_queries(same, ["openalex"], 4)] == ["model"]
    off = built | {"code_query": built["code_query"] | {"searched": False}}
    assert [q["origin"] for q in search_query.compile_queries(off, ["openalex", "semantic_scholar"], 4)] == [
        "model", "model"]


def test_a_correction_acts_on_the_model_terms_counts_what_it_adds_and_can_switch_the_code_query_off():
    built = proposal()
    count, asked = counter({'"freight corridor"': 0})
    rebuilt = asyncio.run(search_query.rebuild(built, [
        {"op": "remove", "phrase": "integer programming"},
        {"op": "add", "phrase": "crew scheduling", "block": "task"},
        {"op": "add", "phrase": "freight corridor", "block": "setting"},
        {"op": "move", "phrase": "delay", "block": "task"},
    ], False, count))
    rows = {t["phrase"]: (t["block"], t["origin"], t["dropped"]) for t in rebuilt["terms"]}
    assert rows == {"rail freight": ("setting", "search_query", None), "timetable": ("task", "search_query", None),
                    "crew scheduling": ("task", "user", None), "freight corridor": ("setting", "user", "zero_results"),
                    "delay": ("task", "question", None)}
    assert rebuilt["outcome_terms"] == [] and not rebuilt["code_query"]["searched"]
    # A count the proposal already read is not asked again; the new terms are.
    assert '"rail freight"' not in asked and '"crew scheduling"' in asked
    assert {e["phrase"] for e in rebuilt["user_edits"]} == {"integer programming", "crew scheduling",
                                                            "freight corridor", "delay"}


# ---- the run around it ---------------------------------------------------------------------------------------

QUESTION = "SYNTHETIC: which scheduling methods have been proposed for rail freight timetables?"
KEY_TERMS = "rail freight; timetable"
WORK = {"id": "https://openalex.org/W9", "doi": "https://doi.org/10.9/a",
        "display_name": "SYNTHETIC rail freight timetable scheduling", "publication_year": 2024, "type": "article",
        "authorships": [], "abstract_inverted_index": {"We": [0], "schedule": [1], "trains.": [2]}}


class OpenAlex:
    """Mocked OpenAlex: counts from a table (default 50), every search one record."""

    def __init__(self, counts=None):
        self.table, self.counts, self.searches = counts or {}, [], []

    def __call__(self, request):
        if request.url.host != "api.openalex.org":
            return httpx.Response(404)
        params = request.url.params
        query = params.get("search.title_and_abstract")
        if params.get("per_page") == "1" and params.get("select") == "id":
            self.counts.append(query)
            return httpx.Response(200, json={"meta": {"count": self.table.get(query, 50)}, "results": []})
        self.searches.append(query)
        return httpx.Response(200, json={"meta": {"count": 1}, "results": [WORK]})


async def no_fetch(url):
    from deixis.documents.fetch import FetchResult
    return FetchResult("http_error", final_url=url, http_status=404)


def client_for(tmp_path, monkeypatch, handler, adapter, approval="as_proposed"):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765, search_workflow="sw", search_query="model",
                              protocol_approval=approval, fulltext_fetch="off"),
                     adapters={"fake": adapter}, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                     fetcher=no_fetch, extra_hosts=("testserver",), trusted_clients=("testclient",))
    client = TestClient(app)
    client.__enter__()
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    return client


def start(client, **body):
    response = client.post("/api/researches", json={"question": QUESTION, "model_connection": "fake",
                                                    "requested_model": "fake-model", "effort": "quick", **body})
    assert response.status_code == 201, response.text
    rid = response.json()["research"]["id"]
    return rid, client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]


def wait(client, rid, run_id, status=("completed", "failed", "paused")):
    deadline = time.time() + 15
    while time.time() < deadline:
        view = client.get(f"/api/researches/{rid}").json()
        run = next(r for r in view["runs"] if r["id"] == run_id)
        if run["status"] in status:
            return view, run
        time.sleep(0.05)
    raise AssertionError("the run did not settle")


def step_output(client, run_id, key):
    row = client.app.state.store.conn.execute(
        "SELECT output_json FROM run_steps WHERE run_id = ? AND operation_key = ?", (run_id, key)).fetchone()
    return json.loads(row[0]) if row and row[0] else None


def protocol_body(client, rid, revision=1):
    return json.loads(client.app.state.store.conn.execute(
        "SELECT body_json FROM protocol_records WHERE research_id = ? ORDER BY protocol_revision LIMIT 1 OFFSET ?",
        (rid, revision - 1)).fetchone()[0])


def calls(adapter, task="search_query"):
    return [si for si in adapter.calls if si["task_type"] == task]


def test_the_model_writes_the_query_and_the_code_query_is_searched_beside_it(tmp_path, monkeypatch):
    openalex, adapter = OpenAlex(), FakeAdapter()
    client = client_for(tmp_path, monkeypatch, openalex, adapter)
    rid, run_id = start(client)
    _, run = wait(client, rid, run_id)
    assert run["status"] == "completed", run
    keys = [s["operation_key"] for s in run["steps"]]
    assert keys.index("vocabulary") < keys.index("search_query") < keys.index("criterion") < keys.index("protocol")
    assert len(calls(adapter)) == 1
    stored = step_output(client, run_id, "search_query")
    assert stored["status"] == "ready"
    origins = [(q["provider_id"], q["origin"]) for q in stored["queries"]]
    assert origins[:2] == [("openalex", "model"), ("openalex", "code")]
    assert '"synthetic setting" AND "synthetic task"' in openalex.searches
    assert next(q["query_text"] for q in stored["queries"] if q["origin"] == "code") in openalex.searches
    body = protocol_body(client, rid)
    assert body["search_query"]["status"] == "ready" and body["search_query"]["code_query_searched"] is True
    assert body["search_query"]["prompt"] == {"files": ["SKILL.md", "references/search-query.md"],
                                              "schema_version": "deixis.search_query.v1"}
    assert body["search_query"]["answer"]["setting"][0]["term"] == "synthetic setting"
    assert {q.get("origin") for q in body["compiled_queries"]} == {"model", "code"}
    assert body["concept_blocks"] == {"setting": ["synthetic setting"], "task": ["synthetic task"]}
    # The run was given the model-query calls on top of its preset.
    preset = TEST_EFFORT_BUDGETS["quick"].max_model_calls
    assert run["budget"]["max_model_calls"] - preset >= SEARCH_QUERY_CALLS


def test_a_chosen_term_no_record_holds_is_searched_as_its_backup(tmp_path, monkeypatch):
    openalex = OpenAlex({'"synthetic task"': 0})
    client = client_for(tmp_path, monkeypatch, openalex, FakeAdapter())
    rid, run_id = start(client)
    wait(client, rid, run_id)
    stored = step_output(client, run_id, "search_query")
    model = next(q["query_text"] for q in stored["queries"] if q["origin"] == "model")
    assert model == '"synthetic setting" AND "synthetic task backup"'
    assert stored["vocabulary"]["search_query"]["meta"]["synthetic task backup"]["backup_for"] == "synthetic task"


def test_an_answer_that_breaks_a_bound_gets_one_repair(tmp_path, monkeypatch):
    sent = []

    def responder(si):
        if si["task_type"] != "search_query":
            return valid_response(si)
        sent.append(si)
        if len(sent) == 1:
            return json.dumps(envelope(si, "deixis.search_query.v1") | answer(
                ["s one", "s two", "s three"], ["t one", "t two", "t three", "t four"]))
        return valid_response(si)

    client = client_for(tmp_path, monkeypatch, OpenAlex(), FakeAdapter(responder))
    rid, run_id = start(client)
    _, run = wait(client, rid, run_id)
    assert run["status"] == "completed" and len(sent) == 2
    assert step_output(client, run_id, "search_query")["status"] == "ready"


def test_a_failed_model_stops_the_run_and_the_code_query_is_searched_only_when_the_user_says_so(tmp_path, monkeypatch):
    openalex = OpenAlex()
    adapter = FakeAdapter(fail=lambda si: ModelStepResult("failed", error="SYNTHETIC down")
                          if si["task_type"] == "search_query" else None)
    client = client_for(tmp_path, monkeypatch, openalex, adapter)
    rid, run_id = start(client)
    _, run = wait(client, rid, run_id)
    assert (run["status"], run["pause_reason"]) == ("paused", "search_query_failed")
    assert run["error"]["retries_left"] == 1
    assert not openalex.searches and not any(s["kind"].startswith("provider_search") for s in run["steps"])
    # Resuming asks the model once more; a second failure leaves no try.
    assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
    _, run = wait(client, rid, run_id, ("paused", "completed", "failed"))
    time.sleep(0.1)
    _, run = wait(client, rid, run_id)
    assert run["pause_reason"] == "search_query_failed" and run["error"]["retries_left"] == 0
    assert len(calls(adapter)) == 2
    assert client.post(f"/api/runs/{run_id}/resume").status_code == 409
    assert client.post(f"/api/runs/{run_id}/search-query-choice").status_code == 200
    _, run = wait(client, rid, run_id, ("completed", "failed"))
    assert run["status"] == "completed", run
    assert len(calls(adapter)) == 2 and openalex.searches
    body = protocol_body(client, rid)
    assert body["search_query"]["status"] == "failed" and body["search_query"]["choice"] == "code_only"
    assert [a["reason"] for a in body["search_query"]["attempts"]] == ["model_call_failed", "model_call_failed"]
    assert not any("origin" in q for q in body["compiled_queries"])


def test_the_code_query_choice_is_refused_on_a_run_that_did_not_stop_for_the_model(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch, OpenAlex(), FakeAdapter())
    rid, run_id = start(client)
    wait(client, rid, run_id)
    assert client.post(f"/api/runs/{run_id}/search-query-choice").status_code == 409


def test_the_card_shows_the_model_query_and_the_code_query_can_be_switched_off(tmp_path, monkeypatch):
    openalex, adapter = OpenAlex(), FakeAdapter()
    client = client_for(tmp_path, monkeypatch, openalex, adapter, approval="ask")
    rid, run_id = start(client)
    view, run = wait(client, rid, run_id)
    assert run["pause_reason"] == "protocol_approval_needed"
    card = client.get(f"/api/researches/{rid}").json()
    approval = next(r for r in card["runs"] if r["id"] == run_id)["approval"]
    side = approval["proposal"]["search_query"]
    assert side["status"] == "ready" and side["code_query"]["searched"] and side["code_query"]["available"]
    assert {t["phrase"]: t["kind"] for t in side["terms"]} == {"synthetic setting": "topic", "synthetic task": "topic"}
    assert {q["origin"] for q in approval["proposal"]["queries"]} == {"model", "code"}
    response = client.post(f"/api/runs/{run_id}/protocol-approval", json={"code_query": False})
    assert response.status_code == 200, response.text
    _, run = wait(client, rid, run_id, ("completed", "failed"))
    assert run["status"] == "completed", run
    body = protocol_body(client, rid)
    assert body["search_query"]["code_query_searched"] is False
    assert {q["origin"] for q in body["compiled_queries"]} == {"model"}
    assert body["approval"]["edited"] is True
    # The model was asked once, before the card; the approval and the resumed run asked nothing again.
    assert len(calls(adapter)) == 1


def test_the_code_query_switch_is_refused_where_no_model_wrote_the_query(tmp_path, monkeypatch):
    adapter = FakeAdapter(fail=lambda si: ModelStepResult("failed", error="SYNTHETIC down")
                          if si["task_type"] == "search_query" else None)
    client = client_for(tmp_path, monkeypatch, OpenAlex(), adapter, approval="ask")
    rid, run_id = start(client)
    wait(client, rid, run_id)
    client.post(f"/api/runs/{run_id}/resume")
    time.sleep(0.2)
    wait(client, rid, run_id)
    client.post(f"/api/runs/{run_id}/search-query-choice")
    _, run = wait(client, rid, run_id, ("paused",))
    assert run["pause_reason"] == "protocol_approval_needed"
    response = client.post(f"/api/runs/{run_id}/protocol-approval", json={"code_query": False})
    assert response.status_code == 422


def test_the_users_own_key_terms_are_searched_and_no_model_writes_a_query(tmp_path, monkeypatch):
    adapter = FakeAdapter()
    client = client_for(tmp_path, monkeypatch, OpenAlex(), adapter)
    rid, run_id = start(client, key_terms=KEY_TERMS)
    _, run = wait(client, rid, run_id)
    assert run["status"] == "completed", run
    assert not calls(adapter)
    assert step_output(client, run_id, "search_query")["status"] == "skipped"
    assert "search_query" not in protocol_body(client, rid)


def test_the_second_round_grows_from_the_model_query_s_own_records(tmp_path, monkeypatch):
    from deixis.workflow import flow as flow_module

    code_work = WORK | {"id": "https://openalex.org/W8", "doi": "https://doi.org/10.9/b",
                        "display_name": "SYNTHETIC record only the code query finds"}

    class TwoQueries(OpenAlex):
        def __call__(self, request):
            response = super().__call__(request)
            query = request.url.params.get("search.title_and_abstract")
            if request.url.params.get("select") != "id" and query != '"synthetic setting" AND "synthetic task"':
                return httpx.Response(200, json={"meta": {"count": 1}, "results": [code_work]})
            return response

    read = []
    candidates = flow_module.phrase_candidates.candidates
    monkeypatch.setattr(flow_module.phrase_candidates, "candidates",
                        lambda records, *rest: read.extend(r["title"] for r in records) or candidates(records, *rest))
    client = client_for(tmp_path, monkeypatch, TwoQueries(), FakeAdapter())
    rid, run_id = start(client)
    _, run = wait(client, rid, run_id)
    assert run["status"] == "completed", run
    assert read == [WORK["display_name"]]


def test_the_code_setting_makes_no_model_query_step(tmp_path, monkeypatch):
    setting = "code"
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    adapter = FakeAdapter()
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765, search_workflow="sw", search_query=setting,
                              protocol_approval="as_proposed", fulltext_fetch="off"),
                     adapters={"fake": adapter}, http_client=httpx.AsyncClient(transport=httpx.MockTransport(OpenAlex())),
                     fetcher=no_fetch, extra_hosts=("testserver",), trusted_clients=("testclient",))
    client = TestClient(app)
    client.__enter__()
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    rid, run_id = start(client)
    _, run = wait(client, rid, run_id)
    assert not calls(adapter) and "search_query" not in [s["operation_key"] for s in run["steps"]]
