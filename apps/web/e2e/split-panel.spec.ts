import { expect, request as apiRequest, test, type APIRequestContext, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort, readingDone } from './ports'
import { openPanel, panel } from './panels'

// UI parity S7a: the research page is a thread with one side panel (mockup R10/P1) instead of tabs. The URL names the
// open panel and the old tab names stay as aliases; panels stack with Back; Full width hides the thread; Close and
// Escape hand focus back to the control that opened the panel; at phone width the panel is a modal dialog.
//
// Its own fixture server with the queue fixture, so the research has sources, queue rows and abstracts to open. Every
// record is SYNTHETIC; a passing case shows how the page behaves, not the quality of a search or a reading.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

const QUESTION = '[queue] How do SYNTHETIC molecular relays and greenhouse irrigation schedule their releases?'

class PanelServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-panel-'))
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
    throw new Error(`panel fixture server on ${this.port} did not start`)
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
const post = (api: Api, url: string, data: unknown) => api.context.post(url, { data, headers: { 'x-deixis-csrf': api.token } })
const viewOf = async (api: Api, rid: string) => (await (await api.context.get(`/api/researches/${rid}`)).json())
const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`), animations: 'disabled' })
const focusedName = (page: Page) => page.evaluate(() => {
  const el = document.activeElement as HTMLElement | null
  return el ? (el.getAttribute('aria-label') ?? el.textContent ?? '').trim() : ''
})

test.describe.serial('S7a: thread and side panel', () => {
  const server = new PanelServer(nextPort(), { DEIXIS_FIXTURE_QUEUE: 'on' })
  let api: Api
  let rid = ''
  let page: Page

  test.beforeAll(async ({ browser }) => {
    await server.start()
    const context = await apiRequest.newContext({ baseURL: server.url(), extraHTTPHeaders: { origin: server.url() } })
    api = { context, token: (await (await context.get('/api/session')).json()).csrf_token as string }
    const created = await post(api, '/api/researches', { question: QUESTION, model_connection: 'codex', requested_model: 'fixture-model', effort: 'quick' })
    expect(created.status()).toBe(201)
    rid = (await created.json()).research.id
    expect((await post(api, `/api/researches/${rid}/runs`, { kind: 'discovery' })).ok()).toBe(true)
    await expect.poll(async () => readingDone(await viewOf(api, rid)), { timeout: 90_000 }).toBe(true)
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  })
  test.afterAll(async () => { await page?.close(); await api?.context.dispose(); await server.stop() })

  test('old tab segments open their panels, and the URL names the panel', async () => {
    const cases: [string, string | RegExp | null, string][] = [
      ['sources', 'Sources', 'sources'], ['queue', /^Awaiting your decision \(\d+\)$/, 'queue'], ['pdfs', 'Get more full text', 'pdfs'],
      ['waiting', 'Get more full text', 'pdfs'], ['evidence', 'Evidence table', 'table'], ['followup', 'Follow-up', 'watch'],
      ['candidates', 'Candidates', 'cands'], ['activity', 'Activity', 'activity'], ['artifacts', null, ''], ['answer', null, ''],
    ]
    for (const [segment, title, canonical] of cases) {
      await page.goto(`${server.url()}/#/research/${rid}/${segment}`)
      await expect(page.locator('.research-thread')).toBeVisible()
      if (title) {
        await expect(panel(page, title)).toBeVisible()
        // The panel is a labelled region beside the thread, not a modal dialog, and the tabs are gone.
        await expect(panel(page, title)).toHaveAttribute('role', 'region')
        await expect(page.locator('[data-split-panel] #split-panel-title')).toBeFocused()
      } else await expect(page.locator('[data-split-panel]')).toHaveCount(0)
      await expect(page.getByRole('tab', { name: /^Sources/ })).toHaveCount(0)
      await expect.poll(() => page.evaluate(() => window.location.hash)).toBe(`#/research/${rid}${canonical ? `/${canonical}` : ''}`)
    }
    // Without a panel the artifacts rail sits beside the thread.
    await expect(page.getByRole('complementary', { name: /^Artifacts/ })).toBeVisible()
  })

  test('the menu opens a panel at its heading; Escape and Close hand focus back to the opener', async () => {
    await page.goto(`${server.url()}/#/research/${rid}`)
    const sources = await openPanel(page, 'sources')
    await expect(sources.locator('#split-panel-title')).toBeFocused()
    await expect(page.getByRole('complementary', { name: /^Artifacts/ })).toHaveCount(0)
    await shot(page, 's7a-sources-panel')
    await page.keyboard.press('Escape')
    await expect(page.locator('[data-split-panel]')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Research actions' })).toBeFocused()
    expect(await page.evaluate(() => window.location.hash)).toBe(`#/research/${rid}`)

    // A count in the thread opens its panel; Close returns to that count.
    const included = page.locator('.research-facts button', { hasText: 'Unique works' })
    await included.click()
    await expect(panel(page, 'Sources')).toBeVisible()
    await panel(page, 'Sources').getByRole('button', { name: 'Close', exact: true }).click()
    await expect(page.locator('[data-split-panel]')).toHaveCount(0)
    await expect(included).toBeFocused()
  })

  test('a source opened from Sources stacks on it, and Back returns to Sources', async () => {
    await page.goto(`${server.url()}/#/research/${rid}/sources`)
    const sources = panel(page, 'Sources')
    await expect(sources).toBeVisible()
    await expect(sources.getByRole('button', { name: 'Back' })).toHaveCount(0)
    await sources.getByRole('button', { name: 'Read abstract' }).first().click()
    const details = panel(page, 'Source details')
    await expect(details).toBeVisible()
    await expect(details.locator('#split-panel-title')).toBeFocused()
    await expect(details.getByRole('heading', { name: 'Abstract' })).toBeVisible()
    // Sources stays the URL's panel while a source is stacked on it.
    expect(await page.evaluate(() => window.location.hash)).toBe(`#/research/${rid}/sources`)
    await shot(page, 's7a-source-details-stacked')
    await details.getByRole('button', { name: 'Back' }).click()
    await expect(panel(page, 'Sources')).toBeVisible()
    await expect(page.locator('[data-split-panel] #split-panel-title')).toBeFocused()
    await expect(panel(page, 'Source details')).toHaveCount(0)
    await expect(panel(page, 'Sources').getByRole('button', { name: 'Back' })).toHaveCount(0)

    // A panel opened from the menu over a stack stacks too; Close ends the whole stack.
    await panel(page, 'Sources').getByRole('button', { name: 'Read abstract' }).first().click()
    await expect(panel(page, 'Source details')).toBeVisible()
    await openPanel(page, 'activity')
    await panel(page, 'Activity').getByRole('button', { name: 'Back' }).click()
    await expect(panel(page, 'Source details')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.locator('[data-split-panel]')).toHaveCount(0)
  })

  test('Full width hides the thread; beside the panel the thread stays usable', async () => {
    await page.goto(`${server.url()}/#/research/${rid}/sources`)
    const sources = panel(page, 'Sources')
    await expect(sources).toBeVisible()
    const width = (await sources.boundingBox())!.width
    const thread = page.locator('.research-thread-col')
    // The panel takes 56% of the split; the thread is not inert and takes clicks.
    expect(width / ((await page.locator('.research-split').boundingBox())!.width)).toBeCloseTo(0.56, 1)
    await expect(thread).toBeVisible()
    expect(await thread.evaluate(el => (el as HTMLElement).inert)).toBe(false)
    await page.getByRole('button', { name: 'Revise question' }).click()
    await expect(page.locator('#revise-question')).toBeFocused()
    await expect(sources).toBeVisible()

    await sources.getByRole('button', { name: 'Full width' }).click()
    await expect(thread).toBeHidden()
    expect((await sources.boundingBox())!.width).toBeGreaterThan(width * 1.5)
    await shot(page, 's7a-wide')
    await sources.getByRole('button', { name: 'Exit full width' }).click()
    await expect(thread).toBeVisible()
    // Closing ends full width: the next panel opens at 56% again.
    await sources.getByRole('button', { name: 'Full width' }).click()
    await sources.getByRole('button', { name: 'Close', exact: true }).click()
    await openPanel(page, 'activity')
    await expect(thread).toBeVisible()
  })

  test('at 390px the panel is a full-screen modal dialog that keeps focus inside', async ({ browser }) => {
    const phone = await browser.newPage({ viewport: { width: 390, height: 844 } })
    try {
      await phone.goto(`${server.url()}/#/research/${rid}/sources`)
      const dialog = phone.getByRole('dialog', { name: 'Sources', exact: true })
      await expect(dialog).toBeVisible()
      await expect(dialog).toHaveAttribute('aria-modal', 'true')
      const box = (await dialog.boundingBox())!
      expect(box.x).toBe(0)
      expect(box.width).toBe(390)
      // Full width stays in the head as the mockup draws it.
      await expect(dialog.getByRole('button', { name: 'Full width' })).toBeVisible()
      await shot(phone, 's7a-phone-dialog')
      for (let i = 0; i < 40; i++) {
        await phone.keyboard.press(i % 7 === 6 ? 'Shift+Tab' : 'Tab')
        expect(await phone.evaluate(() => Boolean(document.activeElement?.closest('[data-split-panel]')))).toBe(true)
      }
      await dialog.getByRole('button', { name: 'Close', exact: true }).click()
      await expect(phone.locator('[data-split-panel]')).toHaveCount(0)
      expect(await focusedName(phone)).not.toBe('')
    } finally { await phone.close() }
  })
})
