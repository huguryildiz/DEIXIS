"""Pure synthetic graph checks; structure establishes no source claim."""

from dataclasses import asdict, replace
from itertools import permutations

import pytest

from deixis.workflow.lineage.assembly import Link, REASONS, RowFacts, assemble, unplaceable_reasons


def link(a, b, **kw):
    return Link(a + b, a, b, kw.get("relation", "extends"), kw.get("from_year", 2000 + ord(a)),
                kw.get("to_year", 2000 + ord(b)), ord(a), ord(b))


def test_directed_diamond_is_one_component_with_root_branch_and_merge():
    result = assemble([link("a", "b"), link("a", "c"), link("b", "d"), link("c", "d")])
    assert len(result.components) == 1
    c = result.components[0]
    assert c.members == ("a", "b", "c", "d") and c.roots == c.branches == ("a",) and c.merges == ("d",)
    assert not c.has_cycle and c.adjacency[-1].in_from == ("b", "c")


def test_chain_branch_and_merge_roles():
    c = assemble([link("a", "b"), link("b", "c"), link("b", "d"), link("c", "d")]).components[0]
    assert c.roots == ("a",) and c.branches == ("b",) and c.merges == ("d",)


def test_two_separate_components_are_ordered_deterministically():
    result = assemble([link("c", "d"), link("a", "b")])
    assert [c.members for c in result.components] == [("a", "b"), ("c", "d")]


def test_input_order_does_not_change_the_output():
    links = [link("a", "b"), link("a", "c"), link("b", "d"), link("c", "d")]
    assert all(assemble(order) == assemble(links) for order in permutations(links))


def test_independent_parallel_never_builds_a_component_or_a_role():
    assert assemble([link("a", "b", relation="independent_parallel")]).components == ()
    c = assemble([link("a", "b"), link("b", "c", relation="independent_parallel")]).components[0]
    assert c.members == ("a", "b") and c.branches == c.merges == ()


def test_cyclic_input_terminates_and_reports_has_cycle():
    c = assemble([link("a", "b"), link("b", "c"), link("c", "a")]).components[0]
    assert c.has_cycle and c.roots == () and len(c.links) == 3


def test_unknown_years_sort_last_with_position_and_id_ties():
    links = [replace(link("a", "b"), from_year=None, to_year=None, from_position=2, to_position=1),
             replace(link("a", "c"), from_year=None, to_year=2020, from_position=2, to_position=9)]
    assert assemble(links).components[0].members == ("c", "b", "a")
    assert assemble([replace(l, from_position=1, to_position=1, to_year=None) for l in links]).components[0].members == ("a", "b", "c")


def test_component_id_depends_only_on_members():
    first = assemble([link("a", "b"), link("b", "c")]).components[0].id
    other = assemble([link("c", "a"), link("a", "b")]).components[0].id
    assert first == other and len(first) == 12
    assert first != assemble([link("a", "b")]).components[0].id


def test_a_single_node_has_no_component():
    assert assemble([]).components == ()


FACT_FIELDS = {"no_relation": "has_no_relation", "insufficient_evidence": "has_insufficient_evidence",
               "rejected": "has_rejected", "not_sent_budget": "has_not_sent_budget", "step_failed": "has_step_failed",
               "human_removed": "has_human_removed", "cross_relation_only": "has_cross_relation", "stale_only": "has_history_link"}


@pytest.mark.parametrize("reason", REASONS)
def test_every_unplaceable_reason_alone(reason):
    facts = RowFacts(target_recorded=True)
    if reason == "not_run":
        facts = replace(facts, target_recorded=False)
    elif reason == "no_pdf_text":
        facts = replace(facts, eligible=False)
    else:
        facts = replace(facts, **{FACT_FIELDS.get(reason, reason): True})
    assert unplaceable_reasons(facts) == (reason,)


def test_reasons_are_ordered_and_deduplicated():
    facts = RowFacts(False, True, True, True, True, True, True, True, True, True, True)
    assert unplaceable_reasons(facts) == REASONS[1:]
    assert len(set(unplaceable_reasons(facts))) == len(unplaceable_reasons(facts))


def test_a_row_with_several_reasons_keeps_all():
    assert unplaceable_reasons(RowFacts(has_step_failed=True, has_history_link=True)) == ("not_run", "step_failed", "stale_only")


def test_fallback_not_run_means_no_recorded_decision():
    assert unplaceable_reasons(RowFacts(target_recorded=True)) == ("not_run",)


def test_no_reason_means_no_continuation():
    forbidden = {"continuation", "foundational", "founder", "novel", "original"}
    assert not forbidden & set(REASONS)
    def keys(value):
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(v) for v in value.values()))
        if isinstance(value, (list, tuple)):
            return set().union(*(keys(v) for v in value))
        return set()
    assert not forbidden & keys(asdict(assemble([link("a", "b")])))
