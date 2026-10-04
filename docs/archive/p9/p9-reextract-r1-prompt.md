<!-- PLAN-REVIEW-ROUNDS: r1 (gpt-6.1-sol medium): düzeltmeyle hazır, 2 high + 7 medium + 2 low, all folded in; r2 (gpt-6.1-sol medium): düzeltmeyle hazır, 0 high + 3 medium + 1 low, all folded in; r3 (gpt-6.1-sol medium): düzeltmeyle hazır, 0 high + 1 medium (rowid replace) + 1 low, all folded in; r4 (gpt-6.1-sol medium): hazır, no findings -->

# Task: P9 re-extraction batch R1, occurrence identity, additive migration and the deterministic promotion policy

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-reextract-r1`, detached at `c3048f4` (origin/main with P8 B1, D181). Design:
`docs/product/p9-reextract-design.md`, accepted as D176. Read all of it; sections 3.3, 4, 4.1, 4.2, 9 (row R1), 9.1 (T1, T3, T4, T5, T10)
and 12 bind this batch. Also read `AGENTS.md`, `CLAUDE.md`, D176, D181, D165 and D169 in `docs/decisions.md`, and
`docs/archive/p8/p8-b1-prompt.md` (the previous batch prompt, style model). Venv: `.venv` is a symlink to the main checkout's arm64 venv. Run tests
with `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest ...`.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted. No real-model call, no
provider call, no network. Do not touch `../DEIXIS*` worktrees, `TODO.md`, `.vscode/`, `scripts/local_index.py`, the live service on port 8765 or
the live data directory. **Do not edit** (other sessions own them): `backend/deixis/models/*`, `backend/deixis/providers/*`,
`backend/deixis/workflow/review/*`, `backend/deixis/domain/rules.py`, `backend/deixis/models/prompt.py`, `backend/deixis/workflow/views.py`,
`backend/deixis/documents/pdf.py`, `backend/deixis/documents/ocr.py`, `backend/deixis/documents/arxiv_source.py`, `backend/deixis/documents/jats.py`,
`backend/deixis/storage/db.py`, `backend/deixis/storage/backup.py`, `backend/deixis/__main__.py`, `scripts/p9/*`, `tests/process/*`, anything under
`apps/web`, `contracts/`, `methods/`. `backend/deixis/workflow/flow.py` and `backend/deixis/api/app.py` are edited by two other batches at the same
time: you may change only the lines named in decisions 9 and 10 below, nothing else in those two files. If R1 truly needs another forbidden file,
stop and report it. Do not invent; report what you could not find, run or measure.

## Why

D165 and D169 left one known defect open (H7 finding 2): an asset row stored from a torn download keeps its `failed` extraction after the file is
repaired, because a second extraction with the same `extraction_version` is impossible (`UNIQUE(asset_id, extraction_version)`) and the promotion
rule (D45) refuses a page-count change from a zero-page failure. D176 accepted a recovery design in batches R1 to R5. **R1 lays the storage and
policy base and nothing user-facing:** a stored extraction gets an identity separate from its tool profile, a recovery attempt can be stored as a
new occurrence beside the old one, and one deterministic, tested policy decides whether that occurrence becomes current. After R1 no route, button
or CLI option starts a recovery (R2a), no file is repaired with a receipt (R2b), interruption is not reconciled (R2c), old citations still open
current text (R3/R4). R1 is not "very small", so it does **not** take R2a with it.

## What is and is not in code (checked on c3048f4)

- `asset_extractions` (`storage/migrations/0027_asset_extractions.sql:9-22`): `id`, `asset_id`, `extraction_version`, `status`, `error`,
  `page_count`, `text_pages`, `passage_count`, `outcome` (`current`/`superseded`/`rejected`), `rejection_reason`, `created_at`,
  `UNIQUE(asset_id, extraction_version)`, partial unique index `asset_extractions_one_current`; later migrations added `math_json`, `ocr_json`.
  There is no profile column, no baseline, no input observation, no decision code. No trigger guards updates of an extraction row.
- `passages_no_update` is last defined in `0054_arxiv_latex_source.sql:37` and covers only `text, source_version_id, kind, physical_page`.
  No production code updates any passage column (`grep -rn "UPDATE passages" backend` finds nothing); tests do at
  `tests/test_lineage_view.py:479`, `tests/test_report_edit_check.py:301` (drops the trigger first), `:561`, `:607` (drops the trigger first),
  `tests/test_storage.py:53` and `tests/test_arxiv_source_migration.py:99` (both expect the refusal).
- The only production updates of `asset_extractions` change `outcome` (`workflow/store.py` near 1382, 1384, 1575). The equation code inserts
  passage-less rows with `INSERT OR IGNORE` (`workflow/equations.py` near 335, 443, 484) and deletes passage-less rejected rows in
  `_forget_failure` (near 473). `tests/test_arxiv_source_route.py:337` updates `created_at` to age a row.
- `Store.reextract_asset` (`workflow/store.py` near 1522): returns `unchanged` when the `(asset_id, extraction_version)` pair exists (near 1537);
  promotion rule near 1541-1551: status rank `succeeded > partial > no_text > failed`, equal page count, no fewer text pages; nothing compares
  *which* pages have text. `_write_extraction` (near 1501) writes passages then the extraction row; `_insert_passage` (near 1445) deduplicates on
  `(source, kind, asset, page, text_sha256, extraction_version)`. `add_asset_with_pages` (near 1481), `replace_asset` (near 1593) write a first
  extraction.
- Tool labels are built from `pdf.EXTRACTION_VERSION`: OCR endpoint `api/app.py:1937` (`ocr.target_version(pdf.EXTRACTION_VERSION, ...)`, 409
  when that pair exists, near 1938); the OCR run merges onto a fresh `pdf.extract_pdf` result (`workflow/flow.py` near 2517-2525, `ocr.merge`
  takes `base.extraction_version`); equations `target_version`/`source_target_version` (`workflow/equations.py:52-61`, `OCR_SUFFIX` at 42 with
  lookahead `(?=\+marker-|\+arxiv-latex-|$)`). The arXiv withdrawal (`workflow/store.py` near 1376) restores "the latest superseded row created at
  or before" the source row, not a recorded predecessor.
- String checks on the current version that must keep working: `views.py:599` (`split("+")[0] == pdf.EXTRACTION_VERSION`), `views.py:602`
  (`NOT LIKE '%+marker-%'`, `'%+arxiv-latex-%'`), `__main__.py:147` (`NOT LIKE EXTRACTION_VERSION || '+%'`), `api/app.py:1973`
  (`split("+")[0]`), equations `endswith(SOURCE_SUFFIX)` (near 76, 106), `"+marker-" in` (near 228, 452), `next_asset`'s
  `NOT LIKE '%+' || MATH_VERSION` (near 514), `OCR_SUFFIX.search`.
- P8 B1 (`workflow/review/reader.py:135-154`) resolves `passage_extraction_id` through `(asset_id, extraction_version)` and
  `current_extraction_id_at_snapshot` through `outcome = 'current'`; it parses no version string. B1's stale rule reports `extraction_changed` and
  `text_superseded` when those move. R1 must keep this true; the shared read-only evidence helper of design section 6 is **R3's**, not R1's.
- Purge: `Store.purge_research` deletes extraction rows near line 403, `Store.purge_sources` near 2449, both with
  `DELETE FROM asset_extractions WHERE asset_id IN (...)` and then `DELETE FROM source_assets`. `tests/test_migrations.py` near 116 calls
  `purge_research` on a library migrated only to 0062.
- Highest migration on main: `0064_owner_reviews.sql`. **Migration numbers stay gap-free on main** (coordinator rule, 3 October, overriding an
  earlier reservation of 0065 for P8 B2): the batch that pushes first takes the next free number, today `0065`; the other renumbers at rebase.
  R1's migration is `0065_asset_recovery.sql` (renamed to `0066` at rebase if P8 B2 lands first). It must not depend on anything B2's migration
  might add and must not reference `runs` (B2's may rebuild it). *(Written first as 0066 with 0065 reserved; changed to 0065 in code-review round 1; renumbered to 0066 at rebase because P8 B2 (532cf89) landed first with `0065_owner_review_decision_requests.sql`.)*
- Baseline before R1 (this worktree, measured by the orchestrator outside the sandbox): `8843 passed, 2 skipped, 62 warnings` in 502 s, no
  failure (`/tmp/reextract-r1-baseline.log`).

## Decisions taken where the design is open (use these; never ask)

1. **Names.** Migration `backend/deixis/storage/migrations/0065_asset_recovery.sql`. New module `backend/deixis/workflow/recovery.py` holding the
   identity helpers (decision 2), the coverage manifest and the pure policy (decisions 5, 6). Store methods in `workflow/store.py` (decision 7).
   Tests in new files `tests/test_reextract_r1_migration.py`, `tests/test_reextract_r1_policy.py`, `tests/test_reextract_r1_store.py`,
   `tests/test_reextract_r1_targeting.py` (more if needed).
2. **Occurrence identity.** `extraction_version` stays the immutable identity of one stored occurrence; the new column `extractor_profile` is the
   tool, version and parameters. A recovery occurrence is `<profile>+reextract-<operation_id>` (operation IDs come from `new_id("rop")`, alphanumeric
   and `_` only). A **tool read built on a head that carries a recovery token** (OCR, Marker, arXiv source) carries the same token **directly after
   the text-layer base**, before its own suffixes: on head `B+reextract-rop_X`, OCR is `B+reextract-rop_X+ocr-tesseract-...-v1`, Marker
   `B+reextract-rop_X[+ocr-...]+marker-...`, source `B+reextract-rop_X[+ocr-...]+arxiv-latex-v1`. This is how R1 implements design 4.2's "distinct
   tool occurrence" for recovery: an old rejected `B+ocr-...` row cannot block OCR on a recovered head, a repeat on the same head is still the same
   pair, and every existing string check listed above keeps its meaning because the token never sits after a tool suffix. **Limit, stated in the
   decision:** the label ties a tool read to the recovery occurrence it was built on, not to every later tool head of that lineage; e.g. OCR
   rejected on `B+reextract-X`, then Marker promoted to `B+reextract-X+marker-...`, then an OCR request targets `B+reextract-X+ocr-...` again and is
   409, exactly as today's plain `B` → `B+marker` → OCR case is. Changing that existing repeat policy is out of R1's scope; a test pins the
   behavior. Every tool row still records its exact `baseline_extraction_id` (decision 4). Heads
   without a token get **byte-identical** labels to today's. `recovery.py` exposes, as pure functions with tests: `RECOVERY_TOKEN = "+reextract-"`;
   `occurrence(profile, operation_id)`; `recovery_token(version) -> str` (the `+reextract-<id>` segment or `""`); `profile_of(version)` (the version
   with that one segment removed; any other version is returned unchanged, including `unknown`); `text_base(current_version)` =
   `pdf.EXTRACTION_VERSION + recovery_token(current_version)` (what OCR/Marker/source labels start from). A version holding two tokens, or a
   malformed token, raises `ValueError` (it cannot be produced by R1's writers; the test shows the refusal). `equations.target_version` and
   `source_target_version` use `text_base(current)` instead of `pdf.EXTRACTION_VERSION`; their OCR part is taken from
   `profile_of(current)` with the existing `OCR_SUFFIX` (it matches because the token is not between the OCR part and the end).
3. **Migration `0065_asset_recovery.sql`** (additive; no table rebuild, no `-- deixis:foreign-keys-off`; no edit of an applied file):
   - `asset_extractions` gains: `extractor_profile TEXT NOT NULL DEFAULT 'unknown'`, then `UPDATE asset_extractions SET extractor_profile =
     extraction_version` (every existing row; no existing value contains `+reextract-`, the test asserts it; a literal `unknown` stays `unknown`);
     `recovery_operation_id TEXT REFERENCES asset_recovery_operations(id)` with a separate partial unique index `WHERE recovery_operation_id IS NOT
     NULL`; `baseline_extraction_id TEXT REFERENCES asset_extractions(id)`; `input_observation_id TEXT REFERENCES asset_file_observations(id)`;
     `diagnostic_only INTEGER NOT NULL DEFAULT 0 CHECK (diagnostic_only IN (0, 1))`; `decision_code TEXT CHECK (decision_code IS NULL OR
     decision_code IN (...decision 6's list...))`. **`input_observation_id IS NULL` means "input bytes not observed" (`legacy_unknown`)**: the
     migration creates no observation rows and hashes no file; every existing row stays NULL. Existing values, `UNIQUE(asset_id,
     extraction_version)` and `asset_extractions_one_current` are untouched.
   - Nullability rule for both new tables: **every column is `NOT NULL` unless this list calls it nullable**; a vocabulary column is `NOT NULL`
     **and** `CHECK IN (...)` (SQLite accepts a CHECK that evaluates to NULL, so a CHECK alone never makes a field required). Tests insert a NULL
     into each required column and expect a refusal.
   - New `asset_file_observations` (`WITHOUT ROWID`): `id TEXT PRIMARY KEY`, `operation_id TEXT REFERENCES asset_recovery_operations(id)` (nullable),
     `kind CHECK IN ('before_restore','after_restore','extraction_input')`, `storage_path TEXT NOT NULL` (relative to the papers folder, as
     `source_assets.storage_path`), `expected_sha256 CHECK length 64`, `expected_byte_size INTEGER NOT NULL`, `observed_sha256` and
     `observed_byte_size` (nullable), `integrity CHECK IN ('verified','mismatch','missing','legacy_unknown')`, `retained_filename TEXT` (nullable),
     `observed_at TEXT NOT NULL`. CHECKs (written with explicit `IS NOT NULL`, never by equality alone): `verified` needs `observed_sha256 IS NOT NULL
     AND observed_byte_size IS NOT NULL` and both equal to the expected ones; `mismatch` needs both observed fields `IS NOT NULL` and (hash or size)
     different; `missing` and `legacy_unknown` need both observed fields NULL; `retained_filename` only with `kind =
     'before_restore'` and an observed hash. Immutable: a `..._no_update` trigger refuses every update; a `..._no_conflicting_insert` trigger
     refuses an insert whose `id` exists (so `INSERT OR REPLACE` cannot swap a row). Deletes stay possible (purge, decision 8); R3 adds the
     authorization rule.
   - New `asset_recovery_operations` (`WITHOUT ROWID`): `id TEXT PRIMARY KEY`, `kind CHECK IN ('file_restore','text_retry')`, `asset_id TEXT
     REFERENCES source_assets(id)` (NOT NULL when `kind = 'text_retry'`, by CHECK), `research_id TEXT` (nullable request context, a CLI request has none;
     **no foreign key**: it is the historical ID of the research that asked, and must survive that research's purge, because `purge_research`
     deletes the research row (`store.py` near 369) before source cleanup and a shared asset's recovery history must stay, design 8), `expected_sha256` (length 64), `expected_byte_size`, `baseline_extraction_id TEXT REFERENCES
     asset_extractions(id) DEFERRABLE INITIALLY DEFERRED`, `baseline_profile TEXT`, `mode TEXT CHECK (mode IS NULL OR mode =
     'retry_failed_or_partial')` (NOT NULL for `text_retry`), `idempotency_key TEXT NOT NULL UNIQUE`, `request_fingerprint TEXT NOT NULL`,
     `lifecycle CHECK IN ('running','completed','interrupted')`, `outcome` (NULL unless completed; `CHECK IN ('promoted','diagnosis_updated',
     'rejected','no_change','refused','file_reused','file_restored','file_refused')`), `reason TEXT`, `decision_code` (same list as the extraction
     column), `before_observation_id` and `after_observation_id` (`REFERENCES asset_file_observations(id) DEFERRABLE INITIALLY DEFERRED`),
     `input_observation_id` (same, deferred), `old_coverage_json`, `new_coverage_json`, `created_at TEXT NOT NULL`, `finished_at TEXT`; CHECKs:
     `finished_at IS NULL` exactly when `lifecycle = 'running'`; `outcome IS NOT NULL` exactly when `lifecycle = 'completed'`.
     **Operation nullability, exhaustive:** NOT NULL always: `id`, `kind`, `expected_sha256`, `expected_byte_size`, `idempotency_key`,
     `request_fingerprint`, `lifecycle`, `created_at`. NOT NULL when `kind = 'text_retry'` (by CHECK), NULL allowed for `file_restore`: `asset_id`,
     `mode`, `baseline_extraction_id`, `baseline_profile`. Nullable, filled later or never: `research_id` (no request context), `outcome`, `reason`,
     `decision_code` (NULL while running, and NULL for `file_*` outcomes), `before_observation_id` and `after_observation_id` (NULL for every
     `text_retry`; set for `file_restore` by R2b), `input_observation_id` (NULL while running and on a refusal), `old_coverage_json`,
     `new_coverage_json` (NULL on a refusal and for `file_restore`), `finished_at` (NULL while running). A reservation test inserts a running
     `text_retry` with none of the later fields and it is accepted. Indexes:
     `(asset_id, created_at)`; partial unique `(asset_id) WHERE kind = 'text_retry' AND lifecycle = 'running'` (at most one running text retry per
     asset); `asset_file_observations(operation_id)`. The **deferred** references are the back edges of the two reference cycles
     (operation ↔ extraction, operation ↔ observation), so one purge transaction can delete all of them (decision 8); every other reference is
     immediate.
   - Guards (triggers): (a) `asset_extractions_no_update`: refuses an update of any column except `outcome`, and an `outcome` change other than
     `current → superseded` or `superseded → current` (the two transitions the code uses today). (b) `asset_extractions_baseline_same_asset`
     (BEFORE INSERT): a non-null `baseline_extraction_id` must name an extraction of the same asset. (c) `asset_extractions_recovery_shape`
     (BEFORE INSERT): a non-null `recovery_operation_id` must name a `text_retry` operation of the same asset, and then `extraction_version =
     extractor_profile || '+reextract-' || recovery_operation_id`; a version without `+reextract-` must have `extractor_profile =
     extraction_version`; `extractor_profile = 'unknown'` is refused unless `extraction_version = 'unknown'` (so a writer that forgets the column
     fails loudly instead of storing `unknown`). (d) `asset_recovery_operations_frozen` (BEFORE UPDATE): a row whose `lifecycle` is not
     `running` is immutable; while running, only `lifecycle`, `outcome`, `reason`, `decision_code`, `input_observation_id`,
     `old_coverage_json`, `new_coverage_json`, `finished_at` may change, plus, **only for a running `file_restore`**, a one-time `NULL → id`
     assignment of `before_observation_id` and of `after_observation_id` to an observation of that operation with kind `before_restore` /
     `after_restore` respectively (no rebinding, no change after completion; R2b's restore sequence reserves, then records the damaged-byte
     observation, then replaces the file); `lifecycle` may only become `completed` or `interrupted` (one terminal transition). Schema-level tests
     cover the file-restore assignments now, although the writer is R2b's. (e) `asset_recovery_operations_no_conflicting_insert`: refuses an insert that conflicts on **any** unique key of the operation table:
     `id`, `idempotency_key`, and the running-asset partial index (another running `text_retry` of the same asset), so an `INSERT OR REPLACE` with a
     fresh id and key cannot delete a running reservation. (f) `asset_extractions_no_conflicting_insert`: refuses an insert that conflicts on
     `id`, on the **rowid** (`asset_extractions` is an ordinary rowid table that R1 must not rebuild, so `INSERT OR REPLACE INTO
     asset_extractions(rowid, ...)` with an existing rowid and otherwise fresh values would replace a row; the guard refuses `NEW.rowid` when a row
     with that rowid exists, and ordinary inserts with an automatically assigned rowid still work), on the occurrence pair `(asset_id, extraction_version)`, on the one-current index (a `current` row while the asset has one), or on the
     recovery-operation index. Because a `RAISE(ABORT)` also fires under `INSERT OR IGNORE`, the three equation inserts that rely on `OR IGNORE` as
     an intentional duplicate no-op (`equations.py` near 335, 443, 484) become `INSERT ... SELECT ... WHERE NOT EXISTS (same pair)` with the same
     no-op meaning; a test shows each still does nothing on a duplicate. Conflict tests run with `recursive_triggers=OFF`, as plain `INSERT`,
     `INSERT OR REPLACE` and upsert; each **reuses exactly the key under test and uses fresh values for every other unique key**, and shows the old
     row unchanged. Cases: operation primary id, idempotency key, running asset; extraction id, rowid, occurrence pair, current asset, recovery
     operation; observation id.
   - **Strengthened `passages_no_update`**: `DROP TRIGGER passages_no_update` and recreate it with the same name and message, covering
     `text, source_version_id, kind, physical_page, asset_id, printed_label, abstract_origin, payload_ref, extraction_version, text_sha256,
     text_source, retrieved_at, created_at`. All other triggers (`passages_fts_insert`, `cell_evidence_same_source`, B1's triggers, ...), indexes and
     FTS content stay exactly as they are.
4. **Every writer sets the new columns.** `_write_extraction` takes `extractor_profile` from `recovery.profile_of(extraction_version)` and accepts
   optional `baseline_extraction_id`, `input_observation_id`, `recovery_operation_id`, `diagnostic_only`, `decision_code`;
   `add_asset_with_pages` accepts an optional `input_observation_id` (R2b will pass a verified one; R1's tests use it to seed a baseline whose input
   was observed); **`reextract_asset` moves its whole decision inside its write transaction**: the current extraction, its stored manifest and
   page set, the memberships and the rule evaluation are read after `BEGIN IMMEDIATE`, so the row it decides against is the row it supersedes and
   records (today it decides at `store.py` near 1540-1552, before `transaction()` near 1564; a `dry_run` still decides without writing); a
   two-connection test changes the head between the caller's start and the transaction (use the `guard` hook or a second connection that commits
   before the write) and shows the decision, the recorded baseline and the superseded row are the new head; `reextract_asset` records `baseline_extraction_id` = the current extraction's id read **inside** its write transaction (NULL when
   the asset has none) for accepted and rejected rows alike, and a decision code (`upgraded` on promotion; `status_worse`,
   `page_count_changed`, `fewer_text_pages`, `text_page_lost`, `ocr_found_no_text` on rejection; its human `rejection_reason` text stays as today).
   The three `INSERT OR IGNORE` statements in `equations.py` set `extractor_profile = recovery.profile_of(version)` and `baseline_extraction_id`
   = the asset's current extraction id. A test greps/ASTs every `INSERT ... INTO asset_extractions` in `backend/deixis` (excluding migrations) and
   fails if one does not name `extractor_profile`.
5. **Coverage manifest** (`recovery.py`, pure): the ordered list of `(physical_page, printed_label, payload_ref, text_sha256, text_source)` that
   `_write_extraction` **would store** for an extraction and chunker, applying `_insert_passage`'s deduplication (first chunk per `(page,
   text_sha256)` within the occurrence), and the same list read back from stored passages of an occurrence (ordered by `rowid`). `P` = the set of
   physical pages in a manifest. A test shows the computed manifest of an extraction equals the stored manifest after `_write_extraction`,
   including a page with two identical chunks.
6. **Promotion policy** (`recovery.decide(baseline, candidate) -> Decision`, pure; `baseline` = the stored current row plus its stored manifest,
   its augmentation facts and its input observation integrity or `None`; `candidate` = status, error, page count, profile and computed manifest;
   `Decision` = `promote: bool`, `diagnostic_only: bool`, `decision_code`, `missing_pages`, old/new coverage). Applied in this order; the first
   match decides:
   1. **`no_change`** (reject): candidate manifest, status, error, page count and profile all equal the baseline's **and** the baseline's
      `ocr_json` and `math_json` are NULL (a candidate never carries them, so a baseline with OCR or math provenance is never `no_change`; it goes on
      to the augmentation rule). A test has identical passages but a baseline with non-null `ocr_json` and expects `augmented_text_would_be_lost`.
   2. **Empty baseline** (`passage_count == 0`, status `failed` or `no_text`): candidate `partial`/`succeeded` with at least one text page →
      promote `recovered_text` (the failed baseline's page count is no veto); candidate `failed` with `error == pdf.ERROR_PASSWORD` exactly and
      baseline status `no_text` → promote diagnostic-only `password_diagnosed`; candidate `no_text` → promote diagnostic-only `no_text_diagnosed`;
      any other candidate (`failed` with another error or a `failed` baseline, or `partial`/`succeeded` without a text page) → reject
      `candidate_failed`.
   3. **Baseline with passages**, in this order: candidate `failed` → reject `candidate_failed`; baseline has augmented content (any stored
      passage with `text_source` other than `text_layer`, or non-null `ocr_json`/`math_json`) → reject `augmented_text_would_be_lost` (a recovery
      candidate is always a plain text-layer read); candidate rank lower → reject `status_worse`; then the page-count/observation table, where
      "obs" is the integrity of the baseline's `input_observation_id` (NULL counts as `legacy_unknown`):

      | page count | obs | `P_old ⊆ P_new` | decision |
      |---|---|---|---|
      | differs | `mismatch` | yes | promote `recovered_from_corrupt_input` |
      | differs | `mismatch` | no | reject `text_page_lost` |
      | differs | `verified` | any | reject `page_count_changed` |
      | differs | `legacy_unknown`, `missing`, NULL | any | reject `legacy_page_count_untrusted` |
      | equal | any | no | reject `text_page_lost` |
      | equal | any | yes | promote `text_updated` |

      Tests are parameterized over all five baseline states (NULL, `legacy_unknown`, `missing`, `verified`, `mismatch`) for both page-count cases.
   The full `decision_code` vocabulary (one Python tuple equal to both SQL CHECK lists, tested like B1's vocabularies): `no_change`,
   `recovered_text`, `password_diagnosed`, `no_text_diagnosed`, `text_updated`, `recovered_from_corrupt_input`, `candidate_failed`,
   `augmented_text_would_be_lost`, `status_worse`, `page_count_changed`, `legacy_page_count_untrusted`, `text_page_lost`, `upgraded`,
   `fewer_text_pages`, `ocr_found_no_text`, `input_not_verified`. The outcome vocabulary of `asset_extractions` stays `current`/`superseded`/
   `rejected`; `no_change` is a decision code on a `rejected` row. **The ordinary path (`reextract_asset`) also gains design 3.3's first row:**
   a promotion additionally requires `P_old ⊆ P_new` (old pages read from the stored current occurrence), else reject `text_page_lost`. This
   applies to ordinary upgrades, OCR, Marker and arXiv source reads alike. Required synthetic execution tests, one per tool (OCR run with the
   fake page reader, Marker with the fake reader, arXiv source with the existing fake fetch): coverage preserved → still promoted; a reparse that
   loses an old text page with equal counts → rejected `text_page_lost`, head unchanged. Do not weaken an existing coverage assertion to keep an old
   promotion; report every existing test this rule changes and why. **Loss of existing augmentation on an ordinary tool promotion** (e.g. an OCR
   read replacing a Marker or LaTeX page while page numbers are kept) is **not** refused by R1: the existing tool policy stays and the decision
   records it as carried to a later batch.
7. **Store methods** (`workflow/store.py`; no route uses them in R1):
   - `add_file_observation(*, kind, storage_path, expected_sha256, expected_byte_size, observed_sha256, observed_byte_size, integrity,
     operation_id=None, retained_filename=None) -> str`: one insert; no file is read by the store.
   - `reserve_text_retry(asset_id, *, expected_extraction_id, idempotency_key, request_fingerprint, research_id=None) -> dict`: in one
     `transaction()`: the asset exists and is in use (else `NotFound`); an existing operation with the same key and fingerprint is returned
     unchanged (no new row); the same key with another fingerprint raises a new `RequestConflict`; the current extraction id differs from
     `expected_extraction_id` → new `RecoveryConflict("baseline_changed")`; current status `succeeded` → new `NotRetryable("already_current")`,
     `pending` → `NotRetryable("pending")`; a queued, running or pause-requested run in **any** research holding the source → `RunInProgress` (no
     `allow_run_id` bypass); a running text retry for the asset → `RecoveryConflict("operation_running")`. Otherwise it inserts a `running`
     `text_retry` row with the asset's `sha256`/`byte_size` as expected identity, the baseline id and its profile, and the old coverage.
   - `complete_text_retry(operation_id, extraction, chunker, *, input_observation_id) -> dict`: a completed operation returns its stored result
     (no write). `extraction` must be a plain text-layer read (`ocr is None`, `math is None`, `profile_of(extraction.extraction_version) ==
     extraction.extraction_version`), else `ValueError`. Inside **one** `transaction()` (no parsing, hashing or `await` inside; the caller passes an
     already parsed `pdf.Extraction`): re-read operation (must be `running`), asset, current extraction, memberships and runs. Refusals complete the
     operation with `outcome = 'refused'` and a reason and write **no** extraction row or passage: `asset_removed`, `asset_replaced` (asset hash
     differs from the operation's expected hash), `baseline_changed`, `run_active`, `input_not_verified` (the observation is missing, not
     `kind = 'extraction_input'`, not `verified`, or its expected hash/size differ from the operation's). Otherwise apply `decide`; write the
     candidate occurrence `occurrence(profile, operation_id)` through `_write_extraction` with `recovery_operation_id`, `baseline_extraction_id`,
     `input_observation_id`, `diagnostic_only`, `decision_code`, outcome `current` (promotion: the exact baseline row becomes `superseded` first and
     the asset's four mirrored fields take the new row's values) or `rejected` (`rejection_reason` a short human sentence naming the code; the head and
     the asset row unchanged); complete the operation (`promoted`, `diagnosis_updated`, `rejected` or `no_change`, the decision code, both coverage
     JSONs with the missing pages) and write one event `asset_text_retried` per research holding the source, payload `{asset_id, source_version_id,
     operation_id, outcome, decision_code, extraction_version, baseline_extraction_id}` (also for `refused`). The return value is the completed
     operation as a dict plus `extraction_id` (NULL when refused). No event uses `asset_reextracted`. The event has no UI label yet (R4); say so.
   - `reserve_text_retry` and `complete_text_retry` are two calls so R2a can parse between them under its file lock; R1 adds no lock, no hashing
     and no interruption handling (a `running` row left by a crash stays until R2c). Write that in the decision's Limits.
8. **Purge.** Replace the `DELETE FROM asset_extractions ...` line in both `purge_research` and `purge_sources` with one helper call that deletes,
   for the source's assets and in this order inside the existing transaction: extraction rows; then observations referenced only by the deleted
   rows (extraction `input_observation_id`, the deleted operations' observation columns, `operation_id`); then the operations. The helper detects a
   schema without the R1 tables or columns explicitly (look the names up in `sqlite_master`/`PRAGMA table_info`, as B1's `purge_owner_reviews`
   does) and never swallows another SQL error. `tests/test_migrations.py` near 116 must keep passing unchanged. A test purges a research whose only
   source has a promoted and a rejected recovery occurrence, a completed operation and observations, and asserts the rows are gone and `PRAGMA
   foreign_key_check` is empty; a second test shows a shared source (held by another research) keeps every recovery row, including an operation whose `research_id`
   names the purged research (the ID stays as historical text). Retained-file unlinking
   and the authorization trigger are R3.
9. **`api/app.py`: only the OCR endpoint `read_with_ocr` (near 1929-1944).** The label is `ocr.target_version(recovery.text_base(
   asset["extraction_version"]), status["version"], status["languages"])`; a current extraction that is `diagnostic_only` with
   `error == pdf.ERROR_PASSWORD` is refused with 422 "This PDF requires a password; OCR cannot read it" before the Tesseract check. Nothing else in
   `app.py` changes (the extraction endpoint and every upload path stay for R2a/R2b).
10. **`workflow/flow.py`: only the OCR merge step (near 2517-2525).** Before `ocr.merge`, set `base.extraction_version =
    recovery.text_base(<the asset's current extraction_version read at that moment>)`, so a merged OCR label carries the head's recovery token.
    Nothing else in `flow.py` changes.
11. **`workflow/equations.py`.** Decisions 2 and 4 plus: `_forget_failure` deletes only rows with `recovery_operation_id IS NULL` (it can never
    delete a recovery occurrence); the arXiv withdrawal in `workflow/store.py` (near 1376) restores the withdrawn row's recorded
    `baseline_extraction_id` when that row exists, is `superseded` and belongs to the asset, and falls back to today's query only for a row without a
    recorded baseline (legacy rows). Nothing else in the equation code changes.

## Tests that must fail on the old code, and regression guards

Name each test's role in your report: **red on old** (the assertion fails on `c3048f4` for the defect named), **guard** (passes on both) or
**new contract** (exercises a function or table that does not exist on `c3048f4`; its defect evidence is the paired red-on-old or guard assertion). The
orchestrator re-runs the red-on-old ones against a clean copy of `c3048f4`; for tests that call new functions only, the red-on-old evidence is the
paired defect assertion listed here, not the missing function.

- **T1** (store level). Seed a current `failed` extraction at today's profile with page count 0 and no passages (`add_asset_with_pages` with a
  failed `pdf.Extraction`), record a `verified` `extraction_input` observation, reserve, complete with a synthetic succeeded 3-page extraction:
  promoted `recovered_text`, new current version `EXTRACTION_VERSION+reextract-<op>`, profile `EXTRACTION_VERSION`, old row `superseded` and
  unchanged otherwise, asset mirrors updated, one event per research. Paired defect assertions (red on old is impossible, they document the
  defect; mark them guard): `reextract_asset(..., pdf.EXTRACTION_VERSION, ...)` on that seed returns `unchanged`; with a distinct version the
  ordinary rule rejects it for the page count.
- **T3**. Seed `partial` at today's profile with text on pages 1 and 2 of 3, cite a page-1 passage from an answer evidence link; retry with text on
  pages 1 to 3 and page 1's text identical: promoted `text_updated`; old passage ids, text, hashes, labels, offsets unchanged; the identical page-1
  chunk is a **new** passage under the new occurrence (not deduplicated into the old one); `Store.evidence_statuses` gives `text_superseded` for the
  old cited passage; the store's retrieval paths (`passages_for`, the search used by inspection, `has_pdf_text`, `asset_page_digest`) return only
  new-occurrence passages.
- **T4**. Seed legacy `no_text`, zero passages; candidate `failed` with `pdf.ERROR_PASSWORD`: current row `failed`, `diagnostic_only = 1`,
  `password_diagnosed`, operation `diagnosis_updated`, old row retained `superseded`, no passage written; the OCR endpoint now returns 422 for it.
  Repeat with an ordinary failure candidate (reject `candidate_failed`) and with a baseline that has passages (the password exception does not apply:
  reject `candidate_failed`). Also `no_text` → `no_text` with a different page count promotes `no_text_diagnosed`, and an identical one is
  `no_change`.
- **T5**. (a) **red on old:** ordinary `reextract_asset` with a candidate that has text on pages 2 and 3 where the current has pages 1 and 2 (same
  page count, same rank, same number of text pages) is rejected with `text_page_lost` now; on `c3048f4` it is promoted. (b) retry on a `partial`
  baseline with an OCR passage → `augmented_text_would_be_lost`, head unchanged. (c) baseline seeded with a `mismatch` input observation and text on
  pages 1-2 of 3; candidate 5 pages with text on 1-5 and a `verified` input → promoted `recovered_from_corrupt_input`. (d) the same with no
  baseline observation → `legacy_page_count_untrusted`; with a `verified` baseline observation → `page_count_changed`.
- **T6 subset that R1 owns**: two operations on one baseline in sequence (first rejected `candidate_failed`, second promoted) leave both
  occurrences and both operations; replaying `complete_text_retry` on a completed operation writes nothing; the same key with another fingerprint
  raises `RequestConflict`. (API-level T6 is R2a.)
- **Refusals** (each its own test): `baseline_changed` at reserve and at complete (the head moved between them through `reextract_asset`),
  `run_active` at complete (a run created in **another** research holding the source after the reserve), `asset_removed`, `asset_replaced`,
  `input_not_verified` (missing, `mismatch`, wrong kind, wrong expected hash), `NotRetryable` for `succeeded` and `pending`,
  `operation_running`; each leaves the head, the passages and the asset row byte-identical (row hashes) and writes no extraction row.
- **T10 (targeting)**. (a) **red on old:** seed a rejected OCR attempt at `B+ocr-...` (as `tests/test_ocr.py`/`tests/test_ocr_run.py` do), recover
  the asset to a `partial` head `B+reextract-rop_X` with image pages, then `POST .../ocr` returns 202 (on `c3048f4` the same seeded rejected row gives
  409; the paired assertion is the 409 on a non-recovered head, which stays); run the OCR run with the existing fake page reader and assert the new
  row is `B+reextract-rop_X+ocr-...`, profile `B+ocr-...`, `baseline_extraction_id` = the recovered head; a second request on that head is 409.
  (b) `equations.target_version`/`source_target_version` for a recovered head, an OCR-on-recovered head and a plain head (plain: byte-identical to
  today's values, asserted against the literal strings); `next_asset` selects a recovered `partial` head as pending even though a Marker row
  `B+marker-...` exists for the pre-recovery head, and does not select a Marker-read recovered head again. (c) the arXiv withdrawal restores the
  recorded baseline: build distinct timestamps `baseline.created_at < competitor.created_at <= source_row.created_at`, where the competitor is
  another `superseded` row of the asset that is not the source row's baseline; assert the restored row is the baseline (red on old: the old query
  selects the competitor; assert that too on the old code path by naming the competitor's id).
  (d) `_forget_failure` cannot delete a recovery row. (e) `complete_text_retry` calls no parser, OCR, Marker, source, provider or model:
  monkeypatch `pdf.extract_pdf`, `ocr.read_page`, the math reader and the equation service's read to raise, and complete a retry.
- **P8 B1 compatibility** (guards on landed B1 code, no edit of `workflow/review/*`): build an owner-review snapshot (B1's public builder, as
  `tests/test_review_stale.py` does) whose evidence is on the old occurrence, then: a promoted retry yields `extraction_changed` and
  `text_superseded` bound to that evidence; a rejected, `no_change` and refused retry yield neither; the manifest's `passage_extraction_id` for a
  passage of a recovery occurrence resolves to that occurrence's row; all B1 test files pass unchanged.
- **Migration, two kinds of test.** (1) **0064 → 0065 preservation** (pattern of `tests/test_review_migration.py`: copy only the R1 migration into a
  directory holding 0001-0064): a library at 0064 populated with assets, passages (text layer, OCR, Marker, latex source), extractions with
  `unknown`, OCR, Marker and source suffixes, rejected rows, owner-review rows and FTS content; after `migrate` returns `[66]`, no old column value
  of any table changed (row hashes over the pre-existing columns); every extraction's `extractor_profile` equals its version,
  `input_observation_id` is NULL, `diagnostic_only` 0; `sqlite_master` before/after differs by exactly the new tables, indexes and triggers, the
  recreated `passages_no_update` (assert its new SQL) and the changed `asset_extractions` DDL (assert it is the old DDL plus the six added column
  definitions and nothing else); `UNIQUE(asset_id, extraction_version)` and the one-current index still refuse duplicates; an FTS `MATCH` returns the
  same rowids; `PRAGMA integrity_check` ok and `foreign_key_check` empty; both new tables are `WITHOUT ROWID`; `PRAGMA foreign_key_list` matches the
  declared targets, and deferral (which that pragma does not report) is shown by the stored DDL text and by a transaction that deletes a referenced
  parent before its child and commits once both are gone. (2) **Historical upgrades** from 0026 (before `asset_extractions`) and 0053 (before the
  0054 passage rebuild) to the head: compare row data only (passage and extraction values, FTS rowids) plus the profile backfill and NULL
  observations; schema differences from the intervening migrations are expected there and not asserted. Every guard of decision 3 has a refusing test and, where it allows
  something, an allowing test (including the two outcome transitions and a `REPLACE` attempt on each new table with `recursive_triggers=OFF`).
  Each newly protected passage column has a refused update; a delete is still allowed.
- **Existing tests the migration breaks, smallest edit each:** `tests/test_migrations.py:670` (make the expected list the migration numbers ≥ 55
  found in the real migrations directory; *superseded in code-review round 1 by the gap-free rule: the literal list ending in 65*); `tests/test_lineage_view.py:479` (keep the
  post-snapshot change: drop `passages_no_update` in that test right before the update, with a comment that this is a deliberate synthetic tamper
  of an isolated library, as `tests/test_report_edit_check.py:301` does; do not move the change before the snapshot, that would make the test
  vacuous); `tests/test_report_edit_check.py:561`
  (pass `text_source` to `_insert_passage`); `tests/test_arxiv_source_route.py:337` (age the row without updating it, e.g. by moving the retry
  window, keeping the assertion); `tests/test_report_edit_check.py:301` and `:607` already drop the trigger: rerun them and leave them. Any other
  test that breaks: report it with the reason before editing it.

## Checks to run

Focused tests while building, then the whole suite inside your sandbox:
`PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest -q -p no:cacheprovider`. Tests that need sockets or process
listings fail in your sandbox; list them by name and compare with the baseline log's failure list; the orchestrator reruns the full suite outside
the sandbox. Then `git diff --check`. No web change: no build, lint or Playwright run.

## Report and records

Write `/tmp/reextract-r1-impl-report.md`: files changed, each decision's implementation with file:line, every test with its role (red on old /
guard / new contract; a new-contract test names its paired defect assertion or guard) and what it shows, existing tests changed and why, full-suite counts with the failure list, what you could not do. Draft the decision entry
at the top of `docs/decisions.md`, above D181: `## D190 — P9 re-extraction R1: a stored extraction has its own identity, a recovery attempt can be
stored beside the old one, and one tested rule decides which is current; nothing starts a recovery yet` with Status (accepted, implemented; writer
gpt-6.1-sol high; leave the reviewer line for the orchestrator), Date 2026-10-03, Context, Decision (the token placement of decision 2, the
migration number (0065 under the gap-free rule) and its guards, the policy table and vocabulary, the new `text_page_lost` rule on the ordinary path, the Store calls, the purge
order), Carried work (R2a: route, CLI, idempotent replay, file lock, hashing into an observation, membership checks, run reservation honoured by run
creation; R2b: `restore_file(op)`; R2c: interrupted `running` rows; R3: the shared B1/report evidence helper, cited-occurrence views, backup of
retained files, purge authorization trigger; R4: UI, the `asset_text_retried` label, `views.py:602`'s rejected-attempt list), Limits (no route, no
real PDF recovered, synthetic tests show workflow behavior only, a page set says nothing about the words on a page, `legacy_unknown` partial rows
with a changed page count stay unrecoverable, a crashed `running` operation stays until R2c). Do not edit `STATUS.md` (the orchestrator does).

## Do not

Add a route, a CLI option, a UI string, a file lock, file hashing or a parse inside the store; change a model contract, method file or StepInput;
change `views.py`, `ocr.py`, `pdf.py`, B1's code or any applied migration; rebuild `asset_extractions` or `passages`; remove
`UNIQUE(asset_id, extraction_version)`; reuse an existing occurrence label for a new attempt; delete or update an old passage or extraction row
outside the purge helper and the two outcome transitions; store "verified" for bytes nobody hashed.
