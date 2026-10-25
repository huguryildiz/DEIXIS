"""The Codex adapter: sign-in state, model mismatch, delivery stages, environment allowlist and concurrent turns.

A fake app-server; no Codex is started. Passing shows the adapter's handling, not the live CLI's behaviour.
"""

import asyncio
import pytest
from pathlib import Path
from types import SimpleNamespace

from deixis.config import Settings
from deixis.domain import skill
from deixis.models import adapter
from deixis.models.adapter import codex_environment
from deixis.models.codex_rpc import CodexAppServer
from deixis.models.codex_rpc import RpcError
from deixis.models.codex_rpc import TurnResult
from deixis.storage import db
from deixis.tools import tool_probe
from deixis.workflow.run.flow import FlowDeps
from deixis.workflow.run.flow import ResearchFlow
from deixis.workflow.run.flow import RunStopped
from deixis.workflow.run.store import Store


@pytest.fixture
def codex(monkeypatch, tmp_path):
    class FakeServer(CodexAppServer):
        start_error = None
        request_error = None
        error_method = None
        account = {"type": "chatgpt", "planType": "SYNTHETIC"}
        model = "requested-model"
        turn_status = "completed"
        turn_error = None
        requests = []
        starts = 0
        closed = 0
        agent = None  # the app-server's `userAgent`, as the binary it was started from reports it
        step_gate = None  # set to an asyncio.Event to hold a turn open

        async def close(self):
            type(self).closed += 1

        async def start(self):
            type(self).starts += 1
            if self.start_error:
                raise self.start_error
            self.proc = SimpleNamespace(returncode=None)

        async def initialize(self, client_name, version):
            return {"userAgent": self.agent} if self.agent else {}

        async def request(self, method, params=None, timeout=60.0):
            self.requests.append((method, params))
            if method == self.error_method:
                raise self.request_error
            if method == "account/read":
                return {"account": self.account}
            if method in ("model/list", "mcpServerStatus/list"):
                return {"data": []}
            if method == "thread/start":
                return {"thread": {"id": "synthetic-thread"}, "model": self.model, "instructionSources": []}
            if method == "turn/start":
                if self.turn_status == "server_exited":
                    self.proc.returncode = 7
                    self.proc.stdout = asyncio.StreamReader()
                    self.proc.stdout.feed_eof()
                    await self._read_stdout()
                elif self.turn_status != "client_timeout":
                    if self.step_gate is not None:
                        await self.step_gate.wait()
                    await self._route_notification({
                        "method": "item/completed", "params": {"threadId": params["threadId"], "item": {
                            "type": "agentMessage", "phase": "final_answer", "text": '{"synthetic": true}',
                        }},
                    })
                    await self._route_notification({
                        "method": "turn/completed", "params": {"threadId": params["threadId"], "turn": {
                            "id": "synthetic-turn", "status": self.turn_status, "error": self.turn_error,
                        }},
                    })
                return {"turn": {"id": "synthetic-turn"}}
            assert method == "thread/unsubscribe"
            return {}

    monkeypatch.setattr(adapter, "CodexAppServer", FakeServer)
    monkeypatch.setattr(adapter, "find_tool", lambda name: "/SYNTHETIC/bin/codex")
    disk = {"version": "SYNTHETIC codex version"}  # what `codex --version` prints now

    async def version(argv, timeout=None, env=None):
        return tool_probe.Probe(0, disk["version"])

    monkeypatch.setattr(adapter, "probe", version)
    FakeServer.disk = disk
    return adapter.CodexAdapter(tmp_path / "home", tmp_path / "workspace"), FakeServer


def run_step(codex):
    return asyncio.run(codex.run_step("BASE", "DEVELOPER", "MESSAGE", {"type": "object"}, "requested-model", "high"))


def test_not_signed_in_is_not_ready_and_auth_rejection_fails_before_send(codex):
    connection, server = codex
    server.account = None
    status = asyncio.run(connection.health())
    assert (status["installed"], status["signed_in"], status["ready"]) == (True, False, False)
    assert status["reason"] == "Not signed in to the DEIXIS Codex home"

    server.error_method = "thread/start"
    server.request_error = RpcError("thread/start", {"message": "SYNTHETIC not signed in"})
    result = run_step(connection)
    assert (result.status, result.delivery_class) == ("unavailable", "before_send")
    assert result.error == str(server.request_error)
    assert not any(method == "turn/start" for method, _ in server.requests)


def test_codex_model_mismatch_is_recorded_and_rejected_by_shared_check(codex, tmp_path):
    connection, server = codex
    server.model = "other-model"
    conn = db.connect(tmp_path / "library.sqlite")
    try:
        db.migrate(conn)
        store = Store(conn)
        rid = store.create_research("SYNTHETIC question", "attached", "quick", [], "codex", "requested-model", "en")
        run = store.create_run(rid, "answer", {"max_model_calls": 2, "max_provider_requests": 0}, None)
        store.update_run(run["id"], status="running")
        flow = ResearchFlow(FlowDeps(
            Settings(data_dir=tmp_path / "data", port=8871), store, {"codex": connection}, skill.load_skill_package(), None,
        ))
        with pytest.raises(RunStopped):
            asyncio.run(flow._model_step(
                store.run(run["id"]), store.scope(rid), "synthetic:answer", "grounded_answer",
            ))

        saved_run = store.run(run["id"])
        assert (saved_run["status"], saved_run["pause_reason"]) == ("paused", "model_mismatch")
        step = store.step(run["id"], "synthetic:answer", "model:grounded_answer")
        assert (step["status"], step["error_code"]) == ("failed", "model_mismatch")
        session = conn.execute("SELECT status, resolved_model, raw_output FROM model_sessions").fetchone()
        assert tuple(session) == ("completed", "other-model", '{"synthetic": true}')
        assert conn.execute("SELECT COUNT(*) FROM answers").fetchone()[0] == 0
        assert sum(method == "turn/start" for method, _ in server.requests) == 1
    finally:
        conn.close()


ERRORS = [
    RpcError("SYNTHETIC", {"message": "process error"}),
    ConnectionError("SYNTHETIC closed stdout"),
    TimeoutError("SYNTHETIC timeout"),
    OSError("SYNTHETIC process error"),
]


@pytest.mark.parametrize("error", ERRORS[:1], ids=["rpc"])
@pytest.mark.parametrize("stage", ["turn/start"])
def test_process_errors_are_classified_by_delivery_stage(codex, stage, error):
    connection, server = codex
    if stage == "start":
        server.start_error = error
    else:
        server.error_method, server.request_error = stage, error
    result = run_step(connection)
    expected = ("failed", "after_send_unknown") if stage == "turn/start" else ("unavailable", "before_send")
    assert (result.status, result.delivery_class) == expected
    assert result.error == str(error)
    assert result.raw_text is None
    assert result.resolved_model == ("requested-model" if stage == "turn/start" else None)
    assert connection._active == set()


def test_codex_environment_keeps_runtime_variables_and_drops_secrets(monkeypatch):
    monkeypatch.setattr("deixis.models.adapter.find_tool", lambda name: None)
    monkeypatch.setattr("deixis.tools.tool_paths.find_tool", lambda name: None)  # no real codex or node folder joins PATH
    source = {
        "PATH": "/usr/bin", "HOME": "/Users/someone", "LC_ALL": "C", "HTTPS_PROXY": "http://proxy.local:3128",
        "OPENALEX_API_KEY": "secret", "DEEPSEEK_API_KEY": "secret", "DEIXIS_CONTACT_EMAIL": "someone@example.org",
        "CODEX_HOME": "/somewhere/else",
    }
    env = codex_environment(Path("/tmp/deixis-codex-home"), source)
    assert env == {"PATH": "/usr/bin", "HOME": "/Users/someone", "LC_ALL": "C", "HTTPS_PROXY": "http://proxy.local:3128",
                   "CODEX_HOME": "/tmp/deixis-codex-home"}


def test_codex_app_server_starts_with_analytics_and_feedback_off(tmp_path):
    from deixis.models.codex_isolation import isolation_overrides

    args, _ = isolation_overrides(config_path=tmp_path / "config.toml")
    pairs = [args[i + 1] for i in range(0, len(args), 2) if args[i] == "-c"]
    assert "analytics.enabled=false" in pairs and "feedback.enabled=false" in pairs


def test_codex_adapter_overlaps_turns_starts_one_server_and_cancels_both(monkeypatch, tmp_path):
    class FakeServer:
        instances = 0
        starts = 0
        peak = 0
        in_flight = 0
        both_started = asyncio.Event()
        release = asyncio.Event()

        def __init__(self, argv, cwd, env=None):
            type(self).instances += 1
            self.proc = None
            self.next_thread = 0
            self.interrupted = []

        async def start(self):
            type(self).starts += 1
            await asyncio.sleep(0)
            self.proc = SimpleNamespace(returncode=None)

        async def initialize(self, client_name, version):
            await asyncio.sleep(0)
            return {}

        async def request(self, method, params=None, timeout=60.0):
            if method == "thread/start":
                self.next_thread += 1
                return {"thread": {"id": f"thread-{self.next_thread}"}, "model": "resolved", "instructionSources": []}
            if method == "turn/interrupt":
                self.interrupted.append((params["threadId"], params["turnId"]))
            return {}

        async def run_turn(self, thread_id, text, output_schema, timeout=300.0, on_started=None, effort=None):
            cls = type(self)
            cls.in_flight += 1
            cls.peak = max(cls.peak, cls.in_flight)
            if on_started:
                await on_started(f"turn-{thread_id}")
            if cls.in_flight == 2:
                cls.both_started.set()
            try:
                await cls.release.wait()
                return TurnResult(
                    turn_id=f"turn-{thread_id}", status="completed", final_text=thread_id,
                    items=[{"type": "agentMessage", "phase": "final_answer", "text": thread_id}],
                )
            finally:
                cls.in_flight -= 1

        async def close(self):
            pass

    async def exercise():
        codex = adapter.CodexAdapter(tmp_path / "home", tmp_path / "workspace")
        calls = [asyncio.create_task(codex.run_step("base", "dev", text, {}, "model")) for text in ("one", "two")]
        await asyncio.wait_for(FakeServer.both_started.wait(), 1)
        cancelled = await codex.cancel()
        FakeServer.release.set()
        return codex, cancelled, await asyncio.gather(*calls)

    monkeypatch.setattr(adapter, "CodexAppServer", FakeServer)
    codex, cancelled, results = asyncio.run(exercise())
    assert FakeServer.instances == FakeServer.starts == 1
    assert FakeServer.peak == 2
    assert cancelled is True
    assert set(codex._server.interrupted) == {
        ("thread-1", "turn-thread-1"), ("thread-2", "turn-thread-2"),
    }
    assert [result.status for result in results] == ["completed", "completed"]
