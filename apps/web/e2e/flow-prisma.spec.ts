import { expect, request as apiRequest, test, type APIRequestContext, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

// Case M: where every work of an sw research stands (slice 20, D102). The Sources tab's flow line, the PRISMA-S search
// report in both formats, the line under an answer that says where the flow stood when the answer started, and the
// Home screen's depth text read from the server's limits.
//
// Its own fixture server, with retrieval and reading switched on and the case J works plus one both reading runs
// include (DEIXIS_FIXTURE_AUDIT), so an answer has a work to use. Every record is SYNTHETIC; a passing case shows
// application behavior, not the quality of a search or a reading.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

const QUESTION = '[queue] How do SYNTHETIC molecular relays and greenhouse irrigation schedule their releases?'

class FlowServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-flow-'))
  constructor(readonly port: number, readonly env: Record<string, string>) {}

  async start() {
    const env = {  // no provider keys or user data directory reach the fixture
      PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend'), ...this.env,
    }
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`http://127.0.0.1:${this.port}/api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`flow fixture server on ${this.port} did not start`)
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
async function apiOf(server: FlowServer): Promise<Api> {
  const context = await apiRequest.newContext({ baseURL: server.url(), extraHTTPHeaders: { origin: server.url() } })
  const token = (await (await context.get('/api/session')).json()).csrf_token as string
  return { context, token }
}
const post = (api: Api, url: string, data: unknown) => api.context.post(url, { data, headers: { 'x-deixis-csrf': api.token } })
const viewOf = async (api: Api, rid: string) => (await (await api.context.get(`/api/researches/${rid}`)).json())
const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`), animations: 'disabled', fullPage: true })

test.describe.serial('M: the flow of an sw research and its search report', () => {
  const server = new FlowServer(8783, { DEIXIS_SEARCH_WORKFLOW: 'sw', DEIXIS_PROTOCOL_APPROVAL: 'as_proposed', DEIXIS_FIXTURE_QUEUE: 'on', DEIXIS_FIXTURE_AUDIT: 'on' })
  let api: Api
  let rid = ''
  let page: Page

  test.beforeAll(async ({ browser }) => {
    await server.start()
    api = await apiOf(server)
    const created = await post(api, '/api/researches', { question: QUESTION, model_connection: 'codex', requested_model: 'fixture-model', effort: 'quick' })
    expect(created.status()).toBe(201)
    rid = (await created.json()).research.id
    expect((await post(api, `/api/researches/${rid}/runs`, { kind: 'discovery' })).ok()).toBe(true)
    await expect.poll(async () => (await viewOf(api, rid)).runs.some((r: { kind: string; status: string }) => r.kind === 'fulltext_adjudication' && r.status === 'completed'), { timeout: 90_000 }).toBe(true)
    // The fixture must have given one include by agreement and four queue rows before the screen is asked anything.
    const five = (await viewOf(api, rid)).counts.flow.five
    if (five.included_by_agreement !== 1 || five.queued !== 4) throw new Error(`fixture failure: flow ${JSON.stringify(five)}`)
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  })
  test.afterAll(async () => { await page?.close(); await api?.context.dispose(); await server.stop() })

  test('the Sources tab shows the five counts in one line and every bucket when opened', async () => {
    await page.goto(`${server.url()}/#/research/${rid}/sources`)
    const block = page.locator('details.flow-block')
    await expect(block.locator('summary')).toContainText('1 included (two agreeing runs 1, you confirmed 0) · 4 in your queue, not looked at · 0 waiting for a PDF')
    await block.locator('summary').click()
    await expect(block.locator('.flow-list li', { hasText: 'Included by two agreeing runs' })).toContainText('1')
    await expect(block.locator('.flow-list li', { hasText: 'In your queue, not looked at' })).toContainText('4')
    await expect(block).toContainText('Incomplete: code and model runs did the screening')
    // A work two agreeing runs included is never called verified (a reason code such as include_quote_unverified may show).
    expect((await block.textContent()) ?? '').not.toMatch(/(?<![_a-z])verified/)
    await expect(block.locator('.flow-list li', { hasText: 'Records returned by citation requests' })).toContainText('0')
    await shot(page, 'M-flow-sources-1440')
  })

  test('the PRISMA-S report downloads as Markdown and JSON with its 16 items and its statement', async () => {
    const block = page.locator('details.flow-block')
    const [md] = await Promise.all([page.waitForEvent('download'), block.getByRole('link', { name: '.md' }).click()])
    const text = readFileSync((await md.path())!, 'utf8')
    expect(text.split('\n')[0]).toBe('# Search report (PRISMA-S items)')
    expect(text).toContain('This is not a PRISMA-compliant review')
    expect(text.match(/^## \d+\. /gm)).toHaveLength(16)
    const [json] = await Promise.all([page.waitForEvent('download'), block.getByRole('link', { name: '.json' }).click()])
    const data = JSON.parse(readFileSync((await json.path())!, 'utf8'))
    expect(data.items).toHaveLength(16)
    expect(data.statement).toContain('This is not a PRISMA-compliant review')
  })

  test('an answer shows where the flow stood when it started, apart from what the model was given', async () => {
    const run = await post(api, `/api/researches/${rid}/runs`, { kind: 'answer' })
    expect(run.ok()).toBe(true)
    await expect.poll(async () => (await viewOf(api, rid)).answers.length, { timeout: 60_000 }).toBe(1)
    await page.goto('about:blank')
    await page.goto(`${server.url()}/#/research/${rid}`)
    const line = page.getByRole('group', { name: 'Flow at the start of this answer' }).first()
    await expect(line).toContainText('When the answer started: included 1 (two agreeing runs 1, you confirmed 0); in your queue, not looked at 4')
    await expect(line).toContainText('Given to the model: works 1, passages')
    await expect(line.locator('.is-attention')).toHaveCount(0)
    await shot(page, 'M-answer-flow-1440')
  })

  test('the Home screen gives the depth of an sw search in the numbers the server reads', async () => {
    const limits = await (await api.context.get('/api/effort-limits')).json()
    expect(limits.search_workflow).toBe('sw')
    const quick = limits.efforts.quick
    await page.goto('about:blank')
    await page.goto(`${server.url()}/#/`)
    await page.getByRole('combobox', { name: 'Research depth' }).click()
    await expect(page.getByRole('option').first()).toContainText(`Each search reads up to ${quick.read} records; the model screens ${quick.abstracts} abstracts`)
    await shot(page, 'M-home-depth-1440')
    await page.keyboard.press('Escape')
  })

  test('at 390 px the flow line and the answer line fit without a horizontal scroll', async ({ browser }) => {
    for (const scheme of ['light', 'dark'] as const) {
      const narrow = await browser.newPage({ viewport: { width: 390, height: 844 }, colorScheme: scheme })
      try {
        await narrow.goto(`${server.url()}/#/research/${rid}/sources`)
        await narrow.locator('details.flow-block summary').click()
        await expect(narrow.locator('.flow-detail')).toBeVisible()
        expect(await narrow.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
        await shot(narrow, `M-flow-sources-390-${scheme}`)
        await narrow.goto('about:blank')
        await narrow.goto(`${server.url()}/#/research/${rid}`)
        await expect(narrow.getByRole('group', { name: 'Flow at the start of this answer' }).first()).toBeVisible()
        expect(await narrow.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
        await shot(narrow, `M-answer-flow-390-${scheme}`)
      } finally { await narrow.close() }
    }
  })
})
