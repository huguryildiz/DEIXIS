"""Gemini CLI model connection with the person's Google account (D23).

Every step and every health probe runs `gemini` headless in a new DEIXIS-owned home under
`<data>/gemini-cli-home`, deleted when the call ends. That home holds generated user and system settings that
register no tools (`tools.core: []`), no MCP servers, no skills, hooks, agents, extensions or context files, and a
system prompt file (GEMINI_SYSTEM_MD) that replaces the CLI's own agent prompt with the step's instructions. The
person's ~/.gemini (settings, hooks, extensions, GEMINI.md) is never loaded.

The Google sign-in is the CLI's own: GOOGLE_APPLICATION_CREDENTIALS points the CLI at the person's
~/.gemini/oauth_creds.json, which the CLI reads itself. DEIXIS only checks that the file exists and never reads or
copies it. A refreshed token the CLI writes lands in the per-call home and is deleted with it.

The CLI cannot list models; the catalogue below is fixed from the model ids Gemini CLI 0.60 accepts. The CLI may still
answer with another model (no preview access, quota fallback): the per-model stats of its result name the model that
answered, and any other model is reported so the step fails with model_mismatch. Any tool event or tool call count
in the output is reported so the step fails with model_isolation_violation. The CLI has no JSON-schema mode, so the
schema reaches the model through the developer instructions (enforces_schema False) and the bounded repair applies.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import signal
import tempfile
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deixis.tools.child_env import NODE_TLS
from deixis.models.adapter import ModelStepResult
from deixis.models.cli_process import reap, spawn_options, stop_group_async, track
from deixis.domain.limits import limit_kind, safe_error, service_error_kind
from deixis.tools import tool_probe
from deixis.tools.tool_paths import child_path, command_for, find_tool

CLI = "gemini"
# Concrete ids from Gemini CLI 0.60's VALID_GEMINI_MODELS (internal, Gemma and custom-tools variants left out).
# Not a live list: the CLI has no command that lists models. Which of them a Google account may use is not known
# until a step runs; a substituted model is caught as model_mismatch.
MODELS = (
    ("gemini-2.5-pro", "Gemini 2.5 Pro"),
    ("gemini-2.5-flash", "Gemini 2.5 Flash"),
    ("gemini-3-pro-preview", "Gemini 3 Pro Preview"),
    ("gemini-3.1-pro-preview", "Gemini 3.1 Pro Preview"),
    ("gemini-3-flash-preview", "Gemini 3 Flash Preview"),
    ("gemini-3.5-flash", "Gemini 3.5 Flash"),
)

# Settings written as both the user and the system settings of the per-call home. System settings win over any other
# scope, so a system-wide /Library/Application Support/GeminiCli file is replaced, not merged.
ISOLATION_SETTINGS: dict[str, Any] = {
    "security": {"auth": {"selectedType": "oauth-personal"}, "folderTrust": {"enabled": False}},
    "tools": {"core": [], "exclude": [], "useRipgrep": False},
    "mcpServers": {},
    "useWriteTodos": False,
    "context": {"fileName": "DEIXIS-NO-CONTEXT-FILE.md", "includeDirectoryTree": False, "discoveryMaxDirs": 0,
                "memoryBoundaryMarkers": [], "includeDirectories": [], "loadMemoryFromIncludeDirectories": False},
    "skills": {"enabled": False},
    "hooksConfig": {"enabled": False},
    "hooks": {},
    "extensions": {"disabled": []},
    "experimental": {"enableAgents": False, "autoMemory": False},
    "general": {"checkpointing": {"enabled": False}, "enableAutoUpdate": False, "enableAutoUpdateNotification": False,
                "plan": {"enabled": False}},
    "privacy": {"usageStatisticsEnabled": False},
    "telemetry": {"enabled": False},
    "ide": {"enabled": False},
    "model": {"skipNextSpeakerCheck": True},
}

# Variables the CLI needs to run and reach the network. API keys and other .env settings are not passed on.
ENV_ALLOWLIST = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "TEMP", "TMP", "LANG", "TERM",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS",
    "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy",
    # A Google Workspace account names its Cloud project for Gemini Code Assist Standard.
    "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_PROJECT_ID",
    "SYSTEMROOT", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "COMSPEC", "PATHEXT",
})

NO_INPUT_TEXT = "No input provided via stdin"


@dataclass
class CliRun:
    returncode: int | None
    stdout: str
    stderr: str


Runner = Callable[[list[str], Mapping[str, str], Path, str, float], Awaitable[CliRun]]


def user_credentials(source: Mapping[str, str] | None = None) -> Path:
    """The person's own Gemini CLI sign-in file. Only its existence is checked; it is never opened by DEIXIS."""
    source = os.environ if source is None else source
    home = source.get("GEMINI_CLI_HOME") or str(Path.home())
    return Path(home) / ".gemini" / "oauth_creds.json"


def prepare_home(base: Path, system_prompt: str) -> Path:
    """A new per-call home: settings, system prompt and an empty working directory. The caller deletes it."""
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    home = Path(tempfile.mkdtemp(prefix="call-", dir=base))
    (home / ".gemini").mkdir(mode=0o700)
    (home / "workspace").mkdir(mode=0o700)
    text = json.dumps(ISOLATION_SETTINGS, indent=1)
    (home / ".gemini" / "settings.json").write_text(text, encoding="utf-8")
    (home / "system-settings.json").write_text(text, encoding="utf-8")
    (home / "system-defaults.json").write_text("{}", encoding="utf-8")
    (home / "trusted-folders.json").write_text("{}", encoding="utf-8")
    (home / "system.md").write_text(system_prompt, encoding="utf-8")
    return home


def cli_environment(home: Path, credentials: Path, source: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if source is None else source
    env = {k: v for k, v in source.items() if k in ENV_ALLOWLIST or k.startswith("LC_")}
    env.update({
        "GEMINI_CLI_HOME": str(home),
        "GEMINI_CLI_SYSTEM_SETTINGS_PATH": str(home / "system-settings.json"),
        "GEMINI_CLI_SYSTEM_DEFAULTS_PATH": str(home / "system-defaults.json"),
        "GEMINI_CLI_TRUSTED_FOLDERS_PATH": str(home / "trusted-folders.json"),
        "GEMINI_SYSTEM_MD": str(home / "system.md"),
        "GOOGLE_APPLICATION_CREDENTIALS": str(credentials),
        # Without a sign-in, headless mode stops with an authentication error instead of opening a browser.
        "NO_BROWSER": "true",
        # The CLI is a node script: node's folder must be on PATH when DEIXIS started with a short one.
        "PATH": child_path(find_tool(CLI), env.get("PATH", "")),
        **NODE_TLS,  # the system certificates, so a network that inspects TLS does not stop the CLI (F1)
    })
    return env


def cli_argv(cli: str | list[str], model: str) -> list[str]:
    # The message goes on stdin; `-p ""` selects headless mode without adding text to it. `-e none` loads no extension.
    return [*([cli] if isinstance(cli, str) else cli), "-m", model, "-o", "stream-json", "-e", "none", "--approval-mode", "default", "-p", ""]


def auth_failure(stderr: str) -> tuple[str, str] | None:
    """(reason_code, reason) when the CLI could not use the Google sign-in, else None."""
    if "IneligibleTierError" in stderr:
        code = re.search(r"reasonCode:\s*'([A-Z_]+)'", stderr)
        message = re.search(r"IneligibleTierError:\s*([^\n]+)", stderr)
        detail = message.group(1).strip() if message else "Google refused this account for Gemini CLI"
        return "auth_failed", f"Google refused this account: {detail[:240]}" + (f" ({code.group(1)})" if code else "")
    if re.search(r"FatalAuthenticationError|Manual authorization is required|Error authenticating", stderr):
        return "auth_failed", "Not signed in to Gemini CLI"
    return None


def parse_events(stdout: str) -> list[dict[str, Any]]:
    events = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


async def run_cli(argv: list[str], env: Mapping[str, str], cwd: Path, stdin: str, timeout: float,
                  active: set[asyncio.subprocess.Process] | None = None) -> CliRun:
    proc = await asyncio.create_subprocess_exec(*argv, cwd=str(cwd), env=dict(env), stdin=asyncio.subprocess.PIPE,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                **spawn_options())
    track(proc)
    if active is not None:
        active.add(proc)
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin.encode("utf-8")), timeout)
    except BaseException:
        # A timeout or a cancelled step: stop the group (the CLI relaunches itself as a child) and wait, bounded.
        await stop_group_async(proc)
        await reap(proc)
        raise
    finally:
        if active is not None:
            active.discard(proc)
        await stop_group_async(proc)  # anything the CLI started and left running
    return CliRun(proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"))


class GeminiCliAdapter:
    connection = "gemini_cli"
    enforces_schema = False

    def __init__(self, home: Path, turn_timeout: float = 300.0, runner: Runner | None = None,
                 credentials: Path | None = None):
        self.home = home
        self.turn_timeout = turn_timeout
        self._runner = runner
        self._credentials = credentials
        self._health: tuple[float, dict[str, Any]] | None = None
        self._checks = 0  # health checks started, to order their answers
        self._lock = asyncio.Lock()
        self._active: set[asyncio.subprocess.Process] = set()

    def credentials(self) -> Path:
        return self._credentials or user_credentials()

    async def _run(self, argv: list[str], system_prompt: str, stdin: str, timeout: float) -> CliRun:
        home = prepare_home(self.home, system_prompt)
        try:
            env = cli_environment(home, self.credentials())
            if self._runner is not None:
                return await self._runner(argv, env, home / "workspace", stdin, timeout)
            return await run_cli(argv, env, home / "workspace", stdin, timeout, self._active)
        finally:
            shutil.rmtree(home, ignore_errors=True)

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
        found = command_for(CLI, await asyncio.to_thread(find_tool, CLI))
        cli = found.argv
        status: dict[str, Any] = {
            "connection": self.connection, "installed": bool(found.found), "ready": False, "catalogue": "fixed",
            # No `isolation` counts: the CLI cannot list the tools or context files it loaded, so none are claimed.
            # The settings register none, and run_step refuses an answer with any tool event.
            "models": [{"id": model, "display_name": name, "is_default": False, "description": "",
                        "default_reasoning_effort": None, "reasoning_efforts": []} for model, name in MODELS],
        }
        if not found.found:
            status["reason"] = "Gemini CLI not found"
            return status
        if found.problem:
            status["reason_code"], status["reason"] = "unsupported_install", found.problem
            return status
        async with self._lock:
            # The version is shown only; a slow start (over 20 s measured on 15 Oct) must not fail the check. The probe
            # keeps that longer limit but is bounded in output like every tool probe (A3b).
            home = prepare_home(self.home, "")
            try:
                version = await tool_probe.probe([*cli, "--version"], 60, cli_environment(home, self.credentials()))
            finally:
                shutil.rmtree(home, ignore_errors=True)
            status["cli_version"] = version.stdout.strip() or None
            if not self.credentials().is_file():
                status.update(signed_in=False, reason_code="auth_failed", reason="Not signed in to Gemini CLI")
                return status
            # An empty prompt makes the CLI sign in and set up the account, then stop before any model request.
            try:
                probe = await self._run([*cli, "-o", "stream-json", "-e", "none", "-p", ""], "", "", 60)
            except (OSError, TimeoutError) as exc:
                # TimeoutError carries no message; a first start that sets the CLI up can take over a minute.
                status["reason"] = ("Gemini CLI did not answer within 60 s" if isinstance(exc, TimeoutError)
                                    else f"Gemini CLI error: {safe_error(str(exc))[:200]}")
                status["reason_code"] = service_error_kind(exc=exc)
                return status
        failure = auth_failure(probe.stderr)
        if failure:
            status["signed_in"] = "Not signed in" not in failure[1]
            status["reason_code"], status["reason"] = failure
        elif NO_INPUT_TEXT in probe.stderr:
            status.update(signed_in=True, ready=True, account_type="google")
        else:
            status["reason"] = f"Gemini CLI check ended unexpectedly (exit {probe.returncode})"
            status["reason_code"] = limit_kind(text=probe.stderr) or "unknown"
        return status

    async def run_step(self, base: str, developer: str, message: str, output_schema: dict[str, Any],
                       requested_model: str | None, reasoning_effort: str | None = None) -> ModelStepResult:
        found = command_for(CLI, await asyncio.to_thread(find_tool, CLI))
        cli = found.argv
        if not cli or not requested_model:
            return ModelStepResult("unavailable", error=(found.problem or "Gemini CLI not found") if not cli else "no model requested",
                                   delivery_class="before_send")
        if not self.credentials().is_file():
            return ModelStepResult("unavailable", error="Not signed in to Gemini CLI", delivery_class="before_send",
                                   error_kind="auth_failed")
        # The schema reaches the model in the developer text (the appendix a non-enforcing adapter is given, D86).
        system = f"{base}\n\n{developer}\n\nReturn only a JSON object."
        try:
            run = await self._run(cli_argv(cli, requested_model), system, message, self.turn_timeout)
        except TimeoutError:
            return ModelStepResult("failed", error="Gemini CLI turn timed out", delivery_class="after_send_unknown")
        except OSError as exc:
            return ModelStepResult("unavailable", error=safe_error(str(exc))[:300], delivery_class="before_send")
        return self.result_of(run, requested_model)

    @staticmethod
    def result_of(run: CliRun, requested_model: str) -> ModelStepResult:
        events = parse_events(run.stdout)
        tools = [str(e.get("tool_name") or e.get("tool_id") or e.get("type")) for e in events
                 if e.get("type") in ("tool_use", "tool_result")]
        result = next((e for e in reversed(events) if e.get("type") == "result"), None)
        stats = (result or {}).get("stats") or {}
        if stats.get("tool_calls") and not tools:
            tools = [f"tool_calls:{stats['tool_calls']}"]
        session = next((e.get("session_id") for e in events if e.get("type") == "init"), None)
        text = "".join(str(e.get("content") or "") for e in events
                       if e.get("type") == "message" and e.get("role") == "assistant")
        answered = sorted((stats.get("models") or {}).keys())
        others = [m for m in answered if m != requested_model]
        resolved = others[0] if others else (requested_model if answered else None)
        usage = {k: stats[k] for k in ("total_tokens", "input_tokens", "output_tokens", "cached", "models") if k in stats} or None
        common: dict[str, Any] = {"resolved_model": resolved, "external_thread_id": session, "token_usage": usage,
                                  "tool_item_types": tools}
        if tools:
            return ModelStepResult("isolation_violation", raw_text=text or None, error="Gemini CLI reported a tool event",
                                   delivery_class="after_send_unknown", **common)
        errors = [str(e.get("message") or "") for e in events if e.get("type") == "error" and e.get("severity") == "error"]
        # Completed only when the closing event says success, no error event came and the process itself exited 0.
        if result is None or result.get("status") != "success" or errors or run.returncode != 0:
            failure = auth_failure(run.stderr) if result is None else None
            # A sign-in refusal comes before any model request: with no answer and no model stats nothing was sent,
            # even if the CLI already wrote its `init` event.
            if failure and not text and not answered:
                return ModelStepResult("unavailable", error=failure[1], error_kind=failure[0],
                                       delivery_class="before_send", **common)
            detail = "; ".join(errors) or (run.stderr.strip().splitlines() or [f"exit {run.returncode}"])[-1]
            return ModelStepResult("failed", raw_text=text or None, error=safe_error(detail)[:300],
                                   delivery_class="after_send_unknown",
                                   error_kind=service_error_kind(text=detail, surface="model"), **common)
        if not text:
            return ModelStepResult("failed", error="empty answer", delivery_class="after_send_unknown", **common)
        return ModelStepResult("completed", raw_text=text, **common)

    async def cancel(self) -> bool:
        active = tuple(self._active)
        for proc in active:
            await stop_group_async(proc, signal.SIGTERM)
        return bool(active)

    async def close(self) -> None:
        await self.cancel()
