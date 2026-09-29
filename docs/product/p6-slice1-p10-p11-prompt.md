<!-- Plan review: gpt-6-sol high, one round (4 high: report anchors not located/stored as model text, TABLE I tied to table_ref, no cell-citing fixture claim, references of a removed source; 2 medium: display order, UI-level 409) — all folded in below. -->

# Task: P6 slice 1, batches P10 + P11 — the report on screen: write it, read it, edit a claim, see what changed

Repo: the git worktree you are started in (`-C`). All paths below are relative to it.

The owner wants a report visible and usable in the app. Today the report run is in code
(`backend/deixis/workflow/report/`, routes `POST/GET /api/researches/{id}/reports…` in `api/app.py`,
`views.py::report_view`) and slice 4 added claim editing and the "evidence changed after this report" marker
(D112, `p6-slice4-editing-stale-measurement.md` §0), but **`apps/web` has no report screen and no report types**.
This task builds the plan's 1h (P10) and 1i (P11) from `docs/product/p6-slice1-report-run.md` (lines ~2265–2410)
and the slice-4 UI items of `p6-slice4-editing-stale-measurement.md` §7 items 1 and 3 that §0 left for P11.

## What is and is not in code (checked 29 September 2026, on `4ae322b`)

- Done: the report run (plan, rounds A–D, code-written II, phrase repair = P8, budget = the "P9/P9.5" prompt
  files), assembly rules 1–4/7/10 (`assembly.py`), `report_view`, claim edit + history + 409, stale marker +
  acknowledgement (D112).
- **Not done** (handoff step list, `p6-slice1-handoff.md` ~line 285): P6 (VIII's numeric core), P7 (the other
  eight assembly rules), P9 (`report_review`; `run_report` ends with "Report review is added by 1f"), P12
  (Markdown export), P13–P16. None of these blocks a screen: the screen renders what the report stores. Because
  there is **no report review**, the screen must never say or suggest that a report was reviewed; its closing
  note says what was checked (structure, anchors located) and that semantic support and a claim review were not.
- Out of scope here: Markdown export/copy (P12), publish, section rewrite, removing citations from a claim
  (`keep_citations_from`), rewrite proposals, any model call, any migration, any contract/method change.

## Backend fix first: a report citation anchor must be located (fail closed)

Found in the plan review (Sol r1): `domain/contracts.py::_check_report_section` never checks that a
`citation_anchors[].quote` is found in its passage, and `report/sections.py::_citation_links` stores the
**model's** quote as `anchor_text` even when `locate_anchor` returned `None` (`anchor_match` NULL). A screen that
highlights `anchor_text` would then mark a guessed or unfound span, which `AGENTS.md` ("Citation integrity is
fail-closed") forbids. Fix it before the screen, mirroring the grounded-answer check (`contracts.py` ~1175):

- in `_check_report_section`, for each anchor with a `passage_id` in the allowlist, an `anchor_not_in_passage`
  issue when `locate_anchor(quote, passage text)` is `None`; for each anchor with a `cell_id`, an
  `anchor_not_in_cell_evidence` issue unless the quote is located in **one** of that cell's stored evidence
  quotes (`report_target.cells[].evidence[].quote`, each tried separately, never joined). Issues go through the
  existing bounded schema repair, so an unrepaired section fails as today; no new loop.
- in `_citation_links`, store the located, source-owned text (`match.text`) as `anchor_text` and its kind as
  `anchor_match`; for a cell anchor, locate against each evidence quote separately (same rule as above).
- tests: an unlocatable passage quote and an unlocatable cell quote each give the issue; a located quote stores
  the source's own words (e.g. a quote differing only in spacing/case stores the passage's spelling).
- `report_view` keeps returning `anchor_match`; the screen highlights only a link whose `anchor_match` is not
  null. Older stored reports may still hold NULL-match links: such a marker opens the passage **without** a mark
  and with the existing "not located" treatment (`PassageSheet` `expectHighlight`), never with a guessed mark.

This is the only change allowed in `sections.py` and `contracts.py`. Check `tests/fixtures/research/*` and
`tests/fakes.py` still produce locatable quotes; if a fixture breaks, fix the fixture's quote, not the check.

## Decisions taken for this task (the plan's text is the intent; these settle where it is unclear)

1. **Where the "fourth state" lives.** `PdfReadiness` is shown only before the first answer and hides while a
   non-PDF run is active, so a user who already has an answer would never see "Write report". Put the fourth
   state in a **new component** `apps/web/src/report/ReportReadiness.tsx`, rendered on the Answer tab under the
   answer/actions area (after `PdfReadiness` or `answer-actions`, whichever renders), whenever the research has at
   least one evidence table with at least one column. It reuses the `.pdf-ready` styles and the `Depth` layout
   (export `Depth` from `PdfReadiness.tsx` rather than copying it). `PdfReadiness` itself is not changed. States:
   - a `table_fill` run of one of these tables is `queued`/`running`/`pause_requested`/`paused` →
     "Filling the evidence table" / "Table fill paused", `Depth` of cells filled / cells left, a bar, Pause/Resume
     (`api.controlRun`, same pattern as `PdfReadiness` state 2), and a text link "Open the table" to the
     Evidence tab;
   - else a `report` run is active or paused → nothing here (the timeline row and the report card show it);
   - else at least one table is ready (below) → the primary button **"Write report"** (with the table's title
     when the research has more than one table: one button per ready table, or a `Select` of ready tables plus
     one button; choose the smaller one and say which), one line under it: "Writes a sectioned report from
     “{table}” and its quotes. Up to {n} model calls." Only if you can read the number from the backend; otherwise
     leave the call count out rather than computing it in the client;
   - else → one quiet line: "A report needs a filled evidence table: {n} cells left in “{table}”." plus the link.
   The Evidence tab's toolbar gets the same "Write report" action (`variant="outline"`), enabled only when that
   table is ready and no run is active, otherwise disabled **with its reason** visible in a `title` and an
   accessible description (`.impeccable.md` §5: a disabled control has a visible or accessible reason).
   Starting a report calls `POST /api/researches/{id}/reports` with `{table_id}` and a fresh `Idempotency-Key`
   (`crypto.randomUUID()`), then refreshes the research view.
2. **Readiness comes from the backend, not the client.** Add to each item of `TableStore.tables()` (the
   `GET …/tables` list) a `report_ready` object computed with the existing `tables.report_ready(store,
   research_id, table_id)` (no `continue_with_failed`): `{"ready": bool, "cells_left": len(missing),
   "cells_total": included_sources × active target columns, "failed_rows": len(failed_rows)}`. Name it honestly:
   `cells_left` counts included-source × column pairs without a terminal value, exactly `report_ready`'s rule.
   Add a pytest for it (ready false with an empty column, true after filling, `failed_rows` counted).
3. **Report card on the Answer tab.** For each `view.reportRuns` entry (newest first; show the newest, and older
   ones on the Artifacts tab list next to the answer reports) render a card with the existing `.report-artifact`
   pattern, labelled **"Evidence report"** so it cannot be confused with the answer's own "Report · VN" card:
   meta line "Evidence report · V{n}" for a `valid` report, "Evidence report · draft" for `draft`,
   "Evidence report · being written" while `in_progress`. The card opens the report sheet. While the report run
   is active the card says so with `role=status` text; the section progress itself is in the timeline.
4. **Report sheet.** `apps/web/src/report/ReportView.tsx`, opened in a `Sheet` with the existing
   `detail-sheet report-sheet` classes and toolbar pattern (`AnswerBlock` in `ResearchView.tsx` is the model;
   do not change `AnswerBlock`). It fetches `GET …/reports/{id}` and refetches when `view.last_event_id`
   changes (drop responses for an older request, as `EvidenceTab` does). Contents, top to bottom:
   - toolbar: title, an **"Evidence view"** toggle (`aria-pressed`), nothing else (export is P12);
   - document head: "Evidence report · V{n}" or, for a draft, "DRAFT: {sections} not validated" and no version
     number (plan §2 decision 11); the research title (h1); the date; when `edited_after_version` is set, one
     line "Edited by hand after version {n}; edited text was not checked again." (§0 item 4b);
   - the report-level band when `evidence_changes.any`: `<Notice tone="attention">` "Evidence changed after this
     report: {changed_cells} cells changed, {removed_sources} sources left, {added_sources} added,
     {revised_columns} columns revised. The report text was not changed. Passage text was not checked." — only the
     non-zero parts, pluralised properly; the last sentence always (from `not_checked`);
   - sections in this **display order** (not `ORDINALS`, which puts `index_terms` last): Abstract, Index Terms,
     I, II, III, IV, V, VI, VII, VIII, IX, References; headings in the **report's language** (`report.language`, `tr` → Turkish,
     anything else → English; a small fixed map in the component, not `t()`, because the UI language and the
     report language can differ): Abstract, Index Terms, I. Introduction, II. Review Methodology, III. Background
     and Taxonomy, IV. Literature Synthesis, V. Comparative Findings, VI. Candidate Unanswered Aspects,
     VII. Future Directions, VIII. Limitations and Threats to Validity, IX. Conclusion, References (Turkish:
     Özet, Dizin Terimleri, Giriş, İnceleme Yöntemi, Arka Plan ve Sınıflandırma, Literatür Sentezi,
     Karşılaştırmalı Bulgular, Cevaplanmamış Yön Adayları, Gelecek Yönelimler, Sınırlılıklar ve Geçerlilik
     Tehditleri, Sonuç, Kaynaklar);
   - II renders `draft.text` as one paragraph (it has no claims); every other section groups its claims by
     `paragraph` (in claim order) into one `<p>` each, claims joined by a space, each claim's text through
     `MathText` (claim text may contain LaTeX), followed by its citation markers;
   - a section whose status is `draft` or `failed` shows the text line "This section was not validated and must
     be written again." (attention tone, not red), and its claims still render;
   - a section with no claims and no text shows its `insufficient_evidence` entries from `draft` if present
     ("Not enough evidence: {reason}"), else "No text was written for this section.";
   - VI starts with one fine-print line: "Candidate aspects the model inferred from the evidence table; none was
     checked by a kill-search." (plan §2 decision 1, §9);
   - IV: the evidence table is part of the report (design §2 decision 3), so IV always shows "TABLE I" when
     `table_i` is not null: after the paragraph holding the first claim whose `table_ref` is `TABLE_I`, or, when
     no claim carries that reference (the fake model never sets it), directly under IV's heading before its first
     paragraph. Caption: "TABLE I. Evidence table as frozen for this report ({rows} sources, {columns}
     columns)." Values are the frozen snapshot's (below); equations: a claim with `equation_ref` gets its printed number "(n)" right-aligned, numbered
     by first appearance of each distinct `equation_ref` across the report;
   - References: numbered list `[n] authors, title, venue, year` from `report.references` (below). A title is a
     button that opens `PassageSheet` **by passage id** on the entry's `open_passage_id` (below), which works even
     after the source left the research (`research_view.sources` no longer lists it, so opening by
     `sourceVersionId` would show nothing); an entry with `open_passage_id` null shows its title as plain text;
   - closing provenance line (when some link has `anchor_match` null, the first sentence becomes "{n} of {m}
     citation anchors were located in their passages or cells; the others open without a mark."): "Anchors were
     located in the cited passages or cells. Whether each passage supports
     its claim was not checked, and this report was not reviewed by a model or a person." with the model (icon +
     display name via `useModelText`/`ModelName`) that wrote it if the run's `requested_model` is available on the
     run in `view.runs`; otherwise leave the model out.
5. **Citations are IEEE numbers from the backend.** Extend `report_view` (backend) so the client does not number:
   - each claim gains `paragraph`, `table_ref`, `equation_ref` (from `report_claims`);
   - each evidence link gains `source_version_id` (already stored on `report_citation_links`) and `ref_number`;
   - the report gains `references: [{number, source_version_id, source_key, title, authors, year, venue, doi,
     version_label, open_passage_id}]`: every cited source version, numbered by first appearance walking sections in `ORDINALS`
     order, claims in `ordinal` order, links in `rowid` order; values from stored records only
     (`source_versions`, `works.source_key`); a source cited through a cell counts like one cited through a passage;
     `open_passage_id` is the first passage the report cites for that source (passage link order above), else the
     first evidence passage of a cited cell of that source in the frozen snapshot, else `null`;
   - the report gains `table_i`: `{columns: [{column_id, name, answer_format}], rows: [{source_version_id,
     ref_number | null, source_key, title}], cells: [{column_id, source_version_id, state, value}]}` read from
     `report_snapshot.snapshot_json` (the frozen values the report was written from, not the live table), or
     `null` when there is no snapshot;
   - the report gains `run: {id, status, pause_reason}` of its run, so the screen can say "being written",
     "paused: {reason}" and whether editing is allowed.
   A claim's markers render as `[2]` or `[2], [5]` (distinct numbers in first-appearance order within the claim),
   each a `<button className="cite-chip">` whose accessible name says "Reference {n}: {source title}". Clicking a
   marker whose link has a `passage_id` opens `PassageSheet` on that passage with `highlightText` = the link's
   `anchor_text` and `fromCitation` true (same as the answer); a link with only a `cell_id` opens the source sheet
   by passage id on that cell's first frozen evidence passage (from `table_i`/snapshot; add
   `evidence_passage_ids` to `table_i.cells` for this), highlighting the link's `anchor_text` only when
   `anchor_match` is not null; with no evidence passage the marker's button is disabled with a reason. Do not open
   a cell panel from here (it lives in the Evidence tab). If
   one number has several links in a claim, the first link is opened; the evidence view lists all of them.
   Keep existing keys and meanings in `report_view` unchanged; extend
   `test_report_view_returns_ordered_sections_claims_and_citation_anchors` or add a test for numbering (two
   claims citing sources A then B then A → A=1, B=2; a cell-only citation gets a number), for `table_i` coming
   from the snapshot (edit a cell after the report: `table_i` keeps the old value), and for `run`.
6. **Evidence view** (toggle, remembered per session in component state only). When on, under each claim a
   small sans line: support type in words ("Stated by the source" / "Analyst inference"), each link as
   "[n] {source_key} · {anchor_text truncated to ~120 chars with the full text in a title}"; an edited claim shows
   "Edited by you" and its warnings in words (`math_not_well_formed` → "A formula may be malformed: {detail}",
   `count_not_rechecked` → "The count was not checked again after the edit."); and the claim's **Edit** button.
   When off, only the flowing text and the citation numbers show (plan §2 decision 9: no ids, labels or anchors
   in the reading view). Analyst inference is not marked in the reading view (it is carried by hedged wording).
7. **Editing a claim** (evidence view only). Edit opens an inline form under the claim: a `textarea` with the
   current text, an optional one-line note, Save and Cancel. Save sends
   `PUT …/reports/{rid}/claims/{cid}` with `{text, note, expected_version: claim.version}` and a fresh
   `Idempotency-Key`; on 200 the returned view replaces the local one and a toast says "Claim saved. Its
   citations were kept; the new text was not checked." On 409 use the tables' wording exactly:
   "Not applied: {message}. The page now shows the latest state." — reload the report and **keep the draft text
   in the form**. On 422 show the message under the field (`role=alert`), keep the form open. The form is
   disabled with its reason while the report's run is not finished (`run.status` not in completed / failed /
   cancelled): "A report can be edited once its run has finished." History: when a claim has revisions, a
   "History ({n})" disclosure (chevron icons, not glyphs) lists the model text and each revision (kind in words:
   "Model text", "Your edit", "Restored"), date, note, and a "Restore" button on every entry except the current
   one; Restore sends `{restore_from: 'model' | revision_id, expected_version}` the same way. Keyboard: the form's
   first field takes focus when it opens; Escape cancels; Ctrl/Cmd+Enter saves.
8. **Section marker and "Keep as is".** A section whose `evidence_changes.open` is non-empty shows, under its
   heading, an attention line "This section rests on evidence that changed after this report:" followed by the
   reasons in words, deduplicated: "a cited cell changed" / "a cited source left the table or the research", with
   "(through the section it summarises)" for `via: body_ref` and "(through a candidate aspect)" for `gap_ref`.
   In the evidence view each change is listed with its column name (from `table_i.columns`) and source key.
   One button **"Keep as is"** sends `POST …/sections/{section_id}/acknowledge-changes` with exactly the open
   keys shown; on 409 the same "Not applied…" toast and reload; on 200 a toast "Marked as seen for this section.
   A later change marks it again." Also show `acknowledged_count` in the evidence view as "{n} earlier changes
   kept as is." Do not offer "Rewrite" (deferred); "edit by hand" is the claim's own Edit.
9. **Timeline rows** (`Transcript.tsx`). Add `'report'` to `RunKind` in `api.ts` and to the Answer tab's
   transcript run filter in `ResearchView.tsx`. A report run's phases are `plan` (`model:report_plan`),
   `sections` (`model:report_section`, `model:report_phrase_repair`) and `assembly` (the run's final state:
   done when the run completed, attention when it paused/failed); no review phase (there is no review step).
   Add the new phase keys to `PhaseKey`/`titles` with plain labels ("Planning the report", "Writing sections",
   "Checking the assembled report" and their done/attention variants in the same style as existing titles). The
   sections phase's expandable detail lists one row per section step from the step's `operation_key`
   (`report_section:III` → "III"): "III written", "III: must be written again", "III failed" — add
   "· {n} claims · {m} sources" only if the step's stored output in `run.steps` holds them; never compute or
   invent counts. The run's plan line: "Write a sectioned report from the evidence table, one model step per
   section." The headings map gets report outcomes ("Wrote the report", "Report paused", "Report failed", …) in
   the existing heading style. Report runs must not break the existing ordering, the "latest answer" slot, or
   runs of other kinds.
10. **Strings.** Every UI string goes through `t()` with its Turkish entry in `i18n.ts` (sentence case, no
    uppercase labels except "TABLE I" and "DRAFT", which are document conventions); labels in `labels.ts` where a
    label record fits (support type, revision kind, change reason).
11. **Style.** `.impeccable.md` is binding: editorial tokens only, no literal colors, serif for report text
    (claims 18px/1.72 as the existing report), sans for headings and interface, hairlines not boxes, no shadow on
    in-flow content, lucide icons with `aria-hidden`, `Notice` for notices, reduced-motion safe, works at 390 px
    (the sheet is full width at ≤760 px; the table I wrap scrolls horizontally inside its own scroller; the edit
    form's buttons wrap), both themes. Put new CSS next to the existing report rules in `workspace.css` (or a new
    `report/report.css` imported once); remove nothing that is still used.

## Acceptance case (Playwright + scripted model)

Add `apps/web/e2e/report.spec.ts` with its own fixture server instance (copy the small server class pattern of
`slice28.spec.ts`; pick a free port above 8799 — check `rg "8[0-9]{3}" apps/web/e2e`). Legacy workflow. The scripted model answers `report_plan`, `report_section` and `report_phrase_repair` through
`tests/fakes.py::valid_response`, but those claims cite passages only (`cell_ids: []`), so no section would react
to a cell edit. Add to `fixture_server.py::ScriptedCodex.respond`, for `report_section` steps whose
`report_target.cells` hold a cell with a value and a stored evidence quote, a second claim in the same paragraph
that cites that cell (`cell_ids`, a `citation_anchors` entry with `cell_id` and a quote taken from that cell's
own evidence quote so it is located), phrased with a phrasebank frame the fake already uses. Do not change
`tests/fakes.py`. Every other case's server must behave exactly as before (the change only touches report
steps, which no other case runs); document it in the module docstring. Steps (SYNTHETIC records; this proves application
behavior, not report quality):

1. Start a research through the composer as the evidence-table cases do, wait for screening, open Evidence,
   add one column, fill it; wait for values.
2. Back on the Answer tab: the fourth state shows "Write report" (and the Evidence toolbar's button is enabled);
   screenshot `report-readiness-desktop`. Click it; the timeline shows the report run with the sections phase;
   wait until the card reads "Evidence report · V1".
3. Open the card: headings I…IX in order, II's methodology sentence, at least one `[1]` marker, a References list
   whose first entry's title matches a source; clicking `[1]` opens the source sheet with the cited text marked.
   Screenshot `report-view-desktop` (1440×900) and `report-view-390` (390×844), both light; one dark desktop.
4. Toggle Evidence view, Edit the first claim of section III, save; the text changes, "Edited by you" shows,
   the head says "Edited by hand after version 1". Then test the UI's 409 path: open Edit on a claim, type a
   draft, change the same claim through the API (a `PUT` with the current version), then press Save in the open
   form: the toast says "Not applied:", the report reloads and the form still holds the typed draft. Restore to the
   model text from History.
5. Edit the cell the fixture's report cites (through the Evidence tab or the API) → reopen the report: the band says a cell
   changed and the citing section shows its marker; "Keep as is" removes that section's marker, the band stays
   (report-level counts do not depend on acknowledgement — check `evidence_changes` in `store.py` and assert what
   it actually does). Screenshot `report-stale-desktop`.

Screenshots go to `DEIXIS_ACCEPTANCE_DIR` like the other cases.

## Ground rules

1. **Run NO state-changing git command** (`add`, `commit`, `checkout`, `stash`, `restore`, `reset`, `rebase`).
   `git status` / `git diff` / `git log` are fine. The reviewing session commits.
2. **Do not touch** `docs/decisions.md`, `TODO.md`, `.vscode/`, `scripts/local_index.py`, `methods/`,
   `contracts/`, any migration, `backend/deixis/workflow/flow.py`. Backend changes are limited to the anchor fix
   above (`contracts.py::_check_report_section`, `sections.py::_citation_links`), `views.py::report_view`,
   `tables.py::TableStore.tables` (the `report_ready` field), `tests/acceptance/fixture_server.py` and tests. `AnswerBlock` and `PdfReadiness`'s
   behavior stay as they are (exporting `Depth` is fine).
3. **Do not invent.** No number, model name, count or state in the UI that the backend did not return. If
   something here cannot be built as written, stop that part and report it.
4. Match the surrounding style: short comments that say why, no new dependency, React 19 + Tailwind 4 +
   `components/ui` primitives, the existing `api.ts` `request` helper and its `ApiError` (status, message).
5. Tests: `PYTHONPATH=backend:. uv run --no-sync pytest -q` (set `UV_CACHE_DIR=/tmp/deixis-uv-cache` if the
   cache is unreachable). Web: `cd apps/web && npm run build && npm run lint`. Acceptance:
   `cd apps/web && DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance-p10 npx playwright test e2e/report.spec.ts`, then
   the whole suite (`npm run test:acceptance`) once at the end.

## Read first

- `AGENTS.md`, `.impeccable.md` (all of it; §2.2, §3 sheets, §4.3, §4.4, §5, §7, §8, §9 matter most).
- `docs/product/p6-report-design.md` §2 (decisions 1, 3, 4, 9, 11), §9; `p6-slice1-report-run.md` 1h and 1i;
  `p6-slice4-editing-stale-measurement.md` §0 and §7.
- `backend/deixis/workflow/views.py::report_view`, `backend/deixis/workflow/report/store.py`
  (`edit_claim`, `claim_revisions`, `evidence_changes`, `acknowledge_changes`), `snapshot.py`,
  `backend/deixis/workflow/tables.py` (`tables`, `report_ready`), the report routes in `api/app.py`.
- `apps/web/src/ResearchView.tsx` (`AnswerBlock`, the Answer and Artifacts tabs, `PassageSheet` wiring),
  `PdfReadiness.tsx`, `EvidenceTable.tsx` (toolbar, 409 handling, `valueText`), `Transcript.tsx`, `api.ts`,
  `citations.tsx`, `MathText.tsx`, `Notice.tsx`, `ModelName.tsx`, `modelText.ts`, `i18n.ts`, `labels.ts`,
  `workspace.css` report rules.
- `tests/test_report_api.py`, `tests/test_report_store.py`, `tests/fakes.py` (report tasks),
  `tests/acceptance/fixture_server.py`, `apps/web/e2e/acceptance.spec.ts` (evidence-table cases),
  `apps/web/e2e/slice28.spec.ts`.

## Procedure

1. Read everything above.
2. Baseline: pytest, build, lint (record counts and the lint warning count).
3. Backend first: failing tests, then `report_view` / `tables()` changes.
4. Frontend, then the acceptance case. Look at your own screenshots (desktop, 390 px, dark) and fix what looks
   wrong against `.impeccable.md` before finishing.
5. Full pytest, build, lint, the new spec, then the whole acceptance suite.

## Final message

- files changed; the decision you took where this brief gave a choice (one button per table or a Select);
- before/after pytest counts, lint warning count, acceptance results (new spec and whole suite);
- the paths of the screenshots you looked at, and what you changed after looking;
- every place this brief could not be followed as written, and what you did instead;
- anything missing, contradictory or already broken you found;
- what you did NOT do.
