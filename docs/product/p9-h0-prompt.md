<!-- PLAN-REVIEW-ROUNDS: gpt-6.1-sol high, r1: hazır değil, 2 high (keyring isolation not reaching the Playwright fixture server; unreadable resident size silently disabling the limit) + 6 medium + 1 low, all folded in; r2: düzeltmeyle hazır (0 high; 4 medium + 1 low folded in); the implementation was written by the orchestrator, not Sol (small, measurement-driven); code review r1: düzeltmeyle hazır (0 high; 3 medium + 2 low folded in); see D138 and D139 -->

# Task: P9 hardening, batches H0a ("Taban çizgisi, ortam sabitleme ve özellik envanteri") and H0b ("Bellek sınırı teşhisi"), one commit

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-h0`, detached at `8091d62` (main with D136). Plan: `docs/product/p9-hardening-plan.md`
(commit `4eb0b87`): read §2 (supported environment), §4 (matrix, closing rule 2, F09), the H0a and H0b sections of §5. Also read `AGENTS.md`,
`CLAUDE.md` and the top of `docs/decisions.md`. The scope below was decided by the main session; where the code differs from what this
prompt says, report it.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted. Do not
invent; report what you could not find. **No real-model call, no provider call.** Do not touch `../DEIXIS` (except writing measurement
output under `../DEIXIS/.local/p9-baseline/` and `../DEIXIS/.local/p9-h0b/`, which are ignored and never committed), `../DEIXIS-l8` or any
other worktree, `TODO.md`, `.vscode/`, `scripts/local_index.py`, `docs/product/sw-status.md`, port 8765 or the live data directory. Backend
tests need `PYTHONPATH=backend:.` and `UV_CACHE_DIR=/tmp/deixis-uv-cache`; Python must be native arm64 (`platform.machine()` is `arm64`).
No method or contract change (`skill_package_hash` stays as it is), no migration, no change to the flow, the worker or the API.

## Why

P9 turns "works on the developer's machine, by the developer's hands" into measured, repeatable claims. H0a fixes the starting point: the
numbers as found on a clean copy of the commit, the supported environment written in the repository, and the list of what the code
implements. H0b settles one safety limit: the 1 GiB memory limit on PDF text extraction (F09). The plan names the known red test
`tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit` and says its cause was never diagnosed. F09 is a
mandatory row: if the limit does not work at the production threshold, that is a product bug and P9 cannot close (§4 rule 2).

## What is and is not in code (checked on 8091d62)

- `backend/deixis/documents/pdf.py::extract_pdf` runs `python -m deixis.documents.pdf <path> <max_chars> <max_memory>` through
  `subprocess.run(..., timeout=90)`. The only memory control is `_watch_memory(limit)` inside that child: a daemon thread that polls
  `resource.getrusage(RUSAGE_SELF).ru_maxrss` every 50 ms and calls `os._exit(3)` over the limit. The parent turns exit code 3 into
  `Extraction("failed", error="extraction exceeded the memory limit")`.
- `ocr.py`, `jats.py` and `arxiv_source.py` start their own children and call `pdf._watch_memory` in them with their own 1 GiB limits. They
  have their own parent-side runners. They are NOT part of this batch (see Limits).
- `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit` builds a 70 MB (decoded) content stream in a file
  under 1 MB and sets the limit to 100 MiB, not the production 1 GiB.
- `apps/web/package.json` has no `engines`; no `.node-version`; the README Quickstart names no supported environment.
- Not in code: any parent-side memory watcher, any test of the 1 GiB threshold, `scripts/p9/`.

## Diagnosis already measured (the main session ran these before writing this prompt; raw lines in `../DEIXIS/.local/p9-h0b/runs.jsonl`)

Probe: `scripts/p9/memory_probe.py` builds a one-page PDF whose Flate content stream decodes to N MiB and runs the production child argv,
sampling the child's resident size from outside (`ps`) and reading its `wait4` peak. macOS 27.0.1 arm64, Python 3.12.13, PyMuPDF from `uv.lock`.

| Run (child, before the fix) | Limit | Decoded input | Result |
|---|---|---|---|
| test scale, 6 runs | 100 MiB | 67 MiB | 6 of 6 never stopped; killed by the probe at 90 s; peak RSS 951 to 1195 MiB (about ten times the limit) |
| production, 3 runs | 1 GiB | 67 MiB | 3 of 3 not stopped within 90 s; peak 903, 1025, 938 MiB |
| production, 3 runs | 1 GiB | 200 MiB | 3 of 3 not stopped within 90 s; peak 1223 to 1312 MiB, over the limit |
| below the limit, 2 runs | 1 GiB | 20 MiB | finishes in 20 to 23 s, peak 573 to 575 MiB, no stop |

The pytest test alone: passed once in 3.7 s, failed with "extraction timed out" (90 s) the next time, on the same machine and code. So it
is not a deterministic failure and not (only) a load effect of `-n auto`: serial runs fail too.

Cause (observed once, saved in `../DEIXIS/.local/p9-h0b/gil-diagnosis.txt` by `scripts/p9/gil_diagnosis.py`): `faulthandler.dump_traceback_later`
in the child shows the main thread inside `pymupdf.extra.page_get_textpage` (a C call that holds the interpreter lock) while the watchdog thread
and a second ticker thread sit on their `sleep` line; the ticker printed nothing in 8 s. A Python thread cannot run while that call holds the
lock, so the watchdog never wakes. The extraction grows past the limit inside long C calls and is stopped, if at all, by the 90 s timeout. For
scale only: the 20 MiB run reached 573 MiB in about 20 s, and the three 200 MiB runs that the fix stops at the 1 GiB limit took 26 to 37 s to get
there, so the 90 s timeout is a late backstop. These are single-input figures, not a model of growth. Other explanations checked: the test's
100 MiB threshold is not the cause (the 1 GiB runs fail the same way); `ru_maxrss` units are not the cause (independent `ps` samples agree and
exceed the limit); macOS memory compression can lower a later reading, which explains why the 67 MiB runs peak between 903 and 1195 MiB, but not
the 200 MiB runs at 1223 to 1312 MiB. This is a product bug, not a test fault.

## Decisions (already taken; do not reopen)

### H0b: the watcher moves to the parent

1. `pdf.py` gets `_run_watched(argv, env, timeout, max_memory) -> subprocess.CompletedProcess`: `Popen` with stdout and stderr to temporary
   files (no pipe to fill), then a loop that waits `WATCH_INTERVAL_SECONDS = 0.05` per turn and checks the child's current resident size from
   outside. Over the limit: kill the child (SIGKILL), return `returncode = MEMORY_EXIT_CODE` with `stderr = b"memory limit exceeded\n"` (so the
   existing mapping to `extraction exceeded the memory limit` is unchanged). Past `timeout`: kill and raise `subprocess.TimeoutExpired` (so the
   existing `extraction timed out` mapping is unchanged). The child is always killed and reaped in a `finally`.
2. `_resident_bytes(pid)`: on macOS, `libproc.proc_pidinfo(pid, PROC_PIDTASKINFO=4, ...)` through `ctypes`, reading `pti_resident_size`; on Linux
   `/proc/<pid>/statm`; anywhere else, or when the read fails, `None` (no check that turn; Windows keeps having no memory limit, as the module
   docstring says). The in-child `_watch_memory` thread stays unchanged as a second guard and because `ocr.py`, `jats.py` and `arxiv_source.py`
   still use it.
3. `extract_pdf` calls `_run_watched(argv, env, TIMEOUT_SECONDS, max_memory)` instead of `subprocess.run`. Nothing else in `extract_pdf` changes
   (argv, env, request file for placements, error mapping, parsing of the result).
4. Judgement taken: the check reads CURRENT resident size, not the peak. A peak since start is not available for another process on macOS
   without root; macOS can compress resident pages, so a current reading can sit below an earlier peak. The limit is "shortly after the size
   crosses the limit at a sample", which the docstring already says. Measured stop point: see the evidence below.
5. Fail-visible, not fail-open (plan review round 1, high): on macOS and Linux, a single unreadable turn is tolerated (a child that just ended,
   a transient read), but `WATCH_LOST_TURNS = 20` unreadable turns in a row (one second) with the child still alive kill the child and raise
   `MemoryWatchLost`; `extract_pdf` maps it to `Extraction("failed", error="extraction memory limit could not be watched")`. A failed library
   load (`ctypes.CDLL`) or a missing `proc_pidinfo` is `None` from `_resident_bytes`, never an exception. Elsewhere (Windows) there is no watch,
   as before, and nothing is claimed for it.
5a. A wait never exceeds the time left (round 1, medium): `proc.wait(min(0.05, time left))`, so a child that ends after the deadline is a timeout.
6. The known red test is kept at its 100 MiB scale (it now runs in about 0.3 to 2 s) and stays in the default suite. A new opt-in test proves
   F09 at the production threshold with a 200 MiB decoded input (about 30 s): it is skipped unless `DEIXIS_P9_PRODUCTION_THRESHOLD=1` exactly, and
   the F09 acceptance run sets it. Fast tests cover `_run_watched` on its own, with a minimal `PATH`-only child environment: a child that prints
   `ready`, then grows by 300 MiB inside `memset` called through `ctypes.PyDLL` (which keeps the lock) and then sleeps 30 s in a PyDLL `sleep`, is
   stopped by the parent with its stdout still `ready` and well before the sleep ends (bound 20 s, not a tight one); a child under the limit
   returns 200 000 bytes of stdout, its stderr and exit code (no pipe stall); a child past the time limit is killed, `TimeoutExpired` is raised and
   its pid is gone afterwards; a child that ends just after a very short deadline is still a timeout; a watch that can never read the child
   raises `MemoryWatchLost` and kills it; one unreadable turn does not stop a child; `extract_pdf` maps `MemoryWatchLost` to its failed result.

### H0a: baseline, environment, feature list

7. Baseline: a clean export of `8091d62` (`git archive`, because no git state-changing command is allowed, so no extra worktree) in `/tmp/h0-base`,
   run with an environment allow-list only (`HOME`, `PATH` with only `uv`, `node`, `npm`, `npx`, `TMPDIR`, `UV_CACHE_DIR`, `PYTHONPATH`,
   `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring`, `LANG`), no `.env` in the export, no model CLI on `PATH`. First step (plan §4 rule 5):
   confirm no `.env` is present and none is loaded; this passed before any harness ran. Record: pytest counts, `-n auto` and `-n 0`
   wall times, `npm ci`, build, lint warning count, Playwright count, with the load average at each start and whether another pytest,
   Playwright or Vite process of another worktree was running. Counts as found are recorded, not assumed (D136 recorded pytest 3,774 passed plus the known
   failure and Playwright 112; the plan says 111). Timings taken under foreign load are marked skewed and not presented as clean. Output only
   under `../DEIXIS/.local/p9-baseline/`. The baseline (clean export, before) and the acceptance run of this batch's changes (after, in this
   worktree: full pytest, build, lint, Playwright) are recorded separately and not mixed.
7a. Keyring isolation (round 1, high): pytest installs an in-memory keyring (`tests/conftest.py`) and the allow-list sets
   `PYTHON_KEYRING_BACKEND`, but the Playwright specs start the fixture server with an environment of `PATH`, `HOME` and `PYTHONPATH` only, so the
   variable never reaches it and the system keychain stays reachable (`/api/credentials`). This was found during the plan review and is a gap
   of the harness as found, so the baseline Playwright run is NOT isolated in that respect (no evidence a real key was read; not established
   either way). The fix kept small: `tests/acceptance/fixture_server.py::main` installs an in-memory keyring before anything else (one class,
   the `conftest.py` one, about 24 lines with its imports), which covers every spec because all of them start that server. Playwright is re-run after the change and must keep
   its count. The spec files (fifteen) and their environments are not edited. Whether other Playwright children (not the fixture server) touch
   the keychain is not claimed.
8. Environment: `apps/web/package.json` gets `"engines": {"node": ">=22.12.0 <23", "npm": ">=10 <11"}`; `.node-version` holds `22.23.2` (the version
   observed); the README gets one supported-environment sentence in the Quickstart (macOS arm64, observed on macOS 27.0.1 and older versions
   untested, native arm64 Python 3.12 from `uv`, Node 22 with npm 10, system Chrome for the browser tests; everything else not supported or tested). No dependency changes. `package-lock.json` is not in the
   allowed list: if `npm ci` or `npm install` would rewrite its root entry because of `engines`, report it; do not edit the lock.
9. Feature list (plan H0a item 3), from code and the README only, recorded in the decision: providers in `providers/registry.py::CONNECTORS`,
   model adapters in `models/`, P7 and P8 parts found or not found (grep for a second-model review and for publication tracking), with the
   statement that a missing P8 piece is not P9's work, and how it binds the matrix (§4 rows are written for these features; a row whose feature
   is missing is written "yok", not run). No new document.
10. The owner's daily-use log (S9, plan H0a item 4) is the owner's file under `.local/p9-daily-use-log.md`; this batch writes nothing there. That
   plan item is therefore recorded as handed to the owner, not as done.

## Limits (do not exceed)

- Do not change `ocr.py`, `jats.py` or `arxiv_source.py`. They use the same in-child thread and so probably have the same hole; this batch only
  records that, as an open follow-up with the measurement still to be made. Do not claim they are fixed or broken: only `extract_pdf` was measured.
- Do not raise or lower `MAX_MEMORY_BYTES` (1 GiB), `TIMEOUT_SECONDS` (90) or any other limit. Do not add `RLIMIT_AS` (macOS does not enforce it).
- No new dependency (`psutil` is not used).
- The fix proves the limit works for PDF text extraction on macOS arm64 with a decoded-content-stream input only. It does not show that other
  file shapes stay under the limit, that the limit prevents the allocation (it stops shortly after), or anything about Windows (no limit there).

## Files allowed

`backend/deixis/documents/pdf.py`, `tests/test_documents.py`, `tests/acceptance/fixture_server.py` (one small in-memory keyring class and the line that installs it),
`scripts/p9/memory_probe.py`, `scripts/p9/gil_diagnosis.py`, `apps/web/package.json`, `.node-version`, `README.md`
(the environment sentence only), `docs/decisions.md` (new entries at the top), this prompt. Measurement output under `../DEIXIS/.local/p9-*/`.

## Files NOT allowed

Everything else, in particular `ocr.py`, `jats.py`, `arxiv_source.py`, `flow.py`, `api/app.py`, migrations, `methods/`, `contracts/`,
`apps/web/package-lock.json`, `docs/product/p9-hardening-plan.md` (no batch status line exists in it), `TODO.md`.

## Tests to add

`tests/test_documents.py`: the `_run_watched` tests and the opt-in production-threshold test of decision 6. The existing memory-limit test
stays as it is.

## Checks to run

Native arm64 check. The known test serial (`-n 0`) several times and under `-n auto`; the opt-in test once; `scripts/p9/memory_probe.py` in
`--mode extract` at the production threshold (three runs), at test scale (five runs) and below the limit (one run: it must finish `succeeded`);
full `PYTHONPATH=backend:. uv run pytest`; web build, lint and the full Playwright run on this worktree (the web source is unchanged except
`engines`, but the fixture server and the PDF path are exercised); `git diff --check`. The probe records the sampled peak by pid (KiB) and the
kernel peak from `RUSAGE_CHILDREN`, and says "sampled" where it is a sample.

## Report at the end

Files changed; baseline numbers with the load notes; the H0b verdict (product bug or test fault) with the evidence; test counts; every
fallback or judgement; what is left open (the three sibling children, Windows, I08).
