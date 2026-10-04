"""Synthetic edit checks; no model, provider or live library is used."""

import copy
import json
import sqlite3

import pytest

from deixis.domain import contracts
from deixis.domain.rules import RevisionConflict
from deixis.storage.db import new_id, transaction
from deixis.workflow.report import assembly, edit_check
from deixis.workflow.report.store import ReportStore
from deixis.workflow.store import NotFound
from deixis.workflow.views import report_view

from tests.report.test_report_assembly import report_with_sections, _issues, _set_section, _add_claim, _claim, _link, _gap, _insert_raw_step_input


# Captured by running these fixtures on 878281f before editing assembly.py.
BASE_OUTPUTS = {
    "clean": [],
    "errors": [{"rule": "banned_word", "section_id": "III", "detail": "ERROR: 'Novel' in heading."}],
    "warnings": [{"rule": "glossary_term_before_definition_warning", "section_id": "II",
                  "detail": "WARNING: glossary term 'resource allocation' is used before its definition in section III."}],
    "malformed": [{"rule": "stored_record_malformed", "section_id": "III",
                   "detail": "ERROR: report_claims III.1 count_json malformed."}],
}


@pytest.mark.parametrize("case", BASE_OUTPUTS)
def test_base_outputs_equal_878281f_literals_even_after_human_edit(report_with_sections, case):
    lib = report_with_sections
    if case == "errors":
        _set_section(lib, "III", draft={"subsections": [{"heading": "Novel methods"}]})
    elif case == "warnings":
        _set_section(lib, "II", draft={"text": "Resource allocation is considered below."})
    elif case == "malformed":
        lib["store"].conn.execute("UPDATE report_claims SET count_json = '{}' WHERE claim_key = 'III.1'")
    assert _issues(lib) == BASE_OUTPUTS[case]
    finish(lib)
    edit(lib, "A novel finding has malformed $math.")
    assert _issues(lib) == BASE_OUTPUTS[case]


def finish(lib, status="valid", run_status="completed"):
    report = lib["reports"].report(lib["report_id"])
    lib["store"].update_run(report["run_id"], status=run_status)
    lib["reports"].finalize(lib["report_id"], status)
    return report["research_id"]


def edit(lib, text, key="III.1"):
    claim = lib["store"].conn.execute("SELECT * FROM report_claims WHERE claim_key = ?", (key,)).fetchone()
    report = lib["reports"].report(lib["report_id"])
    return lib["reports"].edit_claim(report["research_id"], lib["report_id"], claim["id"], text=text,
                                    restore_from=None, note=None, expected_version=claim["version"], idempotency_key=None)


def current(lib):
    return assembly.run_current_checks(lib["store"], lib["reports"], lib["report_id"])


def rules(result):
    return {item["rule"] for item in result["items"]}


def dependencies(lib):
    return edit_check.manifest(lib["store"], lib["reports"], lib["report_id"])


def check(lib):
    report = lib["reports"].report(lib["report_id"])
    return lib["reports"].check_edits(report["research_id"], lib["report_id"])


def test_current_text_glossary_and_banned_word_while_base_stays_clean(report_with_sections):
    lib = report_with_sections
    _add_claim(lib, "I", "I.1", "A bounded synthesis.", support_type="analyst_inference")
    lib["store"].conn.execute("UPDATE report_sections SET ordinal = 1 WHERE section_id = 'I'")
    finish(lib)
    edit(lib, "Resource allocation is novel.", "I.1")
    result = current(lib)
    assert {"glossary_term_before_definition_warning", "banned_word"} <= rules(result)
    assert "banned_word" not in {item["rule"] for item in _issues(lib)}
    assert all(item["severity"] == ("warning" if item["detail"].startswith("WARNING:") else "error")
               for item in result["items"])


@pytest.mark.parametrize("text,expected,skipped", [
    ("9 of 7 sources.", True, False), ("seven sources.", False, True),
    ("The inspected sources.", False, True), ("7 of 7 sources.", False, False),
])
def test_count_current_integers_and_explicit_skip(report_with_sections, text, expected, skipped):
    lib = report_with_sections
    snapshot = lib["reports"].snapshot(lib["report_id"])
    sources = [lib["source_id"]] + [f"synthetic-{i}" for i in range(2, 8)]
    for source in sources[1:]:
        snapshot["rows"].append({"source_version_id": source, "reading_depth": "full_text"})
        snapshot["cells"].append({**snapshot["cells"][0], "cell_id": f"cell-{source}", "source_version_id": source})
    lib["store"].conn.execute("UPDATE report_snapshot SET snapshot_json = ? WHERE report_id = ?",
                              (json.dumps(snapshot), lib["report_id"]))
    count = {"numerator_source_ids": sources, "denominator_source_ids": sources,
             "column_id": snapshot["columns"][0]["column_id"]}
    _add_claim(lib, "IV", "IV.1", "7 of 7 sources.", count=count)
    finish(lib)
    if text != "7 of 7 sources.":
        edit(lib, text, "IV.1")
    result = current(lib)
    assert ("count_number_mismatch" in rules(result)) is expected
    entries = [item for item in result["skipped"] if item["rule"] == "count_text_not_checked"]
    assert bool(entries) is skipped
    if skipped:
        assert entries == [{"rule": "count_text_not_checked", "section_id": "IV", "claim_key": "IV.1",
                            "reason": "no_integer_in_text"}]
        assert result["counts"]["skipped"] >= 1
    assert "count_number_mismatch" not in {item["rule"] for item in _issues(lib)}


def test_unedited_count_without_integer_also_records_skip(report_with_sections):
    lib = report_with_sections
    snapshot = lib["reports"].snapshot(lib["report_id"])
    count = {"numerator_source_ids": [lib["source_id"]], "denominator_source_ids": [lib["source_id"]],
             "column_id": snapshot["columns"][0]["column_id"]}
    _add_claim(lib, "IV", "IV.1", "One source.", count=count)
    assert current(lib)["skipped"] == [{"rule": "count_text_not_checked", "section_id": "IV",
                                       "claim_key": "IV.1", "reason": "no_integer_in_text"}]


def test_budget_recounts_only_edited_sections_with_insufficient_reasons(report_with_sections):
    lib = report_with_sections
    report = lib["reports"].report(lib["report_id"])
    plan = copy.deepcopy(report["plan"])
    plan["section_budgets"] = {"III": {"max_words": 4}, "VIII": {"max_words": 9}}
    lib["reports"].set_plan(lib["report_id"], plan)
    _set_section(lib, "III", draft={"claims": [], "insufficient_evidence": [{"reason": "Missing evidence."}]})
    finish(lib)
    edit(lib, "SYNTHETIC current claim with six words.")
    result = current(lib)
    budgets = [item for item in result["items"] if "word_count_over_budget" in item["rule"]]
    assert [item["detail"] for item in budgets] == [
        "ERROR: current word_count 8 exceeds the frozen upper budget 4.",
        "ERROR: stored word_count 10 exceeds the frozen upper budget 9.",
        "ERROR: current report word_count 18 exceeds the frozen upper budget 13.",
    ]
    assert lib["reports"].section(lib["report_id"], "III")["word_count"] == 10


def test_edited_math_and_diagnostics_skip_frames_but_unedited_frames_still_run(report_with_sections):
    lib = report_with_sections
    lib["store"].conn.execute("DELETE FROM report_phrase_repairs")
    finish(lib)
    edit(lib, "This study cites previous studies with $broken math.")
    result = current(lib)
    assert {"math_not_well_formed", "own_work_phrase_in_claim", "plural_sources_for_one_source"} <= rules(result)
    frames = [item for item in result["items"] if item["rule"] == "unframed_sentence_not_recorded"]
    assert frames and {item["section_id"] for item in frames} == {"abstract"}
    assert {"rule": "phrase_frames", "section_id": "III", "claim_key": "III.1", "reason": "human_text"} in result["skipped"]


@pytest.mark.parametrize("text,error", [("Item 7 describes the limit.", False),
                                       ("Madde 7 ve öğe 8.", False), ("The share is 9 percent.", True)])
def test_edited_viii_reuses_limitations_number_rule(report_with_sections, text, error):
    lib = report_with_sections
    _add_claim(lib, "VIII", "VIII.1", "Item 1 describes the limit.", support_type="analyst_inference")
    finish(lib)
    edit(lib, text, "VIII.1")
    result = current(lib)
    assert ("limitations_number_restated" in rules(result)) is error
    assert contracts.limitations_number_restated(text) is error


@pytest.mark.parametrize("path", ["bibliography", "anchors", "vii_basis", "equations", "depth", "plural"])
def test_each_link_dependent_path_reads_effective_links_and_base_is_raw(report_with_sections, monkeypatch, path):
    lib = report_with_sections
    conn = lib["store"].conn
    target = lib["reports"].effective_links(lib["report_id"])[0]
    if path == "bibliography":
        conn.execute("UPDATE source_versions SET title = '' WHERE id = ?", (lib["source_id"],))
        expected = "reference_record_incomplete"
    elif path == "anchors":
        conn.execute("UPDATE report_citation_links SET anchor_text = 'missing quote' WHERE id = ?", (target["id"],))
        expected = "anchor_not_in_passage"
    elif path == "vii_basis":
        _add_claim(lib, "VII", "VII.1", "A bounded direction.", links=[_link(lib, "VII.1", passage=False)])
        target = lib["reports"].effective_links(lib["report_id"])[-1]
        expected = "vii_claim_without_basis"
    elif path == "equations":
        _add_claim(lib, "IV", "IV.1", "The value is $$x$$.", links=[_link(lib)],
                   origin={"passage_id": lib["section_passage"], "text_source": "text_layer"})
        target = lib["reports"].effective_links(lib["report_id"])[-1]
        expected = "equation_origin_not_cited"
    elif path == "depth":
        # Losing a body's depth must not disable its support-strength comparison.
        conn.execute("UPDATE report_claims SET support_type = 'source_stated' WHERE claim_key = 'abstract.1'")
        conn.execute("UPDATE report_claims SET support_type = 'analyst_inference' WHERE claim_key = 'III.1'")
        expected = "derived_depth_not_checked"
    else:
        finish(lib)
        edit(lib, "Previous studies describe this method.")
        expected = "plural_sources_for_one_source"
    before = current(lib)
    base = _issues(lib)
    original = ReportStore.effective_links
    monkeypatch.setattr(ReportStore, "effective_links", lambda self, rid: [
        link for link in original(self, rid) if link["id"] != target["id"]])
    after = current(lib)
    assert _issues(lib) == base
    if path == "depth":
        assert after["skipped"] != before["skipped"]
        assert any(item["rule"] == expected for item in after["skipped"])
        assert "derived_support_too_strong" in rules(after)
    else:
        before_items = [item for item in before["items"] if item["rule"] == expected and item["section_id"] == target["section_id"]]
        after_items = [item for item in after["items"] if item["rule"] == expected and item["section_id"] == target["section_id"]]
        assert bool(before_items) != bool(after_items)


def test_current_sql_links_only_inside_effective_links(report_with_sections, monkeypatch):
    lib = report_with_sections
    _add_claim(lib, "VII", "VII.1", "A bounded direction.", links=[_link(lib, "VII.1", passage=False)])
    _add_claim(lib, "IV", "IV.1", "The value is $$x$$.", links=[_link(lib)],
               origin={"passage_id": lib["section_passage"], "text_source": "text_layer"})
    original = ReportStore.effective_links
    inside = False
    violations = []
    calls = []
    def effective(self, rid):
        nonlocal inside
        inside = True
        calls.append(rid)
        try:
            return original(self, rid)
        finally:
            inside = False
    monkeypatch.setattr(ReportStore, "effective_links", effective)
    conn = lib["store"].conn
    conn.set_trace_callback(lambda sql: violations.append(sql) if "report_citation_links" in sql.lower() and not inside else None)
    try:
        current(lib)
        dependencies(lib)
    finally:
        conn.set_trace_callback(None)
    assert calls and not violations


def test_missing_body_depth_skips_instead_of_comparing_partial_depths(report_with_sections, monkeypatch):
    lib = report_with_sections
    _add_claim(lib, "IV", "IV.1", "An uncited body claim.")
    claim = lib["store"].conn.execute("SELECT id FROM report_claims WHERE claim_key = 'abstract.1'").fetchone()[0]
    lib["store"].conn.execute("INSERT INTO report_claim_refs VALUES (?, 'body_ref', 'IV.1')", (claim,))
    result = current(lib)
    assert {"rule": "derived_depth_not_checked", "section_id": "abstract", "claim_key": "abstract.1",
            "reason": "no_citation_depth"} in result["skipped"]
    assert "derived_depth_too_deep" not in rules(result)


def test_unknown_body_ref_skips_depth_without_a_partial_comparison(report_with_sections):
    lib = report_with_sections
    conn = lib["store"].conn
    # The base rule keeps its existing behavior; current depth cannot use only the resolved subset.
    conn.execute("UPDATE report_citation_links SET passage_id = ? WHERE claim_id IN"
                 " (SELECT id FROM report_claims WHERE claim_key = 'abstract.1')", (lib["section_passage"],))
    conn.execute("UPDATE report_citation_links SET passage_id = ? WHERE claim_id IN"
                 " (SELECT id FROM report_claims WHERE claim_key = 'III.1')", (lib["abstract_passage"],))
    conn.execute("INSERT INTO report_claim_refs SELECT id, 'body_ref', 'III.missing' FROM report_claims WHERE claim_key = 'abstract.1'")
    result = current(lib)
    assert "derived_depth_too_deep" not in rules(result)
    assert any(item["rule"] == "derived_depth_not_checked" for item in result["skipped"])
    assert "derived_depth_too_deep" in {item["rule"] for item in _issues(lib)}


@pytest.mark.parametrize("change", [
    "revision", "link", "passage_text", "passage_kind", "passage_source", "passage_text_source",
    "snapshot", "draft", "validation", "section_word_count", "section_ordinal", "selected_section_input",
    "link_input", "gap", "phrase_repair", "plan", "language", "language_fallback", "checker_version",
    "phrasebank", "source_title", "source_key", "claim_section", "claim_support", "claim_count",
    "claim_equation_origin", "claim_refs", "claim_paragraph", "claim_key", "claim_ordinal", "claim_table",
    "claim_equation", "claim_axis", "claim_base_text",
])
def test_one_change_in_each_manifest_input_class_changes_fingerprint(report_with_sections, monkeypatch, change):
    lib = report_with_sections
    conn = lib["store"].conn
    finish(lib)
    before = dependencies(lib)
    assert edit_check.fingerprint(before) == edit_check.fingerprint(dependencies(lib))
    if change == "revision":
        edit(lib, "SYNTHETIC human revision.")
    elif change == "link":
        conn.execute("UPDATE report_citation_links SET anchor_text = 'changed' WHERE claim_id IN"
                     " (SELECT id FROM report_claims WHERE claim_key = 'III.1')")
    elif change.startswith("passage_"):
        # Tamper only with this synthetic copy to prove hashing does not rely on immutability guards.
        conn.execute("DROP TRIGGER passages_no_update")
        field = {"passage_text": "text", "passage_kind": "kind", "passage_source": "source_version_id",
                 "passage_text_source": "text_source"}[change]
        value = {"text": "SYNTHETIC changed passage.", "kind": "section", "text_source": "ocr"}.get(field)
        if field == "source_version_id":
            value = lib["store"].create_upload_source("SYNTHETIC other owner")
        passage_id = lib["abstract_passage"] if field == "kind" else lib["section_passage"]
        conn.execute(f"UPDATE passages SET {field} = ? WHERE id = ?", (value, passage_id))
    elif change == "snapshot":
        snap = lib["reports"].snapshot(lib["report_id"])
        snap["corpus"]["found"] += 1
        conn.execute("UPDATE report_snapshot SET snapshot_json = ? WHERE report_id = ?", (json.dumps(snap), lib["report_id"]))
    elif change in {"draft", "validation"}:
        conn.execute(f"UPDATE report_sections SET {change}_json = ? WHERE id = ?",
                     ('{"SYNTHETIC_change":1}', lib["section_ids"]["III"]))
    elif change in {"section_word_count", "section_ordinal"}:
        field = change.removeprefix("section_")
        conn.execute(f"UPDATE report_sections SET {field} = {field} + 1 WHERE id = ?", (lib["section_ids"]["III"],))
    elif change == "selected_section_input":
        # Latest section input changes alone; link input ids still point at the old input.
        _insert_raw_step_input(lib, lib["report_step_id"], '{"question":{"text":"changed","language_hint":"tr"}}')
    elif change == "link_input":
        conn.execute("DROP TRIGGER step_inputs_no_update")
        conn.execute("UPDATE step_inputs SET payload_json = '{}' WHERE id = ?", (lib["report_input_id"],))
    elif change == "gap":
        _gap(lib, "stated_limitation", passage_ids=[lib["section_passage"]])
    elif change == "phrase_repair":
        lib["reports"].save_phrase_repair(lib["report_id"], "III", "III.1#1", "changed", "changed", "unframed_exception")
    elif change == "plan":
        plan = copy.deepcopy(lib["reports"].report(lib["report_id"])["plan"])
        plan["glossary"] = []
        lib["reports"].set_plan(lib["report_id"], plan)
    elif change == "language":
        conn.execute("UPDATE reports SET language = 'tr' WHERE id = ?", (lib["report_id"],))
    elif change == "language_fallback":
        original = lib["store"].scope
        monkeypatch.setattr(lib["store"], "scope", lambda *a, **kw: {**original(*a, **kw), "language_hint": "tr"})
    elif change == "checker_version":
        monkeypatch.setattr(edit_check, "CHECKER_VERSION", "edit-check-2")
    elif change == "phrasebank":
        original = contracts._phrasebank_text()
        monkeypatch.setattr(contracts, "_phrasebank_text", lambda: original + "\nSYNTHETIC phrasebank change")
    elif change == "source_title":
        conn.execute("UPDATE source_versions SET title = 'SYNTHETIC changed title' WHERE id = ?", (lib["source_id"],))
    elif change == "source_key":
        conn.execute("UPDATE works SET source_key = 'SYNTHETIC-changed' WHERE id IN"
                     " (SELECT work_id FROM source_versions WHERE id = ?)", (lib["source_id"],))
    elif change == "claim_section":
        conn.execute("UPDATE report_claims SET report_section_id = ? WHERE claim_key = 'III.1'",
                     (lib["section_ids"]["VIII"],))
    elif change == "claim_refs":
        conn.execute("INSERT INTO report_claim_refs SELECT id, 'body_ref', 'SYNTHETIC' FROM report_claims WHERE claim_key = 'III.1'")
    else:
        field, value = {
            "claim_support": ("support_type", "analyst_inference"), "claim_count": ("count_json", "{}"),
            "claim_equation_origin": ("equation_origin_json", "{}"), "claim_paragraph": ("paragraph", 2),
            "claim_key": ("claim_key", "III.changed"), "claim_ordinal": ("ordinal", 2),
            "claim_table": ("table_ref", "TABLE_I"), "claim_equation": ("equation_ref", "EQ1"),
            "claim_axis": ("axis_id", "SYNTHETIC-axis"),
            "claim_base_text": ("text", "SYNTHETIC changed base text."),
        }[change]
        conn.execute(f"UPDATE report_claims SET {field} = ? WHERE claim_key = 'III.1'", (value,))
    after = dependencies(lib)
    assert edit_check.fingerprint(after) != edit_check.fingerprint(before)
    if change == "selected_section_input":
        assert before["link_step_inputs"] == after["link_step_inputs"]
        assert before["effective_links"] == after["effective_links"]


def test_unlinked_claim_section_move_alone_changes_fingerprint(report_with_sections):
    lib = report_with_sections
    conn = lib["store"].conn
    _add_claim(lib, "IV", "IV.1", "SYNTHETIC uncited claim.")
    finish(lib)
    before = dependencies(lib)
    claim = next(row for row in before["claims"] if row["claim_key"] == "IV.1")
    assert conn.execute("SELECT COUNT(*) FROM report_citation_links WHERE claim_id = ?",
                        (claim["id"],)).fetchone()[0] == 0
    # Tamper only with this synthetic copy; VIII has no claims, so the move preserves claim order.
    conn.execute("UPDATE report_claims SET report_section_id = ? WHERE id = ?",
                 (lib["section_ids"]["VIII"], claim["id"]))
    after = dependencies(lib)
    assert [row["id"] for row in after["claims"]] == [row["id"] for row in before["claims"]]
    assert edit_check.fingerprint(after) != edit_check.fingerprint(before)
    expected = copy.deepcopy(before)
    moved = next(row for row in expected["claims"] if row["id"] == claim["id"])
    moved["report_section_id"] = lib["section_ids"]["VIII"]
    moved["section_id"] = "VIII"
    assert after == expected


def test_absent_inputs_are_explicit_and_latest_phrase_repair_is_selected(report_with_sections):
    lib = report_with_sections
    manifest = dependencies(lib)
    assert next(s for s in manifest["sections"] if s["section_id"] == "VIII")["selected_step_input"] == {"absent": True}
    lib["reports"].save_phrase_repair(lib["report_id"], "III", "III.1#1", "last", "last", "kept")
    rows = [r for r in dependencies(lib)["phrase_repairs"] if r["section_id"] == "III"]
    assert len(rows) == 1 and rows[0]["after"] == "last"
    conn = lib["store"].conn
    conn.execute("UPDATE report_claims SET equation_origin_json = ? WHERE claim_key = 'III.1'",
                 ('{"passage_id":"absent-passage","text_source":"text_layer"}',))
    assert {"id": "absent-passage", "absent": True} in dependencies(lib)["passages"]


def protected_rows(lib):
    return {table: [tuple(row) for row in lib["store"].conn.execute(f"SELECT * FROM {table} ORDER BY id")]
            for table in ("reports", "report_sections", "report_claims")}


def test_persisted_check_is_read_only_replay_writes_nothing_and_version_bump_appends(report_with_sections, monkeypatch):
    lib = report_with_sections
    rid = finish(lib)
    edit(lib, "A novel SYNTHETIC revision.")
    lib["reports"].save_review(lib["report_id"], {"status": "reviewed", "SYNTHETIC": True})
    before = protected_rows(lib)
    first = check(lib)
    assert first["id"].startswith("rec_")
    assert protected_rows(lib) == before
    conn = lib["store"].conn
    events = [tuple(row) for row in conn.execute("SELECT * FROM events ORDER BY id")]
    assert len([e for e in lib["store"].events_after(rid, 0, 1000) if e["type"] == "report_edits_checked"]) == 1
    assert check(lib) == first
    assert [tuple(row) for row in conn.execute("SELECT * FROM events ORDER BY id")] == events
    assert conn.execute("SELECT COUNT(*) FROM report_edit_checks").fetchone()[0] == 1
    monkeypatch.setattr(edit_check, "CHECKER_VERSION", "edit-check-2")
    second = check(lib)
    assert second["id"] != first["id"] and second["checker_version"] == "edit-check-2"
    assert protected_rows(lib) == before
    assert conn.execute("SELECT COUNT(*) FROM report_edit_checks").fetchone()[0] == 2
    assert json.loads(conn.execute("SELECT result_json FROM report_edit_checks WHERE id = ?", (first["id"],)).fetchone()[0]) == first["result"]


def test_evaluation_manifest_insert_and_event_share_one_transaction_and_rollback(report_with_sections, monkeypatch):
    lib = report_with_sections
    finish(lib)
    original = assembly.run_current_checks
    def evaluate(*args):
        assert lib["store"].conn.in_transaction
        assert args[0].conn.in_transaction
        return original(*args)
    monkeypatch.setattr(assembly, "run_current_checks", evaluate)
    original_manifest = edit_check.manifest
    def manifest(*args):
        assert lib["store"].conn.in_transaction
        return original_manifest(*args)
    monkeypatch.setattr(edit_check, "manifest", manifest)
    def fail_event(*args, **kwargs):
        assert lib["store"].conn.in_transaction
        assert lib["store"].conn.execute("SELECT COUNT(*) FROM report_edit_checks").fetchone()[0] == 1
        raise RuntimeError("SYNTHETIC final event failure")
    monkeypatch.setattr(lib["reports"], "_event", fail_event)
    with pytest.raises(RuntimeError, match="final event failure"):
        check(lib)
    assert lib["store"].conn.execute("SELECT COUNT(*) FROM report_edit_checks").fetchone()[0] == 0


def test_state_no_row_then_current_historical_then_new_and_draft_edits(report_with_sections):
    lib = report_with_sections
    rid = finish(lib, "draft")
    assert lib["reports"].edit_check_state(lib["report_id"]) is None
    view = report_view(lib["store"], rid, lib["report_id"])
    assert view["edit_check"] is None and view["has_human_edits"] is False
    first = check(lib)
    assert first["result"]["counts"]["edited_claims"] == 0
    assert report_view(lib["store"], rid, lib["report_id"])["edit_check"]["current"] is True
    edit(lib, "A SYNTHETIC human edit.")
    view = report_view(lib["store"], rid, lib["report_id"])
    assert view["has_human_edits"] is True and view["edited_after_version"] is None
    assert view["edit_check"]["id"] == first["id"] and view["edit_check"]["current"] is False
    second = check(lib)
    assert second["id"] != first["id"]
    assert lib["reports"].edit_check_state(lib["report_id"])["current"] is True


def test_state_prefers_present_fingerprint_over_latest_historical_row(report_with_sections):
    lib = report_with_sections
    finish(lib)
    first = check(lib)
    plan = lib["reports"].report(lib["report_id"])["plan"]
    lib["reports"].set_plan(lib["report_id"], {**plan, "SYNTHETIC": True})
    second = check(lib)
    lib["reports"].set_plan(lib["report_id"], plan)
    state = lib["reports"].edit_check_state(lib["report_id"])
    assert state["id"] == first["id"] != second["id"] and state["current"] is True


@pytest.mark.parametrize("status", ["queued", "running", "pause_requested", "paused"])
def test_check_refuses_unfinished_run(report_with_sections, status):
    lib = report_with_sections
    finish(lib)
    report = lib["reports"].report(lib["report_id"])
    lib["store"].update_run(report["run_id"], status=status)
    with pytest.raises(RevisionConflict):
        check(lib)
    assert lib["store"].conn.execute("SELECT COUNT(*) FROM report_edit_checks").fetchone()[0] == 0


@pytest.mark.parametrize("run_status", ["completed", "failed", "cancelled"])
def test_check_accepts_all_finished_run_statuses(report_with_sections, run_status):
    lib = report_with_sections
    finish(lib, "draft", run_status)
    assert check(lib)["result"]["counts"]["edited_claims"] == 0


def test_other_research_and_unknown_report_raise_not_found(report_with_sections):
    lib = report_with_sections
    finish(lib)
    with pytest.raises(NotFound):
        lib["reports"].check_edits("res_other", lib["report_id"])
    with pytest.raises(NotFound):
        lib["reports"].check_edits(lib["reports"].report(lib["report_id"])["research_id"], "rpt_unknown")


def test_check_table_is_append_only_and_wrong_purge_authorization_cannot_delete(report_with_sections):
    lib = report_with_sections
    finish(lib)
    check(lib)
    conn = lib["store"].conn
    for sql in ("UPDATE report_edit_checks SET checker_version = 'changed'", "DELETE FROM report_edit_checks"):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(sql)
    other = lib["store"].create_research("SYNTHETIC other research", "attached", "quick", [], "fake", "fake", "en")
    with transaction(conn):
        conn.execute("INSERT INTO research_purge_authorizations VALUES (?)", (other,))
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("DELETE FROM report_edit_checks")
        conn.execute("DELETE FROM research_purge_authorizations WHERE research_id = ?", (other,))
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_check_result_bytes_are_deterministic_and_skipped_are_separate(report_with_sections):
    lib = report_with_sections
    finish(lib)
    edit(lib, "A novel SYNTHETIC sentence.")
    one = current(lib)
    two = current(lib)
    assert edit_check.canonical(one) == edit_check.canonical(two)
    assert one["counts"]["errors"] == 1 and one["counts"]["skipped"] == 1
    assert one["not_checked"] == ["semantic_support", "numbers_written_as_words", "passages"]
    assert one["rules_run"] == [check.__name__.removeprefix("_check_") for check in assembly._CHECKS] + ["limitations_number_restated"]


@pytest.mark.parametrize("case,expected", [("duplicates", "duplicate_claim_key"), ("body_refs", "body_ref_missing"),
                                          ("corpus", "corpus_count_mismatch"), ("conflict", "conflict_gap_without_v_claim")])
def test_current_mode_keeps_unchanged_structural_rules(report_with_sections, case, expected):
    lib = report_with_sections
    if case == "duplicates":
        _add_claim(lib, "IV", "III.1", "SYNTHETIC duplicate key.")
    elif case == "body_refs":
        lib["store"].conn.execute("DELETE FROM report_claim_refs")
    elif case == "corpus":
        validation = copy.deepcopy(lib["reports"].section(lib["report_id"], "II")["validation"])
        validation["numbers"]["corpus"]["found"] = 9
        _set_section(lib, "II", validation=validation)
    else:
        _gap(lib, "conflicting_evidence", claim_keys=["V.unknown"])
    assert expected in rules(current(lib))
    assert expected in {item["rule"] for item in _issues(lib)}


@pytest.mark.parametrize("text_source", ["ocr", "marker"])
def test_current_equation_origin_warning_is_preserved_on_edited_math(report_with_sections, text_source):
    lib = report_with_sections
    conn = lib["store"].conn
    passage = lib["store"]._insert_passage(lib["source_id"], None, "section", None, None, None,
                                           None, None, "SYNTHETIC math evidence. $$x$$", text_source=text_source)
    payload = lib["store"].step_input_payload(lib["report_input_id"])
    payload["passages"].append({"passage_id": passage})
    payload["step_input_id"] = new_id("sti")
    report = lib["reports"].report(lib["report_id"])
    lib["store"].insert_step_input(lib["report_step_id"], report["research_id"], report["run_id"], 1,
                                  payload, "base", "developer", "message", {})
    _add_claim(lib, "IV", "IV.1", "The value is $$x$$.", origin={"passage_id": passage, "text_source": text_source},
               links=[_link(lib) | {"passage_id": passage, "step_input_id": payload["step_input_id"], "anchor_text": "math evidence"}])
    finish(lib)
    edit(lib, "The SYNTHETIC value remains $$x$$.", "IV.1")
    result = current(lib)
    equations = [item for item in result["items"] if item["rule"].startswith("equation_")]
    assert equations == [{"rule": "equation_text_source_warning", "section_id": "IV",
                          "detail": f"WARNING: IV.1 equation came from {text_source} text.", "severity": "warning"}]


def test_recount_includes_unedited_claims_of_an_edited_section(report_with_sections):
    lib = report_with_sections
    claims = [_claim("III.1", "SYNTHETIC first claim.", "source_stated"),
              _claim("III.2", "SYNTHETIC second claim remains.", "source_stated")]
    lib["reports"].save_claims(lib["section_ids"]["III"], claims, [])
    plan = copy.deepcopy(lib["reports"].report(lib["report_id"])["plan"])
    plan["section_budgets"]["III"]["max_words"] = 7
    lib["reports"].set_plan(lib["report_id"], plan)
    finish(lib)
    edit(lib, "SYNTHETIC first claim now edited.")
    budgets = [item for item in current(lib)["items"] if item["rule"] == "section_word_count_over_budget"]
    assert budgets[0]["detail"] == "ERROR: current word_count 9 exceeds the frozen upper budget 7."


@pytest.mark.parametrize("origin", ["equation", "gap"])
def test_fingerprint_covers_passages_named_only_by_origins_or_gap_bases(report_with_sections, origin):
    lib = report_with_sections
    conn = lib["store"].conn
    passage = lib["store"]._insert_passage(lib["source_id"], None, "section", None, None, None,
                                           None, None, "SYNTHETIC uncited dependency. $$x$$")
    if origin == "equation":
        conn.execute("UPDATE report_claims SET equation_origin_json = ? WHERE claim_key = 'III.1'",
                     (json.dumps({"passage_id": passage, "text_source": "text_layer"}),))
    else:
        _gap(lib, "stated_limitation", passage_ids=[passage])
    before = dependencies(lib)
    assert passage in {row["id"] for row in before["passages"]}
    assert passage not in {row["passage_id"] for row in before["effective_links"]}
    conn.execute("DROP TRIGGER passages_no_update")
    conn.execute("UPDATE passages SET text = 'SYNTHETIC changed origin passage' WHERE id = ?", (passage,))
    assert edit_check.fingerprint(dependencies(lib)) != edit_check.fingerprint(before)


def test_no_check_state_does_not_build_manifest(report_with_sections, monkeypatch):
    lib = report_with_sections
    def forbidden(*args):
        raise AssertionError("No stored row means no manifest read")
    monkeypatch.setattr(edit_check, "manifest", forbidden)
    assert lib["reports"].edit_check_state(lib["report_id"]) is None


def test_report_in_progress_is_refused_even_with_finished_run(report_with_sections):
    lib = report_with_sections
    report = lib["reports"].report(lib["report_id"])
    lib["store"].update_run(report["run_id"], status="completed")
    with pytest.raises(RevisionConflict):
        check(lib)


def test_check_on_a_trashed_research_is_not_found_and_writes_nothing(report_with_sections):
    from deixis.workflow.store import NotFound

    lib = report_with_sections
    research_id = finish(lib)
    lib["store"].trash_research(research_id)
    before = lib["store"].conn.execute("SELECT (SELECT COUNT(*) FROM report_edit_checks),"
                                       " (SELECT COUNT(*) FROM events)").fetchone()[:]
    with pytest.raises(NotFound):
        check(lib)
    assert tuple(lib["store"].conn.execute("SELECT (SELECT COUNT(*) FROM report_edit_checks),"
                                           " (SELECT COUNT(*) FROM events)").fetchone()[:]) == tuple(before)
