"""Cross-provider records (DOI merge, suspected duplicates, candidate ranks) and per-provider query rules."""

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


def test_found_again_keeps_the_best_rank(store):
    rid, run_id = research(store)
    others = [record(f"W{i}", title=f"SYNTHETIC other record number {i}", doi=None) for i in range(3)]
    search(store, rid, run_id, 0, "openalex", [*others, record("W9")])
    search(store, rid, run_id, 1, "ieee_xplore", [record("123"), *others[:1]])
    ranks = {c["source_version_id"]: c["rank"] for c in store.candidates(rid)}
    assert ranks[store.find_source_by_identifier("doi", DOI)] == 0
    assert [c["rank"] for c in store.candidates(rid)] == sorted(ranks.values())  # candidates interleave by rank


def test_arxiv_doi_never_merges_and_published_doi_flags_a_suspected_duplicate(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "ieee_xplore", [record("123", title="Published title of the synthetic study")])
    preprint = record("2101.00001v1", title="Preprint title of the synthetic study", doi="10.48550/arxiv.2101.00001",
                      merge_by_doi=False, published_doi=DOI)
    search(store, rid, run_id, 1, "arxiv", [preprint])
    search(store, rid, run_id, 2, "openalex", [record("W5", title="Another record", doi="10.48550/arxiv.2101.00001")])
    published, arxiv_source = store.find_source_by_identifier("doi", DOI), store.find_source_by_identifier("arxiv", "2101.00001v1")
    assert published != arxiv_source and len(store.candidates(rid)) == 3
    assert store.suspected_duplicates(rid)[arxiv_source] == [{"source_version_id": published, "basis": "published_doi"}]
    assert store.find_source_by_identifier("openalex", "W5") != arxiv_source


def test_same_title_without_shared_doi_is_flagged_not_merged(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [record("W1", title="SYNTHETIC Release Scheduling: for diffusion channels", doi=None)])
    search(store, rid, run_id, 1, "serpapi", [record("r1", doi=None), record("r2", title="Short", doi=None)])
    first, second = store.find_source_by_identifier("openalex", "W1"), store.find_source_by_identifier("serpapi", "r1")
    assert first != second
    assert store.suspected_duplicates(rid)[first] == [{"source_version_id": second, "basis": "same_title"}]
    assert store.find_source_by_identifier("serpapi", "r2") not in store.suspected_duplicates(rid)


def test_answer_order_facts_count_providers_and_user_choices(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [record("W1", title="SYNTHETIC first record title", doi="10.1/one"),
                                               record("W3", title="SYNTHETIC third record title", doi="10.1/three")])
    search(store, rid, run_id, 1, "ieee_xplore", [record("9", title="SYNTHETIC first record title", doi="10.1/one")])
    search(store, rid, run_id, 2, "biorxiv", [record("W3", title="SYNTHETIC third record title", doi="10.1/three")])
    upload = store.create_upload_source("SYNTHETIC uploaded file")
    store.add_to_corpus(rid, upload, "user_upload", selection_state="included", selection_origin="user")
    first, third = store.find_source_by_identifier("doi", "10.1/one"), store.find_source_by_identifier("doi", "10.1/three")
    facts = store.answer_order_facts(rid, [first, third, upload])
    assert facts == {first: (False, 2), third: (False, 1), upload: (True, 0)}  # bioRxiv through OpenAlex is one provider


def test_answer_order_puts_user_choices_then_more_providers_then_text_match_first():
    from deixis.workflow.flow import answer_source_order

    included = ["a", "b", "c", "d", "e"]
    facts = {"a": (False, 1), "b": (False, 2), "c": (False, 1), "d": (True, 0), "e": (False, 1)}
    texts = {"a": "unrelated words about hospitals", "c": "release scheduling optimization for release scheduling", "e": "scheduling"}
    assert answer_source_order(included, facts, texts, ["scheduling", "optimization"]) == ["d", "b", "c", "e", "a"]


def test_formulation_score_ranks_explicit_model_text_above_narrative_text():
    from deixis.workflow.flow import formulation_score

    formulation = "SYNTHETIC. We minimize total delay subject to x ∈ {0,1} and the constraint x ≤ 1."
    narrative = "SYNTHETIC. The study discusses scheduling results and reports a simulation."
    assert formulation_score(formulation) > formulation_score(narrative)
    assert formulation_score("SYNTHETIC. The word st alone is not an optimization abbreviation.") == 0


def test_answer_retrieval_places_a_formulation_page_before_a_better_fts_match():
    from deixis.workflow.flow import ResearchFlow

    abstract = {"id": "abstract", "source_version_id": "source", "kind": "abstract", "physical_page": None,
                "text": "SYNTHETIC. An abstract about scheduling."}
    formulation = {"id": "formulation", "source_version_id": "source", "kind": "pdf_page", "physical_page": 4,
                   "text": "SYNTHETIC. Minimize delay subject to x ∈ {0,1} and x ≤ 1."}
    fts_match = {"id": "fts", "source_version_id": "source", "kind": "pdf_page", "physical_page": 2,
                 "text": "SYNTHETIC. Scheduling scheduling scheduling results."}

    class RetrievalStore:
        def latest_step_output(self, *_): return None
        def search_passages(self, *_): return [fts_match]
        def passages_for(self, *_): return [abstract, fts_match, formulation]
        def source(self, *_): return {"title": "SYNTHETIC scheduling source"}
        def answer_order_facts(self, *_): return {"source": (True, 1)}

    flow = object.__new__(ResearchFlow)
    flow.store = RetrievalStore()
    passages = flow._retrieve("research", {"question": "How is scheduling optimized?", "revision": 1}, ["source"], 4)
    assert [p["id"] for p in passages] == ["abstract", "formulation", "fts"]


def test_short_attached_pdf_supplies_later_pages_without_the_multi_source_cap():
    from deixis.workflow.flow import ResearchFlow

    pages = [{"id": f"page-{page}-chunk-{chunk}", "source_version_id": "source", "asset_id": "asset", "kind": "pdf_page",
              "physical_page": page, "text": f"SYNTHETIC page {page} chunk {chunk} about packet size and power."}
             for page in range(1, 11) for chunk in range(4)]

    class RetrievalStore:
        def passages_for(self, *_): return pages
        def asset(self, *_): return {"page_count": 10}

    flow = object.__new__(ResearchFlow)
    flow.store = RetrievalStore()
    selected = flow._retrieve("research", {"question": "How are packet size and power chosen?", "revision": 1,
                                            "source_scope": "attached"}, ["source"], 48)
    assert len(selected) == 40
    assert {p["physical_page"] for p in selected} == set(range(1, 11))
    assert [p["id"] for p in selected if p["physical_page"] == 5] == [f"page-5-chunk-{n}" for n in range(4)]


@pytest.mark.parametrize(("page_count", "chunk_count"), [(49, 49), (400, 10)])
def test_large_attached_pdf_keeps_bounded_passage_selection(page_count, chunk_count):
    from deixis.workflow.flow import MAX_PASSAGES_PER_SOURCE, ResearchFlow

    pages = [{"id": f"page-{n}", "source_version_id": "source", "asset_id": "asset", "kind": "pdf_page", "physical_page": n,
              "text": f"SYNTHETIC scheduling evidence on page {n}."} for n in range(1, chunk_count + 1)]

    class RetrievalStore:
        def passages_for(self, *_): return pages
        def asset(self, *_): return {"page_count": page_count}
        def latest_step_output(self, *_): return None
        def search_passages(self, *_): return pages
        def source(self, *_): return {"title": "SYNTHETIC scheduling source"}
        def answer_order_facts(self, *_): return {"source": (True, 0)}

    flow = object.__new__(ResearchFlow)
    flow.store = RetrievalStore()
    selected = flow._retrieve("research", {"question": "How is scheduling optimized?", "revision": 1,
                                            "source_scope": "attached"}, ["source"], 48)
    assert len(selected) == MAX_PASSAGES_PER_SOURCE


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
    ("scopus", 'TITLE-ABS-KEY("molecular communication" AND optimization OR scheduling)'),
    ("scopus", 'TITLE-ABS-KEY(molecular communication resource allocation)'),
    ("ieee_xplore", '"molecular communication" AND (scheduling'),
    ("ieee_xplore", "molecular communication resource allocation"),
    ("biorxiv", '"quorum sensing" AND optimization OR control'),
    ("arxiv", 'abs:molecular communication'),
    ("arxiv", '"molecular communication" AND abs:optimization'),
    ("arxiv", 'abs:"molecular communication" NOT abs:survey'),
    ("arxiv", 'abs:"molecular communication" (abs:scheduling OR abs:allocation)'),
    ("semantic_scholar", '"molecular communication" AND scheduling'),
    ("crossref", "molecular communication resource allocation scheduling routing optimization energy delay"),
    ("serpapi", '"molecular communication" AND (scheduling OR routing)'),
    ("core", '"molecular communication" AND (scheduling'),
    ("core", '"molecular communication" OR "nano network"'),
    ("core", 'title:"molecular communication" AND scheduling'),
    ("core", "molecular communication resource allocation"),
])
def test_malformed_queries_are_refused(provider, query):
    assert query_rules.query_issues(provider, query)
