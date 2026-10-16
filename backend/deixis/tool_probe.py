"""Version and health probes of the command-line tools DEIXIS finds on this computer (A3b, E16).

A probe runs off the event loop with stdin closed, gives up after PROBE_TIMEOUT and then kills the tool's whole process
group (an npm launcher leaves a child holding the pipes), keeps at most OUTPUT_LIMIT bytes of each stream and decodes
them with errors="replace". A hung or oddly encoded tool so reports itself without holding up the API or failing the
checks of the other tools.
"""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from deixis.models.cli_process import reap, spawn_options, stop_group

PROBE_TIMEOUT = 5.0
OUTPUT_LIMIT = 64 * 1024


@dataclass(frozen=True)
class Probe:
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None  # 'not_responding' (killed at the timeout) or 'failed' (could not be started)

    @property
    def ok(self) -> bool:
        return self.error is None and self.returncode == 0


async def _bounded(stream: asyncio.StreamReader) -> bytes:
    # Read to the end but keep only OUTPUT_LIMIT bytes: a tool never blocks on a full pipe, memory stays bounded.
    data = b""
    while chunk := await stream.read(OUTPUT_LIMIT):
        data += chunk[:OUTPUT_LIMIT - len(data)]
    return data


async def probe(argv: Sequence[str], timeout: float | None = None, env: Mapping[str, str] | None = None) -> Probe:
    try:
        proc = await asyncio.create_subprocess_exec(*argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                                    stderr=subprocess.PIPE, env=dict(env) if env is not None else None,
                                                    **spawn_options())
    except (OSError, ValueError) as exc:
        return Probe(stderr=str(exc), error="failed")
    try:
        async with asyncio.timeout(timeout or PROBE_TIMEOUT):
            out, err = await asyncio.gather(_bounded(proc.stdout), _bounded(proc.stderr))
            await proc.wait()
    except TimeoutError:
        return Probe(error="not_responding")
    finally:
        stop_group(proc)
        # What a killed tool left in its pipes is read and dropped, so the pipes close before the loop does.
        try:
            await asyncio.wait_for(asyncio.gather(_bounded(proc.stdout), _bounded(proc.stderr)), 1)
        except TimeoutError:
            pass
        await reap(proc)
    return Probe(proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"))


def probe_blocking(argv: Sequence[str], timeout: float | None = None, env: Mapping[str, str] | None = None) -> Probe:
    """`probe` for synchronous code; call it only from a worker thread, never on the event loop."""
    return asyncio.run(probe(argv, timeout, env))
