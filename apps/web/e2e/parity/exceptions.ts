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
const FAINT_TEXT = ['.side h6', '.recents p', '.rrow em', '.composer textarea::placeholder', '.hint', '.menu h6',
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
  { id: 'ok-tone', rule: '§0 rule 4 (D5: the include tone is darker than the mockup)', token: '--tone-include',
    property: 'color', use: 'icon', selectors: ['.recents svg.i.ok', '.methods .ok', '.pill.ok', '.inc', '.ok-t', '.setup .num.ok'],
    mock: { light: '#2e7d4f', dark: '#6cc48f' }, approved: { light: '#2d7a4d', dark: '#6cc48f' },
    states: ['default', 'hover', 'selected'], note: 'Completed, included.' },
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
    container: 'Answer thread, between the action pills and Next steps: "Reviewed by another model: N reviews, M open findings" once a review exists', app: '.answer-thread .review-target-line' },
  { id: 'answer-live-notices', rule: '§0 rule 5 / AGENTS.md (stale scope and pending late full text are marked explicitly)', slice: 'S10',
    container: 'Answer thread notices: "This answer was produced for revision N …" (stale scope) and the status line "Full text that arrived later is being read; an updated version may follow."', app: '.answer-thread .answer-notice, .answer-late-pending' },
  { id: 'sources-cited-tab', rule: '§0 rule 5 (the answer\'s "View N cited sources" opens the Sources panel on its cited works)', slice: 'S10',
    container: 'Sources panel filter strip: "Cited in answer" first, once the latest answer cites a work (the other P5 tabs are S13\'s)', app: '.source-filters' },
  { id: 'english-question', rule: '§2.2 (Q1)', slice: 'S9', container: 'Plan step detail, row "English question for the semantic search" (the Search plan panel is S23b)', app: '.chat-step-detail .step-row' },
  { id: 'seed-pdfs-block', rule: '§2.2 (Q1, D3)', slice: 'S9', container: 'Plan step detail, "PDFs guiding the search" with each PDF\'s use (read only; the choice of PDFs stays under the thread until S23b)', app: '.chat-step-detail .step-seeds' },
  { id: 'prisma-s-export', rule: '§2.2 (Q1)', slice: 'S8', container: 'Export menu, SOURCES group: rows MD and JSON "PRISMA-S search report" after BIB and RIS', app: '.export-placement' },
  { id: 'search-details', rule: '§2.2 (Q1)', slice: 'S9', container: 'Search step detail: per-query rows, then works per source, the arms and the works no search found; the citation chain\'s requests and limits in the chaining step detail', app: '.chat-step-detail .chat-step-note' },
  { id: 'step-time', rule: '§0 rule 5 (each phase\'s duration was on its line)', slice: 'S9', container: 'Last row of every finished step\'s detail: "Time taken"', app: '.chat-step-detail .step-row' },
  { id: 'run-headings', rule: '§0 rule 5 (runs are separate records: each is paused, resumed, cancelled and timed on its own, and its heading is where focus goes when its chip leaves the topbar)', slice: 'S9',
    container: 'Thread: one 30px heading per run ("Ran search & screening", "Ran answer generation", time, duration) above that run\'s steps; the mockup draws one list for the whole sequence', app: '.chat-turn .chat-toggle' },
  { id: 'audit-sample', rule: '§2.2 (Q1)', slice: 'S14', container: 'Funnel panel, below the stages, collapsed', app: null },
  { id: 'development-lines', rule: '§2.2 (Q1)', slice: 'S15a', container: 'Evidence table ⋯ menu', app: null },
  { id: 'text-recovery', rule: '§2.2 (Q1)', slice: 'S12', container: 'Source details ⋯ menu', app: null },
  { id: 'activity-events', rule: '§2.2 (Q1)', slice: 'S14', container: 'Activity panel, under the runs table', app: null },
  { id: 'trash-kinds', rule: '§2.2 (Q1)', slice: 'S26', container: 'Trash flat list, kinds "Evidence table" / "Table template" (same row as Research and Source)', app: null },
  { id: 'trash-source-menu', rule: '§2.2 (Q1)', slice: 'S26', container: 'Trash Source rows, after Delete permanently: a ⋯ button (30px, the mockup `.ghost.sq`) with Open source details, Restore all from this research and Delete all deletable from this research permanently; the source title opens its abstract', app: '.trash-sq, .trash-title' },
  { id: 'trash-tools', rule: '§2.2 (Q1), §0 rule 5', slice: 'S26', container: 'Trash, a toolbar row above the list: filter, All / Deletable / Still cited, research, sort, Group by research, select shown; source rows carry a checkbox before their kind label, a selection bar (restore, delete, clear) sits under the list, and Group by research adds fold head rows. The mockup list has none of them; they keep the removed-source tools of the earlier page', app: '.trash-tools, .trash-pick, .trash-group-head, .trash-page .selection-bar' },
  { id: 'trash-filter', rule: '§2.2 (Q1)', slice: 'S26', container: 'Trash, under the list when it is longer than 50 rows: a \"Show N more\" button (the mockup list has 2 rows)', app: '.trash-showmore' },
  { id: 'library-pager', rule: '§2.2 (Q1)', slice: 'S25', container: 'Pager under the Library table', app: null },
  { id: 'copyright-footer', rule: '§2.2 (Q1)', slice: 'S24', container: 'Bottom of Settings, foot-note style', app: null },
  { id: 'seed-choice-stale', rule: '§2.2 (Q1)', slice: 'S23b', container: 'Search plan panel, "PDFs guiding the search"; stale-seed warn notice in the plan step', app: null },
  { id: 'search-again-new-answer', rule: '§2.2 (Q1)', slice: 'S8', container: 'Topbar ⋯ menu rows "Search again" and "Generate a new answer", above Move to Trash', app: '.research-menu-placement' },
  { id: 'counts-places', rule: '§2.2 (Q1)', slice: 'S11', container: 'unique and included in the Funnel panel; given and cited in the Answering step detail', app: null },
  { id: 'suggestion-research', rule: 'plan H15 / Q4 (a suggestion names the research whose answer it came from)', slice: 'S5b', container: 'Suggested card, under the suggestion, in the Resume card\'s meta-line style', app: '.home-card-source' },
  { id: 'zotero-library-source', rule: '§0 rule 5 / §2.2 (Q1)', slice: 'S6', container: 'Zotero dialog body, between the lead note and the collections: "Zotero on this computer" / "zotero.org"', app: '.zotero-source' },
  { id: 'language-command', rule: '§2.4 (TR/EN placement)', slice: 'S1', container: 'Search palette: Türkçe / English rows when the query asks for "language" or "dil" (the Settings row is S24)', app: null },
  { id: 'jobs-sheet-controls', rule: '§0 rule 5 / §2.2 (Q1)', slice: 'S1', container: 'Jobs sheet job line: Pause / Resume of an OCR run or a PDF collection, and the research title as a link', app: '.job-action, .job-research' },
  { id: 'jobs-sheet-unconfirmed', rule: '§2.3 / AGENTS.md (no success beyond stored state)', slice: 'S1', container: 'Jobs sheet, under Finished: jobs whose own run failed, was cancelled, or could not be read ("Status unknown")', app: null },
  { id: 'toast-dismiss', rule: '§0 rule 5 / §2.2 (Q1)', slice: 'S1', container: 'Toast, after the text and the Undo link: the dismiss button (errors stay until dismissed)', app: '.toast-close' },
  // S11: from 1100px the rail opens the Sources, queue, PDF and table panels; below it (no rail) the ⋯ menu keeps those rows.
  { id: 'panel-menu-rows', rule: '§0 rule 5 (every live feature keeps working)', slice: 'S11',
    container: 'Topbar ⋯ "Research actions" below 1100px, after Follow-up: Sources, Awaiting your decision, Get more full text and Evidence table with their counts, and a row per older report version and evidence report (the rail lists them from 1100px); Candidates and Follow-up keep their counts (dataText)', app: '.research-menu-placement' },
  { id: 'rail-funnel-opens-sources', rule: '§0 rule 5 (the Funnel panel is S14; its flow counts and search report are in the Sources panel today)', slice: 'S11',
    container: 'Rail box "From search to answer": Open and the five bars open the Sources panel until the Funnel panel (P41) exists', app: null },
  { id: 'rail-waiting-pdf-row', rule: '§0 rule 5 / §2.2 (works waiting for the person\'s PDF are part of "Awaiting you", S5)', slice: 'S11',
    container: 'Rail box "Waiting for your decision", after the queue rows: "N waiting for a PDF" opens the PDFs panel; "N waiting for you" closes a list cut at eight rows', app: null },
  { id: 'rail-metadata-depth', rule: '§0 rule 7 (an included work with no abstract and no PDF is not "abstract only")', slice: 'S11',
    container: 'Rail box "How deeply sources were read": a third legend entry "Metadata only" when a source has neither', app: null },
  { id: 'run-controls', rule: '§0 rule 5 (every live feature keeps working)', slice: 'S9',
    container: 'Topbar, beside Pause: Cancel of a live run (the mockup has no way to stop a live run). Resume run and Cancel run of a paused or stopped run are in the notice under its steps (R18)', app: '.run-strip .run-strip-cancel' },
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
  // S10: the answer in the thread (R22-R29, R32).
  { id: 'answer-compare', rule: '§2.3 (no comparison is drawn until the answer diff, P4, exists: S21)', mock: 'Compare with V1', app: 'Open V1 (opens the earlier version\'s report)' },
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
  { id: 'run-chip-panel', rule: '§2.3 (a sentence names only what exists)', mock: 'Open the Candidates / Follow-up / Evidence tab to control this run (live app, no mockup element)', app: 'Open the Candidates / Follow-up / Evidence table panel to control this run' },
]

/** Geometry axes a pair may not compare because the position follows content the slice must change: a §2.3 copy
 *  change that wraps differently, or a §2.2 placement above the element. The other axes are still checked (±2 px). */
// `widths`, when given, limits the exception to those viewport widths; every other width compares all axes.
export type GeometryException = { id: string; rule: string; pairs: string[]; axes: Array<'x' | 'y' | 'width' | 'height'>; widths?: number[]; note: string }
export const GEOMETRY_EXCEPTIONS: GeometryException[] = [
  { id: 'setup-rows-y', rule: '§2.3 (copy changes setup-leaves and setup-proxy) and §0 rule 2 (example-setup row)',
    pairs: ['home-first.setup-num', 'home-first.setup-num-ok', 'home-first.connect', 'home-first.ready', 'home-first.add'], axes: ['y'],
    note: 'The setup rows sit under the replaced head sentence, and the proxy row holds the replaced proxy sentence; both wrap differently from the mockup at 390 px. x, width and height are compared.' },
  // S3: the palette and the keys dialog leave out the rows of DEFERRED_TARGETS, and the palette's recent rows are as many
  // as the fixture's researches, so the rows below them sit higher than in the mockup.
  { id: 's3-rows-y', rule: 'DEFERRED_TARGETS funnel-key-palette, funnel-key-dialog, followup-send-key; §0 rule 1 (recent rows are data)',
    pairs: ['palette.headings', 'palette.page-rows', 'palette.page-keys', 'palette.goto-rows', 'palette.goto-keys', 'keys.headings', 'keys.labels', 'keys.keys', 'keys.kbd'], axes: ['y'],
    note: 'Rows after a left-out row, or after the recent research rows, move up; x, width and height are compared.' },
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
  { id: 'rail-rows-y', rule: '§0 rule 1 (a list has as many rows as the data has)',
    pairs: ['research.rail-funnel', 'research.rail-boxes', 'research.rail-depth'], axes: ['y'],
    note: 'The Artifacts box lists every report version and table the research has (the fixture has V1, V2 and one table, the mockup one report row and one table), so the boxes below it sit lower; x, width and height are compared.' },
  { id: 'rail-artifacts-height', rule: '§0 rule 1 (a list has as many rows as the data has)', pairs: ['research.rail-artifacts'], axes: ['height'],
    note: 'The Artifacts box has one row per report version, table and evidence report the research has; x, y and width are compared.' },
  { id: 'rail-depth-scope-height', rule: '§2.3 (S11 review item 2: the depth box names its scope, the works given to the latest report)', pairs: ['research.rail-depth'], axes: ['height'],
    note: 'The "How deeply sources were read" box carries one line more than the mockup ("Works given to the latest report (VN)"), so it is taller. Only this box: the other rail boxes keep their height check. x and width are compared, y as rail-rows-y says; rail.spec checks the line.' },
  { id: 'trash-rows-y', rule: '§0 rule 1 (row notes are data: the dates and titles come from the records) and PLACEMENTS trash-source-menu',
    pairs: ['trash.restore', 'trash.delete'], axes: ['y'],
    note: 'The buttons sit in the middle of their row, and a row is as tall as its note wraps (a source note is longer than the mockup\'s example). x, width and height are compared.' },
  { id: 'trash-confirm-buttons-y', rule: 'COPY_CHANGES trash-confirm-research and trash-confirm-source',
    pairs: ['trash-confirm.buttons', 'trash-confirm.icon'], axes: ['y'],
    note: 'The icon is centred on the notice and the buttons sit under the confirm text, which says more than the mockup\'s and wraps onto more lines. x, width and height are compared.' },
  { id: 'zotero-foot-buttons-y', rule: '§2.2 (placement zotero-library-source) and §2.3 (copy changes zotero-lead, zotero-account, zotero-count)',
    pairs: ['zotero.foot-buttons'], axes: ['y'],
    note: 'The footer sits below the library switch row and the replaced notes, whose wrapped height differs from the mockup; x, width and height are compared.' },
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
  { id: 'funnel-key-palette', rule: 'S3 (no key or command without a real target)', selector: '#palList button[data-pal="panel:funnel"]', slice: 'S14',
    note: 'Palette row "Open search funnel" (F): the Funnel panel (P41) does not exist yet.' },
  { id: 'funnel-key-dialog', rule: 'S3 (no key or command without a real target)', selector: '.keys > span:nth-of-type(19), .keys > span:nth-of-type(20)', slice: 'S14',
    note: 'Keys dialog row "Search funnel · F", under ON A RESEARCH: the Funnel panel (P41) does not exist yet.' },
  { id: 'export-pdf-row', rule: 'S8 (never a row that does nothing; print is wired in S27)', selector: '.menu button.fmt[data-msg^="Report saved as PDF"]', slice: 'S27',
    note: 'Export menu, REPORT group: "PDF · Portable document". The print path (print.css + window.print) is not reachable from the UI yet.' },
  { id: 'edit-plan-step', rule: 'S9 (never a link that does nothing)', selector: '.step-detail [data-panel="plan"], .notice [data-panel="plan"]', slice: 'S23b',
    note: 'Plan step detail and too-broad notice: "Edit plan". The Search plan panel (P42) does not exist yet.' },
  { id: 'funnel-not-read-link', rule: 'S9 (never a link that does nothing)', selector: '.step-detail [data-panel="funnel"]', slice: 'S14',
    note: 'Screening step detail: "N not read" is plain text until the Funnel panel (P41) exists.' },
  { id: 'rail-usage-box', rule: 'S11 (RL8 is S27: the usage figures need the S16 routes wired)', selector: '.rail .box:last-child', slice: 'S27',
    note: 'Rail box "Usage": model calls against the limit and the OpenAlex budget today.' },
  { id: 'next-steps-followup-row', rule: 'S10 (never a row that does nothing)', selector: '.follow [data-turn]', slice: 'S22b',
    note: 'Next steps row that asks a follow-up question (R28 → R30/R31): the follow-up turns do not exist yet.' },
  { id: 'followup-send-key', rule: 'S3 (no key or command without a real target)', selector: '.keys > span:nth-of-type(27), .keys > span:nth-of-type(28)', slice: 'S22b',
    note: 'Keys dialog row "Send follow-up · ⌘ ↵", under IN A TEXT BOX: the follow-up composer (R30) does not exist yet.' },
]
