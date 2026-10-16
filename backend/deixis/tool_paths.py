"""Where the command-line tools DEIXIS runs are on this computer (pre-P10 A3).

An app started from the Finder, the Start menu or a desktop launcher gets a short PATH (on macOS only
/usr/bin:/bin:/usr/sbin:/sbin), so `shutil.which` misses tools installed with Homebrew, npm, uv or nvm. `find_tool`
looks in this order: the frozen bundle's own bin/ folder, the process PATH, the places installers usually put tools,
and last the PATH of the person's login shell. A tool's child process gets a PATH with the tool's folder and node's
folder on it (`child_path`), so an npm launcher's `#!/usr/bin/env node` finds node too.

`command_for` turns what `find_tool` found into the argv that starts the tool (pre-P10 A4). On Windows a batch file
(`codex.cmd`, `claude.cmd`) is never run: `cmd.exe` would parse the arguments and a path with `&`, `%` or `^` in it
would run as commands. The tool's native `.exe` is used, else `node.exe` runs the script the npm launcher points at,
else the install type is reported as not supported.
"""

from __future__ import annotations

import asyncio
import os
import platform
import re
import select
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from deixis.paths import is_frozen, resource_root

SHELL_TIMEOUT = 3.0
SHELL_OUTPUT_LIMIT = 64 * 1024
SHELLS = ("bash", "zsh", "sh")  # fish and nushell print PATH differently; they are never asked
# The PATH is printed between two markers and only that part is read: a greeting from .zshrc cannot mix into it.
SHELL_COMMAND = "printf '__DEIXIS_PATH__%s__END__' \"$PATH\""
SHELL_PATH = re.compile(rb"__DEIXIS_PATH__((?:(?!__DEIXIS_PATH__).)*?)__END__", re.S)  # the last start marker before an end

# What the shell is handed: no key, token or proxy setting of DEIXIS's environment reaches .zshrc and the scripts it runs.
SHELL_VARIABLES = ("HOME", "USER", "LOGNAME", "SHELL", "LANG", "TMPDIR", "TERM")

_shell_lock = threading.Lock()
_shell_path: list[str] | None = None  # read once per process
_warm_lock = threading.Lock()  # never held while the shell runs, so the event loop never waits on it
_warming = False


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


def _shell_env() -> dict[str, str]:
    """A minimal environment for the login shell, built here and not by `child_env`, which would look for node and so
    come back into `find_tool`; PATH is the process's own, as the shell would start with it."""
    env = {k: v for k, v in os.environ.items() if k in SHELL_VARIABLES or k.startswith("LC_")}
    env["PATH"] = os.environ.get("PATH", "")
    return env


def _read_shell_path() -> list[str]:
    shell = os.environ.get("SHELL") or ""
    if sys.platform == "win32" or Path(shell).name not in SHELLS or not os.path.isabs(shell):
        return []
    try:
        # Interactive and login, so both .zprofile and .zshrc (where nvm usually sits) run; a new session keeps the
        # shell away from the terminal DEIXIS may have been started from.
        proc = subprocess.Popen([shell, "-i", "-l", "-c", SHELL_COMMAND], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True,
                                env=_shell_env())
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


def _on_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def login_shell_path() -> list[str]:
    """The login shell's PATH folders, read at most once per process; empty when it cannot be read in time.

    The first read takes up to SHELL_TIMEOUT. On the event loop it is never waited for: the read starts in a thread and
    this call answers as if the shell had no more folders; async code calls `find_tool` with `asyncio.to_thread`, which
    waits in the worker, so the answer is complete from the first call there."""
    global _shell_path, _warming
    if _shell_path is not None:
        return _shell_path
    if _on_event_loop():
        with _warm_lock:
            start, _warming = not _warming, True
        if start:
            threading.Thread(target=login_shell_path, daemon=True).start()
        return []
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


# --- starting a tool on Windows (A4) ------------------------------------------------------------------------------

NATIVE = (".exe", ".com")
# npm's Windows launcher ends in `"%_prog%" "%dp0%\node_modules\...\tool.js" %*` (older ones write `%~dp0`).
SHIM_ENTRY = re.compile(r'"%(?:~dp0|dp0%)\\?([^"%]+\.[cm]?js)"', re.I)
# The native binary an npm package ships next to its launcher script, by tool: glob patterns under the launcher's folder.
NATIVE_BINARIES = {"codex": ("node_modules/@openai/codex/vendor/*/codex/codex.exe",
                             "node_modules/@openai/codex/node_modules/@openai/codex-*/vendor/*/codex/codex.exe",
                             "node_modules/@openai/codex-*/vendor/*/codex/codex.exe")}
# Tools whose launcher is never started through node: the Claude Agent SDK takes one executable and refuses a batch file.
NATIVE_ONLY = frozenset({"claude"})
DISPLAY_NAMES = {"codex": "Codex CLI", "claude": "Claude Code", "gemini": "Gemini CLI", "copilot": "GitHub Copilot CLI"}


@dataclass(frozen=True)
class CliCommand:
    """`found` is what find_tool returned; `argv` the words that start the tool (empty when it cannot be started
    safely); `problem` says why in plain words when the tool is found but argv is empty."""
    found: str | None
    argv: list[str] = field(default_factory=list)
    problem: str | None = None


def _arch_first(paths: list[Path]) -> list[Path]:
    machine = platform.machine().lower()
    triple = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
    return sorted(paths, key=lambda p: triple not in str(p))


def _unsupported(name: str) -> str:
    shown = DISPLAY_NAMES.get(name, name)
    if name in NATIVE_ONLY:
        return (f"This {shown} install type isn't supported on Windows (an npm install is a batch launcher). "
                f"Install {shown} with its official native installer instead.")
    return f"This {shown} install type isn't supported on Windows. Reinstall it with npm, or use its native Windows build."


def _windows_command(name: str, found: str) -> CliCommand:
    path = Path(found)
    if path.suffix.lower() in NATIVE:
        return CliCommand(found, [found])
    problem = CliCommand(found, [], _unsupported(name))
    if name in NATIVE_ONLY or path.suffix.lower() not in (".cmd", ".bat"):
        return problem
    folder = path.parent
    for pattern in NATIVE_BINARIES.get(name, ()):
        try:
            hits = _arch_first([p for p in folder.glob(pattern) if p.is_file()])
        except OSError:
            hits = []
        if hits:
            return CliCommand(found, [str(hits[0])])
    try:
        shim = path.read_text(encoding="utf-8", errors="replace")[:64 * 1024]
    except OSError:
        return problem
    entries = SHIM_ENTRY.findall(shim)
    entry = folder.joinpath(*entries[-1].split("\\")) if entries else None
    if entry is None or not entry.is_file():
        return problem
    node = folder / "node.exe"
    node = str(node) if node.is_file() else find_tool("node")
    if not node or Path(node).suffix.lower() not in NATIVE or not Path(node).is_file():
        return problem
    return CliCommand(found, [node, str(entry)])


def command_for(name: str, found: str | None) -> CliCommand:
    """The argv that starts the tool `name` found at `found` (what `find_tool` returned)."""
    if not found:
        return CliCommand(None)
    if sys.platform != "win32":
        return CliCommand(found, [found])
    return _windows_command(name, found)
