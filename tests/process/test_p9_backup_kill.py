"""P9 H2, F03 (kill part): SIGKILL of `deixis backup` before and after its manifest is published.

Real backup process, real restore CLI, a library made through a real server, SYNTHETIC records. Before the manifest the
folder must be refused by `restore`; after it, restore must work. The full restore comparison (every table, canonical
digests, view JSON) is B01 and belongs to H4; it is not claimed here.
"""

from __future__ import annotations

import json
import os
import signal
import sys

import pytest
from p9_harness import (BACKUP_DRIVER, child_env, count, create_research, harness, integrity_check, papers_files,  # noqa: F401
                        sha256_file, upload, wait_for)
from helpers import make_pdf

pytestmark = pytest.mark.process


def make_library(harness, data):
    server = harness.start_server(data, "library")
    rid = create_research(server.client, "attached")
    assert upload(server.client, rid, "a.pdf", make_pdf(["SYNTHETIC page one.", "SYNTHETIC page two."])).status_code == 201
    server.no_network()
    server.signal(signal.SIGTERM)
    server.wait(20)
    return rid


def start_backup(harness, data, dest, mode, tmp_path):
    held = tmp_path / f"held-{mode}"
    env = child_env(harness.home, DEIXIS_DATA_DIR=str(data), P9_BACKUP_HOLD=mode, P9_BACKUP_HELD=str(held))
    proc = harness.popen([sys.executable, str(BACKUP_DRIVER), str(dest)], env, tmp_path / f"backup-{mode}.log")
    wait_for(lambda: held.exists() or proc.poll() is not None, 60, f"the backup reaching {mode}")
    assert held.exists(), f"the backup driver ended with {proc.returncode} before {mode}"
    return proc


def backup_folders(dest):
    return sorted(p for p in dest.iterdir() if p.name.startswith("deixis-backup-"))


@pytest.mark.parametrize("mode", ["during_files", "before_manifest"])
def test_f03_kill_before_the_manifest(harness, tmp_path, mode):
    data, dest = tmp_path / "data", tmp_path / "dest"
    dest.mkdir()
    make_library(harness, data)
    proc = start_backup(harness, data, dest, mode, tmp_path)
    harness.record_descendants(proc.pid)
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=10)
    (folder,) = backup_folders(dest)
    assert not (folder / "manifest.json").exists() and not (folder / "manifest.json.partial").exists()
    print(f"F03 {mode}: folder holds", sorted(p.name for p in folder.rglob("*")))

    empty = tmp_path / "restore-refused"
    done = harness.run_cli(["restore", str(folder)], empty)
    assert done.returncode == 1, (done.returncode, done.stdout, done.stderr)
    assert "not a complete DEIXIS backup" in done.stderr, done.stderr
    left = sorted(p.name for p in empty.rglob("*")) if empty.exists() else []
    assert left == [], left  # no library.sqlite, no .restoring, nothing

    # A new backup into the same destination works and restores.
    again = harness.run_cli(["backup", str(dest)], data)
    assert again.returncode == 0, again.stderr
    complete = [p for p in backup_folders(dest) if (p / "manifest.json").exists()]
    assert len(complete) == 1 and complete[0] != folder
    restored = tmp_path / "restore-ok"
    done = harness.run_cli(["restore", str(complete[0])], restored)
    assert done.returncode == 0, (done.stdout, done.stderr)
    assert integrity_check(restored) == "ok" and count(restored, "researches") == count(data, "researches")


def test_f03_kill_after_the_manifest(harness, tmp_path):
    data, dest = tmp_path / "data", tmp_path / "dest"
    dest.mkdir()
    make_library(harness, data)
    proc = start_backup(harness, data, dest, "after_manifest", tmp_path)
    harness.record_descendants(proc.pid)
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=10)
    (folder,) = backup_folders(dest)
    manifest = json.loads((folder / "manifest.json").read_text())
    for entry in manifest["files"]:
        assert (folder / entry["path"]).is_file() and sha256_file(folder / entry["path"]) == entry["sha256"], entry
    assert {e["path"].split("/")[0] for e in manifest["files"]} >= {"library.sqlite", "papers"}

    restored = tmp_path / "restore-ok"
    done = harness.run_cli(["restore", str(folder)], restored)
    assert done.returncode == 0, (done.stdout, done.stderr)
    assert integrity_check(restored) == "ok"
    assert count(restored, "researches") == count(data, "researches") == 1
    assert [p.name for p in papers_files(restored)] == [p.name for p in papers_files(data)]
    print("F03 after_manifest:", done.stdout.strip().replace(str(restored), "<dir>"))
