"""P9 H4, row B02 tooling: `scripts/release_checks/upgrade_check.py` on SYNTHETIC folders only.

Every test replaces the default data directory with a temp path and clears DEIXIS_DATA_DIR (or sets it to another temp
path); nothing here names, computes or opens the real `~/Library/Application Support/DEIXIS`. The consent flag appears in
its own test and, in the refusal tests, to show that it relaxes nothing it must not.
"""

from __future__ import annotations

import fcntl
import os
import sqlite3
import sys
from pathlib import Path

import pytest

from deixis import config
from deixis.storage import db, upgrades
from deixis.workflow.run.store import Store
from test_restore_matrix import add_versions, make_source_library, newer_code_steps

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "release_checks"))
import upgrade_check as uc  # noqa: E402


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    """A pretend default data directory and a pretend DEIXIS_DATA_DIR folder, both temp paths, plus a separate place to work."""
    default, env = tmp_path / "pretend-default", tmp_path / "pretend-env"
    default.mkdir()
    env.mkdir()
    monkeypatch.setattr(config, "default_data_dir", lambda: default)
    monkeypatch.setenv("DEIXIS_DATA_DIR", str(env))
    return {"default": default, "env": env, "ordinary": tmp_path / "ordinary-live", "scratch": tmp_path / "scratch"}


@pytest.fixture
def tripwire(monkeypatch):
    """Records every directory listing of a path and every SQLite open; the refusal tests assert both stayed empty for LIVE_DIR."""
    seen = {"listed": [], "sqlite": []}
    real_listdir, real_scandir, real_connect = os.listdir, os.scandir, sqlite3.connect

    def record(path):
        # shutil.rmtree (pytest's tmp_path teardown among others) lists a folder through its file descriptor: record the
        # folder the descriptor names, so such a listing is still seen.
        if isinstance(path, int):
            path = os.fsdecode(fcntl.fcntl(path, fcntl.F_GETPATH, bytes(1024)).split(b"\0", 1)[0]) if hasattr(fcntl, "F_GETPATH") else os.readlink(f"/proc/self/fd/{path}")
        seen["listed"].append(Path(path).resolve())

    def listdir(path="."):
        record(path)
        return real_listdir(path)

    def scandir(path="."):
        record(path)
        return real_scandir(path)

    def connect(*args, **kwargs):
        seen["sqlite"].append(args[0])
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(os, "listdir", listdir)
    monkeypatch.setattr(os, "scandir", scandir)
    monkeypatch.setattr(uc.sqlite3, "connect", connect)
    return seen


def untouched(seen, live: Path) -> bool:
    return not [p for p in seen["listed"] if uc.inside(p, live.resolve())] and seen["sqlite"] == []


# ---- copy-live ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("which", ["default"])
def test_copy_live_refuses_a_protected_data_directory_without_the_flag_before_reading_anything(dirs, tripwire, which):
    live, work = dirs[which], dirs["scratch"] / "work"
    with pytest.raises(uc.Refused, match="running product"):
        uc.copy_live(str(live), str(work))
    assert untouched(tripwire, live) and not work.exists()
    assert uc.main(["copy-live", str(live), str(work)]) == 2
    assert untouched(tripwire, live) and not work.exists()


@pytest.mark.parametrize("relation", ["equal"])
@pytest.mark.parametrize("flag", [False])
def test_copy_live_never_accepts_a_work_dir_that_equals_contains_or_is_inside_live(dirs, tripwire, relation, flag):
    live = dirs["ordinary"]
    make_source_library(live)
    work = {"equal": live, "contains": live.parent, "inside": live / "work"}[relation]
    before = sorted(p.relative_to(live).as_posix() for p in live.rglob("*"))
    tripwire["listed"].clear()
    tripwire["sqlite"].clear()
    with pytest.raises(uc.Refused, match="never allowed"):
        uc.copy_live(str(live), str(work), consent=flag)
    assert untouched(tripwire, live)
    assert sorted(p.relative_to(live).as_posix() for p in live.rglob("*")) == before


# ---- restore-copy and open-copy ----------------------------------------------------------------------------------------


def staged(dirs, base: Path | None = None, restored: bool = True, live: Path | None = None) -> Path:
    """A work folder holding the marker and, when asked, a restored library."""
    work = base or dirs["scratch"] / "work"
    work.mkdir(parents=True, exist_ok=True)
    live = live or dirs["ordinary"]
    if not live.exists():
        make_source_library(live)  # The marker's source must be listable for the identity guard.
    (work / uc.MARKER).write_text(str(live), encoding="utf-8")
    if restored:
        make_source_library(work / uc.RESTORED)
    return work


def test_open_copy_counts_before_and_after_are_equal_and_a_pending_migration_is_applied_and_reported(dirs, monkeypatch):
    """A restored library written by earlier code (today's migrations, opened by a code with one more SYNTHETIC
    migration): opening applies exactly that one and loses nothing."""
    packaged = sorted(db.packaged_versions())
    newer, pending = newer_code_steps()
    work = staged(dirs, restored=False)
    target = work / uc.RESTORED / "library.sqlite"
    conn = db.connect(target)
    db.migrate(conn)
    Store(conn).create_research("SYNTHETIC question", "attached", "quick", [], "fake", "fake-model", "en")
    conn.close()
    monkeypatch.setattr(upgrades, "STEPS", newer)
    result = uc.open_copy(str(work))
    assert result["applied_before"] == uc.compact(packaged) and result["pending"] == str(pending)
    assert result["applied_after"] == uc.compact([*packaged, pending])  # numbers may have gaps (0009 is free, D27)
    assert result["applied_by_open"] == 1 and result["unknown"] == "none"
    assert result["sql_before"] == result["sql_after"] and result["sql_before"]["researches"] == 1


def test_open_copy_refuses_a_restored_library_written_by_a_newer_version_with_the_message(dirs, capsys):
    work = staged(dirs)
    add_versions(work / uc.RESTORED / "library.sqlite", 9999)
    assert uc.main(["open-copy", str(work)]) == 1
    assert "newer DEIXIS" in capsys.readouterr().err


def test_open_copy_blocks_every_request_and_starts_no_worker(dirs):
    work = staged(dirs)
    result = uc.open_copy(str(work))
    assert result["applied_by_open"] == 0 and result["views"]["GET /api/researches"] == 1
    assert result["worker_started"] is False and result["outbound_requests"] == 0


