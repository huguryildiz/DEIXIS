"""Synthetic table readiness and immutable report evidence snapshots."""

import json

import pytest

from deixis.storage import db
from deixis.storage.db import new_id, transaction
from deixis.workflow.report.snapshot import build_snapshot
from deixis.workflow.report.store import ReportStore
from deixis.workflow.store import Store
from deixis.workflow.tables import TableStore, report_ready


COLUMN = {"name": "Packet size", "instruction": "Record packet size", "answer_format": "text",
          "options": None, "allow_multiple": False, "unit_hint": None}


@pytest.fixture
def lib(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    research_id = store.create_research("What packet size?", "attached", "quick", [], "fake", "fake-model", None)
    source_id = store.create_upload_source("Synthetic packet study")
    passage_id = store._insert_passage(source_id, None, "abstract", None, None, "provider", None, None,
                                       "The study uses 128-byte packets.")
    store.add_to_corpus(research_id, source_id, "user_upload", selection_state="included", selection_origin="user")
    tables = TableStore(store)
    table_id = tables.create_table(research_id, "Packets", None, None, None)
    column_id = tables.add_column(research_id, table_id, COLUMN, 1, None)
    yield store, ReportStore(store), tables, research_id, source_id, passage_id, table_id, column_id
    conn.close()


def _fill(lib):
    store, _, tables, research_id, source_id, passage_id, table_id, column_id = lib
    run = store.create_run(research_id, "answer", {}, None)
    step = store.step(run["id"], "synthetic:cell", "model:cell_extraction")
    step_input_id = new_id("sti")
    store.insert_step_input(step["id"], research_id, run["id"], 0,
                            {"step_input_id": step_input_id, "task_type": "cell_extraction",
                             "scope_revision": 1, "skill_package_hash": "sha256:0"}, "base", "developer", "message", {})
    revision_id = tables.save_model_output(
        research_id, table_id, column_id, source_id, column_revision=1, state="value",
        value={"text": "128 bytes"}, note=None, reading_depth="abstract", output_status="structurally_valid",
        links=[{"passage_id": passage_id, "source_version_id": source_id, "anchor_text": "128-byte packets",
                "anchor_match": "exact"}], run_id=run["id"], step_id=step["id"], step_input_id=step_input_id,
        model_connection="fake", resolved_model="fake-model", scope_revision=1, cell_version_at_request=0,
        recheck=False,
    )
    store.update_run(run["id"], status="completed")
    return revision_id


def test_report_ready_requires_every_included_source_and_column_to_have_a_terminal_cell(lib):
    store, _, _, research_id, source_id, _, table_id, column_id = lib
    assert report_ready(store, research_id, table_id) == {
        "ready": False, "missing": [{"source_version_id": source_id, "column_id": column_id}], "failed_rows": []}
    _fill(lib)
    assert report_ready(store, research_id, table_id) == {"ready": True, "missing": [], "failed_rows": []}
    second = store.create_upload_source("Second synthetic study")
    store.add_to_corpus(research_id, second, "user_upload", selection_state="included", selection_origin="user")
    assert report_ready(store, research_id, table_id)["missing"] == [{"source_version_id": second, "column_id": column_id}]


def test_report_ready_accepts_human_not_reported_decision(lib):
    store, _, tables, research_id, source_id, _, table_id, column_id = lib
    tables.edit_cell(research_id, table_id, column_id, source_id, "not_reported", None,
                     "Checked the available source.", None, 0, None)
    expected = {"ready": True, "missing": [], "failed_rows": []}
    assert report_ready(store, research_id, table_id) == expected
    assert report_ready(store, research_id, table_id, continue_with_failed=True) == expected


def test_report_ready_requires_explicit_choice_to_continue_with_failed_row(lib):
    store, _, _, research_id, source_id, _, table_id, column_id = lib
    run = store.create_run(research_id, "table_fill", {}, None,
                           {"table_id": table_id, "sources": [{"source_version_id": source_id, "column_ids": [column_id]}]})
    step = store.step(run["id"], f"cell_extraction:{source_id}:0", "model:cell_extraction")
    store.finish_step(step["id"], "failed", error_code="synthetic_failure")
    assert report_ready(store, research_id, table_id) == {
        "ready": False, "missing": [{"source_version_id": source_id, "column_id": column_id}],
        "failed_rows": [source_id]}
    assert report_ready(store, research_id, table_id, continue_with_failed=True)["ready"] is True


def test_report_ready_can_exclude_a_row_with_no_readable_text(lib):
    store, _, tables, research_id, _, _, table_id, column_id = lib
    _fill(lib)
    no_text = store.create_upload_source("No text synthetic study")
    store.add_to_corpus(research_id, no_text, "user_upload", selection_state="included", selection_origin="user")
    tables.add_rows(research_id, table_id, [no_text], tables._table(research_id, table_id)["version"])
    run = store.create_run(research_id, "table_fill", {}, None,
                           {"table_id": table_id, "sources": [{"source_version_id": no_text, "column_ids": [column_id]}]})
    step = store.step(run["id"], f"no_text:{no_text}", "table_no_text")
    tables.save_no_text(research_id, table_id, column_id, no_text, column_revision=1,
                        run_id=run["id"], step_id=step["id"], scope_revision=1)
    assert report_ready(store, research_id, table_id)["ready"] is False
    assert report_ready(store, research_id, table_id, continue_with_failed=True) == {
        "ready": True, "missing": [{"source_version_id": no_text, "column_id": column_id}], "failed_rows": [no_text]}


def test_snapshot_counts_unique_works_separately_from_included_sources(lib):
    store, _, _, research_id, _, _, table_id, _ = lib
    excluded = store.create_upload_source("Excluded synthetic study")
    store.add_to_corpus(research_id, excluded, "user_upload", selection_state="excluded", selection_origin="user")
    corpus = build_snapshot(store, research_id, table_id)["corpus"]
    assert corpus["unique"] == 2
    assert corpus["included"] == 1


def test_snapshot_freezes_cell_revision_value_and_stored_evidence_after_later_edit(lib):
    store, reports, tables, research_id, source_id, passage_id, table_id, column_id = lib
    first_revision = _fill(lib)
    run = store.create_run(research_id, "report", {}, None)
    with transaction(store.conn):
        report_id = reports.create_report(research_id, run["id"], 1, "en")
        snapshot = reports.save_snapshot(report_id, table_id)
    stored_before = store.conn.execute("SELECT snapshot_json FROM report_snapshot WHERE report_id = ?", (report_id,)).fetchone()[0]
    cell = snapshot["cells"][0]
    assert cell == {"cell_id": cell["cell_id"], "cell_revision_id": first_revision, "column_id": column_id,
                    "source_version_id": source_id, "state": "value", "value": {"text": "128 bytes"},
                    "reading_depth": "abstract", "evidence": [{"passage_id": passage_id, "quote": "128-byte packets"}]}
    assert snapshot["corpus"] == {"found": 0, "unique": 1, "screened": 0, "included": 1, "full_text": 0}
    tables.edit_cell(research_id, table_id, column_id, source_id, "value", {"text": "256 bytes"}, None,
                     first_revision, 1, None)
    assert build_snapshot(store, research_id, table_id)["cells"][0]["value"] == {"text": "256 bytes"}
    stored_after = store.conn.execute("SELECT snapshot_json FROM report_snapshot WHERE report_id = ?", (report_id,)).fetchone()[0]
    assert stored_after == stored_before
    assert reports.snapshot(report_id) == json.loads(stored_before)
    assert reports.save_snapshot(report_id, table_id) == snapshot
