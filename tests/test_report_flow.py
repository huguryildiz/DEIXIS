"""Synthetic report-run orchestration; passing does not establish report quality."""

import asyncio
import json
from collections import Counter
from types import SimpleNamespace

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
    def __init__(self, broken_section=None, empty_section=None):
        super().__init__(responder=self._response)
        self.broken_section = broken_section
        self.empty_section = empty_section

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
        "support_type": "source_stated",
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


def report_flow(tmp_path, *, fill=True, broken_section=None, empty_section=None,
                passage_kind="abstract"):
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
            source_id, None, "abstract", None, None, "synthetic_fixture", None, None, PASSAGE,
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
        for column_id in column_ids:
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
    adapter = ReportAdapter(broken_section, empty_section)
    flow = ResearchFlow(FlowDeps(
        Settings(data_dir=tmp_path / "data", port=8765), store, {"fake": adapter},
        skill.load_skill_package(), None, limiter=ModelCallLimiter(3),
    ))
    return flow, store, reports, adapter, store.run(run["id"]), store.scope(research_id), report_id


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
