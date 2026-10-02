<!-- PLAN-REVIEW-ROUNDS: reviewer: Opus 5.5 high (Sol quota out), Sol re-review pending; gpt-6.1-sol returned a usage-limit error (until 3 October 2026 20:39); the implementer is a Sonnet subagent, the reviewer is a different model; rounds are recorded in D161 -->

# Task: P9 batch H1, clean install and start audit

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-h1`, detached at `89285fe` (main with D160). Plan: `docs/product/p9-hardening-plan.md`: read §2
(supported environment), §3.1, §4 rule 2 and rule 5, rows I01 to I08, §5 "H1", §8 and §9 (S1, S8). Also read `AGENTS.md`, `CLAUDE.md` and the
top of `docs/decisions.md` (D159, D139, D138 show how a P9 record reads). **No git state-changing commands** (no add, commit, stash, checkout,
reset, branch, worktree, no `git archive` into the worktree); read-only git (`git log`, `git diff`, `git ls-files`, `git archive HEAD | tar -x -C /tmp/...`)
is fine. Leave every change uncommitted. Do not invent; report what you could not find or measure. **No real-model call, no provider call.** Do
not touch the live service on port 8765, the ports 8858 to 8864, the live data directory (`~/Library/Application Support/DEIXIS`), the real
keychain, `TODO.md`, `.vscode/`, `scripts/local_index.py`, `.local/` of other worktrees, `docs/product/sw-status.md`, `../DEIXIS` or any other
worktree. No migration, no `methods/` or `contracts/` change, no change to the flow, the worker or the API. Kill every process you start (never
`pkill`; kill by the PIDs you recorded). Your own test runs use port **8872** (8871 is the orchestrator's), work directories `/tmp/h1-impl-*`,
and the caches below.

## Why

P9 turns "works on the developer's machine, by the developer's hands" into measured claims. H1 shows that a clean export of a commit, with the
README's own steps, installs, starts, serves the UI and stops again, and that the three failure modes a new user can meet (port busy, no UI
build, unwritable data directory) end with an understandable message. A new user must not need a model account, and the audit must never touch
the developer's keychain, library or live instance. Rows (plan §4): I01 to I05 and I07 are mandatory; I08 (a second person on a clean
account) is not part of this batch's work and is recorded as "not measured; no second-user claim".

## What is and is not in code (checked on 89285fe)

- `backend/deixis/__main__.py::serve` refuses a non-loopback host (exit 2), then `port_available` (bind with `SO_REUSEADDR`): a busy port prints
  `Port N is in use. DEIXIS may already be running at URL ...` to stderr and returns 2 before `create_app` runs. A missing `apps/web/dist`
  prints `UI build not found (apps/web/dist). The API will run; ...` to stdout (block-buffered when stdout is a file, so it appears in the log
  late) and the API still runs. `--no-browser` suppresses `webbrowser.open`.
- `serve` does **not** check the data directory. Measured on 89285fe (export, native arm64, Python 3.12.13, `DEIXIS_DATA_DIR` a `chmod 555`
  directory): the process prints a Python traceback ending in `sqlite3.OperationalError: unable to open database file` from `db.connect`,
  then `ERROR: Application startup failed. Exiting.` and exits with **code 3**; the data directory path appears only inside the traceback, the
  cause (permission) not at all; the directory stays empty. With a data directory that does not exist under a read-only parent the traceback
  ends in `PermissionError: [Errno 13] Permission denied: '/tmp/.../sub'`, exit 3. So I05's "error output names the directory and the cause in
  one sentence" is **not met** today; this batch fixes it (see "What to do", item 3).
- `uv run python -m deixis serve` starts `uv` and, as its child, the venv's python. SIGTERM sent to the `uv` PID reaches the python child:
  measured, both gone in about 0.5 s and the port free. The harness must send the signal to the top process only (what Ctrl-C or a service
  manager does), not to every PID.
- Keychain: `credentials.load_into_environment` (run by `config.load_settings`) calls `keyring.get_keyring()` and, when the backend has
  `priority > 0`, `keyring.get_password` for ten managed keys. With `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring` measured on
  keyring 25.7.0 (the version in `uv.lock`): `get_keyring()` returns the null backend with priority -1, `credentials.keychain_name()` returns
  `None`, `keyring.backends.macOS` is **not imported** (the control run without the variable imports it and returns `macOS.Keyring`, priority
  5), `set_password` does nothing and `get_password` after it returns `None`. So the variable works on this version; the harness must still
  check it, as the plan says, and stop with the alternative (separate user account or `HOME` redirect) if it does not.
- `/api/connections` returns `models` for `codex`, `claude`, `gemini`, `deepseek` (adapters) and nine names that answer
  `ready: false, reason: "Adapter not implemented in this version"`. With no `codex`, `claude` or `gemini` on `PATH` and no keys, every adapter
  returns `ready: false` and a non-empty `reason` without starting a subprocess (`codex CLI not found`, `Claude Code CLI not found`, `Add a
  ... API key in Settings ...`).
- `apps/web/e2e/acceptance.spec.ts` finds the home screen's question box with `page.getByLabel('Research question')`. `playwright.config.ts`
  uses `channel: 'chrome'` (system Google Chrome).
- This machine: macOS 27.0.1 arm64, `uv` 0.11.24, Node 22.23.2, npm 10.9.8, system Chrome; `uv`, `node`, `npm` and **`claude`** all live in
  `~/.local/bin`, `codex` in `/opt/homebrew/bin`, `gemini` in `~/.npm-global/bin`. A `PATH` made of the directories of `uv`, `node` and `npm`
  would therefore contain `claude`. The harness builds its own shim directory (below).
- Cold timing seen once: `uv sync` into an empty cache took 6 min 47 s wall on a slow network (3 s CPU). Do not assume short commands.
- `README.md` already has the supported-environment sentence (H0a). Not in code before this batch: any install script, any data-directory
  preflight, any README statement of the clean-install check.

## Decisions (made here; the plan's own default where it has one; do not ask the owner)

1. **Python harness, not shell.** `scripts/p9/install_check.py` is standard-library only and must run on Python 3.9 (the Xcode `python3` on a
   clean Mac): `from __future__ import annotations`, no `match`, no runtime `X | Y` unions, no 3.10+ library calls; it refuses to run (exit 2)
   below 3.9, when `platform.machine() != "arm64"` (an x86_64 anaconda `python3` under Rosetta says so; the message names
   `/opt/homebrew/bin/python3.12` or any arm64 interpreter as the one to use) or `sys.platform != "darwin"` (the supported environment is macOS
   arm64, plan §2). It needs process groups, signals and sockets that are awkward in bash. `scripts/p9/run_matrix.sh` is the plan's one-command entry; it
   only calls the harness for now and says where later batches add rows.
2. **Export the commit, not the working tree.** `git archive <rev> | tar -x -C <work>/export`. The export contains no `.env`, no `.venv`, no
   `node_modules`, no `dist`. The harness asserts there is no `.env` in the export. Because the batch's own changes are uncommitted, the harness
   also has `--overlay-uncommitted`: after the export it copies, from the working tree, the files that `git ls-files -m -o --exclude-standard`
   lists (read-only git), skipping `.local/`, `node_modules/`, `.venv/`, `dist/`, and records every overlaid path with its sha256 in the
   results (a path that no longer exists in the working tree, a deletion, is not copied; it is removed from the export and recorded as
   deleted; the overlay skips any file whose name starts with `.env`, and the assertion that **no file named `.env*` exists anywhere in the export** (Vite reads `.env.*` at build time) is run after the export and again after the overlay). Without the flag nothing is overlaid. The orchestrator re-runs the harness without the flag on the committed hash after the commit; that run, not the overlay run, is the one a closing record cites.
3. **Isolation (plan §4 rule 5).** The child environment is built from scratch (`env -i` semantics, never inherited) from a named allowlist:
   `PATH` (shim, below), `HOME` (real: uv finds its managed Python under `~/.local/share/uv`; the keychain is isolated by the variable below,
   not by `HOME`), `USER`, `LANG`, `TMPDIR` (inside the work dir), `UV_CACHE_DIR`, `npm_config_cache`, `PYTHONPATH=backend` for `serve` only,
   `DEIXIS_DATA_DIR`, `DEIXIS_CODEX_HOME`, `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring`, `npm_config_userconfig` and
   `npm_config_globalconfig` (both pointing at an empty file in the work dir, so `~/.npmrc` and its registry tokens are not read). The install
   steps (`uv sync`, `npm ci`, `npm run build`) additionally get, only if set in the caller's environment, `HTTP_PROXY`, `HTTPS_PROXY`,
   `NO_PROXY`, `http_proxy`, `https_proxy`, `no_proxy`, `SSL_CERT_FILE`, `NODE_EXTRA_CA_CERTS`; the `serve` runs and every probe do **not** get them (they get the loopback trap of decision 9 instead).
   results.json records the **names** of the variables passed, never their values (proxy values can carry credentials). Nothing else (no `DEIXIS_*` key, no `*_API_KEY`) is passed; the lists are constants in the script. `uv` reads `~/.config/uv/uv.toml` and `UV_*`
   variables are not passed, so the harness only **records** whether `~/.config/uv/uv.toml`, `~/.uv` or `/etc/uv/uv.toml` exists (the directory `~/.config/uv` alone is not a signal: here it holds only `uv-receipt.json`) (a user configuration can change an
   install; it is not blocked).
   The shim directory `<work>/bin` holds tiny `#!/bin/sh` wrappers `exec "<absolute path>" "$@"` for `uv`, `node`, `npm` and `npx`; `PATH` is
   `<work>/bin:/usr/bin:/bin:/usr/sbin:/sbin`. Preflight asserts `shutil.which` finds none of `codex`, `claude`, `gemini` on that `PATH`.
4. **Ports.** Default 8871. The harness refuses 8765, 8858 to 8864 and ports below 1024 (exit 2), and exits 2 when the chosen port is already
   in use at the start (except where a row binds it on purpose).
5. **Work directory.** `--work-dir` (default `/tmp/h1-install-<UTC stamp>`). It must **not exist** when the harness starts: the harness creates
   it (`mkdir`, not `exist_ok`) and deletes only what it created, never a path it was given that already existed; it refuses (exit 2) a
   path that exists, that is inside the repository, inside the live data directory, or that equals or contains `HOME`. A reused directory could
   carry an old `dist`, `.venv` or `node_modules` and make I04 and the "cold" claim pass by accident, so every run, including the overlay run, uses
   a fresh directory. The export, data directories, codex home, logs and, by default, both caches live under it, so the default run is a
   **cold** install (cold for dependencies; the Python interpreter that `uv` finds under `~/.local/share/uv` is not downloaded again); a **warm**
   install passes `--uv-cache` and `--npm-cache` of an earlier kept run (those paths are never deleted). The report records `cache_mode` for the uv cache and the npm cache separately (a cache path that does not exist yet is created, counts as cold for that tool, and is never deleted). The work dir
   is resolved with `Path.resolve()` once at the start (`/tmp` is `/private/tmp` on macOS) and only the resolved form is used afterwards,
   including in every command-line comparison. Raw output (results.json, per-step logs) goes to `--out-dir` (default
   `<repo>/.local/p9-h1/<stamp>/`, ignored by Git; also created fresh). `--keep` keeps the work dir; otherwise it is deleted at the end
   (restore write permission on any read-only directory first).
6. **Time limits (harness choices, written in the record, not product limits).** `uv sync` and `npm ci` 1800 s each, `npm run build` 900 s,
   `/api/health` ready within 60 s of start, graceful stop (SIGTERM to the top process, whole tree gone and port free) within 15 s, and **30 s for every other subprocess** (the keyring
   stages, I03a, I03b, each I05 run, the control) and 90 s for the shell check; a call that runs past its limit is killed (its own group, below),
   the row fails and the recorded PIDs are cleaned up, so a failed port check cannot leave a second server hanging.
7. **I08** is recorded as `not_measured`, text "not measured; no second-user claim". Nothing else is claimed for I08.
8. **Process safety.** Every child (install steps, `serve`, probes, `node`) is started with `start_new_session=True`, so it has a process group
   and session of its own that contain only its descendants. The audit set (below) never includes the harness's own PID, its ancestors or
   anything in the harness's own process group, and the harness never calls `os.killpg` on its own group or on any group it did not create. Cleanup
   signals only PIDs recorded from the harness's children (checked against the recorded command line first), SIGTERM then SIGKILL.
9. **Server-side outbound requests.** The `serve` runs get `HTTP_PROXY`, `HTTPS_PROXY` and `ALL_PROXY` set to `http://127.0.0.1:9` (the
   discard port: nothing listens) and `NO_PROXY=127.0.0.1,localhost`, so an outbound request from the app's httpx client (which honours these
   by default) fails instead of leaving the machine. This is a trap for the app's own HTTP calls, not a firewall; the limits say so. The
   `lsof` snapshots below remain as a second observation.
10. **One launcher, fail closed, always from the export.** Every process that runs `deixis` code (`uv run`, the venv's python, the keyring
    stage 2, `serve`) goes through one function that (a) sets `cwd=<export>`, runs `uv run --project <export>` and the absolute
    `PYTHONPATH=<export>/backend` (a relative path or the worktree as `cwd` would run the worktree's code, `.env` and `dist`, and would make the
    "committed code" run pass on uncommitted changes); (b) refuses to start unless `DEIXIS_DATA_DIR` and `DEIXIS_CODEX_HOME` resolve inside the work
    dir, `PYTHON_KEYRING_BACKEND` is the null backend, and neither `DEIXIS_HOST` nor `DEIXIS_PORT` is passed (a missing `DEIXIS_DATA_DIR` would
    fall back to the live library, `config.py::default_data_dir`). The `--self-test` checks (b) with a bad environment. The shell check and the
    install steps also take `cwd=<export>` (or `<export>/apps/web`). `shell_check.mjs` itself is run from the worktree copy (the exported
    commit does not contain it) and is given the export directory as an argument.
11. **Revision.** `--rev` (default `HEAD`, resolved to a full hash with `git rev-parse`; the hash is recorded).
12. **Order inside the harness** (so no file has to be moved): preflight; export; `uv sync`; keyring isolation
   check in the new venv (stop with exit 4 before anything else, `npm ci` and `serve` included, if it fails); `npm ci`; **I04** (serve before the UI is built); `npm run build`;
   **I02, I03b, I07** in one running instance; I03a; I05; process and port audit; cleanup. The record states this order.

## What to do

1. `scripts/p9/install_check.py` (the harness) with these steps and checks. Each row is a dict `{id, claim, result: "pass"|"fail"|"not_measured",
   execution: "real process", data: <string such as "empty library, no model, no provider key">, numbers: {...}, evidence: [...]}`; results.json is
   `{"commit", "overlay", "machine", "tool_versions", "cache_mode", "steps": [...timings...], "rows": [...]}`; at the end print a plain table and
   the rows are `I01`, `I02`, `I03` (one row; `evidence` carries a and b), `I04`, `I05`, `I07`, `I08` (`not_measured`), `keyring` and `cleanup`; every step in
   `steps` records its command line (without any secret; there is none), start time, seconds and exit code; the exit code is 0 only when every mandatory row passed, 1 otherwise, 2 preflight, 4 keyring isolation failed.
   - **Preflight:** arm64 macOS; `uv`, `node`, `npm` and `/Applications/Google Chrome.app` exist; versions recorded (`uv --version`, `node
     --version`, `npm --version`, `sw_vers -productVersion`, Chrome's `--version` read from the app's Info.plist, not by launching it); the Node
     version satisfies `engines` in `apps/web/package.json` (`>=22.12.0 <23`, npm `>=10 <11`): otherwise exit 2 with "unsupported environment" and run
     nothing (plan §2: outside it the result is "not supported", not "does not work"); shim `PATH` has no model CLI; port allowed and free.
     After `uv sync` the same model-CLI check is repeated for `<export>/.venv/bin` (`uv run` puts it first on `PATH`).
   - **Export** (item 2), then assert no file named `.env*` exists in the export; record sha256 of `uv.lock` and `apps/web/package-lock.json` before and after
     the install steps **and again at the very end** (`uv run` can re-lock; they must not change: a changed lock file means the install is not
     reproducible and I01 fails).
   - **I01:** run exactly the README commands in the export: `uv sync`; in `apps/web`: `npm ci`, `npm run build`. Each must exit 0; record wall
     seconds for each and the total; after `uv sync` assert `.venv/bin/python` reports `platform.machine() == "arm64"` and Python `3.12.x`; after
     the build assert `apps/web/dist/index.html` exists. Logs to `<out>/logs/`.
   - **Keyring check (after `uv sync`, before `npm ci`)**, two stages run with the venv's python and the isolation variable. Stage 1 is a
     process that does only `import keyring; type(keyring.get_keyring())` and checks `sys.modules`: the class must be
     `keyring.backends.null.Keyring` and no `keyring.backends.macOS*` module may be imported. **Only if stage 1 passes** is stage 2 run:
     `deixis.config.load_settings()` with the allowlisted environment (`PYTHONPATH=backend`, `DEIXIS_DATA_DIR` set) and
     `deixis.credentials.keychain_name()` must be `None`. The harness never calls `set_password` or `get_password` itself, in either stage or
     the control. A **control** run in the same venv without the variable only calls `get_keyring()` and records the backend class, to show the
     variable is what changes it (importing the backend module reads no secret). If stage 1 or 2 fails: record, print the alternative the plan names
     (a separate macOS user account, or `HOME` redirected to an empty directory, which also makes uv download its own Python), clean up, exit
     4, and run nothing further (in particular no `load_settings`, which would read ten keys from a real keychain). The running instance is
     checked too (I02): `GET /api/credentials` must answer `keychain.available == false`. Chrome of the shell check is launched with
     `--use-mock-keychain` (explicitly, besides Playwright's own default) so it does not read "Chrome Safe Storage"; record the launch args.
   - **I04** (export has no `dist` yet): start `uv run python -m deixis serve --no-browser --port P` from the export (the README command plus
     `--no-browser` and `--port`; env as in item 3, `DEIXIS_DATA_DIR=<work>/data-nodist`), poll `/api/health` until 200 (limit 60 s), assert
     `status == "ok"`, stop it with SIGTERM to the top PID, then assert the log (read after exit, because stdout is buffered) contains the line
     `UI build not found (apps/web/dist)`. Pass: warning line present and health was 200.
   - **I02** (after the build, `DEIXIS_DATA_DIR=<work>/data`): start as above; poll health; assert 200, `status == "ok"`, `worker == "owner"`,
     record `skill_package_hash` and the seconds to ready; the log has `DEIXIS is running at`. Run the **shell check** (below) in Chrome. Take
     snapshots of the process tree (descendants of the top PID, plus every process in the top process's process group or session, plus every
     process whose command line contains the work dir, by `ps -axo pid=,ppid=,pgid=,sess=,command=`) right after ready, after I03b and I07, and
     immediately before the SIGTERM; the audit set is the union of all of them; record the counts and command names. At each snapshot also
     record the sockets of those PIDs (`lsof -nP -a -p <pids> -i`): every remote address must be loopback; a non-loopback connection is
     recorded as a finding (it does not by itself fail the row, since two instants prove nothing about absence), and if `lsof` cannot be run
     the evidence says "not measured". Then, still running, do I03b and I07 and the `/api/credentials` check. Finally send SIGTERM to the top PID only and wait up to 15 s: pass when the top
     process exited, every PID in the audit set is gone (a PID counts as gone when `kill -0` fails or its command line no longer equals the recorded
     one), no process has the work-dir path in its command line (matched as a whole path component, `<work>/` or a complete argument, never a bare prefix: `run1` is a prefix of `run10`; the harness's own PID, its ancestors and its own process group are excluded from this match), no Playwright Chrome profile of the shell check is left, and the port can be
     bound again (`socket.bind` plus no `lsof -nP -iTCP:P -sTCP:LISTEN` line). Record seconds to exit and the exit code. If something survives,
     the row fails, name it, then SIGKILL the recorded PIDs so nothing is left behind.
   - **Shell check** `scripts/p9/shell_check.mjs`: Node, run with `node` from the shim `PATH`, arguments `<export dir> <url> <screenshot path>`.
     It loads Playwright from the export (`createRequire(path.join(exportDir, 'apps/web/package.json'))('@playwright/test')`, `chromium`),
     launches system Chrome (`channel: 'chrome'`, headless, a temporary profile that Playwright creates), aborts every request whose origin is
     not the served origin and counts them, opens the URL, waits up to 30 s for `getByLabel('Research question')` to be visible, saves a screenshot
     into the work dir (never into the repository), prints one JSON line `{ok, title, external_requests_blocked, console_errors, seconds}` and
     closes the browser. A page that loads but has no question box is `ok: false`. Pass criterion for I02's UI part: `ok: true`.
   - **I03b** (first instance running on P): start a second `serve` on the same port and the same data directory. Pass: exit code 2, stderr contains
     `Port P is in use`, its output contains no `Application startup` (it never reached `create_app`), the data directory's recursive set of file
     names is identical before and after (names only: the first instance may touch WAL contents), and the first instance still answers
     `/api/health` with `worker == "owner"`. I03 passes only when I03a and I03b both pass. This is the "second instance is not a writer" claim; it shows the launcher refuses, not that two
     workers cannot coexist (that is I06, H2).
   - **I03a** (after the I02 instance is gone): the harness itself binds `127.0.0.1:P` (listening socket, closed afterwards) and runs `serve`
     with `DEIXIS_DATA_DIR=<work>/data-never-created` (does not exist). Pass: exit 2, message `Port P is in use`, the directory still does not exist.
   - **I05:** data directory `<work>/data-readonly`, created and `chmod 0o555`. Record the recursive file-name listing, run `serve`, record it
     again. Pass when: exit code is not 0; the listing is identical; no `library.sqlite` and no `-wal`/`-shm`; two separate conditions on the combined output: (1) it does **not** contain the text `Traceback (most recent call last)`, and (2) it does contain a line with both the resolved directory path and a cause. Also run the variant
     `DEIXIS_DATA_DIR=<readonly parent>/sub` (does not exist, parent read-only) and record it as an extra line (it is not a plan row and does not decide I05's result; it must
     meet the same message criterion and a failure is reported). The message criterion's cause pattern is fixed:
     `(?i)not writable|permission denied|read-only|not a folder`, and the line must contain the resolved directory path. Restore the mode in a `finally`.
   - **I07** (running instance of I02): `GET /api/connections`; pass when all of `codex`, `claude`, `gemini`, `deepseek` are in `models`, every
     entry has `ready == false` and a non-empty string `reason` that matches `(?i)cli not found|api key|not implemented in this version`,
     `codex`, `claude` and `gemini` have `installed == false`, `gemini` and `deepseek` have `key_configured == false`, and no entry has a
     `cli_version`. (A reason such as `Claude Code SDK error` would mean a CLI was found and a subprocess started: that fails the row.) Record
     `{name: reason[:80]}` and the audit set's command names (none may be `codex`, `claude`, `gemini` or `tesseract`). It shows the app
     starts and explains itself without any model account; it does not show a working model connection.
   - **Process and port audit** at the very end: no recorded PID alive, nothing listening on P, no process whose command line contains the work
     dir (same matching rule). Add this as row `cleanup` (not a plan row, mandatory for the harness's exit code).
   - Signal handling: a `SIGINT`/`SIGTERM` handler and a `finally` that kill every recorded child process group, restore modes and
     close sockets.
2. `scripts/p9/run_matrix.sh` (bash, `set -u`, `cd` to the repo root): runs `python3 scripts/p9/install_check.py "$@"` and returns its status;
   a comment says later batches append their rows below. Mode 0755.
3. **Small fix in `backend/deixis/__main__.py`** (plan H1: "only if an install step gives an unclear error"; I05 does): before `serve` builds the
   app and after the port check, call a new module-level `data_dir_problem(path: Path) -> str | None`. It walks up to the nearest existing
   ancestor (the path itself if it exists), returns `"is not a folder"` when that is not a directory, `"is not writable"` when
   `os.access(that, os.W_OK | os.X_OK)` is false, otherwise `None`; it creates nothing and writes nothing. `serve` prints one line to stderr,
   for example `Cannot use the data directory <path>: it is not writable (permission denied for <existing ancestor>). Set DEIXIS_DATA_DIR to a
   folder you can write to.` (your own wording, one sentence, both the path and the cause in it, no traceback) and returns 2. Nothing else in
   `__main__.py` changes: not the host check, not the port message, not `backup`/`restore`. `tests/test_cli_options.py` gets tests:
   a `chmod 0o555` directory (skipped when `os.geteuid() == 0`) makes `serve` return 2 with the path in stderr and `create_app` never called
   (monkeypatch `cli.create_app` to raise, and `cli.port_available` to return `True`: `serve` checks the port first and the default port is 8765, the
   owner's live service, which a test must never bind or depend on); a path under a regular file gives `"is not a folder"`; a writable directory and a not-yet-existing
   subdirectory of a writable one give `None`; nothing is created in any of the cases (listing before and after).
4. **README.md** (only these edits): (a) as a new paragraph after the existing "Configure keys ..." paragraph of the Quickstart (the one ending before `## Architecture`), one short paragraph naming `python3 scripts/p9/install_check.py --port
   8871` as the clean-install check (exports `HEAD`, separate data directory and port, isolated keychain, never the live instance), what it
   needs (arm64 macOS, an arm64 `python3` 3.9 or newer, `uv`, Node 22, Chrome; with an x86_64 `python3` use `/opt/homebrew/bin/python3.12` or another arm64
   interpreter) and that a cold run downloads dependencies and can take many minutes; (b) in "Commands", one
   sentence of prose, placed after the line "From the repository root, unless a command changes directory:" and before the `sh` code block (not inside it),
   saying to back up with `deixis backup` before updating the checkout (README advice only; do not claim that a newer
   library is refused, that is H4); (c) the stale status sentence near the end of the historical section ("Real model execution, evidence
   review and production persistence are not implemented."): grep the backend for the model-selected review that the paragraph describes
   (an assessment of a versioned snapshot by another selected model); the sentence is false either way (real model steps and the SQLite
   library exist; `workflow/report/review.py` exists), so replace **only that sentence** with a true one in every case; what you find decides its
   content (for example: the optional review by another selected model described in this paragraph is / is not implemented, while the model steps
   and the local library described above are). Say in your report what you grepped and found. (d) in the first Quickstart sentence ("install Python 3.12, uv, Node.js/npm, and a model connection you can authenticate"), say that a model
   connection is needed to run researches, not to install or start the app (the clean-install check starts it with none; this edit is for whoever
   follows the README on a clean account). Keep the
   README's plain style; no AI-slop phrasing. Do not touch badges, the bibliography or any other section.
5. Do not edit `docs/decisions.md`, the plan, or create `docs/product/p9-acceptance-record.md` (plan §8 merges the per-batch sections there in H8; H0a to
   H0c did not create it either): the orchestrator writes the decision record, which carries this batch's rows, and the plan status line.

## Tests and checks (you run them, with port 8872)

- `git diff --check`; `python3 -m py_compile scripts/p9/install_check.py`; `node --check scripts/p9/shell_check.mjs`.
- `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest tests/test_cli_options.py -q -n 0` (this machine is loaded).
- One real harness run against the committed code with warm caches to debug it:
  `python3 scripts/p9/install_check.py --port 8872 --work-dir /tmp/h1-impl-run1 --uv-cache /tmp/h1-pre-uvcache --npm-cache /tmp/h1-npm-cache --keep`
  (the first `npm ci` fills the npm cache from the network). Expect I05 to **fail** on the message criterion on the committed code, which is
  the "before" measurement. Then one run with `--overlay-uncommitted` where I05 passes. Report both outputs' row results and timings.
- Negative controls: the harness has a `--self-test` flag that runs pure-function assertions (no server, no network, no install) and exits
  0 or 1: the I07 check returns `fail` for an entry with `ready: true` and for an empty `reason`; the I05 message check returns `fail` for
  the traceback text quoted above (path only inside a traceback), for the read-only-parent output `PermissionError: [Errno 13] Permission
  denied: '<path>'` inside a traceback (a single line with path and cause, but a traceback: fail), and `pass` for a one-line message with path and
  cause; the keyring stage-1 decision returns `fail` for the class name `keyring.backends.macOS.Keyring` and for an imported `keyring.backends.macOS` module;
  the I04 check returns `fail` when the warning line is missing; the I03 message check returns `fail` without `Port P is in use`; the "tree gone"
  check returns `fail` for a live PID with the recorded command line and `pass` for a dead one; the port refusal accepts 8871 and refuses
  8765, 8860 and 80. Run it.
- Delete `/tmp/h1-impl-*` work directories you created when you are done, after restoring modes.

## Limits to keep in view (the orchestrator writes them into the decision; do not weaken them)

Cold timing depends on the network of that run; one machine, one macOS version, one run per mode; `HOME` is real (only the keychain is isolated by
the environment variable, and the isolation was verified only on keyring 25.7.0); the UI check proves the question box renders, not that a
research can run; I02's stop is by SIGTERM to the top process, not Ctrl-C in a terminal and not a LaunchAgent; I03b shows the launcher refuses a
second server on the same port, not two workers on one data directory (I06, H2); I05 covers a read-only directory and a read-only parent, not a
full disk (F05) or a read-only `library.sqlite` inside a writable directory; no behavior on another macOS, with a corporate proxy, or without
`uv`/Node; server-side outbound requests are trapped only for the app's own httpx client (proxy variables to a dead loopback port) and observed at three or four
instants, not blocked by a firewall; the real `HOME` may receive writes from `uv` (its managed Python) or Playwright (its cache links), which the harness cannot prevent; a `~/.config/uv` user configuration is recorded, not
blocked; I08 not done.

## Report (your final message, tight)

Files changed (`git status --short`); for each row I01 to I05, I07 the result and numbers on the committed-code run and on the overlay run;
timings per step (cold if you did one, warm otherwise, say which); the keyring check output; the exact I05 message after the fix; what you grepped
for the README sentence and what you wrote; anything you could not do or measure; anything in this prompt that did not match the code.
