import asyncio
import json

import pytest
from claude_agent_sdk import (AssistantMessage, ClaudeSDKError, ResultMessage, ServerToolUseBlock, TextBlock,
                              ToolResultBlock, ToolUseBlock)

from claude_agent_sdk._internal.message_parser import parse_message

from deixis.runtime.config import Settings
from deixis.domain import skill
from deixis.storage import db
from deixis.tools import tool_probe
from deixis.models import claude
from deixis.workflow.run.flow import FlowDeps, ResearchFlow
from deixis.workflow.run.store import Store
from fakes import parse_step_input, valid_response
import sys

EXE = ".exe" if sys.platform == "win32" else ""  # on Windows a fake CLI path must be a native program (tool_paths)


PROBED_CATALOGUE = {
    "models": [
        {"value": "default", "resolvedModel": "claude-opus-5[1m]"},
        {"value": "opus[1m]", "resolvedModel": "claude-opus-5[1m]"},
        {"value": "claude-fable-5-1[1m]", "resolvedModel": "claude-fable-5-1"},
        {"value": "sonnet", "resolvedModel": "claude-sonnet-5"},
        {"value": "haiku", "resolvedModel": "claude-haiku-4-5-20251001"},
    ],
}


class FakeClient:
    info = {
        "account": {"subscriptionType": "Claude Max"},
        "models": [{
            "value": "opus",
            "resolvedModel": "claude-opus-5",
            "displayName": "Opus",
            "description": "Current Opus",
            "supportedEffortLevels": ["low", "high", "max"],
        }],
    }
    messages = []
    options = []

    def __init__(self, options, transport=None):  # transport: the Windows job transport (P10 W2)
        self.options.append(options)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def get_server_info(self):
        return self.info

    async def get_mcp_status(self):
        return {"mcpServers": []}

    async def query(self, message):
        self.messages.append(message)

    async def receive_response(self):
        yield AssistantMessage([TextBlock('{"ignored": true}')], "claude-opus-5", usage={"input_tokens": 4})
        yield ResultMessage("success", 1, 1, False, 1, "session-1", structured_output={"claims": []})

    async def interrupt(self):
        pass

    async def disconnect(self):
        pass


def prepare(monkeypatch):
    FakeClient.messages = []
    FakeClient.options = []
    monkeypatch.setattr(claude, "ClaudeSDKClient", FakeClient)
    monkeypatch.setattr(claude, "find_tool", lambda name: "/SYNTHETIC/bin/claude" + EXE)
    async def version(argv, timeout=None, env=None):
        return tool_probe.Probe(0, "2.1.270 (Claude Code)")

    monkeypatch.setattr(claude, "probe", version)


def test_run_step_uses_requested_selector_effort_and_structured_output(monkeypatch, tmp_path):
    prepare(monkeypatch)
    result = asyncio.run(claude.ClaudeCodeAdapter(tmp_path).run_step(
        "BASE", "DEVELOPER", "MESSAGE", {"type": "object"}, "opus", "max",
    ))
    assert (result.status, result.raw_text, result.resolved_model, result.external_thread_id) == (
        "completed", '{"claims": []}', "claude-opus-5", "session-1",
    )
    assert result.requested_model_verified is True and result.tool_item_types == []
    assert FakeClient.messages == ["MESSAGE"]
    options = FakeClient.options[0]
    assert (options.model, options.effort, options.fallback_model, options.max_turns) == ("opus", "max", None, 3)
    assert options.output_format == {"type": "json_schema", "schema": {"type": "object"}}
    assert options.system_prompt == "BASE\n\nDEVELOPER"


def test_other_tool_use_is_still_reported_with_structured_output(monkeypatch, tmp_path):
    prepare(monkeypatch)

    class ToolClient(FakeClient):
        async def receive_response(self):
            yield AssistantMessage([
                ToolUseBlock("internal-1", "StructuredOutput", {"claims": []}),
                ToolUseBlock("external-1", "Read", {"file_path": "/tmp/example"}),
            ], "claude-opus-5")
            yield ResultMessage("success", 1, 1, False, 1, "session-1", structured_output={"claims": []})

    monkeypatch.setattr(claude, "ClaudeSDKClient", ToolClient)
    result = asyncio.run(claude.ClaudeCodeAdapter(tmp_path).run_step(
        "BASE", "DEVELOPER", "MESSAGE", {"type": "object"}, "opus", "max",
    ))
    assert result.tool_item_types == ["Read"]


def run_with(monkeypatch, tmp_path, messages):
    prepare(monkeypatch)

    class ScriptClient(FakeClient):
        async def receive_response(self):
            for message in messages:
                yield message

    monkeypatch.setattr(claude, "ClaudeSDKClient", ScriptClient)
    return asyncio.run(claude.ClaudeCodeAdapter(tmp_path).run_step(
        "BASE", "DEVELOPER", "MESSAGE", {"type": "object"}, "opus", "max",
    ))


def test_structured_output_retry_within_the_turn_limit_completes(monkeypatch, tmp_path):
    # The CLI rejected the first StructuredOutput call against the schema; the model's second call passed.
    result = run_with(monkeypatch, tmp_path, [
        AssistantMessage([ToolUseBlock("so-1", "StructuredOutput", {"claim": []})], "claude-opus-5"),
        AssistantMessage([ToolUseBlock("so-2", "StructuredOutput", {"claims": []})], "claude-opus-5"),
        ResultMessage("success", 1, 1, False, 2, "session-1", structured_output={"claims": []}),
    ])
    assert (result.status, result.raw_text, result.tool_item_types) == ("completed", '{"claims": []}', [])
    assert result.transport is None


def test_turn_limit_with_only_structured_output_goes_to_validation_not_isolation(monkeypatch, tmp_path):
    # pilot3 battery_soh: no StructuredOutput call passed the CLI's schema check before the turn limit.
    result = run_with(monkeypatch, tmp_path, [
        AssistantMessage([ToolUseBlock("so-1", "StructuredOutput", {"claim": []})], "claude-opus-5"),
        AssistantMessage([ToolUseBlock("so-2", "StructuredOutput", {"claim": [1]})], "claude-opus-5"),
        ResultMessage("error_max_turns", 1, 1, True, 3, "session-1", errors=["Reached maximum number of turns (3)"]),
    ])
    # The last attempt is handed on for DEIXIS's own validation and bounded repair, with the CLI's verdict recorded.
    assert (result.status, result.raw_text, result.tool_item_types) == ("completed", '{"claim": [1]}', [])
    assert result.error == "Reached maximum number of turns (3)" and result.requested_model_verified is True
    assert result.transport == {"structured_output": {"rejected_by_cli": "error_max_turns", "attempts": 2, "turns": 3,
                                                      "error": "Reached maximum number of turns (3)"}}


def test_retry_limit_with_only_structured_output_goes_to_validation(monkeypatch, tmp_path):
    result = run_with(monkeypatch, tmp_path, [
        AssistantMessage([ToolUseBlock("so-1", "StructuredOutput", {"claim": []})], "claude-opus-5"),
        AssistantMessage([ToolResultBlock("so-1", "Output does not match required schema", True)], "claude-opus-5"),
        ResultMessage("error_max_structured_output_retries", 1, 1, True, 2, "session-1",
                      errors=["Failed to provide valid structured output after maximum retries"]),
    ])
    assert (result.status, result.raw_text, result.tool_item_types) == ("completed", '{"claim": []}', [])
    assert result.transport["structured_output"]["rejected_by_cli"] == "error_max_structured_output_retries"


@pytest.mark.parametrize("channel", ["assistant_error", "api_error_status"])
def test_an_api_error_after_structured_output_stays_a_service_failure(monkeypatch, tmp_path, channel):
    attempt = ToolUseBlock("so-1", "StructuredOutput", {"claim": []})
    messages = [AssistantMessage([attempt], "claude-opus-5", error="billing_error" if channel == "assistant_error" else None),
                ResultMessage("error_max_turns", 1, 1, True, 2, "session-1", errors=["Reached maximum number of turns (3)"],
                              api_error_status=529 if channel == "api_error_status" else None)]
    result = run_with(monkeypatch, tmp_path, messages)
    assert (result.status, result.tool_item_types, result.transport) == ("failed", [], None)
    if channel == "assistant_error":
        assert result.error_kind == "quota_exhausted"
    else:
        assert (result.error_kind, result.http_status) == ("service_error", 529)


@pytest.mark.parametrize("other", [ToolUseBlock("external-1", "Bash", {"command": "ls"}),
                                   ServerToolUseBlock("server-1", "web_search", {"query": "x"}),
                                   ToolResultBlock("unknown-1", "result of a call nobody asked for")])
@pytest.mark.parametrize("ending", ["turn_limit", "structured_output"])
def test_any_other_tool_action_is_still_an_isolation_violation(monkeypatch, tmp_path, other, ending):
    final = (ResultMessage("error_max_turns", 1, 1, True, 3, "session-1", errors=["Reached maximum number of turns (3)"])
             if ending == "turn_limit" else
             ResultMessage("success", 1, 1, False, 2, "session-1", structured_output={"claims": []}))
    result = run_with(monkeypatch, tmp_path, [
        AssistantMessage([ToolUseBlock("so-1", "StructuredOutput", {"claim": []}), other], "claude-opus-5"), final,
    ])
    assert result.status == ("failed" if ending == "turn_limit" else "completed")
    assert result.tool_item_types == [getattr(other, "name", None) or "ToolResultBlock"]


# Messages as the CLI writes them, parsed by the SDK's own parser (Sol round 2).
CARRIER = {"type": "assistant", "message": {"model": "claude-opus-5", "content": [
    {"type": "tool_use", "id": "so-1", "name": "StructuredOutput", "input": {"claims": []}}]}}
CARRIER_RESULT = {"type": "user", "message": {"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": "so-1", "content": "Output does not match required schema", "is_error": True}]}}
USER_BASH = {"type": "user", "message": {"role": "user", "content": [
    {"type": "tool_use", "id": "bash-1", "name": "Bash", "input": {"command": "ls"}}]}}
USER_UNKNOWN_RESULT = {"type": "user", "message": {"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": "unknown-1", "content": "a result for a call nobody made"}]}}
ENDINGS = {
    "success": {"type": "result", "subtype": "success", "duration_ms": 1, "duration_api_ms": 1, "is_error": False,
                "num_turns": 2, "session_id": "session-1", "structured_output": {"claims": []}},
    "max_turns": {"type": "result", "subtype": "error_max_turns", "duration_ms": 1, "duration_api_ms": 1, "is_error": True,
                  "num_turns": 3, "session_id": "session-1", "errors": ["Reached maximum number of turns (3)"]},
}


def run_parsed(monkeypatch, tmp_path, raw, ending):
    prepare(monkeypatch)
    messages = [parse_message(m) for m in raw] + ([parse_message(ENDINGS[ending])] if ending in ENDINGS else [])

    class ParsedClient(FakeClient):
        async def receive_response(self):
            for message in messages:
                yield message
            if ending == "timeout":
                await asyncio.sleep(5)
            if ending in ("timeout", "sdk_error"):
                raise ClaudeSDKError("CLI stopped")

    monkeypatch.setattr(claude, "ClaudeSDKClient", ParsedClient)
    return asyncio.run(claude.ClaudeCodeAdapter(tmp_path, turn_timeout=0.05).run_step(
        "BASE", "DEVELOPER", "MESSAGE", {"type": "object"}, "opus", "max",
    ))


ALL_ENDINGS = ["success", "max_turns", "timeout", "sdk_error"]


@pytest.mark.parametrize("ending", ALL_ENDINGS)
def test_the_structured_output_result_in_a_user_message_passes(monkeypatch, tmp_path, ending):
    result = run_parsed(monkeypatch, tmp_path, [CARRIER, CARRIER_RESULT], ending)
    assert result.tool_item_types == []
    assert result.status == ("completed" if ending in ("success", "max_turns") else "failed")


@pytest.mark.parametrize("ending", ALL_ENDINGS)
@pytest.mark.parametrize("foreign, reported", [(USER_BASH, "Bash"), (USER_UNKNOWN_RESULT, "ToolResultBlock")])
def test_a_tool_block_in_a_user_message_is_an_isolation_violation(monkeypatch, tmp_path, ending, foreign, reported):
    result = run_parsed(monkeypatch, tmp_path, [CARRIER, CARRIER_RESULT, foreign], ending)
    assert result.tool_item_types == [reported]
    assert result.status == ("completed" if ending == "success" else "failed")  # flow fails any listed tool action


@pytest.mark.parametrize("failure", ["timeout", "sdk_error"])
def test_structured_output_then_a_broken_session_is_a_failure_not_an_isolation_violation(monkeypatch, tmp_path, failure):
    prepare(monkeypatch)

    class BrokenClient(FakeClient):
        async def receive_response(self):
            yield AssistantMessage([ToolUseBlock("so-1", "StructuredOutput", {"claim": []})], "claude-opus-5")
            if failure == "timeout":
                await asyncio.sleep(5)
            raise ClaudeSDKError("CLI stopped")

    monkeypatch.setattr(claude, "ClaudeSDKClient", BrokenClient)
    result = asyncio.run(claude.ClaudeCodeAdapter(tmp_path, turn_timeout=0.05).run_step(
        "BASE", "DEVELOPER", "MESSAGE", {"type": "object"}, "opus", "max",
    ))
    assert (result.status, result.tool_item_types, result.delivery_class) == ("failed", [], "after_send_unknown")
    assert result.error == ("Claude Code turn timed out" if failure == "timeout" else "CLI stopped")


@pytest.mark.parametrize("attempt", ["valid", "invalid"])
def test_a_recovered_attempt_reaches_validation_and_repair_stays_bounded(monkeypatch, tmp_path, attempt):
    # Through flow._model_step with the real adapter over a fake CLI: every session ends at the turn limit with only
    # StructuredOutput calls, and its last attempt is judged by DEIXIS's own validation.
    prepare(monkeypatch)
    sent = []

    class LimitClient(FakeClient):
        async def query(self, message):
            sent.append(parse_step_input(message))

        async def receive_response(self):
            draft = json.loads(valid_response(sent[-1]))
            if attempt == "invalid":
                draft.pop("claims")
            yield AssistantMessage([ToolUseBlock("so-1", "StructuredOutput", draft)], "claude-opus-5")
            yield ResultMessage("error_max_turns", 1, 1, True, 3, f"session-{len(sent)}",
                                errors=["Reached maximum number of turns (3)"])

    monkeypatch.setattr(claude, "ClaudeSDKClient", LimitClient)
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC question?", "attached", "quick", [], "claude", "opus", "en")
    sid = store.create_upload_source("SYNTHETIC source")
    pids = [store._insert_passage(sid, None, "abstract", None, None, "synthetic_fixture", None, None, text)
            for text in ("SYNTHETIC first passage about release scheduling.",
                         "SYNTHETIC second passage about a relay budget.")]
    flow = ResearchFlow(FlowDeps(Settings(data_dir=tmp_path / "data", port=8872), store,
                                 {"claude": claude.ClaudeCodeAdapter(tmp_path / "claude")}, skill.load_skill_package(), None))
    run = store.create_run(rid, "answer", {"max_model_calls": 4, "max_provider_requests": 0}, None)
    store.update_run(run["id"], status="running")
    try:
        result = asyncio.run(flow._model_step(store.run(run["id"]), store.scope(rid), "synthetic:answer", "grounded_answer",
                                              source_ids=[sid], passage_rows=[store.passage(pid) for pid in pids]))
        sessions = [dict(r) for r in store.conn.execute(
            "SELECT status, tool_item_types_json, validation_json FROM model_sessions ORDER BY rowid")]
        validations = [json.loads(s["validation_json"]) for s in sessions]
        assert all(v["transport"] == {"structured_output": {"rejected_by_cli": "error_max_turns", "attempts": 1, "turns": 3,
                                                            "error": "Reached maximum number of turns (3)"}}
                   for v in validations)
        assert all(json.loads(s["tool_item_types_json"]) == [] for s in sessions)
        assert store.run(run["id"])["usage"]["model_calls"] == len(sent) == len(sessions)
        step = store.conn.execute("SELECT status, error_code FROM run_steps WHERE operation_key = 'synthetic:answer'").fetchone()
        if attempt == "valid":  # accepted without another call
            assert len(sent) == 1 and not result.get("invalid") and validations[0]["ok"] is True
            assert tuple(step) == ("succeeded", None)
        else:  # rejected with the schema's own issues, repaired once, then stored as an unverified draft
            assert len(sent) == 2 and result["invalid"] is True
            assert all(v["ok"] is False and any(i["code"] == "schema_invalid" for i in v["issues"]) for v in validations)
            assert tuple(step) == ("failed", "invalid_model_output")
    finally:
        conn.close()


@pytest.mark.parametrize("requested, catalogue, answered, resolved, verified", [
    ("default", PROBED_CATALOGUE, ["claude-opus-5"], "claude-opus-5", True),
    ("opus[1m]", PROBED_CATALOGUE, ["claude-opus-5"], "claude-opus-5", True),
])
def test_model_verification_uses_session_catalogue_and_response_identity(
    monkeypatch, tmp_path, requested, catalogue, answered, resolved, verified,
):
    prepare(monkeypatch)

    class ModelClient(FakeClient):
        info = catalogue

        async def receive_response(self):
            for model in answered:
                yield AssistantMessage([TextBlock('{"ignored": true}')], model)
            yield ResultMessage("success", 1, 1, False, 1, "session-1", structured_output={"claims": []})

    monkeypatch.setattr(claude, "ClaudeSDKClient", ModelClient)
    adapter = claude.ClaudeCodeAdapter(tmp_path)
    # A stale health catalogue must not authorize a different session model.
    adapter._health = (claude.time.monotonic(), {"models": [{"id": requested, "resolved_model": "claude-sonnet-5"}]})
    result = asyncio.run(adapter.run_step("BASE", "DEVELOPER", "MESSAGE", {}, requested))
    assert (result.status, result.raw_text, result.resolved_model) == ("completed", '{"claims": []}', resolved)
    assert result.requested_model_verified is verified
    assert FakeClient.options[0].model == requested and FakeClient.messages == ["MESSAGE"]
    assert adapter._active == set()


def test_claude_code_telemetry_is_switched_off_for_every_launch(monkeypatch, tmp_path):
    prepare(monkeypatch)
    probed = []

    async def version(argv, timeout=None, env=None):
        probed.append(env)
        return tool_probe.Probe(0, "2.1.270 (Claude Code)")

    monkeypatch.setattr(claude, "probe", version)
    adapter = claude.ClaudeCodeAdapter(tmp_path)
    asyncio.run(adapter.health(refresh=True))
    asyncio.run(adapter.run_step("BASE", "DEVELOPER", "MESSAGE", {"type": "object"}, "opus", "max"))
    assert len(FakeClient.options) == 2 and probed
    for env in [o.env for o in FakeClient.options] + probed:
        for name in ("DISABLE_TELEMETRY", "DISABLE_ERROR_REPORTING", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"):
            assert env[name] == "1"


def test_the_windows_job_transport_fails_closed_on_an_unchecked_sdk_and_on_a_cli_outside_its_job(monkeypatch):
    # P10 W2 (Sol W2/W3 round 2): the hook is trusted only for the SDK versions it was checked against, and each started
    # CLI must be one the hook put in a job; anything else starts nothing or is stopped, and counts as never sent.
    started: list[str] = []

    async def fake_connect(self):
        started.append("cli")
        self._process = type("Proc", (), {"pid": 424242, "returncode": None})()

    stopped: list[int] = []
    monkeypatch.setattr(claude.subprocess_cli.SubprocessCLITransport, "connect", fake_connect)
    monkeypatch.setattr(claude.cli_process, "stop_group", lambda proc, *a: stopped.append(proc.pid))
    monkeypatch.setattr(claude, "JOBS_ON", True)
    transport = claude.JobTransport(prompt="", options=claude.ClaudeAgentOptions())

    monkeypatch.setattr(claude, "JOB_HOOK_SDK", frozenset())
    with pytest.raises(claude.NotInJob):
        asyncio.run(transport.connect())
    assert started == []  # refused before anything ran

    monkeypatch.setattr(claude, "JOB_HOOK_SDK", frozenset({claude.claude_agent_sdk.__version__}))
    with pytest.raises(claude.NotInJob) as refused:
        asyncio.run(transport.connect())
    assert started == ["cli"] and stopped == [424242] and claude._not_started(refused.value)
