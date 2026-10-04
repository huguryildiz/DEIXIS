"""Candidate and packing behavior on synthetic snapshots, without a model."""

from dataclasses import replace
import socket
import subprocess

import pytest

from deixis.workflow.lineage.candidates import (
    NOT_SENT_REASONS, Candidate, LineageWork, candidate_priority, eligible_targets,
    find_candidates, pack_candidates, passage_budget_fits,
)
from deixis.workflow.lineage.edges import Edge, EdgeFrom, EdgeTo, derive_edges, unassessed_edges
from deixis.workflow.lineage.mentions import PassageText


def work(svid, position, author="Nobody", year=2020, text="Unrelated text", **changes):
    values = dict(source_version_id=svid, work_id="work-" + svid, position=position,
                  title="Short title", authors=(author,), year=year, years=(), references_read=False,
                  referenced_ids=frozenset(), openalex_ids=frozenset(),
                  passages=(PassageText("p-" + svid, "pdf_page", text, 1),))
    return LineageWork(**dict(values, **changes))


def candidate(i, total=1, passages=None):
    return Candidate("to", f"from-{i:03d}", 100, i, total, ("surname_year",),
                     tuple(passages if passages is not None else (f"p-{i}",)), "not_read", False)


def pairs(result):
    return tuple((c.from_source_version_id, c.to_source_version_id) for c in result.candidates)


def synthetic_corpus():
    # D mentions B and an unrelated Smith (2010), colliding with A's first author.
    # F's numbered reference has no surname/year or title fragment in its passages.
    return (
        work("A", 0, "Smith", 2010, openalex_ids=frozenset({"W1"})),
        work("B", 1, "Brown", 2012, "We extend Smith (2010).", references_read=True,
             referenced_ids=frozenset({"W1"}), openalex_ids=frozenset({"W2"})),
        work("C", 2, "Chen", 2013, "We change the method of Smith et al., 2010.", references_read=True),
        work("D", 3, "Davis", 2014, "Brown (2012) is mentioned; unrelated Smith (2010) discusses another topic."),
        work("E", 4, "Evans", 2015),
        work("F", 5, "Fox", 2016, "We cite [1] only.", references_read=True, referenced_ids=frozenset({"W1"})),
    )


def test_candidates_for_synthetic_corpus():
    corpus = synthetic_corpus()
    result = find_candidates(corpus)
    assert pairs(result) == (("A", "B"), ("A", "C"), ("A", "D"), ("B", "D"))
    assert tuple(c.edge_state for c in result.candidates) == ("present", "absent_in_read_list", "not_read", "not_read")
    assert result.no_candidate_targets == ("A", "E", "F")
    assert result.scanned_targets == ("A", "B", "C", "D", "E", "F")
    assert all(c.total_matches == 1 and c.basis == ("surname_year",) for c in result.candidates)
    assert tuple(c.mention_passage_ids for c in result.candidates) == (("p-B",), ("p-C",), ("p-D",), ("p-D",))
    edges = derive_edges([EdgeTo(w.source_version_id, w.work_id, w.references_read, w.referenced_ids) for w in corpus],
                         [EdgeFrom(w.source_version_id, w.work_id, w.openalex_ids) for w in corpus])
    assert unassessed_edges(edges, frozenset(pairs(result)), frozenset(result.scanned_targets)) == (Edge("F", "A", "present"),)


def test_same_work_two_versions_never_pair():
    a = work("a", 0, "Smith", 2015, "Smith 2015")
    b = work("b", 1, "Smith", 2015, "Smith 2015", work_id=a.work_id)
    assert find_candidates((a, b)).candidates == ()


def test_same_pair_in_two_separate_calls_is_independent():
    corpus = (work("a", 0, "Smith", 2015), work("b", 1, text="Smith 2015"))
    first = find_candidates(corpus)
    assert pairs(first) == (("a", "b"),)
    assert find_candidates(corpus) == first
    assert find_candidates(corpus, excluded_pairs=frozenset({("a", "b")})).candidates == ()
    assert find_candidates(corpus) == first


def test_duplicate_candidate_pairs_are_not_repeated():
    a = work("a", 0, "Smith", 2015)
    b = work("b", 1, text="Smith 2015")
    duplicate = replace(a, authors=("Other",))
    assert pairs(find_candidates((a, duplicate, b, b))) == (("a", "b"),)
    assert find_candidates((a, a, b, b), targets=(b, b)).scanned_targets == ("b",)


def test_human_decided_pair_is_excluded_by_parameter():
    corpus = synthetic_corpus()
    assert pairs(find_candidates(corpus, excluded_pairs=frozenset({("A", "D")}))) == (
        ("A", "B"), ("A", "C"), ("B", "D"))
    assert ("A", "D") in pairs(find_candidates(corpus, excluded_pairs=frozenset({("D", "A")})))


def test_year_order_warning_is_a_warning_not_a_rejection():
    a = work("a", 0, "Smith", 2020)
    b = work("b", 1, year=2010, text="Smith 2020")
    found = find_candidates((a, b)).candidates
    assert len(found) == 1 and found[0].year_order_warning
    assert not find_candidates((a, replace(b, year=None))).candidates[0].year_order_warning
    assert not find_candidates((replace(a, year=None, years=(2020,)), b)).candidates[0].year_order_warning


def test_only_pdf_text_works_are_targets():
    a = work("a", 2, "Smith", 2015, passages=(PassageText("pa", "abstract", "Nobody 2020", None),))
    b = work("b", 1, text="Smith 2015")
    assert eligible_targets((a, b)) == (b,)
    result = find_candidates((a, b))
    assert result.scanned_targets == ("b",)
    assert pairs(result) == (("a", "b"),)
    assert find_candidates((a, b), targets=(a,)).scanned_targets == ()
    assert find_candidates((a, b), targets=()).scanned_targets == ()
    # Eligibility needs a PDF passage, but all supplied passages can provide mentions.
    mixed = replace(b, passages=(PassageText("empty", "pdf_page", "", 1),
                                 PassageText("abstract", "abstract", "Smith 2015", None)))
    assert find_candidates((a, mixed)).candidates[0].mention_passage_ids == ("abstract",)


def test_priority_key_total_matches_then_from_position():
    a = work("z", 0, "Smith", 2015)
    b = work("b", 1, "Brown", 2015)
    c = work("a", 0, "Adams", 2015)
    to = work("to", 3, text="Smith 2015 Brown 2015 Brown 2015 Adams 2015")
    result = find_candidates((to, b, a, c), targets=(to,))
    assert pairs(result) == (("b", "to"), ("a", "to"), ("z", "to"))
    assert tuple(c.total_matches for c in result.candidates) == (2, 1, 1)
    assert pack_candidates(reversed(result.candidates)).chunks == (result.candidates,)


def test_pack_nine_candidates_makes_two_chunks_of_eight_and_one():
    candidates = tuple(candidate(i) for i in range(9))
    packed = pack_candidates(candidates)
    assert packed.chunks == (candidates[:8], candidates[8:])
    assert packed.not_sent == ()


def test_pack_respects_chunk_count_limit_and_records_beyond_call_limit():
    candidates = tuple(candidate(i) for i in range(25))
    packed = pack_candidates(candidates)
    assert packed.chunks == (candidates[:8], candidates[8:16], candidates[16:24])
    assert tuple((n.candidate, n.reason) for n in packed.not_sent) == ((candidates[24], "beyond_call_limit"),)
    assert NOT_SENT_REASONS == ("too_large_for_one_call", "beyond_call_limit")


def test_pack_candidate_too_large_alone_is_recorded_and_does_not_block_others():
    candidates = tuple(candidate(i) for i in range(3))
    fits = passage_budget_fits({"p-0": 48_001, "p-1": 48_000, "p-2": 1})
    packed = pack_candidates(candidates, fits)
    assert packed.chunks == ((candidates[1],), (candidates[2],))
    assert [(n.candidate, n.reason) for n in packed.not_sent] == [(candidates[0], "too_large_for_one_call")]
    # A too-large candidate also closes an existing chunk before it is skipped.
    lengths = {"p-0": 1, "p-1": 48_001, "p-2": 1}
    packed = pack_candidates(candidates, passage_budget_fits(lengths))
    assert packed.chunks == ((candidates[0],), (candidates[2],))
    assert packed.not_sent[0].candidate == candidates[1]


def test_pack_never_drops_a_candidate_and_keeps_order():
    for size in (0, 1, 7, 8, 9, 23, 24, 25, 40):
        candidates = tuple(candidate(i) for i in range(size))
        for fits in (None, passage_budget_fits({f"p-{i}": 48_001 if i % 5 == 0 else 12_000 for i in range(size)})):
            packed = pack_candidates(candidates, fits)
            sent = tuple(c for chunk in packed.chunks for c in chunk)
            unsent = tuple(n.candidate for n in packed.not_sent)
            all_ids = [c.from_source_version_id for c in (*sent, *unsent)]
            assert len(all_ids) == len(set(all_ids)) == size
            assert set(all_ids) == {c.from_source_version_id for c in candidates}
            assert sent == tuple(sorted(sent, key=candidate_priority))
            assert unsent == tuple(sorted(unsent, key=candidate_priority))
            assert all(0 < len(chunk) <= 8 for chunk in packed.chunks)
            assert len(packed.chunks) <= 3


def test_pack_splits_fewer_than_eight_candidates_when_size_exceeds_budget():
    candidates = tuple(candidate(i) for i in range(5))
    packed = pack_candidates(candidates, passage_budget_fits({f"p-{i}": 12_000 for i in range(5)}))
    assert packed.chunks == (candidates[:4], candidates[4:])
    assert packed.not_sent == ()
    # Default packing ignores text length unless the proxy is supplied explicitly.
    assert pack_candidates(candidates).chunks == (candidates,)


def test_pack_never_makes_empty_chunks_or_spends_call_quota_on_them():
    candidates = tuple(candidate(i) for i in range(7))
    packed = pack_candidates(candidates, passage_budget_fits({f"p-{i}": 48_001 if i < 6 else 1 for i in range(7)}),
                             max_chunks=1)
    assert packed.chunks == ((candidates[-1],),)
    assert len(packed.not_sent) == 6
    assert all(n.reason == "too_large_for_one_call" for n in packed.not_sent)
    packed = pack_candidates(candidates, lambda chunk: False)
    assert packed.chunks == () and len(packed.not_sent) == 7
    # With the last call closed, later candidates receive the call-limit reason.
    packed = pack_candidates(candidates[:3], lambda chunk: len(chunk) <= 1, max_chunks=1)
    assert packed.chunks == ((candidates[0],),)
    assert all(n.reason == "beyond_call_limit" for n in packed.not_sent)


def test_passage_budget_counts_unique_passages():
    lengths = {f"p-{i}": 1 for i in range(25)}
    shared = (candidate(0, passages=("p-0",)), candidate(1, passages=("p-0",)))
    assert passage_budget_fits({"p-0": 48_000})(shared)
    assert not passage_budget_fits({"p-0": 48_001})(shared)
    fits = passage_budget_fits(lengths)
    assert fits(tuple(candidate(i) for i in range(24)))
    assert not fits(tuple(candidate(i) for i in range(25)))
    with pytest.raises(KeyError):
        passage_budget_fits({})(shared)
    snapshot = {"p-0": 48_000}
    fit_snapshot = passage_budget_fits(snapshot)
    snapshot["p-0"] = 48_001
    assert fit_snapshot(shared)


def test_no_model_or_provider_call_is_possible(monkeypatch):
    from deixis.workflow.lineage.baseline import BaselineVersion, field_baseline

    def forbidden(*args, **kwargs):
        raise AssertionError("pure functions must not start network or process operations")

    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, forbidden)
    for name in ("Popen", "run", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, forbidden)
    corpus = synthetic_corpus()
    result = find_candidates(corpus)
    assert len(result.candidates) == 4
    for to in result.scanned_targets:
        assert pack_candidates(tuple(c for c in result.candidates if c.to_source_version_id == to),
                               passage_budget_fits({p.passage_id: len(p.text) for w in corpus for p in w.passages}))
    versions = tuple(BaselineVersion(w.source_version_id, w.work_id, True, False, "2026", 1, None, "review",
                                     w.references_read, w.referenced_ids, w.openalex_ids) for w in corpus)
    assert field_baseline(versions).most_cited_in_corpus.total == 6


def test_packing_rejects_mixed_targets_and_invalid_limits():
    with pytest.raises(ValueError, match="one target"):
        pack_candidates((candidate(0), replace(candidate(1), to_source_version_id="another")))
    for limits in ({"max_per_chunk": 0}, {"max_chunks": 0}, {"max_chunks": -1}):
        with pytest.raises(ValueError, match="positive"):
            pack_candidates((), **limits)
    with pytest.raises(ValueError, match="nonnegative"):
        passage_budget_fits({"p": -1})


def test_no_twenty_five_target_limit_is_applied_here():
    result = find_candidates(tuple(work(str(i), i) for i in range(26)))
    assert len(result.scanned_targets) == 26
