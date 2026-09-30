<!-- PLAN-REVIEW-ROUNDS: gpt-6.1-sol high, r1: 2 high (migration-list assertion outside the allowed files; replay key not bound to table and action) + 4 medium/low, all folded in; r2: 1 high (key name space still collidable with an ordinary add_column client key) + 1 low, folded in as a prefix-first name space and cross-order tests; r3 not run, the fix is the reviewer's own suggestion; code review r1: 0 high, 1 medium (D131 verification text out of date, fixed) + 3 low (template test assertion strengthened; arXiv pin and 390 px assertion judged reasonable) -->

# Task: P6 slice 2, batch L1, role-marked development columns and the "Add development columns" action

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-l1` (detached at `3b703c8`, main with D130). Read
`AGENTS.md`, `CLAUDE.md`, `.impeccable.md` (before touching `apps/web`), `docs/decisions.md` D130 (top), and
`docs/product/p6-slice2-chain-of-ideas.md`: §1 (table row "P5 kanıt tablosu"), §4.2, §5 (the "L1" SQL block), §6 (the
three column instructions, verbatim), §12 "Düğüm sütunları", §18 question 1, §19 "L1". The scope below was decided by the
main session and binds this prompt; where the code differs from what this prompt says, report it.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change
uncommitted. Do not invent; report what you could not find. **No real-model calls. No measurement.** Do not touch
`../DEIXIS`, `.local/`, `TODO.md`, `.vscode/`, `scripts/local_index.py`, `docs/product/sw-status.md`, ports 8765 and
8858-8864. Backend tests need `PYTHONPATH=backend:.` and `UV_CACHE_DIR=/tmp/deixis-uv-cache`. For the web build and
Playwright the worktree needs `apps/web/node_modules`: the orchestrator has already placed a real copy (not a symlink)
there; never symlink into `../DEIXIS`, because the TypeScript build caches would be written into that checkout.

## Why

Slice 2 (Chain of Ideas) records, per work, three node cells: the problem addressed, what was established or changed,
the uncertainty left. They are ordinary visible `text` columns of the P5 evidence table, filled by the existing
`cell_extraction` with quotes, so they inherit append-only revisions, human-edit protection, recheck and quote
verification (D37/D38). Later batches (L2 to L7) must find them, so a column needs a stable **role** that survives
renames and moves. L1 adds only that marker, the explicit action that adds the three columns, and the rules that keep
the marker honest. Nothing reads the role yet.

## What is and is not in code (checked on 3b703c8)

- `table_columns` (migration 0020) has `origin` in {user, model_suggestion, template} and no role. Last migration is
  `0057_report_review.sql`; the next file is `0058_lineage_role.sql`.
- `workflow/tables.py::TableStore`: `add_column` (idempotent through `column_revisions.idempotency_key`, checks the
  table `expected_version`, appends at `MAX(position)+1`), `apply_template` (key suffix `:{index}`), `revise_column`
  (new column revision when the definition changes; `format` change drops fields the new format does not use; a changed
  definition change, name included, makes a new column revision and existing cells read as stale; a position-only change
  adds no revision; all of that stays as is), `remove_column` (sets `removed_at`), `restore_column` (clears it),
  `create_template` (copies `name, instruction, answer_format, options, allow_multiple, unit_hint` only), `table_view`
  (columns carry `id, position, revision, version, origin, name, instruction, answer_format, options, allow_multiple,
  unit_hint`). `MAX_TEXT_VALUE = 500`. `column_spec` normalises a definition and is used for every column write.
- `api/app.py`: `POST {table_path}/columns` (201), `PATCH/DELETE/POST restore` on `/columns/{column_id}`, `POST
  {table_path}/template-columns`; every mutation returns `tables.table_view(...)`; `InvalidTableInput` becomes 422.
- `apps/web/src/EvidenceTable.tsx`: toolbar `Add column`, `Suggest columns`, etc. (line ~345); the zero-column prompt has
  its own `Add column` / `Suggest columns` buttons (line ~411); `ColumnEditor` is the column sheet (line ~524);
  `api.ts::addColumn` and `TableColumn` (line ~637); strings go through `t()` with Turkish entries in `i18n.ts`.
- `report_ready` and `build_snapshot` read **every active column** of the table through `target_columns`; they know
  nothing about roles. The new columns are therefore ordinary columns to the report (a known, accepted interaction,
  D130 and §4.2). Slice 1's report code must not change.

## Decisions (already taken; do not reopen)

1. **Migration `0058_lineage_role.sql`** exactly as §5's L1 block: `ALTER TABLE table_columns ADD COLUMN lineage_role
   TEXT CHECK (lineage_role IN ('problem', 'change', 'uncertainty'))` and the partial unique index
   `table_columns_lineage_role ON table_columns (table_id, lineage_role) WHERE lineage_role IS NOT NULL AND removed_at
   IS NULL`. Existing rows stay NULL. No other table changes. No edit of an applied migration.
2. **The role is set only by the action.** `column_spec`, `add_column`, `apply_template`, `create_template`, the API
   column-create body and model column suggestions never take, write or copy a role. A template saved from a table with
   role columns carries the three columns as ordinary columns (no role); a table started from it has no roles. The role
   is not part of a column revision: it lives on `table_columns` and survives name, position and instruction changes.
3. **`TableStore.add_development_columns(research_id, table_id, expected_version, idempotency_key) -> None`.**
   One transaction. Idempotent replay first: the revision key of this action is
   `lineage-columns:{research_id}:{table_id}:{key}:{role}`. The prefix sits **in front of** the research id, in a name space
   no other writer can produce: `add_column` writes `{research_id}:{key}` and `apply_template` `{research_id}:{key}:{index}`,
   and a research id starts with `res_`, so even a client key that imitates the inner string cannot reproduce this key
   (the column revision key is globally `UNIQUE`, so the name space must be disjoint, not merely filtered by table). If the
   key is given and a `column_revisions.idempotency_key` equal to that exact string for any of the three roles exists
   (revisions of removed columns count: history is not excluded), return without change. Another table or another
   research produces different strings, so the same client key there is not a replay. Otherwise check the
   table `expected_version`, then for each role in the fixed order `problem`, `change`, `uncertainty` that has **no
   active (not removed) column with that role**, insert one `text` column at the next positions after the current
   maximum, with `origin = 'user'`, the role set, and revision key as above (None without a key).
   If all three roles already have an active column the call changes nothing and bumps nothing (no version bump, no
   event) and still returns normally; this is the second idempotency path (no key, or a new key). A no-op leaves no
   stored idempotency record; accepted limit: if a role column is removed afterwards, repeating that same key adds a
   new one (the key was never spent); say so in D131. A removed column that
   holds a role does not count: the action adds a new column for that role. Names, instructions (copy §6 verbatim; do
   not reword, do not add a sentence to `evidence-table.md`):
   - role `problem`: name `Problem addressed`; instruction "The problem or question this work takes up, in its own
     terms, in one or two sentences."
   - role `change`: name `Established or changed`; instruction "What this work states it established, showed or
     changed relative to earlier work. If the passages make no comparison, say so; do not infer one."
   - role `uncertainty`: name `Uncertainty left`; instruction "An uncertainty, limitation or open question the work
     itself names as remaining or as future work. Prefer the stated next step when the source separates a limitation
     from a next step."
   Put the role, name and instruction constants in one small module-level mapping in `tables.py` (for example
   `LINEAGE_ROLE_COLUMNS`); later batches import the role names from there. The table version bumps once and one
   `_changed` event is written for the whole call. Use `column_spec(...)` for each spec so the normal rules apply.
4. **`revise_column` keeps the role honest.** A request whose merged `answer_format` is not `text` on a column that has
   a lineage role raises `InvalidTableInput` (422) without changing anything; the role is not removed by that request
   and there is no request that removes a role in L1. Name, position and instruction changes behave exactly as today
   (an instruction or name change makes a new column revision and existing cells stale, as today; the role stays).
5. **`remove_column` / `restore_column`.** Removing a role column keeps the role on that row. `restore_column` of a
   column whose role is held by another **active** column of the same table raises `InvalidTableInput` (422, a plain
   message naming the conflict) before any write; never let the SQLite unique-index error surface. Restoring when no
   other active column holds the role works as today. The 422 body is the existing `{"detail": ...}` shape.
6. **`table_view` exposes `lineage_role`** (string or null) on each column and nothing else changes in the view.
   `TableColumn` in `api.ts` gets `lineage_role: 'problem' | 'change' | 'uncertainty' | null`.
7. **API.** `POST /api/researches/{research_id}/tables/{table_id}/lineage/columns`, body `ExpectedVersion`, optional
   `Idempotency-Key` header (max 200, same as the others), CSRF as every mutation, returns `tables.table_view(...)`
   with status 200 (a no-op is also 200). No worker wake, no run.
8. **Web, narrow.** (a) `api.addDevelopmentColumns(researchId, tableId, expectedVersion, idempotencyKey)` in `api.ts`.
   (b) A toolbar button `Add development columns` next to `Add column` (same `Button variant="ghost"`, an icon already
   used in the file or a `lucide-react` icon such as `GitBranch`; no new component), shown when the table has columns,
   and the same button in the zero-column prompt row; disabled while `busy`; **not rendered at all when all three roles
   already have an active column** (nothing is left to add, and a title-only disabled button would hide its reason);
   removing one of the role columns brings it back. It calls through the
   existing `act(...)` helper with success text `Development columns added.`, an `onClick` that passes
   `table.table.version` and `newKey()` like `addColumn`. A failed call shows the existing error toast/notice path.
   (c) In `ColumnEditor`, for a column with `lineage_role`, the answer-format control is disabled and a one-line plain
   hint says `This column feeds the development lines and stays a text column.`; the editor still saves name and
   instruction. (d) Turkish entries in `i18n.ts` for every new string (follow how the file writes them). No renamed
   or restyled existing UI, no role badge or pill anywhere, no colour, no new CSS: use the existing toolbar and editor classes; if they truly cannot carry it, stop and report instead of
   editing a stylesheet. Follow `.impeccable.md`.
9. **Slice 1 untouched.** No edit under `backend/deixis/workflow/report/`, no edit of `report_ready` or
   `target_columns` or `build_snapshot`, no change to report schemas, `methods/`, `contracts/`, `flow.py`, `worker.py`.
   `skill_package_hash` must not move (assert it in a test or report the equality).

## Files allowed

`backend/deixis/storage/migrations/0058_lineage_role.sql` (new), `backend/deixis/workflow/tables.py` (columns part,
`table_view`, the constants), `backend/deixis/api/app.py` (one route), `apps/web/src/api.ts`,
`apps/web/src/EvidenceTable.tsx`, `apps/web/src/i18n.ts`, `apps/web/src/labels.ts` only if a string belongs there,
`tests/test_lineage_columns.py` (new), `tests/test_migrations.py` (one new migration test, and the existing assertion at about line 385 that pins the
applied-migration list to `[55, 56, 57]` may be changed to hold once 0058 exists, nothing else in existing tests),
`tests/test_evidence_tables.py`
only if an existing assertion on the exact column-view keys must learn `lineage_role` (say which and why),
`apps/web/e2e/lineage-columns.spec.ts` (new, own port; 8805 was free on this checkout, verify by grepping
`apps/web/e2e` for `Server(` ports and pick an unused one not in 8858-8864 or 8765), `docs/decisions.md` (D131 at the
top), `docs/product/p6-slice2-chain-of-ideas.md` (only the L1 line marked done, see "Decision record"), and this
prompt's comment line.

## Files NOT allowed

Everything else, in particular `backend/deixis/workflow/report/*`, `workflow/flow.py`, `workflow/store.py`,
`domain/*`, `methods/**`, `contracts/**`, `tests/fixtures/research/`, `tests/fakes.py`, other migrations, `scripts/`.
If the work needs one of these, stop and report.

## Tests to add (name them so the limit is readable)

Backend, `tests/test_lineage_columns.py` (fake adapter, temp library, no network):

1. `test_migration_adds_role_column_and_partial_unique_index`: in `tests/test_migrations.py`, apply migrations up to
   0057 on a temporary library with a table and columns, then 0058; existing columns read `lineage_role IS NULL`;
   `PRAGMA foreign_key_check` empty; the index exists; the CHECK refuses a role outside the three; two active columns
   with the same role in one table are refused by SQLite, while a removed one plus an active one are allowed and the
   same role in another table is allowed.
2. `test_add_development_columns_adds_three_text_columns_with_roles`: names, instructions (equal to §6 strings),
   `answer_format = text`, `origin = user`, order problem/change/uncertainty, appended after existing columns, one
   table version bump, columns visible in `table_view` with `lineage_role`.
3. `test_add_development_columns_is_idempotent`: same key twice gives exactly three new columns; a second call with a
   new key and no change adds nothing, does not bump the version and does not raise; a stale `expected_version` on a
   real change raises the usual `RevisionConflict`; the same client key on another table of the same research is not a
   replay and adds that table's columns; an ordinary `add_column` whose client key imitates the inner string (for example `lineage-columns:{table_id}:k:problem`)
   neither makes the action a replay nor is blocked by it, in both call orders and across two tables; a no-op call (three
   roles present, new key), then removing one role column, then the same key again adds exactly the missing role
   (the recorded limit).
4. `test_add_development_columns_adds_only_missing_roles`: a table that already has one role column (made through the
   action, then the other two removed) gets exactly the missing roles; a removed role column does not count as present.
5. `test_add_development_columns_is_atomic`: force a failure on the second insert (monkeypatch `_insert_column` to
   raise the second time) and assert no column, no revision, no version change and no event row remains.
6. `test_role_survives_rename_move_and_instruction_change`: rename, reposition, change instruction (cells become stale
   as today) keep `lineage_role`.
7. `test_role_column_rejects_non_text_format`: `answer_format` `choice`, `number_unit`, `yes_no` all raise
   `InvalidTableInput` and leave the column unchanged; a text-preserving change still works.
8. `test_restore_conflicts_with_active_role_column` and `test_restore_without_conflict_works`: removed role column,
   action adds a new one, restoring the old one raises `InvalidTableInput` with no write; after removing the new one,
   restoring the old one works.
9. `test_templates_and_user_columns_carry_no_role`: a template saved from a table with role columns and a table started
   from it have `lineage_role` NULL everywhere; `add_column` and `apply_template` never set a role; model column
   suggestions untouched (assert on `add_column` with `origin='model_suggestion'`).
10. `test_development_columns_are_ordinary_columns_to_the_report`: documents the accepted interaction (§4.2). On a
    table that is report-ready, adding the development columns makes `report_ready` list the new (empty) cells as
    missing, and `build_snapshot` includes the three columns like any other column. Read the existing report snapshot
    and readiness tests for how to build the state; do not edit report code. The test's docstring says it records a
    known interaction, not a defect fix.
11. `test_api_add_development_columns`: through `create_app` and `TestClient` with the CSRF double-submit as the other
    table tests do: 200 with the table view, three role columns, the same `Idempotency-Key` replay adds nothing, a
    stale `expected_version` gives 409, a non-text PATCH on a role column gives 422 with `detail`, restore conflict
    gives 422, a missing CSRF header is refused like every other mutation, a trashed or unknown table gives 404.
12. `test_skill_package_hash_unchanged_by_l1`: the package hash equals `sha256:cef7c086...` from D129 (read it from
    `decisions.md`/`load_skill_package()` on the base commit and pin the full value in the test only if the repo's
    other tests already pin hashes that way; otherwise report the equality in your final message instead of adding a
    new pin). Slice 1 tests (`tests/test_report_*.py`, `tests/test_evidence_tables.py`) pass unchanged.

Playwright, `apps/web/e2e/lineage-columns.spec.ts` (fixture server, own port, one describe): open a research with a
table that has at least one column (read `report-failed-rows.spec.ts` and `acceptance.spec.ts` for how a table and
columns are created through the API); the toolbar shows `Add development columns`; click it; three columns named as in
decision 3 appear, the success toast shows; the button disappears, so no second copy can be added (count the columns); remove one role column and the button returns, and it is reachable by keyboard; edit one of them: the format control is disabled and the hint shows; reload, the columns are
still there; an empty table shows the same button in its first-column prompt and it works there. Screenshots (below).

## Checks to run

1. `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest` (one known failure:
   `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`; a test that fails under
   parallel load but passes alone: rerun it alone and say so). Baseline on main after D129: 3,131 passed + that failure.
2. `cd apps/web && npm run build && npm run lint` (17 warnings baseline, no new ones) and Playwright against a fresh
   build (`DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance-l1 npm run test:acceptance`; 111 tests today plus the new
   ones).
3. Screenshots at 1440 and 390 px, light and dark, of: the toolbar with the new button, the table after the action
   (three new columns), and the column sheet of a role column with the disabled format control. Look at each image
   (Read the PNG) and fix anything cramped, clipped or unreadable before reporting.
4. `git diff --check`. Report every count. If a tool cannot run in your sandbox (Chrome, loopback ports), say so;
   do not skip silently and do not call an unrun check verified.

## Decision record

`## D131 — P6 slice 2 L1: node columns carry a stable lineage role added only by an explicit action` at the top of
`docs/decisions.md` (above D130), with Status/Date/Context/Decision/Limits; check main's highest number first. Status
`accepted (implemented, uncommitted)`, Date `2026-10-01, P6 slice 2 batch L1`. Limits must say: the role feeds nothing
yet; synthetic data only, no real-model call, no measurement, so the quality of the three columns' cells is unmeasured;
the three columns are ordinary columns to the report, so adding them changes `report_ready` and the snapshot
(recorded, not mitigated, D130); a template does not carry roles; no route removes a role; restoring a removed role
column can conflict and is refused; skill package hash unchanged. Add nothing about results you did not measure. In
the slice 2 note's L1 heading line, append ` ✅ commit: bu satırı ekleyen commit` (no other edit of the note).
