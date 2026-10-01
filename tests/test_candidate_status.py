"""SYNTHETIC pure cases; these check decisions, not scientific validity."""
import ast
import itertools
from pathlib import Path
import sys

import pytest

from deixis.providers.query_rules import query_issues
from deixis.workflow.candidates.hits import merge_and_cut
from deixis.workflow.candidates.status import STATUSES, derive_status
from deixis.workflow.candidates.terms import InvalidTerms, block_vocabulary, compile_queries
from deixis.workflow.vocabulary import TERM_FIELDS

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


def test_no_search_is_not_run_but_attempted_all_failed_search_is_undecided():
    result = derive_status(None, [], [], [], ELEMENTS)
    assert (result["status"], result["reason"]) == ("not_run", "not_searched")
    assert derive(search(found=0, kept=0), [], [], [{"status": "failed"}])["reason"] == "search_failed"


@pytest.mark.parametrize("outcome", ["running", "paused", "stopped", "failed", "completed"])
@pytest.mark.parametrize("other_state", ["assessed", "insufficient_access", "pending", "not_assessed_budget"])
def test_whole_claim_closes_partial_search_and_other_unread_or_unrelated_hits_cannot_undo_it(outcome, other_state):
    other = hit(source_version_id="srv_other", assessment_state=other_state, states_whole_claim=False,
                whole_claim_evidence_count=0, work_relevance="unrelated" if other_state == "assessed" else None)
    result = derive(search(outcome=outcome, kept=2, found=2), [hit(), other])
    assert (result["status"], result["reason"]) == ("closed", "whole_claim_stated")


@pytest.mark.parametrize("relation,alignment,missing,quotes", [
    ("reasoned_inference", "aligned", False, 1), ("partial_match", "aligned", False, 1),
    ("explicit_support", "aligned", True, 1), ("explicit_support", "different_conditions", False, 1),
    ("explicit_support", "unclear", False, 1), ("explicit_support", "aligned", False, 0),
])
def test_closure_requires_explicit_aligned_complete_cells_and_whole_claim_quote(relation, alignment, missing, quotes):
    own = cells(relation=relation, condition_alignment=alignment)
    assert derive(h=[hit(whole_claim_evidence_count=quotes)], c=own[:1] if missing else own)["status"] != "closed"


@pytest.mark.parametrize("code,outcome,query,state,relevance,relation,alignment", [
    ("search_running", "running", "succeeded", "assessed", "unrelated", "no_match_in_supplied_text", None),
    ("search_paused", "paused", "succeeded", "assessed", "unrelated", "no_match_in_supplied_text", None),
    ("search_failed", "completed", "failed", "assessed", "unrelated", "no_match_in_supplied_text", None),
    ("search_incomplete", "failed", "succeeded", "assessed", "unrelated", "no_match_in_supplied_text", None),
    ("search_incomplete", "stopped", "succeeded", "assessed", "unrelated", "no_match_in_supplied_text", None),
    ("query_outcome_unknown", "completed", "outcome_unknown", "assessed", "unrelated", "no_match_in_supplied_text", None),
    ("insufficient_access", "completed", "succeeded", "insufficient_access", None, "no_match_in_supplied_text", None),
    ("not_assessed_budget", "completed", "succeeded", "not_assessed_budget", None, "no_match_in_supplied_text", None),
    ("not_assessed_budget", "completed", "succeeded", "pending", None, "no_match_in_supplied_text", None),
    ("uncertain_relevance", "completed", "succeeded", "assessed", "uncertain", "uncertain", None),
    ("uncertain_cell", "completed", "succeeded", "assessed", "related", "uncertain", None),
    ("unclear_alignment", "completed", "succeeded", "assessed", "related", "partial_match", "unclear"),
])
def test_each_undecided_reason_has_a_fixed_case(code, outcome, query, state, relevance, relation, alignment):
    queries = [{"status": query}]
    if code == "query_outcome_unknown":
        queries.append({"status": "succeeded"})
    result = derive(search(outcome=outcome), [hit(assessment_state=state, work_relevance=relevance,
                    states_whole_claim=False)], cells(relation=relation, condition_alignment=alignment), queries)
    assert result["status"] == "undecided" and result["reason"] == code
    assert result["reasons"] == [code]


def test_undecided_reasons_keep_the_fixed_order_with_several_together():
    result = derive(search(outcome="completed", found=4, kept=4),
                    [hit(states_whole_claim=False, work_relevance="uncertain"),
                     hit(source_version_id="srv_2", assessment_state="insufficient_access", work_relevance=None),
                     hit(source_version_id="srv_3", assessment_state="pending", work_relevance=None),
                     hit(source_version_id="srv_4", states_whole_claim=False)],
                    cells(relation="uncertain", condition_alignment=None) +
                    [dict(source_version_id="srv_4", element_id="ele_1", relation="uncertain", condition_alignment=None),
                     dict(source_version_id="srv_4", element_id="ele_2", relation="partial_match", condition_alignment="unclear")],
                    [{"status": "outcome_unknown"}, {"status": "failed"}])
    assert result["reasons"] == ["search_failed", "query_outcome_unknown", "insufficient_access",
                                 "not_assessed_budget", "uncertain_relevance", "uncertain_cell", "unclear_alignment"]
    assert result["reason"] == "search_failed"


@pytest.mark.parametrize("relation", ["explicit_support", "reasoned_inference", "partial_match"])
def test_support_without_whole_claim_statement_narrows(relation):
    assert derive(h=[hit(states_whole_claim=False)], c=cells(relation=relation))["status"] == "narrowed"


def test_rank_cut_alone_allows_open_and_is_counted_as_unread():
    result = derive(search(found=13, rank_cut=10, duplicates=2),
                    [hit(work_relevance="unrelated", states_whole_claim=False)],
                    cells(relation="no_match_in_supplied_text", condition_alignment=None))
    assert result["status"] == "open"
    assert result["facts"]["unread"] == 10
    assert result["facts"]["reading_depths"] == {"abstract": 1, "stored_passages": 0, "metadata_only": 0}


def test_zero_found_success_is_open_but_zero_kept_above_zero_found_fails_closed():
    assert derive(search(found=0, kept=0), [], [])["status"] == "open"
    result = derive(search(found=4, kept=0, rank_cut=4), [], [])
    assert (result["status"], result["reason"]) == ("undecided", "unclassified")
    assert result["warnings"][0].startswith("unmatched_shape:")
    assert derive(h=[hit(states_whole_claim=False)], c=[])["reason"] == "unclassified"


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


@pytest.mark.parametrize("module", ["status", "hits", "terms"])
def test_candidate_computations_import_only_the_pure_allowlist(module):
    path = Path("backend/deixis/workflow/candidates") / f"{module}.py"
    allowed = {"deixis.providers.query_compiler", "deixis.providers.query_rules",
               "deixis.workflow.criterion", "deixis.workflow.vocabulary"}
    for node in ast.walk(ast.parse(path.read_text())):
        imports = ([node.module] if isinstance(node, ast.ImportFrom) else
                   [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
        for name in imports:
            assert name.split(".")[0] in sys.stdlib_module_names or name in allowed or name.startswith("deixis.domain.")


def record(provider, n, work=None):
    return {"provider": provider, "source_version_id": f"srv_{provider}_{n}", "work_id": work}


def test_merge_is_round_robin_for_shuffled_unequal_provider_lists():
    a, b, c = [record("a", n, f"a{n}") for n in range(4)], [record("b", 0, "b0")], [record("c", n, f"c{n}") for n in range(2)]
    for query_order in itertools.permutations([a, b, c]):
        expected = [q[i] for i in range(4) for q in query_order if i < len(q)]
        actual = merge_and_cut(list(query_order))
        assert [r["source_version_id"] for r in actual["kept"]] == [r["source_version_id"] for r in expected]


def test_merge_first_work_wins_and_missing_work_uses_source_id():
    a, b, no_work = record("a", 1, "shared"), record("b", 1, "shared"), record("c", 1)
    merged = merge_and_cut([[a, no_work], [b, dict(no_work)]])
    assert merged["found"] == 4 and merged["duplicates"] == 2
    assert [r["provider"] for r in merged["kept"]] == ["a", "c"]


def test_merge_cuts_at_eight_with_exact_counts_and_rank_keys():
    merged = merge_and_cut([[record("a", i, f"w{i}") for i in range(11)]])
    assert (merged["found"], merged["kept_count"], merged["rank_cut"], merged["duplicates"]) == (11, 8, 3, 0)
    assert [r["rank_key"] for r in merged["kept"] + merged["cut"]] == list(range(1, 12))
    assert merge_and_cut([]) == {"kept": [], "cut": [], "found": 0, "kept_count": 0, "rank_cut": 0, "duplicates": 0}


def test_block_terms_keep_whole_phrases_normalize_and_deduplicate_across_blocks():
    vocabulary = block_vocabulary([" (SYNTHETIC  NETWORK) ", "synthetic network"], ["synthetic network", "Packet delay"])
    assert vocabulary["block_assignment"] == "kill_search"
    assert [t["phrase"] for t in vocabulary["terms"]] == ["synthetic network", "packet delay"]
    for term in vocabulary["terms"]:
        assert tuple(term) == TERM_FIELDS
        assert term["root"] == term["phrase"] and term["in_query"] == "phrase"
        assert term["phrase_count"] is term["root_count"] is term["dropped"] is None
        assert term["and_only"] is False


@pytest.mark.parametrize("setting,task", [
    (["a", "b", "c"], ["d", "e", "f", "g"]), ([], ["task"]), (["setting"], []),
    (["same"], ["same"]), ([" "], ["task"]),
])
def test_empty_block_cross_block_exhaustion_and_seven_terms_are_refused(setting, task):
    with pytest.raises(InvalidTerms):
        block_vocabulary(setting, task)


def test_real_offline_compiler_output_passes_real_provider_rules():
    queries = compile_queries(block_vocabulary(["synthetic network", "wireless sensor"], ["packet delay", "scheduling"]),
                              ["openalex", "semantic_scholar", "arxiv", "pubmed", "crossref", "scopus", "serpapi", "core"])
    assert queries
    assert all(not query_issues(q["provider_id"], q["query_text"], q.get("endpoint")) for q in queries)
