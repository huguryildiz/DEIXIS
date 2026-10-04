"""Packing preservation with identical measured envelopes, instructions and package identity."""

import copy

import pytest

from deixis.domain.skill import SkillPackage
from deixis.workflow.flow import CAPABILITIES
from deixis.workflow.review import run
from tests.review_helpers import si


@pytest.mark.parametrize("kind", ["answer", "report"])
def test_answer_and_report_near_boundary_packing_preserved_with_identical_inputs(kind, monkeypatch, tmp_path):
    fixture = si(kind)
    part = fixture["review_input"]
    refs = [f"III.{i}" if kind == "report" else f"c{i}" for i in range(1, 5)]
    content = dict(research_id=fixture["research_id"], target_kind=kind, scope_revision=1,
        scope=dict(question="SYNTHETIC question", language="en", steering=None),
        claims=[part["claims"][0] | {"claim_ref": ref, "text": "SYNTHETIC " + "x" * 3990, "section_ref": "III" if kind == "report" else None,
            "citations": [], "revision_id": None, "text_origin": "model", "support_type": "analyst_inference", "table_ref": None, "count": None} for ref in refs],
        sections=[{"section_ref": "III", "title": "SYNTHETIC section", "status": "valid"}] if kind == "report" else [], cells=[], columns=[],
        sources=copy.deepcopy(fixture["sources"]), passages=copy.deepcopy(fixture["passages"][:1]), elements=[], candidate_statement=None)
    for claim in content["claims"]:
        claim["citations"] = [{"passage_id": content["passages"][0]["passage_id"], "cell_id": None, "anchor_text": "SYNTHETIC", "anchor_match": "exact"}]
    content["passages"][0]["text"] = "SYNTHETIC"
    package = SkillPackage(tmp_path, "sha256:" + "1" * 64,
        {"SKILL.md": "SYNTHETIC identical instructions.", "references/review.md": "SYNTHETIC identical review method."})
    original = run.first_request
    measured = []
    def common_request(payload, package, enforces):
        payload = copy.deepcopy(payload)
        # Isolate packing policy from the separately measured shared-contract addition.
        payload["review_input"].pop("candidate_context", None)
        measured.append(payload)
        return original(payload, package, enforces)
    monkeypatch.setattr(run, "first_request", common_request)
    row = dict(focus="source_support", owner_note=None, requested_connection="fake", requested_model="review-model")
    payload = run.review_step_input("rvs_" + "0" * 20, content, row,
        dict(claim_refs=refs[:2], group_index=1, group_count=2), run_id="run_" + "0" * 20,
        step_id="stp_" + "0" * 20, research_id=content["research_id"], package_hash=package.package_hash,
        capabilities=CAPABILITIES, budget=run.review_budget(2), step_input_id="sti_" + "0" * 20, created_at=run.PLAN_TIME)
    initial = common_request(payload, package, True)
    padding = run.REVIEW_GROUP_CHAR_LIMIT - 1 - initial
    assert padding > 0
    content["passages"][0]["text"] += "x" * padding
    ceiling = run.REVIEW_GROUP_CHAR_LIMIT - 1
    planned = run.plan_groups("rvs_" + "0" * 20, content, "source_support", None,
        ("fake", "review-model", "high"), package, CAPABILITIES)
    assert [g["claim_refs"] for g in planned["groups"]] == [refs[:2], refs[2:]]
    assert not planned["not_reviewed"]
    assert all(g["request_chars"] == ceiling for g in planned["groups"])
    assert all(p["skill_package_hash"] == package.package_hash and "candidate_context" not in p["review_input"] for p in measured)
