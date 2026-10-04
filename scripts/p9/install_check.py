#!/usr/bin/env python3
"""P9 H1: clean install and start audit (rows I01 to I05 and I07; I08 is recorded as not measured).

Exports a commit with `git archive` (not the working tree), runs the README's own steps there (`uv sync`,
`npm ci`, `npm run build`, `serve --no-browser`) with a separate data directory, port, caches and an isolated
keychain, and records what a new user can meet: the app starts and serves its UI, a busy port, a missing UI build and
an unwritable data directory each end with an understandable message, and nothing is left running afterwards.

No model call, no provider call. The live service on port 8765, the live data directory and the real keychain are
never touched. Standard library only; runs on Python 3.9 or newer, arm64 macOS only (plan section 2).

    python3 scripts/p9/install_check.py --port 8871
    python3 scripts/p9/install_check.py --self-test

Exit codes: 0 every mandatory row passed, 1 a row failed, 2 refused (environment, port, directory), 4 keychain
isolation failed. Raw output goes to --out-dir (default .local/p9-h1/<stamp>/, ignored by Git).
"""

from __future__ import annotations

import argparse
import datetime
import getpass
import hashlib
import json
import os
import posixpath
import platform
import plistlib
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
CHROME_APP = Path("/Applications/Google Chrome.app")
LIVE_DATA_DIR = Path.home() / "Library" / "Application Support" / "DEIXIS"
REFUSED_PORTS = {8765} | set(range(8858, 8865))
KEYRING_NULL = "keyring.backends.null.Keyring"
MODEL_CLIS = ("codex", "claude", "gemini")
BANNED_COMMANDS = ("codex", "claude", "gemini", "tesseract")
SHIM_TOOLS = ("uv", "node", "npm", "npx")
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
LOOPBACK = ("127.0.0.1", "::1", "localhost")
LOCK_FILES = ("uv.lock", "apps/web/package-lock.json")
INSTALL_PROXY_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
                       "SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS")
OVERLAY_SKIP_PARTS = (".local", "node_modules", ".venv", "dist")
OVERLAY_SKIP_PATHS = (".vscode", "TODO.md", "scripts/local_index.py")
LIMITS = {"uv_sync": 1800, "npm_ci": 1800, "npm_build": 900, "ready": 60, "stop": 15, "other": 30, "shell": 90}
MANDATORY = ("I01", "I02", "I03", "I04", "I05", "I07", "keyring", "cleanup")
ROW_ORDER = ("I01", "I02", "I03", "I04", "I05", "I07", "I08", "keyring", "cleanup")
TRACEBACK = "Traceback (most recent call last)"
I05_CAUSE = re.compile(r"(?i)not writable|permission denied|read-only|not a folder")
I07_REASON = re.compile(r"(?i)cli not found|api key|not implemented in this version")

# What the keyring stages run. They never read or write a secret: stage 1 and the control only ask which backend is
# chosen, stage 2 loads the settings with the isolation variable set (the null backend has nothing to read).
KEYRING_STAGE1 = (
    "import sys, json, keyring\n"
    "b = keyring.get_keyring()\n"
    "print(json.dumps({'cls': type(b).__module__ + '.' + type(b).__name__, 'priority': b.priority,\n"
    "                  'macos_modules': sorted(m for m in sys.modules if m.startswith('keyring.backends.macOS'))}))\n"
)
KEYRING_STAGE2 = (
    "import sys, json\n"
    "import deixis.config as config, deixis.credentials as credentials\n"
    "config.load_settings()\n"
    "print(json.dumps({'keychain_name': credentials.keychain_name(),\n"
    "                  'macos_modules': sorted(m for m in sys.modules if m.startswith('keyring.backends.macOS'))}))\n"
)
KEYRING_CONTROL = (
    "import json, keyring\n"
    "b = keyring.get_keyring()\n"
    "print(json.dumps({'cls': type(b).__module__ + '.' + type(b).__name__, 'priority': b.priority}))\n"
)
KEYRING_ALTERNATIVE = (
    "The PYTHON_KEYRING_BACKEND isolation did not hold on this keyring version. Use a separate macOS user account, or "
    "redirect HOME to an empty directory (which also makes uv download its own Python), and run the check there."
)


CHROME_NAMES = r"(?:google chrome for testing|google chrome|chromium|chrome|chrome-headless-shell|headless_shell)"
CHROME_EXECUTABLE = re.compile(
    r"^/(?:(?![^/]*\.app/)[^ /]+/)*(?:(?:google chrome for testing|google chrome|chromium|chrome)\.app/(?:(?![^/]*\.app/)[^ /]+/)*)?" + CHROME_NAMES + "$")


def comm_of(pid: int) -> Optional[str]:
    """The real executable path of a pid (ps `comm`), which unlike the flattened command line has no argument text in it."""
    try:
        done = subprocess.run(["ps", "-ww", "-o", "comm=", "-p", str(pid)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              universal_newlines=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None


def is_chrome_with_profile(row: Dict[str, Any], profile: str) -> bool:
    """A process whose real executable (ps comm) is a Chrome binary, started as that executable, with a --user-data-dir flag
    under this harness's profile prefix. Argument text is only read after the executable is verified; ps cannot give argv
    boundaries, so a single argument that itself contains the flag text stays indistinguishable (a recorded limit)."""
    cmd = row["cmd"]
    exe = comm_of(row["pid"]) if "--user-data-dir=" + profile in cmd else None
    if not exe or not CHROME_EXECUTABLE.match(exe.lower()) or not (cmd == exe or cmd.startswith(exe + " ")):
        return False
    flags = [p[len("user-data-dir="):] for p in cmd.split(" --")[1:] if p.startswith("user-data-dir=")]
    return bool(flags) and all(" " not in value and ".." not in value.split("/") and posixpath.normpath(value).startswith(profile) for value in flags)


class Aborted(Exception):
    """SIGINT or SIGTERM reached the harness; `finally` blocks clean up."""


# ---------------------------------------------------------------- pure checks (also run by --self-test)


def port_refusal(port: int) -> Optional[str]:
    if port in REFUSED_PORTS:
        return "port %d belongs to a live service (8765, 8858 to 8864)" % port
    if port < 1024:
        return "port %d is below 1024" % port
    if port > 65535:
        return "port %d is not a port" % port
    return None


def _version_tuple(text: str) -> Tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text)[:3])


def satisfies(version: str, spec: str) -> bool:
    """Only the forms used in package.json engines: space-separated `>=X.Y.Z` and `<X[.Y.Z]` terms."""
    def padded(text: str) -> Tuple[int, ...]:
        parts = _version_tuple(text)
        return parts + (0,) * (3 - len(parts))

    have = padded(version.lstrip("v"))
    for term in spec.split():
        match = re.fullmatch(r"(>=|<=|>|<|=)?(\d+(?:\.\d+){0,2})", term)
        if not match:
            raise ValueError("unsupported engines term: %r" % term)
        op, want = match.group(1) or "=", padded(match.group(2))
        holds = {">=": have >= want, ">": have > want, "<=": have <= want, "<": have < want, "=": have == want}[op]
        if not holds:
            return False
    return True


def cmd_mentions_dir(command: str, directory: str) -> bool:
    """True when `directory` occurs as a whole path: `run1` does not match inside `run10` or `/x/run1`."""
    start = 0
    while True:
        at = command.find(directory, start)
        if at < 0:
            return False
        before = command[at - 1] if at > 0 else " "
        after = command[at + len(directory)] if at + len(directory) < len(command) else " "
        if before in " =:'\"" and after in "/ :'\"":
            return True
        start = at + 1


def decide_keyring_stage1(info: Dict[str, Any]) -> Tuple[bool, str]:
    if info.get("cls") != KEYRING_NULL:
        return False, "keyring backend is %s, not the null backend" % info.get("cls")
    if info.get("macos_modules"):
        return False, "a macOS keyring module was imported: %s" % ", ".join(info["macos_modules"])
    return True, "null backend, no macOS keyring module imported"


def check_i04(stdout: str, health_status: Optional[int]) -> Tuple[bool, List[str]]:
    reasons = []
    if "UI build not found (apps/web/dist)" not in stdout:
        reasons.append("the 'UI build not found (apps/web/dist)' warning line is missing")
    if health_status != 200:
        reasons.append("/api/health did not answer 200 (got %s)" % health_status)
    return not reasons, reasons


def check_port_busy(code: Optional[int], stderr: str, combined: str, port: int) -> Tuple[bool, List[str]]:
    reasons = []
    if code != 2:
        reasons.append("exit code %s, not 2" % code)
    if "Port %d is in use" % port not in stderr:
        reasons.append("stderr has no 'Port %d is in use'" % port)
    if "Application startup" in combined:
        reasons.append("the process reached application startup")
    return not reasons, reasons


def check_i05_message(output: str, directory: str) -> Tuple[bool, List[str]]:
    reasons = []
    if TRACEBACK in output:
        reasons.append("output contains a traceback")
    if not any(directory in line and I05_CAUSE.search(line) for line in output.splitlines()):
        reasons.append("no line names both the directory and a cause")
    return not reasons, reasons


def check_i07(connections: Dict[str, Any], audit_names: Iterable[str]) -> Tuple[bool, List[str]]:
    reasons = []
    models = connections.get("models") or {}
    for name in ("codex", "claude", "gemini", "deepseek"):
        if name not in models:
            reasons.append("%s is missing from models" % name)
    for name, entry in sorted(models.items()):
        reason = entry.get("reason")
        if entry.get("ready") is not False:
            reasons.append("%s: ready is %r, not false" % (name, entry.get("ready")))
        if not isinstance(reason, str) or not reason.strip():
            reasons.append("%s: reason is empty" % name)
        elif not I07_REASON.search(reason):
            reasons.append("%s: unexpected reason %r" % (name, reason[:80]))
        if entry.get("cli_version"):
            reasons.append("%s: a CLI answered (cli_version %r)" % (name, entry["cli_version"]))
    for name in ("codex", "claude", "gemini"):
        if name in models and models[name].get("installed") is not False:
            reasons.append("%s: installed is %r, not false" % (name, models[name].get("installed")))
    for name in ("gemini", "deepseek", "qwen", "kimi", "mistral"):
        if name in models and models[name].get("key_configured") is not False:
            reasons.append("%s: key_configured is %r, not false" % (name, models[name].get("key_configured")))
    for command in sorted(set(audit_names) & set(BANNED_COMMANDS)):
        reasons.append("a %s process was in the audit set" % command)
    return not reasons, reasons


def tree_gone(recorded: Dict[int, str], lookup: Callable[[int], Optional[str]]) -> Tuple[bool, List[str]]:
    """`lookup(pid)` gives the pid's current command line or None when it does not exist."""
    alive = []
    for pid, command in sorted(recorded.items()):
        now = lookup(pid)
        if now is not None and now == command:
            alive.append("%d %s" % (pid, command[:100]))
    return not alive, alive


def launch_env_problems(env: Dict[str, str], cwd: Path, work: Path, export: Path, control: bool = False) -> List[str]:
    """The launcher refuses to start unless all of this holds (fail closed)."""
    problems = []
    for key in ("DEIXIS_DATA_DIR", "DEIXIS_CODEX_HOME"):
        value = env.get(key)
        if not value:
            problems.append("%s is not set (the live library would be the fallback)" % key)
        elif not _inside(Path(value), work):
            problems.append("%s=%s is not inside the work directory" % (key, value))
    if not control and env.get("PYTHON_KEYRING_BACKEND") != KEYRING_NULL:
        problems.append("PYTHON_KEYRING_BACKEND is not the null backend")
    for key in ("DEIXIS_HOST", "DEIXIS_PORT"):
        if key in env:
            problems.append("%s must not be passed" % key)
    if env.get("PYTHONPATH") != str(export / "backend"):
        problems.append("PYTHONPATH is not the export's absolute backend directory")
    if Path(cwd).resolve() != export:
        problems.append("cwd is not the export")
    return problems


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(parent)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- system helpers


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(str(path), "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def ps_table() -> List[Dict[str, Any]]:
    """Live processes (zombies left out); macOS `ps` has no usable session column, so the group is pgid."""
    done = subprocess.run(["ps", "-axww", "-o", "pid=,ppid=,pgid=,stat=,command="], stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, universal_newlines=True, timeout=15)
    rows = []
    for line in done.stdout.splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 4 and all(p.isdigit() for p in parts[:3]) and not parts[3].startswith("Z"):
            rows.append({"pid": int(parts[0]), "ppid": int(parts[1]), "pgid": int(parts[2]),
                         "cmd": parts[4] if len(parts) > 4 else ""})
    return rows


def command_of(pid: int) -> Optional[str]:
    """The current command line of a pid, None when it does not exist or is a zombie."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        pass
    done = subprocess.run(["ps", "-ww", "-o", "stat=,command=", "-p", str(pid)], stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, universal_newlines=True, timeout=15)
    parts = done.stdout.strip().split(None, 1)
    if len(parts) < 2 or parts[0].startswith("Z"):
        return None
    return parts[1]


def command_names(commands: Iterable[str]) -> set:
    """Program names of command lines: argv[0], and the script behind an interpreter (`node .../claude` is a claude)."""
    names = set()
    for command in commands:
        tokens = command.split()
        if not tokens:
            continue
        names.add(os.path.basename(tokens[0]))
        if os.path.basename(tokens[0]) in ("node", "python", "python3", "sh", "bash", "zsh", "env"):
            script = next((t for t in tokens[1:] if not t.startswith("-")), None)
            if script:
                names.add(os.path.basename(script))
    return names


def own_exclusions(table: List[Dict[str, Any]]) -> set:
    """The harness itself, its ancestors and its own process group are never audited or signalled."""
    parents = {r["pid"]: r["ppid"] for r in table}
    excluded = {os.getpid()}
    pid = os.getpid()
    while pid in parents and parents[pid] not in excluded and parents[pid] > 0:
        pid = parents[pid]
        excluded.add(pid)
    own_group = os.getpgrp()
    excluded.update(r["pid"] for r in table if r["pgid"] == own_group)
    return excluded


def descendants(table: List[Dict[str, Any]], root: int) -> List[Dict[str, Any]]:
    kids: Dict[int, List[Dict[str, Any]]] = {}
    for row in table:
        kids.setdefault(row["ppid"], []).append(row)
    found, queue = [], [root]
    by_pid = {r["pid"]: r for r in table}
    if root in by_pid:
        found.append(by_pid[root])
    while queue:
        for child in kids.get(queue.pop(), []):
            found.append(child)
            queue.append(child["pid"])
    return found


def lsof_sockets(pids: List[int]) -> Dict[str, Any]:
    """Internet sockets of the given pids; non-loopback remote addresses and wildcard listeners are findings."""
    if not pids:
        return {"measured": True, "sockets": [], "findings": []}
    try:
        done = subprocess.run(["lsof", "-nP", "-a", "-p", ",".join(str(p) for p in sorted(pids)), "-i"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"measured": False, "reason": str(error), "sockets": [], "findings": []}
    sockets, findings = [], []
    for line in done.stdout.splitlines()[1:]:
        parts = line.split(None, 8)
        if len(parts) < 9:
            continue
        name = parts[8]
        state = re.search(r"\((\w+)\)\s*$", name)
        address = re.sub(r"\s*\(\w+\)\s*$", "", name)
        sockets.append({"command": parts[0], "pid": int(parts[1]), "address": address, "state": state.group(1) if state else None})
        if "->" in address:
            remote = address.split("->", 1)[1].rsplit(":", 1)[0].strip("[]")
            if remote not in LOOPBACK:
                findings.append("%s (pid %s) has a non-loopback connection %s" % (parts[0], parts[1], address))
        elif address.startswith("*:") or address.startswith("0.0.0.0:"):
            findings.append("%s (pid %s) listens on all interfaces: %s" % (parts[0], parts[1], address))
    return {"measured": True, "sockets": sockets, "findings": findings}


def port_listeners(port: int) -> List[str]:
    done = subprocess.run(["lsof", "-nP", "-iTCP:%d" % port, "-sTCP:LISTEN"], stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, universal_newlines=True, timeout=20)
    return done.stdout.splitlines()[1:]


def can_bind(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_json(url: str, timeout: float = 5) -> Tuple[Optional[int], Optional[Any]]:
    try:
        with _OPENER.open(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
            try:
                return response.status, json.loads(body)
            except ValueError:
                return response.status, None
    except Exception:  # connection refused, reset, timeout: the caller treats None as "no answer"
        return None, None


def file_names(path: Path) -> Optional[List[str]]:
    """Recursive set of names (files and directories) below a directory; None when it does not exist."""
    if not path.exists():
        return None
    found = []
    for base, dirs, files in os.walk(str(path)):
        for name in dirs + files:
            found.append(os.path.relpath(os.path.join(base, name), str(path)))
    return sorted(found)


def make_tree_writable(path: Path) -> None:
    if not path.exists():
        return
    for base, dirs, files in os.walk(str(path)):
        for name in dirs + files:
            full = os.path.join(base, name)
            if not os.path.islink(full):
                try:
                    mode = os.stat(full).st_mode
                    # owner read and write for everything, search only for directories (an extra x bit on a file would
                    # also change a file shared through a hard link in an external cache)
                    os.chmod(full, mode | stat.S_IWUSR | stat.S_IRUSR | (stat.S_IXUSR if stat.S_ISDIR(mode) else 0))
                except OSError:
                    pass
    try:
        os.chmod(str(path), 0o755)
    except OSError:
        pass


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ---------------------------------------------------------------- the audit


class Audit:
    def __init__(self, args: argparse.Namespace, work: Path, out: Path, rev: str) -> None:
        self.args, self.work, self.out, self.rev = args, work, out, rev
        self.port = args.port
        self.url = "http://127.0.0.1:%d" % args.port
        self.export = work / "export"
        self.bin = work / "bin"
        self.tmp = work / "tmp"
        self.logs = out / "logs"
        self.codex_home = work / "codex-home"
        self.path = "%s:%s" % (self.bin, SYSTEM_PATH)
        self.uv_cache = Path(args.uv_cache).expanduser().resolve() if args.uv_cache else work / "uv-cache"
        self.npm_cache = Path(args.npm_cache).expanduser().resolve() if args.npm_cache else work / "npm-cache"
        self.cache_mode = {"uv": "warm" if args.uv_cache and self.uv_cache.exists() else "cold",
                           "npm": "warm" if args.npm_cache and self.npm_cache.exists() else "cold"}
        self.steps: List[Dict[str, Any]] = []
        self.groups: Dict[int, str] = {}  # pid of every child we started (its own process group) -> command line
        self.procs: Dict[int, subprocess.Popen] = {}
        self.audit_set: Dict[int, str] = {}
        self.snapshots: List[Dict[str, Any]] = []
        self.findings: List[str] = []
        self.env_names: Dict[str, List[str]] = {}
        self.tool_versions: Dict[str, str] = {}
        self.tool_paths: Dict[str, str] = {}
        self.overlay: Dict[str, Any] = {"enabled": bool(args.overlay_uncommitted), "files": [], "deleted": [], "skipped": []}
        self.lock_hashes: Dict[str, Dict[str, str]] = {}
        self.rows: Dict[str, Dict[str, Any]] = {}
        self.readonly_dirs: List[Path] = []
        self.refusal: Optional[str] = None
        self.extra_lines: List[str] = []
        self.sockets: List[socket.socket] = []
        for rid, claim in ROW_CLAIMS.items():
            self.rows[rid] = row(rid, claim, "not_measured", "not run", {}, ["not run in this invocation"])

    # ---- environment

    def env(self, kind: str, data_dir: Optional[Path] = None, serve: bool = False, control: bool = False) -> Dict[str, str]:
        """A child environment built from scratch from named variables (never inherited)."""
        env = {"PATH": self.path, "HOME": str(Path.home()), "USER": os.environ.get("USER") or getpass.getuser(),
               "LANG": os.environ.get("LANG") or "en_US.UTF-8", "TMPDIR": str(self.tmp)}
        if kind in ("install", "serve", "probe"):
            env["UV_CACHE_DIR"] = str(self.uv_cache)
            env["npm_config_cache"] = str(self.npm_cache)
            env["npm_config_userconfig"] = str(self.work / "npmrc-user")
            env["npm_config_globalconfig"] = str(self.work / "npmrc-global")
        if kind in ("serve", "probe"):
            env["DEIXIS_DATA_DIR"] = str(data_dir if data_dir is not None else self.work / "data-probe")
            env["DEIXIS_CODEX_HOME"] = str(self.codex_home)
            env["PYTHON_KEYRING_BACKEND"] = KEYRING_NULL
            env["PYTHONPATH"] = str(self.export / "backend")
            if control:
                del env["PYTHON_KEYRING_BACKEND"]
        if kind == "install":
            for name in INSTALL_PROXY_NAMES:
                if name in os.environ:
                    env[name] = os.environ[name]
        if serve:
            for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
                env[name] = "http://127.0.0.1:9"  # nothing listens on the discard port: outbound requests fail
            env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost"
        self.env_names.setdefault(kind + ("_with_proxy_trap" if serve else ""), sorted(env))
        return env

    def launch(self, python_args: List[str], data_dir: Path, serve: bool = False, control: bool = False):
        """The one launcher for every process that runs DEIXIS code: from the export, absolute paths, fail closed."""
        env = self.env("serve", data_dir, serve=serve, control=control)
        problems = launch_env_problems(env, self.export, self.work, self.export, control=control)
        if problems:
            raise RuntimeError("launcher refused: " + "; ".join(problems))
        argv = [str(self.bin / "uv"), "run", "--project", str(self.export), "python"] + python_args
        return argv, env, self.export

    # ---- processes

    def spawn(self, name: str, argv: List[str], cwd: Path, env: Dict[str, str]) -> subprocess.Popen:
        out = open(str(self.logs / (name + ".stdout.log")), "wb")
        err = open(str(self.logs / (name + ".stderr.log")), "wb")
        try:
            proc = subprocess.Popen(argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                    start_new_session=True)
        finally:
            out.close()
            err.close()
        self.groups[proc.pid] = " ".join(argv)
        self.procs[proc.pid] = proc
        return proc

    def settle_group(self, proc: subprocess.Popen) -> None:
        """After a child ended: anything left in its own process group is recorded and killed."""
        left = [r for r in ps_table() if r["pgid"] == proc.pid and r["pid"] != proc.pid]
        if left:
            self.findings.append("%s left %d process(es) in its group: %s" % (
                self.groups.get(proc.pid, "?")[:60], len(left), ", ".join(r["cmd"][:50] for r in left)))
            self.kill_group(proc.pid)

    def run_step(self, name: str, argv: List[str], cwd: Path, env: Dict[str, str], timeout: int) -> Dict[str, Any]:
        started, t0 = now_iso(), time.time()
        proc = self.spawn(name, argv, cwd, env)
        timed_out = False
        try:
            code: Optional[int] = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            self.kill_group(proc.pid)
            code = proc.wait()
        self.settle_group(proc)
        seconds = round(time.time() - t0, 1)
        step = {"name": name, "argv": argv, "cwd": str(cwd), "start": started, "seconds": seconds, "exit": code,
                "timed_out": timed_out, "limit_seconds": timeout}
        self.steps.append(step)
        return {"exit": None if timed_out else code, "timed_out": timed_out, "seconds": seconds,
                "stdout": read_text(self.logs / (name + ".stdout.log")), "stderr": read_text(self.logs / (name + ".stderr.log"))}

    def kill_group(self, pgid: int, trusted: bool = True) -> None:
        """SIGTERM then SIGKILL to a process group this harness created; never its own group.

        `trusted` is for a child that has only just ended or timed out. Later (a pid may have been reused) the group
        must hold a process that names the work directory or was seen by the audit."""
        if pgid in (os.getpgrp(), os.getpid()) or pgid not in self.groups:
            return
        members = [r for r in ps_table() if r["pgid"] == pgid]
        if not members:
            return
        verified = self.__dict__.get("verified", {})
        if not trusted and not any(verified.get(r["pid"]) == r["cmd"] for r in members):
            return
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(pgid, sig)
            except (ProcessLookupError, PermissionError):
                return
            for _ in range(30):
                if not any(r["pgid"] == pgid for r in ps_table()):
                    return
                time.sleep(0.1)

    def group_trusted(self, pgid: int) -> bool:
        """A child that is still running is certainly ours; for one that has ended only the kill_group checks apply."""
        proc = self.procs.get(pgid)
        return proc is not None and proc.poll() is None

    def owned_pids(self, table: List[Dict[str, Any]]) -> set:
        """Processes this harness may signal: members of a group it created and descendants of such a group's leader,
        while that leader still runs the recorded command. Ownership once verified is remembered in `self.verified`
        (pid and command); what the audit merely observed, or what only names the work directory, is reported, never signalled."""
        verified = self.__dict__.setdefault("verified", {})
        owned = set()
        for leader, recorded_cmd in self.groups.items():
            proc = getattr(self, "procs", {}).get(leader)
            running = proc is not None and proc.poll() is None  # our own live Popen: the pid cannot have been reused, an exec only changes the command
            if any(x["pid"] == leader and (running or x["cmd"] == recorded_cmd) for x in table):
                owned.update(r["pid"] for r in table if r["pgid"] == leader)
                owned.update(r["pid"] for r in descendants(table, leader))
        for r in table:
            if verified.get(r["pid"]) == r["cmd"] and r["pgid"] in self.groups:
                owned.add(r["pid"])  # the leader has gone: a member verified earlier is still ours
        # Playwright starts Chrome detached, in a group of its own; its profile lives in the fresh work dir, so a process
        # that names that profile belongs to the shell check this harness ran
        profile = str(self.tmp / "playwright_chromiumdev_profile")
        profiles = {r["pid"] for r in table if is_chrome_with_profile(r, profile)}
        owned.update(profiles)
        for pid in profiles:
            owned.update(r["pid"] for r in descendants(table, pid))
        verified.update({r["pid"]: r["cmd"] for r in table if r["pid"] in owned})
        return owned

    def kill_recorded(self, recorded: Dict[int, str]) -> None:
        """Check pid and command immediately before signalling. Reuse with the identical command, or reuse
        between this check and kill, remains possible. Freeze ownership before signalling any parent."""
        table = ps_table()
        excluded = own_exclusions(table)
        owned = self.owned_pids(table)
        for sig in (signal.SIGTERM, signal.SIGKILL):
            for pid, command in recorded.items():
                if pid in excluded or pid not in owned or command_of(pid) != command:
                    continue
                try:
                    os.kill(pid, sig)
                except (ProcessLookupError, PermissionError):
                    pass
            time.sleep(0.5)

    def snapshot(self, label: str, top: int) -> Dict[str, Any]:
        table = ps_table()
        excluded = own_exclusions(table)
        work = str(self.work)
        picked: Dict[int, str] = {}
        for r in descendants(table, top):
            picked[r["pid"]] = r["cmd"]
        for r in table:
            if r["pgid"] == top or cmd_mentions_dir(r["cmd"], work):
                picked[r["pid"]] = r["cmd"]
        picked = {pid: cmd for pid, cmd in picked.items() if pid not in excluded}
        self.owned_pids(table)  # remembers which of them are verifiably ours
        for pid, cmd in picked.items():
            self.audit_set.setdefault(pid, cmd)
        sockets = lsof_sockets(sorted(picked))
        for finding in sockets["findings"]:
            self.findings.append("[%s] %s" % (label, finding))
        entry = {"label": label, "processes": len(picked), "commands": sorted(command_names(picked.values())),
                 "sockets": sockets}
        self.snapshots.append(entry)
        return entry

    def survivors(self, recorded: Dict[int, str]) -> List[str]:
        _, alive = tree_gone(recorded, command_of)
        table = ps_table()
        excluded = own_exclusions(table)
        for r in table:
            if r["pid"] not in excluded and cmd_mentions_dir(r["cmd"], str(self.work)):
                alive.append("%d (names the work directory) %s" % (r["pid"], r["cmd"][:100]))
        return sorted(set(alive))

    # ---- server

    def start_server(self, label: str, data_dir: Path) -> Dict[str, Any]:
        argv, env, cwd = self.launch(["-m", "deixis", "serve", "--no-browser", "--port", str(self.port)], data_dir, serve=True)
        started, t0 = now_iso(), time.time()
        proc = self.spawn(label, argv, cwd, env)
        time.sleep(0.3)
        self.groups[proc.pid] = command_of(proc.pid) or self.groups[proc.pid]
        status, body, ready = None, None, None
        while time.time() - t0 < LIMITS["ready"]:
            if proc.poll() is not None:
                break
            status, body = http_json(self.url + "/api/health")
            if status == 200:
                ready = round(time.time() - t0, 1)
                break
            time.sleep(0.25)
        self.steps.append({"name": label, "argv": argv, "cwd": str(cwd), "start": started, "seconds": ready,
                           "exit": None, "timed_out": False, "limit_seconds": LIMITS["ready"], "note": "ready time; stop is a separate step"})
        return {"proc": proc, "status": status, "body": body, "ready_seconds": ready, "label": label}

    def stop_server(self, server: Dict[str, Any]) -> Dict[str, Any]:
        """SIGTERM to the top process only (what Ctrl-C or a service manager sends), then the tree-gone audit."""
        proc = server["proc"]
        self.snapshot(server["label"] + ":before_stop", proc.pid)
        recorded = dict(self.audit_set)
        t0 = time.time()
        if proc.poll() is None:  # never signal a pid the child has already given back
            try:
                proc.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            code: Optional[int] = proc.wait(timeout=LIMITS["stop"])
        except subprocess.TimeoutExpired:
            code = None
        exit_seconds = round(time.time() - t0, 2)
        left = self.survivors(recorded)
        while left and time.time() - t0 < LIMITS["stop"]:
            time.sleep(0.2)
            left = self.survivors(recorded)
        seconds = round(time.time() - t0, 2)
        listening = port_listeners(self.port)
        bound = can_bind(self.port)
        if left or code is None:
            self.kill_recorded(recorded)
            if proc.poll() is None:
                self.kill_group(proc.pid)
        self.settle_group(proc)
        self.steps.append({"name": server["label"] + ":stop", "argv": ["kill -TERM %d" % proc.pid], "cwd": str(self.work),
                           "start": now_iso(), "seconds": seconds, "exit": code, "timed_out": code is None,
                           "limit_seconds": LIMITS["stop"]})
        return {"exit_code": code, "seconds_to_exit": exit_seconds, "seconds_to_tree_gone": seconds, "survivors": left,
                "listening_after": listening, "port_bindable": bound, "audit_set_size": len(recorded),
                "ok": code is not None and not left and not listening and bound}

    # ---- steps

    def tool(self, name: str) -> Optional[str]:
        return shutil.which(name)

    def preflight(self) -> List[str]:
        problems = []
        for name in SHIM_TOOLS:
            found = self.tool(name)
            if not found and name != "npx":
                problems.append("%s not found on PATH" % name)
            if found:
                self.tool_paths[name] = found
        if not CHROME_APP.exists():
            problems.append("%s not found" % CHROME_APP)
        else:
            plist = plistlib.loads((CHROME_APP / "Contents" / "Info.plist").read_bytes())
            self.tool_versions["chrome"] = str(plist.get("CFBundleShortVersionString"))
        if problems:
            return problems
        for name in ("uv", "node", "npm"):
            done = subprocess.run([self.tool_paths[name], "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  universal_newlines=True, timeout=30)
            self.tool_versions[name] = done.stdout.strip().splitlines()[0] if done.stdout.strip() else "?"
        self.tool_versions["macos"] = subprocess.run(["sw_vers", "-productVersion"], stdout=subprocess.PIPE,
                                                     universal_newlines=True, timeout=15).stdout.strip()
        self.tool_versions["harness_python"] = platform.python_version()
        return problems

    def make_shims(self) -> List[str]:
        self.bin.mkdir()
        for name in SHIM_TOOLS:
            if name in self.tool_paths:
                shim = self.bin / name
                shim.write_text('#!/bin/sh\nexec "%s" "$@"\n' % self.tool_paths[name])
                shim.chmod(0o755)
        return [cli for cli in MODEL_CLIS if shutil.which(cli, path=self.path)]

    def export_commit(self) -> None:
        self.export.mkdir()
        archive = subprocess.Popen(["git", "-C", str(REPO), "archive", self.rev], stdout=subprocess.PIPE)
        done = subprocess.run(["tar", "-x", "-C", str(self.export)], stdin=archive.stdout, timeout=300)
        archive.stdout.close()
        if archive.wait() != 0 or done.returncode != 0:
            raise RuntimeError("git archive | tar failed")
        self.assert_no_dotenv("after export")
        if self.args.overlay_uncommitted:
            self.overlay_uncommitted()
            self.assert_no_dotenv("after overlay")

    def assert_no_dotenv(self, when: str) -> None:
        bad = [os.path.join(base, n) for base, dirs, files in os.walk(str(self.export)) for n in dirs + files if n.startswith(".env")]
        if bad:
            raise RuntimeError("a .env* file exists in the export %s: %s" % (when, bad[:3]))

    def overlay_uncommitted(self) -> None:
        listed: set = set()
        for command in (["ls-files", "-z", "-m", "-o", "--exclude-standard"], ["diff", "-z", "--name-only", "HEAD"]):  # unstaged, untracked, staged
            done = subprocess.run(["git", "-C", str(REPO)] + command, stdout=subprocess.PIPE, universal_newlines=True, timeout=60)
            listed.update(name for name in done.stdout.split("\0") if name)
        for rel in sorted(listed):
            parts = Path(rel).parts
            if (any(p in OVERLAY_SKIP_PARTS for p in parts) or any(rel == s or rel.startswith(s + "/") for s in OVERLAY_SKIP_PATHS)
                    or Path(rel).name.startswith(".env")):
                self.overlay["skipped"].append(rel)
                continue
            source, target = REPO / rel, self.export / rel
            if not os.path.lexists(str(source)):
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(str(target))
                elif os.path.lexists(str(target)):
                    target.unlink()
                self.overlay["deleted"].append(rel)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_symlink():
                if os.path.lexists(str(target)):
                    target.unlink()
                os.symlink(os.readlink(str(source)), str(target))
                self.overlay["files"].append({"path": rel, "symlink": os.readlink(str(source))})
            else:
                shutil.copy2(str(source), str(target))
                self.overlay["files"].append({"path": rel, "sha256": sha256_of(source)})

    def engines_check(self) -> List[str]:
        engines = json.loads(read_text(self.export / "apps/web/package.json")).get("engines", {})
        problems = []
        for tool, version in (("node", self.tool_versions["node"]), ("npm", self.tool_versions["npm"])):
            spec = engines.get(tool)
            if spec and not satisfies(version, spec):
                problems.append("%s %s does not satisfy engines %r" % (tool, version, spec))
        return problems

    def hash_locks(self, label: str) -> None:
        self.lock_hashes[label] = {name: sha256_of(self.export / name) for name in LOCK_FILES}

    def python_step(self, name: str, code: str, data_dir: Path, control: bool = False) -> Dict[str, Any]:
        argv, env, cwd = self.launch(["-c", code], data_dir, control=control)
        result = self.run_step(name, argv, cwd, env, LIMITS["other"])
        try:
            result["json"] = json.loads(result["stdout"].strip().splitlines()[-1])
        except (ValueError, IndexError):
            result["json"] = None
        return result

    def keyring_check(self) -> bool:
        data = self.work / "data-keyring"
        evidence: List[Any] = []
        stage1 = self.python_step("keyring-stage1", KEYRING_STAGE1, data)
        ok1, why1 = (False, "stage 1 did not run: exit %s" % stage1["exit"]) if not stage1["json"] else decide_keyring_stage1(stage1["json"])
        evidence.append({"stage": 1, "ok": ok1, "why": why1, "output": stage1["json"]})
        ok2 = False
        if ok1:
            stage2 = self.python_step("keyring-stage2", KEYRING_STAGE2, data)
            info = stage2["json"] or {}
            ok2 = bool(stage2["json"]) and info.get("keychain_name") is None and not info.get("macos_modules")
            evidence.append({"stage": 2, "ok": ok2, "output": info, "exit": stage2["exit"]})
            control = self.python_step("keyring-control", KEYRING_CONTROL, data, control=True)
            evidence.append({"stage": "control (variable unset; asks which backend is chosen, reads no secret)",
                             "output": control["json"]})
        passed = ok1 and ok2
        self.rows["keyring"] = row("keyring", ROW_CLAIMS["keyring"], "pass" if passed else "fail",
                                   "isolated keychain; no secret read or written", {}, evidence)
        return passed

    def install_step(self, key: str, argv: List[str], cwd: Path, limit: int) -> Dict[str, Any]:
        result = self.run_step(key.replace(" ", "-"), argv, cwd, self.env("install"), limit)
        self._i01["numbers"][key.replace(" ", "_") + "_seconds"] = result["seconds"]
        self._i01["evidence"].append({"step": key, "exit": result["exit"], "seconds": result["seconds"], "timed_out": result["timed_out"]})
        return result

    def venv_check(self) -> Tuple[bool, str]:
        python = self.export / ".venv" / "bin" / "python"
        if not python.exists():
            return False, ".venv/bin/python is missing"
        done = subprocess.run([str(python), "-c", "import platform; print(platform.machine(), platform.python_version())"],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=30,
                              env={"PATH": self.path, "HOME": str(Path.home())})
        text = done.stdout.strip()
        self.tool_versions["venv_python"] = text
        return text.startswith("arm64 3.12."), text

    def shell_check(self) -> Dict[str, Any]:
        shot = self.work / "home-screen.png"
        argv = [str(self.bin / "node"), str(REPO / "scripts/p9/shell_check.mjs"), str(self.export), self.url + "/", str(shot)]
        result = self.run_step("shell-check", argv, self.export, self.env("shell"), LIMITS["shell"])
        try:
            parsed = json.loads(result["stdout"].strip().splitlines()[-1])
        except (ValueError, IndexError):
            parsed = {"ok": False, "error": "no JSON line (exit %s)" % result["exit"]}
        parsed["screenshot_saved"] = shot.exists()
        return parsed

    def serve_once(self, name: str, data_dir: Path) -> Dict[str, Any]:
        argv, env, cwd = self.launch(["-m", "deixis", "serve", "--no-browser", "--port", str(self.port)], data_dir, serve=True)
        return self.run_step(name, argv, cwd, env, LIMITS["other"])

    def run(self) -> int:
        ok_env = self.preflight()
        if ok_env:
            return self.refuse("; ".join(ok_env))
        self.tmp.mkdir()
        (self.work / "npmrc-user").write_text("")
        (self.work / "npmrc-global").write_text("")
        on_path = self.make_shims()
        if on_path:
            return self.refuse("a model CLI is on the audit PATH: %s" % ", ".join(on_path))
        self.export_commit()
        engine_problems = self.engines_check()
        if engine_problems:
            return self.refuse("unsupported environment: " + "; ".join(engine_problems))
        self.hash_locks("before")
        self._i01 = {"evidence": [], "numbers": {}, "names": ()}
        self.i01_state = {"ok": True}

        # I01a: uv sync, then the keyring check before anything else runs deixis code or the network
        sync = self.install_step("uv sync", [str(self.bin / "uv"), "sync"], self.export, LIMITS["uv_sync"])
        venv_ok, venv_text = self.venv_check() if sync["exit"] == 0 else (False, "uv sync failed")
        self._i01["evidence"].append({"venv_python": venv_text, "ok": venv_ok})
        venv_bin = self.export / ".venv" / "bin"
        leaked = [c for c in MODEL_CLIS if shutil.which(c, path="%s:%s" % (venv_bin, self.path))]
        if leaked:
            return self.refuse("a model CLI is on the PATH uv run builds: %s" % ", ".join(leaked))
        if sync["exit"] != 0:
            self.finish_i01(False)
            return self.finalize(1)
        if not self.keyring_check():
            self.finish_i01(False)
            print("\nKEYRING ISOLATION FAILED. " + KEYRING_ALTERNATIVE)
            return self.finalize(4)

        ci = self.install_step("npm ci", [str(self.bin / "npm"), "ci"], self.export / "apps/web", LIMITS["npm_ci"])
        if ci["exit"] != 0:
            self.finish_i01(False)
            return self.finalize(1)

        self.run_i04()
        build = self.install_step("npm run build", [str(self.bin / "npm"), "run", "build"], self.export / "apps/web", LIMITS["npm_build"])
        dist = (self.export / "apps/web/dist/index.html").exists()
        self._i01["evidence"].append({"dist_index_html": dist})
        self.hash_locks("after_install")
        locks_same = self.lock_hashes["before"] == self.lock_hashes["after_install"]
        self._i01["evidence"].append({"lock_files_unchanged": locks_same})
        self.finish_i01(sync["exit"] == 0 and ci["exit"] == 0 and build["exit"] == 0 and venv_ok and dist and locks_same)
        if build["exit"] != 0 or not dist:
            return self.finalize(1)

        self.run_i02_i03b_i07()
        self.run_i03a()
        self.run_i05()
        return self.finalize(None)

    def refuse(self, message: str) -> int:
        print("refused: " + message, file=sys.stderr)
        self.refusal = message
        return 2

    def finish_i01(self, passed: bool) -> None:
        self._i01["numbers"]["total_seconds"] = round(sum(v for k, v in self._i01["numbers"].items() if k.endswith("_seconds")), 1)
        self.rows["I01"] = row("I01", ROW_CLAIMS["I01"], "pass" if passed else "fail",
                               "export of a commit, no model account, no provider key", self._i01["numbers"], self._i01["evidence"])

    def run_i04(self) -> None:
        server = self.start_server("serve-nodist", self.work / "data-nodist")
        self.snapshot("nodist:ready", server["proc"].pid)
        stop = self.stop_server(server)
        if not stop["ok"]:
            self.findings.append("I04 instance did not stop cleanly on SIGTERM: %s" % {k: stop[k] for k in ("exit_code", "survivors", "port_bindable")})
        stdout = read_text(self.logs / "serve-nodist.stdout.log")
        ok, reasons = check_i04(stdout, server["status"])
        ok = ok and (server["body"] or {}).get("status") == "ok"
        self.rows["I04"] = row("I04", ROW_CLAIMS["I04"], "pass" if ok else "fail", "export without apps/web/dist, empty library",
                               {"ready_seconds": server["ready_seconds"], "health_status": server["status"]},
                               [{"warning_line_present": "UI build not found (apps/web/dist)" in stdout, "health": server["body"],
                                 "stop": stop, "reasons": reasons}])

    def run_i02_i03b_i07(self) -> None:
        data = self.work / "data"
        server = self.start_server("serve", data)
        proc, body = server["proc"], server["body"] or {}
        evidence: List[Any] = []
        numbers: Dict[str, Any] = {"ready_seconds": server["ready_seconds"], "health_status": server["status"]}
        health_ok = server["status"] == 200 and body.get("status") == "ok" and body.get("worker") == "owner"
        evidence.append({"health": body})
        numbers["skill_package_hash"] = body.get("skill_package_hash")
        self.snapshot("ready", proc.pid)

        shell = self.shell_check()
        evidence.append({"shell_check": shell})
        status, credentials = http_json(self.url + "/api/credentials")
        keychain_off = status == 200 and (credentials or {}).get("keychain", {}).get("available") is False
        evidence.append({"credentials_keychain": (credentials or {}).get("keychain"), "keychain_unavailable": keychain_off})

        # I03b: a second serve on the same port and data directory
        before = file_names(data)
        second = self.serve_once("serve-second", data)
        after = file_names(data)
        busy_ok, busy_reasons = check_port_busy(second["exit"], second["stderr"], second["stdout"] + second["stderr"], self.port)
        status_again, again = http_json(self.url + "/api/health")
        first_still_owner = status_again == 200 and (again or {}).get("worker") == "owner"
        i03b_ok = busy_ok and before == after and first_still_owner
        self.snapshot("after_i03b", proc.pid)

        # I07: connections without any model account
        status, connections = http_json(self.url + "/api/connections", timeout=30)
        self.snapshot("after_i07", proc.pid)
        names = command_names(self.audit_set.values())
        i07_ok, i07_reasons = check_i07(connections or {}, names) if status == 200 else (False, ["/api/connections answered %s" % status])
        reasons_by_model = {n: str(e.get("reason"))[:80] for n, e in sorted(((connections or {}).get("models") or {}).items())}

        stop = self.stop_server(server)
        stdout = read_text(self.logs / "serve.stdout.log")
        running_line = "DEIXIS is running at" in stdout
        profiles = [p.name for p in self.tmp.glob("playwright_chromiumdev_profile*")]
        i02_ok = health_ok and bool(shell.get("ok")) and keychain_off and running_line and stop["ok"] and not profiles
        evidence.append({"chrome_profile_dirs_left": profiles})
        numbers.update({"seconds_to_exit": stop["seconds_to_exit"], "seconds_to_tree_gone": stop["seconds_to_tree_gone"],
                        "exit_code": stop["exit_code"], "audit_set_size": stop["audit_set_size"],
                        "external_requests_blocked": shell.get("external_requests_blocked"), "console_errors": shell.get("console_errors")})
        evidence.append({"running_line_in_log": running_line, "stop": stop, "snapshots": [
            {"label": s["label"], "processes": s["processes"], "commands": s["commands"], "sockets": len(s["sockets"]["sockets"]),
             "sockets_measured": s["sockets"]["measured"]} for s in self.snapshots if not s["label"].startswith(("nodist", "serve-nodist"))]})
        self.rows["I02"] = row("I02", ROW_CLAIMS["I02"], "pass" if i02_ok else "fail",
                               "export, UI built, empty library, no model, no provider key", numbers, evidence)
        self.rows["I03"] = row("I03", ROW_CLAIMS["I03"], "pending", "empty library, no model, no provider key", {}, [
            {"I03b": {"ok": i03b_ok, "second_exit": second["exit"], "stderr": second["stderr"].strip()[:300], "reasons": busy_reasons,
                      "data_dir_names_identical": before == after, "names_count": len(before or []), "first_still_owner": first_still_owner,
                      "second_seconds": second["seconds"]}}])
        self.rows["I07"] = row("I07", ROW_CLAIMS["I07"], "pass" if i07_ok else "fail",
                               "no model CLI on PATH, no keys; shows start and explanation, not a working model connection",
                               {"models": len(reasons_by_model)}, [{"reasons_by_model": reasons_by_model, "audit_commands": sorted(names),
                                                                    "reasons": i07_reasons}])
        self.i03b_ok = i03b_ok

    def run_i03a(self) -> None:
        data = self.work / "data-never-created"
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sockets.append(listener)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # a closed connection of the stopped instance may linger
            listener.bind(("127.0.0.1", self.port))
            listener.listen(1)
            result = self.serve_once("serve-busy", data)
        finally:
            listener.close()
        ok, reasons = check_port_busy(result["exit"], result["stderr"], result["stdout"] + result["stderr"], self.port)
        created = data.exists()
        i03a_ok = ok and not created
        row3 = self.rows["I03"]
        row3["evidence"].append({"I03a": {"ok": i03a_ok, "exit": result["exit"], "stderr": result["stderr"].strip()[:300],
                                         "data_dir_created": created, "reasons": reasons}})
        row3["result"] = "pass" if i03a_ok and getattr(self, "i03b_ok", False) else "fail"
        row3["numbers"] = {"i03a_ok": i03a_ok, "i03b_ok": getattr(self, "i03b_ok", False)}

    def run_i05(self) -> None:
        directory = self.work / "data-readonly"
        parent = self.work / "readonly-parent"
        directory.mkdir()
        parent.mkdir()
        evidence: List[Any] = []
        try:
            directory.chmod(0o555)
            parent.chmod(0o555)
            self.readonly_dirs.extend([directory, parent])
            before = file_names(directory)
            result = self.serve_once("serve-readonly", directory)
            after = file_names(directory)
            combined = result["stdout"] + result["stderr"]
            message_ok, reasons = check_i05_message(combined, str(directory))
            library = [n for n in (after or []) if n.startswith("library.sqlite")]
            ok = result["exit"] not in (0, None) and before == after and not library and message_ok
            line = next((l for l in combined.splitlines() if str(directory) in l), "")
            variant_dir = parent / "sub"
            variant = self.serve_once("serve-readonly-parent", variant_dir)
            variant_out = variant["stdout"] + variant["stderr"]
            variant_ok, variant_reasons = check_i05_message(variant_out, str(variant_dir))
            variant_clean = file_names(parent) == [] and not variant_dir.exists()
            if not (variant_ok and variant_clean and variant["exit"] not in (0, None)):
                self.findings.append("I05 variant (missing directory under a read-only parent) failed: %s" % (variant_reasons or "listing or exit code"))
            self.extra_lines.append("I05 message: %s" % (line.strip() or "(none)"))
            self.extra_lines.append("I05 variant (read-only parent, missing directory; not a plan row): exit %s, message %s, %s" % (
                variant["exit"], "ok" if variant_ok else "NOT ok", next((l for l in variant_out.splitlines() if str(variant_dir) in l), "(no line with the path)").strip()))
            evidence.append({"exit": result["exit"], "listing_before": before, "listing_after": after, "library_files": library,
                             "message": line.strip()[:300], "output_has_traceback": TRACEBACK in combined, "reasons": reasons})
            evidence.append({"variant (not a plan row; does not decide I05)": {
                "exit": variant["exit"], "message_ok": variant_ok, "listing_unchanged": variant_clean,
                "message": next((l for l in variant_out.splitlines() if str(variant_dir) in l), "").strip()[:300], "reasons": variant_reasons}})
            self.rows["I05"] = row("I05", ROW_CLAIMS["I05"], "pass" if ok else "fail",
                                   "read-only empty directory, no model, no provider key", {"exit": result["exit"], "seconds": result["seconds"]}, evidence)
        finally:
            for path in self.readonly_dirs:
                path.chmod(0o755)

    def final_audit(self) -> None:
        table = ps_table()
        excluded = own_exclusions(table)
        owned = self.owned_pids(table)  # includes profile descendants before a parent can disappear
        recorded = dict(self.audit_set)
        recorded.update({r["pid"]: r["cmd"] for r in table if r["pid"] in owned and r["pid"] not in excluded})
        self.audit_set.update(recorded)

        def problems_now() -> List[str]:
            current = ps_table()
            excluded_now = own_exclusions(current)
            groups = ["%d %s" % (r["pid"], r["cmd"][:80]) for r in current
                      if r["pgid"] in self.groups and r["pid"] not in excluded_now]
            return self.survivors(recorded) + groups + ["something listens on %d: %s" % (self.port, l) for l in port_listeners(self.port)]

        profiles = [p.name for p in self.tmp.glob("playwright_chromiumdev_profile*")] if self.tmp.exists() else []
        before = problems_now()
        if before:
            self.kill_recorded(recorded)
            for pid in list(self.groups):
                self.kill_group(pid, trusted=self.group_trusted(pid))
        problems = problems_now()
        self.rows["cleanup"] = row("cleanup", ROW_CLAIMS["cleanup"], "pass" if not problems else "fail",
                                   "process table and sockets after every run",
                                   {"recorded_group_leaders": len(self.groups), "audit_set_size": len(self.audit_set), "port": self.port},
                                   [{"alive_before_cleanup": before, "alive": problems, "reaudited": True,
                                     "chrome_profile_dirs_left_in_tmp": profiles, "findings": self.findings}])

    def finalize(self, forced: Optional[int]) -> int:
        if self.rows["I03"]["result"] == "pending":
            self.rows["I03"]["result"] = "fail"
            self.rows["I03"]["evidence"].append("I03a did not run")
        self.hash_locks("end")
        if self.lock_hashes.get("before") and self.lock_hashes["before"] != self.lock_hashes["end"] and self.rows["I01"]["result"] == "pass":
            self.rows["I01"]["result"] = "fail"
            self.rows["I01"]["evidence"].append({"lock_files_changed_by_a_later_step": self.lock_hashes})
        self.final_audit()
        self.rows["I08"] = row("I08", ROW_CLAIMS["I08"], "not_measured", "none", {}, ["not measured; no second-user claim"])
        failed = [rid for rid in MANDATORY if self.rows[rid]["result"] != "pass"]
        return forced if forced is not None else (1 if failed else 0)


ROW_CLAIMS = {
    "I01": "uv sync, npm ci and npm run build exit 0 in a clean export",
    "I02": "serve starts, /api/health is ok, the question box renders, stop frees the port and leaves no process",
    "I03": "busy port: 'Port N is in use', exit 2, data directory unchanged, a second instance is not a writer",
    "I04": "no apps/web/dist: the API starts and prints the warning",
    "I05": "unwritable data directory: exit not 0, nothing created, one message with path and cause",
    "I07": "without any model account every model connection is not ready and says why",
    "I08": "clean macOS user account, README steps only (manual)",
    "keyring": "PYTHON_KEYRING_BACKEND selects the null backend; no macOS keychain module is imported",
    "cleanup": "no recorded process alive, nothing listens on the port, nothing names the work directory",
}


def row(rid: str, claim: str, result: str, data: str, numbers: Dict[str, Any], evidence: List[Any]) -> Dict[str, Any]:
    return {"id": rid, "claim": claim, "result": result, "execution": "real process", "data": data, "numbers": numbers, "evidence": evidence}


# ---------------------------------------------------------------- self-test


def self_test() -> int:
    failures: List[str] = []

    def expect(label: str, got: Any, want: Any) -> None:
        if got != want:
            failures.append("%s: got %r, wanted %r" % (label, got, want))

    good = {"models": {n: {"ready": False, "reason": "codex CLI not found" if n == "codex" else "Add a key (API key) in Settings",
                           "installed": False, "key_configured": False} for n in ("codex", "claude", "gemini", "deepseek")}}
    expect("i07 baseline", check_i07(good, ["python"])[0], True)
    ready = json.loads(json.dumps(good))
    ready["models"]["codex"]["ready"] = True
    expect("i07 ready entry", check_i07(ready, [])[0], False)
    empty = json.loads(json.dumps(good))
    empty["models"]["claude"]["reason"] = ""
    expect("i07 empty reason", check_i07(empty, [])[0], False)
    sdk = json.loads(json.dumps(good))
    sdk["models"]["claude"]["reason"] = "Claude Code SDK error"
    expect("i07 unexpected reason", check_i07(sdk, [])[0], False)
    expect("i07 banned command", check_i07(good, ["claude"])[0], False)

    directory = "/tmp/x/data-readonly"
    traceback_text = ("Traceback (most recent call last):\n  File \"db.py\", line 12, in connect\n"
                      "    conn = sqlite3.connect('%s/library.sqlite')\nsqlite3.OperationalError: unable to open database file\n"
                      "ERROR:    Application startup failed. Exiting.\n" % directory)
    expect("i05 sqlite traceback", check_i05_message(traceback_text, directory)[0], False)
    permission = "Traceback (most recent call last):\n  File \"x.py\", line 1\nPermissionError: [Errno 13] Permission denied: '%s'\n" % directory
    expect("i05 permission traceback", check_i05_message(permission, directory)[0], False)
    one_line = "Cannot use the data directory %s: it is not writable. Set DEIXIS_DATA_DIR to a folder you can write to.\n" % directory
    expect("i05 one line", check_i05_message(one_line, directory)[0], True)
    expect("i05 no path", check_i05_message("it is not writable\n", directory)[0], False)

    expect("keyring macOS class", decide_keyring_stage1({"cls": "keyring.backends.macOS.Keyring", "macos_modules": []})[0], False)
    expect("keyring macOS module", decide_keyring_stage1({"cls": KEYRING_NULL, "macos_modules": ["keyring.backends.macOS"]})[0], False)
    expect("keyring null", decide_keyring_stage1({"cls": KEYRING_NULL, "macos_modules": []})[0], True)
    for name, code in (("stage1", KEYRING_STAGE1), ("stage2", KEYRING_STAGE2), ("control", KEYRING_CONTROL)):
        expect("keyring snippet %s reads no secret" % name, any(w in code for w in ("get_password", "set_password", "delete_password")), False)

    expect("i04 no warning", check_i04("DEIXIS is running", 200)[0], False)
    expect("i04 no health", check_i04("UI build not found (apps/web/dist). The API will run", None)[0], False)
    expect("i04 pass", check_i04("UI build not found (apps/web/dist). The API will run", 200)[0], True)

    expect("i03 message missing", check_port_busy(2, "something else", "something else", 8871)[0], False)
    expect("i03 pass", check_port_busy(2, "Port 8871 is in use. DEIXIS may", "Port 8871 is in use.", 8871)[0], True)
    expect("i03 started", check_port_busy(2, "Port 8871 is in use.", "Application startup complete", 8871)[0], False)
    expect("i03 exit code", check_port_busy(3, "Port 8871 is in use.", "", 8871)[0], False)

    expect("command names interpreter script", sorted(command_names(["node /x/bin/claude --flag", "/usr/bin/python3 -m deixis"])),
           ["claude", "deixis", "node", "python3"])
    expect("tree alive", tree_gone({10: "uv run x"}, lambda pid: "uv run x")[0], False)
    expect("tree dead", tree_gone({10: "uv run x"}, lambda pid: None)[0], True)
    expect("tree reused pid", tree_gone({10: "uv run x"}, lambda pid: "sleep 5")[0], True)

    expect("port 8871", port_refusal(8871), None)
    expect("port 8872", port_refusal(8872), None)
    for port in (8765, 8860, 8858, 8864, 80):
        expect("port %d" % port, port_refusal(port) is not None, True)

    expect("dir prefix", cmd_mentions_dir("python /tmp/run10/x", "/tmp/run1"), False)
    expect("dir whole", cmd_mentions_dir("python /tmp/run1/x", "/tmp/run1"), True)
    expect("dir argument", cmd_mentions_dir("uv run --project /tmp/run1", "/tmp/run1"), True)
    expect("dir inside longer path", cmd_mentions_dir("cat /var/tmp/run1/x", "/tmp/run1"), False)

    expect("engines node", satisfies("22.23.2", ">=22.12.0 <23"), True)
    expect("engines node 23", satisfies("23.0.0", ">=22.12.0 <23"), False)
    expect("engines node 22.11", satisfies("22.11.0", ">=22.12.0 <23"), False)
    expect("engines npm", satisfies("10.9.8", ">=10 <11"), True)
    expect("engines npm 11", satisfies("11.0.0", ">=10 <11"), False)

    work = Path("/tmp/work").resolve()
    export = work / "export"
    env = {"DEIXIS_DATA_DIR": str(work / "data"), "DEIXIS_CODEX_HOME": str(work / "codex-home"), "PYTHON_KEYRING_BACKEND": KEYRING_NULL,
           "PYTHONPATH": str(export / "backend")}
    expect("launcher baseline", launch_env_problems(env, export, work, export), [])
    expect("launcher no data dir", bool(launch_env_problems({k: v for k, v in env.items() if k != "DEIXIS_DATA_DIR"}, export, work, export)), True)
    expect("launcher live data dir", bool(launch_env_problems(dict(env, DEIXIS_DATA_DIR=str(LIVE_DATA_DIR)), export, work, export)), True)
    expect("launcher real keyring", bool(launch_env_problems(dict(env, PYTHON_KEYRING_BACKEND="x"), export, work, export)), True)
    expect("launcher port env", bool(launch_env_problems(dict(env, DEIXIS_PORT="8765"), export, work, export)), True)
    expect("launcher relative pythonpath", bool(launch_env_problems(dict(env, PYTHONPATH="backend"), export, work, export)), True)
    expect("launcher worktree cwd", bool(launch_env_problems(env, REPO, work, export)), True)
    expect("launcher control", launch_env_problems({k: v for k, v in env.items() if k != "PYTHON_KEYRING_BACKEND"}, export, work, export, control=True), [])

    if failures:
        print("self-test FAILED:\n  " + "\n  ".join(failures))
        return 1
    print("self-test ok")
    return 0


# ---------------------------------------------------------------- main


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="P9 H1 clean install and start audit")
    parser.add_argument("--rev", default="HEAD", help="commit to export (default HEAD)")
    parser.add_argument("--port", type=int, default=8871)
    parser.add_argument("--work-dir", help="must not exist; default /tmp/h1-install-<stamp>")
    parser.add_argument("--out-dir", help="must not exist; default <repo>/.local/p9-h1/<stamp>")
    parser.add_argument("--uv-cache", help="uv cache of an earlier kept run (never deleted); default a fresh one in the work dir")
    parser.add_argument("--npm-cache", help="npm cache of an earlier kept run (never deleted); default a fresh one in the work dir")
    parser.add_argument("--keep", action="store_true", help="keep the work directory")
    parser.add_argument("--overlay-uncommitted", action="store_true", help="copy modified and untracked files over the export")
    parser.add_argument("--self-test", action="store_true", help="run pure-function checks and exit")
    return parser.parse_args(argv)


def host_problems() -> List[str]:
    problems = []
    if sys.version_info < (3, 9):
        problems.append("Python 3.9 or newer is needed (this is %s)" % platform.python_version())
    if sys.platform != "darwin":
        problems.append("the supported environment is macOS arm64 (this is %s)" % sys.platform)
    if platform.machine() != "arm64":
        problems.append("this Python reports %s, not arm64 (Rosetta?); run it with /opt/homebrew/bin/python3.12 or another arm64 interpreter"
                        % platform.machine())
    return problems


def print_table(rows: Dict[str, Dict[str, Any]], steps: List[Dict[str, Any]], extra: List[str]) -> None:
    print("\n%-8s %-13s %s" % ("row", "result", "claim"))
    for rid in ROW_ORDER:
        r = rows[rid]
        print("%-8s %-13s %s" % (rid, r["result"], r["claim"]))
    for line in extra:
        print("  " + line)
    print("\nstep timings (seconds):")
    for s in steps:
        if s["name"].endswith(":stop") or s["seconds"] is None:
            continue
        print("  %-28s %8s  exit %s" % (s["name"], s["seconds"], s["exit"]))


def main() -> int:
    args = parse_args()
    problems = host_problems()
    if problems:
        print("refused: " + "; ".join(problems), file=sys.stderr)
        return 2
    if args.self_test:
        return self_test()
    refusal = port_refusal(args.port)
    if refusal:
        print("refused: " + refusal, file=sys.stderr)
        return 2
    if not can_bind(args.port) or port_listeners(args.port):
        print("refused: port %d is already in use" % args.port, file=sys.stderr)
        return 2
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    work = Path(args.work_dir or "/tmp/h1-install-%s" % stamp).expanduser().resolve()
    if work.exists():
        print("refused: the work directory %s already exists (a reused directory could carry an old build)" % work, file=sys.stderr)
        return 2
    home = Path.home().resolve()
    if _inside(work, REPO) or _inside(work, LIVE_DATA_DIR.resolve()) or work == home or _inside(home, work):
        print("refused: the work directory is inside the repository or the live data directory, or equals or contains HOME", file=sys.stderr)
        return 2
    out = Path(args.out_dir).expanduser().resolve() if args.out_dir else REPO / ".local" / "p9-h1" / stamp
    if out.exists():
        print("refused: the output directory %s already exists" % out, file=sys.stderr)
        return 2
    if _inside(out, work) or _inside(out, LIVE_DATA_DIR.resolve()):
        print("refused: the output directory would be deleted with the work directory or sit in the live data directory", file=sys.stderr)
        return 2
    if args.overlay_uncommitted and args.rev != "HEAD":
        print("refused: --overlay-uncommitted copies changes made against HEAD, so it needs --rev HEAD", file=sys.stderr)
        return 2
    for cache in (args.uv_cache, args.npm_cache):
        if cache and _inside(Path(cache), work):
            print("refused: a cache directory inside the work directory would be deleted with it", file=sys.stderr)
            return 2
    rev = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--verify", args.rev + "^{commit}"], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, universal_newlines=True)
    if rev.returncode != 0:
        print("refused: cannot resolve --rev %s" % args.rev, file=sys.stderr)
        return 2
    try:
        work.mkdir()
    except OSError as error:
        print("refused: cannot create the work directory: %s" % error, file=sys.stderr)
        return 2
    out.mkdir(parents=True)
    (out / "logs").mkdir()
    audit = Audit(args, work, out, rev.stdout.strip())

    def abort(signum, frame):
        raise Aborted("signal %d" % signum)

    previous = {s: signal.signal(s, abort) for s in (signal.SIGINT, signal.SIGTERM)}
    code = 1
    started = now_iso()
    try:
        try:
            code = audit.run()
        except Aborted as error:
            audit.findings.append("harness interrupted: %s" % error)
            code = 1
        except Exception as error:  # report, then fall through to cleanup
            audit.findings.append("harness error: %s: %s" % (type(error).__name__, error))
            print("harness error: %s: %s" % (type(error).__name__, error), file=sys.stderr)
            code = 1
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        for pid in list(audit.groups):
            audit.kill_group(pid, trusted=audit.group_trusted(pid))
        for sock in audit.sockets:
            sock.close()
        for path in audit.readonly_dirs:
            make_tree_writable(path)
        if audit.rows["cleanup"]["result"] == "not_measured":
            try:
                audit.final_audit()
            except Exception as error:
                audit.findings.append("final audit failed: %s" % error)
        uv_config = [str(p) for p in (Path.home() / ".config/uv/uv.toml", Path.home() / ".uv", Path("/etc/uv/uv.toml")) if p.exists()]
        results = {
            "commit": audit.rev, "overlay": audit.overlay, "started": started, "finished": now_iso(),
            "machine": {"platform": platform.platform(), "machine": platform.machine(), "uv_user_configuration": uv_config,
                        "work_dir": str(work), "port": args.port},
            "tool_versions": audit.tool_versions, "cache_mode": audit.cache_mode, "env_variable_names": audit.env_names,
            "lock_file_sha256": audit.lock_hashes, "steps": audit.steps, "rows": [audit.rows[r] for r in ROW_ORDER],
            "findings": audit.findings, "refusal": audit.refusal, "exit_code": code,
        }
        (out / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        if args.keep or audit.rows["cleanup"]["result"] != "pass":
            print("work directory kept: %s" % work)
        else:
            make_tree_writable(work)
            shutil.rmtree(str(work), ignore_errors=True)
    extra = audit.extra_lines + ["finding: " + f for f in audit.findings]
    print_table(audit.rows, audit.steps, extra)
    print("\ncommit %s%s  cache uv=%s npm=%s  results: %s/results.json" % (
        audit.rev[:12], " + uncommitted overlay" if args.overlay_uncommitted else "", audit.cache_mode["uv"], audit.cache_mode["npm"], out))
    return code


if __name__ == "__main__":
    sys.exit(main())
