"""P9 H2 harness: starts real DEIXIS processes, kills them, and reads what the next start finds.

Rules the tests rely on (plan section 4, closing rule 2):
- every process is started by a test, on a port the OS gave (never 8765 or 8858 to 8864) and in a data directory under
  pytest's temp dir; nothing else is signalled. The kill under test is `os.kill(pid, SIGKILL)` on one PID, never a
  group kill, because a real crash ends one process and no production child starts its own session.
- every descendant is recorded as (pid, lstart, command, pgid) before the kill; the teardown kills what is still alive of
  that record when its start time and command still match, so a recycled PID is never signalled.
- the child environment is an allowlist; no model CLI is on its PATH and the working directory is a temp dir.
- child output goes to a file, never to an unread pipe.

Stated limit of the network guard (in `p9_driver.py`, read by `ServerProc.no_network`): it refuses a `socket.socket.connect`
to a non-loopback address and a `fetch_file` call. DNS resolution through `getaddrinfo` is outside it, so a name lookup
that never connects would not be logged.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DRIVER = HERE / "p9_driver.py"
BACKUP_DRIVER = HERE / "p9_backup_driver.py"
REFUSED_PORTS = {8765, *range(8858, 8865)}
QUESTION = "How is molecule release scheduling optimized?"


# ---- processes ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Ident:
    pid: int
    lstart: str
    command: str
    pgid: int


def _parse(line: str) -> tuple[int, int, int, str, str]:
    parts = line.split(None, 8)  # pid ppid pgid, lstart (five words), command
    return int(parts[0]), int(parts[1]), int(parts[2]), " ".join(parts[3:8]), parts[8] if len(parts) > 8 else ""


def ps_table() -> list[tuple[int, int, int, str, str]]:
    out = subprocess.run(["ps", "-A", "-ww", "-o", "pid=,ppid=,pgid=,lstart=,command="], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        try:
            rows.append(_parse(line.strip()))
        except (ValueError, IndexError):
            continue
    return rows


def ps_one(pid: int) -> tuple[str, str, str] | None:
    """(state, lstart, command) of one process, or None when `ps` finds nothing."""
    out = subprocess.run(["ps", "-ww", "-o", "stat=,lstart=,command=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    if not out:
        return None
    parts = out.split(None, 6)
    return parts[0], " ".join(parts[1:6]), parts[6] if len(parts) > 6 else ""


def ident_of(pid: int) -> Ident | None:
    for p, _, pgid, lstart, command in ps_table():
        if p == pid:
            return Ident(p, lstart, command, pgid)
    return None


def descendants(root: int) -> list[Ident]:
    rows = ps_table()
    seen, frontier, found = {root}, [root], []
    while frontier:
        parent = frontier.pop()
        for pid, ppid, pgid, lstart, command in rows:
            if ppid == parent and pid not in seen:
                seen.add(pid)
                frontier.append(pid)
                found.append(Ident(pid, lstart, command, pgid))
    return found


def is_same_and_live(ident: Ident) -> bool:
    """The recorded process still exists, is not a zombie and is the same process (start time and command match)."""
    now = ps_one(ident.pid)
    return now is not None and not now[0].startswith("Z") and now[1] == ident.lstart and now[2] == ident.command


def wait_gone(idents: list[Ident], seconds: float, what: str) -> float:
    """Seconds until none of `idents` is live (an orphan counts as gone when `ps` finds nothing or it is a zombie)."""
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        if not any(is_same_and_live(i) for i in idents):
            return time.monotonic() - started
        time.sleep(0.1)
    alive = [i for i in idents if is_same_and_live(i)]
    pytest.fail(f"{what}: still alive {seconds} s later: {[(i.pid, i.command[:80]) for i in alive]}")


def free_port() -> int:
    from deixis.__main__ import port_available

    for _ in range(50):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if port not in REFUSED_PORTS and port_available("127.0.0.1", port):
            return port
    raise RuntimeError("no free port")


def port_is_free(port: int) -> bool:
    from deixis.__main__ import port_available

    if not port_available("127.0.0.1", port):
        return False
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
    except OSError:
        return True
    return False


def child_env(home: Path, **extra: str) -> dict[str, str]:
    """The allowlist, named one by one. The venv's bin folder first, then the system's; no model CLI is on it."""
    bin_dir = str(Path(sys.executable).parent)
    path = f"{bin_dir}:/usr/bin:/bin"
    assert shutil.which("codex", path=path) is None, "a codex binary is on the child's PATH"
    env = {"PATH": path, "HOME": str(home), "PYTHONPATH": f"{REPO / 'backend'}:{REPO}",
           "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring"}
    for name, value in extra.items():
        assert name.startswith("P9_") or name in ("DEIXIS_DATA_DIR", "FAKE_RUNNER", "DEIXIS_CHILD_LIFETIME_SECONDS"), name
        env[name] = value
    return env


class Harness:
    def __init__(self, tmp: Path):
        if (REPO / ".env").exists():
            pytest.fail("<repo>/.env exists: load_settings would read it; move it away before running process tests")
        self.tmp = tmp
        self.home = tmp / "home"
        self.cwd = tmp / "cwd"
        self.home.mkdir()
        self.cwd.mkdir()
        self.servers: list[ServerProc] = []
        self.tracked: list[Ident] = []
        self.popens: list[subprocess.Popen] = []

    def track(self, ident: Ident | None) -> None:
        if ident is not None and ident not in self.tracked:
            self.tracked.append(ident)

    def record_descendants(self, pid: int) -> list[Ident]:
        found = descendants(pid)
        for ident in found:
            self.track(ident)
        return found

    def popen(self, argv: list[str], env: dict[str, str], log: Path, **kwargs: Any) -> subprocess.Popen:
        handle = open(log, "ab")
        proc = subprocess.Popen(argv, env=env, cwd=self.cwd, stdout=handle, stderr=subprocess.STDOUT, **kwargs)
        handle.close()
        self.popens.append(proc)
        self.track(ident_of(proc.pid))
        return proc

    def teardown(self) -> None:
        for proc in self.popens:
            if proc.poll() is None:
                self.record_descendants(proc.pid)
        for ident in reversed(self.tracked):  # per process, matching (pid, lstart, command) again; no group kill
            if is_same_and_live(ident):
                try:
                    os.kill(ident.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        for proc in self.popens:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    def start_server(self, data_dir: Path, name: str = "server", **env: str) -> "ServerProc":
        server = ServerProc(self, data_dir, name, env)
        self.servers.append(server)
        server.start()
        return server

    def run_cli(self, args: list[str], data_dir: Path, timeout: float = 120) -> subprocess.CompletedProcess:
        """`python -m deixis ...` (backup, restore) with its own data directory; allowlisted environment."""
        env = child_env(self.home, DEIXIS_DATA_DIR=str(data_dir))
        return subprocess.run([sys.executable, "-m", "deixis", *args], env=env, cwd=self.cwd, capture_output=True, text=True,
                              timeout=timeout)


@pytest.fixture
def harness(tmp_path):
    h = Harness(tmp_path)
    yield h
    h.teardown()


class ServerProc:
    def __init__(self, harness: Harness, data_dir: Path, name: str, env: dict[str, str]):
        self.h, self.data_dir, self.name = harness, data_dir, name
        self.port = free_port()
        self.calls_path = harness.tmp / f"{name}-{self.port}-calls.jsonl"
        self.log_path = harness.tmp / f"{name}-{self.port}.log"
        self.env = child_env(harness.home, P9_CALLS=str(self.calls_path), **env)
        self.proc: subprocess.Popen | None = None
        self.client: httpx.Client | None = None
        self.started_at = 0.0

    def start(self, timeout: float = 60) -> None:
        argv = [sys.executable, str(DRIVER), "--data-dir", str(self.data_dir), "--port", str(self.port)]
        # Its own session only isolates it from the terminal's Ctrl-C; the group is never signalled.
        self.proc = self.h.popen(argv, self.env, self.log_path, start_new_session=True)
        self.started_at = time.monotonic()
        base = f"http://127.0.0.1:{self.port}"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                pytest.fail(f"{self.name} exited with {self.proc.returncode} before it was ready:\n{self.log_text()[-2000:]}")
            try:
                if httpx.get(f"{base}/api/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            pytest.fail(f"{self.name} was not ready in {timeout} s:\n{self.log_text()[-2000:]}")
        self.client = httpx.Client(base_url=base, timeout=30)
        self.client.headers["x-deixis-csrf"] = self.client.get("/api/session").json()["csrf_token"]

    @property
    def pid(self) -> int:
        return self.proc.pid

    def alive(self) -> bool:
        return self.proc.poll() is None

    def log_text(self) -> str:
        return self.log_path.read_text(errors="replace") if self.log_path.exists() else ""

    def kill9(self) -> list[Ident]:
        """SIGKILL to this one PID; its descendants are recorded first."""
        found = self.h.record_descendants(self.pid)
        os.kill(self.pid, signal.SIGKILL)
        self.proc.wait(timeout=10)
        return found

    def signal(self, sig: int) -> float:
        started = time.monotonic()
        os.kill(self.pid, sig)
        return started

    def wait(self, timeout: float) -> int:
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pytest.fail(f"{self.name} did not exit in {timeout} s after the signal")

    def health(self) -> dict[str, Any]:
        return self.client.get("/api/health").json()

    def calls(self) -> list[dict[str, Any]]:
        if not self.calls_path.exists():
            return []
        return [json.loads(line) for line in self.calls_path.read_text().splitlines() if line.strip()]

    def wait_held(self, what: str, seconds: float = 60, **match: Any) -> dict[str, Any]:
        """The `held` line of `what` (and any other fields in `match`) in the call log."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            for row in self.calls():
                if row.get("kind") == "held" and row.get("what") == what and all(row.get(k) == v for k, v in match.items()):
                    return row
            if not self.alive():
                pytest.fail(f"{self.name} exited while waiting for a held {what}:\n{self.log_text()[-1500:]}")
            time.sleep(0.1)
        pytest.fail(f"no held {what} line in {seconds} s; calls: {self.calls()[-5:]}")

    def no_network(self) -> None:
        bad = [row for row in self.calls() if row.get("kind") == "network"]
        assert not bad, f"{self.name} tried to reach the network: {bad}"


def task_counts(calls: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in calls:
        if row.get("kind") == "model":
            counts[row["task"]] = counts.get(row["task"], 0) + 1
    return counts


def kind_count(calls: list[dict[str, Any]], kind: str) -> int:
    return sum(1 for row in calls if row.get("kind") == kind)


# ---- research flow through the HTTP API -------------------------------------------------------------------------


def create_research(c: httpx.Client, scope: str, question: str = QUESTION) -> str:
    r = c.post("/api/researches", json={"question": question, "model_connection": "codex", "requested_model": "fixture-model",
                                        "effort": "quick", "source_scope": scope})
    assert r.status_code in (200, 201), r.text
    return r.json()["research"]["id"]


def research_view(c: httpx.Client, rid: str) -> dict[str, Any]:
    r = c.get(f"/api/researches/{rid}")
    assert r.status_code == 200, r.text
    return r.json()


def run_row(c: httpx.Client, rid: str, run_id: str) -> dict[str, Any]:
    return next(run for run in research_view(c, rid)["runs"] if run["id"] == run_id)


def wait_run(c: httpx.Client, rid: str, run_id: str, statuses: tuple[str, ...] = ("completed", "failed", "paused", "cancelled"),
             seconds: float = 120) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    row: dict[str, Any] = {}
    while time.monotonic() < deadline:
        row = run_row(c, rid, run_id)
        if row["status"] in statuses:
            return row
        time.sleep(0.2)
    pytest.fail(f"run {run_id} did not reach {statuses} in {seconds} s; last: {row.get('status')}")


def start_run(c: httpx.Client, rid: str, kind: str) -> str:
    r = c.post(f"/api/researches/{rid}/runs", json={"kind": kind})
    assert r.status_code == 202, r.text
    return r.json()["id"]


def include_records(c: httpx.Client, rid: str) -> int:
    count = 0
    for source in research_view(c, rid)["sources"]:
        if source["version_role"] != "record":
            continue
        r = c.patch(f"/api/researches/{rid}/selections/{source['source_version_id']}",
                    json={"state": "included", "expected_version": source["selection"]["version"], "reason": "p9 test"})
        assert r.status_code == 200, r.text
        count += 1
    return count


def upload(c: httpx.Client, rid: str, name: str, data: bytes, timeout: float = 120) -> httpx.Response:
    return c.post(f"/api/researches/{rid}/uploads", files={"file": (name, data, "application/pdf")}, timeout=timeout)


def discovery_to_answer_ready(c: httpx.Client, rid: str) -> str:
    """Run discovery to its end and include every record; returns the discovery run id."""
    run_id = start_run(c, rid, "discovery")
    row = wait_run(c, rid, run_id)
    assert row["status"] == "completed", row
    assert include_records(c, rid) > 0
    return run_id


# ---- read-only SQLite -------------------------------------------------------------------------------------------


def ro(data_dir: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{data_dir / 'library.sqlite'}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def integrity_check(data_dir: Path) -> str:
    with ro(data_dir) as conn:
        return conn.execute("PRAGMA integrity_check").fetchone()[0]


def foreign_key_check(data_dir: Path) -> list[tuple]:
    with ro(data_dir) as conn:
        return [tuple(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()]


def count(data_dir: Path, table: str, where: str = "1=1", params: tuple = ()) -> int:
    with ro(data_dir) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0]  # noqa: S608 - test-owned names


def rows(data_dir: Path, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with ro(data_dir) as conn:
        return conn.execute(sql, params).fetchall()


def digest(data_dir: Path, table: str, columns: list[str], where: str = "1=1", params: tuple = ()) -> str:
    """A canonical digest of a table's rows for chosen columns (rows ordered by those columns, JSON with sorted keys)."""
    with ro(data_dir) as conn:
        found = conn.execute(f"SELECT {', '.join(columns)} FROM {table} WHERE {where} ORDER BY {', '.join(columns)}", params).fetchall()  # noqa: S608
    return hashlib.sha256(json.dumps([list(row) for row in found], sort_keys=True, default=str).encode()).hexdigest()


PASSAGE_COLUMNS = ["id", "source_version_id", "asset_id", "kind", "physical_page", "extraction_version", "text_sha256"]
ASSET_COLUMNS = ["id", "source_version_id", "sha256", "byte_size", "storage_path", "extraction_status", "page_count"]


def papers_files(data_dir: Path) -> list[Path]:
    folder = data_dir / "papers"
    return sorted(folder.iterdir()) if folder.exists() else []


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wait_for(predicate: Callable[[], Any], seconds: float, what: str, step: float = 0.1) -> Any:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        found = predicate()
        if found:
            return found
        time.sleep(step)
    pytest.fail(f"{what} did not happen in {seconds} s")
