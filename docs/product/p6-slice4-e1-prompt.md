<!-- PLAN-REVIEW-ROUNDS: r1: hazır değil, 1 high (manifest omitted the claim-to-section relation) + 3 medium (base-equality test vs 878281f literals and correct callers, per-path effective_links proof, export base-version note and wording), all folded in; r2: hazır, 0 high -->

# Task: P6 slice 4, batch E1, the model-free check of an edited report (storage, current-text assembly mode, store action, API route, view and export sentence)

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-e1` (detached at `878281f`, main with D147). Read `AGENTS.md`,
`CLAUDE.md`, `docs/decisions.md` D147 (top), D112 (slice 4 small version) and D113 to D129 (slice 1 report), and
`docs/product/p6-slice4-editing-stale-measurement.md`: §0 (F2, F7, F8), §1, §2 ("Düzenlemeleri denetle"), §3 (S1, S2, S5), §4, §5 (the whole
rule table), §6 (the `report_edit_checks` bullet and the closing "no status table" line), §7 items 1, 3, 4, 5, §9 (the E1 rows and the Akış/API row), §11, §12,
§14 "E1". The note is in Turkish; this prompt is the binding English scope. Where the code differs from what this prompt says, report it.
Patterns to copy: `docs/product/p6-slice3-k1-prompt.md` (a sibling storage batch: migration with append-only table and purge-authorization
delete trigger, purge ordering in `Store.purge_research`, lifecycle and backup tests), migration `0056_report_claim_revisions.sql` and
`0057_report_review.sql`, `ReportStore.edit_claim`/`evidence_changes` in `workflow/report/store.py`, `workflow/report/assembly.py`
(the fourteen checks, `run_assembly_checks`), `workflow/views.py::report_view`, `workflow/report/export.py::to_markdown`, `api/app.py`
report routes, `tests/test_report_assembly.py` (the `report_with_sections` fixture), `tests/test_report_export.py`, `tests/test_report_api.py`.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted.
Do not invent; report what you could not find. **No model call, no provider call, no network, no measurement.** Do not touch `../DEIXIS`,
`../DEIXIS-k4` (a web UI batch for slice 3 runs there), `../DEIXIS-x0` (slice 5 export work), `.local/`, `TODO.md`, `.vscode/`,
`scripts/local_index.py`, `docs/product/sw-status.md`, ports 8765 and 8858-8864, or the live data directory. Backend tests need
`PYTHONPATH=backend:.` and `UV_CACHE_DIR=/tmp/deixis-uv-cache`. No `apps/web` change, no method file or contract schema change
(`skill_package_hash` stays as it is today; report its value before and after to prove it), no new model task. Keep edits in shared files
(`workflow/store.py`, `workflow/views.py`, `api/app.py`, `domain/contracts.py`, `workflow/report/store.py`, `workflow/report/assembly.py`)
small and local: other batches rebase over them.

## Why

Slice 1's report can be edited claim by claim (D112, D113), but the assembly rules read `report_claims.text`, which is the model's text, so the
screen and the export say "edited text was not checked again". E1 adds one read-only, model-free action "check edits": the assembly rules re-run
over the **current** (edited) claim text, the result is stored append-only with a fingerprint of everything the check read, and the view and
export say whether that stored result is current or historical. It never changes report status, `report_version`, section status, section
`validation` or the D118 `report_review`. It says nothing about whether a sentence is supported by its citations. Citation removal and the
effective citation set are E2; the screen is E3.

## What is and is not in code (checked on 878281f; re-check, do not assume)

- In code: migrations up to `0060_candidates.sql`; `report_claim_revisions` (0056: kinds `human_edit`/`human_restore`, `current_revision_id`,
  claim `version`), `ReportStore.edit_claim`, `claim_revisions`, `evidence_changes`; `assembly.run_assembly_checks` with fourteen `_check_*`
  functions reading `report_claims.text` through `_claims`/`_section_texts` and `report_citation_links` through `_links`/`_claim_depths`/
  inline SQL; `domain/contracts.limitations_claim_issues` (VIII number restatement, only in the section-writing validator);
  `report_view` (`edited_after_version`, `evidence_changes`, per-claim `revisions`, `model_text`, `edited`); `export.to_markdown`
  (the sentence "Edited by hand after version n; edited text was not checked again." and Turkish twin); `Store.purge_research` deleting
  `report_stale_acknowledgements`, claim revisions, links, refs, claims, phrase repairs, gaps, snapshot, sections, reports in that order.
- Not in code: `report_edit_checks`, any "current" assembly mode, `has_human_edits`, `edit_check` in the view, a check-edits route or
  `ReportStore.check_edits`, an effective-citation read point. Check, do not assume.
- `storage/backup.py` copies the whole SQLite file through the backup API, so a new table is covered; prove it with a test.

## Decisions (already taken; do not reopen)

1. **Migration**: one file, next number after the highest in `backend/deixis/storage/migrations/` (expected `0061_report_edit_checks.sql`;
   check at write time and report the number). Table `report_edit_checks`: `id TEXT PRIMARY KEY` (prefix `rec_`), `report_id TEXT NOT NULL
   REFERENCES reports(id)`, `checker_version TEXT NOT NULL`, `input_fingerprint TEXT NOT NULL` (sha256 hex), `result_json TEXT NOT NULL`,
   `created_at TEXT NOT NULL`, `UNIQUE (report_id, input_fingerprint)`. Append-only: `BEFORE UPDATE` trigger aborts; `BEFORE DELETE` aborts
   unless the owning report's research is in `research_purge_authorizations` (copy the 0056 shape for `report_stale_acknowledgements`).
   Never edit an applied migration. No other schema change. `PRAGMA foreign_key_check` empty and `foreign_keys` ON after migration.
2. **Base mode is untouched.** `run_assembly_checks(store, reports, report_id)` keeps its signature and its exact output, still reads
   `report_claims.text` and raw `report_citation_links`, and its existing callers (`workflow/report/sections.py` at the end of a report run, and `ReportStore.revert_repair`; `finalize` does not call it) are not changed. Current mode is a separate, explicitly chosen entry point in `assembly.py`
   (`run_current_checks(store, reports, report_id) -> dict`), implemented by threading a keyword-only `current: bool = False` (or an
   equivalent small mechanism) through the helpers and checks that differ. Before touching `assembly.py`, run base mode on representative fixtures (a clean report, one with errors, one with warnings, one with a malformed stored record) at `878281f` and paste the exact outputs into the new test as literals; the test compares base output after your change to those literals, and also shows base output is identical before and after claims are edited. The whole existing `tests/test_report_assembly.py`, `tests/test_report_flow.py` and `tests/test_report_review.py` pass unchanged.
3. **One effective-citation read point.** Add `ReportStore.effective_links(report_id) -> list[dict]` returning the rows `_links` returns today
   (`l.*`, `claim_key`, `section_id`; ordered by `rowid`). In E1 it returns **all** `report_citation_links` of the report (E2 will redefine it
   and nothing else). Every link read in current mode (bibliography, anchors, derived depth, gap bases VII cell links, equations, phrase
   frame one-source test) goes through it; current mode contains no other SQL over `report_citation_links`. `_claim_depths` in current mode
   derives depth from `effective_links` rows plus a `passages.kind` lookup rather than its own join. Tests: (a) monkeypatch `ReportStore.effective_links` to drop one link and show the current-mode result changes while base mode does not, in separate cases for each dependent path (bibliography, anchors, VII cell-link basis, equation origin, derived depth, one-source plural diagnostic); (b) a guard: run current mode with `conn.set_trace_callback` and fail if any SQL mentioning `report_citation_links` runs outside an `effective_links` call. Base queries stay raw; view and staleness reads are E2's.
4. **Current-mode rule coverage** (design §5; "edited claim" means `report_claims.current_revision_id IS NOT NULL`, its text is that
   revision's `text`; other claims use `report_claims.text`; the claim sets, keys, refs, paragraph, support_type, count/equation columns are
   always the stored ones because an edit changes none of them):
   - Read as base, unchanged: duplicate claim keys, body_refs, conflict links, corpus counts (II/VIII structural numbers).
   - Current text: glossary order (`_section_texts` uses current claim text; draft text of II/VIII stays), banned words (claim text only;
     headings, gap texts, insufficient-evidence reasons stay the model's), equations (`math_not_well_formed`, equation origin rules, the
     OCR/Marker warning), count fields (membership frozen, text integers compared as today).
   - **Count claims with no integer in the current text** (including a number written as a word): current mode must not treat that as a pass.
     It records a `skipped` entry rule `count_text_not_checked`, reason `no_integer_in_text`, for that claim, for every claim with `count_json`,
     edited or not. It is not an error and not clean.
   - Effective links: bibliography, anchors, derived strength and depth, gap bases (VII). Where depth cannot be computed because a derived-section
     claim or one of its body_ref claims has no effective link with a known depth, record a `skipped` entry rule `derived_depth_not_checked`,
     reason `no_citation_depth`, one per such claim; never a silent pass. Keep the existing derived support-strength comparison running.
   - Word budgets: for a section with at least one edited claim, recompute its word count as the sum of `len(text.split())` over its current
     claim texts plus the draft's `insufficient_evidence` reasons (the same formula as `sections._word_count`, which you may import or
     mirror; do not edit it) and compare to the frozen budget; sections with no edited claim use the stored `word_count` exactly as base. The
     total uses these values. Stored `word_count` is never written.
   - Phrase frames: for an edited claim the mandatory-frame and exception matching are not run (the claim is left out of the `fields` handed to
     `phrasing.flagged_sentences`) and one `skipped` entry rule `phrase_frames`, reason `human_text`, is recorded for it; the own-work phrase and
     plural-sources-for-one-source diagnostics run on its current text and effective links. Unedited claims behave exactly as base. Do not
     change `phrasing.py` or `phrasebank.py`.
   - VIII number restatement: edited claims of section `VIII` are checked with the number-restatement rule of
     `contracts.limitations_claim_issues` (digits outside an "item/öğe/madde N" reference). Factor the number test into a small reusable
     function in `domain/contracts.py` that `limitations_claim_issues` calls, with no behavior change there (existing tests prove it), and report
     item rule `limitations_number_restated`, section `VIII`, severity `error`.
   - Items carry `{rule, section_id, detail, severity}`; `severity` is `warning` when the detail starts with `WARNING:`, else `error`.
5. **Check result record** (`result_json`, version 1): `{"version": 1, "checker_version", "items": [...], "rules_run": [...], "skipped":
   [{rule, section_id, claim_key, reason}], "counts": {"errors", "warnings", "skipped", "edited_claims"}, "not_checked": ["semantic_support",
   "numbers_written_as_words", "passages"]}`. `rules_run` lists, in fixed order, the rule names that executed. Deterministic: sort items and
   skipped entries by a stable key so equal inputs give equal bytes. `CHECKER_VERSION` is a constant string (for example `"edit-check-1"`)
   in the new module; bumping it changes every fingerprint.
6. **Fingerprint** = sha256 of canonical JSON (`sort_keys`, compact separators, `ensure_ascii=False`) of a dependency manifest built in one
   function `edit_check.manifest(...)`, covering **every input class the check reads**: checker version; report language, plan, and the
   language fallback `store.scope(...)` supplies to phrase frames; snapshot content digest (no trigger protects `report_snapshot`, so hash it);
   per section: `section_id`, ordinal, `step_id`, digests of `draft_json` and `validation_json`, `word_count`, and the **selected step input**
   exactly as `assembly._section_payload` selects it (the latest `step_inputs` row for the section's `step_id`: row id and digest of
   `payload_json`; an explicit absent marker when none); per claim: id, **owning section id (`report_section_id` and `section_id`; checks apply rules per section, so a claim moved between sections must change the fingerprint)**, `claim_key`, ordinal, paragraph, `support_type`, `table_ref`,
   `equation_ref`, `axis_id`, `count_json`, `equation_origin_json`, `current_revision_id`, digest of the effective text, sorted `body_ref`/`gap_ref`
   rows; every row `effective_links` returns (all columns); for every passage a link, an equation origin or a gap basis names: id,
   `source_version_id`, `kind`, `text_source`, digest of `text`; for every link `step_input_id`: step id and payload digest; for every
   cited `source_version_id`: title and `works.source_key` (bibliography rule); `report_gaps` rows (gap id, kind, text, basis, provenance);
   the latest `report_phrase_repairs` row per (section, sentence); a digest of the phrasebank text (`contracts._phrasebank_text()`). Missing
   inputs enter as an explicit absent marker, never as omission. Assume nothing is immutable. **Evaluation and insert happen in one
   `transaction(conn)`**, with the manifest, the check and the insert reading one consistent state (no `await`, no clock-dependent input in
   the manifest; `created_at` is not an input). Add a test that moving one claim to another section changes the fingerprint.
7. **`ReportStore.check_edits(research_id, report_id) -> dict`**: raises `NotFound` when the report is not in that research (404 at the
   route); `RevisionConflict` (409) unless the report status is `valid` or `draft` and its run finished (`completed`, `failed`, `cancelled`),
   as `edit_claim` demands. Builds the manifest and fingerprint; if a row for this report with this fingerprint exists, returns it and writes
   nothing (no row, no event, no `updated_at` change); otherwise runs `run_current_checks`, inserts the row, writes one `report_edits_checked`
   event in the same transaction, and returns the stored record. It **never** updates `reports` (status, `report_version`, `updated_at`,
   `review_json`), `report_sections` or any claim. Running it on a report with no human edits is allowed (it then checks the model text
   through the current-mode code; say so in the result via `counts.edited_claims = 0`).
8. **Current or historical.** `ReportStore.edit_check_state(report_id) -> dict | None`: `None` when no row exists; otherwise the row for the
   present fingerprint if it exists (`current: true`), else the latest row (`current: false`), shaped `{id, created_at, checker_version,
   current, errors, warnings, skipped, items, skipped_rules (the skipped entries), rules_run, not_checked, edited_claims}`. It rebuilds the
   manifest only when at least one row exists. No status table: "current" is derived at read time from the fingerprint.
9. **API**: `POST /api/researches/{research_id}/reports/{report_id}/check-edits`, no body, same CSRF rules as the other report mutations,
   returns `report_view(...)` (200). 404 for unknown or other-research report, 409 while the run is unfinished.
10. **View**: `report_view` gains `has_human_edits` (true when any claim revision exists, independent of `edited_after_version`, which stays as
    is and is still null on a draft report) and `edit_check` (the `edit_check_state` dict or `null`). Nothing else in the view changes; do
    not add the E2 fields. Compute `edit_check` only when the report has edits or has a stored row.
11. **Export**: replace the single "edited text was not checked again" paragraph with three states, keyed on `has_human_edits` (fall back to
    `edited_after_version is not None` for hand-built views without the new keys): no check -> exactly the current sentence when a version
    exists (keep the existing English and Turkish strings byte-identical; add an analogous no-version wording for a draft report, English and
    Turkish); current check -> "Edited by hand{ after version n}; the edited text was checked by code rules ({date}): {errors} errors, {warnings}
    warnings; whether the cited evidence supports each sentence was not checked." followed by a short list of the items and, under a "Not checked"
    line, the skipped rules; historical check -> the same with "the last check ({date}) does not cover the current inputs" (inputs may have changed through edits, passages, plan or checker version, not only edits) instead of the counts as current. Both checked states also print the `not_checked` limits (semantic support, numbers written as words, passages) in both languages. Where the D118 review note appears, add one clause that the review covers the model's base version and the human edits were not reviewed; the review record itself is unchanged. Turkish twins for each. Use `_md` for stored text.
12. **Lifecycle**: `Store.purge_research` deletes `report_edit_checks` for the research's reports before `DELETE FROM reports` (next to the
    `report_stale_acknowledgements` delete; its trigger needs the purge authorization already inserted there). Trash and restore of a research
    delete nothing. Backup and restore round-trip the rows identically.
13. **Decision record and note**: add `## D148 — ...` at the top of `docs/decisions.md` (re-check main's top number right before writing; if D148
    is taken use the next free) with Status/Date/Context/Decision/Evidence/Limits like D144 to D147; write what was built and what was not shown
    (no semantic support, no number-word check, real-corpus hit rate unmeasured, no model call). In
    `docs/product/p6-slice4-editing-stale-measurement.md` §14 mark E1 done (a "yapıldı (D148); commit: bu satırı ekleyen commit" note on the E1
    row and under the E1 heading). Do not touch other parts of the note.

## Files allowed

`backend/deixis/storage/migrations/00NN_report_edit_checks.sql` (new), `backend/deixis/workflow/report/edit_check.py` (new: constant,
manifest, fingerprint, result shaping, state), `backend/deixis/workflow/report/assembly.py`, `backend/deixis/workflow/report/store.py`,
`backend/deixis/workflow/store.py` (only the purge delete), `backend/deixis/workflow/views.py`, `backend/deixis/workflow/report/export.py`,
`backend/deixis/api/app.py`, `backend/deixis/domain/contracts.py` (only the reusable number test), `tests/test_report_edit_check.py` (new),
`tests/test_report_assembly.py`, `tests/test_report_api.py`, `tests/test_report_export.py`, `tests/test_backup.py`, `tests/test_corpus_removal.py`
or the existing test that purges a researched report (find it), `tests/test_migrations.py`, `docs/decisions.md`,
`docs/product/p6-slice4-editing-stale-measurement.md` (§14 only), `docs/product/p6-slice4-e1-prompt.md` (comment line only).

## Not allowed

`apps/web`, `methods/`, `contracts/`, `phrasing.py`, `phrasebank.py`, `sections.py`, migration `0056` or any applied migration, E2's
`link_count`/`request_hash`/revision-link tables, `edit_claim` changes (no `link_ids`, no idempotency change), a "Publish" action, a new
`report_version`, section rewrite, any model task, any change to base-mode behavior or to `finalize`/`revert_repair`.

## Tests to add (all synthetic, no model)

1. Migration: empty and populated library; `report_edit_checks` update refused, delete refused outside a research purge, allowed inside it;
   `foreign_key_check` empty.
2. Each current-mode rule on fixed cases: glossary order and banned word on an edited claim (S1); count number mismatch after editing 7 to 9
   (S2) and `count_text_not_checked` skipped when the integers are removed or written as words, and a clean count claim; derived-depth skipped;
   word budget recount of an edited section and unchanged stored count for an unedited one; equation malformed math after an edit; own-work and
   plural-source diagnostics on edited text while frames and exceptions are skipped for the edited claim and still run for an unedited one;
   VIII number restatement on an edited VIII claim; skipped entries are not counted as clean.
3. Base unchanged: same data, base output before edit equals base output after edit; existing assembly tests untouched and green.
4. Single read point: monkeypatched `effective_links` changes current-mode results only.
5. Fingerprint: same inputs give the same fingerprint; **one change in each input class gives a new fingerprint** (parametrized over claim
   revision, link row, passage text, snapshot content, section draft/validation, **selected section step input** changed on its own, gap
   row, phrase repair, plan, language fallback, checker version); a second request with equal inputs writes no second row and no event;
   a bumped checker version writes a new row.
6. State: no row gives `null`; check then edit makes the same row `current: false` and a fresh check writes a second row while the first stays;
   a check on an unedited report; `has_human_edits` true on a draft report whose `edited_after_version` is null.
7. Read-only: after a check the `reports` row (including `updated_at`, `status`, `report_version`, `review_json`), every `report_sections` row
   and every `report_claims` row are byte-identical to before.
8. API: unfinished run 409, other research 404, unknown report 404, CSRF required, view carries `has_human_edits`/`edit_check`, `skipped` listed.
9. Export: three states in English and Turkish; existing export tests pass unchanged.
10. Lifecycle: `purge_research` with a stored check succeeds and leaves no `report_edit_checks`; trash and restore keep it; backup and restore
    give identical rows.

## Checks to run

`PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest` over the touched test files while developing; the final full run is
done by the orchestrator. `git diff --check`. Report `skill_package_hash` before and after (must be equal).

## Report back

Files changed; the migration number; every own-judgement choice; anything in this prompt that did not match the code; open items for E2 to E4.
