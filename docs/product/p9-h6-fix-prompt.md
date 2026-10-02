# Task: P9 H6 fix round, four medium findings from Sol's re-review of H6 (commit 17b8341, D167)

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-h6f`, detached at `c5db475` (main). Read `AGENTS.md`, `CLAUDE.md`, `.impeccable.md`
(section 9 and 10 above all), `docs/product/p9-h6-prompt.md` (the H6 batch prompt) and the D167 entry in `docs/decisions.md` first.
The findings, in Turkish, are in `/tmp/h6f-sol-findings.md` (authoritative; summarised below).

**Rules.** No git state-changing command (no add, commit, stash, checkout, reset, clean, restore). No backend, migration, `methods/`,
contract or fixture-server change, no new dependency. Do not touch ports 8765 or 8858 to 8864, `TODO.md`, `.vscode/`,
`scripts/local_index.py`, `.local/`, `scripts/p9/`. Allowed files: `apps/web/src/focus.ts`, `apps/web/src/EvidenceTable.tsx`,
`apps/web/src/ResearchView.tsx`, `apps/web/src/Toast.tsx` (only if finding 4 shows that closing a toast with the keyboard drops focus to
`body`), `apps/web/e2e/a11y.spec.ts`, any other existing `apps/web/e2e/*.spec.ts` only if it needs the new behaviour. Do not edit
`docs/decisions.md` (the orchestrator writes the follow-up paragraph). Do not run the full Playwright suite; you may build and run single
specs with `DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance-h6f-impl` (ports 8820 to 8824 are the a11y spec's; check `lsof -i :8777-8830`
is empty before a run and kill what you start). `npm ci` was already run in `apps/web`.

## The four findings

1. **`focus.ts:11`, `EvidenceTable.tsx:399`.** The last H6 fix makes `focusWhenLost(..., follow=true)` stop on ANY `keydown` or
   `pointerdown`. While a fill runs and focus sits on the status line (`.evidence-run`), pressing only Shift (or any key that does not move
   focus) cancels the waiter, so when the status row is removed focus falls to `body` instead of the table's current cell. Fix: the
   waiter must end only when the person actually moved focus somewhere else (for example: a `focusin` on an element that is not the element
   the waiter itself focused, or focus on a connected element other than `body` that is not the held target), not on a key or pointer
   press as such. Keep the original reason for the stop (a later action of the person must not be undone by a focus move meant for an
   earlier one): that case is now "focus is on a connected element that is neither `body` nor the target the waiter placed". Add regression
   tests: Shift and a non-focus-moving key (for example ArrowLeft inside the status line, or a letter on a non-field) while focus is held
   must not cancel the waiter; a Tab to another control must cancel it. Put them where the existing specs test this helper or its
   callers (look at what `a11y.spec.ts` and the other specs already do for the fill case), using the real helper in a real page.
2. **`ResearchView.tsx:908` (`ReasonForm`).** After Exclude, `useEffect(() => { if (focusOnOpen) field.current?.focus() }, [focusOnOpen])`
   focuses the reason field unconditionally. If the person moved to the "Filter sources" field while the request was pending, and the row
   stays visible, focus is stolen back when the response arrives. Fix: hand focus over only if focus is still on the control that started
   the action or has been lost to `body` (the person did not move on). If the person moved focus to another real element, leave it. Add a
   regression test: press Exclude, move focus to "Filter sources" before the response settles (delay it with route interception or the
   existing fixture marker if one fits; do not change the fixture server), type into the filter, and assert the characters land in the
   filter and focus is still there.
3. **`ResearchView.tsx:233` (`act`) and `:260` (`startAnswer`, `toRunStatus`).** `act` swallows its error, so `.then(toRunStatus)` also
   runs after a failed "Generate answer now"; focus then goes to the previous run's heading instead of staying with or returning to the
   retry control. Fix: `act` returns an explicit result (for example `true` on success, `false` after a 409 or an error), and focus handoff
   happens only on success and only for the run that was just started (tie it to the new run id, or to the run list actually having a new
   run, not to "the newest heading in the DOM"). Check every other `.then(...)` on `act` in `ResearchView.tsx` and
   `EvidenceTable.tsx:398` (the fill) for the same bug and apply the same rule. On failure, if the pressed button is disabled and focus
   fell to `body`, focus must go back to that button once it is enabled again, or stay on it: pick the smallest change that does that and
   say which in a code comment of one line. Add a regression test with a failed start (route interception returning an error for the
   start-run call, or an existing failure marker such as `[model-down]` if it fits the answer start; do not edit the fixture server).
4. **`a11y.spec.ts:76` (`dismissToasts`; calls at 1159, 1306, 1343 and others) and D167.** X05's keyboard walk closes toasts with
   `.click()`, so D167's "after the first goto every activation is a key press" claim is broader than the code, the click moves focus,
   may cancel new waiters, and the focus a toast removal leaves behind is not checked. Fix: in the keyboard-walk tests (the describe
   that holds X05, lines about 1106 to 1485) replace `dismissToasts` with a keyboard helper that reaches the toast's "Dismiss
   notification" button by Tab (the toast is portaled at the end of `body`, `Toast.tsx`), presses Enter, and then audits where focus is
   (not `body`; an indicator; inside the viewport), recording it in the walk's focus log like the other stops. If closing a toast by
   keyboard really leaves focus on `body`, fix that in `Toast.tsx` (return focus to the element that had it before focus entered the
   toast, if it is still connected; otherwise to the nearest sensible control) and say so. The scan tests (X01 to X04) and the motion and
   zoom tests may keep the click-based `dismissToasts`: they are not claimed to be keyboard-only; keep the old helper for them under a
   clearly different name or keep its name and add the new one, whichever changes fewer lines. After the change, list in a comment above
   the keyboard helper which steps of the walk still use a click (setup only) so the claim in D167 can be stated exactly.

## Done when

`cd apps/web && npm run build && npm run lint` pass (lint 17-warning baseline, no new warning), `git diff --check` is clean, the new and
changed tests pass in a run of the specs you touched (`npx playwright test e2e/a11y.spec.ts -g "X05"` at least), and your final message lists
for each finding: the files and functions changed, the test added, and anything you could not do or measure. Do not write a decision entry or
a summary file.
