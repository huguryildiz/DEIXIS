"""Citation chaining's pure rules: the filter, what is new, and how a seed's title is compared (slice 15, D95).

Rows, titles and abstracts are SYNTHETIC and from two fields (greenhouse irrigation and pallet packing), because the
filter reads the research's own gate blocks and must not know a topic. Passing shows the rules do what the slice says;
it says nothing about how many relevant works a real chain reaches, which the slice's replay and acceptance measure.
"""

import pytest

from deixis.workflow import chaining, ranking

IRRIGATION = {"setting": ["greenhouse"], "task": ["irrigation scheduling"]}


def forms(blocks):
    return ranking.block_forms(blocks)


def test_a_linked_work_the_library_already_holds_is_not_chained():
    seeds = [{"source_version_id": "s1", "openalex_ids": ["W1"], "references": ["W5", "W6", "W7"]},
             {"source_version_id": "s2", "openalex_ids": ["W2"], "references": ["W6", "W8"]}]
    assert chaining.backward_links(seeds, ["W5", "W8"]) == [("s1", "W5"), ("s2", "W8")]
    # A linked record the record path merged into a keyword work has that work's head, and is not a chained work.
    assert chaining.chained_heads(["k1", "c1", "c2", "c1"], keyword_pool={"k1", "k2"}) == ["c1", "c2"]


# ---- what became of each fast-chain request (`request_outcomes`) ---------------------------------------------------


def request(status, output=None, delivery=None, key="chain:fast:0"):
    return {"operation_key": key, "status": status, "output": output, "delivery_class": delivery}


def sends(n, attempts=1):
    return {"transport": {"reserved": 1, "attempts": attempts, "sends": n}}


ZERO = dict.fromkeys(("sent", "answered", "late", "failed", "unknown", "not_sent", "unproven"), 0)


@pytest.mark.parametrize("step,expected", [
    # The transport trace decides first.
    (request("succeeded", {"late": False} | sends(1)), {"sent": 1, "answered": 1}),
    (request("succeeded", {"late": True} | sends(1)), {"sent": 1, "late": 1}),
    (request("failed", sends(1)), {"sent": 1, "failed": 1}),
])
def test_each_fast_chain_request_is_counted_once_by_its_own_step(step, expected):
    assert chaining.request_outcomes([step]) == ZERO | expected
