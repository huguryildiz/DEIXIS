"""Two requests at once start one install, one update or one sign-in (pre-P10 A3 review, E17).

The tool search now runs in a thread, so a request awaits between its "already running" check and its job. These tests
make that wait long (a slow find_tool) and send two requests together. Fake installers are shell scripts that append a
line to a file when they run."""

import asyncio
import dataclasses
import sys
import time

import httpx
import pytest

from deixis.keys import account_signin
from deixis.tools import local_tools
from deixis.keys.account_signin import AccountSignIn
from deixis.tools.local_tools import LocalTools, ToolError

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="the fake installers are shell scripts")


def refuse_everything(request):
    raise httpx.ConnectError("connection refused", request=request)


@pytest.fixture
def tools(monkeypatch):
    monkeypatch.setattr(local_tools, "TOOLS", {k: dataclasses.replace(t, app=None) for k, t in local_tools.TOOLS.items()})
    monkeypatch.setattr(local_tools, "machine", lambda: {"chip": "SYNTHETIC", "memory_gb": 32, "disk_free_gb": 100, "disk_total_gb": 500})
    monkeypatch.setattr(local_tools, "OLLAMA_MAC", False)
    monkeypatch.setattr(local_tools, "LMSTUDIO_MAC", False)
    found = {}

    def find(name):
        time.sleep(0.3)  # a tool search that takes a while, as the first login-shell read does
        return found.get(name)
    monkeypatch.setattr(local_tools, "find_tool", find)
    client = httpx.AsyncClient(transport=httpx.MockTransport(refuse_everything))
    return LocalTools(client), found


def installer(path, body="sleep 0.3\n"):
    path.write_text("#!/bin/sh\necho ran >> " + str(path) + ".log\n" + body)
    path.chmod(0o755)
    return str(path)


def runs(path):
    log = type(path)(str(path) + ".log")
    return log.read_text().count("ran") if log.exists() else 0


async def finish(tools_, tool_id):
    while (tools_._jobs.get(tool_id) or {}).get("status") == "running":
        await asyncio.sleep(0.05)


@posix_only
def test_two_installs_at_once_start_one_process(tools, tmp_path):
    local, found = tools
    found["uv"] = installer(tmp_path / "uv")

    async def scenario():
        results = await asyncio.gather(local.install("kimi_cli"), local.install("kimi_cli"), return_exceptions=True)
        await finish(local, "kimi_cli")
        return results
    results = asyncio.run(scenario())
    errors = [r for r in results if isinstance(r, ToolError)]
    assert len(errors) == 1 and errors[0].status == 409 and sum(isinstance(r, dict) for r in results) == 1
    assert runs(tmp_path / "uv") == 1
    assert local._jobs["kimi_cli"]["status"] == "succeeded"


# ---- sign-in ------------------------------------------------------------------------------------

def sign_in(tmp_path, monkeypatch, find):
    launched = []

    async def check(tool):
        return False
    monkeypatch.setattr(account_signin, "find_tool", find)
    return AccountSignIn(tmp_path / "codex-home", check, launcher=launched.append, platform="linux"), launched


def test_two_sign_ins_at_once_open_one_terminal(tmp_path, monkeypatch):
    def slow(name):
        time.sleep(0.3)
        return f"/usr/local/bin/{name}"
    signin, launched = sign_in(tmp_path, monkeypatch, slow)
    monkeypatch.setattr(account_signin, "build_launch", lambda *a, **k: ["terminal", "codex", "login"])

    async def scenario():
        views = await asyncio.gather(signin.start("codex"), signin.start("codex"))
        during = []

        async def poll():
            during.append(await signin.state("codex"))
        await poll()
        return views, during
    views, during = asyncio.run(scenario())
    assert len(launched) == 1 and [v["state"] for v in views] == ["waiting", "waiting"] and during[0]["state"] == "waiting"


def downloader(monkeypatch):
    """A LocalTools whose server check is slow, with Ollama and LM Studio running, counting the requests that start a download."""
    sent = []

    def handler(request):
        sent.append(str(request.url))
        if request.url.path == "/api/pull":
            return httpx.Response(200, content=b'{"status":"success"}')
        return httpx.Response(200, json={"status": "already_downloaded", "total_size_bytes": 5})
    local = LocalTools(httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    async def slow_snapshot(refresh=False):
        await asyncio.sleep(0.2)  # the server check that runs between the "already running" check and the job
        return {"tools": [{"id": "ollama", "running": True, "models": []}, {"id": "lm_studio", "running": True}]}
    monkeypatch.setattr(local, "snapshot", slow_snapshot)
    return local, sent


