# Task: P6 slice 1, batch P3.5 — the report plan step must see readable text for every included source

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`.

This batch is **not in the plan**. It closes a gap the P3 round exposed, of exactly the kind
`docs/product/p6-slice1-handoff.md` records under "P2.5 neden gerekti": a model cannot fill a field
whose allowlist is empty.

## The gap

`backend/deixis/workflow/report/sections.py` (~line 194) builds the `report_plan` step's passage
allowlist as:

```python
abstract_passages = [passage for source_id in source_ids for passage in flow.store.passages_for(source_id)
                     if passage["kind"] == "abstract"]
```

A research whose sources are **attached PDFs** has no `abstract` passages at all — an upload produces
`pdf_page` passages. For such a research the allowlist is empty, so `_check_report_plan` must reject
every glossary term and every axis the model writes, and the report plan is born dead. The P3 test
`tests/test_report_api.py::test_start_report_returns_an_idempotent_run_with_both_target_ids` only
passes because it inserts a synthetic `abstract` passage straight into the store with
`store._insert_passage(...)`; that line is a workaround for this bug, not a fixture requirement.

## The rule to implement (do not redesign it)

Per included source, in the snapshot's row order:

1. its `abstract` passage if it has one (unchanged behaviour), **else**
2. its **first** `pdf_page` passage — `passages_for` already returns passages ordered by
   `kind, physical_page, rowid`, so this is the first `pdf_page` row it yields for that source.

At most **one** fallback passage per source. Cap the whole list at the run's
`budget["max_answer_passages"]` if that key is present in the run budget (it comes from
`TEST_EFFORT_BUDGETS`); if it is absent, do not invent a cap — say so in your final message.
Keep the current order: sources in snapshot row order.

Nothing else changes. Reading depth, anchors and the rest stay as the records say; you are only making
the allowlist non-empty for a source that has text.

## Ground rules

1. **Run NO state-changing git command.** No `git add`, `git commit`, `git checkout`, `git stash`,
   `git restore`, `git reset`. `git status` / `git diff` / `git log` are fine. The reviewing session
   commits.
2. **Do not touch** anything under `apps/web/`, `backend/deixis/workflow/store.py`,
   `backend/deixis/api/app.py`, `backend/deixis/workflow/flow.py`, `backend/deixis/providers/`,
   `docs/decisions.md`, `tests/test_corpus_removal.py`, `tests/test_provider_flow.py`,
   `tests/test_providers.py`, `.gitignore`, `.impeccable.md`, or the `Elicit - *.csv` files. Several of
   these carry another session's uncommitted edits; leave them exactly as they are.
3. **Do not invent.** If the rule above cannot be written as specified, stop and report it rather than
   improvising. Earlier batches stopped this way four times and each stop was correct.
4. Match the surrounding style: short docstrings saying *why*, no speculative abstraction.
5. Tests need `PYTHONPATH=backend:.`. Set `UV_CACHE_DIR=/tmp/deixis-uv-cache` if the uv cache is
   unreachable.

## Read first

- `backend/deixis/workflow/report/sections.py::run_report` — the plan call and its `passage_rows`.
- `backend/deixis/workflow/store.py::passages_for` (read only) — the order it returns.
- `backend/deixis/domain/contracts.py::_check_report_plan` — why an empty allowlist kills the plan.
- `tests/test_report_flow.py` — the `report_flow` helper and `ReportAdapter`.
- `tests/test_report_api.py` — the P3 tests, including the `_insert_passage` workaround.
- `docs/product/p6-slice1-handoff.md` — "P2.5 neden gerekti".

## What to build

**Files:** `backend/deixis/workflow/report/sections.py`, `tests/test_report_flow.py`,
`tests/test_report_api.py`.

1. Replace the abstract-only list with the rule above. Name the local variable for what it now is.
2. **Test, in `tests/test_report_flow.py`:** a report over sources that have **only** `pdf_page`
   passages (no abstract anywhere) reaches `report_plan` with a **non-empty** passage allowlist and
   finishes `valid`. Assert the allowlist, not just the outcome — read the stored `StepInput` of the
   `report_plan` step (the step row's stored input is what the run recorded) and assert its passages
   are the pdf pages. If the stored StepInput cannot be read back in a test the way you expect, stop
   and report it instead of weakening the assertion to `status == "valid"`.
3. **Test:** a source that *does* have an abstract still contributes its abstract and **not** its pdf
   page — the fallback must not widen what a source with an abstract gives.
4. In `tests/test_report_api.py`, remove the `store._insert_passage(...)` workaround from
   `test_start_report_returns_an_idempotent_run_with_both_target_ids` and confirm the test still
   passes on the uploaded PDF alone. If it does not, **stop and report why** — do not put the
   workaround back and do not weaken the test.

## Procedure

1. Read everything in "Read first".
2. Baseline: `PYTHONPATH=backend:. uv run --no-sync pytest -q` → expect `1 failed, 661 passed`. The one
   failure is `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`,
   broken on `main` for unrelated reasons and the **only** acceptable failure.
3. Write the failing tests first; confirm they fail for the right reason (an empty allowlist, or a
   rejected plan — say which).
4. Implement the rule.
5. Run `PYTHONPATH=backend:. uv run --no-sync pytest tests/test_report_flow.py tests/test_report_api.py -v`
   until green, then the whole suite, and report the numbers.

## Final message

- before/after test counts and any new failure;
- what the `report_plan` allowlist actually contained before and after, for an attached-PDF research;
- whether the P3 `_insert_passage` workaround could be removed, and what happened when you removed it;
- whether `budget["max_answer_passages"]` was there to cap with;
- every place this brief could not be followed as written, and what you did instead;
- anything new you found missing, contradictory or already broken;
- what you did NOT do.
