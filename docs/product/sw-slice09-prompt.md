# Task: SW slice 09 — an sw discovery run screens abstracts with a code stage and two batched model runs whose quotes code verifies; nothing is included from an abstract and what is not read stays unread, not dropped

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 09 of the search workflow build. The master file is `docs/product/sw-status.md`; the line-level plan for this slice is `docs/product/sw-slice09-abstract-screening.md`. That file is the single source of truth for what to build. This prompt only sets the rules of the session. Recommended model: Opus, effort high.

## Ground rules

1. Git: start with `git pull --ff-only`. After that, read-only until the slice is finished. When every task is done and the full test run is green except the one known failure, run `git pull --ff-only` again, then make ONE commit and `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash, reset, rebase or check out files. If the slice is not finished, commit nothing: leave the tree passing and write what remains into row 09 of `sw-status.md`. The one allowed partial finish is named in the slice file: Tasks 1–4 and 6–8 without Task 5. `TODO.md` and `scripts/local_index.py` may show as the owner's uncommitted work: leave them alone and do not stage them. If any other file you did not touch shows as modified, another session is writing here: stop and report.
2. **The `legacy` workflow must behave exactly as before.** Its `screening` contract, its batch loop, the `max_candidates` cut, its protocol body and digest, and `TEST_EFFORT_BUDGETS` stay byte for byte. The extra model calls are added to an `sw` discovery run in `api/app.py` only.
3. **Nothing is included from an abstract.** In an `sw` run `apply_screening_proposal` is never called and no selection becomes `included` in this slice. Selections change only through `DecisionStore.derive_selection`.
4. **Code decides; the model proposes** a label, one quote and one sentence. Code verifies the quote with `contracts.locate_anchor` (`exact` or `normalized` only, at least `ABSTRACT_QUOTE_MIN_CHARS`) in the abstract text the model was shown, and the rule table in the slice file turns two runs into one reason code. Do not add a row to that table.
5. **No record is deleted or hidden, and the user's decision stands.** A record without an abstract is never `out_of_scope`. The codes slice 05 owns (`no_abstract`, `abstract_not_found`, `survey_title_word`) are left alone.
6. **One matcher, one quote finder.** Block presence uses the form matching `ranking.block_scores` uses, moved to a shared helper, on the `blocks` `ranking.query_vocabulary` returns. Do not write a second normaliser or a second matcher.
7. **The read plan is frozen in the `abstract_stage` step output** and a resumed run reads it back instead of computing it again. Batch keys must mean the same records before and after a pause (this exact bug was found in the slice 07 review).
8. **A failed batch loses nothing.** An invalid output does not stop the run and is not repaired; its records stay `abstract_not_proposed` and a later run reads them. A resumed run does not call that step again.
9. The model sees the question and the records, never the criterion sentence, its parts, the cue phrases or the blocks. This was measured: showing the criterion made the model judge it from the abstract.
10. **Existing tests:** only the tests named in the slice file's "Güncellenecek mevcut testler" section may be re-pointed from an sw run's `screening` step to the new step, keeping what they expect. If any other existing test fails, the change is wrong or the slice file is; stop and report.
11. **Do not invent.** The code-stage order, the reading-version rule, the plan, the rule table, the budget formula and the step outputs are complete in the slice file. If a case falls between them, stop and report instead of choosing a workaround. A justified deviation that protects existing behavior is welcome, but name it.
12. No network in tests, and no live step anywhere in this slice: no model call, no provider request, no dry run. Do not start, stop or restart the service on port 8765, and do not open the product database.
13. Match the surrounding style: comment density, naming, short synchronous SQLite transactions, no `await` inside a transaction, UI-visible events written in the same transaction as the state they describe. Whole-research reads in a few queries, not one query per record (slice 05 and 07 reviews measured a second per 2,000 records on the API thread).
14. Python runs as `PYTHONPATH=backend:. uv run ...` from the repo root, on the native arm64 venv.
15. Fixture questions, records and abstracts are SYNTHETIC and from at least two fields. No topic word in product code or in the method file.
16. `apps/web`: read `.impeccable.md` first; the only change is Task 7 (two step kinds mapped to the screening phase, two labels in EN and TR).

## Read first

- `AGENTS.md` — whole file ("User Authority", evidence semantics, timeline states).
- `docs/product/sw-status.md` (rows 02, 03, 05, 06, 07, 08a and the review log for 05, 06, 07), then `docs/product/sw-implementation-plan.md` §2 and the slice 09 entry.
- `docs/product/sw-slice09-abstract-screening.md` — whole file.
- `.local/sw-abstract-batch-2026-09-21/result.md` and `run_generic.py` (`GENERIC2` is the text the method file carries).
- `docs/product/search-workflow-review-2026-09-18.md` — `## SW9`, `## SW1` (points 1, 2, 6), `## SW11` (points 1, 3, 4), `## SW6` (point 2), `## SW5` (point 5).
- `docs/decisions.md` — D71, D72, D77, D78, D79, D80, and D12 (citation handles), D37 (concurrent table fill).
- Code, before editing:
  - `backend/deixis/workflow/flow.py`: `_discovery` whole, `_second_sources`, `_ranking`, `_table_fill` and `_fill_jobs`, `_extraction` (the guard for a step that ended `invalid_model_output`), `_step_input`, `_model_step`, `_call_adapter`, `_checkpoint`, `_pause`.
  - `backend/deixis/workflow/decisions.py` whole; `domain/reason_codes.py` whole; `workflow/lookups.py`: `flag_and_decide`, `_wanted_decision`, `_should_write`, `held_from_screening`, `OWNED_CODES`.
  - `backend/deixis/workflow/ranking.py`: `block_scores`, `_padded`, `_versions`, `_work_row`, `query_vocabulary`; `workflow/concurrency.py`.
  - `backend/deixis/domain/contracts.py`: `locate_anchor`, `citation_handles`, `with_citation_handles`, `resolve_citation_handles`, `_check_vocabulary_labels` and `_check_criterion_proposal` (the pattern for a new task), `step_output_schema`; `domain/rules.py` (`LITERATURE_TASKS`, `NO_REPAIR_TASKS`, `TEST_EFFORT_BUDGETS`, `CRITERION_CALLS`); `domain/skill.py`; `domain/record_identity.py::record_kind`; `workflow/links.py` (how an `artifact_of` link is stored and undone).
  - `backend/deixis/workflow/protocol.py` (`thresholds`); `api/app.py` (run creation, the `CRITERION_CALLS` line); `apps/web/src/Transcript.tsx::phaseOf`, `labels.ts`.
  - `tests/fakes.py::valid_response`, `tests/fixtures/research/*.json`, `tests/acceptance/fixture_server.py`, `tests/determinism_stages.py`.
  - Tests: `tests/test_stage_decisions.py`, `tests/test_ranking_flow.py`, `tests/test_lookup_flow.py`, `tests/test_vocabulary_flow.py`, `tests/test_criterion_flow.py`, the table-fill concurrency tests.

## What to build

Tasks 1–8 of the slice file, in that order.

## Procedure

1. `git pull --ff-only`, `git status --short`, `ls backend/deixis/storage/migrations | tail -1` (expect `0044_record_references.sql`) and `grep -n '^## D' docs/decisions.md | head -1` (expect D80). This slice takes D81 and no migration; if the number differs, use the next free one and say so.
2. Baseline: `PYTHONPATH=backend:. uv run pytest -q 2>&1 | tail -3`. Record the numbers; the one expected failure is `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`, known on this machine and unrelated. Record the current `skill_package_hash`.
3. Set `sw-status.md` row 09 to `uygulanıyor`.
4. For each task: failing tests first, see them fail, implement, run them.
5. For every function that writes or calls out, ask and cover with a test: what happens when the same call is repeated (a second discovery run in the same scope; a run paused between two batches, between the two runs of one batch, and after the code stage; a batch closed twice); what happens after a scope revision (stale decisions are read again, fresh ones are not); what a user decision, a slice 05 code or a permanent delete of a source does to the plan; whether the result depends on the order calls finish in; whether a `legacy` protocol digest and a `legacy` run's steps stay what they were.
6. Task 8: full test run, web build, lint and Playwright A–H, `git diff --check`, the `D<NN>` entry, the SW9 and SW11 status lines, the K3 line of the plan, row 09, the second pull, then the commit and push.

## Final message

- Files created and changed.
- Baseline and final test counts, the exact command, and the Playwright result. `skill_package_hash` before and after (expected: different).
- The names of the tests showing that no selection becomes `included`, that a second run reads on from where the first stopped, that a resumed run reads the stored plan, that a failed batch loses no record, and that `legacy` is unchanged.
- Every existing test re-pointed to the new step.
- Whether Task 5 was done; if so, the test showing the concurrent and the sequential run reach the same decisions.
- Every point where the slice file could not be followed as written, and every deviation you chose, with its reason.
- What you did NOT do.
- Which evidence boundaries were touched (expected: in an `sw` run the model no longer writes a selection, code does; an agreed `out_of_scope` sets the selection to `excluded` with origin `code_rule`; no work is included from an abstract, so until slice 12 an `sw` research includes nothing by itself).
- Confirmation that the live service and the product database were not touched, and the commit hash.
