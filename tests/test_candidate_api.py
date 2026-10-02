"""Synthetic API plumbing; fake outputs do not prove that a model reads a work correctly."""
import copy
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.storage import db
from deixis.workflow.candidates.store import CandidateStore
from fakes import FakeAdapter, valid_response
from test_api_flow import WORKS, session


@pytest.fixture
def api(tmp_path):
    state = SimpleNamespace(records=copy.deepcopy(WORKS[:1]), requests=[])

    def transport(request):
        state.requests.append(request)
        assert request.url.host == "api.openalex.org", "No live provider request is permitted"
        return httpx.Response(200, json={"meta": {"count": len(state.records)}, "results": state.records})

    adapter = FakeAdapter()
    http = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    app = create_app(Settings(data_dir=tmp_path / "data", port=8873), adapters={"fake": adapter},
                     http_client=http, start_worker=False, trusted_clients=("testclient",))
    with TestClient(app, base_url="http://127.0.0.1:8873") as client:
        session(client)
        store = app.state.store
        rid = store.create_research("SYNTHETIC API question?", "academic", "quick", ["openalex"], "fake", "fake-model", "en")
        candidate_store = CandidateStore(store)
        state.__dict__.update(client=client, app=app, store=store, conn=store.conn, rid=rid, adapter=adapter,
                              candidate_store=candidate_store, url=f"/api/researches/{rid}/candidates")
        yield state
        client.portal.call(http.aclose)


def open_owner(api, key=None, text="SYNTHETIC buffering reduces delay.", rid=None):
    url = f"/api/researches/{rid}/candidates" if rid else api.url
    response = api.client.post(url, json={"origin": "owner_text", "text": text},
                               headers={"Idempotency-Key": key} if key else {})
    assert response.status_code == 201, response.text
    return response.json()


def candidate_url(api, candidate):
    return api.url + "/" + candidate["id"]


def edit_body(**changes):
    return dict(claim_statement="SYNTHETIC buffering reduces delay.", conditions=["SYNTHETIC bounded arrivals"],
                elements=[{"text": "SYNTHETIC buffering", "kind": "mechanism"},
                          {"text": "SYNTHETIC delay", "kind": "outcome"}], nearest_simple_explanation=None,
                critical_assumption="SYNTHETIC bound holds", validation_plan="SYNTHETIC compare bounds",
                expected_version=0) | changes


def edited(api, candidate=None):
    candidate = candidate or open_owner(api)
    response = api.client.post(candidate_url(api, candidate) + "/versions", json=edit_body())
    assert response.status_code == 201, response.text
    return response.json()


def execute(api, run):
    async def go():
        api.store.update_run(run["id"], status="running")
        await api.app.state.worker.flow.execute(run["id"])
        return api.store.run(run["id"])
    return api.client.portal.call(go)


def start(api, candidate, key=None):
    url = candidate_url(api, candidate)
    preview = api.client.get(url + "/kill-search/plan")
    assert preview.status_code == 200, preview.text
    response = api.client.post(url + "/kill-search", json={"preview_fingerprint": preview.json()["preview_fingerprint"]},
                               headers={"Idempotency-Key": key} if key else {})
    assert response.status_code == 202, response.text
    return response.json(), preview.json()


def finished(api, candidate=None):
    candidate = candidate or edited(api)
    run, plan = start(api, candidate)
    assert execute(api, run)["status"] == "completed"
    search = api.candidate_store.search_for_run(run["id"])
    return candidate, run, search, plan


def matrix_url(api, candidate, search):
    return candidate_url(api, candidate) + "/kill-searches/" + search["id"]


def gap(api):
    run = api.store.create_run(api.rid, "answer", {}, None)
    api.store.update_run(run["id"], status="completed")
    report, row = db.new_id("rpt"), db.new_id("gap")
    api.conn.execute("INSERT INTO reports (id,research_id,run_id,scope_revision,status,created_at,updated_at)"
                     " VALUES (?, ?, ?, 1, 'draft', 'now', 'now')", (report, api.rid, run["id"]))
    api.conn.execute("INSERT INTO report_gaps (id,report_id,gap_id,kind,text,basis_json,provenance_json,created_at)"
                     " VALUES (?, ?, ?, 'corpus_absence', 'SYNTHETIC gap', '{}', '{}', 'now')", (row, report, row))
    return {"origin": "report_gap", "report_id": report, "gap_row_id": row}


def other_research(api):
    return api.store.create_research("SYNTHETIC other question?", "academic", "quick", ["openalex"], "fake", "fake-model", "en")


def test_open_owner_replay_is_content_bound_and_keys_are_scoped_to_research(api):
    first = open_owner(api, "same")
    assert open_owner(api, "same")["id"] == first["id"]
    assert first["origin"] == "owner_text" and first["origin_basis"] == {}
    assert first["current_version_id"] is first["status"] is None
    assert first["versions"] == first["searches"] == first["runs"] == first["owner_decisions"] == []
    assert first["decompose_budget"] == {"max_model_calls": 6, "max_provider_requests": 0}
    mismatch = api.client.post(api.url, json={"origin": "owner_text", "text": "SYNTHETIC other"}, headers={"Idempotency-Key": "same"})
    assert mismatch.status_code == 422 and "content mismatch" in mismatch.json()["detail"]
    second = open_owner(api, "same", rid=other_research(api))
    assert second["id"] != first["id"]
    keys = [r[0] for r in api.conn.execute("SELECT idempotency_key FROM research_candidates")]
    assert f"{api.rid}:same" in keys and f"{second['research_id']}:same" in keys
    assert api.adapter.calls == api.requests == []


def test_open_gap_replays_fingerprint_preserves_report_and_records_changed_origin(api):
    body = gap(api)
    before = [tuple(r) for r in api.conn.execute("SELECT * FROM report_gaps")]
    first = api.client.post(api.url, json=body)
    assert first.status_code == 201 and first.json()["origin"] == "report_gap"
    assert api.client.post(api.url, json=body).json()["id"] == first.json()["id"]
    assert [tuple(r) for r in api.conn.execute("SELECT * FROM report_gaps")] == before
    api.conn.execute("UPDATE report_gaps SET text='SYNTHETIC revised gap' WHERE id=?", (body["gap_row_id"],))
    second = api.client.post(api.url, json=body).json()
    assert second["id"] != first.json()["id"]
    assert api.client.get(candidate_url(api, first.json())).json()["origin_changed"] is True
    assert api.client.post(api.url.replace(api.rid, other_research(api)), json=body).status_code == 404


def test_list_and_card_bind_versions_computed_status_owner_and_active_run(api):
    candidate = edited(api)
    status = api.candidate_store.candidate_status(candidate["current_version_id"])
    assert candidate["status"] == status and candidate["versions"][0]["conditions"] == ["SYNTHETIC bounded arrivals"]
    run, _ = start(api, candidate)
    card = api.client.get(candidate_url(api, candidate)).json()
    assert card["active_run"]["id"] == run["id"] and card["runs"][0]["kind"] == "kill_search"
    listed = api.client.get(api.url).json()
    assert len(listed) == 1 and listed[0]["claim_statement"] == candidate["versions"][0]["claim_statement"]
    assert listed[0]["status"] == status["computed"] and listed[0]["owner"] is None
    assert listed[0]["active_run_id"] == run["id"]
    api.store.update_run(run["id"], status="cancelled")
    api.candidate_store.trash_candidate(api.rid, candidate["id"])
    assert api.client.get(api.url).json() == []


def test_card_lists_only_last_five_candidate_runs_and_preserves_prefreeze_failure(api):
    candidate = edited(api)
    for i in range(7):
        run, _ = start(api, candidate)
        api.store.update_run(run["id"], status="failed", pause_reason=f"SYNTHETIC_failure_{i}")
    card = api.client.get(candidate_url(api, candidate)).json()
    assert len(card["runs"]) == 5 and card["runs"][0]["error_code"] == "SYNTHETIC_failure_6"
    assert card["searches"] == [] and card["active_run"] is None
    assert card["status"] == api.candidate_store.candidate_status(candidate["current_version_id"])


def test_human_edit_replay_expected_version_conflict_and_candidate_scoped_keys(api):
    candidate = open_owner(api)
    url = candidate_url(api, candidate) + "/versions"
    headers = {"Idempotency-Key": "edit"}
    first = api.client.post(url, json=edit_body(), headers=headers)
    assert first.status_code == 201 and first.json()["versions"][0]["origin"] == "human_edit"
    assert api.client.post(url, json=edit_body(), headers=headers).json()["current_version_id"] == first.json()["current_version_id"]
    assert api.client.post(url, json=edit_body()).status_code == 409
    assert api.client.post(url, json=edit_body(claim_statement="SYNTHETIC changed"), headers=headers).status_code == 422
    second = api.client.post(url, json=edit_body(expected_version=1)).json()
    assert second["current_version"] == 2 and len(second["versions"]) == 2
    foreign = open_owner(api, rid=other_research(api))
    response = api.client.post(f"/api/researches/{foreign['research_id']}/candidates/{foreign['id']}/versions", json=edit_body(), headers=headers)
    assert response.status_code == 201 and response.json()["current_version_id"] != first.json()["current_version_id"]
    key = api.conn.execute("SELECT idempotency_key FROM candidate_versions WHERE id=?", (first.json()["current_version_id"],)).fetchone()[0]
    assert key == f"{api.rid}:{candidate['id']}:edit"


@pytest.mark.parametrize("text", ["\x00SYNTHETIC", "\ud800SYNTHETIC", " \n\t"])
@pytest.mark.parametrize("field", ["claim_statement", "conditions", "elements", "nearest_simple_explanation",
                                  "critical_assumption", "validation_plan"])
def test_human_version_unsafe_text_is_422_without_writes(api, field, text):
    candidate = open_owner(api)
    body = edit_body()
    if field == "conditions":
        body[field] = [text]
    elif field == "elements":
        body[field][0]["text"] = text
    else:
        body[field] = text
    response = api.client.post(candidate_url(api, candidate) + "/versions",
                               content=json.dumps(body), headers={"Content-Type": "application/json"})
    assert response.status_code == 422, response.text
    assert api.candidate_store.versions(candidate["id"]) == []
    assert api.conn.execute("SELECT COUNT(*) FROM claim_elements").fetchone()[0] == 0
    assert api.candidate_store.candidate(candidate["id"])["current_version"] == 0


@pytest.mark.parametrize("text", ["\x00SYNTHETIC", "\ud800SYNTHETIC", " \n\t"])
@pytest.mark.parametrize("route", ["owner_text", "owner_decision"])
def test_owner_unsafe_text_is_422_without_writes(api, route, text):
    if route == "owner_text":
        url, body = api.url, {"origin": "owner_text", "text": text}
        table = "research_candidates"
    else:
        candidate = edited(api)
        url = candidate_url(api, candidate) + f"/versions/{candidate['current_version_id']}/owner-decision"
        body = {"status": "open", "reason": text}
        table = "candidate_status_overrides"
    response = api.client.post(url, content=json.dumps(body), headers={"Content-Type": "application/json"})
    assert response.status_code == 422, response.text
    assert api.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert api.adapter.calls == api.requests == []


def test_decompose_request_replay_after_success_and_once_only_conflict(api, monkeypatch):
    candidate = open_owner(api)
    url = candidate_url(api, candidate) + "/decompose"
    wake = []
    monkeypatch.setattr(api.app.state.worker, "wake", lambda: wake.append(True))
    response = api.client.post(url, headers={"Idempotency-Key": "decompose"})
    assert response.status_code == 202
    run = response.json()
    assert run["kind"] == "claim_decomposition" and run["stage"] == "candidate"
    assert run["idempotency_key"] == f"decompose:{api.rid}:{candidate['id']}:decompose"
    assert execute(api, run)["status"] == "completed"
    replay = api.client.post(url, headers={"Idempotency-Key": "decompose"})
    assert replay.status_code == 202 and replay.json()["id"] == run["id"] and replay.json()["status"] == "completed"
    assert len(api.adapter.calls) == 1 and len(wake) == 2
    assert api.client.post(url).status_code == 409
    card = api.client.get(candidate_url(api, candidate)).json()
    assert card["versions"][0]["step_input_id"] and card["versions"][0]["nearest_simple_explanation"] is None


def test_decompose_replay_conflicting_stored_target_is_409(api):
    candidate, other = open_owner(api), open_owner(api, text="SYNTHETIC other")
    run = api.store.create_run(api.rid, "claim_decomposition", {}, f"decompose:{api.rid}:{candidate['id']}:bad", {"candidate_id": other["id"]})
    api.store.update_run(run["id"], status="completed")
    assert api.client.post(candidate_url(api, candidate) + "/decompose", headers={"Idempotency-Key": "bad"}).status_code == 409


def test_kill_plan_start_fingerprint_replay_after_edit_and_request_namespaces(api, monkeypatch):
    candidate = edited(api)
    url = candidate_url(api, candidate)
    wake = []
    monkeypatch.setattr(api.app.state.worker, "wake", lambda: wake.append(True))
    run, plan = start(api, candidate, "kill")
    assert run["kind"] == "kill_search" and run["stage"] == "candidate" and run["target"] == plan
    assert run["idempotency_key"] == f"killsearch:{api.rid}:{candidate['id']}:kill"
    assert plan["budget"]["max_model_calls"] == 54 and plan["transport"]["max_provider_requests"] == plan["budget"]["max_provider_requests"]
    api.store.update_run(run["id"], status="completed")
    assert api.client.post(url + "/versions", json=edit_body(expected_version=1)).status_code == 201
    body = {"preview_fingerprint": plan["preview_fingerprint"]}
    replay = api.client.post(url + "/kill-search", json=body, headers={"Idempotency-Key": "kill"})
    assert replay.status_code == 202 and replay.json()["id"] == run["id"] and len(wake) == 2
    assert api.client.post(url + "/kill-search", json=body).status_code == 409
    assert api.client.post(url + "/kill-search", json={"preview_fingerprint": "0" * 64}, headers={"Idempotency-Key": "kill"}).status_code == 409


@pytest.mark.parametrize("mode,code", [("no_version", "candidate_not_decomposed"), ("no_provider", "no_searchable_provider"), ("trashed", None)])
def test_plan_and_start_refusals_have_422_or_409_with_the_recorded_code(api, mode, code):
    candidate = open_owner(api) if mode == "no_version" else edited(api)
    if mode == "no_provider":
        api.conn.execute("UPDATE scope_revisions SET providers_json='[]' WHERE research_id=?", (api.rid,))
    if mode == "trashed":
        api.candidate_store.trash_candidate(api.rid, candidate["id"])
    url = candidate_url(api, candidate)
    for response in (api.client.get(url + "/kill-search/plan"), api.client.post(url + "/kill-search", json={"preview_fingerprint": "0" * 64})):
        assert response.status_code == (409 if mode == "trashed" else 422), response.text
        if code:
            assert response.json() == {"detail": code}
    assert api.requests == api.adapter.calls == []


def test_unconfigured_scope_provider_is_not_searchable(api, monkeypatch):
    candidate = edited(api)
    monkeypatch.delenv("IEEE_API_KEY", raising=False)
    api.conn.execute("UPDATE scope_revisions SET providers_json='[\"ieee_xplore\"]' WHERE research_id=?", (api.rid,))
    response = api.client.get(candidate_url(api, candidate) + "/kill-search/plan")
    assert response.status_code == 422 and response.json()["detail"] == "no_searchable_provider"


def test_new_kill_search_refuses_paused_candidate_or_second_active_run(api):
    candidate = edited(api)
    run, plan = start(api, candidate)
    body = {"preview_fingerprint": plan["preview_fingerprint"]}
    url = candidate_url(api, candidate) + "/kill-search"
    assert api.client.post(url, json=body).status_code == 409
    api.store.update_run(run["id"], status="paused")
    assert api.client.post(url, json=body).status_code == 409
    api.store.update_run(run["id"], status="cancelled")
    active = api.store.create_run(api.rid, "answer", {}, None)
    assert api.client.post(url, json=body).status_code == 409
    api.store.update_run(active["id"], status="cancelled")
    assert api.client.post(url, json=body).status_code == 202


def test_matrix_shape_frozen_selection_counts_cells_evidence_and_summary(api):
    candidate, run, search, plan = finished(api)
    response = api.client.get(matrix_url(api, candidate, search))
    assert response.status_code == 200, response.text
    matrix = response.json()
    assert matrix["search_status"] == api.candidate_store.search_status(search["id"])
    assert matrix["search"]["selection"] == {k: plan[k] for k in ("model", "providers", "budget", "transport")}
    assert matrix["search"]["query_block"] and matrix["search"]["rendered_queries"] and matrix["search"]["skipped_terms"] == []
    assert matrix["queries"][0]["status"] == "succeeded" and matrix["queries"][0]["record_count"] == 1
    assert matrix["counts"] == {"found": 1, "kept": 1, "rank_cut": 0, "duplicates": 0}
    hit = matrix["hits"][0]
    assert hit["source"]["title"] == WORKS[0]["display_name"] and hit["reading_depth"] == "abstract"
    assert hit["assessment_state"] == "assessed" and hit["states_whole_claim"] is False
    assert len(matrix["cells"][hit["source_version_id"]]) == 2
    assert matrix["summary"]["hits"][0]["outcome"] == "assessed" and matrix["summary"]["failure_code"] is None
    assert matrix["kill_search_id"] == search["id"] and matrix["candidate_version_id"] == candidate["current_version_id"]
    assert matrix["version"] == 1 and matrix["is_latest_search_of_version"] is True
    assert matrix["evidence"] == []


def test_historical_matrix_returns_its_own_status_and_version_after_later_search_and_edit(api):
    api.records = []
    candidate, first_run, first, _ = finished(api)
    api.records = copy.deepcopy(WORKS[:1])
    api.records[0].pop("abstract_inverted_index")
    _, _, second, _ = finished(api, candidate)
    assert api.candidate_store.search_status(first["id"])["status"] == "open"
    assert api.candidate_store.search_status(second["id"])["status"] == "undecided"
    url = candidate_url(api, candidate)
    card = api.client.get(url).json()
    assert card["status"] == api.candidate_store.candidate_status(candidate["current_version_id"])
    assert card["status"]["previous"] == api.candidate_store.search_status(first["id"])
    assert api.client.post(url + "/versions", json=edit_body(expected_version=1)).status_code == 201
    for search in (first, second):
        matrix = api.client.get(matrix_url(api, candidate, search)).json()
        assert matrix["search_status"] == api.candidate_store.search_status(search["id"])
        assert matrix["version"] == 1 and matrix["is_latest_search_of_version"] == (search == second)


def test_evidence_route_uses_exact_stored_input_and_located_quotes_without_corpus_or_live_view(api, monkeypatch):
    def response(si):
        value = json.loads(valid_response(si))
        if si["task_type"] == "claim_assessment":
            quote = {"passage_id": si["passages"][0]["passage_id"], "quote": si["passages"][0]["text"]}
            value.update(work_relevance="related", states_whole_claim=True, whole_claim_evidence=[quote])
            for cell in value["cells"]:
                cell.update(relation="explicit_support", condition_alignment="aligned", evidence=[quote])
        return json.dumps(value)
    api.adapter.responder = response
    candidate, _, search, _ = finished(api)
    hit = api.candidate_store.hits(search["id"])[0]
    payload = api.store.step_input_payload(hit["step_input_id"])
    def forbidden(*args, **kw):
        raise AssertionError("Evidence must not read a corpus/live passage view")
    monkeypatch.setattr("deixis.api.app.passage_view", forbidden)
    monkeypatch.setattr(api.store, "passages_for", forbidden)
    url = matrix_url(api, candidate, search) + "/hits/" + hit["source_version_id"]
    for member in (False, True):
        if member:
            api.store.add_to_corpus(api.rid, hit["source_version_id"], "user_upload", selection_state="included", selection_origin="user")
        response = api.client.get(url)
        assert response.status_code == 200, response.text
        evidence = response.json()
        assert evidence["passages"] == payload["passages"] and evidence["quotes"]
        assert all(q["evidence_kind"] == "abstract" and q["passage_id"] is None for q in evidence["quotes"])
        assert evidence["source"]["source_version_id"] == hit["source_version_id"]


@pytest.mark.parametrize("mode", ["pending", "insufficient_access", "cut"])
def test_evidence_route_identity_only_for_unassessed_hits_and_404_for_cut_hits(api, mode):
    candidate = edited(api)
    if mode == "insufficient_access":
        api.records[0].pop("abstract_inverted_index")
    elif mode == "cut":
        api.records = [copy.deepcopy(WORKS[0]) | {"id": f"https://openalex.org/W{100+i}", "doi": None} for i in range(9)]
    run, _ = start(api, candidate)
    if mode == "pending":
        api.store.add_usage(run["id"], "model_calls", 53)
    execute(api, run)
    search = api.candidate_store.search_for_run(run["id"])
    hit = next(h for h in api.candidate_store.hits(search["id"]) if bool(h["kept"]) == (mode != "cut"))
    response = api.client.get(matrix_url(api, candidate, search) + "/hits/" + hit["source_version_id"])
    assert response.status_code == (404 if mode == "cut" else 200), response.text
    if mode != "cut":
        assert response.json()["passages"] == response.json()["quotes"] == [] and response.json()["source"]["title"]


def test_other_research_candidate_and_other_candidate_search_or_version_are_404(api):
    candidate, _, search, _ = finished(api)
    other = edited(api)
    foreign_url = candidate_url(api, candidate).replace(api.rid, other_research(api))
    for suffix in ("", "/kill-search/plan", f"/kill-searches/{search['id']}"):
        assert api.client.get(foreign_url + suffix).status_code == 404
    for suffix, body in (("/versions", edit_body()), ("/decompose", {}), ("/kill-search", {"preview_fingerprint": "0" * 64}),
                         (f"/versions/{candidate['current_version_id']}/owner-decision", {"status": "open", "reason": "SYNTHETIC"})):
        assert api.client.post(foreign_url + suffix, json=body).status_code == 404
    hit = api.candidate_store.hits(search["id"])[0]
    for suffix in ("", "/hits/" + hit["source_version_id"]):
        assert api.client.get(matrix_url(api, other, search) + suffix).status_code == 404
    assert api.client.post(candidate_url(api, other) + f"/versions/{candidate['current_version_id']}/owner-decision",
                           json={"status": "open", "reason": "SYNTHETIC"}).status_code == 404
    assert api.client.get(matrix_url(api, candidate, search) + "/hits/srv_unknown").status_code == 404
    assert api.client.get(api.url + "/rcd_unknown").status_code == 404


def test_owner_decisions_append_beside_computed_status_never_override_it(api):
    candidate = edited(api)
    url = candidate_url(api, candidate) + f"/versions/{candidate['current_version_id']}/owner-decision"
    before = api.candidate_store.candidate_status(candidate["current_version_id"])["computed"]
    assert api.client.post(url, json={"status": "closed", "reason": " \n "}).status_code == 422
    for _ in range(2):
        response = api.client.post(url, json={"status": "closed", "reason": "  SYNTHETIC owner judgement  "}, headers={"Idempotency-Key": "ignored"})
        assert response.status_code == 201, response.text
        card = response.json()
        assert card["status"]["computed"] == before and card["status"]["owner"]["status"] == "closed"
        assert card["status"]["owner"]["reason"] == "SYNTHETIC owner judgement"
    assert len(card["owner_decisions"]) == 2 and api.client.get(api.url).json()[0]["owner"] == card["status"]["owner"]


@pytest.mark.parametrize("action,expected", [("pause", "paused"), ("resume", "running"), ("cancel", "stopped")])
def test_run_control_syncs_search_immediately_and_never_renews_usage(api, action, expected):
    candidate = edited(api)
    run, _ = start(api, candidate)
    api.adapter.before = lambda si: api.store.update_run(run["id"], status="pause_requested") if si["task_type"] == "claim_assessment" else None
    assert execute(api, run)["status"] == "paused"
    search = api.candidate_store.search_for_run(run["id"])
    usage = api.store.run(run["id"])["usage"]
    if action == "pause":
        api.store.resume_run(run["id"])
        api.candidate_store.set_kill_search_state(search["id"], "running")
    response = api.client.post(f"/api/runs/{run['id']}/{action}")
    assert response.status_code == 200, response.text
    assert api.candidate_store.kill_search(search["id"])["outcome"] == expected
    assert api.store.run(run["id"])["usage"] == usage


@pytest.mark.parametrize("reader", ["list", "card", "matrix", "evidence", "plan"])
@pytest.mark.parametrize("status,outcome", [("paused", "paused"), ("failed", "failed")])
def test_read_endpoints_perform_only_idempotent_lifecycle_sync_after_recovery_or_failure(api, reader, status, outcome):
    candidate = edited(api)
    run, _ = start(api, candidate)
    api.adapter.before = lambda si: api.store.update_run(run["id"], status="pause_requested") if si["task_type"] == "claim_assessment" else None
    execute(api, run)
    search = api.candidate_store.search_for_run(run["id"])
    api.candidate_store.set_kill_search_state(search["id"], "running")
    if status == "paused":
        api.store.update_run(run["id"], status="running")
        api.app.state.worker.recover()
    else:
        api.store.update_run(run["id"], status="failed", pause_reason="internal_error")
    hit = api.candidate_store.hits(search["id"])[0]
    url = {"list": api.url, "card": candidate_url(api, candidate), "matrix": matrix_url(api, candidate, search),
           "evidence": matrix_url(api, candidate, search) + "/hits/" + hit["source_version_id"],
           "plan": candidate_url(api, candidate) + "/kill-search/plan"}[reader]
    assert api.client.get(url).status_code == 200
    assert api.candidate_store.kill_search(search["id"])["outcome"] == outcome
    events = api.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    api.client.get(url)
    assert api.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == events
    if status == "failed":
        assert api.store.existing_step(run["id"], "kill_search_summary")["output"]["failure_code"] == "internal_error"


@pytest.mark.parametrize("paused_kind,active_kind", [("answer", "kill_search"), ("lineage_links", "claim_decomposition"),
                                                     ("kill_search", "answer"), ("claim_decomposition", "lineage_links")])
def test_resume_409_guard_is_shared_by_candidate_answer_and_lineage_runs(api, paused_kind, active_kind):
    paused = api.store.create_run(api.rid, paused_kind, {}, None)
    api.store.update_run(paused["id"], status="paused")
    api.store.add_usage(paused["id"], "model_calls", 3)
    active = api.store.create_run(api.rid, active_kind, {}, None)
    assert api.client.post(f"/api/runs/{paused['id']}/resume").status_code == 409
    api.store.update_run(active["id"], status="cancelled")
    assert api.client.post(f"/api/runs/{paused['id']}/resume").status_code == 200
    assert api.store.run(paused["id"])["usage"]["model_calls"] == 3


@pytest.mark.parametrize("kind", ["claim_decomposition", "kill_search"])
def test_cancel_interrupts_sequential_candidate_adapter_calls(api, monkeypatch, kind):
    candidate = open_owner(api) if kind == "claim_decomposition" else edited(api)
    response = api.client.post(candidate_url(api, candidate) + "/decompose") if kind == "claim_decomposition" else None
    run = response.json() if response else start(api, candidate)[0]
    api.store.update_run(run["id"], status="running")
    api.app.state.worker.current_run_id = run["id"]
    cancelled = []
    async def cancel():
        cancelled.append(True)
    monkeypatch.setattr(api.adapter, "cancel", cancel)
    assert api.client.post(f"/api/runs/{run['id']}/cancel").status_code == 200
    assert cancelled == [True]


@pytest.mark.parametrize("route", ["open", "edit", "decompose", "start", "owner"])
def test_all_candidate_mutations_preserve_csrf_and_origin_guards(api, route):
    candidate = edited(api)
    base = candidate_url(api, candidate)
    url, body = {"open": (api.url, {"origin": "owner_text", "text": "SYNTHETIC"}),
                 "edit": (base + "/versions", edit_body(expected_version=1)), "decompose": (base + "/decompose", {}),
                 "start": (base + "/kill-search", {"preview_fingerprint": "0" * 64}),
                 "owner": (base + f"/versions/{candidate['current_version_id']}/owner-decision", {"status": "open", "reason": "SYNTHETIC"})}[route]
    token = api.client.headers.pop("x-deixis-csrf")
    assert api.client.post(url, json=body).status_code == 403
    api.client.headers["x-deixis-csrf"] = token
    assert api.client.post(url, json=body, headers={"Origin": "https://foreign.invalid"}).status_code == 403
    assert api.client.post(url, json=body, headers={"Host": "foreign.invalid"}).status_code == 403
    assert api.client.get(base, headers={"Host": "foreign.invalid"}).status_code == 403
    assert api.client.post(base + f"/versions/{candidate['current_version_id']}/owner-decision",
                           json={"status": "open", "reason": "SYNTHETIC"}, headers={"Origin": "http://127.0.0.1:8873"}).status_code == 201


@pytest.mark.parametrize("route", ["open", "edit", "decompose", "start"])
def test_candidate_idempotency_headers_are_bounded_to_200_characters(api, route):
    candidate = edited(api)
    url, body = {"open": (api.url, {"origin": "owner_text", "text": "SYNTHETIC"}),
                 "edit": (candidate_url(api, candidate) + "/versions", edit_body(expected_version=1)),
                 "decompose": (candidate_url(api, candidate) + "/decompose", {}),
                 "start": (candidate_url(api, candidate) + "/kill-search", {"preview_fingerprint": "0" * 64})}[route]
    assert api.client.post(url, json=body, headers={"Idempotency-Key": "x" * 201}).status_code == 422


@pytest.mark.parametrize("route", ["open", "edit", "element", "decompose", "start", "owner"])
def test_candidate_request_bodies_and_nested_elements_refuse_extra_fields(api, route):
    candidate = edited(api)
    base = candidate_url(api, candidate)
    url, body = {"open": (api.url, {"origin": "owner_text", "text": "SYNTHETIC"}),
                 "edit": (base + "/versions", edit_body(expected_version=1)),
                 "element": (base + "/versions", edit_body(expected_version=1)),
                 "decompose": (base + "/decompose", {}),
                 "start": (base + "/kill-search", {"preview_fingerprint": "0" * 64}),
                 "owner": (base + f"/versions/{candidate['current_version_id']}/owner-decision", {"status": "open", "reason": "SYNTHETIC"})}[route]
    if route == "element":
        body["elements"][0]["unexpected"] = True
    else:
        body["unexpected"] = True
    assert api.client.post(url, json=body).status_code == 422


@pytest.mark.parametrize("value", [True, 0.0, "0", -1])
def test_human_edit_expected_version_is_a_strict_nonnegative_integer(api, value):
    candidate = open_owner(api)
    assert api.client.post(candidate_url(api, candidate) + "/versions", json=edit_body(expected_version=value)).status_code == 422


@pytest.mark.parametrize("body", [{"origin": "owner_text", "text": ""}, {"origin": "owner_text", "text": " "},
                                  {"origin": "owner_text", "text": "x" * 2001}, {"origin": "unsupported", "text": "SYNTHETIC"},
                                  {"origin": "report_gap", "report_id": "x" * 81, "gap_row_id": "gap"}])
def test_open_candidate_refuses_blank_overlong_or_unknown_origin_inputs(api, body):
    assert api.client.post(api.url, json=body).status_code == 422


@pytest.mark.parametrize("fingerprint", ["0" * 63, "g" * 64, "0" * 65])
def test_start_refuses_malformed_preview_fingerprint(api, fingerprint):
    candidate = edited(api)
    assert api.client.post(candidate_url(api, candidate) + "/kill-search", json={"preview_fingerprint": fingerprint}).status_code == 422


def test_run_keys_never_replay_across_researches_or_candidates(api):
    first = open_owner(api)
    second = open_owner(api, rid=other_research(api))
    first_run = api.client.post(candidate_url(api, first) + "/decompose", headers={"Idempotency-Key": "same"}).json()
    second_base = f"/api/researches/{second['research_id']}/candidates/{second['id']}"
    second_run = api.client.post(second_base + "/decompose", headers={"Idempotency-Key": "same"}).json()
    assert first_run["id"] != second_run["id"]
    for run in (first_run, second_run):
        assert execute(api, run)["status"] == "completed"
    first_kill, _ = start(api, first, "same")
    plan = api.client.get(second_base + "/kill-search/plan").json()
    second_kill = api.client.post(second_base + "/kill-search", json={"preview_fingerprint": plan["preview_fingerprint"]}, headers={"Idempotency-Key": "same"})
    assert second_kill.status_code == 202 and second_kill.json()["id"] != first_kill["id"]


def test_api_has_no_candidate_trash_restore_or_extra_search_list_route(api):
    candidate = open_owner(api)
    base = candidate_url(api, candidate)
    # 405 when a built SPA's catch-all GET route matches the path; either way no route handles it.
    assert api.client.post(base + "/trash").status_code in (404, 405)
    assert api.client.post(base + "/restore").status_code in (404, 405)
    assert api.client.get(base + "/kill-searches").status_code == 404
