<!-- PLAN-REVIEW-ROUNDS: gpt-6.1-sol high, r1: hazır değil, 2 high (the epoch/ordering rule did not cover a GET that starts after a write begins; the review note must say it covers the model base version only) + 8 medium + 1 low, all folded in; r2: hazır değil, 1 high (a mutation response could undo another tab's newer write; 409 recovery unguarded) + 2 medium + 1 low, folded in (ticket rule plus a confirming GET after every mutation); r3: düzeltmeyle hazır (0 high), 2 low folded in; CODE-REVIEW: r1 hazır/düzeltmeyle hazır (0 high, 2 medium: a returning citation kept its old removal intent, fields editable while a save is in flight), r2 hazır (0 high) -->

# Task: P6 slice 4, batch E3 ("Arayuz"), the report screen for the edit check and for citation removal

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-e3` (detached at `ac5a871`, main with D152 and D153). Read `AGENTS.md`,
`CLAUDE.md`, `.impeccable.md` (MANDATORY before touching `apps/web`; its rules bind every line of UI you write), `docs/decisions.md` D147, D148,
D150 (the slice 4 decision and the two backend batches this one puts a screen on) and D152 (the Candidates screen, the model for how a UI batch is
built and checked), and `docs/product/p6-slice4-editing-stale-measurement.md` (Turkish): §2, §3, §4, §8, §9 "Web", §14 "E3". This prompt is the
binding English scope. Read `docs/product/p6-slice3-k4-prompt.md` and the code it produced (`apps/web/src/candidate/*`,
`apps/web/e2e/candidate.spec.ts`, the `[candidate]` scenario in `tests/acceptance/fixture_server.py`): patterns to copy are the refetch ordering
guard, the 409/422 handling that keeps a typed draft, `useReturnFocus` (`apps/web/src/candidate/focus.ts`), the mocked-JSON rendering tests and the
forbidden-word scan. Where the code differs from what this prompt says, report it.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted.
Do not invent; report what you could not find. **No real-model call, no real provider request, no network: the fixture server's scripted model,
its mocked OpenAlex and synthetic data only.** Do not touch `../DEIXIS`, `../DEIXIS-k5`, `../DEIXIS-x3`, `.local/`, `TODO.md`, `.vscode/`,
`scripts/local_index.py`, `docs/product/sw-status.md`, ports 8765 and 8858-8864, or the live data directory. Backend tests need
`PYTHONPATH=backend:.`, `UV_CACHE_DIR=/tmp/deixis-uv-cache`, `UV_OFFLINE=1` and `UV_PROJECT_ENVIRONMENT=/tmp/e3-venv` (a ready arm64 venv; do not
create a `.venv` in the worktree). `apps/web/node_modules` in the worktree is an APFS clone made by the orchestrator (leave it; the orchestrator removes
it). For Playwright set `DEIXIS_TEST_PYTHON=/Users/huguryildiz/Documents/GitHub/DEIXIS/.venv/bin/python` (the specs set `PYTHONPATH` to the worktree).
If your sandbox blocks loopback binds or process spawning, say so and continue; the orchestrator runs Playwright and takes the screenshots.
`docs/decisions.md`, the slice note and this file's comment line are written by the orchestrator, not by you.

## Why

E1 made an edited report checkable by code and E2 made a claim able to lose citations reversibly, both without a screen. Today the report screen still says
"Edited by hand after version N; edited text was not checked again" whatever the API now knows, the edit form can change text only (every save says "its
citations were kept"), a citation cannot be removed, the history shows text and nothing about citations, and a claim that lost every citation reads as an
uncited sentence with no explanation. E3 puts a screen on the stored state, and only on it. The screen must never claim more than the code did: the check
reads working text with a subset of the assembly rules and says so; a removed citation reduces evidence and says nothing about whether a remaining citation
supports its sentence; a "current" check is a statement about inputs, not about correctness.

## What is and is not in code (checked on ac5a871; re-check, do not assume)

- In code, do not change (except the one route below): `POST /api/researches/{rid}/reports/{report_id}/check-edits` (no body, no `Idempotency-Key`; 200 returns
  the full report view; 409 when the report's run has not finished or the report is not `valid`/`draft`; 404 for another research's or a trashed research's
  report; writes an append-only `report_edits_checked` event and a row only when the input fingerprint is new; never changes report status, version, sections
  or review); `PUT .../claims/{claim_id}` (body `{expected_version, text?, note?, restore_from?, link_ids?}`; header `Idempotency-Key`; 200 returns the full report
  view; 409 stale `expected_version`, unfinished run, or a reused key with different content; 422 for no change, `restore_from` together with `text` or
  `link_ids`, neither given, a link that is not an original link of this claim, or blank/over-long text; `link_ids` is at most 200 ids, each at most 40
  characters; omitted or null keeps the current citation set, `[]` removes all); `POST .../sections/{section_id}/acknowledge-changes`; `GET .../reports/{id}/gaps`
  (K4); the K4 `ReportAspects` block in section VI; CSRF.
- Report view fields E1/E2 added (`backend/deixis/workflow/views.py::report_view`, read it and mirror it exactly):
  - top level: `has_human_edits: boolean` (true after any revision row, also a citation-only one and also on a draft report whose `edited_after_version` is null);
    `edited_after_version: number|null`; `edit_check: null | {id, created_at, checker_version, current: boolean, errors, warnings, skipped, edited_claims,
    items: {rule, section_id, detail, severity: 'error'|'warning'}[], skipped_rules: {rule, section_id, claim_key, reason}[], rules_run: string[],
    not_checked: string[]}` (`current` is true only when the stored fingerprint equals the one computed now; a false `current` still carries the last record
    and means "does not cover the current inputs"). `detail` strings begin with `ERROR: ` or `WARNING: `. `not_checked` is today
    `["semantic_support","numbers_written_as_words","passages"]`. Skipped `rule`/`reason` values seen today: `count_text_not_checked`/`no_integer_in_text`,
    `derived_depth_not_checked`/`no_citation_depth`, `phrase_frames`/`human_text`.
  - per claim: `evidence[]` now holds only EFFECTIVE links and each has `link_id` (plus `passage_id|cell_id`, `source_version_id`, `ref_number`, `anchor_text`,
    `anchor_match`, `open_passage_id`); `original_evidence_count`; `removed_links[]` (`{link_id, passage_id, cell_id, source_version_id, anchor_text,
    anchor_match, title?, source_key?}`, original links not in the current set); `evidence_basis: 'direct'|'none'` (none when no effective link);
    `support_type_note: 'model_written_type'|null` (set only when a claim that HAD original links now has none); `edited_basis: string[]` (claim keys of edited
    claims this claim rests on through `body_ref`/`gap_ref`; independent of whether this claim's own text was edited); `claim_key`; `version`; `text`; `model_text`; `edited`.
  - per revision (`claim.revisions`, oldest first, every human edit including a citation-only one, and every restore; the model's original text is NOT in this list): `id`, `kind`
    (`human_edit`|`human_restore`), `restored_from`, `text`, `note`, `created_at`, `warnings`, `link_count` (null = a revision written before E2: every original
    link was effective), `link_ids` (null when `link_count` is null, else the recorded ids), `changes_current` (true when restoring this revision would change
    the claim's text or effective set).
  - Reference numbers are per source version, not per link: two links to the same source share one `ref_number`. The reading view shows one chip per number
    (first link of that number); the edit form below must work per `link_id`.
- In code (web), `apps/web/src/report/ReportView.tsx` (one 221-line, 25 KB file, dense): `ClaimEdit` edits text and note only and `save` always sends `text`;
  the evidence view lists each claim's effective links as buttons keyed by index; History lists `model_text` and the revisions with "Restore" shown by text
  equality alone; the success toast says "Claim saved. Its citations were kept; the new text was not checked."; the header shows one `<small>` "Edited by
  hand after version {n}; edited text was not checked again." only when `edited_after_version !== null`; a claim with no effective links renders no marker
  at all; after save or cancel the edit form unmounts and focus is lost; the mount effect refetches on `view.last_event_id` and a slow older GET can overwrite
  a newer mutation response. `api.ts` types and `editReportClaim` do not know any of the E1/E2 fields and there is no `checkReportEdits`.
- Not in code: any screen for the edit check, citation removal, citation counts in the history, a "no direct citation" state, the edited-basis note, a fixture
  claim with two citations, a Playwright spec for these. Check, do not assume.

## Backend exception (one, trivial; report it, the main session may veto it)

`ReportStore.acknowledge_changes` (`backend/deixis/workflow/report/store.py`) writes acknowledgement rows and an event inside its transaction and only the route's
later `report_view` call finds out that the research is trashed (`Store.research` raises `NotFound` for a trashed research). Add `self.store.research(research_id)`
as the first line inside its `with transaction(...)` block, like `check_edits` and `edit_claim` do, so a trashed research is not found before anything is written.
Add one test in `tests/test_report_store.py` or `tests/test_report_claim_links.py` (follow `test_two_tabs_and_trashed_research_write_nothing`): trash the research,
call `acknowledge_changes` with a real open key, expect `NotFound`, and prove no `report_stale_acknowledgements` row and no event were written; and that an untrashed
research still acknowledges. No other backend file changes except the fixture below.

## Decisions (already taken; do not reopen)

1. **Files and shape.** Keep `ReportView.tsx` as the owner of state and requests. Extract new code into new files under `apps/web/src/report/` instead of growing
   it: at least `EditCheckPanel.tsx` (header sentence, check button, result list), `ClaimEdit.tsx` (the form, moved out with its citation list) and
   `ClaimHistory.tsx` (history list), and a `editLabels.ts` for the rule/reason/not-checked word maps (or add them to `labels.ts` beside
   `assemblyRuleLabels`; one place, not both). Styles go into `report.css` (editorial tokens only, no literal colors, no new token, sentence-case labels, no
   shadow, no colored side bar thicker than 1px, radii from the guide, sizes from the type scale). Every new string goes through `t()` with a Turkish entry
   in the `tr` map of `i18n.ts`. Plurals follow the repo's pattern: two English keys chosen by the number (`'{n} citation'`/`'{n} citations'`).
2. **API types** (`api.ts`): mirror the view exactly (see "What is and is not in code"): `ReportLink.link_id`; `ReportClaim` gets `original_evidence_count`,
   `removed_links`, `evidence_basis`, `support_type_note`, `edited_basis`; each revision gets `restored_from`, `link_count`, `link_ids`, `changes_current`;
   `ReportDetail` gets `has_human_edits` and `edit_check` (type `EditCheck`). `editReportClaim`'s body gets `link_ids?: string[]` (keep `crypto.randomUUID()`
   per call). Add `checkReportEdits(id, reportId)`: `POST /api/researches/${id}/reports/${reportId}/check-edits`, no body, returns `ReportDetail`. No
   `any`; no cast that hides a missing field.
3. **One read model for the sentence.** The header sentence has exactly the three states of the Markdown export (`backend/deixis/workflow/report/export_text.py::
   edit_note`; read it) and says the same things in the same order; English wording below, Turkish twin from the export's Turkish sentences. `{prefix}` is
   "Edited by hand after version {n}" when `edited_after_version !== null` else "Edited by hand" (Turkish: "{n}. sürümden sonra elle düzenlendi" / "Elle
   düzenlendi"). The existing key `'Edited by hand after version {n}; edited text was not checked again.'` and its Turkish entry stay as they are.
   - no `edit_check`: "{prefix}; edited text was not checked again."
   - `current`: "{prefix}; the edited text was checked by code rules ({date}): {errors}, {warnings}; whether the cited evidence supports each sentence was not
     checked." with `{errors}` "1 error"/"N errors" and `{warnings}` "1 warning"/"N warnings" (grammatical plurals on screen; the export's pinned "N errors"
     wording is not touched and this is a reported judgement call). `{date}` is `created_at` formatted with `toLocaleString(uiLocale(), { dateStyle: 'medium',
     timeStyle: 'short' })`.
   - not `current`: "{prefix}; the last check ({date}) does not cover the current inputs; whether the cited evidence supports each sentence was not checked."
   The state is also a visible text label beside the sentence, never colour alone: "Current" or "Out of date". The sentence is the live region (`role="status"`)
   of the panel; nothing else in the panel is.
4. **The check panel** (`EditCheckPanel`) sits in the report head, replacing the old `<small>`; it renders only when `report.has_human_edits` is true (so a draft
   report with edits shows it too, which the old code did not). Contents, in order:
   - the sentence and its state label (decision 3);
   - one button. Label "Check edited text" when there is no check, "Check again" otherwise. It is **disabled** (never hidden) with a **visible** reason line
     beside it (not `title` alone; also `aria-describedby`): when the report's run has not finished or the report is `in_progress` ("A report can be checked once
     its run has finished."), when the last check is `current` ("This check covers the current text and citations."), and while a request is in flight (label
     "Checking…", `aria-busy`). A click calls `api.checkReportEdits`, sets the returned view as the report (through the ordering guard of decision 12), and shows a
     toast `success`: "Check recorded: {errors}, {warnings}. Whether the cited evidence supports each sentence was not checked." 409 shows the warning toast
     "Not applied: {message}. The page now shows the latest state." and refetches (same text as the existing acknowledge path); other errors an `error` toast.
   - when `edit_check` is not null, the **result list**, also for an out-of-date check (then under a plain line "This is an earlier check; edits or other inputs changed since." so
     the list is never read as describing the present text). Each item: a lucide icon plus the word "Error" or "Warning" (`CircleX`/`TriangleAlert`, `aria-hidden`,
     tones `--tone-exclude`/`--tone-uncertain` for the icon only, the word in ink), the section heading from the existing `labels(section_id)`, the rule in plain words,
     and the stored `detail` with its leading `ERROR: `/`WARNING: ` removed (only when it is exactly that prefix; any other `detail` is shown as stored). Order as
     delivered. A rule code with no entry in the label map prints its code with underscores replaced by spaces (the `assemblyRuleLabels` pattern); do not invent
     labels for the 30-odd assembly rule codes: label only `banned_word`, `count_number_mismatch`, `limitations_number_restated` and `math_not_well_formed` (all four are emitted by
     `assembly.py` / `run_current_checks` today; confirm by grep) and fall back for the rest.
   - zero items: one plain sentence "The rules that ran reported no error or warning." Never "no problems", "clean", "passed" or "verified".
   - a `<details>` "Rules that ran ({n})", closed by default, present whenever a check exists (also when `skipped_rules` is empty), listing `rules_run` (the codes with
     underscores replaced by spaces; no label map);
   - a second `<details>` "Rules that did not run for some claims ({n})", closed by default, present only when `skipped_rules.length > 0`, listing each
     `{claim_key} · {section} · {rule}: {reason}` with plain-word maps for the three known rule codes and three known reasons (human_text = "edited text: required
     phrase frames are not checked", no_integer_in_text = "no whole number in the text to compare", no_citation_depth = "no citation to read the evidence depth from");
     unknown codes fall back as above.
   - one fine-print line, once, always when a check exists: "Not checked: whether the cited evidence supports each sentence, numbers written as words, passages."
     built from `not_checked` (the three known values mapped to those phrases; an unknown value is printed as given). It is neutral fine print, not styled as a
     success.
   No part of the panel may use the words verified, validated, confirmed, approved, clean, passed, correct or "no problems" about the check or the text.
5. **Edit form** (`ClaimEdit`, same file split as decision 1). Keep the text field, note field, Escape = cancel, Cmd/Ctrl+Enter = save, the `expectedVersion`
   handling after a 409 (the typed draft stays, the version in force becomes the one now on screen) and the `role="alert"` error. Add a `<fieldset>` with a
   `<legend>` "Citations to keep" **only when the claim has at least one effective link**; one row per effective link (by `link_id`, not by reference number): a
   native checkbox, checked by default, whose label is "[{n}] {source key or title}" followed, in muted smaller text, by the kind ("passage" or "table cell")
   and the stored anchor text (at most 160 characters then an ellipsis, with a "Show more"/"Show less" text button per row, `aria-expanded`, that reveals the whole text; the
   text is stored data: wrap it in `data-stored-text` and never alter it), all wrapping (`overflow-wrap: anywhere`, no horizontal scroll at 390 px). An unchecked row says in text "Will be removed when you save." Under the list one line
   counts "{k} of {n} citations kept". When every row is unchecked an attention-tone `Notice` says "No citation will remain on this sentence. Its support type stays
   as the model wrote it, and you can bring the citations back from History." When the claim has no effective link the fieldset is replaced by one muted
   sentence: "This sentence has no citations to keep. History can bring earlier citations back." when `claim.original_evidence_count > 0`, otherwise "This sentence has no
   citations to keep." (a claim that never had one has no recovery path and the screen must not hint at one).
   - State is the set of link ids the person unchecked. The kept set is computed against the CURRENT `claim.evidence` on every render, so a link that
     disappeared after a refetch simply drops out and a newly effective one appears checked.
   - The request carries `text` only when the trimmed text differs from the claim's current text, `note` as today, and `link_ids` (the kept ids) only when at
     least one row is unchecked; a form with every box checked sends no `link_ids`. Never send `restore_from` from this form.
   - **One `canSave` rule, applied everywhere:** the Save button, the form's `onSubmit` and the Cmd/Ctrl+Enter handler all test the same condition and do nothing (no request) when it is
     false; the existing keyboard handler that calls `save` directly must go through it. **Save is disabled** (visible reason line, `aria-describedby`) while busy, when the text is blank ("Write the sentence or cancel."), and when neither the text
     nor the citation set changed ("Change the text or remove a citation to save."). The 422 error from the API still shows in the form.
   - On success the form closes, the report becomes the returned view, and focus returns to that claim's "Edit" button (`useReturnFocus` or an equivalent
     that survives the re-render; Cancel and Escape do the same). The returned view's `version` is the claim's new `expected_version`.
6. **Toasts** state what actually happened (the old fixed "its citations were kept" sentence must go, it is false after a removal): text only: "Claim saved. The
   new text was not checked."; citations only or both with `k` removed: "Claim saved. {k} citation removed from this sentence; the edit was not checked."
   (plural key for k > 1; with a text change say "text changed and {k} citation(s) removed"; build the sentence from two clauses, do not make four near-copies);
   a restore: "Version restored with its text and citations." Existing 409/422/other handling stays. Remove the now-unused i18n pair for the old sentence only if
   nothing references it afterwards.
7. **History** (`ClaimHistory`, one disclosure per claim as today, count in the summary as today). Entries: the model's text first, then `claim.revisions` in the
   order delivered. Each entry shows, in its meta line, the citation count of that entry's set: the model entry and a revision with `link_count === null` use
   `claim.original_evidence_count`, any other revision uses its `link_count`; wording "{n} citation"/"{n} citations" ("No citations" for 0), and when the count
   differs from the entry above it "Citations: from {from} to {to}" instead (words, no arrow glyph, no icon). The existing "Your edit"/"Restored" label, date and
   note stay. **"Restore" is shown only when restoring would change something:** for a revision exactly `item.changes_current`; for the model entry
   `claim.text !== claim.model_text || claim.removed_links.length > 0` (the model entry is not in `revisions`, so the screen compares itself). The control's
   accessible name says what it brings back: "Restore this version's text and citations" (visible label stays "Restore"; the existing spec clicks
   `getByRole('button', { name: 'Restore' })`, so keep an accessible name that still matches a substring regex or keep the name exactly "Restore" with the extra
   words in `aria-describedby`; pick the way that keeps the existing report spec passing unchanged and say which). Restore keeps its immediate behaviour (no
   confirmation: it appends a revision and loses nothing); after it focus returns to the claim's "Edit" button.
8. **Claims without an effective citation.** Reading view: a claim with `evidence_basis === 'none'` and `support_type_note !== null` (it had citations that were
   all removed) shows, after the sentence and where chips would be, a muted sans fragment "(no direct citation)" in the `.evidence-report-*` family of classes; a claim
   that never had a citation shows nothing new (model output, not an owner removal; same judgement as the export). Evidence view, claim meta line: the claim key
   (muted, e.g. "III.2"), the support-type label as today, and for `support_type_note === 'model_written_type'` the label becomes "{type} (type as the model wrote it; its
   citations were removed)" with the existing support labels from `labels.ts`; for any claim with `evidence_basis === 'none'` the line "No direct citation." is shown.
   When `removed_links.length > 0` a `<details>` "Citations removed by hand ({n} of {m})" (m = `original_evidence_count`) lists each removed link as plain text
   (`[source key or title] · anchor excerpt`, no button: a removed link has no `open_passage_id`) and ends "History can bring them back." (always true there: a removed link exists only for a claim that had one). No removed link is ever opened,
   and no list is capped silently.
9. **Edited basis.** In the evidence-view meta line of a claim with a non-empty `edited_basis`: "Rests on edited claim {keys}." / "Rests on edited claims {keys}."
   (singular/plural keys), followed by "This sentence was not changed." **only when** `claim.text === claim.model_text` (the claim may itself be edited: `edited_basis` is
   independent of that, and `edited` stays true after a restore to the original text, so compare the texts). The reading view does not get this note.
10. **No new request on render, no polling.** The check result and `has_human_edits` come from the report GET the sheet already makes; the existing refetch on
    `view.last_event_id` stays.
11. **Everything else in the sheet is unchanged** in text, markup order and behaviour: evidence changes, "Keep as is", export buttons, the K4 `ReportAspects` block, tables,
    references (the existing report specs and `candidate.spec.ts` pass unchanged; if one needs a change it is a defect in your change, not in the spec; report it). Exactly
    three deliberate exceptions, each mirroring a sentence the Markdown export already says (`export_text.py`; the screen and the file read one model):
    a. **Review note.** When `review.status === 'reviewed'` the review note gets the sentence "The review covers the model's base version; human edits were not reviewed."
       appended (Turkish: "İnceleme modelin temel sürümünü kapsar; insan düzenlemeleri incelenmedi."), exactly where `review_note` appends it (`export_text.py` ~l.310),
       whether or not the report has edits (the export does the same). The other review notes are unchanged.
    b. **Anchor sentence.** The provenance paragraph's anchor sentence follows `export_text.py` ~l.263-276 instead of the bare `located === allLinks.length` test:
       when there are zero effective links over the whole report **and** at least one claim has `evidence_basis === 'none'` with a non-null `support_type_note`, say "No citation
       anchors remain after citations were removed by hand." (Turkish twin from the export) instead of "Anchors were located in the cited passages or cells."; and when at
       least one such claim exists add " {n} claims have no direct citations after citations were removed by hand." (grammatical singular on screen: " 1 claim has no direct
       citation after citations were removed by hand."; Turkish twin from the export). Every other case keeps today's wording and logic, so a report with no removal reads exactly as now
       (including one that never had a link).
    c. **Edit button reason.** Each claim's "Edit" button, when disabled because the run has not finished, gets a visible reason line and `aria-describedby` in addition to its
       current `title` (".impeccable.md" §9). The other existing `title`-only reasons (export buttons, cite chips) are known drift of this batch's neighbours; leave them and list
       them in your report.
12. **Report state ordering (the applied ticket never goes backwards; every mutation is followed by a confirming read).** Today's mount/event effect refetches on `view.last_event_id`, a slow older
    GET can overwrite a newer mutation response, a GET started after a write began may still read the old state, and another tab's later write can arrive before this tab's mutation
    response. Rule (the refetch guard of K4, see `candidate/CandidateDetail.tsx`, extended): `ReportView` keeps two refs, `seq` (a counter) and `applied` (the highest ticket applied).
    - Every GET (the effect, `refresh`, the confirming read) takes `ticket = ++seq` when it STARTS and applies its response only if `ticket > applied`, then sets `applied = ticket`.
    - A mutation (`save` including restore, `acknowledge`, `check`) applies its returned view on completion, stamping it with a fresh ticket (`ticket = ++seq; applied = ticket`), so any
      GET that started before the response arrived and resolves later is discarded. A mutation response is never rejected for being "old" (this tab serialises its own mutations with `busy`).
    - **After every mutation outcome that is not a 422 form error (success, or 409/other failure) the tab starts one confirming GET** (a fresh ticket, applied by the rule above). It
      replaces today's `await refresh()` after a 409. The confirming read is what makes the screen converge when another tab wrote between this tab's write and its response (the
      response may then briefly show this tab's own result and the next read shows the other tab's newer state).
    - The `expectedVersion` handling after a 409 stays tied to the recovered view that was actually applied (the confirming GET's result).
    - After unmount, late responses are discarded (the `live` flag stays).
    Tests (Tests, d): (i) a GET started before a PUT completes with a stale body and resolves after the PUT response is discarded; (ii) a delayed PUT response arriving after another
    tab's write (made through the API) was already shown leaves the page, once the confirming GET resolved, equal to the server's state (assert the final DOM against a fresh API GET);
    (iii) a 409's recovery view is not overwritten by an older GET that resolves after it; (iv) the same confirming GET follows `check` and `acknowledge`; (v) a completed GET starts no further GET and does not call `onChanged()` (count report GETs after a quiet period); (vi) an isolated 422 form error starts no `refresh` and no confirming GET and keeps the typed draft and the error (the mutation's own event may still trigger the normal effect GET).
13. **Accessibility and keyboard.** Every new control has a visible name and a visible focus ring (the shared `:focus-visible` rule applies; do not remove it);
    the whole flow (open Evidence view, Tab to Edit, edit, Tab through the checkboxes, Space toggles, Cmd/Ctrl+Enter saves, Escape cancels, Tab to Check edited text,
    Enter) works with the keyboard alone and focus is never left on a removed node. Icons are `aria-hidden`; state is never colour alone; contrast stays at 4.5:1 in both
    themes. Disabled controls always carry a visible reason. `prefers-reduced-motion`: add no animation or transition.
14. **Layout.** 1440 px and 390 px, light and dark. At 390 px nothing scrolls horizontally (the existing `scrollWidth <= clientWidth` assertion), the check button
    and its reason stack under the sentence, long anchor text and rule detail wrap, the history and the form keep their current width logic. The panel is hairline-ruled
    (1px `--line`), not a card: no container, no shadow.
15. **Fixture marker** `[report-two-citations]` in `tests/acceptance/fixture_server.py` (the only fixture change): when the question contains it, the scripted
    `report_section` step makes the claim it adds from a filled cell (the `X.2` cell claim) cite two links of ONE source version: its cell and a stored passage **of the same source
    version as that cell** (find the passage in the step input by its source/version field; read the step input shape, do not guess the key; if the step has no passage of that source,
    report it), with a located anchor from that passage's own text exactly as the default `X.1` claim does, in every section where the cell claim is added today. Without the marker nothing
    changes. Two links to one source share a reference number: that is deliberate, it proves the screen keys by `link_id`. Acceptance for the marker: with it, the report run completes
    `valid`, and `GET .../reports/{id}` has at least one claim with two effective links that have two different `link_id`s, the same `source_version_id` and `ref_number`, one with `cell_id`
    and one with `passage_id` (the Playwright spec asserts this before using it). If the scripted report fails validation or an assembly rule, report the rule and what you tried; do not
    weaken a validator. Update the module docstring beside the other markers with one line.
16. **Words.** Sentence case everywhere, no uppercase eyebrow. Terms: "citation" (the API calls it a link), "edited text", "code rules", "semantic support not checked". Never
    write copy that implies verification DEIXIS did not do. The screen says nothing about `report_version` changing, publishing or a new version: there is none.

## Limits of E3 (do not exceed)

No new route; no migration (the one backend change is the `acknowledge_changes` guard); no model call; no change to `methods/`, `contracts/`,
`domain/contracts.py`, `workflow/report/*` other than that one line, `views.py`, `export.py` or `app.py`; no "Publish" action, no new report version, no section rewrite, no
adding a citation, no restoring a single removed link on its own (only History restore, which brings text and set together), no edit of `scope_statement`, no
export change, no PDF/passage change, no new dependency, no new design token. The screen does not run the check automatically after an edit; the person does.
`skill_package_hash` must not move; print it before and after.

## Files allowed

`apps/web/src/report/ReportView.tsx`, new files under `apps/web/src/report/` (`EditCheckPanel.tsx`, `ClaimEdit.tsx`, `ClaimHistory.tsx`, optionally one small labels/helpers
file), `apps/web/src/report/report.css`, `apps/web/src/api.ts`, `apps/web/src/i18n.ts`, `apps/web/src/labels.ts` (only if the label maps go there),
`apps/web/e2e/report-edit.spec.ts` (new), `tests/acceptance/fixture_server.py` (the marker only),
`backend/deixis/workflow/report/store.py` (`acknowledge_changes` only), `tests/test_report_store.py` or `tests/test_report_claim_links.py` (the one test).
Reusing `apps/web/src/candidate/focus.ts` by import is fine; do not edit it. `apps/web/e2e/report.spec.ts` may change only if a string assertion there is made false by a
deliberate wording change in decision 6 (it is not expected to).
## Files NOT allowed

`docs/decisions.md`, the slice note, other docs, `methods/`, `contracts/`, other backend files, other specs, `TODO.md`, `.vscode/`, `scripts/local_index.py`,
`apps/web/package.json` and lockfile, everything under `../DEIXIS*`.

## Tests to add

Playwright `apps/web/e2e/report-edit.spec.ts`, one `ReportServer`-style class like `report.spec.ts` on **port 8808** (not used by any other spec; check
`grep -rn 8808 apps/web/e2e tests/acceptance` first), the question marker `[report-two-citations]`, a `readyResearch`-style helper copied from `report.spec.ts` (do not
import from another spec). All text assertions in English unless stated.

a. **Check flow (scenario).** Write the report; open it; open Evidence view; edit claim III.1 to contain the banned phrase "research gap" and save. The head shows the
   no-check sentence ("Edited by hand after version 1; edited text was not checked again.") and the button "Check edited text" is enabled. Click it: the sentence becomes the
   current one with "1 error, 0 warnings" or the real counts the backend returns (assert from `GET` of the report so the test follows the backend), the state label
   "Current", the list shows an item with the word "Error", the section name "III. Background and Taxonomy" and the banned-word rule; the button is disabled with its visible
   reason. Edit the same claim again to a clean sentence: the sentence is now the out-of-date one, the label "Out of date", the old item is still listed under "This is an
   earlier check…", the button is enabled ("Check again"). Click: current, "The rules that ran reported no error or warning.", the disclosure for skipped rules lists at
   least the phrase-frames skip for the edited claim, the fine-print "Not checked:" line is present exactly once. A second check without any change is impossible from the
   UI (disabled); additionally call the route twice from the test and assert the same record id (no duplicate row). Screenshots: `report-edit-check-desktop`,
   `report-edit-check-390`, and dark.
b. **Citation removal and restore.** Find the claim with two links (assert through the API that at least one claim has two effective links). Open its form: two rows, both
   checked, the count line "2 of 2 citations kept"; Save is disabled with the visible reason; uncheck the first: the row says "Will be removed when you save.", the count says
   "1 of 2", Save is enabled; save: the toast says one citation was removed (not "kept"), the evidence list shows one link, History shows "Citations: from 2 to 1" on the new entry
   and "Restore" on the model entry (assert `removed_links` through the API too); the reading view still shows the source chip (same reference number); click "Restore" on the model
   entry: two links again, the "Restore" control on the model entry is gone (nothing left to restore), focus is on the claim's Edit button. A citation-only save sends no `text`
   (assert the PUT body with `page.on('request')`), a text-only save sends no `link_ids`.
c. **A claim that loses every citation.** Remove the only citation of III.1 (a one-link claim) with the text unchanged: the reading view shows "(no direct citation)" after the
   sentence and no chip; the evidence view shows "No direct citation.", the type label with "(type as the model wrote it; its citations were removed)", the removed-citation
   disclosure with the anchor text, "History can bring them back."; restore it from History: chip and normal meta return. A never-cited claim (VIII.1): the reading view has no "(no direct citation)" fragment, the evidence view has no type suffix and no removed-citation disclosure, and the evidence view does
   show "No direct citation." (decision 8).
d. **Two tabs.** Open the form on a claim, uncheck a citation, then change the claim through the API (`PUT` with the form's `expected_version`, from `page.request` with the CSRF
   header as `report.spec.ts` does); Save: the page shows the "Not applied" toast, the typed text and the unchecked intent survive, the shown version is the new one, and saving again
   succeeds. Also the four orderings (i) to (iv) of decision 12, with routed, delayed report GETs and a delayed PUT (a stale body for (i); a second write through the API for (ii); a 409 for (iii); `check` and `acknowledge` for (iv)). Also: with an empty draft, an unchanged draft, or a
   request in flight, Cmd/Ctrl+Enter sends no PUT (count requests), and the Save button is disabled with its visible reason.
e. **Mocked rendering** (route the report GET with a body built from a real report view plus edits): an `edit_check` with 0 items and 2 skipped rules; one with `skipped_rules: []` (no skipped-rules disclosure, but "Rules that ran" present and listing `rules_run`); one with an unknown rule code
   and an unknown skipped reason and an unknown `not_checked` value (printed as given, no crash); a stale check; an `edit_check` whose `detail` has no `ERROR: ` prefix (shown as stored);
   an `evidence_basis: 'none'` claim with `support_type_note: null` (no "(no direct citation)" fragment, but "No direct citation." in the evidence view); `edited_basis` with one and two
   keys, and with a claim that is itself edited (no "This sentence was not changed." there, present when `text === model_text`); a claim with `evidence_basis: 'none'`, no `support_type_note`
   and `original_evidence_count: 0` (form says only "no citations to keep", no History hint); a report whose every effective link was removed (provenance says "No citation anchors remain
   after citations were removed by hand." and "N claims have no direct citations…", singular for one; a report that never had a link keeps today's sentence); a `reviewed` review (the
   base-version sentence is appended, Turkish too) and a `not_reviewed` one (not appended); a revision with `link_count: null` and one with `link_count: 0` (counts "No citations"); a report with `has_human_edits: true` and `edited_after_version: null` (the prefix
   without "after version"); `has_human_edits: false` (no panel); a run that has not finished (button disabled with its visible reason; Edit disabled as today).
f. **Turkish.** Reopen the report with an edit and a check, and assert the
   Turkish sentence for the current state, the button label, the "Citations to keep" legend in Turkish, and that no English fragment of the new strings remains in the panel and
   form (scan the panel's and form's UI text, excluding `data-stored-text` nodes, for the English words "Check", "citation", "Error"). Do the language switch through the
   app's own TR/EN control in the header: the sheet is modal, so close it, switch, reopen it. `setUiLanguage` in the Node process does not change the browser app; use it only for the
   label-function assertions `report.spec.ts` already makes that way, and keep those two kinds of test apart.
g. **Forbidden words and a11y.** A scan of the UI-owned text of the panel, the form and the history in states a to c (every element except `data-stored-text` nodes: stored claim text,
   anchor text, `detail`, source titles, keys; those are shown as stored and may contain any word) finds none of: verified, validated, confirmed, approved, clean, passed, correct,
   "no problems". Keyboard run of a (open Evidence view, Tab to Edit, Enter, type, Cmd/Ctrl+Enter, Tab to the check button, Enter) with `toBeFocused` assertions at the Edit button after
   save and after Escape. The 390 px assertions: `document.documentElement.scrollWidth <= clientWidth` and, for the panel, the form and the history element themselves, `scrollWidth <= clientWidth`, with the form open and
   with a long check list (route a view with 12 items with long `detail` strings). Table I's own horizontal scroller is out of scope.
h. The existing `report.spec.ts`, `candidate.spec.ts`, `report-failed-rows.spec.ts` pass unchanged.

pytest: the one `acknowledge_changes` test above. No other backend test is needed; do not weaken or edit an existing one.

## Checks to run

Focused while developing: `cd apps/web && npm run build && npm run lint` (lint baseline is 17 warnings; no new warning from your files; report the count) and
`DEIXIS_TEST_PYTHON=/Users/huguryildiz/Documents/GitHub/DEIXIS/.venv/bin/python DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance-e3 npx playwright test e2e/report-edit.spec.ts
e2e/report.spec.ts e2e/candidate.spec.ts` (needs a fresh `npm run build`: the fixture server serves `apps/web/dist`). Backend: `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache UV_OFFLINE=1
UV_PROJECT_ENVIRONMENT=/tmp/e3-venv uv run pytest tests/test_report_store.py tests/test_report_claim_links.py tests/test_report_api.py tests/test_report_edit_check.py tests/test_report_export.py -q`.
The full pytest and the full Playwright run are done by the orchestrator. `git diff --check` clean. Print `skill_package_hash` before and after. Remove no file you did not create.

## Report back (concise)

Files changed; the new components and where the label maps live; how you kept the existing "Restore" spec passing (decision 7); the rule codes you labelled and how you verified
them; the exact toast sentences; the final `Edit`-button focus mechanism; the fixture marker change and whether the scripted report validated; every judgement call (plural wording
vs the export's, locale date, `detail` prefix stripping, reading-view fragment only for removed-by-hand claims); test counts and the focused commands you ran; anything you could not
find or run (sandbox limits); and anything E4's scenario sequence must know (field names, selectors, the marker). Do not write decision or note text.
