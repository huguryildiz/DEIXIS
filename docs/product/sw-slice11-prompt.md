# Task: SW slice 11 — in an sw research the answer input's criterion quota is filled from the approved cue phrases, in rounds across sources, and falls back to the topic order when there are none

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 11 of the search workflow build. The master file is `docs/product/sw-status.md`; the line-level plan for this slice is `docs/product/sw-slice11-criterion-passages.md`. That file is the single source of truth for what to build. This prompt only sets the rules of the session. Recommended model: Opus, effort medium.

## Ground rules

1. Git: start with `git pull --ff-only`. After that, read-only until the slice is finished. When every task is done and the full test run is green except the one known failure, run `git pull --ff-only` again, then make ONE commit and `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash, reset, rebase or check out files. If the slice is not finished, commit nothing: leave the tree passing and write what remains into row 11 of `sw-status.md`. `TODO.md` and `scripts/local_index.py` may show as the owner's uncommitted work: leave them alone and do not stage them. If any other file you did not touch shows as modified, another session is writing here: stop and report.
2. **`legacy` must behave exactly as before.** `_retrieve` called without the new argument is byte for byte today's code; `FORMULATION_TERMS`, `formulation_score` and `FORMULATION_SCORE_THRESHOLD` stay where they are; a `legacy` answer run opens no new step and its protocol body is unchanged. `_cell_passages`, `chunk_page` and `CHUNK_CHARS` are not touched. No backward overlap is built (owner-visible reason in the slice file).
3. **The order ranks and decides nothing.** No `stage_decisions` row, no selection, no reason code, no deleted or hidden passage. Quote verification keeps running on page text; `domain/contracts.py` is not touched. No model is called; no contract, method file or `skill_package_hash` change; no migration.
4. **Lesson A (slice 10 review): rows left between runs are the research's history, not the run's.** Phrases are read only through `store.frozen_criterion(rid, question, steering)`. The slice file lists what happens to a stale or unanswered row, case by case (revised question, null criterion with an older filled one behind it, a proposal still waiting for approval, an approved empty list, a criterion changed by a second discovery run). Each case needs a test with a name that says it. The `criterion_phrases` step belongs to its run and is frozen: a resumed run reads its stored phrases; another answer run opens its own step and never looks at an earlier run's.
5. **Lesson B: records are shared between researches.** Passages, chunks and embeddings are common rows; phrases are per research. The phrase score is never written to any table and never keyed by passage; it is computed in memory from passages `_retrieve` already loaded for this research's included works. No library-wide phrase search. This slice opens no shared row; if you find you must, stop and report, because membership of the asking research would have to be ensured separately.
6. **Lesson C: `store.step` opens the step it reads.** Only the `_answer` path that executes `criterion_phrases` may call it. Every other read (views, test helpers) uses a path that opens nothing. The slice file names the test: no run of another kind, and no read of a run view, leaves a `pending` `criterion_phrases` step.
7. **Lesson D: the budget looks at the run's total and every started model call counts, failed or not.** This slice adds no model call and no call share; `max_model_calls`, `max_answer_passages` and the embedding step stay as they are, and criterion passages are never found by embedding. If you find you need a call or a share, stop and report; a share is not added without writing down whose share pays for a retry.
8. **Patterns are literal.** Every pattern is built with `re.escape` in the form the slice file gives (the form that was measured). Text written by a model or a user is never compiled as a regular expression. Phrases are normalised with `criterion.norm`; do not write a second normaliser.
9. **One order function.** `criterion_passages.criterion_order` is the only place that ranks by phrases; slices 12 and 16 will call it. Do not build the cue-sentence helper, the Marker page chooser or the full-text reading list (owner's decision, in the slice file).
10. **Existing tests:** only the changes named in the slice file's "Güncellenecek mevcut testler" section are allowed. If any other existing test fails, in particular a passage expectation of an `sw` answer test, the change is wrong or the slice file is; stop and report.
11. **Do not invent.** The pattern form, the score pair, the order key, the two quota rules, the fallback, the step output and the five stale-row cases are complete in the slice file. If a case falls between them, stop and report instead of choosing a workaround. A justified deviation that protects existing behavior is welcome, but name it.
12. No network in tests, and no live step anywhere in this slice: no model call, no provider request, no dry run, no timing measurement (owner's decision: this slice does not measure). Anything you would have measured is written down as "ölçülmedi". Do not start, stop or restart the service on port 8765, and do not open the product database.
13. Match the surrounding style: comment density, naming, short synchronous SQLite transactions, no `await` inside a transaction. Scoring runs once per `_retrieve` call; move it to `asyncio.to_thread` only under the condition the slice file gives, and say which you did.
14. Python runs as `PYTHONPATH=backend:. uv run ...` from the repo root, on the native arm64 venv.
15. Fixture records are SYNTHETIC and from at least two fields. No topic word in product code.
16. `apps/web`: read `.impeccable.md` first; the only change is Task 5 (one step label in EN and TR and its phase).

## Read first

- `AGENTS.md` — whole file (evidence semantics, timeline states, "User Authority").
- `docs/product/sw-status.md` (rows 06, 08a, 10 and the review log entries for 08c and 10), then `docs/product/sw-implementation-plan.md` §2 and the slice 11 entry.
- `docs/product/sw-slice11-criterion-passages.md` — whole file.
- `docs/product/search-workflow-review-2026-09-18.md` — `## SW12` (whole), `## SW15` (points 1–4, Limits and the 21 September addendum).
- `docs/decisions.md` — D17, D27, D55, D78, D80, D83.
- Code, before editing:
  - `backend/deixis/workflow/flow.py`: the constants at the top (`MAX_PASSAGES_PER_SOURCE`, `PDF_PAGES_PER_SOURCE`, `FORMULATION_*`), `formulation_score`, `fuse_rankings`, `answer_source_order`, `_answer`, `_inspect`, `_semantic_ranking`, `_retrieve` whole, `_other_copy_step` (the read that opens nothing), and where `frozen_criterion` is already called.
  - `backend/deixis/workflow/store.py`: `frozen_criterion`, `current_protocol`, `freeze_protocol`, `step` / `start_step` / `finish_step`, `latest_step_output`, `STEP_OUTPUT_KINDS`, `passages_for`, `search_passages`, `included_works`, `answer_version`.
  - `backend/deixis/workflow/criterion.py` (`norm`), `workflow/approval.py::apply_criterion`, `workflow/protocol.py` (`thresholds`), `documents/pdf.py::chunk_page` (read only).
  - `.local/generalized-criterion-2026-09-20/run.py` — `pat` and the score pair in `evaluate`; read only, never import it.
  - `apps/web/src/Transcript.tsx` (`phaseOf`), `labels.ts`, `i18n.ts`.
  - Tests: the answer tests in `tests/test_api_flow.py`, `tests/test_criterion_flow.py`, `tests/test_approval_flow.py` (how an approved criterion reaches the protocol), `tests/test_fulltext_flow.py` (setup helpers and the "steps they had" test), `tests/determinism_stages.py`.

## What to build

Tasks 1–6 of the slice file, in that order.

## Procedure

1. `git pull --ff-only`, `git status --short`, `ls backend/deixis/storage/migrations | tail -1` (expect `0045_fulltext_fetch_run_kind.sql`) and `grep -n '^## D' docs/decisions.md | head -1` (expect D83). This slice takes D84 and no migration; if the number differs, use the next free one and say so.
2. Baseline: `PYTHONPATH=backend:. uv run pytest -q 2>&1 | tail -3`. Record the numbers; the one expected failure is `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`, known on this machine and unrelated. Record the current `skill_package_hash`.
3. Set `sw-status.md` row 11 to `uygulanıyor`.
4. For each task: failing tests first, see them fail, implement, run them.
5. For every function that reads stored state or writes, ask and cover with a test: what happens when the same call is repeated (a second answer run in the same scope; a run paused after the `criterion_phrases` step and resumed; a protocol frozen between the pause and the resume); which protocol row is read after a scope revision, after a revised question, and when the newest row has no criterion; what a user's approved empty list does; whether a PDF another research holds in the same library can enter this answer; whether a `legacy` research, a `pdf_collection` run and a `fulltext_fetch` run stay what they were.
6. Task 6: full test run, web build, lint and Playwright A–H, `git diff --check`, the `D<NN>` entry, the SW12 and SW15 status lines, row 11, the second pull, then the commit and push.

## Final message

- Files created and changed.
- Baseline and final test counts, the exact command, and the Playwright result. `skill_package_hash` before and after (expected: the same).
- The names of the tests showing that the `legacy` selection is unchanged, that no phrases means the topic order, that a revised question's old phrases are not used, that a resumed run uses its stored phrases, that a read opens no step, and that the number of model sessions is unchanged.
- Whether scoring runs on the event loop or in `asyncio.to_thread`.
- Every point where the slice file could not be followed as written, and every deviation you chose, with its reason.
- What you did NOT do, and everything left unmeasured, named as "ölçülmedi".
- Which evidence boundaries were touched (expected: in an `sw` answer part of the passages the model sees is now chosen by phrases a model proposed and the user approved — the choice ranks, it decides nothing; an `sw` answer without a criterion loses the formulation quota).
- Confirmation that the live service and the product database were not touched, and the commit hash.
