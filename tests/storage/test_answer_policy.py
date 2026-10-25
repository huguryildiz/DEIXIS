"""Which inspection policy an answer gets, and when an academic answer is refused (D242); all evidence is synthetic."""
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.storage import db
from deixis.storage.db import dumps, now
from deixis.workflow import small_batch
from deixis.workflow.store import Store
from fakes import FakeAdapter


@pytest.fixture
def store(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    yield Store(conn)
    conn.close()


def research(store, *, source_scope="academic"):
    return store.create_research("SYNTHETIC exercise", source_scope, "quick", ["openalex"],
                                 "fake", "fake-model", "en")


def stored_run(store, rid, kind="discovery", status="paused", *, budget=None):
    from uuid import uuid4
    run_id = "run_" + uuid4().hex
    budget = budget or small_batch.freeze_budget({"max_model_calls": 5}, "quick", "off")
    store.conn.execute(
        "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json,"
        " created_at, updated_at) VALUES (?, ?, 1, ?, ?, 'inspection', ?, ?, ?)",
        (run_id, rid, kind, status, dumps(budget), now(), now()))
    return run_id


def test_answer_policy_uses_latest_completed_discovery(store):
    rid = research(store, source_scope="attached_and_academic")
    stored_run(store, rid, status="completed")
    latest = stored_run(store, rid, status="completed")
    store.conn.execute("UPDATE runs SET created_at = '9999' WHERE id = ?", (latest,))
    answer = stored_run(store, rid, "answer")
    budget = small_batch.answer_budget(store, rid, 1, {"max_model_calls": 5})
    assert small_batch.enabled(budget) and budget["inspection"]["list_run_id"] == latest
    assert store.resume_run(answer)["status"] == "queued"


@pytest.mark.parametrize("earlier_discovery", [False])
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
