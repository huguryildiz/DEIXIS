# Task: SW slice 04d — model block labelling over the phrases code extracted

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 04d of the search workflow build. The master file is `docs/product/sw-status.md`; the line-level plan for this slice is `docs/product/sw-slice04d-model-block-labelling.md`. That file is the single source of truth for what to build. This prompt only sets the rules of the session. Recommended model: Opus, effort high.

## Ground rules

1. Git: read-only until the slice is finished. When every task is done and the full test run is green except the one known failure, make ONE commit and `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash, reset, rebase or check out files. If the slice is not finished, commit nothing: leave the tree passing and write what remains into row 04d of `sw-status.md`.
2. **Do not touch** `apps/web/` or any existing migration file. This slice needs no schema change.
3. **The `legacy` workflow must behave exactly as before.** `vocabulary_labels` opens only in the `sw` branch of `flow._discovery`. No existing test expectation may change except the ones that pin `skill_package_hash`, which changes because the method package gains a file. If any other existing test fails, the change is wrong or the slice file is; stop and report.
4. **The single most important test: with the model adapter failing on every call, an `sw` discovery run still searches, using the rule's blocks.** Slice 04a's acceptance condition narrows here from "no model call" to "no *required* model call". If you cannot keep it, stop and report instead of working around it.
5. **The model may not invent.** An output naming a phrase outside the step's allowlist is rejected, not repaired; schema repair is off for this step. A missing or duplicated phrase is an error too, not a warning.
6. **No topic word in product code and none in the method package.** The worked examples in `references/vocabulary-labels.md` must be field-independent, and must NOT be any question from `.local/sw-block-labelling-2026-09-21/questions.json` — that is the measurement set and putting it in the prompt contaminates slice 24.
7. **Do not invent.** The labels, the majority rule, the fall-back and the skip conditions are complete in the slice file. If a case falls between them, stop and report instead of choosing a workaround. A justified deviation that protects existing behavior is welcome, but name it.
8. No network in tests; the model is driven through `tests/fakes.py::FakeAdapter`. One live labelling call for the dry run of Task 6 is allowed; say so if you make it.
9. Match the surrounding style: comment density, naming, short synchronous SQLite transactions, no `await` inside a transaction. Stored step output is what makes a resumed run repeat nothing; a resumed run must not call the model again.
10. Python runs as `PYTHONPATH=backend:. uv run ...` from the repo root, on the native arm64 venv. Do not start, stop or restart the service on port 8765, and do not touch the live library.
11. Fixture records and questions are SYNTHETIC. A passing test shows workflow behavior, not labelling quality; labelling quality was measured once in `.local/sw-block-labelling-2026-09-21/` and is measured again in slice 24.

## Read first

- `AGENTS.md` — whole file.
- `docs/product/sw-status.md`, then `docs/product/sw-implementation-plan.md` §2.
- `docs/product/sw-slice04d-model-block-labelling.md` — whole file.
- `docs/product/search-workflow-review-2026-09-18.md` — `## SW17` whole entry including Limits; `## SW2` points 2 and 6 and its Limits; SW1 point 3.
- `docs/product/sw-slice04a-code-vocabulary.md` — Task 1, Task 3, Task 5 and "Açık noktalar" (what this slice changes).
- `docs/decisions.md` — D73, D70, D44.
- `.local/sw-block-labelling-2026-09-21/REPORT.md` — what was measured and what was not. Do not copy its questions into the method package.
- Code, before editing:
  - `backend/deixis/workflow/flow.py`: `_discovery` (the `sw` branch), `_model_step`, `_step_input`, `OptionalStepFailed` and every existing `optional=True` caller, `_checkpoint`.
  - `backend/deixis/domain/contracts.py`: `step_output_schema`, `check_step_input`, `validate_model_output` and how an existing task's allowlist check is written.
  - `backend/deixis/domain/vocabulary.py` (whole file), `backend/deixis/workflow/vocabulary.py` (whole file).
  - `backend/deixis/domain/skill.py`: `RUNTIME_FILES`, `package_hash`, the integrity check.
  - `backend/deixis/domain/rules.py`: `LITERATURE_TASKS`, `step_model`.
  - `backend/deixis/workflow/protocol.py::build_protocol`; `backend/deixis/domain/canonical.py`.
  - `contracts/research/step-input.schema.json` (`extraction_target`, `allowlist`) and an existing small output schema such as `research-title.schema.json`.
  - Tests: `tests/test_vocabulary.py`, `tests/test_vocabulary_flow.py`, `tests/test_contracts.py`, `tests/test_protocol_record.py`, `tests/fakes.py`, `tests/determinism_stages.py`, `tests/fixtures/research/step-inputs.json`, `tests/fixtures/research/fake-outputs.json`.

Line numbers are approximate; find the symbol.

## What to build

Tasks 1–6 of the slice file, in that order.

## Procedure

1. `git status --short` (expect a clean tree), `ls backend/deixis/storage/migrations | tail -1` (expect `0040_scope_key_terms.sql`) and `grep -n '^## D' docs/decisions.md | head -1` (expect D73). If any differs, say so before going on.
2. Baseline: `PYTHONPATH=backend:. uv run pytest -q 2>&1 | tail -3`. Record the numbers; the one expected failure is `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`, known on this machine and unrelated.
3. Set `sw-status.md` row 04d to `uygulanıyor`.
4. For each task: failing tests first, see them fail, implement, run them.
5. For every function that writes or calls out, ask and cover with a test: what happens when the same call is repeated (a resumed run must not label again); what happens when one run fails, when all three fail, and when the output is invalid; does the result depend on the order the three runs arrive in.
6. Task 6: the dry run on the two topic questions, full test run, `git diff --check`, the `D<NN>` entry, the SW17 and SW2 status lines, row 04d, then the commit and push.

If the session is running long and the work will not finish with tests green, stop at a task boundary, leave the tree passing, commit nothing, and write the remaining tasks into row 04d of `sw-status.md`.

## Final message

- Files created and changed.
- Baseline and final test counts, and the exact command used.
- The old and the new `skill_package_hash`, and every test you had to update because of it.
- The two topic questions' phrases with the rule's block and the model's block side by side.
- The name of the test that proves discovery still searches with the model down.
- Every point where the slice file could not be followed as written, and every deviation you chose, with its reason.
- What you did NOT do.
- Which evidence boundaries were touched (expected: none; the protocol body and the method package hash change).
- Confirmation that the live service and the live library were not touched, and the commit hash.
