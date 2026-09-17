"""Synthetic report-run orchestration; passing does not establish report quality."""

import asyncio
import json
from collections import Counter

import pytest

from deixis.config import Settings
from deixis.domain import skill
from deixis.storage import db
from deixis.storage.db import dumps, new_id
from deixis.workflow.concurrency import ModelCallLimiter
from deixis.workflow.flow import FlowDeps, ResearchFlow, RunStopped
from deixis.workflow.report.sections import run_report
from deixis.workflow.report.store import ReportStore
from deixis.workflow.store import Store
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
PASSAGE = "SYNTHETIC evidence states that molecule release scheduling uses a bounded formulation."
CELL_QUOTE = "SYNTHETIC evidence states that molecule release scheduling"


class ReportAdapter(FakeAdapter):
    def __init__(self, broken_section=None):
        super().__init__(responder=self._response)
        self.broken_section = broken_section

    def _response(self, step_input):
        task = step_input["task_type"]
        if task == "report_plan":
            return json.dumps(envelope(step_input, "deixis.report_plan_draft.v1") | {
                "scope_statement": "SYNTHETIC scope for bounded release scheduling formulations.",
                "research_questions": [
                    {"rq_id": "RQ1", "text": "SYNTHETIC: which formulation is reported?"},
                    {"rq_id": "RQ2", "text": "SYNTHETIC: which evidence supports it?"},
                ],
                "glossary": [],
                "axes": [],
            })
        if task != "report_section":
            from fakes import valid_response
            return valid_response(step_input)
        section_id = step_input["report_target"]["section_id"]
        if section_id == self.broken_section:
            return json.dumps({"SYNTHETIC_broken": True})
        claims, anchors = [], []
        if step_input["report_target"]["cells"]:
            cell = step_input["report_target"]["cells"][0]
            claims = [_claim(section_id, cell_ids=[cell["cell_id"]])]
            anchors = [{"claim_key": f"{section_id}.1", "passage_id": None,
                        "cell_id": cell["cell_id"], "quote": CELL_QUOTE}]
        elif step_input["passages"]:
            passage = step_input["passages"][0]
            claims = [_claim(section_id, passage_ids=[passage["passage_id"]])]
            anchors = [{"claim_key": f"{section_id}.1", "passage_id": passage["passage_id"],
                        "cell_id": None, "quote": CELL_QUOTE}]
        gaps = [{
            "gap_id": "gap9",
            "kind": "stated_limitation",
            "text": "SYNTHETIC model-proposed limitation.",
            "basis_claim_keys": [],
            "basis_passage_ids": [],
            "basis_cell_ids": [],
            "nearest_match": {"status": "not_searched", "source_id": None, "cell_id": None},
        }] if section_id == "VI" else []
        return json.dumps(envelope(step_input, "deixis.report_section_draft.v1") | {
            "section_id": section_id,
            "claims": claims,
            "citation_anchors": anchors,
            "subsections": [],
            "gaps": gaps,
            "insufficient_evidence": [],
        })


def _claim(section_id, passage_ids=None, cell_ids=None):
    return {
        "claim_key": f"{section_id}.1",
        "text": ("It encompasses the SYNTHETIC bounded formulation." if section_id == "III"
                 else "It has been reported that the SYNTHETIC formulation is bounded."),
        "support_type": "source_stated",
        "passage_ids": passage_ids or [],
        "cell_ids": cell_ids or [],
        "paragraph": 1,
        "table_ref": "TABLE_I" if section_id == "IV" else None,
        "equation_ref": None,
        "body_refs": [],
        "axis_id": None,
        "count": None,
        "equation_origin": None,
        "gap_refs": [],
    }


def report_flow(tmp_path, *, fill=True, broken_section=None):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    research_id = store.create_research(
        "How are SYNTHETIC molecular communication systems optimized?",
        "attached", "quick", [], "fake", "fake-model", "en",
    )
    source_id = store.create_upload_source("SYNTHETIC molecular communication study")
    passage_id = store._insert_passage(
        source_id, None, "abstract", None, None, "synthetic_fixture", None, None, PASSAGE,
    )
    store.add_to_corpus(research_id, source_id, "user_upload", selection_state="included", selection_origin="user")
    tables = TableStore(store)
    table_id = tables.create_table(research_id, "SYNTHETIC evidence", None, None, None)
    column_id = tables.add_column(research_id, table_id, COLUMN, 1, None)
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
        tables.save_model_output(
            research_id, table_id, column_id, source_id, column_revision=1, state="value",
            value={"text": "SYNTHETIC bounded formulation"}, note=None, reading_depth="abstract",
            output_status="structurally_valid",
            links=[{"passage_id": passage_id, "source_version_id": source_id,
                    "anchor_text": CELL_QUOTE, "anchor_match": "exact"}],
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
    adapter = ReportAdapter(broken_section)
    flow = ResearchFlow(FlowDeps(
        Settings(data_dir=tmp_path / "data", port=8765), store, {"fake": adapter},
        skill.load_skill_package(), None, limiter=ModelCallLimiter(3),
    ))
    return flow, store, reports, adapter, store.run(run["id"]), store.scope(research_id), report_id


def test_report_run_writes_every_section_and_finalizes_a_valid_report(tmp_path):
    flow, store, reports, _, run, scope, report_id = report_flow(tmp_path)

    asyncio.run(run_report(flow, run, scope))

    sections = reports.sections(report_id)
    assert [section["section_id"] for section in sections] == [
        "abstract", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "index_terms",
    ]
    assert all(section["status"] == "valid" for section in sections)
    assert reports.report(report_id)["status"] == "valid"
    assert reports.report(report_id)["report_version"] == 1
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
