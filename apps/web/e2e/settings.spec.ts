import { expect, test, type Page, type Route } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'

// UI parity S24: the Settings page (mockup ST1-ST11). One column in the mockup's order; the proxy line and the Scopus
// line are two measured facts (plan §2.3); usage rows come from stored model sessions and OpenAlex's last stored
// response; the language row switches the interface; a key field never shows a stored key. The proxy, Scopus, usage and
// key answers are route-simulated with SYNTHETIC values (the fixture server has no proxy, no Scopus key and no stored
// calls); every expected text is built from the simulated record, and every time shown is pinned.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

class SettingsServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-settings-'))
  constructor(readonly port: number) {}
  async start() {
    const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend') }
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`${this.url()}api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`settings fixture server on ${this.port} did not start`)
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
  url(hash = '') { return `http://127.0.0.1:${this.port}/${hash}` }
}

const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`), animations: 'disabled' })
// Times are pinned to 9:05 local so the lines never depend on when the run happens.
const PINNED = new Date(2026, 9, 14, 9, 5).toISOString()
const hhmm = (page: Page, iso: string) => page.evaluate(value => new Date(value).toLocaleTimeString(document.documentElement.lang === 'tr' ? 'tr-TR' : 'en-US', { hour: '2-digit', minute: '2-digit' }), iso)
const ADDRESS = 'https://login.proxy.example.edu/login?url='

type Test = Record<string, unknown>
const tested = (over: Test = {}): Test => ({ proxy_reachable: true, proxy_http_status: 302, proxy_error: null, proxy_error_detail: null, scopus_complete: 'could_not_check',
  scopus_configured: false, address: ADDRESS, route: 'SYNTHETIC-route', route_changed_during_test: false, tested_at: PINNED, ...over })

// The proxy endpoints the shell and the page read, as one SYNTHETIC store: a saved address, the test the next POST
// answers, and a gate that holds a POST open to show the checking state.
class ProxyStore {
  address: string | null = null
  test: Test | null = null
  next: Test | 'fail' = tested()
  gate: Promise<void> | null = null
  posts = 0
  view() {
    return { address: this.address, label: this.address ? 'login.proxy.example.edu' : null, label_default: this.address ? 'login.proxy.example.edu' : null,
      label_is_default: true, test: this.test, test_is_current: !!this.test && this.test.address === this.address }
  }
  async install(page: Page) {
    await page.route('**/api/institution-proxy/settings', route => route.fulfill({ json: this.view() }))
    await page.route('**/api/institution-proxy/test', async route => {
      this.posts++
      if (this.gate) await this.gate
      if (this.next === 'fail') return route.fulfill({ status: 500, json: { detail: 'SYNTHETIC test request failure' } })
      this.test = { ...this.next, address: this.address }
      await route.fulfill({ json: this.view() })
    })
    await page.route('**/api/institution-proxy', async (route: Route) => {
      if (route.request().method() === 'GET') return route.fulfill({ json: { address: this.address } })
      const body = route.request().postDataJSON() as { address: string }
      this.address = body.address || null
      this.test = null
      await route.fulfill({ json: { address: this.address } })
    })
  }
}

test.describe.serial('S24: the Settings page', () => {
  const server = new SettingsServer(nextPort())
  let page: Page

  test.beforeAll(async ({ browser }) => {
    await server.start()
    page = await browser.newPage()
  })
  test.afterAll(async () => { await page?.close(); await server.stop() })

  test('one page in the mockup order; the old Connections link opens it at "On this computer"', async () => {
    await page.goto(server.url('#/settings'))
    await expect(page.locator('.settings-page h2')).toHaveText(['Default models', 'Cloud models', 'On this computer', 'Semantic search', 'Institutional access',
      'Scholarly sources', 'Reference managers', 'Usage this month', 'Language'])
    await expect(page.getByRole('tab')).toHaveCount(0)
    const computer = page.locator('.grid3[data-group="computer"] .conn-name')
    await expect(computer).toHaveText(['Codex CLI', 'Claude Code', 'OCR (Tesseract)', 'Local model servers', 'Equation reader (Marker)'])
    // Scholarly sources: the mockup's five first, then the other registered connectors.
    const sources = page.locator('.grid3[data-group="sources"] .conn-name')
    await expect(sources.nth(0)).toHaveText('OpenAlex')
    await expect(sources.nth(1)).toHaveText('Semantic Scholar')
    await expect(sources.nth(2)).toHaveText('Crossref')
    await expect(sources.nth(3)).toHaveText('Scopus')
    await expect(sources.nth(4)).toHaveText('arXiv')
    await expect(page.locator('.grid3[data-group="references"] .conn-name')).toHaveText(['Zotero', 'BibTeX / RIS files'])
    await expect(page.locator('.settings-footer')).toContainText('© 2026 DEIXIS')

    await page.goto(server.url('#/settings/connections'))
    const heading = page.getByRole('heading', { name: 'On this computer' })
    await expect(heading).toBeFocused()
    expect((await heading.boundingBox())!.y).toBeLessThan(60)
    await shot(page, 'S24-settings-connections-desktop')
  })

  test('default models: role, description, model and effort; a saved default is the stored one', async () => {
    await page.goto(server.url('#/settings'))
    const rows = page.locator('.set-roles > div')
    await expect(rows.locator('b')).toHaveText(['Literature', 'Answer', 'Reviewer'])
    await expect(rows.locator('p')).toHaveText(['Plans searches and screens abstracts', 'Writes the source-linked answer', 'Checks each claim against its passages'])
    const literature = page.getByRole('combobox', { name: 'Literature model' })
    await expect(literature).toBeEnabled()
    const listed = await (await page.request.get(server.url('api/connections'))).json() as { models: Record<string, { models?: { id: string; display_name: string }[] }> }
    const [connection, health] = Object.entries(listed.models).find(([, h]) => (h.models ?? []).length > 0)!
    const model = health.models![0]
    await literature.selectOption({ label: model.display_name })
    await expect(page.getByText(`Default literature model: ${model.id}`)).toBeVisible()
    await page.reload()
    await expect(page.getByRole('combobox', { name: 'Literature model' })).toHaveValue(`${connection}:${model.id}`)
    await expect(page.getByRole('combobox', { name: 'Literature effort' })).toBeVisible()
  })

  test('proxy test states: reachable, did not answer, not asked, could not run, checking; Scopus is its own line', async () => {
    const store = new ProxyStore()
    let scopus = 'not_checked'
    await store.install(page)
    await page.route('**/api/institutional-access**', route => route.fulfill({ json: { status: scopus, via: 'scopus' } }))
    await page.goto(server.url('#/settings/access'))
    await expect(page.getByRole('heading', { name: 'Institutional access' })).toBeFocused()
    const state = page.locator('.proxy-state').first()
    const scopusLine = page.locator('.proxy-scopus')
    await expect(state).toHaveText('Not set upWithout a proxy, publisher links open directly.')
    await expect(scopusLine).toHaveText('Scopus check could not runNo Scopus key is set.')
    await expect(page.locator('.proxy').getByRole('button', { name: 'Remove' })).toHaveCount(0)

    // Test saves the typed address, then asks its host once; the answer is the stored test's.
    await page.getByLabel('Proxy address (EZproxy or OpenAthens prefix)').fill(ADDRESS)
    let release!: () => void
    store.gate = new Promise(resolve => { release = resolve })
    await page.locator('.proxy').getByRole('button', { name: 'Test' }).click()
    await expect(state).toHaveText('Checking: asking the proxy host…')
    await expect(page.locator('.proxy').getByRole('button', { name: 'Test' })).toBeDisabled()
    release(); store.gate = null
    const time = await hhmm(page, PINNED)
    await expect(state).toHaveText(`Proxy reachableArticle access not checked. The proxy host answered with HTTP 302 at ${time}.`)
    expect(store.address).toBe(ADDRESS)
    // The sidebar's access line shows the same fact, and neither says more than was measured.
    await expect(page.locator('.sidebar-foot .access')).toContainText('Proxy reachable · article access not checked')
    for (const word of ['Working', 'VPN required', 'Access uncertain', 'Opened a test article']) await expect(page.locator('.settings-page')).not.toContainText(word)
    await shot(page, 'S24-proxy-reachable-desktop')

    const again = async (next: Test | 'fail') => {
      store.next = next
      await page.locator('.proxy').getByRole('button', { name: 'Test' }).click()
    }
    await again(tested({ proxy_reachable: false, proxy_http_status: null, proxy_error: 'timeout' }))
    await expect(state).toHaveText(`Proxy did not answerNo answer within 10 seconds. Checked at ${time}.`)
    await again(tested({ proxy_reachable: false, proxy_http_status: null, proxy_error: 'unresolved', proxy_error_detail: 'host does not resolve' }))
    await expect(state).toHaveText(`Proxy did not answerIts host name does not resolve on this network. Checked at ${time}.`)
    await again(tested({ proxy_reachable: false, proxy_http_status: null, proxy_error: 'blocked_url', proxy_error_detail: 'SYNTHETIC private address' }))
    await expect(state).toHaveText('Proxy not askedThe address was refused before any request was sent: SYNTHETIC private address')
    await again('fail')
    await expect(state).toContainText('Proxy check could not runThe check could not run:')

    // Scopus's full-view check is a second fact with its own words.
    for (const [status, text] of [['institutional', 'Scopus full view confirmedScopus grants its full view on this network.'],
      ['none', 'Scopus full view not confirmedScopus did not grant its full view on this network.'],
      ['unknown', 'Scopus check could not runScopus gave no usable answer.']] as const) {
      scopus = status
      await page.reload()
      await expect(scopusLine).toHaveText(text)
    }

    // Remove clears the address; the line says what that means.
    await page.locator('.proxy').getByRole('button', { name: 'Remove' }).click()
    await expect(page.getByText('Proxy address removed. Links open directly.')).toBeVisible()
    await expect(state).toHaveText('Not set upWithout a proxy, publisher links open directly.')
    await page.unrouteAll({ behavior: 'ignoreErrors' })
  })

  test('usage rows: calls per role from stored sessions, bar = share; OpenAlex from its last stored response; unknown is "not known"', async () => {
    const usage = { period: 'month', since: new Date(2026, 9, 1).toISOString(), until: new Date(2026, 10, 1).toISOString(), as_of: PINNED, total: 20,
      roles: [{ role: 'answer', calls: 6, share: 0.3 }, { role: 'literature', calls: 13, share: 0.65 }, { role: 'reviewer', calls: 1, share: 0.05 }] }
    let budget: Record<string, unknown> = { provider: 'openalex', unit: 'credits', remaining: 620, limit: 1000, used_fraction: 0.38, reset_at: PINNED, as_of: PINNED, source: 'last_stored_response' }
    let usageFails = false
    await page.route('**/api/usage?period=month', route => usageFails ? route.fulfill({ status: 500, json: { detail: 'SYNTHETIC usage failure' } }) : route.fulfill({ json: usage }))
    await page.route('**/api/openalex/budget-today', route => route.fulfill({ json: budget }))
    await page.goto(server.url('#/settings'))
    const time = await hhmm(page, PINNED)
    for (const row of usage.roles) {
      const line = page.locator(`.set-usage [data-role="${row.role}"]`)
      await expect(line.locator('p')).toHaveText(`${row.calls} ${row.calls === 1 ? 'call' : 'calls'}`)
      await expect(line.locator('.bar i')).toHaveAttribute('style', new RegExp(`width: ${Math.round(row.share * 100)}%`))
    }
    await expect(page.locator('.set-usage > div > b')).toHaveText(['Literature model', 'Answer model', 'Reviewer model', 'OpenAlex today'])
    const openalex = page.locator('.set-usage [data-role="openalex"]')
    await expect(openalex.locator('p')).toHaveText(`38% of budgetLast stored response, ${time}`)
    await expect(openalex.locator('.bar i')).toHaveAttribute('style', /width: 38%/)
    await page.locator('.set-usage').scrollIntoViewIfNeeded()
    await shot(page, 'S24-usage-desktop')

    // No limit header: what is left in OpenAlex's own unit, and no bar (there is no denominator).
    budget = { ...budget, unit: 'usd', remaining: 1.25, limit: null, used_fraction: null }
    await page.reload()
    await expect(openalex.locator('p')).toHaveText(`$1.25 left todayLast stored response, ${time}`)
    await expect(openalex.locator('.bar')).toHaveCSS('visibility', 'hidden')
    // Nothing stored since the reset: not known, never 0.
    budget = { ...budget, unit: null, remaining: null, as_of: null, reset_at: null }
    await page.reload()
    await expect(openalex.locator('p')).toHaveText('not knownNo OpenAlex response stored today')

    // A failed read says so and keeps the rows unknown; Try again reads them.
    usageFails = true
    await page.reload()
    await expect(page.getByRole('alert').filter({ hasText: 'Usage could not be read' })).toBeVisible()
    await expect(page.locator('.set-usage [data-role="literature"] p')).toHaveText('not known')
    usageFails = false
    await page.getByRole('alert').filter({ hasText: 'Usage could not be read' }).getByRole('button', { name: 'Try again' }).click()
    await expect(page.locator('.set-usage [data-role="literature"] p')).toHaveText('13 calls')
    await page.unrouteAll({ behavior: 'ignoreErrors' })
  })

  test('language row: English / Türkçe switches the interface', async () => {
    await page.goto(server.url('#/settings'))
    const group = page.getByRole('group', { name: 'Interface language' })
    await expect(group.getByRole('button', { name: 'English' })).toHaveAttribute('aria-pressed', 'true')
    await expect(page.locator('.settings-page .rows').last()).toContainText('Research content (questions, answers, quotes) stays in the language it was written in.')
    await group.getByRole('button', { name: 'Türkçe' }).click()
    await expect(page.locator('html')).toHaveAttribute('lang', 'tr')
    await expect(page.locator('.settings-page h1')).toHaveText('Ayarlar')
    await expect(page.getByRole('group', { name: 'Arayüz dili' }).getByRole('button', { name: 'Türkçe' })).toHaveAttribute('aria-pressed', 'true')
    await page.getByRole('group', { name: 'Arayüz dili' }).getByRole('button', { name: 'English' }).click()
    await expect(page.locator('html')).toHaveAttribute('lang', 'en')
    await expect(page.locator('.settings-page h1')).toHaveText('Settings')
  })

  test('connection sheet: a key field never shows the stored key; Save and test, Remove key with its inline confirmation', async () => {
    const keychain = { available: true, name: 'SYNTHETIC keychain' }
    let configured = false
    let hold: Promise<void> | null = null
    const entry = () => ({ env: 'OPENAI_API_KEY', group: 'model', service: 'openai', configured, source: configured ? 'keychain' : null, testable: true })
    const listed = await (await page.request.get(server.url('api/credentials'))).json() as { keys: { env: string }[] }
    await page.route('**/api/credentials', route => route.fulfill({ json: { keychain, keys: listed.keys.map(k => k.env === 'OPENAI_API_KEY' ? entry() : k) } }))
    await page.route('**/api/credentials/OPENAI_API_KEY', async route => {
      if (hold) await hold
      configured = route.request().method() === 'PUT'
      await route.fulfill({ json: { key: entry(), test: configured ? { status: 'ok', detail: '', checked_at: PINNED } : null } })
    })
    await page.goto(server.url('#/settings'))
    await page.getByRole('button', { name: /^OpenAI API Not set up/ }).click()
    const sheet = page.getByRole('dialog', { name: 'OpenAI API' })
    const field = sheet.getByLabel('API key')
    await expect(field).toHaveValue('')
    await expect(field).toHaveAttribute('type', 'password')
    await expect(field).toHaveAttribute('placeholder', 'Paste your key')
    await field.fill('SYNTHETIC-not-a-key')
    let release!: () => void
    hold = new Promise(resolve => { release = resolve })
    await sheet.getByRole('button', { name: 'Save and test' }).click()
    await expect(sheet.getByRole('button', { name: 'Testing and saving…' })).toBeDisabled()
    release(); hold = null
    await expect(page.getByText('Key saved.')).toBeVisible()
    // Saved: the field is empty again and says where the key is kept, without any of it.
    await expect(field).toHaveValue('')
    await expect(field).toHaveAttribute('placeholder', /stored in SYNTHETIC keychain$/)
    expect(await sheet.innerText()).not.toContain('SYNTHETIC-not-a-key')
    await expect(sheet.getByRole('button', { name: 'Test' })).toBeVisible()
    await sheet.getByRole('button', { name: 'Remove key' }).click()
    const confirm = sheet.getByRole('group', { name: 'Remove the key' })
    await expect(confirm).toContainText('Remove the key for OpenAI? Semantic search with OpenAI stops until a new key is added.')
    await confirm.getByRole('button', { name: 'Keep it' }).click()
    await expect(confirm).toHaveCount(0)
    await sheet.getByRole('button', { name: 'Remove key' }).click()
    await sheet.getByRole('group', { name: 'Remove the key' }).getByRole('button', { name: 'Remove' }).click()
    await expect(page.getByText('Key removed.')).toBeVisible()
    await expect(field).toHaveAttribute('placeholder', 'Paste your key')
    await sheet.getByRole('button', { name: 'Close' }).click()
    await page.unrouteAll({ behavior: 'ignoreErrors' })
  })

  test('effort keeps "Model default", and a connection test refreshes the default model list (Sol r1 backlog)', async () => {
    // SYNTHETIC connections: Codex lists one model with two thinking levels; a fresh test of Codex lists a second one.
    const efforts = [{ id: 'low', description: '' }, { id: 'high', description: '' }]
    const first = { id: 'syn-model-a', display_name: 'SYNTHETIC model A', is_default: true, reasoning_efforts: efforts }
    const second = { id: 'syn-model-b', display_name: 'SYNTHETIC model B', is_default: false, reasoning_efforts: efforts }
    let tested = false
    const codex = () => ({ connection: 'codex', ready: true, reason: null, installed: true, signed_in: true, models: tested ? [first, second] : [first] })
    await page.route(url => url.pathname === '/api/connections', async route => {
      const response = await route.fetch()
      const body = await response.json() as { models: Record<string, unknown> }
      await route.fulfill({ response, json: { ...body, models: { ...body.models, codex: codex() } } })
    })
    await page.route(url => url.pathname === '/api/connections/codex', route => { tested = true; return route.fulfill({ json: codex() }) })
    const saved: Record<string, unknown>[] = []
    await page.route(url => url.pathname === '/api/settings/literature', route => {
      const body = route.request().postDataJSON() as Record<string, unknown>
      saved.push(body)
      return route.fulfill({ json: { literature: body } })
    })
    await page.goto(server.url('#/settings'))
    await page.reload()
    const model = page.getByRole('combobox', { name: 'Literature model' })
    const effort = page.getByRole('combobox', { name: 'Literature effort' })
    await expect(model).toBeEnabled()
    await expect(model.locator('option', { hasText: 'SYNTHETIC model B' })).toHaveCount(0)
    await model.selectOption({ label: 'SYNTHETIC model A' })
    await expect(effort).toBeEnabled()
    await effort.selectOption('high')
    await expect.poll(() => saved.at(-1)?.reasoning_effort).toBe('high')
    // The nullable choice is still there after a level is chosen, and choosing it saves no level.
    await expect(effort.locator('option')).toHaveText(['Model default', 'Low', 'High'])
    await effort.selectOption({ label: 'Model default' })
    await expect.poll(() => saved.at(-1)?.reasoning_effort ?? 'none').toBe('none')
    // A connection test in the Codex sheet reads the model list again; the default model choices follow it.
    await page.getByRole('button', { name: /^Codex CLI / }).click()
    const sheet = page.getByRole('dialog', { name: 'Codex CLI' })
    await sheet.getByRole('button', { name: 'Test the connection' }).click()
    await expect(sheet.locator('.dmeta')).toContainText('checked')
    await sheet.getByRole('button', { name: 'Close' }).click()
    await expect(model.locator('option', { hasText: 'SYNTHETIC model B' })).toHaveCount(1)
    await page.unrouteAll({ behavior: 'ignoreErrors' })
  })

  test('a failed check says it could not check and adds no new time (Sol r1)', async () => {
    let fail = false
    await page.route(url => url.pathname === '/api/ocr', route => fail ? route.fulfill({ status: 500, json: { detail: 'SYNTHETIC OCR check failure' } }) : route.fallback())
    await page.goto(server.url('#/settings'))
    await page.reload()
    await page.getByRole('button', { name: /^OCR \(Tesseract\)/ }).click()
    const sheet = page.getByRole('dialog', { name: 'OCR (Tesseract)' })
    const find = sheet.getByRole('button', { name: 'Find it on this computer' })
    await find.click()
    await expect(sheet.locator('.dmeta')).toContainText(/checked \d/)
    const pill = await sheet.locator('.dmeta > span').first().innerText()
    fail = true
    await find.click()
    await expect(sheet.locator('.dmeta .check-failed')).toHaveText(/^Could not check: .*SYNTHETIC OCR check failure/)
    await expect(sheet.locator('.dmeta')).not.toContainText(/checked \d/)
    // The state shown is still the last one read; nothing new is claimed.
    await expect(sheet.locator('.dmeta > span').first()).toHaveText(pill)
    fail = false
    await find.click()
    await expect(sheet.locator('.dmeta')).toContainText(/checked \d/)
    await expect(sheet.locator('.dmeta .check-failed')).toHaveCount(0)
    await sheet.getByRole('button', { name: 'Close' }).click()
    await page.unrouteAll({ behavior: 'ignoreErrors' })
  })

  test('a semantic search read that started before a save does not undo the saved choice on screen (Sol r1)', async () => {
    // SYNTHETIC semantic search state: OpenAI and Off can be chosen; nothing is saved yet.
    const option = (provider: string, available: boolean) => ({ provider, models: provider === 'openai' ? ['text-embedding-3-small'] : [], available, reason: available ? null : 'SYNTHETIC not available' })
    const view = (provider: string, explicit: boolean) => ({ provider, model: provider === 'openai' ? 'text-embedding-3-small' : null, explicit,
      options: [option('builtin', false), option('openai', true), option('gemini', false), option('ollama', false), option('lm_studio', false), option('off', true)] })
    let release: () => void = () => {}
    const held = new Promise<void>(resolve => { release = resolve })
    let reads = 0
    await page.route(url => url.pathname === '/api/semantic-search', async route => {
      if (route.request().method() === 'PUT') {
        const body = route.request().postDataJSON() as { provider: string }
        return route.fulfill({ json: view(body.provider, true) })
      }
      reads++
      if (reads === 1) return route.fulfill({ json: view('off', false) })
      await held  // a later read answers with the state from before the save
      return route.fulfill({ json: view('off', false) })
    })
    await page.goto(server.url('#/settings'))
    await page.reload()
    const off = page.locator('.semantic-option[data-row="off"] input')
    await expect(off).toBeChecked()
    // The local server sheet's Test reads semantic search again; that read is held open.
    await page.getByRole('button', { name: /^Local model servers/ }).click()
    const sheet = page.getByRole('dialog', { name: 'Local model servers' })
    await sheet.getByRole('button', { name: 'Test' }).click()
    await expect.poll(() => reads).toBe(2)
    await page.keyboard.press('Escape')
    await expect(sheet).toHaveCount(0)
    await page.locator('.semantic-option[data-row="openai"] input').click()
    await expect(page.getByText('Semantic search setting saved.')).toBeVisible()
    release()
    await page.waitForTimeout(500)
    await expect(page.locator('.semantic-option[data-row="openai"] input')).toBeChecked()
    await expect(page.locator('.semantic-privacy')).toHaveText('Passage text is sent to OpenAI.')
    await page.unrouteAll({ behavior: 'ignoreErrors' })
  })

  test('Sign in again shows the command with Copy; it opens nothing', async () => {
    await page.goto(server.url('#/settings/connections'))
    await page.getByRole('button', { name: /^Codex CLI / }).click()
    const sheet = page.getByRole('dialog', { name: 'Codex CLI' })
    await sheet.getByRole('button', { name: 'Sign in again' }).click()
    // The command names the Codex home this backend runs with (here the fixture data folder's), never a fixed macOS path.
    const home = (await (await page.request.get(server.url('api/connections'))).json() as { codex_home: string }).codex_home
    expect(home.endsWith(`${path.basename(server.dataDir)}/codex-home`)).toBe(true)
    await expect(sheet.locator('.cmd-row code')).toHaveText(`CODEX_HOME='${home}' codex login`)
    await expect(sheet.locator('.cmd-row').getByRole('button', { name: 'Copy' })).toBeVisible()
    await shot(page, 'S24-codex-sheet-desktop')
    await sheet.getByRole('button', { name: 'Close' }).click()
  })

  test('BibTeX / RIS files import into the Library and report what the server stored', async () => {
    await page.goto(server.url('#/settings'))
    await page.getByRole('button', { name: /^BibTeX \/ RIS files/ }).click()
    const sheet = page.getByRole('dialog', { name: 'BibTeX / RIS files' })
    const bib = '@article{syn1,\n  title = {SYNTHETIC imported settings work one},\n  author = {Doe, Jane},\n  year = {2021}\n}\n\n@article{syn2,\n  title = {SYNTHETIC imported settings work two},\n  author = {Roe, Rick},\n  year = {2022}\n}\n'
    const file = { name: 'SYNTHETIC-settings.bib', mimeType: 'text/plain', buffer: Buffer.from(bib) }
    await sheet.locator('input[type=file]').setInputFiles(file)
    const result = sheet.locator('.reference-result')
    await expect(result).toContainText('SYNTHETIC-settings.bib: 2 entries read. 2 saved to the Library, 0 were already there.')
    await expect(result).toContainText('0 matched a provider record by DOI; 2 kept as your own records, not confirmed by a provider.')
    await sheet.locator('input[type=file]').setInputFiles(file)
    await expect(result).toContainText('SYNTHETIC-settings.bib: 2 entries read. 0 saved to the Library, 2 were already there.')
    await sheet.getByRole('button', { name: 'Close' }).click()
  })

  test('phone: one column of tiles, no horizontal scroll', async () => {
    await expect(page.locator('.connection-sheet')).toHaveCount(0)
    await page.setViewportSize({ width: 390, height: 844 })
    // A hash-only goto keeps the page; reload so the phone layout is built from the start.
    await page.goto(server.url('#/settings'))
    await page.reload()
    await expect(page.getByRole('combobox', { name: 'Literature model' })).toBeEnabled()
    const columns = await page.locator('.settings-page .grid3').first().evaluate(el => getComputedStyle(el).gridTemplateColumns.split(' ').length)
    expect(columns).toBe(1)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await shot(page, 'S24-settings-phone')
    await page.setViewportSize({ width: 1280, height: 900 })
  })
})
