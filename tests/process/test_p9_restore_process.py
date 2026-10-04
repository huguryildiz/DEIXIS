"""P9 H4, real processes: a library written by a newer DEIXIS (B03), a backup taken while a run is held and a writer writes
(F10), F03's restore part, and a restore killed half way.

SYNTHETIC records, a scripted model, single runs on one machine; the kills are SIGKILL on one PID, not power loss.
The B03 tests start the production launcher (`python -m deixis serve`), not the fixture driver, so they write no call log
and the `no_network` check does not apply to them; what they show is that the process exits before it binds a port. The
view-JSON part of B01 (research views, citation anchors) is the in-process test's (`tests/hardening/test_p9_restore_matrix.py`); the
tests here compare every table and every file with `p9_restore_compare`.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx
import pytest
from p9_harness import (RESTORE_DRIVER, child_env, count, create_research, discovery_to_answer_ready,  # noqa: F401
                        foreign_key_check, free_port, harness, integrity_check, port_is_free, run_row, start_run, upload,
                        wait_for, wait_run)
from deixis.__main__ import FORCED_EXIT_CODE
from p9_restore_compare import compare_states, library_state, sha256_file, tree_snapshot
from helpers import make_pdf
from test_p9_restore_matrix import CHILD, hand_backup, manifest_of
from test_p9_backup_kill import backup_folders, start_backup

pytestmark = pytest.mark.process
REPO = Path(__file__).resolve().parents[2]


def stop(server) -> None:
    server.no_network()
    server.signal(signal.SIGTERM)
    server.wait(20)


def small_library(harness, data: Path) -> None:
    server = harness.start_server(data, "library")
    rid = create_research(server.client, "attached")
    assert upload(server.client, rid, "a.pdf", make_pdf(["SYNTHETIC page one.", "SYNTHETIC page two."])).status_code == 201
    stop(server)


def rich_library(harness, data: Path) -> None:
    """Some rows of every kind a real run writes: an academic discovery and an answer (payloads, fetched PDFs, passages,
    answers) and a second research with an upload."""
    server = harness.start_server(data, "library")
    c = server.client
    rid = create_research(c, "attached_and_academic")
    discovery_to_answer_ready(c, rid)
    answer = start_run(c, rid, "answer")
    assert wait_run(c, rid, answer)["status"] == "completed"
    other = create_research(c, "attached")
    assert upload(c, other, "b.pdf", make_pdf(["SYNTHETIC b one.", "SYNTHETIC b two."])).status_code == 201
    stop(server)


def facts(folder: Path, names=("library.sqlite", "library.sqlite-wal", "library.sqlite-shm")) -> dict:
    return {n: ((folder / n).stat().st_size, sha256_file(folder / n)) if (folder / n).exists() else None for n in names}


# ---- B03 with the production launcher ------------------------------------------------------------------------------


def launch_production(harness, data: Path, tmp_path: Path, name: str) -> dict:
    port = free_port()
    env = child_env(harness.home, DEIXIS_DATA_DIR=str(data))
    log = tmp_path / f"{name}.log"
    started = time.monotonic()
    proc = harness.popen([sys.executable, "-m", "deixis", "serve", "--no-browser", "--port", str(port)], env, log)
    accepted, done = [], threading.Event()

    def poll() -> None:
        while not done.is_set():
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                accepted.append(time.monotonic())
            except OSError:
                pass
            time.sleep(0.05)

    thread = threading.Thread(target=poll, daemon=True)
    thread.start()
    try:
        code = proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        done.set()
        text = log.read_text(errors="replace")
        pytest.fail(f"the launcher was still running after 20 s (it opened the library); accepted connections: {len(accepted)}\n{text[-600:]}")
    done.set()
    thread.join(2)
    return {"code": code, "seconds": time.monotonic() - started, "accepted": accepted, "log": log.read_text(errors="replace"), "port": port}


def assert_refused_by_the_launcher(harness, data: Path, tmp_path: Path, name: str, watch: tuple[str, ...]) -> None:
    before_names, before_facts, before_tree = sorted(p.name for p in data.iterdir()), facts(data, watch), tree_snapshot(data)
    result = launch_production(harness, data, tmp_path, name)
    print(f"B03 {name}: exit {result['code']} after {result['seconds']:.2f} s; accepted connections {len(result['accepted'])};"
          f" message: {result['log'].strip().splitlines()[-1][:160]}")
    assert result["code"] == 2, result
    assert "newer DEIXIS" in result["log"] and "9999" in result["log"] and "Traceback" not in result["log"], result["log"]
    assert "Uvicorn running" not in result["log"] and "Started server process" not in result["log"]
    assert result["accepted"] == [], "something accepted a connection on the port"
    assert port_is_free(result["port"])
    assert sorted(p.name for p in data.iterdir()) == before_names
    assert facts(data, watch) == before_facts
    assert tree_snapshot(data) == before_tree


def test_b03_the_production_launcher_refuses_a_library_with_an_unknown_migration_id(harness, tmp_path):
    data = tmp_path / "data"
    small_library(harness, data)
    assert not (data / "library.sqlite-wal").exists(), "the stopped server left a -wal"
    conn = sqlite3.connect(data / "library.sqlite")
    conn.execute("INSERT INTO schema_migrations (version, name, applied_at) VALUES (9999, '9999_future.sql', 'SYNTHETIC')")
    conn.commit()
    conn.close()
    assert not (data / "library.sqlite-wal").exists() and not (data / "library.sqlite-shm").exists()
    assert_refused_by_the_launcher(harness, data, tmp_path, "main-file", ("library.sqlite",))


def test_b03_the_production_launcher_refuses_an_unknown_id_that_exists_only_in_the_wal(harness, tmp_path):
    data = tmp_path / "data"
    small_library(harness, data)
    subprocess.run([sys.executable, "-c", CHILD, str(data / "library.sqlite"), str(REPO / "backend")], check=True, timeout=60,
                   env=child_env(harness.home))
    assert (data / "library.sqlite-wal").stat().st_size > 0 and (data / "library.sqlite-shm").exists()
    with sqlite3.connect((data / "library.sqlite").resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as conn:
        assert 9999 not in {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    assert_refused_by_the_launcher(harness, data, tmp_path, "wal-only", ("library.sqlite", "library.sqlite-wal", "library.sqlite-shm"))


# ---- F10: backup while a run is held and a writer writes ------------------------------------------------------------


def backup_path(done: subprocess.CompletedProcess) -> Path:
    assert done.returncode == 0, (done.stdout, done.stderr)
    return Path(done.stdout.strip().removeprefix("Backup written to "))


def test_f10_backups_taken_while_a_run_is_held_and_a_writer_writes_restore_exactly(harness, tmp_path):
    """Three real `deixis backup` runs against a live server. Its discovery run is held in a model call (status `running` is
    checked through the API before each backup) and a thread keeps creating researches and uploading distinct PDFs. Each
    backup is the reference for its own restore (the live library keeps moving); B01's table and file comparison runs on that
    pair. Stopping the server with the call still held makes the shutdown forced (H2, F04); that is expected here."""
    data, dest = tmp_path / "live", tmp_path / "dest"
    dest.mkdir()
    server = harness.start_server(data, "live", P9_HOLD_TASK="abstract_screening")
    c = server.client
    rid = create_research(c, "attached_and_academic")
    run_id = start_run(c, rid, "discovery")
    server.wait_held("model", task="abstract_screening", run_id=run_id)

    writes, stop_writer, failures = [0], threading.Event(), []

    def writer() -> None:
        with httpx.Client(base_url=f"http://127.0.0.1:{server.port}", timeout=60) as w:
            w.headers["x-deixis-csrf"] = w.get("/api/session").json()["csrf_token"]
            while not stop_writer.is_set():
                try:
                    r = w.post("/api/researches", json={"question": f"SYNTHETIC writer question {writes[0]}", "model_connection": "codex",
                                                        "requested_model": "fixture-model", "effort": "quick", "source_scope": "attached"})
                    if r.status_code not in (200, 201):
                        failures.append(r.text)
                        return
                    pdf = make_pdf([f"SYNTHETIC writer page {uuid.uuid4()}"])
                    up = w.post(f"/api/researches/{r.json()['research']['id']}/uploads", files={"file": ("w.pdf", pdf, "application/pdf")})
                    if up.status_code != 201:
                        failures.append(up.text)
                        return
                    writes[0] += 1
                except httpx.HTTPError as error:
                    failures.append(repr(error))
                    return

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    folders, researches, writer_counts = [], [], []
    try:
        for n in range(3):
            floor = writes[0]
            wait_for(lambda: writes[0] >= floor + 3 or failures, 60, f"the writer making 3 more researches before backup {n + 1}")
            assert not failures, failures
            assert run_row(c, rid, run_id)["status"] == "running", "the discovery run must still be held, running"
            writer_counts.append(writes[0])
            started = time.monotonic()
            folder = backup_path(harness.run_cli(["backup", str(dest)], data))
            print(f"F10 backup {n + 1}: {time.monotonic() - started:.2f} s, writer had made {writer_counts[-1]} researches before it")
            assert run_row(c, rid, run_id)["status"] == "running"
            folders.append(folder)
            researches.append(count(folder, "researches"))
    finally:
        stop_writer.set()
        thread.join(30)
    assert not failures, failures
    assert researches == sorted(researches) and researches[-1] > researches[0], researches
    print(f"F10 researches in the three backups: {researches}; writer total {writes[0]}")

    compared_tables = compared_files = 0
    for n, folder in enumerate(folders):
        assert integrity_check(folder) == "ok" and foreign_key_check(folder) == []
        manifest = manifest_of(folder)
        for entry in manifest["files"]:
            assert sha256_file(folder / entry["path"]) == entry["sha256"], entry
        restored = tmp_path / f"restored-{n}"
        done = harness.run_cli(["restore", str(folder)], restored)
        assert done.returncode == 0, (done.stdout, done.stderr)
        assert integrity_check(restored) == "ok" and foreign_key_check(restored) == []
        left, right = library_state(folder), library_state(restored)
        assert compare_states(left, right) == []
        compared_tables += len(left["tables"])
        compared_files += len(left["files"])
        assert count(restored, "researches") == researches[n]
    print(f"F10 compared: {compared_tables} table comparisons ({compared_tables // 3} tables x 3), {compared_files} file hashes")

    server.signal(signal.SIGTERM)
    code = server.wait(40)
    forced = "did not finish shutting down" in server.log_text()
    print(f"F10 shutdown with the model call still held: exit {code}, {'forced' if forced else 'graceful'}")
    assert forced and code == FORCED_EXIT_CODE,(code, server.log_text()[-400:])
    server.no_network()


# ---- F03, restore part ------------------------------------------------------------------------------------------------


def test_f03_backup_killed_after_its_manifest_restores_every_table_and_file(harness, tmp_path):
    """The backup process dies after it published its manifest (H2's kill point); `restore` of that folder is compared with
    B01's table-and-file comparison, not only counts. The view-JSON part of B01 is the in-process test's."""
    data, dest = tmp_path / "data", tmp_path / "dest"
    dest.mkdir()
    rich_library(harness, data)
    proc = start_backup(harness, data, dest, "after_manifest", tmp_path)
    harness.record_descendants(proc.pid)
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=10)
    (folder,) = backup_folders(dest)
    restored = tmp_path / "restored"
    done = harness.run_cli(["restore", str(folder)], restored)
    assert done.returncode == 0, (done.stdout, done.stderr)
    left, right = library_state(folder), library_state(restored)
    diffs = compare_states(left, right)
    print(f"F03 restore part: {len(left['tables'])} tables and {len(left['files'])} files compared, differences: {diffs}; "
          f"researches {count(restored, 'researches')}")
    assert diffs == [] and len(left["files"]) >= 3
    assert integrity_check(restored) == "ok" and foreign_key_check(restored) == []
    assert left["tables"] == library_state(data)["tables"], "the backup differs from the source library the server left"


# ---- a restore killed half way --------------------------------------------------------------------------------------


def start_restore(harness, backup: Path, data: Path, mode: str, tmp_path: Path, nth: int = 1) -> subprocess.Popen:
    held = tmp_path / f"held-restore-{mode}-{nth}"
    env = child_env(harness.home, DEIXIS_DATA_DIR=str(data), P9_RESTORE_HOLD=mode, P9_RESTORE_HELD=str(held), P9_RESTORE_NTH=str(nth))
    proc = harness.popen([sys.executable, str(RESTORE_DRIVER), str(backup)], env, tmp_path / f"restore-{mode}-{nth}.log")
    wait_for(lambda: held.exists() or proc.poll() is not None, 60, f"the restore reaching {mode} {nth}")
    assert held.exists(), f"the restore driver ended with {proc.returncode} before {mode} {nth}: {(tmp_path / f'restore-{mode}-{nth}.log').read_text()[-500:]}"
    print(f"restore held at {mode} {nth}: {held.read_text()}")
    return proc


def wrong_final_files(data: Path, backup: Path) -> list[str]:
    wanted = {e["path"]: e["sha256"] for e in manifest_of(backup)["files"]}
    bad = []
    for sub in ("papers", "provider-payloads"):
        for path in sorted((data / sub).glob("*")) if (data / sub).exists() else []:
            if path.name.startswith(".restoring-") or path.name.endswith(".part"):
                continue
            if wanted.get(f"{sub}/{path.name}") != sha256_file(path):
                bad.append(f"{sub}/{path.name} ({path.stat().st_size} bytes)")
    return bad


@pytest.mark.parametrize("point", ["first_file", "middle_file", "database_copy", "database_replace"])
def test_a_restore_killed_half_way_leaves_no_half_file_and_runs_again(harness, tmp_path, point):
    """`first_file` and `middle_file` cut a file copy at half its bytes: they fail on the old code, which writes the final name
    directly (a half file there makes the next restore refuse). `database_copy` (the staging copy cut) and `database_replace`
    (stopped after a complete staging copy) were already clean on the old code, because the staging file existed there; they
    are regression guards, not failing-first."""
    backup = hand_backup(tmp_path, papers=3, payloads=2)
    files = len(manifest_of(backup)["files"]) - 1
    data = tmp_path / "data"
    if point == "database_replace":
        proc = start_restore(harness, backup, data, "db_replace", tmp_path)
    else:
        nth = {"first_file": 1, "middle_file": 3, "database_copy": files + 1}[point]
        proc = start_restore(harness, backup, data, "file_copy", tmp_path, nth)
    harness.record_descendants(proc.pid)
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=10)

    assert wrong_final_files(data, backup) == [], "a file under a final name does not match the manifest"
    assert not (data / "library.sqlite").exists()
    parts = sorted(p.name for p in data.rglob(".restoring-*.part"))
    staging = (data / "library.sqlite.restoring").exists()
    print(f"after the kill at {point}: leftover .part files {len(parts)}, staging file {staging}, "
          f"final files {sorted(p.name for p in (data / 'papers').glob('*'))}")

    done = harness.run_cli(["restore", str(backup)], data)
    assert done.returncode == 0, (done.stdout, done.stderr)
    assert not list(data.rglob(".restoring-*")) and not (data / "library.sqlite.restoring").exists()
    assert compare_states(library_state(backup), library_state(data)) == []
    assert integrity_check(data) == "ok"
