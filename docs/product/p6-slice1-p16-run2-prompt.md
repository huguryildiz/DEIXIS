# Task: P6 slice 1, batch P16, second attempt (run half), the real-model report measurement on the filled table

Written 30 September 2026 for a later session; derived from `p6-slice1-p16-run-prompt.md` (the first attempt, which stopped at the table: D124) and changed
only where the frozen addendum requires it. Nothing in this file has been run. Frozen documents: `docs/product/p6-slice1-report-expectations.md`
(unchanged, sha256 `31f2666e8f3b15b4b627a6e400f9b983759ae71be484ee6731b55281826b25c7`) and `docs/product/p6-slice1-report-expectations-addendum.md`
(the changed start condition, ranges carried over, the D125 comparison table). The kit is `scripts/p6_eval/measure_report.py`; metrics R1-R11 are defined in
`docs/product/p6-report-design.md` section 13. Read the addendum first; where this prompt and the addendum disagree, stop and say so.

What changes against the first attempt: no fill runs; the report is started from a working copy of the already filled library copy, with the explicit choice
`continue_with_failed` (D125, code commit `97faf6d`); the start checks are the addendum's; R9 pairs are marked before the report; the result is presented as
"a measurement conditional on a table whose fill result was known". Everything else (port 8866, `gpt-5.6-luna` passed explicitly, `DEIXIS_CODEX_HOME`, stop rules,
counter rules, readers, kit commands with the run's own `--report`, one report run) is unchanged.

## Start only if

1. `p6-slice1-report-expectations-addendum.md` is committed on `main` in its own freeze commit and no longer says TASLAK (it says DONDU). If it still says TASLAK, stop and
   say so; do not choose. Its rules (the D125 comparison table, the start checks, the R9 pair rule) stand.
2. `git log -1 --format=%H -- docs/product/p6-slice1-report-expectations-addendum.md` is the freeze commit `<F>`. `git diff --stat 97faf6d <F> -- backend apps/web contracts methods scripts tests`
   is empty (the freeze commit is documentation only) and `sha256sum` of `docs/product/p6-slice1-report-expectations.md` is `31f2666e…b25c7`.
3. `scripts/p6_eval/measure_report.py` and `tests/test_p6_measure_report.py` are unchanged since `cdf79ba` (sha256 prefixes `db203420e4b1`, `7f7d2f0d5004`) and the kit tests pass in
   the run worktree.
4. No other session is using Luna (ask the owner if unsure), no server is bound to port 8866 (`lsof -i :8866`), and no process holds the first attempt's folder open
   (`lsof +D "$RUN1/data"` is empty).
5. The first attempt's folder `RUN1=/Users/huguryildiz/Documents/GitHub/DEIXIS/.local/p6-eval-2026-09-30` exists with `data/library.sqlite` whose sha256 is
   `d8c83eee2b008b50e7d3e1c379ce5d3d9779d494bc7511b766d7c2c542236db8`. If it differs, stop: the filled state is not the one the addendum froze.
6. P15's `results.json` is optional auxiliary context, as in the first prompt: R10 is never measured (`p15_behavior_is_not_r10`).

## Where and how

- **Worktree** pinned at the freeze commit: `git worktree add ../DEIXIS-p16run2 <F>` (detached, from the main checkout). The run does not follow later commits.
  `git diff --stat <F> -- backend apps/web contracts methods scripts tests` must stay empty during the run and is checked at start and at end. Record `<F>`, `git rev-parse 97faf6d`
  and the `skill_package_hash` (from a dry server start in an empty data directory on a free port other than 8866, as in the first attempt) in `protocol2.md`. It must read
  `sha256:08f1bdeadc63b809bdf6d123a1e77889cada14d64d3e851c3d9fe25bfb2704ee`. Record `shasum -a 256 contracts/research/*.schema.json`, and the sha256 of that list, which must
  read `65df8e3cee9d755b295331614d66f659eaa1107ad830523eabe2f98a3891af32`. A difference in either is a stop, not a note.
- **Run folder:** `RUN2=/Users/huguryildiz/Documents/GitHub/DEIXIS/.local/p6-eval-2026-09-30-run2` (absolute, ignored by git, never committed; every command below uses `$RUN2` and `$RUN1`, never a
  relative `.local/...`, because commands run from the worktree). It holds `protocol2.md`, `data/` (the working copy), `server.log`, `poll.log`, the ledger, the sha256 of both frozen
  files, and the kit's outputs. **`$RUN1` is never written to, opened by a server, or repaired.**
- **Working copy, taken from the first attempt's filled copy (not from the live library, no backup/restore, no refill).** `$RUN2` must not exist, not even as a dangling symlink
  (`test ! -e "$RUN2" && test ! -L "$RUN2"`). If it exists, stop without deleting, merging, overwriting or repairing anything and say so. Create it once (`mkdir "$RUN2"`, no `-p`) and copy into the
  absent data path: `cp -Rp "$RUN1/data" "$RUN2/data"`. Before any server starts on the copy, verify that `$RUN2/data` is a separate real directory, `$RUN2/data/library.sqlite` is a regular file (not a symlink),
  the only symlink in the tree is `$RUN2/data/tools` (`find "$RUN2/data" -type l`), pointing to `/Users/huguryildiz/Library/Application Support/DEIXIS/tools` (read only; if the copy turned it into a directory,
  stop), and there is no SQLite sidecar (`library.sqlite-wal`, `-shm`, `-journal`). Any extra symlink or sidecar is a stop. Delete nothing in `$RUN1`. The live service on 8765 is not touched, restarted or queried.
- **Digest of the filled state.** Save the script below as `$RUN2/digest.py` (it opens the file read-only with `mode=ro&immutable=1`; it writes nothing) and run
  `python3 "$RUN2/digest.py" "$RUN1/data/library.sqlite"` and `python3 "$RUN2/digest.py" "$RUN2/data/library.sqlite"`. Both outputs must equal each other and the table of the
  addendum (file sha256, quick_check `ok`, rows 25, columns 7, cells 175, links 219, passages 1417, included 25, `reports` 0, `report_runs_of_research` 0, `active_runs` 0,
  `migration` 57). Write both outputs into `protocol2.md`. Any difference is a stop: the measurement does not start, nothing is repaired, and the results say why.

```python
"""Read-only digest of the filled P16 table state. Usage: python3 digest.py <library.sqlite>"""
import hashlib, json, os, sqlite3, sys

RESEARCH, TABLE = "res_IXBsnzhYZsKByEdTpSJo", "tbl_x8xnc1S4b7ha3WtIJDVU"
path = os.path.abspath(sys.argv[1])
c = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
parts = {
    "quick_check": c.execute("pragma quick_check").fetchall(),
    "rows": c.execute("SELECT source_version_id, removed_at FROM table_rows WHERE table_id=? ORDER BY source_version_id", (TABLE,)).fetchall(),
    "columns": c.execute("SELECT c.id, c.position, c.current_revision, c.removed_at, c.version, r.name, r.instruction, r.answer_format, r.options_json, r.allow_multiple FROM table_columns c JOIN column_revisions r ON r.column_id=c.id AND r.revision=c.current_revision WHERE c.table_id=? ORDER BY c.position, c.id", (TABLE,)).fetchall(),
    "cells": c.execute("SELECT e.id, e.source_version_id, e.column_id, e.current_revision_id, e.version, r.state, r.value_json, r.reading_depth, r.column_revision FROM evidence_cells e LEFT JOIN cell_revisions r ON r.id=e.current_revision_id WHERE e.table_id=? ORDER BY e.id", (TABLE,)).fetchall(),
    "links": c.execute("SELECT l.cell_revision_id, l.passage_id, l.anchor_text, l.anchor_match FROM cell_evidence_links l WHERE l.cell_revision_id IN (SELECT current_revision_id FROM evidence_cells WHERE table_id=?) ORDER BY l.cell_revision_id, l.passage_id, l.anchor_text", (TABLE,)).fetchall(),
    "passages": c.execute("SELECT id, source_version_id, kind, text_sha256 FROM passages WHERE source_version_id IN (SELECT source_version_id FROM table_rows WHERE table_id=? AND removed_at IS NULL) ORDER BY id", (TABLE,)).fetchall(),
    "included": c.execute("SELECT s.source_version_id FROM selections s JOIN corpus_memberships m ON m.research_id=s.research_id AND m.source_version_id=s.source_version_id AND m.removed_at IS NULL WHERE s.research_id=? AND s.state='included' ORDER BY s.source_version_id", (RESEARCH,)).fetchall(),
}
out = {"file_sha256": hashlib.sha256(open(path, "rb").read()).hexdigest()}
for name, rows in parts.items():
    out[name] = {"n": len(rows), "sha256": hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()}
out["reports"] = c.execute("SELECT count(*) FROM reports").fetchone()[0]
out["report_runs_of_research"] = c.execute("SELECT count(*) FROM runs WHERE research_id=? AND kind='report'", (RESEARCH,)).fetchone()[0]
out["active_runs"] = c.execute("SELECT count(*) FROM runs WHERE status IN ('queued','running','pause_requested','paused')").fetchone()[0]
out["migration"] = c.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
print(json.dumps(out, indent=1))
```

- **No foreign work in the copy.** The queries of the digest already require `active_runs` 0. Also check, with `sqlite3` read-only on `$RUN2/data/library.sqlite`: no `person_pdf_requests` row has status
  `waiting` or `planned`, no `run_steps` row has status `running`, and no `pending` run step belongs to a non-terminal run (`queued`, `running`, `pause_requested`, `paused`). All must be zero. `pending` steps attached to
  terminal (`completed`, `cancelled`) runs are expected: the first attempt's copy holds 11 of them (two under cancelled runs, nine `read_equations` steps under a completed fill); they are listed in `protocol2.md` and
  preserved unchanged, because the worker only takes `queued` runs and does not start them. Do not clean or repair the copy. If anything else is found, stop and say so. Write the counts of `runs` by `kind` and
  `status` into `protocol2.md`: at the end, the only new run of the copy may be one `report` run.
- **Port 8866** (`lsof -i :8866` empty; not 8765, not 8858-8864, not 8799).
- **Server environment**, written into `protocol2.md` before the start: `DEIXIS_DATA_DIR=$RUN2/data`; `DEIXIS_CODEX_HOME="$HOME/Library/Application Support/DEIXIS/codex-home"`; every other
  `DEIXIS_*` variable removed (`env -i`-style, keep `PATH` and `HOME`); `DEIXIS_MODEL_CONCURRENCY` left at its default 6.
  `PYTHONPATH=backend:. uv run --no-sync python -m deixis serve --port 8866 --no-browser`, started with `nohup` in the background from the run worktree. The worker starts with the
  server; with zero active runs it has nothing to take.
- **Model: `gpt-5.6-luna`, passed explicitly.** Read `model_connection`, `requested_model`, `reasoning_effort` from `GET /api/researches/res_IXBsnzhYZsKByEdTpSJo` before anything else; they must
  read `codex` / `gpt-5.6-luna` (effort medium). If not, stop; do not change the scope.
- API calls follow `scripts/p6_eval/measure_fill.py`: `GET /api/session`, send the returned token as `x-deixis-csrf` on every non-GET request.

## Steps

1. **Freeze `protocol2.md`** (nothing is started before it exists): `<F>`, `97faf6d`, `skill_package_hash`, schema hashes, sha256 of both frozen files, the research and table ids, the seed
   (20260930) and sample size (30), the readers, the caps, the server environment, the two digest outputs, the run counts, the stop rules copied from the addendum and the expectations file.
2. **Start checks through the API, then the R9 pairs (no fill runs).** `GET /api/researches/res_IXBsnzhYZsKByEdTpSJo/tables` must show for `tbl_x8xnc1S4b7ha3WtIJDVU`:
   `report_ready.ready` false, `cells_left` 21, `failed_rows` 3, `failed_cells` 21, `included_rows` 25, `can_continue_with_failed` true. Save the response into `$RUN2`. Any other value is a
   stop (the state is not the one the addendum froze); no refill, recheck, source removal or cell edit is done to change it. Then write `pairs.json` at
   `$RUN2/pairs.json` (`[{"source_key", "formulation"}]`), **dated and before the report starts**, marked from the "Denklem" column of the filled table. Only completed rows are eligible:
   never `Nandi12`, `Zaman20` or `Sankarasub03`. If no pair can be marked, write `[]` and R9 is "not measurable" as frozen. `pairs.json` is never changed afterwards. Append the addendum
   record to `protocol2.md`: table id, rows, columns, filled cells (168 with a revision, 129 with a value), rows with PDF text.
3. **Start one report run:** `POST /api/researches/res_IXBsnzhYZsKByEdTpSJo/reports` with `{"table_id": "tbl_x8xnc1S4b7ha3WtIJDVU", "continue_with_failed": true}` and the idempotency key
   `p16-run2-report-1`. The response must be a run with `target.continue_with_failed` true and a `target.report_id`; a refusal (409 or any other error) is a stop, recorded as it is:
   nothing else is tried. Poll `GET /api/researches/{id}` every 15 seconds and count the `model_sessions` rows of the copy whose `run_id` is the report run's id (`sqlite3` with `mode=ro`;
   never older sessions) on every poll. Stop at the report session cap (60) or the wall-clock cap (90 minutes) from the report request, under these counter rules: (a) if the count cannot be read on a
   poll (sqlite error, missing file, malformed row), cancel the run through the API at once and record it; do not go on without a count; (b) 15-second polling is not a hard limit: calls in flight at the
   poll that finds the cap reached, and sessions that finish after the cancel, are counted and written in the ledger as `over_cap_in_flight`, and the final count is read once more after the run has stopped;
   (c) after the last research step, a final count at or above the cap is a stop, not a pass; (d) a stop for any of these reasons is a stop, not a failure of the measurement: the run goes to R1 and R7
   only. Do not edit a cell, add a PDF, answer the queue, remove a row, rewrite a section or resume a section by hand. Stop rules as frozen: quota or rate limit stops; one `client_timeout` resumes once
   after 10 minutes; any other `model_call_failed` stops; never another model or connection. A paused run is resumed only for `client_timeout`, once. A model call for any run other than the report run,
   or a new `table_fill` or `table_columns` run, is a stop.
4. **When the run ends or stops:** save `GET /api/researches/{id}` (the run, its steps, its `error`), the report view and the Markdown export into `$RUN2`; keep the export's HTTP status and response body as they are (a 409 on an unfinished report is recorded, not retried or repaired). If no report run was created, skip steps 5 to 7 and record R1-R11 as not measured. **Do not stop the server yet** (step 5's
   `snapshot` reads through its API, and the readers of step 6 open PDF pages through it); check the frozen diff is still empty; re-run the run counts of the copy (the only new run is the one `report` run).
5. **Measure:** from the run worktree,
   `PYTHONPATH=backend:. uv run --no-sync python scripts/p6_eval/measure_report.py snapshot --research res_IXBsnzhYZsKByEdTpSJo --report <target.report_id of step 3's response> --base http://127.0.0.1:8866 --db "$RUN2/data/library.sqlite" --pairs "$RUN2/pairs.json" --out "$RUN2/report"`
   (absolute paths). The server is left up until `snapshot` has written its files; it is not restarted. Reading makes no model call. A run that stopped early for any reason of step 3 goes through
   `snapshot --stopped <reason>` (`session_cap`, `wall_clock_cap`, `counter_unreadable`, `quota`, ...), also when the backend still shows it as completed: then only R1 and R7 are measured, no reading is needed and
   `score` concludes without one. Then the manual checks of the addendum, made read-only from `$RUN2/report/snapshot.json` and the frozen snapshot in it (`db_evidence.frozen_snapshot.failed_rows` gives the three
   source-version ids): (i) the **D125 exclusion count**: how many claims, evidence links, references, gap bases and equation origins of the report point to `srv_f50KBd51bx2a3WXc4O9N`, `srv_4e2Ih9Uf2SOJMGCpwr2u`
   or `srv_IUBsxswhzFoCRiacU9Mn` (Table I listing the three rows with the `failed` flag is expected and does not count); (ii) the **product note**: whether the report view carries `missing_rows`, whether the Markdown
   export carries the missing-rows note immediately after the title and report-version line, whether VIII's eighth item names the three sources with reasons, and whether II states 25 included / 22 completed / 3 failed / 21 of 175 cells missing separately. (iii) the **failure statements**: every sentence of II, VIII or elsewhere that describes a failed row is compared against the stored `failed_rows` records and marked as stating that the row did not complete and was excluded (fine) or as turning the failure into a claim of absence in the source (recorded as an error; it does not change R3's N or U). Write all
   into `$RUN2/report/manual_checks.md` before the readers start; a check that needs evidence that is not available (no frozen snapshot because the run stopped before it, an unreadable `db_evidence`) is recorded as `not_readable`, never with an inferred value. For a stopped run, run `snapshot --stopped <reason>`, skip step 6 and go to `score`. They are recorded as such, not as R-rows.
6. **Read:** the run session fills `review.md` as the analyst (`Reader: analyst`), including R3's missed sentences. R3's primary N and U keep the kit's definition, including its `no_evidence_given` exclusion; failure-only statements of II and VIII are not added to N/U, no cell basis is manufactured and no kit output is altered. They are checked separately against the stored `failed_rows` records and written into `manual_checks.md` (the addendum's R3 row).
   Then `measure_report.py second --out "$RUN2/report"` and a separate Claude Sonnet session (Agent tool, `model: "sonnet"`, given only `second.md` and the quoted passages, not the first reader's marks, not the
   addendum, not the expectations; for R9 the sheet carries the report claims and the input-side equation values) fills `second.md` (`Reader: second`). The owner does not read. The server stays up until step 7 has
   finished; the Sonnet reader reaches PDF pages with a loopback GET (`curl`). A page that cannot be opened is marked with the sheet's `Page could not be opened (no verdict)` box, never judged from extracted text.
   Stop the server after step 7.
7. **Score:** `measure_report.py score --out "$RUN2/report" [--seeded <P15 results.json, auxiliary only>]`.
8. **Results document** `docs/product/p6-slice1-report-results-run2.md` (the first results document is not edited): one row per metric, taken from `results.json`, set beside the frozen range and its
   "if I see this my assumption is wrong" sentence as `in range`, `out of range` or `not measurable`, with value, denominator, sample, readers, and what the run could not read. Apply the reading rule of the
   expectations (hard rows R2, R3, R4a) and the addendum's D125 comparison table (R3 with the frozen kit definition and the failure-statement check kept separate; R11 without the three missing rows; R7 without the fill's 36 sessions). State
   in the first paragraph: one research, one table, one run, one model, model readers unless the owner read; the table's fill result (3 failed rows) was known before the report and the report was written with
   those rows excluded, so the result is "a measurement conditional on a table whose fill result was known". Add the manual checks (exclusion count, product note, failure statements against `failed_rows`) as a separate short section.
9. **Decision record** in `docs/decisions.md` (the next free `D` number checked on `main`, see step 10; D125 is the highest at the time of writing): Status/Date/Context/Decision/Limits, numbers from the
   results document, the limits of the addendum and the kit's `not_readable` list. It records what was measured; it does not turn a passing row into "the report kind is good".
10. Keep the measurement worktree detached at `<F>`; do not pull or rebase it. After measurement and scoring, prepare and commit only `docs/product/p6-slice1-report-results-run2.md`, `docs/decisions.md` and the handoff's "Partiler" line
    in the main checkout (preserving unrelated uncommitted changes there), and run `git pull --rebase` there only when its state permits it, then determine the next free decision number. `.local/` is never committed. Remove the
    measurement worktree (`git worktree remove ../DEIXIS-p16run2`) only after verifying that the results commit is retained on `main`.

## Recorded, and where

Under `$RUN2`: `protocol2.md`; `expectations.sha256` and `addendum.sha256`; `digest.py` and both digest outputs; the saved tables response; `data/` (the working copy, with the report run in it); `server.log`, `poll.log`;
`ledger.jsonl` (one line per event with the model-session count); `run.json`, `report.json`, `report.md`; `pairs.json`; `report/{snapshot.json,automated.json,review.md,second.md,human.json,results.json,manual_checks.md}`;
the readers' names and models; P15's `results.json` copy if used.

## Limits

- No real-model call outside the one report run; the two readers are models and the Sonnet session is outside the session cap and counted separately. No fill, recheck or refill of any row.
- No second run for any reason, including a sample that reads badly. No edit of the expectations or the addendum after the freeze.
- Do not touch the live library, ports 8765 and 8858-8864, `$RUN1`, `sw-status.md`, `TODO.md`, `.vscode/`, `scripts/local_index.py`.
- A `methods/` or backend change during the run is out of scope; if the measurement shows a defect, record it and stop.
- Results say what they measure: workflow and reading evidence on one report written with three rows excluded, not report quality in general and not the quality of a report over a fully filled table.
