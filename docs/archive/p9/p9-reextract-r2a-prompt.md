<!-- PLAN-REVIEW-ROUNDS: r1 (gpt-6.1-sol medium): düzeltmeyle hazır, 2 high + 7 medium + 1 low, all folded in; r2 (gpt-6.1-sol medium): düzeltmeyle hazır, 0 high + 8 medium, all folded in; r3 (gpt-6.1-sol medium): düzeltmeyle hazır, 0 high + 5 medium + 1 low, all folded in; r4 (gpt-6.1-sol medium, last round allowed): düzeltmeyle hazır, 0 high + 4 medium, all folded in by the orchestrator without a fifth round -->


# Task: P9 re-extraction batch R2a, the retry entry points: file lock, verified input, API, CLI and the run reservation policy

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-reextract-r2a`, detached at `2148c32` (origin/main with R1, D190). Design:
`docs/product/p9-reextract-design.md`, accepted as D176. Read all of it; sections 3.2, 5.1, 5.3 (last paragraph only, as a limit), 9 (row R2a),
9.1 (T1, T3, T6, T10's boundary sentence) and 12 (Q1) bind this batch. Also read `AGENTS.md`, `CLAUDE.md`, D190 and D176 in `docs/decisions.md`,
`docs/archive/p9/p9-reextract-r1-prompt.md` (the previous batch prompt, style model) and R1's tests `tests/test_reextract_r1_*.py`. Venv: `.venv` is a
symlink to the main checkout's arm64 venv. Run tests with `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest ...`.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted. No real-model call, no
provider call, no network. Do not touch `../DEIXIS*` worktrees, `TODO.md`, `.vscode/`, `scripts/local_index.py`, the live service on port 8765 or
the live data directory. **Do not edit** (other sessions own them): `backend/deixis/models/*`, `backend/deixis/providers/*`,
`backend/deixis/workflow/flow.py`, `backend/deixis/workflow/views.py`, `backend/deixis/workflow/review/*`, `backend/deixis/documents/*`
(`pdf.py`, `ocr.py`, `arxiv_source.py`, `jats.py` and the rest), `backend/deixis/storage/*` (no migration is needed in R2a; `db.py` and
`backup.py` may be imported, not edited), `backend/deixis/workflow/equations.py`, `scripts/*`, `tests/process/*`, anything under `apps/web`,
`contracts/`, `methods/`, `.impeccable.md`. Existing test files stay unchanged unless decision 11 names them. In `backend/deixis/api/app.py` change
only what decisions 6, 7 and 8 name (the extraction route at `app.py:2033-2045`, one new GET route placed directly after it, the request model, the
exception handlers, and the one line where the lifespan builds `Store`); three other batches edit nearby code at the same time. If R2a truly needs a
forbidden file, stop and report it. Do not invent; report what you could not find, run or measure.

## Why

D165/D169 left H7 finding 2 open: an asset whose stored extraction is `failed` (for instance a torn download parsed into zero pages) stays failed
after its bytes are repaired, because the extraction endpoint answers `unchanged` for today's extractor profile. D176 accepted the recovery design
and Q1's default: **re-upload restores bytes, records the outcome and offers one explicit retry; nothing retries automatically.** R1 (D190) built
the storage and policy: occurrence identity, migration 0066, the pure `recovery.decide`, and `Store.reserve_text_retry` / `complete_text_retry`,
with no entry point. **R2a builds the entry points and the shared policy around them:** one explicit, idempotent retry request through the existing
extraction endpoint and through the CLI; a cross-process lock per file hash; hashing a private copy of the stored file into an `extraction_input`
observation before parsing; the research membership check; and a worker that does not start a run while a live retry holds a source of its
research. After R2a, an existing failed or
partial same-profile row can be retried by a person. Still not done: `restore_file(op)` and repair receipts (R2b), reconciling a reservation left
`running` by a crash (R2c), cited-occurrence views, backup of retained files and the shared evidence helper (R3), any UI (R4).

## What is and is not in code (checked on 2148c32)

- **Extraction route** (`api/app.py:2033-2045`, `reextract_asset`): takes no body. `asset_in_use` (`app.py:1971-1978`) checks the research, active
  membership (`Store.is_active_member`, `store.py:2701`) and that the asset is the source's file in use. When the asset's version's first `+` part
  equals `pdf.EXTRACTION_VERSION` it returns `{"reextraction": {"asset_id", "outcome": "unchanged"}}` **before** checking the file
  (`app.py:2038-2039`), so a same-profile `failed`/`partial`/`no_text` row can never be retried. Otherwise it resolves the path
  (`is_relative_to(root)`, `exists()`; a symlink is followed by `resolve()`), parses with `pdf.extract_pdf` in a thread and calls
  `Store.reextract_asset`. No lock, no hash check of the stored file.
- **Store (R1)**: `reserve_text_retry(asset_id, *, expected_extraction_id, idempotency_key, request_fingerprint, research_id=None)`
  (`store.py:1703`) replays a key with the same fingerprint (returns the stored operation; the caller cannot tell a replay from a new
  reservation), raises `RequestConflict` for another fingerprint, `NotFound` for a removed asset, `RecoveryConflict("baseline_changed")`,
  `NotRetryable("already_current"|"pending")`, `RunInProgress` (any `queued`/`running`/`pause_requested` run in any research holding the source,
  `_asset_run_active`, `store.py:1666`), `RecoveryConflict("operation_running")`. `complete_text_retry(operation_id, extraction, chunker, *,
  input_observation_id)` (`store.py:1737`) requires a parsed plain text-layer `pdf.Extraction`; refusal reasons `asset_removed`,
  `no_holding_research`, `asset_replaced`, `baseline_changed`, `run_active` (it uses `_asset_run_active`, so a `queued` run also refuses),
  `input_not_verified`; it does **not** check that the requesting research (`operation.research_id`) still holds the source. There is no way to end
  a running operation without a parsed extraction (a missing file, a hash mismatch, an exception). `add_file_observation` (`store.py:1672`) records
  caller-supplied observations. Exceptions `RequestConflict`, `RecoveryConflict`, `NotRetryable` (`store.py:109-118`) have **no API handler**;
  `RunInProgress` maps to 409 (`app.py:784`), `RevisionConflict` to 409 with its text (`app.py:808-810`). R1's events carry no `lifecycle` field.
- **Runs**: every run is created by `Store.create_run` (`store.py:726`, the only runtime insertion into `runs` outside migrations), including the worker's
  follow-on runs (`flow.py:3923`, `3993`, `4037`), which are created in a separate transaction after the parent run completes and are not guarded
  against exceptions there; runs are also re-queued by `resume_run` (`:758`), `queue_failed_search_retry` (`:818`), `request_term_suggestions`
  (`:1019`), `submit_approval` (`:1044`), `choose_code_query` (`:1066`). The worker (`worker.py:128-154`) polls once a second: `next_queued_run`
  (`store.py:796`, oldest `queued` run) then, with no `await` in between, `update_run(..., status="running")`. Nothing looks at recovery operations.
- **Locks**: no lock keyed by a PDF's hash exists. The cross-process locks that do exist are unrelated: the worker's `fcntl.flock` on
  `settings.lock_path` (`workflow/worker.py:46-56`, with a `msvcrt` fallback), the arXiv source and the built-in embedding locks
  (`documents/arxiv_source.py:1177-1204`, `workflow/local_embedding_service.py:48-76`). `Settings` (`config.py:24`) has `data_dir`, `papers_dir`,
  `lock_path`; nothing for recovery.
- **CLI** (`__main__.py:131-160`, `reextract`): opens the library with `db.connect` and **migrates on open** (`:143`), selects in-use assets whose
  version is not today's profile or a suffix of it (`:144-148`), parses each file unlocked, and calls `Store.reextract_asset`; `--dry-run` passes
  `dry_run=True` but has already migrated. No single-asset option. `db._applied_versions_from_copy` (`storage/db.py:74-101`) reads a library
  without writing it: three bounded attempts of copying the main file and `-wal` into a temporary folder (`_copy_live_files`, `db.py:62`),
  comparing the main file's size and mtime before and after, and retrying when SQLite cannot read the copy.
- **Upload repair today**: `store_upload` (`app.py:588-622`) replaces a non-whole file under its hash name (`os.replace`); a source-specific upload of
  a hash the source already owns skips extraction (D165 limits), so the failed row stays. R2a does not change that path (R2b).
- **Equations (D52)**: `EquationService.next_asset` (`workflow/equations.py:521-537`) selects in-use `succeeded`/`partial` assets with pending or
  retryable reads, skipping sources held by a research with an active run. It does not look at recovery operations; a background read that writes
  a math occurrence while a retry is parsing moves the head, and `complete_text_retry` then refuses with `baseline_changed`.
- **Views**: `views.py:599` reports `current_extraction: true` for any same-profile asset (also a failed one) and exposes no extraction ID, so no
  page can supply `expected_current_extraction_id` today; R2a adds a read route in `app.py` for it (decision 8), the UI is R4.
- **Baseline**: the D190 rebase verification on this commit, outside the sandbox: 9,614 passed, 0 failed, 2 skipped, 62 warnings in 366.68 s.

## Decisions taken where the design is open (use these; never ask)

1. **Names.** New module `backend/deixis/workflow/text_retry.py` holds the file lock, the liveness probe, the verified copy and the one retry
   driver used by both the API and the CLI. Store changes stay in `workflow/store.py`. One property in `config.py`: `Settings.recovery_dir =
   data_dir / "recovery"` (subfolders `locks/` and `tmp/`, created on use with mode `0o700`). New tests in `tests/test_reextract_r2a_api.py`,
   `tests/test_reextract_r2a_store.py`, `tests/test_reextract_r2a_cli.py` (more files if needed).
2. **File lock.** `text_retry.file_lock(recovery_dir, sha256)` is a context manager taking an exclusive, **non-blocking** OS advisory lock on
   `recovery_dir/locks/<sha256>.lock` (`fcntl.flock(LOCK_EX | LOCK_NB)`; on Windows the `msvcrt.locking` pattern of `worker.py`); if another holder
   exists it raises `FileBusy` without waiting. `sha256` must match `^[0-9a-f]{64}$` (else `ValueError`), so no path can be built from untrusted text.
   Lock files are never deleted (deleting a lock file races with a second opener). `text_retry.lock_held(recovery_dir, sha256) -> bool` probes
   without creating anything: no lock file → `False`; otherwise open it read-only, try `LOCK_SH | LOCK_NB`, release at once; `True` only when that
   attempt fails with `EWOULDBLOCK`/`EAGAIN` (any other `OSError` propagates). A lock held through another open file description, in this process
   or another, counts as held; a test shows both (a separate `open()` in the same process, never `dup()` or an inherited descriptor, which share
   the lock, and a child process), shows that a probe does not weaken the holder's lock (after a probe a third `open()` still cannot take
   `LOCK_EX`), and shows an `OSError` from the probe propagating. The lock is per file hash, as design
   5.1 says, so R2b's `restore_file(op)` can take the same lock later. **In R2a the lock is taken by:** the retry driver (decision 5), the
   ordinary upgrade branch of the extraction route (decision 6), and the library-wide CLI upgrade per asset (decision 9). No other writer is changed
   (R2b).
3. **Verified private copy.** `text_retry.observe_copy(papers_dir, storage_path, expected_sha256, expected_byte_size, copy_path)` runs in a worker
   thread and never raises for a missing or wrong file; it returns `(integrity, observed_sha256, observed_byte_size)` and writes into the `copy_path` its caller created (decision 5).
   Resolution: `root = papers_dir.resolve()`; refuse a `storage_path` that is absolute or contains a path separator or `..` (stored paths are flat
   file names); `path = root / storage_path`; `os.lstat`: a symlink, a missing entry or a non-regular file is `missing` (observed fields NULL;
   wording below). Then open with `O_RDONLY | O_NOFOLLOW | O_NONBLOCK` (where defined; `O_NONBLOCK` so an entry swapped for a FIFO after the `lstat` cannot
   block the open), `fstat` the descriptor at once and continue only for a regular file (else `missing`), and stream: when the size differs from the
   expected size, hash the whole file without copying and return `mismatch`; when it is equal, copy into `copy_path` (truncating it)
   while hashing **the bytes written**, then `fsync`; the copy's digest decides `verified` or `mismatch` (the caller deletes the file in every case). The
   copy is parsed, never the live file. The observation stored is `kind = 'extraction_input'`, `operation_id` = the operation, `storage_path` =
   the asset's, expected = the operation's expected hash/size, observed = the copy's (or the file's) digest/size, integrity as returned. An
   `OSError` other than "not found / not a regular file / symlink" propagates (it becomes an interruption, decision 5). The copy is removed in a
   `finally` on every path; a test asserts `recovery/tmp` is empty after each outcome, including an exception.
4. **Store changes** (`workflow/store.py`):
   - `Store.recovery_dir: Path | None = None` (plain attribute). `create_app`'s lifespan sets it to `settings.recovery_dir` on the `Store` it builds
     (`app.py:648`); the CLI does the same. When it is `None` (tests building a bare `Store`), every running text retry counts as live.
   - **One stored-result serializer** `text_retry_view(operation_id) -> dict` used by every return path (fresh result, every replay, the
     capability route, the CLI line): the operation row plus `input_integrity` (from the stored observation row, NULL when none),
     `extraction_id`, `extraction_version`, `candidate_status` (from the extraction row whose `recovery_operation_id` is the operation, NULL when
     none), `coverage` (`{old_text_pages, new_text_pages, missing_pages}`, sorted page lists derived from the stored coverage JSON, NULL when the
     column is NULL). Nothing in it is taken from the in-memory request; a replay and the first answer are built the same way.
   - `text_retry_by_key(idempotency_key) -> dict | None`: the operation with that key, or `None`. Read only.
   - `reserve_text_retry` additionally returns `"replayed": bool` (true when an existing operation was returned). No other change to its checks.
   - `refuse_text_retry(operation_id, reason, *, input_observation_id=None) -> dict`: in one `transaction()`, a `running` `text_retry` becomes
     `completed`, `outcome = 'refused'`, the given `reason`, `decision_code = 'input_not_verified'` when the reason is `file_missing` or
     `file_mismatch` (else NULL), `input_observation_id` set, `finished_at`; writes **no** extraction or passage; one `asset_text_retried` event per
     holding research. A completed operation is returned unchanged (replay); an interrupted one raises `RecoveryConflict("operation_not_running")`.
     `reason` must be in the closed tuple `TEXT_RETRY_REFUSALS = ("asset_removed", "no_holding_research", "membership_changed", "asset_replaced",
     "baseline_changed", "run_active", "input_not_verified", "file_missing", "file_mismatch")`, else `ValueError`; `complete_text_retry`'s
     reasons are checked against the same tuple.
   - `interrupt_text_retry(operation_id, reason) -> dict`: a `running` operation becomes `lifecycle = 'interrupted'`, `outcome` NULL, `reason` in
     the closed tuple `("storage_full", "storage_unavailable", "cancelled", "unexpected_error")`, `finished_at`; one `asset_text_retried` event
     per holding research; no extraction or passage. A non-running operation is returned unchanged. Used only by the in-process driver when its
     own step fails (decision 5). A crashed process's `running` row is **not** touched by anything in R2a (R2c).
   - **Event payload, all three writers** (`complete_text_retry`, `refuse_text_retry`, `interrupt_text_retry`): `{asset_id, source_version_id,
     operation_id, lifecycle, outcome, reason, decision_code, extraction_version, baseline_extraction_id}`, i.e. R1's payload plus `lifecycle` and
     `reason`; an interruption has `lifecycle: "interrupted"`, `outcome: null`, exactly like its row. Report every R1 test this changes.
   - **The input observation is attached while the operation runs.** New `record_text_retry_input(operation_id, **observation fields) -> str`
     inserts the `extraction_input` observation (with `operation_id`) **and** sets the running operation's `input_observation_id` in one
     transaction (the R1 trigger allows that column to change while `running`). The driver uses it instead of a bare `add_file_observation`, so
     every later ending (promotion, rejection, any final refusal, an interruption) keeps the pointer; `refuse_text_retry`,
     `complete_text_retry` and `interrupt_text_retry` never clear it, and `text_retry_view` reads `input_integrity` through that pointer only.
   - **Pending interruption.** When `interrupt_text_retry` itself fails (the disk is still full, the event write fails), the driver records the
     operation ID and reason in `Store.pending_text_retry_interruptions` (an in-memory dict on the `Store` instance, the pattern of the worker's
     retained `_failed`, `worker.py:156-167`) and re-raises the original error. `Store.flush_text_retry_interruptions()` tries each pending entry
     once (a failure keeps it pending, never raises); it is called at the start of every `execute_text_retry`, of the capability route and of
     `next_queued_run`. Only an operation still `running` is interrupted by a flush. If the process ends before a flush succeeds, the row stays
     `running` and is a crash leftover (R2c); the CLI says so in its error line.
   - `complete_text_retry` additionally refuses with `membership_changed` when `operation.research_id` is not NULL and that research is no longer an
     active member holding the source (`is_active_member`), checked after `asset_removed` and before `asset_replaced`; and its `run_active` check
     counts only `running` and `pause_requested` runs (new private `_asset_run_started`), not `queued` ones (see the run policy below; a queued run
     cannot have started while the reservation was live). Nothing else in its decision order changes. `reserve_text_retry` keeps refusing
     `queued`, `running` and `pause_requested` runs.
   - **Runtime activation search (report it):** grep `backend/deixis` outside `storage/migrations` for every statement that inserts a run or
     sets a run's status to `queued`, `running` or `pause_requested`, and list each with file:line and why the policy below covers it.
   - **Run reservation policy (design 5.1 "all paths that create runs or publish evidence must respect a reserved recovery operation until it
     ends, or the final transaction must refuse promotion"): runs wait for a live retry.** No run creation or re-queue path changes and nothing
     raises: a run can still be created or resumed while a retry is running, and it stays `queued`. `Store.next_queued_run` returns the oldest
     `queued` run **whose research holds no source with a live text retry**, skipping (not failing) the others; it looks at every queued run in
     `created_at` order until it finds one. A text retry is live when the operation is `running` and `lock_held(self.recovery_dir,
     operation.expected_sha256)` is true, or `recovery_dir` is `None`. Membership is the set `_asset_researches` uses. The worker's 1 s poll
     picks the run up once the retry ends; the route also calls `request.app.state.worker.wake()` after the driver returns or raises. Why this
     shape: the worker's follow-on runs (`flow.py:3923`, `3993`, `4037`) and a person's waiting reading run are created after their parent run
     completed, with no handler for a new exception there; deferring the start keeps every creator unchanged, and a run that has not started has
     read nothing. Guarantees to test: (a) reserve refuses when any holding research has a queued, running or pause-requested run; (b) while the
     driver holds the lock, a run queued in a holding research is not started; (c) `complete_text_retry` refuses `run_active` when a run in a
     holding research is `running` or `pause_requested` at the final transaction (the race where the worker started a run between its poll and a
     reservation made by another process); (d) **a reservation left `running` by a crash holds no lock, so it defers no run**; it still blocks a new
     retry of that asset (`operation_running`) until R2c, as D190 records. A paused run stays paused and may be resumed; its earlier frozen inputs
     are protected by the existing freshness checks, as design 5.1 says.
5. **The retry driver** (`text_retry.execute_text_retry(store, settings, *, asset_id, expected_extraction_id, idempotency_key, research_id,
   source_version_id) -> dict`, `async`; the CLI calls it through `asyncio.run`). Store calls stay on the calling (event-loop) thread; hashing,
   copying and parsing run in worker threads; **no SQLite transaction is open across any `await`**. Steps:
   1. `store.flush_text_retry_interruptions()`. `fingerprint = sha256` of canonical JSON (`sort_keys`, no spaces) of `{"asset_id",
      "source_version_id", "research_id", "mode": "retry_failed_or_partial", "expected_current_extraction_id"}` (`research_id` is `null` for the
      CLI).
   2. `store.text_retry_by_key(key)`: same fingerprint → return `text_retry_view` with `replayed: true` (no lock, no file access, no parse, also
      while the operation is still `running`); other fingerprint → `RequestConflict`. The same lookup is repeated when step 4's lock attempt
      fails: a matching operation recorded meanwhile by another request or process is replayed, a conflicting one is `RequestConflict`, and only
      when no operation has that key is the answer `FileBusy`.
   3. File precheck without hashing (the same resolution rules as decision 3, `lstat` only): missing / symlink / non-regular / invalid name →
      `FileMissing` (route: 404 "File missing"); **no operation row is written**.
   4. `with file_lock(settings.recovery_dir, asset.sha256)` (busy → `FileBusy`, route 409, no row): `reserve_text_retry(...)`; if it returns
      `replayed: true` (a concurrent request with the same key won) return its view without parsing. The lock is keyed by the **file hash**, not the
      asset: two assets of different sources that share one stored file exclude each other.
   5. Inside the lock, everything after the reservation is wrapped so the operation always ends. **The driver owns the temporary path:** it
      creates it on the event-loop thread (`mkstemp` in `recovery/tmp`, mode `0o600`, closed at once) and registers it for removal **before**
      starting the copy thread; `observe_copy` writes into that given path (decision 3 is adjusted accordingly: it never chooses the name), so a
      cancellation or a thread failure can never lose the path. `observe_copy` → `record_text_retry_input` →
      integrity `missing` → `refuse_text_retry(op, "file_missing", input_observation_id=obs)`; `mismatch` → `"file_mismatch"`; `verified` →
      parse the copy with `pdf.extract_pdf` (looked up on the module at call time, so tests can monkeypatch `deixis.documents.pdf.extract_pdf`),
      then `complete_text_retry(op, extraction, pdf.chunk_page, input_observation_id=obs)`.
   6. **Threads are drained, never abandoned.** Each thread step (copy, parse) runs through one helper that starts the thread future, awaits it
      under `asyncio.shield`, and on `CancelledError` keeps waiting (shielded, swallowing further cancellations) until the thread has returned, and
      only then re-raises the cancellation; if the drained thread itself raised, that error is logged and the **original** `CancelledError` is
      re-raised. The same helper is used for the parse in the ordinary upgrade branch of the route (decision 6), so its lock is also held until its
      parser thread has stopped. So the temporary copy is deleted and the lock released only after the thread that uses them has
      stopped, and nothing is completed after a cancellation: a cancelled request ends as `interrupted`/`cancelled`, never `promoted`.
   7. **Ending on error, before the terminal commit only.** Any exception after the reservation and **before** the operation's terminal
      transaction has committed (including `CancelledError`): `reason = "cancelled"` for a cancellation,
      `"storage_full"` when `db.describe_failure(exc)` returns code `disk_full`, `"storage_unavailable"` for any other code it returns (busy,
      read-only, damaged), else `"unexpected_error"`; `interrupt_text_retry(op, reason)`; if that call fails, record the pending interruption
      (decision 4) and log it; in every case re-raise the **original** exception. **After** the terminal commit (a completed operation) nothing
      tries to interrupt it (terminal rows are frozen): an error while building the response (for instance in `text_retry_view`) propagates as
      itself, and the committed result stays the answer to a replay of the key; a test injects a serializer failure after commit and then
      replays. **Cleanup** runs in `finally`, after the drain, as independent steps: unlinking the temporary copy and releasing the lock are each
      attempted even when the other fails; a cleanup failure is logged and never replaces the exception already propagating (or a committed
      result). A copy that could not be deleted is named `<sha256>-<random>.pdf`; after step 2's replay lookup (never before it, so a replay touches
      no file) and before the lock attempt, files in `recovery/tmp` whose hash's lock is not held (`lock_held` false) are deleted, so an orphan is
      retried and never deleted while its retry still runs; a failure of this sweep is logged and ignored. The CLI dry run never sweeps
      `recovery/tmp` and deletes only its own system-temporary files. Tests inject an unlink failure, a lock-release failure and both, and show the original outcome or exception and
      a later sweep; a pre-existing orphan and an entry the sweep cannot delete do not change a replay's answer, and a dry run leaves both.
   8. Return `text_retry_view(op)` plus `replayed: false`.
   The driver calls no OCR, Marker, arXiv source, equation service, provider, embedding or model code; it never calls `Store.reextract_asset`.
6. **API: the extraction route.** `POST /api/researches/{rid}/sources/{svid}/assets/{aid}/extractions` keeps its path and CSRF protection.
   - **No body** (and an empty body): today's behavior, except that the ordinary upgrade branch now runs inside `file_lock` (busy → 409 code
     `file_busy`) with its parse run through decision 5's draining helper and the `unchanged` answer gains one field `reason`: `already_current` when the asset's status is `succeeded`, `pending` when
     `pending`, otherwise `retry_available`. The shortcut stays before the file check (moving it is R2c's T7). The library-wide selection does not
     grow.
   - **Body** `TextRetryRequest` (Pydantic, `extra="forbid"`): `mode: Literal["retry_failed_or_partial"]`, `expected_current_extraction_id: str`
     (1-64 chars), `idempotency_key: str` matching `^[A-Za-z0-9_-]{8,128}$`. A body with another mode, a missing or malformed field → 422 (FastAPI
     validation). Then `asset_in_use` (404 for research, membership, foreign or removed asset), then the driver.
   - **Status codes before a reservation** (no operation row written): 404 file missing; 409 with `code` `request_conflict`, `file_busy`,
     `baseline_changed`, `operation_running`, `run_active`; 422 `{"code": "not_retryable", "reason": "already_current" | "pending"}`; the
     existing coded storage refusals (507 `disk_full`, 503 for a busy, read-only or damaged library, `app.py:755-764`). Each 409/422 body is
     `{"detail": <one sentence>, "code": ...}`. Map `RequestConflict`, `RecoveryConflict`, `NotRetryable`, `FileBusy`, `FileMissing` in the route
     (or as handlers registered beside the existing ones); keep the global `RunInProgress` handler unchanged and map the retry's `RunInProgress`
     to `code: "run_active"` inside the route. **The route calls the driver inside the existing `disk_full_refused()` context**
     (`app.py:569-577`), so a native `OSError` that `db.describe_failure` classifies (ENOSPC) reaches the existing coded handler as `DiskFull`
     (507) before or after a reservation; the driver itself still classifies the original exception for the interruption reason.
   - **After a reservation** the response is the research view plus `recovery` = `text_retry_view` plus `replayed`: `{operation_id, lifecycle,
     replayed, outcome, reason, decision_code, input_integrity, candidate_status, extraction_id, extraction_version, baseline_extraction_id,
     coverage}`. Status 200 when `lifecycle` is `completed` or `interrupted`, **202 when it is `running`** (an in-flight replay). A refusal after
     reservation is a 200 whose `outcome` is `refused` and whose `reason` names it; a rejected or `no_change` candidate is a 200 with that
     outcome: no field of the response says text was recovered unless `outcome` is `promoted`. An exception after reservation answers as that
     exception does today (the coded storage refusals above, else 500), with no `recovery` object, and the operation is `interrupted`; a replay of
     its key then answers 200 with `lifecycle: "interrupted"`, `outcome: null` and its reason.
   - The route wakes the worker after the driver returns or raises (decision 4's run policy). The `asset_text_retried` event has no UI label
     (R4); the research view must still answer 200 with such events present (test).
7. **Exception handlers.** Only those decision 6 needs; no existing handler's body changes.
8. **API: a read route for the retry capability** (placed directly after the extraction route): `GET
   /api/researches/{rid}/sources/{svid}/assets/{aid}/text-retry` (same `asset_in_use` checks) first calls
   `flush_text_retry_interruptions()`, then returns `{current_extraction_id, status, extractor_profile, extraction_version, diagnostic_only,
   can_retry_text, reason, latest_operation}`. `reason` is the first that applies, in this order: `no_current_extraction`, `already_current`
   (status `succeeded`), `pending`, `operation_running` (**any** `running` text retry of the asset, live or a crash leftover, because
   `reserve_text_retry` refuses both), `run_active` (a queued, running or pause-requested run in a holding research, the set `reserve_text_retry`
   refuses), `file_missing` (decision 5's precheck); `can_retry_text` is true exactly when `reason` is NULL. `latest_operation` is the newest
   `text_retry` operation of the asset as `text_retry_view`, or NULL. The flush aside, it writes nothing and hashes nothing. It is what R4 will
   call; `views.py` is not changed.
9. **CLI** (`__main__.py`): `deixis reextract --retry ASSET_ID --expected-extraction EXTRACTION_ID [--dry-run]`. `--retry` and
   `--expected-extraction` must come together (argparse error otherwise). Without `--retry` the library-wide upgrade keeps its selection, output
   and behavior, except that each asset is parsed inside `file_lock` (busy → printed outcome `file_busy`, counted, the loop continues).
   - **Retry**: schema check as the existing command, `db.connect`, `db.migrate`, `Store(conn)` with `recovery_dir` set, then
     `asyncio.run(execute_text_retry(..., research_id=None, source_version_id=<the asset's>, idempotency_key="cli-" + uuid4().hex))`. Prints
     one line from `text_retry_view`: lifecycle, outcome, reason or decision code, operation ID, new extraction version or `-`. Exit 0 when an
     operation was recorded as completed (any outcome, including `refused`), 2 for a refusal before a reservation (not found, removed, not
     retryable, baseline changed, operation running, run active, file missing, file busy) with one sentence on stderr, 1 for an interruption
     (and, when the interruption could not be written, a sentence saying the operation stays `running` until a later version reconciles it).
     A storage failure that `db.describe_failure` classifies and that happens before a reservation (opening, migrating, reserving, creating the
     lock folder) prints its one-sentence detail and exits 3, with no operation row. Any other exception is a programming error and keeps the
     existing behavior (a traceback), as the library-wide command does today.
   - **Retry dry run** (design 3.2: "opens no application and writes no migration, operation, passage or event"): take a read-only snapshot
     with the **whole** bounded procedure of `db._applied_versions_from_copy` (`db.py:74-101`: up to three attempts; copy the main file and the
     `-wal` into a temporary folder; compare the main file's size and mtime before and after, and also the `-wal`'s; retry when they differ or
     SQLite cannot read the copy), implemented in `text_retry.py` or `__main__.py` without editing `db.py`, but keeping the copy open for the
     planning reads. When no coherent snapshot is obtained: exit 2, "could not read a consistent copy of the library; try again". When the copy's
     applied migrations differ from `db.packaged_versions()`: exit 2, "this library needs a migration; start DEIXIS once or run without
     --dry-run". Otherwise read the baseline from the copy, apply `reserve_text_retry`'s eligibility checks without writing, run the decision 5
     precheck and `observe_copy` on the live papers folder into a temporary folder and the parser on that private copy (no lock: nothing is
     written to the library), evaluate `recovery.decide` against the stored baseline, print `would promote <code>` / `would reject <code>` /
     `would refuse <reason>`, delete every temporary file and exit 0. Nothing is created inside the data directory by a dry run (the temporary
     folders live in the system temporary directory). A copy failure (`OSError`) prints one sentence and exits 3; a parser exception prints
     one sentence naming the exception class and exits 1; whatever extraction the parser returns (also a `failed` one) is judged only by
     `recovery.decide`, so an identical failure prints `would reject no_change` and a password-protected candidate on an empty `no_text`
     baseline prints `would promote password_diagnosed` (diagnostic only), both exit 0. Each leaves the live library byte-identical. The dry
     run does not call `schema_problem`/`check_schema_known` for its storage decision: its own snapshot step classifies an `OSError` (also one
     wrapped as a cause) with `db.describe_failure`, so a copy failure with ENOSPC exits 3, while an incompatible schema and exhausted
     consistency retries exit 2. The non-dry retry likewise checks the schema with a retry-local wrapper that unwraps
     `SchemaCheckUnreadable.__cause__` and exits 3 for a classified storage cause, 2 for an unknown newer schema.
10. **What R2a does not do.** No migration. No change to upload, matching, Zotero, acquisition, fetch or Replace PDF paths (R2b). No startup
    reconciliation of `running` rows (R2c). No UI string, no `views.py` field, no `api.ts` type (R4); the TypeScript client types for the request
    and the `recovery` object are R4's and the decision says so. No automatic retry anywhere: nothing calls the driver except the route and the CLI.
    No `force` switch. The existing OCR endpoint and `reextract_asset` decision rules are unchanged.
11. **Existing tests.** R1's tests are expected to change only where the new keys or the run policy reach them: in
    `tests/test_reextract_r1_store.py` the result-equality comparisons at `:191`, `:372` and `:403` (both parameters), and in
    `tests/test_reextract_r1_migration.py` those at `:287` and `:341`, compare the stored operation fields with the transient `replayed` key
    removed and assert `replayed` separately (keep the rollback assertion at `:372`, the replay-after-removal coverage at `:403` and the
    immutability assertions of the migration tests); any event-payload assertion that the added `lifecycle`/`reason` keys break; and the
    combined reservation/completion run test (`test_reextract_r1_store.py:375-384`), which is split or branched so reservation still refuses
    `queued`, `running` and `pause_requested` while completion refuses `running` and `pause_requested` and **permits** `queued` (keep all three
    parameters; do not replace `queued` by another running case). Change each minimally and report it. Any other existing test that breaks: report it with the reason before editing it.

## Tests that must fail on the old code, and regression guards

Name each test's role in your report: **red on old** (the assertion fails on `2148c32` for the defect named), **guard** (passes on both) or **new
contract** (exercises a route, option or method that does not exist on `2148c32`; name its paired red-on-old or guard assertion). The
orchestrator re-runs the red-on-old ones against a clean copy of `2148c32`. Synthetic PDFs come from `tests/helpers.py::make_pdf`; seeds go
through `Store.add_asset_with_pages` with a synthetic `pdf.Extraction` and a real file at `papers_dir / storage_path`. Every API test uses
`create_app(..., start_worker=False)` with a temporary data directory and the CSRF cookie/header.

- **T1 (API, red on old), standalone.** Seed an in-use asset whose current extraction is `failed` with error `pdf.ERROR_UNREADABLE`, today's
  profile, page count 0, no passages, with a **torn** file at its hash path (the first 40% of the bytes). Repair the bytes by the path people use
  today: `POST .../uploads` of the full file (or, if that route cannot reach this source, write the bytes and say why). POST the retry body with
  the current extraction ID; record `body.get("reextraction")` in a variable for the failure message. The **first** assertion is behavioral
  and envelope-free: the asset's stored current extraction (`asset_extractions WHERE outcome = 'current'`) is no longer the seeded failed row
  and its version starts with `EXTRACTION_VERSION + "+reextract-"`; then 200, `recovery.outcome == "promoted"`, then
  `decision_code == "recovered_text"`, `input_integrity == "verified"`, new current version `EXTRACTION_VERSION+reextract-<op>`, profile
  `EXTRACTION_VERSION`, old row `superseded` and otherwise byte-identical, passages for every text page, an `extraction_input` observation whose
  observed digest equals the asset hash, one `asset_text_retried` event per holding research agreeing with the response and the row. On
  `2148c32` the same request answers `{"reextraction": {"outcome": "unchanged"}}` and the head stays the failed row (the defect), so the first
  assertion fails there with that outcome in its message.
- **No-body compatibility (separate tests).** On the same seed before the retry, the no-body POST answers `outcome: "unchanged"` and writes
  nothing (guard, passes on both); its `reason == "retry_available"` is asserted in a second test (new contract).
- **T3 (API, red on old), standalone.** Seed `partial` at today's profile from a real parse of a 3-page PDF with page 3's text removed (so page
  1's text is byte-identical to a fresh parse), cite a page-1 passage from an answer evidence link; retry; the first assertion is, as in T1,
  the stored head (a recovery occurrence, not the seeded partial row); then the response's `promoted` / `text_updated`; then old passage IDs, text, hashes, labels, offsets unchanged; the identical page-1 chunk is a new passage of the
  new occurrence; `Store.evidence_statuses` gives `text_superseded` for the cited passage; `passages_for` and `has_pdf_text` see only the new
  occurrence.
- **T6 (API, new contract; paired red on old: T1).** (a) Torn file: key 1 → 200 `refused` / `file_mismatch`, `input_integrity == "mismatch"`,
  an observation with the torn copy's digest and size, no extraction row; the file is repaired; key 2 → `promoted`. (b) The parser
  (monkeypatched `pdf.extract_pdf`) returns `Extraction("failed", error="extraction timed out")` for key 1 (an error different from the
  baseline's, so `recovery.decide` cannot answer `no_change`) → `rejected` / `candidate_failed`; key 2 with the real parser → `promoted`. In
  both: replaying key 1 and key 2 returns their original `text_retry_view` (every field equal, plus `replayed: true`), and a spy shows no extra
  parser or `observe_copy` call and no new operation, observation, extraction, passage or event row; key 2 with another
  `expected_current_extraction_id` → 409 `request_conflict`; a fresh key 3 with the old baseline → 409 `baseline_changed` (two keys, one
  baseline).
- **Request and membership refusals** (each its own test, each asserting no operation row): CSRF missing → 403; research without the source,
  removed membership, an asset of another source, a removed asset → 404; malformed body, unknown mode, short key, extra field → 422; `succeeded`
  head → 422 `not_retryable`/`already_current` and the no-body POST → `unchanged`/`already_current` (healthy duplicate); `pending` → 422
  `pending`; storage path with `..`, an absolute path, a symlink pointing outside `papers`, a directory, a missing file → 404.
- **Verified copy.** A same-size file whose bytes differ (one byte flipped) → `refused`/`file_mismatch` with the flipped copy's digest (the
  hash branch, not the size branch); a larger file → `file_mismatch` with its size, nothing copied; after every outcome `recovery/tmp` is empty.
- **Locks.** A child process (`subprocess` running a short Python snippet) holds `file_lock` for the asset's hash → retry 409 `file_busy`, no
  row; the no-body upgrade of an older-profile asset under the same held lock → 409 `file_busy`; the `lock_held` cases of decision 2.
  **Shared file:** two assets of two sources share one SHA-256 and storage file; while asset A's retry is parked in its parser, asset B's retry
  and B's ordinary upgrade answer 409 `file_busy` with no operation row, and a retry of an asset with another hash proceeds. **Same key,
  two requests:** request 1 is parked between its key lookup and its lock attempt (monkeypatched hook) while request 2 with the same key and
  body reserves and parks in its parser; request 1 then answers 202 replay (not `file_busy`); with a different body it answers 409
  `request_conflict`. **Ordinary-branch cancellation:** cancelling the no-body upgrade of an older-profile asset while its parser thread is
  blocked keeps the lock held (another `open()` cannot take it) until the thread is released.
- **API and CLI at once.** A child process runs the CLI retry (`python -m deixis reextract --retry ...`) on the same library with
  `deixis.documents.pdf.extract_pdf` replaced by a slow fake through a small wrapper script (or another way that keeps the real CLI code path;
  report the way chosen) that signals when it is parsing; meanwhile an API retry of the same asset with another key → 409 `file_busy` (or
  `operation_running`), and a run queued through the API in a holding research is not started by `next_queued_run`; after the child exits, the
  CLI's operation is `completed` and the run is picked up.
- **In-flight replay.** While the driver of key 1 is parked inside a fake parser (an `asyncio`/thread event), a second request with key 1 →
  202, `lifecycle: "running"`, `replayed: true`, no `observe_copy` or parser call (spies), no lock attempt.
- **Cancellation.** Cancel the driver while (a) the copy thread is blocked after creating content in the temporary file, (b) the copy thread
  completes successfully during the drain, (c) the copy thread raises during the drain, and (d) the parse thread is blocked: the lock is still
  held and the temporary file still exists until the thread returns; afterwards the operation is `interrupted`/`cancelled`, the exception seen
  by the caller is `CancelledError` in every case, no extraction row, no `promoted` event, `recovery/tmp` empty, the lock free.
- **Other holders.** A second `Store` connection to the same library holds a `running` reservation → 409 `operation_running`. A `queued` run in
  **another** research holding the source → 409 `run_active`. A `paused` run in a holding research does not block the retry; after the retry it
  resumes (pause/resume).
- **Pathological entries.** The entry is replaced by a FIFO between the `lstat` and the `open` (monkeypatched hook) → the request ends
  (`file_missing`), nothing blocks, no parse, the lock released and `recovery/tmp` empty; the same with a symlink swapped in → `file_missing`.
- **Input provenance on non-promoted endings.** With a verified input, the final refusals `baseline_changed`, `membership_changed` and
  `run_active` keep `input_integrity: "verified"` in the response and its replay, while `outcome` is not `promoted`. For a parser exception the
  first response is the 500 with no `recovery` object; the stored operation keeps its observation pointer and the replay and the capability
  route's `latest_operation` show `input_integrity: "verified"` with `lifecycle: "interrupted"`.
- **CLI storage failures.** A SQLite busy error at reservation (real contention or `sqlite_errorcode` set) → exit 3, one sentence, no row; an
  `OSError(ENOSPC)` creating the lock folder → exit 3, no row; a schema-copy `OSError(ENOSPC)` (dry run and non-dry) → exit 3; an
  incompatible schema → exit 2; a dry-run copy failure → exit 3 and a dry-run parser exception → exit 1, all leaving the live library
  byte-identical; dry runs of an identical failure and of a password diagnosis print `would reject no_change` and `would promote
  password_diagnosed`.
- **Final-transaction races** (the monkeypatched parser performs the race, then returns the extraction; protected state is hashed **after** the
  competing change and **before** completion, and must be unchanged by the completion): another connection promotes an ordinary occurrence →
  `refused`/`baseline_changed`; the requesting research's membership is removed while another research still holds the source →
  `refused`/`membership_changed` (a Store-level test of the same race is red on old: `complete_text_retry` promotes on `2148c32`); a run in
  another holding research is set `running` → `refused`/`run_active`; a run there that is only `queued` → the retry promotes (decision 4).
- **Run policy (Store).** With a live lock (child process) and a running operation: a run queued in a holding research is skipped by
  `next_queued_run` while an older or newer run of an unrelated research is returned; `create_run`, `resume_run`,
  `queue_failed_search_retry`, `request_term_suggestions`, `submit_approval` and `choose_code_query` still succeed (no new exception, a
  follow-on created the way `flow.py:4037` does is created); after the lock is released `next_queued_run` returns the deferred run. With the
  lock released but the operation still `running` (a crash leftover) nothing is deferred and a new retry is 409 `operation_running` (pinned limit
  until R2c). With `recovery_dir = None` a running operation defers.
- **Interruption.** The parser raises → 500, the operation `interrupted`/`unexpected_error`, one event per holding research with `lifecycle:
  "interrupted"`, `outcome: null`, no extraction row, the lock released, `recovery/tmp` empty; replay → 200 with the same view. An `OSError`
  with `ENOSPC` while copying → 507 `disk_full` and `storage_full`; an `OSError(ENOSPC)` before the reservation (creating the lock folder) →
  507 and no row; a real SQLite busy error at completion (a second connection holding `BEGIN IMMEDIATE` with a short busy timeout, or an
  injected `sqlite3.OperationalError` with `sqlite_errorcode = sqlite3.SQLITE_BUSY` set) → 503 and `storage_unavailable`; an unclassified
  `sqlite3.OperationalError` without an error code → 500 and `unexpected_error` (guard that classification is not widened). `interrupt_text_retry` fails once (monkeypatched) → the original error is answered, the operation is still `running`
  and pending; the next `execute_text_retry` (or capability read, or `next_queued_run`) flushes it to `interrupted`.
- **Responses and events agree** (parametrized over `promoted`, `diagnosis_updated` (legacy `no_text` baseline, password-protected candidate via
  the monkeypatched parser), `rejected`, `no_change`, `refused`, and `interrupted` compared through the replay): the `recovery` object, the
  operation row and every event payload name the same lifecycle, outcome, reason, decision code and extraction version.
- **No call outside the parser (T10's first boundary).** Monkeypatch `ocr.read_page`, the math reader, `EquationService.read_asset`, every model
  adapter in `create_app(adapters=...)` and the HTTP client transport to raise; a retry promotes. **Then T10's second boundary, separately:**
  after the promotion of a `partial` head, `EquationService.next_asset` (with a fake installed reader, as the existing equation tests build it)
  selects that asset; that read is existing D52 behavior (guard), not recovery work.
- **Capability route.** For failed, partial, no_text, succeeded, pending, a live running retry, a crash-leftover running retry, a queued run, a
  missing file, and two blockers at once: `can_retry_text` and `reason` in decision 8's order; `latest_operation` after a promotion and after a
  refusal equals the POST's `recovery` without `replayed`; the route writes nothing (row counts) and needs no CSRF token.
- **Research view.** With `asset_text_retried` events of every outcome present, `GET /api/researches/{rid}` answers 200.
- **CLI.** `main(["reextract", "--retry", aid, "--expected-extraction", eid])` with `DEIXIS_DATA_DIR` set to a temporary library: promoted, the
  printed line, exit 0; a not-retryable asset → exit 2, no row; the dry run on an eligible asset prints `would promote recovered_text`, leaves
  `library.sqlite`, `-wal` and `-shm` byte-identical (hashes, and their presence or absence) and adds no row, and creates nothing in the data
  directory; a library whose latest committed rows exist only in the `-wal` (written by a connection with automatic checkpoints off) is planned
  from those rows; a copy step that sees the main file change on every attempt (monkeypatched) exits 2 with the consistency sentence; the dry
  run on a library whose applied migrations stop at 0065 (only migrations up to 0065, as `tests/test_reextract_r1_migration.py` builds one)
  exits 2 and leaves it byte-identical, still at 0065; `--retry` without `--expected-extraction` is an argparse error; `reextract` without
  `--retry` still skips a same-profile failed asset (guard: the selection did not grow) and reports `file_busy` for an asset whose lock a child
  process holds.

## Checks to run

Focused tests while building, then the whole suite inside your sandbox:
`PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest -q -p no:cacheprovider`. Tests that need sockets or process
listings fail in your sandbox; list them by name; the orchestrator reruns the full suite outside the sandbox. If a child-process lock test cannot
run in your sandbox, say so and keep it. Then `git diff --check`. No web change: no build, lint or Playwright run.

## Report and records

Write `/tmp/reextract-r2a-impl-report.md`: files changed, each decision's implementation with file:line, the run-activation grep result of
decision 4, every test with its role (red on old / guard / new contract with its paired assertion) and what it shows, existing tests changed and
why, full-suite counts with the failure list, what you could not do. Draft the decision entry at the top of `docs/decisions.md`, above D190:
`## D191 — P9 re-extraction R2a: a person can retry a failed or partial extraction once per request, through the extraction endpoint or the CLI,
on a hash-checked private copy under a per-file lock; runs wait for a live retry` with Status (accepted, implemented; writer gpt-6.1-sol high;
leave the reviewer line for the orchestrator), Date 2026-10-03, Context, Decision (request body and status codes, replay rules, the lock and its
liveness probe, the verified copy and the observation, the run policy (runs wait; completion refuses started runs) and its crash limit,
`membership_changed`, `refuse_text_retry`, `interrupt_text_retry` and pending interruptions, the drained threads, the capability route, the CLI and its dry run), Carried work (R2b: `restore_file(op)`, receipts, retained bytes, the
lock in every writer, initial attachments recording verified input observations; R2c: reconciling `running` rows, the missing-file check before
the healthy `unchanged`, crash boundaries; R3; R4: UI, the `asset_text_retried` label, TypeScript types for the request and `recovery`; D52
background reads can still move a head during a retry and the retry then refuses `baseline_changed`), Limits (synthetic PDFs only, no real
library recovered, page coverage is not word preservation, a crashed reservation blocks retries of that asset until R2c, the lock is advisory and
does not stop a process outside DEIXIS from changing the file, Windows locking untested). Do not edit `STATUS.md` (the orchestrator does).

## Do not

Retry automatically anywhere; add a migration; parse the live file instead of the verified copy; open a SQLite transaction across an `await`, a
hash or a parse; write an operation row for a request refused before reservation; report text recovery for any outcome but `promoted`; store
`verified` for bytes nobody hashed; change `views.py`, `flow.py`, `equations.py`, any `documents/*` or `storage/*` file, an upload path or the
OCR endpoint; add a `force` switch; let a failure while ending an operation hide the original error.
