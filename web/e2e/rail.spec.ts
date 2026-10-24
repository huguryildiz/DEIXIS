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

const REPO = path.resolve(process.cwd(), '..')
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
    const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: REPO, DEIXIS_FIXTURE_FULLTEXT: 'on' }
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
  run_total?: number
  runs: Array<{ id: string; kind: string; status: string; scope_revision: number; steps?: Step[]; usage: { model_calls?: number }; budget: { max_model_calls?: number } }>
  counts: { queue?: number; look_again?: number; waiting_for_pdf?: number; cited: number; fulltext_read_works?: number; funnel?: { unique: number; abstracts_read: number; candidates: number } | null }
  answers: Array<{ id: string; status: string; inputs_given: { depth?: { pdf: number; abstract: number; metadata: number } } | null }>
  sources: Array<{ version_role: string; selection: { state: string; version: number }; source_version_id: string }>
}
const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
const post = (api: Api, url: string, data: unknown, headers: Record<string, string> = {}) => api.context.post(url, { data, headers: { 'x-deixis-csrf': api.token, ...headers } })
const viewOf = async (api: Api, rid: string) => (await (await api.context.get(`/api/researches/${rid}`)).json()) as View
const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`), animations: 'disabled' })
const rail = (page: Page) => page.getByRole('complementary', { name: /^Artifacts/ })
const box = (page: Page, title: string) => page.locator('.rail .box').filter({ has: page.locator('h5', { hasText: title }) })

// The reading step's rule (Transcript.tsx `readingWorks`), run by run: a work is read in a run when both its full-text
// passes stored a result there. The rail's count is the backend's, over every run of the question, each work once; with
// every reading run among the listed ones the two must agree.
function readInRuns(view: View) {
  const read = new Set<string>()
  for (const run of view.runs) {
    if (run.scope_revision !== view.research.current_scope_revision) continue
    const passes = new Map<string, number>()
    for (const step of run.steps ?? []) {
      if (step.kind !== 'model:fulltext_adjudication') continue
      const work = step.operation_key.replace(/^fulltext_adjudication:/, '').replace(/:[^:]*$/, '')
      passes.set(work, (passes.get(work) ?? 0) + (step.status === 'succeeded' ? 1 : 0))
    }
    for (const [work, n] of passes) if (n >= 2) read.add(work)
  }
  return read.size
}
const newestReport = (view: View) => view.answers.find(a => a.status === 'structurally_valid')!

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
    // Artifacts (n): the report (one row, its versions behind the chip), the table, no evidence report.
    await expect(aside.locator('h5').first()).toHaveText('Artifacts (2)')
    await expect(aside.getByRole('button', { name: /^Evidence table · 6 sources · 4 columns/ })).toBeVisible()
    await aside.locator('.vchip').first().click()
    await expect(page.getByRole('menuitem')).toHaveCount(reports)
    await expect(page.getByRole('menuitem').first()).toContainText(`V${reports}`)
    await page.keyboard.press('Escape')
    // The amber box: one row per queue row, with what each asks; the queue's size is the topbar chip's too.
    const waiting = (view.counts.queue ?? 0) + (view.counts.look_again ?? 0)
    expect(waiting).toBeGreaterThan(0)
    const amber = box(page, 'Waiting for your decision')
    await expect(amber).toHaveClass(/warnbox/)
    await expect(amber.locator('button.li')).toHaveCount(Math.min(waiting, 8))
    await expect(amber.locator('button.li em').first()).toHaveText(/\S/)
    // The funnel: the mockup's five bars, "Found" named for what it counts (unique works) and "Read in full" under its
    // §2.3 name, every number a stored count. Full text read is the backend's count, the reading step's rule over runs.
    const funnel = view.counts.funnel!
    const bars = box(page, 'From search to answer').locator('.fun button')
    await expect(bars.locator('span:first-child')).toHaveText(['Unique works', 'Abstract read', 'Passed the abstract stage', 'Full text read', 'Cited'])
    expect(view.counts.fulltext_read_works).toBeGreaterThan(0)
    expect(view.counts.fulltext_read_works).toBe(readInRuns(view))
    await expect(bars.locator('b')).toHaveText([funnel.unique, funnel.abstracts_read, funnel.candidates, view.counts.fulltext_read_works!, view.counts.cited].map(n => n.toLocaleString()))
    await expect(bars.nth(3)).toHaveAttribute('title', /over every run of this question/)
    // Depth: what the newest report's answer was given (its stored input), in works.
    const given = newestReport(view).inputs_given!.depth!
    expect(given.pdf + given.abstract + given.metadata).toBeGreaterThan(0)
    const depth = box(page, 'How deeply sources were read')
    await expect(depth.locator('.legend')).toContainText(`PDF text ${given.pdf}`)
    await expect(depth.locator('.legend')).toContainText(`Abstract only ${given.abstract}`)
    // Its scope: the works the newest report was given, named by its version (S11 follow-up).
    await expect(depth.locator('.rail-scope')).toHaveText(`Works given to the latest report (V${reports})`)
    // Run: Activity with the research's run count (all of them, not the ten the view lists), Candidates, Follow-up.
    expect(view.run_total).toBeGreaterThanOrEqual(view.runs.length)
    await expect(box(page, 'Run').locator('button.li').first()).toContainText(`${view.run_total} runs`)
    await expect(box(page, 'Run').locator('button.li span')).toHaveText(['Activity', 'Candidates', 'Follow-up'])
    await expect(page.locator('.rail .box h5')).toHaveText(['Artifacts (2)', 'Waiting for your decisionOpen', 'From search to answerOpen', 'How deeply sources were readOpen', 'Run', 'Usage'])
    await shot(page, 's11-rail')
  })

  test('S27 (RL8): the Usage box shows the newest run’s stored calls against its limit and OpenAlex’s last stored budget', async () => {
    const view = await viewOf(api, rid)
    // The run the box names is picked from the stored runs, never by position on the page.
    const run = view.runs.find(r => (r.budget.max_model_calls ?? 0) > 0)!
    expect(run).toBeTruthy()
    const usage = await (await api.context.get(`/api/usage?period=run&run_id=${run.id}`)).json() as { total: number }
    // The rail's figure is the run's counter, which the store writes with each stored model session: the same number.
    expect(run.usage.model_calls ?? 0).toBe(usage.total)
    const budget = await (await api.context.get('/api/openalex/budget-today')).json() as { used_fraction: number | null; remaining: number | null; unit: string | null; as_of: string | null }
    await page.goto(research())
    const usageBox = box(page, 'Usage')
    await expect(usageBox.locator('.kv span:first-child')).toHaveText(['Model calls', 'OpenAlex budget today'])
    await expect(usageBox.locator('.kv').first().locator('.rail-data')).toHaveText(`${usage.total.toLocaleString()} / ${run.budget.max_model_calls!.toLocaleString()}`)
    const kinds: Record<string, string> = { discovery: 'Search & screening', answer: 'Answer', answer_review: 'Answer review', pdf_collection: 'PDF collection', screen_more: 'Abstract screening of more works' }
    await expect(usageBox.locator('.rail-usage-note').first()).toHaveText(`Latest run: ${kinds[run.kind] ?? run.kind}`)
    // The fixture's OpenAlex answers carry no rate-limit header, so nothing is stored since the reset: "not known", no
    // bar and no 0 (a stored figure is shown with its time instead).
    const figure = usageBox.locator('.kv').nth(1).locator('.rail-data')
    if (budget.remaining === null) {
      await expect(figure).toHaveText('not known')
      await expect(usageBox.locator('.bar')).toHaveCount(1)
      await expect(usageBox.locator('.rail-usage-note').nth(1)).toHaveText('No OpenAlex response stored since the daily reset')
    } else {
      await expect(figure).not.toHaveText('not known')
      await expect(usageBox.locator('.rail-usage-note').nth(1)).toHaveText(/^Last stored response, /)
    }
  })

  test('S27 (P25): Recheck this column queues one run over the column; each result waits as a proposal and no value changes', async () => {
    test.setTimeout(150_000)
    type Table = { columns: Array<{ id: string; name: string }>; rows: unknown[]; counts: { with_value: number; pending_proposals: number } }
    const tables = await (await api.context.get(`/api/researches/${rid}/tables`)).json() as Array<{ id: string }>
    const tableOf = async () => (await (await api.context.get(`/api/researches/${rid}/tables/${tables[0].id}`)).json()) as Table
    const before = await tableOf()
    const column = before.columns.find(c => c.name === 'Network model')!
    await page.goto(`${research()}/table`)
    await page.locator('.evidence-grid thead .evidence-col-head', { hasText: 'Network model' }).click()
    const item = page.getByRole('menuitem', { name: /^Recheck this column/ })
    await expect(item).toContainText(`${before.rows.length} rows · 1–2 calls each`)
    const queued = page.waitForResponse(response => response.url().endsWith(`/columns/${column.id}/recheck`) && response.request().method() === 'POST')
    await item.click()
    // The toast names what the server planned: the cells it reads again and the rows it leaves for having no text.
    const run = await (await queued).json() as { id: string; target: { cells: unknown[]; rows_without_text: unknown[] } }
    const planned = run.target.cells.length
    expect(planned + run.target.rows_without_text.length).toBe(before.rows.length)
    await expect(page.locator('.toast').filter({ hasText: planned === 1 ? 'Recheck of “Network model” started: 1 cell is read again.' : `Recheck of “Network model” started: ${planned} cells are read again.` })).toBeVisible()
    await expect.poll(async () => (await viewOf(api, rid)).runs.find(r => r.id === run.id)?.status, { timeout: 120_000 }).toBe('completed')
    // Results wait as proposals: no cell value changed, more proposals wait, and the table's foot reads the stored counts.
    const after = await tableOf()
    expect(after.counts.with_value).toBe(before.counts.with_value)
    expect(after.counts.pending_proposals).toBeGreaterThan(before.counts.pending_proposals)
    await expect(page.locator('.table-counts')).toContainText(`${after.counts.pending_proposals} proposals waiting`)
    await expect(page.locator('.toast').filter({ hasText: 'Column recheck finished. Its results wait as proposals in the cells; no value was changed.' })).toBeVisible()
  })

  test('every box opens its panel; the rail is gone while a panel is open and returns with focus on the box', async () => {
    await page.goto(research())
    await expect(rail(page)).toBeVisible()
    const cases: [string, () => ReturnType<Page['locator']>, string | RegExp][] = [
      ['Activity', () => rail(page).getByRole('button', { name: /^Activity/ }), PANEL_TITLES.activity],
      ['Candidates', () => rail(page).getByRole('button', { name: /^Candidates/ }), PANEL_TITLES.cands],
      ['Follow-up', () => rail(page).getByRole('button', { name: /^Follow-up/ }), PANEL_TITLES.watch],
      ['queue', () => rail(page).getByRole('button', { name: 'Open Waiting for your decision' }), PANEL_TITLES.queue],
      ['the funnel', () => rail(page).getByRole('button', { name: 'Open From search to answer' }), PANEL_TITLES.funnel],
      ['a funnel bar', () => rail(page).locator('.fun button').first(), PANEL_TITLES.funnel],
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
    // The report row opens the newest report's panel.
    await rail(page).locator('.vrow-main').first().click()
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

  test('a list edit after the answer leaves its reading depth; an emptied queue leaves no rows in the amber box', async () => {
    await page.setViewportSize({ width: 1280, height: 900 })
    const before = await viewOf(api, rid)
    const given = newestReport(before).inputs_given!.depth!
    // Excluding an included source after the answer does not rewrite what the answer was given.
    const included = before.sources.find(s => s.version_role === 'record' && s.selection.state === 'included')!
    const patched = await api.context.patch(`/api/researches/${rid}/selections/${included.source_version_id}`,
      { data: { state: 'excluded', expected_version: included.selection.version, reason: 'SYNTHETIC list edit' }, headers: { 'x-deixis-csrf': api.token } })
    expect(patched.ok()).toBe(true)
    const after = await viewOf(api, rid)
    expect(newestReport(after).inputs_given!.depth).toEqual(given)
    // The fixture has no work waiting for a PDF once its queue is answered (its works all have open PDFs), so the
    // waiting count alone is set to one in the view the page receives; the queue and its rows are the server's.
    await page.route(`**/api/researches/${rid}`, async route => {
      if (route.request().method() !== 'GET') return route.fallback()
      const response = await route.fetch()
      const body = await response.json() as View
      body.counts.waiting_for_pdf = 1
      await route.fulfill({ response, json: body })
    })
    await page.goto(research())
    const depth = box(page, 'How deeply sources were read')
    await expect(depth.locator('.legend')).toContainText(`PDF text ${given.pdf}`)
    await expect(depth.locator('.legend')).toContainText(`Abstract only ${given.abstract}`)
    const amber = box(page, 'Waiting for your decision')
    const queueRows = amber.locator('button.li').filter({ hasNotText: /waiting for a PDF/ })
    await expect(queueRows.first()).toBeVisible()
    // Every queue row answered while the page is open: the box stays for the PDF and lists no decided row.
    const rows = (await (await api.context.get(`/api/researches/${rid}/queue`)).json()).rows as Array<{ source_version_id: string; row_token: string }>
    for (const row of rows) {
      const answered = await post(api, `/api/researches/${rid}/queue/${row.source_version_id}/decision`, { decision: 'include', note: null, row_token: row.row_token })
      expect(answered.ok()).toBe(true)
    }
    await expect.poll(async () => (await viewOf(api, rid)).counts.queue ?? 0).toBe(0)
    await expect(queueRows).toHaveCount(0)
    await expect(amber.locator('button.li')).toHaveText([/1 waiting for a PDF/])
    await page.unroute(`**/api/researches/${rid}`)
  })

  test('the flow boxes name their own full-text count apart from the rail’s Full text read', async () => {
    // The rail counts works whose two full-text passes stored a result; the PRISMA-style box counts works with a current
    // full-text decision, the reading's or the person's. One label each (S11 follow-up).
    const view = await viewOf(api, rid) as View & { counts: { flow_boxes?: { boxes: { key: string; count: number | null }[] } } }
    const box = view.counts.flow_boxes!.boxes.find(b => b.key === 'fulltext_read')!
    await page.goto(`${research()}/funnel`)
    const flow = page.locator('details.flow-block')
    await flow.locator('summary').click()
    const row = flow.locator('.flow-list li', { hasText: 'Works with a current full-text decision (reading or yours)' })
    await expect(row.locator('strong')).toHaveText(String(box.count))
    await expect(flow.locator('.flow-list li span', { hasText: /^Full text read$/ })).toHaveCount(0)
  })

  test('a paused PDF collection reads as paused in the background box', async () => {
    // SYNTHETIC: the fixture's collections end within a poll, so a paused collection run is added to the view the page
    // receives (rail.spec's other states are the server's).
    await page.route(`**/api/researches/${rid}`, async route => {
      if (route.request().method() !== 'GET') return route.fallback()
      const response = await route.fetch()
      const body = await response.json() as View
      body.runs = [{ ...body.runs[0], id: 'run_synthetic_collection', kind: 'pdf_collection', status: 'paused', steps: [] }, ...body.runs]
      await route.fulfill({ response, json: body })
    })
    await page.goto('about:blank')
    await page.goto(research())
    const background = box(page, 'In the background')
    await expect(background.locator('.kv span').first()).toHaveText('PDF collection paused')
    await page.unroute(`**/api/researches/${rid}`)
  })

  test('after a question change the depth box says its report belongs to the earlier revision', async () => {
    const before = await viewOf(api, rid)
    const reports = before.answers.filter(a => a.status === 'structurally_valid').length
    const research_ = await (await api.context.get(`/api/researches/${rid}`)).json() as { research: { version: number } }
    const revised = await post(api, `/api/researches/${rid}/scope`, { question: `${PARITY} (SYNTHETIC revision)`, expected_version: research_.research.version, key_terms: null })
    expect(revised.ok(), await revised.text()).toBe(true)
    await page.goto('about:blank')
    await page.goto(research())
    await expect(box(page, 'How deeply sources were read').locator('.rail-scope')).toHaveText(`Works given to the latest report (V${reports}) · question revision 1`)
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
