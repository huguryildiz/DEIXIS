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
  '.pal-list h6', '.pal-list button em', '.pal-foot']
// The mockup's icons and marks that use `--faint`: the app keeps D5's `--faint`, held at 3:1 for icons.
const FAINT_ICON = ['.recents svg.i', '.th-b svg.i', '.search', '.pal-in', '.refs li::before', '.dmeta>span+span::before']
// `--warn` text on the `--warn-bg` tint in the mockup: below 4.5:1, so text on a tint uses `--warn-ink` (D5).
const WARN_ON_TINT = ['.cnt', '.status.warn', '.runchip.warn', '.waitchip', '.v-part', '.seg button.on.unc', '.lockb',
  '.cst.narrowed', '.rel.partly', '.edited']
// `--warn` as a tone on the page (icons, short labels): the app keeps D5's darker `--tone-uncertain`.
const WARN_TONE = ['.recents svg.i.wn', '.step.att>button', '.notice.warn>svg.i', '.box.warnbox h5', '.pill.warn', '.unc',
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
    property: 'color', use: 'icon', selectors: ['.recents svg.i.ok', '.methods .ok', '.pill.ok', '.inc', '.ok-t'],
    mock: { light: '#2e7d4f', dark: '#6cc48f' }, approved: { light: '#2d7a4d', dark: '#6cc48f' },
    states: ['default', 'hover', 'selected'], note: 'Completed, included.' },
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
  { id: 'mockup-toast', rule: '§0 rule 2 (the state switcher announces itself in a toast)', selector: '.toast' },
  { id: 'not-in-mockup-rows', rule: '§0 rule 2 ("N more works … are not shown in this mockup")', selector: '.more-row' },
]

/** Live features with no mockup element, placed in the nearest mockup container (§2.2, Q1). `app` is the selector of
 *  the extra element in the app, filled by the slice that places it; until then the entry documents the placement. */
export type Placement = { id: string; rule: string; slice: string; container: string; app: string | null }
export const PLACEMENTS: Placement[] = [
  { id: 'cloud-models', rule: '§2.2 (Q1)', slice: 'S24', container: 'Settings, tile grid between "Default models" and "On this computer"', app: null },
  { id: 'answer-boundary', rule: '§2.2 (Q1)', slice: 'S9', container: 'Answering step detail and the Methods box', app: null },
  { id: 'english-question', rule: '§2.2 (Q1)', slice: 'S9', container: 'Plan step detail and the Search plan panel', app: null },
  { id: 'seed-pdfs-block', rule: '§2.2 (Q1, D3)', slice: 'S9', container: 'Plan step detail, "PDFs guiding the search"', app: null },
  { id: 'prisma-s-export', rule: '§2.2 (Q1)', slice: 'S8', container: 'Export menu, SOURCES group', app: null },
  { id: 'search-details', rule: '§2.2 (Q1)', slice: 'S9', container: 'Search step detail', app: null },
  { id: 'audit-sample', rule: '§2.2 (Q1)', slice: 'S14', container: 'Funnel panel, below the stages, collapsed', app: null },
  { id: 'development-lines', rule: '§2.2 (Q1)', slice: 'S15a', container: 'Evidence table ⋯ menu', app: null },
  { id: 'text-recovery', rule: '§2.2 (Q1)', slice: 'S12', container: 'Source details ⋯ menu', app: null },
  { id: 'activity-events', rule: '§2.2 (Q1)', slice: 'S14', container: 'Activity panel, under the runs table', app: null },
  { id: 'trash-kinds', rule: '§2.2 (Q1)', slice: 'S26', container: 'Trash flat list, kinds "Evidence table" / "Table template"', app: null },
  { id: 'library-pager', rule: '§2.2 (Q1)', slice: 'S25', container: 'Pager under the Library table', app: null },
  { id: 'copyright-footer', rule: '§2.2 (Q1)', slice: 'S24', container: 'Bottom of Settings, foot-note style', app: null },
  { id: 'seed-choice-stale', rule: '§2.2 (Q1)', slice: 'S23b', container: 'Search plan panel, "PDFs guiding the search"; stale-seed warn notice in the plan step', app: null },
  { id: 'search-again-new-answer', rule: '§2.2 (Q1)', slice: 'S8', container: 'Topbar ⋯ menu rows "Search again" and "Generate a new answer"', app: null },
  { id: 'counts-places', rule: '§2.2 (Q1)', slice: 'S11', container: 'unique and included in the Funnel panel; given and cited in the Answering step detail', app: null },
]

/** Mockup copy replaced because it would be false (§2.3, Q2). The parity check compares structure, not text; behaviour
 *  tests of each state assert the replacement text. */
export const COPY_CHANGES: Array<{ id: string; rule: string; mock: string; app: string }> = [
  { id: 'setup-leaves', rule: '§2.3 (Q2)', mock: 'Nothing leaves this computer except the searches.', app: 'Nothing leaves this computer except the searches and the model calls you set up.' },
  { id: 'read-in-full', rule: '§2.3 (Q2)', mock: 'Read in full', app: 'Full text read' },
  { id: 'read-more-in-full', rule: '§2.3 (Q2)', mock: 'Read more in full', app: 'Get more full text' },
  { id: 'proxy-working', rule: '§2.3 (Q2)', mock: 'Working / VPN required / Access uncertain', app: 'Proxy reachable · article access not checked / Proxy did not answer' },
  { id: 'scopus-check', rule: '§2.3 (Q2)', mock: '(none)', app: 'Scopus full view confirmed / Scopus full view not confirmed / Scopus check could not run' },
  { id: 'guide-plural', rule: '§2.3 (Q2, Q3)', mock: 'PDF guiding the search · its title, abstract and references shape the query. The others are read as sources.', app: 'PDFs guiding the search · their titles, abstracts and references shape the query.' },
  { id: 'scope-academic', rule: '§2.3 (Q2)', mock: 'Searches the connected scholarly sources', app: 'Searches scholarly sources to answer your question. (the model does not pick the providers: code rules route them)' },
  { id: 'scope-pdfs-academic', rule: '§2.3 (Q2, Q3)', mock: 'Searches using a chosen PDF and your question', app: 'Searches using your PDFs and your question. Only included sources are used in the answer. (up to five PDFs guide the search, D3)' },
  { id: 'budget-no-limit', rule: '§2.3 (Q2)', mock: 'N% of today\'s budget', app: '$X left today (when OpenAlex sends no limit header)' },
  { id: 'quota-continue', rule: '§2.3 (Q2, R19)', mock: 'Continue with the N finished searches', app: 'The run went on with the M that finished.' },
  { id: 'find-pdf-proxy-pill', rule: '§2.3 (Q2)', mock: 'TOBB ETÜ proxy', app: 'only the providers actually asked' },
  { id: 'sign-in-terminal', rule: '§2.3 (Q2)', mock: 'Opens sign-in in a terminal', app: 'the CLI login command with Copy' },
]

/** Q3: the composer's single-guide radio becomes check rows, one per eligible PDF (at most five), all checked (D3). */
export const CHECK_ROWS: Array<{ id: string; rule: string; mock: string; app: string | null; slice: string }> = [
  { id: 'guide-check-rows', rule: 'Q3 (D3 kept)', mock: '.guide[role="radiogroup"] input[type="radio"]', app: null, slice: 'S5b' },
]

/** Marks the app draws that the mockup does not, kept for accessibility (WCAG 1.4.1: a selected state is not carried by
 *  a background colour alone). The pairs compare the mockup's elements; these extras are not measured. */
export const APP_ADDITIONS: Array<{ id: string; rule: string; app: string; slice: string }> = [
  { id: 'selected-row-check', rule: 'WCAG 1.4.1 (selection shown by more than a background tint)', app: 'a check mark at the right of the selected row of the scope menu and the depth menu', slice: 'S4' },
]
