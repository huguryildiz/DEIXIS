# Task: SW slice 07 — order the inspection list by rank fusion of four code signals and an optional embedding signal; store every rank; cut nothing

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 07 of the search workflow build. The master file is `docs/product/sw-status.md`; the line-level plan for this slice is `docs/product/sw-slice07-record-ranking.md`. That file is the single source of truth for what to build. This prompt only sets the rules of the session. Recommended model: Opus, effort high.

## Ground rules

1. Git: start with `git pull --ff-only`. After that, read-only until the slice is finished. When every task is done and the full test run is green except the one known failure, run `git pull --ff-only` again, then make ONE commit and `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash, reset, rebase or check out files. If the slice is not finished, commit nothing: leave the tree passing and write what remains into row 07 of `sw-status.md`. `TODO.md` and `scripts/local_index.py` may show as the owner's uncommitted work: leave them alone and do not stage them. If any other file you did not touch shows as modified, another session is writing here: stop and report.
2. **Do not touch** `apps/web/`, `workflow/views.py`, any existing migration file, any contract schema or the method package. This slice adds one migration (`0044`). `skill_package_hash` must **not** change; record it before and after.
3. **The `legacy` workflow must behave exactly as before.** Its OpenAlex `select` string, its screening order, the place and the input of `_source_similarity`, its protocol body (`"signals": []`) and digest stay the same. No existing test expectation may change, except tests that count the step order of an `sw` run; name each of those in the final message. If any other existing test fails, the change is wrong or the slice file is; stop and report.
4. **No new model call and no new provider request.** The ranking step is code. With the model failing on every call an `sw` discovery run still searches, ranks and stores the ranks. The only network work that grows is the existing embedding call, which on `sw` now runs before screening and over the whole pool.
5. **The order removes nothing and decides nothing.** This slice writes no row to `stage_decisions`, `model_proposals`, `selections`, `record_flags` or `record_links`. The `max_candidates` cut was there before and stays until slice 09; a record outside it stays `pending`.
6. **Embedding has no authority.** Off, without a model, or failing, the four code signals produce the same ranks as they do with it, the run neither stops nor pauses, and no record is rescued.
7. **Ranks are fused, never raw scores.** Ties inside a signal share the mean rank; a missing signal is ranked last in that signal and recorded as missing, not left out of the sum; the final tie is broken by `source_version_id`. Nothing may depend on set iteration, row order or the hash seed.
8. **Every hand-picked number is a named constant** in `workflow/ranking.py` and goes into the protocol's `thresholds.ranking`. `RRF_K` is read from its one definition, not repeated. Do not tune any constant or rule to the replay of Task 6.
9. **The signals are `fuse.py`'s** (`.local/quantum-rank-fusion-2026-09-18/fuse.py`), with the four named deviations of the slice file and no others. `flow.fuse_rankings` is left as it is.
10. **No topic word in product code.**
11. **The protocol must not move by accident.** The `protocol` step and `_freeze_expansion` pass the same `embedding_model`; a changed embedding setting marks no stored decision stale.
12. **Do not invent.** Seed rule, pool rule, availability rule, rescue rule and the stored rows are complete in the slice file. If a case falls between them, stop and report instead of choosing a workaround. A justified deviation that protects existing behavior is welcome, but name it.
13. No network in tests and none anywhere else in this slice: Task 6 replays a cached pool through the pure functions, with no request and no model. Do not start, stop or restart the service on port 8765, and do not open the product database.
14. Match the surrounding style: comment density, naming, short synchronous SQLite transactions, no `await` inside a transaction, no query per record. `workflow/expansion.py` is the pattern for a module with pure functions plus one store-driven entry point; `lookups.held_from_screening` after its review fix is the pattern for reading a pool in one query.
15. Python runs as `PYTHONPATH=backend:. uv run ...` from the repo root, on the native arm64 venv.
16. Fixture records are SYNTHETIC and from at least two fields. A passing test shows workflow behavior, not the quality of an order.

## Read first

- `AGENTS.md` — whole file.
- `docs/product/sw-status.md` (rows 02, 04b, 04c, 05 and the review log for 04b and 05), then `docs/product/sw-implementation-plan.md` §2 and the slice 07 entry.
- `docs/product/sw-slice07-record-ranking.md` — whole file.
- `docs/product/sw-slice02-stage-decisions.md` (the signal rank table), `docs/product/sw-slice04c-paging-and-read-budget.md` (`first_rank`, `sw_options`), `docs/product/sw-slice05-survey-flag-abstract-lookup-links.md` (`reference_count`, held records).
- `docs/product/search-workflow-review-2026-09-18.md` — `## SW7` and `## SW8` whole entries including Limits; SW1 point 4; SW14 point 6.
- `docs/decisions.md` — D27, D29, D30, D46, D48, D65, D70, D71, D75, D77.
- `.local/quantum-rank-fusion-2026-09-18/` — `fuse.py`, `missing_signal.py`, `embedding_rescue.py`, `fusion-result.json`, and the shape of `round.json`.
- Code, before editing:
  - `backend/deixis/workflow/flow.py`: `_discovery` whole, `fuse_rankings`, `answer_source_order`, `_source_similarity`, `_second_sources`, `_search`, `_search_pages`, `_expansion`, `_freeze_expansion`, `_checkpoint`.
  - `backend/deixis/workflow/store.py`: `candidates`, `work_heads`, `record_search` (`first_rank`), `upsert_provider_source`, `_store_author_keywords`, `set_reference_count`, `_has_column`, `_insert_mappings`, `scored_sources`, `save_source_similarities`, `purge_sources` and the two table lists used for permanent deletion.
  - `backend/deixis/workflow/decisions.py`: `save_ranks`, `ranks`; `backend/deixis/storage/migrations/0038_stage_decisions.sql` (`record_signal_ranks`), `0042`, `0043`.
  - `backend/deixis/workflow/expansion.py`: `queried_terms`, `queried_form`, `term_rows`, `count_yields`, `first_round_records`; `workflow/vocabulary.py` (`GATE_BLOCKS`, the returned dictionary); `domain/vocabulary.py::words`.
  - `backend/deixis/workflow/lookups.py`: `held_from_screening`; `workflow/protocol.py` whole; `documents/embeddings.py` (`chosen`, `Embedder.stored_model`, `similarity`).
  - `backend/deixis/providers/openalex.py` (`SELECT`, `REFERENCE_COUNT_FIELD`, `_record`, `search_works`), `providers/common.py` (`ProviderRecord`), `providers/registry.py` (`sw_options`).
  - Tests: `tests/test_stage_decisions.py`, `tests/test_search_paging.py`, `tests/test_expansion_flow.py`, `tests/test_criterion_flow.py`, `tests/test_protocol_record.py`, `tests/test_providers.py` (the OpenAlex `select`), `tests/determinism_stages.py`, `tests/test_determinism.py`.

## What to build

Tasks 1–6 of the slice file, in that order.

## Procedure

1. `git pull --ff-only`, `git status --short`, `ls backend/deixis/storage/migrations | tail -1` (expect `0043_record_lookups_and_flags.sql`) and `grep -n '^## D' docs/decisions.md | head -1` (expect D78). This slice takes D79 and migration `0044`; if a number differs, use the next free one and say so.
2. Baseline: `PYTHONPATH=backend:. uv run pytest -q 2>&1 | tail -3`. Record the numbers; the one expected failure is `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`, known on this machine and unrelated. Record the current `skill_package_hash`.
3. Set `sw-status.md` row 07 to `uygulanıyor`.
4. For each task: failing tests first, see them fail, implement, run them.
5. For every function that writes or reads a pool, ask and cover with a test: what happens when the same call is repeated (a run paused between ranking and screening; a run paused in the middle of screening; a second discovery run of the same scope; a record found again with the same reference list); what happens when the pool is empty, when no record has a reference list, when no seed has one, when every score in a signal is equal; does the result depend on the order rows, references or query words arrive in; does the expansion revision still carry `signals`; does a `legacy` protocol digest and a `legacy` OpenAlex request stay what they were; does any row of any decision table change.
6. Before the replay of Task 6, write `expectation.md` into `.local/sw-ranking-replay-2026-09-21/` and do not edit it afterwards.
7. Task 6: the replay, the timing, full test run, `git diff --check`, the `D<NN>` entry, the SW7 and SW8 status lines, row 07, the second pull, then the commit and push.

## Final message

- If the replay missed its frozen expectation, say that first.
- Files created and changed.
- Baseline and final test counts, and the exact command used. `skill_package_hash` before and after (expected: equal).
- The replay: median rank of the 20 positives, counts in the top 100 and 200, share of records without a reference list, the difference from `fuse.py`'s `rrf_no_tfidf`, and the seconds the pure computation took; whether `asyncio.to_thread` was added.
- Seconds per 200-record page of `record_search` with references written.
- The names of the tests showing that the four signals run unchanged with embedding off, that the order deletes nothing, and that ranking runs with the model down; every existing test updated for the step order.
- Every point where the slice file could not be followed as written, and every deviation you chose, with its reason.
- What you did NOT do.
- Which evidence boundaries were touched (expected: none; the `sw` protocol body gains `signals` and `thresholds.ranking`, and the screening order of an `sw` run changes).
- Confirmation that the live service and the product database were not touched, and the commit hash.
