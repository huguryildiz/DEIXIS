import asyncio

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from deixis.tools import tool_probe
from deixis.models import claude


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

    def __init__(self, options):
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
    monkeypatch.setattr(claude, "find_tool", lambda name: "/SYNTHETIC/bin/claude")
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
    assert (options.model, options.effort, options.fallback_model, options.max_turns) == ("opus", "max", None, 1)
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
