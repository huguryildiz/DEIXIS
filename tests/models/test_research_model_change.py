"""UI parity S17, F10: a person moves one role of a research to another model. SYNTHETIC records and the fake adapter:
these tests show which model each step asks for and what is recorded, not model quality.
"""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from deixis.domain.rules import RevisionConflict
from fakes import FakeAdapter
from test_api_flow import app_for, create, session
from test_table_extraction import cell, execute, fill, library


def version(lib):
    return lib.store.research(lib.rid)["version"]


def change(lib, model, role="answer", connection="fake", effort=None, reason=None):
    return lib.store.change_role_model(lib.rid, role, connection, model, effort, version(lib), reason)


def stored_steps(lib, run_id):
    """Everything a finished run's model steps hold: their inputs and sessions, byte for byte."""
    inputs = lib.conn.execute("SELECT * FROM step_inputs WHERE run_id = ? ORDER BY rowid", (run_id,)).fetchall()
    sessions = lib.conn.execute("SELECT * FROM model_sessions WHERE run_id = ? ORDER BY rowid", (run_id,)).fetchall()
    steps = lib.conn.execute("SELECT * FROM run_steps WHERE run_id = ? ORDER BY rowid", (run_id,)).fetchall()
    return [tuple(r) for r in inputs], [tuple(r) for r in sessions], [tuple(r) for r in steps]


def test_a_model_change_is_recorded_and_only_later_steps_use_it(tmp_path):
    lib = library(tmp_path)
    filled = fill(lib)
    execute(lib, filled)
    before = stored_steps(lib, filled["id"])
    assert {s[1] for s in lib.adapter.sent} == {"fake-model"}

    made = change(lib, "fake-model-2", effort="high", reason="model_connection_not_ready")
    assert made["role"] == "answer" and made["changed_by"] == "person" and made["reason"] == "model_connection_not_ready"
    assert made["from"] == {"connection": "fake", "model": "fake-model", "reasoning_effort": None}
    assert made["to"] == {"connection": "fake", "model": "fake-model-2", "reasoning_effort": "high"}
    scope = lib.store.scope(lib.rid)
    assert (scope["model_connection"], scope["requested_model"], scope["reasoning_effort"]) == ("fake", "fake-model-2", "high")
    raw = lib.conn.execute("SELECT requested_model FROM scope_revisions WHERE research_id = ?", (lib.rid,)).fetchone()[0]
    assert raw == "fake-model"  # the scope revision itself is never rewritten
    event = lib.conn.execute("SELECT payload_json FROM events WHERE research_id = ? AND type = 'research_model_changed'",
                             (lib.rid,)).fetchone()
    assert json.loads(event[0])["to"]["model"] == "fake-model-2"

    calls = len(lib.adapter.sent)
    assert execute(lib, filled)["status"] == "completed"  # the finished run again: its steps return what they stored
    assert len(lib.adapter.sent) == calls and stored_steps(lib, filled["id"]) == before

    checked = lib.tables.request_recheck(lib.rid, lib.tid, lib.cid, lib.published, 1, None)
    assert execute(lib, checked)["status"] == "completed"
    assert lib.adapter.sent[-1] == ("cell_extraction", "fake-model-2", "high")
    (payload, requested, resolved) = lib.conn.execute(
        "SELECT si.payload_json, m.requested_model, m.resolved_model FROM step_inputs si"
        " JOIN model_sessions m ON m.step_input_id = si.id WHERE si.run_id = ?", (checked["id"],)).fetchone()
    assert json.loads(payload)["model"]["requested_model"] == "fake-model-2" and requested == resolved == "fake-model-2"
    assert cell(lib, lib.published)["pending_proposal"]["model"]["resolved_model"] == "fake-model-2"
    assert cell(lib, lib.published)["current"]["model"]["resolved_model"] == "fake-model"  # the earlier value keeps its model


def test_the_change_history_is_append_only(tmp_path):
    lib = library(tmp_path)
    change(lib, "fake-model-2")
    change(lib, "fake-model")
    history = lib.store.model_changes(lib.rid)
    assert [(c["from"]["model"], c["to"]["model"]) for c in history] == [("fake-model", "fake-model-2"), ("fake-model-2", "fake-model")]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        lib.conn.execute("UPDATE research_model_changes SET reason = 'x'")
    with pytest.raises(sqlite3.IntegrityError, match="purge authorization"):
        lib.conn.execute("DELETE FROM research_model_changes")
    with pytest.raises(ValueError):
        change(lib, "fake-model")  # the role already uses it: nothing to record
    with pytest.raises(RevisionConflict):
        lib.store.change_role_model(lib.rid, "answer", "fake", "fake-model-2", None, version(lib) - 1)
    lib.store.trash_research(lib.rid)
    lib.store.purge_research(lib.rid)  # the purge authorizes the delete; the rows go with their research
    assert lib.conn.execute("SELECT COUNT(*) FROM research_model_changes").fetchone()[0] == 0


def test_literature_and_reviewer_changes_move_only_their_role(tmp_path):
    lib = library(tmp_path)
    change(lib, "fake-lit", role="literature")
    made = change(lib, "fake-review", role="reviewer")
    assert made["from"] == {"connection": None, "model": None, "reasoning_effort": None, "review_mode": "default"}
    scope = lib.store.scope(lib.rid)
    assert (scope["literature_connection"], scope["literature_model"]) == ("fake", "fake-lit")
    assert (scope["review_mode"], scope["review_connection"], scope["review_model"]) == ("custom", "fake", "fake-review")
    assert scope["requested_model"] == "fake-model"
    execute(lib, fill(lib))
    assert {s[1] for s in lib.adapter.sent} == {"fake-model"}  # a cell extraction runs on the answer role


def test_a_change_is_refused_while_a_run_executes_and_a_resumed_run_takes_it(tmp_path):
    lib = library(tmp_path)
    lib.adapter.ready = False  # the model is down: the run pauses before anything is sent
    run = lib.tables.request_recheck(lib.rid, lib.tid, lib.cid, lib.published, 0, None)
    paused = execute(lib, run)
    assert (paused["status"], paused["pause_reason"]) == ("paused", "model_connection_not_ready") and lib.adapter.sent == []

    lib.store.update_run(run["id"], status="running")
    with pytest.raises(RevisionConflict, match="pause it"):
        change(lib, "fake-model-2")
    lib.store.update_run(run["id"], status="paused")
    change(lib, "fake-model-2", reason="model_connection_not_ready")

    lib.adapter.ready = True
    lib.store.resume_run(run["id"])
    assert execute(lib, run)["status"] == "completed"
    assert lib.adapter.sent == [("cell_extraction", "fake-model-2", None)]


def test_model_mismatch_is_still_enforced_after_a_change(tmp_path):
    lib = library(tmp_path)
    change(lib, "fake-model-2")
    lib.adapter.resolved_model = "fake-model"  # the connection answers with the old model
    run = lib.tables.request_recheck(lib.rid, lib.tid, lib.cid, lib.published, 0, None)
    stopped = execute(lib, run)
    assert (stopped["status"], stopped["pause_reason"]) == ("paused", "model_mismatch")
    assert stopped["error"] == {"requested_model": "fake-model-2", "resolved_model": "fake-model"}
    assert cell(lib, lib.published)["revisions"] == []  # the mismatched output is recorded but never used
    session = lib.conn.execute("SELECT requested_model, resolved_model FROM model_sessions WHERE run_id = ?", (run["id"],)).fetchone()
    assert tuple(session) == ("fake-model-2", "fake-model")


def test_model_change_api(tmp_path):
    adapter = FakeAdapter(models=["fake-model", "fake-model-2"], efforts=["low", "high"])
    with TestClient(app_for(tmp_path, adapter)) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        view = client.get(f"/api/researches/{rid}").json()
        assert view["model_changes"] == []
        url = f"/api/researches/{rid}/models"
        body = {"role": "answer", "connection": "fake", "model": "fake-model-2", "reasoning_effort": "high",
                "expected_version": view["research"]["version"]}

        assert client.put(url, json=body | {"model": "invented"}).status_code == 422  # not listed: refused, never replaced
        assert client.put(url, json=body | {"reasoning_effort": "max"}).status_code == 422
        assert client.put(url, json=body | {"connection": "nowhere"}).status_code == 422
        assert client.put(url, json=body | {"role": "embedding"}).status_code == 422
        assert client.put(url, json=body | {"expected_version": body["expected_version"] + 1}).status_code == 409
        assert client.put(url, json=body, headers={"x-deixis-csrf": "wrong"}).status_code == 403

        changed = client.put(url, json=body | {"reason": "model_connection_not_ready"})
        assert changed.status_code == 200, changed.text
        shown = changed.json()
        assert shown["scope"]["requested_model"] == "fake-model-2" and shown["scope"]["reasoning_effort"] == "high"
        (entry,) = shown["model_changes"]
        assert (entry["role"], entry["from"]["model"], entry["to"]["model"], entry["reason"]) == (
            "answer", "fake-model", "fake-model-2", "model_connection_not_ready")
        assert client.get(f"/api/researches/{rid}").json()["model_changes"] == shown["model_changes"]
        assert client.put(url, json=body | {"expected_version": shown["research"]["version"]}).status_code == 422  # unchanged

        reviewer = client.put(url, json={"role": "reviewer", "connection": "fake", "model": "fake-model",
                                         "reasoning_effort": None, "expected_version": shown["research"]["version"]}).json()
        assert reviewer["reviewer"] == {"mode": "custom", "connection": "fake", "model": "fake-model", "reasoning_effort": None}
        assert [c["role"] for c in reviewer["model_changes"]] == ["answer", "reviewer"]
