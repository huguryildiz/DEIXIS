"""SYNTHETIC pure cases; these check decisions, not scientific validity."""
import itertools

import pytest

from deixis.workflow.candidates_hits import merge_and_cut
from deixis.workflow.candidates_status import STATUSES, derive_status
from deixis.workflow.candidates_terms import block_vocabulary, compile_queries

ELEMENTS = ["ele_1", "ele_2"]


def search(**changes):
    return dict(outcome="completed", found=1, kept=1, rank_cut=0, duplicates=0) | changes


def hit(**changes):
    return dict(source_version_id="srv_1", kept=1, assessment_state="assessed", work_relevance="related",
                states_whole_claim=True, reading_depth="abstract", whole_claim_evidence_count=1) | changes


def cells(**changes):
    return [dict(source_version_id="srv_1", element_id=e, relation="explicit_support",
                 condition_alignment="aligned") | changes for e in ELEMENTS]


def derive(s=None, h=None, c=None, queries=None):
    return derive_status(s if s is not None else search(), queries if queries is not None else [{"status": "succeeded"}],
                         h if h is not None else [hit()], c if c is not None else cells(), ELEMENTS)


@pytest.mark.parametrize("outcome", ["running", "completed"])
@pytest.mark.parametrize("other_state", ["pending"])
def test_whole_claim_closes_partial_search_and_other_unread_or_unrelated_hits_cannot_undo_it(outcome, other_state):
    other = hit(source_version_id="srv_other", assessment_state=other_state, states_whole_claim=False,
                whole_claim_evidence_count=0, work_relevance="unrelated" if other_state == "assessed" else None)
    result = derive(search(outcome=outcome, kept=2, found=2), [hit(), other])
    assert (result["status"], result["reason"]) == ("closed", "whole_claim_stated")


@pytest.mark.parametrize("code,outcome,query,state,relevance,relation,alignment", [
    ("search_running", "running", "succeeded", "assessed", "unrelated", "no_match_in_supplied_text", None),
    ("insufficient_access", "completed", "succeeded", "insufficient_access", None, "no_match_in_supplied_text", None),
])
def test_each_undecided_reason_has_a_fixed_case(code, outcome, query, state, relevance, relation, alignment):
    queries = [{"status": query}]
    if code == "query_outcome_unknown":
        queries.append({"status": "succeeded"})
    result = derive(search(outcome=outcome), [hit(assessment_state=state, work_relevance=relevance,
                    states_whole_claim=False)], cells(relation=relation, condition_alignment=alignment), queries)
    assert result["status"] == "undecided" and result["reason"] == code
    assert result["reasons"] == [code]


def test_completed_search_with_query_records_but_no_hits_or_found_count_fails_closed():
    result = derive(search(found=0, kept=0, query_record_count=1), [], [])
    assert (result["status"], result["reason"]) == ("undecided", "unclassified")
    assert result["reasons"] == ["unclassified"]
    assert result["warnings"] == ["merge_missing"]
    assert derive(search(found=0, kept=0, query_record_count=0), [], [])["status"] == "open"


def test_generated_product_never_opens_or_closes_without_the_explicit_gate():
    for outcome, state, relation, relevance in itertools.product(
        ("running", "paused", "completed", "failed", "stopped"),
        ("pending", "assessed", "insufficient_access", "not_assessed_budget"),
        ("explicit_support", "reasoned_inference", "partial_match", "uncertain", "no_match_in_supplied_text"),
        ("related", "unrelated", "uncertain"),
    ):
        h = hit(assessment_state=state, work_relevance=relevance)
        c = cells(relation=relation, condition_alignment="aligned" if relation != "no_match_in_supplied_text" else None)
        result = derive(search(outcome=outcome), [h], c)
        assert result["status"] in STATUSES
        if result["status"] == "closed":
            assert state == "assessed" and relation == "explicit_support"
        if result["status"] == "open":
            assert outcome == "completed" and state == "assessed" and relevance == "unrelated"


def record(provider, n, work=None):
    return {"provider": provider, "source_version_id": f"srv_{provider}_{n}", "work_id": work}


def test_merge_cuts_at_eight_with_exact_counts_and_rank_keys():
    merged = merge_and_cut([[record("a", i, f"w{i}") for i in range(11)]])
    assert (merged["found"], merged["kept_count"], merged["rank_cut"], merged["duplicates"]) == (11, 8, 3, 0)
    assert [r["rank_key"] for r in merged["kept"] + merged["cut"]] == list(range(1, 12))
    assert merge_and_cut([]) == {"kept": [], "cut": [], "found": 0, "kept_count": 0, "rank_cut": 0, "duplicates": 0}


import json

import pytest

from deixis.storage import db
from deixis.workflow.candidates_hits import concept_scores, concepts, merge_and_cut, rank_and_cut, rank_concepts_and_cut
from deixis.workflow.candidates_store import InvalidCandidateInput
from deixis.workflow.candidates_terms import compile_queries, block_vocabulary
from test_candidate_store import make_library, provider_record, query, start
from test_candidate_flow import lib  # noqa: F401  (fixtures used by name)

PROVIDERS = ["openalex", "semantic_scholar", "arxiv", "biorxiv", "pubmed", "ieee_xplore"]
SETTING = ["underwater acoustic sensor networks", "underwater sensor networks", "UASN"]
TASK = ["depth-based routing", "vector-based forwarding", "DBR"]


def pool(rows):
    per_query = [[{"provider": "openalex", "source_version_id": f"srv_{n:03d}", "work_id": f"wrk_{n:03d}"}
                  for n in range(len(rows))]]
    documents = {f"srv_{n:03d}": {"title": title, "abstract": abstract} for n, (title, abstract) in enumerate(rows)}
    return per_query, documents


def scored(rows, blocks, claim="", backups=None):
    found = concepts(blocks, claim, backups)
    return concept_scores([{"id": f"r{n}", "title": t, "abstract": a} for n, (t, a) in enumerate(rows)], found)


# ---- 1. backups reach the query within the provider's rules, the rest is recorded --------------------------------


# ---- 2. concepts, not name forms -----------------------------------------------------------------------------


def test_a_medicine_claim_ranks_the_direct_comparison_above_single_treatment_works():
    claim = {"text": "SYNTHETIC: In adults with knee osteoarthritis, intra-articular platelet-rich plasma injections "
                     "reduce pain more than hyaluronic acid injections at 12 months.",
             "setting": ["knee osteoarthritis"], "task": ["platelet-rich plasma", "hyaluronic acid"],
             "setting_backup": ["gonarthrosis"], "task_backup": ["PRP", "HA"]}
    single = [(f"SYNTHETIC platelet-rich plasma injections for knee osteoarthritis: cohort {n}",
               "SYNTHETIC: PRP injections reduced pain in knee osteoarthritis at 12 months in a cohort.") for n in range(4)]
    single += [(f"SYNTHETIC hyaluronic acid viscosupplementation in knee osteoarthritis: registry {n}",
                "SYNTHETIC: hyaluronic acid injections and pain in knee osteoarthritis over 12 months.") for n in range(4)]
    noise = [(f"SYNTHETIC total knee arthroplasty outcomes {n}", "SYNTHETIC: pain after knee replacement surgery.")
             for n in range(6)]
    target = ("SYNTHETIC intra-articular injections in knee osteoarthritis: a randomized trial",
              "SYNTHETIC: patients received PRP or HA; pain at 12 months was lower with platelet-rich plasma.")
    per_query, documents = pool([*single, *noise, target])
    merged = rank_concepts_and_cut(per_query, documents, claim, keep=8)
    assert merged["kept"][0]["source_version_id"] == f"srv_{len(single) + len(noise):03d}"
    assert merged["kept"][0]["rank_signals"]["joint"][1] > 0
    assert all(r["rank_signals"]["joint"] == [0, 0.0] for r in merged["kept"][1:] + merged["cut"])


# ---- 3. ranking inputs exported per record -----------------------------------------------------------------


# ---- old plans and store re-verification ------------------------------------------------------------------

@pytest.fixture
def store_lib(tmp_path):
    lib = make_library(tmp_path / "library.sqlite")
    yield lib
    lib.conn.close()


def ranked_search(lib, plan_version):
    s = start(lib, query_block={"setting": [{"term": "synthetic network"}], "task": [{"term": "bounded delay"}],
                                "setting_backup": [{"term": "SN"}], "task_backup": []})
    target = json.loads(lib.conn.execute("SELECT target_json FROM runs WHERE id = ?", (s["run_id"],)).fetchone()[0])
    lib.conn.execute("UPDATE runs SET target_json = ? WHERE id = ?",
                     (db.dumps(target | {"plan_version": plan_version}), s["run_id"]))
    noise = [provider_record(f"SYNTHETIC-{n}", abstract="SYNTHETIC: unrelated text.") for n in range(10)]
    noise[9] = provider_record("SYNTHETIC-target", title="SYNTHETIC bounded delay in a synthetic network",
                               abstract="SYNTHETIC: bounded delay in a synthetic network.")
    return s, query(lib, s, noise)


def test_store_reverification_recomputes_the_concept_cut_and_refuses_tampering(store_lib):
    lib = store_lib
    s, records = ranked_search(lib, 3)
    merged = lib.candidate_store.merge(s["id"], keep=8)
    depths = {r["source_version_id"]: "abstract" for r in records}
    rescored = merged | {"kept": [merged["kept"][0] | {"signal_ranks": {"bm25": 9.0, "blocks": 9.0, "joint": 9.0}},
                                  *merged["kept"][1:]]}
    for forged in (merge_and_cut(lib.candidate_store.query_records(s["id"])), rescored,
                   rank_and_cut(lib.candidate_store.query_records(s["id"]),
                                {r["source_version_id"]: {"title": "x", "abstract": None} for r in records},
                                {"text": "x", "setting": ["x"], "task": ["y"]})):
        with pytest.raises(InvalidCandidateInput, match="Merge differs"):
            lib.candidate_store.record_hits(s["id"], forged, depths)
    lib.candidate_store.record_hits(s["id"], merged, depths)
    assert [h["source_version_id"] for h in lib.candidate_store.hits(s["id"])] == \
        [r["source_version_id"] for r in merged["kept"] + merged["cut"]]
