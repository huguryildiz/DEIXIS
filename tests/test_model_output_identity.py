"""D211 fresh-output identity tests. Scripted adapters only; no provider calls.

new_behavior tests must fail against the complete ab505fd baseline.
preservation tests retain strict validation of scope and stored envelopes.
"""

import asyncio
import copy
import json
from pathlib import Path

import pytest

from deixis.domain import contracts
from deixis.storage.db import new_id
from deixis.workflow.flow import RunStopped
from deixis.workflow.report.sections import revalidate_section
from fakes import valid_response
from test_contracts import STEP_INPUTS
from test_report_path_fix import Capture, REPLAY, patch, rebind, run_step, sessions
from test_report_step_input import report_flow


H9D = json.loads((Path(__file__).parent / "fixtures/research/p9-rf6-h9d-replay.json").read_text())
FOREIGN_ID = "sti_FOREIGNREQUEST01"


def id_changes(row):
    return [c for c in json.loads(row["validation_json"])["normalised"] if c.get("stamped") == "step_input_id"]


@pytest.mark.parametrize("model_id", [FOREIGN_ID, None])
@pytest.mark.parametrize("task,key", [
    ("report_section", "C_report_section_IV"),
    ("grounded_answer", "A_answer"),
    ("abstract_screening", "F_abstract_screening"),
])
def test_new_behavior_initial_wrong_or_missing_id_is_stamped(tmp_path, task, key, model_id):
    def response(si, schema, message):
        draft = json.loads(valid_response(si))
        if model_id is None:
            draft.pop("step_input_id")
        else:
            draft["step_input_id"] = model_id
        return draft

    output, store, adapter, _, _ = run_step(tmp_path, task, STEP_INPUTS[key], response)
    assert not output.get("invalid"), output
    assert len(adapter.calls) == 1
    row = sessions(store)[0]
    assert output["result"]["step_input_id"] == output["step_input_id"] == row["step_input_id"]
    assert id_changes(row) == [{"path": "/step_input_id", "stamped": "step_input_id", "model_value": model_id}]
    assert json.loads(row["raw_output"]).get("step_input_id") == model_id


def test_new_behavior_full_report_repair_with_predecessor_echo_is_accepted(tmp_path):
    first_id = None

    def response(si, schema, message):
        nonlocal first_id
        draft = json.loads(valid_response(si))
        if first_id is None:
            first_id = si["step_input_id"]
            draft["section_id"] = "V"  # Force full repair, not an anchor patch.
        else:
            draft["step_input_id"] = first_id
        return draft

    output, store, adapter, _, _ = run_step(tmp_path, "report_section", STEP_INPUTS["C_report_section_IV"], response)
    assert not output.get("invalid"), output
    assert len(adapter.calls) == 2
    row = sessions(store)[1]
    assert output["result"]["step_input_id"] == output["step_input_id"] == row["step_input_id"] != first_id
    assert id_changes(row) == [{"path": "/step_input_id", "stamped": "step_input_id", "model_value": first_id}]
    assert json.loads(row["raw_output"])["step_input_id"] == first_id


@pytest.mark.parametrize("model_id", [FOREIGN_ID, None])
def test_new_behavior_anchor_patch_response_is_stamped(tmp_path, model_id):
    record = REPLAY["sections"]["IV"]
    count = 0

    def response(si, schema, message):
        nonlocal count
        count += 1
        if count == 1:
            return rebind(record["first_output"], si)
        draft = patch(si)
        if model_id is None:
            draft.pop("step_input_id")
        else:
            draft["step_input_id"] = model_id
        return draft

    output, store, adapter, _, _ = run_step(tmp_path, "report_section", record["step_input"], response)
    assert not output.get("invalid"), output
    assert len(adapter.calls) == 2
    row = sessions(store)[1]
    assert output["result"]["step_input_id"] == row["step_input_id"]
    assert id_changes(row) == [{"path": "/step_input_id", "stamped": "step_input_id", "model_value": model_id}]
    assert json.loads(row["raw_output"]).get("step_input_id") == model_id


@pytest.mark.parametrize("model_id", [FOREIGN_ID, None])
def test_new_behavior_phrase_repair_response_is_stamped(tmp_path, model_id):
    def response(si, schema, message):
        draft = json.loads(valid_response(si))
        if model_id is None:
            draft.pop("step_input_id")
        else:
            draft["step_input_id"] = model_id
        return draft

    template = copy.deepcopy(STEP_INPUTS["C_report_phrase_repair"])
    output, store, adapter, _, _ = run_step(tmp_path, "report_phrase_repair", template, response)
    assert not output.get("invalid"), output
    assert len(adapter.calls) == 1
    row = sessions(store)[0]
    assert output["result"]["step_input_id"] == row["step_input_id"]
    assert id_changes(row) == [{"path": "/step_input_id", "stamped": "step_input_id", "model_value": model_id}]


def setup_request(tmp_path, response, *, attempt_record=None):
    flow, store, _, run, scope, _, _ = report_flow(tmp_path)
    adapter = Capture(response)
    flow.deps.adapters["fake"] = adapter

    def builder(step_id):
        si = copy.deepcopy(STEP_INPUTS["C_report_section_IV"])
        si.update(step_id=step_id, step_input_id=new_id("sti"), research_id=run["research_id"], run_id=run["id"],
                  scope_revision=run["scope_revision"], skill_package_hash=flow.deps.package.package_hash,
                  model={"connection": "fake", "requested_model": "fake-model"})
        si["report_target"].setdefault("validation_context", None)
        return si

    async def execute():
        return await flow._model_step(run, scope, "RF6:section", "report_section",
                                      model=("fake", "fake-model", None), step_input_builder=builder,
                                      attempt_record=attempt_record)

    return flow, store, adapter, run, execute


@pytest.mark.parametrize("change", ["session_closed", "session_closed_with_output", "new_session_same_input", "new_input", "step_closed", "step_reopened"])
def test_new_behavior_late_or_superseded_result_is_recorded_without_step_change(tmp_path, change):
    expected_step = None
    expected_session = None

    def response(si, schema, message):
        nonlocal expected_step, expected_session
        row = sessions(store)[0]
        if change.startswith("session_closed"):
            previous = {"raw_output": "SYNTHETIC previous result", "validation_json": {"ok": True}} if change.endswith("with_output") else {}
            store.finish_model_session(row["id"], status="interrupted", **previous)
            expected_session = dict(sessions(store)[0])
        elif change == "new_session_same_input":
            store.start_model_session(run["research_id"], run["id"], si["step_id"], si["step_input_id"], "fake", "fake-model")
        elif change == "new_input":
            newer = dict(si, step_input_id=new_id("sti"))
            store.insert_step_input(si["step_id"], run["research_id"], run["id"], 1, newer, "base", "developer", "message", schema)
        else:
            store.finish_step(si["step_id"], "cancelled", output={"sentinel": "keep"})
            if change == "step_reopened":
                store.start_step(si["step_id"])
        expected_step = dict(store.conn.execute("SELECT * FROM run_steps WHERE id = ?", (si["step_id"],)).fetchone())
        return json.loads(valid_response(si))

    _, store, adapter, run, execute = setup_request(tmp_path, response)
    with pytest.raises(RunStopped):
        asyncio.run(execute())
    assert dict(store.conn.execute("SELECT * FROM run_steps WHERE id = ?", (adapter.calls[0]["step_id"],)).fetchone()) == expected_step
    row = sessions(store)[0]
    assert row["raw_output"] == ("SYNTHETIC previous result" if change == "session_closed_with_output" else adapter.raw[0])
    assert json.loads(row["validation_json"])["discarded_results"][0]["code"] == "model_attempt_inactive"
    if change.startswith("session_closed"):
        assert row["status"] == "interrupted"
        assert row["finished_at"] == expected_session["finished_at"]
    if change == "session_closed_with_output":
        assert json.loads(row["validation_json"])["ok"]
        assert json.loads(row["validation_json"])["discarded_results"][0]["raw_output"] == adapter.raw[0]
    if change == "new_session_same_input":
        assert sessions(store)[1]["status"] == "started" and sessions(store)[1]["raw_output"] is None


def test_new_behavior_discarded_session_audit_does_not_consume_a_repair_on_recovery(tmp_path):
    def response(si, schema, message):
        if len(adapter.calls) == 1:
            store.finish_model_session(sessions(store)[0]["id"], status="interrupted")
        return json.loads(valid_response(si))

    _, store, adapter, _, execute = setup_request(tmp_path, response, attempt_record=lambda si: {})
    with pytest.raises(RunStopped):
        asyncio.run(execute())
    validation = json.loads(sessions(store)[0]["validation_json"])
    assert "ok" not in validation and "issues" not in validation
    assert validation["discarded_results"][0]["code"] == "model_attempt_inactive"
    output = asyncio.run(execute())
    assert not output.get("invalid"), output
    assert len(adapter.calls) == 2 and "Failed output (as received):" not in adapter.requests[1]["message"]
    assert output["step_input_id"] == sessions(store)[1]["step_input_id"]


def test_new_behavior_observable_session_misassociation_is_rejected(tmp_path, monkeypatch):
    flow, store, adapter, run, execute = setup_request(tmp_path, lambda si, schema, message: json.loads(valid_response(si)))
    original = flow._call_adapter
    foreign_step = store.step(run["id"], "foreign", "model:report_section")
    store.start_step(foreign_step["id"])

    async def misassociate(*args, **kwargs):
        session, result = await original(*args, **kwargs)
        foreign = dict(store.step_input_payload(adapter.calls[0]["step_input_id"]),
                       step_input_id=new_id("sti"), step_id=foreign_step["id"])
        store.insert_step_input(foreign_step["id"], run["research_id"], run["id"], 0, foreign, "base", "dev", "message", {})
        wrong_session = store.start_model_session(run["research_id"], run["id"], foreign_step["id"], foreign["step_input_id"], "fake", "fake-model")
        return wrong_session, result

    monkeypatch.setattr(flow, "_call_adapter", misassociate)
    with pytest.raises(RunStopped):
        asyncio.run(execute())
    assert all(s["status"] == "running" for s in store.run_steps(run["id"]))
    assert sessions(store)[0]["validation_json"] is None
    assert json.loads(sessions(store)[1]["validation_json"])["discarded_results"][0]["code"] == "model_attempt_inactive"


@pytest.mark.parametrize("change", ["scope", "pause", "cancel"])
@pytest.mark.parametrize("when", ["during_call", "before_storage"])
def test_preservation_run_change_keeps_active_attempt_result_reusable(tmp_path, monkeypatch, change, when):
    """Run controls stop downstream work at baseline checkpoints, not active-attempt storage."""
    def change_run():
        if change == "scope":
            store.conn.execute("UPDATE researches SET current_scope_revision = current_scope_revision + 1 WHERE id = ?", (run["research_id"],))
        else:
            store.update_run(run["id"], status="pause_requested" if change == "pause" else "cancelled")

    def response(si, schema, message):
        if when == "during_call":
            change_run()
        return json.loads(valid_response(si))

    _, store, adapter, run, execute = setup_request(tmp_path, response)
    if when == "before_storage":
        original = contracts.validate_model_output

        def validate(si, draft):
            report = original(si, draft)
            change_run()
            return report

        monkeypatch.setattr(contracts, "validate_model_output", validate)
    output = asyncio.run(execute())
    assert not output.get("invalid"), output
    assert store.run(run["id"])["status"] == ("pause_requested" if change == "pause" else "cancelled" if change == "cancel" else run["status"])
    assert sessions(store)[0]["raw_output"] == adapter.raw[0]
    assert json.loads(sessions(store)[0]["validation_json"])["ok"] is True
    step = store.conn.execute("SELECT * FROM run_steps WHERE id = ?", (adapter.calls[0]["step_id"],)).fetchone()
    assert step["status"] == "succeeded" and json.loads(step["output_json"]) == output
    assert asyncio.run(execute()) == output
    assert len(adapter.calls) == 1


def test_new_behavior_h9d_replay_removes_only_the_echo_failure():
    """Repair OUTPUT is synthetic; stored first-attempt claims/anchors retain their content failures.

    The snapshot stores no repair raw_output. This asserts envelope outcome only,
    and cannot establish what that unrecorded repair actually said or whether it was valid.
    """
    si = H9D["repair_step_input"]
    raw = copy.deepcopy(H9D["synthetic_repair_output"])
    assert raw["step_input_id"] == H9D["first_step_input"]["step_input_id"] != si["step_input_id"]
    assert H9D["stored_repair_validation"]["issues"][0]["code"] == "envelope_mismatch"
    raw, _ = contracts.stamp_package_hash("report_section", si, raw)
    before = contracts.validate_model_output(si, raw)
    stamp = getattr(contracts, "stamp_step_input_id", lambda task, payload, draft: (draft, []))
    draft, changes = stamp("report_section", si, copy.deepcopy(raw))
    after = contracts.validate_model_output(si, draft)
    assert "envelope_mismatch" not in after.codes()
    assert "anchor_not_in_cell_evidence" in after.codes()
    assert [(i.code, i.path) for i in after.issues] == [(i.code, i.path) for i in before.issues if i.code != "envelope_mismatch"]
    assert changes == [{"path": "/step_input_id", "stamped": "step_input_id", "model_value": raw["step_input_id"]}]


def test_new_behavior_wrapper_stamp_records_only_changed_present_objects(monkeypatch):
    monkeypatch.setitem(contracts.TASK_OUTPUTS, "synthetic_wrapper", ("ReportSectionDraft", "ReportReview"))
    monkeypatch.setitem(contracts.WRAPPER_KEYS, "ReportSectionDraft", "section")
    monkeypatch.setitem(contracts.WRAPPER_KEYS, "ReportReview", "review")
    si = STEP_INPUTS["C_report_section_IV"]
    stamp = getattr(contracts, "stamp_step_input_id", lambda task, payload, draft: (draft, []))
    draft, changes = stamp("synthetic_wrapper", si, {"section": {"step_input_id": FOREIGN_ID}, "review": None})
    assert draft["section"]["step_input_id"] == si["step_input_id"]
    assert draft["review"] is None
    assert changes == [{"path": "/section/step_input_id", "stamped": "step_input_id", "model_value": FOREIGN_ID}]
    assert stamp("synthetic_wrapper", si, draft)[1] == []
    assert stamp("report_section", si, "invalid JSON") == ("invalid JSON", [])


def test_preservation_wrong_scope_revision_is_still_envelope_mismatch():
    si = STEP_INPUTS["C_report_section_IV"]
    draft = json.loads(valid_response(si))
    draft["scope_revision"] += 1
    assert ("envelope_mismatch", "/scope_revision") in [(i.code, i.path) for i in contracts.validate_model_output(si, draft).issues]


def test_preservation_stored_section_envelope_mismatch_is_not_stamped():
    si = STEP_INPUTS["C_report_section_IV"]
    draft = json.loads(valid_response(si))
    draft["step_input_id"] = FOREIGN_ID
    assert ("envelope_mismatch", "/step_input_id") in [(i.code, i.path) for i in revalidate_section(si, draft).issues]
    assert draft["step_input_id"] == FOREIGN_ID


def test_new_behavior_restoration_uses_original_step_input_not_draft_echo(tmp_path):
    from test_report_flow import report_flow as complete_report_flow
    from deixis.workflow.report.sections import run_report

    flow, store, reports, _, run, scope, report_id = complete_report_flow(tmp_path, unframed_section="IV")
    asyncio.run(run_report(flow, run, scope))
    section = reports.section(report_id, "IV")
    original = store.step_input_payload(section["draft"]["step_input_id"])
    other = dict(original, step_input_id=new_id("sti"))
    store.insert_step_input(original["step_id"], run["research_id"], run["id"], 1, other, "base", "dev", "message", {})
    altered = dict(section["draft"], step_input_id=other["step_input_id"])
    store.conn.execute("UPDATE report_sections SET draft_json = ? WHERE id = ?", (json.dumps(altered), section["id"]))
    assert reports.revert_repair(report_id, "IV", "IV.1#1") == "would_break_assembly"
    event = store.conn.execute("SELECT payload_json FROM events WHERE type = 'report_repair_restoration_rejected' ORDER BY rowid DESC LIMIT 1").fetchone()
    assert ("envelope_mismatch", "/step_input_id") in [(i["code"], i["path"]) for i in json.loads(event[0])["issues"]]
    assert reports.section(report_id, "IV")["draft"] == altered


def test_preservation_matching_fresh_id_has_no_normalisation_record(tmp_path):
    output, store, _, _, _ = run_step(tmp_path, "report_section", STEP_INPUTS["C_report_section_IV"],
                                     lambda si, schema, message: json.loads(valid_response(si)))
    assert not output.get("invalid")
    assert id_changes(sessions(store)[0]) == []
