"""Frozen policy, durable active wall time and stage-specific soft deadlines."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, NamedTuple, Protocol

from deixis.domain import canonical
from deixis.storage.db import new_id, transaction

POLICY = "fast_path_v1"
RUNNER_VERSION = 2
STAGES = ("plan", "search", "ranking", "read", "answer")
# The search method a discovery run is queued with, frozen in its policy. `legacy` is every run's default:
# chain admission `fast_chain_v1`. `m1` selects chain admission `fast_chain_v2`; it is for the M1 measurement
# until all its gates pass.
# `m2` adds the search plan the model writes from the first semantic page (`search_plan_v1`): its terms carry the
# record, field and span they were read from, and it names the works the citation chain starts from. A query written
# under one method is never reused by a run of another (`store.search_query_of`).
SEARCH_METHODS = ("legacy", "m1", "m2")
# The plan rule `m2` freezes: one model call reads the first semantic page and writes the terms, their blocks and the
# chain's starting works. It replaces the three labelling calls and the query call of the older methods.
PLAN_RULE = "search_plan_v1"
# The chain admission rules a run's budget can freeze. v3 (the `m2` method) matches words as v2 does and adds the
# rescue quota: a few linked records the gate blocks' words do not reach are still written as ranked candidates.
CHAIN_RULES = ("fast_chain_v1", "fast_chain_v2", "fast_chain_v3")
# The deeper screening: a Standard or Detailed discovery queued with the option on also screens the next
# `DEEP_SCREENING_WORKS` works of the frozen list, places N+1..N+100, one model read per batch. Frozen in the policy under
# its rule's name; a policy without the key screens 1..N only, as before.
DEEP_SCREENING_RULE = "m3_v1"
# Which of a record's found copies is downloaded first (`acquisition.candidate_order`): a fixed provider priority,
# then the version and the identity, then the URL — never the order the providers happened to answer in. Frozen in
# the policy, so the choice an older run made can be read back as the rule it was made under.
ACQUIRE_RULE = "fast_acquire_v1"
DEEP_SCREENING_WORKS = 100
DEEP_SCREENING_EFFORTS = ("standard", "detailed")


class Mode(NamedTuple):
    """One research depth's numbers, frozen into a run's budget by `freeze_budget`."""
    stage_seconds: tuple[int, int, int, int, int]  # soft deadline of each of STAGES, in order
    read_top: int  # N: the top of the ranking a run reads
    fulltext_works: int  # K: the most works a run reads in full text
    keyword_record_cap: int
    chain_seeds: int  # the works citation chaining starts from: none in Quick, one in Standard, three in Deep
    backward_requests: int
    forward_requests: int
    boolean_plans: int  # the most distinct Boolean query plans a run of this depth sends: one main, the rest focused
    chain_rescue: int  # the most linked records the gate's words do not reach that are still written as candidates
    rerank_pool: float  # the most records the reranker reads, as a multiple of N; a saved factor is kept under it
    rerank_point: str  # "before_list": the list waits for the reranker; "after_list": it is frozen first (Quick)


MODES = {
    # Quick opens no citation request of its own: the reference ids the first semantic page brings are stored and
    # the links inside that page are written, which costs nothing, but no seed work is read.
    "quick": Mode((30, 30, 30, 60, 30), read_top=25, fulltext_works=10, keyword_record_cap=450, chain_seeds=0,
                  backward_requests=0, forward_requests=0, boolean_plans=1, chain_rescue=0,
                  # Quick shows its list without waiting for the reranker, so the reranker does not order that list:
                  # it reads a small group after the list is frozen, and the run keeps its scores to be measured.
                  rerank_pool=2.0, rerank_point="after_list"),
    "standard": Mode((30, 45, 60, 120, 45), read_top=50, fulltext_works=20, keyword_record_cap=1000, chain_seeds=1,
                     backward_requests=4, forward_requests=8, boolean_plans=2, chain_rescue=5,
                     rerank_pool=8.0, rerank_point="before_list"),
    "detailed": Mode((45, 90, 120, 270, 75), read_top=100, fulltext_works=40, keyword_record_cap=2000, chain_seeds=3,
                     backward_requests=8, forward_requests=16, boolean_plans=3, chain_rescue=10,
                     # 8 x 100 is past the reranker's own 400-record limit, so Deep reads the widest window there is.
                     rerank_pool=8.0, rerank_point="before_list"),
}


class LedgerMismatch(RuntimeError):
    """The stored fast-path ledger or stage intervals contradict the run being written."""


class Clock(Protocol):
    def now(self) -> datetime: ...

    async def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


def timestamp(clock: Clock) -> str:
    return clock.now().isoformat(timespec="milliseconds")


def elapsed(start: str, end: str) -> int:
    delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
    return max(0, delta // timedelta(milliseconds=1))


def freeze_budget(budget: dict[str, Any], effort: str, local_model: bool = False,
                  method: str = "legacy", deep_screening: bool = False,
                  lexical_exclusion: bool = True, candidate_embedding: bool = True) -> dict[str, Any]:
    """A run on a model this computer runs (`local_model`) keeps no deadline on the stages where the model works,
    read and answer: a local model screens and answers far slower than the stage bases assume, and a cut read
    leaves the answer unscreened evidence. Search and ranking do not wait on the model and keep theirs; each model
    call still has its own limit (openai_compat.LOCAL_TURN_TIMEOUT).

    `method` is the search method (`SEARCH_METHODS`). A `legacy` policy is exactly the one frozen before `m1`, so
    its hash does not move; `m1` names itself and its two rules.

    `deep_screening` adds the deeper screening's window under `deep_screening`; off adds nothing, so a policy
    frozen without it is byte for byte the one frozen before, hash included. Quick takes no window.

    `candidate_embedding` off records that this run embeds no candidate, so the ranking's embedding signal is left
    out and says why; the reranker reads titles and abstracts as text and needs no embedding. On adds nothing.

    `lexical_exclusion` off records that the abstract stage may not close a record for naming neither gate block
    (`flow._abstract_code_stage`); on adds nothing and leaves the policy as it was. The arm is frozen here, so a
    resumed run screens the way it was queued and the two arms of the measurement stay apart."""
    if method not in SEARCH_METHODS:
        raise ValueError(f"unknown search method {method!r}")
    mode = MODES[effort]
    bases = mode.stage_seconds
    policy = {
        "policy": POLICY, "runner_version": RUNNER_VERSION, "enforcement": ["search", "ranking", "read", "answer"],
        "enforced_stages": ["search", "ranking", "read", "answer"], "background_fetch_slots": 4,
        "approval_mode": "unattended", "auto_answer": True,
        "late_revision": {"mode": "auto", "max_revisions": 1},
        "mode": "deep" if effort == "detailed" else effort,
        "stage_base_ms": dict(zip(STAGES, (s * 1000 for s in bases))), "total_ms": sum(bases) * 1000,
        "N": mode.read_top, "K": mode.fulltext_works, "keyword_record_cap": mode.keyword_record_cap, "semantic_top": 50,
        "chain_seeds": mode.chain_seeds, "backward_requests": mode.backward_requests, "backward_page_size": 50,
        "forward_requests": mode.forward_requests, "forward_page_size": 25,
        "chain_in_flight": 5, "chain_rule": "fast_chain_v1", "acquire_rule": ACQUIRE_RULE,
        "embedding_threads": 4, "fetch_slots": 12, "slot_refill": True, "read_drain_ms": 5000, "arrival_margin_ms": 5000,
        "checkpoint_ms": 5000, "floor_ratio": 0.25,
        # Search always gets at least its own base; an earlier overrun is charged to the later stages instead.
        "protected_stages": ["search"],
        # K admission takes the abstract stage's unresolved works after the candidates (`read.selected`).
        "admission_order": "unresolved_last",
    }
    if method in ("m1", "m2"):
        policy |= {"search_method": method, "chain_rule": "fast_chain_v2"}
    if method == "m2":
        # The chain keeps v2's word matching and adds the rescue quota: `chain_rescue` linked records the gate's
        # words do not reach are written as ranked candidates, and the gate's own verdict on them is still recorded.
        policy |= {"chain_rule": "fast_chain_v3", "chain_rescue": mode.chain_rescue}
        # The model writes the plan from the first semantic page; the chain starts from the works it names.
        # `boolean_plans` counts the distinct Boolean query plans the run may send, the main one included; one plan
        # still goes to every enabled provider in that provider's syntax, and those requests are counted elsewhere.
        policy |= {"plan_rule": PLAN_RULE, "boolean_plans": mode.boolean_plans}
    if deep_screening:
        if effort not in DEEP_SCREENING_EFFORTS:
            raise ValueError(f"deeper screening is not offered at {effort!r}")
        from deixis.domain.rules import ABSTRACT_BATCH
        policy["deep_screening"] = {"rule": DEEP_SCREENING_RULE, "first": mode.read_top + 1,
                                    "last": mode.read_top + DEEP_SCREENING_WORKS, "runs": 1, "batch": ABSTRACT_BATCH}
    if not lexical_exclusion:
        policy["lexical_exclusion"] = False
    if not candidate_embedding:
        policy["candidate_embedding"] = False
    if local_model:
        # Still fast-path stages (`enforces` routes on them); only their deadline is gone.
        policy["no_deadline_stages"] = ["read", "answer"]
    return policy | {"policy_hash": canonical.sha256_hex(policy)}


def with_intent(policy: dict[str, Any], intent: str) -> dict[str, Any]:
    """The frozen policy routed by the research's intent (UI parity S5a): `report` leaves it as it is; `papers` queues
    no answer after discovery; `table` and `compare` queue no answer and open the study table instead
    (`intent.after_discovery`); `statement` queues no answer and checks the research's sentence against the works read
    instead (`statement_check.after_discovery`). The hash covers the routing, so a run keeps the route it was queued
    with."""
    if intent == "report":
        return policy
    routed = {k: v for k, v in policy.items() if k != "policy_hash"} | {"auto_answer": False}
    if intent in ("table", "compare"):
        routed["after_discovery"] = "study_table"
    elif intent == "statement":
        routed["after_discovery"] = "statement_check"
    return routed | {"policy_hash": canonical.sha256_hex(routed)}


def deep_window(policy: dict[str, Any]) -> dict[str, Any] | None:
    """The frozen deeper-screening window of a run's policy, or None when the run was queued without it."""
    deep = policy.get("deep_screening")
    return deep if isinstance(deep, dict) and deep.get("rule") == DEEP_SCREENING_RULE else None


def read_window(policy: dict[str, Any]) -> int:
    """The last list place the run screens: the deeper window's last place when it has one, else N."""
    deep = deep_window(policy)
    return deep["last"] if deep else policy["N"]


def screened_once(effort: str) -> dict[str, int] | None:
    """The list places the deeper screening reads once at this depth, or None where it is not offered."""
    if effort not in DEEP_SCREENING_EFFORTS:
        return None
    n = MODES[effort].read_top
    return {"first": n + 1, "last": n + DEEP_SCREENING_WORKS}


def effort_limits(deep_screening: bool = False) -> dict[str, Any]:
    """What each research depth gives a run, read from MODES at the moment of asking: Home's depth text says these
    numbers, so a changed mode cannot leave the text behind. `minutes` is the stage bases summed and rounded, the
    stages' soft deadlines rather than a promise of how long a run takes; `papers` is N, the top of the ranking a run
    reads; `fulltext` is K, the most works a run reads in their full text (selected pages, UI parity S14's funnel).
    With `deep_screening` on, Standard and Detailed add `screened_once`, the list places read once."""
    return {"efforts": {effort: {"minutes": round(sum(mode.stage_seconds) / 60), "papers": mode.read_top,
                                 "fulltext": mode.fulltext_works,
                                 **({"screened_once": once} if deep_screening and (once := screened_once(effort)) else {})}
                        for effort, mode in MODES.items()}}


def enabled(budget: dict[str, Any]) -> bool:
    return (budget.get("fast_path") or {}).get("policy") == POLICY


def search_method(budget: dict[str, Any]) -> str:
    """The search method a run was queued with: `legacy` for every policy that does not name one."""
    return (budget.get("fast_path") or {}).get("search_method", "legacy")


def candidate_embedding_on(budget: dict[str, Any]) -> bool:
    """Whether this run embeds its candidates. A budget frozen before the switch embedded them, so it still does."""
    return (budget.get("fast_path") or {}).get("candidate_embedding", True)


def chain_on(budget: dict[str, Any]) -> bool:
    return enabled(budget) and budget["fast_path"].get("chain_rule") in CHAIN_RULES


def enforces(budget: dict[str, Any], stage: str) -> bool:
    stages = (budget.get("fast_path") or {}).get("enforced_stages")
    return enabled(budget) and isinstance(stages, list) and stage in stages


def stage_deadline(store: Any, run: dict[str, Any], stage: str) -> datetime | None:
    if not enforces(run["budget"], stage) or stage in run["budget"]["fast_path"].get("no_deadline_stages", ()):
        return None
    ledger = run["budget"]["fast_path"].get("ledger_run_id", run["id"])
    row = store.conn.execute(
        "SELECT i.started_at, s.alloc_ms, s.used_ms FROM fast_path_stages s"
        " JOIN fast_path_intervals i ON i.ledger_run_id = s.ledger_run_id AND i.stage = s.stage"
        " WHERE s.ledger_run_id = ? AND s.stage = ? AND s.status = 'open'"
        " AND i.run_id = ? AND i.closed_at IS NULL AND i.rework = 0",
        (ledger, stage, run["id"])).fetchone()
    if row is None:
        return None
    return datetime.fromisoformat(row["started_at"]) + timedelta(milliseconds=row["alloc_ms"] - row["used_ms"])


def past_deadline(store: Any, run: dict[str, Any], stage: str) -> bool:
    deadline = stage_deadline(store, run, stage)
    return deadline is not None and store.clock.now() >= deadline


def ranking_similarities(store: Any, run: dict[str, Any], model: str) -> dict[str, float]:
    scores = store.source_similarities(run["research_id"], run["scope_revision"], model)
    if not enabled(run["budget"]) or run["kind"] != "discovery":
        return scores
    heads = store.work_heads(run["research_id"])
    for row in store.conn.execute(
            "SELECT q.source_version_id, v.work_id FROM fast_path_embedding_queue q"
            " JOIN source_versions v ON v.id = q.source_version_id"
            " WHERE q.run_id = ? AND q.status = 'unembedded_at_cutoff'", (run["id"],)):
        scores.pop(row["source_version_id"], None)
        scores.pop(heads.get(row["work_id"]), None)
    return scores


def answer_budget(store: Any, rid: str, revision: int, budget: dict[str, Any]) -> dict[str, Any]:
    ledger_id = (budget.get("inspection") or {}).get("list_run_id")
    if not ledger_id:
        return budget
    discovery = store.run(ledger_id)
    policy = discovery["budget"].get("fast_path")
    if not enabled(discovery["budget"]):
        return budget
    ledger = store.conn.execute("SELECT * FROM fast_path_ledgers WHERE ledger_run_id = ?", (ledger_id,)).fetchone()
    if ledger is None or (ledger["research_id"], ledger["scope_revision"], ledger["policy_hash"]) != (rid, revision, policy["policy_hash"]):
        return budget
    return budget | {"fast_path": {"policy": POLICY, "policy_hash": ledger["policy_hash"],
                                   "ledger_run_id": ledger_id, "role": "rerun" if ledger["answer_run_id"] else "first",
                                   **({"enforced_stages": ["answer"]}
                                      if enforces(discovery["budget"], "answer") else {})}}


def create_run(store: Any, run: dict[str, Any]) -> None:
    if not enabled(run["budget"]):
        return
    policy = run["budget"]["fast_path"]
    if run["kind"] == "discovery":
        store.conn.execute(
            "INSERT INTO fast_path_ledgers (ledger_run_id, research_id, scope_revision, policy, policy_hash, mode, started_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run["id"], run["research_id"], run["scope_revision"], POLICY, policy["policy_hash"], policy["mode"], run["created_at"]))
    elif run["kind"] == "answer":
        ledger = store.conn.execute("SELECT * FROM fast_path_ledgers WHERE ledger_run_id = ?", (policy["ledger_run_id"],)).fetchone()
        if ledger is None or (ledger["research_id"], ledger["scope_revision"], ledger["policy_hash"]) != (
                run["research_id"], run["scope_revision"], policy["policy_hash"]):
            raise LedgerMismatch(f"answer run {run['id']}: discovery ledger {policy['ledger_run_id']} is missing or"
                                 " belongs to another research, revision or policy")
        # The role is fixed by the same transaction that queues the answer, rather than by a preceding API read.
        policy["role"] = ("late_revision" if run["budget"].get("late_revision_id")
                          else "rerun" if ledger["answer_run_id"] else "first")
        if policy["role"] == "first":
            store.conn.execute("UPDATE fast_path_ledgers SET answer_run_id = ? WHERE ledger_run_id = ? AND answer_run_id IS NULL",
                               (run["id"], policy["ledger_run_id"]))
        from deixis.storage.db import dumps
        store.conn.execute("UPDATE runs SET budget_json = ? WHERE id = ?", (dumps(run["budget"]), run["id"]))


def enter_stage(store: Any, run: dict[str, Any], stage: str) -> str | None:
    if not enabled(run["budget"]):
        return None
    if run["budget"]["fast_path"].get("role") == "late_revision":
        return None
    conn, ts = store.conn, timestamp(store.clock)
    binding = run["budget"]["fast_path"]
    ledger_id = binding.get("ledger_run_id", run["id"])
    generation = run["budget"].get("retry_provider_requests", 0)
    with transaction(conn):
        if store.run(run["id"])["status"] not in ("running", "pause_requested"):
            return None
        if stage == "answer":
            if binding["role"] == "rerun":
                stage = "answer_rerun"
                if conn.execute("SELECT 1 FROM fast_path_intervals WHERE run_id = ? AND stage = ? AND close_reason = 'stage_done'",
                                (run["id"], stage)).fetchone():
                    return None
            elif conn.execute("SELECT answer_outcome FROM fast_path_ledgers WHERE ledger_run_id = ?", (ledger_id,)).fetchone()[0]:
                return None
        opened = conn.execute("SELECT id FROM fast_path_intervals WHERE run_id = ? AND stage = ? AND closed_at IS NULL",
                              (run["id"], stage)).fetchone()
        if opened:
            return opened[0]
        row = conn.execute("SELECT * FROM fast_path_stages WHERE ledger_run_id = ? AND stage = ?", (ledger_id, stage)).fetchone()
        if row and row["status"] in ("done", "skipped") and row["done_generation"] >= generation:
            return None
        seq = STAGES.index(stage) + 1 if stage in STAGES else 0
        if seq:
            if conn.execute(
                    "SELECT 1 FROM fast_path_intervals i JOIN fast_path_stages s"
                    " ON s.ledger_run_id = i.ledger_run_id AND s.stage = i.stage"
                    " WHERE i.ledger_run_id = ? AND i.closed_at IS NULL AND s.seq > 0 AND s.seq < ?",
                    (ledger_id, seq)).fetchone():
                raise LedgerMismatch(f"run {run['id']}: cannot enter {stage}, a previous stage still has an open interval")
        if row is None and stage != "answer_rerun":
            policy = store.run(ledger_id)["budget"]["fast_path"]
            for ordinal, earlier in enumerate(STAGES[:max(0, seq - 1)], 1):
                conn.execute(
                    "INSERT OR IGNORE INTO fast_path_stages"
                    " (ledger_run_id, stage, seq, base_ms, balance_before_ms, alloc_ms, opened_at, status, done_at, done_generation)"
                    " VALUES (?, ?, ?, ?, 0, 0, ?, 'skipped', ?, ?)",
                    (ledger_id, earlier, ordinal, policy["stage_base_ms"][earlier], ts, ts, generation))
            balance = conn.execute(
                "SELECT COALESCE(SUM(base_ms - used_ms), 0) FROM fast_path_stages"
                " WHERE ledger_run_id = ? AND seq > 0 AND seq < ? AND status IN ('done', 'skipped')", (ledger_id, seq)).fetchone()[0]
            base = policy["stage_base_ms"].get(stage, 0)
            # A protected stage's floor is its whole base; a policy frozen without the field keeps the 25% floor.
            floor = base if stage in policy.get("protected_stages", ()) else int(base * policy["floor_ratio"])
            alloc = max(floor, base + balance) if seq else 0
            conn.execute(
                "INSERT INTO fast_path_stages (ledger_run_id, stage, seq, base_ms, balance_before_ms, alloc_ms, opened_at, status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'open')", (ledger_id, stage, seq, base, balance, alloc, ts))
        rework = int(row is not None and row["status"] in ("done", "skipped"))
        attempt = conn.execute("SELECT COUNT(*) + 1 FROM fast_path_intervals WHERE run_id = ? AND stage = ?", (run["id"], stage)).fetchone()[0]
        interval_id = new_id("fpi")
        conn.execute(
            "INSERT INTO fast_path_intervals (id, ledger_run_id, run_id, stage, attempt, generation, rework, started_at, last_checkpoint_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (interval_id, ledger_id, run["id"], stage, attempt, generation, rework, ts, ts))
        return interval_id


def checkpoint(store: Any, interval_id: str) -> None:
    ts = timestamp(store.clock)
    with transaction(store.conn):
        row = store.conn.execute("SELECT * FROM fast_path_intervals WHERE id = ? AND closed_at IS NULL", (interval_id,)).fetchone()
        if row:
            store.conn.execute(
                "UPDATE fast_path_intervals SET last_checkpoint_at = ?, max_checkpoint_gap_ms = MAX(max_checkpoint_gap_ms, ?)"
                " WHERE id = ? AND closed_at IS NULL", (ts, elapsed(row["last_checkpoint_at"], ts), interval_id))


def close_interval(store: Any, row: Any, ts: str, reason: str) -> None:
    conn = store.conn
    changed = conn.execute(
        "UPDATE fast_path_intervals SET closed_at = ?, close_reason = ?, max_checkpoint_gap_ms = MAX(max_checkpoint_gap_ms, ?)"
        " WHERE id = ? AND closed_at IS NULL",
        (ts, reason, elapsed(row["last_checkpoint_at"], ts), row["id"])).rowcount
    if not changed:
        return
    used = elapsed(row["started_at"], ts)
    conn.execute(
        "UPDATE fast_path_stages SET used_ms = used_ms + ?, rework_ms = rework_ms + ?,"
        " overrun_ms = MAX(0, used_ms + ? - alloc_ms) WHERE ledger_run_id = ? AND stage = ?",
        (used, used if row["rework"] else 0, used, row["ledger_run_id"], row["stage"]))
    if reason == "stage_done":
        conn.execute(
            "UPDATE fast_path_stages SET status = 'done', done_at = ?, done_generation = ? WHERE ledger_run_id = ? AND stage = ?",
            (ts, row["generation"], row["ledger_run_id"], row["stage"]))


def close_stage(store: Any, run_id: str, stage: str) -> None:
    with transaction(store.conn):
        rows = store.conn.execute("SELECT * FROM fast_path_intervals WHERE run_id = ? AND stage = ? AND closed_at IS NULL",
                                  (run_id, stage)).fetchall()
        ts = timestamp(store.clock)
        for row in rows:
            close_interval(store, row, ts, "stage_done")


def close_run(store: Any, run_id: str, reason: str) -> None:
    ts = timestamp(store.clock)
    for row in store.conn.execute("SELECT * FROM fast_path_intervals WHERE run_id = ? AND closed_at IS NULL", (run_id,)).fetchall():
        close_interval(store, row, ts, reason)


def recover(store: Any) -> None:
    for row in store.conn.execute("SELECT * FROM fast_path_intervals WHERE closed_at IS NULL").fetchall():
        close_interval(store, row, row["last_checkpoint_at"], "recovered")


def save_answer(store: Any, run_id: str, outcome: str) -> None:
    run = store.run(run_id)
    if not enabled(run["budget"]):
        return
    binding, ts = run["budget"]["fast_path"], timestamp(store.clock)
    if binding.get("role") == "late_revision":
        return
    if binding["role"] == "rerun":
        close_stage(store, run_id, "answer_rerun")
        return
    changed = store.conn.execute(
        "UPDATE fast_path_ledgers SET answer_outcome = ?, answer_published_at = ?"
        " WHERE ledger_run_id = ? AND answer_run_id = ? AND answer_outcome IS NULL",
        (outcome, ts if outcome == "structurally_valid" else None, binding["ledger_run_id"], run_id)).rowcount
    if changed:
        close_stage(store, run_id, "answer")


def view(store: Any, run: dict[str, Any]) -> dict[str, Any] | None:
    if not enabled(run["budget"]):
        return None
    binding = run["budget"]["fast_path"]
    ledger_id = binding.get("ledger_run_id", run["id"])
    ledger = dict(store.conn.execute("SELECT * FROM fast_path_ledgers WHERE ledger_run_id = ?", (ledger_id,)).fetchone())
    ts = timestamp(store.clock)
    intervals = [dict(row) for row in store.conn.execute("SELECT * FROM fast_path_intervals WHERE ledger_run_id = ?", (ledger_id,))]
    stages = []
    for row in store.conn.execute("SELECT * FROM fast_path_stages WHERE ledger_run_id = ? ORDER BY seq", (ledger_id,)):
        stage = dict(row)
        opened = [i for i in intervals if i["stage"] == stage["stage"] and i["closed_at"] is None]
        stage["live"] = bool(opened)
        stage["used_ms"] += sum(elapsed(i["started_at"], ts) for i in opened)
        stage["rework_ms"] += sum(elapsed(i["started_at"], ts) for i in opened if i["rework"])
        stage["overrun_ms"] = max(0, stage["used_ms"] - stage["alloc_ms"])
        stages.append(stage)
    result = {
        "policy": ledger["policy"], "policy_hash": ledger["policy_hash"], "enforcement": "none",
        "ledger_run_id": ledger_id, "role": binding.get("role"), "stages": stages,
        "balance_ms": sum(s["base_ms"] - s["used_ms"] for s in stages if s["seq"] > 0),
        "used_ms": sum(s["used_ms"] for s in stages if s["seq"] > 0),
        "latency_ms": elapsed(ledger["started_at"], ledger["answer_published_at"]) if ledger["answer_published_at"] else None,
        "answer_outcome": ledger["answer_outcome"],
        "max_checkpoint_gap_ms": max((i["max_checkpoint_gap_ms"] for i in intervals), default=0),
        "rerun_used_ms": sum(elapsed(i["started_at"], i["closed_at"] or ts) for i in intervals
                             if i["run_id"] == run["id"] and i["stage"] == "answer_rerun"),
    }
    policy = store.run(ledger_id)["budget"]["fast_path"]
    if "enforced_stages" in policy:
        result["enforced_stages"] = policy["enforced_stages"]
        result["enforcement"] = policy["enforced_stages"]
    return result
