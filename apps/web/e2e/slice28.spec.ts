import { expect, request as apiRequest, test, type APIRequestContext, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort, readingDone } from './ports'

// Case S (slice 28, SW27, D109): the criterion names a comparator and both reading runs find no part of a work, so code
// does not exclude it. The queue shows it as a `confirm_absent` row whose reason is `comparator_exclusion_withheld`:
// its kind, the question naming the comparator part and the reason, at 1440 and 390 px, and a person's answer takes it
// out.
//
// SYNTHETIC records, a scripted model ("[comparator]" with DEIXIS_FIXTURE_COMPARATOR) and mocked providers. A passing
// case shows application behavior, not how a real model reads a comparison group.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

const QUESTION = '[queue] [comparator] How do SYNTHETIC molecular relays and greenhouse irrigation schedule their releases compared with a fixed release?'
const WORK = 'SYNTHETIC relay release bursts beside a fixed schedule'
const ASKED = 'The reading could not settle the part “measured outcome”.'
const REASON = 'Both runs found parts missing, but the criterion has a comparison group, so the reading did not exclude this work.'

class Slice28Server {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-slice28-'))
  constructor(readonly port: number, readonly env: Record<string, string>) {}

  async start() {
    const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend'), ...this.env }
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`http://127.0.0.1:${this.port}/api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`slice 28 fixture server on ${this.port} did not start`)
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
async function apiOf(server: Slice28Server): Promise<Api> {
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

async function openQueue(page: Page, server: Slice28Server, rid: string) {
  await page.goto('about:blank')
  await page.goto(`${server.url()}/#/research/${rid}/queue`)
  await expect(list(page)).toBeVisible()
}

test.describe.serial('S: a work both runs find no part of, on a comparator criterion, is a queue row, not an exclusion', () => {
  const server = new Slice28Server(nextPort(), { DEIXIS_SEARCH_WORKFLOW: 'sw', DEIXIS_PROTOCOL_APPROVAL: 'as_proposed', DEIXIS_FIXTURE_QUEUE: 'on', DEIXIS_FIXTURE_COMPARATOR: 'on' })
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
    const row = rows.find(r => r.title.startsWith(WORK))
    if (!row || row.kind !== 'confirm_absent') throw new Error(`fixture failure: no confirm_absent row (${rows.map(r => r.kind).join(', ')})`)
    expect([row.reason_code, (row.question as { part: string } | null)?.part]).toEqual(['comparator_exclusion_withheld', 'measured outcome'])
  })
  test.afterAll(async () => { await api?.context.dispose(); await server.stop() })

  test('at 1440 px the row names its kind, asks about the comparator part and says why it is here', async ({ browser }) => {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
    try {
      await openQueue(page, server, rid)
      await expect(page.locator('.queue-panel').getByRole('button', { name: /^Confirm the absence/ })).toBeVisible()
      await option(page, WORK).click()
      await expect(detail(page).getByRole('heading', { name: WORK })).toBeVisible()
      await expect(detail(page).locator('.queue-detail-meta')).toContainText('Confirm the absence')
      await expect(detail(page)).toContainText(ASKED)
      await expect(detail(page)).toContainText(REASON)
      await expect(detail(page)).not.toContainText('You decided this work under an earlier question')
      await expect(detail(page).locator('.queue-run')).toHaveCount(2)
      await shot(page, 'S-queue-comparator-withheld-1440')
    } finally { await page.close() }
  })

  test('at 390 px the same row reads without side scroll, and an answer takes it out of the queue', async ({ browser }) => {
    const narrow = await browser.newPage({ viewport: { width: 390, height: 844 } })
    try {
      await openQueue(narrow, server, rid)
      await option(narrow, WORK).click()
      await expect(list(narrow)).toBeHidden()
      await expect(detail(narrow).getByRole('heading', { name: WORK })).toBeVisible()
      await expect(detail(narrow)).toContainText(ASKED)
      await expect(detail(narrow)).toContainText(REASON)
      expect(await noSideScroll(narrow)).toBe(true)
      await shot(narrow, 'S-queue-comparator-withheld-390')
      await detail(narrow).getByRole('button', { name: 'No, it does not meet the criterion', exact: true }).click()
      await expect.poll(async () => ((await (await api.context.get(`/api/researches/${rid}/queue`)).json()).rows as Row[])
        .some(r => r.title.startsWith(WORK))).toBe(false)
    } finally { await narrow.close() }
  })
})
