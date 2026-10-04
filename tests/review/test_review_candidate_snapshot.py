"""SYNTHETIC feature regressions for candidate copies and fail-closed quote mapping."""

import copy
import json

import pytest

from deixis.domain import contracts
from deixis.domain.canonical import canonical_json
from deixis.workflow.candidates.store import CandidateStore
from deixis.workflow.review.snapshot import build_snapshot, NotReviewable, review_step_input_parts
from deixis.workflow.review.store import NotFound, _snapshot_source_ids
from tests.review.review_candidate_helpers import report_with_sections, review_lib, candidate_lib, snapshot, add_version, search
from tests.review.test_review_run import envelope


def test_candidate_snapshot_equals_stored_input_after_new_version_override_and_passage_edit(candidate_lib, monkeypatch):
    lib = candidate_lib
    saved = snapshot(lib)
    c = saved["content"]
    assert "status" not in c and "validation_plan" not in c
    assert c["candidate_version"] == 1 and len(c["elements"]) == 3
    assert len(c["matrix"]) == 2 and len(c["passages"]) == 4
    assert c["kill_search"]["assessed"] == 2 and c["kill_search"]["unread"] == 1
    payload = envelope(c, {"claim_refs": [], "source_ids": [m["source_id"] for m in c["matrix"]], "group_index": 1, "group_count": 1})
    payload["review_input"]["review_snapshot_id"] = saved["id"]
    assert contracts.check_step_input(payload) == []
    step = lib["store"].step(lib["search"]["run_id"], "SYNTHETIC-frozen-review", "model:owner_review")
    payload["step_id"] = step["id"]
    payload["run_id"] = lib["search"]["run_id"]
    lib["store"].insert_step_input(step["id"], lib["rid"], payload["run_id"], 0, payload, "SYNTHETIC", "SYNTHETIC", "SYNTHETIC", {})
    before = canonical_json(payload)
    newer = add_version(lib)
    cs = CandidateStore(lib["store"])
    cs.record_owner_decision(lib["rid"], newer["id"], "undecided", "SYNTHETIC later version reason")
    cs.record_owner_decision(lib["rid"], lib["candidate_version_id"], "undecided", "SYNTHETIC reviewed version reason")
    # Passage rows are immutable; simulate a changed read without weakening their triggers.
    live_passage = lib["reader"].passage
    monkeypatch.setattr(lib["reader"], "passage", lambda pid: live_passage(pid) | {"text": "SYNTHETIC edited live passage"})
    assert canonical_json(lib["store"].step_input_payload(payload["step_input_id"])) == before
    parts = review_step_input_parts(saved["id"], lib["reviews"].snapshot(saved["id"])["content"], focus="source_support", owner_note="SYNTHETIC owner instruction.")
    assert {k: payload[k] for k in parts} == parts
    assert _snapshot_source_ids(saved["id"], saved["content_json"]) == {m["source_id"] for m in c["matrix"]}


@pytest.mark.parametrize("case", ["missing", "foreign", "historical", "trash", "paused", "running", "none"])
def test_candidate_target_refusals(candidate_lib, case):
    lib = candidate_lib
    tid, rid = lib["candidate_version_id"], lib["rid"]
    if case == "missing": tid = "clv_missing"
    elif case == "foreign": rid = lib["store"].create_research("SYNTHETIC other", "attached", "quick", [], "fake", "fake-model", "en")
    elif case == "historical": add_version(lib)
    elif case == "trash": CandidateStore(lib["store"]).trash_candidate(rid, lib["candidate_id"])
    elif case == "none": tid = add_version(lib)["id"]
    else: search(lib, outcome=case)
    with pytest.raises(NotFound if case in {"missing", "foreign"} else NotReviewable):
        build_snapshot(lib["reader"], rid, "candidate", tid)


@pytest.mark.parametrize("outcome", ["failed", "stopped", "completed"])
def test_latest_terminal_search_is_reviewable_with_its_own_counts(candidate_lib, outcome):
    lib = candidate_lib; latest = search(lib, outcome=outcome, assessed=False)
    content, _ = build_snapshot(lib["reader"], lib["rid"], "candidate", lib["candidate_version_id"])
    assert content["kill_search"]["id"] == latest["id"] and content["kill_search"]["outcome"] == outcome
    assert content["matrix"] == [] and content["kill_search"]["unread"] == 3


def test_abstract_quote_maps_to_exact_assessment_abstract(candidate_lib):
    c = snapshot(candidate_lib)["content"]
    q = c["matrix"][0]["cells"][1]["quotes"][0]
    p = next(p for p in c["passages"] if p["passage_id"] == q["passage_id"])
    assert p["locator"]["kind"] == q["evidence_kind"] == "abstract" and q["quote"] in p["text"]


@pytest.mark.parametrize("case,reason", [("missing", "assessment step input is missing"),
    ("no_abstract", "assessment abstract passage is missing or ambiguous"),
    ("two_abstracts", "assessment abstract passage is missing or ambiguous"),
    ("foreign", "assessment passage belongs to another source"),
    ("unlocated", "matrix quote is not located in assessment passage"),
    ("unshown", "matrix quote passage was not supplied to assessment")])
def test_broken_assessment_quote_stops_snapshot_without_dropping_evidence(candidate_lib, monkeypatch, case, reason):
    lib = candidate_lib; reader = lib["reader"]
    build_snapshot(reader, lib["rid"], "candidate", lib["candidate_version_id"])
    original = reader.assessment_input
    hit = CandidateStore(lib["store"]).hits(lib["search"]["id"])[0]
    def changed(sti):
        raw = original(sti)
        if sti != hit["step_input_id"]: return raw
        if case == "missing": return None
        data = json.loads(raw)
        if case == "no_abstract": data["passages"] = data["passages"][1:]
        elif case == "two_abstracts": data["passages"][1]["locator"]["kind"] = "abstract"
        elif case == "foreign": data["passages"][0]["source_id"] = "srv_FOREIGN001"
        elif case == "unlocated": data["passages"][0]["text"] = "SYNTHETIC unrelated words"
        else: data["passages"] = data["passages"][:1]
        return json.dumps(data)
    monkeypatch.setattr(reader, "assessment_input", changed)
    with pytest.raises(NotReviewable, match=reason):
        build_snapshot(reader, lib["rid"], "candidate", lib["candidate_version_id"])
