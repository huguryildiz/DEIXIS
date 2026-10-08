"""Synthetic ordering and read-model checks; no relevance or live-provider validation."""

import json

import pytest

from deixis.domain import canonical
from deixis.workflow import small_batch, fulltext, ranking


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


def test_v1_replay_is_rank_pool_even_when_counts_are_present():
    stored = manifest()
    for i, row in enumerate(stored["pool"]):
        row["cited_by_count"] = i
    expected = ranking.rank_pool(stored["pool"], stored["verified"], stored["query_words"],
                                 stored["blocks"], stored["embedding_model"], stored["similarities"],
                                 stored["off_reason"], stored["compared_terms"])
    assert small_batch.replay(stored) == expected


@pytest.mark.parametrize("n", [0, 12, 65, 520])
def test_v2_protects_top20_and_tail_with_pool_wide_weighted_ranks(n):
    stored = manifest(n)
    base = small_batch.replay(stored)
    # Reverse citation preference, including a highly cited work outside the gate.
    counts = {rid: i for i, rid in enumerate(base["fused"])}
    for row in stored["pool"]:
        row["cited_by_count"] = counts[row["id"]] if counts[row["id"]] % 3 else None
    stored["ranking_version"] = 2
    ranked = small_batch.replay(stored)
    assert ranked["fused"][:20] == base["fused"][:20]
    assert ranked["fused"][500:] == base["fused"][500:]
    assert set(ranked["fused"][20:500]) == set(base["fused"][20:500])
    cite_ranks = ranked["ranks"]["cites"]
    have = [rid for rid, (_, available) in cite_ranks.items() if available]
    missing = [rank for rank, available in cite_ranks.values() if not available]
    assert len(set(missing)) <= 1
    if missing:
        assert missing[0] == (len(have) + n + 1) / 2
        assert all(cite_ranks[rid][0] < missing[0] for rid in have)
    # Independent weighted-fusion oracle via repeated signals and the existing fuse.
    ranks = base["ranks"] | {"cites": cite_ranks, "cites_again": cite_ranks}
    if "graph" in ranks:
        ranks["graph_again"] = ranks["graph"]
    gate = set(base["fused"][20:500])
    expected = [rid for rid in ranking.fuse(ranks, tuple(ranks)) if rid in gate]
    assert ranked["fused"][20:500] == expected
    if n > 20:
        assert expected != base["fused"][20:500]
    assert ranked["order"] == ranked["fused"]
    assert ranked["fused_code"] == base["fused_code"]
    listing = small_batch.build_list(stored)
    assert listing["signal_reasons"] == base["reasons"]
    assert small_batch.build_list(json.loads(json.dumps(listing["manifest"]))) == listing


def test_v2_citation_ties_and_missing_counts():
    stored = manifest(25)
    for row in stored["pool"]:
        row["cited_by_count"] = None
    stored["pool"][0]["cited_by_count"] = 0
    stored["pool"][1]["cited_by_count"] = 10
    stored["pool"][2]["cited_by_count"] = 10
    stored["ranking_version"] = 2
    ranks = small_batch.replay(stored)["ranks"]["cites"]
    assert ranks["v001"] == ranks["v002"] == (1.5, True)
    assert ranks["v000"] == (3.0, True)
    assert ranks["v003"] == ranks["v024"] == (14.5, False)


@pytest.mark.parametrize("n,sizes", [(0, []), (29, [29]), (40, [40]), (49, [40, 9]), (50, [40, 10]),
                                     (59, [40, 19]), (60, [40, 20]), (81, [40, 40, 1])])
def test_batch_boundaries(n, sizes):
    listing = small_batch.build_list(manifest(n))
    plans = [small_batch.next_batch(listing, i) for i in range(len(sizes))]
    assert [len(plan["work_ids"]) for plan in plans] == sizes
    assert [head for plan in plans for head in plan["order"]] == listing["order"]


def test_legacy_budget_keeps_30_work_boundaries():
    listing = small_batch.build_list(manifest(61))
    plans = [small_batch.next_batch(listing, i, 30) for i in range(3)]
    assert [len(plan["work_ids"]) for plan in plans] == [30, 30, 1]
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
