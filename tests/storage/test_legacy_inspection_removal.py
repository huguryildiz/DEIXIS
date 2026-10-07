"""D242 stored sw policy compatibility; all evidence is synthetic."""
import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.storage import db
from deixis.storage.db import dumps, now
from deixis.workflow import small_batch, waiting
from deixis.workflow.store import Store, LegacyInspectionPolicyRemoved
from deixis.workflow.views import research_view
from deixis.workflow.worker import Worker
from fakes import FakeAdapter
from test_stage_decisions import record

FIXTURE = json.loads((Path(__file__).parents[1] / "fixtures/legacy_sw_inspection.json").read_text())


@pytest.fixture
def store(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    yield Store(conn)
    conn.close()


def research(store, *, workflow="sw", source_scope="academic"):
    return store.create_research("SYNTHETIC exercise", source_scope, "quick", ["openalex"],
                                 "fake", "fake-model", "en", search_workflow=workflow)


def stored_run(store, rid, kind="discovery", status="paused", *, budget=None, key=None):
    # A persisted pre-D242 run, not a new executable request.
    from uuid import uuid4
    run_id = "run_old_" + uuid4().hex
    store.conn.execute(
        "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, idempotency_key,"
        " created_at, updated_at) VALUES (?, ?, 1, ?, ?, 'inspection', ?, ?, ?, ?)",
        (run_id, rid, kind, status, dumps(budget or FIXTURE["budget"]), key, now(), now()))
    return run_id


@pytest.mark.parametrize("kind", ["discovery", "fulltext_fetch", "fulltext_adjudication", "answer"])
@pytest.mark.parametrize("status", ["queued", "running", "pause_requested", "paused"])
def test_recovery_cancels_removed_policy_atomically_and_only_once(store, tmp_path, kind, status):
    rid = research(store)
    run_id = stored_run(store, rid, kind, status)
    before = store.run(run_id)["budget"]
    worker = Worker(store, None, tmp_path / "lock")
    worker.recover()
    assert worker.cancel_legacy_inspection() == 1
    assert store.run(run_id)["status"] == "cancelled"
    assert store.run(run_id)["pause_reason"] == "legacy_inspection_policy_removed"
    assert store.run(run_id)["budget"] == before
    events = [e for e in store.events_after(rid, 0) if e["type"] == "run_cancelled"]
    assert len(events) == 1
    assert events[0]["payload"]["reason"] == "legacy_inspection_policy_removed"
    assert worker.cancel_legacy_inspection() == 0


def test_event_failure_rolls_back_cancellation(store, tmp_path):
    rid = research(store)
    run_id = stored_run(store, rid, status="queued")
    store.conn.execute("CREATE TRIGGER refuse_event BEFORE INSERT ON events"
                       " WHEN new.payload_json LIKE '%legacy_inspection_policy_removed%'"
                       " BEGIN SELECT RAISE(ABORT, 'event refused'); END")
    with pytest.raises(Exception, match="event refused"):
        Worker(store, None, tmp_path / "lock").cancel_legacy_inspection()
    assert store.run(run_id)["status"] == "queued"


@pytest.mark.parametrize("kind", ["discovery", "fulltext_fetch", "fulltext_adjudication", "answer"])
def test_store_resume_retry_and_dispatch_never_call_a_model(tmp_path, kind):
    adapter = FakeAdapter()
    app = create_app(Settings(data_dir=tmp_path / "data"), adapters={"fake": adapter},
                     extra_hosts=("testserver",), trusted_clients=("testclient",), start_worker=False)
    with TestClient(app) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        store = app.state.store
        rid = research(store)
        run_id = stored_run(store, rid, kind)
        for action in ("resume", "retry_failed"):
            response = client.post(f"/api/runs/{run_id}/{action}")
            assert response.status_code == 409
            assert response.json()["code"] == "legacy_inspection_policy_removed"
            assert response.json()["next_action"] == "new_discovery"
        with pytest.raises(LegacyInspectionPolicyRemoved):
            store.resume_run(run_id)
        with pytest.raises(LegacyInspectionPolicyRemoved):
            store.queue_failed_search_retry(run_id)
        with pytest.raises(LegacyInspectionPolicyRemoved):
            asyncio.run(app.state.worker.flow.execute(run_id))
        assert adapter.calls == []
        assert store.run(run_id)["status"] == "paused"


def test_exceptions_keep_person_reading_attached_and_d119_answers(store, tmp_path):
    ids = []
    rid = research(store)
    ids.append(stored_run(store, rid, "fulltext_adjudication", key="fulltext_adjudication:person:stored"))
    rid = research(store, source_scope="attached")
    ids.append(stored_run(store, rid, "answer"))
    rid = research(store, source_scope="attached_and_academic")
    ids.append(stored_run(store, rid, "answer"))
    rid = research(store, workflow="legacy")
    ids.append(stored_run(store, rid, "answer"))
    rid = research(store)
    ids.append(stored_run(store, rid, budget=small_batch.freeze_budget(
        {"max_model_calls": 5}, "quick", "off")))
    assert Worker(store, None, tmp_path / "lock").cancel_legacy_inspection() == 0
    for run_id in ids:
        assert store.resume_run(run_id)["status"] == "queued"


def test_completed_fixture_retains_answer_claim_anchor_input_and_waiting(store, tmp_path):
    rid = research(store)
    svid, _ = store.upsert_provider_source("openalex", replace(record("stored"), abstract=FIXTURE["abstract"],
                                                             abstract_origin="provider"), None)
    store.add_to_corpus(rid, svid, "search")
    passage = store.passages_for(svid)[0]
    discovery = stored_run(store, rid, status="completed")
    plan = store.step(discovery, "fulltext_plan", "code:fulltext_plan")
    store.finish_step(plan["id"], "succeeded", output={"works": [svid], "already_text": [], "not_reached": []})
    answer = stored_run(store, rid, "answer", "completed")
    step = store.step(answer, "answer", "model:grounded_answer")
    payload = {"step_input_id": "input_old", "task_type": "grounded_answer", "scope_revision": 1,
               "skill_package_hash": "stored-package", "sources": [{"source_id": svid}],
               "passages": [passage | {"passage_id": passage["id"]}]}
    store.insert_step_input(step["id"], rid, answer, 1, payload, "stored base", "stored developer", "stored message", {})
    store.finish_step(step["id"], "succeeded", output={"result": {"answer_markdown": FIXTURE["answer"]}})
    store.save_answer(rid, answer, step["id"], "input_old", 1, "structurally_valid",
                      {"title": "Stored title", "answer_language": "en", "answer_markdown": FIXTURE["answer"],
                       "claims": [{"claim_label": "C1", "text": FIXTURE["claim"], "support_type": "source_stated"}]}, {},
                      [{"claim_label": "C1", "passage_id": passage["id"], "source_id": svid,
                        "anchor_text": FIXTURE["abstract"], "anchor_match": "exact"}])
    before = store.conn.serialize()
    view = research_view(store, rid)
    assert view["answers"][0]["claims"][0]["text"] == FIXTURE["claim"]
    assert view["answers"][0]["claims"][0]["evidence"][0]["anchor_text"] == FIXTURE["abstract"]
    assert any(r["steps"] for r in view["runs"] if r["id"] == answer)
    assert store.step_input_payload("input_old") == payload
    assert waiting.waiting_view(store, rid)["order"] == "fulltext_plan"
    assert Worker(store, None, tmp_path / "lock").cancel_legacy_inspection() == 0
    assert store.conn.serialize() == before


def test_new_answer_cannot_fall_back_to_completed_old_discovery(store):
    rid = research(store)
    stored_run(store, rid, status="completed")
    with pytest.raises(LegacyInspectionPolicyRemoved):
        small_batch.answer_budget(store, rid, 1, {"max_model_calls": 5})


def test_browser_seed_reads_answer_and_waiting_from_the_same_fixture(store):
    from stored_inspection import seed
    rid = seed(store, "fake", "fake-model")
    view = research_view(store, rid)
    assert view["answers"][0]["claims"][0]["evidence"][0]["anchor_text"] == FIXTURE["abstract"]
    assert waiting.waiting_view(store, rid)["count"] == 1
    assert all(run["status"] == "completed" for run in view["runs"])


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_failed_discovery_keeps_attached_answer_executable_and_resumable(tmp_path, monkeypatch, status):
    from helpers import make_pdf
    from deixis.models.adapter import ModelStepResult
    from test_small_batch_races import session
    from test_adjudication_flow import wait

    failed = False

    def fail(si):
        nonlocal failed
        if si["task_type"] == "grounded_answer" and not failed:
            failed = True
            return ModelStepResult("unavailable", error="SYNTHETIC answer interruption")
        return None

    cancellations = []
    original = Worker.cancel_legacy_inspection

    def cancel(worker):
        cancellations.append(worker.instance_id)
        return original(worker)

    monkeypatch.setattr(Worker, "cancel_legacy_inspection", cancel)
    adapter = FakeAdapter(fail=fail)
    app = create_app(Settings(data_dir=tmp_path / "data", port=8877), adapters={"fake": adapter},
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with session(app) as client:
        store = app.state.store
        rid = research(store, source_scope="attached_and_academic")
        stored_run(store, rid, status=status)
        upload = client.post(f"/api/researches/{rid}/uploads",
                             files={"file": ("SYNTHETIC.pdf", make_pdf(["SYNTHETIC exercise lowers fatigue."]),
                                             "application/pdf")})
        assert upload.status_code == 201, upload.text
        budget = small_batch.answer_budget(store, rid, 1, {"max_model_calls": 5})
        assert "inspection" not in budget
        response = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"})
        assert response.status_code == 202, response.text
        run_id = response.json()["id"]
        _, paused = wait(client, rid, run_id)
        assert paused["status"] == "paused", paused
        assert original(app.state.worker) == 0
        resumed = client.post(f"/api/runs/{run_id}/resume")
        assert resumed.status_code == 200, resumed.text
        _, completed = wait(client, rid, run_id)
        assert completed["status"] == "completed", completed
        assert store.conn.execute("SELECT 1 FROM answers WHERE run_id = ?", (run_id,)).fetchone()
        assert cancellations == [app.state.worker.instance_id]
        assert not [e for e in store.events_after(rid, 0)
                    if e["type"] == "run_cancelled" and e.get("run_id") == run_id]


def test_mixed_answer_policy_uses_latest_completed_discovery(store, tmp_path):
    rid = research(store, source_scope="attached_and_academic")
    stored_run(store, rid, status="completed")
    frozen = small_batch.freeze_budget({"max_model_calls": 5}, "quick", "off")
    latest = stored_run(store, rid, status="completed", budget=frozen)
    store.conn.execute("UPDATE runs SET created_at = '9999' WHERE id = ?", (latest,))
    answer = stored_run(store, rid, "answer")
    assert small_batch.enabled(small_batch.answer_budget(store, rid, 1, {"max_model_calls": 5}))
    assert Worker(store, None, tmp_path / "lock").cancel_legacy_inspection() == 0
    assert store.resume_run(answer)["status"] == "queued"


@pytest.mark.parametrize("earlier_discovery", [False, True])
def test_academic_answer_without_completed_discovery_in_current_revision_returns_409(tmp_path, earlier_discovery):
    from test_criterion_passage_flow import page_source
    app = create_app(Settings(data_dir=tmp_path / "data", port=8877), adapters={"fake": FakeAdapter()},
                     extra_hosts=("testserver",), trusted_clients=("testclient",), start_worker=False)
    with TestClient(app) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        store = app.state.store
        rid = research(store)
        if earlier_discovery:
            stored_run(store, rid, status="completed", budget=small_batch.freeze_budget({"max_model_calls": 5}, "quick", "off"))
            store.revise_scope(rid, store.research(rid)["version"], "SYNTHETIC revised exercise", None)
        page_source(store, rid, "SYNTHETIC", ["SYNTHETIC exercise lowers fatigue."], "SYNTHETIC abstract.")
        response = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"})
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "legacy_inspection_policy_removed"
