"""P9 H3, F05: what a full disk does to a running DEIXIS, on a real full volume.

The fixture server (`tests/acceptance/fixture_server.py`: the real app with a scripted model and mocked OpenAlex and
PDF links, every record SYNTHETIC) keeps its data directory on a 16 MiB HFS+ sparse disk image. The test fills the
image to 0 bytes free, sends requests, frees the space and checks that nothing was left half written. No other volume
is touched: the image is attached under the test's own tmp folder and always detached and deleted afterwards.
It shows how the application behaves on a full disk; it measures no model quality and no live provider access.

Run on their own: `PYTHONPATH=backend:. uv run pytest tests/process/test_disk_full.py -m process -n 0 -q`.
"""

from __future__ import annotations

import errno
import hashlib
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import warnings
from pathlib import Path

import httpx
import pytest

from helpers import make_pdf

pytestmark = [
    pytest.mark.process,
    pytest.mark.skipif(sys.platform != "darwin" or shutil.which("hdiutil") is None,
                       reason="needs macOS and hdiutil to build a small full disk image"),
]

REPO = Path(__file__).resolve().parents[2]
FIXTURE_SERVER = REPO / "tests" / "acceptance" / "fixture_server.py"
SENTENCE = "DEIXIS could not save because the disk is full. Free some space and try again."
START_SECONDS = 30
MODEL = "fixture-model"


def sh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=120)


@pytest.fixture
def volume(tmp_path):
    """A 16 MiB HFS+ volume mounted under tmp_path; detached and deleted even when the test fails."""
    image, mount = tmp_path / "deixis-h3.sparseimage", tmp_path / "mnt"
    mount.mkdir()
    attached = False
    try:
        made = sh("hdiutil", "create", "-type", "SPARSE", "-size", "16m", "-fs", "HFS+", "-volname", "deixis-h3", str(image))
        assert made.returncode == 0, made.stderr
        attached = True  # before the call: a timed-out or failed attach may still have left a device behind; the finalizer detaches either way
        attach = sh("hdiutil", "attach", str(image), "-mountpoint", str(mount), "-nobrowse", "-noverify")
        assert attach.returncode == 0, attach.stderr
        yield mount
    finally:
        detached = not attached
        for _ in range(5):
            if detached or sh("hdiutil", "detach", str(mount), "-force").returncode == 0:
                detached = True
                break
            time.sleep(1)
        if not detached and str(mount) in sh("hdiutil", "info").stdout:
            # Still mounted: keep the image so the volume is not pulled away from a live mount, and say so.
            warnings.warn(f"could not detach {mount}; the image {image} was left in place (run `hdiutil detach {mount} -force`)")
        else:
            image.unlink(missing_ok=True)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Server:
    """The fixture server as a child process with a named allow-list environment; only this PID is ever signalled."""

    def __init__(self, data_dir: Path, tmp_path: Path):
        self.data_dir, self.port = data_dir, free_port()
        home, logs = tmp_path / "home", tmp_path / "logs"  # outside the volume: logs must not eat its space
        home.mkdir(exist_ok=True)
        logs.mkdir(exist_ok=True)
        env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "PYTHONPATH": str(REPO / "backend"),
               "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring", "PYTHONDONTWRITEBYTECODE": "1"}
        self.err_path = logs / "err.txt"
        with open(logs / "out.txt", "wb") as out, open(self.err_path, "wb") as err:
            self.proc = subprocess.Popen(
                [sys.executable, str(FIXTURE_SERVER), "--data-dir", str(data_dir), "--port", str(self.port)],
                cwd=REPO, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err)
        self.url = f"http://127.0.0.1:{self.port}"

    def wait_healthy(self) -> None:
        deadline = time.monotonic() + START_SECONDS
        while time.monotonic() < deadline:
            assert self.proc.poll() is None, f"the fixture server exited early: {self.err_path.read_text()}"
            try:
                if httpx.get(f"{self.url}/api/health", timeout=2).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.2)
        pytest.fail("the fixture server did not become healthy")

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
        try:
            self.proc.wait(timeout=START_SECONDS)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()

    def call(self, method: str, path: str, **kwargs) -> httpx.Response:
        """One request on a fresh client with its own CSRF token: a failed request closes the keep-alive connection."""
        with httpx.Client(base_url=self.url, timeout=60) as client:
            token = client.get("/api/session").json()["csrf_token"]
            return client.request(method, path, headers={"x-deixis-csrf": token}, **kwargs)


@pytest.fixture
def server_factory(tmp_path):
    started: list[Server] = []

    def make(data_dir: Path) -> Server:
        server = Server(data_dir, tmp_path)
        started.append(server)
        server.wait_healthy()
        return server

    yield make
    for server in started:
        server.stop()


def create_research(server: Server, scope: str, question: str = "How is molecule release scheduling optimized?") -> httpx.Response:
    return server.call("POST", "/api/researches", json={
        "question": question, "source_scope": scope, "model_connection": "codex", "requested_model": MODEL, "effort": "quick"})


_serial = iter(range(1, 1000))


def upload(server: Server, research_id: str) -> httpx.Response:
    """A PDF whose bytes differ on every call, so each upload is a new file."""
    pdf = make_pdf([f"SYNTHETIC disk-full test page {next(_serial)} {time.time_ns()}."])
    return server.call("POST", f"/api/researches/{research_id}/uploads", files={"file": ("notes.pdf", pdf, "application/pdf")})


def free_bytes(path: Path) -> int:
    stat = os.statvfs(path)
    return stat.f_bavail * stat.f_frsize


def fill(mount: Path, library: Path, checkpoint: str = "TRUNCATE") -> Path:
    """Fold the library's WAL into the main file, then take every free byte of the volume with one file.

    TRUNCATE empties the WAL file, so the next commit needs new blocks and fails on the full volume. RESTART keeps the
    file at its size and starts the next commit at its beginning, so commits keep succeeding on the full volume as long
    as they fit in the old size (the download test needs this: only the PDF write may find no room)."""
    side = sqlite3.connect(library, timeout=30)
    try:
        side.execute(f"PRAGMA wal_checkpoint({checkpoint})")
    finally:
        side.close()
    filler = mount / "filler.bin"
    with open(filler, "wb", buffering=0) as out:
        for chunk in (1 << 20, 1 << 16, 1 << 12, 512, 64, 8, 1):
            block = b"\0" * chunk
            while True:
                try:
                    out.write(block)
                except OSError as exc:
                    assert exc.errno == errno.ENOSPC, exc
                    break
    assert free_bytes(mount) == 0
    return filler


def release(filler: Path) -> None:
    filler.unlink()
    assert free_bytes(filler.parent) > 8 << 20


def leftovers(papers: Path) -> list[str]:
    return sorted(p.name for p in papers.rglob("*") if p.suffix in (".partial", ".part"))


def assert_papers_are_whole(papers: Path) -> None:
    """Every stored PDF is named by the SHA-256 of its bytes, and no temporary file remains."""
    assert leftovers(papers) == []
    for pdf in papers.glob("*.pdf"):
        assert hashlib.sha256(pdf.read_bytes()).hexdigest() == pdf.stem, f"{pdf.name} does not hold the bytes it is named for"


def assert_library_is_whole(library: Path) -> None:
    conn = sqlite3.connect(library)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def refused(response: httpx.Response) -> bool:
    return response.status_code == 507 and response.json() == {"detail": SENTENCE, "code": "disk_full"}


def test_full_disk_is_refused_in_one_sentence_and_nothing_is_left_half_written(volume, server_factory):
    """O12/F05: on a full volume create and upload are refused 507 `disk_full`, nothing is left half written."""
    data = volume / "data"
    server = server_factory(data)
    papers, library = data / "papers", data / "library.sqlite"
    # papers/ must exist already: a missing papers/ folder that cannot be created is a bare OSError in the upload route
    # (a 500, listed as a limit), not the DiskFull the upload's own write raises.
    attached = create_research(server, "attached")
    assert attached.status_code == 201, attached.text
    research_id = attached.json()["research"]["id"]
    assert upload(server, research_id).status_code == 201
    assert papers.is_dir()

    filler = fill(volume, library)
    attempts, problems = {}, []  # attempts: requests sent before the first disk_full refusal, per route
    try:
        for name, attempt in (("create", lambda: create_research(server, "attached")), ("upload", lambda: upload(server, research_id))):
            for n in range(1, 6):
                response = attempt()
                if refused(response):
                    attempts[name] = n
                    break
                # Collected, not raised, so the recovery steps below still run and the whole picture is measured.
                problems.append(f"{name} attempt {n}: {response.status_code} {response.text[:200]}")
            else:
                attempts[name] = None
            assert server.call("GET", "/api/health").status_code == 200
            assert leftovers(papers) == []
        print(f"\nattempts before the disk_full refusal after filling: {attempts}")
        assert server.proc.poll() is None
    finally:
        release(filler)

    recovered = create_research(server, "attached")
    assert recovered.status_code == 201
    recovered_id = recovered.json()["research"]["id"]
    assert upload(server, research_id).status_code == 201
    assert server.call("GET", "/api/health").status_code == 200

    server.stop()
    assert server.proc.returncode in (0, -signal.SIGTERM), server.err_path.read_text()
    assert_library_is_whole(library)
    # The writes made after the space came back are on disk, not only in the server's connection.
    reopened = sqlite3.connect(library)
    try:
        assert reopened.execute("SELECT COUNT(*) FROM researches WHERE id = ?", (recovered_id,)).fetchone()[0] == 1
        assert reopened.execute("SELECT COUNT(*) FROM source_assets").fetchone()[0] >= 1
    finally:
        reopened.close()
    assert_papers_are_whole(papers)
    # The first attempt after filling must already be refused with the one sentence, on both routes.
    assert attempts == {"create": 1, "upload": 1}, problems


INCLUDED = ("SYNTHETIC molecule release scheduling with bisection", "SYNTHETIC relay budget allocation",
            "SYNTHETIC molecule schedule letter")


def wait_for_run(server: Server, research_id: str, run_id: str, timeout: float = 60) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        view = server.call("GET", f"/api/researches/{research_id}").json()
        run = next(r for r in view["runs"] if r["id"] == run_id)
        if run["status"] in ("completed", "failed", "paused", "cancelled"):
            return run
        time.sleep(0.2)
    pytest.fail(f"run {run_id} did not finish in {timeout} s")


def test_pdf_download_run_on_a_full_disk(volume, server_factory):
    """O12/F05: a PDF download run on a full volume ends `failed` / `disk_full`, and the next run completes once there is room."""
    data = volume / "data"
    server = server_factory(data)
    papers, library = data / "papers", data / "library.sqlite"
    created = create_research(server, "academic")
    assert created.status_code == 201, created.text
    research_id = created.json()["research"]["id"]
    discovery = server.call("POST", f"/api/researches/{research_id}/runs", json={"kind": "discovery"})
    assert discovery.status_code == 202, discovery.text
    assert wait_for_run(server, research_id, discovery.json()["id"])["status"] == "completed"
    view = server.call("GET", f"/api/researches/{research_id}").json()
    for source in view["sources"]:
        if source["version_role"] == "record" and source["title"] in INCLUDED:
            done = server.call("PATCH", f"/api/researches/{research_id}/selections/{source['source_version_id']}", json={
                "state": "included", "expected_version": source["selection"]["version"], "reason": "SYNTHETIC test selection"})
            assert done.status_code == 200, done.text
    # papers/ exists once any file was stored; the PDF write below is then the first thing to find no room.
    attached = create_research(server, "attached")
    assert upload(server, attached.json()["research"]["id"]).status_code == 201
    wal = Path(f"{library}-wal")
    assert wal.stat().st_size >= 1 << 20, "the WAL is too small to carry a run's commits on a full disk"
    filler = fill(volume, library, checkpoint="RESTART")
    try:
        first = server.call("POST", f"/api/researches/{research_id}/runs", json={"kind": "answer"})
        assert first.status_code == 202, first.text  # the run's own rows fit in the old WAL
        run = wait_for_run(server, research_id, first.json()["id"])
        # Measured: the run ends failed with pause_reason disk_full (the PDF download's OSError ENOSPC, recorded once the
        # failure row could be written), not running, not paused, not completed on abstracts alone.
        assert (run["status"], run["pause_reason"]) == ("failed", "disk_full"), run
        assert server.call("GET", "/api/health").status_code == 200
        assert server.proc.poll() is None
        assert leftovers(papers) == []
    finally:
        filler.unlink()

    assert free_bytes(volume) > 8 << 20
    second = server.call("POST", f"/api/researches/{research_id}/runs", json={"kind": "answer"})
    assert second.status_code == 202, second.text
    run = wait_for_run(server, research_id, second.json()["id"])
    assert run["status"] == "completed", run
    view = server.call("GET", f"/api/researches/{research_id}").json()
    assert any(a["status"] == "structurally_valid" for a in view["answers"]), view["answers"]

    server.stop()
    assert server.proc.returncode in (0, -signal.SIGTERM), server.err_path.read_text()
    assert_library_is_whole(library)
    # H2's store_pdf_file (a .part file and os.replace) replaces the direct write_bytes in flow._fetch_pdf. With this
    # fixture the PDFs are 600 bytes and the open() itself fails on a full HFS+ volume, so no partial file can appear
    # here: this step shows the run's state, not the absence of a half-written PDF.
    assert_papers_are_whole(papers)
