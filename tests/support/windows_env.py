"""What any child Python needs on Windows, whatever the test's allowlist: without SYSTEMROOT Winsock cannot start, and
`import asyncio` fails with WinError 10106. Empty on macOS and Linux."""

import os


def system_env() -> dict[str, str]:
    return {name: os.environ[name] for name in ("SYSTEMROOT",) if name in os.environ}
