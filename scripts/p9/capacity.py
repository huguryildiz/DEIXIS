#!/usr/bin/env python3
"""P9 H5: model-free capacity and performance measurement (plan rows K01 to K07).

Subcommands (all raw output goes to .local/p9-h5/, every library, data dir, backup and home under /tmp/h5-*):

  generate     --root /tmp/h5-lib --points 100,1000,5000,7769,10000   synthetic libraries, one per point
  pdf-library  --root /tmp/h5-lib                                      one research with a 45 MiB, 500-page PDF
  measure      --root /tmp/h5-lib --points ... --reps 3 --out .local/p9-h5/<label>/   [--pdf | --control]
  summarize    --out .local/p9-h5/<label>/ [--also <folder> ...]       summary.json from the repetition files
  table        --out .local/p9-h5/<label>/ [--also <folder> ...]       the Markdown capacity table
  limits       [--out ... [--also <folder> ...]]                       the K07 limits table

K03a needs the "pdf" point next to the N points, and the control run is a third `measure` call. Either run the three calls
(points, --pdf, --control) with the same --out folder, or give each its own folder and name the others with --also on
summarize/table/limits: rep files are merged by point name (--out first, then each --also), and summary.json is written to --out.

Every library is synthetic: SYNTHETIC titles, no answers, reports, evidence tables, model steps or model sessions.
Measure with the repository's venv python (native arm64), for example
  PYTHONPATH=backend:. .venv/bin/python scripts/p9/capacity.py measure ...
The script starts only the processes it records as (pid, lstart, command) and re-checks that record before it signals one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import re
import shutil
import signal
import socket
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
BROWSER = Path(__file__).resolve().parent / "capacity_browser.mjs"
OUT_ROOT = REPO / ".local" / "p9-h5"
SHAPE_VERSION = 1
PORT_FIRST = int(os.environ.get("P9_CAPACITY_PORT_FIRST", "8900"))  # the range is this port and the 20 after it (the matrix runner sets 8950)
PORTS = range(PORT_FIRST, PORT_FIRST + 21)
if any(p == 8765 or 8858 <= p <= 8864 for p in PORTS):
    raise SystemExit(f"P9_CAPACITY_PORT_FIRST={PORT_FIRST}: the range {PORTS[0]} to {PORTS[-1]} touches a live-service port (8765, 8858 to 8864)")
LOAD_LIMIT = 4.0
SEED = 20261002

# ---- frozen thresholds (S7, frozen 2 October 2026 before any measurement; never changed after one) ---------------------

FROZEN: dict[str, Any] = {
    "frozen_on": "2026-10-02",
    "points": [100, 1000, 5000, 7769, 10000],
    "repetitions": 3,
    "rows": {
        "K01a": {"class": "mandatory", "what": "N=1,000: research screen ready in Chrome (K01-ui) and first GET /api/researches/{id}",
                 "metrics": [{"name": "ui_ready_s", "points": [1000], "limit": 2.0, "strict": False},
                             {"name": "first_api_s", "points": [1000], "limit": 2.0, "strict": False}]},
        "K01b": {"class": "mandatory", "what": "N=5,000: research screen ready in Chrome (K01-ui) and first GET /api/researches/{id}",
                 "metrics": [{"name": "ui_ready_s", "points": [5000], "limit": 10.0, "strict": False},
                             {"name": "first_api_s", "points": [5000], "limit": 10.0, "strict": False}]},
        "K01c": {"class": "measure only", "what": "N=100 and N=7,769: K01-ui and first API time",
                 "metrics": [{"name": "ui_ready_s", "points": [100, 7769], "limit": None, "strict": False},
                             {"name": "first_api_s", "points": [100, 7769], "limit": None, "strict": False}]},
        "K01d": {"class": "measure only", "what": "N=10,000: does the screen become ready within 120 s (works / does not work)",
                 "metrics": [{"name": "ui_ready_ok", "points": [10000], "limit": None, "strict": False},
                             {"name": "ui_ready_s", "points": [10000], "limit": None, "strict": False}]},
        "K02a": {"class": "mandatory", "what": "N=1,000: longest /api/health latency overlapping the first research view request",
                 "metrics": [{"name": "health_max_s", "points": [1000], "limit": 0.5, "strict": False}]},
        "K02b": {"class": "mandatory", "what": "N=5,000: same",
                 "metrics": [{"name": "health_max_s", "points": [5000], "limit": 1.0, "strict": False}]},
        "K02c": {"class": "measure only", "what": "every other N, and N=5,000 with one event stream open and a second tab loading the screen: same number",
                 "metrics": [{"name": "health_max_s", "points": [100, 7769, 10000], "limit": None, "strict": False},
                             {"name": "two_tab_health_max_s", "points": [5000], "limit": None, "strict": False}]},
        "K03a": {"class": "mandatory", "what": "server RSS peak (bytes) at N=100, 1,000, 5,000, 7,769 and over the large-PDF steps",
                 "metrics": [{"name": "rss_peak_bytes", "points": [100, 1000, 5000, 7769, "pdf"], "limit": 2_000_000_000, "strict": True}]},
        "K03b": {"class": "measure only", "what": "library.sqlite, -wal and data directory bytes per N",
                 "metrics": [{"name": "db_bytes", "points": [100, 1000, 5000, 7769, 10000], "limit": None, "strict": False},
                             {"name": "wal_bytes", "points": [100, 1000, 5000, 7769, 10000], "limit": None, "strict": False},
                             {"name": "data_dir_bytes", "points": [100, 1000, 5000, 7769, 10000], "limit": None, "strict": False}]},
        "K03c": {"class": "measure only", "what": "server RSS peak (bytes) at N=10,000 and in the control run",
                 "metrics": [{"name": "rss_peak_bytes", "points": [10000, "control"], "limit": None, "strict": False}]},
        "K04a": {"class": "measure only", "what": "Quick find (Meta+K, 'alpha') to first Sources result; API time of GET /api/search",
                 "metrics": [{"name": "quickfind_s", "points": [1000, 5000, 10000], "limit": None, "strict": False},
                             {"name": "search_api_s", "points": [1000, 5000, 10000], "limit": None, "strict": False}]},
        "K04b": {"class": "measure only", "what": "source list first paint (navigation to #/research/<id>/sources to first row)",
                 "metrics": [{"name": "sources_first_paint_s", "points": [1000, 5000, 10000], "limit": None, "strict": False}]},
        "K04c": {"class": "measure only", "what": "passage panel first paint: stored PDF text (Open PDF + Plain text) and abstract",
                 "metrics": [{"name": "passage_pdf_text_s", "points": [1000, 5000, 10000], "limit": None, "strict": False},
                             {"name": "passage_abstract_s", "points": [1000, 5000, 10000], "limit": None, "strict": False}]},
        "K05": {"class": "measure only", "what": "45 MiB, 500-page PDF in the viewer: first page and jump to page 400",
                "metrics": [{"name": "pdf_first_page_s", "points": ["pdf"], "limit": None, "strict": False},
                            {"name": "pdf_jump_s", "points": ["pdf"], "limit": None, "strict": False}]},
        "K06a": {"class": "mandatory", "what": "python -m deixis backup of the N=5,000 library, server stopped (exit 0, manifest present)",
                 "metrics": [{"name": "backup_s", "points": [5000], "limit": 120.0, "strict": False},
                             {"name": "backup_failed", "points": [5000], "limit": 0, "strict": False}]},
        "K06b": {"class": "measure only", "what": "backup folder bytes (N=5,000); backup times at N=1,000, 10,000, the large-PDF library, and with the server running",
                 "metrics": [{"name": "backup_bytes", "points": [5000, "pdf"], "limit": None, "strict": False},
                             {"name": "backup_s", "points": [1000, 10000, "pdf"], "limit": None, "strict": False},
                             {"name": "backup_running_s", "points": [1000, 5000, 10000], "limit": None, "strict": False},
                             {"name": "backup_running_health_max_s", "points": [1000, 5000, 10000], "limit": None, "strict": False}]},
        "K07": {"class": "mandatory", "what": "limits table: every limit has kind, value, source line and measured-peak cells filled", "metrics": []},
    },
}

VERDICTS = ("pass", "fail", "incomplete", "measured")
CONTROL_REPETITIONS = 1  # the control run is one repetition; every other point has FROZEN["repetitions"]
UI_DEADLINE_S = 120.0  # K01d: the screen must be ready within this, goto included


# ---- verdicts: pure functions ------------------------------------------------------------------------------------------


def _present(values: list[Any] | None) -> list[float]:
    return [v for v in (values or []) if v is not None]


def _breaks(value: float, limit: float | None, strict: bool) -> bool:
    if limit is None:
        return False
    return value >= limit if strict else value > limit


def worst_of(name: str, values: list[float]) -> float:
    """The worst repetition: the largest value, except for a 0/1 `_ok` flag where any 0 is the worst (so the minimum)."""
    return min(values) if name.endswith("_ok") else max(values)


def repetitions_for(point: Any, reps: int | None = None) -> int:
    """How many repetitions a point must have: one for the control, FROZEN["repetitions"] for every other point."""
    return reps or (CONTROL_REPETITIONS if str(point) == "control" else FROZEN["repetitions"])


def judge(row: dict[str, Any], results: dict[str, dict[str, list[Any]]], reps: int | None = None) -> dict[str, Any]:
    """Verdict for one frozen row.

    `results` is {point: {metric: [value per repetition, None when a repetition did not produce one]}}. The verdict uses
    the worst repetition (the largest value; for a 0/1 `_ok` flag the smallest) of every metric at every point (the control point has one repetition, every
    other point three; `reps` overrides both); a value on the threshold passes unless the
    row says `strict`. A mandatory row with a breaching value is `fail` even when another repetition is missing; a row
    with a missing repetition or point and no breach is `incomplete`; a measure-only row is `measured` and never fails.
    """
    breach = False
    missing = False
    detail: dict[str, dict[str, Any]] = {}
    pooled: dict[str, list[float]] = {}
    for metric in row["metrics"]:
        name = metric["name"]
        for point in metric["points"]:
            values = (results.get(str(point)) or {}).get(name)
            have = _present(values)
            if len(have) < repetitions_for(point, reps):
                missing = True
            if have:
                pooled.setdefault(name, []).extend(have)
                detail.setdefault(name, {})[str(point)] = {
                    "values": values, "worst": worst_of(name, have), "median": statistics.median(have)}
                if row["class"] == "mandatory" and any(_breaks(v, metric["limit"], metric["strict"]) for v in have):
                    breach = True
            else:
                detail.setdefault(name, {})[str(point)] = {"values": values, "worst": None, "median": None}
    if row["class"] == "mandatory":
        verdict = "fail" if breach else "incomplete" if missing or not row["metrics"] else "pass"
    else:
        verdict = "incomplete" if missing else "measured"
    return {"verdict": verdict, "metrics": detail,
            "pooled": {name: {"worst": worst_of(name, v), "median": statistics.median(v)} for name, v in pooled.items()}}


def judge_limits(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """K07: complete when every cell of every row holds text ("not measured ..." counts as text)."""
    empty = [(r.get("limit"), k) for r in rows for k in ("limit", "kind", "value", "source", "measured") if not str(r.get(k) or "").strip()]
    return {"verdict": "fail" if empty or not rows else "pass", "empty_cells": empty, "rows": len(rows)}


def is_ready_timeout(step: dict[str, Any]) -> bool:
    """The browser step ended because the screen was not ready within the deadline (Playwright TimeoutError), not because the harness broke."""
    return bool(step.get("timeout")) or bool(re.search(r"Timeout [\d.]+ms exceeded", str(step.get("error") or "")))


def k01_fields(step: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    """Record fields and errors of the K01-ui browser step.

    Three outcomes. The screen became ready: its time, `ui_ready_ok` 1 (0 when it took longer than the 120 s deadline).
    The screen was not ready within the deadline (a readiness timeout): this is a measurement, not a harness error, so it is
    written as `ui_ready_timeout` 1, `ui_ready_ok` 0 and `ui_ready_s` = the deadline that was reached (120 s exceeds every K01
    limit, so a mandatory K01 row fails and K01d reads "does not work"); the real elapsed time is `ui_ready_elapsed_s` and
    the unmet conditions are kept. Anything else (no step, a selector error, a crash) is a harness failure: no time and no
    `ui_ready_ok`, so the rows stay `incomplete` and a fast failure never reads as a fast pass."""
    if not step:
        return {"ui_ready_s": None, "ui_ready_ok": None, "ui_ready_timeout": None, "ui_ready_page_ms": None}, ["k01: the browser returned no K01 step"]
    ok, seconds = bool(step.get("ok")), step.get("seconds")
    if not ok and is_ready_timeout(step):
        return {"ui_ready_s": UI_DEADLINE_S, "ui_ready_ok": 0, "ui_ready_timeout": 1, "ui_ready_page_ms": None,
                "ui_ready_elapsed_s": seconds, "ui_ready_error": step.get("error"), "ui_ready_readiness": step.get("readiness")}, []
    if not ok:
        return ({"ui_ready_s": None, "ui_ready_ok": None, "ui_ready_timeout": 0, "ui_ready_page_ms": None, "ui_ready_elapsed_s": seconds},
                [f"k01: {step.get('error') or 'the screen did not become ready'} (waited {seconds} s)"])
    within = seconds is not None and seconds <= UI_DEADLINE_S
    fields = {"ui_ready_s": seconds, "ui_ready_ok": int(within), "ui_ready_timeout": 0, "ui_ready_page_ms": step.get("page_ms"),
              "ui_ready_elapsed_s": seconds}
    errors = [] if within else [f"k01: ready after {seconds:.1f} s, above the {UI_DEADLINE_S:.0f} s deadline"]
    return fields, errors


def first_ok_s(step: dict[str, Any] | None) -> float | None:
    """K05, raw record only: the first moment the viewer conditions held, before the 100 ms stability wait that is part of the
    recorded time. The browser reports the wait it added (`stable_wait_ms`); the recorded seconds minus it is that first moment."""
    if not step or not step.get("ok") or step.get("seconds") is None or step.get("stable_wait_ms") is None:
        return None
    return step["seconds"] - step["stable_wait_ms"] / 1000


def is_loaded(rec: dict[str, Any]) -> bool:
    """A repetition ran under parallel load when its 1-minute load average was at least LOAD_LIMIT at its start or at its end."""
    return any((rec.get(key) or 0) >= LOAD_LIMIT for key in ("load1", "load1_end"))


# ---- guards ------------------------------------------------------------------------------------------------------------


class GuardError(RuntimeError):
    pass


def temp_roots() -> list[str]:
    return sorted({os.path.realpath("/tmp"), os.path.realpath(tempfile.gettempdir())})


def guard_dir(path: str | os.PathLike[str]) -> Path:
    """The real path must sit directly in a temp root inside a folder whose name starts with h5-."""
    real = os.path.realpath(path)
    for root in temp_roots():
        prefix = root.rstrip("/") + "/"
        if real.startswith(prefix):
            first = real[len(prefix):].split("/", 1)[0]
            if first.startswith("h5-"):
                return Path(real)
    raise GuardError(f"{path} (real path {real}) is not inside an h5-* folder under {temp_roots()}")


def guard_port(port: int) -> int:
    if port not in PORTS:
        raise GuardError(f"port {port} is outside {PORTS[0]} to {PORTS[-1]}")
    return port


def guard_out(path: str | os.PathLike[str], out_root: Path = OUT_ROOT) -> Path:
    real = Path(os.path.realpath(path))
    root = Path(os.path.realpath(out_root))
    if real != root and root not in real.parents:
        raise GuardError(f"{path} is not under {root}")
    return real


def guard_repo(repo: Path = REPO) -> None:
    if (repo / ".env").exists():
        raise GuardError(f"{repo / '.env'} exists: load_settings would read it; move it away first")


def require_arm64() -> None:
    if platform.machine() != "arm64":
        raise GuardError(f"this python is {platform.machine()}, not arm64")


# ---- processes ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Ident:
    pid: int
    lstart: str
    command: str


def ps_one(pid: int) -> tuple[str, str, str] | None:
    out = subprocess.run(["ps", "-ww", "-o", "stat=,lstart=,command=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    if not out:
        return None
    parts = out.split(None, 6)
    return parts[0], " ".join(parts[1:6]), parts[6] if len(parts) > 6 else ""


def ident_of(pid: int) -> Ident | None:
    found = ps_one(pid)
    return Ident(pid, found[1], found[2]) if found else None


def is_same_and_live(ident: Ident) -> bool:
    now = ps_one(ident.pid)
    return now is not None and not now[0].startswith("Z") and now[1] == ident.lstart and now[2] == ident.command


def signal_if_same(ident: Ident, sig: int) -> bool:
    if not is_same_and_live(ident):
        return False
    try:
        os.kill(ident.pid, sig)
    except ProcessLookupError:
        return False
    return True


def leftover(started: list[Ident]) -> list[str]:
    """Processes this script started that are still live, plus any process whose command names an h5-run folder."""
    found = [f"{i.pid} {i.command[:100]}" for i in started if is_same_and_live(i)]
    out = subprocess.run(["ps", "-A", "-ww", "-o", "pid=,command="], capture_output=True, text=True).stdout
    for line in out.splitlines():
        pid, _, command = line.strip().partition(" ")
        if pid.isdigit() and int(pid) != os.getpid() and "/h5-run-" in command and "ps -A" not in command:
            found.append(f"{pid} {command[:100]}")
    return sorted(set(found))


def port_free(port: int) -> bool:
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
    except OSError:
        return True
    return False


_port_cursor = [0]


def pick_port() -> int:
    for _ in range(len(PORTS)):
        port = PORTS[_port_cursor[0] % len(PORTS)]
        _port_cursor[0] += 1
        if port_free(port):
            return guard_port(port)
    raise GuardError(f"no free port in {PORTS[0]} to {PORTS[-1]}")


def child_env(home: Path, data_dir: Path) -> dict[str, str]:
    """The allowlist, named one by one: no model CLI on PATH, no repository .env, a temp HOME."""
    path = f"{Path(sys.executable).parent}:/usr/bin:/bin"
    for name in ("codex", "claude", "gemini"):
        if shutil.which(name, path=path):
            raise GuardError(f"a {name} binary is on the child's PATH")
    return {"PATH": path, "HOME": str(home), "PYTHONPATH": f"{REPO / 'backend'}:{REPO}",
            "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring", "DEIXIS_DATA_DIR": str(data_dir)}


def uptime() -> dict[str, Any]:
    text = subprocess.run(["uptime"], capture_output=True, text=True).stdout.strip()
    match = re.search(r"load averages?:\s*([\d.,]+)[ ,]+([\d.,]+)[ ,]+([\d.,]+)", text)
    loads = [float(x.replace(",", ".")) for x in match.groups()] if match else None
    return {"uptime": text, "load1": loads[0] if loads else None, "load5": loads[1] if loads else None}


def dir_bytes(path: Path) -> int:
    total = 0
    for base, _, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(base, name)).st_size
            except OSError:
                pass
    return total


def file_bytes(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


class Server:
    """One `python -m deixis serve` on a data directory, with an RSS sampler (every 100 ms, `ps -o rss=`, KiB x 1024)."""

    def __init__(self, data_dir: Path, work: Path, started: list[Ident]):
        self.data_dir, self.work, self.started = guard_dir(data_dir), guard_dir(work), started
        self.port = pick_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen | None = None
        self.ident: Ident | None = None
        self.rss_peak = 0
        self.rss_last = 0
        self.rss_samples = 0
        self._sampling = threading.Event()
        self._sampler: threading.Thread | None = None
        self.startup_s: float | None = None
        self.log = self.work / f"server-{self.port}.log"

    def start(self, deadline: float = 180.0) -> None:
        import httpx

        argv = [sys.executable, "-m", "deixis", "serve", "--no-browser", "--port", str(self.port)]
        handle = open(self.log, "ab")
        began = time.perf_counter()
        self.proc = subprocess.Popen(argv, env=child_env(self.work / "home", self.data_dir), cwd=self.work / "cwd",
                                     stdout=handle, stderr=subprocess.STDOUT)
        handle.close()
        self.ident = ident_of(self.proc.pid)
        assert self.ident is not None, "the server vanished before it could be recorded"
        self.started.append(self.ident)
        self._sampling.set()
        self._sampler = threading.Thread(target=self._sample, daemon=True)
        self._sampler.start()
        with httpx.Client(trust_env=False, timeout=2) as client:
            while time.perf_counter() - began < deadline:
                if self.proc.poll() is not None:
                    raise RuntimeError(f"the server exited with {self.proc.returncode}: {self.log.read_text()[-600:]}")
                try:
                    if client.get(f"{self.base}/api/health").status_code == 200:
                        self.startup_s = time.perf_counter() - began
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(0.05)
        raise RuntimeError(f"/api/health did not answer 200 within {deadline} s; log tail: {self.log.read_text()[-600:]}")

    def _sample(self) -> None:
        while self._sampling.is_set() and self.proc is not None:
            out = subprocess.run(["ps", "-o", "rss=", "-p", str(self.proc.pid)], capture_output=True, text=True).stdout.strip()
            if out.isdigit():
                self.rss_last = int(out) * 1024
                self.rss_peak = max(self.rss_peak, self.rss_last)
                self.rss_samples += 1
            time.sleep(0.1)

    def stop_sampling(self) -> None:
        self._sampling.clear()
        if self._sampler:
            self._sampler.join(timeout=5)

    def stop(self) -> None:
        self.stop_sampling()
        if self.proc is None or self.ident is None:
            return
        if self.proc.poll() is None:
            signal_if_same(self.ident, signal.SIGTERM)
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                signal_if_same(self.ident, signal.SIGKILL)
                self.proc.wait(timeout=10)
        end = time.time() + 15
        while not port_free(self.port) and time.time() < end:
            time.sleep(0.2)
        assert port_free(self.port), f"port {self.port} is still in use after the server stopped"


class HealthPoller(threading.Thread):
    """GET /api/health every 25 ms on one persistent connection; each request keeps its epoch send/receive times."""

    def __init__(self, base: str):
        super().__init__(daemon=True)
        self.base = base
        self.records: list[tuple[float, float, float, str]] = []
        self._halt = threading.Event()

    def run(self) -> None:
        import httpx

        with httpx.Client(trust_env=False, timeout=120) as client:
            while not self._halt.is_set():
                sent, began = time.time(), time.perf_counter()
                try:
                    status = str(client.get(f"{self.base}/api/health").status_code)
                except httpx.HTTPError as exc:
                    status = type(exc).__name__
                self.records.append((sent, time.time(), time.perf_counter() - began, status))
                self._halt.wait(0.025)

    def finish(self) -> None:
        self._halt.set()
        self.join(timeout=130)

    def overlapping(self, start: float, end: float) -> dict[str, Any]:
        """Health requests whose [send, receive] interval overlaps [start, end] (epoch seconds)."""
        mine = [r for r in self.records if r[0] < end and r[1] > start]
        longest = sorted((r[2] for r in mine), reverse=True)
        return {"n": len(mine), "max_s": longest[0] if longest else None, "top3_s": longest[:3],
                "non_200": sum(1 for r in mine if r[3] != "200")}


class EventStream(threading.Thread):
    """One open GET .../events/stream read, held until stopped."""

    def __init__(self, base: str, research_id: str):
        super().__init__(daemon=True)
        self.url = f"{base}/api/researches/{research_id}/events/stream"
        self.response: Any = None
        self.bytes = 0

    def run(self) -> None:
        import httpx

        try:
            with httpx.Client(trust_env=False, timeout=None) as client, client.stream("GET", self.url) as response:
                self.response = response
                for chunk in response.iter_raw():
                    self.bytes += len(chunk)
        except Exception:
            return

    def finish(self) -> None:
        try:
            if self.response is not None:
                self.response.close()
        except Exception:
            pass
        self.join(timeout=5)


def timed_get(base: str, path: str) -> dict[str, Any]:
    import httpx

    with httpx.Client(trust_env=False, timeout=600) as client:  # a fresh connection each call
        sent, began = time.time(), time.perf_counter()
        try:
            response = client.get(f"{base}{path}")
        except httpx.TimeoutException:  # a request that never finished is a result (the limit was reached), not a harness error
            return {"status": "timeout", "seconds": time.perf_counter() - began, "bytes": 0, "start": sent, "end": time.time(), "body": b""}
        body = response.content  # received in full, parsed later so the parse does not sit inside the health window
        seconds = time.perf_counter() - began
        return {"status": response.status_code, "seconds": seconds, "bytes": len(body), "start": sent, "end": time.time(), "body": body}


# ---- synthetic library -------------------------------------------------------------------------------------------------

TOPICS = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa", "lambda", "mu", "nu", "xi",
          "omicron", "pi", "rho", "sigma", "tau", "upsilon", "phi", "chi", "psi", "omega", "aster", "borealis", "cinder",
          "dune", "ember", "fjord", "glacier", "harbor", "isthmus", "juniper", "kestrel", "lagoon", "meadow", "nebula",
          "orchid", "prairie"]
_PREFIX = ["Ber", "Cal", "Dor", "Els", "Fen", "Gar", "Hol", "Ivr", "Jan", "Kes", "Lor", "Mar", "Nor", "Osk", "Pel", "Quin",
           "Ras", "Sol", "Tor", "Ulm", "Vas", "Wen", "Yar", "Zel"]
_SUFFIX = ["son", "berg", "man", "ford", "hart", "ley", "stad", "wick", "dahl", "ner"]
SURNAMES = [p + s for p in _PREFIX for s in _SUFFIX]
FIRST = ["Ana", "Bo", "Cem", "Dara", "Eli", "Fay", "Gus", "Hana", "Ivo", "Jun", "Kai", "Lea"]
VENUES = ["Journal of Synthetic Capacity", "Proceedings of Synthetic Measurement", "Synthetic Systems Letters",
          "Annals of Fixture Studies", "Transactions on Placeholder Methods", "Bulletin of Test Records",
          "Review of Imaginary Results", "Synthetic Data Quarterly", "Archive of Dummy Findings",
          "Letters in Constructed Evidence", "Journal of Plausible Nothing", "Notes on Fixture Design"]
_WORDS = ("method sample measure design cohort outcome baseline protocol estimate variance control trial setting group "
          "response factor model pattern range level signal interval sequence record context finding source scale "
          "survey review index trend margin sample layer phase stage cycle unit report effect limit group batch "
          "frame series pooled mixed random fixed paired matched blind open nested split").split()
ACTIVE_STATUSES = ("queued", "running", "pause_requested", "paused")


def _rng(*parts: int) -> random.Random:
    return random.Random(SEED * 1_000_003 + sum(p * 7919 ** i for i, p in enumerate(parts)))


def filler(rng: random.Random, chars: int) -> str:
    out: list[str] = []
    size = 0
    while size < chars:
        word = rng.choice(_WORDS)
        out.append(word)
        size += len(word) + 1
    text = " ".join(out)
    return text[:chars].rsplit(" ", 1)[0] + "."


def selection_of(n: int) -> str:
    bucket = n % 20  # 3 included, 11 excluded, 6 pending out of every 20
    return "included" if bucket < 3 else "excluded" if bucket < 14 else "pending"


def _deixis() -> None:
    backend = str(REPO / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)


def pdf_unique(n: int) -> str:
    return hashlib.sha256(f"h5-{n}".encode()).hexdigest()[:16]


def pdf_marker(n: int) -> str:
    """The text on page 1 of work n's stored PDF that no other PDF carries."""
    return f"Unique marker {pdf_unique(n)}"


def pdf_page_text(n: int, page: int, unique: str) -> str:
    rng = _rng(n, page, 3)
    head = f"SYNTHETIC capacity PDF for work {n}, page {page}. Unique marker {unique}. " if page == 1 else f"SYNTHETIC capacity PDF for work {n}, page {page}. "
    return head + filler(rng, 800 - len(head))


def make_small_pdf(n: int) -> tuple[bytes, list[tuple[int, str]]]:
    import pymupdf

    unique = pdf_unique(n)
    doc = pymupdf.open()
    pages: list[tuple[int, str]] = []
    for number in range(1, 7):
        text = pdf_page_text(n, number, unique)
        page = doc.new_page()
        if page.insert_textbox(pymupdf.Rect(50, 50, 545, 790), text, fontsize=10) < 0:
            raise RuntimeError("PDF page text did not fit")
        pages.append((number, text))
    data = doc.tobytes()
    doc.close()
    return data, pages


def _atomic_write(path: Path, data: bytes) -> None:
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    part.replace(path)


class _ReadOnly(sqlite3.Connection):
    """A read-only connection that removes the empty -wal/-shm files its own open created (mode=ro makes them on a WAL library)."""

    fresh: list[Path] = []

    def close(self) -> None:
        super().close()
        wal = [p for p in self.fresh if p.name.endswith("-wal")]
        if all(p.stat().st_size == 0 for p in wal if p.exists()):
            for path in self.fresh:
                path.unlink(missing_ok=True)


def open_ro(data_dir: Path) -> sqlite3.Connection:
    """Read-only, not immutable: immutable=1 ignores -wal, and a run committed in the WAL would be invisible."""
    base = data_dir / "library.sqlite"
    fresh = [Path(f"{base}{suffix}") for suffix in ("-wal", "-shm") if not Path(f"{base}{suffix}").exists()]
    conn = sqlite3.connect(f"file:{base}?mode=ro", uri=True, factory=_ReadOnly)
    conn.fresh = fresh
    return conn


def counts(data_dir: Path, research_id: str | None = None) -> dict[str, Any]:
    conn = open_ro(data_dir)
    try:
        one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
        out: dict[str, Any] = {t: one(f"SELECT COUNT(*) FROM {t}") for t in (
            "researches", "works", "source_versions", "passages", "candidates", "selections", "source_assets", "search_runs",
            "model_sessions", "person_pdf_requests")}
        out["runs_by_status"] = {s: c for s, c in conn.execute("SELECT status, COUNT(*) FROM runs GROUP BY status")}
        if research_id:
            out["research_memberships"] = one("SELECT COUNT(*) FROM corpus_memberships WHERE research_id = ?", research_id)
            out["research_candidates"] = one("SELECT COUNT(*) FROM candidates WHERE research_id = ?", research_id)
            # every selection row of the research, other versions included (they are pending), and the candidates' own mix
            out["research_selections"] = dict(conn.execute(
                "SELECT state, COUNT(*) FROM selections WHERE research_id = ? GROUP BY state", (research_id,)).fetchall())
            out["research_candidate_selections"] = dict(conn.execute(
                "SELECT s.state, COUNT(*) FROM candidates c JOIN selections s ON s.research_id = c.research_id"
                " AND s.source_version_id = c.source_version_id WHERE c.research_id = ? GROUP BY s.state", (research_id,)).fetchall())
            out["research_search_runs"] = one("SELECT COUNT(*) FROM search_runs WHERE research_id = ?", research_id)
        return out
    finally:
        conn.close()


def code_migration() -> int:
    """The highest migration file in backend/deixis/storage/migrations/ today."""
    _deixis()
    from deixis.storage import db

    return max(int(path.name.split("_", 1)[0]) for path in db.MIGRATIONS_DIR.glob("*.sql"))


def library_migration(data_dir: Path) -> int:
    """The highest applied migration recorded in the library (table schema_migrations)."""
    conn = open_ro(data_dir)
    try:
        return conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0
    finally:
        conn.close()


def current_marker(data_dir: Path, info: dict[str, Any]) -> bool:
    """A prepared library is reused only when it was made at the code's highest migration and still is at it: an older one
    would build its missing indexes at server start, and that one-off would land in the start-up time and the RSS peak."""
    try:
        want = code_migration()
        return info.get("migration") == want and library_migration(data_dir) == want
    except sqlite3.Error:
        return False


def ready_problems(data_dir: Path) -> list[str]:
    """Why a prepared library must not be served: anything a server start could pick up and run."""
    problems = []
    if file_bytes(data_dir / "library.sqlite-wal"):
        problems.append("library.sqlite-wal is not empty: checkpoint the library (wal_checkpoint(TRUNCATE)) before it is used")
    conn = open_ro(data_dir)
    try:
        have, want = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0, code_migration()
        if have < want:
            problems.append(f"the library's highest migration is {have}, the code's is {want}: a server start would migrate it "
                            "(index builds in the start-up and RSS numbers); regenerate it with `generate --force` "
                            "(`pdf-library --force` for the large-PDF library)")
        active = conn.execute(f"SELECT COUNT(*) FROM runs WHERE status IN ({','.join('?' * len(ACTIVE_STATUSES))})", ACTIVE_STATUSES).fetchone()[0]
        if active:
            problems.append(f"{active} run(s) are queued, running or paused: a server start would execute them")
        if conn.execute("SELECT COUNT(*) FROM model_sessions").fetchone()[0]:
            problems.append("model_sessions rows exist")
        if conn.execute("SELECT COUNT(*) FROM person_pdf_requests WHERE status IN ('waiting', 'planned')").fetchone()[0]:
            problems.append("person_pdf_requests are waiting or planned: a start would queue reading work")
        if conn.execute("SELECT COUNT(*) FROM works WHERE source_key IS NULL").fetchone()[0]:
            problems.append("works without a source_key")
        return problems
    finally:
        conn.close()


def require_ready(data_dir: Path) -> None:
    problems = ready_problems(data_dir)
    if problems:
        raise GuardError(f"{data_dir} is not a measurable library: " + "; ".join(problems))


def _finish_library(conn: sqlite3.Connection, data_dir: Path) -> None:
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    for suffix in ("-wal", "-shm"):
        (data_dir / f"library.sqlite{suffix}").unlink(missing_ok=True)


def generate_point(root: Path, n: int, force: bool = False) -> dict[str, Any]:
    """One prepared library at <root>/n<N>/ (reused when generated.json matches the shape version)."""
    _deixis()
    from deixis.documents import pdf
    from deixis.providers.common import OtherVersion, ProviderRecord
    from deixis.storage import db
    from deixis.workflow.store import Store

    root = guard_dir(root)
    data_dir = root / f"n{n}"
    marker = data_dir / "generated.json"
    if marker.exists() and not force:
        info = json.loads(marker.read_text())
        if info.get("shape_version") == SHAPE_VERSION and info.get("works") == n and current_marker(data_dir, info):
            info["reused"] = True
            return info
    if data_dir.exists():
        shutil.rmtree(data_dir)
    began = time.perf_counter()
    conn = db.connect(data_dir / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    (data_dir / "papers").mkdir(parents=True, exist_ok=True)

    def new_research(question: str) -> tuple[str, str]:
        rid = store.create_research(question, "academic", "standard", ["openalex"], "codex", None, None)
        run = store.create_run(rid, "discovery", {"max_model_calls": 0, "max_provider_requests": 1}, None)
        return rid, run["id"]

    def record(tag: str, number: int, title: str, other: bool, rng: random.Random) -> Any:
        authors = [f"{rng.choice(FIRST)} {rng.choice(SURNAMES)}" for _ in range(3)]
        venue = VENUES[number % len(VENUES)]
        abstract = f"SYNTHETIC abstract for work {tag}{number}. " + filler(rng, 860)
        versions = [OtherVersion("submittedVersion", f"https://h5.invalid/pdf/{tag}{number}.pdf", None, venue)] if other else []
        return ProviderRecord(
            provider_record_id=f"W{tag}{number}", title=title, authors=authors, year=2000 + rng.randrange(26), venue=venue,
            publication_type="journal-article", doi=f"10.5555/h5.{tag}{number}", landing_url=f"https://h5.invalid/works/{tag}{number}",
            oa_pdf_url=None, oa_pdf_version=None, version_label="publishedVersion", abstract=abstract,
            abstract_origin="provider_openalex_inverted_index", identifiers={}, raw={}, other_versions=versions)

    def add_search(rid: str, run_id: str, index: int, size: int) -> tuple[str, str]:
        step = store.step(run_id, f"search:{index}", "search")
        srid = store.add_search_run(research_id=rid, run_id=run_id, step_id=step["id"], scope_revision=1, provider="openalex",
                                    query_text="SYNTHETIC", request_description="SYNTHETIC", access_mode="open", status="completed",
                                    result_count=size, page_limit=1)
        return srid, step["id"]

    # Four small researches with their own 12 separate works each, so Quick find scans several researches.
    steps: list[str] = []
    runs: list[str] = []
    with db.transaction(conn):
        for k in range(4):
            rid, run_id = new_research(f"SYNTHETIC small research {k + 1}: placeholder question number {k + 1}")
            runs.append(run_id)
            srid, sid = add_search(rid, run_id, 0, 12)
            steps.append(sid)
            for j in range(12):
                rng = _rng(k + 1, j, 9)
                title = f"SYNTHETIC small study {k + 1}-{j} on {TOPICS[1 + (k * 12 + j) % (len(TOPICS) - 1)]}"
                svid, _ = store.upsert_provider_source("openalex", record(f"s{k + 1}-", j, title, False, rng), None)
                store.add_to_corpus(rid, svid, "search", srid, j, selection_state=selection_of(j), scope_revision=1)

    question = f"SYNTHETIC capacity library question: how do study outcomes differ across {n} placeholder works?"
    rid, run_id = new_research(question)
    runs.append(run_id)
    per = max(1, n // 20)
    searches: list[tuple[str, int, int]] = []  # (search run id, first work, size)
    with db.transaction(conn):
        for index in range(20):
            first = index * per
            size = (n - first) if index == 19 else per
            srid, sid = add_search(rid, run_id, index, size)
            steps.append(sid)
            searches.append((srid, first, size))
    included_ordinal = 0
    pdf_bytes = 0
    pdf_files = 0
    batch = 250
    for begin in range(0, n, batch):
        with db.transaction(conn):
            for number in range(begin, min(n, begin + batch)):
                index = min(number // per, 19)
                srid, first, _ = searches[index]
                rng = _rng(number, 1)
                title = f"SYNTHETIC capacity study {number} on {TOPICS[number % len(TOPICS)]}"
                rec = record("", number, title, number % 10 == 0, rng)
                svid, _ = store.upsert_provider_source("openalex", rec, None)
                state = selection_of(number)
                store.add_to_corpus(rid, svid, "search", srid, number - first, selection_state=state, scope_revision=1)
                for other in store.other_version_ids("openalex", rec):
                    store.add_to_corpus(rid, other, "search", srid, candidate=False, scope_revision=1)
                if state == "included":
                    included_ordinal += 1
                    if included_ordinal % 10 == 0:
                        data, pages = make_small_pdf(number)
                        sha = hashlib.sha256(data).hexdigest()
                        _atomic_write(data_dir / "papers" / f"{sha}.pdf", data)
                        extraction = pdf.Extraction("succeeded", len(pages), [pdf.PageText(p, None, pdf.normalize_page_text(t)) for p, t in pages])
                        store.add_asset_with_pages(svid, sha, len(data), f"{sha}.pdf", "download", None, None, extraction,
                                                   pdf.EXTRACTION_VERSION, pdf.chunk_page)
                        pdf_bytes += len(data)
                        pdf_files += 1
    with db.transaction(conn):
        for sid in steps:
            store.finish_step(sid, "succeeded")
        conn.execute("UPDATE runs SET status = 'completed'")
    # An included work needs at least one stored PDF for any N with at least 10 included works.
    if pdf_files == 0 and included_ordinal >= 10:
        raise RuntimeError("no stored PDF was generated")
    _finish_library(conn, data_dir)
    require_ready(data_dir)
    stats = counts(data_dir, rid)
    info = {
        "shape_version": SHAPE_VERSION, "migration": code_migration(), "works": n, "research_id": rid, "question": question, "label": question,
        "big_research_source_versions": stats["research_memberships"], "other_versions": (n + 9) // 10,
        "included": included_ordinal, "pdf_files": pdf_files, "pdf_bytes": pdf_bytes, "counts": stats,
        "files": {"library.sqlite": file_bytes(data_dir / "library.sqlite"), "data_dir": dir_bytes(data_dir)},
        "generation_seconds": round(time.perf_counter() - began, 2), "reused": False,
        "not_in_library": "answers, reports, evidence tables, model steps, model sessions, link_records, person PDF requests",
        "selection_keys": {"research_selections": "every selection row of the big research, its other versions included (pending)",
                           "research_candidate_selections": "the selection mix of the big research's candidates only (the works)"},
    }
    marker.write_text(json.dumps(info, indent=2))
    return info


def _large_pdf(pages: int, target: int) -> bytes:
    import pymupdf

    rng = random.Random(SEED)
    side = 220
    for _ in range(4):
        noise = pymupdf.Pixmap(pymupdf.csRGB, side, side, rng.randbytes(side * side * 3), False).tobytes("jpeg", jpg_quality=90)
        per_page = target / pages - 2500
        scaled = max(32, int(side * math.sqrt(per_page / len(noise))))
        if abs(scaled - side) <= 2:
            break
        side = scaled
    doc = pymupdf.open()
    for number in range(1, pages + 1):
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 545, 330), large_page_text(number), fontsize=10)
        jpeg = pymupdf.Pixmap(pymupdf.csRGB, side, side, rng.randbytes(side * side * 3), False).tobytes("jpeg", jpg_quality=90)
        page.insert_image(pymupdf.Rect(80, 350, 480, 750), stream=jpeg)
    data = doc.tobytes(garbage=0, deflate=False)
    doc.close()
    return data


def large_page_text(number: int) -> str:
    head = f"SYNTHETIC capacity PDF large document, page {number}. "
    return head + filler(_rng(number, 5), 1400 - len(head))


def generate_pdf_library(root: Path, force: bool = False) -> dict[str, Any]:
    _deixis()
    from deixis.documents import pdf
    from deixis.storage import db
    from deixis.workflow.store import Store

    root = guard_dir(root)
    data_dir = root / "pdf"
    marker = data_dir / "generated.json"
    if marker.exists() and not force:
        info = json.loads(marker.read_text())
        if info.get("shape_version") == SHAPE_VERSION and current_marker(data_dir, info):
            return info | {"reused": True}
    if data_dir.exists():
        shutil.rmtree(data_dir)
    began = time.perf_counter()
    pages, target = 500, 45 * 1024 * 1024
    data = _large_pdf(pages, target)
    if not 40 * 1024 * 1024 <= len(data) < 50 * 1024 * 1024:
        raise RuntimeError(f"the large PDF is {len(data)} bytes, outside 40 to 50 MiB")
    conn = db.connect(data_dir / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    (data_dir / "papers").mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(data).hexdigest()
    _atomic_write(data_dir / "papers" / f"{sha}.pdf", data)
    question = "SYNTHETIC large PDF research: one included source with a 500-page file"
    rid = store.create_research(question, "attached", "standard", [], "codex", None, None)
    svid = store.create_upload_source("SYNTHETIC large document")
    store.add_to_corpus(rid, svid, "user_upload", selection_state="included", selection_origin="user")
    # The extractor stops at 400 pages (pdf.MAX_PAGES) and the upload limit is 50 MiB, so no extraction ran: the row is
    # attached with a hand-built extraction of the two pages that matter and the file's real page count.
    extraction = pdf.Extraction("succeeded", pages, [pdf.PageText(p, None, pdf.normalize_page_text(large_page_text(p))) for p in (1, 400)])
    store.add_asset_with_pages(svid, sha, len(data), f"{sha}.pdf", "user_upload", None, "capacity-large.pdf", extraction,
                               pdf.EXTRACTION_VERSION, pdf.chunk_page)
    _finish_library(conn, data_dir)
    require_ready(data_dir)
    info = {"shape_version": SHAPE_VERSION, "migration": code_migration(), "research_id": rid, "label": question, "pages": pages, "pdf_bytes": len(data),
            "sha256": sha, "passages_on_pages": [1, 400], "counts": counts(data_dir, rid),
            "generation_seconds": round(time.perf_counter() - began, 2), "reused": False}
    marker.write_text(json.dumps(info, indent=2))
    return info


# ---- measurement -------------------------------------------------------------------------------------------------------


def clone(src: Path, dst: Path) -> None:
    if subprocess.run(["cp", "-c", "-R", str(src), str(dst)], capture_output=True).returncode != 0:
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst)


def drop_work_index(data_dir: Path) -> str:
    conn = sqlite3.connect(data_dir / "library.sqlite")
    try:
        for row in conn.execute("PRAGMA index_list(source_versions)").fetchall():
            name = row[1]
            if name.startswith("sqlite_autoindex"):
                continue
            columns = [c[2] for c in conn.execute(f"PRAGMA index_info({name})")]
            if columns[:1] == ["work_id"]:
                conn.execute(f"DROP INDEX {name}")
                conn.commit()
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                return name
        raise RuntimeError("no index on source_versions(work_id) found")
    finally:
        conn.close()


NODE_SLACK_S = 60.0  # per step, on top of the browser's own per-step deadline (UI_DEADLINE_S, passed to node as timeoutMs)


# Waits of up to the per-step deadline that one browser step may make one after the other.
NODE_STEP_UNITS = {"k01": 1, "k04": 2, "k04c-abstract": 3, "k04c-pdf": 3, "two-tab": 2, "pdf": 3}


def node_units(steps: list[str]) -> int:
    """K01: the screen; k04: the Sources list, then Quick find; each k04c-*: the Sources list, then two waits (the click and the
    panel); two-tab: two screens one after the other; pdf: the Sources list, the first page, the jump."""
    return sum(NODE_STEP_UNITS[step] for step in steps)


def node_budget_s(units: int) -> float:
    """How long a node run may take: (per-step deadline + slack) for each unit; `units` comes from node_units."""
    return (UI_DEADLINE_S + NODE_SLACK_S) * units


def last_json_line(stdout: str | None) -> dict[str, Any] | None:
    """The last complete JSON line node printed (it prints the result so far after every step; a line cut by a kill is skipped)."""
    for line in reversed((stdout or "").splitlines()):
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


def run_node(node: str, work: Path, args: dict[str, Any], timeout: float, started: list[Ident]) -> dict[str, Any]:
    """Run capacity_browser.mjs and return the last JSON snapshot it printed. When the budget runs out and node is killed,
    the steps it had finished are kept and the result carries `killed: true` and ok false."""
    killed = False
    env = {"PATH": f"{Path(node).parent}:/usr/bin:/bin", "HOME": str(work / "home"), "TMPDIR": str(work)}
    err = open(work / "node.err", "ab")
    proc = subprocess.Popen([node, str(BROWSER), json.dumps(args)], env=env, cwd=work, stdout=subprocess.PIPE, stderr=err, text=True)
    err.close()
    ident = ident_of(proc.pid)
    if ident:
        started.append(ident)
    try:
        stdout, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        killed = True
        if ident:
            signal_if_same(ident, signal.SIGTERM)
        try:
            stdout, _ = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            if ident:
                signal_if_same(ident, signal.SIGKILL)
            stdout, _ = proc.communicate()
    result = last_json_line(stdout)
    if result is None:
        return {"ok": False, "steps": {}, "killed": killed,
                "error": "the browser script printed no JSON; stderr tail: " + (work / "node.err").read_text()[-400:]}
    if killed:
        result.update(ok=False, killed=True, error=f"node was stopped after {timeout:.0f} s; the steps it had finished are kept")
    return result


def heading_label(view: dict[str, Any]) -> str:
    """The research screen's heading text: ResearchView.tsx `heading`."""
    question, title = view["scope"]["question"], view["research"]["title"]
    return question if question.startswith(title) else title


def manifest_expected_files(data_dir: Path) -> int:
    """What storage/backup.py lists: the database copy, each distinct source_assets.storage_path, each distinct payload reference.

    Not the data directory's file count (that also holds worker.lock, -wal, -shm and codex-home)."""
    conn = open_ro(data_dir)
    try:
        papers = {r[0] for r in conn.execute("SELECT storage_path FROM source_assets")}
        payloads = {r[0] for r in conn.execute(
            "SELECT raw_payload_path FROM search_runs WHERE raw_payload_path IS NOT NULL"
            " UNION SELECT provider_payload_path FROM source_versions WHERE provider_payload_path IS NOT NULL"
            " UNION SELECT raw_payload_path FROM kill_search_queries WHERE raw_payload_path IS NOT NULL"
            " UNION SELECT payload_ref FROM passages WHERE kind = 'abstract' AND payload_ref IS NOT NULL")}
        return 1 + len(papers) + len(payloads)
    finally:
        conn.close()


def pdf_markers(data_dir: Path) -> dict[str, str]:
    """{work number: page-1 marker} for every stored PDF; the browser reads the number from the row it clicks."""
    conn = open_ro(data_dir)
    try:
        titles = [r[0] for r in conn.execute(
            "SELECT sv.title FROM source_assets a JOIN source_versions sv ON sv.id = a.source_version_id")]
    finally:
        conn.close()
    found = (re.search(r"capacity study (\d+) on", t) for t in titles)
    return {m.group(1): pdf_marker(int(m.group(1))) for m in found if m}


def run_backup(data_dir: Path, work: Path, tag: str, started: list[Ident]) -> dict[str, Any]:
    dest = work / f"backup-{tag}"
    dest.mkdir()
    log = work / f"backup-{tag}.log"
    began = time.perf_counter()
    with open(log, "ab") as handle:
        proc = subprocess.Popen([sys.executable, "-m", "deixis", "backup", str(dest)], env=child_env(work / "home", data_dir),
                                cwd=work / "cwd", stdout=handle, stderr=subprocess.STDOUT)
        ident = ident_of(proc.pid)
        if ident:
            started.append(ident)
        try:
            code = proc.wait(timeout=3600)
        except subprocess.TimeoutExpired:
            if ident:
                signal_if_same(ident, signal.SIGKILL)
            code = proc.wait()
    seconds = time.perf_counter() - began
    folders = [p for p in dest.iterdir() if p.is_dir()]
    manifest = folders[0] / "manifest.json" if folders else None
    present = bool(manifest and manifest.exists())
    listed = len(json.loads(manifest.read_text())["files"]) if present else None
    expected = manifest_expected_files(data_dir)
    problems = []
    if code != 0 or not present:
        problems.append(f"backup {tag}: exit {code}, manifest {'present' if present else 'missing'}")
    elif listed != expected:
        problems.append(f"backup {tag}: the manifest lists {listed} files, the formula expects {expected}")
    result = {"seconds": seconds, "exit": code, "bytes": dir_bytes(dest), "manifest_present": present,
              "manifest_files": listed, "expected_manifest_files": expected,
              "failed": int(bool(problems)), "problems": problems}
    shutil.rmtree(dest, ignore_errors=True)
    return result


def run_rep(point: Any, rep: int, src: Path, info: dict[str, Any], out: Path, node: str, started: list[Ident],
            control: bool = False, is_pdf: bool = False) -> dict[str, Any]:
    """One repetition: a fresh server process on a fresh clone of the prepared library.

    The raw record keeps both WAL sizes: `wal_bytes_running` (read before the server is stopped) and `wal_bytes` (read after
    the stop, which is the value K03b's table uses)."""
    work = Path(tempfile.mkdtemp(prefix="h5-run-"))
    data = work / "data"
    try:
        guard_dir(work)
        (work / "home").mkdir()
        (work / "cwd").mkdir()
        clone(src, data)
        require_ready(data)  # a copy in which a run could start is refused before any server does
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    rec: dict[str, Any] = {"point": str(point), "rep": rep, "started_epoch": time.time(), **uptime(), "errors": []}
    if control:
        rec["dropped_index"] = drop_work_index(data)
    n = info.get("works")
    server = Server(data, work, started)

    def attempt(name: str, call: Any) -> Any:
        try:
            return call()
        except Exception as exc:  # a failed step is recorded, never silently skipped
            rec["errors"].append(f"{name}: {type(exc).__name__}: {str(exc)[:300]}")
            return None

    try:
        server.start()
        rec["startup_s"] = server.startup_s
        rid = info["research_id"]
        view = None
        if not is_pdf:
            poller = HealthPoller(server.base)
            poller.start()
            try:
                time.sleep(0.3)  # the poller is in steady state before the first view request
                first = timed_get(server.base, f"/api/researches/{rid}")
                warm = timed_get(server.base, f"/api/researches/{rid}")
                time.sleep(0.1)
            finally:  # a raising request must not leave the thread polling inside the next repetitions
                poller.finish()
            rec["first_api_s"], rec["first_view_bytes"], rec["first_status"] = first["seconds"], first["bytes"], first["status"]
            health = poller.overlapping(first["start"], first["end"])
            if first["status"] == "timeout":  # the elapsed time is recorded, so a mandatory K01/K02 row reads it as a breach
                rec.update(first_api_s=first["seconds"], health_n=health["n"], health_max_s=health["max_s"], health_non_200=health["non_200"])
                raise RuntimeError(f"the first GET /api/researches/{rid} did not finish within {first['seconds']:.0f} s")
            if first["status"] != 200:  # an error page is fast: it must not read as a fast view
                rec.update(first_api_s=None, health_max_s=None, health_n=health["n"], health_non_200=health["non_200"])
                raise RuntimeError(f"the first GET /api/researches/{rid} answered {first['status']}, not 200")
            rec.update(health_n=health["n"], health_max_s=health["max_s"], health_top3_s=health["top3_s"], health_non_200=health["non_200"])
            rec["warm_api_s"] = warm["seconds"]
            warm_health = poller.overlapping(warm["start"], warm["end"])
            rec.update(warm_health_max_s=warm_health["max_s"], warm_health_n=warm_health["n"])
            view = json.loads(first["body"])
        else:
            view = json.loads(timed_get(server.base, f"/api/researches/{rid}")["body"])
        label, count = heading_label(view), len(view["sources"])
        rec.update(label=label, sources=count)
        web = str(REPO / "apps" / "web")
        base_args = {"web": web, "url": server.base, "researchId": rid, "label": label, "expectedSources": count,
                     "timeoutMs": int(UI_DEADLINE_S * 1000)}
        if not control and not is_pdf:
            steps = ["k01"] + (["k04", "k04c-abstract", "k04c-pdf"] if point in (1000, 5000, 10000) else [])
            node_args = base_args | {"steps": steps} | ({"pdfMarkers": pdf_markers(data)} if "k04c-pdf" in steps else {})
            browser = run_node(node, work, node_args, node_budget_s(node_units(steps)), started)
            rec["browser"] = {k: v for k, v in browser.items() if k != "steps"}
            rec["browser_steps"] = browser.get("steps", {})
            if browser.get("killed"):
                rec["errors"].append("browser: " + str(browser.get("error")))
            st = browser.get("steps", {})
            fields, problems = k01_fields(st.get("k01"))
            rec.update(fields)
            rec["errors"].extend(problems)
            rec["errors"].extend(f"{name}: {step.get('error')}" for name, step in st.items() if name != "k01" and not step.get("ok"))
            for step, key in (("k04a", "quickfind_s"), ("k04b", "sources_first_paint_s"), ("k04c-pdf", "passage_pdf_text_s"),
                              ("k04c-abstract", "passage_abstract_s")):
                if step in st:
                    rec[key] = st[step]["seconds"] if st[step]["ok"] else None
            if point in (1000, 5000, 10000):
                search = attempt("search_api", lambda: timed_get(server.base, "/api/search?q=alpha"))
                if search:
                    rec["search_api_s"], rec["search_api_bytes"] = search["seconds"], search["bytes"]
            if point == 5000:
                poller2 = HealthPoller(server.base)
                poller2.start()
                stream = EventStream(server.base, rid)
                stream.start()
                try:
                    time.sleep(0.5)
                    two = run_node(node, work, base_args | {"steps": ["two-tab"]}, node_budget_s(node_units(["two-tab"])), started)
                finally:  # neither thread may outlive a raising run_node
                    poller2.finish()
                    stream.finish()
                step = two.get("steps", {}).get("two-tab")
                if step:
                    overlap = poller2.overlapping(step["start_epoch_ms"] / 1000, step["end_epoch_ms"] / 1000)
                    rec["two_tab"] = {"ok": step["ok"], "ui_ready_s": step["seconds"], "health": overlap,
                                      "first_tab_ready": step.get("first_tab_ready"), "stream_bytes": stream.bytes}
                    rec["two_tab_health_max_s"] = overlap["max_s"]
                else:
                    rec["errors"].append("two-tab: " + str(two.get("error") or "no step result"))
        if is_pdf:
            browser = run_node(node, work, base_args | {"steps": ["pdf"], "pages": info["pages"]}, node_budget_s(node_units(["pdf"])), started)
            rec["browser"] = {k: v for k, v in browser.items() if k != "steps"}
            rec["browser_steps"] = browser.get("steps", {})
            if browser.get("killed"):
                rec["errors"].append("browser: " + str(browser.get("error")))
            st = browser.get("steps", {})
            rec["errors"].extend(f"{name}: {step.get('error')}" for name, step in st.items() if not step.get("ok"))
            rec["pdf_first_page_s"] = st["pdf_first_page"]["seconds"] if st.get("pdf_first_page", {}).get("ok") else None
            rec["pdf_jump_s"] = st["pdf_jump"]["seconds"] if st.get("pdf_jump", {}).get("ok") else None
            rec["first_page_first_ok_s"] = first_ok_s(st.get("pdf_first_page"))
            rec["jump_first_ok_s"] = first_ok_s(st.get("pdf_jump"))
    except Exception as exc:
        rec["errors"].append(f"{type(exc).__name__}: {str(exc)[:500]}")
    finally:
        server.stop_sampling()
        rec.update(rss_peak_bytes=server.rss_peak or None, rss_final_bytes=server.rss_last or None, rss_samples=server.rss_samples)
        rec["wal_bytes_running"] = file_bytes(data / "library.sqlite-wal")  # while the server is still up
        try:
            server.stop()
        finally:
            rec["wal_bytes"] = file_bytes(data / "library.sqlite-wal")  # after the stop (the table's K03b value)
    rec["db_bytes"] = file_bytes(data / "library.sqlite")
    rec["data_dir_bytes"] = dir_bytes(data)
    if not control:
        after = counts(data)
        rec["runs_after"] = after["runs_by_status"]
        rec["library_runs_unchanged"] = after["runs_by_status"] == info["counts"]["runs_by_status"]
        if not rec["library_runs_unchanged"]:
            rec["errors"].append(f"library changed: runs by status were {info['counts']['runs_by_status']} and are {after['runs_by_status']} after the repetition")
    if point in (1000, 5000, 10000) or is_pdf:
        stopped = attempt("backup", lambda: run_backup(data, work, "stopped", started))
        if stopped:
            rec["errors"].extend(stopped["problems"])
            rec.update(backup_s=stopped["seconds"], backup_bytes=stopped["bytes"], backup_failed=stopped["failed"],
                       backup_exit=stopped["exit"], backup_manifest_files=stopped["manifest_files"],
                       backup_expected_manifest_files=stopped["expected_manifest_files"])
    if point in (1000, 5000, 10000):
        attempt("backup_running", lambda: _backup_while_serving(data, work, started, rec))
    shutil.rmtree(work, ignore_errors=True)
    end = uptime()
    rec.update(load1_end=end["load1"], uptime_end=end["uptime"], load_high=is_loaded(rec | {"load1_end": end["load1"]}))
    (out / f"{point}-rep{rep}.json").write_text(json.dumps(rec, indent=2, default=str))
    return rec


def _backup_while_serving(data: Path, work: Path, started: list[Ident], rec: dict[str, Any]) -> None:
    server = Server(data, work, started)
    try:
        server.start()
        poller = HealthPoller(server.base)
        poller.start()
        try:
            began, result = time.time(), run_backup(data, work, "running", started)
        finally:
            poller.finish()
        health = poller.overlapping(began, time.time())
        rec["errors"].extend(result["problems"])
        rec.update(backup_running_s=result["seconds"], backup_running_failed=result["failed"],
                   backup_running_health_max_s=health["max_s"], backup_running_health_n=health["n"])
    finally:
        server.stop()


# ---- summary, table, limits --------------------------------------------------------------------------------------------


def load_reps(out: Path, also: tuple[Path, ...] | list[Path] = ()) -> dict[str, list[dict[str, Any]]]:
    """Repetition files of `out`, merged by point name with those of every `also` folder (K03a needs the pdf point of another call)."""
    reps: dict[str, list[dict[str, Any]]] = {}
    seen: dict[tuple[str, Any], Path] = {}
    for folder in (out, *also):
        for path in sorted(folder.glob("*-rep*.json")):
            point = path.name.rsplit("-rep", 1)[0]
            rec = json.loads(path.read_text())
            if (point, rec["rep"]) in seen:  # pooling the same (point, rep) twice would count one repetition as two
                raise GuardError(f"duplicate repetition: point {point}, rep {rec['rep']} is in both {seen[(point, rec['rep'])]} and {path}")
            seen[(point, rec["rep"])] = path
            reps.setdefault(point, []).append(rec)
    for point in reps:
        reps[point].sort(key=lambda r: r["rep"])
    return reps


def results_of(reps: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, list[Any]]]:
    metrics = {m["name"] for row in FROZEN["rows"].values() for m in row["metrics"]}
    return {point: {name: [r.get(name) for r in rows] for name in metrics} for point, rows in reps.items()}


def summarize(out: Path, also: tuple[Path, ...] | list[Path] = ()) -> dict[str, Any]:
    reps = load_reps(out, also)
    results = results_of(reps)
    rows: dict[str, Any] = {}
    for rid, row in FROZEN["rows"].items():
        if rid == "K07":
            continue
        rows[rid] = {"class": row["class"], "what": row["what"], "frozen": row["metrics"]} | judge(row, results)
    table = limits_table(measured_of(reps))
    rows["K07"] = {"class": "mandatory", "what": FROZEN["rows"]["K07"]["what"], "frozen": [], **judge_limits(table)}
    flat = sorted((r for rs in reps.values() for r in rs), key=lambda r: r["started_epoch"])
    summary = {
        "frozen": FROZEN, "rows": rows, "limits": table,
        "load_at_start": flat[0].get("load1") if flat else None, "max_load1": max((r.get("load1") or 0 for r in flat), default=None),
        "under_parallel_load": any(is_loaded(r) for r in flat),
        "loads": [{"point": r["point"], "rep": r["rep"], "uptime": r.get("uptime"), "load1": r.get("load1"),
                   "load1_end": r.get("load1_end"), "load_high": is_loaded(r)} for r in flat],
        "errors": {f"{r['point']}-rep{r['rep']}": r["errors"] for r in flat if r.get("errors")},
        "library_changed": [f"{r['point']}-rep{r['rep']}" for r in flat if r.get("library_runs_unchanged") is False],
        "points": {p: [{k: v for k, v in r.items() if k not in ("browser_steps",)} for r in rs] for p, rs in reps.items()},
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary


def measured_of(reps: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    rss = {p: max((r["rss_peak_bytes"] for r in rs if r.get("rss_peak_bytes")), default=None) for p, rs in reps.items()}
    # per N: the slowest successful repetition's time and how many repetitions were ready (a point counts as loaded when at least one was)
    loaded = []
    for p, rs in reps.items():
        ready = [r["ui_ready_s"] for r in rs if r.get("ui_ready_ok") and r.get("ui_ready_s") is not None]
        if p.isdigit() and ready:
            loaded.append((int(p), max(ready), len(ready), max(len(rs), FROZEN["repetitions"])))
    return {"rss": rss, "largest_loaded": max(loaded) if loaded else None}


def _line_of(path: Path, pattern: str) -> int:
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if re.match(pattern, line):
            return number
    raise RuntimeError(f"{pattern!r} not found in {path}")


def limits_table(measured: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """K07: one row per limit with kind, value (and file:line), and the measured peak, from the code's own constants."""
    _deixis()
    from deixis.api import app as api_app
    from deixis.config import Settings
    from deixis.documents import fetch, pdf

    backend = REPO / "backend" / "deixis"
    where = lambda path, pattern: f"{path.relative_to(REPO)}:{_line_of(path, pattern)}"  # noqa: E731
    mib = lambda v: f"{v:,} bytes ({v / 1048576:g} MiB)"  # noqa: E731
    concurrency = Settings.__dataclass_fields__["model_concurrency"].default
    rss, loaded = (measured or {}).get("rss", {}), (measured or {}).get("largest_loaded")
    rss_text = ("; ".join(f"{'N=' + p if p.isdigit() else p}: {v:,} bytes" for p, v in sorted(rss.items()) if v)
                if any(rss.values()) else "not measured yet (run measure)")
    works_text = (f"largest N that loaded: {loaded[0]:,} works, screen ready in {loaded[1]:.2f} s (slowest successful repetition), "
                  f"{loaded[2]} of {loaded[3]} repetitions ready") if loaded else "not measured yet (run measure)"
    return [
        {"limit": "Upload size", "kind": "hard limit", "raw": api_app.MAX_UPLOAD_BYTES, "value": mib(api_app.MAX_UPLOAD_BYTES),
         "source": where(backend / "api" / "app.py", r"MAX_UPLOAD_BYTES\s*="),
         "measured": "a 45 MiB PDF was viewed, not uploaded; the largest accepted upload is H3's"},
        {"limit": "Download size", "kind": "hard limit", "raw": fetch.MAX_BYTES, "value": mib(fetch.MAX_BYTES),
         "source": where(backend / "documents" / "fetch.py", r"MAX_BYTES\s*="), "measured": "not measured (H3)"},
        {"limit": "Extraction pages", "kind": "hard limit", "raw": pdf.MAX_PAGES, "value": f"{pdf.MAX_PAGES} pages",
         "source": where(backend / "documents" / "pdf.py", r"MAX_PAGES\s*="),
         "measured": "a 500-page PDF was viewed; no extraction ran"},
        {"limit": "Extraction characters", "kind": "hard limit", "raw": pdf.MAX_TEXT_CHARS, "value": f"{pdf.MAX_TEXT_CHARS:,} characters",
         "source": where(backend / "documents" / "pdf.py", r"MAX_TEXT_CHARS\s*="), "measured": "not measured here (H0b)"},
        {"limit": "Extraction time", "kind": "hard limit", "raw": pdf.TIMEOUT_SECONDS, "value": f"{pdf.TIMEOUT_SECONDS} s",
         "source": where(backend / "documents" / "pdf.py", r"TIMEOUT_SECONDS\s*="), "measured": "not measured here (H0b)"},
        {"limit": "Extraction memory", "kind": "watcher threshold", "raw": pdf.MAX_MEMORY_BYTES, "value": mib(pdf.MAX_MEMORY_BYTES),
         "source": where(backend / "documents" / "pdf.py", r"MAX_MEMORY_BYTES\s*="),
         "measured": "not measured here (H0b); the server's RSS is not what this watcher watches"},
        {"limit": "Model concurrency", "kind": "configurable default", "raw": concurrency, "value": f"{concurrency} calls (DEIXIS_MODEL_CONCURRENCY)",
         "source": where(backend / "config.py", r"\s+model_concurrency:\s*int\s*="), "measured": "not measured, needs a model"},
        {"limit": "Server RSS peak", "kind": "measured only", "raw": 2_000_000_000, "value": "no limit in code; K03a threshold below 2,000,000,000 bytes (S7)",
         "source": "scripts/p9/capacity.py FROZEN K03a", "measured": rss_text},
        {"limit": "Works in one research", "kind": "measured only", "raw": None, "value": "no limit in code",
         "source": "scripts/p9/capacity.py FROZEN K01d", "measured": works_text},
    ]


def _fmt(value: Any, metric: str) -> str:
    if value is None:
        return "n/a"
    if metric.endswith("_bytes"):
        return f"{int(value):,}"
    if metric.endswith("_ok") or metric.endswith("_failed"):
        return str(int(value))
    return f"{value:.3f} s"


def render_table(summary: dict[str, Any]) -> str:
    label = " (under parallel load)" if summary.get("under_parallel_load") else ""
    applies = ["The label \"under parallel load\" applies to every row of this table.", ""] if label else []
    lines = [f"Capacity table{label}; load at start {summary.get('load_at_start')}, thresholds frozen {FROZEN['frozen_on']}", "", *applies,
             "| Id | Class | Metric @ point | Threshold (frozen) | Worst | Median | Verdict |", "|---|---|---|---|---|---|---|"]
    for rid, row in summary["rows"].items():
        if rid == "K07":
            lines.append(f"| K07 | mandatory | limits table, {summary['limits'].__len__()} rows | all cells filled | "
                         f"{len(row.get('empty_cells', []))} empty | - | {row['verdict']} |")
            continue
        first = True
        for metric in row["frozen"]:
            limit = metric["limit"]
            threshold = "none" if limit is None else f"{'<' if metric['strict'] else '<='} {_fmt(limit, metric['name']) if not isinstance(limit, int) or metric['name'].endswith('_bytes') else limit}"
            detail = row["metrics"].get(metric["name"], {})
            if limit is None:
                for point, cell in detail.items():
                    lines.append(f"| {rid} | {row['class']} | {metric['name']} @ {point} | {threshold} | {_fmt(cell['worst'], metric['name'])} | "
                                 f"{_fmt(cell['median'], metric['name'])} | {row['verdict'] if first else '↳'} |")
                    first = False
            else:
                pooled = row["pooled"].get(metric["name"], {})
                points = ", ".join(str(p) for p in metric["points"])
                lines.append(f"| {rid} | {row['class']} | {metric['name']} @ {points} | {threshold} | {_fmt(pooled.get('worst'), metric['name'])} | "
                             f"{_fmt(pooled.get('median'), metric['name'])} | {row['verdict'] if first else '↳'} |")
                first = False
        if not row["frozen"]:
            lines.append(f"| {rid} | {row['class']} | - | - | - | - | {row['verdict']} |")
    lines += ["", f"K07 limits table{label}", "", *applies, "| Limit | Kind | Value | Source | Measured peak |", "|---|---|---|---|---|"]
    lines += [f"| {r['limit']} | {r['kind']} | {r['value']} | {r['source']} | {r['measured']} |" for r in summary["limits"]]
    return "\n".join(lines)


# ---- commands ----------------------------------------------------------------------------------------------------------


def cmd_generate(args: argparse.Namespace) -> int:
    require_arm64()
    guard_repo()
    root = guard_dir(args.root)
    root.mkdir(parents=True, exist_ok=True)
    for n in (int(x) for x in args.points.split(",")):
        print(json.dumps(generate_point(root, n, force=args.force), default=str), flush=True)
    return 0


def cmd_pdf_library(args: argparse.Namespace) -> int:
    require_arm64()
    guard_repo()
    root = guard_dir(args.root)
    root.mkdir(parents=True, exist_ok=True)
    print(json.dumps(generate_pdf_library(root, force=args.force), default=str), flush=True)
    return 0


def find_node() -> str:
    node = shutil.which("node")
    if not node:
        raise GuardError("node is not on PATH")
    if not Path("/Applications/Google Chrome.app").exists():
        raise GuardError("system Chrome is not installed")
    return node


def measure_passes(args: argparse.Namespace, root: Path, out: Path, node: str, started: list[Ident]) -> None:
    reps = int(args.reps)
    if args.pdf:
        info = json.loads((root / "pdf" / "generated.json").read_text())
        for rep in range(1, reps + 1):
            print(json.dumps({k: v for k, v in run_rep("pdf", rep, root / "pdf", info, out, node, started, is_pdf=True).items() if k in (
                "rep", "rss_peak_bytes", "pdf_first_page_s", "pdf_jump_s", "backup_s", "errors")}, default=str), flush=True)
    elif args.control:
        info = json.loads((root / "n7769" / "generated.json").read_text())
        run_rep("control", 1, root / "n7769", info, out, node, started, control=True)
    else:
        for point in (int(x) for x in args.points.split(",")):
            info = json.loads((root / f"n{point}" / "generated.json").read_text())
            for rep in range(1, reps + 1):
                rec = run_rep(point, rep, root / f"n{point}", info, out, node, started)
                print(json.dumps({k: rec.get(k) for k in ("point", "rep", "load1", "startup_s", "first_api_s", "health_max_s", "ui_ready_s",
                                                         "rss_peak_bytes", "backup_s", "errors")}, default=str), flush=True)


def cmd_measure(args: argparse.Namespace) -> int:
    require_arm64()
    guard_repo()
    root = guard_dir(args.root)
    out = guard_out(args.out)
    out.mkdir(parents=True, exist_ok=True)
    node = find_node()
    started: list[Ident] = []
    try:
        measure_passes(args, root, out, node, started)
    finally:  # an exception in one repetition still leaves the summary of the finished ones and the leftover list; it is re-raised after
        try:
            summarize(out)
        except Exception as exc:
            print(f"summary.json not written: {type(exc).__name__}: {exc}", file=sys.stderr)
        left = leftover(started)
        print(json.dumps({"leftover_processes": left}))
    return 3 if left else 0


def also_dirs(args: argparse.Namespace) -> list[Path]:
    return [guard_out(path) for path in (args.also or [])]


def cmd_summarize(args: argparse.Namespace) -> int:
    summary = summarize(guard_out(args.out), also_dirs(args))
    print(json.dumps({rid: row["verdict"] for rid, row in summary["rows"].items()}))
    return 0


def cmd_table(args: argparse.Namespace) -> int:
    print(render_table(summarize(guard_out(args.out), also_dirs(args))))
    return 0


def cmd_limits(args: argparse.Namespace) -> int:
    measured = measured_of(load_reps(guard_out(args.out), also_dirs(args))) if args.out else None
    rows = limits_table(measured)
    print("| Limit | Kind | Value | Source | Measured peak |\n|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['limit']} | {r['kind']} | {r['value']} | {r['source']} | {r['measured']} |")
    return 0 if judge_limits(rows)["verdict"] == "pass" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("--root", required=True)
    gen.add_argument("--points", default=",".join(str(p) for p in FROZEN["points"]))
    gen.add_argument("--force", action="store_true")
    gen.set_defaults(run=cmd_generate)
    pl = sub.add_parser("pdf-library")
    pl.add_argument("--root", required=True)
    pl.add_argument("--force", action="store_true")
    pl.set_defaults(run=cmd_pdf_library)
    me = sub.add_parser("measure")
    me.add_argument("--root", required=True)
    me.add_argument("--points", default=",".join(str(p) for p in FROZEN["points"]))
    me.add_argument("--reps", default=str(FROZEN["repetitions"]))
    me.add_argument("--out", required=True)
    me.add_argument("--pdf", action="store_true")
    me.add_argument("--control", action="store_true")
    me.set_defaults(run=cmd_measure)
    for name, fn in (("summarize", cmd_summarize), ("table", cmd_table)):
        p = sub.add_parser(name)
        p.add_argument("--out", required=True)
        p.add_argument("--also", nargs="+", help="more result folders whose repetition files are merged by point name")
        p.set_defaults(run=fn)
    li = sub.add_parser("limits")
    li.add_argument("--out")
    li.add_argument("--also", nargs="+", help="more result folders whose repetition files are merged by point name")
    li.set_defaults(run=cmd_limits)
    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except GuardError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
