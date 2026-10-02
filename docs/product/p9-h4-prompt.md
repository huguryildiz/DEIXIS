<!-- PLAN-REVIEW-ROUNDS: r1 (Opus 5.5 high): düzeltmeyle hazır, 3 high + 5 medium + 5 low, all folded in; r2 (Opus 5.5 high): düzeltmeyle hazır, 1 high + 4 medium + 9 low, all folded in, no third round needed -->
<!-- reviewer: Opus 5.5 high (Sol quota out), Sol re-review pending (gpt-6.1-sol answered with a usage-limit error until 3 October 2026 20:39 when tried once on 2 October 2026) -->

# Task: P9 batch H4, backup, restore and upgrade matrix (B01, B01n, B03, F03 restore part, F06 unknown-version part, F10; B02 tooling)

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-h4`, detached at `7c197b7` (main with D162). Plan: `docs/product/p9-hardening-plan.md` section 4 (closing rule 2,
rows F03, F06, F10, B01, B01n, B02, B03), the H4 section of section 5 and owner question rows S4 and S6 of section 9. Also read `AGENTS.md`, `CLAUDE.md`,
D34, D161, D162 in `docs/decisions.md`, `docs/product/p9-h2-prompt.md` (style model) and the code and tests named below. Venv: `.venv` exists in this
worktree (arm64, `uv sync --offline` done). Run tests with `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest ...`.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted. No real-model call, no
provider call, no network. Do not touch `../DEIXIS*` worktrees, `TODO.md`, `.vscode/`, `scripts/local_index.py`, `docs/product/sw-status.md`, the live
service on port 8765, ports 8858 to 8864, or any live data directory (`~/Library/Application Support/DEIXIS` or whatever `DEIXIS_DATA_DIR` names outside a
temp dir). **Never run anything of this batch against a live data directory**, including the B02 script below (its self-test runs on a synthetic folder
only). No method, contract or migration change (`skill_package_hash` unchanged). Do not invent; report what you could not measure.

## Why

The restore evidence today is `tests/test_backup.py` (nine tests, each over a hand-picked list of tables; D34 measured 30 tables on a live library that has since grown to 62 migrations) and H2's kill
tests (F03 kill part: counts only). H4 compares **every** table and every file after a restore, tries the negative cases, runs backup while a writer
writes, kills a restore half way, and closes the one schema hole the plan found: `db.migrate` applies what is missing but never notices a library written
by a **newer** code version, and `db.connect` writes (`PRAGMA journal_mode = WAL`) before anything is checked. Where a mandatory row finds a defect the
batch fixes it (plan section 4, rule 2).

## What is and is not in code (checked on 7c197b7)

- `storage/backup.py`: `create_backup` takes an SQLite backup-API snapshot, switches the snapshot to `journal_mode = DELETE`, checks integrity, copies the
  referenced files (`papers`, `provider-payloads`) with `shutil.copyfile`, hashes them, publishes `manifest.json` last (via `.partial` and `replace`).
  `restore_backup` refuses a folder without a manifest, a wrong format, an existing `library.sqlite`/`-wal`/`-shm`, unexpected manifest paths, a missing or
  changed file (hash), and a different file already at a target path; then it copies the files **straight to their final names** with `shutil.copyfile`,
  copies the database to `library.sqlite.restoring`, integrity-checks it and `os.replace`s it. **Open item from H2 (D162 Limits):** a SIGKILL during the
  copy of a file leaves a half file under its final, hash-named name; the next `restore` then refuses with "a different file already exists at ...".
  Read the code and confirm before fixing; the test below must fail on the old code.
- `storage/db.py`: `connect()` opens, sets `foreign_keys`, `journal_mode = WAL` (a write on a clean library: it creates `-wal`/`-shm`), `busy_timeout`.
  `migrate()` applies every packaged migration whose version is not in `schema_migrations`; it never looks at versions that are in the table but **not**
  packaged. Callers: `api/app.py` lifespan (line ~556), `__main__.reextract` (line ~113). `serve()` creates the app, so a refusal raised in the lifespan
  would surface as an uvicorn traceback. The packaged versions are 0001 to 0062 with no gap (`storage/migrations/`).
- Probed on this machine: a plain `sqlite3.connect("file:l.sqlite?mode=ro", uri=True)` on a clean WAL-mode database **creates `-shm` and `-wal`** (it is
  not side-effect free); `immutable=1` reads the main file only and creates nothing but ignores a `-wal`.
- `tests/process/` (H2): `p9_harness.py` (processes, allowlisted environment, PID identity record, read-only SQLite helpers `ro`, `integrity_check`,
  `foreign_key_check`, `count`, `digest`, `wait_for`), `p9_driver.py` (production launcher with a scripted model; controls by `P9_*` environment),
  `p9_backup_driver.py` (backup CLI with a hold point), `test_p9_backup_kill.py` (F03 kill part), `make_library` there is the example of a small library
  built through a real server. Process tests carry `@pytest.mark.process`, are deselected by default and run with `-m process -n 0`.
- `scripts/p9/` holds H0 and H1 measurement scripts (standard library or the repo venv).
- README line "Back up the library with the `backup` command below before you update the checkout" already exists (H1). S6's "backup before updating" step
  is therefore in place; no code change for it.

## Decisions taken where the plan is open (owner S6 and S4; the plan's own defaults)

1. S6, schema guard: **yes**. A library whose `schema_migrations` holds any version that is not in the packaged set is refused, by a **read-only
   precheck before `db.connect` writes anything**. The test is set difference (every unknown id), not "highest version".
2. S6, automatic backup before a migration: **no** (plan default). Only the README step, which exists. No new startup message beyond the refusal itself.
3. S4 / B02: tooling only. The implementer builds `scripts/p9/upgrade_check.py` and tests it on a synthetic library; it is **not** run on real data by this
   task. The owner consented to a B02 run in chat; the orchestrator runs it after review. You never run it.
4. The manifest gets no new field (the plan's "gözlenen kod sürümü" is optional); not done, say so in the report.

## What to build

### 1. Production changes (minimal; everything else found is reported, not fixed)

1. `storage/db.py`:
   - `class UnknownSchemaError(RuntimeError)`; `packaged_versions() -> set[int]` from `MIGRATIONS_DIR` (same parsing as `migrate`).
   - `check_schema_known(path: Path) -> None`: returns at once when the file does not exist or is empty. Otherwise it reads with **no SQLite contact with the live files that could write**:
     (i) when no non-empty `<path>-wal` exists: `sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)` (build the URI with `Path.as_uri()` so a
     `#`, `?` or a space in the path is escaped; an unquoted `file:<path>` was probed to cut at `#` and to create a stray file); (ii) when a non-empty `-wal` exists
     (a crashed or still-running writer; the committed rows, possibly the unknown id, may live only in it) copy `library.sqlite` and `library.sqlite-wal` with plain
     reads into a `tempfile.TemporaryDirectory` (same base names, no `-shm`) and read `schema_migrations` from the **copy**. Probed: `mode=ro` on such a library
     leaves `library.sqlite` and `-wal` identical but **changes `-shm`**, and `immutable=1` on it misses an id that exists only in the `-wal`; hence the copy. If the copy cannot be read (`sqlite3.DatabaseError`: a checkpoint between the two reads tore it) retry the copy up to 3 times; after the third failure raise
     `SchemaCheckUnreadable(RuntimeError)` (new, in `db.py`) with one sentence (the library could not be read to check its version, try again with DEIXIS stopped). Never
     raised for the `immutable` path, where a `DatabaseError` propagates as before (corrupt files are H3's). The copy is
     removed afterwards. Short timeout, connection closed before returning. If the database has no `schema_migrations` table it returns (nothing to compare).
     Unknown ids = `applied - packaged_versions()`; if any, raise `UnknownSchemaError` with one sentence and the reason: it names how many unknown
     migration ids and the first few (sorted), says this library was written by a newer DEIXIS, tells the person to update DEIXIS or open it with the version that
     made it, and says nothing was changed. A database that SQLite cannot read (`sqlite3.DatabaseError`) propagates as before (corrupt files are H3/F06's other half, not changed here).
   - `connect(path)` calls `check_schema_known(path)` **first**, before `mkdir`, before `sqlite3.connect`, before any pragma.
2. `__main__.py`: in `serve()`, after the data-directory check and before `create_app`, `check_schema_known(settings.db_path)`; on `UnknownSchemaError` or `SchemaCheckUnreadable` print
   the message to stderr and `return 2` (same style as the other refusals; no traceback, the port is never bound). In `reextract()` the same, `return 2`.
   Nothing else changes (`backup` must still work on such a library: reading a newer library to rescue it is allowed; do not add the check there).
3. `storage/backup.py::restore_backup`: place every file with **copy to a unique temporary name in the target folder, then `os.replace`**:
   `tempfile.mkstemp(dir=folder, prefix=".restoring-", suffix=".part")` (descriptor closed at once), `shutil.copyfile(src, tmp)` (keep calling `shutil.copyfile`, the
   process tests hook it), verify the hash of the temporary file against the manifest entry (BackupError and removal of the temporary file on mismatch), then
   `os.replace(tmp, dest)`; remove the temporary file on any exception (`except BaseException`, so `KeyboardInterrupt` is covered). **Before any write**, a pre-pass over all entries checks every target path: exists with a different hash raises
   `BackupError` (the whole restore is refused with the target tree untouched; today the refusal comes in the middle of the loop after earlier files and the
   `papers/` folder were already written, which plan B01n forbids: this is a mandatory-row defect to fix). Exists with the same hash: kept, as today. After the pre-pass and
   before the first copy, delete leftover `.restoring-*.part` files (this code's own prefix only; never `tmp*.part`, which are downloads) in the two target folders if they exist, so a re-run after a kill starts clean. The database staging (`library.sqlite.restoring`, then `os.replace`) stays. A restore killed half way (SIGKILL) leaves
   `.part` files and maybe some finished files, never a half file under a final name, and running `restore` again succeeds (finished files are verified by hash and kept, leftover `.part` files are deleted). Also wrap the manifest reading so a manifest that is a JSON list, lacks `files`, or has an entry without `path` or `sha256` raises `BackupError` instead of `KeyError`/`AttributeError`/`TypeError` (the CLI would print a traceback).
   Do not change `create_backup`.

### 2. Tooling

`scripts/p9/upgrade_check.py` (repo venv, standard library plus `deixis`). Subcommands; every refusal below happens **before any read or write of any path** and before any SQLite open:
- `copy-live LIVE_DIR WORK_DIR`: an owner-approved read-only copy. It must never write, lock, migrate or open with SQLite anything in `LIVE_DIR` that could write
  (a read-only SQLite open of a WAL library was probed to change `-shm` or to create `-shm`/`-wal`). Refusals: `LIVE_DIR` (resolved) equals the default data dir
  (`config`'s default) or `os.environ["DEIXIS_DATA_DIR"]`, unless `--i-have-owner-consent` is given; `WORK_DIR` (resolved) equals, contains or is inside `LIVE_DIR`
  (never allowed, flag or not); `WORK_DIR` exists and is not empty. It lists `LIVE_DIR` (names only). Two paths: (i) no non-empty `library.sqlite-wal`:
  `sqlite3.connect(<Path.as_uri()>?mode=ro&immutable=1, uri=True)` and `Connection.backup` into `WORK_DIR/live-copy/library.sqlite`; (ii) a non-empty `-wal`
  (the live service is probably running): plain byte reads of `library.sqlite` and then `library.sqlite-wal` into `WORK_DIR/live-copy` (no `-shm`). In both paths open the **copy**, run
  `PRAGMA integrity_check` on it and retry the copy up to 3 times if it is not `ok` (a checkpoint between the byte reads can tear it, and a writer may be active in (i)
  when the `-wal` is empty); after 3 failures stop and say "not measured". On success set the copy's `journal_mode = DELETE`. Copy `papers/` and `provider-payloads/` files with
  plain reads (read bytes, write under `WORK_DIR/live-copy`), only the names the copy's `_referenced_files` lists (import it from `deixis.storage.backup`), skipping a missing one and
  counting it. Never copy `codex-home`, `codex-workspace`, keys, `.env` or anything else. Write `WORK_DIR/.p9-upgrade-copy` holding the resolved `LIVE_DIR`. Print only counts.
  Why a byte copy and not `deixis backup` on the live folder: `create_backup` opens the live database with a normal connection, whose close checkpoints and may remove the
  `-wal`, i.e. writes to live files; the plan says the live dir is never touched.
- `restore-copy WORK_DIR`: refuses without the marker file; runs the product's own `create_backup(Settings(data_dir=WORK_DIR/live-copy), WORK_DIR/backup)` and
  `restore_backup(<that folder>, Settings(data_dir=WORK_DIR/restored))`, so real backup and restore code are exercised on the real library's shape (plan B02); prints counts (files, researches).
- `open-copy WORK_DIR`: refuses, always and even with the consent flag, unless `WORK_DIR/.p9-upgrade-copy` exists and `WORK_DIR/restored` exists; refuses the default data dir,
  `DEIXIS_DATA_DIR`, the marker's `LIVE_DIR`, or anything equal to or inside it. Then, on `WORK_DIR/restored` only: read its applied schema versions (compact range/list), the packaged versions it lacks
  (pending migrations), the unknown ones, and plain-SQL counts (researches, `source_versions`, passages) read with the `immutable` URI; open it
  with `create_app(Settings(data_dir=WORK_DIR/restored, port=<a free port>), adapters={}, start_worker=False, http_client=<an httpx.AsyncClient on a MockTransport that raises for every request>,
  xml_fetcher=<a stub that raises>)` inside `fastapi.testclient.TestClient` (read how `tests/test_api_flow.py::app_for` builds it); after opening, run the **same SQL counts again** and fail if
  any differs (opening and migrating lost nothing); also print the counts the API views give (research list, sources, passages; say which endpoints) as separate information, not as an equality
  (views leave out trashed researches and removed memberships by design: `workflow/views.py` filters). Print only counts, applied versions after opening and the number of migrations applied by
  the open. No titles, no text, no ids. Exit non-zero with the message on a refused schema.
- Import-time side effects: none. The null keyring backend (`keyring.set_keyring`) and the removal of `DEIXIS_CODEX_HOME` and model keys from `os.environ` happen inside `main()`.
- `--self-test`: builds a small synthetic library through the in-process app with the test fake adapter (copy the approach of `tests/test_backup.py::build_library`; the script may
  import from `tests/` by adding the repo root and `tests` to `sys.path`) **that includes a trashed research, a removed membership and a source shared by two researches**, makes
  a "live" folder in a temp dir with a held-open WAL connection (so `-wal` and `-shm` exist) and runs `copy-live`, `restore-copy`, `open-copy` against it with the default data dir
  monkeypatched to another temp path; it does **not** pass the consent flag. Asserts: SQL counts before and after opening equal and equal to the library's, the live folder's file
  names, sizes and sha256 (including `-wal` and `-shm`) are identical before and after, and no file other than the allowed ones was copied. Second case with a clean (no `-wal`) live
  folder that asserts nothing was created in it.

### 3. Tests

All SYNTHETIC records. Shared helper module `tests/p9_restore_compare.py` (importable by both kinds of test; the tests directory is on `sys.path`):
`library_state(data_dir)` returning, for **every** table in `sqlite_master` (type `table`, name not starting `sqlite_`; enumerated, never a hard-coded list) its row
count and a canonical sha256 over all columns of all rows (rows sorted by `repr`, blobs as hex, JSON with sorted keys), plus `{relative path: sha256}` for every
file under `papers/` and `provider-payloads/`; `compare_states(a, b, allow=())` returning a list of differences (empty when equal) and naming table or file. A database
without a `-wal` is opened with `Path.as_uri() + "?mode=ro&immutable=1"` (plain `mode=ro` creates `-wal`/`-shm` on a clean WAL-mode file); one with a `-wal` (a library whose app is still open) is read through `sqlite3.connect(path).backup(<in-memory connection>)`.
Files whose name starts `.restoring-` or ends `.part` are listed separately, never silently skipped.

**`tests/test_p9_restore_matrix.py` (default suite, in-process):**
- B01 (library builder): build ONE rich library through the in-process app with `FakeAdapter`, reusing the existing builders (read `tests/test_backup.py`,
  `tests/test_trash_backup.py`, `tests/test_api_flow.py`, the report fixtures `tests/test_report_assembly.py::report_with_sections`, `tests/test_report_claim_links.py`,
  `tests/test_report_edit_check.py`, candidate/sw-queue and evidence-table tests) to reach as many tables as practical: A to G style flow (attached and academic
  discovery, selections, upload, answer, answer review), an evidence table, trash and corpus removal, the sw/candidate queue, a report with claim links and edit
  checks, lineage and human removals. If composing them in one data directory is not practical, build the largest library you can and say what you could not add.
  The test prints and asserts a coverage line: `tables total N, with rows M`, and names every empty table with a one-clause reason in a dict in the test
  (an empty table without a named reason fails the test, so a future migration's new table is noticed). Report N and M.
  Then `create_backup` while the original app still runs, `restore_backup` into an empty dir, and **before any server opens**: `compare_states(backup folder, restored)` is
  empty (the backup folder is the reference; also assert source equals backup while the original app is idle, so a background write is not mistaken for a restore difference) (tables, counts, canonical digests, files), `PRAGMA integrity_check` ok, `foreign_key_check` empty, `schema_migrations` equal. Then open the restored library with
  `create_app(start_worker=False)` and compare the JSON of every research view (`GET /api/researches/<id>`) and the library list endpoint with those fetched from the
  original app before the backup; allow-list only fields the open itself writes (state each in the test, with why; expect none or `worker_owner`/recovery events);
  open a passage view and a citation anchor of the published answer and the report in the restored app and compare with the original.
- B01n: for each negative case assert `BackupError` (message contains a stable fragment) and that the target tree (names, sizes, sha256 of every file, including
  hidden ones) is **unchanged** by the failed call: target already holds a library; target holds a `-wal` or `-shm` only (ambiguous); a target file with the same name
  and a different hash (run it twice: the conflicting file is the first entry and a middle entry; the middle case fails on the old code because earlier files and `papers/` are already written when the loop reaches it); a backup file missing; a backup file changed (one byte) in `papers/`, in `provider-payloads/` and the database; a folder with no manifest;
  a manifest with a wrong format; a manifest path that escapes (`../x`, a nested path, an absolute path); a manifest without the database entry; a truncated manifest
  (invalid JSON); a manifest that is a JSON list, has no `files`, or has an entry without `path` or `sha256`. Plus: a target that already holds the same-hash file is accepted and kept.
- Restore atomicity (unit): monkeypatch `deixis.storage.backup.shutil.copyfile` so the nth call writes half the source to its destination and raises
  `KeyboardInterrupt`; assert no half file under any final name in the target and no `.restoring-*.part` left (the fixed code removes its temporary file on any exception), no `library.sqlite`, then restore again without the patch: succeeds and
  `compare_states` equals the source. Run it for the first file and for a middle file. Run it on the old code too and paste the failure.
- B03 (unit): a library whose `schema_migrations` additionally has (a) `0063`, (b) `9999`, (c) `0000` (below the range: a "highest version" check would miss
  it), (d) `0063` and `9999` together, (e) a library from an older code (build it by applying packaged migrations 0001 to 0061 only: point `db.MIGRATIONS_DIR` at a temp folder holding copies of those files, run `migrate`, restore the setting; deleting the 0062 row from a full library and re-running `migrate` fails because 0062 adds an existing column): (a) to (d) raise `UnknownSchemaError` from `db.connect` and from
  `check_schema_known` with the ids in the message; (e) opens and `migrate` applies exactly 0062. For each refused case the
  `library.sqlite` size and sha256 are equal before and after, and the folder's file names are the same (no `-wal`/`-shm`/`-journal` created); and again with a
  non-empty `-wal` present, where the unknown id is **only in the `-wal`**: make it in a child Python process that opens the library, sets `PRAGMA wal_autocheckpoint = 0`,
  inserts the `schema_migrations` row (committed) and ends with `os._exit(0)` (no checkpoint, no close); the test first proves the id is absent from the main file
  (an `immutable=1` read of `library.sqlite` alone sees only packaged ids), so an implementation that always reads `immutable` fails this case. In that case `library.sqlite`, `library.sqlite-wal` **and
  `library.sqlite-shm`** (if it existed) sha256 and size are equal before and after (the plan row requires all three). Also a path containing `#` and a space. A corrupt file still raises `sqlite3.DatabaseError`, not
  `UnknownSchemaError`. A unit test makes the WAL-copy function produce a torn copy once (monkeypatch) and shows the retry succeeds, and three times and shows `SchemaCheckUnreadable`.
  Measure and report the precheck's wall time on a synthetic library of about 200 MB, with and without a non-empty `-wal`. `backup.create_backup` on such a library still succeeds and the backup restores (rescue path); do every hash check above **before** this step, because the backup's last SQLite connection checkpoints and removes the `-wal`.
- Connections after a restore (plan section H4 item 5): credentials are not in the backup. Find how the app reports a model connection that has no sign-in
  (`GET /api/connections`, `models/codex*.py`, `apps/web/src` strings through `i18n.ts`/`labels.ts` for the "not ready" text) and write a test or a short, honest finding:
  does the restored library show "not ready" with a reason that tells the person to connect again, instead of an error or a silent working-looking state? Use an
  adapter or a monkeypatch that needs no `codex` binary; if a real adapter cannot be exercised offline, test the reason text and the UI string by reading, and say which.
  Do not change UI or adapters in this batch; a gap is reported.
- Schema guard in the launcher (fast): `__main__.serve` on a library with an unknown id returns 2 and prints the message, without calling `uvicorn.Server`
  (monkeypatch it to fail the test if called); `reextract` returns 2. A normal library still reaches the server call.
- `tests/test_p9_upgrade_check.py`: run the script's `--self-test` logic through its functions (not a subprocess if it is slow), plus every refusal above (`copy-live` on the default dir and on `DEIXIS_DATA_DIR` without the flag, `WORK_DIR` equal/containing/inside `LIVE_DIR`, `WORK_DIR` not empty;
  `open-copy` without the marker, on the default dir, on `DEIXIS_DATA_DIR`, on the marker's live dir, each also with the consent flag; the flag itself in its own test). **The test must monkeypatch the default data dir to a temp path;
  it must never pass or compute the real `~/Library/Application Support/DEIXIS`.**

**`tests/process/test_p9_restore_process.py` (marker `process`; `-m process -n 0`):**
- B03 with the real launcher: a library made through a real server (one research, one upload; stop it with SIGTERM so no `-wal` remains), then the test adds a
  `schema_migrations` row `9999` offline. Hash `library.sqlite`, list the folder. Start the **production** `python -m deixis serve --no-browser --port <free>` through
  `harness.popen` (allowlisted environment with `DEIXIS_DATA_DIR`; it must not use the fixture driver, so it writes no call log and the `no_network` check does not apply
  to this test; say so in the docstring): exit code 2 within 20 s, the message on its output, no connection to the port was ever accepted (a short bind in
  `port_available` is expected), `library.sqlite` sha256 and the folder listing identical to before. A second case: the unknown id exists only in a non-empty `-wal` (the
  child-process construction in the B03 unit test, with the server stopped); same checks for `library.sqlite`, `-wal` and `-shm`. On the old code the launcher starts and serves (or a hash changes): the test must fail
  there; paste the failure.
- F10: a real server (scripted model) with one research whose discovery run is **held running** (`P9_HOLD_TASK` on a discovery model call; wait with `wait_held`; check through the API that the run is `running` before each of the three backups) and a writer thread that keeps creating researches and uploading small
  PDFs (distinct bytes) for the whole test; while it writes the test runs the real `python -m deixis backup <dest>` three times. For each backup folder: the
  database inside passes `integrity_check`, `foreign_key_check` is empty, every manifest file exists with its hash; `restore` into an empty dir exits 0; and
  `compare_states(<backup folder's library.sqlite and files>, restored)` is empty (the backup, not the moving live library, is the reference); counts of
  `researches` in the three backups are non-decreasing and at least one is larger than the first (the writer really ran during the series; assert and report the numbers).
  Stop the server with SIGTERM at the end; the held call makes the shutdown forced (stderr line, exit code `FORCED_EXIT_CODE`, H2): expect that, or release nothing and say so; no `network` line in its call log. The plan row also names "B01 comparisons": this test covers tables and files; the view-JSON part is B01's in-process test, say so in the docstring.
- F03 restore part: reuse `test_p9_backup_kill.py::make_library` shape but with the library of the F10 style (some rows). Kill the real backup after the manifest
  (`after_manifest`), restore with the CLI, and now assert the **B01 comparison** (`compare_states` of the backup folder against the restored directory empty), not
  only counts. The view-JSON part of B01 is the in-process test's; say so in this test's docstring.
- Restore killed half way: add a restore driver (a new small script `tests/process/p9_restore_driver.py` in the style of `p9_backup_driver.py`, or a mode in it) that runs
  `deixis.__main__.main(["restore", folder])` with `DEIXIS_DATA_DIR` set, after wrapping `backup.shutil.copyfile`: the nth call writes the first half of the
  source to the destination it was given, writes a `held` file and sleeps 3600 s (the same trick as the F02 torn-write hook: it shows a truncated final-name file on the
  old code and a truncated `.part` on the fixed code). SIGKILL the driver. Assert: no file under a final name in `papers/` or `provider-payloads/` whose sha256 differs
  from its manifest hash, no `library.sqlite` (a `.restoring-*.part` may remain after a SIGKILL); run the real `restore` again: exit 0, no `.part` left, `compare_states` empty. Also kill it at the other points that exist
  (before the database replace: hook `os.replace` for `library.sqlite`; the database staging file `library.sqlite.restoring` may remain; assert a second restore works).
  The file-copy hook fails on the old code (paste); the database-replace kill is clean on the old code too (the staging file already existed), so it is a regression guard, not a failing-first test; say that.
- Every process test asserts its server logs have no `network` line, kills only PIDs it started, uses its own temp data dir and a free port (`p9_harness` rules).

### 4. Checks to run (in this worktree) and report

`tests/test_backup.py tests/test_trash_backup.py` and the new default-suite files; the process tests with `-m process -n 0` (whole `tests/process/` once, to show H2's 21
still pass); the full default `pytest` once at the end (baseline 8,215 passed, 2 skipped at 7c197b7; one known failure is accepted:
`tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`; a test that fails only under parallel load: rerun it alone and say so);
`scripts/p9/upgrade_check.py --self-test`. No web build, lint or Playwright (no `apps/web` change). Before each production fix run its test on the old code and keep the failure text.

## Files

Allowed: `backend/deixis/storage/db.py`, `backend/deixis/storage/backup.py`, `backend/deixis/__main__.py`, `scripts/p9/upgrade_check.py`, `tests/test_p9_restore_matrix.py`,
`tests/test_p9_upgrade_check.py`, `tests/p9_restore_compare.py`, `tests/process/*` (new files; additive edits to `p9_harness.py` only; do not change an existing H2 test's assertions),
`tests/conftest.py` only if needed (it should not be). Not allowed: `docs/decisions.md`, `docs/product/*` (the main session writes the decision and the status),
`README.md`, migrations, `methods/`, `contracts/`, `pyproject.toml`, `apps/web`, `workflow/`, `api/` (a defect found there is reported), existing H2 tests' assertions.

## Report back (final message of your run; the orchestrator reads it)

Files changed; for each production fix the old-code failure text and the new result; B01 coverage line (tables total, with rows, empty and why); the allow-list used in the
view comparison; B01n case list; the number of file hashes and tables compared (B01 and F10); B03 results including what was measured for `-shm`; F10 numbers (rows in each backup, writer count); restore kill results; the connections
finding; test counts; everything you could not find or measure; every judgment call.
