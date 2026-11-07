"""Stand-ins for the Gemini CLI and the GitHub Copilot CLI for the desktop acceptance (P10 M2). Not the real programs,
not a test module. Run by a launcher in the acceptance's bin folder as `fake_cli.py gemini|copilot ARGS...`; the
launcher sets `_FAKE_CLI_DIR`, where the marker files go.

Both answer the health checks DEIXIS makes (`--version`; Gemini's empty-prompt sign-in probe; Copilot's ACP
`initialize` + `session/new` with one model) and hang on a model step: a long model call. Gemini's step first starts a
short-lived intermediate process that starts a grandchild in a new process group of the CLI's session and exits at
once, so the grandchild's parent is gone well within the watchdog's 0.5 s scan (`gemini-grandchild.json`). Every
record is SYNTHETIC.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

NO_INPUT_TEXT = "No input provided via stdin"  # gemini_cli.NO_INPUT_TEXT: the sign-in probe passed
COPILOT_MODEL = "fake-copilot"


def marker(name: str, **facts) -> None:
    folder = Path(os.environ.get("_FAKE_CLI_DIR") or Path(sys.argv[0]).resolve().parent)
    (folder / name).write_text(json.dumps({"pid": os.getpid(), "pgid": os.getpgrp(), "sid": os.getsid(0), **facts}))


def hang() -> None:
    time.sleep(3600)


def gemini(args: list[str]) -> int:
    if "--version" in args:
        print("0.60.0")
        return 0
    sys.stdin.read()
    if "-m" not in args:  # the sign-in probe: an empty prompt
        print(NO_INPUT_TEXT, file=sys.stderr)
        return 1
    intermediate = subprocess.Popen([sys.executable, __file__, "intermediate"])
    intermediate.wait()
    marker("gemini-hang.json", intermediate=intermediate.pid)
    hang()
    return 0


def intermediate() -> int:
    grandchild = subprocess.Popen([sys.executable, __file__, "grandchild"], process_group=0,
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    marker("gemini-grandchild.json", grandchild=grandchild.pid, intermediate_lived_s=round(time.process_time(), 3))
    return 0  # exits at once; the grandchild is orphaned


def copilot(args: list[str]) -> int:
    if "--version" in args:
        print("1.0.0-SYNTHETIC")
        return 0
    if "--acp" in args:
        for line in sys.stdin:
            message = json.loads(line)
            result = {} if message.get("method") == "initialize" else {
                "sessionId": "SYNTHETIC", "models": {"availableModels": [{"modelId": COPILOT_MODEL, "name": "SYNTHETIC Copilot"}]}}
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": message.get("id"), "result": result}) + "\n")
            sys.stdout.flush()
        return 0
    sys.stdin.read()
    marker("copilot-hang.json")
    hang()
    return 0


def main() -> int:
    mode, args = sys.argv[1], sys.argv[2:]
    if mode == "grandchild":
        hang()
        return 0
    return {"gemini": gemini, "copilot": copilot, "intermediate": lambda _args: intermediate()}[mode](args)


if __name__ == "__main__":
    raise SystemExit(main())
