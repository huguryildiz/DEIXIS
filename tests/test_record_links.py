"""Links between records of one research: what a search stores, what it merges and what undoing a merge restores (SW6).

Records are SYNTHETIC. Passing these tests shows that a search on the `sw` workflow stores every verdict with its rule
and scores, merges only a preprint with its published record, and can take a merge back; it says nothing about how
often the rule is right on real records, which was measured on one topic outside the product.

A `legacy` research is checked here too, because nothing about it may change.
"""

import json

import pytest

from deixis.domain.record_identity import Verdict
from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow import links
from deixis.workflow.store import NotFound, Store

TITLE = "SYNTHETIC release scheduling for diffusion channels"
NEAR_TITLE = "SYNTHETIC release scheduling for diffusion channel"  # title similarity 0.98
BAND_TITLE = "SYNTHETIC release scheduling in diffusion channels"  # title similarity 0.83
ABSTRACT = ("We study SYNTHETIC release scheduling in a diffusion channel and report the packet size that minimises "
            "the error rate under a fixed energy budget.")
OTHER_ABSTRACT = ("A SYNTHETIC survey of receiver architectures for molecular communication, with no scheduling and "
                  "no packet size analysis whatsoever in its pages.")
AUTHORS = ["Aydin, Mert", "Zhao, Li"]
SAME_AUTHORS_OTHER_ORDER = ["Mert Aydin", "Li Zhao"]
DOI = "10.1109/synth.2026.1"
ARXIV_DOI = "10.48550/arxiv.2601.00001"


@pytest.fixture
def store(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    yield Store(connection)
    connection.close()


def record(record_id, title=TITLE, doi=DOI, authors=AUTHORS, abstract=None, year=2026, merge_by_doi=True,
           version_label="publishedVersion", **identifiers):
    return ProviderRecord(
        provider_record_id=record_id, title=title, authors=list(authors), year=year, venue=None, publication_type=None,
        doi=doi, landing_url=None, oa_pdf_url=None, oa_pdf_version=None, version_label=version_label,
        abstract=abstract, abstract_origin="provider" if abstract else None, identifiers=identifiers, raw={},
        merge_by_doi=merge_by_doi,
    )


def preprint(record_id="2601.00001v1", doi=ARXIV_DOI, **fields):
    return record(record_id, doi=doi, merge_by_doi=False, version_label="submittedVersion", **fields)


def research(store, search_workflow="sw"):
    rid = store.create_research("SYNTHETIC question?", "academic", "standard", ["openalex", "arxiv"], "fake", "m", "en",
                                search_workflow=search_workflow)
    run = store.create_run(rid, "discovery", {"max_model_calls": 4, "max_provider_requests": 4, "max_candidates": 50,
                                              "max_answer_passages": 8}, None)
    return rid, run["id"]


def search(store, rid, run_id, index, provider, records):
    step = store.step(run_id, f"search:{index}", f"provider_search:{provider}")
    store.record_search(
        dict(research_id=rid, run_id=run_id, step_id=step["id"], scope_revision=1, provider=provider, query_text="q",
             request_description="GET test", access_mode="keyless", status="completed", delivery_class=None,
             result_count=len(records), provider_total=len(records), page_limit=25, error_json=None,
             raw_payload_path=None),
        provider, records, None, step["id"], "succeeded", step_output={"status": "completed"})


def finish(store, run_id):
    """Purging needs the research to have no active run."""
    store.update_run(run_id, status="completed")


def link_between(store, rid, a, b):
    """The one open link of this pair, whichever way round it is stored."""
    found = [row for row in links.research_links(store, rid)
             if {row["source_version_id"], row["other_source_version_id"]} == {a, b}]
    assert len(found) <= 1, found
    return found[0] if found else None


def joined_preprint(store, rid, run_id, published_abstract=None, preprint_abstract=None, preprint_title=TITLE):
    """A published record and the preprint that names its DOI, found by two searches; returns the two identifiers."""
    search(store, rid, run_id, 0, "openalex", [record("W1", abstract=published_abstract)])
    search(store, rid, run_id, 1, "arxiv", [preprint(title=preprint_title, authors=SAME_AUTHORS_OTHER_ORDER,
                                                     abstract=preprint_abstract, published_doi=DOI)])
    return store.find_source_by_identifier("openalex", "W1"), store.find_source_by_identifier("arxiv", "2601.00001v1")


# ---- the legacy workflow is untouched ----------------------------------------------------


def test_a_legacy_research_still_flags_suspected_duplicates_and_stores_no_links(store):
    rid, run_id = research(store, search_workflow="legacy")
    search(store, rid, run_id, 0, "openalex", [record("W1"), record("W2", doi="10.1145/synth.2026.9")])
    a = store.find_source_by_identifier("openalex", "W1")
    b = store.find_source_by_identifier("openalex", "W2")
    assert store.suspected_duplicates(rid)[a] == [{"source_version_id": b, "basis": "same_title"}]
    assert links.research_links(store, rid) == []


def test_an_sw_research_stores_links_and_no_suspected_duplicates(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [record("W1"), record("W2", doi="10.1145/synth.2026.9")])
    assert store.suspected_duplicates(rid) == {}
    assert [row["rule"] for row in links.research_links(store, rid)] == ["two_published_similar_title"]


# ---- what a search stores -----------------------------------------------------------------


def test_a_preprint_and_its_published_record_become_one_work_headed_by_the_published_record(store):
    rid, run_id = research(store)
    published, pre = joined_preprint(store, rid, run_id, ABSTRACT, ABSTRACT, preprint_title=NEAR_TITLE)
    assert store.source(published)["work_id"] == store.source(pre)["work_id"]
    assert store.work_heads(rid) == {store.source(published)["work_id"]: published}
    row = link_between(store, rid, published, pre)
    assert (row["link_kind"], row["rule"], row["source"], row["merged"]) == ("same_work",
                                                                            "preprint_names_published_doi",
                                                                            "arxiv_doi", 1)
    assert row["author_agreement"] == "agree" and row["year_gap"] == 0
    assert row["title_similarity"] > 0.9 and row["abstract_similarity"] == 1.0


def test_a_text_merge_stores_the_rule_and_its_three_scores(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [record("W1", abstract=ABSTRACT)])
    search(store, rid, run_id, 1, "arxiv", [preprint(title=NEAR_TITLE, authors=SAME_AUTHORS_OTHER_ORDER,
                                                     abstract=ABSTRACT)])
    published = store.find_source_by_identifier("openalex", "W1")
    pre = store.find_source_by_identifier("arxiv", "2601.00001v1")
    row = link_between(store, rid, published, pre)
    assert (row["link_kind"], row["rule"], row["source"], row["merged"]) == ("same_work", "title_authors_abstract",
                                                                            "text", 1)
    assert store.source(published)["work_id"] == store.source(pre)["work_id"]


def test_two_published_records_stay_in_separate_works_and_are_linked_as_extended_versions(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [record("W1", abstract=ABSTRACT),
                                               record("W2", doi="10.1145/synth.2026.9", abstract=ABSTRACT)])
    a = store.find_source_by_identifier("openalex", "W1")
    b = store.find_source_by_identifier("openalex", "W2")
    assert store.source(a)["work_id"] != store.source(b)["work_id"]
    row = link_between(store, rid, a, b)
    assert (row["link_kind"], row["rule"], row["merged"]) == ("extended_version", "two_published_similar_title", 0)


def test_a_work_that_already_has_a_published_record_takes_no_second_one(store):
    rid, run_id = research(store)
    published, pre = joined_preprint(store, rid, run_id)
    search(store, rid, run_id, 2, "crossref", [record("C1", doi="10.1145/synth.2026.9")])
    other = store.find_source_by_identifier("crossref", "C1")
    assert store.source(other)["work_id"] != store.source(pre)["work_id"]
    row = link_between(store, rid, pre, other)
    assert (row["link_kind"], row["rule"], row["merged"]) == ("related_suspected", "work_already_has_published", 0)


def test_a_refused_second_published_record_found_again_adds_no_row(store):
    rid, run_id = research(store)
    _, pre = joined_preprint(store, rid, run_id)
    second = record("C1", doi="10.1145/synth.2026.9")
    search(store, rid, run_id, 2, "crossref", [second])
    search(store, rid, run_id, 3, "crossref", [second])
    other = store.find_source_by_identifier("crossref", "C1")
    rows = [r for r in links.links_for(store, other, include_closed=True)
            if pre in (r["source_version_id"], r["other_source_version_id"])]
    assert [(r["rule"], r["closed_reason"]) for r in rows] == [("work_already_has_published", None)]


def test_a_sibling_paper_by_the_same_authors_stays_suspected(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [record("W1", abstract=ABSTRACT)])
    search(store, rid, run_id, 1, "arxiv", [preprint(title=BAND_TITLE, abstract=OTHER_ABSTRACT)])
    a = store.find_source_by_identifier("openalex", "W1")
    b = store.find_source_by_identifier("arxiv", "2601.00001v1")
    row = link_between(store, rid, a, b)
    assert (row["link_kind"], row["rule"], row["merged"]) == ("related_suspected", "similar_title_same_authors", 0)
    assert store.source(a)["work_id"] != store.source(b)["work_id"]


def test_a_retitled_version_is_probable_and_is_not_merged(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [record("W1", abstract=ABSTRACT)])
    search(store, rid, run_id, 1, "arxiv", [preprint(title=BAND_TITLE, abstract=ABSTRACT)])
    a = store.find_source_by_identifier("openalex", "W1")
    b = store.find_source_by_identifier("arxiv", "2601.00001v1")
    row = link_between(store, rid, a, b)
    assert (row["link_kind"], row["rule"], row["merged"]) == ("probable_version", "abstract_agrees_title_differs", 0)
    assert store.source(a)["work_id"] != store.source(b)["work_id"]


def test_a_correction_notice_attaches_to_the_paper_it_names(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [
        record("W1"), record("W2", title=f"Publisher Correction: {TITLE}", doi="10.1145/synth.2026.9")])
    paper = store.find_source_by_identifier("openalex", "W1")
    notice = store.find_source_by_identifier("openalex", "W2")
    row = link_between(store, rid, paper, notice)
    assert (row["link_kind"], row["rule"], row["merged"]) == ("notice_of", "correction", 0)
    assert row["parent_source_version_id"] == paper
    assert [c["source_version_id"] for c in store.candidates(rid)].count(notice) == 1  # still a candidate (slice 09)


def test_the_preprints_selection_moves_to_the_published_head_on_a_merge(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "arxiv", [preprint(authors=SAME_AUTHORS_OTHER_ORDER, published_doi=DOI)])
    pre = store.find_source_by_identifier("arxiv", "2601.00001v1")
    store.set_user_selection(rid, pre, "included", store.research(rid)["version"], "SYNTHETIC reason")
    search(store, rid, run_id, 1, "openalex", [record("W1")])
    published = store.find_source_by_identifier("openalex", "W1")
    assert store.work_heads(rid) == {store.source(published)["work_id"]: published}
    assert store.included_works(rid) == [published]


# ---- repeating a call, and a verdict that grows stronger -------------------------------------


def test_recording_the_same_search_again_adds_no_row(store):
    rid, run_id = research(store)
    records = [record("W1", abstract=ABSTRACT), record("W2", doi="10.1145/synth.2026.9", abstract=ABSTRACT)]
    search(store, rid, run_id, 0, "openalex", records)
    before = [dict(row) for row in links.research_links(store, rid)]
    search(store, rid, run_id, 1, "openalex", records)
    assert [dict(row) for row in links.research_links(store, rid)] == before


def test_an_abstract_arriving_later_supersedes_the_weaker_verdict(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [record("W1")])
    search(store, rid, run_id, 1, "arxiv", [preprint(title=NEAR_TITLE, authors=SAME_AUTHORS_OTHER_ORDER)])
    published = store.find_source_by_identifier("openalex", "W1")
    pre = store.find_source_by_identifier("arxiv", "2601.00001v1")
    assert link_between(store, rid, published, pre)["rule"] == "similar_title_same_authors"
    search(store, rid, run_id, 2, "openalex", [record("W1", abstract=ABSTRACT)])
    search(store, rid, run_id, 3, "arxiv", [preprint(title=NEAR_TITLE, authors=SAME_AUTHORS_OTHER_ORDER,
                                                     abstract=ABSTRACT)])
    assert link_between(store, rid, published, pre)["rule"] == "title_authors_abstract"
    closed = links.links_for(store, pre, include_closed=True)
    assert [(row["rule"], row["closed_reason"]) for row in closed if row["closed_at"]] == [
        ("similar_title_same_authors", "superseded")]
    assert store.source(published)["work_id"] == store.source(pre)["work_id"]


def test_a_merged_link_is_not_weakened_by_a_later_verdict(store):
    """A work that was joined is not split again by a weaker reading of the same pair; only the user undoes it."""
    rid, run_id = research(store)
    published, pre = joined_preprint(store, rid, run_id, preprint_title=BAND_TITLE)
    row = link_between(store, rid, published, pre)
    assert (row["rule"], row["merged"]) == ("preprint_names_published_doi", 1)
    weaker = Verdict("related_suspected", "similar_title_same_authors", False, 0.83, None, "agree", 0, None)
    assert links.save_link(store, published, pre, weaker, "text")["id"] == row["id"]
    assert link_between(store, rid, published, pre)["rule"] == "preprint_names_published_doi"
    assert len(links.links_for(store, pre, include_closed=True)) == 1
    assert store.source(published)["work_id"] == store.source(pre)["work_id"]


# ---- undoing a merge -------------------------------------------------------------------------


def test_undoing_a_merge_gives_each_record_its_work_back(store):
    rid, run_id = research(store)
    published, pre = joined_preprint(store, rid, run_id)
    row = link_between(store, rid, published, pre)
    undo = json.loads(row["undo_json"])
    links.undo_link(store, row["id"], note="SYNTHETIC check")
    assert store.source(pre)["work_id"] == undo["dropped_work"]["id"] != store.source(published)["work_id"]
    closed = links.links_for(store, pre, include_closed=True)[0]
    assert (closed["closed_reason"], closed["closed_note"]) == ("undone", "SYNTHETIC check")
    assert set(store.work_heads(rid).values()) == {published, pre}


def test_undoing_a_link_that_is_already_closed_is_refused(store):
    rid, run_id = research(store)
    published, pre = joined_preprint(store, rid, run_id)
    row = link_between(store, rid, published, pre)
    links.undo_link(store, row["id"])
    with pytest.raises(ValueError):
        links.undo_link(store, row["id"])
    with pytest.raises(NotFound):
        links.undo_link(store, "lnk_missing")


def test_an_undone_merge_is_not_made_again_by_the_same_search(store):
    rid, run_id = research(store)
    published, pre = joined_preprint(store, rid, run_id)
    links.undo_link(store, link_between(store, rid, published, pre)["id"])
    search(store, rid, run_id, 2, "arxiv", [preprint(authors=SAME_AUTHORS_OTHER_ORDER, published_doi=DOI)])
    assert store.source(pre)["work_id"] != store.source(published)["work_id"]
    assert link_between(store, rid, published, pre) is None


def test_a_restored_work_whose_key_was_taken_is_given_a_new_one(store):
    rid, run_id = research(store)
    published, pre = joined_preprint(store, rid, run_id)
    row = link_between(store, rid, published, pre)
    dropped = json.loads(row["undo_json"])["dropped_work"]
    assert dropped["source_key"] is not None
    store.conn.execute("INSERT INTO works (id, created_at, source_key, source_key_basis) VALUES (?, ?, ?, 'author')",
                       ("wrk_squatter", "2026-01-01T00:00:00.000+00:00", dropped["source_key"]))
    links.undo_link(store, row["id"])
    restored = store.source_key(store.source(pre)["work_id"])
    assert restored is not None and restored != dropped["source_key"]


def test_a_record_that_joined_the_work_later_stays_where_it_is_when_an_earlier_merge_is_undone(store):
    rid, run_id = research(store)
    published, pre = joined_preprint(store, rid, run_id)
    search(store, rid, run_id, 2, "biorxiv", [preprint("BX1", doi="10.1101/2026.01.01.123456",
                                                       authors=SAME_AUTHORS_OTHER_ORDER)])
    third = store.find_source_by_identifier("biorxiv", "BX1")
    assert store.source(third)["work_id"] == store.source(published)["work_id"]
    links.undo_link(store, link_between(store, rid, published, pre)["id"])
    assert store.source(third)["work_id"] == store.source(published)["work_id"]
    assert store.source(pre)["work_id"] != store.source(published)["work_id"]


def test_undoing_a_merge_leaves_every_passage_and_record_in_place(store):
    rid, run_id = research(store)
    published, pre = joined_preprint(store, rid, run_id, published_abstract=ABSTRACT, preprint_abstract=ABSTRACT)
    passages = {svid: [p["id"] for p in store.passages_for(svid)] for svid in (published, pre)}
    links.undo_link(store, link_between(store, rid, published, pre)["id"])
    assert {svid: [p["id"] for p in store.passages_for(svid)] for svid in (published, pre)} == passages
    assert store.source(published)["id"] == published and store.source(pre)["id"] == pre


def test_links_for_a_record_reads_the_pair_from_either_side(store):
    rid, run_id = research(store)
    published, pre = joined_preprint(store, rid, run_id)
    assert [row["id"] for row in links.links_for(store, published)] == [row["id"] for row in links.links_for(store, pre)]
    links.undo_link(store, link_between(store, rid, published, pre)["id"])
    assert links.links_for(store, published) == []
    assert len(links.links_for(store, published, include_closed=True)) == 1


# ---- permanent deletion ----------------------------------------------------------------------


def test_a_research_with_linked_records_can_be_permanently_deleted(store):
    rid, run_id = research(store)
    joined_preprint(store, rid, run_id)
    assert links.research_links(store, rid)
    finish(store, run_id)
    store.trash_research(rid)
    store.purge_research(rid)
    assert store.conn.execute("SELECT COUNT(*) FROM record_links").fetchone()[0] == 0


def test_a_link_of_a_record_another_research_still_holds_stays(store):
    """Links belong to the library, like the works they group, so deleting one research does not take them."""
    both = [record("W1", abstract=ABSTRACT), record("W2", doi="10.1145/synth.2026.9", abstract=ABSTRACT)]
    first, first_run = research(store)
    search(store, first, first_run, 0, "openalex", both)
    second, second_run = research(store)
    search(store, second, second_run, 0, "openalex", both)
    assert len(links.research_links(store, second)) == 1
    finish(store, first_run)
    store.trash_research(first)
    store.purge_research(first)
    assert len(links.research_links(store, second)) == 1


def test_a_removed_and_linked_source_can_be_purged_from_one_research(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [record("W1", abstract=ABSTRACT),
                                               record("W2", doi="10.1145/synth.2026.9", abstract=ABSTRACT)])
    a = store.find_source_by_identifier("openalex", "W1")
    b = store.find_source_by_identifier("openalex", "W2")
    assert link_between(store, rid, a, b) is not None
    finish(store, run_id)
    store.remove_sources(rid, [b], None)
    store.purge_sources(rid, [b])
    assert store.conn.execute("SELECT COUNT(*) FROM record_links").fetchone()[0] == 0
    assert store.source(a)["id"] == a
