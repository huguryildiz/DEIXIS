"""Synthetic ordering and read-model checks; no relevance or live-provider validation."""

import json

import pytest

from deixis.domain import canonical
from deixis.workflow import small_batch, fulltext


def manifest(n=61, priority=()):
    pool = [{"id": f"v{i:03}", "work_id": f"w{i:03}", "title": f"SYNTHETIC tomato irrigation {i}",
             "abstract": None if i % 3 else "SYNTHETIC greenhouse irrigation",
             "own_ids": {f"W{i}"}, "references": None if i % 2 else {"W0"}} for i in range(n)]
    return {"pool": pool, "versions": {r["id"]: r for r in pool}, "verified": [],
            "query_words": {"tomato", "irrigation"}, "blocks": {"setting": ["tomato"], "task": ["irrigation"]},
            "embedding_model": "synthetic", "similarities": {r["id"]: i / n for i, r in enumerate(pool) if i % 4},
            "off_reason": None, "compared_terms": None, "user_priority": list(priority)}


def test_fused_order_and_manifest_are_exactly_replayable():
    listing = small_batch.build_list(manifest())
    stored = json.loads(json.dumps(listing))
    assert stored["manifest_hash"] == canonical.sha256_hex(stored["manifest"])
    assert stored["automatic_order"] == small_batch.replay(stored["manifest"])["fused"]
    assert stored["order_hash"] == canonical.sha256_hex(stored["order"])
    assert small_batch.build_list(stored["manifest"]) == stored
    assert len(set(item["work_id"] for item in stored["items"])) == 61


@pytest.mark.parametrize("n,sizes", [(0, []), (29, [29]), (49, [30, 19]), (50, [30, 20]),
                                     (59, [30, 29]), (60, [30, 30]), (61, [30, 30, 1])])
def test_batch_boundaries(n, sizes):
    listing = small_batch.build_list(manifest(n))
    plans = [small_batch.next_batch(listing, i) for i in range(len(sizes))]
    assert [len(plan["work_ids"]) for plan in plans] == sizes
    assert [head for plan in plans for head in plan["order"]] == listing["order"]


def test_user_priority_does_not_reorder_automatic_section():
    listing = small_batch.build_list(manifest(priority=["v020", "v001"]))
    assert listing["order"][:2] == ["v020", "v001"]
    assert listing["order"][2:] == [head for head in listing["automatic_order"] if head not in ("v020", "v001")]


@pytest.mark.parametrize("code,processed,blocker", [
    ("no_fulltext", True, None), ("text_unreadable", True, None), ("all_parts_verified", True, None),
    ("fulltext_runs_disagree", False, "human_pending"), ("include_quote_unverified", False, "human_pending"),
    ("not_read_yet", False, "budget_deferred")])
def test_terminal_access_is_distinct_from_inclusion_and_human_blockers(code, processed, blocker):
    item = {"work_id": "w", "head": "v", "position": 1, "user_priority": False}
    work = {"work_id": "w", "head": "v", "versions": [{"id": "v", "fulltext": {
        "reason_code": code, "decided_by": "code", "stale": False}, "abstract": None}]}
    state = small_batch.work_state(item, work)
    assert state["processed"] is processed
    assert state["blocker"] == blocker
    assert state["included"] is (code == "all_parts_verified")


def test_common_fetch_order_does_not_promote_candidate_over_unresolved():
    works = [{"work_id": head, "head": head, "chained": i % 2, "versions": [{"id": head,
              "has_text": False, "fulltext": None, "abstract": {"reason_code": code,
              "decided_by": "code", "stale": False}}]} for i, (head, code) in enumerate([
                  ("v1", "runs_agree_unresolved"), ("v2", "blocks_in_title"), ("v3", "blocks_in_title")])]
    assert fulltext.fetch_plan(works, ["v1", "v2", "v3"], 2, preserve_order=True)["works"] == ["v1", "v2"]
    baseline = fulltext.baseline_of(works)
    assert fulltext.safe_to_fetch(works, ["v1", "v2", "v3"], 2, (), 0, {"v1"}, baseline,
                                  preserve_order=True) == ["v2"]


def test_human_fulltext_inclusion_is_terminal_without_becoming_model_adjudication():
    item = {"work_id": "w", "head": "v", "position": 1, "user_priority": False}
    work = {"work_id": "w", "head": "v", "versions": [{"id": "v", "fulltext": {
        "reason_code": "human_include", "decided_by": "human", "stale": False}, "abstract": None}]}
    state = small_batch.work_state(item, work)
    assert state["processed"] and state["included"]
    assert not state["fulltext_adjudicated"]
