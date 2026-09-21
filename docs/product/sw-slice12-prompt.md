# Task: SW slice 12 — an sw retrieval run is followed by a full-text reading run: two model runs propose a label and a verbatim quote per criterion part, code checks every quote on the page, and only agreement with every quote verified includes a work

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 12 of the search workflow build. The master file is `docs/product/sw-status.md`; the line-level plan for this slice is `docs/product/sw-slice12-fulltext-adjudication.md`. That file is the single source of truth for what to build. This prompt only sets the rules of the session. Implementer: Grok 4.7 (owner's decision); the review is done afterwards by another model against the slice file, so everything you decide on your own must be named in your final message.

## Ground rules

1. Git: start with `git pull --ff-only`. After that, read-only until the slice is finished. When every task is done and the full test run is green except the one known failure, run `git pull --ff-only` again, then make ONE commit and `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash, reset, rebase or check out files. If the slice is not finished, commit nothing: leave the tree passing and write what remains into row 12 of `sw-status.md`. `TODO.md`, `scripts/local_index.py` and `.vscode/` may show as the owner's uncommitted work: leave them alone and do not stage them. If any other file you did not touch shows as modified, another session is writing here: stop and report.
2. **This slice is where a wrong decision silently corrupts evidence.** For the first time code sets a work to `included` without the user. The only path to `included` is: two runs both label every criterion part `present`, and every quote of both runs is found verbatim (`exact` or `normalized`, never fuzzy) in the page text the model was shown. Anything less is `unresolved` with its reason code. A quote that cannot be verified never includes. Do not soften any row of the rule table in the slice file.
3. **Authority is code; the user is above code.** The model's label alone writes nothing; no confidence is asked for or used; the model step has no tools and no loop beyond the existing bounded schema repair. A work with a human full-text decision is not read; `HumanDecisionStands` is not swallowed; `derive_selection` never overwrites a selection whose origin is the user; a work the user excluded is not read.
4. **The code gate is off.** Phrase counts close nothing and keep no work from the model; they only order the passages to read, through slice 11's `criterion_passages.criterion_order`. Do not write a second ranker. Preprint-only evidence and a model family are labels, never queue reasons.
5. **Other runs stay what they were.** `legacy` researches, and `discovery`, `fulltext_fetch`, `answer` and `pdf_collection` runs keep their steps and budgets. `CAPABILITIES.supported_tasks` is not extended. `TEST_EFFORT_BUDGETS` is not touched.
6. **Lesson A: rows left between runs are the research's history, not the run's.** The criterion is read only through `store.frozen_criterion` and frozen in the plan step. The slice file says, case by case, what happens to a fresh decision, a stale decision, a call that did not answer, an invalid output, and the identity check (recomputed at read time, never read from an earlier run's step output). Each case needs a test whose name says it.
7. **Lesson B: records are shared between researches.** Only versions in `store.work_versions(rid, head)` are read. This slice opens no shared row; if you find you must, stop and report.
8. **Lesson C: `store.step` opens the step it reads.** Only the path that executes a step calls it; views, the summary and test helpers read through a path that opens nothing.
9. **Lesson D: the budget looks at the run's total and every started call counts, failed or not.** No retry share is added: a repair attempt and a failed call are paid from the same total, the works at the END of the plan are then not read, the summary counts them as `not_reached`, and no decision is written for them. A work is never half-sent. Work read back from the store on a resumed run is never written to the budget. The slice file names the test: a plan exactly as long as the limit, paused in the middle, resumed, finishes the whole plan and repeats no call. Read how a repair attempt is counted in `usage["model_calls"]` and say so in the final message.
10. **No second concurrency mechanism.** Calls go through `flow._send_through_limiter` with one job per (work, run number). No `asyncio.gather`, no semaphore of your own, no new loop. A decision is written on the event loop in one short transaction with no `await` inside; a response that arrives after the run stopped or the scope was revised is stored as a step and writes no decision.
11. **The method file text is given in the slice file and is copied unchanged.** It was tried with no model; do not tune it, and do not make any live model call in this slice.
12. **Existing tests:** only the changes named in the slice file's "Güncellenecek mevcut testler" section are allowed. If any other existing test fails, the change is wrong or the slice file is; stop and report.
13. **Do not invent.** The eligibility rule, the reading list, the contract, the verification rule, the verdict and the rule table, the auto-queue condition, the budget and the step outputs are complete in the slice file. If a case falls between them, STOP AND REPORT instead of choosing a workaround; an unfinished slice with a clear question is better than a finished one with a guessed rule. A justified deviation that protects existing behavior is welcome, but name it.
14. No network in tests and no live step anywhere: no model call, no provider request, no download, no dry run, no timing. Anything you would have measured is written down as "ölçülmedi". Do not start, stop or restart the service on port 8765, and do not open the product database.
15. Match the surrounding style: comment density, naming, short synchronous SQLite transactions, UI-visible events written in the same transaction as the state they describe, whole-research reads in a few queries. Mirror slice 09 (`abstract_stage.py`, `flow._abstract_stage`) and slice 10 (`fulltext.py`, `flow._fulltext_fetch`) rather than designing a new shape.
16. Python runs as `PYTHONPATH=backend:. uv run ...` from the repo root, on the native arm64 venv (`uv run python -c "import platform; print(platform.machine())"` must print `arm64`).
17. Fixture records are SYNTHETIC and from at least two fields. No topic word in product code.
18. `apps/web`: read `.impeccable.md` first; the only change is Task 8.

## Read first

- `AGENTS.md` and `CLAUDE.md` — whole files.
- `docs/product/sw-status.md`: the "Bir tur" section, rows 02, 09, 10, 11, and every row of the review log ("Yapılan incelemeler") — the findings there are the mistakes this slice must not repeat. Then `docs/product/sw-implementation-plan.md` §2 and the slice 12 entry.
- `docs/product/sw-slice12-fulltext-adjudication.md` — whole file. For the shape to mirror: `docs/product/sw-slice09-abstract-screening.md` and `docs/product/sw-slice10-background-fulltext-fetch.md`.
- `docs/product/search-workflow-review-2026-09-18.md` — `## SW1`, `## SW11`, `## SW15` (point 5), `## SW16`.
- `docs/decisions.md` — D4, D12, D48, D71, D78, D80, D81, D83, D84.
- Code, before editing:
  - `backend/deixis/workflow/abstract_stage.py` whole; `workflow/fulltext.py` whole; `workflow/criterion_passages.py` whole; `workflow/decisions.py` whole; `domain/reason_codes.py` whole; `documents/identity.py`.
  - `backend/deixis/workflow/flow.py`: `execute`, `_checkpoint`, `_abstract_stage`, `_abstract_code_stage`, `_abstract_call`, `_close_abstract_batch`, `_write_abstract_codes`, `_model_calls_left`, `_send_through_limiter`, `_model_step`, `_step_input`, `_fulltext_fetch`, `_fulltext_plan`, `_fulltext_works`, `_write_fulltext_codes`, `_queue_fulltext_fetch`, `_criterion_phrases`, `_retrieve`, `HANDLE_TASKS`, `CAPABILITIES`.
  - `backend/deixis/domain/contracts.py`: how `abstract_screening` is registered end to end, `_check_abstract_screening`, `locate_anchor`, `citation_handles`; `contracts/research/abstract-screening.schema.json` and `step-input.schema.json`; `domain/skill.py::RUNTIME_FILES`; `methods/deixis-research/SKILL.md` and `provenance.json` (the abstract-screening entries).
  - `backend/deixis/workflow/store.py`: `create_run`, `step` / `start_step` / `finish_step`, `latest_step_output`, `STEP_OUTPUT_KINDS`, `frozen_criterion`, `work_versions`, `work_heads`, `answer_version`, `has_pdf_text`, `passages_for`, `search_passages`, `_write_extraction`.
  - `backend/deixis/api/app.py`: `StartRun`, the run budget function; `config.py` (`fulltext_fetch` as the pattern); `workflow/protocol.py` (`thresholds`); `storage/migrations/0045_fulltext_fetch_run_kind.sql`.
  - Tests: `tests/test_abstract_flow.py`, `tests/test_abstract_concurrency.py`, `tests/test_fulltext_flow.py`, `tests/test_criterion_passage_flow.py`, `tests/fakes.py`, `tests/fixtures/research/*.json`, `tests/determinism_stages.py`, `tests/acceptance/fixture_server.py`.

## What to build

Tasks 1–9 of the slice file, in that order.

## Procedure

1. `git pull --ff-only`, `git status --short`, `ls backend/deixis/storage/migrations | tail -1` (expect `0045_fulltext_fetch_run_kind.sql`) and `grep -n '^## D' docs/decisions.md | head -1` (expect D84). This slice takes D85 and migration `0046`; if a number differs, use the next free one and say so.
2. Baseline: `PYTHONPATH=backend:. uv run pytest -q 2>&1 | tail -3` (about nine minutes). Record the numbers; the one expected failure is `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`, known on this machine and unrelated. Record the current `skill_package_hash`.
3. Set `sw-status.md` row 12 to `uygulanıyor`.
4. For each task: failing tests first, see them fail, implement, run them.
5. For every function that writes or calls out, ask and cover with a test: what happens when the same call is repeated (a second reading run in the same scope; a run paused between two works, between the two runs of one work, and after the plan step; the same retrieval run completing twice); what a resumed run counts and whether any number differs from the uninterrupted run; what happens after a scope revision and after a revised criterion; what a user decision, a user exclusion, a user inclusion or a permanent delete of a source does; what happens when the model is off, when one run does not answer, and when the output is invalid; whether the other run kinds and `legacy` stay what they were.
6. Task 9: full test run, web build, lint and Playwright A–H, `git diff --check`, the `D<NN>` entry, the SW status lines, row 12, the second pull, then the commit and push.

## Final message

- Files created and changed.
- Baseline and final test counts, the exact command, and the Playwright result. `skill_package_hash` before and after (expected: changed).
- The names of the tests showing that an unverifiable quote does not include, that nothing is decided while the model is off, that the user's selection is not overwritten, that a resumed run finishes the plan and repeats no call, that a work one of whose runs did not answer is read with two calls by the next run, that no work is half-sent, that a read opens no step, and that the other run kinds are unchanged.
- How a repair attempt is counted in `usage["model_calls"]`, and whether you moved `_topic_terms` out of `_retrieve`.
- Every point where the slice file could not be followed as written, and every deviation you chose, with its reason. Every rule you had to decide yourself because the slice file was silent.
- What you did NOT do, and everything left unmeasured, named as "ölçülmedi".
- Which evidence boundaries were touched (expected: code includes a work without the user for the first time, only on two agreeing runs with every quote found verbatim on the page; code can exclude a work on the strength of selected passages; an `sw` answer no longer waits for manual inclusion).
- Confirmation that the live service and the product database were not touched, and the commit hash.
