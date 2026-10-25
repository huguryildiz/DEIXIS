"""Synthetic edit checks; no model, provider or live library is used."""

import json

import pytest

from deixis.domain.rules import RevisionConflict
from deixis.workflow import report_assembly as assembly, report_edit_check as edit_check

from test_report_assembly import report_with_sections, _issues, _add_claim


# Captured by running these fixtures on 878281f before editing assembly.py.


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


@pytest.mark.parametrize("status", ["running"])
def test_check_refuses_unfinished_run(report_with_sections, status):
    lib = report_with_sections
    finish(lib)
    report = lib["reports"].report(lib["report_id"])
    lib["store"].update_run(report["run_id"], status=status)
    with pytest.raises(RevisionConflict):
        check(lib)
    assert lib["store"].conn.execute("SELECT COUNT(*) FROM report_edit_checks").fetchone()[0] == 0
