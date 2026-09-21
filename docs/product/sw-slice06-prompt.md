# Task: SW slice 06 — the model proposes the inclusion criterion, its parts and cue phrases; code keeps what two of three runs agree on

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 06 of the search workflow build. The master file is `docs/product/sw-status.md`; the line-level plan for this slice is `docs/product/sw-slice06-criterion-proposal.md`. That file is the single source of truth for what to build. This prompt only sets the rules of the session. Recommended model: Opus, effort medium.

## Ground rules

1. Git: start with `git pull --ff-only`. After that, read-only until the slice is finished. When every task is done and the full test run is green except the one known failure, run `git pull --ff-only` again, then make ONE commit and `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash, reset, rebase or check out files. If the slice is not finished, commit nothing: leave the tree passing and write what remains into row 06 of `sw-status.md`. `TODO.md` and `scripts/local_index.py` may show as the owner's uncommitted work: leave them alone and do not stage them. If any other file you did not touch shows as modified, another session is writing here: stop and report.
2. **Do not touch** `apps/web/` or any migration file. This slice needs no migration. `skill_package_hash` changes, and that is expected: record the old and the new value.
3. **The `legacy` workflow must behave exactly as before.** No criterion step opens there, and a legacy protocol body and its digest stay the same. No existing test expectation may change, except tests that count the step order of an `sw` run; name each of those in the final message. If any other existing test fails, the change is wrong or the slice file is; stop and report.
4. **No required model call.** With the model failing on every call an `sw` discovery run still searches, does not pause, and freezes a protocol whose four criterion fields are null.
5. **One run is never used.** With fewer than two valid runs the four fields stay null. The model's strength mark is not asked for and has no field.
6. **The criterion decides nothing and orders nothing in this slice.** No `stage_decisions` row, no selection, no passage order changes. `FORMULATION_TERMS` stays as it is.
7. **The prompt is fixed.** The method file carries the rules of `RULES3` in `.local/sw-criterion-prompt-fix-2026-09-21/run.py`, in the package's style, without changing what they say. Do not add the two `RULES4` sentences, do not improve the wording, and do not tune it to the dry run. None of that trial's five questions, and none of `.local/sw-block-labelling-2026-09-21/questions.json`, may appear in the method file as an example.
8. **No topic word in product code or in the method file.**
9. **The criterion must not move by accident.** A resumed run, a later discovery run of the same scope, a scope revision with the same question, and the expansion's second protocol revision all carry the same criterion fields, byte for byte. A criterion that changes marks every stored decision stale (`decisions.is_stale`).
10. **Do not invent.** The consensus rule, the base run, the reuse rule and the protocol fields are complete in the slice file. If a case falls between them, stop and report instead of choosing a workaround. A justified deviation that protects existing behavior is welcome, but name it.
11. No network in tests. The one live step is required: the dry run of Task 6 (six model calls, `deepseek-flash`, DeepSeek connection, effort high), against a separate `DEIXIS_DATA_DIR`, with no provider request, output kept under `.local/`. Do not start, stop or restart the service on port 8765, and do not open the product database.
12. Match the surrounding style: comment density, naming, short synchronous SQLite transactions, no `await` inside a transaction. `_vocabulary_labels` in `flow.py` is the pattern for three optional model steps.
13. Python runs as `PYTHONPATH=backend:. uv run ...` from the repo root, on the native arm64 venv.
14. Fixture questions and outputs are SYNTHETIC and from at least two fields. A passing test shows workflow behavior, not the quality of a criterion.

## Read first

- `AGENTS.md` — whole file.
- `docs/product/sw-status.md` (rows 01, 04a, 04d and the review log for 01 and 04d), then `docs/product/sw-implementation-plan.md` §2 and the slice 06 entry.
- `docs/product/sw-slice06-criterion-proposal.md` — whole file.
- `docs/product/sw-slice04d-model-block-labelling.md` — the closest earlier slice: a new contract, a new method file and three optional runs.
- `docs/product/search-workflow-review-2026-09-18.md` — `## SW15` whole entry including Limits and the 21 September addendum; SW14 points 1 and 2; SW11 point 10.
- `docs/decisions.md` — D70, D71, D74.
- `.local/sw-criterion-prompt-fix-2026-09-21/` — `protocol.md`, `result.md`, `run.py` (the prompt and the consensus rule as code).
- Code, before editing:
  - `backend/deixis/workflow/flow.py`: `_discovery` whole, `_vocabulary`, `_vocabulary_labels`, `_freeze_expansion`, `_checkpoint`, `_model_step`, `_step_input`, `OptionalStepFailed`.
  - `backend/deixis/workflow/protocol.py` whole; `backend/deixis/workflow/store.py`: `freeze_protocol`, `current_protocol`, `step`, `finish_step`.
  - `backend/deixis/workflow/decisions.py`: `CRITERION_FIELDS`, `_protocol_hashes`, `is_stale`.
  - `backend/deixis/workflow/vocabulary.py`: `apply_labels`, `LABEL_RUNS`, `THRESHOLDS`.
  - `backend/deixis/domain/contracts.py`: how `vocabulary_labels` is registered, `step_output_schema`, `_check_vocabulary_labels`; `domain/rules.py` (`LITERATURE_TASKS`, `NO_REPAIR_TASKS`, `schema_repairs`); `domain/skill.py` (`RUNTIME_FILES`, the integrity check).
  - `contracts/research/vocabulary-labels.schema.json`, `contracts/research/step-input.schema.json`, `methods/deixis-research/SKILL.md`, `references/vocabulary-labels.md`, `provenance.json`.
  - Tests: `tests/test_vocabulary_labels.py`, `tests/test_vocabulary_flow.py`, `tests/test_expansion_flow.py`, `tests/test_protocol_record.py`, `tests/test_stage_decisions.py` (staleness), `tests/determinism_stages.py`, `tests/fakes.py::valid_response`, `tests/fixtures/research/*.json`.

## What to build

Tasks 1–6 of the slice file, in that order.

## Procedure

1. `git pull --ff-only`, `git status --short`, `ls backend/deixis/storage/migrations | tail -1` (expect `0043_record_lookups_and_flags.sql`) and `grep -n '^## D' docs/decisions.md | head -1` (expect D77). This slice takes D78 and no migration; if the number differs, use the next free one and say so.
2. Baseline: `PYTHONPATH=backend:. uv run pytest -q 2>&1 | tail -3`. Record the numbers; the one expected failure is `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`, known on this machine and unrelated. Record the current `skill_package_hash`.
3. Set `sw-status.md` row 06 to `uygulanıyor`.
4. For each task: failing tests first, see them fail, implement, run them.
5. For every function that writes or calls out, ask and cover with a test: what happens when the same call is repeated (a run paused between two proposal calls; a second discovery run; a new scope revision with the same question, and one with another question); what happens when one, two or all three calls fail or return invalid output; does the result depend on the order runs, parts or phrases arrive in; does the expansion revision still carry the criterion; does a `legacy` protocol digest stay what it was.
6. Task 6: the dry run, full test run, `git diff --check`, the `D<NN>` entry, the SW15 status line, row 06, the second pull, then the commit and push.

## Final message

- If the dry run lost the thing sought on either question, say that first.
- Files created and changed.
- Baseline and final test counts, and the exact command used. Old and new `skill_package_hash`.
- The dry run for both questions: criterion sentence, parts, number of kept phrases, `sought_term_in_criterion`, how many runs passed the schema on the first attempt, seconds per call.
- The name of the test showing that a search runs with the model down, and every existing test updated for the step order.
- Every point where the slice file could not be followed as written, and every deviation you chose, with its reason.
- What you did NOT do.
- Which evidence boundaries were touched (expected: none; the protocol body and the method package digest change).
- Confirmation that the live service and the product database were not touched, and the commit hash.
