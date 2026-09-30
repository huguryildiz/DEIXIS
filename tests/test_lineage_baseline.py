"""Stored-value and denominator boundaries over synthetic included versions."""

from dataclasses import fields, replace
from pathlib import Path
import random

from deixis.workflow.lineage import baseline
from deixis.workflow.lineage.baseline import (
    REVIEW_NOTE, SHOWN, BaselineEntry, BaselineVersion, IncludedCitations, field_baseline,
)


def version(wid, svid=None, **changes):
    values = dict(source_version_id=svid or wid + "-v", work_id=wid, is_head=True,
                  has_active_asset=False, created_at="2026-01-01", cited_by_count=10,
                  cited_by_count_at="2026-09-30", publication_type="article", references_read=False,
                  referenced_ids=frozenset(), openalex_ids=frozenset({"W" + wid}))
    return BaselineVersion(**dict(values, **changes))


def entry_for(result, wid):
    return next(e for e in result.most_cited_in_corpus.entries if e.work_id == wid)


def citations(versions, wid="1"):
    return entry_for(field_baseline(versions), wid).cited_by_included


def test_most_cited_from_stored_counts_with_work_id_ties():
    result = field_baseline((version("b", cited_by_count=20), version("a", cited_by_count=20),
                             version("c", cited_by_count=100)))
    assert tuple((e.work_id, e.cited_by_count) for e in result.most_cited_in_corpus.entries) == (
        ("c", 100), ("a", 20), ("b", 20))
    assert all(e.cited_by_count_at == "2026-09-30" for e in result.most_cited_in_corpus.entries)


def test_unknown_count_is_not_zero_and_is_counted_separately():
    result = field_baseline((version("a", cited_by_count=None), version("b", cited_by_count=0)))
    assert result.unknown_count_works == 1
    assert tuple(e.work_id for e in result.most_cited_in_corpus.entries) == ("b",)
    unknown_review = field_baseline((version("a", cited_by_count=None, publication_type="review"),))
    assert unknown_review.review_in_corpus.entries[0].cited_by_count is None


def test_review_list_uses_registered_type_and_note():
    result = field_baseline((version("b", publication_type="ReViEw"), version("a", publication_type="review"),
                             version("c", publication_type="review-article"), version("d", publication_type=None)))
    assert tuple(e.work_id for e in result.review_in_corpus.entries) == ("a", "b")
    assert result.review_in_corpus.entries[1].publication_type == "ReViEw"
    assert REVIEW_NOTE == "Registered type: review. Which provider wrote the type is not stored."


def test_representative_follows_d48_order_and_fills_no_gap():
    head = version("a", "head", cited_by_count=None, cited_by_count_at=None, publication_type=None,
                   created_at="2026-03-01")
    other = version("a", "asset", is_head=False, has_active_asset=True, publication_type="review",
                    created_at="2026-01-01", cited_by_count=100)
    result = field_baseline((other, head))
    assert result.representatives[0].source_version_id == "head"
    assert result.unknown_count_works == 1
    assert result.most_cited_in_corpus.entries == () and result.review_in_corpus.entries == ()
    assert field_baseline((replace(head, is_head=False), other)).representatives[0].source_version_id == "asset"
    tied_asset = replace(other, source_version_id="asset-z", created_at="2026-02-01")
    assert field_baseline((tied_asset, other)).representatives[0].source_version_id == "asset"
    tied_id = replace(other, source_version_id="asset-a")
    assert field_baseline((other, tied_id)).representatives[0].source_version_id == "asset"
    # A known head count with missing date/type also cannot borrow those fields.
    head_known = replace(head, cited_by_count=1)
    selected = entry_for(field_baseline((other, head_known)), "a")
    assert (selected.cited_by_count, selected.cited_by_count_at, selected.publication_type) == (1, None, None)


def test_representative_reason_and_versions_considered():
    versions = (version("b", "b-other", is_head=False), version("a", "a-other", is_head=False, has_active_asset=True),
                version("a", "a-head"))
    result = field_baseline(versions)
    assert tuple((r.work_id, r.source_version_id, r.reason, r.versions_considered) for r in result.representatives) == (
        ("a", "a-head", "head", ("a-head", "a-other")), ("b", "b-other", "other_version", ("b-other",)))


def test_first_five_shown_and_total_reported():
    result = field_baseline(tuple(version(str(i), publication_type="review") for i in range(7)))
    assert SHOWN == 5
    for listing in (result.most_cited_in_corpus, result.review_in_corpus):
        assert listing.total == 7 and len(listing.shown) == 5
        assert listing.shown == listing.entries[:5]
    empty = field_baseline(())
    assert empty.representatives == () and empty.unknown_count_works == 0
    assert empty.most_cited_in_corpus.total == empty.review_in_corpus.total == 0


def test_cited_by_included_counts_distinct_works_not_versions():
    versions = (version("1"), version("2", references_read=True, referenced_ids=frozenset({"W1"})),
                version("2", "2-other", is_head=False, references_read=True, referenced_ids=frozenset({"W1"})),
                version("3", references_read=True, referenced_ids=frozenset({"W1"})))
    result = field_baseline(versions)
    assert entry_for(result, "1").cited_by_included == IncludedCitations(2, 2, 2, True)
    reviews = field_baseline((replace(versions[0], publication_type="review"), *versions[1:]))
    assert reviews.review_in_corpus.entries[0].cited_by_included == IncludedCitations(2, 2, 2, True)


def test_cited_by_included_excludes_target_from_denominator():
    versions = (version("1", references_read=True, referenced_ids=frozenset({"W1"})),
                version("1", "1-other", is_head=False, references_read=True, referenced_ids=frozenset({"W1"})),
                version("2", references_read=True))
    assert citations(versions) == IncludedCitations(0, 1, 1, True)
    assert citations(versions[:2]) == IncludedCitations(None, 0, 0, True)


def test_unread_or_unresolved_is_never_zero():
    assert citations((version("1"), version("2"))) == IncludedCitations(None, 1, 0, True)
    assert citations((version("1", openalex_ids=frozenset()), version("2", references_read=True))) == (
        IncludedCitations(None, 1, 1, False))
    assert citations((version("1", openalex_ids=frozenset()), version("2"))) == IncludedCitations(None, 1, 0, False)


def test_partially_read_corpus_reports_zero_with_its_denominators():
    assert citations((version("1"), version("2", references_read=True), version("3"))) == IncludedCitations(0, 2, 1, True)


def test_references_of_an_unread_version_are_not_counted_and_a_read_non_representative_version_counts_once_per_work():
    target = version("1")
    unread = version("2", referenced_ids=frozenset({"W1"}))
    read = version("2", "2-other", is_head=False, references_read=True, referenced_ids=frozenset({"W1"}))
    assert citations((target, unread)) == IncludedCitations(None, 1, 0, True)
    assert citations((target, unread, version("3", references_read=True))) == IncludedCitations(0, 2, 1, True)
    assert citations((target, unread, read)) == IncludedCitations(1, 1, 1, True)
    assert entry_for(field_baseline((target, unread, read)), "2").source_version_id == unread.source_version_id


def test_target_identity_is_union_of_its_versions_ids():
    versions = (version("1", openalex_ids=frozenset()),
                version("1", "1-other", is_head=False, openalex_ids=frozenset({"https://openalex.org/w9"})),
                version("2", references_read=True, referenced_ids=frozenset({" W9 "})))
    assert citations(versions) == IncludedCitations(1, 1, 1, True)
    assert entry_for(field_baseline(versions), "1").source_version_id == "1-v"


def test_no_forbidden_word_anywhere():
    package_sources = tuple(Path(baseline.__file__).parent.glob("*.py"))
    for path in package_sources:
        source = path.read_text().casefold()
        for forbidden in ("foundational", "kurucu"):
            assert forbidden not in source, path
    result = field_baseline((version("1", publication_type="review"),
                             version("2", references_read=True, referenced_ids=frozenset({"W1"}))))
    for forbidden in ("foundational", "kurucu"):
        assert forbidden not in repr(result).casefold()


def test_baseline_uses_no_quality_score():
    assert {f.name for f in fields(BaselineEntry)} == {
        "work_id", "source_version_id", "cited_by_count", "cited_by_count_at", "publication_type", "cited_by_included"}
    entry = entry_for(field_baseline((version("1"),)), "1")
    assert not hasattr(entry, "score")


def test_baseline_is_deterministic_under_shuffled_input():
    versions = [version("1", "head", cited_by_count=None, publication_type="review"),
                version("1", "other", is_head=False, cited_by_count=100),
                version("2", "z", is_head=False, has_active_asset=True, references_read=True,
                        referenced_ids=frozenset({"w1"})),
                version("2", "a", is_head=False, has_active_asset=True), version("3", cited_by_count=0)]
    expected = field_baseline(versions)
    for seed in range(10):
        shuffled = list(versions)
        random.Random(seed).shuffle(shuffled)
        assert field_baseline(shuffled) == expected
