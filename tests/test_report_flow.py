"""Synthetic report-run orchestration; passing does not establish report quality."""

import asyncio
import json
from collections import Counter
from types import SimpleNamespace

import pytest

from deixis.config import Settings
from deixis.domain import skill
from deixis.models.adapter import ModelStepResult
from deixis.storage import db
from deixis.storage.db import dumps, new_id
from deixis.workflow.concurrency import ModelCallLimiter
from deixis.workflow.flow import FlowDeps, ResearchFlow, RunStopped
from deixis.workflow.report.sections import _citation_links, _pause_detail, run_report
from deixis.workflow.report.phrasing import _report_checkpoint
from deixis.workflow.report.assembly import run_assembly_checks
from deixis.workflow.report import assembly
from deixis.workflow.report.selection import SECTION_BUDGET_TOKENS
from deixis.workflow.report.store import ReportStore
from deixis.workflow.store import Store
from deixis.workflow.worker import Worker
from deixis.workflow import flow as flow_module
from deixis.workflow.tables import TableStore
from fakes import FakeAdapter, envelope


COLUMN = {
    "name": "SYNTHETIC method",
    "instruction": "Record the SYNTHETIC method.",
    "answer_format": "text",
    "options": None,
    "allow_multiple": False,
    "unit_hint": None,
}
LIMITATIONS_COLUMN = COLUMN | {
    "name": "SYNTHETIC stated limitations",
    "instruction": "Record the source's stated limitations.",
}
FUTURE_WORK_COLUMN = COLUMN | {
    "name": "SYNTHETIC stated future work",
    "instruction": "Record the source's stated future work.",
}
PASSAGE = "SYNTHETIC evidence states that molecule release scheduling uses a bounded formulation."
CELL_QUOTE = "SYNTHETIC evidence states that molecule release scheduling"


def test_report_links_store_source_owned_anchor_text():
    payload = {"step_input_id": "sti_test", "passages": [{"passage_id": "p1", "source_id": "s1",
               "text": "The Source  states a measured result."}], "report_target": {"cells": [{"cell_id": "c1",
               "source_version_id": "s1", "evidence": [{"quote": "The Stored  CELL quote."}]}]}}
    draft = {"citation_anchors": [
        {"claim_key": "IV.1", "passage_id": "p1", "cell_id": None, "quote": "the source states a measured result."},
        {"claim_key": "IV.1", "passage_id": None, "cell_id": "c1", "quote": "the stored cell quote."},
    ]}
    links = _citation_links(payload, draft)
    assert [(link["anchor_text"], link["anchor_match"]) for link in links] == [
        ("The Source  states a measured result", "normalized"),
        ("The Stored  CELL quote", "normalized"),
    ]


def _add_pdf(store, source_id, pages):
    extraction = SimpleNamespace(
        status="succeeded", error=None, page_count=len(pages),
        pages=[SimpleNamespace(physical_page=number, printed_label=None, text=text)
               for number, text in enumerate(pages, 1)],
    )
    return store.add_asset_with_pages(
        source_id, "synthetic-report-pdf", 10, "synthetic-report.pdf", "user_upload", None,
        "synthetic-report.pdf", extraction, "synthetic-v1", lambda text: [(0, len(text), text)],
    )


class ReportAdapter(FakeAdapter):
    def __init__(self, broken_section=None, empty_section=None, unframed_section=None,
                 ambiguous_anchor_section=None):
        super().__init__(responder=self._response)
        self.broken_section = broken_section
        self.empty_section = empty_section
        self.unframed_section = unframed_section
        self.ambiguous_anchor_section = ambiguous_anchor_section

    def _response(self, step_input):
        task = step_input["task_type"]
        if task == "report_plan":
            passage_id = step_input["allowlist"]["passage_ids"][0]
            columns = step_input["report_target"]["columns"]
            column_id = columns[0]["column_id"]
            limitations_column_id = next(column["column_id"] for column in columns
                                         if "limitations" in column["name"])
            future_work_column_id = next(column["column_id"] for column in columns
                                         if "future work" in column["name"])
            return json.dumps(envelope(step_input, "deixis.report_plan_draft.v2") | {
                "scope_statement": "SYNTHETIC scope for bounded release scheduling formulations.",
                "research_questions": [
                    {"rq_id": "RQ1", "text": "SYNTHETIC: which formulation is reported?"},
                    {"rq_id": "RQ2", "text": "SYNTHETIC: which evidence supports it?"},
                ],
                "glossary": [{"term": "release scheduling", "definition": "SYNTHETIC definition.",
                              "passage_id": passage_id}],
                "axes": [{"axis_id": "AX1", "label": "SYNTHETIC method", "column_id": column_id}],
                "limitations_column_id": limitations_column_id,
                "future_work_column_id": future_work_column_id,
            })
        if task != "report_section":
            from fakes import valid_response
            return valid_response(step_input)
        section_id = step_input["report_target"]["section_id"]
        if section_id == self.broken_section:
            return json.dumps({"SYNTHETIC_broken": True})
        claims, anchors = [], []
        insufficient_evidence = []
        if section_id == self.empty_section:
            pass
        elif step_input["report_target"]["cells"]:
            cell = step_input["report_target"]["cells"][0]
            claims = [_claim(section_id, cell_ids=[cell["cell_id"]])]
            anchors = [{"claim_key": f"{section_id}.1", "passage_id": None,
                        "cell_id": cell["cell_id"], "quote": CELL_QUOTE}]
        elif step_input["passages"]:
            passage = step_input["passages"][0]
            claims = [_claim(section_id, passage_ids=[passage["passage_id"]])]
            anchors = [{"claim_key": f"{section_id}.1", "passage_id": passage["passage_id"],
                        "cell_id": None, "quote": CELL_QUOTE}]
        elif step_input["report_target"]["prior_summaries"]:
            summary = step_input["report_target"]["prior_summaries"][0]
            claims = [_claim(section_id, body_refs=[summary["claim_key"]])]
        else:
            insufficient_evidence = [{"context": section_id,
                                      "reason": "It is beyond the scope of this synthetic fixture to add a claim."}]
        if section_id == self.unframed_section and claims:
            claims[0]["text"] = "Fig weiro randomtext not a frame sentence at all zzq."
        if section_id == self.ambiguous_anchor_section and anchors:
            anchors[0]["passage_id"] = step_input["passages"][0]["passage_id"]
        gaps = [{
            "gap_id": "gap9",
            "kind": "stated_limitation",
            "text": "SYNTHETIC model-proposed limitation.",
            "basis_claim_keys": [],
            "basis_passage_ids": [],
            "basis_cell_ids": [step_input["report_target"]["cells"][0]["cell_id"]],
            "nearest_match": {"status": "not_searched", "source_id": None, "cell_id": None},
        }] if section_id == "VI" else []
        return json.dumps(envelope(step_input, "deixis.report_section_draft.v2") | {
            "section_id": section_id,
            "claims": claims,
            "citation_anchors": anchors,
            "subsections": [],
            "gaps": gaps,
            "insufficient_evidence": insufficient_evidence,
        })


def _claim(section_id, passage_ids=None, cell_ids=None, body_refs=None):
    text = {
        "III": "It encompasses the SYNTHETIC bounded formulation.",
        "V": "The SYNTHETIC formulation is different from its alternative in a number of respects.",
        "IX": "This report has shown that the SYNTHETIC formulation is bounded.",
        "abstract": "This report has shown that the SYNTHETIC formulation is bounded.",
    }.get(section_id, "It has been reported that the SYNTHETIC formulation is bounded.")
    return {
        "claim_key": f"{section_id}.1",
        "text": text,
        "support_type": "analyst_inference" if section_id == "VIII" else "source_stated",
        "passage_ids": passage_ids or [],
        "cell_ids": cell_ids or [],
        "paragraph": 1,
        "table_ref": "TABLE_I" if section_id == "IV" else None,
        "equation_ref": None,
        "body_refs": body_refs or [],
        "axis_id": None,
        "count": None,
        "equation_origin": None,
        "gap_refs": [],
    }


def report_flow(tmp_path, *, fill=True, broken_section=None, empty_section=None, unframed_section=None,
                ambiguous_anchor_section=None, passage_kind="abstract", cell_quotes=None):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    research_id = store.create_research(
        "How are SYNTHETIC molecular communication systems optimized?",
        "attached", "quick", [], "fake", "fake-model", "en",
    )
    source_id = store.create_upload_source("SYNTHETIC molecular communication study")
    if passage_kind == "pdf_page":
        _add_pdf(store, source_id, [
            PASSAGE,
            "SYNTHETIC second page that must not widen the report plan allowlist.",
        ])
        passage_id = store.passages_for(source_id)[0]["id"]
    else:
        passage_id = store._insert_passage(
            source_id, None, "abstract", None, None, "synthetic_fixture", None, None,
            PASSAGE + (" " + " ".join(cell_quotes) if cell_quotes else ""),
        )
    store.add_to_corpus(research_id, source_id, "user_upload", selection_state="included", selection_origin="user")
    tables = TableStore(store)
    table_id = tables.create_table(research_id, "SYNTHETIC evidence", None, None, None)
    column_ids = [
        tables.add_column(research_id, table_id, column, version, None)
        for version, column in enumerate((COLUMN, LIMITATIONS_COLUMN, FUTURE_WORK_COLUMN), 1)
    ]
    if fill:
        fill_run = store.create_run(research_id, "answer", {}, None)
        step = store.step(fill_run["id"], "synthetic:cell", "model:cell_extraction")
        step_input_id = new_id("sti")
        store.insert_step_input(
            step["id"], research_id, fill_run["id"], 0,
            {"step_input_id": step_input_id, "task_type": "cell_extraction", "scope_revision": 1,
             "skill_package_hash": "sha256:synthetic"},
            "base", "developer", "message", {},
        )
        for index, column_id in enumerate(column_ids):
            tables.save_model_output(
                research_id, table_id, column_id, source_id, column_revision=1, state="value",
                value={"text": "SYNTHETIC bounded formulation"}, note=None, reading_depth="abstract",
                output_status="structurally_valid",
                links=[{"passage_id": passage_id, "source_version_id": source_id,
                        "anchor_text": cell_quotes[index] if cell_quotes else CELL_QUOTE, "anchor_match": "exact"}],
                run_id=fill_run["id"], step_id=step["id"], step_input_id=step_input_id,
                model_connection="fake", resolved_model="fake-model", scope_revision=1,
                cell_version_at_request=0, recheck=False,
            )
        store.update_run(fill_run["id"], status="completed")
    run = store.create_run(
        research_id, "report", {"max_model_calls": 100, "max_provider_requests": 0}, None,
        {"table_id": table_id},
    )
    reports = ReportStore(store)
    report_id = reports.create_report(research_id, run["id"], 1, "en")
    store.update_run(
        run["id"], status="running", target_json=dumps({"table_id": table_id, "report_id": report_id}),
    )
    adapter = ReportAdapter(broken_section, empty_section, unframed_section, ambiguous_anchor_section)
    flow = ResearchFlow(FlowDeps(
        Settings(data_dir=tmp_path / "data", port=8765), store, {"fake": adapter},
        skill.load_skill_package(), None, limiter=ModelCallLimiter(3),
    ))
    return flow, store, reports, adapter, store.run(run["id"]), store.scope(research_id), report_id


def _section_calls(adapter):
    return Counter(call["report_target"]["section_id"] for call in adapter.calls
                   if call["task_type"] == "report_section")


def _claims(store, reports, report_id, section_id):
    return store.conn.execute(
        "SELECT claim_key FROM report_claims WHERE report_section_id = ?",
        (reports.section(report_id, section_id)["id"],),
    ).fetchall()


def _resume_report(flow, store, run, scope):
    store.update_run(run["id"], status="running", pause_reason=None, error_json=None)
    asyncio.run(run_report(flow, store.run(run["id"]), scope))


def _reason_codes(store, run):
    return [(reason["section_id"], reason["code"]) for reason in store.run(run["id"])["error"]["reasons"]]


def test_report_temporary_rate_limit_retries_twice_then_completes(tmp_path, monkeypatch):
    monkeypatch.setattr(flow_module, "RATE_LIMIT_BACKOFF_SECONDS", 0)
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    attempts = 0

    def fail(si):
        nonlocal attempts
        if si["task_type"] == "report_section" and si["report_target"]["section_id"] == "III":
            attempts += 1
            if attempts <= 2:
                return ModelStepResult("failed", error="rate_limit_error: temporary limit")
        return None

    adapter.fail = fail
    asyncio.run(run_report(flow, run, scope))
    assert _section_calls(adapter)["III"] == 3
    assert flow.deps.limiter.limit == 1
    assert reports.section(report_id, "III")["status"] == "valid"
    assert reports.report(report_id)["status"] == "valid"


def test_report_quota_exhaustion_records_reason_and_resumes_only_failed_section(tmp_path, monkeypatch):
    monkeypatch.setattr(flow_module, "RATE_LIMIT_BACKOFF_SECONDS", 0)
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    adapter.fail = lambda si: (ModelStepResult("failed", error="rate_limit_error: quota exhausted " + "x" * 500)
                               if si["task_type"] == "report_section" and si["report_target"]["section_id"] == "III"
                               else None)
    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))
    assert _section_calls(adapter)["III"] == 1
    assert flow.deps.limiter.limit == 3
    assert reports.section(report_id, "III")["status"] == "failed"
    assert reports.section(report_id, "III")["validation"]["issues"][0]["code"] == "model_call_failed"
    assert all(reports.section(report_id, section)["status"] == "valid" for section in ("IV", "V"))
    stopped = store.run(run["id"])
    assert (stopped["status"], stopped["pause_reason"]) == ("paused", "section_failed")
    assert _reason_codes(store, run) == [("III", "model_call_failed")]
    assert "rate_limit_error" in stopped["error"]["reasons"][0]["detail"]["error"]
    assert len(stopped["error"]["reasons"][0]["detail"]["error"]) == 300
    before = _section_calls(adapter)
    adapter.fail = None
    _resume_report(flow, store, run, scope)
    after = _section_calls(adapter)
    assert after["III"] == before["III"] + 1
    assert all(after[section] == before[section] for section in ("IV", "V"))
    assert reports.report(report_id)["status"] == "valid"


def test_report_crash_during_call_recovers_unknown_step_and_resends(tmp_path):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)

    def crash(si):
        if si["task_type"] == "report_section" and si["report_target"]["section_id"] == "IV":
            raise SystemExit("SYNTHETIC crash during IV")

    adapter.before = crash
    with pytest.raises(SystemExit):
        asyncio.run(run_report(flow, run, scope))
    step = store.step(run["id"], "report_section:IV", "model:report_section")
    assert step["status"] == "running"
    assert store.conn.execute("SELECT status FROM model_sessions WHERE step_id = ?", (step["id"],)).fetchone()[0] == "started"
    assert store.run(run["id"])["status"] == "running"
    assert reports.section(report_id, "IV")["status"] == "running"
    assert not _claims(store, reports, report_id, "IV")
    before = _section_calls(adapter)
    succeeded_before = [section for section in ("III", "V")
                        if store.step(run["id"], f"report_section:{section}", "model:report_section")["status"] == "succeeded"]
    recovered = Worker(store, flow, tmp_path / "lock").recover()
    assert recovered["runs"] >= 1 and recovered["steps"] >= 1 and recovered["model_sessions"] >= 1
    assert (store.run(run["id"])["status"], store.run(run["id"])["pause_reason"]) == ("paused", "backend_restarted")
    assert store.step(run["id"], "report_section:IV", "model:report_section")["status"] == "outcome_unknown"
    adapter.before = None
    _resume_report(flow, store, run, scope)
    assert reports.report(report_id)["status"] == "valid"
    assert _section_calls(adapter)["IV"] == 2
    section_ids = [section["section_id"] for section in reports.sections(report_id)]
    assert len(section_ids) == len(set(section_ids))
    keys = [row[0] for row in store.conn.execute("SELECT claim_key FROM report_claims c JOIN report_sections s"
             " ON s.id = c.report_section_id WHERE s.report_id = ?", (report_id,))]
    assert len(keys) == len(set(keys))
    for section in succeeded_before:
        assert _section_calls(adapter)[section] == before[section]


def test_report_crash_after_saved_result_reuses_it_on_resume(tmp_path, monkeypatch):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    original = ReportStore.save_claims
    crashed = False

    def crash_once(self, section_key, claims, links):
        nonlocal crashed
        if section_key == reports.section(report_id, "IV")["id"] and not crashed:
            crashed = True
            raise SystemExit("SYNTHETIC crash before IV claims")
        return original(self, section_key, claims, links)

    monkeypatch.setattr(ReportStore, "save_claims", crash_once)
    with pytest.raises(SystemExit):
        asyncio.run(run_report(flow, run, scope))
    assert store.run(run["id"])["status"] == "running"
    assert reports.section(report_id, "IV")["status"] == "running"
    assert not _claims(store, reports, report_id, "IV")
    assert store.step(run["id"], "report_section:IV", "model:report_section")["status"] == "succeeded"
    Worker(store, flow, tmp_path / "lock").recover()
    assert store.run(run["id"])["pause_reason"] == "backend_restarted"
    monkeypatch.setattr(ReportStore, "save_claims", original)
    _resume_report(flow, store, run, scope)
    assert reports.report(report_id)["status"] == "valid"
    assert _section_calls(adapter)["IV"] == 1
    assert len(_claims(store, reports, report_id, "IV")) == 1


def test_report_cancel_during_section_keeps_late_result_unapplied(tmp_path):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)

    def cancel(si):
        if si["task_type"] == "report_section" and si["report_target"]["section_id"] == "IV":
            store.update_run(run["id"], event="run_cancelled", status="cancelled", pause_reason="user_cancelled")

    adapter.before = cancel
    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))
    assert store.run(run["id"])["status"] == "cancelled"
    assert store.step(run["id"], "report_section:IV", "model:report_section")["status"] == "succeeded"
    assert reports.section(report_id, "IV")["status"] == "running"
    assert not _claims(store, reports, report_id, "IV")
    assert reports.report(report_id)["status"] == "in_progress"
    assert not any(section in _section_calls(adapter) for section in ("VI", "VII", "VIII", "I", "IX", "abstract", "index_terms"))


def test_report_scope_change_stops_sibling_late_results(tmp_path):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)

    def revise(si):
        if si["task_type"] == "report_section" and si["report_target"]["section_id"] == "IV":
            research_id = run["research_id"]
            store.revise_scope(research_id, store.research(research_id)["version"],
                               "A revised SYNTHETIC question", None)

    adapter.before = revise
    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))
    assert (store.run(run["id"])["status"], store.run(run["id"])["pause_reason"]) == ("cancelled", "scope_revised")
    assert store.step(run["id"], "report_section:IV", "model:report_section")["status"] == "succeeded"
    for section in ("III", "IV", "V"):
        step = store.step(run["id"], f"report_section:{section}", "model:report_section")
        if step["status"] == "succeeded":
            assert not _claims(store, reports, report_id, section)
    assert reports.report(report_id)["status"] == "in_progress"
    assert not any(section in _section_calls(adapter) for section in ("VI", "VII", "VIII", "I", "IX", "abstract", "index_terms"))


def test_report_pause_during_section_applies_stored_result_once_on_resume(tmp_path):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    paused = False

    def pause(si):
        nonlocal paused
        if si["task_type"] == "report_section" and si["report_target"]["section_id"] == "IV" and not paused:
            paused = True
            store.update_run(run["id"], event="run_pause_requested", status="pause_requested",
                             pause_reason="user_requested")

    adapter.before = pause
    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))
    assert (store.run(run["id"])["status"], store.run(run["id"])["pause_reason"]) == ("paused", "user_requested")
    assert not _claims(store, reports, report_id, "IV")
    _resume_report(flow, store, run, scope)
    assert reports.report(report_id)["status"] == "valid"
    assert len(_claims(store, reports, report_id, "IV")) == 1
    assert _section_calls(adapter)["IV"] == 1
    assert all(_section_calls(adapter)[section] <= 1 for section in ("III", "V"))


@pytest.mark.parametrize("repair_fails", [False, True])
def test_report_cancel_during_phrase_repair_writes_no_repair_row(tmp_path, repair_fails):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path, unframed_section="IV")

    def cancel(si):
        if si["task_type"] == "report_phrase_repair":
            store.update_run(run["id"], event="run_cancelled", status="cancelled", pause_reason="user_cancelled")

    adapter.before = cancel
    if repair_fails:
        adapter.fail = lambda si: (ModelStepResult("failed", error="SYNTHETIC connection lost")
                                   if si["task_type"] == "report_phrase_repair" else None)
    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))
    assert store.run(run["id"])["status"] == "cancelled"
    assert store.conn.execute("SELECT COUNT(*) FROM report_phrase_repairs WHERE report_id = ?", (report_id,)).fetchone()[0] == 0
    assert not _claims(store, reports, report_id, "IV")


def test_report_repair_checkpoint_stops_an_already_paused_run(tmp_path):
    flow, store, _, _, run, _, _ = report_flow(tmp_path)
    # A failed model call checkpoints before repair_section can handle OptionalStepFailed.
    # The helper also guards a pause already finalized by a sibling section.
    store.update_run(run["id"], status="paused", pause_reason="user_requested")
    with pytest.raises(RunStopped):
        _report_checkpoint(flow, run)


def test_report_pause_finalized_during_phrase_repair_writes_no_repair_row(tmp_path):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path, unframed_section="IV")

    def pause(si):
        if si["task_type"] == "report_phrase_repair":
            store.update_run(run["id"], status="paused", pause_reason="user_requested")

    adapter.before = pause
    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))
    assert (store.run(run["id"])["status"], store.run(run["id"])["pause_reason"]) == (
        "paused", "user_requested",
    )
    assert store.conn.execute(
        "SELECT COUNT(*) FROM report_phrase_repairs WHERE report_id = ?", (report_id,),
    ).fetchone()[0] == 0
    assert store.step(run["id"], "report_phrase_repair:IV", "model:report_phrase_repair")["status"] == "succeeded"
    assert reports.section(report_id, "IV")["status"] == "running"
    assert not _claims(store, reports, report_id, "IV")


def test_report_wrong_model_reason_keeps_output_unapplied(tmp_path):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)

    def select_model(si):
        adapter.resolved_model = ("some-other-model" if si["task_type"] == "report_section"
                                  and si["report_target"]["section_id"] == "IV" else None)

    adapter.before = select_model
    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))
    assert reports.section(report_id, "IV")["status"] == "failed"
    assert reports.section(report_id, "IV")["validation"]["issues"][0]["code"] == "model_mismatch"
    assert not _claims(store, reports, report_id, "IV")
    assert all(reports.section(report_id, section)["status"] == "valid" for section in ("III", "V"))
    assert store.run(run["id"])["pause_reason"] == "section_failed"
    assert _reason_codes(store, run) == [("IV", "model_mismatch")]


def test_report_budget_exhaustion_records_reason(tmp_path):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    store.update_run(run["id"], budget_json=dumps(run["budget"] | {"max_model_calls": 1}))
    run = store.run(run["id"])
    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))
    assert not any(call["task_type"] == "report_section" for call in adapter.calls)
    assert all(reports.section(report_id, section)["validation"]["issues"][0]["code"] == "budget_exhausted"
               for section in ("III", "IV", "V"))
    assert store.run(run["id"])["pause_reason"] == "section_failed"
    assert _reason_codes(store, run) == [(section, "budget_exhausted") for section in ("III", "IV", "V")]


def test_report_invalid_output_reason_uses_first_model_issue(tmp_path):
    flow, store, reports, _, run, scope, report_id = report_flow(tmp_path, broken_section="IV")
    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))
    issue = reports.section(report_id, "IV")["validation"]["issues"][0]
    assert issue["code"] != "unknown"
    assert _reason_codes(store, run) == [("IV", issue["code"])]


def test_report_rewrite_reason_uses_first_three_issues(tmp_path):
    flow, store, reports, _, run, scope, report_id = report_flow(tmp_path, empty_section="VIII")
    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))
    section = reports.section(report_id, "VIII")
    assert section["status"] == "draft"
    issue_codes = [f"synthetic_limitation_{i}" for i in range(5)]
    issues = [{"code": code, "detail": f"SYNTHETIC issue {i}"}
              for i, code in enumerate(issue_codes)]
    reports.save_section_draft(section["id"], section["step_id"], "draft", section["draft"],
                               section["validation"] | {"issues": issues}, section["word_count"])
    assert store.run(run["id"])["pause_reason"] == "section_must_be_rewritten"
    assert reports.section(report_id, "VIII")["validation"]["issues"] == issues
    detail = _pause_detail(reports, report_id, ["VIII"], 3)
    assert detail["sections"] == ["VIII"]
    assert [(reason["section_id"], reason["code"]) for reason in detail["reasons"]] == [
        ("VIII", code) for code in issue_codes[:3]
    ]
    assert [reason["detail"] for reason in detail["reasons"]] == [
        issue["detail"] for issue in issues[:3]
    ]


def test_report_failed_sections_and_reasons_keep_round_order(tmp_path):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    adapter.fail = lambda si: (ModelStepResult("failed", error="SYNTHETIC connection lost")
                               if si["task_type"] == "report_section"
                               and si["report_target"]["section_id"] in {"III", "V"} else None)
    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))
    error = store.run(run["id"])["error"]
    assert error["sections"] == ["III", "V"]
    assert [reason["section_id"] for reason in error["reasons"]] == error["sections"]
    assert _reason_codes(store, run) == [("III", "model_call_failed"), ("V", "model_call_failed")]
    assert all(reports.section(report_id, section)["status"] == "failed" for section in error["sections"])


def test_report_plan_uses_the_first_pdf_page_when_no_source_has_an_abstract(tmp_path):
    flow, store, reports, _, run, scope, report_id = report_flow(tmp_path, passage_kind="pdf_page")
    source_id = store.conn.execute("SELECT source_version_id FROM corpus_memberships").fetchone()[0]

    asyncio.run(run_report(flow, run, scope))

    step = store.step(run["id"], "report_plan", "model:report_plan")
    payload = store.step_input_payload(step["output"]["step_input_id"])
    expected = [passage for passage in store.passages_for(source_id) if passage["kind"] == "pdf_page"]
    assert [(passage["passage_id"], passage["locator"]["kind"]) for passage in payload["passages"]] == [
        (expected[0]["id"], "pdf_page")
    ]
    assert payload["allowlist"]["passage_ids"] == [expected[0]["id"]]
    assert reports.report(report_id)["status"] == "valid"


def test_report_plan_keeps_an_abstract_without_adding_its_pdf_page(tmp_path):
    flow, store, reports, _, run, scope, report_id = report_flow(tmp_path)
    source_id = store.conn.execute("SELECT source_version_id FROM corpus_memberships").fetchone()[0]
    abstract_id = next(passage["id"] for passage in store.passages_for(source_id)
                       if passage["kind"] == "abstract")
    _add_pdf(store, source_id, ["SYNTHETIC PDF page that must not widen the report plan allowlist."])

    asyncio.run(run_report(flow, run, scope))

    step = store.step(run["id"], "report_plan", "model:report_plan")
    payload = store.step_input_payload(step["output"]["step_input_id"])
    assert [(passage["passage_id"], passage["locator"]["kind"]) for passage in payload["passages"]] == [
        (abstract_id, "abstract")
    ]
    assert payload["allowlist"]["passage_ids"] == [abstract_id]


def test_report_run_writes_every_section_and_finalizes_a_valid_report(tmp_path):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)

    asyncio.run(run_report(flow, run, scope))

    sections = reports.sections(report_id)
    assert [section["section_id"] for section in sections] == [
        "abstract", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "index_terms",
    ]
    assert all(section["status"] == "valid" for section in sections)
    assert reports.report(report_id)["status"] == "valid"
    assert reports.report(report_id)["report_version"] == 1
    for section_id in ("III", "IV", "V"):
        claim_count = store.conn.execute(
            "SELECT COUNT(*) FROM report_claims WHERE report_section_id = ?",
            (reports.section(report_id, section_id)["id"],),
        ).fetchone()[0]
        assert claim_count >= 1
    section_inputs = {call["report_target"]["section_id"]: call for call in adapter.calls
                      if call["task_type"] == "report_section"}
    assert all(call["report_target"]["limitations_core"] is None for call in adapter.calls
               if call["task_type"] == "report_plan")
    assert all(call["report_target"]["limitations_core"] is None for section, call in section_inputs.items()
               if section != "VIII")
    viii = reports.section(report_id, "VIII")
    core = section_inputs["VIII"]["report_target"]["limitations_core"]
    assert core == viii["validation"]["numbers"]
    assert core["corpus"] == reports.snapshot(report_id)["corpus"]
    assert core["kind"] == "limitations"
    assert viii["draft"]["text"].startswith("1. Recall was not measured")
    assert section_inputs["VIII"]["passages"] == []
    assert run_assembly_checks(store, reports, report_id) == []
    assert [cell["column_id"] for cell in section_inputs["VI"]["report_target"]["cells"]] == [
        section_inputs["VI"]["report_target"]["plan"]["limitations_column_id"]
    ]
    assert [cell["column_id"] for cell in section_inputs["VII"]["report_target"]["cells"]] == [
        section_inputs["VII"]["report_target"]["plan"]["future_work_column_id"]
    ]
    link = store.conn.execute(
        "SELECT cell_id, anchor_text, anchor_match FROM report_citation_links WHERE cell_id IS NOT NULL"
    ).fetchone()
    assert dict(link) == {"cell_id": reports.snapshot(report_id)["cells"][0]["cell_id"],
                          "anchor_text": CELL_QUOTE, "anchor_match": "exact"}
    provenance = json.loads(store.conn.execute(
        "SELECT provenance_json FROM report_gaps WHERE report_id = ? AND gap_id = 'gap9'", (report_id,),
    ).fetchone()[0])
    vi_input_id = store.step(run["id"], "report_section:VI", "model:report_section")["output"]["step_input_id"]
    assert provenance == {"origin": "model", "section_id": "VI", "step_input_id": vi_input_id}
    before_calls = len(adapter.calls)
    before_numbers = reports.section(report_id, "VIII")["validation"]["numbers"]
    asyncio.run(run_report(flow, store.run(run["id"]), scope))
    assert len(adapter.calls) == before_calls
    assert len([section for section in reports.sections(report_id) if section["section_id"] == "VIII"]) == 1
    assert reports.section(report_id, "VIII")["validation"]["numbers"] == before_numbers


def test_equation_source_warning_alone_finalizes_valid(tmp_path, monkeypatch):
    flow, store, reports, _, run, scope, report_id = report_flow(tmp_path)
    observed = []

    def checks_with_equation_warning(store_arg, reports_arg, report_id_arg):
        assert run_assembly_checks(store_arg, reports_arg, report_id_arg) == []
        observed.append(report_id_arg)
        return [{"rule": "equation_text_source_warning", "section_id": "IV",
                 "detail": "WARNING: IV.1 equation came from ocr text."}]

    monkeypatch.setattr(assembly, "run_assembly_checks", checks_with_equation_warning)
    asyncio.run(run_report(flow, run, scope))
    assert observed == [report_id]
    assert reports.report(report_id)["status"] == "valid"


def test_viii_records_a_prior_section_budget_cut_in_the_full_run(tmp_path, monkeypatch):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    monkeypatch.setitem(SECTION_BUDGET_TOKENS, "III", 1)
    asyncio.run(run_report(flow, run, scope))
    viii = reports.section(report_id, "VIII")
    assert viii["validation"]["numbers"]["truncation"]["by_section"]["III"]["passage"] >= 1
    assert viii["validation"]["numbers"]["truncation"]["budget_cut"] >= 1
    assert viii["validation"]["numbers"]["truncation"]["missing_evidence"] == 0
    assert reports.report(report_id)["status"] == "valid"


def test_failed_viii_keeps_its_model_independent_numbers_without_text(tmp_path):
    flow, store, reports, _, run, scope, report_id = report_flow(tmp_path, broken_section="VIII")
    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))
    viii = reports.section(report_id, "VIII")
    assert viii["status"] == "failed"
    assert viii["draft"] is None
    assert viii["validation"]["numbers"]["corpus"] == reports.snapshot(report_id)["corpus"]


def test_assembly_still_catches_a_wrong_corpus_count_in_viii_numbers(tmp_path):
    flow, store, reports, _, run, scope, report_id = report_flow(tmp_path)
    asyncio.run(run_report(flow, run, scope))
    section = reports.section(report_id, "VIII")
    validation = section["validation"] | {"numbers": section["validation"]["numbers"] |
                  {"corpus": section["validation"]["numbers"]["corpus"] | {"included": 999}}}
    reports.save_section_draft(section["id"], section["step_id"], "valid", section["draft"],
                               validation, section["word_count"])
    assert "corpus_count_mismatch" in {issue["rule"] for issue in run_assembly_checks(store, reports, report_id)}


def test_assembly_catches_viii_text_drift(tmp_path):
    flow, store, reports, _, run, scope, report_id = report_flow(tmp_path)
    asyncio.run(run_report(flow, run, scope))
    section = reports.section(report_id, "VIII")
    draft = section["draft"] | {"text": section["draft"]["text"] + " 999 included sources."}
    reports.save_section_draft(section["id"], section["step_id"], "valid", draft,
                               section["validation"], section["word_count"])
    assert "limitations_text_drift" in {issue["rule"] for issue in run_assembly_checks(store, reports, report_id)}


def test_report_run_fails_when_the_evidence_table_is_not_ready(tmp_path):
    flow, store, reports, _, run, scope, report_id = report_flow(tmp_path, fill=False)

    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))

    assert store.run(run["id"])["status"] == "failed"
    assert store.run(run["id"])["pause_reason"] == "table_not_ready"
    assert reports.sections(report_id) == []


def test_a_failed_section_pauses_the_run_after_its_round(tmp_path):
    flow, store, reports, _, run, scope, report_id = report_flow(tmp_path, broken_section="IV")

    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))

    assert store.run(run["id"])["status"] == "paused"
    assert store.run(run["id"])["pause_reason"] == "section_failed"
    assert {section["section_id"] for section in reports.sections(report_id)} == {"II", "III", "IV", "V"}
    assert reports.section(report_id, "IV")["status"] == "failed"


def test_an_ambiguous_citation_anchor_repairs_then_pauses_as_invalid_model_output(tmp_path):
    flow, store, reports, adapter, run, scope, report_id = report_flow(
        tmp_path, ambiguous_anchor_section="IV",
    )

    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))

    stopped = store.run(run["id"])
    assert stopped["status"] == "paused"
    assert stopped["pause_reason"] == "section_failed"
    assert stopped["error"]["sections"] == ["IV"]
    assert stopped["error"]["reasons"][0]["code"] == "citation_anchor_target_count"
    step = store.step(run["id"], "report_section:IV", "model:report_section")
    assert step["status"] == "failed"
    assert step["error_code"] == "invalid_model_output"
    assert {issue["code"] for issue in json.loads(step["error_json"])} == {
        "citation_anchor_target_count"
    }
    assert [call["report_target"]["section_id"] for call in adapter.calls
            if call["task_type"] == "report_section"].count("IV") == 2
    section = reports.section(report_id, "IV")
    assert section["status"] == "failed"
    assert {issue["code"] for issue in section["validation"]["issues"]} == {
        "citation_anchor_target_count"
    }


def test_an_empty_section_without_insufficient_evidence_pauses_the_run(tmp_path):
    flow, store, reports, _, run, scope, report_id = report_flow(tmp_path, empty_section="IV")

    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))

    assert store.run(run["id"])["status"] == "paused"
    assert store.run(run["id"])["pause_reason"] == "section_must_be_rewritten"
    section = reports.section(report_id, "IV")
    assert section["status"] == "draft"
    validation = section["validation"]
    assert validation["issues"] == [{"code": "empty_section",
                                     "detail": "section has no claims or insufficient-evidence entries"}]


def test_an_unframed_section_is_repaired_and_the_report_completes(tmp_path):
    flow, store, reports, _, run, scope, report_id = report_flow(tmp_path, unframed_section="IV")

    asyncio.run(run_report(flow, run, scope))

    assert reports.report(report_id)["status"] == "valid"
    section = reports.section(report_id, "IV")
    assert section["status"] == "valid"
    assert section["validation"]["issues"] == []
    repair = store.conn.execute(
        "SELECT section_id, sentence_id, outcome FROM report_phrase_repairs WHERE report_id = ?",
        (report_id,),
    ).fetchone()
    assert dict(repair) == {"section_id": "IV", "sentence_id": "IV.1#1", "outcome": "kept"}


def test_viii_repair_that_restates_a_number_pauses_for_rewrite(tmp_path):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    original_response = adapter.responder

    def scripted_response(step_input):
        task = step_input["task_type"]
        target = step_input["report_target"]
        if task == "report_section" and target["section_id"] == "VIII":
            draft = json.loads(original_response(step_input))
            draft["claims"][0]["text"] = "Item 3 xqz unframed synthetic sentence."
            return json.dumps(draft)
        if task == "report_phrase_repair" and target["section_id"] == "VIII":
            return json.dumps(envelope(step_input, "deixis.report_phrase_repair_draft.v1") | {
                "repairs": [{"sentence_id": item["sentence_id"],
                             "text": "3 studies xqz unframed synthetic sentence."}
                            for item in target["repair_request"]["sentences"]],
            })
        return original_response(step_input)

    adapter.responder = scripted_response
    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))

    assert store.run(run["id"])["status"] == "paused"
    assert store.run(run["id"])["pause_reason"] == "section_must_be_rewritten"
    viii = reports.section(report_id, "VIII")
    assert viii["status"] == "draft"
    assert viii["validation"]["ok"] is False
    issues = viii["validation"]["issues"]
    assert {issue["code"] for issue in issues} == {"unframed_exception", "limitations_number_restated"}
    assert [reason["code"] for reason in store.run(run["id"])["error"]["reasons"]] == [
        issue["code"] for issue in issues[:3]
    ]
    assert any(issue["detail"].startswith("/claims/0/text:") for issue in issues)
    assert any(call["task_type"] == "report_phrase_repair" and
               call["report_target"]["section_id"] == "VIII" for call in adapter.calls)
    assert viii["draft"]["claims"][0]["text"] == "3 studies xqz unframed synthetic sentence."
    assert viii["draft"]["text"].startswith("1. Recall was not measured")
    assert viii["validation"]["numbers"]
    assert not any(section["section_id"] == "VIII" and section["status"] == "valid"
                   for section in reports.sections(report_id))


def test_a_resumed_report_run_does_not_call_the_model_again_for_a_succeeded_section(tmp_path):
    flow, store, _, adapter, run, scope, _ = report_flow(tmp_path, broken_section="IV")
    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))
    before = Counter(
        call["report_target"]["section_id"] for call in adapter.calls if call["task_type"] == "report_section"
    )

    adapter.broken_section = None
    store.update_run(run["id"], status="running", pause_reason=None, error_json=None)
    asyncio.run(run_report(flow, store.run(run["id"]), scope))
    after = Counter(
        call["report_target"]["section_id"] for call in adapter.calls if call["task_type"] == "report_section"
    )

    assert after["III"] == before["III"]
    assert after["V"] == before["V"]
    assert after["IV"] > before["IV"]
