"""P9 H3, O8 and O9: what `python -m deixis serve` does with a library file it cannot open, or cannot find.

Every case starts the real launcher as a child process (the model-free parts of the app only: no model CLI on PATH, no
keychain, a temporary HOME and data directory) and looks at its exit code, its stderr and the files it leaves behind.
The tests show the launcher's behavior on synthetic libraries; they say nothing about model quality or provider access.

Run on their own: `PYTHONPATH=backend:. uv run pytest tests/process/test_library_open_faults.py -m process -n 0 -q`.
"""

from __future__ import annotations

import hashlib
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.process

REPO = Path(__file__).resolve().parents[2]
START_SECONDS = 20  # generous: a refusal takes well under a second, a healthy start a few


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def launcher_env(data_dir: Path, home: Path) -> dict[str, str]:
    """A named allow-list: nothing of the caller's environment (no provider key, no model CLI) reaches the child."""
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        "PYTHONPATH": str(REPO / "backend"),
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
        "DEIXIS_DATA_DIR": str(data_dir),
    }


def start(data_dir: Path, tmp_path: Path, port: int, **files) -> subprocess.Popen:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return subprocess.Popen(
        [sys.executable, "-m", "deixis", "serve", "--no-browser", "--port", str(port)], cwd=REPO,
        env=launcher_env(data_dir, home), stdin=subprocess.DEVNULL,
        stdout=files.get("stdout", subprocess.PIPE), stderr=files.get("stderr", subprocess.PIPE))


def make_library(path: Path) -> None:
    """A real, migrated library: db.connect plus db.migrate on a fresh file, closed so the WAL is folded in."""
    from deixis.storage import db

    conn = db.connect(path)
    db.migrate(conn)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    for suffix in ("-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)
    assert path.stat().st_size > 4096


def refuses(tmp_path: Path, damage) -> tuple[subprocess.CompletedProcess, Path, str, float]:
    data = tmp_path / "data"
    data.mkdir()
    library = data / "library.sqlite"
    damage(library)
    before = sha256(library)
    started = time.monotonic()
    proc = start(data, tmp_path, free_port())
    try:
        out, err = proc.communicate(timeout=START_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        pytest.fail(f"the launcher did not exit within {START_SECONDS} s")
    elapsed = time.monotonic() - started
    # An empty -wal and -shm file may appear next to the library (SQLite creates them when the file is opened in WAL
    # mode before the damage is noticed). This is not asserted away; the main file is what must stay byte-identical.
    assert sha256(library) == before, "the launcher changed the library file"
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err), library, before, elapsed


def assert_one_sentence(result, library: Path, reason: str, elapsed: float) -> None:
    err = result.stderr.decode()
    assert result.returncode == 2, err
    assert elapsed < 10, f"took {elapsed:.1f} s to refuse"
    assert str(library) in err
    assert reason in err
    assert "Traceback" not in err
    assert "did not start" in err


def garbage(library: Path) -> None:
    library.write_bytes(b"this is not a sqlite database\n" * 400)


def truncated(size) -> object:
    def damage(library: Path) -> None:
        make_library(library)
        whole = library.read_bytes()
        library.write_bytes(whole[: size(len(whole))])
    return damage


def test_garbage_library_is_refused_in_one_sentence(tmp_path):
    """O8: a file that is not a database exits 2 with one sentence."""
    result, library, _, elapsed = refuses(tmp_path, garbage)
    assert_one_sentence(result, library, "file is not a database", elapsed)


def test_library_cut_in_half_is_refused_in_one_sentence(tmp_path):
    """O8: a library cut in half exits 2 with one sentence."""
    result, library, _, elapsed = refuses(tmp_path, truncated(lambda n: n // 2))
    assert_one_sentence(result, library, "database disk image is malformed", elapsed)


def test_library_cut_to_100_bytes_is_refused_in_one_sentence(tmp_path):
    """O8: a library cut to 100 bytes exits 2 with one sentence."""
    result, library, _, elapsed = refuses(tmp_path, truncated(lambda n: 100))
    assert library.stat().st_size == 100
    assert_one_sentence(result, library, "database disk image is malformed", elapsed)


def stop(proc: subprocess.Popen) -> int:
    """SIGTERM the child this test started and wait for it; kill it only if it ignores the signal."""
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
    try:
        return proc.wait(timeout=START_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise


def serve_until_healthy(data: Path, tmp_path: Path):
    port = free_port()
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    with open(logs / "out.txt", "wb") as out, open(logs / "err.txt", "wb") as err:
        proc = start(data, tmp_path, port, stdout=out, stderr=err)
    try:
        deadline = time.monotonic() + START_SECONDS
        while time.monotonic() < deadline:
            assert proc.poll() is None, f"the launcher exited early: {(logs / 'err.txt').read_text()}"
            try:
                if httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=2).status_code == 200:
                    return proc, port
            except httpx.TransportError:
                time.sleep(0.2)
        pytest.fail(f"/api/health did not answer 200 within {START_SECONDS} s")
    except BaseException:
        stop_quietly(proc)
        raise


def stop_quietly(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.kill()
        proc.wait()


def test_zero_byte_library_starts_as_a_fresh_library(tmp_path):
    """O8: an empty library file is a first run: it starts as a fresh library."""
    data = tmp_path / "data"
    data.mkdir()
    library = data / "library.sqlite"
    library.write_bytes(b"")
    proc, port = serve_until_healthy(data, tmp_path)
    try:
        listing = httpx.get(f"http://127.0.0.1:{port}/api/researches", timeout=5)
        assert listing.status_code == 200 and listing.json() == []
    finally:
        code = stop(proc)
    assert code in (0, -signal.SIGTERM), code
    assert library.stat().st_size > 0


def test_missing_library_next_to_orphan_papers_starts_empty_and_leaves_them(tmp_path):
    """O9: a missing library next to full `papers/` starts empty and leaves the PDFs alone."""
    # O9 is a limit, not a goal: with `library.sqlite` gone and `papers/` still full of PDFs, DEIXIS starts a new,
    # empty library and does not say that files in `papers/` belong to nothing. The test pins today's behavior (the
    # orphan file is neither deleted nor changed) so a later change to it is a decision, not an accident.
    data = tmp_path / "data"
    (data / "papers").mkdir(parents=True)
    orphan = data / "papers" / f"{'a' * 64}.pdf"
    orphan.write_bytes(b"%PDF-1.4\n% an orphan that no library row points at\n")
    before = orphan.read_bytes()
    assert not (data / "library.sqlite").exists()
    proc, port = serve_until_healthy(data, tmp_path)
    try:
        listing = httpx.get(f"http://127.0.0.1:{port}/api/researches", timeout=5)
        assert listing.status_code == 200 and listing.json() == []
    finally:
        code = stop(proc)
    assert code in (0, -signal.SIGTERM), code
    assert (data / "library.sqlite").exists()
    assert orphan.read_bytes() == before
    assert sorted(p.name for p in (data / "papers").iterdir()) == [orphan.name]
