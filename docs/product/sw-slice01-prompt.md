# Task: SW slice 01 — protocol record and determinism

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 01 of the search workflow build. The master file is `docs/product/sw-status.md`; the line-level plan for this slice is `docs/product/sw-slice01-protocol-and-determinism.md`. That file is the single source of truth for what to build. This prompt only sets the rules of the session.

## Ground rules

1. Run NO state-changing git command: no commit, push, stash, reset, checkout of files, or branch. Read-only git (`status`, `diff`, `log`) is fine.
2. **Do not touch** `apps/web/`, `contracts/research/`, `methods/deixis-research/`, any existing file in `backend/deixis/storage/migrations/`, or the untracked `.playwright-mcp/` and `skills-lock.json`. This slice changes no contract and no method file, so `skill_package_hash` must not change.
3. **Do not invent.** If something cannot be built as the slice file says (a function is not where it says, a test expectation changes for a reason other than a score tie, a column already exists), stop and report it instead of choosing a workaround.
4. No scope beyond the slice file: no UI, no new dependency, no refactor of adjacent code, no branching on `search_workflow` (it is stored and written into the protocol, nothing reads it yet).
5. Match the surrounding style: comment density, naming, short synchronous SQLite transactions, no `await` inside a transaction, UI-visible events written in the same transaction as the state they describe.
6. Python runs as `PYTHONPATH=backend:. uv run ...` from the repo root, on the native arm64 venv. Do not start, stop or restart the service on port 8765, and do not run anything against the live data directory; tests use their own temporary one.
7. Fixture records are SYNTHETIC. A passing test shows workflow behavior, not model quality; say so where you report results.

## Read first

- `AGENTS.md` — whole file; the Evidence Contract, the backend/contract rules and the Completion Report section apply.
- `docs/product/sw-status.md` — where this slice sits.
- `docs/product/sw-implementation-plan.md` — §2 only (rules for every slice).
- `docs/product/sw-slice01-protocol-and-determinism.md` — whole file.
- `docs/product/search-workflow-review-2026-09-18.md` — the SW14 entry only (search for `## SW14`).
- Code, before editing:
  - `backend/deixis/workflow/flow.py`: `fuse_rankings` (~line 79), `answer_source_order` (~95), `_discovery` (~211–289, the protocol step goes after the compiled queries are stored and before the `_search` loop), `_search` payload write (~366–380), `_model_step` (~1058).
  - `backend/deixis/workflow/store.py`: `STEP_OUTPUT_KINDS` (~31), `create_research` (~112, note the `seed_mode` column guard), `scope` / `revise_scope` (~326–363) and the second scope insert path (~436–452), `step` (~551), `insert_step_input` (~621), `finish_model_session` (~646), `included_works` (~1339), `add_search_run` (~1372), `search_passages` (~1722).
  - `backend/deixis/config.py` (the `query_strategy` pattern), `backend/deixis/domain/rules.py` (`step_model`, `effective_reviewer`, `SCREENING_BATCH`).
  - `backend/deixis/storage/migrations/0001_initial.sql` (`run_steps`, `step_inputs` and its immutability triggers, `model_sessions`) and one recent `ALTER TABLE` migration for style.
  - `tests/test_migrations.py`, `tests/test_provider_flow.py`, `tests/test_semantic_retrieval.py`, `tests/fakes.py`, and `app_for()` in `tests/test_api_flow.py`.

Line numbers are approximate; find the symbol.

## What to build

Tasks 1–7 of the slice file, in that order. Each task lists its files, interfaces, the failing tests to write first, and the command that must pass.

## Procedure

1. `git status --short` and `ls backend/deixis/storage/migrations | tail -1`. Expect a clean tree apart from `.playwright-mcp/` and `skills-lock.json`, and `0036_report_section_ii.sql` as the last migration. If either differs, say so before going on.
2. Baseline: `PYTHONPATH=backend:. uv run pytest -q 2>&1 | tail -3`. Record the counts. If anything fails at baseline, name it and continue only if it is unrelated to this slice.
3. Set `sw-status.md` row 01 to `uygulanıyor`.
4. For each task: write the failing tests, see them fail, implement, run the task's command. For Task 6, write the replay test before Task 5's change if you can, and say whether you saw it red for `fuse_rankings`.
5. When an existing test's expected order changes in Task 5, check that the two rows really have equal scores before changing the expectation. If they do not, stop.
6. Task 7: full `PYTHONPATH=backend:. uv run pytest`, `git diff --check`, the draft `D<NN>` entry at the top of `docs/decisions.md` (check the next free number first; other sessions add decisions), the SW14 status line, and row 01 in `sw-status.md` set to `uygulandı, inceleme bekliyor` with what is left open.

If the session is running long and the work will not finish with tests green, stop at a task boundary, leave the tree passing, and write the remaining tasks into row 01 of `sw-status.md`.

## Final message

- Files created and changed.
- Baseline and final test counts, and the exact command used.
- Every existing test expectation you changed, with the reason.
- Every place a `set` was iterated on the way to an output: what you found, what you changed, what you left and why.
- Every point where the slice file could not be followed as written.
- What you did NOT do.
- Which evidence boundaries were touched (none are expected: no citation, anchor, selection or version logic changes).
- Confirmation that the live service was not touched and nothing was committed.
