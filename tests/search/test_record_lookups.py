"""Asking a second source about a record by DOI: the two clients, and what the library keeps of their answers.

No network: the answers are SYNTHETIC and shaped after the provider documentation read on 2026-09-21. Passing shows
that the clients read an answer the way the documentation describes it and that the library records it once, not
that either source holds anything or fills any particular share of the missing abstracts.
"""

import asyncio
import json

import httpx
import pytest

from deixis.providers import common, crossref, lookup

DOI = "10.1109/synth.2026.1"
OTHER_DOI = "10.1145/synth.2026.9"
ARXIV_DOI = "10.48550/arxiv.2601.00001"
ABSTRACT = "We schedule SYNTHETIC molecule releases and report the packet size that minimises the error rate."


@pytest.fixture(autouse=True)
def no_waits(monkeypatch):
    sleeps = []

    async def instant(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(common.asyncio, "sleep", instant)
    monkeypatch.setattr(common.SEMANTIC_SCHOLAR_PACER, "interval_seconds", 0.0)
    return sleeps


def s2(dois, handler, api_key=None):
    seen = []

    def record(request):
        seen.append(request)
        return handler(request)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(record)) as client:
            return await lookup.semantic_scholar_batch(client, dois, api_key)
    return asyncio.run(go()), seen


def cr(doi, handler, contact_email="contact@example.org"):
    seen = []

    def record(request):
        seen.append(request)
        return handler(request)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(record)) as client:
            return await lookup.crossref_work(client, doi, contact_email)
    return asyncio.run(go()), seen


def paper(doi=None, abstract=None, references=None, paper_id="s2abc"):
    external = {"DOI": doi} if doi else {}
    return {"paperId": paper_id, "externalIds": external, "abstract": abstract, "referenceCount": references}


def work(**fields):
    return {"status": "ok", "message-type": "work", "message": {"DOI": DOI, **fields}}


# ---- the clients: Semantic Scholar ------------------------------------------------------------------------


def test_a_key_is_sent_as_a_header_and_never_in_the_description():
    secret = "SYNTHETIC-key"
    (_, outcome), seen = s2([DOI], lambda r: httpx.Response(200, json=[paper(DOI)]), api_key=secret)
    assert seen[0].headers["x-api-key"] == secret
    assert secret not in outcome.request_description and outcome.access_mode == "api_key"


# ---- Crossref --------------------------------------------------------------------------------


# ---- what the library keeps of an answer ---------------------------------------------------


@pytest.fixture
def store(tmp_path):
    from deixis.storage import db
    from deixis.workflow.run.store import Store
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    yield Store(connection)
    connection.close()


def provider_record(record_id="W1", doi=DOI, title="SYNTHETIC release scheduling for diffusion channels",
                    abstract=None, reference_count=None, version_label="publishedVersion", merge_by_doi=True,
                    references=None, **identifiers):
    from deixis.providers.common import ProviderRecord
    return ProviderRecord(
        provider_record_id=record_id, title=title, authors=["Aydin, Mert"], year=2026, venue=None,
        publication_type=None, doi=doi, landing_url=None, oa_pdf_url=None, oa_pdf_version=None,
        version_label=version_label, abstract=abstract, abstract_origin="provider" if abstract else None,
        identifiers=identifiers, raw={}, reference_count=reference_count, merge_by_doi=merge_by_doi,
        references=references)


def research(store, providers=("openalex", "semantic_scholar", "crossref"), workflow="sw"):
    rid = store.create_research("SYNTHETIC question?", "academic", "standard", list(providers), "fake", "m", "en",
                                search_workflow=workflow)
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
    return step


def lookup_rows(store, source_version_id):
    return [dict(r) for r in store.conn.execute(
        "SELECT * FROM record_lookups WHERE source_version_id = ? ORDER BY provider", (source_version_id,))]


def abstract_of(store, source_version_id):
    row = store.conn.execute(
        "SELECT text, abstract_origin, payload_ref FROM passages WHERE source_version_id = ? AND kind = 'abstract'",
        (source_version_id,)).fetchone()
    return None if row is None else dict(row)


def test_a_found_answer_with_an_abstract_is_stored_with_its_origin_and_its_payload(store):
    from deixis.workflow.search import lookups
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [provider_record()])
    svid = store.find_source_by_identifier("openalex", "W1")
    added = lookups.store_answer(store, svid, "semantic_scholar", lookup.LookupAnswer("found", abstract=ABSTRACT),
                                 "stp_1", "stp_1.json")
    assert added == {"found": 1, "abstracts_filled": 1, "links": 0, "failed": 0}
    assert abstract_of(store, svid) == {"text": ABSTRACT, "abstract_origin": "lookup_semantic_scholar",
                                        "payload_ref": "stp_1.json"}
    assert [(r["provider"], r["status"], r["had_abstract"]) for r in lookup_rows(store, svid)] == [
        ("semantic_scholar", "found", 1)]


def test_an_abstract_the_record_already_has_is_not_written_over(store):
    from deixis.workflow.search import lookups
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [provider_record(abstract=ABSTRACT)])
    svid = store.find_source_by_identifier("openalex", "W1")
    added = lookups.store_answer(store, svid, "crossref", lookup.LookupAnswer("found", abstract="SYNTHETIC other"),
                                 "stp_2", None)
    assert added["abstracts_filled"] == 0 and abstract_of(store, svid)["text"] == ABSTRACT


# ---- planning who is asked ------------------------------------------------------------------


SURVEY_TITLE = "A SYNTHETIC survey of release scheduling for diffusion channels"


def plan(store, rid, providers=("openalex", "semantic_scholar", "crossref"), limit=None):
    from deixis.domain.survey_words import STRONG_TITLE_WORDS
    from deixis.workflow.search import lookups
    scope = {"providers": list(providers)}
    kwargs = {} if limit is None else {"limit": limit}
    return lookups.plan_semantic_scholar(store, rid, 1, scope, STRONG_TITLE_WORDS, **kwargs)


def planned(store, plan_output):
    return [row["doi"] for batch in plan_output["batches"] for row in batch]


# ---- deleting -------------------------------------------------------------------------------


# ---- the reference list a record's own bibliography names (slice 07) -------------------------


def references_read(store, source_version_id):
    return store.conn.execute("SELECT references_read FROM source_versions WHERE id = ?",
                              (source_version_id,)).fetchone()[0]


# ---- slice 13g Task 4: the Scopus client (D91) ------------------------------------------------------------------
# Answers shaped after `providers/scopus.py`'s notes: an entry list under `search-results`, the abstract as
# `dc:description` in the complete view, an empty set as one entry holding `error`, 401 without entitlement.


def scopus(handler):
    seen = []

    def record(request):
        seen.append(request)
        return handler(request)

    async def ask():
        async with httpx.AsyncClient(transport=httpx.MockTransport(record)) as client:
            return await lookup.scopus_abstract(client, DOI, "SYNTHETIC-scopus-key")
    return (*asyncio.run(ask()), seen)


def test_a_scopus_answer_that_names_another_doi_is_not_taken_as_the_abstract():
    """Review of 13g (2026-09-23): the abstract is written to the record that was asked about, so an entry naming
    another DOI must not fill it."""
    answer, outcome, _ = scopus(lambda request: httpx.Response(200, json={"search-results": {
        "opensearch:totalResults": "1", "entry": [{"prism:doi": "10.9/another", "dc:description": ABSTRACT}]}}))
    assert (answer.status, answer.abstract) == ("not_found", None)
    assert "another" in (outcome.error or "")
    same, _, _ = scopus(lambda request: httpx.Response(200, json={"search-results": {
        "opensearch:totalResults": "2", "entry": [{"prism:doi": "10.9/another", "dc:description": "SYNTHETIC other"},
                                                  {"prism:doi": DOI.upper(), "dc:description": ABSTRACT}]}}))
    assert (same.status, same.abstract) == ("found", ABSTRACT)


# ---- Scopus in batches: one OR query for up to 25 DOIs (live probe 4 Oct 2026, see providers/lookup.py) -----------


