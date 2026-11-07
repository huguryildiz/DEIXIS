r"""Smoke run of the BUILT backend sidecar (P10 M1 acceptance, macOS arm64; P10 W3, Windows x64).

    uv run python scripts/p10/sidecar_smoke.py [--sidecar packaging/sidecar/dist/deixis-backend] [--keep]

The onedir build is copied to a temp folder outside the checkout and run from there with a temp DEIXIS_DATA_DIR, no
DEIXIS_REPO_ROOT, a minimal environment, a port other than 8765 (saved in the data folder before the start), the null
keyring backend and outbound HTTP(S) sent to a closed local port. The control token is the first stdin line, as the
shell sends it. A stand-in `codex` (fake_codex.py, run by this checkout's Python) is first on PATH: on macOS a shell
script; on Windows an npm install as `tool_paths._windows_command` reads one (`codex.cmd` whose entry line points at
`node_modules\@fake\codex\bin\codex.js`, a Node script that runs fake_codex.py with stdio passed through), so node
and Python are real grandchildren. OCR uses the language data inside the package (P10 M3), never a Tesseract installed
on this computer.
Processes are listed with `ps` on macOS and `Get-CimInstance Win32_Process` on Windows. Rows, each printed as passed
or failed:

  resources    `deixis-backend --check-resources` passes
  listening    the `listening` line arrives; health 200 with its nonce; index.html served; cold start timed
  new_library  a new library made from the packaged schema.sql (its versions equal this checkout's)
  refusals     shutdown without or with a wrong token 403; a normal POST without CSRF 403
  pdf          a synthetic PDF upload gives passages (the frozen `-m deixis.documents.pdf` child and its guard)
  answer       question -> cited answer through the packaged binary, the uploaded PDF the only source, fake codex
  token_env    DEIXIS_CONTROL_TOKEN is not in the fake codex's environment
  ocr          /api/ocr reports the package's own eng+tur data (bundled, engine pymupdf, inside the sidecar folder) and a
               scanned page is read by the app's OCR run (the frozen `-m deixis.documents.ocr` child)
  jats         one JATS file drawn as a PDF by `deixis-backend -m deixis.documents.jats` (invoked here, not by the app)
  shutdown     shutdown with the token and no CSRF cookie; exit 0; no leftover process (pid + start time)
  upgrade      a filled library made by the old migration files (version 1) opens and upgrades: rows and counts
               (less the worker lease and the citation keys every start writes), PDF hash, integrity_check,
               foreign_key_check, and the version record and schema as a new library's
  stdin_exit   stdin closed -> exit within 6 s + 4 s margin

Windows only (P10 W3):
  startup_failed  a second backend on the same data folder prints a `startup_failed` line and exits non-zero
  runtime      `deixis-backend --check-runtime` after the frozen entry's DLL search reset: a PDF opened and rendered,
               a throwaway Credential Locker entry written, read and deleted, an https request through the system trust
               store, and the DLL probe: `probe-<name>.exe` (scripts/p10/dll_probe, built here with rustc) outside the
               package, started by the backend as an external tool, loads `<name>.dll` by name, where <name> is a DLL
               of `_internal`; the only copy with the marker export sits in a folder on PATH, so the probe passes only
               when no package folder is in its DLL search (inherited SetDllDirectory, PATH)

Before anything runs, the build must be current (row build_current): the build identity the binary reports (through
`--check-resources`) equals the identity file in the folder, its per-file sha256 list equals this working tree's
`deixis/**/*.py`, every `package_manifest.datas()` file in the bundle equals its source, and web/dist is newer than
everything under web/src; on a mismatch the run stops. The result line names the sha256 of the binary.

Every record is SYNTHETIC. Passing shows the packaged process runs these paths on this Mac; it says nothing about a
real model, a clean machine or the window.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import queue
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
WINDOWS = sys.platform == "win32"
LINUX = sys.platform.startswith("linux")
BINARY = "deixis-backend.exe" if WINDOWS else "deixis-backend"
HTTPS_URL = "https://api.openalex.org/works?per-page=1"
PROBE_NAMES = ("sqlite3", "libffi-8", "libcrypto-3", "libssl-3")  # DLLs a Windows onedir build holds in _internal
sys.path[:0] = [str(REPO), str(REPO / "tests" / "support"), str(REPO / "tests" / "storage")]
from helpers import make_pdf  # noqa: E402
from old_library import master, old_library  # noqa: E402
from test_schema_upgrades import PAPER, fill, rows, user_tables  # noqa: E402

from deixis import package_manifest  # noqa: E402
from deixis.documents import jats as jats_module  # noqa: E402
from deixis.storage import db  # noqa: E402

TOKEN = "SYNTHETIC-control-token-" + os.urandom(8).hex()
STOP_LIMIT = 6.0 + 4.0
OWNER_PORT = 8765
QUESTION = "How is molecule release scheduling optimized in SYNTHETIC diffusion channels?"
results: dict[str, dict] = {}
# What every start writes into an existing library by design, left out of the upgrade comparison: the worker's lease row
# and each work's citation key, given at startup (`source_keys.assign_missing`, D59).
START_WRITES = {"worker_owner": None, "works": ("source_key", "source_key_basis")}


def compared(tables: dict) -> dict:
    return {t: [c for c in cols if c not in (START_WRITES.get(t) or ())] for t, cols in tables.items()
            if not (t in START_WRITES and START_WRITES[t] is None)}


def row(name: str, ok: bool, **facts) -> None:
    results[name] = {"ok": bool(ok), **facts}
    print(f"{'PASS' if ok else 'FAIL'} {name} {json.dumps(facts, default=str)}", flush=True)


def free_port() -> int:
    while True:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if port != OWNER_PORT:
            return port


# Every process: pid -> (parent pid, start time, command line). PowerShell starts in about a second, so on Windows a
# child that lives less than that can be missed by the watch; what is left at the end is always in the last listing.
CIM = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; Get-CimInstance Win32_Process | ForEach-Object "
       '{ "{0}`t{1}`t{2}`t{3}" -f $_.ProcessId, $_.ParentProcessId, $_.CreationDate.Ticks, $_.CommandLine }')


def processes() -> dict[int, tuple[int, str, str]]:
    table: dict[int, tuple[int, str, str]] = {}
    if WINDOWS:
        encoded = base64.b64encode(CIM.encode("utf-16-le")).decode()  # no quoting through the Windows command line
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                             capture_output=True, encoding="utf-8", errors="replace", timeout=120).stdout
        if not out.strip():
            raise RuntimeError("Get-CimInstance Win32_Process listed no process")
        for line in out.splitlines():
            parts = line.split("\t", 3)
            if len(parts) == 4 and parts[0].isdigit() and parts[1].isdigit():
                table[int(parts[0])] = (int(parts[1]), parts[2], parts[3])
        return table
    out = subprocess.run(["ps", "-A", "-ww", "-o", "pid=,ppid=,lstart=,command="], capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = line.split(None, 7)  # pid ppid, lstart (five words), command
        if len(parts) >= 7 and parts[0].isdigit() and parts[1].isdigit():
            table[int(parts[0])] = (int(parts[1]), " ".join(parts[2:7]), parts[7] if len(parts) > 7 else "")
    return table


def lstart(pid: int, table: dict | None = None) -> str | None:
    found = (processes() if table is None else table).get(pid)
    return found[1] if found else None


def descendants(pid: int, table: dict | None = None) -> set[int]:
    table = processes() if table is None else table
    found, todo = set(), [pid]
    while todo:
        parent = todo.pop()
        for child, (ppid, _, _) in table.items():
            if ppid == parent and child not in found:
                found.add(child)
                todo.append(child)
    return found


class Sidecar:
    """One `serve --desktop` process of the copied binary; its stdout read on a thread."""

    def __init__(self, binary: Path, data: Path, env: dict[str, str]):
        port = free_port()
        data.mkdir(parents=True, exist_ok=True)
        (data / "desktop-port.json").write_text(json.dumps({"port": port}))
        self.env = env | {"DEIXIS_DATA_DIR": str(data), "DEIXIS_PORT": str(free_port())}
        self.started = time.monotonic()
        self.proc = subprocess.Popen([str(binary), "serve", "--desktop"], cwd=binary.parent.parent, env=self.env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=open(data / f"stderr-{os.urandom(3).hex()}.txt", "wb"))
        self.proc.stdin.write(f"{TOKEN}\n".encode())  # the control token as the first stdin line, as the shell sends it
        self.proc.stdin.flush()
        self.lines: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.seen: dict[int, str | None] = {self.proc.pid: lstart(self.proc.pid)}
        self.event: dict | None = None
        self.url = ""
        self.marks = (str(binary.parent), str(data))  # a child started on its own names the bundle or the data folder
        threading.Thread(target=self._watch, daemon=True).start()

    def _watch(self) -> None:
        """For the process's whole life (M2, Sol backlog from M1): every 0.2 s its descendants, and every process whose
        command names the bundle or the data folder, so an orphan or a child in its own session is seen too."""
        while self.proc.poll() is None:
            table = processes()
            self.remember_children(table)
            for pid, (_, start, command) in table.items():
                if pid != os.getpid() and any(m in command for m in self.marks):
                    self.seen.setdefault(pid, start)
            time.sleep(0.2)

    def _read(self) -> None:
        for line in self.proc.stdout:
            self.lines.put(line.decode(errors="replace"))
        self.lines.put("")

    def wait_listening(self, seconds: float = 90) -> dict:
        line = self.lines.get(timeout=seconds)
        self.event = json.loads(line)
        self.url = f"http://127.0.0.1:{self.event.get('port')}"
        return self.event

    def remember_children(self, table: dict | None = None) -> None:
        table = processes() if table is None else table
        for pid in descendants(self.proc.pid, table):
            self.seen.setdefault(pid, lstart(pid, table))

    def leftovers(self) -> list[tuple[int, str]]:
        """Every process seen while it ran that still lives, and every process now naming the bundle or the data folder."""
        table = processes()
        named = {(pid, start) for pid, (_, start, command) in table.items()
                 if pid != os.getpid() and any(m in command for m in self.marks)}
        return sorted({(pid, start) for pid, start in self.seen.items() if start and lstart(pid, table) == start} | named)

    def kill(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()


def wait_run(client: httpx.Client, rid: str, run_id: str, seconds: float = 180) -> tuple[dict, dict]:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        view = client.get(f"/api/researches/{rid}").json()
        run = next(r for r in view["runs"] if r["id"] == run_id)
        if run["status"] in ("completed", "failed", "paused", "cancelled"):
            return view, run
        time.sleep(0.5)
    raise TimeoutError(f"run {run_id} did not finish")


def asset_of(data: Path, source_version_id: str | None) -> dict:
    """The uploaded file's stored asset row (read-only)."""
    with sqlite3.connect(f"file:{data / 'library.sqlite'}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        found = conn.execute("SELECT id, extraction_status, page_count FROM source_assets WHERE source_version_id = ?"
                             " AND removed_at IS NULL", (source_version_id,)).fetchone()
    return dict(found) if found else {}


def scanned_pdf(text: str) -> bytes:
    """A one-page PDF whose page is only a picture of `text` (no text layer), as a scanner makes it."""
    import pymupdf

    page_doc = pymupdf.open("pdf", make_pdf([text]))
    pixmap = page_doc[0].get_pixmap(dpi=200)
    out = pymupdf.open()
    page = out.new_page(width=612, height=792)
    page.insert_image(page.rect, pixmap=pixmap)
    return out.tobytes()


def jats_xml() -> bytes:
    return ("""<?xml version="1.0" encoding="UTF-8"?>
<article><front><article-meta><title-group><article-title>SYNTHETIC JATS article on release scheduling</article-title>
</title-group></article-meta></front><body><sec><title>Results</title><p>SYNTHETIC: a bounded release schedule keeps
the error low in a diffusion channel.</p></sec></body></article>""").encode()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stale_build(sidecar: Path, reported: str | None) -> list[str]:
    """Why the folder at `sidecar` was not built from this working tree; empty when it was."""
    internal = sidecar / "_internal"
    identity_file = internal / "deixis" / package_manifest.BUILD_IDENTITY
    if not identity_file.is_file():
        return [f"no build identity in {identity_file}"]
    problems = [] if reported == sha256(identity_file) else ["the binary reports another build identity than its folder holds"]
    built = json.loads(identity_file.read_text(encoding="utf-8"))["files"]
    tree = {p.relative_to(REPO).as_posix(): sha256(p) for p in sorted((REPO / "deixis").rglob("*.py"))
            if "__pycache__" not in p.parts}
    problems += [f"code differs from the build: {name}" for name in sorted(set(built) | set(tree)) if built.get(name) != tree.get(name)]
    for source, dest in package_manifest.datas(REPO):
        bundled = internal / dest / Path(source).name
        if not bundled.is_file() or sha256(bundled) != sha256(Path(source)):
            problems.append(f"data file differs from the build: {Path(source).relative_to(REPO)}")
    pins = {name: pin["sha256"] for name, pin in json.loads((REPO / "packaging" / "tesseract-versions.json").read_text(encoding="utf-8"))["files"].items()}
    try:
        bundled_pins = json.loads((internal / "tessdata" / "PINS.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        bundled_pins = None
    if bundled_pins != pins:
        problems.append("the OCR language data differs from packaging/tesseract-versions.json")
    web = REPO / "web"
    newest = max(p.stat().st_mtime for p in (web / "src").rglob("*") if p.is_file())
    if (web / "dist" / "index.html").stat().st_mtime < newest:
        problems.append("web/dist is older than web/src: run `npm run build` and build the sidecar again")
    return problems


def session(client: httpx.Client) -> None:
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sidecar", type=Path, default=REPO / "packaging" / "sidecar" / "dist" / "deixis-backend")
    parser.add_argument("--keep", action="store_true", help="keep the temp folder")
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix="deixis-sidecar-smoke-"))
    assert not work.resolve().is_relative_to(REPO.resolve())
    shutil.copytree(args.sidecar, work / "deixis-backend", symlinks=True)
    binary = work / "deixis-backend" / BINARY
    bin_dir = work / "bin"
    bin_dir.mkdir()
    home = work / "home"
    home.mkdir()
    proxies = {  # outbound HTTP(S) goes to a closed local port; loopback stays direct
        "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9", "NO_PROXY": "127.0.0.1,localhost"}
    if WINDOWS:
        fake_codex_npm(bin_dir)
        system = os.environ.get("SYSTEMROOT", r"C:\Windows")
        base = {k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "PATHEXT", "COMSPEC", "ProgramFiles", "PROGRAMFILES")
                if k in os.environ}
        env = base | {"USERPROFILE": str(home), "HOME": str(home), "TEMP": str(work), "TMP": str(work),
                      "LOCALAPPDATA": str(home / "AppData" / "Local"), "APPDATA": str(home / "AppData" / "Roaming"),
                      "PATH": os.pathsep.join([str(bin_dir), str(Path(shutil.which("node")).parent), f"{system}\\System32", system]),
                      "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring", **proxies}
    else:
        codex = bin_dir / "codex"
        codex.write_text(f"#!/bin/sh\n_FAKE_CODEX_DIR={bin_dir} exec {sys.executable} {REPO / 'scripts' / 'p10' / 'fake_codex.py'} \"$@\"\n")
        codex.chmod(0o755)
        env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin", "TMPDIR": str(work), "LANG": "en_US.UTF-8",
               "USER": os.environ.get("USER", "smoke"), "SHELL": "/bin/sh",
               "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring", **proxies}
    sidecars: list[Sidecar] = []
    try:
        done = subprocess.run([str(binary), "--check-resources"], cwd=work, env=env, capture_output=True, text=True, timeout=120)
        try:
            reported = json.loads(done.stdout.strip().splitlines()[-1]).get("build_identity_sha256")
        except (ValueError, IndexError):
            reported = None
        stale = stale_build(work / "deixis-backend", reported)
        row("build_current", not stale, binary_sha256=sha256(binary), build_identity_sha256=reported, problems=stale[:20])
        if stale:
            return 1
        row("resources", done.returncode == 0, stdout=done.stdout.strip(), stderr=done.stderr.strip()[-400:])

        data = work / "data"
        sc = Sidecar(binary, data, env)
        sidecars.append(sc)
        event = sc.wait_listening()
        listening_s = time.monotonic() - sc.started
        client = httpx.Client(base_url=sc.url, timeout=30, trust_env=False)
        health = client.get("/api/health")
        health_s = time.monotonic() - sc.started
        index = client.get("/")
        row("listening", event.get("event") == "listening" and event.get("pid") == sc.proc.pid and event.get("port") != OWNER_PORT
            and health.status_code == 200 and health.json().get("nonce") == event.get("nonce")
            and index.status_code == 200 and "<div id=\"root\"" in index.text,
            port=event.get("port"), listening_s=round(listening_s, 2), health_200_s=round(health_s, 2))
        with sqlite3.connect(f"file:{data / 'library.sqlite'}?mode=ro", uri=True) as conn:
            versions = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
        row("new_library", versions == db.packaged_versions(), versions=len(versions), log=(data / "logs" / "backend.log").is_file())

        plain = httpx.Client(base_url=sc.url, timeout=30, trust_env=False)
        refused = [plain.post("/api/internal/shutdown").status_code,
                   plain.post("/api/internal/shutdown", headers={"X-Deixis-Control": "wrong"}).status_code,
                   plain.post("/api/researches", json={"question": QUESTION}).status_code]
        row("refusals", refused == [403, 403, 403], statuses=refused)

        session(client)
        made = client.post("/api/researches", json={"question": QUESTION, "source_scope": "attached", "effort": "quick",
                                                    "model_connection": "codex", "requested_model": "gpt-fake",
                                                    "reasoning_effort": "medium"})
        if made.status_code != 201:
            row("pdf", False, create=made.status_code, detail=made.text[:400])
            raise SystemExit(1)
        rid = made.json()["research"]["id"]
        pdf_bytes = make_pdf(["SYNTHETIC page one: a bounded molecule release schedule minimizes the decoding error.",
                              "SYNTHETIC page two: the schedule is computed by bisection over the release window."])
        uploaded = client.post(f"/api/researches/{rid}/uploads", files={"file": ("synthetic-release.pdf", pdf_bytes, "application/pdf")})
        sc.remember_children()
        asset = asset_of(data, uploaded.json().get("uploaded_source_version_id") if uploaded.status_code == 201 else None)
        passages = sc_passages(data, asset.get("id"))
        row("pdf", uploaded.status_code == 201 and asset.get("extraction_status") == "succeeded" and passages > 0,
            status=uploaded.status_code, extraction=asset.get("extraction_status"), pages=asset.get("page_count"), passages=passages)

        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"})
        if run.status_code in (200, 201, 202):
            view, finished = wait_run(client, rid, run.json()["id"])
            answer = (view.get("answers") or [{}])[0]
            claims = answer.get("claims") or []
            cited = [e for c in claims for e in c.get("evidence") or [] if e.get("anchor_text")]
            row("answer", finished["status"] == "completed" and answer.get("status") == "structurally_valid" and bool(cited),
                run=finished["status"], pause=finished.get("pause_reason"), failure=finished.get("failure_reason"),
                answer=answer.get("status"), claims=len(claims), cited_evidence=len(cited))
        else:
            row("answer", False, start=run.status_code, detail=run.text[:400])
        seen = bin_dir / "env-seen.json"
        names = json.loads(seen.read_text()) if seen.exists() else None
        row("token_env", names is not None and "DEIXIS_CONTROL_TOKEN" not in names, codex_started=names is not None,
            variables=len(names or []))

        ocr_row(client, data, work)
        if WINDOWS:
            startup_failed_row(binary, work, env)
            runtime_row(work, binary, env)
        if LINUX:
            startup_failed_row(binary, work, env)
            linux_runtime_row(work, binary, env)
            keychain_rows(binary, work, env)

        jats_dir = work / "jats"
        jats_dir.mkdir()
        (jats_dir / "in.xml").write_bytes(jats_xml())
        done = subprocess.run([str(binary), "-m", "deixis.documents.jats", str(jats_dir / "in.xml"), str(jats_dir / "out.pdf"),
                               str(jats_module.MAX_MEMORY_BYTES), str(jats_module.MAX_RENDER_PAGES),
                               str(jats_module.MAX_RENDER_BYTES)], cwd=work, env=env, capture_output=True, timeout=120)
        out = jats_dir / "out.pdf"
        row("jats", done.returncode == 0 and out.exists() and out.read_bytes().startswith(b"%PDF-"),
            exit=done.returncode, bytes=out.stat().st_size if out.exists() else 0, stderr=done.stderr.decode()[-300:])

        sc.remember_children()
        stopping = time.monotonic()
        stop = plain.post("/api/internal/shutdown", headers={"X-Deixis-Control": TOKEN})
        code = sc.proc.wait(STOP_LIMIT + 5)
        stop_s = time.monotonic() - stopping
        time.sleep(1)
        left = sc.leftovers()
        row("shutdown", stop.status_code == 202 and "deixis_csrf" not in plain.cookies and code == 0 and not left,
            status=stop.status_code, exit=code, seconds=round(stop_s, 2), processes_seen=len(sc.seen), leftovers=left)

        old = work / "old-data"
        (old / "papers").mkdir(parents=True)
        conn = old_library(old / "library.sqlite", 1)
        fill(conn)
        tables = compared(user_tables(conn))
        before = rows(conn, tables)
        counts = {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}  # noqa: S608
        conn.commit()
        conn.close()
        (old / "papers" / "SYNTHETIC-paper.pdf").write_bytes(PAPER)
        up = Sidecar(binary, old, env)
        sidecars.append(up)
        up.wait_listening()
        healthy = httpx.get(f"{up.url}/api/health", timeout=30, trust_env=False).status_code
        up.remember_children()
        closing = time.monotonic()
        up.proc.stdin.close()
        code = up.proc.wait(STOP_LIMIT + 5)
        closed_s = time.monotonic() - closing
        time.sleep(1)
        row("stdin_exit", code == 0 and closed_s <= STOP_LIMIT and not up.leftovers(), exit=code, seconds=round(closed_s, 2))
        conn = sqlite3.connect(old / "library.sqlite")
        fresh = sqlite3.connect(":memory:")
        db.migrate(fresh)
        record = "SELECT version, name FROM schema_migrations ORDER BY version"
        stored = conn.execute("SELECT sha256, byte_size, storage_path FROM source_assets WHERE id = 'ast_SYNTHETIC'").fetchone()
        paper = (old / "papers" / stored[2]).read_bytes()
        checks = {"health": healthy == 200, "rows": rows(conn, tables) == before,
                  "counts": {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables} == counts,  # noqa: S608
                  "pdf_hash": hashlib.sha256(paper).hexdigest() == stored[0] and len(paper) == stored[1],
                  "integrity": conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
                  "foreign_keys": conn.execute("PRAGMA foreign_key_check").fetchall() == [],
                  "versions": conn.execute(record).fetchall() == fresh.execute(record).fetchall(),
                  "schema": master(conn) == master(fresh)}
        after = rows(conn, tables)
        changed = {t: {"before": len(before[t]), "after": len(after[t])} for t in tables if after[t] != before[t]}
        conn.close()
        row("upgrade", all(checks.values()), from_version=1, changed=changed, **checks)
    finally:
        for sidecar in sidecars:
            sidecar.kill()
        size = sum(p.stat().st_size for p in (work / "deixis-backend").rglob("*") if p.is_file() and not p.is_symlink())
        print(json.dumps({"binary_sha256": sha256(binary) if binary.exists() else None,
                          "sidecar_mb": round(size / 1e6, 1), "passed": sum(r["ok"] for r in results.values()),
                          "failed": [n for n, r in results.items() if not r["ok"]], "work": str(work) if args.keep else None}))
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
    return 0 if results and all(r["ok"] for r in results.values()) else 1


def ocr_row(client: httpx.Client, data: Path, work: Path) -> None:
    """The package's own language data, then a scanned page read by the app's OCR run (the frozen `-m deixis.documents.ocr` child)."""
    tool = client.get("/api/ocr").json()
    inside = bool(tool.get("path")) and Path(tool["path"]).resolve().is_relative_to(work.resolve())
    if not (tool.get("bundled") and tool.get("engine") == "pymupdf" and tool.get("languages") == ["eng", "tur"] and inside):
        row("ocr", False, bundled=tool.get("bundled"), engine=tool.get("engine"), languages=tool.get("languages"),
            path=tool.get("path"), reason=tool.get("reason"))
        return
    made = client.post("/api/researches", json={"question": QUESTION + " (scanned)", "source_scope": "attached",
                                                "effort": "quick", "model_connection": "codex",
                                                "requested_model": "gpt-fake", "reasoning_effort": "medium"})
    orid = made.json()["research"]["id"]
    uploaded = client.post(f"/api/researches/{orid}/uploads", files={"file": (
        "synthetic-scan.pdf", scanned_pdf("SYNTHETIC scanned page about bounded release schedules"), "application/pdf")})
    osvid = uploaded.json()["uploaded_source_version_id"]
    oasset = asset_of(data, osvid)
    started = client.post(f"/api/researches/{orid}/sources/{osvid}/assets/{oasset['id']}/ocr")
    if started.status_code == 202:
        oview, orun = wait_run(client, orid, started.json()["id"])
        text = sc_text(data, oasset["id"])
        row("ocr", orun["status"] == "completed" and "release" in text.lower(), run=orun["status"],
            pause=orun.get("pause_reason"), failure=orun.get("failure_reason"), text=text[:80])
    else:
        row("ocr", False, start=started.status_code, detail=started.text[:300], extraction=oasset.get("extraction_status"))


def fake_codex_npm(bin_dir: Path) -> None:
    """Windows: the fake codex laid out as an npm global install (`tool_paths._windows_command` runs node on the entry
    script its `codex.cmd` names); the Node script runs fake_codex.py with this checkout's Python, stdio passed through."""
    entry = bin_dir / "node_modules" / "@fake" / "codex" / "bin" / "codex.js"
    entry.parent.mkdir(parents=True)
    (bin_dir / "codex.cmd").write_text(  # the tail of npm's own launcher
        '@ECHO off\r\nSETLOCAL\r\nSET dp0=%~dp0\r\nSET "_prog=node"\r\n'
        'endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  "%dp0%\\node_modules\\@fake\\codex\\bin\\codex.js" %*\r\n')
    entry.write_text(
        "const { spawnSync } = require('child_process');\n"
        f"const python = {json.dumps(sys.executable)};\n"
        f"const script = {json.dumps(str(REPO / 'scripts' / 'p10' / 'fake_codex.py'))};\n"
        "const done = spawnSync(python, [script, ...process.argv.slice(2)],\n"
        f"  {{ stdio: 'inherit', env: {{ ...process.env, _FAKE_CODEX_DIR: {json.dumps(str(bin_dir))} }} }});\n"
        "process.exit(done.status === null ? 1 : done.status);\n")


def startup_failed_row(binary: Path, work: Path, env: dict[str, str]) -> None:
    """Windows: a desktop start on a data folder that is a file prints one `startup_failed` line and exits non-zero."""
    not_a_folder = work / "not-a-folder"
    not_a_folder.write_text("SYNTHETIC")
    done = subprocess.run([str(binary), "serve", "--desktop"], cwd=work, env=env | {"DEIXIS_DATA_DIR": str(not_a_folder)},
                          input=f"{TOKEN}\n".encode(), capture_output=True, timeout=120)
    lines = [line for line in done.stdout.decode(errors="replace").splitlines() if line.strip()]
    try:
        event = json.loads(lines[0]) if len(lines) == 1 else {}
    except ValueError:
        event = {}
    row("startup_failed", event.get("event") == "startup_failed" and done.returncode != 0, code=event.get("code"),
        exit=done.returncode, lines=len(lines), message=str(event.get("message"))[:200])


def runtime_row(work: Path, binary: Path, env: dict[str, str]) -> None:
    """Windows: `--check-runtime` (in-process native code after the DLL search reset) with the DLL probe."""
    internal = binary.parent / "_internal"
    system32 = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32"
    name = next((n for n in PROBE_NAMES if (internal / f"{n}.dll").is_file() and not (system32 / f"{n}.dll").exists()), None)
    rustc = shutil.which("rustc")
    folder, dll_dir, exe_dir = work / "runtime", work / "probe-dll", work / "probe-exe"
    for made in (folder, dll_dir, exe_dir):
        made.mkdir()
    args = [str(binary), "--check-runtime", str(folder), "--https", HTTPS_URL]
    probe = {"dll": name, "rustc": rustc}
    if name and rustc:
        source = REPO / "scripts" / "p10" / "dll_probe"
        static = ["-C", "target-feature=+crt-static", "-O"]
        built = [subprocess.run([rustc, "--crate-type", "cdylib", *static, "-o", str(dll_dir / f"{name}.dll"),
                                 str(source / "probe_dll.rs")], capture_output=True, text=True),
                 subprocess.run([rustc, *static, "-o", str(exe_dir / f"probe-{name}.exe"), str(source / "probe.rs")],
                                capture_output=True, text=True)]
        probe["build"] = [b.returncode for b in built]
        if all(b.returncode == 0 for b in built):
            args += ["--probe", str(exe_dir / f"probe-{name}.exe")]
            # Negative control: with the package folder as an inherited DLL directory, as PyInstaller's bootloader sets
            # it, the probe must get the package's copy (exit 3); this shows the probe can see what the check rules out.
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.SetDllDirectoryW.argtypes = (ctypes.c_wchar_p,)
            kernel32.SetDllDirectoryW(str(internal))
            try:
                control = subprocess.run([str(exe_dir / f"probe-{name}.exe")], capture_output=True, text=True, timeout=60,
                                         env=env | {"PATH": os.pathsep.join([env["PATH"], str(dll_dir)])})
            finally:
                kernel32.SetDllDirectoryW(None)
            probe["control"] = {"exit": control.returncode, "said": control.stdout.strip()[-200:]}
        else:
            probe["build_error"] = "\n".join(b.stderr for b in built)[-400:]
    # The real keyring and the network for this one call; the probe DLL's folder last on PATH, after the system's.
    run_env = {k: v for k, v in env.items() if k not in ("PYTHON_KEYRING_BACKEND", "HTTP_PROXY", "HTTPS_PROXY")}
    run_env["PATH"] = os.pathsep.join([env["PATH"], str(dll_dir)])
    done = subprocess.run(args, cwd=work, env=run_env, capture_output=True, text=True, timeout=180)
    try:
        report = json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        report = {"ok": False, "stdout": done.stdout[-400:], "stderr": done.stderr[-400:]}
    checks = report.get("checks", {})
    row("runtime", done.returncode == 0 and report.get("ok") is True and "dll_probe" in checks
        and probe.get("control", {}).get("exit") == 3, exit=done.returncode,
        probe=probe, checks=checks, **({} if checks else {"report": report}))


class PrivateKeyring:
    """A D-Bus session bus and a gnome-keyring of this smoke's own (in a temp HOME, unlocked with a throwaway password),
    so the Secret Service rows never reach the caller's bus or keyring. `env` is None where dbus-daemon or
    gnome-keyring-daemon is not installed (those rows are then not measured)."""

    def __init__(self, work: Path):
        self.procs: list[subprocess.Popen] = []
        self.env: dict[str, str] | None = None
        if not (shutil.which("dbus-daemon") and shutil.which("gnome-keyring-daemon")):
            return
        home = Path(tempfile.mkdtemp(prefix="keyring-home-", dir=work))  # one per instance (runtime row, keychain rows)
        runtime = home / "run"
        runtime.mkdir(parents=True)
        runtime.chmod(0o700)
        env = {"HOME": str(home), "XDG_RUNTIME_DIR": str(runtime), "XDG_DATA_HOME": str(home / "share"),
               "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        bus = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.procs.append(bus)
        env["DBUS_SESSION_BUS_ADDRESS"] = bus.stdout.readline().strip()
        keyring = subprocess.Popen(["gnome-keyring-daemon", "--foreground", "--unlock", "--components=secrets"], env=env,
                                   stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        self.procs.append(keyring)
        keyring.stdin.write("deixis-smoke-throwaway")  # an empty password leaves no default collection (a prompt)
        keyring.stdin.close()
        ends = time.monotonic() + 10
        while not (home / "share" / "keyrings" / "login.keyring").exists() and time.monotonic() < ends:
            time.sleep(0.1)
        self.env = {k: env[k] for k in ("DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR")}

    def close(self) -> None:
        for proc in reversed(self.procs):
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


LINUX_PROBE_LIBS = ("libssl.so.3", "libcrypto.so.3", "libffi.so.8", "libz.so.1", "liblzma.so.5", "libbz2.so.1.0")


def linux_runtime_row(work: Path, binary: Path, env: dict[str, str]) -> None:
    """Linux (P10 L3): `--check-runtime` with the library probe (scripts/p10/dll_probe/linux_probe.c, built here with
    gcc), which loads by soname a library the package also holds in _internal/ and logs the file the loader picked and
    the LD_LIBRARY_PATH it got, on the three routes an outside program is started by (`child_env`, a model CLI through
    Codex's allowlist and the session launcher, the Claude Agent SDK's own transport). The person's own LD_LIBRARY_PATH
    must come back unchanged (Codex's allowlist drops the name altogether), and no route may load the package's copy.
    The person's folder holds a copy of the system's library (the marker): the routes that keep the person's
    LD_LIBRARY_PATH must load that copy, the CLI route the system's; a probe that loads nothing fails. Negative control:
    started with _internal on LD_LIBRARY_PATH, the probe loads the package's copy. The in-process keychain check runs
    against this smoke's own bus and keyring (`PrivateKeyring`), never the caller's; without gnome-keyring it is not
    measured."""
    folder = work / "runtime"
    folder.mkdir()
    internal = binary.parent / "_internal"
    system = {}
    for line in subprocess.run(["ldconfig", "-p"], capture_output=True, text=True).stdout.splitlines():
        name, _, target = line.strip().partition(" => ")
        if "64" in name:  # "(libc6,x86-64)" / "(libc6,AArch64)": this machine's own libraries
            system.setdefault(name.split(" ")[0], target.strip())
    # The listed ones first; a uv-installed Python links OpenSSL and zlib statically, so then any library the package
    # holds under a soname the system also has.
    held = sorted(p.name for p in internal.glob("lib*.so*") if p.is_file() and p.name in system)
    lib = next((name for name in LINUX_PROBE_LIBS if name in held), held[0] if held else None)
    probe = work / "probe-bin" / "linux-probe"
    probe.parent.mkdir()
    built = subprocess.run(["gcc", "-O2", f'-DPROBE_LIB="{lib}"', "-o", str(probe),
                            str(REPO / "scripts" / "p10" / "dll_probe" / "linux_probe.c"), "-ldl"],
                           capture_output=True, text=True) if lib and shutil.which("gcc") else None
    if built is None or built.returncode != 0:
        row("runtime", False, library=lib, gcc=shutil.which("gcc"), build=built.stderr[-400:] if built else None,
            system_libraries=len(system), package_libraries=sorted(p.name for p in internal.glob("lib*.so*"))[:40])
        return
    log = Path(f"{probe}.log")
    subprocess.run([str(probe), "control"], env=env | {"LD_LIBRARY_PATH": str(internal)}, check=True)
    control = log.read_text().strip().split("\t")[-1]
    log.unlink()
    marker = work / "person-libs"  # the person's own LD_LIBRARY_PATH, with the marker copy of the system's library
    marker.mkdir()
    shutil.copy2(system[lib], marker / lib)
    person = str(marker)
    private = PrivateKeyring(work)
    keychain = private.env is not None
    run_env = {k: v for k, v in env.items() if k not in ("PYTHON_KEYRING_BACKEND", "HTTP_PROXY", "HTTPS_PROXY",
                                                          "DBUS_SESSION_BUS_ADDRESS")}
    run_env["LD_LIBRARY_PATH"] = person
    if keychain:
        run_env |= private.env
    else:
        run_env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    try:
        done = subprocess.run([str(binary), "--check-runtime", str(folder), "--https", HTTPS_URL, "--library-probe",
                               str(probe)], cwd=work, env=run_env, capture_output=True, text=True, timeout=180)
    finally:
        private.close()
    try:
        report = json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        report = {"ok": False, "stdout": done.stdout[-400:], "stderr": done.stderr[-400:]}
    checks = report.get("checks", {})
    needed = ["pdf_render", "https", "library_paths"] + (["credential_locker"] if keychain else [])
    routes = checks.get("library_paths", {}).get("routes", {})
    def loaded(route: str) -> Path | None:
        value = routes.get(route, {}).get("loaded", "-")
        return Path(value).resolve() if value not in ("", "-") else None

    row("runtime", all(checks.get(name, {}).get("ok") for name in needed) and len(routes) == 3
        and all(r["ld_library_path"] == person and loaded(n) == (marker / lib).resolve()
                for n, r in routes.items() if n != "cli")
        and routes.get("cli", {}).get("ld_library_path") in ("", person)  # Codex's allowlist does not pass it on at all
        and loaded("cli") in (Path(system[lib]).resolve(), (marker / lib).resolve())
        and Path(control).resolve().is_relative_to(internal.resolve()), exit=done.returncode, library=lib,
        control=control, keychain="measured" if keychain else "not measured", checks=checks,
        **({} if checks else {"report": report}))


def keychain_rows(binary: Path, work: Path, env: dict[str, str]) -> None:
    """Linux (P10 L3): where a saved key lives and whether it survives a restart of the backend.
    keychain_secret_service (against this smoke's own bus and throwaway keyring, `PrivateKeyring`; not measured without
    gnome-keyring): Settings names the keychain, a key saved through the API is read back by a new backend on the same
    data folder, then deleted.
    keychain_none (no session bus): Settings says there is no keychain; a saved key works for this run (source
    `session`) and is gone after a restart; after the person chooses the unencrypted file, a saved key is in a 0600 file
    in the data folder and a new backend reads it back."""
    def backend(data: Path, extra: dict[str, str]) -> tuple[Sidecar, httpx.Client]:
        sc = Sidecar(binary, data, extra)
        sc.wait_listening()
        client = httpx.Client(base_url=sc.url, timeout=30, trust_env=False)
        session(client)
        return sc, client

    def stop(sc: Sidecar, client: httpx.Client) -> None:
        client.post("/api/internal/shutdown", headers={"X-Deixis-Control": TOKEN})
        try:
            sc.proc.wait(20)
        finally:
            sc.kill()
            client.close()

    base = {k: v for k, v in env.items() if k not in ("PYTHON_KEYRING_BACKEND", "DBUS_SESSION_BUS_ADDRESS")}
    key, value = "ZOTERO_LIBRARY_ID", "7340021"
    def key_status(client: httpx.Client) -> dict:
        return next(k for k in client.get("/api/credentials").json()["keys"] if k["env"] == key)

    private = PrivateKeyring(work)
    try:
        if private.env is not None:
            bus = base | private.env
            data = work / "keychain-ss"
            sc, client = backend(data, bus)
            try:
                first = client.get("/api/credentials").json()["keychain"]
                saved = client.put(f"/api/credentials/{key}", json={"value": value}).status_code
            finally:
                stop(sc, client)
            sc, client = backend(data, bus)
            try:
                again = key_status(client)
                deleted = client.delete(f"/api/credentials/{key}").status_code
            finally:
                stop(sc, client)
            row("keychain_secret_service", first.get("available") is True and first.get("mode") == "keychain"
                and saved == 200 and again.get("configured") is True and again.get("source") == "keychain"
                and deleted in (200, 204), keychain=first.get("name"), saved=saved, read_back=again.get("source"),
                deleted=deleted, bus="this smoke's own")
        else:
            row("keychain_secret_service", True, measured=False, reason="dbus-daemon or gnome-keyring not installed here")
    finally:
        private.close()
    data = work / "keychain-none"
    sc, client = backend(data, base)
    try:
        first = client.get("/api/credentials").json()["keychain"]
        in_session = client.put(f"/api/credentials/{key}", json={"value": value}).status_code
        session_source = key_status(client).get("source")
    finally:
        stop(sc, client)
    sc, client = backend(data, base)
    try:
        after_restart = key_status(client).get("configured")
        chosen = client.put("/api/credentials/file-store", json={"enabled": True}).status_code
        saved = client.put(f"/api/credentials/{key}", json={"value": value}).status_code
        files = [p for p in data.rglob("*") if p.is_file() and value in p.read_text(errors="ignore")]
        modes = sorted(oct(p.stat().st_mode & 0o777) for p in files)
    finally:
        stop(sc, client)
    sc, client = backend(data, base)
    try:
        again = next(k for k in client.get("/api/credentials").json()["keys"] if k["env"] == key)
    finally:
        stop(sc, client)
    row("keychain_none", first.get("available") is False and first.get("mode") == "session" and in_session == 200
        and session_source == "session" and after_restart is False and chosen == 200 and saved == 200
        and modes == ["0o600"] and again.get("configured") is True and again.get("source") == "file",
        mode=first.get("mode"), session_saved=in_session, session_source=session_source,
        session_after_restart=after_restart, chosen=chosen, saved=saved, file_modes=modes, read_back=again.get("source"))


def sc_passages(data: Path, asset_id: str | None) -> int:
    if not asset_id:
        return 0
    with sqlite3.connect(f"file:{data / 'library.sqlite'}?mode=ro", uri=True) as conn:
        return conn.execute("SELECT COUNT(*) FROM passages WHERE asset_id = ? AND kind = 'pdf_page'", (asset_id,)).fetchone()[0]


def sc_text(data: Path, asset_id: str) -> str:
    with sqlite3.connect(f"file:{data / 'library.sqlite'}?mode=ro", uri=True) as conn:
        found = conn.execute("SELECT text FROM passages WHERE asset_id = ? AND text_source = 'ocr'", (asset_id,)).fetchall()
    return " ".join(r[0] for r in found)


if __name__ == "__main__":
    raise SystemExit(main())
