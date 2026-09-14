"""P1 deterministic contract tests with synthetic inputs and fake model outputs.

Passing these tests shows schema, identifier-scope and version rules hold in code.
It does not show that any model follows the method package.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from deixis.domain import contracts
from deixis.domain.rules import (
    RevisionConflict,
    after_invalid_output,
    check_expected_version,
    effective_selection,
    result_applicability,
)

FIXTURES = Path(__file__).parent / "fixtures" / "research"
STEP_INPUTS = json.loads((FIXTURES / "step-inputs.json").read_text())
CASES = json.loads((FIXTURES / "fake-outputs.json").read_text())["cases"]


def test_canonical_schemas_are_valid_draft_2020_12():
    for name in contracts.SCHEMA_FILES:
        Draft202012Validator.check_schema(contracts.load_schema(name))


@pytest.mark.parametrize("task_type", sorted(contracts.TASK_OUTPUTS))
def test_step_output_schema_is_self_contained_and_strict(task_type):
    schema = contracts.step_output_schema(task_type)
    Draft202012Validator.check_schema(schema)
    assert "common.schema.json" not in json.dumps(schema)
    assert contracts.strict_compatibility_issues(schema) == []


@pytest.mark.parametrize("key", sorted(k for k in STEP_INPUTS if not k.startswith("_")))
def test_synthetic_step_inputs_are_valid_and_self_consistent(key):
    assert contracts.check_step_input(STEP_INPUTS[key]) == []


def test_step_input_allowlist_must_resolve_to_its_own_records():
    broken = json.loads(json.dumps(STEP_INPUTS["A_answer"]))
    broken["allowlist"]["passage_ids"].append("psg_SYNB1pg001")
    codes = {i.code for i in contracts.check_step_input(broken)}
    assert codes == {"allowlist_without_record"}


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_fake_output_case(case):
    step_input = STEP_INPUTS[case["step_input"]]
    raw = case.get("output_raw", case.get("output"))
    report = contracts.validate_model_output(step_input, raw)
    assert report.ok is case["expect_ok"], [vars(i) for i in report.issues]
    assert report.codes() == sorted(case["expect_codes"])
    if "expect_warnings" in case:
        assert [w.code for w in report.warnings] == case["expect_warnings"]


def test_cross_research_passage_is_rejected_even_though_it_exists_elsewhere():
    """T08 (P1 part): a passage in research B's records is not citable from A."""
    b_passages = {p["passage_id"] for p in STEP_INPUTS["B_answer"]["passages"]}
    case = next(c for c in CASES if c["name"] == "answer_cross_research_passage")
    cited = case["output"]["claims"][0]["passage_ids"][0]
    assert cited in b_passages
    report = contracts.validate_model_output(STEP_INPUTS["A_answer"], case["output"])
    assert "unknown_passage_id" in report.codes()


def test_abstract_evidence_link_has_no_page_and_depth_comes_from_records():
    """T02 (P1 part): locator and reading depth are backend-derived, never model-supplied."""
    step_input = STEP_INPUTS["A_answer"]
    draft = next(c for c in CASES if c["name"] == "answer_valid")["output"]
    links = {l["passage_id"]: l for l in contracts.derive_evidence_links(step_input, draft)}
    abstract_link = links["psg_SYNA1abs01"]
    assert abstract_link["reading_depth"] == "abstract"
    assert abstract_link["locator"] == {"kind": "abstract", "physical_page": None, "printed_label": None}
    page_link = links["psg_SYNA1pg003"]
    assert page_link["locator"]["physical_page"] == 3 and page_link["locator"]["printed_label"] == "129"
    assert all(l["semantic_review"] == "not_checked" for l in links.values())


def test_evidence_stays_on_inspected_version():
    """T03 (P1 part): a preprint passage links to the preprint, not the published version."""
    step_input = STEP_INPUTS["A_answer"]
    draft = next(c for c in CASES if c["name"] == "answer_valid")["output"]
    link = next(l for l in contracts.derive_evidence_links(step_input, draft) if l["passage_id"] == "psg_SYNA3pg002")
    assert link["source_id"] == "srv_SYNA3pre01"
    families = {s["source_id"]: s["work_id"] for s in step_input["sources"]}
    assert families["srv_SYNA3pre01"] == families["srv_SYNA3pub01"]


def test_stale_scope_result_is_not_applied_as_current():
    """T18 (P1 part)."""
    assert result_applicability(1, 1) == "current"
    assert result_applicability(1, 2) == "stale_scope"


def test_schema_repair_is_bounded_to_one_attempt():
    assert after_invalid_output(0) == "repair"
    assert after_invalid_output(1) == "store_unverified_draft"


def test_user_selection_overrides_model_screening_proposal():
    proposals = {"cnd_SYNA1cand": "include", "cnd_SYNA2cand": "uncertain", "cnd_SYNA4cand": "exclude"}
    user = {"cnd_SYNA4cand": "included", "cnd_SYNA1cand": "excluded"}
    selection = effective_selection(proposals, user)
    assert selection["cnd_SYNA4cand"] == {"state": "included", "origin": "user"}
    assert selection["cnd_SYNA1cand"] == {"state": "excluded", "origin": "user"}
    assert selection["cnd_SYNA2cand"] == {"state": "pending", "origin": "model_proposal"}


def test_stale_edit_cannot_overwrite_newer_human_version():
    check_expected_version(4, 4)
    with pytest.raises(RevisionConflict):
        check_expected_version(3, 4)
