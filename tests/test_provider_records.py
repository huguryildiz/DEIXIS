"""Cross-provider records (DOI merge, suspected duplicates, candidate ranks) and per-provider query rules."""

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


def test_found_again_keeps_the_best_rank(store):
    rid, run_id = research(store)
    others = [record(f"W{i}", title=f"SYNTHETIC other record number {i}", doi=None) for i in range(3)]
    search(store, rid, run_id, 0, "openalex", [*others, record("W9")])
    search(store, rid, run_id, 1, "ieee_xplore", [record("123"), *others[:1]])
    ranks = {c["source_version_id"]: c["rank"] for c in store.candidates(rid)}
    assert ranks[store.find_source_by_identifier("doi", DOI)] == 0
    assert [c["rank"] for c in store.candidates(rid)] == sorted(ranks.values())  # candidates interleave by rank


def test_arxiv_doi_never_merges_and_a_preprint_naming_the_published_doi_joins_its_work(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "ieee_xplore", [record("123", title="Published title of the synthetic study")])
    preprint = record("2101.00001v1", title="Preprint title of the synthetic study", doi="10.48550/arxiv.2101.00001",
                      merge_by_doi=False, published_doi=DOI)
    search(store, rid, run_id, 1, "arxiv", [preprint])
    search(store, rid, run_id, 2, "openalex", [record("W5", title="Another record", doi="10.48550/arxiv.2101.00001")])
    published, arxiv_source = store.find_source_by_identifier("doi", DOI), store.find_source_by_identifier("arxiv", "2101.00001v1")
    unversioned = store.find_source_by_identifier("openalex", "W5")
    assert len({published, arxiv_source, unversioned}) == 3  # separate source versions, never merged
    assert store.source(published)["work_id"] == store.source(arxiv_source)["work_id"] == store.source(unversioned)["work_id"]
    assert store.suspected_duplicates(rid) == {} and store.work_heads(rid) == {store.source(published)["work_id"]: published}


def test_records_of_one_arxiv_preprint_are_versions_of_one_work_with_one_candidate(store):
    rid, run_id = research(store)
    arxiv_doi = "10.48550/arxiv.2101.00001"
    search(store, rid, run_id, 0, "openalex", [record("W5", doi=arxiv_doi)])
    search(store, rid, run_id, 1, "arxiv", [record("2101.00001v1", doi=arxiv_doi, merge_by_doi=False)])
    unversioned, arxiv_source = store.find_source_by_identifier("openalex", "W5"), store.find_source_by_identifier("arxiv", "2101.00001v1")
    assert unversioned != arxiv_source and store.source(unversioned)["work_id"] == store.source(arxiv_source)["work_id"]
    assert [c["source_version_id"] for c in store.candidates(rid)] == [unversioned]  # screened once, as the first found
    assert store.is_active_member(rid, arxiv_source) and store.suspected_duplicates(rid) == {}


def test_same_title_without_shared_doi_is_flagged_not_merged(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [record("W1", title="SYNTHETIC Release Scheduling: for diffusion channels", doi=None)])
    search(store, rid, run_id, 1, "serpapi", [record("r1", doi=None), record("r2", title="Short", doi=None)])
    first, second = store.find_source_by_identifier("openalex", "W1"), store.find_source_by_identifier("serpapi", "r1")
    assert first != second
    assert store.suspected_duplicates(rid)[first] == [{"source_version_id": second, "basis": "same_title"}]
    assert store.find_source_by_identifier("serpapi", "r2") not in store.suspected_duplicates(rid)


AUTHORS = ["Tu N. Nguyen", "Dung H. P. Nguyen", "Dang H. Pham", "Bing-Hong Liu"]
TITLE = "SYNTHETIC entanglement routing rate: approximation algorithms"


def preprint_record(record_id="2207.11821v1", authors=AUTHORS, title=TITLE):
    return replace(record(record_id, title=title, doi="10.48550/arxiv.2207.11821", merge_by_doi=False),
                   authors=authors, version_label="arXiv v1")


def published_record(record_id="W9", authors=AUTHORS, title=TITLE, doi=DOI):
    return replace(record(record_id, title=title, doi=doi), authors=authors)


def screen(store, rid, run_id, svid, proposal="include"):
    step = store.step(run_id, f"screening:{svid}", "model:screening")
    store.apply_screening_proposal(rid, svid, proposal, "SYNTHETIC reason", "title_and_abstract", step["id"])


def test_a_published_record_heads_the_work_of_its_screened_preprint(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "arxiv", [preprint_record()])
    preprint = store.find_source_by_identifier("arxiv", "2207.11821v1")
    screen(store, rid, run_id, preprint)
    search(store, rid, run_id, 1, "openalex", [published_record(authors=["T. N. Nguyen", "D. H. P. Nguyen", "D. H. Pham"])])
    published = store.find_source_by_identifier("openalex", "W9")
    wid = store.source(published)["work_id"]
    assert store.source(preprint)["work_id"] == wid and store.suspected_duplicates(rid) == {}
    assert store.work_heads(rid) == {wid: published} and store.included_works(rid) == [published]
    head = store.conn.execute("SELECT state, origin, proposal FROM selections WHERE source_version_id = ?", (published,)).fetchone()
    assert tuple(head) == ("included", "model_proposal", "include")  # taken from the screened preprint, not screened again


def test_a_preprint_found_after_its_published_record_follows_it(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [published_record()])
    published = store.find_source_by_identifier("openalex", "W9")
    screen(store, rid, run_id, published, "exclude")
    search(store, rid, run_id, 1, "arxiv", [preprint_record()])
    preprint = store.find_source_by_identifier("arxiv", "2207.11821v1")
    assert store.source(preprint)["work_id"] == store.source(published)["work_id"]
    assert set(store.work_heads(rid).values()) == {published} and store.included_works(rid) == []


@pytest.mark.parametrize("other", [
    published_record("W9", authors=["Alice Other", "Tu N. Nguyen"]),  # another first author
    published_record("W9", authors=["Tu N. Nguyen", "Xu Li", "Yan Zhao", "Ken Ito"]),  # too few shared authors
])
def test_same_title_without_matching_authors_stays_a_suspected_duplicate(store, other):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "arxiv", [preprint_record()])
    search(store, rid, run_id, 1, "openalex", [other])
    preprint, published = store.find_source_by_identifier("arxiv", "2207.11821v1"), store.find_source_by_identifier("openalex", "W9")
    assert store.source(preprint)["work_id"] != store.source(published)["work_id"]
    assert store.suspected_duplicates(rid)[preprint] == [{"source_version_id": published, "basis": "same_title"}]


def test_two_published_records_with_one_title_stay_separate_works(store):
    rid, run_id = research(store)
    search(store, rid, run_id, 0, "openalex", [published_record("W1", doi="10.1/conference")])
    search(store, rid, run_id, 1, "ieee_xplore", [published_record("123", doi="10.1/journal")])
    first, second = store.find_source_by_identifier("openalex", "W1"), store.find_source_by_identifier("ieee_xplore", "123")
    assert store.source(first)["work_id"] != store.source(second)["work_id"] and store.suspected_duplicates(rid)[first]


def test_flags_stored_before_d48_are_joined_at_startup(store, monkeypatch):
    from deixis.workflow import store as store_module

    rid, run_id = research(store)
    monkeypatch.setattr(store_module, "same_publication", lambda *args: False)  # linking as before D48
    search(store, rid, run_id, 0, "openalex", [published_record()])
    search(store, rid, run_id, 1, "arxiv", [preprint_record()])
    published, preprint = store.find_source_by_identifier("openalex", "W9"), store.find_source_by_identifier("arxiv", "2207.11821v1")
    screen(store, rid, run_id, published)
    screen(store, rid, run_id, preprint)
    assert store.suspected_duplicates(rid)
    monkeypatch.undo()
    assert store.link_published_versions() == 1 and store.link_published_versions() == 0
    assert store.source(preprint)["work_id"] == store.source(published)["work_id"] and store.suspected_duplicates(rid) == {}
    assert store.included_works(rid) == [published]  # the preprint's own earlier selection no longer counts


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


def _many_sources_store(pages_of_s2):
    abstracts = {f"s{n}": {"id": f"abstract-{n}", "source_version_id": f"s{n}", "kind": "abstract", "physical_page": None,
                           "text": f"SYNTHETIC abstract {n} about scheduling."} for n in range(1, 6)}

    class RetrievalStore:
        def latest_step_output(self, *_): return None
        def search_passages(self, svids, *_):
            return [p for p in pages_of_s2 if p["id"] == "fts" and p["source_version_id"] in svids]
        def passages_for(self, svid): return [abstracts[svid], *(pages_of_s2 if svid == "s2" else [])]
        def source(self, svid): return {"title": f"SYNTHETIC source {svid}"}
        def answer_order_facts(self, *_): return {f"s{n}": (True, 6 - n) for n in range(1, 6)}

    return RetrievalStore()


def test_answer_retrieval_gives_a_pdf_source_its_best_pages_when_sources_outnumber_the_passage_limit():
    from deixis.workflow.flow import ResearchFlow

    page = lambda pid, n, text: {"id": pid, "source_version_id": "s2", "asset_id": "asset", "kind": "pdf_page", "physical_page": n, "text": text}
    pages = [page("plain", 1, "SYNTHETIC introduction."), page("fts", 2, "SYNTHETIC scheduling scheduling results."),
             page("formulation", 3, "SYNTHETIC. Minimize delay subject to x ∈ {0,1} and x ≤ 1.")]
    flow = object.__new__(ResearchFlow)
    flow.store = _many_sources_store(pages)
    scope = {"question": "How is scheduling optimized?", "revision": 1}
    sources = [f"s{n}" for n in range(1, 6)]
    assert [p["id"] for p in flow._retrieve("research", scope, sources, 4)] == ["abstract-1", "abstract-2", "fts", "formulation"]
    # With room for every source, the selection is unchanged: every abstract first, then pages.
    assert [p["id"] for p in flow._retrieve("research", scope, sources, 8)][:5] == [f"abstract-{n}" for n in range(1, 6)]


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


def test_migration_joins_records_of_one_arxiv_preprint_found_before_d46(tmp_path, monkeypatch):
    import shutil

    from deixis.workflow import store as store_module
    from deixis.workflow.views import research_view

    real = db.MIGRATIONS_DIR
    old = tmp_path / "migrations"
    old.mkdir()
    for path in real.glob("*.sql"):
        # Today's code writes memberships with 0029's columns (D50), so that migration comes along.
        if int(path.name.split("_", 1)[0]) <= 25 or path.name.startswith("0029_"):
            shutil.copy(path, old / path.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", old)
    monkeypatch.setattr(store_module, "ARXIV_DOI_PREFIX", "not-linked-before-d46")
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    old_store = Store(conn)
    rid, run_id = research(old_store)
    arxiv_doi = "10.48550/arxiv.2101.00001"
    search(old_store, rid, run_id, 0, "arxiv", [record("2101.00001v1", doi=arxiv_doi, merge_by_doi=False)])
    search(old_store, rid, run_id, 1, "openalex", [record("W5", doi=arxiv_doi)])
    arxiv_source, unversioned = old_store.find_source_by_identifier("arxiv", "2101.00001v1"), old_store.find_source_by_identifier("openalex", "W5")
    assert len(old_store.candidates(rid)) == 2 and old_store.suspected_duplicates(rid)[arxiv_source]

    monkeypatch.undo()
    db.migrate(conn)
    new_store = Store(conn)
    assert new_store.source(unversioned)["work_id"] == new_store.source(arxiv_source)["work_id"]
    assert conn.execute("SELECT COUNT(*) FROM works").fetchone()[0] == 1 and new_store.suspected_duplicates(rid) == {}
    view = research_view(new_store, rid)
    assert [(s["source_version_id"], s["version_role"]) for s in view["sources"]] == [(arxiv_source, "record"), (unversioned, "other_version")]
    assert view["counts"]["unique"] == 1
    conn.close()
