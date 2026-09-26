import { expect, request as apiRequest, test, type APIRequestContext, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

// Case P (slice 25, SW21, D106): works whose own PDF is withheld get their text from Europe PMC's open-access XML,
// drawn as a PDF by DEIXIS. Every surface that names one of its pages says "Europe PMC text, rendered p. n", never
// "PDF p. n": the queue strip, the closest text and the part link, the audit sample, the answer's reference list and
// its Markdown copy, the passage sheet's plain text and the PDF viewer. The plain "PDF p. n" of an ordinary PDF is
// checked on the same surfaces by cases A, J and K.
//
// Case Q (slice 25, SW22, D106): an sw research whose search finished with nothing included can still ask for an
// answer; the answer says no work was included at full text when it started, with the flow line, and asks no model.
//
// Both run on SYNTHETIC records with a scripted model and mocked providers. A passing case shows application behavior,
// not how often Europe PMC holds a work or how well its XML draws.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

const RENDERED = 'Europe PMC text, rendered p. 1'
const QUESTION = '[queue] How do SYNTHETIC molecular relays and greenhouse irrigation schedule their releases?'
const AGREED = 'SYNTHETIC release window pacing along molecular relay chains'
const TITLES = {
  choose_run: 'SYNTHETIC bisection release scheduling for molecular relay networks',
  confirm_quote: 'SYNTHETIC moisture threshold irrigation of greenhouse benches',
}

class Slice25Server {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-slice25-'))
  constructor(readonly port: number, readonly env: Record<string, string>) {}

  async start() {
    const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend'), ...this.env }
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`http://127.0.0.1:${this.port}/api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`slice 25 fixture server on ${this.port} did not start`)
  }

  async stop() {
    const proc = this.proc
    if (!proc || proc.exitCode !== null) return
    const exited = new Promise(resolve => proc.once('exit', resolve))
    proc.kill('SIGTERM')
    await exited
  }

  url() { return `http://127.0.0.1:${this.port}` }
}

type Api = { context: APIRequestContext; token: string }
async function apiOf(server: Slice25Server): Promise<Api> {
  const context = await apiRequest.newContext({ baseURL: server.url(), extraHTTPHeaders: { origin: server.url() } })
  const token = (await (await context.get('/api/session')).json()).csrf_token as string
  return { context, token }
}
const post = (api: Api, url: string, data: unknown) => api.context.post(url, { data, headers: { 'x-deixis-csrf': api.token } })
const viewOf = async (api: Api, rid: string) => (await api.context.get(`/api/researches/${rid}`)).json()
type RunRow = { kind: string; status: string }

async function createResearch(api: Api, question: string) {
  const created = await post(api, '/api/researches', { question, model_connection: 'codex', requested_model: 'fixture-model', effort: 'quick' })
  expect(created.status()).toBe(201)
  return (await created.json()).research.id as string
}

const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`), animations: 'disabled', fullPage: true })
const list = (page: Page) => page.getByRole('listbox', { name: 'Rows awaiting your decision' })
const option = (page: Page, title: string) => list(page).getByRole('option', { name: new RegExp(`^${title}`) })
const detail = (page: Page) => page.locator('.queue-detail')
const sheet = (page: Page) => page.locator('.source-sheet')
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)

test.describe.serial('P: pages of Europe PMC’s drawn text say "rendered" on every surface', () => {
  const server = new Slice25Server(8785, {
    DEIXIS_SEARCH_WORKFLOW: 'sw', DEIXIS_PROTOCOL_APPROVAL: 'as_proposed', DEIXIS_FIXTURE_QUEUE: 'on', DEIXIS_FIXTURE_AUDIT: 'on',
    DEIXIS_FIXTURE_EUROPEPMC: 'on',
  })
  let api: Api
  let rid = ''
  let page: Page

  test.beforeAll(async ({ browser }) => {
    await server.start()
    api = await apiOf(server)
    rid = await createResearch(api, QUESTION)
    expect((await post(api, `/api/researches/${rid}/runs`, { kind: 'discovery' })).ok()).toBe(true)
    await expect.poll(async () => (await viewOf(api, rid)).runs.some((r: RunRow) => r.kind === 'fulltext_adjudication' && r.status === 'completed'),
      { timeout: 90_000 }).toBe(true)
    // The fixture must have drawn the withheld works from Europe PMC before anything is asked of the screen.
    const view = await viewOf(api, rid)
    const drawn = view.sources.filter((s: { access: { assets: { original_filename: string | null }[] } }) =>
      s.access.assets.some(a => (a.original_filename ?? '').endsWith('.europepmc.pdf')))
    if (drawn.length < 3) throw new Error(`fixture failure: ${drawn.length} works drawn from Europe PMC`)
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  })
  test.afterAll(async () => { await page?.close(); await api?.context.dispose(); await server.stop() })

  test('the queue strip, the part link, the plain text and the PDF viewer name a rendered page', async () => {
    await page.goto(`${server.url()}/#/research/${rid}/queue`)
    await option(page, TITLES.choose_run).click()
    await expect(detail(page).locator('.queue-page-link').first()).toHaveText(RENDERED)
    await expect(detail(page)).not.toContainText('PDF p.')
    await detail(page).locator('.queue-page-link').first().click()
    await expect(sheet(page).locator('.pdf-text-citation')).toContainText(`The model’s quote, found in the text of ${RENDERED}.`)
    await expect(sheet(page)).toContainText('This PDF was drawn by DEIXIS from Europe PMC’s open-access text. Its pages are not the publisher’s pages.')
    await expect(sheet(page).locator('.pdf-text-page h4').first()).toHaveText(RENDERED)
    await shot(page, 'P-queue-rendered-text-1440')
    await sheet(page).getByRole('tab', { name: 'PDF' }).click()
    await expect(sheet(page).locator('.pdf-viewer canvas')).toHaveAttribute('aria-label', RENDERED)
    await expect(sheet(page).locator('.pdf-viewer')).toHaveAttribute('aria-label', new RegExp(`· ${RENDERED}$`))
    await shot(page, 'P-viewer-rendered-1440')
    await page.keyboard.press('Escape')
  })

  test('the closest text of an unverified quote and its strip name a rendered page', async () => {
    await option(page, TITLES.confirm_quote).click()
    await expect(detail(page).locator('.queue-pair h5').nth(1)).toHaveText(`The closest text · ${RENDERED}`)
    await detail(page).getByRole('button', { name: 'Open page 1 in the PDF' }).click()
    await sheet(page).getByRole('tab', { name: 'Plain text' }).click()
    await expect(sheet(page).locator('.pdf-text-citation')).toContainText(`nothing on ${RENDERED} is marked`)
    await page.keyboard.press('Escape')
  })

  test('the audit sample names the rendered page of each quote', async () => {
    const row = page.locator('.audit-panel .audit-group').first().locator('.audit-row', { hasText: AGREED })
    await row.getByRole('button', { name: 'Show what the runs said' }).click()
    await expect(row.locator('.audit-runs')).toContainText(`(${RENDERED})`)
    await expect(row.locator('.audit-runs')).not.toContainText('PDF p.')
  })

  test('the answer’s reference list and its Markdown copy name the rendered page', async () => {
    const started = await post(api, `/api/researches/${rid}/runs`, { kind: 'answer' })
    expect(started.status()).toBe(202)
    const runId = (await started.json()).id as string
    await expect.poll(async () => (await viewOf(api, rid)).runs.find((r: RunRow & { id: string }) => r.id === runId)?.status,
      { timeout: 60_000 }).toBe('completed')
    await page.goto('about:blank')
    await page.goto(`${server.url()}/#/research/${rid}`)
    await page.getByRole('button', { name: /Open report:/ }).first().click()
    const report = page.locator('.report-sheet')
    const reference = report.locator('.reference-list li', { hasText: AGREED })
    await expect(reference.locator('.ref-pills')).toContainText(RENDERED)
    await expect(report.locator('.cite-chip').first()).toHaveAttribute('title', new RegExp(RENDERED))
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
    await report.getByRole('button', { name: 'Copy' }).click()
    const copied = await page.evaluate(() => navigator.clipboard.readText())
    expect(copied).toContain(RENDERED)
    expect(copied).not.toContain('PDF p. 1')
    await shot(page, 'P-answer-rendered-1440')
  })
})

test.describe.serial('Q: an sw research with nothing included ends with an answer that says so', () => {
  // Retrieval and reading are off here, so the search finishes with no work included (the fixture's smallest case).
  const server = new Slice25Server(8780, { DEIXIS_SEARCH_WORKFLOW: 'sw', DEIXIS_PROTOCOL_APPROVAL: 'as_proposed' })
  let api: Api
  let rid = ''

  test.beforeAll(async () => {
    await server.start()
    api = await apiOf(server)
    rid = await createResearch(api, 'How is SYNTHETIC molecule release scheduled in relay networks?')
    expect((await post(api, `/api/researches/${rid}/runs`, { kind: 'discovery' })).ok()).toBe(true)
    await expect.poll(async () => (await viewOf(api, rid)).runs.some((r: RunRow) => r.kind === 'discovery' && r.status === 'completed'),
      { timeout: 90_000 }).toBe(true)
    const view = await viewOf(api, rid)
    if (view.counts.included !== 0) throw new Error(`fixture failure: ${view.counts.included} works included`)
  })
  test.afterAll(async () => { await api?.context.dispose(); await server.stop() })

  for (const width of [1440, 390]) {
    test(`at ${width} px the answer button is on and the answer says nothing was included when it started`, async ({ browser }) => {
      const page = await browser.newPage({ viewport: { width, height: 1000 } })
      try {
        await page.goto(`${server.url()}/#/research/${rid}`)
        const button = page.getByRole('button', { name: /Generate (source-linked|a new) answer/ })
        await expect(button).toBeEnabled()
        // The run ends within one poll, so the page never sees it running and shows no toast; the notice is the check.
        if (width === 1440) await button.click()
        const notice = page.getByText('No work was included at full text when this answer started, so no answer was written and no model was asked.')
        await expect(notice).toBeVisible()
        await expect(page.getByText(/met the criterion/)).toHaveCount(0)
        await expect(page.getByRole('group', { name: 'Flow at the start of this answer' }).first()).toBeVisible()
        expect(await noSideScroll(page)).toBe(true)
        await shot(page, `Q-no-include-answer-${width}`)
      } finally { await page.close() }
    })
  }
})
