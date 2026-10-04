"""The pure identity rule: record kind, author agreement and the verdict a pair of records gets (SW6).

All records here are SYNTHETIC. Passing these tests shows that the rule table of slice 03 is implemented as written;
it says nothing about how well the thresholds separate real versions from sibling papers, which was measured on one
topic only (`.local/quantum-dedup-2026-09-18/`) and is not measured inside the product.
"""

import pytest

from deixis.domain.record_identity import (ABSTRACT_MERGE, AUTHOR_OVERLAP, MAX_YEAR_GAP, MIN_TITLE_CHARS,
                                           TITLE_MERGE, TITLE_RELATED, THRESHOLDS, author_agreement, classify_pair,
                                           comparable_title, normalize_text, notice_type, record_kind, similarity,
                                           surnames, trigrams)
from deixis.workflow.store import is_preprint

TITLE = "SYNTHETIC release scheduling for diffusion channels"
ABSTRACT = ("We study SYNTHETIC release scheduling in a diffusion channel and report the packet size that minimises "
            "the error rate under a fixed energy budget.")
OTHER_ABSTRACT = ("A SYNTHETIC survey of receiver architectures for molecular communication, with no scheduling and "
                  "no packet size analysis whatsoever in its pages.")


def rec(title=TITLE, doi="10.1109/synth.2026.1", authors=("Aydin, Mert", "Zhao, Li"), year=2026, abstract=None,
        version_label="publishedVersion", publication_type=None):
    return {"doi": doi, "title": title, "authors": list(authors), "year": year, "abstract": abstract,
            "version_label": version_label, "publication_type": publication_type}


def preprint(doi="10.48550/arxiv.2601.00001", **fields):
    return rec(doi=doi, version_label="submittedVersion", **fields)


# ---- normalisation ---------------------------------------------------------------------


def test_html_and_math_remnants_normalise_away_to_the_clean_title():
    dirty = "SYNTHETIC release <i>scheduling</i> for $\\mathcal{D}$ diffusion channels"
    clean = "SYNTHETIC release scheduling for diffusion channels"
    assert similarity(dirty, clean) == 1.0


def test_accents_normalise_to_their_plain_letters():
    assert normalize_text("Schrödinger's Gedächtnis") == normalize_text("Schrodinger s Gedachtnis")


def test_a_title_in_a_non_latin_script_does_not_normalise_to_nothing():
    assert normalize_text("量子記憶の研究") != ""
    assert similarity("量子記憶の研究", "量子記憶の研究") == 1.0


def test_similarity_is_none_when_either_side_normalises_to_nothing():
    assert similarity("***", TITLE) is None
    assert similarity(TITLE, None) is None
    assert similarity(None, None) is None


def test_trigrams_of_a_text_shorter_than_three_characters_is_empty():
    assert trigrams("ab") == frozenset()
    assert trigrams("abcd") == frozenset({"abc", "bcd"})


# ---- authors ---------------------------------------------------------------------------


def test_last_comma_first_and_first_last_give_the_same_surname():
    assert surnames(["Aydin, Mert"]) == surnames(["Mert Aydin"]) == ["aydin"]


def test_an_accented_surname_matches_its_unaccented_spelling():
    assert author_agreement(["Gökçe Şahin"], ["Gokce Sahin"]) == "agree"


def test_names_written_the_other_way_round_still_agree():
    straight = ["Mert Aydin", "Li Zhao"]
    reversed_order = ["Aydin Mert", "Zhao Li"]  # no comma, family name first
    assert author_agreement(straight, reversed_order) == "agree"


def test_a_placeholder_author_list_is_unknown_not_different():
    assert surnames(["Anonymous"]) == []
    assert author_agreement(["Anonymous"], ["Mert Aydin"]) == "unknown"
    assert author_agreement([], ["Mert Aydin"]) == "unknown"


def test_author_agreement_needs_half_of_the_shorter_list():
    assert AUTHOR_OVERLAP == 0.5
    assert author_agreement(["Mert Aydin", "Li Zhao"], ["Mert Aydin", "Ada Kaya", "Bo Sun", "Eda Tan"]) == "agree"
    assert author_agreement(["Mert Aydin", "Li Zhao"], ["Ada Kaya", "Bo Sun"]) == "differ"


def test_author_agreement_is_symmetric():
    a, b = ["Mert Aydin", "Li Zhao"], ["Ada Kaya", "Bo Sun"]
    assert author_agreement(a, b) == author_agreement(b, a) == "differ"


# ---- record kind -----------------------------------------------------------------------


@pytest.mark.parametrize("title, kind", [
    ("Publisher Correction: SYNTHETIC release scheduling", "notice"),
    ("Erratum: SYNTHETIC release scheduling", "notice"),
    ("Corrigendum to: SYNTHETIC release scheduling", "notice"),
    ("WITHDRAWN: SYNTHETIC release scheduling", "notice"),
    ("Retraction: SYNTHETIC release scheduling", "notice"),
])
def test_a_notice_title_prefix_names_a_notice(title, kind):
    assert record_kind(rec(title=title)) == kind


def test_a_prefix_word_used_as_ordinary_prose_is_not_a_notice():
    assert notice_type("Correction of errors in SYNTHETIC quantum memories") is None
    assert record_kind(rec(title="Correction of errors in SYNTHETIC quantum memories")) == "published"


def test_notice_type_names_which_notice_it_is():
    assert notice_type("Publisher Correction: SYNTHETIC study") == "correction"
    assert notice_type("Corrigendum to: SYNTHETIC study") == "correction"
    assert notice_type("WITHDRAWN: SYNTHETIC study") == "withdrawal"
    assert notice_type("Retracted: SYNTHETIC study") == "retraction"
    assert notice_type("SYNTHETIC study") is None


def test_a_repository_doi_or_a_data_title_names_an_artifact():
    assert record_kind(rec(doi="10.5281/zenodo.123")) == "artifact"
    assert record_kind(rec(title="Data supporting SYNTHETIC release scheduling")) == "artifact"


def test_a_preprint_doi_prefix_or_a_submitted_version_names_a_preprint():
    assert record_kind(rec(doi="10.1101/2026.01.01.123456")) == "preprint"
    assert record_kind(preprint()) == "preprint"
    assert record_kind(rec(doi=None, version_label="arXiv:2601.00001v2")) == "preprint"


def test_a_record_without_a_doi_and_without_a_preprint_label_is_unknown():
    assert record_kind(rec(doi=None)) == "unknown"


@pytest.mark.parametrize("record", [
    rec(), preprint(), rec(doi=None), rec(doi="10.48550/arxiv.2601.00002"),
    rec(doi="10.1109/synth.2026.9", version_label="submittedVersion"),
    rec(doi=None, version_label="arXiv:2601.00003v1"), rec(doi=None, version_label=None),
])
def test_the_preprint_condition_answers_exactly_as_the_store_rule_does(record):
    """`record_kind` may not import `is_preprint` (it would be a cycle), so the two copies are pinned to each other."""
    source = {"doi": record["doi"], "version_label": record["version_label"]}
    if is_preprint(source):
        assert record_kind(record) == "preprint"
    else:
        assert record_kind(record) != "preprint"


def test_comparable_title_drops_the_prefix_that_names_a_notice_or_an_artifact():
    assert comparable_title(rec(title=f"Publisher Correction: {TITLE}")) == normalize_text(TITLE)
    assert comparable_title(rec(title=f"Correction to: {TITLE}")) == normalize_text(TITLE)
    assert comparable_title(rec(title=f"Data supporting {TITLE}")) == normalize_text(TITLE)
    assert comparable_title(rec(title=TITLE)) == normalize_text(TITLE)


# ---- the rule table --------------------------------------------------------------------


def test_thresholds_are_the_measured_values():
    assert THRESHOLDS == {"title_merge": 0.85, "abstract_merge": 0.8, "title_related": 0.6,
                          "author_overlap": 0.5, "max_year_gap": 5}
    assert (TITLE_MERGE, ABSTRACT_MERGE, TITLE_RELATED, MAX_YEAR_GAP, MIN_TITLE_CHARS) == (0.85, 0.8, 0.6, 5, 12)


def test_two_notices_or_two_artifacts_give_no_verdict():
    notice = rec(title=f"Publisher Correction: {TITLE}")
    assert classify_pair(notice, rec(title=f"Erratum: {TITLE}", doi="10.1109/synth.2026.2")) is None
    assert classify_pair(rec(doi="10.5281/zenodo.1"), rec(doi="10.6084/m9.figshare.2")) is None


def test_a_notice_attaches_to_the_paper_it_names():
    notice = rec(title=f"Publisher Correction: {TITLE}", doi="10.1109/synth.2026.2")
    paper = rec()
    verdict = classify_pair(notice, paper)
    assert (verdict.link_kind, verdict.rule, verdict.merge, verdict.parent) == ("notice_of", "correction", False, "b")
    assert classify_pair(paper, notice).parent == "a"


@pytest.mark.parametrize("title, rule", [("WITHDRAWN: " + TITLE, "withdrawal"), ("Retraction: " + TITLE, "retraction")])
def test_a_withdrawal_and_a_retraction_carry_their_own_rule(title, rule):
    verdict = classify_pair(rec(title=title, doi="10.1109/synth.2026.2"), rec())
    assert (verdict.link_kind, verdict.rule) == ("notice_of", rule)


def test_a_notice_whose_authors_differ_from_the_paper_still_attaches():
    """Notices often carry the publisher, not the authors; only `differ` blocks the link."""
    notice = rec(title=f"Erratum: {TITLE}", doi="10.1109/synth.2026.2", authors=["Anonymous"])
    assert classify_pair(notice, rec()).link_kind == "notice_of"
    other = rec(title=f"Erratum: {TITLE}", doi="10.1109/synth.2026.2", authors=["Ada Kaya", "Bo Sun"])
    assert classify_pair(other, rec()) is None


def test_a_notice_of_a_different_paper_gives_no_verdict():
    notice = rec(title="Publisher Correction: SYNTHETIC receiver design for molecular links",
                 doi="10.1109/synth.2026.2")
    assert classify_pair(notice, rec()) is None


def test_an_artifact_attaches_to_the_paper_whose_title_and_authors_it_shares():
    artifact = rec(title=f"Data supporting {TITLE}", doi="10.5281/zenodo.123")
    verdict = classify_pair(artifact, rec())
    assert (verdict.link_kind, verdict.rule, verdict.merge, verdict.parent) == ("artifact_of", "artifact_same_title",
                                                                                False, "b")


def test_an_artifact_whose_authors_differ_gives_no_verdict():
    artifact = rec(title=f"Data supporting {TITLE}", doi="10.5281/zenodo.123", authors=["Ada Kaya", "Bo Sun"])
    assert classify_pair(artifact, rec()) is None


def test_a_preprint_that_names_the_published_doi_merges_whatever_the_title_says():
    verdict = classify_pair(preprint(title="SYNTHETIC an entirely different working title"), rec(),
                            names_published_doi=True)
    assert (verdict.link_kind, verdict.rule, verdict.merge) == ("same_work", "preprint_names_published_doi", True)


def test_a_named_published_doi_is_not_the_rule_for_two_preprints():
    """Row 5 needs one preprint and one published record; two preprints fall through to the text rules."""
    other = preprint(doi="10.1101/2026.01.01.999999", title="SYNTHETIC release scheduling in diffusion channels")
    verdict = classify_pair(preprint(), other, names_published_doi=True)
    assert (verdict.link_kind, verdict.rule, verdict.merge) == ("related_suspected", "similar_title_same_authors",
                                                                False)


def test_a_named_published_doi_ignores_a_year_gap_above_the_limit():
    verdict = classify_pair(preprint(year=2012), rec(year=2026), names_published_doi=True)
    assert verdict.merge is True and verdict.year_gap == 14


def test_a_pair_below_the_related_threshold_gives_no_verdict():
    assert classify_pair(preprint(title="SYNTHETIC receiver architectures for molecular links"), rec()) is None


def test_a_title_shorter_than_the_minimum_gives_no_verdict():
    assert len(normalize_text("Editorial")) < MIN_TITLE_CHARS
    assert classify_pair(preprint(title="Editorial"), rec(title="Editorial")) is None


def test_differing_authors_give_no_verdict():
    assert classify_pair(preprint(authors=["Ada Kaya", "Bo Sun"]), rec()) is None


def test_unknown_authors_leave_the_pair_suspected():
    verdict = classify_pair(preprint(authors=[]), rec())
    assert (verdict.link_kind, verdict.rule, verdict.merge) == ("related_suspected", "authors_unknown", False)


def test_two_published_records_never_merge_however_alike_they_are():
    a = rec(doi="10.1109/synth.2026.1", abstract=ABSTRACT)
    b = rec(doi="10.1145/synth.2026.9", abstract=ABSTRACT)
    verdict = classify_pair(a, b)
    assert verdict.merge is False
    assert (verdict.link_kind, verdict.rule) == ("extended_version", "two_published_similar_title")
    assert verdict.title_similarity == 1.0 and verdict.abstract_similarity == 1.0


def test_two_published_records_with_a_merely_similar_title_stay_suspected():
    b = rec(doi="10.1145/synth.2026.9", title="SYNTHETIC release scheduling for diffusion links and channels")
    verdict = classify_pair(rec(), b)
    assert TITLE_RELATED <= verdict.title_similarity < TITLE_MERGE
    assert (verdict.link_kind, verdict.rule, verdict.merge) == ("related_suspected", "two_published", False)


def test_a_record_of_unknown_kind_stays_suspected():
    verdict = classify_pair(rec(doi=None), rec())
    assert (verdict.link_kind, verdict.rule, verdict.merge) == ("related_suspected", "kind_unknown", False)


def test_a_year_gap_above_the_limit_blocks_a_merge_and_says_so():
    verdict = classify_pair(preprint(year=2019, abstract=ABSTRACT), rec(year=2026, abstract=ABSTRACT))
    assert verdict.year_gap == 7 > MAX_YEAR_GAP
    assert (verdict.link_kind, verdict.rule, verdict.merge) == ("related_suspected", "year_gap_blocks_merge", False)


def test_a_year_gap_within_the_limit_still_merges():
    verdict = classify_pair(preprint(year=2022, abstract=ABSTRACT), rec(year=2026, abstract=ABSTRACT))
    assert verdict.year_gap == 4
    assert (verdict.link_kind, verdict.rule, verdict.merge) == ("same_work", "title_authors_abstract", True)


def test_title_authors_and_abstract_together_merge_a_preprint_with_its_published_record():
    preprint_record = preprint(title="SYNTHETIC release scheduling for diffusion channel", abstract=ABSTRACT)
    verdict = classify_pair(preprint_record, rec(abstract=ABSTRACT))
    assert verdict.title_similarity >= TITLE_MERGE and verdict.abstract_similarity >= ABSTRACT_MERGE
    assert (verdict.link_kind, verdict.rule, verdict.merge) == ("same_work", "title_authors_abstract", True)
    assert verdict.author_agreement == "agree" and verdict.parent is None


def test_two_preprints_of_one_work_merge_as_well():
    other = preprint(doi="10.1101/2026.01.01.123456", abstract=ABSTRACT)
    verdict = classify_pair(preprint(abstract=ABSTRACT), other)
    assert (verdict.link_kind, verdict.merge) == ("same_work", True)


def test_a_similar_but_not_identical_title_does_not_merge_when_an_abstract_is_missing():
    verdict = classify_pair(preprint(title="SYNTHETIC release scheduling for diffusion channel"), rec())
    assert verdict.title_similarity >= TITLE_MERGE and verdict.abstract_similarity is None
    assert (verdict.link_kind, verdict.rule, verdict.merge) == ("related_suspected", "similar_title_same_authors",
                                                                False)


def test_an_identical_title_merges_when_an_abstract_is_missing():
    verdict = classify_pair(preprint(abstract=ABSTRACT), rec())
    assert (verdict.link_kind, verdict.rule, verdict.merge) == ("same_work", "identical_title_authors", True)


def test_a_retitled_version_is_probable_and_does_not_merge():
    retitled = preprint(title="SYNTHETIC scheduling of releases for diffusion channels", abstract=ABSTRACT)
    verdict = classify_pair(retitled, rec(abstract=ABSTRACT))
    assert TITLE_RELATED <= verdict.title_similarity < TITLE_MERGE
    assert (verdict.link_kind, verdict.rule, verdict.merge) == ("probable_version", "abstract_agrees_title_differs",
                                                                False)


def test_a_sibling_paper_by_the_same_authors_stays_suspected():
    sibling = preprint(title="SYNTHETIC release scheduling in diffusion channels", abstract=OTHER_ABSTRACT)
    verdict = classify_pair(sibling, rec(abstract=ABSTRACT))
    assert verdict.abstract_similarity < ABSTRACT_MERGE
    assert (verdict.link_kind, verdict.rule, verdict.merge) == ("related_suspected", "similar_title_same_authors",
                                                                False)


@pytest.mark.parametrize("a, b", [
    (preprint(abstract=ABSTRACT), rec(abstract=ABSTRACT)),
    (rec(title=f"Publisher Correction: {TITLE}", doi="10.1109/synth.2026.2"), rec()),
    (rec(title=f"Data supporting {TITLE}", doi="10.5281/zenodo.1"), rec()),
    (rec(), rec(doi="10.1145/synth.2026.9")),
    (preprint(authors=[]), rec()),
    (preprint(title="SYNTHETIC receiver architectures for molecular links"), rec()),
])
def test_a_verdict_differs_only_in_its_parent_when_the_two_records_are_swapped(a, b):
    forward, backward = classify_pair(a, b), classify_pair(b, a)
    if forward is None:
        assert backward is None
        return
    flipped = {"a": "b", "b": "a", None: None}[forward.parent]
    assert backward == type(forward)(**{**forward.__dict__, "parent": flipped})
