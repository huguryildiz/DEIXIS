"""What is left of the term expansion (SW2.4): the stored second-round blocks a run's ranking reads.

The second round itself was removed in the clean start (slice 3a); a fast-path run stores an empty expansion step.
Phrases are SYNTHETIC.
"""

from deixis.workflow.expansion import expansion_blocks, term_rows


def test_the_stored_searched_blocks_are_what_the_ranking_reads_and_a_fast_run_reads_none():
    searched = {"setting": ["SYNTHETIC quantum internet"], "task": ["SYNTHETIC remote entanglement"]}
    assert expansion_blocks({"searched": searched}) == searched
    rows = term_rows([], {"searched": searched})
    assert [(r["phrase"], r["block"], r["origin"]) for r in rows] == [
        ("SYNTHETIC quantum internet", "setting", "data"), ("SYNTHETIC remote entanglement", "task", "data")]
    # The fast path writes `{"queries": [], "expansion": {"searched": {}}}`, and a run with no step has none.
    assert expansion_blocks({"searched": {}}) == expansion_blocks(None) == {"setting": [], "task": []}
