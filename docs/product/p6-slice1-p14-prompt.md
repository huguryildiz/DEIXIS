<!-- Plan review: gpt-6-sol high; code review: 1 round, verdict düzeltmeyle hazır (its one high was a stale doc snapshot, already fixed) -->
<!-- PLAN-REVIEW-ROUNDS: gpt-6-sol high, 2 rounds: r1 2 high (Download .md is disabled on a paused report so the 409 is checked through the API; the report Cancel has no confirmation dialog), r2 0 high, verdict hazir; all folded in -->

# Task: P6 slice 1, batch P14, Playwright acceptance of the report with a scripted model (plan 1l)

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-p14` (detached at `867376d`: main with P9/D118, P12/D120
export and slice 31/D119, which removed the legacy search workflow, so every new research is `sw`). Read `AGENTS.md`,
`CLAUDE.md`, `.impeccable.md`, `docs/product/p6-slice1-report-run.md` section "1l" (older than the code; where this prompt
differs, this prompt wins), and D113, D115, D116, D118, D120 at the top of `docs/decisions.md`.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change
uncommitted. Do not create files outside the list below. Do not invent; report what you could not find. **No real-model
calls**: the scripted acceptance server only. Do not touch `../DEIXIS-s30`, `../DEIXIS-s31`, `../DEIXIS`, `.local/`,
`TODO.md`, `.vscode/`, `scripts/local_index.py`, `sw-status.md`. Never use ports 8765 or 8858-8864; the report spec's
servers use 8801 (existing) and, for the two new cases, 8802 and 8803. Run Playwright with
`DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance-p14` (never the default directory). Another session (batch P13) is changing
`backend/deixis/workflow/report/sections.py`, `phrasing.py`, `flow.py` and the stored `error_json` of report runs in a
different worktree: this batch changes none of those.

## What is and is not in code (checked on 867376d)

- `plan 1l` as written is mostly done. `apps/web/e2e/report.spec.ts` already has two tests, both driving the real UI
  against `tests/acceptance/fixture_server.py`: (1) `write, read, edit, restore and acknowledge an evidence report`
  (start research, include a source, add a column, fill, readiness panel, Write report, open the report, numbered `[1]`
  citation chips and TABLE I, Copy Markdown and Download .md, review provenance text in three variants, source sheet
  from a chip, edit a claim, 409 conflict keeps the draft, Restore, a cell edit makes a section stale, Keep as is,
  screenshots at 1440 and 390 px in light and dark); (2) `a scripted report review finding appears as a model flag`
  (`[report-review-finding]`).
- `ScriptedCodex.respond()` in `fixture_server.py` already answers `report_plan`, `report_section`,
  `report_phrase_repair` and `report_review` through `valid_response(si)` from `tests/fakes.py`, adds one cell-citing
  claim to a `report_section` output when the section's input holds a filled cell with a stored evidence quote (selection
  gives IV such cells; III and VIII get none) and the section is not VII (VII gets an `insufficient_evidence` entry instead), and adds one
  review finding under `[report-review-finding]`.
- **Not covered, and what this batch adds** (the two cases plan 1l names that no test has yet, plus the paused state
  the plan's step list never reached):
  A. **Assembly refuses a banned word and the report stays a draft.** The plan calls the marker
     `[report-invent-locator]`; that name is wrong (no locator is involved: assembly rule `_check_banned_words` in
     `assembly.py` rejects "gap", "novel" and the like in any claim outside II). Use `[report-banned-word]`.
  B. **A section that comes back empty pauses the run and the screen says so.** `sections.py::_run_section` marks a
     section with neither claims nor `insufficient_evidence` as `draft` with issue `empty_section`; after the round
     `run_report` pauses with `pause_reason = "section_must_be_rewritten"` and `error_json = {"sections": [...]}`.
     The UI already words this in `labels.ts` ("A section must be written again."), `Transcript.tsx` ("IV: must be
     written again") and `ReportView.tsx` ("This section was not validated and must be written again.", header
     "Paused: ..."). Nothing tests it in a browser.
- What the screen shows for an assembly failure is **not known**: `report_view` does not return the assembly issues,
  and the `DRAFT: {n} sections not validated` header counts only sections whose own status is not `valid`, which is 0
  when every section validated and only assembly refused. Observe it first (Decision 4).
- Resuming a run that paused on `section_must_be_rewritten` replays the section's stored succeeded step, so the section
  stays empty; whether and how a section is written again is P13's and later work. **This batch does not test Resume
  to success.**

## Decisions taken (the plan's own default where it has one; own judgement is marked)

1. **Extend, do not rewrite.** Keep tests 1 and 2 as they are (they are the plan's "writing a report produces a
   readable, numbered document" case). Add two tests to `report.spec.ts`, after them, with a `ReportServer` that takes its
   port as a constructor argument (default 8801, so tests 1 and 2 change by nothing but that signature). Each new test
   builds its research through the same steps test 2 uses; extract those steps into one local helper
   `readyResearch(page, server, question)` returning `researchId`, and use it for the two new tests only (leave tests 1
   and 2's inline steps alone, to keep the diff reviewable). Own judgement.
2. **Two new fixture markers, in `ScriptedCodex.respond()` only, applying to `report_section` steps:**
   - `[report-banned-word]`: the fixture's appended cell claim of section IV reads "It has been reported that this
     synthetic table cell records a research gap." (the phrase stays source-stated so only the banned-word rule and
     nothing else can refuse it; check with `assembly.run_assembly_checks` in a throwaway Python call that the only
     error is `banned_word`, and if another rule also errors, change the sentence until only `banned_word` does and say
     what you changed).
   - `[report-empty-section]`: for section IV the fixture returns `claims: []`, `citation_anchors: []`,
     `insufficient_evidence: []` and does **not** append the cell claim (the append step must be skipped for IV under
     this marker, or the section is not empty). Every other section is written as usual.
   Both markers go in the research question, like `[report-review-finding]`. No new `task_type` branches; no change to
   `tests/fakes.py`, fixtures under `tests/fixtures/research/`, contracts or `methods/` (so `skill_package_hash` does not
   move). Update the module docstring's paragraph about report steps with one sentence per marker.
3. **Test A (`[report-banned-word]`), what it asserts.** After Write report the run ends `completed` (the report run
   itself finishes; assembly failure is the report's status, not the run's failure) and:
   - `GET /api/researches/{id}/reports/{report_id}` returns `status: "draft"`, and the run's `error` (the stored
     `error_json`) contains an issue whose `rule` is `banned_word` for section `IV` (read the field name from the
     response; if the run object does not expose it through any API, assert the timeline's "Assembled report" line and
     the header instead and report that the API hides it);
   - the opened report sheet's header starts with `DRAFT` and is not `Evidence report · V1`, and no version number is
     shown for it;
   - Copy Markdown puts a text on the clipboard whose first non-empty line is the draft line P12 writes (read the exact
     text from `report/export.py`; do not hard-code a guess), and the file name of Download .md carries no `-v1`;
   - the Answer tab's report entry says draft, not V1 (`Evidence report · draft`, `i18n.ts`).
   Screenshots: the draft sheet at 1440 px light, 1440 dark, 390 light (use `page.emulateMedia` for the scheme as test 2
   does), each looked at by you.
4. **What test A does with the "0 sections not validated" question (own judgement, the plan's default is silence).**
   If, when you run it, the header reads `DRAFT: 0 sections not validated` (or anything else that hides the assembly
   error), **do not change `apps/web/src` or the backend in this batch.** Write the test to assert only what is true and
   not misleading (status draft via API, header begins with `DRAFT`, no V1, export draft line, run error has the rule),
   record the header wording in the decision's Limits as a known gap ("the screen does not say which assembly rule
   refused the report"), and list it in your final message so the main session can decide on a follow-up. A test that
   pins the misleading `0 sections` wording is not allowed.
5. **Test B (`[report-empty-section]`), what it asserts.** After Write report the run is `paused`, not failed and not
   completed, and:
   - the run's `pause_reason` is `section_must_be_rewritten` and its `error` lists section `IV` (through the runs or
     research API the UI already uses; find the field, do not invent one);
   - the timeline says `Report paused`, its section line says `IV: must be written again`, and the run's Resume and
     Cancel buttons are visible;
   - `GET .../reports` shows a report whose status is not `valid` (assembly did not run: the report is `in_progress`);
     the Answer tab's report entry does not read `Evidence report · V1`;
   - opening the report sheet shows the header `Paused: A section must be written again.` and, inside section IV, the
     notice `This section was not validated and must be written again.`; the Markdown export endpoint, called directly through the API request context, answers 409 (the report is
     unfinished), and the sheet's Copy Markdown and Download .md buttons are disabled (`ReportView.tsx`; do not
     click them, and do not mock a 409 here: test 1 already does that);
   - Cancel from the timeline (the report run's Cancel button sends the request directly, with no confirmation dialog:
     `ResearchView.tsx`; the `Cancel this run?` dialog belongs to table-fill runs only) leaves the timeline saying
     `Report cancelled` and the report still not valid; nothing else runs afterwards.
   Do not click Resume in this test. Screenshots: the paused timeline and the paused sheet at 1440 px light and dark,
   and the paused timeline at 390 px; look at each.
6. **If batch P13 is present on `HEAD` when you start** (check: `grep -n "^## D121" docs/decisions.md` and
   `git log --oneline -3`; the worktree above is at 867376d, where it is not), and it stores the reason a section failed
   in the run's `error_json` or shows it on screen, add one assertion to test B for that reason in the place P13 put it,
   read from P13's decision, not guessed. If it is not present, add none and say P13's failure-reason display is not
   covered. Either way, do not depend on P13's names in code that must pass without it.
7. **Nothing else added.** No test of quota, crash, late result or scope change in the browser (P13's Python tests own
   them); no Turkish-UI report test; no change to readiness gating tests (P10's); no new screenshot naming scheme
   (names: `report-draft-desktop`, `report-draft-dark-desktop`, `report-draft-390`, `report-paused-desktop`,
   `report-paused-dark-desktop`, `report-paused-390`, plus `report-paused-sheet-desktop` and `report-paused-sheet-dark-desktop`).
8. **Decision record.** New `## D122 — ...` at the top of `docs/decisions.md` (or the next free number if D121 is not the
   highest below it after P13 lands; check the file when you write it, D121 belongs to P13) with Status/Date/Context/
   Decision/Limits: what the two new cases show (a scripted model refusing assembly and a scripted empty section; the
   UI states for a draft and a paused report), what they do not (report quality, a real model, Resume to success, the
   header wording gap from Decision 4 if it appeared), and the test counts. Add one line to
   `docs/product/p6-slice1-handoff.md`'s "Partiler" list in the style of the P12 line, ending `commit: <hash>`
   (placeholder; the main session fills it in) and marking `P14` done in the open-batch list line.

## Files allowed

- `apps/web/e2e/report.spec.ts` (two tests, `ReportServer` port argument, `readyResearch` helper, screenshots).
- `tests/acceptance/fixture_server.py` (`ScriptedCodex.respond()` and its module docstring only).
- `docs/decisions.md` (one new entry at the top), `docs/product/p6-slice1-handoff.md` (one line, one status edit).
- This prompt file itself (only to fill in the plan-review comment lines; do not otherwise edit it).

## Files NOT allowed

Everything under `backend/`, `apps/web/src/`, `methods/`, `contracts/`, `tests/fakes.py`, `tests/fixtures/`,
`storage/migrations/`, any other e2e spec, `apps/web/playwright.config.ts`, `package.json`, lockfiles. If a needed
change seems to require one of them, stop that item, record it under Limits and in your final message.

## Checks to run (in the worktree; the worktree needs `npm ci` in `apps/web` or a `node_modules` symlink from the main checkout)

1. `cd apps/web && npm run build && npm run lint` (17 warnings today; no new ones).
2. `DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance-p14 npm run test:acceptance -- report.spec.ts` (the four report tests
   pass), then the whole suite once (`npm run test:acceptance`; 106 passed on 867376d, now 108 expected). A test that
   fails only under the full run: rerun it alone and say so.
3. `PYTHONPATH=backend:. uv run pytest` in full is expected unchanged (the fixture server is not imported by pytest);
   run `PYTHONPATH=backend:. uv run pytest tests/test_report_flow.py tests/test_report_export.py -q` at least, and the
   full run if time allows (one known memory-limit failure is accepted: name it).
4. Screenshots: the eight named in Decision 7 (including test A's three); open each PNG and check text is readable, nothing
   overlaps, dark mode has no light patches, 390 px has no horizontal scroll.

## Report at the end

Files changed; the two markers' exact wording; for test A, the header text you actually saw and whether Decision 4
applied; whether P13 was present; test counts (report spec, full Playwright, pytest); every own judgement; anything you
could not find or could not make pass.
