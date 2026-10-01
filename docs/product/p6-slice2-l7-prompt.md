<!-- PLAN-REVIEW-ROUNDS: gpt-6.1-sol high, r1: hazır değil, 4 high (stale refresh signal is the event cursor not table version, ConfirmDialog has no note slot, cycle fixture needs candidate + earlier run, support-type note overclaim vs forbidden word) + 5 medium, all folded in; r2: düzeltmeyle hazır (0 high; 2 medium folded in: retry checkbox always available, unchecked printed with current true); implementation next -->

# Task: P6 slice 2, batch L7 ("Arayuz"), the Development lines screen

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-l7` (detached at `8091d62`, main with D136). Read `AGENTS.md`,
`CLAUDE.md`, `.impeccable.md` (MANDATORY before touching `apps/web`), `docs/decisions.md` D130 to D136 (top), and
`docs/product/p6-slice2-chain-of-ideas.md`: §3 (rules), §4.1 to §4.6, §12 "Arayuz"/web paragraph, §13 (acceptance scenario), §19 "L7".
Read the L6 prompt `docs/product/p6-slice2-l6-prompt.md` for the exact JSON of the read model (items 8 to 17) and the route rules
(item 18); the TypeScript types in `apps/web/src/api.ts` (lines 7 to 94) mirror it. The scope below was decided by the main session
and binds this prompt; where the code differs from what this prompt says, report it.

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change uncommitted.
Do not invent; report what you could not find. **No real-model calls, no provider calls; the fixture server's scripted model and
synthetic data only.** Do not touch `../DEIXIS`, `.local/`, `TODO.md`, `.vscode/`, `scripts/local_index.py`,
`docs/product/sw-status.md`, ports 8765 and 8858-8864, or the live data directory. Backend tests need `PYTHONPATH=backend:.` and
`UV_CACHE_DIR=/tmp/deixis-uv-cache`. `apps/web/node_modules` in the worktree is a clone made by the orchestrator (leave it; the
orchestrator removes it). The worktree has no `.venv`: for Playwright set `DEIXIS_TEST_PYTHON=/Users/huguryildiz/Documents/GitHub/DEIXIS/.venv/bin/python`
(the specs already set `PYTHONPATH` to the worktree). If your sandbox blocks loopback binds or process spawning, say so and
continue; the orchestrator runs Playwright.

## Why

L1 to L6 built role columns, candidates, the contract, durable decisions, the flow and the read/edit API. No screen shows any of
it. L7 adds the screen: an Evidence sub-view "Development lines" that shows the read model of L6, starts the link-finding run with
its call ceiling, lets the human remove, edit and add links, and shows the field baseline in its own panel. The screen only
presents recorded state. It never claims more than the contract supports: a stored quote is "located text", never "verified"; a
link is "model proposal" or "human decision"; nothing says a work is "foundational", "original" or that a line "ended".

## What is and is not in code (checked on 8091d62)

- In code (backend, do not change): `GET .../lineage` (view), `GET .../lineage/baseline`, `GET .../lineage/plan?retry_failed=`,
  `POST .../lineage/runs` (body `preview_fingerprint`, `retry_failed`; `Idempotency-Key`; 202 returns the run),
  `POST .../lineage/columns` (`api.addDevelopmentColumns` exists), `POST/PUT/DELETE .../lineage/links[/{id}]` (return the fresh view),
  the run kind `lineage_links` (stage `synthesis`, its steps and `runs.target_json`), CSRF and idempotency as the table routes.
- In code (web): `api.ts` has the lineage TYPES only (L6) and `addDevelopmentColumns`; `EvidenceTable.tsx` has the "Add development
  columns" button (line ~281) and the role-column lock hint; `PassageSheet.tsx` opens a passage with highlighted anchors
  (`highlightTexts`); the web labels an unknown run kind as an answer run.
- Not in code: any lineage fetch function, the plan type, any component under `apps/web/src/lineage/`, EN/TR copy for the screen, the
  run-kind and step labels of `lineage_links`, a fixture-server scenario, `apps/web/e2e/lineage.spec.ts`. Check, do not assume. In
  particular read how `ResearchView.tsx`, `Transcript.tsx`, `BackgroundJobs.tsx`, `labels.ts` and `EvidenceTable.tsx` treat `table_fill`
  and `table_columns` runs (active-run banner, pause/cancel/resume, polling, step labels, `kind` special cases) and give
  `lineage_links` the same treatment where it fits; `api/app.py` already excludes `lineage_links` next to `table_fill` at line ~1193.

## Decisions (already taken; do not reopen)

### Placement and structure

1. **Where.** Inside the Evidence tab, for a table that exists, a two-option switch (a tablist or segmented control in the style the
   file already uses) "Table" | "Development lines" next to the table title area. The default is "Table"; the choice is kept per
   table in component state (not persisted). The sub-view renders a new component `apps/web/src/lineage/DevelopmentLines.tsx`
   (with its own small sub-components in `apps/web/src/lineage/` and a `lineage.css` imported where `EvidenceTable.css` is).
   `EvidenceTable.tsx` and `ResearchView.tsx` get the smallest possible edits (the switch, passing `researchId`, `tableId`, the active
   run, `view.sources` / source lookup, `onRunStarted`, `onPassage` opener). Do not restructure them.
2. **One data source.** `api.lineage(researchId, tableId)`, `api.lineageBaseline(...)`, `api.lineagePlan(..., retryFailed)`,
   `api.startLineageRun(..., previewFingerprint, retryFailed, idempotencyKey)`, `api.addLineageLink`, `api.editLineageLink`,
   `api.removeLineageLink` (DELETE with the query parameters of `LineageLinkRemove`). Add the plan response type after reading
   `LineagePlanner.preview` in `workflow/lineage/run.py`; mirror the JSON exactly. Mutations send `Idempotency-Key: crypto.randomUUID()`
   as the other mutations do and return the fresh view, which replaces the screen state (no second fetch). The view is refetched
   whenever the research view's stored event cursor moves (`view.last_event_id`, the signal `EvidenceTable.tsx` already uses at line
   ~187; a cell save does NOT bump the table `version`, and lineage writes publish their own events), when the table version changes,
   when a `lineage_links` run for this table leaves the active state, and on a manual "Refresh" control. This covers a human edit made in
   another tab and a cell, column, scope, selection or PDF change that makes a link stale. Read which events lineage writes and cell
   saves emit and confirm the cursor moves for each (report any that does not, with the file/line); do not add a backend event.
   No polling of its own beyond what the research view already does.
3. **Names, not ids.** Every link, list and cell shows a work as its label from `nodes[svid]`: `source_key` when present (the
   short key the app already shows elsewhere, `SourceKey` component) with the year, plus the title in a title attribute or second line;
   fall back to the title. The title is VISIBLE text wherever a work is named in a list (unplaceable, baseline, not accepted, history), as a keyboard-reachable
   control that opens the existing source sheet exactly as `.impeccable.md` §4 requires for a listed source title (find how the table
   and the answer list do it and reuse it); a `title` attribute alone is not enough. A `nodes[svid].live === false` end is labelled "no longer in this table" in plain text. Never print a raw
   id as the visible text. Components and lists reference rows by `source_version_id`; resolve through `nodes`.

### Sections of the sub-view (top to bottom; every list the model returns is shown, none is hidden, merged or capped silently)

4. **Status block** (from `view.status`, plain sentences and counts, no gauge): which of the three roles exist ("Problem, change and
   uncertainty columns: present / missing: ..."); `live_rows`, `pdf_text_rows` ("rows with stored PDF text"), `nodes_complete`,
   `nodes_partial`, `missing_cells`; `placed_rows` and `unplaced_rows`. The two actions live here:
   - "Add development columns" (reuse `api.addDevelopmentColumns`; shown only while a role is missing; same toast as the table view).
   - "Find development links": enabled only when the three columns exist and no run is active. Click calls `lineagePlan` and shows
     the plan as an inline confirmation card (not a native dialog): number of works it will read (`selected` targets), calls, the
     call ceiling ("at most N model calls", the plan's ceiling field), pairs not sent for budget and the unselected targets as the plan
     states them, the model name as the table fill shows it, and the plan fingerprint is carried into the start request. Buttons
     "Start" and "Cancel". A checkbox "Retry failed pairs" is ALWAYS available beside Find (not conditional on the plan's `failed_unchanged`: a normal preview can have both `selected` and `failed_unchanged` empty while `retry_failed=true` reselects the failed pairs, see `tests/test_lineage_flow.py` ~609); toggling it refetches the plan with `retry_failed`; add a UI test for that case. Start is disabled exactly when `selected.length === 0` (what the backend refuses), with a plain sentence saying why. A plan whose
     targets are all model-free outcomes (zero calls, targets recorded as no candidate) is STARTABLE: calls 0 is shown as "0 model
     calls; the scan is recorded" and Start stays enabled; never disable on `calls === 0` or on a target's `outcome === 'settled'`. A 409 on start (changed plan,
     active run, paused run) shows the backend message in the existing toast/card language and refetches the plan.
   - A short fixed note under the block, EN and TR: "Links are model proposals or human decisions, each recorded with text quoted
     from the later work. Whether the quoted text supports the relation has not been checked." (No other claim about support; the word
     "verified" is not used. `analyst_inference` links exist, so the note must not say the later work stated every link.)
5. **Lines**: for each `components[]` (ordered as given): a heading with the member count and, in plain text, the roots, branches and
   merges ("starts at ...", "branches at ...", "merges at ..." with work labels); a `has_cycle` component says "contains a cycle
   among stored links" in the error tone (it cannot occur by L4, but the flag is reported, never hidden). Then the link rows in
   the order the model gives them ("year order"). Each link row, plain text, one line that wraps: `FROM -> TO` (an arrow glyph
   with an accessible text "to"), relation label, support type ("source stated" / "analyst inference"), and the citation-list state
   ("citation list: present / not in the read list / unresolved / not read"; `edge_state` null prints nothing). Below or beside, one
   line of `what_changed` (the stored text, byte for byte, never rewritten, never truncated without a disclosure control) and the
   author ("model proposal" / "human decision"; `human_edited` prints "human edited" only in text). Branches are shown by indent:
   a link whose `from` is a branch point sits under a small "from X" group heading; a merge target prints "also from Y" listing the other
   incoming `from` labels of the component's `adjacency` (the L6 `in_from`). Pills only for short states; "stale", "human edited", "unchecked"
   and the warnings are PLAIN TEXT, not pills and not a new color vocabulary. The warnings in plain text per link:
   `unexpected_no_citation_edge` ("the later work does not cite the earlier one in its stored reference list"), `year_order_warning`
   ("the later work has an earlier year than the source"), `not_head_ends` ("this version is not the head of its work"; name
   the end), `output_status === 'unverified_draft'` ("draft, not structurally validated"). A link row is a button (keyboard
   focusable) that opens the existing `PassageSheet` at the stored evidence: the first evidence item's passage, its `anchor_text`
   as `highlightTexts`, page from `physical_page` / `printed_label`. A link with several evidence items shows a small list of them
   ("Evidence 1 of 2" controls) inside the opened row (expand/collapse), each opening the sheet. Read how `EvidenceTable.tsx`/`Transcript.tsx`
   open the passage sheet (props, the `Passage` fetch) and reuse that path; add a fetch function only if none exists. If the
   passage cannot be loaded, show the same error card the table cell uses; never fall back to showing the quote as verified text.
   The row's action buttons (Edit, Remove) are separate buttons, not nested inside the row button.
6. **Cross relations** (`cross_relations`, flat list, same link-row component, heading "Independent parallel work" with a one-line
   explanation "stated by the later work as parallel; these do not form lines"). An empty list prints "None." and the section stays
   visible.
7. **Works without a placed link** (`unplaceable`): one entry per work, sorted as given, each with ALL its `reasons` as plain-language
   sentences (a fixed map; see the reason list below), and a disclosure listing `details` (for each: reason sentence, the pair with labels
   where `from`/`to` exist, run and scope revision and recorded time, and the currency sentence of item 10). `last_run` printed as
   "last considered in run of <date>" when present. The fixed copy MUST NOT mean "no continuation exists": for
   `no_candidate` say "no earlier work in this table was found mentioned in its stored text", for `not_run` "no recorded decision for
   this work yet", never "no development", "dead end", "end of line", "foundational". The eleven reasons and their sentences are one
   map in `labels.ts` (or the lineage folder), each with EN and TR text: `not_run`, `no_pdf_text`, `no_candidate`, `no_relation`,
   `insufficient_evidence`, `rejected`, `not_sent_budget`, `step_failed`, `human_removed`, `cross_relation_only`, `stale_only`.
8. **Proposals not accepted** (`not_accepted`): each with the pair labels, `rejection_code` (a fixed sentence map for the codes that
   L4/L5 produce: `anchor_not_found`, `same_work`, `cycle`, `stale_input`, `human_precedence`/`superseded_by_human` and any other code in
   `backend/deixis/workflow/lineage/store.py`; an unknown code prints as the raw code in plain text, never hidden), the proposed
   decision/relation/`what_changed`/support as the model proposed it, `superseded` ("a later decision exists on this pair") and
   `pair_state` in plain text. This is history, not an action list; no accept button (a rejected proposal can only be re-decided by a
   human through "Add link", see item 12).
9. **Citation edges without a mention**: two separate lists, each with its own heading and a count even when zero:
   - `unassessed_edges`: "The stored reference list of the later work names the earlier one, but no mention was found in its
     scanned text." (pair list)
   - `edges_into_unscanned_targets`: "The later work was not scanned for mentions ({no_pdf_text: has no stored PDF text; not_run:
     has not been through a run}); no mention claim is made." (pair list with the `to_reason`)
10. **Run outcomes** (`step_outcomes`; the two filtered lists `not_sent_budget` and `failed_pairs` are shown as their own labelled
    sections AND `step_outcomes` is shown whole, so a chunk-level `step_failed` / `skipped` item is visible; an item may appear in two
    sections, say so with one line). Each item: kind sentence (`failed_pair`: "the model call for this pair failed", `unsent_pair`: "not
    sent: the call budget or message size did not allow it", `step_failed`: "a model call failed for this work's candidates",
    `skipped`: "a chunk was skipped when the run stopped"), the pair or the `to` work, `reason` raw text in a small plain line, run
    date and scope revision, and **currency in plain text from `current` / `stale_reasons` / `unchecked`**:
    `current === true` "the inputs that were checked are unchanged since" (and `unchecked` is printed whenever non-empty, for true, false and null alike: a negative decision can be `current: true` with `unchecked: ["passage_text"]`; render "not checked: passage text" beside it; test this combination), `false` + reasons (`scope_changed` "the question's scope changed", `node_changed`
    "a development cell changed", `passage_changed` "a passage changed") , `null` "not checked: <unchecked names>". Never
    print "current" for `null`. The same currency sentence is used in item 7 details.
11. **History**: `history.stale` ("Links that no longer hold because their inputs changed", each with its `stale_reasons` as sentences:
    `evidence_not_current` "a cited passage is no longer current", `scope_changed`, `node_changed`) and `history.out_of_scope`
    ("Links whose work left this table or the selection"; name the ends in `not_live_ends`). Both reuse the link-row component, are
    collapsed behind a disclosure that shows the count in its summary (the summary is always visible, never zero-hidden), and are
    editable/removable by a human as the API allows (a stale link can be edited or removed; an out-of-scope link can be removed, edit
    is left to the server's answer: send it and show the server's error if any, do not pre-block).
12. **Pair decisions and human actions** (from `pair_decisions` for CAS values):
    - **Remove** on a current/stale link row: `ConfirmDialog` (add a small OPTIONAL content slot, `children`, to `ConfirmDialog.tsx` for the note field; every existing call keeps its behaviour and markup) with the pair names and a note field (optional, 2000), then
      `DELETE` with `expected_version = link.version`, `based_on_revision_id = link.revision_id`. Result: fresh view.
    - **Edit** on a link row: a sheet/dialog (reuse `components/ui` Sheet or Dialog as the column editor does) with relation (the six
      values, labelled), `what_changed` (1 to 500, counter), support type, note (optional, 2000), and the evidence items (see
      "Evidence picker"). Send `PUT` with `expected_version`, `based_on_revision_id`. Saved text is shown as typed. A human edit is
      listed afterwards as "human decision".
    - **Add link** (a button in the sub-view toolbar, plus a row action "Add a link" in the unplaceable list for that work as the
      later or earlier work): a sheet with two selects (earlier work = from, later work = to, both from live rows of `nodes`,
      labelled; selecting the same work disables Save with a text hint), relation, `what_changed`, support type, note, evidence. The CAS value is read
      from `pair_decisions` for that exact (from, to) pair: no entry means `expected_version = 0`; an entry means its `version`. When the
      entry's `decision` is `link` the sheet says "This pair already has a link; edit it instead" and links to the edit action
      (the server also answers 409); when it is `no_relation`, `insufficient_evidence` or `removed`, the sheet says in plain text what the
      current decision is and by whom, and still allows Save (that is what the CAS value is for). An independent_parallel relation needs
      `source_stated`: the form selects `source_stated` and disables the other when that relation is chosen (the server also enforces).
    - **Evidence picker** (add and edit): one to five evidence items, each `{passage_id, quote}`. The passages offered are those of
      the LATER work (`to`) of the pair, the active asset's passages of that version: use `api.assetText` (the asset-text route) for the
      version's active asset; do NOT limit the picker to table-cell evidence (a row with stored PDF text and empty cells must still be
      addable; test it). A version with no active asset text says so in plain text and Save stays disabled. Only `pdf_page` passages of
      the current extraction are offered (the server accepts only current ones; check `passages.kind`/currency in the asset-text payload). The user picks a passage (shown with its page label), sees its text, and either selects
      text in it ("Use selected text" button reading `window.getSelection()` inside the passage box) or types/pastes the quote into a
      textarea. The quote goes to the server as typed; the screen never says it is verified: after a successful save it is
      "located in the later work's text" (the server only accepts located quotes). A 422 shows the backend message under the form
      (the quote could not be located, a passage of another work, a cycle, a non-live end, the same work, an evidence list that is empty or
      over 5), in the language the other forms use for field errors; a 409 shows "This pair changed since you opened it" with a
      "Reload" control that refetches the view and keeps the user's typed text. Keyboard: the picker is a plain list of buttons
      with `aria-pressed`/`aria-current`; focus moves into the sheet on open and back to the invoking button on close.
13. **Baseline** ("Field baseline", a separate button in the toolbar that toggles a separate panel; fetched on first open and on
    refresh): the fixed scope sentence from `scope`; `representatives` (one line each: which version stands for the work and why, `head`
    or `other_version`, no "foundational"); the two lists `most_cited_in_corpus` and `review_in_corpus` each with its `note` (from the server),
    `total`, the first five (`shown`) and a "Show all N" control that reveals `entries`; each entry: label, year, provider count with
    its date (`cited_by_count_at`), `publication_type`, and "cited by N of the works in this table" using
    `cited_by_included_works` (`count` null never prints as 0; the two null causes are told apart from `target_resolved` and `lists_read`: `target_resolved` false
    -> "not counted: this work could not be matched to the identifiers in the stored reference lists", `target_resolved` true and
    `lists_read` 0 -> "not counted: no reference list of the other works was read"; read `baseline.py` for the exact conditions and
    word any other null case as "not counted"; `lists_read` and `other_works` print as "reference lists read: A of B" in plain text); `unknown_count_works` printed as "N works
    have no stored count; they are not ranked and not counted as zero". The panel states "Computed when you open it from stored
    data; no search was made." Not a score; no ordering words other than the list names.
14. **Counts line**: a compact line of `counts` (components, current links, cross relations, stale, out of scope, not accepted,
    unplaced, edges without mention) and the `edge_states` shown in a separate sentence labelled "Citation lists" ("present N, not in
    the read list N, unresolved N, not read N"), explicitly not links.
15. **Empty and partial states.** No table columns: the status block explains and offers the button. All sections render with
    "None." when empty (headings always present, so no list is hidden). Loading: reuse the table view's skeleton/pending style.
    Error loading: the existing error card with Retry. While a `lineage_links` run for this table is active: the sub-view shows the run
    state line from the existing run banner conventions (do not duplicate pause/cancel controls if the research view already shows them;
    check) and disables Find/Add/Edit/Remove while a run is active ONLY if the backend would refuse (it does not for human edits; so do
    NOT disable human edits during a run, they are safe by L4/L5 rules; disable only "Find development links").

### Copy, labels, i18n

16. All UI strings go through `t()` with EN as the key and TR in `i18n.ts`'s `tr` map (read how existing strings are added; Turkish is
    required for every new string, correct and natural). Run-kind label `lineage_links` -> "Development links" / TR; stage `synthesis`
    already has a label; step kinds of the lineage run (`model:lineage_links`, the code steps and the publication step; read the real
    `operation_key`/`kind` strings in `flow.py` and `run.py`) get entries in `labels.ts::stepLabel`; unknown ones must not fall back
    to a misleading answer-run description. Add the `lineage_links` run to any `JOB_KINDS` / active-run logic only where `table_fill` is
    treated the same way and the behaviour fits; justify each place in the report.
17. Forbidden in any string DEIXIS writes: "foundational", "founder", "novel", "original", "continuation" (as a claim), "importance",
    "strength", "score", "verified" for a quote, "proof". Stored source text, titles, quotes, `what_changed` and notes are shown byte
    for byte even if they contain such words. A Playwright check (item 21) scans the rendered screen chrome for the forbidden words
    with a stored title that contains "foundational" in the data and asserts that the title text itself is intact.

### Design (`.impeccable.md` rules apply; read §2 to §10)

18. Editorial tokens only, no literal colors, no new token unless you add it to both `:root` and `.dark` and say so; hierarchy
    from type, weight, spacing and hairlines; no cards-in-cards, no shadows except where a sheet floats; lists are real `<ol>/<ul>` with
    headings (`h3`/`h4`) in a logical order; disclosures are `<details>` or buttons with `aria-expanded`; the arrow glyph in a link row
    is decorative with an `aria-label` text alternative on the row (for example "Nakano13 to Smith15, changes method, source stated");
    every interactive control has a visible focus ring from the existing styles; target size is as the table toolbar's; Tab order follows
    the visual order; `prefers-reduced-motion` honoured (use the existing motion helpers; add no animation that does not).
    Works at 1440 and 390 px in light and dark. The Evidence page already scrolls sideways on a phone (a known pre-existing issue;
    do not fix it); the NEW sub-view must itself not overflow sideways at 390 px (long keys, titles and `what_changed` wrap;
    use `overflow-wrap:anywhere` where needed). The switch and the toolbar buttons wrap, not clip.

### Fixture scenario and tests

19. **Fixture server** (`tests/acceptance/fixture_server.py`, the scripted model `ScriptedCodex.respond`, the OpenAlex/PDF mocks):
    a question marker `[lineage]` (add it to the file header's marker list) that adds six synthetic works A to F and their PDFs
    (note §13: A base with a high count; B and C each mention A in one sentence and extend it; D mentions B but unrelated and a same-surname
    different author of A so the mention finder mis-matches; E mentions none; F cites A only by number `[1]`, with a stored
    `references_read` and a resolved edge to A and no passage that could match A). The scripted model must (a) fill the three role
    cells of every row (`cell_extraction` for the three lineage-role columns, valid JSON per its contract; read the existing
    `table_fill` scripting and the real contract), (b) answer `lineage_links`: `link` for A->B and A->C with a located quote from the later
    work's passage and relation `extends` / `changes_method`, `no_relation` for D, nothing for E and F (no candidates). The exact
    work ids, texts and the expected candidate pairs are written in a comment block in the fixture so they can be read. The text of each
    passage must contain the exact stored quote the script returns (check how L5/L3 tests build a valid `lineage_links` output and what the
    validator requires: located quotes from the later work, `source_stated` needs the candidate's own mention passage, handles).
    Use real `StepInput` data (`si`) to pick passage ids and handles; do not hardcode ids. A second marker `[lineage-reject]` produces a `cycle` rejection in `not_accepted`: publication orders proposals by
    `(to_svid, from_svid)` (`LineageStore.apply_model_proposals`), not by call order, and the validator refuses a decision for a pair
    that is not a candidate, so the variant needs (a) a passage in A's text that mentions B by surname+year or title fragment, so
    B->A is a real candidate, with a usable quote, and (b) A->B published in an EARLIER run (a first run with the base script, then a
    second run on a changed pair set or `retry_failed`, whichever the planner really allows; read `run.py` to find a legal way to
    make a second run ask B->A) so that the later proposal B->A closes a directed cycle against the stored current link. State in the
    fixture comment how the second run is triggered and assert the `cycle` code in the spec. If no legal way exists, report it and
    cover `cycle` in the mocked-JSON test only. Merge (two
    branches into one node), budget-unsent, `step_failed` and the other history cases are NOT driven through the fixture (too
    costly): they are covered by the mocked-JSON rendering test of item 21. Keep every other scenario of the fixture untouched
    (existing Playwright specs must still pass unchanged).
20. **Playwright `apps/web/e2e/lineage.spec.ts`** (own fixture-server instance on an unused port; the existing specs use 8777-8799 and
    8801-8805 and others: grep `PORT =` and pick an unused one, comment it; copy the server class of `lineage-columns.spec.ts`).
    Driven against the real fixture server (the §13 acceptance scenario):
    - start a research with `[lineage]`, let discovery finish, open the Evidence tab, create the table (use the API for speed where
      the other specs do), add development columns, fill the table (the existing table fill route/UI), open "Development lines";
    - "Find development links": the plan card shows works, calls and ceiling; Start; wait for the run; the lines show one component
      with A branching to B and C (assert the link texts, relation, `source stated`, `citation list: present`), D appears in "Works
      without a placed link" with the `no_relation` reason sentence (the fixture must make D's wrong-surname mention a real candidate
      pair that the script answers `no_relation` for; assert exactly that, and the candidate pair texts in the fixture comment), E
      with `no_candidate` (scanned, nothing found), F in `unassessed_edges` (its stored edge to A, F scanned, no mention found);
      if the real backend cannot produce one of these, fix the fixture, not the assertion, and report it;
      no list is missing (all headings visible);
    - clicking the A->B link row opens `PassageSheet` with the anchor highlighted on the stored page (assert the page label and the
      `<mark>` text equals the stored quote);
    - **human actions persist**: remove A->C (confirm), the link leaves the lines and C appears under "Works without a placed link" with
      `human_removed`; reload the page: still removed; "Add link" A->C again with a quote picked from C's passage: link back as "human decision";
      edit its `what_changed`; a quote that is not in C's text gives the 422 message and keeps the typed text; a stale CAS (open the add sheet,
      change the pair through the API, save) shows the 409 text and "Reload";
    - `[lineage-reject]` variant (second research on the same server): the `cycle` rejection is listed with its sentence and pair;
    - the baseline panel opens and shows the scope sentence, the "Show all" control and the unknown-count sentence;
    - keyboard: Tab reaches the switch, Find, a link row, Edit, Remove, Add; Enter on a link row opens the sheet; Escape closes
      sheets and returns focus; the forbidden-word scan of item 17;
    - `prefers-reduced-motion` emulated: the screen works (no animation required to reach any state; assert the sheet opens);
    - 1440 and 390 px, light and dark screenshots into `OUT` for: toolbar+plan card, lines, the lists region, the add sheet, the baseline
      panel. At 390 px assert the NEW sub-view container has `scrollWidth <= clientWidth`.
    Mocked-JSON rendering test in the same file (`page.route` on `**/lineage` GET for a research opened on the fixture server, serving a
    hand-built `LineageView` JSON that matches `api.ts` types): a component with a merge and a branch (diamond), a stale link and an
    out-of-scope link with `not_live_ends` and a non-live node, a `not_head_ends` link, an `unexpected_no_citation_edge` link, a
    `year_order_warning` link, an unverified draft, a cross relation, ALL eleven unplaceable reasons (one work each, and one work with
    several), `details` with `current` true/false/null and every `unchecked` name, a `not_accepted` entry with `superseded` true,
    `unassessed_edges`, `edges_into_unscanned_targets` with both reasons, `step_outcomes` of all four kinds with `not_sent_budget` and
    `failed_pairs` duplicates, a `has_cycle` component, titles/quotes/`what_changed`/notes containing "foundational" returned byte for byte,
    very long unbroken strings. Assert every list heading and every item is visible or reachable through its disclosure, that no `null`
    currency prints "current", and the forbidden-word scan. Take light/dark 390 px screenshots of it.
    Update `lineage-columns.spec.ts` only if the switch breaks its selectors (it must not need to).
21. Existing checks: `cd apps/web && npm run build && npm run lint` (17 warnings baseline, no new ones), the focused spec
    `DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance-l7 DEIXIS_TEST_PYTHON=... npx playwright test e2e/lineage.spec.ts e2e/lineage-columns.spec.ts`
    (see `package.json` for the exact script/config), then the backend files you touched
    (`PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest tests/test_lineage_*.py -n 0` is enough as a smoke; the
    orchestrator runs the full suites). Backend changes: only the fixture server and, if a view-shape gap is found, report it instead of
    editing `workflow/lineage/*` or `api/app.py`.

## Limits of L7 (do not exceed)

No backend change other than `tests/acceptance/fixture_server.py` (and tests it needs). No migration, no contract/method change
(`skill_package_hash` stays `sha256:371fcecb...`), no new route. No graph/canvas drawing, no new color vocabulary, no new ranking or
"importance" display, no auto-accept of a proposal, no model call from a button other than "Find development links" (which only starts
the existing run through the plan). No persistence of UI choices. No report integration (2c). No claim that a quote proves a relation.
Do not fix pre-existing sideways scrolling of the Evidence page.

## Files allowed

`apps/web/src/lineage/*` (new), `apps/web/src/api.ts`, `apps/web/src/i18n.ts`, `apps/web/src/labels.ts`, `apps/web/src/EvidenceTable.tsx`,
`apps/web/src/EvidenceTable.css` or the new `lineage.css`, `apps/web/src/ResearchView.tsx`, `apps/web/src/Transcript.tsx`, `apps/web/src/ConfirmDialog.tsx` (optional content slot only),
`apps/web/src/BackgroundJobs.tsx`, `apps/web/src/PassageSheet.tsx` (only if opening at a stored anchor needs a prop it lacks; keep every existing behaviour),
`apps/web/e2e/lineage.spec.ts` (new), `apps/web/e2e/lineage-columns.spec.ts` (only selectors), `tests/acceptance/fixture_server.py`.
`docs/` is written by the orchestrator.

## Files NOT allowed

`backend/` (everything), `methods/`, `contracts/`, migrations, `tests/*.py` other than the fixture server, `package.json`,
`package-lock.json`, `apps/web/node_modules`, everything in the "do not touch" list above.

## Report at the end

Files changed; the exact request/response types you added; every judgement call (where the switch sits, the passage-open path, the
fixed sentence maps, the evidence picker's passage source, run-kind handling in each place you touched); what the fixture scenario
really produces for D, E, F; what is deferred; everything you could not find or verify; build, lint and Playwright results (counts,
or why not run), and the paths of the screenshots you looked at.
