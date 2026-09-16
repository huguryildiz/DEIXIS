import asyncio
from types import SimpleNamespace

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from deixis.models import claude


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
    monkeypatch.setattr(claude.shutil, "which", lambda name: "/SYNTHETIC/bin/claude")
    monkeypatch.setattr(claude.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="2.1.270 (Claude Code)"))


def test_health_reads_account_scoped_models_and_efforts_from_sdk(monkeypatch, tmp_path):
    prepare(monkeypatch)
    status = asyncio.run(claude.ClaudeCodeAdapter(tmp_path).health(refresh=True))
    assert (status["ready"], status["signed_in"], status["plan_type"]) == (True, True, "Claude Max")
    assert status["isolation"] == {"instruction_sources": 0, "live_mcp_servers": []}
    assert status["models"] == [{
        "id": "opus", "display_name": "Opus", "resolved_model": "claude-opus-5", "is_default": False,
        "description": "Current Opus", "default_reasoning_effort": None,
        "reasoning_efforts": [{"id": "low", "description": ""}, {"id": "high", "description": ""}, {"id": "max", "description": ""}],
    }]
    options = FakeClient.options[0]
    assert options.tools == [] and options.setting_sources == [] and options.skills == [] and options.strict_mcp_config is True


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


def test_structured_output_block_is_not_reported_as_external_tool_use(monkeypatch, tmp_path):
    prepare(monkeypatch)

    class StructuredClient(FakeClient):
        async def receive_response(self):
            yield AssistantMessage([ToolUseBlock("internal-1", "StructuredOutput", {"claims": []})], "claude-opus-5")
            yield ResultMessage("success", 1, 1, False, 1, "session-1", structured_output={"claims": []})

    monkeypatch.setattr(claude, "ClaudeSDKClient", StructuredClient)
    result = asyncio.run(claude.ClaudeCodeAdapter(tmp_path).run_step(
        "BASE", "DEVELOPER", "MESSAGE", {"type": "object"}, "opus", "max",
    ))
    assert result.status == "completed" and result.raw_text == '{"claims": []}'
    assert result.tool_item_types == []


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
