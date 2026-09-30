<!-- PLAN-REVIEW-ROUNDS: gpt-6.1-sol high, 2 rounds: r1 3 high (VIII's eighth item fails the strict step-input schema; resume was blocked by the live readiness check before the stored snapshot; two existing tests conflict with the new rules) plus 4 medium, all folded in; r2 0 high, verdict hazir, one medium (test that a flagged save_snapshot refuses a not-ready table and writes nothing) folded in -->

# Task: P6 slice 1, batch P17, write a report with failed rows

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-p17` (detached at `1466a1f`). Read `AGENTS.md`,
`CLAUDE.md`, `.impeccable.md` (before touching `apps/web`), `docs/product/p6-report-design.md` sections 4-6,
`docs/product/p6-slice1-report-results.md`, and D112-D124 at the top of `docs/decisions.md` (D124 is why this batch
exists). The joint decision of Claude and gpt-6.1-sol that this batch implements is summarized under "Why" below.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change
uncommitted. Do not invent; report what you could not find. **No real-model calls**: fake models and the scripted
acceptance server only. Do not touch `../DEIXIS`, `.local/`, `TODO.md`, `.vscode/`, `scripts/local_index.py`,
`sw-status.md`. Never use ports 8765 or 8858-8864. Playwright runs with `DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance-p17`
and the ports your new spec picks must not collide with the existing specs (grep `apps/web/e2e` for the ports in use).
Tests need `PYTHONPATH=backend:.` and possibly `UV_CACHE_DIR=/tmp/deixis-uv-cache`. The worktree needs `npm ci` in
`apps/web` (or a `node_modules` symlink from `../DEIXIS/apps/web/node_modules`; remove it when you are done).

## Why

In the P16 real measurement (D124) the evidence table of `res_IXBsnzhYZsKByEdTpSJo` ended with 25 included sources, seven
columns, 175 cells: 22 sources completed, three not (two sources with no stored text, whose 14 cells hold a system
`inaccessible` revision, and one source whose only extraction call failed, so its 7 cells have no revision at all). So
21 of 175 cells are missing and `report_ready` is false, and no report could start. `tables.py::report_ready` already
has a `continue_with_failed` parameter, but nothing passes it: not `request_report`, not the API, not the screen. The
design note (section 6) foresees the owner continuing with failed rows. This batch connects that explicit choice to
the report path **without weakening any evidence rule**.

## What is and is not in code (checked on 1466a1f)

- In code: `tables.py::report_ready(store, research_id, table_id, continue_with_failed=False)` returns
  `{"ready", "missing": [{source_version_id, column_id}], "failed_rows": [source ids]}`. A row is failed when it is an
  active included row, has at least one missing cell, and every one of its missing cells is a recorded failure: the
  cell's current state is `inaccessible`, or a `model:cell_extraction` step of a `table_fill` run of this scope revision
  has status `failed`/`outcome_unknown` for the batch that holds the column. `ready` with the flag is true when every
  missing item belongs to a failed row. **Gap:** it does not require one completed row, so "every row failed" would
  pass; and nothing reports why a row failed.
- `TableStore.tables()` puts `report_ready: {ready, cells_left, cells_total, failed_rows: <count>}` on each table summary.
- `ReportStore.request_report(research_id, table_id, idempotency_key)` refuses when `not readiness["ready"]` with
  `RevisionConflict("Include sources and fill every active evidence-table column before starting a report")`; the run
  target is `{"table_id", "report_id"}`. `POST /api/researches/{id}/reports` takes `StartReport {table_id}`.
- `sections.py::run_report` calls `report_ready(...)` (no flag) and `flow._fail(run_id, "table_not_ready", readiness)`,
  then `reports.save_snapshot(report_id, table_id)`, which builds the snapshot in the same transaction and returns an
  existing snapshot on resume (so resume already uses the stored snapshot; keep that).
- `snapshot.py::build_snapshot` freezes `rows` (every included active source), `cells` (current revision of every cell of
  those rows), `columns`, `corpus {found, unique, screened, included, full_text}`. Readers of the snapshot: `selection.py`
  (`snapshot["rows"]` for the source list), `gaps.py` (cells), `assembly.py` (rows at ~313, ~390, ~419; cells elsewhere),
  `review.py` (cells), `store.py::evidence_changes` (rows and cells), `review_methodology.py` (corpus; II is
  code-written, VIII's `limitations_core` is code-written numbers), `views.py::report_view` (Table I from
  `frozen["rows"]`/`cells`), `export.py::to_markdown` (Table I and headers), `sections.py` (plan passages from rows).
- Web: `api.ts` `TableSummary.report_ready` type; `EvidenceTable.tsx` (toolbar "Write report", disabled with the reason
  "A report needs a filled evidence table: {n} cells left"); `report/ReportReadiness.tsx` (the readiness panel that lists
  ready tables and otherwise says "A report needs a filled evidence table"); `report/ReportView.tsx` (report header and
  provenance paragraph); strings in `i18n.ts`.
- Not in code: any way to choose to continue with failed rows; failed-row detail with reasons; a snapshot that records
  failed rows; II/VIII wording about them; any screen text about missing rows.

## Fail-closed rules (these bind everything below; each needs a test)

1. **Default stays false.** Without the explicit choice, behavior, refusal message and stored records of every existing
   path are byte-for-byte unchanged (do not add keys to a snapshot, a run target, or a section's numbers when no choice
   was made and no failed row exists; existing tests must pass unchanged except where they assert the exact
   `report_ready`/`TableSummary` dict shape, which may gain the new keys named below).
2. **The choice is stored on the run and reaches the runner's second readiness check.** `StartReport` gets
   `continue_with_failed: bool = False`. `request_report(..., continue_with_failed=False)` stores it in the run target
   (`{"table_id", "report_id", "continue_with_failed": true}`; write the key only when true) and calls
   `report_ready(..., continue_with_failed=...)`. `run_report` reads it from `run["target"]` and passes it to its own
   `report_ready` call, and `save_snapshot` receives it too. No migration is needed for this (the target is JSON); if you
   find you need one, the next number is `0058` and you must say why.
3. **Continuing is possible only when every missing cell comes from a recorded failed or inaccessible cell.** An untried
   cell (missing, no `inaccessible` state, no failed/outcome_unknown step covering it) blocks; a row that is not an active
   included row blocks. **Also block when no row is completed** ("all rows failed"): with the flag, `ready` requires at
   least one included row that is not failed (and, as today, at least one included source and one column).
4. **Readiness and snapshot come from one consistent moment, on the flagged path only.** `save_snapshot` (new signature
   `save_snapshot(report_id, table_id, continue_with_failed=False)`): an existing snapshot is returned first, unchanged,
   with no readiness check (resume uses the stored snapshot). For a new snapshot with `continue_with_failed=True` it
   re-runs `report_ready(..., True)` inside its own transaction and builds the snapshot from that same result (the
   failed-row detail comes from it); if not ready it raises `RevisionConflict` (`run_report` fails the run with
   `table_not_ready`). With `continue_with_failed=False` it does exactly what it does today, no new check (the default
   path stays byte-for-byte; `tests/test_report_store.py` saves snapshots of tables that are not ready and must keep
   passing unchanged).
   **Resume of a flagged run does not re-check the live table.** In `run_report`, when the run's target has
   `continue_with_failed` true and a snapshot already exists for the report, skip the live `report_ready` check and use
   the stored snapshot (a column or source added after the snapshot must not strand the resume). A run without the flag
   keeps today's order (live check first) whatever exists.
5. **The snapshot keeps all included sources and freezes the failed rows separately.** When failed rows exist (only
   then), the snapshot gets:
   - `rows`: unchanged (every included source, failed ones too; a failed row's `reading_depth` is null);
   - `cells`: the current-revision cells of **completed rows only** (this is how failed rows stay out of every reader of
     `cells`: selection, gaps, assembly member/citation/absence-basis checks, review, change detection);
   - `failed_rows`: one entry per failed row, in `rows` order:
     `{"source_version_id", "source_key", "title", "missing_columns": [{"column_id", "name", "reason"}],
     "reason", "existing_cells": [{"cell_id", "cell_revision_id", "column_id", "state"}]}`. `reason` per missing column is
     `no_stored_text` when the cell's current state is `inaccessible`, else the `error_code` of the failed step that
     covers it (`extraction_failed` when it has none); the row's `reason` is the first missing column's reason.
     `existing_cells` keeps the existing `inaccessible` revisions (id, revision id, state) as provenance; it carries no
     value and no quote;
   - `row_counts`: `{"included", "completed", "failed", "cells_total", "cells_missing"}` (`cells_total` = included rows
     times active columns, `cells_missing` = length of `readiness["missing"]`).
   **No value, anchor, evidence link or artificial cell revision is written or invented for a cell without a revision.**
   `corpus` (found, unique, screened, included, full_text) is unchanged, so the PDF ratio keeps the included-source
   denominator. Add `snapshot.evidence_row_ids(snapshot)` (rows minus failed) and use it wherever code decides which
   sources the model may see or cite: `selection.select_evidence`, the plan-passages loop in `run_report`, and
   assembly's three `rows`-based source sets. A snapshot stored without `failed_rows` (all existing ones) behaves as
   before (`.get("failed_rows", [])`).
6. **Failure is never counted as `not_found`.** Failed rows are out of the model's content evidence, of the
   aggregation denominators (gap candidates use only `cells`, so they exclude failed rows; verify that
   `gaps.generate_corpus_absence_candidates` and assembly's absence-basis check at ~509 cannot count a failed row's cell)
   and of absence candidates. Add a test where three completed full-text rows plus one failed row exist and the failed
   row changes no candidate or count.
7. **Section II** (code-written, `review_methodology.py`) separates four numbers when failed rows exist: included
   sources, completed rows, failed rows, missing cells of total. `numbers["rows"] = {"included", "completed", "failed",
   "cells_missing", "cells_total"}` (only when failed rows exist) and one extra sentence appended to the rendered text
   (English and Turkish, next to the existing templates), e.g. EN: "Of the {included} included sources, {completed} have
   a completed evidence-table row and {failed} do not ({cells_missing} of {cells_total} table cells are missing); rows
   that did not complete are left out of the report's evidence." The found/unique/screened/included/full_text figures
   and `full_text_ratio` stay as they are. The assembly corpus-count checks are unchanged.
8. **Section VIII** (`limitations_core`) gets one more item, appended after the existing seven so their numbers do not
   move, only when failed rows exist: key `failed_rows`, text naming each failed source (`source_key`, else title) with
   its reason in words (`no_stored_text` -> "no stored text"; any other code shown as its code with underscores as
   spaces), in English and Turkish, and a `numbers["failed_rows"]` list `[{source_version_id, name, reason}]`. VIII's
   text stays rendered by `render_limitations` from the items, and the "limitations_text_drift" check keeps working
   unchanged. **This needs a contract change and it is allowed:** `contracts/research/step-input.schema.json` describes
   `limitations_core` strictly (exactly seven items, item number at most seven, fixed keys, no extra properties; the
   numbers are passed to the VIII model call, so an unknown item fails as `step_input_invalid`). Widen only that
   sub-schema, backward compatibly: allow one more item with key `failed_rows` and number 8 (`minItems`/`maxItems`
   seven or eight; the eighth is valid only with key `failed_rows`), and an optional top-level `failed_rows` property
   (array of `{source_version_id, name, reason}`). A limitations_core with seven items and no `failed_rows` must still
   validate, so `tests/fixtures/research/*` and `tests/fakes.py` need no change (if they do, stop and report). Add
   a validation test for both shapes and for a bad eighth item. `methods/` is not changed (VIII's claims only reference
   item numbers already); if you conclude the instructions must change, stop and report instead. Report whether
   `skill_package_hash` moved (it should not: `contracts/` is not in the method package; check).
9. **The screen and the outputs say what is missing.**
   - `TableSummary.report_ready` gains `can_continue_with_failed: bool` and `failed_cells: int` (`failed_rows` stays the
     row count), and `included_rows: int`; computed from `report_ready(..., continue_with_failed=True)` (the same
     function, one call), and `ready` remains the default-choice answer.
   - When `ready` is false and `can_continue_with_failed` is true, the readiness panel (`ReportReadiness.tsx`) and the
     table toolbar (`EvidenceTable.tsx`) show, before the choice: "{n} of {m} sources did not complete the table
     ({cells} cells are missing). These rows will not be used in the report's evidence assessment or in its counts."
     (use the plan's wording where it fits the surrounding copy: "25 kaynağın 3'ünde tablo doldurma tamamlanmadı; 21 hücre
     eksik. Bu satırlar raporun kanıt değerlendirmesine ve toplulaştırma paydalarına alınmayacak." is the Turkish source
     text; the English UI string is yours, plain and exact) and a button **"Write the report with missing rows"** that
     calls `api.startReport(..., { continueWithFailed: true })`. The ordinary "Write report" button is not shown in that
     state (it would be refused); when `ready` is true nothing changes.
   - The report screen (`ReportView.tsx`, header area, not only the provenance paragraph) shows a note when the report's
     snapshot has failed rows: how many rows and cells are missing and that those rows were left out; `report_view`
     returns `missing_rows: {"counts": row_counts, "failed_rows": [{source_version_id, source_key, title, reason,
     missing_columns}]}` (null when the snapshot has none). Table I marks a failed row's cells as missing (the existing
     "—" for a cell not in `cells`) and `table_i.rows` gets `failed: true` for those rows.
   - `export.py::to_markdown` writes the same note (English and Turkish) under the title block and lists the failed
     sources with reasons; without failed rows the Markdown is unchanged.
   - Add every new UI string to `i18n.ts` (Turkish too, if the file carries Turkish strings) and `labels.ts` if the reason
     codes need labels.
10. **Anchor, phrase, assembly and review checks are unchanged.** Do not edit `assembly.py` rules, the contracts, the
    citation resolution or `phrasing.py`, except the three `rows`-set lines named in rule 5.

## Files allowed

(Also allowed: `contracts/research/step-input.schema.json`, only the `limitations_core` sub-schema as rule 8 says;
`tests/test_report_snapshot.py` line ~94 and its neighbors, see "Existing tests" below.)

Backend: `backend/deixis/workflow/tables.py` (`report_ready`, `tables()`), `workflow/report/store.py` (`request_report`,
`save_snapshot`; `evidence_changes` is NOT changed: a failed source leaving the table stays a corpus change on purpose), `workflow/report/snapshot.py`, `workflow/report/selection.py`, `workflow/report/sections.py`,
`workflow/report/assembly.py` (only the rows-based source sets), `workflow/report/review_methodology.py`,
`workflow/report/export.py`, `workflow/views.py` (`report_view` only), `api/app.py` (`StartReport`, `start_report`).
Web: `apps/web/src/api.ts`, `EvidenceTable.tsx`, `report/ReportReadiness.tsx`, `report/ReportView.tsx`,
`report/report.css` (only if a note needs a style; reuse existing classes first), `i18n.ts`, `labels.ts`.
Tests: new `tests/test_report_failed_rows.py`; edits to existing pytest files only where a dict shape assertion needs the
new keys; `apps/web/e2e/report.spec.ts` or a new `apps/web/e2e/report-failed-rows.spec.ts` (prefer the new file);
`tests/acceptance/fixture_server.py` (one new marker, see Tests). Docs: `docs/decisions.md` (Orchestrator writes D125;
you do not), this prompt file untouched.

## Files NOT allowed

`methods/`, `contracts/`, `tests/fakes.py`, `tests/fixtures/`, `storage/migrations/` (unless rule 2's exception applies and
you report it), `flow.py`, `phrasing.py`, `review.py`, `plan.py`, other e2e specs, `package.json`, lockfiles, the
Playwright config. If a needed change seems to require one of them, stop that item and report.

## Existing tests

Two existing tests conflict with the rules, one intentionally. `tests/test_report_snapshot.py` (~line 94) asserts that
`report_ready(..., continue_with_failed=True)` is true when the only included row failed; rule 3 makes that false
("all rows failed" blocks). Change that test to add one completed row (so it still proves the flag's positive path) and
add the all-failed case as a new assertion; say so in your report. No other existing test may be edited except to add the
new optional keys to an exact-dict assertion. `tests/test_report_store.py` must pass unchanged.

## Tests to add (fake models only)

Backend (`tests/test_report_failed_rows.py`; build the table state with the store the way `tests/test_report_snapshot.py`
and the fill tests do, using a fake adapter; no network):
1. `report_ready` default: with a failed row, `ready` is false; `continue_with_failed=True`: true.
2. Untried cell in one row (missing, no state, no failed step) plus a failed row: flag true still blocks.
3. All included rows failed: flag true blocks.
4. `request_report` without the flag refuses (same message as today); with the flag creates the run whose target holds
   `continue_with_failed` true; the API `POST /reports` with `{"table_id", "continue_with_failed": true}` returns 202 and
   without the field refuses as today.
5. `run_report` uses the stored choice: a run created with the flag proceeds through the snapshot; the same table with a
   run created without it (created directly with the store) fails `table_not_ready`.
6. Snapshot: `rows` has all included sources, `cells` none of a failed row's, `failed_rows` has id, name, missing columns
   with reasons (`no_stored_text` for an `inaccessible` row, the step's error code for a failed extraction), the existing
   `inaccessible` revision ids under `existing_cells`, `row_counts` right; no new cell revision or evidence link exists
   after the snapshot (count rows in `cell_revisions` and `cell_evidence_links` before and after).
7. A snapshot without failed rows has no `failed_rows`/`row_counts` key and equals what `build_snapshot` returned before
   this batch (compare with a stored older-shaped dict).
8. Selection and gaps: a failed row's source ids appear in no passage, cell or `truncated` record `select_evidence` returns (it returns `passages`, `cells`, `truncated`, not a sources list); the three-completed-plus-one-
   failed absence test of rule 6; assembly refuses a claim citing a failed row's source with the existing rule.
9. II text and numbers contain the four separate numbers; the full-text ratio still uses the included denominator; VIII has
   the eighth item naming the sources with reasons; without failed rows II and VIII are byte-identical to today's output
   (existing tests cover that; add one explicit assertion).
10. A full `run_report` with a fake model over a table with failed rows ends `completed`, report status valid or draft as
    the fake dictates, `report_view["missing_rows"]` is set, `table_i.rows[*].failed` is right, and the Markdown export
    contains the note and the failed source names with reasons (English and Turkish).
11. Resume: pause a flagged run after the snapshot, then change the live table in two ways (fill a failed row's cell;
    and, in a second case, add a new column so live readiness would be false) and resume; the run does not fail with
    `table_not_ready`, the stored snapshot is used (its `failed_rows` unchanged). A non-flagged run keeps today's order.
12. A partly filled failed row (some columns hold `value` or `not_found_in_inspected_scope`, one column's batch failed;
    use more columns than one extraction batch, or a second failed column) is failed as a whole: none of its existing
    cells is in `snapshot["cells"]`, in any `select_evidence` cells, in gap candidates, or in the `report_plan`,
    `report_section` and `report_review` StepInputs the fake adapter receives (capture them; the failed source's
    id and passages appear in none of them, neither in `passages`, `report_target.cells`, `sources` nor the allowlists).
13. Backward compatibility: a stored snapshot without `failed_rows`/`row_counts` (an older-shaped dict built by hand or
    from `build_snapshot` before your change) is read by `selection`, `gaps`, assembly, `report_view`, `evidence_changes`
    and the export exactly as before.
15. A flagged `save_snapshot` on a table that is not ready (for instance an untried cell) raises `RevisionConflict` and writes no snapshot row and no `report_snapshot_saved` event; a non-flagged call on the same table behaves as today.
14. `freeze_plan`'s word budget for a flagged run uses the snapshot's completed-row count (`row_counts.completed`), not
    the live table's row count: in `run_report` pass `snapshot.get("row_counts", {}).get("completed", <today's value>)`.
    Test both (flagged: completed count; no failed rows: today's value).

Browser (Playwright, scripted server): add one marker to `tests/acceptance/fixture_server.py::ScriptedCodex`,
`[fill-fails-one-row]`: for `cell_extraction`, the model output for **one** fixed source (choose deterministically, e.g.
the second source in the call order, or by title) is invalid in a way the existing flow records as a failed step (read how
`[model-down]` or the failure scripts make a step fail, and reuse that; document the marker in the module docstring);
every other extraction succeeds. The spec: start research with the marker, include sources, build a table, fill; the
readiness panel and toolbar say how many rows and cells are missing and offer "Write the report with missing rows" (the
plain "Write report" is not offered); click it; the report run completes; the report header note names the missing
rows and cells; Copy Markdown / the export shows the note; screenshots at 1440 and 390 px in light and dark of the choice
state and of the opened report (names: `report-missing-choice-*`, `report-missing-sheet-*`). Also assert through the API
that a `POST` without the flag is refused with 409/conflict-style status for this table (read the real status code).

## Checks to run (in the worktree)

1. `PYTHONPATH=backend:. uv run pytest` in full (parallel default; one known failure is accepted:
   `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`; a test that fails only under
   parallel load: rerun it alone and say so).
2. `cd apps/web && npm run build && npm run lint` (17 warnings baseline, no new ones).
3. `DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance-p17 npm run test:acceptance -- <your spec>` then the whole suite once
   (108 passed before this batch; expect 109 or 110). A test that fails only under the full run: rerun alone and say so.
4. Screenshots: open each PNG and check text is readable, nothing overlaps, dark mode has no light patches, 390 px has no
   horizontal scroll.

## Report at the end

Files changed; whether a migration was needed and why; the exact English strings you chose for the screen note, the
choice button and the II and VIII sentences; the pytest, build, lint and Playwright counts; every own judgement (marker
choice, reason mapping, where the note sits); anything you could not find, could not make pass, or think a rule above gets
wrong.
