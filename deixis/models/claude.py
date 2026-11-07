"""Claude Code model connection through Anthropic's official Agent SDK.

The SDK control plane supplies the signed-in account's current model catalogue
and per-model effort levels without sending a model prompt. Research steps run
in fresh, non-persistent sessions with built-in tools, MCP servers, skills and
filesystem settings disabled. No fallback model is configured.

Claude Code delivers JSON-schema output through its internal StructuredOutput tool, which checks the answer against
the schema and, when it does not match, lets the model try again in a further turn. A step gets MAX_TURNS turns for
that: a session that ends at the limit or at the CLI's retry limit without a valid answer hands its last
StructuredOutput attempt to DEIXIS's own validation, which accepts it or starts the step's bounded repair.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

import claude_agent_sdk
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ClaudeSDKError,
    CLIConnectionError,
    RateLimitEvent,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from claude_agent_sdk._internal.transport import subprocess_cli

from deixis.tools.child_env import NODE_TLS, child_env
from deixis.models import cli_process, quota
from deixis.models.adapter import ModelStepResult
from deixis.domain.limits import limit_kind, service_error_kind, safe_error
from deixis.tools.tool_paths import child_path, command_for, find_tool
from deixis.tools.tool_probe import probe
from deixis.tools import win_job


# The first turn and up to two more for the CLI's StructuredOutput retries.
MAX_TURNS = 3
# Result subtypes that mean the model answered but no StructuredOutput call passed the CLI's schema check.
NO_VALID_STRUCTURED_OUTPUT = ("error_max_turns", "error_max_structured_output_retries")


def _model_matches(actual: str | None, expected: str) -> bool:
    # Context suffixes describe the window, not the model identity; preserve
    # the original reported string in provenance.
    return actual is not None and re.sub(r"\[[^\[\]]+\]$", "", actual) == re.sub(r"\[[^\[\]]+\]$", "", expected)


# Claude Code's own telemetry, error reporting and other nonessential traffic, switched off with the variables its
# documentation lists (code.claude.com/docs/en/env-vars: DISABLE_TELEMETRY, DISABLE_ERROR_REPORTING and
# CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC, which also covers auto-updates and /feedback). Any non-empty value turns them on (F3).
TELEMETRY_OFF = {"DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}

# P10 W2: on Windows every process the SDK's transport opens (the CLI and its own --version check) starts suspended in a
# kill-on-close job of its own before it runs (`cli_process.spawn_in_jobs`); on macOS the CLI stays in the backend's
# process group, where the desktop watchdog finds it (P10 M2).
JOBS_ON = cli_process.spawn_in_jobs(subprocess_cli)
# The SDK versions whose transport was read and tested with this hook (tests/rules/test_windows_jobs.py). Another
# version may start its processes some other way, so on Windows it is refused until it is checked and added here.
JOB_HOOK_SDK = frozenset({"0.2.152"})


class NotInJob(CLIConnectionError):
    """Nothing was started: this SDK's processes cannot be put in a job."""


class JobTransport(subprocess_cli.SubprocessCLITransport):
    """Windows: the SDK's own subprocess transport, refusing to start when its processes would not go into a job, and
    ending the CLI's job when it closes, so whatever the CLI started goes too, also after the CLI's own clean exit."""

    async def connect(self) -> None:
        # Fail closed before anything starts: an SDK whose transport no longer starts processes through `anyio`, or a
        # version this hook was not checked against.
        if not JOBS_ON or claude_agent_sdk.__version__ not in JOB_HOOK_SDK:
            raise NotInJob("Claude Code was not started: its process could not be put in a job")
        await super().connect()
        if not cli_process.joined_job(self._process):  # started some other way after all: stop it, report nothing sent
            proc, self._process = self._process, None
            if proc is not None:
                cli_process.stop_group(proc)
            raise NotInJob("Claude Code was stopped: its process did not start inside a job")

    async def close(self) -> None:
        proc = self._process
        try:
            await super().close()
        finally:
            if proc is not None:
                cli_process.stop_group(proc)


def sdk_client(options: ClaudeAgentOptions) -> ClaudeSDKClient:
    """The SDK client; on Windows over JobTransport (no prompt: DEIXIS sends its message with `query`)."""
    if not cli_process.WINDOWS:
        return ClaudeSDKClient(options)
    return ClaudeSDKClient(options, transport=JobTransport(prompt="", options=options))


def _not_started(exc: BaseException) -> bool:
    """The CLI was never run (P10 W2): it could not join its job and was terminated unrun, so nothing was sent."""
    return isinstance(exc, (win_job.JobError, NotInJob)) or isinstance(exc.__cause__, win_job.JobError)


class ClaudeCodeAdapter:
    connection = "claude"
    enforces_schema = True
    sends_reasoning_effort = True  # ClaudeAgentOptions(effort=...)

    def __init__(self, workspace: Path, turn_timeout: float = 300.0):
        self.workspace = workspace
        self.turn_timeout = turn_timeout
        self._health: tuple[float, dict[str, Any]] | None = None
        self._checks = 0  # health checks started, to order their answers
        self._lock = asyncio.Lock()
        self._active: set[ClaudeSDKClient] = set()
        # The usage limit the CLI reported on the last call (there is no live read), kept across restarts.
        self._quota_file = workspace.parent / "claude-quota.json"
        self._quota: dict[str, Any] | None = None

    async def quota(self) -> dict[str, Any] | None:
        """Claude's usage limit as reported on the last call, with that call's time; None before any call."""
        return self._quota or await asyncio.to_thread(quota.load, self._quota_file)

    def _note_quota(self, raw: Any) -> None:
        windows = quota.claude_windows(raw)
        if windows:
            self._quota = {"source": "last_call", "seen_at": quota.now_iso(), "windows": windows}
            quota.save(self._quota_file, self._quota)

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
                # The CLI inherits the app's environment, where a key saved for the Anthropic API connection lives;
                # emptied here so this connection runs on the signed-in account, never on that key.
                "ANTHROPIC_API_KEY": "",
                # An npm-installed CLI is a node script: node's folder must be on PATH when DEIXIS started with a short one.
                "PATH": child_path(cli),
                **NODE_TLS,  # an npm-installed CLI trusts the system certificates (F1)
                **TELEMETRY_OFF,
            },
        }
        options.update(overrides)
        return ClaudeAgentOptions(**options)

    async def health(self, refresh: bool = False) -> dict[str, Any]:
        if self._health and not refresh and time.monotonic() - self._health[0] < 60:
            return self._health[1]
        self._checks += 1
        check = self._checks
        status = await self._check()
        if check == self._checks:  # a check that started later owns the cache: only the newest may write it, whatever it found (E7)
            self._health = (time.monotonic(), status)
        elif self._health:
            return self._health[1]  # a newer check owns the answer: the caller gets that one, not this stale one
        return status

    async def _check(self) -> dict[str, Any]:
        found = command_for("claude", await asyncio.to_thread(find_tool, "claude"))
        status: dict[str, Any] = {"connection": self.connection, "installed": bool(found.found), "ready": False}
        if not found.found:
            status["reason"] = "Claude Code CLI not found"
            return status
        if found.problem:  # the SDK starts one executable and refuses a Windows batch launcher (A4)
            status["reason_code"], status["reason"] = "unsupported_install", found.problem
            return status
        cli = found.argv[0]
        version = await probe([cli, "--version"], env=child_env(TELEMETRY_OFF, tool=cli))  # no saved key reaches the probe
        if version.error == "not_responding":
            status["reason_code"] = "timeout"
            status["reason"] = "Claude Code CLI is not responding"
            return status
        status["cli_version"] = version.stdout.strip() or None
        try:
            async with self._lock:
                async with sdk_client(self._options(cli, system_prompt="DEIXIS model catalogue probe.")) as client:
                    info = await client.get_server_info() or {}
                    mcp = await client.get_mcp_status()
        except (ClaudeSDKError, OSError, TimeoutError) as exc:
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
        return status

    async def run_step(self, base: str, developer: str, message: str, output_schema: dict[str, Any],
                       requested_model: str | None, reasoning_effort: str | None = None) -> ModelStepResult:
        found = command_for("claude", await asyncio.to_thread(find_tool, "claude"))
        cli = found.argv[0] if found.argv else None
        if not cli or not requested_model:
            return ModelStepResult("unavailable", error=(found.problem or "Claude Code CLI not found") if not cli else "no model requested",
                                   delivery_class="before_send")
        options = self._options(
            cli,
            model=requested_model,
            effort=reasoning_effort,
            system_prompt=f"{base}\n\n{developer}",
            output_format={"type": "json_schema", "schema": output_schema},
            max_turns=MAX_TURNS,
        )
        text_parts: list[str] = []
        tool_types: list[str] = []
        attempts: list[Any] = []  # every StructuredOutput call's input, in order
        carrier_ids: set[str] = set()

        def external_tools() -> list[str]:
            # StructuredOutput is the CLI's own carrier for JSON-schema output (offered only because of output_format;
            # built-in tools and MCP servers are off). Any other tool action is an isolation violation.
            return [name for name in tool_types if name != "StructuredOutput"]

        def note_block(block: Any, from_user: bool = False) -> None:
            # Fail closed, in assistant and user messages alike: text, thinking, the model's StructuredOutput
            # calls and the results of those calls pass; every other block the SDK parses (another tool call, a
            # StructuredOutput call in a user message, a server tool use such as web_search, a server tool result, a
            # result for an unknown call, a block type this adapter does not know) is recorded as a tool action.
            # A user message's text is not the model's answer and is not kept.
            if isinstance(block, TextBlock):
                if not from_user:
                    text_parts.append(block.text)
            elif isinstance(block, ThinkingBlock):
                pass
            elif isinstance(block, ToolUseBlock) and block.name == "StructuredOutput" and not from_user:
                tool_types.append(block.name)
                carrier_ids.add(block.id)
                attempts.append(block.input)
            elif isinstance(block, ToolResultBlock) and block.tool_use_id in carrier_ids:
                pass
            else:
                name = getattr(block, "name", None)
                tool_types.append(name if isinstance(name, str) and name and name != "StructuredOutput"
                                  else type(block).__name__)

        actual_model: str | None = None
        assistant_error: str | None = None
        expected_model = requested_model
        session_id: str | None = None
        usage: dict[str, Any] | None = None
        client: ClaudeSDKClient | None = None
        try:
            async with sdk_client(options) as client:
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
                                note_block(block)
                        elif isinstance(item, UserMessage):
                            for block in item.content if isinstance(item.content, list) else []:
                                note_block(block, from_user=True)
                        elif isinstance(item, RateLimitEvent):
                            self._note_quota(item.rate_limit_info.raw)
                        elif isinstance(item, ResultMessage):
                            session_id = item.session_id
                            usage = item.usage or usage
                            if item.structured_output is not None:
                                text_parts = [json.dumps(item.structured_output, ensure_ascii=False)]
                            elif item.result and not text_parts:
                                text_parts = [item.result]
                            if item.is_error:
                                error = "; ".join(item.errors or []) or item.result or item.subtype
                                if (item.subtype in NO_VALID_STRUCTURED_OUTPUT and item.structured_output is None
                                        and item.api_error_status is None and assistant_error is None
                                        and attempts and not external_tools()):
                                    # The model answered, but no attempt passed the CLI's schema check within the
                                    # turn limit. Its last attempt goes to DEIXIS's normalisation and validation, which
                                    # accept it or start the bounded repair; the CLI's verdict is kept with the record.
                                    return ModelStepResult(
                                        "completed", raw_text=json.dumps(attempts[-1], ensure_ascii=False),
                                        resolved_model=actual_model, external_thread_id=session_id, token_usage=usage,
                                        error=error, requested_model_verified=_model_matches(actual_model, expected_model),
                                        transport={"structured_output": {"rejected_by_cli": item.subtype, "error": safe_error(error),
                                                                         "attempts": len(attempts), "turns": item.num_turns}},
                                    )
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
                                   token_usage=usage, tool_item_types=external_tools(), error="Claude Code turn timed out",
                                   delivery_class="after_send_unknown",
                                   requested_model_verified=_model_matches(actual_model, expected_model))
        except (ClaudeSDKError, OSError) as exc:
            return ModelStepResult("failed", resolved_model=actual_model, external_thread_id=session_id,
                                   token_usage=usage, tool_item_types=external_tools(), error=safe_error(str(exc))[:300],
                                   delivery_class="before_send" if _not_started(exc) else "after_send_unknown",
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
