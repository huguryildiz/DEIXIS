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

from deixis import account_signin, local_tools
from deixis.account_signin import AccountSignIn, SignInError
from deixis.local_tools import LocalTools, ToolError

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


@posix_only
def test_a_refused_install_gives_the_slot_back(tools, tmp_path):
    local, found = tools

    async def scenario():
        with pytest.raises(ToolError) as refused:
            await local.install("kimi_cli")  # no uv on this computer
        assert refused.value.status == 422 and "kimi_cli" not in local._jobs
        found["uv"] = installer(tmp_path / "uv", "exit 0\n")
        job = await local.install("kimi_cli")
        await finish(local, "kimi_cli")
        return job
    assert asyncio.run(scenario())["status"] in {"running", "succeeded"}
    assert runs(tmp_path / "uv") == 1


@posix_only
def test_a_cancel_during_the_tool_search_raises_no_key_error_and_starts_nothing(tools, tmp_path):
    local, found = tools
    found["uv"] = installer(tmp_path / "uv")

    async def scenario():
        first = asyncio.create_task(local.install("kimi_cli"))
        await asyncio.sleep(0.1)  # the request is waiting for the tool search
        second = await asyncio.gather(local.install("kimi_cli"), return_exceptions=True)
        cancelled = local.cancel("kimi_cli")  # no task or process exists yet
        outcome = (await asyncio.gather(first, return_exceptions=True))[0]
        return second[0], cancelled, outcome
    second, cancelled, outcome = asyncio.run(scenario())
    assert isinstance(second, ToolError) and second.status == 409
    assert cancelled["status"] == "cancelled"
    assert isinstance(outcome, ToolError) and outcome.status == 409
    assert runs(tmp_path / "uv") == 0


def test_two_updates_at_once_run_one_upgrade(tools, tmp_path, monkeypatch):
    local, found = tools
    ran = []

    async def run(self, tool_id, job, argv):
        ran.append(argv[1:])
        await asyncio.sleep(0.2)
        job.update(status="succeeded", finished_at="SYNTHETIC")

    monkeypatch.setattr(LocalTools, "_run", run)
    monkeypatch.setattr(local_tools, "_command_output", lambda argv, timeout=None: "")
    found.update(ollama="/opt/homebrew/bin/ollama", brew="/opt/homebrew/bin/brew")

    async def scenario():
        results = await asyncio.gather(local.update("ollama"), local.update("ollama"), return_exceptions=True)
        await finish(local, "ollama")
        return results
    results = asyncio.run(scenario())
    assert sum(isinstance(r, ToolError) and r.status == 409 for r in results) == 1 and sum(isinstance(r, dict) for r in results) == 1
    assert ran == [["upgrade", "ollama"]]


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


def test_a_sign_in_that_cannot_start_leaves_no_waiting_state_and_can_be_tried_again(tmp_path, monkeypatch):
    found = {"codex": None}

    def find(name):
        time.sleep(0.1)
        return found.get(name)
    signin, launched = sign_in(tmp_path, monkeypatch, find)
    monkeypatch.setattr(account_signin, "build_launch", lambda *a, **k: ["terminal"])

    async def scenario():
        with pytest.raises(SignInError):
            await signin.start("codex")
        idle = dict(await signin.state("codex"))
        found["codex"] = "/usr/local/bin/codex"
        return idle, await signin.start("codex")
    idle, view = asyncio.run(scenario())
    assert idle["state"] == "idle" and view["state"] == "waiting" and len(launched) == 1


def test_the_health_check_does_not_run_before_the_terminal_is_open(tmp_path, monkeypatch):
    checks = []

    async def check(tool):
        checks.append(tool)
        return True  # an older session is open: it must not count as this sign-in
    clock = [1000.0]
    monkeypatch.setattr(account_signin, "find_tool", lambda name: (time.sleep(0.2), "/bin/codex")[1])
    monkeypatch.setattr(account_signin, "build_launch", lambda *a, **k: ["terminal"])
    signin = AccountSignIn(tmp_path / "h", check, launcher=lambda spec: None, platform="linux", interval=0, clock=lambda: clock[0])

    async def scenario():
        starting = asyncio.create_task(signin.start("codex"))
        await asyncio.sleep(0.05)
        clock[0] += 5
        view = await signin.state("codex")
        await starting
        return view
    view = asyncio.run(scenario())
    assert checks == [] and view["state"] == "waiting"


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


def test_two_ollama_downloads_at_once_start_one(monkeypatch):
    local, sent = downloader(monkeypatch)

    async def scenario():
        results = await asyncio.gather(local.pull_model("qwen3:8b"), local.pull_model("qwen3:8b"), return_exceptions=True)
        await local._pull_task
        return results
    results = asyncio.run(scenario())
    errors = [r for r in results if isinstance(r, ToolError)]
    assert len(errors) == 1 and errors[0].status == 409 and sum(isinstance(r, dict) for r in results) == 1
    assert sent.count("http://127.0.0.1:11434/api/pull") == 1 and local._pull["status"] == "succeeded"


def test_two_lm_studio_downloads_at_once_start_one(monkeypatch):
    local, sent = downloader(monkeypatch)

    async def scenario():
        return await asyncio.gather(local.lm_studio_pull("qwen/qwen3.5-9b"), local.lm_studio_pull("qwen/qwen3.5-9b"),
                                    return_exceptions=True)
    results = asyncio.run(scenario())
    errors = [r for r in results if isinstance(r, ToolError)]
    assert len(errors) == 1 and errors[0].status == 409 and sum(isinstance(r, dict) for r in results) == 1
    assert sent.count("http://127.0.0.1:1234/api/v1/models/download") == 1


def test_a_refused_download_gives_the_slot_back(monkeypatch):
    local, sent = downloader(monkeypatch)
    real = local.snapshot

    async def down(refresh=False):
        data = await real(refresh)
        return {"tools": [{**t, "running": False} for t in data["tools"]]}
    monkeypatch.setattr(local, "snapshot", down)

    async def scenario():
        for pull in (local.pull_model("qwen3:8b"), local.lm_studio_pull("qwen/qwen3.5-9b")):
            with pytest.raises(ToolError):
                await pull  # the server is not running
        assert local._pull is None and local._lms_pull is None
        monkeypatch.setattr(local, "snapshot", real)
        return await local.pull_model("qwen3:8b"), await local.lm_studio_pull("qwen/qwen3.5-9b")
    ollama, lms = asyncio.run(scenario())
    assert ollama["status"] in ("running", "succeeded") and lms["status"] == "succeeded"
