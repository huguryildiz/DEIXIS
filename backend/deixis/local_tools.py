"""Command-line tools and local model servers on this computer (D29).

Detection reads the PATH, app bundles, `--version` output and the model servers' loopback endpoints. An install runs
the one package-manager command fixed for that tool id, never a command taken from a request. Codex and Claude Code run
research steps; the other CLI is detected only, and a local server's embedding models can rank answer passages.
"""

from __future__ import annotations

import asyncio
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from deixis.storage.db import now

CACHE_SECONDS = 30
INSTALL_TIMEOUT_SECONDS = 20 * 60
OUTPUT_TAIL_CHARS = 4000


@dataclass(frozen=True)
class Tool:
    id: str
    name: str
    kind: str  # 'cli' or 'server'
    binary: str
    install: tuple[str, ...]  # argv; the first item is the package manager, looked up on PATH
    url: str
    role: str = "detected"
    app: str | None = None  # a macOS app bundle that also counts as installed
    endpoint: str | None = None


TOOLS = {t.id: t for t in (
    Tool("claude_code", "Claude Code", "cli", "claude", ("npm", "install", "-g", "@anthropic-ai/claude-code"),
         "https://docs.claude.com/en/docs/claude-code/setup", role="runs_steps"),
    Tool("codex", "Codex CLI", "cli", "codex", ("npm", "install", "-g", "@openai/codex"),
         "https://developers.openai.com/codex/cli", role="runs_steps"),
    Tool("gemini_cli", "Gemini CLI", "cli", "gemini", ("npm", "install", "-g", "@google/gemini-cli"),
         "https://github.com/google-gemini/gemini-cli"),
    Tool("ollama", "Ollama", "server", "ollama", ("brew", "install", "ollama"), "https://ollama.com/download",
         app="/Applications/Ollama.app", endpoint="http://127.0.0.1:11434"),
    Tool("lm_studio", "LM Studio", "server", "lms", ("brew", "install", "--cask", "lm-studio"), "https://lmstudio.ai/download",
         app="/Applications/LM Studio.app", endpoint="http://127.0.0.1:1234"),
)}


class ToolError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _command_output(argv: list[str]) -> str | None:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=15)
    except (subprocess.TimeoutExpired, OSError):
        return None
    lines = [line.strip() for line in (done.stdout or done.stderr).strip().splitlines()]
    if done.returncode != 0 or not lines:
        return None
    # `ollama --version` warns first when its server is not running and names the version on a later line.
    line = next((line for line in lines if re.search(r"\d+\.\d+", line)), lines[0])
    return re.sub(r"^warning:\s*", "", line, flags=re.IGNORECASE)


def _app_version(app: str) -> str | None:
    try:
        with open(Path(app) / "Contents" / "Info.plist", "rb") as f:
            return plistlib.load(f).get("CFBundleShortVersionString")
    except (OSError, plistlib.InvalidFileException):
        return None


def machine() -> dict[str, Any]:
    chip = memory = None
    if sys.platform == "darwin":
        chip = _command_output(["sysctl", "-n", "machdep.cpu.brand_string"])
        memory_bytes = _command_output(["sysctl", "-n", "hw.memsize"])
        memory = int(memory_bytes) if memory_bytes and memory_bytes.isdigit() else None
    else:
        chip = platform.processor() or None
        try:
            memory = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        except (AttributeError, ValueError, OSError):
            memory = None
    return {"chip": chip, "memory_gb": round(memory / 2**30) if memory else None,
            "disk_free_gb": round(shutil.disk_usage(Path.home()).free / 2**30)}


class LocalTools:
    def __init__(self, client: httpx.AsyncClient):
        self._client = client
        self._cache: tuple[float, dict[str, Any]] | None = None
        self._jobs: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._procs: dict[str, asyncio.subprocess.Process] = {}

    async def snapshot(self, refresh: bool = False) -> dict[str, Any]:
        if refresh or not self._cache or time.monotonic() - self._cache[0] > CACHE_SECONDS:
            tools = await asyncio.gather(*(self._detect(tool) for tool in TOOLS.values()))
            self._cache = (time.monotonic(), {"machine": await asyncio.to_thread(machine), "tools": list(tools)})
        data = self._cache[1]
        return {**data, "tools": [{**t, "job": self._jobs.get(t["id"])} for t in data["tools"]]}

    async def _detect(self, tool: Tool) -> dict[str, Any]:
        path = shutil.which(tool.binary)
        app = tool.app if tool.app and Path(tool.app).exists() else None
        version = await asyncio.to_thread(_command_output, [path, "--version"]) if path else None
        manager = shutil.which(tool.install[0])
        models = await self._server_models(tool) if tool.kind == "server" else None
        status: dict[str, Any] = {
            # A server that answers counts as installed even when its binary is not on PATH.
            "id": tool.id, "name": tool.name, "kind": tool.kind, "installed": bool(path or app or models is not None),
            "version": version or (_app_version(app) if app else None), "path": path or app, "role": tool.role,
            "install": {"command": " ".join(tool.install), "available": bool(manager),
                        "unavailable_reason": None if manager else f"{tool.install[0]} was not found on this computer's PATH",
                        "url": tool.url},
        }
        if tool.kind == "server":
            status |={"endpoint": tool.endpoint, "running": models is not None, "models": models or []}
        return status

    async def _server_models(self, tool: Tool) -> list[dict[str, Any]] | None:
        """Models the running server lists, or None when it does not answer."""
        try:
            if tool.id == "ollama":
                tags = await self._client.get(f"{tool.endpoint}/api/tags", timeout=2)
                if tags.status_code != 200:
                    return None
                models = []
                for m in tags.json().get("models", []):
                    shown = await self._client.post(f"{tool.endpoint}/api/show", json={"model": m["name"]}, timeout=5)
                    capabilities = shown.json().get("capabilities", []) if shown.status_code == 200 else []
                    models.append({"id": m["name"], "size_bytes": m.get("size"), "embedding": "embedding" in capabilities})
                return models
            native = await self._client.get(f"{tool.endpoint}/api/v0/models", timeout=2)
            if native.status_code == 200:
                return [{"id": m["id"], "size_bytes": None, "embedding": m.get("type") == "embeddings"}
                        for m in native.json().get("data", [])]
            listed = await self._client.get(f"{tool.endpoint}/v1/models", timeout=2)
            if listed.status_code != 200:
                return None
            # The OpenAI-compatible list has no model type; LM Studio's embedding models carry "embed" in their ids.
            return [{"id": m["id"], "size_bytes": None, "embedding": "embed" in m["id"].lower()} for m in listed.json().get("data", [])]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None

    async def install(self, tool_id: str) -> dict[str, Any]:
        tool = TOOLS.get(tool_id)
        if tool is None:
            raise ToolError(404, f"Unknown tool '{tool_id}'")
        if (self._jobs.get(tool_id) or {}).get("status") == "running":
            raise ToolError(409, f"{tool.name} is already being installed")
        current = next(t for t in (await self.snapshot(refresh=True))["tools"] if t["id"] == tool_id)
        if current["installed"]:
            raise ToolError(409, f"{tool.name} is already installed")
        manager = shutil.which(tool.install[0])
        if not manager:
            raise ToolError(422, current["install"]["unavailable_reason"])
        job = {"status": "running", "command": " ".join(tool.install), "started_at": now(), "finished_at": None, "output": ""}
        self._jobs[tool_id] = job
        task = asyncio.create_task(self._run(tool_id, job, [manager, *tool.install[1:]]))
        self._tasks[tool_id] = task
        task.add_done_callback(lambda t, tool_id=tool_id: self._tasks.pop(tool_id, None))
        return job

    def cancel(self, tool_id: str) -> dict[str, Any]:
        tool = TOOLS.get(tool_id)
        if tool is None:
            raise ToolError(404, f"Unknown tool '{tool_id}'")
        job = self._jobs.get(tool_id)
        if not job or job["status"] != "running":
            raise ToolError(409, f"{tool.name} is not being installed")
        proc = self._procs.get(tool_id)
        if proc:
            proc.kill()
        self._tasks[tool_id].cancel()
        job.update(status="cancelled", finished_at=now())
        return job

    async def _run(self, tool_id: str, job: dict[str, Any], argv: list[str]) -> None:
        output = bytearray()
        env = {**os.environ, "HOMEBREW_NO_AUTO_UPDATE": "1", "NONINTERACTIVE": "1", "CI": "1"}

        async def read(proc: asyncio.subprocess.Process) -> int:
            assert proc.stdout is not None
            async for line in proc.stdout:
                output.extend(line)
                job["output"] = output[-OUTPUT_TAIL_CHARS:].decode("utf-8", "replace")
            return await proc.wait()

        try:
            proc = await asyncio.create_subprocess_exec(*argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                                        stderr=subprocess.STDOUT, env=env)
        except OSError as exc:
            job.update(status="failed", finished_at=now(), output=f"{type(exc).__name__}: {exc}")
            return
        self._procs[tool_id] = proc
        try:
            try:
                code = await asyncio.wait_for(read(proc), INSTALL_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                proc.kill()
                job.update(status="failed", finished_at=now(), output=job["output"] + "\nStopped after 20 minutes.")
                return
            job.update(status="succeeded" if code == 0 else "failed", finished_at=now())
            self._cache = None
        finally:
            self._procs.pop(tool_id, None)
