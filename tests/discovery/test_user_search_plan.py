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
EXCLUDED_HOSTS = {"semantic_scholar": "api.semanticscholar.org", "crossref": "api.crossref.org",
                  "scopus": "api.elsevier.com"}


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
                          "exclusion_title_words": ["survey"]},
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
    ({"task": [{"term": '"timetable"'}]}, "query_syntax_in_term"),
    ({"task": [{"term": "very long freight timetable scheduling"}]}, "query_term_too_long"),
    ({"setting": [{"term": t} for t in ("a1", "a2", "a3", "a4")], "task": [{"term": t} for t in ("b1", "b2", "b3")]},
     "too_many_query_terms"),
    ({"task_backup": [{"term": "rail freight"}]}, "duplicate_query_term"),
    ({"providers": ["semantic_scholar", "crossref"]}, "openalex_required"),
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
    # Before the run: Query 1 compiled from the words, Query 2 the code's query from the question's newest protocol.
    assert view["queries"][0] == {"label": "Query 1", "origin": "user", "compiled_from": "plan_words",
                                  "query_text": '"rail freight" AND ("timetable scheduling" OR "train dispatching")'}
    assert view["queries"][1]["origin"] == "code"

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
    assert any(q.get("origin") == "code" for q in body["compiled_queries"])

    # After the run the panel shows the queries the protocol froze.
    after = client.get(f"/api/researches/{rid}/search-plan").json()
    assert after["origin"] == "user" and {q["compiled_from"] for q in after["queries"]} == {"protocol"}


def test_a_term_no_record_holds_is_searched_as_its_backup_and_a_block_left_empty_ends_the_run(tmp_path, monkeypatch):
    providers = Providers({'"train dispatching"': 0})
    client = client_for(tmp_path, monkeypatch, providers, FakeAdapter())
    rid = create(client)
    assert save(client, rid, plan()).status_code == 200
    run = discover(client, rid)
    assert run["status"] == "completed", run
    user_query = next(q for q in protocols(client, rid)[-1]["compiled_queries"] if q.get("origin") == "user")
    assert user_query["query_text"] == '"rail freight" AND ("timetable scheduling" OR "crew rostering")'

    providers.table.update({'"rail freight"': 0})
    assert save(client, rid, plan()).status_code == 200
    run = discover(client, rid)
    assert (run["status"], run["pause_reason"]) == ("failed", "user_plan_unsearchable"), run
    assert len(protocols(client, rid)) == 1  # nothing was frozen for the plan that could not be searched


def test_the_protocol_freezes_before_the_first_request_that_fetches_search_results(tmp_path, monkeypatch):
    from deixis.workflow.store import Store

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


@pytest.mark.parametrize("kept", [(), ("crossref",), ("semantic_scholar", "scopus")])
def test_a_provider_left_out_of_the_plan_gets_no_search_and_no_abstract_lookup_request(tmp_path, monkeypatch, kept):
    # Control: the same research without a plan asks all three, so a zero below is the plan's doing.
    control = Providers()
    client = client_for(tmp_path / "control", monkeypatch, control, FakeAdapter())
    run = discover(client, create(client, effort="detailed"))
    assert run["status"] == "completed", run
    assert all(control.hosts(host) for host in EXCLUDED_HOSTS.values())
    assert any(method == "GET" for _, method in control.hosts("api.semanticscholar.org"))  # the bulk search
    client.__exit__(None, None, None)

    providers = Providers()
    client = client_for(tmp_path / "plan", monkeypatch, providers, FakeAdapter())
    rid = create(client, effort="detailed")
    assert save(client, rid, plan(providers=("openalex", *kept))).status_code == 200
    run = discover(client, rid)
    assert run["status"] == "completed", run
    left_out = [p for p in EXCLUDED_HOSTS if p not in kept]
    for provider, host in EXCLUDED_HOSTS.items():
        assert bool(providers.hosts(host)) == (provider in kept), (provider, providers.hosts(host))
    # Each provider left out is recorded as left out by the person, where it would have been asked.
    body = protocols(client, rid)[-1]
    assert body["fast_path_search"]["excluded_providers"] == left_out
    assert body["user_plan"]["excluded_providers"] == left_out
    routing = {row["provider_id"]: row["reason"] for row in body["source_routing"]["left_out"]}
    if "semantic_scholar" in left_out:
        assert routing["semantic_scholar"] == "excluded_by_user"
        bulk = client.app.state.store.conn.execute(
            "SELECT status, error_code FROM run_steps WHERE run_id = ? AND operation_key = 'search:fast:s2_bulk'",
            (run["id"],)).fetchone()
        assert tuple(bulk) == ("cancelled", "excluded_by_user")
    for provider in left_out:
        plan_step = step_output(client, run["id"], f"lookup_plan:{provider}")
        # Scopus opens no plan step when it may not be asked, as for a research without it (D91).
        assert plan_step is None if provider == "scopus" else plan_step["skipped"] == "excluded_by_user"


def test_a_worker_that_dies_after_the_counts_resumes_without_asking_or_freezing_twice(tmp_path, monkeypatch):
    from deixis.storage import db
    from deixis.workflow import flow as flow_module

    build = flow_module.search_query_rules.vocabulary
    died = []

    def dies_once(*args):
        if not died:
            died.append(True)
            raise RuntimeError("SYNTHETIC crash after the counts")
        return build(*args)

    monkeypatch.setattr(flow_module.search_query_rules, "vocabulary", dies_once)
    first, adapter = Providers(), FakeAdapter()
    client = client_for(tmp_path, monkeypatch, first, adapter)
    rid = create(client)
    assert save(client, rid, plan()).status_code == 200
    run = discover(client, rid)
    assert run["status"] == "failed"
    counted = step_output(client, run["id"], "search_query")["checked"]["probes"]
    client.__exit__(None, None, None)
    assert counted and not first.searches
    conn = db.connect(tmp_path / "data" / "library.sqlite")
    conn.execute("UPDATE runs SET status = 'running' WHERE id = ?", (run["id"],))  # the worker died mid-step
    conn.close()

    second, adapter = Providers(), FakeAdapter()
    client = client_for(tmp_path, monkeypatch, second, adapter)
    assert client.post(f"/api/runs/{run['id']}/resume").status_code == 200
    deadline = time.time() + 20
    while time.time() < deadline:
        run = next(r for r in client.get(f"/api/researches/{rid}").json()["runs"] if r["id"] == run["id"])
        if run["status"] in ("completed", "failed", "paused"):
            break
        time.sleep(0.05)
    assert run["status"] == "completed", run
    assert planning_calls(adapter, 2) == []
    assert not {p["query"] for p in counted} & set(second.counts)
    assert len(protocols(client, rid)) == 1


def test_a_later_revision_made_another_way_does_not_inherit_the_plan(tmp_path, monkeypatch):
    """The rule: a plan belongs to the revision it was saved with. A revision made by another route (here the same
    question saved again) asks the model for the query and takes back the newest criterion a model proposed, never
    the person's; the plan applies again only when it is saved again."""
    adapter = FakeAdapter()
    client = client_for(tmp_path, monkeypatch, Providers(), adapter)
    rid = create(client)
    assert discover(client, rid)["status"] == "completed"
    model_criterion = protocols(client, rid)[0]["inclusion_criterion"]
    assert save(client, rid, plan()).status_code == 200
    assert discover(client, rid)["status"] == "completed"
    revised = client.post(f"/api/researches/{rid}/scope",
                          json={"question": QUESTION, "steering": None, "expected_version": version(client, rid)})
    assert revised.status_code == 200, revised.text
    scope = client.app.state.store.scope(rid)
    assert scope["revision"] == 3 and scope["user_plan"] is None
    run = discover(client, rid)
    assert run["status"] == "completed", run
    assert "search_query" in planning_calls(adapter, 3)
    body = protocols(client, rid)[-1]
    assert "user_plan" not in body and body["approval"]["approved_by"] == "unattended"
    assert body["search_query"].get("origin") is None
    assert body["inclusion_criterion"] == model_criterion != plan()["criterion"]["text"]
    assert body["criterion_origin"]["origin"] == "protocol"  # taken back from revision 1's, the model's
    assert client.get(f"/api/researches/{rid}/search-plan").json()["origin"] == "model"
