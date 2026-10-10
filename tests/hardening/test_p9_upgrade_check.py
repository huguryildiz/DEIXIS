"""P9 H4, row B02 tooling: `scripts/p9/upgrade_check.py` on SYNTHETIC folders only.

Every test replaces the default data directory with a temp path and clears DEIXIS_DATA_DIR (or sets it to another temp
path); nothing here names, computes or opens the real `~/Library/Application Support/DEIXIS`. The consent flag appears in
its own test and, in the refusal tests, to show that it relaxes nothing it must not.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

from deixis import config
from deixis.storage import db
from deixis.workflow.store import Store
from test_p9_restore_matrix import add_versions, make_source_library, migrated_library, newer_code_migrations

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "p9"))
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

    def listdir(path="."):
        seen["listed"].append(Path(path).resolve())
        return real_listdir(path)

    def scandir(path="."):
        seen["listed"].append(Path(path).resolve())
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


def test_the_self_test_passes_with_a_held_open_wal_and_with_a_clean_live_folder(capsys):
    assert uc.self_test() == 0
    out = capsys.readouterr().out
    assert "self-test wal" in out and "self-test clean" in out and "self-test: ok" in out


# ---- copy-live ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("which", ["default", "env"])
def test_copy_live_refuses_a_protected_data_directory_without_the_flag_before_reading_anything(dirs, tripwire, which):
    live, work = dirs[which], dirs["scratch"] / "work"
    with pytest.raises(uc.Refused, match="running product"):
        uc.copy_live(str(live), str(work))
    assert untouched(tripwire, live) and not work.exists()
    assert uc.main(["copy-live", str(live), str(work)]) == 2
    assert untouched(tripwire, live) and not work.exists()


def test_the_consent_flag_alone_lets_copy_live_read_a_protected_directory(dirs):
    make_source_library(dirs["default"])
    counts = uc.copy_live(str(dirs["default"]), str(dirs["scratch"] / "work"), consent=True)
    assert counts["researches"] == 1 and (dirs["scratch"] / "work" / uc.MARKER).read_text() == str(dirs["default"].resolve())
    assert uc.main(["copy-live", str(dirs["env"]), str(dirs["scratch"] / "work2"), uc.CONSENT]) == 2  # no library there: refused, not crashed


@pytest.mark.parametrize("relation", ["equal", "contains", "inside"])
@pytest.mark.parametrize("flag", [False, True])
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


def test_copy_live_refuses_a_work_dir_inside_the_products_data_directory(dirs):
    live = dirs["ordinary"]
    make_source_library(live)
    with pytest.raises(uc.Refused, match="running product"):
        uc.copy_live(str(live), str(dirs["default"] / "work"), consent=True)


def test_copy_live_refuses_a_work_dir_that_is_not_empty_before_reading_live(dirs, tripwire):
    live, work = dirs["ordinary"], dirs["scratch"] / "work"
    make_source_library(live)
    work.mkdir(parents=True)
    (work / "something").write_text("x")
    tripwire["listed"].clear()
    tripwire["sqlite"].clear()
    with pytest.raises(uc.Refused, match="not empty"):
        uc.copy_live(str(live), str(work))
    assert untouched(tripwire, live) and sorted(p.name for p in work.iterdir()) == ["something"]


def test_copy_live_reads_an_ordinary_live_folder_without_changing_it(dirs):
    live = dirs["ordinary"]
    make_source_library(live)
    (live / "codex-home").mkdir()
    (live / "codex-home" / "auth.json").write_text("SYNTHETIC")
    before = uc._tree(live)
    counts = uc.copy_live(str(live), str(dirs["scratch"] / "work"))
    assert counts["researches"] == 1 and counts["files_copied"] == 0
    assert uc._tree(live) == before
    assert sorted(p.name for p in (dirs["scratch"] / "work" / uc.COPY).iterdir()) == ["library.sqlite"]


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


def test_restore_copy_and_open_copy_refuse_a_folder_without_the_marker(dirs):
    work = dirs["scratch"] / "work"
    make_source_library(work / uc.RESTORED)
    with pytest.raises(uc.Refused, match="not a copy made by copy-live"):
        uc.restore_copy(str(work))
    with pytest.raises(uc.Refused, match="not a copy made by copy-live"):
        uc.open_copy(str(work))


def test_open_copy_refuses_a_folder_without_a_restored_library(dirs):
    work = staged(dirs, restored=False)
    with pytest.raises(uc.Refused, match="no restored folder"):
        uc.open_copy(str(work))


@pytest.mark.parametrize("flag", [False, True])
@pytest.mark.parametrize("where", ["default", "env", "marker_live"])
def test_open_copy_refuses_the_products_directories_and_the_marked_live_folder_even_with_the_flag(dirs, tripwire, where, flag):
    live = dirs["ordinary"]
    base = {"default": dirs["default"], "env": dirs["env"], "marker_live": live}[where] / "work"
    work = staged(dirs, base, live=live)
    tripwire["sqlite"].clear()
    argv = ["open-copy", str(work)] + ([uc.CONSENT] if flag else [])
    assert uc.main(argv) == 2
    assert tripwire["sqlite"] == [], "SQLite was opened before the refusal"


def test_open_copy_counts_before_and_after_are_equal_and_a_pending_migration_is_applied_and_reported(dirs, monkeypatch):
    """A restored library written by earlier code (today's migrations, opened by a code with one more SYNTHETIC
    migration): opening applies exactly that one and loses nothing."""
    packaged = sorted(db.packaged_versions())
    newer, pending = newer_code_migrations(dirs["scratch"])
    work = staged(dirs, restored=False)
    target = work / uc.RESTORED / "library.sqlite"
    conn = db.connect(target)
    db.migrate(conn)
    Store(conn).create_research("SYNTHETIC question", "attached", "quick", [], "fake", "fake-model", "en")
    conn.close()
    monkeypatch.setattr(db, "MIGRATIONS_DIR", newer)
    result = uc.open_copy(str(work))
    assert result["applied_before"] == uc.compact(packaged) and result["pending"] == str(pending)
    assert result["applied_after"] == f"1-{pending}"
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


def test_importing_the_script_has_no_side_effects_on_the_environment():
    """The model keys and the keyring are touched in main(), not at import: re-importing leaves a set key in place."""
    import importlib

    os.environ["GEMINI_API_KEY"] = "SYNTHETIC-not-a-key"
    try:
        importlib.reload(uc)
        assert os.environ["GEMINI_API_KEY"] == "SYNTHETIC-not-a-key"
    finally:
        os.environ.pop("GEMINI_API_KEY", None)


def test_main_without_a_command_prints_usage_and_returns_2(capsys):
    assert uc.main([]) == 2
