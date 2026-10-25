"""A search plan the person edited (UI parity S23a, F18): saved as a scope revision, searched without the three model
planning calls, approved as `user_edited`, frozen before the first result fetch, and no request to a provider the
person left out.

Every question, record and count is SYNTHETIC; OpenAlex, Semantic Scholar, Crossref and Scopus are one mocked
transport that logs every request, and the model is the fake adapter. Passing shows workflow behavior (which calls
are made, what is sent, what is recorded), not whether an edited plan finds better works.
"""

import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.providers.registry import CONNECTORS
from fakes import FakeAdapter

QUESTION = "SYNTHETIC: which scheduling methods have been proposed for rail freight timetables?"
PLANNING_TASKS = ("vocabulary_labels", "search_query", "criterion_proposal")


def work(n, abstract=True):
    return {"id": f"https://openalex.org/W{n}", "doi": f"https://doi.org/10.9/synthetic.{n}",
            "display_name": f"SYNTHETIC rail freight timetable scheduling {n}", "publication_year": 2024,
            "type": "article", "authorships": [],
            **({"abstract_inverted_index": {"We": [0], "schedule": [1], "trains.": [2]}} if abstract else {})}


class Providers:
    """Every provider on one transport. OpenAlex: counts from a table (default 50), every result page two works,
    one without an abstract (so it is looked up elsewhere). The others answer with nothing found."""

    def __init__(self, counts=None, events=None):
        self.table, self.log = counts or {}, []
        self.events = events if events is not None else []
        self.searches, self.counts = [], []

    def hosts(self, host):
        return [entry for entry in self.log if entry[0] == host]

    def __call__(self, request):
        host, params = request.url.host, request.url.params
        if host == "api.openalex.org":
            query = params.get("search.title_and_abstract")
            if params.get("per_page") == "1" and params.get("select") == "id":
                self.log.append((host, "count"))
                self.counts.append(query)
                return httpx.Response(200, json={"meta": {"count": self.table.get(query, 50)}, "results": []})
            kind = "group_by" if params.get("group_by") else "fetch"
            self.log.append((host, kind))
            self.events.append(kind)
            if query:
                self.searches.append(query)
            return httpx.Response(200, json={"meta": {"count": 2, "next_cursor": None},
                                             "results": [work(1), work(2, abstract=False)]})
        self.log.append((host, request.method))
        self.events.append(host)
        if host == "api.semanticscholar.org":
            if request.url.path.endswith("/batch"):
                return httpx.Response(200, json=[None for _ in json.loads(request.content)["ids"]])
            return httpx.Response(200, json={"total": 0, "data": []})
        if host == "api.elsevier.com":
            return httpx.Response(401, json={})
        return httpx.Response(404)


async def no_fetch(url):
    from deixis.documents.fetch import FetchResult
    return FetchResult("http_error", final_url=url, http_status=404)


def client_for(tmp_path, monkeypatch, handler, adapter):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    # Scopus in scope and configured, so a run that may ask it would send its access check.
    monkeypatch.setenv(CONNECTORS["scopus"].key_env, "SYNTHETIC-scopus-key")
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765, fulltext_fetch="off"),
                     adapters={"fake": adapter}, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                     fetcher=no_fetch, extra_hosts=("testserver",), trusted_clients=("testclient",))
    client = TestClient(app)
    client.__enter__()
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    return client


def create(client, effort="quick"):
    response = client.post("/api/researches", json={"question": QUESTION, "model_connection": "fake",
                                                    "requested_model": "fake-model", "effort": effort})
    assert response.status_code == 201, response.text
    return response.json()["research"]["id"]


def discover(client, rid):
    response = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"})
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    deadline = time.time() + 20
    while time.time() < deadline:
        run = next(r for r in client.get(f"/api/researches/{rid}").json()["runs"] if r["id"] == run_id)
        if run["status"] in ("completed", "failed", "paused"):
            return run
        time.sleep(0.05)
    raise AssertionError("the run did not settle")


def version(client, rid):
    return client.get(f"/api/researches/{rid}").json()["research"]["version"]


def plan(providers=("openalex",), **changes):
    body = {"schema_version": "deixis.user_search_plan.v1",
            "setting": [{"term": "rail freight"}],
            "task": [{"term": "timetable scheduling"}, {"term": "train dispatching"}],
            "setting_backup": [], "task_backup": [{"term": "crew rostering"}],
            "criterion": {"text": "SYNTHETIC: the paper proposes a method that schedules rail freight timetables.",
                          "parts": [{"name": "scheduling method", "definition": "A method that builds a timetable.",
                                     "role": "core", "phrases": ["timetable", "freight train scheduling"]}],
                          "exclusion_title_words": ["survey"], "question_elements": [], "required_roles": []},
            "providers": list(providers)}
    return body | changes


def save(client, rid, body):
    return client.post(f"/api/researches/{rid}/search-plan", json={"expected_version": version(client, rid), "plan": body})


def protocols(client, rid):
    return [json.loads(row[0]) for row in client.app.state.store.conn.execute(
        "SELECT body_json FROM protocol_records WHERE research_id = ? ORDER BY protocol_revision", (rid,))]


def step_output(client, run_id, key):
    row = client.app.state.store.conn.execute(
        "SELECT output_json FROM run_steps WHERE run_id = ? AND operation_key = ?", (run_id, key)).fetchone()
    return json.loads(row[0]) if row and row[0] else None


def planning_calls(adapter, revision):
    return [si["task_type"] for si in adapter.calls
            if si["task_type"] in PLANNING_TASKS and si["scope_revision"] == revision]


# ---- saving -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("change", "code"), [
    ({"task": [{"term": "timetable AND dispatching"}]}, "query_syntax_in_term"),
    pytest.param({"providers": ["semantic_scholar", "crossref"]}, "openalex_required", id="change5-openalex_required"),
])
def test_a_plan_that_breaks_a_rule_is_refused_with_the_reason_and_nothing_is_saved(tmp_path, monkeypatch, change, code):
    client = client_for(tmp_path, monkeypatch, Providers(), FakeAdapter())
    rid = create(client)
    before = client.get(f"/api/researches/{rid}").json()["research"]["current_scope_revision"]
    response = save(client, rid, plan(**change))
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "invalid_search_plan"
    assert code in {issue["code"] for issue in response.json()["issues"]}
    assert client.get(f"/api/researches/{rid}").json()["research"]["current_scope_revision"] == before


def test_a_stale_version_is_a_conflict(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch, Providers(), FakeAdapter())
    rid = create(client)
    response = client.post(f"/api/researches/{rid}/search-plan",
                           json={"expected_version": version(client, rid) - 1, "plan": plan()})
    assert response.status_code == 409


# ---- the run of a saved plan ---------------------------------------------------------------------------------------

def test_a_saved_plan_is_searched_without_the_three_planning_calls_and_recorded_as_user_edited(tmp_path, monkeypatch):
    providers, adapter = Providers(), FakeAdapter()
    client = client_for(tmp_path, monkeypatch, providers, adapter)
    rid = create(client)
    first = discover(client, rid)
    assert first["status"] == "completed", first
    # The model-made plan the panel starts from: the model's query, the code's beside it, read-only.
    view = client.get(f"/api/researches/{rid}/search-plan").json()
    assert view["origin"] == "model" and view["plan"]["providers"][0] == "openalex"
    assert [(q["label"], q["origin"]) for q in view["queries"]] == [("Query 1", "model"), ("Query 2", "code")]
    assert {p["provider_id"]: p["required"] for p in view["providers"]}["openalex"] is True
    assert set(planning_calls(adapter, 1)) == set(PLANNING_TASKS)

    saved = save(client, rid, plan(providers=("openalex", "semantic_scholar", "crossref", "scopus")))
    assert saved.status_code == 200, saved.text
    view = saved.json()
    assert view["scope_revision"] == 2 and view["origin"] == "user" and view["issues"] == []
    # Before the run: a preview compiled from the plan's words alone; the question's query is not searched beside it.
    assert view["queries_preview"] is True
    assert view["queries"] == [{"label": "Query 1", "origin": "user", "compiled_from": "plan_words",
                                "query_text": '"rail freight" AND ("timetable scheduling" OR "train dispatching")'}]
    crossref = next(p for p in view["providers"] if p["provider_id"] == "crossref")
    assert crossref["not_covered"] == ["pdf_link_lookup"]  # PDF links are still asked of Crossref

    second = discover(client, rid)
    assert second["status"] == "completed", second
    assert planning_calls(adapter, 2) == []
    labels = step_output(client, second["id"], "vocabulary")["vocabulary"]["labelling"]
    assert labels["skipped"] == "user_plan" and labels["runs_ok"] == 0

    approval = step_output(client, second["id"], "protocol_approval")["approval"]
    assert (approval["mode"], approval["approved_by"], approval["edited"]) == ("user_edited", "user", True)
    shown = next(r for r in client.get(f"/api/researches/{rid}").json()["runs"] if r["id"] == second["id"])
    assert shown["approval"]["approved_by"] == "user"

    body = protocols(client, rid)[-1]
    assert body["user_plan"]["plan"] == plan(providers=("openalex", "semantic_scholar", "crossref", "scopus"))
    assert body["user_plan"]["scope_revision"] == 2 and body["user_plan"]["excluded_providers"] == []
    query = body["search_query"]
    assert (query["origin"], query["model"], query["prompt"]) == ("user", None, None)
    assert query["plan_sha256"] == body["user_plan"]["plan_sha256"] == body["approval"]["plan_sha256"]
    assert body["approval"]["mode"] == "user_edited"
    assert {t["origin"] for t in body["vocabulary"]} == {"user"}
    assert body["concept_blocks"] == {"setting": ["rail freight"], "task": ["timetable scheduling", "train dispatching"]}
    assert body["inclusion_criterion"] == plan()["criterion"]["text"]
    assert body["criterion_origin"]["origin"] == "user" and body["exclusion_title_words"] == ["survey"]
    assert [c["phrase"] for c in body["cue_phrases"]] == ["freight train scheduling", "timetable"]
    user_query = next(q for q in body["compiled_queries"] if q.get("origin") == "user")
    assert user_query["query_text"] == '"rail freight" AND ("timetable scheduling" OR "train dispatching")'
    assert user_query["query_text"] in providers.searches
    assert {q.get("origin") for q in body["compiled_queries"]} == {"user"}
    assert (query["code_query_searched"], query["code_query_left_out"]) == (False, "user_plan")

    # After the run the panel shows the queries the protocol froze.
    after = client.get(f"/api/researches/{rid}/search-plan").json()
    assert after["origin"] == "user" and after["queries_preview"] is False
    assert {q["compiled_from"] for q in after["queries"]} == {"protocol"}


def test_the_protocol_freezes_before_the_first_request_that_fetches_search_results(tmp_path, monkeypatch):
    from deixis.workflow.run.store import Store

    events = []
    real = Store.freeze_protocol

    def freeze(self, *args, **kwargs):
        events.append("freeze")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Store, "freeze_protocol", freeze)
    providers = Providers(events=events)
    client = client_for(tmp_path, monkeypatch, providers, FakeAdapter())
    rid = create(client)
    assert save(client, rid, plan()).status_code == 200
    run = discover(client, rid)
    assert run["status"] == "completed", run
    assert events.count("freeze") == 1 and "fetch" in events
    assert events.index("freeze") < events.index("fetch")
    # Only planning requests (term counts, the field distribution) went before it.
    assert set(events[:events.index("freeze")]) <= {"group_by"}


# ---- the criterion belongs to the plan's revision: the full-text path reads exactly the one it froze -------------


# ---- the comparator guard travels with the criterion (slice 28, D109) ---------------------------------------------

