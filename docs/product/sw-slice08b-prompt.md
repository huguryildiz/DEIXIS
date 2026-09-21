# Task: SW slice 08b — the approval card: the user sees, corrects and approves the search terms and the inclusion criterion before an sw run searches (interface)

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 08b of the search workflow build. The master file is `docs/product/sw-status.md`; the line-level plan for this slice is `docs/product/sw-slice08b-protocol-approval-ui.md`. That file is the single source of truth for what to build. This prompt only sets the rules of the session. Recommended model: Opus, effort medium.

## Ground rules

1. **Do not start unless row 08a of `sw-status.md` says `kapandı`.** If it does not, stop and say so.
2. Git: start with `git pull --ff-only`. After that, read-only until the slice is finished. When every task is done and every check is green, run `git pull --ff-only` again, then make ONE commit and `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash, reset, rebase or check out files. If the slice is not finished, commit nothing: leave the tree building and passing, and write what remains into row 08b. `TODO.md` and `scripts/local_index.py` may show as the owner's uncommitted work: leave them alone and do not stage them. If any other file you did not touch shows as modified, another session is writing here: stop and report.
3. **Backend is closed**, with one named exception: `views.research_view` may gain the scope's `search_workflow` and `key_terms` if it does not carry them, with one test. No route, no flow, no store, no migration, no contract, no method package.
4. **Render recorded backend state.** A run waiting for approval never looks successful; the card says `approved` only when the view does; while the submission is being checked the card is locked. This is a new pause reason, not a new run status. No plain Resume on a run that waits for approval.
5. **No new design language.** Read `.impeccable.md` first and use its tokens, the components in `apps/web/src/components/ui`, and the existing `.chat-note` tones. One run is one timeline item; the card lives inside it. `ConfirmDialog` is not used for the approval.
6. Every string goes through `i18n.ts` / `labels.ts`, in English and Turkish, in the calm factual tone of the existing pause sentences. A missing count is "not counted", never 0. The card does not overstate the criterion: in this build it orders nothing and decides nothing yet.
7. **`legacy` researches and the existing Playwright cases A–G stay exactly as they are.** The new scenario runs against a second fixture server (`DEIXIS_SEARCH_WORKFLOW=sw`, `DEIXIS_PROTOCOL_APPROVAL=ask`, its own port and data directory).
8. Visual work needs no step-by-step approval from the owner: make the change, take screenshots (light, dark, 390 px wide), open them with the Read tool, fix what is wrong, look again, and show only the finished state.
9. **Do not invent.** What the card shows, which edits it offers and what each pause links to are complete in the slice file. If the view lacks something the card needs, stop and report instead of adding backend code.
10. Accessibility: every action by keyboard, moving a term through a `select` (no drag and drop), badges not told apart by color alone, errors announced through `aria-live`.
11. Do not start, stop or restart the service on port 8765, and do not open the product database. Fixture data is SYNTHETIC; a passing scenario shows workflow behavior.

## Read first

- `AGENTS.md` — whole file; `.impeccable.md` — whole file.
- `docs/product/sw-status.md` (rows 08a and 08b, the review log for 08a), then the slice 08 entry of `docs/product/sw-implementation-plan.md`.
- `docs/product/sw-slice08b-protocol-approval-ui.md` — whole file; `docs/product/sw-slice08a-protocol-approval-backend.md` — Task 1 (the edit package), Task 3 (states) and Task 4 (route and view shape).
- `docs/product/search-workflow-review-2026-09-18.md` — SW2 points 1 and 6, SW15 point 3.
- Code, before editing:
  - `backend/deixis/workflow/views.py::research_view` (the `approval` field), `backend/deixis/api/app.py` (the approval route, `control_run`, the scope revision body).
  - `apps/web/src/api.ts` (`controlRun`, `reviseScope`, the run and step types), `Transcript.tsx` (how a paused run and its note are rendered), `ResearchView.tsx` (`RevisionForm`, the run control buttons, the pause toast and chip), `labels.ts` (`pauseReasons`, `pauseReasonText`), `i18n.ts`, `workspace.css` (`.chat-note`, the timeline phase icons), `ConfirmDialog.tsx`, `components/ui/*`.
  - `apps/web/playwright.config.*`, `apps/web/e2e/acceptance.spec.ts` (helpers and style), `tests/acceptance/fixture_server.py`.

## What to build

Tasks 1–5 of the slice file, in that order.

## Procedure

1. `git pull --ff-only`, `git status --short`, check row 08a. `cd apps/web && npm ci` if needed.
2. Baseline: `npm run build && npm run lint`, and the existing acceptance run (`DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance npm run test:acceptance`). Record the results.
3. Set row 08b to `uygulanıyor`.
4. Build Task 1 to Task 3, then write scenario H (Task 4) and make it pass. Take the screenshots the slice file names and look at them.
5. Ask of the card: what does it show while the submission is being checked; after a 422; after the backend stops the run again with `vocabulary_empty`; when the criterion is unavailable; when the run was approved by the setting or by an earlier approval rather than by the user; when the page is reloaded in each state.
6. Task 5: build, lint, acceptance (A–G and H), full pytest, `git diff --check`, the D80 Limits edit, row 08b, the second pull, then the commit and push.

## Final message

- Files created and changed.
- Results of build, lint, Playwright (A–G and H separately) and pytest.
- Paths of the screenshots you looked at, and what you found and fixed in them.
- The one backend place touched, if any.
- Every point where the slice file could not be followed as written, and every deviation you chose, with its reason.
- What you did NOT do.
- Confirmation that the live service and the product database were not touched, and the commit hash.
