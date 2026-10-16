"""Codex adapter paths with a fake app-server; no CLI, network or real model calls."""

import asyncio
from types import SimpleNamespace

import pytest

from deixis.tools import tool_probe
from deixis.config import Settings
from deixis.domain import skill
from deixis.models import adapter
from deixis.models.codex_rpc import CodexAppServer, RpcError
from deixis.storage import db
from deixis.workflow.flow import FlowDeps, ResearchFlow, RunStopped
from deixis.workflow.store import Store


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


def test_missing_cli_is_not_ready_and_fails_before_send(codex, monkeypatch):
    connection, server = codex
    monkeypatch.setattr(adapter, "find_tool", lambda name: None)
    server.start_error = FileNotFoundError("codex CLI not found")

    assert asyncio.run(connection.health()) == {
        "connection": "codex", "installed": False, "ready": False, "reason": "codex CLI not found",
    }
    assert server.starts == 0
    result = run_step(connection)
    assert (result.status, result.delivery_class, result.error) == ("unavailable", "before_send", "codex CLI not found")
    assert result.resolved_model is None and result.raw_text is None
    assert server.requests == []


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


def test_resolved_model_comes_from_thread_start(codex):
    connection, server = codex
    server.model = "resolved-model"
    result = run_step(connection)
    assert (result.status, result.raw_text, result.resolved_model, result.external_thread_id) == (
        "completed", '{"synthetic": true}', "resolved-model", "synthetic-thread",
    )
    assert result.delivery_class is None and result.error is None
    assert result.requested_model_verified is False
    requests = dict(server.requests)
    assert requests["thread/start"]["model"] == "requested-model"
    assert requests["turn/start"]["effort"] == "high"
    assert connection._active == set()


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


@pytest.mark.parametrize("error", ERRORS, ids=["rpc", "connection", "timeout", "os"])
@pytest.mark.parametrize("stage", ["start", "account/read"])
def test_health_reports_app_server_errors(codex, stage, error):
    connection, server = codex
    if stage == "start":
        server.start_error = error
    else:
        server.error_method, server.request_error = stage, error
    status = asyncio.run(connection.health())
    assert status["installed"] is True and status["ready"] is False
    assert status["reason"] == f"codex app-server error: {str(error)[:200]}"


@pytest.mark.parametrize("error", ERRORS, ids=["rpc", "connection", "timeout", "os"])
@pytest.mark.parametrize("stage", ["start", "thread/start", "turn/start"])
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


@pytest.mark.parametrize("turn_status", ["client_timeout", "server_exited"])
def test_turn_timeout_and_nonzero_exit_have_unknown_delivery(codex, turn_status):
    connection, server = codex
    server.turn_status = turn_status
    connection.turn_timeout = 0 if turn_status == "client_timeout" else 1
    result = run_step(connection)
    assert (result.status, result.delivery_class, result.error) == ("failed", "after_send_unknown", turn_status)
    assert result.resolved_model == "requested-model" and result.raw_text is None
    assert connection._active == set() and connection._server._turn_notifications == {}
    if turn_status == "server_exited":
        assert connection._server.proc.returncode == 7


@pytest.mark.parametrize("message, limited", [
    ("SYNTHETIC HTTP 429: Too Many Requests", True),
    ("SYNTHETIC rate_limit_error", True),
    ("SYNTHETIC quota exceeded", False),
    ("SYNTHETIC authentication failed", False),
])
def test_failed_turn_error_text_reaches_rate_limit_classifier(codex, message, limited):
    connection, server = codex
    server.turn_status = "failed"
    server.turn_error = {"message": message}
    result = run_step(connection)
    assert (result.status, result.delivery_class) == ("failed", "after_send_unknown")
    assert result.error == str(server.turn_error)
    assert adapter.is_rate_limited(result) is limited


def swap_binary(server, version):
    """The CLI updated itself: `codex --version` says `version` now, and a server started from here on reports it."""
    server.disk["version"] = f"codex-cli {version}"
    server.agent = f"deixis/{version} (SYNTHETIC)"


def test_health_tells_the_running_version_from_the_one_on_disk_and_restarts_at_an_idle_moment(codex):
    connection, server = codex
    swap_binary(server, "1.0.0")
    status = asyncio.run(connection.health(refresh=True))
    assert (status["cli_version"], status["running_version"], status["restart_pending"], server.starts) == ("codex-cli 1.0.0", "1.0.0", False, 1)

    swap_binary(server, "1.1.0")  # the CLI is updated while DEIXIS runs
    status = asyncio.run(connection.health(refresh=True))
    assert (status["cli_version"], status["running_version"], status["restart_pending"]) == ("codex-cli 1.1.0", "1.1.0", False)
    assert (server.starts, server.closed) == (2, 1)  # idle: the old server was closed and a new one started
    asyncio.run(connection.health(refresh=True))
    assert server.starts == 2  # nothing changed, nothing restarted


def test_a_swapped_binary_never_restarts_the_server_mid_step(codex):
    connection, server = codex
    swap_binary(server, "1.0.0")

    async def scenario():
        await connection.health(refresh=True)
        server.step_gate = asyncio.Event()
        step = asyncio.create_task(connection.run_step("BASE", "DEVELOPER", "MESSAGE", {"type": "object"}, "requested-model"))
        while not any(method == "turn/start" for method, _ in server.requests):
            await asyncio.sleep(0)
        swap_binary(server, "1.1.0")
        busy = await connection.health(refresh=True)  # a step is using the old server
        assert (busy["running_version"], busy["restart_pending"], server.starts, server.closed) == ("1.0.0", True, 1, 0)
        server.step_gate.set()
        assert (await step).status == "completed"
        idle = await connection.health(refresh=True)  # the step is done
        return idle
    idle = asyncio.run(scenario())
    assert (idle["running_version"], idle["restart_pending"], server.starts, server.closed) == ("1.1.0", False, 2, 1)


def test_a_step_looks_at_the_disk_version_at_most_every_30_seconds(codex):
    connection, server = codex
    swap_binary(server, "1.0.0")

    async def scenario():
        await connection.run_step("BASE", "DEVELOPER", "MESSAGE", {"type": "object"}, "requested-model")
        swap_binary(server, "1.1.0")
        await connection.run_step("BASE", "DEVELOPER", "MESSAGE", {"type": "object"}, "requested-model")
        assert server.starts == 1  # looked less than 30 s ago
        connection._disk_checked = 0.0
        await connection.run_step("BASE", "DEVELOPER", "MESSAGE", {"type": "object"}, "requested-model")
    asyncio.run(scenario())
    assert (server.starts, server.closed, connection._running_version) == (2, 1, "1.1.0")
