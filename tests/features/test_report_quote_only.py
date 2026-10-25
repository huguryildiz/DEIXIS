"""SYNTHETIC checks of D58: report sections receive every table cell with its quotes before any page text, and the
report review reads cell quotes in batches. Passing shows workflow behavior, not report or review quality."""

import json

from deixis.domain import contracts
from deixis.storage import db
from deixis.storage.db import dumps
from deixis.workflow import report_review as review

with open("tests/fixtures/research/step-inputs.json", encoding="utf-8") as source:
    STEP_INPUTS = json.load(source)
with open("tests/fixtures/research/fake-outputs.json", encoding="utf-8") as source:
    SECTION_OUTPUT = next(case["output"] for case in json.load(source)["cases"] if case["name"] == "report_section_valid")
QUOTE_ONLY = "psg_SYNQUOTEONLY01"


def _quote_only_input():
    si = json.loads(json.dumps(STEP_INPUTS["C_report_section_IV"]))
    si["report_target"]["cells"] = [{
        "cell_id": "cel_SYNQUOTE0001", "cell_revision_id": "crv_SYNQUOTE0001", "column_id": "col_SYNTHR0001",
        "source_version_id": si["passages"][0]["source_id"], "state": "value",
        "value": {"text": "SYNTHETIC rate $x^2$"}, "reading_depth": "full_text",
        "evidence": [{"passage_id": QUOTE_ONLY, "quote": "SYNTHETIC stored quote states the rate $x^2$"}]}]
    si["allowlist"]["cell_ids"] = ["cel_SYNQUOTE0001"]
    si["allowlist"]["cell_evidence_passage_ids"] = [QUOTE_ONLY]
    return si


def _cell_draft():
    draft = json.loads(json.dumps(SECTION_OUTPUT))
    draft["claims"][0] |= {"passage_ids": [], "cell_ids": ["cel_SYNQUOTE0001"]}
    draft["citation_anchors"] = [{"claim_key": "IV.1", "passage_id": None, "cell_id": "cel_SYNQUOTE0001",
                                  "quote": "stored quote states the rate"}]
    return draft


def test_a_quote_only_cell_is_cited_by_its_quote_and_its_page_cannot_be_cited():
    si = _quote_only_input()
    assert contracts.validate_model_output(si, _cell_draft()).ok

    draft = _cell_draft()
    draft["claims"][0]["passage_ids"] = [QUOTE_ONLY]
    draft["citation_anchors"].append({"claim_key": "IV.1", "passage_id": QUOTE_ONLY, "cell_id": None,
                                      "quote": "stored quote states the rate"})
    codes = contracts.validate_model_output(si, draft).codes()
    assert "unknown_passage_id" in codes


