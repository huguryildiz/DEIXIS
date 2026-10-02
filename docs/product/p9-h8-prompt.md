<!-- PLAN-REVIEW-ROUNDS: r1 (Opus 5.5 high): düzeltmeyle hazır, 3 high + 6 medium + 5 low, all folded in below; r2 (Opus 5.5 high): düzeltmeyle hazır, 0 high + 3 medium + 3 low, all folded in (DEIXIS_DATA_DIR pointed into the out folder, bind check and port-clash scan for Playwright, --basetemp under the out folder, stage exit codes folded into rows, provenance in matrix.json); code review r1 (Opus 5.5 high): düzeltmeyle hazır, 1 high (README claimed a pass before any run) + 3 medium + 5 low, folded in; code review r2: düzeltmeyle hazır, 0 high, 3 medium + 6 low (SIGHUP under nohup, F09 gate note, collect() tests, abort wait and detach, and others folded in) ;  reviewer: Opus 5.5 high (Sol quota out), Sol re-review pending (gpt-6.1-sol was not tried again in this batch; the brief records the usage-limit error until 3 October 2026 20:39) -->

# Task: P9 batch H8, merge the acceptance matrix and write the record of known issues and capacity limits

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-h8`, detached at `17b8341` (main with D167). Plan: `docs/product/p9-hardening-plan.md` §2 (supported
environment), §4 (rules 1 to 5 and the full tables), §5 "H8", §8 (record format) and §9 (owner questions). The P9 exit condition is the P9 row of
`docs/product/implementation-plan.md` §9 (line 299): *a repeatable install and an acceptance matrix in the supported environment; known bugs and capacity
limits open*. Also read `AGENTS.md`, `CLAUDE.md` and D138, D139, D159 and D161 to D167 in `docs/decisions.md` (the inputs; D167 is the highest number on
main, so the next free one is D168). Style model: `docs/product/p9-h2-prompt.md`. Venv: `.venv` exists in this worktree (arm64, `uv sync --offline` done),
`apps/web/node_modules` was installed with `npm ci` (the main checkout's copy has no `@axe-core/playwright`); the main session removes it afterwards.
Run tests with `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest ...`.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted. No real-model call, no
provider call beyond what the existing harnesses already do (the installer downloads packages; nothing else leaves the machine). Do not touch
`../DEIXIS-h6` or any other `../DEIXIS*` worktree, `TODO.md`, `.vscode/`, `scripts/local_index.py`, `docs/product/sw-status.md`, the live service on port
8765, ports 8858 to 8864, or the live data directory `~/Library/Application Support/DEIXIS`. Use ports 8950 to 8970 for anything new. No method, contract or
migration change (`skill_package_hash` unchanged). Do not invent; report what you could not measure.

## Why

H1 to H7 each left a harness, a test group or a measurement script, and a status paragraph in the plan. Nothing yet runs them together, and the numbers
and the open items are spread over ten decisions. H8 (a) makes one command run every automatic row (S, G, A) and print the result row by row, (b) runs it
twice in a clean worktree and compares the pass/fail result, (c) collects every "left open" and "not measured" item into one record, and (d) closes the
model-free part of P9 with a decision that states what the evidence is. It adds no product feature and fixes a defect only if the matrix run shows a
mandatory row failing (plan §4 rule 2); such a row is reported first and is not hidden.

## What is and is not in code (checked on 17b8341)

- `scripts/p9/run_matrix.sh` (11 lines) calls `scripts/p9/install_check.py "$@"` and exits with its status. Nothing else is run by it.
- `scripts/p9/install_check.py` (I01 to I05, I07, a keyring check and a cleanup check; I08 recorded as not measured) exports a commit with `git archive`,
  default port 8871 (`--port`), raw output in `.local/p9-h1/<stamp>/results.json` (`rows[]` with `id`, `result` in `pass|fail|not_measured`, `numbers`).
  `--overlay-uncommitted` copies modified files over the export.
- `scripts/p9/capacity.py` (generate, pdf-library, measure, summarize, table, limits) refuses ports outside the constant `PORTS = range(8900, 8921)`, refuses a
  data/library root that is not `/tmp/h5-*`, and writes raw output under `.local/p9-h5/`. `summary.json` has `rows[<K id>]` with `class` and `verdict` in
  `pass|fail|incomplete|measured`. `limits` prints the K07 table and exits 1 if a cell is empty. D166 says `run_matrix.sh` does not run it yet.
- Tests: default `pytest` (about 8,357 tests at 5b616e5, parallel by default) leaves out `-m process` (`tests/conftest.py`); the process tests need
  `-m process -n 0`. F09 at the production 1 GiB limit is two opt-in tests behind `DEIXIS_P9_PRODUCTION_THRESHOLD=1`
  (`tests/test_documents.py::test_extraction_is_stopped_at_the_production_memory_limit` and the one in `tests/test_arxiv_source_archive.py`).
- Playwright: `npm run test:acceptance` (full suite, `workers: 1`, 170 tests at 17b8341 including `e2e/a11y.spec.ts` with 28). Spec files use fixed ports
  (8777 to 8824, `a11y.spec.ts` 8820 to 8824); `a11y.spec.ts` refuses to start when its port already answers. The JSON reporter writes
  `$DEIXIS_ACCEPTANCE_DIR/results.json`. Specs A to G are in `e2e/acceptance.spec.ts` with titles starting `A:` to `G:`.
- Not in code: `docs/product/p9-acceptance-record.md`, any single command over the groups above, any mapping from a test to a matrix row.

## What to build

### 1. `scripts/p9/run_matrix.py` and a thinner `scripts/p9/run_matrix.sh`

`run_matrix.sh` keeps its name and becomes: refuse unless `uname -m` is `arm64`, then `exec` the repo venv's python (`.venv/bin/python`, falling back to
`python3`) on `scripts/p9/run_matrix.py "$@"`. `run_matrix.py` is standard library only. One command, `scripts/p9/run_matrix.sh`, runs these stages in
this order and then writes the table:

1. `preflight`: refuse (exit 2, nothing started) when `<repo>/.env` exists (plan §4 rule 5), when the Python that runs the script is not arm64
   (`platform.machine()`, not `uname`), when one of the ports 8950 to 8970 or one of the fixed Playwright fixture ports 8777 to 8824 already has a listener
   (the acceptance spec files other than `a11y.spec.ts` reuse a server that is already answering on their port, so a foreign server could be measured; the
   same check is repeated just before the `playwright` stage, and a busy port gives `ölçülmedi`, not a pass), when a model CLI or `tesseract` can be found on
   the stages' PATH, or when `uv`/`node`/`npm` is missing; record `uptime`, the commit hash, whether the work tree is dirty
   (`git status --porcelain`, read only), macOS/Python/uv/Node/npm versions, and the listener PIDs of port 8765 (read with `lsof`, never connected to).
2. `install`: `scripts/p9/install_check.py --port 8950 --out-dir <out>/install --work-dir /tmp/h1-install-matrix-<stamp>` (I01 to I05, I07, and its own
   `keyring` and `cleanup` rows). It exports a commit, so by default it tests `HEAD` while every other stage tests the working tree; `--overlay-uncommitted`
   is passed through only when the matrix command got it, and the record states which provenance each stage had.
3. `pytest`: the default suite, `-n auto`, with `--junitxml`.
4. `process`: `-m process -n 0` (I06, F01 to F06, F10, B01 process parts, B03), with `--junitxml`.
5. `f09`: the two production-threshold tests with `DEIXIS_P9_PRODUCTION_THRESHOLD=1`, `-n 0`, with `--junitxml`; a pass means two tests passed and none was skipped.
6. `web`: `npm run build`, `npm run lint` (warnings counted; baseline 17; a count above the baseline or any error fails the row `suite-web`). If
   `apps/web/node_modules` is missing the stage runs `npm ci` first and says so. The app serves `apps/web/dist`, so a stale or missing build would let the
   browser and capacity rows measure old code: the `playwright` and `capacity` rows are `ölçülmedi` ("depends on the web stage") unless `web` ran in this
   invocation and succeeded, whatever order or `--only` was used.
7. `playwright`: `npm run test:acceptance` with `DEIXIS_ACCEPTANCE_DIR=<out>/playwright`.
8. `capacity`: `capacity.py generate`, `pdf-library`, `measure` (points, `--pdf`, `--control`), `summarize`, `table` and `limits`, all roots under a fresh
   `/tmp/h5-matrix-<stamp>`, raw output under `.local/p9-h5/matrix-<stamp>/`, using the venv python. Because `PORTS` is a constant, add one environment
   variable to `capacity.py`: `P9_CAPACITY_PORT_FIRST` (default 8900; the range is that port and the 20 after it; the value must still keep every port out of
   8765 and 8858 to 8864), the run script sets it to 8950, the default behaviour and the existing test (`test_only_ports_8900_to_8920_are_allowed`) do not
   change, and the two error messages that name "8900 to 8920" use the real bounds. Delete the `/tmp/h5-matrix-<stamp>` roots at the end unless `--keep`.

Options: `--out-dir` (default `.local/p9-matrix/<stamp>/`, ignored by Git; it must not exist), `--only a,b` and `--skip a,b` (stage names; a skipped stage gives
its rows `ölçülmedi` with the reason "stage skipped", so a partial run can never print an all-pass table), `--overlay-uncommitted`, `--keep`,
`--self-test` (pure checks of the row mapping, no stage). Stages run even after an earlier stage failed (a failure is a result), except that a refusal in
`preflight` stops everything. Every stage logs to `<out>/<stage>.log`, records its command line, start and end time, exit code and `uptime` at its start and
end. Child environment: an allow-list named one by one (`PATH` = the venv's bin dir, a shim directory holding symlinks to `uv`, `node`, `npm`, `npx` only
(the tools live next to `claude` in `~/.local/bin` on this machine, so a directory entry would leak it), `/usr/bin:/bin:/usr/sbin:/sbin`; `HOME` (the real
one, as D161 says); `TMPDIR`;
`UV_CACHE_DIR`; `PYTHONPATH=backend:.`; `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring`; `LANG`; the stage's own variables), never the live data
directory, never a model CLI on `PATH`. No stage may write to `~/Library/Application Support/DEIXIS`; no stage connects to port 8765.

After the last stage: list listeners on 8950 to 8970 and 8777 to 8824, any process whose command line mentions the out dir or a `/tmp/h5-matrix-*` root, a
mounted `deixis-h3` disk image, the install work folder, the capacity root and `h5-run-*` repetition folders newer than the run (all must be empty;
a leftover is a failure of the row `cleanup`), re-read the 8765 listener PIDs (record only), and write `<out>/matrix.json` and `<out>/matrix.md`.

### 2. The row table

A static table in `run_matrix.py` lists every row of plan §4 with `id`, a short claim, `class` (`zorunlu`, `isteğe bağlı`, `yalnız ölçüm`), `kind`
(S, G, A, E, M) and an evidence rule. Classes: mandatory are I01 to I07, F01 to F04, F06, F07, F08, F09, F10, B01, B01n, B03, A to G, X01 to X06 (as one row for X01 to X04), and the K rows
that `capacity.FROZEN` calls `mandatory` (K01a, K01b, K02a, K02b, K03a, K06a, K07); the K rows take their class from `capacity.FROZEN` only (`mandatory` is
`zorunlu`, `measure only` is `yalnız ölçüm`), there is no second copy. Optional: B02, I08, F05, X07, R01, R02 and D01 to D06 (the H7 items; the plan names them
`D01…`, the id `D` stays the A to G case). Added mandatory rows that no plan row names, so a failure outside the map cannot pass: one per stage
(`suite-pytest`, `suite-process`, `suite-web`, `suite-playwright`, `suite-capacity`: exit code 0 and no failed or errored test, mapped to a row or not) and the
install check's own `install-keyring` and `install-cleanup`, and the run's `cleanup` row.
Evidence rules:
- `install`: the row's `result` in install `results.json` (`pass` is geçti, `fail` is geçmedi; `not_measured`, `pending`, any other value and a missing file are ölçülmedi). I08 is `ölçülmedi` ("E, not run by
  the harness; not done in H1").
- `junit`: a row owns a list of (file pattern, test-name pattern) pairs over the `pytest` and `process` junit files. Result: geçti if at least one test
  matched and every matched test passed (skipped counts as ölçülmedi, never as a pass); geçmedi if one matched test failed or errored; ölçülmedi if
  nothing matched (a renamed test must show up as a missing row, not as a pass). The count of matched tests is printed. Mapping (check the names with
  `--collect-only`; do not guess): I06 `tests/process/test_p9_crash.py::test_i06*`; F01 `test_p9_crash.py::test_f01*`; F02 `test_p9_files.py`; F03
  `test_p9_backup_kill.py` and `test_p9_restore_process.py::test_f03*`; F04 `test_p9_shutdown.py`; F05 `test_disk_full.py` and
  `tests/test_p9_faults_documents.py::test_o12*`; F06 `test_library_open_faults.py` and `test_p9_restore_process.py::test_b03*`; F07
  `tests/test_p9_faults_providers.py`; F08 `tests/test_p9_faults_documents.py::test_d*`; F10 `test_p9_restore_process.py::test_f10*`; B01
  `tests/test_p9_restore_matrix.py::test_b01_*` and `::test_a_restored_library_shows_the_model_connection*`; B01n `test_p9_restore_matrix.py::test_b01n_*`; B03
  `test_p9_restore_matrix.py::test_b03_*` and `test_p9_restore_process.py::test_b03*`; D `tests/test_p9_h7_*.py`. F09 owns the two `f09` tests.
  B02: the matrix does not open the owner's library, so the row is `ölçülmedi` here; the tooling tests (`test_b02_*`, `tests/test_p9_upgrade_check.py`)
  are listed as a note. Keep every pattern in one table so the unit test can check each one matches at least one collected test.
- `playwright`: the row's specs in `results.json` (a spec is passed when all its results are `passed`; `skipped` is ölçülmedi). A to G: specs in
  `acceptance.spec.ts` whose title starts with the letter and a colon; X01 to X04 together: specs under a suite or title containing `X01-X04` in
  `a11y.spec.ts`; X05: containing `X05`; X06: containing `X06` except the spec titled `400%` (recorded, not mandatory, inside the X06 block). X07: `ölçülmedi` ("E, VoiceOver, not run"). The whole-suite counts (passed, failed, skipped, total) are printed.
- `capacity`: K rows from `summary.json` (`pass` is geçti, `measured` is geçti with class `yalnız ölçüm`, `fail` is geçmedi, `incomplete` is ölçülmedi),
  K07 from `limits --out <summary folder>` exit code 0 and the printed table holding no "not measured yet" cell (`judge_limits` counts any text as filled). A repetition flagged `load_high` is counted and printed as a note; it does not change a verdict (the thresholds were frozen
  under load, D166).
- R01, R02: `ölçülmedi` ("M, real model, H9/H10 not run").
Each row prints: id, class, kind, result (one of geçti, geçmedi, ölçülmedi, desteklenmiyor), evidence (matched count, file or stage) and a note column. A
`desteklenmiyor` result is for a row whose environment is outside plan §2; the table has none today, but the code must accept it.
The 400% layout spec inside the X06 block is excluded from row X06, but a failed spec still fails `suite-playwright` (the suite row wins: no failed spec, mapped or not). Exit status: 0 when every mandatory row is geçti, 1 otherwise, 2 for a refusal.

### 3. Tests (`tests/test_p9_run_matrix.py`, default run, no processes started)

Pure functions only, on synthetic junit and Playwright JSON snippets and on a real `--collect-only` listing: the row mapping (pass, fail, skipped, nothing
matched, mixed), a pattern that matches no collected test fails the test, class lookup, the all-mandatory-pass exit rule, a skipped stage gives
`ölçülmedi`, the refusal rules (`.env`, busy port, wrong architecture) and the cleanup check. Do not run a stage in a test.

### 4. The record: `docs/product/p9-acceptance-record.md`

English, plain prose (the plan itself is Turkish, but the decisions and the other records are English; the matrix words geçti, geçmedi, ölçülmedi and
desteklenmiyor stay as the plan wrote them). Sections:
1. Header: date, commit, what a reader should not conclude (the plan §4 closing sentence and §10).
2. Supported environment (plan §2, with what was observed) and the baseline counts (D139 as found, and the counts of the two closing runs).
3. Matrix result, row by row: id, class, kind, execution type, data/model reality (two separate fields, plan §4 rule 4), result of the closing runs, the
   earlier recorded measurement (decision number and date) and what the row does not show. E and M rows are linked to their earlier record (date,
   environment, provenance); they are not re-run.
4. Known bugs and open observations: every "left open" item from D138, D139, D159, D161 to D167 (D167's "Known findings" included), each with its
   source decision, whether it is a defect, a limit or an observation, and severity in the H7 sense (a data loss, b blocks work, c misleading text, d cosmetic).
   Read the decisions; do not summarise from this prompt.
5. Capacity limits: the table of `capacity.py limits`, the K01 to K07 numbers of the closing runs, the documented limits without a threshold (view call
   linear in works and blocks the event loop for its duration, Sources list not virtualized, opening a passage from the list), and the supported upper
   size (10,000 works in one research, as measured).
6. Not measured: the report on a real model (H9, R01), real-model call repeat after SIGKILL (H10, R02), I08 second user, screen readers other than
   VoiceOver and VoiceOver itself (X07), older macOS, Intel, Linux, Windows (desteklenmiyor, P10), power loss and kernel panic, another machine, a quiet-machine
   re-run of H5, text-only zoom, B02 re-run, and whatever the decisions' Limits sections add.
7. Sol re-review debt: the list of P9 commits reviewed by Opus 5.5 high with a GPT re-review pending (take the hashes from `git log` on main for D138 to D167
   and this batch; mark the ones whose last fix was not reviewed, such as D167's `focus.ts` fix after round 4).
8. P9 exit condition, item by item (see below).
9. Owner decisions that are still open (S4 was answered for B02; S8 I08; S9 daily-use log; S11 H10).

### 5. The decision `## D168 — P9 model-free hardening closes ...` at the top of `docs/decisions.md`

Status/Date/Context/Decision/Limits like D161 to D167. Status line: `accepted (implemented, uncommitted; reviewer: Opus 5.5 high (Sol quota out), Sol re-review
pending)`. The number D168 is a placeholder if main took another number in the meantime (check `git log origin/main` is not needed; just read the top of the file).
State the evidence level openly: automatic rows on one machine, scripted model and synthetic records, a closing run under foreign load (record the load
averages), the I08 second-user claim not made, H9 and H10 not done, and that "closes" means the model-free matrix passed, not that the product is verified.

### 6. Status lines

`docs/README.md` and `README.md`: update the status wording to say P9's model-free part closed, with the record's link; do not rewrite anything else. Add a
one-line status for H8 to the plan's §4 status paragraphs or §5 H8 block, like the other batches did.

## Exit check (the batch is not done until both are recorded)

Run `scripts/p9/run_matrix.sh` end to end twice in this worktree, one after the other, each in the background with `nohup`, each under its own `--out-dir`.
Record `uptime` at the start of each. Compare the two `matrix.json` files: the per-row result must be identical (times, RSS and counts that vary are not
compared). If they differ (D162 says load can push the shutdown tests into the forced-exit path; D166 and the F09 smoke runs say timing and memory
pressure matter), do not pick one: report the difference and its cause, and run a third time only to understand it, never to replace a failed run. Every mandatory row must be geçti. A mandatory row that fails: stop, report it as the first line of the final report, put it in the record as
geçmedi, and do not write "closes". Before writing "closes", apply plan §4 rule 2 to section 4 of the record: no open severity-(a) item (data loss or evidence integrity), no unenforced
security limit (F09 included), no serious or critical accessibility defect; otherwise the decision says "does not close" and why. State the provenance
stage by stage (install tested `HEAD` or the overlay; the other stages the working tree; this worktree had `.venv` and `node_modules` installed before the run, so
the cold-install timings are those of I01 only). Mark the P9 exit condition item by item in the record: (1) repeatable install in the supported environment (I01 to
I05, I07 pass in both runs; I08 not done, so no second-user claim), (2) acceptance matrix (the run), (3) known bugs open (section 4), (4) capacity limits
open (section 5), (5) what the model-free close does not cover.

## Checks

`PYTHONPATH=backend:. .venv/bin/python -m pytest tests/test_p9_run_matrix.py tests/test_capacity_script.py -n 0`, the full default pytest (once, with the
matrix runs or separately), `git diff --check`, every relative link in the new and changed docs resolves, every command written in the record or the README
exists (`scripts/p9/run_matrix.sh --self-test`). `npm run lint` stays at 17 warnings; no web source change is expected.

## Files allowed

`scripts/p9/run_matrix.sh`, `scripts/p9/run_matrix.py` (new), `scripts/p9/capacity.py` (the port variable only), `tests/test_p9_run_matrix.py` (new),
`docs/product/p9-acceptance-record.md` (new), `docs/product/p9-hardening-plan.md` (a status line), `docs/decisions.md` (D168), `docs/README.md`, `README.md`,
this prompt. Not allowed: anything under `backend/` and `apps/web/src`, a migration, a contract, `methods/`, an existing test (except to add the port-variable
case to `tests/test_capacity_script.py` if needed).

## Do not invent

If a row, a number or an open item cannot be found in the decisions or in a run, write `ölçülmedi` or "not found" and say where you looked. Do not turn a
note into a pass. Do not change a frozen threshold. Report every own-judgement decision.

## Own-judgement changes made while building (after the prompt was reviewed)

The stage order that ran is: preflight, f09, process, install, pytest, web, playwright, capacity (not the order written in section 1). The parallel pytest
stage keeps the 1-minute load high for minutes afterwards and the process tests and F09 are wall-clock, so they run first. The three wall-clock stages
(f09, process, capacity) wait up to 10 minutes for a 1-minute load below 4 and at least 50 percent free memory (`memory_pressure`) and record what they
started at; a failure that started above those limits carries a note saying so. Reason: F09 failed in four trial and closing runs when the machine was loaded
or short of memory (the child's growth to 1 GiB is slow and the 90 s extraction clock or the child's 100 s lifetime alarm ends it first), and passed in 26 to
57 s when it was not. A hang-up is not handled when `nohup` ignored it. Each stage runs in its own process group; a signal ends the group, then everything
whose command line names the output folder, then detaches any disk image of the run, then still writes `matrix.json` with the unfinished stages `ölçülmedi`.
A bug found on the way: blocking the handled signals around `Popen` made every child inherit a blocked SIGTERM (17 process tests and I02 failed); the child
unblocks them itself and a test pins it.
