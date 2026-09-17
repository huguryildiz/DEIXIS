"""Synthetic report persistence; no report run or model is executed."""

import pytest

from deixis.storage import db
from deixis.storage.db import new_id
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


def test_save_claims_retry_replaces_claims_refs_and_citation_links_atomically(lib):
    store, reports, research_id, run_id = lib
    report_id = reports.create_report(research_id, run_id, 1, "en")
    section_id = reports.create_section(report_id, "VI", 1)
    source_id = store.create_upload_source("SYNTHETIC source")
    passage_id = store._insert_passage(source_id, None, "abstract", None, None, "synthetic", None, None,
                                        "SYNTHETIC evidence")
    step = store.step(run_id, "report:VI", "model:report_section")
    step_input_id = new_id("sti")
    store.insert_step_input(step["id"], research_id, run_id, 0,
                            {"step_input_id": step_input_id, "task_type": "report_section",
                             "scope_revision": 1, "skill_package_hash": "sha256:synthetic"},
                            "base", "developer", "message", {})
    first = [{"claim_key": "VI.1", "paragraph": 1, "text": "First claim", "support_type": "analyst_inference",
              "body_refs": ["V.1"], "gap_refs": []}]
    retry = [{"claim_key": "VI.2", "paragraph": 2, "text": "Replacement claim", "support_type": "analyst_inference",
              "body_refs": [], "gap_refs": ["gap2"]}]
    link = lambda key: [{"claim_key": key, "passage_id": passage_id, "source_version_id": source_id,
                         "step_input_id": step_input_id, "anchor_text": "SYNTHETIC evidence", "anchor_match": "exact"}]
    reports.save_claims(section_id, first, link("VI.1"))

    reports.save_claims(section_id, retry, link("VI.2"))

    claims = store.conn.execute("SELECT id, claim_key, text FROM report_claims WHERE report_section_id = ?",
                                (section_id,)).fetchall()
    assert [(row["claim_key"], row["text"]) for row in claims] == [("VI.2", "Replacement claim")]
    assert [(row["ref_kind"], row["ref_value"]) for row in store.conn.execute(
        "SELECT ref_kind, ref_value FROM report_claim_refs WHERE claim_id = ?", (claims[0]["id"],)
    )] == [("gap_ref", "gap2")]
    links = store.conn.execute("SELECT claim_id, passage_id FROM report_citation_links").fetchall()
    assert [(row["claim_id"], row["passage_id"]) for row in links] == [(claims[0]["id"], passage_id)]


def test_save_gaps_retry_replaces_changed_text_for_the_same_gap_id(lib):
    store, reports, research_id, run_id = lib
    report_id = reports.create_report(research_id, run_id, 1, "en")
    gaps = [{"gap_id": "gap1", "kind": "corpus_absence", "text": "SYNTHETIC bounded absence",
             "basis_cell_ids": [], "provenance": {"search_date": "2026-09-17"}}]

    reports.save_gaps(report_id, gaps)
    reports.save_gaps(report_id, [{**gaps[0], "text": "SYNTHETIC replacement absence"}])

    assert store.conn.execute("SELECT COUNT(*) FROM report_gaps WHERE report_id = ?", (report_id,)).fetchone()[0] == 1
    assert store.conn.execute("SELECT text FROM report_gaps WHERE report_id = ?", (report_id,)).fetchone()[0] == \
        "SYNTHETIC replacement absence"
