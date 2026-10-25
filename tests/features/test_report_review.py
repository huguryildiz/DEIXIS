"""Synthetic report review behavior; these tests do not measure review quality."""

import asyncio
import json


from deixis.domain import contracts
from deixis.workflow import report_review as review
from deixis.workflow.report_sections import run_report
from deixis.workflow import report_sections
from deixis.workflow.views import report_view
from deixis.models.adapter import ModelStepResult
from fakes import valid_response
from test_report_flow import report_flow


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
