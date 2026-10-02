<!-- PLAN-REVIEW-ROUNDS: r1: hazır değil, 3 high (REPLACE could replace a sealed revision row; export printed the anchors-located success sentence for zero links; contradictory read-authority wording for report_claim_revision_links) + 3 medium (zero-link current-mode test too weak; fixture could mask the new lifecycle branch; AST scan alone does not prove the view/staleness read point and S7/gap_ref cases missing), all folded in; r2: hazır değil, 2 high (explicit-rowid REPLACE escape on the revision and link tables; leftover contradictory "one place that reads" wording), both folded in; r3: hazır, 0 high -->

# Task: P6 slice 4, batch E2, citation removal from an edited claim and one recorded effective citation set (storage, store action, read point, staleness, view, export, lifecycle)

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-e2` (detached at `def7c26`, main with D147 to D149 and E1 = D148). Read `AGENTS.md`,
`CLAUDE.md`, `docs/decisions.md` D147, D148 (E1), D112 (claim edit with history), D113 to D129 (slice 1 report), and
`docs/product/p6-slice4-editing-stale-measurement.md`: §0 (F6, F9), §1, §2 ("Atıf kaldırma"), §3 (S3, S4, S6, S7), §4 (the effective-citation,
staleness and "edited basis" bullets), §6 (the `report_claim_revisions` columns, `report_claim_revision_links`, "Etkin atıf tanımı", edit
request and idempotency bullets, `report_view` bullet), §7 items 1 to 5, §8 (first and third bullets, behavior only), §9 (the E2 test line
and the Akış/API line), §11, §12, §14 "E2". The note is in Turkish; this prompt is the binding English scope. Where the code differs from what
this prompt says, report it.
Patterns to copy: migration `0056_report_claim_revisions.sql` (immutable table, purge-authorization delete trigger) and `0061_report_edit_checks.sql`;
`docs/product/p6-slice4-e1-prompt.md` (the sibling batch; its limits bind you); `ReportStore.edit_claim`, `claim_revisions`, `effective_links`,
`evidence_changes` in `workflow/report/store.py`; `workflow/views.py::report_view`; `workflow/report/export.py::to_markdown`;
`Store.purge_research`, `research_cites_asset`, `asset_impact`, `cited_source_versions` in `workflow/store.py`; `tests/test_report_edit_check.py`,
`tests/test_report_store.py` (`_finished_claim`, `test_edit_history_restore_warnings_and_replay`), `tests/test_backup.py`
(`test_backup_restore_preserves_report_edit_checks_identically_without_models`), `tests/test_migrations.py` (the 0061 migration test),
`tests/test_asset_replacement.py`, `tests/test_candidate_store.py::test_research_cites_asset_and_asset_impact_count_only_candidate_passage_quotes`.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted.
Do not invent; report what you could not find. **No model call, no provider call, no network, no measurement.** Do not touch `../DEIXIS`,
`../DEIXIS-k4` (a web UI batch for slice 3 runs there), `../DEIXIS-x0` and any `../DEIXIS-x*` (slice 5 LaTeX export; it will read report
citations through `ReportStore.effective_links`, so keep that the single read point and keep its row shape), `.local/`, `TODO.md`, `.vscode/`,
`scripts/local_index.py`, `docs/product/sw-status.md`, ports 8765 and 8858-8864, or the live data directory. Backend tests need
`PYTHONPATH=backend:.` and `UV_CACHE_DIR=/tmp/deixis-uv-cache`. No `apps/web` change (E3 owns the screen), no method file or contract schema
change, no new model task (`skill_package_hash` stays `sha256:8e1e4a8453a286ac9da8628dd095dd7796f3a49ae374d7930cb3ef06c546ee76`; report it
before and after). Keep edits in shared files (`workflow/store.py`, `workflow/views.py`, `api/app.py`, `workflow/report/store.py`,
`workflow/report/assembly.py`, `workflow/report/export.py`) small and local: other batches rebase over them.

## Why

Slice 1's report cannot lose a wrong citation: D112's edit changes text and leaves every citation link in place (§0 F6). E2 lets the owner
remove citations from a claim, reversibly and with history. Every revision records the claim's complete **effective citation set**, sealed at
insert; one definition of "effective link" (`ReportStore.effective_links`) feeds the edit check (E1), section-level staleness, reference
numbering, the view and the export; no link row is ever deleted or rewritten. A claim with no effective citation is a visible state ("no direct
citations"), not a refusal, because a body or gap reference, or a count, may still support it. Report-level snapshot counts stay independent of
removals. E2 also closes the lifecycle gap that report citations are invisible to `research_cites_asset` and `asset_impact` (F9), and the
trashed-research gap in `edit_claim`. Removing a citation reduces evidence; it cannot add one. E2 says nothing about whether a remaining
citation supports its sentence.

## What is and is not in code (checked on def7c26; re-check, do not assume)

- In code: migrations up to `0061_report_edit_checks.sql`; `report_claim_revisions` (0056: `kind` `human_edit`/`human_restore`, `restored_from`,
  `idempotency_key UNIQUE`, update trigger aborts, delete trigger aborts unless purge-authorized); `ReportStore.edit_claim(research_id, report_id,
  claim_id, *, text, restore_from, note, expected_version, idempotency_key)` which keeps links fixed, replays an idempotency key by returning the
  earlier revision without comparing content, and does not check that the research is active; `ReportStore.effective_links` (E1) returning **all**
  `report_citation_links` rows with `claim_key` and `section_id`, ordered by rowid, used by current-mode assembly and `edit_check.manifest`;
  `ReportStore.evidence_changes` reading `report_citation_links` directly for section-level staleness; `report_view` reading
  `report_citation_links` directly per claim for `evidence` and numbering; `export.to_markdown` working only from the view;
  `research_cites_asset` and `asset_impact` that do not count report citations; `cited_source_versions`, `purge_sources`' "cited" listing
  and `Store.purge_research` that already treat `report_citation_links` rows as citations (all rows, so removed links keep protecting their
  sources); `storage/backup.py` copying the whole SQLite file.
- Not in code: `link_count`, `request_hash`, `report_claim_revision_links`, a `link_ids` request field, citation-only edits, restore of citation
  sets, a redefined `effective_links`, `evidence_basis`/`removed_links`/revision link fields in the view, report citations in
  `research_cites_asset`/`asset_impact`. Check, do not assume.
- Base-mode callers of assembly are `workflow/report/sections.py` (end of a report run) and `ReportStore.revert_repair`; they, `review.py`
  (the D118 review of the model's base version), `sections.py`' own link read and `save_claims` keep their raw `report_citation_links` reads.
  The design note and E1 text wrongly name `finalize` as an assembly caller; it is not one.

## Decisions (already taken; do not reopen)

1. **Migration**: one file, next number after the highest in `backend/deixis/storage/migrations/` (expected `0062_report_claim_links.sql`;
   check at write time and report the number). Never edit an applied migration. Contents:
   - `ALTER TABLE report_claim_revisions ADD COLUMN link_count INTEGER` (NULL = a revision written before this migration: every original link of
     the claim is effective; a number N >= 0 = the size of this revision's recorded set, 0 for the empty set) and `ADD COLUMN request_hash TEXT`
     (NULL = old revision: idempotency keeps the D112 replay behavior). Existing rows are not rewritten; the 0056 update trigger does not fire for
     `ALTER`. Add `CHECK`s only if SQLite allows them on `ALTER ... ADD COLUMN` without a table rebuild; otherwise enforce non-negativity in the
     store and a `BEFORE INSERT` trigger on `report_claim_revisions` (abort when `link_count < 0`).
   - `report_claim_revision_links (revision_id TEXT NOT NULL REFERENCES report_claim_revisions(id), link_id TEXT NOT NULL REFERENCES
     report_citation_links(id), PRIMARY KEY (revision_id, link_id)) WITHOUT ROWID`, append-only: `BEFORE UPDATE` aborts; `BEFORE DELETE` aborts unless the
     owning research (revision to claim to section to report to research) is in `research_purge_authorizations` (copy the 0056 shape);
     **sealing** `BEFORE INSERT` trigger: abort when the revision's `link_count` is NULL, abort when the revision already has `link_count` rows
     in this table (late insert, empty set and old revision all refused), abort when the link's `claim_id` differs from the revision's `claim_id`.
     **REPLACE guard** (the connection does not enable `recursive_triggers`, so `INSERT OR REPLACE` deletes a conflicting row without firing the
     delete trigger): copy `0059_lineage_links.sql`'s `*_no_conflicting_insert` triggers: a `BEFORE INSERT` trigger on `report_claim_revisions` that
     aborts when a row with the same `id` exists or when `NEW.idempotency_key IS NOT NULL` and a row with that key exists, and the same kind of trigger
     on `report_claim_revision_links` for an existing `(revision_id, link_id)`. **Explicit-rowid REPLACE**: `report_claim_revisions` is an ordinary rowid table, so a `BEFORE INSERT` trigger there
     must also abort when an explicit `NEW.rowid` collides with an existing row (verify in an in-memory database how SQLite exposes `NEW.rowid` in
     a `BEFORE INSERT` trigger and write the condition that really catches `INSERT OR REPLACE INTO report_claim_revisions (rowid, ...)`); the link
     table is created `WITHOUT ROWID` so it has no rowid to collide on. Regression tests for both escape routes: (a) `INSERT OR REPLACE` on a sealed
     revision by `id` and by explicit `rowid`, changing its `link_count`, refused; (b) a link row cannot be moved to another revision or replaced by
     any `INSERT OR REPLACE`, and a late link still cannot be added afterwards; a revision with no links cannot be deleted or replaced the same way.
     The store action inserts the revision row with `link_count = N` and the N link rows in the same transaction and, before the transaction
     ends, checks the row count equals `link_count` (raise `RuntimeError` or `ValueError`, rolling everything back, if not).
   - `PRAGMA foreign_key_check` empty and `foreign_keys` ON after migration; an empty and a populated library migrate with no existing row changed.
2. **One effective definition, one read point.** `ReportStore.effective_links(report_id) -> list[dict]` keeps its signature, row shape
   (`l.*`, `claim_key`, `section_id`) and ordering (`ORDER BY l.rowid`) and is redefined: a link is effective when its claim has no
   `current_revision_id`, or that revision's `link_count` is NULL, or `report_claim_revision_links` holds `(current revision, link)`. The
   definition appears **once** in the code (one SQL statement, not two copies that could drift). Add `ReportStore.removed_links(report_id)`:
   the report's `report_citation_links` rows that are not effective (same row shape; computed from `effective_links` ids, not a second copy of the
   rule), and `ReportStore.original_links(claim_id)` returning a claim's original link rows (used to validate `link_ids` and for restore of an old
   revision). No other code outside this set, the base-mode paths named above, `save_claims` and the lifecycle/purge code in `workflow/store.py`
   reads `report_citation_links`. A test enforces this by parsing the Python sources of `backend/deixis` with `ast`: collect every function (by
   file and qualified name) whose string constants mention `report_citation_links`, and assert the set equals a fixed allowlist written in the
   test. The allowlist is exactly the functions that exist after your change and are named above (base-mode `assembly._links` and
   `assembly._claim_depths` base branch and `assembly` base gap-basis read, `sections.py` link read, `review.py` link read, `ReportStore.save_claims`,
   `ReportStore.effective_links`, `ReportStore.removed_links` if it needs raw SQL, `ReportStore.original_links`, `Store.purge_research`,
   `Store.cited_source_versions`, the corpus-removal listing in `workflow/store.py`, `Store.research_cites_asset`, `Store.asset_impact`). After
   your change `views.report_view` and `ReportStore.evidence_changes` must not be in it.
   Reads of `report_claim_revision_links` have their own explicit, tested allowlist (same `ast` method): `ReportStore.effective_links` (the
   membership test inside the one definition), `ReportStore.claim_revisions` (the only place that projects a historical revision's `link_ids` for the
   view), the `edit_claim` write path (reads a restore target's set and the post-insert row-count check), and `Store.purge_research`. `report_view` and
   `evidence_changes` never read it directly and never build their own effectiveness rule. The source scan is completed by a **runtime guard**:
   trace SQL with `conn.set_trace_callback` while `report_view` and `evidence_changes` run on a report with removed links, and fail if any
   statement mentioning `report_citation_links` or `report_claim_revision_links` runs outside a call to `effective_links`, `removed_links`,
   `claim_revisions`; and monkeypatch `original_links` to raise while they run (they must not use the original set).
3. **Edit request.** `ReportClaimEdit` (API) and `edit_claim` gain `link_ids: list[str] | None` (API: at most 200 items, each at most 40
   characters; default none = "not given"). Rules, in this order inside the one transaction:
   (a) `Store.research(research_id)` first (a trashed or unknown research is `NotFound` and nothing is written; this closes the trashed-research
   gap for `edit_claim`; do not change other store actions);
   (b) claim lookup as today (404 `NotFound` for another research's or report's claim);
   (c) idempotency replay: a `Idempotency-Key` already stored on a revision of **another claim** raises `RevisionConflict` as today; on this claim,
   a stored revision with `request_hash IS NULL` returns that revision without writing (D112 behavior kept for old rows); a revision with a
   `request_hash` returns it without writing only when the new request's hash is equal, else raises `RevisionConflict` ("This idempotency key was
   used for a different edit"); `expected_version` is not consulted on a replay (as today);
   (d) report/run state check and `check_expected_version` as today;
   (e) shape: exactly one of three shapes is valid: `text` and/or `link_ids` (an edit; at least one given), or `restore_from` alone. `restore_from`
   together with `text` or `link_ids`, or none of the three, raises `InvalidTableInput` (422). `link_ids = []` is valid (remove every citation);
   (f) `link_ids` are deduplicated and must each be an **original** link of this claim (`original_links(claim_id)`); an unknown id or another
   claim's link raises `InvalidTableInput`. Adding a link that is not one of the claim's original links is impossible by construction;
   (g) the new text is: `text` stripped when given; for `restore_from`, the target revision's text (`"model"` = `report_claims.text`); for a
   citation-only edit, the claim's **current** text (current revision text, else model text). The new effective set is: `link_ids` when given; the
   current effective set when `link_ids` is not given; for a restore, the target revision's recorded set (a target revision with `link_count IS
   NULL`, and `"model"`, mean **all original links** of the claim). Store sets as sorted-by-link-rowid link ids;
   (h) an edit whose new text equals the current text **and** whose new set equals the current effective set raises `InvalidTableInput` (today's
   "different from the current text" refusal, widened); an empty text still raises; a citation-only edit is valid;
   (i) warnings as today, computed from the new text (a citation-only edit keeps `count_not_rechecked` for a count claim; do not change the
   warning kinds);
   (j) insert the revision with `link_count = len(new set)` and `request_hash`, then the link rows, then update the claim (`current_revision_id`,
   `version + 1`), `reports.updated_at`, and write the `report_claim_edited` event (add `link_count` to its payload), all in the same transaction.
   `request_hash` = sha256 hex of canonical JSON (`sort_keys`, compact separators, `ensure_ascii=False`) of `{"text": stripped text or null,
   "restore_from": ..., "link_ids": sorted unique list or null, "note": stripped note or null}` computed from the raw request before validation
   (so the same request always hashes the same). A `link_ids` of `null` and of `[]` hash differently. Every new revision stores a hash, including
   requests that carry no `Idempotency-Key`.
   `kind` stays `human_edit` for an edit and `human_restore` for a restore. Update `test_edit_history_restore_warnings_and_replay` (the same key
   with different content now raises `RevisionConflict`, with equal content returns the same revision) and add a legacy case (a revision inserted
   with `request_hash` NULL replays as in D112). The API maps `RevisionConflict` to 409 and `InvalidTableInput` to 422 as it does today; verify.
4. **Staleness.** `evidence_changes` derives each claim's direct changes (and so the `body_ref`/`gap_ref` indirect ones that read
   `direct[...]`) from `effective_links` instead of raw links. The report-level numbers (`changed_cells`, `removed_sources`, `added_sources`,
   `revised_columns`, `any`) are computed exactly as today, independent of removals. A removed link's cell changing later opens no change on that
   claim; restoring the link re-derives it from the then-current state; acknowledgement keys (`cell:{id}:{revision}`, `source:{id}:{stamp}`) are
   unchanged, so an acknowledgement made while a link was effective still hides the same change after restore. Gap basis cell ids (from
   `report_gaps`) are not affected by claim-link removal.
5. **View** (`report_view`; additive, keep existing keys). Per claim: `evidence` = the claim's **effective** links only, each with a new
   `link_id` (keep `ref_number`, `open_passage_id` etc. as today); numbering, `references`, `first_passage`, `cited_cells` and `table_i` row
   numbers come from effective links only, so a source cited only by removed links disappears from the numbering and the reference list.
   New per claim: `original_evidence_count`; `removed_links` (for each removed link: `link_id`, `passage_id`, `cell_id`, `source_version_id`,
   `anchor_text`, `anchor_match`, plus `source_key` and `title` when the source version exists); `evidence_basis` (`"direct"` when at least one
   effective link, else `"none"`); `support_type_note` (`"model_written_type"` when `evidence_basis` is `"none"` and `original_evidence_count > 0`,
   else `null`); `edited_basis` (sorted claim keys of the edited claims it rests on, empty list when none: for each `body_ref` that resolves to
   exactly one claim of another section by the same rule `evidence_changes` uses, and each `basis_claim_keys` entry of each `gap_ref`'s gap that
   resolves to exactly one claim, include the key when that claim has a `current_revision_id`). New per revision in `revisions`: `link_count`
   (null for an old revision) and `link_ids` (null for an old revision, else the recorded ids), plus `changes_current` (true when restoring it
   would change the claim's text or effective set, using "all original links" for a NULL `link_count`). the projection of a historical revision's `link_ids` for the view happens only in
   `claim_revisions` (all other access to that table follows decision 2's allowlist); the view never merges its own copy of the effective rule. `has_human_edits` already covers citation-only
   edits (it tests for any revision row); keep that.
6. **Export** (`to_markdown`, from the view only). Reference numbers and the reference list follow the view, so removed citations vanish from
   both. The paragraph with the anchor sentence also says, only when at least one claim has `evidence_basis == "none"` and `support_type_note`
   not null (all of a claim's citations were removed), a sentence "N claims have no direct citations after citations were removed by hand."
   (English) and a Turkish twin, N = that count; nothing is printed when N is 0, so a report with no removals exports byte-identically to today.
   Claims that never had citations are not counted (judgement: they are model output, not an owner removal). Keep the existing edit-check and
   review sentences.
   **The anchor success sentence must not be printed for zero links after a removal.** Today `located == len(links)` is true for zero links and the
   export says "Anchors were located in the cited passages or cells." When the total number of effective links over all claims is 0 **and** at least one
   claim has a `support_type_note` (citations were removed by hand), replace that sentence by "No citation anchors remain after citations were removed
   by hand." (English) and a Turkish twin; every other case keeps today's logic and wording, so exports of reports with no removals stay byte-identical
   (including a report that never had a link). Test English and Turkish: the success sentence is absent when all citations were removed, present and
   unchanged when removals leave at least one located link, and the zero-link, no-removal export is unchanged.
7. **Lifecycle** (migration, not model code). `Store.purge_research` deletes `report_claim_revision_links` **before** `report_claim_revisions`
   and `report_citation_links` (and after `UPDATE report_claims SET current_revision_id = NULL`, as the existing order requires); a trashed
   research keeps everything; restore keeps everything. `research_cites_asset` gains a `UNION ALL` branch: a `report_citation_links` row with a
   `passage_id` in the asset whose claim belongs to a report of this research (effective **and** removed rows, since a removed link can be
   restored). `asset_impact` gains `report_citations`: the count of `report_citation_links` rows (all, effective and removed) whose `passage_id`
   is in the asset; existing keys keep their values. `cited_source_versions` and the removed-source "cited" listing already count every link row;
   add tests proving a source whose only citation was removed from the report is still protected (`purge_sources` refuses) and still listed as
   cited. Cell links (`cell_id`, no `passage_id`) are covered by the existing cell evidence branches; do not duplicate them. Backup needs no
   code change; prove it with a test: a library holding citation-removed and restored revisions, migrate, backup, restore, then compare every row
   of the new and changed tables and the effective links before and after (copy the E1 backup test). Report a code change only if the test
   shows one is needed.
8. **Assembly and edit check stay as E1 left them** except through `effective_links`: current mode already reads only `effective_links` for
   links; do not edit `assembly.py` unless a test proves a current-mode rule mishandles a claim with zero effective links (then fix minimally and
   keep base mode byte-identical; the E1 base-output literal test in `tests/test_report_edit_check.py` and the three existing assembly, flow and
   review test files must pass unchanged). A claim whose citations were all removed must not crash current mode, must not appear as an error by
   itself, and must not be reported as clean where a rule cannot run (E1's `derived_depth_not_checked`/`count_text_not_checked` skips apply).
   The edit check's fingerprint changes when the effective set changes (it already hashes `effective_links`); add a test. The edit check of E1
   reads claims with `current_revision_id` as edited, also for a citation-only revision; leave that and report it under judgement calls.
9. **No model call; no new route.** The existing `PUT .../claims/{claim_id}` carries `link_ids`; the response stays `report_view`. No other API
   change. `purge_table` and the other D112 open debts are untouched.

## Files allowed

`backend/deixis/storage/migrations/0062_report_claim_links.sql` (new), `backend/deixis/workflow/report/store.py`, `backend/deixis/workflow/views.py`,
`backend/deixis/workflow/report/export.py`, `backend/deixis/workflow/store.py` (`purge_research`, `research_cites_asset`, `asset_impact` only),
`backend/deixis/api/app.py` (`ReportClaimEdit` and the edit route only), `backend/deixis/workflow/report/assembly.py` only under decision 8,
`tests/test_report_claim_links.py` (new), `tests/test_report_store.py`, `tests/test_report_api.py`, `tests/test_report_export.py`,
`tests/test_asset_replacement.py` or `tests/test_corpus_removal.py` (whichever fits the existing patterns), `tests/test_backup.py`,
`tests/test_migrations.py` (new-migration test; update the expected migration lists that now end in 62), `tests/test_trash_backup.py` if needed
for purge. Not allowed: `apps/web`, `methods/`, `contracts/`, `domain/contracts.py`, `workflow/report/sections.py`, `review.py`,
`phrasing.py`, `phrasebank.py`, `workflow/report/edit_check.py` (it already reads `effective_links`; report if it needs a change), `docs/decisions.md`
and the slice note (the orchestrator writes them), other migrations.

## Tests to add (synthetic, no model)

Use the `report_with_sections` fixture of `tests/test_report_assembly.py` and the `_finished_claim` helper of `tests/test_report_store.py`.

- Migration: empty and populated library migrate; old revisions have `link_count IS NULL` and every original link is effective; foreign keys.
  Sealing: a late link insert, an insert into an empty-set revision, an insert for an old revision (NULL `link_count`), and a link of another
  claim are all refused; update refused; delete refused without purge authorization, with another research's authorization, allowed with the right one.
- Store: citation-only edit (text unchanged) valid; text-plus-set edit; empty set; `link_ids` order and duplicate canonicalisation; unknown
  link, another claim's link, `restore_from` with `text` or `link_ids`, neither given: `InvalidTableInput`; no-op (same text and same set)
  refused; restore returns text and set together (3 links to 2 and back); restore of an old NULL revision and of `"model"` brings back all
  original links; the original link rows are never deleted or changed (compare `report_citation_links` before and after); version bumps and a
  stale `expected_version` is a 409; two-tab case: the second editor with the old version gets `RevisionConflict` and nothing is written.
- Idempotency: equal content replays the same revision with no write; different content under the same key raises `RevisionConflict`; the same
  key on another claim raises; after an intermediate edit a replay of the first request still returns the first revision (as D112 order);
  `link_ids=None` versus `[]` hash differently; legacy NULL `request_hash` revision replays as D112.
- Trashed research: `edit_claim` raises `NotFound` and writes nothing (no revision, no event).
- Effective definition: `effective_links` excludes removed links, includes all for an unedited claim and for an old revision; ordering by rowid;
  the `ast` source-scan test (decision 2).
- Staleness (include the S7 source case, the `gap_ref` path and the basis cells): change a cell cited only by a removed link, `evidence_changes` opens nothing on that claim's section (and nothing via `body_ref`
  from another section) while `changed_cells` still counts it; restore the link and the change opens; acknowledgement made before removal still
  hides it after restore; report-level counts identical before and after a removal; a still-effective link's change still opens; a source removed from the research after the claim lost its only link to it opens no section mark while
  `removed_sources` still counts it (S7), and restoring the link opens it; a change that reaches a section through `gap_ref` `basis_claim_keys` follows the
  other claim's effective links; changes of a gap's `basis_cell_ids` are unaffected by claim-link removal.
- View: effective `evidence` with `link_id`; `removed_links`; `evidence_basis` and `support_type_note` for a fully de-cited claim (and `null` note
  for a claim that never had links); reference numbers and the `references` list drop a source that only removed links cited; `revisions` carry
  `link_count`, `link_ids`, `changes_current`; `edited_basis` through `body_ref` and through a gap's `basis_claim_keys`; `has_human_edits` true after a
  citation-only edit.
- Export: no removals give exactly today's output (golden comparison to a pre-change export of the same fixture, captured on `def7c26` before
  editing and pasted as a literal or a stored fixture inside the test); a removal drops the number and the reference; the new sentence appears only
  for a fully de-cited claim, in English and Turkish.
- Edit check: with **real removal revisions** (not model-fixture edits), cases for a VII claim whose only basis was a future-work cell link, an equation
  claim whose origin passage link is removed, and a derived-section claim whose body-ref target loses its links: current mode does not crash, never
  reports clean where a rule cannot run (each non-runnable check is an explicit `skipped` entry), and the outcome of each rule that can run is asserted
  exactly (an error that is the honest consequence of the removal, such as `vii_claim_without_basis` or `equation_origin_not_cited`, is expected and
  asserted; base mode shows none of them). The fingerprint changes when a link is removed and again when it is restored; the E1 tests still pass unchanged.
- Lifecycle (use a **dedicated source and asset cited only by a report passage link**: assert it has no answer, table row, cell, lineage or candidate
  citation, so the new `research_cites_asset` branch and the existing `cited_source_versions` cannot pass through another path; the shared
  `report_with_sections` source is not enough): `purge_research` with revisions and sets present succeeds and leaves no `report_claim_revision_links` rows; trash and restore keep
  rows; `research_cites_asset` true and `asset_impact["report_citations"]` counts for a report passage link, also after the link is removed;
  another research is not affected; `cited_source_versions` and `purge_sources` still protect a source whose only citation was removed, before removal,
  after removal and after restore; if `tests/test_asset_replacement.py` already drives the asset-removal routes that `research_cites_asset` governs
  (`api/app.py` around the three calls), add one API-level case there, otherwise report that it was not added; backup and restore round-trip
  identical rows.
- API (`tests/test_report_api.py`): `PUT .../claims/{id}` with `link_ids` returns the view with the new set; two-tab 409; unknown or other claim's
  `link_ids` 422; another research's report 404; unfinished report run 409.

## Checks to run

Focused while developing: `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache UV_OFFLINE=1 uv run pytest tests/test_report_claim_links.py
tests/test_report_edit_check.py tests/test_report_assembly.py tests/test_report_flow.py tests/test_report_review.py tests/test_report_store.py
tests/test_report_api.py tests/test_report_export.py tests/test_migrations.py tests/test_backup.py tests/test_corpus_removal.py
tests/test_asset_replacement.py tests/test_trash_backup.py tests/test_candidate_store.py tests/test_lineage_store.py -q`. Then the full suite is run by the
orchestrator. `git diff --check` clean. Print `skill_package_hash` before and after. Do not run Playwright or npm.

## Report back (concise)

Files changed, migration number, the effective-definition location, the allowlist from decision 2, test counts and the focused command, every
judgement call (especially: citation-only revision counted as an edited claim by E1; `support_type_note` and export counts limited to fully
de-cited claims; `report_citations` counts passage links only), anything you could not find, and anything E3 (screen) or E4 (scripted sequence)
must know about field names. Do not write decision or note text.
