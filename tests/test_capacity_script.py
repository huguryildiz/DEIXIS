"""P9 H5: the capacity script's frozen table, verdicts, guards, generator and limits table (no server, no Chrome).

The frozen values below are an independent copy of D166's table (frozen 2 October 2026, before any measurement). A change
to `capacity.FROZEN` that is not a change to this copy fails here, which is the point.
"""

import importlib.util
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import pymupdf
import pytest

from deixis.storage import db
from deixis.workflow.store import Store
from deixis.workflow.views import research_view

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("capacity", REPO / "scripts" / "p9" / "capacity.py")
capacity = importlib.util.module_from_spec(_spec)
sys.modules["capacity"] = capacity
_spec.loader.exec_module(capacity)

# (class, [(metric, points, limit, strict)]) per row id.
EXPECTED_ROWS = {
    "K01a": ("mandatory", [("ui_ready_s", [1000], 2.0, False), ("first_api_s", [1000], 2.0, False)]),
    "K01b": ("mandatory", [("ui_ready_s", [5000], 10.0, False), ("first_api_s", [5000], 10.0, False)]),
    "K01c": ("measure only", [("ui_ready_s", [100, 7769], None, False), ("first_api_s", [100, 7769], None, False)]),
    "K01d": ("measure only", [("ui_ready_ok", [10000], None, False), ("ui_ready_s", [10000], None, False)]),
    "K02a": ("mandatory", [("health_max_s", [1000], 0.5, False)]),
    "K02b": ("mandatory", [("health_max_s", [5000], 1.0, False)]),
    "K02c": ("measure only", [("health_max_s", [100, 7769, 10000], None, False),
                              ("two_tab_health_max_s", [5000], None, False)]),
    "K03a": ("mandatory", [("rss_peak_bytes", [100, 1000, 5000, 7769, "pdf"], 2_000_000_000, True)]),
    "K03b": ("measure only", [(m, [100, 1000, 5000, 7769, 10000], None, False) for m in ("db_bytes", "wal_bytes", "data_dir_bytes")]),
    "K03c": ("measure only", [("rss_peak_bytes", [10000, "control"], None, False)]),
    "K04a": ("measure only", [("quickfind_s", [1000, 5000, 10000], None, False), ("search_api_s", [1000, 5000, 10000], None, False)]),
    "K04b": ("measure only", [("sources_first_paint_s", [1000, 5000, 10000], None, False)]),
    "K04c": ("measure only", [("passage_pdf_text_s", [1000, 5000, 10000], None, False),
                              ("passage_abstract_s", [1000, 5000, 10000], None, False)]),
    "K05": ("measure only", [("pdf_first_page_s", ["pdf"], None, False), ("pdf_jump_s", ["pdf"], None, False)]),
    "K06a": ("mandatory", [("backup_s", [5000], 120.0, False), ("backup_failed", [5000], 0, False)]),
    "K06b": ("measure only", [("backup_bytes", [5000, "pdf"], None, False), ("backup_s", [1000, 10000, "pdf"], None, False),
                              ("backup_running_s", [1000, 5000, 10000], None, False),
                              ("backup_running_health_max_s", [1000, 5000, 10000], None, False)]),
    "K07": ("mandatory", []),
}


def test_the_frozen_table_equals_the_one_written_before_the_measurement():
    frozen = capacity.FROZEN
    assert frozen["frozen_on"] == "2026-10-02"
    assert frozen["points"] == [100, 1000, 5000, 7769, 10000]
    assert frozen["repetitions"] == 3
    got = {rid: (row["class"], [(m["name"], m["points"], m["limit"], m["strict"]) for m in row["metrics"]])
           for rid, row in frozen["rows"].items()}
    assert got == EXPECTED_ROWS


def results(**by_point):
    return {str(point): metrics for point, metrics in by_point.items()}


def test_judge_uses_the_worst_repetition_and_a_value_on_the_threshold_passes():
    row = capacity.FROZEN["rows"]["K01a"]
    on = {"ui_ready_s": [1.0, 2.0, 1.5], "first_api_s": [0.5, 0.6, 0.7]}
    assert capacity.judge(row, {"1000": on})["verdict"] == "pass"
    over = {"ui_ready_s": [0.1, 0.1, 2.0001], "first_api_s": [0.5, 0.6, 0.7]}  # one bad repetition decides
    assert capacity.judge(row, {"1000": over})["verdict"] == "fail"
    assert capacity.judge(row, {"1000": over})["metrics"]["ui_ready_s"]["1000"]["worst"] == 2.0001
    api = {"ui_ready_s": [1.0, 1.0, 1.0], "first_api_s": [0.1, 2.5, 0.1]}  # the second metric of the row counts too
    assert capacity.judge(row, {"1000": api})["verdict"] == "fail"


def test_a_strict_threshold_fails_on_equality_and_a_missing_repetition_is_incomplete_not_pass():
    rss = capacity.FROZEN["rows"]["K03a"]
    points = ("100", "1000", "5000", "7769", "pdf")
    below = {p: {"rss_peak_bytes": [1_999_999_999, 5, 5]} for p in points}
    assert capacity.judge(rss, below)["verdict"] == "pass"
    equal = {p: {"rss_peak_bytes": [2_000_000_000, 5, 5]} for p in points}
    assert capacity.judge(rss, equal)["verdict"] == "fail"
    short = dict(below, **{"100": {"rss_peak_bytes": [5, 5]}})
    assert capacity.judge(rss, short)["verdict"] == "incomplete"
    gap = dict(below, **{"100": {"rss_peak_bytes": [5, None, 5]}})
    assert capacity.judge(rss, gap)["verdict"] == "incomplete"
    no_point = {p: v for p, v in below.items() if p != "pdf"}
    assert capacity.judge(rss, no_point)["verdict"] == "incomplete"
    # a breach already seen cannot be rescued by the repetition that is missing
    assert capacity.judge(rss, dict(below, **{"100": {"rss_peak_bytes": [2_000_000_001]}}))["verdict"] == "fail"


def test_a_measure_only_row_is_measured_and_never_fails():
    row = capacity.FROZEN["rows"]["K01c"]
    huge = {"ui_ready_s": [999.0, 999.0, 999.0], "first_api_s": [999.0, 999.0, 999.0]}
    assert capacity.judge(row, {"100": huge, "7769": huge})["verdict"] == "measured"
    assert capacity.judge(row, {"100": huge})["verdict"] == "incomplete"  # a point is missing
    assert capacity.judge(row, {})["verdict"] == "incomplete"


def test_the_verdict_set_is_exactly_pass_fail_incomplete_measured():
    assert capacity.VERDICTS == ("pass", "fail", "incomplete", "measured")
    seen = set()
    for rid, row in capacity.FROZEN["rows"].items():
        if rid == "K07":
            continue
        ok = {str(p): {m["name"]: [1, 1, 1] for m in row["metrics"] if p in m["points"]} for m in row["metrics"] for p in m["points"]}
        seen |= {capacity.judge(row, ok)["verdict"], capacity.judge(row, {})["verdict"]}
    seen.add(capacity.judge(capacity.FROZEN["rows"]["K02a"], {"1000": {"health_max_s": [9, 9, 9]}})["verdict"])
    seen.add(capacity.judge_limits([])["verdict"])
    assert seen <= set(capacity.VERDICTS) and {"pass", "fail", "incomplete", "measured"} <= seen


def test_the_backup_row_fails_on_a_failed_backup_even_when_it_is_fast():
    row = capacity.FROZEN["rows"]["K06a"]
    assert capacity.judge(row, {"5000": {"backup_s": [3, 3, 3], "backup_failed": [0, 0, 0]}})["verdict"] == "pass"
    assert capacity.judge(row, {"5000": {"backup_s": [3, 3, 3], "backup_failed": [0, 1, 0]}})["verdict"] == "fail"
    assert capacity.judge(row, {"5000": {"backup_s": [3, 3, 120.5], "backup_failed": [0, 0, 0]}})["verdict"] == "fail"


def test_the_control_point_has_one_repetition_and_every_other_point_three():
    assert [capacity.repetitions_for(p) for p in (100, "1000", "pdf", "control")] == [3, 3, 3, 1]
    row = capacity.FROZEN["rows"]["K03c"]
    three = [1, 2, 3]
    assert capacity.judge(row, {"10000": {"rss_peak_bytes": three}, "control": {"rss_peak_bytes": [7]}})["verdict"] == "measured"
    assert capacity.judge(row, {"10000": {"rss_peak_bytes": three}, "control": {"rss_peak_bytes": [None]}})["verdict"] == "incomplete"
    assert capacity.judge(row, {"10000": {"rss_peak_bytes": three}})["verdict"] == "incomplete"  # the control point is missing
    assert capacity.judge(row, {"10000": {"rss_peak_bytes": [1]}, "control": {"rss_peak_bytes": [7]}})["verdict"] == "incomplete"
    k02c = capacity.FROZEN["rows"]["K02c"]  # no control point in K02c: its health numbers stay in the control's raw file
    assert all("control" not in m["points"] for m in k02c["metrics"])
    full = {str(p): {"health_max_s": three} for p in (100, 7769, 10000)} | {"5000": {"two_tab_health_max_s": three}}
    assert capacity.judge(k02c, full)["verdict"] == "measured"


def test_a_harness_failure_of_the_k01_step_stays_incomplete_and_never_yields_a_pass():
    broken = {"ok": False, "seconds": 0.2, "error": "locator.click: strict mode violation", "page_ms": 5}  # not a timeout
    fields, errors = capacity.k01_fields(broken)
    assert fields["ui_ready_s"] is None and fields["ui_ready_ok"] is None and fields["ui_ready_page_ms"] is None
    assert errors and "strict mode" in errors[0]
    none_fields = capacity.k01_fields(None)
    assert none_fields[0]["ui_ready_s"] is None and none_fields[0]["ui_ready_ok"] is None and none_fields[1]
    for rid, point, api in (("K01a", "1000", 0.1), ("K01b", "5000", 0.1)):
        row = capacity.FROZEN["rows"][rid]
        bad = {"ui_ready_s": [fields["ui_ready_s"]] * 3, "first_api_s": [api] * 3}
        assert capacity.judge(row, {point: bad})["verdict"] == "incomplete"
        mixed = {"ui_ready_s": [0.5, fields["ui_ready_s"], 0.5], "first_api_s": [api] * 3}  # one failed repetition of three
        assert capacity.judge(row, {point: mixed})["verdict"] == "incomplete"
        good = capacity.k01_fields({"ok": True, "seconds": 0.5, "page_ms": 500.0})[0]
        assert good == {"ui_ready_s": 0.5, "ui_ready_ok": 1, "ui_ready_timeout": 0, "ui_ready_page_ms": 500.0, "ui_ready_elapsed_s": 0.5}
        assert capacity.judge(row, {point: {"ui_ready_s": [0.5] * 3, "first_api_s": [api] * 3}})["verdict"] == "pass"
    k01d = capacity.FROZEN["rows"]["K01d"]  # a harness failure at N=10,000 is incomplete, not "does not work"
    assert capacity.judge(k01d, {"10000": {"ui_ready_ok": [fields["ui_ready_ok"]] * 3, "ui_ready_s": [None] * 3}})["verdict"] == "incomplete"


def test_a_readiness_timeout_is_a_measured_breach_not_a_harness_error():
    timed_out = {"ok": False, "seconds": 120.4, "timeout": True, "page_ms": None, "readiness": {"title_ok": True, "tab_count_ok": False},
                 "error": "page.waitForFunction: Timeout 120000ms exceeded.; title aria-label visible: true; tab count equal: false"}
    fields, errors = capacity.k01_fields(timed_out)
    assert errors == []  # nothing broke: the screen was simply not ready
    assert fields["ui_ready_timeout"] == 1 and fields["ui_ready_ok"] == 0 and fields["ui_ready_s"] == 120.0
    assert fields["ui_ready_elapsed_s"] == 120.4 and fields["ui_ready_readiness"] == {"title_ok": True, "tab_count_ok": False}
    assert capacity.k01_fields({"ok": False, "seconds": 120.1, "error": "page.goto: Timeout 120000ms exceeded."})[0]["ui_ready_timeout"] == 1  # by text too
    for rid, point in (("K01a", "1000"), ("K01b", "5000")):  # 120 s exceeds both limits: the mandatory row fails
        timed = {"ui_ready_s": [fields["ui_ready_s"]] * 3, "first_api_s": [0.1] * 3}
        assert capacity.judge(capacity.FROZEN["rows"][rid], {point: timed})["verdict"] == "fail"
        one = {"ui_ready_s": [0.5, fields["ui_ready_s"], 0.5], "first_api_s": [0.1] * 3}
        assert capacity.judge(capacity.FROZEN["rows"][rid], {point: one})["verdict"] == "fail"
    # N=10,000: works / does not work is measured with value 0, never incomplete
    k01d = capacity.judge(capacity.FROZEN["rows"]["K01d"], {"10000": {"ui_ready_ok": [0, 0, 0], "ui_ready_s": [120.0] * 3}})
    assert k01d["verdict"] == "measured" and k01d["metrics"]["ui_ready_ok"]["10000"]["worst"] == 0


def test_the_worst_ok_flag_is_the_minimum_and_the_worst_time_is_the_maximum():
    row = capacity.FROZEN["rows"]["K01d"]
    mixed = capacity.judge(row, {"10000": {"ui_ready_ok": [1, 0, 1], "ui_ready_s": [5.0, 120.0, 9.0]}})
    assert mixed["metrics"]["ui_ready_ok"]["10000"]["worst"] == 0 and mixed["pooled"]["ui_ready_ok"]["worst"] == 0
    assert mixed["metrics"]["ui_ready_s"]["10000"]["worst"] == 120.0
    assert capacity.judge(row, {"10000": {"ui_ready_ok": [1, 1, 1], "ui_ready_s": [5.0, 6.0, 9.0]}})["metrics"]["ui_ready_ok"]["10000"]["worst"] == 1


def test_a_screen_that_became_ready_after_120_s_is_not_ok():
    fields, errors = capacity.k01_fields({"ok": True, "seconds": 120.5, "page_ms": 1.0})
    assert fields["ui_ready_ok"] == 0 and fields["ui_ready_s"] == 120.5 and errors
    assert capacity.k01_fields({"ok": True, "seconds": 120.0, "page_ms": 1.0})[0]["ui_ready_ok"] == 1


def test_a_repetition_is_under_parallel_load_when_it_started_or_ended_at_load_4_or_more():
    assert not capacity.is_loaded({"load1": 3.99, "load1_end": 3.5}) and not capacity.is_loaded({})
    assert capacity.is_loaded({"load1": 4.0, "load1_end": 0.5})
    assert capacity.is_loaded({"load1": 0.5, "load1_end": 4.2})  # the first repetition was quiet, a later one was not
    assert capacity.is_loaded({"load1": 1.0, "load1_end": 9.0})


def test_summarize_labels_the_result_by_any_repetition_and_merges_folders_by_point_name(tmp_path):
    def rec(point, rep, **extra):
        return {"point": point, "rep": rep, "started_epoch": float(rep), "errors": [], "load1": 0.5, "load1_end": 0.5, "rss_workload_complete": True, **extra}

    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    for rep in (1, 2, 3):
        (a / f"5000-rep{rep}.json").write_text(__import__("json").dumps(rec("5000", rep, rss_peak_bytes=100 * rep, load1_end=6.0 if rep == 3 else 0.5)))
        (b / f"pdf-rep{rep}.json").write_text(__import__("json").dumps(rec("pdf", rep, rss_peak_bytes=7 * rep)))
    (b / "control-rep1.json").write_text(__import__("json").dumps(rec("control", 1, rss_peak_bytes=9)))
    assert set(capacity.load_reps(a)) == {"5000"}
    assert set(capacity.load_reps(a, [b])) == {"5000", "pdf", "control"}
    summary = capacity.summarize(a, [b])
    assert summary["under_parallel_load"] is True  # only the third repetition ended at load 6
    assert [x["load_high"] for x in summary["loads"] if x["point"] == "5000"] == [False, False, True]
    k03a = summary["rows"]["K03a"]["metrics"]["rss_peak_bytes"]
    assert k03a["pdf"]["worst"] == 21 and k03a["5000"]["worst"] == 300  # K03a reads the pdf point of the other folder
    assert summary["rows"]["K03c"]["metrics"]["rss_peak_bytes"]["control"]["worst"] == 9
    assert (a / "summary.json").exists() and not (b / "summary.json").exists()


# ---- guards --------------------------------------------------------------------------------------------------------------


def test_directories_must_sit_in_an_h5_folder_directly_under_a_temp_root(tmp_path):
    root = Path(tempfile.mkdtemp(prefix="h5-"))
    link = Path(tempfile.gettempdir()) / f"h5-link-{os.getpid()}"
    try:
        assert capacity.guard_dir(root) == Path(os.path.realpath(root))
        assert capacity.guard_dir(root / "n100" / "deeper") == Path(os.path.realpath(root)) / "n100" / "deeper"
        with pytest.raises(capacity.GuardError):
            capacity.guard_dir(tmp_path)  # pytest's temp dir is not an h5-* folder
        with pytest.raises(capacity.GuardError):
            capacity.guard_dir(Path(tempfile.gettempdir()) / "somewhere" / "h5-late")  # h5- only later in the path
        with pytest.raises(capacity.GuardError):
            capacity.guard_dir(Path(tempfile.gettempdir()) / "not-h5-lib")
        with pytest.raises(capacity.GuardError):
            capacity.guard_dir(Path(tempfile.gettempdir()) / "h5x" / "lib")  # the folder name starts with h5x, not h5-
        with pytest.raises(capacity.GuardError):
            capacity.guard_dir(Path.home() / "Library" / "Application Support" / "DEIXIS")
        os.symlink(tmp_path, link)  # an h5-* name that resolves outside is refused
        with pytest.raises(capacity.GuardError):
            capacity.guard_dir(link / "lib")
    finally:
        link.unlink(missing_ok=True)
        shutil.rmtree(root, ignore_errors=True)


def test_only_ports_8900_to_8920_are_allowed():
    assert capacity.guard_port(8900) == 8900 and capacity.guard_port(8920) == 8920
    for port in (8765, 8860, 8858, 8864, 8899, 8921, 0, 5178):
        with pytest.raises(capacity.GuardError):
            capacity.guard_port(port)


def test_raw_output_must_stay_under_the_p9_h5_folder_and_a_repository_env_is_refused(tmp_path):
    assert capacity.guard_out(REPO / ".local" / "p9-h5" / "x") == Path(os.path.realpath(REPO / ".local" / "p9-h5" / "x"))
    for outside in (REPO / ".local" / "other", REPO / "docs", tmp_path):
        with pytest.raises(capacity.GuardError):
            capacity.guard_out(outside)
    capacity.guard_repo(tmp_path)
    (tmp_path / ".env").write_text("X=1")
    with pytest.raises(capacity.GuardError):
        capacity.guard_repo(tmp_path)


def test_the_child_environment_is_an_allowlist(tmp_path):
    env = capacity.child_env(tmp_path / "home", tmp_path / "data")
    assert set(env) == {"PATH", "HOME", "PYTHONPATH", "PYTHON_KEYRING_BACKEND", "DEIXIS_DATA_DIR"}
    assert env["PYTHON_KEYRING_BACKEND"] == "keyring.backends.null.Keyring"
    assert not any(shutil.which(name, path=env["PATH"]) for name in ("codex", "claude", "gemini"))


# ---- generator -----------------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def library():
    root = Path(tempfile.mkdtemp(prefix="h5-"))
    info = capacity.generate_point(root, 100)
    yield root, info
    shutil.rmtree(root, ignore_errors=True)


def test_the_generated_library_has_the_stated_shape(library):
    root, info = library
    data_dir = root / "n100"
    conn = sqlite3.connect(f"file:{data_dir / 'library.sqlite'}?immutable=1", uri=True)
    rid = info["research_id"]
    one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
    assert one("SELECT COUNT(*) FROM researches") == 5  # one big research and four small ones
    assert one("SELECT COUNT(*) FROM candidates WHERE research_id = ?", rid) == 100
    assert one("SELECT COUNT(*) FROM corpus_memberships WHERE research_id = ?", rid) == 100 + 100 // 10
    assert one("SELECT COUNT(*) FROM works") == 100 + 48  # four small researches own 12 separate works each
    assert one("SELECT COUNT(*) FROM search_runs WHERE research_id = ?", rid) == 20
    assert one("SELECT SUM(result_count) FROM search_runs WHERE research_id = ?", rid) == 100
    mix = dict(conn.execute("SELECT s.state, COUNT(*) FROM candidates c JOIN selections s"
                            " ON s.research_id = c.research_id AND s.source_version_id = c.source_version_id"
                            " WHERE c.research_id = ? GROUP BY s.state", (rid,)).fetchall())
    assert mix == {"included": 15, "excluded": 55, "pending": 30}
    stats = info["counts"]  # both selection counts are named: every selection row (other versions are pending) and the candidates' own mix
    assert stats["research_selections"] == {"included": 15, "excluded": 55, "pending": 40}
    assert stats["research_candidate_selections"] == mix == {"included": 15, "excluded": 55, "pending": 30}
    assert set(info["selection_keys"]) == {"research_selections", "research_candidate_selections"}
    assert one("SELECT COUNT(*) FROM works WHERE source_key IS NULL") == 0
    assert one("SELECT COUNT(DISTINCT work_id) FROM source_versions WHERE title LIKE '%alpha%'") == 3  # works 0, 40, 80 of 40 topic words
    assert one("SELECT COUNT(*) FROM researches WHERE title LIKE '%alpha%'") == 0
    assert one("SELECT COUNT(*) FROM source_versions WHERE authors_json LIKE '%alpha%'") == 0
    assets = conn.execute("SELECT sha256, byte_size, storage_path, page_count FROM source_assets").fetchall()
    assert len(assets) == 1 and info["pdf_files"] == 1  # every 10th included work: 15 included -> the 10th
    for sha, size, storage_path, pages in assets:
        stored = data_dir / "papers" / storage_path
        assert storage_path == f"{sha}.pdf" and stored.stat().st_size == size
        import hashlib
        assert hashlib.sha256(stored.read_bytes()).hexdigest() == sha
        with pymupdf.open(stored) as pdf_file:
            assert pdf_file.page_count == pages == 6 and "SYNTHETIC capacity PDF" in pdf_file[0].get_text()
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()
    assert not (data_dir / "library.sqlite-wal").exists() and not (data_dir / "library.sqlite-shm").exists()


def test_the_library_has_nothing_a_server_start_could_run(library):
    root, info = library
    assert capacity.ready_problems(root / "n100") == []
    stats = info["counts"]
    assert set(stats["runs_by_status"]) == {"completed"} and stats["model_sessions"] == 0 and stats["person_pdf_requests"] == 0


def test_the_library_opens_through_the_research_view_and_quick_find(library):
    root, info = library
    copy = root / "open-check"
    shutil.copytree(root / "n100", copy)
    conn = db.connect(copy / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    view = research_view(store, info["research_id"])
    assert len(view["sources"]) == 110
    assert capacity.heading_label(view) == info["label"]  # the title's aria-label follows ResearchView.tsx's rule
    found = store.quick_search("alpha")
    assert found["sources"] and all("alpha" in s["title"] for s in found["sources"]) and not found["researches"]
    conn.close()


def test_a_run_queued_in_the_wal_is_seen_and_a_non_empty_wal_is_refused(library, tmp_path):
    root, _ = library
    live = root / "wal-live"
    shutil.copytree(root / "n100", live)
    writer = sqlite3.connect(live / "library.sqlite")  # stays open, so its commit stays in the -wal
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("UPDATE runs SET status = 'queued' WHERE id = (SELECT id FROM runs LIMIT 1)")
    writer.commit()
    copy = root / "wal-copy"
    copy.mkdir()
    try:
        assert (live / "library.sqlite-wal").stat().st_size > 0
        for name in ("library.sqlite", "library.sqlite-wal", "library.sqlite-shm"):
            shutil.copy2(live / name, copy / name)
    finally:
        writer.close()
    problems = capacity.ready_problems(copy)
    assert any("-wal is not empty" in p for p in problems)
    assert any("queued" in p for p in problems)  # mode=ro reads the WAL; immutable=1 would have missed the queued run
    with pytest.raises(capacity.GuardError):
        capacity.require_ready(copy)
    bare = root / "wal-bare"  # the same files with the WAL left behind are refused as well
    bare.mkdir()
    shutil.copy2(live / "library.sqlite", bare / "library.sqlite")
    (bare / "library.sqlite-wal").write_bytes(b"x" * 32)
    assert any("-wal is not empty" in p for p in capacity.ready_problems(bare))
    with pytest.raises(capacity.GuardError):
        capacity.require_ready(bare)


def test_a_copy_in_which_a_run_is_queued_is_refused_before_any_server_starts(library):
    root, info = library
    copy = root / "queued-copy"
    shutil.copytree(root / "n100", copy)
    conn = sqlite3.connect(copy / "library.sqlite")
    conn.execute("UPDATE runs SET status = 'queued' WHERE id = (SELECT id FROM runs LIMIT 1)")
    conn.commit()
    conn.close()
    assert any("queued" in p for p in capacity.ready_problems(copy))
    with pytest.raises(capacity.GuardError):
        capacity.require_ready(copy)
    out = root / "out"
    out.mkdir()
    started = []
    with pytest.raises(capacity.GuardError):
        capacity.run_rep(100, 1, copy, info, out, "node", started)
    assert started == [] and not list(out.iterdir())  # no server, no node, no repetition file


def test_a_prepared_library_is_reused_only_at_the_codes_highest_migration(library):
    root, info = library
    want = capacity.code_migration()
    assert info["migration"] == want == capacity.library_migration(root / "n100")
    assert want == max(int(p.name.split("_", 1)[0]) for p in (REPO / "backend" / "deixis" / "storage" / "migrations").glob("*.sql"))
    scratch = Path(tempfile.mkdtemp(prefix="h5-"))
    try:
        shutil.copytree(root / "n100", scratch / "n100")
        assert capacity.generate_point(scratch, 100)["reused"] is True  # current marker, current library
        marker = scratch / "n100" / "generated.json"
        import json
        stored = json.loads(marker.read_text())
        del stored["migration"]  # a marker written before the migration number was kept
        marker.write_text(json.dumps(stored))
        again = capacity.generate_point(scratch, 100)
        assert again["reused"] is False and again["migration"] == want
        conn = sqlite3.connect(scratch / "n100" / "library.sqlite")  # a library made one migration earlier, under a current marker
        conn.execute("DELETE FROM schema_migrations WHERE version = ?", (want,))
        conn.commit()
        conn.close()
        assert capacity.library_migration(scratch / "n100") == want - 1
        assert any(f"highest migration is {want - 1}" in p and "generate --force" in p for p in capacity.ready_problems(scratch / "n100"))
        with pytest.raises(capacity.GuardError, match="regenerate it with `generate --force`"):
            capacity.require_ready(scratch / "n100")
        started = []
        out = scratch / "out"
        out.mkdir()
        with pytest.raises(capacity.GuardError, match="highest migration"):  # measure's repetition refuses it before any server starts
            capacity.run_rep(100, 1, scratch / "n100", again, out, "node", started)
        assert started == [] and not list(out.iterdir())
        assert capacity.generate_point(scratch, 100)["reused"] is False  # and generate rebuilds it
        assert capacity.library_migration(scratch / "n100") == want and capacity.ready_problems(scratch / "n100") == []
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def test_the_stored_pdfs_carry_the_marker_the_browser_waits_for(library):
    root, _ = library
    markers = capacity.pdf_markers(root / "n100")
    assert len(markers) == 1
    number, marker = next(iter(markers.items()))
    stored = next((root / "n100" / "papers").glob("*.pdf"))
    with pymupdf.open(stored) as pdf_file:
        first, other = pdf_file[0].get_text(), pdf_file[1].get_text()
    assert marker in " ".join(first.split()) and marker not in " ".join(other.split())
    assert f"work {number}, page 1" in " ".join(first.split()) and marker != capacity.pdf_marker(int(number) + 1)


def test_a_backup_whose_manifest_count_differs_from_the_formula_is_failed(library, monkeypatch):
    root, _ = library
    work = Path(tempfile.mkdtemp(prefix="h5-run-"))
    try:
        (work / "home").mkdir()
        (work / "cwd").mkdir()
        data = work / "data"
        shutil.copytree(root / "n100", data)
        ok = capacity.run_backup(data, work, "ok", [])
        assert ok["failed"] == 0 and ok["problems"] == [] and ok["manifest_files"] == ok["expected_manifest_files"] == 2
        monkeypatch.setattr(capacity, "manifest_expected_files", lambda _dir: 3)
        bad = capacity.run_backup(data, work, "bad", [])
        assert bad["failed"] == 1 and bad["exit"] == 0 and bad["manifest_present"]
        assert any("lists 2 files" in p and "expects 3" in p for p in bad["problems"])
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_an_exception_in_a_repetition_still_writes_the_summary_and_prints_the_leftovers(library, monkeypatch, capsys):
    import argparse
    import json

    root, info = library
    out = capacity.OUT_ROOT / f"test-{os.getpid()}"
    calls = []

    def fake_run_rep(point, rep, src, info, out, node, started, **kw):
        calls.append(rep)
        if rep == 2:
            raise RuntimeError("second repetition broke")
        (out / f"{point}-rep{rep}.json").write_text(json.dumps({"point": str(point), "rep": rep, "started_epoch": 1.0, "errors": [], "load1": 0.5}))
        return {"point": point, "rep": rep}

    monkeypatch.setattr(capacity, "run_rep", fake_run_rep)
    monkeypatch.setattr(capacity, "find_node", lambda: "node")
    args = argparse.Namespace(root=str(root), points="100", reps="3", out=str(out), pdf=False, control=False)
    try:
        with pytest.raises(RuntimeError, match="second repetition broke"):
            capacity.cmd_measure(args)
        assert calls == [1, 2]
        summary = json.loads((out / "summary.json").read_text())
        assert summary["points"]["100"][0]["rep"] == 1 and summary["rows"]["K01c"]["verdict"] == "incomplete"
        assert '"leftover_processes"' in capsys.readouterr().out
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_the_manifest_count_formula_matches_what_backup_lists(library, tmp_path):
    from deixis.config import Settings
    from deixis.storage import backup

    root, _ = library
    copy = root / "backup-check"
    shutil.copytree(root / "n100", copy)
    folder = backup.create_backup(Settings(data_dir=copy), tmp_path)
    import json
    listed = len(json.loads((folder / "manifest.json").read_text())["files"])
    assert listed == capacity.manifest_expected_files(copy) == 1 + 1  # the database copy and the one stored PDF


# ---- raising steps, killed node, duplicates, the works cell ---------------------------------------------------------------


def _fake_rep(monkeypatch, wal=0):
    """Stand-ins for the server and the two threads, so that run_rep runs without a process; returns what they recorded."""
    import json
    import time as _time

    class Recorded:
        pollers, streams, node_calls = [], [], []

    class FakePoller:
        def __init__(self, base):
            self.finished = False
            Recorded.pollers.append(self)

        def start(self):
            pass

        def finish(self):
            self.finished = True

        def overlapping(self, start, end):
            return {"n": 0, "max_s": None, "top3_s": [], "non_200": 0}

    class FakeStream(FakePoller):
        bytes = 0
        status, connected_at, ended_at = None, None, None
        ready = __import__("threading").Event()
        ready.set()

        def covered(self, start, end):
            return False

        def __init__(self, base, research_id):
            self.finished = False
            Recorded.streams.append(self)

    class FakeServer:
        def __init__(self, data, work, started):
            self.data, self.base, self.startup_s = data, "http://127.0.0.1:8900", 0.0
            self.rss_peak = self.rss_last = self.rss_samples = 1

        def start(self):
            if wal:  # the server's WAL while it runs
                (self.data / "library.sqlite-wal").write_bytes(b"x" * wal)

        def stop_sampling(self):
            pass

        def stop(self):  # a clean shutdown checkpoints and removes the WAL
            (self.data / "library.sqlite-wal").unlink(missing_ok=True)

    def get(base, path):
        body = json.dumps({"scope": {"question": "q"}, "research": {"title": "q"}, "sources": [{}, {}, {}]}).encode()
        return {"status": 200, "seconds": 0.01, "bytes": len(body), "start": _time.time(), "end": _time.time(), "body": body}

    stub_backup = {"seconds": 0.0, "bytes": 0, "failed": 0, "exit": 0, "manifest_files": 2, "expected_manifest_files": 2, "problems": []}
    monkeypatch.setattr(capacity, "Server", FakeServer)
    monkeypatch.setattr(capacity, "HealthPoller", FakePoller)
    monkeypatch.setattr(capacity, "EventStream", FakeStream)
    monkeypatch.setattr(capacity, "timed_get", get)
    monkeypatch.setattr(capacity, "run_backup", lambda *a, **k: stub_backup)
    Recorded.pollers, Recorded.streams, Recorded.node_calls = [], [], []
    return Recorded


@pytest.mark.parametrize("missing", ["health_errors", "first_tab", "second_tab", "stream_http", "stream_connect", "stream_closed", "none"])
def test_run_rep_publishes_health_only_with_successful_tabs_and_sse_window(library, tmp_path, monkeypatch, missing):
    root, info = library
    covered = getattr(capacity.EventStream, "covered", None)
    fakes = _fake_rep(monkeypatch)
    monkeypatch.setattr(capacity.time, "sleep", lambda _: None)
    monkeypatch.setattr(capacity.HealthPoller, "overlapping", lambda *a: {"n": 4, "max_s": .01, "top3_s": [.01], "non_200": int(missing == "health_errors")})
    stream_cls = capacity.EventStream
    stream_cls.status = 500 if missing == "stream_http" else 200
    stream_cls.connected_at = None if missing == "stream_connect" else 0
    stream_cls.ended_at = 1 if missing == "stream_closed" else None
    if covered is not None:
        monkeypatch.setattr(stream_cls, "covered", covered)

    def node(*args):
        steps = args[2]["steps"]
        if steps == ["two-tab"]:
            return {"steps": {"two-tab": {"ok": missing != "second_tab", "seconds": .1, "first_tab_ready": missing != "first_tab", "start_epoch_ms": 2000, "end_epoch_ms": 3000}}}
        return {"steps": {"k01": {"ok": True, "seconds": .01}}}
    monkeypatch.setattr(capacity, "run_node", node)
    monkeypatch.setattr(capacity, "_backup_while_serving", lambda *a: None)
    out = tmp_path / "out"
    out.mkdir()
    rec = capacity.run_rep(5000, 1, root / "n100", info, out, "node", [])
    published = __import__("json").loads((out / "5000-rep1.json").read_text())
    expected = .01 if missing == "none" else None
    assert published["two_tab_health_max_s"] == expected
    assert published["health_max_s"] == expected
    assert rec["health_non_200"] == int(missing == "health_errors")


def test_failed_pdf_browser_preserves_raw_rss_but_k03a_is_incomplete(library, tmp_path, monkeypatch):
    root, info = library
    _fake_rep(monkeypatch)
    monkeypatch.setattr(capacity, "run_node", lambda *a: {"steps": {}, "killed": True, "error": "before PDF step"})
    out = tmp_path / "out"
    out.mkdir()
    rec = capacity.run_rep("pdf", 1, root / "n100", info | {"pages": 500}, out, "node", [], is_pdf=True)
    assert rec["rss_peak_bytes"] == 1
    reps = {p: [dict(rss_peak_bytes=1)] * 3 for p in ("100", "1000", "5000", "7769")}
    reps["pdf"] = [rec] * 3
    assert capacity.judge(capacity.FROZEN["rows"]["K03a"], capacity.results_of(reps))["verdict"] == "incomplete"
    assert rec["rss_workload_complete"] is False


@pytest.mark.parametrize("failure", ["ui_failure", "api_timeout", "two_tab_raise"])
def test_run_rep_exception_paths_cannot_publish_a_fast_health_time(library, tmp_path, monkeypatch, failure):
    root, info = library
    _fake_rep(monkeypatch)
    monkeypatch.setattr(capacity.time, "sleep", lambda _: None)
    monkeypatch.setattr(capacity.HealthPoller, "overlapping", lambda *a: {"n": 4, "max_s": .01, "top3_s": [.01], "non_200": 0})
    get = capacity.timed_get
    if failure == "api_timeout":
        monkeypatch.setattr(capacity, "timed_get", lambda *a: get(*a) | {"status": "timeout", "seconds": 120})
    def node(*args):
        if args[2]["steps"] == ["two-tab"]:
            raise RuntimeError("two-tab did not complete")
        return {"steps": {"k01": {"ok": failure != "ui_failure", "seconds": .01}}}
    monkeypatch.setattr(capacity, "run_node", node)
    monkeypatch.setattr(capacity, "_backup_while_serving", lambda *a: None)
    out = tmp_path / "out"
    out.mkdir()
    point = 5000 if failure == "two_tab_raise" else 1000
    rec = capacity.run_rep(point, 1, root / "n100", info, out, "node", [])
    assert rec["health_n"] == 4 and rec["health_max_s"] is None
    row = capacity.FROZEN["rows"]["K02b" if point == 5000 else "K02a"]
    assert capacity.judge(row, capacity.results_of({str(point): [rec] * 3}))["verdict"] == "incomplete"


def test_measure_refuses_stale_repetitions_before_starting(library, tmp_path, monkeypatch):
    import argparse
    root, _ = library
    out = tmp_path / "old-out"
    out.mkdir()
    for rep in (1, 2, 3): (out / f"100-rep{rep}.json").write_text('{"rep":' + str(rep) + '}')
    monkeypatch.setattr(capacity, "guard_out", lambda _: out)
    monkeypatch.setattr(capacity, "find_node", lambda: "node")
    monkeypatch.setattr(capacity, "measure_passes", lambda *a: pytest.fail("must refuse before starting or merging old repetitions"))
    monkeypatch.setattr(capacity, "leftover", lambda _: [])
    with pytest.raises(capacity.GuardError, match="not empty"):
        capacity.cmd_measure(argparse.Namespace(root=str(root), out=str(out), reps="1"))


def test_a_raising_view_request_stops_the_poller_and_the_wal_is_read_after_the_server_stopped(library, monkeypatch):
    root, info = library
    fakes = _fake_rep(monkeypatch, wal=50)

    def boom(base, path):
        raise RuntimeError("view request broke")

    monkeypatch.setattr(capacity, "timed_get", boom)
    out = root / "out-poller"
    out.mkdir()
    rec = capacity.run_rep(100, 1, root / "n100", info, out, "node", [])
    assert len(fakes.pollers) == 1 and all(p.finished for p in fakes.pollers)  # the thread was stopped although the request raised
    assert any("view request broke" in e for e in rec["errors"])
    assert rec["wal_bytes_running"] == 50 and rec["wal_bytes"] == 0  # read before and after the stop


def test_a_raising_node_run_stops_the_poller_and_the_event_stream_of_the_two_tab_step(library, monkeypatch):
    root, info = library
    fakes = _fake_rep(monkeypatch)

    def node(node_path, work, args, timeout, started):
        fakes.node_calls.append(args["steps"])
        if args["steps"] == ["two-tab"]:
            raise RuntimeError("node broke")
        return {"ok": True, "steps": {"k01": {"ok": True, "seconds": 0.5, "page_ms": 1.0}}}

    monkeypatch.setattr(capacity, "run_node", node)
    out = root / "out-stream"
    out.mkdir()
    rec = capacity.run_rep(5000, 1, root / "n100", info, out, "node", [])
    assert ["two-tab"] in fakes.node_calls
    assert len(fakes.streams) == 1 and fakes.streams[0].finished
    assert fakes.pollers and all(p.finished for p in fakes.pollers)  # the first, the two-tab and the running-backup poller
    assert any("node broke" in e for e in rec["errors"])


def test_a_repetition_after_which_the_runs_changed_records_an_error(library, monkeypatch):
    root, info = library
    _fake_rep(monkeypatch)
    out = root / "out-runs"
    out.mkdir()
    same = capacity.run_rep(100, 1, root / "n100", info, out, "node", [])
    assert same["library_runs_unchanged"] is True and not any("library changed" in e for e in same["errors"])
    monkeypatch.setattr(capacity, "counts", lambda data_dir, research_id=None: {"runs_by_status": {"completed": 24, "queued": 1}})
    rec = capacity.run_rep(100, 2, root / "n100", info, out, "node", [])
    assert rec["library_runs_unchanged"] is False
    assert any("library changed" in e and "queued" in e for e in rec["errors"])


def test_the_node_budget_counts_every_wait_a_step_makes(library, monkeypatch):
    root, info = library
    assert [capacity.node_units([s]) for s in ("k01", "k04", "k04c-abstract", "k04c-pdf", "two-tab", "pdf")] == [1, 2, 3, 3, 2, 3]
    assert capacity.node_units(["k01", "k04", "k04c-abstract", "k04c-pdf"]) == 9
    fakes = _fake_rep(monkeypatch)
    budgets = []

    def node(node_path, work, args, timeout, started):
        budgets.append((args["steps"], timeout))
        return {"ok": True, "steps": {"k01": {"ok": True, "seconds": 0.5, "page_ms": 1.0}}}

    monkeypatch.setattr(capacity, "run_node", node)
    out = root / "out-budget"
    out.mkdir()
    capacity.run_rep(5000, 1, root / "n100", info, out, "node", [])
    assert fakes.pollers
    assert budgets[0] == (["k01", "k04", "k04c-abstract", "k04c-pdf"], capacity.node_budget_s(9))
    assert budgets[1] == (["two-tab"], capacity.node_budget_s(2))


def test_the_first_moment_the_pdf_conditions_held_is_the_recorded_time_minus_the_stability_wait():
    assert capacity.first_ok_s({"ok": True, "seconds": 2.0, "stable_wait_ms": 120.0}) == pytest.approx(1.88)
    assert capacity.first_ok_s({"ok": False, "seconds": 2.0, "stable_wait_ms": 120.0}) is None
    assert capacity.first_ok_s({"ok": True, "seconds": 2.0}) is None and capacity.first_ok_s(None) is None


def test_the_node_budget_is_the_step_deadline_plus_slack_per_step():
    assert capacity.node_budget_s(1) == capacity.UI_DEADLINE_S + capacity.NODE_SLACK_S
    assert capacity.node_budget_s(4) == 4 * (capacity.UI_DEADLINE_S + capacity.NODE_SLACK_S)


def test_the_last_complete_json_line_is_the_result_and_a_cut_line_is_skipped():
    assert capacity.last_json_line('{"a": 1}\nnoise\n{"a": 2}\n{"a": 3, "cut') == {"a": 2}
    assert capacity.last_json_line("no json at all") is None and capacity.last_json_line(None) is None


def _fake_node(work, body):
    path = work / "fakenode"
    path.write_text(f"#!{sys.executable}\nimport sys, time\n{body}")
    path.chmod(0o755)
    (work / "home").mkdir(exist_ok=True)
    return str(path)


def test_a_killed_node_keeps_the_steps_it_had_finished_and_a_finished_node_gives_its_last_line():
    work = Path(tempfile.mkdtemp(prefix="h5-run-"))
    try:
        first = '{"ok": false, "steps": {"k01": {"ok": true, "seconds": 1.5}}}'
        hung = _fake_node(work, f"print({first!r}, flush=True)\nsys.stdout.write('{{\"ok\": false, \"ste')\nsys.stdout.flush()\ntime.sleep(60)\n")
        started = []
        result = capacity.run_node(hung, work, {}, 4.0, started)  # killed after 4 s, mid-line of its second snapshot
        assert result["killed"] is True and result["ok"] is False and "stopped after" in result["error"]
        assert result["steps"]["k01"] == {"ok": True, "seconds": 1.5}  # the finished step survives the kill
        assert len(started) == 1 and not capacity.is_same_and_live(started[0])
        done = _fake_node(work, f"print({first!r}, flush=True)\nprint('{{\"ok\": true, \"steps\": {{\"k01\": {{}}, \"k04b\": {{}}}}}}', flush=True)\n")
        finished = capacity.run_node(done, work, {}, 30.0, [])
        assert finished["ok"] is True and set(finished["steps"]) == {"k01", "k04b"} and "killed" not in finished
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_a_repetition_that_two_folders_both_hold_is_refused(tmp_path):
    import json

    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    base = {"point": "1000", "errors": [], "started_epoch": 1.0}
    (a / "1000-rep1.json").write_text(json.dumps(base | {"rep": 1}))
    (b / "1000-rep2.json").write_text(json.dumps(base | {"rep": 2}))
    assert [r["rep"] for r in capacity.load_reps(a, [b])["1000"]] == [1, 2]  # different repetitions of one point merge
    (b / "1000-rep1.json").write_text(json.dumps(base | {"rep": 1}))
    with pytest.raises(capacity.GuardError, match="duplicate repetition: point 1000, rep 1"):
        capacity.load_reps(a, [b])
    with pytest.raises(capacity.GuardError, match="duplicate repetition"):
        capacity.summarize(a, [b])
    assert not (a / "summary.json").exists()


def test_the_works_cell_shows_the_slowest_successful_repetition_and_how_many_were_ready():
    def rec(rep, ok, seconds):
        return {"rep": rep, "ui_ready_ok": ok, "ui_ready_s": seconds}

    reps = {"1000": [rec(1, 1, 1.0), rec(2, 1, 1.5), rec(3, 1, 1.2)],
            "10000": [rec(1, 1, 5.0), rec(2, 1, 9.0), rec(3, 0, 120.0)]}
    assert capacity.measured_of(reps)["largest_loaded"] == (10000, 9.0, 2, 3)  # not the fastest (5.0), and not the timeout
    cell = next(r for r in capacity.limits_table(capacity.measured_of(reps)) if r["limit"] == "Works in one research")["measured"]
    assert "10,000 works" in cell and "9.00 s (slowest successful repetition)" in cell and "2 of 3 repetitions ready" in cell
    none = {"10000": [rec(1, 0, 120.0), rec(2, 0, 120.0), rec(3, 0, 120.0)], "1000": [rec(1, 1, 1.0), rec(2, 0, 120.0), rec(3, 1, 3.0)]}
    assert capacity.measured_of(none)["largest_loaded"] == (1000, 3.0, 2, 3)  # a point with no ready repetition did not load


# ---- limits (K07) --------------------------------------------------------------------------------------------------------


def test_the_limits_table_has_no_empty_cell_and_its_constants_are_the_codes():
    from deixis.api import app as api_app
    from deixis.config import Settings
    from deixis.documents import fetch, pdf

    rows = capacity.limits_table()
    assert capacity.judge_limits(rows)["verdict"] == "pass"
    for row in rows:
        for key in ("limit", "kind", "value", "source", "measured"):
            assert str(row[key]).strip(), (row["limit"], key)
    raw = {r["limit"]: r["raw"] for r in rows}
    assert raw["Upload size"] == api_app.MAX_UPLOAD_BYTES == 50 * 1024 * 1024
    assert raw["Download size"] == fetch.MAX_BYTES
    assert raw["Extraction pages"] == pdf.MAX_PAGES
    assert raw["Extraction characters"] == pdf.MAX_TEXT_CHARS
    assert raw["Extraction time"] == pdf.TIMEOUT_SECONDS
    assert raw["Extraction memory"] == pdf.MAX_MEMORY_BYTES
    assert raw["Model concurrency"] == Settings.__dataclass_fields__["model_concurrency"].default
    kinds = {r["limit"]: r["kind"] for r in rows}
    assert kinds["Extraction memory"] == "watcher threshold" and kinds["Model concurrency"] == "configurable default"
    assert {r["kind"] for r in rows} == {"hard limit", "watcher threshold", "configurable default", "measured only"}
    # the server's RSS is not what the 1 GiB watcher watches, and the file:line of each constant is real
    watcher = next(r for r in rows if r["limit"] == "Extraction memory")
    assert "RSS is not what this watcher watches" in watcher["measured"]
    for row in rows[:7]:
        path, line = row["source"].rsplit(":", 1)
        assert (REPO / path).read_text().splitlines()[int(line) - 1].strip()
    assert capacity.judge_limits([dict(rows[0], measured="")])["verdict"] == "fail"
    assert capacity.judge_limits([dict(rows[0], source="")])["verdict"] == "fail"  # the file:line cell counts as well
    assert capacity.judge_limits([dict(rows[0], source=" ")])["empty_cells"] == [(rows[0]["limit"], "source")]


def test_the_load_label_is_repeated_under_each_table_heading_and_the_header_keeps_it():
    rows = capacity.limits_table()
    base = {"rows": {}, "limits": rows, "load_at_start": 9.0}
    loaded = capacity.render_table(base | {"under_parallel_load": True}).splitlines()
    sentence = 'The label "under parallel load" applies to every row of this table.'
    assert "(under parallel load)" in loaded[0]
    assert loaded[loaded.index(sentence) - 1] == "" and sentence in loaded[1:4]  # under the first heading
    heading = next(i for i, line in enumerate(loaded) if line.startswith("K07 limits table"))
    assert "(under parallel load)" in loaded[heading] and loaded[heading + 2] == sentence  # and under the K07 heading
    assert loaded.count(sentence) == 2
    quiet = capacity.render_table(base | {"under_parallel_load": False})
    assert "under parallel load" not in quiet


def test_a_first_view_request_that_times_out_is_a_result_not_a_harness_error(monkeypatch):
    import httpx

    def hang(self, url, **kwargs):
        raise httpx.ReadTimeout("no answer")

    monkeypatch.setattr(httpx.Client, "get", hang)
    got = capacity.timed_get("http://127.0.0.1:9", "/api/researches/x")
    assert got["status"] == "timeout" and got["seconds"] >= 0 and got["end"] >= got["start"]


def test_a_record_without_the_workload_complete_field_does_not_supply_an_rss_peak():
    reps = {"pdf": [{"rep": 1, "rss_peak_bytes": 5}, {"rep": 2, "rss_peak_bytes": 6, "rss_workload_complete": True}]}
    assert capacity.results_of(reps)["pdf"]["rss_peak_bytes"] == [None, 6]
