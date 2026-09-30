"""Stored legacy discovery is readable, but every route that could resume it is closed."""

import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.storage import db
from deixis.storage.db import now
from deixis.workflow.store import LegacyResearchReadOnly, Store
from deixis.workflow.views import research_view
from deixis.workflow.worker import Worker
from fakes import FakeAdapter
from helpers import make_pdf
from test_api_flow import wait_run


def old_research(store):
    return store.create_research("SYNTHETIC old question", "attached_and_academic", "quick", ["openalex"],
                                 "fake", "fake-model", "en", search_workflow="legacy")


def old_run(store, rid, kind="discovery", status="paused", key=None):
    run_id = f"run_old_{kind}_{status}_{key or 'one'}"
    store.conn.execute(
        "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, idempotency_key,"
        " created_at, updated_at) VALUES (?, ?, 1, ?, ?, 'discovery', '{}', ?, ?, ?)",
        (run_id, rid, kind, status, key, now(), now()),
    )
    return run_id


@pytest.fixture
def store(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    yield Store(conn)
    conn.close()


def test_stored_legacy_plan_and_screening_notes_remain_readable(store):
    rid = old_research(store)
    run_id = old_run(store, rid, status="completed")
    plan = {"output_type": "SearchPlan", "result": {
        "question_interpretation": "old interpretation", "search_rationale": "old rationale",
        "scope_boundaries": ["one provider"],
        "concepts": [{"label": "old concept", "synonyms": ["stored synonym"]}]}}
    for key, kind, output in (("search_plan", "model:search_plan", plan),
                              ("screening", "model:screening", {"result": {"notes": "old screening note"}})):
        step = store.step(run_id, key, kind)
        store.finish_step(step["id"], "succeeded", output=output)
    view = research_view(store, rid)
    assert view["research"]["read_only_reason"] == "legacy_research_read_only"
    assert view["runs"][0]["plan"]["concepts"][0]["synonyms"] == ["stored synonym"]
    assert view["runs"][0]["screening_notes"][0]["text"] == "old screening note"
    assert "queue" not in view["counts"]


def test_legacy_answer_uses_stored_plan_concepts(tmp_path):
    adapter = FakeAdapter()
    app = create_app(Settings(data_dir=tmp_path / "data"), adapters={"fake": adapter},
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        store = app.state.store
        rid = old_research(store)
        run_id = old_run(store, rid, status="completed")
        step = store.step(run_id, "search_plan", "model:search_plan")
        store.finish_step(step["id"], "succeeded", output={"output_type": "SearchPlan", "result": {
            "question_interpretation": "old question", "search_rationale": "old rationale", "scope_boundaries": [],
            "concepts": [{"label": "stored anchor phrase", "synonyms": ["prior term"]}]}})
        assert "stored" in app.state.worker.flow._topic_terms(rid, store.scope(rid))
        upload = client.post(f"/api/researches/{rid}/uploads", files={"file": (
            "old.pdf", make_pdf(["SYNTHETIC stored anchor phrase supports this answer."]), "application/pdf")})
        assert upload.status_code == 201, upload.text
        response = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"})
        assert response.status_code == 202, response.text
        view, run = wait_run(client, rid, response.json()["id"])
        assert run["status"] == "completed" and view["answers"][0]["status"] == "structurally_valid"
        assert not any(step["operation_key"] == "answer_start_snapshot" for step in run["steps"])
        assert not any(step["operation_key"] == "criterion_phrases" for step in run["steps"])
        assert any(call["task_type"] == "grounded_answer" for call in adapter.calls)


def test_store_rejects_scope_edits_and_all_discovery_queue_paths(store):
    rid = old_research(store)
    with pytest.raises(LegacyResearchReadOnly):
        store.revise_scope(rid, store.research(rid)["version"], "changed question", None)
    with pytest.raises(LegacyResearchReadOnly):
        store.set_seed(rid, store.research(rid)["version"], "missing")
    for kind in ("discovery", "fulltext_fetch", "fulltext_adjudication"):
        with pytest.raises(LegacyResearchReadOnly):
            store.create_run(rid, kind, {}, "used-key")
        paused = old_run(store, rid, kind=kind)
        with pytest.raises(LegacyResearchReadOnly):
            store.update_run(paused, status="queued")
        with pytest.raises(LegacyResearchReadOnly):
            store.update_run(paused, status="running")
    completed = old_run(store, rid, status="completed", key="used-key")
    with pytest.raises(LegacyResearchReadOnly):
        store.create_run(rid, "discovery", {}, "used-key")
    with pytest.raises(LegacyResearchReadOnly):
        store.queue_failed_search_retry(completed)
    for path in (store.submit_approval, store.request_term_suggestions, store.choose_code_query):
        with pytest.raises(LegacyResearchReadOnly):
            path(completed, {}) if path == store.submit_approval else path(completed)
    # Answer and auxiliary runs remain available. Each is ended before the next queue operation.
    for kind in ("answer", "pdf_collection", "pdf_ocr", "table_columns", "table_fill", "cell_recheck", "research_title", "report"):
        run = store.create_run(rid, kind, {}, None)
        store.update_run(run["id"], status="running")
        store.update_run(run["id"], status="completed")


def test_api_rejects_each_legacy_discovery_entry_and_keeps_answer_resume(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data"), adapters={}, start_worker=False,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        store = app.state.store
        rid = old_research(store)
        paused = old_run(store, rid)
        for kind in ("discovery", "fulltext_fetch", "fulltext_adjudication"):
            response = client.post(f"/api/researches/{rid}/runs", json={"kind": kind})
            assert (response.status_code, response.json()["detail"]) == (409, "legacy_research_read_only")
        routes = [
            ("post", f"/api/runs/{paused}/resume", None),
            ("post", f"/api/runs/{paused}/retry_failed", None),
            ("post", f"/api/runs/{paused}/protocol-approval", {}),
            ("post", f"/api/runs/{paused}/term-suggestions", None),
            ("post", f"/api/runs/{paused}/search-query-choice", None),
            ("post", f"/api/researches/{rid}/seed", {"expected_version": 0, "source_version_id": "srv_missing0"}),
            ("post", f"/api/researches/{rid}/scope", {"expected_version": 0, "question": "changed question"}),
        ]
        for method, path, body in routes:
            response = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
            assert (response.status_code, response.json()["detail"]) == (409, "legacy_research_read_only"), path
        no_source_answer = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"})
        assert no_source_answer.status_code == 422
        assert no_source_answer.json()["detail"] == "Include at least one source before generating an answer"
        answer = old_run(store, rid, kind="answer")
        response = client.post(f"/api/runs/{answer}/resume")
        assert response.status_code == 200 and response.json()["status"] == "queued"


@pytest.mark.parametrize("status", ["queued", "running", "pause_requested", "paused"])
def test_recovery_then_cleanup_cancels_legacy_discovery_atomically(store, tmp_path, status):
    rid = old_research(store)
    run_id = old_run(store, rid, status=status)
    old_run(store, rid, kind="answer", status="queued")
    worker = Worker(store, None, tmp_path / "worker.lock")
    worker.recover()
    assert worker.cancel_legacy_discovery() == 1
    assert store.run(run_id)["status"] == "cancelled"
    events = [e for e in store.events_after(rid, 0) if e["run_id"] == run_id and e["type"] == "run_cancelled"]
    assert len(events) == 1 and events[0]["payload"]["reason"] == "legacy_workflow_removed"
    assert store.conn.execute("SELECT status FROM runs WHERE research_id = ? AND kind = 'answer'", (rid,)).fetchone()[0] == "queued"
    assert worker.cancel_legacy_discovery() == 0


def test_cleanup_rolls_back_status_when_event_cannot_be_written(store, tmp_path):
    rid = old_research(store)
    run_id = old_run(store, rid, status="queued")
    store.conn.execute("CREATE TRIGGER refuse_event BEFORE INSERT ON events WHEN new.payload_json LIKE '%legacy_workflow_removed%'"
                       " BEGIN SELECT RAISE(ABORT, 'event refused'); END")
    worker = Worker(store, None, tmp_path / "worker.lock")
    worker.recover()
    with pytest.raises(Exception, match="event refused"):
        worker.cancel_legacy_discovery()
    assert store.run(run_id)["status"] == "queued"
