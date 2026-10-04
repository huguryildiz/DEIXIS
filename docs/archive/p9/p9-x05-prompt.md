# P9 X05 batch: the keyboard-focus walk must not flake

Decision number: D200. Plan by Claude Opus 5.5, reviewed by gpt-6.1-sol medium. Code by gpt-6.1-sol high, reviewed by Claude Opus 5.5. Base: `481d016`.

## Why

`apps/web/e2e/a11y.spec.ts` X05 fails now and then under load: RR-B matrix run 1 (D170), the P8 B3 full run (D183), the G1 B4 full run (D194) and the P8 B8a full run (D185) each saw one failure. Alone the X05 group passed 10/10 and 19/19, and once failed alone on a different case. The P9 exit needs two clean RR-B matrix runs in a row, so this flake blocks P9.

The batch prompt from the coordinator: find the cause; if the app has a race, fix the app; only where the app is correct may the test wait on a real condition; never raise a timeout.

## What was measured before this prompt (Claude, on `481d016`)

### Failure 1: "A, B, C", focus after Generate answer now (G1 B4 run, `/tmp/deixis-acceptance-g1b4`)

`a11y.spec.ts:1176` expects `.chat-turn .chat-toggle` with "Ran answer generation" to be focused; it timed out after 30 s ("inactive"). In the trace the run was posted, the research reloaded 20 ms later, the next reload came at +945 ms (run finished), and the audit at +3.7 s found focus on `<body>`.

Probe (temporary spec, not committed; it logs `document.activeElement` every frame and every 20 ms after Enter on Generate answer now):

- CPU throttled 6x, 5 handoffs: 4 went to the run's heading button; 1 went to `SPAN.run-strip-status[data-run-id=<new run>] "Answer · Running"` and then to `<body>` when the run finished (1.9 s).
- Same probe with the first research reload after the POST answered with the new run still `running` (route rewrite) and queued `requestAnimationFrame` callbacks run in the microtask after a `.chat-turn` or `.run-strip` node is inserted (a frame between React's commit and its passive effects): 4 of 4 handoffs went to the run strip status, then to `<body>` when the run finished.

Cause in the code:

- `ResearchView.tsx:140-141`: `focusRuns` is a ref copied from `view.runs` in a passive `useEffect`.
- `ResearchView.tsx:269-274` (`toRunStatus`): the handoff finds the run's heading by the run's position in `focusRuns.current` and indexes `document.querySelectorAll('.chat-turn .chat-toggle')` with it. In a frame after the commit that adds the new run but before the passive effect has run, `focusRuns.current` does not contain the run, the index is -1, and the fallback `.run-strip-status[data-run-id=…]` (`ResearchView.tsx:481`), rendered in the same commit, takes focus.
- `focus.ts:24`: without `follow` the wait stops once it has placed focus. The run strip exists only while the run is active or paused (`ResearchView.tsx:480`), so when the run ends the focused node is removed and focus is on `<body>`.

This is an app race, not test timing. The 30 s `toBeFocused` already waits on the real condition. D167's open list already named the positional lookup ("finds the run's heading by its position in the transcript list, not by `data-run-id`").

### Failure 2: "evidence report", toast focus pushed out of view (P8 B8a X05-alone run, `/tmp/p8b8a-accx05`)

`dismissToastsByKeyboard` failed with "returned toast focus is visible inside the viewport". Trace: the walk tabbed from Open evidence report through the footer to the toast; just before the toast, "DEIXIS on GitHub" (footer) was focused, visible and in the viewport. Enter dismissed the toast and focus went back to that footer link, which is the correct return target (`Toast.tsx:24-31`). A research reload arrived at +363 ms; the screencast shows the report card still "Evidence report · being written" with "Writing sections, step 2 of 3" before the Enter, and after the reload the run has finished, the readiness panel and the Evidence report section are back above the footer, a new toast "Evidence report finished" is up, and the footer link is below the viewport. The audit at +410 ms saw it out of view.

The test moved on as soon as "Open evidence report" was visible (`a11y.spec.ts:1359-1361`), but that button is shown while the report is still being written. The focus return is right; the page grew under it because the run the test started had not ended. This one is test timing: the test must wait for the report run to end (a real state) before it dismisses toasts.

## What to change

### 1. App: the run handoff finds the heading by run id (`Transcript.tsx`, `ResearchView.tsx`)

- `Transcript.tsx` (`RunTurn`, the `button.chat-toggle` at line 567): add `data-run-id={run.id}`.
- `ResearchView.tsx` `toRunStatus`: find `.chat-turn .chat-toggle[data-run-id="<runId>"]` first, then the existing `.run-strip-status[data-run-id="<runId>"]` fallback. Use `CSS.escape` on the id in both selectors. No positional lookup.
- Remove `focusRuns` (the ref and its effect) if nothing else uses it (today nothing does).
- Do not change `focus.ts`, its 2.5 s default, the `follow` argument of this call, `act`, or any other caller. Do not add a timer.

Not in this batch (record as a limit, do not fix): when the Answer tab is not shown the heading is not rendered, so the run strip status still takes focus and focus goes to `<body>` when that run ends (Resume pressed from another tab). It is not on the X05 walk and was not measured.

### 2. Test: the evidence-report case waits for its run to end (`a11y.spec.ts`)

In `evidence report: the table scroll region is a Tab stop with a focus ring`, after `Open evidence report` is visible and before `dismissToastsByKeyboard`, wait for the report run to have ended, by states the page shows: the report card that holds `open` is present and no longer reads "being written" (assert the card's presence and its terminal text, scoped to that card, so an absent card cannot satisfy a negative check), and no `.run-strip-status` is shown. Use expect timeouts no larger than the 90 s that test already allows for the button; no fixed sleep. Then dismiss toasts as now (that also dismisses "Evidence report finished").

Check every other `dismissToastsByKeyboard` call site for the same hazard (a run the test started still active when its toasts are dismissed). Static reading by the plan reviewer: `1177` waits for "Ran answer generation" (ended); `1324` waits only for the first filled cell, so the fill can still be running: wait there until the table's run line `.evidence-run` is gone (not `.run-strip-status`, which is not used for table runs); `1420` and `1444` follow column creation without a fill; `1536` follows a rejected answer start; `1550` follows a rejected selection change. Confirm or correct each in the report and change only sites where the hazard is real.

### 3. Regression test that fails on the old lookup (`a11y.spec.ts`, `tests/acceptance/fixture_server.py`)

Fixture: a new question marker `[answer-hold]`. When the task is `grounded_answer` and the question carries the marker, the scripted model waits until a file `answer-release` exists in the fixture's data directory, polling every 0.1 s, and fails the step after 60 s (the same shape as `[review-hold]` at `fixture_server.py:458-464`). Add the marker to the module docstring list.

Spec: one test in `X05 regressions: asynchronous focus ownership`:

1. An init script that models a browser frame that falls between React's commit and its passive effects: wrap `window.requestAnimationFrame` so each callback is queued and runs exactly once, either on the next real frame or earlier, when a `MutationObserver` callback sees a `.run-strip-status` element inserted (directly or inside an inserted node), whichever comes first; `cancelAnimationFrame` keeps working for wrapped ids. The script also records, in order, every `focusin` target (class and `data-run-id`) and every early flush (time and whether a `.chat-turn .chat-toggle` for the new run existed). Comment why the hook exists. React may flush passive effects synchronously for some updates, so the hook alone does not prove the race happened: the test's old-code check (below) is what proves it.
2. Before setup, remove any stale `answer-release` file. `startResearch` with a question carrying `[answer-hold]` (the `keys` fixture), open the Answer tab, Tab to Generate answer now. Arm `page.waitForResponse` for the POST to `/api/researches/<id>/runs` before pressing Enter, press Enter, then await it.
3. Read the new run id from the POST response (`page.waitForResponse` on the runs POST). While the run is still running (its `.run-strip-status[data-run-id=<id>]` is visible), assert: the focused element is `.chat-turn .chat-toggle[data-run-id=<id>]`, and the focus record never contains `.run-strip-status`.
4. Write `answer-release`, wait for "Ran answer generation", `quiet(page)`, and assert the same heading is still focused (not `<body>`).
5. Cleanup in `finally`, also when an assertion failed (the original assertion error must still be the test's failure): write `answer-release` if it is not there, wait until the held run is no longer active (the API view or the page shows a terminal status; bounded by the fixture's 60 s hold), wait until the page no longer renders `.run-strip-status[data-run-id=<id>]` (the page reloads 250 ms after an event, so an API status alone is too early), then take a snapshot of `document.activeElement` (tag, class, `data-run-id`, or `body`) and attach it, with the focus record, to the test (`test.info().attach` or an annotation), and then remove the file. The `focusin` record cannot show focus falling to `<body>` when a node is removed; the snapshot after the run ended is what shows it. The fixture worker runs one run at a time, so a held run left behind would stall the next tests on `keys`.

Old-code check (Sol states how; Claude re-runs it outside the sandbox): with `Transcript.tsx`'s new `data-run-id` attribute present but `ResearchView.tsx`'s `toRunStatus` restored to the positional lookup of `481d016`, the test must fail because focus went to `.run-strip-status` (shown in the focus record) and then to `<body>` after release, not merely because a selector is missing. With change 1 it must pass.

Keep the existing "A, B, C" assertion at `a11y.spec.ts:1176`; you may add that the focused heading's `data-run-id` is the run the POST returned.

### Other paths that are not fixed here (record as unverified)

From the plan review, possible but not observed in any trace: concurrent `load()` calls have no ordering guard, so an older response could overwrite a newer view (`ResearchView.tsx:149-158, 192, 242`); the App route-change loop (`App.tsx:127`) can compete while armed; replacing a toast changes its portal key, so a focused toast can be removed by the next one (`Toast.tsx:22, 42`). Do not change them in this batch. The 2.5 s window of `focusWhenLost` starts after `act()` returns, so a slow POST or reload does not use it up.

## Files

Allowed: `apps/web/src/ResearchView.tsx`, `apps/web/src/Transcript.tsx`, `apps/web/e2e/a11y.spec.ts`, `tests/acceptance/fixture_server.py`.

Forbidden: `apps/web/src/focus.ts`, `apps/web/playwright.config.ts`, any other spec, backend code, contracts, migrations, `docs/decisions.md`, `STATUS.md` (Claude writes the records). No timeout in any file may be raised, and no fixed `waitForTimeout` may be added to make a case pass.

## Checks

- `cd apps/web && npm run build && npm run lint` (lint baseline: 0 errors, 16 warnings; no new warning); `git diff --check`.
- Sol's sandbox cannot run Chrome or bind ports; Claude runs Playwright outside it under the shared port lock.
- Claude's measurement (same procedure before and after, under `/tmp/deixis-playwright.lock`, released between runs): the X05 group (`npx playwright test e2e/a11y.spec.ts -g X05`) 30 times alone, and the full Playwright suite 3 times while the full pytest suite runs in parallel in the same worktree as CPU load. Before: on `481d016`. After: on this batch. Counts go into D200; the load pytest's own exit status is recorded. These runs measure the X05 flake only; they do not replace the two consecutive clean RR-B matrix runs the P9 exit needs.
- Claude also runs the regression test on the old lookup (above) and on the fix, keeps both traces, and looks at the focused heading at 1280 and 390 px.

## Report

Write `/tmp/x05-impl-report.md`: each change with file:line, each `dismissToastsByKeyboard` site and what you found, how the regression test fails on the old code, build and lint output, what you could not run.
