"""Ranking signals (bm25, blocks, tfidf, graph, joint), their RRF fusion and the frozen list's replay.

Pure functions over SYNTHETIC pools. Passing shows the order rules; a rank is a priority signal, not a relevance verdict.
"""

import random
import pytest
from deixis.domain.canonical import sha256_hex
from deixis.workflow import ranking
import json
from deixis.domain import canonical
from deixis.workflow import small_batch, ranking


# ---- from tests__discovery__test_record_ranking.py ------------------------------------------------------------

BLOCKS = {"setting": ["diffusion channel", "molecular"], "task": ["release scheduling", "repeater"]}


# Four works of two fields plus one record that shares neither vocabulary. `own_ids` and `references` are OpenAlex
# short identifiers; W9x identifiers belong to works outside the pool.
POOL = [
    {"id": "srv_a", "work_id": "wrk_a", "title": "SYNTHETIC release scheduling for a diffusion channel",
     "abstract": "We schedule molecular releases in a diffusion channel and bound the error rate.",
     "own_ids": frozenset({"W1"}), "references": frozenset({"W91", "W92", "W93"})},
    {"id": "srv_b", "work_id": "wrk_b", "title": "SYNTHETIC molecular release schedules",
     "abstract": "Release scheduling of molecular signals is compared against a fixed interval.",
     "own_ids": frozenset({"W2"}), "references": frozenset({"W91", "W92"})},
    {"id": "srv_c", "work_id": "wrk_c", "title": "SYNTHETIC repeater chains for optical links",
     "abstract": "We place repeaters along an optical link and measure the loss.",
     "own_ids": frozenset({"W3"}), "references": frozenset({"W94"})},
    {"id": "srv_d", "work_id": "wrk_d", "title": "SYNTHETIC bakery logistics in a small town",
     "abstract": None, "own_ids": frozenset({"W4"}), "references": frozenset()},
    {"id": "srv_e", "work_id": "wrk_e", "title": "SYNTHETIC diffusion channel capacity",
     "abstract": "The capacity of a diffusion channel is derived.", "own_ids": frozenset({"W5"}),
     "references": None},
]


QUERY_WORDS = {"diffusion", "channel", "molecular", "release", "scheduling", "repeater"}


def order_of(scores, available=None):
    ranked = ranking.mean_ranks(scores, available or {})
    return sorted(ranked, key=lambda rid: (ranked[rid][0], rid))


def test_bm25_scores_the_record_whose_text_holds_most_of_the_query_words_first():
    scores = ranking.bm25_scores(POOL, QUERY_WORDS)
    assert set(scores) == {row["id"] for row in POOL}
    assert order_of(scores)[0] in ("srv_a", "srv_b")
    assert order_of(scores)[-1] == "srv_d"  # the bakery holds none of the words


def test_graph_counts_shared_references_and_a_citation_in_either_direction():
    cited_by_seed = {"id": "srv_x", "work_id": "wrk_x", "title": "SYNTHETIC cited work", "abstract": None,
                     "own_ids": frozenset({"W91"}), "references": frozenset({"W2"})}
    pool = POOL + [cited_by_seed]
    scores = ranking.graph_scores(pool, [POOL[1]])  # the seed lists W91 and W92 and is work W2
    assert scores["srv_a"] > 0  # two shared references
    assert scores["srv_c"] == 0.0
    # One direction each: the seed's reference list names this record's work, and the record's list names the seed's.
    assert scores["srv_x"] == 2.0
    assert scores["srv_b"] == 0.0  # the seed is this record's own work


def test_fusion_adds_reciprocal_ranks_and_breaks_a_tie_by_identifier():
    ranks = {"bm25": {"a": (1.0, True), "b": (2.0, True)}, "blocks": {"a": (2.0, True), "b": (1.0, True)}}
    assert ranking.fuse(ranks, ("bm25", "blocks")) == ["a", "b"]  # equal sums; the identifier decides


def test_a_missing_signal_enters_the_sum_at_its_last_place_rather_than_being_left_out():
    """`missing_signal.py`: dropping the term made the measured order worse, so it is kept (SW7.4)."""
    ranks = {"bm25": {"a": (1.0, True), "b": (2.0, True), "c": (3.0, True)},
             "graph": {"a": (3.0, False), "b": (1.0, True), "c": (2.0, True)}}
    # a leads on BM25 but has no graph signal, so its last place there is really added and b passes it.
    assert ranking.fuse(ranks, ("bm25", "graph")) == ["b", "a", "c"]
    assert ranking.fuse({"bm25": ranks["bm25"]}, ("bm25",)) == ["a", "b", "c"]


@pytest.mark.parametrize("seed", [1])
def test_every_output_is_the_same_whatever_order_the_pool_rows_arrive_in(seed):
    shuffled = list(POOL)
    random.Random(seed).shuffle(shuffled)
    seeds = [POOL[1], POOL[2]]

    def digest(pool):
        ranks = {name: ranking.mean_ranks(scores, ranking.availability(pool, name)) for name, scores in (
            ("bm25", ranking.bm25_scores(pool, QUERY_WORDS)), ("blocks", ranking.block_scores(pool, BLOCKS)),
            ("tfidf", ranking.tfidf_scores(pool, seeds)), ("graph", ranking.graph_scores(pool, seeds)))}
        fused = ranking.fuse(ranks, ranking.CODE_SIGNALS)
        return sha256_hex({"ranks": {name: {rid: list(value) for rid, value in row.items()}
                                     for name, row in ranks.items()}, "fused": fused})

    assert digest(shuffled) == digest(POOL)


# ---- from tests__discovery__test_small_batch_ranking.py ------------------------------------------------------------

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


def v3_manifest(n=120):
    stored = manifest(n)
    for i, row in enumerate(stored["pool"]):
        row["cited_by_count"] = i % 7 or None
    return stored


@pytest.mark.parametrize("n", [65])
def test_v3_keeps_the_v1_top20_and_orders_a_permutation(n):
    stored = v3_manifest(n)
    v1 = small_batch.replay(stored)
    stored["ranking_version"] = 3
    ranked = small_batch.replay(stored)
    assert ranked["fused"][:20] == v1["fused"][:20]
    assert sorted(ranked["fused"]) == sorted(v1["fused"])
    assert ranked["order"] == ranked["fused"]
    assert sorted(ranked["fused_code"]) == sorted(v1["fused_code"])
    listing = small_batch.build_list(stored)
    assert small_batch.build_list(json.loads(json.dumps(listing["manifest"]))) == listing


@pytest.mark.parametrize("n,sizes", [pytest.param(49, [40, 9], id="49-sizes3")])
def test_batch_boundaries(n, sizes):
    listing = small_batch.build_list(manifest(n))
    plans = [small_batch.next_batch(listing, i) for i in range(len(sizes))]
    assert [len(plan["work_ids"]) for plan in plans] == sizes
    assert [head for plan in plans for head in plan["order"]] == listing["order"]


def test_user_priority_does_not_reorder_automatic_section():
    listing = small_batch.build_list(manifest(priority=["v020", "v001"]))
    assert listing["order"][:2] == ["v020", "v001"]
    assert listing["order"][2:] == [head for head in listing["automatic_order"] if head not in ("v020", "v001")]
