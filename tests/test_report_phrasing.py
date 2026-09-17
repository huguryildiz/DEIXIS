import pytest

from deixis.domain import phrasebank
from deixis.domain.skill import load_skill_package
from deixis.workflow.report.phrasing import flagged_sentences


PHRASEBANK_TEXT = load_skill_package().files[phrasebank.PHRASEBANK]


def test_flagged_sentences_checks_claim_text_and_preserves_neighbours():
    claims = [{
        "claim_key": "IV.1",
        "support_type": "source_stated",
        "text": (
            "It has been reported that molecule budgets affect delivery. "
            "Fig weiro randomtext not a frame sentence at all zzq. "
            "It has been reported that relay placement affects delivery."
        ),
    }]

    flagged = flagged_sentences("IV", claims, PHRASEBANK_TEXT, "en")

    assert [item["sentence_id"] for item in flagged] == ["IV.1#2"]
    assert flagged[0]["support_type"] == "source_stated"
    assert len(flagged[0]["nearest_frames"]) == 3
    assert flagged[0]["previous_sentence"].startswith("It has been reported")
    assert flagged[0]["next_sentence"].startswith("It has been reported")


def test_flagged_sentences_checks_insufficient_evidence_reasons():
    claims = [{
        "claim_key": "IV.1",
        "support_type": "source_stated",
        "text": "It has been reported that molecule budgets affect delivery.",
        "insufficient_evidence": [
            {"context": "validation", "reason": "Zzq randomtext gives no framed explanation at all."},
        ],
    }]

    flagged = flagged_sentences("IV", claims, PHRASEBANK_TEXT, "en")

    assert [item["sentence_id"] for item in flagged] == ["insufficient_evidence.1#1"]
    assert flagged[0]["support_type"] == "analyst_inference"
    assert flagged[0]["previous_sentence"] is None
    assert flagged[0]["next_sentence"] is None


def test_section_without_assigned_frames_is_not_checked():
    claims = [{
        "claim_key": "index_terms.1",
        "support_type": "source_stated",
        "text": "Quantum networks. Entanglement routing. Fidelity.",
    }]

    assert flagged_sentences("index_terms", claims, PHRASEBANK_TEXT, "en") == []


def test_unknown_section_is_a_caller_error():
    with pytest.raises(KeyError):
        flagged_sentences("unknown", [], PHRASEBANK_TEXT, "en")
