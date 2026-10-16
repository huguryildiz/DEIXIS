"""Where the command-line tools DEIXIS runs are on this computer (pre-P10 A3).

An app started from the Finder, the Start menu or a desktop launcher gets a short PATH (on macOS only
/usr/bin:/bin:/usr/sbin:/sbin), so `shutil.which` misses tools installed with Homebrew, npm, uv or nvm. `find_tool`
looks in this order: the frozen bundle's own bin/ folder, the process PATH, the places installers usually put tools,
and last the PATH of the person's login shell. A tool's child process gets a PATH with the tool's folder and node's
folder on it (`child_path`), so an npm launcher's `#!/usr/bin/env node` finds node too.
"""

from __future__ import annotations

import os
import re
import select
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from deixis.paths import is_frozen, resource_root

SHELL_TIMEOUT = 3.0
SHELL_OUTPUT_LIMIT = 64 * 1024
SHELLS = ("bash", "zsh", "sh")  # fish and nushell print PATH differently; they are never asked
# The PATH is printed between two markers and only that part is read: a greeting from .zshrc cannot mix into it.
SHELL_COMMAND = "printf '__DEIXIS_PATH__%s__END__' \"$PATH\""
SHELL_PATH = re.compile(rb"__DEIXIS_PATH__((?:(?!__DEIXIS_PATH__).)*?)__END__", re.S)  # the last start marker before an end

_shell_lock = threading.Lock()
_shell_path: list[str] | None = None  # read once per process


def _newest(pattern_root: Path, pattern: str) -> list[str]:
    """The matching folders, newest version first (nvm keeps one folder per Node version)."""
    def version(path: Path) -> tuple[int, ...]:
        return tuple(int(n) for n in re.findall(r"\d+", path.parent.name))
    try:
        return [str(p) for p in sorted(pattern_root.glob(pattern), key=version, reverse=True)]
    except OSError:
        return []


def known_places() -> list[str]:
    """Folders installers usually put tools in, whether or not they exist."""
    home = Path.home()
    places = [str(home / ".local" / "bin"), str(home / ".npm-global" / "bin"), str(home / ".volta" / "bin")]
    nvm = Path(os.environ.get("NVM_DIR") or home / ".nvm")
    places += _newest(nvm / "versions" / "node", "*/bin")
    fnm = os.environ.get("FNM_DIR")
    if sys.platform == "win32":
        appdata, local = os.environ.get("APPDATA"), os.environ.get("LOCALAPPDATA")
        places += [str(Path(appdata) / "npm")] if appdata else []
        places += [str(Path(local) / "Programs")] if local else []
        fnm_root = Path(fnm) if fnm else Path(appdata) / "fnm" if appdata else None
        places += [str(fnm_root / "aliases" / "default")] if fnm_root else []
    else:
        places += ["/opt/homebrew/bin", "/usr/local/bin"]
        fnm_root = Path(fnm) if fnm else (home / "Library" / "Application Support" / "fnm" if sys.platform == "darwin"
                                          else home / ".local" / "share" / "fnm")
        places.append(str(fnm_root / "aliases" / "default" / "bin"))
    return places


def _stop(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _read_shell_path() -> list[str]:
    shell = os.environ.get("SHELL") or ""
    if sys.platform == "win32" or Path(shell).name not in SHELLS or not os.path.isabs(shell):
        return []
    try:
        # Interactive and login, so both .zprofile and .zshrc (where nvm usually sits) run; a new session keeps the
        # shell away from the terminal DEIXIS may have been started from.
        proc = subprocess.Popen([shell, "-i", "-l", "-c", SHELL_COMMAND], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return []
    data = b""
    deadline = time.monotonic() + SHELL_TIMEOUT
    try:
        fd = proc.stdout.fileno()
        while len(data) < SHELL_OUTPUT_LIMIT and not SHELL_PATH.search(data):
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
                break
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            data += chunk
    except (OSError, ValueError):
        return []
    finally:
        _stop(proc)
        proc.stdout.close()
        try:
            proc.wait(1)
        except subprocess.TimeoutExpired:
            pass
    found = SHELL_PATH.findall(data[:SHELL_OUTPUT_LIMIT])
    return [d for d in found[-1].decode("utf-8", "replace").split(os.pathsep) if os.path.isabs(d)] if found else []


def login_shell_path() -> list[str]:
    """The login shell's PATH folders, read at most once per process; empty when it cannot be read in time."""
    global _shell_path
    with _shell_lock:
        if _shell_path is None:
            _shell_path = _read_shell_path()
        return _shell_path


def _which(name: str, folders: list[str]) -> str | None:
    # shutil.which honours PATHEXT on Windows and returns the full path of codex.cmd, uv.exe and the like.
    return shutil.which(name, path=os.pathsep.join(folders)) if folders else None


def find_tool(name: str) -> str | None:
    """The full path of the command-line tool `name`, or None."""
    if is_frozen():
        if found := _which(name, [str(resource_root() / "bin")]):
            return found
    if found := shutil.which(name):
        return found
    if found := _which(name, known_places()):
        return found
    return _which(name, login_shell_path())


def child_path(tool: str | None = None, base: str | None = None) -> str:
    """A PATH for a tool's child process: the tool's folder, node's folder, then `base` (the process PATH)."""
    base = os.environ.get("PATH", "") if base is None else base
    node = find_tool("node")
    folders = [str(Path(p).parent) for p in (tool, node) if p]
    return os.pathsep.join(dict.fromkeys([*folders, *(d for d in base.split(os.pathsep) if d)]))
