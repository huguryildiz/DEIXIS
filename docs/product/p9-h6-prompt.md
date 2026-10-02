<!-- PLAN-REVIEW-ROUNDS: round 1 düzeltmeyle hazır (2 yüksek, 5 orta, 5 düşük); round 2 düzeltmeyle hazır (0 yüksek, 3 orta, 7 düşük); all folded in, no round 3 needed; reviewer: Opus 5.5 high (Sol quota out), Sol re-review pending; gpt-6.1-sol returned a usage-limit error on 2 October 2026 (until 3 October 2026 20:39). Code review rounds 1-4: 1, 0, 1, 0 high (Opus 5.5 high) -->

# Task: P9 batch H6, accessibility audit (axe scan, keyboard walk, reduced motion, 200% zoom)

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-h6`, detached at `89285fe` (main with D160). Plan: `docs/product/p9-hardening-plan.md`
§3.5, §4 rule 2 and rows X01 to X07, §5 "H6", §9 S3, §10. Read `AGENTS.md`, `CLAUDE.md` and `.impeccable.md` (all of it, §9 and §11 above all)
before touching `apps/web`. **No git state-changing commands** (no add, commit, stash, checkout, reset, clean, restore). No real-model call, no
provider call. Do not touch port 8765, ports 8858 to 8864, the live data directory, `TODO.md`, `.vscode/`, `scripts/local_index.py`, `.local/`
of any other checkout, `sw-status.md`, or the other worktrees (`../DEIXIS`, `../DEIXIS-h0d`, `../DEIXIS-h1`). No backend, migration,
`methods/`, contract or fixture-server change. No new runtime UI dependency. Do not invent; report what you could not find or measure.

## Why

Nothing in the repository scans the interface for accessibility defects (plan §3.5: "no automatic scanner, no screen reader pass, no real
contrast measure, no 200% zoom"). `.impeccable.md` §9 states the rules (focus ring, `role=grid`, combobox/listbox, `role=status/alert`,
`aria-hidden` icons, 4.5:1 contrast, reduced motion), and 49 `.tsx` files use `aria-*` or `role`, but none of it is measured. P9 cannot close
with a serious or critical accessibility defect open (plan §4 rule 2), and "no serious or critical axe finding" is required, not just
recorded (X01 to X04).

## What is and is not in code on 89285fe

In code: `apps/web/src` (React 19, Tailwind 4, base-ui); theme is a `deixis-theme` value in `localStorage` (`light`, `dark`, else follows
`prefers-color-scheme`), shown as a `dark` class on `<html>`, toggled by the button named "Use dark theme" / "Use light theme"; the main
breakpoint is 760 px (drawer sidebar, one-column rows, full-width report sheet); `index.css` has one global `prefers-reduced-motion: reduce`
block (animation and transition duration .01 ms, one iteration, `scroll-behavior: auto`) plus blocks in `EvidenceTable.css`, `workspace.css`,
`report/report.css`, `ResearchView.tsx`; script-driven scrolls use `scrollBehavior()` from `motion.ts`. 142 Playwright tests pass (`acceptance.spec.ts` and 17
other specs under `apps/web/e2e`), each spawning `tests/acceptance/fixture_server.py` (real app, scripted model, SYNTHETIC records) on its
own port; lint is at 17 warnings. Existing keyboard coverage: 24 `press` calls in `acceptance.spec.ts`, the evidence grid arrow keys, the
human queue Tab order, `report.spec.ts`.

Not in code: `@axe-core/playwright` (not in `apps/web/package.json`), any accessibility spec, a zoom or reduced-motion test, a VoiceOver
record, a known-issues record. `docs/product/p9-acceptance-record.md` does not exist yet (H8 creates it).

## Decisions (the plan's own defaults; do not ask the owner)

1. **Dependency (S3: yes).** `@axe-core/playwright` as a `devDependency` only, installed with `npm install --save-dev @axe-core/playwright`
   in `apps/web` (so `package.json` and `package-lock.json` change, nothing else). `npm ci` must work afterwards from a clean
   `node_modules`. No change to `dependencies`, to `vite.config.ts`, or to the shipped bundle: record the `npm run build` output sizes before
   adding the devDependency and again right after adding it, before any `src` fix, so a size change caused by a fix is not
   mistaken for one caused by the dependency.
2. **One new spec, `apps/web/e2e/a11y.spec.ts`**, same style as the existing specs (own fixture server class, own `DEIXIS_ACCEPTANCE_DIR`
   output, SYNTHETIC records, scripted model). Ports: use a block that no spec uses. Specs use 8777 to 8808 today (before the full suite run `lsof -i :8777-8830`: it must be empty, because a fixture's `start()` accepts
   any server that answers `/api/health` on its port, so another worktree's server on the same port would be measured instead of yours;
   the new spec waits for its own child process with the `exitCode` check pattern of `report-edit.spec.ts:21-24`) (grep `e2e/*.ts` for
   `FixtureServer(`, `Server(` and `PORT =` again before choosing; other worktrees may add specs). Use 8820 and up, never 8765 or 8858
   to 8864.
3. **Frozen screen list for X01 to X04** (frozen here, before any scan; add nothing after you see results, and record any screen you could not
   reach as "not reached" with the reason, never silently drop it). Each screen is scanned in four states: light 1280x900 (X01), dark
   1280x900 (X02), light 390x844 (X03), dark 390x844 (X04). Screens:
   1. Home, new research (empty composer; also with the source-scope list open).
   2. Research screen after search and screening, tab Sources (a row open with the exclude-reason form, as in case D).
   3. Research screen, tab Answer, before an answer exists and after one is generated (the report artifact button is visible).
   4. Two different surfaces share the class `.report-sheet`; scan both as separate screens. 4a: the answer report
      (`ResearchView.tsx`, opened from the "Open report:" artifact button, with `.claim` and `.reference-list` entries). 4b: the P6 evidence
      report (`report/ReportView.tsx`, reached as in `e2e/report.spec.ts`, `readyResearch`), with its check panel, one claim edit form open,
      and the citation-removal form open (`e2e/report-edit.spec.ts` shows how to reach them).
   5. The passage sheet ("Source details" dialog) with a citation highlight.
   6. The PDF tab or the plain-text document view of a source that has a PDF (the main flow of `acceptance.spec.ts` seeds the research with
      `replacementPdf()` through the file input; its source opens in the PDF tab or text view).
   7. Evidence tab: empty state, a filled table, and the cell panel dialog.
   8. Library, with at least one research; Trash with at least one item.
   9. Settings (defaults) and Settings, Connections (including one connection sheet open).
   10. The human queue of an sw research (`DEIXIS_FIXTURE_QUEUE=on`, question marker `[queue]`, see `e2e/human-queue.spec.ts`), list plus
       one open row.
   11. Transient overlays: quick find (Cmd/Ctrl+K), one confirm dialog, one toast (a success toast closes after about 5 s, so trigger it
       again for every theme and width, or use an error toast).
   Tabs not on this list (Activity, Candidates, Artifacts, "Waiting for your PDF") are not scanned; say so in the Limits.
   Scan rules: `AxeBuilder` with tags `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa`; the page must be settled first (loading
   text gone, no mid-transition colors: open the scan pages in a context with `reducedMotion: 'reduce'` so contrast is not measured during a
   fade, the motion paths are covered by X06; this means gradient text such as `.shimmer-text` and styles that exist only in normal motion
   mode are not measured for contrast, state that in the Limits). `wcag22aa` brings the `target-size` rule; that is this prompt's own
   choice, not the plan's, so a `target-size` finding counts like any other, and if fixing it at 390 px would need a wide CSS change,
   record that and fix only what the rules of `.impeccable.md` allow. **No exclusions:** never use `.exclude()`, `.disableRules()`,
   `.withRules()` to narrow the rules, `.include()` to narrow a page, or a per-node skip to make a scan pass. If a serious or critical
   finding cannot be fixed inside the allowed files (a base-ui guard element, the pdf.js canvas or text layer, KaTeX output), the test
   stays red, say which node and why, and report it as an open mandatory failure for the owner (plan §4 rule 2); do not hide it. The tag set above is frozen here as the definition of X01 to X04 before any
   measurement. Give the scan test `test.setTimeout` large enough for about 60 scans (default is 120 s), or split it into a serial describe
   whose last test makes the aggregated assertion. Count findings by `impact`; the assertion is `serious + critical === 0` per screen and state
   (a real test failure, with the rule ids, node count and a short selector in the failure message). Scan **every** screen and state first,
   write the JSON, and make the assertion once at the end (a single aggregated assert or `expect.soft`), so a first failure does not hide
   the rest and the "before" numbers are complete. All findings (every impact) are also
   written to `${OUT}/a11y-findings.json` and copied after each of the two scans (baseline and final) to
   `.local/p9-h6/findings-before.json` and `findings-after.json` in the worktree (ignored; the first scan must not be overwritten), with the
   sha256 of each and the command line written into the decision (rule id, impact, help text, node count, first selector, screen, theme, width); never write
   `html` of nodes into docs. `incomplete` results are recorded per rule too: for `color-contrast` incompletes (gradient or image
   background) check the computed text and background colors by hand with a small `page.evaluate` and record the ratio, or write
   "ölçülmedi" for that element.
4. **Baseline before any fix.** Order: `npm run build` (the fixture server serves `apps/web/dist`, which does not exist in this worktree
   yet) -> baseline scan -> fixes -> `npm run build` again -> rescan. A rescan without the second build measures the old code. Run the scan first on the unchanged `apps/web/src`, save the raw result, and keep per-screen, per-state
   counts of serious, critical, moderate and minor findings (these "before" numbers go in the decision). Then fix, then rescan for the
   "after" numbers. A scan test that has not been seen failing on a real defect proves little, so keep the baseline output as evidence; if
   there were zero serious or critical findings on the baseline, also show once that the scanner can fail (for example run the
   same scan against a throwaway page with a known missing label, not committed) and say so.
5. **X05, keyboard walk (a Playwright test).** The A to G cases of `acceptance.spec.ts` by keyboard only: after the initial `goto` and the
   same setup the existing helpers use (file input, selections through the API are allowed for setup and must be named as such), every
   activation is a key press (Tab, Shift+Tab, Enter, Space, Escape, arrow keys, Home/End), no `click()`. Cover at least: composer reached by
   Tab and Start research by Enter; the tab list by arrow keys; Sources: exclude with a reason and Save (D), open "Read abstract" (G),
   Escape returns focus to the control that opened it; generate the answer, open the report, a citation chip opens the stored passage (A),
   Escape returns focus to the chip; the version-labelled references (B, C) reachable; an evidence cell by arrow keys, Enter opens the cell
   panel, Escape returns focus to the cell; quick find by shortcut, listbox by arrow keys, Escape; one provider failure (E, marker
   `[rate-limit]`, its own research): the "Search details" `<details>` opens by keyboard and the OpenAlex line reads "rate limited" (the
   stored list has no `role`, and must not get one: `role=alert` is for blocking errors and `role=status` for live text, `.impeccable.md`
   §9); reload keeps the state (F). The model-error half of E (`[model-down]`, then the Resume button) is
   also reached by keyboard once; if you leave it out, say so in the Limits. At every step assert the
   focused element is visible, inside the viewport and has a visible focus indicator. Frozen rule: the app's own indicator is the 2 px
   accent outline (`.app button:focus-visible`, `App.css`); sheets, dialogs and toasts render in portals outside `.app` and plain
   `<button>`, `<a>`, `<summary>` there get Chrome's native `outline: auto` ring. The native ring counts as a visible indicator
   (computed `outline-style` not `none`, or a clear `box-shadow` or border change); an element whose computed outline is `none` with no
   other change fails and is fixed. Three controls deliberately show focus on the nearest
   `:focus-within` container instead of the element (the composer textarea, `App.css:7`; the quick find input, `workspace.css:792`;
   the model palette search, `App.css:59`; the evidence label with `:has(input:focus-visible)`, `EvidenceTable.css:222`): for those
   the indicator is measured on the container (its border, outline or box-shadow differs from the unfocused state) and they are not
   "fixed" with a second outline. Elements that rely on the native ring are listed as an observation, not changed, and one of them is
   photographed in each theme. After each dialog or sheet closes with Escape,
   assert `document.activeElement` is the element that opened it (or the documented fallback if the opener is gone). Keep the walk in
   one test per case or one serial describe, readable, and add a focus-trap check: Tab from the last control inside an open dialog stays
   in the dialog.
6. **X06, reduced motion and 200% zoom.**
   - Reduced motion: a context with `reducedMotion: 'reduce'`. On a screen with live work (the evidence fill with the `[slow-cells]` marker; the scripted model otherwise finishes at once, so check
     `fixture_server.py` for another slow marker before claiming a running research) and
     on the sheets, dialogs, toasts and tabs: assert that no element has a computed `animation-duration` or `transition-duration` above
     0.01 ms (allow the single global-block value, and list exceptions by selector instead of weakening the assertion), that
     `document.getAnimations()` holds no animation with infinite iterations, and that `getComputedStyle(documentElement).scrollBehavior`
     is `auto`. The typewriter title shows its full text at once. Then run the same checks without the preference once, only to prove the
     test sees motion there (a positive control; if the app has no motion on the page used, say so).
   - 200% zoom: Playwright cannot set browser zoom, so use the layout width a 1280 px window has at 200%: viewport 640x450 CSS px with
     `deviceScaleFactor: 2`. State this equivalence in the spec comment and in the decision, and add 400% (320x225) as an extra, recorded
     non-mandatory measurement. The tasks are done at that size, not only looked at: open each screen at 640x450 from the start (set the
     viewport before `goto`) and run the flow question -> start -> Sources -> Answer -> report -> citation -> passage, and the evidence
     cell -> panel flow, by keyboard or click. At 640x450 for the home, research (Sources, Answer), report sheet, passage sheet, evidence table with the
     cell panel and the human queue: assert no horizontal page scroll (`document.documentElement.scrollWidth <= clientWidth`, with a
     named exception for an element that scrolls inside its own scroller as `.impeccable.md` §7 allows), the primary controls of the screen
     (start research, tab list, the report open button, close buttons of sheets, the evidence cell panel actions, the cited-passage
     "Go to cited text" or equivalent) are visible and not covered (check with `elementFromPoint` at the control centre), and the evidence
     access of §7 stays reachable.
7. **X07 (VoiceOver).** Optional; do not run it and do not invent results. Write "ölçülmedi" with the reason (the agent cannot drive
   VoiceOver) and list the three flows to do by hand (opening, answer plus citation, evidence table cell) so the owner or a later session
   can do them. If during the work you found things axe cannot see (label wording, reading order), list them as observations, labelled
   "from reading the markup, not from a screen reader".
8. **Fixing.** Serious and critical findings (and any focus, zoom or reduced-motion assertion that fails) are fixed in `apps/web/src`,
   smallest reversible change, existing classes and tokens, per `.impeccable.md` §11 (no new UI dependency; remove a CSS class you leave
   unreferenced; strings through `t()`/`i18n.ts` with the Turkish map beside the English one if you add or change one; keep §9 and §6). A
   fix that cannot follow a rule in `.impeccable.md` is recorded in its §10 with the reason; otherwise do not edit `.impeccable.md`.
   Moderate and minor findings are not fixed in this batch, unless one root cause covers both a serious and a minor finding and the fix
   is one line. They go into the known-issues list below. When a fix changes something visible, rerun the affected existing specs, and
   look at the changed screen (see Checks).
9. **Known-issues record.** The plan's acceptance record is created in H8, so for now the non-serious findings are listed in the decision
   record `## D16X` under "Known findings (not fixed)": rule id, impact, number of nodes, screens, one line of cause each. H8 collects them.

## Files allowed

- `apps/web/e2e/a11y.spec.ts` (new)
- `apps/web/package.json`, `apps/web/package-lock.json` (the devDependency only)
- `apps/web/src/*` (fixes for serious or critical findings, and for failed focus, zoom or reduced-motion assertions), including its CSS files
- `.impeccable.md` only for a §10 exception
- `docs/decisions.md` (new top entry `## D16X`, placeholder number; the main session renumbers), `docs/product/p9-hardening-plan.md` (one status line after H6's "Göstermez" paragraph, in the pattern of the H0c line in H0b)
- this prompt file
- raw output only under `/tmp/h6-*` and the worktree's ignored `.local/p9-h6/`

Anything else needs a stated reason in your report; the default is not to touch it.

## Checks (all in the worktree, nothing in the other checkouts)

1. `cd apps/web && npm ci` from a clean `node_modules` (delete it first and reinstall after adding the devDependency to show the lock file
   is consistent). `npm run build`; `npm run lint` (baseline 17 warnings, no new warning from your files).
2. The new spec alone, then the full suite on a fresh build: `DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance-h6 npm run test:acceptance`.
   Report passed counts (142 before this batch plus the new tests); a flaky test is named, rerun once, and reported as flaky, not hidden.
3. If, and only if, a backend file changed (none should), run the full pytest. Otherwise say pytest was not run and why.
4. Screenshots of every screen you changed, at 1280 or 1440 px and at 390 px, light and dark, plus the focus state of each changed control,
   saved under `/tmp/h6-shots/` and **actually opened with the image reader**; describe in the report what each one showed. If no
   `apps/web/src` file changed, say so and take a small set of the scanned screens anyway.
5. `git diff --check` clean. Processes you started (servers, Chrome) are all stopped at the end; check with `lsof -i :8820-8830`.

## Output

- X01 to X06 each: executed result, number of screens and states, serious plus critical count before and after fixes (per screen and
  state), moderate and minor counts, the incomplete contrast items and what you did with each.
- Per plan §4 rule 4, every result carries two separate fields: execution type (automated browser test, manual) and data/model reality
  (synthetic records, scripted model).
- X07: "ölçülmedi" with the reason and the three flows, plus the labelled observations, if any.
- A table of every fix: file, rule or assertion it addressed, one-line cause.
- Third-party findings that cannot be fixed in the allowed files (base-ui focus guards with `tabindex=0` and `aria-hidden`, pdf.js, KaTeX)
  in their own list with the node and the rule, so the owner can decide.
- A one-line rerun command for the scan, and a note that the `run_matrix.sh` row is left to H1 and H8 (the script does not exist yet).
- What you could not reach or measure, with the reason (a screen not reachable in the fixture, a state not reproducible, a rule axe marks
  incomplete).
- The changed-file list (`git status --short`) and the checks above with counts.

## Limits to state in the decision

The scan is automated: axe finds the defects it can find mechanically (it cannot judge label wording, reading order, or whether focus
order makes sense) and says nothing about cognitive accessibility. Chrome only (Playwright `channel: 'chrome'`). Synthetic records and a
scripted model, so text lengths and states are those of the fixtures. The 200% case is the 640 px layout equivalent, not Chrome's own
zoom (so text-only zoom and browser zoom behaviour are not measured). Reduced motion is measured as computed styles and live animations
at a point in time, not as a frame-by-frame check. X07 was not run. A passing scan on the frozen screen list says nothing about screens
or states not on it.
