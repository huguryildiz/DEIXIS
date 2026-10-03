"""Synthetic policy contracts; paired with the Store's D45 defect guards and page-loss red test."""

import pytest

from deixis.documents import pdf
from deixis.workflow import recovery


def state(status="partial", page_count=3, pages=(1, 2), **overrides):
    return {"status": status, "error": None, "page_count": page_count, "extractor_profile": pdf.EXTRACTION_VERSION,
            "manifest": [(p, str(p), "chars:0-1", str(p), "text_layer") for p in pages],
            "passage_count": len(pages), "ocr_json": None, "math_json": None, **overrides}


@pytest.mark.parametrize("version", ["unknown", pdf.EXTRACTION_VERSION, "B+ocr-tesseract-5-eng-v1+marker-v1"])
def test_plain_identity_is_byte_identical(version):
    assert recovery.profile_of(version) == version
    assert recovery.recovery_token(version) == ""
    assert recovery.text_base(version) == pdf.EXTRACTION_VERSION


@pytest.mark.parametrize("suffix", ["", "+ocr-tesseract-5-eng-v1", "+ocr-tesseract-5-eng-v1+marker-v1", "+arxiv-latex-v1"])
def test_recovery_identity_removes_only_one_segment(suffix):
    version = pdf.EXTRACTION_VERSION + "+reextract-rop_X" + suffix
    assert recovery.profile_of(version) == pdf.EXTRACTION_VERSION + suffix
    assert recovery.recovery_token(version) == "+reextract-rop_X"
    assert recovery.text_base(version) == pdf.EXTRACTION_VERSION + "+reextract-rop_X"
    assert recovery.occurrence(pdf.EXTRACTION_VERSION, "rop_X") == pdf.EXTRACTION_VERSION + "+reextract-rop_X"


@pytest.mark.parametrize("version", ["B+reextract-", "B+reextract-rop-X", "B+reextract-x+reextract-y", "B+reextract-x!"])
def test_malformed_and_multiple_tokens_are_refused(version):
    with pytest.raises(ValueError): recovery.profile_of(version)


@pytest.mark.parametrize("operation", ["", "rop-X", "x+y", "../x"])
def test_occurrence_refuses_invalid_ids(operation):
    with pytest.raises(ValueError): recovery.occurrence("B", operation)
    with pytest.raises(ValueError): recovery.occurrence("B+reextract-x", "rop_X")


@pytest.mark.parametrize("integrity", [None, "legacy_unknown", "missing", "verified", "mismatch"])
@pytest.mark.parametrize("count", [3, 5])
@pytest.mark.parametrize("new_pages", [(1, 2, 3), (2, 3)])
def test_page_count_observation_table(integrity, count, new_pages):
    baseline = state(input_integrity=integrity)
    candidate = state(page_count=count, pages=new_pages)
    decision = recovery.decide(baseline, candidate)
    lost = 1 not in new_pages
    if count == 3:
        code = "text_page_lost" if lost else "text_updated"
    elif integrity == "mismatch":
        code = "text_page_lost" if lost else "recovered_from_corrupt_input"
    else:
        code = "page_count_changed" if integrity == "verified" else "legacy_page_count_untrusted"
    assert decision.decision_code == code
    assert decision.promote == (code in ("text_updated", "recovered_from_corrupt_input"))
    assert decision.missing_pages == ([1] if lost else [])
    assert (decision.old_coverage, decision.new_coverage) == (baseline["manifest"], candidate["manifest"])


@pytest.mark.parametrize("status", ["failed", "no_text"])
@pytest.mark.parametrize("candidate_status,error,pages,code,diagnostic", [
    ("succeeded", None, (1, 2, 3), "recovered_text", False),
    ("partial", None, (1,), "recovered_text", False),
    ("partial", None, (), "candidate_failed", False),
    ("succeeded", None, (), "candidate_failed", False),
    ("no_text", None, (), "no_text_diagnosed", True),
    ("failed", "ordinary failure", (), "candidate_failed", False),
])
def test_empty_baseline_rules(status, candidate_status, error, pages, code, diagnostic):
    decision = recovery.decide(state(status, 0, ()), state(candidate_status, 3, pages, error=error))
    assert (decision.decision_code, decision.diagnostic_only) == (code, diagnostic)
    assert decision.promote == (code != "candidate_failed")


@pytest.mark.parametrize("status", ["failed", "no_text"])
def test_password_exception_is_only_for_empty_no_text(status):
    decision = recovery.decide(state(status, 0, ()), state("failed", 0, (), error=pdf.ERROR_PASSWORD))
    assert decision.decision_code == ("password_diagnosed" if status == "no_text" else "candidate_failed")


@pytest.mark.parametrize("provenance", ["ocr_json", "math_json", "passage"])
def test_identical_augmented_text_is_not_no_change(provenance):
    baseline = state()
    if provenance == "passage":
        baseline["manifest"] = [(*baseline["manifest"][0][:4], "ocr"), baseline["manifest"][1]]
    else: baseline[provenance] = "{}"
    candidate = state()
    assert recovery.decide(baseline, candidate).decision_code == "augmented_text_would_be_lost"


def test_policy_precedence_and_no_change():
    assert recovery.decide(state(), state()).decision_code == "no_change"
    assert recovery.decide(state(ocr_json="{}"), state("failed", error=pdf.ERROR_PASSWORD)).decision_code == "candidate_failed"
    assert recovery.decide(state(), state("no_text", pages=())).decision_code == "status_worse"
    assert recovery.decide(state(), state("failed", error=pdf.ERROR_PASSWORD)).decision_code == "candidate_failed"
