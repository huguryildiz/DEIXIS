"""Claude Code model connection through Anthropic's official Agent SDK.

The SDK control plane supplies the signed-in account's current model catalogue
and per-model effort levels without sending a model prompt. Research steps run
in fresh, non-persistent sessions with built-in tools, MCP servers, skills and
filesystem settings disabled. No fallback model is configured.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ClaudeSDKError,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from deixis.models.adapter import ModelStepResult
from deixis.domain.limits import limit_kind, service_error_kind, safe_error


def _model_matches(actual: str | None, expected: str) -> bool:
    # Context suffixes describe the window, not the model identity; preserve
    # the original reported string in provenance.
    return actual is not None and re.sub(r"\[[^\[\]]+\]$", "", actual) == re.sub(r"\[[^\[\]]+\]$", "", expected)


class ClaudeCodeAdapter:
    connection = "claude"
    enforces_schema = True

    def __init__(self, workspace: Path, turn_timeout: float = 300.0):
        self.workspace = workspace
        self.turn_timeout = turn_timeout
        self._health: tuple[float, dict[str, Any]] | None = None
        self._lock = asyncio.Lock()
        self._active: set[ClaudeSDKClient] = set()

    def _options(self, cli: str, **overrides: Any) -> ClaudeAgentOptions:
        self.workspace.mkdir(parents=True, exist_ok=True)
        options: dict[str, Any] = {
            "cli_path": cli,
            "cwd": self.workspace,
            "tools": [],
            "allowed_tools": [],
            "mcp_servers": {},
            "strict_mcp_config": True,
            "setting_sources": [],
            "skills": [],
            "permission_mode": "dontAsk",
            "fallback_model": None,
            "extra_args": {"no-session-persistence": None},
            "env": {
                "CLAUDE_CODE_SAFE_MODE": "1",
                "CLAUDE_AGENT_SDK_CLIENT_APP": "deixis/0.1.0",
            },
        }
        options.update(overrides)
        return ClaudeAgentOptions(**options)

    async def health(self, refresh: bool = False) -> dict[str, Any]:
        if self._health and not refresh and time.monotonic() - self._health[0] < 60:
            return self._health[1]
        cli = shutil.which("claude")
        status: dict[str, Any] = {"connection": self.connection, "installed": bool(cli), "ready": False}
        if not cli:
            status["reason"] = "Claude Code CLI not found"
            return status
        try:
            done = await asyncio.to_thread(subprocess.run, [cli, "--version"], capture_output=True, text=True, timeout=15)
            status["cli_version"] = done.stdout.strip() or None
            async with self._lock:
                async with ClaudeSDKClient(self._options(cli, system_prompt="DEIXIS model catalogue probe.")) as client:
                    info = await client.get_server_info() or {}
                    mcp = await client.get_mcp_status()
        except (ClaudeSDKError, OSError, subprocess.TimeoutExpired, TimeoutError) as exc:
            status["reason"] = f"Claude Code SDK error: {safe_error(str(exc))[:200]}"
            status["reason_code"] = service_error_kind(exc=exc)
            return status
        account = info.get("account") or {}
        status.update(
            signed_in=bool(account),
            account_type=account.get("subscriptionType"),
            plan_type=account.get("subscriptionType"),
            isolation={
                "instruction_sources": 0,
                "live_mcp_servers": [s["name"] for s in mcp.get("mcpServers", []) if s.get("status") == "connected"],
            },
            models=[
                {
                    "id": model["value"],
                    "display_name": model.get("displayName") or model["value"],
                    "resolved_model": model.get("resolvedModel"),
                    "is_default": model["value"] == "default",
                    "description": model.get("description") or "",
                    "default_reasoning_effort": model.get("defaultEffortLevel"),
                    "reasoning_efforts": [{"id": effort, "description": ""}
                                          for effort in model.get("supportedEffortLevels") or []],
                }
                for model in info.get("models", [])
                if model.get("value")
            ],
        )
        if not status["signed_in"]:
            status["reason_code"] = "auth_failed"
            status["reason"] = "Not signed in to Claude Code"
        elif status["isolation"]["live_mcp_servers"]:
            status["reason"] = "Isolation check failed: MCP servers are connected"
        else:
            status["ready"] = True
        self._health = (time.monotonic(), status)
        return status

    async def run_step(self, base: str, developer: str, message: str, output_schema: dict[str, Any],
                       requested_model: str | None, reasoning_effort: str | None = None) -> ModelStepResult:
        cli = shutil.which("claude")
        if not cli or not requested_model:
            return ModelStepResult("unavailable", error="Claude Code CLI not found" if not cli else "no model requested",
                                   delivery_class="before_send")
        options = self._options(
            cli,
            model=requested_model,
            effort=reasoning_effort,
            system_prompt=f"{base}\n\n{developer}",
            output_format={"type": "json_schema", "schema": output_schema},
            max_turns=1,
        )
        text_parts: list[str] = []
        tool_types: list[str] = []
        structured_output_received = False

        def external_tools() -> list[str]:
            # Claude's JSON-schema output is an internal StructuredOutput block.
            # Accept it only when the SDK also delivered the structured result.
            return [name for name in tool_types if not (structured_output_received and name == "StructuredOutput")]

        actual_model: str | None = None
        assistant_error: str | None = None
        expected_model = requested_model
        session_id: str | None = None
        usage: dict[str, Any] | None = None
        client: ClaudeSDKClient | None = None
        try:
            async with ClaudeSDKClient(options) as client:
                self._active.add(client)
                # Resolve selectors from this session's catalogue, not cached health
                # or a guessed model-name prefix. AssistantMessage.model comes from
                # the CLI's response and must match that concrete identity.
                info = await client.get_server_info() or {}
                expected_model = next((model.get("resolvedModel") or requested_model
                                       for model in info.get("models", [])
                                       if model.get("value") == requested_model), requested_model)
                await client.query(message)
                async with asyncio.timeout(self.turn_timeout):
                    async for item in client.receive_response():
                        if isinstance(item, AssistantMessage):
                            if item.error == "billing_error" or assistant_error != "billing_error":
                                assistant_error = item.error or assistant_error
                            # Keep a mismatch even if a later message uses the expected model.
                            if actual_model is None or _model_matches(actual_model, expected_model):
                                actual_model = item.model or actual_model
                            usage = item.usage or usage
                            for block in item.content:
                                if isinstance(block, TextBlock):
                                    text_parts.append(block.text)
                                elif isinstance(block, ToolUseBlock):
                                    tool_types.append(block.name)
                        elif isinstance(item, ResultMessage):
                            session_id = item.session_id
                            usage = item.usage or usage
                            if item.structured_output is not None:
                                structured_output_received = True
                                text_parts = [json.dumps(item.structured_output, ensure_ascii=False)]
                            elif item.result and not text_parts:
                                text_parts = [item.result]
                            if item.is_error:
                                error = "; ".join(item.errors or []) or item.result or item.subtype
                                kind = service_error_kind(item.api_error_status or assistant_error,
                                                          payload={"type": assistant_error}, text=error, surface="model")
                                return ModelStepResult(
                                    "failed", raw_text=None if item.api_error_status else "".join(text_parts) or None, resolved_model=actual_model,
                                    external_thread_id=session_id, token_usage=usage, tool_item_types=external_tools(),
                                    error=f"API request failed (HTTP {item.api_error_status})." if item.api_error_status else error,
                                    error_kind=kind, http_status=item.api_error_status,
                                    delivery_class="after_send_unknown",
                                    requested_model_verified=_model_matches(actual_model, expected_model),
                                )
        except TimeoutError:
            return ModelStepResult("failed", resolved_model=actual_model, external_thread_id=session_id,
                                   token_usage=usage, tool_item_types=tool_types, error="Claude Code turn timed out",
                                   delivery_class="after_send_unknown",
                                   requested_model_verified=_model_matches(actual_model, expected_model))
        except (ClaudeSDKError, OSError) as exc:
            return ModelStepResult("failed", resolved_model=actual_model, external_thread_id=session_id,
                                   token_usage=usage, tool_item_types=tool_types, error=safe_error(str(exc))[:300],
                                   delivery_class="after_send_unknown",
                                   requested_model_verified=_model_matches(actual_model, expected_model))
        finally:
            if client is not None:
                self._active.discard(client)
        return ModelStepResult(
            "completed", raw_text="".join(text_parts), resolved_model=actual_model,
            external_thread_id=session_id, token_usage=usage, tool_item_types=external_tools(),
            requested_model_verified=_model_matches(actual_model, expected_model),
        )

    async def cancel(self) -> bool:
        async def interrupt(client: ClaudeSDKClient) -> bool:
            try:
                await client.interrupt()
                return True
            except ClaudeSDKError:
                return False

        active = tuple(self._active)
        return any(await asyncio.gather(*(interrupt(client) for client in active))) if active else False

    async def close(self) -> None:
        active = tuple(self._active)
        if active:
            await asyncio.gather(*(client.disconnect() for client in active), return_exceptions=True)
            self._active.difference_update(active)
