"""Smoke run of the BUILT backend sidecar (P10 M1 acceptance), macOS arm64.

    uv run python scripts/p10/sidecar_smoke.py [--sidecar packaging/sidecar/dist/deixis-backend] [--keep]

The onedir build is copied to a temp folder outside the checkout and run from there with a temp DEIXIS_DATA_DIR, no
DEIXIS_REPO_ROOT, a minimal environment, a port other than 8765 (saved in the data folder before the start), the null
keyring backend and outbound HTTP(S) sent to a closed local port. A stand-in `codex` (fake_codex.py, run by this
checkout's Python) is first on PATH. Tesseract is the one installed on this Mac (Homebrew), found by the app's own
tool lookup. Rows, each printed as passed or failed:

  resources    `deixis-backend --check-resources` passes
  listening    the `listening` line arrives; health 200 with its nonce; index.html served; cold start timed
  new_library  a new library made from the packaged schema.sql (its versions equal this checkout's)
  refusals     shutdown without or with a wrong token 403; a normal POST without CSRF 403
  pdf          a synthetic PDF upload gives passages (the frozen `-m deixis.documents.pdf` child and its guard)
  answer       question -> cited answer through the packaged binary, the uploaded PDF the only source, fake codex
  token_env    DEIXIS_CONTROL_TOKEN is not in the fake codex's environment
  ocr          a scanned page read by the app's OCR run (the frozen `-m deixis.documents.ocr` child)
  jats         one JATS file drawn as a PDF by `deixis-backend -m deixis.documents.jats` (invoked here, not by the app)
  shutdown     shutdown with the token and no CSRF cookie; exit 0; no leftover process (pid + start time)
  upgrade      a filled library made by the old migration files (version 1) opens and upgrades: rows and counts
               (less the worker lease and the citation keys every start writes), PDF hash, integrity_check,
               foreign_key_check, and the version record and schema as a new library's
  stdin_exit   stdin closed -> exit within 6 s + 4 s margin

Before anything runs, the build must be current (row build_current): the build identity the binary reports (through
`--check-resources`) equals the identity file in the folder, its per-file sha256 list equals this working tree's
`deixis/**/*.py`, every `package_manifest.datas()` file in the bundle equals its source, and web/dist is newer than
everything under web/src; on a mismatch the run stops. The result line names the sha256 of the binary.

Every record is SYNTHETIC. Passing shows the packaged process runs these paths on this Mac; it says nothing about a
real model, a clean machine or the window.
"""

from __future__ import annotations

import argparse
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


def lstart(pid: int) -> str | None:
    done = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True)
    return done.stdout.strip() or None


def descendants(pid: int) -> set[int]:
    found, todo = set(), [pid]
    while todo:
        done = subprocess.run(["pgrep", "-P", str(todo.pop())], capture_output=True, text=True)
        for child in map(int, done.stdout.split()):
            if child not in found:
                found.add(child)
                todo.append(child)
    return found


class Sidecar:
    """One `serve --desktop` process of the copied binary; its stdout read on a thread."""

    def __init__(self, binary: Path, data: Path, env: dict[str, str]):
        port = free_port()
        data.mkdir(parents=True, exist_ok=True)
        (data / "desktop-port.json").write_text(json.dumps({"port": port}))
        self.env = env | {"DEIXIS_DATA_DIR": str(data), "DEIXIS_PORT": str(free_port()), "DEIXIS_CONTROL_TOKEN": TOKEN}
        self.started = time.monotonic()
        self.proc = subprocess.Popen([str(binary), "serve", "--desktop"], cwd=binary.parent.parent, env=self.env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=open(data / "stderr.txt", "wb"))
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
            self.remember_children()
            done = subprocess.run(["ps", "-axww", "-o", "pid=,command="], capture_output=True, text=True)
            for line in done.stdout.splitlines():
                pid, _, command = line.strip().partition(" ")
                if pid.isdigit() and int(pid) != os.getpid() and any(m in command for m in self.marks):
                    self.seen.setdefault(int(pid), lstart(int(pid)))
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

    def remember_children(self) -> None:
        for pid in descendants(self.proc.pid):
            self.seen.setdefault(pid, lstart(pid))

    def leftovers(self) -> list[tuple[int, str]]:
        return [(pid, start) for pid, start in self.seen.items() if start and lstart(pid) == start]

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
    binary = work / "deixis-backend" / "deixis-backend"
    bin_dir = work / "bin"
    bin_dir.mkdir()
    codex = bin_dir / "codex"
    codex.write_text(f"#!/bin/sh\n_FAKE_CODEX_DIR={bin_dir} exec {sys.executable} {REPO / 'scripts' / 'p10' / 'fake_codex.py'} \"$@\"\n")
    codex.chmod(0o755)
    home = work / "home"
    home.mkdir()
    env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin", "TMPDIR": str(work), "LANG": "en_US.UTF-8",
           "USER": os.environ.get("USER", "smoke"), "SHELL": "/bin/sh",
           "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
           # outbound HTTP(S) goes to a closed local port; loopback stays direct
           "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9", "NO_PROXY": "127.0.0.1,localhost"}
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
