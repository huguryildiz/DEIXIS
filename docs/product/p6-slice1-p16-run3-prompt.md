# Task: P6 slice 1, batch P16, third and last attempt (run half), the real-model report measurement on the filled table

Written 30 September 2026 for a later session; derived from `p6-slice1-p16-run2-prompt.md` (the second attempt, which stopped at section IV: D126) and changed
only where the frozen second addendum requires it. Nothing in this file has been run. Frozen documents: `docs/product/p6-slice1-report-expectations.md`
(unchanged, sha256 `31f2666e8f3b15b4b627a6e400f9b983759ae71be484ee6731b55281826b25c7`), `docs/product/p6-slice1-report-expectations-addendum.md`
(first addendum, unchanged, sha256 `4770f1a6c4da61ff7055e1f00c2e91847f1533c4bb072b47be43f4a97c658ce9`) and `docs/product/p6-slice1-report-expectations-addendum-2.md`
(the last-attempt rule, the changed product, the new hashes, the D127 comparison table). The kit is `scripts/p6_eval/measure_report.py`; metrics R1-R11 are defined in
`docs/product/p6-report-design.md` section 13. Read both addenda first; where this prompt and an addendum disagree, stop and say so.

**Last-attempt rule (verbatim from addendum 2, binding on every step below):** "Üçüncü P16 girişimi bu ölçüm dizisinin son girişimidir; yalnız bir yeni rapor koşusu açılır. Yalnız `client_timeout` için mevcut tek sürdürme hakkı uygulanır. Başka duruşta müdahale veya dördüncü girişim yapılmaz; tamamlanmaya bağlı ölçütler ‘ölçülemedi’ olarak kapanır, elde edilen R1/R7 korunur."

What changes against the second attempt: the product is `14a6e6f` (D127: per-step citation handles in the four report tasks, output ids checked against the shown evidence), so `skill_package_hash` and the allowed code diff change;
the working copy is a **new independent copy of the first attempt's report-free filled copy** (not of the second attempt's folder); the R9 pairs are the second attempt's `pairs.json`, byte for byte; there are two added manual records
(the saved-input exclusion rule, the id-issue record); the result is presented as "a development measurement on a product fixed after an observed failure, conditional on the same known corpus". Everything else (port 8866,
`gpt-5.6-luna` passed explicitly, `DEIXIS_CODEX_HOME`, stop rules, counter rules, readers, kit commands with the run's own `--report`, one report run, `continue_with_failed`) is unchanged.

## Start only if

1. `p6-slice1-report-expectations-addendum-2.md` is committed on `main` in its own freeze commit and no longer says TASLAK (it says DONDU). If it still says TASLAK, stop and
   say so; do not choose. Its rules (the last-attempt rule, the D127 comparison table, the R9 pair rule, the added records) and those of the first addendum stand.
2. `git log -1 --format=%H -- docs/product/p6-slice1-report-expectations-addendum-2.md` is the freeze commit `<F>`. `git merge-base --is-ancestor 14a6e6f <F>` succeeds;
   `git diff --stat 14a6e6f <F> -- backend apps/web contracts methods scripts tests` is empty (the freeze commit is documentation only); `git diff 15bb131 14a6e6f -- backend apps/web contracts methods scripts tests | shasum -a 256`
   is `4185cb2db05d79bc0566cbbfb330f29836fb98ffa4c27eb8490001f863e95413`; `sha256sum` of `docs/product/p6-slice1-report-expectations.md` is `31f2666e…b25c7` and of
   `docs/product/p6-slice1-report-expectations-addendum.md` is `4770f1a6…58ce9`.
3. `scripts/p6_eval/measure_report.py` and `tests/test_p6_measure_report.py` are unchanged since `cdf79ba` (sha256 prefixes `db203420e4b1`, `7f7d2f0d5004`) and the kit tests pass in
   the run worktree.
4. No other session is using Luna (ask the owner if unsure), no server is bound to port 8866 (`lsof -i :8866`; the second attempt's server must be stopped: if it is running, stop and say so, do not kill it), and no process holds the
   first or the second attempt's folder open (`lsof +D "$RUN1/data"` and `lsof +D "$RUN2/data"` are empty).
5. The first attempt's folder `RUN1=/Users/huguryildiz/Documents/GitHub/DEIXIS/.local/p6-eval-2026-09-30` exists with `data/library.sqlite` whose sha256 is
   `d8c83eee2b008b50e7d3e1c379ce5d3d9779d494bc7511b766d7c2c542236db8`. If it differs, stop: the filled state is not the one the addenda froze. `RUN2=/Users/huguryildiz/Documents/GitHub/DEIXIS/.local/p6-eval-2026-09-30-run2`
   exists and holds `pairs.json` whose sha256 is `2037d99376c0d341b75b0e39dbe3f179a09ed121863d0ed567ca4970231c7b96`; it is used only to copy that file (read only). Nothing else of `$RUN2` is used, opened by a server, cleaned or written.
6. P15's `results.json` is optional auxiliary context, as in the first prompt: R10 is never measured (`p15_behavior_is_not_r10`).

## Where and how

- **Worktree** pinned at the freeze commit: `git worktree add ../DEIXIS-p16run3 <F>` (detached, from the main checkout). The run does not follow later commits.
  `git diff --stat 14a6e6f -- backend apps/web contracts methods scripts tests` (against the worktree's HEAD `<F>`) must stay empty during the run and is checked at start and at end. Record `<F>`, `git rev-parse 14a6e6f`
  and the `skill_package_hash` (from a dry server start in an empty data directory on a free port other than 8866, as in the earlier attempts) in `protocol3.md`. It must read
  `sha256:52775258f530aa6a51513488f2aea37d0b7e609ffebe23d06451fd8ef0ae81ac`. Record `shasum -a 256 contracts/research/*.schema.json`, and the sha256 of that list, which must
  read `65df8e3cee9d755b295331614d66f659eaa1107ad830523eabe2f98a3891af32`. Record the sha256 of `git diff 15bb131 14a6e6f -- backend apps/web contracts methods scripts tests`, which must read
  `4185cb2db05d79bc0566cbbfb330f29836fb98ffa4c27eb8490001f863e95413`. A difference in any of them is a stop, not a note.
- **Run folder:** `RUN3=/Users/huguryildiz/Documents/GitHub/DEIXIS/.local/p6-eval-2026-09-30-run3` (absolute, ignored by git, never committed; every command below uses `$RUN3`, `$RUN2` and `$RUN1`, never a
  relative `.local/...`, because commands run from the worktree). It holds `protocol3.md`, `data/` (the working copy), `server.log`, `poll.log`, the ledger, the sha256 of the frozen
  files, and the kit's outputs. **`$RUN1` and `$RUN2` are never written to, opened by a server, cleaned or repaired.**
- **Working copy, a new independent copy of the first attempt's report-free filled copy (not of `$RUN2`, not from the live library, no backup/restore, no refill).** `$RUN3` must not exist, not even as a dangling symlink
  (`test ! -e "$RUN3" && test ! -L "$RUN3"`). If it exists, stop without deleting, merging, overwriting or repairing anything and say so. Create it once (`mkdir "$RUN3"`, no `-p`) and copy into the
  absent data path: `cp -Rp "$RUN1/data" "$RUN3/data"`. Before any server starts on the copy, verify that `$RUN3/data` is a separate real directory, `$RUN3/data/library.sqlite` is a regular file (not a symlink),
  the only symlink in the tree is `$RUN3/data/tools` (`find "$RUN3/data" -type l`), pointing to `/Users/huguryildiz/Library/Application Support/DEIXIS/tools` (read only; if the copy turned it into a directory,
  stop), and there is no SQLite sidecar (`library.sqlite-wal`, `-shm`, `-journal`). Any extra symlink or sidecar is a stop. Delete nothing in `$RUN1` or `$RUN2`. The live service on 8765 is not touched, restarted or queried.
- **Digest of the filled state.** Save the script below as `$RUN3/digest.py` (it opens the file read-only with `mode=ro&immutable=1`; it writes nothing) and run
  `python3 "$RUN3/digest.py" "$RUN1/data/library.sqlite"` and `python3 "$RUN3/digest.py" "$RUN3/data/library.sqlite"`. Both outputs must equal each other and the table of the
  first addendum (file sha256, quick_check `ok`, rows 25, columns 7, cells 175, links 219, passages 1417, included 25, `reports` 0, `report_runs_of_research` 0, `active_runs` 0,
  `migration` 57). Write both outputs into `protocol3.md`. Any difference is a stop: the measurement does not start, nothing is repaired, and the results say why.

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

- **No foreign work in the copy.** The queries of the digest already require `active_runs` 0. Also check, with `sqlite3` read-only on `$RUN3/data/library.sqlite`: no `person_pdf_requests` row has status
  `waiting` or `planned`, no `run_steps` row has status `running`, and no `pending` run step belongs to a non-terminal run (`queued`, `running`, `pause_requested`, `paused`). All must be zero. `pending` steps attached to
  terminal (`completed`, `cancelled`) runs are expected: the first attempt's filled copy holds 11 of them (two under cancelled runs, nine `read_equations` steps under a completed fill); they are listed in `protocol3.md` and
  preserved unchanged, because the worker only takes `queued` runs and does not start them. Do not clean or repair the copy. If anything else is found, stop and say so. Write the counts of `runs` by `kind` and
  `status` into `protocol3.md`: at the end, the only new run of the copy may be one `report` run.
- **Port 8866** (`lsof -i :8866` empty; not 8765, not 8858-8864, not 8799).
- **Server environment**, written into `protocol3.md` before the start: `DEIXIS_DATA_DIR=$RUN3/data`; `DEIXIS_CODEX_HOME="$HOME/Library/Application Support/DEIXIS/codex-home"`; every other
  `DEIXIS_*` variable removed (`env -i`-style, keep `PATH` and `HOME`); `DEIXIS_MODEL_CONCURRENCY` left at its default 6.
  `PYTHONPATH=backend:. uv run --no-sync python -m deixis serve --port 8866 --no-browser`, started with `nohup` in the background from the run worktree. The worker starts with the
  server; with zero active runs it has nothing to take.
- **Model: `gpt-5.6-luna`, passed explicitly.** Read `model_connection`, `requested_model`, `reasoning_effort` from `GET /api/researches/res_IXBsnzhYZsKByEdTpSJo` before anything else; they must
  read `codex` / `gpt-5.6-luna` (effort medium). If not, stop; do not change the scope.
- API calls follow `scripts/p6_eval/measure_fill.py`: `GET /api/session`, send the returned token as `x-deixis-csrf` on every non-GET request.

## Steps

1. **Freeze `protocol3.md`** (nothing is started before it exists): `<F>`, `14a6e6f`, `skill_package_hash`, schema hashes, the sha256 of the allowed code diff, sha256 of the three frozen files (expectations, addendum, addendum 2) and of `pairs.json`, the research and table ids, the seed
   (20260930) and sample size (30), the readers, the caps, the server environment, the two digest outputs, the run counts, the stop rules copied from the last-attempt rule (verbatim), the addenda and the expectations file.
2. **Start checks through the API, then the R9 pairs (no fill runs).** `GET /api/researches/res_IXBsnzhYZsKByEdTpSJo/tables` must show for `tbl_x8xnc1S4b7ha3WtIJDVU`:
   `report_ready.ready` false, `cells_left` 21, `failed_rows` 3, `failed_cells` 21, `included_rows` 25, `can_continue_with_failed` true. Save the response into `$RUN3`. Any other value is a
   stop (the state is not the one the addenda froze); no refill, recheck, source removal or cell edit is done to change it. Then the R9 pairs: **no new marking.** Copy the second attempt's pairs file byte for byte:
   `cp "$RUN2/pairs.json" "$RUN3/pairs.json"` (read only on the `$RUN2` side), **dated and before the report starts**, and verify its sha256 is `2037d99376c0d341b75b0e39dbe3f179a09ed121863d0ed567ca4970231c7b96`.
   Verify, read-only on `$RUN3/data/library.sqlite`, that each pair's `source_key` is one of the 22 completed rows (never `Nandi12`, `Zaman20` or `Sankarasub03`) and write the id, current revision and value of that source's "Denklem" cell into `protocol3.md`.
   The `formulation` field is a descriptive label frozen in the second attempt: **no verbatim match against the cell is required or attempted** (none of the seven occurs verbatim). R9 eligibility stays the unchanged kit rule (an equation displayed in the input the model was given).
   A pair whose source is not a completed row is a stop; no pair is added, removed or edited. `pairs.json` is never changed afterwards. Append the addendum record to `protocol3.md`: table id, rows, columns,
   filled cells (168 with a revision, 129 with a value), rows with PDF text.
3. **Start one report run** (the only new report run of this attempt; the last-attempt rule governs every stop below): `POST /api/researches/res_IXBsnzhYZsKByEdTpSJo/reports` with `{"table_id": "tbl_x8xnc1S4b7ha3WtIJDVU", "continue_with_failed": true}` and the idempotency key
   `p16-run3-report-1`. The response must be a run with `target.continue_with_failed` true and a `target.report_id`; a refusal (409 or any other error) is a stop, recorded as it is:
   nothing else is tried. Poll `GET /api/researches/{id}` every 15 seconds and count the `model_sessions` rows of the copy whose `run_id` is the report run's id (`sqlite3` with `mode=ro`;
   never older sessions) on every poll. Stop at the report session cap (60) or the wall-clock cap (90 minutes) from the report request, under these counter rules: (a) if the count cannot be read on a
   poll (sqlite error, missing file, malformed row), cancel the run through the API at once and record it; do not go on without a count; (b) 15-second polling is not a hard limit: calls in flight at the
   poll that finds the cap reached, and sessions that finish after the cancel, are counted and written in the ledger as `over_cap_in_flight`, and the final count is read once more after the run has stopped;
   (c) after the last research step, a final count at or above the cap is a stop, not a pass; (d) a stop for any of these reasons is a stop, not a failure of the measurement: the run goes to R1 and R7
   only, R2-R6, R8, R9 and R11 close as "not measurable", and no fourth attempt is made or proposed. Do not edit a cell, add a PDF, answer the queue, remove a row, rewrite a section or resume a section by hand. Stop rules as frozen: quota or rate limit stops; one `client_timeout` resumes once
   after 10 minutes; any other `model_call_failed` stops; never another model or connection. A paused run is resumed only for `client_timeout`, once, through the product's resume. **The stop reason is taken from the root cause in the stored step and session error records, not from the outer `pause_reason`:** a section call's timeout is recorded as `model_call_failed` and the run is then paused as `section_failed`; if, whatever the outer code, every stop cause is `client_timeout`, the right is unused and the caps are not exceeded, resume once after 10 minutes; with any other or mixed cause (for example `unknown_passage_id`), a quota or load stop, `budget_exhausted`, a second `client_timeout`, the run is **not** resumed, repaired or restarted (addendum 2, last-attempt rule); an already paused or terminal run is not cancelled and its backend status is left as it is, while a run that is still running is ended only by the measurement-ending cancel below, and the run goes to `snapshot --stopped <reason>`. **Freezing the records:** if a stop cause other than the permitted `client_timeout` resume is found while the run is still running (for example a phrase-repair call failure after which the product goes on), cancel it through the API, solely to end the measurement; this is not a repair, retry or rewrite. Freezing is **not** defined by stored steps leaving the `running` label (on a rate-limit or cancel path the product can leave a step `running`): the measurement observer (the run's driver script, set up before the run, changing no product file) records when the report execution stopped; after that record and a zero count of `model_sessions.status='started'` are verified, re-read the final counter and error records once, then take the single `snapshot --stopped <reason>` and `score`; readers are not started. Persistent `running` step or section records are not changed and are recorded separately. If the end of execution cannot be verified (a started session still runs after a bounded wait), no "final state" claim is made and R1/R7 are labelled "state at record time". R7's main duration keeps the frozen `created_at`/`updated_at` definition (on the cancel path: up to the cancel record); the times of detecting the cause, of the cancel and of the last session's end go into a separate record and the closing wait is not added to R7. **Monitoring reads more than the run's top-level status:** on every poll and at the final evaluation also read the report run's step and session error records, the sections' validations and `review.reason`; a call failure that falls under a stop rule is evaluated through `snapshot --stopped <reason>` (readers not started) even if the product continued or completed (phrase repair records a call failure as an exception and goes on; the final review may keep a valid report after `model_call_failed`). Permitted schema repairs and structural pattern exceptions are not mixed up with provider call failures. A model call for any run other than the report run,
   or a new `table_fill` or `table_columns` run, is a stop.
4. **When the run ends or stops:** save `GET /api/researches/{id}` (the run, its steps, its `error`), the report view and the Markdown export into `$RUN3`; keep the export's HTTP status and response body as they are (a 409 on an unfinished report is recorded, not retried or repaired). If no report run was created, skip the measurement actions of steps 5 to 7, apply the common close after step 7, go to step 8 and record R1-R11 as not measured. **Do not stop the server yet** (step 5's
   `snapshot` reads through its API, and the readers of step 6 open PDF pages through it); check the frozen diff is still empty; re-run the run counts of the copy (the only new run is the one `report` run).
5. **Measure:** from the run worktree,
   `PYTHONPATH=backend:. uv run --no-sync python scripts/p6_eval/measure_report.py snapshot --research res_IXBsnzhYZsKByEdTpSJo --report <target.report_id of step 3's response> --base http://127.0.0.1:8866 --db "$RUN3/data/library.sqlite" --pairs "$RUN3/pairs.json" --out "$RUN3/report"`
   (absolute paths). The server is left up until `snapshot` has written its files; it is not restarted. Reading makes no model call. A run that stopped early for any reason of step 3 goes through
   `snapshot --stopped <reason>` (`session_cap`, `wall_clock_cap`, `counter_unreadable`, `quota`, ...), also when the backend still shows it as completed: then only R1 and R7 are measured, no reading is needed and
   `score` concludes without one. Then the manual checks of the addendum, made read-only from `$RUN3/report/snapshot.json` and the frozen snapshot in it (`db_evidence.frozen_snapshot.failed_rows` gives the three
   source-version ids): (i) the **D125 exclusion count** (addendum 2 replaces the second attempt's "no stored input mentions a failed source" rule with: the three source-version ids and their 101 passage ids occur in no stored step input's `passages`, `sources`, `allowlist`, `report_target.cells`, `report_target.gap_candidates`, `report_target.plan` or `report_target.columns`, and only in `report_target.limitations_core.failed_rows` and display-only review fields; read from the stored step inputs, `not_readable` if unavailable): how many claims, evidence links, references, gap bases, equation origins and count members of the report point to `srv_f50KBd51bx2a3WXc4O9N`, `srv_4e2Ih9Uf2SOJMGCpwr2u`
   or `srv_IUBsxswhzFoCRiacU9Mn` (Table I listing the three rows with the `failed` flag is expected and does not count); (ii) the **product note**: whether the report view carries `missing_rows`, whether the Markdown
   export carries the missing-rows note immediately after the title and report-version line, whether VIII's eighth item names the three sources with reasons, and whether II states 25 included / 22 completed / 3 failed / 21 of 175 cells missing separately. (iii) the **failure statements**: every sentence of II, VIII or elsewhere that describes a failed row is compared against the stored `failed_rows` records and marked as stating that the row did not complete and was excluded (fine) or as turning the failure into a claim of absence in the source (recorded as an error; it does not change R3's N or U). (iv) the **id-issue record** (addendum 2, descriptive, not an R-row, no claim about handles): for each report step (plan, sections, abstract, index terms, phrase repair, review), read from the stored sessions and step records, read-only, how many id issue codes (`unknown_passage_id`, `unknown_cell_id`, `unknown_source_id`, `unknown_column_id`) appeared, in which field (claim, anchor, count, gap, equation origin, plan), and whether they survived the one repair; state for each figure whether it comes from the raw model output (handles) or the stored result (real ids). If R1a, R1b or R1c is out of range or the run stopped because of a section, record per section whether the cause is the older class (claim passage/cell membership, equation-origin passage membership: both existed at `15bb131`) or a D127 section-level membership check (citation anchors, count fields, gap bases, nearest match: new); use the issue code and field path together, and record the plan's existing membership codes too (the code list is not limiting). Write all
   into `$RUN3/report/manual_checks.md` before the readers start; a check that needs evidence that is not available (no frozen snapshot because the run stopped before it, an unreadable `db_evidence`) is recorded as `not_readable`, never with an inferred value. For a stopped run, run `snapshot --stopped <reason>`, skip step 6 and go to `score`. They are recorded as such, not as R-rows.
6. **Read:** the run session fills `review.md` as the analyst (`Reader: analyst`), including R3's missed sentences. R3's primary N and U keep the kit's definition, including its `no_evidence_given` exclusion; failure-only statements of II and VIII are not added to N/U, no cell basis is manufactured and no kit output is altered. They are checked separately against the stored `failed_rows` records and written into `manual_checks.md` (the addendum's R3 row).
   Then `measure_report.py second --out "$RUN3/report"` and a separate Claude Sonnet session (Agent tool, `model: "sonnet"`, given only `second.md` and the quoted passages, not the first reader's marks, not the
   addendum, not the expectations; for R9 the sheet carries the report claims and the input-side equation values) fills `second.md` (`Reader: second`). The owner does not read. The server stays up until step 7 has
   finished; the Sonnet reader reaches PDF pages with a loopback GET (`curl`). A page that cannot be opened is marked with the sheet's `Page could not be opened (no verdict)` box, never judged from extracted text.
   Stop the server after step 7.
7. **Score:** `measure_report.py score --out "$RUN3/report" [--seeded <P15 results.json, auxiliary only>]`.
   **Common close, on every path (completed, stopped early, no report created):** after the needed records and, where they apply, `snapshot` and `score` are written, stop only the measurement server that this attempt started (its PID is recorded in `protocol3.md`; port 8866 is then free). A paused run is not resumed and the database is not modified by the close.
8. **Results document** `docs/product/p6-slice1-report-results-run3.md` (the first two results documents are not edited): one row per metric, taken from `results.json`, set beside the frozen range and its
   "if I see this my assumption is wrong" sentence as `in range`, `out of range` or `not measurable`, with value, denominator, sample, readers, and what the run could not read. Apply the reading rule of the
   expectations (hard rows R2, R3, R4a) and both addenda's comparison tables (R3 with the frozen kit definition and the failure-statement check kept separate; R11 without the three missing rows; R7 without the fill's 36 sessions and without the second attempt's 7 sessions; the D127 shifts of addendum 2). State
   in the first paragraph: one research, one table, one new run, one model, model readers unless the owner read; the table's fill result (3 failed rows) and the second attempt's stop were known before the report and the report was written with
   those rows excluded, so the result is **"a development measurement on a product fixed after an observed failure, conditional on the same known corpus"**. Right after it, set the three attempts side by side (D124: no report started; D126: one run stopped at section IV;
   this run: what happened) without counting them as three report runs. On success write only that the report completed on this sample; do not write that handles caused it, that the report is good in general, or anything about another corpus (those need an independent corpus). On a stop write R1 and R7 as obtained, the rest as not measurable, and no proposal for a fourth attempt (an open question for the owner only). If the attempt stopped at the start or no report run was created, write "third attempt: report not started; new report runs 0; no reader; R1-R11 not measured"; use "one new run" only when the run was really created and "the report was written with those rows excluded" only for the content that exists. Add the manual checks (exclusion count, product note, failure statements against `failed_rows`, id-issue record) as a separate short section.
9. **Decision record** in `docs/decisions.md` (the next free `D` number checked on `main`, see step 10; D127 is the highest at the time of writing, so D128 unless a later one exists): Status/Date/Context/Decision/Limits, numbers from the
   results document, the limits of the addendum and the kit's `not_readable` list. It records what was measured; it does not turn a passing row into "the report kind is good", keeps D124 and D126 standing and does not hide the earlier stops.
10. Keep the measurement worktree detached at `<F>`; do not pull or rebase it. After measurement and scoring, prepare and commit only `docs/product/p6-slice1-report-results-run3.md`, `docs/decisions.md` and the handoff's "Partiler" line
    in the main checkout (preserving unrelated uncommitted changes there), and run `git pull --rebase` there only when its state permits it, then determine the next free decision number. `.local/` is never committed. Remove the
    measurement worktree (`git worktree remove ../DEIXIS-p16run3`) only after verifying that the results commit is retained on `main`.

## Recorded, and where

Under `$RUN3`: `protocol3.md`; `expectations.sha256`, `addendum.sha256` and `addendum2.sha256`; `digest.py` and both digest outputs; the saved tables response; `data/` (the working copy, with the report run in it); `server.log`, `poll.log`;
`ledger.jsonl` (one line per event with the model-session count); `run.json`, `report.json`, `report.md`; `pairs.json`; `report/{snapshot.json,automated.json,review.md,second.md,human.json,results.json,manual_checks.md}`;
the readers' names and models; P15's `results.json` copy if used.

## Limits

- No real-model call outside the one report run; the two readers are models and the Sonnet session is outside the session cap and counted separately. No fill, recheck or refill of any row.
- No second run for any reason, including a sample that reads badly, and **no fourth attempt** (addendum 2). No edit of the expectations or either addendum after the freeze, and no range adjusted after a result is known.
- Do not touch the live library, ports 8765 and 8858-8864, `$RUN1`, `sw-status.md`, `TODO.md`, `.vscode/`, `scripts/local_index.py`.
- A `methods/` or backend change during the run is out of scope; if the measurement shows a defect, record it and stop.
- Writing to, cleaning, repairing or starting a server on `$RUN1` or `$RUN2` is forbidden. Permitted read-only uses: for `$RUN1`, the hash and digest checks and the copy; for `$RUN2`, only verifying and copying `pairs.json`.
- Results say what they measure: workflow and reading evidence on one report written with three rows excluded, not report quality in general and not the quality of a report over a fully filled table.
