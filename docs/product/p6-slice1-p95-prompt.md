# Task: P6 slice 1, batch P9.5 — the report budget must cover schema repairs

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`.

Follow-up to batch P9 (`e09005a`), which you wrote. The fifth real-model run
(`gpt-5.6-luna`, copied library) hit `budget_exhausted` again at exactly 22 calls: **10 of 11
sections valid, section `I` never written.**

Measured: the run made **17 model steps** but spent **22 model calls**. The five extra calls are
bounded schema repairs — `flow.py` re-calls the model once per step when the output fails its schema
(`MAX_SCHEMA_REPAIRS = 1`), and each attempt counts against `max_model_calls`. Your P9 note predicted
exactly this; the brief asked you not to inflate the number silently, so it was left out. Now it is
measured, so put it in.

## What to change

`backend/deixis/workflow/report/store.py::request_report`, the budget expression only.

Every model step may need one schema repair, so a step costs up to `1 + MAX_SCHEMA_REPAIRS` calls.
Size the cap for that worst case across the mandatory steps (plan + model-written sections + title)
and the optional phrase repairs (one per section). Import `MAX_SCHEMA_REPAIRS` from
`deixis.domain.rules` rather than writing `2`, keep deriving the section count from `ROUNDS`, and keep
the comment naming each term so a reader can check it against `run_report`.

A cap is a ceiling, not a spend: the fifth run would still have made 22 calls under a higher cap. Do
not add any margin beyond the worst case you can justify from the code, and state the number your
expression produces.

## Tests

Update the P9 budget tests to the new number (they assert the old one — that is the one test file you
*should* change here). The eleven-section fake-adapter test must still pass. Do not weaken anything
else.

## Ground rules

1. **Run NO state-changing git command.** The reviewing session commits.
2. **Do not touch** `apps/web/`, `backend/deixis/workflow/store.py`, `backend/deixis/api/app.py`,
   `backend/deixis/workflow/flow.py`, `backend/deixis/providers/`, `docs/decisions.md`,
   `docs/README.md`, `tests/test_corpus_removal.py`, `tests/test_provider_flow.py`,
   `tests/test_providers.py`, `scripts/isolated_*.py`, `tests/test_isolated_*.py`, `.gitignore`,
   `.impeccable.md`, the `Elicit - *.csv` files, or `TEST_EFFORT_BUDGETS`.
3. **Do not invent.** If the worst case cannot be derived from the code, stop and report it.
4. Tests need `PYTHONPATH=backend:.`; set `UV_CACHE_DIR=/tmp/deixis-uv-cache` if needed.

## Procedure

1. Baseline `PYTHONPATH=backend:. uv run --no-sync pytest -q`; record the numbers. Only
   `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit` may fail.
2. Change the expression and the budget tests, then run the whole suite.

## Final message

- the new expression, quoted, and the number it produces;
- before/after test counts;
- anything you could not follow, and what you did instead;
- what you did NOT do.
