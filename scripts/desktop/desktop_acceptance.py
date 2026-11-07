"""Acceptance of the packaged DEIXIS.app on this Mac (P10 M2), macOS arm64.

    uv run python scripts/desktop/desktop_acceptance.py [--dmg desktop/src-tauri/target/release/bundle/dmg/DEIXIS_<version>_aarch64.dmg]
                                                    [--only ROW,...] [--keep]

The app is installed by copying DEIXIS.app out of the DMG into a temp folder outside the checkout and started there
by its executable, with a minimal environment: a temp HOME and DEIXIS_DATA_DIR per scenario (a port other than 8765
saved in it before the start, and DEIXIS_PORT set to another free port), the null keyring backend, no modal error
dialog (DEIXIS_DESKTOP_NO_DIALOG=1: a failed start prints and exits), outbound HTTP(S)
sent to a closed local port, and stand-in model CLIs first on PATH (fake_codex.py, fake_cli.py; run by this checkout's
Python). Never port 8765 or the owner's library. UI steps go through scripts/desktop/desktop_ui.swift (window list and
Accessibility; the terminal needs Accessibility access). Rows, each printed as PASS, FAIL, NOT_DONE or MANUAL (this
script cannot check it; a person does, as the row's note says). The exit code is 0 only when every row run is PASS or
MANUAL:

  install        DMG attached read-only, DEIXIS.app copied out, its signature verifies; .app and .dmg size
  open           the window is on screen and shows the research UI (its sidebar texts, read through
                 Accessibility from the WKWebView); health 200 within 60 s; launch-to-window and launch-to-health
                 timed; screenshot of the window (`screencapture -l`)
  csrf_save      inside the WKWebView, the sidebar's theme button is pressed (Accessibility) and the backend stores
                 the new theme: the web app's own session-cookie + header save
  browser        the packaged backend in Chrome (and Playwright's WebKit when its build for this Playwright is
                 installed): JS and CSS load, React renders, language and theme saved through the UI survive a restart
                 on another port (scripts/desktop/browser_check.mjs)
  second_launch  starting the executable again adds no process (the new one exits) and the window comes back
  close_keeps    the window's close button hides it; every process stays
  quit_plain     Quit (the app's quit, as Cmd+Q or the menu-bar Quit; sent with NSRunningApplication.terminate)
                 leaves no DEIXIS process within 15 s
  quit_codex     the same under a hanging model step, one launch per CLI (the worker runs one run at a time): fake
  quit_gemini    codex (in the backend's group), gemini (own session; its step starts an intermediate that leaves a
  quit_copilot   grandchild in another process group of that session and exits at once) and copilot (own session)
  quit_pdf       the same during a PDF extraction with its memory guard running
  quit_server    a local model server: MANUAL (it cannot be faked cheaply: the llama.cpp runtime record)
  quit_forced    the same while a long model call holds the shutdown: the backend ends by its 6 s exit (the
                 watchdog logs `forced_exit` when the backend's stderr says so)
  download       in the installed app's window a finished research's report (Markdown, a blob: download) and the
                 sources CSV are downloaded through the UI; both files land in HOME/Downloads with their content
  kill_shell     `kill -9` of the app's process under the gemini step: nothing left within 15 s
  kill_backend   `kill -9` of the backend under the gemini step: nothing left within 15 s; the window shows
                 the "backend stopped" page (screenshot); its Restart starts a new backend; then Quit
  tray           the menu-bar item exists; its menu cannot be opened through Accessibility: MANUAL
  ocr            OCR with the app's own language data (P10 M3): /api/ocr says bundled, engine pymupdf, eng+tur, its folder
                 inside the installed .app; a scanned SYNTHETIC page read by the app's OCR run gives its words; no
                 `tesseract` process was seen (Homebrew's stays installed, the frozen app never asks it)
  theme          the window follows Settings' theme (P10 M3): Dark saved through the API reaches the shell's
                 `window-theme` file within one status poll; after Quit the next launch shows a dark first frame
                 (screenshot of the launch page, mean brightness) and its page's prefers-color-scheme is dark

Rows that drive the window (open, csrf_save, second_launch, close_keeps, the Restart half of kill_backend, download)
are NOT_DONE while the screen is locked (the frontmost app is loginwindow): no window can come to the front then, and
its web content is not readable through Accessibility.

"Nothing left" is checked three ways: every process the watcher saw for the scenario (the app's subtree, its process
groups and sessions, anything whose command names the scenario's folders; sampled every 0.2 s for the whole run, so
children started on their own and orphans are seen) is gone; `lsof` finds no open file in the data folder; and a
process table diff (pid + start time, before the launch and 15 s after) lists every new live process with why it is
not DEIXIS, or the row fails. A new process is "not related" only when nothing ties it to the scenario and it is not
an orphan (parent launchd) running a program DEIXIS or its stand-ins run (python, sh, sleep, node, deixis-backend). Every record is SYNTHETIC. Passing shows these paths on this Mac, not a clean machine.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import sqlite3
from contextlib import closing
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "tests" / "support")]
from helpers import make_pdf, make_scanned_pdf  # noqa: E402

from deixis.tools import child_record  # noqa: E402

HERE = Path(__file__).resolve().parent
VERSION = json.loads((REPO / "desktop" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))["version"]
DMG = REPO / "desktop" / "src-tauri" / "target" / "release" / "bundle" / "dmg" / f"DEIXIS_{VERSION}_aarch64.dmg"
OWNER_PORT = 8765
LEFT_LIMIT = 15.0
QUESTION = "How is molecule release scheduling optimized in SYNTHETIC diffusion channels?"
results: dict[str, dict] = {}


MANUAL = "manual"
GENERIC = ("python", "sh", "bash", "zsh", "sleep", "node", "deixis-backend", "codex", "gemini", "copilot")


def row(name: str, ok: bool | None | str, **facts) -> None:
    results[name] = {"ok": ok, **facts}
    word = "MANUAL" if ok == MANUAL else "NOT_DONE" if ok is None else "PASS" if ok else "FAIL"
    print(f"{word} {name} {json.dumps(facts, default=str)}", flush=True)


def free_port() -> int:
    while True:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if port != OWNER_PORT:
            return port


def commands() -> dict[int, str]:
    done = subprocess.run(["ps", "-axww", "-o", "pid=,command="], capture_output=True, text=True)
    found = {}
    for line in done.stdout.splitlines():
        pid, _, command = line.strip().partition(" ")
        if pid.isdigit():
            found[int(pid)] = command.strip()
    return found


def table() -> dict[str, dict]:
    """Every visible process: identity -> pid, ppid, pgid, sid, command."""
    names = commands()
    found = {}
    for pid, (ppid, pgid, start) in child_record.snapshot().items():
        try:
            sid = os.getsid(pid)
        except OSError:
            sid = -1
        found[f"{pid}:{start}"] = {"pid": pid, "ppid": ppid, "pgid": pgid, "sid": sid, "command": names.get(pid, "")}
    return found


class Watcher:
    """Samples the process table every 0.2 s for the whole scenario and keeps every DEIXIS process it sees."""

    def __init__(self, marks: list[str]):
        self.marks = marks
        self.roots: set[int] = set()
        self.seen: dict[str, dict] = {}
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def sample(self) -> None:
        procs = table()
        mine = {os.getpgrp(), os.getsid(0), 0, 1}  # this script's own group and session are never DEIXIS's
        groups = ({p["pgid"] for p in self.seen.values()} | {p["sid"] for p in self.seen.values()}) - mine
        changed = True
        while changed:
            changed = False
            pids = {p["pid"] for i, p in self.seen.items() if i in procs} | self.roots
            for ident, proc in procs.items():
                if ident in self.seen:
                    continue
                if (proc["ppid"] in pids or proc["pid"] in self.roots or any(m in proc["command"] for m in self.marks)
                        or (proc["pgid"] in groups and proc["pgid"] > 1) or (proc["sid"] in groups and proc["sid"] > 1)):
                    self.seen[ident] = proc
                    groups |= {proc["pgid"], proc["sid"]} - mine
                    changed = True

    def run(self) -> None:
        while not self.stop.is_set():
            self.sample()
            self.stop.wait(0.2)

    def alive(self) -> list[dict]:
        now = table()
        return [self.seen[i] | {"ident": i} for i in self.seen if i in now]

    def close(self) -> None:
        self.stop.set()
        self.thread.join(2)


class Scenario:
    """One launch of the installed app with its own data folder."""

    def __init__(self, work: Path, app: Path, env: dict[str, str], name: str, data: Path | None = None):
        self.name, self.app = name, app
        self.data = data or work / f"data-{name}"  # `data`: another scenario's library, started again
        self.data.mkdir(exist_ok=data is not None)
        self.port = free_port()
        (self.data / "desktop-port.json").write_text(json.dumps({"port": self.port}))
        self.env = env | {"DEIXIS_DATA_DIR": str(self.data), "DEIXIS_PORT": str(free_port())}
        self.before = set(table())
        self.watch = Watcher([str(app), str(work / "bin"), str(self.data), str(HERE / "fake_")])
        self.proc: subprocess.Popen | None = None
        self.started = 0.0
        self.client: httpx.Client | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def launch(self) -> None:
        self.started = time.monotonic()
        # Its own session, as an app started from the Finder is: nothing of this script's session is counted as DEIXIS.
        self.proc = subprocess.Popen([str(self.app / "Contents" / "MacOS" / "deixis-desktop")], env=self.env,
                                     start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=open(self.data.parent / f"shell-{self.name}.err", "wb"))
        self.watch.roots.add(self.proc.pid)
        self.watch.start()

    def wait_health(self, seconds: float = 60, since: float | None = None) -> float | None:
        ends = (self.started if since is None else since) + seconds
        while time.monotonic() < ends:
            try:
                if httpx.get(f"{self.url}/api/health", timeout=2, trust_env=False).status_code == 200:
                    return time.monotonic() - self.started
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        return None

    def session(self) -> httpx.Client:
        if self.client is None:
            self.client = httpx.Client(base_url=self.url, timeout=60, trust_env=False)
            self.client.headers["x-deixis-csrf"] = self.client.get("/api/session").json()["csrf_token"]
        return self.client

    def backend_pid(self) -> int | None:
        for proc in table().values():
            if "serve --desktop" in proc["command"] and str(self.app) in proc["command"]:
                return proc["pid"]
        return None

    def check_left(self, trigger: float) -> dict:
        """Within 15 s of `trigger` nothing of this scenario may be alive; then the lsof and table checks."""
        while time.monotonic() < trigger + LEFT_LIMIT and self.watch.alive():
            time.sleep(0.2)
        gone_s = time.monotonic() - trigger
        left = self.watch.alive()
        self.watch.close()
        time.sleep(max(0.0, trigger + LEFT_LIMIT - time.monotonic()))
        done = subprocess.run(["lsof", "-n", "+D", str(self.data)], capture_output=True, text=True)
        open_files = [line for line in done.stdout.splitlines()[1:] if line.strip()]
        new = {i: p for i, p in table().items() if i not in self.before}
        mine = os.getpid()
        explained, unexplained = [], []
        for ident, proc in new.items():
            if ident in self.watch.seen:
                unexplained.append(proc | {"why": "seen as DEIXIS of this scenario"})
            elif proc["pid"] == mine or proc["ppid"] == mine:
                explained.append(f"{proc['pid']} this acceptance script: {proc['command'][:80]}")
            elif any(m in proc["command"] for m in self.watch.marks):
                unexplained.append(proc | {"why": "names this scenario's folders"})
            elif proc["ppid"] == 1 and Path(proc["command"].split(" ")[0]).name.startswith(GENERIC):
                unexplained.append(proc | {"why": "an orphan running a program DEIXIS runs"})
            else:
                explained.append(f"{proc['pid']} (parent {proc['ppid']}) not related (no ancestry, group, session or "
                                 f"folder): {proc['command'][:100]}")
        return {"ok": not left and not open_files and not unexplained, "all_gone_s": round(gone_s, 2),
                "seen": len(self.watch.seen), "left": [p["command"][:120] for p in left], "open_files": open_files[:5],
                "unexplained": unexplained[:5], "new_processes_explained": explained[:12]}

    def kill_all(self) -> None:
        """Cleanup after a failure: only what this scenario started."""
        for proc in self.watch.alive():
            try:
                os.kill(proc["pid"], signal.SIGKILL)
            except OSError:
                pass
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
        self.watch.close()


class UI:
    def __init__(self, binary: Path):
        self.binary = binary

    def __call__(self, *args: str) -> dict | list | None:
        done = subprocess.run([str(self.binary), *args], capture_output=True, text=True, timeout=30)
        try:
            return json.loads(done.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return None

    def locked(self) -> bool:
        return (self("front", "1") or {}).get("front") == "com.apple.loginwindow"

    def window(self, pid: int) -> dict | None:
        found = [w for w in self("windows", str(pid)) or [] if w.get("layer") == 0 and w.get("name") == "DEIXIS"]
        return found[0] if found else None


def brightness(png: Path) -> float:
    """The mean of a screenshot's grey values, 0 (black) to 255 (white)."""
    import pymupdf

    base = pymupdf.Pixmap(str(png))
    pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.Pixmap(base, 0) if base.alpha else base)
    samples = pix.samples
    return round(sum(samples) / len(samples), 1)


def wait_for(check, seconds: float, step: float = 0.2):
    ends = time.monotonic() + seconds
    while time.monotonic() < ends:
        if (value := check()):
            return value
        time.sleep(step)
    return None


def start_model_steps(sc: Scenario, bin_dir: Path, connections: list[tuple[str, str]]) -> dict:
    """One research per connection, a synthetic PDF as its only source, an answer run; until each CLI hangs."""
    client = sc.session()
    started = {}
    for connection, model in connections:
        body = {"question": f"{QUESTION} ({connection})", "source_scope": "attached", "effort": "quick",
                "model_connection": connection, "requested_model": model}
        made = client.post("/api/researches", json=body | ({"reasoning_effort": "medium"} if connection == "codex" else {}))
        if made.status_code != 201:
            started[connection] = f"create {made.status_code}: {made.text[:200]}"
            continue
        rid = made.json()["research"]["id"]
        pdf = make_pdf([f"SYNTHETIC page: a bounded molecule release schedule ({connection})."])
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("synthetic.pdf", pdf, "application/pdf")})
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"})
        started[connection] = run.status_code
    names = {"codex": "codex-hang.json", "gemini_cli": "gemini-hang.json", "copilot_cli": "copilot-hang.json"}
    wanted = [bin_dir / names[c] for c, _m in connections] + ([bin_dir / "gemini-grandchild.json"]
                                                             if any(c == "gemini_cli" for c, _m in connections) else [])
    ready = wait_for(lambda: all(p.exists() for p in wanted), 90)
    time.sleep(1.5)  # a few watchdog scans
    facts = {"runs": started, "hanging": bool(ready)}
    if (bin_dir / "gemini-grandchild.json").exists():
        grand = json.loads((bin_dir / "gemini-grandchild.json").read_text())
        hung = json.loads((bin_dir / "gemini-hang.json").read_text()) if (bin_dir / "gemini-hang.json").exists() else {}
        info = table()
        gpid = grand["grandchild"]
        current = next((p for p in info.values() if p["pid"] == gpid), {})
        facts["grandchild"] = {"pid": gpid, "pgid": current.get("pgid"), "ppid": current.get("ppid"),
                               "cli_pgid": hung.get("pgid"), "other_group": current.get("pgid") != hung.get("pgid")}
    return facts


def wait_run(client: httpx.Client, rid: str, run_id: str, seconds: float = 180) -> tuple[dict, dict]:
    ends = time.monotonic() + seconds
    while time.monotonic() < ends:
        view = client.get(f"/api/researches/{rid}").json()
        run = next(r for r in view["runs"] if r["id"] == run_id)
        if run["status"] in ("completed", "failed", "paused", "cancelled"):
            return view, run
        time.sleep(0.5)
    return view, run


def clear_markers(bin_dir: Path) -> None:
    for path in bin_dir.glob("*.json"):
        path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dmg", type=Path, default=DMG)
    parser.add_argument("--only", default="", help="comma-separated rows (scenario names) to run")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    only = {r for r in args.only.split(",") if r}
    wanted = lambda name: not only or name in only  # noqa: E731
    work = Path(tempfile.mkdtemp(prefix="deixis-desktop-acceptance-"))
    assert not work.resolve().is_relative_to(REPO.resolve())
    scenarios: list[Scenario] = []
    try:
        ui_binary = work / "desktop_ui"
        subprocess.run(["swiftc", "-O", str(HERE / "desktop_ui.swift"), "-o", str(ui_binary)], check=True,
                       capture_output=True)
        ui = UI(ui_binary)
        mount = work / "mnt"
        subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mount), str(args.dmg)],
                       check=True, capture_output=True)
        try:
            (work / "Applications").mkdir()
            subprocess.run(["ditto", str(mount / "DEIXIS.app"), str(work / "Applications" / "DEIXIS.app")], check=True)
        finally:
            subprocess.run(["hdiutil", "detach", str(mount)], capture_output=True)
        app = work / "Applications" / "DEIXIS.app"
        verify = subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], capture_output=True, text=True)
        size = sum(p.stat().st_size for p in app.rglob("*") if p.is_file() and not p.is_symlink())
        row("install", verify.returncode == 0, dmg_mb=round(args.dmg.stat().st_size / 1e6, 1), app_mb=round(size / 1e6, 1),
            codesign=verify.stderr.strip()[-200:] or "valid")

        bin_dir = work / "bin"
        bin_dir.mkdir()
        python = sys.executable
        launchers = {
            # A hanging model call unless the download row has put `no-hang` there (it needs a finished answer).
            "codex": f"[ -e {bin_dir / 'no-hang'} ] || export _FAKE_CODEX_HANG=1; "
                     f"_FAKE_CODEX_DIR={bin_dir} exec {python} {HERE / 'fake_codex.py'} \"$@\"",
            "gemini": f"_FAKE_CLI_DIR={bin_dir} exec {python} {HERE / 'fake_cli.py'} gemini \"$@\"",
            "copilot": f"_FAKE_CLI_DIR={bin_dir} exec {python} {HERE / 'fake_cli.py'} copilot \"$@\"",
        }
        for name, line in launchers.items():
            (bin_dir / name).write_text(f"#!/bin/sh\n{line}\n")
            (bin_dir / name).chmod(0o755)
        home = work / "home"
        (home / ".gemini").mkdir(parents=True)
        (home / ".gemini" / "oauth_creds.json").write_text("{}")  # only its existence is checked, never read
        (work / "tmp").mkdir()
        env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin", "TMPDIR": str(work / "tmp"),
               "LANG": "en_US.UTF-8", "USER": os.environ.get("USER", "acceptance"), "SHELL": "/bin/sh",
               "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
               "DEIXIS_DESKTOP_NO_DIALOG": "1",  # a failed start prints its message and exits; no modal on the screen
               "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9", "NO_PROXY": "127.0.0.1,localhost"}
        models = [("codex", "gpt-fake"), ("gemini_cli", "gemini-2.5-flash"), ("copilot_cli", "fake-copilot")]
        gemini = [models[1]]  # the CLI whose step leaves an orphaned grandchild in another process group

        locked = "the screen is locked: no window comes to the front and its web content cannot be read"
        if wanted("open") and ui.locked():
            sc = Scenario(work, app, env, "open")
            scenarios.append(sc)
            sc.launch()
            health_s = sc.wait_health()
            for name in ("open", "csrf_save", "second_launch", "close_keeps"):
                row(name, None, reason=locked, **({"launch_to_health_s": round(health_s, 2) if health_s else None}
                                                  if name == "open" else {}))
            row("tray", MANUAL, menu_bar_items=(ui("tray-count", str(sc.proc.pid)) or {}).get("items"))
            trigger = time.monotonic()
            ui("terminate", str(sc.proc.pid))
            facts = sc.check_left(trigger)
            row("quit_plain", facts.pop("ok"), shell_exit=sc.proc.poll(), **facts)
        elif wanted("open"):
            sc = Scenario(work, app, env, "open")
            scenarios.append(sc)
            sc.launch()
            window = wait_for(lambda: (w := ui.window(sc.proc.pid)) and w.get("onscreen") and w, 60, 0.05)
            window_s = time.monotonic() - sc.started if window else None
            health_s = sc.wait_health()
            time.sleep(3)  # the page renders
            shot = work / "open-window.png"
            capture = None
            if window:
                activated = ui("activate", str(sc.proc.pid))  # in front, so Stage Manager shows no thumbnail
                time.sleep(1)
                capture = subprocess.run(["screencapture", "-x", "-o", "-l", str(window["id"]), str(shot)],
                                         capture_output=True, text=True)
            shown = ui("texts", str(sc.proc.pid)) or []
            research_ui = all(any(text == want for text in shown) for want in ("New research", "Library", "Settings"))
            row("open", bool(window and health_s is not None and health_s <= 60 and shot.exists() and research_ui),
                research_ui=research_ui, texts_read=len(shown),
                launch_to_window_s=round(window_s, 2) if window_s else None,
                launch_to_health_s=round(health_s, 2) if health_s else None, port=sc.port, screenshot=str(shot),
                activated=activated if window else None,
                capture=(capture.returncode, capture.stderr.strip()[-200:]) if capture else None)

            before = sc.session().get("/api/settings/preferences").json().get("theme")

            def press_theme():
                for label in ("Switch to dark mode", "Switch to light mode"):
                    if (done := ui("press", str(sc.proc.pid), label)) and done.get("pressed"):
                        return done
                return None
            pressed = wait_for(press_theme, 20, 1) or ui("press", str(sc.proc.pid), "Switch to dark mode")
            stored = wait_for(lambda: sc.session().get("/api/settings/preferences").json().get("theme") not in (None, before)
                              and sc.session().get("/api/settings/preferences").json().get("theme"), 10)
            log = (sc.data / "logs" / "backend.log").read_text(encoding="utf-8", errors="replace")
            row("csrf_save", bool((pressed or {}).get("pressed") and stored),
                pressed=pressed, theme_before=before, theme_stored=stored,
                put_logged='"PUT /api/settings/preferences HTTP/1.1" 200' in log)

            family = lambda: sorted(p["pid"] for p in sc.watch.alive())  # noqa: E731
            count_before = family()
            second = subprocess.run([str(app / "Contents" / "MacOS" / "deixis-desktop")], env=sc.env, timeout=30,
                                    capture_output=True, start_new_session=True)
            time.sleep(3)
            count_after = family()
            back = ui.window(sc.proc.pid)
            row("second_launch", second.returncode == 0 and count_after == count_before and bool(back and back["onscreen"]),
                second_exit=second.returncode, processes_before=len(count_before), processes_after=len(count_after),
                window_onscreen=bool(back and back["onscreen"]))

            closed = ui("close", str(sc.proc.pid))
            time.sleep(2)
            hidden = ui.window(sc.proc.pid)
            healthy = sc.wait_health(5, time.monotonic()) is not None
            row("close_keeps", bool((closed or {}).get("closed") and hidden and not hidden["onscreen"]
                                    and family() == count_before and healthy),
                closed=closed, window_onscreen=bool(hidden and hidden["onscreen"]), processes=len(family()),
                health=healthy)
            subprocess.run([str(app / "Contents" / "MacOS" / "deixis-desktop")], env=sc.env, timeout=30, capture_output=True,
                           start_new_session=True)  # shows the hidden window again

            row("tray", MANUAL, menu_bar_items=(ui("tray-count", str(sc.proc.pid)) or {}).get("items"),
                note="the item exists; its menu (Open, running count, Quit) does not open through Accessibility, "
                     "so the count and the menu's Quit are a manual check; Quit itself is the same quit() as Cmd+Q")

            trigger = time.monotonic()
            ui("terminate", str(sc.proc.pid))
            facts = sc.check_left(trigger)
            row("quit_plain", facts.pop("ok"), shell_exit=sc.proc.poll(), **facts)

        if wanted("browser"):
            browser_data = work / "data-browser"
            done = subprocess.run(["node", str(HERE / "browser_check.mjs"), str(app / "Contents" / "Resources" / "sidecar"
                                                                               / "deixis-backend" / "deixis-backend"),
                                   str(browser_data), json.dumps(env)], cwd=REPO / "web", capture_output=True, text=True,
                                  timeout=600)
            try:
                found = json.loads(done.stdout.strip().splitlines()[-1])
            except (ValueError, IndexError):
                found = {"ok": False, "stdout": done.stdout[-600:], "stderr": done.stderr[-600:]}
            row("browser", found.pop("ok", False), **found)

        def quit_with_load(name: str, load, trigger_action) -> None:
            clear_markers(bin_dir)
            sc = Scenario(work, app, env, name)
            scenarios.append(sc)
            sc.launch()
            if sc.wait_health() is None:
                row(name, False, reason="no health within 60 s")
                return
            facts = load(sc)
            backend = sc.backend_pid()
            trigger = time.monotonic()
            extra = trigger_action(sc, backend) or {}
            left = sc.check_left(trigger)
            reaper_log = sc.data / "logs" / "desktop-reaper.log"
            tail = reaper_log.read_text(encoding="utf-8").splitlines()[-3:] if reaper_log.exists() else []
            verdict = extra.pop("ok", True)
            ok = left.pop("ok") and facts.get("hanging", True)
            row(name, (None if ok else False) if verdict is None else ok and verdict,
                **facts, **extra, **left, shell_exit=sc.proc.poll(), reaper_log=tail)

        def terminate(sc: Scenario, _backend) -> dict:
            ui("terminate", str(sc.proc.pid))
            return {}

        # The worker runs one run at a time, so each CLI's hanging model step is its own launch and Quit.
        for connection, model in models:
            name = f"quit_{connection.removesuffix('_cli')}"
            if wanted(name) or wanted("quit_models"):
                quit_with_load(name, lambda sc, c=connection, m=model: start_model_steps(sc, bin_dir, [(c, m)]), terminate)

        if wanted("quit_pdf"):
            def pdf_load(sc: Scenario) -> dict:
                client = sc.session()
                made = client.post("/api/researches", json={"question": QUESTION + " (pdf)", "source_scope": "attached",
                                                            "effort": "quick", "model_connection": "codex",
                                                            "requested_model": "gpt-fake", "reasoning_effort": "medium"})
                rid = made.json()["research"]["id"]
                pages = [f"SYNTHETIC page {i}: " + "a bounded molecule release schedule minimizes error. " * 40
                         for i in range(1500)]
                pdf = make_pdf(pages)
                threading.Thread(target=lambda: client.post(f"/api/researches/{rid}/uploads", timeout=300, files={
                    "file": ("synthetic-long.pdf", pdf, "application/pdf")}), daemon=True).start()
                running = wait_for(lambda: (lambda c: any("deixis.documents.pdf" in v for v in c.values())
                                            and any("deixis.documents.child_guard" in v for v in c.values()))(commands()),
                                   60, 0.05)
                time.sleep(0.6)
                return {"hanging": bool(running), "pdf_mb": round(len(pdf) / 1e6, 1),
                        "extraction_and_guard_running": bool(running)}
            quit_with_load("quit_pdf", pdf_load, terminate)

        if wanted("quit_server"):
            row("quit_server", MANUAL, note="a local model server needs the llama.cpp runtime and a model installed with "
                                          "their integrity record (llama_runtime.server_matches); not faked here")

        if wanted("quit_forced"):
            def forced(sc: Scenario, backend) -> dict:
                stopping = time.monotonic()
                ui("terminate", str(sc.proc.pid))
                ended = wait_for(lambda: backend is None or child_record.process_info(backend) is None, 14, 0.05)
                return {"backend_ended_s": round(time.monotonic() - stopping, 2) if ended else None}
            def forced_check(name: str) -> None:
                quit_with_load(name, lambda sc: start_model_steps(sc, bin_dir, [("codex", "gpt-fake")]), forced)
                log = (work / f"data-{name}" / "logs" / "desktop-reaper.log")
                text = log.read_text(encoding="utf-8") if log.exists() else ""
                results[name]["forced_exit_seen"] = "forced_exit:" in text
                if not results[name]["forced_exit_seen"]:
                    results[name]["ok"] = False
                print(f"     {name} forced_exit_seen={results[name]['forced_exit_seen']}", flush=True)
            forced_check("quit_forced")

        if wanted("kill_shell"):
            def kill_shell(sc: Scenario, _backend) -> dict:
                os.kill(sc.proc.pid, signal.SIGKILL)
                return {}
            quit_with_load("kill_shell", lambda sc: start_model_steps(sc, bin_dir, gemini), kill_shell)

        if wanted("kill_backend"):
            def kill_backend(sc: Scenario, backend) -> dict:
                if backend is None:
                    return {"ok": False, "backend": None}
                os.kill(backend, signal.SIGKILL)
                stopped = wait_for(lambda: child_record.process_info(backend) is None, 5, 0.05)
                time.sleep(3)  # the watchdog cleans up; the window shows the stopped page
                if ui.locked():
                    left_now = [p for p in sc.watch.alive() if p["pid"] != sc.proc.pid]
                    ui("terminate", str(sc.proc.pid))
                    return {"ok": None if stopped and sc.proc.poll() is None and not left_now else False,
                            "reason": locked + " (the stopped page and its Restart are not checked)",
                            "left_before_quit": [p["command"][:80] for p in left_now]}
                shot = work / "backend-stopped.png"
                window = ui.window(sc.proc.pid)
                if window:
                    ui("activate", str(sc.proc.pid))
                    time.sleep(1)
                    subprocess.run(["screencapture", "-x", "-o", "-l", str(window["id"]), str(shot)], capture_output=True)
                alive_shell = sc.proc.poll() is None
                stopped_page = "Restart" in (ui("texts", str(sc.proc.pid)) or [])
                left_now = [p for p in sc.watch.alive() if p["pid"] != sc.proc.pid]
                # The page's Restart starts a new backend (on the saved port); no automatic restart before it.
                pressed = ui("press", str(sc.proc.pid), "Restart")
                restarted = sc.wait_health(30, time.monotonic()) is not None
                new_backend = sc.backend_pid()
                ui("terminate", str(sc.proc.pid))
                return {"ok": bool(stopped and alive_shell and shot.exists() and stopped_page and not left_now
                                   and restarted and new_backend not in (None, backend)), "stopped_page": stopped_page,
                        "screenshot": str(shot), "shell_alive_after_kill": alive_shell,
                        "left_before_quit": [p["command"][:80] for p in left_now],
                        "restart_pressed": (pressed or {}).get("pressed"), "restarted": restarted}
            quit_with_load("kill_backend", lambda sc: start_model_steps(sc, bin_dir, gemini), kill_backend)
        if wanted("ocr"):
            sc = Scenario(work, app, env, "ocr")
            scenarios.append(sc)
            sc.launch()
            if sc.wait_health() is None:
                row("ocr", False, reason="no health within 60 s")
            else:
                client = sc.session()
                tool = client.get("/api/ocr").json()
                inside = bool(tool.get("path")) and Path(tool["path"]).resolve().is_relative_to(app.resolve())
                facts = {k: tool.get(k) for k in ("bundled", "engine", "languages", "version", "path", "reason")}
                made = client.post("/api/researches", json={"question": "SYNTHETIC scanned question?", "source_scope": "attached",
                                                            "effort": "quick", "model_connection": "codex",
                                                            "requested_model": "gpt-fake", "reasoning_effort": "medium"})
                rid = made.json()["research"]["id"]
                uploaded = client.post(f"/api/researches/{rid}/uploads", files={"file": ("synthetic-scan.pdf", make_scanned_pdf(
                    [("scan", "SYNTHETIC scanned page about bounded release schedules")]), "application/pdf")}).json()
                svid = uploaded.get("uploaded_source_version_id")
                with closing(sqlite3.connect(f"file:{sc.data / 'library.sqlite'}?mode=ro", uri=True)) as conn:
                    asset = conn.execute("SELECT id FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL",
                                         (svid,)).fetchone()
                started = client.post(f"/api/researches/{rid}/sources/{svid}/assets/{asset[0] if asset else ''}/ocr")
                run = wait_run(client, rid, started.json()["id"])[1] if started.status_code == 202 else {}
                with closing(sqlite3.connect(f"file:{sc.data / 'library.sqlite'}?mode=ro", uri=True)) as conn:
                    text = " ".join(r[0] for r in conn.execute(
                        "SELECT text FROM passages WHERE asset_id = ? AND text_source = 'ocr'", (asset[0] if asset else "",)))
                asked = [p["command"][:100] for p in sc.watch.seen.values() if "tesseract" in Path(p["command"].split(" ")[0]).name]
                row("ocr", bool(tool.get("bundled") and tool.get("engine") == "pymupdf" and tool.get("languages") == ["eng", "tur"]
                                and inside and run.get("status") == "completed" and "release" in text.lower() and not asked),
                    **facts, data_inside_app=inside, start=started.status_code, run=run.get("status"),
                    failure=run.get("failure_reason"), text=text[:80], tesseract_processes=asked)
            trigger = time.monotonic()
            ui("terminate", str(sc.proc.pid))
            sc.check_left(trigger)
        if wanted("theme"):
            saved = home / "Library" / "Application Support" / "org.deixis.desktop" / "window-theme"
            sc = Scenario(work, app, env, "theme")
            scenarios.append(sc)
            sc.launch()
            facts: dict = {}
            if sc.wait_health() is None:
                row("theme", False, reason="no health within 60 s")
            else:
                put = sc.session().put("/api/settings/preferences", json={"theme": "dark"})
                kept = wait_for(lambda: saved.is_file() and saved.read_text().strip() == "dark", 12, 0.25)
                facts |= {"put": put.status_code, "window_theme_file": saved.read_text().strip() if saved.is_file() else None}
                trigger = time.monotonic()
                ui("terminate", str(sc.proc.pid))
                sc.check_left(trigger)
                again = Scenario(work, app, env, "theme-again", data=sc.data)  # the same library, which holds Dark
                scenarios.append(again)
                again.launch()
                if ui.locked():
                    healthy = again.wait_health() is not None
                    stored = again.session().get("/api/settings/preferences").json().get("theme") if healthy else None
                    row("theme", None if kept and stored == "dark" else False, reason=locked, theme_after_restart=stored, **facts)
                else:
                    window = wait_for(lambda: (w := ui.window(again.proc.pid)) and w.get("onscreen") and w, 60, 0.05)
                    shot = work / "theme-launch.png"
                    if window:
                        subprocess.run(["screencapture", "-x", "-o", "-l", str(window["id"]), str(shot)], capture_output=True)
                    first = brightness(shot) if shot.exists() else None
                    healthy = again.wait_health() is not None
                    stored = again.session().get("/api/settings/preferences").json().get("theme") if healthy else None
                    content = wait_for(lambda: "New research" in (ui("texts", str(again.proc.pid)) or []), 30, 1) if healthy else None
                    time.sleep(2)  # the backend's page renders
                    page = work / "theme-page.png"
                    if window:
                        ui("activate", str(again.proc.pid))
                        time.sleep(1)
                        subprocess.run(["screencapture", "-x", "-o", "-l", str(window["id"]), str(page)], capture_output=True)
                    later = brightness(page) if page.exists() else None
                    row("theme", bool(kept and stored == "dark" and content and first is not None and first < 80
                                      and later is not None and later < 80),
                        **facts, theme_after_restart=stored, research_ui=bool(content), first_frame_brightness=first,
                        page_brightness=later, screenshots=[str(shot), str(page)])
                trigger = time.monotonic()
                ui("terminate", str(again.proc.pid))
                again.check_left(trigger)
                again.kill_all()  # nothing of it may hold the single-instance lock when the next scenario starts
        if wanted("download"):
            clear_markers(bin_dir)
            (bin_dir / "no-hang").write_text("")  # fake codex answers: the report needs a finished answer
            downloads = home / "Downloads"
            shutil.rmtree(downloads, ignore_errors=True)
            sc = Scenario(work, app, env, "download")
            scenarios.append(sc)
            sc.launch()
            steps: list = []
            if sc.wait_health() is None:
                row("download", False, reason="no health within 60 s")
            elif ui.locked():
                row("download", None, reason=locked)
            else:
                client = sc.session()
                made = client.post("/api/researches", json={"question": QUESTION + " (download)", "source_scope": "attached",
                                                            "effort": "quick", "model_connection": "codex",
                                                            "requested_model": "gpt-fake", "reasoning_effort": "medium"})
                rid = made.json()["research"]["id"]
                client.post(f"/api/researches/{rid}/uploads", files={"file": ("synthetic.pdf", make_pdf(
                    ["SYNTHETIC page: a bounded molecule release schedule minimizes the decoding error."]),
                    "application/pdf")})
                run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"})
                view, finished = wait_run(client, rid, run.json()["id"])
                title = view["research"]["title"]
                pid = str(sc.proc.pid)
                ui("activate", pid)

                def press(text: str, exact: bool = False) -> bool:
                    done = ui("press" if exact else "press-part", pid, text)
                    steps.append(done)
                    return bool(done and done.get("pressed"))
                opened = wait_for(lambda: press(title), 20, 1)
                exported = wait_for(lambda: press("Export", exact=True), 20, 1)
                markdown = wait_for(lambda: press("Markdown"), 10, 0.5)
                md = wait_for(lambda: sorted(downloads.glob("*.md")), 15)
                # The evidence table's CSV from the same Export menu (an attached-PDF research has no Sources panel).
                export_again = wait_for(lambda: press("Export", exact=True), 10, 0.5)
                csv_pressed = wait_for(lambda: press("Comma-separated values"), 10, 0.5)
                csv = wait_for(lambda: sorted(downloads.glob("*.csv")), 15)
                (work / "download-texts.json").write_text(json.dumps(ui("texts", pid) or [], indent=1))
                md_text = md[0].read_text(encoding="utf-8") if md else ""
                csv_text = csv[0].read_text(encoding="utf-8-sig") if csv else ""
                shell_err = (work / "shell-download.err").read_text(encoding="utf-8", errors="replace")
                row("download", bool(md and title in md_text and csv and "synthetic" in csv_text.lower()),
                    run=finished["status"], title=title, opened=bool(opened), export_pressed=bool(exported),
                    markdown_pressed=bool(markdown), export_again_pressed=bool(export_again), csv_pressed=bool(csv_pressed),
                    files=[p.name for p in downloads.glob("*")] if downloads.exists() else [],
                    report_bytes=len(md_text), csv_lines=len(csv_text.splitlines()),
                    shell_says=[line for line in shell_err.splitlines() if "Download" in line][:4], steps=steps[-3:])
            (bin_dir / "no-hang").unlink(missing_ok=True)
            trigger = time.monotonic()
            ui("terminate", str(sc.proc.pid))
            left = sc.check_left(trigger)
            results["download"]["left_ok"] = left["ok"]
            if not left["ok"]:
                results["download"]["ok"] = False
                print(f"     download left={left}", flush=True)
    finally:
        for sc in scenarios:
            sc.kill_all()
        passed = sum(1 for r in results.values() if r["ok"] is True)
        print(json.dumps({"passed": passed, "failed": [n for n, r in results.items() if r["ok"] is False],
                          "not_done": [n for n, r in results.items() if r["ok"] is None],
                          "manual": [n for n, r in results.items() if r["ok"] == MANUAL],
                          "work": str(work) if args.keep else None}))
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
    return 0 if results and all(r["ok"] is True or r["ok"] == MANUAL for r in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
