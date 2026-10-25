"""Synthetic report-run orchestration; passing does not establish report quality."""

import asyncio
import json
from collections import Counter
from types import SimpleNamespace

import pytest

from deixis.config import Settings
from deixis.domain import contracts, skill
from deixis.models.adapter import ModelStepResult
from deixis.storage import db
from deixis.storage.db import dumps, new_id
from deixis.workflow.run.concurrency import ModelCallLimiter
from deixis.workflow.run.flow import FlowDeps, ResearchFlow, RunStopped
from deixis.workflow.features.report.report_sections import _citation_links, run_report
from deixis.workflow.features.report.report_assembly import run_assembly_checks
from deixis.workflow.features.report import report_sections as sections
from deixis.workflow.features.report.report_plan import ALLOWED_SUPPORT, freeze_plan, section_budgets
from deixis.workflow.features.report.report_store import ReportStore
from deixis.workflow.run.store import Store
from deixis.workflow.run.worker import Worker
from deixis.workflow.run import flow as flow_module
from deixis.workflow.features.tables.tables import TableStore
from fakes import FakeAdapter, envelope
from dataclasses import asdict
from deixis.domain.rules import TEST_EFFORT_BUDGETS
from deixis.workflow.search import small_batch
from test_criterion_passage_flow import library
import copy
from pathlib import Path
from deixis.workflow.features.report.report_gaps import generate_corpus_absence_candidates
from deixis.workflow.features.report.report_review_methodology import write_review_methodology
from deixis.workflow.run.store import NotFound
from deixis.workflow.features.report.report_selection import CELL_RESERVE_TOKENS
from deixis.workflow.features.report.report_selection import SECTION_BUDGET_TOKENS
from deixis.workflow.features.report.report_selection import select_evidence


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
        return json.dumps(envelope(step_input, "deixis.report_section_draft.v3") | {
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
                ambiguous_anchor_section=None, passage_kind="abstract", cell_quotes=None, section_repairs=None):
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
    budget = {"max_model_calls": 100, "max_provider_requests": 0}
    if section_repairs is not None:
        budget["max_report_section_repairs"] = section_repairs
    run = store.create_run(research_id, "report", budget, None, {"table_id": table_id})
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


def test_assembly_still_catches_a_wrong_corpus_count_in_viii_numbers(tmp_path):
    flow, store, reports, _, run, scope, report_id = report_flow(tmp_path)
    asyncio.run(run_report(flow, run, scope))
    section = reports.section(report_id, "VIII")
    validation = section["validation"] | {"numbers": section["validation"]["numbers"] |
                  {"corpus": section["validation"]["numbers"]["corpus"] | {"included": 999}}}
    reports.save_section_draft(section["id"], section["step_id"], "valid", section["draft"],
                               validation, section["word_count"])
    assert "corpus_count_mismatch" in {issue["rule"] for issue in run_assembly_checks(store, reports, report_id)}


def test_report_run_fails_when_the_evidence_table_has_no_included_row(tmp_path):
    # Empty cells do not stop a report (D68); a table none of whose rows is an included source does.
    flow, store, reports, _, run, scope, report_id = report_flow(tmp_path, fill=False)
    store.conn.execute("UPDATE selections SET state = 'excluded' WHERE research_id = ?", (run["research_id"],))

    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))

    assert store.run(run["id"])["status"] == "failed"
    assert store.run(run["id"])["pause_reason"] == "table_not_ready"
    assert reports.sections(report_id) == []


def test_a_section_that_fails_both_repairs_pauses_the_run(tmp_path):
    flow, store, reports, adapter, run, scope, report_id = report_flow(
        tmp_path, broken_section="IV", section_repairs=2)

    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))

    assert _section_calls(adapter)["IV"] == 3
    stopped = store.run(run["id"])
    assert (stopped["status"], stopped["pause_reason"], stopped["error"]["sections"]) == ("paused", "section_failed", ["IV"])
    assert reports.section(report_id, "IV")["status"] == "failed"
    step = store.step(run["id"], "report_section:IV", "model:report_section")
    assert (step["status"], step["error_code"]) == ("failed", "invalid_model_output")


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
    assert store.run(run["id"])["pause_reason"] == "section_failed"
    section = reports.section(report_id, "IV")
    assert section["status"] == "failed"
    validation = section["validation"]
    assert validation["issues"] == [{"code": "empty_section", "path": "/claims",
                                     "message": contracts.EMPTY_REPORT_SECTION_MESSAGE}]
    assert store.run(run["id"])["error"] == {
        "sections": ["IV"], "reasons": [{"section_id": "IV", "code": "empty_section", "detail": None}],
    }


def test_freeze_plan_overrides_all_model_supplied_code_owned_fields_without_mutating_the_draft():
    model_plan = {
        "scope_statement": "SYNTHETIC scope", "research_questions": [], "glossary": [], "axes": [],
        "corpus": {"included": 999}, "section_budgets": {"VI": {"max_words": 999999}},
        "allowed_support": {"VI": ["source_stated"]},
    }
    snapshot = {"corpus": {"found": 40, "unique": 22, "screened": 22, "included": 8, "full_text": 5}}

    frozen = freeze_plan(model_plan, snapshot, included_count=8)

    assert frozen["corpus"] == snapshot["corpus"]
    assert frozen["allowed_support"]["VI"] == ["analyst_inference"]
    assert frozen["section_budgets"] == section_budgets(5500, 8)
    assert model_plan["corpus"] == {"included": 999}
    assert ALLOWED_SUPPORT["VI"] == ("analyst_inference",)


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


# Synthetic D238 allocation evidence and the answer whose frozen list is missing; no model or scientific validation.

def answer_run(store, rid):
    run = store.create_run(rid, "answer", asdict(TEST_EFFORT_BUDGETS["quick"]), None)
    store.update_run(run["id"], status="completed")  # its steps are written here, not by the worker
    return store.run(run["id"])


def flow_of(store):
    flow = object.__new__(ResearchFlow)
    flow.store = store
    return flow


def test_missing_frozen_list_becomes_recorded_failed_answer(tmp_path):
    import asyncio
    from deixis.workflow.run.flow import RunStopped

    store, rid = library(tmp_path)
    discovery = store.create_run(rid, "discovery", {"inspection": {"policy": small_batch.POLICY}}, None)
    store.update_run(discovery["id"], status="completed")
    run = answer_run(store, rid)
    run["budget"] = small_batch.answer_budget(store, rid, run["scope_revision"], run["budget"])
    flow = flow_of(store)
    flow._held = {}
    with pytest.raises(RunStopped):
        asyncio.run(flow._answer(run, store.scope(rid)))
    failed = store.run(run["id"])
    assert failed["status"] == "failed"
    assert failed["pause_reason"] == "answer_frozen_list_missing"
    assert failed["error"]["list_run_id"] == discovery["id"]


# RF3 synthetic replay and repair behavior; no real-model or evidence-quality claim.

REPLAY = json.loads((Path(__file__).parent.parent / "fixtures/research/report-empty-vi-replay.json").read_text())


EMPTY_MESSAGE = (
    "section has no claims or insufficient-evidence entries; write at least one claim supported by the given evidence, "
    "or one insufficient_evidence entry naming the missing material and why; never invent a claim, passage, cell, gap or quote"
)


@pytest.mark.parametrize("section_id", ["VI"])
def test_empty_section_replay_is_a_semantic_issue_in_every_section(section_id):
    si, draft = copy.deepcopy(REPLAY["step_input"]), copy.deepcopy(REPLAY["output"])
    si["report_target"]["section_id"] = draft["section_id"] = section_id
    result = contracts.validate_model_output(si, draft)
    assert not result.ok
    assert [vars(issue) for issue in result.issues] == [
        {"code": "empty_section", "path": "/claims", "message": EMPTY_MESSAGE}
    ]


# Corpus-absence candidates derived from synthetic frozen snapshots.

def test_corpus_absence_requires_at_least_three_full_text_applicable_not_found_rows():
    snapshot = {
        "cells": [
            {"cell_id": f"cel_{i}", "column_id": "col_x", "source_version_id": f"srv_{i}",
             "state": "not_found_in_inspected_scope", "reading_depth": "full_text"}
            for i in range(2)
        ],
        "rows": [{"source_version_id": f"srv_{i}", "reading_depth": "full_text"} for i in range(2)],
    }
    assert generate_corpus_absence_candidates(snapshot, [{"axis_id": "AX1", "column_id": "col_x"}]) == []

    snapshot["cells"] += [{"cell_id": "cel_2", "column_id": "col_x", "source_version_id": "srv_2",
                            "state": "not_found_in_inspected_scope", "reading_depth": "full_text"}]
    snapshot["rows"] += [{"source_version_id": "srv_2", "reading_depth": "full_text"}]
    candidates = generate_corpus_absence_candidates(snapshot, [{"axis_id": "AX1", "column_id": "col_x"}])
    assert len(candidates) == 1 and candidates[0]["full_text_applicable_count"] == 3


# Synthetic, code-written Review Methodology section coverage.

@pytest.fixture
def lib(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    reports = ReportStore(store)
    research_id = store.create_research(
        "Which methods were studied?", "academic", "quick", ["openalex"], "fake", "fake-screening", "en"
    )
    discovery = store.create_run(research_id, "discovery", {"max_model_calls": 4}, None)
    search = store.step(discovery["id"], "search:0", "provider_search:openalex")
    store.finish_step(search["id"], "succeeded", output={"status": "completed", "result_count": 7})
    store.add_search_run(
        research_id=research_id, run_id=discovery["id"], step_id=search["id"], scope_revision=1,
        provider="openalex", query_text="synthetic methods", request_description="synthetic request",
        access_mode="keyless", status="completed", delivery_class=None, result_count=7, provider_total=7,
        page_limit=25, error_json=None, raw_payload_path=None,
    )
    screening = store.step(discovery["id"], "screening", "model:screening")
    step_input_id = new_id("sti")
    store.insert_step_input(
        screening["id"], research_id, discovery["id"], 0,
        {"step_input_id": step_input_id, "task_type": "screening", "scope_revision": 1,
         "skill_package_hash": "sha256:synthetic", "capabilities": {"supported_tasks": ["screening"]},
         "budget": {"max_model_calls": 4},
         "model": {"connection": "fake", "requested_model": "fake-screening"}},
        "base", "developer", "message", {},
    )
    store.finish_step(screening["id"], "succeeded", output={"result": {"decisions": []}})
    store.update_run(discovery["id"], status="completed")

    acquisition = store.create_run(research_id, "answer", {}, None)
    store.finish_step(store.step(acquisition["id"], "fetch:a", "fetch_pdf")["id"], "succeeded")
    store.finish_step(store.step(acquisition["id"], "other:a", "pdf_other_copy")["id"], "failed")
    store.update_run(acquisition["id"], status="completed")
    report_run = store.create_run(research_id, "report", {}, None)
    report_id = reports.create_report(research_id, report_run["id"], 1, "en")
    yield store, reports, report_id, research_id
    conn.close()


def test_review_methodology_reports_corpus_counts_and_provider_dates_without_a_model_call(lib):
    store, reports, report_id, research_id = lib
    snapshot = {"corpus": {"found": 17, "unique": 11, "screened": 9, "included": 4, "full_text": 2}}

    write_review_methodology(store, reports, report_id, research_id, snapshot)

    section = reports.section(report_id, "II")
    assert section["status"] == "valid" and section["step_id"] is None
    assert str(snapshot["corpus"]["found"]) in section["draft"]["text"]
    assert "synthetic methods" in section["draft"]["text"]
    # No fast-path step records the compiled query version this sentence names (slice 3b).
    assert "the compiled query version was not recorded" in section["draft"]["text"]
    numbers = section["validation"]["numbers"]
    assert numbers["corpus"] == snapshot["corpus"]
    assert (numbers["fetch_pdf"], numbers["pdf_other_copy"], numbers["full_text_ratio"]) == (1, 1, 0.5)
    assert "17 found, 11 unique, 9 screened, and 4 included" in section["draft"]["text"]
    assert json.loads(store.conn.execute(
        "SELECT usage_json FROM runs WHERE id = (SELECT run_id FROM reports WHERE id = ?)", (report_id,)
    ).fetchone()[0]).get("model_calls", 0) == 0


SUMMARY = {"sent": 7, "accepted": 1, "returned": 40, "raw_returned": 44, "admitted_returned": 40, "failed": 3,
           "passed_filter": 12, "late_records": 3, "unknown": 2, "unsent": {"cutoff": 1}}


def chain_steps(store, research_id, requests=(), *, seeds=(3, 1), kept=12, summary=True):
    """A SYNTHETIC fast chain on the fixture's discovery run: semantic seeds, seeds the ranking added, the request
    steps given as (status, output, delivery_class), and the summary `fast_chain.Round.summary` writes. The summary's
    `sent` counts every request not cancelled, a failure before sending too; the report must not read it."""
    run_id = store.conn.execute("SELECT id FROM runs WHERE research_id = ? AND kind = 'discovery'", (research_id,)).fetchone()[0]
    for key, count in zip(("fast_chain:seeds", "fast_chain:seeds_fallback"), seeds):
        store.finish_step(store.step(run_id, key, "code:fast_chain")["id"], "succeeded",
                          output={"seeds": [{"source_version_id": f"sv{i}", "references": ["W1", "W2"]} for i in range(count)]})
    for i, (status, output, delivery) in enumerate(requests):
        store.finish_step(store.step(run_id, f"chain:fast:{i}", "provider_chain:openalex")["id"], status, output=output,
                          delivery_class=delivery)
    if summary:
        store.finish_step(store.step(run_id, "fast_chain:summary", "code:fast_chain")["id"], "succeeded",
                          output=SUMMARY | {"passed_filter": kept})
    return run_id


def sends(n, attempts=1):
    return {"transport": {"reserved": 1, "attempts": attempts, "sends": n}}


# Synthetic, model-independent tests for report evidence selection.

class PassageStore:
    def __init__(self, passages, superseded=()):
        self.passages = passages
        self.superseded = {item["id"]: item for item in superseded}

    def passage(self, passage_id):
        found = self.superseded.get(passage_id) or next(
            (item for items in self.passages.values() for item in items if item["id"] == passage_id), None)
        if found is None:
            raise NotFound(passage_id)
        return found

    def passages_for(self, source_version_id):
        return list(self.passages.get(source_version_id, []))

    def search_passages(self, source_version_ids, _query, limit):
        return [passage for source_id in source_version_ids
                for passage in self.passages.get(source_id, [])][:limit]


def passage(number, source, text="SYNTHETIC passage"):
    return {"id": f"psg_{number:08d}", "source_version_id": source, "kind": "pdf_page", "text": text}


def cell(number, source, column, evidence):
    return {
        "cell_id": f"cel_{number:08d}", "cell_revision_id": f"crv_{number:08d}", "column_id": column,
        "source_version_id": source, "state": "value", "value": {"text": f"value {number}"},
        "reading_depth": "full_text", "evidence": [
            {"passage_id": item["id"], "quote": item["text"]} for item in evidence
        ],
    }


def test_section_iv_admits_every_cell_with_its_quotes_before_any_page(monkeypatch):
    # D58 replaces the old rule that a cell came only with all of its pages: a cell carries its stored quotes, and pages
    # are added after every cell, while the room lasts.
    first = passage(1, "srv_source01", "SYNTHETIC " + "a" * 600)
    second = passage(2, "srv_source02", "SYNTHETIC " + "b" * 600)
    snapshot = {
        "rows": [{"source_version_id": "srv_source01"}, {"source_version_id": "srv_source02"}],
        "columns": [{"column_id": "col_method01", "name": "Method", "instruction": "Method"}],
        "cells": [cell(1, "srv_source01", "col_method01", [first]),
                  cell(2, "srv_source02", "col_method01", [second])],
    }
    monkeypatch.setitem(SECTION_BUDGET_TOKENS, "IV", 650)
    monkeypatch.setitem(CELL_RESERVE_TOKENS, "IV", 0)

    selected = select_evidence(PassageStore({"srv_source01": [first], "srv_source02": [second]}),
                               snapshot, "IV", {"axes": []}, [])

    assert [item["cell_id"] for item in selected["cells"]] == ["cel_00000001", "cel_00000002"]
    assert {item["id"] for item in selected["passages"]} == {"psg_00000001"}
    assert selected["truncated"] == [{"source_version_id": "srv_source02", "record_kind": "cell_page"}]
