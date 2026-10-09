"""D251: durable retrieval outside the single research-run worker lane."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from deixis.storage.db import new_id, transaction
from deixis.workflow import fast_path
from deixis.workflow.store import ACTIVE_RUN_STATUSES

log = logging.getLogger("deixis.background_fetch")


class FetchSlots:
    """Process-wide work slots; queued foreground work takes priority."""

    def __init__(self, limit: int = 12):
        self.limit = limit
        self.active = 0
        self.waiting = 0
        self.changed = asyncio.Condition()

    @asynccontextmanager
    async def slot(self, *, background: bool = False):
        async with self.changed:
            if not background:
                self.waiting += 1
            try:
                await self.changed.wait_for(lambda: self.active < self.limit and (not background or not self.waiting))
                self.active += 1
            finally:
                if not background:
                    self.waiting -= 1
                    self.changed.notify_all()
        try:
            yield
        finally:
            async with self.changed:
                self.active -= 1
                self.changed.notify_all()


def other_run_active(store: Any, rid: str, owner_id: str) -> bool:
    return bool(store.conn.execute(
        "SELECT 1 FROM runs WHERE research_id = ? AND id != ?"
        f" AND status IN ({','.join('?' * len(ACTIVE_RUN_STATUSES))})",
        (rid, owner_id, *ACTIVE_RUN_STATUSES)).fetchone())


async def before_publish(flow: Any, run: dict[str, Any], work_id: str | None = None) -> None:
    """Hold corpus publication while another run uses the research's sources.

    In-flight handoffs may still be downloading when another run queues. Check again
    immediately before corpus publication, including after extraction awaits.
    """
    if not fast_path.enforces(run["budget"], "read"):
        return
    store = flow.store
    handed_off = store.conn.execute(
        "SELECT 1 FROM fast_path_background_fetches WHERE run_id = ?", (run["id"],)).fetchone()
    if handed_off:
        while other_run_active(store, run["research_id"], run["id"]):
            flow._stop_work_if_requested(run)
            await asyncio.sleep(0.05)
    flow._stop_work_if_requested(run)
    if work_id is not None and work_id not in store.work_heads(run["research_id"]):
        from deixis.workflow.flow import RunStopped
        raise RunStopped


def enqueue(store: Any, run: dict[str, Any], item: dict[str, Any], origin: str) -> None:
    # Caller owns the cutoff transaction; never publish a queue without its closure.
    store.conn.execute(
        "INSERT OR IGNORE INTO fast_path_background_fetches"
        " (id, ledger_run_id, run_id, research_id, scope_revision, work_id, head, position, origin, status, queued_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)",
        (new_id("bfetch"), run["id"], run["id"], run["research_id"], run["scope_revision"],
         item["work_id"], item["head"], item["position"], origin, fast_path.timestamp(store.clock)))


def recover(store: Any) -> None:
    if store.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'fast_path_background_fetches'").fetchone():
        store.conn.execute("UPDATE fast_path_background_fetches SET status = 'queued' WHERE status = 'running'")


class BackgroundFetchLane:
    def __init__(self, flow: Any):
        self.flow = flow
        self.store = flow.store
        self.tasks: dict[tuple[str, str], asyncio.Task] = {}
        self.woken = asyncio.Event()
        self.stopping = False

    def wake(self) -> None:
        self.woken.set()

    def adopt(self, run: dict[str, Any], wid: str, task: asyncio.Task) -> None:
        key = (run["id"], wid)
        self.tasks[key] = asyncio.create_task(self._settle(run, wid, task))
        self.wake()

    def _mark_running(self, run: dict[str, Any], wid: str) -> None:
        with transaction(self.store.conn):
            self.store.conn.execute(
                "UPDATE fast_path_background_fetches SET status = 'running', attempts = attempts + 1, started_at = ?"
                " WHERE run_id = ? AND work_id = ? AND status = 'queued'",
                (fast_path.timestamp(self.store.clock), run["id"], wid))

    async def _settle(self, run: dict[str, Any], wid: str, task: asyncio.Task) -> None:
        from deixis.workflow.flow import RunStopped

        self._mark_running(run, wid)
        try:
            await task
        except asyncio.CancelledError:
            # Worker shutdown retains the running row for recovery, never calls it a failure.
            raise
        except RunStopped:
            pass
        except Exception:
            log.exception("background fetch failed: %s", wid)
        step = self.store.existing_step(run["id"], f"fulltext_work:{wid}")
        status = step["status"] if step else "failed"
        code = step.get("error_code") if step else "fetch_not_settled"
        owner_status = self.store.run(run["id"])["status"]
        if owner_status in ("cancelled", "failed"):
            status, code = owner_status, f"run_{owner_status}"
        elif self.store.research(run["research_id"])["current_scope_revision"] != run["scope_revision"]:
            status, code = "cancelled", "scope_revised"
        elif wid not in self.store.work_heads(run["research_id"]):
            status, code = "cancelled", "source_changed"
        elif status not in ("succeeded", "failed", "cancelled"):
            status, code = "failed", "fetch_not_settled"
        with transaction(self.store.conn):
            self.store.conn.execute(
                "UPDATE fast_path_background_fetches SET status = ?, outcome_code = ?, finished_at = ?"
                " WHERE run_id = ? AND work_id = ?",
                (status, code, fast_path.timestamp(self.store.clock), run["id"], wid))
        from deixis.workflow import late_revision
        late_revision.advance(self.flow, run["research_id"])

    async def _fetch(self, run: dict[str, Any], wid: str) -> None:
        async with self.flow.deps.fetch_slots.slot(background=True):
            await before_publish(self.flow, run)
            self.flow._claim(run["id"], wid, False, "fast_path")
            await self.flow._overlap_work(run, wid)

    def pick(self) -> None:
        from deixis.workflow import late_revision
        late_revision.advance(self.flow)
        for key, task in list(self.tasks.items()):
            if task.done():
                del self.tasks[key]
                task.result()
        rows = self.store.conn.execute(
            "SELECT q.* FROM fast_path_background_fetches q WHERE q.status = 'queued'"
            " ORDER BY q.queued_at, q.position, q.id").fetchall()
        for row in rows:
            key = (row["run_id"], row["work_id"])
            if key in self.tasks:
                continue
            run = self.store.run(row["run_id"])
            missing = self.store.work_heads(row["research_id"]).get(row["work_id"]) is None
            revised = self.store.research(row["research_id"])["current_scope_revision"] != row["scope_revision"]
            if run["status"] in ("cancelled", "failed"):
                with transaction(self.store.conn):
                    self.store.conn.execute(
                        "UPDATE fast_path_background_fetches SET status = ?, outcome_code = ?, finished_at = ? WHERE id = ?",
                        (run["status"], f"run_{run['status']}", fast_path.timestamp(self.store.clock), row["id"]))
                continue
            if revised or missing:
                with transaction(self.store.conn):
                    self.store.conn.execute(
                        "UPDATE fast_path_background_fetches SET status = 'cancelled', outcome_code = ?, finished_at = ? WHERE id = ?",
                        ("scope_revised" if revised else "source_changed", fast_path.timestamp(self.store.clock), row["id"]))
                continue
            if run["status"] != "completed" or other_run_active(self.store, row["research_id"], run["id"]):
                continue
            if len(self.tasks) >= run["budget"]["fast_path"].get("background_fetch_slots", 4):
                break
            task = asyncio.create_task(self._fetch(run, row["work_id"]))
            self.adopt(run, row["work_id"], task)

    async def run_forever(self) -> None:
        try:
            while not self.stopping:
                try:
                    self.pick()
                except Exception:
                    log.exception("background queue turn failed; retrying")
                self.woken.clear()
                try:
                    await asyncio.wait_for(self.woken.wait(), timeout=0.1)
                except TimeoutError:
                    pass
        finally:
            tasks = list(self.tasks.values())
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.tasks.clear()

    def stop(self) -> None:
        self.stopping = True
        self.wake()
