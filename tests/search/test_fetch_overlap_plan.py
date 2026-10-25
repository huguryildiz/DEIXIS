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


def test_a_human_decision_is_read_as_it_is_under_the_baseline():
    human = work(0, fulltext_row=code("no_fulltext", decided_by="human"))
    works = [human, work(1)]
    order = [w["head"] for w in works]
    assert fulltext.safe_to_fetch(works, order, 2, (), 0, set(), fulltext.baseline_of(works)) == ["wrk_1"]
