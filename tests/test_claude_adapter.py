import asyncio
from types import SimpleNamespace

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

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


@pytest.mark.parametrize("requested, catalogue, answered, resolved, verified", [
    ("default", PROBED_CATALOGUE, ["claude-opus-5"], "claude-opus-5", True),
    ("opus[1m]", PROBED_CATALOGUE, ["claude-opus-5"], "claude-opus-5", True),
    ("claude-fable-5-1[1m]", PROBED_CATALOGUE, ["claude-fable-5-1"], "claude-fable-5-1", True),
    ("sonnet", PROBED_CATALOGUE, ["claude-sonnet-5"], "claude-sonnet-5", True),
    ("sonnet", PROBED_CATALOGUE, ["claude-haiku-4-5-20251001"], "claude-haiku-4-5-20251001", False),
    ("claude-fable-5-1[1m]", PROBED_CATALOGUE, ["claude-fable-5-1[1m]"], "claude-fable-5-1[1m]", True),
    ("default", PROBED_CATALOGUE, ["claude-opus-5", "claude-sonnet-5"], "claude-sonnet-5", False),
    ("default", PROBED_CATALOGUE, ["claude-sonnet-5", "claude-opus-5"], "claude-sonnet-5", False),
    ("default", PROBED_CATALOGUE, [], None, False),
    ("default", PROBED_CATALOGUE, [None], None, False),
    ("opus", FakeClient.info, ["claude-opus-5"], "claude-opus-5", True),
    ("opus", FakeClient.info, ["claude-sonnet-5"], "claude-sonnet-5", False),
    ("default", {"models": [{"value": "default", "resolvedModel": "claude-opus-5"}]},
     ["claude-opus-5"], "claude-opus-5", True),
    ("claude-opus-5", None, ["claude-opus-5"], "claude-opus-5", True),
    ("claude-opus-5", FakeClient.info, ["claude-sonnet-5"], "claude-sonnet-5", False),
    ("opus", None, ["claude-opus-5"], "claude-opus-5", False),
    ("opus", {"models": [{"value": "opus"}]}, ["claude-opus-5"], "claude-opus-5", False),
    ("opus", FakeClient.info, [], None, False),
    ("claude-opus-5", FakeClient.info, [], None, False),
    ("opus", FakeClient.info, ["claude-sonnet-5", "claude-opus-5"], "claude-sonnet-5", False),
    ("claude-opus-5", FakeClient.info, ["claude-opus-5", "claude-sonnet-5"], "claude-sonnet-5", False),
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


@pytest.mark.parametrize("errors, message, subtype, expected_error", [
    (["authentication_failed", "Not signed in"], "ignored", "error", "authentication_failed; Not signed in"),
    (None, "quota exceeded", "error", "quota exceeded"),
    ([], None, "error_max_turns", "error_max_turns"),
])
def test_error_result_preserves_failure_and_does_not_verify_an_unreported_model(
    monkeypatch, tmp_path, errors, message, subtype, expected_error,
):
    prepare(monkeypatch)

    class ErrorClient(FakeClient):
        async def receive_response(self):
            yield ResultMessage(subtype, 1, 1, True, 1, "session-error", result=message,
                                usage={"input_tokens": 4}, errors=errors)

    monkeypatch.setattr(claude, "ClaudeSDKClient", ErrorClient)
    adapter = claude.ClaudeCodeAdapter(tmp_path)
    result = asyncio.run(adapter.run_step("BASE", "DEVELOPER", "MESSAGE", {}, "opus"))
    assert (result.status, result.error, result.delivery_class) == ("failed", expected_error, "after_send_unknown")
    assert result.external_thread_id == "session-error" and result.token_usage == {"input_tokens": 4}
    assert result.raw_text == message and result.resolved_model is None
    assert result.requested_model_verified is False and adapter._active == set()


@pytest.mark.parametrize("answered, verified", [(None, False), ("claude-opus-5", True), ("claude-sonnet-5", False)])
def test_timeout_preserves_observed_model_and_cleans_up_client(monkeypatch, tmp_path, answered, verified):
    prepare(monkeypatch)

    class TimeoutClient(FakeClient):
        async def receive_response(self):
            if answered:
                yield AssistantMessage([TextBlock("partial")], answered, usage={"input_tokens": 4})
            await asyncio.Event().wait()

    monkeypatch.setattr(claude, "ClaudeSDKClient", TimeoutClient)
    adapter = claude.ClaudeCodeAdapter(tmp_path, turn_timeout=0.01)
    result = asyncio.run(adapter.run_step("BASE", "DEVELOPER", "MESSAGE", {}, "opus"))
    assert (result.status, result.error, result.delivery_class) == ("failed", "Claude Code turn timed out", "after_send_unknown")
    assert result.resolved_model == answered and result.requested_model_verified is verified
    assert result.token_usage == ({"input_tokens": 4} if answered else None)
    assert adapter._active == set()


@pytest.mark.parametrize("error", [claude.ClaudeSDKError("SYNTHETIC SDK failure"), OSError("SYNTHETIC process failure")])
def test_sdk_or_process_failure_is_not_model_verification(monkeypatch, tmp_path, error):
    prepare(monkeypatch)

    class FailedClient(FakeClient):
        async def query(self, message):
            raise error

    monkeypatch.setattr(claude, "ClaudeSDKClient", FailedClient)
    adapter = claude.ClaudeCodeAdapter(tmp_path)
    result = asyncio.run(adapter.run_step("BASE", "DEVELOPER", "MESSAGE", {}, "opus"))
    assert (result.status, result.error, result.delivery_class) == ("failed", str(error), "after_send_unknown")
    assert result.resolved_model is None and result.requested_model_verified is False
    assert adapter._active == set()


def test_missing_cli_is_unavailable_without_starting_a_client(monkeypatch, tmp_path):
    prepare(monkeypatch)
    monkeypatch.setattr(claude.shutil, "which", lambda name: None)
    adapter = claude.ClaudeCodeAdapter(tmp_path)
    status = asyncio.run(adapter.health(refresh=True))
    result = asyncio.run(adapter.run_step("BASE", "DEVELOPER", "MESSAGE", {}, "opus"))
    assert (status["installed"], status["ready"], status["reason"]) == (False, False, "Claude Code CLI not found")
    assert (result.status, result.error, result.delivery_class) == ("unavailable", "Claude Code CLI not found", "before_send")
    assert result.requested_model_verified is False
    assert FakeClient.options == [] and FakeClient.messages == []


def test_health_reports_not_signed_in_without_sending_a_prompt(monkeypatch, tmp_path):
    prepare(monkeypatch)

    class SignedOutClient(FakeClient):
        info = {"account": None, "models": []}

    monkeypatch.setattr(claude, "ClaudeSDKClient", SignedOutClient)
    status = asyncio.run(claude.ClaudeCodeAdapter(tmp_path).health(refresh=True))
    assert (status["installed"], status["signed_in"], status["ready"]) == (True, False, False)
    assert status["reason"] == "Not signed in to Claude Code"
    assert FakeClient.messages == []


def test_concurrent_steps_overlap_and_cancel_interrupts_every_client(monkeypatch, tmp_path):
    prepare(monkeypatch)

    class BlockingClient(FakeClient):
        instances = []
        in_flight = 0
        peak = 0
        both_started = asyncio.Event()
        release = asyncio.Event()

        def __init__(self, options):
            super().__init__(options)
            self.interrupted = False
            self.instances.append(self)

        async def receive_response(self):
            type(self).in_flight += 1
            type(self).peak = max(type(self).peak, type(self).in_flight)
            if type(self).in_flight == 2:
                type(self).both_started.set()
            try:
                await type(self).release.wait()
                yield ResultMessage("success", 1, 1, False, 1, f"session-{len(self.instances)}",
                                    structured_output={"claims": []})
            finally:
                type(self).in_flight -= 1

        async def interrupt(self):
            self.interrupted = True

    async def exercise():
        adapter = claude.ClaudeCodeAdapter(tmp_path)
        calls = [asyncio.create_task(adapter.run_step(
            "BASE", "DEVELOPER", message, {"type": "object"}, "opus", "max",
        )) for message in ("one", "two")]
        await asyncio.wait_for(BlockingClient.both_started.wait(), 1)
        cancelled = await adapter.cancel()
        BlockingClient.release.set()
        return cancelled, await asyncio.gather(*calls)

    monkeypatch.setattr(claude, "ClaudeSDKClient", BlockingClient)
    cancelled, results = asyncio.run(exercise())
    assert BlockingClient.peak == 2
    assert cancelled is True
    assert len(BlockingClient.instances) == 2
    assert all(client.interrupted for client in BlockingClient.instances)
    assert [result.status for result in results] == ["completed", "completed"]


def test_close_disconnects_every_active_client(monkeypatch, tmp_path):
    prepare(monkeypatch)

    class BlockingClient(FakeClient):
        instances = []
        both_started = asyncio.Event()
        release = asyncio.Event()

        def __init__(self, options):
            super().__init__(options)
            self.disconnected = False
            self.instances.append(self)

        async def receive_response(self):
            if len(self.instances) == 2:
                type(self).both_started.set()
            await type(self).release.wait()
            yield ResultMessage("success", 1, 1, False, 1, "session", structured_output={"claims": []})

        async def disconnect(self):
            self.disconnected = True

    async def exercise():
        adapter = claude.ClaudeCodeAdapter(tmp_path)
        calls = [asyncio.create_task(adapter.run_step(
            "BASE", "DEVELOPER", message, {"type": "object"}, "opus", "max",
        )) for message in ("one", "two")]
        await asyncio.wait_for(BlockingClient.both_started.wait(), 1)
        await adapter.close()
        BlockingClient.release.set()
        await asyncio.gather(*calls)

    monkeypatch.setattr(claude, "ClaudeSDKClient", BlockingClient)
    asyncio.run(exercise())
    assert len(BlockingClient.instances) == 2
    assert all(client.disconnected for client in BlockingClient.instances)
