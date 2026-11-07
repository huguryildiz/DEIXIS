"""The record of processes DEIXIS starts in a session of their own (P10 M2): `run/children.jsonl` in the data folder.

macOS and Linux (`ON`): the session scan reads the process table through libproc on macOS and `/proc` on Linux (P10
L2). On Windows this layer is off and the job objects stand in for it (`tools/win_job.py`).

A model CLI or tool probe (`models/cli_process.py`), a local model server (`documents/local_embedding.py`) and the
login-shell PATH read (`tools/tool_paths.py`) leave the backend's process group on purpose, so a kill of that group
does not reach them. On macOS and Linux each is started through `deixis.session_launcher`: a small process that leads the new
session and, while the record is on, writes its own line here (pid, kernel start time, group, session, and the
identity of the backend that owns it) and only then starts the program, which stays in its group and session. If the
line cannot be written, or the owning backend is already gone, the program is never started. The launcher outlives the
program and watches its owner: when the program ends, or the owner dies, it kills every process still in its session,
again until none is left, and only then removes its line. The PDF children's memory guard (`documents/child_guard.py`)
never forks; it writes its own line before it reports ready and does not run without one.

Ownership is proven, never assumed. A group or session id is used to find or signal processes only while its leader
is alive with the start time read when it was started or recorded (a live leader's pid cannot be reused, so the id is
still that leader's). Once a leader is gone, only identities seen and recorded (pid + start time) are signalled. Every
kill re-reads the identity first; on Linux through a pidfd opened before the re-read, so a pid reused in between is
never hit; macOS has no pidfd to close the last microseconds. A line is removed only once what
it names is verified gone.

The record is switched on by `configure` (the serving backend) and reaches the app's own Python children through the
environment (`child_env(bundled=True)` passes these two names). Nothing is recorded while it is off (tests, the CLI
commands); the launcher then only leads and empties its session. Writes take an exclusive `flock` and are fsynced.
"""

from __future__ import annotations

import ctypes
import json
import os
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from deixis.documents.child_guard import _BsdInfo, _libproc, linux_start, process_info, signal_identity  # pid + start identity

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

RECORD_ENV = "DEIXIS_CHILD_RECORD"
OWNER_ENV = "DEIXIS_CHILD_OWNER"
RECORD_NAME = Path("run") / "children.jsonl"
ACK_ENV = "DEIXIS_CHILD_RECORD_ACK"  # set by the desktop watchdog: the backend tells it the record path first
LAUNCHER = "deixis.session_launcher"
NONE = "-"  # the launcher's record and owner arguments while the record is off
GONE_WAIT_SECONDS = 3.0
CLEAN_SECONDS = 10.0
LINUX = sys.platform.startswith("linux")
ON = (sys.platform == "darwin" or LINUX) and fcntl is not None


class RecordFailed(OSError):
    """The line could not be written: the process must not run unrecorded."""


def record_path(data_dir: Path) -> Path:
    return data_dir / RECORD_NAME


def identity(pid: int) -> str | None:
    """`pid:start` of a live process, or None."""
    info = process_info(pid)
    return f"{pid}:{info.start}" if info else None


def alive(ident: str | None) -> bool:
    """Whether the process `pid:start` still runs with that start time."""
    if not ident:
        return False
    pid, _, start = ident.partition(":")
    info = process_info(int(pid))
    return info is not None and info.start == start


def configure(data_dir: Path) -> Path | None:
    """Switch the record on for this process (the serving backend) and its own children; returns its path (None where
    this layer is off)."""
    if not ON:
        return None
    path = record_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.environ[RECORD_ENV] = str(path)
    os.environ[OWNER_ENV] = identity(os.getpid()) or f"{os.getpid()}:unreadable"
    return path


def target() -> tuple[Path, str] | None:
    """(record path, owner identity) while the record is on, else None."""
    path, owner = os.environ.get(RECORD_ENV), os.environ.get(OWNER_ENV)
    return (Path(path), owner) if path and owner and ON else None


@dataclass(frozen=True)
class Entry:
    pid: int
    start: str
    pgid: int
    sid: int
    owner: str
    kind: str

    @property
    def ident(self) -> str:
        return f"{self.pid}:{self.start}"


def _parse(line: str) -> Entry | None:
    try:
        item = json.loads(line)
        return Entry(int(item["pid"]), str(item["start"]), int(item["pgid"]), int(item["sid"]), str(item["owner"]),
                     str(item.get("kind") or ""))
    except (ValueError, KeyError, TypeError):
        return None


def entries(path: Path) -> list[Entry]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return [entry for entry in map(_parse, text.splitlines()) if entry is not None]


def rewrite(path: Path, keep) -> list[Entry]:
    """Under the lock: keep the lines for which `keep(entry)` is true; returns the lines dropped."""
    dropped: list[Entry] = []
    with open(path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        kept: list[str] = []
        for line in handle.read().splitlines():
            entry = _parse(line)
            if entry is None:
                continue
            if keep(entry):
                kept.append(line)
            else:
                dropped.append(entry)
        handle.seek(0)
        handle.truncate()
        handle.write("".join(f"{line}\n" for line in kept))
        handle.flush()
        os.fsync(handle.fileno())
    return dropped


def register_self(kind: str, path: Path | None = None, owner: str | None = None) -> str | None:
    """Write this process (a session leader) to the record. None when the record is off; RecordFailed when it is on and
    the line could not be written, or the owner is already gone (nobody would stop this process)."""
    if path is None or owner is None:
        found = target()
        if found is None:
            return None
        path, owner = found
    ident = identity(os.getpid())
    if ident is None:
        raise RecordFailed("this process's identity cannot be read")
    line = json.dumps({"pid": os.getpid(), "start": ident.partition(":")[2], "pgid": os.getpgrp(), "sid": os.getsid(0),
                       "owner": owner, "kind": kind})
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise RecordFailed(f"the child record could not be written: {exc}") from exc
    if not alive(owner):
        remove(path, ident)
        raise RecordFailed("the DEIXIS process that started this one has ended")
    return ident


def remove(path: Path, ident: str | None) -> None:
    """Remove one line (a process whose cleanup is done)."""
    if not ident or not path.exists():
        return
    try:
        rewrite(path, lambda e: e.ident != ident)
    except OSError:
        pass


def launcher_argv(argv: list[str], kind: str) -> list[str]:
    """`argv` started through the session launcher (macOS, Linux), which records it while the record is on (module text)."""
    if not ON:
        return list(argv)
    path, owner = target() or (NONE, NONE)
    prefix = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-I"]
    return [*prefix, "-m", LAUNCHER, str(path), owner, kind, "--", *argv]


def leader(pid: int) -> str | None:
    """The identity of a session leader just started (kept by the caller for `stop_group`); None where this is off."""
    return identity(pid) if ON else None


def snapshot() -> dict[int, tuple[int, int, str]]:
    """Every process this user can see: pid -> (ppid, pgid, start), zombies left out. macOS (libproc), Linux (`/proc`,
    start = boot id + `starttime`, as `child_guard.process_info`); empty elsewhere."""
    if LINUX:
        return {pid: (ppid, pgid, start) for pid, (state, ppid, pgid, start) in proc_stats().items() if state != "Z"}
    lib = _libproc()
    if sys.platform != "darwin" or lib is None:
        return {}
    lib.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.proc_listallpids.restype = ctypes.c_int
    count = lib.proc_listallpids(None, 0)
    buffer = (ctypes.c_int * (count + 256))()
    count = lib.proc_listallpids(buffer, ctypes.sizeof(buffer))
    table: dict[int, tuple[int, int, str]] = {}
    info = _BsdInfo()
    for pid in buffer[:max(count, 0)]:
        if pid <= 0:
            continue
        if lib.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info)) != ctypes.sizeof(info) or info.status == 5:
            continue
        table[pid] = (int(info.ppid), int(info.pgid), f"{info.start_sec}:{info.start_usec}")
    return table


def proc_stats() -> dict[int, tuple[str, int, int, str]]:
    """Linux: pid -> (state, ppid, pgid, start) for every `/proc/<pid>/stat` readable now (a process may end mid-scan)."""
    table: dict[int, tuple[str, int, int, str]] = {}
    try:
        names = [entry.name for entry in os.scandir("/proc") if entry.name.isdigit()]
    except OSError:
        return table
    for name in names:
        try:
            # comm can hold spaces and parentheses; the fields after the last ')' start with field 3 (state).
            fields = Path(f"/proc/{name}/stat").read_text().rsplit(")", 1)[1].split()
            table[int(name)] = (fields[0], int(fields[1]), int(fields[2]), linux_start(fields[19]))
        except (OSError, ValueError, IndexError):
            continue
    return table


def members(leader: str, table: dict[int, tuple[int, int, str]] | None = None) -> set[str]:
    """Identities in the group or session led by `leader` (pid:start), other than the leader; empty unless the leader
    is alive with that start time, which is what makes the group and session id its own."""
    if not alive(leader):
        return set()
    pid = int(leader.partition(":")[0])
    found = set()
    for other, (_ppid, pgid, start) in (snapshot() if table is None else table).items():
        if other in (pid, os.getpid()):
            continue
        try:
            sid = os.getsid(other)
        except OSError:
            sid = -1
        if pgid == pid or sid == pid:
            found.add(f"{other}:{start}")
    return found if alive(leader) else set()  # still the same leader after the scan


def kill_identity(ident: str) -> bool:
    """SIGKILL the process `pid:start` only while it is that process (`child_guard.signal_identity`: a pidfd on Linux)."""
    pid, _, start = ident.partition(":")
    if int(pid) == os.getpid():
        return False
    return signal_identity(int(pid), start, signal.SIGKILL)


def wait_gone(idents: set[str], seconds: float = GONE_WAIT_SECONDS) -> set[str]:
    """The identities still alive after up to `seconds`."""
    ends = time.monotonic() + seconds
    left = {i for i in idents if alive(i)}
    while left and time.monotonic() < ends:
        time.sleep(0.02)
        left = {i for i in left if alive(i)}
    return left


def sweep_members(leader: str, seconds: float = CLEAN_SECONDS) -> list[str]:
    """Kill the verified members of `leader`'s group and session, not the leader, scanning again after each round until
    none is left (a member may have started another one meanwhile) or `seconds` have passed."""
    killed: list[str] = []
    ends = time.monotonic() + seconds
    while (found := members(leader)) and time.monotonic() < ends:
        killed += [ident for ident in sorted(found) if kill_identity(ident)]
        wait_gone(found, min(GONE_WAIT_SECONDS, max(0.0, ends - time.monotonic())))
    return killed


def stop_group(pid: int, leader: str | None, sig: int) -> set[str]:
    """Signal the process group of a session leader DEIXIS started (`pid`, whose identity `leader` was read at the
    start). macOS and Linux: only while `leader` is still that process, so the group id is its own; a SIGKILL first kills the
    verified members of its session in other groups. Once it is gone nothing is signalled: the launcher emptied its
    session before it ended, or left its line for the watchdog. Returns the identities found (to wait for). Where this
    layer is off: killpg as before M2. Linux signals each verified member and the leader through a pidfd instead of
    killpg (a group has no pidfd, and asyncio's child watcher may reap the launcher on its own, freeing its pid); macOS
    keeps check-then-killpg."""
    if not ON:
        try:
            os.killpg(pid, sig)
        except OSError:
            pass
        return set()
    if not leader or int(leader.partition(":")[0]) != pid or not alive(leader):
        return set()
    found = members(leader)
    if LINUX:  # no killpg: asyncio may reap the launcher on its own; each verified member and the leader by pidfd
        for ident in sorted(found) + [leader]:
            kill_identity(ident) if sig == signal.SIGKILL else signal_identity(
                int(ident.partition(":")[0]), ident.partition(":")[2], sig)
        return found | {leader}
    if sig == signal.SIGKILL:
        for ident in sorted(found):
            kill_identity(ident)
    if alive(leader):
        try:
            os.killpg(pid, sig)  # the group id is the live leader's pid
        except OSError:
            pass
    return found | {leader}


def sweep(leader: str, seconds: float = CLEAN_SECONDS) -> tuple[list[str], set[str]]:
    """Empty the group and session `leader` leads while it is alive (`sweep_members`, for up to `seconds`), and only
    once a scan finds no member, kill the leader. (signalled, still alive: members a scan still finds, or the leader)"""
    killed = sweep_members(leader, seconds)
    if left := members(leader):
        return killed, left | {leader}  # the leader stays, so its session can still be found and its line stays
    if kill_identity(leader):
        killed.append(leader)
    return killed, wait_gone({leader}, min(GONE_WAIT_SECONDS, max(0.1, seconds)))


def recover(path: Path | None) -> list[str]:
    """At a start, before any child: stop what a backend that is gone left in the record. A line whose recorded leader
    still runs is swept through it; otherwise nothing but the recorded identity is touched (it is dead or another
    process now). A line goes once all of that is verified gone. Lines of a backend that still runs (another DEIXIS on
    this folder) are left alone."""
    if path is None or not path.exists():
        return []
    killed: list[str] = []
    cleaned: set[str] = set()
    for entry in entries(path):
        if alive(entry.owner):
            continue
        signalled, left = sweep(entry.ident)
        killed += signalled
        if not left:
            cleaned.add(entry.ident)
    if cleaned:
        try:
            rewrite(path, lambda e: e.ident not in cleaned)
        except OSError:
            pass
    return killed
