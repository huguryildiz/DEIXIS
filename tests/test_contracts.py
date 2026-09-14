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


@pytest.mark.parametrize("query, ambiguous", [
    ('"molecular communication" optimization OR "operations research"', True),  # live: same count as the phrase alone
    ('"molecular communication" AND optimization OR scheduling', True),
    ("molecular communication optimization OR scheduling", True),
    ('"molecular communication" (optimization OR scheduling)', True),
    ('"molecular communication" AND (optimization OR (scheduling AND delay))', False),
    ('"molecular communication" AND (optimization OR scheduling)', False),  # live: 308 relevant works
    ('"molecular communication" optimization', False),  # adjacency without OR acts as AND
    ("optimization OR scheduling OR allocation", False),
    ("molecular communication or optimization", False),  # lowercase or is an ordinary word
    ('"molecular communication" AND (optimization OR scheduling', True),
])
def test_openalex_query_with_ambiguous_or_is_rejected(query, ambiguous):
    plan = json.loads(json.dumps(next(c for c in CASES if c["name"] == "search_plan_valid")["output"]))
    result = plan["search_plan"] if "search_plan" in plan else plan
    result["queries"][0].update(provider_id="openalex", query_text=query)
    report = contracts.validate_model_output(STEP_INPUTS["A_search_plan"], plan)
    assert ("provider_query_syntax" in report.codes()) is ambiguous


def test_answer_steps_show_short_handles_that_map_back_to_records():
    step_input = STEP_INPUTS["A_answer"]
    shown = contracts.with_citation_handles(step_input)
    assert [p["passage_id"] for p in shown["passages"]] == [f"psg_P{n:07d}" for n in range(1, len(step_input["passages"]) + 1)]
    assert set(shown["allowlist"]["source_ids"]) == {s["source_id"] for s in shown["sources"]}
    assert contracts.check_step_input(shown) == []  # handles still satisfy the StepInput schema

    first, source = shown["passages"][0], shown["sources"][0]
    answer = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    answer["claims"] = [dict(answer["claims"][0], passage_ids=[first["passage_id"]])]
    answer["limitations"] = [dict(answer["limitations"][0], source_ids=[source["source_id"]])] if answer["limitations"] else []
    resolved = contracts.resolve_citation_handles(step_input, json.dumps(answer))
    report = contracts.validate_model_output(step_input, resolved)
    assert not {"unknown_passage_id", "unknown_source_id"} & set(report.codes()), report.issues
    assert contracts.derive_evidence_links(step_input, resolved)[0]["passage_id"] == step_input["passages"][0]["passage_id"]

    swapped = "psg_" + source["source_id"].removeprefix("srv_")  # the live copy error: a source suffix under the passage prefix
    answer["claims"][0]["passage_ids"] = [swapped]
    report = contracts.validate_model_output(step_input, contracts.resolve_citation_handles(step_input, json.dumps(answer)))
    assert "unknown_passage_id" in report.codes()


def test_answer_review_must_review_every_claim_once_by_label():
    step_input = json.loads(json.dumps(STEP_INPUTS["A_answer"]))
    first = step_input["passages"][0]["passage_id"]
    step_input.update(task_type="answer_review", output_schema_versions=["deixis.answer_review.v1"], claims_under_review=[
        {"claim_label": label, "text": "SYNTHETIC claim", "support_type": "source_stated", "passage_ids": [first]} for label in ("c1", "c2")
    ])
    assert contracts.check_step_input(step_input) == []
    assert "claims_under_review" in json.dumps(contracts.with_citation_handles(step_input))

    envelope = {"schema_version": "deixis.answer_review.v1"} | {k: step_input[k] for k in contracts.ENVELOPE_FIELDS}
    verdict = {"verdict": "partially_supported", "reason": "SYNTHETIC reason"}
    valid = envelope | {"reviews": [{"claim_label": "c1"} | verdict, {"claim_label": "c2"} | verdict], "notes": ""}
    assert contracts.validate_model_output(step_input, valid).ok
    broken = envelope | {"reviews": [{"claim_label": "c1"} | verdict, {"claim_label": "c1"} | verdict, {"claim_label": "c9"} | verdict], "notes": ""}
    assert {"duplicate_claim_review", "unknown_claim_label", "claim_without_review"} <= set(contracts.validate_model_output(step_input, broken).codes())

    step_input["claims_under_review"][0]["passage_ids"] = ["psg_notInThisStepInput"]
    assert "review_passage_missing" in {i.code for i in contracts.check_step_input(step_input)}


@pytest.mark.parametrize("query, rejected", [
    ("molecular communication resource allocation scheduling routing optimization", True),  # live: 4 works, 0 of 22 known
    ('"molecular communication" AND (routing OR scheduling) AND (optimization OR algorithm)', True),  # three required parts
    ('"molecular communication" AND (a OR b OR c OR d OR e OR f)', True),  # six operators
    ('"molecular communication" AND ("resource allocation" OR scheduling)', False),  # live: 5 known papers in the top 25
    ('"molecular communication" optimization', False),
    ("optimization OR scheduling OR allocation", False),  # one OR group is one required part
    ('"molecular communication" AND (optimization OR (scheduling AND delay))', False),
])
def test_openalex_query_shape_is_limited(query, rejected):
    plan = json.loads(json.dumps(next(c for c in CASES if c["name"] == "search_plan_valid")["output"]))
    result = plan["search_plan"] if "search_plan" in plan else plan
    result["queries"][0].update(provider_id="openalex", query_text=query)
    report = contracts.validate_model_output(STEP_INPUTS["A_search_plan"], plan)
    assert (any(i.code == "provider_query_shape" and i.path == "/queries/0/query_text" for i in report.issues)) is rejected


def test_openalex_plan_without_a_quoted_core_phrase_is_rejected():
    plan = json.loads(json.dumps(next(c for c in CASES if c["name"] == "search_plan_valid")["output"]))
    for query in plan["search_plan"]["queries"]:
        query["query_text"] = "optimization OR scheduling"
    report = contracts.validate_model_output(STEP_INPUTS["A_search_plan"], plan)
    assert any(i.code == "provider_query_shape" and i.path == "/queries" for i in report.issues)


@pytest.mark.parametrize("text", [
    "Equation 4 on page 12 proves convergence.", "The bound holds (Eq. (7)).", "Table 2 lists the delays.",
    "As shown in Fig. 3, error falls.", "Section 4.2 derives the rule.", "See 10.1234/abc.def for the proof.",
    "Sayfa 5'teki denklem 3 bunu gösterir.", "Şekil 2 hatanın azaldığını gösterir.",
])
def test_claim_text_with_its_own_locator_is_rejected(text):
    """T02 (code part): an answer may not assert a page, equation, table, figure, section or DOI in claim text."""
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["claims"][0]["text"] = text
    report = contracts.validate_model_output(STEP_INPUTS["A_answer"], draft)
    assert "locator_in_claim_text" in report.codes()


@pytest.mark.parametrize("text", [
    "It has been reported that release timing is optimized with a lookup table approach.",
    "It has been reported that two-page summaries were not used.",
    "It has been reported that the 5G section of the network uses 3 relays.",
    "It has been reported that performance improved by 10.5 percent.",
])
def test_ordinary_claim_text_is_not_mistaken_for_a_locator(text):
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["claims"][0]["text"] = text
    assert contracts.validate_model_output(STEP_INPUTS["A_answer"], draft).ok


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
