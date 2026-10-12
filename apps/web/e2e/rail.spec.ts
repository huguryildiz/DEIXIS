import { expect, request as apiRequest, test, type APIRequestContext, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'
import { PANEL_TITLES, panel, reportPanel, type PanelName } from './panels'

// UI parity S11: the artifacts rail (mockup `rail()`, RL1-RL7). Boxes in the mockup's order with counts from the view,
// each box opening the panel stack, the rail gone while a panel is open and under 1100px, and, below 1100px, the ⋯ menu
// keeping the four panel rows the rail opens above it (plan §0 rule 5).
//
// Its own fixture server with full-text reading on, so the [parity] research reads full texts as the mockup's does.
// Every record is SYNTHETIC; a passing case shows how the page behaves, not the quality of a search or an answer.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

const PARITY = '[parity] How has the relationship between k-connectivity, network lifetime and energy consumption been modeled in SYNTHETIC wireless sensor networks?'

class RailServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-rail-'))
  constructor(readonly port: number) {}
  async start() {
    const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend'), DEIXIS_FIXTURE_FULLTEXT: 'on' }
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`http://127.0.0.1:${this.port}/api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`rail fixture server on ${this.port} did not start`)
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
  url() { return `http://127.0.0.1:${this.port}` }
}

type Api = { context: APIRequestContext; token: string }
type Step = { kind: string; status: string; operation_key: string }
type View = {
  research: { current_scope_revision: number }
  runs: Array<{ id: string; kind: string; status: string; scope_revision: number; steps?: Step[] }>
  counts: { queue?: number; look_again?: number; waiting_for_pdf?: number; cited: number; funnel?: { unique: number; abstracts_read: number; candidates: number } | null }
  answers: Array<{ id: string; status: string }>
  sources: Array<{ version_role: string; selection: { state: string }; has_pdf_text: boolean; answer_reads_version_id: string | null; source_version_id: string; access: { abstract_passage_id: string | null } }>
}
const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
const post = (api: Api, url: string, data: unknown, headers: Record<string, string> = {}) => api.context.post(url, { data, headers: { 'x-deixis-csrf': api.token, ...headers } })
const viewOf = async (api: Api, rid: string) => (await (await api.context.get(`/api/researches/${rid}`)).json()) as View
const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`), animations: 'disabled' })
const rail = (page: Page) => page.getByRole('complementary', { name: /^Artifacts/ })
const box = (page: Page, title: string) => page.locator('.rail .box').filter({ has: page.locator('h5', { hasText: title }) })

// The same rule the rail uses for "Full text read": a work counts once both its full-text passes stored a result.
function fullTextRead(view: View) {
  const passes = new Map<string, number>()
  for (const run of view.runs) {
    if (run.scope_revision !== view.research.current_scope_revision) continue
    for (const step of run.steps ?? []) {
      if (step.kind !== 'model:fulltext_adjudication') continue
      const work = step.operation_key.replace(/^fulltext_adjudication:/, '').replace(/:[^:]*$/, '')
      passes.set(work, (passes.get(work) ?? 0) + (step.status === 'succeeded' ? 1 : 0))
    }
  }
  return [...passes.values()].filter(n => n >= 2).length
}

test.describe.serial('S11: the artifacts rail', () => {
  test.setTimeout(240_000)
  const server = new RailServer(nextPort())
  let api: Api
  let rid = ''
  let page: Page
  const research = () => `${server.url()}/#/research/${rid}`

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(240_000)
    await server.start()
    const context = await apiRequest.newContext({ baseURL: server.url(), extraHTTPHeaders: { origin: server.url() } })
    api = { context, token: (await (await context.get('/api/session')).json()).csrf_token as string }
    const settle = (kinds: string[]) => expect.poll(async () => {
      const view = await viewOf(api, rid)
      return kinds.every(k => view.runs.some(r => r.kind === k)) && !view.runs.some(r => ACTIVE.has(r.status))
    }, { timeout: 110_000, intervals: [500] }).toBe(true)
    const created = await post(api, '/api/researches', { question: PARITY, model_connection: 'codex', requested_model: 'fixture-model', effort: 'standard' })
    expect(created.status()).toBe(201)
    rid = (await created.json()).research.id
    expect((await post(api, `/api/researches/${rid}/runs`, { kind: 'discovery' }, { 'Idempotency-Key': `rail-discovery-${rid}` })).ok()).toBe(true)
    await settle(['discovery', 'answer'])
    // A second answer (V2), so there is an older report version, and a table of included sources with four columns.
    expect((await post(api, `/api/researches/${rid}/runs`, { kind: 'answer' }, { 'Idempotency-Key': `rail-answer-2-${rid}` })).ok()).toBe(true)
    await new Promise(resolve => setTimeout(resolve, 300))
    await settle(['answer'])
    const included = (await viewOf(api, rid)).sources.filter(s => s.version_role === 'record' && s.selection.state === 'included').map(s => s.source_version_id).slice(0, 6)
    const made = await (await post(api, `/api/researches/${rid}/tables`, { title: 'SYNTHETIC study table', rows: included })).json()
    let version = made.table.version as number
    for (const name of ['Network model', 'k', 'Lifetime definition', 'Energy model']) {
      const column = await (await post(api, `/api/researches/${rid}/tables/${made.table.id}/columns`, { name, instruction: `State the ${name.toLowerCase()} the source uses.`, answer_format: 'text', expected_version: version })).json()
      version = column.table.version
    }
    page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  })
  test.afterAll(async () => { await page?.close(); await api?.context.dispose(); await server.stop() })

  test('the rail lists the boxes in the mockup order, each number from the research’s own records', async () => {
    const view = await viewOf(api, rid)
    await page.goto(research())
    const aside = rail(page)
    await expect(aside).toBeVisible()
    const reports = view.answers.filter(a => a.status === 'structurally_valid').length
    // Artifacts (n): every report version, the table, no evidence report; the rows read as the mockup's.
    await expect(aside.locator('h5').first()).toHaveText(`Artifacts (${reports + 1})`)
    await expect(aside.getByRole('button', { name: /^Evidence table · 6 sources · 4 columns/ })).toBeVisible()
    await expect(aside.locator('button.li').filter({ hasText: /V\d+$/ })).toHaveCount(reports)
    // The amber box: one row per queue row, with what each asks; the queue's size is the topbar chip's too.
    const waiting = (view.counts.queue ?? 0) + (view.counts.look_again ?? 0)
    expect(waiting).toBeGreaterThan(0)
    const amber = box(page, 'Waiting for your decision')
    await expect(amber).toHaveClass(/warnbox/)
    await expect(amber.locator('button.li')).toHaveCount(Math.min(waiting, 8))
    await expect(amber.locator('button.li em').first()).toHaveText(/\S/)
    // The funnel: the mockup's five bars, "Read in full" under its §2.3 name, every number a stored count.
    const funnel = view.counts.funnel!
    await expect(box(page, 'From search to answer').locator('.fun button span:first-child')).toHaveText(['Found', 'Abstract read', 'Passed the abstract stage', 'Full text read', 'Cited'])
    await expect(box(page, 'From search to answer').locator('.fun button b')).toHaveText([funnel.unique, funnel.abstracts_read, funnel.candidates, fullTextRead(view), view.counts.cited].map(n => n.toLocaleString()))
    // Depth: PDF text and abstract only, over the included sources an answer reads.
    let pdf = 0
    let abstract = 0
    for (const s of view.sources.filter(s => s.version_role === 'record' && s.selection.state === 'included')) {
      const read = s.answer_reads_version_id ? view.sources.find(o => o.source_version_id === s.answer_reads_version_id) ?? s : s
      if (read.has_pdf_text) pdf++
      else if (read.access.abstract_passage_id) abstract++
    }
    const depth = box(page, 'How deeply sources were read')
    await expect(depth.locator('.legend')).toContainText(`PDF text ${pdf}`)
    await expect(depth.locator('.legend')).toContainText(`Abstract only ${abstract}`)
    // Run: Activity with its run count, Candidates, Follow-up. Usage is not here (RL8 is S27's).
    await expect(box(page, 'Run').locator('button.li').first()).toContainText(`${view.runs.length} runs`)
    await expect(box(page, 'Run').locator('button.li span')).toHaveText(['Activity', 'Candidates', 'Follow-up'])
    await expect(page.locator('.rail .box h5')).toHaveText([`Artifacts (${reports + 1})`, 'Waiting for your decisionOpen', 'From search to answerOpen', 'How deeply sources were readOpen', 'Run'])
    await shot(page, 's11-rail')
  })

  test('every box opens its panel; the rail is gone while a panel is open and returns with focus on the box', async () => {
    await page.goto(research())
    await expect(rail(page)).toBeVisible()
    const cases: [string, () => ReturnType<Page['locator']>, string | RegExp][] = [
      ['Activity', () => rail(page).getByRole('button', { name: /^Activity/ }), PANEL_TITLES.activity],
      ['Candidates', () => rail(page).getByRole('button', { name: /^Candidates/ }), PANEL_TITLES.cands],
      ['Follow-up', () => rail(page).getByRole('button', { name: /^Follow-up/ }), PANEL_TITLES.watch],
      ['queue', () => rail(page).getByRole('button', { name: 'Open Waiting for your decision' }), PANEL_TITLES.queue],
      ['the funnel', () => rail(page).getByRole('button', { name: 'Open From search to answer' }), 'Sources'],
      ['a funnel bar', () => rail(page).locator('.fun button').first(), 'Sources'],
      ['depth', () => rail(page).getByRole('button', { name: 'Open How deeply sources were read' }), 'Get more full text'],
      ['the table', () => rail(page).getByRole('button', { name: /^Evidence table · / }), 'Evidence table'],
    ]
    for (const [name, button, title] of cases) {
      const opener = button()
      await opener.click()
      await expect(panel(page, title), `${name} opens its panel`).toBeVisible()
      await expect(rail(page), `${name}: the rail is hidden while the panel is open`).toBeHidden()
      await page.keyboard.press('Escape')
      await expect(page.locator('[data-split-panel]')).toHaveCount(0)
      await expect(rail(page)).toBeVisible()
      await expect(opener, `${name}: focus returns to the box`).toBeFocused()
    }
    // A report version opens the report panel.
    await rail(page).locator('button.li').filter({ hasText: /V\d+$/ }).first().click()
    await expect(reportPanel(page)).toBeVisible()
    await expect(rail(page)).toBeHidden()
  })

  test('under 1100px the rail is gone and the ⋯ menu reaches the four panels; from 1100px it does not list them', async () => {
    await page.goto(research())
    if (await page.locator('[data-split-panel]').count()) await page.keyboard.press('Escape')
    await expect(page.locator('[data-split-panel]')).toHaveCount(0)
    await page.setViewportSize({ width: 1100, height: 900 })
    await expect(rail(page)).toBeVisible()
    await page.getByRole('button', { name: 'Research actions' }).click()
    for (const row of [/^Sources\b/, /^Awaiting your decision\b/, /^Get more full text\b/, /^Evidence table\b/]) await expect(page.getByRole('menuitem', { name: row })).toHaveCount(0)
    await expect(page.getByRole('menuitem', { name: /^Activity\b/ })).toBeVisible()
    await page.keyboard.press('Escape')
    await page.setViewportSize({ width: 1099, height: 900 })
    await expect(rail(page)).toBeHidden()
    const rows: Array<[PanelName, RegExp]> = [['sources', /^Sources\b/], ['queue', /^Awaiting your decision\b/], ['pdfs', /^Get more full text\b/], ['table', /^Evidence table\b/]]
    for (const [name, row] of rows) {
      await page.getByRole('button', { name: 'Research actions' }).click()
      await page.getByRole('menuitem', { name: row }).click()
      await expect(panel(page, PANEL_TITLES[name])).toBeVisible()
      await page.keyboard.press('Escape')
      await expect(page.locator('[data-split-panel]')).toHaveCount(0)
    }
    // The older report version has its row too, since the rail was the only list of them.
    await page.getByRole('button', { name: 'Research actions' }).click()
    await page.getByRole('menuitem', { name: /^Report · V1\b/ }).click()
    await expect(reportPanel(page)).toBeVisible()
    await page.keyboard.press('Escape')
    await shot(page, 's11-narrow')
  })

  test('at phone width the same rows open the panels as dialogs', async () => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto(research())
    await expect(page.locator('.research-topbar')).toBeVisible()
    await expect(rail(page)).toBeHidden()
    await page.getByRole('button', { name: 'Research actions' }).click()
    await page.getByRole('menuitem', { name: /^Get more full text\b/ }).click()
    await expect(page.getByRole('dialog', { name: 'Get more full text' })).toBeVisible()
    await page.setViewportSize({ width: 1280, height: 900 })
  })
})
