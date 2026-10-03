# P9 re-extraction: closing record (R5, D208)

Date: 2026-10-03. Base: `dbec4fc` (origin/main after R4 `c94e954`, RF3 follow-up `414185f`, P8 B7 `dbec4fc`). Design: [p9-reextract-design.md](p9-reextract-design.md) (D176), row R5. Batches closed here: R1 D190, R2a D191, R2b D192, R2c D195, R3 D197, R4 D203.

This record states what was run and what the numbers are. All evidence is synthetic: temporary libraries, tiny generated PDFs, fake adapters, a scripted model. It says nothing about real libraries, real models or real providers.

## 1. Verdict

H7 finding 2 is closed for the explicit text-retry workflow (API, CLI and web button). Re-uploading a repaired file restores the bytes and leaves the stored text unchanged; a person then retries the text once per click, and a recovered extraction is stored beside the old one. A no-body extraction POST on a present same-profile file still answers `unchanged`, by design, and does not check the file's hash. Nothing here shows that a recovered text is complete or that a located anchor supports a claim.

No re-extraction regression was observed in the listed R5 checks, and no must-fix re-extraction implementation item was identified. Three optional follow-ups are named in section 6. This verdict closes re-extraction R5 only; the RR-B matrix pair, H10 and the owed measurements listed in STATUS.md are separate work and are not closed here. Windows behavior, power-loss durability and recovery on a real library are not shown.

The first R5 run, on `c94e954`, found one red browser test (`e2e/report.spec.ts:403`). It was stale after RF3 (D206), not a re-extraction regression, and `414185f` already fixed it. The full and compatibility pytest suites, the build, lint (`/tmp/r5/lint2.log`, exit 0, 16 warnings) and the browser checks were rerun on `dbec4fc`. The recovery-only run in section 2 is historical `c94e954` evidence.

## 2. Commands and counts (commit stated per result)

Python was the native arm64 venv (`platform.machine()` printed `arm64`). Tests build their own temporary data directories; nothing used `~/Library/Application Support/DEIXIS`, port 8765 or the live codex-home.

| Step | Command | Result |
|---|---|---|
| Full deterministic suite | `PYTHONPATH=backend:. .venv/bin/python -m pytest -q -p no:cacheprovider -rs` | 13,553 passed, 0 failed, 2 skipped, 62 warnings, 429 s. On `c94e954` the same command gave 13,550 passed, 2 skipped (twice). |
| Focused recovery and compatibility set | `PYTHONPATH=backend:. .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_reextract_*.py` plus the 26 files listed in section 3 | 2,009 passed, 0 failed, 60 warnings, 83 s (identical on `c94e954`). |
| Recovery files alone | `PYTHONPATH=backend:. .venv/bin/python -m pytest -q -p no:cacheprovider -n 0 tests/test_reextract_*.py` (22 files, on `c94e954`) | 866 passed, 6 warnings, 320 s. |
| Web build | `cd apps/web && npm ci && npm run build` | passes; the only output besides success is the large-chunk notice. |
| Web lint | `npm run lint` (oxlint) | exit 0, 16 warnings (`set-state-in-effect` and `only-export-components`; the same kind as before). |
| Browser acceptance | `DEIXIS_ACCEPTANCE_DIR=/tmp/r5/acc3 npx playwright test e2e/reextract.spec.ts e2e/a11y.spec.ts e2e/acceptance.spec.ts e2e/report.spec.ts e2e/lineage.spec.ts e2e/pdf-document.spec.ts e2e/waiting-pdf.spec.ts e2e/candidate-review.spec.ts`, under `/tmp/deixis-playwright.lock` | 101 passed, 0 failed, 8.6 min (reextract 1, a11y 38, acceptance 30, report 6, lineage 5, pdf-document 8, waiting-pdf 8, candidate-review 5). The suite has 212 tests in 24 files; the other 16 files were not run. |

Skips (both unchanged and unrelated to recovery): `tests/test_documents.py:232` and `tests/test_arxiv_source_archive.py:575`, F09 at the production limit (about 30 s each; run with `DEIXIS_P9_PRODUCTION_THRESHOLD=1`; not run here). Warnings: 62 pytest warnings, mainly SWIG `DeprecationWarning`s from the PDF library import. Baseline failures: none on this base. On `c94e954` one browser failure (above); also a first attempt of the focused command printed `no tests ran` because the shell did not split the file list, and was rerun correctly.

## 3. Compatibility files and the T-tests

The focused set is `tests/test_reextract_*.py` (22 files) plus: `test_source_versions`, `test_asset_replacement`, `test_evidence_status`, `test_ocr`, `test_ocr_run`, `test_equations`, `test_arxiv_source_route`, `test_arxiv_source_matching`, `test_person_reading`, `test_lineage_plan`, `test_lineage_flow`, `test_lineage_view`, `test_lineage_api`, `test_p9_faults_documents`, `test_p9_restore_matrix`, `test_p9_rr_a_storage`, `test_candidate_store`, `test_report_edit_check`, `test_p9_h7_torn_upload`, and the seven P8 B1 owner-review files (`test_review_contract`, `_migration`, `_snapshot`, `_store`, `_stale`, `_backup_purge`, `_separation`). This is the design's section 2.1 inventory, section 4.1 and R5 list. Three cited locations in the design point at a blank line or a fixture (`test_lineage_view.py:518`/`543`, `test_lineage_api.py:19`); the intended tests are at `:520`/`:545` and `test_lineage_api.py:186`/`196`.

T1 to T10 each have existing tests (names at `docs/product/p9-reextract-r*-prompt.md` and in the decision entries): T1 `test_reextract_r1_store.py::test_t1_*`, `test_reextract_r2a_api.py::test_t1_repaired_failed_same_profile_publishes_new_head_red_on_old`, `test_reextract_r2a_cli.py`; T2 `test_reextract_r2b_api.py`, `test_reextract_r2b_writers.py`; T3 `test_reextract_r1_store.py::test_t3_*`, `test_reextract_r2a_api.py::test_t3_*`; T4 `test_reextract_r1_store.py::test_t4_*`, `test_reextract_r1_policy.py`; T5 `test_reextract_r1_store.py::test_t5_*`; T6 `test_reextract_r1_store.py::test_t6_*`, `test_reextract_r2a_api.py::test_t6_*`; T7 `test_reextract_r2a_api.py`, `test_reextract_r2c_reconcile.py`, `_crashes.py`, `_limits.py`; T8 `test_reextract_r3_views.py`, `test_reextract_r3_guards.py`; T9 `test_reextract_r3_history.py`; T10 `test_reextract_r1_targeting.py::test_t10_*`, `test_reextract_r2a_api.py:465` and `:481`. B1 compatibility is also checked by `test_reextract_r1_targeting.py::test_b1_snapshot_retains_content_and_reports_only_promoted_extraction_staleness` and `test_reextract_r3_guards.py::test_s5_*`.

### T10 deviations (accepted, not closed)

- `test_reextract_r2a_api.py:481` (`test_later_d52_selection_after_partial_retry_is_separate_guard`) proves that the background selection picks the promoted asset. It stops at `next_asset` and does not run a fake background reader or assert that reader's own baseline and outcome. `test_reextract_r1_targeting.py:186` publishes through a direct Store call.
- `test_reextract_r2a_api.py:465` (named "fail-on-call") traps the OCR, Marker/equation and model fakes but installs no HTTP transport trap. Its name overstates it.

No runtime defect was found by reading either test; the design's full T10 assertion is simply not demonstrated.

## 4. Old-code failure evidence

Recorded in the decision entries by the reviewing session, on a clean copy of the previous commit. These are behavioral failures, not missing-module errors, except where noted.

| Batch | Old commit | Failing tests (count) | Where recorded |
|---|---|---|---|
| R1 | `c3048f4` | 3 (`test_reextract_r1_red_on_old.py`) | D190 |
| R2a | `2148c32` | 3 (T1, T3, removed-member final transaction) | D191 |
| R2b | `19d0a48` | 41 parameterized failures (T2 and writers) | D192 |
| R2c | `87cee0b` | 29 failures; the present-file and torn-file no-body guards pass on both | D195 (the implementer did not replay; the reviewer's record is used) |
| R3 | `af9a21e` | 22 failures; one earlier reproduction of the frozen-only case was invalid and was corrected | D197 |
| R4 | `03422d7` | 11 designated failures; two guards fail there only on a missing module; the browser spec was not run on old code | D203 |

The R5 batch did not re-run old code. Existing regression-only guards (healthy duplicate, no-change, foreign membership, limits, CSRF, rollback, old/new-schema refusal, T10's later D52 selection) are guards, not old-code defects.

## 5. H7 finding 2

The finding: a `failed` asset row for a torn file stays unusable after a new upload repaired the file; re-extraction answers `unchanged` (D165, D169, D176).

How it is closed, by layer: R1 gives each stored extraction its own occurrence identity and lets an empty failed or no-text head recover despite a changed page count, with the old occurrence kept (`workflow/recovery.py`, `store.py`). R2a adds the explicit API/CLI retry (`api/app.py` text-retry route, `workflow/text_retry.py`, `__main__.py`). R2b makes every PDF writer restore a damaged file through one `restore_file` with a receipt and retained bytes, and makes a same-hash Replace PDF return a file-only result. R2c reconciles interrupted operations without retrying text. R3 keeps old citations, reports and owner reviews on their own extraction and covers backup, restore and purge. R4 adds the one-click retry, history and the cited-extraction viewer. The end-to-end defect (seed a failed row, restore the file, retry, reopen the old citation) is exercised in `test_reextract_r2a_api.py::test_t1_*` and `e2e/reextract.spec.ts`.

What stays as it was: upload alone does not change stored text; the no-body same-profile POST still answers `unchanged` (`test_no_body_same_profile_failed_is_unchanged_guard`) and that answer does not mean the file is whole. Whether a real, torn library file recovers is not measured.

## 6. Open items

Items the earlier batches listed as "later" and that a later batch then built (locks, receipts, reconciliation, history, backup/purge, R4 controls) are not repeated. What remains is below. Classified jointly with gpt-6.1-sol medium (read-only); all are limits unless marked.

**Must-fix within the R5 re-extraction scope: none.**

**Optional follow-ups (named, not P10 blockers, not implemented here):**
- R5-F1, T10 coverage: execute a fake D52 background reader on a promoted asset and assert its own baseline and outcome; add the missing HTTP transport trap to the fail-on-call test.
- R5-F2, candidate and lineage views gain no occurrence or freshness fields (D197 waited for P8 B8a, which has landed as D185); Zotero per-item notes are English only.
- R5-F3, viewer and figure routes take no reader lock. Same-hash restoration does not invalidate cached figure descriptors (`api/app.py:2074-2095`), which remain until restart or eviction; PNG responses permit browser caching for one hour (`:2109-2110`). This is a presentation-integrity limit, not evidence of database damage (D195).

**Limits on what is demonstrated**
- Synthetic PDFs, stores and scripted model only; no real library, provider or model call; page coverage does not establish word preservation or scientific support.
- Windows locking is implemented but untested. Power-loss recovery and filesystem durability are not shown (macOS child kills only; ENOSPC injected, SQLite-full real). Advisory locks stop no outside process.
- A restored file, a promoted extraction or a located anchor validates no claim. `input_relation` compares the recorded parser input with the recorded hash, not the file served now.

**Limits in recovery behavior**
- Legacy inputs are NULL and are never backfilled; OCR, Marker and arXiv-source reads record no input observation; pre-0066 libraries and non-hexadecimal hashes parse without observations, and a pre-0066 library gets no recovery UI.
- A legacy extraction with passages cannot recover when the candidate's page count changes. A rejected OCR configuration can block the same configuration inside a recovered lineage after Marker promotion. Ordinary tool promotion can lose existing augmentation when page coverage survives (old occurrences survive, but current retrieval can lose content).
- No automatic retry and no force switch; reconciliation never parses text or completes a restore. An interruption reason held in one process can later read `process_ended`. Long Marker or arXiv reads block retries with 409; a restore waits ten seconds before 409; an independent D52 read can move the baseline during a retry (`baseline_changed`).
- A password-protected head has no retry button (POST and CLI still accept). A running retry has no polling. The latest-restore lookup scans per asset without an index. Matched or acquired candidate confirmation returns no receipt (it is in events and history).
- Table evidence payloads gain no occurrence fields; their existing evidence-status fields remain. Abandoned private copies are swept only by later verified reads or fresh retries; replay and dry run never sweep them.
- Superseded citations withhold figures from the present file; "Show current text" has no anchor marks.

**Limits in retention and purge**
- Backup leaves out unreferenced retained files, `.part` staging files and private copies, and can fail behind a long equation read (ten-second lock wait). `.part` files and abandoned private copies are not cleaned at startup or by purge.
- Reconciliation leaves a running retry that already owns an extraction unresolved and logs the inconsistent state (`workflow/reconcile.py:32-34`); lock or storage failures can also leave operations running and purge blocked. A crashed `running` operation blocks purge until reconciliation; frozen model-input references can stop a source-only purge; purge runs synchronously in the write transaction (one synthetic timing, no latency guarantee). Unreadable report snapshots or gap bases still break existing views and exports.
