# Task: SW slice 09, Task 5 — the abstract screening calls of an sw run are sent concurrently through the run's limiter

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. Slice 09 was committed as `c12af9b` without its Task 5 (the split point its slice file allows): the (batch, run) calls of `flow._abstract_stage` still go out one after another, so a standard-effort read is 10 sequential model calls. This session builds Task 5 of `docs/product/sw-slice09-abstract-screening.md` and nothing else. That section is the single source of truth. Recommended model: Opus, effort high.

## Ground rules

1. Git: start with `git pull --ff-only`. Read-only until the task is finished. When the full test run is green except the one known failure, `git pull --ff-only` again, then ONE commit and `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash, reset, rebase or check out files. If the task is not finished, commit nothing. `TODO.md`, `scripts/local_index.py` and the two `docs/product/sw-slice08c-*` files may show as the owner's uncommitted work: leave them alone and do not stage them. Any other modified file you did not touch means another session is writing here: stop and report.
2. **No second concurrency mechanism.** The loop is the one `_table_fill` uses (`deps.limiter`, `_checkpoint` before each submission, calls in flight finish and write their steps when the run is stopped, a rate-limit answer goes through `limiter.reduce()`). Extracting that loop into a shared helper is allowed; `_table_fill`'s behavior and tests must not change.
3. **The decisions must be the ones sequential sending gives.** The frozen read plan, the step keys (`abstract_screening:{batch}:{run}`), the budget rule (a batch is read twice or not at all) and `_close_abstract_batch` stay as they are. A batch is closed on the event loop, in short transactions, only when both of its runs have finished; never `await` inside a transaction.
4. The budget check must hold under concurrency: no submission may take the run past `max_model_calls`, and a batch whose two calls no longer fit is not half-sent.
5. `legacy` is untouched. No contract, method package, migration or `apps/web` change; `skill_package_hash` stays what it is (record it before and after).
6. **No existing test expectation may change.** No network in tests; fixtures SYNTHETIC. No live model call, no provider request, no dry run. Do not touch the service on port 8765 or the product database.
7. Do not invent. If a case falls outside Task 5 as written, stop and report; a justified deviation that protects existing behavior is welcome, but name it.
8. Python runs as `PYTHONPATH=backend:. uv run ...` from the repo root, on the native arm64 venv.

## Read first

- `docs/product/sw-status.md` row 09; `docs/product/sw-slice09-abstract-screening.md` — Task 4 and Task 5, and the K3 paragraph.
- `backend/deixis/workflow/flow.py`: `_abstract_stage`, `_abstract_call`, `_close_abstract_batch`, the budget helper above `_abstract_call`, `_table_fill`'s submission loop, `_call_adapter`, `_model_step`; `backend/deixis/workflow/concurrency.py` whole.
- Tests: `tests/test_abstract_flow.py`, and the table-fill tests that cover the limiter, a pause while calls are in flight, and a rate-limit answer.

## Procedure

1. Pull, `git status --short`, baseline `PYTHONPATH=backend:. uv run pytest -q 2>&1 | tail -3` (the one expected failure is `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`).
2. Tests first, see them fail: at most `limiter.limit` calls in flight at once; the decision table equals the one sequential sending writes for the same fake outputs; a pause stops new submissions, the calls in flight write their steps, and resuming calls only what is missing; a batch with one invalid run closes as it does today; the budget is never passed and no batch is half-sent; a rate-limit answer lowers the limit.
3. Implement, run the abstract, table-fill and determinism tests, then the full run and `git diff --check`.
4. Row 09 of `sw-status.md`: replace the "Task 5 yapılmadı … sırayla gidiyor" sentence with what was built and the commit; D81's Limits lose the matching sentence if they carry one. The row's status stays `uygulandı, inceleme bekliyor`: the full review reads both commits.

## Final message

Files changed; baseline and final test counts and the command; `skill_package_hash` before and after (expected: equal); whether the loop was shared or mirrored, and why; the names of the new tests; every deviation and everything not done; confirmation that no live service, model or database was touched; the commit hash.
