import { expect, request as apiRequest, test, type APIRequestContext, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort, readingDone } from './ports'
import { panel, reportPanel, sourcePanel } from './panels'
import { chooseLanguage } from './language'

// UI parity S3: the shortcut layer (mockup keydown handler, O3), the keys dialog (O2) and the search palette (O1).
// Single keys S R T Q P open a research page's panels, N and L go to New research and the Library, `[` shows or hides
// the sidebar, `?` opens the keys dialog, Esc closes the open panel. They are off inside text fields, and the keys
// dialog's switch turns them off across reloads (WCAG 2.1.4). The mockup's F (search funnel) has no target yet.
//
// Its own fixture server with the queue fixture, so the research has sources, queue rows and an answer. Every record is
// SYNTHETIC; a passing case shows how the page behaves, not the quality of a search or an answer.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

const QUESTION = '[queue] How do SYNTHETIC molecular relays and greenhouse irrigation schedule their releases?'

class KeysServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-keys-'))
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
    throw new Error(`keys fixture server on ${this.port} did not start`)
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
const hash = (page: Page) => page.evaluate(() => window.location.hash)
const palette = (page: Page) => page.getByRole('dialog', { name: 'Search', exact: true })
const keysDialog = (page: Page) => page.getByRole('dialog', { name: 'Shortcuts', exact: true })

test.describe.serial('S3: shortcuts, keys dialog, palette', () => {
  const server = new KeysServer(nextPort(), { DEIXIS_FIXTURE_QUEUE: 'on' })
  let api: Api
  let rid = ''
  let page: Page
  const research = () => `${server.url()}/#/research/${rid}`

  test.beforeAll(async ({ browser }) => {
    await server.start()
    const context = await apiRequest.newContext({ baseURL: server.url(), extraHTTPHeaders: { origin: server.url() } })
    api = { context, token: (await (await context.get('/api/session')).json()).csrf_token as string }
    const created = await post(api, '/api/researches', { question: QUESTION, model_connection: 'codex', requested_model: 'fixture-model', effort: 'quick' })
    expect(created.status()).toBe(201)
    rid = (await created.json()).research.id
    expect((await post(api, `/api/researches/${rid}/runs`, { kind: 'discovery' })).ok()).toBe(true)
    await expect.poll(async () => readingDone(await viewOf(api, rid)), { timeout: 90_000 }).toBe(true)
    // The answer run is queued when discovery completes; R opens its report.
    await expect.poll(async () => (await viewOf(api, rid)).answers.length, { timeout: 90_000 }).toBeGreaterThan(0)
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  })
  test.afterAll(async () => { await page?.close(); await api?.context.dispose(); await server.stop() })

  test('S R T Q P open the research panels and the report; Esc closes the panel from the thread', async () => {
    await page.goto(research())
    await expect(page.locator('.research-thread')).toBeVisible()
    await expect(page.locator('[data-split-panel]')).toHaveCount(0)
    const cases: [string, string | RegExp, string][] = [
      ['s', 'Sources', 'sources'], ['q', /^Awaiting your decision \(\d+\)$/, 'queue'], ['p', 'Get more full text', 'pdfs'], ['t', 'Evidence table', 'table'],
    ]
    for (const [key, title, segment] of cases) {
      await page.keyboard.press(key)
      const opened = panel(page, title)
      await expect(opened, `${key} opens its panel`).toBeVisible()
      await expect(opened.locator('#split-panel-title'), `${key}: the panel's heading has focus`).toBeFocused()
      // Each key starts a new stack (mockup `openPanel(…, false)`), so there is no Back.
      await expect(opened.getByRole('button', { name: 'Back', exact: true })).toHaveCount(0)
      await expect.poll(() => hash(page)).toBe(`#/research/${rid}/${segment}`)
    }
    await page.keyboard.press('r')
    const report = reportPanel(page)
    await expect(report, 'R opens the shown answer’s report').toBeVisible()
    // A new stack like the other keys: the Evidence table open before is not below it.
    await expect(report.getByRole('button', { name: 'Back', exact: true })).toHaveCount(0)
    await shot(page, 's3-report-by-key')
    // Report → a cited source's details stacked on it → R brings the report back in front, as a new stack.
    await report.locator('.reference-list li').getByRole('button').first().click()
    await expect(sourcePanel(page)).toBeVisible()
    await expect(report).toHaveCount(0)
    await page.keyboard.press('r')
    await expect(reportPanel(page), 'R returns to the report over its source details').toBeVisible()
    await expect(reportPanel(page).locator('#split-panel-title')).toBeFocused()
    await expect(sourcePanel(page)).toHaveCount(0)
    await expect(reportPanel(page).getByRole('button', { name: 'Back', exact: true })).toHaveCount(0)
    // The same from the palette's Open report row.
    await reportPanel(page).locator('.reference-list li').getByRole('button').first().click()
    await expect(sourcePanel(page)).toBeVisible()
    await page.keyboard.press('ControlOrMeta+k')
    await palette(page).getByRole('option', { name: 'Open report' }).click()
    await expect(reportPanel(page)).toBeVisible()
    await expect(sourcePanel(page)).toHaveCount(0)

    // Escape from the thread (outside the panel) closes it, as Escape inside the panel already did.
    await page.keyboard.press('s')
    await expect(panel(page, 'Sources')).toBeVisible()
    await page.getByRole('heading', { level: 1 }).click()
    await page.keyboard.press('Escape')
    await expect(page.locator('[data-split-panel]')).toHaveCount(0)
  })

  test('N, L, [ and ? work anywhere', async () => {
    await page.goto(research())
    await expect(page.locator('.research-thread')).toBeVisible()
    await page.keyboard.press('l')
    await expect.poll(() => hash(page)).toBe('#/library')
    await page.keyboard.press('n')
    await expect.poll(() => hash(page)).toBe('#/')
    await expect(page.getByLabel('Research question')).toBeVisible()
    // Research keys do nothing on another page.
    await page.keyboard.press('s')
    await expect.poll(() => hash(page)).toBe('#/')

    const app = page.locator('.app')
    await expect(app).not.toHaveClass(/sidebar-collapsed/)
    await page.keyboard.press('[')
    await expect(app).toHaveClass(/sidebar-collapsed/)
    await page.keyboard.press('[')
    await expect(app).not.toHaveClass(/sidebar-collapsed/)

    await page.keyboard.press('?')
    const dialog = keysDialog(page)
    await expect(dialog).toBeVisible()
    await expect(dialog.locator('.keys-heading')).toHaveText(['Anywhere', 'On a research', 'In a text box'])
    await expect(dialog.locator('.keys-heading > span').first()).toHaveCSS('text-transform', 'uppercase')
    const rows = await dialog.locator('.keys > span:not(.keys-keys)').allTextContents()
    expect(rows).toEqual(['Search and commands', 'Keyboard shortcuts', 'New research', 'Library', 'Show or hide the sidebar', 'Close panel or dialog',
      'Sources', 'Report', 'Evidence table', 'Awaiting your decision', 'Get more full text', 'Start research (home)'])
    await expect(dialog.getByRole('checkbox', { name: 'Single-key shortcuts' })).toBeChecked()
    await shot(page, 's3-keys-dialog')
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)

    // The sidebar button opens the same dialog and gets focus back when it closes.
    const button = page.getByRole('button', { name: 'Shortcuts', exact: true })
    await button.click()
    await expect(keysDialog(page)).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(keysDialog(page)).toHaveCount(0)
    await expect(button).toBeFocused()
  })

  test('single keys are off inside text fields and while a dialog is open', async () => {
    await page.goto(`${server.url()}/#/`)
    const question = page.getByLabel('Research question')
    await question.click()
    await page.keyboard.type('nls?[')
    await expect(question).toHaveValue('nls?[')
    expect(await hash(page)).toBe('#/')
    await expect(keysDialog(page)).toHaveCount(0)
    await expect(page.locator('.app')).not.toHaveClass(/sidebar-collapsed/)
    await question.fill('')

    await page.goto(`${research()}/sources`)
    const filter = panel(page, 'Sources').getByRole('searchbox', { name: 'Filter sources' })
    await filter.click()
    await page.keyboard.type('qpt')
    await expect(filter).toHaveValue('qpt')
    await expect(panel(page, 'Sources')).toBeVisible()

    // The palette keeps its keys: L typed into it does not leave for the Library.
    await page.keyboard.press('ControlOrMeta+k')
    await expect(palette(page)).toBeVisible()
    await page.keyboard.type('l')
    await expect(palette(page).getByRole('combobox')).toHaveValue('l')
    expect(await hash(page)).toBe(`#/research/${rid}/sources`)
    await page.keyboard.press('Escape')
    await expect(palette(page)).toHaveCount(0)
  })

  test('the off switch turns single keys off and stays off after a reload', async () => {
    await page.goto(research())
    await expect(page.locator('.research-thread')).toBeVisible()
    await page.getByRole('button', { name: 'Shortcuts', exact: true }).click()
    const toggle = keysDialog(page).getByRole('checkbox', { name: 'Single-key shortcuts' })
    await toggle.uncheck()
    await page.keyboard.press('Escape')
    await expect(keysDialog(page)).toHaveCount(0)
    await page.keyboard.press('l')
    await page.keyboard.press('s')
    await page.keyboard.press('?')
    expect(await hash(page)).toBe(`#/research/${rid}`)
    await expect(page.locator('[data-split-panel]')).toHaveCount(0)
    await expect(keysDialog(page)).toHaveCount(0)

    await page.reload()
    await expect(page.locator('.research-thread')).toBeVisible()
    await page.keyboard.press('l')
    await page.keyboard.press('?')
    expect(await hash(page)).toBe(`#/research/${rid}`)
    await expect(keysDialog(page)).toHaveCount(0)
    // ⌘K / Ctrl K is not a single key: it still opens the palette, which offers no letter for a key that is off.
    await page.keyboard.press('ControlOrMeta+k')
    await expect(palette(page)).toBeVisible()
    await expect(palette(page).getByRole('option', { name: 'Open sources' }).locator('em')).toHaveCount(0)
    await page.keyboard.press('Escape')

    await page.getByRole('button', { name: 'Shortcuts', exact: true }).click()
    await expect(toggle).not.toBeChecked()
    await toggle.check()
    await page.keyboard.press('Escape')
    await expect(keysDialog(page)).toHaveCount(0)
    await page.keyboard.press('l')
    await expect.poll(() => hash(page)).toBe('#/library')
  })

  test('the palette: groups, keys, commands and search results', async () => {
    await page.goto(research())
    await expect(page.locator('.research-thread')).toBeVisible()
    await page.keyboard.press('ControlOrMeta+k')
    const dialog = palette(page)
    await expect(dialog).toBeVisible()
    const field = dialog.getByRole('combobox')
    await expect(field).toHaveAttribute('placeholder', 'Search research, library, or type a command…')
    await expect(field).toBeFocused()
    // 560px at 14vh (mockup `.pal` in `.scrim`).
    const box = (await page.locator('.quick-find').boundingBox())!
    expect(Math.round(box.width)).toBe(560)
    expect(Math.abs(box.y - 140)).toBeLessThanOrEqual(1)
    const groups = dialog.locator('.quick-find-group')
    await expect(groups).toHaveText(['On this page', 'Recent research', 'Go to'])
    await expect(groups.first().locator('span')).toHaveCSS('text-transform', 'uppercase')
    const options = (group: string) => dialog.locator(`[role=group][aria-labelledby="qf-group-${group}"] [role=option]`)
    await expect(options('Page').locator('strong')).toHaveText(['Open sources', 'Open report', 'Awaiting your decision', 'Get more full text', 'Toggle dark mode'])
    await expect(options('Page').locator('em')).toHaveText(['S', 'R', 'Q', 'P'])
    await expect(options('Research').locator('em').first()).toHaveText('Research')
    await expect(options('Pages').locator('strong')).toHaveText(['New research', 'Library', 'Settings', 'Keyboard shortcuts'])
    await expect(options('Pages').locator('em')).toHaveText(['N', 'L', '?'])
    await expect(dialog.locator('.quick-find-foot')).toHaveText('↑↓ navigate↵ openesc close')
    // No language command in the default view.
    await expect(dialog.getByRole('option', { name: 'Türkçe' })).toHaveCount(0)
    await shot(page, 's3-palette')

    // A command opens its panel; the opener gets focus back when the panel closes.
    await dialog.getByRole('option', { name: 'Open sources' }).click()
    await expect(dialog).toHaveCount(0)
    await expect(panel(page, 'Sources')).toBeVisible()
    await expect(panel(page, 'Sources').locator('#split-panel-title')).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(page.locator('[data-split-panel]')).toHaveCount(0)

    // Keyboard shortcuts opens the keys dialog in the palette's place.
    await page.keyboard.press('ControlOrMeta+k')
    await dialog.getByRole('option', { name: 'Keyboard shortcuts' }).click()
    await expect(keysDialog(page)).toBeVisible()
    await expect(palette(page)).toHaveCount(0)
    await page.keyboard.press('Escape')

    // Typing filters the commands and lists the research and sources /api/search finds.
    await page.keyboard.press('ControlOrMeta+k')
    await field.fill('SYNTHETIC')
    await expect(options('Research').first()).toBeVisible()
    await expect(dialog.locator('#qf-group-Research')).toHaveText('Research')
    await expect(options('Page')).toHaveCount(0)
    await field.fill('libr')
    await expect(options('Pages').locator('strong')).toHaveText(['Library'])
    await page.keyboard.press('Enter')
    await expect.poll(() => hash(page)).toBe('#/library')

    // Away from a research the page has only the theme command.
    await page.keyboard.press('ControlOrMeta+k')
    await expect(options('Page').locator('strong')).toHaveText(['Toggle dark mode'])
    const dark = await page.locator('html').evaluate(el => el.classList.contains('dark'))
    await dialog.getByRole('option', { name: 'Toggle dark mode' }).click()
    await expect(page.locator('html')).toHaveClass(dark ? /^(?!.*\bdark\b)/ : /\bdark\b/)
    await page.keyboard.press('ControlOrMeta+k')
    await dialog.getByRole('option', { name: 'Toggle dark mode' }).click()
    await expect(page.locator('html')).toHaveClass(dark ? /\bdark\b/ : /^(?!.*\bdark\b)/)
  })

  test('the language command appears only when the query asks for it', async () => {
    await page.goto(`${server.url()}/#/`)
    await page.keyboard.press('ControlOrMeta+k')
    const dialog = palette(page)
    await expect(dialog.getByRole('option', { name: 'English' })).toHaveCount(0)
    await dialog.getByRole('combobox').fill('lang')
    await expect(dialog.locator('#qf-group-Language')).toHaveText('Language')
    await expect(dialog.getByRole('option', { name: 'Türkçe', exact: true })).toBeVisible()
    await dialog.getByRole('option', { name: 'Türkçe', exact: true }).click()
    await expect(page.locator('html')).toHaveAttribute('lang', 'tr')
    await page.keyboard.press('?')
    await expect(page.getByRole('dialog', { name: 'Kısayollar' })).toBeVisible()
    await expect(page.getByRole('dialog', { name: 'Kısayollar' }).locator('.keys-heading')).toHaveText(['Her yerde', 'Bir araştırmada', 'Bir metin kutusunda'])
    await page.keyboard.press('Escape')
    await chooseLanguage(page, 'en')
    await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  })
})
