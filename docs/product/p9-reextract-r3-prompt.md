<!-- PLAN-REVIEW-ROUNDS: r1 (gpt-6.1-sol medium): düzeltmeyle hazır, 4 high + 9 medium + 1 low, all folded in; O1-O6 agreed, O7 proposed by Sol; r2: düzeltmeyle hazır, 3 high + 3 medium, all folded in (R2-F3 resolved by narrowing the promise, accepted in r3); r3: düzeltmeyle hazır, 0 high, 0 medium, 2 low, folded in by the orchestrator without a fourth round; after the implementer's stop on S1, the anchor clause was clarified (stored `anchor_text`, no offsets) -->
<!-- REBASE NOTE: the migration this prompt calls 0068 landed as 0069_recovery_purge_authorization.sql, because P8 B5 took 0068 first. -->

# Task: P9 re-extraction batch R3, cited-occurrence views, one shared evidence-dependency helper, verified input observations, backup and authorized purge of recovery history

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-reextract-r3`, detached at `af9a21e` (origin/main with R1 = D190, R2a = D191,
R2b = D192, R2c = D195). Design: `docs/product/p9-reextract-design.md`, accepted as D176. Read all of it; sections 3.1, 5.2, 6, 8, 9
(row R3), 9.1 (T8, T9) and 10 bind this batch. Also read `AGENTS.md`, `CLAUDE.md`, D181 (P8 B1), D190, D191, D192 and D195 in
`docs/decisions.md`, `docs/product/p9-reextract-r2c-prompt.md` (the previous batch prompt), `backend/deixis/workflow/text_retry.py`,
`backend/deixis/workflow/file_restore.py`, `backend/deixis/storage/backup.py`, `backend/deixis/workflow/review/reader.py`,
`backend/deixis/workflow/review/stale.py`, `backend/deixis/workflow/review/store.py`, the R1/R2 tests `tests/test_reextract_r*_*.py` with
their helper modules (`tests/reextract_r2a_helpers.py`, `tests/reextract_r2b_helpers.py`, `tests/reextract_r2c_helpers.py`) and
`tests/review_helpers.py`. Venv: `.venv` is a symlink to the main checkout's arm64 venv; `apps/web/node_modules` is installed. Run tests
with `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest ...`.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted. No real-model
call, no provider call, no network. Do not touch `../DEIXIS*` worktrees, `TODO.md`, `.vscode/`, `scripts/local_index.py`, the live service on
port 8765 or the live data directory. **Do not edit** (other sessions own them or R3 does not need them): `backend/deixis/models/*`,
`backend/deixis/providers/*`, `backend/deixis/workflow/review/snapshot.py`, `stale.py`, `run.py` and every other `workflow/review/*`
file except the one method named in decision 2 of `reader.py` (P8 B8a edits these files now; touch no other line of `reader.py`),
`backend/deixis/workflow/candidates/*`, `backend/deixis/workflow/lineage/*`, `backend/deixis/workflow/tables.py`,
`backend/deixis/workflow/equations.py`, `backend/deixis/storage/db.py`, `backend/deixis/documents/*` except
`documents/acquisition.py::_attach_pdf` (decision 6: imports, the verified read, observation forwarding to `add_asset_with_pages` and
`FileBusy` handling, nothing else), `scripts/*`, `tests/process/*`, anything under `apps/web`, `contracts/`, `methods/`, `.impeccable.md`.
In `backend/deixis/workflow/flow.py` change only `_fetch_pdf`'s placement/parse/insert block (`flow.py:2782-2796`: the verified read,
observation forwarding and extending its existing `FileBusy` handling, decision 6); P8 B5 edits `flow.py` at the same time. In
`backend/deixis/api/app.py` change only what decisions 3, 4, 6, 7 and 10 name. Existing test files stay
unchanged unless decision 12 names them. If R3 truly needs a forbidden file, stop and report it. Do not invent; report what you could not
find, run or measure.

## Why

R1 to R2c made a damaged PDF repairable and its text retryable without losing old evidence, but four promises of D176 are still open.
(1) **Old citations cannot show their own document.** A citation of a superseded extraction resolves its own passage
(`views.py:981-1004`), but the document-text route returns only the current extraction (`app.py:1971-1998` through `store.passages_for`,
`store.py:3079-3087`), and no view says which bytes the cited text was read from or that the file was repaired since (design 6, 7, Q5).
(2) **Report passage freshness is not compared at all.** `ReportStore.evidence_changes` (`report/store.py:406-414`) states
`not_checked: ["passages"]`; a report whose cited passages were superseded exports no notice (`report/export.py:122-123`,
`report/latex.py:245`), while the P8 B1 owner review computes the same rule a second time in Python (`review/reader.py:135-153`, comment
"EVIDENCE_STATUS_SQL's rule, without importing the writable main store"). Design 6 asks for one shared read-only helper used by both.
(3) **Input provenance exists only for retries.** Initial attachments and ordinary upgrades parse the stored path directly and store
`input_observation_id` NULL (`app.py:1630`, `1659`, `1759`, `1883`, `1925`, `2120`, `2155`; `documents/acquisition.py:482`;
`flow.py:2792`; `__main__.py:165`), so even new extractions cannot later prove what bytes they read (design 6 last paragraph; moved from
R2b to R3 by D192 with Sol's agreement). (4) **Repair history is neither backed up nor purgeable.** Backup lists only
`source_assets.storage_path` and payloads (`backup.py:52-67`), so `papers/retained-<sha>.bin` is omitted (pinned as an R3 limitation by
`tests/test_reextract_r2b_store.py:339`); purge deletes only text-retry rows keyed by asset (`store.py:1538-1565`), so `file_restore`
receipts (asset NULL, keyed by hash), their observations and retained files survive the purge of every asset with that hash; recovery rows
have no delete guard (D190 carried "the purge authorization trigger" to R3); unreferenced retained files left by a crash have no owner.
Still not done after R3: any UI (R4: retry action, history, labels for `process_ended`, `file_busy`, receipts, the cited-extraction viewer);
the compatibility closing run (R5).

## What is and is not in code (checked on af9a21e)

- **Evidence status rule.** `EVIDENCE_STATUS_SQL` (`store.py:33-38`) over `passages p LEFT JOIN source_assets a`: `current` for no asset,
  `pdf_replaced`/`pdf_removed` for a removed asset, `text_superseded` when `p.extraction_version IS NOT a.extraction_version`, else `current`.
  Imported by `tables.py:17`, `views.py:26`, `lineage/run.py:24`; `Store.evidence_statuses` (`store.py:2087`) uses it.
  `ReviewReader.evidence_dependency` (`review/reader.py:135-153`) re-implements it in Python and resolves `passage_extraction_id` through the
  unique pair `(asset_id, extraction_version)` and `current_extraction_id_at_snapshot` as the live `outcome='current'` row; `stale.py:106-123`
  and `snapshot.py:46-55` consume that dict. `tests/test_review_separation.py:14-36` forbids `deixis.workflow.store` imports in the review
  package and requires constant `SELECT` strings for `reader.py`'s `execute` calls; `:39-45` pins the reader's public method names.
- **Reports.** `report_citation_links` (`0035_report_run_kind.sql:92-102`) hold every citation; `ReportStore.effective_links`
  (`report/store.py:348`) is the effective set and `original_links` (`:368`) the restorable ones. `report_snapshot.snapshot_json` freezes
  cells with `evidence: [{passage_id, quote}]` (`report/snapshot.py:41-43`); `report_gaps.basis_json` holds `basis_passage_ids`
  (`report/assembly.py:84-86`); section inputs are the latest `step_inputs` row of each section's `step_id` (`assembly._section_payload`,
  `report/assembly.py:94-105`), whose StepInput lists `passages[].passage_id` and `allowlist.passage_ids`
  (`contracts/research/step-input.schema.json`); claim `equation_origin_json` may name a `passage_id` (`report/edit_check.py:58-64`).
  `edit_check.py:30-90` already enumerates most of these without a freshness rule. `report_view` (`views.py:265-432`) returns
  `evidence_changes` minus its sections; the export adds `export_text.evidence_changed_sentence` (`export_text.py:177-180`, "Passage text was
  not checked.") only when `evidence_changes.any`.
- **Passage and document views.** `passage_view` (`views.py:981-1004`) returns the cited passage's own `text`, `extraction_version` and
  `evidence_status`, nothing about its occurrence or input. `GET .../assets/{asset_id}/text` (`app.py:1971-1998`) refuses removed assets and
  returns current-extraction passages only. `GET .../assets/{asset_id}` (`app.py:1953-1969`) serves the stored file for in-use or cited
  assets (`store.research_cites_asset`, `store.py:2096`).
- **Input observations.** `text_retry.observe_copy` (`text_retry.py:138`) copies through one no-follow descriptor, fsyncs and returns
  `(integrity, sha, size)`; a size difference hashes without copying. `Store.add_file_observation` (`store.py:1715`) inserts an immutable
  observation; `operation_id` is nullable and nothing in 0066 requires it for `extraction_input`. `asset_extractions.input_observation_id`
  is a non-deferrable FK, frozen after insert (`0066_asset_recovery.sql:60`, `:72-94`), so the observation must be inserted first in the
  same transaction. `add_asset_with_pages` (`store.py:1570`) already accepts `input_observation_id`; `reextract_asset` (`:1630`) and
  `replace_asset` (`:2051`) do not. `_write_extraction` (`:1591-1628`) refuses recovery metadata on pre-0066 schemas. `db.transaction`
  nests by joining the outer transaction (`db.py:143-158`). Private retry copies live at `recovery_dir/tmp/<sha>-*.pdf` and are swept by
  `_sweep` (`text_retry.py:192`) only when the hash lock is free. OCR (`flow.py:2566-2616`), Marker and arXiv source reads
  (`equations.py:293`, `:444`) parse the stored path and record no input observation.
- **Backup.** `create_backup` (`backup.py:70-110`) snapshots SQLite, enumerates `_referenced_files` on the snapshot (`:52-67`: every
  `source_assets` row, removed ones included, mapped name → sha256 by dict, so a repeated name silently keeps the last hash), copies and
  verifies each file, no lock. `restore_backup` (`:148-210`) accepts any flat name under `papers/` or `provider-payloads/`, refuses an
  existing library or a different file at a destination, places files atomically and the database last. `NOT_INCLUDED` (`:26`) does not
  mention `recovery/`. Backup and restore are CLI-only (`__main__.py:339-366`). `tests/test_p9_restore_matrix.py:685-686` lists both
  recovery tables as empty "because R1 exposes no route".
- **Retained bytes.** `restore_file` names them `papers/retained-<observed_sha256>.bin` (`file_restore.py:175-190`), renames them durable
  before the `before_restore` observation (the only kind that may carry `retained_filename`, 0066 CHECK) commits; a matching existing
  retained file is reused, another one refuses `retention_conflict`. A crash between that rename and the commit leaves a retained file no
  observation names (R2c reconciliation never deletes it, D195).
- **Purge.** `purge_research` (`store.py:304`) needs a trashed research and no active run; it deletes research rows, then per source
  skips shared or cited ones (`cited_source_versions`, `store.py:2813-2835`, which unions B1's `snapshot_referenced_source_versions`,
  `review/store.py:95`, fail-closed `SnapshotDependencyUnreadable`) and deletes the rest, calling `_purge_asset_extractions`
  (`store.py:1538-1565`) before `DELETE FROM source_assets`. `purge_sources` (`:2837`) works on removed members, refuses cited ones and does
  the same per-source deletion. Both return papers-relative file names that the routes unlink after commit (`unlink_orphans`,
  `app.py:1008-1022`, returns names it could not remove). `research_purge_authorizations` (0010) opens the delete triggers of other tables;
  `purge_research` deletes its row (`store.py:395`) before the per-source loop. `asset_recovery_operations` and `asset_file_observations`
  have no delete trigger. Tests delete them directly: `tests/test_reextract_r1_migration.py:189-192`, `:383`. No CLI purge exists.
- **Baseline**: the orchestrator's full run on this commit outside the sandbox: 12,476 passed, 0 failed, 2 skipped, 62 warnings in
  403.62 s (`/tmp/reextract-r3-baseline.log`).

## Decisions taken where the design is open (use these; never ask)

Owner-level choices among them (marked **O**) were proposed by the orchestrator (Claude Opus 5.5) and are confirmed or changed in the plan
review by gpt-6.1-sol medium; the decision entry records who agreed.

1. **Names.** New modules: `backend/deixis/workflow/evidence_deps.py` (decision 2), `backend/deixis/workflow/report/passage_freshness.py`
   (decision 3), `backend/deixis/workflow/recovery_history.py` (decisions 8 and 10; it may import `store`, `text_retry`, `file_restore`).
   New migration `backend/deixis/storage/migrations/0068_recovery_purge_authorization.sql` (decision 9; the number is provisional: if another
   batch lands 0068 first, the orchestrator renumbers at rebase and the strict migration-list tests stay strict). New tests in
   `tests/test_reextract_r3_*.py` with a shared `tests/reextract_r3_helpers.py` if useful.
2. **One shared dependency rule** (`evidence_deps.py`). It imports only the standard library (a test pins that it never imports
   `deixis.workflow.store`, `report.store`, `tables`, `flow` or `review`).
   - Move `EVIDENCE_STATUS_SQL` verbatim into it; `store.py` imports it from there under the same name, so every existing
     `from deixis.workflow.store import EVIDENCE_STATUS_SQL` keeps working (no other module changes its import).
   - `passage_dependencies(conn, passage_ids) -> dict[str, dict | None]`: one constant `SELECT` per chunk of at most 500 ids, read-only, no
     transaction of its own. Per id: the passage row's columns, `dependency_asset_id`, `asset_sha256`, `removed_at`, `removal_reason`,
     `asset_extraction_version`, `passage_extraction_id` (the `asset_extractions` row of the unique pair `(p.asset_id,
     p.extraction_version)`), `passage_extraction_outcome`, `current_extraction_id` (the asset's `outcome='current'` row) and
     `evidence_status` computed **in SQL with `EVIDENCE_STATUS_SQL`**; `None` for an unknown id. On a pre-0066 library it works unchanged
     (it reads no 0066 column except where present; no `extractor_profile` is required).
   - `ReviewReader.evidence_dependency` keeps its name and signature; its body becomes a call to `passage_dependencies(self._conn, [pid])`
     mapped to the exact dict it returns today (same keys, same values; `current_extraction_id` is returned under its existing key
     `current_extraction_id_at_snapshot`). No other line of `reader.py` changes, and `stale.py`/`snapshot.py` are untouched, so B1's reasons
     come from the shared rule with no behavior change. A guard test runs the old query (copied into the test as the oracle) and the new
     method over every passage of the review fixtures and of the R3 promotion fixture and requires equal dicts.
3. **Report passage freshness** (`report/passage_freshness.py::passage_freshness(conn, report_id) -> dict`), read-only, deterministic
   identity comparison, never a support check, never writes (`updated_at`, claims, check results and acknowledgements stay unchanged).
   - Dependencies, each with its `used_by` entry `{"kind", "ref"}`: `citation` (an effective link of `effective_links`, ref = link id),
     `restorable_citation` (a link of the report's claims that is not effective, ref = link id), `snapshot_cell` (a passage in
     `report_snapshot.snapshot_json` cell evidence, ref = cell id), `gap_basis` (`report_gaps.basis_json.basis_passage_ids`, ref = gap row
     id), `section_input` (`passages[].passage_id` and `allowlist.passage_ids` of each section's selected step input under
     `assembly._section_payload`'s latest-row rule, and of every step input named by the report's citation links, ref = step input id),
     `equation_origin` (claim `equation_origin_json.passage_id`, ref = claim id). JSON is parsed with `json`, never matched with `LIKE`.
   - Result (closed shape): `{"compared": "passage_identity", "semantic_support": "not_checked", "dependencies": <distinct passage ids>,
     "affected": [...], "unresolved": [...], "file_restored_after": [...]}`. `affected`: every resolved passage whose shared-helper
     `evidence_status != "current"`, as `{"passage_id", "source_version_id", "evidence_status", "passage_extraction_id",
     "current_extraction_id", "used_by"}`. `unresolved`: `{"passage_id": <id or null>, "reason": "passage_missing" | "unreadable_record",
     "used_by"}` for an id with no passage row, or a snapshot, basis or step-input record that cannot be parsed into the expected shape (the
     function still answers; it is a read model, not a purge gate). `file_restored_after`: passage ids whose asset hash has a completed
     `file_restore` operation with outcome `file_restored` finished after the passage's occurrence was created (decision 4's rule). Lists are
     sorted by passage id; `used_by` by kind then ref.
   - `report_view` adds the top-level key `passage_freshness` beside `evidence_changes`; `evidence_changes` keeps `not_checked:
     ["passages"]` and every existing key and value (design 6: that older checker's contract is unchanged). Markdown and LaTeX exports add
     one sentence when `affected` or `unresolved` is non-empty, after the evidence-change sentence, from a new
     `export_text.passage_freshness_sentence(tr, affected, unresolved)`: English "Passage freshness compared: {a} passage(s) this report used
     are no longer the current text of their PDF{; {u} could not be resolved}. Semantic support was not checked." with a Turkish equivalent of
     the same content. Reports with no affected or unresolved passage export byte-identically to today.
   - **Unreadable records.** `passage_freshness` itself never raises on an unreadable record; it reports it in `unresolved`. R3 does not
     change how the existing readers treat an unreadable report snapshot or gap basis (`ReportStore.snapshot`, `report/store.py:135-140`;
     `evidence_changes`, `:420-423`, `:480-482`; `report_view`, `views.py:273-277`, `:297-299`, `:386-417`): they raise as today, so through
     the report view and the exports `unreadable_record` is reachable for step-input payloads and claim equation origins, and through
     `passage_freshness` directly for every record kind. Hardening those pre-existing readers is outside R3 (Limits); R3 adds no new
     failure path to them.
4. **Cited-occurrence views** (`views.py`, `app.py`). Design 7 and Q5: an old citation opens its own stored extraction; current text is an
   explicit comparison; the input relation is stated, never inferred.
   - `passage_view` adds `occurrence`: `null` for an abstract (no asset), else `{"extraction_id", "extraction_version", "extractor_profile"
     (null before 0066), "outcome" ("current" | "superseded" | "rejected" | null when the pair has no row), "is_current",
     "current_extraction_id", "input": null | {"observation_id", "integrity", "observed_sha256"}, "input_relation", "file_restored_after",
     "latest_file_restore"}`. `input` is the occurrence's own `input_observation_id` row; `null` means the input was not recorded and is
     **never backfilled** from today's file. `input_relation` relates the bytes the parser read to the asset's **recorded expected
     identity** (`asset.sha256`), not to the file the PDF route serves now (that route serves the present file without hashing it,
     `app.py:1953-1969`; D195 Limits): `"input_matched_expected_hash"` when `input.integrity == "verified"` and its observed hash equals
     the asset hash, `"input_differed_from_expected_hash"` when `input.integrity == "mismatch"` (with `"retained_copy": true|false` added:
     whether a `before_restore` observation's `retained_filename` names those observed bytes), `"input_not_recorded"` otherwise. R4 copy
     must keep that qualification. `file_restored_after` is true when a
     completed `file_restore` operation with outcome `file_restored` for the asset's hash finished after the occurrence's `created_at`;
     `latest_file_restore` is `store.file_restore_view` of the newest such operation or null. All of it is read through decision 2's helper
     plus constant SELECTs; a pre-0066 library answers `extractor_profile`, `input`, `latest_file_restore` null, `input_relation`
     `"input_not_recorded"`, `file_restored_after` false.
   - `GET .../assets/{asset_id}/text` takes an optional `extraction_id` query parameter. Absent: unchanged. Present: access follows
     `get_asset`'s rule (in use, or a removed/replaced asset this research cites), the extraction must belong to the asset and have outcome
     `current` or `superseded` (a `rejected` or foreign id answers 404 "Extraction is not part of this asset"), and the response has the same
     shape with the passages of exactly that occurrence (`asset_id` and `extraction_version` equal, ordered as `passages_for` orders), the
     `equations_to_check`/`source_equations` of that version, plus top-level `occurrence` (decision 4's object without per-passage data).
     The current text of an **in-use** asset stays available through the request without the parameter (that request still refuses a
     removed asset, `app.py:1975-1978`); the response's `occurrence` says which occurrence it is.
   - No highlight, page match, offset or anchor is computed here. Each evidence link already carries its stored, source-owned
     `anchor_text` (located by `domain.contracts.locate_anchor` when the answer was validated, `contracts.py:1314-1338`; no offsets are
     stored or returned); the UI keeps locating that exact text in the passage it shows. R3 adds no range contract.
5. **Verified input observations** (new helper in `text_retry.py`, used by decisions 6 and 7).
   - `async read_verified(store, papers_dir, recovery_dir, *, storage_path, sha256, byte_size, lock: bool) -> VerifiedRead` with fields
     `extraction` and `observation` (the fields for `add_file_observation`, kind `extraction_input`, `operation_id` NULL) or `observation`
     None. With `lock=True` it takes the hash lock through `file_restore.writer_lock` (wait up to `WRITER_LOCK_WAIT_SECONDS`, then
     `FileBusy`); with `lock=False` the caller already holds it (never acquire twice). Under the lock: `observe_copy` into
     `recovery_dir/tmp/<sha>-*.pdf` in `drained_thread`, then, only when the copy is `verified`, `pdf.extract_pdf(copy)` in `drained_thread`
     with the parser defaults; the copy is unlinked in `finally` (cleanup failures logged, never hiding the result or the original error);
     the lock is released after the parse. Store calls stay on the event-loop thread; no transaction spans an await. Abandoned copies:
     with `lock=True`, `read_verified` calls the existing `_sweep(recovery_dir)` **before** acquiring the lock, as `execute_text_retry`
     does (`text_retry.py:229-232`; it removes only `<sha>-*.pdf` copies whose hash lock is free, so copies under another live lock
     survive); with `lock=False` (the caller already holds the hash lock) it calls `_sweep` and then removes the remaining
     `<own sha>-*.pdf` copies, which no live holder can own while this caller holds the lock; the synchronous CLI equivalent follows the
     `lock=False` rule. So an abandoned copy of a killed attachment, upgrade or retry is removed by the next verified read or text retry of
     the same or of any other file; nothing else sweeps (no startup sweep is claimed).
   - **O1. Copy not verified on an initial attachment** (missing, size or digest mismatch; only an outside process can cause it, because
     every writer replaces by rename under the lock): nothing is parsed; the observation records what was seen (`missing`, or `mismatch` with
     the observed digest and size) and the asset gets a `failed` extraction with no pages, `page_count` 0 and error "The stored PDF changed
     before its text was read; upload it again to repair it." built as `pdf.Extraction(status="failed", error=...)` in `text_retry.py`
     (no edit to `documents/pdf.py`). The person can repair and retry through R2a (an empty failed baseline recovers under D190).
   - **Legacy cases read as today, with no observation:** a stored hash that is not lowercase 64-hex (synthetic fixtures such as
     `"sha-paper"`; no writer can lock or replace such a path) or a library without the 0066 tables: parse the stored path directly,
     `observation` None. A guard test pins both branches.
6. **Initial attachments.** Every site that parses a newly placed file for its first extraction calls `read_verified(..., lock=True)` on
   the placed `storage_path` and passes the observation to the Store, which inserts it and links it as `input_observation_id` in the same
   transaction as the extraction: `app.py:1630` (upload, new source), `:1659` (upload to an existing source), `:1759` (waiting attachment),
   `:1883` and `:1925` (both Zotero paths), `:2120` (Replace PDF, through a new keyword of `replace_asset`), `documents/acquisition.py:482`
   (`_attach_pdf`, used by acquisition, renditions that attach a PDF and confirmed candidates) and `flow.py:2792` (run-time fetch). A
   `FileBusy` from this read is handled exactly as that caller already handles `FileBusy` from `restore_file`/`store_pdf_file` (the placed
   file stays; no asset is created; run-time fetch finishes its step `failed` with `fetch_file_busy`, which means extending `_fetch_pdf`'s
   existing `try` to cover the read). Both Zotero routes call the verified read **inside** their existing per-item exception handlers
   (`app.py:1875-1886`, `:1917-1927` today parse outside them), so a `FileBusy` read is noted and the import continues as it does for a
   busy placement (no asset). An O1 result (`missing`/`mismatch` observation, failed extraction) is not an exception: the item keeps its
   failed asset and observation **and** gets a per-item note naming the unverified input, and the import continues. The match endpoints (`app.py:1692`,
   `:1708`) parse a staged upload and create no asset: unchanged. `add_asset_with_pages`, `reextract_asset` and `replace_asset` accept
   `input_observation: dict | None` (inserted through `add_file_observation` inside their write transaction, NULL operation); a dry run
   inserts nothing.
7. **Ordinary upgrades.** The no-body extraction POST (`app.py:2152-2156`) keeps its lock, its precheck and its same-profile shortcut, and
   replaces the direct parse with `read_verified(..., lock=False)` under the lock it holds. **O2.** A copy that is not verified publishes
   nothing and answers 409 `{"code": "input_not_verified", "detail": "The stored PDF does not match its recorded hash; upload it again to
   repair it, then extract its text again."}`; the head, passages and events are unchanged. The CLI library-wide upgrade
   (`__main__.py:160-169`) does the same under its existing non-blocking lock (a synchronous equivalent of the helper is acceptable if it
   shares `observe_copy`, the copy location, the cleanup and the observation fields), prints outcome `input_not_verified` for such an
   asset, counts it and continues; exit code 0 as for every other per-asset outcome; `--dry-run` copies and parses but inserts no
   observation. OCR, Marker and arXiv source reads keep parsing the stored path and record no input observation (**O3**: their reads hold a
   run or the reader lock and are tool augmentations, not ordinary upgrades; Limits).
8. **Backup** (`storage/backup.py`, `recovery_history.py` helpers allowed).
   - `_referenced_files` also lists every `asset_file_observations.retained_filename` under `papers/` with its **observed** digest
     (`observed_sha256`). The name must match `^retained-[0-9a-f]{64}\.bin$` and its hex part must equal that digest; otherwise
     `BackupError` naming the observation. A name listed twice with two different non-null hashes (two asset rows, two observations, or an
     asset and an observation) raises `BackupError("contradictory hashes recorded for papers/<name>")` instead of keeping the last one.
     Retained files are copied and verified like asset files; restore needs no change (they are flat `papers/` names) and places them
     before the database as today. A retained file no observation names is not backed up (it is not evidence, design 5.2).
   - **O4. Serialisation.** Each asset file whose stored hash is lowercase 64-hex is copied and verified while holding that hash's lock,
     waited for with a synchronous loop of the same `WRITER_LOCK_WAIT_SECONDS` / 0.05 s semantics as `writer_lock`; still busy after the wait
     → `BackupError("papers/<name> is busy with a file repair, text retry or equation read; try the backup again when it ends")`, and the
     partial backup folder is removed as today. Retained files are written once and never replaced, so they are copied without a lock and
     verified against their observed digest; a missing or concurrently removed retained file refuses the backup like a missing asset file.
     Hashes that are not 64-hex keep today's lock-free copy. A text retry or restore row still
     `running` in the snapshot is copied as recorded; after restore, R2c's startup reconciliation ends it as `process_ended` (no text is
     retried).
   - `NOT_INCLUDED` adds `"recovery (file locks and private temporary copies)"`.
9. **Purge authorization** (migration `0068_recovery_purge_authorization.sql`). `CREATE TABLE recovery_purge_authorizations (sha256 TEXT
   PRIMARY KEY) WITHOUT ROWID`; `BEFORE DELETE` triggers on `asset_recovery_operations` and `asset_file_observations` abort with
   "recovery history requires purge authorization" unless a row for `OLD.expected_sha256` exists. Nothing else changes in the schema; no
   existing trigger, index or FK is dropped. The migration test shows the guard on both tables, that an authorized delete in one
   transaction leaves `PRAGMA foreign_key_check` empty, and that 0068 applies on a 0067 library and on the historical fixtures the strict
   migration tests already use.
10. **Authorized purge of recovery history** (`store.py` purge paths, `recovery_history.py`, `app.py` purge routes and
    `unlink_orphans`).
    - **O5.** Inside the existing purge transaction, before any deletion of a source that will be deleted: if any `running` recovery
      operation is a text retry of one of its assets or a `file_restore` of one of their hashes, raise `RevisionConflict("A file repair or
      text retry of these sources is still running; try again when it ends.")` (existing 409 mapping; the whole purge rolls back). A crashed
      running row is normally reconciled on the next worker turn (R2c); a reconciliation failure or the absence of a worker can prolong the
      refusal (Limits).
    - **O7. Frozen JSON records protect their passages' sources** (design 8: "Also inspect passage IDs embedded in StepInputs, report
      snapshots and gap basis JSON when determining orphanhood"). A new read-only scan in `recovery_history.py` (or a module it imports;
      not `review/*`), run inside both purge transactions after the purged research's own rows are gone and before any source deletion,
      parses with `json` every surviving `step_inputs.payload_json`, `report_snapshot.snapshot_json` and `report_gaps.basis_json`, collects
      at any depth every value under a key named `passage_id` and every element of a list under a key named `passage_ids` or
      `basis_passage_ids` (the gap record's key, `report/assembly.py:83-85`), maps those passages to their `source_version_id` and treats
      those sources as referenced. A string is a reference; `null` is no reference (the contract permits null passage ids, e.g.
      `step-input.schema.json:448-455`, `:1362-1365`); any other type under those keys, a non-list under a list key, or unparsable JSON
      raises a new `FrozenDependencyUnreadable` (409, code `frozen_dependency_unreadable`, detail "A stored model input, report
      snapshot or gap record could not be read, so nothing was deleted."), mapped like `SnapshotDependencyUnreadable`; nothing is deleted.
      In `purge_research` a referenced source is kept like a shared one. In `purge_sources` a referenced source refuses the purge with
      `RevisionConflict("A stored model input or report record still uses passages of {n} of these sources; delete their research
      instead")`, after the existing citation refusal. Passage ids with no row are ignored (already orphaned). This changes existing
      behavior: a removed source whose passages were ever sent to a model step in that research can no longer be purged on its own. Existing
      tests that purge such a source: report each with the reason and change the fixture (not the assertion) only where the test is not
      about this rule.
    - **Source sharing versus byte sharing.** When a source survives (shared, cited, snapshot-protected or O7-referenced), every row of its
      assets survives, including their text-retry history and input observations, unchanged. When a source is deleted, R1's
      `_purge_asset_extractions` keeps deleting **that asset's** extractions, text-retry operations and extraction-input observations even
      if another source's asset has the same bytes. The hash-keyed history (`file_restore` operations, their `before`/`after`
      observations and retained files) is deleted only when **no** remaining `source_assets` row (any state, any research) has that hash; a
      remaining asset with the same hash keeps it.
    - **FK-safe order.** Before deleting anything of a source, compute the closure of recovery rows that must survive: an observation
      still referenced by a row outside the deleted set keeps itself, its owning operation (`operation_id`) and, transitively, everything
      that operation or a kept extraction references (operation → asset, operation → baseline extraction, extraction → baseline extraction,
      extraction → operation). No application path creates such an outside reference today; if the closure would keep any row whose
      asset, extraction or source is about to be deleted, the purge refuses with `RevisionConflict("Recovery history of these sources is
      still referenced elsewhere; nothing was deleted.")` and the whole transaction rolls back (no partial deletion). Otherwise delete the
      eligible extraction rows, then eligible observations, then eligible operations, before the assets; never update a frozen pointer to
      break a cycle. Authorization rows (decision 9) for every hash touched are inserted first and deleted before commit. `PRAGMA
      foreign_key_check` is empty after commit.
    - B1's protections stay exactly as they are: citations and surviving owner-review snapshots (`cited_source_versions`) keep their sources;
      an unreadable snapshot still stops the purge with `SnapshotDependencyUnreadable` and changes nothing; an authorized purge of a
      snapshot's own research still deletes its owner-review rows first under B1's order.
    - **Retained bytes leave only through a guarded unlink.** Both purge methods keep their return shapes and add a deleted retained filename
      to their papers-relative orphan list only when no remaining observation names it. `unlink_orphans` (`app.py:1008-1022`) removes a name
      matching `^retained-[0-9a-f]{64}\.bin$` only through `recovery_history.remove_retained(store, papers_dir, name)`: inside one short
      `BEGIN IMMEDIATE`, re-check that no observation names it and that no `file_restore` operation is `running` (a restore of **another**
      hash can reuse the same retained name between purge commit and unlink, `file_restore.py:176-191`), then unlink synchronously before
      `COMMIT`; otherwise leave the file and report the name in `files_not_removed`. Asset files and payloads keep today's unlink.
    - **O6. Unreferenced retained files.** New CLI `deixis recovery-files [--delete]`: lists `papers/retained-*.bin` whose name no
      observation references (plus their size) and, only with `--delete`, removes each one through the same `remove_retained`. It first runs
      `reconcile.reconcile_stale` under the normal Store setup. `.part` staging files are not touched. Exit 0 when every requested deletion
      succeeded, 1 when a running restore blocked one or an unlink failed (each such name printed), 2 for a schema problem (existing
      `schema_problem` rule). No API route.
11. **Rejected and superseded text stay out of retrieval.** No code change is expected: a guard shows that after rejected, `no_change`,
    diagnostic-only and promoted retries, `passages_for`, `search_passages` (FTS), `has_pdf_text`, `answer_versions` and the inspection
    ranking read only the current occurrence, and that rejected candidate passages never appear in any of them.
12. **Existing tests.** Expected changes, each minimal and reported: `tests/test_reextract_r2b_store.py::test_backup_and_purge_keep_
    receipt_and_retained_bytes_new_contract` (it pins the R3 limitation: the retained file now **is** in the backup, and the unshared purge
    now deletes the receipt and returns the retained file; the shared case keeps both); `tests/test_reextract_r1_migration.py:189-192` and
    `:383` (raw deletes now need the authorization row inside the same transaction); `tests/test_p9_restore_matrix.py:685-686` (fill the
    recovery tables and a retained file in the rich library and remove them from `EMPTY_BECAUSE`; add `recovery_purge_authorizations` to
    `EMPTY_BECAUSE` with the transient-authorization reason used at `:702`); strict migration lists (`tests/test_migrations.py:670`, the
    packaged maximum at `tests/test_connector_dispatch.py:592` and any other that names the last packaged migration) gain 68, while
    `tests/test_connector_dispatch.py:606` stays `[67]` (it copies only 0067 into an isolated directory); a separate 0067→0068 preservation
    test is added. Tests whose fixtures purge a source that O7 now protects: see decision 10.
    Any other existing test that breaks: report it with the reason before editing it; do not weaken an assertion to pass.

## Tests that must fail on the old code, and regression guards

Name each test's role: **red on old** (the first assertion fails on `af9a21e` for the defect named), **guard** (passes on both) or **new
contract** (exercises something that does not exist on `af9a21e`; name its paired red-on-old or guard assertion). The orchestrator re-runs
the red-on-old ones against a clean copy of `af9a21e`. Each red-on-old test's **first** assertion is behavioral and old-compatible (routes,
tables, columns and functions present on `af9a21e`). Synthetic PDFs from `tests/helpers.py::make_pdf`; libraries in `tmp_path`; API tests
use `create_app(..., start_worker=False)` unless a test is about the lifespan or worker; child processes get `PYTHONPATH=<worktree>/backend`
(plus the worktree root when they import `tests.*`) and the temporary `DEIXIS_DATA_DIR`. **Fail-on-call fakes**: `ocr.read_page`, the math
reader, adapters and the HTTP transport raise in every test that is not about them.

- **S1 (red on old): an old citation opens its own document text.** Seed a `partial` head with passages cited by an answer; promote a
  same-profile retry (R2a POST) that reads more pages. `GET .../assets/{aid}/text?extraction_id=<old>` → first assertion: every returned
  passage id belongs to the old occurrence and the text is the old text (old: the parameter is ignored and current passages come back).
  Then: `occurrence.outcome == "superseded"`; without the parameter the current occurrence; a rejected occurrence and another asset's
  extraction answer 404; a replaced asset the research cites still opens its old occurrence; the citing evidence link's stored
  `anchor_text` is a contiguous substring of the returned old passage's text (and the test seeds the promoted text so that the same
  anchor is not contained in the current passage of that page, showing the old occurrence is what makes it locatable).
- **S2 (new contract, paired with S1): passage provenance.** `passage_view` of the cited old passage: `occurrence` with `extraction_id`
  resolved by the pair, `is_current` false, `current_extraction_id` the promoted head, `input` null and `input_relation` `"input_not_recorded"`
  for the legacy head (never backfilled, even after the file is hashed by a later restore); after a `restore_file` repair of a torn file,
  `file_restored_after` true and `latest_file_restore` the receipt; for an extraction made by R3's initial attachment, `input.integrity`
  `"verified"` and `input_relation` `"input_matched_expected_hash"`, unchanged after the stored file is torn later (the field describes
  the recorded input, not the served file); a mismatch input observation (seeded) gives `"input_differed_from_expected_hash"` with
  `retained_copy` true exactly when a retained file of those bytes is recorded; abstracts give `occurrence` null; a pre-0066 library
  answers the documented nulls.
- **S3 (red on old): report passage freshness is disclosed.** A report whose effective citation, restorable citation, snapshot cell
  evidence, gap basis, section input and equation origin each use a passage of the partial head; promote the retry. Markdown export →
  first assertion: the passage-freshness sentence is present (old: the export says nothing, because `evidence_changes.any` is false).
  Then `report_view["passage_freshness"]["affected"]` lists each passage once with every `used_by` kind, `evidence_status`
  `text_superseded`, distinct `passage_extraction_id` and `current_extraction_id`; `evidence_changes` is byte-identical to before
  (including `not_checked: ["passages"]`); LaTeX export carries the sentence; Turkish export carries the Turkish sentence; a missing
  passage is `unresolved` (`passage_missing`) through the report view (unreadable basis JSON is tested only by calling
  `passage_freshness` directly, below); a report with nothing affected exports byte-identically;
  every table's rows are unchanged by building the view and the exports. **Unreadable records (new contract):** `passage_freshness`
  called directly on an unparsable and on a wrong-shaped snapshot, gap basis and step-input payload returns `unresolved` entries with
  `unreadable_record` and does not raise; through the report view an unreadable section step input does the same.
- **S4a (guard): dependency results unchanged.** For every passage of the review fixtures and of the promotion fixture,
  `ReviewReader.evidence_dependency` equals the complete old computation copied into the test (the old SQL **and** the old Python status
  derivation, `review/reader.py:136-153`), and `Store.evidence_statuses` is unchanged; this part runs on both commits.
  **S4b (new contract, paired with S4a):** `evidence_deps.passage_dependencies(...)["evidence_status"]` equals `Store.evidence_statuses`
  for every passage; `evidence_deps` imports none of the forbidden modules; `tests/test_review_separation.py` passes unchanged.
- **S5 (guard, T8): owner review and protected rows.** One library with an answer, a table cell, a report (all six dependency kinds) and a
  P8 B1 owner-review snapshot of the answer and of the report, all using the partial head's passages. For each outcome — promoted retry,
  rejected retry (candidate loses an old text page), `no_change` retry, diagnosis (legacy empty `no_text` head and a password PDF, a
  separate asset whose source is in the same research), interrupted retry (R2c child killed in the parser, then reconciled) and file-only
  restore — compare every application row of every table before and after by identity and content (`tests/review_helpers.all_rows`).
  Allowed differences only: new rows in `asset_recovery_operations`, `asset_file_observations`, `asset_extractions`, `passages` and
  `events`; the prior extraction's `outcome` and the asset's four mirror fields on promotion or diagnosis; the operation's lifecycle
  columns; the `sqlite_sequence` row of `events` advancing by exactly the number of new events (no other `sqlite_sequence` row may change);
  FTS physical storage, which is checked logically instead (every old passage row byte-identical; FTS search returns exactly the current
  occurrence's passages). Owner-review rows
  (`content_json`, `content_sha256`, `markers_json`, findings, decisions) are byte-identical in every case. `stale_reasons`: after
  promotion `extraction_changed` and `text_superseded` for each manifest entry whose recorded status was `current`; after rejected,
  `no_change`, interrupted and file-only, no reason; a snapshot taken when its evidence was already superseded keeps distinct
  `passage_extraction_id` and `current_extraction_id_at_snapshot` and gains no reason until a dependency moves. Answer
  `source_text_changed` and the cell `text_superseded` flag follow promotion only.
- **S6 (red on old): initial attachments record their verified input.** Parametrized over generic upload (new and existing source),
  waiting attachment, both Zotero paths, acquisition `_attach_pdf`, confirmed candidate, run-time fetch and Replace PDF (reuse
  `reextract_r2b_helpers` drivers). First assertion (SQL on 0066 columns): the new asset's current extraction has a non-NULL
  `input_observation_id` (old: NULL). Then: kind `extraction_input`, `operation_id` NULL, `verified`, observed digest/size equal to the
  asset's; the parser was called with a path under `recovery_dir/tmp`, never the stored path; the private copy is gone. **New contract:**
  an outside process tearing the stored file between placement and the read (patched `observe_copy` boundary) gives a `failed`
  extraction with O1's error, a `mismatch`/`missing` observation and no parser call; a busy lock beyond the patched wait gives each
  caller's existing `FileBusy` outcome and no asset; a two-item Zotero import whose first item's stored file is torn before the read
  records that item's failed asset, observation and note without calling the parser for it, and completes the second item; a non-hex
  synthetic hash and a pre-0066 library parse the stored path with no
  observation.
- **S7 (red on old): ordinary upgrade reads a verified copy.** Older-profile asset, stored file torn (same size, other bytes). No-body
  POST → first assertion: status 409 with code `input_not_verified` (old: 200 and an extraction parsed from the torn bytes is recorded).
  Head, passages and events unchanged. Whole file: 200, the new extraction links a verified observation, parser called on the private
  copy. CLI library-wide upgrade: `input_not_verified` line, other assets still processed, exit 0; `--dry-run` writes no observation.
- **S8 (red on old): backup keeps retained bytes, T9 round trip.** One library: R2b's torn-file repair of a shared asset, a promoted
  retry, an answer and a report citing the old occurrence, and populated P8 B1 owner-review rows for both (snapshots with manifests, reviews,
  findings, decisions). `create_backup` → first assertion: the manifest lists `papers/retained-<observed>.bin` with the observed digest
  (old: absent). Then restore into a fresh folder: retained bytes, observations, receipts, extractions, old/current passages and every
  owner-review row and manifest are identical (row and file hashes, IDs); startup of the restored library retries no text. Then, **in the
  restored library**, purge an unrelated research that shares the source: the same comparisons hold. **New contract (paired with the
  first assertion):** contradictory hashes for one name refuse with no backup folder left; a retained name not matching its observed digest
  refuses; a retained file no observation names is not backed up; a removed retained file refuses; `NOT_INCLUDED` names recovery.
- **S9 (new contract, paired with S8's first assertion): backup races complete or refuse.** A child process holds the asset hash lock (as a restore or retry would): backup
  with the wait patched small refuses with O4's message and leaves no folder; the child releasing within the wait lets the backup finish
  with verified bytes. A child running a real restore parked after its retention rename and before its observation commit: a backup
  taken then either refuses or contains a database and files that agree (every referenced file present and verified; the unreferenced
  retained file absent). A backup taken while a text retry row is `running` restores into a library whose startup reconciles it to
  `process_ended` with the parser spy silent.
- **S10 (red on old): purge removes unshared recovery history.** Torn-file repair (receipt with `before`/`after` observations and a
  retained file) plus a promoted retry of an asset held by one research; trash and `DELETE /api/trash/{rid}` → first assertion:
  `asset_recovery_operations` has no row for that hash (old: the `file_restore` receipt survives). Then no observation of it remains, the
  response unlinked `retained-<sha>.bin` (gone from disk), `PRAGMA foreign_key_check` is empty. Same through the source-purge route.
  **Guards and new contract:** (a) a second research sharing the source keeps every recovery row and the retained bytes unchanged;
  (b) another source's asset with the same bytes keeps the hash-keyed history and retained bytes, while the deleted asset's own text-retry
  rows and input observations go; (c) a citation in another research and (d) a surviving owner-review snapshot as the only protection
  (T9) each keep the source and all its history; (e) an unreadable snapshot (each B1 shape) stops the purge with
  `SnapshotDependencyUnreadable` and changes nothing; (f) an authorized purge of the snapshot's own research deletes its owner-review rows
  first under B1's order, then the recovery history; (g) an observation still referenced from outside the deleted set keeps itself and
  its owning operation, with an empty FK check; an outside reference (seeded by direct SQL) to an observation owned by a text-retry
  operation of the otherwise deletable asset refuses the purge with nothing deleted; (h) **cross-hash unlink race**: after the purge commits and before `unlink_orphans` runs, a
  restore of another hash records an observation naming the same retained file (or is `running`) → the file stays and is reported in
  `files_not_removed`.
- **S10b (red on old, O7): frozen JSON records protect sources.** Each of a step input (`passages[].passage_id`), a report snapshot cell
  evidence entry and a gap `basis_passage_ids` entry, as the **only** reference to a removed source's passage (no citation, no owner-review
  snapshot): `purge_sources` → first assertion: 409 and the source row still exists (old: the source and its passages are deleted).
  In `purge_research` of another research holding nothing else, the source survives. Unparsable JSON, an integer or object
  `passage_id`, and a `basis_passage_ids` that is not a list of strings each stop either purge with `frozen_dependency_unreadable` and change
  nothing. **Guard:** valid stored candidate and report-review step inputs with `passage_id: null` (as in
  `tests/fixtures/research/step-inputs.json`) do not block an otherwise eligible purge; B1's snapshot refusal order is unchanged.
- **S11 (red on old): purge refuses while recovery runs.** A child process holds a real text retry parked in its parser (or a restore
  parked in its retention copy) for an asset of the research; trash and purge → first assertion: `RevisionConflict` / HTTP 409 (old: the
  purge deletes the asset's rows while the operation runs). Nothing deleted; after the child finishes, the purge succeeds.
- **S12 (red on old): purge authorization guard.** Plain `DELETE` of an observation, then of an operation, outside purge → first
  assertion: `sqlite3.IntegrityError` and the row still exists (old: the delete succeeds). Then the trigger message; inside an authorized transaction it succeeds; `INSERT OR REPLACE` cannot bypass it (existing conflict triggers).
- **S13 (new contract, paired with S10's first assertion and S10h): `deixis recovery-files`.** Lists an unreferenced retained file and leaves it without `--delete`; deletes it with
  `--delete`; never deletes a referenced retained file or a `.part` file; with a live restore running (child holds its lock) refuses and
  exits 1; a crashed running restore is reconciled first and then the file is deleted.
- **S14 (guard): retrieval reads only the current occurrence** (decision 11).
- **S14b (guard): preservation in surfaces R3 does not change.** After a promoted retry over the partial head: a PDF seed's stored
  question/vocabulary inputs and `seed_status` (`store.py:557`, its extraction-version rule), a person-reading plan and its quotes, a lineage link's
  evidence (`lineage/view.py:44-47`) and its existing staleness flags, a candidate's basis passages (`candidates/store.py:213-216`) and
  `claim_matrix_evidence` keep their rows and IDs byte-identical, still resolve the cited passage text, and show whatever freshness signal
  they already had; no novelty verdict, lineage decision or plan is recomputed. Adding occurrence/status fields to the candidate and
  lineage views is carried (decision record), not done here, because P8 B8a owns the candidate files now.
- **S16 (new contract): abandoned private copies.** A child killed inside the verified read of an attachment and of an ordinary upgrade
  leaves `recovery_dir/tmp/<sha>-*.pdf`; the next verified read of the **same** hash (both `lock=True` and `lock=False` callers) and of a
  **different** hash, and the next text retry, each remove it; a copy whose hash lock a live child holds survives a sweep made by another
  hash's read.
- **S15 (guard): unchanged R1/R2a/R2b/R2c and B1 behavior.** All `tests/test_reextract_r1_*`, `r2a_*`, `r2b_*`, `r2c_*` and every
  `tests/test_review_*` pass (with only decision 12's changes).

## Checks to run

Focused tests while building, then the whole suite inside your sandbox:
`PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest -q -p no:cacheprovider`. Tests needing sockets, process
listings or child processes that your sandbox blocks: list them by name; the orchestrator reruns the full suite outside the sandbox. Keep
child-process tests even if your sandbox cannot run them, and say so. Then `git diff --check`. No web change: no build, lint or Playwright run.

## Report and records

Write `/tmp/reextract-r3-impl-report.md`: files changed, each decision's implementation with file:line, every test with its role and what it
shows, existing tests changed and why, full-suite counts with the failure list, what you could not do. Draft the decision entry at the top of
`docs/decisions.md`, above D195: `## D197 — P9 re-extraction R3: an old citation opens its own extraction with its input stated, reports and
owner reviews share one passage-dependency rule, new extractions record the bytes they read, and repair history is backed up and purged only
by authorized purge` with Status (accepted, implemented; writer gpt-6.1-sol high; leave the reviewer line and the owner-level agreement line
for the orchestrator), Date 2026-10-03, Context, Decision (the shared helper and what consumes it; the report freshness shape and export
sentence and its `unresolved` reporting; the occurrence object, `input_relation` vocabulary and the `extraction_id`
text parameter; verified reads for initial attachments and
ordinary upgrades with O1/O2; backup listing, contradiction refusal and O4 serialisation; migration number and the purge authorization trigger;
purge of `file_restore` history and retained bytes, source versus byte sharing, the FK-safe order, the guarded retained unlink, O5
refusal, O7 frozen-record protection, shared/cited/snapshot protection; the `recovery-files` CLI), Verification
(leave counts for the orchestrator), Carried work (R4: UI for the occurrence object, current-text comparison, `input_relation` and
`file_restored_after` copy that keeps the "recorded expected identity" qualification, report passage-freshness display,
`input_not_verified`, `frozen_dependency_unreadable`, the retry action and history, labels for `process_ended`, `file_busy` and receipts,
`.impeccable.md` 4.6 change; candidate and lineage view fields for occurrence/freshness after P8 B8a lands; R5: closing compatibility run),
Limits (synthetic PDFs only; no real
library; OCR, Marker and arXiv source reads record no input observation; legacy extractions keep a NULL input and are never backfilled;
a backup waits up to 10 s for a busy file and then refuses, so a long equation read can make a backup fail; advisory locks cannot stop outside
processes; a crashed running operation blocks purge until reconciled, normally on the next worker turn; `.part` staging files are never
purged; abandoned private copies are removed only by a later verified read or text retry; a removed source whose passages were sent to a
model step can no longer be purged on its own (O7); the frozen-record scan reads every stored step input on each purge and its cost is
unmeasured; an unreadable report snapshot or gap basis still makes the report view and exports fail as before R3; report passage freshness
is an identity comparison and checks no semantic support; `input_relation` describes the recorded input
against the expected hash, not the bytes the PDF route serves now; candidate, lineage and table views gain no field in R3; Windows
untested). Do not edit
`STATUS.md` (the orchestrator does).

## Do not

Rewrite, delete or re-hash old passages, extractions, observations, snapshots, report rows or owner-review rows outside an authorized purge;
backfill an input observation for an existing extraction; parse unverified bytes on an initial attachment or ordinary upgrade (except the
legacy non-hex/pre-0066 branch); make the passage view or the report view write anything; change `evidence_changes`' existing keys or values;
add a stale reason to B1's closed `REASONS`; edit `stale.py`, `snapshot.py`, `run.py` or any `reader.py` line other than the body of
`evidence_dependency`; back up an unreferenced retained file or a `recovery/` file; delete hash-owned file-restore history while any remaining
asset holds that hash (asset-owned text-retry history follows decision 10's deletion and retained-dependency rules); delete a retained file while a restore runs or except through `remove_retained`; let a cleanup failure hide the original error; add production crash hooks; edit forbidden
files.
