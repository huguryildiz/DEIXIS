"""D4: an answer over attached PDFs only shares the passage limit among them, and reference lists go last.

`flow._retrieve` on a store built here. SYNTHETIC text; this shows which passages are chosen, not answer quality.
"""

from deixis.storage import db
from deixis.workflow.flow import MAX_PASSAGES_PER_SOURCE, _reference_list
from deixis.workflow.store import Store
from test_criterion_passage_flow import ABSTRACT, OFF_PAGE, QUESTION, TOPIC_PAGE, page_source, retrieve

REFERENCE_PAGE = ("SYNTHETIC fatigue. REFERENCES "
                  "[1] A. Smith, “Exercise after chemotherapy,” J. Onc., 2020. "
                  "[2] Jones, B., “Fatigue in cancer,” 2019. "
                  "[3] C. Lee and D. Park, “Supervised exercise,” 2021.")


def attached_library(tmp_path, scope="attached"):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research(QUESTION, scope, "standard", [], "fake", "fake-model", None)
    return store, rid


def per_source(chosen, svid):
    return len([p for p in chosen if p["source_version_id"] == svid])


def test_two_attached_pdfs_share_the_limit_instead_of_six_passages_each(tmp_path):
    store, rid = attached_library(tmp_path)
    svids = [page_source(store, rid, f"pdf{i}", [f"{TOPIC_PAGE} page {n}." for n in range(20)], ABSTRACT)
             for i in range(2)]
    chosen = retrieve(store, rid, svids, 48)
    assert all(per_source(chosen, svid) > MAX_PASSAGES_PER_SOURCE for svid in svids)
    assert all(per_source(chosen, svid) <= 48 // 2 for svid in svids)
    assert len(chosen) <= 48


def test_many_attached_pdfs_keep_the_six_passage_floor_and_the_limit(tmp_path):
    store, rid = attached_library(tmp_path)
    svids = [page_source(store, rid, f"pdf{i}", [f"{TOPIC_PAGE} page {n}." for n in range(10)], ABSTRACT)
             for i in range(12)]
    chosen = retrieve(store, rid, svids, 48)
    assert len(chosen) <= 48 and all(per_source(chosen, svid) <= MAX_PASSAGES_PER_SOURCE for svid in svids)


def test_attached_and_academic_keeps_the_six_passage_cap(tmp_path):
    store, rid = attached_library(tmp_path, "attached_and_academic")
    svids = [page_source(store, rid, f"pdf{i}", [f"{TOPIC_PAGE} page {n}." for n in range(20)], ABSTRACT)
             for i in range(2)]
    chosen = retrieve(store, rid, svids, 48)
    assert all(per_source(chosen, svid) == MAX_PASSAGES_PER_SOURCE for svid in svids)


def test_a_reference_list_passage_comes_after_every_topic_page(tmp_path):
    """A reference page matches the question words, yet a page that states a finding is given before it."""
    store, rid = attached_library(tmp_path)
    pages = [REFERENCE_PAGE] + [f"{TOPIC_PAGE} page {n}." for n in range(8)]
    svids = [page_source(store, rid, f"pdf{i}", pages, ABSTRACT) for i in range(2)]
    roomy = [p["text"] for p in retrieve(store, rid, svids, 48)]
    assert REFERENCE_PAGE in roomy  # room is left, so it is not dropped
    tight = [p["text"] for p in retrieve(store, rid, svids, 2 * (1 + 8))]
    assert REFERENCE_PAGE not in tight and len(tight) == 2 * (1 + 8)


def test_body_citations_are_not_a_reference_list():
    assert _reference_list(REFERENCE_PAGE)
    assert not _reference_list("SYNTHETIC as shown in [5] considering depth, and in [6], [7] and [12] for energy.")
    assert not _reference_list("SYNTHETIC [1] A. Smith found fatigue fell, [2] B. Lee agreed and [3] C. Park did not.")
    conclusions = "SYNTHETIC conclusions: supervised exercise lowered fatigue in every cohort we studied. " * 6
    assert not _reference_list(conclusions + REFERENCE_PAGE)
    short_conclusion = "SYNTHETIC Conclusion: supervised exercise lowered fatigue in all three cohorts we followed. "
    assert not _reference_list(short_conclusion + REFERENCE_PAGE + " [4] D. Kim, \u201cRest,\u201d 2018.")
    quoted = "SYNTHETIC Conclusion: \u201csupervised exercise\u201d lowered fatigue in the three cohorts we followed. "
    assert not _reference_list(quoted + REFERENCE_PAGE.split("REFERENCES ")[1])
    previous_tail = "Commun., vol. 120, pp. 1\u201316, Oct. 2021.\n"
    assert _reference_list(previous_tail + REFERENCE_PAGE.split("REFERENCES ")[1])


def test_no_included_source_gives_no_passage(tmp_path):
    store, rid = attached_library(tmp_path)
    assert retrieve(store, rid, [], 48) == []
