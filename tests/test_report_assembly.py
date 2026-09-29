"""Synthetic structural checks over a stored report; no model is called."""

import copy
import json

import pytest

from deixis.domain import contracts
from deixis.storage import db
from deixis.storage.db import new_id
from deixis.workflow.report.assembly import run_assembly_checks
from deixis.workflow.report import phrasing, review_methodology
from deixis.workflow.report import gaps as report_gaps
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
    phrasebank_text = contracts._phrasebank_text()
    for section_id, claims in (("III", [_claim("III.1", "Resource allocation assigns capacity.", "source_stated")]),
                               ("abstract", [_claim("abstract.1", "This survey summarizes the evidence.",
                                                    "analyst_inference")])):
        for flagged in phrasing.flagged_sentences(section_id, claims, phrasebank_text, "en"):
            reports.save_phrase_repair(report_id, section_id, flagged["sentence_id"], flagged["text"],
                                       flagged["text"], "unframed_exception")

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


def _set_section(lib, section_id, *, draft=None, validation=None):
    section = lib["reports"].section(lib["report_id"], section_id)
    lib["reports"].save_section_draft(
        section["id"], section["step_id"], "valid", draft if draft is not None else section["draft"],
        validation if validation is not None else section["validation"], section["word_count"],
    )


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
    for flagged in phrasing.flagged_sentences(section_id, [claim], contracts._phrasebank_text(), "en"):
        lib["reports"].save_phrase_repair(lib["report_id"], section_id, flagged["sentence_id"],
                                          flagged["text"], flagged["text"], "unframed_exception")
    return claim


def _link(lib, key="IV.1", *, passage=True, source_id=None, anchor=None, match="exact"):
    return {"claim_key": key, "passage_id": lib["section_passage"] if passage else None,
            "cell_id": None if passage else lib["cell_id"],
            "source_version_id": source_id or lib["source_id"], "step_input_id": lib["report_input_id"],
            "anchor_text": anchor if anchor is not None else "selected-section evidence", "anchor_match": match}


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
    lib["reports"].save_phrase_repair(lib["report_id"], "IV", "III.1#1", "A duplicate key.",
                                      "A duplicate key.", "unframed_exception")

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
    lib["reports"].save_phrase_repair(lib["report_id"], "I", "I.1#1",
                                      "Resource allocation is considered below.",
                                      "Resource allocation is considered below.", "unframed_exception")

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
    numbers = copy.deepcopy(section["validation"]["numbers"])
    numbers["corpus"]["found"] = 9
    lib["reports"].save_section_draft(section["id"], None, "valid", section["draft"],
                                      {"ok": True, "issues": [], "numbers": numbers}, 10)

    issues = _issues(lib)

    assert {issue["rule"] for issue in issues} == {"corpus_count_mismatch"}
    assert issues[0]["section_id"] == "II"


def test_section_word_count_over_budget_is_an_error(report_with_sections):
    lib = report_with_sections
    section = lib["reports"].section(lib["report_id"], "VIII")
    lib["reports"].save_section_draft(
        section["id"], None, "valid", section["draft"], section["validation"], 700,
    )

    issues = _issues(lib)

    assert {issue["rule"] for issue in issues} == {
        "section_word_count_over_budget", "report_word_count_over_budget",
    }
    assert {issue["section_id"] for issue in issues} == {"VIII", "report"}


@pytest.mark.parametrize("section_id,change,expected", [
    ("II", lambda n: n.pop("corpus"), "corpus_numbers_missing"),
    ("II", lambda n: n.update(kind="limitations"), "corpus_numbers_missing"),
    ("II", lambda n: n["corpus"].update(unique=7), "corpus_count_mismatch"),
    ("VIII", lambda n: n["corpus"].update(included=7), "corpus_count_mismatch"),
    ("II", lambda n: n.update(full_text_ratio=0.5), "corpus_count_mismatch"),
    ("VIII", lambda n: n.update(no_full_text_share=0.5), "corpus_count_mismatch"),
    ("VIII", lambda n: n.update(items=[{}]), "corpus_numbers_missing"),
    ("II", lambda n: n["corpus"].update(found=True), "corpus_numbers_missing"),
    ("VIII", lambda n: n.update(no_full_text_share=float("nan")), "corpus_numbers_missing"),
])
def test_rule7_structured_number_failures(report_with_sections, section_id, change, expected):
    lib = report_with_sections
    section = lib["reports"].section(lib["report_id"], section_id)
    validation = copy.deepcopy(section["validation"])
    change(validation["numbers"])
    _set_section(lib, section_id, validation=validation)
    assert expected in _rules(lib)


def test_rule7_prose_only_and_limitations_drift(report_with_sections):
    lib = report_with_sections
    _set_section(lib, "II", draft={"text": "999 included sources."})
    assert _issues(lib) == []
    _set_section(lib, "VIII", draft={"text": "999 included sources."})
    assert _rules(lib) == {"limitations_text_drift"}


@pytest.mark.parametrize("count,text,expected", [
    ({"numerator_source_ids": ["x", "x"], "denominator_source_ids": ["x"], "column_id": "c"},
     "2 of 1 sources.", "count_members_invalid"),
    ({"numerator_source_ids": ["x"], "denominator_source_ids": ["x"], "column_id": "c"},
     "1 of 1 sources.", "count_member_not_in_snapshot"),
])
def test_rule5_invalid_members(report_with_sections, count, text, expected):
    lib = report_with_sections
    _add_claim(lib, "IV", "IV.1", text, count=count)
    assert expected in _rules(lib)


def test_rule5_matching_count_and_wrong_text(report_with_sections):
    lib = report_with_sections
    snapshot = lib["reports"].snapshot(lib["report_id"])
    count = {"numerator_source_ids": [lib["source_id"]], "denominator_source_ids": [lib["source_id"]],
             "column_id": snapshot["columns"][0]["column_id"]}
    _add_claim(lib, "IV", "IV.1", "1 of 1 sources.", count=count)
    assert "count_number_mismatch" not in _rules(lib)
    _add_claim(lib, "IV", "IV.1", "2 of 1 sources.", count=count)
    assert "count_number_mismatch" in _rules(lib)


@pytest.mark.parametrize("mode,expected", [
    ("depth", "count_depth_mixed"), ("state", "count_value_mixed"),
    ("value", "count_value_mixed"),
])
def test_rule5_snapshot_cells_must_agree(report_with_sections, mode, expected):
    lib = report_with_sections
    snapshot = lib["reports"].snapshot(lib["report_id"])
    other = {**snapshot["cells"][0], "cell_id": "second-cell", "source_version_id": "second-source"}
    snapshot["rows"].append({"source_version_id": "second-source", "reading_depth": "full_text"})
    if mode == "depth":
        other["reading_depth"] = "abstract"
    elif mode == "state":
        other["state"] = "not_found_in_inspected_scope"
    else:
        other["value"] = {"text": "another method"}
    snapshot["cells"].append(other)
    lib["store"].conn.execute("UPDATE report_snapshot SET snapshot_json = ? WHERE report_id = ?",
                              (json.dumps(snapshot), lib["report_id"]))
    count = {"numerator_source_ids": [lib["source_id"], "second-source"],
             "denominator_source_ids": [lib["source_id"], "second-source"],
             "column_id": snapshot["columns"][0]["column_id"]}
    _add_claim(lib, "IV", "IV.1", "2 of 2 sources.", count=count)
    assert expected in _rules(lib)


@pytest.mark.parametrize("field,value", [
    ("count_json", "{}"), ("count_json", "[]"), ("count_json", '{"numerator_source_ids":[1]}'),
    ("count_json", "{"), ("equation_origin_json", "{}"), ("equation_origin_json", "[]"),
    ("equation_origin_json", '{"passage_id":3,"text_source":"ocr"}'), ("equation_origin_json", "{"),
])
def test_stored_claim_json_malformed_is_an_issue(report_with_sections, field, value):
    lib = report_with_sections
    lib["store"].conn.execute(f"UPDATE report_claims SET {field} = ? WHERE claim_key = 'III.1'", (value,))
    assert "stored_record_malformed" in _rules(lib)


@pytest.mark.parametrize("text,blocked", [
    ("A research gap remains.", True), ("ARAŞTIRMA BOŞLUĞU vardır.", True),
    ("Boşluğu inceledik.", True), ("The band gap is measured.", False),
    ("The band-gap is measured.", False), ("The energy-gap is measured.", False),
    ("A research-gap remains.", True),
    ("The first author studied first-order behavior.", False),
    ("The $\\mathrm{gap}$ is measured.", False),
])
def test_rule6_claim_words(report_with_sections, text, blocked):
    lib = report_with_sections
    _add_claim(lib, "IV", "IV.1", text)
    assert ("banned_word" in _rules(lib)) is blocked


@pytest.mark.parametrize("field,draft", [
    ("heading", {"subsections": [{"heading": "Novel methods"}]}),
    ("gap", {"gaps": [{"gap_id": "gap3", "text": "An open problem remains."}]}),
    ("insufficient_evidence", {"insufficient_evidence": [{"reason": "An open question remains."}]}),
])
def test_rule6_draft_fields(report_with_sections, field, draft):
    lib = report_with_sections
    _set_section(lib, "III", draft=draft)
    assert any(issue["rule"] == "banned_word" and field in issue["detail"] for issue in _issues(lib))


def test_rule6_stored_gap_text(report_with_sections):
    lib = report_with_sections
    _gap(lib, "conflicting_evidence")
    lib["store"].conn.execute("UPDATE report_gaps SET text = 'A novel result.' WHERE report_id = ?",
                              (lib["report_id"],))
    assert "banned_word" in _rules(lib)


@pytest.mark.parametrize("mutation,expected", [
    ("foreign", "citation_source_not_in_corpus"),
    ("incomplete", "reference_record_incomplete"),
    ("mismatch", "citation_source_mismatch"),
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
    ("null", "citation_anchor_unmatched"), ("passage", "anchor_not_in_passage"),
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


@pytest.mark.parametrize("text_source", ["ocr", "marker"])
def test_rule11_math_and_origin_failures(report_with_sections, text_source):
    lib = report_with_sections
    _add_claim(lib, "IV", "IV.1", "The value is $x.")
    assert "math_not_well_formed" in _rules(lib)
    _add_claim(lib, "IV", "IV.1", "The value is $$x$$.")
    assert "equation_origin_missing" in _rules(lib)
    origin = {"passage_id": "foreign", "text_source": "text_layer"}
    _add_claim(lib, "IV", "IV.1", "The value is $$x$$.", origin=origin)
    assert {"equation_origin_not_in_input", "equation_origin_without_math"} <= _rules(lib)
    origin["passage_id"] = lib["section_passage"]
    _add_claim(lib, "IV", "IV.1", "The value is $$x$$.", origin=origin, links=[_link(lib)])
    assert "equation_origin_without_math" in _rules(lib)
    math_passage = lib["store"]._insert_passage(lib["source_id"], None, "section", None, None, None,
                                                  None, None, "SYNTHETIC selected-section evidence. $$x$$",
                                                  text_source=text_source)
    payload = lib["store"].step_input_payload(lib["report_input_id"])
    payload["passages"].append({"passage_id": math_passage})
    payload["step_input_id"] = new_id("sti")
    lib["store"].insert_step_input(lib["report_step_id"], lib["reports"].report(lib["report_id"])["research_id"],
                                   lib["reports"].report(lib["report_id"])["run_id"], 1, payload,
                                   "base", "developer", "message", {})
    origin["passage_id"] = math_passage
    origin["text_source"] = text_source
    _add_claim(lib, "IV", "IV.1", "The value is $$x$$.", origin=origin,
               links=[_link(lib) | {"passage_id": math_passage,
                                    "step_input_id": payload["step_input_id"]}])
    assert "equation_text_source_warning" in _rules(lib)
    assert not {issue["rule"] for issue in _issues(lib) if not issue["rule"].endswith("_warning")}


@pytest.mark.parametrize("origin_source,passage_source,warning", [
    ("text_layer", "ocr", True),
    ("ocr", "text_layer", False),
])
def test_rule11_origin_source_must_match_stored_passage(report_with_sections, origin_source,
                                                         passage_source, warning):
    lib = report_with_sections
    math_passage = lib["store"]._insert_passage(lib["source_id"], None, "section", None, None, None,
                                                  None, None, "SYNTHETIC selected-section evidence. $$x$$",
                                                  text_source=passage_source)
    payload = lib["store"].step_input_payload(lib["report_input_id"])
    payload["passages"].append({"passage_id": math_passage})
    payload["step_input_id"] = new_id("sti")
    report = lib["reports"].report(lib["report_id"])
    lib["store"].insert_step_input(lib["report_step_id"], report["research_id"], report["run_id"], 1,
                                   payload, "base", "developer", "message", {})
    _add_claim(lib, "IV", "IV.1", "The value is $$x$$.",
               origin={"passage_id": math_passage, "text_source": origin_source},
               links=[_link(lib) | {"passage_id": math_passage, "step_input_id": payload["step_input_id"]}])
    issues = [issue for issue in _issues(lib) if issue["section_id"] == "IV"]
    assert {issue["rule"] for issue in issues} == (
        {"equation_origin_mismatch", "equation_text_source_warning"} if warning
        else {"equation_origin_mismatch"}
    )
    assert all(issue["detail"].startswith("WARNING:") for issue in issues
               if issue["rule"] == "equation_text_source_warning")


@pytest.mark.parametrize("passages", [None, "x", [{"passage_id": 3}]])
def test_rule11_malformed_input_passages_cannot_supply_equation_origin(report_with_sections, passages):
    lib = report_with_sections
    math_passage = lib["store"]._insert_passage(lib["source_id"], None, "section", None, None, None,
                                                  None, None, "SYNTHETIC selected-section evidence. $$x$$")
    payload = lib["store"].step_input_payload(lib["report_input_id"])
    payload["step_input_id"] = new_id("sti")
    payload["passages"] = passages
    report = lib["reports"].report(lib["report_id"])
    lib["store"].insert_step_input(lib["report_step_id"], report["research_id"], report["run_id"], 1,
                                   payload, "base", "developer", "message", {})
    _add_claim(lib, "IV", "IV.1", "The value is $$x$$.",
               origin={"passage_id": math_passage, "text_source": "text_layer"},
               links=[_link(lib) | {"passage_id": math_passage, "step_input_id": payload["step_input_id"]}])
    assert _rules(lib) == {"equation_origin_not_in_input"}


def test_rule11_other_step_input_cannot_supply_equation_origin(report_with_sections):
    lib = report_with_sections
    math_passage = lib["store"]._insert_passage(lib["source_id"], None, "section", None, None, None,
                                                  None, None, "SYNTHETIC selected-section evidence. $$x$$")
    report = lib["reports"].report(lib["report_id"])
    other_step = lib["store"].step(report["run_id"], "report:other", "model:report_section")
    payload = lib["store"].step_input_payload(lib["report_input_id"])
    payload["step_input_id"] = new_id("sti")
    payload["passages"] = [{"passage_id": math_passage}]
    lib["store"].insert_step_input(other_step["id"], report["research_id"], report["run_id"], 0,
                                   payload, "base", "developer", "message", {})
    _add_claim(lib, "IV", "IV.1", "The value is $$x$$.",
               origin={"passage_id": math_passage, "text_source": "text_layer"},
               links=[_link(lib) | {"passage_id": math_passage, "step_input_id": payload["step_input_id"]}])
    assert _rules(lib) == {"equation_origin_not_in_input"}


def _gap(lib, kind, gap_id="gap1", *, claim_keys=None, passage_ids=None, cell_ids=None, origin="model"):
    lib["reports"].save_gaps(lib["report_id"], [{
        "gap_id": gap_id, "kind": kind, "text": "A bounded finding.",
        "basis": {"basis_claim_keys": claim_keys or [], "basis_passage_ids": passage_ids or [],
                  "basis_cell_ids": cell_ids or [], "nearest_match": None},
        "provenance": {"origin": origin},
    }])


def _vi_input(lib):
    snapshot = lib["reports"].snapshot(lib["report_id"])
    column = snapshot["columns"][0]["column_id"]
    snapshot["cells"][0]["state"] = "not_found_in_inspected_scope"
    snapshot["cells"][0]["value"] = None
    for index in (2, 3):
        snapshot["rows"].append({"source_version_id": f"synthetic-{index}", "reading_depth": "full_text"})
        snapshot["cells"].append({**snapshot["cells"][0], "cell_id": f"synthetic-cell-{index}",
                                  "source_version_id": f"synthetic-{index}"})
    lib["store"].conn.execute("UPDATE report_snapshot SET snapshot_json = ? WHERE report_id = ?",
                              (json.dumps(snapshot), lib["report_id"]))
    candidates = report_gaps.generate_corpus_absence_candidates(snapshot, [{"column_id": column}])
    report = lib["reports"].report(lib["report_id"])
    step = lib["store"].step(report["run_id"], "report:VI:synthetic", "model:report_section")
    section = lib["reports"].create_section(lib["report_id"], "VI", 6)
    lib["section_ids"]["VI"] = section
    lib["reports"].save_section_draft(section, step["id"], "valid", {"claims": []},
                                      {"ok": True, "issues": []}, 5)
    payload = {"step_input_id": new_id("sti"), "task_type": "report_section", "scope_revision": 1,
               "skill_package_hash": "sha256:synthetic",
               "question": {"text": "What methods?", "language_hint": "en"},
               "passages": [{"passage_id": lib["section_passage"]}],
               "report_target": {"cells": [snapshot["cells"][0]], "gap_candidates": candidates}}
    lib["store"].insert_step_input(step["id"], report["research_id"], report["run_id"], 0,
                                   payload, "base", "developer", "message", {})
    return snapshot, candidates[0]


def _add_vi_input(lib, payload):
    report = lib["reports"].report(lib["report_id"])
    step_id = lib["reports"].section(lib["report_id"], "VI")["step_id"]
    payload["step_input_id"] = new_id("sti")
    lib["store"].insert_step_input(step_id, report["research_id"], report["run_id"], 1,
                                   payload, "base", "developer", "message", {})


def _insert_raw_step_input(lib, step_id, raw):
    input_id = new_id("sti")
    lib["store"].conn.execute(
        "INSERT INTO step_inputs (id, step_id, research_id, run_id, attempt, task_type,"
        " scope_revision, skill_package_hash, payload_json, base_instructions,"
        " developer_instructions, user_message, output_schema_json, created_at)"
        " SELECT ?, step_id, research_id, run_id, attempt + 1, task_type, scope_revision,"
        " skill_package_hash, ?, base_instructions, developer_instructions, user_message,"
        " output_schema_json, created_at FROM step_inputs WHERE id = ?",
        (input_id, raw, lib["store"].last_step_input(step_id)["id"]),
    )
    return input_id


@pytest.mark.parametrize("field,value", [
    ("report_target", None), ("cells", None), ("gap_candidates", None), ("passages", "x"),
    ("cells", [{"cell_id": 3}]), ("gap_candidates", [{"gap_id": 3}]),
    ("passages", [{"passage_id": 3}]),
])
@pytest.mark.parametrize("kind", ["stated_limitation", "corpus_absence"])
def test_rule9_malformed_vi_input_fails_closed(report_with_sections, field, value, kind):
    lib = report_with_sections
    _, candidate = _vi_input(lib)
    step_id = lib["reports"].section(lib["report_id"], "VI")["step_id"]
    input_id = lib["store"].last_step_input(step_id)["id"]
    payload = lib["store"].step_input_payload(input_id)
    if field in {"cells", "gap_candidates"}:
        payload["report_target"][field] = value
    else:
        payload[field] = value
    _add_vi_input(lib, payload)
    if kind == "stated_limitation":
        _gap(lib, kind, cell_ids=[lib["cell_id"]])
    else:
        _gap(lib, kind, candidate["gap_id"], cell_ids=candidate["basis_cell_ids"], origin="code")
    if kind == "corpus_absence":
        expected = {"gap_absence_basis_invalid"} if field in {"report_target", "gap_candidates"} else set()
    else:
        expected = {"gap_basis_missing"} if field in {"report_target", "cells", "passages"} else set()
    assert _rules(lib) == expected


def test_rule9_stated_limitation_and_absence_pass(report_with_sections):
    lib = report_with_sections
    snapshot, candidate = _vi_input(lib)
    _gap(lib, "stated_limitation", cell_ids=[lib["cell_id"]])
    assert _issues(lib) == []
    _gap(lib, "corpus_absence", candidate["gap_id"], cell_ids=candidate["basis_cell_ids"], origin="code")
    assert _issues(lib) == []


def test_rule9_missing_foreign_and_absence_mismatch(report_with_sections):
    lib = report_with_sections
    snapshot, candidate = _vi_input(lib)
    _gap(lib, "stated_limitation")
    assert "gap_basis_missing" in _rules(lib)
    _gap(lib, "stated_limitation", cell_ids=["foreign"])
    assert "gap_basis_foreign" in _rules(lib)
    _gap(lib, "corpus_absence", candidate["gap_id"], cell_ids=candidate["basis_cell_ids"], origin="code")
    snapshot["cells"].append({**snapshot["cells"][0], "cell_id": "fourth", "state": "value"})
    lib["store"].conn.execute("UPDATE report_snapshot SET snapshot_json = ? WHERE report_id = ?",
                              (json.dumps(snapshot), lib["report_id"]))
    assert "gap_absence_basis_invalid" in _rules(lib)


def test_rule9_absence_requires_code_candidate_and_unique_ids(report_with_sections):
    lib = report_with_sections
    _, candidate = _vi_input(lib)
    _gap(lib, "corpus_absence", candidate["gap_id"], cell_ids=candidate["basis_cell_ids"], origin="model")
    assert "gap_absence_basis_invalid" in _rules(lib)
    repeated = candidate["basis_cell_ids"] + [candidate["basis_cell_ids"][0]]
    _gap(lib, "corpus_absence", candidate["gap_id"], cell_ids=repeated, origin="code")
    assert "gap_absence_basis_invalid" in _rules(lib)
    _gap(lib, "corpus_absence", "other-id", cell_ids=candidate["basis_cell_ids"], origin="code")
    assert "gap_absence_basis_invalid" in _rules(lib)


def test_rule9_kind_and_missing_vi_input(report_with_sections):
    lib = report_with_sections
    _gap(lib, "stated_limitation", cell_ids=[lib["cell_id"]])
    assert "gap_basis_missing" in _rules(lib)
    _gap(lib, "other_kind", cell_ids=[lib["cell_id"]])
    assert "gap_kind_unknown" in _rules(lib)


@pytest.mark.parametrize("case", ["foreign_source_passage", "other_column_cell",
                                  "omitted_passage", "omitted_cell"])
def test_rule9_foreign_passage_and_column(report_with_sections, case):
    lib = report_with_sections
    snapshot, _ = _vi_input(lib)
    step_id = lib["reports"].section(lib["report_id"], "VI")["step_id"]
    payload = lib["store"].step_input_payload(lib["store"].last_step_input(step_id)["id"])
    if case in {"foreign_source_passage", "omitted_passage"}:
        source = (lib["store"].create_upload_source("SYNTHETIC other work")
                  if case == "foreign_source_passage" else lib["source_id"])
        passage = lib["store"]._insert_passage(source, None, "section", None, None, None,
                                                None, None, "A recorded limitation.")
        if case == "foreign_source_passage":
            payload["passages"].append({"passage_id": passage})
        _gap(lib, "stated_limitation", passage_ids=[passage])
    else:
        if case == "other_column_cell":
            snapshot["columns"].append({**snapshot["columns"][0], "column_id": "other-column"})
            cell_id = "other-column-cell"
            snapshot["cells"].append({**snapshot["cells"][0], "cell_id": cell_id,
                                      "column_id": "other-column"})
            payload["report_target"]["cells"].append(snapshot["cells"][-1])
        else:
            cell_id = snapshot["cells"][1]["cell_id"]
        lib["store"].conn.execute("UPDATE report_snapshot SET snapshot_json = ? WHERE report_id = ?",
                                  (json.dumps(snapshot), lib["report_id"]))
        _gap(lib, "stated_limitation", cell_ids=[cell_id])
    _add_vi_input(lib, payload)
    assert _rules(lib) == {"gap_basis_foreign"}


def test_rule9_vii_refs_and_future_work_cell(report_with_sections):
    lib = report_with_sections
    _add_claim(lib, "VII", "VII.1", "A tentative direction.", support_type="analyst_inference")
    assert {"vii_claim_without_basis", "vii_inference_without_gap"} <= _rules(lib)
    _add_claim(lib, "VII", "VII.1", "A tentative direction.", support_type="source_stated",
               links=[_link(lib, key="VII.1", passage=False)])
    assert "vii_claim_without_basis" not in _rules(lib)
    _add_claim(lib, "VII", "VII.1", "A tentative direction.", support_type="source_stated",
               gap_refs=["unknown"], links=[_link(lib, key="VII.1", passage=False)])
    assert "gap_ref_unknown" in _rules(lib)


@pytest.mark.parametrize("field,value", [
    ("basis_json", "{}"), ("basis_json", "[]"),
    ("basis_json", '{"basis_claim_keys":[1],"basis_passage_ids":[],"basis_cell_ids":[]}'),
    ("basis_json", "{"), ("provenance_json", "{}"), ("provenance_json", "[]"),
    ("provenance_json", '{"origin":3}'), ("provenance_json", "{"),
])
def test_stored_gap_json_malformed_is_an_issue(report_with_sections, field, value):
    lib = report_with_sections
    _gap(lib, "conflicting_evidence", claim_keys=["V.1"])
    lib["store"].conn.execute(f"UPDATE report_gaps SET {field} = ? WHERE report_id = ?",
                              (value, lib["report_id"]))
    assert sum(issue["rule"] == "stored_record_malformed" for issue in _issues(lib)) == 1


def test_rule13_conflict_gap_needs_v_claim(report_with_sections):
    lib = report_with_sections
    _gap(lib, "conflicting_evidence", claim_keys=["V.1"])
    assert "conflict_gap_without_v_claim" in _rules(lib)
    _add_claim(lib, "V", "V.1", "A recorded comparison.")
    assert "conflict_gap_without_v_claim" not in _rules(lib)


def test_rule14_exception_must_match_current_sentence(report_with_sections):
    lib = report_with_sections
    conn = lib["store"].conn
    conn.execute("DELETE FROM report_phrase_repairs WHERE section_id = 'III'")
    assert "unframed_sentence_not_recorded" in _rules(lib)
    for before, after, outcome, passing in (
        ("different", "Resource allocation assigns capacity.", "unframed_exception", True),
        ("Resource allocation assigns capacity.", "refused", "reverted_exception", True),
        ("different", "also different", "unframed_exception", False),
        ("Resource allocation assigns capacity.", "same", "kept", False),
    ):
        lib["reports"].save_phrase_repair(lib["report_id"], "III", "III.1#1", before, after, outcome)
        assert ("unframed_sentence_not_recorded" not in _rules(lib)) is passing


@pytest.mark.parametrize("question", [None, "x", {}, {"text": 1},
                                     {"text": "x", "language_hint": 1}])
def test_rule14_malformed_stored_question_is_blocking(report_with_sections, question):
    lib = report_with_sections
    payload = lib["store"].step_input_payload(lib["report_input_id"])
    payload["question"] = question
    payload["step_input_id"] = new_id("sti")
    report = lib["reports"].report(lib["report_id"])
    lib["store"].insert_step_input(lib["report_step_id"], report["research_id"], report["run_id"], 1,
                                   payload, "base", "developer", "message", {})
    issues = [issue for issue in _issues(lib) if issue["section_id"] == "III"]
    assert len(issues) == 1
    assert issues[0]["rule"] == "stored_record_malformed"
    assert "step_inputs" in issues[0]["detail"] and "question" in issues[0]["detail"]


def test_rule14_own_work_and_plural_sources(report_with_sections):
    lib = report_with_sections
    _add_claim(lib, "IV", "IV.1", "This study cites previous studies.", links=[_link(lib)])
    assert {"own_work_phrase_in_claim", "plural_sources_for_one_source"} <= _rules(lib)
    other_source = lib["store"].create_upload_source("SYNTHETIC second method study")
    other_passage = lib["store"]._insert_passage(other_source, None, "section", None, None, None,
                                                  None, None, "SYNTHETIC second evidence.")
    snapshot = lib["reports"].snapshot(lib["report_id"])
    snapshot["rows"].append({"source_version_id": other_source, "reading_depth": "selected_sections"})
    lib["store"].conn.execute("UPDATE report_snapshot SET snapshot_json = ? WHERE report_id = ?",
                              (json.dumps(snapshot), lib["report_id"]))
    second_link = _link(lib) | {"passage_id": other_passage, "source_version_id": other_source,
                                "anchor_text": "second evidence"}
    _add_claim(lib, "IV", "IV.1", "Previous studies report a method.", links=[_link(lib), second_link])
    assert "plural_sources_for_one_source" not in _rules(lib)


@pytest.mark.parametrize("field", ["subsections", "gaps", "insufficient_evidence"])
@pytest.mark.parametrize("value", [None, "not a list", ["not an object"]])
def test_malformed_draft_list_is_one_blocking_issue(report_with_sections, field, value):
    lib = report_with_sections
    _set_section(lib, "III", draft={"claims": [], field: value})
    issues = [issue for issue in _issues(lib) if issue["rule"] == "stored_record_malformed"]
    assert len(issues) == 1
    assert issues[0]["section_id"] == "III"
    assert "report_sections draft_json" in issues[0]["detail"]
    assert field in issues[0]["detail"]


@pytest.mark.parametrize("entry", [{"reason": None}, {}, {"reason": 3}])
def test_malformed_insufficient_evidence_item_is_blocking_and_does_not_raise(report_with_sections, entry):
    lib = report_with_sections
    _set_section(lib, "III", draft={"claims": [], "insufficient_evidence": [entry]})
    issues = [issue for issue in _issues(lib) if issue["rule"] == "stored_record_malformed"]
    assert issues and all(issue["section_id"] == "III" for issue in issues)


@pytest.mark.parametrize("raw", ["{", "[]"])
def test_malformed_vi_payload_is_recorded_for_gap_check(report_with_sections, raw):
    lib = report_with_sections
    _, candidate = _vi_input(lib)
    step_id = lib["reports"].section(lib["report_id"], "VI")["step_id"]
    _insert_raw_step_input(lib, step_id, raw)
    _gap(lib, "corpus_absence", candidate["gap_id"], cell_ids=candidate["basis_cell_ids"], origin="code")
    issues = [issue for issue in _issues(lib) if issue["section_id"] == "VI"]
    assert {issue["rule"] for issue in issues} == {"stored_record_malformed", "gap_absence_basis_invalid"}
    assert sum("step_inputs payload_json" in issue["detail"] for issue in issues) == 1


@pytest.mark.parametrize("raw", ["{", "[]"])
def test_malformed_equation_payload_is_recorded(report_with_sections, raw):
    lib = report_with_sections
    math_passage = lib["store"]._insert_passage(lib["source_id"], None, "section", None, None, None,
                                                  None, None, "SYNTHETIC math evidence. $$x$$")
    payload = lib["store"].step_input_payload(lib["report_input_id"])
    payload["passages"].append({"passage_id": math_passage})
    payload["step_input_id"] = new_id("sti")
    report = lib["reports"].report(lib["report_id"])
    lib["store"].insert_step_input(lib["report_step_id"], report["research_id"], report["run_id"], 1,
                                   payload, "base", "developer", "message", {})
    _add_claim(lib, "IV", "IV.1", "The value is $$x$$.",
               origin={"passage_id": math_passage, "text_source": "text_layer"},
               links=[_link(lib) | {"passage_id": math_passage,
                                    "anchor_text": "math evidence", "step_input_id": payload["step_input_id"]}])
    _insert_raw_step_input(lib, lib["report_step_id"], raw)
    issues = [issue for issue in _issues(lib) if issue["section_id"] == "IV"]
    assert sum(issue["rule"] == "stored_record_malformed" and "step_inputs payload_json" in issue["detail"]
               for issue in issues) == 1


@pytest.mark.parametrize("raw", ["{", "[]"])
def test_malformed_language_payload_is_recorded(report_with_sections, raw):
    lib = report_with_sections
    _insert_raw_step_input(lib, lib["report_step_id"], raw)
    issues = [issue for issue in _issues(lib) if issue["section_id"] == "III"
              and issue["rule"] == "stored_record_malformed"]
    assert len(issues) == 1
    assert "step_inputs payload_json" in issues[0]["detail"]


def test_equation_link_to_older_malformed_input_is_recorded(report_with_sections):
    lib = report_with_sections
    raw_id = _insert_raw_step_input(lib, lib["report_step_id"], "[]")
    payload = lib["store"].step_input_payload(lib["report_input_id"])
    payload["step_input_id"] = new_id("sti")
    report = lib["reports"].report(lib["report_id"])
    lib["store"].insert_step_input(lib["report_step_id"], report["research_id"], report["run_id"], 3,
                                   payload, "base", "developer", "message", {})
    math_passage = lib["store"]._insert_passage(lib["source_id"], None, "section", None, None, None,
                                                  None, None, "SYNTHETIC math evidence. $$x$$")
    _add_claim(lib, "IV", "IV.1", "The value is $$x$$.",
               origin={"passage_id": math_passage, "text_source": "text_layer"},
               links=[_link(lib) | {"passage_id": math_passage,
                                    "anchor_text": "math evidence", "step_input_id": raw_id}])
    issues = [issue for issue in _issues(lib) if issue["section_id"] == "IV"]
    assert sum(issue["rule"] == "stored_record_malformed" and "step_inputs payload_json" in issue["detail"]
               for issue in issues) == 1


def test_equation_origin_must_be_cited_by_its_claim(report_with_sections):
    lib = report_with_sections
    math_passage = lib["store"]._insert_passage(lib["source_id"], None, "section", None, None, None,
                                                  None, None, "SYNTHETIC math evidence. $$x$$")
    payload = lib["store"].step_input_payload(lib["report_input_id"])
    payload["passages"].append({"passage_id": math_passage})
    payload["step_input_id"] = new_id("sti")
    report = lib["reports"].report(lib["report_id"])
    lib["store"].insert_step_input(lib["report_step_id"], report["research_id"], report["run_id"], 1,
                                   payload, "base", "developer", "message", {})
    _add_claim(lib, "IV", "IV.1", "The value is $$x$$.",
               origin={"passage_id": math_passage, "text_source": "text_layer"},
               links=[_link(lib) | {"step_input_id": payload["step_input_id"]}])
    assert {issue["rule"] for issue in _issues(lib) if issue["section_id"] == "IV"} == {
        "equation_origin_not_cited"}


def test_absence_candidate_does_not_require_vi_cells_or_passages(report_with_sections):
    lib = report_with_sections
    _, candidate = _vi_input(lib)
    step_id = lib["reports"].section(lib["report_id"], "VI")["step_id"]
    payload = lib["store"].step_input_payload(lib["store"].last_step_input(step_id)["id"])
    del payload["passages"]
    del payload["report_target"]["cells"]
    _add_vi_input(lib, payload)
    _gap(lib, "corpus_absence", candidate["gap_id"], cell_ids=candidate["basis_cell_ids"], origin="code")
    assert _issues(lib) == []
    _gap(lib, "stated_limitation", cell_ids=[lib["cell_id"]])
    assert _rules(lib) == {"gap_basis_missing"}
