import { expect, request as apiRequest, test, type Browser, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { createServer } from 'node:net'
import { APP_EXCLUDE, MOCK_EXCLUDE, MOCKUP, PARITY_OUT, auditSelectors, checkBreakpoint, driveMockup, gateSurface, measure, openMockup, writePixelDiff, type FixtureContext } from './gates'
import { BREAKPOINT, PAIRS, SURFACES, THEMES, WIDTHS, pairsFor, pendingBySlice, type Surface, type Theme } from './parity-map'

// Parity check (D8, plan §4.1): the app on the fixture server against the mockup v24, per surface, at 1280 and 390,
// light and dark. Active pairs are checked; pending pairs (a later slice changes them) are counted and printed.
// Pixel diffs go to .local/parity/ as a review aid and never fail. The research is the fixture's SYNTHETIC [parity]
// research; a passing check shows layout, not model quality.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const QUESTION = '[parity] How has the relationship between k-connectivity, network lifetime and energy consumption been modeled in SYNTHETIC wireless sensor networks?'
const FOLLOWUP = '[fu-not] Which works report lifetime in rounds or hours for a fixed k?'
// The [parity] research reads full text, so retrieval and reading are on (tests/acceptance/fixture_server.py docstring).
const PARITY_ENV = { DEIXIS_FIXTURE_FULLTEXT: 'on' }

// A port nobody listens on: another session's fixture server on a shared port would otherwise answer the health check.
function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const probe = createServer()
    probe.once('error', reject)
    probe.listen(0, '127.0.0.1', () => {
      const address = probe.address()
      probe.close(() => (typeof address === 'object' && address ? resolve(address.port) : reject(new Error('no port'))))
    })
  })
}

class FixtureServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-parity-'))
  port = 0
  url() { return `http://127.0.0.1:${this.port}` }
  async start() {
    this.port = await freePort()
    const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend'), ...PARITY_ENV }
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      if (this.proc.exitCode !== null) throw new Error(`parity fixture server exited with ${this.proc.exitCode}`)
      try { if ((await fetch(`${this.url()}/api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`parity fixture server on ${this.port} did not start`)
  }
  async stop() {
    const proc = this.proc
    if (proc && proc.exitCode === null) {
      const exited = new Promise(resolve => proc.once('exit', resolve))
      proc.kill('SIGTERM')
      await exited
    }
    rmSync(this.dataDir, { recursive: true, force: true })
  }
}

const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
type View = { runs: Array<{ kind: string; status: string }>; sources: Array<{ source_version_id: string; version_role: string; selection: { state: string } }> }

/** Creates the [parity] research as the plan shapes it (§4.1): discovery and its answer, a second answer (V2), and a
 *  6 × 4 study table, the way the UI's own buttons would ask for them. */
async function parityResearch(base: string): Promise<string> {
  const api = await apiRequest.newContext({ baseURL: base, extraHTTPHeaders: { origin: base } })
  const token = (await (await api.get('/api/session')).json()).csrf_token as string
  const post = async (url: string, data: unknown, headers: Record<string, string> = {}) => {
    const response = await api.post(url, { data, headers: { 'x-deixis-csrf': token, ...headers } })
    expect(response.ok(), `${url}: ${await response.text()}`).toBe(true)
    return response.json()
  }
  const view = async (id: string) => (await (await api.get(`/api/researches/${id}`)).json()) as View
  // Settled: a run of each kind exists and none of the research's runs is active.
  const settle = (id: string, kinds: string[]) => expect.poll(async () => {
    const v = await view(id)
    return kinds.every(k => v.runs.some(r => r.kind === k)) && !v.runs.some(r => ACTIVE.has(r.status))
  }, { timeout: 110_000, intervals: [500] }).toBe(true)
  const id = (await post('/api/researches', { question: QUESTION, model_connection: 'codex', requested_model: 'fixture-model', effort: 'standard' })).research.id as string
  await post(`/api/researches/${id}/runs`, { kind: 'discovery' }, { 'Idempotency-Key': `parity-discovery-${id}` })
  await settle(id, ['discovery', 'answer'])
  await post(`/api/researches/${id}/runs`, { kind: 'answer' }, { 'Idempotency-Key': `parity-answer-2-${id}` })
  await new Promise(resolve => setTimeout(resolve, 300))
  await settle(id, ['answer'])
  const included = (await view(id)).sources.filter(s => s.version_role === 'record' && s.selection.state === 'included').map(s => s.source_version_id).slice(0, 6)
  let table = await post(`/api/researches/${id}/tables`, { title: 'SYNTHETIC study table', rows: included })
  const path = `/api/researches/${id}/tables/${table.table.id}`
  for (const name of ['Network model', 'k', 'Lifetime definition', 'Energy model']) {
    table = await post(`${path}/columns`, { name, instruction: `State the ${name.toLowerCase()} the source uses.`, answer_format: 'text', expected_version: table.table.version })
  }
  await post(`${path}/fill`, { expected_version: table.table.version })
  await new Promise(resolve => setTimeout(resolve, 300))
  await settle(id, ['answer'])
  // S22b: one follow-up question, as the composer sends it; the fixture's model says its passages do not answer it
  // ("[fu-not]"), as the mockup's "rounds" turn does.
  const revision = ((await (await api.get(`/api/researches/${id}`)).json()) as { research: { current_scope_revision: number } }).research.current_scope_revision
  await post(`/api/researches/${id}/followup-turns`, { question: FOLLOWUP, expected_scope_revision: revision }, { 'Idempotency-Key': `parity-followup-${id}` })
  await new Promise(resolve => setTimeout(resolve, 300))
  await settle(id, ['followup_answer'])
  await api.dispose()
  return id
}

/** S15a: a second SYNTHETIC research whose evidence table holds every included source, filled, with one evidence report
 *  written from it (a report needs every included row filled). The bisection work is included so the table has the
 *  fixture's two works. */
async function reportResearch(base: string): Promise<string> {
  const api = await apiRequest.newContext({ baseURL: base, extraHTTPHeaders: { origin: base } })
  const token = (await (await api.get('/api/session')).json()).csrf_token as string
  const headers = (extra: Record<string, string> = {}) => ({ 'x-deixis-csrf': token, ...extra })
  const post = async (url: string, data: unknown, extra: Record<string, string> = {}) => {
    const response = await api.post(url, { data, headers: headers(extra) })
    expect(response.ok(), `${url}: ${await response.text()}`).toBe(true)
    return response.json()
  }
  type Source = { source_version_id: string; version_role: string; title: string; selection: { state: string; version: number } }
  const view = async (id: string) => (await (await api.get(`/api/researches/${id}`)).json()) as Omit<View, 'sources'> & { sources: Source[] }
  const settle = (id: string, kind: string) => expect.poll(async () => {
    const v = await view(id)
    return v.runs.some(r => r.kind === kind) && !v.runs.some(r => ACTIVE.has(r.status))
  }, { timeout: 110_000, intervals: [500] }).toBe(true)
  const id = (await post('/api/researches', { question: 'SYNTHETIC: How are molecule release schedules compared?', model_connection: 'codex', requested_model: 'fixture-model', effort: 'standard' })).research.id as string
  await post(`/api/researches/${id}/runs`, { kind: 'discovery' }, { 'Idempotency-Key': `parity-report-discovery-${id}` })
  await settle(id, 'discovery')
  const bisection = (await view(id)).sources.find(s => s.version_role === 'record' && s.title.includes('bisection'))
  if (bisection && bisection.selection.state !== 'included') {
    const response = await api.patch(`/api/researches/${id}/selections/${bisection.source_version_id}`, { data: { state: 'included', expected_version: bisection.selection.version }, headers: headers() })
    expect(response.ok(), await response.text()).toBe(true)
  }
  const rows = (await view(id)).sources.filter(s => s.version_role === 'record' && s.selection.state === 'included').map(s => s.source_version_id)
  let table = await post(`/api/researches/${id}/tables`, { title: 'SYNTHETIC study table', rows })
  const path = `/api/researches/${id}/tables/${table.table.id}`
  table = await post(`${path}/columns`, { name: 'SYNTHETIC method', instruction: 'State the synthetic method the source uses.', answer_format: 'text', expected_version: table.table.version })
  await post(`${path}/fill`, { expected_version: table.table.version }, { 'Idempotency-Key': `parity-report-fill-${id}` })
  await new Promise(resolve => setTimeout(resolve, 300))
  await settle(id, 'table_fill')
  await post(`/api/researches/${id}/reports`, { table_id: table.table.id }, { 'Idempotency-Key': `parity-report-${id}` })
  await new Promise(resolve => setTimeout(resolve, 300))
  await settle(id, 'report')
  await api.dispose()
  return id
}

/** S15b: a third SYNTHETIC research for the Candidates, review and Follow-up panels. Its question carries the fixture's
 *  "[candidate]" and "[review-finding]" markers: one candidate sentence broken into a card and searched, one review of
 *  that candidate version by another model (a finding with a located quote), and one manual follow-up of the search
 *  queries. Each step goes through the API the UI's own buttons call. */
async function candidateResearch(base: string): Promise<string> {
  const api = await apiRequest.newContext({ baseURL: base, extraHTTPHeaders: { origin: base } })
  const token = (await (await api.get('/api/session')).json()).csrf_token as string
  const headers = (key = true) => ({ 'x-deixis-csrf': token, ...(key ? { 'Idempotency-Key': crypto.randomUUID() } : {}) })
  const post = async (url: string, data?: unknown, key = true) => {
    const response = await api.post(url, { ...(data === undefined ? {} : { data }), headers: headers(key) })
    expect(response.ok(), `${url}: ${await response.text()}`).toBe(true)
    return response.json()
  }
  const get = async (url: string) => (await api.get(url)).json()
  const settle = (id: string, kind: string) => expect.poll(async () => {
    const v = (await get(`/api/researches/${id}`)) as View
    return v.runs.some(r => r.kind === kind) && !v.runs.some(r => ACTIVE.has(r.status))
  }, { timeout: 110_000, intervals: [500] }).toBe(true)
  const id = (await post('/api/researches', { question: 'SYNTHETIC bounded scheduling [candidate] [review-finding]', model_connection: 'codex', requested_model: 'fixture-model', effort: 'standard' }, false)).research.id as string
  await post(`/api/researches/${id}/runs`, { kind: 'discovery' })
  await settle(id, 'discovery')
  const base_ = `/api/researches/${id}/candidates`
  const cid = (await post(base_, { origin: 'owner_text', text: 'SYNTHETIC bounded scheduling reduces delay under bounded arrivals.' })).id as string
  await post(`${base_}/${cid}/decompose`)
  await settle(id, 'claim_decomposition')
  const plan = await get(`${base_}/${cid}/kill-search/plan`)
  await post(`${base_}/${cid}/kill-search`, { preview_fingerprint: plan.preview_fingerprint })
  await settle(id, 'kill_search')
  const vid = (await get(`${base_}/${cid}`)).current_version_id as string
  const connections = await get('/api/connections')
  const model = connections.models.codex.models[0]
  const request = { target_kind: 'candidate', target_id: vid, focus: 'source_support', owner_note: null, connection: 'codex', model: model.id, reasoning_effort: model.default_reasoning_effort ?? null }
  const shown = await post(`/api/researches/${id}/reviews/preview`, request, false)
  await post(`/api/researches/${id}/reviews`, { ...request, snapshot_sha256: shown.snapshot_sha256, preview_fingerprint: shown.preview_fingerprint })
  await expect.poll(async () => ((await get(`/api/researches/${id}/reviews?target_kind=candidate&target_id=${vid}`)) as Array<{ state: string }>)[0]?.state, { timeout: 110_000, intervals: [500] }).toBe('completed')
  await post(`/api/researches/${id}/watches/preview`, { kind: 'protocol_queries' }, false)
  const scope = ((await get(`/api/researches/${id}`)) as { research: { current_scope_revision: number } }).research.current_scope_revision
  await post(`/api/researches/${id}/watches`, { mode: 'manual', interval_days: null, catch_up: null, kind: 'protocol_queries', expected_scope_revision: scope })
  await new Promise(resolve => setTimeout(resolve, 300))
  await expect.poll(async () => !((await get(`/api/researches/${id}`)) as View).runs.some(r => ACTIVE.has(r.status)), { timeout: 110_000, intervals: [500] }).toBe(true)
  await api.dispose()
  return id
}

async function pagesFor(browser: Browser, width: number, theme: Theme) {
  const size = { width, height: width < 768 ? 844 : 900 }
  const mockContext = await browser.newContext({ viewport: size, colorScheme: theme })
  const appContext = await browser.newContext({ viewport: size, colorScheme: theme })
  const scratchContext = await browser.newContext({ viewport: { width: 800, height: 600 } })
  const [mock, app, scratch] = await Promise.all([mockContext.newPage(), appContext.newPage(), scratchContext.newPage()])
  await openMockup(mock)
  return { mock, app, scratch, close: () => Promise.all([mockContext.close(), appContext.close(), scratchContext.close()]) }
}

// The mockup's normal state has background work in the sidebar foot ("In the background · N"). The app shows the same
// card from one SYNTHETIC equation-reader read: the reader installed, one library PDF being read and two waiting. Only
// this read is answered here; everything else comes from the fixture server.
const READER = {
  installed: true, package: 'marker-pdf', path: '', size_bytes: 0, models_downloaded: true, disk_free_gb: 100,
  install: { available: true, unavailable_reason: null, url: '' }, job: null,
  reading: { asset_id: 'ast_parity', title: 'SYNTHETIC library PDF', pages: 12, started_at: new Date().toISOString() },
  pdfs: { read: 4, reading: 1, pending: 2 },
}

// The dialog surface opens the equation reader's Install confirm, so there the reader is SYNTHETIC and not installed.
const READER_OFF = { ...READER, installed: false, models_downloaded: false, reading: null, pdfs: {} }

async function showApp(page: Page, base: string, surface: Surface, research: string, report: string, cand: string) {
  await surface.prepare?.(page)
  await page.route('**/api/equation-reader', route => route.fulfill({ json: surface.reader === 'not-installed' ? READER_OFF : READER }))
  // The mockup always has a current research; the app's "Current research" names the one opened last in this browser,
  // so the [parity] research is opened first.
  await page.goto(`${base}/#/research/${research}`)
  await page.locator('.research-topbar').first().waitFor()
  await page.goto(`${base}/${surface.app.replace('{research}', research).replace('{report}', report).replace('{cand}', cand)}`)
  await surface.open?.(page)
  await page.locator(surface.ready).first().waitFor()
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(300)  // let entrance transitions settle before measuring
  if (surface.appAct) {
    await surface.appAct(page)
    await page.mouse.move(0, 0)
    await page.waitForTimeout(300)
  }
}

type AnswerView = { status: string; created_at: string; applicability: string; source_text_changed: boolean; unanswered_aspects?: string[] }

/** The fixture facts data lists count from. `library` is the number of works /api/library lists (S25). Suggestions follow S5a's rule (Q4): from each research only its latest
 *  structurally valid answer, and only while it is current (same question and source selection, no source text
 *  changed); at most two in all. */
async function fixtureContext(base: string): Promise<FixtureContext> {
  const api = await apiRequest.newContext({ baseURL: base, extraHTTPHeaders: { origin: base } })
  try {
    const list = (await (await api.get('/api/researches')).json()) as Array<{ id: string }> | { researches: Array<{ id: string }> }
    const researches = Array.isArray(list) ? list : list.researches
    let suggestions = 0
    for (const r of researches) {
      const view = (await (await api.get(`/api/researches/${r.id}`)).json()) as { answers: AnswerView[] }
      const latest = view.answers.filter(a => a.status === 'structurally_valid').sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
      if (latest && latest.applicability === 'current' && !latest.source_text_changed) suggestions += (latest.unanswered_aspects ?? []).length
    }
    const library = ((await (await api.get('/api/library')).json()) as { entries: unknown[] }).entries.length
    return { researches: researches.length, suggestions: Math.min(2, suggestions), library }
  } finally {
    await api.dispose()
  }
}

test.describe('parity: app against the mockup v24', () => {
  // Not serial: one failing variant must not hide the others. A failure restarts the worker, which builds its own
  // server and research again.
  const server = new FixtureServer()
  let research = ''
  let report = ''
  let cand = ''
  let ctx: FixtureContext = { researches: 0, suggestions: 0, library: 0 }

  test.beforeAll(async () => {
    test.setTimeout(300_000)
    await server.start()
    research = await parityResearch(server.url())
    report = await reportResearch(server.url())
    cand = await candidateResearch(server.url())
    ctx = await fixtureContext(server.url())
    const pending = pendingBySlice()
    const total = Object.values(pending).reduce((a, b) => a + b, 0)
    const active = PAIRS.filter(p => p.status === 'active').length
    console.log(`parity: mockup ${MOCKUP}; diffs in ${PARITY_OUT}`)
    console.log(`parity: ${active} active pairs, ${total} pending: ${Object.entries(pending).map(([s, n]) => `${s} ${n}`).join(', ')}`)
  })
  test.afterAll(async () => { await server.stop() })

  for (const surface of SURFACES) {
    for (const width of surface.widths ?? WIDTHS) {
      for (const theme of THEMES) {
        test(`${surface.id} at ${width}, ${theme}`, async ({ browser }, info) => {
          const pages = await pagesFor(browser, width, theme)
          try {
            await driveMockup(pages.mock, surface.mock)
            // The mockup's job and run simulations re-render the sidebar every few seconds; the state is set, so its timers stop.
            await pages.mock.evaluate(() => { const last = window.setTimeout(() => {}, 0); for (let id = 1; id <= last; id++) { clearTimeout(id); clearInterval(id) } })
            if (surface.mockAct) { await pages.mock.evaluate(surface.mockAct); await pages.mock.waitForTimeout(300) }
            await showApp(pages.app, server.url(), surface, research, report, cand)
            const pairs = pairsFor(surface.id, width)
            const failures = await gateSurface(pairs, { width, theme }, pages.mock, pages.app, ctx)
            await auditSelectors(pages.mock, pages.app, surface.id, { width, theme })
            info.annotations.push({ type: 'parity', description: `${pairs.length} active pairs checked` })
            const diff = await writePixelDiff(pages.mock, pages.app, pages.scratch, `${surface.id}-${width}-${theme}`)
            info.annotations.push({ type: 'pixel-diff', description: diff })
            expect(failures, `${surface.id} ${width} ${theme}:\n${failures.join('\n')}`).toEqual([])
          } finally {
            await surface.appUndo?.(pages.app).catch(() => {})
            await pages.close()
          }
        })
      }
    }
  }

  test(`breakpoint ${BREAKPOINT}: rail, Library third pane, panel and thread widths`, async ({ browser }) => {
    const failures: string[] = []
    for (const surface of SURFACES) {
      const pairs = PAIRS.filter(p => p.surface === surface.id && p.breakpoint && p.status === 'active')
      if (!pairs.length) continue
      const pages = await pagesFor(browser, BREAKPOINT, 'light')
      try {
        await driveMockup(pages.mock, surface.mock)
        await showApp(pages.app, server.url(), surface, research, report, cand)
        for (const pair of pairs) {
          failures.push(...checkBreakpoint(pair, { mock: await measure(pages.mock, pair.mock, MOCK_EXCLUDE, []), app: await measure(pages.app, pair.app, APP_EXCLUDE, []) }))
        }
      } finally {
        await pages.close()
      }
    }
    expect(failures, failures.join('\n')).toEqual([])
  })

  // openMockup throws when the file is missing (DEIXIS_PARITY_MOCKUP or the main checkout's .local), so this fails, never skips.
  test('the mockup loads with its own state globals', async ({ browser }) => {
    const context = await browser.newContext()
    try {
      const page = await context.newPage()
      await openMockup(page)
      expect(await page.evaluate('[setScenario, go, openPanel, menu].every(f => typeof f === "function")')).toBe(true)
    } finally {
      await context.close()
    }
  })
})
