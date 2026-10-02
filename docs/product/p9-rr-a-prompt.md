<!-- PLAN-REVIEW-ROUNDS: r1 (gpt-6.1-sol high): düzeltmeyle hazır, 0 high + 4 medium + 1 low, all folded in; code r1: düzeltmeyle hazır, 1 medium fixed; code r2: hazır (F5 test order, F7 nine call sites, process-test ports, F1 identity check and test matrix, F3 fixture) -->

# Task: P9 fix batch RR-A, the gpt-6.1-sol re-review findings on H2 (finding 1), H3, H4 and H7 (storage, backup, startup, API)

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-rra`, detached at `c5db475` (main also holds `3b7bd31`, a docs-only P7 commit). The findings are
in `/tmp/solrr/h4-answer.md`, `/tmp/solrr/h3-answer.md`, `/tmp/solrr/h7-answer.md` and `/tmp/solrr/h2-answer.md` (finding 1 only); Sol said each one
still holds on main. The batches behind them are `docs/product/p9-h{2,3,4,7}-prompt.md`, their decisions D162 to D165 in `docs/decisions.md`. Run tests
with `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest ...` (the venv exists, arm64).

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted. No real-model call, no
provider call, no network. Do not touch `../DEIXIS*` worktrees, `TODO.md`, `.vscode/`, `scripts/local_index.py`, the live service on port 8765, ports
below 8980 or above 8990, or `~/Library/Application Support/DEIXIS`. **Never run anything of this batch against a live data directory.** Every test uses
`tmp_path` and synthetic data. No method, contract or migration change. Do not invent; report what you could not find or fix.

## Files

Allowed: `backend/deixis/storage/db.py`, `backend/deixis/storage/backup.py`, `backend/deixis/__main__.py`, `backend/deixis/api/app.py`,
`scripts/p9/upgrade_check.py`, new test files `tests/test_p9_rr_a_*.py`, small edits to existing tests whose expectation this batch changes on purpose
(named below), `docs/decisions.md` (one new decision), `docs/product/p9-hardening-plan.md` (one status line each for H2, H3, H4, H7).
Not allowed (RR-B owns them): `scripts/p9/run_matrix.py`, `scripts/p9/capacity*`, `backend/deixis/documents/pdf.py`,
`backend/deixis/documents/arxiv_source.py`, `tests/process/test_p9_children.py`, `apps/web/e2e/report-edit.spec.ts`,
`docs/product/p9-acceptance-record.md`. Nothing under `apps/web`.

Each code change gets a test that **fails on the old code**; run it on the old code first (stash is forbidden: write the test, run it, see it fail, then
change the code), and say so in the report.

## The fixes

### F1 (high, H4 finding 1): B02 sub-paths can reach the live directory (`scripts/p9/upgrade_check.py`)

Today `restore_copy` and `open_copy` only keep `WORK_DIR` itself away from protected directories and the marker's LIVE_DIR. A symlink or hard link at
`WORK_DIR/live-copy`, `WORK_DIR/backup`, `WORK_DIR/restored`, `restored/library.sqlite`, `restored/library.sqlite.restoring`, `restored/papers` or
`live-copy/library.sqlite` reaches the live directory: `create_backup` opens `live-copy/library.sqlite` with a normal SQLite connection (can checkpoint
and write), writes the backup under `WORK_DIR/backup`; `restore_backup` copies into `restored/` and copies the database to
`library.sqlite.restoring` (`shutil.copyfile` writes through a symlink); `open_copy` opens `restored/library.sqlite` through the app (migrations).

Build one function, e.g. `check_work_tree(work_dir, live_dir)`, in the script's "path rules" section:
- walk `WORK_DIR` **without following symlinks** (`os.scandir` recursion, or `os.walk` with `followlinks=False` and a check of `dirnames` too);
- a symlink anywhere under it (file or folder, working or dangling) raises `Refused`, naming the path relative to WORK_DIR only;
- a regular file with `st_nlink > 1` raises `Refused` (a hard link to a live file shows as nlink 2 on both sides; files made by `copy-live`, the backup
  and the restore have nlink 1; a macOS clone from `shutil.copyfile` is not a hard link);
- compare `(st_dev, st_ino)` of every `library.sqlite*` file found under WORK_DIR and of every regular file under the sub-paths with the files of LIVE_DIR
  (`lstat`, names only; LIVE_DIR is listed with `os.scandir` and its files `lstat`ed, never opened): a match raises `Refused`. This is the real hard-link test;
  `st_nlink > 1` stays as a deliberate, conservative second rule (it also refuses harmless local hard links, and it does not refuse APFS clones, which are
  independent files);
- use `lstat` / `follow_symlinks=False` everywhere; a scan error (`OSError`) is a `Refused`, never skipped silently;
- every top-level sub-path that exists (`live-copy`, `backup`, `restored`) must have a resolved path inside the resolved WORK_DIR and must pass
  `forbid_protected(..., (live_dir,))`.
Call it: in `restore_copy` before `create_backup`, again after `create_backup` and before `restore_backup`, and in `open_copy` (`check_open_paths`)
before anything is opened. Output stays names and counts only. Exit code 2 through the existing `Refused` path. Do not weaken `copy-live`'s rules.
Tests (new file `tests/test_p9_rr_a_upgrade_paths.py`, same `dirs`-style fixtures as `tests/test_p9_upgrade_check.py`, a SYNTHETIC live folder built
with `make_source_library`; never the real directory). Prepare WORK_DIR with a real `copy-live` run (so the marker exists), then replace one piece by a
link, then call the subcommand named here; each must raise `Refused` (`main` returns 2):
- `restore-copy` with `live-copy` replaced by a symlink to the live folder (old code: opens the live database; must fail on old code);
- `restore-copy` with `backup` pre-created as a symlink to a folder inside tmp that is not protected (old code writes the backup through it; must fail on old code);
- `restore-copy` with `live-copy/papers` as a symlink to another tmp folder; `restore-copy` with `live-copy/library.sqlite` replaced by a hard link to the live library;
- `restore-copy` with `restored/` pre-created containing a symlink `library.sqlite.restoring` that points at the live library file (old code writes through it);
- `open-copy` after a good `restore-copy`, with `restored/library.sqlite` replaced by a hard link to the live library, and again by a symlink to it;
- `open-copy` with `restored` itself a symlink to a non-protected tmp folder (old code accepts that).
`restored` as a symlink straight to the live folder and `restored/library.sqlite` already existing before `restore-copy` are refused by the old code too
(`forbid_protected`, "a library already exists"): include them as regression guards and say in the report they do not prove a fix.
After each: the live folder is byte-identical (hash every file, `-wal` and `-shm` included) with no file added, and no SQLite connection was opened on a
live path (extend the `tripwire` idea to record every `sqlite3.connect` argument and `shutil.copyfile` destination, and compare resolved paths and
`(st_dev, st_ino)`, not only the argument). Also one test that a normal `copy-live` then `restore-copy` then `open-copy` still passes.
The guard protects against links that exist when it runs; it gives no guarantee against a path swapped between the check and the use (single-user tool;
record that in the decision's Limits).

### F2 (medium, H4 finding 2): a symlinked `library.sqlite` slips past the schema guard (`storage/db.py`)

`check_schema_known` tests `-wal` by the link's name, so a symlink to a real database whose real `-wal` holds an unknown migration is accepted. Resolve
the database path at the top of `check_schema_known` (`path = Path(path).resolve()`) and use that one path for every sidecar test, the copy and the
immutable URI; in `connect` open SQLite with the resolved path too (the `path.parent.mkdir` stays on the given path). Test: a real library with known
migrations in the main file and an unknown id (`9999`) only in its real `-wal` (see `library_with_id_only_in_the_wal` in
`tests/test_p9_restore_matrix.py`; reuse or copy it), a symlink to it in another folder: `check_schema_known(link)` raises `UnknownSchemaError`, and
`connect(link)` does too.

### F3 (medium, H4 finding 3): the staged database is not checked against the manifest hash (`storage/backup.py::restore_backup`)

After `shutil.copyfile(backup / DB_NAME, staging)` compute the hash of `staging` and compare it with the manifest entry's `sha256` **before** the integrity
check; on mismatch unlink `staging` and raise `BackupError("restored database does not match the manifest")`; also unlink `staging` when the integrity
check fails. `os.replace` is never reached on a mismatch. Test: wrap `shutil.copyfile` (monkeypatch on `deixis.storage.backup.shutil`) so that, for a
destination ending `.restoring`, after the real copy it opens the staged file and changes a stored text with SQL (integrity stays `ok`). `make_source_library` creates researches only: first
add a real SYNTHETIC passage or other text row, or change an existing research title, and assert the UPDATE changed exactly one row. Restore raises
`BackupError`, `library.sqlite` does not exist, no `.restoring` file remains. A second test: a staged copy that fails the integrity check (damage the copy
so `PRAGMA integrity_check` is not `ok` or SQLite raises `DatabaseError`) also leaves no `.restoring` file once the connection is closed.

### F4 (medium, H4 finding 4 and H3 finding 1): temporary-folder creation is outside the controlled refusal (`storage/db.py::_applied_versions_from_copy`)

`tempfile.TemporaryDirectory(...)` runs before the `try`; an ENOSPC/EDQUOT/permission error escapes as a raw `OSError`, and `serve`/`reextract` end in a
traceback with exit 1. Create the folder inside a guard that turns `OSError` into `SchemaCheckUnreadable` with the existing "free some disk space or fix
the permissions" sentence (and keep the cleanup behaviour). The `path.stat()` calls in that function are inside the same guard. Tests: with a library that
has a non-empty `-wal` (the helper above), monkeypatch `tempfile.TemporaryDirectory` to raise `OSError(28, ...)` and then `OSError(13, ...)`:
`check_schema_known` raises `SchemaCheckUnreadable`; `deixis.__main__.serve(settings, False, ())` returns **2**, prints one message with no `Traceback`, creates
no app, and changes no file (use the fixtures `fake_uvicorn`, `settings_for`, `free_port`, `file_facts` of `tests/test_p9_restore_matrix.py`); `reextract`
likewise returns 2.

### F5 (medium, H3 finding 3): the startup refusal says it "changed nothing" although finished migrations stay (`storage/db.py::open_problem`)

Migrations commit one by one; a failure at migration N leaves 1..N-1 applied. Change the sentence (it currently ends "so DEIXIS did not start and changed
nothing; ...") to: `... could not be opened ({reason}), so DEIXIS did not start. A schema migration that had already finished stays applied; {advice}.`
Update `tests/test_p9_faults_documents.py:471` accordingly (it asserts "did not start and changed nothing"; assert "did not start" and "stays applied"
instead). New test: a temp `MIGRATIONS_DIR` (monkeypatch `db.MIGRATIONS_DIR`) with `0001` creating a table and `0002` that must fail with SQLITE_FULL
(it inserts a `zeroblob(1000000)`). Do it in this order, or the limit hits `0001` itself: first run `db.connect` + `db.migrate` with only `0001` on the
file and close; then add `0002` to the temp folder and call `open_problem` with `db.connect` wrapped so the returned connection gets
`PRAGMA max_page_count = <its current page_count>` before `migrate` runs. The error has `sqlite_errorcode` 13. Assert: `open_problem` returns the new
sentence, the sentence does not contain "changed nothing", the version row and table of `0001` are in the file, the version row of `0002` is not. No
change to `migrate` itself.

### F6 (medium, H3 finding 2): a disk full while the multipart parser spools a big upload answers 400 instead of 507 (`api/app.py`)

FastAPI parses the body before the endpoint runs; an `OSError` from Starlette's spooled temp file (above 1 MiB) becomes
`HTTPException(400, "There was an error parsing the body")` with `__cause__` set to the original error, so `DiskFull` never fires. Add an exception
handler for `starlette.exceptions.HTTPException` that returns the 507 `disk_full` JSON when `db.describe_failure(exc.__cause__)` names a failure (use the
same body shape as the existing `storage_failed` handler) and otherwise delegates to FastAPI's default `http_exception_handler` unchanged (same status,
detail and headers for every other HTTPException; the existing tests prove it). Tests: monkeypatch `tempfile.SpooledTemporaryFile.rollover` to raise
`OSError(28, ...)`, post a 2 MiB PDF-looking upload to `/api/researches/{id}/uploads` of an attached-scope research (use `test_api_flow` helpers as
`tests/test_p9_h7_torn_upload.py` does): status 507, `code == "disk_full"`. A second test: a normal 404 and a 422 still come out as before; an
unrelated `OSError` (errno 13) in that stage still gives 400.

### F7 (medium, H7 finding 1): directory creation in the Zotero routes can still 500 (`api/app.py`)

`settings.payloads_dir.mkdir(...)` (zotero import) and `settings.papers_dir.mkdir(...)` (zotero import, zotero-pdfs) run outside `disk_full_refused()`.
Put each inside the guard (the same `with` as the following write where that reads naturally). The upload routes have the same unguarded
`settings.papers_dir.mkdir` (`upload`, `upload_to_source`, `match_uploads`): guard those too, they are the same class and the same sentence.
There are **nine** such call sites in `api/app.py`: the three Zotero ones, `upload`, `upload_to_source`, `match_uploads`, `match_waiting` (~line 1566),
`attach_waiting_pdf` (~1607) and `replace_asset` (~1941). They all run during a request and none is excluded. Guard all nine.
Tests: for each of the nine call sites, make the `mkdir` of exactly that synthetic target path (the full `tmp_path/.../papers` or `provider-payloads` path,
not just the folder name) raise `OSError(28)`, with the folder absent, and assert 507 `disk_full`; and `OSError(13)` there is still a 500. Extend or follow `tests/test_p9_h7_zotero_disk.py`; extend its AST test
so it finds every `mkdir` of `papers_dir`/`payloads_dir` in `api/app.py` and asserts each is inside `disk_full_refused` (expect nine; the startup creation
of the data directories in `lifespan`/`create_app` is not inside a request route: if the AST finds such calls, list exactly which and why they are excluded).

### F8 (medium, H2 finding 1): the shutdown watchdog depends on its stderr write (`__main__.py::watch_shutdown`)

If stderr is a file on a full disk, `sys.stderr.write` or `flush` raises before `exit_function` runs and the process hangs. Wrap the two diagnostic lines
in `try: ... except OSError: pass` and put the `exit_function(FORCED_EXIT_CODE)` call in a `finally` (or after the try), so the exit always runs; a
non-OSError from stderr must also still end in the exit (use `except Exception` for the diagnostic only). Tests in a new file (do not edit
`tests/test_serve_shutdown.py` beyond what is needed): a `sys.stderr` stand-in whose `write` raises `OSError(28)`, one whose `flush` raises it, and one
whose `write` raises `ValueError` (closed stream); in all three the recording exit function is called once with `FORCED_EXIT_CODE`.

## Not in scope, to record in the decision as "not fixed" with the reason

- H7 finding 2 (an old `failed` asset record whose torn file was repaired by a new upload stays unusable; reextract says `unchanged`): needs a new
  evidence-preserving re-extraction path for failed or partial asset rows, i.e. a design decision about stored evidence, and it is the limit D165 wrote down.
  Not fixed.
- H3 finding 4 (`apps/web/src/api.ts` `exportError` does not translate coded errors in Turkish): low, web-only, needs the web build and Playwright; not fixed.
- H4 finding 5 (D163 says titles and text were not read by `upgrade_check`, but the view JSON is read in memory): the new decision states the accurate
  wording (no title or text is printed or stored; the views are read in memory); no code change.
- H2 finding 2 belongs to RR-B.
Do not fix these in this batch even if easy; the report lists them as not fixed.

## Checks to run (all inside the worktree)

1. The new tests, each shown failing on the old code first.
2. `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest -q` (full; the accepted failure
   `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit` aside; a test that fails only under parallel load: rerun alone and say so).
3. `... -m pytest -m process -n 0 -q` (startup and backup code changed).
4. `.venv/bin/python scripts/p9/upgrade_check.py --self-test` (synthetic only; it must still print `self-test: ok`).
5. `git diff --check`.
Do not start `serve` against a data directory you did not just create under `tmp_path`. For servers you start by hand use ports 8980 to 8990. The existing
process-test harness (`tests/process/p9_harness.py`) and `free_port()` in `tests/test_p9_restore_matrix.py` ask the OS for a free loopback port and
start synthetic servers on it: that is allowed for those existing tests (it is how they run); do not change it, and start nothing else on other ports.

## Report

Per finding: what changed, the test, whether it failed on the old code, anything you could not fix. Name every file you touched. Do not write the
decision or the plan lines; the orchestrator does.
