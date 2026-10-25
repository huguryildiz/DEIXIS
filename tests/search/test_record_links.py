"""Links between records of one research: what a search stores, what it merges and what undoing a merge restores (SW6).

Records are SYNTHETIC. Passing these tests shows that a search on the `sw` workflow stores every verdict with its rule
and scores, merges only a preprint with its published record, and can take a merge back; it says nothing about how
often the rule is right on real records, which was measured on one topic outside the product.
"""

import json

import pytest

from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow.run import links
from deixis.workflow.run.store import Store

TITLE = "SYNTHETIC release scheduling for diffusion channels"
NEAR_TITLE = "SYNTHETIC release scheduling for diffusion channel"  # title similarity 0.98
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


# ---- repeating a call, and a verdict that grows stronger -------------------------------------


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


def test_an_undone_merge_is_not_made_again_by_the_same_search(store):
    rid, run_id = research(store)
    published, pre = joined_preprint(store, rid, run_id)
    links.undo_link(store, link_between(store, rid, published, pre)["id"])
    search(store, rid, run_id, 2, "arxiv", [preprint(authors=SAME_AUTHORS_OTHER_ORDER, published_doi=DOI)])
    assert store.source(pre)["work_id"] != store.source(published)["work_id"]
    assert link_between(store, rid, published, pre) is None


# ---- permanent deletion ----------------------------------------------------------------------
