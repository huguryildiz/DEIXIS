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
from deixis.providers.pacing import SerialRequestPacer

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


def test_the_batch_names_an_arxiv_record_by_its_arxiv_id_and_the_rest_by_doi():
    (answers, outcome), seen = s2([DOI, ARXIV_DOI], lambda r: httpx.Response(200, json=[paper(DOI), paper()]))
    body = json.loads(seen[0].content)
    assert seen[0].method == "POST" and str(seen[0].url).startswith(lookup.S2_BATCH_URL)
    assert body == {"ids": [f"DOI:{DOI}", "ARXIV:2601.00001"]}
    # The documentation is explicit that `fields` is a query parameter and not part of the body.
    assert seen[0].url.params["fields"] == lookup.S2_LOOKUP_FIELDS and "fields" not in body
    assert set(answers) == {DOI, ARXIV_DOI} and outcome.status == "completed"


def test_a_null_element_is_a_record_semantic_scholar_does_not_hold():
    (answers, _), _ = s2([DOI, OTHER_DOI], lambda r: httpx.Response(200, json=[None, paper(OTHER_DOI, ABSTRACT)]))
    assert answers[DOI].status == "not_found" and answers[DOI].abstract is None
    assert (answers[OTHER_DOI].status, answers[OTHER_DOI].abstract) == ("found", ABSTRACT)


def test_a_record_it_holds_without_an_abstract_is_found_with_no_abstract():
    """`found` and `not_found` are different answers: only `found` says the source was asked and had nothing to add."""
    (answers, _), _ = s2([DOI], lambda r: httpx.Response(200, json=[paper(DOI, None, references=182)]))
    assert (answers[DOI].status, answers[DOI].abstract, answers[DOI].reference_count) == ("found", None, 182)


def test_a_different_external_doi_is_a_link_and_the_same_one_is_not():
    (answers, _), _ = s2([ARXIV_DOI], lambda r: httpx.Response(200, json=[paper(DOI, paper_id="s2xyz")]))
    assert answers[ARXIV_DOI].linked_dois == [DOI] and answers[ARXIV_DOI].paper_id == "s2xyz"
    (same, _), _ = s2([DOI], lambda r: httpx.Response(200, json=[paper(DOI)]))
    assert same[DOI].linked_dois == []


def test_a_batch_that_is_rate_limited_on_every_attempt_leaves_every_record_failed():
    attempts = []

    def handler(request):
        attempts.append(request)
        return httpx.Response(429, text="SYNTHETIC rate limit")

    (answers, outcome), _ = s2([DOI, OTHER_DOI], handler)
    assert [a.status for a in answers.values()] == ["failed", "failed"]
    assert (outcome.status, outcome.retries, len(attempts)) == ("rate_limited", 2, 3)


def test_an_answer_of_another_length_is_not_attached_to_the_wrong_record():
    """A short or reordered list would put one record's abstract on another; the whole batch fails instead."""
    (answers, outcome), _ = s2([DOI, OTHER_DOI], lambda r: httpx.Response(200, json=[paper(DOI, ABSTRACT)]))
    assert [a.status for a in answers.values()] == ["failed", "failed"]
    assert outcome.status == "parse_error"


def test_the_batch_request_passes_through_the_shared_semantic_scholar_gate(monkeypatch):
    """D67: one process-wide gate over every api.semanticscholar.org request, batch lookups included."""
    import time
    monkeypatch.setattr(common, "SEMANTIC_SCHOLAR_PACER", SerialRequestPacer(0.06))
    starts = []

    async def handler(request):
        starts.append(time.monotonic())
        return httpx.Response(200, json=[paper(DOI)])

    async def go():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await asyncio.gather(lookup.semantic_scholar_batch(client, [DOI]),
                                        lookup.semantic_scholar_batch(client, [OTHER_DOI]))

    asyncio.run(go())
    assert len(starts) == 2 and starts[1] - starts[0] >= 0.055


def test_a_key_is_sent_as_a_header_and_never_in_the_description():
    secret = "SYNTHETIC-key"
    (_, outcome), seen = s2([DOI], lambda r: httpx.Response(200, json=[paper(DOI)]), api_key=secret)
    assert seen[0].headers["x-api-key"] == secret
    assert secret not in outcome.request_description and outcome.access_mode == "api_key"


# ---- Crossref --------------------------------------------------------------------------------


def test_the_doi_is_percent_encoded_into_the_path():
    (answer, _), seen = cr(DOI, lambda r: httpx.Response(200, json=work()))
    # The slash inside a DOI is part of the identifier, not another path segment, so it goes on the wire escaped.
    assert seen[0].url.raw_path.decode().startswith(f"/works/{DOI.replace('/', '%2F')}?")
    assert seen[0].url.params["mailto"] == "contact@example.org" and answer.status == "found"


def test_a_doi_crossref_does_not_register_is_not_found_rather_than_failed():
    (answer, outcome), _ = cr(DOI, lambda r: httpx.Response(404, text="Resource not found."))
    assert answer.status == "not_found" and outcome.http_status == 404
    assert outcome.status == "zero_results"


def test_a_server_error_is_a_failure_and_the_record_is_asked_again_another_day():
    (answer, outcome), _ = cr(DOI, lambda r: httpx.Response(500, text="SYNTHETIC outage"))
    assert answer.status == "failed" and outcome.status == "failed"


def test_jats_markup_is_stripped_from_the_abstract():
    payload = work(abstract="<jats:title>Abstract</jats:title><jats:p>We schedule release&amp;times.</jats:p>")
    (answer, _), _ = cr(DOI, lambda r: httpx.Response(200, json=payload))
    assert answer.abstract == "We schedule release&times."
    assert answer.abstract == crossref.strip_markup(payload["message"]["abstract"])


def test_both_directions_of_the_preprint_relation_are_read_apart():
    payload = work(**{"reference-count": 182, "relation": {
        lookup.IS_PREPRINT_OF: [{"id": OTHER_DOI, "id-type": "doi", "asserted-by": "subject"}],
        lookup.HAS_PREPRINT: [{"id": ARXIV_DOI, "id-type": "doi", "asserted-by": "subject"}]}})
    (answer, _), _ = cr(DOI, lambda r: httpx.Response(200, json=payload))
    assert answer.linked_dois == [OTHER_DOI] and answer.has_preprint == [ARXIV_DOI]
    assert answer.reference_count == 182


def test_a_relation_that_names_something_other_than_a_doi_is_left_alone():
    payload = work(relation={lookup.IS_PREPRINT_OF: [{"id": "arXiv:2601.00001", "id-type": "arxiv",
                                                      "asserted-by": "subject"}]})
    (answer, _), _ = cr(DOI, lambda r: httpx.Response(200, json=payload))
    assert answer.linked_dois == []


def test_a_work_with_no_relation_and_no_abstract_is_found_and_empty():
    (answer, _), _ = cr(DOI, lambda r: httpx.Response(200, json=work()))
    assert (answer.status, answer.abstract, answer.linked_dois, answer.reference_count) == ("found", None, [], None)


# ---- what the library keeps of an answer ---------------------------------------------------


@pytest.fixture
def store(tmp_path):
    from deixis.storage import db
    from deixis.workflow.store import Store
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
    from deixis.workflow import lookups
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


def test_a_crossref_abstract_carries_its_own_origin(store):
    from deixis.workflow import lookups
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [provider_record()])
    svid = store.find_source_by_identifier("openalex", "W1")
    lookups.store_answer(store, svid, "crossref", lookup.LookupAnswer("found", abstract=ABSTRACT), "stp_2", None)
    assert abstract_of(store, svid)["abstract_origin"] == "lookup_crossref_jats"


def test_an_abstract_the_record_already_has_is_not_written_over(store):
    from deixis.workflow import lookups
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [provider_record(abstract=ABSTRACT)])
    svid = store.find_source_by_identifier("openalex", "W1")
    added = lookups.store_answer(store, svid, "crossref", lookup.LookupAnswer("found", abstract="SYNTHETIC other"),
                                 "stp_2", None)
    assert added["abstracts_filled"] == 0 and abstract_of(store, svid)["text"] == ABSTRACT


def test_a_source_that_already_answered_is_not_written_again_and_a_failed_row_is(store):
    """A second discovery run must not turn a `found` row into a `not_found` one, but may retry a failure."""
    from deixis.workflow import lookups
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [provider_record()])
    svid = store.find_source_by_identifier("openalex", "W1")
    lookups.store_answer(store, svid, "crossref", lookup.LookupAnswer("failed"), "stp_1", None)
    assert lookups.answered(store, svid, "crossref") is False
    lookups.store_answer(store, svid, "crossref", lookup.LookupAnswer("not_found"), "stp_2", None)
    assert lookups.answered(store, svid, "crossref") is True
    lookups.store_answer(store, svid, "crossref", lookup.LookupAnswer("found", abstract=ABSTRACT), "stp_3", None)
    assert abstract_of(store, svid) is None  # the source had already answered; it is not asked or written again
    assert [(r["status"], r["step_id"]) for r in lookup_rows(store, svid)] == [("not_found", "stp_2")]


def test_a_linked_doi_is_stored_under_its_own_scheme_and_not_as_a_published_doi(store):
    """`legacy` reads `published_doi`; an external link must not reach it (D48)."""
    from deixis.workflow import lookups
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "arxiv", [provider_record("A1", doi=ARXIV_DOI, merge_by_doi=False,
                                                            version_label="submittedVersion")])
    svid = store.find_source_by_identifier("arxiv", "A1")
    added = lookups.store_answer(store, svid, "semantic_scholar",
                                 lookup.LookupAnswer("found", linked_dois=[DOI]), "stp_1", None)
    assert added["links"] == 1
    schemes = {r[0]: r[1] for r in store.conn.execute(
        "SELECT scheme, value FROM identifier_mappings WHERE source_version_id = ? AND scheme LIKE '%doi%'", (svid,))}
    assert schemes.get("linked_doi") == DOI and "published_doi" not in schemes
    assert lookups.linked_dois(store, svid) == [DOI]


def test_the_other_direction_of_the_crossref_relation_is_written_onto_the_preprint(store):
    from deixis.workflow import lookups
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [provider_record()])
    search(store, rid, run_id, 1, "arxiv", [provider_record("A1", doi=ARXIV_DOI, merge_by_doi=False,
                                                            version_label="submittedVersion")])
    published = store.find_source_by_identifier("openalex", "W1")
    pre = store.find_source_by_identifier("arxiv", "A1")
    # arXiv DOIs never merge by DOI, so the preprint keeps its own `doi` mapping for the lookup to find.
    store.conn.execute("INSERT OR IGNORE INTO identifier_mappings (source_version_id, scheme, value, provider,"
                       " retrieved_at) VALUES (?, 'doi', ?, 'arxiv', '2026-09-21T00:00:00.000+00:00')",
                       (pre, ARXIV_DOI))
    lookups.store_answer(store, published, "crossref", lookup.LookupAnswer("found", has_preprint=[ARXIV_DOI]),
                         "stp_1", None)
    assert lookups.linked_dois(store, pre) == [DOI]  # the link is written where the preprint can name it


def test_a_reference_count_is_filled_once_and_never_written_over(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [provider_record(reference_count=182)])
    svid = store.find_source_by_identifier("openalex", "W1")
    assert store.source(svid)["reference_count"] == 182
    search(store, rid, run_id, 1, "crossref", [provider_record("C1", reference_count=17)])
    assert store.source(svid)["reference_count"] == 182  # the same DOI, a second provider: the first count stands


def test_a_count_that_arrives_later_fills_an_empty_column(store):
    from deixis.workflow import lookups
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [provider_record()])
    svid = store.find_source_by_identifier("openalex", "W1")
    assert store.source(svid)["reference_count"] is None
    lookups.store_answer(store, svid, "crossref", lookup.LookupAnswer("found", reference_count=150), "stp_1", None)
    assert store.source(svid)["reference_count"] == 150


# ---- planning who is asked ------------------------------------------------------------------


SURVEY_TITLE = "A SYNTHETIC survey of release scheduling for diffusion channels"


def plan(store, rid, providers=("openalex", "semantic_scholar", "crossref"), limit=None):
    from deixis.domain.survey_words import STRONG_TITLE_WORDS
    from deixis.workflow import lookups
    scope = {"providers": list(providers)}
    kwargs = {} if limit is None else {"limit": limit}
    return lookups.plan_semantic_scholar(store, rid, 1, scope, STRONG_TITLE_WORDS, **kwargs)


def planned(store, plan_output):
    return [row["doi"] for batch in plan_output["batches"] for row in batch]


def test_a_record_without_an_abstract_is_asked_about_and_one_with_an_abstract_is_not(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [provider_record("W1"),
                                               provider_record("W2", doi=OTHER_DOI, abstract=ABSTRACT)])
    assert planned(store, plan(store, rid)) == [DOI]


def test_a_record_whose_title_already_names_a_survey_is_not_asked_for_an_abstract(store):
    """It leaves the screening list anyway, so its missing abstract is not worth a request."""
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [provider_record("W1", title=SURVEY_TITLE)])
    assert planned(store, plan(store, rid)) == []


def test_a_record_without_a_doi_is_not_asked_about(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [provider_record("W1", doi=None)])
    assert planned(store, plan(store, rid)) == []


def test_a_preprint_is_asked_about_for_its_links_even_when_it_has_an_abstract(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "arxiv", [provider_record("A1", doi=ARXIV_DOI, abstract=ABSTRACT,
                                                            merge_by_doi=False, version_label="submittedVersion")])
    output = plan(store, rid)
    assert planned(store, output) == [ARXIV_DOI]
    assert output["batches"][0][0]["reason"] == "link"


def test_a_record_a_source_already_answered_about_is_left_out_of_the_next_plan(store):
    from deixis.workflow import lookups
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [provider_record("W1"), provider_record("W2", doi=OTHER_DOI)])
    first = store.find_source_by_identifier("openalex", "W1")
    lookups.store_answer(store, first, "semantic_scholar", lookup.LookupAnswer("not_found"), "stp_1", None)
    assert planned(store, plan(store, rid)) == [OTHER_DOI]


def test_a_record_a_source_failed_on_is_asked_again_by_a_later_run(store):
    from deixis.workflow import lookups
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [provider_record("W1")])
    svid = store.find_source_by_identifier("openalex", "W1")
    lookups.store_answer(store, svid, "semantic_scholar", lookup.LookupAnswer("failed"), "stp_1", None)
    assert planned(store, plan(store, rid)) == [DOI]


def test_a_source_outside_the_researchs_scope_is_planned_no_request_at_all(store):
    rid, run_id = research(store, providers=("openalex",))
    search(store, rid, run_id, 0, "openalex", [provider_record("W1")])
    output = plan(store, rid, providers=("openalex",))
    assert output == {"batches": [], "outside_limit": 0, "skipped": "out_of_scope"}


def test_records_beyond_the_request_limit_are_counted_and_left_for_a_later_run(store, monkeypatch):
    from deixis.domain.survey_words import STRONG_TITLE_WORDS
    from deixis.workflow import lookups
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex",
           [provider_record(f"W{i}", doi=f"10.1/synth.{i}") for i in range(5)])
    monkeypatch.setattr(lookup, "S2_LOOKUP_BATCH", 2)
    output = lookups.plan_semantic_scholar(store, rid, 1, {"providers": ["semantic_scholar"]},
                                           STRONG_TITLE_WORDS, limit=2)
    assert [len(batch) for batch in output["batches"]] == [2, 2] and output["outside_limit"] == 1


def test_crossref_is_planned_only_for_records_still_without_an_abstract(store):
    from deixis.domain.survey_words import STRONG_TITLE_WORDS
    from deixis.workflow import lookups
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [provider_record("W1"), provider_record("W2", doi=OTHER_DOI)])
    first = store.find_source_by_identifier("openalex", "W1")
    lookups.store_answer(store, first, "semantic_scholar", lookup.LookupAnswer("found", abstract=ABSTRACT),
                         "stp_1", None)
    output = lookups.plan_crossref(store, rid, 1, {"providers": ["semantic_scholar", "crossref"]},
                                   STRONG_TITLE_WORDS, spent=1)
    assert [row["doi"] for chunk in output["chunks"] for row in chunk] == [OTHER_DOI]


def test_the_crossref_allowance_is_what_the_first_source_left(store):
    from deixis.domain.survey_words import STRONG_TITLE_WORDS
    from deixis.workflow import lookups
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex",
           [provider_record(f"W{i}", doi=f"10.1/synth.{i}") for i in range(4)])
    output = lookups.plan_crossref(store, rid, 1, {"providers": ["crossref"]}, STRONG_TITLE_WORDS, spent=1, limit=3)
    assert sum(len(chunk) for chunk in output["chunks"]) == 2 and output["outside_limit"] == 2


# ---- deleting -------------------------------------------------------------------------------


def test_purging_a_research_clears_its_flags_and_the_lookups_of_its_records(store):
    from deixis.workflow import lookups
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [provider_record("W1")])
    svid = store.find_source_by_identifier("openalex", "W1")
    lookups.store_answer(store, svid, "crossref", lookup.LookupAnswer("not_found"), "stp_1", None)
    store.conn.execute("INSERT INTO record_flags (research_id, scope_revision, source_version_id, flag, evidence,"
                       " created_at) VALUES (?, 1, ?, 'survey_title_word', 'survey', '2026-09-21T00:00:00.000+00:00')",
                       (rid, svid))
    store.update_run(run_id, status="completed")
    store.trash_research(rid)
    store.purge_research(rid)
    assert store.conn.execute("SELECT COUNT(*) FROM record_flags").fetchone()[0] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM record_lookups").fetchone()[0] == 0


# ---- the reference list a record's own bibliography names (slice 07) -------------------------


def reference_rows(store, source_version_id):
    return [r[0] for r in store.conn.execute(
        "SELECT referenced_id FROM record_references WHERE source_version_id = ? ORDER BY referenced_id",
        (source_version_id,))]


def references_read(store, source_version_id):
    return store.conn.execute("SELECT references_read FROM source_versions WHERE id = ?",
                              (source_version_id,)).fetchone()[0]


def test_a_read_list_an_empty_list_and_an_unasked_one_are_three_different_records(store):
    """"Read and empty" is not "not read": both have no graph signal, but only one of them was asked (SW7.4)."""
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [
        provider_record("W1", doi="10.1/one", references=("W7", "W8")),
        provider_record("W2", doi="10.1/two", references=()),
        provider_record("W3", doi="10.1/three", references=None),
    ])
    listed, empty, unasked = (store.find_source_by_identifier("openalex", f"W{i}") for i in (1, 2, 3))
    assert (reference_rows(store, listed), references_read(store, listed)) == (["W7", "W8"], 1)
    assert (reference_rows(store, empty), references_read(store, empty)) == ([], 1)
    assert (reference_rows(store, unasked), references_read(store, unasked)) == ([], 0)


def test_the_same_record_found_again_does_not_multiply_its_references(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [provider_record("W1", references=("W7", "W8"))])
    svid = store.find_source_by_identifier("openalex", "W1")
    search(store, rid, run_id, 1, "openalex", [provider_record("W1", references=("W8", "W9"))])
    assert reference_rows(store, svid) == ["W7", "W8", "W9"]  # a second read adds what it names, nothing twice


def test_a_second_provider_that_names_no_list_does_not_unread_the_first_one(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [provider_record("W1", references=("W7",))])
    svid = store.find_source_by_identifier("openalex", "W1")
    search(store, rid, run_id, 1, "crossref", [provider_record("C1", references=None)])
    assert (reference_rows(store, svid), references_read(store, svid)) == (["W7"], 1)


def test_purging_a_source_takes_its_reference_rows(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [
        provider_record("W1", doi="10.1/one", references=("W7",)),
        provider_record("W2", doi="10.1/two", references=("W8",)),
    ])
    gone = store.find_source_by_identifier("openalex", "W1")
    kept = store.find_source_by_identifier("openalex", "W2")
    store.update_run(run_id, status="cancelled")
    store.remove_sources(rid, [gone], None)
    assert store.purge_sources(rid, [gone])[0] == [gone]
    assert reference_rows(store, gone) == [] and reference_rows(store, kept) == ["W8"]
