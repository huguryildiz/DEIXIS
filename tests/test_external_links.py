"""What a version link named by a second source does to a pair of records (SW6.4, slice 05).

Records are SYNTHETIC. Passing these tests shows that a named link confirms a merge even when the title was
rewritten, that a link naming a different published version blocks one, and that a merge made this way goes through
exactly the same guards and undo path as a merge made from the text; it says nothing about how often the external
sources are right, which was measured on one topic outside the product.

A `legacy` research is checked here too, because nothing about it may change.
"""

import pytest

from deixis.providers.common import ProviderRecord
from deixis.providers.lookup import LookupAnswer
from deixis.storage import db
from deixis.workflow import links, lookups
from deixis.workflow.store import Store

TITLE = "SYNTHETIC release scheduling for diffusion channels"
# A title the text rule can never match to TITLE: SW6.4 keeps the link even when the title changed at publication.
RETITLED = "SYNTHETIC energy budgets of nanoscale transmitters under drift"
NEAR_TITLE = "SYNTHETIC release scheduling for diffusion channel"
ABSTRACT = ("We study SYNTHETIC release scheduling in a diffusion channel and report the packet size that minimises "
            "the error rate under a fixed energy budget.")
OTHER_ABSTRACT = "We measure SYNTHETIC turbulence in a vascular channel and fit a drift model to it."
AUTHORS = ["Aydin, Mert", "Zhao, Li"]
DOI = "10.1109/synth.2026.1"
OTHER_DOI = "10.1145/synth.2026.9"
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
        merge_by_doi=merge_by_doi)


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


def link_between(store, rid, a, b):
    found = [row for row in links.research_links(store, rid)
             if {row["source_version_id"], row["other_source_version_id"]} == {a, b}]
    assert len(found) <= 1, found
    return found[0] if found else None


def name_link(store, svid, value, provider="semantic_scholar"):
    """What a lookup answer writes: the DOI a second source says is another version of this record."""
    lookups.store_answer(store, svid, provider, LookupAnswer("found", linked_dois=[value]), "stp_lookup", None)


def own_doi(store, svid, doi):
    """An arXiv DOI never merges by DOI, so the preprint needs its own `doi` mapping for a link to find it."""
    store.conn.execute("INSERT OR IGNORE INTO identifier_mappings (source_version_id, scheme, value, provider,"
                       " retrieved_at) VALUES (?, 'doi', ?, 'arxiv', '2026-09-21T00:00:00.000+00:00')", (svid, doi))


def pair(store, rid, run_id, preprint_title=RETITLED, preprint_abstract=None, published_abstract=None):
    """A published record and a preprint, found by two searches, with no link between them yet."""
    search(store, rid, run_id, 0, "openalex", [record("W1", abstract=published_abstract)])
    search(store, rid, run_id, 1, "arxiv", [preprint(title=preprint_title, abstract=preprint_abstract)])
    published = store.find_source_by_identifier("openalex", "W1")
    pre = store.find_source_by_identifier("arxiv", "2601.00001v1")
    own_doi(store, pre, ARXIV_DOI)
    return published, pre


def run_external(store, rid):
    with db.transaction(store.conn):
        return links.link_external(store, rid)


# ---- a named link confirms ------------------------------------------------------------------


def test_a_retitled_preprint_merges_with_the_published_record_a_source_named(store):
    """The titles share nothing, so only the external link can join them (SW6.4)."""
    rid, run_id = research(store)
    published, pre = pair(store, rid, run_id)
    assert link_between(store, rid, published, pre) is None  # the text rule never looked at this pair
    name_link(store, pre, DOI)
    assert run_external(store, rid) == {"confirmed": 1, "blocked": 0, "disagree": 0}
    row = link_between(store, rid, published, pre)
    assert (row["link_kind"], row["rule"], row["source"], row["merged"]) == (
        "same_work", "external_link_names_published_doi", "semantic_scholar", 1)
    assert store.source(published)["work_id"] == store.source(pre)["work_id"]


def test_a_crossref_relation_names_its_own_source_on_the_link(store):
    rid, run_id = research(store)
    published, pre = pair(store, rid, run_id)
    name_link(store, pre, DOI, provider="crossref")
    run_external(store, rid)
    assert link_between(store, rid, published, pre)["source"] == "crossref_relation"


def test_a_merge_made_from_an_external_link_can_be_undone_like_any_other(store):
    rid, run_id = research(store)
    published, pre = pair(store, rid, run_id)
    name_link(store, pre, DOI)
    run_external(store, rid)
    row = link_between(store, rid, published, pre)
    links.undo_link(store, row["id"], "SYNTHETIC: the user says these are different papers")
    assert store.source(published)["work_id"] != store.source(pre)["work_id"]
    assert links.links_for(store, pre, include_closed=True)[0]["closed_reason"] == "undone"


def test_a_pair_the_user_undid_is_not_merged_again_by_an_external_link(store):
    rid, run_id = research(store)
    published, pre = pair(store, rid, run_id)
    name_link(store, pre, DOI)
    run_external(store, rid)
    links.undo_link(store, link_between(store, rid, published, pre)["id"])
    assert run_external(store, rid) == {"confirmed": 1, "blocked": 0, "disagree": 0}  # read again, stored not at all
    assert link_between(store, rid, published, pre) is None
    assert store.source(published)["work_id"] != store.source(pre)["work_id"]


def test_reading_the_same_external_links_twice_adds_no_row(store):
    rid, run_id = research(store)
    published, pre = pair(store, rid, run_id)
    name_link(store, pre, DOI)
    run_external(store, rid)
    before = [dict(row) for row in links.research_links(store, rid)]
    run_external(store, rid)
    assert [dict(row) for row in links.research_links(store, rid)] == before


# ---- a named link blocks --------------------------------------------------------------------


def test_a_preprint_naming_another_published_doi_is_not_merged_with_this_one(store):
    """The text alone would have merged this pair; the link says the published version is a different paper."""
    rid, run_id = research(store)
    published, pre = pair(store, rid, run_id, preprint_title=NEAR_TITLE, preprint_abstract=ABSTRACT,
                          published_abstract=ABSTRACT)
    assert link_between(store, rid, published, pre)["rule"] == "title_authors_abstract"
    # A fresh pair, so the earlier merge does not stand in the way of what the rule now says.
    store.conn.execute("DELETE FROM record_links")
    name_link(store, pre, OTHER_DOI)
    with db.transaction(store.conn):
        links.link_records(store, rid, [pre])
    row = link_between(store, rid, published, pre)
    assert (row["link_kind"], row["rule"], row["merged"]) == ("related_suspected", "external_link_names_other_doi", 0)


def test_the_arxiv_doi_field_blocks_the_same_pair_at_search_time(store):
    """Slice 03 only let the author's own field confirm a merge; now it blocks one too."""
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [record("W1", abstract=ABSTRACT)])
    search(store, rid, run_id, 1, "arxiv", [preprint(title=NEAR_TITLE, abstract=ABSTRACT, published_doi=OTHER_DOI)])
    published = store.find_source_by_identifier("openalex", "W1")
    pre = store.find_source_by_identifier("arxiv", "2601.00001v1")
    row = link_between(store, rid, published, pre)
    assert (row["rule"], row["merged"]) == ("external_link_names_other_doi", 0)
    assert store.source(published)["work_id"] != store.source(pre)["work_id"]


def test_two_sources_naming_two_different_dois_confirm_nothing(store):
    rid, run_id = research(store)
    published, pre = pair(store, rid, run_id)
    name_link(store, pre, DOI, provider="semantic_scholar")
    name_link(store, pre, OTHER_DOI, provider="crossref")
    assert run_external(store, rid) == {"confirmed": 0, "blocked": 0, "disagree": 1}
    row = link_between(store, rid, published, pre)
    assert (row["link_kind"], row["rule"], row["merged"]) == ("related_suspected", "external_links_disagree", 0)
    assert store.source(published)["work_id"] != store.source(pre)["work_id"]


def test_two_published_records_are_not_merged_by_an_external_link_either(store):
    """SW6.5 holds by every path: the guard in `save_link` refuses the merge and records why."""
    rid, run_id = research(store)
    # The preprint and W1 are merged by the text alone, so the preprint itself names no DOI yet.
    search(store, rid, run_id, 0, "openalex", [record("W1")])
    search(store, rid, run_id, 1, "arxiv", [preprint(title=TITLE)])
    search(store, rid, run_id, 2, "crossref", [record("C1", title=RETITLED, doi=OTHER_DOI)])
    published = store.find_source_by_identifier("openalex", "W1")
    pre = store.find_source_by_identifier("arxiv", "2601.00001v1")
    other = store.find_source_by_identifier("crossref", "C1")
    own_doi(store, pre, ARXIV_DOI)
    assert store.source(published)["work_id"] == store.source(pre)["work_id"]  # merged by identical title and authors
    name_link(store, pre, OTHER_DOI)  # a source now names a second published version of the same preprint
    run_external(store, rid)
    row = link_between(store, rid, pre, other)
    assert (row["link_kind"], row["rule"], row["merged"]) == ("related_suspected", "work_already_has_published", 0)
    assert store.source(other)["work_id"] != store.source(pre)["work_id"]


def test_a_merged_pair_an_external_link_contradicts_is_counted_and_left_merged(store):
    """Only the user undoes a merge (D72); code that disagrees with itself says so and changes nothing."""
    rid, run_id = research(store)
    published, pre = pair(store, rid, run_id, preprint_title=NEAR_TITLE, preprint_abstract=ABSTRACT,
                          published_abstract=ABSTRACT)
    assert store.source(published)["work_id"] == store.source(pre)["work_id"]
    name_link(store, pre, OTHER_DOI)
    assert links.contradicted_merges(store, rid) == [sorted((published, pre))]
    assert store.source(published)["work_id"] == store.source(pre)["work_id"]


# ---- what an abstract arriving later changes ---------------------------------------------------


def test_a_pair_is_read_again_when_a_lookup_fills_an_abstract(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [record("W1", abstract=ABSTRACT)])
    search(store, rid, run_id, 1, "arxiv", [preprint(title=NEAR_TITLE)])
    published = store.find_source_by_identifier("openalex", "W1")
    pre = store.find_source_by_identifier("arxiv", "2601.00001v1")
    assert link_between(store, rid, published, pre)["rule"] == "similar_title_same_authors"
    lookups.store_answer(store, pre, "crossref", LookupAnswer("found", abstract=ABSTRACT), "stp_lookup", None)
    with db.transaction(store.conn):
        links.link_records(store, rid, [pre])
    assert link_between(store, rid, published, pre)["rule"] == "title_authors_abstract"
    closed = [row for row in links.links_for(store, pre, include_closed=True) if row["closed_at"]]
    assert [(row["rule"], row["closed_reason"]) for row in closed] == [("similar_title_same_authors", "superseded")]


# ---- the legacy workflow is untouched ------------------------------------------------------------


def test_a_legacy_research_does_not_read_a_linked_doi(store):
    """`legacy` reads `published_doi` alone (D48), so the scheme this slice writes is invisible to it."""
    rid, run_id = research(store, search_workflow="legacy")
    search(store, rid, run_id, 0, "openalex", [record("W1", title=TITLE)])
    search(store, rid, run_id, 1, "openalex", [record("W2", title=RETITLED, doi=OTHER_DOI)])
    first = store.find_source_by_identifier("openalex", "W1")
    second = store.find_source_by_identifier("openalex", "W2")
    name_link(store, first, OTHER_DOI)
    assert store.suspected_duplicates(rid) == {}  # the titles differ and a linked DOI is not a duplicate signal
    assert links.research_links(store, rid) == []
    assert store.source(first)["work_id"] != store.source(second)["work_id"]
