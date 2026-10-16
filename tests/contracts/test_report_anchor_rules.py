"""Report-section anchor rules match the answer path: every anchor names a claim of the draft and one of that claim's
own passages or cells, and every claim-evidence pair has an anchor. SYNTHETIC fixtures; workflow rules only."""

import json
from pathlib import Path

from deixis.domain import contracts

FIXTURES = Path(__file__).parent.parent / "fixtures" / "research"
STEP_INPUTS = json.loads((FIXTURES / "step-inputs.json").read_text())
CASES = json.loads((FIXTURES / "fake-outputs.json").read_text())["cases"]


def section():
    si = json.loads(json.dumps(STEP_INPUTS["C_report_section_IV"]))
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "report_section_valid")["output"]))
    return si, draft


def test_the_valid_fixture_still_passes():
    si, draft = section()
    assert contracts.validate_model_output(si, draft).ok


def test_anchor_naming_no_claim_of_the_draft_is_rejected():
    si, draft = section()
    draft["citation_anchors"].append(dict(draft["citation_anchors"][0], claim_key="IV.9"))
    report = contracts.validate_model_output(si, draft)
    assert not report.ok
    issue = next(i for i in report.issues if i.code == "unknown_anchor_claim")
    assert issue.path == "/citation_anchors/1/claim_key" and issue.message == "IV.9"


def test_claim_passage_without_anchor_is_rejected():
    si, draft = section()
    draft["citation_anchors"] = []
    report = contracts.validate_model_output(si, draft)
    assert "missing_citation_anchor" in report.codes()
    assert next(i for i in report.issues if i.code == "missing_citation_anchor").message.startswith("IV.1:psg_SYNA1abs01")


def test_claim_cell_without_anchor_is_rejected():
    si, draft = section()
    cell_id = "cel_SYNTHR0001"
    si["report_target"]["cells"] = [{"cell_id": cell_id, "cell_revision_id": "crv_SYNTHR0001",
        "column_id": "col_SYNTHR0001", "source_version_id": si["passages"][0]["source_id"],
        "state": "value", "value": {"text": "value"}, "reading_depth": "abstract",
        "evidence": [{"passage_id": si["passages"][0]["passage_id"], "quote": "SYNTHETIC stored cell quote words"}]}]
    si["allowlist"]["cell_ids"] = [cell_id]
    draft["claims"][0]["cell_ids"] = [cell_id]
    assert "missing_citation_anchor" in contracts.validate_model_output(si, draft).codes()
    draft["citation_anchors"].append({"claim_key": "IV.1", "passage_id": None, "cell_id": cell_id,
                                      "quote": "SYNTHETIC stored cell quote words"})
    assert contracts.validate_model_output(si, draft).ok


def test_anchor_to_a_passage_the_claim_does_not_cite_is_rejected():
    si, draft = section()
    other = next(p for p in si["passages"] if p["passage_id"] == "psg_SYNA1pg003")
    draft["citation_anchors"].append({"claim_key": "IV.1", "passage_id": other["passage_id"], "cell_id": None,
                                      "quote": other["text"][:60]})
    report = contracts.validate_model_output(si, draft)
    issue = next(i for i in report.issues if i.code == "anchor_passage_not_cited")
    assert issue.path == "/citation_anchors/1/passage_id"


def test_schema_description_names_the_anchor_rules():
    description = contracts.load_schema("ReportSectionDraft")["properties"]["citation_anchors"]["description"]
    assert "checked in code" in description and "every" in description.lower()


def test_null_citation_anchors_reach_validation_instead_of_crashing_the_resolver():
    si = json.loads(json.dumps(STEP_INPUTS["A_answer"]))
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["citation_anchors"] = None
    resolved = contracts.resolve_citation_handles(si, json.dumps(draft))
    assert isinstance(resolved, dict) and resolved["citation_anchors"] is None
    assert not contracts.validate_model_output(si, resolved).ok


def test_plural_source_repair_message_names_no_phrasebank_frame():
    si = json.loads(json.dumps(STEP_INPUTS["A_answer"]))
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["claims"][0]["text"] = "Previous studies report the fake claim."
    report = contracts.validate_model_output(si, draft)
    finding = next(w for w in report.warnings if w.code == "plural_sources_for_one_source")
    assert "frame" not in finding.message


def answer_with_handles():
    si = STEP_INPUTS["A_answer"]
    shown = contracts.with_citation_handles(si)
    return si, shown["passages"][0]["passage_id"], shown["sources"][0]["source_id"]


def test_padded_handles_in_prose_are_named_too():
    si, passage_handle, source_handle = answer_with_handles()
    padded = passage_handle.replace("_P", "_P0")  # one leading zero too many, as resolve_citation_handles accepts
    title = next(s["title"] for s in si["sources"] if s["source_id"] == si["passages"][0]["source_id"])
    data = {"claims": [{"text": f"SYNTHETIC claim ({padded})."}], "limitations": [],
            "unanswered_aspects": [f"Nothing in {source_handle.replace('_S', '_S00')}."]}
    named = contracts.name_sources_in_prose(si, data)
    assert named["claims"][0]["text"] == f"SYNTHETIC claim (“{title}”)."
    assert named["unanswered_aspects"] == [f"Nothing in “{si['sources'][0]['title']}”."]


def test_answer_review_reason_and_notes_are_cleaned_of_handles():
    si, passage_handle, source_handle = answer_with_handles()
    title = next(s["title"] for s in si["sources"] if s["source_id"] == si["passages"][0]["source_id"])
    review = {"reviews": [{"claim_label": "c1", "verdict": "supported", "reason": f"{passage_handle} states it."}],
              "notes": f"Only {source_handle} was read."}
    named = contracts.name_sources_in_prose(si, review)
    assert named["reviews"][0]["reason"] == f"“{title}” states it."
    assert named["notes"] == f"Only “{si['sources'][0]['title']}” was read."
