<!-- PLAN-REVIEW-ROUNDS: r1 (gpt-6.1-sol medium): düzeltmeyle hazır, 5 high + 3 medium + 1 low, all folded in; r2: düzeltmeyle hazır, 2 high + 2 medium, all folded in; r3: düzeltmeyle hazır, 1 high + 1 medium, folded in; r4 (last round allowed): düzeltmeyle hazır, 1 high (do not forward cancellation to the arXiv child task), folded in by the orchestrator without a fifth round -->


# Task: P9 re-extraction batch R2c, crash reconciliation of recovery operations, reader locks, crash boundaries, parser limits and full-disk refusal

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-reextract-r2c`, detached at `87cee0b` (origin/main with R1 = D190, R2a = D191,
R2b = D192). Design: `docs/product/p9-reextract-design.md`, accepted as D176. Read all of it; sections 3.2 (the call boundary), 5.1, 5.2,
5.3, 9 (row R2c), 9.1 (T7) and 10 bind this batch. Also read `AGENTS.md`, `CLAUDE.md`, D190, D191 and D192 in `docs/decisions.md`,
`docs/product/p9-reextract-r2b-prompt.md` (the previous batch prompt), `backend/deixis/workflow/text_retry.py`,
`backend/deixis/workflow/file_restore.py`, `backend/deixis/workflow/worker.py`, and the R2a/R2b tests `tests/test_reextract_r2a_*.py`,
`tests/test_reextract_r2b_*.py` with `tests/reextract_r2a_helpers.py` and `tests/reextract_r2b_helpers.py`. Venv: `.venv` is a symlink to
the main checkout's arm64 venv. Run tests with `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest ...`.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted. No real-model
call, no provider call, no network. Do not touch `../DEIXIS*` worktrees, `TODO.md`, `.vscode/`, `scripts/local_index.py`, the live service on
port 8765 or the live data directory. **Do not edit** (other sessions own them or the batch does not need them): `backend/deixis/models/*`,
`backend/deixis/providers/*`, `backend/deixis/workflow/views.py`, `backend/deixis/workflow/review/*`,
`backend/deixis/workflow/report/*`, `backend/deixis/storage/*` (`db.py` and `backup.py` may be imported, not edited; no migration),
`backend/deixis/documents/*` except decision 5's changes to `MathReader.read` and `MathReader.close` in `documents/math_reader.py`, `scripts/*`,
`tests/process/*`, anything under `apps/web`, `contracts/`, `methods/`, `.impeccable.md`. In `backend/deixis/workflow/flow.py` change only
`_read_equations` (decision 5; P7 G1 B4 edits flow.py's provider dispatch at the same time). In `backend/deixis/api/app.py` change only the
lifespan (decision 3) and the extraction POST's no-body path (decision 8); in `backend/deixis/workflow/store.py` change only what decisions
2 and 4 name (P7 G1 B4 edits `store.py` at the same time; keep the diff small and local). Existing test files stay unchanged unless decision 11 names them. If R2c truly needs a forbidden file, stop and report
it. Do not invent; report what you could not find, run or measure.

## Why

D191 and D192 left four gaps that R2c closes. (1) A text retry or file restore whose process died stays `running` for ever: the next
retry of that asset is refused `operation_running` (`store.py:1972`) and the receipt never says what happened; the CLI even prints
"stays running until a later version reconciles it" (`__main__.py:224`, `:232`). Design 5.3: a stale operation is reconciled only by whoever
holds its file's lock, a text attempt becomes `interrupted` and is **never re-run**, and a file restore is reconciled from its recorded
observations and the file actually present. (2) The equation reader and the arXiv source route read the stored PDF without the per-file lock
(D192 carried "decisions about reader locks for OCR, equation reading and arXiv stamping"), so a restore or a text retry can interleave
with a read that later publishes an extraction. (3) Design 9 row R2c and T7 ask for crash-boundary evidence, the existing parser caps on
the retry path and real full-disk refusals, with "old or complete new head only; storage failure never reports recovery". (4) D191 carried
"the missing-file check before healthy `unchanged`": the no-body extraction POST still answers `unchanged` for a same-profile asset whose
file is gone. Still not done after R2c: backup and authorized purge of retained bytes and receipts, verified input observations for initial
attachments and ordinary upgrades, cited-occurrence views (R3); any UI (R4).

## What is and is not in code (checked on 87cee0b)

- **Liveness today.** Every text retry and every file restore holds `text_retry.file_lock(recovery_dir, sha256)` (exclusive flock on
  `recovery_dir/locks/<sha>.lock`, `text_retry.py:62-95`) from before its reservation until after its terminal commit
  (`text_retry.py:232-275`; `file_restore.py:143-223`). The only way a row stays `running` without its lock held while its process lives is
  a failed interruption write, kept in `Store.pending_text_retry_interruptions` / `pending_file_restore_interruptions` and flushed by
  `flush_text_retry_interruptions` (`store.py:1818-1836`) at the next driver call, capability read or `next_queued_run`. `next_queued_run`
  (`store.py:806-835`) already treats a running operation as live only when its lock is held (`lock_held`, `text_retry.py:98-118`), so a
  crashed row defers no run. flock conflicts between two descriptors of the same process too (R2b's in-process busy tests rely on it).
- **What a crashed row blocks.** `reserve_text_retry` refuses `operation_running` for any running `text_retry` row of the asset
  (`store.py:1968-1972`), so after a crash the asset cannot be retried again; the capability GET answers `operation_running` for it
  (`app.py:2155-2159`, pinned by `tests/test_reextract_r2a_api.py:446-461` case `crashed`). A crashed `file_restore` row blocks nothing but
  keeps a `running` receipt (`latest_file_restore` shows it) and R2b's scheduler query defers runs only while its lock is held.
- **Nothing reconciles.** `Worker.recover()` (`worker.py:67-83`) marks running steps/sessions `outcome_unknown` and running runs `paused`
  under the worker ownership lock (`worker.py:46-65`), called from the lifespan when the process owns the worker (`app.py:690`) or takes it
  over (`app.py:694-703`). No code reads a `running` recovery operation to end it. The interruption vocabulary is
  `TEXT_RETRY_INTERRUPTIONS = ("storage_full", "storage_unavailable", "cancelled", "unexpected_error")` (`store.py:32`), used by
  `interrupt_text_retry` (`:1804`) and `interrupt_file_restore` (`:1925`); `asset_recovery_operations.reason` is free text in 0066 (no CHECK),
  so a new interruption reason needs no migration. The frozen trigger allows `before_observation_id` and `after_observation_id` to be set once
  each while `running`, to an observation of this operation of the matching kind.
- **Restore ordering (R2b).** Reservation (`running` row) → retention copy, rename to `papers/retained-<observed>.bin`, directory fsync →
  `before_restore` observation and pointer committed → one `BEGIN IMMEDIATE` transaction holding only reads, the started-run check and the
  synchronous `os.replace(staged, target)`, then `COMMIT` → directory fsync → `after_restore` observation and pointer → completion. So: no
  `before_observation_id` means the target was never replaced by that operation; a `before_observation_id` without completion means the
  target may or may not have been replaced. R2b turns a failed commit after the rename into an interruption (or a pending one).
- **Text retry ordering (R2a).** Reservation → `extraction_input` observation and pointer → parse of a verified private copy (no DB write) →
  `complete_text_retry` (`store.py:1984-2047`): one transaction that supersedes the baseline, appends the candidate extraction and passages,
  updates the four asset mirrors, completes the operation and writes one `asset_text_retried` event per holding research. Its final checks
  (removed asset, holding research, membership, replaced bytes, baseline, started run, verified input) are read inside that transaction;
  `tests/test_reextract_r2a_api.py:334-368` exercises baseline, membership and run races from a second connection in the same process.
- **Readers without the lock.** `EquationService._read` (Marker, `equations.py:247-295`) opens the stored path four times
  (`pdf.extract_pdf` `:263`, `math_pages`/`table_pages` `:271`, `reader.read` `:281`, `check_equations` `:291`) and then calls
  `store.reextract_asset` (`:293`); `_eligibility` reads the arXiv stamp from the stored PDF once per asset and stores the eligibility row
  permanently (`equations.py:297-317`); `_read_source` reads it again (`arxiv_source.read_source` and `pdf.extract_pdf(path, placements=...)`,
  `equations.py:387-401`) before its guarded `reextract_asset`. Callers: the background loop `run_forever` (`:539-560`, which sleeps
  `RETRY_SECONDS` after `RunInProgress`), the retry route via `_retry` (`:513-519`) and, inside runs, `flow._read_equations` and
  `flow._read_source_equations` (`flow.py:2603-2650`), which treat a returned `pending` state as a finished step and only `failed` as a
  pause. The OCR run (`flow._pdf_ocr`, `flow.py:2502-2560`) reads inside a run of the research that holds the asset; a restore refuses at
  reservation while any holding research has a queued, running or pause-requested run, its final check is serialized with run starts, and
  `next_queued_run` defers runs while a restore or retry is live; a text retry reserves only without such a run and never changes file bytes.
  The PDF viewer and the figure route (`app.py:1949-1952`, `:1990-1997`) only display bytes.
- **Parser bounds.** `pdf.extract_pdf(path, max_chars=MAX_TEXT_CHARS, max_memory=MAX_MEMORY_BYTES)` runs a watched child
  (`pdf.py:379-420`): `MAX_PAGES = 400` and `MAX_TEXT_CHARS = 3_000_000` apply in the child (`pdf.py:58-59`, `:245`),
  `MAX_MEMORY_BYTES` (1 GiB) is passed to it, `TIMEOUT_SECONDS = 90` is read by the parent at call time (`pdf.py:67`, `:391`); a timeout,
  memory exit or crash returns a `failed` extraction, not an exception. The text retry calls `pdf.extract_pdf(copy_path)` with the defaults
  (`text_retry.py:254`). No test runs those bounds through the retry path.
- **Full disk.** `db.describe_failure` maps `OSError(ENOSPC/EDQUOT)` and SQLite result code 13 to `disk_full`/507 (`db.py:172-192`); the
  retry route and the upload routes wrap the work in `disk_full_refused()`. Existing tests produce real `SQLITE_FULL` with
  `PRAGMA max_page_count` (`tests/test_p9_h7_savepoint.py:18`, `tests/test_p9_rr_a_storage.py:145`,
  `tests/test_p9_faults_documents.py:318`); R2a/R2b inject SQLite failures with fake `sqlite_errorcode` exceptions and `ENOSPC` with
  patched writes.
- **Missing file before `unchanged`.** The no-body extraction POST returns `{"outcome": "unchanged", "reason": ...}` for a same-profile
  asset at `app.py:2129-2131`, before the existence check at `:2132-2135`.
- **Baseline**: the orchestrator's full run on this commit outside the sandbox: 11,856 passed, 0 failed, 2 skipped, 62 warnings in
  376.69 s (`/tmp/reextract-r2c-baseline.log`).

## Decisions taken where the design is open (use these; never ask)

1. **Names.** New module `backend/deixis/workflow/reconcile.py` holds `RECONCILE_REASON = "process_ended"`,
   `async reconcile_hash(store, papers_dir, recovery_dir, sha256) -> dict` (the caller already holds that hash's lock),
   `async reconcile_try_hash(store, papers_dir, recovery_dir, sha256) -> dict` (returns at once when no operation of that hash is
   `running`; otherwise tries the hash's lock **non-blocking**, skips on busy, else runs `reconcile_hash` under it and releases it) and
   `async reconcile_stale(store, papers_dir, recovery_dir) -> dict` (`reconcile_try_hash` for each distinct hash of a `running` operation).
   All return counts `{"text_retries": n, "file_restores": n, "live": n}`. Nothing ever acquires the same hash lock twice in one call path
   (flock on a second descriptor of the same process would refuse it). New tests in `tests/test_reextract_r2c_*.py` with a shared helper module if useful.
2. **Vocabulary** (`store.py`). Add `"process_ended"` to `TEXT_RETRY_INTERRUPTIONS` (one tuple, used by both interruption writers). It
   means: the process that owned the operation ended before writing a terminal state, and a later owner of the file lock found it running.
   No other reason or outcome changes; no migration.
3. **Who reconciles, and when.** Exclusive ownership of an operation **is** its file's lock (design 5.3: "the same cross-process lock").
   - `reconcile_hash` (lock held by the caller): first `store.flush_text_retry_interruptions()`; then every operation with that
     `expected_sha256` still `running` is stale, because every live operation holds this lock, **except** an ID still present in either of
     this Store's pending-interruption maps after the flush (its write failed again; it keeps its real reason and is left for a later flush,
     and is not counted as reconciled). Reconcile each other one per decision 4.
   - `reconcile_try_hash` / `reconcile_stale`: flush pending interruptions; select the distinct hashes of `running` operations (a plain
     query; the table is small and 0066 has no index for this, no migration is added); for each, try `file_lock` **non-blocking**;
     `FileBusy` → count `live`, skip (another process or an in-flight operation of this process owns it); acquired → `reconcile_hash` under
     it, then release. A lock `OSError` other than busy → log once per hash/errno for the Store's lifetime, count `live`, skip (conservative,
     like `next_queued_run`).
   - **Callers:** (a) the lifespan, when this process owns the worker, right after `worker.recover()` and `cancel_legacy_discovery()`, both in
     the owner branch and in `take_over_when_released`: `app.state.reconciled = await reconcile.reconcile_stale(...)`; (b) every worker turn,
     inside `Worker._turn` before `next_queued_run`, through a method that returns at once when `store.recovery_dir is None` or the store has
     no recovery schema (`_extraction_has_recovery_metadata`), catches `Exception` (logs once per exception type until a sweep succeeds) and
     never prevents the turn from picking a run; (c) **lazily** in `execute_text_retry` right after `file_lock` is acquired and before
     `reserve_text_retry` (`reconcile_hash`, lock already held), and in `restore_file` **before** its whole-file fast path
     (`file_restore.py:141`; `reconcile_try_hash`, which takes the lock only when a `running` operation of that hash exists and releases it
     before the fast path, so the fast path and `writer_lock` keep R2b's behavior; busy → skip and continue as R2b). The whole-file fast
     path must not leave a crashed receipt of its own hash running when its lock is free. Then, right after `writer_lock` succeeds and
     before the under-lock re-inspection, `restore_file` also calls `reconcile_hash` (lock already held, no second acquisition), so a holder
     that died while this writer was waiting is reconciled before the file is touched. In (c) a storage failure propagates (the route maps it to 507/503 as today; the staged file is cleaned by
     R2b's ownership rule) and no operation is reserved. In (a) and (b) a failure is logged and the row stays `running` for the next sweep;
     the app still starts.
   - A replay of an idempotency key whose row is `running` keeps R2a's behavior (no lock, returns the stored state with 202); after
     reconciliation the same key returns the stored `interrupted` state (design 5.3). The capability GET is unchanged and still answers
     `operation_running` for a running row (R2a test `crashed` stays as it is); the worker sweep ends a crashed row within one turn.
   - No reconciliation path parses, copies the input, calls OCR, the equation reader, acquisition, providers or models, or creates an
     extraction, passage or operation. There is no automatic text retry anywhere.
4. **What reconciliation writes.**
   - `text_retry` row: `store.interrupt_text_retry(oid, "process_ended")`. Its `extraction_input` observation, if recorded, stays linked.
     `complete_text_retry` is one transaction, so a running row never has a candidate extraction; reconciliation checks that no
     `asset_extractions` row has `recovery_operation_id = oid` and, if one does, logs an error and leaves the row running (an impossible
     state must not be relabelled).
   - `file_restore` row with `before_observation_id` NULL: the target was never replaced by it; `interrupt_file_restore(oid,
     "process_ended")`, no new observation. A `retained-*.bin` or `.part` file left by the crash is not evidence and is neither referenced,
     promoted nor deleted (design 5.2; R3 decides backup of unreferenced retained files).
   - `file_restore` row with a `before_observation_id`: inspect `papers/<sha>.pdf` with `pdf_files.inspect_file` in `drained_thread`
     (no-follow, through one descriptor). Present regular file or absent: if `after_observation_id` is NULL, record an `after_restore`
     observation of what is present (`verified`, `mismatch` or `missing`, with observed digest/size) through
     `record_file_restore_observation`; then `interrupt_file_restore(oid, "process_ended")`. A non-regular entry (`FileNotRegular`): no
     observation, interrupt. The operation is **never** completed as `file_restored` by reconciliation, even when the file is now whole:
     the receipt says the operation did not finish and records what the file is now (design 5.2: "a recoverable operation, not a success
     toast"). The target is never written, renamed or deleted; retained bytes stay.
   - Each writer emits its existing event (`asset_text_retried` / `asset_file_restore_finished`) with `reason = "process_ended"`, exactly
     once; a second sweep finds nothing. Every reconciliation write, of either kind, runs inside R2b's rollback wrapper
     (`file_restore.transaction`, which closes a transaction left open by a failed `COMMIT`); `flush_text_retry_interruptions` also wraps
     its pending **text** interruption writes in it (today only the restore half is wrapped, `store.py:1818-1836`), so no reconciliation or
     flush can leave an uncommitted interruption and the write lock behind after the file lock is released. A crash during reconciliation itself
     leaves at most an `after_observation_id` already set, which the next reconciliation reuses instead of recording another.
5. **Reader locks** (`equations.py`). `EquationService` gains one helper that returns
   `file_restore.resolve_recovery_dir(self.store, self.papers_dir)` and takes `text_retry.file_lock(dir, asset["sha256"])` **non-blocking**,
   once per read, never nested. **Only for a valid stored hash** (`text_retry.HASH`, lowercase 64-digit hexadecimal): an asset whose
   stored `sha256` is anything else (no application writer produces one; several existing synthetic fixtures do, e.g.
   `tests/test_equations.py:52` `"sha-paper"`, `tests/test_arxiv_source_route.py:108`, `tests/test_ocr.py:99`) is read without the lock,
   because no writer or retry can lock, restore or retry such a path either (`file_lock` and `restore_file` refuse invalid hashes), so
   there is nothing to exclude. `file_lock`'s validation is unchanged and those fixtures stay unchanged. A guard test pins both branches.
   - `_read` (Marker): after the existing state checks and before **any** write or file read of this attempt (before `pdf.extract_pdf`
     and before `_forget_failure`), take the lock and hold it through `store.reextract_asset` or `_record_without_passages`, so no restore or
     text retry of that file runs between reading and publishing.
   - `_read_source` (arXiv): take the lock once, right after the `route_active` check and before `_eligibility`, `sources.reset`, any
     `_forget_failure`, `sources.ensure`, `sources.read`, `arxiv_source.read_source`, `pdf.extract_pdf(path, placements=...)` and the final
     guarded `reextract_asset` / `_record_source_rejection`, and hold it to the end of the method (fetching and the rate gate included: one
     region is simpler than revalidating state after a gap; `arxiv-sources/*.src` writes are not hash paths and keep their own locks).
     `_eligibility` itself takes no lock; it is only called from inside this region, so the permanent `asset_arxiv_versions` row is never
     written from a stamp read without the lock.
   - On `FileBusy`: nothing has been written or read yet by construction (no failure row, no attempt counted, no `_forget_failure`, no
     source reset, no event, no reader or parser call); return `equation_state(self.store, asset_id) | {"outcome": "file_busy"}`.
     `run_forever` sleeps `RETRY_SECONDS` after a `file_busy` outcome (as after `RunInProgress`), so the background loop does not spin.
     `_retry` needs no change.
   - **Runs** (`flow._read_equations`, `flow.py:2603-2624`, the only flow edit): a returned `outcome == "file_busy"` finishes the step
     `succeeded` with that output and never pauses the run, even when the state is `failed` (a failed read with attempts left goes back to
     `read_asset`, which can now answer busy). `_read_source_equations` already finishes `succeeded`; no change there.
   - **Cancellation and child processes.** No lock is released while a thread or child process of the read can still touch the file: every
     `asyncio.to_thread` call inside the locked region becomes `text_retry.drained_thread`; on `CancelledError` (or any exception) inside the
     region, `_read` awaits the reader's close before the lock is released, repeating the shielded await through further cancellations
     (drained_thread's pattern). `MathReader` changes (its only changes): `read` drains its own `inline_math_marks` thread
     (`math_reader.py:298`) on cancellation before re-raising, with a local helper of the same semantics (`documents/*` must not import
     `workflow/*`); `close` becomes one shared close task per process (created on the first call, awaited by every concurrent caller:
     preemption at `equations.py:242`, shutdown at `:578`, a cancelled `_read`), which closes stdin, waits, kills after its timeout and
     then **awaits** the kill (`process.wait()`), so the Marker process is reaped before any caller returns. `close` never takes
     `MathReader.lock` (`read` calls `close` while holding it, `math_reader.py:305`). `EquationService.stop` awaits its cancelled tasks
     (catching their `CancelledError`) after cancelling them, so shutdown does not release a file lock while a read is still unwinding. `arxiv_source.run_child` kills and awaits its
     child in `finally` (`arxiv_source.py:1121-1132`), but those awaits are not shielded, so a second cancellation could cut them short:
     in `equations.py`, run `arxiv_source.read_source(...)` as its own task and await it with drained_thread's pattern: **never cancel
     that task**; on cancellation keep shield-awaiting it through further cancellations until it ends by itself (bounded by `run_child`'s
     own timeout and memory watch), then re-raise `CancelledError` without publishing its result, before the lock can be released. A cancelled read
     publishes nothing.
   - The OCR run takes **no** reader lock: it reads only inside a run of a research holding the asset, and the run rules above already
     exclude restores and retries of that file for its duration. A guard test pins this (decision 10). The PDF viewer and figure routes
     only display bytes and take no lock (Limits).
   - Holding the lock during a long Marker read means a text retry of that file answers 409 `file_busy` and a restore waits 10 s and then
     answers 409 `file_busy` until the read ends; this is intended and recorded in Limits.
6. **Crash boundaries are a test obligation, not new production hooks.** No production code gains crash or fault hooks. Tests kill a real
   child Python process with `os._exit(137)` at named points by monkeypatching inside the child, then reopen the library in the parent
   (SQLite's WAL drops the uncommitted transaction) and check the invariants before and after reconciliation. Placement rules: "after a
   method/commit" = a wrapper that calls the real method (or leaves the transaction context) and then exits; "after statement X inside a
   transaction" = exit when the next statement is about to run (a `set_trace_callback` fires **before** a statement executes, so it marks
   the boundary after the previous one) or a wrapper around the helper that issued X; the retention rename (`os.replace` whose destination
   is `retained-*.bin`) and the target replacement (destination `<sha>.pdf`) are distinguished by destination in a wrapped `os.replace`.
   Each child prints a handshake line before parking or dying; the parent reads with a bounded timeout (30 s), kills and reaps the child on
   timeout, and asserts the child's exit code (137) so a test never passes because the child failed early.
7. **Parser limits on the retry path.** No limit changes. The retry and the equation reader keep calling `pdf.extract_pdf` with its
   defaults; tests prove that the retry path keeps them and that a bounded failure is an operation result, not a crash or a success.
8. **Missing file before `unchanged`.** In the no-body path of the extraction POST, run `text_retry.precheck(settings.papers_dir,
   asset["storage_path"])` **before** the same-profile shortcut; `FileMissing` keeps its existing global 404 handler. Only presence and
   regular-file status are checked (no hashing on this path); a torn same-profile file still answers `unchanged` (Limits). The older-profile
   path is unchanged.
9. **CLI.** The two "stays running until a later version reconciles it" messages (`__main__.py:224`, `:232`) become
   `"The text retry operation stays running until DEIXIS reconciles it (at its next start, while it runs, or at the next retry of this file)."`.
   Exit codes do not change. The CLI retry reconciles lazily through `execute_text_retry` (decision 3c); the CLI never reconciles an
   operation whose lock another process holds.
10. **Required tests** are listed in the next section; the R2a/R2b fail-on-call fakes pattern applies to every reconciliation test.
11. **Existing tests.** Expected changes, each minimal and reported: `tests/test_reextract_r2a_api.py::test_second_store_reservation_and_
    other_research_queued_run_refuse` (a reservation written by a second Store **without** the lock is now, by definition, a crash
    leftover: split it into "lock held by a child process → 409 `file_busy`, row stays running" and "no lock → reconciled `process_ended`,
    the new retry proceeds"); `tests/test_reextract_r2a_cli.py:101` (the message text). Any other existing test that breaks: report it with
    the reason before editing it; do not weaken an assertion to pass.

## Tests that must fail on the old code, and regression guards

Name each test's role: **red on old** (the first assertion fails on `87cee0b` for the defect named), **guard** (passes on both) or **new
contract** (exercises something that does not exist on `87cee0b`; name its paired red-on-old or guard assertion). The orchestrator re-runs
the red-on-old ones against a clean copy of `87cee0b`. Each red-on-old test's **first** assertion is behavioral and old-compatible (only
routes, tables and functions present on `87cee0b`). Synthetic PDFs from `tests/helpers.py::make_pdf`; libraries in `tmp_path`; API tests use
`create_app(..., start_worker=False)` unless the test is about the lifespan or the worker; child processes get `PYTHONPATH=<worktree>/backend`
(plus the worktree root when they import `tests.*`) and `DEIXIS_DATA_DIR` of the temporary library. **Parser spy**: `pdf.extract_pdf`,
`ocr.read_page`, the math reader, adapters and the HTTP transport monkeypatched to raise in the parent process during every
reconciliation, startup and sweep assertion.

- **R1 (red on old): a crashed text retry no longer blocks the asset.** A child process runs a real retry (`execute_text_retry` through the
  CLI or a small script) on a failed same-profile asset and `os._exit(137)`s inside the parser. Parent: a fresh retry POST with a new key →
  first assertion: status 200 and outcome `promoted` (old: 409 `operation_running`). Then the crashed row is `interrupted` /
  `process_ended` with its `extraction_input` observation kept, exactly one `asset_text_retried` event for it with that reason, and a replay
  of the crashed key returns the stored interrupted view. Also through the CLI: a second `deixis reextract --retry` after the crash
  reconciles and retries (exit 0).
- **R2 (red on old): startup reconciles.** The same crash, then `create_app(start_worker=True)` lifespan → first assertion (SQL): the row is
  no longer `running` (old: running). Then `process_ended`, `app.state.reconciled` counts, no extraction/passage/operation added, parser spy
  silent, head unchanged. Same for a crashed `file_restore` (R3/R4 below) through startup.
- **R3 (red on old): file restore crash boundaries.** A child runs a generic upload of the full bytes over the torn shared file (R2b's
  seed) and dies at each point: after reservation; after the retained rename and before the before observation commits; after the before
  observation; after the target `os.replace` inside the replacement transaction (before `COMMIT`); after that commit; after the after
  observation.
  Parent, before reconciliation: target either still the torn bytes or whole (never anything else), no `asset_extractions` or passage
  change, the old head current. After reconciliation (startup, worker sweep or a later upload's lazy path, one parametrization each):
  first assertion `lifecycle != 'running'` (old: running); each parametrization reaches reconciliation only through an old-compatible
  entry point (the lifespan with `start_worker=True`, a worker turn, a later same-hash upload POST, including one over the already whole
  target that takes R2b's fast path), never by importing `reconcile` before the first assertion; then `interrupted` / `process_ended`,
  never `completed`; an `after_restore`
  observation exactly when a before observation existed (integrity `mismatch` when the crash preceded the rename, `verified` after it), the
  retained file and the before observation kept, one `asset_file_restore_finished` event; a later same-hash upload behaves as R2b
  specifies (restores, or `reused` when the file is already whole) and `latest_file_restore` names the newest operation.
- **R4 (new contract, paired with R1): text retry crash boundaries.** Child dies after reservation; after the input observation; inside the
  parser; inside `complete_text_retry` after supersession, after the candidate extraction insert, after the passages, after the mirror
  update, after the event insert (all before `COMMIT`); and after `COMMIT` before the lock is released. Parent: either the old extraction is
  current with its mirrors, passages and no completion event, or (after `COMMIT`) the complete new extraction is current with all its
  passages, matching mirrors and exactly one event per holding research; never a mixed passage set, half-updated mirrors or an event
  claiming promotion without promotion. Then reconciliation ends the uncommitted cases as `process_ended` and leaves the committed one
  untouched.
- **R5 (red on old): equation reader takes the lock.** A child process holds `file_lock` for the asset's hash; a background read
  (`read_asset(..., background=True)`) and the retry route's read with a fake installed Marker reader → first assertion: the fake reader
  and `pdf.extract_pdf` were not called (old: called). Then state stays `pending` (or `failed` with the same attempt count), outcome
  `file_busy`, no extraction row, no event. After release the same read runs. arXiv route: with the lock held, `_eligibility` writes no
  `asset_arxiv_versions` row and `_read_source` calls neither `read_source` nor `extract_pdf`; after release the row is written once.
  **New contract:** an in-run equation step (`flow._read_equations` with a fake reader) hitting `file_busy` finishes its step without
  pausing the run, parametrized over an initially `pending` asset and an initially `failed` asset with attempts left (the second pauses on
  old code for another reason, so it is new contract, not red on old); a text retry while a Marker read holds the lock answers 409
  `file_busy`; a restore waits and answers 409 `file_busy` when the read outlasts `WRITER_LOCK_WAIT_SECONDS` (patched small); a restore
  attempted while the arXiv route is parked inside `sources.ensure` (fake fetcher) is blocked the same way; the background loop with a
  busy file makes at most one read attempt per `RETRY_SECONDS` (patched small, counted). **Cancellation (new contract):** cancelling a
  Marker read parked in `reader.read` (fake reader whose process is a real child `sleep`), in a drained `pdf.extract_pdf` thread, and an
  arXiv read parked in `run_child` (cancelled while the child runs, again while it is being killed, and once during its timeout cleanup), and a Marker read parked in `inline_math_marks` → the hash lock stays held (a child `lock_held` probe
  answers true) until the thread has returned and every child process is reaped (`os.waitpid`/`returncode` set), then is released;
  nothing is published. Overlapping preemption (a run's read closing the background read's reader), `EquationService.stop()` and a
  second cancellation of the same read all await the same close and leave no unreaped process.
- **R6 (red on old): missing same-profile file.** No-body POST on a same-profile asset whose file was deleted → first assertion status 404
  "File missing" (old: 200 `unchanged`). **Guard:** present file → 200 `unchanged`; a symlink or FIFO at the path → 404.
- **R7 (new contract): exclusive reconciliation.** A child process runs a real retry parked in its parser (holding the lock). Parent:
  `reconcile_stale`, the worker sweep and the lifespan startup all count it `live` and leave it `running`; `next_queued_run` still defers
  the holding research; the child then finishes normally and its own terminal write stands (one event). Same with a restore parked in its
  retention copy. A pending in-memory interruption of this process is written with its own reason (e.g. `storage_full`), not
  `process_ended`; when that pending write fails once more during the flush, reconciliation leaves the row running, the entry stays
  pending, and the next successful flush writes `storage_full` with exactly one event. A failed `COMMIT` during a text or restore
  reconciliation write and during a pending text flush (connection wrapper) leaves `conn.in_transaction` false, the row `running` and no
  event visible from a second connection; the next sweep reconciles it once. **Writer waiting during a crash:** a child holds the hash
  lock inside a real restore (parked), a second upload of the same bytes starts and waits in `writer_lock`, the child is killed → the
  waiting upload reconciles the dead holder's receipt (`process_ended`) before it inspects the file, then restores or reuses. A row whose `recovery_operation_id` already has an extraction (seeded by direct SQL) is logged and left running.
- **R8 (new contract): no automatic text retry.** Over startup, ten worker turns, `reconcile_stale`, the capability GET and
  `next_queued_run`, with stale text and restore rows present: parser spy silent, no extraction, passage or operation added, the failed head
  unchanged; only an explicit POST retries.
- **R9 (guard/new contract): cross-process final-transaction races.** A child process (not a second connection in the same process), while
  the parent's retry is parked after parsing: promotes another extraction through `Store.reextract_asset`, removes the asset's source from
  the research, replaces the asset through `Store.replace_asset` with other bytes, or starts a run in another holding research → refusal
  with `baseline_changed`, `membership_changed`, `asset_removed` or `run_active`, head and mirrors as the child left them, no
  `promoted` event (guard: R2a's same-process races already pass on old; the removal and replacement cases are new).
- **R10 (guard): parser limits on the retry path.** (a) A spy shows the retry calls `pdf.extract_pdf` with only the private copy path, so
  the defaults hold. (b) `pdf.TIMEOUT_SECONDS` patched to a tiny value → the candidate is `failed` "extraction timed out", the operation
  completes `rejected` with the policy's decision code (expected `candidate_failed`; report the actual one), head unchanged, lock released, no child left (check with `child_guard`'s helpers or
  `os.waitpid` as the existing child tests do). (c) The parser called with `max_memory` tiny through a wrapper → "exceeded the memory limit"
  → `rejected`. (d) A 401-page synthetic PDF over a failed head → candidate `partial` because of the page cap, decision recorded
  (promoted `recovered_text` with pages 1-400), no page above 400. (e) `max_chars` small through a wrapper → truncated candidate recorded as
  the policy decides. None of these is an interruption or a 5xx.
- **R11 (new contract): real full disk.** `SQLITE_FULL` produced by `PRAGMA max_page_count` **on the connection that performs the
  write** (`store.conn`, or the lifespan's connection), no fake exception. Saturation must be deterministic per boundary: after seeding,
  fill until no free page is left and the table/index the boundary writes to cannot take another row without a new page (for example
  filler rows in a scratch table plus filler rows of the written table's own shape where its constraints allow, or a boundary write that
  allocates, such as passages); each test captures the exception raised at the named boundary (wrapper) and asserts its
  `sqlite_errorcode & 0xFF == 13`. If a boundary cannot be made to fail with a real `SQLITE_FULL`, say so in the report and keep R2a/R2b's
  injected error for it; do not claim it real. Boundaries: text retry reservation (507, no row, lock released); text retry final
  commit with many passages (507, row `interrupted` / `storage_full` or pending and flushed later after `max_page_count` is raised, head
  unchanged, no candidate passages, no `promoted` event); restore reservation (507, no row, staged file removed); restore before-observation
  commit (507, target still torn, row interrupted or pending, retained file kept); restore after-observation (target whole, row interrupted,
  never `file_restored`); reconciliation at startup with a full library (app starts, row stays `running`, after space returns the next sweep
  ends it with one event; apply the cap through a wrapper around the lifespan's `reconcile.reconcile_stale` call so migrations and worker
  ownership succeed first). `OSError(ENOSPC)` injected at: the text retry's private-copy write; the upload staging write; the retention
  copy **after some bytes were written** and the retention file's `fsync`; the target `os.replace`; the directory `fsync` after the
  replacement → 507 in each, partial copies removed, target bytes unchanged before the replacement point (replaced after it), retained
  bytes and before observation kept once committed, row `interrupted` / `storage_full` or no row before reservation. Every case: no
  response or event reports a recovered text or `file_restored`.
- **R12 (guard): OCR run excludes repair.** With an OCR run of the holding research `running`, a restore of that hash is refused
  `run_active` with no mutation and a text retry is refused `run_active`; no reader lock is taken by the OCR run.
- **R13 (guard): unchanged R2a/R2b behavior.** All `tests/test_reextract_r1_*`, `r2a_*`, `r2b_*` pass (with only decision 11's changes);
  the capability GET's `crashed` case still answers `operation_running` with start_worker false.

## Checks to run

Focused tests while building, then the whole suite inside your sandbox:
`PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest -q -p no:cacheprovider`. Tests needing sockets, process
listings or child processes that your sandbox blocks: list them by name; the orchestrator reruns the full suite outside the sandbox. Keep
child-process tests even if your sandbox cannot run them, and say so. Then `git diff --check`. No web change: no build, lint or Playwright run.

## Report and records

Write `/tmp/reextract-r2c-impl-report.md`: files changed, each decision's implementation with file:line, every test with its role and what
it shows, existing tests changed and why, full-suite counts with the failure list, what you could not do. Draft the decision entry at the top
of `docs/decisions.md`, above D192: `## D195 — P9 re-extraction R2c: a recovery operation left running by an ended process is reconciled by
whoever holds its file lock, never re-run; equation and arXiv readers take that lock; crash, limit and full-disk boundaries are tested` with
Status (accepted, implemented; writer gpt-6.1-sol high; leave the reviewer line for the orchestrator), Date 2026-10-03, Context, Decision
(the `process_ended` reason, lock ownership as liveness, the three reconciliation points, what is written for each operation kind and state,
never `file_restored` by reconciliation, no automatic retry, reader locks and `file_busy`, why the OCR run takes none, the missing-file check,
the CLI message), Verification (leave counts for the orchestrator), Carried work (R3: backup and authorized purge of retained bytes, receipts
and unreferenced retained files; verified input observations for initial attachments and ordinary upgrades; provenance views. R4: UI labels
for `process_ended`, `file_busy` equation outcome and the receipts), Limits (synthetic PDFs only; no real library; crash tests kill a
child Python process on macOS and do not show power loss or filesystem behavior; `ENOSPC` is injected, `SQLITE_FULL` is real; advisory locks
cannot stop outside processes; a pending interruption in another process may be relabelled `process_ended`; a long Marker read or an
arXiv read (including its source download) makes retries and restores of that file answer 409; viewer and figure routes take no lock and the figure cache keyed by hash can keep figures read
from torn bytes until restart; a torn same-profile file still answers `unchanged` to the no-body POST; Windows untested). Do not edit
`STATUS.md` (the orchestrator does).

## Do not

Re-run, retry or parse anything during reconciliation; complete a restore as `file_restored` from reconciliation; reconcile an operation
whose lock another holder has; write, rename or delete the target, retained or `.part` files while reconciling; let a reconciliation failure
stop the app or the worker loop; record an equation failure, attempt or eligibility row when the file is busy; add production crash hooks; add
a migration; edit `flow.py` beyond `_read_equations`, `documents/*` beyond `MathReader.read`, `MathReader.close` and their local draining helper in `math_reader.py`, `views.py`, `storage/*` or any
`providers/*` file; release a reader lock while a thread or child of that read is still running; change the text retry or restore success paths
beyond decision 3c's lazy call; let a cleanup failure hide the original error.
