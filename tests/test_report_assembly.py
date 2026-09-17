"""Synthetic structural checks over a stored report; no model is called."""

import pytest

from deixis.storage import db
from deixis.storage.db import new_id
from deixis.workflow.report.assembly import run_assembly_checks
from deixis.workflow.report.store import ReportStore
from deixis.workflow.store import Store
from deixis.workflow.tables import TableStore


COLUMN = {
    "name": "Method", "instruction": "Record the method", "answer_format": "text",
    "options": None, "allow_multiple": False, "unit_hint": None,
}


def _claim(key, text, support_type, body_refs=None):
    return {
        "claim_key": key, "paragraph": 1, "text": text, "support_type": support_type,
        "table_ref": None, "equation_ref": None, "axis_id": None, "count": None,
        "equation_origin": None, "body_refs": body_refs or [], "gap_refs": [],
    }


@pytest.fixture
def report_with_sections(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    reports = ReportStore(store)
    research_id = store.create_research(
        "What methods were studied?", "attached", "quick", [], "fake", "fake-model", "en"
    )
    source_id = store.create_upload_source("SYNTHETIC method study")
    abstract_passage = store._insert_passage(
        source_id, None, "abstract", None, None, "synthetic", None, None,
        "SYNTHETIC abstract evidence.",
    )
    section_passage = store._insert_passage(
        source_id, None, "section", None, None, None, None, None,
        "SYNTHETIC selected-section evidence.",
    )
    store.add_to_corpus(research_id, source_id, "user_upload", selection_state="included", selection_origin="user")

    tables = TableStore(store)
    table_id = tables.create_table(research_id, "SYNTHETIC evidence", None, None, None)
    column_id = tables.add_column(research_id, table_id, COLUMN, 1, None)
    cell_run = store.create_run(research_id, "answer", {}, None)
    cell_step = store.step(cell_run["id"], "synthetic:cell", "model:cell_extraction")
    cell_input_id = new_id("sti")
    store.insert_step_input(
        cell_step["id"], research_id, cell_run["id"], 0,
        {"step_input_id": cell_input_id, "task_type": "cell_extraction", "scope_revision": 1,
         "skill_package_hash": "sha256:synthetic"},
        "base", "developer", "message", {},
    )
    cell_revision_id = tables.save_model_output(
        research_id, table_id, column_id, source_id, column_revision=1, state="value",
        value={"text": "SYNTHETIC method"}, note=None, reading_depth="full_text",
        output_status="structurally_valid",
        links=[{"passage_id": section_passage, "source_version_id": source_id,
                "anchor_text": "selected-section evidence", "anchor_match": "exact"}],
        run_id=cell_run["id"], step_id=cell_step["id"], step_input_id=cell_input_id,
        model_connection="fake", resolved_model="fake-model", scope_revision=1,
        cell_version_at_request=0, recheck=False,
    )
    cell_id = store.conn.execute(
        "SELECT cell_id FROM cell_revisions WHERE id = ?", (cell_revision_id,)
    ).fetchone()[0]
    store.update_run(cell_run["id"], status="completed")

    report_run = store.create_run(research_id, "report", {}, None)
    report_id = reports.create_report(research_id, report_run["id"], 1, "en")
    snapshot = reports.save_snapshot(report_id, table_id)
    budgets = {section_id: {"min_words": 0, "max_words": 100, "max_claims": 40}
               for section_id in ("abstract", "I", "III", "IV", "VIII", "IX")}
    reports.set_plan(report_id, {
        "glossary": [{"term": "resource allocation", "definition": "Resource allocation assigns capacity.",
                      "passage_id": abstract_passage}],
        "corpus": snapshot["corpus"], "section_budgets": budgets,
    })

    report_step = store.step(report_run["id"], "report:synthetic", "model:report_section")
    report_input_id = new_id("sti")
    store.insert_step_input(
        report_step["id"], research_id, report_run["id"], 0,
        {"step_input_id": report_input_id, "task_type": "report_section", "scope_revision": 1,
         "skill_package_hash": "sha256:synthetic"},
        "base", "developer", "message", {},
    )

    section_ids = {}
    for section_id, ordinal, text in (
        ("abstract", 0, None),
        ("II", 2, "The frozen corpus contained 0 found, 1 unique, 0 screened, and 1 included sources; "
                  "full text was available for 0/1 included sources."),
        ("III", 3, None),
        ("VIII", 8, "The limitations cover 1 included and 0 full-text sources."),
    ):
        section_key = reports.create_section(report_id, section_id, ordinal)
        section_ids[section_id] = section_key
        reports.save_section_draft(
            section_key, None if section_id in {"II", "VIII"} else report_step["id"], "valid",
            {"text": text} if text is not None else {"claims": []}, {"ok": True, "issues": []}, 10,
        )

    reports.save_claims(section_ids["III"], [
        _claim("III.1", "Resource allocation assigns capacity.", "source_stated"),
    ], [{"claim_key": "III.1", "passage_id": section_passage, "source_version_id": source_id,
         "step_input_id": report_input_id, "anchor_text": "selected-section evidence", "anchor_match": "exact"}])
    reports.save_claims(section_ids["abstract"], [
        _claim("abstract.1", "This survey summarizes the evidence.", "analyst_inference", ["III.1"]),
    ], [{"claim_key": "abstract.1", "passage_id": abstract_passage, "source_version_id": source_id,
         "step_input_id": report_input_id, "anchor_text": "abstract evidence", "anchor_match": "exact"}])

    yield {
        "store": store, "reports": reports, "report_id": report_id, "report_step_id": report_step["id"],
        "report_input_id": report_input_id, "section_ids": section_ids, "source_id": source_id,
        "abstract_passage": abstract_passage, "section_passage": section_passage, "cell_id": cell_id,
    }
    conn.close()


def _issues(lib):
    return run_assembly_checks(lib["store"], lib["reports"], lib["report_id"])


def test_clean_report_returns_an_empty_list(report_with_sections):
    assert _issues(report_with_sections) == []


def test_duplicate_claim_key_across_sections_is_an_error(report_with_sections):
    lib = report_with_sections
    section_id = lib["reports"].create_section(lib["report_id"], "IV", 4)
    lib["reports"].save_section_draft(
        section_id, lib["report_step_id"], "valid", {"claims": []}, {"ok": True, "issues": []}, 5
    )
    lib["reports"].save_claims(
        section_id, [_claim("III.1", "A duplicate key.", "source_stated")], []
    )

    issues = _issues(lib)

    assert {issue["rule"] for issue in issues} == {"duplicate_claim_key"}


def test_glossary_term_used_before_its_definition_section_is_a_warning(report_with_sections):
    lib = report_with_sections
    section_id = lib["reports"].create_section(lib["report_id"], "I", 1)
    lib["reports"].save_section_draft(
        section_id, lib["report_step_id"], "valid", {"claims": []}, {"ok": True, "issues": []}, 8
    )
    lib["reports"].save_claims(section_id, [
        _claim("I.1", "Resource allocation is considered below.", "analyst_inference", ["III.1"]),
    ], [{"claim_key": "I.1", "passage_id": lib["abstract_passage"], "source_version_id": lib["source_id"],
         "step_input_id": lib["report_input_id"], "anchor_text": "abstract evidence", "anchor_match": "exact"}])

    issues = _issues(lib)

    assert {issue["rule"] for issue in issues} == {"glossary_term_before_definition_warning"}
    assert issues[0]["detail"].startswith("WARNING:")


def test_abstract_claim_without_body_refs_is_an_error(report_with_sections):
    lib = report_with_sections
    lib["reports"].save_claims(
        lib["section_ids"]["abstract"],
        [_claim("abstract.1", "This survey summarizes the evidence.", "analyst_inference")], [],
    )

    issues = _issues(lib)

    assert {issue["rule"] for issue in issues} == {"body_ref_missing"}
    assert issues[0]["section_id"] == "abstract"


def test_derived_claim_cannot_claim_stronger_support_than_its_body_refs(report_with_sections):
    lib = report_with_sections
    lib["reports"].save_claims(lib["section_ids"]["III"], [
        _claim("III.1", "Resource allocation assigns capacity.", "analyst_inference"),
    ], [{"claim_key": "III.1", "passage_id": lib["abstract_passage"], "source_version_id": lib["source_id"],
         "step_input_id": lib["report_input_id"], "anchor_text": "abstract evidence", "anchor_match": "exact"}])
    lib["reports"].save_claims(lib["section_ids"]["abstract"], [
        _claim("abstract.1", "This survey summarizes the evidence.", "source_stated", ["III.1"]),
    ], [{"claim_key": "abstract.1", "cell_id": lib["cell_id"], "source_version_id": lib["source_id"],
         "step_input_id": lib["report_input_id"], "anchor_text": "selected-section evidence", "anchor_match": "exact"}])

    issues = _issues(lib)

    assert {issue["rule"] for issue in issues} == {"derived_support_too_strong", "derived_depth_too_deep"}


def test_section_ii_and_viii_numbers_match_the_frozen_corpus(report_with_sections):
    lib = report_with_sections
    section = lib["reports"].section(lib["report_id"], "II")
    lib["reports"].save_section_draft(
        section["id"], None, "valid",
        {"text": "The frozen corpus contained 9 found, 1 unique, 0 screened, and 1 included sources; "
                 "full text was available for 0/1 included sources."},
        {"ok": True, "issues": []}, 10,
    )

    issues = _issues(lib)

    assert {issue["rule"] for issue in issues} == {"corpus_count_mismatch"}
    assert issues[0]["section_id"] == "II"


def test_section_word_count_over_budget_is_an_error(report_with_sections):
    lib = report_with_sections
    section = lib["reports"].section(lib["report_id"], "VIII")
    lib["reports"].save_section_draft(
        section["id"], None, "valid", section["draft"], {"ok": True, "issues": []}, 700,
    )

    issues = _issues(lib)

    assert {issue["rule"] for issue in issues} == {
        "section_word_count_over_budget", "report_word_count_over_budget",
    }
    assert {issue["section_id"] for issue in issues} == {"VIII", "report"}
