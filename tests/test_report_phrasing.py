import asyncio
import json

import pytest

from deixis.domain import phrasebank
from deixis.domain.skill import load_skill_package
from deixis.workflow.report.phrasing import flagged_sentences, repair_section
from deixis.workflow.report.plan import freeze_plan
from fakes import envelope
from test_report_flow import report_flow


PHRASEBANK_TEXT = load_skill_package().files[phrasebank.PHRASEBANK]


def test_flagged_sentences_only_checks_claims_and_insufficient_evidence_reasons():
    claims = [
        {"claim_key": "IV.1", "support_type": "source_stated",
         "text": "Fig weiro randomtext not a frame sentence at all zzq."},
        {"context": "validation", "reason": "Zzq randomtext gives no framed explanation at all."},
    ]

    flagged = flagged_sentences("IV", claims, PHRASEBANK_TEXT, "en")

    assert [item["sentence_id"] for item in flagged] == ["IV.1#1", "insufficient_evidence.1#1"]
    assert all(len(item["nearest_frames"]) == 3 for item in flagged)


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


def _repair_case(tmp_path, original, replacement, *, repair_ready=True):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    snapshot = reports.save_snapshot(report_id, run["target"]["table_id"])
    columns = snapshot["columns"]
    reports.set_plan(report_id, freeze_plan({
        "scope_statement": "SYNTHETIC scope.",
        "research_questions": [],
        "glossary": [],
        "axes": [{"axis_id": "AX1", "label": columns[0]["name"],
                  "column_id": columns[0]["column_id"]}],
        "limitations_column_id": columns[1]["column_id"],
        "future_work_column_id": columns[2]["column_id"],
    }, snapshot, len(snapshot["rows"])))
    ordinary_response = adapter.responder

    def responder(step_input):
        if step_input["task_type"] == "report_phrase_repair":
            return json.dumps(envelope(step_input, "deixis.report_phrase_repair_draft.v1") | {
                "repairs": [{"sentence_id": "IV.1#1", "text": replacement}],
            })
        return ordinary_response(step_input)

    adapter.responder = responder
    adapter.ready = repair_ready
    draft = {"claims": [{"claim_key": "IV.1", "text": original}], "insufficient_evidence": []}
    flagged = [{
        "sentence_id": "IV.1#1",
        "text": original,
        "support_type": "source_stated",
        "nearest_frames": ["It has been reported that X."],
        "previous_sentence": None,
        "next_sentence": None,
    }]
    repaired, exceptions = asyncio.run(
        repair_section(flow, run, scope, report_id, "IV", draft, flagged)
    )
    rows = [dict(row) for row in store.conn.execute(
        "SELECT sentence_id, before, after, outcome FROM report_phrase_repairs WHERE report_id = ?",
        (report_id,),
    )]
    return repaired, exceptions, rows, adapter


def test_repair_section_with_no_flagged_sentences_makes_no_call():
    draft = {"claims": [], "insufficient_evidence": []}

    repaired, exceptions = asyncio.run(
        repair_section(None, None, None, "rpt_unused", "IV", draft, [])
    )

    assert repaired is draft
    assert exceptions == []


def test_repair_section_applies_the_rewrite_and_records_a_kept_outcome(tmp_path):
    replacement = "It has been reported that the result reached 12 units."

    repaired, exceptions, rows, adapter = _repair_case(
        tmp_path, "The result reached 12 units.", replacement,
    )

    assert repaired["claims"][0]["text"] == replacement
    assert exceptions == []
    assert rows == [{
        "sentence_id": "IV.1#1", "before": "The result reached 12 units.",
        "after": replacement, "outcome": "kept",
    }]
    assert [call["task_type"] for call in adapter.calls].count("report_phrase_repair") == 1
    repair_input = next(call for call in adapter.calls if call["task_type"] == "report_phrase_repair")
    assert phrasebank.PHRASEBANK in repair_input["skill_files"]


def test_repair_section_rejects_a_changed_number_and_records_an_exception(tmp_path):
    original = "The result reached 12 units."

    repaired, exceptions, rows, _ = _repair_case(
        tmp_path, original, "It has been reported that the result reached 13 units.",
    )

    assert repaired["claims"][0]["text"] == original
    assert [item["sentence_id"] for item in exceptions] == ["IV.1#1"]
    assert rows[0]["outcome"] == "unframed_exception"


def test_repair_section_rejects_a_changed_math_span(tmp_path):
    original = "The relation is $x+y$."

    repaired, exceptions, rows, _ = _repair_case(
        tmp_path, original, "It has been reported that the relation is $x+z$.",
    )

    assert repaired["claims"][0]["text"] == original
    assert [item["sentence_id"] for item in exceptions] == ["IV.1#1"]
    assert rows[0]["outcome"] == "unframed_exception"


def test_repair_section_records_a_rewrite_that_remains_unframed_as_an_exception(tmp_path):
    replacement = "Zzq randomtext still follows no supplied frame at all."

    repaired, exceptions, rows, _ = _repair_case(
        tmp_path, "Fig weiro randomtext not a frame sentence at all zzq.", replacement,
    )

    assert repaired["claims"][0]["text"] == replacement
    assert [item["sentence_id"] for item in exceptions] == ["IV.1#1"]
    assert rows[0]["outcome"] == "unframed_exception"


def test_repair_section_failure_records_an_exception_without_pausing(tmp_path):
    original = "Fig weiro randomtext not a frame sentence at all zzq."

    repaired, exceptions, rows, adapter = _repair_case(
        tmp_path, original, "unused", repair_ready=False,
    )

    assert repaired["claims"][0]["text"] == original
    assert [item["sentence_id"] for item in exceptions] == ["IV.1#1"]
    assert rows[0] == {
        "sentence_id": "IV.1#1", "before": original, "after": original,
        "outcome": "unframed_exception",
    }
    assert adapter.calls == []
