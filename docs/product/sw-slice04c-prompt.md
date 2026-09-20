# Task: SW slice 04c — paging and the read budget in the sw search

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 04c of the search workflow build. The master file is `docs/product/sw-status.md`; the line-level plan for this slice is `docs/product/sw-slice04c-paging-and-read-budget.md`. That file is the single source of truth for what to build. This prompt only sets the rules of the session. Recommended model: Opus, effort medium.

## Ground rules

1. Git: start with `git pull --ff-only`. After that, read-only until the slice is finished. When every task is done and the full test run is green except the one known failure, run `git pull --ff-only` again, then make ONE commit and `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash, reset, rebase or check out files. If the slice is not finished, commit nothing: leave the tree passing and write what remains into row 04c of `sw-status.md`.
2. **Slice 04d is committed (`d42beda`, D74) and its full review is pending**, so a review session may push a fix to `flow.py` around `_vocabulary` / `_vocabulary_labels` or to `protocol.py`'s vocabulary term fields while you work. Keep to the three places in `flow.py` that the slice file's touch map names; do not edit `_vocabulary`, `_vocabulary_labels`, `_count_probe`, `_searchable`, `_model_step` or `_step_input`, and do not reformat or reorder anything in `flow.py`. If the second pull brings a commit that conflicts, resolve by hand keeping both changes, rerun the full tests, and say so in the final message. If files you did not touch show as modified in the working tree, another session is writing here: stop and report.
3. **Do not touch** `apps/web/`, `contracts/research/`, `methods/deixis-research/`, `backend/deixis/workflow/links.py`, or any existing migration file.
4. **The `legacy` workflow must behave exactly as before.** A provider search called without `cursor` sends the same request and the same `request_description` as today; `results_per_query`, `max_provider_requests` and `core_depth` keep their meaning; a legacy run opens no `:page:` step and its `search_runs` rows hold NULL in the new columns. No existing test expectation may change. If an existing test fails, the change is wrong or the slice file is; stop and report.
5. **Leave the screening cut alone.** `[: budget["max_candidates"]]` in `_discovery` stays. Removing it for `sw` is slice 09.
6. **The read limit never drops a record.** It only stops asking for more pages. Every record that was read becomes a candidate; what was not read is counted, and an unknown provider total is stored as NULL, not as 0.
7. **Every page is its own step**, and the next page's cursor is read from the previous page's stored step output. A resumed run must not request a page twice; a failed page must not stop another query or lose the pages already read.
8. **Do not invent.** The provider table, the stop reasons and the failed-page rule are complete in the slice file. Verify each provider row against that provider's own API documentation; where the documentation disagrees, the documentation wins and you name the row in the final message. If a case falls between the rules, stop and report instead of choosing a workaround. A justified deviation that protects existing behavior is welcome, but name it.
9. No network in tests, and no real waiting: provider paging is tested with a mocked `httpx` transport, and `page_gap` is zero or `asyncio.sleep` is patched. One manual live request per keyless provider to confirm the paging parameter is allowed; say so if you make any.
10. Match the surrounding style: comment density, naming, short synchronous SQLite transactions, no `await` inside a transaction. The page's search run, its candidates and its step outcome are written in one `record_search` transaction, as today.
11. Python runs as `PYTHONPATH=backend:. uv run ...` from the repo root, on the native arm64 venv. Do not start, stop or restart the service on port 8765. The timing script uses a temporary `DEIXIS_DATA_DIR`, never the live library.
12. Fixture records are SYNTHETIC. A passing test shows workflow behavior, not live provider paging.

## Read first

- `AGENTS.md` — whole file.
- `docs/product/sw-status.md`, then `docs/product/sw-implementation-plan.md` §2 and the slice 04c entry.
- `docs/product/sw-slice04c-paging-and-read-budget.md` — whole file.
- `docs/product/search-workflow-review-2026-09-18.md` — SW7 Context (the 1,369-record first round) and SW2 point 3.
- `docs/decisions.md` — D18, D73, D74, D70, D13.
- Code, before editing:
  - `backend/deixis/workflow/flow.py`: `_discovery` (the search loop, `searched()`, `retry_failed`, the `max_candidates` cut) and `_search` (whole).
  - `backend/deixis/providers/common.py` (`SearchOutcome`, `send`, `redact`), `providers/registry.py`, and the search function of every provider module: `openalex.py`, `biorxiv.py`, `crossref.py`, `semantic_scholar.py`, `arxiv.py`, `pubmed.py`, `ieee_xplore.py`, `scopus.py`, `core.py`, `serpapi.py`; `providers/pacing.py`.
  - `backend/deixis/domain/rules.py`: `EffortBudget`, `TEST_EFFORT_BUDGETS`.
  - `backend/deixis/workflow/store.py`: `record_search`, `add_search_run`, `add_to_corpus`, `step`, `finish_step`.
  - `backend/deixis/workflow/links.py::link_records` (read only).
  - `backend/deixis/workflow/protocol.py::build_protocol` (the `thresholds` block); `backend/deixis/workflow/views.py` (`search_runs`, `counts`).
  - `backend/deixis/storage/migrations/0001_initial.sql` (`search_runs`), `0003`, `0037`.
  - Tests: `tests/test_providers.py`, `tests/test_provider_flow.py`, `tests/test_vocabulary_flow.py` (how an `sw` discovery run is driven through `create_app` with a mocked OpenAlex), `tests/test_protocol_record.py`, `tests/test_record_links.py`.

Line numbers in the slice file are approximate; find the symbol.

## What to build

Tasks 1–6 of the slice file, in that order.

## Procedure

1. `git pull --ff-only`, then `git status --short` (expect a clean tree), `ls backend/deixis/storage/migrations | tail -1` and `grep -n '^## D' docs/decisions.md | head -1`. Expect `0040_scope_key_terms.sql` and D74; this slice takes `0041` and D75. If either differs, use the next free number and say so.
2. Baseline: `PYTHONPATH=backend:. uv run pytest -q 2>&1 | tail -3`. Record the numbers; the one expected failure is `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`, known on this machine and unrelated.
3. Set `sw-status.md` row 04c to `uygulanıyor`.
4. For each task: failing tests first, see them fail, implement, run them.
5. For every function that writes or calls out, ask and cover with a test: what happens when the same call is repeated (a resumed run, a retried page: no page twice, no count twice); what happens when a page fails in the middle; does the result depend on the order rows or providers arrive in.
6. Task 5: run the timing script and keep its output under `.local/`.
7. Task 6: full test run, `git diff --check`, the `D<NN>` entry, row 04c, the second pull, then the commit and push.

If the session is running long and the work will not finish with tests green, stop at a task boundary, leave the tree passing, commit nothing, and write the remaining tasks into row 04c of `sw-status.md`.

## Final message

- If one page's `record_search` took more than a second at 1,500 candidates, say that first.
- Files created and changed.
- Baseline and final test counts, and the exact command used.
- The provider table: which rows you verified against the provider's documentation, and any row you corrected.
- The timing numbers: per page, the `link_records` share, the total, and which records were used.
- Every point where the slice file could not be followed as written, and every deviation you chose, with its reason.
- What you did NOT do.
- Which evidence boundaries were touched (expected: none; the candidate pool grows, and the content of `search_runs` and of the protocol body changes).
- Whether the second pull brought a commit and whether anything conflicted.
- Confirmation that the live service was not touched, and the commit hash.
