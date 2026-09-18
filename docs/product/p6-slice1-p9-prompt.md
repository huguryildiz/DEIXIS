# Task: P6 slice 1, batch P9 — give a report run its own model-call budget

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`.

Not in the plan. It comes from the fourth real-model run (18 September, `gpt-5.6-luna`, on the copied library,
recorded in `docs/product/p6-slice1-handoff.md`): **nine of eleven sections came out valid and then the run
stopped at `budget_exhausted`.** `abstract` and `index_terms` never ran, and `report_phrase_repair:I` failed
for the same reason.

## Why

`ReportStore.request_report` takes the run budget from the research's effort preset:

```python
budget = TEST_EFFORT_BUDGETS[scope["effort"]].__dict__
```

Those presets were sized for the search-and-answer workflow (a search plan, screening batches, one answer).
`standard` allows `max_model_calls=15`. A report needs, structurally: 1 plan call + one call per
model-written section (10 — `II` is written by code) + up to one phrase-repair call per section + possibly one
`research_title` call. So the floor is 11 and the realistic ceiling is above 20. Fifteen is a cap sized for a
different job, and it truncates every report.

`api/app.py`'s `start_run` already sets task-shaped budgets this way for other run kinds
(`research_title` → `{"max_model_calls": 2, ...}`, `pdf_collection` → `{"max_model_calls": 0, ...}`), so the
pattern exists — but **that file is off-limits this round** (another session is editing it). Do the work in
`ReportStore.request_report`.

## What to build

**Files:** `backend/deixis/workflow/report/store.py`, and wherever the count of model-written sections is
already defined (`backend/deixis/workflow/report/sections.py::ROUNDS` / `ORDINALS` — **do not duplicate the
section list**; import or derive it). Tests in `tests/test_report_api.py` or `tests/test_report_store.py`,
whichever already covers `request_report`.

1. Compute the report run's `max_model_calls` from the report's own structure rather than the effort preset:
   one plan call, one call per model-written section, one phrase-repair call per section, and one title call.
   Write the arithmetic as one short expression with a comment naming each term, so a later reader can check
   it against `run_report`.
2. Keep every other budget field as the effort preset gives it (`max_answer_passages` is used by the plan
   step's passage cap; `max_provider_requests` should be 0 — a report searches nothing — **verify that claim
   in `run_report` before setting it**, and say what you found).
3. **Do not** change `TEST_EFFORT_BUDGETS`, and do not make report budgets depend on effort. If you think
   effort should still scale something here, say so in your final message rather than implementing it.
4. Note for your sizing: a bounded schema repair re-calls the model and each attempt counts against
   `max_model_calls` (`flow.py` ~1088). Decide whether to add margin for that, state your decision and its
   reasoning, and do not silently inflate the number.

## Tests

- `request_report` stores a budget whose `max_model_calls` matches the formula, for a `quick` research and a
  `standard` one — **the same number for both**, since it no longer depends on effort.
- `max_provider_requests` is 0.
- A fake-adapter flow test that a report run now reaches **all eleven** sections without `budget_exhausted`
  (the existing fake-model report tests should already cover the happy path; extend rather than duplicate).
- Do not weaken the existing budget-exhaustion tests elsewhere, if any exist. If one asserts the old number,
  stop and report it instead of editing it.

## Ground rules

1. **Run NO state-changing git command.** `git status` / `git diff` / `git log` are fine. The reviewing
   session commits.
2. **Do not touch** anything under `apps/web/`, `backend/deixis/workflow/store.py`,
   `backend/deixis/api/app.py`, `backend/deixis/workflow/flow.py`, `backend/deixis/providers/`,
   `docs/decisions.md`, `docs/README.md`, `tests/test_corpus_removal.py`, `tests/test_provider_flow.py`,
   `tests/test_providers.py`, `scripts/isolated_*.py`, `tests/test_isolated_*.py`, `.gitignore`,
   `.impeccable.md`, or the `Elicit - *.csv` files. Another session is working in the same tree.
3. **Do not invent.** If something cannot be written as specified, stop and report it.
4. Tests need `PYTHONPATH=backend:.`; set `UV_CACHE_DIR=/tmp/deixis-uv-cache` if the uv cache is unreachable.

## Read first

- `backend/deixis/workflow/report/store.py::request_report`.
- `backend/deixis/workflow/report/sections.py` — `ROUNDS`, `ORDINALS`, `run_report` (how many model calls it
  can make, including `_research_title` and `repair_section`).
- `backend/deixis/domain/rules.py` — `TEST_EFFORT_BUDGETS`, `EffortBudget`, `MAX_SCHEMA_REPAIRS`.
- `backend/deixis/workflow/flow.py` ~line 1088 (read only) — the budget check and what counts as a call.
- `docs/product/p6-slice1-handoff.md` — the fourth-run entry.

## Procedure

1. Read everything in "Read first".
2. Baseline: `PYTHONPATH=backend:. uv run --no-sync pytest -q`. Record the exact numbers; another session
   keeps adding tests. The only acceptable failure is
   `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`.
3. Write the failing tests first.
4. Implement, then run the whole suite.

## Final message

- the formula you wrote, quoted, and the number it produces;
- what you found about `max_provider_requests` in `run_report`;
- your decision about schema-repair margin and why;
- before/after test counts and any new failure;
- every place this brief could not be followed as written, and what you did instead;
- anything new you found missing, contradictory or already broken;
- what you did NOT do.
