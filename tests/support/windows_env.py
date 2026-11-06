"""What any child Python needs on Windows, whatever the test's allowlist: without SYSTEMROOT Winsock cannot start, and
`import asyncio` fails with WinError 10106. Empty on macOS and Linux."""

import os
import sys


def system_env() -> dict[str, str]:
    return {name: os.environ[name] for name in ("SYSTEMROOT",) if name in os.environ}


# A whole discovery run through the API takes 10 to 20 times longer on a 4-vCPU Windows runner with four workers than
# on the Mac (measured in the W1 CI runs: 30 to 85 s against 2 to 4 s); alone, in the Windows VM, about twice as long.
# The run-settling waits stretch by this factor there; on macOS and Linux they are unchanged.
WAIT_FACTOR = 4 if sys.platform == "win32" else 1
