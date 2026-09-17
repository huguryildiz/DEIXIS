"""Synthetic report persistence; no report run or model is executed."""

import pytest

from deixis.storage import db
from deixis.workflow.report.store import ReportStore
from deixis.workflow.store import Store


@pytest.fixture
def lib(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    research_id = store.create_research("Q?", "academic", "quick", ["openalex"], "fake", None, None)
    run = store.create_run(research_id, "report", {}, None)
    yield store, ReportStore(store), research_id, run["id"]
    conn.close()


def test_report_store_creates_a_report_and_its_sections_in_order(lib):
    _, reports, research_id, run_id = lib
    report_id = reports.create_report(research_id, run_id, 1, "en")
    reports.create_section(report_id, "IV", 2)
    reports.create_section(report_id, "III", 1)
    sections = reports.sections(report_id)
    assert [section["section_id"] for section in sections] == ["III", "IV"]
    assert all(section["status"] == "pending" for section in sections)
    assert reports.report(report_id)["status"] == "in_progress"


def test_report_store_persists_claim_refs_gaps_and_valid_version(lib):
    store, reports, research_id, run_id = lib
    report_id = reports.create_report(research_id, run_id, 1, "en")
    section_id = reports.create_section(report_id, "VI", 1)
    reports.set_plan(report_id, {"scope_statement": "Q"})
    step = store.step(run_id, "report:VI", "model:report_section")
    reports.save_section_draft(section_id, step["id"], "valid", {"claims": []}, {"issues": []}, 18)
    reports.save_claims(section_id, [{
        "claim_key": "VI.1", "paragraph": 1, "text": "A bounded claim.", "support_type": "analyst_inference",
        "table_ref": None, "equation_ref": None, "axis_id": None, "count": None, "equation_origin": None,
        "body_refs": ["IV.1"], "gap_refs": ["gap1"],
    }], [])
    claim_id = store.conn.execute("SELECT id FROM report_claims WHERE report_section_id = ?", (section_id,)).fetchone()[0]
    assert {(row["ref_kind"], row["ref_value"]) for row in store.conn.execute(
        "SELECT ref_kind, ref_value FROM report_claim_refs WHERE claim_id = ?", (claim_id,)
    )} == {("body_ref", "IV.1"), ("gap_ref", "gap1")}
    reports.save_gaps(report_id, [{"gap_id": "gap1", "kind": "corpus_absence", "text": "Bounded gap",
                                   "basis_cell_ids": [], "provenance": {"search_date": "now"}}])
    reports.save_phrase_repair(report_id, "VI", "VI.1", "before", "after", "kept")
    assert reports.finalize(report_id, "valid") == 1
    assert reports.report(report_id)["report_version"] == 1
    assert reports.report(report_id)["plan"] == {"scope_statement": "Q"}


def test_report_store_refuses_valid_version_with_pending_section(lib):
    _, reports, research_id, run_id = lib
    report_id = reports.create_report(research_id, run_id, 1, "en")
    reports.create_section(report_id, "IV", 1)
    with pytest.raises(ValueError, match="valid"):
        reports.finalize(report_id, "valid")
    assert reports.finalize(report_id, "draft") is None
    assert reports.report(report_id)["report_version"] is None
