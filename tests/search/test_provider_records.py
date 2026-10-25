"""Cross-provider records (DOI merge, preprint and published versions, candidate ranks) and per-provider query rules."""

from dataclasses import replace

import pytest

from deixis.providers import query_rules
from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow.store import Store

DOI = "10.1109/synth.2021.1"


@pytest.fixture
def store(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    yield Store(connection)
    connection.close()


def record(record_id, title="SYNTHETIC release scheduling for diffusion channels", doi=DOI, abstract=None, merge_by_doi=True, **identifiers):
    return ProviderRecord(
        provider_record_id=record_id, title=title, authors=[], year=2021, venue=None, publication_type=None, doi=doi,
        landing_url=None, oa_pdf_url=None, oa_pdf_version=None, version_label="publishedVersion", abstract=abstract,
        abstract_origin="provider_test" if abstract else None, identifiers=identifiers, raw={}, merge_by_doi=merge_by_doi,
    )


def search(store, rid, run_id, index, provider, records):
    step = store.step(run_id, f"search:{index}", f"provider_search:{provider}")
    fields = dict(research_id=rid, run_id=run_id, step_id=step["id"], scope_revision=1, provider=provider, query_text="q",
                  request_description="GET test", access_mode="keyless", status="completed", delivery_class=None,
                  result_count=len(records), provider_total=len(records), page_limit=25, error_json=None, raw_payload_path=None)
    store.record_search(fields, provider, records, None, step["id"], "succeeded", step_output={"status": "completed"})


def research(store):
    rid = store.create_research("SYNTHETIC question?", "academic", "standard", ["openalex", "ieee_xplore", "arxiv"], "fake", "m", "en")
    run = store.create_run(rid, "discovery", {"max_model_calls": 4, "max_provider_requests": 4, "max_candidates": 50,
                                               "max_answer_passages": 8}, None)
    return rid, run["id"]


def test_same_doi_from_two_providers_is_one_source_with_both_mappings(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [record("W1", doi=DOI)])
    search(store, rid, run_id, 1, "ieee_xplore", [record("123", doi=DOI, abstract="We schedule release times.")])
    candidates = store.candidates(rid)
    assert len(candidates) == 1
    svid = candidates[0]["source_version_id"]
    assert store.find_source_by_identifier("openalex", "W1") == store.find_source_by_identifier("ieee_xplore", "123") == svid
    assert [p["text"] for p in store.passages_for(svid)] == ["We schedule release times."]  # the abstract the first record lacked


AUTHORS = ["Tu N. Nguyen", "Dung H. P. Nguyen", "Dang H. Pham", "Bing-Hong Liu"]
TITLE = "SYNTHETIC entanglement routing rate: approximation algorithms"


def preprint_record(record_id="2207.11821v1", authors=AUTHORS, title=TITLE):
    return replace(record(record_id, title=title, doi="10.48550/arxiv.2207.11821", merge_by_doi=False),
                   authors=authors, version_label="arXiv v1")


def published_record(record_id="W9", authors=AUTHORS, title=TITLE, doi=DOI):
    return replace(record(record_id, title=title, doi=doi), authors=authors)


def screen(store, rid, run_id, svid, proposal="include"):
    # Historical selection row: the removed model step cannot run in this checkout.
    store.conn.execute(
        "UPDATE selections SET state = ?, origin = 'model_proposal', proposal = ?,"
        " proposal_reason = 'SYNTHETIC reason', proposal_basis = 'title_and_abstract'"
        " WHERE research_id = ? AND source_version_id = ?",
        ("included" if proposal == "include" else "excluded", proposal, rid, svid),
    )


def test_a_published_record_heads_the_work_of_its_screened_preprint(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "arxiv", [preprint_record()])
    preprint = store.find_source_by_identifier("arxiv", "2207.11821v1")
    screen(store, rid, run_id, preprint)
    search(store, rid, run_id, 1, "openalex", [published_record(authors=["T. N. Nguyen", "D. H. P. Nguyen", "D. H. Pham"])])
    published = store.find_source_by_identifier("openalex", "W9")
    wid = store.source(published)["work_id"]
    assert store.source(preprint)["work_id"] == wid
    assert store.work_heads(rid) == {wid: published} and store.included_works(rid) == [published]
    head = store.conn.execute("SELECT state, origin, proposal FROM selections WHERE source_version_id = ?", (published,)).fetchone()
    assert tuple(head) == ("included", "model_proposal", "include")  # taken from the screened preprint, not screened again


def test_well_formed_queries_for_every_provider_pass():
    assert [(p, query_rules.query_issues(p, q)) for p, q in [
        ("openalex", '"molecular communication" AND ("resource allocation" OR scheduling)'),
        ("biorxiv", '"quorum sensing" AND (optimization OR "optimal control")'),
        ("ieee_xplore", '"molecular communication" AND (scheduling OR "power allocation")'),
        ("scopus", 'TITLE-ABS-KEY("molecular communication" AND ("resource allocation" OR scheduling))'),
        ("arxiv", 'abs:"molecular communication" AND (abs:scheduling OR abs:allocation)'),
        ("semantic_scholar", "molecular communication resource allocation"),
        ("crossref", "molecular communication scheduling"),
        ("core", '"molecular communication" AND ("resource allocation" OR scheduling)'),
        ("serpapi", '"molecular communication" scheduling OR "resource allocation"'),
    ] if query_rules.query_issues(p, q)] == []


@pytest.mark.parametrize("provider,query", [
    ("scopus", '"molecular communication" AND scheduling'),
    ("semantic_scholar", '"molecular communication" AND scheduling'),
])
def test_malformed_queries_are_refused(provider, query):
    assert query_rules.query_issues(provider, query)
