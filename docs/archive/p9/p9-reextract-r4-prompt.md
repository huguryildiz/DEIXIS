<!-- PLAN-REVIEW-ROUNDS: r1 (gpt-6.1-sol medium): düzeltmeyle hazır, 4 high + 7 medium + 1 low, all folded in; decisions 1, 2, 5, 10 agreed, 3 and 11 changed as Sol proposed ; r2: düzeltmeyle hazır, 1 high + 4 medium + 1 low, all folded in; r3: düzeltmeyle hazır, 0 high, 0 medium, 1 low, folded in by the orchestrator without a fourth round -->

# Task: P9 re-extraction batch R4, the text-retry action, recovery history, English/Turkish result copy and the cited-extraction viewer in the web app

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-reextract-r4`, detached at `03422d7` (origin/main with R1 = D190, R2a = D191,
R2b = D192, R2c = D195, R3 = D197, migration 0069). Design: `docs/product/p9-reextract-design.md`, accepted as D176. Read all of it;
sections 3.2, 3.3, 5.2, 6, 7, 9 (row R4) and 10 bind this batch. Also read `AGENTS.md`, `CLAUDE.md`, `.impeccable.md` (all of it,
before touching `apps/web`), D190, D191, D192, D195 and D197 in `docs/decisions.md` (their "Carried work" paragraphs list what R4
owes), `docs/archive/p9/p9-reextract-r3-prompt.md` (the previous batch prompt), `backend/deixis/workflow/text_retry.py`,
`backend/deixis/workflow/file_restore.py`, `backend/deixis/workflow/recovery.py`, the recovery parts of
`backend/deixis/workflow/store.py` (`text_retry_view` 1734, `file_restore_view` 1874, `latest_file_restore` 1887,
`_retry_baseline` 1940), `backend/deixis/workflow/views.py` (`occurrence_view` 984, `passage_view` 1024, the source asset dict at 602),
`backend/deixis/workflow/report/passage_freshness.py`, `tests/acceptance/fixture_server.py`, `apps/web/e2e/report.spec.ts` (fixture
server start, research setup) and `apps/web/e2e/a11y.spec.ts` (how axe is called; do not edit it). Venv: `.venv` is a symlink to the main
checkout's arm64 venv; `apps/web/node_modules` is installed (`npm ci` ran). Run tests with
`PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest ...`.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted. No real-model
call, no provider call, no network. Do not touch `../DEIXIS*` worktrees, `TODO.md`, `.vscode/`, `scripts/local_index.py`, the live service on
port 8765 or the live data directory. Your sandbox cannot bind sockets or run Chrome: write the Playwright spec and make it compile
(`npm run build` type-checks only `src`: `tsconfig.app.json:26` includes `src` alone, so add an e2e-specific check, for example
`npx tsc --noEmit --skipLibCheck --module esnext --moduleResolution bundler --target es2022 --types node e2e/reextract.spec.ts`, or a
small `tsconfig.e2e.json` used only for that command; never claim `tsconfig.app.json` covers `e2e/`), but the orchestrator runs it. Say in your report which checks you could not run.

**Files you may change:** `apps/web/src/**` (in `ResearchView.tsx` only: the upload handlers at `:286-289`, the replacement and
re-extraction handlers at `:316-327`, props and rendering for the recovery UI in the source row at `:1105-1130` (including the
rejected-extraction sentence at `:1112`, decision 4), and `describeEvent`; preserve the existing focus helpers and handlers, which X05
may be editing, and keep new focus behavior inside `TextRecovery`; put new UI in new components, decision 9), `apps/web/e2e/reextract.spec.ts`
(new) and, if you need one, `apps/web/tsconfig.e2e.json` (new), `.impeccable.md` (as "Report and records" says, nothing else),
`tests/acceptance/fixture_server.py` (decision 12: a new seed function, a new `--write-reextract-pdfs` option and its env switch; no
change to existing scripts or markers), `backend/deixis/workflow/recovery_view.py` (new, read-only), `backend/deixis/workflow/views.py`
(only the source asset dict at 602, decision 1), `backend/deixis/api/app.py` (only the GET `text-retry` route at 2228-2260 and one new
GET route, decisions 1-3), `backend/deixis/workflow/store.py` (only adding `"read_equations"` to `STEP_OUTPUT_KINDS` at `:37`,
decision 8), new `tests/test_reextract_r4_*.py` files. **Do not edit:** `docs/decisions.md`, `STATUS.md` (the orchestrator
writes them), `apps/web/e2e/a11y.spec.ts` and any other existing spec (another batch, X05, edits the a11y spec and maybe ResearchView focus
code now), `backend/deixis/workflow/flow.py`, `backend/deixis/providers/*`, `backend/deixis/models/*`, watch/scheduler files (P8 B6),
any other line of `backend/deixis/workflow/store.py`, `text_retry.py`, `file_restore.py`, `recovery.py`, `reconcile.py`, `recovery_history.py`,
`evidence_deps.py`, `storage/*` (no migration: none is needed; if one truly is, stop and report), `contracts/`, `methods/`,
`backend/deixis/documents/*`, existing test files. If R4 truly needs a forbidden file, stop and report it. Do not invent; report what you
could not find, run or measure.

## Why

D190-D197 built the stored half of D176: a person can retry a failed or partial extraction through the API or CLI, every PDF writer
repairs a damaged file through `restore_file` with a receipt, crashed operations are reconciled, and an old citation can open its own
extraction with its recorded input stated. None of it is visible in the web app. A same-profile failed row still offers no action
(`ResearchView.tsx:1124` shows "Extract text again" only for an older profile), a same-hash Replace PDF that repairs a file is toasted as
"PDF replaced" (`ResearchView.tsx:321`), the two new events render as raw type names (`ResearchView.tsx:1235-1280`, `default` branch),
coded refusals have no Turkish text, an old citation still opens the current text of the page (`PassageSheet.tsx:84-90`, `.impeccable.md`
section 4.6 line 253), and the report shows no passage-freshness notice although the view already returns `passage_freshness`.
R4 is the interface batch. R5 closes the finding with the compatibility run.

## What is and is not in code (checked on 03422d7)

Backend, already there (use it, do not change its write behavior):

- `POST /api/researches/{rid}/sources/{svid}/assets/{aid}/extractions` (`app.py:2189-2226`). A body `TextRetryRequest` (`app.py:566`:
  `mode: "retry_failed_or_partial"`, `expected_current_extraction_id`, `idempotency_key` matching `^[A-Za-z0-9_-]{8,128}$`) runs one text
  retry and answers `{...research_view, "recovery": text_retry_view}`, 200 when completed or interrupted, 202 while a replay finds it
  running. Pre-reservation refusals: 404 `File missing` (no code; `text_retry.FileMissing`, `app.py:832`), 409 coded `request_conflict`,
  `baseline_changed`, `operation_running`, `operation_not_running` (`app.py:808-818`), `run_active` (`app.py:2202`), `file_busy`
  (`app.py:824`), 422 `not_retryable` with `reason` (`app.py:820`), 507/503 storage refusals (`db.describe_failure`). No body keeps the
  ordinary upgrade (`reextraction` result; 409 `input_not_verified` at `app.py:2219-2222` when the stored bytes do not match).
- `GET .../assets/{aid}/text-retry` (`app.py:2228-2260`): `current_extraction_id`, `status`, `extractor_profile`, `extraction_version`,
  `diagnostic_only`, `can_retry_text`, `reason` (blocker order: `no_current_extraction`, `already_current`, `pending`, `operation_running`,
  `run_active`, `file_missing`), `latest_operation` (a `text_retry_view`), `latest_file_restore` (a `file_restore_view` for the asset's hash).
  It flushes pending interruptions and otherwise writes nothing.
- `text_retry_view` (`store.py:1734`), closed fields: `operation_id`, `asset_id`, `lifecycle` (`running|completed|interrupted`), `outcome`
  (`promoted|diagnosis_updated|rejected|no_change|refused`), `reason` (refusals `store.py:31`: `asset_removed`, `no_holding_research`,
  `membership_changed`, `asset_replaced`, `baseline_changed`, `run_active`, `input_not_verified`, `file_missing`, `file_mismatch`;
  interruptions `store.py:33`: `storage_full`, `storage_unavailable`, `cancelled`, `unexpected_error`, `process_ended`), `decision_code`
  (`recovery.py:13`), `input_observation_id`, `input_integrity`, `candidate_status`, `extraction_id`, `extraction_version`,
  `baseline_extraction_id`, `coverage` (`old_text_pages`, `new_text_pages`, `missing_pages`), `created_at`, `finished_at`.
- `file_restore_view` (`store.py:1874`): `lifecycle`, `outcome` (`file_restored|file_reused|file_refused`), `reason` (`run_active`,
  `retention_conflict`, `file_not_regular`, or an interruption reason), `created_at`, `finished_at`, `operation_id`, `sha256`,
  `before_integrity`, `after_integrity`, `retained`. Upload, source upload, waiting upload and Replace PDF responses carry `file_restore`
  (or null) (`app.py:1660`, `1698`, `1805`, `2180`, `2187`); confirming a matched or acquired candidate returns only the research view (its
  receipt, if any, is recorded as an event and in history, not in the response; R4 does not change that write path); a same-hash Replace PDF of a damaged file answers 200 with
  the receipt and no `asset_replaced` (`app.py:2177-2180`); a whole same-hash file keeps 422 `SameFile`. Refused restores raise
  `FileRestoreRefused` → 409 with codes `run_active`, `retention_conflict`, `file_not_regular` (`app.py:828`, details at
  `file_restore.py:22`).
- Events (one per holding research): `asset_text_retried` (`store.py:1772-1781`: `asset_id`, `operation_id`, `lifecycle`, `outcome`,
  `reason`, `decision_code`, `extraction_version`, `baseline_extraction_id`, `source_version_id`) and `asset_file_restore_finished`
  (`store.py:1893-1904`: `operation_id`, `sha256`, `lifecycle`, `outcome`, `reason`, `before_integrity`, `after_integrity`, `retained`,
  `affected_asset_ids`).
- Passage view `occurrence` (`views.py:984-1021`, null for abstracts): `extraction_id`, `extraction_version`, `extractor_profile`, `outcome`,
  `is_current`, `current_extraction_id`, `input` (`observation_id`, `integrity`, `observed_sha256`) or null, `input_relation`
  (`input_matched_expected_hash|input_differed_from_expected_hash|input_not_recorded`), `retained_copy` (only on a mismatch),
  `file_restored_after`, `latest_file_restore`. `GET /api/researches/{rid}/assets/{aid}/text?extraction_id=...` (`app.py:2011-2057`)
  opens exactly a current or superseded occurrence and returns `occurrence` too; foreign or rejected IDs answer 404.
- The report view returns `passage_freshness` (`views.py:430`; shape at `report/passage_freshness.py:118-119`: `compared`,
  `semantic_support: "not_checked"`, `dependencies`, `affected` (`passage_id`, `source_version_id`, `evidence_status`,
  `passage_extraction_id`, `current_extraction_id`, `used_by`), `unresolved` (`passage_id` or null, `reason` `passage_missing|
  unreadable_record`, `used_by`), `file_restored_after` (passage IDs)). Export already writes the sentence (`report/export_text.py:183`).
- Purge routes answer 409 `{code: "frozen_dependency_unreadable", detail: "A stored model input, report snapshot or gap record could not
  be read, so nothing was deleted."}` (`app.py:1042`, `1625`; `recovery_history.py:19-21`).
- Equation reads answer `outcome: "file_busy"` with the unchanged state (`equations.py:337`, `519`); an in-run `read_equations` step then
  succeeds with that output (`flow.py:2698-2701`). Run-time fetch steps finish with `error_code` `fetch_file_repair_refused` or
  `fetch_file_busy` (`flow.py:2809`, `2852`), which `fetchReasonText` (`labels.ts:277-283`) shows as "connection failed".

Web, today:

- `api.ts:394` `Reextraction` and `api.ts:1117-1118` `reextractAsset` send the no-body POST only. No type for the retry request/result,
  the receipt, the capability, `occurrence` or `passage_freshness`. `Passage` (`api.ts:637`) and `AssetText` (`api.ts:395`) lack
  `occurrence`; `assetText` (`api.ts:1152`) takes no `extraction_id`.
- Coded refusals show `t(body.detail)` (`api.ts:997`), so a coded English sentence needs a Turkish entry in `i18n.ts` to be translated.
  None of the R2a-R3 sentences above has one (checked with `grep -F` on `i18n.ts`).
- `PassageSheet.tsx:80-95` opens a `current` or `text_superseded` PDF passage inside `api.assetText(researchId, p.asset_id)` (the current
  text) and `:151-155` says only "This passage comes from an earlier text extraction ({version})...". Every evidence surface opens this
  one sheet: answers (`ResearchView.tsx:639`), cells (`EvidenceTable.tsx:827`), lineage, the human queue, the Library and the Trash.
- `ReportView.tsx:298-303` shows `evidence_changes` only.
- No browser test touches re-extraction (`grep -ril reextract apps/web/e2e` is empty).

## Decisions taken where the design is open (use these; never ask)

**1. Capability in the source view (read-only).** New `backend/deixis/workflow/recovery_view.py` holds
`text_recovery(store, asset, source_version_id, papers_dir: Path | None) -> dict`, moved from the GET route body (`app.py:2231-2260`),
returning exactly the GET's current fields plus `file_checked: bool` and with the decision 2 reason. With `papers_dir=None` it skips the
file presence check (the POST still answers 404 for a missing file). The GET route calls it with `settings.papers_dir`; its existing values and blocker order are unchanged apart from decision 2. `views.py:602`
adds `"text_recovery": text_recovery(store, full_asset, svid, None)` to every in-use asset of a source row, computed inside the existing
read snapshot. The asset SELECT at `views.py:607-608` does not read `sha256` or `storage_path`, which `text_recovery` needs: load the
complete asset record internally (for example `store.asset(r["id"])`, or extend that internal SELECT) and pass it, while the public asset
projection stays exactly as it is (no `sha256`, `storage_path` or other new key besides `text_recovery`). `file_checked` is true only when
`precheck` actually ran: it is false for every DB-only summary and also in the GET when an earlier blocker returned before the file check.
It writes nothing; in particular the view never calls `flush_text_retry_interruptions` (the GET keeps doing so). No new index,
no new write.

**2. Password-protected heads are not offered a retry.** In `text_recovery`, after `pending` and before `operation_running`, a current
head whose `status == "failed"` and `error == pdf.ERROR_PASSWORD` gives `can_retry_text: false`, `reason: "password_protected"`. Same
bytes always fail again; the remedy is an unlocked copy through Replace PDF. The POST, the CLI and every write path keep accepting such a
request (no behavior change there; state it in a test). A legacy `no_text` head is still offered ("Check PDF text again", decision 5);
its retry is what can publish the `password_diagnosed` diagnosis.

**3. History route.** New `GET /api/researches/{rid}/sources/{svid}/assets/{aid}/recovery-history`, guarded exactly like the GET
`text-retry` route (`asset_in_use`), read-only, no flush. It returns `{"text_retries": [{"operation": text_retry_view, "candidate":
details | null}...], "file_restores": [file_restore_view...], "text_retries_truncated": bool, "file_restores_truncated": bool}`: this
asset's text-retry operations and the file-restore operations of its `sha256`, each newest first by `(created_at, id)`, at most 20 each
(read 21 to set the flag). `details` is a separate closed projection of the operation's own candidate extraction row (`asset_extractions`
with `recovery_operation_id` = the operation): exactly `extraction_id`, `extraction_version`, `extractor_profile`, `status`, `error`,
`page_count`, `outcome`, `decision_code`, `diagnostic_only`; null when the operation published no candidate. The existing serializers stay
unchanged. Nothing else is serialized: no paths, filenames, keys or fingerprints. The UI loads it when the history disclosure opens and
again after an action while it is open.

**4. The retry action.** A new `TextRecovery` component (decision 9) renders, per in-use asset of a source row whose `text_recovery`
has `status` in `failed|partial|no_text`, or has a `latest_operation` or `latest_file_restore`:
- one line with the latest recorded result (decision 6), from `latest_operation` and `latest_file_restore` (UI failures read the latest
  attempt as well as the head, so a rejected or interrupted retry never disappears behind an older success). Precedence by recorded
  time: if a file restore was created after the latest text operation was created (or there is no text operation), the line is the
  receipt sentence (its "Stored text has not been retried." is true because no later attempt exists); otherwise it is the text
  operation's sentence, preceded by "File restored." only when a `completed`/`file_restored` receipt finished before that operation was
  created. A running operation or restore is always the line. "Future work uses this extraction" is said only while the operation's
  `extraction_id` equals `text_recovery.current_extraction_id`; for an older promotion whose extraction is no longer current, say
  "This extraction became current; a later extraction is in use now.";
- the generic sentence at `ResearchView.tsx:1112` ("A later text extraction ({version}) was not used...") is not rendered when the
  rejected version contains `+reextract-` (a recovery candidate, `recovery.py:12`); the recovery line and history describe it instead, so
  it is not shown twice;
- the action button when `status` is `failed|partial|no_text`: label "Retry text extraction" (failed, partial) or "Check PDF text again"
  (`no_text`). When `can_retry_text` is false the button stays focusable with `aria-disabled="true"`, a Tooltip and an
  `aria-describedby` sr-only reason (the `.impeccable.md` 4.6 PDF-tab pattern), using the reason copy in decision 6. `already_current`
  and `password_protected` hide the button instead (nothing to retry; the password line names the remedy);
- a "Text recovery history" disclosure (decision 7).
Clicking sends `{mode: "retry_failed_or_partial", expected_current_extraction_id: text_recovery.current_extraction_id,
idempotency_key: crypto.randomUUID()}` (a fresh key per click; never re-send automatically). While the request is in flight the button
is `aria-disabled` with "Text retry is running…" in a `role=status` line beside it; focus stays on the button. A 202 (`lifecycle:
running`) keeps that state and reloads the view on the next research event (no new polling loop). After the response the view reloads
from the returned research view, the result line shows the stored outcome, and focus stays on the button or, if the button disappeared,
moves to the result line (`tabIndex=-1`). A toast repeats the result sentence (green only for `promoted` with `candidate_status:
succeeded`; amber for partial, diagnosis, rejected, no change, refused, interrupted). Errors before reservation show their translated
sentence in a `role=alert` line under the button (and an error toast), keep the button enabled, and reload the view for `baseline_changed`
and `operation_running`. The existing no-body "Extract text again" button for an older profile stays as it is. The OCR and
equation buttons are unchanged, except that the existing `ocrOffer` already returns null for a `failed` head, which must remain true
after a password diagnosis (assert it in the acceptance spec).

**5. File-restore receipts in the upload paths.** Every UI path that receives `file_restore` shows its receipt sentence (decision 6):
`api.upload` (`ResearchView.tsx:286`, `Home.tsx:276`), `uploadToSource` (`ResearchView.tsx:288`, `PdfReadiness.tsx:181`),
`attachWaiting` (`WaitingForPdf.tsx:91`) and `replaceAsset` (`ResearchView.tsx:316-322`). For Replace PDF, when the response carries
`file_restore` and the same asset ID is still the source's in-use asset, the result is file-only: the toast is the receipt sentence (once; it already
contains "Stored text has not been retried.") and never "PDF replaced". A receipt with `lifecycle` `interrupted`, or a 409 refusal, is amber/red with
its reason. Type the four responses with `file_restore: FileRestoreReceipt | null`.

**6. Copy.** All strings go through `t()` with Turkish entries in `i18n.ts`; mapping functions live in `labels.ts` (`textRetryResultText`,
`fileRestoreText`, `textRecoveryReasonText`, decision-code labels). Primary English copy, from design section 7 where it exists:

| Recorded state | English copy |
|---|---|
| `promoted`, candidate `succeeded` | "Text extracted again. Future work uses this extraction; earlier evidence keeps its cited text." |
| `promoted`, candidate `partial` | "Text extraction updated, but some pages still have no extracted text." plus "Pages with text: {pages}." from `coverage.new_text_pages` |
| `diagnosis_updated` + `password_diagnosed` | "This PDF requires a password. Text was not recovered. Replace it with an unlocked copy." (error tone) |
| `diagnosis_updated` + `no_text_diagnosed` | "PDF text checked again. No text was extracted." (it does not say the PDF has no text layer) |
| `rejected` + code | "Earlier text stays in use: {reason}." with a phrase per decision code (`candidate_failed` "the new read failed", `augmented_text_would_be_lost` "the new read would drop OCR, Marker or arXiv source text", `status_worse` "the new read is less complete", `page_count_changed` "the page count changed", `legacy_page_count_untrusted` "the page count changed and the earlier input was not recorded", `text_page_lost` "a page that had text would lose it", any other code: its name with spaces) |
| `no_change` | "No change to stored text." |
| `refused` + `file_mismatch` | "The stored PDF does not match its recorded hash. Upload the same PDF again to restore it, then retry." |
| `refused` + `file_missing` | "The stored PDF was missing when the retry looked for it. Upload the same PDF again to restore it, then retry." |
| `refused` + `input_not_verified` | "The bytes read could not be matched to the file's recorded hash, so no text was published." |
| `refused` + other reason | "Text retry refused: {reason}." (`run_active` "a research using this source has an active run", `baseline_changed` "the stored text changed first", `membership_changed` "this research no longer holds the source", `asset_removed`, `asset_replaced`, `no_holding_research` in plain words) |
| `interrupted` + reason | "Text retry was interrupted; no new extraction was published." plus the reason (`process_ended` "DEIXIS stopped before it finished", `storage_full` "the disk is full", `storage_unavailable` "storage could not be written", `cancelled` "it was cancelled", `unexpected_error` "an unexpected error") |
| receipt `file_restored` (result line) | "File restored. Stored text has not been retried." plus "The stored file was missing." (`before_integrity: missing`) or "The stored file was damaged; its damaged bytes are kept." / "...damaged." (`mismatch`, by `retained`) |
| receipt `file_reused` | "The stored file was already whole; nothing was rewritten." |
| receipt `file_refused` + reason | "File not restored: {reason}." (`run_active`, `retention_conflict`, `file_not_regular` in plain words) |
| receipt `interrupted` + reason | "File restore did not finish; upload the PDF again." plus the reason |

Add "File restored." before a `promoted` sentence only when `latest_file_restore` is `completed`/`file_restored` and finished before that
operation was created. Disabled-reason copy (`text_recovery.reason`): `operation_running` "A text retry is already running for this
PDF.", `run_active` "A research using this source has an active run; retry when it ends.", `pending` "This PDF is still being read.",
`file_missing` "The stored PDF is missing; upload it again to restore it.", `no_current_extraction` "No extraction is stored for this
PDF." Pre-reservation errors: the coded backend sentences; a 404 whose `detail` is exactly `File missing` → "The stored PDF is missing;
upload it again to restore it." (any other 404, such as "Source is not part of this research", keeps its own message); 422 `not_retryable` → "This extraction is not eligible for a text retry." Add Turkish entries for every coded English sentence
the R2a-R3 routes send, including `request_conflict`, `baseline_changed`, `operation_running`, `operation_not_running`, `run_active`
(both texts), `file_busy`, `not_retryable`, the no-body `input_not_verified`, the three `file_restore.DETAILS` and
`frozen_dependency_unreadable`. The Trash shows the purge refusal through its existing message path; check it reads in Turkish.
Never write "verified", "repaired text" or "recovered" for a diagnosis, refusal or file-only restore. Hashes are compared with the file's
recorded hash; never call that a scientific or bibliographic verification.

**7. History disclosure.** `<details>`-style disclosure (ChevronRight/ChevronDown, count in the summary, `aria-expanded` on a real button
or native `details`/`summary`), one list merged from both arrays newest first. Each entry: date (`uiLocale()`), kind ("Text retry" or
"File restore"), and what happened in that operation, in the past tense, never a present-state claim: a restore is "File restored; this
operation did not retry text." (plus the before-integrity sentence), "File was already whole; nothing was rewritten.", "File not
restored: {reason}.", "File restore did not finish: {reason}."; a text retry is "This extraction became current." (promoted),
"Diagnosis recorded: {password or no-text phrase}." (diagnosis), "Not used: {reason}." (rejected), "No change to stored text.",
"Refused: {reason}.", "Interrupted: {reason}; nothing was published."; for text retries also `candidate_status`, the candidate's
recorded `error` from `details`, and coverage ("Pages with text before: …; after: …";
"Not measured: whether the words match the PDF."). A "Details" disclosure inside each entry shows the candidate's extraction ID, extraction version (occurrence) and
extractor profile from `details`, input integrity and before/after integrity, in the system monospace stack. When a flag is true, say
"Latest 20 text retries shown." and/or "Latest 20 file restores shown.". No
progress percentage anywhere.

**8. Events.** `describeEvent` (`ResearchView.tsx:1235`) gains `asset_text_retried` (icon `ScanText`, text "PDF text retried", chips: the
outcome as "in use" ok / "diagnosis" warn / "not used" warn / "no change" neutral / "refused" warn / "interrupted" warn, and the reason or
decision-code phrase) and `asset_file_restore_finished` (icon `FileCheck` or `ShieldCheck` from lucide, text "PDF file restore", chips: the
outcome, "damaged bytes kept" when `retained`, "{n} PDF records share this file" when `affected_asset_ids.length > 1`). `fetchReasonText`
(`labels.ts:277`) gains `fetch_file_repair_refused` "the stored file could not be repaired now" and `fetch_file_busy` "the stored file was
busy". The `read_equations` step output is not public today (`store.py:37-40`, `1148`) and the transcript assigns that step no phase
(`Transcript.tsx:52-77`). Add `"read_equations"` to `STEP_OUTPUT_KINDS` (its output is `{asset_id, ...equation_state}`: small counts
and page lists, no model prose) and, in the transcript of a run, render one quiet line "PDF busy; equations of {n} PDF(s) were not read
in this run." only when at least one of its `read_equations` steps has `output.outcome === "file_busy"`; runs without such a step look
exactly as before (do not assign the step a phase). Add a pytest that seeds a succeeded `read_equations` step with that output and
checks `run_steps` carries it.

**9. Component placement.** New files: `apps/web/src/TextRecovery.tsx` (row action, result line, history) and, if useful,
`apps/web/src/occurrence.tsx` (occurrence notice and text toggle). `ResearchView.tsx` changes only: the upload handlers at `:286-289`
(receipts), the replacement and re-extraction handlers at `:316-327`, recovery props and rendering in the source row at `:1105-1130`
(including the sentence at `:1112`), and `describeEvent`. Preserve X05's focus helpers and handlers; recovery focus behavior lives in
`TextRecovery`.
Reuse `Notice`, `Tooltip`, `Button`, existing classes and tokens; new CSS goes in `workspace.css` with editorial tokens only, both themes,
no literal colors, no shadows on in-flow content, labels sentence case.

**10. The cited-extraction viewer (PassageSheet).** Every PDF passage that today opens inside its document (`evidence_status` `current` or
`text_superseded`, `PassageSheet.tsx:85`) loads that document as `api.assetText(researchId, assetId, occurrence.extraction_id)` (add the
optional parameter to `api.assetText`), **also when the occurrence is current**, and uses the response only when its
`occurrence.extraction_id` equals the passage's; otherwise, on a 404, or when the passage's `occurrence.extraction_id` is null, it shows
the single-passage view with the stored passage text, never the current text. This removes the race in which a promotion between the
passage request and a parameterless document request showed newer text as "Cited text". The parameterless request remains only for the
explicit current-text comparison below and for opening a source or asset without a cited passage. For a non-current occurrence
(`occurrence.is_current` false, `evidence_status === "text_superseded"`) the sheet thus opens the **cited extraction's** stored text on
the cited page, with the existing strip ("Cited text · PDF p. N", "Go to cited text") and the existing anchor marking. A "Show current text" action (a button in the occurrence notice) switches the document to `api.assetText(researchId,
assetId)` (current); in that mode the strip reads "Current text · PDF p. N · not the cited extraction", **no anchor is marked** and the
cited-page tint is not applied, and the action reads "Back to cited text". The occurrence notice replaces the single sentence at
`PassageSheet.tsx:155` and states, from recorded fields only:
- "This passage comes from an earlier text extraction ({version}). New answers and cells read the current extraction."
- the input relation: `input_matched_expected_hash` "This text was read from bytes matching the file's recorded hash.";
  `input_differed_from_expected_hash` "This text was read from bytes that differed from the file's recorded hash." plus "Those bytes are
  kept." or "Those bytes were not kept." (`retained_copy`); `input_not_recorded` "Which bytes this text was read from was not recorded.";
- when `file_restored_after`: "The PDF file was restored after this text was extracted."
The PDF tab shows one line above the viewer for a non-current cited occurrence, for any passage whose
`occurrence.file_restored_after` is true, and for any passage whose `input_relation` is not `input_matched_expected_hash`: "The PDF
shown is the stored file{, restored after this text was extracted}. It is not necessarily the bytes this text was read from." The input
relation compares the recorded parser input with the file's recorded (expected) hash; it never checks the file served now, and no copy
may say or imply that it does. Figures cut from the PDF (`PdfTextDocument`) come from the stored
file: in the cited non-current view pass a prop that suppresses figure pictures and shows their captions with "Figure picture not shown:
it would be cut from the current file, not the cited extraction." Current passages keep today's behavior except for the PDF-tab line under the conditions above;
abstracts keep today's behavior exactly.
Add `occurrence` to the `Passage` and `AssetText` types.

**11. Report passage freshness.** `ReportView.tsx` shows, beside the existing evidence-change notice, one `<Notice
tone="attention">` when `affected` or `unresolved` is non-empty and one `<Notice tone="info">` when `file_restored_after` is non-empty
(both may appear; a restore-only report gets only the second). The first counts `affected` by `evidence_status`: "Passage freshness
compared: {a} passages this report used are no longer the current text of their PDF{, {b} come from a replaced PDF}{, {c} from a removed
PDF}{; {k} references could not be resolved}. Semantic support not checked." (`text_superseded` → a, `pdf_replaced` → b,
`pdf_removed` → c; omit zero parts; plural forms through `t()`). The second: "{n} passages this report used were extracted before their
PDF file was restored. The restored file is not necessarily the bytes they were read from." No per-claim marking, no change to
`evidence_changes` handling, report text or acknowledgements. Add the `passage_freshness` type.

**12. Fixture seed (`tests/acceptance/fixture_server.py`).** With `DEIXIS_FIXTURE_REEXTRACT=on`, `seed_reextract(data_dir)` runs before
`create_app` (like `seed_stored_legacy`) and creates, through `Store` methods only (no raw SQL except what an existing helper in this
file already does), one research "SYNTHETIC re-extraction research" with `source_scope="attached"`, question in English, and three
uploaded sources with deterministic titles:
- **S1 "SYNTHETIC failed read"** (the existing-failed-row defect): true PDF `P1` (2 pages of SYNTHETIC text); its asset's current
  extraction is the result of `pdf.extract_pdf` on a truncated copy of `P1` (expect `failed`, zero passages; if the parser does not
  fail on the truncation you pick, craft `Extraction(status="failed", page_count=0, error=...)` with a real parser error string), at
  `pdf.EXTRACTION_VERSION`, with no input observation (legacy); the stored file `papers/<sha(P1)>.pdf` holds the truncated bytes. Add one
  earlier text-retry operation on S1 that ended `interrupted/process_ended` (reserve through the Store, then `interrupt_text_retry`;
  release any lock), so history and the result line show an interruption.
- **S2 "SYNTHETIC partial legacy read"**: true PDF `P2` with page 1 text `NEW1` and page 2 text `NEW2`; current extraction crafted as
  `Extraction(status="partial", page_count=2, pages=[PageText(1, "1", OLD1)])` where `OLD1` shares a cited sentence with `NEW1` but has
  a distinguishable extra marker phrase (for example "SYNTHETIC earlier reading"), at `pdf.EXTRACTION_VERSION`, no input observation; the
  stored file holds truncated `P2` bytes. A retry after restore must give `promoted`/`text_updated`; check it with `recovery.decide` in
  a pytest.
- **S3 "SYNTHETIC locked PDF"**: a user-password-encrypted one-page PDF stored whole under its true hash; current extraction legacy
  `Extraction(status="no_text", page_count=1)`, zero passages. A retry must give `diagnosis_updated`/`password_diagnosed`.
S2 is included; S1 and S3 stay undecided so the answer, table and report read S2 only (if the answer or table flow still reads
undecided sources, put S1 and S3 in a second seeded research and say so). `--write-reextract-pdfs DIR` writes `P1.pdf`, `P2.pdf` (the
true bytes the spec uploads to restore) and exits, like the existing `--write-*` options. Encrypted bytes come from PyMuPDF
(`tobytes(encryption=..., user_pw=...)`, as `tests/test_p9_faults_documents.py:42` does). Nothing else in the fixture changes.

**13. Acceptance spec `apps/web/e2e/reextract.spec.ts`** (port 8870, its own temporary data dir, its own `DEIXIS_ACCEPTANCE_DIR`
subfolder for screenshots, the `ReportServer`-style start/stop of `report.spec.ts`). Each UI step is followed by an API assertion of
the persisted state through an `APIRequestContext` with the CSRF header (backend record assertions accompany screenshots):
1. Open the seeded research, Sources tab: S1 shows the failed text, "Retry text extraction" and the interrupted result line; S2 shows
   "Retry text extraction"; S3 shows "Check PDF text again". Desktop 1280 light screenshot.
2. Through the UI, generate the answer, add one column and fill it, write the report (as `report.spec.ts` does). Read the answer's
   cited passage ID(s), a cell evidence passage ID and a report citation passage ID through the API; assert they are S2 page-1 passages
   whose `occurrence.is_current` is true.
3. Retry S2 before any restore: the result line shows the `file_mismatch` refusal sentence; the API shows `latest_operation` with
   `lifecycle: completed`, `outcome: refused`, `reason: file_mismatch`, `decision_code: input_not_verified`, `input_integrity:
   mismatch`, and an unchanged `current_extraction_id`.
4. Replace PDF on S2 with `P2.pdf` (through the existing Replace dialog): the toast and result line show "File restored. Stored text has
   not been retried." and no "PDF replaced"; the API shows `latest_file_restore` `completed/file_restored`, `before_integrity: mismatch`,
   `retained: true`, the same in-use asset ID, `current_extraction_id` unchanged, and an `asset_file_restore_finished` event.
5. Retry S2: "File restored." + "Text extracted again. ..." visible; the API shows `promoted`/`text_updated`, a new
   `current_extraction_id`, the step-2 passages now `evidence_status: text_superseded` with `occurrence.is_current: false`, and an
   `asset_text_retried` event.
6. S1: Replace PDF with `P1.pdf` → receipt; retry → `promoted`/`recovered_text` in UI and API (the failed row is recovered).
7. S3: "Check PDF text again" → the password sentence; the API shows `diagnosis_updated`/`password_diagnosed`, `diagnostic_only: true`,
   `text_recovery.reason: password_protected`; the S3 row has no retry button, no OCR button, and no "Text extracted again" anywhere in it.
8. Reopen the answer citation: the sheet shows `OLD1`'s marker phrase with the anchor marked and does not contain `NEW2`; the occurrence
   notice shows the earlier-extraction, `input_not_recorded` and file-restored sentences; "Show current text" shows `NEW1` and `NEW2`
   with no `mark.citation-highlight` in the document; "Back to cited text" restores the marked cited view. PDF tab shows the
   stored-file line. Do the same, more briefly, from the cell panel's "Open in source" and from a report citation chip.
9. The report sheet shows the passage-freshness notice with the affected count the API's `passage_freshness.affected` gives.
10. S2's history disclosure (keyboard: Tab to its control, Enter) lists the refusal, the file restore and the promotion newest first;
    Details shows the occurrence version.
11. Activity tab: the two event kinds render their labels, not raw type names.
12. Simulated UI states, done between steps 2 and 3 while S2 still offers its retry (it disappears after promotion): with `page.route`
    on the S2 POST, fulfill 409 `file_busy`, 409 `run_active`, 409 `baseline_changed`, 422 `not_retryable`, a 404 `File missing` and 507
    with the app's storage-full body (read its shape from `db.describe_failure`): each shows its translated sentence in a `role=alert`, the
    button stays enabled and focused. After each mock, assert through the API that S2's `latest_operation`, `current_extraction_id` and
    the event count are unchanged; name these screenshots `reextract-simulated-*`. The running state: in a separate page (or the same page
    followed by `unroute` and a reload), fulfill one 202 with the complete envelope (a real research view fetched first, plus a `recovery`
    object carrying every `text_retry_view` field with `lifecycle: running`, null outcome and `finished_at`) for the running-state
    screenshot; no completion event follows, so discard that page (or reload) and wait for the real, enabled retry button before step 3.
    Keyboard: Tab reaches the retry button and Enter triggers it (the real step 3 retry is triggered this way).
    Race guard: in step 8, `page.waitForRequest` shows that the document request for the cited passage carries its `extraction_id`; also
    open one current cited passage before step 5 and assert the same. Simulated race (labelled simulated): with `page.route` on the
    document request of a cited passage, answer with a body whose `occurrence.extraction_id` differs from the passage's (for example the
    current text's response) and assert the sheet shows the stored single passage and none of that other text; and with a delayed
    document response, assert that the text shown is still the cited occurrence's after the view reloads mid-request.
13. Turkish: switch the UI to TR and check the result lines, history entries and the occurrence notice show Turkish text (no English
    sentence from decision 6 remains).
14. Screenshots at 1280 and 390 px, light and dark, of: the source rows with results, the open history, the cited view and the current
    view of the sheet, and the report notice (name them `reextract-<state>-<width>-<theme>.png`). Run `AxeBuilder` (`@axe-core/playwright`,
    as `a11y.spec.ts` does) on the source rows with history open and on the sheet in both modes, light and dark, at 1280 and 390; assert
    no violations. Repeat one sheet check with `reducedMotion: "reduce"` and assert the toggle and jump still work.

## Tests that must fail on the old code, and regression guards

Write them in new files `tests/test_reextract_r4_view.py` (and more `test_reextract_r4_*.py` if useful). Red-on-old tests (V1, V2's
capability part, V3, V6) must fail on a clean copy of `03422d7` at a behavioral assertion, not at an import of a new module: assert
through the HTTP routes and the research view first, and import a new module only after an HTTP assertion that shows the R4 behavior.

- V1: the research view's in-use asset carries `text_recovery` with the GET's values for a failed same-profile head (offered), a partial
  head (offered), a legacy `no_text` head (offered), a healthy head (`already_current`), a running operation and an active run, always
  with `file_checked: false`; the GET gives the same values, with `file_checked: false` for the early blockers (`already_current`,
  `pending`, `password_protected`, `operation_running`, `run_active`, `no_current_extraction`) and `file_checked: true` only where the
  precheck ran (offered heads and `file_missing` for a missing file). (Old: no key.)
- V2: a `failed`/`password-protected PDF` head: GET and view say `password_protected`; a POST with a valid body still runs and records
  its result (regression guard: the write path is unchanged).
- V3: the history route: newest first, both kinds, 20-item bound with the truncation flags (seed 21 each), closed fields only (each
  text-retry entry's keys are exactly `{operation, candidate}`; `operation` keys equal the unchanged `text_retry_view` keys; `candidate`
  is null or has exactly the nine decision 3 fields; file-restore entries' keys equal `file_restore_view` keys), 404 for a foreign research, a removed asset or another source's
  asset, and no writes (compare `total_changes`/row counts before and after). (Old: 404 route.)
- V4 (regression guard, passes on old code by design): the GET `text-retry` route returns its R2a-R2c values unchanged for the existing
  cases (run the existing R2a/R2b capability tests unchanged; they must pass).
- V6: a succeeded `read_equations` step with `output.outcome == "file_busy"` appears with its output in the research view's run steps.
  (Old: output null.)
- V5 (fixture guard, not red-on-old): `seed_reextract` builds the three sources as decision 12 states, and `recovery.decide` on S2's seeded baseline and a parse of `P2`
  gives `text_updated` with promotion, on S1's gives `recovered_text`, on S3's gives `password_diagnosed`; the stored files of S1 and S2 do
  not hash to their expected `sha256`.
- Browser: `reextract.spec.ts` fails on old code (no retry control); the orchestrator confirms that on a clean copy.
- Existing pytest and Playwright suites must still pass; you change no existing test.

## Checks to run

Run `PYTHONPATH=backend:. .venv/bin/python -m pytest -q tests/test_reextract_r4_*.py tests/test_reextract_r2a_api.py
tests/test_reextract_r2b_api.py tests/test_reextract_r3_*.py` and, if time allows, the full suite (socket/process tests fail inside your
sandbox; list them). `cd apps/web && npm run build && npm run lint` (no new lint warnings). Type-check `e2e/reextract.spec.ts`. `git diff
--check`. You cannot run Playwright; the orchestrator runs it under the shared lock.

## Report and records

Write `/tmp/reextract-r4-impl-report.md`: every decision above with file:line of the implementation; the copy table as implemented in
English and Turkish; tests added and their red-on-old reasoning; checks run and their counts; what you could not run; any deviation and
why. Do not write `docs/decisions.md` or `STATUS.md`. Update `.impeccable.md` only as follows: in section 4.6 replace "A passage from an
earlier extraction opens the current text of the same page." with the decision 10 rule (cited extraction's stored text; "Show current text"
comparison without marking; input-relation and restored-file notice; the PDF-tab line; figure pictures withheld in the cited non-current
view), and in section 4.5 add one bullet for the text-recovery line, action, disabled reasons and history (decisions 4, 6, 7). Keep the
guide's style (Rule/Current, sentence case); no other section changes.

## Do not

- Do not change any write path, refusal order, status code, event payload, migration, recovery policy or parser default.
- Do not add polling loops, progress percentages, a force switch, automatic retries or an automatic retry after upload.
- Do not mark or guess anchors in the current-text comparison; do not substitute the current page into the cited view; do not show the
  restored PDF as the verified input of old text.
- Do not add a UI dependency, literal colors, shadows on in-flow content, uppercase labels or new font sizes outside the scale.
- Do not claim that a restored file, a promoted extraction or a located anchor validates a claim; copy says what was compared.
