"""Synthetic planning and envelope checks; no model/provider quality evidence."""

import copy
import json

import pytest

from deixis.domain import contracts, skill
from deixis.domain.rules import schema_repairs
from deixis.models import prompt
from deixis.workflow.flow import CAPABILITIES
from deixis.workflow.report.review import REVIEW_BUDGET_TOKENS
from deixis.workflow.review import run as reviews
from deixis.workflow.review.snapshot import build_snapshot
from tests.review_helpers import report_with_sections, review_lib, si


def content(lib, kind="report"):
    return build_snapshot(lib["reader"], lib["rid"], kind, lib[kind + "_id"])[0]


def plan(saved, **kwargs):
    return reviews.plan_groups("rvs_" + "0" * 20, saved, "source_support", None,
        ("fake", "review-model", "high"), skill.load_skill_package(), CAPABILITIES, **kwargs)


def envelope(saved, group, **kwargs):
    return reviews.review_step_input("rvs_" + "0" * 20, saved,
        {"focus": "source_support", "owner_note": "SYNTHETIC owner instruction.",
         "requested_connection": "fake", "requested_model": "review-model"}, group,
        run_id="run_" + "0" * 20, step_id="stp_" + "0" * 20, research_id=saved["research_id"],
        package_hash=skill.package_hash(), capabilities=CAPABILITIES, budget=reviews.review_budget(group["group_count"]),
        step_input_id="sti_" + "0" * 20, created_at=reviews.PLAN_TIME, **kwargs)


@pytest.mark.parametrize("kind", ["answer", "report", "candidate"])
def test_review_envelope_all_fixture_targets_and_capability_copy(kind):
    fixture = si(kind)
    part = fixture["review_input"]
    saved = {"research_id": fixture["research_id"], "target_kind": kind, "scope_revision": fixture["scope_revision"],
             "scope": {"question": fixture["question"]["text"], "language": "en", "steering": "SYNTHETIC steering"},
             "claims": copy.deepcopy(part["claims"]), "sections": copy.deepcopy(part["sections"]),
             "cells": [], "columns": part["columns"], "sources": fixture["sources"], "passages": fixture["passages"],
             "elements": part["elements"], "candidate_statement": part["candidate_statement"]}
    if kind == "candidate":
        from tests.review_candidate_helpers import candidate_context_fixture
        context = candidate_context_fixture(fixture)
        saved.update({k: context[k] for k in ("candidate_version", "conditions", "critical_assumption", "nearest_simple_explanation")})
        saved.update(kill_search=context["kill_search"], candidate_status=context["status"], matrix=context["matrix"])
    for c in part["cells"]:
        saved["cells"].append(c | {"source_version_id": c["source_id"], "value": json.loads(c["value_text"]) if c["value_text"] else None})
    before = copy.deepcopy(CAPABILITIES)
    payload = envelope(saved, {"group_index": 1, "group_count": 1, "claim_refs": [c["claim_ref"] for c in saved["claims"]]})
    assert contracts.check_step_input(payload) == []
    assert CAPABILITIES == before
    assert payload["capabilities"]["supported_tasks"] == before["supported_tasks"] + ["owner_review"]
    assert payload["capabilities"]["unsupported_tasks"] == before["unsupported_tasks"]
    assert "claim_check" in payload["capabilities"]["unsupported_tasks"]
    assert payload["enabled_providers"] == payload["candidates"] == payload["human_corrections"] == []
    assert "SYNTHETIC owner instruction." in prompt.step_message(payload)
    assert schema_repairs("owner_review") == 1


@pytest.mark.parametrize("schema_mode", [True, False])
def test_request_size_counts_exactly_one_schema(schema_mode):
    schema = contracts.step_output_schema("owner_review")
    developer = "developer" + ("\n\n" + prompt.schema_appendix("owner_review", schema) if not schema_mode else "")
    expected = len("base") + len(developer) + len("message")
    if schema_mode:
        expected += len(json.dumps(schema, separators=(",", ":"), ensure_ascii=False))
    assert reviews.request_chars("base", developer, "message", schema, schema_mode) == expected
    assert REVIEW_BUDGET_TOKENS * 4 == reviews.REVIEW_REQUEST_CHAR_LIMIT == 120000
    assert reviews.REVIEW_GROUP_CHAR_LIMIT == 96000


def test_planner_splits_closed_claim_bound_without_passages_and_is_deterministic(review_lib):
    saved = content(review_lib, "answer")
    base = saved["claims"][0]
    saved["claims"] = [base | {"claim_ref": f"c{i}", "text": "x", "citations": []} for i in range(1, 103)]
    saved["passages"] = saved["sources"] = []
    first = plan(saved)
    assert first == plan(saved)
    assert [len(g["claim_refs"]) for g in first["groups"]] == [100, 2]
    assert first["not_reviewed"] == []
    for group in first["groups"]:
        assert contracts.check_step_input(envelope(saved, group)) == []


@pytest.mark.parametrize("bound,reason", [("text", "claim_text_too_long"), ("citations", "too_many_citations"),
                                         ("cell", "cell_value_too_large"), ("size", "claim_too_large")])
def test_planner_records_unrepresentable_single_claim_without_truncation(review_lib, bound, reason):
    saved = content(review_lib)
    saved["claims"] = [next(c for c in saved["claims"] if c["claim_ref"] == "III.1")]
    if bound == "text":
        saved["claims"][0]["text"] = "x" * 4001
    elif bound == "citations":
        saved["claims"][0]["citations"] *= 25
    elif bound == "cell":
        saved["cells"][0]["value"] = {"text": "x" * 4001}
    else:
        next(p for p in saved["passages"] if p["passage_id"] == review_lib["section_passage"])["text"] = "x" * 100000
    before = copy.deepcopy(saved)
    result = plan(saved)
    assert not result["groups"]
    assert reason in {r["reason"] for r in result["not_reviewed"]}
    assert all(r["claim_ref"] == "III.1" and r["section_ref"] == "III" for r in result["not_reviewed"])
    assert all(isinstance(r["request_chars"], int) and r["request_chars"] > 0 for r in result["not_reviewed"])
    assert saved == before


def test_planner_records_more_than_48_passages_for_one_claim(review_lib):
    saved = content(review_lib, "answer")
    p = saved["passages"][0]
    saved["passages"] = [p | {"passage_id": "psg_" + f"{i:020d}"} for i in range(49)]
    saved["claims"][0]["citations"] = [{"passage_id": p["passage_id"], "cell_id": None, "anchor_text": "x"} for p in saved["passages"]]
    result = plan(saved)
    assert result["groups"] == []
    assert "too_many_passages" in {r["reason"] for r in result["not_reviewed"]}
    assert all(r["section_ref"] is None for r in result["not_reviewed"])


@pytest.mark.parametrize("status", ["queued", "running", "pause_requested", "paused", "cancelled", "failed"])
def test_derived_state_preserves_run_status_and_unknown(status):
    value = reviews.review_state({"status": status, "pause_reason": "SYNTHETIC", "steps": [{"status": "outcome_unknown"}]},
        {"sections_not_reviewed_json": "[]", "failure_reason": None}, 1, 2)
    assert value["state"] == status and value["outcome_unknown"]
    assert value["pause_reason"] == "SYNTHETIC"


@pytest.mark.parametrize("done,omitted,state", [(0, [], "failed"), (1, [], "partial"), (2, [], "completed"), (2, ["x"], "partial")])
def test_completed_coverage_derived_state(done, omitted, state):
    value = reviews.review_state({"status": "completed"}, {"sections_not_reviewed_json": json.dumps(omitted)}, done, 2)
    assert value["state"] == state
    assert value["failure_reason"] == ("nothing_reviewed" if not done else None)
