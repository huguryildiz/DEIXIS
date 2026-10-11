import type { Page } from '@playwright/test'
import type { Use } from './exceptions'
import type { FixtureContext } from './gates'

// Which mockup element corresponds to which app element, per surface (plan §4.1). A pair is `active` when the current
// app already matches it within tolerance, or `pending:<slice>` when a later slice of the parity plan changes that part
// of the screen. Pending pairs are counted and printed, not checked. The slice that ports a screen turns its pairs to
// `active` in the same commit.

export type Theme = 'light' | 'dark'
export type Check = 'chrome' | 'content' | 'type' | 'colour' | 'icon'
export type SurfaceId = 'home' | 'research' | 'zotero' | 'collapsed' | 'drawer' | 'jobs-sheet' | 'toast' | 'menu' | 'dialog'
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
  /** Before the app page loads: answers that the fixture server has no source for (e.g. a Zotero library). */
  prepare?: (page: Page) => Promise<unknown>
  /** After the page loads: the clicks that open this state (a dialog), before `ready` is awaited. */
  open?: (page: Page) => Promise<unknown>
  /** Only at these viewport widths (default: every width). */
  widths?: number[]
  /** A state on top of the page (collapsed sidebar, drawer, sheet, toast, menu, dialog): the mockup script run after
   *  `mock`, the app steps that open the same state, and the app steps that undo a change to the fixture afterwards. */
  mockAct?: string
  appAct?: (page: Page) => Promise<void>
  appUndo?: (page: Page) => Promise<void>
  /** The equation reader the app is shown with (default: one PDF being read, the background card's source). */
  reader?: 'reading' | 'not-installed'
}

/** The Zotero library the dialog surface shows: SYNTHETIC collections shaped like the mockup's six (two of them
 *  sub-collections of the first), one with a count Zotero did not send. The fixture server has no Zotero. */
export const ZOTERO_COLLECTIONS = [
  { key: 'SYNA', name: 'SYNTHETIC UWSN reliability', items: 24, parent: null },
  { key: 'SYNB', name: 'SYNTHETIC UWSN reliability / k-connectivity', items: 11, parent: 'SYNA' },
  { key: 'SYNC', name: 'SYNTHETIC UWSN reliability / Lifetime models', items: 9, parent: 'SYNA' },
  { key: 'SYND', name: 'SYNTHETIC IRS and RIS', items: 31, parent: null },
  { key: 'SYNE', name: 'SYNTHETIC Quantum networks', items: null, parent: null },
  { key: 'SYNF', name: 'SYNTHETIC Thesis reading list', items: 46, parent: null },
]

export const WIDTHS = [1280, 390]
export const THEMES: Theme[] = ['light', 'dark']
export const BREAKPOINT = 1024
const DESK = [1280]
const PHONE = [390]

const HOME = "setScenario('ok'); go('home')"
export const SURFACES: Surface[] = [
  { id: 'home', mock: HOME, app: '#/', ready: '#research-question' },
  { id: 'research', mock: "setScenario('ok')", app: '#/research/{research}', ready: '.research-topbar' },
  { id: 'zotero', mock: "setScenario('ok'); go('home'); zoteroDlg('home')", app: '#/', ready: '.zotero-dialog .zotero-cols label',
    prepare: page => page.route('**/api/zotero/collections**', route => route.fulfill({ json: { source: 'local', collections: ZOTERO_COLLECTIONS } })),
    open: async page => {
      await page.locator('.composer-add').click()
      await page.getByRole('menuitem', { name: /Zotero collection/ }).click()
      await page.mouse.move(0, 0)
    } },
  // S1 states (plan O4–O7, S2, S20): the collapsed strip, the phone drawer, the jobs sheet, a toast with Undo, the
  // recent row's menu and the dialog shell.
  { id: 'collapsed', mock: HOME, mockAct: 'setSideOff(true)', app: '#/', ready: '#research-question', widths: DESK,
    appAct: page => page.locator('.sidebar-toggle').click() },
  { id: 'drawer', mock: HOME, mockAct: "document.getElementById('app').classList.add('nav-open')", app: '#/', ready: '#research-question', widths: PHONE,
    appAct: async page => { await page.locator('.mobile-menu').click(); await page.locator('aside.sidebar.is-open').waitFor() } },
  { id: 'jobs-sheet', mock: HOME, mockAct: 'st.jobsOpen = true; render()', app: '#/', ready: '#research-question', widths: DESK,
    appAct: async page => { await page.locator('.sidebar-foot .bgcard').click(); await page.locator('.jobs-sheet').waitFor() } },
  { id: 'toast', mock: HOME, mockAct: "toast('Moved to Trash.', () => {}); clearTimeout(tt); document.querySelector('.toast').dataset.parity = ''", app: '#/', ready: '#research-question', widths: DESK,
    appAct: async page => {
      await page.locator('.recent-list .recent-row').first().hover()
      await page.locator('.recent-list .recent-more').first().click()
      await page.getByRole('menuitem', { name: 'Move to Trash' }).click()
      await page.locator('.toast .toast-action').waitFor()
    },
    appUndo: async page => {
      if (await page.locator('.toast .toast-action').isVisible()) await page.locator('.toast .toast-action').click()
      await page.locator('.recent-list .recent-row').first().waitFor()
    } },
  { id: 'menu', mock: HOME, mockAct: "st.menuArg = 0; document.querySelector('.rrow').classList.add('on'); menu('rmenu', document.querySelector('.rrow .rmore'))", app: '#/', ready: '#research-question', widths: DESK,
    appAct: async page => {
      await page.locator('.recent-list .recent-row').first().hover()
      await page.locator('.recent-list .recent-more').first().click()
      await page.locator('[data-slot=dropdown-menu-content]').waitFor()
    } },
  { id: 'dialog', mock: HOME, mockAct: "zoteroDlg('home')", app: '#/settings/connections', ready: '.connection-grid', reader: 'not-installed',
    appAct: async page => {
      await page.getByRole('button', { name: /^Marker/ }).click()
      await page.locator('.connection-sheet').getByRole('button', { name: 'Install', exact: true }).click()
      await page.locator('.dialog').waitFor()
    } },
]

// A pair that already matches on the desktop while its phone layout is a later slice's: two entries.
const phoneLater = (pair: Pair, slice: string, why: string): Pair[] => [
  { ...pair, widths: DESK },
  { ...pair, id: `${pair.id}@390`, widths: PHONE, status: `pending:${slice}`, why },
]

const NAV_ICONS = [['plus', 'plus'], ['search', 'search'], ['clock', 'clock'], ['inbox', 'inbox'], ['lib', 'library-big'], ['gear', 'sliders-horizontal'], ['trash', 'trash']].map(([mock, app]) => ({ mock, app }))

const shell = (surface: SurfaceId): Pair[] => [
  { id: `${surface}.sidebar`, surface, mock: '.side', app: 'aside.sidebar', checks: ['chrome', 'colour'], widths: DESK, use: 'decorative', status: 'active' },
  { id: `${surface}.brand-row`, surface, mock: '.side .brand', app: '.sidebar-head', checks: ['chrome'], text: true, widths: DESK, status: 'active' },
  { id: `${surface}.collapse`, surface, mock: '#sideTog', app: '.sidebar-toggle', checks: ['chrome'], widths: DESK, unordered: true,
    status: 'active' },
  // Lucide names confirmed by S1.
  { id: `${surface}.nav`, surface, mock: '.nav button', app: 'aside nav button', checks: ['chrome', 'type', 'colour', 'icon'], list: 'fixed', widths: DESK,
    icon: NAV_ICONS,
    dataText: { mock: ['.cnt'], app: ['.nav-count'] }, states: ['hover', 'selected'], selected: { mock: '.nav button.on', app: 'aside nav button.selected' },
    status: 'active' },
  { id: `${surface}.recents-label`, surface, mock: '#recentsH', app: '.recents-label', checks: ['chrome', 'type', 'colour'], widths: DESK, states: [],
    status: 'active' },
  { id: `${surface}.recent-row`, surface, mock: '.recents .rrow', app: '.recent-list .recent-row', checks: ['chrome', 'type'], widths: DESK,
    list: 'data', expected: ctx => Math.min(12, ctx.researches), states: ['hover', 'selected'],
    selected: { mock: '.recents .rrow.on', app: '.recent-list .recent-row.is-active' },
    status: 'active' },
  { id: `${surface}.access`, surface, mock: '.side-foot .access', app: '.sidebar-foot .access', checks: ['chrome', 'type', 'colour'], widths: DESK, states: ['hover'],
    status: 'active' },  // §2.3 copy: COPY_CHANGES proxy-working and scopus-check
  { id: `${surface}.user-row`, surface, mock: '.side-foot .user', app: '.sidebar-foot .user', checks: ['chrome', 'type'], widths: DESK,
    status: 'active' },
  { id: `${surface}.jobs-card`, surface, mock: '.side-foot .bgcard', app: '.sidebar-foot .bgcard', checks: ['chrome', 'type'], widths: DESK,
    status: 'active' },
  { id: `${surface}.mobilebar`, surface, mock: '.mobilebar', app: '.mobilebar', checks: ['chrome', 'colour'], widths: PHONE,
    status: 'active' },
]

// The S1 states. The drawer is the desktop sidebar opened over the page at 390; the collapsed strip shows icons only.
const states: Pair[] = [
  ...shell('drawer').filter(p => p.id !== 'drawer.mobilebar').map(p => ({ ...p, widths: PHONE })),
  { id: 'collapsed.sidebar', surface: 'collapsed', mock: '.side', app: 'aside.sidebar', checks: ['chrome', 'colour'], use: 'decorative', status: 'active' },
  { id: 'collapsed.brand-row', surface: 'collapsed', mock: '.side .brand', app: '.sidebar-head', checks: ['chrome'], status: 'active' },
  { id: 'collapsed.collapse', surface: 'collapsed', mock: '#sideTog', app: '.sidebar-toggle', checks: ['chrome'], unordered: true, status: 'active' },
  { id: 'collapsed.nav', surface: 'collapsed', mock: '.nav button', app: 'aside nav button', checks: ['chrome', 'colour', 'icon'], list: 'fixed', text: false, icon: NAV_ICONS,
    dataText: { mock: ['.cnt'], app: ['.nav-count'] }, states: ['hover', 'selected'], selected: { mock: '.nav button.on', app: 'aside nav button.selected' }, status: 'active' },
  { id: 'collapsed.user-row', surface: 'collapsed', mock: '.side-foot .user', app: '.sidebar-foot .user', checks: ['chrome'], status: 'active' },
  // O7: the right sheet over a scrim, here the jobs sheet; its rows come from the SYNTHETIC equation-reader read (one job).
  { id: 'jobs-sheet.scrim', surface: 'jobs-sheet', mock: '.sheet-scrim', app: '[data-slot=sheet-overlay]', checks: ['chrome', 'colour'], use: 'decorative', unordered: true, status: 'active' },
  { id: 'jobs-sheet.sheet', surface: 'jobs-sheet', mock: '#jobsSheet', app: '.jobs-sheet', checks: ['chrome', 'colour'], use: 'decorative', unordered: true, status: 'active' },
  { id: 'jobs-sheet.head', surface: 'jobs-sheet', mock: '#jobsSheet .p-head', app: '.jobs-sheet [data-slot=sheet-header]', checks: ['chrome', 'colour'], use: 'decorative', unordered: true, status: 'active' },
  { id: 'jobs-sheet.title', surface: 'jobs-sheet', mock: '#jobsSheet .p-head h2', app: '.jobs-sheet [data-slot=sheet-title]', checks: ['type', 'icon'], icon: { mock: 'clock', app: 'clock' }, unordered: true, status: 'active' },
  { id: 'jobs-sheet.close', surface: 'jobs-sheet', mock: '#jobsSheet .p-head .ib', app: '.jobs-sheet [data-slot=sheet-close]', checks: ['chrome', 'icon'], icon: { mock: 'x', app: 'x' }, unordered: true, status: 'active' },
  { id: 'jobs-sheet.job', surface: 'jobs-sheet', mock: '#jobsSheet .job', app: '.jobs-sheet .jobs-body > .job', checks: ['chrome', 'type'], list: 'data', expected: () => 1, unordered: true, status: 'active' },
  // §2.3 copy: COPY_CHANGES jobs-note (the promise is conditional).
  { id: 'jobs-sheet.note', surface: 'jobs-sheet', mock: '#jobsSheet .foot-note', app: '.jobs-sheet .foot-note', checks: ['content', 'type', 'colour'], states: [], unordered: true, status: 'active' },
  // O4: toast bottom-centre on ink with an Undo link. Its dismiss button is a §2.2 placement (toast-dismiss), so the box is not compared.
  { id: 'toast.toast', surface: 'toast', mock: '.toast', app: '.toast', checks: ['type', 'colour'], unordered: true, status: 'active' },
  { id: 'toast.undo', surface: 'toast', mock: '.toast .tbtn', app: '.toast .toast-action', checks: ['type', 'colour'], text: true, unordered: true, status: 'active' },
  // O5: the recent row's menu (Rename, Move to Trash as a danger row).
  { id: 'menu.menu', surface: 'menu', mock: '.menu', app: '[data-slot=dropdown-menu-content]', checks: ['chrome', 'colour'], use: 'decorative', unordered: true, status: 'active' },
  { id: 'menu.items', surface: 'menu', mock: '.menu button', app: '[data-slot=dropdown-menu-content] [data-slot=dropdown-menu-item]', checks: ['chrome', 'type', 'colour', 'icon'], list: 'fixed',
    icon: [{ mock: 'pen', app: 'pencil-line' }, { mock: 'trash', app: 'trash' }], states: ['hover'], unordered: true, status: 'active' },
  // O6: the dialog shell (mockup `.pal.dlg`), opened in the app by a confirm dialog (the equation reader's Install).
  { id: 'dialog.scrim', surface: 'dialog', mock: '.scrim', app: '.dialog-scrim', checks: ['chrome', 'colour'], use: 'decorative', unordered: true, status: 'active' },
  { id: 'dialog.dialog', surface: 'dialog', mock: '.pal.dlg', app: '.dialog', checks: ['content', 'colour'], use: 'decorative', unordered: true, status: 'active' },
  { id: 'dialog.head', surface: 'dialog', mock: '.pal.dlg .pal-in', app: '.dialog-head', checks: ['chrome', 'colour'], use: 'decorative', unordered: true, status: 'active' },
  { id: 'dialog.title', surface: 'dialog', mock: '.pal.dlg .pal-in b', app: '.dialog-title', checks: ['type'], unordered: true, status: 'active' },
  { id: 'dialog.close', surface: 'dialog', mock: '.pal.dlg .pal-in .ib', app: '.dialog-close', checks: ['chrome', 'icon'], icon: { mock: 'x', app: 'x' }, unordered: true, status: 'active' },
  { id: 'dialog.body', surface: 'dialog', mock: '.pal.dlg .dlg-b', app: '.dialog-body', checks: ['content'], unordered: true, status: 'active' },
  { id: 'dialog.footer', surface: 'dialog', mock: '.pal.dlg .dlg-f', app: '.dialog-footer', checks: ['content', 'colour'], use: 'decorative', unordered: true, status: 'active' },
]

export const PAIRS: Pair[] = [
  ...shell('home'),
  ...states,
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

  // S6: the Zotero dialog of Home (H17). The dialog's and the footer's height and y depend on the rows and on how the
  // §2.3 notes wrap, so those two frames are compared as content (x, width, padding, line height); the head row is
  // chrome, and the footer buttons are chrome without y (a declared geometry exception).
  { id: 'zotero.dialog', surface: 'zotero', mock: '.pal.dlg', app: '.zotero-dialog', checks: ['content', 'colour'], use: 'decorative', status: 'active' },
  { id: 'zotero.head', surface: 'zotero', mock: '.dlg .pal-in', app: '.zotero-dialog-head', checks: ['chrome', 'type', 'colour', 'icon'], text: true,
    icon: { mock: 'lib', app: 'library' }, status: 'active' },
  { id: 'zotero.title', surface: 'zotero', mock: '.dlg .pal-in b', app: '.zotero-dialog-title', checks: ['chrome', 'type'], status: 'active' },
  { id: 'zotero.close', surface: 'zotero', mock: '.dlg .pal-in .ib', app: '.zotero-dialog-close', checks: ['chrome', 'colour', 'icon'],
    icon: { mock: 'x', app: 'x' }, states: [], status: 'active' },
  { id: 'zotero.lead', surface: 'zotero', mock: '.dlg-b > p.foot-note:first-child', app: '.zotero-dialog-lead', checks: ['content', 'type', 'colour'], status: 'active' },
  { id: 'zotero.cols', surface: 'zotero', mock: '.zcols', app: '.zotero-cols', checks: ['content', 'colour'], use: 'decorative', status: 'active' },
  { id: 'zotero.col-row', surface: 'zotero', mock: '.zcols label:not(.sub)', app: '.zotero-cols label:not(.sub)', checks: ['chrome', 'content', 'type', 'icon'],
    list: 'data', expected: () => ZOTERO_COLLECTIONS.filter(c => !c.parent).length, icon: { mock: 'folder', app: 'folder' }, status: 'active' },
  { id: 'zotero.col-count', surface: 'zotero', mock: '.zcols em', app: '.zotero-cols em', checks: ['type', 'colour'], states: [],
    list: 'data', expected: () => ZOTERO_COLLECTIONS.filter(c => c.items !== null).length, status: 'active' },
  { id: 'zotero.col-sub', surface: 'zotero', mock: '.zcols label.sub', app: '.zotero-cols label.sub', checks: ['chrome', 'content', 'type', 'icon'],
    list: 'data', expected: () => ZOTERO_COLLECTIONS.filter(c => c.parent).length, icon: { mock: 'folder', app: 'folder' }, status: 'active' },
  { id: 'zotero.note', surface: 'zotero', mock: '.dlg-b > p.foot-note:last-child', app: '.zotero-dialog-note', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'zotero.foot', surface: 'zotero', mock: '.dlg-f', app: '.zotero-dialog-foot', checks: ['content', 'colour'], use: 'decorative', status: 'active' },
  // Chrome geometry minus y (GEOMETRY_EXCEPTIONS zotero-foot-buttons-y): the footer's place follows the notes above it.
  { id: 'zotero.foot-buttons', surface: 'zotero', mock: '.dlg-f button', app: '.zotero-dialog-foot button', checks: ['chrome', 'content', 'type', 'colour'], list: 'fixed', status: 'active' },
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
