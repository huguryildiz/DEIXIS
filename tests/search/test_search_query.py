"""The model-written sw query: the contract of one call, what code checks and counts, and the run around it.

Every question, term and count here is SYNTHETIC and from more than one field, OpenAlex is mocked and the model is
the fake adapter, so passing shows workflow behavior: which call is made, what is counted, what is searched and what
is recorded. It says nothing about whether a model writes a good query; that was measured on three questions with
one model (`notes/archive/sw/sw-model-query-experiment-2026-09-24/result.md`) and nowhere else.
"""

import asyncio
import json
import sqlite3
import time
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.runtime.config import Settings
from deixis.domain import contracts
from deixis.domain.rules import LITERATURE_TASKS, SEARCH_QUERY_CALLS, TEST_EFFORT_BUDGETS, schema_repairs
from deixis.domain.skill import RUNTIME_FILES
from deixis.models.adapter import ModelStepResult
from deixis.providers.registry import CONNECTORS
from deixis.workflow.search import search_query
from deixis.workflow.search import search as fast_search
from fakes import FakeAdapter, valid_response
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
    # "integer programming" finds records alone and none with the setting block, so the next task backup is
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


def test_under_the_forms_rule_a_term_is_counted_as_before_and_only_the_whole_query_carries_the_forms():
    # A term keeps or loses its place on the same counts as before the rule; the forms are added only when the query
    # is compiled, and the whole-query count is that compiled text. The forms are read from the terms' own spelling,
    # so the acronym in "graph BERT" gets none although the stored phrase is lower-cased.
    model = answer(["Mixture of Experts", "graph BERT"], ["differentiable", "time series"])
    setting, task = '("mixture of experts" OR "graph bert")', '(differentiable OR "time series")'
    before = ['"mixture of experts"', '"graph bert"', "differentiable", '"time series"',
              f'"mixture of experts" AND {task}', f'"graph bert" AND {task}', f"differentiable AND {setting}",
              f'"time series" AND {setting}']
    count, asked = counter({})
    checked = asyncio.run(search_query.check(model, count, phrase_forms=True))
    sent = '("mixture of experts" OR "mixtures of experts" OR "graph bert") AND (differentiable OR "time series")'
    assert asked == before + [sent]
    built = search_query.vocabulary({"language": "en"}, checked, {"origin": "model"}, question_words=False)
    queries = search_query.compile_queries(built, ["openalex"], 1)
    assert [query["query_text"] for query in queries] == [sent] and "berts" not in sent
    built = search_query.with_compiled(built, queries)
    forms = built["phrase_forms"]
    assert (forms["rule"], forms["counts"]) == (search_query.query_compiler.PHRASE_FORMS_RULE, "without_variants")
    # Each phrase says what the compiled query did with its form.
    assert [(row["phrase"], row["variant"], row["searched"], row["left_out"]) for row in forms["terms"]] == [
        ("mixture of experts", "mixtures of experts", True, None), ("graph bert", None, False, "no_variant"),
        ("time series", None, False, "no_variant")]
    # A plan counted before the rule: the same term counts, its own whole-query count, no forms anywhere.
    old_count, old_asked = counter({})
    old = asyncio.run(search_query.check(model, old_count))
    assert old_asked == before + [f"{setting} AND {task}"]
    old_built = search_query.vocabulary({"language": "en"}, old, {"origin": "model"}, question_words=False)
    assert "phrase_forms" not in old and "phrase_forms" not in old_built
    (old_query,) = search_query.compile_queries(old_built, ["openalex"], 1)
    assert old_query["query_text"] == f"{setting} AND {task}" and "phrase_forms" not in old_query


# ---- the proposal, its queries and its correction ------------------------------------------------------------

def code_vocabulary(too_broad=False):
    return {"language": "en", "block_assignment": "rule",
            "terms": [{"phrase": "rail networks", "block": "setting", "origin": "question", "root": "rail",
                       "in_query": "root", "phrase_count": 90, "root_count": 900, "and_only": False, "dropped": None},
                      {"phrase": "timetabling", "block": "task", "origin": "question", "root": "timetabling",
                       "in_query": "root", "phrase_count": 80, "root_count": 80, "and_only": False, "dropped": None}],
            "claim_words": ["integer programming"], "exclusion_words": ["survey"], "outcome_terms": ["delay"],
            "gate_count": 40, "probes": [], "probes_skipped": 0, "too_broad": too_broad}


def proposal(model_answer=None, counts=None, too_broad=False):
    count, _ = counter(counts or {})
    checked = asyncio.run(search_query.check(model_answer or answer(["rail freight"], ["timetable", "integer programming"]),
                                             count))
    return search_query.vocabulary(code_vocabulary(too_broad), checked,
                                   {"status": "ready", "attempts": [], "step_input_id": "sti_x", "resolved_model": "m",
                                    "answer": {}})



def test_the_questions_own_words_are_kept_beside_the_models_terms_and_read_from_an_older_record():
    """What gates and orders records: the plan's terms and the question's own words beside them.

    A research searched before the question's own code query was removed kept the same words under that query's
    record, and only a query that really was searched counts, so what gated its records does not change.
    """
    built = proposal()
    assert search_query.question_vocabulary(built) == code_vocabulary()
    assert [t["phrase"] for t in search_query.question_terms(built)] == ["rail networks", "timetabling"]
    # A vocabulary that is itself the question's own has none beside it, so its words are not counted twice.
    assert search_query.question_vocabulary(code_vocabulary()) is None and search_query.question_terms(code_vocabulary()) == []
    # An older research: the words come from that query's record, and only where it was searched.
    stored = {"terms": [], "code_query": {"vocabulary": code_vocabulary(), "queries": [{"query_text": "x"}], "searched": True}}
    assert [t["phrase"] for t in search_query.question_terms(stored)] == ["rail networks", "timetabling"]
    left_out = {"terms": [], "code_query": {"vocabulary": code_vocabulary(), "queries": [], "searched": False,
                                            "left_out": "too_wide"}}
    assert search_query.question_vocabulary(left_out) is None and search_query.question_terms(left_out) == []


def test_an_older_researchs_own_second_query_is_compiled_again_and_settled_as_it_was():
    """A research searched before the question's own code query was removed keeps that round: the stored query is
    placed after the plan's query of the same provider, and `settled` reads back whether it really was compiled."""
    older = {k: v for k, v in proposal().items() if k != "question_vocabulary"}  # the key did not exist then
    stored = older | {"code_query": {
        "vocabulary": code_vocabulary(), "searched": True,
        "queries": [{"provider_id": p, "query_text": f"{p}: rail AND timetabling", "rationale": "Concept blocks",
                     "dropped_terms": []} for p in ("openalex", "semantic_scholar")]}}
    queries = search_query.compile_queries(stored, ["openalex", "semantic_scholar"], 8)
    assert [(q["provider_id"], q["origin"]) for q in queries] == [
        ("openalex", "model"), ("openalex", "code"), ("semantic_scholar", "model"), ("semantic_scholar", "code")]
    # Written before `compiled` existed: it is read back from the queries, and the words it carried still gate.
    settled = search_query.settled(stored, queries)
    assert settled["code_query"]["compiled"] is True
    assert [t["phrase"] for t in search_query.question_terms(settled)] == ["rail networks", "timetabling"]
    # A round the request limit left that query out of: its words gated nothing then, and they gate nothing now.
    cut = search_query.settled(stored, [q for q in queries if q["origin"] != "code"])
    assert cut["code_query"]["compiled"] is False and search_query.question_terms(cut) == []

# ---- the run around it ---------------------------------------------------------------------------------------

QUESTION = "SYNTHETIC: which scheduling methods have been proposed for rail freight timetables?"
KEY_TERMS = "rail freight; timetable"
WORK = {"id": "https://openalex.org/W9", "doi": "https://doi.org/10.9/a",
        "display_name": "SYNTHETIC rail freight timetable scheduling", "publication_year": 2024, "type": "article",
        "authorships": [], "abstract_inverted_index": {"We": [0], "schedule": [1], "trains.": [2]}}


class OpenAlex:
    """Mocked OpenAlex: counts from a table (default 50), every search one record."""

    def __init__(self, counts=None):
        self.table, self.counts, self.searches, self.semantic = counts or {}, [], [], []
        self.plain = []  # the short phrases sent to the plain `search=` route, kept apart from the keyword searches

    def __call__(self, request):
        if request.url.host != "api.openalex.org":
            return httpx.Response(404)
        params = request.url.params
        query = params.get("search.title_abstract_keywords")
        if params.get("per_page") == "1" and params.get("select") == "id":
            self.counts.append(query)
            return httpx.Response(200, json={"meta": {"count": self.table.get(query, 50)}, "results": []})
        if params.get("search.semantic"):
            self.semantic.append(params["search.semantic"])
        elif params.get("search") is not None:
            self.plain.append(params["search"])
        else:
            self.searches.append(query)
        return httpx.Response(200, json={"meta": {"count": 1}, "results": [WORK]})


async def no_fetch(url):
    from deixis.documents.fetch import FetchResult
    return FetchResult("http_error", final_url=url, http_status=404)


def client_for(tmp_path, monkeypatch, handler, adapter):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765, fulltext_fetch="off"),
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


def calls(adapter, task="search_plan"):
    return [si for si in adapter.calls if si["task_type"] == task]


def test_the_model_writes_the_query_and_it_is_the_only_keyword_query_of_the_round(tmp_path, monkeypatch):
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
    # Nothing code compiled from the question's own words is sent beside it: every query of the round is the model's.
    assert origins[0] == ("openalex", "model") and {o for _, o in origins} == {"model"}
    assert "synthetic AND schedule" in openalex.searches
    body = protocol_body(client, rid)
    assert body["search_query"]["status"] == "ready"
    # The prompt version is the one the model was sent, read from its StepInput and not from the package at freeze.
    assert body["search_query"]["prompt"] == {"files": ["SKILL.md", "references/search-plan.md"],
                                              "schema_version": "deixis.search_plan.v2",
                                              "skill_package_hash": calls(adapter)[0]["skill_package_hash"]}
    assert body["search_query"]["answer"]["setting"][0]["term"] == "SYNTHETIC"
    assert {q.get("origin") for q in body["compiled_queries"]} == {"model"}
    assert body["concept_blocks"] == {"setting": ["synthetic"], "task": ["schedule"]}
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


def test_a_run_freezes_its_chain_rule_and_admission_forms_before_it_searches(tmp_path, monkeypatch):
    from deixis.workflow.search import chaining

    # Every count is 300,000, so no term reaches the one-million rule and the run searches the model's query.
    openalex = OpenAlex(counts=EveryCount(300_000))
    client = client_for(tmp_path, monkeypatch, openalex, FakeAdapter())
    rid, run_id = start(client)
    _, run = wait(client, rid, run_id)
    assert run["status"] == "completed", run
    stored, body = step_output(client, run_id, "search_query"), protocol_body(client, rid)
    # The question's own words are kept beside the model's terms with their counts, and nothing searches them.
    assert stored["vocabulary"]["question_vocabulary"]["gate_count"] == 300_000
    assert {q["origin"] for q in stored["queries"]} == {"model"}
    # Only what was searched stands in the ranking blocks; the selection is frozen in the body's budget.
    assert body["concept_blocks"] == {"setting": ["synthetic"], "task": ["schedule"]}
    assert run["budget"]["fast_path"]["chain_rule"] == chaining.RULE_V3
    frozen = body["citation_chaining"]
    assert frozen["rule_version"] == chaining.RULE_V3
    assert frozen["admission_forms_sha256"] == chaining.forms_digest(frozen["admission_forms"])
    assert " synthetic" in frozen["admission_forms"]["setting"]


def test_a_failed_model_stops_the_run_and_no_query_is_searched_in_its_place(tmp_path, monkeypatch):
    openalex = OpenAlex()
    adapter = FakeAdapter(fail=lambda si: ModelStepResult("failed", error="SYNTHETIC down")
                          if si["task_type"] == "search_plan" else None)
    client = client_for(tmp_path, monkeypatch, openalex, adapter)
    rid, run_id = start(client)
    _, run = wait(client, rid, run_id)
    assert (run["status"], run["pause_reason"]) == ("paused", "search_query_failed")
    assert run["error"]["retries_left"] == 1
    # No query the model would have written was searched. The question's own semantic request went out before the
    # model was asked at all (P2), so its step is the one provider search of the plan this paused run holds; the short
    # phrase searches beside the plan follow it and wait for no plan.
    assert not openalex.searches and openalex.semantic[0] == QUESTION and openalex.semantic.count(QUESTION) == 1
    assert [s["operation_key"] for s in run["steps"] if s["kind"].startswith("provider_search")
            and not s["operation_key"].startswith((fast_search.PHRASE_KEY, fast_search.PLAIN_PHRASE_KEY))] == [
        "search:fast:semantic"]
    # Resuming asks the model once more; a second failure leaves no try.
    assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
    _, run = wait(client, rid, run_id, ("paused", "completed", "failed"))
    time.sleep(0.1)
    _, run = wait(client, rid, run_id)
    assert run["pause_reason"] == "search_query_failed" and run["error"]["retries_left"] == 0
    assert len(calls(adapter)) == 2
    # No try left and no way around the model: the run stays paused, and the way on is a new scope revision. Code
    # compiles no query of its own, so there is nothing to search in the model's place.
    assert client.post(f"/api/runs/{run_id}/resume").status_code == 409
    # The question's own request went once, and no short phrase was sent twice; how many went out before each stop
    # depends on when the planning step failed.
    assert not openalex.searches and openalex.semantic.count(QUESTION) == 1
    assert len(set(openalex.semantic)) == len(openalex.semantic) <= 7
    assert len(calls(adapter)) == 2


def test_the_users_own_key_terms_are_searched_and_no_model_writes_a_query(tmp_path, monkeypatch):
    adapter = FakeAdapter()
    client = client_for(tmp_path, monkeypatch, OpenAlex(), adapter)
    rid, run_id = start(client, key_terms=KEY_TERMS)
    _, run = wait(client, rid, run_id)
    assert run["status"] == "completed", run
    assert not calls(adapter)
    assert step_output(client, run_id, "search_query")["status"] == "skipped"
    assert "search_query" not in protocol_body(client, rid)


def phrase_plan(si):
    """The fake's plan with its setting term replaced by the phrase "rail freight", read from the record's title."""
    body = json.loads(valid_response(si))
    if si["task_type"] == "search_plan":
        record = si["sources"][0]
        start = record["title"].index("rail freight")
        body["setting"] = [{"term": "rail freight", "kind": "topic", "why": "SYNTHETIC setting term",
                            "evidence": {"record_id": record["source_id"], "field": "title",
                                         "span": [start, start + len("rail freight")],
                                         "relation": "SYNTHETIC relation to the question"}}]
    return json.dumps(body)


def test_a_run_frozen_before_the_forms_rule_counts_and_compiles_its_plan_the_old_way_on_resume(tmp_path, monkeypatch):
    # The run's first plan call fails and it pauses before any count is read; it is resumed under this version.
    # Its frozen policy names no forms rule, so the resumed plan is counted and compiled exactly as before. A run
    # queued now, on the same question, searches the plural beside the phrase.
    from deixis.domain import canonical
    from deixis.workflow.run import fast_path
    freeze, old = fast_path.freeze_budget, [True]

    def frozen(*args, **kwargs):
        policy = freeze(*args, **kwargs)
        if old[0]:
            policy = {k: v for k, v in policy.items() if k not in ("policy_hash", "phrase_forms_rule")}
            policy["policy_hash"] = canonical.sha256_hex(policy)
        return policy
    monkeypatch.setattr(fast_path, "freeze_budget", frozen)
    failed = []

    def fail_once(si):
        if si["task_type"] == "search_plan" and not failed:
            failed.append(si)
            return ModelStepResult("failed", error="SYNTHETIC down")
        return None
    openalex = OpenAlex()
    client = client_for(tmp_path, monkeypatch, openalex, FakeAdapter(phrase_plan, fail=fail_once))
    rid, run_id = start(client)
    _, run = wait(client, rid, run_id)
    assert (run["status"], run["pause_reason"]) == ("paused", "search_query_failed")
    assert not any("rail freight" == query.strip('"') for query in openalex.counts)  # the plan was not counted yet
    assert "phrase_forms_rule" not in run["budget"]["fast_path"]
    assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
    _, run = wait(client, rid, run_id, ("completed", "failed"))
    assert run["status"] == "completed", run
    stored = step_output(client, run_id, "search_query")
    assert "phrase_forms" not in stored["vocabulary"] and stored["queries"][0]["query_text"] == '"rail freight" AND schedule'
    assert not any("rail freights" in query for query in openalex.counts + openalex.searches)
    old[0] = False
    rid, run_id = start(client)
    _, run = wait(client, rid, run_id)
    assert run["status"] == "completed", run
    assert run["budget"]["fast_path"]["phrase_forms_rule"] == search_query.query_compiler.PHRASE_FORMS_RULE
    stored = step_output(client, run_id, "search_query")
    assert stored["queries"][0]["query_text"] == '("rail freight" OR "rail freights") AND schedule'
    assert stored["vocabulary"]["phrase_forms"]["terms"] == [
        {"phrase": "rail freight", "block": "setting", "variant": "rail freights", "searched": True, "left_out": None}]


def test_a_source_routing_recompile_of_a_plan_counted_before_the_rule_gives_its_old_text():
    from deixis.workflow.run.flow import ResearchFlow
    model = answer(["mixture of experts"], ["differentiable"])
    count, _ = counter({})
    checked = asyncio.run(search_query.check(model, count))
    vocabulary = search_query.vocabulary({"language": "en"}, checked, {"origin": "model"}, question_words=False)
    budget = {"max_provider_requests": 4, "fast_path": {"boolean_plans": 1}}
    built, compiled = ResearchFlow._compiled(None, vocabulary, ["openalex"], budget)
    assert [query["query_text"] for query in compiled] == ['"mixture of experts" AND differentiable']
    assert "phrase_forms" not in built and "phrase_forms" not in compiled[0]


def test_a_newer_query_under_the_other_forms_rule_does_not_hide_an_older_one_this_run_can_reuse(tmp_path, monkeypatch):
    # A wrote its query before the forms rule, B after it; C, frozen before the rule, reuses A's query and asks the
    # model nothing, although B's is the newest of the scope revision.
    from deixis.domain import canonical
    from deixis.workflow.run import fast_path
    freeze, old = fast_path.freeze_budget, [True]

    def frozen(*args, **kwargs):
        policy = freeze(*args, **kwargs)
        if old[0]:
            policy = {k: v for k, v in policy.items() if k not in ("policy_hash", "phrase_forms_rule")}
            policy["policy_hash"] = canonical.sha256_hex(policy)
        return policy
    monkeypatch.setattr(fast_path, "freeze_budget", frozen)
    adapter = FakeAdapter()
    client = client_for(tmp_path, monkeypatch, OpenAlex(), adapter)
    rid, first = start(client)
    assert wait(client, rid, first)[1]["status"] == "completed"
    old[0] = False
    second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    assert wait(client, rid, second)[1]["status"] == "completed"
    # B, under the rule, does not take A's query and writes its own.
    assert "reused_from_run" not in step_output(client, second, "search_query") and len(calls(adapter)) == 2
    assert "phrase_forms" in step_output(client, second, "search_query")["vocabulary"]
    old[0] = True
    third = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    _, run = wait(client, rid, third)
    assert run["status"] == "completed", run
    stored = step_output(client, third, "search_query")
    assert stored["reused_from_run"] == first and len(calls(adapter)) == 2
    assert "phrase_forms" not in stored["vocabulary"]


def test_under_the_forms_rule_the_routing_distribution_is_read_for_the_query_the_search_sends():
    # The field distribution is asked for the OpenAlex text the compiler writes, forms included; a plan counted
    # before the rule is asked for its old gate query.
    from deixis.workflow.search import routing
    model = answer(["mixture of experts"], ["load balancing"])
    count, _ = counter({})
    checked = asyncio.run(search_query.check(model, count, phrase_forms=True))
    built = search_query.vocabulary({"language": "en"}, checked, {"origin": "model"}, question_words=False)
    (sent,) = search_query.compile_queries(built, ["openalex"], 1)
    assert routing.gate_query(built) == sent["query_text"] == (
        '("mixture of experts" OR "mixtures of experts") AND "load balancing"')
    old = asyncio.run(search_query.check(model, counter({})[0]))
    old_built = search_query.vocabulary({"language": "en"}, old, {"origin": "model"}, question_words=False)
    assert routing.gate_query(old_built) == '("mixture of experts") AND ("load balancing")'


# ---- review of 2026-09-23 (gpt-6-sol high) -----------------------------------------------------------------------


def test_a_run_reuses_only_a_query_written_under_its_own_plan_rule(tmp_path, monkeypatch):
    # A stored query carries the decisions of the plan rule it was written under. A second run of the same scope
    # revision reuses it, and a query written under another rule is not reused: that run asks once and freezes
    # its own.
    adapter = FakeAdapter()
    client = client_for(tmp_path, monkeypatch, OpenAlex(counts=EveryCount(300_000)), adapter)
    rid, first = start(client)
    assert wait(client, rid, first)[1]["status"] == "completed"
    second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    assert wait(client, rid, second)[1]["status"] == "completed"
    assert step_output(client, second, "search_query")["reused_from_run"] == first and len(calls(adapter)) == 1
    client.__exit__(None, None, None)
    # The stored query now says it was written under another plan rule, so the next run does not take it.
    with sqlite3.connect(tmp_path / "data" / "library.sqlite") as conn:
        for run_id in (first, second):
            budget = json.loads(conn.execute("SELECT budget_json FROM runs WHERE id = ?", (run_id,)).fetchone()[0])
            budget["fast_path"]["plan_rule"] = "SYNTHETIC_older_rule"
            conn.execute("UPDATE runs SET budget_json = ? WHERE id = ?", (json.dumps(budget), run_id))
    client = client_for(tmp_path, monkeypatch, OpenAlex(counts=EveryCount(300_000)), adapter)
    third = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    _, run = wait(client, rid, third)
    assert run["status"] == "completed", run
    stored = step_output(client, third, "search_query")
    assert "reused_from_run" not in stored and len(calls(adapter)) == 2
    assert stored["vocabulary"]["question_vocabulary"]["gate_count"] == 300_000
