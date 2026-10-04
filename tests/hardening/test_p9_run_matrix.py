"""P9 H8: the row mapping of `scripts/p9/run_matrix.py`. Pure functions on synthetic junit and Playwright files; no stage is run
and nothing is started except one `pytest --collect-only` listing, used to prove every test pattern in the row table matches a real test."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "p9"))
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


def test_no_junit_file_is_not_a_pass():
    res = rm.rule_junit(None, [("tests.a", "test_*")], "stage pytest skipped")
    assert res["result"] == NOT and res["note"] == "stage pytest skipped"


def test_orphan_evidence_is_mandatory_and_missing_or_skipped_never_passes(tmp_path):
    row = next(r for r in rm.ROWS if r["id"] == "F04-orphan")
    assert row["cls"] == "zorunlu"
    assert rm.evaluate(row, {})["result"] == NOT
    skipped = junit(tmp_path, [(module, pattern.rstrip("*"), "skipped") for module, pattern in row["rule"][1]])
    assert rm.evaluate(row, {"process": skipped})["result"] == NOT
    passed = junit(tmp_path, [(module, pattern.rstrip("*"), "passed") for module, pattern in row["rule"][1]])
    assert rm.evaluate(row, {"process": passed})["result"] == PASS
    without_control = [c for c in passed if c["name"] != "test_orphan_memory_guard_disabled_control"]
    assert rm.evaluate(row, {"process": without_control})["result"] == NOT


def test_a_failure_in_one_stage_file_is_not_hidden_by_a_pass_of_the_same_test_in_another(tmp_path):
    data = {"missing": {}, "pytest": junit(tmp_path, [("tests.a", "test_x", "passed")]), "process": junit(tmp_path, [("tests.a", "test_x", "failed")])}
    row = {"id": "T", "rule": ("junit", [("tests.a", "test_x")])}
    assert rm.evaluate(row, data)["result"] == FAIL


def test_the_f09_row_reads_only_the_f09_file_so_a_skipped_default_run_cannot_spoil_or_fake_it(tmp_path):
    f09 = next(r for r in rm.ROWS if r["id"] == "F09")
    skipped = junit(tmp_path, [("tests.documents.test_documents", "test_extraction_is_stopped_at_the_production_memory_limit", "skipped"),
                               ("tests.documents.test_arxiv_source_archive", "test_the_source_child_is_stopped_at_the_production_memory_limit", "skipped")])
    passed = junit(tmp_path, [("tests.documents.test_documents", "test_extraction_is_stopped_at_the_production_memory_limit", "passed"),
                              ("tests.documents.test_arxiv_source_archive", "test_the_source_child_is_stopped_at_the_production_memory_limit", "passed")])
    assert rm.evaluate(f09, {"missing": {}, "pytest": skipped})["result"] == NOT
    assert rm.evaluate(f09, {"missing": {}, "pytest": skipped, "f09": passed})["result"] == PASS
    assert rm.evaluate(f09, {"missing": {}, "f09": skipped})["result"] == NOT


def pw_file(tmp_path, suites):
    path = tmp_path / "results.json"
    path.write_text(json.dumps({"suites": suites}))
    return rm.playwright_specs(path)


def spec(title, status, file="acceptance.spec.ts"):
    result = {"expected": "passed", "unexpected": "failed", "flaky": "passed", "skipped": "skipped"}[status]
    return {"title": title, "file": file, "tests": [{"status": status, "expectedStatus": "passed", "results": [{"status": result}]}]}


@pytest.mark.parametrize("test,want", [
    ({"status": "expected", "expectedStatus": "failed", "results": [{"status": "failed"}]}, NOT),
    ({"status": "expected", "expectedStatus": "passed", "results": []}, NOT),
    ({"status": "skipped", "expectedStatus": "passed", "results": [{"status": "skipped"}]}, NOT),
    ({"status": "flaky", "expectedStatus": "passed", "results": [{"status": "failed"}, {"status": "passed"}]}, FAIL),
    ({"status": "expected", "expectedStatus": "passed", "results": [{"status": "passed"}, {"status": "failed"}]}, FAIL),
])
def test_playwright_execution_evidence_binds_row_suite_and_mandatory_result(tmp_path, test, want):
    specs = pw_file(tmp_path, [{"file": "acceptance.spec.ts", "specs": [{"title": "A: x", "tests": [test]}]}])
    data = {"playwright": specs, "web_ok": True, "stage_ok": {"playwright": True}}
    rows = {r["id"]: r for r in rm.table(data)}
    assert rows["A"]["result"] == want
    assert rows["suite-playwright"]["result"] == want
    assert rm.exit_status([rows["A"], rows["suite-playwright"]]) == 1


def test_playwright_rows_match_by_file_and_title_and_include_the_describe_titles(tmp_path):
    specs = pw_file(tmp_path, [
        {"title": "acceptance.spec.ts", "file": "acceptance.spec.ts", "specs": [spec("A: x", "expected"), spec("setup", "expected")],
         "suites": [{"title": "block", "file": "acceptance.spec.ts", "specs": [spec("B: y", "expected")]}]},
        {"title": "a11y.spec.ts", "file": "a11y.spec.ts", "suites": [{"title": "X05: A to G by keyboard", "file": "a11y.spec.ts", "specs": [spec("walk", "expected", "a11y.spec.ts")]}]},
    ])
    rows = {r["id"]: r for r in rm.ROWS}
    assert rm.evaluate(rows["A"], {"missing": {}, "playwright": specs, "web_ok": True})["result"] == PASS
    assert rm.evaluate(rows["B"], {"missing": {}, "playwright": specs, "web_ok": True})["result"] == PASS
    assert rm.evaluate(rows["C"], {"missing": {}, "playwright": specs, "web_ok": True})["result"] == NOT  # nothing named C: matched nothing
    assert rm.evaluate(rows["X05"], {"missing": {}, "playwright": specs, "web_ok": True})["result"] == PASS
    assert rm.evaluate(rows["X06"], {"missing": {}, "playwright": specs, "web_ok": True})["result"] == NOT


def test_playwright_failed_flaky_and_skipped_specs(tmp_path):
    for status, want in (("unexpected", FAIL), ("flaky", FAIL), ("skipped", NOT), ("expected", PASS)):
        specs = pw_file(tmp_path, [{"title": "acceptance.spec.ts", "file": "acceptance.spec.ts", "specs": [spec("E: x", status)]}])
        assert rm.rule_playwright(specs, "acceptance.spec.ts", r"(^|\s)E: ", "")["result"] == want


def test_a_missing_playwright_file_is_not_a_pass(tmp_path):
    assert rm.playwright_specs(tmp_path / "none.json") is None
    assert rm.rule_playwright(None, "acceptance.spec.ts", "A", "stage playwright skipped")["result"] == NOT


def test_install_rows():
    results = {"commit": "abc" * 10, "rows": [{"id": "I01", "result": "pass"}, {"id": "I02", "result": "fail"}, {"id": "I08", "result": "not_measured"}]}
    assert rm.rule_install(results, "I01", "")["result"] == PASS
    assert rm.rule_install(results, "I02", "")["result"] == FAIL
    assert rm.rule_install(results, "I08", "")["result"] == NOT
    assert rm.rule_install(results, "I05", "")["result"] == NOT
    assert rm.rule_install(None, "I01", "skipped")["result"] == NOT


def test_capacity_rows_take_the_class_from_the_frozen_table_and_k07_needs_the_limits_command():
    import capacity
    rows = {r["id"]: r for r in rm.capacity_rows()}
    assert set(rows) == set(capacity.FROZEN["rows"])
    assert rows["K01a"]["cls"] == "zorunlu" and rows["K05"]["cls"] == "yalnız ölçüm"
    summary = {"rows": {"K01a": {"verdict": "pass"}, "K01b": {"verdict": "fail"}, "K01c": {"verdict": "measured"}, "K02a": {"verdict": "incomplete"}, "K07": {"verdict": "pass"}}}
    assert rm.rule_capacity(summary, 0, "K01a", "")["result"] == PASS
    assert rm.rule_capacity(summary, 0, "K01b", "")["result"] == FAIL
    assert rm.rule_capacity(summary, 0, "K01c", "")["result"] == PASS
    assert rm.rule_capacity(summary, 0, "K02a", "")["result"] == NOT
    assert rm.rule_capacity(summary, 1, "K07", "", "ok")["result"] == FAIL
    assert rm.rule_capacity(summary, None, "K07", "", "ok")["result"] == NOT
    assert rm.rule_capacity(summary, 0, "K07", "", "ok")["result"] == PASS
    assert rm.rule_capacity(None, 0, "K01a", "stage capacity skipped")["result"] == NOT


def test_an_empty_run_passes_nothing_and_exits_1():
    rows = rm.table({"missing": {}})
    assert not [r for r in rows if r["result"] == PASS]
    assert rm.exit_status(rows) == 1
    assert {r["result"] for r in rows} <= set(rm.RESULTS)


def test_exit_status_is_0_only_when_every_mandatory_row_passed():
    rows = [{"class": "zorunlu", "result": PASS}, {"class": "isteğe bağlı", "result": NOT}, {"class": "yalnız ölçüm", "result": FAIL}]
    assert rm.exit_status(rows) == 0
    assert rm.exit_status(rows + [{"class": "zorunlu", "result": NOT}]) == 1
    assert rm.exit_status(rows + [{"class": "zorunlu", "result": FAIL}]) == 1


def test_a_skipped_stage_gives_olculmedi_with_its_reason():
    data = {"missing": {"playwright": "stage playwright skipped"}, "playwright": None, "web_ok": True}
    row = next(r for r in rm.ROWS if r["id"] == "A")
    res = rm.evaluate(row, data)
    assert res["result"] == NOT and res["note"] == "stage playwright skipped"


def test_a_cleanup_finding_fails_the_cleanup_row_and_none_passes_it():
    assert [r for r in rm.table({"missing": {}, "cleanup": []}) if r["id"] == "cleanup"][0]["result"] == PASS
    bad = [r for r in rm.table({"missing": {}, "cleanup": ["listeners: 8950 (pid 1)"]}) if r["id"] == "cleanup"][0]
    assert bad["result"] == FAIL and "8950" in bad["note"]
    assert [r for r in rm.table({"missing": {}}) if r["id"] == "cleanup"][0]["result"] == NOT


def test_refusals(tmp_path):
    tools = {"uv": "/x/uv", "node": "/x/node", "npm": "/x/npm"}
    assert rm.refusals(tmp_path, "arm64", [], tools, tmp_path / "out") == []
    (tmp_path / ".env").write_text("X=1")
    assert any(".env" in p for p in rm.refusals(tmp_path, "arm64", [], tools, tmp_path / "out"))
    assert any("arm64" in p for p in rm.refusals(tmp_path, "x86_64", [], tools, tmp_path / "out2"))
    assert any("8950" in p for p in rm.refusals(tmp_path, "arm64", [8950], tools, tmp_path / "out3"))
    assert any("npm" in p for p in rm.refusals(tmp_path, "arm64", [], dict(tools, npm=None), tmp_path / "out4"))
    (tmp_path / "exists").mkdir()
    assert any("already exists" in p for p in rm.refusals(tmp_path, "arm64", [], tools, tmp_path / "exists"))


def test_the_script_never_names_a_live_port_and_points_a_forgetful_child_away_from_the_live_data_directory(tmp_path):
    assert not set(rm.OWN_PORTS) & rm.LIVE_PORTS
    assert not set(rm.PLAYWRIGHT_PORTS) & rm.LIVE_PORTS
    run = rm.Run(rm.parse_args([]), tmp_path / "out", "x")
    env = run.env()
    assert Path(env["DEIXIS_DATA_DIR"]).parent == tmp_path / "out"
    assert str(rm.LIVE_DATA_DIR) not in env.values()
    assert "--basetemp" in run.pytest_cmd(tmp_path / "a.xml") and str(tmp_path / "out") in " ".join(run.pytest_cmd(tmp_path / "a.xml"))


def test_a_port_clash_in_the_playwright_log_makes_the_browser_rows_olculmedi(tmp_path):
    specs = pw_file(tmp_path, [{"title": "acceptance.spec.ts", "file": "acceptance.spec.ts", "specs": [spec("A: x", "expected")]}])
    row = next(r for r in rm.ROWS if r["id"] == "A")
    res = rm.evaluate(row, {"missing": {}, "playwright": specs, "web_ok": True, "playwright_port_clash": True})
    assert res["result"] == NOT and "address already in use" in res["note"]


def test_a_nonzero_exit_of_the_install_or_f09_stage_turns_a_pass_into_a_fail():
    install = {"commit": "a" * 10, "rows": [{"id": "I01", "result": "pass"}]}
    row = next(r for r in rm.ROWS if r["id"] == "I01")
    assert rm.evaluate(row, {"missing": {}, "install": install, "stage_ok": {"install": False}})["result"] == FAIL
    assert rm.evaluate(row, {"missing": {}, "install": install, "stage_ok": {"install": True}})["result"] == PASS


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
                             cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, env=dict(__import__("os").environ, PYTHONPATH="backend:."))
    assert listing.returncode == 0, listing.stdout[-2000:]
    collected = []
    for line in listing.stdout.splitlines():
        if "::" in line and line.startswith("tests/"):
            path, _, name = line.partition("::")
            full = name.split("::")[-1]
            collected.append({"module": path[:-3].replace("/", "."), "name": full, "status": "passed"})
    assert len(collected) > 8000, listing.stdout[-500:]
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


@pytest.fixture(params=["T14", "T16"])
def p8_evidence(request, collected_cases):
    row = next(r for r in rm.ROWS if r["id"] == request.param)
    specs = [{"file": rule[1], "title": "synthetic execution", "status": "passed"}
             for rule in leaf_rules(row["rule"]) if rule[0] == "pw"]
    data = {"pytest": [c.copy() for c in collected_cases if not c["module"].startswith(rm.PROC)],
            "process": [c.copy() for c in collected_cases if c["module"].startswith(rm.PROC)],
            "playwright": specs, "web_ok": True}
    return row, data


def test_p8_rows_require_backend_and_every_browser_file(p8_evidence):
    row, data = p8_evidence
    assert row["cls"] == "zorunlu" and row["kind"] == {"T14": "S", "T16": "S+G"}[row["id"]]
    assert rm.evaluate(row, data)["result"] == PASS
    assert rm.evaluate(row, {**data, "pytest": None})["result"] == NOT
    for spec in data["playwright"]:
        remaining = [s for s in data["playwright"] if s is not spec]
        assert rm.evaluate(row, {**data, "playwright": remaining})["result"] == NOT
        for status, want in (("skipped", NOT), ("failed", FAIL)):
            assert rm.evaluate(row, {**data, "playwright": remaining + [{**spec, "status": status}]})["result"] == want
    for gates in ({"web_ok": False}, {"playwright_port_clash": True}):
        assert rm.evaluate(row, {**data, **gates})["result"] == NOT


def test_p8_rows_require_each_junit_pair_and_retain_failures_when_browser_is_missing(p8_evidence):
    row, data = p8_evidence
    for module, pattern in row["rule"][1][1]:
        source = "process" if module.startswith(rm.PROC) else "pytest"
        cases = data[source]
        hit = [c for c in cases if rm.rule_junit([c], [(module, pattern)], "")["result"] == PASS]
        assert hit
        remaining = [c for c in cases if c not in hit]
        assert rm.evaluate(row, {**data, source: remaining})["result"] == NOT
        for status, want in (("skipped", NOT), ("failed", FAIL)):
            changed = remaining + [{**c, "status": status} for c in hit]
            assert rm.evaluate(row, {**data, source: changed, "playwright": None})["result"] == want


def test_p8_process_source_is_required_only_by_t16(p8_evidence):
    row, data = p8_evidence
    want = NOT if row["id"] == "T16" else PASS
    assert rm.evaluate(row, {**data, "process": None})["result"] == want
    assert rm.evaluate(row, {**data, "process": []})["result"] == want


def test_empty_all_rule_is_not_a_pass():
    assert rm.evaluate({"id": "empty", "rule": ("all",)}, {})["result"] == NOT


def test_the_capacity_port_variable_moves_the_range_and_refuses_a_live_port():
    code = "import sys; sys.path.insert(0, 'scripts/p9'); import capacity; print(capacity.PORTS[0], capacity.PORTS[-1])"
    ok = subprocess.run([sys.executable, "-c", code], cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
                        env=dict(__import__("os").environ, P9_CAPACITY_PORT_FIRST="8950", PYTHONPATH="backend:."))
    assert ok.stdout.split() == ["8950", "8970"], ok.stderr
    for bad in ("8765", "8850", "8860"):
        res = subprocess.run([sys.executable, "-c", code], cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
                             env=dict(__import__("os").environ, P9_CAPACITY_PORT_FIRST=bad, PYTHONPATH="backend:."))
        assert res.returncode != 0 and "live-service" in res.stderr + res.stdout, bad


def test_k07_is_not_a_pass_while_a_limits_cell_says_it_was_never_measured():
    summary = {"rows": {"K07": {"verdict": "pass"}}}
    done = "| Server RSS peak | measured only | no limit | x | N=1000: 5 bytes |"
    assert rm.rule_capacity(summary, 0, "K07", "", done)["result"] == PASS
    assert rm.rule_capacity(summary, 0, "K07", "", done + " not measured yet (run measure)")["result"] == NOT
    assert rm.rule_capacity(summary, 0, "K07", "", None)["result"] == NOT


def test_playwright_exclusion_keeps_the_400_percent_record_out_of_x06(tmp_path):
    specs = pw_file(tmp_path, [{"title": "a11y.spec.ts", "file": "a11y.spec.ts", "suites": [{"title": "X06: reduced motion and the 200% layout", "file": "a11y.spec.ts", "specs": [
        spec("200% tasks", "expected", "a11y.spec.ts"), spec("400% (320x225): recorded, not mandatory", "unexpected", "a11y.spec.ts")]}]}])
    row = next(r for r in rm.ROWS if r["id"] == "X06")
    assert rm.evaluate(row, {"missing": {}, "playwright": specs, "web_ok": True})["result"] == PASS


def test_the_browser_and_capacity_rows_need_a_clean_build_in_the_same_run(tmp_path):
    specs = pw_file(tmp_path, [{"title": "acceptance.spec.ts", "file": "acceptance.spec.ts", "specs": [spec("A: x", "expected")]}])
    row = next(r for r in rm.ROWS if r["id"] == "A")
    for web_ok in (None, False):
        res = rm.evaluate(row, {"missing": {}, "playwright": specs, "web_ok": web_ok})
        assert res["result"] == NOT and "depends on the web stage" in res["note"]
    assert rm.evaluate(row, {"missing": {}, "playwright": specs, "web_ok": True})["result"] == PASS
    cap = next(r for r in rm.capacity_rows() if r["id"] == "K01a")
    assert rm.evaluate(cap, {"missing": {}, "capacity": {"rows": {"K01a": {"verdict": "pass"}}}, "web_ok": False})["result"] == NOT


def test_a_suite_row_fails_on_any_failed_test_or_a_nonzero_exit_even_when_no_matrix_row_names_the_test(tmp_path):
    ok = junit(tmp_path, [("tests.unmapped", "test_a", "passed")])
    bad = junit(tmp_path, [("tests.unmapped", "test_a", "passed"), ("tests.unmapped", "test_b", "failed")])
    suite = next(r for r in rm.ROWS if r["id"] == "suite-pytest")
    assert rm.evaluate(suite, {"missing": {}, "pytest": ok, "stage_ok": {"pytest": True}})["result"] == PASS
    assert rm.evaluate(suite, {"missing": {}, "pytest": bad, "stage_ok": {"pytest": False}})["result"] == FAIL
    assert rm.evaluate(suite, {"missing": {}, "pytest": ok, "stage_ok": {"pytest": False}})["result"] == FAIL  # a collection error shows as the exit code
    assert rm.evaluate(suite, {"missing": {}, "pytest": None})["result"] == NOT
    web = next(r for r in rm.ROWS if r["id"] == "suite-web")
    assert rm.evaluate(web, {"missing": {}, "stage_ok": {"web": True}, "lint": {"warnings": 17, "errors": 0, "baseline": 17}})["result"] == PASS
    assert rm.evaluate(web, {"missing": {}, "stage_ok": {"web": False}})["result"] == FAIL
    assert rm.evaluate(web, {"missing": {}})["result"] == NOT
    pw = next(r for r in rm.ROWS if r["id"] == "suite-playwright")
    specs = pw_file(tmp_path, [{"title": "x.spec.ts", "file": "x.spec.ts", "specs": [spec("one", "expected", "x.spec.ts"), spec("two", "unexpected", "x.spec.ts")]}])
    assert rm.evaluate(pw, {"missing": {}, "playwright": specs, "stage_ok": {"playwright": False}, "web_ok": True})["result"] == FAIL
    assert rm.evaluate(pw, {"missing": {}, "playwright": specs, "stage_ok": {"playwright": None}, "web_ok": True})["result"] == FAIL  # a failed spec is never hidden by a refusal flag


def test_web_verdict_needs_clean_commands_a_summary_line_no_error_and_no_new_warning():
    ok = "Found 17 warnings and 0 errors.\nFinished in 5ms"
    assert rm.web_verdict(True, ok)[1] is True
    assert rm.web_verdict(True, "Found 18 warnings and 0 errors.")[1] is False
    assert rm.web_verdict(True, "Found 3 warnings and 1 error.")[1] is False
    assert rm.web_verdict(False, ok)[1] is False
    lint, good, note = rm.web_verdict(True, "no summary here")
    assert lint is None and good is False and "no summary" in note


def test_the_pure_cleanup_check_sees_a_listener_a_process_of_the_run_and_a_mounted_image():
    needles = ["/tmp/run-x/out", "matrix-x"]
    ps = "100 python something /tmp/run-x/out/pytest-tmp/server.py\n101 other unrelated\n102 ps -A\n103 python run_matrix.py /tmp/run-x/out"
    assert rm.leftover_findings([], ps, "", needles, "999") == ["process 100: python something /tmp/run-x/out/pytest-tmp/server.py"]
    assert rm.leftover_findings([(8950, "7")], "", "", needles, "999")[0].startswith("listeners: 8950")
    assert "disk image" in rm.leftover_findings([], "", "image-path : /tmp/run-x/out/a.sparseimage", needles, "999")[0]
    assert rm.leftover_findings([], "100 x /tmp/run-x/out/y", "", needles, "100") == []  # the runner's own pid
    assert rm.leftover_findings([], ps, "", ["/nowhere"], "999") == []


def test_bind_busy_sees_a_listener_on_every_address_not_only_127_0_0_1():
    import socket
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET, "0.0.0.0"), (socket.AF_INET6, "::1")):
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            sock.bind((host, 0))
            sock.listen(1)
        except OSError:
            sock.close()
            continue  # no IPv6 here
        port = sock.getsockname()[1]
        try:
            assert port in rm.bind_busy([port]), host
        finally:
            sock.close()
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
    free.close()
    assert rm.bind_busy([port]) == []


def test_the_f09_stage_exit_code_and_an_output_folder_inside_the_live_data_directory(tmp_path):
    row = next(r for r in rm.ROWS if r["id"] == "F09")
    passed = junit(tmp_path, [("tests.documents.test_documents", "test_extraction_is_stopped_at_the_production_memory_limit", "passed"),
                              ("tests.documents.test_arxiv_source_archive", "test_the_source_child_is_stopped_at_the_production_memory_limit", "passed")])
    assert rm.evaluate(row, {"missing": {}, "f09": passed, "stage_ok": {"f09": False}})["result"] == FAIL
    assert rm.evaluate(row, {"missing": {}, "f09": passed, "stage_ok": {"f09": True}})["result"] == PASS
    tools = {"uv": "/x", "node": "/x", "npm": "/x"}
    assert any("live data directory" in p for p in rm.refusals(tmp_path, "arm64", [], tools, rm.LIVE_DATA_DIR / "p9-x"))


def test_a_signal_ends_the_stage_tree_and_raises_aborted(tmp_path):
    import time
    run = rm.Run(rm.parse_args([]), tmp_path / "out", "t")
    (tmp_path / "out").mkdir()
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", str(run.out / "detached-stand-in")], start_new_session=True)
    run.proc = proc
    with pytest.raises(rm.Aborted):
        run.abort(15, None)
    for _ in range(50):
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    assert proc.poll() is not None


def test_interrupted_before_detached_child_registration_is_found_and_killed(tmp_path, monkeypatch):
    run = rm.Run(rm.parse_args([]), tmp_path / "out", "interrupted")
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", str(run.out / "detached-stand-in")], start_new_session=True)
    # Inject this owned process table: the workspace sandbox refuses ps, but the real stand-in is still killed.
    ps = f"{proc.pid} {' '.join(proc.args)}\n"
    monkeypatch.setattr(rm, "sh", lambda argv: subprocess.CompletedProcess(argv, 0, ps if argv[0] == "ps" else "", ""))
    try:
        assert any(f"process {proc.pid}:" in x for x in rm.leftover_findings([], ps, "", [str(run.out)], str(__import__("os").getpid())))
        assert run.proc is None  # abort happened before registration
        with pytest.raises(rm.Aborted):
            run.abort(15, None)
        rm.kill_started(run)
        assert proc.wait(timeout=10) != 0
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()


def test_matrix_capacity_commands_use_three_fresh_folders_and_merge_all_three(tmp_path, monkeypatch):
    import capacity
    args = rm.parse_args(["--only", "capacity", "--keep"])
    run = rm.Run(args, tmp_path / "out", "integration")
    run.cap_root, run.cap_out = tmp_path / "root", tmp_path / "capacity"
    run.out.mkdir()
    monkeypatch.setattr(rm, "gate", lambda *a: None)
    monkeypatch.setattr(capacity, "require_arm64", lambda: None)
    monkeypatch.setattr(capacity, "guard_repo", lambda: None)
    monkeypatch.setattr(capacity, "guard_dir", lambda p: Path(p))
    monkeypatch.setattr(capacity, "guard_out", lambda p: Path(p))
    monkeypatch.setattr(capacity, "find_node", lambda: "node")
    monkeypatch.setattr(capacity, "leftover", lambda _: [])
    outputs = []

    def measurements(args, root, out, node, started):
        point = "pdf" if args.pdf else "control" if args.control else "1000"
        outputs.append(out)
        (out / f"{point}-rep1.json").write_text(json.dumps({"point": point, "rep": 1, "errors": [], "started_epoch": 1, "load1": 0}))
    monkeypatch.setattr(capacity, "measure_passes", measurements)

    def stage(name, commands):
        assert name == "capacity"
        for argv, _, _ in commands:
            if argv[2] in ("generate", "pdf-library"):
                continue
            assert capacity.main(argv[2:]) == 0
        run.stages[name] = {}
    monkeypatch.setattr(run, "stage", stage)
    monkeypatch.setattr(run, "call", lambda argv, env, repo, fh: capacity.main(argv[2:]))
    rm.run_stages(args, run, {}, run.out, tmp_path)
    assert len(set(outputs)) == 3
    assert set(json.loads((run.cap_out / "summary.json").read_text())["points"]) == {"1000", "pdf", "control"}


def test_wait_quiet_waits_for_a_low_load_and_gives_up_after_the_limit():
    loads = iter([9.0, 8.0, 3.0, 3.0])
    now = [0.0]
    waited, load, free = rm.wait_quiet(lambda: (next(loads), 0, 0), lambda s: now.__setitem__(0, now[0] + s), lambda: now[0], limit=6.0, max_wait=100)
    assert waited == 30 and load == 3.0 and free == 100.0
    now[0] = 0.0
    waited, load, free = rm.wait_quiet(lambda: (9.0, 0, 0), lambda s: now.__setitem__(0, now[0] + s), lambda: now[0], limit=6.0, max_wait=100)
    assert 100 <= waited < 120 and load == 9.0
    now[0] = 0.0
    frees = iter([20.0, 30.0, 60.0, 60.0])
    waited, load, free = rm.wait_quiet(lambda: (1.0, 0, 0), lambda s: now.__setitem__(0, now[0] + s), lambda: now[0], limit=6.0, max_wait=100, free_memory=lambda: next(frees), min_free=50)
    assert waited == 30 and free == 60.0
    assert rm.STAGES[1] == "f09"


def fake_run(tmp_path, only=None, skip=None, stages=None):
    args = rm.parse_args(([] if not only else ["--only", only]) + ([] if not skip else ["--skip", skip]))
    run = rm.Run(args, tmp_path / "out", "t")
    (tmp_path / "out").mkdir(parents=True, exist_ok=True)
    run.stages = stages or {}
    return run


def test_collect_marks_unwanted_stages_missing_and_reads_the_stage_files(tmp_path):
    run = fake_run(tmp_path, only="playwright,web", stages={"web": {"ok": True}, "playwright": {"ok": True}})
    (tmp_path / "out" / "playwright").mkdir()
    (tmp_path / "out" / "playwright" / "results.json").write_text(json.dumps({"suites": [{"title": "acceptance.spec.ts", "file": "acceptance.spec.ts", "specs": [spec("A: x", "expected")]}]}))
    (tmp_path / "out" / "playwright.log").write_text("all fine")
    data = rm.collect(run)
    assert data["web_ok"] is True and data["playwright"][0]["status"] == "passed"
    assert data["missing"]["install"] == "stage install skipped" and "capacity" in data["missing"]
    assert data["playwright_port_clash"] is False
    rows = {r["id"]: r for r in rm.table(data)}
    assert rows["A"]["result"] == PASS and rows["I01"]["result"] == NOT and rows["K01a"]["result"] == NOT


def test_collect_web_ok_is_true_only_for_a_stage_that_ran_here_and_succeeded(tmp_path):
    for stages, want in (({"web": {"ok": True}}, True), ({"web": {"ok": False}}, False), ({"web": {"ok": None}}, False), ({}, False)):
        run = fake_run(tmp_path, only="web", stages=stages)
        assert rm.collect(run)["web_ok"] is want


def test_collect_sees_an_address_in_use_error_in_the_playwright_log_and_a_refusal_reason(tmp_path):
    run = fake_run(tmp_path, only="playwright", stages={"playwright": {"ok": None, "refused": "fixture ports in use: [8801]"}})
    assert rm.collect(run)["missing"]["playwright"] == "stage playwright refused: fixture ports in use: [8801]"
    run2 = fake_run(tmp_path / "b", only="playwright", stages={"playwright": {"ok": False}})
    (tmp_path / "b" / "out" / "playwright").mkdir(parents=True, exist_ok=True)
    (tmp_path / "b" / "out" / "playwright" / "results.json").write_text('{"suites": []}')
    (tmp_path / "b" / "out" / "playwright.log").write_text("Error: listen EADDRINUSE: address already in use 127.0.0.1:8801")
    assert rm.collect(run2)["playwright_port_clash"] is True


def test_run_stages_runs_the_stages_in_the_order_of_STAGES_with_f09_first():
    import inspect
    source = inspect.getsource(rm.run_stages)
    order = re.findall(r'run\.wanted\("(\w+)"\)', source)
    assert order == list(rm.STAGES[1:])
    assert rm.STAGES[1] == "f09"


def test_images_of_a_run_are_found_by_their_image_path():
    info = ("================================================\nframework : 1\nimage-path : /tmp/other/x.sparseimage\n/dev/disk7 GUID\n/dev/disk7s1 Apple_HFS /Volumes/a\n"
            "================================================\nframework : 1\nimage-path : /tmp/run-x/out/process-tmp/t/deixis-h3.sparseimage\n/dev/disk9 GUID\n/dev/disk9s1 Apple_HFS /tmp/m\n")
    assert rm.images_of_run(info, ["/tmp/run-x/out"]) == ["/dev/disk9"]
    assert rm.images_of_run(info, ["/nowhere"]) == []


def test_a_f09_failure_at_a_busy_load_says_so(tmp_path):
    row = next(r for r in rm.ROWS if r["id"] == "F09")
    failed = junit(tmp_path, [("tests.documents.test_documents", "test_extraction_is_stopped_at_the_production_memory_limit", "failed"),
                              ("tests.documents.test_arxiv_source_archive", "test_the_source_child_is_stopped_at_the_production_memory_limit", "passed")])
    gate = {"waited_s": 1200, "load1_at_start": 9.5, "limit": 4.0}
    res = rm.evaluate(row, {"missing": {}, "f09": failed, "f09_quiet_wait": gate})
    assert res["result"] == FAIL and "load" in res["note"]
    quiet = rm.evaluate(row, {"missing": {}, "f09": failed, "f09_quiet_wait": dict(gate, load1_at_start=2.0)})
    assert quiet["result"] == FAIL and "ran at 1-minute load" not in quiet["note"]


def test_a_stage_child_does_not_inherit_blocked_signals(tmp_path):
    """A SIGTERM-blocking mask inherited across exec made every stage unkillable; the child must start with the handled signals unblocked."""
    import signal
    run = rm.Run(rm.parse_args([]), tmp_path / "out", "t")
    run.handled = [signal.SIGINT, signal.SIGTERM]
    out = tmp_path / "mask.txt"
    code = "import signal,sys; open(sys.argv[1],'w').write(str(sorted(int(s) for s in signal.pthread_sigmask(signal.SIG_BLOCK, []))))"
    with out.open("w") as fh:
        pass
    rc = run.call([sys.executable, "-c", code, str(out)], dict(__import__("os").environ), tmp_path, subprocess.DEVNULL)
    assert rc == 0 and out.read_text() == "[]"
    after = signal.pthread_sigmask(signal.SIG_BLOCK, [])
    assert signal.SIGTERM not in after and signal.SIGINT not in after


GUARD_TESTS = [
    "test_guard_decisions[parent0-200-wait]", "test_guard_decisions[None-200-kill]", "test_guard_decisions[None-50-wait]",
    "test_guard_decisions[parent3-200-kill]", "test_reparented_child_is_orphan_even_when_original_parent_is_alive",
    "test_unreadable_orphan_rss_fails_closed_after_bounded_turns",
    "test_guard_ends_with_child_or_at_absolute_deadline[None-0]", "test_guard_ends_with_child_or_at_absolute_deadline[child1-0]",
    "test_guard_ends_with_child_or_at_absolute_deadline[child2-10]", "test_final_start_time_check_refuses_pid_reuse",
    "test_guard_start_failure_exits_before_any_extraction", "test_guard_readiness_timeout_is_fail_closed_and_reaped",
    "test_early_guard_loss_ends_idle_child_with_distinct_code",
    "test_no_guard_remains_after_child_end_and_stdio_is_devnull[normal]", "test_no_guard_remains_after_child_end_and_stdio_is_devnull[crash]",
    "test_no_guard_remains_after_child_end_and_stdio_is_devnull[timeout]", "test_no_guard_remains_after_child_end_and_stdio_is_devnull[child_sigkill]",
    "test_parent_launchers_pass_their_identity", "test_pdf_launcher_passes_parent_start_time_before_child_work",
    "test_guard_failure_is_a_clear_error_in_every_parent_api[pdf]", "test_guard_failure_is_a_clear_error_in_every_parent_api[ocr]",
    "test_guard_failure_is_a_clear_error_in_every_parent_api[jats]", "test_arxiv_guard_exit_maps_to_watch_loss"]


def test_f04_orphan_is_not_measured_when_any_one_named_guard_test_is_missing():
    patterns = next(r["rule"][1] for r in rm.ROWS if r["id"] == "F04-orphan")
    process = ["test_extraction_child_is_ended_by_its_own_lifetime", "test_extraction_child_lifetime_disabled_control",
               "test_lifetime_observer_rejects_normal_completion", "test_orphan_memory_guard_stops_gil_holding_pdf_by_sigkill",
               "test_orphan_memory_guard_disabled_control", "test_orphan_guard_parent_alive_preserves_pdf_memory_failure"]
    cases = [{"module": rm.PROC + "test_p9_children", "name": n, "status": "passed"} for n in process]
    cases += [{"module": "tests.hardening.test_child_guard", "name": n, "status": "passed"} for n in GUARD_TESTS]
    assert rm.rule_junit(cases, patterns, "x")["result"] == PASS
    for i in range(len(cases)):
        assert rm.rule_junit(cases[:i] + cases[i + 1:], patterns, "x")["result"] == NOT, cases[i]
