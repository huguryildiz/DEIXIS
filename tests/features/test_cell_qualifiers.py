"""What a cell says its finding was measured against, and where that travels.

Three fields ride with a cell answer: `compared_method`, `condition` and `direction`. Synthetic records and model
output throughout; these show the rules and the surfaces, not extraction quality.
"""

import asyncio
import copy
import json
import sqlite3

import pytest

from deixis.domain import contracts
from deixis.exports import table as table_export
from deixis.storage import db
from deixis.workflow.features.report import report_evidence_view, report_export_text, report_snapshot
from deixis.workflow.features.tables.tables import check_qualifiers
from fakes import valid_response
from old_library import master, old_library
from test_evidence_tables import VALUE, cell, decide, edit, make_lib, step_input
from test_table_abstract_rows import execute, make_library, new_table, version
from test_table_extraction import cell_draft, cell_step_input

MEASURED = {"compared_method": "SYNTHETIC VBF", "condition": "10 nodes, 1 km depth", "direction": "lower"}
NUMBER_COLUMN = {"answer_format": "number_unit"}


def written(lib, sv=None, **fields):
    """One model answer for the packet-size column, with whatever qualifiers the case gives it."""
    sv = sv or lib.published
    return lib.tables.save_model_output(
        lib.rid, lib.tid, lib.cid, sv, column_revision=1, state=fields.pop("state", "value"),
        value=fields.pop("value", VALUE), note=None, reading_depth=fields.pop("reading_depth", "abstract"),
        output_status="structurally_valid",
        links=fields.pop("links", [{"passage_id": lib.abstracts[sv], "source_version_id": sv,
                                    "anchor_text": "128 bytes", "anchor_match": "exact"}]),
        run_id=lib.run_id, step_id=lib.step_id, step_input_id=step_input(lib), model_connection="fake",
        resolved_model="fake-model", scope_revision=1, cell_version_at_request=fields.pop("at_version", None),
        recheck=fields.pop("recheck", False), **fields)


def stored(lib, revision_id):
    return dict(lib.conn.execute("SELECT compared_method, condition, direction FROM cell_revisions WHERE id = ?",
                                 (revision_id,)).fetchone())


# ---- the contract -----------------------------------------------------------------------------
def draft_with(**fields):
    si = cell_step_input()
    draft = cell_draft(si)
    draft["cells"][0].update(fields)
    return si, draft


def test_a_value_may_say_what_it_was_measured_against():
    si, draft = draft_with(**MEASURED)
    assert contracts.validate_model_output(si, draft).ok


@pytest.mark.parametrize("index, fields, code", [
    # A cell that found nothing states no finding, so it qualifies none.
    (3, MEASURED, "qualifier_outside_a_value"),
    (2, {"condition": "10 nodes"}, "qualifier_outside_a_value"),
    # A direction is a direction against something.
    (0, {"direction": "lower"}, "direction_without_compared_method"),
])
def test_a_qualifier_outside_its_rules_is_invalid_model_output(index, fields, code):
    si = cell_step_input()
    draft = cell_draft(si)
    draft["cells"][index].update(fields)
    assert contracts.validate_model_output(si, draft).codes() == [code]


@pytest.mark.parametrize("fields", [{"compared_method": "  "}, {"condition": "\t"}])
def test_a_blank_qualifier_is_reported_not_quietly_dropped(fields):
    si, draft = draft_with(**fields)
    assert contracts.validate_model_output(si, draft).codes() == ["blank_qualifier"]


@pytest.mark.parametrize("index, fields, code", [
    (0, {"compared_method": "  "}, "blank_qualifier"),
    (3, {"compared_method": "SYNTHETIC VBF"}, "qualifier_outside_a_value"),
    (0, {"direction": "lower"}, "direction_without_compared_method"),
])
def test_one_cells_bad_qualifier_does_not_cost_the_other_cells_of_the_call(index, fields, code):
    """A qualifier problem belongs to its own cell, so the call's other answers are still kept and only that column is
    asked again, as every other per-cell problem is."""
    si = cell_step_input()
    draft = cell_draft(si)
    draft["cells"][index].update(fields)
    salvage = contracts.salvage_cells(si, draft)
    assert salvage is not None, "a single bad qualifier must not fail the whole output"
    assert [item["column_id"] for item in salvage["cells"]] == \
        [c["column_id"] for i, c in enumerate(draft["cells"]) if i != index]
    assert {c["column_id"]: [i["code"] for i in issues] for c, issues in
            [(draft["cells"][index], salvage["bad"][draft["cells"][index]["column_id"]])]} == \
        {draft["cells"][index]["column_id"]: [code]}


def test_an_unknown_direction_is_a_schema_error():
    si, draft = draft_with(compared_method="SYNTHETIC VBF", direction="sideways")
    assert contracts.validate_model_output(si, draft).codes() == ["schema_invalid"]


def test_the_salvage_path_keeps_the_qualifiers_for_the_store_to_judge():
    """`storable_cells` carries them; what drops them is the store's own check, one place for every writer."""
    si, draft = draft_with(**MEASURED)
    kept = contracts.storable_cells(si, draft)
    assert {name: kept[0][name] for name in MEASURED} == MEASURED
    # The same answer with its quotes unlocated becomes a value without linked evidence, which carries none.
    assert check_qualifiers("not_verified", [], **MEASURED) == (None, None, None)
    assert check_qualifiers("value", [], **MEASURED) == (None, None, None)
    # A link the code could not anchor is no basis for a comparison, as it is none for the value.
    assert check_qualifiers("value", [{"passage_id": "psg_x", "anchor_match": None}], **MEASURED) == (None, None, None)
    assert check_qualifiers("value", [{"passage_id": "psg_x", "anchor_match": "exact"}], **MEASURED) == \
        ("SYNTHETIC VBF", "10 nodes, 1 km depth", "lower")


# ---- the writers ------------------------------------------------------------------------------
def test_a_model_fill_stores_them_and_every_cell_surface_reads_them_back(tmp_path):
    lib = make_lib(tmp_path)
    revision = written(lib, **MEASURED)
    assert stored(lib, revision) == MEASURED
    current = cell(lib)["current"]
    assert {name: current[name] for name in MEASURED} == MEASURED


def test_the_library_refuses_a_qualifier_the_store_would_not_write(tmp_path):
    """The rules are a CHECK too, so no writer can get round them by calling the store another way."""
    lib = make_lib(tmp_path)
    cell_id = lib.tables._cell(lib.tid, lib.cid, lib.published, create=True)["id"]
    for fields in ({"state": "unknown", "compared_method": "SYNTHETIC VBF"},
                   {"state": "value", "value_json": "{}", "direction": "lower"},
                   {"state": "value", "value_json": "{}", "compared_method": "x", "direction": "sideways"}):
        names = ", ".join(fields)
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            lib.conn.execute(
                f"INSERT INTO cell_revisions (id, cell_id, kind, author, column_revision, created_at, {names})"
                f" VALUES ('crv_SYNTHETIC', ?, 'human_edit', 'human', 1, 'n', {', '.join('?' * len(fields))})",
                (cell_id, *fields.values()))


def test_accepting_a_proposal_keeps_what_the_proposal_said_it_was_measured_against(tmp_path):
    lib = make_lib(tmp_path)
    written(lib)  # the cell's current value, so the next answer waits as a proposal
    proposal = written(lib, value={"number": 64, "unit": "byte", "as_stated": "64 bytes"}, recheck=True, **MEASURED)
    accepted = decide(lib, proposal, True, 1)
    assert stored(lib, accepted) == MEASURED
    assert cell(lib)["current"]["compared_method"] == "SYNTHETIC VBF"


def test_a_persons_own_value_carries_no_models_qualifier(tmp_path):
    """Even a person's value that keeps the model's quotes is their own; a model's comparison does not ride onto it."""
    lib = make_lib(tmp_path)
    first = written(lib, **MEASURED)
    revision = edit(lib, 1, state="value", value={"number": 256, "unit": "byte"}, keep=first)
    assert stored(lib, revision) == {"compared_method": None, "condition": None, "direction": None}


def test_a_metadata_only_record_produces_no_finding(tmp_path):
    """A record with only a title and authors has no passage, so `_extraction` stops before any call.

    That is the one boundary every cell writer goes through — the reading-time lane, a fill, a recheck and the
    automatic re-read after a PDF arrives — so none of them can read a finding out of a bare record. The table still
    records the row, as a system `inaccessible` cell, so the person sees why it is empty rather than nothing at all.
    """
    lib = make_library(tmp_path)
    bare = lib.store.create_upload_source("C SYNTHETIC metadata only")
    lib.store.add_to_corpus(lib.rid, bare, "user_upload", selection_state="included", selection_origin="user")
    assert lib.store.passages_for(bare) == []

    tid = new_table(lib)
    run = lib.tables.request_fill(lib.rid, tid, None, False, version(lib, tid), None, included_only=True)
    assert execute(lib, run)["status"] == "completed"

    cid = lib.tables.target_columns(lib.rid, tid)[0]["id"]
    current = lib.tables.cell_view(lib.rid, tid, cid, bare)["current"]
    assert (current["kind"], current["author"], current["state"], current["reading_depth"]) == \
        ("system_fill", "system", "inaccessible", "metadata")
    assert (current["compared_method"], current["condition"], current["direction"]) == (None, None, None)

    # No model call was made for it, and no StepInput names it: the step that wrote the cell is the no-text step.
    steps = {row["operation_key"]: row["kind"] for row in lib.conn.execute(
        "SELECT operation_key, kind FROM run_steps WHERE run_id = ?", (run["id"],))}
    assert steps.get(f"no_text:{bare}") == "table_no_text"
    assert not [key for key, kind in steps.items() if kind == "model:cell_extraction" and bare in key]
    sent = [row[0] for row in lib.conn.execute(
        "SELECT payload_json FROM step_inputs WHERE run_id = ?", (run["id"],))]
    assert not [payload for payload in sent if bare in payload]

    # The same boundary on the paths a recheck and the automatic re-read take.
    columns = lib.tables.target_columns(lib.rid, tid)
    scope = lib.store.scope(lib.rid)
    assert asyncio.run(lib.flow._extraction(run, scope, "probe", bare, columns, 24)) is None


# ---- the report and the exports ---------------------------------------------------------------
def test_the_report_snapshot_carries_them_and_names_a_depth_it_narrowed(tmp_path):
    """The snapshot is what a report is written from, so what a finding stands against is in it, and so is the fact
    that a depth in it is the report's bound rather than the cell's own reading."""
    lib = make_lib(tmp_path)
    written(lib, **MEASURED)
    written(lib, sv=lib.preprint, reading_depth="selected_sections")
    snapshot = report_snapshot.build_snapshot(lib.store, lib.rid, lib.tid)
    by_source = {item["source_version_id"]: item for item in snapshot["cells"]}
    assert len(by_source) == 2, snapshot["cells"]
    assert {name: by_source[lib.published][name] for name in MEASURED} == MEASURED
    assert by_source[lib.published]["depth_narrowed"] is False
    assert by_source[lib.preprint]["compared_method"] is None

    # A row the answer bound to its abstract alone gives its abstract: a cell that read pages keeps its value, and
    # the narrowing is recorded so no surface reads it as an abstract-only cell.
    answer_input = {"items": [
        {"source_version_id": lib.preprint, "route": "abstract", "abstract_ids": [lib.abstracts[lib.preprint]]},
        # Bound to no passage at all, so the quotes this row's cell cites fall outside what the answer read.
        {"source_version_id": lib.published, "route": "abstract", "abstract_ids": []},
    ]}
    view = report_evidence_view.build(lib.store, lib.rid, lib.tid, answer_input, lib.run_id)
    narrowed = next(item for item in view["cells"] if item["source_version_id"] == lib.preprint)
    assert narrowed["reading_depth"] == "abstract" and narrowed["depth_narrowed"] is True

    # A cell whose quotes fall outside what the answer bound keeps its value for the person but counts unverified,
    # and its comparison goes with the quotes it rested on.
    cut = next(item for item in view["cells"] if item["source_version_id"] == lib.published)
    assert cut["state"] == "not_verified"
    assert (cut["compared_method"], cut["condition"], cut["direction"]) == (None, None, None)


def test_an_old_snapshot_without_the_fields_still_builds_a_report_input(tmp_path):
    """A report continued from a snapshot frozen before the fields existed reads them as absent, never as an error."""
    si = cell_step_input()
    old_cell = {"cell_id": "cel_SYNTHETIC", "cell_revision_id": "crv_SYNTHETIC", "column_id": "col_SYNMETHOD1",
                "source_version_id": "srv_SYNA1pub01", "state": "value", "value": {"text": "x"},
                "reading_depth": "abstract", "evidence": []}
    target = {"report_id": "rep_SYNTHETIC", "section_id": "IV", "columns": [], "plan": None, "cells": [old_cell],
              "gap_candidates": [], "prior_summaries": [], "review_scope": None}
    payload = copy.deepcopy(si)
    payload.update(task_type="report_section", output_schema_versions=["deixis.report_section_draft.v3"],
                   report_target=target)
    payload.pop("extraction_target")
    assert [i.code for i in contracts.check_step_input(payload) if i.path.startswith("/report_target/cells")] == []


@pytest.mark.parametrize("tr", [False, True])
def test_the_report_writes_the_comparison_beside_the_value(tr):
    value = {"state": "value", "value": {"number": 128, "unit": "byte", "as_stated": None}} | MEASURED
    text = report_export_text.cell_text(value, NUMBER_COLUMN, tr, str)
    assert "128" in text and ("SYNTHETIC VBF" in text) and "10 nodes, 1 km depth" in text
    # Without a direction the comparison is still named, so the reader is not told a way it does not have.
    plain = report_export_text.cell_text(value | {"direction": None}, NUMBER_COLUMN, tr, str)
    assert "SYNTHETIC VBF" in plain and ("lower" not in plain and "daha düşük" not in plain)
    assert report_export_text.comparison_text({"compared_method": None, "condition": None, "direction": None}, tr) == ""


EMPTY = {"state": "not_found_in_inspected_scope", "reading_depth": "abstract", "depth_narrowed": False}


@pytest.mark.parametrize("cell_fields, column, abstract_wording", [
    (EMPTY, NUMBER_COLUMN, True),
    # A column that asks for no measurement says nothing about a measurement.
    (EMPTY, {"answer_format": "text"}, False),
    # The cell read more than an abstract, so the words would be false.
    (EMPTY | {"reading_depth": "selected_sections"}, NUMBER_COLUMN, False),
    # The depth is the report's own narrowing, not the cell's: the cell did look further.
    (EMPTY | {"depth_narrowed": True}, NUMBER_COLUMN, False),
    # A record frozen before the field existed says neither way, and may already have narrowed a depth.
    ({"state": "not_found_in_inspected_scope", "reading_depth": "abstract"}, NUMBER_COLUMN, False),
    (EMPTY | {"state": "unknown"}, NUMBER_COLUMN, False),
])
def test_a_measurement_the_abstract_does_not_state_says_so_in_those_words(cell_fields, column, abstract_wording):
    words = "not stated in the abstract that was read"
    assert (report_export_text.empty_state_text(cell_fields, column, False) == words) is abstract_wording
    assert (report_export_text.empty_state_text(cell_fields, column, True) == "okunan özette belirtilmemiş") is abstract_wording
    # The table's own export writes the same choice, in its own capitalisation.
    exported = table_export._cell(table_export.translator("en"), "en", column, {"current": cell_fields})
    assert (exported.state == "Not stated in the abstract that was read") is abstract_wording


def test_the_table_export_writes_the_comparison_in_its_own_field(tmp_path):
    lib = make_lib(tmp_path)
    written(lib, **MEASURED)
    view = lib.tables.table_view(lib.rid, lib.tid)
    header, names, data = table_export.rows(view, [], language="en", style="apa")
    index = [row["source_version_id"] for row in view["rows"]].index(lib.published)
    assert data[index][1][0].comparison == "lower than SYNTHETIC VBF; 10 nodes, 1 km depth"
    assert "{name} — comparison" in table_export.PER_COLUMN


# ---- the library upgrade ----------------------------------------------------------------------
def test_an_upgraded_library_holds_the_three_columns_and_their_check(tmp_path):
    conn = old_library(tmp_path / "old.sqlite", 16)
    assert db.migrate(conn) == list(range(17, db.schema_version() + 1))
    columns = {row[1] for row in conn.execute("PRAGMA table_info(cell_revisions)")}
    assert {"compared_method", "condition", "direction"} <= columns
    fresh = db.connect(tmp_path / "fresh.sqlite")
    db.migrate(fresh)
    assert master(conn) == master(fresh)


# ---- the model's own instructions -------------------------------------------------------------
def test_the_fake_answers_a_measurement_column_with_a_comparison():
    si = cell_step_input()
    draft = json.loads(valid_response(si))
    by_id = {c["column_id"]: c for c in draft["cells"]}
    number = next(c for c in si["extraction_target"]["columns"] if c["answer_format"] == "number_unit")
    other = next(c for c in si["extraction_target"]["columns"] if c["answer_format"] == "text")
    assert by_id[number["column_id"]]["compared_method"] and by_id[number["column_id"]]["direction"] == "lower"
    assert by_id[other["column_id"]]["compared_method"] is None
    assert contracts.validate_model_output(si, draft).ok


def test_the_cell_instructions_name_the_three_fields():
    text = (db.SCHEMA.parent.parent / "methods/deixis-research/references/evidence-table.md").read_text(encoding="utf-8")
    for name in ("compared_method", "condition", "direction"):
        assert f"`{name}`" in text
    assert "not stated in\n   the abstract that was read" in text


def test_the_report_instructions_tell_two_findings_apart():
    text = (db.SCHEMA.parent.parent / "methods/deixis-research/references/report.md").read_text(encoding="utf-8")
    assert "`condition`" in text and "`direction`" in text and "two findings" in text
