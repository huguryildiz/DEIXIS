"""Assembly wording checks over stored claims (own-work and several-sources wording, D43) and the LaTeX conversion
fallback's log. SYNTHETIC report rows; lexical checks, not proof of misattribution."""

import logging

from deixis.workflow import report_assembly as assembly, report_latex_math as latex_math
from test_report_assembly import _add_claim, _link, report_with_sections  # noqa: F401  (pytest fixture)


def _wording(lib):
    return [(i["rule"], i["section_id"]) for i in
            assembly._check_phrase_frames(lib["store"], lib["reports"], lib["report_id"])]


def test_clean_claims_have_no_wording_findings(report_with_sections):
    assert _wording(report_with_sections) == []


def test_own_work_wording_in_a_claim_is_an_error(report_with_sections):
    lib = report_with_sections
    _add_claim(lib, "IV", "IV.1", "This study compares the methods.", links=[_link(lib)])
    assert _wording(lib) == [("own_work_phrase_in_claim", "IV")]


def test_plural_source_wording_counts_the_claims_linked_sources(report_with_sections):
    lib = report_with_sections
    _add_claim(lib, "IV", "IV.1", "Previous studies compare the methods.", links=[_link(lib)])
    assert _wording(lib) == [("plural_sources_for_one_source", "IV")]
    other = lib["store"].create_upload_source("SYNTHETIC second study")
    _add_claim(lib, "IV", "IV.1", "Previous studies compare the methods.",
               links=[_link(lib), _link(lib, source_id=other)])
    assert _wording(lib) == []


def test_unexpected_math_conversion_error_falls_back_to_plain_text_and_is_logged(monkeypatch, caplog):
    def broken(span):
        raise RuntimeError("SYNTHETIC conversion bug")
    monkeypatch.setattr(latex_math, "closed_scan", broken)
    with caplog.at_level(logging.ERROR, logger=latex_math.__name__):
        span = latex_math.classify("$x^2$")
    assert span.kind == "plain"
    assert any("SYNTHETIC conversion bug" in (r.exc_text or "") or r.exc_info for r in caplog.records)
