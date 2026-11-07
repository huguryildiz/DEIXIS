"""A stand-in for the `codex` CLI for the packaged-sidecar smoke run (P10 M1). Not the real program, not a test module.

`--version` prints a version; `app-server` speaks the JSON-RPC lines `models/codex_rpc.py` sends and answers every
turn with `tests/support/fakes.valid_response` for the StepInput in the turn's text (SYNTHETIC output that passes the
step's checks). On start it writes the names of the environment variables it was given to `env-seen.json` next to its
launcher, so the smoke run can show which variables reach a model CLI. With `_FAKE_CODEX_HANG` set (by the desktop
acceptance's launcher) a turn never completes: a long model call.
"""

from __future__ import annotations

import json
import os
import sys
import time
from itertools import count
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests" / "support"))
from fakes import parse_step_input, valid_response  # noqa: E402

VERSION = "0.200.0"
MODEL = "gpt-fake"
ids = count(1)


def send(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def answer(method: str, params: dict) -> dict:
    if method == "initialize":
        return {"userAgent": f"codex_fake/{VERSION} (SYNTHETIC)"}
    if method == "account/read":
        return {"account": {"type": "chatgpt", "planType": "plus"}}
    if method == "model/list":
        return {"data": [{"id": MODEL, "displayName": "SYNTHETIC fake model", "isDefault": True, "description": "",
                          "defaultReasoningEffort": "medium",
                          "supportedReasoningEfforts": [{"reasoningEffort": "medium", "description": ""}]}]}
    if method == "mcpServerStatus/list":
        return {"data": []}
    if method == "thread/start":
        return {"thread": {"id": f"thr_{next(ids)}"}, "model": params.get("model") or MODEL, "instructionSources": []}
    if method in ("thread/unsubscribe", "turn/interrupt"):
        return {}
    raise KeyError(method)


def main() -> int:
    if "--version" in sys.argv[1:]:
        print(f"codex-cli {VERSION}")
        return 0
    if sys.argv[1:2] != ["app-server"]:
        print("fake codex: only --version and app-server", file=sys.stderr)
        return 2
    launcher = Path(os.environ.get("_FAKE_CODEX_DIR") or Path(sys.argv[0]).resolve().parent)
    (launcher / "env-seen.json").write_text(json.dumps(sorted(os.environ)), encoding="utf-8")
    for line in sys.stdin:
        message = json.loads(line)
        if "id" not in message:
            continue  # a notification (`initialized`)
        method, params = message.get("method"), message.get("params") or {}
        if method == "turn/start":
            turn = f"turn_{next(ids)}"
            send({"id": message["id"], "result": {"turn": {"id": turn}}})
            if os.environ.get("_FAKE_CODEX_HANG"):  # desktop acceptance: a model call that does not end
                (launcher / "codex-hang.json").write_text(json.dumps({"pid": os.getpid(), "pgid": os.getpgrp()}))
                time.sleep(3600)
            text = next(i["text"] for i in params["input"] if i.get("type") == "text")
            output = valid_response(parse_step_input(text))
            thread = params["threadId"]
            send({"method": "item/completed", "params": {"threadId": thread, "item": {
                "type": "agentMessage", "phase": "final_answer", "text": output}}})
            send({"method": "turn/completed", "params": {"threadId": thread, "turn": {"id": turn, "status": "completed"}}})
            continue
        try:
            send({"id": message["id"], "result": answer(method, params)})
        except KeyError:
            send({"id": message["id"], "error": {"code": -32601, "message": f"SYNTHETIC: {method} not provided"}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
