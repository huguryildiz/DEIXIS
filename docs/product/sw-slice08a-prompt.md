# Task: SW slice 08a — an sw discovery run stops before its first search until the user approves or corrects the vocabulary and the criterion (backend only)

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 08a of the search workflow build. The master file is `docs/product/sw-status.md`; the line-level plan for this slice is `docs/product/sw-slice08a-protocol-approval-backend.md`. That file is the single source of truth for what to build. This prompt only sets the rules of the session. Recommended model: Opus, effort high.

## Ground rules

1. Git: start with `git pull --ff-only`. After that, read-only until the slice is finished. When every task is done and the full test run is green except the one known failure, run `git pull --ff-only` again, then make ONE commit and `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash, reset, rebase or check out files. If the slice is not finished, commit nothing: leave the tree passing and write what remains into row 08a of `sw-status.md`. `TODO.md` and `scripts/local_index.py` may show as the owner's uncommitted work: leave them alone and do not stage them. If any other file you did not touch shows as modified, another session is writing here: stop and report.
2. **Do not touch** `apps/web/`, any migration file, any contract schema or the method package. This slice needs no migration. `skill_package_hash` must not change; record it before and after.
3. **The `legacy` workflow must behave exactly as before.** No approval step opens there, the run never stops for approval, and a legacy protocol body and its digest stay the same.
4. **No existing test expectation may change.** Existing test files that drive an `sw` run to its end get `protocol_approval="as_proposed"` in their `Settings(...)` setup; that is a setup change, and every file touched that way is named in the final message, as is every test updated for the step order. If any other existing test fails, the change is wrong or the slice file is; stop and report.
5. **No search before approval.** In `ask` mode, when the run stops there is no `provider_search` step, no candidate and no protocol record, and the mocked provider has seen count probes only. A plain `resume` on a run waiting for approval is refused.
6. **No new model call.** Approval never re-runs the criterion or the labelling step.
7. **The user's correction stands above the model and the rule**, and nothing is edited in place: the proposal stays in the step output as it was, the approved form is written beside it, and a frozen protocol record is never changed.
8. **One code path builds a vocabulary.** A corrected vocabulary is rebuilt through `vocabulary.build_vocabulary` from an `Extraction`, never by patching term dictionaries. Counts the proposal already read are not asked again; an approval without a term edit sends no request and keeps the proposal's queries byte for byte.
9. **The approval must not be lost on the way.** The `protocol` step, `_freeze_expansion`, `_expansion`, `_second_sources` and `_ranking` all read the approved vocabulary, queries and criterion. An expansion revision that carries the proposal instead undoes the user's correction and marks every decision stale.
10. **Network work runs in the worker, not in the route.** The route validates, stores the submission and queues the run in one transaction.
11. **Do not invent.** The edit operations, their validation, the reuse rule for an earlier approval, the step output and the view shape are complete in the slice file. If a case falls between them, stop and report instead of choosing a workaround. A justified deviation that protects existing behavior is welcome, but name it.
12. No network in tests, and no live step anywhere in this slice. Do not start, stop or restart the service on port 8765, and do not open the product database.
13. Match the surrounding style: comment density, naming, short synchronous SQLite transactions, no `await` inside a transaction, UI-visible events written in the same transaction as the state they describe.
14. Python runs as `PYTHONPATH=backend:. uv run ...` from the repo root, on the native arm64 venv.
15. Fixture questions, terms and criteria are SYNTHETIC and from at least two fields. No topic word in product code.

## Read first

- `AGENTS.md` — whole file ("User Authority" and the timeline state rules matter here).
- `docs/product/sw-status.md` (rows 04a, 04d, 06, 07 and the review log for 04a, 04d, 06, 07), then `docs/product/sw-implementation-plan.md` §2 and the slice 08 entry.
- `docs/product/sw-slice08a-protocol-approval-backend.md` — whole file. Skim `docs/product/sw-slice08b-protocol-approval-ui.md` for what the screen will need from the view.
- `docs/product/search-workflow-review-2026-09-18.md` — `## SW2` (points 1, 5, 6), `## SW15` (point 3), `## SW14` (points 1, 2), `## SW17` (point 2), SW11 point 10.
- `docs/decisions.md` — D70, D73, D74, D76, D78, D79.
- Code, before editing:
  - `backend/deixis/workflow/flow.py`: `_discovery` whole, `_pause`, `_checkpoint`, `_vocabulary`, `_searchable`, `_vocabulary_labels`, `_criterion`, `_count_probe`, `_expansion`, `_freeze_expansion`, `_second_sources`, `_ranking`.
  - `backend/deixis/workflow/vocabulary.py` whole (`build_vocabulary`, `apply_labels`, `TERM_FIELDS`, `LABELS`, `MAX_PROBES`); `domain/vocabulary.py` (`Extraction`, `extract`, how `key_terms` is parsed); `workflow/criterion.py` (`norm`, `consensus`); `workflow/expansion.py` (`second_round_vocabulary`, `term_rows`); `providers/query_compiler.py::compile_block_queries`.
  - `backend/deixis/workflow/protocol.py` whole; `workflow/store.py`: `step`, `set_step_output`, `start_step`, `finish_step`, `update_run`, `freeze_protocol`, `current_protocol`, `frozen_criterion`, `revise_scope`; `workflow/decisions.py`: `CRITERION_FIELDS`, `is_stale`; `workflow/worker.py::recover`.
  - `backend/deixis/api/app.py`: `control_run`, the run creation route, the scope revision route, the CSRF middleware; `workflow/views.py::research_view`; `config.py` (`Settings`, the environment loader).
  - `tests/acceptance/fixture_server.py`.
  - Tests: `tests/test_vocabulary_flow.py`, `tests/test_vocabulary_labels.py`, `tests/test_criterion_flow.py`, `tests/test_expansion_flow.py`, `tests/test_ranking_flow.py`, `tests/test_protocol_record.py`, `tests/determinism_stages.py`.

## What to build

Tasks 1–6 of the slice file, in that order.

## Procedure

1. `git pull --ff-only`, `git status --short`, `ls backend/deixis/storage/migrations | tail -1` (expect `0044_record_references.sql`) and `grep -n '^## D' docs/decisions.md | head -1` (expect D79). This slice takes D80 and no migration; if the number differs, use the next free one and say so.
2. Baseline: `PYTHONPATH=backend:. uv run pytest -q 2>&1 | tail -3`. Record the numbers; the one expected failure is `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`, known on this machine and unrelated. Record the current `skill_package_hash`.
3. Set `sw-status.md` row 08a to `uygulanıyor`.
4. For each task: failing tests first, see them fail, implement, run them.
5. For every function that writes or calls out, ask and cover with a test: what happens when the same call is repeated (the approval posted twice; a run paused and resumed after approval; a second discovery run; a scope revision with the same question, and one with another; a scope revision that arrives while the run waits); what happens when a submitted edit empties the vocabulary or makes it too broad; does the result depend on the order the edit operations arrive in; does the expansion revision still carry the correction; does a `legacy` protocol digest stay what it was; does a run in `as_proposed` mode ever look user-approved.
6. Task 6: full test run, `git diff --check`, the `D<NN>` entry, the SW2 and SW15 status lines, row 08a, the second pull, then the commit and push.

## Final message

- Files created and changed.
- Baseline and final test counts, and the exact command used. `skill_package_hash` before and after (expected: equal).
- The names of the tests showing that no search request leaves before approval, that an approval without a term edit sends no count request, and that the expansion revision carries the correction.
- Every existing test file whose setup was switched to `as_proposed`, and every existing test updated for the step order.
- Which way the count cache was built (wrapper, or a `known` argument to `build_vocabulary`), and why.
- Every point where the slice file could not be followed as written, and every deviation you chose, with its reason.
- What you did NOT do.
- Which evidence boundaries were touched (expected: the `sw` protocol body gains `approval`; an `sw` run no longer searches without the user's approval).
- Confirmation that the live service and the product database were not touched, and the commit hash.
