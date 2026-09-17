"""Process-wide bound on concurrent model calls, shared by table fill and, later, the report run.

A model call is send-then-wait: nothing about it needs the database connection while it is in flight (flow.py never
awaits inside a transaction), so several calls may be in flight at once as long as their number stays under a limit
that can drop at runtime, on a rate-limit response, without dropping calls already in flight.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


class ModelCallLimiter:
    """Bound concurrent model calls and keep one operation key from running twice concurrently.

    The bound is process-wide and mutable: reduce() lowers it (floor 1) when a call comes back rate-limited; calls
    already granted a slot keep running, and the next call to wait for a slot sees the lower ceiling. run() is the
    only way to send a call through the limiter; a second call for a key already in flight waits for and returns
    the first call's outcome instead of sending its own.
    """

    def __init__(self, limit: int):
        self._limit = max(1, limit)
        self._in_flight = 0
        self._condition = asyncio.Condition()
        self._by_key: dict[str, asyncio.Task[Any]] = {}

    @property
    def limit(self) -> int:
        return self._limit

    async def reduce(self) -> int:
        async with self._condition:
            self._limit = max(1, self._limit // 2)
            self._condition.notify_all()
            return self._limit

    async def run(self, key: str, factory: Callable[[], Awaitable[T]]) -> T:
        existing = self._by_key.get(key)
        if existing is not None:
            return await existing
        task: asyncio.Task[T] = asyncio.ensure_future(self._run_one(factory))
        self._by_key[key] = task
        try:
            return await task
        finally:
            del self._by_key[key]

    async def _run_one(self, factory: Callable[[], Awaitable[T]]) -> T:
        async with self._condition:
            await self._condition.wait_for(lambda: self._in_flight < self._limit)
            self._in_flight += 1
        try:
            return await factory()
        finally:
            async with self._condition:
                self._in_flight -= 1
                self._condition.notify_all()
