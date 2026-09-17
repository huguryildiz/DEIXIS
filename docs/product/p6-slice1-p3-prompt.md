# Task: P6 slice 1, batch P3 — report API routes and view models

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`.

This is plan task **1g** (both Task 1 and Task 2) in `docs/product/p6-slice1-report-run.md`, around
line 2157. The orchestration it exposes (`backend/deixis/workflow/report/sections.py::run_report`,
reached through `ResearchFlow.execute`'s `report` branch) is already committed and tested; nothing
outside the backend can reach it yet.

## Ground rules

1. **Run NO state-changing git command.** No `git add`, `git commit`, `git checkout`, `git stash`,
   `git restore`, `git reset`. `git status` / `git diff` / `git log` are fine. The reviewing session
   commits.
2. **Do not touch** anything under `apps/web/`, `backend/deixis/workflow/store.py`,
   `backend/deixis/providers/`, `docs/decisions.md`, `tests/test_corpus_removal.py`,
   `tests/test_provider_flow.py`, `tests/test_providers.py`, `.gitignore`, `.impeccable.md`, or the
   `Elicit - *.csv` files. Several of these have unrelated uncommitted edits in the worktree; leave
   them exactly as they are.
   The plan's Task 2 also asks for a `reportRuns` field in `apps/web/src/api.ts`. **Skip that** — it is
   a TypeScript type only, it is needed when the report UI is built (a later batch), and that file has
   uncommitted edits. Say in your final message that you skipped it.
   `backend/deixis/api/app.py` and `backend/deixis/workflow/flow.py` also carry unrelated uncommitted
   edits (provider search retry: `retry_failed_searches_only`, `retry_provider_requests`, a module
   docstring, a `/retry` route area). **Leave those hunks untouched**; add your routes elsewhere in
   `app.py`, next to the evidence-table routes.
3. **Do not invent.** If something cannot be written as specified, stop and report it rather than
   improvising. Earlier batches stopped this way four times and each stop was correct.
4. Match the surrounding style: short docstrings saying *why*, no speculative abstraction, type hints
   as in neighbouring code.
5. Tests need `PYTHONPATH=backend:.`. Set `UV_CACHE_DIR=/tmp/deixis-uv-cache` if the uv cache is
   unreachable.

## Read first

- `docs/product/p6-slice1-report-run.md`, task **1g** (~line 2157) — both tasks, in full.
- `docs/product/p6-slice1-handoff.md` — your batch is **P3**.
- `AGENTS.md`, `CLAUDE.md`.
- `backend/deixis/api/app.py`: the `create_app` injection seam, the `RevisionConflict` exception
  handler (~line 419), `tables_of(request)` (~line 1234), and especially the evidence-table routes
  `POST .../tables/{id}/columns/suggest` and `POST .../tables/{id}/fill` (~line 1312–1320) — the
  request/idempotency/`worker.wake()` pattern you must copy. Note the CSRF and Host/Origin rules that
  apply to every mutation.
- `backend/deixis/workflow/tables.py`: `TableStore.request_fill`, `request_column_suggestions`,
  `table_view`, `report_ready`.
- `backend/deixis/workflow/report/store.py`: `ReportStore` — `create_report`, `report`, `sections`,
  `snapshot`, `finalize`.
- `backend/deixis/workflow/views.py`: `research_view` (~line 44) and how `table_view` is deliberately
  kept out of it.
- `backend/deixis/workflow/report/sections.py` — what `run_report` expects in `run["target"]`.
- `tests/test_api_flow.py` — the `app_for(tmp_path)` / `session(raw)` / `create(client)` helpers and
  how an evidence table is created and filled in a test.

## What to build

### Task 1 — `ReportStore.request_report` and three routes

**Files:** `backend/deixis/workflow/report/store.py`, `backend/deixis/api/app.py`,
and a new `tests/test_report_api.py`.

```python
# ReportStore
def request_report(self, research_id: str, table_id: str, idempotency_key: str | None) -> dict[str, Any]:
    """Queue a report run over one evidence table, refusing a table that is not ready."""
```

It checks the §4 precondition — the research has included sources and
`workflow.tables.report_ready(store, research_id, table_id)["ready"]` is true — and raises
`RevisionConflict` otherwise, so the existing handler turns it into the same status the table routes
already return for a conflict (**read the handler and use whatever status it actually produces; the
plan says 422, verify rather than assume**). On success it creates the run and the report in the right
order and returns the run: `Store.create_run(research_id, "report", budget, idempotency_key,
target={"table_id": ..., "report_id": ...})`, with `ReportStore.create_report` giving the report id.
`create_report` requires an existing report run, so work out the correct order and say in your final
message what you had to do; if the two cannot be satisfied without changing `Store` (which you must
not touch), stop and report it.

Routes, next to the evidence-table routes in `app.py`:

- `POST /api/researches/{research_id}/reports` → 202, body `{"table_id": str}` as a Pydantic model
  named `StartReport`, optional `Idempotency-Key` header, ending in `request.app.state.worker.wake()`
  exactly like `POST .../fill`. Returns the run.
- `GET /api/researches/{research_id}/reports/{report_id}` → the full report view (Task 2).
- `GET /api/researches/{research_id}/reports` → the summary list (Task 2).

Budget: use the same source the table routes use for a run's budget; do not invent numbers.

**Tests** (`tests/test_report_api.py`), following `tests/test_api_flow.py`'s helpers:
- starting a report on a table with no columns is refused with the conflict status, and no run is
  created;
- after a filled table, `POST .../reports` returns 202 and a run whose `target` carries both
  `table_id` and `report_id`;
- replaying the same `Idempotency-Key` returns the same run id and does not create a second report;
- `GET .../reports/{id}` on an unknown id is a 404;
- a report of another research is not readable through this research's path.

### Task 2 — `report_view` and the research-view summary list

**Files:** `backend/deixis/workflow/views.py`, plus tests in `tests/test_report_api.py`.

- `report_view(store: Store, research_id: str, report_id: str) -> dict[str, Any]` — a new standalone
  function, kept out of `research_view` the way `table_view` is. It returns the report with its
  sections in ordinal order, each section's `section_id`, `status`, `word_count`, `draft`,
  `validation`, and its claims with their citation links resolved enough for the UI to open evidence
  (claim key, text, support type, and for each citation the passage id or cell id plus anchor text).
  Read `views.py`'s existing answer/claim view code and follow its shape and naming rather than
  inventing a new one.
- `research_view` gains a **summary** list only, named **`reportRuns`** (the plan fixes this name
  deliberately): `[{"id", "status", "report_version", "created_at"}]`, newest first. Full section
  content stays behind `GET .../reports/{id}`.

**The naming point matters, read it carefully.** `research_view` already exposes `report_version` and
`report_title` on *answers*, and the web UI's Artifacts tab already has a local `reports` variable
built from `view.answers`. Those are grounded answers, not this slice's reports. **Do not rename or
change any of that existing answer-side naming.** Your addition is the separate `reportRuns` list. If
you find a place where the two would collide in the same payload, stop and report it.

**Tests:**
- `research_view` lists a queued report under `reportRuns` with exactly those four keys and no section
  content;
- `report_view` returns the sections in ordinal order with their claims and citation anchors, for a
  report produced by actually running `run_report` with the fake adapter (reuse
  `tests/test_report_flow.py`'s `report_flow` helper if that is the least duplication — import it or
  factor the shared part out, your call, but do not weaken the existing tests);
- a research with no report has `reportRuns == []`.

## Procedure

1. Read everything in "Read first".
2. Baseline: `PYTHONPATH=backend:. uv run --no-sync pytest -q` → expect `1 failed, 655 passed`. The one
   failure is `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`,
   broken on `main` for unrelated reasons and the **only** acceptable failure.
3. Write the failing tests first; confirm they fail for the right reason.
4. Implement Task 1, then Task 2.
5. Run `PYTHONPATH=backend:. uv run --no-sync pytest tests/test_report_api.py -v` until green, then the
   whole suite, and report the numbers.
6. **Show the route actually works end to end**, not just that tests pass: in a throwaway script, start
   a report through `POST /api/researches/{id}/reports` against a `TestClient` with the fake adapter,
   let the worker run it, then `GET .../reports/{id}` and print the section ids with their status and
   claim counts. Paste that in your final message.

## Final message

- before/after test counts and any new failure;
- the route-level output from step 6;
- the conflict status the existing handler actually returns, and the order you had to use to create
  the run and the report;
- every place the brief could not be followed as written, and what you did instead;
- anything new you found missing, contradictory or already broken;
- what you did NOT do (including the skipped `apps/web/src/api.ts` type).
