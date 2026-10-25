"""Single-owner local worker.

Ownership is an OS advisory lock held for the process lifetime; a PID or stale
heartbeat alone never releases it. After acquiring the lock, half-finished work of
the previous instance is marked `outcome_unknown` / `paused` so the user decides
whether to resume (a model call may then be repeated).
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from deixis.storage.db import describe_failure, now, transaction
from deixis.workflow.run.flow import ResearchFlow
from deixis.workflow.run.store import Store

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None  # type: ignore[assignment]
    import msvcrt

log = logging.getLogger("deixis.worker")
PROCESS_STARTED_AT = datetime.now(timezone.utc).isoformat()
RETRY_SECONDS = 1.0  # wait after a failed turn (a database, disk or code error) before the next one


def failure_identity(exc: BaseException) -> tuple[str, str]:
    """What makes two failures the same for logging: their type and message."""
    return type(exc).__name__, str(exc)


class Worker:
    def __init__(self, store: Store, flow: ResearchFlow, lock_path: Path):
        self.store = store
        self.flow = flow
        self.lock_path = lock_path
        self.instance_id = str(uuid.uuid4())
        self.current_run_id: str | None = None
        self._fd: int | None = None
        self._wake = asyncio.Event()
        self._stop = asyncio.Event()
        self._failed: tuple[str, str, dict] | None = None  # (run id, pause reason, error) not yet written
        self._reconcile_errors: set[type[Exception]] = set()
        self._sweep_errors: dict[str, tuple[str, str]] = {}  # sweep -> the failure last logged for it
        self._background_task: asyncio.Task | None = None

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if fcntl:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            os.close(fd)
            return False
        self._fd = fd
        with transaction(self.store.conn):
            self.store.conn.execute(
                "INSERT INTO worker_owner (singleton, instance_id, pid, process_started_at, heartbeat_at) VALUES (1, ?, ?, ?, ?)"
                " ON CONFLICT(singleton) DO UPDATE SET instance_id = excluded.instance_id, pid = excluded.pid,"
                " process_started_at = excluded.process_started_at, heartbeat_at = excluded.heartbeat_at",
                (self.instance_id, os.getpid(), PROCESS_STARTED_AT, now()),
            )
        return True

    def recover(self) -> dict[str, int]:
        conn = self.store.conn
        with transaction(conn):
            from deixis.workflow.run import fast_path

            fast_path.recover(self.store)
            # A provider request still out when the process stopped stays "not known whether sent" (D31); its row
            # says why.
            conn.execute("UPDATE provider_requests SET delivery_class = 'backend_stopped', settled_at = ?"
                         " WHERE settled_at IS NULL", (now(),))
            from deixis.workflow.read import background_fetch
            background_fetch.recover(self.store)
            steps = conn.execute(
                "UPDATE run_steps SET status = 'outcome_unknown', finished_at = ? WHERE status = 'running'", (now(),)
            ).rowcount
            # A call out when the process stopped may have been billed: it counts as spent, estimated from what was sent (F4).
            from deixis.workflow.run import spend
            for row in conn.execute("SELECT id FROM model_sessions WHERE status = 'started'").fetchall():
                spend.record_session(conn, row["id"], None)
            sessions = conn.execute(
                "UPDATE model_sessions SET status = 'outcome_unknown', finished_at = ? WHERE status = 'started'", (now(),)
            ).rowcount
            runs = conn.execute("SELECT id, research_id FROM runs WHERE status IN ('running', 'pause_requested')").fetchall()
            for run in runs:
                conn.execute(
                    "UPDATE runs SET status = 'paused', pause_reason = 'backend_restarted', version = version + 1, updated_at = ? WHERE id = ?",
                    (now(), run["id"]),
                )
                self.store._event(run["research_id"], "run_paused", {"status": "paused", "pause_reason": "backend_restarted"}, run["id"])
        return {"runs": len(runs), "steps": steps, "model_sessions": sessions}

    def wake(self) -> None:
        self._wake.set()

    async def run_forever(self) -> None:
        lane = getattr(self.flow, "background_fetch", None)
        if lane is not None:
            self._background_task = asyncio.create_task(lane.run_forever())
        try:
            await self._run_forever()
        finally:
            if lane is not None:
                lane.stop()
                await self._background_task

    async def _run_forever(self) -> None:
        try:
            # A person's files that were waiting when the last instance stopped (slice 18b, decision 5).
            self.flow.queue_person_readings()
        except Exception:  # noqa: BLE001 - the worker must still start
            log.exception("queueing waiting person readings at start failed")
        last_error: tuple[str, str] | None = None
        while not self._stop.is_set():
            try:
                await self._turn()
                last_error = None
            except Exception as exc:  # noqa: BLE001 - logged once per failure, then the next turn
                # A full disk, a locked library or a code error must not end the worker: no run would start again until
                # a restart (P9 H3). The same failure every turn is logged once; a different one is logged again.
                if failure_identity(exc) != last_error:
                    log.exception("worker turn failed; trying again")
                last_error = failure_identity(exc)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=RETRY_SECONDS)
                except TimeoutError:
                    pass

    async def _turn(self) -> None:
        if self._failed is not None:
            self._write_failure()
        self.store.conn.execute("UPDATE worker_owner SET heartbeat_at = ? WHERE instance_id = ?", (now(), self.instance_id))
        await self.reconcile_recovery()
        from deixis.workflow.answer import late_revision
        from deixis.workflow.features.tables import table_refresh, table_rows
        self._sweep("late_revision", lambda: late_revision.advance(self.flow))
        # after the late answer revision, so that one is queued first (D52)
        self._sweep("table_refresh", lambda: table_refresh.advance(self.store))
        self._sweep("table_rows", lambda: table_rows.advance(self.store))
        run = self.store.next_queued_run()
        if run is None:
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=1.0)
            except TimeoutError:
                pass
            return
        self.store.update_run(run["id"], event="run_started", status="running", pause_reason=None, error_json=None)
        self.current_run_id = run["id"]
        try:
            await self.flow.execute(run["id"])
        except Exception as exc:  # noqa: BLE001 - record any unexpected failure on the run
            log.exception("run %s failed", run["id"])
            failure = describe_failure(exc)
            self._failed = (run["id"], "disk_full" if failure and failure[0] == "disk_full" else "internal_error",
                            {"error": f"{type(exc).__name__}: {str(exc)[:300]}"})
        finally:
            self.current_run_id = None
        if self._failed is not None:
            self._write_failure()
        else:
            self._run_ended(run["id"])

    def _sweep(self, name: str, advance: Callable[[], object]) -> None:
        """Run one sweep that queues work; its failure is logged (once while it stays the same) and the turn goes on, so
        a sweep that fails every turn does not keep the queued runs from starting."""
        try:
            advance()
        except Exception as exc:  # noqa: BLE001 - one sweep must not hold up the queue
            if self._sweep_errors.get(name) != failure_identity(exc):
                log.exception("worker sweep %s failed; the turn goes on", name)
            self._sweep_errors[name] = failure_identity(exc)
        else:
            self._sweep_errors.pop(name, None)

    async def reconcile_recovery(self) -> dict[str, int] | None:
        if self.store.recovery_dir is None:
            return None
        from deixis.workflow.read import reconcile

        try:
            result = await reconcile.reconcile_stale(self.store, self.flow.deps.settings.papers_dir, self.store.recovery_dir)
        except Exception as exc:
            if type(exc) not in self._reconcile_errors:
                self._reconcile_errors.add(type(exc))
                log.exception("Recovery reconciliation failed; continuing the worker turn")
            return None
        self._reconcile_errors.clear()
        return result

    def _write_failure(self) -> None:
        """Record the failure of a run. When the write itself fails (the disk is still full) the failure stays in
        memory and the next turn writes it again, so the run does not stay `running` once there is room."""
        run_id, reason, error = self._failed
        if self.store.run(run_id)["status"] not in ("running", "pause_requested"):
            self._failed = None  # a cancel or pause that arrived meanwhile stands
            self._run_ended(run_id)
            return
        # A person's files the run held are closed by this same write (`Store.update_run`, slice 18b).
        self.store.update_run(run_id, event="run_failed", status="failed", pause_reason=reason, error_json=error)
        self._failed = None
        self._run_ended(run_id)

    def _run_ended(self, run_id: str) -> None:
        lane = getattr(self.flow, "background_fetch", None)
        if lane is not None:
            lane.wake()
        # Whichever way the run returned, a person's waiting files get their reading run now (slice 18b).
        try:
            self.flow.person_run_ended(run_id)
            from deixis.workflow.answer import late_revision
            from deixis.workflow.features.tables import table_refresh, table_rows
            rid = self.store.run(run_id)["research_id"]
            late_revision.advance(self.flow, rid)
            table_refresh.advance(self.store, rid)
            table_rows.advance(self.store, rid)
        except Exception:  # noqa: BLE001 - the next run must not be held up by it
            log.exception("queueing a person's reading after run %s failed", run_id)

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
