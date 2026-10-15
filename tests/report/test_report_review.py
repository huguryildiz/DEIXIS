"""Synthetic report review behavior; these tests do not measure review quality."""

import asyncio
import json

import pytest

from deixis.domain import contracts
from deixis.workflow.report import assembly, review
from deixis.workflow.report import store as report_store
from deixis.workflow.report.sections import run_report
from deixis.workflow.report import sections as report_sections
from deixis.workflow.flow import RunStopped
from deixis.workflow.views import report_view
from deixis.workflow.store import NotFound
from deixis.models.adapter import ModelStepResult
from fakes import scripted_report_review, valid_response
from test_report_flow import report_flow


def _errors(store, reports, report_id):
    return [issue for issue in assembly.run_assembly_checks(store, reports, report_id)
            if not (issue["rule"].endswith("_warning") and issue["detail"].startswith("WARNING:"))]


def test_review_without_findings_records_coverage_and_valid_input(tmp_path):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    assert report_view(store, run["research_id"], report_id)["review"] is None
    asyncio.run(run_report(flow, run, scope))
    saved = reports.report(report_id)["review"]
    assert report_view(store, run["research_id"], report_id)["review"] == saved
    assert saved["status"] == "reviewed"
    assert not saved["findings"] and not saved["reverted"]
    assert sorted(saved["sections_reviewed"] + [x["section_id"] for x in saved["sections_not_reviewed"]]) == sorted(
        section["section_id"] for section in reports.sections(report_id) if section["section_id"] != "II")
    payload = store.step_input_payload(saved["step_input_id"])
    assert not contracts.check_step_input(payload)
    assert payload["report_target"]["review_sections"]
    assert all(section["section_id"] != "II" for section in payload["report_target"]["review_sections"])
    assert len([call for call in adapter.calls if call["task_type"] == "report_review"]) == 1


def test_review_output_rejects_an_unknown_claim_and_the_removed_repair_fields():
    with open("tests/fixtures/research/step-inputs.json", encoding="utf-8") as source:
        payload = json.load(source)["C_report_review"]
    with open("tests/fixtures/research/fake-outputs.json", encoding="utf-8") as source:
        output = next(case["output"] for case in json.load(source)["cases"] if case["name"] == "report_review_valid")
    # D43: findings no longer name a repaired sentence, and support_broken went with the repair step.
    examples = [
        ({"claim_key": "IV.99", "code": "other"}, "review_claim_unknown"),
        ({"claim_key": "IV.1", "sentence_id": None, "code": "other"}, "schema_invalid"),
        ({"claim_key": "IV.1", "code": "support_broken"}, "schema_invalid"),
    ]
    for finding, code in examples:
        result = contracts.validate_model_output(payload, output | {"findings": [finding | {"text": "SYNTHETIC flag"}]})
        assert code in {issue.code for issue in result.issues}
    report_level = {"claim_key": None, "code": "abstract_body_mismatch", "text": "SYNTHETIC flag"}
    assert contracts.validate_model_output(payload, output | {"findings": [report_level]}).ok


def test_zero_review_budget_records_no_model_call(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "REVIEW_BUDGET_TOKENS", 0)
    flow, _, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    asyncio.run(run_report(flow, run, scope))
    saved = reports.report(report_id)
    assert saved["status"] == "valid" and saved["report_version"] == 1
    assert saved["review"]["status"] == "not_reviewed"
    assert saved["review"]["reason"] == "input_too_large"
    assert saved["review"]["sections_not_reviewed"] == review._input(flow, reports, report_id)[3]
    assert not [call for call in adapter.calls if call["task_type"] == "report_review"]


def test_claimless_report_has_nothing_to_review(tmp_path, monkeypatch):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)

    async def skip_review(*_):
        pass

    monkeypatch.setattr(report_sections, "run_report_review", skip_review)
    asyncio.run(run_report(flow, run, scope))
    monkeypatch.setattr(report_sections, "run_report_review", review.run_report_review)
    store.conn.execute("UPDATE report_claims SET report_section_id = ? WHERE report_section_id != ?",
                       (reports.section(report_id, "II")["id"], reports.section(report_id, "II")["id"]))

    asyncio.run(review.run_report_review(flow, run, scope, reports, report_id))

    saved = reports.report(report_id)["review"]
    assert saved["status"] == "not_reviewed" and saved["reason"] == "nothing_to_review"
    assert saved["sections_not_reviewed"]
    assert all(item["reason"] == "no_claims" for item in saved["sections_not_reviewed"])
    assert not [call for call in adapter.calls if call["task_type"] == "report_review"]


def test_unavailable_passages_keep_their_own_reason_when_nothing_can_be_read(tmp_path, monkeypatch):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)

    async def skip_review(*_):
        pass

    monkeypatch.setattr(report_sections, "run_report_review", skip_review)
    asyncio.run(run_report(flow, run, scope))
    store.conn.execute("UPDATE report_claims SET report_section_id = ?"
                       " WHERE id NOT IN (SELECT claim_id FROM report_citation_links)",
                       (reports.section(report_id, "II")["id"],))

    def unavailable_passage(passage_id):
        raise NotFound(passage_id)

    monkeypatch.setattr(store, "passage", unavailable_passage)

    asyncio.run(review.run_report_review(flow, run, scope, reports, report_id))

    saved = reports.report(report_id)["review"]
    assert saved["status"] == "not_reviewed" and saved["reason"] == "nothing_to_review"
    assert saved["sections_not_reviewed"] == review._input(flow, reports, report_id)[3]
    assert any(item["reason"] == "passage_unavailable" for item in saved["sections_not_reviewed"])
    assert not [call for call in adapter.calls if call["task_type"] == "report_review"]


def test_review_budget_omits_later_whole_sections(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "REVIEW_BUDGET_TOKENS", 500)
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    asyncio.run(run_report(flow, run, scope))
    saved = reports.report(report_id)["review"]
    assert saved["status"] == "reviewed"
    assert saved["sections_reviewed"]
    assert any(item["reason"] == "input_too_large" for item in saved["sections_not_reviewed"])
    payload = store.step_input_payload(saved["step_input_id"])
    assert [item["section_id"] for item in payload["report_target"]["review_sections"]] == saved["sections_reviewed"]


def test_optional_review_failure_keeps_valid_report(tmp_path):
    flow, _, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    adapter.fail = lambda si: (ModelStepResult("failed", error="SYNTHETIC review call failed",
                                               delivery_class="before_send")
                               if si["task_type"] == "report_review" else None)
    asyncio.run(run_report(flow, run, scope))
    saved = reports.report(report_id)
    assert saved["status"] == "valid" and saved["report_version"] == 1
    assert saved["review"]["status"] == "not_reviewed"
    assert saved["review"]["reason"] == "model_call_failed"


def test_review_model_mismatch_keeps_valid_report(tmp_path):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    adapter.fail = lambda si: (ModelStepResult("completed", raw_text=valid_response(si),
                                               resolved_model="SYNTHETIC-other-model")
                               if si["task_type"] == "report_review" else None)
    asyncio.run(run_report(flow, run, scope))
    saved = reports.report(report_id)
    assert saved["status"] == "valid" and saved["report_version"] == 1
    assert saved["review"]["status"] == "not_reviewed"
    assert saved["review"]["reason"] == "model_mismatch"
    assert store.step(run["id"], "report_review", "model:report_review")["status"] == "failed"


def test_cancelled_mismatched_review_is_not_saved(tmp_path):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)

    def mismatch_after_cancel(si):
        if si["task_type"] != "report_review":
            return None
        store.update_run(run["id"], status="cancelled")
        return ModelStepResult("completed", raw_text=valid_response(si), resolved_model="SYNTHETIC-other-model")

    adapter.fail = mismatch_after_cancel
    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))
    assert reports.report(report_id)["status"] == "valid"
    assert reports.report(report_id)["review"] is None
    assert store.run(run["id"])["status"] == "cancelled"


def test_invalid_review_output_is_recorded_without_demoting_report(tmp_path):
    flow, _, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    ordinary = adapter.responder
    adapter.responder = lambda si: (json.dumps({"SYNTHETIC_broken": True})
                                    if si["task_type"] == "report_review" else ordinary(si))
    asyncio.run(run_report(flow, run, scope))
    saved = reports.report(report_id)
    assert saved["status"] == "valid" and saved["report_version"] == 1
    assert saved["review"]["status"] == "not_reviewed"
    assert saved["review"]["reason"] == "invalid_model_output"
    assert saved["review"]["detail"]


def test_report_level_finding_has_no_section(tmp_path):
    flow, _, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    adapter.responder = scripted_report_review(adapter.responder, lambda _: [{
        "claim_key": None, "code": "abstract_body_mismatch", "text": "SYNTHETIC mismatch",
    }])
    asyncio.run(run_report(flow, run, scope))
    assert reports.report(report_id)["review"]["findings"][0]["section_id"] is None


def test_report_budget_formula_includes_review(tmp_path, monkeypatch):
    flow, store, reports, _, run, _, _ = report_flow(tmp_path)
    monkeypatch.setattr(report_store, "REPORT_CALL_FLOOR", 0)
    store.update_run(run["id"], status="completed")
    requested = reports.request_report(run["research_id"], run["target"]["table_id"], None)
    assert requested["budget"]["max_model_calls"] == (1 + 10 + 1 + 10 + 1) * (1 + report_store.MAX_SCHEMA_REPAIRS)


def test_pause_after_finalization_resumes_one_review(tmp_path, monkeypatch):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    original = report_sections.run_report_review

    async def pause_before_review(*args):
        store.update_run(run["id"], status="pause_requested")
        await original(*args)
    monkeypatch.setattr(report_sections, "run_report_review", pause_before_review)
    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))
    assert reports.report(report_id)["status"] == "valid"
    assert reports.report(report_id)["review"] is None
    assert store.run(run["id"])["status"] == "paused"
    store.update_run(run["id"], status="running", pause_reason=None)
    monkeypatch.setattr(report_sections, "run_report_review", original)
    asyncio.run(run_report(flow, store.run(run["id"]), scope))
    assert reports.report(report_id)["review"]["status"] == "reviewed"
    assert len([call for call in adapter.calls if call["task_type"] == "report_review"]) == 1


def test_cancel_after_finalization_stops_before_review(tmp_path, monkeypatch):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    original = report_sections.run_report_review

    async def cancel_before_review(*args):
        store.update_run(run["id"], status="cancelled")
        await original(*args)

    monkeypatch.setattr(report_sections, "run_report_review", cancel_before_review)
    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))
    assert reports.report(report_id)["status"] == "valid"
    assert reports.report(report_id)["review"] is None
    assert store.run(run["id"])["status"] == "cancelled"
    assert not [call for call in adapter.calls if call["task_type"] == "report_review"]


def test_replay_uses_stored_omission_reasons_after_claim_table_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "REVIEW_BUDGET_TOKENS", 500)
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    asyncio.run(run_report(flow, run, scope))
    first = reports.report(report_id)["review"]
    omitted = next(item for item in first["sections_not_reviewed"] if item["reason"] == "input_too_large")
    section = reports.section(report_id, omitted["section_id"])
    assert store.conn.execute("SELECT 1 FROM report_claims WHERE report_section_id = ?",
                              (section["id"],)).fetchone()
    stored = store.step(run["id"], "report_review", "model:report_review")
    assert stored["output"]["sections_not_reviewed"] == first["sections_not_reviewed"]
    store.conn.execute("UPDATE reports SET review_json = NULL WHERE id = ?", (report_id,))
    store.conn.execute("UPDATE report_claims SET report_section_id = ? WHERE report_section_id = ?",
                       (reports.section(report_id, "II")["id"], section["id"]))
    assert store.conn.execute("SELECT 1 FROM report_claims WHERE report_section_id = ?",
                              (section["id"],)).fetchone() is None
    asyncio.run(review.run_report_review(flow, run, scope, reports, report_id))
    assert reports.report(report_id)["review"] == first
    assert len([call for call in adapter.calls if call["task_type"] == "report_review"]) == 1


def test_successful_step_commits_coverage_before_interrupted_return(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "REVIEW_BUDGET_TOKENS", 500)
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    original = store.complete_model_step

    def interrupt_after_commit(session_id, session_fields, step_id, status, **fields):
        original(session_id, session_fields, step_id, status, **fields)
        if step_id == store.step(run["id"], "report_review", "model:report_review")["id"] and status == "succeeded":
            raise RuntimeError("SYNTHETIC interruption after commit")

    monkeypatch.setattr(store, "complete_model_step", interrupt_after_commit)
    with pytest.raises(RuntimeError, match="SYNTHETIC interruption"):
        asyncio.run(run_report(flow, run, scope))
    step = store.step(run["id"], "report_review", "model:report_review")
    assert step["status"] == "succeeded"
    assert any(item["reason"] == "input_too_large" for item in step["output"]["sections_not_reviewed"])
    assert reports.report(report_id)["review"] is None

    monkeypatch.setattr(store, "complete_model_step", original)
    asyncio.run(review.run_report_review(flow, run, scope, reports, report_id))
    assert reports.report(report_id)["review"]["sections_not_reviewed"] == step["output"]["sections_not_reviewed"]
    assert len([call for call in adapter.calls if call["task_type"] == "report_review"]) == 1


def test_unavailable_exact_passage_omits_the_whole_section(tmp_path, monkeypatch):
    flow, store, reports, _, run, scope, report_id = report_flow(tmp_path)
    asyncio.run(run_report(flow, run, scope))
    missing = reports.snapshot(report_id)["cells"][0]["evidence"][0]["passage_id"]
    original = store.passage

    def passage_by_id(passage_id):
        if passage_id == missing:
            raise NotFound(passage_id)
        return original(passage_id)
    monkeypatch.setattr(store, "passage", passage_by_id)
    target, _, _, omitted = review._input(flow, reports, report_id)
    assert "IV" not in target["review_scope"]
    assert {item["section_id"] for item in omitted if item["reason"] == "passage_unavailable"} >= {"IV"}
