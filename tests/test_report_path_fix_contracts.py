"""D198 new-contract guards paired with workflow E1/A1; all records are synthetic."""

import copy
import json
import random

import pytest

from deixis.domain import contracts
from deixis.models import prompt
from fakes import valid_response
from test_contracts import STEP_INPUTS
from test_report_anchor_repair import two_cells, issues, BAD_QUOTE
from test_report_path_fix import REPLAY, patch, run_step


def template(task):
    for si in STEP_INPUTS.values():
        if isinstance(si, dict) and si.get("task_type") == task:
            return copy.deepcopy(si)
    si = copy.deepcopy(STEP_INPUTS["A_answer"])
    si["task_type"] = task
    if task == "answer_review":
        si["claims_under_review"] = []
    if task in contracts.EXTRACTION_TASKS:
        if task == "cell_extraction":
            si["sources"] = si["sources"][:1]
            sid = si["sources"][0]["source_id"]
            si["passages"] = [p for p in si["passages"] if p["source_id"] == sid]
            si["allowlist"]["source_ids"] = [sid]
            si["allowlist"]["passage_ids"] = [p["passage_id"] for p in si["passages"]]
        si["extraction_target"] = {"table_id": "tbl_SYNTHETIC01", "source_id": si["sources"][0]["source_id"],
            "passage_scope": {"given": len(si["passages"]), "available": len(si["passages"]), "all_pages_given": False},
            "columns": [{"column_id": "col_SYNTHETIC01", "revision": 1, "name": "SYNTHETIC existing column",
                         "instruction": "Record the stated method.", "answer_format": "text", "options": None,
                         "allow_multiple": False, "unit_hint": None}]}
    return si


@pytest.mark.parametrize("task", sorted(contracts.TASK_OUTPUTS))
def test_e2_sent_and_stored_schema_omit_hash_but_canonical_validation_requires_it(tmp_path, task):
    """New contract E2 paired with E1: every task sends/stores transport schema while canonical contracts stay strict."""
    canonical = contracts.step_output_schema(task)
    wire = contracts.model_output_schema(task)
    assert "skill_package_hash" not in wire["properties"]
    assert "skill_package_hash" not in wire["required"]
    assert canonical["properties"].get("skill_package_hash") and "skill_package_hash" in canonical["required"]
    assert contracts.strict_compatibility_issues(wire) == []
    output, store, adapter, _, _ = run_step(tmp_path, task, template(task),
        lambda si, schema, message: {k: v for k, v in json.loads(valid_response(si)).items() if k != "skill_package_hash"})
    assert not output.get("invalid")
    assert adapter.requests[0]["schema"] == wire
    row = store.conn.execute("SELECT payload_json, output_schema_json FROM step_inputs ORDER BY rowid").fetchone()
    assert json.loads(row["output_schema_json"]) == wire
    si = json.loads(row["payload_json"])
    unstamped = copy.deepcopy(output["result"])
    del unstamped["skill_package_hash"]
    assert "schema_invalid" in contracts.validate_model_output(si, unstamped).codes()
    assert contracts.step_output_schema(task) == canonical
    assert "skill_package_hash" in contracts.load_schema(contracts.TASK_OUTPUTS[task][0])["required"]


@pytest.mark.parametrize("value", [None, [], 4, "not JSON", '["not an object"]'])
def test_e2_stamping_leaves_non_objects_unchanged(value):
    """New contract E2 paired with E1: stamping cannot manufacture an output from an invalid shape."""
    assert contracts.stamp_package_hash("report_section", STEP_INPUTS["C_report_section_IV"], value) == (value, [])


def test_e2_wrapper_stamping_and_schema_preserve_all_non_null_alternatives(monkeypatch):
    """New contract E2 paired with E1: wrapper alternatives retain their short binding fields and stamp individually."""
    monkeypatch.setitem(contracts.TASK_OUTPUTS, "synthetic_wrapper", ("ReportSectionDraft", "ReportReview"))
    monkeypatch.setitem(contracts.WRAPPER_KEYS, "ReportSectionDraft", "section")
    monkeypatch.setitem(contracts.WRAPPER_KEYS, "ReportReview", "review")
    wire = contracts.model_output_schema("synthetic_wrapper")
    assert contracts.strict_compatibility_issues(wire) == []
    for field in wire["properties"].values():
        obj = field["anyOf"][0]
        assert "skill_package_hash" not in obj["properties"]
        assert {"step_input_id", "scope_revision"} <= set(obj["required"])
    si = STEP_INPUTS["C_report_section_IV"]
    value = {"section": {"skill_package_hash": "wrong"}, "review": None}
    draft, changes = contracts.stamp_package_hash("synthetic_wrapper", si, value)
    assert draft["section"]["skill_package_hash"] == si["skill_package_hash"] and draft["review"] is None
    assert changes == [{"path": "/section/skill_package_hash", "stamped": "skill_package_hash", "model_value": "wrong"}]


def test_a3_full_repair_checks_exact_markers_and_preserved_evidence_independently():
    """New contract A3 paired with red A3: key markers are exact and old insufficiency entries cannot disappear."""
    check = contracts.report_section_repair_issues
    original = {"claims": [{"claim_key": "V.1"}, {"claim_key": "V.1"}, 4, {}, {"claim_key": None}]}
    for context in ["V.10: explanation", "V.1: ", "V.1: \t"]:
        assert [i.message for i in check(original, {"insufficient_evidence": [{"context": context}]})] == ["V.1"]
    assert check(original, {"insufficient_evidence": [{"context": "V.1: explanation"}]}) == []
    assert check(original, {"claims": [{"claim_key": "V.1"}]}) == []
    iv = REPLAY["sections"]["IV"]
    dropped = check(iv["first_output"], iv["repair_output"])
    assert [i.code for i in dropped] == ["repair_dropped_insufficient_evidence"] * 2
    for malformed in [None, [], "not JSON", {"claims": None}, {"claims": [4, {}, {"claim_key": None}]}]:
        assert check(malformed, {}) == []
    old = {"claims": None, "insufficient_evidence": [{"context": "x", "reason": "y"}, 4, {}]}
    assert [i.code for i in check(old, {})] == ["repair_dropped_insufficient_evidence"]
    assert check(old, {"insufficient_evidence": [{"context": "x", "reason": "y"}]}) == []
    assert [i.code for i in check(old, {"insufficient_evidence": [{"context": "x", "reason": "changed"}]})] == ["repair_dropped_insufficient_evidence"]
    assert [i.code for i in check({"claims": [{"claim_key": "V.1"}], "insufficient_evidence": None}, {})] == ["repair_dropped_claim"]


def test_a6b_pair_context_distinguishes_remaining_support():
    """New contract A6b paired with A1: the model sees all current claim anchors; dropping the last needs removal."""
    si, draft = two_cells()
    # One failing cell anchor and one passing anchor on a different cell.
    pairs = contracts.report_section_anchor_repair_context(si, draft, issues(si, draft))
    assert pairs[0]["claims"][0]["anchors"] == [
        {"anchor_index": 0, "target": "cell", "failing": True},
        {"anchor_index": 1, "target": "cell", "failing": False}]
    choice = patch(si, [{"anchor_index": 0, "quote_number": None}])
    assert contracts.validate_report_section_anchor_patch(si, draft, pairs, choice).ok
    single = copy.deepcopy(draft)
    single["citation_anchors"] = single["citation_anchors"][:1]
    fewer = contracts.report_section_anchor_repair_context(si, single, issues(si, single))
    assert len(fewer[0]["claims"][0]["anchors"]) == 1
    assert "anchor_patch_claim_unsupported" in contracts.validate_report_section_anchor_patch(si, single, fewer, choice).codes()
    draft["citation_anchors"][1]["cell_id"] = None
    draft["citation_anchors"][1]["passage_id"] = si["passages"][0]["passage_id"]
    assert contracts.report_section_anchor_repair_context(si, draft, issues(si, draft))[0]["claims"][0]["anchors"][1]["target"] == "passage"


@pytest.mark.parametrize("drop", [0, 2])
def test_a7_dropped_anchor_prunes_cell_id_only_without_remaining_same_cell_support(drop):
    """New contract A7 paired with A1: dropping one of two anchors keeps its cell; dropping a sole anchor removes it."""
    si, draft = two_cells()
    draft["citation_anchors"].insert(1, copy.deepcopy(draft["citation_anchors"][0]))
    draft["citation_anchors"][1]["quote"] = si["report_target"]["cells"][0]["evidence"][0]["quote"]
    draft["citation_anchors"][drop]["quote"] = BAD_QUOTE
    pairs = contracts.report_section_anchor_repair_context(si, draft, issues(si, draft))
    # Make any other initially failing anchor valid so the patch covers exactly the selected failure.
    for i, anchor in enumerate(draft["citation_anchors"]):
        if i != drop:
            cell = next(c for c in si["report_target"]["cells"] if c["cell_id"] == anchor["cell_id"])
            anchor["quote"] = cell["evidence"][0]["quote"]
    pairs = contracts.report_section_anchor_repair_context(si, draft, issues(si, draft))
    choice = patch(si, [{"anchor_index": drop, "quote_number": None}])
    assert contracts.validate_report_section_anchor_patch(si, draft, pairs, choice).ok
    merged, changes = contracts.apply_report_section_anchor_patch(si, draft, pairs, choice)
    first, second = [c["cell_id"] for c in si["report_target"]["cells"]]
    assert merged["claims"][0]["cell_ids"] == ([first, second] if drop == 0 else [first])
    assert len(merged["citation_anchors"]) == 2 and changes[0]["removed"]
    assert contracts.validate_model_output(si, merged).ok


def test_a8_randomized_patches_never_invent_evidence_or_unnamed_text():
    """New contract property guard A8 paired with A1/A4/A7: random model choices bound every merged edit."""
    rng = random.Random(198)
    for _ in range(80):
        si, draft = two_cells()
        # Give each cell two distinct stored quote choices; only anchor 0 fails.
        for cell in si["report_target"]["cells"]:
            cell["evidence"].append(cell["evidence"][0] | {"quote": "SYNTHETIC second stored choice for " + cell["cell_id"]})
        before = copy.deepcopy(draft)
        pairs = contracts.report_section_anchor_repair_context(si, draft, issues(si, draft))
        number = rng.choice([None, 1, 2])
        text = rng.choice([None, "SYNTHETIC model rewrite within chosen support."])
        remove = rng.choice([False, True])
        choice = patch(si, [{"anchor_index": 0, "quote_number": number}], [{
            "claim_key": "IV.1", "text": None if remove else text, "removed": remove,
            "context": "SYNTHETIC no support" if remove else None,
            "reason": "SYNTHETIC reason" if remove else None}])
        validation = contracts.validate_report_section_anchor_patch(si, draft, pairs, choice)
        assert validation.ok
        merged, _ = contracts.apply_report_section_anchor_patch(si, draft, pairs, choice)
        assert len(merged["citation_anchors"]) <= len(draft["citation_anchors"])
        for anchor in merged["citation_anchors"]:
            old = next(a for a in before["citation_anchors"] if a["cell_id"] == anchor["cell_id"])
            assert {k: v for k, v in anchor.items() if k != "quote"} == {k: v for k, v in old.items() if k != "quote"}
            if anchor != old:
                assert anchor["cell_id"] == pairs[0]["cell_id"] and number is not None
                assert anchor["quote"] == pairs[0]["allowed_quotes"][number - 1]["quote"]
        if not remove:
            assert merged["claims"][0]["text"] == (text or before["claims"][0]["text"])
        assert draft == before


@pytest.mark.parametrize("field", ["context", "reason", "text"])
def test_s1_patch_schemas_resolve_refs_and_reject_whitespace(field):
    """New contract S1 paired with A1: canonical and adapter schemas enforce non-whitespace prose."""
    si = REPLAY["sections"]["IV"]["step_input"]
    draft = patch(si, claims=[{"claim_key": "IV.9", "text": None, "removed": True,
                              "context": "SYNTHETIC context", "reason": "SYNTHETIC reason"}])
    canonical = contracts.canonical_validator("ReportSectionAnchorRepair")
    assert canonical.is_valid(draft)
    wire = contracts.report_section_anchor_patch_schema()
    assert "common.schema.json" not in json.dumps(wire)
    assert contracts.strict_compatibility_issues(wire) == []
    from jsonschema import Draft202012Validator
    validator = Draft202012Validator(wire)
    assert validator.is_valid(draft)
    draft["claims"][0][field] = " \t\n"
    assert not canonical.is_valid(draft) and not validator.is_valid(draft)


@pytest.mark.parametrize("field,size", [("anchors", 301), ("claims", 41)])
def test_s1_patch_schema_rejects_overlong_arrays(field, size):
    """New contract S1 paired with A1: deterministic array bounds apply before merging."""
    si = REPLAY["sections"]["IV"]["step_input"]
    draft = patch(si, claims=[{"claim_key": "IV.9", "text": None, "removed": False, "context": None, "reason": None}])
    draft[field] *= size
    assert not contracts.canonical_validator("ReportSectionAnchorRepair").is_valid(draft)


def test_a6_prefixed_context_bound_and_empty_patch_fail_closed():
    """New contract A6 paired with A1: even schema-valid contexts cannot exceed the stored prefix bound."""
    si, draft = two_cells()
    key = "X" * 30 + ".1"
    draft["claims"][0]["claim_key"] = key
    for anchor in draft["citation_anchors"]: anchor["claim_key"] = key
    pairs = contracts.report_section_anchor_repair_context(si, draft, issues(si, draft))
    choice = patch(si, [{"anchor_index": 0, "quote_number": 1}], [{"claim_key": key, "text": None,
                    "removed": True, "context": "x" * 180, "reason": "SYNTHETIC reason"}])
    assert contracts.canonical_validator("ReportSectionAnchorRepair").is_valid(choice)
    assert "anchor_patch_removal" in contracts.validate_report_section_anchor_patch(si, draft, pairs, choice).codes()
    choice["anchors"] = []
    assert "schema_invalid" in contracts.validate_report_section_anchor_patch(si, draft, pairs, choice).codes()


def test_patch_eligibility_requires_distinct_exact_issue_indices_and_all_pairs():
    """New contract guard paired with A1: mixed, duplicate, malformed or unpaired issues select full repair."""
    problem = [{"code": "anchor_not_in_cell_evidence", "path": "/citation_anchors/8/quote"}]
    pairs = [{"anchor_index": 8}]
    assert contracts.report_section_anchor_patch_eligible(problem, pairs)
    for issues_, pairs_ in [(problem * 2, pairs * 2), (problem, []), (problem, [{"anchor_index": 9}]),
                            (problem + [{"code": "schema_invalid", "path": "/"}], pairs),
                            ([{"code": problem[0]["code"], "path": None}], pairs)]:
        assert not contracts.report_section_anchor_patch_eligible(issues_, pairs_)


def test_schema_integer_choices_with_decimal_json_spelling_apply_without_changing_selection():
    """New contract paired with A1: JSON Schema integer values such as 0.0 still index the selected quote safely."""
    si, draft = two_cells()
    pairs = contracts.report_section_anchor_repair_context(si, draft, issues(si, draft))
    choice = patch(si, [{"anchor_index": 0.0, "quote_number": 1.0}])
    assert contracts.validate_report_section_anchor_patch(si, draft, pairs, choice).ok
    merged, _ = contracts.apply_report_section_anchor_patch(si, draft, pairs, choice)
    assert merged["citation_anchors"][0]["quote"] == pairs[0]["allowed_quotes"][0]["quote"]


def test_a10_direct_full_repair_form_preserves_old_form_without_failed_output():
    """New contract A10 paired with full-message A5: opt-in raw output changes report-section messages only."""
    from test_report_anchor_repair import old_repair_message
    si = STEP_INPUTS["C_report_section_IV"]
    problem = [{"code": "schema_invalid", "path": "/", "message": "SYNTHETIC failure"}]
    assert prompt.repair_message(si, problem) == old_repair_message(si, problem)
    text = '{"SYNTHETIC": "raw handle form cel_L0000001"}'
    message = prompt.repair_message(si, problem, failed_output=text)
    assert text in message and prompt.REPORT_SECTION_FULL_REPAIR_GUIDANCE in message
    for task in ["grounded_answer", "cell_extraction"]:
        other = si | {"task_type": task}
        assert prompt.repair_message(other, problem, failed_output=text) == old_repair_message(other, problem)
