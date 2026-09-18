# Task: P6 slice 1, batch P8.5 — a report citation anchor must name exactly one target

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`.

Not in the plan. It comes from the third real-model run (18 September, `gpt-5.6-luna`, on the copied library),
which **crashed**:

```
sqlite3.IntegrityError: CHECK constraint failed: (passage_id IS NOT NULL) <> (cell_id IS NOT NULL)
  workflow/report/sections.py:165 _run_section -> reports.save_claims(...)
  workflow/report/store.py:194 save_claims
```

Section IV's model output gave, in all three of its `citation_anchors`, **both** a `passage_id` and a
`cell_id` (e.g. `psg_e0rKB67OihLsuCy9fqhF` together with `cel_25QQhi1cLtaeWqwApogp`). The run failed with
`internal_error`, losing a run that had already spent seven model calls.

## What is already true, and what is missing

`contracts/research/report-section-draft.schema.json` line ~103 already documents the invariant:

> "One anchor per claim-evidence pair. **Exactly one of passage_id/cell_id is non-null (checked in code)**"

**It is not checked in code.** JSON Schema cannot express it here (both fields are nullable), the semantic
check `contracts._check_report_section` does not test it, `sections.py::_citation_links` only branches on
`passage_id is not None` and copies `cell_id` through unchanged, and the first thing that notices is the
SQLite CHECK in migration 0035 — as a crash, not a validation failure.

`methods/deixis-research/references/report.md` does not tell the model this rule either.

## What to build

1. **`backend/deixis/domain/contracts.py::_check_report_section`** — add the check: for every
   `citation_anchors[]` entry, exactly one of `passage_id` / `cell_id` is non-null. Neither → an issue;
   both → an issue. Follow the file's existing `Issue(code, path, ...)` conventions exactly: read the
   neighbouring report checks and copy their code naming, JSON-pointer path style and message register. This
   must be an **issue**, not a warning, so that `_model_step` routes it into the existing bounded schema
   repair and, if repair fails, into `invalid_model_output` — never into a crash.
2. **`methods/deixis-research/references/report.md`** — state the rule for the model, in the file's own
   voice, where the section instructions describe citation anchors: an anchor cites **either** a passage
   **or** an evidence-table cell, never both and never neither; a claim supported by both a passage and a
   cell needs one anchor for each. Keep it short; do not restructure the file. This changes
   `skill_package_hash` — expected.
3. **`backend/deixis/workflow/report/sections.py::_citation_links`** — make the function itself refuse to
   build a link that names both or neither, rather than relying on the database. Raising there would still
   crash the run, so **do not raise**: decide, and say in your final message which of these you did and why —
   either the validator alone is enough because an invalid anchor can no longer reach this function, or a
   defensive guard here is warranted. If you conclude the validator alone suffices, leave the function
   unchanged and say so; do not add dead defensive code.

## Tests

- `tests/test_contracts.py` (or the file where the other `_check_report_section` cases live — find it):
  an anchor with both ids is rejected; an anchor with neither is rejected; one with exactly one is accepted.
  Do not weaken any existing case.
- A flow-level test proving the run no longer dies: a `ReportAdapter` section response whose anchor carries
  both ids ends as a **validation** outcome (repair attempt, then `invalid_model_output` pause) and **not**
  `internal_error`. Assert the run's `pause_reason`/`error`, and assert no `IntegrityError` escapes.
- Package integrity after the method-package edit:
  `PYTHONPATH=backend:. uv run --no-sync python -c "from deixis.domain import skill; print(skill.integrity_issues())"`

## Ground rules

1. **Run NO state-changing git command.** `git status` / `git diff` / `git log` are fine. The reviewing
   session commits.
2. **Do not touch** anything under `apps/web/`, `backend/deixis/workflow/store.py`,
   `backend/deixis/api/app.py`, `backend/deixis/workflow/flow.py`, `backend/deixis/providers/`,
   `docs/decisions.md`, `docs/README.md`, `tests/test_corpus_removal.py`, `tests/test_provider_flow.py`,
   `tests/test_providers.py`, `scripts/isolated_*.py`, `tests/test_isolated_*.py`, `.gitignore`,
   `.impeccable.md`, or the `Elicit - *.csv` files. Another session is working in the same tree.
3. **Do not change migration 0035 or add a migration.** The database CHECK is correct; the layer above it is
   what is missing.
4. **Do not invent.** If something cannot be written as specified, stop and report it.
5. Tests need `PYTHONPATH=backend:.`; set `UV_CACHE_DIR=/tmp/deixis-uv-cache` if the uv cache is unreachable.

## Read first

- `backend/deixis/domain/contracts.py` — `_check_report_section` and the report checks around it.
- `contracts/research/report-section-draft.schema.json` — `citation_anchors` (~line 100).
- `backend/deixis/workflow/report/sections.py::_citation_links` and `_run_section`.
- `backend/deixis/storage/migrations/0035_report_run_kind.sql` — the `report_citation_links` CHECK.
- `backend/deixis/workflow/flow.py` ~line 1137 (read only) — how an issue becomes a repair attempt and then
  `invalid_model_output`.
- `tests/fakes.py::valid_response` and `tests/fixtures/research/fake-outputs.json` — a schema/semantic change
  usually needs these updated too.
- `AGENTS.md` — citation integrity is fail-closed.

## Procedure

1. Read everything in "Read first".
2. Baseline: `PYTHONPATH=backend:. uv run --no-sync pytest -q`. Record the exact numbers; another session
   keeps adding tests. The only acceptable failure is
   `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`.
3. Write the failing tests first; confirm they fail for the right reason (a crash, not a validation error).
4. Implement, then run the whole suite.

## Final message

- before/after test counts and any new failure;
- the issue code and path you added, quoted;
- what you decided about `_citation_links` and why;
- whether the fixtures/fakes needed changing;
- every place this brief could not be followed as written, and what you did instead;
- anything new you found missing, contradictory or already broken;
- what you did NOT do.
