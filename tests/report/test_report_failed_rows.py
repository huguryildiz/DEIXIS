"""Failed-row report boundaries using synthetic records and fake adapters only."""

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
from deixis.workflow.report.selection import select_evidence
from deixis.workflow.report.snapshot import build_snapshot, evidence_row_ids
from deixis.workflow.report.store import ReportStore
from deixis.workflow.tables import TableStore, report_ready
from deixis.workflow.views import report_view
from test_api_flow import create, session, wait_run
from test_report_api import create_table, fill_table, upload_and_include
from test_report_flow import COLUMN, PASSAGE, CELL_QUOTE, ReportAdapter, _add_pdf, _claim, report_flow


REFUSAL = "Include sources and fill every active evidence-table column before starting a report"


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


def flagged(state):
    _, store, _, _, run, _, _ = state
    return store.update_run(run["id"], target_json=dumps(run["target"] | {"continue_with_failed": True}))


def snapshot(state):
    _, _, reports, _, run, _, report = state
    return reports.save_snapshot(report, run["target"]["table_id"], continue_with_failed=True)


def test_default_refuses_and_flag_requires_recorded_failures_and_a_completed_row(state):
    _, store, reports, _, run, _, _ = state
    rid, table = run["research_id"], run["target"]["table_id"]
    sid = add_source(state, "SYNTHETIC failed extraction")
    fail_source(state, sid)
    assert report_ready(store, rid, table)["ready"] is False
    assert report_ready(store, rid, table, True)["ready"] is True
    with pytest.raises(RevisionConflict, match=REFUSAL):
        reports.request_report(rid, table, None)
    store.update_run(run["id"], status="completed")
    created = reports.request_report(rid, table, "explicit", continue_with_failed=True)
    assert created["target"] == {"table_id": table, "report_id": created["target"]["report_id"], "continue_with_failed": True}
    store.update_run(created["id"], status="completed")
    untried = add_source(state, "SYNTHETIC untried")
    assert not report_ready(store, rid, table, True)["ready"]
    fail_source(state, untried)
    completed = evidence_row_ids(build_snapshot(store, rid, table))[0]
    tables = TableStore(store)
    tables.remove_row(rid, table, completed, tables._table(rid, table)["version"])
    # An included source without an active row is blocked even with its old terminal revisions.
    assert not report_ready(store, rid, table, True)["ready"]
    store.conn.execute("UPDATE corpus_memberships SET removed_at = 'synthetic' WHERE source_version_id = ?", (completed,))
    assert not report_ready(store, rid, table, True)["ready"]  # every remaining row failed


@pytest.mark.parametrize("status,code,expected", [("failed", "anchor_not_in_passage", "anchor_not_in_passage"),
                                                 ("outcome_unknown", None, "extraction_failed")])
def test_snapshot_keeps_failed_provenance_but_writes_no_cell_evidence(state, status, code, expected):
    _, store, _, _, run, _, _ = state
    no_text = add_source(state, "SYNTHETIC no text", text=False)
    fail_source(state, no_text, no_text=True)
    failed = add_source(state, "SYNTHETIC failed")
    fail_source(state, failed, status=status, code=code)
    counts_before = [store.conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                     for name in ("cell_revisions", "cell_evidence_links")]
    frozen = snapshot(state)
    assert len(frozen["rows"]) == 3 and len(frozen["cells"]) == 3
    assert all(row["reading_depth"] is None for row in frozen["rows"] if row["source_version_id"] in (failed, no_text))
    assert [r["source_version_id"] for r in frozen["failed_rows"]] == [no_text, failed]
    for row, reason in zip(frozen["failed_rows"], ("no_stored_text", expected)):
        assert row["title"] and row["source_key"] and row["reason"] == reason
        assert [c["reason"] for c in row["missing_columns"]] == [reason] * 3
        assert all(set(cell) == {"cell_id", "cell_revision_id", "column_id", "state"} for cell in row["existing_cells"])
    assert len(frozen["failed_rows"][0]["existing_cells"]) == 3
    assert {c["cell_revision_id"] for c in frozen["failed_rows"][0]["existing_cells"]} == {
        row[0] for row in store.conn.execute("SELECT current_revision_id FROM evidence_cells WHERE source_version_id = ?", (no_text,))}
    assert frozen["failed_rows"][1]["existing_cells"] == []
    assert frozen["row_counts"] == {"included": 3, "completed": 1, "failed": 2, "cells_total": 9, "cells_missing": 6}
    assert counts_before == [store.conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                             for name in ("cell_revisions", "cell_evidence_links")]
    summary = TableStore(store).tables(run["research_id"])[0]["report_ready"]
    assert summary == {"ready": False, "cells_left": 6, "cells_total": 9, "failed_rows": 2,
                       "can_continue_with_failed": True, "failed_cells": 6, "included_rows": 3}


def test_failed_step_from_another_scope_cannot_qualify_an_untried_row(state):
    _, store, _, _, run, _, _ = state
    sid = add_source(state, "SYNTHETIC stale failure")
    fail_source(state, sid, revision=0)
    assert report_ready(store, run["research_id"], run["target"]["table_id"], True)["failed_rows"] == []


def test_flagged_snapshot_refusal_writes_nothing_but_default_still_saves(state):
    _, store, reports, _, _, _, report = state
    add_source(state, "SYNTHETIC untried")
    events = store.conn.execute("SELECT COUNT(*) FROM events WHERE type = 'report_snapshot_saved'").fetchone()[0]
    with pytest.raises(RevisionConflict, match=REFUSAL):
        snapshot(state)
    assert store.conn.execute("SELECT COUNT(*) FROM report_snapshot").fetchone()[0] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM events WHERE type = 'report_snapshot_saved'").fetchone()[0] == events
    table = state[4]["target"]["table_id"]
    old = reports.save_snapshot(report, table)
    assert "failed_rows" not in old and "row_counts" not in old
    assert reports.save_snapshot(report, table, True) == old


@pytest.mark.parametrize("language", ["en", "tr"])
def test_complete_flagged_run_views_export_numbers_and_evidence_inputs(state, language):
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
    flagged(state)
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
    assert core["items"][7]["number"] == 8 and core["items"][7]["key"] == "failed_rows"
    assert core["failed_rows"][0]["source_version_id"] == sid
    assert "anchor not in passage" in viii["draft"]["text"]
    assert assembly.run_assembly_checks(store, reports, report) == []
    view = report_view(store, run["research_id"], report)
    assert view["missing_rows"]["counts"] == frozen["row_counts"]
    assert [r.get("failed", False) for r in view["table_i"]["rows"]] == [False, True]
    markdown = to_markdown(view, title="SYNTHETIC report", corpus=frozen["corpus"])
    assert ("missing cells: 1" if language == "en" else "1 hücre eksik") in markdown
    assert core["failed_rows"][0]["name"] in markdown and "anchor not in passage" in markdown
    assert "—" in markdown


def test_runner_without_choice_fails_before_snapshot(state):
    flow, store, reports, adapter, run, scope, _ = state
    fail_source(state, add_source(state, "SYNTHETIC failed"))
    with pytest.raises(RunStopped):
        asyncio.run(sections.run_report(flow, run, scope))
    assert store.run(run["id"])["pause_reason"] == "table_not_ready"
    assert adapter.calls == [] and store.conn.execute("SELECT COUNT(*) FROM report_snapshot").fetchone()[0] == 0


def test_runner_fails_closed_if_transactional_readiness_changes(state, monkeypatch):
    flow, store, _, _, run, scope, _ = state
    fail_source(state, add_source(state, "SYNTHETIC failed"))
    run = flagged(state)
    from deixis.workflow import tables as table_module
    original = table_module.report_ready
    moments = []
    def changed(store_arg, rid, table, continue_with_failed=False):
        moments.append(store_arg.conn.in_transaction)
        if store_arg.conn.in_transaction:
            add_source(state, "SYNTHETIC row added before snapshot")
        return original(store_arg, rid, table, continue_with_failed)
    monkeypatch.setattr(table_module, "report_ready", changed)
    with pytest.raises(RunStopped):
        asyncio.run(sections.run_report(flow, run, scope))
    assert moments == [True]
    assert store.run(run["id"])["pause_reason"] == "table_not_ready"
    assert store.conn.execute("SELECT COUNT(*) FROM report_snapshot").fetchone()[0] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM events WHERE type = 'report_snapshot_saved'").fetchone()[0] == 0


def test_failed_row_edits_are_not_cell_changes_but_departure_remains_a_corpus_change(state):
    _, store, reports, _, run, _, report = state
    sid = add_source(state, "SYNTHETIC failed")
    fail_source(state, sid)
    frozen = snapshot(state)
    save_cell(state, sid, frozen["columns"][0]["column_id"])
    assert reports.evidence_changes(report)["changed_cells"] == 0
    tables = TableStore(store)
    table, rid = run["target"]["table_id"], run["research_id"]
    tables.remove_row(rid, table, sid, tables._table(rid, table)["version"])
    assert reports.evidence_changes(report)["removed_sources"] == 1


@pytest.mark.parametrize("change", ["fill", "column", "source"])
def test_flagged_resume_uses_frozen_snapshot_after_live_edits(state, change):
    flow, store, reports, adapter, run, scope, report = state
    sid = add_source(state, "SYNTHETIC failed")
    fail_source(state, sid)
    run = flagged(state)
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
        assert not report_ready(store, run["research_id"], table, True)["ready"]
    else:
        add_source(state, "SYNTHETIC new untried source")
        assert not report_ready(store, run["research_id"], table, True)["ready"]
    adapter.before = None
    store.update_run(run["id"], status="running", pause_reason=None)
    asyncio.run(flow.execute(run["id"]))
    assert store.run(run["id"])["status"] == "completed"
    assert reports.snapshot(report) == before


def test_default_resume_still_checks_live_readiness_first(state):
    flow, store, reports, adapter, run, scope, report = state
    reports.save_snapshot(report, run["target"]["table_id"])
    add_source(state, "SYNTHETIC untried")
    with pytest.raises(RunStopped):
        asyncio.run(sections.run_report(flow, run, scope))
    assert store.run(run["id"])["pause_reason"] == "table_not_ready" and adapter.calls == []


@pytest.mark.parametrize("failed", [False, True])
def test_word_budget_uses_completed_snapshot_rows_only_when_present(state, monkeypatch, failed):
    flow, store, _, _, run, scope, _ = state
    if failed:
        fail_source(state, add_source(state, "SYNTHETIC failed"))
        run = flagged(state)
    original = sections.freeze_plan
    counts = []
    def freeze(output, frozen, count):
        counts.append(count)
        return original(output, frozen, count)
    monkeypatch.setattr(sections, "freeze_plan", freeze)
    asyncio.run(sections.run_report(flow, run, scope))
    assert counts == [1]
    assert len(TableStore(store).active_rows(run["target"]["table_id"])) == (2 if failed else 1)


def test_limitations_input_contract_accepts_seven_and_eight_but_refuses_bad_eighth(state):
    flow, store, reports, adapter, run, scope, report = state
    asyncio.run(sections.run_report(flow, run, scope))
    old = next(copy.deepcopy(si) for si in adapter.calls if si["task_type"] == "report_section"
               and si["report_target"]["section_id"] == "VIII")
    assert contracts.check_step_input(old) == []
    sid = add_source(state, "SYNTHETIC failed")
    fail_source(state, sid)
    frozen = build_snapshot(store, run["research_id"], run["target"]["table_id"],
                            report_ready(store, run["research_id"], run["target"]["table_id"], True))
    updated = copy.deepcopy(old)
    updated["report_target"]["limitations_core"] = review_methodology.limitations_core(store, reports, report, frozen)
    assert contracts.check_step_input(updated) == []
    for field, value in (("key", "truncation"), ("number", 7)):
        bad = copy.deepcopy(updated)
        bad["report_target"]["limitations_core"]["items"][7][field] = value
        assert "step_input_schema_invalid" in {i.code for i in contracts.check_step_input(bad)}
    # D234 adds the all-abstract access limitation; failed-row input rules stay fixed.
    assert skill.load_skill_package().package_hash == "sha256:ddacd99a2e904bc9e64488cb416615ff22b48310719317e60dfcc5747706cd04"


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
    frozen = snapshot(state)
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


def test_existing_assembly_rule_rejects_failed_source_citation(state):
    _, store, reports, _, run, _, report = state
    sid = add_source(state, "SYNTHETIC failed")
    fail_source(state, sid)
    snapshot(state)
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
    assert set(old) == {"table_revision", "columns", "rows", "cells", "corpus"}
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
                    "corpus": {"found": 0, "unique": 1, "screened": 0, "included": 1, "full_text": 0}}
    assert old == expected_old
    assert reports.save_snapshot(report, table, True) == old
    assert reports.save_snapshot(report, table) == old
    asyncio.run(sections.run_report(flow, run, scope))
    view = report_view(store, rid, report)
    before = to_markdown(view, title="SYNTHETIC", corpus=old["corpus"])
    ii = reports.section(report, "II")
    viii = reports.section(report, "VIII")
    assert "rows" not in ii["validation"]["numbers"]
    core = viii["validation"]["numbers"]
    assert "failed_rows" not in core and len(core["items"]) == 7
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


def test_api_requires_explicit_choice_and_completes_flagged_report(tmp_path):
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
        refused = client.post(url, json={"table_id": table_id})
        assert refused.status_code == 409 and REFUSAL in refused.text
        accepted = client.post(url, json={"table_id": table_id, "continue_with_failed": True})
        assert accepted.status_code == 202, accepted.text
        assert accepted.json()["target"]["continue_with_failed"] is True
        _, done = wait_run(client, rid, accepted.json()["id"])
        assert done["status"] == "completed", done
        assert client.get(f"{url}/{accepted.json()['target']['report_id']}").json()["missing_rows"] is not None


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
    readiness = report_ready(store, rid, table, True)
    assert readiness["ready"] and readiness["failed_rows"] == [failed] and len(readiness["missing"]) == 3
    assert store.conn.execute("SELECT COUNT(*) FROM cell_revisions r JOIN evidence_cells c ON c.id = r.cell_id"
                              " WHERE c.source_version_id = ?", (failed,)).fetchone()[0] == 0
