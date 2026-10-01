# Task: P6 slice 2, batch L9 (run half), the real-model development-lines measurement

Written 1 October 2026 with the freeze. Nothing in this file has been run. The frozen expectations are
`docs/product/p6-slice2-expectations.md` and `docs/product/p6-slice2-chain.json` (the pre-written chain G); the kit is
`scripts/p6_eval/measure_lineage.py`; the method is `docs/product/p6-slice2-chain-of-ideas.md` sections 14 and 17 (D130). What went
wrong in the P16 series (D124, D126, D128) and is not repeated: freeze before any run, product tree and `skill_package_hash` checked at
the dry start, zero `started` sessions verified, no intervention during the run.

## Start only if

1. The freeze commit (expectations, chain, kit, its test, this file) is on `origin/main` (`git fetch` and `git log origin/main`), and
   `p6-slice2-expectations.md` no longer says TASLAK. If it still does, stop and say so.
2. `PYTHONPATH=backend:. uv run pytest tests/test_p6_measure_lineage.py -n 0` passes in the pinned worktree.
3. No other session uses Luna and nothing is bound to port 8867 (`lsof -i :8867`). The live service on 8765 is never touched.

## Where and how

- **Worktree** pinned at the freeze commit: `git worktree add ../DEIXIS-l9run <freeze-hash>` (detached). Product trees must equal the
  frozen ones: `git rev-parse <hash>:backend` = `aa638af2...`, `:contracts` = `d06c7968...`, `:methods` = `a035e01b...`, `:apps/web` =
  `9e3ecf7d...` (full values in the expectations file). the executing worktree is checked, not only the commit: `git -C ../DEIXIS-l9run rev-parse HEAD` is the freeze hash,
  `git -C ../DEIXIS-l9run diff <hash> -- apps/web backend contracts methods` is empty (staged and unstaged) and
  `git -C ../DEIXIS-l9run status --porcelain --untracked-files=all -- apps/web backend contracts methods` prints nothing; repeat it
  before the dry start, before each snapshot and after the run.
- **Run folder:** `RUN=/Users/huguryildiz/Documents/GitHub/DEIXIS/.local/p6-slice2-l9` (absolute, ignored by git, never committed). It holds
  `protocol.md`, `data/` (EMPTY at the start; never a copy of the owner's library), `server.log`, `poll.log`, `ledger.jsonl` (one JSON
  line per event with the session count), `expectations.sha256` and `chain.sha256` (of the two frozen files), the kit's outputs, saved
  API responses and the readers' files.
- **Server:** from the worktree, `nohup env -i PATH="$PATH" HOME="$HOME" DEIXIS_DATA_DIR="$RUN/data"
  DEIXIS_CODEX_HOME="$HOME/Library/Application Support/DEIXIS/codex-home" PYTHONPATH=backend:. uv run --no-sync python -m deixis serve
  --port 8867 --no-browser > "$RUN/server.log" 2>&1 &`. No other `DEIXIS_*` variable. The web build is not needed (API only).
  `DEIXIS_MODEL_CONCURRENCY` stays unset; `/api/health` does not report it, so record the pinned code's default (6) and that the launch
  environment sets no override.
- API calls follow `scripts/p6_eval/measure_fill.py`: `GET /api/session`, send the returned token as `x-deixis-csrf` on every non-GET.
- **Model:** `codex` / `gpt-5.6-luna` / `medium`, passed explicitly in the research record. Read the scope back; if it differs, stop.
- **Counter:** `sqlite3 "file:$RUN/data/library.sqlite?mode=ro"` (never write). Sessions of a run:
  `SELECT count(*), sum(status='started') FROM model_sessions WHERE run_id = ?`. **Preparation uses one aggregate counter**: the whole table,
  `SELECT count(*), sum(status='started') FROM model_sessions` (the library starts empty, so this spans both attempts and the fill), plus an
  elapsed-time ledger from the first research record to the filled table. Read it every 15 seconds while a run is active and write each
  reading to `poll.log`. At a cap or an unreadable counter: cancel the active runs through the API, read the count once more after they
  drain, write the overshoot as `over_cap_in_flight`, and stop.

## Steps

1. **Dry start and protocol.** Start the server on the empty `$RUN/data`; `GET /api/health` must show the frozen `skill_package_hash`
   (`sha256:371fcecb7977...`); run the executing-worktree check of "Where and how" and compare the four tree hashes with the frozen values; `SELECT count(*) FROM model_sessions WHERE status='started'` = 0 and no
   non-terminal run exists. Write `protocol.md` (freeze hash, trees, skill hash, the sha256 of all five freeze files (expectations, chain JSON, this prompt, the kit and its
   test; recheck them before every snapshot and score), the server environment, the model, the
   research record fields, the caps copied from the expectations file, the stop rules) **before** any research exists. Anything unequal: stop.
2. **Independence reference** (reads the owner's live library through the product's own consistent backup; it writes only under `$RUN` and is skipped if the main session withholds that read, in which case K0 is recorded as not verifiable and the measurement stops before the table). `DEIXIS_DATA_DIR="$HOME/Library/Application Support/DEIXIS" PYTHONPATH=backend:. uv run --no-sync python -m
   deixis backup "$RUN/owner-backup"` (it reads the live library consistently while the service runs). Keep the dated folder; it is only read.
3. **Create the research** (`POST /api/researches`) with the frozen question and record fields, then `POST /api/researches/{id}/runs`
   `{"kind":"discovery"}`. When the run pauses for `protocol_approval_needed`, copy the card to the ledger and approve it as proposed
   (`POST /api/runs/{run_id}/protocol-approval` with `{}`); no edits. Wait until
   the discovery run is `completed` (the full-text fetch runs inside it; its `fulltext_summary` step must be `succeeded`) and, if discovery
   queued a `fulltext_adjudication` run, that run is `completed` too (no such run is an accepted outcome, written down; no separate
   `fulltext_fetch` run is expected). Record each run's status, steps, `error` and session count. The expected successor run is not a foreign
   queued run. Preparation caps: 300 sessions in total over all attempts and 4 hours (quota waits excluded and recorded). A stop for the frozen reasons
   is a stop; a second attempt (new research, same question) only under the infrastructure rule of the expectations file. Do not
   restart a run to get a better corpus.
4. **Rows, independence, table.** `PYTHONPATH=backend:. uv run --no-sync python scripts/p6_eval/measure_lineage.py rows --db
   "$RUN/data/library.sqlite" --research <id> > "$RUN/rows.json"` prints the frozen selection. Then `PYTHONPATH=backend:. uv run --no-sync python scripts/p6_eval/measure_lineage.py independence --db
   "$RUN/data/library.sqlite" --rows "$RUN/rows.json" --reference "$RUN/owner-backup/<dated>/library.sqlite" > "$RUN/independence.json"` (check
   the backup's actual layout; it compares every included work, not only the rows). Any overlapping source is K0 failing: create no table, make
   no fill, write `gates.md` with the independence result and go straight to the **no-lineage branch** of steps 9 and 10.
   Otherwise create the table with `POST /api/researches/{id}/tables` `{"title":"L9 development lines","rows":[...]}` using exactly the
   rows of `rows.json`, then `POST .../tables/{tid}/lineage/columns` with `{"expected_version": <table version>}` and an
   `Idempotency-Key`. Fill with `POST .../tables/{tid}/fill` (`{"expected_version": <version>}`; every active column). Nothing is
   edited by hand. Wait for the fill run to end (it counts in the aggregate preparation cap).
5. **Gates and addendum** (only when a table exists). Read `GET .../lineage` (`status.pdf_text_rows`, `status.nodes_complete`) and `GET .../lineage/plan` (sum of
   `candidate_count`, number of `selected` works with `candidate_count > 0`). Save both. K0 (independence) to K3 of the expectations file
   decide: if any fails, write `gates.md` with the numbers, make **no** lineage run, skip steps 6 to 8, and go to steps 9 and 10 with the
   no-lineage branch: the results document says R12 to R15 are not measurable because no lineage run was made, and why. If all pass, write
   the dated addendum `addendum.md` before anything else: table id, sha256 of `rows.json` and of the saved `GET .../tables/{tid}` response,
   the plan's `preview_fingerprint` and `counts`, the gate values, date and time.
6. **The one lineage run.** `POST .../lineage/runs` `{"preview_fingerprint": <the addendum's value>, "retry_failed": false}` with
   `Idempotency-Key: l9-lineage-1` (a 409 means the input changed: stop and say so). After the run exists, its stored plan's
   `preview_fingerprint` (`runs.target_json`) must equal the addendum's. Poll the run every 15 seconds. Caps: the plan's `max_model_calls` in sessions and 60 minutes (quota waits excluded).
   Stop rules exactly as the expectations file. After the in-flight calls drain, read the root errors from the stored steps and sessions
   (`SELECT operation_key, status, error_code, error_json FROM run_steps WHERE run_id = ?` and the sessions' `validation_json`), never from the
   run's `pause_reason`. Only when every root error is `client_timeout` resume once after 10 minutes; when every root error is quota or
   load the measurement waits and the main session is told; resume only on its "connection is back" instruction, the same run, at most twice for the lineage run (three times
   per preparation run), each recorded; a mix, anything else, or a spent limit stops. No cell edit, no link edit,
   no new run. A stop is a result, not a failure of the measurement: write the reason, the structural numbers, the sessions and minutes, and
   measure nothing from the half run: use the stopped snapshot of step 7. When the run ends, read the session count once more; any session
   still `started` is a stop.
7. **Snapshot** (server still up): `PYTHONPATH=backend:. uv run --no-sync python scripts/p6_eval/measure_lineage.py snapshot --research <id> --table <tid> --run <lineage run id> --base
   http://127.0.0.1:8867 --db "$RUN/data/library.sqlite" --g docs/product/p6-slice2-chain.json --out "$RUN/kit"`. A stopped or paused run goes through the same
   command with `--stopped <reason>` (the kit then writes `results.json` with structure and usage only and no reader sheet); without it the
   kit refuses a run that is not `completed` with a succeeded publication, or while a session is `started`. Save the research JSON, the
   table view and `GET .../lineage` into `$RUN/` as well. Check the frozen diff is empty. Then stop the server.
8. **Reader** (skipped for a stopped run and for the no-lineage branch). One separate Claude Sonnet session (Agent tool, `model: "sonnet"`) given only `$RUN/kit/reader.md` fills `$RUN/kit/reader.json`
   (at most two sessions, 30 minutes each; a second only for a missing, invalid or overflowed answer; the page is never shortened). It is
   outside every cap and counted separately; record the resolved model id, the default effort and that it is a model reading. The
   branches are exclusive. A complete valid reading goes to the ordinary score: `PYTHONPATH=backend:. uv run --no-sync python
   scripts/p6_eval/measure_lineage.py score --out "$RUN/kit"` (with a zero-link sample R12 and R13 come out not measurable by themselves and the
   mention-form items are the only reader work). An incomplete reading ends with the same command plus `--unread reader_incomplete`, and a sheet
   whose reading material could not be rebuilt from the accepted revision's own input (the kit refuses a semantic score and says so) ends with
   it plus `--unread material_unavailable`; in both of those, R12, R13 and the mention form are not measurable, R14 and R15 stay as measured in
   `snapshot.json`, and you go straight to step 9.
9. **Results document** (three shapes: a measured run; a stopped run, built from the stopped snapshot's `results.json` with structure and
   usage only; the no-lineage branch, which says that no lineage run occurred, reports zero lineage runs, the gate values or the K0
   overlap and the preparation record) `docs/product/p6-slice2-results.md`: first paragraph says what this measures (one fresh corpus, one run, one link
   producing model, the supported mention form, tied to this table; reader models named; model reading, not human review). One row per metric
   from `results.json` against the frozen range and the "my assumption is wrong if" sentence as `in range`, `out of range` or
   `not measurable`, with value, denominator, sample, reader. Hard rows (R12 not-supports, R13) first. Then the structural counts, every G
   pair with its status, the mention-form counts (pairs with a body mention, reference-list-only pairs, unclear; the sentence that all
   found mentions are in reference lists is never written), R15 with reasons, the independence result, the preparation record (attempts,
   sessions, minutes, what was left out of the table and why), calls, tokens and time of fill and lineage, and what could not be read. The
   expectations file is not edited. A success and a failure are each their own decision record.
10. **Decision record** in `docs/decisions.md` (next free D number after `git fetch`; D141 unless taken), Status/Date/Context/Decision/
    Evidence/Limits, numbers from the results document, the language of section 14 item 5, and the open items (reference-list handling,
    numbered citations). Mark L9 done in `p6-slice2-chain-of-ideas.md` section 19 and the L9 row of its batch table. Do not commit, push or
    change git state; the main session does that.
11. gpt-6.1-sol high reviews the results text until it says hazir (only high findings block).

## Recorded, and where

Under `$RUN`: `protocol.md`; `expectations.sha256`; `chain.sha256`; `data/` (the run's library); `server.log`, `poll.log`, `ledger.jsonl`;
`owner-backup/`; `rows.json`, `independence.json`; `gates.md` or the saved plan, lineage and table JSON; `kit/{snapshot.json,reader.md,
key.json,reader.json,results.json}`; the reader's model.

## Limits

- No real-model call outside the preparation runs, the one lineage run and the one Sonnet reader. No second lineage run for any reason,
  including a sample that reads badly. No edit of the expectations or of G after the freeze. gpt-6.1-sol editorial reviews of the results text are outside the measurement, recorded separately, and do not touch the "one producing
  model" statement. No change to `backend`, `contracts`, `methods` or `apps/web` during the measurement; a defect found is recorded and the measurement continues or stops under the frozen rules.
- Do not touch the live library or service (8765), `.vscode/`, `TODO.md`, `scripts/local_index.py`, or the earlier `.local` folders.
- Results say what they measure: workflow and reading evidence on one fresh corpus with the supported mention form, not development-line
  quality in general and not behavior on numbered-citation fields.
