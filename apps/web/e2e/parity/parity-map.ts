import type { Use } from './exceptions'
import type { FixtureContext } from './gates'

// Which mockup element corresponds to which app element, per surface (plan §4.1). A pair is `active` when the current
// app already matches it within tolerance, or `pending:<slice>` when a later slice of the parity plan changes that part
// of the screen. Pending pairs are counted and printed, not checked. The slice that ports a screen turns its pairs to
// `active` in the same commit.

export type Theme = 'light' | 'dark'
export type Check = 'chrome' | 'content' | 'type' | 'colour' | 'icon'
export type SurfaceId = 'home' | 'research'
export type Status = 'active' | `pending:${string}`

export type Pair = {
  id: string
  surface: SurfaceId
  mock: string              // selector in the mockup
  app: string               // selector in the app
  checks: Check[]           // presence is always checked for an active pair
  status: Status
  /** `fixed`: the mockup's items are the spec (nav, menu rows, tabs, head buttons, toolbars), compared item by item
   *  including fixed text. `data`: rows that come from records; the count is `expected` from the fixture, never the
   *  mockup's example count, and each row is compared with the mockup's first row for layout and style. */
  list?: 'fixed' | 'data'
  expected?: (ctx: FixtureContext) => number
  text?: boolean            // compare fixed text (default: on for fixed lists, off otherwise)
  dataText?: { mock?: string[]; app?: string[] }  // selectors inside the element whose text is data, left out of the comparison
  states?: Array<'hover' | 'selected'>             // interaction states the element has; colour is checked in each
  selected?: { mock: string; app: string }         // the selected item, when `states` has 'selected'
  widths?: number[]         // only at these viewport widths (default: every width)
  unordered?: boolean       // not part of the surface's order check (floating or positioned chrome)
  use?: Use                 // what the `color` property carries, for colour exceptions and contrast (default text)
  icon?: { mock: string; app: string } | Array<{ mock: string; app: string }>  // mockup `P` name ↔ lucide name; per item for a list
  breakpoint?: boolean      // compared at 1024 for visibility and width only (rail, Library third pane, panel, thread)
  why?: string              // for a pending pair: what the slice changes
}

export type Surface = {
  id: SurfaceId
  /** Puts the mockup in this state through its own globals. */
  mock: string
  /** The app URL hash for this state; `{research}` is the [parity] research id. */
  app: string
  /** An app element that shows the state is ready. */
  ready: string
}

export const SURFACES: Surface[] = [
  { id: 'home', mock: "setScenario('ok'); go('home')", app: '#/', ready: '#research-question' },
  { id: 'research', mock: "setScenario('ok')", app: '#/research/{research}', ready: '.research-topbar' },
]

export const WIDTHS = [1280, 390]
export const THEMES: Theme[] = ['light', 'dark']
export const BREAKPOINT = 1024
const DESK = [1280]
const PHONE = [390]

// A pair that already matches on the desktop while its phone layout is a later slice's: two entries.
const phoneLater = (pair: Pair, slice: string, why: string): Pair[] => [
  { ...pair, widths: DESK },
  { ...pair, id: `${pair.id}@390`, widths: PHONE, status: `pending:${slice}`, why },
]

const shell = (surface: SurfaceId): Pair[] => [
  { id: `${surface}.sidebar`, surface, mock: '.side', app: 'aside.sidebar', checks: ['chrome', 'colour'], widths: DESK, use: 'decorative', status: 'active' },
  { id: `${surface}.brand-row`, surface, mock: '.side .brand', app: '.sidebar-head', checks: ['chrome'], text: true, widths: DESK, status: 'active' },
  { id: `${surface}.collapse`, surface, mock: '#sideTog', app: '.sidebar-toggle', checks: ['chrome'], widths: DESK, unordered: true,
    status: 'pending:S1', why: 'S1 gives the brand row the mockup collapse button position (app 28px at x 218, mockup 32px)' },
  // Lucide names are S1's choice; the slice that turns this pair on confirms them.
  { id: `${surface}.nav`, surface, mock: '.nav button', app: 'aside nav button', checks: ['chrome', 'type', 'colour', 'icon'], list: 'fixed', widths: DESK,
    icon: [['plus', 'plus'], ['search', 'search'], ['clock', 'clock'], ['inbox', 'inbox'], ['lib', 'library'], ['gear', 'settings-2'], ['trash', 'trash-2']].map(([mock, app]) => ({ mock, app })),
    dataText: { mock: ['.cnt'], app: ['.nav-count'] }, states: ['hover', 'selected'], selected: { mock: '.nav button.on', app: 'aside nav button.selected' },
    status: 'pending:S1', why: 'S1: New research, Search (in the list), Current research, Awaiting you, Library, Settings, Trash' },
  { id: `${surface}.recents-label`, surface, mock: '#recentsH', app: '.recents-label', checks: ['chrome', 'type', 'colour'], widths: DESK,
    status: 'pending:S1', why: 'S1: uppercase 11px label, no collapse toggle' },
  { id: `${surface}.recent-row`, surface, mock: '.recents .rrow', app: '.recent-list .recent-row', checks: ['chrome', 'type'], widths: DESK,
    list: 'data', expected: ctx => Math.min(12, ctx.researches), states: ['hover', 'selected'],
    selected: { mock: '.recents .rrow.on', app: '.recent-list .recent-row.is-active' },
    status: 'pending:S1', why: 'S1: status icon, 13px title, short time' },
  { id: `${surface}.access`, surface, mock: '.side-foot .access', app: '.access-status', checks: ['chrome', 'type', 'colour'], widths: DESK,
    status: 'pending:S2', why: 'S1/S2: proxy line and Scopus line (§2.3 copy), backend in S2' },
  { id: `${surface}.user-row`, surface, mock: '.side-foot .user', app: '.sidebar-user', checks: ['chrome', 'type'], widths: DESK,
    status: 'pending:S2', why: 'S2: profile name and initials; S1/S3: shortcuts and theme buttons' },
  { id: `${surface}.jobs-card`, surface, mock: '.side-foot .bgcard', app: '.background-jobs', checks: ['chrome', 'type'], widths: DESK,
    status: 'pending:S1', why: 'S1: "In the background · N" card (needs the [jobs-running] fixture state)' },
  { id: `${surface}.mobilebar`, surface, mock: '.mobilebar', app: '.mobilebar', checks: ['chrome', 'colour'], widths: PHONE,
    status: 'pending:S1', why: 'S1: 46px bar with menu and DEIXIS, no TR/EN or theme in it' },
]

export const PAIRS: Pair[] = [
  ...shell('home'),
  { id: 'home.composer', surface: 'home', mock: '.composer', app: 'form.composer', checks: ['chrome'], status: 'active' },
  { id: 'home.scope-button', surface: 'home', mock: '.band .band-btn', app: '.composer-scope', checks: ['chrome', 'type'],
    status: 'active' },
  { id: 'home.band', surface: 'home', mock: '.composer .band', app: '.composer-band', checks: ['chrome', 'colour'],
    status: 'active' },
  { id: 'home.question', surface: 'home', mock: 'textarea#q', app: '#research-question', checks: ['chrome', 'type', 'colour'], status: 'active' },
  { id: 'home.control-row', surface: 'home', mock: '.composer .comp-row', app: '.composer-controls', checks: ['chrome'], status: 'active' },
  { id: 'home.control-row-style', surface: 'home', mock: '.composer .comp-row', app: '.composer-controls', checks: ['colour'],
    status: 'active' },
  { id: 'home.add-sources', surface: 'home', mock: '.comp-row [data-menu="attach"]', app: '.composer-add', checks: ['chrome', 'colour', 'icon'],
    icon: { mock: 'plus', app: 'plus' }, status: 'active' },
  { id: 'home.models', surface: 'home', mock: '.comp-row [data-menu="models"]', app: '.models-summary', checks: ['chrome', 'type'],
    status: 'active' },
  { id: 'home.depth', surface: 'home', mock: '.comp-row [data-menu="depth"]', app: '[aria-label="Research depth"]', checks: ['chrome', 'type'],
    status: 'active' },
  { id: 'home.send', surface: 'home', mock: '.comp-row .send', app: '.send-button', checks: ['chrome', 'icon'], icon: { mock: 'up', app: 'arrow-up' }, status: 'active' },
  { id: 'home.send-style', surface: 'home', mock: '.comp-row .send', app: '.send-button', checks: ['colour'],
    status: 'active' },
  { id: 'home.mode-chips', surface: 'home', mock: '.chips .chip', app: '.mode-chips .chip', checks: ['chrome', 'type', 'colour'], list: 'fixed',
    states: ['hover', 'selected'], selected: { mock: '.chips .chip.on', app: '.mode-chips .chip.on' },
    status: 'pending:S5b', why: 'S5b: intent chips (needs S5a intent backend)' },
  // Resume (one research exists) plus up to two Suggested cards from stored unanswered aspects (Q4).
  { id: 'home.cards', surface: 'home', mock: '.cards .card', app: '.home-cards .card', checks: ['content', 'type'], list: 'data',
    expected: ctx => (ctx.researches ? 1 : 0) + Math.min(2, ctx.suggestions),
    status: 'pending:S5b', why: 'S5b: Resume and Suggested cards' },
  { id: 'home.hint', surface: 'home', mock: '.home .hint', app: '.home-hint', checks: ['content', 'type', 'colour'], states: [],
    status: 'active' },

  ...shell('research'),
  { id: 'research.topbar', surface: 'research', mock: '.topbar', app: '.research-topbar', checks: ['chrome', 'colour'], use: 'decorative', status: 'active' },
  { id: 'research.title', surface: 'research', mock: '.topbar h1', app: '.research-topbar h1', checks: ['type'], widths: DESK,
    status: 'pending:S8', why: 'S8: title button with pencil on hover' },
  { id: 'research.wait-chip', surface: 'research', mock: '.topbar .waitchip', app: '.research-topbar .wait-chip', checks: ['chrome', 'type', 'colour'], widths: DESK,
    status: 'pending:S8', why: 'S8: "N waiting for you" chip' },
  { id: 'research.revise', surface: 'research', mock: '.topbar [data-act="editq"]', app: '.research-revise', checks: ['chrome', 'type', 'colour'], widths: DESK,
    status: 'pending:S8', why: 'S8: topbar order and size of Revise question' },
  { id: 'research.export', surface: 'research', mock: '.topbar [data-menu="export"]', app: '.research-topbar .research-export', checks: ['chrome', 'type', 'colour'], widths: DESK,
    status: 'pending:S8', why: 'S8: Export button and menu groups' },
  { id: 'research.more', surface: 'research', mock: '.topbar [data-menu="research"]', app: '.research-topbar .research-more', checks: ['chrome', 'icon'], widths: DESK,
    icon: { mock: 'more', app: 'ellipsis' }, status: 'pending:S8', why: 'S8: ⋯ research menu' },
  { id: 'research.thread', surface: 'research', mock: '.thread-inner', app: '.thread-inner', checks: ['content'], breakpoint: true,
    status: 'pending:S7a', why: 'S7a: the tabs become thread + rail + panel' },
  { id: 'research.question', surface: 'research', mock: '.thread .q', app: '.chat-question', checks: ['content', 'type', 'colour'],
    status: 'pending:S8', why: 'S8: question bubble with scope label and date · revision' },
  { id: 'research.steps', surface: 'research', mock: '.steps .step', app: '.chat-steps .chat-step', checks: ['content', 'type'], list: 'fixed',
    text: false,  // each step line mixes the phase with its counts; S9 separates them and sets `dataText` before turning this on
    status: 'pending:S9', why: 'S9: one line per phase' },
  { id: 'research.usage-line', surface: 'research', mock: '.steps .usage-line', app: '.usage-line', checks: ['content', 'type', 'colour'],
    status: 'pending:S9', why: 'S9: role · model usage line' },
  { id: 'research.answer-card', surface: 'research', mock: '.thread .art', app: '.thread .art', checks: ['content', 'type', 'colour'],
    status: 'pending:S10', why: 'S10: answer card in the thread' },
  { id: 'research.prose', surface: 'research', mock: '.thread .prose', app: '.thread .prose', checks: ['content', 'type'],
    status: 'pending:S10', why: 'S10: answer prose with cite chips' },
  { id: 'research.methods', surface: 'research', mock: '.thread .methods', app: '.thread .methods', checks: ['content', 'type'],
    status: 'pending:S10', why: 'S10: methods box under the answer' },
  { id: 'research.next-steps', surface: 'research', mock: '.thread .follow', app: '.thread .follow', checks: ['content', 'type'],
    status: 'pending:S10', why: 'S10: next steps box' },
  { id: 'research.followup-composer', surface: 'research', mock: '.mini', app: '.followup-composer', checks: ['content', 'colour'],
    status: 'pending:S22b', why: 'S22b: sticky follow-up composer' },
  { id: 'research.rail', surface: 'research', mock: '.rail', app: '.rail', checks: ['chrome'], widths: DESK, breakpoint: true,
    status: 'pending:S11', why: 'S11: artifacts rail, hidden under 1100px' },
  { id: 'research.rail-boxes', surface: 'research', mock: '.rail .box', app: '.rail .box', checks: ['content', 'type'], list: 'fixed', widths: DESK,
    dataText: { mock: ['.tnum', 'button.li span', 'button.li em'], app: ['.tnum', '.rail-data'] },
    status: 'pending:S11', why: 'S11: artifacts, waiting, funnel, depth, run and usage boxes' },
]

/** Pending pairs per slice, for the summary line. */
export function pendingBySlice(pairs: Pair[] = PAIRS): Record<string, number> {
  const out: Record<string, number> = {}
  for (const p of pairs) if (p.status !== 'active') out[p.status.slice('pending:'.length)] = (out[p.status.slice('pending:'.length)] ?? 0) + 1
  return Object.fromEntries(Object.entries(out).sort(([a], [b]) => a.localeCompare(b, 'en', { numeric: true })))
}

export function pairsFor(surface: SurfaceId, width: number): Pair[] {
  return PAIRS.filter(p => p.surface === surface && p.status === 'active' && (!p.widths || p.widths.includes(width)))
}
