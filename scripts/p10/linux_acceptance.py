"""Acceptance of the installed DEIXIS on Linux x64 (P10 L5): the .deb and the AppImage as built by linux-desktop.yml.

    python scripts/p10/linux_acceptance.py --deb DEIXIS_0.1.1_amd64.deb --appimage DEIXIS_0.1.1_amd64.AppImage
                                           [--evidence DIR] [--only ROW,...] [--formats deb,appimage]

Runs inside an X display with a window manager and a D-Bus session (CI: xvfb-run + dbus-run-session + Openbox), as a
user who may use sudo for `apt` (the .deb's install and removal). Needs `tauri-driver` and `WebKitWebDriver` on PATH for
the rows inside the window, `wmctrl` and ImageMagick's `import`. Standard library only (plus tests/support/helpers
.make_pdf); the fake codex runs with this Python, which must import the repo's `deixis` package. Every record is
SYNTHETIC. Rows per format (`deb_*`, `appimage_*`), each PASS, FAIL, NOT_DONE (could not be checked here, with the
reason) or MANUAL; the exit code is 0 only when every row run is PASS or MANUAL:

  install        .deb: `apt-get install --no-install-recommends ./file.deb` (dependencies resolved, the indicator library
                 among them); the shell and the sidecar are executable. AppImage: copied and made executable. SHA-256.
  open           launched by tauri-driver + WebKitWebDriver with a temp DEIXIS_DATA_DIR: health 200 with a start nonce on
                 the port read from desktop-port.json within 60 s; one "DEIXIS" window (wmctrl); the page is the
                 backend's origin and shows the research screen; screenshot of the screen (import -window root)
  csrf_save      inside the window the sidebar's theme button is clicked and the backend stores the new theme (session
                 cookie + CSRF header); a PUT without the header is refused 403
  pdf_tab        an uploaded synthetic PDF's source sheet opens from the research page and its PDF tab draws a page
                 (the canvas gets data-rendered-page, so pdf.js's worker and the canvas ran in WebKitGTK)
  download       a finished research's report (Markdown) and CSV, through the window's Export menu, land in the Downloads
                 folder the shell names (no XDG user-dirs file on the runner: ~/Downloads) with their content; each
                 twice, the second as "name (1).ext" with the first file unchanged, and nothing written elsewhere
  second_launch  the installed executable again: it exits, the DEIXIS process set is unchanged, still one window
  env            the backend's environment (/proc/<pid>/environ) holds no AppImage variable and no PATH, XDG_DATA_DIRS or
                 LD_LIBRARY_PATH entry inside $APPDIR; a link the page opens goes to a fake xdg-open, which records the
                 same for its own environment (run for both formats; outside an AppImage the shell changes nothing)
  close_quits    under load (a hanging fake codex that leaves an orphaned `setsid` grandchild, and a PDF extraction
                 child): closing the window (wmctrl -c) quits; nothing left within 15 s
  kill_shell     SIGKILL of the shell under the same load: nothing left within 15 s
  kill_backend   SIGKILL of the backend under the same load while a run is active: within 15 s the old backend family
                 is gone while the shell stays; the window shows "backend stopped"; its Restart brings a new backend
                 (a new nonce); integrity_check and foreign_key_check ok; the interrupted run is paused with its step
                 outcome_unknown; then closing the window leaves nothing
  no_fuse        AppImage only: `--appimage-extract-and-run` (no FUSE needed, K14): health, then SIGTERM-free quit by
                 closing the window, nothing left
  uninstall      .deb: `apt-get remove` removes the package; every scenario's library folder keeps its files.
                 AppImage: the file is deleted; the libraries are kept.

"Nothing left" is checked three ways: every process the watcher saw for the scenario (the shell, its descendants by
parent pid and start time, anything whose command names the install, the data or the fake-tool folder; /proc every
0.2 s) is gone within 15 s; no process holds a file in the data folder open (/proc/*/fd); and a full /proc snapshot
before the launch and 15 s after the trigger lists every new live process with why it is not DEIXIS, or the row fails.
A local model server under load is not faked here (it needs the llama.cpp runtime and a model with their integrity
record), the same as on macOS: written as not measured. Passing shows these paths on this runner, not a desktop.
"""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "tests" / "support")]
from helpers import make_pdf  # noqa: E402  (pure Python, no package import)

LEFT_LIMIT = 15.0
QUESTION = "How is molecule release scheduling optimized in SYNTHETIC diffusion channels?"
DEB_LIB = Path("/usr/lib/DEIXIS")
GENERIC = ("python", "python3", "node", "sh", "bash", "sleep", "deixis-backend", "deixis-desktop", "codex", "tesseract",
           "WebKitWebProcess", "WebKitNetworkProcess", "xdg-open")
APPIMAGE_NAMES = ("APPDIR", "APPIMAGE", "ARGV0", "OWD")
results: dict[str, dict] = {}


def row(name: str, ok: bool | None | str, **facts) -> None:
    results[name] = {"ok": ok, **facts}
    word = {True: "PASS", False: "FAIL", None: "NOT_DONE"}.get(ok, "MANUAL") if not isinstance(ok, str) else "MANUAL"
    print(f"{word} {name} {json.dumps(facts, default=str)[:3000]}", flush=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return port if port != 8765 else free_port()


def wait_for(check, seconds: float, step: float = 0.2):
    ends = time.monotonic() + seconds
    while True:
        try:
            value = check()
        except (OSError, ValueError, KeyError, RuntimeError):
            value = None
        if value or time.monotonic() >= ends:
            return value
        time.sleep(step)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# ------------------------------------------------------------------------------------------------- processes ---

def proc_table() -> dict[str, dict]:
    """`pid:starttime` -> pid, ppid, start, name, cmd, exe for every process readable now."""
    table: dict[str, dict] = {}
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        try:
            stat = Path(f"/proc/{entry.name}/stat").read_text()
            name = stat[stat.index("(") + 1:stat.rindex(")")]
            fields = stat.rsplit(")", 1)[1].split()
            if fields[0] == "Z":
                continue
            cmd = Path(f"/proc/{entry.name}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
        except (OSError, ValueError, IndexError):
            continue
        try:
            exe = os.readlink(f"/proc/{entry.name}/exe")
        except OSError:
            exe = ""
        pid = int(entry.name)
        table[f"{pid}:{fields[19]}"] = {"pid": pid, "ppid": int(fields[1]), "t": int(fields[19]), "name": name,
                                        "cmd": cmd, "exe": exe}
    return table


RUNNER_FOLDERS = ("_diag", "_temp", "_actions", "_tool", "runners")  # the CI runner's own, written while a job runs


def download_roots(home: Path, work: Path) -> list[tuple[Path, bool]]:
    """Where a misdirected download could land: the whole home folder (this checkout, the shell's current folder and
    Wry's default without a Downloads folder, is inside it) and the scenario folder."""
    return [(home, True), (work, True)]


def files_state(roots: list[tuple[Path, bool]], skip: set[Path]) -> dict[Path, tuple[int, int]]:
    """Every file (size, mtime) under each root (its subfolders only when the flag says so) outside `skip` and
    outside hidden and __pycache__ folders (caches the webview, Python and the tools write): an added or changed file
    there is a write outside the Downloads folder."""
    found: dict[Path, tuple[int, int]] = {}
    for root, deep in roots:
        for folder, dirs, names in os.walk(root):
            here = Path(folder)
            dirs[:] = [d for d in dirs if deep and not d.startswith(".") and d not in ("__pycache__", *RUNNER_FOLDERS)
                       and here / d not in skip]
            for name in names:
                if here / name in skip:
                    continue
                try:
                    st = (here / name).stat()
                except OSError:
                    continue
                found[here / name] = (st.st_size, st.st_mtime_ns)
    return found


def owner_uid(pid: int) -> int | None:
    try:
        return os.stat(f"/proc/{pid}").st_uid
    except OSError:
        return None


def alive(ident: str, table: dict | None = None) -> bool:
    return ident in (proc_table() if table is None else table)


def environ_of(pid: int) -> dict[str, str]:
    raw = Path(f"/proc/{pid}/environ").read_bytes()
    return dict(item.split("=", 1) for item in raw.decode(errors="replace").split("\0") if "=" in item)


def holders(folder: Path) -> list[str]:
    """Processes with a file inside `folder` open."""
    found = []
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            for fd in os.scandir(f"/proc/{entry.name}/fd"):
                target = os.readlink(fd.path)
                if target.startswith(str(folder) + "/"):
                    found.append(f"{entry.name} {target}")
        except OSError:
            continue
    return found


class Watcher:
    """Samples /proc every 0.2 s for the whole scenario and keeps every DEIXIS process it sees."""

    def __init__(self, marks: list[str]):
        self.marks = marks
        self.roots: set[int] = set()
        self.harness_roots: set[int] = set()
        self.harness: dict[str, dict] = {}  # tauri-driver and its WebKitWebDriver: followed to the app, not DEIXIS
        self.seen: dict[str, dict] = {}
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def sample(self) -> None:
        procs = proc_table()
        changed = True
        while changed:
            changed = False
            parents = {p["pid"]: p["t"] for i, p in (self.seen | self.harness).items() if i in procs}
            for ident, proc in procs.items():
                if ident in self.seen or ident in self.harness or proc["pid"] == os.getpid():
                    continue
                child = proc["ppid"] in parents and proc["t"] >= parents[proc["ppid"]]
                if proc["pid"] in self.harness_roots or (child and proc["exe"].endswith("/WebKitWebDriver")):
                    self.harness[ident] = proc
                    changed = True
                elif child or any(m in proc["cmd"] or m in proc["exe"] for m in self.marks):
                    self.seen[ident] = proc
                    changed = True

    def run(self) -> None:
        while not self.stop.is_set():
            self.sample()
            self.stop.wait(0.2)

    def alive(self) -> list[dict]:
        now = proc_table()
        return [self.seen[i] | {"ident": i} for i in self.seen if i in now]

    def close(self) -> None:
        self.stop.set()
        if self.thread.is_alive():
            self.thread.join(2)


# --------------------------------------------------------------------------------------------------- the API ---

class Http:
    """The backend's API as the page uses it: the session cookie and the CSRF header; never through a proxy."""

    def __init__(self, port: int):
        self.base = f"http://127.0.0.1:{port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                  urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.headers: dict[str, str] = {}

    def call(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None,
             timeout: float = 60) -> tuple[int, bytes]:
        request = urllib.request.Request(self.base + path, data=body, method=method, headers=self.headers | (headers or {}))
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()
        except OSError as error:
            return 0, str(error).encode()

    def json(self, method: str, path: str, payload=None, **kw) -> tuple[int, dict]:
        body = None if payload is None else json.dumps(payload).encode()
        status, raw = self.call(method, path, body, {"Content-Type": "application/json"} if body else None, **kw)
        try:
            return status, json.loads(raw or b"null")
        except ValueError:
            return status, {"raw": raw[:300].decode(errors="replace")}

    def login(self) -> None:
        _, session = self.json("GET", "/api/session")
        self.headers["x-deixis-csrf"] = session["csrf_token"]

    def upload(self, path: str, name: str, data: bytes, timeout: float = 120) -> tuple[int, dict]:
        boundary = "SYNTHETIC" + os.urandom(8).hex()
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
                "Content-Type: application/pdf\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
        status, raw = self.call("POST", path, body, {"Content-Type": f"multipart/form-data; boundary={boundary}"},
                                timeout=timeout)
        try:
            return status, json.loads(raw)
        except ValueError:
            return status, {}


def health(port: int, timeout: float = 2) -> dict | None:
    status, body = Http(port).json("GET", "/api/health", timeout=timeout)
    return body if status == 200 else None


# ------------------------------------------------------------------------------------------------- WebDriver ---

class Driver:
    """W3C WebDriver against tauri-driver, which starts WebKitWebDriver, which starts the app with the environment
    tauri-driver was given."""

    def __init__(self, application: str, env: dict[str, str], log: Path):
        self.port = free_port()
        native = free_port()
        self.proc = subprocess.Popen(["tauri-driver", "--port", str(self.port), "--native-port", str(native)], env=env,
                                     stdout=open(log, "ab"), stderr=subprocess.STDOUT, start_new_session=True)
        self.base = f"http://127.0.0.1:{self.port}"
        self.session = None
        if not wait_for(lambda: self._raw("GET", "/status")[0] == 200, 20, 0.2):
            raise RuntimeError("tauri-driver did not answer")
        status, body = self._raw("POST", "/session", {"capabilities": {"alwaysMatch": {
            "tauri:options": {"application": application}}}}, timeout=120)
        value = body.get("value") or {}
        if status != 200 or "sessionId" not in value:
            raise RuntimeError(f"no WebDriver session ({status}): {json.dumps(value)[:400]}")
        self.session = value["sessionId"]

    def _raw(self, method: str, path: str, payload=None, timeout: float = 30) -> tuple[int, dict]:
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method,
                                         headers={"Content-Type": "application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=timeout) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            try:
                return error.code, json.loads(error.read() or b"{}")
            except ValueError:
                return error.code, {}
        except (OSError, ValueError):
            return 0, {}

    def call(self, method: str, path: str, payload=None, timeout: float = 30):
        status, body = self._raw(method, f"/session/{self.session}{path}", payload, timeout)
        if status != 200:
            raise RuntimeError(f"WebDriver {method} {path}: {status} {json.dumps(body)[:300]}")
        return body.get("value")

    def eval(self, script: str, *args):
        return self.call("POST", "/execute/sync", {"script": script, "args": list(args)})

    def url(self) -> str:
        return self.call("GET", "/url") or ""

    def go(self, url: str) -> None:
        self.call("POST", "/url", {"url": url}, timeout=60)

    def text(self) -> str:
        return self.eval("return document.body ? document.body.innerText : ''") or ""

    def click(self, want: str, exact: bool = False) -> bool:
        """A real click (WebDriver element click) on the first visible button, link, tab or menu item whose
        aria-label or text is `want` (or contains it)."""
        test = (f"normalize-space(@aria-label)={json.dumps(want)} or normalize-space(.)={json.dumps(want)}" if exact else
                f"contains(@aria-label,{json.dumps(want)}) or contains(normalize-space(.),{json.dumps(want)})")
        xpath = f"//*[self::button or self::a or @role='menuitem' or @role='tab' or @role='button'][{test}]"
        try:
            found = self.call("POST", "/elements", {"using": "xpath", "value": xpath}) or []
        except RuntimeError:
            return False
        for element in found:
            eid = next(iter(element.values()))
            try:
                if self.call("GET", f"/element/{eid}/displayed"):
                    self.call("POST", f"/element/{eid}/click", {})
                    return True
            except RuntimeError:
                continue
        return False

    def close(self) -> None:
        if self.session:
            self._raw("DELETE", f"/session/{self.session}", timeout=20)
            self.session = None
        if self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait()


# --------------------------------------------------------------------------------------------------- scenario ---

class Scenario:
    """One launch of the installed app (one format) with its own data folder."""

    def __init__(self, work: Path, env: dict[str, str], fmt: str, name: str, exe: str, marks: list[str]):
        self.fmt, self.name, self.work, self.exe = fmt, name, work, exe
        self.data = work / f"data-{fmt}-{name}"
        self.data.mkdir()
        self.saved_port = free_port()
        (self.data / "desktop-port.json").write_text(json.dumps({"port": self.saved_port}))
        self.env = env | {"DEIXIS_DATA_DIR": str(self.data), "DEIXIS_PORT": str(free_port())}
        self.before = proc_table()
        self.watch = Watcher([*marks, str(self.data), str(work / "bin")])
        self.driver: Driver | None = None
        self.driver_error = ""
        self.proc: subprocess.Popen | None = None
        self.started = 0.0
        self.port: int | None = None
        self.api: Http | None = None

    def launch(self, driven: bool = True, extra_args: tuple[str, ...] = ()) -> None:
        self.started = time.monotonic()
        if driven:
            try:
                self.driver = Driver(self.exe, self.env, self.work / f"driver-{self.fmt}-{self.name}.log")
                self.watch.harness_roots.add(self.driver.proc.pid)
            except RuntimeError as error:
                self.driver_error = str(error)
        if self.driver is None:
            self.proc = subprocess.Popen([self.exe, *extra_args], env=self.env, cwd=str(self.work),
                                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=open(self.work / f"shell-{self.fmt}-{self.name}.err", "wb"),
                                         start_new_session=True)
            self.watch.roots.add(self.proc.pid)
        self.watch.thread.start()

    def shell_pid(self) -> int | None:
        """The shell: the process running deixis-desktop seen for this scenario (under the driver, or launched)."""
        now = proc_table()
        shells = [p["pid"] for i, p in self.watch.seen.items() if i in now and
                  (p["exe"].endswith("/deixis-desktop") or Path(p["cmd"].split(" ")[0] if p["cmd"] else "").name == "deixis-desktop")]
        return min(shells) if shells else None

    def backend_pids(self) -> list[int]:
        """The serving backend: `deixis-backend serve --desktop` (the watchdog's child)."""
        return [p["pid"] for i, p in proc_table().items() if i in self.watch.seen and "serve --desktop" in p["cmd"]
                and p["exe"].endswith("/deixis-backend")]

    def read_port(self) -> int | None:
        try:
            return json.loads((self.data / "desktop-port.json").read_text(encoding="utf-8")).get("port")
        except (OSError, ValueError):
            return None

    def wait_health(self, seconds: float = 60, since: float | None = None) -> tuple[float | None, dict | None]:
        start = self.started if since is None else since
        while time.monotonic() < start + seconds:
            port = self.read_port()
            if port and (body := health(port)) is not None:
                self.port, self.api = port, Http(port)
                return time.monotonic() - start, body
            time.sleep(0.1)
        return None, None

    def session(self) -> Http:
        if not self.api.headers:
            self.api.login()
        return self.api

    def windows(self) -> list[str]:
        listing = subprocess.run(["wmctrl", "-l", "-p"], capture_output=True, text=True).stdout.splitlines()
        return [line for line in listing if line.rstrip().endswith(" DEIXIS")]

    def family(self) -> list[int]:
        return sorted(p["pid"] for p in self.watch.alive())

    def check_left(self, trigger: float) -> dict:
        while time.monotonic() < trigger + LEFT_LIMIT and self.watch.alive():
            time.sleep(0.2)
        gone_s = time.monotonic() - trigger
        left = self.watch.alive()
        self.watch.close()
        time.sleep(max(0.0, trigger + LEFT_LIMIT - time.monotonic()))
        held = holders(self.data)
        after = proc_table()
        seen_pids = {p["pid"] for p in self.watch.seen.values()}
        driver = {p["pid"] for p in self.watch.harness.values()}
        explained, unexplained = [], []
        excused: set[str] = set()  # new processes whose origin is known and not DEIXIS (their children are excused too)
        for ident, proc in sorted(((i, p) for i, p in after.items() if i not in self.before), key=lambda x: x[1]["t"]):
            cmd = proc["cmd"]
            parent = next((i for i, p in after.items() if p["pid"] == proc["ppid"] and p["t"] <= proc["t"]), None)
            known_parent = parent is not None and after[parent]["pid"] != 1 and parent not in self.watch.seen and (
                parent in self.before or parent in excused)
            if ident in self.watch.seen and proc["pid"] not in driver:
                unexplained.append(proc | {"why": "seen as DEIXIS of this scenario"})
            elif proc["pid"] == os.getpid() or proc["ppid"] == os.getpid() or proc["pid"] in driver:
                excused.add(ident)
                explained.append(f"{proc['pid']} this acceptance script's own child or WebDriver: {cmd[:80]}")
            elif str(self.data) in cmd or str(self.work / "bin") in cmd or self.exe in cmd:
                unexplained.append(proc | {"why": "names this scenario's folders or the installed app"})
            elif proc["ppid"] in seen_pids - driver:
                unexplained.append(proc | {"why": "its parent pid was a DEIXIS process of this scenario"})
            elif proc["ppid"] == 2:  # kthreadd's children
                excused.add(ident)
                explained.append(f"{proc['pid']} {proc['name']} kernel thread")
            elif (owner := owner_uid(proc["pid"])) is not None and owner != os.getuid():  # DEIXIS runs as this user
                excused.add(ident)
                explained.append(f"{proc['pid']} {proc['name']} runs as user {owner}, not this one: {cmd[:80]}")
            elif known_parent:
                excused.add(ident)
                explained.append(f"{proc['pid']} {proc['name']} child of {after[parent]['name']} ({after[parent]['pid']}),"
                                 f" which ran before the launch: {cmd[:80]}")
            else:  # an orphan (re-parented to init) or of unknown origin: never excused
                unexplained.append(proc | {"why": "new, and not a child of a process that ran before the launch"})
        return {"ok": not left and not held and not unexplained, "all_gone_s": round(gone_s, 2),
                "seen": len(self.watch.seen), "seen_names": sorted({p["name"] for p in self.watch.seen.values()}),
                "left": [f"{p['pid']} {p['name']}" for p in left], "open_files": held[:10],
                "unexplained": unexplained[:5], "new_processes_explained": explained[:15]}

    def kill_all(self) -> None:
        for proc in self.watch.alive():
            try:
                os.kill(proc["pid"], signal.SIGKILL)
            except OSError:
                pass
        if self.driver:
            self.driver.close()
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
        wait_for(lambda: not self.watch.alive(), 10)
        self.watch.close()


# ------------------------------------------------------------------------------------------------------- load ---

def fake_tools(bin_dir: Path, python: str) -> None:
    """codex: fake_codex.py behind a shell script that first leaves an orphaned grandchild in a session of its own
    (`( setsid sleep & )`: the subshell exits at once, so the sleep's parent is gone), the escape the watchdog's
    subreaper must catch; a turn hangs unless `no-hang` exists. xdg-open: records the named environment variables."""
    codex = bin_dir / "codex"
    codex.write_text(
        "#!/bin/sh\n"
        f"( setsid /bin/sleep 307 >/dev/null 2>&1 & )\n"
        f"[ -e {bin_dir / 'no-hang'} ] || export _FAKE_CODEX_HANG=1\n"
        f"_FAKE_CODEX_DIR={bin_dir} exec {python} {REPO / 'scripts' / 'p10' / 'fake_codex.py'} \"$@\"\n")
    opener = bin_dir / "xdg-open"
    names = " ".join(("APPDIR", "APPIMAGE", "PATH", "XDG_DATA_DIRS", "LD_LIBRARY_PATH", "GTK_PATH", "GTK_EXE_PREFIX",
                      "GTK_DATA_PREFIX", "GDK_PIXBUF_MODULE_FILE", "GIO_MODULE_DIR", "GI_TYPELIB_PATH",
                      "GSETTINGS_SCHEMA_DIR", "DBUS_SESSION_BUS_ADDRESS"))
    opener.write_text("#!/bin/sh\n"
                      f"for n in {names}; do eval \"printf '%s=%s\\n' $n \\\"\\${{$n-}}\\\"\"; done > {bin_dir / 'xdg-open.env'}\n"
                      f"printf '%s\\n' \"$1\" > {bin_dir / 'xdg-open.url'}\n")
    for tool in (codex, opener):
        tool.chmod(0o755)


REFUSALS: list = []


def new_research(api: Http, tag: str) -> str | None:
    status, made = api.json("POST", "/api/researches", {
        "question": f"{QUESTION} ({tag})", "source_scope": "attached", "effort": "quick", "model_connection": "codex",
        "requested_model": "gpt-fake", "reasoning_effort": "medium"})
    if status != 201:
        REFUSALS.append({"tag": tag, "status": status, "body": json.dumps(made)[:300]})
    return made["research"]["id"] if status == 201 else None


def start_load(sc: Scenario, bin_dir: Path) -> dict:
    """A hanging fake-codex answer (with its orphaned setsid grandchild), then a long PDF upload whose extraction child
    is running."""
    for marker in bin_dir.glob("*.json"):
        marker.unlink()
    api = sc.session()
    facts: dict = {}
    rid = new_research(api, f"{sc.fmt} {sc.name} answer")
    if rid:
        api.upload(f"/api/researches/{rid}/uploads", "synthetic.pdf",
                   make_pdf([f"SYNTHETIC page: a bounded molecule release schedule ({sc.name})."]))
        facts["answer_run"] = api.json("POST", f"/api/researches/{rid}/runs", {"kind": "answer"})[0]
    facts["research"] = rid
    if not rid:
        facts["refused"] = REFUSALS[-1:]
    facts["codex_hanging"] = bool(wait_for(lambda: (bin_dir / "codex-hang.json").exists(), 120, 0.5))
    facts["setsid_orphan"] = bool(wait_for(lambda: [p for p in proc_table().values() if p["cmd"] == "/bin/sleep 307"], 10))
    pdf_rid = new_research(api, f"{sc.fmt} {sc.name} pdf")
    pages = [f"SYNTHETIC page {i}: " + "a bounded molecule release schedule minimizes error. " * 40 for i in range(4000)]
    pdf = make_pdf(pages)
    facts["pdf_mb"] = round(len(pdf) / 1e6, 1)

    def upload():
        if pdf_rid:
            other = Http(sc.port)
            other.login()
            other.upload(f"/api/researches/{pdf_rid}/uploads", "synthetic-long.pdf", pdf, timeout=600)
    threading.Thread(target=upload, daemon=True).start()
    child = wait_for(lambda: next((p["pid"] for p in proc_table().values() if "deixis.documents.pdf" in p["cmd"]
                                   and p["exe"].endswith("/deixis-backend")), None), 120, 0.05)
    facts["pdf_child_running"] = bool(child)
    facts["hanging"] = facts["codex_hanging"] and facts["pdf_child_running"] and facts["setsid_orphan"]
    facts["load_processes"] = sorted({p["name"] for p in sc.watch.alive()})
    return facts


def close_window(sc: Scenario) -> bool:
    return subprocess.run(["wmctrl", "-c", "DEIXIS", "-F"], capture_output=True).returncode == 0


def screenshot(out: Path) -> bool:
    return subprocess.run(["import", "-window", "root", str(out)], capture_output=True, timeout=60).returncode == 0


def appimage_leaks(env: dict[str, str]) -> dict:
    appdir = env.get("APPDIR", "")
    named = {k: env[k] for k in APPIMAGE_NAMES if k in env}
    inside = {k: v for k, v in env.items() if "/.mount_" in v or (appdir and appdir in v)}
    return named | inside


# ------------------------------------------------------------------------------------------------------ rows ---

def install(fmt: str, package: Path, work: Path) -> tuple[str | None, list[str]]:
    """Installs one format; returns the executable to start and the marks of its install folder."""
    if fmt == "deb":
        done = subprocess.run(["sudo", "apt-get", "install", "-y", "--no-install-recommends", str(package)],
                              capture_output=True, text=True, timeout=600)
        exe = shutil.which("deixis-desktop") or "/usr/bin/deixis-desktop"
        backend = DEB_LIB / "sidecar" / "deixis-backend" / "deixis-backend"
        status = subprocess.run(["dpkg-query", "-W", "-f", "${Status} ${Version}", "deixis"], capture_output=True,
                                text=True).stdout
        indicator = subprocess.run(["dpkg-query", "-W", "-f", "${Status}", "libayatana-appindicator3-1"],
                                   capture_output=True, text=True).stdout
        ok = (done.returncode == 0 and os.access(exe, os.X_OK) and os.access(backend, os.X_OK)
              and "install ok installed" in indicator)
        row(f"{fmt}_install", ok, package=package.name, package_mb=round(package.stat().st_size / 1e6, 1),
            sha256=sha256(package), exit=done.returncode, dpkg=status, indicator_library=indicator,
            shell=exe, backend_executable=os.access(backend, os.X_OK), stderr=done.stderr[-400:] if done.returncode else "")
        return (exe if ok else None), [str(DEB_LIB), exe]
    target = work / package.name
    shutil.copy(package, target)
    target.chmod(0o755)
    ok = os.access(target, os.X_OK)
    row(f"{fmt}_install", ok, package=package.name, package_mb=round(package.stat().st_size / 1e6, 1),
        sha256=sha256(package), copied_to=str(target))
    return (str(target) if ok else None), [str(target), "/.mount_DEIXIS", "squashfs-root"]


def format_rows(fmt: str, exe: str, marks: list[str], work: Path, env: dict[str, str], bin_dir: Path, evidence: Path,
                wanted, scenarios: list[Scenario]) -> None:
    def scenario(name: str, driven: bool = True, extra: tuple[str, ...] = ()) -> Scenario:
        sc = Scenario(work, env, fmt, name, exe, marks)
        scenarios.append(sc)
        sc.launch(driven, extra)
        return sc

    if wanted("open"):
        sc = scenario("open")
        health_s, body = sc.wait_health()
        drv = sc.driver
        page = wait_for(lambda: drv and drv.url().startswith(f"http://127.0.0.1:{sc.port}/") and drv.url(), 30, 0.5) \
            if drv and health_s else None
        texts = wait_for(lambda: (t := drv.text()) and all(w in t for w in ("New research", "Library", "Settings")) and t,
                         20, 0.5) if page else None
        windows = wait_for(sc.windows, 20, 0.5) or []
        time.sleep(1)
        shot = screenshot(evidence / f"{fmt}-open.png")
        row(f"{fmt}_open", bool(body and body.get("nonce") and health_s and health_s <= 60 and page and texts
                                and len(windows) == 1 and shot),
            launch_to_health_s=round(health_s, 2) if health_s else None, port=sc.port, port_is_saved=sc.port == sc.saved_port,
            health_has_nonce=bool(body and body.get("nonce")), page_url=page, research_texts=bool(texts),
            windows=windows, screenshot=shot, driver=None if drv else sc.driver_error)

        if wanted("csrf_save"):
            if sc.api is None or drv is None:
                row(f"{fmt}_csrf_save", None, reason=f"no backend or no WebDriver ({sc.driver_error})")
            else:
                api = sc.session()
                time.sleep(2)
                before = api.json("GET", "/api/settings/preferences")[1].get("theme")
                refused = Http(sc.port).json("PUT", "/api/settings/preferences", {"theme": "dark"})[0]
                pressed = drv.click("Switch to dark mode", True) or drv.click("Switch to light mode", True)
                stored = wait_for(lambda: (t := api.json("GET", "/api/settings/preferences")[1].get("theme"))
                                  not in (None, before) and t, 10, 0.5)
                row(f"{fmt}_csrf_save", bool(pressed and stored and refused == 403), via="real click in the window",
                    pressed=pressed, theme_before=before, theme_stored=stored, put_without_csrf=refused)

        if wanted("pdf_tab"):
            if sc.api is None or drv is None:
                row(f"{fmt}_pdf_tab", None, reason=f"no backend or no WebDriver ({sc.driver_error})")
            else:
                api = sc.session()
                rid = new_research(api, f"{fmt} pdf tab")
                title = f"SYNTHETIC release schedules {fmt}"
                status, _ = api.upload(f"/api/researches/{rid}/uploads", f"{title}.pdf", make_pdf(
                    [f"{title}: page one of a synthetic paper.", "SYNTHETIC page two: the bounded schedule."]))

                def open_from_library():  # Library: the title opens the source sheet once its text is stored
                    drv.go(f"http://127.0.0.1:{sc.port}/#/library")
                    time.sleep(1.5)
                    return drv.click(title)
                opened = wait_for(open_from_library, 60, 2)
                pressed = wait_for(lambda: drv.click("Open PDF"), 20, 1) if opened else False
                drawn = wait_for(lambda: drv.eval("const c = document.querySelector('canvas[data-rendered-page]');"
                                                  " return c ? c.dataset.renderedPage : null"), 30, 0.5) if pressed else None
                screenshot(evidence / f"{fmt}-pdf-tab.png")
                row(f"{fmt}_pdf_tab", bool(status == 201 and opened and pressed and drawn), upload=status,
                    sheet_opened=bool(opened), open_pdf=bool(pressed), rendered_page=drawn,
                    page_text=None if drawn else drv.text()[:300])

        if wanted("second_launch"):
            count_before = sc.family()
            second = subprocess.run([exe], env=sc.env, timeout=60, capture_output=True)
            time.sleep(3)
            count_after = sc.family()
            row(f"{fmt}_second_launch", second.returncode == 0 and len(sc.windows()) == 1 and
                set(count_after) <= set(count_before), second_exit=second.returncode,
                processes_before=len(count_before), processes_after=len(count_after), windows=sc.windows())

        if wanted("env"):
            backend = sc.backend_pids()
            # The bootloader sets _PYI_* and LD_LIBRARY_PATH (its own _internal) for the backend itself and keeps what
            # it inherited in LD_LIBRARY_PATH_ORIG; child_env takes those back out for every child (sidecar smoke).
            seen = {k: v for k, v in (environ_of(backend[0]) if backend else {}).items()
                    if not k.startswith("_PYI_") and k != "LD_LIBRARY_PATH"}
            if drv:
                (bin_dir / "xdg-open.env").unlink(missing_ok=True)
                try:
                    drv.eval("window.location.href = 'https://example.org/deixis-acceptance'")
                except RuntimeError:
                    pass
                opened = wait_for(lambda: (bin_dir / "xdg-open.env").read_text(), 15, 0.5) or ""
            else:
                opened = ""
            opener_env = dict(line.split("=", 1) for line in opened.splitlines() if "=" in line)
            shell = sc.shell_pid()
            shell_env = environ_of(shell) if shell else {}
            row(f"{fmt}_env", bool(backend and not appimage_leaks(seen) and opened
                                   and not appimage_leaks({k: v for k, v in opener_env.items() if v})),
                in_appimage=bool(shell_env.get("APPDIR")), backend_leaks=appimage_leaks(seen),
                xdg_open_called=bool(opened), xdg_open_leaks=appimage_leaks({k: v for k, v in opener_env.items() if v}),
                shell_has_appdir_vars=sorted(k for k in shell_env if k in APPIMAGE_NAMES))

        if wanted("close_quits"):
            facts = start_load(sc, bin_dir)
            trigger = time.monotonic()
            closed = close_window(sc)
            left = sc.check_left(trigger)
            row(f"{fmt}_close_quits", left.pop("ok") and facts["hanging"] and closed, closed=closed, **facts, **left)
        sc.kill_all()

    if wanted("download"):
        # A launch of its own with the fake codex answering: its app-server keeps the hang setting it started with.
        for marker in bin_dir.glob("*.json"):
            marker.unlink()
        (bin_dir / "no-hang").write_text("")
        sc = scenario("download")
        downloads = Path(env["HOME"]) / "Downloads"
        drv = sc.driver
        if sc.wait_health()[0] is None or drv is None:
            row(f"{fmt}_download", None if drv is None else False,
                reason=f"no health within 60 s or no WebDriver ({sc.driver_error})")
        else:
            downloads.mkdir(exist_ok=True)
            (downloads / f"SYNTHETIC earlier download {fmt}.md").write_text("SYNTHETIC: must stay as it is\n")
            before = {p.name for p in downloads.glob("*")}
            api = sc.session()
            rid = new_research(api, f"{fmt} download")
            api.upload(f"/api/researches/{rid}/uploads", "synthetic.pdf", make_pdf(
                ["SYNTHETIC page: a bounded molecule release schedule minimizes the decoding error."]))
            _, run = api.json("POST", f"/api/researches/{rid}/runs", {"kind": "answer"})
            finished = wait_for(lambda: (r := next((x for x in api.json("GET", f"/api/researches/{rid}")[1].get("runs", [])
                                                    if x["id"] == run.get("id")), None))
                                and r["status"] in ("completed", "failed", "paused", "cancelled") and r, 240, 1)
            title = api.json("GET", f"/api/researches/{rid}")[1]["research"]["title"]
            drv.go(f"http://127.0.0.1:{sc.port}/#/research/{rid}")
            opened = wait_for(lambda: title[:40] in drv.text(), 30, 1)
            time.sleep(2)
            fresh = lambda suffix: sorted(p for p in downloads.glob(f"*{suffix}") if p.name not in before)  # noqa: E731
            kept_downloads = {p: sha256(p) for p in downloads.glob("*") if p.is_file()} if downloads.exists() else {}
            skip = {downloads, evidence, bin_dir, Path.cwd() / "acceptance.txt", *(x.data for x in scenarios),
                    *work.glob("driver-*.log"), *work.glob("shell-*.err")}  # this script's own logs
            roots = download_roots(Path(env["HOME"]), work)
            elsewhere_before = files_state(roots, skip)

            def export(item: str, suffix: str, count: int) -> bool:  # Export → item, until `count` new files are there
                return bool(wait_for(lambda: drv.click("Export", True), 20, 1)) and bool(wait_for(
                    lambda: drv.click(item), 10, 0.5)) and bool(wait_for(lambda: len(fresh(suffix)) >= count, 30))

            # Each export twice: the second must get a free name ("name (1).ext") and leave the first file as it was.
            steps = {"md_1": export("Markdown", ".md", 1)}
            first_md = {p: sha256(p) for p in fresh(".md")}
            steps["md_2"] = export("Markdown", ".md", 2)
            steps["csv_1"] = export("Comma-separated values", ".csv", 1)
            first_csv = {p: sha256(p) for p in fresh(".csv")}
            steps["csv_2"] = export("Comma-separated values", ".csv", 2)
            md, csv = fresh(".md"), fresh(".csv")
            kept_first = len(first_md) == 1 and len(first_csv) == 1 and all(
                p.exists() and sha256(p) == digest for p, digest in (first_md | first_csv).items())
            free_names = len(md) == 2 and len(csv) == 2 and {p.name for p in md + csv} == {
                name for first in (first_md | first_csv) for name in (first.name, f"{first.stem} (1){first.suffix}")}
            md_text = md[0].read_text(encoding="utf-8") if md else ""
            csv_text = csv[0].read_text(encoding="utf-8-sig") if csv else ""
            after_state = files_state(roots, skip)
            elsewhere = sorted(str(p) for p in set(after_state) | set(elsewhere_before)  # added, changed or removed
                               if elsewhere_before.get(p) != after_state.get(p))[:20]
            downloads_kept = all(p.is_file() and sha256(p) == digest for p, digest in kept_downloads.items())
            shell_log = work / f"driver-{fmt}-download.log"
            shell_said = [ln for ln in shell_log.read_text(errors="replace").splitlines() if "DEIXIS: Download" in ln
                          or "DEIXIS: download" in ln] if shell_log.exists() else []
            for path in md + csv:
                shutil.move(str(path), evidence / f"{fmt}-download-{path.name}")
            row(f"{fmt}_download", bool(all(steps.values()) and md and title in md_text and csv
                                        and "synthetic" in csv_text.lower() and kept_first and free_names and not elsewhere
                                        and downloads_kept),
                run=(finished or {}).get("status"), opened=bool(opened), steps=steps, files=[p.name for p in md + csv],
                first_files_unchanged=kept_first, second_got_free_name=free_names, written_elsewhere=elsewhere,
                earlier_downloads_unchanged=downloads_kept, earlier_downloads=len(kept_downloads),
                downloads_folder=str(downloads), report_bytes=len(md_text), csv_lines=len(csv_text.splitlines()),
                shell_said=shell_said[:8])

        sc.kill_all()
        (bin_dir / "no-hang").unlink(missing_ok=True)

    if wanted("kill_shell"):
        sc = scenario("kill_shell")
        if sc.wait_health()[0] is None:
            row(f"{fmt}_kill_shell", False, reason="no health within 60 s", driver=sc.driver_error)
        else:
            facts = start_load(sc, bin_dir)
            shell = sc.shell_pid()
            trigger = time.monotonic()
            killed = bool(shell) and os.kill(shell, signal.SIGKILL) is None
            left = sc.check_left(trigger)
            row(f"{fmt}_kill_shell", left.pop("ok") and facts["hanging"] and killed, shell=shell, **facts, **left)
        sc.kill_all()

    if wanted("kill_backend"):
        sc = scenario("kill_backend")
        if sc.wait_health()[0] is None or sc.driver is None:
            row(f"{fmt}_kill_backend", None if sc.driver is None else False,
                reason=f"no health within 60 s or no WebDriver ({sc.driver_error})")
        else:
            drv = sc.driver
            nonce = (health(sc.port) or {}).get("nonce")
            facts = start_load(sc, bin_dir)
            active: dict = {}
            if facts.get("research"):
                view = sc.session().json("GET", f"/api/researches/{facts['research']}")[1]
                run = next((r for r in view.get("runs", []) if r.get("status") == "running"), None)
                step = next((st for st in (run or {}).get("steps", []) or [] if st.get("status") == "running"), None)
                if run and step:
                    active = {"run": run["id"], "step": step.get("id") or step.get("operation_key")}
            backend = sc.backend_pids()
            shell = sc.shell_pid()
            old = {i: p for i, p in sc.watch.seen.items() if p["pid"] != shell and "WebKit" not in p["name"]
                   and p["exe"] != exe and not p["name"].startswith("DEIXIS_")}  # the AppImage runtime: the shell's
            trigger = time.monotonic()
            killed = len(backend) == 1 and os.kill(backend[0], signal.SIGKILL) is None
            old_gone = wait_for(lambda: not [i for i in old if alive(i)], LEFT_LIMIT, 0.2)
            old_left = [f"{p['pid']} {p['name']}" for i, p in old.items() if alive(i)]
            stopped_page = wait_for(lambda: "/index.html" in drv.url() and "Restart" in drv.text() and drv.text(), 20, 0.5)
            shell_alive = bool(shell) and any(p["pid"] == shell for p in proc_table().values())
            screenshot(evidence / f"{fmt}-backend-stopped.png")
            pressed = drv.click("Restart", True) if stopped_page else False
            restarted_s, body = sc.wait_health(40, time.monotonic()) if pressed else (None, None)
            new_nonce = (body or {}).get("nonce")
            integrity = keys = None
            run_state: dict = {}
            if restarted_s:
                with sqlite3.connect(f"file:{sc.data / 'library.sqlite'}?mode=ro", uri=True) as conn:
                    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                    keys = conn.execute("PRAGMA foreign_key_check").fetchall()
                if active:
                    view = sc.session().json("GET", f"/api/researches/{facts['research']}")[1]
                    run = next((r for r in view.get("runs", []) if r["id"] == active["run"]), {})
                    step = next((st for st in run.get("steps", []) or []
                                 if (st.get("id") or st.get("operation_key")) == active["step"]), {})
                    run_state = {"run": run.get("status"), "step": step.get("status"), "active_before_kill": active}
            closed = close_window(sc)
            left = sc.check_left(time.monotonic())
            ok = bool(killed and old_gone and shell_alive and stopped_page and pressed and restarted_s
                      and new_nonce and new_nonce != nonce and integrity == "ok" and keys == []
                      and run_state.get("run") == "paused" and run_state.get("step") == "outcome_unknown" and closed)
            row(f"{fmt}_kill_backend", ok and left.pop("ok") and facts["hanging"], backend_killed=killed,
                old_family_gone_15s=bool(old_gone), old_left=old_left, shell_alive_after_kill=shell_alive,
                stopped_page=(stopped_page or "")[:160], restart_pressed=bool(pressed),
                restarted_s=round(restarted_s, 2) if restarted_s else None, new_nonce=bool(new_nonce and new_nonce != nonce),
                integrity=integrity, foreign_keys=keys, interrupted=run_state, **facts, after_close=left)
        sc.kill_all()

    if fmt == "appimage" and wanted("no_fuse"):
        sc = scenario("no_fuse", driven=False, extra=("--appimage-extract-and-run",))
        health_s, body = sc.wait_health()
        windows = wait_for(sc.windows, 20, 0.5) or []
        closed = close_window(sc) if health_s else False
        left = sc.check_left(time.monotonic())
        row(f"{fmt}_no_fuse", bool(health_s and body and body.get("nonce") and windows and closed and left.pop("ok")),
            launch_to_health_s=round(health_s, 2) if health_s else None, windows=windows, closed=closed, **left)
        sc.kill_all()


def uninstall(fmt: str, exe: str | None, scenarios: list[Scenario]) -> None:
    def listing(folder: Path) -> dict[str, str]:  # every kept data file by content (logs and lock files aside)
        return {str(p.relative_to(folder)): sha256(p) for p in folder.rglob("*")
                if p.is_file() and p.suffix not in (".log", ".lock") and "-wal" not in p.name and "-shm" not in p.name}
    mine = [sc for sc in scenarios if sc.fmt == fmt]
    libraries = {sc.data: listing(sc.data) if (sc.data / "library.sqlite").is_file() else None for sc in mine}
    if fmt == "deb":
        done = subprocess.run(["sudo", "apt-get", "remove", "-y", "deixis"], capture_output=True, text=True, timeout=300)
        gone = not Path("/usr/bin/deixis-desktop").exists() and not DEB_LIB.exists()
        code = done.returncode
    else:
        Path(exe).unlink(missing_ok=True) if exe else None
        gone, code = not (exe and Path(exe).exists()), 0
    kept = {d.name: files is not None and d.is_dir() and listing(d) == files for d, files in libraries.items()}
    row(f"{fmt}_uninstall", bool(code == 0 and gone and all(kept.values())), exit=code, removed=gone, libraries_kept=kept)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deb", type=Path)
    parser.add_argument("--appimage", type=Path)
    parser.add_argument("--formats", default="deb,appimage")
    parser.add_argument("--evidence", type=Path, default=None)
    parser.add_argument("--only", default="", help="comma-separated rows (without the format prefix)")
    args = parser.parse_args()
    only = {r for r in args.only.split(",") if r}
    wanted = lambda name: not only or name in only  # noqa: E731
    work = Path(tempfile.mkdtemp(prefix="deixis-linux-acceptance-"))
    evidence = (args.evidence or work / "evidence").resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    bin_dir = work / "bin"
    bin_dir.mkdir()
    fake_tools(bin_dir, sys.executable)
    keep = ("HOME", "USER", "LOGNAME", "LANG", "DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR",
            "XDG_SESSION_TYPE", "SHELL")
    env = {k: os.environ[k] for k in keep if k in os.environ} | {
        "PATH": f"{bin_dir}:{os.path.dirname(shutil.which('tauri-driver') or '/usr/bin')}:/usr/local/bin:/usr/bin:/bin",
        "TMPDIR": str(work), "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
        "DEIXIS_DESKTOP_NO_DIALOG": "1",
        "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9", "NO_PROXY": "127.0.0.1,localhost"}
    print(json.dumps({"work": str(work), "evidence": str(evidence), "python": sys.version.split()[0],
                      "os": Path("/etc/os-release").read_text().split("PRETTY_NAME=")[-1].split("\n")[0],
                      "local_model_server": "not measured (needs the llama.cpp runtime and a model with their record)"}),
          flush=True)
    scenarios: list[Scenario] = []
    try:
        for fmt in [f for f in args.formats.split(",") if f]:
            package = args.deb if fmt == "deb" else args.appimage
            if package is None:
                continue
            package = package.resolve()  # apt-get installs a local .deb only by a path with a slash
            exe, marks = install(fmt, package, work)
            try:
                if exe:
                    format_rows(fmt, exe, marks, work, env, bin_dir, evidence, wanted, scenarios)
            finally:
                for sc in scenarios:
                    sc.kill_all()
                uninstall(fmt, exe, scenarios)
    finally:
        passed = sum(1 for r in results.values() if r["ok"] is True)
        summary = {"passed": passed, "failed": [n for n, r in results.items() if r["ok"] is False],
                   "not_done": [n for n, r in results.items() if r["ok"] is None],
                   "manual": [n for n, r in results.items() if r["ok"] == "manual"]}
        print(json.dumps(summary), flush=True)
        (evidence / "results.json").write_text(json.dumps({"summary": summary, "rows": results}, indent=1, default=str),
                                               encoding="utf-8")
        for log in list(work.glob("shell-*.err")) + list(work.glob("driver-*.log")):
            shutil.copy(log, evidence / log.name)
        for sc in scenarios:
            for name in ("backend.log", "desktop-reaper.log"):
                log = sc.data / "logs" / name
                if log.exists():
                    shutil.copy(log, evidence / f"{sc.fmt}-{sc.name}-{name}")
        shutil.rmtree(work, ignore_errors=True)
    return 0 if results and all(r["ok"] is True or r["ok"] == "manual" for r in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
