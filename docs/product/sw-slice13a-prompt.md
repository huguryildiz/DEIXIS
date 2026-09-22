# Task: SW slice 13a — a model connection that cannot enforce the output schema is still usable: show it the schema and a skeleton, normalise a recorded alias table before validation, and stop repair from pausing the run

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 13a of the search workflow build, a follow-up of slice 13's fourth smoke run. The master file is `docs/product/sw-status.md`; the line-level plan for this slice is `docs/product/sw-slice13a-schema-lenient-models.md`, the decision is D86 in `docs/decisions.md`. The slice file is the single source of truth; this prompt only sets the rules of the session. Implementer: Opus · high; the review is done afterwards by another model against the slice file, so everything you decide on your own must be named in your final message.

## Ground rules

1. Git: start with `git pull --ff-only`. Read-only until the slice is finished. When every task is done and the full test run is green except the one known failure, `git pull --ff-only` again, then ONE commit and `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash, reset, rebase or check out files. If the slice is not finished, commit nothing: leave the tree passing and write what remains into row 13a of `sw-status.md`. `TODO.md`, `scripts/local_index.py`, `.vscode/` and everything under `.local/` are the owner's: never stage them. If another file you did not touch shows as modified, another session is writing here: stop and report.
2. **The model boundary is the point of this slice, not a side effect.** The model has no tools; output from a model other than the requested one is never used; the raw output is stored byte for byte. The alias table renames fields only and changes no value; a missing required field, a wrong label value, an unknown passage id are left for validation to reject. If you find yourself wanting to "fix" one more thing the model got wrong, stop: that is slice 24's question, not this slice's.
3. **An enforcing adapter's StepInput does not move.** The skeleton is appended only when `enforces_schema` is `False`. The method package is not edited and `skill_package_hash` stays what it is; say the hash before and after in the final message (compute it with `domain/skill.py`, do not start the service).
4. **Lesson D holds:** every started call is paid from the run total, repair included; this slice only checks, before sending, whether the calls a work may still need fit. No reserved share, no second budget. The reading run must finish `completed` with `not_reached` when repairs eat the budget; a `budget_exhausted` pause reached through the limiter path is a bug and needs a failing test first.
5. **Existing tests:** only the changes the slice file names. If any other existing test fails, the change is wrong or the slice file is; stop and report.
6. **Do not invent.** The alias table, the skeleton rule, the budget arithmetic and the tests are in the slice file. If a case falls between them, STOP AND REPORT rather than choose a workaround.
7. No network in tests and no live model call anywhere; no dry run, no timing. The fifth smoke run is not yours. Do not start, stop or query the service on port 8765 and do not open the product database.
8. Match the surrounding style. Python runs as `PYTHONPATH=backend:. uv run ...` from the repo root on the native arm64 venv.
9. Fixture records are SYNTHETIC and from at least two fields. No topic word in product code.

## Read first

- `AGENTS.md` (Model boundary, User Authority) and `CLAUDE.md`.
- `docs/product/sw-status.md`: "Bir tur", rows 09, 12, 13 and 13a, and the whole review log ("Yapılan incelemeler"). Then `docs/product/sw-implementation-plan.md` §2.
- `docs/product/sw-slice13a-schema-lenient-models.md` whole; `docs/decisions.md` D12, D81, D85, D86.
- `.local/sw-smoke-2026-09-22/result-run4.md` if present (read-only evidence: what DeepSeek returned; not part of the repo).
- Code, before editing: `backend/deixis/models/adapter.py` (protocol, `ModelStepResult`), `models/deepseek.py`, `models/gemini.py`, `models/claude.py`, `models/prompt.py`; `domain/contracts.py` (`validate_model_output`, `resolve_citation_handles`, `step_output_schema`, `_check_fulltext_adjudication`); `domain/rules.py` (`MAX_SCHEMA_REPAIRS`, `NO_REPAIR_TASKS`, `schema_repairs`, `after_invalid_output`); `workflow/flow.py` (`_model_step`, `_call_adapter`, `_send_through_limiter`, `_model_calls_left`, `_abstract_stage`, `_abstract_call`, `_fulltext_adjudication` and its sender); `tests/fakes.py`, `tests/test_adjudication_flow.py`, `tests/test_abstract_concurrency.py`, `tests/test_deepseek_adapter.py`, `tests/test_contracts.py`.

## What to build

Tasks 1–5 of the slice file, in that order.

## Procedure

1. `git pull --ff-only`, `git status --short`, `grep -n '^## D' docs/decisions.md | head -3` (expect D88, D87, D86 present; this slice implements D86 and opens no number), `ls backend/deixis/storage/migrations | tail -1` (expect `0047`; this slice opens no migration).
2. Baseline: `PYTHONPATH=backend:. uv run pytest -q 2>&1 | tail -3` (about nine minutes; the one expected failure is `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`). Record the numbers and the current `skill_package_hash`.
3. Set row 13a to `uygulanıyor`.
4. For each task: failing tests first, see them fail, implement, run them.
5. Ask for every write path: what a resumed run does (a step whose output was normalised is read back as stored, not normalised twice); what happens with an enforcing adapter (nothing new); what the answer run does on two invalid outputs (unchanged: unverified draft); whether `legacy` and the table runs stay what they were.
6. Task 5: full test run, `git diff --check`, D86 status line, row 13a, second pull, commit, push.

## Final message

Files changed; baseline and final test counts with the exact command; `skill_package_hash` before and after (expected: unchanged); the names of the tests showing that a renamed field is normalised and recorded, that a wrong value is still rejected, that an enforcing adapter's StepInput is byte-identical, that the reading run completes with `not_reached` instead of pausing, and that no work is half-sent; the exact alias table as implemented; every deviation from the slice file with its reason; what you did not do and what is "ölçülmedi"; confirmation that the live service and the product database were not touched; the commit hash.
