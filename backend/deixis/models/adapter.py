"""Model connection contract and the Codex App Server adapter.

The adapter never falls back to another connection or model. It starts a new,
ephemeral Codex thread per step in a DEIXIS-owned CODEX_HOME, refuses a thread
that reports loaded instruction files, and reports any tool item so the caller
can reject the output.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from deixis.models.codex_isolation import isolation_overrides
from deixis.models.codex_rpc import CodexAppServer, RpcError

# Variables the Codex app-server needs to run and reach the network. Provider keys and other
# settings loaded from .env are deliberately not passed on.
CODEX_ENV_ALLOWLIST = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "TEMP", "TMP", "LANG", "TERM",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy",
    "SYSTEMROOT", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "COMSPEC", "PATHEXT",
})


def codex_environment(codex_home: Path, source: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if source is None else source
    env = {k: v for k, v in source.items() if k in CODEX_ENV_ALLOWLIST or k.startswith("LC_")}
    env["CODEX_HOME"] = str(codex_home)
    return env


@dataclass
class ModelStepResult:
    status: str  # completed, failed, interrupted, unavailable, isolation_violation
    raw_text: str | None = None
    resolved_model: str | None = None
    external_thread_id: str | None = None
    token_usage: dict[str, Any] | None = None
    tool_item_types: list[str] = field(default_factory=list)
    error: str | None = None
    delivery_class: str | None = None
    # True when an adapter used a provider selector/alias exactly as requested
    # and separately reports the concrete model that answered.
    requested_model_verified: bool = False


RATE_LIMIT_ERROR_RE = re.compile(
    r"\b(429|rate.?limit(?:ed|ing|_error)?|too many requests|quota|resource_exhausted|resource has been exhausted)\b",
    re.IGNORECASE,
)


def is_rate_limited(result: ModelStepResult) -> bool:
    """Best-effort read of a failed call's free-text error as a provider rate limit or quota response.

    No adapter reports a structured rate-limit status today (unlike providers/common.py's search retries). A miss
    here only means the ordinary pause-on-failure path runs, which is always a correct (if less helpful) outcome.
    """
    return result.status == "failed" and bool(result.error) and bool(RATE_LIMIT_ERROR_RE.search(result.error))


class ModelAdapter(Protocol):
    connection: str

    async def health(self, refresh: bool = False) -> dict[str, Any]: ...

    async def run_step(self, base: str, developer: str, message: str, output_schema: dict[str, Any],
                       requested_model: str | None, reasoning_effort: str | None = None) -> ModelStepResult: ...

    async def cancel(self) -> bool: ...

    async def close(self) -> None: ...


class CodexAdapter:
    connection = "codex"

    def __init__(self, codex_home: Path, workspace: Path, turn_timeout: float = 300.0):
        self.codex_home = codex_home
        self.workspace = workspace
        self.turn_timeout = turn_timeout
        self._server: CodexAppServer | None = None
        self._lock = asyncio.Lock()
        self._health: tuple[float, dict[str, Any]] | None = None
        self._active: tuple[str, str] | None = None

    async def _ensure_server(self) -> CodexAppServer:
        if self._server and self._server.proc and self._server.proc.returncode is None:
            return self._server
        self.codex_home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.workspace.mkdir(parents=True, exist_ok=True)
        overrides, _ = isolation_overrides(config_path=self.codex_home / "config.toml")
        env = codex_environment(self.codex_home)
        server = CodexAppServer(["codex", "app-server", *overrides], cwd=str(self.workspace), env=env)
        await server.start()
        await server.initialize("deixis", "0.1.0")
        self._server = server
        return server

    async def health(self, refresh: bool = False) -> dict[str, Any]:
        if self._health and not refresh and time.monotonic() - self._health[0] < 60:
            return self._health[1]
        status: dict[str, Any] = {"connection": "codex", "installed": bool(shutil.which("codex")), "ready": False}
        if not status["installed"]:
            status["reason"] = "codex CLI not found"
            return status
        status["cli_version"] = subprocess.run(["codex", "--version"], capture_output=True, text=True).stdout.strip()
        try:
            async with self._lock:
                server = await self._ensure_server()
                account = (await server.request("account/read", {})).get("account") or {}
                status["signed_in"] = bool(account)
                status["account_type"] = account.get("type")
                status["plan_type"] = account.get("planType")
                models = await server.request("model/list", {})
                status["models"] = [
                    {"id": m["id"], "display_name": m.get("displayName") or m["id"], "is_default": bool(m.get("isDefault")),
                     "description": m.get("description") or "", "default_reasoning_effort": m.get("defaultReasoningEffort"),
                     "reasoning_efforts": [{"id": e["reasoningEffort"], "description": e.get("description") or ""}
                                           for e in m.get("supportedReasoningEfforts") or []]}
                    for m in models.get("data", []) if not m.get("hidden")
                ]
                mcp = await server.request("mcpServerStatus/list", {"detail": "toolsAndAuthOnly"})
                live_mcp = [m["name"] for m in mcp.get("data", []) if m.get("runtimeStatus") or m.get("tools")]
                thread = await server.request(
                    "thread/start",
                    {"cwd": str(self.workspace), "ephemeral": True, "sandbox": "read-only", "approvalPolicy": "never",
                     "baseInstructions": "DEIXIS isolation check."},
                )
                sources = thread.get("instructionSources") or []
                await server.request("thread/unsubscribe", {"threadId": thread["thread"]["id"]})
        except (RpcError, ConnectionError, TimeoutError, OSError) as exc:
            status["reason"] = f"codex app-server error: {str(exc)[:200]}"
            return status
        status["isolation"] = {"instruction_sources": len(sources), "live_mcp_servers": live_mcp}
        if not status["signed_in"]:
            status["reason"] = "Not signed in to the DEIXIS Codex home"
        elif sources or live_mcp:
            status["reason"] = "Isolation check failed: instruction files or MCP tools are loaded"
        else:
            status["ready"] = True
        self._health = (time.monotonic(), status)
        return status

    async def run_step(self, base: str, developer: str, message: str, output_schema: dict[str, Any],
                       requested_model: str | None, reasoning_effort: str | None = None) -> ModelStepResult:
        async with self._lock:
            try:
                server = await self._ensure_server()
                started = await server.request(
                    "thread/start",
                    {"cwd": str(self.workspace), "ephemeral": True, "sandbox": "read-only", "approvalPolicy": "never",
                     "model": requested_model, "baseInstructions": base, "developerInstructions": developer},
                    timeout=90,
                )
            except (RpcError, ConnectionError, TimeoutError, OSError) as exc:
                return ModelStepResult("unavailable", error=str(exc)[:300], delivery_class="before_send")
            thread_id = started["thread"]["id"]
            resolved = started.get("model")
            if started.get("instructionSources"):
                return ModelStepResult("isolation_violation", resolved_model=resolved, external_thread_id=thread_id,
                                       error="instruction files loaded into thread", delivery_class="before_send")

            async def remember(turn_id: str) -> None:
                self._active = (thread_id, turn_id)

            try:
                turn = await server.run_turn(thread_id, message, output_schema, timeout=self.turn_timeout, on_started=remember,
                                             effort=reasoning_effort)
            except (RpcError, ConnectionError, TimeoutError, OSError) as exc:
                return ModelStepResult("failed", resolved_model=resolved, external_thread_id=thread_id,
                                       error=str(exc)[:300], delivery_class="after_send_unknown")
            finally:
                self._active = None
            try:
                await server.request("thread/unsubscribe", {"threadId": thread_id}, timeout=10)
            except (RpcError, ConnectionError, TimeoutError):
                pass
        status = {"completed": "completed", "interrupted": "interrupted"}.get(turn.status, "failed")
        delivery = None if status == "completed" else "after_send_unknown"
        return ModelStepResult(
            status, raw_text=turn.final_text, resolved_model=resolved, external_thread_id=thread_id,
            token_usage=turn.token_usage, tool_item_types=turn.tool_item_types,
            error=str(turn.error)[:300] if turn.error else (None if status == "completed" else turn.status),
            delivery_class=delivery,
        )

    async def cancel(self) -> bool:
        if not (self._server and self._active):
            return False
        thread_id, turn_id = self._active
        try:
            await self._server.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id}, timeout=10)
            return True
        except (RpcError, ConnectionError, TimeoutError):
            return False

    async def close(self) -> None:
        if self._server:
            await self._server.close()
            self._server = None
