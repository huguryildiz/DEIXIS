"""RF4 synthetic section rules and modification checks; no real-model calls.

Tests prefixed preservation keep assembly assertions. Other negative regressions
are checked against the old runtime in a separate scratch tree, without stash.
"""

import asyncio
import copy
import json
from pathlib import Path

import pytest

from deixis.domain import contracts
from deixis.workflow.flow import RunStopped
from deixis.workflow.report import assembly, sections
from deixis.workflow.report.sections import run_report
from fakes import envelope
from test_contracts import STEP_INPUTS
from test_report_flow import _claim, report_flow
from test_report_path_fix import run_step, rebind, first_issues, sessions


REPLAY = json.loads((Path(__file__).parent / "fixtures/research/report-rf4-replay.json").read_text())
PID, SID, CID, COL = "psg_SYNTHRF4001", "srv_SYNTHRF4001", "cel_SYNTHRF4001", "col_SYNTHR0001"


def packet(section="IV"):
    si = copy.deepcopy(STEP_INPUTS["C_report_section_IV"])
    for field in ("question", "sources", "passages"):
        si[field] = copy.deepcopy(REPLAY[field])
    target = si["report_target"]
    target["section_id"] = section
    target["cells"] = copy.deepcopy(REPLAY["cells"])
    target["plan"]["section_budgets"] = {section: {"min_words": 0, "max_words": 1000, "max_claims": 40}}
    target["prior_summaries"] = [{"section_id": "IV", "claim_key": "IV.9", "first_sentence": "SYNTHETIC body summary.",
                                  "support_type": "source_stated", "reading_depth": "selected_sections"}]
    target["validation_context"] = {"source_ids": [p["source_id"] for p in si["sources"]], "column_ids": [COL],
        "cells": [{k: c[k] for k in ("cell_id", "source_version_id", "column_id", "state", "value", "reading_depth")} for c in target["cells"]],
        "accepted_gaps": [], "basis_cells": [], "basis_passages": []}
    si["allowlist"].update(source_ids=[s["source_id"] for s in si["sources"]], passage_ids=[p["passage_id"] for p in si["passages"]],
                           cell_ids=[c["cell_id"] for c in target["cells"]], column_ids=[COL], gap_ids=[])
    claim = _claim(section, passage_ids=[PID])
    if section in {"abstract", "I", "IX"}:
        claim["body_refs"] = ["IV.9"]
    if section == "VII":
        claim["cell_ids"] = [CID]
    draft = envelope(si, "deixis.report_section_draft.v2") | {"section_id": section, "claims": [claim],
        "citation_anchors": [{"claim_key": claim["claim_key"], "passage_id": PID, "cell_id": None,
                              "quote": si["passages"][0]["text"]}], "subsections": [], "gaps": [], "insufficient_evidence": []}
    if section == "VII":
        draft["citation_anchors"] = [{"claim_key": "VII.1", "passage_id": None, "cell_id": CID,
                                      "quote": target["cells"][0]["evidence"][0]["quote"]}]
    return si, draft


def codes(si, draft):
    return contracts.validate_model_output(si, draft).codes()


@pytest.mark.parametrize("where", ["claim", "heading", "gap", "insufficient"])
@pytest.mark.parametrize("language", ["en", "tr"])
def test_banned_word_blocks_each_prose_field(where, language):
    si, draft = packet("VI" if where == "gap" else "VIII")
    si["question"]["language_hint"] = language
    text = REPLAY["bad_texts"]["banned" if language == "en" else "turkish_banned"]
    if where == "claim":
        draft["claims"][0]["text"] = text
    elif where == "heading":
        draft["subsections"] = [{"axis_id": "AX1", "heading": text}]
    elif where == "gap":
        draft["gaps"] = [gap_record(text=text)]
    else:
        draft["insufficient_evidence"] = [{"context": "SYNTHETIC missing basis", "reason": text}]
    assert "banned_word" in codes(si, draft)


@pytest.mark.parametrize("section", ["abstract", "IX"])
@pytest.mark.parametrize("language", ["en", "tr", "zz"])
def test_own_work_is_blocking_with_assembly_language_fallback(section, language):
    si, draft = packet(section)
    si["question"]["language_hint"] = language
    draft["claims"][0]["text"] = REPLAY["bad_texts"]["turkish_own_work" if language == "tr" else "own_work"]
    result = contracts.validate_model_output(si, draft)
    assert "own_work_phrase_in_claim" in result.codes()
    assert "own_work_phrase_in_claim" not in [w.code for w in result.warnings]


def test_plural_source_rule_counts_cell_anchors_and_ignores_uncited_passage_ids():
    si, draft = packet()
    draft["claims"][0]["text"] = "Previous studies report a SYNTHETIC bounded result."
    draft["claims"][0]["passage_ids"] = si["allowlist"]["passage_ids"]
    draft["citation_anchors"] = [{"claim_key": "IV.1", "passage_id": None, "cell_id": CID,
                                  "quote": si["report_target"]["cells"][0]["evidence"][0]["quote"]}]
    assert "plural_sources_for_one_source" in codes(si, draft)
    other = si["report_target"]["cells"][1]
    draft["citation_anchors"].append({"claim_key": "IV.1", "passage_id": None, "cell_id": other["cell_id"], "quote": other["evidence"][0]["quote"]})
    assert "plural_sources_for_one_source" not in codes(si, draft)


def equation_packet():
    si, draft = packet()
    draft["claims"][0].update(equation_ref="EQ4", equation_origin={"passage_id": PID, "text_source": "text_layer"})
    return si, draft


@pytest.mark.parametrize("failure", ["missing", "not_cited", "without_math", "not_in_input", "mismatch", "malformed"])
def test_individual_equation_failures_are_section_issues(failure):
    si, draft = equation_packet()
    claim = draft["claims"][0]
    expected = {"missing": "equation_origin_missing", "not_cited": "equation_origin_not_cited", "without_math": "equation_origin_without_math",
                "not_in_input": "equation_origin_not_in_input", "mismatch": "equation_origin_mismatch", "malformed": "math_not_well_formed"}[failure]
    if failure == "missing":
        claim["equation_origin"] = None
    elif failure == "not_cited":
        draft["citation_anchors"][0].update(passage_id=None, cell_id=CID, quote=si["report_target"]["cells"][0]["evidence"][0]["quote"])
    elif failure == "without_math":
        si["passages"][0]["text"] = draft["citation_anchors"][0]["quote"] = "SYNTHETIC source has no mathematical expression."
    elif failure == "not_in_input":
        claim["equation_origin"]["passage_id"] = "psg_SYNTHRF4999"
    elif failure == "mismatch":
        claim["equation_origin"]["text_source"] = "ocr"
        # A persisted passage anchor is authoritative even when the redundant passage_ids list is empty.
        claim["passage_ids"] = []
    else:
        claim["text"] = "It has been reported that $$x={1$$."
    assert expected in codes(si, draft)


def test_valid_equation_origin_passes_and_display_requires_origin_without_ref():
    si, draft = equation_packet()
    assert contracts.validate_model_output(si, draft).ok
    draft["claims"][0].update(text="It has been reported that $$x=1$$.", equation_ref=None, equation_origin=None)
    assert "equation_origin_missing" in codes(si, draft)


def test_positive_control_valid_origin_and_physical_gap_wording():
    """Positive control: valid origin, physical terminology and math vocabulary pass on old and new code."""
    si, draft = equation_packet()
    draft["claims"][0]["text"] = "It has been reported that the SYNTHETIC band gap is $\\mathrm{novelty}$ dependent."
    assert contracts.validate_model_output(si, draft).ok


@pytest.mark.parametrize("phrase", [
    "Bu çalışmaların", "bu araştırmalarda", "bu makaleler", "bu tezlerde", "mevcut incelemeler",
])
def test_turkish_plural_sources_do_not_trigger_the_own_work_section_issue(phrase):
    si, draft = packet("IX")
    si["question"]["language_hint"] = "tr"
    draft["claims"][0]["text"] = f"{phrase} SYNTHETIC kapsamı sınırlıdır."
    assert "own_work_phrase_in_claim" not in codes(si, draft)


@pytest.mark.parametrize("failure", ["missing", "unknown", "support", "depth"])
def test_derived_rules_are_blocking(failure):
    si, draft = packet("abstract")
    expected = {"missing": "body_ref_missing", "unknown": "body_ref_unknown", "support": "derived_support_too_strong", "depth": "derived_depth_too_deep"}[failure]
    if failure == "missing":
        draft["claims"][0]["body_refs"] = []
    elif failure == "unknown":
        draft["claims"][0]["body_refs"] = ["IV.99"]
    else:
        si["report_target"]["prior_summaries"][0]["support_type" if failure == "support" else "reading_depth"] = "analyst_inference" if failure == "support" else "abstract"
    assert expected in codes(si, draft)


@pytest.mark.parametrize("failure", ["within", "prior", "concurrent_prefix"])
def test_duplicate_keys_and_concurrent_namespace(failure):
    si, draft = packet()
    if failure == "within":
        draft["claims"].append(copy.deepcopy(draft["claims"][0]))
    else:
        draft["claims"][0]["claim_key"] = "IV.9" if failure == "prior" else "V.1"
    assert ("claim_key_section_mismatch" if failure == "concurrent_prefix" else "duplicate_claim_key") in codes(si, draft)


def test_section_word_budget_is_blocking():
    si, draft = packet()
    si["report_target"]["plan"]["section_budgets"]["IV"]["max_words"] = 1
    assert "section_word_count_over_budget" in codes(si, draft)


@pytest.mark.parametrize("failure", ["members", "missing", "depth", "value", "numbers"])
def test_count_rules_use_the_full_frozen_domain(failure):
    si, draft = packet()
    claim = draft["claims"][0]
    claim.update(text="It has been reported that 2 of 2 SYNTHETIC sources agree.", count={"numerator_source_ids": si["allowlist"]["source_ids"].copy(),
                 "denominator_source_ids": si["allowlist"]["source_ids"].copy(), "column_id": COL})
    context = si["report_target"]["validation_context"]
    expected = {"members": "count_members_invalid", "missing": "count_member_not_in_snapshot", "depth": "count_depth_mixed", "value": "count_value_mixed", "numbers": "count_number_mismatch"}[failure]
    if failure == "members":
        claim["count"]["numerator_source_ids"].append(SID)
    elif failure == "missing":
        context["cells"] = context["cells"][:1]
    elif failure == "depth":
        context["cells"][1]["reading_depth"] = "abstract"
    elif failure == "value":
        context["cells"][1]["value"] = {"text": "SYNTHETIC different value"}
    else:
        claim["text"] = "It has been reported that 9 of 9 SYNTHETIC sources agree."
    assert expected in codes(si, draft)


def gap_record(**updates):
    return {"gap_id": "gap9", "kind": "stated_limitation", "text": "SYNTHETIC stated limitation candidate.",
        "basis_claim_keys": [], "basis_passage_ids": [], "basis_cell_ids": [CID],
        "nearest_match": {"status": "not_searched", "source_id": None, "cell_id": None}} | updates


@pytest.mark.parametrize("failure", ["missing", "foreign", "conflict", "absence"])
def test_gap_basis_rules_are_blocking(failure):
    si, draft = packet("VI")
    gap = gap_record()
    expected = {"missing": "gap_basis_missing", "foreign": "gap_basis_foreign", "conflict": "conflict_gap_without_v_claim", "absence": "gap_absence_basis_invalid"}[failure]
    if failure == "missing":
        gap["basis_cell_ids"] = []
    elif failure == "foreign":
        si["report_target"]["plan"]["limitations_column_id"] = None
    elif failure == "conflict":
        gap.update(kind="conflicting_evidence", basis_cell_ids=[], basis_claim_keys=["III.1"])
    else:
        gap.update(kind="corpus_absence")
    draft["gaps"] = [gap]
    assert expected in codes(si, draft)


@pytest.mark.parametrize("support,expected", [("source_stated", "vii_claim_without_basis"), ("analyst_inference", "vii_inference_without_gap")])
def test_vii_requires_an_accepted_gap_or_anchored_future_cell(support, expected):
    si, draft = packet("VII")
    draft["claims"][0]["support_type"] = support
    si["report_target"]["plan"]["future_work_column_id"] = None
    assert expected in codes(si, draft)
    si["report_target"]["validation_context"]["accepted_gaps"] = [{k: v for k, v in gap_record().items() if k != "nearest_match"}]
    si["allowlist"]["gap_ids"] = ["gap9"]
    draft["claims"][0]["gap_refs"] = ["gap9"]
    assert contracts.validate_model_output(si, draft).ok


@pytest.mark.parametrize("still_bad", [False, True])
def test_single_section_repair_sees_new_issues_and_is_bounded(tmp_path, still_bad):
    si, good = packet()
    bad = copy.deepcopy(good)
    bad["claims"][0]["text"] = REPLAY["bad_texts"]["banned"]
    attempts = 0
    def respond(current, schema, message):
        nonlocal attempts
        attempts += 1
        return rebind(bad if attempts == 1 or still_bad else good, current)
    output, store, adapter, _, _ = run_step(tmp_path, "report_section", si, respond)
    assert len(sessions(store)) == attempts == 2
    assert "banned_word" in {i["code"] for i in first_issues(store)}
    assert '"banned_word"' in adapter.requests[1]["message"]
    assert bool(output.get("invalid")) is still_bad


@pytest.mark.parametrize("violation", ["own_work", "banned"])
def test_phrase_repair_introducing_a_violation_retains_the_valid_section(tmp_path, violation):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path, unframed_section="IV")
    original = adapter.responder
    def respond(si):
        if si["task_type"] == "report_phrase_repair" and si["report_target"]["section_id"] == "IV":
            return json.dumps(envelope(si, "deixis.report_phrase_repair_draft.v1") | {
                "repairs": [{"sentence_id": s["sentence_id"], "text": REPLAY["bad_texts"][violation]} for s in si["report_target"]["repair_request"]["sentences"]]})
        return original(si)
    adapter.responder = respond
    asyncio.run(run_report(flow, run, scope))
    section = reports.section(report_id, "IV")
    assert section["status"] == "valid"
    assert reports.report(report_id)["status"] == "valid"
    assert section["draft"]["claims"][0]["text"] == "Fig weiro randomtext not a frame sentence at all zzq."
    expected = "own_work_phrase_in_claim" if violation == "own_work" else "banned_word"
    rejection = next(i for i in section["validation"]["issues"] if i["code"] == "phrase_repair_rejected")
    assert expected in rejection["blocking_codes"]
    assert len([c for c in adapter.calls if c["task_type"] == "report_phrase_repair" and c["report_target"]["section_id"] == "IV"]) == 1


def test_review_reversion_invokes_complete_validator_on_original_input(tmp_path, monkeypatch):
    flow, store, reports, _, run, scope, report_id = report_flow(tmp_path, unframed_section="IV")
    asyncio.run(run_report(flow, run, scope))
    section = reports.section(report_id, "IV")
    original = store.step_input_payload(section["draft"]["step_input_id"])
    seen = []
    validate = contracts.validate_model_output
    def reject(payload, draft):
        seen.append(copy.deepcopy(payload))
        result = validate(payload, draft)
        result.issues.append(contracts.Issue("SYNTHETIC_complete_validator", "/claims/0/text", "SYNTHETIC refusal"))
        return result
    monkeypatch.setattr(contracts, "validate_model_output", reject)
    assert reports.revert_repair(report_id, "IV", "IV.1#1") == "would_break_assembly"
    assert seen == [original]
    assert reports.section(report_id, "IV") == section
    assert reports.report(report_id)["status"] == "valid"
    assert store.conn.execute("SELECT COUNT(*) FROM events WHERE type = 'report_repair_restoration_rejected'").fetchone()[0] == 1


def test_vii_receives_accepted_vi_bases_without_widening_citations(tmp_path):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    asyncio.run(run_report(flow, run, scope))
    call = next(c for c in adapter.calls if c["task_type"] == "report_section" and c["report_target"]["section_id"] == "VII")
    context = call["report_target"]["validation_context"]
    assert context["accepted_gaps"][0]["gap_id"] == "gap9"
    assert context["basis_cells"] and context["basis_passages"]
    assert call["allowlist"]["gap_ids"] == ["gap9"]
    assert not {c["cell_id"] for c in context["basis_cells"]} & set(call["allowlist"]["cell_ids"])


def test_context_cap_fails_section_before_any_send_without_truncation(tmp_path, monkeypatch):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    original = sections._validation_context
    def oversized(*args):
        context = original(*args)
        context["cells"][0]["value"] = {"text": "SYNTHETIC " * 30000}
        return context
    monkeypatch.setattr(sections, "_validation_context", oversized)
    with pytest.raises(RunStopped):
        asyncio.run(run_report(flow, run, scope))
    assert not [c for c in adapter.calls if c["task_type"] == "report_section"]
    assert reports.section(report_id, "IV")["status"] == "failed"
    assert reports.section(report_id, "IV")["validation"]["issues"][0]["code"] == "report_validation_context_too_large"


def test_frozen_count_context_does_not_grant_citation_rights():
    si, draft = packet()
    other = si["report_target"]["cells"][1]
    si["report_target"]["cells"] = si["report_target"]["cells"][:1]
    si["sources"] = si["sources"][:1]
    si["allowlist"]["source_ids"] = [SID]
    si["allowlist"]["cell_ids"] = [CID]
    si["passages"] = si["passages"][:2]
    si["allowlist"]["passage_ids"] = [p["passage_id"] for p in si["passages"]]
    draft["claims"][0].update(text="It has been reported that 1 of 2 SYNTHETIC sources meets the criterion.", count={
        "numerator_source_ids": [SID], "denominator_source_ids": [SID, other["source_version_id"]], "column_id": COL})
    assert contracts.validate_model_output(si, draft).ok
    draft["claims"][0]["cell_ids"] = [other["cell_id"]]
    draft["citation_anchors"] = [{"claim_key": "IV.1", "passage_id": None, "cell_id": other["cell_id"], "quote": other["evidence"][0]["quote"]}]
    assert "unknown_cell_id" in codes(si, draft)


def test_corpus_absence_uses_all_frozen_full_text_cells_without_citation_expansion():
    si, draft = packet("VI")
    context = si["report_target"]["validation_context"]
    third = dict(context["cells"][0], cell_id="cel_SYNTHRF4003", source_version_id="srv_SYNTHRF4003")
    context["cells"].append(third)
    context["source_ids"].append(third["source_version_id"])
    for c in context["cells"]:
        c.update(state="not_found_in_inspected_scope", value=None)
    basis = [c["cell_id"] for c in context["cells"]]
    si["report_target"]["gap_candidates"] = [{"gap_id": "gap1", "kind": "corpus_absence", "column_id": COL,
        "basis_cell_ids": basis, "full_text_applicable_count": 3, "summary_only_count": 0}]
    si["allowlist"]["gap_ids"] = ["gap1"]
    draft["gaps"] = [gap_record(gap_id="gap1", kind="corpus_absence", basis_cell_ids=basis)]
    draft["claims"][0]["gap_refs"] = ["gap1"]
    assert contracts.validate_model_output(si, draft).ok
    context["cells"].append(dict(third, cell_id="cel_SYNTHRF4004", source_version_id="srv_SYNTHRF4004"))
    assert "gap_absence_basis_invalid" in codes(si, draft)


@pytest.mark.parametrize("section,violation,still_bad", [
    ("VIII", "banned", False), ("VIII", "banned", True),
    ("abstract", "own_work", False), ("IX", "own_work", False),
    ("IV", "equation", False), ("IV", "equation", True),
])
def test_h9b_shapes_repair_at_the_section_or_end_section_failed(tmp_path, section, violation, still_bad):
    flow, store, reports, adapter, run, scope, report_id = report_flow(tmp_path)
    original = adapter.responder
    count = 0
    def respond(si):
        nonlocal count
        draft = json.loads(original(si))
        if si["task_type"] == "report_section" and si["report_target"]["section_id"] == section:
            count += 1
            if count == 1 or still_bad:
                claim = draft["claims"][0]
                if violation == "equation":
                    # Origin is listed but has no math; the only anchor is a cell anchor.
                    pid = si["passages"][0]["passage_id"]
                    claim.update(equation_ref="EQ4", equation_origin={"passage_id": pid, "text_source": "text_layer"}, passage_ids=[pid])
                else:
                    claim["text"] = REPLAY["bad_texts"][violation]
        return json.dumps(draft)
    adapter.responder = respond
    if still_bad:
        with pytest.raises(RunStopped):
            asyncio.run(run_report(flow, run, scope))
        assert reports.section(report_id, section)["status"] == "failed"
        assert store.run(run["id"])["pause_reason"] == "section_failed"
    else:
        asyncio.run(run_report(flow, run, scope))
        assert reports.report(report_id)["status"] == "valid"
    assert count == 2
    model_rows = list(store.conn.execute("SELECT m.validation_json FROM model_sessions m JOIN step_inputs si ON si.id = m.step_input_id JOIN run_steps s ON s.id = si.step_id WHERE s.run_id = ? AND s.operation_key = ? ORDER BY si.attempt", (run["id"], f"report_section:{section}")))
    issues = {i["code"] for i in json.loads(model_rows[0][0])["issues"]}
    expected = {"banned": {"banned_word"}, "own_work": {"own_work_phrase_in_claim"}, "equation": {"equation_origin_not_cited", "equation_origin_without_math"}}[violation]
    assert expected <= issues


def test_anchor_patch_is_fully_revalidated_against_original_input(tmp_path, monkeypatch):
    si, draft = packet()
    draft["claims"][0]["cell_ids"] = [CID]
    draft["citation_anchors"] = [{"claim_key": "IV.1", "passage_id": None, "cell_id": CID, "quote": "SYNTHETIC missing quote from cell."}]
    calls = 0
    def respond(current, schema, message):
        nonlocal calls
        calls += 1
        if calls == 1:
            return rebind(draft, current)
        return {"schema_version": "deixis.report_section_anchor_repair.v1", "step_input_id": current["step_input_id"], "scope_revision": current["scope_revision"],
                "anchors": [{"anchor_index": 0, "quote_number": 1}], "claims": [{"claim_key": "IV.1", "removed": False,
                    "text": REPLAY["bad_texts"]["own_work"], "context": None, "reason": None}]}
    seen = []
    validate = contracts.validate_model_output
    def capture(payload, output):
        seen.append(copy.deepcopy(payload))
        return validate(payload, output)
    monkeypatch.setattr(contracts, "validate_model_output", capture)
    output, store, _, _, _ = run_step(tmp_path, "report_section", si, respond)
    assert output["invalid"]
    assert "own_work_phrase_in_claim" in {i["code"] for i in output["issues"]}
    original = store.step_input_payload(sessions(store)[0]["step_input_id"])
    assert seen[-1] == original
    assert calls == 2
