"""The delivery-time targets, the handover moment and what the measurement reads back.

The design gives each depth an end-to-end target for the first sourced answer and a moment by which the run must
turn to writing it. Both count on the person's clock, from the question's submission, so the queue, the gaps
between stages and any pause are inside them. These tests hold the frozen numbers and the three ways a run can
reach the handover with time it never spent working: a long queue, a pause, and an earlier stage overrunning.
"""

import sqlite3
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from deixis.domain import canonical
from deixis.domain.rules import TEST_EFFORT_BUDGETS
from deixis.storage import db
from deixis.workflow.run import fast_path
from deixis.workflow.run.store import Store
from deixis.workflow.search import small_batch
from test_fast_path_clock import FakeClock

sys.path.append(str(Path(__file__).resolve().parents[2] / "scripts" / "benchmark"))
from delivery_time import anchors, ledgers, reports, summary  # noqa: E402

# What the design asks of each depth, in seconds: the end-to-end target for the first sourced answer, and the
# latest moment the run hands over to writing it. Frozen here so a later change to the stage split cannot drift
# away from the design without this test saying so.
TARGETS = {"quick": (60, 35), "standard": (120, 70), "detailed": (300, 210)}


@pytest.fixture
def lab(tmp_path):
    """A library, a fake clock and a factory for a discovery run at any depth."""
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    clock = FakeClock()
    store = Store(conn, clock)
    clock.store = store

    def run_at(effort, *, local_model=False, policy_edit=None):
        rid = store.create_research(f"SYNTHETIC {effort}", "academic", effort, ["openalex"], "fake", "fake-model", "en")
        budget = small_batch.freeze_budget(TEST_EFFORT_BUDGETS[effort].__dict__, effort, "off")
        policy = fast_path.freeze_budget(budget, effort, local_model=local_model)
        if policy_edit:
            policy = {k: v for k, v in policy.items() if k != "policy_hash"}
            policy_edit(policy)
            policy["policy_hash"] = canonical.sha256_hex(policy)
        budget["fast_path"] = policy
        run = store.create_run(rid, "discovery", budget, None)
        store.update_run(run["id"], status="running")
        return SimpleNamespace(store=store, conn=conn, clock=clock, rid=rid, run=store.run(run["id"]))

    yield SimpleNamespace(store=store, conn=conn, clock=clock, run_at=run_at)
    conn.close()


def _answer_run(lab_run, effort):
    """The answer run the app queues once discovery completes, bound to the same ledger."""
    lab_run.store.update_run(lab_run.run["id"], status="completed")
    budget = small_batch.answer_budget(lab_run.store, lab_run.rid, 1, TEST_EFFORT_BUDGETS[effort].__dict__)
    budget = fast_path.answer_budget(lab_run.store, lab_run.rid, 1, budget)
    run = lab_run.store.create_run(lab_run.rid, "answer", budget, None)
    lab_run.store.update_run(run["id"], status="running")
    return lab_run.store.run(run["id"])


def _finish(lab_run, stage, seconds):
    fast_path.enter_stage(lab_run.store, lab_run.run, stage)
    lab_run.clock.advance(seconds)
    fast_path.close_stage(lab_run.store, lab_run.run["id"], stage)


@pytest.mark.parametrize("effort", sorted(TARGETS))
def test_every_depth_keeps_the_designs_target_and_handover(effort):
    target, handover = TARGETS[effort]
    bases = fast_path.MODES[effort].stage_seconds
    assert sum(bases) == target, f"{effort}: the stage bases must sum to the end-to-end target"
    assert sum(bases[:len(fast_path.PRE_ANSWER)]) == handover, f"{effort}: the pre-answer bases must sum to the handover"
    # The answer stage is what is left of the target after the handover, which is the design's own arithmetic.
    assert bases[-1] == target - handover


@pytest.mark.parametrize("effort", sorted(TARGETS))
def test_the_frozen_policy_names_the_handover_rule_and_its_moment(lab, effort):
    policy = lab.run_at(effort).run["budget"]["fast_path"]
    assert policy["handover_rule"] == fast_path.HANDOVER_RULE
    assert policy["handover_ms"] == TARGETS[effort][1] * 1000
    assert policy["total_ms"] == TARGETS[effort][0] * 1000
    assert policy["policy_hash"] == canonical.sha256_hex({k: v for k, v in policy.items() if k != "policy_hash"})


def test_a_local_model_run_keeps_no_handover_and_says_so_by_name(lab):
    """A departure from the design, readable in the run's own record rather than a missing key: the depth's targets
    assume a model the stage bases were measured against. Held to no target either, here and in the measurement."""
    lib = lab.run_at("standard", local_model=True)
    policy = lib.run["budget"]["fast_path"]
    assert policy["handover"] == "none_local_model" and "handover_ms" not in policy
    assert fast_path.handover_deadline(lib.store, lib.run) is None
    _finish(lib, "read", 900)
    lib.store.update_run(lib.run["id"], status="failed")
    assert fast_path.view(lib.store, lib.store.run(lib.run["id"]))["on_target"] is None


def test_a_policy_frozen_before_the_rule_keeps_its_stage_deadline_alone(lab):
    lib = lab.run_at("standard", policy_edit=lambda p: [p.pop("handover_rule"), p.pop("handover_ms"),
                                                        p.pop("evidence_minimum")])
    _finish(lib, "plan", 8)
    fast_path.enter_stage(lib.store, lib.run, "search")
    lib.clock.advance(200)
    fast_path.close_stage(lib.store, lib.run["id"], "search")
    fast_path.enter_stage(lib.store, lib.run, "read")
    assert fast_path.handover_deadline(lib.store, lib.run) is None
    # Its read deadline is its own floor from the moment it opened, as it was before the rule.
    deadline = fast_path.stage_deadline(lib.store, lib.run, "read")
    assert deadline == lib.clock.now() + timedelta(milliseconds=int(33000 * 0.25))


def test_a_long_queue_is_inside_the_handover(lab):
    """The run was created when the question was submitted and only began working 40 seconds later. Standard hands
    over at second 70, so reading gets the 30 seconds that are left, not its own 33."""
    # The handover as a cutoff is the rule before the evidence minimum, under which it cuts no stage.
    lib = lab.run_at("standard", policy_edit=lambda p: p.pop("evidence_minimum"))
    lib.clock.advance(40)
    _finish(lib, "plan", 0)
    fast_path.enter_stage(lib.store, lib.run, "read")
    started = fast_path.ledger_started_at(lib.store, lib.run)
    assert fast_path.stage_deadline(lib.store, lib.run, "read") == started + timedelta(seconds=70)
    lib.clock.advance(29)
    assert not fast_path.past_deadline(lib.store, lib.run, "read")
    lib.clock.advance(1)
    assert fast_path.past_deadline(lib.store, lib.run, "read")


def test_the_handover_moment_itself_is_already_past(lab):
    """The boundary belongs to the answer: at exactly the handover second the run hands over."""
    lib = lab.run_at("standard")
    fast_path.enter_stage(lib.store, lib.run, "read")
    lib.clock.advance(70)
    assert lib.clock.now() == fast_path.handover_deadline(lib.store, lib.run)
    assert fast_path.past_deadline(lib.store, lib.run, "read")


def test_a_pause_gives_no_fresh_window(lab):
    """A run that stopped overnight and resumed has missed its target; it does not start a new 70 seconds. Its own
    stage accounting excludes the downtime, which is why the handover is read from the clock and not from it."""
    # The handover as a cutoff is the rule before the evidence minimum, under which it cuts no stage.
    lib = lab.run_at("standard", policy_edit=lambda p: p.pop("evidence_minimum"))
    _finish(lib, "plan", 5)
    lib.clock.advance(9 * 60 * 60)  # the person's computer was asleep
    fast_path.enter_stage(lib.store, lib.run, "read")
    # The stage's own accounting still has time: it spent five seconds in all.
    assert fast_path.stage_deadline(lib.store, lib.run, "read") < lib.clock.now()
    assert fast_path.past_deadline(lib.store, lib.run, "read")


def test_an_earlier_stage_overrunning_cannot_push_the_first_answer_past_the_target(lab):
    """Search keeps its whole base however badly the plan overran, and a later stage keeps a quarter of its own, so
    before the handover nothing stopped the pre-answer stages from passing the target between them."""
    # The handover as a cutoff is the rule before the evidence minimum, under which it cuts no stage.
    lib = lab.run_at("standard", policy_edit=lambda p: p.pop("evidence_minimum"))
    _finish(lib, "search", 180)
    fast_path.enter_stage(lib.store, lib.run, "ranking")
    assert fast_path.past_deadline(lib.store, lib.run, "ranking")
    fast_path.close_stage(lib.store, lib.run["id"], "ranking")
    fast_path.enter_stage(lib.store, lib.run, "read")
    assert fast_path.past_deadline(lib.store, lib.run, "read")


def test_the_answer_stage_is_not_cut_by_the_handover(lab):
    """The handover is the moment writing starts, so it bounds the stages before it and never the writing itself: a
    run that reached the handover late still gets its whole writing budget, because a cut there would leave the
    person a draft instead of an answer."""
    lib = lab.run_at("standard")
    _finish(lib, "plan", 0)
    _finish(lib, "search", 0)
    _finish(lib, "ranking", 0)
    _finish(lib, "read", 300)
    # The run reached the handover 230 seconds late.
    assert fast_path.handover_deadline(lib.store, lib.run) < lib.clock.now()
    answer = _answer_run(lib, "standard")
    fast_path.enter_stage(lib.store, answer, "answer")
    # Writing keeps a deadline of its own, late handover or not: a cut here would leave the person a draft instead
    # of an answer, and the answer run's binding carries no handover at all.
    assert "handover_ms" not in answer["budget"]["fast_path"]
    deadline = fast_path.stage_deadline(lib.store, answer, "answer")
    assert deadline is not None and deadline > lib.clock.now()


def test_the_run_view_says_where_it_stood_against_its_target(lab):
    """The handover moment is when writing actually started, which is the answer stage opening: the read stage
    closing comes before the optional title call and before the answer run is queued."""
    lib = lab.run_at("standard")
    _finish(lib, "plan", 10)
    _finish(lib, "search", 20)
    _finish(lib, "ranking", 10)
    _finish(lib, "read", 25)
    answer = _answer_run(lib, "standard")
    lib.clock.advance(3)  # the title call and queuing the answer sit between the two
    fast_path.enter_stage(lib.store, answer, "answer")
    view = fast_path.view(lib.store, lib.store.run(answer["id"]))
    assert (view["target_ms"], view["handover_ms"]) == (120000, 70000)
    # Turned to writing at second 68 of the person's clock, inside the 70 the depth allows.
    assert view["handover_at_ms"] == 68000 and view["handover_on_target"] is True
    # Nothing is published yet and the answer has not ended, so the end-to-end target is undecided.
    assert view["latency_ms"] is None and view["on_target"] is None and view["handover_passed_at"] is None


def test_an_answer_that_never_published_missed_the_target(lab):
    """The person was given no sourced answer inside the depth's target, so the run missed it; it is undecided only
    while a valid answer may still arrive."""
    lib = lab.run_at("standard")
    _finish(lib, "plan", 2)
    _finish(lib, "search", 2)
    _finish(lib, "ranking", 2)
    _finish(lib, "read", 2)
    answer = _answer_run(lib, "standard")
    fast_path.enter_stage(lib.store, answer, "answer")
    assert fast_path.view(lib.store, lib.store.run(answer["id"]))["on_target"] is None
    fast_path.save_answer(lib.store, answer["id"], "unverified_draft")
    assert fast_path.view(lib.store, lib.store.run(answer["id"]))["on_target"] is False


def test_the_missed_moment_is_recorded_when_a_stage_sees_it_pass(lab):
    """Recorded by whichever stage first reads the clock after the moment, so a run that spent its whole budget in
    the plan stage is marked rather than looking untimed."""
    lib = lab.run_at("standard")
    fast_path.enter_stage(lib.store, lib.run, "plan")
    lib.clock.advance(400)  # a model call that took minutes, or a run resumed the next morning
    fast_path.note_handover_passed(lib.store, lib.run)
    passed = lib.conn.execute("SELECT handover_passed_at FROM fast_path_ledgers WHERE ledger_run_id = ?",
                              (lib.run["id"],)).fetchone()[0]
    assert passed is not None
    # Written once: a later stage does not move it.
    lib.clock.advance(100)
    fast_path.note_handover_passed(lib.store, lib.run)
    assert lib.conn.execute("SELECT handover_passed_at FROM fast_path_ledgers WHERE ledger_run_id = ?",
                            (lib.run["id"],)).fetchone()[0] == passed


def test_a_retried_search_of_a_completed_run_still_stops_at_the_handover(lab):
    """Retrying a failed search opens a rework interval, which the stage accounting does not give a deadline; the
    handover reaches it all the same, because the person's clock has run out either way. Queued through the
    application's own retry, so the budget it writes is the one the resumed run reads."""
    # The handover as a cutoff is the rule before the evidence minimum, under which it cuts no stage.
    lib = lab.run_at("standard", policy_edit=lambda p: p.pop("evidence_minimum"))
    _finish(lib, "search", 2)
    lib.conn.execute(
        "INSERT INTO run_steps (id, run_id, operation_key, kind, status, attempt) VALUES (?, ?, ?, ?, 'failed', 1)",
        ("stp_synthetic_retry", lib.run["id"], "search:fast:openalex:1", "provider_search:openalex"))
    lib.store.update_run(lib.run["id"], status="completed")
    lib.clock.advance(300)
    lib.store.queue_failed_search_retry(lib.run["id"])
    lib.store.update_run(lib.run["id"], status="running")
    run = lib.store.run(lib.run["id"])
    assert run["budget"]["retry_provider_requests"] == 1
    fast_path.enter_stage(lib.store, run, "search")
    rework = lib.conn.execute("SELECT rework FROM fast_path_intervals WHERE run_id = ? AND stage = 'search'"
                              " ORDER BY rowid DESC LIMIT 1", (run["id"],)).fetchone()[0]
    assert rework == 1
    assert fast_path.past_deadline(lib.store, run, "search")
    assert lib.conn.execute("SELECT handover_passed_at FROM fast_path_ledgers WHERE ledger_run_id = ?",
                            (run["id"],)).fetchone()[0] is not None


def test_under_the_evidence_minimum_a_retried_search_keeps_a_deadline_of_its_own(lab):
    """The handover cuts no stage under the evidence minimum, so a rework interval, which has no stage accounting,
    keeps the search stage's allocation or its minimum from its own start instead of running without a deadline."""
    lib = lab.run_at("standard")
    _finish(lib, "search", 2)
    lib.conn.execute(
        "INSERT INTO run_steps (id, run_id, operation_key, kind, status, attempt) VALUES (?, ?, ?, ?, 'failed', 1)",
        ("stp_synthetic_retry", lib.run["id"], "search:fast:openalex:1", "provider_search:openalex"))
    lib.store.update_run(lib.run["id"], status="completed")
    lib.clock.advance(300)
    lib.store.queue_failed_search_retry(lib.run["id"])
    lib.store.update_run(lib.run["id"], status="running")
    run = lib.store.run(lib.run["id"])
    fast_path.enter_stage(lib.store, run, "search")
    alloc = lib.conn.execute("SELECT alloc_ms FROM fast_path_stages WHERE ledger_run_id = ? AND stage = 'search'",
                             (run["id"],)).fetchone()[0]
    deadline = fast_path.stage_deadline(lib.store, run, "search")
    assert deadline == lib.clock.now() + timedelta(milliseconds=max(alloc, fast_path.EVIDENCE_SEARCH_MS))
    assert not fast_path.past_deadline(lib.store, run, "search")
    # The handover's passing is still recorded.
    assert lib.conn.execute("SELECT handover_passed_at FROM fast_path_ledgers WHERE ledger_run_id = ?",
                            (run["id"],)).fetchone()[0] is not None


def test_the_depth_text_names_no_length_of_time():
    """A depth's budgets aim at a target whose attainment is measured, so the label promises reading, not minutes."""
    limits = fast_path.effort_limits()
    assert set(limits["efforts"]) == {"quick", "standard", "detailed"}
    for depth in limits["efforts"].values():
        assert "minutes" not in depth and set(depth) == {"papers", "fulltext"}


def test_the_measurement_reads_the_times_back_and_keeps_local_runs_apart(lab):
    """What the tool reports is the time to the answer being RECORDED: the display is not timed anywhere. It goes
    through the real answer run, so the handover moment it reads is the answer stage opening and the citations it
    counts are the published answer's own."""
    paced = lab.run_at("standard")
    _finish(paced, "plan", 5)
    _finish(paced, "search", 10)
    _finish(paced, "ranking", 10)
    _finish(paced, "read", 20)
    answer = _answer_run(paced, "standard")
    fast_path.enter_stage(paced.store, answer, "answer")
    paced.clock.advance(30)
    paced.store.save_answer(paced.rid, answer["id"], None, None, 1, "structurally_valid",
                            {"title": "SYNTHETIC answer", "claims": []}, {"ok": True})
    fast_path.save_answer(paced.store, answer["id"], "structurally_valid")
    paced.store.update_run(answer["id"], status="completed")

    # A run that ended without ever answering: it gave the person no sourced answer inside the target, so it missed
    # it rather than being left out of the rate.
    silent = lab.run_at("standard")
    _finish(silent, "read", 2)
    silent.store.update_run(silent.run["id"], status="failed")

    local = lab.run_at("standard", local_model=True)
    _finish(local, "read", 400)

    conn = sqlite3.connect(lab.conn.execute("PRAGMA database_list").fetchone()[2])
    conn.row_factory = sqlite3.Row
    try:
        rows = ledgers(conn)
        result = summary(rows, reports(conn))
    finally:
        conn.close()
    standard = result["modes"]["standard"]
    assert (standard["runs"], standard["valid_answers"]) == (2, 1)
    assert (standard["target_ms"], standard["handover_ms"]) == (120000, 70000)
    # 45 s of stages, then writing: recorded at second 75, inside the 120 the depth allows. The run that never
    # answered is in the denominator, so the rate is one in two.
    assert standard["to_record_median_ms"] == 75000
    assert standard["on_target_to_record"] == {"n": 2, "met": 1, "rate": 0.5}
    assert standard["still_running"] == 0
    # Writing began at second 45, when the answer stage opened.
    assert standard["handover_at_median_ms"] == 45000 and standard["handover_on_target"]["rate"] == 1.0
    assert standard["stages"]["read"]["median_ms"] == 11000
    # The published answer here cites nothing; the counting itself is tested below.
    assert standard["citations"] == {"links": 0, "located": 0}
    # The local run is summarized apart and is held to no target.
    assert result["local"]["runs"] == 1 and result["local"]["handover_ms"] is None
    assert result["local"]["on_target_to_record"]["n"] == 0
    assert result["reports"] == {"n": 0, "finalized": 0, "to_finalized_median_ms": None, "to_finalized_worst_ms": None}


def test_a_published_answers_citations_are_counted_as_located_or_not():
    """An anchor says the quoted words were found in a passage the step was given, which is a structural fact and
    never a judgement that the passage supports the claim. Counted over the three tables the query reads."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE answers (id TEXT PRIMARY KEY, run_id TEXT, status TEXT, created_at TEXT);
        CREATE TABLE claims (id TEXT PRIMARY KEY, answer_id TEXT);
        CREATE TABLE evidence_links (id TEXT PRIMARY KEY, claim_id TEXT, anchor_match TEXT);
        INSERT INTO answers VALUES ('a1', 'run_1', 'structurally_valid', '2026-11-10T00:00:00Z');
        INSERT INTO answers VALUES ('a0', 'run_1', 'unverified_draft', '2026-11-09T00:00:00Z');
        INSERT INTO claims VALUES ('c1', 'a1'), ('c2', 'a1'), ('c9', 'a0');
        INSERT INTO evidence_links VALUES ('e1', 'c1', 'exact'), ('e2', 'c2', NULL), ('e9', 'c9', 'exact');
    """)
    try:
        # The draft's own citation is not counted: the published answer is the one the person was given.
        assert anchors(conn, "run_1") == {"links": 2, "located": 1}
        assert anchors(conn, "run_other") is None
    finally:
        conn.close()


def test_the_gap_between_two_stages_cannot_hide_the_moment(lab):
    """Read closes inside the handover, the optional title call and queuing the answer then take it past, and the
    answer stage opening is where that is seen. Every stage opening reads the clock for this reason."""
    lib = lab.run_at("standard")
    _finish(lib, "plan", 5)
    _finish(lib, "search", 5)
    _finish(lib, "ranking", 5)
    _finish(lib, "read", 50)  # read closed at second 65, inside the 70
    assert lib.conn.execute("SELECT handover_passed_at FROM fast_path_ledgers WHERE ledger_run_id = ?",
                            (lib.run["id"],)).fetchone()[0] is None
    answer = _answer_run(lib, "standard")
    lib.clock.advance(10)  # the title call
    fast_path.enter_stage(lib.store, answer, "answer")
    view = fast_path.view(lib.store, lib.store.run(answer["id"]))
    assert view["handover_at_ms"] == 75000 and view["handover_on_target"] is False
    assert view["handover_passed_at"] is not None


def test_a_research_that_queues_no_answer_is_left_out_of_the_rate(lab):
    """A research asking only for papers, a table, a comparison or a check of its own sentence never queues an
    answer, so counting it as a miss would push the rate down by how often those are used."""
    lib = lab.run_at("standard", policy_edit=lambda p: p.update(fast_path.with_intent(dict(p), "papers")))
    assert lib.run["budget"]["fast_path"]["auto_answer"] is False
    _finish(lib, "read", 2)
    lib.store.update_run(lib.run["id"], status="completed")
    conn = sqlite3.connect(lab.conn.execute("PRAGMA database_list").fetchone()[2])
    conn.row_factory = sqlite3.Row
    try:
        rows = ledgers(conn)
        result = summary(rows, reports(conn))
    finally:
        conn.close()
    assert rows[0]["no_answer_intended"] is True and rows[0]["on_target_to_record"] is None
    assert result["modes"] == {} and result["no_answer_intended"] == 1


def test_the_reranker_allowance_is_frozen_per_depth_and_not_for_a_local_model(lab):
    # Quick's list now waits for the reranker as the other depths' do, so it keeps the same allowance; a local-model
    # run keeps its own arithmetic and names no key, so its policy is the one frozen before the rule.
    for effort, ms in (("quick", 3000), ("standard", 3000), ("detailed", 3000)):
        policy = lab.run_at(effort).run["budget"]["fast_path"]
        assert policy["rerank_allowance"] == {"rule": fast_path.RERANK_ALLOWANCE_RULE, "ms": ms}
        assert fast_path.rerank_allowance_ms({"fast_path": policy}) == ms
    assert "rerank_allowance" not in lab.run_at("standard", local_model=True).run["budget"]["fast_path"]
    # The reranked-window word rule is frozen at every depth and for every model, inside the policy's own hash.
    for effort, local in (("quick", False), ("standard", True), ("detailed", False)):
        policy = lab.run_at(effort, local_model=local).run["budget"]["fast_path"]
        assert fast_path.window_word_rule(policy) and policy["window_word_rule"] == fast_path.WINDOW_WORD_RULE
        body = {key: value for key, value in policy.items() if key not in ("policy_hash", "intent")}
        assert canonical.sha256_hex(body) == policy["policy_hash"]
    # The number-form rule of the plan's quoted phrases is frozen at every depth and for every model.
    for effort, local in (("quick", False), ("standard", True), ("detailed", False)):
        assert fast_path.phrase_forms_on(lab.run_at(effort, local_model=local).run["budget"])
