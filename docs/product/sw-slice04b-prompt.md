# Task: SW slice 04b — expansion from the first round's data, and yield per term

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 04b of the search workflow build. The master file is `docs/product/sw-status.md`; the line-level plan for this slice is `docs/product/sw-slice04b-data-expansion.md`. That file is the single source of truth for what to build. This prompt only sets the rules of the session. Recommended model: Opus, effort high.

## Ground rules

1. Git: start with `git pull --ff-only`. After that, read-only until the slice is finished. When every task is done and the full test run is green except the one known failure, run `git pull --ff-only` again, then make ONE commit and `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash, reset, rebase or check out files. If the slice is not finished, commit nothing: leave the tree passing and write what remains into row 04b of `sw-status.md`. `TODO.md` and `scripts/local_index.py` may show as the owner's uncommitted work: leave them alone and do not stage them. If any other file you did not touch shows as modified, another session is writing here: stop and report.
2. **Do not touch** `apps/web/`, `contracts/research/`, `methods/deixis-research/`, `backend/deixis/workflow/links.py`, or any existing migration file. `skill_package_hash` must not change.
3. **The `legacy` workflow must behave exactly as before.** The `vocabulary_expansion` step opens only in the `sw` branch of `flow._discovery`; a legacy protocol body and its digest stay the same. No existing test expectation may change. If an existing test fails, the change is wrong or the slice file is; stop and report.
4. **No model call is added.** The flow tests run with a model adapter that fails on every call, and the expansion and the second round still run.
5. **No topic word in product code, and no new word list.** Stop words come from the lists already in `domain/vocabulary_words.py`. If a test seems to need a field's term added to a list, the rule is wrong for that case: report it, do not add the word.
6. **Claim words and exclusion words never reach a query**, by any route. A data phrase that holds one is dropped before the probe.
7. **The stored `vocabulary` step output is not edited.** The expansion lives in its own step; the protocol gets a new revision with the reason `data_expansion`, never an edit of the first one. With no accepted term there is no second round and no second revision.
8. **Do not invent.** The candidate rules, the two thresholds of the field probe, the single-block skip and the second-round query shape are complete in the slice file. If a case falls between them, stop and report instead of choosing a workaround. A justified deviation that protects existing behavior is welcome, but name it.
9. No network in tests. The one live call this slice makes is required, not optional: the count probe over the dry run's 20 candidates (at most 40 OpenAlex count requests), with its output kept under `.local/`. Do not tune a threshold to its result; if the accepted phrases look wrong, say so at the top of the final message. Do not start, stop or restart the service on port 8765.
10. Match the surrounding style: comment density, naming, short synchronous SQLite transactions, no `await` inside a transaction. Stored step output is what makes a resumed run repeat nothing: neither a count probe nor a page may run twice.
11. Python runs as `PYTHONPATH=backend:. uv run ...` from the repo root, on the native arm64 venv.
12. Fixture records and questions are SYNTHETIC and from at least two fields. A passing test shows workflow behavior, not the quality of the expansion.

## Read first

- `AGENTS.md` — whole file.
- `docs/product/sw-status.md` (rows 04a, 04c, 04d and the review log), then `docs/product/sw-implementation-plan.md` §2 and the slice 04 entry.
- `docs/product/sw-slice04b-data-expansion.md` — whole file.
- `docs/product/search-workflow-review-2026-09-18.md` — `## SW2` whole entry including Limits; SW1 point 3; the expansion sentence in SW3's Context; SW14 points 1 and 2.
- `docs/decisions.md` — D73, D74, D75, D70, D18.
- `.local/quantum-source-comparison-2026-09-18/expand_from_data.py` and `round2-expansion.json`, if present: the probe the thresholds come from.
- Code, before editing:
  - `backend/deixis/workflow/flow.py`: `_discovery` whole, `_vocabulary`, `_count_probe`, `_search`, `_search_pages`, `extra_page_requests`, `_checkpoint`, `_pause`.
  - `backend/deixis/domain/vocabulary.py`, `domain/vocabulary_words.py`, `backend/deixis/workflow/vocabulary.py` (the shape of the vocabulary output, `_or_group`, `quoted`, `GATE_BLOCKS`).
  - `backend/deixis/providers/query_compiler.py::compile_block_queries`; `providers/common.py::ProviderRecord`; `providers/ieee_xplore.py`, `providers/pubmed.py` (record mapping) and their fixtures in `tests/test_providers.py`.
  - `backend/deixis/workflow/store.py`: `upsert_provider_source`, `candidates`, `work_heads`, `freeze_protocol`, `current_protocol`, `step`, `finish_step`.
  - `backend/deixis/workflow/protocol.py::build_protocol`; `backend/deixis/domain/canonical.py`.
  - Tests: `tests/test_vocabulary_flow.py`, `tests/test_search_paging.py` (how a paged `sw` run is driven with a mocked OpenAlex that serves both pages and counts), `tests/test_protocol_record.py`, `tests/determinism_stages.py`.

## What to build

Tasks 1–6 of the slice file, in that order.

## Procedure

1. `git pull --ff-only`, `git status --short`, `ls backend/deixis/storage/migrations | tail -1` (expect `0041_search_run_pages.sql`) and `grep -n '^## D' docs/decisions.md | head -1` (expect D75). This slice takes `0042` and D76; if either differs, use the next free number and say so.
2. Baseline: `PYTHONPATH=backend:. uv run pytest -q 2>&1 | tail -3`. Record the numbers; the one expected failure is `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`, known on this machine and unrelated.
3. Set `sw-status.md` row 04b to `uygulanıyor`.
4. For each task: failing tests first, see them fail, implement, run them.
5. For every function that writes or calls out, ask and cover with a test: what happens when the same call is repeated (a resumed run: no probe twice, no page twice, no second `data_expansion` revision); what happens when the count probe fails or is unavailable; what happens when the second round's provider fails; how the request allowance behaves with the second round's pages and their retries; does the result depend on the order rows or providers arrive in.
6. Task 6: the dry run, full test run, `git diff --check`, the `D<NN>` entry, the SW2 status line, row 04b, the second pull, then the commit and push.

If the session is running long and the work will not finish with tests green, stop at a task boundary, leave the tree passing, commit nothing, and write the remaining tasks into row 04b of `sw-status.md`.

## Final message

- Files created and changed.
- Baseline and final test counts, and the exact command used.
- If the live probe accepted phrases that are clearly not search terms for the question, or accepted none, say that first.
- The dry run's 20 candidates with their document frequencies, both counts and the verdict of the live probe for each.
- How the IEEE and PubMed keyword fields were verified.
- Every point where the slice file could not be followed as written, and every deviation you chose, with its reason.
- What you did NOT do.
- Which evidence boundaries were touched (expected: none; the candidate pool grows and the protocol may gain a second revision).
- Confirmation that the live service was not touched, and the commit hash.
