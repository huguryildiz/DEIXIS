"""Citation chaining's pure rules: the filter, what is new, and how a seed's title is compared (slice 15, D95).

Rows, titles and abstracts are SYNTHETIC and from two fields (greenhouse irrigation and pallet packing), because the
filter reads the research's own gate blocks and must not know a topic. Passing shows the rules do what the slice says;
it says nothing about how many relevant works a real chain reaches, which the slice's replay and acceptance measure.
"""

import pytest

from deixis.workflow import chaining, ranking

IRRIGATION = {"setting": ["greenhouse"], "task": ["irrigation scheduling"]}
PACKING = {"setting": ["warehouse"], "task": ["pallet loading"]}


def forms(blocks):
    return ranking.block_forms(blocks)


def test_the_filter_passes_a_setting_or_a_task_form_in_title_or_abstract():
    irrigation, packing = forms(IRRIGATION), forms(PACKING)
    assert chaining.passes(irrigation, "SYNTHETIC greenhouse climate control", "We model the air.")
    assert chaining.passes(irrigation, "SYNTHETIC crop water", "We compare irrigation scheduling rules.")
    assert not chaining.passes(irrigation, "SYNTHETIC crop water", "We compare the soil of two fields.")
    assert chaining.passes(packing, "SYNTHETIC pallet loading with robots", None)
    assert not chaining.passes(packing, "SYNTHETIC greenhouse irrigation scheduling", "Water use of a crop.")
    # A form matches at a word start only, as the ranking's block signal does.
    assert not chaining.passes(packing, "SYNTHETIC nonwarehouse storage", None)


def test_a_work_without_an_abstract_is_judged_on_its_title():
    irrigation = forms(IRRIGATION)
    assert chaining.passes(irrigation, "SYNTHETIC irrigation scheduling of tomato", None)
    assert not chaining.passes(irrigation, "SYNTHETIC tomato yield", None)
    assert not chaining.passes(irrigation, "SYNTHETIC tomato yield", "")


def test_a_linked_work_the_library_already_holds_is_not_chained():
    seeds = [{"source_version_id": "s1", "openalex_ids": ["W1"], "references": ["W5", "W6", "W7"]},
             {"source_version_id": "s2", "openalex_ids": ["W2"], "references": ["W6", "W8"]}]
    assert chaining.backward_links(seeds, ["W5", "W8"]) == [("s1", "W5"), ("s2", "W8")]
    # A linked record the record path merged into a keyword work has that work's head, and is not a chained work.
    assert chaining.chained_heads(["k1", "c1", "c2", "c1"], keyword_pool={"k1", "k2"}) == ["c1", "c2"]


def test_seed_titles_are_compared_case_folded_and_without_punctuation():
    assert chaining.norm_title("SYNTHETIC Greenhouse irrigation") == chaining.norm_title("synthetic greenhouse  IRRIGATION!")
    assert chaining.norm_title(None) == ""


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
    # A 429 that went out, then a ConnectError before the retry was sent: the last delivery is `before_send`, but the
    # trace recorded one send, so the request was sent and failed.
    (request("failed", sends(1, attempts=2), "before_send"), {"sent": 1, "failed": 1}),
    (request("failed", sends(0), "before_send"), {"not_sent": 1}),
    (request("failed", sends(0)), {"not_sent": 1}),
    (request("outcome_unknown", {"unknown": True} | sends(1)), {"sent": 1, "unknown": 1}),
    (request("outcome_unknown", {"unknown": True} | sends(0)), {"not_sent": 1}),
    (request("cancelled", {"unsent": "cutoff", "returned": 0} | sends(1)), {"sent": 1, "failed": 1}),
    # Without a trace: a reply was sent, a failure is sent unless `before_send`, a cancel was not, an unknown is unproven.
    (request("succeeded", {"late": False}), {"sent": 1, "answered": 1}),
    (request("failed", {"returned": 0}), {"sent": 1, "failed": 1}),
    (request("failed", {"returned": 0}, "before_send"), {"not_sent": 1}),
    (request("cancelled", {"unsent": "cutoff", "returned": 0}), {"not_sent": 1}),
    (request("outcome_unknown", {"unsent": None, "unknown": True, "returned": 0}), {"unproven": 1}),
    # Not settled yet, and not a chain request: not counted.
    (request("running", sends(1)), {}),
    (request("pending"), {}),
    (request("succeeded", sends(1), key="search:0"), {}),
])
def test_each_fast_chain_request_is_counted_once_by_its_own_step(step, expected):
    assert chaining.request_outcomes([step]) == ZERO | expected


def test_sent_is_the_sum_of_its_four_outcomes_and_unproven_is_apart():
    steps = [request("succeeded", {"late": False} | sends(1)), request("succeeded", {"late": True} | sends(1)),
             request("failed", sends(1, attempts=2), "before_send"), request("outcome_unknown", sends(1)),
             request("outcome_unknown", {"unknown": True}), request("cancelled", {"unsent": "cutoff"})]
    counts = chaining.request_outcomes(steps)
    assert counts == {"sent": 4, "answered": 1, "late": 1, "failed": 1, "unknown": 1, "not_sent": 1, "unproven": 1}
    assert counts["sent"] == counts["answered"] + counts["late"] + counts["failed"] + counts["unknown"]
