# Task: P6 slice 1, batch P16 (run half), the real-model report measurement

Written 30 September 2026 with the preparation half (`p6-slice1-p16-prompt.md`), for a later session. Nothing in this file has been
run. The frozen expectations are `docs/product/p6-slice1-report-expectations.md`; the kit is `scripts/p6_eval/measure_report.py`;
metrics R1-R11 are defined in `docs/product/p6-report-design.md` section 13; the plan is `p6-slice1-report-run.md` section "1n".

## Start only if

1. `p6-slice1-report-expectations.md` is committed on `main` in its own freeze commit and no longer says TASLAK. Its decisions
   (made by Claude and gpt-6.1-sol on the owner's instruction, 30 September 2026) stand: path B on `res_IXBsnzhYZsKByEdTpSJo`, the
   seven frozen columns, model readers only, report cap 60 sessions / 90 minutes, fill cap 60 sessions / 60 minutes. If the file
   still says TASLAK, stop and say so; do not choose.
2. `scripts/p6_eval/measure_report.py` and `tests/test_p6_measure_report.py` are committed and the tests pass.
3. No other session is using Luna (`sw-status.md` row 30 is closed since D114; ask the owner if unsure) and no server is bound to
   the port below.
4. P15's `results.json` (`.local/report-behavior-<date>/results.json`) is optional auxiliary context, already known before the freeze. R10
   is not measured in this slice (no error is seeded into a stored report): the row is always written `not_measurable`
   (`p15_behavior_is_not_r10`), and P15 is never compared with an R10 range. With `--seeded` the kit only carries the file as a
   separate `p15_behavior` record; `flagged` means a finding was raised on the seeded claim, not that the fault was correctly
   diagnosed.

## Where and how

- **Worktree** pinned at the commit that holds the frozen expectations and the kit: `git worktree add ../DEIXIS-p16run <hash>`
  (detached). The run does not follow later commits; `git diff --stat <hash> -- backend apps/web contracts methods` must stay
  empty during the run and is checked before the run starts and after it ends. Write the hash and the `skill_package_hash` (from a
  dry server start in an empty data directory) into `protocol.md`.
- **Run folder:** `RUN=/Users/huguryildiz/Documents/GitHub/DEIXIS/.local/p6-eval-2026-09-30` (absolute; every command below uses `$RUN`, never a relative `.local/...`, because the commands run from the worktree and the folder is in the main checkout) (ignored by git, never committed). It holds `protocol.md`,
  `data/` (the library copy), `server.log`, `poll.log`, the ledger, the sha256 of the expectations file, and the kit's outputs.
- **Library copy, never the live one, taken through the product's own consistent backup** (the live database is in WAL mode; a file
  copy could mix two moments): `DEIXIS_DATA_DIR="$HOME/Library/Application Support/DEIXIS" PYTHONPATH=backend:. uv run --no-sync python
  -m deixis backup "$RUN/backup"`, then `DEIXIS_DATA_DIR="$RUN/data" PYTHONPATH=backend:. uv run --no-sync python -m deixis restore
  "$RUN/backup/<the dated folder>"` into the empty `$RUN/data` (restore verifies the listed hashes). Path B is decided (fill on the
  copy): symlink `tools` to the live one (`ln -s "$HOME/Library/Application Support/DEIXIS/tools" "$RUN/data/tools"`; it is only read).
  The live service on 8765 is not touched, restarted or queried; the backup runs while it serves, which is safe.
- **Clean the copy of foreign work before the server starts.** The worker takes any queued job of the copy, not only ours. With
  `sqlite3` on `$RUN/data/library.sqlite` list runs whose status is `queued`, `running`, `pause_requested` or `paused` and any
  pending file-read or extraction rows; write the list into `protocol.md`; if any exist, set those runs to `cancelled` in the copy
  (the copy only) and record it. Do the same for `person_pdf_requests` rows with status `waiting` or `planned` (the worker turns
  `waiting` rows into new full-text reading runs at start, `flow.py::queue_person_readings`): set them to `unread` in the copy and
  record the counts. Re-run both queries; both must return zero rows before the server starts, otherwise stop and say so. This is
  how no foreign model call runs and none escapes the `run_id` session counters.
- **Port 8866** (not 8765, not 8858-8864, not 8799 which `measure_fill.py` uses). Check it is free with `lsof -i :8866`.
- **Server environment**, written into `protocol.md` before the start: `DEIXIS_DATA_DIR=<the copy>`;
  `DEIXIS_CODEX_HOME="$HOME/Library/Application Support/DEIXIS/codex-home"` (a copy without the Codex home cannot sign in;
  earlier live runs set exactly this); every other `DEIXIS_*` variable removed (`env -i`-style, keep `PATH` and `HOME`);
  `DEIXIS_MODEL_CONCURRENCY` left at its default 6 and the value the server reports recorded.
  `PYTHONPATH=backend:. uv run --no-sync python -m deixis serve --port 8866 --no-browser`, started with `nohup` in the background,
  from the worktree.
- **Model: `gpt-5.6-luna`, passed explicitly.** The report's model is the research's scope (`model_connection`,
  `requested_model`, `reasoning_effort`; the same model runs the plan, sections, phrase repairs, review and the research title).
  Read them from `GET /api/researches/{id}` before anything else. They must read `codex` / `gpt-5.6-luna`; if not, stop (the
  measurement is defined for Luna; changing the scope would change the scope revision the report belongs to). For path B, create the
  research scope with `model_connection=codex`, `requested_model=gpt-5.6-luna`, `reasoning_effort=medium`, as the candidate
  researches already have. Record the effort in `protocol.md`.
- API calls follow `scripts/p6_eval/measure_fill.py`: `GET /api/session`, send the returned token as `x-deixis-csrf` on every
  non-GET request.

## Steps

1. **Freeze `protocol.md`** (nothing is started before it exists): worktree hash, `skill_package_hash`, expectations sha256,
   the research id as chosen in the expectations file (25 included sources, the most one fill run reads), the seven frozen columns
   (copied from the expectations file before the fill), the seed (20260930) and sample
   size (30), the readers, the caps, the server environment, the stop rules copied from the expectations file. Then, **before the
   report starts and dated**, append the addendum: the table id, the count of rows, columns, filled cells and rows with PDF text,
   and `pairs.json` (`[{"source_key", "formulation"}]`, marked from the filled table's equation column and never changed after).
   The addendum follows step 2. The report does not start without the addendum.
2. **Fill (path B is decided):** create the table on the copy with exactly the seven columns of the expectations file, word for word
   (`answer_format`, options and instructions as frozen); if the table would have more than 8 columns, stop: the fill cap is void.
   Fill it (`POST .../tables/{id}/fill`). Caps: **60 model sessions of the fill run's `run_id` and 60 minutes from the moment the
   fill request is sent, waits and queue time included.** Stop rules of the counter (apply to the report run too, with 60 sessions
   / 90 minutes from the report request): (a) if the session count cannot be read on a poll (sqlite error, missing file, malformed
   row), stop the run at once (cancel it through the API) and record that; do not go on without a count; (b) 15-second polling is
   not a hard limit: calls in flight at the poll that finds the cap reached, and any sessions that finish after the cancel, are
   counted and written in the ledger as `over_cap_in_flight`, and the final session count is read once more after the run has
   stopped and recorded; (c) after the last research step, a final count at or above the cap is a stop, not a pass; (d) a stop for
   any of these reasons is a stop, not a failure of the measurement: the run goes to R1 and R7 only. The table must reach `report_ready` (`GET /api/researches/{id}/tables/{id}` and the readiness
   panel's rule) before step 3; if it does not, the measurement does not start and the run says why. Nothing is edited by hand.
3. **Start one report run:** `POST /api/researches/{id}/reports` with `{"table_id": ...}` and an idempotency key `p16-report-1`.
   Poll `GET /api/researches/{id}` every 15 seconds; count the `model_sessions` rows of the copy whose `run_id` is the report run's id
   (`sqlite3` with `mode=ro`; never the copy's older sessions) on every poll. Stop at the report session cap (60) or the wall-clock cap (90 minutes) under the counter rules of step 2. Do not edit a cell, add a PDF, answer
   the queue, rewrite a section or resume a section by hand. The stop rules (quota or rate limit stops; one `client_timeout`
   resumes once after 10 minutes; any other `model_call_failed` stops; never another model or connection) apply as frozen. A
   paused run is resumed only for `client_timeout`, once.
   **A fill that stops before the table is `report_ready` starts no report:** record the fill stop (reason, session count, minutes) in
   `protocol.md` and the ledger, skip steps 3-7, and let the results document say that R1-R11 are not measured because the fill
   stopped. `snapshot --stopped` is only for a report run that exists.
4. **When the run ends or stops:** save `GET /api/researches/{id}` (the run, its steps, its `error`) and the report view and Markdown
   export into the run folder. **Do not stop the server yet** (step 5's `snapshot` reads through its API, and the readers of step 6
   open the original PDF pages of R6's equations through it); check the frozen diff is
   still empty.
5. **Measure:** from the worktree,
   `PYTHONPATH=backend:. uv run --no-sync python scripts/p6_eval/measure_report.py snapshot --research <id> --report <the run's own report id, `target.report_id` of the start response of step 3> --base http://127.0.0.1:8866
   --db "$RUN/data/library.sqlite" --pairs "$RUN/pairs.json" --out "$RUN/report"` (all paths absolute). The server of the run is left up
   until `snapshot` has written its files; it is not restarted (a restart would let its worker pick up more work). Reading makes no model
   call. A run that stopped early, for any reason of step 2 or 3, goes through `snapshot` with `--stopped <reason>` (`session_cap`,
   `wall_clock_cap`, `counter_unreadable`, `quota`, ...; `snapshot` never fails on an unreadable `--db`, it marks the affected rows
   `not_readable`), also when the backend still shows the run as completed (for example a
   final count at the cap): then only R1 and R7 are measured, no reading is needed and `score` concludes without one.
6. **Read:** the run session fills `review.md` as the analyst (`Reader: analyst`), including R3's missed sentences. Then
   `measure_report.py second --out "$RUN/report"` and a separate Claude Sonnet session (Agent tool, `model: "sonnet"`, given only `second.md`
   and the quoted passages, not the first reader's marks or the expectations; for R9 the sheet itself carries the report claims and the
   input-side equation values) fills `second.md` (`Reader: second`). The owner does not read.
   The server stays up until step 7 has finished; the Sonnet reader reaches the PDF pages with a loopback GET (`curl`). A page that
   cannot be opened at reading time is marked with the sheet's `Page could not be opened (no verdict)` box, never judged from the
   extracted text. Stop the server after step 7.
7. **Score:** `measure_report.py score --out "$RUN/report" [--seeded <P15 results.json, auxiliary only>]`.
8. **Results document** `docs/product/p6-slice1-report-results.md`: one row per metric, taken from `results.json`, set beside the
   frozen range and the "if I see this my assumption is wrong" sentence as `in range`, `out of range` or `not measurable`, with value,
   denominator, sample, readers, and what the run could not read. The expectations file is not edited. Apply the reading rule of the
   expectations file (the three hard rows R2, R3, R4a). State in the first paragraph what this measures: one research, one table, one
   run, one model, model readers unless the owner read.
9. **Decision record** (after the results document, with the next free `D` number checked on `main` after `git pull --rebase`):
   Status/Date/Context/Decision/Limits, numbers from the results document, the two limits above and the kit's `not_readable` list. It
   records what was measured; it does not turn a passing row into "the report kind is good".
10. Commit only `docs/product/p6-slice1-report-results.md`, `docs/decisions.md` and the handoff's "Partiler" line; `.local/` is never
    committed; `git worktree remove ../DEIXIS-p16run` at the end.

## Recorded, and where

Under `.local/p6-eval-2026-09-30/`: `protocol.md`; `expectations.sha256`; `data/` (the copy, with the report run in it);
`server.log`, `poll.log`; `ledger.jsonl` (one line per event: start, poll counts, stop, resume, end, with the model-session count);
`run.json`, `report.json`, `report.md` (export); `report/{snapshot.json,automated.json,review.md,second.md,human.json,results.json}`;
the readers' names and models; `pairs.json`; P15's `results.json` copy if used (auxiliary).

## Limits

- No real-model call outside the one report run (and, on path B, the one fill); the two readers are models and the Sonnet session is
  outside the session cap and counted separately.
- No second run for any reason, including a sample that reads badly. No edit of the expectations after the freeze.
- Do not touch the live library, ports 8765 and 8858-8864, `sw-status.md`, `TODO.md`, `.vscode/`, `scripts/local_index.py`.
- A `methods/` or backend change during the run is out of scope; if the measurement shows a defect, record it and stop.
- Results say what they measure: this is workflow and reading evidence on one report, not report quality in general.
