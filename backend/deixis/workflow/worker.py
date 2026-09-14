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

from deixis.storage.db import now, transaction
from deixis.workflow.flow import ResearchFlow
from deixis.workflow.store import Store

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None  # type: ignore[assignment]
    import msvcrt

log = logging.getLogger("deixis.worker")
PROCESS_STARTED_AT = datetime.now(timezone.utc).isoformat()


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
            steps = conn.execute(
                "UPDATE run_steps SET status = 'outcome_unknown', finished_at = ? WHERE status = 'running'", (now(),)
            ).rowcount
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
        while not self._stop.is_set():
            self.store.conn.execute("UPDATE worker_owner SET heartbeat_at = ? WHERE instance_id = ?", (now(), self.instance_id))
            run = self.store.next_queued_run()
            if run is None:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=1.0)
                except TimeoutError:
                    pass
                continue
            self.current_run_id = run["id"]
            self.store.update_run(run["id"], event="run_started", status="running", pause_reason=None, error_json=None)
            try:
                await self.flow.execute(run["id"])
            except Exception as exc:  # noqa: BLE001 - record any unexpected failure on the run
                log.exception("run %s failed", run["id"])
                self.store.update_run(run["id"], event="run_failed", status="failed", pause_reason="internal_error",
                                      error_json={"error": f"{type(exc).__name__}: {str(exc)[:300]}"})
            finally:
                self.current_run_id = None

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
