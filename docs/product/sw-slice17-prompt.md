# Task: SW slice 17: the human queue screen (D97)

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. The master file is `docs/product/sw-status.md`, and the
line-level plan is `docs/product/sw-slice17-human-queue-screen.md`. Its seven decisions were settled jointly by Claude
and `gpt-5.6-sol` · medium on 24 September 2026, at the owner's request (`.local/sw-slice17-plan-2026-09-24/`
`sol-medium.md`, `sol-approval.md`); read the section "Ortak kararlar" first, it overrides the recommendations above it
where they differ. The slice file is the only source of truth; this prompt sets the rules of the session. The
implementer is Opus · medium. The review is batched, so list every place where you used your own judgement.

## Ground rules

1. **Git.** Run `git pull --ff-only` first and work in the main checkout on `main`. At the end make ONE commit and
   run `git push origin main`. No branch, no PR, no AI attribution, no co-author. Before the push, run
   `git log origin/main..HEAD --format=%B | grep -i co-authored-by`. Never stash or reset. Leave the owner's files
   alone: `TODO.md`, `.vscode/`, `scripts/local_index.py`. If the slice is not finished, commit nothing: write what
   remains into row 17 of `sw-status.md` and say so.
2. **No model contract change.** `skill_package_hash` must stay
   `sha256:7d4e238c3e9feebd451c77fb997aff717a3617008bd4165be56f9fba46bf6fca`. Check it before and after with
   `PYTHONPATH=backend uv run python -c "from deixis.domain.skill import package_hash; print(package_hash())"`.
   No migration (the highest is `0051`), no new reason code.
3. **Back end: reads only.** The only back-end changes are the ones in decision 6 and "Ortak kararlar" 2–3:
   `passage_id`, `asset_id`, `anchor_text`, both versions for `choose_version`, the `decided` list with a typed
   `answer`, and a typed `detail.reason` on the queue endpoints' 409. Reading the queue opens no step and writes nothing
   (Ders C). Nothing changes for a `legacy` research; its view and the queue endpoints' 422 stay as they are.
4. **Evidence rules.** Highlight only the backend's `anchor_text` in the plain-text view. Never highlight a model quote,
   a fuzzy match or the closest passage. The PDF view is a canvas and shows no mark; do not pretend it does. The screen
   never says a decision is correct.
5. **Design.** Read `.impeccable.md` in full before touching `apps/web`, and `AGENTS.md`. Reuse tokens, `Notice`,
   `Toast`, `PassageSheet`, `.ref-pill`, `.tab-strip`; no new UI dependency; both themes, 760 px breakpoint, 390 px
   usable, keyboard, reduced motion, sentence-case labels, every string through `t()` with its Turkish in `i18n.ts`.
6. **Tests.** Tests use no network and no live model. Change existing tests only where the slice file names it, and
   list each change in the final message. Cases A–I of the acceptance suite must pass unchanged.
7. **Live service.** Do not start, stop or query the service on port 8765, and do not open the product database. The
   visual check (Task 5) serves a copy of a stored `.local` library on another port with its own `DEIXIS_DATA_DIR`,
   and makes no model call.
8. **Python.** `PYTHONPATH=backend:. uv run ...` from the repo root, native arm64. Known failures that are not this
   slice's: `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`, and the import
   errors of `test_isolated_pdf_prefetch.py` and `test_p4_eval.py`.

## Read first

- `AGENTS.md`, `CLAUDE.md`, `.impeccable.md`.
- `docs/product/sw-status.md`: rows 16, 17, 18, 20.
- The slice file in full, especially "Sahibin vereceği kararlar", "Ortak kararlar" and the Task list.
- `docs/decisions.md`: D96 (the queue back end), D71.
- `docs/product/search-workflow-review-2026-09-18.md`: SW11 (points 1, 6, 7, 11).
- Code: `backend/deixis/workflow/queue.py`, `backend/deixis/api/app.py` (the four queue endpoints),
  `backend/deixis/domain/contracts.py` (`locate_anchor`), `apps/web/src/api.ts` (the `Queue*` types),
  `ResearchView.tsx` (tabs, event subscription, `PassageSheet` targets), `PassageSheet.tsx`, `PdfViewer.tsx`,
  `Transcript.tsx`, `Toast.tsx`, `Notice.tsx`, `i18n.ts`, `labels.ts`.
- Tests: `tests/test_queue.py`, `tests/test_queue_api.py`, `tests/acceptance/fixture_server.py`, `apps/web/e2e/*.spec.ts`.
- Measurement: `.local/sw-slice17-plan-2026-09-24/shape.json`.

## What to build

Tasks 1–5 of the slice file, in order. Back-end tests first (Task 4 names them), then the screen, then the fixture and
case J.

## Procedure

1. `git pull --ff-only`, `git status --short`. Baseline `PYTHONPATH=backend:. uv run pytest -q`; record the count and
   `skill_package_hash`.
2. Set row 17 to `uygulanıyor`.
3. Task 1 with its tests; suite green.
4. Tasks 2–3; `npm run build` and `npm run lint` (no new warning).
5. Task 4: fixture server and case J; `DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance npm run test:acceptance` (A–J).
6. Task 5: the visual check on a copy of `.local/sw-slice16-acceptance-2026-09-24/data-q1-quick-luna-r2` under
   `.local/sw-slice17-acceptance-<date>/`, screenshots at 1440 px and 390 px in light and dark, the check list and the
   decision round into `result.md`. Look at the screenshots yourself before you call it done.
7. D97 at the top of `docs/decisions.md` (Status / Date / Context / Decision / Limits); it records decision 2 as a
   deliberate departure from SW11.6's wording, with its reason. Update SW11's status line. Full test suite,
   `git diff --check`, `skill_package_hash` unchanged. Row 17 to `uygulandı, inceleme bekliyor`; commit and push.

## Final message

- Files changed; the back-end fields added and the 409 envelope.
- Baseline and final test counts; the new tests by name; every changed expectation with its reason.
- Case J: what it checks and that A–I still pass.
- The visual check: which rows were opened, the screenshots' paths, what the check list found.
- Every place where you used your own judgement, with the rule you applied; every deviation from the slice file.
- What was "ölçülmedi".
- Confirmation that the live service and the product database were not touched.
- The commit hash, or why there is none.
