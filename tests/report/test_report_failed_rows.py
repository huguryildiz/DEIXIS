"""Reports over tables with failed or empty cells (D68), and the older failed-row snapshots they still read.

Synthetic records and fake adapters only: these tests show what the report run, its snapshot, views and exports do with
such cells; they say nothing about model quality.""" 

import asyncio
import copy
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.domain import contracts, skill
from deixis.domain.rules import RevisionConflict
from deixis.storage.db import dumps, new_id
from deixis.workflow.flow import RunStopped
from deixis.workflow.report import assembly, sections, review_methodology
from deixis.workflow.report.export import to_markdown
from deixis.workflow.report.gaps import generate_corpus_absence_candidates
from deixis.workflow.report.selection import select_evidence, usable_cells
from deixis.workflow.report.snapshot import build_snapshot, evidence_row_ids
from deixis.workflow.report.store import ReportStore
from deixis.workflow.tables import TableStore, report_ready
from deixis.workflow.views import report_view
from test_api_flow import create, session, wait_run
from test_report_api import create_table, fill_table, upload_and_include
from test_report_flow import COLUMN, PASSAGE, CELL_QUOTE, ReportAdapter, _add_pdf, _claim, report_flow


REFUSAL = "A report needs an evidence table with at least one column and one included source"


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


def save_cell(state, sid, cid, *, state_name="value", depth="abstract"):
    _, store, _, _, run, _, _ = state
    rid, table = run["research_id"], run["target"]["table_id"]
    fill = synthetic_fill_run(store, run, {"table_id": table})
    step = store.step(fill["id"], "synthetic:cell", "model:cell_extraction")
    sti = new_id("sti")
    store.insert_step_input(step["id"], rid, fill["id"], 0,
                            {"step_input_id": sti, "task_type": "cell_extraction", "scope_revision": 1,
                             "skill_package_hash": "sha256:synthetic"}, "base", "developer", "message", {})
    passage = store.passages_for(sid)[0]
    cell_version = TableStore(store).cell_view(rid, table, cid, sid)["version"]
    revision = TableStore(store).save_model_output(
        rid, table, cid, sid, column_revision=1, state=state_name,
        value={"text": "SYNTHETIC bounded formulation"} if state_name == "value" else None,
        note=None, reading_depth=depth, output_status="structurally_valid",
        links=[{"passage_id": passage["id"], "source_version_id": sid,
                "anchor_text": CELL_QUOTE, "anchor_match": "exact"}],
        run_id=fill["id"], step_id=step["id"], step_input_id=sti,
        model_connection="fake", resolved_model="fake-model", scope_revision=1,
        cell_version_at_request=cell_version, recheck=False,
    )
    cell = TableStore(store).cell_view(rid, table, cid, sid)
    if cell["pending_proposal"]:
        TableStore(store).decide_proposal(rid, table, cid, sid, revision, True, cell["version"], None)
    store.update_run(fill["id"], status="completed")
    return revision


def snapshot(state):
    _, _, reports, _, run, _, report = state
    return reports.save_snapshot(report, run["target"]["table_id"])


def legacy_snapshot(state, failed, reason="anchor_not_in_passage", save=True):
    """Save a snapshot as the failed-row rule saved it before D68: the failed rows listed with their missing
    columns, their cells left out, row counts, and no basis."""
    _, store, reports, _, run, _, report = state
    rid, table = run["research_id"], run["target"]["table_id"]
    frozen = build_snapshot(store, rid, table)
    frozen.pop("basis")
    terminal = {"value", "unknown", "not_reported", "not_applicable", "not_found_in_inspected_scope", "not_verified"}
    states = {(c["source_version_id"], c["column_id"]): c["state"] for c in frozen["cells"]}
    details, missing = [], 0
    for sid in failed:
        source = store.conn.execute("SELECT v.title, w.source_key FROM source_versions v JOIN works w ON w.id = v.work_id"
                                    " WHERE v.id = ?", (sid,)).fetchone()
        columns = [{"column_id": c["column_id"], "name": c["name"], "reason": reason}
                   for c in frozen["columns"] if states.get((sid, c["column_id"])) not in terminal]
        missing += len(columns)
        details.append({"source_version_id": sid, "source_key": source["source_key"], "title": source["title"],
                        "missing_columns": columns, "reason": reason, "existing_cells": []})
    frozen["cells"] = [c for c in frozen["cells"] if c["source_version_id"] not in failed]
    frozen["failed_rows"] = details
    frozen["row_counts"] = {"included": len(frozen["rows"]), "completed": len(frozen["rows"]) - len(failed),
                            "failed": len(failed), "cells_total": len(frozen["rows"]) * len(frozen["columns"]),
                            "cells_missing": missing}
    if save:
        store.conn.execute("INSERT INTO report_snapshot (report_id, table_id, table_revision, snapshot_json, created_at)"
                           " VALUES (?, ?, ?, ?, 'synthetic')", (report, table, frozen["table_revision"], dumps(frozen)))
    return frozen


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


def test_only_a_table_without_a_column_or_an_included_row_is_refused(state):
    _, store, reports, _, run, _, _ = state
    rid, table = run["research_id"], run["target"]["table_id"]
    store.update_run(run["id"], status="completed")
    tables = TableStore(store)
    for column in tables.target_columns(rid, table):
        tables.remove_column(rid, table, column["id"], column["version"])
    assert report_ready(store, rid, table)["ready"] is False
    with pytest.raises(RevisionConflict, match=REFUSAL):
        reports.request_report(rid, table, None)
    empty = tables.create_table(rid, "SYNTHETIC empty", [], None, None)
    tables.add_column(rid, empty, COLUMN, tables._table(rid, empty)["version"], None)
    assert report_ready(store, rid, empty)["ready"] is False


def test_the_snapshot_keeps_every_row_and_its_basis_names_what_could_not_be_verified(state):
    _, store, _, _, run, _, _ = state
    rid, table = run["research_id"], run["target"]["table_id"]
    no_text = add_source(state, "SYNTHETIC no text", text=False)
    fail_source(state, no_text, no_text=True)
    failed = add_source(state, "SYNTHETIC failed")
    fail_source(state, failed)
    partial = add_source(state, "SYNTHETIC partly read")
    _add_pdf(store, partial, [PASSAGE])
    columns = [c["id"] for c in TableStore(store).target_columns(rid, table)]
    save_cell(state, partial, columns[0], depth="selected_sections")
    frozen = snapshot(state)
    assert "failed_rows" not in frozen and "row_counts" not in frozen
    assert [r["source_version_id"] for r in frozen["rows"]][1:] == [no_text, failed, partial]
    assert frozen["basis"] == {
        "sources": 4, "full_text": 1, "abstract_only": 2, "metadata_only": 1, "cells_total": 12, "cells_unverified": 5,
        "unverified_sources": [
            {"source_version_id": failed, "source_key": frozen["basis"]["unverified_sources"][0]["source_key"],
             "title": "SYNTHETIC failed", "cells_unverified": 3, "cells_total": 3},
            {"source_version_id": partial, "source_key": frozen["basis"]["unverified_sources"][1]["source_key"],
             "title": "SYNTHETIC partly read", "cells_unverified": 2, "cells_total": 3}]}
    assert all(item["source_key"] for item in frozen["basis"]["unverified_sources"])
    assert evidence_row_ids(frozen) == [r["source_version_id"] for r in frozen["rows"]]


@pytest.mark.parametrize("language", ["en", "tr"])
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


@pytest.mark.parametrize("language", ["en", "tr"])
def test_a_legacy_failed_row_snapshot_keeps_its_boundary_views_and_export(state, language):
    flow, store, reports, adapter, run, _, report = state
    store.conn.execute("UPDATE reports SET language = ? WHERE id = ?", (language, report))
    sid = add_source(state, "SYNTHETIC partially filled")
    completed = store.included_sources(run["research_id"])[0]
    _add_pdf(store, completed, [PASSAGE])
    columns = TableStore(store).target_columns(run["research_id"], run["target"]["table_id"])
    for col, cell_state in zip(columns[:2], ("value", "not_found_in_inspected_scope")):
        save_cell(state, sid, col["id"], state_name=cell_state, depth="full_text")
    fail_source(state, sid, columns=[columns[2]["id"]])
    failed_passages = {p["id"] for p in store.passages_for(sid)}
    failed_cells = {r[0] for r in store.conn.execute("SELECT id FROM evidence_cells WHERE source_version_id = ?", (sid,))}
    legacy_snapshot(state, [sid])
    asyncio.run(flow.execute(run["id"]))
    assert store.run(run["id"])["status"] == "completed"
    assert reports.report(report)["status"] == "valid"
    frozen = reports.snapshot(report)
    assert frozen["row_counts"]["cells_missing"] == 1
    assert not any(c["source_version_id"] == sid for c in frozen["cells"])
    for section in ("III", "IV", "V", "VI", "VII"):
        selected = select_evidence(store, frozen, section, reports.report(report)["plan"], [])
        assert sid not in json.dumps(selected)
    for call in adapter.calls:
        if call["task_type"] not in ("report_plan", "report_section", "report_review"):
            continue
        assert sid not in call["allowlist"]["source_ids"]
        assert not failed_passages.intersection(call["allowlist"]["passage_ids"])
        assert not failed_cells.intersection(call["allowlist"].get("cell_ids", []))
        assert all(p["source_id"] != sid for p in call["passages"])
        assert all(s["source_id"] != sid for s in call["sources"])
        assert all(c["source_version_id"] != sid for c in (call.get("report_target") or {}).get("cells", []))
    ii = reports.section(report, "II")
    assert ii["validation"]["numbers"]["rows"] == frozen["row_counts"]
    assert ii["validation"]["numbers"]["full_text_ratio"] == 0.5
    assert ii["validation"]["numbers"]["corpus"]["included"] == 2
    assert ("missing table cells: 1 of 6" if language == "en" else "6 tablo hücresinin 1") in ii["draft"]["text"]
    viii = reports.section(report, "VIII")
    core = viii["validation"]["numbers"]
    assert core["items"][6]["number"] == 7 and core["items"][6]["key"] == "failed_rows"
    assert core["failed_rows"][0]["source_version_id"] == sid
    assert "anchor not in passage" in viii["draft"]["text"]
    assert assembly.run_assembly_checks(store, reports, report) == []
    view = report_view(store, run["research_id"], report)
    assert view["missing_rows"]["counts"] == frozen["row_counts"] and view["basis"] is None
    assert [r.get("failed", False) for r in view["table_i"]["rows"]] == [False, True]
    markdown = to_markdown(view, title="SYNTHETIC report", corpus=frozen["corpus"])
    assert ("missing cells: 1" if language == "en" else "1 hücre eksik") in markdown
    assert core["failed_rows"][0]["name"] in markdown and "anchor not in passage" in markdown
    assert "—" in markdown


def test_runner_fails_closed_if_transactional_readiness_changes(state, monkeypatch):
    flow, store, _, _, run, scope, _ = state
    fail_source(state, add_source(state, "SYNTHETIC failed"))
    from deixis.workflow import tables as table_module
    original = table_module.report_ready
    moments = []
    def changed(store_arg, rid, table):
        moments.append(store_arg.conn.in_transaction)
        result = original(store_arg, rid, table)
        return result | {"ready": False} if store_arg.conn.in_transaction else result
    monkeypatch.setattr(table_module, "report_ready", changed)
    with pytest.raises(RunStopped):
        asyncio.run(sections.run_report(flow, run, scope))
    assert moments[-1] is True
    assert store.run(run["id"])["pause_reason"] == "table_not_ready"
    assert store.conn.execute("SELECT COUNT(*) FROM report_snapshot").fetchone()[0] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM events WHERE type = 'report_snapshot_saved'").fetchone()[0] == 0


def test_failed_row_edits_are_not_cell_changes_but_departure_remains_a_corpus_change(state):
    _, store, reports, _, run, _, report = state
    sid = add_source(state, "SYNTHETIC failed")
    fail_source(state, sid)
    frozen = legacy_snapshot(state, [sid])
    save_cell(state, sid, frozen["columns"][0]["column_id"])
    assert reports.evidence_changes(report)["changed_cells"] == 0
    tables = TableStore(store)
    table, rid = run["target"]["table_id"], run["research_id"]
    tables.remove_row(rid, table, sid, tables._table(rid, table)["version"])
    assert reports.evidence_changes(report)["removed_sources"] == 1


@pytest.mark.parametrize("change", ["fill", "column", "source"])
def test_a_resume_with_failed_cells_uses_its_frozen_snapshot_after_live_edits(state, change):
    flow, store, reports, adapter, run, scope, report = state
    sid = add_source(state, "SYNTHETIC failed")
    fail_source(state, sid)
    adapter.before = lambda si: store.update_run(run["id"], status="pause_requested") if si["task_type"] == "report_plan" else None
    with pytest.raises(RunStopped):
        asyncio.run(sections.run_report(flow, run, scope))
    before = reports.snapshot(report)
    table = run["target"]["table_id"]
    tables = TableStore(store)
    if change == "fill":
        save_cell(state, sid, before["columns"][0]["column_id"])
    elif change == "column":
        tables.add_column(run["research_id"], table, COLUMN | {"name": "SYNTHETIC new column"},
                          tables._table(run["research_id"], table)["version"], None)
    else:
        add_source(state, "SYNTHETIC new untried source")
    adapter.before = None
    store.update_run(run["id"], status="running", pause_reason=None)
    asyncio.run(flow.execute(run["id"]))
    assert store.run(run["id"])["status"] == "completed"
    assert reports.snapshot(report) == before


def test_default_resume_goes_on_from_its_saved_snapshot_and_plan(state):
    # D63: a report paused after its snapshot and plan is not failed by rows the table gained since, and its word budgets
    # stay those it froze; the added source is reported as a change instead.
    flow, store, reports, adapter, run, scope, report = state
    adapter.before = lambda si: store.update_run(run["id"], status="pause_requested") if si["task_type"] == "report_section" else None
    with pytest.raises(RunStopped):
        asyncio.run(sections.run_report(flow, run, scope))
    before, plan = reports.snapshot(report), reports.report(report)["plan"]
    assert plan is not None
    add_source(state, "SYNTHETIC untried")
    adapter.before = None
    store.update_run(run["id"], status="running", pause_reason=None)
    asyncio.run(flow.execute(run["id"]))
    assert store.run(run["id"])["status"] == "completed"
    assert reports.snapshot(report) == before and reports.report(report)["plan"] == plan
    assert reports.evidence_changes(report)["added_sources"] == 1



@pytest.mark.parametrize("failed", [False, True])
def test_word_budget_uses_completed_snapshot_rows_only_when_present(state, monkeypatch, failed):
    flow, store, _, _, run, scope, _ = state
    if failed:
        sid = add_source(state, "SYNTHETIC failed")
        fail_source(state, sid)
        legacy_snapshot(state, [sid])
    original = sections.freeze_plan
    counts = []
    def freeze(output, frozen, count):
        counts.append(count)
        return original(output, frozen, count)
    monkeypatch.setattr(sections, "freeze_plan", freeze)
    asyncio.run(sections.run_report(flow, run, scope))
    assert counts == [1]
    assert len(TableStore(store).active_rows(run["target"]["table_id"])) == (2 if failed else 1)


def test_limitations_input_contract_accepts_six_and_seven_but_refuses_bad_seventh(state):
    flow, store, reports, adapter, run, scope, report = state
    asyncio.run(sections.run_report(flow, run, scope))
    old = next(copy.deepcopy(si) for si in adapter.calls if si["task_type"] == "report_section"
               and si["report_target"]["section_id"] == "VIII")
    assert contracts.check_step_input(old) == []
    sid = add_source(state, "SYNTHETIC failed")
    fail_source(state, sid)
    frozen = legacy_snapshot(state, [sid], save=False)
    updated = copy.deepcopy(old)
    updated["report_target"]["limitations_core"] = review_methodology.limitations_core(store, reports, report, frozen)
    assert contracts.check_step_input(updated) == []
    for field, value in (("key", "truncation"), ("number", 8)):
        bad = copy.deepcopy(updated)
        bad["report_target"]["limitations_core"]["items"][6][field] = value
        assert "step_input_schema_invalid" in {i.code for i in contracts.check_step_input(bad)}
    # D243 changes shared answer instructions, the clean start (D1) the method cleanup and UI parity S5a the column
    # suggestion frame, S22a, D66 and D92 the follow-up method files, D51 and D87 the report writing rules; failed-row input rules stay fixed.
    assert skill.load_skill_package().package_hash == "sha256:5766d7fc0043707019cdb200641d0b834fb449bcb33e9eed1d6c3016213ec70c"


def test_three_full_text_absence_rows_have_identical_candidates_with_failed_row(state):
    _, store, reports, _, run, _, report = state
    rid, table = run["research_id"], run["target"]["table_id"]
    cid = TableStore(store).target_columns(rid, table)[0]["id"]
    first = store.included_sources(rid)[0]
    # Use fresh model revisions for the three completed full-text rows.
    for sid in [first, add_source(state, "SYNTHETIC completed 2"), add_source(state, "SYNTHETIC completed 3")]:
        for column in TableStore(store).target_columns(rid, table):
            save_cell(state, sid, column["id"], state_name="not_found_in_inspected_scope", depth="full_text")
        _add_pdf(store, sid, [PASSAGE])
    axes = [{"axis_id": "AX1", "column_id": cid}]
    baseline = generate_corpus_absence_candidates(build_snapshot(store, rid, table), axes)
    assert baseline[0]["full_text_applicable_count"] == 3
    failed = add_source(state, "SYNTHETIC partial full text")
    _add_pdf(store, failed, [PASSAGE])
    save_cell(state, failed, cid, state_name="not_found_in_inspected_scope", depth="full_text")
    remaining = [c["id"] for c in TableStore(store).target_columns(rid, table)][1:]
    fail_source(state, failed, columns=remaining)
    frozen = legacy_snapshot(state, [failed])
    assert generate_corpus_absence_candidates(frozen, axes) == baseline
    reports.set_plan(report, {"axes": axes})
    reports.save_gaps(report, [{"gap_id": "gap1", "kind": "corpus_absence", "text": "SYNTHETIC candidate",
                              "basis_claim_keys": [], "basis_passage_ids": [], "basis_cell_ids": baseline[0]["basis_cell_ids"],
                              "nearest_match": {"status": "not_searched", "source_id": None, "cell_id": None},
                              "provenance": {"origin": "code", "section_id": "VI", "step_input_id": "sti_synthetic"}}])
    # No stored VI input: the existing check refuses it; adding the failed cell cannot make its basis valid.
    failed_cell = store.conn.execute("SELECT id FROM evidence_cells WHERE source_version_id = ? AND column_id = ?",
                                    (failed, cid)).fetchone()[0]
    store.conn.execute("UPDATE report_gaps SET basis_json = ? WHERE report_id = ?",
                       (dumps({"basis_claim_keys": [], "basis_passage_ids": [],
                               "basis_cell_ids": baseline[0]["basis_cell_ids"] + [failed_cell]}), report))
    assert "gap_absence_basis_invalid" in {i["rule"] for i in assembly._check_gap_bases(store, reports, report)}
    review_methodology.write_review_methodology(store, reports, report, rid, frozen)
    assert reports.section(report, "II")["validation"]["numbers"]["full_text_ratio"] == 1


def test_existing_assembly_rule_rejects_a_legacy_failed_source_citation(state):
    _, store, reports, _, run, _, report = state
    sid = add_source(state, "SYNTHETIC failed")
    fail_source(state, sid)
    legacy_snapshot(state, [sid])
    section = reports.create_section(report, "III", 3)
    passage = store.passages_for(sid)[0]["id"]
    step = store.step(run["id"], "synthetic:citation", "model:report_section")
    sti = new_id("sti")
    store.insert_step_input(step["id"], run["research_id"], run["id"], 0,
                            {"step_input_id": sti, "task_type": "report_section", "scope_revision": 1,
                             "skill_package_hash": "sha256:synthetic"}, "base", "developer", "message", {})
    reports.save_claims(section, [_claim("III", passage_ids=[passage])],
                        [{"claim_key": "III.1", "passage_id": passage, "cell_id": None,
                          "source_version_id": sid, "step_input_id": sti, "anchor_text": CELL_QUOTE,
                          "anchor_match": "exact"}])
    assert "citation_source_not_in_corpus" in {i["rule"] for i in assembly._check_bibliography(store, reports, report)}
    store.conn.execute("UPDATE report_claims SET count_json = ? WHERE report_section_id = ?",
                       (dumps({"numerator_source_ids": [sid], "denominator_source_ids": [sid],
                               "column_id": reports.snapshot(report)["columns"][0]["column_id"]}), section))
    assert "count_member_not_in_snapshot" in {i["rule"] for i in assembly._check_count_fields(store, reports, report)}


def test_old_snapshot_and_code_sections_keep_their_shapes_and_output(state):
    flow, store, reports, _, run, scope, report = state
    table, rid = run["target"]["table_id"], run["research_id"]
    old = build_snapshot(store, rid, table)
    assert set(old) == {"table_revision", "columns", "rows", "cells", "corpus", "basis"}
    source = store.included_sources(rid)[0]
    passage = store.passages_for(source)[0]["id"]
    version = store.conn.execute("SELECT version_label FROM source_versions WHERE id = ?", (source,)).fetchone()[0]
    expected_old = {"table_revision": TableStore(store)._table(rid, table)["version"],
                    "columns": [{"column_id": c["id"], "revision": c["current_revision"], "name": c["name"],
                                 "instruction": c["instruction"], "answer_format": c["answer_format"]}
                                for c in TableStore(store).target_columns(rid, table)],
                    "rows": [{"source_version_id": source, "version_label": version, "reading_depth": "abstract"}],
                    "cells": [{"cell_id": c["cell_id"], "cell_revision_id": c["cell_revision_id"], "column_id": c["column_id"],
                               "source_version_id": source, "state": "value", "value": {"text": "SYNTHETIC bounded formulation"},
                               "reading_depth": "abstract", "evidence": [{"passage_id": passage, "quote": CELL_QUOTE}]}
                              for c in old["cells"]],
                    "corpus": {"found": 0, "unique": 1, "screened": 0, "included": 1, "full_text": 0},
                    "basis": {"sources": 1, "full_text": 0, "abstract_only": 1, "metadata_only": 0, "cells_total": 3,
                              "cells_unverified": 0, "unverified_sources": []}}
    assert old == expected_old
    assert reports.save_snapshot(report, table) == old
    asyncio.run(sections.run_report(flow, run, scope))
    view = report_view(store, rid, report)
    before = to_markdown(view, title="SYNTHETIC", corpus=old["corpus"])
    ii = reports.section(report, "II")
    viii = reports.section(report, "VIII")
    assert "rows" not in ii["validation"]["numbers"]
    core = viii["validation"]["numbers"]
    assert "failed_rows" not in core and len(core["items"]) == 6
    assert viii["draft"]["text"] == review_methodology.render_limitations(core, "en")
    review_methodology.write_review_methodology(store, reports, report, rid, old)
    assert reports.section(report, "II")["draft"] == ii["draft"]
    assert view["missing_rows"] is None
    assert reports.evidence_changes(report)["any"] is False
    assert assembly.run_assembly_checks(store, reports, report) == []
    for section in ("III", "IV", "V", "VI", "VII"):
        assert select_evidence(store, old, section, reports.report(report)["plan"], []) == select_evidence(
            store, reports.snapshot(report), section, reports.report(report)["plan"], [])
    assert generate_corpus_absence_candidates(old, []) == []
    assert to_markdown(report_view(store, rid, report), title="SYNTHETIC", corpus=old["corpus"]) == before


def test_api_starts_a_report_over_a_row_without_text_and_names_it(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "api", port=8804), adapters={"fake": ReportAdapter()},
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        upload_and_include(client, rid)
        table = create_table(client, rid, with_columns=True)
        fill_table(client, rid, table)
        store = raw.app.state.store
        sid = store.create_upload_source("SYNTHETIC missing text")
        store.add_to_corpus(rid, sid, "user_upload", selection_state="included", selection_origin="user")
        table_id = table["table"]["id"]
        tables = TableStore(store)
        tables.add_rows(rid, table_id, [sid], tables._table(rid, table_id)["version"])
        fill = tables.request_fill(rid, table_id, None, False, tables._table(rid, table_id)["version"], None)
        raw.app.state.worker.wake()
        _, done = wait_run(client, rid, fill["id"])
        assert done["status"] == "completed"
        url = f"/api/researches/{rid}/reports"
        accepted = client.post(url, json={"table_id": table_id})
        assert accepted.status_code == 202, accepted.text
        assert "continue_with_failed" not in accepted.json()["target"]
        _, done = wait_run(client, rid, accepted.json()["id"])
        assert done["status"] == "completed", (done["pause_reason"], done.get("error"))
        view = client.get(f"{url}/{accepted.json()['target']['report_id']}").json()
        assert view["missing_rows"] is None
        assert (view["basis"]["sources"], view["basis"]["metadata_only"]) == (2, 1)
        # A row without text holds 'inaccessible' cells: it counts as read from metadata only, not as unverified.
        assert view["basis"]["unverified_sources"] == [] and sid in [r["source_version_id"] for r in reports_rows(raw, accepted)]
        # An older client that still sends the removed choice is not refused.
        again = client.post(url, json={"table_id": table_id, "continue_with_failed": True})
        assert again.status_code == 202, again.text
        wait_run(client, rid, again.json()["id"])


def reports_rows(raw, accepted):
    return ReportStore(raw.app.state.store).snapshot(accepted.json()["target"]["report_id"])["rows"]


def test_scripted_marker_fails_only_fixed_source_through_real_fill_path(state):
    from tests.acceptance.fixture_server import ScriptedCodex

    flow, store, _, _, run, scope, _ = state
    failed = add_source(state, "SYNTHETIC molecule release scheduling with bisection")
    healthy = add_source(state, "SYNTHETIC healthy extraction")
    store.update_run(run["id"], status="completed")
    rid, table = run["research_id"], run["target"]["table_id"]
    tables = TableStore(store)
    fill = tables.request_fill(rid, table, None, False, tables._table(rid, table)["version"], None)
    store.update_run(fill["id"], status="running")
    flow.deps.adapters = {"fake": ScriptedCodex()}
    asyncio.run(flow._table_fill(store.run(fill["id"]), scope | {"question": scope["question"] + " [fill-fails-one-row]"}))
    steps = [s for s in store.run_steps(fill["id"]) if s["kind"] == "model:cell_extraction"]
    assert [(s["status"], s["error_code"]) for s in steps if failed in s["operation_key"]] == [("failed", "invalid_model_output")]
    assert all(s["status"] == "succeeded" for s in steps if healthy in s["operation_key"])
    readiness = report_ready(store, rid, table)
    assert readiness["ready"] and {m["source_version_id"] for m in readiness["missing"]} == {failed}
    assert len(readiness["missing"]) == 3
    # Invalid JSON is a whole-output failure: nothing is salvaged or retried for it.
    assert not any(s["operation_key"].startswith("cell_salvage:") or s["operation_key"].endswith(":retry")
                   for s in store.run_steps(fill["id"]))
    assert store.conn.execute("SELECT COUNT(*) FROM cell_revisions r JOIN evidence_cells c ON c.id = r.cell_id"
                              " WHERE c.source_version_id = ?", (failed,)).fetchone()[0] == 0


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
