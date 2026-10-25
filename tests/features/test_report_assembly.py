"""Preservation tests: synthetic structural checks over stored reports; no model is called.

RF4 keeps these final assertions while moving model-correctable rules earlier.
"""

import copy
import json

import pytest

from deixis.storage import db
from deixis.storage.db import new_id
from deixis.workflow.features.report.report_assembly import run_assembly_checks
from deixis.workflow.features.report import report_review_methodology as review_methodology
from deixis.workflow.features.report.report_store import ReportStore
from deixis.workflow.run.store import Store
from deixis.workflow.features.tables.tables import TableStore


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
        "limitations_column_id": column_id, "future_work_column_id": column_id,
    })

    report_step = store.step(report_run["id"], "report:synthetic", "model:report_section")
    report_input_id = new_id("sti")
    store.insert_step_input(
        report_step["id"], research_id, report_run["id"], 0,
        {"step_input_id": report_input_id, "task_type": "report_section", "scope_revision": 1,
         "skill_package_hash": "sha256:synthetic",
         "question": {"text": "What methods were studied?", "language_hint": "en"},
         "passages": [{"passage_id": abstract_passage}, {"passage_id": section_passage}],
         "report_target": {"cells": [{"cell_id": cell_id}], "gap_candidates": []}},
        "base", "developer", "message", {},
    )

    section_ids = {}
    for section_id, ordinal, text in (
        ("abstract", 0, None),
        ("II", 2, "The frozen corpus contained 0 found, 1 unique, 0 screened, and 1 included sources; "
                  "full text was available for 0/1 included sources."),
        ("III", 3, None),
        ("VIII", 8, ""),
    ):
        section_key = reports.create_section(report_id, section_id, ordinal)
        section_ids[section_id] = section_key
        numbers = None
        if section_id == "II":
            corpus = snapshot["corpus"]
            numbers = {"version": 1, "kind": "review_methodology", "corpus": corpus,
                       "full_text_ratio": corpus["full_text"] / corpus["included"]}
        elif section_id == "VIII":
            corpus = snapshot["corpus"]
            numbers = {"version": 1, "kind": "limitations", "corpus": corpus,
                       "included": corpus["included"], "full_text": corpus["full_text"],
                       "no_full_text_share": (corpus["included"] - corpus["full_text"]) / corpus["included"],
                       "items": []}
            text = review_methodology.render_limitations(numbers, "en")
        reports.save_section_draft(
            section_key, None if section_id in {"II", "VIII"} else report_step["id"], "valid",
            {"text": text} if text is not None else {"claims": []},
            {"ok": True, "issues": [], **({"numbers": numbers} if numbers else {})}, 10,
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


def _rules(lib):
    return {issue["rule"] for issue in _issues(lib)}


def _add_claim(lib, section_id, key, text, *, count=None, origin=None, equation_ref=None, links=None,
               support_type="source_stated", gap_refs=None):
    section = lib["section_ids"].get(section_id)
    if section is None:
        section = lib["reports"].create_section(lib["report_id"], section_id, {"IV": 4, "V": 5, "VI": 6,
                                                                            "VII": 7, "IX": 9}.get(section_id, 4))
        lib["section_ids"][section_id] = section
        lib["reports"].save_section_draft(section, lib["report_step_id"], "valid", {"claims": []},
                                          {"ok": True, "issues": []}, 5)
    claim = _claim(key, text, support_type)
    claim.update(count=count, equation_origin=origin, equation_ref=equation_ref, gap_refs=gap_refs or [])
    lib["reports"].save_claims(section, [claim], links or [])
    return claim


def _link(lib, key="IV.1", *, passage=True, source_id=None, anchor=None, match="exact"):
    return {"claim_key": key, "passage_id": lib["section_passage"] if passage else None,
            "cell_id": None if passage else lib["cell_id"],
            "source_version_id": source_id or lib["source_id"], "step_input_id": lib["report_input_id"],
            "anchor_text": anchor if anchor is not None else "selected-section evidence", "anchor_match": match}


def test_clean_report_returns_an_empty_list(report_with_sections):
    assert _issues(report_with_sections) == []


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
    numbers = copy.deepcopy(section["validation"]["numbers"])
    numbers["corpus"]["found"] = 9
    lib["reports"].save_section_draft(section["id"], None, "valid", section["draft"],
                                      {"ok": True, "issues": [], "numbers": numbers}, 10)

    issues = _issues(lib)

    assert {issue["rule"] for issue in issues} == {"corpus_count_mismatch"}
    assert issues[0]["section_id"] == "II"


@pytest.mark.parametrize("mutation,expected", [
    ("foreign", "citation_source_not_in_corpus"),
])
def test_rule8_citation_records(report_with_sections, mutation, expected):
    lib = report_with_sections
    conn = lib["store"].conn
    foreign_source = lib["store"].create_upload_source("SYNTHETIC foreign study")
    if mutation == "foreign":
        conn.execute("UPDATE report_citation_links SET source_version_id = ? WHERE claim_id IN"
                     " (SELECT id FROM report_claims WHERE claim_key = 'III.1')", (foreign_source,))
    elif mutation == "incomplete":
        conn.execute("UPDATE works SET source_key = NULL WHERE id IN"
                     " (SELECT work_id FROM source_versions WHERE id = ?)", (lib["source_id"],))
    else:
        conn.execute("UPDATE report_citation_links SET source_version_id = ? WHERE claim_id IN"
                     " (SELECT id FROM report_claims WHERE claim_key = 'III.1')", (foreign_source,))
    assert expected in _rules(lib)


@pytest.mark.parametrize("mutation,expected", [
    ("passage", "anchor_not_in_passage"),
    ("cell", "anchor_not_in_cell_evidence"),
])
def test_rule12_anchor_relocation(report_with_sections, mutation, expected):
    lib = report_with_sections
    conn = lib["store"].conn
    if mutation == "null":
        conn.execute("UPDATE report_citation_links SET anchor_match = NULL WHERE claim_id IN"
                     " (SELECT id FROM report_claims WHERE claim_key = 'III.1')")
    elif mutation == "passage":
        other = lib["store"]._insert_passage(lib["source_id"], None, "section", None, None, None,
                                              None, None, "Different passage.")
        conn.execute("UPDATE report_citation_links SET passage_id = ? WHERE claim_id IN"
                     " (SELECT id FROM report_claims WHERE claim_key = 'III.1')", (other,))
    else:
        _add_claim(lib, "IV", "IV.1", "A supported observation.", links=[_link(lib, passage=False)])
        snapshot = lib["reports"].snapshot(lib["report_id"])
        snapshot["cells"][0]["evidence"] = [{"quote": "A different quote."}]
        conn.execute("UPDATE report_snapshot SET snapshot_json = ? WHERE report_id = ?",
                     (json.dumps(snapshot), lib["report_id"]))
    assert expected in _rules(lib)


def _gap(lib, kind, gap_id="gap1", *, claim_keys=None, passage_ids=None, cell_ids=None, origin="model"):
    lib["reports"].save_gaps(lib["report_id"], [{
        "gap_id": gap_id, "kind": kind, "text": "A bounded finding.",
        "basis": {"basis_claim_keys": claim_keys or [], "basis_passage_ids": passage_ids or [],
                  "basis_cell_ids": cell_ids or [], "nearest_match": None},
        "provenance": {"origin": origin},
    }])


