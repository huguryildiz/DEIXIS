# Task: SW slice 16: the human queue, back end (D96)

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. The master file is `docs/product/sw-status.md`, and the
line-level plan is `docs/product/sw-slice16-human-queue.md`. Its seven decisions were revised through three rounds with
`gpt-6-sol` (one high, two medium; `.local/sw-slice16-queue-measure-2026-09-24/sol-*.md`) and accepted as recommended,
the optional fifth answer ("PDF doğru, model okusun") included: the owner made approval conditional on Sol medium, and
Sol medium approved all seven on 24 September 2026. The slice writes D96 and migration `0051`. The slice file is the
only source of truth; this prompt sets the rules of the session. The implementer is Opus · high. The review is a full
one, so list every place where you used your own judgement.

## Ground rules

1. **Git.** Run `git pull --ff-only` first and work in the main checkout on `main`. At the end make ONE commit and
   run `git push origin main`. No branch, no PR, no AI attribution, no co-author. Before the push, run
   `git log origin/main..HEAD --format=%B | grep -i co-authored-by`. Never stash or reset. Leave the owner's files
   alone: `TODO.md`, `.vscode/`, `scripts/local_index.py`. If the slice is not finished, or Task 5's acceptance fails
   on the slice's own cause, commit nothing: write what remains into row 16 of `sw-status.md` and say so.
2. **No model contract change.** `skill_package_hash` must stay
   `sha256:7d4e238c3e9feebd451c77fb997aff717a3617008bd4165be56f9fba46bf6fca`. Check it before and after with
   `PYTHONPATH=backend uv run python -c "from deixis.domain.skill import package_hash; print(package_hash())"`.
   No new reason code: the four human codes are already in `domain/reason_codes.py`.
3. **Nothing changes for a research without a human decision.** Discovery, retrieval, reading and answer steps,
   their inputs, outputs and budgets stay byte-identical. The only behaviour changes touch works a person decided:
   the abstract read plan, the two send-time checks in the reading run, the batch check in the abstract stage, and the
   identity exemption of a confirmed PDF.
4. **`legacy` does not change.** The queue endpoints answer 422 for a legacy research; its view is byte-identical.
5. **Decisions are added, never edited** (D71). The selection link is its own append-only table
   (`human_selection_links`); no UPDATE of a `stage_decisions` row other than `superseded_at`.
6. **One short transaction, no `await` inside.** Decision, selection, link, history and event go together; the
   `row_token` is recomputed inside that transaction. Reading the queue opens no step and writes nothing (Ders C).
7. **No topic word in product code.** Questions, cue sentences and order come from the frozen criterion's parts and
   the stored rankings. Fixtures are SYNTHETIC and come from at least two fields.
8. **Existing tests.** Change only what the slice file names, and list each change in the final message. Tests use no
   network and no live model. Do not start, stop or query the service on port 8765, and do not open the product
   database.
9. **Live model.** Task 5's one live run uses `gpt-5.6-luna` · medium over the Codex connection, passed explicitly.
   If Luna fails, for quota or anything else, stop and report. Do not switch models.
10. **Python.** `PYTHONPATH=backend:. uv run ...` from the repo root, native arm64. Scripts under a folder holding a
    `numbers.py` run with `python -P`. Known failures that are not this slice's:
    `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`, and the import errors of
    `test_isolated_pdf_prefetch.py` and `test_p4_eval.py`.

## Read first

- `AGENTS.md`, `CLAUDE.md` (and `.impeccable.md` only for what slice 17 will need from `api.ts`).
- `docs/product/sw-status.md`: rows 12, 15, 16, 17, 18, 20; decision K8.
- The slice file in full, especially "Sahibin vereceği kararlar" and its Sol notes.
- `.local/sw-slice16-queue-measure-2026-09-24/`: `protocol.md`, `result.md`, `table.md`, `counts.json`, `measure.py`
  (Task 5's replay reuses its counting rule), `sol-review.md`, `sol-approval*.md`.
- `docs/product/search-workflow-review-2026-09-18.md`: SW11 in full.
- `docs/decisions.md`: D71, D81, D83, D85, D94, D95.
- Code: `workflow/decisions.py`, `domain/reason_codes.py`, `workflow/fulltext.py` (`group_of`),
  `workflow/adjudication.py`, `workflow/abstract_stage.py` (`read_plan`), `workflow/flow.py` (`_abstract_stage`,
  `_fulltext_adjudication`, `_adjudication_call`, `_close_adjudication`, `_adjudication_plan`, `_user_supplied_pdf`,
  `_adjudication_summary`), `workflow/criterion_passages.py` (`compile_phrases`), `domain/contracts.py`
  (`locate_anchor`), `workflow/store.py` (`set_user_selection`, `_settle_work_head`, `work_heads`, `answer_version`,
  `page_texts`), `workflow/views.py` (`research_view`), `api/app.py`, `storage/migrations/` (the highest is `0050`).
- Tests: `test_decisions*.py`, `test_adjudication.py`, `test_adjudication_flow.py`, `test_abstract_stage.py`,
  `test_abstract_flow.py`, `test_fulltext_flow.py`, `tests/determinism_stages.py`.

## What to build

Tasks 1–5 of the slice file, in order, tests first for each task (Task 4 names them).

## Procedure

1. `git pull --ff-only`, `git status --short`. Baseline `PYTHONPATH=backend:. uv run pytest -q`; record the count and
   `skill_package_hash`.
2. Set row 16 to `uygulanıyor`.
3. Tasks 1–4, tests first, then code; keep the suite green after each task. `npm run build` and `npm run lint`
   (only `api.ts` changes).
4. Task 5: the offline replay over the 11 stored slice 15 libraries must reproduce `counts.json` exactly. Then write
   `protocol.md` in `.local/sw-slice16-acceptance-<date>/` before the first request, run the one live quantum `quick`
   run and the decision round. If it passes:
   - write D96 at the top of `docs/decisions.md`; update SW11's status line;
   - write the four separate items (criterion topic part, quote verification, identity check, SW6.6) into
     `sw-status.md` as the slice file says;
   - full test suite, `git diff --check`, `skill_package_hash` unchanged;
   - row 16 to `uygulandı, inceleme bekliyor`; commit and push.

## Final message

- Files changed, with the migration number.
- Baseline and final test counts; the new tests by name; every changed expectation with its reason.
- Replay: rows per library and reason against `counts.json`.
- Live run: verified works in pool / plan / read against 22 / 11 / 7, included, queue rows; if a loss exceeds K8, the
  step it was traced to.
- Decision round: each decision, undo and PDF confirmation, the selections and history rows written, and the model
  calls of the following reading run for decided works (expected 0) and a confirmed PDF (expected 2).
- The time `research_view` gained from the queue count.
- Every place where you used your own judgement, with the rule you applied; every deviation from the slice file.
- What was "ölçülmedi".
- Confirmation that the live service and the product database were not touched.
- The commit hash, or why there is none.
