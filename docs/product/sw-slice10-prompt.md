# Task: SW slice 10 — an sw discovery run is followed by a full-text retrieval run that fetches once per work in rank order, records the version read, and leaves a work without text unresolved

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 10 of the search workflow build. The master file is `docs/product/sw-status.md`; the line-level plan for this slice is `docs/product/sw-slice10-background-fulltext-fetch.md`. That file is the single source of truth for what to build. This prompt only sets the rules of the session. Recommended model: Opus, effort high.

## Ground rules

1. Git: start with `git pull --ff-only`. After that, read-only until the slice is finished. When every task is done and the full test run is green except the one known failure, run `git pull --ff-only` again, then make ONE commit and `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash, reset, rebase or check out files. If the slice is not finished, commit nothing: leave the tree passing and write what remains into row 10 of `sw-status.md`. `TODO.md` and `scripts/local_index.py` may show as the owner's uncommitted work: leave them alone and do not stage them. If any other file you did not touch shows as modified, another session is writing here: stop and report.
2. **`legacy`, `answer` and `pdf_collection` must behave exactly as before.** Their steps, the `MAX_DOWNLOADS_PER_RUN` cap, the D35 trigger for the other-copy lookup, `TEST_EFFORT_BUDGETS`, and `acquire_for_source` called without the new argument stay byte for byte. Everything new is reached only from a `fulltext_fetch` run of an `sw` research.
3. **No selection changes in this slice.** The three codes it writes (`not_read_yet`, `text_unreadable`, `no_fulltext`) are all `unresolved`. Nothing becomes `included` or `excluded`; the user's decision stands and `HumanDecisionStands` is not swallowed. No model is called; no contract, method file or `skill_package_hash` change.
4. **D4, D22, D35 hold.** A PDF is attached only to the source version it belongs to; every candidate and attempt is stored; a link that refused is not requested again, a timeout is. A verified copy of a *different, declared* version goes to its own version row under the same work (slice file, Task 4), never onto the published record. An `uncertain` copy still waits for the user. Web search stays off in this run.
5. **Lesson 1 from the slice 09 review: work read back from the store on a resumed run is never written to a budget or a counter.** The work limit, the `downloads` usage and the summary numbers count only work done in this call; a work whose stored step is `succeeded` or `failed` is skipped without touching any live counter, and the summary is totalled from stored step outputs. The slice file names the test that must exist: a plan exactly as long as the limit, paused in the middle, resumed, finishes the whole plan. A resume test with a generous budget does not show this bug; slice 09's did not.
6. **Lesson 2 from slice 09 Task 5: no second concurrency mechanism.** This slice fetches sequentially, for the reasons in the slice file. If you add concurrency at all, the only way is `flow._send_through_limiter` with one job per work; no `asyncio.gather`, no semaphore of your own, no new loop. Say in the final message which you did.
7. **The plan is frozen in the `fulltext_plan` step output** and a resumed run reads it back. Step keys carry the head's identifier, never a position in the list.
8. **One matcher, one fetch path.** `match_pdf_to_source` is moved, not copied. Retrieval goes through `_acquire_pdf`, `_fetch_pdf`, `_find_other_copy` and `acquire_for_source`; do not write a second downloader, a second lookup, an arXiv title search or a Europe PMC request (owner's decision, in the slice file).
9. One work's failure does not stop the run. A work whose routes did not all answer gets no decision and is tried again by a later run.
10. **Existing tests:** only the setup change named in the slice file's "Güncellenecek mevcut testler" section is allowed (`fulltext_fetch="off"` in existing `sw` setups and the H fixture server, and one protocol-shape test). No expectation changes. If any other existing test fails, the change is wrong or the slice file is; stop and report.
11. **Do not invent.** The three groups and their order, the eligibility rule, the result table, the version-row rule, the auto-queue condition and the step outputs are complete in the slice file. If a case falls between them, stop and report instead of choosing a workaround. A justified deviation that protects existing behavior is welcome, but name it.
12. No network in tests, and no live step anywhere in this slice: no download, no provider request, no dry run, no timing measurement. Measurement is slice 24; anything you would have measured is written down as "ölçülmedi". Do not start, stop or restart the service on port 8765, and do not open the product database.
13. Match the surrounding style: comment density, naming, short synchronous SQLite transactions, no `await` inside a transaction, UI-visible events written in the same transaction as the state they describe. Whole-research reads in a few queries, not one query per record. PDF extraction stays in `asyncio.to_thread`.
14. Python runs as `PYTHONPATH=backend:. uv run ...` from the repo root, on the native arm64 venv.
15. Fixture records are SYNTHETIC and from at least two fields. No topic word in product code.
16. `apps/web`: read `.impeccable.md` first; the only change is Task 8 (run kind, three step labels in EN and TR, the `pdf` phase, the background-jobs set, the run filter). `PdfReadiness.tsx` is not touched.

## Read first

- `AGENTS.md` — whole file ("User Authority", evidence semantics, timeline states).
- `docs/product/sw-status.md` (rows 02, 03, 07, 09 and the review log for 07 and 09), then `docs/product/sw-implementation-plan.md` §2 and the slice 10 entry.
- `docs/product/sw-slice10-background-fulltext-fetch.md` — whole file.
- `docs/product/search-workflow-review-2026-09-18.md` — `## SW10` (points 1–5 and Limits), `## SW11` (point 1), `## SW6` (points 4–5).
- `docs/decisions.md` — D4, D18, D22, D35, D48, D49, D71, D72, D81.
- Code, before editing:
  - `backend/deixis/workflow/flow.py`: `execute`, `_checkpoint`, `_pause`, `_inspect`, `_acquire_pdf`, `_fetch_pdf`, `_needs_other_copy`, `_find_other_copy`, `_abstract_stage` with `_model_calls_left` (where lesson 1 was fixed), `_send_through_limiter`, `_ranking`.
  - `backend/deixis/documents/acquisition.py` whole; `documents/fetch.py`; `documents/pdf.py::extract_pdf`.
  - `backend/deixis/workflow/store.py`: `create_run`, `step` / `start_step` / `finish_step`, `STEP_OUTPUT_KINDS`, `upsert_provider_source` with `_insert_other_version` and how other versions become members of a research, `work_heads`, `_settle_work_head`, `work_versions`, `answer_version`, `has_pdf_text`, `pdf_candidates`, `pdf_discoveries`, `pdf_link_refusal`, `record_pdf_attempt`, `add_asset_with_pages`.
  - `backend/deixis/workflow/decisions.py` whole; `domain/reason_codes.py` whole; `workflow/ranking.py::_versions`; `workflow/abstract_stage.py::should_write`.
  - `backend/deixis/api/app.py`: `StartRun`, `start_run`, `match_pdf_to_source` and its constants, `match_uploads`; `backend/deixis/config.py` (`protocol_approval` as the pattern for the new setting); `workflow/protocol.py` (`thresholds`); `storage/migrations/0035_report_run_kind.sql`.
  - `apps/web/src/Transcript.tsx` (`phaseOf`, the phase order, the plan sentence), `labels.ts`, `BackgroundJobs.tsx`, `ResearchView.tsx` (the run-kind filter).
  - Tests: the `pdf_collection` and other-copy tests, the `uploads/match` tests, `tests/test_abstract_flow.py` and `tests/test_abstract_concurrency.py` (the resume and budget cases), `tests/determinism_stages.py`, `tests/acceptance/fixture_server.py`.

## What to build

Tasks 1–9 of the slice file, in that order.

## Procedure

1. `git pull --ff-only`, `git status --short`, `ls backend/deixis/storage/migrations | tail -1` (expect `0044_record_references.sql`) and `grep -n '^## D' docs/decisions.md | head -1` (expect D82). This slice takes D83 and migration `0045`; if a number differs, use the next free one and say so.
2. Baseline: `PYTHONPATH=backend:. uv run pytest -q 2>&1 | tail -3`. Record the numbers; the one expected failure is `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`, known on this machine and unrelated. Record the current `skill_package_hash`.
3. Set `sw-status.md` row 10 to `uygulanıyor`.
4. For each task: failing tests first, see them fail, implement, run them.
5. For every function that writes or calls out, ask and cover with a test: what happens when the same call is repeated (a second retrieval run in the same scope; a run paused between two works, after a work's `fetch_pdf` step, and after the plan step; the same discovery run completing twice; the version row opened twice); what a resumed run counts, and whether any number differs from the uninterrupted run; what happens after a scope revision; what a user decision, a user exclusion or a permanent delete of a source does to the plan; whether a `legacy` research, an `answer` run and a `pdf_collection` run stay what they were.
6. Task 9: full test run, web build, lint and Playwright A–H, `git diff --check`, the `D<NN>` entry, the SW10 status line, row 10, the second pull, then the commit and push.

## Final message

- Files created and changed.
- Baseline and final test counts, the exact command, and the Playwright result. `skill_package_hash` before and after (expected: the same).
- The names of the tests showing that no selection changes, that a resumed run finishes the whole plan and counts nothing twice, that a later run continues where the first stopped, that a copy of another version lands on its own version row, and that `legacy`, `answer` and `pdf_collection` are unchanged.
- Every existing test file whose setup was switched to `fulltext_fetch="off"`.
- Whether fetching is sequential or concurrent; if concurrent, that it goes through `_send_through_limiter`.
- Every point where the slice file could not be followed as written, and every deviation you chose, with its reason.
- What you did NOT do, and everything left unmeasured, named as "ölçülmedi".
- Which evidence boundaries were touched (expected: code may open a version row under a work and attach a PDF to it without the user's confirmation, only for a DOI-verified copy with a declared version; the full-text stage gets its first decisions and all of them are `unresolved`; the other-copy lookup runs for a work with no open link at all, in this run kind only).
- Confirmation that the live service and the product database were not touched, and the commit hash.
