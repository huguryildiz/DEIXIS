<!-- reviewer: Opus 5.5 high (Sol quota out), Sol re-review pending. Plan and code written by the Sonnet orchestrator subagent itself (no Sol implementation); Opus 5.5 high code review 1 round, 0 high, verdict "düzeltmeyle hazır", fixes folded in. -->

# Task: P6 slice 5, batch X5, the "Download LaTeX" button on the report screen, its strings, the Playwright test and the design-note status line (no model, no network, no backend change)

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-x5` (detached at `af01d87`, which is `origin/main`
with slice 5 X1 (D153), X2 (D151), X3 (D155) and X4 (D158) and slice 4 E3 (D156) on top). Read `AGENTS.md`, `CLAUDE.md`,
`.impeccable.md` (required before touching `apps/web`), `docs/product/p6-slice5-latex-export.md` (this batch is its section 11
"X5"; section 8 and decisions Q8 and Q15 bind it) and D158, D156 and D149 at the top of `docs/decisions.md`. Read also
`docs/product/p6-slice5-x4-prompt.md` (same style). Where this prompt differs from the note, this prompt wins and says so.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change
uncommitted. Do not invent; report what you could not find or could not make pass. No real-model call, no network, no
provider call. Do not touch `../DEIXIS`, `../DEIXIS-h0c`, other worktrees, `.local/`, `TODO.md`, `.vscode/`,
`scripts/local_index.py`, `sw-status.md`, the live data directory, ports 8765 and 8858-8864. The Playwright fixture server
uses port 8801 (`report.spec.ts`); use another port for any extra script of your own.

## What is and is not in code (checked on af01d87)

- Present (X4, D158), read-only here: `GET /api/researches/{id}/reports/{report_id}/export?format=latex`. 200
  `application/zip`, `Content-Disposition: attachment; filename="report-<slug>-v<n>-latex.zip"` (or `…-draft-latex.zip`;
  a first version matches `^report-.*-v1-latex\.zip$`), and `X-Deixis-Export-Notes: <total note count>` as ASCII digits.
  404, 409 ("The report is still being written" and every `RevisionConflict` from `to_latex`) and 422 are JSON
  `{"detail": ...}` with no `Content-Disposition` and no notes header. Same origin through the Vite proxy and through the
  backend that serves `dist/`, so the page can read both headers without a CORS expose list.
- Present: the Markdown export in `apps/web/src/api.ts::reportMarkdown`, the "Copy Markdown" and "Download .md" buttons in the
  `ReportView.tsx` toolbar (`SheetHeader.report-toolbar`), `report.css` (`@media(max-width:600px)` hides
  `.report-export-label` so that only the icon remains), the toast (`useToast`, one at a time, tones `success`, `warning`,
  `error`; errors stay until dismissed), and the Playwright export test in `apps/web/e2e/report.spec.ts` (Markdown copy,
  Markdown download name, a 409 that raises no download).
- Not in code: `api.reportLatex`, any LaTeX button, any `LaTeX` string in `i18n.ts`, any e2e step for the zip. The
  acceptance fixture server needs no scripted case: a finished report exports through the real route, and the notes count
  is exercised by rewriting the response header in the test (`route.fetch()` then `route.fulfill`).

## Decisions taken (the note's own default where it has one; own judgement is marked)

1. **Client (note section 8).** `api.reportLatex(id, reportId) -> { blob, filename, notes }`. Error handling is shared with
   `reportMarkdown` through one small `exportError(response)` (own judgement: the four lines would otherwise be copied;
   `reportMarkdown` behaves as before). The filename comes from `Content-Disposition` with the same strict pattern
   (`[a-zA-Z0-9._-]+`), fallback `report-latex.zip`. `notes` is the header when it matches `^\d+$`, else 0 (own judgement:
   a missing or malformed header on a 200 is not expected after X4; it must not raise an error or hide the file).
2. **Button.** A third ghost `Button` after "Download .md": lucide `FileCode` icon, label "Download LaTeX" in
   `.report-export-label` (hidden under 600 px by the existing rule, so no CSS change), `aria-label` "Download LaTeX".
   `FileCode` rather than `Download` (own judgement): at narrow width only icons remain and two identical download icons
   would not tell the zip from the `.md`. Same disabled rule as the Markdown buttons: no report, run not finished, or
   report `in_progress`, and while an export is running; the same `title` text when blocked. Own judgement: the long
   condition is now a `const exportBlocked` used by all three buttons instead of a third copy.
3. **Download.** `saveBlob(blob, filename)` (object URL, temporary `<a download>`, revoke on the next tick) is extracted from
   the Markdown branch and used by both (own judgement: same reason as 1). No new dependency, no `components/ui` change.
4. **Toast (Q8, note section 8).** Exactly one toast per export. Notes 0: `success`, "LaTeX downloaded: a zip with the .tex
   and .bib files." Notes 1: `warning`, "LaTeX downloaded with 1 export note. It is listed in a comment block at the top of
   the .tex file." Notes 2 to 20: `warning`, "LaTeX downloaded with {n} export notes. They are listed in a comment block at
   the top of the .tex file." Notes above 20: `warning`, "... The first 20 are listed in a comment block at the top of the
   .tex file." (the `.tex` lists at most 20 and says "and N more"; the constant is `LATEX_NOTES_LISTED = 20`). The
   success toast is not shown in addition to the warning. The export notes are not described further in the toast (own
   judgement: the comment block names them; the toast must not claim more than the count).
5. **Errors.** A non-2xx response (409 the report is still being written, 404, 422) raises `ApiError`; the catch shows the
   server's `detail` in an `error` toast, as the Markdown path does, and no download starts (the blob is only read after
   `response.ok`).
6. **Strings.** All through `t()`; Turkish entries sit after "Markdown downloaded." in `i18n.ts`: "Download LaTeX" /
   "LaTeX indir", and the four toast strings. English is the key.
7. **Decision number (own judgement).** D160 (renumbered at commit; D159 went to P9 H0c) follows D158 on `origin/main` at `af01d87`; the main session
   renumbers when it commits (the other chats also write decisions).

## Files allowed

`apps/web/src/api.ts`, `apps/web/src/report/ReportView.tsx`, `apps/web/src/i18n.ts`, `apps/web/e2e/report.spec.ts`,
`docs/product/p6-report-design.md` (section 12 item 5 status line), `docs/decisions.md` (the D160 entry), this prompt.
`apps/web/src/report/report.css` only if the narrow layout needs it (it did not). `tests/acceptance/fixture_server.py` is not
in the list and is not needed. No backend, migration, `methods/`, contract or `skill_package_hash` change.

## Tests

`apps/web/e2e/report.spec.ts`, inside the existing report test, after the Markdown 409 step:

- Success: click "Download LaTeX"; the download name matches `^report-.*-v1-latex\.zip$`; the file starts with the zip
  signature `PK` (a signature only; the two correct files are pinned by the backend tests of X4); the real response
  header `x-deixis-export-notes` (captured with `waitForResponse`) matches `^\d+$`; the toast agrees with it (success when 0,
  warning when above 0).
- Notes: for header values 3, 1 and 25, rewrite the real response with `route.fetch()` and `route.fulfill`; one download
  each, exactly one `.toast` in the page, a `warning` toast with the text of decision 4.
- 409: `route.fulfill` with status 409 and `{"detail": "The report is still being written"}`; an `error` toast with that
  text and no new download event.

## Checks

- `cd apps/web && npm run build && npm run lint` (17-warning baseline, no new warning).
- `DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance-x5 npm run test:acceptance` against that fresh build; report the total.
- Full `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest`. Known to be flaky under load: the `test_audit`
  stratum and the `test_builtin_embedding_flow` 429 wait; rerun such a file alone and say so.
- Screenshots read by the orchestrator, light and dark, at 1440 and 390 px: the toolbar with the new button (label at 1440,
  icon only at 390), the keyboard focus ring on it, Enter and Space each starting a download, the success toast, a warning
  toast with notes, a Turkish warning toast at 390, no horizontal scroll at 390. The focus ring was not captured in light
  at 390 px (captured in light at 1440 and in dark at 1440 and 390).
- `git diff --check`.

Done when: build and lint without a new warning, the acceptance suite green, the button usable and its focus visible at both
widths and in both themes, strings present in both languages, the status line and the D160 entry written, and no file outside
the list changed.
