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
from deixis.workflow.candidates_store import CandidateStore
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


@pytest.mark.parametrize("reader", ["matrix"])
@pytest.mark.parametrize("status,outcome", [("paused", "paused")])
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


@pytest.mark.parametrize("route", ["start"])
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
















import json

from deixis.storage import db

ASPECTS = ["SYNTHETIC aspect one.", "SYNTHETIC aspect two."]


def answer(api):
    run = api.store.create_run(api.rid, "answer", {}, None)
    id_ = db.new_id("ans")
    api.conn.execute(
        "INSERT INTO answers (id, research_id, run_id, scope_revision, status, draft_json, validation_json, report_version,"
        " created_at) VALUES (?, ?, ?, 1, 'structurally_valid', ?, '{}', 1, 'now')",
        (id_, api.rid, run["id"], json.dumps({"title": "SYNTHETIC", "unanswered_aspects": ASPECTS})))
    return f"/api/researches/{api.rid}/answers/{id_}/candidates"


def test_create_reuse_and_list(api):
    url = answer(api)
    first = api.client.post(url, json={"aspect_index": 1, "text": "  SYNTHETIC claim.  "}, headers={"Idempotency-Key": "a"})
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["reused"] is False and body["replayed"] is False and body["card"]["origin"] == "answer_thread"
    assert body["card"]["origin_text"] == "SYNTHETIC claim."
    assert body["card"]["origin_provenance"]["aspect_text"] == ASPECTS[1]
    again = api.client.post(url, json={"aspect_index": 1, "text": "SYNTHETIC other."})
    assert again.status_code == 201 and again.json()["reused"] is True and again.json()["card"]["id"] == body["card"]["id"]
    assert again.json()["replayed"] is False
    generic = api.client.post(url, json={"text": "SYNTHETIC generic claim."}, headers={"Idempotency-Key": "g"})
    assert generic.status_code == 201 and generic.json()["card"]["origin"] == "answer_thread"
    # The same submission again (its response was lost): the same candidate and no second link.
    retry = api.client.post(url, json={"text": "SYNTHETIC generic claim."}, headers={"Idempotency-Key": "g"})
    assert retry.status_code == 201 and retry.json()["replayed"] is True and retry.json()["card"]["id"] == generic.json()["card"]["id"]
    listed = api.client.get(url)
    assert listed.status_code == 200, listed.text
    rows = listed.json()["candidates"]
    assert [(r["aspect_index"], r["origin_text"]) for r in rows] == [(1, "SYNTHETIC claim."), (None, "SYNTHETIC generic claim.")]
    assert all(r["search"] is None and r["run"] is None for r in rows)
    decompose = listed.json()["decompose"]
    assert decompose["model"] == "fake-model" and decompose["max_provider_requests"] == 0
    # The research's candidate list shows them too; nothing was searched.
    assert {c["origin"] for c in api.client.get(api.url).json()} == {"answer_thread"}
    assert api.requests == []
