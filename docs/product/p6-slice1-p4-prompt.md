# Task: P6 slice 1, batch P4 — the plan's named end-to-end report test, over the routes

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`.

This is the plan's **1c Task 3, Step 1** test —
`test_report_run_completes_with_fake_adapter_and_produces_a_valid_report` in
`docs/product/p6-slice1-report-run.md` (~line 1508) — which was deferred until the routes existed.
The routes now exist (batch P3, commit `3d00bff`); the plan step's passage allowlist was fixed in
batch P3.5 (`a374189`).

**Read the handoff first:** `docs/product/p6-slice1-handoff.md`, batch **P4**.

## What is already covered, and what is not

`tests/test_report_api.py::test_start_report_returns_an_idempotent_run_with_both_target_ids` already
drives `POST /api/researches/{id}/reports` → worker → `GET .../reports/{id}` with the fake adapter.
So the chain is proven. What the plan's test adds and nobody asserts yet:

- the **full ordered section list** as `GET .../reports/{report_id}` returns it;
- `status == "valid"` and `report_version == 1` **on the report detail**, not only on the summary row;
- that the report the routes produce carries claims with resolvable citation anchors (today that is
  only asserted by calling `report_view` directly, not through HTTP).

**A discrepancy you must resolve rather than hide.** The plan's snippet expects

```python
["III", "IV", "V", "VI", "VII", "VIII", "I", "IX", "abstract", "index_terms"]
```

— ten sections, in round order, without `II`. The implementation writes **eleven** sections and
`report_view` returns them in **ordinal** order (`abstract, I, II, …, IX, index_terms`), because `II`
is written by code (`review_methodology.py`) and the view orders by ordinal. Assert what the code
actually does, and **say in your final message** that the plan's snippet is stale and how.

## Ground rules

1. **Run NO state-changing git command.** No `git add`, `git commit`, `git checkout`, `git stash`,
   `git restore`, `git reset`. `git status` / `git diff` / `git log` are fine. The reviewing session
   commits.
2. **Do not touch** anything under `apps/web/`, `backend/deixis/workflow/store.py`,
   `backend/deixis/api/app.py`, `backend/deixis/workflow/flow.py`, `backend/deixis/providers/`,
   `docs/decisions.md`, `tests/test_corpus_removal.py`, `tests/test_provider_flow.py`,
   `tests/test_providers.py`, `.gitignore`, `.impeccable.md`, or the `Elicit - *.csv` files. They carry
   another session's uncommitted edits.
3. This batch is **test-only**. If making the test pass requires a production change, **stop and report
   it** — do not change production code to fit a test.
4. **Do not invent.** If something cannot be written as specified, stop and report it.
5. Tests need `PYTHONPATH=backend:.`. Set `UV_CACHE_DIR=/tmp/deixis-uv-cache` if the uv cache is
   unreachable.

## Read first

- `docs/product/p6-slice1-report-run.md` ~line 1508 — the plan's test snippet and its helpers.
- `tests/test_report_api.py` — `upload_and_include`, `create_table`, `fill_table`, and the existing
  route test; reuse these helpers, do not duplicate them.
- `tests/test_report_flow.py` — `ReportAdapter`, `report_flow`.
- `backend/deixis/workflow/views.py::report_view` — the exact shape the route returns.

## What to build

**File:** `tests/test_report_api.py` (the plan says `tests/test_report_flow.py`, but the route helpers
live in `tests/test_report_api.py` and that file is where the HTTP-level report tests already are;
put it there and note the move in your final message).

One test named exactly
`test_report_run_completes_with_fake_adapter_and_produces_a_valid_report`, which:

1. creates an attached-source research, uploads and includes one PDF, creates and fills the evidence
   table (reuse the existing helpers);
2. `POST /api/researches/{id}/reports` with an `Idempotency-Key`, asserts 202, waits for the run to
   reach `completed`;
3. `GET /api/researches/{id}/reports/{report_id}` and asserts: `status == "valid"`,
   `report_version == 1`, the exact ordered `section_id` list, that **every** section has a non-empty
   `draft`, and that at least one section's claims carry citation links whose `anchor_text` is
   non-empty and which name exactly one of `passage_id` / `cell_id`;
4. asserts `GET /api/researches/{id}` lists the finished report under `reportRuns` with `status`
   `valid` and `report_version` 1.

Do not weaken any existing test and do not delete the existing route test; this one is the plan's
named end-to-end case, the other is the idempotency case.

## Procedure

1. Read everything in "Read first".
2. Baseline: `PYTHONPATH=backend:. uv run --no-sync pytest -q` → expect `1 failed, 663 passed`. The one
   failure is `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`,
   broken on `main` for unrelated reasons and the **only** acceptable failure.
3. Write the test; if it fails, say precisely why before changing anything.
4. `PYTHONPATH=backend:. uv run --no-sync pytest tests/test_report_api.py -v`, then the whole suite.

## Final message

- before/after test counts and any new failure;
- the section list the route actually returned, and how the plan's snippet was stale;
- whether every section's draft was non-empty, and which sections carried citation links (II is
  code-written prose and has no claims — say what you saw);
- every place this brief could not be followed as written, and what you did instead;
- anything new you found missing, contradictory or already broken;
- what you did NOT do.
