# Task: SW slice 02 — stage decisions storage

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 02 of the search workflow build. The master file is `docs/product/sw-status.md`; the line-level plan for this slice is `docs/product/sw-slice02-stage-decisions.md`. That file is the single source of truth for what to build. This prompt only sets the rules of the session. Recommended model: Opus, effort high.

## Ground rules

1. Run NO state-changing git command: no commit, push, stash, reset, checkout of files, or branch. Read-only git is fine.
2. **Do not touch** `apps/web/`, `contracts/research/`, `methods/deixis-research/`, `backend/deixis/workflow/flow.py`, or any existing migration file. No contract or method file changes, so `skill_package_hash` must not change.
3. **Nothing writes to the new tables from the product flow in this slice.** You build tables, a store class, the derivation function and their tests. If you find yourself wiring a call into `flow.py`, `api/app.py` or `views.py`, stop: that belongs to a later slice.
4. **No existing test expectation may change.** The `legacy` workflow must behave exactly as before. If an existing test fails after your change, the change is wrong or the slice file is; stop and report.
5. **Do not invent.** If something cannot be built as the slice file says, stop and report it instead of choosing a workaround. A justified deviation that protects existing behavior (as slice 01's purge exception did) is welcome, but name it.
6. The user's selection always wins: a `selections` row with `origin = 'user'` never has its `state` changed by derivation.
7. Match the surrounding style: comment density, naming, short synchronous SQLite transactions, no `await` inside a transaction.
8. Python runs as `PYTHONPATH=backend:. uv run ...` from the repo root, on the native arm64 venv. Do not start, stop or restart the service on port 8765; tests use their own temporary data directory.
9. Fixture records are SYNTHETIC. A passing test shows workflow behavior, not model quality.

## Read first

- `AGENTS.md` — whole file; "User Authority and Workflow Boundaries", the Evidence Contract, the backend rules and the Completion Report apply.
- `docs/product/sw-status.md`, then `docs/product/sw-implementation-plan.md` §2.
- `docs/product/sw-slice02-stage-decisions.md` — whole file.
- `docs/product/search-workflow-review-2026-09-18.md` — SW9 points 4–5 and SW11 points 1–7 and 10–11 (search for `## SW9`, `## SW11`).
- Code, before editing:
  - `backend/deixis/workflow/tables.py`: `TableStore` (~108) and `purge_tables`, the pattern `DecisionStore` follows.
  - `backend/deixis/workflow/store.py`: `purge_research` (~243), `_bump_selection_revision` (~312), `freeze_protocol` / `current_protocol` (~475), `work_heads` (~1367), `_settle_work_head` (~1385), `purge_sources` (~1586), `apply_screening_proposal` (~1690, the three writes derivation must repeat), `set_user_selection` (~1742).
  - `backend/deixis/domain/canonical.py` and `backend/deixis/domain/rules.py::effective_selection`.
  - Migrations: `0001_initial.sql` (`selections`, `selection_history`), `0010` (purge authorizations), `0021_library_membership.sql` and `0019_table_run_kinds.sql` (table rebuild pattern), `0037_protocol_records.sql` (delete trigger with the purge exception).
  - Tests: `tests/test_migrations.py`, `tests/test_protocol_record.py` (`store_for`), `tests/test_corpus_removal.py` (purge tests), `tests/determinism_stages.py`, `tests/test_source_versions.py` (how a work with two versions is set up).

Line numbers are approximate; find the symbol.

## What to build

Tasks 1–7 of the slice file, in that order.

## Procedure

1. `git status --short` (expect a clean tree) and `ls backend/deixis/storage/migrations | tail -1` (expect `0037_protocol_records.sql`). If either differs, say so before going on.
2. Baseline: `PYTHONPATH=backend:. uv run pytest -q 2>&1 | tail -3`. Expect `1 failed, 733 passed`; the one failure is `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`, known on this machine and unrelated.
3. Set `sw-status.md` row 02 to `uygulanıyor`.
4. For each task: failing tests first, see them fail, implement, run them.
5. For every write function ask the two questions slice 01 missed, and cover each with a test: what happens when the same call is repeated (a resumed run), and what happens on permanent deletion (`purge_research`, `purge_sources`).
6. The `selections` rebuild is the riskiest step: test it with rows inserted before the migration runs (see how `tests/test_migrations.py` applies migrations up to a number), and compare every column after it.
7. Task 7: full test run, `git diff --check`, the `D<NN>` entry (check the next free number first), the SW9 and SW11 status lines, and row 02 in `sw-status.md`.

If the session is running long and the work will not finish with tests green, stop at a task boundary, leave the tree passing, and write the remaining tasks into row 02 of `sw-status.md`.

## Final message

- Files created and changed.
- Baseline and final test counts, and the exact command used.
- How you verified that the `selections` rebuild kept every existing row and column.
- Every point where the slice file could not be followed as written, and every deviation you chose, with its reason.
- What you did NOT do.
- Which evidence boundaries were touched (expected: selection logic, reachable only from the new function and only for `sw` researches).
- Confirmation that the live service was not touched and nothing was committed.
