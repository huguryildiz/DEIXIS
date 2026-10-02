<!-- PLAN-REVIEW-ROUNDS: r1 (Opus 5.5 high): hazır değil, 2 high + 8 medium + 9 low, all folded in; r2 (Opus 5.5 high): düzeltmeyle hazır, 1 high + 2 medium + 4 low, all folded in, no third round needed; implementation by Sonnet (claude -p, effort high); code review r1 (Opus 5.5 high): düzeltmeyle hazır, 0 high, 1 medium + 8 low folded in; r2: hazır, 0 high, 9 low (7 folded in); reviewer: Opus 5.5 high (Sol quota out), Sol re-review pending (gpt-6.1-sol answered with a usage-limit error until 3 October 2026 20:39 when tried once on 2 October 2026) -->

# Task: P9 batch H2, process-level crash and shutdown (F01, F02, F03 kill part, F04, I06)

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-h2`, detached at `4050a94` (main with D160). Plan: `docs/product/p9-hardening-plan.md` §2 (supported
environment), §4 (closing rule 2, rows F01 to F04 and I06) and the H2 section of §5. Also read `AGENTS.md`, `CLAUDE.md`, D138, D139 and D159 in
`docs/decisions.md` and `docs/product/p9-h0c-prompt.md` (style model). Venv: `.venv` exists in this worktree (arm64, `uv sync --offline` done). Run
tests with `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest ...` (or `uv run`).

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted. No real-model call, no
provider call, no network. Do not touch `../DEIXIS*` worktrees, `TODO.md`, `.vscode/`, `scripts/local_index.py`, `docs/product/sw-status.md`, the live service
on port 8765, ports 8858 to 8864, or the live data directory. No method, contract or migration change (`skill_package_hash` unchanged). Do not invent;
report what you could not measure.

## Why

Today the only process-level kill evidence is the Playwright F case: it stops the backend with SIGTERM (`server.stop()`), on synthetic rows. It shows
nothing about SIGKILL. H2 starts real processes, kills them, and checks what the next start finds. Where it finds a defect in a mandatory row the batch
fixes it (plan §4 rule 2).

## Hard rules for the process tests

- Every process the tests start is started by the test, on its own port (asked from the OS with a bind to port 0; the harness refuses 8765 and 8858 to
  8864) and its own data directory under pytest's temp dir. A test kills only PIDs it started or recorded as their descendants. Never `pkill`, never a
  pattern kill. **The kill under test is `os.kill(pid, SIGKILL)` on the one parent PID** (the server, a backup driver, a child-parent helper), never
  `killpg`: no production child starts its own session, so a group kill would end the children with the parent and the child tests would pass
  without showing that they end by themselves, and a real crash kills one PID only. Servers may be started with `start_new_session=True` (isolation from
  the terminal's Ctrl-C), but the group is used only by the teardown. Before the kill, every descendant is recorded as `(pid, lstart, command, pgid)` (by
  `ps -A -o pid=,ppid=,pgid=,lstart=,command=` walking parent links); a teardown fixture kills what is still alive of that record, matching `(pid, lstart,
  command)` again, and may `killpg` a recorded pgid only for that cleanup.
- Child environment is an allowlist, named one by one: `PATH` (the venv's bin folder, `/usr/bin`, `/bin`; no model CLI on it), `HOME` (a temp dir),
  `PYTHONPATH`, `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring`, and the `P9_*` controls below. Working directory is a temp dir, so no `.env` is read.
  Real `codex` is never started; the model is a scripted stand-in (`tests/acceptance/fixture_server.py::ScriptedCodex`, SYNTHETIC records).
- Tests carry `@pytest.mark.process` and are left out of the default run. Register the marker in `tests/conftest.py::pytest_configure` (one line) and add a
  `pytest_collection_modifyitems` there that deselects items marked `process` unless the `-m` expression names `process`. Run them with
  `-m process -n 0` (serial: the thresholds are wall-clock). Do not change `pyproject.toml`.
- PID safety: a PID whose start time or command no longer matches its record is never signalled. A child the test started itself is checked with `Popen.poll()`, never `os.kill(pid, 0)`
  (a dead, unwaited child looks alive to it); a descendant that is not the test's own child (an orphan) counts as gone when `ps -p` finds nothing or
  its state starts with `Z`.
- The harness fails closed (pytest.fail with a clear message) if `<repo>/.env` exists: `config.load_settings` reads it, and the backup and restore children call
  it. Those two children also get `DEIXIS_DATA_DIR` in their environment.
- No network: the driver gives `create_app` a stub `xml_fetcher` (the default `acquisition.fetch_xml` opens its own client and bypasses the mock
  transport), and installs a guard that refuses and logs (`network` line) any `fetch.fetch_file` call or `socket.socket.connect` to a non-loopback address.
  Every server test asserts the log has no `network` line.
- Child stdout and stderr go to a file in the temp dir, never an unread pipe (uvicorn logs at info level).
- Port-free check: `deixis.__main__.port_available("127.0.0.1", port)` (it uses `SO_REUSEADDR` like uvicorn) and a refused connect.
- `pytest-timeout` is not installed: every wait in a test has its own deadline and an assertion naming what did not happen.
- Python native arm64.

## What is and is not in code (checked on 4050a94 and by probes in this worktree)

- `Worker` (`workflow/worker.py`): OS `flock` on `worker.lock`; `recover()` marks `running` steps and `started` model sessions `outcome_unknown` and
  running runs `paused/backend_restarted`. `api/app.py::lifespan` starts `take_over_when_released()` for a second process: it polls `acquire()` every
  1 s, then recovers. `/api/health` returns `worker: owner|not_owner` and `recovered`.
- `__main__.serve()` runs `uvicorn.Server` with `timeout_graceful_shutdown=3`.
- `tests/acceptance/fixture_server.py` builds the app with injected `adapters`, `http_client`, `fetcher`; it has no call counter and no way to hold a model
  call open. Nothing in `tests/` starts a real process and sends SIGKILL.
- Working throwaway probes written by the main session (reusable as a starting point, not committed): `/tmp/h2-probe/driver.py` (a server process that
  logs every model call to a JSONL file and holds one task type open), `probe1.py` (F01 shape), `probe2.py` and `probe3.py` (F04 shapes),
  `orphan_parent.py` and `orphan_probe.py` (orphan child shape). They run against this worktree's `.venv`.

Measured by those probes on this machine (macOS arm64, Python 3.12, uvicorn 0.53; single runs, not distributions):

1. **F01 shape works today.** Attached-and-academic research, discovery completes (3 `vocabulary_labels`, 3 `criterion_proposal`, 2
   `abstract_screening` model calls), include the sources, start an `answer` run whose `grounded_answer` call is held open, SIGKILL the process. The next
   process reports `recovered = {runs: 1, steps: 1, model_sessions: 1}`; the run is `paused/backend_restarted`, the step `outcome_unknown`; after
   `POST /api/runs/<id>/resume` the run completes with one answer, the call log shows `grounded_answer` exactly twice in total and no earlier task again,
   and the run's `usage` is `{downloads: 2, model_calls: 2}`.
2. **F04 defects (two).** (a) SIGTERM to the launcher with an open event stream and an idle worker: exit in 3.2 s (uvicorn re-raises the signal, status
   `-15`), port free. The same with a model call in flight: still running after 30 s, had to be killed. Cause: the `lifespan` shutdown does
   `await worker.stop()` then `await task`; `stop()` only sets a flag read between runs, so shutdown waits for the model call (a Codex turn can run 300 s).
   (b) A worker thread blocked in `asyncio.to_thread(pdf.extract_pdf)` (patched to sleep 25 s; the first version of this probe set the variable after
   the server had started and showed nothing, the corrected one is `probe3.py`): SIGTERM exits in 3.2 s (the re-raised signal ends the interpreter), but
   **SIGINT (Ctrl-C) took 24.2 s and exited 0**, because after the signal is re-raised as `KeyboardInterrupt` the interpreter waits for the executor
   thread (`asyncio.run` closes the default executor with a 300 s join; the thread lives as long as its extraction child, up to 90 s). Ctrl-C is the
   normal way to stop `python -m deixis serve`.
3. **Orphan defect.** `pdf.extract_pdf` on a PDF whose content stream decodes to 60 MiB, parent SIGKILLed 3 s in: the extraction child was reparented to
   PID 1 and was still running 42 s later (resident size 120 to 600 MiB). The 90 s time limit and the 1 GiB limit (D138, D159) live in the parent
   (`pdf._run_watched`), so they die with it. `ocr.py`, `jats.py` and `arxiv_source.py` children have the same shape (their parents hold the clocks; all
   four call `pdf._watch_memory` in the child).
4. **Torn PDF file (found by plan review, to be shown by test).** `flow.py` (the fetch step, about line 2689), `acquisition.py::_attach_pdf` (line 470) and
   two Zotero routes in `api/app.py` write a downloaded PDF straight to `papers/<sha256>.pdf` with `path.write_bytes(data)` guarded by `if not
   path.exists()`. A SIGKILL during the write leaves a truncated file under its final, hash-named name; the resume sees `exists()`, extracts from the
   truncated file, and stores a `source_assets` row whose `sha256` is the hash of the full data, so the file no longer matches its row and
   `backup.create_backup` later refuses with "file does not match its recorded hash". Uploads are not affected (`store_upload` writes a `.partial` file and
   `os.replace`s it). Read the code to confirm this before relying on it; the F02 test must show it on the old code.

## What to build

### 1. Harness and drivers (tests only)

- `tests/process/p9_harness.py`: `ServerProc` (start the driver as a child, wait for `/api/health`, an `httpx.Client` with the CSRF header from
  `/api/session`, `kill9()`, `signal(sig)`, `wait(timeout)`, `alive()`), free-port helper with the refused ports, the child environment allowlist, the
  `.env` fail-closed check, the PID identity record, a teardown registry, a `calls()` reader of the JSONL call log, and read-only SQLite helpers (`mode=ro`
  URI): `integrity_check`, `foreign_key_check`, table row counts, a canonical digest of a table's rows for chosen columns. Name the modules uniquely
  (the tests directory is on `sys.path`).
- `tests/process/p9_driver.py` (script): the real launcher with injected stand-ins. It imports `fixture_server` (as the Playwright run does), sets
  `deixis.__main__.create_app` to a `functools.partial` that injects `adapters={"codex": RecordingCodex()}`, `http_client`, `fetcher`, and then calls
  `deixis.__main__.serve(settings, False, ())`, so the production `uvicorn.Config`, signal handling and shutdown are what is signalled. Settings as in
  `fixture_server.main`, non-queue mode, every switch explicit: `fulltext_fetch="off"`, `fulltext_adjudication="off"`, `arxiv_source="off"`,
  `search_query="code"`, `protocol_approval="as_proposed"`, `model_concurrency=1`. Args:
  `--data-dir`, `--port`. Controls by environment (all optional): `P9_CALLS` (path of the JSONL log); `P9_HOLD_TASK` and `P9_HOLD_NTH` (default 1: the
  model call of that task type that is held open after being logged, `asyncio.sleep(3600)`); `P9_HOLD_FETCH_NTH` (hold the nth `fetcher` call after
  logging it); `P9_HOLD_PAPER_WRITE_NTH` (see below); `P9_HOLD_EXTRACT_NTH` (hold the nth `pdf.extract_pdf` call in its thread after logging it);
  `P9_GATE_DIR` (see below). `RecordingCodex(fixture_server.ScriptedCodex)` appends one JSON line before each call (`task`, `run_id`, `pid`, `monotonic`)
  with flush and `os.fsync`; the `fetcher` wrapper, the mocked OpenAlex handler (`provider` lines: host and path) and the patched `extract_pdf` log the
  same way; a held call also writes a `held` line so the test knows the moment.
- Torn-write hook (F02): when `P9_HOLD_PAPER_WRITE_NTH` is set, the driver patches `pathlib.Path.write_bytes` for targets inside `<data>/papers/` ending
  `.pdf` or `.part`: the nth such write writes the first half of the bytes (`open`, `write`, `flush`, `fsync`), appends a `held` line, and sleeps 3600 s.
  It works the same on the old code (a truncated `<sha>.pdf`) and on the fixed code (a truncated `.part`), which is the point. The fix below must
  therefore write its temporary file with `Path.write_bytes`.
- Mid-transaction gate (F02): when `P9_GATE_DIR` is set the driver wraps `deixis.storage.db.migrate` so that, after the real migration, the connection
  gets a SQL function `p9_gate()` and a TEMP trigger `AFTER INSERT ON passages WHEN (SELECT COUNT(*) FROM passages WHERE asset_id = NEW.asset_id) = 2 BEGIN
  SELECT p9_gate(); END` (not before the migration: `passages` does not exist yet on an empty directory and a later migration rebuilds it). `p9_gate()`
  does nothing unless `<P9_GATE_DIR>/armed` exists; when it does, it writes `<P9_GATE_DIR>/reached` and sleeps 3600 s inside the open `BEGIN IMMEDIATE`
  write transaction of `Store.add_asset_with_pages` (the asset row and two passage rows inserted, not committed). The test arms it after the first
  upload, sees `reached`, and sends the SIGKILL itself.
- `tests/process/p9_backup_driver.py` (script): runs `deixis.__main__.main(["backup", dest])` with `DEIXIS_DATA_DIR` pointing at a prepared library, after
  patching one point selected by `P9_BACKUP_HOLD`: `during_files` (the first `shutil.copyfile` inside `deixis.storage.backup` blocks, after writing a
  `held` file), `before_manifest` (the `json.dumps` of the manifest blocks), `after_manifest` (the real `create_backup` returns, then the driver
  blocks before printing). Replace the names `backup.shutil` / `backup.json` with small wrappers; do not edit `backup.py`.
- `tests/process/p9_stand_in_codex.py` (script) and `tests/process/p9_child_parent.py` (script): the parent starts a production class and prints one JSON
  line with the child PID, then sleeps; the test SIGKILLs the parent. Subcommands: `codex` (`models.codex_rpc.CodexAppServer(argv=[python,
  p9_stand_in_codex.py, mode], cwd=tmp)`, then `await start()` and `await initialize("p9-test", "0")`; stand-in modes `idle` = answers `initialize`, then reads
  stdin lines until EOF and exits; `busy:S` = answers `initialize`, then sleeps S s without reading stdin, then reads until EOF), `embedding`
  (`documents.local_embedding.LocalEmbedder` built with `tests/builtin_helpers.fake_embedder` and `install_fake` on a temp data dir, after
  `builtin_helpers.fake_manifest` replaced `local_embedding.MODEL_FILES` in that process (otherwise the runner answers `files_do_not_match`), `FAKE_RUNNER=ok` or
  `slow:3`; start it, send one embed request in a task for the busy case, print the runner PID), `pdf` (calls `pdf._run_watched` directly on a PDF built with
  `scripts/p9/memory_probe.build_pdf` at 60 MiB decoded, with the argv and `PYTHONPATH` env of `extract_pdf` plus a `DEIXIS_CHILD_LIFETIME_SECONDS` entry
  and a 60 s parent clock; the child PID is found by parent PID with `ps`).

### 2. Tests (`tests/process/`, marker `process`)

- **F01, answer variant** (`test_p9_crash.py`): the shape of probe 1 with the driver (hold the `grounded_answer` call). Before the kill the log has the
  held call; after the kill and a fresh process on the same data dir: `/api/health` `recovered` is `{runs: 1, steps: 1, model_sessions: 1}`; run
  `paused/backend_restarted`; the `grounded_answer` step `outcome_unknown`; `integrity_check` ok. After resume: run completed, exactly one row in `answers`
  for the research, `grounded_answer` appears exactly twice in the log, the counts of every other task and the number of `fetch` lines are the same before
  the kill and after the resume (completed steps: increase 0), `model_sessions` has two rows for that step (first `outcome_unknown`, second `completed`)
  and the run's `usage.model_calls` is 2. State in the docstring that the second send is expected behavior (a separate session and a separate
  budget unit), not a defect.
- **F01, discovery variant (mandatory)**: hold the 2nd `abstract_screening` call (`P9_HOLD_TASK=abstract_screening`, `P9_HOLD_NTH=2`) during the discovery
  run, kill, restart, resume that run. Per-task call counts before the kill for every task but `abstract_screening` equal the counts after the resume
  (completed steps: increase 0); `abstract_screening` rises by exactly 1 beyond the held call (3 in total); the logged provider requests (`provider`
  lines) are identical in number before and after the resume (completed searches are not repeated); the run completes.
- **F02, download write**: attached-and-academic research as in F01; hold the 2nd paper write (`P9_HOLD_PAPER_WRITE_NTH=2`) during the `answer` run,
  SIGKILL. After restart, for every file `papers/<name>.pdf` the sha256 of its bytes equals `<name>` (name is hash); every `source_assets` row has its
  file with an equal sha256, or the row does not exist; the first asset's passages are digest-identical to before; `integrity_check` ok,
  `foreign_key_check` empty. Resume completes with one answer. Then `python -m deixis backup <dest>` (real CLI, `DEIXIS_DATA_DIR` of this library)
  succeeds. This test fails on the old code (truncated final file, hash mismatch at resume or at backup); paste that failure.
- **F02, file written, row not**: hold the right `pdf.extract_pdf` call (the attached upload's extraction is call 1, so `P9_HOLD_EXTRACT_NTH=2` is the first extraction of the `answer` run; say in the test which one is held and why) (the file is complete and hash-named, the
  row does not exist), SIGKILL, restart, resume: the file is reused (its size and hash are checked), the row appears, one answer, backup succeeds.
- **F02, passage write**: attached research, upload PDF A (two pages), digest A's `source_assets` and `passages` rows; arm the gate; upload PDF B (two
  pages, different text) from a thread; wait for `reached`; SIGKILL. After restart: no `source_assets` row and no `passages` row for B (rolled back), A's
  digest unchanged, `integrity_check` ok, `foreign_key_check` empty. Count `works` and `source_versions` before and after: the upload route commits
  `create_upload_source` in its own transaction before `add_asset_with_pages`, so one source row without an asset and not a member of any research may
  remain; assert it is not in the research's view or in the library list and not counted, report the delta, and in D162 say why this still meets F02's wording (no
  `source_assets` row without its file, a write cut inside a transaction is wholly absent; the leftover row has no asset, no passage and no membership) and
  that it is not a defect of this batch to fix. Report
  the `*.partial` and unreferenced `<sha>.pdf` left in `papers/`. Upload B again without the gate: 201, its passage count equals that of a fresh upload of
  the same file in a second data directory.
- **I06** (`test_p9_crash.py`): process 1 owns the data dir, process 2 starts on another port with the same data dir: `/api/health` `owner` and
  `not_owner`. Process 1 has a held `grounded_answer`. SIGKILL process 1. Process 2 becomes `owner` within 10 s (poll 0.2 s; record the time) and its
  `recovered` is `{runs: 1, steps: 1, model_sessions: 1}`; the research view through process 2 shows the run `paused/backend_restarted`. Resume through
  process 2 (its driver holds nothing) completes with one answer.
- **F03, kill part** (`test_p9_backup_kill.py`): a library made through a server process (one research, one upload; stop it with SIGTERM), then the backup
  driver killed at each of `during_files`, `before_manifest`, `after_manifest` (the test waits for the `held` file, then SIGKILLs). Before the manifest
  (the first two): the folder has no `manifest.json`; `python -m deixis restore <folder>` (real CLI, empty data dir) exits 1 with `not a complete DEIXIS
  backup` on stderr and leaves the data dir empty (no `library.sqlite`, no `.restoring`); a new backup into the same destination afterwards succeeds and
  restores. After the manifest: restore exits 0, the restored `library.sqlite` passes `integrity_check`, each manifest file exists with the listed sha256,
  and the research count equals the source's. The B01 comparisons (every table, canonical digests, view JSON) belong to H4 and are not claimed here.
- **F04** (`test_p9_shutdown.py`): signal the launcher with an event stream open (`/api/researches/<id>/events/stream` read in a thread). Cases, each
  with SIGTERM and with SIGINT: (1) idle worker; (2) a held model call; (3) a real slow extraction in flight: upload a PDF built with
  `scripts/p9/memory_probe.build_pdf` at 60 MiB decoded from a thread (its real extraction child runs for tens of seconds; no patch). Each: the wall time
  from the signal to exit is at most 10 s; exit status is 0 or `-signal` (graceful) or `deixis.__main__.FORCED_EXIT_CODE` (the watchdog below); the case
  is classified by the stderr line "did not finish shutting down" as well as by the status (a status of 1 alone is Python's generic failure), and the test
  asserts the expected path: (1) graceful, (2) forced, (3) forced for SIGINT and graceful for SIGTERM (the re-raised signal ends the interpreter);
  the signal goes to the server PID only (a terminal's Ctrl-C reaches the whole foreground group; say that in the docstring); port free; no process of the test's
  list left except the real extraction child of (3), whose own end is checked in the children test (it is bounded by the lifetime alarm). For (2) also
  check the next start reports `recovered` runs 1 and steps 1 and the run `paused/backend_restarted`.
- **Child process lifetime after SIGKILL** (`test_p9_children.py`): the kill is `os.kill` on the parent helper only (see the rules). `codex` stand-in modes
  `idle` and `busy:3`: the child is recorded before the kill; after it the parent is confirmed dead (`Popen.poll()`), and in `busy:3` the child is still
  alive at least 1 s after that (positive control: it did not die with the group or the parent); it is gone within 3 s (`idle`) and within 8 s (`busy:3`)
  of the kill (stdin EOF). `embedding` `FAKE_RUNNER=ok` and `slow:3` (same positive control in `slow:3`): the runner is gone within 3 s and 8 s, and the in-use lock
  (`flock(LOCK_EX|LOCK_NB)` on `tools/embedding-in-use.lock`) is free afterwards. `pdf`: with `DEIXIS_CHILD_LIFETIME_SECONDS=8` the orphan is observed alive
  at 5 s after it was first seen alive and gone by 8 + 5 s after it (this also fails on the old code, where the child outlives the parent's clock; it is
  not allowed to pass because the child crashed early). Without the variable the child's default lifetime is the module constant (assert the constant, do
  not wait for it).

### 3. Fixes (production, minimal; every other defect found outside this list is reported, not fixed)

1. `__main__.serve()`: a daemon watchdog thread, started before `server.run()`, waits until `server.should_exit` is true (uvicorn sets it on SIGINT and
   SIGTERM; poll 0.1 s), waits `SHUTDOWN_EXIT_SECONDS = 6.0` more, then writes one line to stderr ("DEIXIS did not finish shutting down in 6 s; exiting")
   and calls `os._exit(FORCED_EXIT_CODE)` with `FORCED_EXIT_CODE = 1` (module constants). A shutdown that completes sooner is untouched and the thread
   dies with the process. No change to `api/app.py`: nothing is cancelled and no task is interrupted, so the state at a forced exit is exactly the state
   after a SIGKILL, which F01 and I06 already show is recovered (`outcome_unknown`, `paused/backend_restarted`; the lock is released by the OS). The
   price, to be written in D162: a model call in flight when the person presses Ctrl-C is not waited for and is sent again on resume, as after a crash.
   Make the watchdog a small function that takes the server, the seconds, an exit function and a `threading.Event` that cancels it, so one fast default-suite
   test can drive it with a fake server and a recording exit function (`tests/test_serve_shutdown.py`: exit not called while `should_exit` is false, called once with the code after it
   turns true, not called when the cancel event is set first).
2. `documents/pdf.py::_watch_memory(limit)` (shared by the pdf, ocr, jats and arxiv source children): first arm a hard lifetime with `signal.alarm`
   (default action, no Python handler, so it ends the process even inside a C call that holds the interpreter lock; guarded by `hasattr(signal, "alarm")`).
   `CHILD_LIFETIME_SECONDS = 100` (above the longest parent clock, 90 s) unless the environment has `DEIXIS_CHILD_LIFETIME_SECONDS` (a positive integer, read by
   the child; the parents pass the environment dict they already build, so only a caller that adds the entry changes it). Add one fast test
   (`tests/test_child_lifetime.py`): a Python child that calls `_watch_memory(10**12)`, prints `armed` and then sleeps in a C call (`time.sleep(30)`) with the
   variable set to 1 ends with return code `-signal.SIGALRM`, at least 0.9 s after it was started and at most 6 s after `armed` was read; the constant is above `pdf.TIMEOUT_SECONDS`,
   `ocr.TIMEOUT_SECONDS`, `jats.RENDER_TIMEOUT_SECONDS` and `arxiv_source.CHILD_TIMEOUT_SECONDS`. Existing extraction, OCR, JATS and arXiv tests stay unchanged.
3. Atomic PDF file write: a small function (new module `documents/pdf_files.py`, `store_pdf_file(papers_dir, sha256, data) -> Path`): if
   `<sha>.pdf` exists and its size equals `len(data)` and its sha256 equals `sha256`, return it; otherwise create a unique temporary name in the same folder (`tempfile.mkstemp(dir=papers_dir, suffix=".part")`, descriptor closed at once, so two
   processes on one data directory never share a temporary file), write `data` to it with `Path.write_bytes`, and `os.replace` it to `<sha>.pdf` (a wrong
   existing file is replaced; the temporary file is removed on an exception). Use it at the four sites named in finding 4
   above (`flow.py` fetch step, `acquisition._attach_pdf`, the two Zotero routes in `api/app.py`) and nowhere else; change only the lines that write the
   file. Add a fast test (`tests/test_pdf_files.py`): fresh write, reuse of a correct file (the file is not rewritten: mtime kept), replacement of a
   truncated file, no `.part` left after success or after an exception.

A defect found in `codex_rpc.py` or `local_embedding_service.py` itself by the child tests gets a production fix in this batch; if the stand-ins show none,
write that. The `deaf` case (a child that never reads its stdin) is not tested: whether the real `codex app-server` exits on stdin EOF is a property of
that program, which this batch does not start (the production `embedding_runner.py` has the same `for line in sys.stdin` shape as the fake, by reading
only); it is a Limit in D162 and an input of H10.

## Files

Allowed: `tests/process/*` (new), `tests/conftest.py` (marker and deselect hook only), `tests/test_serve_shutdown.py`, `tests/test_child_lifetime.py`,
`tests/test_pdf_files.py`, `backend/deixis/__main__.py` (the watchdog only), `backend/deixis/documents/pdf.py` (`_watch_memory` and the constants only),
`backend/deixis/documents/pdf_files.py` (new), the four write lines in `backend/deixis/workflow/flow.py`, `backend/deixis/documents/acquisition.py` and
`backend/deixis/api/app.py`, `docs/decisions.md` (D162 at the top; D160 is the highest on main and on the other P9 worktrees today), `docs/product/p9-hardening-plan.md`
(status lines in the H2 section and next to F01 to F04 and I06), this prompt. Not allowed: `pyproject.toml`, `tests/acceptance/fixture_server.py` (import
it, do not edit it), `backup.py`, `worker.py`, `api/app.py::lifespan`, `codex_rpc.py`, `local_embedding_service.py` unless a child test finds a defect
there, `methods/`, `contracts/`, migrations, `apps/web`.

## Checks to run and report

- `-m process -n 0`: all pass, wall time of the file set, each threshold's measured value (F04 times and which exit path, I06 takeover time, child exit
  times).
- For F04 (2) and (3, SIGINT), F02 download write and the `pdf` orphan test: run them on the unfixed code first (apply the fixes last) and paste the failing
  line, so the report shows each fails without its fix.
- Full default `PYTHONPATH=backend:. uv run pytest` (baseline: 8,204 passed, 2 skipped on 4050a94, before this batch). Tests that fail only under parallel
  load: rerun alone and say so. Also `tests/test_cli_options.py`, `tests/test_documents.py`, `tests/test_ocr*.py`, `tests/test_arxiv_source*.py` by name.
- The main session runs the Playwright acceptance file after you finish (the fixes touch the download write path and the launcher); do not start it.
- `git status --short` at the end.

## Record

D162 at the top of `docs/decisions.md` (Status line must read "reviewer: Opus 5.5 high (Sol quota out), Sol re-review pending"): what was killed and
what each row showed (kill window, observed state after restart), the three fixes with the before measurements (F04 held call: no exit in 30 s and more;
SIGINT with a running extraction thread: 24 s and the thread's whole life; orphan alive 42 s and more; truncated hash-named file adopted), the F01 resend as
expected behavior, the Ctrl-C price of the forced exit, the leftover-file and orphan-source-row notes, and Limits: one shape per scenario and single runs;
SIGKILL, not power loss or kernel panic (SQLite WAL durability is not shown); the stand-ins are not real `codex` (H10); a child that ignores stdin EOF is
not stopped by anything in DEIXIS; the lifetime alarm bounds the orphan's time, not its memory (an orphaned extraction can still pass 1 GiB until it ends)
and the extraction child of a forced exit lives until then; a jats render leaves its temp folder and a pdf request leaves its placements file when the
parent is killed; the Marker runner and the Claude and Gemini CLI children are not covered; `scripts/p9/child_memory_probe.py` (default `--timeout 120`) is now ended by the alarm at 100 s; a torn `<sha>.pdf` already present in an existing library is not detected or repaired by anything; a terminal's Ctrl-C reaches the whole foreground process group, the tests signal the server PID only; a forced exit also cuts a slow `equations.stop()` or `builtin.stop()`; `scripts/p9/gil_diagnosis.py` would be ended by the alarm if it
ran past 100 s; payload files are written with `write_text` (rewritten on resume, not reused) and are not changed; Windows is unmeasured; the process tests
are not in the default run. Status lines for F01, F02, F04, I06, F03 (kill part only; the restore comparison is H4) in the plan.

## Do not

Do not add features, change the F-row wording, widen the fixes (no supervisor wrapper around `codex`, no new recovery path, no cancellation of tasks at
shutdown), or start the real `codex`.
