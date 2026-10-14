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
  | 'research-menu' | 'export-menu' | 'title-edit' | 'revise' | 'trash' | 'trash-confirm' | 'trash-empty' | 'report-panel' | 'report-changes' | 'cite-panel' | 'detail-panel'
  | 'sources-why' | 'sources-sel' | 'queue-panel' | 'pdfs-panel' | 'funnel-panel' | 'activity-panel'
  | 'table-panel' | 'cell-panel' | 'ereport-panel' | 'ecite-panel'
  | 'cands-panel' | 'cand-panel' | 'cev-panel' | 'review-dialog' | 'review-panel' | 'watch-panel' | 'schedule-dialog' | 'followup-turn' | 'plan-panel' | 'settings' | 'settings-sheet'
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
  /** The app URL hash for this state; `{research}` is the [parity] research id, `{report}` the research with an evidence report,
   *  `{cand}` the S15b research with a searched candidate, its review and a follow-up. */
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

/** S26: a Trash of one research and one removed source, the research newer, as the mockup's two rows. */
async function trashRows(page: Page) {
  await page.route('**/api/trash', route => route.fulfill({ json: {
    researches: [{ id: 'syn-trashed', title: 'SYNTHETIC research moved to the Trash', trashed_at: '2026-10-09T10:00:00Z' }], tables: [], templates: [],
    sources: [{ source_version_id: 'sv-syn', work_id: 'w-syn', title: 'SYNTHETIC removed source title', version_label: 'publishedVersion', year: 2021, research_id: 'syn-research', research_title: 'SYNTHETIC research that lost a source',
      removed_at: '2026-10-08T10:00:00Z', removal_note: null, found_again_at: null, quotes: 0, cells: 0, abstract_passage_id: null, cited: 0 }],
  } }))
}

/** S24: the mockup's Settings state: a saved proxy whose host answered (its "Working" line) and an OpenAlex budget with
 *  a limit (its 38% bar). SYNTHETIC records shaped like the stored ones; nothing is asked of a real proxy or OpenAlex. */
async function settingsState(page: Page) {
  const at = '2026-10-14T07:05:00Z'
  const address = 'https://login.proxy.example.edu/login?url='
  const view = { address, label: 'login.proxy.example.edu', label_default: 'login.proxy.example.edu', label_is_default: true, test_is_current: true,
    test: { proxy_reachable: true, proxy_http_status: 302, proxy_error: null, proxy_error_detail: null, scopus_complete: 'could_not_check', scopus_configured: false,
      address, route: 'SYNTHETIC-route', route_changed_during_test: false, tested_at: at } }
  await page.route('**/api/institution-proxy/settings', route => route.fulfill({ json: view }))
  await page.route('**/api/institution-proxy/test', route => route.fulfill({ json: view }))
  await page.route('**/api/institution-proxy', route => route.fulfill({ json: { address } }))
  await page.route('**/api/openalex/budget-today', route => route.fulfill({ json: { provider: 'openalex', unit: 'credits', remaining: 620, limit: 1000, used_fraction: 0.38,
    reset_at: at, as_of: at, source: 'last_stored_response' } }))
}

/** S13: the Sources panel on "Cited in answer", where the mockup opens it. */
async function citedTab(page: Page) {
  await page.locator('.source-filters button').filter({ hasText: 'Cited in answer' }).click()
  await page.locator('.source-filters button.on').filter({ hasText: 'Cited in answer' }).waitFor()
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
  { id: 'research-panel', mock: "setScenario('ok'); openPanel('sources', 'cited', false)", app: '#/research/{research}/sources', ready: '[data-split-panel] #split-panel-title',
    // The mockup opens the Sources panel on "Cited in answer", as the answer's "View N cited sources" does (S10).
    appAct: citedTab },
  // S12: the report panel (P2/P3), the Citation panel (P11) and Source details (P12-P20). The mockup's report has two
  // versions as the fixture's research has. The app opens the Citation panel from the thread's first chip whose citation
  // is a PDF page (found by the chip's locator, "PDF p. N", as the mockup's cob22 is a PDF work) and Source details from
  // that entry.
  { id: 'report-panel', mock: "setScenario('ok'); st.version = 2; st.viewVer = 2; openPanel('report')", app: '#/research/{research}', ready: '.research-topbar',
    appAct: async page => { await page.locator('#research-answer').click(); await page.locator('.report-document-head h1').waitFor() } },
  // S21: the same report with Show changes on (P4): the head's button reads Hide changes, the "Changes since V1" box sits
  // under the meta line and the text carries the marks. The mockup is put in its own late-full-text state (its `late`
  // action without the wait: akr18's PDF found, V2 written); the fixture's V2 of the [parity] research differs from V1
  // by the scripted SYNTHETIC revision of fixture_server.parity_revision (a claim's depth, a new claim, the limit).
  { id: 'report-changes', mock: "setScenario('ok'); S.akr18.acc = 'pdf'; S.akr18.pg = 11; st.pdf.status.akr18 = 'found'; st.version = 2; st.viewVer = 2; st.late = { k: 'akr18', v: 2 }; st.compare = true; openPanel('report')",
    app: '#/research/{research}', ready: '.research-topbar',
    appAct: async page => {
      await page.locator('#research-answer').click()
      await page.locator('.split-panel-head .report-compare').click()
      await page.locator('.report-panel .changes').waitFor()
    } },
  { id: 'cite-panel', mock: "setScenario('ok'); openPanel('cite', 'cob22')", app: '#/research/{research}', ready: '.research-topbar',
    appAct: async page => { await page.locator('.answer-thread .answer-prose .cite-chip[title*="PDF p."]').first().click(); await page.locator('.cite-entry .quote mark').waitFor() } },
  { id: 'detail-panel', mock: "setScenario('ok'); openPanel('cite', 'cob22'); openPanel('detail', 'cob22')", app: '#/research/{research}', ready: '.research-topbar',
    appAct: async page => {
      await page.locator('.answer-thread .answer-prose .cite-chip[title*="PDF p."]').first().click()
      await page.locator('.cite-entry .rowacts button').first().click()
      await page.locator('.source-detail .docnav').waitFor()
    } },
  // S14: the queue (P39), Get more full text (P40), Search funnel (P41) and Activity (P34) panels, each opened fresh. The
  // queue is ready once its last card's detail is read (its answers turn on); the funnel once its unscreened page is in.
  { id: 'queue-panel', mock: "setScenario('ok'); openPanel('queue', null, false)", app: '#/research/{research}/queue',
    ready: '[data-split-panel] .queue-cards > .qcard:last-child .qopts button:not([disabled])' },
  { id: 'pdfs-panel', mock: "setScenario('ok'); openPanel('pdfs', null, false)", app: '#/research/{research}/pdfs', ready: '[data-split-panel] .pdfs-panel .pdfs-answer',
    // The fixture's works all have their PDF text, so the one list with rows is "PDF text in hand", opened here.
    appAct: async page => { await page.locator('.pdfs-panel .pdf-ready-full > summary').click(); await page.locator('.pdfs-panel .pdf-ready-full li.prow').first().waitFor() } },
  { id: 'funnel-panel', mock: "setScenario('ok'); openPanel('funnel', null, false)", app: '#/research/{research}/funnel', ready: '[data-split-panel] .funnel-panel .stage .lost .link' },
  { id: 'activity-panel', mock: "setScenario('ok'); openPanel('activity', null, false)", app: '#/research/{research}/activity', ready: '[data-split-panel] .activity-table tbody tr' },
  // S15a: the Evidence table panel (P21-P26) and a cell's panel (P27) on the [parity] research's 6 × 4 table; the evidence
  // report (P28-P30) and its Citation panel (P31) on a second SYNTHETIC research whose table holds every included source,
  // which a report needs. The app opens the Citation panel from the third chip, the first that cites a table cell, as the
  // mockup's cob20|req does.
  { id: 'table-panel', mock: "setScenario('ok'); openPanel('table', null, false)", app: '#/research/{research}/table', ready: '[data-split-panel] .evidence-grid tbody tr' },
  // The cell's meta line ends in its fill time, which the fixture stamps with the clock: from 10:00 to 12:59 the hour has
  // two digits and the line wraps at 1280, moving Recheck down one line. The time is pinned to 9:05 local so the
  // measurement does not depend on when the run happens.
  { id: 'cell-panel', mock: "setScenario('ok'); openPanel('table', null, false); openPanel('cell', 'cob20|req')", app: '#/research/{research}/table', ready: '[data-split-panel] .evidence-grid tbody tr',
    prepare: page => page.route('**/api/researches/*/tables/*/cells/**', async route => {
      if (route.request().method() !== 'GET') return route.fallback()
      const response = await route.fetch()
      const cell = await response.json() as { current: { created_at: string } | null; revisions: Array<{ created_at: string }> }
      const at = new Date(2026, 9, 13, 9, 5).toISOString()
      for (const rev of [cell.current, ...cell.revisions]) if (rev) rev.created_at = at
      return route.fulfill({ response, json: cell })
    }),
    appAct: async page => { await page.locator('.evidence-grid [data-cell="0:0"]').click(); await page.locator('.cell-detail .dhead h1').waitFor() } },
  { id: 'ereport-panel', mock: "setScenario('ok'); erepStart(); st.erep.state = 'done'; openPanel('ereport', null, false)", app: '#/research/{report}', ready: '.research-topbar',
    appAct: async page => { await page.locator('[aria-label="Open evidence report"]').click(); await page.locator('.evidence-report-document .report-document-head h1').waitFor() } },
  { id: 'ecite-panel', mock: "setScenario('ok'); erepStart(); st.erep.state = 'done'; openPanel('ereport', null, false); openPanel('ecite', 'cob20|req')", app: '#/research/{report}', ready: '.research-topbar',
    appAct: async page => {
      await page.locator('[aria-label="Open evidence report"]').click()
      await page.locator('.evidence-report-document .cite-chip').nth(2).click()
      await page.locator('.ecite-detail .quote mark').waitFor()
    } },
  // S15b: the Candidates list (P35), one candidate stacked on it (P35), a kept work's evidence (P36), the review request
  // dialog after Preview and the review panel (P32/P33), the Follow-up panel (P37) and its Schedule dialog (P38), on the
  // {cand} research. The mockup's own candidate c1 (set to Narrowed, the status the fixture's search computes) and its
  // "Search queries of this research" follow-up (set to Manual, as the fixture's follow-up is) are the pair.
  { id: 'cands-panel', mock: "setScenario('ok'); openPanel('cands', null, false)", app: '#/research/{cand}/cands', ready: '[data-split-panel] .candidate-list .ccard' },
  { id: 'cand-panel', mock: "setScenario('ok'); cands_()[0].status = 'narrowed'; openPanel('cands', null, false); openPanel('cand', 'c1')", app: '#/research/{cand}/cands', ready: '[data-split-panel] .candidate-list .ccard',
    appAct: async page => { await page.locator('.candidate-list-row').first().click(); await page.locator('.candidate-detail .candidate-matrix').waitFor() } },
  { id: 'cev-panel', mock: "setScenario('ok'); openPanel('cands', null, false); openPanel('cand', 'c1'); openPanel('cev', 'c1|cob22')", app: '#/research/{cand}/cands', ready: '[data-split-panel] .candidate-list .ccard',
    appAct: async page => {
      await page.locator('.candidate-list-row').first().click()
      await page.locator('.candidate-detail .candidate-work-title').first().click()
      await page.locator('.candidate-evidence .candidate-passage').first().waitFor()
    } },
  { id: 'review-dialog', mock: "setScenario('ok'); openPanel('cands', null, false); openPanel('cand', 'c1')", mockAct: "reviewDlg('cand', 'c1'); document.querySelector('[data-act=\"rvpreview\"]').click()",
    app: '#/research/{cand}/cands', ready: '[data-split-panel] .candidate-list .ccard',
    appAct: async page => {
      await page.locator('.candidate-list-row').first().click()
      await page.locator('.candidate-detail .candidate-review-open').first().click()
      await page.locator('.review-dialog').getByRole('button', { name: 'Preview', exact: true }).click()
      await page.locator('.review-dialog .sendbox').waitFor()
    } },
  { id: 'review-panel', mock: "setScenario('ok'); openPanel('cands', null, false); openPanel('cand', 'c1'); st.rv = { target: 'cand', focus: 'Source support', model: 'deepseek-flash', note: '', state: 'done', g: 2, dec: {}, why: {}, applied: {}, snap: rvSnap('cand', 'c1') }; openPanel('review', null, true)",
    app: '#/research/{cand}/cands', ready: '[data-split-panel] .candidate-list .ccard',
    appAct: async page => {
      await page.locator('.candidate-list-row').first().click()
      await page.locator('.candidate-detail .review-target-line').first().click()
      await page.locator('.review-pane .finding').first().waitFor()
    } },
  { id: 'watch-panel', mock: "setScenario('ok'); openPanel('watch', null, false)", app: '#/research/{cand}/watch', ready: '[data-split-panel] .followup-watch' },
  // S23b: the Search plan panel (P42) of the [parity] research, opened fresh; ready once its buttons are drawn.
  { id: 'plan-panel', mock: "setScenario('ok'); openPanel('plan', null, false)", app: '#/research/{research}/plan', ready: '[data-split-panel] .plan-panel .rowbtns .btn-teal' },
  // S22b: a follow-up turn in the thread (R31). The mockup's own "rounds" turn (its passages do not answer, so it offers
  // "Search for new works on this"), finished at once: its timers are not started. The app's [parity] research holds one
  // SYNTHETIC follow-up the fixture's model answers `not_answered` ("[fu-not]").
  { id: 'followup-turn', mock: "setScenario('ok'); { const later = window.setTimeout; window.setTimeout = () => 0; addTurn('rounds'); window.setTimeout = later } st.turns[0].state = 'done'; render()",
    app: '#/research/{research}', ready: '.followup-turn .followup-prose' },
  { id: 'schedule-dialog', mock: "setScenario('ok'); openPanel('watch', null, false)", mockAct: "schedDlg('q', false); sdSet('freq', 0)", app: '#/research/{cand}/watch', ready: '[data-split-panel] .followup-watch',
    appAct: async page => { await page.locator('.followup-watch').first().getByRole('button', { name: 'Schedule…' }).click(); await page.locator('.followup-dialog .fmts').first().waitFor() } },
  // S13: the Sources panel with its reason bar (the first row excluded) and with its selection bar (the first row
  // chosen). The app's Exclude is answered here, so the fixture's research is never changed: the PATCH gets an empty
  // 200 and the view the page reloads has that row excluded by the person.
  { id: 'sources-why', mock: "setScenario('ok'); openPanel('sources', 'cited', false)", app: '#/research/{research}/sources', ready: '[data-split-panel] .source-table',
    mockAct: "document.querySelector('.panel tbody tr .seg button.exc').click()",
    appAct: async page => {
      await citedTab(page)
      const row = page.locator('.source-table tr.source-row').first()
      const title = (await row.locator('.src-t').innerText()).trim()
      await page.route('**/api/researches/*/selections/*', route => route.request().method() === 'PATCH' ? route.fulfill({ json: {} }) : route.fallback())
      await page.route(url => /^\/api\/researches\/[^/]+$/.test(url.pathname), async route => {
        if (route.request().method() !== 'GET') return route.fallback()
        const response = await route.fetch()
        const body = await response.json() as { sources: Array<{ title: string; version_role: string; selection: Record<string, unknown> }> }
        const source = body.sources.find(s => s.version_role === 'record' && s.title === title)
        if (source) source.selection = { ...source.selection, state: 'excluded', origin: 'user', user_reason: null }
        await route.fulfill({ response, json: body })
      })
      await row.getByRole('button', { name: 'Exclude' }).click()
      await page.locator('.why-bar').waitFor()
    } },
  { id: 'sources-sel', mock: "setScenario('ok'); openPanel('sources', 'cited', false)", app: '#/research/{research}/sources', ready: '[data-split-panel] .source-table',
    mockAct: "document.querySelector('.panel tbody input[data-sel]').click()",
    appAct: async page => { await citedTab(page); await page.locator('.source-table tr.source-row td.cb input').first().check(); await page.locator('.selbar').waitFor() } },
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
  // S26: the Trash page. The app's /api/trash is answered with two SYNTHETIC rows shaped like the mockup's (a research,
  // then a source); the fixture server's own Trash is empty and nothing in the parity research is removed.
  { id: 'trash', mock: "setScenario('ok'); go('trash')", app: '#/trash', ready: '.trash-rows', prepare: trashRows },
  { id: 'trash-confirm', mock: "setScenario('ok'); go('trash')", mockAct: 'st.trashAsk = 0; render()', app: '#/trash', ready: '.trash-rows', prepare: trashRows,
    appAct: page => page.locator('.trash-row .trash-delete').first().click() },
  { id: 'trash-empty', mock: "setScenario('ok'); st.trashR = []; go('trash')", app: '#/trash', ready: '.trash-empty', prepare: page => page.route('**/api/trash', route => route.fulfill({ json: { researches: [], tables: [], sources: [], templates: [] } })) },
  { id: 'title-edit', mock: "setScenario('ok')", mockAct: 'st.renTitle = true; render()', app: '#/research/{research}', ready: '.research-topbar',
    // The app focuses the field it opens; the mockup's render leaves it unfocused, so the field is compared at rest.
    appAct: async page => { await page.locator('.research-topbar .research-title-button').click(); await page.locator('.research-title-input').blur() } },
  { id: 'revise', mock: "setScenario('ok')", mockAct: 'st.editQ = true; render()', app: '#/research/{research}', ready: '.research-topbar', widths: DESK,
    appAct: async page => { await page.locator('.research-topbar .research-revise').click(); await page.locator('#revise-question').blur() } },
  // S24: the Settings page (ST1–ST11), one column in the mockup's order with the Cloud models block (PLACEMENTS) after
  // Default models.
  { id: 'settings', mock: "setScenario('ok'); go('settings')", app: '#/settings', ready: '.settings-page .set-usage [data-role="openalex"] small', prepare: settingsState },
  { id: 'settings-sheet', mock: "setScenario('ok'); go('settings')", mockAct: "st.conn = 'Codex CLI'; render()", app: '#/settings', ready: '.settings-page .set-usage', prepare: settingsState,
    appAct: async page => {
      await page.locator('.grid3[data-group="computer"] .conn').filter({ hasText: /^Codex CLI/ }).click()
      await page.locator('.connection-sheet .connection-body .acts').waitFor()
      await page.mouse.move(0, 0)
    } },
  { id: 'dialog', mock: HOME, mockAct: "zoteroDlg('home')", app: '#/settings/connections', ready: '.settings-page .grid3[data-group="computer"]', reader: 'not-installed',
    appAct: async page => {
      await page.getByRole('button', { name: /^Equation reader/ }).click()
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

// O1 (S3): the search palette over the research page. The page's rows hold the funnel row since S14; the
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
    icon: [{ mock: 'book', app: 'book-open' }, { mock: 'doc', app: 'text-align-start' }, { mock: 'funnel', app: 'funnel' }, { mock: 'inbox', app: 'inbox' }, { mock: 'file', app: 'file-text' }, { mock: 'moon', app: 'moon' }],
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
// S8 (R8): the Export menu. The PDF rows open the print dialog (S27); the PRISMA-S rows are a PLACEMENT. The
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

// S26: the Trash page (T1-T3). The source row's ⋯ button and title button are the PLACEMENT trash-source-menu; the
// confirm texts are COPY_CHANGES trash-confirm-*. Row notes are data (the dates and titles come from the records).
// S24: the Settings page (ST1–ST11). Pairs below the Cloud models block (a PLACEMENT) compare x and width, not y. Tile
// pills, tile notes and the semantic rows' notes carry changed copy (COPY_CHANGES settings-*, semantic-*), so their text
// is not compared; headings, role and usage names and the language row are.
const SI = '.settings-in'
const SP = '.settings-page'
const settingsPage: Pair[] = [
  { id: 'settings.title', surface: 'settings', mock: `${SI} > h1`, app: `${SP} > h1`, checks: ['chrome', 'type', 'colour'], text: true, status: 'active' },
  { id: 'settings.headings', surface: 'settings', mock: `${SI} > h2`, app: `${SP} > h2`, checks: ['content', 'type', 'colour'], list: 'fixed', text: true, states: [], status: 'active' },
  { id: 'settings.roles', surface: 'settings', mock: `${SI} > .rows:has(select)`, app: `${SP} > .set-roles`, checks: ['chrome', 'colour'], use: 'decorative', status: 'active' },
  { id: 'settings.role', surface: 'settings', mock: `${SI} > .rows:has(select) > div`, app: '.set-roles > div', checks: ['chrome', 'colour'], use: 'decorative', list: 'fixed', text: false, status: 'active' },
  { id: 'settings.role-name', surface: 'settings', mock: `${SI} > .rows:has(select) > div > b`, app: '.set-roles > div > b', checks: ['type', 'colour'], list: 'fixed', text: true, states: [], status: 'active' },
  { id: 'settings.role-note', surface: 'settings', mock: `${SI} > .rows:has(select) > div > p`, app: '.set-roles > div > p', checks: ['type', 'colour'], list: 'fixed', text: true, states: [], status: 'active' },
  { id: 'settings.role-select', surface: 'settings', mock: `${SI} > .rows:has(select) select`, app: '.set-roles select', checks: ['type', 'colour'], list: 'fixed', text: false, states: [], status: 'active' },
  { id: 'settings.computer', surface: 'settings', mock: `${SI} > h2:nth-of-type(2) + .grid3`, app: '.grid3[data-group="computer"]', checks: ['content'], status: 'active' },
  { id: 'settings.computer-tile', surface: 'settings', mock: `${SI} > h2:nth-of-type(2) + .grid3 > .conn`, app: '.grid3[data-group="computer"] > .conn', checks: ['content', 'colour'], use: 'decorative', list: 'fixed', text: false, states: ['hover'], hoverSurface: true, status: 'active' },
  { id: 'settings.tile-name', surface: 'settings', mock: `${SI} > h2:nth-of-type(2) + .grid3 > .conn > b`, app: '.grid3[data-group="computer"] > .conn > b', checks: ['type', 'colour'], list: 'fixed', text: false, states: [], status: 'active' },
  { id: 'settings.tile-pill', surface: 'settings', mock: `${SI} > h2:nth-of-type(2) + .grid3 > .conn .st`, app: '.grid3[data-group="computer"] > .conn .st', checks: ['type'], list: 'fixed', text: false, states: [], status: 'active' },
  { id: 'settings.tile-note', surface: 'settings', mock: `${SI} > h2:nth-of-type(2) + .grid3 > .conn small`, app: '.grid3[data-group="computer"] > .conn small', checks: ['type', 'colour'], list: 'fixed', text: false, states: [], status: 'active' },
  { id: 'settings.semantic-note', surface: 'settings', mock: `${SI} > h2:nth-of-type(3) + .foot-note`, app: `${SP} > .foot-note:has(+ .semantic-choices)`, checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'settings.semantic', surface: 'settings', mock: `${SI} > .rows.opts`, app: '.semantic-choices', checks: ['content', 'colour'], use: 'decorative', status: 'active' },
  { id: 'settings.semantic-row', surface: 'settings', mock: `${SI} > .rows.opts > label`, app: '.semantic-choices > .semantic-option > label', checks: ['content', 'type'], list: 'fixed', text: false, status: 'active' },
  { id: 'settings.semantic-note-row', surface: 'settings', mock: `${SI} > .rows.opts > label small`, app: '.semantic-choices > .semantic-option > label small', checks: ['type', 'colour'], list: 'fixed', text: false, states: [], status: 'active' },
  { id: 'settings.proxy', surface: 'settings', mock: `${SI} .proxy`, app: `${SP} .proxy`, checks: ['content', 'colour'], use: 'decorative', status: 'active' },
  { id: 'settings.proxy-label', surface: 'settings', mock: `${SI} .proxy > .lbl`, app: `${SP} .proxy > .lbl`, checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'settings.proxy-field', surface: 'settings', mock: '#pxUrl', app: '#proxy-address', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'settings.proxy-test', surface: 'settings', mock: `${SI} .proxy .lbl .row button`, app: `${SP} .proxy .lbl .row button`, checks: ['content', 'type', 'colour'], list: 'fixed', text: true, states: ['hover'], status: 'active' },
  { id: 'settings.proxy-state', surface: 'settings', mock: `${SI} .proxy > .row`, app: `${SP} .proxy > .proxy-state`, checks: ['content', 'type', 'colour'], text: false, states: [], status: 'active' },
  { id: 'settings.proxy-foot', surface: 'settings', mock: `${SI} .proxy > .foot-note`, app: `${SP} .proxy > .foot-note`, checks: ['type', 'colour'], text: false, states: [], status: 'active' },
  { id: 'settings.source-tile', surface: 'settings', mock: `${SI} > h2:nth-of-type(5) + .grid3 > .conn`, app: '.grid3[data-group="sources"] > .conn', checks: ['content', 'colour'], use: 'decorative', list: 'fixed', text: false, states: ['hover'], hoverSurface: true, status: 'active' },
  { id: 'settings.reference-tile', surface: 'settings', mock: `${SI} > h2:nth-of-type(6) + .grid3 > .conn`, app: '.grid3[data-group="references"] > .conn', checks: ['content', 'colour'], use: 'decorative', list: 'fixed', text: false, states: ['hover'], hoverSurface: true, status: 'active' },
  { id: 'settings.usage', surface: 'settings', mock: `${SI} > h2:nth-of-type(7) + .rows`, app: '.set-usage', checks: ['content', 'colour'], use: 'decorative', status: 'active' },
  { id: 'settings.usage-row', surface: 'settings', mock: `${SI} > h2:nth-of-type(7) + .rows > div`, app: '.set-usage > div', checks: ['content', 'colour'], use: 'decorative', list: 'fixed', text: false, status: 'active' },
  { id: 'settings.usage-name', surface: 'settings', mock: `${SI} > h2:nth-of-type(7) + .rows > div > b`, app: '.set-usage > div > b', checks: ['type', 'colour'], list: 'fixed', text: true, states: [], status: 'active' },
  { id: 'settings.usage-bar', surface: 'settings', mock: `${SI} > h2:nth-of-type(7) + .rows .bar`, app: '.set-usage .bar', checks: ['colour'], use: 'decorative', list: 'fixed', text: false, states: [], status: 'active' },
  { id: 'settings.usage-value', surface: 'settings', mock: `${SI} > h2:nth-of-type(7) + .rows > div > p`, app: '.set-usage > div > p', checks: ['type', 'colour'], list: 'fixed', text: false, states: [], status: 'active' },
  { id: 'settings.language', surface: 'settings', mock: `${SI} > .rows:has(.lang) > div`, app: '.set-lang > div', checks: ['content', 'colour'], use: 'decorative', status: 'active' },
  { id: 'settings.language-name', surface: 'settings', mock: `${SI} > .rows:has(.lang) b`, app: '.set-lang b', checks: ['type', 'colour'], text: true, states: [], status: 'active' },
  { id: 'settings.language-note', surface: 'settings', mock: `${SI} > .rows:has(.lang) p`, app: '.set-lang p', checks: ['content', 'type', 'colour'], text: true, states: [], status: 'active' },
  { id: 'settings.language-switch', surface: 'settings', mock: `${SI} .lang`, app: '.set-lang .lang', checks: ['content', 'colour'], use: 'decorative', status: 'active' },
  { id: 'settings.language-button', surface: 'settings', mock: `${SI} .lang button`, app: '.set-lang .lang button', checks: ['content', 'type', 'colour'], list: 'fixed', text: true, states: [], status: 'active' },
  // The connection sheet (mockup `connSheet()`), shown for Codex CLI: head, live state line, account sentence (COPY_CHANGES
  // account-codex) and the two buttons. The checks and models below the buttons are the PLACEMENT settings-sheet-facts.
  { id: 'settings-sheet.scrim', surface: 'settings-sheet', mock: '.sheet-scrim', app: '[data-slot=sheet-overlay]', checks: ['chrome', 'colour'], use: 'decorative', unordered: true, status: 'active' },
  { id: 'settings-sheet.sheet', surface: 'settings-sheet', mock: 'aside.sheet', app: '.connection-sheet', checks: ['chrome', 'colour'], use: 'decorative', unordered: true, status: 'active' },
  { id: 'settings-sheet.head', surface: 'settings-sheet', mock: 'aside.sheet .p-head', app: '.connection-sheet [data-slot=sheet-header]', checks: ['chrome', 'colour'], use: 'decorative', unordered: true, status: 'active' },
  { id: 'settings-sheet.title', surface: 'settings-sheet', mock: 'aside.sheet .p-head h2', app: '.connection-sheet [data-slot=sheet-title]', checks: ['type', 'icon'], icon: { mock: 'link', app: 'link' }, text: true, unordered: true, status: 'active' },
  { id: 'settings-sheet.close', surface: 'settings-sheet', mock: 'aside.sheet .p-head .ib', app: '.connection-sheet [data-slot=sheet-close]', checks: ['chrome', 'icon'], icon: { mock: 'x', app: 'x' }, unordered: true, status: 'active' },
  { id: 'settings-sheet.meta', surface: 'settings-sheet', mock: 'aside.sheet .pad.detail > .dmeta', app: '.connection-body > .dmeta', checks: ['chrome', 'type'], text: false, unordered: true, status: 'active' },
  { id: 'settings-sheet.account', surface: 'settings-sheet', mock: 'aside.sheet .pad.detail > .foot-note', app: '.connection-body > .foot-note', checks: ['content', 'type', 'colour'], text: false, states: [], unordered: true, status: 'active' },
  { id: 'settings-sheet.buttons', surface: 'settings-sheet', mock: 'aside.sheet .pad.detail .acts button', app: '.connection-body > .acts button', checks: ['content', 'type', 'colour'], list: 'fixed', text: true, states: ['hover'], unordered: true, status: 'active' },
]

const TR = '.settings .rows > div'
const trashPage: Pair[] = [
  { id: 'trash.title', surface: 'trash', mock: '.settings h1', app: '.trash-page > h1', checks: ['chrome', 'type', 'colour'], text: true, status: 'active' },
  { id: 'trash.rows', surface: 'trash', mock: '.settings .rows', app: '.trash-rows', checks: ['content', 'colour'], use: 'decorative', status: 'active' },
  { id: 'trash.row', surface: 'trash', mock: TR, app: '.trash-rows > .trash-row', checks: ['content', 'colour'], use: 'decorative', list: 'fixed', text: false, status: 'active' },
  { id: 'trash.kind', surface: 'trash', mock: `${TR} > b`, app: '.trash-row > b', checks: ['content', 'type', 'colour'], list: 'fixed', text: true, status: 'active' },
  { id: 'trash.note', surface: 'trash', mock: `${TR} > p`, app: '.trash-row > p', checks: ['content', 'type', 'colour'], list: 'fixed', text: false, states: [], status: 'active' },
  { id: 'trash.restore', surface: 'trash', mock: `${TR} [data-trrestore]`, app: '.trash-restore', checks: ['chrome', 'type', 'colour'], list: 'fixed', text: true, states: ['hover'], status: 'active' },
  { id: 'trash.delete', surface: 'trash', mock: `${TR} [data-trdel]`, app: '.trash-delete', checks: ['chrome', 'type', 'colour'], list: 'fixed', text: true, states: ['hover'], status: 'active' },
  { id: 'trash.foot', surface: 'trash', mock: '.settings .foot-note', app: '.trash-foot', checks: ['content', 'type', 'colour'], text: true, states: [], status: 'active' },
  { id: 'trash-confirm.notice', surface: 'trash-confirm', mock: '.settings .notice.warn', app: '.trash-notice', checks: ['content', 'colour'], use: 'decorative', status: 'active' },
  { id: 'trash-confirm.icon', surface: 'trash-confirm', mock: '.notice.warn > svg.i', app: '.trash-notice > svg', checks: ['chrome', 'colour', 'icon'], use: 'icon', icon: { mock: 'warn', app: 'triangle-alert' }, states: [], status: 'active' },
  { id: 'trash-confirm.text', surface: 'trash-confirm', mock: '.notice.warn .nb > span', app: '.trash-notice-body > span', checks: ['content', 'type', 'colour'], text: false, status: 'active' },
  { id: 'trash-confirm.buttons', surface: 'trash-confirm', mock: '.notice.warn .acts .ghost', app: '.trash-acts .trash-ghost', checks: ['chrome', 'type', 'colour'], list: 'fixed', text: true, states: ['hover'], status: 'active' },
  { id: 'trash-empty.empty', surface: 'trash-empty', mock: '.settings .empty', app: '.trash-empty', checks: ['content', 'colour'], use: 'decorative', status: 'active' },
  { id: 'trash-empty.icon', surface: 'trash-empty', mock: '.empty svg.i', app: '.trash-empty svg', checks: ['chrome', 'colour', 'icon'], use: 'icon', icon: { mock: 'trash', app: 'trash' }, status: 'active' },
  { id: 'trash-empty.heading', surface: 'trash-empty', mock: '.empty h2', app: '.trash-empty h2', checks: ['chrome', 'type', 'colour'], text: true, status: 'active' },
  { id: 'trash-empty.text', surface: 'trash-empty', mock: '.empty p', app: '.trash-empty p', checks: ['content', 'type', 'colour'], text: true, states: [], status: 'active' },
  { id: 'trash-empty.foot', surface: 'trash-empty', mock: '.settings .foot-note', app: '.trash-foot', checks: ['content', 'type', 'colour'], text: true, states: [], status: 'active' },
]

export const PAIRS: Pair[] = [
  ...settingsPage,
  ...trashPage,
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
  // S22b (R30): the sticky follow-up composer at the foot of the thread: the field, "+" (Get more full text), the
  // research's depth as a label (COPY_CHANGES followup-depth-label) and Send.
  { id: 'research.followup-compose', surface: 'research', mock: '.foot-compose', app: '.followup-compose', checks: ['chrome'], use: 'decorative', status: 'active' },
  { id: 'research.followup-composer', surface: 'research', mock: '.mini', app: '.followup-composer', checks: ['content', 'colour'], use: 'decorative', status: 'active' },
  { id: 'research.followup-field', surface: 'research', mock: '.mini textarea', app: '.followup-composer textarea', checks: ['chrome', 'type'], status: 'active' },
  { id: 'research.followup-add', surface: 'research', mock: '.mini .r .ib', app: '.followup-composer .followup-add', checks: ['chrome', 'colour', 'icon'],
    icon: { mock: 'plus', app: 'plus' }, states: [], status: 'active' },
  { id: 'research.followup-depth', surface: 'research', mock: '.mini .r .ghost', app: '.followup-composer .followup-depth', checks: ['chrome', 'type', 'colour'], states: [], status: 'active' },
  { id: 'research.followup-send', surface: 'research', mock: '.mini .r .send', app: '.followup-composer .followup-send', checks: ['chrome', 'colour', 'icon'],
    icon: { mock: 'up', app: 'arrow-up' }, use: 'icon', states: [], status: 'active' },
  // S11 (RL1-RL7): the artifacts rail; RL8's Usage box (S27) is the last box, its own pair below.
  { id: 'research.rail', surface: 'research', mock: '.rail', app: '.rail', checks: ['chrome'], widths: DESK, breakpoint: true, status: 'active' },
  // The boxes' h5 carries a count inside plain text (`Artifacts (2)`), so fixed text is not compared for the box frames;
  // the funnel's labels and the Run box rows are (fixed text, data left out). The frames are chrome (§4.1): the
  // Artifacts box has a row per report version and table (its height is data), the boxes below it sit lower by as much.
  { id: 'research.rail-artifacts', surface: 'research', mock: '.rail .box:first-child', app: '.rail .box:first-child', checks: ['chrome', 'content'], text: false, widths: DESK, status: 'active' },
  { id: 'research.rail-boxes', surface: 'research', mock: '.rail .box:not(:first-child):not(:has(.legend)):not(:last-child)', app: '.rail .box:not(:first-child):not(:has(.legend)):not(:last-child)', checks: ['chrome', 'content'], list: 'fixed', text: false, widths: DESK, status: 'active' },
  // The Usage box (RL8, S27) names the run its calls belong to and the time of the stored OpenAlex response, two lines
  // the mockup lacks (PLACEMENTS rail-usage-notes), and draws the budget bar only with a limit header; its height is left
  // out (GEOMETRY_EXCEPTIONS rail-usage-height). Its kv rows are compared for type and colour.
  { id: 'research.rail-usage', surface: 'research', mock: '.rail .box:last-child', app: '.rail .box:last-child', checks: ['chrome', 'content'], text: false, widths: DESK, status: 'active' },
  { id: 'research.rail-usage-kv', surface: 'research', mock: '.rail .box:last-child .kv', app: '.rail .box:last-child .kv', checks: ['type', 'colour'], list: 'fixed', widths: DESK,
    dataText: { mock: ['.tnum'], app: ['.rail-data'] }, states: [], status: 'active' },
  // The depth box ("How deeply sources were read", the one box with a legend) is its own pair: it carries a scope line
  // the mockup lacks (GEOMETRY_EXCEPTIONS rail-depth-scope-height), so only its height is left out.
  { id: 'research.rail-depth', surface: 'research', mock: '.rail .box:has(.legend)', app: '.rail .box:has(.legend)', checks: ['chrome', 'content'], text: false, widths: DESK, status: 'active' },
  { id: 'research.rail-heads', surface: 'research', mock: '.rail .box:not(.warnbox) h5', app: '.rail .box:not(.warnbox) h5', checks: ['type', 'colour'], list: 'fixed', text: false, widths: DESK,
    states: [], status: 'active' },
  // The amber box's heading is text on the amber tint: --warn-ink (exception warn-text-on-tint), checked at 4.5:1.
  { id: 'research.rail-warn-head', surface: 'research', mock: '.rail .box.warnbox h5', app: '.rail .box.warnbox h5', checks: ['type', 'colour'], text: false, widths: DESK,
    states: [], status: 'active' },
  { id: 'research.rail-funnel', surface: 'research', mock: '.rail .fun button', app: '.rail .fun button', checks: ['chrome', 'type', 'colour'], list: 'fixed', widths: DESK,
    dataText: { mock: ['.tnum'], app: ['.rail-data'] }, states: ['hover'], status: 'active' },


  // S22b (R31): one follow-up turn: the Question bubble, its two step lines, the short answer and its actions. The
  // bubble is as wide as its question (data, GEOMETRY_EXCEPTIONS followup-question-width); the step lines' words carry
  // the passage count (data), so their text is checked by e2e/followup-turns.spec.ts.
  { id: 'followup-turn.question', surface: 'followup-turn', mock: '.thread-inner > .follow ~ .q', app: '.followup-turn .followup-q', checks: ['content', 'type', 'colour'], status: 'active' },
  { id: 'followup-turn.question-label', surface: 'followup-turn', mock: '.thread-inner > .follow ~ .q b', app: '.followup-turn .followup-q > b', checks: ['type', 'colour', 'icon'], text: true,
    icon: { mock: 'chat', app: 'message-square' }, states: [], status: 'active' },
  { id: 'followup-turn.steps', surface: 'followup-turn', mock: '.thread-inner > .follow ~ .steps .step', app: '.followup-turn .followup-step', checks: ['content', 'type', 'icon'], list: 'fixed',
    text: false, icon: [{ mock: 'book', app: 'book-open' }, { mock: 'pen', app: 'pencil-line' }], status: 'active' },
  { id: 'followup-turn.step-lines', surface: 'followup-turn', mock: '.thread-inner > .follow ~ .steps .step > button', app: '.followup-turn .followup-step-line', checks: ['content', 'type', 'colour'], list: 'fixed',
    text: false, states: [], status: 'active' },
  { id: 'followup-turn.prose', surface: 'followup-turn', mock: '.thread-inner > .follow ~ .prose', app: '.followup-turn .followup-prose', checks: ['content', 'type'], status: 'active' },
  { id: 'followup-turn.acts', surface: 'followup-turn', mock: '.thread-inner > .follow ~ .acts', app: '.followup-turn .followup-acts', checks: ['content'], status: 'active' },
  { id: 'followup-turn.search', surface: 'followup-turn', mock: '.thread-inner > .follow ~ .acts .ghost', app: '.followup-turn .followup-acts .answer-pill', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'search', app: 'search' }, text: true, states: [], status: 'active' },
  { id: 'followup-turn.copy', surface: 'followup-turn', mock: '.thread-inner > .follow ~ .acts .ib', app: '.followup-turn .followup-acts .answer-ib', checks: ['chrome', 'icon'],
    icon: { mock: 'copy', app: 'copy' }, states: [], status: 'active' },
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
  // S13 Sources panel body (P5, P6, P8-P10): the filter tabs, the toolbar, the table head and the first row's parts.
  // Column widths follow the rows' text (an auto table layout), so cells inside the table compare type and colour, and
  // their controls compare width and height with x and y left out (GEOMETRY_EXCEPTIONS sources-table-cells-xy).
  { id: 'sources.tabs', surface: 'research-panel', mock: '.panel .tabs button', app: '.sources-panel-box .tabs.source-filters button', checks: ['chrome', 'type', 'colour'], list: 'fixed',
    dataText: { mock: ['em'], app: ['em'] }, states: ['selected'], selected: { mock: '.panel .tabs button.on', app: '.sources-panel-box .tabs.source-filters button.on' }, status: 'active' },
  { id: 'sources.tab-count', surface: 'research-panel', mock: '.panel .tabs button em', app: '.sources-panel-box .tabs.source-filters button em', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'sources.toolbar', surface: 'research-panel', mock: '.panel .toolbar', app: '.sources-panel-box .toolbar.source-toolbar', checks: ['chrome', 'colour'], use: 'decorative', status: 'active' },
  { id: 'sources.search', surface: 'research-panel', mock: '.panel .toolbar .search', app: '.sources-panel-box .toolbar .search', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'search', app: 'search' }, use: 'icon', states: [], status: 'active' },
  { id: 'sources.tools', surface: 'research-panel', mock: '.panel .toolbar > button', app: '.sources-panel-box .toolbar > button', checks: ['chrome', 'type', 'colour', 'icon'], list: 'fixed',
    icon: [{ mock: 'sort', app: 'arrow-up-down' }, { mock: 'filter', app: 'funnel' }, { mock: 'dl', app: 'download' }, { mock: 'lib', app: 'library-big' }], states: [], status: 'active' },
  { id: 'sources.table', surface: 'research-panel', mock: '.panel .tbl-wrap', app: '.sources-panel-box .tbl-wrap', checks: ['content', 'colour'], use: 'decorative', status: 'active' },
  { id: 'sources.th', surface: 'research-panel', mock: '.panel .tbl-wrap thead th', app: '.sources-panel-box .source-table thead th', checks: ['type', 'colour'], list: 'fixed',
    dataText: { mock: ['span'], app: ['.th-count'] }, states: [], status: 'active' },
  { id: 'sources.title', surface: 'research-panel', mock: '.panel tbody tr:first-child .src-t', app: '.source-table tbody tr.source-row:first-child .src-t', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'sources.meta', surface: 'research-panel', mock: '.panel tbody tr:first-child .src-m', app: '.source-table tbody tr.source-row:first-child .src-m', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'sources.pill', surface: 'research-panel', mock: '.panel tbody tr:first-child .pills .pill', app: '.source-table tbody tr.source-row:first-child .pills .pill', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'link', app: 'link-2' }, states: [], status: 'active' },
  { id: 'sources.rowact', surface: 'research-panel', mock: '.panel tbody tr:first-child .rowacts button[data-remove]', app: '.source-table tbody tr.source-row:first-child .rowacts button[aria-label="Remove from research"]', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'trash', app: 'trash' }, states: [], status: 'active' },
  { id: 'sources.prop', surface: 'research-panel', mock: '.panel tbody tr:first-child .prop', app: '.source-table tbody tr.source-row:first-child .prop', checks: ['type', 'colour'], states: [], status: 'active' },
  // The verdict and the chosen segment of an included work (the first row's state is the fixture's data).
  { id: 'sources.verdict', surface: 'research-panel', mock: '.panel tbody .prop b.inc', app: '.source-table tbody .prop b.verdict.is-include', checks: ['type', 'colour'], unordered: true, states: [], status: 'active' },
  { id: 'sources.seg', surface: 'research-panel', mock: '.panel tbody tr:first-child .seg', app: '.source-table tbody tr.source-row:first-child .seg', checks: ['chrome', 'colour'], use: 'decorative', states: [], status: 'active' },
  { id: 'sources.seg-buttons', surface: 'research-panel', mock: '.panel tbody tr:first-child .seg button', app: '.source-table tbody tr.source-row:first-child .seg button', checks: ['chrome', 'type'], list: 'fixed', states: [], status: 'active' },
  { id: 'sources.seg-on', surface: 'research-panel', mock: '.panel tbody .seg button.on.inc', app: '.source-table tbody .seg button.is-included[aria-pressed=true]', checks: ['type', 'colour'], unordered: true, states: [], status: 'active' },
  // The reason bar above the table (P10) and the selection bar at the panel's foot (P8).
  { id: 'sources.why-bar', surface: 'sources-why', mock: '.panel .why-bar', app: '.sources-panel-box .why-bar', checks: ['chrome', 'colour'], use: 'decorative', states: [], status: 'active' },
  { id: 'sources.why-label', surface: 'sources-why', mock: '.panel .why-bar .lbl > span', app: '.sources-panel-box .why-bar .lbl > span', checks: ['type', 'colour'], dataText: { mock: ['b'], app: ['b'] }, text: true, states: [], status: 'active' },
  { id: 'sources.why-field', surface: 'sources-why', mock: '.panel .why-bar .field', app: '.sources-panel-box .why-bar .field', checks: ['chrome', 'type', 'colour'], states: [], status: 'active' },
  { id: 'sources.why-buttons', surface: 'sources-why', mock: '.panel .why-bar .why-f > button', app: '.sources-panel-box .why-bar .why-f > button', checks: ['chrome', 'type', 'colour'], list: 'fixed', states: [], status: 'active' },
  { id: 'sources.selbar', surface: 'sources-sel', mock: '.panel .selbar', app: '.sources-panel-box .selbar', checks: ['chrome', 'colour'], use: 'decorative', states: [], status: 'active' },
  { id: 'sources.selbar-count', surface: 'sources-sel', mock: '.panel .selbar > b', app: '.sources-panel-box .selbar > b', checks: ['type', 'colour'], text: true, states: [], status: 'active' },
  { id: 'sources.selbar-buttons', surface: 'sources-sel', mock: '.panel .selbar > button', app: '.sources-panel-box .selbar .selection-bar-actions > button', checks: ['chrome', 'type', 'colour', 'icon'], list: 'fixed',
    icon: [{ mock: 'table', app: 'table-2' }, { mock: 'lib', app: 'library-big' }], states: [], status: 'active' },
  // S12 report panel (P2/P3). The head: the title, Version, Citation style, Review with another model, Download. At 1280
  // every check runs. At 390 the mockup's head runs past the screen's edge (its controls are not hidden there and its
  // title shrinks to no width), so the phone pairs compare type, colour and icons and leave out geometry by the declared
  // exception report-head-phone (exceptions.ts); the title is not paired at 390 for the same reason.
  { id: 'report-panel.title', surface: 'report-panel', widths: DESK, mock: '.panel .p-head h2', app: '.split-panel-head h2', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'doc', app: 'text-align-start' }, states: [], status: 'active' },
  { id: 'report-panel.version', surface: 'report-panel', widths: DESK, mock: '.panel .p-head select[data-ver]', app: '.split-panel-head .report-select[aria-label="Version"]', checks: ['chrome', 'type', 'colour'], unordered: true, states: [], status: 'active' },
  { id: 'report-panel.style', surface: 'report-panel', widths: DESK, mock: '.panel .p-head select[data-cstyle]', app: '.split-panel-head .report-select[aria-label="Citation style"]', checks: ['chrome', 'type', 'colour'], unordered: true, states: [], status: 'active' },
  { id: 'report-panel.review', surface: 'report-panel', widths: DESK, mock: '.panel .p-head [data-act="review"]', app: '.split-panel-head .report-review', checks: ['chrome', 'colour', 'icon'],
    icon: { mock: 'shield', app: 'shield-check' }, states: ['hover'], unordered: true, status: 'active' },
  { id: 'report-panel.download', surface: 'report-panel', widths: DESK, mock: '.panel .p-head [data-menu="rexport"]', app: '.split-panel-head .report-download', checks: ['chrome', 'colour', 'icon'],
    icon: { mock: 'dl', app: 'download' }, states: ['hover'], unordered: true, status: 'active' },
  // S21: Show changes (P4), between Version and Citation style. At 390 the app draws it as a 30px eye icon with its name
  // kept for screen readers (the mockup's text button runs off the screen there), so only its colours are compared.
  { id: 'report-panel.compare', surface: 'report-panel', widths: DESK, mock: '.panel .p-head [data-act="compare"]', app: '.split-panel-head .report-compare', checks: ['chrome', 'type', 'colour'], text: true, unordered: true, states: ['hover'], status: 'active' },
  { id: 'report-panel.compare@390', surface: 'report-panel', widths: PHONE, mock: '.panel .p-head [data-act="compare"]', app: '.split-panel-head .report-compare', checks: ['colour'], unordered: true, states: [], status: 'active' },
  { id: 'report-panel.version@390', surface: 'report-panel', widths: PHONE, mock: '.panel .p-head select[data-ver]', app: '.split-panel-head .report-select[aria-label="Version"]', checks: ['chrome', 'type', 'colour'], unordered: true, states: [], status: 'active' },
  { id: 'report-panel.style@390', surface: 'report-panel', widths: PHONE, mock: '.panel .p-head select[data-cstyle]', app: '.split-panel-head .report-select[aria-label="Citation style"]', checks: ['chrome', 'type', 'colour'], unordered: true, states: [], status: 'active' },
  { id: 'report-panel.review@390', surface: 'report-panel', widths: PHONE, mock: '.panel .p-head [data-act="review"]', app: '.split-panel-head .report-review', checks: ['chrome', 'colour', 'icon'],
    icon: { mock: 'shield', app: 'shield-check' }, states: [], unordered: true, status: 'active' },
  { id: 'report-panel.download@390', surface: 'report-panel', widths: PHONE, mock: '.panel .p-head [data-menu="rexport"]', app: '.split-panel-head .report-download', checks: ['chrome', 'colour', 'icon'],
    icon: { mock: 'dl', app: 'download' }, states: [], unordered: true, status: 'active' },
  // The document: the serif title, the meta line, the section headings, the claim badges, the references, the check line.
  { id: 'report-panel.h1', surface: 'report-panel', mock: '.report h1', app: '.report-document-head h1', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'report-panel.meta', surface: 'report-panel', mock: '.report .meta', app: '.report-document-head .meta', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'report-panel.h2', surface: 'report-panel', mock: '.report h2', app: '.report-content h2', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'report-panel.badge-abs', surface: 'report-panel', mock: '.report .badge-s.v-abs', app: '.report-content .badge-s.v-abs', checks: ['type', 'colour'], text: true, unordered: true, states: [], status: 'active' },
  { id: 'report-panel.refs', surface: 'report-panel', mock: '.report .refs li', app: '.report-content .refs > li', checks: ['type'], states: [], status: 'active' },
  { id: 'report-panel.check', surface: 'report-panel', mock: '.report .check', app: '.report-content .check', checks: ['type', 'colour'], states: [], status: 'active' },
  // S21 the answer diff (P4): Hide changes in the head, the box and its heading, and the marks: a depth badge struck out
  // and its replacement (`del.badge-s`, `ins.badge-s`), and the limit removed and added (`del`, `ins` in the text).
  { id: 'report-changes.compare', surface: 'report-changes', widths: DESK, mock: '.panel .p-head [data-act="compare"]', app: '.split-panel-head .report-compare', checks: ['chrome', 'type', 'colour'], text: true, unordered: true, states: [], status: 'active' },
  { id: 'report-changes.compare@390', surface: 'report-changes', widths: PHONE, mock: '.panel .p-head [data-act="compare"]', app: '.split-panel-head .report-compare', checks: ['colour'], unordered: true, states: [], status: 'active' },
  { id: 'report-changes.box', surface: 'report-changes', mock: '.report .changes', app: '.report-panel .changes', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'report-changes.heading', surface: 'report-changes', mock: '.report .changes > b', app: '.report-panel .changes > b', checks: ['type', 'colour'], text: true, states: [], status: 'active' },
  { id: 'report-changes.badge-del', surface: 'report-changes', mock: '.report del.badge-s', app: '.report-content del.badge-s', checks: ['type', 'colour'], unordered: true, states: [], status: 'active' },
  // The added badge's colour is the "Full text" badge's own (S12: accent; the mockup's --pdf), which no report pair compares.
  { id: 'report-changes.badge-ins', surface: 'report-changes', mock: '.report ins.badge-s', app: '.report-content ins.badge-s', checks: ['type'], unordered: true, states: [], status: 'active' },
  { id: 'report-changes.del', surface: 'report-changes', mock: '.report p > del:not(.badge-s)', app: '.report-content .plain-list del', checks: ['type', 'colour'], unordered: true, states: [], status: 'active' },
  { id: 'report-changes.ins', surface: 'report-changes', mock: '.report p > ins:not(.badge-s)', app: '.report-content .plain-list ins', checks: ['type', 'colour'], unordered: true, states: [], status: 'active' },
  // S12 Citation panel (P11): one entry per cited passage.
  { id: 'cite-panel.title', surface: 'cite-panel', mock: '.panel .p-head h2', app: '.split-panel-head h2', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'link', app: 'link' }, text: true, states: [], status: 'active' },
  { id: 'cite-panel.entry', surface: 'cite-panel', mock: '.cit article', app: '.cite-entry', checks: ['chrome', 'colour'], use: 'decorative', states: [], status: 'active' },
  { id: 'cite-panel.venue', surface: 'cite-panel', mock: '.cit .venue', app: '.cite-entry .venue', checks: ['chrome', 'type', 'colour', 'icon'], icon: { mock: 'file', app: 'file-text' }, states: [], status: 'active' },
  { id: 'cite-panel.work', surface: 'cite-panel', mock: '.cit h3', app: '.cite-entry h3', checks: ['chrome', 'type', 'colour'], states: [], status: 'active' },
  { id: 'cite-panel.authors', surface: 'cite-panel', mock: '.cit .au', app: '.cite-entry .au', checks: ['chrome', 'type', 'colour'], states: [], status: 'active' },
  { id: 'cite-panel.quote', surface: 'cite-panel', mock: '.cit .quote', app: '.cite-entry .quote', checks: ['chrome', 'type', 'colour'], states: [], status: 'active' },
  { id: 'cite-panel.mark', surface: 'cite-panel', mock: '.cit .quote mark', app: '.cite-entry .quote mark.citation-highlight', checks: ['chrome', 'colour'], states: [], status: 'active' },
  { id: 'cite-panel.loc', surface: 'cite-panel', mock: '.cit .loc', app: '.cite-entry .loc', checks: ['chrome', 'type', 'colour'], states: [], status: 'active' },
  { id: 'cite-panel.located', surface: 'cite-panel', mock: '.cit .loc .ok-t', app: '.cite-entry .loc .ok-t', checks: ['chrome', 'type', 'colour'], text: true, states: [], status: 'active' },
  { id: 'cite-panel.actions', surface: 'cite-panel', mock: '.cit .rowacts button', app: '.cite-entry .rowacts button', checks: ['chrome', 'type', 'colour', 'icon'], list: 'fixed',
    icon: [{ mock: 'doc', app: 'text-align-start' }, { mock: 'file', app: 'file-text' }], states: [], status: 'active' },
  // S12 Source details (P12-P20): the work, where it stands, the action row, the tabs, the cited place, the foot.
  { id: 'detail-panel.title', surface: 'detail-panel', mock: '.panel .p-head h2', app: '.split-panel-head h2', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'file', app: 'file-text' }, text: true, states: [], status: 'active' },
  { id: 'detail-panel.back', surface: 'detail-panel', mock: '.panel .p-head [data-act="back"]', app: '.split-panel-head [aria-label="Back"]', checks: ['chrome', 'colour', 'icon'],
    icon: { mock: 'left', app: 'chevron-left' }, unordered: true, states: [], status: 'active' },
  { id: 'detail-panel.venue', surface: 'detail-panel', mock: '.detail .dhead .venue', app: '.source-detail .dhead .venue', checks: ['chrome', 'type', 'colour'], states: [], status: 'active' },
  { id: 'detail-panel.work', surface: 'detail-panel', mock: '.detail h1', app: '.source-detail .dhead .source-title', checks: ['chrome', 'type', 'colour'], states: [], status: 'active' },
  { id: 'detail-panel.authors', surface: 'detail-panel', mock: '.detail .dhead .au', app: '.source-detail .dhead .au', checks: ['chrome', 'type', 'colour'], states: [], status: 'active' },
  { id: 'detail-panel.pills', surface: 'detail-panel', mock: '.detail .dhead .pill', app: '.source-detail .dhead .pills .ref-pill', checks: ['chrome', 'type', 'colour'], list: 'data', expected: () => 2, states: [], status: 'active' },
  { id: 'detail-panel.dmeta', surface: 'detail-panel', mock: '.detail .dmeta', app: '.source-detail .dmeta', checks: ['chrome', 'type', 'colour'], states: [], status: 'active' },
  { id: 'detail-panel.primary', surface: 'detail-panel', mock: '.detail .dacts .btn-pri', app: '.source-detail .dacts .btn-pri', checks: ['chrome', 'type', 'colour', 'icon'], text: true,
    icon: { mock: 'file', app: 'file-text' }, states: ['hover'], status: 'active' },
  { id: 'detail-panel.icons', surface: 'detail-panel', mock: '.detail .dacts .ib', app: '.source-detail .dacts .ib', checks: ['chrome', 'colour', 'icon'], list: 'fixed', text: false,
    icon: [{ mock: 'link', app: 'link' }, { mock: 'copy', app: 'copy' }, { mock: 'more', app: 'ellipsis' }], states: [], status: 'active' },
  { id: 'detail-panel.tabs', surface: 'detail-panel', mock: '.detail .tabs button', app: '.source-detail [role=tablist] [role=tab]', checks: ['chrome', 'type'], list: 'fixed', states: [], status: 'active' },
  { id: 'detail-panel.docnav', surface: 'detail-panel', mock: '.detail .docnav', app: '.source-detail .docnav', checks: ['chrome', 'type', 'colour'], states: [], status: 'active' },
  { id: 'detail-panel.foot', surface: 'detail-panel', mock: '.detail > p.foot-note:last-child', app: '.source-detail .source-sheet-foot', checks: ['chrome', 'type', 'colour'], states: [], status: 'active' },
  // S14 queue panel (P39): the intro, then one card per row (the fixture's three), each with its head, title and answers.
  { id: 'queue.title', surface: 'queue-panel', mock: '.panel .p-head h2', app: '.split-panel-head h2', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'inbox', app: 'inbox' }, text: true, states: [], status: 'active' },
  { id: 'queue.intro', surface: 'queue-panel', mock: '.panel .pad > p', app: '.queue-panel > p', checks: ['chrome', 'type', 'colour'], states: [], status: 'active' },
  { id: 'queue.cards', surface: 'queue-panel', mock: '.panel .qcard', app: '.queue-panel .qcard', checks: ['chrome', 'colour'], use: 'decorative', list: 'data', expected: () => 3, states: [], status: 'active' },
  { id: 'queue.head', surface: 'queue-panel', mock: '.panel .qcard header', app: '.queue-panel .qcard header', checks: ['chrome', 'type', 'colour'], list: 'data', expected: () => 3, states: [], status: 'active' },
  { id: 'queue.kind', surface: 'queue-panel', mock: '.panel .qcard header b', app: '.queue-panel .qcard header b', checks: ['type', 'colour'], use: 'icon', states: [], status: 'active' },
  { id: 'queue.work', surface: 'queue-panel', mock: '.panel .qcard .qb h4', app: '.queue-panel .qcard .qb h4', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'queue.answer', surface: 'queue-panel', mock: '.panel .qcard .qopts button', app: '.queue-panel .qcard .qopts button', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'check', app: 'check' }, states: ['hover'], status: 'active' },
  { id: 'queue.answer-note', surface: 'queue-panel', mock: '.panel .qcard .qopts button small', app: '.queue-panel .qcard .qopts button small', checks: ['type', 'colour'], states: [], status: 'active' },
  // S14 Get more full text (P40): the depth boxes, Collect, the first list's head, the drop zone and the answer button.
  { id: 'pdfs.title', surface: 'pdfs-panel', mock: '.panel .p-head h2', app: '.split-panel-head h2', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'file', app: 'file-text' }, states: [], status: 'active' },
  { id: 'pdfs.heading', surface: 'pdfs-panel', mock: '.panel .pad > h3', app: '.pdfs-panel > h3', checks: ['chrome', 'type', 'colour'], text: true, states: [], status: 'active' },
  { id: 'pdfs.depth', surface: 'pdfs-panel', mock: '.panel .depth', app: '.pdfs-panel .depth', checks: ['chrome', 'colour'], use: 'decorative', states: [], status: 'active' },
  { id: 'pdfs.depth-cells', surface: 'pdfs-panel', mock: '.panel .depth > div', app: '.pdfs-panel .depth > div', checks: ['chrome', 'colour'], use: 'decorative', list: 'data', expected: () => 4, states: [], status: 'active' },
  { id: 'pdfs.depth-n', surface: 'pdfs-panel', mock: '.panel .depth b', app: '.pdfs-panel .depth b', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'pdfs.depth-label', surface: 'pdfs-panel', mock: '.panel .depth span', app: '.pdfs-panel .depth span', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'pdfs.collect', surface: 'pdfs-panel', mock: '.panel .acts [data-act="collect"]', app: '.pdfs-panel .acts .btn-teal', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'dl', app: 'download' }, text: true, states: [], status: 'active' },
  { id: 'pdfs.list-head', surface: 'pdfs-panel', mock: '.panel .plist > h4', app: '.pdfs-panel .plist > h4', checks: ['chrome', 'type', 'colour'], states: [], status: 'active' },
  { id: 'pdfs.row', surface: 'pdfs-panel', mock: '.panel .plist .prow', app: '.pdfs-panel .plist li.prow', checks: ['type', 'colour'], unordered: true, states: [], status: 'active' },
  { id: 'pdfs.drop', surface: 'pdfs-panel', mock: '.panel .drop', app: '.pdfs-panel .drop', checks: ['chrome', 'type', 'colour', 'icon'], icon: { mock: 'ul', app: 'upload' }, states: [], status: 'active' },
  { id: 'pdfs.answer', surface: 'pdfs-panel', mock: '.panel .acts [data-act="genv2"]', app: '.pdfs-panel .pdfs-answer .btn-teal', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'redo', app: 'rotate-cw' }, states: [], status: 'active' },
  // S14 Search funnel (P41): the lede, six stages with their share and bar, what was lost, and the wider-net notice.
  { id: 'funnel.title', surface: 'funnel-panel', mock: '.panel .p-head h2', app: '.split-panel-head h2', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'funnel', app: 'funnel' }, text: true, states: [], status: 'active' },
  { id: 'funnel.lede', surface: 'funnel-panel', mock: '.panel .pad > p', app: '.funnel-panel > p', checks: ['chrome', 'type', 'colour'], text: true, states: [], status: 'active' },
  { id: 'funnel.stages', surface: 'funnel-panel', mock: '.panel .stage', app: '.funnel-panel .stage', checks: ['chrome', 'colour'], use: 'decorative', list: 'data', expected: () => 6, states: [], status: 'active' },
  { id: 'funnel.label', surface: 'funnel-panel', mock: '.panel .stage h4', app: '.funnel-panel .stage h4', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'funnel.note', surface: 'funnel-panel', mock: '.panel .stage h4 small', app: '.funnel-panel .stage h4 small', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'funnel.count', surface: 'funnel-panel', mock: '.panel .stage .kv span:first-child', app: '.funnel-panel .stage .kv span:first-child', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'funnel.share', surface: 'funnel-panel', mock: '.panel .stage .kv span:last-child', app: '.funnel-panel .stage .kv span:last-child', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'funnel.track', surface: 'funnel-panel', mock: '.panel .stage .track', app: '.funnel-panel .stage .track', checks: ['chrome', 'colour'], use: 'decorative', states: [], status: 'active' },
  { id: 'funnel.bar', surface: 'funnel-panel', mock: '.panel .stage .track i', app: '.funnel-panel .stage .track i', checks: ['chrome', 'colour'], use: 'decorative', states: [], status: 'active' },
  { id: 'funnel.lost', surface: 'funnel-panel', mock: '.panel .stage .lost', app: '.funnel-panel .stage .lost', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'funnel.lost-n', surface: 'funnel-panel', mock: '.panel .stage .lost b', app: '.funnel-panel .stage .lost b', checks: ['type', 'colour'], use: 'icon', states: [], status: 'active' },
  { id: 'funnel.link', surface: 'funnel-panel', mock: '.panel .stage .lost .link', app: '.funnel-panel .stage .lost .link', checks: ['type', 'colour'], text: true, states: [], status: 'active' },
  { id: 'funnel.notice', surface: 'funnel-panel', mock: '.panel .pad > .notice', app: '.funnel-panel > .notice', checks: ['chrome', 'type', 'colour', 'icon'], icon: { mock: 'info', app: 'info' }, states: [], status: 'active' },
  // S14 Activity (P34): the runs table, its status pill and the foot note; the recorded events follow (PLACEMENTS activity-events).
  { id: 'activity.title', surface: 'activity-panel', mock: '.panel .p-head h2', app: '.split-panel-head h2', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'clock', app: 'clock' }, text: true, states: [], status: 'active' },
  { id: 'activity.table', surface: 'activity-panel', mock: '.panel .p-body > .tbl-wrap', app: '.activity-runs > .tbl-wrap', checks: ['chrome', 'colour'], use: 'decorative', states: [], status: 'active' },
  { id: 'activity.th', surface: 'activity-panel', mock: '.panel .tbl-wrap thead th', app: '.activity-table thead th', checks: ['type', 'colour'], list: 'fixed', states: [], status: 'active' },
  { id: 'activity.run', surface: 'activity-panel', mock: '.panel tbody tr:first-child td:first-child b', app: '.activity-table tbody tr:first-child td:first-child b', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'activity.meta', surface: 'activity-panel', mock: '.panel tbody tr:first-child .src-m', app: '.activity-table tbody tr:first-child .src-m', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'activity.status', surface: 'activity-panel', mock: '.panel tbody .status.ok', app: '.activity-table .status.ok', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'activity.foot', surface: 'activity-panel', mock: '.panel .p-body > .foot-note', app: '.activity-runs > .foot-note', checks: ['type', 'colour'], states: [], status: 'active' },
  // S15a Evidence table (P21-P26): the head, the toolbar, the column heads, the first row and its first cell, the foot.
  // The column names and cell values are the fixture's, so the heads and cells compare type, colour and icon only.
  { id: 'table.title', surface: 'table-panel', mock: '.panel .p-head h2', app: '.split-panel-head h2', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'table', app: 'table-2' }, text: true, states: [], status: 'active' },
  { id: 'table.toolbar', surface: 'table-panel', mock: '.panel .p-body > .toolbar > button', app: '.table-panel > .toolbar > button', checks: ['chrome', 'type', 'colour', 'icon'], list: 'fixed',
    icon: [{ mock: 'plus', app: 'plus' }, { mock: 'bulb', app: 'lightbulb' }, { mock: 'doc', app: 'text-align-start' }, { mock: 'info', app: 'info' }, { mock: 'dl', app: 'download' }, { mock: 'more', app: 'ellipsis' }],
    states: [], status: 'active' },
  { id: 'table.col-head', surface: 'table-panel', mock: '.panel thead .th-b:not(.th-add)', app: '.evidence-grid thead .th-b.evidence-col-head', checks: ['type', 'colour', 'icon'], list: 'data', expected: () => 4,
    icon: { mock: 'doc', app: 'text-align-start' }, states: [], status: 'active' },
  { id: 'table.col-add', surface: 'table-panel', mock: '.panel thead .th-b.th-add', app: '.evidence-grid thead .th-b.th-add', checks: ['type', 'colour', 'icon'], text: true,
    icon: { mock: 'plus', app: 'plus' }, states: [], status: 'active' },
  { id: 'table.wrap', surface: 'table-panel', mock: '.panel .p-body > .tbl-wrap', app: '.table-panel > .tbl-wrap', checks: ['chrome', 'colour'], use: 'decorative', states: [], status: 'active' },
  { id: 'table.row-head', surface: 'table-panel', mock: '.panel tbody tr:first-child > td:first-child', app: '.evidence-grid tbody tr:first-child > th.evidence-row-head', checks: ['content'], states: [], status: 'active' },
  { id: 'table.cell-box', surface: 'table-panel', mock: '.panel tbody tr:first-child > td:nth-child(2)', app: '.evidence-grid tbody tr:first-child > td:nth-child(2)', checks: ['content'], states: [], status: 'active' },
  { id: 'table.source', surface: 'table-panel', mock: '.panel tbody tr:first-child .src-t', app: '.evidence-grid tbody tr:first-child .src-t', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'table.source-meta', surface: 'table-panel', mock: '.panel tbody tr:first-child .src-m', app: '.evidence-grid tbody tr:first-child .src-m', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'table.cell', surface: 'table-panel', mock: '.panel tbody tr:first-child .cell', app: '.evidence-grid tbody tr:first-child .cell', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'table.cell-note', surface: 'table-panel', mock: '.panel tbody tr:first-child .cell small', app: '.evidence-grid tbody tr:first-child .cell small', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'table.foot', surface: 'table-panel', mock: '.panel .p-body > p.foot-note', app: '.table-panel > .evidence-footnote', checks: ['type', 'colour'], text: true, states: [], status: 'active' },
  // S15a a cell's panel (P27): the value, how it was found, Recheck and the source, then Source, Passage, Column
  // instruction and History (COPY_CHANGES cell-history).
  { id: 'cell.title', surface: 'cell-panel', mock: '.panel .p-head h2', app: '.split-panel-head h2', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'table', app: 'table-2' }, states: [], status: 'active' },
  { id: 'cell.back', surface: 'cell-panel', mock: '.panel .p-head [data-act="back"]', app: '.split-panel-head [aria-label="Back"]', checks: ['chrome', 'colour', 'icon'],
    icon: { mock: 'left', app: 'chevron-left' }, unordered: true, states: [], status: 'active' },
  { id: 'cell.detail', surface: 'cell-panel', mock: '.panel .pad.detail', app: '.cell-detail', checks: ['content'], use: 'decorative', states: [], status: 'active' },
  { id: 'cell.dacts', surface: 'cell-panel', mock: '.detail .dacts', app: '.cell-detail .dacts', checks: ['content'], use: 'decorative', states: [], status: 'active' },
  { id: 'cell.venue', surface: 'cell-panel', mock: '.detail .dhead .venue', app: '.cell-detail .dhead .venue', checks: ['content', 'type', 'colour', 'icon'],
    icon: { mock: 'doc', app: 'text-align-start' }, states: [], status: 'active' },
  { id: 'cell.value', surface: 'cell-panel', mock: '.detail .dhead h1', app: '.cell-detail .dhead h1', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'cell.dmeta', surface: 'cell-panel', mock: '.detail .dmeta', app: '.cell-detail .dmeta', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'cell.recheck', surface: 'cell-panel', mock: '.detail .dacts .btn-pri', app: '.cell-detail .dacts .btn-pri', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'redo', app: 'rotate-cw' }, states: [], status: 'active' },
  // "Edit value" sits between Recheck and the source button (PLACEMENTS cell-live-parts), so the button is not placed by the mockup's x.
  { id: 'cell.open-source', surface: 'cell-panel', mock: '.detail .dacts .ib', app: '.cell-detail .dacts .ib', checks: ['colour', 'icon'],
    icon: { mock: 'file', app: 'file-text' }, unordered: true, states: [], status: 'active' },
  { id: 'cell.sub', surface: 'cell-panel', mock: '.detail h4.sub', app: '.cell-detail h4.sub', checks: ['content', 'type', 'colour'], list: 'fixed', dataText: { app: ['small'] }, states: [], status: 'active' },
  { id: 'cell.quote', surface: 'cell-panel', mock: '.detail .quote', app: '.cell-detail .quote', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'cell.loc', surface: 'cell-panel', mock: '.detail .loc', app: '.cell-detail .loc', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  // S15a the evidence report (P28-P30): the head with Evidence view, Review with another model and Download, the title,
  // the meta line and the check block at the end.
  { id: 'ereport.title', surface: 'ereport-panel', mock: '.panel .p-head h2', app: '.split-panel-head h2', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'doc', app: 'text-align-start' }, states: [], status: 'active' },
  { id: 'ereport.actions', surface: 'ereport-panel', mock: '.panel .p-head .ib:not([data-act="wide"]):not([data-act="close"])', app: '.split-panel-head .report-toolbar-actions .ib', checks: ['chrome', 'colour', 'icon'], list: 'fixed', text: false,
    icon: [{ mock: 'table', app: 'table-2' }, { mock: 'shield', app: 'shield-check' }, { mock: 'dl', app: 'download' }], unordered: true, states: [], status: 'active' },
  { id: 'ereport.document', surface: 'ereport-panel', mock: '.panel .report', app: '.erep-panel .evidence-report-document', checks: ['content'], use: 'decorative', states: [], status: 'active' },
  { id: 'ereport.h1', surface: 'ereport-panel', mock: '.report h1', app: '.evidence-report-document .report-document-head h1', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'ereport.meta', surface: 'ereport-panel', mock: '.report .meta', app: '.evidence-report-document .report-document-head .meta', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'ereport.check', surface: 'ereport-panel', mock: '.report .check', app: '.evidence-report-check', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  // S15a the Citation panel of the evidence report (P31): the frozen value, the stored passage, where its anchor stands.
  { id: 'ecite.title', surface: 'ecite-panel', mock: '.panel .p-head h2', app: '.split-panel-head h2', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'link', app: 'link' }, text: true, states: [], status: 'active' },
  { id: 'ecite.back', surface: 'ecite-panel', mock: '.panel .p-head [data-act="back"]', app: '.split-panel-head [aria-label="Back"]', checks: ['chrome', 'colour', 'icon'],
    icon: { mock: 'left', app: 'chevron-left' }, unordered: true, states: [], status: 'active' },
  { id: 'ecite.venue', surface: 'ecite-panel', mock: '.detail .dhead .venue', app: '.ecite-detail .dhead .venue', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'ecite.value', surface: 'ecite-panel', mock: '.detail .dhead h1', app: '.ecite-detail .dhead h1', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'ecite.sub', surface: 'ecite-panel', mock: '.detail h4.sub', app: '.ecite-detail h4.sub', checks: ['type', 'colour'], text: true, states: [], status: 'active' },
  { id: 'ecite.quote', surface: 'ecite-panel', mock: '.detail .quote', app: '.ecite-detail .quote', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'ecite.loc', surface: 'ecite-panel', mock: '.detail .loc', app: '.ecite-detail .loc', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'ecite.foot', surface: 'ecite-panel', mock: '.detail > p.foot-note', app: '.ecite-detail > p.foot-note', checks: ['type', 'colour'], text: true, states: [], status: 'active' },
  // S15b the Candidates list (P35): the head, the intro, Add candidate and the first card (its meta line and claim).
  { id: 'cands.title', surface: 'cands-panel', mock: '.panel .p-head h2', app: '.split-panel-head h2', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'bulb', app: 'lightbulb' }, text: true, states: [], status: 'active' },
  { id: 'cands.intro', surface: 'cands-panel', mock: '.panel .pad > p:first-child', app: '.candidates-list > p:first-child', checks: ['chrome', 'content', 'type', 'colour'], text: true, states: [], status: 'active' },
  { id: 'cands.add', surface: 'cands-panel', mock: '.panel .pad > .acts .ghost', app: '.candidates-list > .acts .ghost:first-child', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'plus', app: 'plus' }, text: true, states: [], status: 'active' },
  { id: 'cands.card', surface: 'cands-panel', mock: '.panel .ccard', app: '.candidate-list .ccard', checks: ['content', 'colour'], list: 'data', expected: () => 1, use: 'decorative', states: [], status: 'active' },
  { id: 'cands.card-meta', surface: 'cands-panel', mock: '.panel .ccard:first-of-type .meta', app: '.candidate-list li:first-child .ccard .meta', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'cands.card-claim', surface: 'cands-panel', mock: '.panel .ccard:first-of-type p', app: '.candidate-list li:first-child .ccard p', checks: ['type', 'colour'], states: [], status: 'active' },
  // S15b one candidate (P35): the head with Back, the venue and the sentence, the section heads, the card's element list,
  // the status line, the claim matrix and its relation cells.
  { id: 'cand.title', surface: 'cand-panel', mock: '.panel .p-head h2', app: '.split-panel-head h2', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'bulb', app: 'lightbulb' }, text: true, states: [], status: 'active' },
  { id: 'cand.back', surface: 'cand-panel', mock: '.panel .p-head [data-act="back"]', app: '.split-panel-head [aria-label="Back"]', checks: ['chrome', 'colour', 'icon'],
    icon: { mock: 'left', app: 'chevron-left' }, unordered: true, states: [], status: 'active' },
  { id: 'cand.detail', surface: 'cand-panel', mock: '.panel .pad.detail', app: '.candidate-detail', checks: ['content'], use: 'decorative', states: [], status: 'active' },
  { id: 'cand.venue', surface: 'cand-panel', mock: '.detail .dhead .venue', app: '.candidate-detail .dhead .venue', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'cand.sentence', surface: 'cand-panel', mock: '.detail .dhead .sentence', app: '.candidate-detail .dhead .sentence', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'cand.sub', surface: 'cand-panel', mock: '.detail > h4.sub', app: '.candidate-detail h4.sub', checks: ['content', 'type', 'colour'], list: 'fixed', text: false, states: [], status: 'active' },
  { id: 'cand.element', surface: 'cand-panel', mock: '.detail > .elist li:first-child', app: '.candidate-detail .candidate-version .elist li:first-child', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'cand.status', surface: 'cand-panel', mock: '.detail .cst', app: '.candidate-detail .candidate-status-line .cst:not(.yours)', checks: ['type', 'colour'], unordered: true, states: [], status: 'active' },
  { id: 'cand.matrix', surface: 'cand-panel', mock: '.detail .tbl-wrap', app: '.candidate-detail .candidate-matrix-wrap', checks: ['content', 'colour'], use: 'decorative', states: [], status: 'active' },
  { id: 'cand.matrix-th', surface: 'cand-panel', mock: '.detail table.mx thead th:first-child', app: '.candidate-detail table.mx thead th:first-child', checks: ['type', 'colour'], text: true, states: [], status: 'active' },
  { id: 'cand.work', surface: 'cand-panel', mock: '.detail table.mx tbody tr:first-child .src-t', app: '.candidate-detail table.mx tbody tr:first-child .src-t', checks: ['type', 'colour'], states: [], status: 'active' },
  // S15b a kept work's evidence (P36): the head, the frozen passage with its mark and the closing note with Open the source.
  { id: 'cev.title', surface: 'cev-panel', mock: '.panel .p-head h2', app: '.split-panel-head h2', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'bulb', app: 'file-search' }, text: true, states: [], status: 'active' },
  { id: 'cev.back', surface: 'cev-panel', mock: '.panel .p-head [data-act="back"]', app: '.split-panel-head [aria-label="Back"]', checks: ['chrome', 'colour', 'icon'],
    icon: { mock: 'left', app: 'chevron-left' }, unordered: true, states: [], status: 'active' },
  { id: 'cev.venue', surface: 'cev-panel', mock: '.detail .dhead .venue', app: '.candidate-evidence .dhead .venue', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'cev.h1', surface: 'cev-panel', mock: '.detail .dhead h1', app: '.candidate-evidence .dhead h1', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'cev.quote', surface: 'cev-panel', mock: '.detail .quote', app: '.candidate-evidence .quote', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'cev.mark', surface: 'cev-panel', mock: '.detail .quote mark', app: '.candidate-evidence .quote mark', checks: ['colour'], use: 'decorative', states: [], status: 'active' },
  { id: 'cev.foot', surface: 'cev-panel', mock: '.detail > p.foot-note:last-child', app: '.candidate-evidence > p.foot-note:last-child', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  // S15b the review request dialog after Preview (P32): the shared dialog chrome, the focus options, the note field, the
  // "What will be sent" box and the footer.
  { id: 'rvdlg.scrim', surface: 'review-dialog', mock: '.scrim', app: '.dialog-scrim', checks: ['chrome', 'colour'], use: 'decorative', unordered: true, status: 'active' },
  { id: 'rvdlg.dialog', surface: 'review-dialog', mock: '.pal.dlg', app: '.review-dialog', checks: ['content', 'colour'], use: 'decorative', unordered: true, status: 'active' },
  { id: 'rvdlg.head', surface: 'review-dialog', mock: '.pal.dlg .pal-in', app: '.review-dialog .dialog-head', checks: ['chrome', 'colour', 'icon'], use: 'decorative',
    icon: { mock: 'shield', app: 'shield-check' }, unordered: true, status: 'active' },
  { id: 'rvdlg.title', surface: 'review-dialog', mock: '.pal.dlg .pal-in b', app: '.review-dialog .dialog-title', checks: ['type'], text: true, unordered: true, status: 'active' },
  { id: 'rvdlg.close', surface: 'review-dialog', mock: '.pal.dlg .pal-in .ib', app: '.review-dialog .dialog-close', checks: ['chrome', 'icon'], icon: { mock: 'x', app: 'x' }, unordered: true, status: 'active' },
  { id: 'rvdlg.option', surface: 'review-dialog', mock: '.pal.dlg .opts label', app: '.review-dialog .opts label', checks: ['content', 'type', 'colour'], list: 'fixed', text: true, unordered: true, states: [], status: 'active' },
  // The note's text colour is the person's own text (--ink); the mockup's textarea inherits the label's muted colour.
  { id: 'rvdlg.note', surface: 'review-dialog', mock: '.pal.dlg #rvNote', app: '.review-dialog textarea.field', checks: ['content', 'type'], unordered: true, states: [], status: 'active' },
  { id: 'rvdlg.sendbox', surface: 'review-dialog', mock: '.pal.dlg .sendbox', app: '.review-dialog .sendbox', checks: ['content', 'colour'], use: 'decorative', unordered: true, states: [], status: 'active' },
  { id: 'rvdlg.sendbox-head', surface: 'review-dialog', mock: '.pal.dlg .sendbox > b', app: '.review-dialog .sendbox h3', checks: ['type', 'colour'], text: true, unordered: true, states: [], status: 'active' },
  { id: 'rvdlg.footer', surface: 'review-dialog', mock: '.pal.dlg .dlg-f', app: '.review-dialog .dialog-footer', checks: ['content', 'colour'], use: 'decorative', unordered: true, status: 'active' },
  { id: 'rvdlg.buttons', surface: 'review-dialog', mock: '.pal.dlg .dlg-f button', app: '.review-dialog .dialog-footer button', checks: ['chrome', 'type', 'colour'], list: 'fixed', text: true, unordered: true, states: [], status: 'active' },
  // S15b the review panel (P33): the head, the meta line, the first finding with its kind, its located quote and the
  // Accept / Dismiss / Defer row, and the closing summary line.
  { id: 'rvpanel.title', surface: 'review-panel', mock: '.panel .p-head h2', app: '.split-panel-head h2', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'shield', app: 'shield-check' }, text: true, states: [], status: 'active' },
  { id: 'rvpanel.back', surface: 'review-panel', mock: '.panel .p-head [data-act="back"]', app: '.split-panel-head [aria-label="Back"]', checks: ['chrome', 'colour', 'icon'],
    icon: { mock: 'left', app: 'chevron-left' }, unordered: true, states: [], status: 'active' },
  { id: 'rvpanel.dmeta', surface: 'review-panel', mock: '.detail > .dmeta', app: '.review-detail > .dmeta', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'rvpanel.finding', surface: 'review-panel', mock: '.detail .finding', app: '.review-detail .finding', checks: ['content', 'colour'], list: 'data', expected: () => 2, use: 'decorative', states: [], status: 'active' },
  { id: 'rvpanel.kind', surface: 'review-panel', mock: '.detail .finding:first-of-type header b', app: '.review-detail .finding:first-of-type header h4', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'rvpanel.quote', surface: 'review-panel', mock: '.detail .finding:first-of-type .quote', app: '.review-detail .finding:first-of-type .quote', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'rvpanel.loc', surface: 'review-panel', mock: '.detail .finding:first-of-type .loc', app: '.review-detail .finding:first-of-type .loc', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'rvpanel.acts', surface: 'review-panel', mock: '.detail .finding:first-of-type .acts .ghost', app: '.review-detail .finding:first-of-type .acts .ghost', checks: ['chrome', 'type', 'colour', 'icon'], list: 'fixed', text: true,
    icon: [{ mock: 'check', app: 'check' }, { mock: 'x', app: 'x' }], states: [], status: 'active' },
  { id: 'rvpanel.summary', surface: 'review-panel', mock: '.detail > p.foot-note:last-child', app: '.review-detail > p.foot-note.review-foot', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  // S15b the Follow-up panel (P37): the head, the intro, the search-queries box with its name, mode line and actions, the
  // records heading and the closing note.
  { id: 'watch.title', surface: 'watch-panel', mock: '.panel .p-head h2', app: '.split-panel-head h2', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'clock', app: 'clock' }, text: true, states: [], status: 'active' },
  { id: 'watch.intro', surface: 'watch-panel', mock: '.panel .pad > p:first-child', app: '.followup-view .followup-intro > p', checks: ['type', 'colour'], text: true, states: [], status: 'active' },
  { id: 'watch.box', surface: 'watch-panel', mock: '.panel .watch:first-of-type', app: '.followup-view .watch:first-of-type', checks: ['content', 'colour'], use: 'decorative', states: [], status: 'active' },
  { id: 'watch.name', surface: 'watch-panel', mock: '.panel .watch:first-of-type h4', app: '.followup-view .watch:first-of-type h4', checks: ['content', 'type', 'colour', 'icon'],
    icon: { mock: 'search', app: 'search' }, text: true, states: [], status: 'active' },
  { id: 'watch.mode', surface: 'watch-panel', mock: '.panel .watch:first-of-type > small:first-of-type', app: '.followup-view .watch:first-of-type > small:first-of-type', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'watch.acts', surface: 'watch-panel', mock: '.panel .watch:first-of-type > .acts:last-child .ghost', app: '.followup-view .watch:first-of-type > .acts:last-of-type .ghost', checks: ['chrome', 'type', 'colour'], list: 'fixed', text: true, states: [], status: 'active' },
  { id: 'watch.records', surface: 'watch-panel', mock: '.panel .pad > h3', app: '.followup-view > h3', checks: ['type', 'colour'], states: [], status: 'active' },
  // S15b the Schedule dialog (P38): the shared dialog chrome, the frequency choices and the footer.
  { id: 'sched.dialog', surface: 'schedule-dialog', mock: '.pal.dlg', app: '.followup-dialog', checks: ['content', 'colour'], use: 'decorative', unordered: true, status: 'active' },
  { id: 'sched.head', surface: 'schedule-dialog', mock: '.pal.dlg .pal-in', app: '.followup-dialog .dialog-head', checks: ['chrome', 'colour', 'icon'], use: 'decorative',
    icon: { mock: 'clock', app: 'clock' }, unordered: true, status: 'active' },
  { id: 'sched.title', surface: 'schedule-dialog', mock: '.pal.dlg .pal-in b', app: '.followup-dialog .dialog-title', checks: ['type'], text: true, unordered: true, status: 'active' },
  { id: 'sched.frequency', surface: 'schedule-dialog', mock: '.pal.dlg .fmts:has(input[name="wfreq"]) label', app: '.followup-dialog .fmts label', checks: ['type', 'colour'], list: 'fixed', text: true, unordered: true, states: [], status: 'active' },
  { id: 'sched.footer', surface: 'schedule-dialog', mock: '.pal.dlg .dlg-f', app: '.followup-dialog .dialog-footer', checks: ['content', 'colour'], use: 'decorative', unordered: true, status: 'active' },
  { id: 'sched.buttons', surface: 'schedule-dialog', mock: '.pal.dlg .dlg-f button', app: '.followup-dialog .dialog-footer button', checks: ['chrome', 'type', 'colour'], list: 'fixed', text: true, unordered: true, states: [], status: 'active' },
  // S23b the Search plan panel (P42): the head, the lede, the words and their chips, the add field, the stored query, the
  // criterion, the sources and the two buttons. The live parts the mockup has no place for (the stored plan's rule notice,
  // the block labels and the block choice, the notes under the queries, Crossref's note, the PDFs guiding the search) are
  // PLACEMENTS plan-live-parts; the rows below them are compared for x, width, type and colour, not y.
  { id: 'plan.title', surface: 'plan-panel', mock: '.panel .p-head h2', app: '.split-panel-head h2', checks: ['chrome', 'type', 'colour', 'icon'],
    icon: { mock: 'pen', app: 'pencil-line' }, text: true, states: [], status: 'active' },
  { id: 'plan.lede', surface: 'plan-panel', mock: '.panel .pad > p:first-child', app: '.plan-panel > p:first-child', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'plan.words', surface: 'plan-panel', mock: '.panel .pad > .lbl:has(.kw)', app: '.plan-panel > .lbl:has(.kw)', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'plan.chip', surface: 'plan-panel', mock: '.panel .kw span', app: '.plan-panel .kw > span', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'plan.chip-remove', surface: 'plan-panel', mock: '.panel .kw button', app: '.plan-panel .kw > span > button', checks: ['icon', 'colour'],
    icon: { mock: 'x', app: 'x' }, states: [], status: 'active' },
  { id: 'plan.add', surface: 'plan-panel', mock: '#addword', app: '.plan-panel .plan-add input.field', checks: ['chrome', 'type', 'colour'], states: [], status: 'active' },
  { id: 'plan.query', surface: 'plan-panel', mock: '#pq1', app: '.plan-panel textarea.field.mono', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'plan.criterion', surface: 'plan-panel', mock: '#pcrit', app: '.plan-panel textarea.field:not(.mono)', checks: ['content', 'type', 'colour'], states: [], status: 'active' },
  { id: 'plan.provider', surface: 'plan-panel', mock: '.panel .provs label', app: '.plan-panel .provs label', checks: ['content', 'type', 'colour'], list: 'data', expected: () => 4, states: [], status: 'active' },
  { id: 'plan.provider-note', surface: 'plan-panel', mock: '.panel .provs label small', app: '.plan-panel .provs label small', checks: ['type', 'colour'], states: [], status: 'active' },
  { id: 'plan.buttons', surface: 'plan-panel', mock: '.panel .rowbtns button', app: '.plan-panel .rowbtns button', checks: ['chrome', 'type', 'colour'], list: 'fixed', text: true, states: [], status: 'active' },
  { id: 'plan.search', surface: 'plan-panel', mock: '.panel .rowbtns .btn-teal', app: '.plan-panel .rowbtns .btn-teal', checks: ['type', 'colour', 'icon'], icon: { mock: 'search', app: 'search' }, states: [], status: 'active' },
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
