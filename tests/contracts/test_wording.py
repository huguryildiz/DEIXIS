"""Wording checks on answer prose: question language, own-work words and several-sources wording (D43).

The checks are lexical: a pattern match is a finding, not proof that the sentence misattributes anything.
"""

import json
from pathlib import Path

import pytest

from deixis.domain import contracts, wording

FIXTURES = Path(__file__).parent.parent / "fixtures" / "research"
STEP_INPUTS = json.loads((FIXTURES / "step-inputs.json").read_text())
CASES = json.loads((FIXTURES / "fake-outputs.json").read_text())["cases"]


def anchored(draft):
    """Re-derive one exact citation anchor per claim-passage link after a test rewrites the claims."""
    text = {p["passage_id"]: " ".join(p["text"].split()) for p in STEP_INPUTS["A_answer"]["passages"]}
    draft["citation_anchors"] = [{"claim_label": c["claim_label"], "passage_id": pid, "quote": text[pid][:600]}
                                 for c in draft["claims"] for pid in c["passage_ids"]]
    return draft


@pytest.mark.parametrize("support_type, passage_ids, rejected", [
    ("source_stated", ["psg_SYNA1abs01", "psg_SYNA1pg003"], False),  # two passages of one source
    ("source_stated", ["psg_SYNA1abs01", "psg_SYNA3pg002"], True),
    ("analyst_inference", ["psg_SYNA1abs01", "psg_SYNA3pg002"], False),
])
def test_source_stated_claim_cites_one_source(support_type, passage_ids, rejected):
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["claims"] = [dict(draft["claims"][0], support_type=support_type, passage_ids=passage_ids)]
    draft["limitations"], draft["unanswered_aspects"] = [], []
    report = contracts.validate_model_output(STEP_INPUTS["A_answer"], anchored(draft))
    codes = [(i.code, i.path) for i in report.issues if i.code == "source_stated_several_sources"]
    assert codes == ([("source_stated_several_sources", "/claims/0/passage_ids")] if rejected else [])
    assert report.ok is not rejected


def test_several_sources_defect_is_never_salvaged_with_anchor_defects():
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["claims"] = [dict(draft["claims"][0], support_type="source_stated",
                            passage_ids=["psg_SYNA1abs01", "psg_SYNA3pg002"])]
    draft["limitations"], draft["unanswered_aspects"] = [], []
    draft = anchored(draft)
    draft["citation_anchors"].append(dict(draft["citation_anchors"][0]))  # duplicate anchor, salvageable alone
    assert {i.code for i in contracts.validate_model_output(STEP_INPUTS["A_answer"], draft).issues} >= {
        "source_stated_several_sources", "duplicate_citation_anchor"}
    assert contracts.salvage_answer_draft(STEP_INPUTS["A_answer"], draft) == (draft, [])


