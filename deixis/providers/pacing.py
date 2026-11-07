"""Process-wide pacing for provider APIs with a cumulative request limit."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Awaitable, Callable, TypeVar


T = TypeVar("T")


class CoolingDown(Exception):
    """A request that asked not to wait out a cooldown was not sent; `seconds` is what was left of it."""

    def __init__(self, seconds: float):
        super().__init__(f"cooling down for {seconds:.1f} s")
        self.seconds = seconds


class SerialRequestPacer:
    """Serialize attempts and leave a minimum gap after each completed attempt.

    A thread lock keeps the gate shared across event loops in this process. Holding it
    through the HTTP call is conservative: another endpoint cannot start while the
    previous attempt is still in flight. Cancellation releases the gate.

    A cooldown (`cool_down`) holds every attempt back until it ends. Its deadline has a lock of its own, so
    concurrent updates keep the later one. A caller that passes `skip_in_cooldown` is never held by it: whether it
    is still queued for the gate or already holding it, it gets `CoolingDown` at once and sends nothing.
    """

    def __init__(self, interval_seconds: float):
        self.interval_seconds = interval_seconds
        self._lock = threading.Lock()
        self._last_finished = 0.0
        self._cooldown_lock = threading.Lock()
        self._cooldown_until = 0.0

    def cool_down(self, seconds: float) -> None:
        """Send nothing for `seconds` from now. A later, shorter cooldown never shortens one already set."""
        with self._cooldown_lock:
            self._cooldown_until = max(self._cooldown_until, time.monotonic() + max(0.0, seconds))

    def cooling(self) -> float:
        """Seconds left of the current cooldown; 0 when there is none."""
        with self._cooldown_lock:
            return max(0.0, self._cooldown_until - time.monotonic())

    async def run(self, factory: Callable[[], Awaitable[T]], *, skip_in_cooldown: bool = False) -> T:
        while not self._lock.acquire(blocking=False):
            if skip_in_cooldown and (left := self.cooling()) > 0:
                raise CoolingDown(left)
            await asyncio.sleep(0.05)
        sent = False
        try:
            while True:
                cooling = self.cooling()
                if skip_in_cooldown and cooling > 0:
                    raise CoolingDown(cooling)
                left = max(self.interval_seconds - (time.monotonic() - self._last_finished), cooling)
                if left <= 0:
                    break
                # Woken at least every second, so a cooldown set meanwhile reaches a caller that skips it.
                await asyncio.sleep(min(left, 1.0) if skip_in_cooldown else left)
            sent = True
            return await factory()
        finally:
            if sent:
                self._last_finished = time.monotonic()
            self._lock.release()


# Measured live on 2026-09-18 with a key, six searches per interval: 1.05 s got 1/6 through, 2 s got 4/6. The stated
# limit is one request per second, but requests landing on the boundary are throttled, so leave a full second of slack.
# 3 s, after 3 of 6 requests at 2 s spacing met a CloudFront 429 on 6 Nov 2026 (one probe, not a measured rate).
SEMANTIC_SCHOLAR_PACER = SerialRequestPacer(3.0)
# How long every Semantic Scholar caller holds off after a 429 that names no wait (a Retry-After is used instead,
# up to S2_MAX_COOLDOWN_SECONDS, so one long header cannot hold a search for an hour). Hand-picked, not measured.
S2_COOLDOWN_SECONDS = 15.0
S2_MAX_COOLDOWN_SECONDS = 60.0


class StartPacer:
    """Space send starts across event loops without serializing HTTP replies."""

    def __init__(self, interval_seconds):
        self.interval_seconds = interval_seconds
        self._lock = threading.Lock()
        self._next = 0.0

    async def start(self):
        """Wait until this start is one interval after the last start, checked when the caller wakes: callers that
        overslept together (a stalled loop, a suspended machine) still start one interval apart."""
        while True:
            with self._lock:
                now = time.monotonic()
                if now >= self._next:
                    self._next = now + self.interval_seconds
                    return
                delay = self._next - now
            await asyncio.sleep(delay)

    async def wait(self):
        with self._lock:
            start = max(time.monotonic(), self._next)
            self._next = start + self.interval_seconds
        await asyncio.sleep(max(0, start - time.monotonic()))


# Only the marked fast-chain execution opts in, including its keyword pages
# and every common.send retry. The documented ceiling is 100 requests/s.
FAST_OPENALEX_PACER = StartPacer(0.1)
