# Task: SW slice 13d — the code stage stops holding the event loop: measure first, then batch the reads and writes, output byte for byte the same

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 13d of the search workflow build. The master file is `docs/product/sw-status.md`; the line-level plan is `docs/product/sw-slice13d-code-stage-speed.md`. No decision record: behaviour does not change. The slice file is the single source of truth; this prompt only sets the rules of the session. Implementer: Opus · medium. The review is done later, together with 13b and 13c.

**This slice runs in parallel with 13b, so it works in its own worktree.** 13b touches `providers/registry.py`, `providers/query_compiler.py`, `flow._discovery`'s provider list, the search step, `api/app.py` and the UI labels. You touch `flow._abstract_code_stage`, `_write_abstract_codes`, `workflow/decisions.py`, `workflow/criterion.py`, `workflow/views.py` and, if an index is needed, migration `0048`. If your work needs one of 13b's files changed, stop and report.

## Ground rules

1. Git, worktree variant: from the main checkout run `git pull --ff-only`, then `git worktree add --detach /Users/huguryildiz/Documents/GitHub/DEIXIS-13d main` and work ONLY inside `/Users/huguryildiz/Documents/GitHub/DEIXIS-13d` (`uv sync` there first; the venv must be arm64). Read-only until the slice is finished. When every task is done and the full test run is green except the one known failure: `git fetch origin`; if `origin/main` moved (13b landed), `git rebase origin/main` is allowed here and only here, because these commits exist in no other tree; if the rebase conflicts, stop and report. Then ONE commit (`git commit`), `git push origin HEAD:main`, and `git worktree remove /Users/huguryildiz/Documents/GitHub/DEIXIS-13d` from the main checkout. No branch is pushed, no PR, no AI attribution, no co-author. Never stash or reset. If the slice is not finished, push nothing: leave the worktree in place and write what remains into row 13d of `sw-status.md` in the worktree, then say so.
2. **Behaviour is identical.** Same input → same `stage_decisions` rows, same `selections`, same step output, same events, same order. The proof is a test that captures the code stage's output and decision rows before your change (write it first, on the unchanged code, with synthetic data that has: several works with several versions, a human decision that must be skipped, a stale decision, a record with an `artifact_of` link, a survey title word) and asserts equality after. `tests/determinism_stages.py` is the pattern.
3. **Measure before and after** on a COPY of `/Users/huguryildiz/Documents/GitHub/DEIXIS/.local/sw-smoke-2026-09-22/data-3/library.sqlite` (research `res_WHbBqsPV0ZnOZyxQvF5i`; open the original read-only with `sqlite3.connect('file:…?mode=ro', uri=True)` only to copy it, never write to it). `cProfile` the three functions the slice file names; write the profiles and the before/after times to `/Users/huguryildiz/Documents/GitHub/DEIXIS/.local/sw-code-stage-2026-09-22/` (not in the repo) and the three hottest frames into row 13d.
4. **Event-loop rule stays:** short synchronous transactions, no `await` inside one, no `asyncio.to_thread` for store work (one SQLite connection on the loop thread). Speed comes from fewer statements (whole-research reads in a few queries, `executemany` writes in one transaction, dict lookups instead of nested scans), never from threads.
5. `HumanDecisionStands` is still not swallowed; a human decision is still skipped; `derive_selection` semantics are unchanged (call it once per touched work, batched if you like, same result).
6. Existing tests: only the changes the slice file names. Do not invent; if a case falls between the rules, STOP AND REPORT.
7. No network in tests, no live model, no live provider. Do not start, stop or query the service on port 8765 and do not open the product database.
8. Python runs as `PYTHONPATH=backend:. uv run ...` from the worktree root; the suite runs in parallel by default (about 75 s). Fixture records are SYNTHETIC and from at least two fields; no topic word in product code.

## Read first

- `AGENTS.md`, `CLAUDE.md`; `docs/product/sw-status.md` ("Bir tur", rows 05, 07, 09, 13, 13d, and the review log: the 04b and 05 rows are about exactly this kind of cost); the slice file whole; `docs/decisions.md` D71, D77, D79, D81.
- Code: `backend/deixis/workflow/flow.py` (`_abstract_code_stage`, `_abstract_decisions`, `_artifact_links`, `_write_abstract_codes`, `_criterion` and what it counts), `workflow/decisions.py` (whole: `current`, `record`, `is_stale`, `derive_selection`, `HumanDecisionStands`), `workflow/abstract_stage.py` (`code_outcome`, `should_write`, `read_plan`), `workflow/criterion.py` (the count queries), `workflow/views.py` (`research_view`, the `ordered` loop after `work_heads`), `workflow/store.py` (`answer_versions` from `fe7c31d` as the pattern for a batched read, `candidates`, `work_heads`, `source`), `storage/migrations/0047_source_versions_work_id.sql`; tests: `tests/test_abstract_flow.py`, `tests/test_view_scaling.py` (the statement-count pattern), `tests/determinism_stages.py`, `tests/test_stage_decisions*.py`.

## What to build

Tasks 1–3 of the slice file, in that order.

## Procedure

1. Worktree as in rule 1; `git status --short`; `ls backend/deixis/storage/migrations | tail -1` (expect `0047`; take `0048` only if an index is needed and say so).
2. Baseline test run and the before-profile (Task 1).
3. Set row 13d to `uygulanıyor` (in the worktree's `sw-status.md`).
4. Equality test first on the unchanged code, then the scaling test (statement count does not grow with records), then the change.
5. After-profile on the same copy; the numbers go into row 13d with the targets from the slice file (≤ 20 s / 15 s / 3 s) and whether each was met.
6. Task 3: full test run, `git diff --check`, row 13d, fetch (rebase only if needed), commit, push `HEAD:main`, remove the worktree.

## Final message

Files changed; baseline and final test counts; before/after times for the three functions on the data-3 copy and the three hottest frames before; the name of the equality test and of the scaling test; whether a migration was added; every deviation with its reason; what is "ölçülmedi" (another machine, another topic, the provider share of `criterion`); confirmation that the live service, the product database and the original `data-3` file were not written; the commit hash.
