<!-- PLAN-REVIEW-ROUNDS: r1 (gpt-6.1-sol medium): düzeltmeyle hazır, 4 high + 6 medium + 1 low, all folded in (initial-attachment input observations moved to R3, jointly decided); r2: düzeltmeyle hazır, 1 high + 2 medium + 2 low, all folded in; r3: düzeltmeyle hazır, 1 high, folded in; r4 (last round allowed): düzeltmeyle hazır, 0 high + 0 medium + 1 low, folded in by the orchestrator without a fifth round -->


# Task: P9 re-extraction batch R2b, file repair receipts and retained damaged bytes through one `restore_file(op)`

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-reextract-r2b`, detached at `19d0a48` (origin/main with R1 = D190, R2a = D191 and
P7 G1 B2 = D178). Design: `docs/product/p9-reextract-design.md`, accepted as D176. Read all of it; sections 3.1, 5.1 (last two paragraphs:
the active-run rule), 5.2, 9 (row R2b), 9.1 (T2) and 12 (Q1, Q6) bind this batch. Also read `AGENTS.md`, `CLAUDE.md`, D190, D191 and D176 in
`docs/decisions.md`, `docs/product/p9-reextract-r2a-prompt.md` (the previous batch prompt, style model), `backend/deixis/workflow/text_retry.py`
and R2a's tests `tests/test_reextract_r2a_*.py` with `tests/reextract_r2a_helpers.py`. Venv: `.venv` is a symlink to the main checkout's arm64
venv. Run tests with `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest ...`.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted. No real-model
call, no provider call, no network. Do not touch `../DEIXIS*` worktrees, `TODO.md`, `.vscode/`, `scripts/local_index.py`, the live service on
port 8765 or the live data directory. **Do not edit** (other sessions own them or the batch does not need them): `backend/deixis/models/*`,
`backend/deixis/providers/*`, `backend/deixis/workflow/views.py`, `backend/deixis/workflow/review/*`, `backend/deixis/workflow/report/*`,
`backend/deixis/workflow/equations.py`, `backend/deixis/storage/*` except a new migration file if decision 12 truly needs one (`db.py` and
`backup.py` may be imported, not edited), `backend/deixis/documents/*` except `pdf_files.py` and `acquisition.py`, `backend/deixis/__main__.py`,
`scripts/*`, `tests/process/*`, anything under `apps/web`, `contracts/`, `methods/`, `.impeccable.md`. In `backend/deixis/api/app.py` change
only `store_upload`, the routes and handlers decision 8 names and the R2a capability route (decision 9); in `backend/deixis/workflow/flow.py` change only `_fetch_pdf` and
`_find_other_copy`; other batches edit nearby code at the same time. Existing test files stay unchanged unless decision 13 names them. If R2b
truly needs a forbidden file, stop and report it. Do not invent; report what you could not find, run or measure.

## Why

D165 made uploads replace a torn file under its hash name, but nothing records that the bytes were repaired, the damaged bytes are thrown
away, and nine other places write the same hash path the same way. D176 (design 3.1, 5.2) requires **one** replacement path for a non-whole
stored file, `restore_file(op)`: it takes the per-file lock, refuses while a run that could read the file is active, keeps the damaged bytes
it can still see, writes a repair receipt, and never changes the stored text (Q1: a repaired file is offered one explicit text retry, which
R2a built). R2a (D191) left this to R2b: "R2b owns `restore_file(op)`, repair receipts, retained damaged bytes, the lock in every writer and
verified input observations for initial attachments." After R2b a person who re-uploads a torn file gets a receipt, the damaged bytes stay
on disk, the failed text head stays as it was, and the R2a retry recovers it. Still not done: reconciling an operation a crash left
`running` (R2c), backup and authorized purge of retained bytes and receipts, cited-occurrence views (R3), any UI (R4).

## What is and is not in code (checked on 19d0a48)

- **The two file writers.** `pdf_files.store_pdf_file(papers_dir, sha256, data)` (`documents/pdf_files.py:29-42`) returns at once when
  `file_is_whole` (`:24-26`: regular file, size and SHA-256 equal); otherwise it writes a `mkstemp(..., suffix=".part")` file and
  `os.replace`s it over `<sha>.pdf`, with no fsync, no lock, no receipt and no copy of what it replaced. `file_is_whole` uses
  `Path.is_file()` and `path.open`, so a symlink resolving to a regular file passes it. `store_upload(file, papers_dir)`
  (`api/app.py:596-626`) streams the upload into `mkstemp(..., suffix=".partial")` while hashing (50 MB cap, `%PDF-` check, ENOSPC as
  `DiskFull`), then reuses a whole file or `os.replace`s the partial over `<sha>.pdf` (`:617-620`), same gaps.
- **Callers of `store_upload`**: generic upload `upload` (`app.py:1593`, write at `:1599`; it reuses an existing active `user_upload` source
  with that hash and only restores its membership, `:1601-1609`); `upload_to_source` (`:1619`, write `:1628`; a hash the source already owns
  skips extraction, `:1629-1632`); legacy matching `match_uploads` (`:1650`, write `:1665`) and sw matching `match_waiting` (`:1671`, write
  `:1677`), which only parse with `MATCH_TEXT_CHARS` and propose a match: the person's confirmation sends the file again through
  `upload_to_source` or `attach_waiting_pdf` (`apps/web/src/api.ts:990`, `:1017`), so matching never needs the stored file; waiting
  attachment `attach_waiting_pdf` (`:1704`, write `:1717`); Replace PDF `replace_asset` route (`:2052`, write `:2059`), which **writes first
  and then** raises `SameFile` for the asset's own hash (`:2060-2061`, handler 422 at `:830-832`).
- **Callers of `store_pdf_file`**: Zotero import (`app.py:1802`, write `:1835`) and Zotero PDFs (`:1844`, write `:1871`), each inside
  `disk_full_refused()`; acquisition `_attach_pdf` (`documents/acquisition.py:466-473`, write `:470`), reached from `acquire_for_source`
  (`:330`; route `discover_source_pdf` `app.py:1754` and `Flow._find_other_copy` `flow.py:2738`), `_attach_other_version` (`:426`),
  `_attach_rendition` (`:273`) and `attach_confirmed_candidate` (`:476`; route `attach_pdf_candidate` `app.py:1774`); run-time fetch
  `Flow._fetch_pdf` (`flow.py:2707-2732`, write `:2721`) inside a `running` run. Zotero and acquisition skip a source that already has an
  asset, so a torn file reaches them only as a **shared** hash path owned by another source's asset.
- **No other active-library writer of a hash path**: `os.replace` in `backend/deixis` outside these two writers is in `credentials.py`,
  `storage/backup.py`, `documents/local_embedding.py`, `documents/arxiv_source.py` and `workflow/local_embedding_service.py`. Only
  `backup.py:142` places `papers/<sha>.pdf`, and only while restoring a backup into a folder with no existing library (`backup.py:148`); it is
  out of R2b's scope and stays as it is. Readers of the stored file take no lock: the OCR run (`flow.py:2509`) and the equation reader
  (`equations.py:262`, `:304`, `:387`); the CLI upgrade and the text retry already take R2a's lock (`__main__.py:164`, `text_retry.py:232`).
  Atomic replacement keeps an already opened inode, but an unlocked reader can still read torn old bytes, or different versions across
  separate opens.
- **Locks and liveness (R2a)**: `text_retry.file_lock(recovery_dir, sha256)` (`text_retry.py:62-95`, exclusive, non-blocking, `FileBusy`
  with global 409 `file_busy` handler at `app.py:814-816`), `lock_held` (`:98-118`), `precheck` (`:121-135`), `drained_thread` (`:172-189`).
  `Store.recovery_dir` is set in the lifespan (`app.py:657`); a bare `Store` has `None`. `Settings.recovery_dir` is `data_dir / "recovery"`
  and `Settings.papers_dir` is `data_dir / "papers"` (`config.py:60-70`).
- **Run policy (R2a)**: `_asset_run_active(svid)` (`store.py:1700`, queued/running/pause_requested in any research with a membership row
  for the source), `_asset_run_started(svid)` (`:1706`), `next_queued_run` (`:804-833`) skips researches holding a source with a **live**
  text retry (operation `running` and its hash lock held, or `recovery_dir is None`) and does not look at `file_restore` operations.
  `replace_asset` (`store.py:1933`) refuses active runs in every research holding the source (`RunInProgress`, 409 at `app.py:793`).
- **Schema (R1, migration 0066)**: `asset_recovery_operations.kind` already allows `file_restore` (asset_id nullable; the CHECK also
  permits `mode = 'retry_failed_or_partial'` there, so `mode` NULL for restores is this batch's writer invariant, not a schema rule;
  `idempotency_key` NOT NULL UNIQUE, `request_fingerprint` NOT NULL); outcomes `file_reused`, `file_restored`, `file_refused` exist;
  `before_observation_id` / `after_observation_id` may each be set once, while `running`, to an observation of this operation of kind
  `before_restore` / `after_restore` (frozen trigger); `asset_file_observations` allows `retained_filename` only on `before_restore` with an
  observed digest; observations are immutable; `integrity` must agree with the digests (`verified` equal, `mismatch` different, `missing`
  NULL). Nothing writes a `file_restore` row, `before_restore`, `after_restore` or `retained_filename` today. `events.type` is free text.
- **Store writers**: `add_asset_with_pages(..., *, input_observation_id=None)` (`store.py:1567-1588`) already passes an observation ID to
  `_write_extraction`; `replace_asset` (`:1933`) has no such parameter; `add_file_observation` (`:1712`) inserts in its own (nesting)
  transaction. `_purge_asset_extractions` (`:1535-1562`) deletes operations by `asset_id`, the observations those operations hold and the
  input observations linked from the purged extractions (also ones with no operation), unless something else still holds them.
- **Tests today**: `tests/test_p9_h7_torn_upload.py:10` plants a torn file before any asset row exists and checks the upload repairs it;
  `tests/test_pdf_files.py` unit-tests `store_pdf_file`; `tests/test_p9_h7_zotero_disk.py:21-56` monkeypatches `pdf_files.store_pdf_file` and
  `:58-75` counts two `store_pdf_file` calls in `app.py` inside `disk_full_refused`. No test seeds a failed asset over a torn shared file and
  then repairs it through any writer.
- **Baseline**: the orchestrator's full run on this commit outside the sandbox: 10,422 passed, 0 failed, 2 skipped, 62 warnings in
  388.40 s (`/tmp/reextract-r2b-baseline.log`).

## Decisions taken where the design is open (use these; never ask)

1. **Names.** New module `backend/deixis/workflow/file_restore.py` holds `Staged`, `Placement`, `FileRestoreRefused`, `restore_file` and an
   async `store_pdf_file`. `documents/pdf_files.py` keeps `file_is_whole`, rewritten to be no-follow (decision 2a), and gains
   `stage_bytes(path, data) -> (sha256, size)` (sync, run through `text_retry.drained_thread`: write into the given path, flush, `fsync`,
   SHA-256 of the bytes written). **The caller allocates the path on the event-loop thread** (`mkstemp(dir=papers_dir, suffix=".part")`,
   closed at once) and owns it before the thread starts, R2a's pattern for its private copy, because `drained_thread` drops a thread's result
   after a cancellation and a path created inside the thread would be lost; **`pdf_files.store_pdf_file` is removed**, so no caller can place a hash path outside
   `restore_file`. `store_upload` becomes staging only: same streaming, cap, header check and `DiskFull` mapping, plus `fsync`, returning a
   `Staged` whose file is still the `.partial`; it never touches `<sha>.pdf`. New tests in `tests/test_reextract_r2b_*.py` (more files if
   needed) with a shared helper module if useful.
2. **Placement outcomes.** `async restore_file(store, papers_dir, recovery_dir, staged, *, caller, research_id) -> Placement` is the only code
   in the active library that may `os.replace` onto `papers/<sha>.pdf` (backup restoration into an empty folder, `backup.py:142`, is the one
   named exception and is unchanged). `caller` is one of the closed tuple `FILE_WRITERS = ("upload", "source_upload", "waiting_upload",
   "zotero_import", "zotero_pdfs", "acquisition", "run_fetch", "replace_pdf")` (else `ValueError`, after which the staged file is still
   removed). The **affected assets** of a hash are **all** `source_assets` rows with that `sha256`, removed or replaced included (a removed
   asset's file is still backed up and its passages are still cited; design 3.1 and 5.1 say "every asset sharing the physical file"). A hash
   is **owned** when it has at least one affected asset. In this order:
   a. **No-follow inspection.** Every inspection of a stored path (the whole check, the under-lock re-check, the retention copy, the reuse
      of an existing retained file, the after-restore observation) opens it with `O_RDONLY | O_NOFOLLOW | O_NONBLOCK` (where defined),
      checks `fstat` for a regular file and hashes **through that descriptor**; `ENOENT` means absent, `ELOOP` or a non-regular `fstat` means
      `file_not_regular`. Nothing follows a symlink, and a swap after an `lstat` cannot redirect a read.
   b. Fast path without the lock: the target is whole (regular, size and digest equal) → outcome **`reused`**, the staged file is unlinked,
      no row. A whole file stays whole: every application writer places only bytes whose digest is the name.
   c. Otherwise take `text_retry.file_lock(recovery_dir, sha256)` (busy → `FileBusy`, staged unlinked, no row) and hold it until the
      operation ends. Re-inspect: whole now → `reused`; not regular → `FileRestoreRefused("file_not_regular")` (no row, nothing written);
      absent and not owned → `os.replace(staged, target)`, `fsync` of the directory, outcome **`new`**, no row (design 3.1: initial storage at
      an unowned absent path is attachment).
   d. Every other case (a present non-whole regular file, owned or not; an absent file that is owned) is a **restore with a receipt**
      (decisions 3-5), outcome **`restored`**.
   `Placement` carries `path`, `sha256`, `size`, `outcome`, `operation_id` (restores only). No outcome parses anything; `restore_file` never
   calls the parser, OCR, equation, acquisition, provider or model code.
3. **Active-run rule and reservation** (design 5.1 last paragraph, 3.1). `Store.reserve_file_restore(sha256, byte_size, *, caller,
   research_id) -> dict` runs in one `transaction()`: if `_asset_run_active` is true for the source of any affected asset, raise
   `FileRestoreRefused("run_active")` and write nothing. There is **no bypass**: a run-time fetch whose own run (or any run) holds an
   affected source is refused like any other caller. Otherwise insert the operation: `kind = 'file_restore'`, `asset_id` NULL (one physical
   file can belong to several assets; the receipt is keyed by `expected_sha256`), `research_id` = the caller's research or NULL, expected
   hash/size, `mode` NULL, `idempotency_key = "restore-" + uuid4().hex`, `request_fingerprint` = SHA-256 of canonical JSON `{"kind":
   "file_restore", "sha256", "caller", "research_id"}`, `lifecycle = 'running'`. Restores are not replayable requests; each write is its own
   operation. **While a restore is live** (running and its hash lock held, or `recovery_dir is None`), `next_queued_run` also skips
   researches holding the source of any affected asset (extend R2a's query; same OSError-conservative probe and logging).
4. **Retention before replacement** (design 5.2). Under the lock, after the reservation:
   - **Absent** target: record a `before_restore` observation with `integrity = 'missing'`, nothing retained.
   - **Present** regular file: copy it through the no-follow descriptor in a thread (`drained_thread`) into a `mkstemp(dir=papers_dir,
     suffix=".part")` file while hashing, then `fsync` it. If digest and size equal the expected ones (only an outside process can cause
     this), record the observation as `verified`, complete the operation as **`file_reused`**, remove both temporary files and return
     `reused`. Otherwise the final name is `papers/retained-<observed_sha256>.bin` (flat, inside papers; `.bin` because a damaged file may not
     be a PDF; the prefix keeps it apart from every `<sha>.pdf`). If that name already holds a regular file (no-follow) whose digest and size
     are the observed ones, keep it, remove the copy, and `fsync` the existing file and the directory; if it holds anything else, complete
     the operation as `file_refused` with reason `retention_conflict` (before observation recorded with `retained_filename` NULL; target and
     the existing name untouched; staged file and copy removed). Otherwise `os.replace` the copy to that name and `fsync` the directory.
     Then record the `before_restore` observation (`integrity = 'mismatch'`, observed digest/size, `retained_filename`) **and** set
     `before_observation_id` in one transaction (`Store.record_file_restore_observation(operation_id, kind, **fields) -> str`, the pattern of
     `record_text_retry_input`). Only after that commit may the target be replaced.
   - Any exception here (including `OSError(ENOSPC)` while copying, an `fsync` failure of the copy, the retained file or the directory,
     `SQLITE_FULL` while recording) ends the operation as decision 6's interruption; the target is never replaced after a retention failure.
5. **Replacement and receipt.** The started-run check and the replacement are serialized with run starts: in one short `transaction()`
   (`BEGIN IMMEDIATE`, no `await`, no hashing inside), recompute the affected assets and their holding researches, check
   `_asset_run_started` for each affected source, and if none, perform the synchronous `os.replace(staged.path, target)` and then commit
   (the worker's `update_run(..., status="running")` takes the same write lock, so no run can start between the check and the rename). If a
   run has started, complete as `file_refused`, reason `run_active` (target untouched, retained bytes and the before observation kept). A
   failure of the commit after the rename leaves the operation `running` and is handled as decision 6's interruption (the file is already
   replaced; R2c reconciles from the observations). `db.transaction` runs `COMMIT` outside its rollback handler (`db.py:148-158`), so a
   failed commit can leave the connection inside an open transaction, and the next `db.transaction` would silently join it. **Every R2b
   transaction boundary** uses one local wrapper (in `file_restore.py` or `store.py`, `db.py` unchanged) that, on any exception including a
   failed `COMMIT`, rolls back a still-active transaction (`conn.in_transaction`) and re-raises the original exception: the reservation, the
   before and after observations with their pointer updates, the replacement transaction, completion, interruption and the pending flush of
   restore interruptions. The interruption path checks `conn.in_transaction` is false before it writes. R2a's text retry code is unchanged. After the transaction: `fsync` the directory, hash the target (no-follow, in a thread)
   and record the `after_restore` observation with `after_observation_id` in one transaction, then complete: `lifecycle = 'completed'`,
   `outcome = 'file_restored'`, `reason` NULL, `finished_at`. If the after observation is not `verified` (only an outside process can cause
   this), record it as observed and interrupt the operation with `unexpected_error`. The stored text is untouched in every case: no
   extraction, passage, asset mirror field or selection changes.
6. **Endings, events and views** (`workflow/store.py`).
   - `complete_file_restore(operation_id, outcome, reason=None)` for `file_restored`, `file_reused`, `file_refused` (`reason` in the closed
     tuple `FILE_RESTORE_REFUSALS = ("run_active", "retention_conflict", "file_not_regular")`, required for `file_refused`, NULL otherwise);
     `interrupt_file_restore(operation_id, reason)` with R2a's `TEXT_RETRY_INTERRUPTIONS` reasons; both act only on a `running`
     `file_restore` row (a completed or interrupted row is returned unchanged **and emits no second event**; another kind raises
     `RecoveryConflict("operation_not_running")`).
   - Errors after the reservation and before the terminal commit follow R2a's driver rule (D191): `cancelled` for `CancelledError`,
     `storage_full` / `storage_unavailable` from `db.describe_failure`, else `unexpected_error`; if the interruption itself fails, the ID and
     reason go to `Store.pending_file_restore_interruptions` and `flush_text_retry_interruptions()` also flushes that dict (same three
     callers as in R2a). The **original** exception always propagates.
   - **Temporary-file ownership.** From creation to its end, each temporary file has exactly one owner: the code that allocated its path on
     the event-loop thread (decision 1) until it holds a `Staged` (it removes the file on any exception, including a cancellation, after the
     thread has finished), then the route or
     writer until it hands the `Staged` to `restore_file`, then `restore_file`, which removes the staged file and its retention copy on every
     path it does not rename them. Every exit before the hand-over (`check_attach` refusing, `ValueError`, cancellation, a parser error in
     matching) removes the staged file. Threads that use a file are drained (`drained_thread`) before the file is removed. Each cleanup step
     (unlinks, lock release) is independent and logged and never replaces the propagating error or a committed result.
   - Each terminal writer emits **`asset_file_restore_finished`** (a neutral name: refusals and interruptions end here too), in the same
     transaction, to every research that has a membership row for the source of an affected asset plus the operation's `research_id` when
     that research exists, each research once. Payload: `{operation_id, sha256, lifecycle, outcome, reason, before_integrity,
     after_integrity, retained, affected_asset_ids}` (sorted IDs; `retained` boolean). No UI label (R4); the research view must still answer
     200 with these events present.
   - `file_restore_view(operation_id) -> dict`, the only public shape, built from stored rows: `{operation_id, lifecycle, outcome, reason,
     sha256, before_integrity, after_integrity, retained, created_at, finished_at}`. Never the retained filename, key, fingerprint or paths.
     `latest_file_restore(sha256)` returns the newest view for a hash or `None`.
   - `FileRestoreRefused(code, operation_id=None)` with a one-sentence detail per code; one global handler: 409 `{"detail", "code"}`.
7. **Extraction input of an initial attachment: moved to R3** (owner-level choice, decided with gpt-6.1-sol medium in plan review round 1).
   D191 carried "verified input observations for initial attachments" to R2b. An observation taken when the file is placed would label as
   `verified` input bytes the parser did not read through a verified private copy, which is the claim the observation exists to make. R2b
   therefore records **no** `extraction_input` observation for new attachments or ordinary upgrades; their `input_observation_id` stays NULL
   (unknown), exactly as today. R3 owns verified input for initial attachments and ordinary upgrades (a private copy, R2a's pattern).
   `add_asset_with_pages` and `replace_asset` are not changed for this.
8. **Callers** (each routes through decision 2; none keeps its own `os.replace`):
   - `upload`, `upload_to_source`: `staged = await store_upload(...)` inside `disk_full_refused()`, then `placement = await
     restore_file(...)` inside the same context (ENOSPC is 507) with `caller` `upload` / `source_upload`; the rest of each route keeps its
     logic; the response gains `file_restore` (`file_restore_view` when the placement was a restore, else `null`). A same-hash upload over a
     torn file therefore restores the bytes and keeps the failed head; the person then retries through R2a.
   - `match_uploads`, `match_waiting`: stage, parse the staged `.partial` with `MATCH_TEXT_CHARS` through `drained_thread`, remove it
     (decision 6's ownership rule); **they no longer place any file** (the confirmation uploads it again). Responses unchanged. D192 records
     this behavior change.
   - `attach_waiting_pdf`: stage, first `check_attach` (a refusal removes the staged file), then `restore_file` (`waiting_upload`), parse,
     the existing transaction; response gains `file_restore`.
   - Zotero import and Zotero PDFs: `placement = await file_restore.store_pdf_file(store, settings.papers_dir, settings.recovery_dir, data,
     caller=..., research_id=...)` inside `disk_full_refused()` (the AST guard keeps counting two `store_pdf_file` calls there);
     `FileBusy` / `FileRestoreRefused` add a note `"PDF not added: <sentence>"` for that item and continue, like `ZoteroError`.
   - Acquisition: `_attach_pdf`, `_attach_rendition`, `_attach_other_version`, `acquire_for_source` and `attach_confirmed_candidate` gain
     keyword `research_id` where missing and `recovery_dir: Path | None = None`. Lock directory resolution, one helper used everywhere: an
     explicit `recovery_dir` wins; if `store.recovery_dir` is also set and differs, raise `ValueError` (two lock namespaces would not exclude
     each other); else `store.recovery_dir`; only when neither is set, `papers_dir.parent / "recovery"`. Production routes and the flow pass
     `settings.recovery_dir` explicitly. `_attach_pdf` uses `file_restore.store_pdf_file(..., caller="acquisition")`. `FileBusy` /
     `FileRestoreRefused` propagate: the two routes answer 409 through the handlers; `Flow._find_other_copy` catches them and finishes its
     step `failed` with `error_code` `fetch_file_repair_refused` (refusal code in `error`) or `fetch_file_busy`, returning the shape
     `acquire_for_source` returns when no asset was attached.
   - `Flow._fetch_pdf`: after a successful fetch, `file_restore.store_pdf_file(..., caller="run_fetch", research_id=run["research_id"])` with
     `self.deps.settings` dirs. `FileRestoreRefused` → `finish_step(..., "failed", error_code="fetch_file_repair_refused", error={"code":
     <refusal code>, "url": ...})`; `FileBusy` → `error_code="fetch_file_busy"`; in both nothing is parsed or attached and the method
     returns so the run continues without that PDF (design 3.1). Neither code is a link refusal: `pdf_link_refusal` (`store.py:2151`) keeps
     its list, so a later run requests the link again; a test pins this.
   - Replace PDF: stage; when `staged.sha256 == asset["sha256"]`, call `restore_file(..., caller="replace_pdf")`: `reused` → the existing
     `SameFile` (422); `restored` → 200 with the research view and `file_restore`, **no** `replace_asset`, no parse, no `asset_replaced`
     event; refusals → 409. A different hash: `restore_file` for the new hash (usually `new`), parse, `replace_asset` (its own active-run
     refusal unchanged).
9. **Retry capability read.** The R2a GET `.../assets/{aid}/text-retry` gains one field `latest_file_restore` =
   `latest_file_restore(asset["sha256"])`; nothing else in it changes (it still writes nothing but the pending-interruption flush).
10. **Purge and backup in R2b.** No change. A `file_restore` row has no `asset_id`, so `_purge_asset_extractions` leaves it and its
    observations; `unlink_orphans` only removes asset storage paths, so retained files stay. Backup does not copy retained files yet (R3
    owns `_referenced_files`); a test pins that a backup taken after a restore still succeeds and that the retained file and receipt survive a
    purge of the research that triggered it. The decision's Limits state both.
11. **Shared helpers.** Reuse `text_retry.file_lock`, `lock_held`, `drained_thread` and `db.describe_failure`; do not change the text retry
    driver's behavior. A directory `fsync` helper may skip only where opening a directory is unsupported (Windows), never on an `OSError`
    from `fsync` itself.
12. **Migration.** None is expected (0066 already has every column, kind, outcome and trigger used above; the plan reviewer checked NULL-asset
    receipts, both observation pointers and terminal freezing in memory). If one is truly needed, stop and report why before writing it.
13. **Existing tests.** Expected changes, each minimal and reported: `tests/test_pdf_files.py` (the removed `store_pdf_file`: move its
    whole/torn/same-size/exception cases to `stage_bytes` + `restore_file` without losing a case); `tests/test_p9_h7_zotero_disk.py`
    (monkeypatch target becomes the staging step; the AST count keeps two calls named `store_pdf_file` inside `disk_full_refused`);
    `tests/test_p9_restore_matrix.py:685-686` only if its rich library now writes restore rows (it should not: it seeds no damaged file).
    Any other existing test that breaks: report it with the reason before editing it; do not weaken an assertion to pass.

## Tests that must fail on the old code, and regression guards

Name each test's role: **red on old** (the assertion fails on `19d0a48` for the defect named), **guard** (passes on both) or **new contract**
(exercises something that does not exist on `19d0a48`; name its paired red-on-old or guard assertion). The orchestrator re-runs the red-on-old
ones against a clean copy of `19d0a48`. Synthetic PDFs from `tests/helpers.py::make_pdf`; seeds through `Store.add_asset_with_pages` with a real
file at `papers_dir / storage_path`; API tests use `create_app(..., start_worker=False)` with a temporary data directory and the CSRF cookie and
header. **The common seed** ("torn shared file"): asset A of source S1, held by research R1, current extraction `failed` at today's profile with
zero pages, its hash path holding the first 40% of the PDF's bytes (digest `d_torn`). Each red-on-old test's **first** assertion is
behavioral, envelope-free and old-compatible (it uses only files and rows that exist on `19d0a48`), so the old code fails it with the old
behavior in the message. The usual first assertion is **retention**: some regular file under the data directory has digest `d_torn` (old code
destroys those bytes); for refusals it is **no mutation**: A's file is still byte-identical to the torn bytes.

- **T2a (red on old): generic upload keeps the damaged bytes and writes a receipt.** Upload the full PDF through `POST .../uploads` into R1
  (A's source is a `user_upload`, so the route reuses S1). First assertion: retention. Then: `papers/retained-<d_torn>.bin` holds them;
  exactly one `file_restore` operation, `completed` / `file_restored`, `before_restore` `mismatch` with that digest and filename,
  `after_restore` `verified`; one `asset_file_restore_finished` event in R1 agreeing with `file_restore_view` and the response's
  `file_restore`; `<sha>.pdf` whole; A's current extraction is the same failed row (no new extraction or passage); GET text-retry shows
  `can_retry_text` true and `latest_file_restore` equal to the view; a retry POST (R2a body) then promotes `recovered_text`.
- **T2b (red on old): source upload,** the same through `POST .../sources/{S1}/uploads` (the route skips extraction for an owned hash).
- **T2c (red on old): Replace PDF same hash over a torn file** → first assertion: status 200 (old: 422 `SameFile` after silently repairing);
  then retention, receipt, no `asset_replaced` event, A not replaced, head unchanged. **Guard:** the same over a whole file → 422 `SameFile`,
  no operation row, file mtime unchanged.
- **T2d (red on old): run-time fetch refuses a torn file its own run holds.** S2 is a provider source in R1 whose `oa_pdf_url` the fake
  fetcher answers with the full bytes of A's hash; A (S1) is also held by R1; an answer (or PDF collection) run of R1 fetches. First
  assertion: no mutation (old: replaced). Then the `fetch_pdf` step is `failed` with `fetch_file_repair_refused` and `error.code ==
  "run_active"`, no asset for S2, no parse call (spy), no operation row, the run continues to its end; `pdf_link_refusal` for S2 is `None`.
  **Red on old too:** the same with A held only by an idle research R3 → first assertion retention; then the fetch restores with a receipt
  and attaches S2.
- **T2e (red on old): a queued run in another holding research blocks every writer.** R2 also holds S1 and has a `queued` run; generic
  upload in R1 → first assertion no mutation (old: 201 and replaced); then 409 `run_active`, no operation row, no retained file. Parametrize
  over `running` and `pause_requested`; a `paused` run → allowed. **Removed sharer (red on old):** the only asset sharing the hash is a
  removed (replaced) asset of S3, held by R4 with a queued run → upload of the same bytes to a new source in R1 is refused, no mutation.
- **T2f (red on old): matching does not write.** `POST .../uploads/match` (legacy research) and the sw match with the full bytes → first
  assertion no mutation (old: replaced); no `<sha>.pdf` written for a new hash either; no `.partial` left; responses unchanged in shape.
- **T2g (red on old, one parametrized case per writer)**: waiting attachment, Zotero import, Zotero PDFs, acquisition through
  `pdf-discovery` (a verified-version candidate), its Europe PMC rendition branch (`_attach_rendition`), both `_attach_other_version`
  branches (fetched PDF and Europe PMC rendition), confirmed-candidate attachment and `Flow._find_other_copy`, each attaching the full bytes
  of A's hash (or, for a rendition, a fake renderer returning them) to another source. In these success cases A is held **only by an idle
  research R3** (no run); the writer's own research does not hold S1. The two `_attach_other_version` branches are reached by a direct call
  or through `acquire_for_source(..., other_versions=True)` (the `pdf-discovery` route does not enable them). First assertion: retention.
  Then one receipt, A's head unchanged. Refusal cases, each: first assertion no mutation. With R2 holding S1 with a queued run: Zotero notes
  `"PDF not added: ..."` and continues, the acquisition routes answer 409 `run_active`. `_find_other_copy` inside a running run of a
  research that holds S1 finishes `failed` / `fetch_file_repair_refused` (own-run refusal).
- **Lock (red on old; `file_lock` exists on `19d0a48`).** A child process holds `file_lock` for the hash → first assertion no mutation;
  generic upload 409 `file_busy` (no row), run-time fetch `fetch_file_busy`, Zotero note. **Scheduler (red on old):** a seeded running
  `file_restore` row (0066 schema) whose hash lock a child process holds → `next_queued_run` skips a queued run of a research holding an
  affected source and returns an unrelated one; after release the run is returned. **New contract:** a text retry parked in its parser
  blocks a restore of the same hash, and a restore parked in its retention copy blocks a text retry (409 `file_busy`).
- **Run started at the replacement boundary (new contract).** A second connection sets a run in R2 to `running` (a) after reservation and
  before the final transaction → `file_refused` / `run_active`, target still torn, retained file and before observation kept; (b) holding
  `BEGIN IMMEDIATE` while the restore reaches its final transaction → the restore waits for or fails on the write lock (busy timeout), never
  renames before the competing transaction ends, and ends as `file_refused` or interrupted `storage_unavailable` with the target torn.
- **Interruptions (new contract).** `OSError(ENOSPC)` while copying the damaged bytes → upload 507 `disk_full`, operation `interrupted` /
  `storage_full`, target unchanged, no retained file, no `.part`/`.partial` left; an `fsync` failure of a new retained file, of an existing
  reused retained file and of the directory before replacement → interrupted, target unchanged; a SQLite failure recording the before
  observation (injected `sqlite_errorcode` FULL) → interrupted `storage_full`, target unchanged; a reservation failure (SQLite busy) → 503,
  no row, staged removed; `os.replace` onto the target raising `OSError(EIO)` → 500, `unexpected_error`, target unchanged, retained bytes
  kept; a failure of the commit after the rename and a directory `fsync` failure after it → interrupted with the target replaced (crash
  reconciliation itself is R2c). **Failed `COMMIT` at each boundary** (reservation, before observation, replacement, after observation,
  completion, interruption; injected through a connection wrapper or `set_trace_callback`-style hook): afterwards `store.conn.in_transaction`
  is false, the state read from a second connection is the state before that boundary (or the recorded interruption), and when the
  interruption's own commit fails the interruption is pending and the next flush ends it with exactly one event. A failed `COMMIT` during
  that pending flush leaves no open transaction, keeps the pending entry, shows the unchanged running row and no terminal event from a second
  connection; a later successful flush removes the entry and commits exactly one event. Completion's event write failing once → the completion rolls back atomically and the immediate interruption
  succeeds (`interrupted`, one event); completion's event write and the interruption both failing → the row stays `running`, the
  interruption is pending, and the next `flush_text_retry_interruptions` ends it with exactly one event. `CancelledError` during the
  retention copy → `cancelled`, lock released after the thread finished.
- **Temporary files (new contract).** `check_attach` refusing, cancellation during staging after the path is allocated and before the
  staging thread returns (the thread then completes successfully), cancellation and a parser error during matching,
  an invalid `caller`: no `.part`/`.partial` left in each, the original exception seen; an unlink failure is logged and does not replace it.
- **Edge cases (new contract).** Absent file owned by A → receipt with `before_restore` `missing`, nothing retained, file restored; torn file
  with no owner (the D165 case, `test_p9_h7_torn_upload.py:10`'s seed) → receipt with `research_id` set and no affected assets, bytes
  retained; a symlink at `<sha>.pdf` pointing to a whole copy outside papers → 409 `file_not_regular` (not `reused`), link and target
  untouched; a regular file swapped for a symlink or FIFO after the first inspection (monkeypatched hook) → `file_not_regular`, nothing
  blocks, nothing followed; a pre-existing `retained-<d_torn>.bin` with the same bytes → kept, one file; one with other bytes or a symlink
  there → `file_refused` / `retention_conflict`, target untouched; the copy found `verified` under the lock (hook) → `file_reused`; the
  lock-directory helper raises on an explicit `recovery_dir` that differs from `store.recovery_dir`.
- **Guards.** Whole-file duplicates through each upload route keep their policy (no row, no rewrite: mtime unchanged); an absent unowned hash
  is written with no row (`new`); a second upload of the same bytes after a restore writes nothing; new attachments still have
  `input_observation_id` NULL (decision 7); `test_p9_h7_torn_upload.py` passes unchanged; a backup after a restore succeeds; purging R1
  leaves the retained file and the receipt rows.
- **Static guard.** An AST/grep test: within `backend/deixis`, no module but `workflow/file_restore.py` calls `os.replace` with a target
  under the papers folder (allowlist `backup.py` and the four unrelated modules listed above by name), and `pdf_files` has no
  `store_pdf_file`.
- **No call outside the writer.** With OCR, math reader, equation service, adapters and HTTP transport monkeypatched to raise, a restore
  through the generic upload completes; the parser spy shows no call for a reused source.

## Checks to run

Focused tests while building, then the whole suite inside your sandbox:
`PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest -q -p no:cacheprovider`. Tests needing sockets or process
listings fail in your sandbox; list them by name; the orchestrator reruns the full suite outside the sandbox. Keep child-process lock tests
even if your sandbox cannot run them, and say so. Then `git diff --check`. No web change: no build, lint or Playwright run.

## Report and records

Write `/tmp/reextract-r2b-impl-report.md`: files changed, each decision's implementation with file:line, every test with its role and what
it shows, existing tests changed and why, full-suite counts with the failure list, what you could not do. Draft the decision entry at the top
of `docs/decisions.md`, above D191: `## D192 — P9 re-extraction R2b: every PDF writer repairs a damaged stored file through one restore_file,
under the file lock, after keeping the damaged bytes and with a receipt; the stored text stays until a person retries it` with Status
(accepted, implemented; writer gpt-6.1-sol high; leave the reviewer line for the orchestrator), Date 2026-10-03, Context, Decision (outcomes
and when a receipt is written, ownership, the lock and the fast path, the active-run rule with no bypass, retention and its name, ordering and
durability, the serialized final check, endings and events, views, temporary-file ownership, each caller's change including matching no
longer writing and Replace PDF's file-only result, the fetch codes, initial input observations moved to R3 and who agreed), Carried work
(R2c: reconciling `running` restores and retries, deciding locks for readers (OCR run, equation reader, arXiv stamp), crash boundaries; R3:
backup and authorized purge of retained files and receipts, verified input observations for initial attachments and ordinary upgrades,
provenance views; R4: UI labels for `asset_file_restore_finished` and `file_restore`), Limits (synthetic PDFs only; no real library
repaired; retained bytes are not backed up until R3 and are never deleted by purge in R2b; the lock is advisory and an outside process can
still change a file; unlocked readers can still read torn bytes; Windows untested). Do not edit `STATUS.md` (the orchestrator does).

## Do not

Parse, retry or promote text as part of a restore; replace a non-whole hash path anywhere but `restore_file`; replace before the damaged
bytes and their observation are committed; follow a symlink at a hash path; let any run (including the fetching run) bypass the active-run
rule; write an operation row for a refusal before reservation; name the retained file by the expected hash; delete retained bytes; add a
migration without stopping first; change `views.py`, `equations.py`, any `providers/*` file, the text retry driver's behavior or the
OCR endpoint; let a cleanup failure hide the original error.
