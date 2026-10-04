"""Synthetic report persistence; no report run or model is executed."""

import sqlite3

import pytest

from deixis.domain.rules import RevisionConflict
from deixis.storage import db
from deixis.storage.db import new_id
from deixis.workflow.report.store import ReportStore
from deixis.workflow.store import NotFound, Store
from deixis.workflow.tables import InvalidTableInput, TableStore
from deixis.workflow.views import report_view
from test_report_flow import report_flow


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


def test_purge_research_removes_finished_report_and_dependents(lib):
    """A finished report must not hold a trashed research in the database."""
    store, reports, research_id, _ = lib
    report_id, _, (claim_id,) = _finished_claim(lib)
    reports.edit_claim(research_id, report_id, claim_id, text="SYNTHETIC human text", restore_from=None,
                       note=None, expected_version=1, idempotency_key=None)
    store.conn.execute("INSERT INTO report_stale_acknowledgements VALUES (?, ?, ?, ?, ?)",
                       ("rsa_purge", report_id, "IV", "cell:synthetic:changed", "2026-09-29T00:00:00Z"))
    store.trash_research(research_id)

    store.purge_research(research_id)

    assert store.conn.execute("SELECT COUNT(*) FROM reports WHERE research_id = ?", (research_id,)).fetchone()[0] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM report_claim_revisions").fetchone()[0] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM report_stale_acknowledgements").fetchone()[0] == 0


def _finished_claim(lib, *, count=None, second=False):
    store, reports, research_id, run_id = lib
    report_id = reports.create_report(research_id, run_id, 1, "en")
    section_id = reports.create_section(report_id, "IV", 1)
    claims = [{"claim_key": f"IV.{n}", "paragraph": n, "text": f"SYNTHETIC model {n}",
               "support_type": "analyst_inference", "count": count if n == 1 else None}
              for n in range(1, 3 if second else 2)]
    reports.save_claims(section_id, claims, [])
    reports.save_section_draft(section_id, store.step(run_id, "report:IV", "model:report_section")["id"],
                               "valid", {"claims": claims}, {"issues": []}, 4)
    reports.finalize(report_id, "valid")
    store.update_run(run_id, status="completed")
    claim_ids = [r[0] for r in store.conn.execute(
        "SELECT id FROM report_claims WHERE report_section_id = ? ORDER BY ordinal", (section_id,))]
    return report_id, section_id, claim_ids


def test_report_revision_tables_are_append_only_except_authorized_purge(lib):
    store, reports, research_id, _ = lib
    report_id, section_id, (claim_id,) = _finished_claim(lib)
    columns = {r[1] for r in store.conn.execute("PRAGMA table_info(report_claims)")}
    assert {"current_revision_id", "version"} <= columns
    for table in ("report_claim_revisions", "report_stale_acknowledgements"):
        assert store.conn.execute("SELECT name FROM sqlite_master WHERE name = ?", (table,)).fetchone()
    revision_id = reports.edit_claim(research_id, report_id, claim_id, text="Human text", restore_from=None,
                                     note=None, expected_version=1, idempotency_key=None)
    store.conn.execute("INSERT INTO report_stale_acknowledgements VALUES (?, ?, ?, ?, ?)",
                       ("rsa_test", report_id, "IV", "cell:test:revision", "2026-09-29T00:00:00Z"))
    for table, row_id in (("report_claim_revisions", revision_id), ("report_stale_acknowledgements", "rsa_test")):
        with pytest.raises(sqlite3.IntegrityError):
            store.conn.execute(f"UPDATE {table} SET created_at = created_at WHERE id = ?", (row_id,))
        with pytest.raises(sqlite3.IntegrityError):
            store.conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
    store.conn.execute("INSERT INTO research_purge_authorizations VALUES (?)", (research_id,))
    store.conn.execute("UPDATE report_claims SET current_revision_id = NULL WHERE id = ?", (claim_id,))
    store.conn.execute("DELETE FROM report_claim_revisions WHERE id = ?", (revision_id,))
    store.conn.execute("DELETE FROM report_stale_acknowledgements WHERE id = 'rsa_test'")


def test_edit_history_restore_warnings_and_replay(lib):
    store, reports, research_id, _ = lib
    report_id, section_id, (first, second) = _finished_claim(lib, count={"value": 2}, second=True)
    revision = reports.edit_claim(research_id, report_id, first, text="Human $\\frac{a$ text", restore_from=None,
                                  note="reason", expected_version=1, idempotency_key="once")
    assert reports.edit_claim(research_id, report_id, first, text="Human $\\frac{a$ text", restore_from=None,
                              note="reason", expected_version=1, idempotency_key="once") == revision
    with pytest.raises(RevisionConflict, match="different edit"):
        reports.edit_claim(research_id, report_id, first, text="ignored", restore_from=None,
                           note=None, expected_version=1, idempotency_key="once")
    with pytest.raises(RevisionConflict):
        reports.edit_claim(research_id, report_id, second, text="other", restore_from=None,
                           note=None, expected_version=1, idempotency_key="once")
    with pytest.raises(RevisionConflict):
        reports.edit_claim(research_id, report_id, first, text="stale", restore_from=None,
                           note=None, expected_version=1, idempotency_key=None)
    view = report_view(store, research_id, report_id)
    claim = view["sections"][0]["claims"][0]
    assert (claim["text"], claim["model_text"], claim["version"], claim["edited"]) == (
        "Human $\\frac{a$ text", "SYNTHETIC model 1", 2, True)
    assert {w["kind"] for w in claim["warnings"]} == {"math_not_well_formed", "count_not_rechecked"}
    assert view["edited_after_version"] == view["report_version"] == 1
    assert store.conn.execute("SELECT COUNT(*) FROM events WHERE research_id = ? AND type = 'report_claim_edited'",
                              (research_id,)).fetchone()[0] == 1
    with pytest.raises(RevisionConflict):
        reports.save_claims(section_id, [], [])
    assert store.conn.execute("SELECT COUNT(*) FROM report_claims WHERE report_section_id = ?", (section_id,)).fetchone()[0] == 2
    reports.edit_claim(research_id, report_id, first, text=None, restore_from="model", note=None,
                       expected_version=2, idempotency_key=None)
    reports.edit_claim(research_id, report_id, first, text=None, restore_from=revision, note=None,
                       expected_version=3, idempotency_key=None)
    assert [r["kind"] for r in reports.claim_revisions(first)] == ["human_edit", "human_restore", "human_restore"]
    for text, restore in (("", None), ("same", "model"), (None, None), (None, "missing"),
                          ("Human $\\frac{a$ text", None)):
        with pytest.raises(InvalidTableInput):
            reports.edit_claim(research_id, report_id, first, text=text, restore_from=restore, note=None,
                               expected_version=4, idempotency_key=None)
    other_revision = reports.edit_claim(research_id, report_id, second, text="Other human", restore_from=None,
                                        note=None, expected_version=1, idempotency_key=None)
    with pytest.raises(InvalidTableInput):
        reports.edit_claim(research_id, report_id, first, text=None, restore_from=other_revision, note=None,
                           expected_version=4, idempotency_key=None)


def test_edit_waits_for_terminal_report_run(lib):
    store, reports, research_id, run_id = lib
    report_id = reports.create_report(research_id, run_id, 1, "en")
    section_id = reports.create_section(report_id, "IV", 1)
    reports.save_claims(section_id, [{"claim_key": "IV.1", "paragraph": 1, "text": "Model",
                                     "support_type": "analyst_inference"}], [])
    claim_id = store.conn.execute("SELECT id FROM report_claims").fetchone()[0]
    with pytest.raises(RevisionConflict, match="run has finished"):
        reports.edit_claim(research_id, report_id, claim_id, text="Human", restore_from=None,
                           note=None, expected_version=1, idempotency_key=None)


def test_report_without_snapshot_has_no_measured_changes(lib):
    _, reports, research_id, run_id = lib
    report_id = reports.create_report(research_id, run_id, 1, "en")
    reports.create_section(report_id, "IV", 1)
    changes = reports.evidence_changes(report_id)
    assert changes["any"] is False
    assert changes["changed_cells"] == changes["removed_sources"] == changes["added_sources"] == 0
    assert changes["sections"]["IV"]["open"] == []


def _snapshot_report(tmp_path, *, change_before_claims=False):
    _, store, reports, _, run, _, report_id = report_flow(tmp_path)
    research_id = run["research_id"]
    table_id = reports.snapshot(report_id)["table_id"] if store.conn.execute(
        "SELECT 1 FROM report_snapshot WHERE report_id = ?", (report_id,)).fetchone() else None
    if table_id is None:
        table_id = store.conn.execute("SELECT id FROM evidence_tables WHERE research_id = ?", (research_id,)).fetchone()[0]
        reports.save_snapshot(report_id, table_id)
    cell = dict(store.conn.execute("SELECT * FROM evidence_cells WHERE table_id = ? LIMIT 1", (table_id,)).fetchone())
    if change_before_claims:
        TableStore(store).edit_cell(research_id, table_id, cell["column_id"], cell["source_version_id"],
                                    "not_verified", {"text": "SYNTHETIC new value"}, None, None, cell["version"], None)
    input_id = store.conn.execute("SELECT id FROM step_inputs WHERE research_id = ? LIMIT 1", (research_id,)).fetchone()[0]
    passage_id = store.passages_for(cell["source_version_id"])[0]["id"]
    for ordinal, section_name in enumerate(("IV", "V", "abstract", "VI"), 1):
        section = reports.create_section(report_id, section_name, ordinal)
        claim = {"claim_key": f"{section_name}.1", "paragraph": 1, "text": "SYNTHETIC claim",
                 "support_type": "analyst_inference", "body_refs": ["IV.1"] if section_name == "abstract" else [],
                 "gap_refs": ["gap1"] if section_name == "VI" else []}
        links = [{"claim_key": "IV.1", "cell_id": cell["id"],
                  "source_version_id": cell["source_version_id"], "step_input_id": input_id,
                  "anchor_text": "SYNTHETIC evidence", "anchor_match": "exact"}] if section_name == "IV" else []
        if section_name == "V":
            links = [{"claim_key": "V.1", "passage_id": passage_id,
                      "source_version_id": cell["source_version_id"], "step_input_id": input_id,
                      "anchor_text": "SYNTHETIC evidence", "anchor_match": "exact"}]
        reports.save_claims(section, [claim], links)
    reports.save_gaps(report_id, [{"gap_id": "gap1", "kind": "corpus_absence", "text": "SYNTHETIC gap",
                                   "basis_cell_ids": [cell["id"]], "provenance": {"search_date": "2026-09-29"}}])
    store.update_run(run["id"], status="completed")
    return store, reports, research_id, report_id, table_id, cell


@pytest.mark.parametrize("change_before_claims", [False, True])
def test_changed_snapshot_cell_reaches_only_direct_and_one_level_refs(tmp_path, change_before_claims):
    store, reports, research_id, report_id, table_id, cell = _snapshot_report(
        tmp_path, change_before_claims=change_before_claims)
    if not change_before_claims:
        TableStore(store).edit_cell(research_id, table_id, cell["column_id"], cell["source_version_id"],
                                    "not_verified", {"text": "SYNTHETIC new value"}, None, None, cell["version"], None)
    changes = reports.evidence_changes(report_id)
    assert changes["changed_cells"] == 1
    assert changes["not_checked"] == ["passages"]
    assert [(c["kind"], c["via"]) for c in changes["sections"]["IV"]["open"]] == [("cell_changed", "citation")]
    assert [(c["kind"], c["via"]) for c in changes["sections"]["abstract"]["open"]] == [("cell_changed", "body_ref")]
    assert [(c["kind"], c["via"]) for c in changes["sections"]["VI"]["open"]] == [("cell_changed", "gap_ref")]
    assert changes["sections"]["V"]["open"] == []


def test_trashed_research_acknowledges_nothing_then_restored_research_acknowledges(tmp_path):
    store, reports, research_id, report_id, table_id, cell = _snapshot_report(tmp_path)
    TableStore(store).edit_cell(research_id, table_id, cell["column_id"], cell["source_version_id"],
                                "not_verified", {"text": "SYNTHETIC changed"}, None, None, cell["version"], None)
    key = reports.evidence_changes(report_id)["sections"]["IV"]["open"][0]["key"]
    store.trash_research(research_id)
    before = [tuple(row) for row in store.conn.execute("SELECT * FROM events ORDER BY id")]
    with pytest.raises(NotFound):
        reports.acknowledge_changes(research_id, report_id, "IV", [key])
    assert store.conn.execute("SELECT COUNT(*) FROM report_stale_acknowledgements").fetchone()[0] == 0
    assert [tuple(row) for row in store.conn.execute("SELECT * FROM events ORDER BY id")] == before
    store.restore_research(research_id)
    assert reports.acknowledge_changes(research_id, report_id, "IV", [key]) == 1
    assert reports.evidence_changes(report_id)["sections"]["IV"]["acknowledged_count"] == 1
    assert store.conn.execute("SELECT COUNT(*) FROM events WHERE type = 'report_changes_acknowledged'").fetchone()[0] == 1


def test_acknowledged_cell_change_reopens_on_a_new_revision(tmp_path):
    store, reports, research_id, report_id, table_id, cell = _snapshot_report(tmp_path)
    tables = TableStore(store)
    tables.edit_cell(research_id, table_id, cell["column_id"], cell["source_version_id"], "not_verified",
                     {"text": "SYNTHETIC changed"}, None, None, cell["version"], None)
    key = reports.evidence_changes(report_id)["sections"]["IV"]["open"][0]["key"]
    with pytest.raises(RevisionConflict):
        reports.acknowledge_changes(research_id, report_id, "IV", [key, "unknown"])
    assert store.conn.execute("SELECT COUNT(*) FROM report_stale_acknowledgements").fetchone()[0] == 0
    assert reports.acknowledge_changes(research_id, report_id, "IV", [key]) == 1
    assert reports.evidence_changes(report_id)["sections"]["IV"]["acknowledged_count"] == 1
    with pytest.raises(RevisionConflict):
        reports.acknowledge_changes(research_id, report_id, "IV", [key])
    tables.edit_cell(research_id, table_id, cell["column_id"], cell["source_version_id"], "not_verified",
                     {"text": "SYNTHETIC changed again"}, None, None, cell["version"] + 1, None)
    new_change = reports.evidence_changes(report_id)["sections"]["IV"]["open"][0]
    assert new_change["key"] != key
    with pytest.raises(RevisionConflict):
        reports.acknowledge_changes(research_id, report_id, "IV", [key])


def test_gap_claim_basis_uses_that_claims_direct_changes(tmp_path):
    store, reports, research_id, report_id, table_id, cell = _snapshot_report(tmp_path)
    reports.save_gaps(report_id, [{"gap_id": "gap1", "kind": "corpus_absence", "text": "SYNTHETIC gap",
                                   "basis_cell_ids": [], "basis_claim_keys": ["IV.1"],
                                   "provenance": {"search_date": "2026-09-29"}}])
    TableStore(store).edit_cell(research_id, table_id, cell["column_id"], cell["source_version_id"],
                                "not_verified", {"text": "SYNTHETIC changed"}, None, None, cell["version"], None)
    changes = reports.evidence_changes(report_id)
    assert [(change["kind"], change["via"]) for change in changes["sections"]["VI"]["open"]] == [
        ("cell_changed", "gap_ref")]
    assert changes["sections"]["VI"]["unresolved_refs"] == 0


def test_unresolved_reference_is_counted_without_guessing_a_change(tmp_path):
    store, reports, _, report_id, _, _ = _snapshot_report(tmp_path)
    claim_id = store.conn.execute(
        "SELECT c.id FROM report_claims c JOIN report_sections s ON s.id = c.report_section_id"
        " WHERE s.report_id = ? AND s.section_id = 'V'", (report_id,),
    ).fetchone()[0]
    store.conn.execute("INSERT INTO report_claim_refs VALUES (?, 'body_ref', 'missing.claim')", (claim_id,))
    changes = reports.evidence_changes(report_id)["sections"]["V"]
    assert changes["unresolved_refs"] == 1
    assert changes["open"] == []


def test_row_departure_acknowledgement_does_not_hide_later_departure(tmp_path):
    store, reports, research_id, report_id, table_id, cell = _snapshot_report(tmp_path)
    tables = TableStore(store)
    tables.remove_row(research_id, table_id, cell["source_version_id"],
                      tables._table(research_id, table_id)["version"])
    store.conn.execute("UPDATE table_rows SET removed_at = ? WHERE table_id = ? AND source_version_id = ?",
                       ("2026-09-29T00:00:00.001Z", table_id, cell["source_version_id"]))
    first = reports.evidence_changes(report_id)
    assert first["removed_sources"] == 1
    key = first["sections"]["IV"]["open"][0]["key"]
    reports.acknowledge_changes(research_id, report_id, "IV", [key])
    tables.add_rows(research_id, table_id, [cell["source_version_id"]],
                    tables._table(research_id, table_id)["version"])
    assert reports.evidence_changes(report_id)["removed_sources"] == 0
    tables.remove_row(research_id, table_id, cell["source_version_id"],
                      tables._table(research_id, table_id)["version"])
    store.conn.execute("UPDATE table_rows SET removed_at = ? WHERE table_id = ? AND source_version_id = ?",
                       ("2026-09-29T00:00:00.002Z", table_id, cell["source_version_id"]))
    second = reports.evidence_changes(report_id)
    assert second["sections"]["IV"]["open"][0]["key"] != key


def test_exclusion_and_table_row_removal_both_remove_snapshot_source(tmp_path):
    store, reports, research_id, report_id, table_id, cell = _snapshot_report(tmp_path)
    source_id = cell["source_version_id"]
    selection = store.conn.execute("SELECT version FROM selections WHERE research_id = ? AND source_version_id = ?",
                                   (research_id, source_id)).fetchone()
    store.set_user_selection(research_id, source_id, "excluded", selection["version"], "SYNTHETIC exclusion")
    excluded = reports.evidence_changes(report_id)
    assert excluded["removed_sources"] == 1
    assert excluded["sections"]["IV"]["open"][0]["kind"] == "source_removed"
    assert excluded["sections"]["V"]["open"][0]["kind"] == "source_removed"
    store.set_user_selection(research_id, source_id, "included", selection["version"] + 1, None)
    assert reports.evidence_changes(report_id)["removed_sources"] == 0
    tables = TableStore(store)
    tables.remove_row(research_id, table_id, source_id, tables._table(research_id, table_id)["version"])
    removed = reports.evidence_changes(report_id)
    assert removed["removed_sources"] == 1
    assert removed["sections"]["IV"]["open"][0]["kind"] == "source_removed"
    tables.add_rows(research_id, table_id, [source_id], tables._table(research_id, table_id)["version"])
    assert reports.evidence_changes(report_id)["removed_sources"] == 0
    store.remove_sources(research_id, [source_id], "SYNTHETIC removal")
    membership = reports.evidence_changes(report_id)
    assert membership["removed_sources"] == 1
    assert membership["sections"]["IV"]["open"][0]["key"].startswith(f"source:{source_id}:")


def test_new_and_preincluded_table_rows_are_both_counted_as_added(tmp_path):
    _, store, reports, _, run, _, report_id = report_flow(tmp_path)
    research_id = run["research_id"]
    table_id = store.conn.execute("SELECT id FROM evidence_tables WHERE research_id = ?", (research_id,)).fetchone()[0]
    first = store.create_upload_source("SYNTHETIC already included")
    store.add_to_corpus(research_id, first, "user_upload", selection_state="included", selection_origin="user")
    reports.save_snapshot(report_id, table_id)
    tables = TableStore(store)
    tables.add_rows(research_id, table_id, [first], tables._table(research_id, table_id)["version"])
    assert reports.evidence_changes(report_id)["added_sources"] == 1
    second = store.create_upload_source("SYNTHETIC newly included")
    store.add_to_corpus(research_id, second, "user_upload", selection_state="included", selection_origin="user")
    tables.add_rows(research_id, table_id, [second], tables._table(research_id, table_id)["version"])
    assert reports.evidence_changes(report_id)["added_sources"] == 2


def test_revised_or_removed_snapshot_column_is_report_level_only(tmp_path):
    store, reports, research_id, report_id, table_id, cell = _snapshot_report(tmp_path)
    tables = TableStore(store)
    column = tables._column(table_id, cell["column_id"])
    tables.revise_column(research_id, table_id, cell["column_id"], {"instruction": "SYNTHETIC revised"},
                         None, column["version"])
    changes = reports.evidence_changes(report_id)
    assert changes["revised_columns"] == 1
    assert changes["sections"]["IV"]["open"] == []
    tables.remove_column(research_id, table_id, cell["column_id"], column["version"] + 1)
    assert reports.evidence_changes(report_id)["revised_columns"] == 1


def test_report_remains_readable_with_trashed_table_but_table_purge_is_blocked(tmp_path):
    store, reports, research_id, report_id, table_id, _ = _snapshot_report(tmp_path)
    tables = TableStore(store)
    tables.trash_table(research_id, table_id, tables._table(research_id, table_id)["version"])
    assert reports.evidence_changes(report_id)["any"] is False
    with pytest.raises(sqlite3.IntegrityError):
        tables.purge_table(table_id)
    assert store.conn.execute("SELECT 1 FROM evidence_tables WHERE id = ?", (table_id,)).fetchone()
