"""Process-wide pacing for provider APIs with a cumulative request limit."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Awaitable, Callable, TypeVar


T = TypeVar("T")


class SerialRequestPacer:
    """Serialize attempts and leave a minimum gap after each completed attempt.

    A thread lock keeps the gate shared across event loops in this process. Holding it
    through the HTTP call is conservative: another endpoint cannot start while the
    previous attempt is still in flight. Cancellation releases the gate.
    """

    def __init__(self, interval_seconds: float):
        self.interval_seconds = interval_seconds
        self._lock = threading.Lock()
        self._last_finished = 0.0

    async def run(self, factory: Callable[[], Awaitable[T]]) -> T:
        while not self._lock.acquire(blocking=False):
            await asyncio.sleep(0.05)
        try:
            remaining = self.interval_seconds - (time.monotonic() - self._last_finished)
            while remaining > 0:
                await asyncio.sleep(remaining)
                remaining = self.interval_seconds - (time.monotonic() - self._last_finished)
            return await factory()
        finally:
            self._last_finished = time.monotonic()
            self._lock.release()


# Measured live on 2026-09-18 with a key, six searches per interval: 1.05 s got 1/6 through, 2 s got 4/6. The stated
# limit is one request per second, but requests landing on the boundary are throttled, so leave a full second of slack.
SEMANTIC_SCHOLAR_PACER = SerialRequestPacer(2.0)


class StartPacer:
    """Space send starts across event loops without serializing HTTP replies."""

    def __init__(self, interval_seconds):
        self.interval_seconds = interval_seconds
        self._lock = threading.Lock()
        self._next = 0.0

    async def wait(self):
        with self._lock:
            start = max(time.monotonic(), self._next)
            self._next = start + self.interval_seconds
        await asyncio.sleep(max(0, start - time.monotonic()))


# Only the marked fast-chain execution opts in, including its keyword pages
# and every common.send retry. The documented ceiling is 100 requests/s.
FAST_OPENALEX_PACER = StartPacer(0.1)
