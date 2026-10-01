<!-- PLAN-REVIEW-ROUNDS: gpt-6.1-sol high, r1: hazır değil, 1 high (cycle graph vs stale edges) + 6 medium, all folded in; r2: hazır değil, 1 high (stale exclusion by link id lets a refreshed link hide a cycle) + 1 medium (UNION evidence branch cannot be isolated under the same-source trigger), both folded in; r3: hazır, 0 high; implementation by gpt-6.1-sol; code review r1 hazır değil (1 high REPLACE bypass, 1 medium savepoint), r2 hazır değil (1 high rowid), r3 düzeltmeyle hazır (0 high, 1 medium insertion order), all fixed; see D134 -->

# Task: P6 slice 2, batch L4, durable storage for development links

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-l4` (detached at `93e2d2c`, main with D133). Read `AGENTS.md`,
`CLAUDE.md`, `docs/decisions.md` D130 to D133 (top), and `docs/product/p6-slice2-chain-of-ideas.md`: §3 (rules), §4.3 (all of it),
§5 (SQL and the lifecycle paragraph), §12 "Depolama", §19 "L4". The scope below was decided by the main session and binds this
prompt; where the code differs from what this prompt says, report it. Patterns to copy: migration `0046_fulltext_adjudication_run_kind.sql`
(runs rebuild), `0020_evidence_tables.sql` + `0029_trash_and_corpus_removal.sql` (append-only triggers with research and table purge
authorizations, `cell_evidence_same_source`), `workflow/tables.py::TableStore` (`_insert_revision`, `edit_cell`, `save_model_output`,
`check_expected_version`, `_delete_tables`), and `tests/test_migrations.py` (0046 test: rows survive a runs rebuild).

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted.
Do not invent; report what you could not find. **No real-model calls, no provider calls, no measurement.** Do not touch `../DEIXIS`,
`.local/`, `TODO.md`, `.vscode/`, `scripts/local_index.py`, `docs/product/sw-status.md`, ports 8765 and 8858-8864, or the live data
directory. Backend tests need `PYTHONPATH=backend:.` and `UV_CACHE_DIR=/tmp/deixis-uv-cache`. No web work, no API work, no method or
contract change in this batch (so `skill_package_hash` stays `sha256:371fcecb...`).

## Why

Slice 2 decides, per candidate pair, whether the later work states a development relation to an earlier work. L1 gave role columns,
L2 pure candidate/edge/baseline functions, L3 the contract and transport path. L4 builds only the durable layer: the tables, the
append-only guards, the storage primitives that record and publish decisions, the human write primitives, and the six lifecycle
hooks. Nobody calls the primitives from the flow yet (L5) and no route exposes them (L6). L4 stores *applied* model proposals; it
does not read node cells, build a `lineage_target`, pack candidates, or run a model.

## What is and is not in code (checked on 93e2d2c)

- In code: migrations up to `0058_lineage_role.sql`; `runs` was last rebuilt by `0046` (kinds up to `fulltext_adjudication`);
  `workflow/tables.py` has `TableStore.trash_table` (rejects active runs of kinds `table_fill`, `cell_recheck`, `table_columns`),
  `table_impact`, `purge_table`, `purge_tables`, `_delete_tables`, `LINEAGE_ROLE_COLUMNS`; `workflow/store.py` has
  `cited_source_versions` (four-way UNION), `research_cites_asset`, `asset_impact`, and research deletion calling `purge_tables`;
  `domain/contracts.py` has `locate_anchor`; `workflow/lineage/` holds only L2's pure functions.
- Not in code: any `lineage_links*` table, trigger, `lineage_links` run kind, `LineageStore`, lifecycle hook for lineage. Check, do not assume.

## Decisions (already taken; do not reopen)

1. **One migration**, the next number after `0058` (check the directory; expected `0059_lineage_links.sql`), first line
   `-- deixis:foreign-keys-off`. Order inside the file: (a) rebuild `runs` exactly as `0046` does, same columns, same stage list, same
   `runs_status` index, with `'lineage_links'` added to the `kind` CHECK; update the `target_json` comment to say lineage runs carry
   `{"table_id", "plan_version", ...}` (L5 defines the rest); copy every column list from the current schema, not from memory; (b) the
   three tables of §5 (`lineage_links`, `lineage_link_revisions`, `lineage_link_evidence`) with the CHECKs of §5 **exactly** as the note
   writes them, plus the indexes; (c) triggers (below). Existing migrations are never edited. A comment block explains the lineage
   target and that `lineage_links.current_revision_id` points at a decision record, not at an active link.
2. **Triggers** (SQL names are yours, behavior is fixed):
   - `lineage_link_evidence_same_source` BEFORE INSERT, as §5 (evidence only from the link's `to` version, passage must belong to
     `NEW.source_version_id`).
   - `lineage_link_revisions_no_update` and `lineage_link_evidence_no_update` (always abort); `..._no_delete` for both, aborting unless the
     owning table's research is in `research_purge_authorizations` **or** the table is in `table_purge_authorizations` (0020/0029 pattern;
     join through `lineage_links.table_id` then `evidence_tables`).
   - **Pointer guard** on `lineage_links` (BEFORE INSERT: `current_revision_id` must be NULL; BEFORE UPDATE OF `current_revision_id`:
     when the new value is not NULL, the revision must exist, belong to the same `link_id`, have `disposition = 'accepted'`, be
     `output_status = 'structurally_valid'` when `author = 'model'`, and, when `decision = 'link'`, have at least one
     `lineage_link_evidence` row). This enforces the §4.3 publication conditions at the lowest level, so no code path can point at
     another pair's revision, a rejected one, or an evidence-less active link. Setting the pointer to NULL is always allowed
     (lifecycle).
   - `lineage_links` identity columns (`table_id`, `from_source_version_id`, `to_source_version_id`) cannot be updated.
3. **`workflow/lineage/store.py`, class `LineageStore(store: Store)`**, `self.conn = store.conn`, same style as `TableStore`
   (`transaction()` joins an outer transaction; `InvalidLineageInput` for refused input, `RevisionConflict` for stale versions,
   `NotFound`). It imports `locate_anchor` from `deixis.domain.contracts`. Nothing in `workflow/lineage/{mentions,edges,candidates,baseline}.py`
   changes. No import of `flow.py`.
   - **Vocabulary constants** (module level, tested against the SQL CHECK lists so they cannot drift; `rejection_code` has no SQL enum CHECK in the note, so only `RELATIONS`, `SUPPORT_TYPES`, `DECISIONS` and the revision `kind` values are compared with `sqlite_master`, and `REJECTION_CODES` is the note's list): `RELATIONS`, `SUPPORT_TYPES`,
     `DECISIONS`, `REJECTION_CODES = ("cycle", "anchor_not_found", "same_work", "endpoint_not_included", "superseded_by_human", "stale_input")`,
     `MAX_WHAT_CHANGED = 500`, `MAX_EVIDENCE = 5`.
   - **Pair row**: `ensure_link(table_id, from_svid, to_svid) -> dict` get-or-create (`llk_` id, `version` 0). `from_svid == to_svid` raises
     `InvalidLineageInput` (nothing can be recorded for it; the CHECK would refuse it anyway). Same-work pairs (equal `source_versions.work_id`
     for different version ids) do get a pair row, because a rejected proposal needs somewhere to hang.
   - **Endpoint rule** (`endpoint_not_included`): a version is a live endpoint iff it is a non-removed `table_rows` row of that table, an
     active corpus member of the table's research (the `SOURCE_ACTIVE_SQL` condition of `tables.py`) and `selections.state = 'included'`
     for that research. Check the real `selections` and `corpus_memberships` columns; do not guess. Put the SQL once in this module.
   - **Cycle graph (L4 filters what it can, the caller supplies what it cannot).** The graph used by every cycle check is `active_links` (current revision accepted, `decision='link'`, `relation != 'independent_parallel'`) restricted to pairs whose two ends are live endpoints (rule above), minus the edges named in the optional parameter `stale_revisions: Mapping[str, str] = {}` (link id -> the stale **revision id**); an edge is excluded only while the pair's pointer still equals that stale revision, so a link refreshed earlier in the same batch re-enters the graph under its new revision that `apply_model_proposal(s)`, `add_link` and `edit_link` take. L4 cannot know node-input or extraction staleness (L5b/L6 compute it), so a stale edge is excluded only when the caller names it by revision; with the default an unnamed stale edge still counts, which is a stated limit. `independent_parallel` pairs are never in the graph.
   - **Input contract of `apply_model_proposal`.** L4 receives only decisions that L3's validator and the flow already resolved to real ids. The store still checks shape and raises `InvalidLineageInput` (a caller bug, never a stored rejection; the batch rolls back): `decision` in `DECISIONS`; `link` has `relation`, `what_changed` (1 to 500), `support_type` and 1 to 5 evidence items; any other decision has all three null and no evidence; `independent_parallel` only with `source_stated`; `output_status` in (`structurally_valid`, `unverified_draft`), supplied by the caller from the step's validation result; `step_input_id` non-empty. Meaning and the draft's other fields are not L4's job.
   - **`apply_model_proposal(...)`** (keyword arguments, runs in one transaction that joins the caller's): for one pair, record the
     model's decision and, when the rules allow, publish it as the pair's current decision. Parameters: `research_id, table_id,
     from_svid, to_svid, decision` (the draft's decision item, with **real** ids: `decision`, `relation`, `what_changed`,
     `support_type`, `evidence: [{passage_id, quote}]`, `note`), `edge_state`, `run_id, step_id, step_input_id, scope_revision,
     link_version_at_request, inputs` (a dict of the from/to node cell revision ids the call used, stored verbatim), `input_fingerprint`
     (str), `output_status`, `idempotency_key` (optional). The fingerprint is stored **inside** `inputs_json` as `{"fingerprint": ..., "inputs": ...}`
     (the note's §5 has no fingerprint column; judgement, report it). Rules, first failing wins, in this fixed order:
     1. `same_work`; 2. `endpoint_not_included` (either end); 3. `superseded_by_human` (the pair's current revision has `author = 'human'`,
     including a human removal); 4. `stale_input` (`scope_revision` differs from the research's current one, or `link_version_at_request`
     differs from the pair's `version`; `None` means 0); 5. for `decision = 'link'` only: `anchor_not_found` (every quote must be
     located by `locate_anchor` in the stored text of a passage that belongs to the `to` version; nothing is stored from an unlocated
     quote); 6. for `decision = 'link'` with `relation != 'independent_parallel'` only: `cycle` (adding the directed edge from to `to`
     would close a directed cycle in the current graph, with this pair's own existing edge removed first; the diamond
     `A->B, A->C, B->D, C->D` is valid; an undirected-cycle test would wrongly reject it). `independent_parallel` never adds a
     graph edge and is never cycle-checked.
     A **rejected** proposal is stored as a revision (`disposition = 'rejected'`, the rejection code, the decision fields exactly as the
     model gave them, no evidence rows because stored evidence must be located text, `origin = 'mention'`) and changes nothing else: not the
     pair's pointer, not its `version`, not the graph. An **accepted** proposal stores the revision with `disposition = 'accepted'` and, for
     a link, one evidence row per located quote with `anchor_text` the located source text (never the model's raw quote) and the real
     `anchor_match`; a repeated located text of the same passage within one decision is stored once. Publication of an accepted
     revision: it becomes the current decision iff (a) the pointer is NULL, or (b) the current revision is model-authored and its stored
     fingerprint differs from this one; and the revision is `structurally_valid`. In every other case the accepted revision stays recorded
     and the pointer does not move (same fingerprint: nothing to replace; `unverified_draft`: never current). Making a revision current
     bumps the pair's `version` by one and touches the table; it emits one `lineage_changed` event only when the current decision changed.
     Return `{link_id, revision_id, disposition, rejection_code, current}` (`current` true iff the pointer equals this revision **now**).
     **Idempotent**: this lookup runs first, before any rule: a replayed `idempotency_key`, or an existing model revision of the same pair with
     the same `step_input_id`, returns that stored revision without inserting (a resumed run must not add a revision twice; same as
     `save_model_output`), with `disposition` and `rejection_code` read from the row and `current` recomputed from the pointer at replay time (a human
     edit after the first call makes it false). A key already used for another pair raises `InvalidLineageInput`.
   - **`apply_model_proposals(proposals: list[dict]) -> list[dict]`**: one transaction; applies the proposals sorted by
     `(to_svid, from_svid)` ascending (the §4.3 fixed order; caller order and finishing order never matter), each seeing the graph left by the
     previous one, so a cycle closed by two proposals in one batch is caught on the second. If one proposal raises, the whole batch rolls
     back. Returns the results in the applied order.
   - **Human primitives** (each one transaction, `expected_version` is the pair's `version`, compared with `check_expected_version`; a pair
     that does not exist yet has version 0; event `lineage_changed`; the human revision is `author='human'`, `origin='human'`,
     `disposition='accepted'`, no step fields, no `output_status`): `add_link(research_id, table_id, from_svid, to_svid, relation,
     what_changed, support_type, evidence, note, expected_version, idempotency_key)`; `edit_link(research_id, table_id, link_id, relation,
     what_changed, support_type, evidence, note, based_on_revision_id, expected_version, idempotency_key)`; `remove_link(research_id,
     table_id, link_id, note, based_on_revision_id, expected_version, idempotency_key)`. Rules: for `add_link` and `edit_link` both ends
     are live endpoints (else `InvalidLineageInput`, same endpoint SQL); `remove_link` has **no** endpoint condition (a person can remove a link whose
     source was since excluded; the note requires live ends to create links, not to remove them); different works; an active link needs 1 to 5 evidence items, each a passage of
     the `to` version with a quote that `locate_anchor` places (D130 decision 6: a human cannot add or keep a link without a placed
     quote; the chosen support type is not independent verification); `what_changed` 1 to 500 characters; `relation`/`support_type` from the
     vocabularies; `independent_parallel` needs `source_stated` for humans too (same rule as the model's; judgement, report it); `add_link` is refused with `RevisionConflict` when the pair already has an active current link (use edit) and is
     otherwise allowed over `NULL`, `no_relation`, `insufficient_evidence` and `removed`; `edit_link` and `remove_link` need the current
     revision to be an active link and `based_on_revision_id` to equal the current pointer (else `RevisionConflict`); an edit or add that
     is not `independent_parallel` is cycle-checked over the cycle graph above, with the pair's own existing edge removed first (`InvalidLineageInput`, message names
     the cycle). A human revision becomes current immediately (pointer set after the evidence rows, `version` + 1). `remove_link` writes
     `kind='human_remove'`, `decision='removed'`, and the next model run can never reactivate it (rule 3 above). Replayed
     `idempotency_key` returns the stored revision id; a key used for another pair raises `InvalidLineageInput`.
   - **Reads the next batches need** (small, tested, no view model): `link(table_id, from_svid, to_svid)`, `link_by_id(link_id)`,
     `revisions(link_id)` (oldest first), `evidence(revision_id)`, `active_links(table_id)` (pairs whose current revision is accepted with
     `decision='link'`, with relation, from, to, revision id; **no** endpoint, stale or independent-parallel filtering here, the
     assembly batch L6 does that), `human_decided_pairs(table_id) -> set[tuple[from_svid, to_svid]]` (current revision authored by a
     human; this is the exclusion set L2's `candidates` already takes as a parameter and L5 will pass). Do not add a view model.
4. **Lifecycle hooks (§5, six points)**, each with its own test:
   - `workflow/tables.py::_delete_tables`: first set `lineage_links.current_revision_id = NULL` for the selected tables, then delete evidence,
     revisions, links in that order (the triggers recognise research and table purge). Do this **before** deleting `table_rows`; it must
     work for `purge_table` (table authorization) and for research deletion through `purge_tables` (research authorization). The new tables carry no
     `research_id`, so the general `WHERE research_id = ?` deletion list is **not** touched.
   - `Store.cited_source_versions`: add both ends of `lineage_links` and `lineage_link_evidence.source_version_id` to the UNION.
   - `Store.research_cites_asset`: add a UNION ALL branch for `lineage_link_evidence` joined to `passages.asset_id`, scoped to the research through
     link, table (`evidence_tables.research_id`).
   - `Store.asset_impact`: add `"lineage_links"` (distinct pairs with an evidence row on a passage of the asset). Additive key; if an existing
     test compares the dict exactly, update only that expectation and report it.
   - `TableStore.table_impact`: add `"lineage_links"` (pairs whose current revision is an active link) and `"lineage_human_edits"`
     (human revisions of the table's pairs). Same rule for existing exact comparisons.
   - `TableStore.trash_table`: add `'lineage_links'` to the kinds that block trashing while a run on this table is active (`target_json.$.table_id`).
     Trashing and restoring a table must not rewrite any lineage revision or evidence row (test by comparing the three tables before and after).
5. **Limits of L4** (do not exceed): no node-cell reading, no stale detection of node inputs (the stored `inputs` are opaque to L4; the L5b
   publication transaction rechecks them), no candidate selection, no flow, no worker, no API, no web, no view model, no events beyond
   `lineage_changed`, no `CAPABILITIES`/contract/method change. The pair `version` counts only changes of the current decision.

## Files allowed

`backend/deixis/storage/migrations/00NN_lineage_links.sql` (new, `NN` = next free), `backend/deixis/workflow/lineage/store.py` (new),
`backend/deixis/workflow/tables.py` (only `_delete_tables`, `trash_table`, `table_impact`), `backend/deixis/workflow/store.py` (only
`cited_source_versions`, `research_cites_asset`, `asset_impact`), `tests/test_lineage_store.py` (new), `tests/test_migrations.py`,
`tests/test_backup.py`, `tests/test_corpus_removal.py`, and any other existing test whose exact expectation legitimately changes
(`table_impact`/`asset_impact` keys, a migration-count assertion); say which and why.
`docs/decisions.md` (D134) and this prompt's comment line are written by the orchestrator, not by you.

## Files NOT allowed

Everything else, in particular `backend/deixis/domain/*`, `backend/deixis/workflow/flow.py`, `backend/deixis/workflow/worker.py`,
`backend/deixis/api/*`, `workflow/lineage/{mentions,edges,candidates,baseline}.py`, `contracts/*`, `methods/*`, `apps/web/*`, `scripts/*`,
`docs/product/sw-status.md`, `TODO.md`, `.vscode/`, any existing migration.

## Tests to add (synthetic, no network, no real model; name each so its limit is readable)

`tests/test_migrations.py`:
- `test_the_lineage_migration_keeps_every_run_and_every_row_that_points_at_one`: database at the version before the new migration, one
  run of every kind the old CHECK allows (with `target_json`, `usage_json`, `error_json`, `idempotency_key`, odd statuses), plus rows in
  tables that reference `runs` (a `run_steps` row, a `cell_revisions` row with `run_id`, a `chain_links` row if its columns allow); migrate;
  every run row identical column by column; dependent rows intact; `PRAGMA foreign_key_check` empty and `foreign_keys` ON after;
  `runs_status` index present; the new kind accepted; an unknown kind still refused. Also: the migration applies cleanly on an **empty**
  pre-P6 copy (migrations up to 0058 on a fresh file, nothing inserted), and the vocabularies in `store.py` equal the SQL CHECK lists
  (parse `sqlite_master`).
- Trigger and CHECK tests live in `tests/test_lineage_store.py` (below) against the real migrated schema.

`tests/test_lineage_store.py` (fixture: synthetic research, one table, four to six source versions with passages, using the same helpers
as `test_lineage_columns.py` / `test_report_*`; text marked SYNTHETIC):
- Schema guards: `test_checks_refuse_inconsistent_decisions` (link without relation, non-link with relation, `human_remove` without
  `removed`, model without `step_input_id`, human with `origin='mention'`, rejected without code, accepted with code, human rejected,
  `from = to`); `test_append_only_triggers` (update and delete of revisions and evidence refused; delete allowed only under a research
  or table purge authorization); `test_evidence_must_come_from_the_later_work` (a passage of the `from` version or of a third version is
  refused by the trigger); `test_pointer_guard` (another pair's revision refused; a rejected revision refused; an unverified model draft
  refused; a link revision without evidence refused; NULL always allowed).
- Model proposals: `test_first_accepted_model_decision_fills_the_empty_pointer`; `test_link_then_no_relation_moves_the_pointer_and_drops_the_edge`;
  `test_accepted_model_revision_with_unchanged_fingerprint_is_recorded_but_not_current`; `test_changed_fingerprint_replaces_a_model_current`;
  `test_unverified_draft_is_never_current`; `test_rejected_proposal_keeps_pointer_version_and_old_link` (for each code: `same_work`,
  `endpoint_not_included`, `superseded_by_human`, `stale_input` by scope and by link version, `anchor_not_found`, `cycle`; a first rejected
  proposal leaves the pointer NULL; the rejected revision is stored with its code and the model's fields; no evidence rows); the fixed rule
  order with a proposal that breaks two rules; `test_stored_anchor_is_the_located_source_text_not_the_raw_quote` (exact, normalized and fuzzy
  quotes); `test_same_located_text_twice_is_stored_once`; `test_diamond_is_valid_and_directed_cycle_is_rejected`;
  `test_independent_parallel_adds_no_edge_and_is_not_cycle_checked`; `test_replacing_a_link_removes_its_own_old_edge_for_the_cycle_check`;
  `test_batch_applies_in_fixed_order_whatever_the_input_order` (shuffle the input, compare stored revision order and results);
  `test_batch_catches_a_cycle_closed_by_two_proposals`; `test_batch_is_atomic`; `test_replay_does_not_add_a_second_revision` (idempotency key
  and `step_input_id`); `test_accepted_model_draft_never_becomes_current_by_itself` (a lower-level insert of an accepted model revision
  without going through publication leaves the pointer NULL; only the publication rules move it).
- Humans: `test_human_add_needs_a_placed_quote_from_the_later_work`; `test_human_add_over_none_no_relation_and_removed`; `test_human_add_refused_over_an_active_link`;
  `test_human_edit_and_remove_use_expected_version_and_based_on` (stale version and wrong `based_on` give `RevisionConflict`); `test_human_decision_survives_a_later_model_run`
  (model proposal after human edit or removal is stored rejected with `superseded_by_human`; removal is never reactivated); `test_human_cycle_is_refused`;
  `test_human_decided_pairs_is_the_exclusion_set` (and that it feeds `candidates` as the existing parameter, one assertion, no L2 change);
  `test_human_write_replay_and_foreign_key_reuse`; `test_what_changed_length_and_vocabularies`.
- Cycle graph and contracts: `test_cycle_check_ignores_edges_with_excluded_or_removed_ends`; `test_cycle_check_ignores_named_stale_revisions` (the same proposal is a `cycle` without `stale_revisions` and accepted with it); `test_refreshed_stale_link_counts_again_inside_the_same_batch` (stale `z->a` named, the batch publishes a new `z->a` first and then tries `a->z`: the second is rejected as `cycle`); `test_proposal_shape_errors_raise_and_store_nothing` (empty evidence on a link, fields on a non-link, `independent_parallel` with `analyst_inference`, bad `output_status`); `test_replay_recomputes_current_after_a_human_edit`; `test_model_key_reused_for_another_pair_is_refused`; `test_human_independent_parallel_needs_source_stated`; `test_remove_link_works_when_an_end_is_no_longer_live`.
- Lifecycle, one test per point: `test_purge_table_deletes_lineage_rows_in_order` (a purge authorization for another table does not allow the delete); `test_research_deletion_deletes_lineage_rows` (through the real
  deletion entry point, with runs and step inputs deleted afterwards); `test_cited_source_versions_sees_lineage_ends_and_evidence` (the lineage end branch is isolated from `table_rows`; the evidence branch cannot be isolated because the same-source trigger forces evidence to the link's `to` version, so test the combined lineage protection, that historic and removed decisions still protect, and that another research's table record protects);
  `test_research_cites_asset_sees_lineage_evidence` (plus the existing PDF removal/replacement route, driven through `create_app` and the test client, treats a file cited only by lineage evidence as cited; no API code changes); `test_asset_impact_counts_lineage_links`; `test_table_impact_counts_lineage_links_and_human_edits`;
  `test_trash_table_refuses_while_a_lineage_run_is_active` (insert a `lineage_links` run row directly) and
  `test_trash_and_restore_do_not_rewrite_lineage_history`.
- `tests/test_backup.py`: `test_backup_and_restore_keep_lineage_revisions_evidence_and_human_removals_identical` (use the existing backup/restore
  entry points; compare the three tables row by row before and after).
- `tests/test_corpus_removal.py`: a source cited only by lineage evidence cannot be purged from the corpus; after the link's table is purged it can.

## Checks to run

Focused: `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest tests/test_lineage_store.py tests/test_migrations.py tests/test_backup.py tests/test_corpus_removal.py tests/test_lineage_columns.py -n 0`,
then the full `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest` (one failure is accepted:
`tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`; a test that fails only under parallel load and
passes alone: rerun it alone and say so). Report the counts. If any test outside the allowed list fails, stop and report; do not widen scope.

## Report at the end

Files changed; the migration number; every judgement call (fingerprint inside `inputs_json`, rule order, `independent_parallel`
for humans, endpoint SQL, `table_impact`/`asset_impact` keys, anything the note left open); everything you could not find or verify;
the exact pytest counts.
