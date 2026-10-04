"""The four code signals, their rank fusion and the embedding rescue arm, as pure functions (SW7, SW8, slice 07).

Records are SYNTHETIC and from two fields, and no signal is measured here: what these tests show is the behavior of
the rules — which record a signal can score at all, how a tie is shared, where a missing signal goes, and that no
result depends on the order the rows arrived in. They say nothing about whether the order finds relevant papers.
"""

import random

import pytest

from deixis.domain.canonical import sha256_hex
from deixis.workflow import ranking
from deixis.workflow.ranking import RESCUE_EMBEDDING_TOP

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


def ranks_of(scores, available=None):
    return {rid: rank for rid, (rank, _) in ranking.mean_ranks(scores, available or {}).items()}


def order_of(scores, available=None):
    ranked = ranking.mean_ranks(scores, available or {})
    return sorted(ranked, key=lambda rid: (ranked[rid][0], rid))


# ---- the signals -----------------------------------------------------------------------------

def test_bm25_scores_the_record_whose_text_holds_most_of_the_query_words_first():
    scores = ranking.bm25_scores(POOL, QUERY_WORDS)
    assert set(scores) == {row["id"] for row in POOL}
    assert order_of(scores)[0] in ("srv_a", "srv_b")
    assert order_of(scores)[-1] == "srv_d"  # the bakery holds none of the words


def test_a_record_without_an_abstract_is_still_scored_by_bm25_with_its_title():
    """Named deviation 4: SW7.4's "no abstract" is a missing TF-IDF signal, not a missing BM25 one."""
    titles_only = [row | {"abstract": None} for row in POOL]
    scores = ranking.bm25_scores(titles_only, QUERY_WORDS)
    assert scores["srv_e"] > 0 and scores["srv_d"] == 0


def test_the_block_score_counts_blocks_in_the_title_then_distinct_forms_in_title_and_abstract():
    scores = ranking.block_scores(POOL, BLOCKS)
    assert scores["srv_a"] == (2, 3)  # both blocks in the title; "diffusion channel", "release scheduling", "molecular"
    assert scores["srv_c"] == (1, 1)  # only the task block, by "repeater"
    assert scores["srv_d"] == (0, 0)
    # A title hit always outranks a record that only repeats forms in its abstract, whatever the counts.
    assert scores["srv_a"] > scores["srv_b"] > scores["srv_d"]


def test_a_block_form_matches_at_a_word_start_and_not_inside_a_word():
    """Named deviation 3: "repeater" catches "repeaters"; it must not catch a word that merely contains it."""
    pool = [{"id": "plural", "work_id": "w1", "title": "SYNTHETIC repeaters on a chain", "abstract": None,
             "own_ids": frozenset(), "references": None},
            {"id": "inside", "work_id": "w2", "title": "SYNTHETIC norepeater budget", "abstract": None,
             "own_ids": frozenset(), "references": None}]
    scores = ranking.block_scores(pool, {"task": ["repeater"]})
    assert scores["plural"] == (1, 1) and scores["inside"] == (0, 0)


def test_tfidf_never_counts_a_seed_of_the_record_s_own_work():
    seeds = [POOL[0]]  # the only seed is srv_a's own work
    scores = ranking.tfidf_scores(POOL, seeds)
    assert scores["srv_a"] == 0.0
    assert scores["srv_b"] > 0.0


def test_tfidf_has_no_score_for_a_record_that_only_has_a_title():
    """The record is still ranked, but the signal is recorded as missing and goes to the tail (SW7.4)."""
    scores = ranking.tfidf_scores(POOL, [POOL[1]])
    available = ranking.availability(POOL, "tfidf")
    assert available["srv_d"] is False and available["srv_a"] is True
    assert ranks_of(scores, available)["srv_d"] == len(POOL)  # one record without an abstract: the last place alone


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


def test_a_record_with_an_empty_or_unread_reference_list_has_no_graph_signal():
    available = ranking.availability(POOL, "graph")
    assert available["srv_d"] is False and available["srv_e"] is False and available["srv_a"] is True


# ---- ranks and fusion ------------------------------------------------------------------------

def test_equal_scores_share_the_mean_rank():
    ranked = ranks_of({"a": 5.0, "b": 5.0, "c": 1.0, "d": 5.0})
    assert ranked == {"a": 2.0, "b": 2.0, "d": 2.0, "c": 4.0}


def test_a_missing_signal_is_last_however_high_its_score():
    ranked = ranks_of({"a": 99.0, "b": 2.0, "c": 1.0}, {"a": False, "b": True, "c": True})
    assert ranked == {"b": 1.0, "c": 2.0, "a": 3.0}


def test_two_missing_signals_share_the_tail_s_mean_rank():
    ranked = ranks_of({"a": 9.0, "b": 2.0, "c": 1.0, "d": 0.0},
                      {"a": False, "b": True, "c": True, "d": False})
    assert ranked == {"b": 1.0, "c": 2.0, "a": 3.5, "d": 3.5}


def test_fusion_adds_reciprocal_ranks_and_breaks_a_tie_by_identifier():
    ranks = {"bm25": {"a": (1.0, True), "b": (2.0, True)}, "blocks": {"a": (2.0, True), "b": (1.0, True)}}
    assert ranking.fuse(ranks, ("bm25", "blocks")) == ["a", "b"]  # equal sums; the identifier decides


def test_a_record_last_in_one_signal_does_not_sink_in_the_fusion():
    """SW7's g016 case, with SYNTHETIC ranks: one collapsed signal must not decide the fused place."""
    ids = [f"r{i:03d}" for i in range(50)]
    strong = {rid: (float(position + 1), True) for position, rid in enumerate(ids)}
    collapsed = {rid: (float(len(ids) - position), True) for position, rid in enumerate(ids)}
    # r000 is first in three signals and last in the fourth.
    ranks = {"bm25": strong, "blocks": strong, "tfidf": strong, "graph": collapsed}
    assert ranking.fuse(ranks, ranking.CODE_SIGNALS)[0] == "r000"


def test_a_missing_signal_enters_the_sum_at_its_last_place_rather_than_being_left_out():
    """`missing_signal.py`: dropping the term made the measured order worse, so it is kept (SW7.4)."""
    ranks = {"bm25": {"a": (1.0, True), "b": (2.0, True), "c": (3.0, True)},
             "graph": {"a": (3.0, False), "b": (1.0, True), "c": (2.0, True)}}
    # a leads on BM25 but has no graph signal, so its last place there is really added and b passes it.
    assert ranking.fuse(ranks, ("bm25", "graph")) == ["b", "a", "c"]
    assert ranking.fuse({"bm25": ranks["bm25"]}, ("bm25",)) == ["a", "b", "c"]


# ---- the rescue arm --------------------------------------------------------------------------

def rescue(code_position, embedding_rank):
    """One record at a named place in the code order and in the embedding, inside a pool of 400."""
    ids = [f"r{i:03d}" for i in range(400)]
    target = ids[code_position - 1]
    # Every other record sits far down the embedding, so only the named one can meet the second condition.
    embedding = {rid: (float(position + RESCUE_EMBEDDING_TOP + 1), True) for position, rid in enumerate(ids)}
    embedding[target] = (float(embedding_rank), True)
    return ranking.inspection_order(list(ids), list(ids), embedding), target


def test_a_record_is_rescued_only_when_it_is_outside_the_code_top_and_inside_the_embedding_top():
    (order, rescued), target = rescue(201, 50)
    assert rescued == [target] and order[0] == target


def test_a_record_inside_the_code_top_is_not_rescued_however_high_the_embedding_puts_it():
    (order, rescued), target = rescue(200, 1)
    assert rescued == [] and order[0] != target


def test_a_record_below_the_embedding_top_is_not_rescued_however_low_the_code_order_puts_it():
    (order, rescued), target = rescue(399, 51)
    assert rescued == []


def test_without_an_embedding_the_fused_order_stands_and_nobody_is_rescued():
    fused = ["a", "b", "c"]
    assert ranking.inspection_order(fused, fused, None) == (["a", "b", "c"], [])


def test_a_record_without_a_stored_similarity_is_not_rescued_by_the_tail_rank_it_shares():
    """The embedding has no authority (SW8.2): a record the embedding never scored cannot enter through it."""
    ids = [f"r{i:03d}" for i in range(300)]
    embedding = {rid: (299.5, False) for rid in ids}
    embedding[ids[0]] = (1.0, True)
    order, rescued = ranking.inspection_order(list(ids), list(ids), embedding)
    assert rescued == [] and order == ids


def test_several_rescued_records_come_in_embedding_order():
    ids = [f"r{i:03d}" for i in range(300)]
    embedding = {rid: (float(position + 1), True) for position, rid in enumerate(ids)}
    embedding["r250"], embedding["r260"] = (3.0, True), (2.0, True)
    order, rescued = ranking.inspection_order(list(ids), list(ids), embedding)
    assert rescued == ["r260", "r250"] and order[:2] == ["r260", "r250"]
    assert order[2:] == [rid for rid in ids if rid not in ("r250", "r260")]


# ---- nothing depends on the order the rows arrived in ------------------------------------------

@pytest.mark.parametrize("seed", [1, 2, 3])
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


def test_an_outcome_term_the_question_did_not_hold_is_among_the_words_bm25_reads():
    """The approval card tells the user an outcome term orders the records; one added there must really do so."""
    vocabulary = {"terms": [], "outcome_terms": ["SYNTHETIC seedling survival"]}
    query_words, _ = ranking.query_vocabulary({"question": "Which canopy is reported?"}, vocabulary, [])
    assert {"seedling", "survival"} <= query_words
