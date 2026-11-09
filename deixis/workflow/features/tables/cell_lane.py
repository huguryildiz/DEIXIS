"""Who owns a cell call once the run that sent it has moved on.

A cell call sent while a paper is being read must outlive the reading: the design wants the first answer written
without waiting for table work, and the frozen plan wants the call finished rather than cancelled. So the call is
owned from the moment it is sent by this lane instead of by the read stage, which therefore neither waits for it at
its cutoff nor cancels it on its error path.

The lane holds nothing but the tasks. There is no queue row and nothing is retried: the call's own step is its
record, and a task the lane cancels at shutdown leaves its step `running`, which the next start marks
`outcome_unknown` for the person to see. A call that raises has already closed its own step, so the lane only logs
it; one failing call never touches another.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Awaitable

log = logging.getLogger("deixis.cell_lane")
# Cell calls out at once. Their own bound, not the run's model-call limiter: that limiter is shared with the
# readings and its ceiling falls to one after a rate-limited answer, so a cell call waiting in it could hold up the
# reading it was meant to follow.
SLOTS = 2


class CellLane:
    """Owner of the cell calls sent during a reading."""

    def __init__(self) -> None:
        self.tasks: dict[tuple[str, str], asyncio.Task] = {}
        self._slots: asyncio.Semaphore | None = None

    @asynccontextmanager
    async def slot(self):
        """One of the lane's own places to send from; made on first use, inside the loop the calls run on."""
        if self._slots is None:
            self._slots = asyncio.Semaphore(SLOTS)
        async with self._slots:
            yield

    def out(self, run_id: str, svid: str) -> bool:
        """Whether this run already has a call out for this source, which a resumed reading must not send again."""
        task = self.tasks.get((run_id, svid))
        return task is not None and not task.done()

    def send(self, run_id: str, svid: str, work: Any) -> asyncio.Task:
        """Own one source's cell calls from the start, keyed by the run that sent them and the source.

        A call already out for that pair keeps the lane's place: a resumed reading, whose own record of what it
        sent is empty, cannot replace a task the shutdown would then be unable to wait for. The coroutine it
        offered is closed unstarted and the call already out is returned.
        """
        key = (run_id, svid)
        existing = self.tasks.get(key)
        if existing is not None and not existing.done():
            work.close()
            return existing
        task = asyncio.create_task(self._observe(key, work))
        self.tasks[key] = task
        return task

    async def _observe(self, key: tuple[str, str], work: Awaitable[Any]) -> None:
        try:
            await work
        except asyncio.CancelledError:
            raise  # shutdown: the step stays open and the next start marks it outcome_unknown
        except Exception:  # noqa: BLE001 - the call closed its own step; one call must not end the lane
            log.exception("a cell call of run %s for source %s failed", *key)
        finally:
            # Only this task's own place is given up: a call sent for the same source since keeps the lane's.
            if self.tasks.get(key) is asyncio.current_task():
                del self.tasks[key]

    def working(self, run_id: str | None = None) -> int:
        """How many cell calls are still out, of one run or of all of them."""
        return sum(1 for (owner, _svid), task in self.tasks.items()
                   if not task.done() and (run_id is None or owner == run_id))

    async def close(self) -> None:
        """End every call the lane owns, waiting for each to unwind before the library is closed."""
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
