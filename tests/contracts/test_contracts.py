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
    result_applicability,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "research"
STEP_INPUTS = json.loads((FIXTURES / "step-inputs.json").read_text())
CASES = json.loads((FIXTURES / "fake-outputs.json").read_text())["cases"]


def test_canonical_schemas_are_valid_draft_2020_12():
    for name in contracts.SCHEMA_FILES:
        Draft202012Validator.check_schema(contracts.load_schema(name))


def test_report_passage_anchor_must_be_located():
    si = json.loads(json.dumps(STEP_INPUTS["C_report_section_IV"]))
    draft = json.loads(json.dumps(next(case for case in CASES if case["name"] == "report_section_valid")["output"]))
    draft["citation_anchors"][0]["quote"] = "SYNTHETIC words absent from every passage"
    assert "anchor_not_in_passage" in contracts.validate_model_output(si, draft).codes()


def test_report_cell_anchor_must_be_in_one_stored_quote():
    si = json.loads(json.dumps(STEP_INPUTS["C_report_section_IV"]))
    draft = json.loads(json.dumps(next(case for case in CASES if case["name"] == "report_section_valid")["output"]))
    cell_id = "cel_SYNTHR0001"
    si["report_target"]["cells"] = [{"cell_id": cell_id, "cell_revision_id": "crv_SYNTHR0001",
        "column_id": "col_SYNTHR0001", "source_version_id": si["passages"][0]["source_id"],
        "state": "value", "value": {"text": "value"}, "reading_depth": "abstract",
        "evidence": [{"passage_id": si["passages"][0]["passage_id"], "quote": "first words"},
                     {"passage_id": si["passages"][0]["passage_id"], "quote": "second words"}]}]
    si["allowlist"]["cell_ids"] = [cell_id]
    draft["claims"][0]["cell_ids"] = [cell_id]
    draft["citation_anchors"].append({"claim_key": draft["claims"][0]["claim_key"],
        "passage_id": None, "cell_id": cell_id, "quote": "words second"})
    assert "anchor_not_in_cell_evidence" in contracts.validate_model_output(si, draft).codes()


def test_step_output_schema_is_self_contained_and_strict():
    for task_type in sorted(contracts.TASK_OUTPUTS):
        schema = contracts.step_output_schema(task_type)
        Draft202012Validator.check_schema(schema)
        assert "common.schema.json" not in json.dumps(schema), task_type
        assert contracts.strict_compatibility_issues(schema) == [], task_type


def test_synthetic_step_inputs_are_valid_and_self_consistent():
    issues = {key: [vars(i) for i in contracts.check_step_input(si)] for key, si in sorted(STEP_INPUTS.items())
              if not key.startswith("_")}
    assert {key: found for key, found in issues.items() if found} == {}


def test_fake_valid_response_passes_every_fixture_step_contract():
    """tests/support/fakes.py::valid_response must keep matching the schemas (CLAUDE.md: a schema change updates it)."""
    from fakes import valid_response

    failed = {}
    for key, si in sorted(STEP_INPUTS.items()):
        if key.startswith("_"):
            continue
        report = contracts.validate_model_output(si, valid_response(si))
        if not report.ok:
            failed[key] = report.codes()
    assert failed == {}


def test_step_input_allowlist_must_resolve_to_its_own_records():
    broken = json.loads(json.dumps(STEP_INPUTS["A_answer"]))
    broken["allowlist"]["passage_ids"].append("psg_SYNB1pg001")
    codes = {i.code for i in contracts.check_step_input(broken)}
    assert codes == {"allowlist_without_record"}


def test_fake_output_case():
    """Every case in tests/fixtures/research/fake-outputs.json gives its expected verdict, codes and warnings."""
    wrong = {}
    for case in CASES:
        report = contracts.validate_model_output(STEP_INPUTS[case["step_input"]], case.get("output_raw", case.get("output")))
        got = {"ok": report.ok, "codes": report.codes()}
        want = {"ok": case["expect_ok"], "codes": sorted(case["expect_codes"])}
        if "expect_warnings" in case:
            got["warnings"], want["warnings"] = [w.code for w in report.warnings], case["expect_warnings"]
        if got != want:
            wrong[case["name"]] = (got, want)
    assert len(CASES) > 50 and wrong == {}


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


def test_quote_not_found_in_the_cited_passage_rejects_the_draft_and_the_link_has_no_anchor():
    step_input = STEP_INPUTS["A_answer"]
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["citation_anchors"][0]["quote"] = "SYNTHETIC. This sentence was not present in the cited passage."
    report = contracts.validate_model_output(step_input, draft)
    assert not report.ok and report.codes() == ["anchor_not_in_passage"]
    link = contracts.derive_evidence_links(step_input, draft)[0]
    assert (link["anchor_text"], link["anchor_match"]) == (None, None)


def test_missing_citation_anchor_rejects_the_draft():
    step_input = STEP_INPUTS["A_answer"]
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["citation_anchors"].pop()
    report = contracts.validate_model_output(step_input, draft)
    assert not report.ok and report.codes() == ["missing_citation_anchor"]
    assert "psg_" in report.issues[0].message


PDF_TEXT = ("SYNTHETIC. Earlier text.\nThe bit error probability is p e = Q( √ 2 E b /N 0 ) for each\n"
            "release, and the objec-\ntive minimizes it under a mol-\necule budget per frame. Later text.")


@pytest.mark.parametrize("quote, kind", [
    ("The bit error probability is p e = Q( √ 2 E b /N 0 ) for each release,", "exact"),
    ("The bit error probability is pe = Q(√2Eb/NO) for each release, and the objective minimises it under a molecule budget per frame.", "fuzzy"),
])
def test_quote_is_located_despite_pdf_extraction_damage_and_keeps_the_passage_words(quote, kind):
    match = contracts.locate_anchor(quote, PDF_TEXT)
    assert match is not None and match.kind == kind
    assert match.text.startswith("The bit error probability") and match.text in PDF_TEXT


@pytest.mark.parametrize("quote", [
    "The bit error probability is minimized under a molecule budget per frame.",  # two spans joined into one
])
def test_translated_or_spliced_quote_is_not_located(quote):
    assert contracts.locate_anchor(quote, PDF_TEXT) is None


def test_handles_written_into_answer_text_are_replaced_by_source_titles():
    step_input = STEP_INPUTS["A_answer"]
    shown = contracts.with_citation_handles(step_input)
    first, source = shown["passages"][0], shown["sources"][0]
    title = step_input["sources"][0]["title"]
    passage_title = next(s["title"] for s in step_input["sources"] if s["source_id"] == step_input["passages"][0]["source_id"])
    answer = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    answer["claims"] = [dict(answer["claims"][0], passage_ids=[first["passage_id"]], text=f"SYNTHETIC claim ({first['passage_id']}).")]
    answer["limitations"] = [{"kind": "access", "source_ids": [source["source_id"]], "text": f"{source['source_id']} is read from its abstract only."}]
    answer["unanswered_aspects"] = [f"Nothing in {source['source_id']}, {first['passage_id']}."]
    resolved = contracts.name_sources_in_prose(step_input, contracts.resolve_citation_handles(step_input, json.dumps(answer)))
    assert resolved["limitations"][0]["text"] == f"“{title}” is read from its abstract only."
    assert resolved["claims"][0]["text"] == f"SYNTHETIC claim (“{passage_title}”)."
    assert resolved["unanswered_aspects"] == [f"Nothing in “{title}”, “{passage_title}”."]
    assert resolved["limitations"][0]["source_ids"] == [step_input["sources"][0]["source_id"]]

    # Titles are put in after validation: a limitation listing many handles stays within the text length limit.
    answer["limitations"][0]["text"] = ", ".join([source["source_id"]] * 30) + " are read from abstracts only."
    resolved = contracts.resolve_citation_handles(step_input, json.dumps(answer))
    assert "schema_invalid" not in contracts.validate_model_output(step_input, resolved).codes()
    assert len(contracts.name_sources_in_prose(step_input, resolved)["limitations"][0]["text"]) > 500


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


def test_stale_edit_cannot_overwrite_newer_human_version():
    check_expected_version(4, 4)
    with pytest.raises(RevisionConflict):
        check_expected_version(3, 4)


