"""Synthetic API/export reason boundaries; details are data, never display copy."""

import asyncio
import json

import pytest

from deixis.workflow.report.export import to_markdown
from deixis.workflow.report.sections import run_report
from deixis.workflow.report import assembly
from deixis.workflow.views import report_view
from test_report_flow import report_flow


def assembly_draft(tmp_path):
    state = report_flow(tmp_path)
    flow, store, reports, adapter, run, scope, report_id = state
    # Preservation: inject a stored bad section at assembly, bypassing the new section-time rejection.
    original = assembly.run_assembly_checks
    def checks(store_arg, reports_arg, report_arg):
        store_arg.conn.execute("UPDATE report_claims SET text = ? WHERE report_section_id = ?",
            ("It has been reported that the SYNTHETIC formulation records a research gap.",
             reports_arg.section(report_arg, "IV")["id"]))
        return original(store_arg, reports_arg, report_arg)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(assembly, "run_assembly_checks", checks)
        asyncio.run(run_report(flow, run, scope))
    assert reports.report(report_id)["status"] == "draft"
    return state


@pytest.mark.parametrize("language", ["en", "tr"])
@pytest.mark.parametrize("count", [0, 1])
def test_assembly_draft_export_names_only_three_unique_error_rules_and_never_details(tmp_path, language, count):
    _, store, _, _, run, _, report_id = assembly_draft(tmp_path)
    entries = [{"rule": rule, "section_id": "IV", "detail": "model-written secret cel_REALSECRET psg_REALSECRET"}
               for rule in ["banned_word", "banned_word", "empty_section", "unknown_rule", "fourth_rule", "fifth_rule"]]
    entries.insert(0, {"rule": "equation_text_source_warning", "section_id": "IV", "detail": "WARNING: secret"})
    store.update_run(run["id"], status="completed", error_json=entries)
    view = report_view(store, run["research_id"], report_id)
    assert view["run"]["error"] == entries
    view["language"] = language
    if count:
        view["sections"][0]["status"] = "draft"
    text = to_markdown(view, title="SYNTHETIC report", corpus=None)
    first = text.splitlines()[0]
    if count:
        assert first == ("> DRAFT: 1 sections not validated." if language == "en" else "> TASLAK: 1 bölüm doğrulanmadı.")
    else:
        assert first == ("> DRAFT: the assembly check refused the report (banned word, empty section, unknown rule and 2 more)."
                         if language == "en" else "> TASLAK: birleştirme kontrolü raporu reddetti (yasak sözcük, boş bölüm, unknown rule ve 2 kural daha).")
    assert not any(secret in text for secret in ("secret", "REALSECRET", "model-written", "equation text source warning", "fourth rule", "fifth rule"))


@pytest.mark.parametrize("language", ["en", "tr"])
@pytest.mark.parametrize("error", [None, {"sections": ["IV"]}, [{"rule": "only_warning", "section_id": None, "detail": "WARNING: secret"}]])
def test_no_stored_assembly_reason_keeps_the_existing_draft_line(tmp_path, language, error):
    _, store, _, _, run, _, report_id = assembly_draft(tmp_path)
    store.update_run(run["id"], status="completed", error_json=error)
    view = report_view(store, run["research_id"], report_id)
    if not isinstance(error, list):
        assert "error" not in view["run"]
    view["language"] = language
    assert to_markdown(view, title="SYNTHETIC", corpus=None).splitlines()[0] == (
        "> DRAFT: 0 sections not validated." if language == "en" else "> TASLAK: 0 bölüm doğrulanmadı.")


def test_warning_suffix_without_warning_detail_is_an_assembly_error(tmp_path):
    _, store, _, _, run, _, report_id = assembly_draft(tmp_path)
    store.update_run(run["id"], status="completed", error_json=[{"rule": "odd_warning", "section_id": "IV", "detail": "ERROR: secret"}])
    view = report_view(store, run["research_id"], report_id)
    assert to_markdown(view, title="SYNTHETIC", corpus=None).splitlines()[0] == "> DRAFT: the assembly check refused the report (odd warning)."
