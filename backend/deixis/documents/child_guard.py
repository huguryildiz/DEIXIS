"""Resident-memory guard for an orphaned extraction child (stdlib only; no MuPDF import).

The child waits for a readiness byte before extracting; startup failure exits with
GUARD_EXIT_CODE. All three stdio descriptors are /dev/null and the guard owns its
session, so it cannot keep extraction pipes open. It polls child identity until
normal exit, crash, timeout or SIGKILL, or until the absolute child-alarm deadline
plus DEADLINE_MARGIN_SECONDS. A recorded parent already gone at startup is an orphan.
PDF and arXiv receive their original parent's identity from that parent. OCR and
JATS capture getppid as their first main statement: if the parent died earlier,
PID 1 makes the child look parentless from birth and is recorded as gone. A
different, living subreaper cannot be distinguished from the original parent by
this fallback; it requires identity passed by the launcher to close that case.

Only orphans are killed here. PDF and arXiv have parent-side memory watchers;
OCR and JATS retain their in-child thread, which may stop late while their parent
lives. Unreadable orphan RSS for WATCH_LOST_TURNS consecutive turns fails closed.
Identity is pid plus kernel start time. Immediately before a single SIGKILL the
guard re-reads that identity. macOS has no pidfd: a microsecond-scale window
remains between the final check and kill; nothing else closes that window.

The child's thread checks guard identity between C calls and exits on early loss.
If the guard is killed during a long GIL-holding C call, the child is unguarded
until the next check. A group kill that reaches the guard, Windows (unsupported),
and a child that dies before readiness are not covered by orphan memory evidence.
"""
from __future__ import annotations

import ctypes
import ctypes.util
from dataclasses import dataclass
import functools
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

WATCH_INTERVAL_SECONDS = 0.05
WATCH_LOST_TURNS = 20
GUARD_EXIT_CODE = 6
READY_TIMEOUT_SECONDS = 5.0
DEADLINE_MARGIN_SECONDS = 2.0


@functools.lru_cache(maxsize=1)
def _libproc():
    try:
        lib = ctypes.CDLL(ctypes.util.find_library("proc") or "libproc.dylib", use_errno=True)
        lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        lib.proc_pidinfo.restype = ctypes.c_int
        return lib
    except (OSError, AttributeError):
        return None


class _BsdInfo(ctypes.Structure):
    # SDK sys/proc_info.h, struct proc_bsdinfo (136 bytes on macOS arm64).
    _fields_ = [(name, ctypes.c_uint32) for name in (
        "flags", "status", "xstatus", "pid", "ppid", "uid", "gid", "ruid", "rgid", "svuid", "svgid", "reserved")]
    _fields_ += [("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32)]
    _fields_ += [(name, ctypes.c_uint32) for name in ("nfiles", "pgid", "jobc", "tdev", "tpgid", "nice")]
    _fields_ += [("start_sec", ctypes.c_uint64), ("start_usec", ctypes.c_uint64)]


@dataclass(frozen=True)
class ProcessInfo:
    start: str
    ppid: int


def process_info(pid: int) -> ProcessInfo | None:
    if sys.platform == "darwin":
        lib = _libproc()
        if lib is None:
            return None
        info = _BsdInfo()
        size = lib.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
        if size != ctypes.sizeof(info) or info.status == 5:  # SZOMB: dead even before reaping
            return None
        return ProcessInfo(f"{info.start_sec}:{info.start_usec}", int(info.ppid))
    if sys.platform.startswith("linux"):
        try:
            # comm can contain spaces and parentheses; fields after the final ')' begin with field 3.
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            return None if fields[0] == "Z" else ProcessInfo(fields[19], int(fields[1]))
        except (OSError, ValueError, IndexError):
            return None
    return None


def _resident_bytes(pid: int) -> int | None:
    if sys.platform == "darwin":
        lib = _libproc()
        if lib is None:
            return None
        info = (ctypes.c_uint64 * 12)()
        size = lib.proc_pidinfo(pid, 4, 0, ctypes.byref(info), ctypes.sizeof(info))
        return int(info[1]) if size == ctypes.sizeof(info) else None
    try:
        return int(Path(f"/proc/{pid}/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return None


def parent_env(env: dict[str, str] | None) -> dict[str, str]:
    info = process_info(os.getpid())
    return dict(os.environ if env is None else env) | {"DEIXIS_PARENT_PID": str(os.getpid()),
                                                      "DEIXIS_PARENT_START": info.start if info else "unreadable"}


def original_parent(fallback_pid: int) -> tuple[int, str]:
    pid = int(os.environ.get("DEIXIS_PARENT_PID", fallback_pid))
    start = os.environ.get("DEIXIS_PARENT_START")
    info = process_info(pid) if start is None else None
    return pid, start if start is not None else info.start if info and pid > 1 else "gone"


@dataclass
class Guard:
    child_pid: int
    child_start: str
    parent_pid: int
    parent_start: str
    limit: int
    deadline: float
    unread: int = 0
    last_under_at: float | None = None

    def turn(self, now: float, reader=process_info, resident=_resident_bytes) -> tuple[str, int | None]:
        child = reader(self.child_pid)
        if child is None or child.start != self.child_start or now >= self.deadline:
            return "end", None
        parent = reader(self.parent_pid)
        if parent is not None and parent.start == self.parent_start and child.ppid == self.parent_pid:
            self.unread = 0
            return "wait", None
        rss = resident(self.child_pid)
        self.unread = 0 if rss is not None else self.unread + 1
        if rss is not None and rss <= self.limit:
            self.last_under_at = now
        return ("kill" if (rss is not None and rss > self.limit) or self.unread >= WATCH_LOST_TURNS else "wait"), rss

    def signal_once(self, reader=process_info, kill=os.kill) -> bool:
        child = reader(self.child_pid)
        if child is None or child.start != self.child_start:
            return False
        try:
            kill(self.child_pid, signal.SIGKILL)
            return True
        except ProcessLookupError:
            return False


def start_guard(limit: int, lifetime: int, parent: tuple[int, str]) -> tuple[subprocess.Popen, str]:
    child = process_info(os.getpid())
    if child is None:
        raise RuntimeError("child identity unreadable")
    read_fd, write_fd = os.pipe()
    proc = None
    try:
        argv = [sys.executable, "-m", "deixis.documents.child_guard", str(os.getpid()), child.start,
                str(parent[0]), parent[1], str(limit), str(time.monotonic() + lifetime + DEADLINE_MARGIN_SECONDS), str(write_fd)]
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True, pass_fds=(write_fd,))
        os.close(write_fd)
        write_fd = -1
        if not select.select([read_fd], [], [], READY_TIMEOUT_SECONDS)[0] or os.read(read_fd, 1) != b"R":
            raise RuntimeError("guard did not report ready")
        identity = process_info(proc.pid)
        if identity is None or proc.poll() is not None:
            raise RuntimeError("guard ended at startup")
        return proc, identity.start
    except BaseException:
        if proc is not None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            proc.wait()
        raise
    finally:
        os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)


def main() -> None:
    guard = Guard(int(sys.argv[1]), sys.argv[2], int(sys.argv[3]), sys.argv[4], int(sys.argv[5]), float(sys.argv[6]))
    log_path = os.environ.get("DEIXIS_CHILD_GUARD_LOG")  # test evidence only; read solely in this guard process

    def record(action: str, rss: int | None = None) -> None:
        if log_path:
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"action": action, "pid": guard.child_pid, "guard_pid": os.getpid(),
                                         "resident_bytes": rss, "limit": guard.limit, "monotonic": time.monotonic(),
                                         "last_under_at": guard.last_under_at,
                                         "stdio_devnull": all(os.fstat(fd).st_rdev == os.stat(os.devnull).st_rdev for fd in (0, 1, 2))}) + "\n")
                handle.flush()

    child = process_info(guard.child_pid)
    if child is None or child.start != guard.child_start:
        return
    record("ready", _resident_bytes(guard.child_pid))
    guard.last_under_at = time.monotonic()
    ready_fd = int(sys.argv[7])
    os.write(ready_fd, b"R")
    os.close(ready_fd)
    while True:
        action, rss = guard.turn(time.monotonic())
        if action == "end":
            return
        if action == "kill":
            record("kill", rss)  # evidence written before signalling; a failed log write fails closed via guard-loss check
            guard.signal_once()
            return
        time.sleep(WATCH_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
