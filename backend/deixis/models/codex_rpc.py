"""Minimal client for `codex app-server` over stdio (newline-delimited JSON-RPC).

Server-initiated requests are answered fail-closed: DEIXIS never approves a
command, file change, permission grant, dynamic tool call or token refresh
requested on behalf of a model step. Every such request is recorded.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

TOOL_ITEM_TYPES = frozenset(
    {
        "commandExecution",
        "fileChange",
        "mcpToolCall",
        "dynamicToolCall",
        "collabAgentToolCall",
        "subAgentActivity",
        "webSearch",
        "imageView",
        "imageGeneration",
        "sleep",
    }
)


class RpcError(Exception):
    def __init__(self, method: str, error: Any):
        super().__init__(f"{method}: {error}")
        self.method = method
        self.error = error


def deny_server_request(method: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
        return {"decision": "decline"}, None
    if method == "mcpServer/elicitation/request":
        return {"action": "decline", "content": None}, None
    if method == "item/tool/call":
        return {"contentItems": [], "success": False}, None
    return None, {"code": -32000, "message": f"DEIXIS does not grant {method}"}


@dataclass
class TurnResult:
    turn_id: str | None
    status: str
    error: Any = None
    started_item_types: list[str] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)
    final_text: str | None = None
    token_usage: dict[str, Any] | None = None
    notification_counts: dict[str, int] = field(default_factory=dict)

    @property
    def tool_item_types(self) -> list[str]:
        seen = self.started_item_types + [i.get("type", "") for i in self.items]
        return sorted({t for t in seen if t in TOOL_ITEM_TYPES})


class CodexAppServer:
    def __init__(self, argv: list[str], cwd: str, env: dict[str, str] | None = None):
        self.argv = argv
        self.cwd = cwd
        self.env = env
        self.proc: asyncio.subprocess.Process | None = None
        self.notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.server_requests: list[dict[str, Any]] = []
        self.stderr_tail: deque[str] = deque(maxlen=80)
        self._pending: dict[int, asyncio.Future] = {}
        self._ids = itertools.count(1)
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            *self.argv,
            cwd=self.cwd,
            env=self.env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=64 * 1024 * 1024,
        )
        self._tasks = [asyncio.create_task(self._read_stdout()), asyncio.create_task(self._read_stderr())]

    async def initialize(self, client_name: str, version: str) -> dict[str, Any]:
        result = await self.request(
            "initialize",
            {"clientInfo": {"name": client_name, "title": "DEIXIS", "version": version}},
        )
        await self.notify("initialized")
        return result

    async def _send(self, message: dict[str, Any]) -> None:
        assert self.proc and self.proc.stdin
        self.proc.stdin.write((json.dumps(message) + "\n").encode())
        await self.proc.stdin.drain()

    async def request(self, method: str, params: dict[str, Any] | None = None, timeout: float = 60.0) -> Any:
        rid = next(self._ids)
        future = asyncio.get_running_loop().create_future()
        self._pending[rid] = future
        message: dict[str, Any] = {"id": rid, "method": method}
        if params is not None:
            message["params"] = params
        await self._send(message)
        try:
            response = await asyncio.wait_for(future, timeout)
        finally:
            self._pending.pop(rid, None)
        if "error" in response:
            raise RpcError(method, response["error"])
        return response.get("result")

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"method": method}
        if params is not None:
            message["params"] = params
        await self._send(message)

    async def _read_stdout(self) -> None:
        assert self.proc and self.proc.stdout
        while line := await self.proc.stdout.readline():
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                self.stderr_tail.append(f"[non-json stdout] {line[:200]!r}")
                continue
            if "method" in message and "id" in message:
                await self._answer_server_request(message)
            elif "method" in message:
                await self.notifications.put(message)
            elif "id" in message and message["id"] in self._pending:
                future = self._pending[message["id"]]
                if not future.done():
                    future.set_result(message)
        for future in self._pending.values():
            if not future.done():
                future.set_exception(ConnectionError("codex app-server closed stdout"))
        await self.notifications.put({"method": "__eof__"})

    async def _answer_server_request(self, message: dict[str, Any]) -> None:
        result, error = deny_server_request(message["method"])
        self.server_requests.append(
            {"method": message["method"], "answered": "error" if error else result}
        )
        reply: dict[str, Any] = {"id": message["id"]}
        reply.update({"error": error} if error else {"result": result})
        await self._send(reply)

    async def _read_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        while line := await self.proc.stderr.readline():
            self.stderr_tail.append(line.decode(errors="replace").rstrip()[:500])

    async def run_turn(
        self,
        thread_id: str,
        text: str,
        output_schema: dict[str, Any] | None,
        timeout: float = 300.0,
        on_started: Callable[[str], Awaitable[None]] | None = None,
    ) -> TurnResult:
        params: dict[str, Any] = {"threadId": thread_id, "input": [{"type": "text", "text": text}]}
        if output_schema is not None:
            params["outputSchema"] = output_schema
        started = await self.request("turn/start", params)
        turn_id = started["turn"]["id"]
        result = TurnResult(turn_id=turn_id, status="inProgress")
        counts: Counter[str] = Counter()
        if on_started:
            await on_started(turn_id)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                result.status = "client_timeout"
                break
            try:
                message = await asyncio.wait_for(self.notifications.get(), remaining)
            except TimeoutError:
                result.status = "client_timeout"
                break
            method = message["method"]
            counts[method] += 1
            if method == "__eof__":
                result.status = "server_exited"
                break
            params = message.get("params") or {}
            if params.get("threadId") not in (None, thread_id):
                continue
            if method == "item/started":
                result.started_item_types.append(params["item"].get("type", ""))
            elif method == "item/completed":
                result.items.append(params["item"])
            elif method == "thread/tokenUsage/updated":
                result.token_usage = params.get("tokenUsage")
            elif method == "turn/completed" and params["turn"]["id"] == turn_id:
                result.status = params["turn"]["status"]
                result.error = params["turn"].get("error")
                break
        messages = [i for i in result.items if i.get("type") == "agentMessage"]
        finals = [m for m in messages if m.get("phase") == "final_answer"] or messages
        result.final_text = finals[-1]["text"] if finals else None
        result.notification_counts = dict(counts)
        return result

    async def close(self) -> None:
        if not self.proc:
            return
        if self.proc.returncode is None:
            if self.proc.stdin:
                self.proc.stdin.close()
            try:
                await asyncio.wait_for(self.proc.wait(), 5)
            except TimeoutError:
                self.proc.terminate()
                try:
                    await asyncio.wait_for(self.proc.wait(), 5)
                except TimeoutError:
                    self.proc.kill()
                    await self.proc.wait()
        for task in self._tasks:
            task.cancel()
