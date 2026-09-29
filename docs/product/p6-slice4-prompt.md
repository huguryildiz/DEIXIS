# Task: P6 slice 4 (small version) — edit a report claim with history, and show what evidence changed after the report

Repo: the git worktree you are started in (`-C`). All paths below are relative to it.

The design note is `docs/product/p6-slice4-editing-stale-measurement.md`; **its §0 (29 September 2026) is the
spec for this task** and overrides §1–§13 where they differ. §1–§13 are the 17 September draft: read them for
intent and names, but build only what §0 lists. The owner did not choose among the §12 options; the
coordinator took the draft's own fallbacks, with one deviation (staleness is computed when the report is read,
not written by every mutation; §0 explains why).

The report run itself (P6 slice 1) is in code: `backend/deixis/workflow/report/` (`store.py`, `sections.py`,
`snapshot.py`), migrations `0035_report_run_kind.sql` and `0036_report_section_ii.sql`, the report routes in
`backend/deixis/api/app.py` (search `reports_of`), and `backend/deixis/workflow/views.py::report_view`.
There is **no report screen** in `apps/web`; this task adds none.

## What to build

### 1. Migration `backend/deixis/storage/migrations/0056_report_claim_revisions.sql`

Confirm `0056` is the next free number with `ls backend/deixis/storage/migrations/`; if it is taken, use the
next free one and say so. Never edit an existing migration.

- `report_claim_revisions`: `id TEXT PRIMARY KEY` (`rcv_`), `claim_id TEXT NOT NULL REFERENCES report_claims(id)`,
  `kind TEXT NOT NULL CHECK (kind IN ('human_edit', 'human_restore'))`, `restored_from TEXT` (NULL for a plain
  edit; `'model'` or the id of an earlier revision of the same claim for a restore; checked in code, so no FK),
  `text TEXT NOT NULL`, `warnings_json TEXT NOT NULL DEFAULT '[]'`, `note TEXT`, `idempotency_key TEXT UNIQUE`,
  `created_at TEXT NOT NULL`, `CHECK ((kind = 'human_restore') = (restored_from IS NOT NULL))`, and an index on
  `(claim_id, created_at)`.
- `ALTER TABLE report_claims ADD COLUMN current_revision_id TEXT REFERENCES report_claim_revisions(id)` and
  `ADD COLUMN version INTEGER NOT NULL DEFAULT 1`.
- `report_stale_acknowledgements`: `id TEXT PRIMARY KEY` (`rsa_`), `report_id TEXT NOT NULL REFERENCES reports(id)`,
  `section_id TEXT NOT NULL`, `change_key TEXT NOT NULL`, `created_at TEXT NOT NULL`,
  `UNIQUE (report_id, section_id, change_key)`.
- Both new tables are append-only: `BEFORE UPDATE` triggers always abort; `BEFORE DELETE` triggers abort unless
  the owning research has a row in `research_purge_authorizations` (copy the `cell_revisions_no_delete` pattern
  in `0020_evidence_tables.sql`, joining through `report_claims -> report_sections -> reports` or `reports`).

### 2. `ReportStore` (`backend/deixis/workflow/report/store.py`)

`report_claims.text` stays the model's text and is never updated. The claim's current text is the text of
`current_revision_id` when set, else `report_claims.text`.

- `edit_claim(research_id, report_id, claim_id, *, text, restore_from, note, expected_version, idempotency_key) -> str`
  returns the new revision id. One transaction. In order:
  1. The report must belong to `research_id` and the claim to the report, else `NotFound`.
  2. Idempotency: scope the key as `f"{research_id}:{idempotency_key}"` (same as `request_report`). A replay of
     the same key on the same claim returns the stored revision id without writing; the same key on another
     claim is a `RevisionConflict`.
  3. Refuse with `RevisionConflict` unless `reports.status IN ('valid', 'draft')` **and** the report's run is in
     a terminal state (`completed`, `failed`, `cancelled`); message: a report can be edited once its run has
     finished.
  4. `check_expected_version(expected_version, claim.version)` (`deixis.domain.rules`).
  5. Exactly one of `text` and `restore_from` is given. With `restore_from`, the new text is the model's text
     (`'model'`) or that revision's text; a revision of another claim is refused. The resulting text is stripped;
     empty text, or text identical to the current text, is refused. Refusals of input are 422: reuse the error
     class/handler the table routes use for 422 (`InvalidTableInput` in `workflow/tables.py`) or add a report
     equivalent registered the same way; say which.
  6. Warnings (never blocking), stored in `warnings_json` as a list of `{"kind", "detail"}`:
     `math_not_well_formed` for each math span `domain/contracts.py::_math_spans` finds that
     `_math_span_is_well_formed` rejects (import the helpers; do not copy them), and `count_not_rechecked` when
     the claim has a non-NULL `count_json`. The phrasebank check does **not** run on human text.
  7. Insert the revision (`kind` `human_edit` or `human_restore`), set `report_claims.current_revision_id` and
     `version = version + 1`, touch `reports.updated_at`, and write a `report_claim_edited` event through
     `self._event` in the same transaction. `report_version`, `reports.status`, the section's status and
     `draft_json`, and the citation links do not change.
- `claim_revisions(claim_id) -> list[dict]`, oldest first, warnings decoded.
- `save_claims`: before deleting anything, if any claim of that section has a `report_claim_revisions` row,
  raise `RevisionConflict` (fail closed: a rewrite must never erase a human edit; the pending-proposal flow of
  the draft's S3 is deferred).
- `evidence_changes(report_id) -> dict`: read-only comparison of the frozen `report_snapshot` with live records.
  A report without a snapshot returns an empty result, not an error.
  - A snapshot cell is **changed** when the live `evidence_cells.current_revision_id` differs from its
    `cell_revision_id` (including a cell whose current revision is now NULL or whose row no longer exists).
    Change key: `f"cell:{cell_id}:{live_revision_id or 'none'}"`.
  - **Row set.** The snapshot's rows are the table's active rows that are also included sources
    (`build_snapshot`: `tables.active_rows(table_id)` ∩ `store.included_sources(research_id)`). Compute the live
    row set **the same way** (one shared helper if that avoids duplicating the rule). A snapshot row's source is
    **removed** when it is not in the live row set (excluded, removed from the research, or removed from the
    table row list); a source is **added** when it is in the live row set but not among the snapshot rows
    (including an already-included source added to the table later).
  - **Removal key.** `f"source:{source_version_id}:{stamp}"`, where `stamp` is the timestamp of the transition
    that currently keeps the source out: the latest of `corpus_memberships.removed_at` (when set), the
    selection's `updated_at` (when its state is not `included`), and the table row's removal timestamp (read the
    table-row schema in `0020_evidence_tables.sql` / `tables.py::remove_row`; if it has none, say so and what you
    used). Each of these is written when the source leaves, and a later independent departure can only happen
    after the source came back, so it carries a later stamp and therefore a new key; an unrelated later update of
    an excluded selection only re-opens the marker (a conservative false positive, acceptable). Two departures in
    the same millisecond would share a key; note this as a limit, do not engineer around it. A test must cover
    remove → acknowledge → restore → remove again → a new open change (set timestamps explicitly if needed).
  - Report level: counts of changed snapshot cells, removed sources, added sources, and **revised** columns (a
    snapshot column whose live `current_revision` differs or which is removed), plus `any: bool`. Look at how
    `build_snapshot` reads columns and use the same source. Name the result so it does not claim more than it
    checks: it does **not** detect PDF re-extraction or passage changes (the snapshot stores no extraction
    identity); put `"not_checked": ["passages"]` in the report-level result.
  - Section level: for each report section, the changes its claims depend on:
    (a) direct: changed cells one of its claims cites through `report_citation_links.cell_id`, and removed sources
    one of its claims cites through `report_citation_links.source_version_id` (passage or cell link);
    (b) one level through references: a claim's `report_claim_refs` `body_ref` names a `claim_key` of another
    section of the same report, and that claim's direct changes count for the referring section; a `gap_ref` names
    a `report_gaps.gap_id` of the report, and the gap's `basis_json` `basis_cell_ids` (changed cells) and
    `basis_claim_keys` (those claims' direct changes) count likewise. Verify in `sections.py`/`save_gaps` how
    `claim_key` and `gap_id` are scoped and resolve them accordingly; if a reference cannot be resolved, skip it
    and count it in a `unresolved_refs` integer on the section rather than guessing.
    Each change is `{"key", "kind": "cell_changed" | "source_removed", "source_version_id", "cell_id"?,
    "column_id"?, "via": "citation" | "body_ref" | "gap_ref"}` (deduplicate by key, preferring `citation`),
    split into `open` (key not in `report_stale_acknowledgements` for that report and section) and an
    `acknowledged_count`.
  - Keep it to a handful of queries per report (no per-link query loops over the whole table).
- `acknowledge_changes(research_id, report_id, section_id, change_keys) -> int`: one transaction. Every key must
  be a currently open change of that section, otherwise `RevisionConflict` (the evidence changed again; the
  page must reload) and nothing is written. Insert with `INSERT OR IGNORE`, write a
  `report_changes_acknowledged` event, return the number inserted. An acknowledgement never expires; a later
  change produces a new key and therefore a new open change.

### 3. View (`backend/deixis/workflow/views.py::report_view`)

Keep every existing field and its meaning. Add:
- per claim: `id`, `version`, `text` (now the **current** text), `model_text` (`report_claims.text`),
  `edited` (bool), `warnings` (current revision's, `[]` if none) and `revisions` (from `claim_revisions`).
- per section: `evidence_changes: {"open": [...], "acknowledged_count": n}`.
- on the report: `evidence_changes` (the report-level counts and `any`), and `edited_after_version`: the
  `report_version` when any claim of the report has a revision, else `None`. Add a short docstring/comment in
  `report_view` stating the contract: an edited claim's `text` is the person's working text, not re-validated;
  the section's `draft`, `validation` and `word_count` and the report's `report_version` still describe the
  model-written, validated version until a publish step exists.

Check that `test_report_view_returns_ordered_sections_claims_and_citation_anchors` still passes unchanged; if it
compares whole dicts and fails only because of the added keys, adjust it minimally and say so.

### 4. Routes (`backend/deixis/api/app.py`, next to the existing report routes)

- `PUT /api/researches/{research_id}/reports/{report_id}/claims/{claim_id}` with body
  `{text?: str (max 4000), restore_from?: str (max 40), note?: str (max 1000), expected_version: int}` and an
  optional `Idempotency-Key` header (same header declaration as `edit_cell`); returns `report_view`.
- `POST /api/researches/{research_id}/reports/{report_id}/sections/{section_id}/acknowledge-changes` with body
  `{change_keys: list[str]}` (1 to 500 items, each max 200 chars); returns `report_view`.
- Both go through the existing CSRF and Host/Origin middleware like every other mutation; do not add auth code.

### 5. Research purge

`Store.purge_research` (`backend/deixis/workflow/store.py`) today deletes `runs` but no report rows, so a
research with a report probably cannot be purged at all (foreign keys are on). First write test 11b and run it on
the unchanged code; report whether it already fails. Then add the report deletions to `purge_research`, inside
the existing purge authorization and before `runs` / `step_inputs` / `passages` / evidence tables they point at:
`report_stale_acknowledgements`, `report_claim_revisions` (after clearing `report_claims.current_revision_id`),
`report_citation_links`, `report_claim_refs`, `report_claims`, `report_phrase_repairs`, `report_gaps`,
`report_snapshot`, `report_sections`, `reports`, all scoped to the research. This is the only change allowed in
`store.py`. Table purge (`tables.py::purge_table`) with a report pointing at the table is out of scope: report
what happens, do not change it.

## Tests (write them first, see them fail)

Put store-level tests in `tests/test_report_store.py` and route/view tests in `tests/test_report_api.py`
(reuse their existing helpers for building a valid fake-model report; add a small shared helper only if two
tests need it). Synthetic data only.

1. Migration: both tables and both new columns exist; `UPDATE`/`DELETE` on a revision and an acknowledgement
   abort; `DELETE` succeeds with a `research_purge_authorizations` row for that research.
2. Editing a claim of a valid report: new `human_edit` revision, view `text` is the new text, `model_text` the
   old, `edited` true, `version` 2, citations and `report_version` unchanged, `edited_after_version` equals the
   report version, one `report_claim_edited` event.
3. Wrong `expected_version` → 409 and nothing written.
4. Same `Idempotency-Key` twice → one revision; the same key on another claim → 409.
5. Restore to `'model'` and to an earlier revision → `human_restore` revisions with the right text; a revision
   id of another claim → 422; text equal to the current text → 422; empty text → 422; both or neither of
   `text`/`restore_from` → 422.
6. Edit while the report is `in_progress` (or its run not terminal) → 409.
7. A malformed math span gives a `math_not_well_formed` warning and the edit is saved; a claim with
   `count_json` gets `count_not_rechecked`.
8. `save_claims` on a section with a human revision raises `RevisionConflict` and leaves the claims intact.
9. After the report: editing a cited cell through the table API marks the citing section's change open (kind
   `cell_changed`) and not a section that does not cite that cell; report-level `changed_cells` is 1.
10. A cell changed **after the snapshot but before the claims were saved** is still reported (store-level test:
    save a snapshot, edit a cell, then save claims citing it).
11. Excluding a cited source after the report opens a `source_removed` change on the citing sections and counts
    in `removed_sources`; removing its row from the table (source still included) does the same; including a new
    source and adding it to the table counts in `added_sources`, and adding an already-included source to the
    table later counts too.
11a. A section whose claim has a `body_ref` to a claim citing a changed cell shows that change with
    `via: "body_ref"`; a `gap_ref` to a gap whose `basis_cell_ids` holds a changed cell shows it with
    `via: "gap_ref"`; a section with neither shows nothing.
11b. `purge_research` of a trashed research that has a finished report, an edited claim and an acknowledgement
    succeeds and leaves no report rows (see item 5 below).
12. Acknowledge: the change moves out of `open` and `acknowledged_count` becomes 1; editing the same cell again
    opens a new change with a new key; an unknown or no-longer-open key → 409 and nothing written.
13. The HTTP routes: happy path for both, a 409 path for each, and a mutation without the CSRF header is refused
    like other mutations.

## Ground rules

1. **Run NO state-changing git command** (`add`, `commit`, `checkout`, `stash`, `restore`, `reset`, `rebase`).
   `git status` / `git diff` / `git log` are fine. The reviewing session commits.
2. **Do not touch** `apps/web/`, `docs/decisions.md`, `TODO.md`, `.vscode/`, `scripts/local_index.py`,
   `methods/` (the skill package hash must not change), `contracts/`, or any existing migration. In
   `backend/deixis/workflow/store.py` change only `purge_research` (item 5); change `tables.py` only for a shared
   read helper if needed, and say why.
3. **Do not invent.** If something cannot be written as specified, stop that part and report it. Do not build
   anything §0 lists as deferred (publish, section rewrite proposals, stable identities, plan edits, UI).
4. Match the surrounding style: short docstrings that say why, no speculative abstraction, type hints as in the
   neighbouring code, one SQLite connection, short synchronous transactions, events in the same transaction as
   the state they describe.
5. Tests need `PYTHONPATH=backend:.`; set `UV_CACHE_DIR=/tmp/deixis-uv-cache` if the uv cache is unreachable.
   Use `uv run --no-sync`.

## Read first

- `docs/product/p6-slice4-editing-stale-measurement.md` §0, then §2 (S1, S2, S5, S7, S10) and §3.
- `backend/deixis/workflow/report/store.py`, `snapshot.py`; `backend/deixis/workflow/report/sections.py` around
  `save_claims` and `finalize`.
- `backend/deixis/workflow/tables.py::edit_cell`, `_set_current`, `_replayed_revision` (the pattern to mirror).
- `backend/deixis/storage/migrations/0020_evidence_tables.sql` (triggers), `0035_report_run_kind.sql`.
- `backend/deixis/workflow/views.py::report_view`; `backend/deixis/api/app.py` report and cell routes and the
  exception handlers.
- `tests/test_report_api.py`, `tests/test_report_store.py`, `tests/test_report_flow.py` (fake report adapter).

## Procedure

1. Read everything above.
2. Baseline: `PYTHONPATH=backend:. uv run --no-sync pytest -q`. Record the exact numbers. The only known
   failure is `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit` (it may
   pass on a quiet machine).
3. Write the failing tests, run them, see them fail.
4. Implement; run the new tests, then the whole suite.

## Final message

- files changed, and the migration number used;
- the source-removal stamp column you chose and why it changes on every removal;
- which 422 error class you used;
- before/after test counts and any new failure;
- every place this brief could not be followed as written, and what you did instead;
- anything you found missing, contradictory or already broken (for example whether `purge_research` deletes
  report rows at all);
- what you did NOT do.
