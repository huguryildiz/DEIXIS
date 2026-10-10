#!/usr/bin/env python3
"""P9 H8: the whole automatic acceptance matrix (every S, G and A row of plan section 4) in one command.

    scripts/p9/run_matrix.sh                       # all stages, then the table
    scripts/p9/run_matrix.sh --only pytest,process # a partial run; the other rows print "ölçülmedi"
    scripts/p9/run_matrix.sh --self-test           # checks of the row mapping, no stage is started

Stages, in order: preflight, f09 (H0b, H0c), process (H2, H3, H4), install (H1), pytest, web (build and lint), playwright (A to G,
X01 to X06), capacity (H5). The wall-clock stages (f09, process, capacity) first wait up to 10 minutes for a 1-minute load below QUIET_LOAD and
record the load they started at; the process tests run before the parallel pytest stage so its workers do not load them. Each writes its log under the output folder. After the last one the script lists what a
run could leave behind (listeners on its ports, processes naming its folders, a mounted test disk image), then writes
`matrix.json` and `matrix.md` and prints the table. A row is geçti only when its evidence ran and passed; a skipped or missing
stage, a skipped test and a test pattern that matches nothing all give ölçülmedi, never a pass.

Isolation: no model call, no provider call (the installer downloads packages, nothing else leaves the machine). The live service
(port 8765), the live data directory and the real keychain are never touched; ports 8950 to 8970 are the script's own, and the
Playwright specs keep their fixed fixture ports (8777 to 8824), which the script checks are free first.

Exit codes: 0 every mandatory row is geçti, 1 a mandatory row is not, 2 refused (nothing was started). Standard library only.
"""

from __future__ import annotations

import argparse
import datetime
import fnmatch
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Optional

REPO = Path(__file__).resolve().parents[2]
LIVE_DATA_DIR = Path.home() / "Library" / "Application Support" / "DEIXIS"
OWN_PORTS = range(8950, 8971)
PLAYWRIGHT_PORTS = range(8777, 8825)
LIVE_PORTS = {8765} | set(range(8858, 8865))
LINT_BASELINE = 17
STAGES = ("preflight", "f09", "process", "install", "pytest", "web", "playwright", "capacity")
GATED = ("f09", "process", "capacity")  # wall-clock stages: they wait for a quiet machine first (the pytest stage's own workers keep the 1-minute load high afterwards)
QUIET_LOAD = 4.0  # F09 grows a child to 1 GiB against a 90 s clock; under heavy load or swap it times out first (it failed at load 6 to 11, passed at 4.4; same limit as capacity.LOAD_LIMIT)
QUIET_WAIT_SECONDS = 600
QUIET_FREE_MEMORY = 50  # percent; F09 failed twice at a 1-minute load below 4 while memory was tight (swap in use), and passed with 69% free
KEYRING_NULL = "keyring.backends.null.Keyring"
RESULTS = ("geçti", "geçmedi", "ölçülmedi", "desteklenmiyor")
CLASSES = ("zorunlu", "isteğe bağlı", "yalnız ölçüm")
PASS, FAIL, NOT, UNSUPPORTED = RESULTS

# ---- the row table -----------------------------------------------------------------------------------------------------
# Every row of plan section 4. `rule` says where the evidence comes from:
#   ("install", id)                      the row of the same id in install_check's results.json
#   ("junit", [(module, name_glob), ...][, sources])  every pair must match at least one test, and every matched test must pass;
#                                        `sources` limits the junit files read (default pytest, process and f09)
#   ("pw", file, title_regex[, exclude_regex])  Playwright specs in that file whose full title matches (and not the exclusion)
#   ("cap", id)                          a row of capacity.py's summary.json (the class comes from capacity.FROZEN)
#   ("static", reason)                   not run by this script; the record links the earlier measurement
#   ("all", rule, ...)                  every child rule must pass; failures outrank missing or skipped evidence
# `execution` and `data` are the two separate fields of plan section 4 rule 4.

PROC = "tests.process."
ROWS: list[dict[str, Any]] = [
    {"id": "I01", "claim": "uv sync, npm ci and npm run build finish clean in a clean export", "cls": "zorunlu", "kind": "G", "execution": "real process", "data": "no data", "rule": ("install", "I01")},
    {"id": "I02", "claim": "serve starts, /api/health ok, the question box renders, a stop frees the port", "cls": "zorunlu", "kind": "G", "execution": "real process, real Chrome", "data": "empty library", "rule": ("install", "I02")},
    {"id": "I03", "claim": "busy port: one clear message, exit 2, no second writer", "cls": "zorunlu", "kind": "G", "execution": "real process", "data": "empty library", "rule": ("install", "I03")},
    {"id": "I04", "claim": "no apps/web/dist: the API starts and warns", "cls": "zorunlu", "kind": "G", "execution": "real process", "data": "empty library", "rule": ("install", "I04")},
    {"id": "I05", "claim": "unwritable data directory: start fails, exit not 0, nothing left behind", "cls": "zorunlu", "kind": "G", "execution": "real process", "data": "empty library", "rule": ("install", "I05")},
    {"id": "I06", "claim": "two processes on one data directory: second is not_owner, takes over when the owner is killed", "cls": "zorunlu", "kind": "G", "execution": "real process", "data": "synthetic records, scripted model", "rule": ("junit", [(PROC + "test_p9_crash", "test_i06*")])},
    {"id": "I07", "claim": "isolated environment: model connections show not ready with a reason", "cls": "zorunlu", "kind": "G", "execution": "real process", "data": "empty library", "rule": ("install", "I07")},
    {"id": "I08", "claim": "a clean macOS user account follows the README", "cls": "isteğe bağlı", "kind": "E", "execution": "by hand", "data": "real machine", "rule": ("static", "E row, not run by the script; not done in H1, so no second-user claim")},
    {"id": "install-keyring", "claim": "the install check's keychain isolation held (the real keychain was never read)", "cls": "zorunlu", "kind": "G", "execution": "real process", "data": "no data", "rule": ("install", "keyring")},
    {"id": "install-cleanup", "claim": "the install check left no process, port or work folder behind", "cls": "zorunlu", "kind": "G", "execution": "real process", "data": "no data", "rule": ("install", "cleanup")},
    {"id": "F01", "claim": "SIGKILL during a model step: outcome_unknown, run paused, one resend, one published answer", "cls": "zorunlu", "kind": "G", "execution": "real process", "data": "synthetic records, scripted model", "rule": ("junit", [(PROC + "test_p9_crash", "test_f01*")])},
    {"id": "F02", "claim": "SIGKILL during a PDF download or passage write: no half record", "cls": "zorunlu", "kind": "G", "execution": "real process", "data": "synthetic records, scripted model", "rule": ("junit", [(PROC + "test_p9_files", "test_f02*")])},
    {"id": "F03", "claim": "SIGKILL while a backup is taken: before the manifest it is refused, after it restores equal", "cls": "zorunlu", "kind": "G", "execution": "real process", "data": "synthetic records", "rule": ("junit", [(PROC + "test_p9_backup_kill", "test_f03*"), (PROC + "test_p9_restore_process", "test_f03*")])},
    {"id": "F04", "claim": "SIGTERM and Ctrl-C end the server within the bound, with a held model call or extraction", "cls": "zorunlu", "kind": "G", "execution": "real process", "data": "synthetic records, scripted model", "rule": ("junit", [(PROC + "test_p9_shutdown", "test_f04*")])},
    {"id": "F04-orphan", "claim": "orphan extraction: SIGALRM lifetime and SIGKILL resident guard, negative controls and guard cleanup", "cls": "zorunlu", "kind": "G", "execution": "real processes, kqueue exit status", "data": "synthetic GIL-holding PDF", "rule": ("junit", [
        (PROC + "test_p9_children", "test_extraction_child_is_ended_by_its_own_lifetime"),
        (PROC + "test_p9_children", "test_extraction_child_lifetime_disabled_control"),
        (PROC + "test_p9_children", "test_lifetime_observer_rejects_normal_completion"),
        (PROC + "test_p9_children", "test_orphan_memory_guard_stops_gil_holding_pdf_by_sigkill"),
        (PROC + "test_p9_children", "test_orphan_memory_guard_disabled_control"),
        (PROC + "test_p9_children", "test_orphan_guard_parent_alive_preserves_pdf_memory_failure"),
        ("tests.hardening.test_child_guard", "test_guard_decisions[parent0-200-wait]"),
        ("tests.hardening.test_child_guard", "test_guard_decisions[None-200-kill]"),
        ("tests.hardening.test_child_guard", "test_guard_decisions[None-50-wait]"),
        ("tests.hardening.test_child_guard", "test_guard_decisions[parent3-200-kill]"),
        ("tests.hardening.test_child_guard", "test_reparented_child_is_orphan_even_when_original_parent_is_alive"),
        ("tests.hardening.test_child_guard", "test_unreadable_orphan_rss_fails_closed_after_bounded_turns"),
        ("tests.hardening.test_child_guard", "test_guard_ends_with_child_or_at_absolute_deadline[None-0]"),
        ("tests.hardening.test_child_guard", "test_guard_ends_with_child_or_at_absolute_deadline[child1-0]"),
        ("tests.hardening.test_child_guard", "test_guard_ends_with_child_or_at_absolute_deadline[child2-10]"),
        ("tests.hardening.test_child_guard", "test_final_start_time_check_refuses_pid_reuse"),
        ("tests.hardening.test_child_guard", "test_guard_start_failure_exits_before_any_extraction"),
        ("tests.hardening.test_child_guard", "test_guard_readiness_timeout_is_fail_closed_and_reaped"),
        ("tests.hardening.test_child_guard", "test_early_guard_loss_ends_idle_child_with_distinct_code"),
        ("tests.hardening.test_child_guard", "test_no_guard_remains_after_child_end_and_stdio_is_devnull[normal]"),
        ("tests.hardening.test_child_guard", "test_no_guard_remains_after_child_end_and_stdio_is_devnull[crash]"),
        ("tests.hardening.test_child_guard", "test_no_guard_remains_after_child_end_and_stdio_is_devnull[timeout]"),
        ("tests.hardening.test_child_guard", "test_no_guard_remains_after_child_end_and_stdio_is_devnull[child_sigkill]"),
        ("tests.hardening.test_child_guard", "test_parent_launchers_pass_their_identity"),
        ("tests.hardening.test_child_guard", "test_pdf_launcher_passes_parent_start_time_before_child_work"),
        ("tests.hardening.test_child_guard", "test_guard_failure_is_a_clear_error_in_every_parent_api[pdf]"),
        ("tests.hardening.test_child_guard", "test_guard_failure_is_a_clear_error_in_every_parent_api[ocr]"),
        ("tests.hardening.test_child_guard", "test_guard_failure_is_a_clear_error_in_every_parent_api[jats]"),
        ("tests.hardening.test_child_guard", "test_arxiv_guard_exit_maps_to_watch_loss")])},
    {"id": "F05", "claim": "full disk: a clear refusal, the database is not damaged", "cls": "isteğe bağlı", "kind": "G", "execution": "real process on a 16 MiB disk image", "data": "synthetic records", "rule": ("junit", [(PROC + "test_disk_full", "test_*"), ("tests.hardening.test_p9_faults_documents", "test_o12*")])},
    {"id": "F06", "claim": "damaged or truncated library and unknown migration: start refused, data unchanged", "cls": "zorunlu", "kind": "G", "execution": "real process", "data": "synthetic records", "rule": ("junit", [(PROC + "test_library_open_faults", "test_*"), ("tests.hardening.test_p9_faults_documents", "test_o8_*"), (PROC + "test_p9_restore_process", "test_b03*")])},
    {"id": "F07", "claim": "provider timeout, 5xx, malformed or empty body, 429, slow answer, zero results: stored status and visible reason", "cls": "zorunlu", "kind": "S", "execution": "automatic test", "data": "mocked providers", "rule": ("junit", [("tests.hardening.test_p9_faults_providers", "test_p[1245]_*"), ("tests.providers.test_providers", "test_zero_results_is_distinct_from_failure"), ("tests.providers.test_providers", "test_short_rate_limit_is_retried_and_counted"), ("tests.providers.test_providers", "test_long_rate_limit_is_not_retried"), ("tests.candidates.test_candidate_flow", "test_d18_failures_continue_and_unknown_delivery_cannot_become_open")])},
    {"id": "F08", "claim": "encrypted, zero-page, huge, corrupt PDF and over-limit upload: a code and a visible reason", "cls": "zorunlu", "kind": "S", "execution": "automatic test", "data": "synthetic PDFs", "rule": ("junit", [("tests.hardening.test_p9_faults_documents", "test_d*")])},
    {"id": "F09", "claim": "the production 1 GiB watcher stops an extraction that passes the limit", "cls": "zorunlu", "kind": "G", "execution": "real child process at the production limit", "data": "scaled synthetic input", "rule": ("junit", [("tests.documents.test_documents", "test_extraction_is_stopped_at_the_production_memory_limit"), ("tests.documents.test_arxiv_source_archive", "test_the_source_child_is_stopped_at_the_production_memory_limit")], ("f09",))},
    {"id": "F10", "claim": "a backup taken while a run is held and a writer writes restores equal", "cls": "zorunlu", "kind": "G", "execution": "real process", "data": "synthetic records, scripted model", "rule": ("junit", [(PROC + "test_p9_restore_process", "test_f10*")])},
    {"id": "B01", "claim": "backup into an empty folder restores every table, file and view equal", "cls": "zorunlu", "kind": "S+G", "execution": "automatic test, real process", "data": "synthetic records", "rule": ("junit", [("tests.hardening.test_p9_restore_matrix", "test_b01_*"), ("tests.hardening.test_p9_restore_matrix", "test_a_restored_library_shows_the_model_connection*")])},
    {"id": "B01n", "claim": "negative restores (full target, wrong file, no manifest, ...) change nothing", "cls": "zorunlu", "kind": "S", "execution": "automatic test", "data": "synthetic records", "rule": ("junit", [("tests.hardening.test_p9_restore_matrix", "test_b01n_*")])},
    {"id": "B02", "claim": "today's code opens a restored copy of the owner's own library", "cls": "isteğe bağlı", "kind": "G", "execution": "real process on a copy", "data": "real library", "rule": ("static", "needs the owner's library and consent; not opened by this script (tooling tests run in the pytest stage)")},
    {"id": "B03", "claim": "a library with an unknown migration id is refused before any write", "cls": "zorunlu", "kind": "G", "execution": "automatic test, real process", "data": "synthetic records", "rule": ("junit", [("tests.hardening.test_p9_restore_matrix", "test_b03_*"), (PROC + "test_p9_restore_process", "test_b03*")])},
    {"id": "D01-D06", "claim": "the six daily-use defects of H7 stay closed", "cls": "isteğe bağlı", "kind": "S", "execution": "automatic test", "data": "synthetic records", "rule": ("junit", [("tests.hardening.test_p9_h7_run_line", "test_*"), ("tests.hardening.test_p9_h7_savepoint", "test_*"), ("tests.hardening.test_p9_h7_test_names", "test_*"), ("tests.hardening.test_p9_h7_torn_upload", "test_*"), ("tests.hardening.test_p9_h7_zotero_disk", "test_*")])},
    {"id": "T14", "claim": "review results stay separate, inputs are immutable, stale reasons are shown, and only the user's checked apply save changes main text; candidates included", "cls": "zorunlu", "kind": "S", "execution": "automatic test, automatic browser test", "data": "synthetic records, scripted model", "rule": ("all",
        ("junit", [
            ("tests.review.test_review_snapshot", "test_*"),
            ("tests.review.test_review_stale", "test_*"),
            ("tests.review.test_review_store", "test_*"),
            ("tests.review.test_review_migration", "test_*"),
            ("tests.review.test_review_separation", "test_*"),
            ("tests.review.test_review_run", "test_*"),
            ("tests.review.test_review_flow", "test_*"),
            ("tests.review.test_review_api", "test_*"),
            ("tests.review.test_review_lifecycle_guards", "test_real_worker_api_lifecycle_denies_every_other_write_and_keeps_all_row_hashes[normal]"),
            ("tests.review.test_review_lifecycle_guards", "test_real_worker_api_lifecycle_denies_every_other_write_and_keeps_all_row_hashes[internal_error]"),
            ("tests.review.test_review_lifecycle_guards", "test_real_worker_api_lifecycle_denies_every_other_write_and_keeps_all_row_hashes[invalid_output]"),
            ("tests.review.test_review_lifecycle_guards", "test_real_worker_api_lifecycle_denies_every_other_write_and_keeps_all_row_hashes[cancelled]"),
            ("tests.review.test_review_lifecycle_guards", "test_cancel_with_waiting_person_file_matches_nonreview_run_end_followup"),
            ("tests.review.test_review_decision_requests", "test_*"),
            ("tests.review.test_review_read_model_b3", "test_*"),
            ("tests.review.test_review_candidate_contract", "test_*"),
            ("tests.review.test_review_candidate_snapshot", "test_*"),
            ("tests.review.test_review_candidate_stale", "test_*"),
            ("tests.review.test_review_candidate_planner", "test_*"),
            ("tests.review.test_review_candidate_api", "test_*"),
            ("tests.review.test_review_candidate_guards", "test_candidate_real_worker_api_denies_other_writes_and_preserves_nonempty_candidate_tables[normal]"),
            ("tests.review.test_review_candidate_guards", "test_candidate_real_worker_api_denies_other_writes_and_preserves_nonempty_candidate_tables[internal_error]"),
            ("tests.review.test_review_candidate_guards", "test_candidate_real_worker_api_denies_other_writes_and_preserves_nonempty_candidate_tables[invalid_output]"),
            ("tests.review.test_review_candidate_guards", "test_candidate_real_worker_api_denies_other_writes_and_preserves_nonempty_candidate_tables[cancelled]"),
            ("tests.review.test_review_candidate_preservation", "test_*"),
            ("tests.review.test_review_candidate_backup", "test_*")]),
        ("pw", "review.spec.ts", r"."),
        ("pw", "candidate-review.spec.ts", r"."))},
    {"id": "T16", "claim": "follow-up shows missed time, catch-up is bounded, and records are announced once per research within the stored identity limits, including kill and restart", "cls": "zorunlu", "kind": "S+G", "execution": "automatic test, real process, automatic browser test", "data": "synthetic records, scripted model, mocked providers", "rule": ("all",
        ("junit", [
            ("tests.watch.test_watch_migration", "test_*"),
            ("tests.watch.test_watch_api", "test_*"),
            ("tests.watch.test_watch_check", "test_*"),
            ("tests.watch.test_watch_identity", "test_*"),
            ("tests.watch.test_watch_recovery", "test_*"),
            ("tests.watch.test_watch_separation", "test_*"),
            ("tests.watch.test_watch_schedule_migration", "test_*"),
            ("tests.watch.test_watch_scheduler", "test_*"),
            ("tests.watch.test_watch_scheduler_lifespan", "test_*"),
            ("tests.watch.test_watch_process_driver", "test_*"),
            (PROC + "test_watch_restart", "test_closed_across_due_period_one_catchup_one_item"),
            (PROC + "test_watch_restart", "test_kill_during_catchup_request_recovery_unknown_not_resent_on_resume"),
            (PROC + "test_watch_restart", "test_kill_after_read_before_completion_resume_publishes_once_without_request"),
            (PROC + "test_watch_restart", "test_further_restart_same_answers_before_next_due_no_duplicate"),
            ("tests.watch.test_followup_count", "test_*")]),
        ("pw", "followup.spec.ts", r"."))},
    {"id": "suite-pytest", "claim": "the default pytest suite: exit 0 and no failed or errored test, mapped to a row or not", "cls": "zorunlu", "kind": "S", "execution": "automatic test", "data": "synthetic records, scripted model", "rule": ("suite", "pytest")},
    {"id": "suite-process", "claim": "every process test (-m process): exit 0 and no failed or errored test", "cls": "zorunlu", "kind": "G", "execution": "real process", "data": "synthetic records, scripted model", "rule": ("suite", "process")},
    {"id": "suite-web", "claim": "npm run build exits 0 and npm run lint has no error and no warning above the baseline", "cls": "zorunlu", "kind": "S", "execution": "build and lint", "data": "no data", "rule": ("suite", "web")},
    {"id": "suite-playwright", "claim": "the whole Playwright suite: exit 0 and no failed spec, mapped to a row or not", "cls": "zorunlu", "kind": "S", "execution": "automatic browser test", "data": "synthetic records, scripted model", "rule": ("suite", "playwright")},
    {"id": "suite-capacity", "claim": "every capacity command exited 0 (a leftover process makes `measure` exit 3)", "cls": "zorunlu", "kind": "G", "execution": "real process, real Chrome", "data": "synthetic records", "rule": ("suite", "capacity")},
    {"id": "A", "claim": "an answer citation opens the stored passage", "cls": "zorunlu", "kind": "S", "execution": "automatic browser test", "data": "synthetic records, scripted model", "rule": ("pw", "acceptance.spec.ts", r"(^|\s)A: ")},
    {"id": "B", "claim": "abstract-only source labelled as abstract, no invented page", "cls": "zorunlu", "kind": "S", "execution": "automatic browser test", "data": "synthetic records, scripted model", "rule": ("pw", "acceptance.spec.ts", r"(^|\s)B: ")},
    {"id": "C", "claim": "preprint and published version stay separate", "cls": "zorunlu", "kind": "S", "execution": "automatic browser test", "data": "synthetic records, scripted model", "rule": ("pw", "acceptance.spec.ts", r"(^|\s)C: ")},
    {"id": "D", "claim": "a misleading keyword is excluded and the reason stays", "cls": "zorunlu", "kind": "S", "execution": "automatic browser test", "data": "synthetic records, scripted model", "rule": ("pw", "acceptance.spec.ts", r"(^|\s)D: ")},
    {"id": "E", "claim": "provider quota and model failure stay visible, not zero results", "cls": "zorunlu", "kind": "S", "execution": "automatic browser test", "data": "synthetic records, scripted model", "rule": ("pw", "acceptance.spec.ts", r"(^|\s)E: ")},
    {"id": "F", "claim": "reload and backend restart keep the same state", "cls": "zorunlu", "kind": "G", "execution": "automatic browser test, real process", "data": "synthetic records, scripted model", "rule": ("pw", "acceptance.spec.ts", r"(^|\s)F: ")},
    {"id": "G", "claim": "instructions inside a PDF or abstract change nothing", "cls": "zorunlu", "kind": "S", "execution": "automatic browser test", "data": "synthetic records, scripted model", "rule": ("pw", "acceptance.spec.ts", r"(^|\s)G: ")},
    {"id": "X01-X04", "claim": "axe scan, 26 screens, light and dark, 1280 and 390 px: no serious or critical finding", "cls": "zorunlu", "kind": "G", "execution": "automatic browser test, real Chrome", "data": "synthetic records, scripted model", "rule": ("pw", "a11y.spec.ts", r"X01-X04")},
    {"id": "X05", "claim": "A to G by keyboard; visible focus; Escape returns focus", "cls": "zorunlu", "kind": "S", "execution": "automatic browser test", "data": "synthetic records, scripted model", "rule": ("pw", "a11y.spec.ts", r"X05")},
    {"id": "X06", "claim": "reduced motion and the 200% layout", "cls": "zorunlu", "kind": "S", "execution": "automatic browser test", "data": "synthetic records, scripted model", "rule": ("pw", "a11y.spec.ts", r"X06", r"400%")},
    {"id": "X07", "claim": "VoiceOver, three flows", "cls": "isteğe bağlı", "kind": "E", "execution": "by hand", "data": "real machine", "rule": ("static", "E row (VoiceOver), not run by the script; not measured in H6")},
    {"id": "R01", "claim": "a report on a fresh corpus with a real model (R1 to R11)", "cls": "isteğe bağlı", "kind": "M", "execution": "real model", "data": "real corpus", "rule": ("static", "M row, H9 not run")},
    {"id": "R02", "claim": "a real model call is resent once after SIGKILL", "cls": "isteğe bağlı", "kind": "M", "execution": "real model", "data": "real corpus", "rule": ("static", "M row, H10 not run")},
]
CLEANUP_ROW = {"id": "cleanup", "claim": "nothing the run started is left running or mounted", "cls": "zorunlu", "kind": "G", "execution": "real process", "data": "no data", "rule": ("static", "")}
CAP_CLASS = {"mandatory": "zorunlu", "measure only": "yalnız ölçüm"}


def capacity_rows() -> list[dict[str, Any]]:
    """K01 to K07 from capacity.FROZEN (its class is the only copy)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import capacity  # noqa: PLC0415  (stdlib-only at import time)
    out = []
    for rid, spec in capacity.FROZEN["rows"].items():
        out.append({"id": rid, "claim": spec["what"], "cls": CAP_CLASS[spec["class"]], "kind": "G", "execution": "real process, real Chrome",
                    "data": "synthetic records", "rule": ("cap", rid)})
    return out


def rows_ordered() -> list[dict[str, Any]]:
    """Plan order; the capacity rows go in front of the A to G browser rows."""
    i = next(n for n, r in enumerate(ROWS) if r["id"] == "A")
    return ROWS[:i] + capacity_rows() + ROWS[i:]


# ---- evidence rules (pure) ---------------------------------------------------------------------------------------------


def row_result(result: str, evidence: str = "", note: str = "") -> dict[str, str]:
    return {"result": result, "evidence": evidence, "note": note}


def junit_cases(paths: list[Path]) -> list[dict[str, str]]:
    cases = []
    for path in paths:
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError):
            continue
        for tc in root.iter("testcase"):
            status = "passed"
            if tc.find("failure") is not None or tc.find("error") is not None:
                status = "failed"
            elif tc.find("skipped") is not None:
                status = "skipped"
            cases.append({"module": tc.get("classname", ""), "name": tc.get("name", ""), "status": status})
    return cases


def rule_junit(cases: Optional[list[dict[str, str]]], patterns: list[tuple[str, str]], missing_reason: str) -> dict[str, str]:
    if cases is None:
        return row_result(NOT, "", missing_reason)
    matched, notes = [], []
    for module, glob in patterns:
        # A pattern without a wildcard that names a parameter set ("name[param]") must match that exact case; others ignore the parameters
        hit = [c for c in cases if c["module"] == module
               and (c["name"] == glob if "[" in glob and "*" not in glob else fnmatch.fnmatchcase(re.sub(r"\[.*\]$", "", c["name"]), glob))]
        if not hit:
            notes.append("no test matches %s::%s" % (module, glob))
        matched.extend(hit)
    failed = [c for c in matched if c["status"] == "failed"]
    skipped = [c for c in matched if c["status"] == "skipped"]
    evidence = "%d tests (%d passed)" % (len(matched), sum(c["status"] == "passed" for c in matched))
    if failed:
        return row_result(FAIL, evidence, "failed: " + ", ".join(sorted({c["name"] for c in failed})[:4]))
    if notes or skipped:
        extra = notes + (["%d skipped" % len(skipped)] if skipped else [])
        return row_result(NOT, evidence, "; ".join(extra))
    return row_result(PASS, evidence)


def playwright_specs(path: Path) -> Optional[list[dict[str, str]]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    specs: list[dict[str, str]] = []

    def walk(suite: dict[str, Any], titles: list[str]) -> None:
        here = titles + ([suite["title"]] if suite.get("title") and not suite.get("file") == suite.get("title") else [])
        for spec in suite.get("specs", []):
            statuses = []
            for test in spec.get("tests", []):
                results = test.get("results", [])
                if test.get("status") in ("unexpected", "flaky"):
                    statuses.append("failed")
                elif test.get("expectedStatus") == "failed" or not results or test.get("status") == "skipped":
                    statuses.append("skipped")
                elif test.get("status") == "expected" and results[-1].get("status") == "passed":
                    statuses.append("passed")
                else:
                    statuses.append("failed")
            if statuses and all(s == "passed" for s in statuses):
                status = "passed"
            elif not statuses or ("skipped" in statuses and "failed" not in statuses):
                status = "skipped"
            else:
                status = "failed"
            specs.append({"file": Path(spec.get("file") or suite.get("file") or "").name, "title": " ".join(here + [spec.get("title", "")]), "status": status})
        for child in suite.get("suites", []):
            walk(child, here)

    for suite in data.get("suites", []):
        walk(suite, [])
    return specs


def rule_playwright(specs: Optional[list[dict[str, str]]], file: str, regex: str, missing_reason: str, exclude: Optional[str] = None) -> dict[str, str]:
    if specs is None:
        return row_result(NOT, "", missing_reason)
    hit = [s for s in specs if s["file"] == file and re.search(regex, s["title"]) and not (exclude and re.search(exclude, s["title"]))]
    if not hit:
        return row_result(NOT, "0 specs", "no spec in %s matches %s" % (file, regex))
    failed = [s for s in hit if s["status"] == "failed"]
    skipped = [s for s in hit if s["status"] == "skipped"]
    evidence = "%d specs (%d passed)" % (len(hit), sum(s["status"] == "passed" for s in hit))
    if failed:
        return row_result(FAIL, evidence, "failed: " + "; ".join(s["title"][:70] for s in failed[:3]))
    if skipped:
        return row_result(NOT, evidence, "%d skipped" % len(skipped))
    return row_result(PASS, evidence)


def rule_install(results: Optional[dict[str, Any]], rid: str, missing_reason: str) -> dict[str, str]:
    if results is None:
        return row_result(NOT, "", missing_reason)
    for row in results.get("rows", []):
        if row.get("id") == rid:
            res = {"pass": PASS, "fail": FAIL}.get(row.get("result"), NOT)
            return row_result(res, "install_check %s" % (results.get("commit", "")[:10]), "" if res == PASS else str(row.get("result")))
    return row_result(NOT, "", "install_check has no row %s" % rid)


def rule_capacity(summary: Optional[dict[str, Any]], limits_code: Optional[int], rid: str, missing_reason: str, limits_text: Optional[str] = None) -> dict[str, str]:
    if summary is None:
        return row_result(NOT, "", missing_reason)
    row = summary.get("rows", {}).get(rid)
    if row is None:
        return row_result(NOT, "", "summary.json has no row %s" % rid)
    verdict = row.get("verdict")
    evidence = "capacity summary, %s" % verdict
    if rid == "K07":
        if limits_code is None:
            return row_result(NOT, evidence, "the limits command did not run")
        if limits_code != 0:
            return row_result(FAIL, evidence, "capacity.py limits exited %d" % limits_code)
        if limits_text is None or "not measured yet" in limits_text:
            return row_result(NOT, evidence, "the limits table has cells that were never measured (judge_limits counts any text as filled)")
    if verdict in ("pass", "measured"):
        return row_result(PASS, evidence, "ran under parallel load (a repetition started or ended at load >= 4)" if summary.get("under_parallel_load") else "")
    if verdict == "fail":
        return row_result(FAIL, evidence)
    return row_result(NOT, evidence, "verdict %s" % verdict)


def rule_suite(name: str, data: dict[str, Any], missing_reason: str) -> dict[str, str]:
    """One mandatory row per stage: its exit code and every failed test count, whether or not a test belongs to a matrix row."""
    ok = data.get("stage_ok", {}).get(name)
    if name in ("pytest", "process"):
        cases = data.get(name)
        if cases is None:
            return row_result(NOT, "", missing_reason)
        failed = sum(c["status"] == "failed" for c in cases)
        skipped = sum(c["status"] == "skipped" for c in cases)
        evidence = "%d tests, %d failed, %d skipped" % (len(cases), failed, skipped)
        if failed or ok is False:
            return row_result(FAIL, evidence, "%d failed or errored%s" % (failed, "; exit code not 0" if ok is False else ""))
        return row_result(PASS if cases and ok else NOT, evidence, "" if cases and ok else "no tests or no exit code")
    if name == "playwright":
        specs = data.get("playwright")
        if specs is None:
            return row_result(NOT, "", missing_reason)
        failed = sum(sp["status"] == "failed" for sp in specs)
        skipped = sum(sp["status"] == "skipped" for sp in specs)
        evidence = "%d specs, %d failed, %d skipped" % (len(specs), failed, skipped)
        if failed or ok is False:
            return row_result(FAIL, evidence, "%d failed%s" % (failed, "; exit code not 0" if ok is False else ""))
        measured = bool(specs) and not skipped and ok is True
        return row_result(PASS if measured else NOT, evidence, "" if measured else "skipped or absent execution evidence, or the stage did not finish")
    if ok is None:
        return row_result(NOT, "", missing_reason)
    detail = data.get("lint")
    evidence = ("lint %d warnings, %d errors (baseline %d)" % (detail["warnings"], detail["errors"], detail["baseline"])) if detail and name == "web" else ""
    return row_result(PASS if ok else FAIL, evidence, "" if ok else "a command exited nonzero or lint is above the baseline")


def evaluate(row: dict[str, Any], data: dict[str, Any]) -> dict[str, str]:
    """`data` holds what the stages produced; a stage that did not run leaves its key out (None)."""
    kind = row["rule"][0]
    missing = lambda stage: data.get("missing", {}).get(stage, "stage %s did not run" % stage)  # noqa: E731
    if kind == "all":
        results = [evaluate({**row, "rule": rule}, data) for rule in row["rule"][1:]]
        if not results:
            return row_result(NOT, "", "no evidence rules")
        result = next((status for status in (FAIL, NOT, UNSUPPORTED) if any(r["result"] == status for r in results)), PASS)
        return row_result(result, "; ".join(r["evidence"] for r in results if r["evidence"]),
                          "; ".join(r["note"] for r in results if r["note"]))
    if kind == "static":
        return row_result(NOT, "", row["rule"][1])
    if kind == "install":
        res = rule_install(data.get("install"), row["rule"][1], missing("install"))
        if res["result"] == PASS and data.get("stage_ok", {}).get("install") is False:
            return row_result(FAIL, res["evidence"], "install_check exited nonzero although its row says pass")
        return res
    if kind == "junit":
        sources = row["rule"][2] if len(row["rule"]) > 2 else ("pytest", "process", "f09")
        cases: Optional[list[dict[str, str]]] = None
        reasons = []
        for key in sources:
            if data.get(key) is not None:
                cases = (cases or []) + data[key]
            else:
                reasons.append(missing(key))
        res = rule_junit(cases, row["rule"][1], "; ".join(reasons))
        if row["id"] == "F09" and res["result"] == PASS and data.get("stage_ok", {}).get("f09") is False:
            res = row_result(FAIL, res["evidence"], "the f09 stage exited nonzero")
        gate = data.get("f09_quiet_wait")
        if row["id"] == "F09" and gate and (gate["load1_at_start"] >= gate["limit"] or gate.get("free_memory_percent", 100) < gate.get("min_free", 0)) and res["result"] != PASS:
            res["note"] = "; ".join(filter(None, [res["note"], "ran at 1-minute load %.1f (limit %.0f, waited %d s): a timeout here can be load, not the watcher" % (gate["load1_at_start"], gate["limit"], gate["waited_s"])]))
        if reasons and cases is not None and res["result"] != PASS:
            res["note"] = "; ".join(filter(None, [res["note"]] + reasons))
        return res
    if kind in ("pw", "cap") or row["rule"] in (("suite", "playwright"), ("suite", "capacity")):
        if data.get("web_ok") is not True:  # both the browser rows and the capacity rows measure the served apps/web/dist: a stale or missing build proves nothing
            return row_result(NOT, "", "depends on the web stage: it must run in this invocation and build clean")
    if data.get("playwright_port_clash") and (kind == "pw" or row["rule"] == ("suite", "playwright")):
        return row_result(NOT, "", "a fixture port was taken while the suite ran (address already in use): a foreign server may have been measured")
    if kind == "suite":
        res = rule_suite(row["rule"][1], data, missing(row["rule"][1]))
        gate_info = data.get("quiet_wait", {}).get(row["rule"][1])
        if gate_info and gate_info["load1_at_start"] >= gate_info["limit"] and res["result"] != PASS:
            res["note"] = "; ".join(filter(None, [res["note"], "stage started at 1-minute load %.1f (limit %.0f, waited %d s): wall-clock failures can be load" % (gate_info["load1_at_start"], gate_info["limit"], gate_info["waited_s"])]))
        return res
    if kind == "pw":
        return rule_playwright(data.get("playwright"), row["rule"][1], row["rule"][2], missing("playwright"), row["rule"][3] if len(row["rule"]) > 3 else None)
    if kind == "cap":
        return rule_capacity(data.get("capacity"), data.get("limits_code"), row["rule"][1], missing("capacity"), data.get("limits_text"))
    raise ValueError(kind)


def table(data: dict[str, Any], rows: Optional[list[dict[str, Any]]] = None) -> list[dict[str, Any]]:
    out = []
    for row in rows or rows_ordered():
        res = evaluate(row, data)
        out.append({"id": row["id"], "class": row["cls"], "kind": row["kind"], "execution": row["execution"], "data": row["data"], "claim": row["claim"], **res})
    cleanup = data.get("cleanup")
    if cleanup is None:
        out.append({"id": "cleanup", "class": "zorunlu", "kind": "G", "execution": "real process", "data": "no data", "claim": CLEANUP_ROW["claim"], **row_result(NOT, "", "the cleanup check did not run")})
    else:
        out.append({"id": "cleanup", "class": "zorunlu", "kind": "G", "execution": "real process", "data": "no data", "claim": CLEANUP_ROW["claim"],
                    **row_result(PASS if not cleanup else FAIL, "", "; ".join(cleanup))})
    return out


def exit_status(rows: list[dict[str, Any]]) -> int:
    """0 only when every mandatory row is geçti."""
    return 0 if all(r["result"] == PASS for r in rows if r["class"] == "zorunlu") else 1


def refusals(root: Path, machine: str, busy_ports: list[int], tools: dict[str, Optional[str]], out_dir: Path) -> list[str]:
    problems = []
    if (root / ".env").exists():
        problems.append("%s/.env exists: the run would read it (plan section 4 rule 5)" % root)
    if machine != "arm64":
        problems.append("architecture is %s, not arm64 (plan section 2)" % machine)
    if busy_ports:
        problems.append("ports already listening: %s" % ", ".join(str(p) for p in busy_ports))
    for name, path in tools.items():
        if not path:
            problems.append("%s is not on PATH" % name)
    if out_dir.exists():
        problems.append("the output folder %s already exists" % out_dir)
    live = LIVE_DATA_DIR.resolve()
    if out_dir.resolve() == live or live in out_dir.resolve().parents:
        problems.append("the output folder is inside the live data directory")
    return problems


# ---- helpers that look at the machine ----------------------------------------------------------------------------------


def sh(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, **kw)


def uptime() -> str:
    return sh(["uptime"]).stdout.strip()


def listeners(first: int, last: int) -> list[tuple[int, str]]:
    """(port, pid) of every TCP listener in the range; read only."""
    res = sh(["lsof", "-nP", "-iTCP:%d-%d" % (first, last), "-sTCP:LISTEN", "-Fpn"])
    out, pid = [], ""
    for line in res.stdout.splitlines():
        if line.startswith("p"):
            pid = line[1:]
        elif line.startswith("n") and ":" in line:
            try:
                out.append((int(line.rsplit(":", 1)[1]), pid))
            except ValueError:
                pass
    return out


def bind_busy(ports: "range | list[int]") -> list[int]:
    """Ports that something answers on, whoever owns it: a connect to loopback over IPv4 and IPv6 sees a listener on 127.0.0.1, 0.0.0.0, ::1
    and :: and of another user (lsof alone misses those). A bind test is left out on purpose: it also fails on a TIME_WAIT socket a finished
    stage left behind, and refused the second closing run for that."""
    import socket  # noqa: PLC0415
    busy = []
    for port in ports:
        taken = False
        for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            try:
                if sock.connect_ex((host, port)) == 0:
                    taken = True
            except OSError:
                pass
            finally:
                sock.close()
        if taken:
            busy.append(port)
    return busy


def version(cmd: list[str]) -> str:
    try:
        return sh(cmd).stdout.strip().splitlines()[0]
    except (OSError, IndexError):
        return "unknown"


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Aborted(Exception):
    pass


class Run:
    def __init__(self, args: argparse.Namespace, out: Path, stamp: str) -> None:
        stamp = "%s-%d" % (stamp, os.getpid())  # one-second stamps alone could collide when two runs start together
        self.args, self.out, self.stamp = args, out, stamp
        self.stages: dict[str, dict[str, Any]] = {}
        self.shims = out / "bin"
        self.cap_out = REPO / ".local" / "p9-h5" / ("matrix-" + stamp)
        self.cap_root = Path("/tmp/h5-matrix-" + stamp)
        self.python = str(REPO / ".venv" / "bin" / "python")
        self.proc: Optional[subprocess.Popen] = None
        self.handled: list[int] = []
        self.install_work = Path("/tmp/h1-install-matrix-" + stamp)
        self.meta_lint: Optional[dict[str, int]] = None
        self.started_epoch = time.time()

    def env(self, **extra: str) -> dict[str, str]:
        env = {"PATH": "%s:%s:/usr/bin:/bin:/usr/sbin:/sbin" % (REPO / ".venv" / "bin", self.shims), "HOME": str(Path.home()), "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
               "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", "/tmp/deixis-uv-cache"), "PYTHONPATH": "backend:.", "PYTHON_KEYRING_BACKEND": KEYRING_NULL,
               "LANG": os.environ.get("LANG", "en_US.UTF-8"),
               "DEIXIS_DATA_DIR": str(self.out / "no-live-data")}  # a child that forgets its own --data-dir lands here, never in the live library
        env.update(extra)
        return env

    def make_shims(self, tools: dict[str, Optional[str]]) -> None:
        self.shims.mkdir(parents=True)
        for name in ("uv", "node", "npm", "npx"):
            real = tools.get(name) or shutil.which(name)
            if real:
                os.symlink(real, str(self.shims / name))

    def stage(self, name: str, commands: list[tuple[list[str], dict[str, str], Path]]) -> bool:
        """Run the commands in order; one log; True when every exit code is 0."""
        record: dict[str, Any] = {"started": now_iso(), "uptime_start": uptime(), "commands": []}
        log = self.out / ("%s.log" % name)
        ok = True
        with log.open("w", encoding="utf-8") as fh:
            for cmd, env, cwd in commands:
                fh.write("$ %s   (cwd %s)\n" % (" ".join(cmd), cwd))
                fh.flush()
                t0 = time.time()
                rc = self.call(cmd, env, cwd, fh)
                record["commands"].append({"cmd": " ".join(cmd), "rc": rc, "seconds": round(time.time() - t0, 1)})
                fh.write("\n[exit %d, %.1f s]\n" % (rc, time.time() - t0))
                ok = ok and rc == 0
        record["ended"], record["uptime_end"], record["ok"] = now_iso(), uptime(), ok
        self.stages[name] = record
        return ok

    def abort(self, signum: int, frame: Any) -> None:
        if self.proc is not None and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
                for _ in range(100):
                    if self.proc.poll() is not None:
                        break
                    time.sleep(0.1)
                os.killpg(self.proc.pid, signal.SIGKILL)  # no-op error when the group is already gone
            except OSError:
                pass
        raise Aborted("signal %d" % signum)

    def call(self, cmd: list[str], env: dict[str, str], cwd: Path, out: Any) -> int:
        """Run one command in its own process group, so an abort can end the whole tree."""
        blocked = set(self.handled)
        if blocked:
            signal.pthread_sigmask(signal.SIG_BLOCK, blocked)  # a signal between fork and the assignment would orphan the child
        try:
            # the child inherits the blocked mask across exec, so it unblocks the signals itself (a blocked SIGTERM made every stage tree unkillable)
            self.proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=out, stderr=subprocess.STDOUT, start_new_session=True,
                                         preexec_fn=(lambda: signal.pthread_sigmask(signal.SIG_UNBLOCK, blocked)) if blocked else None)
        finally:
            if blocked:
                signal.pthread_sigmask(signal.SIG_UNBLOCK, blocked)
        try:
            return self.proc.wait()
        finally:
            self.proc = None

    def wanted(self, name: str) -> bool:
        only = set(filter(None, (self.args.only or "").split(",")))
        skip = set(filter(None, (self.args.skip or "").split(",")))
        return (not only or name in only) and name not in skip

    def pytest_cmd(self, junit: Path, *extra: str) -> list[str]:
        # --basetemp puts every test server, data folder and disk image under the output folder, so the cleanup check can see a leaked one
        return [self.python, "-m", "pytest", "-p", "no:cacheprovider", "--junitxml", str(junit), "--basetemp", str(self.out / (junit.stem + "-tmp")), "-q"] + list(extra)


def collect(run: Run) -> dict[str, Any]:
    data: dict[str, Any] = {"missing": {}}
    for name in STAGES[1:]:
        if not run.wanted(name):
            data["missing"][name] = "stage %s skipped" % name
    out = run.out
    data["stage_ok"] = {name: st.get("ok") for name, st in run.stages.items()}
    data["web_ok"] = run.stages.get("web", {}).get("ok") is True
    data["lint"] = run.meta_lint
    if run.wanted("install"):
        path = out / "install" / "results.json"
        data["install"] = json.loads(path.read_text()) if path.exists() else None
        if data["install"] is None:
            data["missing"]["install"] = "install_check wrote no results.json"
    for stage, xml in (("pytest", "pytest.xml"), ("process", "process.xml"), ("f09", "f09.xml")):
        if run.wanted(stage):
            path = out / xml
            data[stage] = junit_cases([path]) if path.exists() else None
            if data[stage] is None:
                data["missing"][stage] = "stage %s wrote no junit file" % stage
    if run.wanted("playwright"):
        data["playwright"] = playwright_specs(out / "playwright" / "results.json")
        if data["playwright"] is None:
            refused = run.stages.get("playwright", {}).get("refused")
            data["missing"]["playwright"] = ("stage playwright refused: " + refused) if refused else "Playwright wrote no results.json"
    pw_log = out / "playwright.log"
    data["playwright_port_clash"] = bool(run.wanted("playwright") and pw_log.exists() and re.search(r"EADDRINUSE|Errno 48|address already in use", pw_log.read_text(errors="replace")))
    if run.wanted("capacity"):
        path = run.cap_out / "summary.json"
        data["capacity"] = json.loads(path.read_text()) if path.exists() else None
        if data["capacity"] is None:
            data["missing"]["capacity"] = "capacity.py wrote no summary.json"
        data["limits_code"] = run.stages.get("capacity", {}).get("limits_rc")
        limits_file = out / "capacity-limits.txt"
        data["limits_text"] = limits_file.read_text(errors="replace") if limits_file.exists() else None
    return data


def web_verdict(commands_ok: bool, log_text: str) -> tuple[Optional[dict[str, int]], bool, str]:
    """(lint numbers, ok, note): build and lint exit 0, lint prints its summary, no error, warnings not above the baseline."""
    found = re.findall(r"Found (\d+) warnings? and (\d+) errors?", log_text)
    if not found:
        return None, False, "lint printed no summary line" if commands_ok else "a command exited nonzero"
    lint = {"warnings": int(found[-1][0]), "errors": int(found[-1][1]), "baseline": LINT_BASELINE}
    ok = commands_ok and lint["errors"] == 0 and lint["warnings"] <= LINT_BASELINE
    return lint, ok, "" if ok else "a command exited nonzero or lint is above the baseline"


def leftover_findings(busy: list[tuple[int, str]], ps_text: str, hdiutil_text: str, needles: list[str], me: str) -> list[str]:
    """Pure part of the cleanup check: listeners, processes naming the run's folders, a mounted image of the run."""
    found = []
    if busy:
        found.append("listeners: " + ", ".join("%d (pid %s)" % b for b in busy))
    for line in ps_text.splitlines():
        pid, _, command = line.strip().partition(" ")
        if pid != me and any(n in command for n in needles) and not command.startswith("ps ") and "run_matrix" not in command:
            found.append("process %s: %s" % (pid, command[:100]))
    if any(n in hdiutil_text for n in needles):
        found.append("a disk image of this run is still mounted")
    return found


def kill_started(run: Run) -> None:
    """After an abort: end every process whose command line names this run's folders (test servers start their own sessions)."""
    needles = [str(run.out), str(run.out.resolve()), "/tmp/h5-matrix-" + run.stamp, "matrix-" + run.stamp]
    me = str(os.getpid())
    for line in sh(["ps", "-A", "-o", "pid=,command="]).stdout.splitlines():
        pid, _, command = line.strip().partition(" ")
        if pid != me and any(n in command for n in needles) and not command.startswith("ps ") and "run_matrix" not in command:
            try:
                os.kill(int(pid), signal.SIGKILL)
            except (OSError, ValueError):
                pass
    for device in images_of_run(sh(["hdiutil", "info"]).stdout, needles):
        sh(["hdiutil", "detach", "-force", device])


def images_of_run(info: str, needles: list[str]) -> list[str]:
    """Device names (/dev/diskN) of the disk images in `hdiutil info` whose image path names this run's folders."""
    devices = []
    for block in info.split("================================================"):
        if any(("image-path" in line and n in line) for line in block.splitlines() for n in needles):
            match = re.search(r"^(/dev/disk\d+)\s", block, re.M)
            if match:
                devices.append(match.group(1))
    return devices


def leftovers(run: Run) -> list[str]:
    """Anything this run could have left: listeners on its ports, processes naming its folders, a mounted test image."""
    busy = [(p, pid) for p, pid in listeners(OWN_PORTS[0], OWN_PORTS[-1])]
    busy += [(p, pid) for p, pid in listeners(PLAYWRIGHT_PORTS[0], PLAYWRIGHT_PORTS[-1])]
    needles = [str(run.out), str(run.out.resolve()), "/tmp/h5-matrix-" + run.stamp, "matrix-" + run.stamp]
    found = leftover_findings(busy, sh(["ps", "-A", "-o", "pid=,command="]).stdout, sh(["hdiutil", "info"]).stdout, needles, str(os.getpid()))
    if run.install_work.exists():
        found.append("install work folder %s is still there" % run.install_work)
    if run.cap_root.exists() and not run.args.keep:
        found.append("capacity folder %s is still there" % run.cap_root)
    tmp = Path(os.environ.get("TMPDIR", "/tmp"))
    for folder in list(tmp.glob("h5-run-*")) + list(Path("/tmp").glob("h5-run-*")):  # capacity.py's per-repetition folders; one made by another run in the same minutes is flagged too
        try:
            if folder.stat().st_mtime >= run.started_epoch:
                found.append("capacity repetition folder %s is still there" % folder)
        except OSError:
            pass
    return found


# ---- output ------------------------------------------------------------------------------------------------------------


def render_markdown(rows: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    lines = ["# P9 acceptance matrix run", "",
             "Commit `%s`%s, started %s, finished %s. %s." % (meta["commit"][:12], " (work tree dirty)" if meta["dirty"] else "", meta["started"], meta["finished"], meta["uptime_start"]),
             "", "| Row | Class | Kind | Result | Evidence | Note |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| %s | %s | %s | %s | %s | %s |" % (r["id"], r["class"], r["kind"], r["result"], r["evidence"], r["note"].replace("|", "/")))
    counts = {k: sum(r["result"] == k for r in rows) for k in RESULTS}
    lines += ["", "Totals: " + ", ".join("%s %d" % (k, v) for k, v in counts.items()) + ". Mandatory rows not geçti: %s." % (
        ", ".join(r["id"] for r in rows if r["class"] == "zorunlu" and r["result"] != PASS) or "none")]
    for stage, gate_info in meta.get("quiet_wait", {}).items():
        lines.append("- quiet gate before %s: %s" % (stage, gate_info))
    if meta.get("aborted"):
        lines.append("- **aborted**: %s; unfinished stages give ölçülmedi" % meta["aborted"])
    for name, st in meta["stages"].items():
        lines.append("- stage %s: %s, %s to %s, uptime at start: %s" % (name, "ok" if st.get("ok") else "not ok", st["started"], st["ended"], st["uptime_start"].split("load averages:")[-1].strip()))
    return "\n".join(lines) + "\n"


def print_table(rows: list[dict[str, Any]]) -> None:
    print("\n%-9s %-13s %-5s %-12s %-26s %s" % ("row", "class", "kind", "result", "evidence", "note"))
    for r in rows:
        print("%-9s %-13s %-5s %-12s %-26s %s" % (r["id"], r["class"], r["kind"], r["result"], r["evidence"][:26], r["note"][:80]))


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="P9 acceptance matrix, one command")
    p.add_argument("--out-dir", help="must not exist; default .local/p9-matrix/<stamp>")
    p.add_argument("--only", help="comma-separated stage names; the others give ölçülmedi")
    p.add_argument("--skip", help="comma-separated stage names to skip (their rows give ölçülmedi)")
    p.add_argument("--overlay-uncommitted", action="store_true", help="install stage: copy modified files over the exported commit")
    p.add_argument("--keep", action="store_true", help="keep the /tmp/h5-matrix-* capacity folders")
    p.add_argument("--self-test", action="store_true", help="check the row mapping and exit")
    args = p.parse_args(argv)
    for name in (args.only or "").split(",") + (args.skip or "").split(","):
        if name and name not in STAGES:
            p.error("unknown stage %r (stages: %s)" % (name, ", ".join(STAGES)))
    return args


def self_test() -> int:
    failures = []
    ids = [r["id"] for r in rows_ordered()]
    if len(ids) != len(set(ids)):
        failures.append("duplicate row ids")
    empty = {"missing": {}}
    rows = table(empty)
    if exit_status(rows) != 1 or any(r["result"] == PASS for r in rows):
        failures.append("an empty run must not pass any row")
    if failures:
        print("self-test FAILED:\n  " + "\n  ".join(failures))
        return 1
    print("self-test ok (%d rows)" % len(rows))
    return 0


def free_memory_percent() -> float:
    """System-wide free memory percentage from `memory_pressure` (100 when it cannot be read)."""
    match = re.search(r"free percentage:\s*(\d+)%", sh(["memory_pressure"]).stdout)
    return float(match.group(1)) if match else 100.0


def wait_quiet(loadavg: Callable[[], tuple], sleep: Callable[[float], None], clock: Callable[[], float], limit: float = QUIET_LOAD, max_wait: float = QUIET_WAIT_SECONDS,
               free_memory: Callable[[], float] = lambda: 100.0, min_free: float = QUIET_FREE_MEMORY) -> tuple[float, float, float]:
    """Wait until the 1-minute load is below `limit` and the free memory is at least `min_free` percent (at most `max_wait` seconds);
    returns (seconds waited, load at the end, free memory percent at the end)."""
    t0 = clock()
    while (loadavg()[0] >= limit or free_memory() < min_free) and clock() - t0 < max_wait:
        sleep(15)
    return clock() - t0, loadavg()[0], free_memory()


def gate(run: Run, meta: dict[str, Any], name: str) -> None:
    waited, load, free = wait_quiet(os.getloadavg, time.sleep, time.monotonic, free_memory=free_memory_percent)
    meta.setdefault("quiet_wait", {})[name] = {"waited_s": round(waited), "load1_at_start": round(load, 2), "limit": QUIET_LOAD, "free_memory_percent": free, "min_free": QUIET_FREE_MEMORY}
    if name == "f09":
        meta["f09_quiet_wait"] = meta["quiet_wait"][name]
    print("stage %s (waited %.0f s for 1-minute load < %.0f and free memory >= %d%%; load %.2f, free %.0f%%) ..." % (name, waited, QUIET_LOAD, QUIET_FREE_MEMORY, load, free), flush=True)


def run_stages(args: argparse.Namespace, run: Run, meta: dict[str, Any], out: Path, web: Path) -> None:
    if run.wanted("f09"):
        gate(run, meta, "f09")
        run.stage("f09", [(run.pytest_cmd(out / "f09.xml", "-n", "0", "tests/documents/test_documents.py::test_extraction_is_stopped_at_the_production_memory_limit",
                                          "tests/documents/test_arxiv_source_archive.py::test_the_source_child_is_stopped_at_the_production_memory_limit"),
                           run.env(DEIXIS_P9_PRODUCTION_THRESHOLD="1"), REPO)])
    if run.wanted("process"):
        gate(run, meta, "process")
        run.stage("process", [(run.pytest_cmd(out / "process.xml", "-m", "process", "-n", "0"), run.env(), REPO)])
    if run.wanted("install"):
        cmd = [run.python, "scripts/p9/install_check.py", "--port", "8950", "--out-dir", str(out / "install"), "--work-dir", str(run.install_work)]
        if args.overlay_uncommitted:
            cmd.append("--overlay-uncommitted")
        env = run.env()
        env.pop("PYTHONPATH", None)
        print("stage install ...", flush=True)
        run.stage("install", [(cmd, env, REPO)])
    if run.wanted("pytest"):
        print("stage pytest ...", flush=True)
        run.stage("pytest", [(run.pytest_cmd(out / "pytest.xml", "-m", "slow or not slow"), run.env(), REPO)])
    if run.wanted("web"):
        print("stage web ...", flush=True)
        cmds = []
        if not (web / "node_modules").exists():
            cmds.append((["npm", "ci"], run.env(), web))
        cmds += [(["npm", "run", "build"], run.env(), web), (["npm", "run", "lint"], run.env(), web)]
        ok = run.stage("web", cmds)
        lint, verdict, note = web_verdict(ok, (out / "web.log").read_text(errors="replace"))
        meta["lint"] = run.meta_lint = lint
        run.stages["web"]["ok"], run.stages["web"]["note"] = verdict, note
    if run.wanted("playwright"):
        taken = sorted(set([p for p, _ in listeners(PLAYWRIGHT_PORTS[0], PLAYWRIGHT_PORTS[-1])] + bind_busy(PLAYWRIGHT_PORTS)))
        if taken:
            print("stage playwright refused: fixture ports in use: %s" % taken, flush=True)
            run.stages["playwright"] = {"started": now_iso(), "ended": now_iso(), "uptime_start": uptime(), "uptime_end": uptime(), "ok": None, "commands": [], "refused": "fixture ports in use: %s" % taken}
        else:
            print("stage playwright ...", flush=True)
            run.stage("playwright", [(["npm", "run", "test:acceptance"], run.env(DEIXIS_ACCEPTANCE_DIR=str(out / "playwright")), web)])
    if run.wanted("capacity"):
        gate(run, meta, "capacity")
        env = run.env(P9_CAPACITY_PORT_FIRST="8950")
        cap = [run.python, "scripts/p9/capacity.py"]
        root, cout = str(run.cap_root), str(run.cap_out)
        normal, pdf_out, control = [str(run.cap_out / name) for name in ("normal", "pdf", "control")]
        merge = ["--out", cout, "--also", normal, pdf_out, control]
        cmds = [(cap + ["generate", "--root", root], env, REPO), (cap + ["pdf-library", "--root", root], env, REPO),
                (cap + ["measure", "--root", root, "--out", normal], env, REPO), (cap + ["measure", "--root", root, "--pdf", "--out", pdf_out], env, REPO),
                (cap + ["measure", "--root", root, "--control", "--out", control], env, REPO), (cap + ["summarize"] + merge, env, REPO),
                (cap + ["table"] + merge, env, REPO)]
        run.stage("capacity", cmds)
        with (out / "capacity-limits.txt").open("w", encoding="utf-8") as fh:
            run.stages["capacity"]["limits_rc"] = run.call(cap + ["limits"] + merge, env, REPO, fh)
        if not args.keep:
            shutil.rmtree(str(run.cap_root), ignore_errors=True)



def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        return self_test()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out_dir).expanduser().resolve() if args.out_dir else REPO / ".local" / "p9-matrix" / stamp
    tools = {name: shutil.which(name) for name in ("uv", "node", "npm")}
    busy = [p for p, _ in listeners(OWN_PORTS[0], OWN_PORTS[-1])] + [p for p, _ in listeners(PLAYWRIGHT_PORTS[0], PLAYWRIGHT_PORTS[-1])]
    busy += bind_busy(OWN_PORTS) + bind_busy(PLAYWRIGHT_PORTS)
    problems = refusals(REPO, platform.machine(), sorted(set(busy)), tools, out)
    try:
        capacity_rows()
    except (SystemExit, ValueError) as exc:  # a bad P9_CAPACITY_PORT_FIRST in the caller's environment
        problems.append("P9_CAPACITY_PORT_FIRST: %s" % exc)
    if not (REPO / ".venv" / "bin" / "python").exists():
        problems.append(".venv/bin/python is missing: run `uv sync` first")
    if problems:
        print("refused: " + "; ".join(problems), file=sys.stderr)
        return 2
    leak = [name for name in ("codex", "claude", "gemini", "tesseract")
            if shutil.which(name, path="%s:/usr/bin:/bin:/usr/sbin:/sbin" % (REPO / ".venv" / "bin"))]
    if leak:
        print("refused: a model CLI or OCR tool would be on the stage PATH: %s" % ", ".join(leak), file=sys.stderr)
        return 2
    out.mkdir(parents=True)
    run = Run(args, out, stamp)
    run.make_shims(tools)
    dirty = bool(sh(["git", "-C", str(REPO), "status", "--porcelain"]).stdout.strip())
    commit = sh(["git", "-C", str(REPO), "rev-parse", "HEAD"]).stdout.strip()
    meta: dict[str, Any] = {
        "commit": commit, "dirty": dirty, "started": now_iso(), "uptime_start": uptime(), "ports_own": "8950 to 8970",
        "versions": {"macOS": version(["sw_vers", "-productVersion"]), "python": version([run.python, "--version"]), "uv": version(["uv", "--version"]),
                     "node": version(["node", "--version"]), "npm": version(["npm", "--version"]), "arch": platform.machine()},
        "provenance": {"install": "HEAD plus uncommitted overlay" if args.overlay_uncommitted else "HEAD export only (uncommitted changes not included)",
                       "other_stages": "working tree (.venv and apps/web/node_modules as found, installed before the run)"},
        "live_8765_listeners_before": [pid for p, pid in listeners(8765, 8765)],
    }
    print("preflight ok: commit %s%s, %s" % (commit[:10], " (dirty)" if dirty else "", meta["uptime_start"]), flush=True)
    web = REPO / "apps" / "web"

    handled = [signal.SIGINT, signal.SIGTERM] + ([] if signal.getsignal(signal.SIGHUP) is signal.SIG_IGN else [signal.SIGHUP])  # nohup ignores SIGHUP on purpose
    run.handled = handled
    previous = {sig: signal.signal(sig, run.abort) for sig in handled}
    try:
        run_stages(args, run, meta, out, web)
    except Aborted as error:
        meta["aborted"] = str(error)
        print("aborted: %s; stopping what this run started" % error, flush=True)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        kill_started(run)
        if not args.keep:
            shutil.rmtree(str(run.cap_root), ignore_errors=True)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)

    data = collect(run)
    data["cleanup"] = leftovers(run)
    data["f09_quiet_wait"] = meta.get("f09_quiet_wait")
    data["quiet_wait"] = meta.get("quiet_wait", {})
    meta["finished"], meta["stages"] = now_iso(), run.stages
    meta["live_8765_listeners_after"] = [pid for p, pid in listeners(8765, 8765)]
    rows = table(data)
    status = exit_status(rows)
    (out / "matrix.json").write_text(json.dumps({"meta": meta, "rows": rows, "exit_status": status}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "matrix.md").write_text(render_markdown(rows, meta), encoding="utf-8")
    print_table(rows)
    print("\n%s  results: %s/matrix.json" % ("every mandatory row geçti" if status == 0 else "MANDATORY ROW NOT geçti", out))
    return status


if __name__ == "__main__":
    sys.exit(main())
