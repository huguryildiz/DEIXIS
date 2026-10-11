import { expect, request as apiRequest, test, type Browser, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { createServer } from 'node:net'
import { COLOUR_EXCEPTIONS } from './exceptions'
import {
  APP_EXCLUDE, MOCK_EXCLUDE, MOCKUP, PARITY_OUT, checkBreakpoint, checkChrome, checkColour, checkContent, checkContrast,
  checkIcon, checkIconBox, checkOrder, checkPresence, checkType, driveMockup, exceptionFor, hovered, measure, openMockup,
  writePixelDiff, type Side,
} from './gates'
import { BREAKPOINT, PAIRS, SURFACES, THEMES, WIDTHS, pairsFor, pendingBySlice, type Surface, type Theme } from './parity-map'

// Parity check (D8, plan §4.1): the app on the fixture server against the mockup v24, per surface, at 1280 and 390,
// light and dark. Active pairs are checked; pending pairs (a later slice changes them) are counted and printed.
// Pixel diffs go to .local/parity/ as a review aid and never fail. The research is the fixture's SYNTHETIC [parity]
// research; a passing check shows layout, not model quality.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const QUESTION = '[parity] How has the relationship between k-connectivity, network lifetime and energy consumption been modeled in SYNTHETIC wireless sensor networks?'
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

async function showApp(page: Page, base: string, surface: Surface, research: string) {
  await page.goto(`${base}/${surface.app.replace('{research}', research)}`)
  await page.locator(surface.ready).first().waitFor()
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(300)  // let entrance transitions settle before measuring
}

const PROBE = [...new Set(COLOUR_EXCEPTIONS.flatMap(e => e.selectors))]

/** Every gate of §4.1 for one surface and variant. Returns failure lines. */
async function gate(surface: Surface, width: number, theme: Theme, mock: Page, app: Page): Promise<{ failures: string[]; checked: number }> {
  const pairs = pairsFor(surface.id, width)
  const failures: string[] = []
  const measured = new Map<string, Side>()
  for (const pair of pairs) {
    const side: Side = { mock: await measure(mock, pair.mock, MOCK_EXCLUDE, PROBE), app: await measure(app, pair.app, APP_EXCLUDE, []) }
    measured.set(pair.id, side)
    const presence = checkPresence(pair, side)
    failures.push(...presence)
    if (presence.length) continue
    if (pair.checks.includes('chrome')) failures.push(...checkChrome(pair, side))
    if (pair.checks.includes('content')) failures.push(...checkContent(pair, side))
    if (pair.checks.includes('type')) failures.push(...checkType(pair, side))
    if (pair.checks.includes('colour')) {
      failures.push(...checkColour(pair, side, { width, theme }))
      // A declared exception's contrast is also checked in the hover state (§4.1).
      const exception = side.mock && exceptionFor(pair, 'color', theme, side.mock)
      if (exception?.states.includes('hover')) {
        const hover = await hovered(app, pair.app, APP_EXCLUDE, [])
        if (hover) failures.push(...checkContrast(pair.id, exception.use, hover, `${theme} ${width} hover`))
      }
    }
    if (pair.checks.includes('icon')) failures.push(...checkIcon(pair, side), ...await checkIconBox(pair, mock, app))
  }
  failures.push(...checkOrder(pairs, measured))
  return { failures, checked: pairs.length }
}

test.describe('parity: app against the mockup v24', () => {
  // Not serial: one failing variant must not hide the others. A failure restarts the worker, which builds its own
  // server and research again.
  const server = new FixtureServer()
  let research = ''

  test.beforeAll(async () => {
    test.setTimeout(180_000)
    await server.start()
    research = await parityResearch(server.url())
    const pending = pendingBySlice()
    const total = Object.values(pending).reduce((a, b) => a + b, 0)
    const active = PAIRS.filter(p => p.status === 'active').length
    console.log(`parity: mockup ${MOCKUP}; diffs in ${PARITY_OUT}`)
    console.log(`parity: ${active} active pairs, ${total} pending: ${Object.entries(pending).map(([s, n]) => `${s} ${n}`).join(', ')}`)
  })
  test.afterAll(async () => { await server.stop() })

  for (const surface of SURFACES) {
    for (const width of WIDTHS) {
      for (const theme of THEMES) {
        test(`${surface.id} at ${width}, ${theme}`, async ({ browser }, info) => {
          const pages = await pagesFor(browser, width, theme)
          try {
            await driveMockup(pages.mock, surface.mock)
            await showApp(pages.app, server.url(), surface, research)
            const { failures, checked } = await gate(surface, width, theme, pages.mock, pages.app)
            info.annotations.push({ type: 'parity', description: `${checked} active pairs checked` })
            const diff = await writePixelDiff(pages.mock, pages.app, pages.scratch, `${surface.id}-${width}-${theme}`)
            info.annotations.push({ type: 'pixel-diff', description: diff })
            expect(failures, `${surface.id} ${width} ${theme}:\n${failures.join('\n')}`).toEqual([])
          } finally {
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
        await showApp(pages.app, server.url(), surface, research)
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
