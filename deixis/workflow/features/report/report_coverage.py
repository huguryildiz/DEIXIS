"""Which of a report's sub-questions the synthesis begins without evidence for (P12).

Pure: a function of the report's frozen snapshot and its frozen plan. No database, no clock, no model.

The plan binds each sub-question the question asks for — a comparison, a condition, a criterion — to one column of
the Evidence table (`axes`). A column's cells are what the report may stand on for that sub-question, so before the
sections are written this module records, per sub-question, how many rows carry a located quote for it, how deep each
of those rows was read, and which sub-questions have no such row at all. The record is evidence for the reader of the
run, never an input to a model step: nothing here decides what a section may cite.

A column states a finding for a row only when a cell of it holds a value with a linked quote. A cell whose source had
no text (`inaccessible`), a value nobody located in a passage (`not_verified`), a column the row's reading did not
settle (`unknown`) and a column that does not apply to it (`not_applicable`) are each kept apart: they say the
sub-question is open for that row, not answered.
"""

from __future__ import annotations

from typing import Any

from deixis.workflow.features.report.report_snapshot import evidence_row_ids

RULE = "report_coverage_v1"
# A cell state that answers its sub-question for one row, as long as a quote was located in a passage.
ANSWERING = frozenset({"value"})
# What a cell says about its sub-question when it does not answer it. `not_reported` and `not_found_in_inspected_scope`
# are the readings that looked and found nothing; the others never got that far.
OPEN_STATES = ("unknown", "not_reported", "not_found_in_inspected_scope", "not_verified", "inaccessible",
               "not_applicable")
DEPTHS = ("metadata", "abstract", "selected_sections", "full_text")


def _answered(cell: dict[str, Any]) -> bool:
    """Whether this cell answers its sub-question for its row: a value with at least one located quote."""
    return cell.get("state") in ANSWERING and bool(cell.get("evidence"))


def axis_cells(snapshot: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    """One record per stored cell that a sub-question of the plan rests on, in the plan's order then the row's.

    The pair a sub-question and one row make: which column answers that sub-question, what the row's cell of it says,
    how deep it was read, and whether it answers the sub-question at all. This is the one reading of the plan against
    the snapshot: the coverage record counts these by sub-question and the file-request list reads the same records by
    row (`report_file_asks`), so neither surface has a rule of its own about what an open sub-question is.

    Only the rows the report may stand on are read: a row whose own table cells failed is named in the basis note and
    is not evidence, so it neither answers a sub-question nor counts against one. A row whose cell of that column was
    never stored makes no record, because there is nothing stored to point at.
    """
    rows = evidence_row_ids(snapshot)
    order = {source_id: index for index, source_id in enumerate(rows)}
    cells_by_column: dict[str, list[dict[str, Any]]] = {}
    for cell in snapshot.get("cells") or []:
        if cell["source_version_id"] in order:
            cells_by_column.setdefault(cell["column_id"], []).append(cell)
    names = {column["column_id"]: column.get("name") for column in snapshot.get("columns") or []}
    records = []
    for axis in plan.get("axes") or []:
        column_id = axis["column_id"]
        for cell in sorted(cells_by_column.get(column_id, []), key=lambda item: order[item["source_version_id"]]):
            records.append({
                "axis_id": axis["axis_id"], "label": axis["label"], "column_id": column_id,
                "column_name": names.get(column_id), "column_missing": column_id not in names,
                "source_version_id": cell["source_version_id"], "cell_id": cell.get("cell_id"),
                "state": cell.get("state"), "reading_depth": cell.get("reading_depth"),
                "answered": _answered(cell),
            })
    return records


def open_axes_by_row(snapshot: dict[str, Any], plan: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Per row, the sub-questions its own cell leaves open, in the plan's order.

    A row is listed only for a sub-question whose cell it stores and whose cell does not answer it. What the caller
    does with that is the caller's: this says which question stays open on which row, and nothing about files.
    """
    open_rows: dict[str, list[dict[str, Any]]] = {}
    for index, record in enumerate(axis_cells(snapshot, plan)):
        if not record["answered"]:
            open_rows.setdefault(record["source_version_id"], []).append(record | {"axis_order": index})
    return open_rows


def axis_coverage(snapshot: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    """One record per sub-question of the plan, in the plan's order.

    `rows_answered` counts the rows whose cell of that column holds a located value; `depths` counts those rows by how
    deep the column was read in them; `states` counts every other row by what its cell says. `column_missing` marks a
    sub-question whose column is not in the snapshot at all, which leaves it without evidence by definition.
    """
    by_axis: dict[str, list[dict[str, Any]]] = {}
    for record in axis_cells(snapshot, plan):
        by_axis.setdefault(record["axis_id"], []).append(record)
    names = {column["column_id"]: column.get("name") for column in snapshot.get("columns") or []}
    records = []
    for axis in plan.get("axes") or []:
        column_id = axis["column_id"]
        cells = by_axis.get(axis["axis_id"], [])
        answered = [cell for cell in cells if cell["answered"]]
        unanswered = [cell for cell in cells if not cell["answered"]]
        records.append({
            "axis_id": axis["axis_id"], "label": axis["label"], "column_id": column_id,
            "column_name": names.get(column_id), "column_missing": column_id not in names,
            "rows": len(cells), "rows_answered": len(answered),
            "depths": {depth: sum(cell["reading_depth"] == depth for cell in answered)
                       for depth in DEPTHS if any(cell["reading_depth"] == depth for cell in answered)},
            "states": {state: sum(cell["state"] == state for cell in unanswered)
                       for state in OPEN_STATES if any(cell["state"] == state for cell in unanswered)},
        })
    return records


def coverage(snapshot: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """What the synthesis of this report starts with: its sub-questions, and the ones without evidence.

    `without_evidence` is the axis ids no row answered — the sub-questions the sections are written without. A plan
    with no axis records none, and says so through `axes: 0`.
    """
    axes = axis_coverage(snapshot, plan)
    return {"rule": RULE, "axes": len(axes), "sub_questions": axes,
            "without_evidence": [axis["axis_id"] for axis in axes if not axis["rows_answered"]],
            "research_questions": [question["rq_id"] for question in plan.get("research_questions") or []]}
