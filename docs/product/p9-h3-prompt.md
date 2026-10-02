<!-- PLAN-REVIEW-ROUNDS: round 1 Opus 5.5 high: 1 high, 6 medium, 8 low; round 2: 0 high, 6 medium, 6 low; code review round 1: 0 high, 2 medium, 5 low; round 2: 0 high, 2 medium, 5 low (folded in without a third round); all folded in; reviewer: Opus 5.5 high (Sol quota out), Sol re-review pending -->

# Task: P9 batch H3, fault-injection inventory and the gaps it finds

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-h3`, detached at `4050a94` (origin/main, D159 on top). Plan:
`docs/product/p9-hardening-plan.md` H3 section, §4 (closing rules, rule 2) and the F05, F06, F07, F08 rows. Style models:
`docs/product/p9-h0-prompt.md`, `docs/product/p9-h0c-prompt.md`; decisions D138, D139, D159.
**No git state-changing commands.** No real-model call, no live provider call (every provider and PDF fetch is mocked).
Do not touch port 8765, ports 8858 to 8864, the live data directory, `TODO.md`, `.vscode/`, `scripts/local_index.py`, `sw-status.md`
or the other worktrees (`../DEIXIS-h1`, `../DEIXIS-h2`, `../DEIXIS-h6`, `../DEIXIS`). No migration, contract-schema or `methods/` change
(`skill_package_hash` must stay as it is). Start your own servers on free ports only and kill only the PIDs you started. Do not invent;
report what you could not measure.

Base note: `origin/main` moved to `30ce8c8` after this prompt was first written. H1 (D161, commit `6fd7a49`) added `__main__.py::data_dir_problem`; `serve` now prints its message and returns **2** for an unwritable data directory. Your startup refusal also returns 2 and goes AFTER that check. Your worktree is still at `4050a94` and you cannot rebase; write the block so it merges (a separate helper, one call). The decision number is D162 (H1 took D161); the main session renumbers if needed.

Parallel work you must not collide with: H2 writes process-crash tests under `tests/process/` (create no `conftest.py` or `__init__.py`
there; your files are `tests/process/test_disk_full.py` and `tests/process/test_library_open_faults.py`); H1 owns the unwritable-data-
directory startup message (I05) and may also edit `backend/deixis/__main__.py::serve`; H2 also edits `pdf.py` (`_arm_lifetime`), `__main__.py::serve` (`watch_shutdown`), `api/app.py` and `tests/conftest.py` (a `process` pytest marker that leaves `process` tests out of the default run); H6 edits `PdfViewer.tsx` (near line 98, `setError`) and `i18n.ts`. Keep each of your edits to those files small and local. H4 owns the read-only precheck for an unknown
migration id (B03) and the backup of a damaged library. Keep your edit to `serve` to one short block so a rebase merges.

## Why

P9 needs every fault class in the F rows to have one named test or an explicit "out of scope, and why", and the user-visible text of
each failure checked against the one-sentence-and-a-reason rule (`.impeccable.md` copy rule), not a raw exception. The inventory below
was made by reading the code and the tests at `4050a94` (grep and read, nothing run, then the measurements in the next section).

## Measured before implementation (macOS 27.0.1 arm64, Python 3.12, small sparse disk image mounted under /tmp)

- Disk full, real fixture server (`tests/acceptance/fixture_server.py`) with its data directory on a 16 MiB HFS+ sparse image filled to 0
  bytes free: `POST /api/researches` answers 500 "Internal Server Error" (traceback `sqlite3.OperationalError: database or disk is full`
  at `COMMIT`); `POST .../uploads` answers 500 (`OSError: [Errno 28]` creating `papers/`); `/api/health` still 200; after the space is freed an
  upload gives 201. Server start on a full disk fails in `db.migrate` with a traceback. Nothing in `backend/deixis` catches
  `sqlite3.OperationalError`/`DatabaseError` or `ENOSPC`; the only OSError-to-HTTP mappings are the two `.env` 503s.
- Worker: `Worker.run_forever` has no guard around the heartbeat UPDATE, `next_queued_run()` or the `update_run(... failed ...)` in its
  `except Exception`; a sqlite error there ends the worker task (no more runs until restart; the run stays `running`).
- Corrupt library at open (`db.connect` then `db.migrate`, scripts run on copies): a garbage file raises `DatabaseError: file is not a
  database` and the file hash is unchanged; a truncated copy (half, 4096 bytes, 100 bytes) raises `database disk image is malformed`, the main
  file hash is unchanged but empty `-wal` and `-shm` files appear; a zero-byte file becomes a fresh library (first run); a file with 4 KiB of
  garbage inside a data page opens without error (only `integrity_check` sees it); a library that records migration id 9999 opens without error
  (that is B03, H4). `serve` shows all of these as an uvicorn traceback.
- PDFs through `pdf.extract_pdf` on generated files: password-protected (user password) gives status `no_text`, 2 pages, 0 text, which the UI
  words "PDF has no text layer" (wrong reason, and OCR would be offered); owner-password-only gives `succeeded`; truncated or 9-byte-header file
  gives `failed` with the MuPDF traceback tail in `extraction_error`; a PDF with an empty page tree gives `no_text`, 0 pages; 450 pages gives
  `partial`, `page_count` 450, 400 pages read. `extraction_error` is stored but is not in the research view and not shown.

## Inventory at `4050a94` (class, existing test, verdict)

Line numbers are `def test_...` lines. `tests/test_api_flow.py` defines 35 test names twice; only the later copy runs (cleanup is outside H3;
report it). "Weak" means the test exists but asserts the status code only.

| Class | Existing test | Gap in H3 |
|---|---|---|
| P1 provider timeout | `tests/test_providers.py:386` (all 10 providers, `timeout`/`after_send_unknown`), `tests/test_candidate_flow.py:198,:692`, `apps/web/e2e/candidate.spec.ts:589` (mocked JSON, a weak link to P1) | none for the connector; discovery-flow level (stored `search_runs.status`, run pause `provider_timeout`) has NO test: add |
| P2 provider 5xx | `test_providers.py:386`, `tests/test_search_parallelism.py:343,:335` | weak: step status not asserted (code stores `outcome_unknown` for the step, `failed` on the `search_runs` row): add the assertion in a new test |
| P3 429 / quota | `test_providers.py:317,:334,:349,:370`, `tests/test_api_flow.py:1379`, `tests/test_search_paging.py:300`, `tests/test_effort_limits.py:105`, `apps/web/e2e/acceptance.spec.ts:513` | none; the UI does not tell quota from rate limit (stated limit) |
| P4 malformed JSON body | `test_providers.py:386` (`<html>`, all 10), `tests/test_openalex.py:95` | flow level (`search_runs.status parse_error`, pause `provider_parse_error`): add |
| P5 empty 200 body | none | add, all providers that `test_providers.py` parametrizes |
| P6 slow success | `test_search_parallelism.py:472,:452,:542,:639` | none (no delay near the real 30 s limit; stated) |
| P7 zero results vs failure | `test_providers.py:328`, `test_search_paging.py:362`, `test_candidate_flow.py:198`, `apps/web/e2e/acceptance.spec.ts:519` | none |
| D1 encrypted PDF | none | add; product defect (mislabelled `no_text`): fix |
| D2 zero-page PDF | none | add; same fix |
| D3 above `MAX_PAGES` | none | add (450-page file, `partial`, 400 read) |
| D4 corrupt or truncated PDF | none direct (`tests/test_fetch_overlap_flow.py:488` indirect) | add; raw traceback in `extraction_error`: fix |
| D5 non-PDF bytes | `tests/test_documents.py:79` (extraction only) | add upload route 422 text and the fetched-bytes path through the upload route |
| D6 upload over 50 MiB | `test_api_flow.py:1668` (weak) | add the message assertion; missing Content-Length 411 untested: add |
| D7 download over 30 MiB | none for PDFs (`tests/test_arxiv_source_fetch.py:156` is the arXiv source file) | add `fetch_pdf` `too_large` and its stored flow code `fetch_too_large` |
| D8 private or unsafe URL | `test_documents.py:104,:275,:253`, `test_arxiv_source_fetch.py:182` | flow mapping `blocked_url` to stored code: add one assertion |
| D9 text above the limit | `test_documents.py:109,:117,:221,:167` | none |
| D10 asset file missing on disk | none (`tests/test_backup.py:246` is the backup refusal) | add the 404 "File missing" routes and a UI reason |
| O1 SQLite busy or locked | only `tests/test_arxiv_source_route.py:507` (exclusion, not error handling) | add; bare 500 today: fix |
| O2 CSRF | `test_api_flow.py:1685` and 8 other files (status only) | add the `detail` assertions only; stated: `api.ts` refreshes the token once, so a CSRF refusal is rarely visible |
| O3 Host/Origin | same tests (status only) | same; a wrong Host blocks the page itself, so no UI text can exist (out of scope for copy, reason stated) |
| O4 model `client_timeout` | `tests/test_adjudication_flow.py:724,:787,:805`, `tests/test_queue_api.py:656` | none; text is the generic "The model call did not complete" (no cause, stated limit) |
| O5 `model_mismatch` | `test_api_flow.py:1478`, `tests/test_lineage_flow.py:1092`, `tests/test_report_flow.py:504`, `tests/test_report_review.py:181` | none |
| O6 schema repair exhausted | `test_api_flow.py:1334,:1826`, `tests/test_report_flow.py:740`, `tests/test_table_extraction.py:438`, `tests/test_candidate_flow.py:225`, `tests/test_criterion_flow.py:124` | none |
| O7 model quota | `tests/test_adapter_rate_limit.py:12`, `test_report_flow.py:269,:290`, `tests/test_lineage_flow.py:752` | none; stops as generic `model_call_failed` (stated limit) |
| O8 corrupt or truncated library | none | add (real process); traceback today: fix |
| O9 library missing, data files present | none | add (real process); behavior is a fresh empty library with the orphan files untouched: pin it, record it as a limit |
| O10 unknown migration id | none | out of scope for H3: B03, H4 (F06 stays split, see verdicts) |
| O11 unwritable data directory | none | out of scope: I05, H1 |
| O12 disk full (F05) | none | add (real process on a disk image + in-process worker test); 500 today: fix |
| Backup of a damaged library | none | out of scope: H4 |

## What to do

### 1. Backend fixes (smallest change that makes each test below pass)

a. **Database and disk errors in a request** (`backend/deixis/api/app.py`). Register handlers, near the existing ones, for
`sqlite3.DatabaseError` and for a small typed `DiskFull` exception that `store_upload` raises (it catches `OSError` with `ENOSPC`/`EDQUOT` from its own write and re-raises it as `DiskFull`; a global `OSError` handler is avoided because Starlette wraps an exception of a handled class raised after the response started in a `RuntimeError`). Other disk-full `OSError`s in routes stay a 500 and are listed as a limit. Classify with one small function (put it in `backend/deixis/storage/db.py`, e.g.
`describe_failure(exc) -> tuple[str, int, str] | None` returning code, HTTP status and the English sentence) so the request handler, the
worker and the startup message use the same text:
- SQLite primary result code 13 (`SQLITE_FULL`) or `OSError` with `errno.ENOSPC` or `errno.EDQUOT`: code `disk_full`, 507,
  "DEIXIS could not save because the disk is full. Free some space and try again."
- primary codes 5 or 6 (`BUSY`, `LOCKED`): `database_busy`, 503, "DEIXIS could not save because another process is using the library. Try again in a moment."
- code 8 (`READONLY`): `database_readonly`, 503, "DEIXIS could not save because the library file is read-only. Make it writable, or restore a copy, and try again."
- codes 11 (`CORRUPT`) and 26 (`NOTADB`): `database_damaged`, 503, "DEIXIS cannot read its library because the file is damaged. Restore it from a backup."
Use `getattr(exc, "sqlite_errorcode", None)` and `& 0xFF` (Python 3.12; an exception without the attribute is unclassified).
**Prerequisite (review finding, measured):** `db.transaction` (`storage/db.py:48-52`) runs an unconditional `ROLLBACK` in its error branch. SQLite has already rolled back after a statement-level `SQLITE_FULL`, so that `ROLLBACK` raises `OperationalError: cannot rollback - no transaction is active` (code 1) and the real error survives only in `__context__`; the classifier would miss it and the response would stay 500. Change it to `except BaseException: if conn.in_transaction: conn.execute("ROLLBACK"); raise`. Do not edit sibling helpers in `store.py`, `candidates/store.py` or `lineage/store.py` unless a test shows the same defect. A test must prove it: `max_page_count` makes an INSERT inside `db.transaction` raise with `sqlite_errorcode == 13`, and a route over such a store answers 507. Any other `DatabaseError` or `OSError` is re-raised unchanged by the handler, so a code bug
still ends as the 500 it is today and `IntegrityError` handling in `store.py` is not affected. The response body is
`{"detail": <sentence>, "code": <code>}`. Never put the exception text, a path or a table name in `detail`.

b. **Worker** (`backend/deixis/workflow/worker.py`). A `sqlite3.DatabaseError` or `OSError` inside the loop body (heartbeat, `next_queued_run`,
`update_run`) must not end `run_forever`: log it (once per distinct error class until a turn succeeds, not every second), wait about a second (stop-aware) and go on. A run that failed with a failure that
`describe_failure` classifies as `disk_full` is recorded `failed` with `pause_reason = "disk_full"` (other failures keep `internal_error`
and the existing `error_json`). If recording the failure itself raises a database/OS error (the disk is still full), keep
`(run_id, reason, error_json)` in memory and retry the write at the top of each loop turn until it succeeds, so the run does not stay
`running` once there is room again. No other change to the loop, to `recover`, or to run states.

c. **Startup message** (`backend/deixis/__main__.py::serve` plus a helper in `storage/db.py`). After the existing port check and before
`uvicorn.Server`, open the library the way the app will (`db.connect`, `db.migrate`, close) inside a `try`; catch only what `describe_failure` classifies (damaged or not-a-database: advice "restore it from a backup or move it aside"; full: "free some space"; busy: "close the other DEIXIS or tool using it"; read-only: as above). Any other exception (a failing migration, which today ends in uvicorn's lifespan traceback with exit code 3 and from `serve` would end with code 1; say which in the record, `CANTOPEN` on an unwritable directory, which is H1's) is NOT caught and ends as it does today. On a classified failure
print ONE sentence to stderr that names the library path and the reason, say that DEIXIS did not start and changed nothing, and return 2 (as H1's message does). Example:
"The library file {path} could not be opened ({reason}), so DEIXIS did not start and changed nothing; {advice}." `{reason}` is the
SQLite message (`file is not a database`, `database disk image is malformed`, `database or disk is full`). No traceback. A missing file is not an
error (first run). Do not add an unwritable-data-directory message (H1) and do not add the unknown-migration check (H4); leave a comment pointing at
both, and a comment that H4's read-only precheck must run BEFORE this block (this block's `db.connect` creates `-wal`/`-shm` files and switches the journal mode). This must not change the behavior for a healthy library.

d. **PDF failure classes** (`backend/deixis/documents/pdf.py`). In `_extract_in_process`, a document with `needs_pass` (measured: this alone suffices; owner-password-only files have `needs_pass` 0) that
cannot be read without a password fails with error text `password-protected PDF`; `page_count == 0` fails with `PDF has no pages`; a file MuPDF
cannot open fails with `PDF could not be read` instead of the traceback tail. Protocol (the parent currently stores the last 400 characters of stderr for any nonzero exit, and exit code 3 means the memory limit): the child's `__main__` catches the three named conditions (and `ValueError("not a PDF")`, and MuPDF's open error) and writes `{"error": "<fixed text>"}` to stdout, exiting 0; the parent passes a known fixed text through unchanged; any other nonzero exit (a crash, a signal) becomes `PDF could not be read`, with the stderr tail going to the log only, not into `extraction_error`; keep the
existing `extraction timed out`, `extraction exceeded the memory limit` and `extraction memory limit could not be watched` strings and the
`failed` status; owner-password-only files that open stay `succeeded`). Do not change `Extraction`'s statuses, `EXTRACTION_VERSION` or the stored
format. Put `extraction_error` in the research view's asset dict (`workflow/views.py`, the `SELECT` near line 604) as an additive key.

### 2. Web (`apps/web/src`; read `.impeccable.md` first; strings in English and Turkish via `i18n.ts`; no layout or CSS change)

- `api.ts::request` (and the export error path only if it already parses `detail` the same way): when the error body has a string `code`, show
  `t(detail)` as the message (English text is the key). Add the Turkish renderings of the four sentences in 1a to `i18n.ts`, appended at the end of the `tr` map (H6 edits near line 1857). Do not translate
  other backend messages.
- `labels.ts` pause reasons: add `disk_full` with "The disk is full, so DEIXIS could not save this run. Free some space and start the run again." (EN and TR).
- `labels.ts::accessParts` (line ~321, the source list's PDF line): a `failed` asset today reads "PDF · ? pages · text failed" (page count unknown) with `tone: 'text'`. Add a `failed` branch with `tone: 'unstated'` and the same three reason fragments as below.
- `PdfReadiness.tsx::missingReason`: for `extraction_status === 'failed'` return `t('PDF is password-protected')`, `t('PDF has no pages')` or
  `t('PDF could not be read')` from `extraction_error` (any other failed error: `t('PDF could not be read')`); EN and TR. Add `extraction_error`
  to the `Asset` type in `api.ts`.
- The missing PDF file (D10): `PdfViewer.tsx` shows pdf.js's own message after "Could not display PDF". When the asset request answers 404 ("File missing")
  show `t('The PDF file is missing from the data folder. Add the PDF again.')` instead. Change only the `setError` in the `getDocument().catch` (about line 29), not line 98 or 99 (H6 edits 98, and 99 is the `Notice`); pdf.js's error carries a `status` field here; if the viewer cannot see the status,
  say so in your report rather than rewriting it.
- The upload refusals "PDF larger than 50 MB", "Only PDF files are supported", "Upload size must be declared": add Turkish renderings; they travel
  through `request()`, which only translates when `code` is present, so give them a code (`upload_too_large`, `upload_not_pdf`, `upload_size_undeclared`). `store_upload` raises `HTTPException` (it cannot carry a body field), so add one small exception class with a handler answering `{"detail": ..., "code": ...}` for the two raised there (`app.py:517`, `:521`), and add `"code"` to the `JSONResponse` refusals in `local_guard` (`:647-650`; the 413 text exists in two places). Keep status codes and English texts.
No Playwright spec is required for these strings; one is allowed if it is small and deterministic. Build, lint (17 warnings baseline), and run the full
Playwright suite once after the web edits.

### 3. Tests (new files only; do not edit existing tests except to fix a test your change breaks, and say which)

`tests/test_p9_faults.py` (in process, model-free, socket-free apart from the existing `create_app` patterns), one test per inventory row marked "add":
- P5 for every provider of `test_providers.py::ALL` (200 with empty body: measured, all 10 give `status == "parse_error"` and `delivery_class is None`).
- P1, P4, P2 at discovery-flow level through the `test_search_parallelism.py` helpers (`Hosts`, `run_discovery`; subclass or wrap, do not edit): stored `search_runs.status`,
  run `pause_reason`, step status for the 5xx case, and that the pause reason has a sentence in `apps/web/src/labels.ts` (read the file as text and assert the
  key and a non-empty sentence; say in a comment that it checks presence, not rendering).
- D1 to D5, D3 (450 pages), via `pdf.extract_pdf` and the upload route (`tests/helpers.py::make_pdf` or `pymupdf` to build the encrypted, zero-page, truncated, empty-tree files; the
  zero-page file is raw bytes with an empty page tree). Assert status, `extraction_error` text and, through the research view, `extraction_error` on the asset.
- D6 message and 411 (and `fetch_pdf`'s two branches separately: a declared `Content-Length` over 30 MiB at `fetch.py:~132`, and an undeclared stream that passes the limit at `~137`) (a request without Content-Length: send the multipart body with a chunked generator through `httpx`), D7 (`fetch_module.fetch_pdf` with a mock transport that declares
  and streams more than 30 MiB: status `too_large` (`fetch_pdf` writes nothing, so the no-residue claim is tested at flow level: no `source_assets` row and an empty `papers/`); and the flow's stored `fetch_too_large` for a work whose link answers that), D8 flow mapping,
  D10 (delete the stored file, then GET the asset, `/figures` and a re-extract (set the asset's `extraction_version` to an old value first, otherwise the route answers 200 "unchanged" before it looks at the file): 404 "File missing"; the passage text route still answers).
- O1, O12 request handlers: a route whose store call raises `sqlite3.OperationalError` created with the right code (build it with `sqlite3` by really filling a tiny database
  with `PRAGMA max_page_count` for FULL, and by holding a write lock from a second connection with a short timeout for BUSY, with the app connection's `PRAGMA busy_timeout` set to about 50 ms so the test does not wait the production 30 s; never fake a message string), answers the code, status, JSON sentence;
  an unrelated `OperationalError` (no such table) still answers 500; an `OSError(ENOSPC)` inside `store_upload` answers 507 and leaves no `.partial`.
- Worker: `run_forever` survives a database error in the heartbeat and in recording a failure, records `disk_full` once the write works, and then runs the next queued run (drive it
  with `Worker` over a real `Store`, a fake flow, and `asyncio`; keep the waits short by patching the sleep).
- P5 at flow level is not tested separately (the connector returns the same `parse_error` as P4; say so in the record).
- O2, O3: the `detail` text of the three guard refusals (existing tests assert the status only).
Name each test after the class (`test_d1_...`) and put the inventory id in the docstring.

Both process files set `pytestmark = pytest.mark.process` (H2 adds that marker and the default-run exclusion in `tests/conftest.py`, uncommitted, so your base has neither; do not touch `conftest.py`). On your base the full run is therefore `pytest -m "not process"`, and the two process files are run on their own with `-m process -n 0`; write both commands in the record. They are slow and must not run under `-n auto` load.

`tests/process/test_disk_full.py` (macOS only; `pytest.mark.skipif` when `sys.platform != "darwin"` or `hdiutil` is missing, with the reason in the marker): create a 16 MiB HFS+ sparse image
with `hdiutil create -type SPARSE`, attach it with `hdiutil attach -mountpoint <tmp_path>/mnt -nobrowse -noverify`, always detach it (`hdiutil detach <mountpoint> -force`) and
delete the image in a `finally`/fixture finalizer even when the test fails. It touches no other volume. Start `tests/acceptance/fixture_server.py` as a subprocess on a free port with its data
directory on the image, an allow-listed environment (`PATH` without model CLIs, `HOME` set to a temp dir, `PYTHONPATH`, `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring`), and a fresh `httpx` client per request after a
failure (a failed request closes the keep-alive connection). Before filling, run `PRAGMA wal_checkpoint(TRUNCATE)` from a separate connection to the library (SQLite reuses WAL space after a checkpoint, so small commits can succeed at 0 bytes free), then fill the free space with a file of the volume (write with `buffering=0` in decreasing chunk sizes down to one byte; a closing flush
can raise). Expect (record the number of attempts; the first attempt after filling must already be refused): create-research and upload answer 507 with code `disk_full` and the sentence, `/api/health` stays 200, no `.partial` file remains in `papers/`; after the filler is deleted a
create and an upload succeed (201); stop the server (SIGTERM, wait) and `PRAGMA integrity_check` is `ok` and `PRAGMA foreign_key_check` is empty on the file. Kill only the PID you started. Also assert that every `papers/*.pdf` has a SHA-256 equal to its file name and that no `.partial` or `.part` file remains. H2's `pdf_files.store_pdf_file` (temporary `.part` and `os.replace`) fixes the direct `write_bytes` at `acquisition.py:~472`, `flow.py:~2691`, `app.py:~1675/1712`; do NOT touch those lines. If the check fails on your base, record F05's download half as "depends on H2, partial" and do not fake a pass. The plan names the PDF download path for F05: add one step where the fixture's mocked PDF fetch (a run over the fixture's own scripted PDF link) runs while the disk is full; expected, the run ends `failed` with `pause_reason disk_full` (or the nearest honest state you measure), and after space is freed the next run starts and completes. If the fixture cannot drive that deterministically, report F05's download half as "partial" instead of faking it.

`tests/process/test_library_open_faults.py` (real `python -m deixis serve --no-browser --port <free>` subprocess from the repo root with the same named allow-list as the disk test: `PATH` without model CLIs, temporary `HOME`, `PYTHONPATH`, `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring`, `DEIXIS_DATA_DIR=<tmp>`, nothing else): garbage file, truncated copy (half and 100 bytes) of a real library: exit code 2 within a few seconds, stderr holds the library path and the SQLite reason and no `Traceback`, the SHA-256 of the
main file is unchanged (record in a comment that empty `-wal`/`-shm` files may appear and that this is not asserted away); a zero-byte file starts as a fresh library (health 200, then SIGTERM); a
missing library with a `papers/` folder holding a file starts empty and the orphan file is byte-identical afterwards (pins O9; comment says it is a limit, not a goal).

### 4. Record

- `docs/decisions.md`: new top entry `## D162 — P9 H3: ...` (check the highest number on main and in the other worktrees at write time; the main session renumbers). Status line:
  `accepted (implemented, uncommitted; reviewer: Opus 5.5 high (Sol quota out), Sol re-review pending)`. Context, Decision (the inventory table: class, existing test file:line, new test name or
  "out of scope + why"), the per-row verdict for F05, F06, F07, F08 (F06: the corrupt/truncated half passes, the unknown-migration half stays with H4/B03 and is NOT shown by H3), Verification (counts), Limits
  (what a disk image on one machine does not show; HFS+ not the user's APFS volume; ENOSPC on a different write path not hit; quota/rate-limit and generic model text; CSRF/Host copy; PDF
  classes MuPDF accepts but we did not generate; `test_api_flow.py` duplicate names; the stale `running` step rows after a mid-step database error are not changed; `EXTRACTION_VERSION` is unchanged and a `failed` re-extraction ranks below `no_text` (`store.py:~1538`), so password-protected PDFs stored earlier stay `no_text` permanently and OCR is still offered for them; `match_waiting`'s `has_text_layer` is `null` for a password-protected file; truncating only data pages of a populated library can open without error).
- Add one status line under the H3 section of `docs/product/p9-hardening-plan.md` ("H3 uygulandı", with the number the main session gives), nothing else in the plan.

## Checks to run (in the worktree; `PYTHONPATH=backend:. uv run ...`, `UV_CACHE_DIR=/tmp/deixis-uv-cache`)

New test files alone; the files you touched near (`tests/test_documents.py`, `tests/test_api_flow.py`, `tests/test_providers.py`, `tests/test_search_parallelism.py`, `tests/test_backup.py`); then the full
`pytest` (parallel by default; a test that fails under load and passes alone is rerun alone and named; known flaky: the audit stratum test and `test_builtin_embedding_flow` 429 wait); then, because `apps/web`
changes: `npm run build`, `npm run lint` (17 warnings, no new), and the Playwright suite (clone `node_modules` with `cp -c -R` from the main checkout, make a temporary `.venv` symlink the suite needs, remove
both afterwards; `DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance-h3`). After the run: `hdiutil info` shows no image of yours still attached, no `/tmp/deixis-acceptance-h3` server left, no PID of yours alive.

## Do not

Do not rewrite existing tests; do not add features beyond the list; do not change provider retry behavior, run states, the answer flow or the method package; do not touch `backup.py`; do not edit
applied migrations. If a measurement contradicts this prompt, report the measurement and the smallest deviation you made.
