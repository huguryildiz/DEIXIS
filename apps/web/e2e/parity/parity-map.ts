import type { Page } from '@playwright/test'
import type { Use } from './exceptions'
import type { FixtureContext } from './gates'

// Which mockup element corresponds to which app element, per surface (plan §4.1). A pair is `active` when the current
// app already matches it within tolerance, or `pending:<slice>` when a later slice of the parity plan changes that part
// of the screen. Pending pairs are counted and printed, not checked. The slice that ports a screen turns its pairs to
// `active` in the same commit.

export type Theme = 'light' | 'dark'
export type Check = 'chrome' | 'content' | 'type' | 'colour' | 'icon'
export type SurfaceId = 'home' | 'home-first' | 'home-guide' | 'research' | 'zotero' | 'collapsed' | 'drawer' | 'jobs-sheet' | 'toast' | 'menu' | 'dialog' | 'research-panel' | 'palette' | 'keys'
  | 'research-menu' | 'export-menu' | 'title-edit' | 'revise'
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
  hoverSurface?: boolean    // on hover also compare background, border colour and shadow (a card that lifts, §4.1)
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
// The sidebar's controls are in the drawer on a phone: both sides open it there first (no effect above 820px).
const NAV_OPEN = "document.getElementById('app').classList.add('nav-open'); "
async function drawerIfPhone(page: Page) {
  if (!await page.locator('.mobile-menu').isVisible()) return
  await page.locator('.mobile-menu').click()
  await page.locator('aside.sidebar.is-open').waitFor()
}

/** S5b: the first-run Home. No model connection is ready, no research exists and nothing is suggested; the scholarly
 *  sources and the proxy setting are the fixture server's own. */
async function firstRun(page: Page) {
  await page.route('**/api/connections**', async route => {
    const response = await route.fetch()
    const body = await response.json() as { models: Record<string, unknown> }
    await route.fulfill({ response, json: { ...body, models: {} } })
  })
  await page.route('**/api/researches', route => route.request().method() === 'GET' ? route.fulfill({ json: [] }) : route.fallback())
  await page.route('**/api/suggestions', route => route.fulfill({ json: { suggestions: [] } }))
}

/** S5b: two SYNTHETIC PDFs attached in a mixed search, so the composer shows its guide rows (Q3). */
export const GUIDE_PDFS = ['SYNTHETIC-guide-first.pdf', 'SYNTHETIC-guide-second.pdf']

export const SURFACES: Surface[] = [
  // S5b: ready once the Resume card is there (the card pairs measure it); the composer comes first.
  { id: 'home', mock: HOME, app: '#/', ready: '.home-cards .card' },
  { id: 'home-first', mock: "setScenario('first'); go('home')", app: '#/', ready: '.home-setup', prepare: firstRun },
  { id: 'home-guide', mock: `setScenario('ok'); go('home'); st.scope = 'PDFs + academic search'; st.files = ${JSON.stringify(GUIDE_PDFS)}; render()`,
    app: '#/', ready: '.composer .guide label',
    open: page => page.locator('input[type=file]').first().setInputFiles(GUIDE_PDFS.map(name => ({ name, mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\n%%EOF\n') }))) },
  { id: 'research', mock: "setScenario('ok')", app: '#/research/{research}', ready: '.research-topbar' },
  // The research page with one side panel open (S7a, R10/P1): the Sources panel, opened fresh.
  { id: 'research-panel', mock: "setScenario('ok'); openPanel('sources', 'cited', false)", app: '#/research/{research}/sources', ready: '[data-split-panel] #split-panel-title' },
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
  { id: 'jobs-sheet', mock: HOME, mockAct: NAV_OPEN + 'st.jobsOpen = true; render()', app: '#/', ready: '#research-question',
    appAct: async page => { await drawerIfPhone(page); await page.locator('.sidebar-foot .bgcard').click(); await page.locator('.jobs-sheet').waitFor() } },
  { id: 'toast', mock: HOME, mockAct: NAV_OPEN + "toast('Moved to Trash.', () => {}); clearTimeout(tt); document.querySelector('.toast').dataset.parity = ''", app: '#/', ready: '#research-question',
    appAct: async page => {
      await drawerIfPhone(page)
      await page.locator('.recent-list .recent-row').first().hover()
      await page.locator('.recent-list .recent-more').first().click()
      await page.getByRole('menuitem', { name: 'Move to Trash' }).click()
      await page.locator('.toast .toast-action').waitFor()
    },
    appUndo: async page => {
      if (await page.locator('.toast .toast-action').isVisible()) await page.locator('.toast .toast-action').click()
      await page.locator('.recent-list .recent-row').first().waitFor()
    } },
  { id: 'menu', mock: HOME, mockAct: NAV_OPEN + "st.menuArg = 0; document.querySelector('.rrow').classList.add('on'); menu('rmenu', document.querySelector('.rrow .rmore'))", app: '#/', ready: '#research-question',
    appAct: async page => {
      await drawerIfPhone(page)
      await page.locator('.recent-list .recent-row').first().hover()
      await page.locator('.recent-list .recent-more').first().click()
      await page.locator('[data-slot=dropdown-menu-content]').waitFor()
    } },
  // S3 (O1, O2): the search palette and the keys dialog over the research page, each opened by its key.
  { id: 'palette', mock: "setScenario('ok')", mockAct: 'palette()', app: '#/research/{research}', ready: '.research-topbar',
    appAct: async page => { await page.keyboard.press('ControlOrMeta+k'); await page.locator('.quick-find .quick-find-foot').waitFor() } },
  { id: 'keys', mock: "setScenario('ok')", mockAct: 'keysDlg()', app: '#/research/{research}', ready: '.research-topbar',
    appAct: async page => { await page.keyboard.press('?'); await page.locator('.keys-dialog .keys').waitFor() } },
  // S8 (R2, R7–R9): the topbar's ⋯ and Export menus, the rename row and the revise form, over the research page.
  { id: 'research-menu', mock: "setScenario('ok')", mockAct: "menu('research', document.querySelector('.topbar [data-menu=\"research\"]'))", app: '#/research/{research}', ready: '.research-topbar',
    appAct: async page => { await page.locator('.research-topbar .research-more').click(); await page.locator('[data-slot=dropdown-menu-content]').waitFor() } },
  { id: 'export-menu', mock: "setScenario('ok')", mockAct: "menu('export', document.querySelector('.topbar [data-menu=\"export\"]'))", app: '#/research/{research}', ready: '.research-topbar',
    appAct: async page => { await page.locator('.research-topbar .research-export').click(); await page.locator('[data-slot=dropdown-menu-content]').waitFor() } },
  { id: 'title-edit', mock: "setScenario('ok')", mockAct: 'st.renTitle = true; render()', app: '#/research/{research}', ready: '.research-topbar',
    // The app focuses the field it opens; the mockup's render leaves it unfocused, so the field is compared at rest.
    appAct: async page => { await page.locator('.research-topbar .research-title-button').click(); await page.locator('.research-title-input').blur() } },
  { id: 'revise', mock: "setScenario('ok')", mockAct: 'st.editQ = true; render()', app: '#/research/{research}', ready: '.research-topbar', widths: DESK,
    appAct: async page => { await page.locator('.research-topbar .research-revise').click(); await page.locator('#revise-question').blur() } },
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

// The steps' phase icons (S9): pen, search, graph, checks, book, file and shield in the mockup's `P` table.
const STEP_ICONS = [{ mock: 'pen', app: 'pencil-line' }, { mock: 'search', app: 'search' }, { mock: 'graph', app: 'waypoints' },
  { mock: 'checks', app: 'list-checks' }, { mock: 'book', app: 'book-open' }, { mock: 'file', app: 'file-text' }, { mock: 'shield', app: 'shield-check' }]
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

// O1 (S3): the search palette over the research page. The page's rows leave out the funnel row (DEFERRED_TARGETS); the
// recent rows are the fixture's researches; the letter keys are compared as their own lists (dataText leaves them out
// of the row text, so "Read more in full" meets its copy change).
const PAL_PAGE = '#palList button:is([data-pal^="panel:"], [data-pal="theme"])'
const PAL_GOTO = '#palList button:is([data-pal="go:home"], [data-pal="go:library"], [data-pal="go:settings"], [data-pal="keys"])'
const APP_GROUP = (group: string) => `.quick-find [aria-labelledby="qf-group-${group}"] [role=option]`
const palette: Pair[] = [
  { id: 'palette.scrim', surface: 'palette', mock: '.scrim', app: '.quick-find-backdrop', checks: ['chrome', 'colour'], use: 'decorative', unordered: true, status: 'active' },
  { id: 'palette.box', surface: 'palette', mock: '.pal', app: '.quick-find', checks: ['chrome', 'colour'], use: 'decorative', unordered: true, status: 'active' },
  // STYLE_EXCEPTIONS palette-focus-line: the app's focus line under the field.
  { id: 'palette.field', surface: 'palette', mock: '.pal-in', app: '.quick-find-field', checks: ['chrome', 'colour', 'icon'], use: 'icon',
    icon: { mock: 'search', app: 'search' }, unordered: true, states: [], status: 'active' },
  { id: 'palette.input', surface: 'palette', mock: '#palq', app: '.quick-find-field input', checks: ['chrome', 'type', 'colour'], unordered: true, states: [], status: 'active' },
  { id: 'palette.headings', surface: 'palette', mock: '.pal-list h6', app: '.quick-find-group', checks: ['chrome', 'type', 'colour'], list: 'fixed', unordered: true, states: [], status: 'active' },
  { id: 'palette.page-rows', surface: 'palette', mock: PAL_PAGE, app: APP_GROUP('Page'), checks: ['chrome', 'type', 'colour', 'icon'], list: 'fixed',
    dataText: { mock: ['em'], app: ['em'] },
    icon: [{ mock: 'book', app: 'book-open' }, { mock: 'doc', app: 'text-align-start' }, { mock: 'inbox', app: 'inbox' }, { mock: 'file', app: 'file-text' }, { mock: 'moon', app: 'moon' }],
    unordered: true, states: [], status: 'active' },
  { id: 'palette.page-keys', surface: 'palette', mock: `${PAL_PAGE} em`, app: `${APP_GROUP('Page')} em`, checks: ['chrome', 'type', 'colour'], list: 'fixed', unordered: true, states: [], status: 'active' },
  { id: 'palette.recent-rows', surface: 'palette', mock: '#palList button[data-pal="go:research"]', app: APP_GROUP('Research'), checks: ['chrome', 'type', 'icon'], list: 'data',
    expected: ctx => Math.min(5, ctx.researches), icon: { mock: 'node', app: 'vector-square' }, unordered: true, status: 'active' },
  { id: 'palette.goto-rows', surface: 'palette', mock: PAL_GOTO, app: APP_GROUP('Pages'), checks: ['chrome', 'type', 'colour', 'icon'], list: 'fixed',
    dataText: { mock: ['em'], app: ['em'] },
    icon: [{ mock: 'plus', app: 'plus' }, { mock: 'lib', app: 'library-big' }, { mock: 'gear', app: 'sliders-horizontal' }, { mock: 'kbd', app: 'keyboard' }],
    unordered: true, states: [], status: 'active' },
  { id: 'palette.goto-keys', surface: 'palette', mock: `${PAL_GOTO} em`, app: `${APP_GROUP('Pages')} em`, checks: ['chrome', 'type', 'colour'], list: 'fixed', unordered: true, states: [], status: 'active' },
  { id: 'palette.foot', surface: 'palette', mock: '.pal-foot', app: '.quick-find-foot', checks: ['chrome', 'type', 'colour'], text: true, unordered: true, states: [], status: 'active' },
]
// O2 (S3): the keys dialog. Its rows leave out "Search funnel" and "Send follow-up" (DEFERRED_TARGETS); its foot line
// with the off switch is an app addition (APP_ADDITIONS keys-off-switch), not measured.
const keysDialog: Pair[] = [
  { id: 'keys.scrim', surface: 'keys', mock: '.scrim', app: '.dialog-scrim', checks: ['chrome', 'colour'], use: 'decorative', unordered: true, status: 'active' },
  { id: 'keys.dialog', surface: 'keys', mock: '.pal', app: '.keys-dialog', checks: ['content', 'colour'], use: 'decorative', unordered: true, status: 'active' },
  { id: 'keys.head', surface: 'keys', mock: '.pal .pal-in', app: '.keys-dialog .dialog-head', checks: ['chrome', 'colour', 'icon'], use: 'decorative',
    icon: { mock: 'kbd', app: 'keyboard' }, unordered: true, status: 'active' },
  { id: 'keys.title', surface: 'keys', mock: '.pal .pal-in b', app: '.keys-dialog .dialog-title', checks: ['type'], text: true, unordered: true, status: 'active' },
  { id: 'keys.close', surface: 'keys', mock: '.pal .pal-in .ib', app: '.keys-dialog .dialog-close', checks: ['chrome', 'icon'], icon: { mock: 'x', app: 'x' }, unordered: true, status: 'active' },
  { id: 'keys.grid', surface: 'keys', mock: '.keys', app: '.keys-dialog .keys', checks: ['content'], unordered: true, status: 'active' },
  { id: 'keys.headings', surface: 'keys', mock: '.keys h6', app: '.keys-dialog .keys-heading', checks: ['chrome', 'type', 'colour'], list: 'fixed', unordered: true, states: [], status: 'active' },
  { id: 'keys.labels', surface: 'keys', mock: '.keys > span:nth-of-type(odd)', app: '.keys-dialog .keys > span:not(.keys-keys)', checks: ['chrome', 'type', 'colour'], list: 'fixed', unordered: true, states: [], status: 'active' },
  { id: 'keys.keys', surface: 'keys', mock: '.keys > span:nth-of-type(even)', app: '.keys-dialog .keys-keys', checks: ['chrome', 'type'], list: 'fixed', unordered: true, status: 'active' },
  { id: 'keys.kbd', surface: 'keys', mock: '.keys kbd', app: '.keys-dialog .keys kbd', checks: ['chrome', 'type', 'colour'], list: 'fixed', unordered: true, states: [], status: 'active' },
]

// S8 (R9): the ⋯ menu. Its rows with a mockup counterpart are compared; the placement rows (panels the rail and the steps
// will open, Search again and Generate a new answer) are PLACEMENTS and left out, so Move to Trash sits lower.
const MENU = '[data-slot=dropdown-menu-content]'
const MENU_ROWS = `${MENU} [data-slot=dropdown-menu-item]:not(.research-menu-placement)`
const researchMenu: Pair[] = [
  { id: 'research-menu.menu', surface: 'research-menu', mock: '.menu', app: MENU, checks: ['content', 'colour'], use: 'decorative', unordered: true, status: 'active' },
  { id: 'research-menu.rows', surface: 'research-menu', mock: '.menu button:not(.danger)', app: `${MENU_ROWS}:not([data-variant=destructive])`, checks: ['chrome', 'type', 'colour', 'icon'], list: 'fixed',
    dataText: { app: ['.research-tab-count'] }, icon: [{ mock: 'pen', app: 'pencil-line' }, { mock: 'clock', app: 'clock' }, { mock: 'bulb', app: 'lightbulb' }, { mock: 'clock', app: 'clock' }],
    states: ['hover'], unordered: true, status: 'active' },
  { id: 'research-menu.trash', surface: 'research-menu', mock: '.menu button.danger', app: `${MENU} [data-variant=destructive]`, checks: ['chrome', 'type', 'colour', 'icon'], text: true,
    icon: { mock: 'trash', app: 'trash' }, unordered: true, status: 'active' },
]
// S8 (R8): the Export menu. The PDF row is DEFERRED_TARGETS (S27 wires print); the PRISMA-S rows are a PLACEMENT. The
// counts in the sources rows are data, so the rows' text is compared through their format labels.
const exportMenu: Pair[] = [
  { id: 'export-menu.menu', surface: 'export-menu', mock: '.menu', app: MENU, checks: ['content', 'colour'], use: 'decorative', unordered: true, status: 'active' },
  { id: 'export-menu.headings', surface: 'export-menu', mock: '.menu h6', app: `${MENU} [data-slot=dropdown-menu-label]`, checks: ['type', 'colour'], list: 'fixed', unordered: true, states: [], status: 'active' },
  { id: 'export-menu.rows', surface: 'export-menu', mock: '.menu button.fmt', app: `${MENU} .menu-fmt`, checks: ['chrome', 'type', 'colour'], list: 'fixed', text: false, states: ['hover'], unordered: true, status: 'active' },
  { id: 'export-menu.formats', surface: 'export-menu', mock: '.menu button.fmt b', app: `${MENU} .menu-fmt b`, checks: ['type', 'colour'], list: 'fixed', unordered: true, states: [], status: 'active' },
  { id: 'export-menu.details', surface: 'export-menu', mock: '.menu button.fmt span', app: `${MENU} .menu-fmt b + span`, checks: ['type', 'colour'], list: 'fixed', text: false, unordered: true, states: [], status: 'active' },
]
// S8 (R2): the rename row in the topbar; (R7): the revise form in the bubble.
const titleEdit: Pair[] = [
  { id: 'title-edit.row', surface: 'title-edit', mock: '.topbar .ttl-edit', app: '.research-title-edit', checks: ['chrome'], status: 'active' },
  { id: 'title-edit.field', surface: 'title-edit', mock: '#ttlIn', app: '.research-title-input', checks: ['chrome', 'type', 'colour'], states: [], status: 'active' },
  { id: 'title-edit.suggest', surface: 'title-edit', mock: '.ttl-edit [data-act="suggesttitle"]', app: '.research-title-suggest', checks: ['chrome', 'type', 'colour', 'icon'], widths: DESK, text: true,
    icon: { mock: 'bulb', app: 'lightbulb' }, status: 'active' },
  { id: 'title-edit.save', surface: 'title-edit', mock: '.ttl-edit [data-act="savetitle"]', app: '.research-title-save', checks: ['chrome', 'type', 'colour'], text: true, status: 'active' },
  { id: 'title-edit.cancel', surface: 'title-edit', mock: '.ttl-edit [data-act="canceltitle"]', app: '.research-title-cancel', checks: ['chrome', 'icon'], icon: { mock: 'x', app: 'x' }, status: 'active' },
]
const revise: Pair[] = [
  { id: 'revise.form', surface: 'revise', mock: '.thread .q.edit', app: '.chat-question.is-editing', checks: ['content', 'colour'], use: 'decorative', status: 'active' },
  { id: 'revise.labels', surface: 'revise', mock: '.q.edit label', app: '.chat-question.is-editing label', checks: ['type', 'colour'], list: 'fixed', text: false, states: [], status: 'active' },
  { id: 'revise.question', surface: 'revise', mock: '#editq', app: '#revise-question', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'revise.terms', surface: 'revise', mock: '#editkw', app: '#revise-key-terms', checks: ['chrome', 'type', 'colour'], states: [], status: 'active' },
  { id: 'revise.buttons', surface: 'revise', mock: '.q.edit .rowbtns button', app: '.chat-question-buttons button', checks: ['chrome', 'type', 'colour'], list: 'fixed', text: false, status: 'active' },
]

export const PAIRS: Pair[] = [
  ...researchMenu,
  ...exportMenu,
  ...titleEdit,
  ...revise,
  ...shell('home'),
  ...states,
  ...palette,
  ...keysDialog,
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
  { id: 'home.mode-chips', surface: 'home', mock: '.chips .chip', app: '.mode-chips .chip', checks: ['chrome', 'type', 'colour', 'icon'], list: 'fixed',
    icon: [['file', 'file-text'], ['search', 'search'], ['table', 'table-2'], ['graph', 'network'], ['clip', 'paperclip']].map(([mock, app]) => ({ mock, app })),
    states: ['hover', 'selected'], selected: { mock: '.chips .chip.on', app: '.mode-chips .chip.on' }, status: 'active' },
  // Resume (one research exists) plus up to two Suggested cards from stored unanswered aspects (Q4).
  { id: 'home.cards', surface: 'home', mock: '.cards .card', app: '.home-cards .card', checks: ['content', 'type', 'colour'], list: 'data',
    expected: ctx => (ctx.researches ? 1 : 0) + Math.min(2, ctx.suggestions), states: ['hover'], hoverSurface: true, status: 'active' },
  { id: 'home.card-tag', surface: 'home', mock: '.cards .card .tag', app: '.home-cards .card .home-card-tag', checks: ['chrome', 'type', 'colour', 'icon'], list: 'data',
    expected: ctx => (ctx.researches ? 1 : 0) + Math.min(2, ctx.suggestions), states: [],
    icon: [{ mock: 'redo', app: 'rotate-cw' }, { mock: 'bulb', app: 'lightbulb' }, { mock: 'bulb', app: 'lightbulb' }], status: 'active' },
  { id: 'home.card-text', surface: 'home', mock: '.cards .card p', app: '.home-cards .card p', checks: ['content', 'type', 'colour'], list: 'data',
    expected: ctx => (ctx.researches ? 1 : 0) + Math.min(2, ctx.suggestions), states: [], status: 'active' },
  // The Resume card's line; a Suggested card's research title is a declared placement (exceptions.ts) and not counted.
  { id: 'home.card-meta', surface: 'home', mock: '.cards .card small', app: '.home-cards .card small', checks: ['content', 'type', 'colour'], list: 'data',
    expected: ctx => (ctx.researches ? 1 : 0), states: [], status: 'active' },
  { id: 'home.hint', surface: 'home', mock: '.home .hint', app: '.home-hint', checks: ['content', 'type', 'colour'], states: [],
    status: 'active' },

  // S5b: the first-run setup card (H2). The rows follow the head sentence and the proxy sentence, both replaced under
  // §2.3, so their y is a declared geometry exception; the mockup's "Use the example setup" row is a mockup control.
  { id: 'home-first.setup', surface: 'home-first', mock: '.setup', app: '.home-setup', checks: ['content', 'colour'], use: 'decorative', status: 'active' },
  { id: 'home-first.setup-head', surface: 'home-first', mock: '.setup h3', app: '.home-setup h2', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'home-first.setup-rows', surface: 'home-first', mock: '.setup > div:has(> .num)', app: '.home-setup-row', checks: ['content', 'type'], list: 'fixed', text: false, status: 'active' },
  { id: 'home-first.setup-num', surface: 'home-first', mock: '.setup .num:not(.ok)', app: '.home-setup .num:not(.ok)', checks: ['chrome', 'type', 'colour'], list: 'fixed', text: true, states: [], status: 'active' },
  { id: 'home-first.setup-num-ok', surface: 'home-first', mock: '.setup .num.ok', app: '.home-setup .num.ok', checks: ['chrome', 'colour', 'icon'], use: 'icon', states: [],
    icon: { mock: 'check', app: 'check' }, status: 'active' },
  { id: 'home-first.connect', surface: 'home-first', mock: '.setup .btn-teal', app: '.home-setup .setup-connect', checks: ['chrome', 'type', 'colour'], text: true, status: 'active' },
  { id: 'home-first.ready', surface: 'home-first', mock: '.setup .st.ok', app: '.home-setup .st.ok', checks: ['chrome', 'type', 'colour'], text: true, states: [], status: 'active' },
  { id: 'home-first.add', surface: 'home-first', mock: '.setup > div > .ghost[data-go="settings"]', app: '.home-setup .setup-add', checks: ['chrome', 'type', 'colour'], text: true, status: 'active' },
  { id: 'home-first.connect-hint', surface: 'home-first', mock: '.home-inner > p.hint', app: '.home-connect-hint', checks: ['content', 'type', 'colour'], text: true, states: [], status: 'active' },

  // S5b: the PDF guide rows (H11, Q3): check rows instead of the mockup's radio (CHECK_ROWS in exceptions.ts).
  { id: 'home-guide.guide', surface: 'home-guide', mock: '.composer .guide', app: '.composer .guide', checks: ['content', 'colour'], use: 'decorative', status: 'active' },
  { id: 'home-guide.lead', surface: 'home-guide', mock: '.guide > span', app: '.guide > span:first-child', checks: ['content', 'type', 'colour'], text: true, states: [], status: 'active' },
  { id: 'home-guide.row', surface: 'home-guide', mock: '.guide label', app: '.guide label', checks: ['content', 'type', 'colour'], list: 'data', expected: () => GUIDE_PDFS.length, states: [], status: 'active' },
  { id: 'home-guide.check', surface: 'home-guide', mock: '.guide input', app: '.guide input', checks: ['chrome'], list: 'data', expected: () => GUIDE_PDFS.length, status: 'active' },

  ...shell('research'),
  { id: 'research.topbar', surface: 'research', mock: '.topbar', app: '.research-topbar', checks: ['chrome', 'colour'], use: 'decorative', status: 'active' },
  // S8 (R1–R9): the title button, the waiting chip, Revise question (an icon at 390, a §2.2 placement), Export and ⋯.
  { id: 'research.title', surface: 'research', mock: '.topbar h1', app: '.research-topbar h1', checks: ['type'], status: 'active' },
  { id: 'research.title-button', surface: 'research', mock: '.topbar h1 .ttl', app: '.research-topbar .research-title-button', checks: ['type', 'icon'],
    icon: { mock: 'pen', app: 'pencil-line' }, status: 'active' },
  { id: 'research.wait-chip', surface: 'research', mock: '.topbar .waitchip', app: '.research-topbar .wait-chip', checks: ['chrome', 'type', 'colour', 'icon'], widths: DESK,
    icon: { mock: 'inbox', app: 'inbox' }, states: [], status: 'active' },
  { id: 'research.revise', surface: 'research', mock: '.topbar [data-act="editq"]', app: '.research-revise', checks: ['chrome', 'type', 'colour', 'icon'], widths: DESK,
    icon: { mock: 'pen', app: 'pencil-line' }, text: true, status: 'active' },
  { id: 'research.export', surface: 'research', mock: '.topbar [data-menu="export"]', app: '.research-topbar .research-export', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'dl', app: 'download' }, text: true, status: 'active' },
  { id: 'research.more', surface: 'research', mock: '.topbar [data-menu="research"]', app: '.research-topbar .research-more', checks: ['chrome', 'icon'],
    icon: { mock: 'more', app: 'ellipsis' }, status: 'active' },
  { id: 'research.thread', surface: 'research', mock: '.thread-inner', app: '.thread-inner', checks: ['content'], breakpoint: true,
    status: 'active' },
  // S8 (R13): the question bubble, its scope label in accent and "date · revision N".
  { id: 'research.question', surface: 'research', mock: '.thread .q', app: '.chat-question', checks: ['content', 'type', 'colour'], status: 'active' },
  { id: 'research.question-scope', surface: 'research', mock: '.thread .q b', app: '.chat-question > b', checks: ['type', 'colour', 'icon'], text: true,
    icon: { mock: 'search', app: 'search' }, states: [], status: 'active' },
  { id: 'research.question-time', surface: 'research', mock: '.thread .q time', app: '.chat-question > time', checks: ['type', 'colour'], states: [], status: 'active' },
  // S9 (R14): one line per phase, from the plan to the citation check. The discovery run's five phases and the latest
  // answer's two are open; an earlier answer folds to its run heading. A line's words carry its counts and provider
  // names (data), so its text is checked by the behaviour tests (e2e/steps.spec.ts), not here.
  { id: 'research.steps', surface: 'research', mock: '.steps .step', app: '.chat-steps .chat-step', checks: ['content', 'type', 'icon'], list: 'fixed',
    text: false, icon: STEP_ICONS, status: 'active' },
  { id: 'research.step-lines', surface: 'research', mock: '.steps .step > button', app: '.chat-steps .chat-step-line', checks: ['content', 'type', 'colour'], list: 'fixed',
    text: false, states: ['hover'], status: 'active' },
  { id: 'research.usage-line', surface: 'research', mock: '.steps .usage-line', app: '.usage-line', checks: ['content', 'type', 'colour'],
    states: [], status: 'active' },
  // S10 (R22-R29): the latest answer in the thread. Its words are the answer's (data); answer-thread.spec.ts checks them.
  { id: 'research.answer-card', surface: 'research', mock: '.thread .art', app: '.answer-thread #research-answer', checks: ['content', 'type', 'colour'], status: 'active' },
  { id: 'research.prose', surface: 'research', mock: '.thread .prose', app: '.answer-thread .answer-prose', checks: ['content', 'type'], status: 'active' },
  { id: 'research.methods', surface: 'research', mock: '.thread .methods', app: '.answer-thread .methods', checks: ['content', 'type'], status: 'active' },
  { id: 'research.answer-acts', surface: 'research', mock: '.thread-inner > .acts', app: '.answer-thread .answer-acts', checks: ['content'], status: 'active' },
  { id: 'research.next-steps', surface: 'research', mock: '.thread .follow', app: '.answer-thread .follow', checks: ['content', 'type'], status: 'active' },
  { id: 'research.followup-composer', surface: 'research', mock: '.mini', app: '.followup-composer', checks: ['content', 'colour'],
    status: 'pending:S22b', why: 'S22b: sticky follow-up composer' },
  // S11 (RL1-RL7): the artifacts rail. RL8's Usage box is S27's, so the box list is compared up to it (DEFERRED_TARGETS).
  { id: 'research.rail', surface: 'research', mock: '.rail', app: '.rail', checks: ['chrome'], widths: DESK, breakpoint: true, status: 'active' },
  // The boxes' h5 carries a count inside plain text (`Artifacts (2)`), so fixed text is not compared for the box frames;
  // the funnel's labels and the Run box rows are (fixed text, data left out). The frames are chrome (§4.1): the
  // Artifacts box has a row per report version and table (its height is data), the boxes below it sit lower by as much.
  { id: 'research.rail-artifacts', surface: 'research', mock: '.rail .box:first-child', app: '.rail .box:first-child', checks: ['chrome', 'content'], text: false, widths: DESK, status: 'active' },
  { id: 'research.rail-boxes', surface: 'research', mock: '.rail .box:not(:first-child)', app: '.rail .box:not(:first-child)', checks: ['chrome', 'content'], list: 'fixed', text: false, widths: DESK, status: 'active' },
  { id: 'research.rail-heads', surface: 'research', mock: '.rail .box:not(.warnbox) h5', app: '.rail .box:not(.warnbox) h5', checks: ['type', 'colour'], list: 'fixed', text: false, widths: DESK,
    states: [], status: 'active' },
  // The amber box's heading is text on the amber tint: --warn-ink (exception warn-text-on-tint), checked at 4.5:1.
  { id: 'research.rail-warn-head', surface: 'research', mock: '.rail .box.warnbox h5', app: '.rail .box.warnbox h5', checks: ['type', 'colour'], text: false, widths: DESK,
    states: [], status: 'active' },
  { id: 'research.rail-funnel', surface: 'research', mock: '.rail .fun button', app: '.rail .fun button', checks: ['chrome', 'type', 'colour'], list: 'fixed', widths: DESK,
    dataText: { mock: ['.tnum'], app: ['.rail-data'] }, states: ['hover'], status: 'active' },

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
  // The panel frame (S7a, R10/P1). Its body is each panel's own slice (S12-S15b); here the frame, its 46px head, the
  // heading and the head buttons. At 390 the panel covers the screen.
  { id: 'panel.frame', surface: 'research-panel', mock: '.panel', app: '[data-split-panel]', checks: ['chrome', 'colour'], use: 'decorative', status: 'active' },
  // At 1024 the panel and the thread are 56% / 44% of the space beside the sidebar on both sides, but the app's sidebar
  // is 224px there (App.css, under 1050px) and the mockup's 256px.
  { id: 'panel.frame@1024', surface: 'research-panel', mock: '.panel', app: '[data-split-panel]', checks: [], widths: [], breakpoint: true,
    status: 'pending:S1', why: 'S1: sidebar 256px at 1024 (app 224px), then the panel is 430px as in the mockup' },
  { id: 'panel.head', surface: 'research-panel', mock: '.panel .p-head', app: '.split-panel-head', checks: ['chrome', 'colour'], use: 'decorative', status: 'active' },
  { id: 'panel.title', surface: 'research-panel', mock: '.panel .p-head h2', app: '.split-panel-head h2', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'book', app: 'book-open' }, text: true, status: 'active' },
  { id: 'panel.wide', surface: 'research-panel', mock: '.panel .p-head [data-act="wide"]', app: '.split-panel-head .split-panel-wide', checks: ['chrome', 'colour', 'icon'],
    icon: { mock: 'max', app: 'maximize-2' }, states: ['hover'], unordered: true, status: 'active' },
  { id: 'panel.close', surface: 'research-panel', mock: '.panel .p-head [data-act="close"]', app: '.split-panel-head [aria-label="Close"]', checks: ['chrome', 'colour', 'icon'],
    icon: { mock: 'x', app: 'x' }, states: ['hover'], unordered: true, status: 'active' },
  { id: 'panel.thread', surface: 'research-panel', mock: '.thread-inner', app: '.thread-inner', checks: ['content'], widths: DESK, status: 'active' },
  { id: 'panel.thread@1024', surface: 'research-panel', mock: '.thread-inner', app: '.thread-inner', checks: [], widths: [], breakpoint: true,
    status: 'pending:S1', why: 'S1: sidebar 256px at 1024 (app 224px), then the thread beside the panel is 338px as in the mockup' },
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
