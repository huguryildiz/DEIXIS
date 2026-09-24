import { expect, request as apiRequest, test, type APIRequestContext, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

// Case J: the human queue of an sw research (slice 17, D97). A person sees the works the reading could not settle,
// opens a row's page, and answers; an answer can be taken back, a row that moved is refused, and the list follows the
// event stream.
//
// Its own fixture server, with retrieval and reading switched on (DEIXIS_FIXTURE_QUEUE) and four SYNTHETIC works the
// scripted reading model answers so that each gives one row kind. A second server, the one A–G use, holds a legacy
// research. A passing case shows application behavior, not whether a person reads a paper well.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

const QUESTION = '[queue] How do SYNTHETIC molecular relays and greenhouse irrigation schedule their releases?'
const TITLES = {
  choose_run: 'SYNTHETIC bisection release scheduling for molecular relay networks',
  confirm_quote: 'SYNTHETIC moisture threshold irrigation of greenhouse benches',
  find_part: 'SYNTHETIC greedy release slots for molecular relays',
  confirm_pdf: 'SYNTHETIC drip irrigation timing in tomato greenhouses',
}

class QueueServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-queue-'))
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
    throw new Error(`queue fixture server on ${this.port} did not start`)
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

// The API as another tab would use it: its own cookie jar and CSRF token, so the page's session is not touched.
async function apiOf(server: QueueServer) {
  const context = await apiRequest.newContext({ baseURL: server.url(), extraHTTPHeaders: { origin: server.url() } })
  const token = (await (await context.get('/api/session')).json()).csrf_token as string
  return { context, token }
}
type Api = { context: APIRequestContext; token: string }
const post = (api: Api, url: string, data: unknown) => api.context.post(url, { data, headers: { 'x-deixis-csrf': api.token } })

async function createResearch(api: Api, question: string) {
  const created = await post(api, '/api/researches', { question, model_connection: 'codex', requested_model: 'fixture-model', effort: 'quick' })
  expect(created.status()).toBe(201)
  return (await created.json()).research.id as string
}

type Row = { source_version_id: string; work_id: string; kind: string; title: string; row_token: string }
const queueOf = async (api: Api, rid: string) => (await (await api.context.get(`/api/researches/${rid}/queue`)).json()) as { rows: Row[] }
const rowOf = async (api: Api, rid: string, kind: string) => (await queueOf(api, rid)).rows.find(r => r.kind === kind)!

const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`), animations: 'disabled', fullPage: true })
const list = (page: Page) => page.getByRole('listbox', { name: 'Rows awaiting your decision' })
const option = (page: Page, title: string) => list(page).getByRole('option', { name: new RegExp(`^${title}`) })
const detail = (page: Page) => page.locator('.queue-detail')
const sheet = (page: Page) => page.locator('.source-sheet')

async function openQueue(page: Page, server: QueueServer, rid: string) {
  await page.goto('about:blank')  // a hash-only change would keep the tab that is open
  await page.goto(`${server.url()}/#/research/${rid}/queue`)
  await expect(list(page)).toBeVisible()
}

test.describe.serial('J: the human queue of an sw research', () => {
  const server = new QueueServer(8781, { DEIXIS_SEARCH_WORKFLOW: 'sw', DEIXIS_PROTOCOL_APPROVAL: 'as_proposed', DEIXIS_FIXTURE_QUEUE: 'on' })
  const legacy = new QueueServer(8782, {})
  let api: Api
  let rid = ''
  let page: Page

  test.beforeAll(async ({ browser }) => {
    await Promise.all([server.start(), legacy.start()])
    api = await apiOf(server)
    rid = await createResearch(api, QUESTION)
    expect((await post(api, `/api/researches/${rid}/runs`, { kind: 'discovery' })).ok()).toBe(true)
    // Discovery, retrieval and reading run one after another; the queue is read once the reading run has settled.
    await expect.poll(async () => {
      const view = await (await api.context.get(`/api/researches/${rid}`)).json()
      return view.runs.some((r: { kind: string; status: string }) => r.kind === 'fulltext_adjudication' && r.status === 'completed')
    }, { timeout: 90_000 }).toBe(true)
    // Ortak karar 4: the four kinds must be there before anything is asked of the screen; if not, the fixture failed.
    const kinds = new Set((await queueOf(api, rid)).rows.map(r => r.kind))
    for (const kind of Object.keys(TITLES)) if (!kinds.has(kind)) throw new Error(`fixture failure: no ${kind} row in the queue (${[...kinds].join(', ')})`)
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  })
  test.afterAll(async () => { await page?.close(); await api?.context.dispose(); await Promise.all([server.stop(), legacy.stop()]) })

  test('the tab and its count are in an sw research and not in a legacy one', async () => {
    const other = await apiOf(legacy)
    const legacyId = await createResearch(other, 'How is SYNTHETIC molecule release scheduled in relay networks?')
    await other.context.dispose()
    await page.goto(`${legacy.url()}/#/research/${legacyId}`)
    await expect(page.getByRole('tab', { name: /^Sources/ })).toBeVisible()
    await expect(page.getByRole('tab', { name: /Awaiting your decision/ })).toHaveCount(0)
    await page.goto(`${server.url()}/#/research/${rid}`)
    await expect(page.getByRole('tab', { name: 'Awaiting your decision 4' })).toBeVisible()
    // The reading run's turn names the rows once and opens the tab.
    await page.locator('.chat-queue-line').getByRole('button', { name: 'Open' }).click()
    await expect(list(page)).toBeVisible()
    await expect(list(page).getByRole('option')).toHaveCount(4)
  })

  test('a row fills the detail, and Enter opens its page in the PDF at full width with the anchor marked in the text', async () => {
    await openQueue(page, server, rid)
    await option(page, TITLES.choose_run).click()
    await expect(detail(page).getByRole('heading', { name: TITLES.choose_run })).toBeVisible()
    await expect(detail(page)).toContainText('Does this paper have the part “method of its own”?')
    await expect(detail(page)).toContainText('The two reading runs came to different readings of the text.')
    await expect(detail(page).locator('.queue-run')).toHaveCount(2)
    await shot(page, 'J-queue-choose-run-1440')
    await list(page).focus()
    await page.keyboard.press('Enter')
    await expect(sheet(page)).toHaveClass(/is-full/)
    await expect(sheet(page).getByRole('tab', { name: 'PDF' })).toHaveAttribute('aria-selected', 'true')
    await expect(sheet(page).getByLabel('Page number')).toHaveValue('1')
    await sheet(page).getByRole('tab', { name: 'Plain text' }).click()
    const strip = sheet(page).locator('.pdf-text-citation')
    await expect(strip).toContainText('The model’s quote, found in the text of PDF p. 1.')
    await expect(strip).not.toHaveClass(/is-unmarked/)
    await expect(sheet(page).locator('mark.citation-highlight')).toContainText('We propose a bisection schedule')
    await page.keyboard.press('Escape')
    await expect(sheet(page)).toHaveCount(0)
  })

  test('an unverified quote shows the closest text beside it and opens its page unmarked, with an amber strip', async () => {
    await option(page, TITLES.confirm_quote).click()
    await expect(detail(page)).toContainText('the model’s quote was not found in the text. The closest text is beside it; match ratio 0.98.')
    await expect(detail(page).locator('.queue-pair')).toHaveCount(2)  // one pair per run
    await detail(page).getByRole('button', { name: 'Open page 1 in the PDF' }).click()
    await expect(sheet(page).getByLabel('Page number')).toHaveValue('1')
    await sheet(page).getByRole('tab', { name: 'Plain text' }).click()
    await expect(sheet(page).locator('.pdf-text-citation')).toHaveClass(/is-unmarked/)
    await expect(sheet(page).locator('.pdf-text-citation')).toContainText('nothing on PDF p. 1 is marked')
    await expect(sheet(page).locator('mark.citation-highlight')).toHaveCount(0)
    await page.keyboard.press('Escape')
  })

  test('a row whose part has no cue says so', async () => {
    await option(page, TITLES.find_part).click()
    await expect(detail(page)).toContainText('Does this paper have the part “measured outcome”?')
    await expect(detail(page)).toContainText('This part’s phrases do not occur in the text.')
  })

  test('an answer to a row that changed since it was shown is refused, the row is read again and the note is kept', async () => {
    await option(page, TITLES.confirm_quote).click()
    await expect(detail(page).getByRole('button', { name: 'Include', exact: true })).toBeEnabled()
    await detail(page).getByRole('button', { name: 'Add a note' }).click()
    await detail(page).getByRole('textbox').fill('SYNTHETIC note kept through a refusal')
    // The event stream is held back, so the screen still shows the row as it was.
    await page.route('**/events/stream**', route => route.abort())
    const row = await rowOf(api, rid, 'confirm_quote')
    const answered = await (await post(api, `/api/researches/${rid}/queue/${row.source_version_id}/decision`, { decision: 'include', note: null, row_token: row.row_token })).json()
    expect((await post(api, `/api/researches/${rid}/queue/${row.source_version_id}/undo`, { row_token: answered.undo_token })).ok()).toBe(true)
    await detail(page).getByRole('button', { name: 'Include', exact: true }).click()
    await expect(detail(page)).toContainText('This row changed after it was shown; its current state is loaded. Your answer was not saved.')
    await expect(option(page, TITLES.confirm_quote)).toHaveAttribute('aria-selected', 'true')
    await expect(detail(page).getByRole('textbox')).toHaveValue('SYNTHETIC note kept through a refusal')
    // The answers wait for the row read again under the new list, then take the note.
    await expect(detail(page).getByRole('button', { name: 'Include', exact: true })).toBeEnabled()
    await page.unroute('**/events/stream**')
  })

  test('an answer to a row another tab took out keeps its note, with the work it was written for', async () => {
    await page.reload()
    await option(page, TITLES.find_part).click()
    await detail(page).getByRole('button', { name: 'Add a note' }).click()
    await detail(page).getByRole('textbox').fill('SYNTHETIC note for a row that left')
    await page.route('**/events/stream**', route => route.abort())
    const row = await rowOf(api, rid, 'find_part')
    const answered = await (await post(api, `/api/researches/${rid}/queue/${row.source_version_id}/decision`, { decision: 'not_sure', note: null, row_token: row.row_token })).json()
    await detail(page).getByRole('button', { name: 'Not sure' }).click()
    const notice = page.locator('.queue-panel .notice', { hasText: 'The row you answered left the queue after it was shown.' })
    await expect(notice).toContainText(`Your note for “${TITLES.find_part}” is kept here:`)
    await expect(notice).toContainText('SYNTHETIC note for a row that left')
    await expect(option(page, TITLES.find_part)).toHaveCount(0)
    // The note is not left under the row the selection moved to.
    await expect(detail(page).getByRole('textbox')).toHaveCount(0)
    // The three views were read again: the tab's count follows the queue.
    await expect(page.getByRole('tab', { name: 'Awaiting your decision 3' })).toBeVisible()
    await page.unroute('**/events/stream**')
    expect((await post(api, `/api/researches/${rid}/queue/${row.source_version_id}/undo`, { row_token: answered.undo_token })).ok()).toBe(true)
    await expect(option(page, TITLES.find_part)).toHaveCount(1)
  })

  test('a detail that keeps disagreeing with the list is read again a bounded number of times and can be read again by hand', async () => {
    await page.reload()
    const row = await rowOf(api, rid, 'find_part')
    let reads = 0
    await page.route(`**/queue/${row.source_version_id}`, async route => {
      reads++
      const response = await route.fetch()
      const body = await response.json()
      await route.fulfill({ response, json: { ...body, row: { ...body.row, row_token: 'SYNTHETIC-moved' } } })
    })
    await option(page, TITLES.find_part).click()
    await expect(detail(page)).toContainText('This row kept changing while it was read, so it cannot be answered yet.')
    await expect(detail(page).getByRole('button', { name: 'Not sure' })).toBeDisabled()
    const settled = reads
    await page.waitForTimeout(1000)
    expect(reads).toBe(settled)
    expect(reads).toBeLessThanOrEqual(3)
    await page.unroute(`**/queue/${row.source_version_id}`)
    await detail(page).getByRole('button', { name: 'Read it again' }).click()
    await expect(detail(page).getByRole('button', { name: 'Not sure' })).toBeEnabled()
  })

  test('a list read that finishes after a newer one is not shown', async () => {
    let first = true
    let held = 0
    await page.route('**/queue', async route => {
      if (!first) return route.continue()
      first = false
      const response = await route.fetch()
      const body = await response.json()
      await new Promise(resolve => setTimeout(resolve, 4000))
      held = Date.now()
      await route.fulfill({ response, json: { ...body, rows: [] } })
    })
    await page.goto('about:blank')
    await page.goto(`${server.url()}/#/research/${rid}/queue`)
    await expect(page.getByRole('tab', { name: /Awaiting your decision/ })).toBeVisible()
    await page.waitForTimeout(500)  // the event stream is open
    // While the first read is held, another tab's answer and undo are two events, and each reads the list again.
    const row = await rowOf(api, rid, 'find_part')
    const answered = await (await post(api, `/api/researches/${rid}/queue/${row.source_version_id}/decision`, { decision: 'not_sure', note: null, row_token: row.row_token })).json()
    expect((await post(api, `/api/researches/${rid}/queue/${row.source_version_id}/undo`, { row_token: answered.undo_token })).ok()).toBe(true)
    await expect(list(page).getByRole('option')).toHaveCount(4)
    expect(held).toBe(0)  // the newer reads were shown before the first one finished
    await expect.poll(() => held, { timeout: 10_000 }).toBeGreaterThan(0)
    await page.waitForTimeout(300)
    await expect(list(page).getByRole('option')).toHaveCount(4)  // its empty answer came last and was not shown
    await page.unroute('**/queue')
  })

  test('after an answer whose own list read was overtaken, the selection moves on from the newest list', async () => {
    await page.reload()
    await expect(list(page).getByRole('option')).toHaveCount(4)
    const titles = await list(page).getByRole('option').evaluateAll(els => els.map(el => el.getAttribute('aria-label') ?? ''))
    const [firstTitle, answeredTitle, nextTitle] = titles.map(label => Object.values(TITLES).find(title => label.startsWith(title))!)
    // With the event stream held back, the answer's own list read is the first one; the research view it reloads
    // brings a new event id and a second read, which finishes first. The held read then answers with an empty list.
    await page.route('**/events/stream**', route => route.abort())
    let first = true
    await page.route('**/queue', async route => {
      if (!first || route.request().method() !== 'GET') return route.continue()
      first = false
      const response = await route.fetch()
      const body = await response.json()
      await new Promise(resolve => setTimeout(resolve, 2000))
      await route.fulfill({ response, json: { ...body, rows: [] } })
    })
    await option(page, answeredTitle).click()
    await detail(page).getByRole('button', { name: 'Not sure' }).click()
    await expect(option(page, answeredTitle)).toHaveCount(0)
    await expect(page.locator('.toast')).toBeVisible({ timeout: 10_000 })
    // The row after the answered one is selected, not the first row a lost selection falls back to.
    await expect(option(page, nextTitle)).toHaveAttribute('aria-selected', 'true')
    await expect(option(page, firstTitle)).toHaveAttribute('aria-selected', 'false')
    await page.unroute('**/queue')
    await page.unroute('**/events/stream**')
    await page.locator('.toast').getByRole('button', { name: 'Undo' }).click()
    await expect(option(page, answeredTitle)).toHaveCount(1)
  })

  test('Include takes the row out, the notification takes it back, and the source list shows the choice as the user’s', async () => {
    await page.reload()
    await option(page, TITLES.choose_run).click()
    // The row stays where it is until the server has answered.
    let release = () => {}
    const held = new Promise<void>(resolve => { release = resolve })
    await page.route('**/queue/*/decision', async route => { await held; await route.continue() })
    await detail(page).getByRole('button', { name: 'Include', exact: true }).click()
    await page.waitForTimeout(300)
    await expect(option(page, TITLES.choose_run)).toHaveCount(1)
    await expect(option(page, TITLES.choose_run)).toHaveAttribute('aria-selected', 'true')
    release()
    await expect(option(page, TITLES.choose_run)).toHaveCount(0)
    await page.unroute('**/queue/*/decision')
    const toast = page.locator('.toast')
    await expect(toast).toContainText('Included. Your choice shows in the sources as your own selection.')
    await toast.getByRole('button', { name: 'Undo' }).click()
    await expect(option(page, TITLES.choose_run)).toHaveCount(1)
    await option(page, TITLES.choose_run).click()
    await detail(page).getByRole('button', { name: 'Include', exact: true }).click()
    await expect(option(page, TITLES.choose_run)).toHaveCount(0)
    await expect(page.getByRole('tab', { name: 'Awaiting your decision 3' })).toBeVisible()
    await page.getByRole('tab', { name: /^Sources/ }).click()
    const row = page.locator('.source-row', { hasText: TITLES.choose_run })
    await expect(row.getByRole('button', { name: 'Include' })).toHaveAttribute('aria-pressed', 'true')
    await expect(row).toContainText('Your answer in the queue: you included it')
  })

  test('PDF is right takes the row out, lists it under your decisions, and is taken back from there', async () => {
    await openQueue(page, server, rid)
    await option(page, TITLES.confirm_pdf).click()
    await expect(detail(page)).toContainText('Is this PDF the work named here?')
    await expect(detail(page)).toContainText('First page of the PDF')
    await detail(page).getByRole('button', { name: 'PDF is right, let the model read it' }).click()
    await expect(option(page, TITLES.confirm_pdf)).toHaveCount(0)
    await expect(page.locator('.toast')).toContainText('No run starts by itself.')
    const decided = page.locator('.queue-decided')
    await decided.locator('summary').click()
    const entry = decided.locator('li', { hasText: TITLES.confirm_pdf })
    await expect(entry).toContainText('you confirmed the PDF')
    await shot(page, 'J-queue-decided-1440')
    await entry.getByRole('button', { name: /^Undo your decision/ }).click()
    await expect(option(page, TITLES.confirm_pdf)).toHaveCount(1)
    await expect(decided.locator('li', { hasText: TITLES.confirm_pdf })).toHaveCount(0)
  })

  test('the event stream refreshes the open queue and keeps the note being written', async () => {
    await option(page, TITLES.find_part).click()
    await detail(page).getByRole('button', { name: 'Add a note' }).click()
    await detail(page).getByRole('textbox').fill('SYNTHETIC note being written')
    const row = await rowOf(api, rid, 'confirm_pdf')
    expect((await post(api, `/api/researches/${rid}/queue/${row.source_version_id}/decision`, { decision: 'not_sure', note: null, row_token: row.row_token })).ok()).toBe(true)
    await expect(option(page, TITLES.confirm_pdf)).toHaveCount(0)
    await expect(detail(page).getByRole('textbox')).toHaveValue('SYNTHETIC note being written')
    await expect(option(page, TITLES.find_part)).toHaveAttribute('aria-selected', 'true')
  })

  test('the keyboard reaches the list, moves through it, opens a page and answers; focus goes to the next row', async () => {
    await page.reload()
    await expect(list(page)).toBeVisible()
    await page.getByRole('tab', { name: /Awaiting your decision/ }).focus()
    for (let i = 0; i < 20 && !(await list(page).evaluate(el => el === document.activeElement)); i++) await page.keyboard.press('Tab')
    await expect(list(page)).toBeFocused()
    const first = await list(page).getAttribute('aria-activedescendant')
    await page.keyboard.press('ArrowDown')
    const second = await list(page).getAttribute('aria-activedescendant')
    expect(second).not.toBe(first)
    await page.keyboard.press('ArrowUp')
    await expect(list(page)).toHaveAttribute('aria-activedescendant', first!)
    await page.keyboard.press('Enter')
    await expect(sheet(page)).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(list(page)).toBeFocused()
    const notSure = detail(page).getByRole('button', { name: 'Not sure' })
    for (let i = 0; i < 40 && !(await notSure.evaluate(el => el === document.activeElement)); i++) await page.keyboard.press('Tab')
    await expect(notSure).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(list(page)).toBeFocused()
    await expect(list(page).getByRole('option')).toHaveCount(1)
    await expect(list(page)).toHaveAttribute('aria-activedescendant', second!)
  })

  test('at 390 px the list gives way to the detail and back, the full title shows and the answers do not cover it', async ({ browser }) => {
    // Put the answered rows back so the narrow screen has a row of each open kind to show.
    for (const entry of (await (await api.context.get(`/api/researches/${rid}/queue`)).json()).decided as { source_version_id: string; undo_token: string; answer: string }[]) {
      if (entry.answer !== 'include') await post(api, `/api/researches/${rid}/queue/${entry.source_version_id}/undo`, { row_token: entry.undo_token })
    }
    const narrow = await browser.newPage({ viewport: { width: 390, height: 844 } })
    try {
      await openQueue(narrow, server, rid)
      await expect(narrow.getByRole('tab', { name: /Awaiting your decision/ })).toBeVisible()
      await expect(detail(narrow)).toBeHidden()
      await option(narrow, TITLES.confirm_quote).click()
      await expect(list(narrow)).toBeHidden()
      const title = detail(narrow).getByRole('heading', { name: TITLES.confirm_quote })
      await expect(title).toBeVisible()
      await expect(title).toHaveText(TITLES.confirm_quote)
      await shot(narrow, 'J-queue-detail-390')
      // Scrolled to the end, the pinned answers rest under the last section instead of over it.
      await narrow.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
      const last = await narrow.locator('.queue-detail section').last().boundingBox()
      const foot = await narrow.locator('.queue-foot').boundingBox()
      expect(last!.y + last!.height).toBeLessThanOrEqual(foot!.y + 1)
      await detail(narrow).getByRole('button', { name: 'Back to the list' }).click()
      await expect(list(narrow)).toBeFocused()
      await expect(list(narrow)).toHaveAttribute('aria-activedescendant', /queue-row-/)
      await expect(option(narrow, TITLES.confirm_quote)).toHaveAttribute('aria-selected', 'true')
      // An answer moves to the next row's detail, with focus on its title.
      await option(narrow, TITLES.confirm_quote).click()
      await detail(narrow).getByRole('button', { name: 'Not sure' }).click()
      await expect(option(narrow, TITLES.confirm_quote)).toHaveCount(0)
      await expect(narrow.locator('#queue-detail-title')).toBeFocused()
      await expect(detail(narrow).getByRole('heading', { name: TITLES.confirm_quote })).toHaveCount(0)
    } finally { await narrow.close() }
  })
})
