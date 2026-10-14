"""GitHub Copilot CLI model connection: research steps through the account signed in to Copilot CLI (D24).

Each step is one `copilot -p` run in prompt mode with JSONL output, in a DEIXIS-owned COPILOT_HOME and an empty
workspace. Copilot's tools cannot be switched off with an empty `--available-tools` (measured: the model still read a
file and ran a shell command), so the only available tool is a name that does not exist and every tool kind is also
denied. Built-in MCP servers and AGENTS.md-style instruction files are off; any MCP server that still connects, tool
request or tool run is reported so the step is rejected. The model catalogue comes from the account through Copilot's
ACP mode (`initialize` + `session/new`), which sends no prompt.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from deixis.models.adapter import CODEX_ENV_ALLOWLIST, ModelStepResult
from deixis.domain.limits import safe_error, service_error_kind

# A tool name Copilot does not have: with it as the only available tool, the model is offered none.
NO_TOOL = "deixis_no_tool"
DENIED_TOOLS = ("shell", "write", "read", "url", "memory")
ISOLATION_ARGS = (
    f"--available-tools={NO_TOOL}", *(f"--deny-tool={kind}" for kind in DENIED_TOOLS),
    "--disable-builtin-mcps", "--no-custom-instructions", "--no-ask-user", "--no-auto-update", "--no-color",
)


def native_binary(found: Path) -> str:
    """The platform binary behind npm's `copilot` launcher. The launcher is a node script that runs the binary as a
    child with the same pipes; stopping the launcher leaves the binary running and holding them, so DEIXIS runs the
    binary itself. A standalone install (Homebrew, WinGet, the install script) is the binary already."""
    real = found.resolve()
    # npm on Windows puts copilot.cmd next to node_modules; on macOS and Linux the link points into the package.
    package = real.parent if real.name == "npm-loader.js" else found.parent / "node_modules" / "@github" / "copilot"
    if not (package / "npm-loader.js").is_file():
        return str(found)
    plat = {"darwin": "darwin", "win32": "win32"}.get(sys.platform, "linux")
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(platform.machine().lower(), platform.machine().lower())
    name = "copilot.exe" if plat == "win32" else "copilot"
    plats = ["linuxmusl", "linux"] if plat == "linux" else [plat]
    for p in plats:
        for base in (package / "node_modules" / "@github", package.parent):  # nested, or hoisted next to the package
            candidate = base / f"copilot-{p}-{arch}" / name
            if candidate.is_file():
                return str(candidate)
    return str(found)


def copilot_environment(home: Path, source: Mapping[str, str] | None = None) -> dict[str, str]:
    """The variables Copilot needs to run and reach the network. GITHUB_TOKEN, GH_TOKEN and COPILOT_GITHUB_TOKEN are
    left out on purpose: Copilot would use them before the signed-in account, and GITHUB_TOKEN is the GitHub Models key
    of another connection (D22)."""
    source = os.environ if source is None else source
    env = {k: v for k, v in source.items() if k in CODEX_ENV_ALLOWLIST or k.startswith("LC_")}
    env.update(COPILOT_HOME=str(home), COPILOT_AUTO_UPDATE="false", NO_COLOR="1")
    return env


class CopilotCliAdapter:
    connection = "copilot_cli"
    enforces_schema = False

    def __init__(self, home: Path, workspace: Path, turn_timeout: float = 300.0, cli: list[str] | None = None):
        self.home = home
        self.workspace = workspace
        self.turn_timeout = turn_timeout
        self._cli = cli  # tests pass a fake; otherwise `copilot` on PATH (copilot.cmd on Windows)
        self._health: tuple[float, dict[str, Any]] | None = None
        self._active: set[asyncio.subprocess.Process] = set()

    @staticmethod
    def _spawn_options() -> dict[str, Any]:
        # Its own process group, so a stop also reaches anything the binary started.
        if sys.platform == "win32":
            return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        return {"start_new_session": True}

    @staticmethod
    def _stop(proc: asyncio.subprocess.Process, sig: int = signal.SIGKILL if hasattr(signal, "SIGKILL") else signal.SIGTERM) -> None:
        if proc.returncode is not None:
            return
        try:
            if sys.platform == "win32":
                proc.kill()
            else:
                os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    def _command(self) -> list[str] | None:
        if self._cli is not None:
            return list(self._cli)
        found = shutil.which("copilot")
        return [native_binary(Path(found))] if found else None

    def _prepare(self) -> dict[str, str]:
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.workspace.mkdir(parents=True, exist_ok=True)
        return copilot_environment(self.home)

    def _configured_mcp_servers(self) -> list[str]:
        try:
            servers = json.loads((self.home / "mcp-config.json").read_text(encoding="utf-8")).get("mcpServers") or {}
        except (OSError, ValueError, AttributeError):
            return []
        return sorted(servers) if isinstance(servers, dict) else []

    async def _acp_catalogue(self, cmd: list[str], env: dict[str, str]) -> dict[str, Any]:
        """`session/new`'s result: the signed-in account's models. Raises RuntimeError with the agent's error text."""
        proc = await asyncio.create_subprocess_exec(
            *cmd, "--acp", "--disable-builtin-mcps", "--no-custom-instructions", "--no-auto-update",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=self.workspace, env=env, **self._spawn_options())
        assert proc.stdin and proc.stdout

        async def call(rid: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
            proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}) + "\n").encode())
            await proc.stdin.drain()
            while True:
                line = await proc.stdout.readline()
                if not line:
                    raise RuntimeError("Copilot CLI closed the ACP connection")
                try:
                    reply = json.loads(line)
                except ValueError:
                    continue
                if reply.get("id") == rid:
                    if "error" in reply:
                        raise RuntimeError(str((reply["error"] or {}).get("message") or reply["error"]))
                    return reply.get("result") or {}

        try:
            async with asyncio.timeout(60):
                await call(1, "initialize", {"protocolVersion": 1, "clientCapabilities": {}})
                return await call(2, "session/new", {"cwd": str(self.workspace), "mcpServers": []})
        finally:
            self._stop(proc)
            await proc.wait()

    async def health(self, refresh: bool = False) -> dict[str, Any]:
        if self._health and not refresh and time.monotonic() - self._health[0] < 60:
            return self._health[1]
        cmd = self._command()
        status: dict[str, Any] = {"connection": self.connection, "installed": bool(cmd), "ready": False}
        if not cmd:
            status["reason"] = "GitHub Copilot CLI not found"
            return status
        env = self._prepare()
        try:
            done = await asyncio.create_subprocess_exec(*cmd, "--version", stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.DEVNULL, env=env,
                                                        **self._spawn_options())
            try:
                out, _ = await asyncio.wait_for(done.communicate(), 15)
            finally:
                self._stop(done)
            version = re.search(r"\d+(?:\.\d+)+", out.decode(errors="replace"))
            status["cli_version"] = version.group(0) if version else None
            session = await self._acp_catalogue(cmd, env)
        except (OSError, RuntimeError, TimeoutError) as exc:
            text = safe_error(str(exc))[:200]
            status["signed_in"] = False if "auth" in text.lower() or "login" in text.lower() else None
            status["reason_code"] = "auth_failed" if status["signed_in"] is False else service_error_kind(exc=exc)
            status["reason"] = f"Copilot CLI error: {text}"
            return status
        status["signed_in"] = True
        status["isolation"] = {"instruction_sources": 0, "live_mcp_servers": self._configured_mcp_servers()}
        catalogue = (session.get("models") or {}).get("availableModels") or []
        status["models"] = [
            {"id": m["modelId"], "display_name": m.get("name") or m["modelId"], "is_default": False,
             "description": "" if m.get("description") in (None, m.get("name")) else m["description"], "default_reasoning_effort": None, "reasoning_efforts": [],
             "usage": (m.get("_meta") or {}).get("copilotUsage")}
            # "auto" lets Copilot pick a model per request; a step asks for one model and checks that it answered.
            for m in catalogue
            if m.get("modelId") and m["modelId"] != "auto" and (m.get("_meta") or {}).get("copilotEnablement", "enabled") == "enabled"
        ]
        if status["isolation"]["live_mcp_servers"]:
            status["reason"] = "Isolation check failed: MCP servers are configured in the DEIXIS Copilot home"
        elif not status["models"]:
            status["reason"] = "Copilot CLI lists no models for this account"
        else:
            status["ready"] = True
        self._health = (time.monotonic(), status)
        return status

    async def run_step(self, base: str, developer: str, message: str, output_schema: dict[str, Any],
                       requested_model: str | None, reasoning_effort: str | None = None) -> ModelStepResult:
        cmd = self._command()
        if not cmd or not requested_model:
            return ModelStepResult("unavailable", error="GitHub Copilot CLI not found" if not cmd else "no model requested",
                                   delivery_class="before_send")
        env = self._prepare()
        # Prompt mode has no separate system message; the schema is in the stored developer text (D86).
        prompt = f"{base}\n\n{developer}\n\nReturn only a JSON object.\n\n{message}"
        args = [*cmd, "-p", "", "--output-format", "json", "--model", requested_model, *ISOLATION_ARGS]
        if reasoning_effort:
            args += ["--reasoning-effort", reasoning_effort]
        try:
            proc = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.PIPE, cwd=self.workspace, env=env,
                                                        **self._spawn_options())
        except OSError as exc:
            return ModelStepResult("unavailable", error=safe_error(str(exc))[:300], delivery_class="before_send")
        self._active.add(proc)
        try:
            out, err = await asyncio.wait_for(proc.communicate(prompt.encode()), self.turn_timeout)
        except TimeoutError:
            self._stop(proc)
            await proc.wait()
            return ModelStepResult("failed", error="Copilot CLI turn timed out", delivery_class="after_send_unknown")
        finally:
            self._active.discard(proc)
        return parse_events(out.decode(errors="replace"), err.decode(errors="replace"), proc.returncode, requested_model)

    async def cancel(self) -> bool:
        active = tuple(self._active)
        for proc in active:
            self._stop(proc, signal.SIGTERM)
        return bool(active)

    async def close(self) -> None:
        await self.cancel()


def parse_events(stdout: str, stderr: str, returncode: int | None, requested_model: str) -> ModelStepResult:
    """One `copilot -p --output-format json` run's JSONL into a step result."""
    actual_model: str | None = None
    content: str | None = None
    tools: list[str] = []
    live_mcp: list[str] = []
    errors: list[str] = []
    usage: dict[str, Any] | None = None
    session_id: str | None = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            if line.strip():
                errors.append(line.strip())
            continue
        if not isinstance(event, dict):
            continue
        kind, data = event.get("type") or "", event.get("data") or {}
        if kind == "session.mcp_servers_loaded":
            live_mcp += [s.get("name") or "?" for s in data.get("servers") or [] if s.get("status") == "connected"]
        elif kind == "assistant.message":
            # Keep a mismatch even if a later message uses the requested model.
            if actual_model is None or actual_model == requested_model:
                actual_model = data.get("model") or actual_model
            if data.get("content"):
                content = data["content"]
            tools += [t.get("name") or "?" for t in data.get("toolRequests") or []]
        elif kind == "tool.execution_start":
            tools.append(data.get("toolName") or "?")
        elif kind == "model.call_final_result" and data.get("result") not in (None, "success"):
            errors.append(str(data.get("error") or data.get("result")))
        elif kind == "session.error" or kind.endswith(".error"):
            errors.append(str(data.get("message") or data.get("error") or kind))
        elif kind == "session.usage_checkpoint":
            for metric in data.get("providerModelMetrics") or []:
                usage = (metric.get("metrics") or {}).get("usage") or usage
        elif kind == "result":
            session_id = event.get("sessionId") or session_id
    errors += [line.strip() for line in stderr.splitlines() if line.strip()][-3:]
    common: dict[str, Any] = {"resolved_model": actual_model, "external_thread_id": session_id, "token_usage": usage,
                              "tool_item_types": tools, "requested_model_verified": actual_model == requested_model}
    if live_mcp:
        return ModelStepResult("isolation_violation", error=f"MCP servers connected: {', '.join(live_mcp)}",
                               delivery_class="after_send_unknown", **common)
    if returncode != 0 or content is None:
        error = "; ".join(errors) or f"Copilot CLI exited with code {returncode}"
        sent = actual_model is not None
        return ModelStepResult("failed", raw_text=content, error=safe_error(error)[:300],
                               delivery_class="after_send_unknown" if sent else "before_send", **common)
    return ModelStepResult("completed", raw_text=content, **common)
