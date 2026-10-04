"""Synthetic rows and fake step inputs; no model, provider or network.

This deterministic sequence shows how stored pieces behave in one order,
not how a real report reads or whether its evidence supports its claims.
"""

import ast
from contextlib import contextmanager
from pathlib import Path

import pytest

from deixis.config import Settings
from deixis.domain.rules import RevisionConflict
from deixis.storage import db
from deixis.storage.backup import create_backup, restore_backup
from deixis.storage.db import new_id
from deixis.workflow.report.export import export_markdown
from deixis.workflow.report.store import ReportStore
from deixis.workflow.store import Store
from deixis.workflow.tables import TableStore
from deixis.workflow.views import report_view
from tests.report.test_report_assembly import report_with_sections, _add_claim, _gap, _link
from tests.report.test_report_claim_links import assert_only_report_cites, claim, edit, rows, view_claim
from tests.report.test_report_edit_check import check, current, finish


REPORT_TABLES = (
    "report_claim_revisions", "report_claim_revision_links", "report_citation_links",
    "report_claims", "reports", "report_sections", "report_claim_refs", "report_gaps",
    "report_snapshot", "report_edit_checks", "report_stale_acknowledgements", "events",
)
PURGE_GUARD_TABLES = (
    "report_citation_links", "report_claim_revisions", "source_versions", "events",
)
NO_CHECKED_SUPPORT = ["semantic_support", "numbers_written_as_words", "passages"]
ZERO_LINK_SKIPS = [
    {"rule": "phrase_frames", "section_id": "III", "claim_key": "III.1", "reason": "human_text"},
    {"rule": "derived_depth_not_checked", "section_id": "abstract", "claim_key": "abstract.1",
     "reason": "no_citation_depth"},
]


@pytest.fixture(autouse=True)
def no_socket_or_http(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("The synthetic edit sequence must not use sockets or HTTP")

    for target in ("socket.socket.connect", "socket.create_connection",
                   "httpx.Client.send", "httpx.AsyncClient.send"):
        monkeypatch.setattr(target, forbidden)


@pytest.fixture
def sequence_library(tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    settings.data_dir.mkdir()
    generator = report_with_sections.__wrapped__(settings.data_dir)
    lib = next(generator)
    try:
        _add_claim(lib, "III", "III.1", "Resource allocation assigns capacity.", links=[
            _link(lib, "III.1", passage=False), _link(lib, "III.1"),
        ])
        _add_claim(lib, "IV", "IV.1", "SYNTHETIC retained basis.", links=[_link(lib, passage=False)])
        _add_claim(lib, "VI", "VI.1", "SYNTHETIC stated limitation.", gap_refs=["gap1"])
        # A passage supplies the stated limitation's required basis without adding
        # an independent cell basis that would bypass III.1's effective links.
        _gap(lib, "stated_limitation", claim_keys=["III.1"], passage_ids=[lib["section_passage"]])
        lib["research_id"] = finish(lib)
        lib["settings"] = settings
        lib["all_link_ids"] = [r[0] for r in lib["store"].conn.execute("SELECT id FROM report_citation_links ORDER BY rowid")]
        lib["L_cell"], lib["L_pass"] = [r["id"] for r in lib["reports"].original_links(claim(lib)["id"])]
        lib["expected_runs"] = {r["id"]: r["kind"] for r in lib["store"].conn.execute("SELECT id, kind FROM runs")}
        lib["expected_inputs"] = {r["id"]: (r["run_id"], r["step_id"]) for r in
                                  lib["store"].conn.execute("SELECT id, run_id, step_id FROM step_inputs")}
        yield lib
    finally:
        with pytest.raises(StopIteration):
            next(generator)


def _table_state(conn, tables=REPORT_TABLES):
    return {table: rows(conn, table) for table in tables}


def _base_state(lib):
    report = lib["reports"].report(lib["report_id"])
    return {
        "links": sorted((tuple(r) for r in lib["store"].conn.execute(
            "SELECT l.* FROM report_citation_links l JOIN report_claims c ON c.id = l.claim_id"
            " JOIN report_sections s ON s.id = c.report_section_id WHERE s.report_id = ?",
            (lib["report_id"],),
        )), key=repr),
        "report": {key: report[key] for key in ("status", "report_version", "review")},
        "sections": [(s["section_id"], s["status"], s["validation"], s["word_count"], s["draft"])
                     for s in lib["reports"].sections(lib["report_id"])],
    }


def _view(lib):
    return report_view(lib["store"], lib["research_id"], lib["report_id"])


def _cell(lib):
    return dict(lib["store"].conn.execute("SELECT * FROM evidence_cells WHERE id = ?", (lib["cell_id"],)).fetchone())


def _recheck_proposal(lib, ordinal):
    """Store fake extraction input/output directly; never execute a run."""
    store = lib["store"]
    cell = _cell(lib)
    run = store.create_run(lib["research_id"], "cell_recheck", {}, None)
    step = store.step(run["id"], f"synthetic:recheck:{ordinal}", "model:cell_extraction")
    input_id = new_id("sti")
    store.insert_step_input(
        step["id"], lib["research_id"], run["id"], 0,
        {"step_input_id": input_id, "task_type": "cell_extraction", "scope_revision": 1,
         "skill_package_hash": "sha256:synthetic"}, "base", "developer", "message", {},
    )
    proposal = TableStore(store).save_model_output(
        lib["research_id"], cell["table_id"], cell["column_id"], lib["source_id"],
        column_revision=1, state="value", value={"text": f"SYNTHETIC recheck {ordinal}"},
        note=None, reading_depth="full_text", output_status="structurally_valid",
        links=[{"passage_id": lib["section_passage"], "source_version_id": lib["source_id"],
                "anchor_text": "selected-section evidence", "anchor_match": "exact"}],
        run_id=run["id"], step_id=step["id"], step_input_id=input_id,
        model_connection="fake", resolved_model="fake-model", scope_revision=1,
        cell_version_at_request=cell["version"], recheck=True,
    )
    lib["expected_runs"][run["id"]] = "cell_recheck"
    lib["expected_inputs"][input_id] = (run["id"], step["id"])
    return run["id"], proposal


def _accept_recheck(lib, proposal):
    cell = _cell(lib)
    return TableStore(lib["store"]).decide_proposal(
        lib["research_id"], cell["table_id"], cell["column_id"], lib["source_id"],
        proposal, True, cell["version"], None,
    )


def _active_runs(lib):
    return lib["store"].conn.execute(
        "SELECT id FROM runs WHERE research_id = ? AND status IN ('queued', 'running', 'pause_requested')",
        (lib["research_id"],),
    ).fetchall()


def _other_finished_report(lib):
    store, reports = lib["store"], lib["reports"]
    rid = store.create_research("SYNTHETIC other", "attached", "quick", [], "fake", "fake-model", "en")
    store.add_to_corpus(rid, lib["source_id"], "user_upload", selection_state="included", selection_origin="user")
    run = store.create_run(rid, "report", {}, None)
    report = reports.create_report(rid, run["id"], 1, "en")
    section = reports.create_section(report, "IV", 4)
    step = store.step(run["id"], "synthetic:other-report", "model:report_section")
    sti = new_id("sti")
    store.insert_step_input(
        step["id"], rid, run["id"], 0,
        {"step_input_id": sti, "task_type": "report_section", "scope_revision": 1,
         "skill_package_hash": "sha256:synthetic", "passages": [{"passage_id": lib["section_passage"]}]},
        "base", "developer", "message", {},
    )
    reports.save_claims(section, [
        {"claim_key": "IV.other", "paragraph": 1, "text": "SYNTHETIC other.", "support_type": "source_stated"},
    ], [{"claim_key": "IV.other", "passage_id": lib["section_passage"], "source_version_id": lib["source_id"],
         "step_input_id": sti, "anchor_text": "selected-section evidence", "anchor_match": "exact"}])
    store.update_run(run["id"], status="completed")
    reports.finalize(report, "draft")
    cid = store.conn.execute("SELECT id FROM report_claims WHERE report_section_id = ?", (section,)).fetchone()[0]
    reports.edit_claim(rid, report, cid, text="SYNTHETIC other changed.", restore_from=None,
                       note=None, expected_version=1, idempotency_key=None)
    # Rows in the two tables that purge deletes by research, so a missing WHERE would show.
    store.conn.execute("INSERT INTO report_edit_checks (id, report_id, checker_version, input_fingerprint,"
                       " result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                       (new_id("rec"), report, "synthetic", "f" * 64, "{}", "2026-10-02T00:00:00Z"))
    store.conn.execute("INSERT INTO report_stale_acknowledgements VALUES (?, ?, ?, ?, ?)",
                       (new_id("rsa"), report, "IV", "cell:synthetic:other", "2026-10-02T00:00:00Z"))
    assert rows(store.conn, "report_edit_checks") and rows(store.conn, "report_stale_acknowledgements")
    return rid, report


def test_synthetic_scripted_edit_sequence(sequence_library, tmp_path):
    """Fifteen steps on synthetic rows and fake inputs; no scientific validation."""
    lib = sequence_library
    store, reports, rid, report_id = lib["store"], lib["reports"], lib["research_id"], lib["report_id"]
    conn = store.conn
    failures, completed = [], set()

    def soft(step, condition, message):
        if not condition:
            failures.append(f"step {step}: {message}")

    @contextmanager
    def step(number, requires=()):
        missing = set(requires) - completed
        if missing:
            failures.append(f"step {number}: not run; prerequisite steps {sorted(missing)} could not finish")
            yield False
            return
        try:
            yield True
        except Exception as exc:
            failures.append(f"step {number}: {type(exc).__name__}: {exc}; remaining operations in this step not run")
        else:
            completed.add(number)

    def refused(number, call, tables=PURGE_GUARD_TABLES):
        before = _table_state(conn, tables)
        try:
            call()
        except RevisionConflict as exc:
            soft(number, "Evidence still cites" in str(exc), f"wrong purge refusal: {exc}")
        else:
            soft(number, False, "purge did not refuse cited evidence")
        soft(number, _table_state(conn, tables) == before, "refused purge wrote rows or events")

    def marks(number, sid, expected):
        changes = reports.evidence_changes(report_id)["sections"][sid]
        actual = {(m["kind"], m["via"]) for m in changes["open"]}
        soft(number, actual == set(expected) and len(changes["open"]) == len(expected),
             f"{sid} open marks: {changes['open']!r}; expected {expected!r}")
        for mark in changes["open"]:
            soft(number, mark["source_version_id"] == lib["source_id"], f"{sid} mark names another source")
            if mark["kind"] == "cell_changed":
                live = _cell(lib)
                soft(number, mark["cell_id"] == lib["cell_id"] and
                     mark["key"] == f"cell:{lib['cell_id']}:{live['current_revision_id']}", "wrong cell change key")
            elif mark["kind"] == "source_removed":
                stamp = conn.execute("SELECT removed_at FROM corpus_memberships WHERE research_id = ?"
                                     " AND source_version_id = ?", (rid, lib["source_id"])).fetchone()[0]
                soft(number, mark["key"] == f"source:{lib['source_id']}:{stamp}", "wrong source departure key")
        return changes

    # 1. Baseline.
    with step(1) as ready:
        if ready:
            baseline = _base_state(lib)
            original_text = view_claim(lib)["model_text"]
            view = _view(lib)
            soft(1, view["has_human_edits"] is False and view["edit_check"] is None, "baseline edit state")
            soft(1, len(view_claim(lib)["evidence"]) == 2, "baseline citation count")
            soft(1, not view["evidence_changes"]["any"] and view["evidence_changes"]["changed_cells"] == 0,
                 "baseline has evidence changes")
            soft(1, all(not s["evidence_changes"]["open"] for s in view["sections"]), "baseline has open marks")
            soft(1, "Edited by hand" not in export_markdown(store, rid, report_id)[0], "baseline export claims edits")

    # 2. Edit text.
    with step(2, (1,)) as ready:
        if ready:
            revisions = [edit(lib, text="Resource allocation is novel.")]
            view = _view(lib)
            soft(2, view["has_human_edits"] and view["edit_check"] is None and view_claim(lib)["edited"], "edit state")
            soft(2, len(view_claim(lib)["evidence"]) == 2, "text edit changed citations")
            soft(2, f"Edited by hand after version {view['report_version']}; edited text was not checked again."
                 in export_markdown(store, rid, report_id)[0], "unchecked export sentence")

    # 3. Remove one citation, text kept.
    with step(3, (2,)) as ready:
        if ready:
            step3_revision = edit(lib, link_ids=[lib["L_pass"]])
            revisions.append(step3_revision)
            c = view_claim(lib)
            soft(3, [e["link_id"] for e in c["evidence"]] == [lib["L_pass"]] and
                 [e["link_id"] for e in c["removed_links"]] == [lib["L_cell"]], "wrong effective/removed citations")
            soft(3, c["original_evidence_count"] == 2 and c["evidence_basis"] == "direct", "citation basis")
            soft(3, c["text"] == "Resource allocation is novel.", "citation-only edit changed text")
            soft(3, rows(conn, "report_citation_links") == baseline["links"], "original links changed")

    # 4. Change the removed link's cell with a recheck.
    with step(4, (3,)) as ready:
        if ready:
            before_cell = _cell(lib)
            run_id, proposal = _recheck_proposal(lib, 1)
            soft(4, _cell(lib) == before_cell, "proposal changed the cell before acceptance")
            soft(4, conn.execute("SELECT kind FROM cell_revisions WHERE id = ?", (proposal,)).fetchone()[0]
                 == "model_proposal", "recheck is not a proposal")
            soft(4, reports.evidence_changes(report_id)["changed_cells"] == 0, "proposal opened cell staleness")
            _accept_recheck(lib, proposal)
            store.update_run(run_id, status="completed")
            soft(4, not _active_runs(lib), "recheck left an active run")
            soft(4, reports.evidence_changes(report_id)["changed_cells"] == 1, "accepted recheck did not change cell")
            for sid in ("III", "abstract", "VI"):
                marks(4, sid, [])
            marks(4, "IV", [("cell_changed", "citation")])

    # 5. Remove a source from the research; refused purge is read-only.
    with step(5, (4,)) as ready:
        if ready:
            soft(5, not _active_runs(lib), "source removal has an active run")
            store.remove_sources(rid, [lib["source_id"]], "SYNTHETIC first removal")
            marks(5, "III", [("source_removed", "citation")])
            marks(5, "IV", [("cell_changed", "citation"), ("source_removed", "citation")])
            soft(5, _view(lib)["evidence_changes"]["removed_sources"] == 1, "removed-source snapshot count")
            refused(5, lambda: store.purge_sources(rid, [lib["source_id"]]))

    # 6. Check the edits, then replay without any write.
    with step(6, (2,)) as ready:
        if ready:
            events_before = rows(conn, "events")
            check_before = rows(conn, "report_edit_checks")
            base_before = _base_state(lib)
            first = check(lib)
            first_row = tuple(conn.execute("SELECT * FROM report_edit_checks WHERE id = ?", (first["id"],)).fetchone())
            result = _view(lib)["edit_check"]
            soft(6, result["id"] == first["id"] and result["current"], "check not current")
            soft(6, any(i["rule"] == "banned_word" and i["severity"] == "error" and i["section_id"] == "III"
                        and "novel" in i["detail"] for i in result["items"]), "banned word not an error")
            soft(6, isinstance(result["rules_run"], list) and isinstance(result["skipped_rules"], list), "rule list shape")
            soft(6, result["not_checked"] == NO_CHECKED_SUPPORT, "unchecked boundaries")
            soft(6, _base_state(lib) == base_before, "check changed base report/sections/review")
            added = [tuple(r) for r in conn.execute("SELECT * FROM events") if tuple(r) not in events_before]
            soft(6, len(added) == 1 and len(conn.execute("SELECT 1 FROM events WHERE type = 'report_edits_checked'").fetchall()) == 1,
                 "check did not add exactly one report_edits_checked event")
            soft(6, len(rows(conn, "report_edit_checks")) == len(check_before) + 1, "check row count")
            before_replay = _table_state(conn, ("report_edit_checks", "events"))
            soft(6, check(lib)["id"] == first["id"], "replay returned another record")
            soft(6, _table_state(conn, ("report_edit_checks", "events")) == before_replay, "replay wrote rows/events")
            text = export_markdown(store, rid, report_id)[0]
            soft(6, f"the edited text was checked by code rules ({result['created_at']}): {result['errors']} errors, "
                 f"{result['warnings']} warnings; whether the cited evidence supports each sentence was not checked."
                 in text, "checked export sentence/counts")

    # 7. Edit again; the check goes out of date, then a new record is added.
    with step(7, (3, 6)) as ready:
        if ready:
            revisions.append(edit(lib, text="Resource allocation assigns capacity."))
            historical = _view(lib)["edit_check"]
            soft(7, not historical["current"] and historical["id"] == first["id"] and
                 historical["items"] == first["result"]["items"], "historical check lost its original errors")
            soft(7, "does not cover the current inputs" in export_markdown(store, rid, report_id)[0], "stale export sentence")
            second = check(lib)
            soft(7, second["id"] != first["id"] and len(rows(conn, "report_edit_checks")) == 2, "new check not appended")
            soft(7, tuple(conn.execute("SELECT * FROM report_edit_checks WHERE id = ?", (first["id"],)).fetchone()) == first_row,
                 "first check changed bytes")
            soft(7, _view(lib)["edit_check"]["current"] and
                 not any(i["rule"] == "banned_word" for i in second["result"]["items"]), "corrected text still has banned error")

    # 8. A link change alone makes the check out of date.
    with step(8, (5, 7)) as ready:
        if ready:
            text_before = view_claim(lib)["text"]
            revisions.append(edit(lib, link_ids=[]))
            c = view_claim(lib)
            soft(8, c["text"] == text_before and not _view(lib)["edit_check"]["current"], "link-only change/check currency")
            soft(8, not c["evidence"] and c["evidence_basis"] == "none" and c["support_type_note"] == "model_written_type",
                 "zero-link evidence state")
            soft(8, {e["link_id"] for e in c["removed_links"]} == {lib["L_cell"], lib["L_pass"]}, "both removed links missing")
            marks(8, "III", [])
            marks(8, "IV", [("cell_changed", "citation"), ("source_removed", "citation")])
            soft(8, _view(lib)["evidence_changes"]["removed_sources"] == 1, "citation removal changed snapshot count")
            third = check(lib)
            result = _view(lib)["edit_check"]
            soft(8, third["id"] not in (first["id"], second["id"]) and len(rows(conn, "report_edit_checks")) == 3,
                 "citation check not appended")
            soft(8, result["current"] and result["errors"] == 0, "zero citations failed code checks")
            soft(8, result["skipped_rules"] == ZERO_LINK_SKIPS, f"actual skipped rules: {result['skipped_rules']!r}")
            soft(8, current(lib)["skipped"] == ZERO_LINK_SKIPS, "stored and direct skips differ")
            before_replay = _table_state(conn, ("report_edit_checks", "events"))
            soft(8, check(lib)["id"] == third["id"] and _view(lib)["edit_check"]["skipped_rules"] == ZERO_LINK_SKIPS,
                 "zero-link replay/skip stability")
            soft(8, _table_state(conn, ("report_edit_checks", "events")) == before_replay, "zero-link replay wrote")

    # 9. Keep only the cell change as is, restore membership, then change and remove again.
    with step(9, (8,)) as ready:
        if ready:
            open_iv = reports.evidence_changes(report_id)["sections"]["IV"]["open"]
            old_key = next(m["key"] for m in open_iv if m["kind"] == "cell_changed")
            before_ack = _view(lib)["edit_check"]
            soft(9, reports.acknowledge_changes(rid, report_id, "IV", [old_key]) == 1, "acknowledgement count")
            iv = marks(9, "IV", [("source_removed", "citation")])
            soft(9, iv["acknowledged_count"] == 1, "acknowledged cell not counted")
            soft(9, _view(lib)["edit_check"] == before_ack and before_ack["current"], "acknowledgement changed check currency")
            before_repeat = _table_state(conn)
            try:
                reports.acknowledge_changes(rid, report_id, "IV", [old_key])
            except RevisionConflict:
                pass
            else:
                soft(9, False, "acknowledgement replay accepted")
            soft(9, _table_state(conn) == before_repeat, "refused acknowledgement wrote")
            soft(9, not _active_runs(lib), "membership restore has an active run")
            store.restore_sources(rid, [lib["source_id"]])
            before_cell = _cell(lib)
            run_id, proposal = _recheck_proposal(lib, 2)
            soft(9, _cell(lib) == before_cell, "second proposal changed cell before acceptance")
            _accept_recheck(lib, proposal)
            store.update_run(run_id, status="completed")
            soft(9, not _active_runs(lib), "second recheck left an active run")
            iv = marks(9, "IV", [("cell_changed", "citation")])
            new_key = next(m["key"] for m in iv["open"] if m["kind"] == "cell_changed")
            soft(9, new_key != old_key and iv["acknowledged_count"] == 0, "new cell change inherited acknowledgement")
            before_old_key = _table_state(conn)
            try:
                reports.acknowledge_changes(rid, report_id, "IV", [old_key])
            except RevisionConflict:
                pass
            else:
                soft(9, False, "old key accepted for a new change")
            soft(9, _table_state(conn) == before_old_key, "old-key refusal wrote")
            store.remove_sources(rid, [lib["source_id"]], "SYNTHETIC second removal")
            marks(9, "IV", [("cell_changed", "citation"), ("source_removed", "citation")])

    # 10. Restore the model's version, then step 3's text and set together.
    with step(10, (9,)) as ready:
        if ready:
            revisions.append(edit(lib, restore_from="model"))
            c = view_claim(lib)
            soft(10, c["text"] == original_text and len(c["evidence"]) == 2 and not c["removed_links"], "model restore")
            marks(10, "abstract", [("cell_changed", "body_ref"), ("source_removed", "citation")])
            marks(10, "III", [("cell_changed", "citation"), ("source_removed", "citation")])
            marks(10, "VI", [("cell_changed", "gap_ref"), ("source_removed", "gap_ref")])
            soft(10, not _view(lib)["edit_check"]["current"], "restore left check current")
            soft(10, [r["id"] for r in c["revisions"]] == revisions, "history not oldest-first/complete")
            soft(10, [r["link_count"] for r in c["revisions"]] == [2, 1, 1, 0, 2], "model-restore link_count series")
            soft(10, [r["changes_current"] for r in c["revisions"]] == [True, True, True, True, False], "model-restore history flags")
            revisions.append(edit(lib, restore_from=step3_revision))
            c = view_claim(lib)
            soft(10, c["text"] == "Resource allocation is novel." and
                 [e["link_id"] for e in c["evidence"]] == [lib["L_pass"]], "step 3 restore lost text/set")
            soft(10, [r["id"] for r in c["revisions"]] == revisions and
                 [r["link_count"] for r in c["revisions"]] == [2, 1, 1, 0, 2, 1], "final revision series")
            soft(10, [r["changes_current"] for r in c["revisions"]] == [True, False, True, True, True, False],
                 "equivalent prior revision still offered for restore")

    # 11. Restore source membership; only the retained cell marks remain.
    with step(11, (10,)) as ready:
        if ready:
            soft(11, not _active_runs(lib), "source restore has an active run")
            store.restore_sources(rid, [lib["source_id"]])
            changes = reports.evidence_changes(report_id)
            soft(11, changes["removed_sources"] == 0 and changes["changed_cells"] == 1, "source/cell totals after restore")
            soft(11, all(m["kind"] != "source_removed" for s in changes["sections"].values() for m in s["open"]),
                 "source restore left departure marks")
            for sid in ("III", "abstract", "VI"):
                soft(11, not any(m["kind"] == "cell_changed" for m in changes["sections"][sid]["open"]),
                     f"{sid} cites the removed cell after step 3 restore")
            marks(11, "IV", [("cell_changed", "citation")])
            before_noop = _table_state(conn, PURGE_GUARD_TABLES)
            soft(11, store.purge_sources(rid, [lib["source_id"]]) == ([], [], []), "active membership purge is not a no-op")
            soft(11, _table_state(conn, PURGE_GUARD_TABLES) == before_noop, "active membership purge wrote")

    # 12. Original links and the model's base status/version/sections/review are untouched.
    with step(12, (1,)) as ready:
        if ready:
            soft(12, rows(conn, "report_citation_links") == baseline["links"], "original links differ byte for byte")
            soft(12, _base_state(lib) == baseline, "base report/sections/review changed during the sequence")

    # 13. Export with a citation set present, using only its effective reference numbers.
    with step(13, (10,)) as ready:
        if ready:
            text, filename = export_markdown(store, rid, report_id)
            c = view_claim(lib)
            numbers = list(dict.fromkeys(e["ref_number"] for e in c["evidence"]))
            soft(13, "Edited by hand" in text and filename.endswith(".md"), "edited export missing")
            body = text.split("## III.", 1)[1].split("## IV.", 1)[0]
            soft(13, body.strip().endswith(c["text"] + " " + ", ".join(f"[{n}]" for n in numbers)),
                 "III.1 reference numbers differ from view")
            soft(13, [r["number"] for r in _view(lib)["references"]] == [1] and numbers == [1], "unexpected effective references")

    # 14. Backup and restore every report table and its derived read state.
    with step(14, (1,)) as ready:
        if ready:
            soft(14, rows(conn, "source_assets") == [], "synthetic library has assets")
            before = _table_state(conn)
            before_effective, before_check = reports.effective_links(report_id), _view(lib)["edit_check"]
            lib["sequence_runs"] = [dict(r) for r in conn.execute("SELECT * FROM runs ORDER BY rowid")]
            lib["sequence_inputs"] = [dict(r) for r in conn.execute("SELECT * FROM step_inputs ORDER BY rowid")]
            backup = create_backup(lib["settings"], tmp_path / "backups")
            restored_settings = Settings(data_dir=tmp_path / "restored")
            restore_backup(backup, restored_settings)
            restored_conn = db.connect(restored_settings.db_path)
            try:
                db.migrate(restored_conn)
                restored_store = Store(restored_conn)
                soft(14, _table_state(restored_conn) == before, "backup report tables differ row for row")
                soft(14, restored_conn.execute("PRAGMA foreign_key_check").fetchall() == [], "restored foreign key violations")
                soft(14, ReportStore(restored_store).effective_links(report_id) == before_effective, "restored effective links differ")
                soft(14, report_view(restored_store, rid, report_id)["edit_check"] == before_check, "restored edit-check state/counts differ")
                soft(14, [dict(r) for r in restored_conn.execute("SELECT * FROM runs ORDER BY rowid")] == lib["sequence_runs"] and
                     [dict(r) for r in restored_conn.execute("SELECT * FROM step_inputs ORDER BY rowid")] == lib["sequence_inputs"],
                     "backup changed the synthetic run/input audit")
            finally:
                restored_conn.close()

    # 15. Trash/restore preserve all rows; purge removes only the first research.
    with step(15, (9, 14)) as ready:
        if ready:
            other_rid, other_report = _other_finished_report(lib)
            all_before = _table_state(conn)
            # This library has exactly two researches; pin the first one's row
            # identities before purge, then compare the remaining rows exactly.
            first_ids = {report_id}
            first_ids.update(r[0] for r in conn.execute("SELECT id FROM report_sections WHERE report_id = ?", (report_id,)))
            first_ids.update(r[0] for r in conn.execute("SELECT c.id FROM report_claims c JOIN report_sections s"
                                                       " ON s.id = c.report_section_id WHERE s.report_id = ?", (report_id,)))
            first_ids.update(r[0] for r in conn.execute("SELECT v.id FROM report_claim_revisions v JOIN report_claims c"
                                                       " ON c.id = v.claim_id JOIN report_sections s ON s.id = c.report_section_id"
                                                       " WHERE s.report_id = ?", (report_id,)))
            first_ids.add(rid)
            second_rows = {table: [r for r in rs if not first_ids.intersection(r)] for table, rs in all_before.items()}
            readable = reports.report(report_id)
            store.trash_research(rid)
            soft(15, reports.report(report_id) == readable, "trashed report no longer readable from store")
            soft(15, _table_state(conn) == all_before, "trash changed report tables/events")
            store.restore_research(rid)
            soft(15, _table_state(conn) == all_before, "research restore changed report tables/events")
            soft(15, _base_state(lib) == baseline, "base state changed before purge")
            store.trash_research(rid)
            store.purge_research(rid)
            for table in REPORT_TABLES:
                soft(15, rows(conn, table) == second_rows[table], f"purge left first-research rows or changed second rows in {table}")
            soft(15, reports.report(other_report)["research_id"] == other_rid and store.research(other_rid)["id"] == other_rid,
                 "second research/report lost")
            soft(15, conn.execute("SELECT 1 FROM researches WHERE id = ?", (rid,)).fetchone() is None, "first research remains")
            soft(15, conn.execute("PRAGMA foreign_key_check").fetchall() == [], "purge foreign key violations")

    if failures:
        pytest.fail("Synthetic sequence failures (no slice closure):\n" + "\n".join(failures))


def test_the_sequence_is_model_free(sequence_library, tmp_path):
    # Exercise the same function on this test's fresh library. Capture step 14's
    # audit because step 15 intentionally purges the first research's runs.
    test_synthetic_scripted_edit_sequence(sequence_library, tmp_path)
    lib = sequence_library
    runs, inputs = lib["sequence_runs"], lib["sequence_inputs"]
    assert len(runs) == len(inputs) == 4  # fixture fill/report + two recheck proposals
    assert {r["id"]: r["kind"] for r in runs} == lib["expected_runs"]
    assert {r["id"]: (r["run_id"], r["step_id"]) for r in inputs} == lib["expected_inputs"]
    assert sorted(r["kind"] for r in runs) == ["answer", "cell_recheck", "cell_recheck", "report"]
    assert all(r["status"] == "completed" for r in runs)
    tree = ast.parse(Path(__file__).read_text())
    imports = [name for node in ast.walk(tree) for name in (
        [alias.name for alias in node.names] if isinstance(node, ast.Import) else
        [node.module or ""] if isinstance(node, ast.ImportFrom) else []
    )]
    assert not any(name.split(".")[0] in {"httpx", "requests"} or "adapter" in name.split(".")
                   or name.startswith("deixis.models") for name in imports)


def test_two_orders_end_in_the_same_effective_set(tmp_path):
    @contextmanager
    def fresh(name):
        generator = report_with_sections.__wrapped__(tmp_path / name)
        lib = next(generator)
        try:
            _add_claim(lib, "III", "III.1", "Resource allocation assigns capacity.", links=[
                _link(lib, "III.1", passage=False), _link(lib, "III.1"),
            ])
            finish(lib)
            yield lib
        finally:
            with pytest.raises(StopIteration):
                next(generator)

    def normal(link):
        return ("III.1", link["anchor_text"], "passage" if link["passage_id"] else "cell")

    def end_state(lib):
        c = view_claim(lib)
        first = check(lib)
        assert report_view(lib["store"], lib["reports"].report(lib["report_id"])["research_id"], lib["report_id"])["edit_check"]["current"]
        before = _table_state(lib["store"].conn, ("report_edit_checks", "events"))
        assert check(lib)["id"] == first["id"]
        assert _table_state(lib["store"].conn, ("report_edit_checks", "events")) == before
        return (c["text"], sorted(normal(l) for l in lib["reports"].effective_links(lib["report_id"]) if l["claim_key"] == "III.1"),
                sorted(normal(l) for l in c["removed_links"]), c["original_evidence_count"])

    with fresh("remove-first") as one, fresh("text-first") as two:
        keep_one = next(l["id"] for l in one["reports"].original_links(claim(one)["id"]) if l["passage_id"])
        keep_two = next(l["id"] for l in two["reports"].original_links(claim(two)["id"]) if l["passage_id"])
        edit(one, link_ids=[keep_one])
        edit(one, text="SYNTHETIC edited allocation.")
        edit(two, text="SYNTHETIC edited allocation.")
        edit(two, link_ids=[keep_two])
        assert end_state(one) == end_state(two) == (
            "SYNTHETIC edited allocation.", [("III.1", "selected-section evidence", "passage")],
            [("III.1", "selected-section evidence", "cell")], 2,
        )


def test_report_only_source_stays_protected_through_removal_and_restore(report_with_sections):
    lib = report_with_sections
    store = lib["store"]
    source = store.create_upload_source("SYNTHETIC report-only B")
    rid = lib["reports"].report(lib["report_id"])["research_id"]
    store.add_to_corpus(rid, source, "user_upload", selection_state="included", selection_origin="user")
    passage = store._insert_passage(source, None, "section", None, None, None, None, None, "SYNTHETIC report-only quote.")
    payload = store.step_input_payload(lib["report_input_id"])
    payload["step_input_id"] = new_id("sti")
    payload["passages"].append({"passage_id": passage})
    report = lib["reports"].report(lib["report_id"])
    store.insert_step_input(lib["report_step_id"], rid, report["run_id"], 1, payload, "base", "developer", "message", {})
    _add_claim(lib, "IV", "IV.1", "SYNTHETIC report-only claim.", links=[
        _link(lib) | {"source_version_id": source, "passage_id": passage,
                     "anchor_text": "report-only quote", "step_input_id": payload["step_input_id"]},
    ])
    finish(lib)
    store.remove_sources(rid, [source], "SYNTHETIC removed membership")
    for stage in ("original", "removed", "restored"):
        if stage == "removed":
            edit(lib, "IV.1", link_ids=[])
        elif stage == "restored":
            edit(lib, "IV.1", restore_from="model")
        assert_only_report_cites(store, source)
        assert rows(store.conn, "source_assets") == []
        before = _table_state(store.conn, PURGE_GUARD_TABLES)
        with pytest.raises(RevisionConflict, match="Evidence still cites"):
            store.purge_sources(rid, [source])
        assert _table_state(store.conn, PURGE_GUARD_TABLES) == before, stage
