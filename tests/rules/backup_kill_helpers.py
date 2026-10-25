"""Helpers for P9 H2, F03 (kill part): SIGKILL of `deixis backup` before and after its manifest is published.

Real backup process, real restore CLI, a library made through a real server, SYNTHETIC records. Before the manifest the
folder must be refused by `restore`; after it, restore must work. The full restore comparison (every table, canonical
digests, view JSON) is B01 and belongs to H4; it is not claimed here.
"""

from __future__ import annotations

import signal
import sys

import pytest
from process_harness import BACKUP_DRIVER, child_env, create_research, harness, upload, wait_for
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


