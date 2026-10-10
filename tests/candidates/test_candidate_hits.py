"""Every search that found a candidate and the two numbers per source read from them (slice 14, D93, migration 0049).

Records and searches are SYNTHETIC and from two fields, written straight through the store. Passing shows what is
kept and counted, not whether a record only one source found is relevant; the numbers count, they do not judge.
"""

from __future__ import annotations

import pytest

from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow import views
from deixis.workflow.store import Store


@pytest.fixture
def store(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    yield Store(connection)
    connection.close()


def record(provider, number, doi=None):
    return ProviderRecord(
        provider_record_id=f"{provider}-{number}", title=f"SYNTHETIC {provider} record {number}", authors=[], year=2025,
        venue=None, publication_type=None, doi=doi or f"10.9/{provider}.{number}", landing_url=None, oa_pdf_url=None,
        oa_pdf_version=None, version_label=None, abstract=None, abstract_origin=None, identifiers={}, raw={})


def research(store, workflow="sw"):
    rid = store.create_research("SYNTHETIC question?", "academic", "standard", ["openalex", "pubmed"], "fake", "m", "en",
                                search_workflow=workflow)
    run = store.create_run(rid, "discovery", {"max_model_calls": 4, "max_provider_requests": 8, "max_candidates": 50,
                                              "max_answer_passages": 8}, None)
    return rid, run["id"]


def search(store, rid, run_id, key, provider, query, records):
    step = store.step(run_id, key, f"provider_search:{provider}")
    store.record_search(dict(
        research_id=rid, run_id=run_id, step_id=step["id"], scope_revision=1, provider=provider, query_text=query,
        request_description="GET SYNTHETIC", access_mode="keyless", status="completed", delivery_class=None,
        result_count=len(records), provider_total=len(records), page_limit=25, error_json=None, raw_payload_path=None,
    ), provider, records, None, step["id"], "succeeded", step_output={"status": "completed"})


def test_a_record_found_by_two_searches_keeps_both_while_its_candidate_row_keeps_one(store):
    rid, run_id = research(store)
    shared = "10.9/shared.reef"
    search(store, rid, run_id, "search:0", "openalex", "reef AND transplant", [record("openalex", 1, shared)])
    search(store, rid, run_id, "search:1", "pubmed", "reef[Title/Abstract]", [record("pubmed", 1, shared)])
    (candidate,) = store.candidates(rid)
    hits = store.conn.execute("SELECT source_version_id, search_run_id FROM candidate_hits WHERE research_id = ?",
                              (rid,)).fetchall()
    assert len(hits) == 2 and {h["source_version_id"] for h in hits} == {candidate["source_version_id"]}


def test_each_source_counts_the_works_it_brought_and_those_no_other_source_did(store):
    rid, run_id = research(store)
    search(store, rid, run_id, "search:0", "openalex", "q1", [record("openalex", 1), record("openalex", 2, "10.9/both")])
    search(store, rid, run_id, "search:1", "pubmed", "q2", [record("pubmed", 1, "10.9/both"), record("pubmed", 2),
                                                            record("pubmed", 3)])
    counts = views.source_counts(store, run_id)
    assert counts == {"counted": True, "sources": [
        {"provider_id": "openalex", "works": 2, "only": 1}, {"provider_id": "pubmed", "works": 3, "only": 2}]}


def test_every_query_of_one_source_is_counted_in_its_one_row(store):
    rid, run_id = research(store)
    card = store.step(run_id, "protocol_approval", "code:protocol_approval")
    store.start_step(card["id"])
    store.finish_step(card["id"], "succeeded", output={"approved": {"queries": [{"provider_id": "openalex"}]}})
    search(store, rid, run_id, "search:0", "openalex", "q1", [record("openalex", 1)])
    search(store, rid, run_id, "search:1", "openalex", "q2", [record("openalex", 2), record("openalex", 1)])
    counts = views.source_counts(store, run_id)
    assert counts["sources"] == [{"provider_id": "openalex", "works": 2, "only": 2}]


def test_a_run_searched_before_the_hit_table_says_its_counts_were_not_kept_rather_than_zero(store):
    rid, run_id = research(store)
    search(store, rid, run_id, "search:0", "openalex", "q1", [record("openalex", 1)])
    store.conn.execute("DELETE FROM candidate_hits")  # as a research searched before migration 0049 has none
    assert views.source_counts(store, run_id) == {"counted": False, "sources": []}
    other_rid, other_run = research(store)
    assert views.source_counts(store, other_run) is None  # searched nothing
