"""The safe set of the full-text fetch that overlaps discovery (slice 17a, decision 2), as a pure function.

`fulltext.safe_to_fetch` says which works may be fetched while the model is still reading other abstracts. What is
checked here is the rule, not a library: over many SYNTHETIC random plans, every work it lets start early is in the
final plan whatever the pending works turn out to be, and the baseline keeps the fetch's own codes and texts out of
the plan it is computed against. No database, no network, no model.
"""

import random

from deixis.workflow import fulltext

OUTCOMES = ("runs_agree_candidate", "runs_agree_out_of_scope", "runs_agree_unresolved", "abstract_not_proposed")
NO_BASELINE = {"settled": [], "has_text": []}


def code(reason_code, decided_by="code", stale=False):
    return {"reason_code": reason_code, "decided_by": decided_by, "stale": stale}


def work(number, abstract="blocks_in_title", *, head=None, versions=1, has_text=False, fulltext_row=None,
         selection=None, chained=False):
    """One SYNTHETIC work of `versions` records; the first holds the abstract decision, `head` names its head."""
    ids = [f"srv_{number}_{i}" for i in range(versions)]
    return {"work_id": f"wrk_{number}", "head": head or ids[0], "selection": selection, "chained": chained,
            "versions": [{"id": svid, "has_text": has_text and i == 0,
                          "abstract": code(abstract) if i == 0 and abstract else None,
                          "fulltext": fulltext_row if i == 0 else None} for i, svid in enumerate(ids)]}


def decided(works, outcomes):
    """The works once every pending one has its final abstract decision."""
    return [dict(w, versions=[dict(v, abstract=code(outcomes[w["work_id"]]) if i == 0 else v["abstract"])
                              for i, v in enumerate(w["versions"])]) if w["work_id"] in outcomes else w
            for w in works]


def final_ids(works, order, limit, chain_order=(), room=0, baseline=NO_BASELINE):
    plan = fulltext.fetch_plan(fulltext.as_of_baseline(works, baseline), order, limit, chain_order, room)
    of = {w["head"]: w["work_id"] for w in works}
    return [of[head] for head in plan["works"]]


def test_a_work_let_start_early_is_in_the_final_plan_whatever_the_pending_works_become():
    """The property: for every pending work's outcome (candidate, out of scope, unresolved routed or not)."""
    checked = early = 0
    for seed in range(400):
        rng = random.Random(seed)
        count = rng.randint(1, 14)
        works = [work(n, rng.choice(OUTCOMES + ("blocks_in_title", "both_blocks_missing", None)),
                      chained=rng.random() < 0.2) for n in range(count)]
        order = [w["head"] for w in works if not w["chained"]]
        rng.shuffle(order)
        chain_order = [w["head"] for w in works if w["chained"]]
        rng.shuffle(chain_order)
        limit, room = rng.randint(0, count), rng.randint(0, 3)
        pending = {w["work_id"] for w in works if rng.random() < 0.4}
        baseline = {"settled": sorted(w["work_id"] for w in works if rng.random() < 0.1),
                    "has_text": sorted(w["work_id"] for w in works if rng.random() < 0.1)}
        safe = fulltext.safe_to_fetch(works, order, limit, chain_order, room, pending, baseline)
        assert not set(safe) & pending
        for _ in range(6):
            outcomes = {work_id: rng.choice(OUTCOMES) for work_id in pending}
            final = final_ids(decided(works, outcomes), order, limit, chain_order, room, baseline)
            assert set(safe) <= set(final), (seed, safe, final)
            checked += 1
        early += len(safe)
    assert checked == 2400 and early > 0


def test_with_nothing_pending_the_safe_set_is_the_plan():
    works = [work(n) for n in range(5)]
    order = [w["head"] for w in works]
    assert fulltext.safe_to_fetch(works, order, 3, (), 0, set(), NO_BASELINE) == ["wrk_0", "wrk_1", "wrk_2"]


def test_a_pending_work_ahead_holds_a_slot_and_one_behind_takes_none():
    works = [work(0), work(1, "abstract_not_proposed"), work(2), work(3)]
    order = [w["head"] for w in works]
    # wrk_1 may still become a candidate: it keeps its slot, so only two of the three code candidates are safe.
    assert fulltext.safe_to_fetch(works, order, 3, (), 0, {"wrk_1"}, NO_BASELINE) == ["wrk_0", "wrk_2"]
    # Behind the limit it takes nothing from the works ahead of it.
    assert fulltext.safe_to_fetch(works, [*order[:1], *order[2:], order[1]], 3, (), 0, {"wrk_1"},
                                  NO_BASELINE) == ["wrk_0", "wrk_2", "wrk_3"]


def test_already_text_is_not_fetched_and_takes_no_slot():
    works = [work(0, has_text=True), work(1), work(2)]
    order = [w["head"] for w in works]
    baseline = fulltext.baseline_of(works)
    assert baseline["has_text"] == ["wrk_0"]
    assert fulltext.safe_to_fetch(works, order, 2, (), 0, set(), baseline) == ["wrk_1", "wrk_2"]


def test_a_fresh_code_of_this_stage_settles_a_work_and_a_stale_one_does_not():
    works = [work(0, fulltext_row=code("no_fulltext")), work(1, fulltext_row=code("no_fulltext", stale=True)),
             work(2)]
    order = [w["head"] for w in works]
    baseline = fulltext.baseline_of(works)
    assert baseline["settled"] == ["wrk_0"]
    assert fulltext.safe_to_fetch(works, order, 3, (), 0, set(), baseline) == ["wrk_1", "wrk_2"]


def test_a_work_of_several_versions_is_read_by_work_and_keeps_its_place_when_its_head_changes():
    works = [work(0, versions=2), work(1)]
    order = [w["head"] for w in works]
    assert fulltext.safe_to_fetch(works, order, 1, (), 0, set(), NO_BASELINE) == ["wrk_0"]
    # Its second record heads the work now (a chain record joined to it); the order read by work finds it.
    moved = [dict(works[0], head=works[0]["versions"][1]["id"]), works[1]]
    assert fulltext.safe_to_fetch(moved, [moved[0]["head"], moved[1]["head"]], 1, (), 0, set(), NO_BASELINE) == ["wrk_0"]


def test_the_chain_room_is_its_own_and_a_pending_chain_work_takes_no_keyword_slot():
    works = [work(0), work(1), work(2, chained=True), work(3, "abstract_not_proposed", chained=True)]
    order, chain_order = [works[0]["head"], works[1]["head"]], [works[3]["head"], works[2]["head"]]
    assert fulltext.safe_to_fetch(works, order, 2, chain_order, 1, {"wrk_3"}, NO_BASELINE) == ["wrk_0", "wrk_1"]
    assert fulltext.safe_to_fetch(works, order, 2, chain_order, 2, {"wrk_3"}, NO_BASELINE) == ["wrk_0", "wrk_1", "wrk_2"]


def test_the_baseline_masks_the_codes_and_texts_the_fetch_wrote_itself():
    """Sol, finding 4: a work the fetch settled or gave a text must not drop out and let the works behind move up."""
    works = [work(n) for n in range(4)]
    order = [w["head"] for w in works]
    baseline = fulltext.baseline_of(works)
    before = fulltext.safe_to_fetch(works, order, 2, (), 0, set(), baseline)
    after = [dict(works[0], versions=[dict(works[0]["versions"][0], has_text=True, fulltext=code("not_read_yet"))]),
             dict(works[1], versions=[dict(works[1]["versions"][0], fulltext=code("no_fulltext"))]), *works[2:]]
    assert before == ["wrk_0", "wrk_1"]
    assert fulltext.safe_to_fetch(after, order, 2, (), 0, set(), baseline) == before
    assert final_ids(after, order, 2, baseline=baseline) == before
    # Without the baseline the two settled works would leave the plan and two others would be fetched too.
    assert final_ids(after, order, 2, baseline=fulltext.baseline_of(after)) == ["wrk_2", "wrk_3"]


def test_a_human_decision_is_read_as_it_is_under_the_baseline():
    human = work(0, fulltext_row=code("no_fulltext", decided_by="human"))
    works = [human, work(1)]
    order = [w["head"] for w in works]
    assert fulltext.safe_to_fetch(works, order, 2, (), 0, set(), fulltext.baseline_of(works)) == ["wrk_1"]


def test_a_broken_condition_is_what_makes_an_early_work_leave_the_plan():
    """A person's selection is outside the proof (decision 2): the early work leaves the final plan, and only then."""
    works = [work(n) for n in range(3)]
    order = [w["head"] for w in works]
    safe = fulltext.safe_to_fetch(works, order, 2, (), 0, set(), NO_BASELINE)
    excluded = [dict(works[0], selection={"state": "excluded", "origin": "user"}), *works[1:]]
    assert safe == ["wrk_0", "wrk_1"] and final_ids(excluded, order, 2) == ["wrk_1", "wrk_2"]


def test_the_baseline_digest_does_not_depend_on_the_order_the_works_were_read_in():
    works = [work(n, has_text=n % 2 == 0, fulltext_row=code("no_fulltext") if n % 3 == 0 else None) for n in range(9)]
    fixed = {"as_of": "2026-09-24T00:00:00Z", "scope_revision": 1, "criterion_hash": None, "limit": 80,
             "chain_room": 12, "keyword_order_step": "stp_1"}
    one = fulltext.baseline_of(works, **fixed)
    other = fulltext.baseline_of(list(reversed(works)), **fixed)
    assert one == other and one["hash"] == other["hash"]
    assert fulltext.baseline_of(works, **(fixed | {"limit": 79}))["hash"] != one["hash"]
