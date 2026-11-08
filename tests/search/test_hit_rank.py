"""Where each record stood in each query that found it, and who may read that record.

The place and the provider's score are an audit record: this file holds the writing test and the guard that no gate,
threshold or screening path reads either. SYNTHETIC libraries; no live app, provider or model.
"""

import tempfile
from pathlib import Path

import pytest

from dataclasses import replace

from deixis.providers import facade, pubmed, registry, scopus
from deixis.providers.common import ProviderRecord, SearchOutcome
from deixis.storage import db
from deixis.workflow.run.store import Store

ROOT = Path(__file__).resolve().parents[2]
# The hit column's name; a module could only use the stored score by naming it.
COLUMN = "raw_score"
# The record field the score travels on, and the select field the request asks for.
FIELD = "relevance_score"
# The only files that may name either: the request that asks for the score, the record that carries it, the write that
# stores it, and the schema. A read anywhere else would put the score into a decision.
SCORE_READERS = {"deixis/providers/openalex.py", "deixis/providers/common.py", "deixis/workflow/run/store.py",
                 "deixis/storage/schema.sql", "deixis/storage/upgrades.py"}


def record(identity, score=None):
    return ProviderRecord(provider_record_id=identity, title=f"SYNTHETIC {identity}", authors=[], year=2026,
                          venue=None, publication_type=None, doi=f"10.0000/{identity.lower()}", landing_url=None,
                          oa_pdf_url=None, oa_pdf_version=None, version_label="publishedVersion",
                          abstract=f"SYNTHETIC abstract {identity}", abstract_origin="provider", identifiers={},
                          raw={"id": identity}, relevance_score=score)


def library(directory):
    conn = db.connect(Path(directory) / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC question?", "academic", "quick", ["openalex"], "fake", "fake-model", None)
    run = store.create_run(rid, "discovery", {"max_model_calls": 1, "max_provider_requests": 2, "max_candidates": 50,
                                              "max_answer_passages": 8}, None)
    return conn, store, rid, run


def search(store, rid, run, key, records, sort=None, first_rank=0):
    """One answered query: its `search_runs` row with the sorting setting it carried, and its records in order."""
    step = store.step(run["id"], key, "provider_search:openalex")
    fields = dict(research_id=rid, run_id=run["id"], step_id=step["id"], scope_revision=1, provider="openalex",
                  query_text=key, request_description="GET SYNTHETIC", access_mode="keyless", status="completed",
                  delivery_class=None, result_count=len(records), provider_total=len(records), page_limit=25,
                  error_json=None, raw_payload_path=None, sort=sort)
    return store.record_search(fields, "openalex", records, None, step["id"], "succeeded",
                               step_output={"status": "completed"}, first_rank=first_rank)


def test_every_query_keeps_its_own_place_and_score_and_the_candidate_keeps_only_the_best_place():
    with tempfile.TemporaryDirectory() as directory:
        conn, store, rid, run = library(directory)
        # Two queries over an overlapping set. W2 is third in the first query and first in the second, so before the
        # two new columns its second place was lost: `candidates.rank` keeps the best place alone.
        first = search(store, rid, run, "search:0", [record("W1", 92.5), record("W9", 71.0), record("W2", 30.25)])
        second = search(store, rid, run, "search:1", [record("W2", 88.0), record("W1", 12.5)], sort="cited_by_count:desc")

        hits = {(r["search_run_id"], r["source_version_id"]): r for r in conn.execute(
            "SELECT * FROM candidate_hits WHERE research_id = ?", (rid,))}
        svid = {name: store.find_source_by_identifier("openalex", name) for name in ("W1", "W2", "W9")}
        assert [(hits[(first, svid[n])]["rank"], hits[(first, svid[n])]["raw_score"]) for n in ("W1", "W9", "W2")] == \
               [(0, 92.5), (1, 71.0), (2, 30.25)]
        assert [(hits[(second, svid[n])]["rank"], hits[(second, svid[n])]["raw_score"]) for n in ("W2", "W1")] == \
               [(0, 88.0), (1, 12.5)]
        # The candidate row still keeps the best place of the two, so the second query's place is only on the hit row.
        ranks = {r[0]: r[1] for r in conn.execute(
            "SELECT source_version_id, rank FROM candidates WHERE research_id = ?", (rid,))}
        assert ranks[svid["W2"]] == 0 and hits[(first, svid["W2"])]["rank"] == 2
        # The sorting setting each request carried, so a later reader can tell a relevance list from another order.
        sorts = {r[0]: r[1] for r in conn.execute("SELECT id, sort FROM search_runs WHERE research_id = ?", (rid,))}
        assert sorts == {first: None, second: "cited_by_count:desc"}


def test_a_paged_query_counts_places_over_its_pages_and_a_provider_without_a_score_stores_none():
    with tempfile.TemporaryDirectory() as directory:
        conn, store, rid, run = library(directory)
        # A provider that scores nothing: the place is still kept, the score stays NULL and is never read as zero.
        first = search(store, rid, run, "search:0", [record("W1"), record("W2")])
        later = search(store, rid, run, "search:1", [record("W3", 5.0)], first_rank=2)
        hits = [(r["search_run_id"], r["rank"], r["raw_score"]) for r in conn.execute(
            "SELECT * FROM candidate_hits WHERE research_id = ? ORDER BY search_run_id, rank", (rid,))]
        assert sorted(hits) == sorted([(first, 0, None), (first, 1, None), (later, 2, 5.0)])


def _names_the_score(path):
    """Whether this file names the stored score at all: the hit column anywhere, or the record's field as an
    annotation, a keyword argument, an attribute read or a `getattr` of that name.

    Read from the syntax tree, not the text, so a reranker's own reply field (`item.get("relevance_score")`, a dict key
    of a different thing with the same name) is not mistaken for the record's.
    """
    import ast
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".sql":
        return COLUMN in text
    if COLUMN in text:
        return True
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == FIELD:
            return True
        if isinstance(node, (ast.keyword, ast.arg)) and node.arg == FIELD:
            return True
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == FIELD:
            return True
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
                and len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and node.args[1].value == FIELD):
            return True
        if isinstance(node, ast.Name) and node.id == "RELEVANCE_SCORE_FIELD":
            return True
    return False


def test_a_caller_whose_records_are_not_the_provider_s_order_passes_the_real_places():
    """The citation chain's `first_rank` is a candidate ordering offset, not a place, and its filter drops records
    between the ones it keeps. So the hit rows take `hit_ranks`, and the candidate ranks keep the offset."""
    with tempfile.TemporaryDirectory() as directory:
        conn, store, rid, run = library(directory)
        step = store.step(run["id"], "chain:fast:backward:0", "provider_search:openalex")
        fields = dict(research_id=rid, run_id=run["id"], step_id=step["id"], scope_revision=1, provider="openalex",
                      query_text="chain:fast:backward:0", request_description="GET SYNTHETIC", access_mode="keyless",
                      status="completed", delivery_class=None, result_count=2, provider_total=2, page_limit=25,
                      error_json=None, raw_payload_path=None, sort=None)
        # The provider answered with three records and the filter kept the first and the third.
        srid = store.record_search(fields, "openalex", [record("W1"), record("W3")], None, step["id"], "succeeded",
                                   step_output={"status": "completed"}, first_rank=1_000_000_000,
                                   hit_ranks=[0, 2])
        svid = {name: store.find_source_by_identifier("openalex", name) for name in ("W1", "W3")}
        hits = {r["source_version_id"]: r["rank"] for r in conn.execute(
            "SELECT * FROM candidate_hits WHERE search_run_id = ?", (srid,))}
        assert [hits[svid["W1"]], hits[svid["W3"]]] == [0, 2]
        ranks = {r[0]: r[1] for r in conn.execute(
            "SELECT source_version_id, rank FROM candidates WHERE research_id = ?", (rid,))}
        assert [ranks[svid["W1"]], ranks[svid["W3"]]] == [1_000_000_000, 1_000_000_001]
        # A places list that does not name every record is a code error, not a silently wrong audit row.
        later = store.step(run["id"], "chain:fast:backward:1", "provider_search:openalex")
        with pytest.raises(ValueError):
            store.record_search(fields | {"step_id": later["id"]}, "openalex", [record("W4")], None, later["id"],
                                "succeeded", hit_ranks=[])


def test_admission_keeps_each_record_s_place_in_the_provider_s_answer():
    """A record whose identity is unusable is dropped before the records are written. Counting the kept records in
    order would move every later record up by one, so admission reports the places it kept."""
    answer = SearchOutcome("completed", None, "GET SYNTHETIC", "keyless",
                           records=[record("{bad}"), record("W1"), record("None"), record("W2")])
    kept, dropped, places = facade._admit(answer, None)
    assert [r.provider_record_id for r in kept.records] == ["W1", "W2"]
    assert dropped == 2 and places == (1, 3)
    # Nothing dropped: the places are the order itself, and a caller may count instead.
    _, dropped, places = facade._admit(replace(answer, records=[record("W1"), record("W2")]), None)
    assert dropped == 0 and places == (0, 1)


def test_an_id_the_answer_repeats_keeps_the_first_place_it_took():
    """A provider that lists one work twice gives it one hit row. The place kept is the first, not the last: the
    later one would put the record behind works the provider listed after it."""
    with tempfile.TemporaryDirectory() as directory:
        conn, store, rid, run = library(directory)
        step = store.step(run["id"], "search:0", "provider_search:openalex")
        fields = dict(research_id=rid, run_id=run["id"], step_id=step["id"], scope_revision=1, provider="openalex",
                      query_text="search:0", request_description="GET SYNTHETIC", access_mode="keyless",
                      status="completed", delivery_class=None, result_count=3, provider_total=3, page_limit=25,
                      error_json=None, raw_payload_path=None, sort=None)
        # The provider answered [W1, W2, W1]; the caller gives the places it read from the answer.
        srid = store.record_search(fields, "openalex", [record("W1"), record("W2"), record("W1")], None, step["id"],
                                   "succeeded", step_output={"status": "completed"}, hit_ranks=[0, 1, 0])
        svid = {name: store.find_source_by_identifier("openalex", name) for name in ("W1", "W2")}
        hits = {r["source_version_id"]: r["rank"] for r in conn.execute(
            "SELECT * FROM candidate_hits WHERE search_run_id = ?", (srid,))}
        assert hits[svid["W1"]] == 0 and hits[svid["W2"]] == 1


def test_the_sorting_setting_recorded_is_the_query_s_own_or_the_one_the_connector_always_sends():
    """PubMed and Scopus send their own relevance sort whatever the query names, so NULL would say the provider
    answered in an unnamed order. A query that names a sort keeps its own."""
    assert registry.effective_sort({"provider_id": "pubmed"}) == pubmed.FIXED_SORT
    assert registry.effective_sort({"provider_id": "scopus"}) == scopus.FIXED_SORT
    assert registry.effective_sort({"provider_id": "openalex"}) is None
    assert registry.effective_sort({"provider_id": "pubmed", "sort": "pub_date"}) == "pub_date"
    # A provider the registry does not hold names nothing rather than raising inside a search's write.
    assert registry.effective_sort({"provider_id": "SYNTHETIC"}) is None


def test_no_gate_threshold_or_screening_path_reads_the_relevance_score():
    """The score is stored for inspection only. Only the request, the record, the write and the schema may name it.

    A static check cannot stop a name a module builds at run time (`row["raw_" + "score"]`), so the test below also
    shows, by running the writes, that nothing a later stage reads carries the score at all.
    """
    naming = {path.relative_to(ROOT).as_posix()
              for path in sorted(p for p in (ROOT / "deixis").rglob("*") if p.suffix in (".py", ".sql"))
              if _names_the_score(path)}
    assert naming == SCORE_READERS


def test_nothing_a_later_stage_reads_carries_the_score_so_two_scorings_decide_alike():
    """The score stays in `candidate_hits`. The rows the screening and ranking stages read are the candidates and the
    sources, and neither carries it, so no stage can reach the score even by a name it builds at run time.
    """
    with tempfile.TemporaryDirectory() as directory:
        conn, store, rid, run = library(directory)
        search(store, rid, run, "search:0", [record("W1", 1.0), record("W2", 99.0)])
        candidates = store.candidates(rid, 1)
        assert candidates and all(COLUMN not in row and FIELD not in row for row in candidates)
        sources = [dict(r) for r in conn.execute("SELECT * FROM source_versions")]
        assert sources and all(COLUMN not in row and FIELD not in row for row in sources)

        # The same two records with the scores swapped: the places and the candidate order do not move.
        with tempfile.TemporaryDirectory() as other:
            conn2, store2, rid2, run2 = library(other)
            search(store2, rid2, run2, "search:0", [record("W1", 99.0), record("W2", 1.0)])
            order = [(r["rank"], store.source(r["source_version_id"])["title"]) for r in candidates]
            order2 = [(r["rank"], store2.source(r["source_version_id"])["title"])
                      for r in store2.candidates(rid2, 1)]
            assert order == order2
