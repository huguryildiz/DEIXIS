import asyncio
from types import SimpleNamespace

from deixis.models import adapter
from deixis.models.codex_rpc import CodexAppServer, TurnResult


def test_run_turn_routes_interleaved_notifications_to_their_threads():
    async def exercise():
        server = CodexAppServer(["codex"], "/SYNTHETIC")

        async def request(method, params=None, timeout=60.0):
            assert method == "turn/start"
            return {"turn": {"id": f"turn-{params['threadId']}"}}

        server.request = request
        first = asyncio.create_task(server.run_turn("one", "first", None))
        second = asyncio.create_task(server.run_turn("two", "second", None))
        while len(server._turn_notifications) < 2:
            await asyncio.sleep(0)

        await server._route_notification({"method": "server/ping"})
        await server._route_notification({
            "method": "item/started", "params": {"threadId": "two", "item": {"type": "webSearch"}},
        })
        await server._route_notification({
            "method": "item/completed", "params": {"threadId": "one", "item": {
                "type": "agentMessage", "phase": "final_answer", "text": "first answer",
            }},
        })
        await server._route_notification({
            "method": "thread/tokenUsage/updated", "params": {"threadId": "two", "tokenUsage": {"total": 22}},
        })
        await server._route_notification({
            "method": "item/started", "params": {"threadId": "one", "item": {"type": "commandExecution"}},
        })
        await server._route_notification({
            "method": "item/completed", "params": {"threadId": "two", "item": {
                "type": "agentMessage", "phase": "final_answer", "text": "second answer",
            }},
        })
        await server._route_notification({
            "method": "thread/tokenUsage/updated", "params": {"threadId": "one", "tokenUsage": {"total": 11}},
        })
        await server._route_notification({
            "method": "turn/completed", "params": {"threadId": "two", "turn": {
                "id": "turn-two", "status": "interrupted", "error": "stopped",
            }},
        })
        await server._route_notification({
            "method": "turn/completed", "params": {"threadId": "one", "turn": {
                "id": "turn-one", "status": "completed",
            }},
        })
        return server, *await asyncio.gather(first, second)

    server, first, second = asyncio.run(exercise())
    assert (first.final_text, first.token_usage, first.status, first.error) == (
        "first answer", {"total": 11}, "completed", None,
    )
    assert (second.final_text, second.token_usage, second.status, second.error) == (
        "second answer", {"total": 22}, "interrupted", "stopped",
    )
    assert first.tool_item_types == ["commandExecution"]
    assert second.tool_item_types == ["webSearch"]
    assert first.notification_counts["server/ping"] == second.notification_counts["server/ping"] == 1


def test_run_turn_eof_ends_every_waiting_thread():
    async def exercise():
        server = CodexAppServer(["codex"], "/SYNTHETIC")

        async def request(method, params=None, timeout=60.0):
            return {"turn": {"id": f"turn-{params['threadId']}"}}

        server.request = request
        turns = [asyncio.create_task(server.run_turn(thread, "message", None)) for thread in ("one", "two")]
        while len(server._turn_notifications) < 2:
            await asyncio.sleep(0)
        await server._route_notification({"method": "__eof__"})
        return await asyncio.gather(*turns)

    results = asyncio.run(exercise())
    assert [result.status for result in results] == ["server_exited", "server_exited"]


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


import pytest


@pytest.mark.parametrize("started", [True, False])
def test_codex_turn_is_interrupted_when_its_caller_stops_waiting(monkeypatch, tmp_path, started):
    """D258: a read cutoff cancels the wait; the adapter interrupts that turn and leaves the thread."""
    class FakeServer:
        def __init__(self, argv, cwd, env=None):
            self.proc = None
            self.sent = []
            self.started = asyncio.Event()

        async def start(self):
            self.proc = SimpleNamespace(returncode=None)

        async def initialize(self, client_name, version):
            return {}

        async def request(self, method, params=None, timeout=60.0):
            self.sent.append((method, params))
            if method == "thread/start":
                return {"thread": {"id": "thread-1"}, "model": "resolved", "instructionSources": []}
            return {}

        async def run_turn(self, thread_id, text, output_schema, timeout=300.0, on_started=None, effort=None):
            if started:
                await on_started("turn-1")
            self.started.set()  # without `started`, cancelled before the turn's id came back
            await asyncio.sleep(60)

        async def close(self):
            pass

    async def exercise():
        codex = adapter.CodexAdapter(tmp_path / "home", tmp_path / "workspace")
        call = asyncio.create_task(codex.run_step("base", "dev", "text", {}, "model"))
        while codex._server is None or not codex._server.started.is_set():
            await asyncio.sleep(0)
        call.cancel()
        await asyncio.gather(call, return_exceptions=True)
        await asyncio.gather(*codex._abandoned)
        return codex

    monkeypatch.setattr(adapter, "CodexAppServer", FakeServer)
    codex = asyncio.run(exercise())
    assert (("turn/interrupt", {"threadId": "thread-1", "turnId": "turn-1"}) in codex._server.sent) is started
    assert ("thread/unsubscribe", {"threadId": "thread-1"}) in codex._server.sent
    assert not codex._active and not codex._abandoned
