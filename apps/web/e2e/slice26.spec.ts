import { expect, request as apiRequest, test, type APIRequestContext, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort, readingDone, modeEnv } from './ports'

// Case R (slice 26, SW26, D107): both reading runs find every part of a work whose title names a study protocol, and
// code neither includes nor excludes it. The queue shows it as a `confirm_results` row: its kind, the question for that
// kind and the reason, at 1440 and 390 px, and a person's answer takes it out.
//
// SYNTHETIC records, a scripted model ("[protocol-title]" with DEIXIS_FIXTURE_PROTOCOL) and mocked providers. A passing
// case shows application behavior, not how often a real title names a protocol.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

const QUESTION = '[queue] [protocol-title] How do SYNTHETIC molecular relays and greenhouse irrigation schedule their releases?'
const PROTOCOL = 'SYNTHETIC release windows for molecular relay chains: a study protocol'
const ASKED = 'The title names a study protocol. Does this paper report results for every part, rather than only planning to measure them?'
const REASON = 'The title names a study protocol, so the reading neither included nor excluded this work.'

class Slice26Server {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-slice26-'))
  constructor(readonly port: number, readonly env: Record<string, string>) {}

  async start() {
    const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend'), ...modeEnv, ...this.env }
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`http://127.0.0.1:${this.port}/api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`slice 26 fixture server on ${this.port} did not start`)
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
async function apiOf(server: Slice26Server): Promise<Api> {
  const context = await apiRequest.newContext({ baseURL: server.url(), extraHTTPHeaders: { origin: server.url() } })
  const token = (await (await context.get('/api/session')).json()).csrf_token as string
  return { context, token }
}
const post = (api: Api, url: string, data: unknown) => api.context.post(url, { data, headers: { 'x-deixis-csrf': api.token } })
type Row = { source_version_id: string; kind: string; reason_code: string; title: string; question: unknown }

const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`), animations: 'disabled', fullPage: true })
const list = (page: Page) => page.getByRole('listbox', { name: 'Rows awaiting your decision' })
const option = (page: Page, title: string) => list(page).getByRole('option', { name: new RegExp(`^${title}`) })
const detail = (page: Page) => page.locator('.queue-detail')
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)

async function openQueue(page: Page, server: Slice26Server, rid: string) {
  await page.goto('about:blank')
  await page.goto(`${server.url()}/#/research/${rid}/queue`)
  await expect(list(page)).toBeVisible()
}

test.describe.serial('R: a work whose title names a study protocol is a queue row, not an include', () => {
  const server = new Slice26Server(nextPort(), { DEIXIS_SEARCH_WORKFLOW: 'sw', DEIXIS_PROTOCOL_APPROVAL: 'as_proposed', DEIXIS_FIXTURE_QUEUE: 'on', DEIXIS_FIXTURE_PROTOCOL: 'on' })
  let api: Api
  let rid = ''

  test.beforeAll(async () => {
    await server.start()
    api = await apiOf(server)
    const created = await post(api, '/api/researches', { question: QUESTION, model_connection: 'codex', requested_model: 'fixture-model', effort: 'quick' })
    expect(created.status()).toBe(201)
    rid = (await created.json()).research.id as string
    expect((await post(api, `/api/researches/${rid}/runs`, { kind: 'discovery' })).ok()).toBe(true)
    await expect.poll(async () => {
      const view = await (await api.context.get(`/api/researches/${rid}`)).json()
      return readingDone(view)
    }, { timeout: 90_000 }).toBe(true)
    const rows = (await (await api.context.get(`/api/researches/${rid}/queue`)).json()).rows as Row[]
    const row = rows.find(r => r.title.startsWith(PROTOCOL))
    if (!row || row.kind !== 'confirm_results') throw new Error(`fixture failure: no confirm_results row (${rows.map(r => r.kind).join(', ')})`)
    expect([row.reason_code, row.question]).toEqual(['protocol_title', null])
  })
  test.afterAll(async () => { await api?.context.dispose(); await server.stop() })

  test('at 1440 px the row names its kind, asks whether the paper reports results and says why it is here', async ({ browser }) => {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
    try {
      await openQueue(page, server, rid)
      await expect(page.locator('.queue-panel').getByRole('button', { name: /^Confirm the results/ })).toBeVisible()
      await option(page, PROTOCOL).click()
      await expect(detail(page).getByRole('heading', { name: PROTOCOL })).toBeVisible()
      await expect(detail(page).locator('.queue-detail-meta')).toContainText('Confirm the results')
      await expect(detail(page)).toContainText(ASKED)
      await expect(detail(page)).toContainText(REASON)
      await expect(detail(page)).not.toContainText('You decided this work under an earlier question')
      await expect(detail(page).locator('.queue-run')).toHaveCount(2)
      await shot(page, 'R-queue-protocol-title-1440')
    } finally { await page.close() }
  })

  test('at 390 px the same row reads without side scroll, and an answer takes it out of the queue', async ({ browser }) => {
    const narrow = await browser.newPage({ viewport: { width: 390, height: 844 } })
    try {
      await openQueue(narrow, server, rid)
      await option(narrow, PROTOCOL).click()
      await expect(list(narrow)).toBeHidden()
      await expect(detail(narrow).getByRole('heading', { name: PROTOCOL })).toBeVisible()
      await expect(detail(narrow)).toContainText(ASKED)
      await expect(detail(narrow)).toContainText(REASON)
      expect(await noSideScroll(narrow)).toBe(true)
      await shot(narrow, 'R-queue-protocol-title-390')
      await detail(narrow).getByRole('button', { name: 'Yes', exact: true }).click()
      await expect.poll(async () => ((await (await api.context.get(`/api/researches/${rid}/queue`)).json()).rows as Row[])
        .some(r => r.title.startsWith(PROTOCOL))).toBe(false)
    } finally { await narrow.close() }
  })
})
