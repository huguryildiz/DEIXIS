"""SYNTHETIC source grouping and refusal without truncation."""

import copy

import pytest

from deixis.workflow.review.snapshot import ReviewInputTooLarge, review_step_input_parts
from tests.review_candidate_helpers import report_with_sections, review_lib, candidate_lib, snapshot
from tests.test_review_run import plan, envelope


def test_candidate_packs_by_assessed_source_with_all_shared_elements(candidate_lib, monkeypatch):
    from deixis.workflow.review import run
    c = snapshot(candidate_lib)["content"]
    baseline = plan(c); assert len(baseline["groups"]) == 1
    sizes = []
    for source in c["matrix"]:
        single = copy.deepcopy(c); single["matrix"] = [source]
        sizes.append(plan(single)["groups"][0]["request_chars"])
    monkeypatch.setattr(run, "REVIEW_GROUP_CHAR_LIMIT", max(sizes) + 100)
    planned = plan(c)
    assert len(planned["groups"]) == 2
    assert [g["source_ids"] for g in planned["groups"]] == [[m["source_id"]] for m in c["matrix"]]
    for g in planned["groups"]:
        si = envelope(c, g)
        assert si["review_input"]["elements"] == [{k: e[k] for k in ("element_ref", "position", "kind", "text")} for e in c["elements"]]
        assert len(si["review_input"]["candidate_context"]["matrix"]) == 1
        assert all(p["source_id"] in g["source_ids"] for p in si["passages"])
        assert g["claim_refs"] == []


def test_source_too_large_is_recorded_without_cutting_passages(candidate_lib):
    c = snapshot(candidate_lib)["content"]
    sid = c["matrix"][0]["source_id"]
    for p in c["passages"]:
        if p["source_id"] == sid: p["text"] = "SYNTHETIC " + "x" * 100000
    original = copy.deepcopy(c)
    planned = plan(c)
    assert len(planned["groups"]) == 1 and planned["groups"][0]["source_ids"] == [c["matrix"][1]["source_id"]]
    assert "source_too_large" in {r["reason"] for r in planned["not_reviewed"]}
    assert {r["source_id"] for r in planned["not_reviewed"]} == {sid}
    assert all(r["claim_ref"] is None and r["section_ref"] is None for r in planned["not_reviewed"])
    assert c == original


def test_no_assessed_source_gets_one_empty_matrix_group(candidate_lib):
    c = snapshot(candidate_lib)["content"]; c["matrix"] = []; c["passages"] = []; c["sources"] = []
    planned = plan(c)
    assert len(planned["groups"]) == 1 and planned["groups"][0]["source_ids"] == []
    assert envelope(c, planned["groups"][0])["review_input"]["candidate_context"]["matrix"] == []


@pytest.mark.parametrize("field", ["conditions", "critical_assumption", "nearest_simple_explanation", "candidate_statement", "element", "owner_reason"])
def test_shared_candidate_bound_refuses_whole_candidate_without_cut(candidate_lib, field):
    c = snapshot(candidate_lib)["content"]
    if field == "conditions": c[field] = ["SYNTHETIC " + "x" * 301]
    elif field == "element": c["elements"][0]["text"] = "SYNTHETIC " + "x" * 4001
    elif field == "owner_reason": c["candidate_status"]["owner"]["reason"] = "SYNTHETIC " + "x" * 2001
    else: c[field] = "SYNTHETIC " + "x" * 4001
    original = copy.deepcopy(c)
    with pytest.raises(ReviewInputTooLarge): review_step_input_parts("rvs_SYNTHSNAP01", c, focus="source_support", owner_note=None)
    planned = plan(c)
    assert planned["groups"] == [] and planned["not_reviewed"][0]["reason"] == "candidate_too_large"
    assert c == original


def test_source_matrix_bound_is_recorded_per_source(candidate_lib):
    c = snapshot(candidate_lib)["content"]; c["matrix"][0]["note"] = "SYNTHETIC " + "x" * 401
    planned = plan(c)
    assert len(planned["groups"]) == 1
    assert planned["not_reviewed"][0]["source_id"] == c["matrix"][0]["source_id"]
    assert planned["not_reviewed"][0]["reason"] == "note_too_long"


def test_shared_candidate_keeps_each_measured_bound_reason_with_null_source(candidate_lib):
    c = snapshot(candidate_lib)["content"]
    c["conditions"] = ["SYNTHETIC condition"] * 7
    c["critical_assumption"] = "SYNTHETIC " + "x" * 4001
    original = copy.deepcopy(c)
    planned = plan(c)
    rows = planned["not_reviewed"]
    assert planned["groups"] == []
    assert [r["reason"] for r in rows] == ["candidate_too_large", "too_many_conditions", "critical_assumption_too_long"]
    assert all(r["source_id"] is None and r["claim_ref"] is None and r["section_ref"] is None for r in rows)
    assert len({r["request_chars"] for r in rows}) == 1
    assert c == original
