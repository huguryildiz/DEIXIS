"""Model-free: what an adapter says it sent in place of the step schema is stored with the validation record (D93)."""

import asyncio
import json

from deixis.config import Settings
from deixis.domain import skill
from deixis.models.adapter import ModelStepResult
from deixis.storage import db
from deixis.workflow.flow import FlowDeps, ResearchFlow
from deixis.workflow.store import Store
from fakes import FakeAdapter, valid_response

TRANSPORT = {"schema_transform": "SYNTHETIC.v1", "sent_schema_sha256": "sha256:" + "0" * 64, "filled_nulls": ["/x"]}


def run(tmp_path, transport):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC question?", "attached", "quick", [], "fake", "fake-model", "en")
    sid = store.create_upload_source("SYNTHETIC source")
    pid = store._insert_passage(sid, None, "abstract", None, None, "synthetic_fixture", None, None,
                                "SYNTHETIC passage about release scheduling.")
    adapter = FakeAdapter(fail=lambda si: ModelStepResult("completed", raw_text=valid_response(si),
                                                          resolved_model="fake-model", transport=transport))
    flow = ResearchFlow(FlowDeps(Settings(data_dir=tmp_path / "data", port=8873), store, {"fake": adapter},
                                 skill.load_skill_package(), None))
    run = store.create_run(rid, "answer", {"max_model_calls": 2, "max_provider_requests": 0}, None)
    store.update_run(run["id"], status="running")
    result = asyncio.run(flow._model_step(store.run(run["id"]), store.scope(rid), "synthetic:answer", "grounded_answer",
                                          source_ids=[sid], passage_rows=[store.passage(pid)]))
    validation = json.loads(store.conn.execute("SELECT validation_json FROM model_sessions WHERE step_input_id = ?",
                                               (result["step_input_id"],)).fetchone()[0])
    store.conn.close()
    return result, validation


def test_the_adapters_transport_record_is_stored_with_the_validation(tmp_path):
    result, validation = run(tmp_path, TRANSPORT)
    assert not result.get("invalid") and validation["ok"]
    assert validation["transport"] == TRANSPORT


def test_no_transport_record_adds_no_key(tmp_path):
    _, validation = run(tmp_path, None)
    assert "transport" not in validation
