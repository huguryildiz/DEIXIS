"""Synthetic K2 contracts and fake transport only; no model behavior or scientific validation."""

import asyncio
import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from deixis.config import Settings
from deixis.domain import contracts, skill
from deixis.domain.rules import LITERATURE_TASKS, MAX_SCHEMA_REPAIRS, NO_REPAIR_TASKS, schema_repairs, step_model
from deixis.paths import SKILL_DIR
from deixis.storage import db
from deixis.storage.db import transaction
from deixis.workflow.candidates.store import CandidateStore
from deixis.workflow.flow import FlowDeps, HANDLE_TASKS, ResearchFlow, TIMEOUT_RETRIED_TASKS
from deixis.workflow.store import Store
from fakes import FakeAdapter, parse_step_input, valid_response
from test_contracts import CASES, STEP_INPUTS

TASKS = contracts.CANDIDATE_TASKS


def fixture(task="claim_assessment"):
    return copy.deepcopy(STEP_INPUTS["J_" + task])


def output(si=None):
    return json.loads(valid_response(si or fixture()))


def codes(si):
    return {issue.code for issue in contracts.check_step_input(si)}


def verdict(si, draft):
    return contracts.validate_model_output(si, draft)


def evidence(si, n=0):
    p = si["passages"][n]
    return {"passage_id": p["passage_id"], "quote": p["text"]}


def support(si, draft, i=0):
    draft["work_relevance"] = "related"
    draft["cells"][i].update(relation="explicit_support", condition_alignment="aligned", evidence=[evidence(si)])
    return draft


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def test_candidate_schemas_are_registered_strict_and_resolve_their_refs():
    names = ("ClaimDecomposition", "KillSearchQuery", "ClaimAssessment")
    files = ("claim-decomposition.schema.json", "kill-search-query.schema.json", "claim-assessment.schema.json")
    for task, name, filename in zip(TASKS, names, files):
        assert contracts.SCHEMA_FILES[name] == filename
        assert contracts.SCHEMA_VERSIONS[name] == f"deixis.{task}.v1"
        assert contracts.TASK_OUTPUTS[task] == (name,)
        validator = contracts.canonical_validator(name)
        Draft202012Validator.check_schema(validator.schema)
        for node in walk(validator.schema):
            if "$ref" in node:
                assert validator._resolver.lookup(node["$ref"]).contents
        wire = contracts.step_output_schema(task)
        assert "common.schema.json" not in json.dumps(wire)
        assert contracts.strict_compatibility_issues(wire) == []
        Draft202012Validator(wire).validate(output(fixture(task)))
        for node in walk(wire):
            if "$ref" in node:
                assert Draft202012Validator(wire)._resolver.lookup(node["$ref"]).contents
    validator = contracts.canonical_validator("StepInput")
    for node in walk(validator.schema):
        if "$ref" in node:
            assert validator._resolver.lookup(node["$ref"]).contents
    bad = []
    si = fixture("claim_decomposition")
    d = output(si)
    bad.append((si, d | {"extra": True}))
    d["elements"][0]["extra"] = True
    bad.append((si, copy.deepcopy(d)))
    d = output(si)
    bad.append((si, d | {"elements": d["elements"] * 2 + [d["elements"][0]]}))
    bad.append((si, d | {"elements": d["elements"][:1]}))
    si = fixture("kill_search_query")
    d = output(si)
    bad.append((si, d | {"setting_backup": [{"term": "SYNTHETIC"}] * 4}))
    si = fixture()
    d = support(si, output(si))
    bad.append((si, d | {"cells": d["cells"] * 2 + [d["cells"][0]]}))
    d["cells"][0]["evidence"] *= 4
    bad.append((si, copy.deepcopy(d)))
    d = output(si)
    bad.append((si, d | {"whole_claim_evidence": [evidence(si)] * 4}))
    d["cells"][0]["extra"] = True
    bad.append((si, d))
    d = support(si, output(si))
    d["cells"][0]["evidence"][0]["evidence_kind"] = "abstract"
    bad.append((si, d))
    for si, draft in bad:
        assert list(Draft202012Validator(contracts.step_output_schema(si["task_type"])).iter_errors(draft))


@pytest.mark.parametrize("slot", ["target", "version", "element", "basis"])
def test_step_input_schema_accepts_the_fixtures_and_rejects_open_objects(slot):
    si = fixture("claim_decomposition" if slot == "basis" else "claim_assessment")
    contracts.canonical_validator("StepInput").validate(si)
    target = si["candidate_target"]
    where = target if slot == "target" else target["version"] if slot == "version" else (
        target["version"]["elements"][0] if slot == "element" else target["basis"][0])
    where["extra"] = True
    assert "step_input_schema_invalid" in codes(si)
    si = fixture()
    si["task_type"] = "grounded_answer"
    assert "candidate_target_mismatch" in codes(si)


@pytest.mark.parametrize("key", ["J_claim_decomposition", "J_claim_decomposition_owner_text", "J_kill_search_query", "J_claim_assessment"])
def test_fixture_step_inputs_are_clean(key):
    si = copy.deepcopy(STEP_INPUTS[key])
    assert contracts.check_step_input(si) == []
    assert verdict(si, output(si)).ok


@pytest.mark.parametrize("mutation", ["absent", "wrong_task", "candidates", "candidate_ids", "extraction_target",
                                     "report_target", "vocabulary_target", "screening_target", "suggestion_target",
                                     "adjudication_target", "lineage_target"])
def test_check_step_input_rejects_candidate_target_mismatch(mutation):
    si = fixture()
    if mutation == "absent":
        del si["candidate_target"]
    elif mutation == "wrong_task":
        si["task_type"] = "grounded_answer"
    elif mutation == "candidates":
        si["candidates"] = copy.deepcopy(STEP_INPUTS["F_abstract_screening"]["candidates"])
    elif mutation == "candidate_ids":
        si["allowlist"]["candidate_ids"] = ["cnd_SYNTHOTHER01"]
    elif mutation == "extraction_target":
        si[mutation] = {"table_id": "tbl_SYNTHOTHER01", "source_id": None, "columns": [], "passage_scope": None}
    else:
        donor = next(v for v in STEP_INPUTS.values() if isinstance(v, dict) and mutation in v)
        si[mutation] = copy.deepcopy(donor[mutation])
    assert "candidate_target_mismatch" in codes(si)


def test_check_step_input_rejects_candidate_unexpected_field():
    si = fixture()
    si["claims_under_review"] = []
    assert "candidate_unexpected_field" in codes(si)


@pytest.mark.parametrize("task,key", [("claim_decomposition", "element_ids"), ("kill_search_query", "element_ids"),
                                    ("claim_assessment", "cell_ids"), ("claim_assessment", "phrases"),
                                    ("claim_assessment", "column_ids"), ("claim_assessment", "gap_ids")])
def test_check_step_input_rejects_candidate_allowlist_key(task, key):
    si = fixture(task)
    si["allowlist"][key] = []
    assert "candidate_allowlist_key" in codes(si)


@pytest.mark.parametrize("task,mutation", [("claim_decomposition_owner_text", "gap"), ("claim_decomposition_owner_text", "basis"),
                                         ("claim_decomposition", "no_gap")])
def test_check_step_input_rejects_candidate_origin_mismatch(task, mutation):
    si = fixture(task)
    if mutation == "basis":
        si["candidate_target"]["basis"] = [{"kind": "claim", "text": "SYNTHETIC", "passage_id": None}]
    else:
        si["candidate_target"]["gap_kind"] = "corpus_absence" if mutation == "gap" else None
    assert "candidate_origin_mismatch" in codes(si)


@pytest.mark.parametrize("task", TASKS)
def test_check_step_input_rejects_candidate_version_mismatch(task):
    si = fixture(task)
    si["candidate_target"]["version"] = fixture()["candidate_target"]["version"] if task == "claim_decomposition" else None
    assert "candidate_version_mismatch" in codes(si)


@pytest.mark.parametrize("mutation", ["null", "other", "extra_source", "duplicate_source", "not_allowed", "query_set"])
def test_check_step_input_rejects_candidate_assessed_source_mismatch(mutation):
    si = fixture("kill_search_query" if mutation == "query_set" else "claim_assessment")
    target = si["candidate_target"]
    if mutation == "null":
        target["assessed_source_id"] = None
    elif mutation in ("other", "query_set"):
        target["assessed_source_id"] = "srv_SYNTHOTHER01"
    elif mutation == "not_allowed":
        si["allowlist"]["source_ids"] = []
    else:
        source = copy.deepcopy(si["sources"][0])
        if mutation == "extra_source":
            source["source_id"] = "srv_SYNTHOTHER01"
        si["sources"].append(source)
    assert "candidate_assessed_source_mismatch" in codes(si)


@pytest.mark.parametrize("task", TASKS)
def test_check_step_input_rejects_candidate_origin_text_mismatch(task):
    si = fixture(task)
    si["candidate_target"]["origin_text"] = None if task == "claim_decomposition" else "SYNTHETIC"
    assert "candidate_origin_text_mismatch" in codes(si)


@pytest.mark.parametrize("task", ["kill_search_query", "claim_assessment"])
def test_check_step_input_rejects_candidate_basis_mismatch(task):
    si = fixture(task)
    si["candidate_target"]["basis"] = [{"kind": "claim", "text": "SYNTHETIC", "passage_id": None}]
    assert "candidate_basis_mismatch" in codes(si)


@pytest.mark.parametrize("kind,pid", [("passage", None), ("claim", "psg_SYNTHCAND01"), ("cell", "psg_SYNTHCAND01")])
def test_check_step_input_rejects_candidate_basis_shape(kind, pid):
    si = fixture("claim_decomposition")
    si["candidate_target"]["basis"][0].update(kind=kind, passage_id=pid)
    assert "candidate_basis_shape" in codes(si)


def test_check_step_input_rejects_candidate_basis_passage_unknown():
    si = fixture("claim_decomposition")
    si["candidate_target"]["basis"][0]["passage_id"] = "psg_SYNTHOTHER01"
    assert "candidate_basis_passage_unknown" in codes(si)


@pytest.mark.parametrize("field", ["sources", "passages", "both"])
def test_check_step_input_rejects_candidate_no_records(field):
    si = fixture("kill_search_query")
    for key in ("sources", "passages") if field == "both" else [field]:
        si[key] = fixture()[key]
    assert "candidate_no_records" in codes(si)


def test_check_step_input_rejects_candidate_assessment_without_text():
    si = fixture()
    si["passages"] = []
    si["allowlist"]["passage_ids"] = []
    assert "candidate_assessment_without_text" in codes(si)


def test_check_step_input_rejects_candidate_passage_not_assessed_work():
    si = fixture()
    si["passages"][0]["source_id"] = "srv_SYNTHOTHER01"
    assert "candidate_passage_not_assessed_work" in codes(si)


@pytest.mark.parametrize("task", TASKS)
def test_check_step_input_rejects_candidate_passage_count(task):
    si = fixture(task)
    passage = fixture()["passages"][0]
    si["passages"] = [passage | {"passage_id": f"psg_SYNTHCOUNT{i:02d}"} for i in range(25)]
    si["allowlist"]["passage_ids"] = [p["passage_id"] for p in si["passages"]]
    assert "candidate_passage_count" in codes(si)
    si["passages"] = [passage] * 25
    assert "candidate_passage_count" not in codes(si)  # Count unique passages, not duplicate records.


@pytest.mark.parametrize("positions", [[1, 1, 3], [2, 1, 3], [1, 2, 4]])
def test_check_step_input_rejects_candidate_element_positions(positions):
    si = fixture()
    for e, position in zip(si["candidate_target"]["version"]["elements"], positions):
        e["position"] = position
    assert "candidate_element_positions" in codes(si)


def test_check_step_input_rejects_duplicate_candidate_element():
    si = fixture()
    elements = si["candidate_target"]["version"]["elements"]
    elements[1]["element_id"] = elements[0]["element_id"]
    assert "duplicate_candidate_element" in codes(si)


@pytest.mark.parametrize("field,mutation", [("source_ids", "empty"), ("passage_ids", "empty"),
                                          ("element_ids", "absent"), ("element_ids", "empty"),
                                          ("element_ids", "extra"), ("element_ids", "duplicate")])
def test_check_step_input_rejects_candidate_allowlist_mismatch(field, mutation):
    si = fixture()
    allow = si["allowlist"]
    if mutation == "absent":
        del allow[field]
    elif mutation == "empty":
        allow[field] = []
    elif mutation == "extra":
        allow[field].append("ele_SYNTHOTHER01")
    else:
        allow[field].append(allow[field][0])
    assert "candidate_allowlist_mismatch" in codes(si)
    si = fixture()
    si["allowlist"]["element_ids"].reverse()
    assert codes(si) == set()  # Equality is ID membership with no repeats, not presentation order.


@pytest.mark.parametrize("field,key", [("sources", "title"), ("passages", "text"),
                                     ("passages", "source_id"), ("passages", "locator")])
def test_check_step_input_rejects_candidate_conflicting_record(field, key):
    si = fixture()
    duplicate = copy.deepcopy(si[field][0])
    si[field].append(duplicate)
    assert "candidate_conflicting_record" not in codes(si)
    duplicate[key] = {"kind": "abstract", "physical_page": 2, "printed_label": None} if key == "locator" else (
        "srv_SYNTHOTHER01" if key == "source_id" else "SYNTHETIC conflicting record")
    assert "candidate_conflicting_record" in codes(si)


def test_owner_text_target_needs_an_empty_basis():
    si = fixture("claim_decomposition_owner_text")
    assert contracts.check_step_input(si) == []
    si["candidate_target"]["basis"] = [{"kind": "cell", "text": "SYNTHETIC", "passage_id": None}]
    assert "candidate_origin_mismatch" in codes(si)


@pytest.mark.parametrize("code", ["unknown_source_id", "unknown_passage_id", "duplicate_element_ref", "element_ref_order", "blank_text",
                                  "validation_plan_design_terms"])
def test_decomposition_rejected_fixture_codes(code):
    case = next(c for c in CASES if c["name"] == "candidate_decomposition_" + code)
    assert code in verdict(fixture("claim_decomposition"), case["output"]).codes()


def test_decomposition_unknown_source_id():
    si = fixture("claim_decomposition")
    d = output(si)
    d["source_ids"] = ["srv_SYNTHUNKNOWN01"]
    assert "unknown_source_id" in verdict(si, d).codes()


def test_decomposition_unknown_passage_id():
    si = fixture("claim_decomposition")
    d = output(si)
    d["passage_ids"] = ["psg_SYNTHUNKNOWN01"]
    assert "unknown_passage_id" in verdict(si, d).codes()


def test_decomposition_duplicate_element_ref():
    si = fixture("claim_decomposition")
    d = output(si)
    d["elements"][1]["element_ref"] = "e1"
    assert "duplicate_element_ref" in verdict(si, d).codes()


def test_decomposition_element_ref_order():
    si = fixture("claim_decomposition")
    d = output(si)
    d["elements"].reverse()
    assert "element_ref_order" in verdict(si, d).codes()


@pytest.mark.parametrize("field", ["claim_statement", "critical_assumption", "validation_plan", "rationale", "condition", "element",
                                 "nearest_simple_explanation"])
@pytest.mark.parametrize("text", [" \t ", "\u00a0\u2003", "\x00SYNTHETIC", "SYNTHETIC\x00text", "SYNTHETIC\x00", "\x00",
                                 "\ud800", "\udfff"])
def test_decomposition_blank_text(field, text):
    si = fixture("claim_decomposition")
    assert si["candidate_target"]["basis"]  # Exercise text validation without the no-basis rule.
    d = output(si)
    if field == "condition":
        d["conditions"] = [text]
        path = "/conditions/0"
    elif field == "element":
        d["elements"][0]["text"] = text
        path = "/elements/0/text"
    else:
        d[field] = text
        path = "/" + field
    report = verdict(si, d)
    assert report.codes() == (["text_not_encodable"] if text in ("\ud800", "\udfff") else ["blank_text"])
    assert report.issues[0].path == path
    assert "encodable as UTF-8" in report.issues[0].message


def test_decomposition_nearest_explanation_without_basis():
    si = fixture("claim_decomposition_owner_text")
    d = output(si)
    d["nearest_simple_explanation"] = "SYNTHETIC invention"
    assert "nearest_explanation_without_basis" in verdict(si, d).codes()


def test_nearest_explanation_needs_a_shown_basis():
    si = fixture("claim_decomposition_owner_text")
    assert output(si)["nearest_simple_explanation"] is None
    assert verdict(si, output(si)).ok
    d = output(si)
    d["nearest_simple_explanation"] = "SYNTHETIC invention"
    assert "nearest_explanation_without_basis" in verdict(si, d).codes()
    si = fixture("claim_decomposition")
    assert verdict(si, output(si)).ok
    d = output(si)
    d["nearest_simple_explanation"] = None
    assert verdict(si, d).ok


@pytest.mark.parametrize("term", ["protocol", "sample size", "power analysis", "apparatus", "equipment", "instrumentation",
                                  "reagent", "reagents", "randomized", "randomised", "preregistered", "pre-registered"])
def test_decomposition_validation_plan_design_terms(term):
    si = fixture("claim_decomposition")
    d = output(si)
    d["validation_plan"] = "SYNTHETIC: " + term.upper()
    assert "validation_plan_design_terms" in verdict(si, d).codes()


def test_design_terms_are_a_surface_check_only():
    si = fixture("claim_decomposition")
    d = output(si)
    d["validation_plan"] = "SYNTHETIC: choose a protocol."
    assert "validation_plan_design_terms" in verdict(si, d).codes()
    # This screen is superficial. A useless plan without the words passes; content quality is not checked.
    for text in ("SYNTHETIC: do nothing at all.", "SYNTHETIC: tooling and protocolized labels."):
        d["validation_plan"] = text
        assert verdict(si, d).ok


@pytest.mark.parametrize("mutation", ["many", "empty", "syntax", "long", "duplicate", "backup", "blank"])
def test_query_reuses_the_search_query_bounds(mutation):
    si = fixture("kill_search_query")
    d = output(si)
    if mutation == "many":
        d["setting"] = [{"term": f"setting {i}", "kind": "topic", "why": "SYNTHETIC"} for i in range(4)]
        d["task"] = [{"term": f"task {i}", "kind": "other", "why": "SYNTHETIC"} for i in range(3)]
    elif mutation == "empty":
        d["setting"] = []
    elif mutation == "syntax":
        d["task"][0]["term"] = "queue AND delay"
    elif mutation == "long":
        d["task"][0]["term"] = "one two three four five"
    elif mutation == "duplicate":
        d["task"][0]["term"] = d["setting"][0]["term"]
    elif mutation == "backup":
        d["task_backup"] = [{"term": d["setting"][0]["term"]}]
    else:
        d["task"][0]["term"] = "   "
    query = contracts.ValidationReport()
    contracts._check_search_query(d, query)
    candidate_report = verdict(si, d)
    search_si = fixture("kill_search_query")
    search_si["task_type"] = "search_query"
    search_d = d | {"schema_version": "deixis.search_query.v1"}
    search_report = verdict(search_si, search_d)
    assert query.codes() and candidate_report.codes() == search_report.codes()


@pytest.mark.parametrize("task", ["kill_search_query", "search_query"])
@pytest.mark.parametrize("block", ["setting", "task", "setting_backup", "task_backup"])
@pytest.mark.parametrize("text", ["SYNTHETIC\x00term", "\ud800", "\udfff"])
def test_query_terms_and_backups_reject_unstorable_text_at_its_path(task, block, text):
    si = fixture(task) if task == "kill_search_query" else copy.deepcopy(STEP_INPUTS["H_search_query"])
    d = output(si)
    if block.endswith("_backup"):
        d[block] = [{"term": text}]
    else:
        d[block][0]["term"] = text
    report = verdict(si, d)
    expected = "text_not_encodable" if task in TASKS and text in ("\ud800", "\udfff") else "blank_text"
    assert report.codes() == [expected]
    assert report.issues[0].path == f"/{block}/0/term"
    assert "encodable as UTF-8" in report.issues[0].message


@pytest.mark.parametrize("code", ["unknown_element_ref", "duplicate_claim_cell", "claim_cell_missing", "alignment_missing",
                                  "alignment_on_no_match", "support_without_evidence", "unrelated_needs_no_match_cells",
                                  "related_needs_support_cell", "uncertain_needs_uncertain_cell", "whole_claim_without_evidence",
                                  "whole_claim_evidence_without_flag", "whole_claim_needs_related", "unknown_passage_id",
                                  "anchor_not_in_passage", "duplicate_evidence_quote", "blank_text"])
def test_assessment_rejected_fixture_codes(code):
    case = next(c for c in CASES if c["name"] == "candidate_assessment_" + code)
    assert code in verdict(fixture(), case["output"]).codes()


def test_assessment_unknown_element_ref():
    si = fixture()
    d = output(si)
    d["cells"][0]["element_ref"] = "ele_SYNTHUNKNOWN01"
    assert "unknown_element_ref" in verdict(si, d).codes()


def test_assessment_duplicate_claim_cell():
    si = fixture()
    d = output(si)
    d["cells"].append(copy.deepcopy(d["cells"][0]))
    assert "duplicate_claim_cell" in verdict(si, d).codes()


def test_assessment_claim_cell_missing():
    si = fixture()
    d = output(si)
    d["cells"] = d["cells"][:1]
    report = verdict(si, d)
    assert len([i for i in report.issues if i.code == "claim_cell_missing" and i.path == "/cells"]) == 2


def test_every_element_gets_exactly_one_cell():
    si = fixture()
    assert verdict(si, output(si)).ok
    d = output(si)
    d["cells"][1] = copy.deepcopy(d["cells"][0])
    assert {"duplicate_claim_cell", "claim_cell_missing"} <= set(verdict(si, d).codes())


@pytest.mark.parametrize("relation", ["explicit_support", "reasoned_inference", "partial_match"])
def test_assessment_alignment_missing(relation):
    si = fixture()
    d = support(si, output(si))
    d["cells"][0].update(relation=relation, condition_alignment=None)
    assert "alignment_missing" in verdict(si, d).codes()


def test_assessment_alignment_on_no_match():
    si = fixture()
    d = output(si)
    d["cells"][0]["condition_alignment"] = "different_conditions"
    assert "alignment_on_no_match" in verdict(si, d).codes()


@pytest.mark.parametrize("relation", ["explicit_support", "reasoned_inference", "partial_match"])
def test_assessment_support_without_evidence(relation):
    si = fixture()
    d = support(si, output(si))
    d["cells"][0].update(relation=relation, evidence=[])
    assert "support_without_evidence" in verdict(si, d).codes()


def test_assessment_unrelated_needs_no_match_cells():
    si = fixture()
    d = support(si, output(si))
    d["work_relevance"] = "unrelated"
    assert "unrelated_needs_no_match_cells" in verdict(si, d).codes()


def test_assessment_related_needs_support_cell():
    si = fixture()
    d = output(si) | {"work_relevance": "related"}
    assert "related_needs_support_cell" in verdict(si, d).codes()


def test_assessment_uncertain_needs_uncertain_cell():
    si = fixture()
    d = output(si) | {"work_relevance": "uncertain"}
    assert "uncertain_needs_uncertain_cell" in verdict(si, d).codes()


def test_relevance_and_cells_must_agree():
    si = fixture()
    assert verdict(si, output(si)).ok
    d = output(si) | {"work_relevance": "uncertain"}
    for alignment in (None, "aligned", "different_conditions", "unclear"):
        d["cells"][0].update(relation="uncertain", condition_alignment=alignment)
        assert verdict(si, d).ok
    for relation in contracts.CANDIDATE_SUPPORT_RELATIONS:
        for alignment in ("aligned", "different_conditions", "unclear"):
            d = support(si, output(si))
            d["cells"][0].update(relation=relation, condition_alignment=alignment)
            assert verdict(si, d).ok


def test_assessment_whole_claim_without_evidence():
    si = fixture()
    d = support(si, output(si)) | {"states_whole_claim": True}
    assert "whole_claim_without_evidence" in verdict(si, d).codes()


def test_assessment_whole_claim_evidence_without_flag():
    si = fixture()
    d = output(si) | {"whole_claim_evidence": [evidence(si)]}
    assert "whole_claim_evidence_without_flag" in verdict(si, d).codes()


def test_assessment_whole_claim_needs_related():
    si = fixture()
    d = output(si) | {"states_whole_claim": True, "whole_claim_evidence": [evidence(si)]}
    assert "whole_claim_needs_related" in verdict(si, d).codes()


def test_whole_claim_needs_a_located_quote_and_related_relevance():
    si = fixture()
    d = support(si, output(si)) | {"states_whole_claim": True, "whole_claim_evidence": [evidence(si)]}
    assert verdict(si, d).ok
    # Whole-claim coherence with the other cells is deliberately open; K1 cannot close with no-match cells.
    assert d["cells"][1]["relation"] == "no_match_in_supplied_text"
    d["whole_claim_evidence"][0]["quote"] = "SYNTHETIC invented absent words"
    assert "anchor_not_in_passage" in verdict(si, d).codes()


@pytest.mark.parametrize("where", ["cell", "whole"])
def test_assessment_unknown_passage_id(where):
    si = fixture()
    d = support(si, output(si))
    items = d["cells"][0]["evidence"]
    if where == "whole":
        d.update(states_whole_claim=True, whole_claim_evidence=[evidence(si)])
        items = d["whole_claim_evidence"]
    items[0]["passage_id"] = "psg_SYNTHUNKNOWN01"
    assert "unknown_passage_id" in verdict(si, d).codes()


def test_assessment_anchor_not_in_passage():
    si = fixture()
    d = support(si, output(si))
    d["cells"][0]["evidence"][0]["quote"] = "SYNTHETIC nonexistent words absent from all shown text."
    report = verdict(si, d)
    assert "anchor_not_in_passage" in report.codes()
    assert any("the quoted text was not found in the cited passage" in i.message for i in report.issues)


@pytest.mark.parametrize("where", ["cell", "whole"])
def test_assessment_duplicate_evidence_quote(where):
    si = fixture()
    d = support(si, output(si))
    items = d["cells"][0]["evidence"]
    if where == "whole":
        d.update(states_whole_claim=True, whole_claim_evidence=[evidence(si)])
        items = d["whole_claim_evidence"]
    items.append(evidence(si) | {"quote": si["passages"][0]["text"].replace(" ", "  ")})
    assert "duplicate_evidence_quote" in verdict(si, d).codes()


@pytest.mark.parametrize("field", ["note", "nearest_match_summary"])
@pytest.mark.parametrize("text", ["   ", "\u00a0\u2003", "\x00SYNTHETIC", "SYNTHETIC\x00text", "SYNTHETIC\x00", "\x00",
                                 "\ud800", "\udfff"])
def test_assessment_blank_text(field, text):
    si = fixture()
    d = output(si)
    if field == "note":
        d["cells"][0][field] = text
        path = "/cells/0/note"
    else:
        d[field] = text
        path = "/" + field
    report = verdict(si, d)
    assert report.codes() == (["text_not_encodable"] if text in ("\ud800", "\udfff") else ["blank_text"])
    assert report.issues[0].path == path
    assert "encodable as UTF-8" in report.issues[0].message


@pytest.mark.parametrize("task,slot", [("claim_decomposition", ("claim_statement",)),
                                      ("claim_assessment", ("cells", 0, "note")),
                                      ("kill_search_query", ("task", 0, "term"))])
@pytest.mark.parametrize("text", ["\ud800", "\udfff"])
def test_escaped_lone_surrogate_in_json_output_is_rejected_at_its_path(task, slot, text):
    si = fixture(task)
    d = output(si)
    parent = d
    for key in slot[:-1]:
        parent = parent[key]
    parent[slot[-1]] = text
    raw = json.dumps(d, ensure_ascii=True)
    assert text.encode("unicode_escape").decode("ascii") in raw
    assert json.loads(raw) == d
    report = contracts.validate_model_output(si, raw)
    assert not report.ok
    path = "/" + "/".join(map(str, slot))
    assert [(issue.code, issue.path) for issue in report.issues] == [("text_not_encodable", path)]
    assert "encodable as UTF-8" in report.issues[0].message


@pytest.mark.parametrize("task,slot", [("kill_search_query", ("setting", 0, "why")),
                                      ("kill_search_query", ("task", 0, "why")),
                                      ("claim_assessment", ("cells", 0, "evidence", 0, "quote")),
                                      ("claim_assessment", ("whole_claim_evidence", 0, "quote")),
                                      ("claim_assessment", ("cells", 0, "element_ref")),
                                      ("claim_assessment", ("cells", 0, "object_key"))])
@pytest.mark.parametrize("text", ["\ud800", "\udfff"])
@pytest.mark.parametrize("as_json", [False, True], ids=["dict", "escaped-json"])
def test_candidate_generic_utf8_guard_rejects_values_and_keys_at_exact_paths(task, slot, text, as_json):
    si = fixture(task)
    d = output(si)
    if task == "claim_assessment":
        for i in range(len(d["cells"])):
            support(si, d, i)
        d.update(states_whole_claim=True, whole_claim_evidence=[evidence(si)])
    assert verdict(si, d).ok
    parent = d
    for key in slot[:-1]:
        parent = parent[key]
    if slot[-1] == "object_key":
        # The key and its value share a path, which must get only one encoding issue.
        parent[text] = text
        slot = (*slot[:-1], text)
    else:
        parent[slot[-1]] = parent[slot[-1]] + text if slot[-1] == "quote" else text
    raw = json.dumps(d, ensure_ascii=True) if as_json else d
    if as_json:
        assert text.encode("unicode_escape").decode("ascii") in raw
    report = contracts.validate_model_output(si, raw)
    path = "/" + "/".join(map(str, slot))
    path = path.encode("utf-8", "backslashreplace").decode("utf-8")
    assert not report.ok
    assert [(i.code, i.path) for i in report.issues if i.code == "text_not_encodable"] == [
        ("text_not_encodable", path)]
    if slot[-1] == text:
        assert "schema_invalid" in report.codes()


@pytest.mark.parametrize("task", TASKS)
@pytest.mark.parametrize("as_json", [False, True], ids=["dict", "escaped-json"])
def test_candidate_utf8_guard_walks_schema_invalid_shapes_and_escapes_pointer_keys(task, as_json):
    si = fixture(task)
    d = {"unexpected/branch~": ["\ud800", {"nested": "\udfff"}]}
    report = contracts.validate_model_output(si, json.dumps(d) if as_json else d)
    assert not report.ok and "schema_invalid" in report.codes()
    assert [(i.code, i.path) for i in report.issues if i.code == "text_not_encodable"] == [
        ("text_not_encodable", "/unexpected~1branch~0/0"),
        ("text_not_encodable", "/unexpected~1branch~0/1/nested")]


@pytest.mark.parametrize("as_json", [False, True], ids=["dict", "escaped-json"])
def test_generic_utf8_guard_leaves_other_tasks_unchanged(as_json):
    si = copy.deepcopy(STEP_INPUTS["H_search_query"])
    d = output(si)
    d["setting"][0]["why"] = "\ud800"
    assert contracts.validate_model_output(si, json.dumps(d) if as_json else d).ok


@pytest.mark.parametrize("task,slot", [("claim_decomposition", ("claim_statement",)),
                                      ("kill_search_query", ("setting", 0, "why")),
                                      ("claim_assessment", ("cells", 0, "note"))])
@pytest.mark.parametrize("as_json", [False, True], ids=["dict", "json"])
def test_candidate_utf8_guard_accepts_real_non_bmp_characters_and_accents(task, slot, as_json):
    si = fixture(task)
    d = output(si)
    parent = d
    for key in slot[:-1]:
        parent = parent[key]
    parent[slot[-1]] = "SYNTHETIC café naïve ölçüm 😀"
    assert contracts.validate_model_output(si, json.dumps(d) if as_json else d).ok


def test_generic_utf8_guard_repairs_why_once_through_real_model_step(tmp_path):
    attempts = []

    def surrogate_once(shown):
        draft = output(shown)
        attempts.append(shown)
        if len(attempts) == 1:
            draft["setting"][0]["why"] = "\ud800"
        return json.dumps(draft, ensure_ascii=True)

    state = candidate_flow(tmp_path, "kill_search_query", surrogate_once)
    try:
        result = run_candidate(state, "kill_search_query")
        assert len(state[2].calls) == 2 and not result.get("invalid")
        step = state[1].step(state[3]["id"], "synthetic:candidate", "model:kill_search_query")
        assert step["status"] == "succeeded" and step["output"] == result
        validations = [json.loads(row[0]) for row in state[1].conn.execute(
            "SELECT validation_json FROM model_sessions ORDER BY rowid")]
        assert [(i["code"], i["path"]) for i in validations[0]["issues"]] == [
            ("text_not_encodable", "/setting/0/why")]
        assert validations[0]["ok"] is False and validations[1]["ok"] is True
        messages = [row[0] for row in state[1].conn.execute("SELECT user_message FROM step_inputs ORDER BY rowid")]
        assert len(messages) == 2 and "text_not_encodable" in messages[1] and "/setting/0/why" in messages[1]
    finally:
        state[1].conn.close()


@pytest.mark.parametrize("slot", ["object_key", "element_ref"])
@pytest.mark.parametrize("surrogate", ["\ud800", "\udfff"])
def test_surrogate_diagnostics_are_stored_after_one_repair_through_model_step(tmp_path, slot, surrogate):
    text = "SYNTHETIC café 😀" + surrogate
    escaped = "SYNTHETIC café 😀" + (r"\ud800" if surrogate == "\ud800" else r"\udfff")

    def bad(shown):
        draft = output(shown)
        if slot == "object_key":
            draft["cells"][0][text] = text
        else:
            draft["cells"][0]["element_ref"] = text
        return json.dumps(draft, ensure_ascii=True)

    state = candidate_flow(tmp_path, "claim_assessment", bad)
    try:
        result = run_candidate(state, "claim_assessment")
        assert result["invalid"] and len(state[2].calls) == 2
        step = state[1].step(state[3]["id"], "synthetic:candidate", "model:claim_assessment")
        assert step["status"] == "failed" and step["error_code"] == "invalid_model_output"
        validations = [json.loads(row[0]) for row in state[1].conn.execute(
            "SELECT validation_json FROM model_sessions ORDER BY rowid")]
        assert len(validations) == 2 and all(v["ok"] is False for v in validations)
        for validation in validations:
            issues = validation["issues"]
            if slot == "object_key":
                assert any(i["code"] == "text_not_encodable" and i["path"] == "/cells/0/" + escaped for i in issues)
            else:
                assert any(i["code"] == "unknown_element_ref" and i["path"] == "/cells/0/element_ref"
                           and i["message"] == escaped for i in issues)
            json.dumps(validation, ensure_ascii=False).encode("utf-8")
        assert result["issues"] == validations[-1]["issues"]
        messages = [row[0] for row in state[1].conn.execute("SELECT user_message FROM step_inputs ORDER BY rowid")]
        assert len(messages) == 2 and json.dumps(escaped, ensure_ascii=False)[1:-1] in messages[1]
        assert surrogate not in messages[1]
        assert json.loads(result["raw_output"]) == json.loads(bad(state[2].calls[-1]))
    finally:
        state[1].conn.close()


@pytest.mark.parametrize("task", TASKS)
@pytest.mark.parametrize("schema_invalid", [False, True])
def test_candidate_diagnostics_preserve_encodable_text_and_escape_issues_and_warnings(monkeypatch, task, schema_invalid):
    si = fixture(task)
    draft = output(si)
    if schema_invalid:
        draft["extra"] = True
    safe = "SYNTHETIC café naïve ölçüm 😀 /~ \\ud800"
    bad = safe + "\ud800"
    expected = safe + r"\ud800"

    def diagnostics(step_input, output_type, result, report):
        for entries in (report.issues, report.warnings):
            entries.append(contracts.Issue("synthetic_encodable", "/" + safe, safe))
            entries.append(contracts.Issue("synthetic_surrogate", "/" + bad, bad))

    monkeypatch.setattr(contracts, "_semantic_checks", diagnostics)
    report = verdict(si, draft)
    for entries in (report.issues, report.warnings):
        encodable, escaped = [i for i in entries if i.code.startswith("synthetic_")]
        assert encodable.path.encode("utf-8") == ("/" + safe).encode("utf-8")
        assert encodable.message.encode("utf-8") == safe.encode("utf-8")
        assert vars(escaped) == {"code": "synthetic_surrogate", "path": "/" + expected, "message": expected}


def test_blank_text_is_a_repair_issue(tmp_path):
    si = fixture("claim_decomposition")
    d = output(si) | {"claim_statement": "   "}
    assert verdict(si, d).codes() == ["blank_text"]
    assert schema_repairs(si["task_type"]) == 1
    attempts = []

    def blank_once(shown):
        draft = output(shown)
        attempts.append(shown)
        if len(attempts) == 1:
            draft["claim_statement"] = "   "
        return json.dumps(draft)

    state = candidate_flow(tmp_path, "claim_decomposition", blank_once)
    result = run_candidate(state, "claim_decomposition")
    assert len(state[2].calls) == 2 and not result.get("invalid")
    step = state[1].step(state[3]["id"], "synthetic:candidate", "model:claim_decomposition")
    assert step["status"] == "succeeded"


@pytest.mark.parametrize("task,slot", [("claim_decomposition", ("claim_statement",)),
                                      ("claim_decomposition", ("elements", 0, "text")),
                                      ("claim_assessment", ("cells", 0, "note"))])
def test_nul_text_is_rejected_at_its_path_and_repaired_once_through_model_step(tmp_path, task, slot):
    attempts = []

    def nul_once(shown):
        draft = output(shown)
        attempts.append(shown)
        if len(attempts) == 1:
            parent = draft
            for key in slot[:-1]:
                parent = parent[key]
            parent[slot[-1]] = "\x00SYNTHETIC"
        return json.dumps(draft)

    state = candidate_flow(tmp_path, task, nul_once)
    result = run_candidate(state, task)
    assert len(state[2].calls) == 2 and not result.get("invalid")
    step = state[1].step(state[3]["id"], "synthetic:candidate", "model:" + task)
    assert step["status"] == "succeeded"
    validations = [json.loads(row[0]) for row in state[1].conn.execute(
        "SELECT validation_json FROM model_sessions ORDER BY rowid")]
    path = "/" + "/".join(map(str, slot))
    assert [(i["code"], i["path"]) for i in validations[0]["issues"]] == [("blank_text", path)]
    assert validations[0]["ok"] is False and validations[1]["ok"] is True
    payload = state[1].step_input_payload(result["step_input_id"])
    assert verdict(payload, result["result"]).ok


@pytest.mark.parametrize("text", [" SYNTHETIC ", "\u00a0SYNTHETIC\u00a0", "\u2003SYNTHETIC\u2003",
                                 "\tSYNTHETIC\t", "\nSYNTHETIC\n", "SYNTHETIC\ttext", "SYNTHETIC\ntext",
                                 "SYNTHETIC\u00a0text", "SYNTHETIC\u2003text"])
def test_accepted_decomposition_text_can_be_stored_by_k1_add_version(tmp_path, text):
    def awkward(shown):
        draft = output(shown)
        for field in ("claim_statement", "nearest_simple_explanation", "critical_assumption", "validation_plan", "rationale"):
            draft[field] = text
        draft["conditions"] = [text]
        for element in draft["elements"]:
            element["text"] = text
        return json.dumps(draft)

    state = candidate_flow(tmp_path, "claim_decomposition", awkward)
    result = run_candidate(state, "claim_decomposition")
    assert len(state[2].calls) == 1 and not result.get("invalid")
    store = state[1]
    payload = store.step_input_payload(result["step_input_id"])
    draft = result["result"]
    assert verdict(payload, draft).ok
    candidates = CandidateStore(store)
    candidate = candidates.open_from_owner_text(state[3]["research_id"], "SYNTHETIC owner claim")
    version = candidates.add_version(candidate["research_id"], candidate["id"],
        **{field: draft[field] for field in ("claim_statement", "conditions", "elements", "nearest_simple_explanation",
                                            "critical_assumption", "validation_plan")},
        origin="model_decomposition", step_input_id=result["step_input_id"], expected_version=0)
    assert version["claim_statement"] == text
    assert json.loads(version["conditions_json"]) == [text]
    assert version["nearest_simple_explanation"] == version["critical_assumption"] == version["validation_plan"] == text
    assert all(e["text"] == text for e in version["elements"])
    store.conn.close()


def test_support_cell_needs_a_located_quote():
    si = fixture()
    d = support(si, output(si))
    assert verdict(si, d).ok
    d["cells"][0]["evidence"] = []
    assert "support_without_evidence" in verdict(si, d).codes()
    d["cells"][0]["evidence"] = [evidence(si) | {"quote": "SYNTHETIC absent invention"}]
    assert "anchor_not_in_passage" in verdict(si, d).codes()


@pytest.mark.parametrize("where", ["cell", "whole"])
def test_quote_must_come_from_the_assessed_work(where):
    si = fixture()
    d = support(si, output(si))
    if where == "whole":
        d.update(states_whole_claim=True, whole_claim_evidence=[evidence(si)])
        d["cells"][0]["evidence"] = [evidence(si, 1)]
    si["passages"][0]["source_id"] = "srv_SYNTHOTHER01"
    assert "unknown_passage_id" in verdict(si, d).codes()
    si = fixture()
    si["allowlist"]["passage_ids"] = []
    assert "unknown_passage_id" in verdict(si, d).codes()


def test_same_quote_may_support_two_cells():
    si = fixture()
    d = support(si, output(si))
    support(si, d, 1)
    d.update(states_whole_claim=True, whole_claim_evidence=[evidence(si)])
    assert verdict(si, d).ok


@pytest.mark.parametrize("task", TASKS)
@pytest.mark.parametrize("field,value", [("step_input_id", "sti_SYNTHOTHER01"), ("scope_revision", 2),
                                        ("skill_package_hash", "sha256:" + "f" * 64)])
def test_envelope_mismatch_is_reported(task, field, value):
    si = fixture(task)
    d = output(si) | {field: value}
    assert "envelope_mismatch" in verdict(si, d).codes()


def test_evidence_helper_stores_the_located_words_and_maps_the_kind():
    si = fixture()
    for n, kind in ((0, "abstract"), (1, "passage")):
        p = si["passages"][n]
        located = contracts.locate_anchor(p["text"], p["text"])
        assert contracts.claim_assessment_evidence(si, evidence(si, n)) == {
            "evidence_kind": kind, "passage_id": None if kind == "abstract" else p["passage_id"], "quote": located.text}
    assert contracts.claim_assessment_evidence(si, {"passage_id": "psg_SYNTHUNKNOWN01", "quote": "SYNTHETIC"}) is None
    assert contracts.claim_assessment_evidence(si, evidence(si) | {"quote": "SYNTHETIC nonexistent absent invented words"}) is None
    p = si["passages"][0]
    p["text"] = "SYNTHETIC: the buffering method decreases the mean queue delay under bounded arrival conditions"
    raw = p["text"].replace("decreases", "increases")
    anchor = contracts.locate_anchor(raw, p["text"])
    assert anchor is not None and anchor.kind == "fuzzy"
    d = support(si, output(si))
    d["cells"][0]["evidence"][0]["quote"] = raw
    assert verdict(si, d).ok
    stored = contracts.claim_assessment_evidence(si, {"passage_id": p["passage_id"], "quote": raw})
    assert stored["quote"] == anchor.text == p["text"]
    assert "decreases" in stored["quote"] and "increases" not in stored["quote"]
    d["cells"][0]["evidence"].append(evidence(si))
    assert "duplicate_evidence_quote" in verdict(si, d).codes()


def test_a_located_but_irrelevant_quote_still_validates():
    si = fixture()
    d = support(si, output(si))
    d["cells"][0]["evidence"] = [evidence(si, 1)]
    # Structural only: the green wall quote does not support a queue mechanism. No semantic verification exists.
    assert verdict(si, d).ok


def test_candidate_handles_are_numbered_per_step_and_recomputed_from_the_stored_input():
    si = fixture()
    handles = contracts.citation_handles(si)
    assert handles == contracts.candidate_citation_handles(si)
    assert [handles[p["passage_id"]] for p in si["passages"]] == ["psg_P0000001", "psg_P0000002"]
    assert handles[si["sources"][0]["source_id"]] == "srv_S0000001"
    elements = si["candidate_target"]["version"]["elements"]
    assert [handles[e["element_id"]] for e in elements] == [f"ele_E{n:07d}" for n in range(1, 4)]
    assert contracts.citation_handles(json.loads(json.dumps(si))) == handles
    si["passages"].reverse()
    elements.reverse()
    si["allowlist"]["element_ids"].reverse()
    fresh = contracts.citation_handles(si)
    assert fresh[si["passages"][0]["passage_id"]] == "psg_P0000001"
    assert fresh[elements[0]["element_id"]] == "ele_E0000001"
    si["allowlist"]["passage_ids"].append("psg_SYNTHEXTRA01")
    si["allowlist"]["source_ids"].append("srv_SYNTHEXTRA01")
    si["allowlist"]["element_ids"].append("ele_SYNTHEXTRA01")
    si["candidate_target"]["basis"] = [{"kind": "passage", "text": "SYNTHETIC", "passage_id": "psg_SYNTHEXTRA02"}]
    si["candidate_target"]["assessed_source_id"] = "srv_SYNTHEXTRA02"
    fresh = contracts.citation_handles(si)
    assert fresh["psg_SYNTHEXTRA01"] == "psg_P0000003"
    assert fresh["psg_SYNTHEXTRA02"] == "psg_P0000004"
    assert fresh["srv_SYNTHEXTRA01"] == "srv_S0000002"
    assert fresh["srv_SYNTHEXTRA02"] == "srv_S0000003"
    assert fresh["ele_SYNTHEXTRA01"] == "ele_E0000004"
    si["passages"].append(copy.deepcopy(si["passages"][0]))
    assert contracts.citation_handles(si) == fresh  # First occurrence wins.


@pytest.mark.parametrize("task", TASKS)
def test_with_citation_handles_converts_only_declared_slots(task):
    si = fixture(task)
    handles = contracts.citation_handles(si)
    marker = next(iter(handles), "srv_SYNTHCAND01")
    si["question"]["text"] = marker
    target = si["candidate_target"]
    target["origin_text"] = marker
    if target["version"]:
        target["version"]["claim_statement"] = marker
        target["version"]["conditions"] = [marker]
        target["version"]["elements"][0]["text"] = marker
    for basis in target["basis"]:
        basis["text"] = marker
    before = copy.deepcopy(si)
    expected = copy.deepcopy(si)
    for owner, key, _, _ in contracts._report_id_fields(expected, contracts.CANDIDATE_INPUT_ID_FIELDS):
        if isinstance(owner[key], str):
            owner[key] = handles.get(owner[key], owner[key])
    shown = contracts.with_citation_handles(si)
    assert shown == expected and si == before
    assert shown["candidate_target"]["candidate_id"] == target["candidate_id"]
    assert shown["candidate_target"]["origin_text"] == marker
    for field in contracts.ENVELOPE_FIELDS:
        assert shown[field] == si[field]
    assert None not in handles
    if task == "claim_decomposition":
        assert shown["candidate_target"]["basis"][0]["passage_id"] == "psg_P0000001"
        assert shown["candidate_target"]["basis"][1]["passage_id"] is None


def test_output_resolution_maps_element_ref_and_passage_ids():
    si = fixture()
    shown = contracts.with_citation_handles(si)
    d = support(shown, output(shown))
    d.update(states_whole_claim=True, whole_claim_evidence=[evidence(shown)])
    d["cells"][0]["note"] = "ele_E0000001 psg_P0000001"
    d["cells"][0]["evidence"][0]["quote"] = shown["passages"][0]["text"]
    resolved = contracts.resolve_citation_handles(si, json.dumps(d))
    assert resolved["cells"][0]["element_ref"] == si["candidate_target"]["version"]["elements"][0]["element_id"]
    assert resolved["cells"][0]["evidence"][0]["passage_id"] == si["passages"][0]["passage_id"]
    assert resolved["whole_claim_evidence"][0]["passage_id"] == si["passages"][0]["passage_id"]
    assert resolved["cells"][0]["note"] == d["cells"][0]["note"]
    assert resolved["cells"][0]["evidence"][0]["quote"] == d["cells"][0]["evidence"][0]["quote"]
    assert verdict(si, resolved).ok
    si = fixture("claim_decomposition")
    d = output(contracts.with_citation_handles(si))
    resolved = contracts.resolve_citation_handles(si, json.dumps(d))
    assert resolved["source_ids"] == si["allowlist"]["source_ids"]
    assert resolved["passage_ids"] == si["allowlist"]["passage_ids"]
    assert [e["element_ref"] for e in resolved["elements"]] == ["e1", "e2", "e3"]
    assert verdict(si, resolved).ok
    pid = si["passages"][0]["passage_id"]
    assert contracts.issues_with_handles(si, [{"message": pid}]) == [{"message": "psg_P0000001"}]
    si = fixture("kill_search_query")
    d = output(si)
    d["task"][0]["term"] = "psg_P0000001"
    assert contracts.resolve_citation_handles(si, json.dumps(d)) == d


def test_leading_zero_handles_resolve():
    si = fixture()
    shown = contracts.with_citation_handles(si)
    d = support(shown, output(shown))
    d["cells"][0]["element_ref"] = "ele_E00000001"
    d["cells"][1]["element_ref"] = "ele_E2"
    d["cells"][0]["evidence"][0]["passage_id"] = "psg_P00000001"
    resolved = contracts.resolve_citation_handles(si, json.dumps(d))
    assert verdict(si, resolved).ok
    si = fixture("claim_decomposition")
    d = output(contracts.with_citation_handles(si))
    d["source_ids"] = ["srv_S00000001"]
    d["passage_ids"] = ["psg_P1"]
    assert verdict(si, contracts.resolve_citation_handles(si, json.dumps(d))).ok


@pytest.mark.parametrize("field,bad,code", [("element_ref", "ele_SYNTHUNKNOWN01", "unknown_element_ref"),
                                         ("passage_id", "psg_SYNTHUNKNOWN01", "unknown_passage_id")])
def test_an_unshown_real_id_is_rejected_not_resolved(field, bad, code):
    si = fixture()
    d = support(si, output(si))
    owner = d["cells"][0] if field == "element_ref" else d["cells"][0]["evidence"][0]
    owner[field] = bad
    assert contracts.resolve_citation_handles(si, json.dumps(d)) == d
    assert code in verdict(si, d).codes()


def candidate_flow(tmp_path, task, responder=valid_response, owner=False):
    """Temporary DB, no service or candidate store; target and source evidence are hand-built."""
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC background question", "attached", "quick", [], "fake", "research-model", "en")
    si = fixture("claim_decomposition_owner_text" if owner else task)
    target = si["candidate_target"]
    sids = [store.create_upload_source(s["title"]) for s in si["sources"]]
    remap = {s["source_id"]: sid for s, sid in zip(si["sources"], sids)}
    rows, pids = [], []
    with transaction(conn):
        for p in si["passages"]:
            loc = p["locator"]
            pid = store._insert_passage(remap[p["source_id"]], None, loc["kind"], loc["physical_page"],
                                        loc["printed_label"], p["abstract_origin"], None, None, p["text"])
            rows.append(store.passage(pid))
            pids.append(pid)
    passage_map = {p["passage_id"]: pid for p, pid in zip(si["passages"], pids)}
    for item in target["basis"]:
        if item["passage_id"] is not None:
            item["passage_id"] = passage_map[item["passage_id"]]
    if target["assessed_source_id"] is not None:
        target["assessed_source_id"] = remap[target["assessed_source_id"]]
    adapter = FakeAdapter(responder=responder)
    flow = ResearchFlow(FlowDeps(Settings(data_dir=tmp_path / "data", port=8871), store,
                                {"fake": adapter}, skill.load_skill_package(), None))
    # Generic answer run is only a storage harness: K2 adds no candidate dispatch or stage mapping.
    run = store.create_run(rid, "answer", {"max_model_calls": 4, "max_provider_requests": 0}, None)
    store.update_run(run["id"], status="running")
    scope = store.scope(rid)
    scope.update(literature_model="unused-literature-model", literature_connection="unused", reasoning_effort="high")
    return flow, store, adapter, store.run(run["id"]), scope, sids, rows, target


def run_candidate(state, task):
    flow, store, adapter, run, scope, sids, passages, target = state
    return asyncio.run(flow._model_step(run, scope, "synthetic:candidate", task, source_ids=sids,
                                       passage_rows=passages, candidate_target=target))


def assert_fake_step(tmp_path, task):
    state = candidate_flow(tmp_path, task)
    flow, store, adapter, run, scope, sids, passages, target = state
    result = run_candidate(state, task)
    step = store.step(run["id"], "synthetic:candidate", "model:" + task)
    assert step["status"] == "succeeded" and step["output"] == result
    payload = store.step_input_payload(result["step_input_id"])
    assert payload["candidate_target"] == target
    assert payload["skill_files"] == ["SKILL.md", "references/candidate-check.md"]
    assert payload["output_schema_versions"] == ["deixis." + task + ".v1"]
    assert payload["skill_package_hash"] == flow.deps.package.package_hash == skill.package_hash()
    assert payload["allowlist"]["candidate_ids"] == []
    assert payload["allowlist"]["source_ids"] == sids
    assert payload["allowlist"]["passage_ids"] == [p["id"] for p in passages]
    message = store.conn.execute("SELECT user_message FROM step_inputs WHERE id = ?", (result["step_input_id"],)).fetchone()[0]
    shown = parse_step_input(message)
    assert shown == adapter.calls[0] == contracts.with_citation_handles(payload)
    raw = json.loads(store.model_session(result["step_input_id"])["raw_output"])
    assert result["result"] == contracts.resolve_citation_handles(payload, json.dumps(raw))
    assert len(adapter.calls) == 1
    for real, handle in contracts.citation_handles(payload).items():
        assert real not in message and handle in message
    if task == "claim_decomposition":
        assert raw["source_ids"] == ["srv_S0000001"] and raw["passage_ids"] == ["psg_P0000001"]
        assert result["result"]["source_ids"] == sids
        assert result["result"]["passage_ids"] == [passages[0]["id"]]
        assert raw["elements"][0]["element_ref"] == "e1"
    elif task == "claim_assessment":
        assert raw["cells"][0]["element_ref"] == "ele_E0000001"
        assert result["result"]["cells"][0]["element_ref"] == target["version"]["elements"][0]["element_id"]
        assert payload["allowlist"]["element_ids"] == [e["element_id"] for e in target["version"]["elements"]]
    else:
        assert payload["sources"] == payload["passages"] == []
        assert contracts.citation_handles(payload)[target["version"]["elements"][0]["element_id"]] == "ele_E0000001"
    assert adapter.sent == [(task, "research-model", "high")]
    assert task not in payload["capabilities"]["supported_tasks"]
    for table in ("research_candidates", "candidate_versions", "claim_matrix_cells", "claim_matrix_evidence"):
        assert store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_fake_adapter_answers_claim_decomposition_through_model_step(tmp_path):
    assert_fake_step(tmp_path, "claim_decomposition")


def test_fake_adapter_answers_kill_search_query_through_model_step(tmp_path):
    assert_fake_step(tmp_path, "kill_search_query")


def test_fake_adapter_answers_claim_assessment_through_model_step(tmp_path):
    assert_fake_step(tmp_path, "claim_assessment")


def forbidden_salvage(*args, **kwargs):
    pytest.fail("Candidate tasks must never use D56 answer salvage")


def test_candidate_step_repairs_once_then_stops_without_salvage(tmp_path, monkeypatch):
    monkeypatch.setattr(contracts, "salvage_answer_draft", forbidden_salvage)

    def bad(si):
        d = support(si, output(si))
        d["cells"][0]["evidence"][0]["quote"] = "SYNTHETIC absent nonexistent invention on both attempts."
        return json.dumps(d)

    state = candidate_flow(tmp_path, "claim_assessment", bad)
    result = run_candidate(state, "claim_assessment")
    assert result["invalid"] and "anchor_not_in_passage" in {i["code"] for i in result["issues"]}
    assert len(state[2].calls) == 2
    step = state[1].step(state[3]["id"], "synthetic:candidate", "model:claim_assessment")
    assert step["status"] == "failed" and step["error_code"] == "invalid_model_output"
    messages = list(state[1].conn.execute("SELECT user_message FROM step_inputs ORDER BY rowid"))
    assert len(messages) == 2 and "anchor_not_in_passage" in messages[1][0] and "psg_P0000001" in messages[1][0]
    assert state[1].conn.execute("SELECT COUNT(*) FROM model_sessions").fetchone()[0] == 2


@pytest.mark.parametrize("field,bad,code", [("passage_id", "srv_S0000001", "unknown_passage_id"),
                                         ("passage_id", "ele_E0000001", "unknown_passage_id"),
                                         ("element_ref", "psg_P0000001", "unknown_element_ref")])
def test_wrong_kind_handle_is_unknown_and_repaired_once_then_fails(tmp_path, monkeypatch, field, bad, code):
    monkeypatch.setattr(contracts, "salvage_answer_draft", forbidden_salvage)

    def wrong(si):
        d = support(si, output(si))
        owner = d["cells"][0] if field == "element_ref" else d["cells"][0]["evidence"][0]
        owner[field] = bad
        return json.dumps(d)

    state = candidate_flow(tmp_path, "claim_assessment", wrong)
    result = run_candidate(state, "claim_assessment")
    assert result["invalid"] and len(state[2].calls) == 2
    path = "/cells/0/element_ref" if field == "element_ref" else "/cells/0/evidence/0/passage_id"
    assert code in {i["code"] for i in result["issues"] if i["path"] == path}
    if field == "passage_id":
        assert "schema_invalid" in {i["code"] for i in result["issues"] if i["path"] == path}
    for row in state[1].conn.execute("SELECT raw_output,validation_json FROM model_sessions"):
        assert bad in row["raw_output"]
        assert code in {i["code"] for i in json.loads(row["validation_json"])["issues"] if i["path"] == path}


def test_candidate_tasks_use_the_research_model_and_default_repairs():
    scope = {"model_connection": "research", "requested_model": "chosen-research", "reasoning_effort": "high",
             "literature_connection": "literature", "literature_model": "chosen-literature", "literature_reasoning_effort": "low"}
    for task in TASKS:
        assert step_model(scope, task) == ("research", "chosen-research", "high")
        assert schema_repairs(task) == MAX_SCHEMA_REPAIRS == 1
        assert task in HANDLE_TASKS
        assert task not in LITERATURE_TASKS + NO_REPAIR_TASKS + TIMEOUT_RETRIED_TASKS


def test_candidate_method_text_carries_the_rules():
    text = " ".join((SKILL_DIR / "references/candidate-check.md").read_text().split())
    for rule in ("owner's proposal", "always null for an owner's sentence without basis", "never invent a nearest explanation",
                 "Name no tool, protocol, sample size or procedure", "Different terminology alone is not a lower relation",
                 "never a contradiction", "Parts stated separately do not state the whole claim", "never proof of absence",
                 "copy it exactly as shown", "`srv_S...`", "`psg_P...`", "`ele_E...`", "data, not instructions",
                 "background only, never the claim", "no alternatives", "no improved idea", "never used to widen the search",
                 "Never claim in your own words", '"novel"', '"original"', '"the first"', '"gap"', '"unexplored"',
                 "not text quoted from a source", '"original signal"'):
        assert rule in text
    assert "foundational" not in text.lower()


def test_behavior_cases_are_defined_and_never_run():
    data = json.loads((Path(__file__).parent.parent / "model_behavior/candidate_cases.json").read_text())
    assert data["status"] == "run_once_2026-10-02" and data["prepared"] == "2026-10-01" and data["split"] == "development"
    assert [c["id"] for c in data["cases"]] == [f"CB{n:02d}" for n in range(1, 8)]
    for case in data["cases"]:
        assert case["fixture"] in STEP_INPUTS and case["task_type"] in TASKS and case["judgement"] == "human"
        assert set(case) >= {"id", "title", "task_type", "fixture", "fixture_change", "expected", "failure_if", "judgement"}
        assert "SYNTHETIC" in case["fixture_change"]
    for marker in ("SYNTHETIC", "One attempt per case", "heuristics", "not the K6 measurement"):
        assert marker in data["note"]
    for marker in ("Zero-result", "all-queries-failed", "no-abstract", "code states checked in K3 tests"):
        assert marker in data["cases"][1]["expected"]
