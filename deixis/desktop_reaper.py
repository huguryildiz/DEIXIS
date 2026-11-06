"""Watchdog between the packaged app's shell and the backend, macOS (P10 M2).

    deixis-backend -m deixis.desktop_reaper [serve options...]

The shell (Tauri) starts this process and writes the control token as the first line on its stdin, then holds stdin
open. The watchdog moves into a session of its own (so it outlives the shell's process group), starts the backend
(`serve --desktop`) as the leader of a new process group, hands it the token as the first line of its stdin, and relays
the backend's stdout (the JSON start lines) and stderr to its own. Before the backend switches the child record on (and
so before it can start any recorded child) it names the record's path in a `child_record` line on stdout and waits
for this watchdog's `ack` line on stdin; that line is not relayed. It does no other work: every SCAN_SECONDS it notes
by pid + start time each process in the backend's subtree, in this watchdog's own session (which the backend and
everything it starts without leaving the session belong to) and in each recorded session whose launcher still runs
(`tools/child_record.py`), so a member that is orphaned later stays known.

Trigger: EOF on its stdin (the shell quit, crashed or was killed) or the end of the backend. Then it asks a backend
that still runs to stop (the token route), waits up to SHUTDOWN_WAIT_SECONDS, then SIGKILLs every other member of its
own session (the backend first among them). Once the backend is gone no new launcher can be recorded (a launcher
refuses a dead owner), so it then reads the record again and empties each recorded session of this backend while its
launcher lives, scanning again until no member is left, and only then kills the launcher; then every other known
identity still alive. It removes only the lines whose processes are verified gone and exits with the backend's code. A group or
session id is never used unless its leader is alive with its recorded start time. macOS has no subreaper: a process
that calls setsid itself and whose parent ended within one scan can escape all of this; the desktop acceptance diffs
the process table to catch such a case.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from deixis.tools import child_record

SCAN_SECONDS = 0.5
SHUTDOWN_WAIT_SECONDS = 8.0
CONTROL_HEADER = "X-Deixis-Control"
FORCED_EXIT = b"did not finish shutting down"  # the backend's own words (`__main__.watch_shutdown`)


def backend_argv(extra: list[str]) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "serve", "--desktop", *extra]
    return [sys.executable, "-m", "deixis", "serve", "--desktop", *extra]


def read_line(fd: int = 0) -> str:
    line = b""
    while len(line) < 4096:
        byte = os.read(fd, 1)
        if not byte or byte == b"\n":
            break
        line += byte
    return line.decode("utf-8", "replace").strip()


LOG_FILE: list[Path] = []  # logs/desktop-reaper.log in the data folder, once the backend has named that folder


def log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} desktop_reaper[{os.getpid()}]: {message}\n"
    try:
        sys.stderr.write(line)
        sys.stderr.flush()
    except (OSError, ValueError):
        pass
    if LOG_FILE:
        try:
            with open(LOG_FILE[0], "a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:
            pass


class Reaper:
    """The set of processes to stop for one backend, and the stop itself. A group or session is only searched or
    signalled through a leader that is alive with its recorded start time: this watchdog's own session (it is its
    leader), the backend's group while the backend runs, and each recorded session while its launcher runs. Everything
    else is signalled by the identities seen."""

    def __init__(self, backend_pid: int, backend_start: str | None, snapshot=child_record.snapshot):
        self.pid, self.start = backend_pid, backend_start
        self.owner = f"{backend_pid}:{backend_start}"
        self.me = child_record.identity(os.getpid())
        self.known: set[str] = set()
        self.record: Path | None = None
        self.snapshot = snapshot

    def recorded(self) -> list[child_record.Entry]:
        return [e for e in child_record.entries(self.record) if e.owner == self.owner] if self.record else []

    def scan(self) -> None:
        """Note the backend's live subtree, the members of this watchdog's session and of the recorded sessions."""
        table = self.snapshot()
        children: dict[int, list[int]] = {}
        for pid, (ppid, _pgid, _start) in table.items():
            children.setdefault(ppid, []).append(pid)
        recorded = self.recorded()
        roots = {self.pid: self.start} | {int(i.partition(":")[0]): i.partition(":")[2] for i in self.known}
        roots |= {e.pid: e.start for e in recorded}
        todo = [pid for pid, start in roots.items() if pid in table and table[pid][2] == start]
        seen: set[int] = set()
        while todo:
            pid = todo.pop()
            if pid in seen:
                continue
            seen.add(pid)
            todo.extend(children.get(pid, []))
        self.known |= {f"{pid}:{table[pid][2]}" for pid in seen - {os.getpid()} if pid in table}
        if self.me:
            self.known |= child_record.members(self.me, table)  # the backend's group and all it left in this session
        for entry in recorded:
            self.known |= child_record.members(entry.ident, table)
        self.known.discard(self.me or "")

    def on_line(self, line: bytes) -> tuple[bool, bytes | None]:
        """One stdout line of the backend: (relay it to the shell?, reply to write to the backend's stdin)."""
        try:
            event = json.loads(line)
            kind = event.get("event")
        except (ValueError, AttributeError):
            return True, None
        if kind == "child_record" and event.get("path"):
            self.record = Path(event["path"])
            LOG_FILE[:] = [self.record.parent.parent / "logs" / "desktop-reaper.log"]
            log(f"backend {self.pid} records its children in {self.record}")
            return False, b"ack\n"
        if kind == "listening" and event.get("data_dir"):
            LOG_FILE[:] = [Path(event["data_dir"]) / "logs" / "desktop-reaper.log"]
        return True, None

    def stop(self) -> list[str]:
        """SIGKILL the backend and every other member of this watchdog's session; then, with no owner left to record a
        new launcher, read the record again and empty each recorded session of this backend through its live launcher
        before the launcher itself goes (`child_record.sweep`); then every other identity seen. Drops only the lines
        whose processes are verified gone."""
        killed: list[str] = []
        if self.me:
            killed += child_record.sweep_members(self.me)
        left: set[str] = set()
        cleaned: set[str] = set()
        for entry in self.recorded():  # read again now that the owner is gone; launchers are never killed from `known`
            signalled, still = child_record.sweep(entry.ident)
            killed += signalled
            left |= still
            if not still:
                cleaned.add(entry.ident)
        killed += [ident for ident in sorted(self.known - left) if child_record.kill_identity(ident)]
        left |= child_record.wait_gone(self.known)
        if self.record and cleaned:
            try:
                child_record.rewrite(self.record, lambda e: e.ident not in cleaned)
            except OSError:
                pass
        if left:
            log(f"still alive after the stop: {', '.join(sorted(left))}")
        return killed


def ask_shutdown(port: int, token: str) -> bool:
    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/internal/shutdown", method="POST", data=b"",
                                     headers={CONTROL_HEADER: token})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # loopback, never through a proxy
    try:
        with opener.open(request, timeout=2) as response:
            return response.status == 202
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        os.setsid()
    except OSError:
        pass  # already a session leader
    token = read_line(0)
    env = {k: v for k, v in os.environ.items() if k != "DEIXIS_CONTROL_TOKEN"} | {child_record.ACK_ENV: "1"}
    proc = subprocess.Popen(backend_argv(argv), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            process_group=0, env=env)
    info = child_record.process_info(proc.pid)
    reaper = Reaper(proc.pid, info.start if info else None)
    proc.stdin.write((token + "\n").encode())
    proc.stdin.flush()
    port: list[int] = []
    shell_gone = threading.Event()

    def relay_stdout() -> None:
        for line in proc.stdout:
            relay, reply = reaper.on_line(line)
            if reply is not None:
                try:
                    proc.stdin.write(reply)
                    proc.stdin.flush()
                except (OSError, ValueError):
                    pass
            try:
                event = json.loads(line) if relay else {}
                if event.get("event") == "listening":
                    port.append(int(event["port"]))
                    log(f"backend {proc.pid} listening on port {event['port']}")
            except (ValueError, KeyError, TypeError, AttributeError):
                pass
            if not relay:
                continue
            try:
                sys.stdout.buffer.write(line)
                sys.stdout.buffer.flush()
            except (OSError, ValueError):
                pass

    def relay_stderr() -> None:
        for line in proc.stderr:
            if FORCED_EXIT in line:
                log("forced_exit: the backend ended by its shutdown time limit")
            try:
                sys.stderr.buffer.write(line)
                sys.stderr.buffer.flush()
            except (OSError, ValueError):
                pass

    def watch_shell() -> None:
        try:
            while os.read(0, 65536):
                pass
        except OSError:
            pass
        shell_gone.set()

    for target in (relay_stdout, relay_stderr, watch_shell):
        threading.Thread(target=target, daemon=True).start()
    while proc.poll() is None and not shell_gone.is_set():
        reaper.scan()
        shell_gone.wait(SCAN_SECONDS)
    reaper.scan()
    if proc.poll() is not None:
        log(f"the backend ended ({proc.returncode}); stopping what it left")
    else:
        log("the shell is gone; asking the backend to stop")
        if port and token:
            ask_shutdown(port[0], token)
        try:
            proc.stdin.close()  # stdin EOF stops the backend too, also before it listens
        except OSError:
            pass
        ends = time.monotonic() + SHUTDOWN_WAIT_SECONDS
        while proc.poll() is None and time.monotonic() < ends:
            reaper.scan()
            time.sleep(0.1)
    log(f"backend ended with {proc.poll()}" if proc.poll() is not None else "backend still running after the wait")
    killed = reaper.stop()
    log(f"stopped {len(killed)}: {', '.join(killed)}" if killed else "nothing left to stop")
    try:
        code = proc.wait(5)
    except subprocess.TimeoutExpired:
        code = -9
    return code if code >= 0 else 128 - code


if __name__ == "__main__":
    raise SystemExit(main())
