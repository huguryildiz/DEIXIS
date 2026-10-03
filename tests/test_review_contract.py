"""Owner-review rejection paths on synthetic inputs; no scientific quality claim."""

import copy
import json
import sqlite3

import pytest
from jsonschema import Draft202012Validator

from deixis.domain import contracts
from tests.fakes import valid_response
from tests.review_helpers import si, output, finding


def codes(step_input, result):
    return {i.code for i in contracts.validate_model_output(step_input, result).issues}


def input_codes(step_input):
    return {i.code for i in contracts.check_step_input(step_input)}


@pytest.mark.parametrize("wire", [False, True])
def test_owner_review_schema_is_closed_and_strict(wire):
    schema = contracts.step_output_schema("owner_review") if wire else contracts.load_schema("OwnerReview")
    Draft202012Validator.check_schema(schema)
    assert contracts.strict_compatibility_issues(contracts.step_output_schema("owner_review")) == []
    draft = output(); draft["verdict"] = "invented"
    assert "schema_invalid" in codes(si(), draft)


def test_empty_and_evidenced_findings_are_valid():
    step = si(); draft = output(step)
    assert codes(step, draft) == set()
    draft["findings"] = [finding(step)]
    draft["supported_points"] = [{"target_ref": {"kind": "claim", "ref": "c1"}, "evidence": draft["findings"][0]["evidence"]}]
    assert codes(step, draft) == set()


@pytest.mark.parametrize("change,code", [
    ({"target_ref": {"kind": "section", "ref": "III"}}, "review_target_kind_mismatch"),
    ({"target_ref": {"kind": "claim", "ref": "c2"}}, "review_ref_unknown"),
    ({"target_ref": {"kind": "claim", "ref": None}}, "review_ref_without_kind"),
    ({"target_ref": {"kind": "whole", "ref": "c1"}}, "review_ref_without_kind"),
    ({"evidence": [{"passage_handle": "psg_UNKNOWN0001", "anchor": "SYNTHETIC."}]}, "review_passage_not_allowed"),
    ({"evidence": [{"passage_handle": "psg_SYNA1abs01", "anchor": "No such words."}]}, "review_anchor_not_in_passage"),
    ({"evidence": []}, "finding_without_evidence"),
])
def test_each_semantic_rejection(change, code):
    step = si(); draft = output(step); draft["findings"] = [finding(step, **change)]
    assert code in codes(step, draft)


@pytest.mark.parametrize("array", ["findings", "supported_points"])
def test_one_changed_word_is_fuzzy_and_refused(array):
    step = si(); step["passages"][0]["text"] = "SYNTHETIC: The scheduling mechanism decreases delay under bounded arrivals."
    quote = "SYNTHETIC: The scheduling mechanism increases delay under bounded arrivals."
    assert contracts.locate_anchor(quote, step["passages"][0]["text"]).kind == "fuzzy"
    item = finding(step, evidence=[{"passage_handle": step["passages"][0]["passage_id"], "anchor": quote}])
    if array == "supported_points":
        item = {k: item[k] for k in ("target_ref", "evidence")}
    draft = output(step); draft[array] = [item]
    assert "review_anchor_not_exact" in codes(step, draft)


def test_normalized_contiguous_quote_is_valid():
    step = si(); step["passages"][0]["text"] = "SYNTHETIC: A bounded\n scheduling mechanism."
    draft = output(step); draft["findings"] = [finding(step, evidence=[{"passage_handle": step["passages"][0]["passage_id"], "anchor": "A bounded scheduling mechanism."}])]
    assert codes(step, draft) == set()


@pytest.mark.parametrize("array", ["findings", "supported_points"])
@pytest.mark.parametrize("length", [1, 11, 12])
def test_review_anchor_minimum_length(array, length):
    step = si(); draft = output(step)
    item = finding(step, kind="unsupported", evidence=[{
        "passage_handle": step["passages"][0]["passage_id"],
        "anchor": step["passages"][0]["text"][:length],
    }])
    draft[array] = [item if array == "findings" else {k: item[k] for k in ("target_ref", "evidence")}]
    assert ("schema_invalid" in codes(step, draft)) == (length < 12)


def test_duplicate_handle_and_duplicate_evidence():
    step = si(); draft = output(step); item = finding(step)
    draft["findings"] = [item, copy.deepcopy(item)]
    assert "duplicate_finding_handle" in codes(step, draft)
    draft["findings"] = [item]; item["evidence"] *= 2
    assert "duplicate_review_evidence" in codes(step, draft)


@pytest.mark.parametrize("kind", ["unsupported", "partially_supported", "overstated", "missing_context", "inconsistent", "assumption_unstated", "other"])
def test_evidence_requirement_per_kind(kind):
    step = si(); draft = output(step); draft["findings"] = [finding(step, kind=kind, evidence=[])]
    assert ("finding_without_evidence" in codes(step, draft)) == (kind in {"unsupported", "partially_supported", "overstated"})


@pytest.mark.parametrize("target_kind", ["answer", "report", "candidate"])
@pytest.mark.parametrize("kind", ["claim", "section", "candidate_element", "whole"])
def test_typed_target_kind_matrix(target_kind, kind):
    step = si(target_kind); draft = output(step)
    refs = {"claim": step["allowlist"]["claim_refs"], "section": step["allowlist"]["section_refs"], "candidate_element": step["allowlist"]["element_refs"]}
    draft["context_limits"] = [{"code": "not_enough_context", "target_ref": {"kind": kind, "ref": None if kind == "whole" else (refs[kind] or ["c1"])[0]}, "text": "SYNTHETIC context."}]
    accepted = kind in {"answer": {"claim", "whole"}, "report": {"claim", "section", "whole"}, "candidate": {"candidate_element", "whole"}}[target_kind]
    assert ("review_target_kind_mismatch" not in codes(step, draft)) == accepted
    if accepted:
        assert codes(step, draft) == set()


def test_claim_label_is_not_a_section_ref():
    step = si("report"); draft = output(step)
    draft["context_limits"] = [{"code": "only_abstract", "target_ref": {"kind": "section", "ref": "III.1"}, "text": "SYNTHETIC"}]
    assert "review_ref_unknown" in codes(step, draft)


@pytest.mark.parametrize("field", list(contracts.ENVELOPE_FIELDS))
def test_envelope_mismatch(field):
    step = si(); draft = output(step)
    draft[field] = 2 if field == "scope_revision" else "sti_OTHER0001" if field == "step_input_id" else "sha256:" + "2" * 64
    assert "envelope_mismatch" in codes(step, draft)


@pytest.mark.parametrize("draft", [{}, {"findings": [None]}, {"findings": "bad"}, {"findings": [{"target_ref": []}]}])
def test_schema_invalid_draft_best_effort_never_raises(draft):
    assert "schema_invalid" in codes(si(), draft)


def test_best_effort_keeps_semantic_rejection_on_extra_property():
    step = si(); draft = output(step); draft["extra"] = True
    draft["findings"] = [finding(step, target_ref={"kind": "claim", "ref": "c2"})]
    assert {"schema_invalid", "review_ref_unknown"} <= codes(step, draft)


@pytest.mark.parametrize("field", ["rationale", "notes", "suggested_fix", "extra_key"])
def test_surrogates_produce_utf8_storable_diagnostics(field):
    step = si(); draft = output(step); draft["findings"] = [finding(step)]
    if field == "extra_key":
        draft["\ud800"] = "bad"
    elif field == "notes":
        draft[field] = "\ud800"
    else:
        draft["findings"][0][field] = "\ud800"
    report = contracts.validate_model_output(step, json.dumps(draft))
    assert "text_not_encodable" in {i.code for i in report.issues}
    with sqlite3.connect(":memory:") as conn:
        conn.execute("CREATE TABLE diagnostics (path TEXT, message TEXT)")
        conn.executemany("INSERT INTO diagnostics VALUES (?, ?)", [(i.path, i.message) for i in report.issues])


@pytest.mark.parametrize("target_kind", ["answer", "report", "candidate"])
def test_handles_roundtrip_and_zero_padding(target_kind):
    step = si(target_kind); shown = contracts.with_citation_handles(step)
    assert contracts.check_step_input(shown) == []
    for field in ("claim_refs", "section_refs", "element_refs"):
        assert shown["allowlist"][field] == step["allowlist"][field]
    raw = json.loads(valid_response(shown))
    raw["supported_points"][0]["evidence"][0]["passage_handle"] = "psg_P00000001"
    resolved = contracts.resolve_citation_handles(step, json.dumps(raw))
    assert codes(step, resolved) == set()
    raw["supported_points"][0]["evidence"][0]["passage_handle"] = "srv_S00000001"
    assert "review_passage_not_allowed" in codes(step, contracts.resolve_citation_handles(step, json.dumps(raw)))


@pytest.mark.parametrize("has_passages", [True, False])
def test_fake_response_with_and_without_passages(has_passages):
    step = si()
    if not has_passages:
        step["passages"] = []; step["sources"] = []
        step["allowlist"]["passage_ids"] = []; step["allowlist"]["source_ids"] = []
        step["review_input"]["passage_ids"] = []; step["review_input"]["claims"][0]["citations"] = []
    assert input_codes(step) == set()
    assert codes(step, valid_response(step)) == set()
    draft = json.loads(valid_response(step))
    assert bool(draft["supported_points"]) == has_passages
    assert bool(draft["context_limits"]) != has_passages


def report_cell_input():
    step = si("report"); pid = step["passages"][0]["passage_id"]
    step["review_input"]["cells"] = [{"cell_id": "cel_SYNTHCELL01", "column_id": "col_SYNTHCOL01", "source_id": step["sources"][0]["source_id"], "state": "value", "value_text": "{}", "evidence": [{"passage_id": pid, "quote": "SYNTHETIC."}]}]
    step["review_input"]["columns"] = [{"column_id": "col_SYNTHCOL01", "name": "SYNTHETIC column", "answer_format": "text"}]
    step["review_input"]["claims"][0]["citations"] = [{"cell_id": "cel_SYNTHCELL01", "passage_id": None, "anchor_text": "SYNTHETIC."}]
    step["allowlist"]["cell_ids"] = ["cel_SYNTHCELL01"]
    assert input_codes(step) == set()
    return step


@pytest.mark.parametrize("case,code", [
    ("both_ids", "review_citation_id_mismatch"), ("neither_id", "review_citation_id_mismatch"),
    ("passage_not_shown", "review_citation_passage_missing"), ("passage_not_allowed", "review_citation_passage_missing"),
    ("cell_not_shown", "review_citation_cell_missing"), ("cell_not_allowed", "review_citation_cell_missing"),
    ("source_not_shown", "review_cell_source_missing"), ("source_not_allowed", "review_cell_source_missing"),
    ("column_not_shown", "review_cell_column_missing"), ("cell_evidence_missing", "review_cell_passage_missing"),
    ("passage_ids_mismatch", "review_passage_ids_mismatch"), ("allowlist_passages_mismatch", "review_passage_ids_mismatch"),
    ("duplicate_ref", "duplicate_review_ref"), ("duplicate_cell", "duplicate_review_ref"),
    ("ref_list_mismatch", "review_allowlist_mismatch"), ("section_list_mismatch", "review_allowlist_mismatch"),
    ("element_list_mismatch", "review_allowlist_mismatch"), ("group_index", "review_group_out_of_range"),
    ("blank_note", "review_owner_note_blank"), ("empty_note", "review_owner_note_blank"),
    ("long_note", "step_input_schema_invalid"), ("extra_property", "step_input_schema_invalid"),
    ("unknown_allowlist", "step_input_schema_invalid"), ("other_allowlist", "review_allowlist_mismatch"),
    ("other_target", "review_input_mismatch"), ("candidates", "review_input_mismatch"),
    ("wrong_target_shape", "review_target_shape_mismatch"), ("claim_section", "review_claim_section_missing"),
    ("too_many_passages", "review_passage_count"),
])
def test_each_step_input_rejection(case, code):
    step = report_cell_input(); review = step["review_input"]; cite = review["claims"][0]["citations"][0]; cell = review["cells"][0]
    if case == "both_ids": cite["passage_id"] = step["passages"][0]["passage_id"]
    elif case == "neither_id": cite["cell_id"] = None
    elif case.startswith("passage_not_"):
        cite["cell_id"] = None; cite["passage_id"] = step["passages"][0]["passage_id"]
        if case == "passage_not_shown": step["passages"] = []
        else: step["allowlist"]["passage_ids"] = []
    elif case == "cell_not_shown": review["cells"] = []
    elif case == "cell_not_allowed": step["allowlist"]["cell_ids"] = []
    elif case == "source_not_shown": step["sources"] = []
    elif case == "source_not_allowed": step["allowlist"]["source_ids"] = []
    elif case == "column_not_shown": review["columns"] = []
    elif case == "cell_evidence_missing": cell["evidence"][0]["passage_id"] = "psg_UNKNOWN0001"
    elif case == "passage_ids_mismatch": review["passage_ids"] = []
    elif case == "allowlist_passages_mismatch": step["allowlist"]["passage_ids"] = []
    elif case == "duplicate_ref": review["claims"] *= 2
    elif case == "duplicate_cell": review["cells"] *= 2
    elif case == "ref_list_mismatch": step["allowlist"]["claim_refs"] = []
    elif case == "section_list_mismatch": step["allowlist"]["section_refs"] = []
    elif case == "element_list_mismatch": step["allowlist"]["element_refs"] = ["e1"]
    elif case == "group_index": review["group_index"] = 2
    elif case == "blank_note": review["owner_note"] = " \t\n "
    elif case == "empty_note": review["owner_note"] = ""
    elif case == "long_note": review["owner_note"] = "a" * 501
    elif case == "extra_property": review["extra"] = True
    elif case == "unknown_allowlist": step["allowlist"]["extra"] = []
    elif case == "other_allowlist": step["allowlist"]["column_ids"] = []
    elif case == "other_target": step["candidate_target"] = copy.deepcopy(si_base_candidate_target())
    elif case == "candidates": step["candidates"] = copy.deepcopy(si_base_candidates())
    elif case == "wrong_target_shape": review["target_kind"] = "answer"
    elif case == "claim_section": review["claims"][0]["section_ref"] = "IV"
    elif case == "too_many_passages":
        step["passages"] *= 49  # The top-level cap is enforced even when the nested list is short.
    assert code in input_codes(step)


def si_base_candidate_target():
    from tests.review_helpers import INPUTS
    return next(v["candidate_target"] for v in INPUTS.values() if isinstance(v, dict) and "candidate_target" in v)


def si_base_candidates():
    from tests.review_helpers import INPUTS
    return next(v["candidates"] for v in INPUTS.values() if isinstance(v, dict) and v.get("candidates"))


def test_review_input_is_required_iff_owner_review():
    step = si(); del step["review_input"]
    assert "review_input_mismatch" in input_codes(step)
    step = si(); step["task_type"] = "grounded_answer"
    assert "review_input_mismatch" in input_codes(step)
