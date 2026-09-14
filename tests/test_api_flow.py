"""Model-independent end-to-end checks of the local API, worker and persistence.

Uses the test-only FakeAdapter, mocked OpenAlex HTTP and a fake PDF fetcher. These
show workflow/persistence behavior (A–G deterministic parts), not model quality or
live provider access.
"""

import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents.fetch import FetchResult
from deixis.storage import db
from fakes import FakeAdapter, envelope, valid_response
from helpers import make_pdf

WORKS = [
    {
        "id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/a", "display_name": "SYNTHETIC diffusion channel scheduling",
        "publication_year": 2021, "type": "article", "authorships": [], "ids": {"openalex": "https://openalex.org/W1"},
        "primary_location": {"version": "publishedVersion", "source": {"display_name": "Synthetic J"}},
        "best_oa_location": {"pdf_url": "https://example.org/w1.pdf", "version": "publishedVersion"},
        "abstract_inverted_index": {"We": [0], "schedule": [1], "molecule": [2], "releases.": [3]},
    },
    {
        "id": "https://openalex.org/W2", "doi": None, "display_name": "SYNTHETIC relay budget", "publication_year": 2019,
        "type": "article", "authorships": [], "ids": {}, "primary_location": {}, "best_oa_location": None,
        "abstract_inverted_index": {"Relays": [0], "share": [1], "nutrients.": [2]},
    },
    {
        "id": "https://openalex.org/W3", "doi": "https://doi.org/10.1/c", "display_name": "SYNTHETIC molecule schedule letter",
        "publication_year": 2017, "type": "article", "authorships": [], "ids": {},
        "primary_location": {"version": "publishedVersion"},
        "best_oa_location": {"pdf_url": "https://example.org/w3-manuscript.pdf", "version": "submittedVersion"},
        "abstract_inverted_index": {"Molecule": [0], "schedule": [1], "letter.": [2]},
    },
]


def openalex_client(status=200):
    def handler(request):
        if status != 200:
            return httpx.Response(status, headers={"retry-after": "60"})
        return httpx.Response(200, json={"meta": {"count": len(WORKS)}, "results": WORKS})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def fake_fetch(url):
    return FetchResult("ok", data=make_pdf(["SYNTHETIC page one: molecule release schedule minimizes error."]), final_url=url, http_status=200)


def app_for(tmp_path, adapter=None, http_status=200):
    settings = Settings(data_dir=tmp_path / "data", port=8765)
    return create_app(settings, adapters={"fake": adapter or FakeAdapter()}, http_client=openalex_client(http_status),
                      fetcher=fake_fetch, extra_hosts=("testserver",))


def session(client):
    token = client.get("/api/session").json()["csrf_token"]
    client.headers["x-deixis-csrf"] = token
    return client


def wait_run(client, rid, run_id, statuses=("completed", "failed", "paused", "cancelled"), timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        view = client.get(f"/api/researches/{rid}").json()
        run = next(r for r in view["runs"] if r["id"] == run_id)
        if run["status"] in statuses:
            return view, run
        time.sleep(0.1)
    raise AssertionError(f"run did not finish: {run}")


def create(client, **overrides):
    body = {"question": "How is molecule release scheduling optimized?", "model_connection": "fake", "effort": "quick"} | overrides
    response = client.post("/api/researches", json=body)
    assert response.status_code == 201, response.text
    return response.json()["research"]["id"]


def test_question_to_cited_answer_and_restart(tmp_path):
    adapter = FakeAdapter()
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        rid = create(client)
        first = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}, headers={"Idempotency-Key": "k1"}).json()
        again = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}, headers={"Idempotency-Key": "k1"}).json()
        assert first["id"] == again["id"]  # F: double submit does not create a second run

        view, run = wait_run(client, rid, first["id"])
        assert run["status"] == "completed", run
        assert view["counts"]["found"] == 3 and view["counts"]["unique"] == 3
        assert all(s["selection"]["origin"] == "model_proposal" for s in view["sources"])

        second = next(s for s in view["sources"] if "relay" in s["title"])
        stale = client.patch(f"/api/researches/{rid}/selections/{second['source_version_id']}",
                             json={"state": "excluded", "expected_version": second["selection"]["version"] - 1})
        assert stale.status_code == 409
        changed = client.patch(f"/api/researches/{rid}/selections/{second['source_version_id']}",
                               json={"state": "excluded", "expected_version": second["selection"]["version"], "reason": "not about scheduling"})
        assert changed.status_code == 200 and changed.json()["origin"] == "user"

        upload = client.post(f"/api/researches/{rid}/uploads", files={"file": ("my_notes.pdf", make_pdf(["SYNTHETIC uploaded molecule schedule notes."]), "application/pdf")})
        assert upload.status_code == 201

        answer_run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, answer_run["id"])
        assert run["status"] == "completed", run
        answer = view["answers"][0]
        assert answer["status"] == "structurally_valid" and answer["applicability"] == "current"
        evidence = answer["claims"][0]["evidence"][0]
        assert evidence["source_version_id"] != second["source_version_id"]  # excluded source not given to the model
        given = adapter.calls[-1]
        assert second["source_version_id"] not in given["allowlist"]["source_ids"]

        passage = client.get(f"/api/researches/{rid}/passages/{evidence['passage_id']}").json()
        assert passage["source"]["id"] == evidence["source_version_id"]
        pdf_sources = [s for s in view["sources"] if s["access"]["assets"]]
        assert len(pdf_sources) == 2  # downloaded OA PDF + uploaded file
        letter = next(s for s in view["sources"] if "letter" in s["title"])
        assert letter["access"]["oa_pdf_version"] == "submittedVersion" and not letter["access"]["assets"]  # other version not attached
        asset_id = pdf_sources[0]["access"]["assets"][0]["id"]
        assert client.get(f"/api/researches/{rid}/assets/{asset_id}").headers["content-type"] == "application/pdf"
        before = view

    with TestClient(app_for(tmp_path)) as client:  # F: backend restart
        after = client.get(f"/api/researches/{rid}").json()
        assert after["answers"][0]["claims"] == before["answers"][0]["claims"]
        assert [s["selection"] for s in after["sources"]] == [s["selection"] for s in before["sources"]]

        session(client)
        other = create(client, question="Unrelated research B question")
        leak = client.get(f"/api/researches/{other}/passages/{evidence['passage_id']}")
        assert leak.status_code == 404  # T08: passage outside research B's corpus


def test_invalid_output_is_repaired_once_then_kept_as_unverified_draft(tmp_path):
    def bad(si):
        if si["task_type"] != "grounded_answer":
            return valid_response(si)
        return json.dumps(envelope(si, "deixis.grounded_answer_draft.v1") | {
            "answer_language": "en",
            "claims": [{"claim_label": "c1", "text": "Invented", "support_type": "source_stated", "passage_ids": ["psg_INVENTED0001"]}],
            "limitations": [], "unanswered_aspects": [], "capability_notice": None,
        })

    adapter = FakeAdapter(bad)
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        rid = create(client, source_scope="attached")
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC molecule text"]), "application/pdf")})
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, run["id"])
        answer = view["answers"][0]
        assert answer["status"] == "unverified_draft" and answer["claims"] == []
        assert {i["code"] for i in answer["validation"]["issues"]} == {"unknown_passage_id"}
        assert len(adapter.calls) == 2  # original + one repair
        assert run["usage"]["model_calls"] == 2


def test_attached_only_scope_never_searches(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = create(client, source_scope="attached")
        assert client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).status_code == 422
        view = client.get(f"/api/researches/{rid}").json()
        assert view["search_runs"] == [] and view["scope"]["providers"] == []


def test_provider_rate_limit_pauses_without_fallback(tmp_path):
    with TestClient(app_for(tmp_path, http_status=429)) as client:
        session(client)
        rid = create(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, run = wait_run(client, rid, run["id"])
        assert run["status"] == "paused" and run["pause_reason"] == "provider_rate_limited"
        assert view["search_runs"][0]["status"] == "rate_limited"
        assert view["counts"]["found"] == 0  # E: not shown as zero results of a completed search


def test_model_not_ready_pauses_run(tmp_path):
    with TestClient(app_for(tmp_path, FakeAdapter(ready=False))) as client:
        session(client)
        rid = create(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        _, run = wait_run(client, rid, run["id"])
        assert (run["status"], run["pause_reason"]) == ("paused", "model_connection_not_ready")


def test_backend_crash_mid_run_is_recovered_as_paused_then_resumable(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as client:
        session(client)
        rid = create(client, source_scope="attached")
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC molecule text"]), "application/pdf")})
    conn = db.connect(tmp_path / "data" / "library.sqlite")
    conn.execute(
        "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
        " VALUES ('run_CRASHED000001', ?, 1, 'answer', 'running', 'answer', ?, 'now', 'now')",
        (rid, json.dumps({"max_model_calls": 4, "max_provider_requests": 2, "max_candidates": 15, "max_answer_passages": 8})),
    )
    conn.execute(
        "INSERT INTO run_steps (id, run_id, operation_key, kind, status, attempt) VALUES ('stp_CRASHED000001', 'run_CRASHED000001', 'grounded_answer', 'model:grounded_answer', 'running', 1)"
    )
    conn.close()

    with TestClient(app_for(tmp_path)) as client:
        session(client)
        assert client.get("/api/health").json()["recovered"] == {"runs": 1, "steps": 1, "model_sessions": 0}
        view = client.get(f"/api/researches/{rid}").json()
        run = view["runs"][0]
        assert (run["status"], run["pause_reason"]) == ("paused", "backend_restarted")
        assert run["steps"][0]["status"] == "outcome_unknown"
        client.post(f"/api/runs/{run['id']}/resume")
        view, run = wait_run(client, rid, run["id"])
        assert run["status"] == "completed" and view["answers"][0]["status"] == "structurally_valid"


def test_second_instance_does_not_start_a_worker(tmp_path):
    with TestClient(app_for(tmp_path)) as first, TestClient(app_for(tmp_path)) as second:
        assert first.get("/api/health").json()["worker"] == "owner"
        assert second.get("/api/health").json()["worker"] == "not_owner"


def test_waiting_instance_takes_over_after_owner_stops(tmp_path):
    first = TestClient(app_for(tmp_path)).__enter__()
    second = TestClient(app_for(tmp_path)).__enter__()
    try:
        assert second.get("/api/health").json()["worker"] == "not_owner"
        first.__exit__(None, None, None)  # e.g. a restart that starts before the old process has exited
        deadline = time.time() + 5
        while second.get("/api/health").json()["worker"] != "owner" and time.time() < deadline:
            time.sleep(0.1)
        assert second.get("/api/health").json()["worker"] == "owner"
    finally:
        second.__exit__(None, None, None)


def test_mutations_require_csrf_and_known_host(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        body = {"question": "x question", "model_connection": "fake"}
        assert client.post("/api/researches", json=body).status_code == 403
        session(client)
        assert client.post("/api/researches", json=body, headers={"origin": "http://evil.example"}).status_code == 403
        assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 403
        assert client.post("/api/researches", json=body | {"model_connection": "codex"}).status_code == 422
