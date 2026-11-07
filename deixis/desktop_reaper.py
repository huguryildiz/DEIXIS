"""Watchdog between the packaged app's shell and the backend, macOS (P10 M2) and Linux (L2).

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
the process table to catch such a case. On Linux the watchdog is the backend's child subreaper
(`PR_SET_CHILD_SUBREAPER`): an orphaned descendant is re-parented to it, not to init, so the scan, which also walks the
watchdog's own children, keeps it; the watchdog reaps those orphans when they end (never the backend, whose status
stays with `subprocess`).
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from deixis.documents import child_guard
from deixis.tools import child_record

SCAN_SECONDS = 0.5
SHUTDOWN_WAIT_SECONDS = 8.0
STOP_BUDGET_SECONDS = 13.0  # one deadline from the trigger to the end of the stop; the shell waits 8 + 6 s for this watchdog
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


PR_SET_CHILD_SUBREAPER = 36


def become_subreaper() -> bool:
    """Linux: orphaned descendants come to this process instead of init. False elsewhere or on failure."""
    if not child_record.LINUX:
        return False
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        return libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) == 0
    except (OSError, AttributeError):
        return False


def reap_orphans(backend_pid: int) -> list[int]:
    """Linux: wait for the ended orphans re-parented to this watchdog (zombies whose parent is this process), never the
    backend: `waitpid(-1)` would take its exit status from `subprocess.Popen`."""
    if not child_record.LINUX:
        return []
    reaped = []
    for pid, (state, ppid, _pgid, _start) in child_record.proc_stats().items():
        if state == "Z" and ppid == os.getpid() and pid != backend_pid:
            try:
                if os.waitpid(pid, os.WNOHANG)[0] == pid:
                    reaped.append(pid)
            except ChildProcessError:
                pass
    return reaped


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
        self.subreaper = False  # Linux: set by main() once this process is the subreaper; then stop() sweeps its subtree

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
        if self.subreaper:  # orphans re-parented to this subreaper
            roots |= {pid: start for pid, (ppid, _pgid, start) in table.items() if ppid == os.getpid()}
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

    def stop(self, deadline: float | None = None) -> list[str]:
        """SIGKILL the backend and every other member of this watchdog's session; then, with no owner left to record a
        new launcher, read the record again and empty each recorded session of this backend through its live launcher
        before the launcher itself goes (`child_record.sweep`); then every other identity seen; on Linux last the whole
        subtree again. Every stage takes only what is left of `deadline` (monotonic; default STOP_BUDGET_SECONDS from
        now), so the shell's wait for this process is never outrun. Drops only the lines whose processes are verified
        gone; the others stay for `recover` at the next start."""
        deadline = time.monotonic() + STOP_BUDGET_SECONDS if deadline is None else deadline
        remaining = lambda: max(0.0, deadline - time.monotonic())  # noqa: E731
        killed: list[str] = []
        if self.me:
            killed += child_record.sweep_members(self.me, remaining())
        left: set[str] = set()
        cleaned: set[str] = set()
        for entry in self.recorded():  # read again now that the owner is gone; launchers are never killed from `known`
            signalled, still = child_record.sweep(entry.ident, remaining())
            killed += signalled
            left |= still
            if not still:
                cleaned.add(entry.ident)
        killed += [ident for ident in sorted(self.known - left) if child_record.kill_identity(ident)]
        left |= child_record.wait_gone(self.known, min(child_record.GONE_WAIT_SECONDS, remaining()))
        if self.record and cleaned:
            try:
                child_record.rewrite(self.record, lambda e: e.ident not in cleaned)
            except OSError:
                pass
        if self.subreaper:
            killed += self.sweep_subtree(remaining())
            left = {i for i in left if child_record.alive(i)}
        if left:
            log(f"still alive after the stop: {', '.join(sorted(left))}")
        return killed

    def drain(self, deadline: float) -> bool:
        """Linux, after the backend was waited for: stop only once the kernel says this watchdog has no child at all
        (`waitid` ECHILD). A /proc scan can miss a process that forked and exited while it read; its child is then
        adopted here, so a live child the kernel still counts leads to another subtree sweep. Ended children are reaped
        (none is the backend: Popen has its status)."""
        while True:
            try:
                ended = os.waitid(os.P_ALL, 0, os.WEXITED | os.WNOHANG)
            except ChildProcessError:
                return True
            if ended is not None:
                continue
            if time.monotonic() >= deadline:
                return False
            self.sweep_subtree(min(0.5, max(0.0, deadline - time.monotonic())))
            time.sleep(0.02)

    def sweep_subtree(self, seconds: float) -> list[str]:
        """Linux: kill this watchdog's whole live subtree (its children by ppid, recursively: the backend's family and
        the orphans adopted as subreaper), scanning again after each round until a scan finds none or `seconds` pass.
        Catches a process started after the last scan, also one that called setsid."""
        killed: list[str] = []
        ends = time.monotonic() + seconds
        while time.monotonic() < ends:
            table = self.snapshot()
            children: dict[int, list[int]] = {}
            for pid, (ppid, _pgid, _start) in table.items():
                children.setdefault(ppid, []).append(pid)
            found, todo = set(), list(children.get(os.getpid(), []))
            while todo:
                pid = todo.pop()
                if pid not in found:
                    found.add(pid)
                    todo.extend(children.get(pid, []))
            idents = {f"{pid}:{table[pid][2]}" for pid in found}
            if not idents:
                break
            killed += [ident for ident in sorted(idents) if child_record.kill_identity(ident)]
            child_record.wait_gone(idents, min(1.0, max(0.0, ends - time.monotonic())))
            reap_orphans(self.pid)
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
    subreaper = become_subreaper() and child_guard.boot_id() is not None  # Linux: no boot id, no identity to kill by
    if child_record.LINUX and not subreaper:
        print(json.dumps({"event": "startup_failed", "code": "process_guard",
                          "message": "DEIXIS could not set up the guard that stops its programs when it quits."}), flush=True)
        log("child subreaper could not be set; the backend is not started")
        return 1
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
    reaper.subreaper = subreaper
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
        reap_orphans(proc.pid)
        shell_gone.wait(SCAN_SECONDS)
    deadline = time.monotonic() + STOP_BUDGET_SECONDS  # one deadline from the trigger for every stage below
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
        ends = min(time.monotonic() + SHUTDOWN_WAIT_SECONDS, deadline - 2.0)
        while proc.poll() is None and time.monotonic() < ends:
            reaper.scan()
            time.sleep(0.1)
    log(f"backend ended with {proc.poll()}" if proc.poll() is not None else "backend still running after the wait")
    killed = reaper.stop(deadline)
    reap_orphans(proc.pid)
    log(f"stopped {len(killed)}: {', '.join(killed)}" if killed else "nothing left to stop")
    try:
        code = proc.wait(max(0.5, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        code = -9
    if subreaper and proc.returncode is not None:  # the backend's status is Popen's now; every other child is ours
        drained = reaper.drain(deadline)
        log("no child left" if drained else "children still alive at the deadline")
    return code if code >= 0 else 128 - code


if __name__ == "__main__":
    raise SystemExit(main())
