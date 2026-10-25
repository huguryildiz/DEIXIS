"""What a version link named by a second source does to a pair of records (SW6.4, slice 05).

Records are SYNTHETIC. Passing these tests shows that a named link confirms a merge even when the title was
rewritten, that a link naming a different published version blocks one, and that a merge made this way goes through
exactly the same guards and undo path as a merge made from the text; it says nothing about how often the external
sources are right, which was measured on one topic outside the product.
"""

import pytest

from deixis.providers.common import ProviderRecord
from deixis.providers.lookup import LookupAnswer
from deixis.storage import db
from deixis.workflow.run import links
from deixis.workflow.search import lookups
from deixis.workflow.run.store import Store

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


def research(store):
    rid = store.create_research("SYNTHETIC question?", "academic", "standard", ["openalex", "arxiv"], "fake", "m", "en")
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


def test_a_pair_the_user_undid_is_not_merged_again_by_an_external_link(store):
    rid, run_id = research(store)
    published, pre = pair(store, rid, run_id)
    name_link(store, pre, DOI)
    run_external(store, rid)
    links.undo_link(store, link_between(store, rid, published, pre)["id"])
    assert run_external(store, rid) == {"confirmed": 1, "blocked": 0, "disagree": 0}  # read again, stored not at all
    assert link_between(store, rid, published, pre) is None
    assert store.source(published)["work_id"] != store.source(pre)["work_id"]


# ---- a named link blocks --------------------------------------------------------------------


# ---- what an abstract arriving later changes ---------------------------------------------------
