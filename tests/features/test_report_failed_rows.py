"""Reports over tables with failed or empty cells (D68), and the older failed-row snapshots they still read.

Synthetic records and fake adapters only: these tests show what the report run, its snapshot, views and exports do with
such cells; they say nothing about model quality.""" 

import asyncio
from dataclasses import replace

import pytest

from deixis.workflow import report_assembly as assembly, report_sections as sections
from deixis.workflow.report_export import to_markdown
from deixis.workflow.report_selection import select_evidence, usable_cells
from deixis.workflow.report_snapshot import evidence_row_ids
from deixis.workflow.tables import TableStore, report_ready
from deixis.workflow.views import report_view
from test_report_flow import PASSAGE, report_flow


def synthetic_fill_run(store, run, target):
    status = store.run(run["id"])["status"]
    store.update_run(run["id"], status="paused")
    fill = store.create_run(run["research_id"], "table_fill", {}, None, target)
    store.update_run(run["id"], status=status)
    return fill


@pytest.fixture
def state(tmp_path):
    value = report_flow(tmp_path)
    # No server is started by this fixture; keep even its configured port separate from the live library.
    value[0].deps.settings = replace(value[0].deps.settings, port=8804)
    yield value
    value[1].conn.close()


def add_source(state, title, *, text=True):
    _, store, _, _, run, _, _ = state
    rid, table = run["research_id"], run["target"]["table_id"]
    sid = store.create_upload_source(title)
    if text:
        store._insert_passage(sid, None, "abstract", None, None, "synthetic", None, None, PASSAGE)
    store.add_to_corpus(rid, sid, "user_upload", selection_state="included", selection_origin="user")
    tables = TableStore(store)
    tables.add_rows(rid, table, [sid], tables._table(rid, table)["version"])
    return sid


def fail_source(state, sid, *, columns=None, no_text=False, code="anchor_not_in_passage", status="failed", revision=None):
    _, store, _, _, run, _, _ = state
    rid, table = run["research_id"], run["target"]["table_id"]
    tables = TableStore(store)
    columns = columns or [c["id"] for c in tables.target_columns(rid, table)]
    fill = synthetic_fill_run(store, run,
                              {"table_id": table, "sources": [{"source_version_id": sid, "column_ids": columns}]})
    if revision is not None:
        store.conn.execute("UPDATE runs SET scope_revision = ? WHERE id = ?", (revision, fill["id"]))
    step = store.step(fill["id"], f"no_text:{sid}" if no_text else f"cell_extraction:{sid}:0",
                      "table_no_text" if no_text else "model:cell_extraction")
    if no_text:
        for cid in columns:
            tables.save_no_text(rid, table, cid, sid, column_revision=1,
                                run_id=fill["id"], step_id=step["id"], scope_revision=1)
    store.finish_step(step["id"], status, error_code=code)
    store.update_run(fill["id"], status="completed")
    return step


def snapshot(state):
    _, _, reports, _, run, _, report = state
    return reports.save_snapshot(report, run["target"]["table_id"])


def test_a_report_starts_without_a_choice_when_cells_failed_or_are_empty(state):
    _, store, reports, _, run, _, _ = state
    rid, table = run["research_id"], run["target"]["table_id"]
    failed = add_source(state, "SYNTHETIC failed extraction")
    fail_source(state, failed)
    add_source(state, "SYNTHETIC never filled")
    readiness = report_ready(store, rid, table)
    assert readiness["ready"] is True and len(readiness["missing"]) == 6 and readiness["rows"] == 3
    assert TableStore(store).tables(rid)[0]["report_ready"] == {"ready": True, "cells_left": 6, "cells_total": 9, "included_rows": 3}
    store.update_run(run["id"], status="completed")
    created = reports.request_report(rid, table, "plain")
    assert created["target"] == {"table_id": table, "report_id": created["target"]["report_id"]}


@pytest.mark.parametrize("language", ["en"])
def test_a_fully_failed_source_is_used_from_its_abstract_and_named_in_the_basis_note(state, language):
    flow, store, reports, adapter, run, _, report = state
    store.conn.execute("UPDATE reports SET language = ? WHERE id = ?", (language, report))
    sid = add_source(state, "SYNTHETIC fully failed")
    fail_source(state, sid)
    asyncio.run(flow.execute(run["id"]))
    assert store.run(run["id"])["status"] == "completed"
    assert reports.report(report)["status"] == "valid"
    frozen = reports.snapshot(report)
    assert sid in evidence_row_ids(frozen) and not any(c["source_version_id"] == sid for c in frozen["cells"])
    # Its abstract is given to the sections that read passages; its cells, holding nothing, are not.
    # The model sees records by handle, so the source is found by its title and its passage by that source.
    given = [call for call in adapter.calls if call["task_type"] == "report_section"]
    shown = [(call, next((x["source_id"] for x in call["sources"] if x.get("title") == "SYNTHETIC fully failed"), None))
             for call in given]
    assert any(handle and any(p["source_id"] == handle and p["text"] == PASSAGE for p in call["passages"])
               for call, handle in shown)
    assert not any(c["source_version_id"] == handle for call, handle in shown if handle
                   for c in call["report_target"]["cells"])
    assert assembly.run_assembly_checks(store, reports, report) == []
    view = report_view(store, run["research_id"], report)
    assert view["missing_rows"] is None
    assert view["basis"]["unverified_sources"][0]["source_version_id"] == sid
    markdown = to_markdown(view, title="SYNTHETIC report", corpus=frozen["corpus"])
    key = view["basis"]["unverified_sources"][0]["source_key"]
    if language == "en":
        assert ("Basis of this report: 0 of 2 sources were read from full text and 2 from the abstract or metadata only."
                " 3 of 6 table cells could not be verified against a quote; the report does not cite them.") in markdown
        assert "Upload the PDFs of the sources read from the abstract or metadata for a more detailed report." in markdown
        assert f"- {key}: 3 of 3 cells not verified" in markdown
    else:
        assert "Bu raporun dayanağı: 2 kaynağın 0 tanesi tam metinden" in markdown and "PDF'lerini yükleyin" in markdown
        assert f"- {key}: 3 hücreden 3 tanesi doğrulanmadı" in markdown
    assert markdown.index("Basis") < markdown.index("## ") if language == "en" else markdown.index("dayanağı") < markdown.index("## ")


def test_cells_no_claim_can_cite_are_neither_evidence_nor_a_count(state):
    _, store, reports, _, run, _, report = state
    rid, table = run["research_id"], run["target"]["table_id"]
    no_text = add_source(state, "SYNTHETIC no text", text=False)
    fail_source(state, no_text, no_text=True)
    sid = add_source(state, "SYNTHETIC unverified")
    column = TableStore(store).target_columns(rid, table)[0]["id"]
    TableStore(store).edit_cell(rid, table, column, sid, "not_verified", {"text": "SYNTHETIC unchecked value"}, None, None,
                                0, None)
    frozen = snapshot(state)
    hidden = {c["cell_id"] for c in frozen["cells"] if c["source_version_id"] in (no_text, sid)}
    assert hidden and not hidden & {c["cell_id"] for c in usable_cells(frozen)}
    context = sections._validation_context(state[0], report, frozen, "IV")
    assert not hidden & {c["cell_id"] for c in context["cells"]}
    for section in ("IV", "V"):
        assert not hidden & {c["cell_id"] for c in select_evidence(store, frozen, section, {}, [])["cells"]}
