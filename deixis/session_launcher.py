"""Leader of a session DEIXIS starts for an outside program (P10 M2); see `tools/child_record.py`.

    <python or deixis-backend> -m deixis.session_launcher RECORD OWNER KIND -- PROGRAM ARGS...

Started with `start_new_session`, so this process leads the new session and process group. While the record is on
(RECORD and OWNER are not `-`) it writes its own line to the child record first; if that fails, or the owner (the
backend) is already gone, PROGRAM never runs, the exit code is RECORD_FAILED and stderr starts with REFUSED. Then it starts PROGRAM in its group and session with the standard streams, other inherited file
descriptors and environment it was given (less the packaged app's own `_PYI_*` variables), and lets go of the streams
so only PROGRAM holds the pipes. Signals sent to the group reach PROGRAM; this process ignores TERM, INT and HUP while
PROGRAM runs. Every WATCH_SECONDS it checks that the owner still runs; if the owner has died, it kills PROGRAM and
everything else in its session. PROGRAM's end does not end the ownership: this process stays the session's leader and kills every
process still in the session or group, again until none is left; only then is the line removed. If something is still
there after CLEAN_SECONDS (a process it may not signal), the line stays for the watchdog and the next start. Then this
process ends as PROGRAM did (its exit code, or the same signal).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

RECORD_FAILED = 125
REFUSED = "DEIXIS did not start "
CANCEL = signal.SIGUSR1  # Linux `child_record.stop_group`: start nothing more, empty the session, then end
CLEAN_SECONDS = 10.0
WATCH_SECONDS = 0.5


def program_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith(("_PYI_", "_MEIPASS"))}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 5 or argv[3] != "--":
        print("usage: session_launcher RECORD OWNER KIND -- PROGRAM ARGS...", file=sys.stderr)
        return 2
    record, owner, kind, program = Path(argv[0]), argv[1], argv[2], argv[4:]
    cancelled: list[bool] = []
    signal.signal(CANCEL, lambda *_: cancelled.append(True))  # before this line its default action ends this process
    from deixis.tools import child_record

    recorded = child_record.NONE not in (argv[0], owner)
    try:
        ident = child_record.register_self(kind, record, owner) if recorded else child_record.identity(os.getpid())
    except child_record.RecordFailed as exc:
        print(f"{REFUSED}{Path(program[0]).name}: {exc}", file=sys.stderr)
        return RECORD_FAILED
    if ident is None:  # nothing could stop its session by identity (Linux without a boot id)
        print(f"{REFUSED}{Path(program[0]).name}: this process's identity cannot be read", file=sys.stderr)
        return RECORD_FAILED
    if cancelled:  # cancelled before PROGRAM started: it never runs
        if recorded:
            child_record.remove(record, ident)
        return 128 + signal.SIGKILL
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda *_: None)  # a handler, not SIG_IGN: PROGRAM starts with the default action
    try:
        child = subprocess.Popen(program, env=program_env(), close_fds=False)
    except OSError as exc:
        if recorded:
            child_record.remove(record, ident)
        print(f"{program[0]}: {exc}", file=sys.stderr)
        return 127
    null = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(null, fd)  # PROGRAM alone holds the pipes, so its caller sees EOF when PROGRAM is done
    os.closerange(3, 1 << 16)  # the inherited locks and pipes stay with PROGRAM only
    while True:
        try:
            code = child.wait(WATCH_SECONDS)
            break
        except subprocess.TimeoutExpired:
            if cancelled or (recorded and not child_record.alive(owner)):
                child_record.sweep_members(ident)  # cancelled, or the owner is gone: nobody else will stop this session
        except InterruptedError:
            continue
    child_record.sweep_members(ident, CLEAN_SECONDS)  # until a scan finds none
    if recorded and not child_record.members(ident):
        child_record.remove(record, ident)
    if code < 0:
        if -code not in (signal.SIGKILL, signal.SIGSTOP):  # those two have no handler to reset (EINVAL)
            signal.signal(-code, signal.SIG_DFL)
        os.kill(os.getpid(), -code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
