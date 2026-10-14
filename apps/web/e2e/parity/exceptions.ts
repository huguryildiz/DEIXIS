// Every difference the parity check allows between the app and the mockup v24 (D8, plan §4.1). Each entry names the
// rule it cites. Anything not listed here fails the check. A slice that needs a new difference adds it here, with its
// rule, in the same commit.

export type Use = 'text' | 'icon' | 'dot' | 'decorative'
export type ThemePair = { light: string; dark: string }

/** A token kept at its D5 value instead of the mockup's (rule 4: contrast beats colour match). Listed by selector (the
 *  mockup CSS selectors where the mockup uses the token this way), CSS property and use. The app's computed value is
 *  compared to `approved` (exact, after alpha compositing), and its contrast is checked by use on the element's actual
 *  background, in both themes and in the hover and selected states the pairs measure: text 4.5:1, a meaning-carrying
 *  icon or dot 3:1. Keeping a token never waives the contrast check. */
export type ColourException = {
  id: string
  rule: string
  token: string               // the app token that holds the approved value
  property: 'color' | 'background-color' | 'border-top-color'
  use: Use
  selectors: string[]         // mockup selectors (tested with Element.matches on the mockup element); '*' = every element
  pairs?: string[]            // parity-map pair ids this also covers explicitly
  mock: ThemePair             // the mockup's value
  approved: ThemePair         // the D5 value the app keeps
  states: Array<'default' | 'hover' | 'selected'>
  note: string
}

// The mockup's text that uses `--faint` (#9aa0a8 / #6f7680). In the app such text uses `--muted` (plan §4.1).
const FAINT_TEXT = ['.side h6', '.recents p', '.rrow em', '.composer textarea::placeholder', '.mini textarea::placeholder', '.hint', '.menu h6',
  '.menu button:disabled', '.menu .badge', '.q time', '.revline', '.step-detail .row>span:last-child', '.next',
  '.usage-line', '.box h5', '.box>button.li em', '.tabs button em', '.nr', '.more-row td', '.loc', '.foot-note', '.pgm',
  '.cell small', '.cell.nrc', '.cell .nrc', '.zcols em', '.elist b', '.hist li small', '.detail h4.sub', '.cols-list button em',
  '.pal-list h6', '.pal-list button em', '.pal-foot', '.keys h6']
// The mockup's icons and marks that use `--faint`: the app keeps D5's `--faint`, held at 3:1 for icons.
const FAINT_ICON = ['.recents svg.i', '.th-b svg.i', '.search', '.pal-in', '.refs li::before', '.dmeta>span+span::before']
// `--warn` text on the `--warn-bg` tint in the mockup: below 4.5:1, so text on a tint uses `--warn-ink` (D5).
const WARN_ON_TINT = ['.cnt', '.status.warn', '.runchip.warn', '.waitchip', '.v-part', '.seg button.on.unc', '.lockb',
  '.cst.narrowed', '.rel.partly', '.edited', '.box.warnbox h5']
// `--warn` as a tone on the page (icons, short labels): the app keeps D5's darker `--tone-uncertain`.
const WARN_TONE = ['.recents svg.i.wn', '.step.att>button', '.notice.warn>svg.i', '.pill.warn', '.unc',
  '.warn-t', '.qcard header b', '.stage .lost b']

export const COLOUR_EXCEPTIONS: ColourException[] = [
  { id: 'muted-text', rule: '§0 rule 4 (D5: --muted stays #5b6475; mockup --muted on --chip fails 4.5:1)', token: '--muted',
    property: 'color', use: 'text', selectors: ['*'], mock: { light: '#6b7280', dark: '#9aa1ab' }, approved: { light: '#5b6475', dark: '#9aa1ab' },
    states: ['default', 'hover', 'selected'], note: 'Metadata, captions and quiet labels, including on the chip surface.' },
  { id: 'faint-text-is-muted', rule: '§0 rule 4 / plan §4.1 (text that uses --faint in the mockup uses --muted)', token: '--muted',
    property: 'color', use: 'text', selectors: FAINT_TEXT, mock: { light: '#9aa0a8', dark: '#6f7680' }, approved: { light: '#5b6475', dark: '#9aa1ab' },
    states: ['default', 'hover', 'selected'], note: '--faint (#828993 / #707781) is approved for icons and hairlines only, never text.' },
  { id: 'faint-icon', rule: '§0 rule 4 (D5: --faint held at 3:1, icons and hairlines only)', token: '--faint',
    property: 'color', use: 'icon', selectors: FAINT_ICON, mock: { light: '#9aa0a8', dark: '#6f7680' }, approved: { light: '#828993', dark: '#707781' },
    states: ['default', 'hover', 'selected'], note: 'Meaning-carrying icons need 3:1 on their actual surface.' },
  { id: 'warn-text-on-tint', rule: '§0 rule 4 (mockup --warn on --warn-bg fails 4.5:1)', token: '--warn-ink',
    property: 'color', use: 'text', selectors: WARN_ON_TINT, mock: { light: '#a2650c', dark: '#e2a54c' }, approved: { light: '#8a5a0b', dark: '#e7c27a' },
    states: ['default', 'hover', 'selected'], note: 'Text on a tinted notice uses the matching -ink token (.impeccable.md §2.1).' },
  { id: 'warn-tone', rule: '§0 rule 4 (D5: the uncertain tone is darker than the mockup)', token: '--tone-uncertain',
    property: 'color', use: 'icon', selectors: WARN_TONE, mock: { light: '#a2650c', dark: '#e2a54c' }, approved: { light: '#985f0b', dark: '#e2a54c' },
    states: ['default', 'hover', 'selected'], note: 'Icons and short tone labels on the page surfaces.' },
  { id: 'plan-query-readonly', rule: 'F18 / D12 (a person edits words, never query text) and WCAG 3.3.2 (a field that cannot be typed in does not look like one that can)', token: '--sidebar-surface',
    property: 'background-color', use: 'text', selectors: ['#pq1', '#pq2'], pairs: ['plan.query'], mock: { light: '#ffffff', dark: '#16181b' }, approved: { light: '#f7f8f9', dark: '#1c1f23' },
    states: ['default'], note: 'The stored Query 1 / Query 2 of the Search plan panel are read-only fields on the sidebar surface; the mockup draws them as editable fields on the page surface. Their muted text keeps 4.5:1 on it.' },
  { id: 'ok-text-on-tint', rule: '§0 rule 4 / .impeccable.md §2.1 (text on a tinted surface uses the matching -ink token)', token: '--ok-ink',
    property: 'color', use: 'text', selectors: ['.seg button.on.inc', '.status.ok'], mock: { light: '#2e7d4f', dark: '#6cc48f' }, approved: { light: '#2f6b45', dark: '#8fd0a4' },
    states: ['default'], note: 'The chosen Include segment of the Sources table and the Activity panel\'s "Completed" status pill: their label on --ok-surface.' },
  { id: 'ok-tone-text', rule: '§0 rule 4 (D5: the include tone is darker than the mockup), as text', token: '--tone-include',
    property: 'color', use: 'text', selectors: ['.prop b.inc'], mock: { light: '#2e7d4f', dark: '#6cc48f' }, approved: { light: '#2d7a4d', dark: '#6cc48f' },
    states: ['default'], note: 'The Model proposal\'s "include" verdict word in the Sources table; text, so 4.5:1 applies.' },
  { id: 'ok-tone', rule: '§0 rule 4 (D5: the include tone is darker than the mockup)', token: '--tone-include',
    property: 'color', use: 'icon', selectors: ['.recents svg.i.ok', '.methods .ok', '.pill.ok', '.inc', '.ok-t', '.setup .num.ok'],
    mock: { light: '#2e7d4f', dark: '#6cc48f' }, approved: { light: '#2d7a4d', dark: '#6cc48f' },
    states: ['default', 'hover', 'selected'], note: 'Completed, included.' },
  { id: 'ok-tone-text', rule: '§0 rule 4 (D5: the include tone is darker than the mockup)', token: '--tone-include',
    property: 'color', use: 'text', selectors: ['.cit .loc .ok-t', '.dmeta .ok-t'], mock: { light: '#2e7d4f', dark: '#6cc48f' }, approved: { light: '#2d7a4d', dark: '#6cc48f' },
    states: ['default'], note: 'S12: short tone words on the page surface, the Citation panel\'s "Located in the passage" and Source details\' "Included"; they keep 4.5:1 as text.' },
  { id: 'ok-text-on-tint', rule: '§0 rule 4 (mockup --ok on --ok-bg is 4.41:1, below 4.5:1)', token: '--ok-ink',
    property: 'color', use: 'text', selectors: ['.st.ok'], mock: { light: '#2e7d4f', dark: '#6cc48f' }, approved: { light: '#2f6b45', dark: '#8fd0a4' },
    states: ['default'], note: 'Text on the green tint uses the matching -ink token (.impeccable.md §2.1): the setup card\'s "Ready".' },
  { id: 'abstract-dot', rule: 'D5 abstract colour (index.css --attr-abstract): approved for dots and icons only', token: '--attr-abstract',
    property: 'color', use: 'dot', selectors: ['.pill.abs', '.v-abs'], mock: { light: '#8b95a5', dark: '#8a94a3' }, approved: { light: '#6e7a8e', dark: '#8a94a3' },
    states: ['default', 'hover', 'selected'], note: 'A source-attribute dot or icon. Reference pills may keep the D5 color-mix foreground.' },
  { id: 'abstract-label', rule: 'D5 abstract colour / plan §4.1: abstract labels use --muted, never --attr-abstract as text', token: '--muted',
    property: 'color', use: 'text', selectors: ['.pill.abs', '.v-abs'], mock: { light: '#8b95a5', dark: '#8a94a3' }, approved: { light: '#5b6475', dark: '#9aa1ab' },
    states: ['default', 'hover', 'selected'], note: 'The words "Abstract only" and similar labels.' },
]

/** Controls that exist only to operate the mockup (§0 rule 2). Their elements are ignored on the mockup side. */
export const EXCLUDED_MOCK_CONTROLS: Array<{ id: string; rule: string; selector: string }> = [
  { id: 'states-switcher', rule: '§0 rule 2', selector: '#statesBtn' },
  { id: 'example-tag', rule: '§0 rule 2', selector: '.mock-tag' },
  { id: 'example-setup', rule: '§0 rule 2', selector: '.setup [data-scen="ok"]' },
  { id: 'mockup-toast', rule: '§0 rule 2 (the state switcher announces itself in a toast)', selector: '.toast:not([data-parity])' },
  { id: 'not-in-mockup-rows', rule: '§0 rule 2 ("N more works … are not shown in this mockup")', selector: '.more-row' },
  { id: 'edit-plan-too-broad', rule: 'S23b (never a link to nothing: a too-broad or empty-vocabulary stop ends before its plan is frozen, so the Search plan panel would hold no plan of it; the rewrite field is the way on, R21)', selector: '.notice [data-panel="plan"]' },
]

/** Live features with no mockup element, placed in the nearest mockup container (§2.2, Q1). `app` is the selector of
 *  the extra element in the app, filled by the slice that places it; until then the entry documents the placement. */
export type Placement = { id: string; rule: string; slice: string; container: string; app: string | null }
export const PLACEMENTS: Placement[] = [
  { id: 'cloud-models', rule: '§2.2 (Q1)', slice: 'S24', container: 'Settings, tile grid between "Default models" and "On this computer"', app: null },
  { id: 'answer-boundary', rule: '§2.2 (Q1)', slice: 'S10', container: 'Answering step detail (S9) and the Methods box, under "Full method" (S10); no longer under the answer card', app: '.chat-step-detail .answer-flow, .methods .answer-flow' },
  { id: 'method-full', rule: '§0 rule 5 (every live feature keeps working)', slice: 'S10',
    container: 'Methods box, after its paragraph: a "Full method" disclosure with the live method sections (approach, search strategy, study selection, extraction, limitations, evidence base and what is not measured)', app: '.methods .method-more' },
  { id: 'answer-review-summary', rule: '§0 rule 5 (every live feature keeps working)', slice: 'S10',
    container: 'Answer thread, between the action pills and Next steps, and the report\'s check lines (S15b): "Reviewed by another model: N reviews, M open findings" once a review exists; it opens the review panel', app: '.answer-thread .review-target-line, .report-document .review-target-line' },
  { id: 'answer-live-notices', rule: '§0 rule 5 / AGENTS.md (stale scope and pending late full text are marked explicitly)', slice: 'S10',
    container: 'Answer thread notices: "This answer was produced for revision N …" (stale scope) and the status line "Full text that arrived later is being read; an updated version may follow."', app: '.answer-thread .answer-notice, .answer-late-pending' },
  { id: 'sources-cited-tab', rule: '§0 rule 5 (the answer\'s "View N cited sources" opens the Sources panel on its cited works)', slice: 'S10',
    container: 'Sources panel filter strip: "Cited in answer" first, then Included, Passed abstract, Undecided, Excluded, Not read (S27) and All, where the mockup has it', app: null },
  { id: 'english-question', rule: '§2.2 (Q1)', slice: 'S9', container: 'Plan step detail, row "English question for the semantic search" (the Search plan panel is S23b)', app: '.chat-step-detail .step-row' },
  { id: 'seed-pdfs-block', rule: '§2.2 (Q1, D3)', slice: 'S9', container: 'Plan step detail, "PDFs guiding the search" with each PDF\'s use (read only; the choice of PDFs stays under the thread until S23b)', app: '.chat-step-detail .step-seeds' },
  { id: 'prisma-s-export', rule: '§2.2 (Q1)', slice: 'S8', container: 'Export menu, SOURCES group: rows MD and JSON "PRISMA-S search report" after BIB and RIS', app: '.export-placement' },
  { id: 'search-details', rule: '§2.2 (Q1)', slice: 'S9', container: 'Search step detail: per-query rows, then works per source, the arms and the works no search found; the citation chain\'s requests and limits in the chaining step detail', app: '.chat-step-detail .chat-step-note' },
  { id: 'step-time', rule: '§0 rule 5 (each phase\'s duration was on its line)', slice: 'S9', container: 'Last row of every finished step\'s detail: "Time taken"', app: '.chat-step-detail .step-row' },
  { id: 'run-headings', rule: '§0 rule 5 (runs are separate records: each is paused, resumed, cancelled and timed on its own, and its heading is where focus goes when its chip leaves the topbar)', slice: 'S9',
    container: 'Thread: one 30px heading per run ("Ran search & screening", "Ran answer generation", time, duration) above that run\'s steps; the mockup draws one list for the whole sequence', app: '.chat-turn .chat-toggle' },
  { id: 'audit-sample', rule: '§2.2 (Q1)', slice: 'S14', container: 'Funnel panel, below the stages and the wider-net notice: the flow line and its PRISMA-S report, then "Audit sample" collapsed', app: '.funnel-panel .flow-block, details.funnel-more' },
  { id: 'development-lines', rule: '§2.2 (Q1)', slice: 'S15a', container: 'Evidence table ⋯ menu, after Add development columns: "Development lines" opens its panel on the table (Back returns)', app: '.table-menu-placement' },
  // S15a: every live table, cell and report feature stays (§0 rule 5).
  { id: 'table-live-parts', rule: '§0 rule 5 (every live feature keeps working)', slice: 'S15a',
    container: 'Evidence table: the run line, the failed-rows notice, Add rows and the table picker when there is more than one table; the ⋯ menu also holds Save as template, Remove all columns, Add rows, Add development columns and Move to Trash; the foot counts rows, columns, cells and proposals', app: '.table-panel > .table-counts' },
  { id: 'cell-live-parts', rule: '§0 rule 5 / AGENTS.md (a person\'s edit stays separate from machine proposals)', slice: 'S15a',
    container: 'Cell panel: "Edit value" beside Recheck, the Details toggle in the meta line, the stored flags, a proposal waiting for review, the edit form and the support note', app: '.cell-detail .dacts .ghost' },
  { id: 'ecite-source-details', rule: '§0 rule 5 (a report chip opened Source details at the cited passage)', slice: 'S15a',
    container: 'Evidence report Citation panel, under the anchor line: "Open in Source details"', app: '.ecite-detail .rowacts' },
  // S15b: every live candidate, review and follow-up feature stays (§0 rule 5).
  { id: 'cands-live-parts', rule: '§0 rule 5 (every live feature keeps working)', slice: 'S15b',
    container: 'Candidates list: Refresh beside Add candidate, the character count in the add form, "In the Trash" cards; one candidate: Refresh in the venue line, the origin notice and "What it was opened from", "Earlier versions", the search list as buttons, the full status disclosure, Provider searches, the search terms, Candidate runs and the card editor', app: '.candidates-list > .acts .ghost + .ghost, .candidate-detail .venue .ib, .candidate-detail details' },
  { id: 'review-live-parts', rule: '§0 rule 5 / AGENTS.md (findings stay proposals; the stored review copy is what was sent)', slice: 'S15b',
    container: 'Review dialog: the target line, the model picker with its connection, the logical steps and per-group token lines and the Not reviewed list in What will be sent; review panel: the list of earlier reviews, Pause/Resume/Cancel, the Not reviewed and Details disclosures, the finding\'s group refs, the text at review time, impact/fix/uncertainty, Apply through the editor and the decision history', app: '.review-dialog .review-model, .review-pane .review-list-row, .review-detail details, .finding .kv2, .finding .review-history' },
  { id: 'followup-live-parts', rule: '§0 rule 5 (every live feature keeps working)', slice: 'S15b',
    container: 'Follow-up panel: Refresh beside the intro, the citing-works box when it is on, the check details disclosure, the missed-check notices after the records, and the Notices, Dismissed and Turned off disclosures; Schedule dialog: the units it reads in a disclosure', app: '.followup-view .followup-intro .ib, .followup-view details, .followup-dialog details' },
  { id: 'sources-selbar-live', rule: '§0 rule 5 (every live feature keeps working)', slice: 'S13',
    container: 'Sources selection bar, after Start table and Add to library: the live "Add to table" menu and "Remove from research"', app: '.selbar .selbar-add-table, .selbar .selbar-remove' },
  { id: 'text-recovery', rule: '§2.2 (Q1)', slice: 'S12', container: 'Source details ⋯ menu, after Copy as BibTeX: Extract text again, Read equations again and Read with OCR (S13: the Sources row actions also hold "Retry text extraction", from the same retry path)', app: '.source-more-menu .source-text-tool' },
  { id: 'report-copy', rule: '§0 rule 5 (every live feature keeps working)', slice: 'S12',
    container: 'Report panel Download menu, after DOCX: "Copy · Markdown to the clipboard" (the report\'s Copy button had no place in the mockup head)', app: '.report-export-menu .export-placement' },
  { id: 'report-check-files', rule: '§0 rule 5 (the cited sources\' .bib/.ris are tied to the report\'s answer)', slice: 'S12',
    container: 'Report check line "Export cited: .bib .ris" downloads the cited sources of this answer version', app: '.report-content .check .export-links' },
  { id: 'activity-events', rule: '§2.2 (Q1)', slice: 'S14', container: 'Activity panel, under the runs table and its foot note: the recorded events', app: '.activity-runs > .activity-panel' },
  // S14: every live queue, PDF and funnel feature stays (§0 rule 5).
  { id: 'queue-live-parts', rule: '§0 rule 5 (every live feature keeps working)', slice: 'S14',
    container: 'Queue panel: the override line under the intro, the kind chips and reason filter above the cards, each card\'s version pill, place and DOI, the two runs with their quotes and page links, the closest text, the cues, "Why it is here", "Open page N in the PDF", the note field, "Show N more", the semantic-support foot note and "Your decisions"', app: '.queue-panel .overrides-line, .queue-panel .queue-filters, .queue-panel .queue-decided' },
  { id: 'pdfs-live-parts', rule: '§0 rule 5 (every live feature keeps working)', slice: 'S14',
    container: 'Get more full text: the included sources part (unread PDFs, included without a PDF with Upload PDF, OCR and Zotero, PDF text in hand), the waiting works with DOI, publisher and Find PDF links and their reading place, the version choice of a dropped file, Your files, and Search again beside the answer button', app: '.pdfs-panel .person-files' },
  { id: 'thread-pdf-note', rule: '§0 rule 5 (the thread said how many included sources lack a PDF before the first answer)', slice: 'S14',
    container: 'Thread, before a first answer: one line "N included sources have no PDF yet; an answer cites them from their abstracts." with "Get more full text" (the readiness block moved into the panel)', app: '.thread-pdf-note' },
  { id: 'trash-kinds', rule: '§2.2 (Q1)', slice: 'S26', container: 'Trash flat list, kinds "Evidence table" / "Table template" (same row as Research and Source)', app: null },
  { id: 'trash-source-menu', rule: '§2.2 (Q1)', slice: 'S26', container: 'Trash Source rows, after Delete permanently: a ⋯ button (30px, the mockup `.ghost.sq`) with Open source details, Restore all from this research and Delete all deletable from this research permanently; the source title opens its abstract', app: '.trash-sq, .trash-title' },
  { id: 'trash-tools', rule: '§2.2 (Q1), §0 rule 5', slice: 'S26', container: 'Trash, a toolbar row above the list: filter, All / Deletable / Still cited, research, sort, Group by research, select shown; source rows carry a checkbox before their kind label, a selection bar (restore, delete, clear) sits under the list, and Group by research adds fold head rows. The mockup list has none of them; they keep the removed-source tools of the earlier page', app: '.trash-tools, .trash-pick, .trash-group-head, .trash-page .selection-bar' },
  { id: 'trash-filter', rule: '§2.2 (Q1)', slice: 'S26', container: 'Trash, under the list when it is longer than 50 rows: a \"Show N more\" button (the mockup list has 2 rows)', app: '.trash-showmore' },
  { id: 'library-pager', rule: '§2.2 (Q1)', slice: 'S25', container: 'Pager under the Library table', app: null },
  { id: 'copyright-footer', rule: '§2.2 (Q1)', slice: 'S24', container: 'Bottom of Settings, foot-note style', app: null },
  { id: 'seed-choice-stale', rule: '§2.2 (Q1)', slice: 'S23b', container: 'Search plan panel, after Sources: "PDFs guiding the search" with each PDF\'s use, the choice of PDFs and its notes. The stale-seed warn notice and "Use current PDF text" sit in a one-line block under the thread, not in the plan step: that step folds once an answer follows, which would hide a notice that needs the person. The block also shows while no readable PDF is chosen and before the first search, with "Choose PDFs" opening the panel', app: '.plan-panel .plan-seeds, .research-seed' },
  { id: 'plan-live-parts', rule: '§0 rule 5 / D12 (the panel says which revision\'s stored plan it shows and what saving does)', slice: 'S23b',
    container: 'Search plan panel: a warn notice naming the rules the stored plan breaks (or the rules a refused save named), a block label above each block\'s chips ("Field or setting", "What is looked for") with the backup words under them, an "Add to" block choice beside Add a word, the English question the semantic search sends for this revision (read only), one line under the queries (preview, stored queries vs edited words, the plan searched with its own words only), the criterion\'s kept parts under it, Crossref\'s PDF-link note under the sources, the conflict notice of a revision saved elsewhere, and "Available when the run ends." beside the buttons', app: '.plan-panel .plan-issues, .plan-panel .kw > small, .plan-panel .plan-add > .lbl:last-child, .plan-panel .plan-english, .plan-panel .plan-note, .plan-panel .plan-crossref, .plan-panel .plan-wait' },
  { id: 'search-again-new-answer', rule: '§2.2 (Q1)', slice: 'S8', container: 'Topbar ⋯ menu rows "Search again", "Search plan" (S23b: opens the Search plan panel, also before the current revision has a plan step) and "Generate a new answer", above Move to Trash', app: '.research-menu-placement' },
  // S27: the wired C features keep the live parts the mockup has no place for (§0 rule 5) and name what they read.
  { id: 'model-down-live-parts', rule: '§0 rule 5 (every stopped run can be cancelled) / AGENTS.md (a fallback is explicit, recorded and presented)', slice: 'S27',
    container: 'Model-down notice (R20): after "Retry this step" and "Choose another model", the live "Cancel run"; above the buttons, one line per model change the person made since the stop (role, from, to, time)', app: '.chat-note .notice-model-change' },
  { id: 'rail-usage-notes', rule: '§2.3 / parity-backlog S16 (a figure names its run and its stored response)', slice: 'S27',
    container: 'Rail Usage box: under the model calls bar "Latest run: <kind>" (the run the calls belong to), and under the OpenAlex figure "Last stored response, HH:MM"', app: '.rail .rail-usage-note' },
  { id: 'sources-notread-more', rule: '§0 rule 1 (a list has as many rows as the data has)', slice: 'S27',
    container: 'Sources "Not read" table: a last row "Show N more" while the never-screened list has more pages, and a listed work this research no longer holds as a row of its stored fields', app: '.sources-panel-box .source-more, .sources-panel-box .source-unlisted' },
  { id: 'counts-places', rule: '§2.2 (Q1)', slice: 'S11', container: 'unique and included in the Funnel panel; given and cited in the Answering step detail', app: null },
  { id: 'suggestion-research', rule: 'plan H15 / Q4 (a suggestion names the research whose answer it came from)', slice: 'S5b', container: 'Suggested card, under the suggestion, in the Resume card\'s meta-line style', app: '.home-card-source' },
  { id: 'zotero-library-source', rule: '§0 rule 5 / §2.2 (Q1)', slice: 'S6', container: 'Zotero dialog body, between the lead note and the collections: "Zotero on this computer" / "zotero.org"', app: '.zotero-source' },
  { id: 'language-command', rule: '§2.4 (TR/EN placement)', slice: 'S1', container: 'Search palette: Türkçe / English rows when the query asks for "language" or "dil" (the Settings row is S24)', app: null },
  { id: 'jobs-sheet-controls', rule: '§0 rule 5 / §2.2 (Q1)', slice: 'S1', container: 'Jobs sheet job line: Pause / Resume of an OCR run or a PDF collection, and the research title as a link', app: '.job-action, .job-research' },
  { id: 'jobs-sheet-unconfirmed', rule: '§2.3 / AGENTS.md (no success beyond stored state)', slice: 'S1', container: 'Jobs sheet, under Finished: jobs whose own run failed, was cancelled, or could not be read ("Status unknown")', app: null },
  { id: 'toast-dismiss', rule: '§0 rule 5 / §2.2 (Q1)', slice: 'S1', container: 'Toast, after the text and the Undo link: the dismiss button (errors stay until dismissed)', app: '.toast-close' },
  // S11: from 1100px the rail opens the Sources, queue, PDF and table panels; below it (no rail) the ⋯ menu keeps those rows.
  { id: 'panel-menu-rows', rule: '§0 rule 5 (every live feature keeps working)', slice: 'S11',
    container: 'Topbar ⋯ "Research actions" below 1100px, after Follow-up: Sources, Awaiting your decision, Get more full text and Evidence table with their counts, Search funnel (S14), and a row per older report version and evidence report (the rail lists them from 1100px); Candidates and Follow-up keep their counts (dataText)', app: '.research-menu-placement' },
  { id: 'rail-waiting-pdf-row', rule: '§0 rule 5 / §2.2 (works waiting for the person\'s PDF are part of "Awaiting you", S5)', slice: 'S11',
    container: 'Rail box "Waiting for your decision", after the queue rows: "N waiting for a PDF" opens the PDFs panel; "N waiting for you" closes a list cut at eight rows', app: null },
  { id: 'rail-metadata-depth', rule: '§0 rule 7 (an included work with no abstract and no PDF is not "abstract only")', slice: 'S11',
    container: 'Rail box "How deeply sources were read": a third legend entry "Metadata only" when a source has neither', app: null },
  { id: 'run-controls', rule: '§0 rule 5 (every live feature keeps working)', slice: 'S9',
    container: 'Topbar, beside Pause: Cancel of a live run (the mockup has no way to stop a live run). Resume run and Cancel run of a paused or stopped run are in the notice under its steps (R18)', app: '.run-strip .run-strip-cancel' },
  { id: 'followup-turn-states', rule: 'D11 / §2.3 (a follow-up the passages do not answer says so; stale and stopped turns are marked)', slice: 'S22b',
    container: 'Follow-up turn, between the step lines and the actions: "The passages in this research do not answer this." (or "… answer part of this."), "Not answered by these passages" with the stored aspects, "Asked under revision N of the question.", the stale-selection line, and the notices of a paused, failed or cancelled turn, an unverified draft or a research with no passage to give', app: '.followup-turn .followup-outcome, .followup-turn .followup-gaps, .followup-turn .followup-note, .followup-turn .followup-notice' },
  { id: 'revise-phone', rule: '§0 rule 5 (every live feature keeps working)', slice: 'S22b',
    container: 'Topbar at ≤820px: Revise question stays as a 30px icon button (the mockup hides it there and revises through the follow-up composer, R30)', app: null },
  { id: 'key-terms-syntax', rule: '§0 rule 5 (the key-terms syntax is how a person writes the blocks the search reads)', slice: 'S8',
    container: 'Revise form, under English key terms: one 11.5px muted line on the block syntax', app: '#revise-key-terms-hint' },
]

/** Mockup copy replaced because it would be false (§2.3, Q2). The parity check compares structure, not text; behaviour
 *  tests of each state assert the replacement text. */
export const COPY_CHANGES: Array<{ id: string; rule: string; mock: string; app: string }> = [
  { id: 'trash-confirm-research', rule: '§2.3 (Q2; §2.2 S19a: a sentence about what deletion removes also says what stays)', mock: 'Its answers, decisions and run history go with it.', app: 'Its answers, decisions, run history, unshared evidence and files go with it. Sources another research holds and items you saved to the library stay.' },
  { id: 'trash-confirm-source', rule: '§2.3 (Q2; S19a: the library record stays when another research holds the source or it is saved)', mock: 'Your decision and notes on it go with it.', app: 'The research loses its record of this source, your decision and notes on it. Its library record, passages and PDF go too, unless another research holds it or you saved it to the library.' },
  { id: 'trash-confirm-table-template', rule: '§0 rule 5 (the mockup asks for research and sources only)', mock: '(none)', app: 'Table: its rows, columns, cells with a value and edits of yours are deleted; passages, files and answers stay. Template: its column definitions are deleted; tables started from it keep their own columns.' },
  { id: 'setup-leaves', rule: '§2.3 (Q2)', mock: 'Nothing leaves this computer except the searches.', app: 'Nothing leaves this computer except the searches and the model calls you set up.' },
  { id: 'rail-table-draft', rule: '§2.3 (Q2: a label names only what the records hold)', mock: 'Evidence table · N sources · M columns   draft', app: 'Evidence table · N sources · M columns (no "draft" label: a table has no draft state in the records)' },
  { id: 'read-in-full', rule: '§2.3 (Q2)', mock: 'Read in full', app: 'Full text read' },
  { id: 'rail-found-unique', rule: '§2.3 (Q2: the bar counts unique works, duplicates merged, not the rows the searches found)', mock: 'Found', app: 'Unique works' },
  { id: 'read-more-in-full', rule: '§2.3 (Q2)', mock: 'Read more in full', app: 'Get more full text' },
  { id: 'proxy-working', rule: '§2.3 (Q2)', mock: 'Working / VPN required / Access uncertain', app: 'Proxy reachable · article access not checked / Proxy did not answer' },
  { id: 'scopus-check', rule: '§2.3 (Q2)', mock: '(none)', app: 'Scopus full view confirmed / Scopus full view not confirmed / Scopus check could not run' },
  { id: 'guide-plural', rule: '§2.3 (Q2, Q3)', mock: 'PDF guiding the search · its title, abstract and references shape the query. The others are read as sources.', app: 'PDFs guiding the search · their titles, abstracts and references shape the query.' },
  { id: 'scope-academic', rule: '§2.3 (Q2)', mock: 'Searches the connected scholarly sources', app: 'Searches scholarly sources to answer your question. (the model does not pick the providers: code rules route them)' },
  { id: 'scope-pdfs-academic', rule: '§2.3 (Q2, Q3)', mock: 'Searches using a chosen PDF and your question', app: 'Searches using your PDFs and your question. Only included sources are used in the answer. (up to five PDFs guide the search, D3)' },
  { id: 'budget-no-limit', rule: '§2.3 (Q2)', mock: 'N% of today\'s budget', app: '$X left today (when OpenAlex sends no limit header)' },
  { id: 'quota-continue', rule: '§2.3 (Q2, R19)', mock: 'Continue with the N finished searches', app: 'The run went on with the M that finished.' },
  { id: 'find-pdf-proxy-pill', rule: '§2.3 (Q2)', mock: 'TOBB ETÜ proxy', app: 'only the providers actually asked' },
  // S12: the report, Citation and Source details panels say only what the records hold.
  { id: 'find-pdf-running', rule: '§2.3 (the lookup is one request; which services it reaches is known only from what it records)', mock: 'Unpaywall, OpenAlex, arXiv, Semantic Scholar, TOBB ETÜ proxy, ticked one by one', app: 'Looking for an open copy… with no service named while it runs; afterwards one pill per service it asked, from its recorded lookups (✓ answered, ⚠ failed), and "Not asked: …" with the reason for each service it recorded without a request (no key or contact setting, the daily budget closed)' },
  { id: 'find-pdf-found', rule: '§2.3 (the version and what the file holds come from the stored file and its extraction)', mock: 'Found an open copy. arXiv, accepted manuscript, N pages. The text is read with the next answer; citations name the copy that was read (the accepted manuscript). It counts as a different version of this work, not as extra evidence.', app: 'Found an open copy. {provider}, {version}, N pages. then, by the stored extraction: Its text was extracted page by page (no OCR); a new answer can read it. Citations name the copy that was read. / Text was extracted from some of its pages … / The file is kept, but it has no text layer to extract, so a new answer cannot read it yet. / The file is kept, but its text could not be extracted, … / The file is kept; its text has not been read yet.' },
  { id: 'find-pdf-none', rule: '§2.3 (the services named are the ones the lookup asked)', mock: 'Checked Unpaywall, OpenAlex, arXiv and Semantic Scholar. The publisher copy may open through your institution.', app: 'Checked {the services asked}. (or "No service could be asked."; the proxy sentence and Open via only when a proxy is set and the work has a DOI)' },
  { id: 'detail-decided-by', rule: '§2.3 (no "two reads" per source is stored; who decided is)', mock: 'Included · two reads', app: 'Included · your decision / model proposal / code rule' },
  { id: 'detail-cited-in', rule: '§2.3 (the count is of the latest answer\'s claims)', mock: 'cited in N claims / not cited', app: 'cited in N claims of Vn / not cited in Vn' },
  { id: 'detail-passed-abstract', rule: '§2.3 (the view has no per-source abstract-stage result)', mock: 'Passed the abstract stage, full text not read', app: 'Undecided' },
  { id: 'cite-open-abstract', rule: '§2.3 (an abstract passage has no full text to open)', mock: 'Open in the full text (for an abstract passage)', app: 'Open the abstract' },
  { id: 'cite-locator', rule: '§2.3 (the stored locator and version of the cited copy)', mock: 'Abstract · Located in the passage · Reviewer: supported', app: '{locator} · {version} · Located in the passage (or "No located anchor: the passage opens without a mark") · Reviewer: {verdict} only when the claim was reviewed' },
  { id: 'report-meta-verdicts', rule: '§2.3 (counts come from the stored claim reviews)', mock: '12 supported · 2 partly supported', app: 'one badge per verdict the claim reviews gave, none before a review' },
  { id: 'claim-basis-mixed', rule: '§2.3 (a claim citing both an abstract and a PDF page says both)', mock: 'From abstract or Full text', app: 'From abstract and Full text for a mixed evidence basis' },
  { id: 'jobs-note', rule: '§2.3 (Q2; late_revision.py skips text that is not eligible)', mock: 'Text read in the background joins the next answer.', app: 'Text read in the background can be used in the next answer if it qualifies.' },
  { id: 'setup-proxy', rule: '§2.3 (Q2, S5b: DEIXIS never fetches through the proxy; links of works waiting for a PDF open through it in the browser)', mock: 'Lets DEIXIS open PDFs your library pays for.', app: 'Lets you open PDFs your library pays for, through its sign-in.' },
  { id: 'setup-sources', rule: '§2.3 (Q2, S5b: "Ready" comes from the connections list; no request to OpenAlex or Crossref is made)', mock: 'OpenAlex and Crossref work without a key.', app: 'OpenAlex and Crossref work without a key. Configured · not tested live.' },
  { id: 'guide-limit', rule: '§2.3 (Q2, Q3, S5b: with more than five checked PDFs the backend keeps five by D3\'s question-word rule; the page says so instead of drawing every chip as a guide)', mock: '(none; every chip reads as guiding)', app: 'Up to five guide the search; DEIXIS keeps the five whose first pages share the most words with your question., and the chips of checked PDFs read "may guide the search"' },
  { id: 'sign-in-terminal', rule: '§2.3 (Q2)', mock: 'Opens sign-in in a terminal', app: 'the CLI login command with Copy' },
  { id: 'zotero-lead', rule: '§2.3 (Q2, S6: one collection per import, D16; its own items only)', mock: 'Choose collections. DEIXIS reads their items and attached PDFs; it never changes your Zotero library.', app: 'Choose a collection. DEIXIS reads its own items (not its sub-collections) and each item’s first readable PDF; it never changes your Zotero library.' },
  { id: 'zotero-account', rule: '§2.3 (Q2, S6: the local app has no key; the zotero.org key is set in .env and its rights are not checked)', mock: 'Connected as the Zotero account in Settings · read-only key.', app: 'Reads Zotero on this computer through its local API · read-only. / Reads the zotero.org library set in .env · read-only.' },
  { id: 'zotero-count', rule: '§2.3 (Q2, S6: the count is Zotero’s numItems; the import skips standalone notes and non-PDF attachments)', mock: 'Import N items (no note on what N counts)', app: 'Import N items, with "Counts are Zotero’s own; standalone notes and non-PDF attachments are skipped, so fewer items may be added." in the foot note' },
  { id: 'zotero-home-join', rule: '§2.3 (Q2, S6: Home imports when the research starts, as included sources)', mock: 'Items join this research as attached sources.', app: 'Items are imported when the research starts and join it as included sources.' },
  { id: 'answer-first-version', rule: '§2.3 (a sentence names only what exists)', mock: 'Answer · Writing a new version', app: 'Answer · Writing the first version (when no answer version exists yet)' },
  { id: 'revline-no-answer', rule: '§2.3 (a sentence names only what exists)', mock: 'Revision N and its answer are kept', app: 'Revision N is kept (when no valid report was written for revision N)' },
  { id: 'revise-above', rule: '§2.3 (live copy; the revise form moved into the bubble, S8)', mock: '(none)', app: 'Revise the question above … (was "below", where the old form sat)' },
  // Live copy, not mockup copy: the run chips named the tabs, which no longer exist (S7a). S8 replaces the chips (R3-R6).
  // S9: the step lines and details say only what the run recorded.
  { id: 'step-read-in-full', rule: '§2.3 (Q2, read-in-full)', mock: 'Read 20 works in full · 14 passed the abstract stage, full text not tried', app: 'Read N works in their full text (selected pages) · M passed the abstract stage, full text not tried' },
  { id: 'step-read-row', rule: '§2.3 (Q2, read-in-full)', mock: 'Open-access PDF found and read · 20', app: 'Full text retrieved · N / Full text read (selected pages) · M' },
  { id: 'step-read-link', rule: '§2.3 (Q2, read-more-in-full)', mock: 'Read more in full', app: 'Get more full text' },
  { id: 'step-screened', rule: '§2.3 (the abstract stage records passed and not passed; works waiting for a person are counted in the queue, not per stage)', mock: 'Screened 50 abstracts twice · 34 passed the abstract stage, 13 excluded, 3 waiting for you', app: 'Screened N abstracts twice · P passed the abstract stage, Q out of scope (Q is the flow\'s out-of-scope buckets, not read minus passed; "twice" only when every abstract read had two reads); the waiting count is a row of the details' },
  { id: 'step-screen-rows', rule: '§2.3 (a sentence names only the operation done)', mock: 'Ranked by similarity, top 50 read / Two reads agree: passes the abstract stage', app: 'Ranked by similarity, top N read (only when the similarity step scored the records; otherwise "Top N of the ranking read") / Passed the abstract stage' },
  { id: 'step-screen-note', rule: '§2.3 (no stored record says a disagreement waits for a person at the abstract stage)', mock: 'Each batch is read twice by the literature model. An abstract alone never includes a work; disagreements wait for you.', app: 'Each batch is read twice by the literature model. An abstract alone never includes a work.' },
  { id: 'step-chain-rows', rule: '§2.3 (each direction records the records returned, not the works it added)', mock: 'Reference lists of 8 seed works · 51 added / Works citing the seeds · 35 added', app: 'Reference lists of N seed works · R records returned / Works citing the seeds · R records returned, then "Works the chain brought · W works, O not found by any search"' },
  { id: 'step-search-rows', rule: '§2.3 (the merge counts are the funnel\'s; with chained works the two counts are named apart)', mock: 'Records merged by DOI · 447 → 326', app: 'Records merged by DOI · R → U (no chained works) / Records retrieved by search · R and Unique works, with the citation chain · U' },
  { id: 'step-stop-texts', rule: '§2.3 (the reason is the notice\'s; the line says where the run stood)', mock: 'Stopped while searching: OpenAlex budget used up / Stopped while screening: the literature model did not answer / Paused before reading full texts', app: 'Stopped while <phase> / Paused while <phase> / Cancelled while <phase>; "Stopped while planning: the question is too broad" as drawn' },
  { id: 'step-next-names', rule: '§0 rule 1 (the mockup lists the later steps by their finished lines, which hold counts not known yet)', mock: 'Next: searched openalex and semantic scholar · 326 unique works, …', app: 'Next: search the providers, follow citations, screen abstracts, read full texts, write a source-linked answer, check citations · stage N of M' },
  { id: 'step-claim-review', rule: '§2.3 (a sentence names only what exists)', mock: 'Claim review by gpt-5.6-luna · 12 supported · 2 partly supported', app: 'Claim review · Not recorded for this answer (when no reviewer model reviewed it)' },
  { id: 'step-unattended', rule: '§0 rule 5 (live copy kept)', mock: 'Nobody reviewed the vocabulary; the fast path went on without asking.', app: 'Nobody reviewed the search vocabulary; the fast path went on without asking.' },
  { id: 'broad-notice', rule: '§2.3 (no stored count for the too-common words)', mock: 'The question\'s words match too many works. "network" and "energy" alone return about 2.1 million records, so the search would not be specific. Rewrite the question with narrower terms.', app: 'Every search term in the question is too common to search on its own, so nothing was searched. Revise the question above with a narrower topic or with key terms, and search again.' },
  // S14: the queue, Get more full text and Search funnel panels say only what the records hold.
  { id: 'queue-intro', rule: '§2.3 (an answer is recorded as the person\'s decision and can be taken back; whether the next answer uses it depends on the work\'s state)', mock: 'These came up while DEIXIS worked. Your answer is recorded and used in the next answer; nothing here was decided for you.', app: 'These came up while DEIXIS worked. Your answer is recorded as your decision and can be taken back; nothing here was decided for you.' },
  { id: 'queue-empty', rule: '§2.3 (the queue holds full-text reading rows, PDF checks and version choices; "every screening disagreement" names a stage that queues nothing)', mock: 'Every screening disagreement, PDF check and version choice has an answer. Your answers are kept with this research.', app: 'No row waits for your decision. Your answers are kept with this research.' },
  { id: 'queue-card-heads', rule: '§2.3 (the rows come from the full-text reading, not from abstract screening)', mock: 'Screening · two reads disagreed', app: 'one head per row kind: Reading · the two reading runs disagreed / Quote check · a quote was not found on its page / Missing part · … / Protocol · results, or only a plan? / PDF check · is this the right file? / Version · … / Look again · you decided this under an earlier question' },
  { id: 'queue-answer-notes', rule: '§2.3 (each note says what the stored answer does, in the words of its toast)', mock: 'Include · Use it when the answer is written / Not sure · Keeps it undecided; it stays out of the answer / PDF is wrong or incomplete · Falls back to the abstract; you can attach the right file', app: 'Yes · Recorded as your own selection in the sources / Not sure · Leaves it awaiting a decision; it does not come back by itself / PDF is wrong or incomplete · The work moves to those waiting for a PDF / PDF is right · The next reading run reads this work; no run starts by itself' },
  { id: 'pdfs-depth-labels', rule: '§2.3 (Q2: "full text" only for a full-text read; the box counts works waiting for the person\'s PDF)', mock: 'Waiting for full text', app: 'Waiting for your PDF' },
  { id: 'pdfs-list-head', rule: '§2.3 (the list holds the works no route found an open copy for, in reading order)', mock: 'Passed the abstract stage, waiting for full text', app: 'N works wait for your PDF (and the included sources part above: Your PDF, not read yet / Included, no PDF yet / PDF text in hand)' },
  { id: 'pdfs-drop-note', rule: '§2.3 (the match reads the DOI or title on a file\'s first pages; no size limit is set by the app)', mock: 'Up to 50 MB each. You confirm where each file goes before anything is read.', app: 'Each is matched to a work by the DOI or title on its first pages; you choose the version and confirm before anything is attached.' },
  { id: 'pdfs-answer-note', rule: '§2.3 (Q2: a file is read by the next reading run, not by the answer; the note counts what is still unread or waiting)', mock: 'N more sources will be read in full. / Collect or upload PDFs first.', app: 'N files you added are not read yet; an answer leaves out a work whose only text they are. / N works still wait for a PDF.' },
  { id: 'funnel-stage-notes', rule: '§2.3 (each stage note is built from the stored counts and the run\'s depth; reading depth is named as selected pages)', mock: '326 from three searches, 86 from one citation round … / Two reads agreed that the abstract meets the criterion … / Full text came from open-access PDFs …', app: '{keyword} from the searches ({rows} records returned), {chained} only from citation chaining … / Works whose current abstract-stage decision is that they may meet the criterion … / Works whose two full-text passes both stored a result in one run. Each pass reads selected pages of the PDF, not the whole text …' },
  { id: 'funnel-lost-lines', rule: '§2.3 (each lost line is a stored flow bucket; works waiting for a person are the queue\'s rows)', mock: 'N never screened, ranked below the limit / N excluded · N waiting for you / N passed the abstract stage, full text not tried', app: 'N never screened / N out of scope by two model reads, by a code rule, surveys by their title, left open at the abstract stage / N waiting for a PDF, with text in hand not read yet, passed the abstract stage full text not tried, waiting for your decision' },
  { id: 'funnel-wider-net', rule: '§2.3 (Q2; the numbers are the server\'s Detailed limits, and the bulk query runs only when Semantic Scholar is searched)', mock: 'Want a wider net? Detailed depth screens up to 100 abstracts and reads up to 40 full texts; it also adds one Semantic Scholar bulk query.', app: 'Want a wider net? Detailed depth screens up to N abstracts and reads up to K works in their full text (selected pages); it also adds one Semantic Scholar bulk query when that source is searched.' },
  { id: 'activity-foot', rule: '§2.3 (Took is the wall time from the first start, pauses included; a time with no event behind it reads not started or not finished)', mock: 'Every step is stored. A paused or interrupted run resumes without repeating model calls that already finished.', app: 'Every step is stored. A paused or interrupted run resumes without repeating model calls that already finished. Took runs from a run’s first start to its end, pauses included.' },
  // S10: the answer in the thread (R22-R29, R32).
  { id: 'answer-compare', rule: '§2.3 (S21: the button opens V2\'s report with its changes since V1; when V1 is not the stored version V2 is compared with, the notice shows "Open V1" instead, never a comparison with another record)', mock: 'Compare with V1', app: 'Compare with V1' },
  // S21: the answer diff (P4). Each line names a stored difference between the two versions; a kind that did not change has no line.
  { id: 'changes-full-text', rule: '§2.3 (read-in-full; the diff compares the passages each version cites)', mock: 'Read in full now: <titles>', app: 'Cited from full text in V{v}, only from abstracts in V{b}: <source keys>' },
  { id: 'changes-badges', rule: '§2.3 (the count and both badges come from the two stored answers)', mock: 'Badges on those claims changed from “From abstract” to “Full text”', app: 'Badge(s) on N claim(s) changed from “{from}” to “{to}”' },
  { id: 'changes-left-out', rule: '§2.3 (the diff compares the answers, not the selection; a dropped source shows as changed citations or claims)', mock: 'N cited source left out after your decision', app: '(no line; "N claims keep their wording but cite different passages", "N claims added", "N claims of V{b} are not in this version:" with the removed claims)' },
  { id: 'changes-limits', rule: '§2.3 (said only when the limits differ)', mock: 'Limits updated (always)', app: 'Limits updated (only when a limit was added or removed); "No differences in claim wording, cited passages, reading depth or limits." when nothing differs; foot line naming what was compared' },
  { id: 'answer-latest', rule: '§2.3 (the records do not say which cited sources V2 read in full that V1 had as abstracts)', mock: 'Answer V2 is the latest. It read N cited sources in full that V1 had only as abstracts. V1 is kept.', app: 'Answer V2 is the latest. V1 is kept.' },
  { id: 'answer-late', rule: '§2.3 (Q2, read-in-full; the records count the sources, not their titles)', mock: 'A late full text produced answer V2. <title> arrived after V1 was written; V2 reads it in full. This happens once per answer. V1 is kept.', app: 'A late full text produced answer V2. Full text for N sources arrived after V1 was written; V2 reads them (selected pages). This happens once per answer. V1 is kept.; "Open the new full text" left out (the view does not name the late file)' },
  { id: 'answer-out-of-date', rule: '§2.3 (no stored count of the changed decisions)', mock: 'This answer is out of date. You changed N source decisions after it was written; the answer still uses the old selection.', app: 'This answer is out of date. Your source selection changed after it was written; the answer still uses the old selection.' },
  { id: 'answer-pdf-replaced', rule: '§0 rule 2 (the "(Here: …)" example) / §2.3 (the view does not name the replaced file)', mock: '… to read the current text. (Here: you attached a new file for X.) + Open the source', app: '… to read the current text. (no example sentence, no "Open the source")' },
  { id: 'answer-clarify-below', rule: '§2.3 (the revise form is in the question bubble above, S8)', mock: 'Revise the question below to continue. No answer was written.', app: 'Revise the question to continue. No answer was written.' },
  { id: 'answer-noinc-line', rule: '§2.3 (the line is where the works stood when the answer started, from its start snapshot)', mock: 'Found 412 · screened 50 · passed the abstract stage 34 · included 0 · read in full 0 · waiting for full text 34', app: 'When the answer started: included N · in your queue N · waiting for a PDF N · full text not read N · criterion not met N' },
  { id: 'answer-nopass-line', rule: '§2.3 (only the included count at the answer\'s start is recorded)', mock: 'Included 3 · with an abstract 0 · with PDF text 0', app: 'Included when the answer started: N' },
  { id: 'answer-live-card', rule: '§2.3 (Q2, read-in-full; a new version reads new full text only when it is the late revision)', mock: 'Writing answer V2… · Reading the new full texts · V1 stays available', app: 'Writing answer V2… · V1 stays available (a person\'s new answer) / Reading the full texts that arrived late · V1 stays available (the late revision)' },
  { id: 'answer-methods', rule: '§2.3 (Q2; every number and sentence from the stored method record)', mock: 'One OpenAlex semantic search and two keyword searches, one round of citation chaining. 50 of 412 works were screened twice … 20 works were read in full text and included. 14 more passed the abstract stage without a full text; they are not included, and where cited they are labelled “From abstract”. Every citation resolves to a stored passage given to this step. Claim support was reviewed by a second model.', app: 'N searches were sent to <providers>, and citation chaining ran. The model read the abstracts of A of F works against the criterion (see what was not read). R works were read in their full text (selected pages); included when the answer started: I. B works were given to the answer from their abstracts only; where cited they are labelled “From abstract”. Every citation resolves … Claim support was reviewed by the reviewer model / was not reviewed by a reviewer model / is being reviewed (the reviewer may be the same model)' },
  { id: 'answer-next-steps', rule: '§0 rule 1 (row text built from real counts, plan R28)', mock: 'Build a table of connectivity requirements, energy models and lifetime metrics / Get full text for the 14 works that passed the abstract stage', app: 'Build an evidence table of the N included sources (Open the evidence table once one exists) / Get full text for the N works the answer read from their abstracts only' },
  { id: 'no-research-opened', rule: '§2.3 (with researches in the list, none has been opened in this browser yet)', mock: 'No research yet · Your questions and their answers will appear here. Set up a model first, then ask a question.', app: 'as drawn when no research exists; "No research opened yet · Open one from Recent research, or start a new one." otherwise' },
  { id: 'sources-rank-pill', rule: '§2.3 (Q2: rank and similarity are signals, labelled as such)', mock: 'rank N · similarity S', app: 'search rank N · similarity S' },
  { id: 'sources-citations', rule: '§2.3 (Q2: the count is OpenAlex\'s, not citations in this research)', mock: 'N citations', app: 'cited by N (OpenAlex)' },
  { id: 'sources-cited-claims', rule: '§2.3 (Q2: counted from the claims of the answer shown)', mock: '(none)', app: 'cited in N claim(s) of VN' },
  { id: 'sources-chosen', rule: '§2.3', mock: 'N sources chosen', app: 'N chosen' },
  { id: 'sources-why-example', rule: '§0 rule 2 (no example text that reads as a stored value)', mock: 'placeholder "e.g. terrestrial network only; no lifetime result"', app: '(no placeholder)' },
  { id: 'sources-proposal', rule: '§2.3 (Q2: built from the stored machine decision of the full-text, else abstract stage)', mock: 'include / passed abstract / uncertain / exclude / not screened + a written reason', app: 'the stored outcome word + its reason code in words + its basis (two full-text reads, or title and abstract); "not read in full" with no basis when the full text is missing, unreadable, waiting to be read or not yet confirmed as the work\'s; "not screened" when no decision exists' },
  // S15a: the Evidence table, cell and evidence report panels say only what the records hold.
  { id: 'cell-history', rule: '§2.3 (the list holds earlier values, proposals and the current value, newest first)', mock: 'Earlier values', app: 'History' },
  { id: 'cell-recheck', rule: '§2.3 (the button rechecks this one cell; the column recheck is DEFERRED_TARGETS column-recheck)', mock: 'Recheck', app: 'Recheck this cell' },
  { id: 'column-remove', rule: '§2.3 (a removed column\'s cells are kept and come back with Undo)', mock: 'Delete column', app: 'Remove column' },
  { id: 'suggest-count', rule: '§2.3 (the suggestion step returns up to eight columns, not three)', mock: 'Three proposals; you accept each one', app: 'Up to eight proposals; you accept each one' },
  { id: 'column-dialog-foot', rule: '§2.3 (the fill shows its call estimate before it starts; the dialog does not fill)', mock: 'Filling reads the text DEIXIS has for each source: up to N calls with gpt-5.6-luna.', app: 'The column starts empty. Fill empty cells reads the text DEIXIS has for each source and shows its calls before it starts.' },
  { id: 'report-write-again', rule: '§2.3 (the next version number is given when the run writes it)', mock: 'Write V{n+1}', app: 'Write a new version' },
  { id: 'ecite-foot', rule: '§2.3 (the report stores the cell value and the passage, not text frozen apart from them)', mock: 'This is the text frozen with the report. Later edits to the evidence table do not change it.', app: 'This is the value and passage stored with the report. Later edits to the evidence table do not change them.' },
  { id: 'ecite-changed', rule: '§2.3 (the notice names the change the report records)', mock: 'The table cell changed after this report. The report still cites the text above.', app: 'the stored evidence-change line of the section, with "Open the current cell"' },
  // S15b: the review, Candidates and Follow-up panels say only what the records hold.
  { id: 'review-stale', rule: '§2.3 (the notice names the stored target kind and its recorded reasons)', mock: 'Written against an earlier text: {reasons}. The findings are kept as they were.', app: 'Written against an earlier {report|answer|candidate}: {reasons}. The findings are kept as they were.' },
  { id: 'review-accepted', rule: '§2.3 / AGENTS.md (an accepted finding changes nothing by itself; the wording names the target)', mock: 'Accepted. Recorded. No text was changed.', app: 'Accepted. Recorded. No text was changed. (report) / No change was made to the answer. / No change was made to the candidate.' },
  { id: 'review-loc', rule: '§2.3 (the passage kind and the normalising note come from the stored anchor)', mock: '{source} · abstract · Located quote; whether it supports the target was not checked.', app: '{source} · Located in the passage[ · after normalising…] · Whether it supports the target was not checked.' },
  { id: 'followup-nothing-new', rule: '§2.3 (the list shows stored records; a check that found nothing says so in its own line)', mock: 'Nothing new since the last check.', app: 'No new record is listed.' },
  { id: 'followup-never-on', rule: '§2.3 (a follow-up that was never enabled is not "turned off")', mock: 'This follow-up is turned off.', app: 'This follow-up is not on. (never enabled) / This follow-up is turned off. (disabled)' },
  { id: 'followup-placeholder', rule: '§2.3 (a follow-up is answered from the passages the research holds; sending it does not revise the question or add PDFs, D11)', mock: 'Ask about anything you see, revise the question, or add PDFs', app: 'Ask about the passages this research has read' },
  { id: 'followup-depth-label', rule: '§2.3 (a follow-up has no depth of its own: it reads at most the passage limit of the research\'s depth)', mock: 'the composer\'s depth menu button (Quick / Standard / Detailed)', app: 'the research\'s depth as a label, with "A follow-up reads at most the passage limit of this research\'s depth." as its title' },
  { id: 'followup-search-saved', rule: '§2.3 ("Search for new works on this" saves a question revision; no search is queued until the person starts one, D11)', mock: 'New search queued as revision N', app: 'Saved as revision N of the question. No search has started; start it with Search again. (Search providers before a first search)' },
  { id: 'followup-next-step-row', rule: '§2.3 / §0 rule 1 (the row\'s question is the answer\'s first stored unanswered aspect; it is put in the composer and sent by the person)', mock: 'Find works that report lifetime in rounds or hours for a fixed k (asked at once)', app: 'the first unanswered aspect of the shown answer, put in the follow-up composer' },
  { id: 'followup-live-step', rule: '§2.3 (no count before the selection is stored)', mock: 'Looked in the 48 passages from this research (spinning while live)', app: 'Looking in the passages from this research (no count) until the selection is stored; then Looked in the N passages, N = the call\'s allowlist' },
  { id: 'followup-old-scope', rule: '§2.3 (the lock reason names why Check now waits)', mock: '(no reason line under an old-scope follow-up)', app: 'the stored rebind reason under the notice, and "Checks wait until you rebind this follow-up to the current question."' },
  { id: 'candidate-searching', rule: '§2.3 (the providers come from the frozen plan, shown in the plan above)', mock: 'Searching OpenAlex and Semantic Scholar, then assessing the kept works against the card…', app: 'Searching, then assessing the kept works against the card…' },
  { id: 'candidate-searches', rule: '§2.3 (the list is every stored search of the version, each a button)', mock: 'Searches (n) · showing the last 5', app: 'Searches (n)' },
  { id: 'run-chip-panel', rule: '§2.3 (a sentence names only what exists)', mock: 'Open the Candidates / Follow-up / Evidence tab to control this run (live app, no mockup element)', app: 'Open the Candidates / Follow-up / Evidence table panel to control this run' },
  // S23b: the Search plan panel says where its plan came from, which revision it belongs to and what the server did.
  { id: 'plan-lede', rule: '§2.3 (the plan is written by the model, by code from the question\'s words or by the person; the sentence says which, and names the revision the plan was searched or saved for, D12)', mock: 'The fast path wrote this plan from your question and ran it without asking. Change anything and search again; the current answer stays with revision N.', app: '"The fast path wrote this plan from your question and ran it without asking." (model) / "Code built this plan from the question’s words and ran it without asking." (code) / "This plan was saved by you." (person), then "Plan frozen for revision B." / "Saved for revision N; no search has frozen it yet." / "Saved for revision N and frozen by its search." (a frozen protocol is not a sent or answered request), then "Change anything and search again: saving makes revision N+1; the current answer stays with revision A."' },
  { id: 'plan-queries-readonly', rule: '§2.3 / F18 (a person edits words; the query is compiled from them by code, D12)', mock: 'Query 1 / Query 2 as editable text fields', app: 'Query N · model / from the question’s words / your plan, read only, as many as the stored plan holds; under them "A preview: …" for a saved plan not yet searched, "The queries above are the stored ones; …" once words are edited, and "Saved, the plan is searched with its own words only: the query built from the question’s words is not searched beside it."' },
  { id: 'plan-words-blocks', rule: '§2.3 / F18 (the plan has two blocks of words; a word added goes to the block chosen)', mock: 'Search words (one list); Add a word', app: 'Search words with "Field or setting" and "What is looked for" lists; Add a word with an "Add to" block choice' },
  { id: 'plan-provider-notes', rule: '§2.3 (each note says what that provider is asked for, from the stored provider row; D12)', mock: 'OpenAlex semantic and keyword · Semantic Scholar abstracts and bulk query · Scopus not set up · needs an institutional key', app: 'OpenAlex "semantic and keyword · required: the search and the citation chain run on OpenAlex" (ticked, locked) · Semantic Scholar "abstracts, and one bulk query at Detailed depth" · Crossref "abstracts" · Scopus "abstracts, once its full view is confirmed"; a provider outside the research\'s sources "not among this research’s sources" and one without its key "not set up · needs a key in Settings" (not tickable)' },
  { id: 'plan-crossref-pdf-links', rule: '§2.3 / D12 limits (full-text acquisition still asks Crossref for PDF links)', mock: '(none)', app: 'Crossref is still asked for PDF links when full text is fetched, even when it is unticked here.' },
  { id: 'plan-search-again', rule: '§2.3 (saving and starting are two server answers; each is reported as it came back)', mock: 'Searching again with the edited plan (revision N)', app: 'Plan saved as revision N of the question. The search started. / Plan saved as revision N of the question. The search did not start: … / The search started with the plan saved for revision N. (unchanged saved plan) / Not saved. The plan breaks these rules: … (draft kept)' },
  // S27: the export rows, the usage figures, the model-down notice, "Not read" and the column recheck say what the records hold.
  { id: 'pdf-row-print', rule: '§2.4 (no PDF writer: the row opens the print dialog) / §2.3', mock: 'PDF row toast "Report saved as PDF, citations as footnotes" / "Evidence report saved as PDF"', app: 'the print dialog opens on the report panel as shown; no toast says a file was saved (the person saves it there); the row\'s title says so' },
  { id: 'usage-box-calls', rule: '§2.3 (calls are the run\'s stored model sessions by role)', mock: 'The models were asked 31 times (limit 60): literature 22, answer 6, reviewer 3.', app: 'The models were asked N times (limit L): the roles with calls, each with its count' },
  { id: 'usage-box-openalex', rule: '§2.3 / F7 (the figure is OpenAlex\'s last stored response; no per-run request count is stored)', mock: 'OpenAlex: 5 requests, 38% of today\'s budget. Semantic Scholar: 26 abstract lookups.', app: 'OpenAlex: P% of today’s budget used, in its last stored response (HH:MM). / $X or N credits left today (no limit header) / no budget figure stored since the daily reset, so today’s budget is not known' },
  { id: 'rail-usage-figures', rule: '§2.3 / F7', mock: 'Model calls 31 / 60 · OpenAlex budget today 38%', app: 'the newest run with a call limit, N / L, named under the bar; OpenAlex P% / $X left / N credits left / not known, with the stored response\'s time' },
  { id: 'model-down-reason', rule: '§2.3 (the notice gives the stored pause reason and service error, not a fixed timeout)', mock: 'The literature model did not answer within 120 seconds. The screening call is marked outcome_unknown and was not retried, so no call runs twice. Search results are kept.', app: 'the stored pause reason and the connection\'s error lines, and "Unfinished: … Resuming repeats it" when a step\'s outcome is unknown' },
  { id: 'not-read-notice', rule: '§2.3 / F12 (counts from the never-screened route; rank and similarity are ordering signals)', mock: 'These works were found but never screened: Standard depth screens the 50 most similar abstracts. 362 works sit below that line; three are shown here. Including one by hand sends it to the next answer.', app: 'These works were found but never screened: {depth} depth screens the top {n} of the ranked list. {total} works sit below that line, listed here in its order; {screenable} of them have an abstract to read. Rank and similarity are the signals the list was ordered by, not relevance.' },
  { id: 'screen-more-count', rule: '§2.3 / F13 (the next run reads at most 40 works that have an abstract)', mock: 'Screen 40 more', app: 'Screen N more, N = min(40, works with an abstract left)' },
  { id: 'column-recheck-calls', rule: '§2.3 (each cell is a cell recheck: 1–2 calls; rows without stored text get none)', mock: 'Recheck this column · 6 calls', app: 'Recheck this column · N rows · 1–2 calls each · model' },
  { id: 'model-line-sessions', rule: '§2.3 / D15 (a finished step names the model it ran on, from its stored sessions)', mock: 'Literature · <model> (one model per role, with effort)', app: 'one entry per model the phase\'s stored calls went to, without effort (not stored per call); while the run can still send, "<Role>, set for the next calls · <model>" when the role now points elsewhere' },
  { id: 'review-again-button', rule: '§2.3 / D15 (a review by another model keeps its requested model; a role change never moves it)', mock: 'Choose another model', app: 'on a stopped review: Review again with another model, which opens the review request for the same target and starts a new review' },
]

/** Geometry axes a pair may not compare because the position follows content the slice must change: a §2.3 copy
 *  change that wraps differently, or a §2.2 placement above the element. The other axes are still checked (±2 px). */
// `widths`, when given, limits the exception to those viewport widths; every other width compares all axes.
export type GeometryException = { id: string; rule: string; pairs: string[]; axes: Array<'x' | 'y' | 'width' | 'height'>; widths?: number[]; note: string }
export const GEOMETRY_EXCEPTIONS: GeometryException[] = [
  { id: 'plan-rows-y', rule: 'PLACEMENTS plan-live-parts (the stored plan\'s rule notice, the block labels, the notes under the queries and Crossref\'s note sit above these rows)', pairs: ['plan.add', 'plan.buttons'], axes: ['y'],
    note: 'Add a word and the two buttons sit below the live parts the mockup has no place for, so their top follows the stored plan. x, width and height are compared (Add a word\'s width: see plan-add-width).' },
  { id: 'plan-add-width', rule: 'PLACEMENTS plan-live-parts ("Add to" block choice beside Add a word, F18: a word goes to the block chosen)', pairs: ['plan.add'], axes: ['width'], widths: [1280],
    note: 'At 1280 the block choice shares the row, so the field is narrower; at 390 the choice wraps under it and the width is compared. x and height are compared at both widths.' },
  { id: 'setup-rows-y', rule: '§2.3 (copy changes setup-leaves and setup-proxy) and §0 rule 2 (example-setup row)',
    pairs: ['home-first.setup-num', 'home-first.setup-num-ok', 'home-first.connect', 'home-first.ready', 'home-first.add'], axes: ['y'],
    note: 'The setup rows sit under the replaced head sentence, and the proxy row holds the replaced proxy sentence; both wrap differently from the mockup at 390 px. x, width and height are compared.' },
  // S3: the palette and the keys dialog leave out the rows of DEFERRED_TARGETS, and the palette's recent rows are as many
  // as the fixture's researches, so the rows below them sit higher than in the mockup.
  { id: 's3-rows-y', rule: '§0 rule 1 (recent rows are data); the keys dialog rows were left out while S22b was not built',
    pairs: ['palette.headings', 'palette.page-rows', 'palette.page-keys', 'palette.goto-rows', 'palette.goto-keys', 'keys.headings', 'keys.labels', 'keys.keys', 'keys.kbd'], axes: ['y'],
    note: 'Rows after a left-out row, or after the recent research rows, move up; x, width and height are compared.' },
  { id: 'followup-question-width', rule: '§0 rule 1 (the question is the person\'s, from the records)', pairs: ['followup-turn.question'], axes: ['x', 'width'],
    note: 'The Question bubble sits at the right and is as wide as its question, which is the fixture\'s, not the mockup\'s example; its type and colour are compared.' },
  { id: 'followup-acts-y', rule: 'PLACEMENTS followup-turn-states; §0 rule 1 (the answer\'s claims and aspects are stored data)', pairs: ['followup-turn.search', 'followup-turn.copy'], axes: ['y'],
    note: 'The turn\'s actions follow its stored prose, the outcome line and the unanswered aspects above them; x, width and height are compared.' },
  { id: 'palette-recent-height', rule: '§0 rule 1 (example data is not copied: the row is a research title from the records)',
    pairs: ['palette.recent-rows'], axes: ['height'],
    note: 'A recent research row wraps its title as the mockup\'s does, so its height follows the title\'s length (the fixture\'s title is longer than the mockup\'s example). x and width are compared.' },
  { id: 's8-menu-rows-y', rule: 'PLACEMENTS panel-menu-rows and search-again-new-answer; DEFERRED_TARGETS export-pdf-row',
    pairs: ['research-menu.trash', 'export-menu.rows'], axes: ['y'],
    note: 'Move to Trash sits below the placement rows; the Export rows after the left-out PDF row move up. x, width and height are compared.' },
  { id: 's8-suggest-phone', rule: '§0 rule 5 (Suggest a short title has no other path; the mockup hides it at ≤820px)', widths: [390],
    pairs: ['title-edit.row', 'title-edit.field', 'title-edit.save', 'title-edit.cancel'], axes: ['x', 'width'],
    note: 'At 390px the rename row keeps Suggest as a 30px icon button, so the row and field are 38px narrower and Save and ✕ sit 38px to the right of the field\'s end; y and height are compared, and every axis at 1280.' },
  { id: 's8-revise-buttons-y', rule: 'PLACEMENTS key-terms-syntax', pairs: ['revise.buttons'], axes: ['y'],
    note: 'Cancel and Save revision sit below the key-terms syntax line; x, width and height are compared.' },
  // S12 Citation panel and Source details: blocks whose size is a record's, and the blocks below them.
  { id: 'cite-work-height', rule: '§0 rule 1 (example data is not copied: the work title is the record\'s)', pairs: ['cite-panel.work'], axes: ['height'],
    note: 'The work\'s title wraps as its length does (the fixture\'s title fits one line, the mockup\'s takes two). x, y and width are compared.' },
  { id: 'cite-below-title-y', rule: '§0 rule 1 (the title and quote are the record\'s)', pairs: ['cite-panel.authors', 'cite-panel.quote', 'cite-panel.mark', 'cite-panel.loc', 'cite-panel.located', 'cite-panel.actions'], axes: ['y'],
    note: 'Everything under the title moves with the title\'s lines, and the locator line and actions also with the quote\'s. x, width and height are compared where the pair checks them.' },
  { id: 'cite-quote-size', rule: '§0 rule 1, §2.3 cite-locator (the quote is the stored passage around its located anchor, about 240 characters each side, not the mockup\'s whole abstract)', pairs: ['cite-panel.quote', 'cite-panel.entry'], axes: ['height'],
    note: 'The quote and so the entry are as tall as the stored passage\'s excerpt. x, y (entry) and width are compared.' },
  { id: 'cite-mark-width', rule: '§0 rule 1 (the mark is the record\'s located anchor)', pairs: ['cite-panel.mark'], axes: ['width'],
    note: 'The marked anchor is as wide as its own text. x is compared.' },
  { id: 'cite-located-x', rule: '§2.3 cite-locator (the locator line names the cited copy\'s version before "Located in the passage")', pairs: ['cite-panel.located'], axes: ['x'],
    note: '"Located in the passage" sits after the version part the mockup does not have. width and height are compared.' },
  { id: 'detail-work-height', rule: '§0 rule 1 (the work title is the record\'s)', pairs: ['detail-panel.work'], axes: ['height'],
    note: 'The title wraps as its length does. x, y (at 1280) and width are compared.' },
  { id: 'detail-venue-phone', rule: '§0 rule 1, §2.3 (the venue line carries the record\'s source key and its stored citation count with its provider)', widths: [390],
    pairs: ['detail-panel.work', 'detail-panel.authors', 'detail-panel.dmeta', 'detail-panel.primary', 'detail-panel.icons', 'detail-panel.tabs', 'detail-panel.docnav'], axes: ['y'],
    note: 'At 390 the venue line ("key · venue · year · cited by N (OpenAlex)") wraps to two lines, so the blocks below sit lower by that line less the title\'s difference. Only their position: their x, width and height (the buttons\' and tabs\' sizes included) are compared, and every axis at 1280.' },
  { id: 'detail-venue-phone-height', rule: '§0 rule 1, §2.3 (as detail-venue-phone)', widths: [390], pairs: ['detail-panel.venue'], axes: ['height'],
    note: 'The venue line itself is two lines tall at 390. x, y and width are compared.' },
  { id: 'detail-access-pill-width', rule: '§0 rule 1 (the page count is the stored file\'s)', pairs: ['detail-panel.pills'], axes: ['x', 'width'],
    note: '"PDF text · N pp." is as wide as its page count (2 in the fixture, 10 in the mockup), and the version pill after it moves by as much. y and height are compared.' },
  { id: 'detail-foot-y', rule: '§0 rule 1 (the text view holds the stored text, not the mockup\'s placeholder document)', pairs: ['detail-panel.foot'], axes: ['y'],
    note: 'The foot line sits under the text view, which is as long as the stored text. x, width and height are compared.' },
  { id: 'changes-box-phone', rule: '§4.1 (the box spans the report document, whose phone padding is the S12 report\'s, not the mockup\'s)', widths: [390],
    pairs: ['report-changes.box'], axes: ['x', 'width'],
    note: 'At 390 the app\'s report document has 18px side padding (S12) and the box fills its width, as the mockup\'s box fills its report\'s; the mockup\'s box starts at x 31 and is 329px wide, the app\'s at x 18 and 354px wide. Its padding, border, radius, colours and type are compared, and every axis at 1280.' },
  { id: 'report-head-phone', rule: '§4.1 (the mockup has no phone layout for this head: at 390 it runs past the screen\'s edge)', widths: [390],
    pairs: ['report-panel.version@390', 'report-panel.style@390', 'report-panel.review@390', 'report-panel.download@390'], axes: ['x', 'y', 'width', 'height'],
    note: 'At 390 the mockup\'s report head keeps Version, Show changes, Citation style and its buttons in one row wider than the screen, so its title has no width and its controls sit off-screen. The app fits the head in the screen; type, colour and icons are compared, geometry is not, and the title is compared at 1280 only. a11y.spec checks the app\'s head controls at 390.' },
  { id: 'rail-rows-y', rule: '§0 rule 1 (a list has as many rows as the data has)',
    pairs: ['research.rail-funnel', 'research.rail-boxes', 'research.rail-depth', 'research.rail-usage'], axes: ['y'],
    note: 'The Artifacts box lists every report version and table the research has (the fixture has V1, V2 and one table, the mockup one report row and one table), so the boxes below it sit lower; x, width and height are compared.' },
  { id: 'rail-artifacts-height', rule: '§0 rule 1 (a list has as many rows as the data has)', pairs: ['research.rail-artifacts'], axes: ['height'],
    note: 'The Artifacts box has one row per report version, table and evidence report the research has; x, y and width are compared.' },
  { id: 'rail-depth-scope-height', rule: '§2.3 (S11 review item 2: the depth box names its scope, the works given to the latest report)', pairs: ['research.rail-depth'], axes: ['height'],
    note: 'The "How deeply sources were read" box carries one line more than the mockup ("Works given to the latest report (VN)"), so it is taller. Only this box: the other rail boxes keep their height check. x and width are compared, y as rail-rows-y says; rail.spec checks the line.' },
  { id: 'rail-usage-height', rule: 'PLACEMENTS rail-usage-notes (the Usage box names its run and its stored response) / §0 rule 1', pairs: ['research.rail-usage'], axes: ['height'],
    note: 'The Usage box carries "Latest run: <kind>" and "Last stored response, HH:MM" under its figures and draws the OpenAlex bar only when OpenAlex sent a limit header, so its height follows the records. x and width are compared, y as rail-rows-y says; rail.spec checks the figures against the stored run and the budget route.' },
  { id: 'trash-rows-y', rule: '§0 rule 1 (row notes are data: the dates and titles come from the records) and PLACEMENTS trash-source-menu',
    pairs: ['trash.restore', 'trash.delete'], axes: ['y'],
    note: 'The buttons sit in the middle of their row, and a row is as tall as its note wraps (a source note is longer than the mockup\'s example). x, width and height are compared.' },
  { id: 'trash-confirm-buttons-y', rule: 'COPY_CHANGES trash-confirm-research and trash-confirm-source',
    pairs: ['trash-confirm.buttons', 'trash-confirm.icon'], axes: ['y'],
    note: 'The icon is centred on the notice and the buttons sit under the confirm text, which says more than the mockup\'s and wraps onto more lines. x, width and height are compared.' },
  { id: 'zotero-foot-buttons-y', rule: '§2.2 (placement zotero-library-source) and §2.3 (copy changes zotero-lead, zotero-account, zotero-count)',
    pairs: ['zotero.foot-buttons'], axes: ['y'],
    note: 'The footer sits below the library switch row and the replaced notes, whose wrapped height differs from the mockup; x, width and height are compared.' },
  { id: 'sources-table-cells-xy', rule: 'S13 (the table\'s column widths follow its rows\' text: an auto table layout)', pairs: ['sources.pill', 'sources.rowact', 'sources.seg', 'sources.seg-buttons'], axes: ['x', 'y'],
    note: 'Inside the source table a control\'s place depends on the data in its row and column; its width and height are still compared.' },
  { id: 'sources-selbar-buttons', rule: '§0 rule 5 (the two live buttons sit between the mockup\'s three)', pairs: ['sources.selbar-buttons'], axes: ['x', 'y'],
    note: 'Start table, Add to library and Clear move along the wrapped bar around Add to table and Remove from research; their width and height are compared.' },
  { id: 'sources-tab-counts', rule: 'S13 (each tab\'s count is the fixture\'s data, not the mockup\'s example count)', pairs: ['sources.tabs'], axes: ['x', 'width'],
    note: 'A tab\'s width follows the digits of its count and the tabs after it move by that; y and height are compared.' },
  { id: 'sources-rowact-target', rule: 'WCAG 2.5.8 (target size: the row actions wrap, so each keeps a 24px target)', pairs: ['sources.rowact'], axes: ['height'],
    note: 'Row actions are 24px tall; the mockup\'s are 18px, below the 24px minimum once they wrap onto several lines.' },
  { id: 'sources-why-wrap', rule: 'S13 (the bar names the excluded work: its title is data and wraps by its length)', pairs: ['sources.why-bar', 'sources.why-field', 'sources.why-buttons'], axes: ['y', 'height'],
    note: 'The reason bar\'s height and the place of its field and buttons follow the wrapped title; x and width are compared.' },
  { id: 'sources-selbar-foot', rule: '§0 rule 5 (the live Add to table and Remove from research stay in the bar; the live extras sit below the table)', pairs: ['sources.selbar'], axes: ['y', 'height'],
    note: 'The bar stays in view at the panel\'s foot (the mockup\'s follows the table, the app has its access and export blocks below the table) and wraps onto a second line with the two live buttons; its width and the buttons\' width and height are compared.' },
  // S14: the queue, PDF, funnel and Activity panels hold the records' content, which is longer than the mockup's examples.
  { id: 'queue-card-content', rule: '§0 rule 5 (every live feature keeps working) and PLACEMENTS queue-live-parts', pairs: ['queue.cards'], axes: ['height'],
    note: 'A card holds what the reading stored for its row: both runs with their quotes and page links, the closest text, the cues, "Why it is here", "Open page N in the PDF" and the note button, so it is taller than the mockup\'s example card. x and width are compared.' },
  { id: 'queue-head-phone', rule: 'COPY_CHANGES queue-card-heads (each kind has its own head, as long as its words)', widths: [390], pairs: ['queue.head'], axes: ['height'],
    note: 'At 390 a head wraps by its kind\'s words: the mockup\'s third card is a version choice, whose long head takes two lines; the fixture\'s third row is a missing part, whose head takes one. x, y and width are compared, and every axis at 1280.' },
  { id: 'queue-answer-y', rule: 'GEOMETRY_EXCEPTIONS queue-card-content', pairs: ['queue.answer'], axes: ['y'],
    note: 'The answers sit under the card\'s stored content. x, width and height are compared.' },
  { id: 'pdfs-included-part', rule: 'PLACEMENTS pdfs-live-parts', pairs: ['pdfs.list-head', 'pdfs.drop', 'pdfs.answer'], axes: ['y'],
    note: 'The included-sources lists (unread PDFs, included without a PDF, PDF text in hand) sit between Collect and the waiting list, and the waiting list has the fixture\'s rows, so the blocks below sit where the data puts them. x, width and height are compared.' },
  { id: 'pdfs-drop-button', rule: 'WCAG 2.1.1 (keyboard: the mockup\'s drop zone is a label, which a keyboard cannot reach)', pairs: ['pdfs.drop'], axes: ['height'],
    note: 'The drop zone holds a "Choose files" button under its note, so a keyboard reaches the file picker; it is taller by that row. x, y (as pdfs-included-part says) and width are compared.' },
  { id: 'funnel-stage-notes', rule: 'COPY_CHANGES funnel-stage-notes, funnel-lost-lines and funnel-wider-net', pairs: ['funnel.stages', 'funnel.notice'], axes: ['y', 'height'],
    note: 'Each stage is as tall as its note and lost line, which are built from the stored counts, and the wider-net notice wraps its longer sentence. x and width are compared, and every stage part\'s type and colour.' },
  // S15b: these rows sit under record content and the live parts kept by PLACEMENTS review-live-parts and
  // followup-live-parts (the target line and model picker, the stored check lines, a finding's group refs, claim text
  // and impact/fix/uncertainty, the units the follow-up reads), so their y follows the records.
  { id: 's15b-rows-under-records-y', rule: '§0 rule 1 (the text above is the record\'s) and §0 rule 5 (live parts above)',
    pairs: ['watch.acts', 'rvpanel.acts', 'rvdlg.buttons', 'sched.buttons'], axes: ['y'],
    note: 'Check now / Schedule… / Turn off, a finding\'s Accept / Dismiss / Defer and the dialog footers follow the stored content above them. x, width and height are compared.' },
  // S15a: the [parity] table holds 6 of the research's included sources, so the report gate's reason stands above the
  // toolbar (the mockup's table holds every included source and has no reason line).
  { id: 'table-toolbar-reason', rule: '§0 rule 1 (the reason comes from the stored table summary) and AGENTS.md (a disabled action says why)', pairs: ['table.toolbar', 'table.wrap'], axes: ['y'],
    note: 'The toolbar and the grid sit under the one-line report reason ("A report needs a filled evidence table: N cells left …"). x, width and height of every button, and x and width of the grid, are compared.' },
  { id: 'table-grid-rows', rule: '§0 rule 1 (a grid has as many rows as the data has, each as tall as its values)', pairs: ['table.wrap'], axes: ['height'],
    note: 'The grid holds the fixture\'s six rows with their stored values and the row heads\' meta lines, so its height follows the data. x and width are compared.' },
  { id: 'table-cell-width', rule: 'S13 sources-table-cells-xy (an auto table layout: a column is as wide as its text)', pairs: ['table.cell-box'], axes: ['width'],
    note: 'A value column is as wide as its header and values, which are the fixture\'s. x, padding and line height are compared.' },
  { id: 'cell-recheck-label', rule: 'COPY_CHANGES cell-recheck', pairs: ['cell.recheck'], axes: ['width'],
    note: 'The button reads "Recheck this cell", so it is wider than the mockup\'s "Recheck". x, y and height are compared.' },
  { id: 'cell-meta-phone', rule: 'PLACEMENTS cell-live-parts (the meta line also holds the Details toggle)', widths: [390], pairs: ['cell.recheck'], axes: ['y'],
    note: 'At 390 the meta line (state, author and depth, model, date, Details) wraps to a second line, so the actions sit one line lower. Every axis is compared at 1280.' },
  { id: 'activity-runs-rows', rule: '§0 rule 1 (a list has as many rows as the data has)', pairs: ['activity.table'], axes: ['height'],
    note: 'The table has one row per run the research recorded. x, y and width are compared.' },
]

/** S6: the mockup's collection checkboxes become radio rows. An import takes one collection (D16, `collection_key`), and
 *  Home holds one chosen collection until the research starts. Same row layout; only the input's type differs. */
export const SINGLE_CHOICE: Array<{ id: string; rule: string; mock: string; app: string; slice: string }> = [
  { id: 'zotero-one-collection', rule: '§0 rule 3 and 5 (one collection per import, D16)', mock: '.zcols input[type="checkbox"]', app: '.zotero-cols input[type="radio"]', slice: 'S6' },
]

/** Q3: the composer's single-guide radio becomes check rows, one per eligible PDF (at most five), all checked (D3). */
export const CHECK_ROWS: Array<{ id: string; rule: string; mock: string; app: string | null; slice: string }> = [
  { id: 'guide-check-rows', rule: 'Q3 (D3 kept)', mock: '.guide[role="radiogroup"] input[type="radio"]', app: '.composer .guide[role="group"] input[type="checkbox"]', slice: 'S5b' },
]

/** Marks the app draws that the mockup does not, kept for accessibility (WCAG 1.4.1: a selected state is not carried by
 *  a background colour alone). The pairs compare the mockup's elements; these extras are not measured. */
export const APP_ADDITIONS: Array<{ id: string; rule: string; app: string; slice: string }> = [
  { id: 'selected-row-check', rule: 'WCAG 1.4.1 (selection shown by more than a background tint)', app: 'a check mark at the right of the selected row of the scope menu and the depth menu', slice: 'S4' },
  { id: 'diff-mark-cues', rule: 'WCAG 1.4.1 (an addition or removal is not told by its tint alone) / 1.3.1 (screen readers)', app: 'the answer diff\'s `ins` is underlined (the mockup\'s has no underline) and `del` keeps its strike-through; each starts with a visually hidden "Added:" or "Removed:" (citations: "Added citation:", "Removed citation:")', slice: 'S21' },
  { id: 'compare-phone-icon', rule: '§4.1 report-head-phone (the mockup\'s head runs past a phone screen)', app: 'below 520px "Show changes"/"Hide changes" is a 30px eye / eye-off icon button whose name stays for screen readers, and Citation style is as wide as its value, so the report head fits a 390px screen', slice: 'S21' },
  { id: 'followup-compose-short-window', rule: 'WCAG 1.4.10 / 2.4.11 (a sticky box must not cover the thread it belongs to)', app: 'in a window 560px tall or less the follow-up composer stays in the flow at the end of the thread instead of sticking to its foot (the parity windows are 844 and 900px tall)', slice: 'S22b' },
  { id: 'keys-off-switch', rule: '§2.4 (single-key shortcuts) / WCAG 2.1.4 (character key shortcuts can be turned off)', app: 'the keys dialog\'s foot: one line with the "Single-key shortcuts" checkbox, kept across reloads (.keys-dialog .keys-foot)', slice: 'S3' },
]

/** Styles the app draws where the mockup draws none, kept for accessibility. The listed properties of the listed pairs
 *  are not compared; every other check of those pairs still runs. */
export const STYLE_EXCEPTIONS: Array<{ id: string; rule: string; pairs: string[]; properties: string[]; note: string }> = [
  { id: 'menu-heading-case', rule: '.impeccable.md §2.4 (small caps labels are sentence-case text uppercased by CSS)', pairs: ['export-menu.headings'], properties: ['text-transform'],
    note: 'The mockup writes REPORT, EVIDENCE TABLE and SOURCES in capitals; the app writes Report, Evidence table and Sources and uppercases them in CSS, so the Turkish labels case-fold correctly. The rendered text is the same.' },
  { id: 'palette-focus-line', rule: 'WCAG 2.4.7 (focus visible; a11y.spec X05 needs an indicator on every focus stop)', pairs: ['palette.field'], properties: ['box-shadow'],
    note: 'While its input has focus the palette field draws a 2px accent line along its bottom edge (inset box-shadow); the mockup\'s field has no focus indicator.' },
]

/** Mockup elements whose target the app does not have yet (S3: a key or row is not shown before the thing it opens
 *  exists). Their mockup elements are left out of the lists they sit in, like the excluded mockup controls. */
export const DEFERRED_TARGETS: Array<{ id: string; rule: string; selector: string; slice: string; note: string }> = [
]
