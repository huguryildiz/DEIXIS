<!-- PLAN-REVIEW-ROUNDS: gpt-6.1-sol high, r1 (run twice, two answers): hazır değil, 4 + 3 high (purity-test file list, carried failures, pair CAS info missing, historical negatives shown as current, step-level failures hidden) + 8 medium + 1 low, all folded in; r2: hazır değil, 3 high (unchecked currency reported as current, chunk failures and skipped lost, closing rule ignored humans) + 5 medium + 1 low, all folded in; r3: hazır (0 high; 1 medium, 1 low folded in); implementation by gpt-6.1-sol; code review r1 hazır sayıldı (0 high, 1 medium + 2 low fixed by the orchestrator); see D136 -->

# Task: P6 slice 2, batch L6 ("Montaj ve insan düzenleme API'si"), assembly of development lines and the human link-editing API

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-l6` (detached at `90ff783`, main with D135). Read `AGENTS.md`,
`CLAUDE.md`, `docs/decisions.md` D130 to D135 (top), and `docs/product/p6-slice2-chain-of-ideas.md`: §3 (rules), §4.1, §4.3 (human
precedence, publication), §4.4 (field baseline), §4.5 (components), §4.6 (behavior only), §5, §12 "Montaj ve insan düzenleme" and
"Alan tabanı", §19 "L6" and the L1 to L5 entries. The scope below was decided by the main session and binds this prompt; where the
code differs from what this prompt says, report it. Patterns to copy: `workflow/lineage/run.py` (`build_snapshot`, `build_node`,
`stale_link_revisions`, `LineagePlanner._history`), `workflow/lineage/store.py` (`LineageStore`, its human primitives),
`workflow/lineage/baseline.py` and `edges.py` (pure L2 pieces), `workflow/tables.py::TableStore.table_view`, and the L5 routes in
`api/app.py` (`lineage_of`, `table_path`, the `InvalidLineageInput` handler). Test patterns: `tests/test_lineage_plan.py::make_env`,
`attach`, `fill`, `record_publication`; `tests/test_lineage_flow.py` (`queue`, `execute`, `human_add`, the fake adapter).

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted.
Do not invent; report what you could not find. **No real-model calls, no provider calls, no measurement; the fake adapter and
synthetic fixtures only.** Do not touch `../DEIXIS`, `.local/`, `TODO.md`, `.vscode/`, `scripts/local_index.py`,
`docs/product/sw-status.md`, ports 8765 and 8858-8864, or the live data directory. Backend tests need `PYTHONPATH=backend:.` and
`UV_CACHE_DIR=/tmp/deixis-uv-cache`. No method or contract change (so `skill_package_hash` stays `sha256:371fcecb...`), no migration
(if you find one unavoidable, stop and report instead of adding it), no change to the flow (`flow.py`), the worker, the planner's
selection or fingerprints, or `store.py` rules of L4.

## Why

L1 to L5 built role columns, candidates, the contract, durable decisions and the flow that publishes them. Nothing reads the decisions
back as lines yet. L6 adds (1) a pure assembly of the current active links into lines (weakly connected components with roots,
branches and merges, a separate cross-relation list, and the history of stale or out-of-scope links), (2) a read model that tells the
user, for every live row, whether it is placed or why not, (3) the read-time field baseline, and (4) the routes for reading both and
for human add, edit and remove of links. No screen exists (L7). Every list the note names is returned; none is hidden or merged.

## What is and is not in code (checked on 90ff783)

- In code: `LineageStore` with `active_links` (UNFILTERED: it returns every current accepted `link` revision, stale or not, live ends
  or not), `human_decided_pairs`, `link`, `link_by_id`, `ensure_link`, `revisions`, `evidence`, `_current`, `_live`, `add_link`,
  `edit_link`, `remove_link` (all with `stale_revisions` where they check cycles), `LIVE_ENDPOINT_SQL`; `run.py`: `build_snapshot`
  (rows with `LineageWork`, eligibility, node JSON, human pairs), `build_node`, `stale_link_revisions(store, table_id)` (returns
  `{link_id: revision_id}` only, no reasons), `LineagePlanner._history` (private); `baseline.field_baseline(versions)` and its
  dataclasses; `edges.derive_edges`, `unassessed_edges`; `candidates.find_candidates`; the routes `GET .../lineage/plan`,
  `POST .../lineage/runs`, `POST .../lineage/columns`; the `lineage_publication` step output of finished runs
  (`published`, `step_failed`, `failed_pairs`, `targets[{to,target_fp,outcome,no_candidate}]`, `not_sent_budget`, `skipped`).
- Not in code: `assembly.py`, any lineage read route, any baseline route, any human link route, a staleness function that says WHY a
  link is stale, any reader of publication records outside the planner. Check, do not assume.

## Decisions (already taken; do not reopen)

### Reading rules

1. **One synchronous read.** The view and the baseline are built inside one `transaction(store.conn)` read block with no awaits
   (as `build_snapshot` does). No model call, no provider call, no write. `build_snapshot` is reused as it is (do not change its
   output). A route calls it through the same `store_of(request)` the other table routes use.
2. **Table and research are checked first** with `TableStore._table(research_id, table_id)` (404 as the other routes). A trashed or
   foreign table behaves as that function already does.
3. **Live row** = a row in `build_snapshot(...).rows` (L4's `LIVE_ENDPOINT_SQL` rule). **Eligible** = `SnapshotRow.eligible`
   (a current `pdf_page` passage; stored text, never "full text reviewed").

### Staleness with reasons (small refactor in `run.py`, behaviour of L5 unchanged)

4. Add `stale_link_reasons(store, table_id) -> dict[link_id, tuple[revision_id, tuple[str, ...]]]` in `run.py` holding the logic that
   `stale_link_revisions` has today, with the reasons `evidence_not_current` (a cited passage is no longer current), `scope_changed`
   and `node_changed` (model revisions only, exactly the L5 rules). `stale_link_revisions` becomes a thin wrapper returning
   `{link_id: revision_id}` and every L5 test stays green unchanged. The selection revision never makes a link stale (L5 rule).
   **Two policies, kept apart.** (a) ACTIVE links keep exactly the L5 policy: stored EVIDENCE passages must still be current; model
   revisions also compare scope and node snapshots; a change that touches only a mention passage never changes the stale map
   (test it). (b) NON-link model decisions (`no_relation`, `insufficient_evidence`, rejected revisions; item 12a) use a second function
   `decision_currency` that compares scope, node snapshots (from `inputs_json.inputs`) and whether the recorded MENTION passage ids
   are still current passages of the `to` version. Share only the small comparison helpers (scope, node snapshot equality, passage
   currency); do not merge the two policies and do not change (a).
5. **Head change** (note §3, §12): a link end that is a version no longer heading its work (`Store.work_heads(research_id)` does not
   map the end's `work_id` to it) gets the display flag `not_head_ends: ["from"|"to"]` on the link. It is NOT a stale reason and
   changes no component: the decision does not record which version headed the work when it was made, so "head changed after the
   decision" cannot be told from "never the head" without a migration. This knowingly relaxes note §3 and §12 (head change gives
   `stale` or re-evaluation). The orchestrator records the relaxation as an explicit change in D136 and aligns the note; do not
   hide it and do not add a persistent record under the migration ban.

### Assembly (`workflow/lineage/assembly.py`, new, PURE: no database, no flow, no model)

6. Input: plain frozen data only. A link: `link_id, from_svid, to_svid, relation, from_year, to_year, from_position,
   to_position`. Output `Assembly`:
   - **components**: weakly connected components over the given development links (relation != `independent_parallel`; the
     function itself refuses to build edges from `independent_parallel` links even if given them, so they can never join a
     component). Each component: `members` (svids, sorted by (year nulls last, position, svid)), `links` (ordered by
     (from_year nulls last, to_year nulls last, from_position, to_position, link_id)), per node `in_from` and `out_to` lists, and
     `roots` (in-degree 0, out-degree above 0), `branches` (out-degree above 1), `merges` (in-degree above 1), `has_cycle`
     (true when a directed cycle exists; the algorithm must terminate on cyclic input and report it, never loop and never hide the
     component). `id` = first 12 hex of sha256 of the sorted member svids (read-time only, not persistent; say so in the field
     comment). Components are ordered by their first member's (year nulls last, position, svid).
   - The directed diamond `A->B, A->C, B->D, C->D` is one component: root A, branch A, merge D, no cycle.
   - A root's structural signal is exactly (in-degree 0, out-degree N). The words "foundational" and "founder" are never used in any
     key, fixed label or reason code that DEIXIS writes (stored source text is returned unchanged, item 15).
7. `unplaceable_reasons(facts) -> tuple[str, ...]` is also pure: it takes plain per-row facts (below) and returns the reasons of the
   closed list `not_run, no_pdf_text, no_candidate, no_relation, insufficient_evidence, rejected, not_sent_budget, step_failed,
   human_removed, cross_relation_only, stale_only`, in that fixed order, de-duplicated. A reason never means "no continuation
   exists"; there is no such state in this slice. Facts of a row that is NOT placed (placed = endpoint of a current development link
   of a component):
   - `eligible: bool` -> `no_pdf_text` when false.
   - `target_recorded: bool` (some finished lineage run's publication record lists the row as a target; a HISTORICAL fact) ->
     `not_run` when the row is eligible and this is false.
   - `no_candidate: bool` -> `no_candidate`. It is CURRENT, not historical: the row was recorded as a target AND a model-free scan
     of today's passages (item 14) finds no candidate for it. An old record's `no_candidate` flag is never used.
   - over the pairs of this table that have the row as `from` or `to`: `has_no_relation` (a pair whose current revision is an accepted
     model `no_relation`), `has_insufficient_evidence` (same for `insufficient_evidence`), `has_rejected` (a pair whose LATEST
     `model_propose` revision is rejected, any code), `has_human_removed` (a pair whose current revision is a human removal),
     `has_cross_relation` (a current independent_parallel link at the row), `has_history_link` (the row is an end of a stale or
     out-of-scope active link), `has_not_sent_budget`, `has_step_failed` (both from the OPEN step outcomes of item 12).
     A skipped chunk gives no reason of its own (the fallback below covers it; it is listed in `step_outcomes`).
   - **Fallback:** a live unplaced row with no applicable reason gets `not_run`; its meaning is "no recorded decision for this work".
     Test it with a named test so the case is visible.
   A row that has any reason keeps all its applicable reasons (a row may have several).

### The read model (`workflow/lineage/view.py`, new; reads the database, calls `assembly.py`)

8. `LineageView(store).view(research_id, table_id) -> dict`, JSON-safe. Top level keys:
   `table_id`, `table_version` (the table row's `version`), `status`, `nodes`, `pair_decisions`, `components`, `cross_relations`,
   `unplaceable`, `not_accepted`, `unassessed_edges`, `edges_into_unscanned_targets`, `not_sent_budget`, `history`, `counts`.
   - `nodes`: `{source_version_id: {source_version_id, work_id, source_key, title, year, version_label, live, position, eligible,
     access_level}}` for EVERY source version any list refers to, including ends that are no longer live (`live: false`; then
     `position`, `eligible` and `access_level` are null; read them with `Store.source` and `works.source_key`). Components, lists
     and links reference rows by `source_version_id` only; the node data lives here once. `status` counts the live rows only.
   - `pair_decisions`: one entry for EVERY `lineage_links` row of the table (read all of them and each pair's `_current`
     revision): `link_id`, `from`, `to`, `version` (the CAS value), `current_revision_id` (null when none), `decision`
     (`link`, `no_relation`, `insufficient_evidence`, `removed`, or null when no accepted decision is current), `author`
     (`model`, `human` or null), `disposition`. This is what a client reads to add a human link over a pair that already has a
     `no_relation`, `insufficient_evidence` or removed decision. A pair with no row yet needs `expected_version = 0`.
   - `status`: `roles` (`{problem, change, uncertainty}` true when an active role column exists), `live_rows`, `pdf_text_rows`,
     `nodes_complete` (rows whose three cells all have a current revision, state not `missing`), `nodes_partial` (some but not all),
     `missing_cells` (live rows x 3 minus cells with a current revision), `placed_rows`, `unplaced_rows`.
9. **Links.** Take `LineageStore.active_links(table_id)` (unfiltered) and `stale_link_reasons`. For each link row build a link object:
   `link_id`, `version` (the pair's `version`, to be sent back as `expected_version`), `revision_id` (to be sent back as
   `based_on_revision_id`), `from`, `to`, `relation`, `what_changed`, `support_type`, `author` (`model` or `human`),
   `human_edited` (author is human), `note`, `edge_state` (the CURRENT edge state of the pair derived with `edges.derive_edges` from
   the snapshot rows, not the stored one; for a non-live end `null`), `unexpected_no_citation_edge` (current edge state is
   `absent_in_read_list`), `year_order_warning` (the pair's `to` year is earlier than the `from` year when both are known),
   `not_head_ends`, `output_status` and `scope_revision` and `run_id` (from the revision; `null` for human), `created_at`, `evidence`
   (rows from `LineageStore.evidence(revision_id)`: `passage_id`, `anchor_text`, `anchor_match`, plus `physical_page`, `printed_label`
   and passage `kind` read from `passages`), `stale_reasons` (list, possibly empty). Classification:
   - both ends live and no stale reasons: `current`; relation `independent_parallel` -> `cross_relations`, else -> assembly input.
   - both ends live and stale reasons: `history.stale` (kept whole, with `stale_reasons`); never in a component. A stale
     independent_parallel link goes here too.
   - at least one end not live: `history.out_of_scope` with `not_live_ends` (`["from"]`, `["to"]` or both). The note's "stale and
     out-of-scope history are listed apart" is two lists in `history`.
   The decision rows are never rewritten by reading.
10. **Components** come from `assembly.py` over the current development links; the view fills each link object into the component
    (`links` hold link objects, ordering as item 6). `cross_relations` is ordered like component links. Roots, branches, merges are
    lists of svids. A cycle never occurs in stored data by L4's rule, but a stale edge that re-enters is possible, so `has_cycle` is
    reported by the assembly as is.
11. **`unplaceable`**: every live row that is not an endpoint of a current development link, sorted by (year nulls last, position,
    svid), as `{source_version_id, reasons: [...]}` using `unplaceable_reasons`. A row that is an end only of a current cross relation
    is unplaced with `cross_relation_only` (and any other applicable reason).
12. **Step outcomes (reader in `view.py`, do not touch the planner).** Runs of the table are `runs` with `kind = 'lineage_links'` and
    `json_extract(target_json,'$.table_id') = table_id`, any scope revision, ordered `(created_at, rowid)`; a run counts only if its
    `lineage_publication` step succeeded (`Store.existing_step`, `step_output`). `recorded_at` = the step's `finished_at`, else
    `created_at`. Build a top-level `step_outcomes` list, independent of placement, with one item per OPEN outcome:
    `{kind, from, to, key, pair_fp, reason, run_id, scope_revision, recorded_at, current, stale_reasons, unchecked}` where `kind` is
    `failed_pair` (an entry of a record's `failed_pairs`), `unsent_pair` (an entry of a record's `not_sent_budget`; the field there
    is `pair_fingerprint`, map it to `pair_fp`), `step_failed` (an entry of `step_failed`; `from` null, `key` set) or `skipped` (an
    entry of `skipped`; `from` null, `key` set); fields that do not apply are null.
    - **Chaining across runs.** Per pair keep the LAST `failed_pairs` entry and the LAST `not_sent_budget` entry over all counted runs,
      each with its own record's `recorded_at` and `run_id`: a later run carries earlier failures in its plan (`failed_unchanged`) and
      may publish `failed_pairs = []` (the L5 test `test_retry_failed_reopens_carried_failures_after_remaining_pairs_settle`), so a
      carried failure keeps its ORIGINAL `recorded_at`. Per chunk keep the last `step_failed` and `skipped` entry per (`run_id`, `key`).
    - **Closing.** A pair-level entry is OPEN until the pair has a `model_propose` revision created after `recorded_at`, or the
      pair's CURRENT revision is a human one (human add, edit or remove; the history record stays in the run). A chunk-level entry
      is OPEN while at least one of the chunk's pairs (the `from` list of the chunk with that `key` in the run's frozen plan,
      `Store.run(run_id)["target"]["chunks"]`) is not closed in the same way; an unrelated pair's assessment never closes it.
      Only open entries are listed; nothing else is dropped, because the runs and revisions themselves are untouched.
    - **Per-row flags.** `has_step_failed`: the row is `to` or `from` of an open `failed_pair` or of an open `step_failed` chunk
      (the chunk's `to` and its planned `from` list). `has_not_sent_budget`: the row is `to` or `from` of an open `unsent_pair`.
    - `target_recorded` = some counted run's publication `targets` lists the row as `to`. `last_run` of a row = the latest such run
      as `{run_id, scope_revision, recorded_at}`.
    - `scanned_targets` = the rows with `target_recorded` that are live and eligible now (a scan is model-free and is redone, item 14).
    - **12a. Currency.** Historical negative facts are never presented as current without a check. `current` is `true`, `false` or
      `null` (unknown), with `stale_reasons` (`scope_changed`, `node_changed`, `passage_changed`) and `unchecked` (names of the checks
      that could not be made). Rules: (i) a negative or rejected REVISION (`no_relation`, `insufficient_evidence`, `rejected`): use
      `decision_currency` of item 4(b); `unchecked` lists `passage_text`. (ii) a `failed_pair` or `step_failed` whose chunk step
      output holds a `send_record` (`Store.existing_step(run_id, key)["output"]["send_record"]`: node snapshots, mention ids and
      shown-passage `text_sha256`): compare scope, the node snapshots and the passage digests with today's. A `failed_pairs` item has
      no `key`: find its chunk in the same run's frozen plan by `(from, to)` (`target.chunks[].to`, `.from`), read that chunk step,
      and confirm the record's pair by `pair_fp` before comparing. A blocked send may store a `blocked_send_record` (see the L5 test
      `test_message_too_large_failure_keeps_a_record`); use whichever real record exists. (iii) an `unsent_pair`
      or an entry for which no real send record exists (this policy then treats currency as unknown): `current = false` with `scope_changed` when the
      run's scope differs, else `null` with `unchecked: ["node_snapshots", "passages"]`. Never answer `true` for a check that was not
      made. The row keeps its reason either way; `details` carries the same fields.
    - **`unplaceable[].details`** items: `{reason, from, to, link_id, revision_id, run_id, scope_revision, recorded_at, current,
      stale_reasons, unchecked}`; `link_id` and `revision_id` are null for an entry with no `lineage_links` row (a pair never
      decided); `run_id`, `scope_revision` and `recorded_at` are null where not stored. The exact JSON and the TypeScript types in
      `api.ts` mirror each other and the key list of item 8; the `unplaceable` item is `{source_version_id, reasons, details, last_run}`.

13. **`not_accepted`**: for every pair that has at least one rejected `model_propose` revision, its LATEST REJECTED revision (a later
    accepted model revision does not remove it), one entry each, with `superseded` (true when a later accepted revision of any
    author exists on the pair): `link_id`, `from`, `to`,
    `revision_id`, `rejection_code`, the proposed `decision`, `relation`, `what_changed`, `support_type`, `note`, `run_id`,
    `created_at`, `pair_state` (what the pair's CURRENT decision is: `none`, `link`, `no_relation`, `insufficient_evidence`,
    `removed`, and `author`). Never hidden because the pair was later decided; `superseded` and the pair state say so. Sorted by (`to` year, `to`
    position, `from` position, link_id).
14. **One current scan.** Recompute at read time over the scanned targets only: load current passages for just those targets
    (`Store.passages_for`), build `LineageWork` objects, and run ONE `find_candidates(works, targets=scanned,
    excluded_pairs=frozenset())` (no exclusion, so a target whose only candidates are human pairs is not called "no candidate").
    From it: `no_candidate` (item 7) = scanned targets that appear in its `no_candidate_targets`; and `unassessed_edges` =
    `edges.unassessed_edges(edges, candidate_pairs, scanned, snapshot.human_pairs)`. **`unassessed_edges`** (a `present` citation
    edge into a SCANNED target with no found mention): exclude a pair that has a current active link. Entries: `from`, `to`. **`edges_into_unscanned_targets`** (the L2 leftover): `present` edges
    (`derive_edges` over all live rows) whose `to` is not scanned, excluding human pairs and pairs with a current active link:
    `from`, `to`, and `to_reason` (`no_pdf_text` or `not_run`). It is a separate list: for those targets no mention scan has run, so
    "mention not found" is not claimed. `unexpected_no_citation_edge` appears only on links, as item 9.
15. The top-level `not_sent_budget` and `failed_pairs` lists are the `unsent_pair` and `failed_pair` items of `step_outcomes` (same
    shape); `step_outcomes` also holds the chunk-level items, so a partial success hides no failure. The top-level keys are exactly:
    `table_id, table_version, status, nodes, pair_decisions, components, cross_relations, unplaceable, not_accepted,
    unassessed_edges, edges_into_unscanned_targets, step_outcomes, not_sent_budget, failed_pairs, history, counts` (this replaces
    the shorter key list of item 8). `counts`: link counts per list (`components`, `current_links`, `cross_relations`, `history_stale`,
    `history_out_of_scope`, `unplaceable` with a per-reason map, `not_accepted`, `unassessed_edges`, `edges_into_unscanned_targets`,
    `not_sent_budget`, `failed_pairs`, `step_outcomes`, `human_edited_links`) and `edge_states` (`present`, `absent_in_read_list`, `unresolved`,
    `not_read`: `edges.edge_counts` over the CURRENT live ordered pairs of different works, note §4.1; kept apart from link counts
    and described in a field comment as a count of citation-list states, not of links). No score, no ranking, no word "foundational" or "founder", no statement of originality. The forbidden words (`foundational`, `founder`, `novel`, `original`, "continuation") are forbidden in
    keys, fixed labels and reason codes that DEIXIS writes, never in stored source text: a title, quote, `what_changed` or human note
    is returned byte for byte even if it contains such a word (tested).

### The field baseline (`LineageView.baseline(research_id, table_id)`)

16. Versions = the live rows of the table. Build `baseline.BaselineVersion` per row from the database: `is_head`
    (`Store.work_heads(research_id)` maps the row's work to it), `has_active_asset` (a `source_assets` row with `removed_at IS NULL`),
    `created_at` (= `corpus_memberships.created_at` of the row's source version in this research, NOT `source_versions.created_at`; D132's
    "membership creation time"), `cited_by_count`, `cited_by_count_at`, `publication_type`, `references_read`, `referenced_ids`
    (`record_references`), `openalex_ids` (`identifier_mappings`, scheme `openalex`). Call `field_baseline`.
17. Output: `table_id`, `scope` (the fixed text "Among the works this research included"), `representatives` (as the dataclass, with
    `versions_considered`), and for each of `most_cited_in_corpus` and `review_in_corpus`: `total`, `shown` (first 5), `entries` (all,
    for "show all"); each entry: `work_id`, `source_version_id`, `source_key`, `title`, `year`, `cited_by_count`, `cited_by_count_at`,
    `publication_type`, `cited_by_included_works` (`count` which may be null, `other_works`, `lists_read`, `target_resolved`),
    plus `unknown_count_works`, and the two fixed notes: for review `baseline.REVIEW_NOTE`; for most cited "Counts come from the
    provider and date shown; works without a stored count are not ranked and not counted as zero." A null included-citation count is
    never rendered as zero. No model, search or provider call. The baseline is computed, never stored.

### Human editing routes (`api/app.py`)

18. Routes (all under `table_path`; mutations ride the existing CSRF check):
    - `GET .../lineage` -> the view. `GET .../lineage/baseline` -> the baseline.
    - `POST .../lineage/links` (201): body `from_source_version_id`, `to_source_version_id`, `relation` (the six values),
      `what_changed` (1 to 500 chars), `support_type`, `evidence` (1 to 5 items of `{passage_id, quote}`), `note` (optional, at most
      2000 chars), `expected_version` (int, 0 for a pair that has no row yet; otherwise the pair's `version`). Calls
      `LineageStore.add_link(..., idempotency_key, stale_revisions=stale_link_revisions(...))`.
    - `PUT .../lineage/links/{link_id}` (200): body `relation`, `what_changed`, `support_type`, `evidence`, `note`,
      `based_on_revision_id`, `expected_version`. Calls `edit_link`.
    - `DELETE .../lineage/links/{link_id}` (200): query `expected_version`, `based_on_revision_id`, optional `note`. Calls `remove_link`.
    - All three accept `Idempotency-Key`. Each returns the fresh `view`. A link id of another table or research is 404 (the store
      already does this). A stale link can be edited or removed by a human (L4 rules). Errors: wrong `expected_version` or a
      `based_on_revision_id` that is not the current active revision -> 409 (existing `RevisionConflict` handler); a quote that is
      not located in a passage of the LATER work, a passage of another work, an unknown passage, a cycle, a non-live end, the same
      work, `independent_parallel` without `source_stated`, an evidence list that is empty or over 5 -> 422 (existing
      `InvalidLineageInput` handler or request validation). Do not widen what L4 accepts; the routes only pass through and map errors. The error matrix, kept as L4 has it: re-adding over an
      ACTIVE link -> 409 ("use edit"); edit or remove of a pair with no active current link, or with another revision than the current
      one -> 409; remove has NO live-end condition and no cycle check (do not add one); wrong `expected_version` -> 409.
    - After a human write the next preview and run do not re-ask the pair (L4's `human_decided_pairs`); this is tested (item 21).
19. Add and edit call `stale_link_revisions` at request time and pass its result as `stale_revisions` to the store, as L4 intends.
    `remove_link` takes no such parameter (check the signature) and gets none.
20. Route registration: keep the plan and run routes untouched; add the new ones next to them.

### Web (`apps/web/src/api.ts`, types only)

Add the TypeScript types of the view, link object, baseline and the three request bodies, exported, with no UI use and no fetch
functions (L7 owns both). Keep the file's style. Then `cd apps/web && npm run build && npm run lint` (17 warnings baseline, no new
ones). The orchestrator runs Playwright. If the worktree has no `node_modules`, ask nothing: report it and continue; the orchestrator
links it.

## Limits of L6 (do not exceed)

No screen, no fetch function, no copy (EN or TR), no fixture-server scenario, no UI label for the run kind (L7). No new run kind, no
flow, worker, planner or contract change. No new sort of "strength", "importance", "novelty" or "foundational" anywhere. No claim
that a stored quote proves a relation (L4 limit stands). Head change is a display flag only (item 5).

## Files allowed

`backend/deixis/workflow/lineage/assembly.py` (new), `backend/deixis/workflow/lineage/view.py` (new),
`backend/deixis/workflow/lineage/run.py` (only item 4), `backend/deixis/api/app.py` (models and routes of item 18 only),
`apps/web/src/api.ts` (types only), `tests/test_lineage_assembly.py` (new), `tests/test_lineage_api.py` (new),
`tests/test_lineage_view.py` (new, if you want the read model apart from the routes), `tests/test_lineage_mentions.py` ONLY for
`test_package_imports_no_database_provider_or_model`: `assembly` joins the pure module set (`{"__init__","mentions","edges","candidates",
"baseline","assembly"}`, still under the same import allow-list), and `view` is excluded with `store` and `run` as a database-reading
module; keep every forbidden-import check; existing lineage tests otherwise only to extend a helper import. `docs/` is written by the orchestrator, not by you.

## Files NOT allowed

`flow.py`, `worker.py`, `store.py` (both), `tables.py`, `contracts.py`, `methods/`, `contracts/`, migrations, `tests/acceptance/`,
`apps/web` other than `api.ts`, everything in the "do not touch" list above.

## Tests to add (synthetic, no network, no real model; name each so its limit is readable)

`tests/test_lineage_assembly.py` (pure, no database):
- `test_directed_diamond_is_one_component_with_root_branch_and_merge`, `test_chain_branch_and_merge_roles`,
  `test_two_separate_components_are_ordered_deterministically`, `test_input_order_does_not_change_the_output`,
  `test_independent_parallel_never_builds_a_component_or_a_role` (given such a link the function ignores it for edges and
  components), `test_cyclic_input_terminates_and_reports_has_cycle`, `test_unknown_years_sort_last_with_position_and_id_ties`,
  `test_component_id_depends_only_on_members`, `test_a_single_node_has_no_component`.
- `test_every_unplaceable_reason_alone` (parametrised over the eleven reasons), `test_reasons_are_ordered_and_deduplicated`,
  `test_a_row_with_several_reasons_keeps_all`, `test_fallback_not_run_means_no_recorded_decision`, `test_no_reason_means_no_continuation`
  (no reason code or key claims a line ended; "continuation", "foundational", "founder" are absent from every key, fixed label and
  reason code).

`tests/test_lineage_view.py` / `tests/test_lineage_api.py` (real database through `make_env`, the real routes through `create_app`
with CSRF as the plan tests do; the fake adapter where a run is needed):
- Components and lists: `test_view_places_links_into_components_with_year_order` (use `LineageStore.apply_model_proposal` and human
  primitives to build synthetic decisions), `test_diamond_from_stored_links`, `test_cross_relation_is_listed_apart_and_builds_no_component`,
  `test_stale_link_stays_out_of_the_component_and_in_history_with_its_reasons` for each of: a cell revision changed, a column
  instruction edited, scope revised, a cited PDF removed, a cited PDF replaced; a human link is NOT stale after a node edit but IS
  after its evidence passage stops being current; `test_selection_change_makes_the_link_out_of_scope_not_stale` (an end excluded or
  its table row removed -> `history.out_of_scope` with `not_live_ends`); `test_head_change_is_a_flag_not_a_stale_reason`;
  `test_stale_edge_is_excluded_from_assembly_but_the_decision_row_is_unchanged` (the stored revision and pointer are identical
  before and after the read).
- Every unplaceable reason from real state: `not_run`, `no_pdf_text`, `no_candidate`, `no_relation`, `insufficient_evidence`,
  `rejected` (each rejection code at least once through L4), `not_sent_budget`, `step_failed`, `human_removed`,
  `cross_relation_only`, `stale_only` (use REAL runs with the fake adapter for every failure, unsent or skipped case so the stored publication record has its real shape; `record_publication` only for facts that do not read a publication record); an eligible row with
  no record uses the fallback; a row appears once with several reasons; a placed row is absent.
- `test_not_accepted_lists_the_latest_rejected_revision_and_the_pair_state` (a later human decision does not hide it; a rejection
  followed by an accepted model revision stays listed with `superseded` true),
  `test_unassessed_edge_present_edge_without_mention_in_a_scanned_target`,
  `test_present_edge_into_an_unscanned_target_is_listed_apart` (no mention claim; reason `no_pdf_text` or `not_run`),
  `test_unexpected_no_citation_edge_only_when_absent_in_read_list` (the four edge states on links),
  `test_not_sent_budget_list_drops_a_pair_after_a_later_revision`.
- `test_view_and_baseline_reads_execute_no_write_statement` (a SQLite authorizer or trace on the connection rejects every INSERT,
  UPDATE, DELETE or DDL during both reads; pair rows, revisions, pointers and events are unchanged; the plan tests' `NeverAdapter`
  makes any model or provider call fail), `test_view_is_one_synchronous_read` (no await in the read path; say how you tested it),
  `test_forbidden_words_are_absent_from_deixis_text_but_source_text_is_returned_unchanged` (a stored title, a quote, `what_changed`
  and a human note containing "foundational" come back byte for byte; no DEIXIS key, label or reason code uses the words).
- Carried failures and currency: `test_a_carried_failure_stays_an_open_pair_failure_when_the_later_run_publishes_empty_failed_pairs`
  (failure, a second run that carries it with `failed_pairs = []`, the view still lists it with the ORIGINAL `recorded_at`; a
  successful retry afterwards closes it, and the old-input-A-failure, retry-at-A, change-to-B, return-to-A case does not resurrect
  it), `test_a_pair_failure_is_listed_whether_or_not_its_row_is_placed`,
  `test_no_candidate_is_current_not_historical` (a target recorded `no_candidate` whose PDF is replaced by one that mentions an
  earlier work no longer shows `no_candidate`; a target whose only candidates are human pairs is not `no_candidate`),
  `test_old_negative_decisions_say_they_are_not_current` (a `no_relation`, an `insufficient_evidence` and a rejected revision made at
  an earlier scope revision, an earlier node snapshot, and a mention passage replaced by a new extraction: `details[].current` is
  false with the matching `stale_reasons`; the reason itself is still returned), `test_nodes_include_non_live_ends_with_live_false`
  (a `history.out_of_scope` link and a `not_accepted` entry with an excluded end resolve in `nodes`).
- Step outcomes: `test_partial_success_keeps_the_failed_chunk_visible_though_its_row_is_placed`, `test_message_too_large_and_skipped_chunks_appear_in_step_outcomes`,
  `test_a_human_decision_closes_an_open_failure_but_the_run_record_is_kept`, `test_an_unrelated_pair_assessment_does_not_close_a_chunk_failure`,
  `test_unchecked_inputs_never_report_current_true` (scope unchanged but a PDF extraction or a node changed: a send-record failure says
  `current` false with the reason; an unsent entry says `current` null with `unchecked`),
  `test_a_mention_only_change_does_not_change_stale_link_revisions` (L5 policy intact) and
  `test_combined_stale_reasons_and_non_live_ends_equal_the_old_stale_map`.
- Pair decisions and CAS: `test_pair_decisions_list_every_pair_with_its_version` and, for each of a `no_relation`, an
  `insufficient_evidence` and a human-removed pair, `test_get_then_post_adds_a_human_link_with_the_read_version`, plus the brand-new
  pair with `expected_version = 0`; a stale `version` read from an earlier GET -> 409.
- Extraction and refresh: `test_extraction_change_marks_a_link_stale_and_a_refreshed_revision_is_not_excluded_by_an_old_stale_map`
  (the stale map is recomputed on every request; after a model link is replaced by a refreshed revision the link is current again).
  The PDF-protection route behaviour of note §12 ("only lineage evidence opens the PDF") is covered at store level by the L4 test
  `tests/test_lineage_store.py::test_research_cites_asset_sees_lineage_evidence`; add `test_evidence_created_by_the_post_route_protects_the_pdf`
  (the same removal route call, with the human link created through the new POST route).
- `stale_link_reasons`: each reason alone; `stale_link_revisions` returns the same ids as before (the L5 tests still pass).
- Baseline: `test_baseline_representative_uses_membership_creation_time_not_version_creation_time` (the two orders differ),
  `test_edge_state_counts_are_kept_apart_from_link_counts`, `test_baseline_uses_stored_counts_and_ranks_only_known_counts`, `test_unknown_count_is_not_zero_and_is_counted`,
  `test_baseline_counts_distinct_works_not_versions_and_excludes_the_target`, `test_baseline_representative_is_shown_and_not_filled_from_another_version`,
  `test_review_note_says_registered_type_and_no_foundational_word`, `test_included_citation_count_is_null_not_zero_without_read_lists`,
  `test_first_five_shown_and_all_returned`, `test_baseline_makes_no_model_or_search_call`.
- Routes: `test_get_lineage_and_baseline_404_for_missing_table_and_foreign_research`,
  `test_human_add_needs_a_placed_quote_in_a_passage_of_the_later_work` (a passage of the earlier work -> 422, an unplaced quote -> 422,
  a correct one -> 201 and the link appears in a component), `test_human_add_expected_version_zero_for_a_new_pair_and_409_for_a_wrong_one`,
  `test_human_edit_and_remove_use_expected_version_and_based_on_revision` (409 both ways), `test_human_remove_is_listed_as_human_removed_and_never_reactivated_by_a_run`,
  `test_remove_has_no_live_end_or_cycle_condition_and_re_adding_over_an_active_link_is_409` (also: edit or remove of a pair with
  no active link is 409), `test_human_routes_require_csrf`, `test_idempotency_key_replays_the_same_write`, `test_cycle_is_422_and_a_stale_edge_does_not_block_a_closing_human_link`,
  `test_edit_of_a_stale_link_is_allowed_and_makes_it_current_again_when_the_evidence_is_current`, request validation errors (relation
  vocabulary, `what_changed` length, evidence count) are 422.
- **Closing the L5b-dependent item:** `test_a_model_run_does_not_overwrite_a_human_decision` end to end: a human add and a human
  remove (two pairs) through the ROUTES, then a real lineage run through `ResearchFlow.execute` with the fake adapter that proposes
  `link` and `no_relation` for those pairs if it is asked; the human pairs are not candidates (no call for them), a pair that the
  adapter is asked about in a run started BEFORE the human write (in flight) is recorded `superseded_by_human`, and the view after the
  run still shows the human link, the human removal (`human_removed`) and the human revision as current. The model never changes a
  human-authored current revision.
- Web types: no test; `npm run build` and lint only.

## Checks to run

Focused: `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest tests/test_lineage_assembly.py tests/test_lineage_view.py
tests/test_lineage_api.py tests/test_lineage_plan.py tests/test_lineage_flow.py tests/test_lineage_store.py -n 0`. Then the full
`PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest` (one failure accepted:
`tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`; a test that fails only under parallel load
and passes alone: rerun it alone and say so). If your sandbox blocks loopback or process access and a failure looks environmental, say
so; do not "fix" it. Web: `cd apps/web && npm run build && npm run lint`.

## Report at the end

Files changed; every judgement call (the unplaceable fallback, the head flag, what "scanned" means, latest-record rules, the edge
state shown, the route shapes, anything the note left open); what is deferred to L7; everything you could not find or verify; the exact
pytest counts (focused and full) and the web build and lint results.
