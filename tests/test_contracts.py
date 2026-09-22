"""P1 deterministic contract tests with synthetic inputs and fake model outputs.

Passing these tests shows schema, identifier-scope and version rules hold in code.
It does not show that any model follows the method package.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from deixis.domain import contracts
from deixis.providers import query_rules
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


@pytest.mark.parametrize("name", ["ReportPlanDraft", "ReportSectionDraft", "ReportPhraseRepairDraft", "ReportReview"])
def test_new_report_schemas_are_valid_draft_2020_12_and_registered(name):
    assert name in contracts.SCHEMA_FILES
    Draft202012Validator.check_schema(contracts.load_schema(name))


def test_report_task_types_are_registered():
    for task in ("report_plan", "report_section", "report_phrase_repair", "report_review"):
        assert task in contracts.TASK_OUTPUTS
    assert contracts.SCHEMA_FILES["ReportPlanDraft"] == "report-plan.schema.json"
    assert contracts.SCHEMA_FILES["ReportSectionDraft"] == "report-section-draft.schema.json"
    assert contracts.SCHEMA_FILES["ReportPhraseRepairDraft"] == "report-phrase-repair.schema.json"
    assert contracts.SCHEMA_FILES["ReportReview"] == "report-review.schema.json"


def test_report_step_input_requires_report_target_only_for_report_tasks():
    si = json.loads(json.dumps(STEP_INPUTS["A_search_plan"]))
    si["allowlist"]["column_ids"] = []
    assert contracts.check_step_input(si) == []
    si["task_type"] = "report_plan"
    si["output_schema_versions"] = ["deixis.report_plan_draft.v2"]
    issues = {i.code for i in contracts.check_step_input(si)}
    assert "report_target_mismatch" in issues


def test_report_target_requires_frozen_cells_and_gap_candidates():
    si = json.loads(json.dumps(STEP_INPUTS["C_report_section_IV"]))
    del si["report_target"]["cells"]
    assert "step_input_schema_invalid" in {issue.code for issue in contracts.check_step_input(si)}


def test_report_target_column_ids_are_unique():
    si = json.loads(json.dumps(STEP_INPUTS["C_report_plan"]))
    si["report_target"]["columns"].append(dict(si["report_target"]["columns"][0]))

    assert "duplicate_report_column" in {issue.code for issue in contracts.check_step_input(si)}


def test_report_plan_column_roles_must_come_from_the_step_allowlist():
    si = STEP_INPUTS["C_report_plan"]
    draft = json.loads(json.dumps(next(case for case in CASES if case["name"] == "report_plan_valid")["output"]))
    assert contracts.validate_model_output(si, draft).ok

    draft["limitations_column_id"] = "col_NOTGIVEN01"
    assert contracts.validate_model_output(si, draft).codes() == ["limitations_column_not_in_allowlist"]


@pytest.mark.parametrize(("passage_id", "cell_id", "expect_ok"), [
    ("psg_SYNA1abs01", None, True),
    ("psg_SYNA1abs01", "cel_SYNTHR0001", False),
    (None, None, False),
])
def test_report_citation_anchor_names_exactly_one_target(passage_id, cell_id, expect_ok):
    si = STEP_INPUTS["C_report_section_IV"]
    draft = json.loads(json.dumps(next(case for case in CASES if case["name"] == "report_section_valid")["output"]))
    draft["citation_anchors"][0]["passage_id"] = passage_id
    draft["citation_anchors"][0]["cell_id"] = cell_id

    report = contracts.validate_model_output(si, draft)

    assert report.ok is expect_ok
    if not expect_ok:
        assert report.codes() == ["citation_anchor_target_count"]
        assert report.issues[0].path == "/citation_anchors/0"


def test_report_cell_must_be_present_in_the_step_input_allowlist_and_records():
    si = json.loads(json.dumps(STEP_INPUTS["C_report_section_IV"]))
    cell = {
        "cell_id": "cel_SYNTHR0001", "cell_revision_id": "crv_SYNTHR0001", "column_id": "col_SYNTHR0001",
        "source_version_id": "srv_SYNA1pub01", "state": "value", "value": {"text": "SYNTHETIC value"},
        "reading_depth": "full_text", "evidence": [{"passage_id": "psg_SYNA1pg003",
                                                    "quote": "SYNTHETIC. The objective minimizes expected bit error probability"}],
    }
    si["report_target"]["cells"] = [cell]
    si["allowlist"]["cell_ids"] = [cell["cell_id"]]
    si["allowlist"]["column_ids"] = [cell["column_id"]]
    assert contracts.check_step_input(si) == []
    si["allowlist"]["cell_ids"] = []
    assert "report_cell_not_allowed" in {issue.code for issue in contracts.check_step_input(si)}
    si["allowlist"]["cell_ids"] = [cell["cell_id"]]
    si["report_target"]["cells"] = []
    assert "allowlist_without_record" in {issue.code for issue in contracts.check_step_input(si)}


def test_report_cell_evidence_passage_must_be_in_the_step_input_allowlist():
    si = json.loads(json.dumps(STEP_INPUTS["C_report_section_IV"]))
    passage = si["passages"][0]
    si["report_target"]["cells"] = [{
        "cell_id": "cel_SYNTHR0001", "cell_revision_id": "crv_SYNTHR0001", "column_id": "col_SYNTHR0001",
        "source_version_id": passage["source_id"], "state": "value", "value": {"text": "SYNTHETIC value"},
        "reading_depth": "abstract", "evidence": [{"passage_id": "psg_NOTGIVEN001", "quote": "SYNTHETIC quote"}],
    }]
    si["allowlist"]["cell_ids"] = ["cel_SYNTHR0001"]
    si["allowlist"]["column_ids"] = ["col_SYNTHR0001"]

    issues = contracts.check_step_input(si)

    assert "report_cell_passage_not_allowed" in {issue.code for issue in issues}


def test_report_gap_candidate_basis_must_be_in_the_frozen_cells():
    si = json.loads(json.dumps(STEP_INPUTS["C_report_section_VII"]))
    si["report_target"]["section_id"] = "VI"
    si["allowlist"]["column_ids"] = ["col_SYNTHR0001"]
    si["allowlist"]["gap_ids"] = ["gap1"]
    si["report_target"]["gap_candidates"] = [{
        "gap_id": "gap1", "kind": "corpus_absence", "column_id": "col_SYNTHR0001",
        "basis_cell_ids": ["cel_SYNTHR0001", "cel_SYNTHR0002", "cel_SYNTHR0003"],
        "full_text_applicable_count": 3, "summary_only_count": 0,
    }]
    codes = {issue.code for issue in contracts.check_step_input(si)}
    assert "gap_basis_cell_missing" in codes


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


def test_evidence_links_keep_the_located_passage_words():
    links = contracts.derive_evidence_links(STEP_INPUTS["A_answer"], next(c for c in CASES if c["name"] == "answer_valid")["output"])
    assert all(l["anchor_match"] == "exact" and l["anchor_text"] for l in links)


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


def test_answer_title_has_a_strict_fifteen_word_ceiling():
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["title"] = " ".join(f"word{n}" for n in range(16))
    report = contracts.validate_model_output(STEP_INPUTS["A_answer"], draft)
    assert report.codes() == ["answer_title_too_long"]
    assert report.issues[0].path == "/title"

    draft["title"] = " ".join(f"word{n}" for n in range(15))
    assert contracts.validate_model_output(STEP_INPUTS["A_answer"], draft).ok


def test_a_schema_error_does_not_hide_the_semantic_issues_a_repair_must_also_fix():
    """One repair is all a step gets, so the first report must name every issue: the schema error and the rule
    breaches behind it. Slice 13a's fifth smoke run lost its answer to a section too long, then a title too long."""
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["claims"][0]["section"] = "s" * 121
    draft["title"] = " ".join(f"word{n}" for n in range(16))
    report = contracts.validate_model_output(STEP_INPUTS["A_answer"], draft)
    assert not report.ok
    assert "schema_invalid" in report.codes() and "answer_title_too_long" in report.codes()
    assert [i.code for i in report.issues][0] == "schema_invalid"  # the shape first, then the rules


def test_semantic_checks_on_a_schema_invalid_draft_never_raise():
    draft = {"title": " ".join(f"word{n}" for n in range(16))}  # nothing else the answer checks expect
    report = contracts.validate_model_output(STEP_INPUTS["A_answer"], draft)
    assert not report.ok and "schema_invalid" in report.codes()


def test_research_title_rejects_long_titles_and_verbatim_question():
    si = {"question": {"text": "What is the effect of X on Y?"}}
    report = contracts.ValidationReport()
    contracts._check_title(si, {"title": " ".join(f"word{n}" for n in range(16))}, report)
    assert report.codes() == ["title_too_long"]

    report = contracts.ValidationReport()
    contracts._check_title(si, {"title": si["question"]["text"]}, report)
    assert report.codes() == ["title_copies_question"]

    report = contracts.ValidationReport()
    contracts._check_title(si, {"title": "  "}, report)
    assert report.codes() == ["title_empty"]


def test_anchor_for_a_passage_the_claim_does_not_cite_is_still_an_issue():
    step_input = STEP_INPUTS["A_answer"]
    draft = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    draft["citation_anchors"][0]["passage_id"] = "psg_SYNA3pg002"  # cited by c3, not by c1
    assert contracts.validate_model_output(step_input, draft).codes() == ["anchor_passage_not_cited", "missing_citation_anchor"]


PDF_TEXT = ("SYNTHETIC. Earlier text.\nThe bit error probability is p e = Q( √ 2 E b /N 0 ) for each\n"
            "release, and the objec-\ntive minimizes it under a mol-\necule budget per frame. Later text.")


@pytest.mark.parametrize("quote, kind", [
    ("The bit error probability is p e = Q( √ 2 E b /N 0 ) for each release,", "exact"),
    ("The bit error probability is pe = Q(√2Eb/N0) for each release, and the objective minimizes it under a molecule budget per frame.", "normalized"),
    ("The bit error probability is pe = Q(√2Eb/NO) for each release, and the objective minimises it under a molecule budget per frame.", "fuzzy"),
])
def test_quote_is_located_despite_pdf_extraction_damage_and_keeps_the_passage_words(quote, kind):
    match = contracts.locate_anchor(quote, PDF_TEXT)
    assert match is not None and match.kind == kind
    assert match.text.startswith("The bit error probability") and match.text in PDF_TEXT


@pytest.mark.parametrize("quote", [
    "Die Bitfehlerwahrscheinlichkeit wird unter einem Molekülbudget pro Rahmen minimiert.",
    "The bit error probability is minimized under a molecule budget per frame.",  # two spans joined into one
])
def test_translated_or_spliced_quote_is_not_located(quote):
    assert contracts.locate_anchor(quote, PDF_TEXT) is None


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
    assert query_rules.openalex_or_is_ambiguous(query) is ambiguous


def test_answer_steps_show_short_handles_that_map_back_to_records():
    step_input = STEP_INPUTS["A_answer"]
    shown = contracts.with_citation_handles(step_input)
    assert [p["passage_id"] for p in shown["passages"]] == [f"psg_P{n:07d}" for n in range(1, len(step_input["passages"]) + 1)]
    assert set(shown["allowlist"]["source_ids"]) == {s["source_id"] for s in shown["sources"]}
    assert contracts.check_step_input(shown) == []  # handles still satisfy the StepInput schema

    first, source = shown["passages"][0], shown["sources"][0]
    answer = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    answer["claims"] = [dict(answer["claims"][0], passage_ids=[first["passage_id"]])]
    answer["citation_anchors"] = [{"claim_label": "c1", "passage_id": first["passage_id"], "quote": first["text"]}]
    answer["limitations"] = [dict(answer["limitations"][0], source_ids=[source["source_id"]])] if answer["limitations"] else []
    resolved = contracts.resolve_citation_handles(step_input, json.dumps(answer))
    report = contracts.validate_model_output(step_input, resolved)
    assert not {"unknown_passage_id", "unknown_source_id"} & set(report.codes()), report.issues
    assert contracts.derive_evidence_links(step_input, resolved)[0]["passage_id"] == step_input["passages"][0]["passage_id"]
    assert resolved["citation_anchors"][0]["passage_id"] == step_input["passages"][0]["passage_id"]

    swapped = "psg_" + source["source_id"].removeprefix("srv_")  # the live copy error: a source suffix under the passage prefix
    answer["claims"][0]["passage_ids"] = [swapped]
    report = contracts.validate_model_output(step_input, contracts.resolve_citation_handles(step_input, json.dumps(answer)))
    assert "unknown_passage_id" in report.codes()


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


def test_salvage_drops_repeated_stray_and_unquoted_citations_but_not_a_claim_left_without_evidence():
    step_input = STEP_INPUTS["A_answer"]
    first, second = step_input["passages"][0], step_input["passages"][1]
    quote = lambda p: " ".join(p["text"].split())[:200]
    answer = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    answer["claims"] = [dict(answer["claims"][0], claim_label="c1", passage_ids=[first["passage_id"], second["passage_id"]]),
                        dict(answer["claims"][0], claim_label="c2", passage_ids=[second["passage_id"]])]
    answer["citation_anchors"] = [{"claim_label": "c1", "passage_id": first["passage_id"], "quote": "SYNTHETIC words that are in no passage"},
                                  {"claim_label": "c1", "passage_id": first["passage_id"], "quote": quote(first)},
                                  {"claim_label": "c2", "passage_id": first["passage_id"], "quote": quote(first)}]
    before = contracts.validate_model_output(step_input, json.loads(json.dumps(answer)))
    assert {"duplicate_citation_anchor", "missing_citation_anchor", "anchor_passage_not_cited"} <= set(before.codes())
    salvaged, warnings = contracts.salvage_answer_draft(step_input, json.loads(json.dumps(answer)))
    assert salvaged["claims"][0]["passage_ids"] == [first["passage_id"]]
    assert salvaged["citation_anchors"] == [{"claim_label": "c1", "passage_id": first["passage_id"], "quote": quote(first)}]
    assert {w.code for w in warnings} == {"duplicate_citation_anchor_ignored", "uncited_anchor_ignored", "citation_without_quote_removed"}
    # c2 has no quoted citation left to keep, so the draft stays invalid.
    assert contracts.validate_model_output(step_input, salvaged).codes() == ["missing_citation_anchor"]


def test_a_handle_with_extra_leading_zeros_resolves_to_its_record():
    step_input = STEP_INPUTS["A_answer"]
    answer = json.loads(json.dumps(next(c for c in CASES if c["name"] == "answer_valid")["output"]))
    answer["claims"] = [dict(answer["claims"][0], passage_ids=["psg_P00000001"])]
    answer["citation_anchors"] = [{"claim_label": "c1", "passage_id": "psg_P000001", "quote": "SYNTHETIC quote"}]
    resolved = contracts.resolve_citation_handles(step_input, json.dumps(answer))
    assert resolved["claims"][0]["passage_ids"] == [step_input["passages"][0]["passage_id"]]
    assert resolved["citation_anchors"][0]["passage_id"] == step_input["passages"][0]["passage_id"]


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
    assert bool(query_rules.openalex_query_shape_issues(query)) is rejected


def search_plan(concepts, providers, step_input=STEP_INPUTS["A_search_plan"]):
    output = json.loads(json.dumps(next(c for c in CASES if c["name"] == "search_plan_valid")["output"]))
    output["search_plan"].update(concepts=concepts, providers=providers)
    return contracts.validate_model_output(step_input, output)


def test_search_plan_needs_exactly_one_core_concept():
    method = {"label": "integer programming", "role": "method", "synonyms": ["integer programming"]}
    assert "core_concept_count" in search_plan([method], ["openalex"]).codes()
    core = {"label": "moleküler haberleşme", "role": "core", "synonyms": ["molecular communication"]}
    assert "core_concept_count" in search_plan([core, dict(core, label="nano networks"), method], ["openalex"]).codes()
    assert search_plan([core, method], ["openalex"]).ok
    # Synonyms are the search terms; the label is display text, so a core without synonyms goes back for repair.
    assert "core_without_synonyms" in search_plan([dict(core, synonyms=[]), method], ["openalex"]).codes()


def test_search_plan_from_which_no_query_can_be_built_goes_back_for_repair():
    step_input = json.loads(json.dumps(STEP_INPUTS["A_search_plan"]))
    step_input["enabled_providers"] = ["core", "serpapi"]
    core = {"label": "molecular communication", "role": "core", "synonyms": ["molecular communication"]}
    # CORE answers a quoted phrase without AND with an error, so a core concept alone gives it no query.
    assert search_plan([core], ["core"], step_input).codes() == ["no_compiled_query"]
    assert search_plan([core, {"label": "scheduling", "role": "method", "synonyms": ["scheduling"]}], ["core"], step_input).ok
    assert search_plan([core], ["serpapi"], step_input).codes() == ["supplementary_provider_limit"]
    assert "duplicate_provider" in search_plan([core], ["openalex", "openalex"]).codes()


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
