# Task: SW slice 03 — record kind and version links

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 03 of the search workflow build. The master file is `docs/product/sw-status.md`; the line-level plan for this slice is `docs/product/sw-slice03-record-kind-and-version-links.md`. That file is the single source of truth for what to build. This prompt only sets the rules of the session. Recommended model: Opus, effort high.

## Ground rules

1. Git: read-only until the slice is finished. When every task is done and the full test run is green except the one known failure, make ONE commit and `git push origin main`. No branch, no PR, no AI attribution in the commit message, no co-author. Never stash, reset, rebase or check out files. If the slice is not finished, commit nothing: leave the tree passing and write what remains into row 03 of `sw-status.md`.
2. **Do not touch** `apps/web/`, `contracts/research/`, `methods/deixis-research/`, `backend/deixis/workflow/flow.py`, `backend/deixis/workflow/views.py`, `backend/deixis/api/`, or any existing migration file. `skill_package_hash` must not change.
3. **The `legacy` workflow must behave exactly as before.** `is_preprint`, `is_published`, `same_publication`, `_flag_suspected_duplicates`, `work_heads` and `_settle_work_head` keep their behavior; `_join_if_same_publication` is split, not changed. No existing test expectation may change. If an existing test fails after your change, the change is wrong or the slice file is; stop and report.
4. **Two published records never share a work**, by any path, including the DOI-named link and a merge into a work that already has a published record. Treat this as the invariant every merge test must defend.
5. **Do not invent.** The decision table in the slice file is complete: if a pair falls between its rows, or a rule cannot be built as written, stop and report instead of choosing a workaround. A justified deviation that protects existing behavior is welcome, but name it.
6. No model call, no embedding, no network call in product code or tests. No topic-specific word: the kind lists are repository and notice names. The only network access in this slice is Task 7's script under `.local/`, which is not product code.
7. Match the surrounding style: comment density, naming, short synchronous SQLite transactions, no `await` inside a transaction. `link_records` runs inside `record_search`'s transaction and opens none of its own.
8. Python runs as `PYTHONPATH=backend:. uv run ...` from the repo root, on the native arm64 venv. Do not start, stop or restart the service on port 8765; tests use their own temporary data directory.
9. Fixture records are SYNTHETIC. A passing test shows workflow behavior, not merge accuracy on real records.

## Read first

- `AGENTS.md` — whole file; the Evidence Contract (source identity is an evidence boundary), "User Authority and Workflow Boundaries", the backend rules and the Completion Report apply.
- `docs/product/sw-status.md`, then `docs/product/sw-implementation-plan.md` §2.
- `docs/product/sw-slice03-record-kind-and-version-links.md` — whole file.
- `docs/product/search-workflow-review-2026-09-18.md` — `## SW6`, whole entry including Limits.
- `docs/decisions.md` — D46, D48, D59, D65, D71.
- The measurement scripts the rules come from: `.local/quantum-dedup-2026-09-18/title_pairs.py`, `classify.py`, `signals.py`.
- Code, before editing:
  - `backend/deixis/workflow/store.py`: `title_key`, `is_preprint`, `is_published`, `_surnames`, `same_publication` (~50–78); `purge_research` (~243–303); `upsert_provider_source` and `_insert_provider_record` (~761–841); `_assign_source_key` (~887); `record_search` (~1259); `_work_candidate`, `_flag_suspected_duplicates`, `_join_if_same_publication`, `link_published_versions`, `work_heads`, `_settle_work_head` (~1280–1418); `purge_sources` (~1588–1645).
  - `backend/deixis/workflow/decisions.py` (slice 02: style of a store module, closing a row instead of editing it) and `backend/deixis/workflow/protocol.py::build_protocol`.
  - `backend/deixis/providers/common.py::ProviderRecord`.
  - Migrations: `0001_initial.sql` (`works`, `source_versions`, `identifier_mappings`, `candidates`), `0006_suspected_duplicates.sql`, `0026_arxiv_preprint_work.sql`, `0033_work_source_keys.sql`, `0038_stage_decisions.sql`.
  - Tests: `tests/test_stage_decisions.py` (helpers `research`, `search`, `record`, `two_versions`), `tests/test_provider_records.py` and `tests/test_api_flow.py` (the D46/D48 expectations that must keep passing), `tests/test_corpus_removal.py` (purge), `tests/test_protocol_record.py`, `tests/test_migrations.py`, `tests/determinism_stages.py` with `tests/test_determinism.py`.

Line numbers are approximate; find the symbol.

## What to build

Tasks 1–8 of the slice file, in that order. Task 7 is the one to drop if the session runs long; say so in the final message and in row 03.

## Procedure

1. `git status --short` (expect a clean tree), `ls backend/deixis/storage/migrations | tail -1` (expect `0038_stage_decisions.sql`) and `grep -n '^## D' docs/decisions.md | head -1` (expect D71). If any differs, say so before going on.
2. Baseline: `PYTHONPATH=backend:. uv run pytest -q 2>&1 | tail -3`. Expect `1 failed, 766 passed`; the one failure is `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`, known on this machine and unrelated.
3. Set `sw-status.md` row 03 to `uygulanıyor`.
4. For each task: failing tests first, see them fail, implement, run them.
5. After splitting `_join_works` out of `_join_if_same_publication`, run `tests/test_provider_records.py`, `tests/test_api_flow.py` and `tests/test_source_versions.py` before writing anything else on top of it.
6. For every write function ask the questions earlier slices missed, and cover each with a test: what happens when the same call is repeated (a record found again, a resumed run); what happens on permanent deletion (`purge_research`, `purge_sources`); does the result depend on the order the rows arrived in, and if it must, is that named.
7. Task 8: timing, full test run, `git diff --check`, the `D<NN>` entry, the SW6 status line, row 03 in `sw-status.md`, then the commit and push.

If the session is running long and the work will not finish with tests green, stop at a task boundary, leave the tree passing, commit nothing, and write the remaining tasks into row 03 of `sw-status.md`.

## Final message

- Files created and changed.
- Baseline and final test counts, and the exact command used.
- The measured time of one `link_records` call (1,500 candidates, 50 new records).
- Task 7: counts per verdict and rule for the 127 pairs, and the titles of every pair that came out `merge = True`; or that Task 7 was dropped.
- How you verified that the `_join_works` split left `legacy` behavior unchanged.
- Every point where the slice file could not be followed as written, and every deviation you chose, with its reason.
- What you did NOT do.
- Which evidence boundaries were touched (expected: source identity and work grouping, reachable only from a search of an `sw` research).
- Confirmation that the live service was not touched, and the commit hash.
