"""Frozen policy, durable active wall time and stage-specific soft deadlines."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from deixis.domain import canonical
from deixis.storage.db import new_id, transaction

POLICY = "fast_path_v1"
RUNNER_VERSION = 2
STAGES = ("plan", "search", "ranking", "read", "answer")
MODES = {
    "quick": ((30, 30, 30, 60, 30), 25, 10, 450, 10, 2, 2),
    "standard": ((30, 45, 60, 120, 45), 50, 20, 1000, 20, 4, 8),
    "detailed": ((45, 90, 120, 270, 75), 100, 40, 2000, 30, 8, 16),
}


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


def freeze_budget(budget: dict[str, Any], effort: str) -> dict[str, Any]:
    bases, n, k, cap, seeds, backward, forward = MODES[effort]
    policy = {
        "policy": POLICY, "runner_version": RUNNER_VERSION, "enforcement": ["search", "ranking", "read", "answer"],
        "enforced_stages": ["search", "ranking", "read", "answer"], "background_fetch_slots": 4,
        "approval_mode": "unattended", "auto_answer": True,
        "late_revision": {"mode": "auto", "max_revisions": 1},
        "mode": "deep" if effort == "detailed" else effort,
        "stage_base_ms": dict(zip(STAGES, (s * 1000 for s in bases))), "total_ms": sum(bases) * 1000,
        "N": n, "K": k, "keyword_record_cap": cap, "semantic_top": 50,
        "chain_seeds": seeds, "backward_requests": backward, "backward_page_size": 50,
        "forward_requests": forward, "forward_page_size": 25,
        "chain_in_flight": 5, "chain_rule": "fast_chain_v1",
        "embedding_threads": 4, "fetch_slots": 12, "slot_refill": True, "arrival_margin_ms": 5000,
        "checkpoint_ms": 5000, "floor_ratio": 0.25,
    }
    return policy | {"policy_hash": canonical.sha256_hex(policy)}


def enabled(budget: dict[str, Any]) -> bool:
    return (budget.get("fast_path") or {}).get("policy") == POLICY


def chain_on(budget: dict[str, Any]) -> bool:
    return enabled(budget) and budget["fast_path"].get("chain_rule") == "fast_chain_v1"


def enforces(budget: dict[str, Any], stage: str) -> bool:
    stages = (budget.get("fast_path") or {}).get("enforced_stages")
    return enabled(budget) and isinstance(stages, list) and stage in stages


def stage_deadline(store: Any, run: dict[str, Any], stage: str) -> datetime | None:
    if not enforces(run["budget"], stage):
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
        assert ledger is not None and (ledger["research_id"], ledger["scope_revision"], ledger["policy_hash"]) == (
            run["research_id"], run["scope_revision"], policy["policy_hash"])
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
            assert not conn.execute(
                "SELECT 1 FROM fast_path_intervals i JOIN fast_path_stages s"
                " ON s.ledger_run_id = i.ledger_run_id AND s.stage = i.stage"
                " WHERE i.ledger_run_id = ? AND i.closed_at IS NULL AND s.seq > 0 AND s.seq < ?",
                (ledger_id, seq)).fetchone(), "previous stage still has an open interval"
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
            alloc = max(int(base * policy["floor_ratio"]), base + balance) if seq else 0
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
    # A library opened below migration 0073 (the old-schema migration tests) has no interval to close.
    if not store.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'fast_path_intervals'").fetchone():
        return
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
