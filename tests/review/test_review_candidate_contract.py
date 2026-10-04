"""Closed candidate context and D12 handles, using SYNTHETIC inputs only."""

import copy
import json

import pytest

from deixis.domain import contracts
from tests.review.review_helpers import si
from tests.review.review_candidate_helpers import candidate_response, candidate_context_fixture


def payload():
    value = si("candidate")
    context = candidate_context_fixture(value)
    value["review_input"]["candidate_context"] = context
    context["matrix"][0]["cells"] = [{"element_ref": "e1", "relation": "partial_match", "condition_alignment": "aligned",
        "note": "SYNTHETIC note", "quotes": [{"passage_id": value["passages"][0]["passage_id"], "quote": value["passages"][0]["text"]}]}]
    context["matrix"][0]["whole_claim_quotes"] = copy.deepcopy(context["matrix"][0]["cells"][0]["quotes"])
    return value


def test_well_formed_candidate_context_is_accepted():
    assert contracts.check_step_input(payload()) == []


@pytest.mark.parametrize("case,code", [("source", "review_matrix_source_missing"),
    ("foreign_passage", "review_matrix_passage_source_mismatch"), ("unknown_element", "review_matrix_element_missing"),
    ("duplicate_element", "duplicate_review_ref"), ("answer_context", "review_target_shape_mismatch"),
    ("candidate_null", "review_target_shape_mismatch"), ("absent", "step_input_schema_invalid"),
    ("unknown_passage", "review_matrix_passage_missing"), ("element_allowlist", "review_allowlist_mismatch")])
def test_candidate_context_rejects_each_bad_link_with_its_code(case, code):
    value = payload(); ctx = value["review_input"]["candidate_context"]; source = ctx["matrix"][0]
    if case == "source": source["source_id"] = "srv_UNKNOWN001"
    elif case == "foreign_passage":
        other = copy.deepcopy(value["sources"][0]); other["source_id"] = "srv_OTHER0001"
        value["sources"].append(other); value["allowlist"]["source_ids"].append(other["source_id"])
        value["passages"][0]["source_id"] = other["source_id"]
    elif case == "unknown_element": source["cells"][0]["element_ref"] = "e99"
    elif case == "duplicate_element": source["cells"].append(copy.deepcopy(source["cells"][0]))
    elif case == "answer_context": value = si("answer"); value["review_input"]["candidate_context"] = ctx
    elif case == "candidate_null": value["review_input"]["candidate_context"] = None
    elif case == "absent": del value["review_input"]["candidate_context"]
    elif case == "unknown_passage": source["cells"][0]["quotes"][0]["passage_id"] = "psg_UNKNOWN001"
    else: value["allowlist"]["element_refs"] = []
    assert code in {issue.code for issue in contracts.check_step_input(value)}


def test_candidate_matrix_handles_round_trip_in_sent_message_and_output():
    value = payload(); sent = contracts.with_citation_handles(value)
    assert contracts.check_step_input(sent) == []
    matrix = sent["review_input"]["candidate_context"]["matrix"][0]
    assert matrix["source_id"] == "srv_S0000001"
    assert matrix["cells"][0]["quotes"][0]["passage_id"] == "psg_P0000001"
    assert matrix["whole_claim_quotes"][0]["passage_id"] == "psg_P0000001"
    out = json.loads(candidate_response(sent))
    result = contracts.resolve_citation_handles(value, json.dumps(out))
    assert result["findings"][0]["evidence"][0]["passage_handle"] == value["passages"][0]["passage_id"]
