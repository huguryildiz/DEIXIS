"""The model-written sw query: the contract of one call, what code checks and counts, and the run around it (D92).

Every question, term and count here is SYNTHETIC and from more than one field, OpenAlex is mocked and the model is
the fake adapter, so passing shows workflow behavior: which call is made, what is counted, what is searched and what
is recorded. It says nothing about whether a model writes a good query; that was measured on three questions with
one model (`notes/archive/sw/sw-model-query-experiment-2026-09-24/result.md`) and nowhere else.
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
from deixis.domain.skill import RUNTIME_FILES
from deixis.models.adapter import ModelStepResult
from deixis.providers.registry import CONNECTORS
from deixis.workflow.search import search_query
from fakes import FakeAdapter
from windows_env import WAIT_FACTOR

FIXTURES = Path(__file__).parent.parent / "fixtures" / "research"
STEP_INPUT = json.loads((FIXTURES / "step-inputs.json").read_text(encoding="utf-8"))["H_search_query"]


def term(phrase, kind="topic", why="SYNTHETIC reason"):
    return {"term": phrase, "kind": kind, "why": why}


def answer(setting, task, setting_backup=(), task_backup=()):
    return {"field": "synthetic field", "setting": [term(p) for p in setting], "task": [term(p) for p in task],
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
    assert contracts.SCHEMA_VERSIONS["SearchQuery"] == "deixis.search_query.v2"
    assert RUNTIME_FILES["search_query"] == ("SKILL.md", "references/search-query.md")
    assert "search_query" in LITERATURE_TASKS  # the literature model writes the query, as it labels blocks
    assert schema_repairs("search_query") == 1
    assert contracts.strict_compatibility_issues(contracts.step_output_schema("search_query")) == []


# ---- what code checks and counts ----------------------------------------------------------------------------

def test_a_term_that_finds_nothing_with_the_other_block_brings_its_backup_and_counts_run_four_at_a_time():
    # D154: "integer programming" finds records alone and none with the setting block, so the next task backup is
    # searched beside it; it stays, with its warning. The counts overlap, at most 4 out, and every row keeps its order.
    out, peak, asked = [0], [0], []

    async def count(query):
        asked.append(query)
        out[0] += 1
        peak[0] = max(peak[0], out[0])
        await asyncio.sleep(0.1)
        out[0] -= 1
        return 0 if query == '"integer programming" AND ("rail freight" OR "freight railway")' else 50
    model = answer(["rail freight", "freight railway"], ["timetable", "integer programming", "train dispatching"],
                   task_backup=["train scheduling", "crew rostering"])
    started = time.monotonic()
    checked = asyncio.run(search_query.check(model, count))
    elapsed = time.monotonic() - started
    setting, task = '("rail freight" OR "freight railway")', '(timetable OR "integer programming" OR "train dispatching")'
    wider = task[:-1] + ' OR "train scheduling")'
    assert asked == ['"rail freight"', '"freight railway"', 'timetable', '"integer programming"', '"train dispatching"',
                     f'"rail freight" AND {task}', f'"freight railway" AND {task}', f'timetable AND {setting}',
                     f'"integer programming" AND {setting}', f'"train dispatching" AND {setting}',
                     '"train scheduling"', f'"train scheduling" AND {setting}',
                     # the setting terms' counts are read again against the task block they are searched with
                     f'"rail freight" AND {wider}', f'"freight railway" AND {wider}', f"{setting} AND {wider}"]
    assert [p["query"] for p in checked["probes"]] == asked  # the record follows the order the queries were asked in
    assert 1 < peak[0] <= 4 and elapsed < 0.1 * len(asked) * 0.75
    assert [(c["phrase"], c["with_other_block"], c["backup_for"]) for c in checked["checks"]] == [
        ("rail freight", 50, None), ("freight railway", 50, None), ("timetable", 50, None),
        ("integer programming", 0, None), ("train dispatching", 50, None), ("train scheduling", 50, "integer programming")]
    assert checked["checks"][-1]["used_because"] == search_query.ZERO_WITH_OTHER
    assert [t["phrase"] for t in checked["terms"] if not t["dropped"]] == [
        "rail freight", "freight railway", "timetable", "integer programming", "train dispatching", "train scheduling"]
    assert checked["meta"]["train scheduling"] == {"kind": None, "why": None, "backup_for": "integer programming",
                                                   "used_because": search_query.ZERO_WITH_OTHER}
    assert checked["backups_left"] == {"setting": [], "task": ["crew rostering"]}
    assert checked["warnings"] == [{"phrase": "integer programming", "block": "task",
                                    "warning": "no_records_with_other_block"}]
    assert checked["searchable"] and checked["gate_count"] == 50


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


def client_for(tmp_path, monkeypatch, handler, adapter, setting="model", method="legacy"):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765, search_query=setting,
                              fulltext_fetch="off", search_method=method),
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
    deadline = time.time() + 15 * WAIT_FACTOR
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
    # The prompt version is the one the model was sent, read from its StepInput and not from the package at freeze.
    assert body["search_query"]["prompt"] == {"files": ["SKILL.md", "references/search-query.md"],
                                              "schema_version": "deixis.search_query.v2",
                                              "skill_package_hash": calls(adapter)[0]["skill_package_hash"]}
    assert body["search_query"]["answer"]["setting"][0]["term"] == "synthetic setting"
    assert {q.get("origin") for q in body["compiled_queries"]} == {"model", "code"}
    assert body["concept_blocks"] == {"setting": ["synthetic setting"], "task": ["synthetic task"]}
    # The run was given the model-query calls on top of its preset.
    preset = TEST_EFFORT_BUDGETS["quick"].max_model_calls
    assert run["budget"]["max_model_calls"] - preset >= SEARCH_QUERY_CALLS


class EveryCount(dict):
    """A count table in which every query matches the same number of works."""

    def __init__(self, value):
        super().__init__()
        self.value = value

    def get(self, key, default=None):
        return self.value

    def __bool__(self):
        return True


def test_under_the_m1_method_a_code_query_wider_than_its_limit_or_on_one_block_is_not_searched(tmp_path, monkeypatch):
    from deixis.workflow.search import chaining

    # Every count is 300,000: the code's gate query cannot be narrowed below it, and no term reaches the one-million
    # rule. A `legacy` run searches the code's query beside the model's as before; an `m1` run leaves it out (D163 M1).
    runs = {}
    for method in ("legacy", "m1"):
        openalex = OpenAlex(counts=EveryCount(300_000))
        client = client_for(tmp_path / method, monkeypatch, openalex, FakeAdapter(), method=method)
        rid, run_id = start(client)
        _, run = wait(client, rid, run_id)
        assert run["status"] == "completed", run
        runs[method] = (step_output(client, run_id, "search_query"), protocol_body(client, rid), run)
    legacy, m1 = runs["legacy"], runs["m1"]
    assert "code" in {q["origin"] for q in legacy[0]["queries"]}
    assert "left_out" not in legacy[0]["vocabulary"]["code_query"]
    assert legacy[2]["budget"]["fast_path"]["chain_rule"] == "fast_chain_v1"
    assert "search_method" not in legacy[2]["budget"]["fast_path"]
    assert "admission_forms" not in legacy[1]["citation_chaining"]

    stored, body, run = m1
    assert stored["vocabulary"]["code_query"]["vocabulary"]["gate_count"] == 300_000
    assert stored["vocabulary"]["code_query"]["searched"] is False
    assert stored["vocabulary"]["code_query"]["left_out"] == "too_wide"
    assert {q["origin"] for q in stored["queries"]} == {"model"}
    assert body["search_query"]["code_query_searched"] is False
    # No code term reaches the ranking blocks or the chain forms; the selection is frozen in the body's budget.
    assert body["concept_blocks"] == {"setting": ["synthetic setting"], "task": ["synthetic task"]}
    assert body["budget"]["fast_path"]["search_method"] == "m1"
    frozen = body["citation_chaining"]
    assert frozen["rule_version"] == "fast_chain_v2"
    assert frozen["admission_forms_sha256"] == chaining.forms_digest(frozen["admission_forms"])
    assert " synthetic setting" in frozen["admission_forms"]["setting"]

    # A code query whose setting block lost every term is a one-block query: left out whatever its count.
    one_block = code_vocabulary()
    one_block["terms"][0]["dropped"] = "zero_results"
    count, _ = counter({})
    checked = asyncio.run(search_query.check(answer(["rail freight"], ["timetable"]), count))
    built = search_query.vocabulary(one_block, CODE_QUERIES, checked, {"status": "ready", "attempts": [],
                                    "step_input_id": "sti_x", "resolved_model": "m", "answer": {}}, 250_000)
    assert built["code_query"]["searched"] is False and built["code_query"]["left_out"] == "one_block"


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


def test_the_users_own_key_terms_are_searched_and_no_model_writes_a_query(tmp_path, monkeypatch):
    adapter = FakeAdapter()
    client = client_for(tmp_path, monkeypatch, OpenAlex(), adapter)
    rid, run_id = start(client, key_terms=KEY_TERMS)
    _, run = wait(client, rid, run_id)
    assert run["status"] == "completed", run
    assert not calls(adapter)
    assert step_output(client, run_id, "search_query")["status"] == "skipped"
    assert "search_query" not in protocol_body(client, rid)


# ---- review of 2026-09-23 (gpt-6-sol high) -----------------------------------------------------------------------


def test_a_run_reuses_only_a_query_written_under_its_own_search_method(tmp_path, monkeypatch):
    # D163 M1: a stored query carries the code-query decision of the method it was written under. A legacy run's
    # query is not reused by an m1 run of the same scope revision; the m1 run asks once and applies its own limit.
    legacy_adapter, m1_adapter = FakeAdapter(), FakeAdapter()
    client = client_for(tmp_path, monkeypatch, OpenAlex(counts=EveryCount(300_000)), legacy_adapter)
    rid, first = start(client)
    assert wait(client, rid, first)[1]["status"] == "completed"
    client.__exit__(None, None, None)
    client = client_for(tmp_path, monkeypatch, OpenAlex(counts=EveryCount(300_000)), m1_adapter, method="m1")
    second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    _, run = wait(client, rid, second)
    assert run["status"] == "completed", run
    stored = step_output(client, second, "search_query")
    assert "reused_from_run" not in stored and len(calls(m1_adapter)) == 1
    assert stored["vocabulary"]["code_query"]["left_out"] == "too_wide"
    client.__exit__(None, None, None)
    # A legacy run after the m1 one takes the first legacy query, as before M1: no model call.
    client = client_for(tmp_path, monkeypatch, OpenAlex(counts=EveryCount(300_000)), legacy_adapter)
    third = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    assert wait(client, rid, third)[1]["status"] == "completed"
    assert step_output(client, third, "search_query")["reused_from_run"] == first and len(calls(legacy_adapter)) == 1
