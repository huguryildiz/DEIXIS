<!-- PLAN-REVIEW-ROUNDS: gpt-6.1-sol high, r1: hazır değil, 2 high (payload references lost across purge filters and passages.payload_ref; upsert_provider_source is not full corpus isolation) + 6 medium; r2: hazır değil, 1 high (kill_search_query_records missing from purge order) + 4 medium, the isolation high downgraded to a documented limit; r3: düzeltmeyle hazır, 0 high, 2 medium (replay compares record content; events in fresh-source test), all folded in; implementation by gpt-6.1-sol; see D144 -->

# Task: P6 slice 3, batch K1, durable storage and pure computations for claim candidates and kill-search

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-k1` (detached at `9ae16fb`, main with D143). Read `AGENTS.md`,
`CLAUDE.md`, `docs/decisions.md` D143 (top) and D134, and `docs/product/p6-slice3-kill-search.md`: §0 (what the old draft got wrong),
§1, §2 steps 0 to 5, §4, §5 (status derivation, all of it), §6, §7 (all of it), §9 items 1 and 5, §11, §12 "Modelsiz depolama ve saf
hesap (K1)", §17 "K1". The note is in Turkish; this prompt is the binding English scope. Where the code differs from what this prompt says,
report it. Patterns to copy: `docs/product/p6-slice2-l4-prompt.md` (this batch is its sibling: a `runs` rebuild, append-only tables with
purge authorizations, a store class, lifecycle hooks, tests), migration `0059_lineage_links.sql` (the latest `runs` rebuild, the
`..._no_conflicting_insert` triggers, `WITHOUT ROWID` tables, purge-authorization delete triggers, pointer guards),
`workflow/lineage/store.py` (`LineageStore`: `transaction()`, `ensure_*`, version bump with a one-millisecond `created_at` bump so
insertion order survives, `InvalidLineageInput`, `check_expected_version`), `tests/test_lineage_store.py` (the `make_library` fixture and
helpers) and the 0059 test in `tests/test_migrations.py`.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted.
Do not invent; report what you could not find. **No real-model calls, no provider calls, no network, no measurement.** Do not touch
`../DEIXIS`, `../DEIXIS-s2fix` (another batch runs there and edits lineage code, `domain/contracts.py` and the lineage parts of
`workflow/store.py`; it adds no migration), `.local/`, `TODO.md`, `.vscode/`, `scripts/local_index.py`, `docs/product/sw-status.md`, ports
8765 and 8858-8864, or the live data directory. Backend tests need `PYTHONPATH=backend:.` and `UV_CACHE_DIR=/tmp/deixis-uv-cache`. No web
work, no API work, no flow work, no method or contract change (`skill_package_hash` stays `sha256:371fcecb...`). Keep edits in the shared
files `workflow/store.py` and `storage/backup.py` small and local so the rebase over the other batch is trivial.

## Why

Slice 3 lets the owner open a one-claim candidate card from a report gap or from their own sentence and run a bounded kill-search for
prior art on that claim (D143). K1 builds only the durable layer and the pure code that derives a status. Nothing calls it from the
flow yet (K3) and no route exposes it. K1 stores *applied* results handed to it; it runs no model, builds no provider request, reads no
node or report view model and writes nothing into `report_gaps`.

## What is and is not in code (checked on 9ae16fb)

- In code: migrations up to `0059_lineage_links.sql` (the last `runs` rebuild, kinds up to `lineage_links`; `stage` already allows
  `candidate`); `Store.upsert_provider_source(provider, record, payload_path) -> (svid, created)`; `Store.purge_research`,
  `purge_sources`, `cited_source_versions`, `research_cites_asset`, `asset_impact`; `storage/backup.py::_referenced_files`;
  `providers.query_compiler.compile_block_queries` and `providers.query_rules.query_issues`; `workflow/vocabulary.TERM_FIELDS`;
  `report_gaps` (0035) with `domain.contracts.GAP_KINDS` (three kinds); `workflow/lineage/*` (do not touch).
- Not in code: any candidate table, trigger, `claim_decomposition` or `kill_search` run kind, `workflow/candidates/`. Check, do not assume.
- `create_run`'s stage mapping (`workflow/store.py`, stage `extraction` for unknown kinds) and `flow.py` dispatch are K3's. Do **not**
  add them; list "create_run stage mapping for the two new kinds" as an open item.

## Decisions (already taken; do not reopen)

1. **One migration**, the next number after the highest in `backend/deixis/storage/migrations/` (expected `0060_candidates.sql`; check),
   first line `-- deixis:foreign-keys-off`. Order: (a) rebuild `runs` exactly as `0059` does (copy every column and the stage list from
   the current schema, same `runs_status` index) with `'claim_decomposition'` and `'kill_search'` added to the `kind` CHECK; update the
   `target_json` comment (candidate runs carry `{"candidate_id", "candidate_version_id", ...}`; K3 defines the rest); (b) the tables
   below; (c) triggers. Existing migrations are never edited. `PRAGMA foreign_key_check` must be empty after the rebuild and
   `foreign_keys` ON after the migration runner finishes.
2. **Tables** (§7 of the note is the intent; the SQL is yours but the properties below are fixed). Explicit primary keys; use
   `WITHOUT ROWID` plus the 0059 `..._no_conflicting_insert` triggers for the tables whose rows must never be replaced
   (`research_candidates`, `candidate_versions`, `claim_elements`, `claim_matrix_cells`, `claim_matrix_evidence`,
   `candidate_status_overrides`, `kill_searches`, `kill_search_queries`, `kill_search_query_records`, `kill_search_hits`). Id prefixes: `rcd_`, `clv_`, `ele_`,
   `kls_`, `cmx_`. Columns as in §7, with these fixes:
   - `research_candidates`: `origin` in (`report_gap`, `owner_text`); `origin_gap_row_id`, `origin_report_id` plain text, **no FK** to
     `report_gaps`, `reports` or any table/cell row; `gap_kind` plain text checked in code against `GAP_KINDS` (like 0035, no SQL
     CHECK); `origin_basis_json`, `origin_basis_view_json`, `origin_provenance_json`, `origin_fingerprint`; CHECKs: `report_gap` rows
     need report id, gap row id, gap kind and fingerprint, `owner_text` rows have those four NULL; a partial UNIQUE index
     `(research_id, origin_gap_row_id, origin_fingerprint) WHERE origin_gap_row_id IS NOT NULL`; `current_version INTEGER NOT NULL
     DEFAULT 0`; `trashed_at`; FK `research_id -> researches`. Identity/origin columns cannot be updated (trigger); `current_version`
     may only be set to a version that exists for the same candidate and only upward by one.
   - `candidate_versions` and `claim_elements`: append-only (no update ever; delete only under a research purge authorization of the
     owning candidate's research). `UNIQUE (candidate_id, version)`, `UNIQUE (candidate_version_id, position)`; `origin` in
     (`model_decomposition`, `human_edit`); `step_input_id` references `step_inputs(id)` and is required exactly when `origin =
     'model_decomposition'`; element `kind` in (`mechanism`, `condition`, `outcome`, `parameter`); 2 to 6 elements per version is
     enforced by the store (a trigger cannot count children inserted later), the CHECK on `position` is `>= 1`.
   - `kill_searches`: FK `candidate_version_id -> candidate_versions`, `run_id -> runs` UNIQUE; insert guard: the run's `kind` is
     `kill_search` and its `research_id` equals the candidate's `research_id`; frozen columns (`candidate_version_id`, `run_id`,
     `query_block_json`, `rendered_queries_json`, `skipped_terms_json`, `selection_json`) cannot be updated; `outcome` in (`running`,
     `paused`, `completed`, `failed`, `stopped`), updatable only in the directions `running <-> paused`, `running|paused ->
     completed|failed|stopped`, and a terminal outcome never changes; counts `found`, `kept`, `rank_cut`, `duplicates` (non-negative,
     `kept <= 8` by CHECK), updatable only while not terminal.
   - `kill_search_queries`: FK to `kill_searches`; `UNIQUE (kill_search_id, position)`; `status` in (`succeeded`, `failed`,
     `outcome_unknown`); `provider`, `query_text`, `record_count`, `error_code`, `raw_payload_path`, `payload_sha256` (both NULL
     allowed: a failed query may have no file), `step_id`; immutable.
   - `kill_search_query_records` (new, not in §7; own-judgement, report it): one row per record a successful query returned:
     `(kill_search_id, position, rank, provider, source_version_id, work_id)`, PK `(kill_search_id, position, rank)`, FKs to
     `kill_searches` and `source_versions`; immutable, deleted only under the research purge authorization. It makes the
     merge input durable and replayable (K3 reads it back), and it is what `purge_research` reads to find every source a kill-search
     created even when the run died before any hit was written.
   - `kill_search_hits`: `UNIQUE (kill_search_id, source_version_id)`, FKs to `kill_searches` and `source_versions`; `work_id` copied
     (plain text, from `source_versions.work_id`), `rank_key` integer (the merged order, 1-based), `kept` 0/1, `cut_reason` (`rank_cut`
     or NULL, required exactly when `kept = 0`), `reading_depth` in (`abstract`, `stored_passages`, `metadata_only`) required when
     kept, `assessment_state` in (`pending`, `assessed`, `insufficient_access`, `not_assessed_budget`), required when kept and NULL
     when not; `work_relevance` in (`unrelated`, `related`, `uncertain`), `states_whole_claim` 0/1, `note`, `step_input_id` all NULL
     unless `assessment_state = 'assessed'` and then `work_relevance`, `states_whole_claim` and `step_input_id` are NOT NULL (CHECKs).
     Update trigger: identity columns immutable; `assessment_state` may only move from `pending` to one of the three other values and
     a non-pending state never changes; assessment columns may be set only in that same update.
   - `claim_matrix_cells`: `UNIQUE (kill_search_id, element_id, source_version_id)`; `relation` in (`explicit_support`,
     `reasoned_inference`, `partial_match`, `no_match_in_supplied_text`, `uncertain`); `condition_alignment` in (`aligned`,
     `different_conditions`, `unclear`) or NULL with the CHECK of §5 (required for the three support relations, NULL for
     `no_match_in_supplied_text`, optional for `uncertain`); append-only. Insert trigger (§7 integrity checks, choose triggers, not the
     store alone): the element belongs to the search's candidate version; the hit `(kill_search_id, source_version_id)` exists, is kept
     and its `assessment_state` is `assessed`.
   - `claim_matrix_evidence`: as §7 (`element_id` NULL means a whole-claim quote and then `matrix_cell_id` is NULL; otherwise
     `matrix_cell_id` is required); `evidence_kind` in (`abstract`, `passage`), `passage_id` required exactly for `passage` and
     must belong to the same `source_version_id` (trigger, like `lineage_link_evidence_same_source`); `quote` non-empty; append-only. Insert
     trigger: the `(kill_search_id, source_version_id, element_id)` of an element quote equal its cell's; a whole-claim quote needs a
     hit with `states_whole_claim = 1`, `assessed`, kept.
   - `candidate_status_overrides`: `candidate_version_id -> candidate_versions`, `status` in (`not_run`, `undecided`, `narrowed`,
     `closed`, `open`), `reason` with `CHECK (length(trim(reason)) > 0)`, `created_at`; append-only.
   - **Append-only delete rule** for every append-only table and for `kill_searches`, `kill_search_queries`, `kill_search_query_records`, `kill_search_hits`: a
     delete is refused unless the owning candidate's research is in `research_purge_authorizations` (join through candidate_version ->
     candidate -> research_id). Do not authorize through `table_purge_authorizations`.
   - Indexes you need for the reads below; none else.
3. **Pure modules**, no database, no clock, no I/O, no provider or model import (a purity test like L2's: parse the module imports; only
   stdlib, `deixis.providers.query_compiler`/`query_rules` (terms only, see below), `deixis.workflow.criterion.norm`,
   `deixis.workflow.vocabulary.TERM_FIELDS` and `deixis.domain.*` constants are allowed).
   - `workflow/candidates/status.py`: `derive_status(search, queries, hits, cells, element_ids) -> dict`. Inputs are plain dicts/lists
     (the store builds them). `search` is `None` or `{outcome, found, kept, rank_cut, duplicates}`; `queries` have `status`; `hits` have
     `source_version_id, kept, assessment_state, work_relevance, states_whole_claim, reading_depth, whole_claim_evidence_count`;
     `cells` have `source_version_id, element_id, relation, condition_alignment`. Output: `{"status", "reason", "reasons": [..],
     "facts": {found, kept, assessed, unread, rank_cut, duplicates, queries_total, queries_succeeded, queries_failed,
     queries_unknown, reading_depths: {abstract, stored_passages, metadata_only}}, "warnings": [..]}`; no prose (K4 renders text);
     `unread` = `rank_cut` + kept hits not `assessed`. Implement the §5 table rule by rule, first match wins:
     1. `search is None` -> `not_run`, reason `not_searched`.
     2. some kept `assessed` hit with `states_whole_claim` true, `whole_claim_evidence_count >= 1`, and for **every** id in
        `element_ids` exactly one cell of that hit that is `explicit_support` with `condition_alignment = 'aligned'` -> `closed`
        (`whole_claim_stated`), whatever the outcome (running, paused, stopped and failed searches included). `reasoned_inference`,
        `partial_match`, a missing cell or `states_whole_claim` without a quote cannot close. An unrelated, unreadable or unassessed
        other hit does not undo it.
     3. -> `undecided`, with `reasons` listing every applicable code in this fixed order and `reason` the first: `search_running`
        (outcome running), `search_paused`, `search_failed` (outcome completed and no query `succeeded`), `search_incomplete` (outcome
        failed or stopped), `query_outcome_unknown` (outcome completed and some query `outcome_unknown`; own-judgement addition,
        report it: an unknown query result cannot support "no match"), `insufficient_access`, `not_assessed_budget` (also a kept hit
        still `pending` once the search is not running or paused), `uncertain_relevance` (assessed hit `uncertain`),
        `uncertain_cell` (a `related` assessed hit has an `uncertain` cell), `unclear_alignment` (a support cell with
        `condition_alignment = 'unclear'`).
     4. any assessed hit with a support cell (`explicit_support`, `reasoned_inference`, `partial_match`) -> `narrowed` (`partial_overlap`).
     5. outcome `completed` AND at least one query `succeeded` AND ((`kept > 0` AND every kept hit `assessed` with `work_relevance =
        'unrelated'`) OR (`kept == 0` AND `found == 0`)) -> `open` (`no_match_in_assessed_subset`). An empty hit list with `found > 0`
        is never `open`.
     6. anything else -> `undecided` with reason `unclassified` and a warning naming the unmatched shape (fail closed; never `open`).
     `rank_cut` alone never makes `undecided`. A kept hit with `assessed` but `work_relevance = 'related'` and no support cell cannot
     exist (store rejects it); if it reaches the function anyway it falls to rule 6.
   - `workflow/candidates/hits.py`: `merge_and_cut(per_query: list[list[dict]], keep: int = 8) -> dict`. `per_query[i]` is the i-th
     *successful* query's ordered records, each `{"provider", "source_version_id", "work_id"}`, queries already in position order. Order:
     round-robin by rank (every query's 1st record, then every 2nd, ...; inside one rank, query order); deduplicate by `work_id` (first
     seen wins, the later records count as `duplicates`; a record with no `work_id` is deduplicated by `source_version_id`); keep the
     first `keep`, the rest are `rank_cut`. Returns `{"kept": [..], "cut": [..], "found", "kept_count", "rank_cut", "duplicates"}` with
     `rank_key` 1-based over kept then cut. Deterministic, order-stable, pure.
   - `workflow/candidates/terms.py`: `block_vocabulary(setting: list[str], task: list[str]) -> dict` builds `{"block_assignment":
     "kill_search", "terms": [...]}` in the `TERM_FIELDS` shape (each term entered as its whole phrase: `root = phrase`,
     `in_query = "phrase"`, counts `None`, `and_only` False, `dropped` None), normalised with `criterion.norm`, de-duplicated across
     both blocks, **at most 6 terms in total and at least 1 per block** (`InvalidTerms` otherwise); no backup terms and no
     substitution anywhere (D143 leaves D92's backup substitution out; the K2 contract may carry backups for display only). `compile_queries(vocabulary, providers, limit=6)`
     calls `compile_block_queries(vocabulary, providers, limit, routed=True)` and returns the queries; `query_issues` is applied by a
     test, not by this function. No other function.
4. **`workflow/candidates/store.py`, class `CandidateStore(store: Store)`**, `self.conn = store.conn`, same style as `LineageStore`
   (`transaction()` joins an outer one; `InvalidCandidateInput` for refused input, `RevisionConflict` for stale versions, `NotFound`).
   Nothing in `workflow/report/*`, `workflow/lineage/*`, `flow.py` or `worker.py` changes; no import of `flow.py`. Functions (each
   one transaction, each emits one `candidate_changed` event via `Store._event` with `{candidate_id, change}`):
   - `open_from_gap(research_id, report_id, gap_row_id) -> dict`: the report must belong to the research and the row to the report
     (`NotFound` otherwise), `kind` in `GAP_KINDS` (`InvalidCandidateInput`). Copies `kind`, `text`, `basis_json`, `provenance_json`,
     the report id and `report_gaps.id` as plain text. `origin_fingerprint` = sha256 hex of canonical JSON (`sort_keys`,
     separators) of `{"kind", "text", "basis": parsed basis_json}`. `origin_basis_view_json` = the basis resolved to visible content
     at that moment, best effort and fail-soft: `basis_cell_ids` -> the cell's current value text, `basis_passage_ids` -> the passage
     text and its source version id, `basis_claim_keys` -> the claim's current text; an id that no longer resolves is recorded as
     `{"id": ..., "missing": true}`, never an error. Same gap row id and same fingerprint -> returns the existing candidate (replay,
     no second row). Same gap row id but a different fingerprint -> a new candidate; the older one stays and is reported as superseded
     by the read `candidate(...)["origin_changed"]` (true when a newer candidate with the same `origin_gap_row_id` exists).
   - `open_from_owner_text(research_id, text, idempotency_key=None) -> dict`: text 1 to 2000 characters after strip; the origin fields
     are NULL, `origin = 'owner_text'`; a replayed `idempotency_key` (stored as a column with UNIQUE; add it to `research_candidates`)
     returns the same candidate, a key used for another research or another text raises `InvalidCandidateInput`.
   - `add_version(research_id, candidate_id, *, claim_statement, conditions, elements, nearest_simple_explanation, critical_assumption,
     validation_plan, origin, step_input_id, expected_version, idempotency_key=None) -> dict`: `expected_version` is the candidate's
     `current_version` (0 for the first), checked with `check_expected_version`; new version number = current + 1; elements 2 to 6,
     each `{text, kind}` with `position` assigned 1.. in order; `claim_statement` and element texts non-empty; `conditions` a list of
     non-empty strings (may be empty); `nearest_simple_explanation` may be NULL; `origin` and `step_input_id` as the CHECK says; the
     `current_version` pointer moves in the same transaction; an `idempotency_key` (column on `candidate_versions`, UNIQUE) replay with the same candidate and the same content (claim, conditions,
     elements, explanation, assumption, plan, origin, step input) returns the stored version **before** the `expected_version` check; the
     same key with different content or for another candidate raises `InvalidCandidateInput`. A trashed candidate refuses new versions.
   - Reads: `candidate(candidate_id)`, `candidates(research_id, include_trashed=False)`, `version(candidate_version_id)` (with its
     elements in position order), `versions(candidate_id)` (oldest first), all returning dicts; `NotFound` when the candidate belongs
     to another research than the caller names (functions that take `research_id` check the pair).
   - `trash_candidate(research_id, candidate_id)` / `restore_candidate(...)`: set/clear `trashed_at`; refused (`RevisionConflict`)
     while an active run (`ACTIVE_RUN_STATUSES`) of kind `claim_decomposition` or `kill_search` has `target_json.$.candidate_id` equal
     to the candidate. Trashing never rewrites any version, search, hit, cell or override (test by comparing the tables).
   - `start_kill_search(research_id, candidate_version_id, run_id, *, query_block, rendered_queries, skipped_terms, selection) ->
     dict`: inserts the `kills_searches` row with `outcome = 'running'` and the frozen columns (JSON-dumped verbatim); the version must
     belong to a candidate of the research and be the candidate's version (any version, not only the current: a search of an older
     version is allowed and stays tied to it); the run must exist, be of kind `kill_search` and belong to the research; a replay with
     the same `run_id` and identical version and frozen content returns the stored row, the same `run_id` with a different version or
     different frozen content raises `InvalidCandidateInput`; `created_at` is bumped by one millisecond when needed so "latest search" by
     `(created_at, id)` follows insertion order (the L4 pattern).
   - `record_query(kill_search_id, *, position, provider, query_text, status, records, error_code=None, raw_payload_path=None,
     payload_sha256=None, step_id=None) -> list[dict]`: refused (`RevisionConflict`) when the search is terminal. `records` are provider
     record objects (the type `upsert_provider_source` takes); it calls **only** `store.upsert_provider_source(provider, record,
     raw_payload_path)` per record, inserts the `kill_search_queries` row and one `kill_search_query_records` row per record
     (rank 1-based in provider order), and returns `[{"provider", "source_version_id", "work_id"}]` in that order for `merge_and_cut`.
     A failed or unknown query has no records. Replaying the same `position` with the same provider, query text, status, error code, payload path, payload hash, step id and
     the same ordered record list (compare a sha256 of the canonical JSON of each record's `provider_record_id`, title, DOI and abstract; store that digest in a `records_sha256` column of `kill_search_queries`) returns the list rebuilt from the stored query-record rows and inserts nothing
     (do not call `upsert_provider_source` again on a replay); the same position with any of these different raises
     `InvalidCandidateInput`. `query_records(kill_search_id) -> list[list[dict]]` returns the stored per-query lists (succeeded
     queries only, position order) so a resumed run can call `merge_and_cut` again. **Isolation (tested)**: nothing in this module
     or its callees may call or reach `record_search`, `add_search_run`, `add_to_corpus`, `link_records`, `_corpus_changed`, or write
     `corpus_memberships`, `candidates`, `selections`, `selection_history`, `search_runs`, `candidate_hits`, `suspected_duplicates`,
     `researches.selection_revision`. Known limit (decision, do not engineer around it, report it): `upsert_provider_source` is the
     shared-library write path discovery uses too, so for a source another research already holds it may fill absent metadata,
     add an abstract passage, re-check arXiv eligibility (`enrich_source`, which can change `asset_arxiv_versions`,
     `asset_extractions`, `source_assets` and write `events` rows of researches holding the source, and can withdraw a source
     reading another research is using), exactly as another research's discovery would. D143 chose this path; K1 claims only that
     the **protected tables** listed in the isolation test do not change, not that no shared library row or other research's
     reading can change. Do not promise full data cleanup either: sibling `other_versions` rows and the payload files they name may
     remain after a purge and enter backups; that is a stated retention trade-off, not a leak to fix here.
   - `record_hits(kill_search_id, merged, reading_depths) -> None`: `merged` is `merge_and_cut`'s result; writes one `kill_search_hits`
     row per kept and cut record (kept: `assessment_state = 'pending'`, `reading_depth` from the caller-supplied map
     `{source_version_id: depth}`, which must cover every kept id (else `InvalidCandidateInput`); cut: `cut_reason = 'rank_cut'`), and
     sets `found`, `kept`, `rank_cut`, `duplicates` on the search (`found` = raw records returned by successful queries before any
     deduplication, `duplicates` = records dropped as another record's work, so `found - duplicates` unique works, `kept` at most 8,
     `rank_cut = found - duplicates - kept`). Refused when the search is terminal. Callable once per search (a second call raises).
   - `publish_assessment(kill_search_id, source_version_id, *, assessment_state, work_relevance=None, states_whole_claim=False,
     note=None, step_input_id=None, cells=(), whole_claim_quotes=()) -> dict`; `cells` is a list of `{element_id, relation,
     condition_alignment, quotes: [{evidence_kind, passage_id, quote}]}`, `whole_claim_quotes` a list of the same quote shape.
     Concurrency control is the hit's own state: publication works from `pending` only (anything else is `RevisionConflict`, except
     an identical replay of a published hit, which returns the stored result). It is **refused with `RevisionConflict` when the search
     is terminal** (`completed`, `failed`, `stopped`), so a late or stale result changes no row; `running` and `paused` accept it.
     For `insufficient_access` and `not_assessed_budget` there are no cells, no quotes, no relevance and no step input; the store
     writes them (code writes `insufficient_access`, the flow writes `not_assessed_budget` before it finishes the search). For
     `assessed` the store validates **before writing anything** (raise `InvalidCandidateInput`, nothing stored), with the consistency
     rules of §5: `step_input_id` required; `cells` must contain **exactly one** cell for **every** element of the search's candidate
     version (`element_id` real ids; missing, duplicate and extra element all rejected); `unrelated` -> every cell
     `no_match_in_supplied_text`; `related` -> at least one support cell; `uncertain` -> at least one `uncertain` cell;
     `condition_alignment` required and non-NULL for the three support relations, NULL for `no_match_in_supplied_text`;
     `explicit_support`, `reasoned_inference`, `partial_match` need at least one quote; `states_whole_claim = True` needs at least one
     whole-claim quote and `related`; whole-claim quotes only when the flag is True. Quotes are stored **as given**: K1 does not
     locate quotes (K2/K3 do that against the text given to the model); it only enforces the passage-belongs-to-source rule (trigger).
     Write order inside one transaction: hit update, cells, element quotes, whole-claim quotes. Use the SAVEPOINT pattern of
     `LineageStore` (copy it) so that when the caller holds an outer transaction, catches an error from this function and still
     commits, none of its partial writes survive.
   - `finish_kill_search(kill_search_id, outcome)`: `running|paused` -> terminal; `set_kill_search_state(kill_search_id, outcome)`
     for `running <-> paused`; both go through the trigger rules; a terminal outcome never changes. Replaying the same terminal
     outcome is a no-op.
   - `record_owner_decision(research_id, candidate_version_id, status, reason) -> dict`: append-only; empty or whitespace reason ->
     `InvalidCandidateInput`; never changes anything else; does not satisfy any evidence gate (nothing in K1 reads it for a status).
   - `kill_search(kill_search_id)`, `searches(candidate_version_id)` (oldest first), `queries(kill_search_id)`,
     `hits(kill_search_id)`, `cells(kill_search_id)`, `evidence(kill_search_id)`, `overrides(candidate_version_id)`.
   - **`candidate_status(candidate_version_id) -> dict`**: `{"computed": derive_status(latest search), "previous": derive_status(most
     recent earlier search whose outcome is `completed`) or None, "owner": latest override or None}`. The latest search is the one with the
     greatest `(created_at, id)`, **whatever its outcome**. The store builds `derive_status`'s inputs, including
     `whole_claim_evidence_count` (rows of `claim_matrix_evidence` with `element_id IS NULL` for the hit) and the version's `element_ids`.
     `previous` never decides the computed status. No version reads another version's searches.
5. **Lifecycle hooks (§9 items 1 and 5)**, each with its own test, edits minimal:
   - `Store.purge_research`: delete the research's candidate tree after the research purge authorization row is inserted and **before**
     `purge_tables`/`step_inputs`/`runs`/passages are deleted (module-level function `purge_candidates(conn, research_id)` in
     `workflow/candidates/store.py`, imported lazily like `purge_tables`): overrides, evidence, cells, hits, query records, queries, searches,
     elements, versions candidates (`current_version` is a plain integer, nothing to clear). Collect the
     `kill_search_queries` payload paths and add them to the `payloads` list before deleting; collect the research's kill-search `source_version_id`s (union of `kill_search_query_records` and `kill_search_hits`) and add
     them to `source_ids`, so sources that only a kill-search held (even one that died before writing hits) are cleaned like
     candidate-pool sources; the "shared" check there must now also treat a source as shared when another research's
     `kill_search_query_records` or `kill_search_hits` still hold it. Sibling `other_versions` rows that `upsert_provider_source` made
     for a record are not cleaned (discovery does not clean them either; known limit, report it). The final "unreferenced payload"
     filter, here **and** in `purge_sources`, must treat a file as referenced while any of these still names it:
     `search_runs.raw_payload_path`, `source_versions.provider_payload_path`, `kill_search_queries.raw_payload_path`, and
     `passages.payload_ref` (an abstract passage added through a kill-search query points at that file).
   - `Store.purge_sources`: the "source still held elsewhere" check also counts `kill_search_query_records` and `kill_search_hits` (any
     research), so a shared source is not deleted; its final payload filter gets the four-way reference check above. It does not
     delete candidate rows.
   - `Store.cited_source_versions`: add `claim_matrix_cells.source_version_id` and `claim_matrix_evidence.source_version_id` to the UNION
     (a source an assessment cell or quote cites is cited; a hit that was never assessed is protected by the shared-source check, not
     by raising). Keep the existing placeholders in order.
   - `Store.research_cites_asset`: add a UNION ALL branch for `claim_matrix_evidence` (kind `passage`) joined through
     `kill_searches -> candidate_versions -> research_candidates.research_id` to `passages.asset_id`.
   - `Store.asset_impact`: add the key `"candidate_quotes"` (count of `claim_matrix_evidence` rows on passages of the asset). Additive; if an
     existing test compares the dict exactly, update only that expectation and report it.
   - `storage/backup.py::_referenced_files`: add `kill_search_queries.raw_payload_path` and `passages.payload_ref` **only for rows with `kind = 'abstract' AND payload_ref IS NOT NULL`** (PDF passages hold character ranges
     such as `chars:0-120`, which are not files and must never reach the backup file list; test it) to the provider-payload set; backup and restore
     keep the ten candidate tables row by row.
   - Research trash/restore keep everything; a test proves no candidate-table row changes.
6. **Limits of K1** (do not exceed): no model call, no contract, no method file, no `RUNTIME_FILES` change, no `flow.py`, `worker.py`,
   `api/*`, no `create_run` stage mapping, no web, no view model, no `workflow/report/*`, no write to `report_gaps`, no PDF acquisition,
   no quote location, no budget or ceiling logic (K3), no status text (K4), no sort of candidates for display.

## Files allowed

`backend/deixis/storage/migrations/00NN_candidates.sql` (new, `NN` = next free), `backend/deixis/workflow/candidates/__init__.py`,
`status.py`, `hits.py`, `terms.py`, `store.py` (new), `backend/deixis/workflow/store.py` (only `purge_research`, `purge_sources`,
`cited_source_versions`, `research_cites_asset`, `asset_impact`), `backend/deixis/storage/backup.py` (only `_referenced_files`),
`tests/test_candidate_status.py`, `tests/test_candidate_store.py` (new), `tests/test_migrations.py`, `tests/test_backup.py`,
`tests/test_corpus_removal.py`, and any other existing test whose exact expectation legitimately changes (a migration-count
assertion, an exact `asset_impact` dict); say which and why. `docs/decisions.md` (D144) and this prompt's comment line are written by
the orchestrator, not by you.

## Files NOT allowed

Everything else, in particular `backend/deixis/domain/*`, `backend/deixis/workflow/flow.py`, `worker.py`, `api/*`,
`workflow/report/*`, `workflow/lineage/*`, `contracts/*`, `methods/*`, `apps/web/*`, `scripts/*`, `tests/fakes.py`, `tests/fixtures/*`,
`docs/product/sw-status.md`, `TODO.md`, `.vscode/`, any existing migration.

## Tests to add (synthetic, no network, no real model; text marked SYNTHETIC; name each test so its limit is readable)

`tests/test_candidate_status.py` (pure; build inputs by hand): one fixed case per rule of the §5 table and per reason code, plus:
`closed` from a partial or paused or stopped search; `closed` not undone by an unrelated, `insufficient_access` or unassessed other hit;
`reasoned_inference` and `partial_match` and a missing element cell and `different_conditions` and `unclear` each fail to close;
`states_whole_claim` without `whole_claim_evidence_count` fails to close; every undecided reason alone and the fixed reason order with
several together; `search_failed` versus `not_run`; `rank_cut` alone gives `open` when everything kept is unrelated and `facts.unread`
counts it; zero found with a succeeded query gives `open`, kept zero with found above zero gives `unclassified`; a `completed` search
with an `outcome_unknown` query gives `undecided`; `running` search with only unrelated hits gives `undecided` (not `open`); a pending
hit in a completed search gives `not_assessed_budget`; the table is exhaustive: a small generated product of outcomes, hit states and
cell relations never returns a status outside the five and never returns `open` or `closed` without its explicit rule's conditions
(property-style loop, deterministic, no random); purity (import allowlist) for all three pure modules.
`merge_and_cut` cases: round-robin across providers, `work_id` deduplication (first wins, duplicates counted), cut at 8 with the
exact `rank_cut` count and `rank_key` order, shuffled inputs of different lengths, a record without `work_id`, empty input.
`block_vocabulary` cases: shape equals `TERM_FIELDS`, normalisation, cross-block duplicate, 7 terms refused, empty block refused;
`compile_queries` output on a mixed provider list passes `query_rules.query_issues` for every returned query (one assertion over the
real compiler and the real rules, offline).

`tests/test_candidate_store.py` (fixture: synthetic research with a table and a few source versions with passages, like
`make_library`; plus one report with a `report_gaps` row of each kind inserted directly by SQL, not through the report flow):
- Schema guards, direct SQL against the real migrated schema: CHECK refusals for every constraint listed in decision 2 (origin
  shapes, version/step_input rule, hit shape rules, cell alignment rule, evidence shape rule, empty owner reason); append-only
  triggers (update and delete of versions, elements, cells, evidence, overrides refused; deletes of searches, queries and hits
  refused; deletes allowed only under a research purge authorization of the owning research and not under another research's);
  conflicting inserts (REPLACE, upsert, explicit id) refused for every no-conflicting-insert table; hit update rules (pending ->
  assessed only once, non-pending frozen, identity columns frozen); `kill_searches` frozen columns and outcome transitions (terminal
  frozen, counts frozen after terminal); `kill_searches` insert guard (a run of another kind, a run of another research refused); cell
  integrity triggers (an element of another version, a source that is not a kept assessed hit of that search refused); evidence
  integrity triggers (mismatched search/source/element against its cell refused, passage of another source refused, whole-claim quote
  needs the whole-claim hit); `current_version` pointer guards.
- Store behaviour: `open_from_gap` for each of the three gap kinds copies text, basis, provenance and kind, with the basis view
  resolved (and the missing-id fail-soft case); the same row opened twice returns the same candidate; the row rewritten in place by SQL
  with a different text then opened again gives a **new** candidate and the old one reads `origin_changed`; a gap of a report of another
  research, a gap row of another report, a kind outside `GAP_KINDS` all refused; the copy survives deleting the `report_gaps` row
  (the candidate still reads fully); `open_from_owner_text` with replay and key reuse; `add_version` versions 1 and 2 with
  `expected_version` conflicts, element count 1 and 7 refused, the pointer moving only through the function, replay and cross-candidate
  key reuse; a trashed candidate refuses a new version; trash refused while an active candidate run exists (insert the run row
  directly) and allowed after it ends; trash/restore leave every other table unchanged.
- Kill-search records: `start_kill_search` with replay and wrong kind/research; `record_query` stores sources only through
  `upsert_provider_source`; `record_hits` then `publish_assessment` for every outcome (assessed with a link between relevance and
  cells, `insufficient_access`, `not_assessed_budget`); every rejected publication shape stores **nothing** (missing, duplicate and
  extra cell; wrong relevance/cell pairing; missing alignment; support relation without a quote; whole-claim flag without a quote or
  with `unrelated`; step input missing); a second publication for the same hit is a conflict; replay with identical content is
  returned; `finish_kill_search` transitions and the frozen terminal; **isolation** test: take a full snapshot (every row of
  `corpus_memberships`, `candidates`, `candidate_hits`, `search_runs`, `selections`, `selection_history`, `record_links`,
  `researches.selection_revision` and the research's `updated_at`) before a complete start/query/hits/publish/finish sequence and
  compare after (the protected set is exactly the research-scoped tables listed here; the shared library rows `works`, `source_versions`, `identifier_mappings`, `passages`, `record_references`, and, only when a source already held by a research is re-upserted, `asset_arxiv_versions`,
  `asset_extractions`, `source_assets` and `events`, plus the candidate tables, may differ; a test with a **fresh** source asserts
  those last four do not change, ignoring only `candidate_changed` events the candidate functions themselves write; add a test that a
  replay with the same `provider_record_id`s but a changed abstract raises), and a spy that fails the test if `record_search`,
  `add_search_run`, `add_to_corpus`, `link_records` or `_corpus_changed` is called; `candidate_status` through the store for one fixed
  case per status computed from stored rows, including a running search with partial cells that already closes, a newer failed search
  hiding an older completed one (the older one shows as `previous` and does not decide), no search at all, and a search of version 1
  not affecting version 2; owner decisions appended with reason, the empty reason refused, the computed status unchanged by them.
- Lifecycle, one test per point: `purge_research` through the real entry point deletes the whole candidate tree and the hit-only
  sources and leaves a source another research's hit still holds, deletes payload files only when nothing else references them
  (including a `kill_search_queries` path shared with a `search_runs` path), and works with a research that has runs, step inputs and
  passages created by the candidate batch; `purge_sources` refuses nothing it did not refuse before, does not delete a source a kill-search
  hit of another research holds, and does not delete candidate rows; `cited_source_versions` sees cell and evidence sources, and does not
  raise for a hit-only source; `research_cites_asset` sees a candidate passage quote, and the existing PDF removal/replacement route
  (through `create_app` and the test client, no API code changes) treats a file cited only by a kill-search quote as cited;
  `asset_impact` counts `candidate_quotes`; trash and restore of the research change no candidate-table row.
- `tests/test_migrations.py`: `test_the_candidate_migration_keeps_every_run_and_every_row_that_points_at_one` (database at the
  version before the new migration, one run of every kind the old CHECK allows with `target_json`, `usage_json`, `error_json`,
  `idempotency_key` and odd statuses, rows in tables that reference `runs` (`run_steps`, `cell_revisions.run_id`, a
  `lineage_link_revisions` row with `run_id`); migrate; every run row identical column by column; dependent rows intact;
  `PRAGMA foreign_key_check` empty and `foreign_keys` ON after; `runs_status` index present; both new kinds accepted; an unknown kind
  still refused), the migration on an **empty** pre-0060 database, and a test that the Python vocabularies you introduced (relation,
  alignment, assessment state, outcome and so on, as module constants in `store.py` or `status.py`) equal the SQL CHECK lists parsed
  from `sqlite_master`.
- `tests/test_backup.py`: `test_backup_and_restore_keep_candidates_searches_hits_cells_overrides_and_payload_files_identical` (use the existing
  entry points; compare every candidate table row by row before and after; a kill-search query payload file is present after restore;
  a missing referenced payload file makes the backup fail like any other).
- Payload references (in `tests/test_candidate_store.py`, two named tests): `purge_sources` of research A does not delete a payload
  file that a live `kill_search_queries` row of research B still names; a payload file that only a surviving abstract passage's
  `payload_ref` names (source kept, query rows purged) is not deleted and is still in the backup. Also: a run interrupted after
  `record_query` and before `record_hits` has its sources removed by `purge_research` of that research.
- Backup shape: a PDF passage with `payload_ref = 'chars:0-120'` does not add a file to the backup list and the backup of such a
  library succeeds.
- Atomicity: `publish_assessment` run inside an outer transaction with an error injected at the last evidence insert (the caller
  catches it and commits) leaves the hit `pending` and no cell or quote row; a late publication on a terminal search, a second publication,
  and `record_query` / `record_hits` on a terminal search change no row.
- Idempotency: `add_version` same key same content returns the first version even when `expected_version` is now stale; same key
  different content raises; `start_kill_search` same run id different version raises.
- `tests/test_corpus_removal.py`: a source cited only by a kill-search assessment cell cannot be purged from the corpus; after the
  candidate's research is purged (or the cells are gone) it can; a source only a hit holds is not deleted by another research's
  `purge_sources`.

## Checks to run

Focused: `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest tests/test_candidate_status.py tests/test_candidate_store.py
tests/test_migrations.py tests/test_backup.py tests/test_corpus_removal.py tests/test_lineage_store.py -n 0`, then the full
`PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest` (expect 0 failures; the old memory-limit failure is fixed on main; a
test that fails only under parallel load and passes alone: rerun it alone and say so). Report the counts. If any test outside the
allowed list fails, stop and report; do not widen scope. `git diff --check` clean.

## Report at the end

Files changed; the migration number; every judgement call (the `query_outcome_unknown` reason, pending hits, kept-zero rule, hit
`assessment_state` shape, candidate trash functions, event name, `idempotency_key` columns, anything the note left open); everything
you could not find or verify; the exact pytest counts; open items for K2 and K3 (at least: `create_run` stage mapping, quote
location against the model-given text, budget ceilings, step-input/handle plumbing, per-query merge input persistence).
