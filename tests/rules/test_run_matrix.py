"""P9 H8: the row mapping of `scripts/release_checks/run_matrix.py`. Pure functions on synthetic junit and Playwright files; no stage is run
and nothing is started except one `pytest --collect-only` listing, used to prove every test pattern in the row table matches a real test."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "release_checks"))
import run_matrix as rm  # noqa: E402

PASS, FAIL, NOT = rm.PASS, rm.FAIL, rm.NOT


def junit(tmp_path, cases):
    body = "".join(
        '<testcase classname="%s" name="%s">%s</testcase>' % (m, n, {"passed": "", "failed": "<failure/>", "error": "<error/>", "skipped": "<skipped/>"}[s])
        for m, n, s in cases)
    path = tmp_path / "x.xml"
    path.write_text('<testsuites><testsuite>%s</testsuite></testsuites>' % body)
    return rm.junit_cases([path])


def test_junit_row_passes_only_when_every_pattern_matched_and_everything_passed(tmp_path):
    cases = junit(tmp_path, [("tests.a", "test_x[1]", "passed"), ("tests.a", "test_x[2]", "passed"), ("tests.b", "test_y", "passed")])
    res = rm.rule_junit(cases, [("tests.a", "test_x"), ("tests.b", "test_*")], "")
    assert res["result"] == PASS and res["evidence"].startswith("3 tests")


def test_a_failed_or_errored_test_fails_the_row(tmp_path):
    for status in ("failed", "error"):
        cases = junit(tmp_path, [("tests.a", "test_x", "passed"), ("tests.a", "test_z", status)])
        assert rm.rule_junit(cases, [("tests.a", "test_*")], "")["result"] == FAIL


def test_a_skipped_test_is_not_a_pass(tmp_path):
    cases = junit(tmp_path, [("tests.a", "test_x", "skipped")])
    assert rm.rule_junit(cases, [("tests.a", "test_x")], "")["result"] == NOT


def test_a_pattern_that_matches_nothing_is_not_a_pass_even_when_another_pattern_matched(tmp_path):
    cases = junit(tmp_path, [("tests.a", "test_x", "passed")])
    res = rm.rule_junit(cases, [("tests.a", "test_x"), ("tests.a", "test_renamed")], "")
    assert res["result"] == NOT and "no test matches" in res["note"]


def spec(title, status, file="acceptance.spec.ts"):
    result = {"expected": "passed", "unexpected": "failed", "flaky": "passed", "skipped": "skipped"}[status]
    return {"title": title, "file": file, "tests": [{"status": status, "expectedStatus": "passed", "results": [{"status": result}]}]}


def test_exit_status_is_0_only_when_every_mandatory_row_passed():
    rows = [{"class": "zorunlu", "result": PASS}, {"class": "isteğe bağlı", "result": NOT}, {"class": "yalnız ölçüm", "result": FAIL}]
    assert rm.exit_status(rows) == 0
    assert rm.exit_status(rows + [{"class": "zorunlu", "result": NOT}]) == 1
    assert rm.exit_status(rows + [{"class": "zorunlu", "result": FAIL}]) == 1


def test_the_script_never_names_a_live_port_and_points_a_forgetful_child_away_from_the_live_data_directory(tmp_path):
    assert not set(rm.OWN_PORTS) & rm.LIVE_PORTS
    assert not set(rm.PLAYWRIGHT_PORTS) & rm.LIVE_PORTS
    run = rm.Run(rm.parse_args([]), tmp_path / "out", "x")
    env = run.env()
    assert Path(env["DEIXIS_DATA_DIR"]).parent == tmp_path / "out"
    assert str(rm.LIVE_DATA_DIR) not in env.values()
    assert "--basetemp" in run.pytest_cmd(tmp_path / "a.xml") and str(tmp_path / "out") in " ".join(run.pytest_cmd(tmp_path / "a.xml"))


def test_row_ids_are_unique_and_every_row_has_a_class_and_a_kind():
    ids = [r["id"] for r in rm.rows_ordered()]
    assert len(ids) == 63
    assert len(ids) == len(set(ids))
    assert ids[ids.index("D01-D06"):ids.index("suite-pytest") + 1] == ["D01-D06", "T14", "T16", "suite-pytest"]
    assert len(rm.table({})) == 64  # the cleanup row follows the ordered rows
    assert all(r["cls"] in rm.CLASSES and r["kind"] and r["execution"] and r["data"] for r in rm.rows_ordered())


def leaf_rules(rule):
    if rule[0] == "all":
        for child in rule[1:]:
            yield from leaf_rules(child)
    else:
        yield rule


@pytest.fixture(scope="module")
def collected_cases():
    listing = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "-n", "0", "-m", "process or not process"],
                             cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, env={k: v for k, v in dict(__import__("os").environ, PYTHONPATH="backend:.").items() if k != "DEIXIS_TEST_SHARD"})  # every test, not one CI shard
    assert listing.returncode == 0, listing.stdout[-2000:]
    collected = []
    for line in listing.stdout.splitlines():
        if "::" in line and line.startswith("tests/"):
            path, _, name = line.partition("::")
            full = name.split("::")[-1]
            collected.append({"module": path[:-3].replace("/", "."), "name": full, "status": "passed"})
    assert len(collected) > 1000, listing.stdout[-500:]
    return collected


def test_every_junit_pattern_matches_a_real_collected_test(collected_cases):
    """A renamed test must show up here, not as a silent hole in the matrix."""
    unmatched = []
    for row in rm.rows_ordered():
        for rule in leaf_rules(row["rule"]):
            if rule[0] != "junit":
                continue
            for module, glob in rule[1]:
                if rm.rule_junit(collected_cases, [(module, glob)], "")["result"] != PASS:
                    unmatched.append("%s: %s::%s" % (row["id"], module, glob))
    assert unmatched == []


def test_f04_orphan_is_not_measured_when_any_one_named_guard_test_is_missing():
    patterns = next(r["rule"][1] for r in rm.ROWS if r["id"] == "F04-orphan")
    assert all(module.startswith(rm.PROC) for module, _ in patterns)
    cases = [{"module": module, "name": name, "status": "passed"} for module, name in patterns]
    assert rm.rule_junit(cases, patterns, "x")["result"] == PASS
    for i in range(len(cases)):
        assert rm.rule_junit(cases[:i] + cases[i + 1:], patterns, "x")["result"] == NOT, cases[i]
