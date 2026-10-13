import { expect, request as apiRequest, test, type APIRequestContext, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort, readingDone } from './ports'
import { expectMenuCount, openAudit, openPanel, PANEL_TITLES, panel, queueCard, queueCards, showAnswer } from './panels'

// Case J: the human queue of an sw research (slice 17, D97). A person sees the works the reading could not settle,
// opens a row's page, and answers; an answer can be taken back, a row that moved is refused, and the list follows the
// event stream.
//
// Its own fixture server, with retrieval and reading switched on (DEIXIS_FIXTURE_QUEUE) and four SYNTHETIC works the
// scripted reading model answers so that each gives one row kind.
// A passing case shows application behavior, not whether a person reads a paper well.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

const AGREED = 'SYNTHETIC release window pacing along molecular relay chains'
const OFF_TOPIC = 'SYNTHETIC hospital visiting hours after staff feedback'
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
    if (proc && proc.exitCode === null) {
      const exited = new Promise(resolve => proc.once('exit', resolve))
      proc.kill('SIGTERM')
      await exited
    }
    rmSync(this.dataDir, { recursive: true, force: true })
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
// The queue is stacked cards (UI parity S14, P39): one list item per row, named by its work's title.
const cards = (page: Page) => queueCards(page)
const card = (page: Page, title: string) => queueCard(page, title)
const titlesOf = (page: Page) => page.locator('.queue-panel .qcard-title').allTextContents()
const sheet = (page: Page) => page.locator('.source-sheet')
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)

async function openQueue(page: Page, server: QueueServer, rid: string) {
  await page.goto('about:blank')  // a hash-only change would keep the tab that is open
  await page.goto(`${server.url()}/#/research/${rid}/queue`)
  await expect(cards(page)).toBeVisible()
}

test.describe.serial('J: the human queue of an sw research', () => {
  // DEIXIS_FIXTURE_AUDIT adds one work both reading runs include (slice 20): it is no queue row, and the audit sample's
  // group of agreeing includes shows it.
  const server = new QueueServer(nextPort(), { DEIXIS_SEARCH_WORKFLOW: 'sw', DEIXIS_FIXTURE_QUEUE: 'on', DEIXIS_FIXTURE_AUDIT: 'on' })
  let api: Api
  let rid = ''
  let page: Page

  test.beforeAll(async ({ browser }) => {
    await server.start()
    api = await apiOf(server)
    rid = await createResearch(api, QUESTION)
    expect((await post(api, `/api/researches/${rid}/runs`, { kind: 'discovery' })).ok()).toBe(true)
    // Discovery, retrieval and reading run one after another; the queue is read once the reading run has settled.
    await expect.poll(async () => {
      const view = await (await api.context.get(`/api/researches/${rid}`)).json()
      return readingDone(view)
    }, { timeout: 90_000 }).toBe(true)
    // Ortak karar 4: the four kinds must be there before anything is asked of the screen; if not, the fixture failed.
    const kinds = new Set((await queueOf(api, rid)).rows.map(r => r.kind))
    for (const kind of Object.keys(TITLES)) if (!kinds.has(kind)) throw new Error(`fixture failure: no ${kind} row in the queue (${[...kinds].join(', ')})`)
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  })
  test.afterAll(async () => { await page?.close(); await api?.context.dispose(); await server.stop() })

  test('the panel and its count are in the research, and focus lands on the panel heading only', async () => {
    await page.goto(`${server.url()}/#/research/${rid}`)
    await expectMenuCount(page, 'queue', 4)
    // The reading run's turn names the rows once, in its screening step's details, and opens the panel (S9, R15).
    await page.locator('.chat-step-line', { hasText: 'Screened' }).click()
    await expect(page.locator('.chat-step-detail .step-row', { hasText: 'Waiting for your decision' })).toContainText('4')
    await page.locator('.chat-step-detail').getByRole('button', { name: 'Open' }).click()
    await expect(cards(page)).toBeVisible()
    await expect(cards(page).locator(':scope > .qcard')).toHaveCount(4)
    await expect(page.locator('[data-split-panel] #split-panel-title')).toBeFocused()
    await expect(page.locator('.queue-panel > p').first()).toHaveText('These came up while DEIXIS worked. Your answer is recorded as your decision and can be taken back; nothing here was decided for you.')
  })

  test('each of the eight row kinds has its own card head', async () => {
    // The fixture gives four kinds; the other four are the find_part row's detail under SYNTHETIC rows the list read adds.
    const base = (await queueOf(api, rid)).rows.find(r => r.kind === 'find_part')!
    const found = await (await api.context.get(`/api/researches/${rid}/queue/${base.source_version_id}`)).json()
    const heads: Record<string, [string, string]> = {
      confirm_quote: ['Quote check', 'a quote was not found on its page'],
      choose_run: ['Reading', 'the two reading runs disagreed'],
      choose_version: ['Version', 'two versions of this work; they are different sources, not interchangeable'],
      confirm_pdf: ['PDF check', 'is this the right file?'],
      confirm_absent: ['Missing part', 'both runs read a required part as absent'],
      find_part: ['Missing part', 'the runs did not find this part'],
      confirm_results: ['Protocol', 'results, or only a plan?'],
      look_again: ['Look again', 'you decided this under an earlier question'],
    }
    const extra = ['choose_version', 'confirm_absent', 'confirm_results', 'look_again'].map(kind => ({
      ...base, kind, work_id: `SYNTHETIC-${kind}`, source_version_id: `SYNTHETIC-${kind}`, title: `SYNTHETIC ${kind} card`,
      row_token: `SYNTHETIC-${kind}-token`, question: kind === 'confirm_absent' ? base.question : null,
    }))
    await page.route(`**/api/researches/${rid}/queue`, async route => {
      if (route.request().method() !== 'GET') return route.continue()
      const response = await route.fetch()
      const body = await response.json()
      await route.fulfill({ response, json: { ...body, rows: [...body.rows, ...extra] } })
    })
    await page.route('**/queue/SYNTHETIC-*', route => {
      const row = extra.find(r => route.request().url().endsWith(r.source_version_id))!
      return route.fulfill({ json: { row, decision: null, undo_token: '', detail: found.detail } })
    })
    await openQueue(page, server, rid)
    const titles: Record<string, string> = { ...TITLES, ...Object.fromEntries(extra.map(r => [r.kind, r.title])) }
    for (const [kind, [head, about]] of Object.entries(heads)) {
      const one = card(page, titles[kind])
      await expect(one.locator('header b')).toHaveText(head)
      await expect(one.locator('header span')).toContainText(about)
    }
    await expect(page.getByRole('heading', { name: 'Decided under an earlier question; look again' })).toBeVisible()
    await expect(card(page, titles.confirm_results)).toContainText('The title names a study protocol.')
    await shot(page, 'J-queue-every-kind-1440')
    await page.unroute(`**/api/researches/${rid}/queue`)
    await page.unroute('**/queue/SYNTHETIC-*')
  })

  test('a kind filter whose last row is answered falls back to every row instead of an empty filter', async () => {
    await openQueue(page, server, rid)
    const chips = page.locator('.queue-chips')
    await chips.getByRole('button', { name: /^Confirm the PDF/ }).click()
    await expect(cards(page).locator(':scope > .qcard')).toHaveCount(1)
    await card(page, TITLES.confirm_pdf).getByRole('button', { name: 'Not sure' }).click()
    await expect(card(page, TITLES.confirm_pdf)).toHaveCount(0)
    await expect(cards(page).locator(':scope > .qcard')).toHaveCount(3)
    await expect(page.getByText('No row matches this filter.')).toHaveCount(0)
    await expect(chips.getByRole('button', { name: /^All/ })).toHaveAttribute('aria-pressed', 'true')
    await page.locator('.toast').getByRole('button', { name: 'Undo' }).click()
    await expect(cards(page).locator(':scope > .qcard')).toHaveCount(4)
  })

  test('a card shows both runs, and its page button opens the PDF at full width with the anchor marked in the text', async () => {
    await openQueue(page, server, rid)
    const one = card(page, TITLES.choose_run)
    await expect(one).toContainText('Is this paper a source for the question?')
    await expect(one.locator('header')).toContainText('the two reading runs disagreed')
    await expect(one.locator('.queue-run')).toHaveCount(2)
    await shot(page, 'J-queue-choose-run-1440')
    const open = one.getByRole('button', { name: 'Open page 1 in the PDF' })
    await open.click()
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
    await expect(open).toBeFocused()
  })

  test('an unverified quote shows the closest text beside it and opens its page unmarked, with an amber strip', async () => {
    const one = card(page, TITLES.confirm_quote)
    await expect(one).toContainText('the model’s quote was not found in the text. The closest text is beside it; match ratio 0.98.')
    await expect(one.locator('.queue-pair')).toHaveCount(2)  // one pair per run
    await one.getByRole('button', { name: 'Open page 1 in the PDF' }).click()
    await expect(sheet(page).getByLabel('Page number')).toHaveValue('1')
    await sheet(page).getByRole('tab', { name: 'Plain text' }).click()
    await expect(sheet(page).locator('.pdf-text-citation')).toHaveClass(/is-unmarked/)
    await expect(sheet(page).locator('.pdf-text-citation')).toContainText('nothing on PDF p. 1 is marked')
    await expect(sheet(page).locator('mark.citation-highlight')).toHaveCount(0)
    await page.keyboard.press('Escape')
  })

  test('a row whose part has no cue says so', async () => {
    const one = card(page, TITLES.find_part)
    await expect(one).toContainText('The reading could not settle the part “measured outcome”.')
    await expect(one).toContainText('This part’s phrases do not occur in the text.')
  })

  test('an answer to a row that changed since it was shown is refused, the row is read again and the note is kept', async () => {
    const one = card(page, TITLES.confirm_quote)
    await expect(one.getByRole('button', { name: 'Yes', exact: true })).toBeEnabled()
    await one.getByRole('button', { name: 'Add a note' }).click()
    await one.getByRole('textbox').fill('SYNTHETIC note kept through a refusal')
    // The event stream is held back, so the screen still shows the row as it was.
    await page.route('**/events/stream**', route => route.abort())
    const row = await rowOf(api, rid, 'confirm_quote')
    const answered = await (await post(api, `/api/researches/${rid}/queue/${row.source_version_id}/decision`, { decision: 'include', note: null, row_token: row.row_token })).json()
    expect((await post(api, `/api/researches/${rid}/queue/${row.source_version_id}/undo`, { row_token: answered.undo_token })).ok()).toBe(true)
    await one.getByRole('button', { name: 'Yes', exact: true }).click()
    await expect(one).toContainText('This row changed after it was shown; its current state is loaded. Your answer was not saved.')
    await expect(one.getByRole('textbox')).toHaveValue('SYNTHETIC note kept through a refusal')
    // The answers wait for the row read again under the new list, then take the note.
    await expect(one.getByRole('button', { name: 'Yes', exact: true })).toBeEnabled()
    await page.unroute('**/events/stream**')
  })

  test('an answer to a row another tab took out keeps its note, with the work it was written for', async () => {
    await page.reload()
    const one = card(page, TITLES.find_part)
    await one.getByRole('button', { name: 'Add a note' }).click()
    await one.getByRole('textbox').fill('SYNTHETIC note for a row that left')
    await page.route('**/events/stream**', route => route.abort())
    const row = await rowOf(api, rid, 'find_part')
    const answered = await (await post(api, `/api/researches/${rid}/queue/${row.source_version_id}/decision`, { decision: 'not_sure', note: null, row_token: row.row_token })).json()
    await one.getByRole('button', { name: 'Not sure' }).click()
    const notice = page.locator('.queue-panel .notice', { hasText: 'The row you answered left the queue after it was shown.' })
    await expect(notice).toContainText(`Your note for “${TITLES.find_part}” is kept here:`)
    await expect(notice).toContainText('SYNTHETIC note for a row that left')
    await expect(one).toHaveCount(0)
    // The note is not left under another card.
    await expect(page.locator('.queue-panel textarea')).toHaveCount(0)
    // The three views were read again: the tab's count follows the queue.
    await expectMenuCount(page, 'queue', 3)
    await page.unroute('**/events/stream**')
    expect((await post(api, `/api/researches/${rid}/queue/${row.source_version_id}/undo`, { row_token: answered.undo_token })).ok()).toBe(true)
    await expect(card(page, TITLES.find_part)).toHaveCount(1)
  })

  test('a detail that keeps disagreeing with the list is read again a bounded number of times and can be read again by hand', async () => {
    const row = await rowOf(api, rid, 'find_part')
    let reads = 0
    await page.route(`**/queue/${row.source_version_id}`, async route => {
      reads++
      const response = await route.fetch()
      const body = await response.json()
      await route.fulfill({ response, json: { ...body, row: { ...body.row, row_token: 'SYNTHETIC-moved' } } })
    })
    await page.reload()  // every card on screen reads its detail as the panel opens
    const one = card(page, TITLES.find_part)
    await expect(one).toContainText('This row kept changing while it was read, so it cannot be answered yet.')
    await expect(one.getByRole('button', { name: 'Not sure' })).toBeDisabled()
    const settled = reads
    await page.waitForTimeout(1000)
    expect(reads).toBe(settled)
    expect(reads).toBeLessThanOrEqual(3)
    await page.unroute(`**/queue/${row.source_version_id}`)
    await one.getByRole('button', { name: 'Read it again' }).click()
    await expect(one.getByRole('button', { name: 'Not sure' })).toBeEnabled()
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
    await expect(panel(page, PANEL_TITLES.queue)).toBeVisible()
    await page.waitForTimeout(500)  // the event stream is open
    // While the first read is held, another tab's answer and undo are two events, and each reads the list again.
    const row = await rowOf(api, rid, 'find_part')
    const answered = await (await post(api, `/api/researches/${rid}/queue/${row.source_version_id}/decision`, { decision: 'not_sure', note: null, row_token: row.row_token })).json()
    expect((await post(api, `/api/researches/${rid}/queue/${row.source_version_id}/undo`, { row_token: answered.undo_token })).ok()).toBe(true)
    await expect(cards(page).locator(':scope > .qcard')).toHaveCount(4)
    expect(held).toBe(0)  // the newer reads were shown before the first one finished
    await expect.poll(() => held, { timeout: 10_000 }).toBeGreaterThan(0)
    await page.waitForTimeout(300)
    await expect(cards(page).locator(':scope > .qcard')).toHaveCount(4)  // its empty answer came last and was not shown
    await page.unroute('**/queue')
  })

  test('after an answer whose own list read was overtaken, focus moves to the next card of the newest list', async () => {
    await page.reload()
    await expect(cards(page).locator(':scope > .qcard')).toHaveCount(4)
    const [firstTitle, answeredTitle, nextTitle] = await titlesOf(page)
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
    await card(page, answeredTitle).getByRole('button', { name: 'Not sure' }).click()
    await expect(card(page, answeredTitle)).toHaveCount(0)
    await expect(page.locator('.toast')).toBeVisible({ timeout: 10_000 })
    // The card after the answered one takes focus, not the first card a lost place falls back to.
    await expect(card(page, nextTitle).locator('.qcard-title')).toBeFocused()
    await expect(card(page, firstTitle)).toHaveCount(1)
    await page.unroute('**/queue')
    await page.unroute('**/events/stream**')
    await page.locator('.toast').getByRole('button', { name: 'Undo' }).click()
    await expect(card(page, answeredTitle)).toHaveCount(1)
  })

  test('Include takes the row out, the notification takes it back, and the source list shows the choice as the user’s', async () => {
    await page.reload()
    // The card stays where it is until the server has answered.
    let release = () => {}
    const held = new Promise<void>(resolve => { release = resolve })
    await page.route('**/queue/*/decision', async route => { await held; await route.continue() })
    await card(page, TITLES.choose_run).getByRole('button', { name: 'Yes', exact: true }).click()
    await page.waitForTimeout(300)
    await expect(card(page, TITLES.choose_run)).toHaveCount(1)
    release()
    await expect(card(page, TITLES.choose_run)).toHaveCount(0)
    await page.unroute('**/queue/*/decision')
    const toast = page.locator('.toast')
    await expect(toast).toContainText('Included. Your choice shows in the sources as your own selection.')
    await toast.getByRole('button', { name: 'Undo' }).click()
    await expect(card(page, TITLES.choose_run)).toHaveCount(1)
    await card(page, TITLES.choose_run).getByRole('button', { name: 'Yes', exact: true }).click()
    await expect(card(page, TITLES.choose_run)).toHaveCount(0)
    await expectMenuCount(page, 'queue', 3)
    await openPanel(page, 'sources')
    const row = page.locator('.source-row', { hasText: TITLES.choose_run })
    await expect(row.getByRole('button', { name: 'Include' })).toHaveAttribute('aria-pressed', 'true')
    await expect(row).toContainText('Your answer in the queue: you included it')
  })

  test('PDF is right takes the row out, lists it under your decisions, and is taken back from there', async () => {
    await openQueue(page, server, rid)
    const one = card(page, TITLES.confirm_pdf)
    await expect(one).toContainText('Is this PDF the work named here?')
    await expect(one).toContainText('First page of the PDF')
    await expect(one.getByRole('button', { name: 'PDF is right, let the model read it' })).toContainText('The next reading run reads this work; no run starts by itself')
    await one.getByRole('button', { name: 'PDF is right, let the model read it' }).click()
    await expect(one).toHaveCount(0)
    await expect(page.locator('.toast')).toContainText('No run starts by itself.')
    const decided = page.locator('.queue-decided')
    await decided.locator('summary').click()
    const entry = decided.locator('li', { hasText: TITLES.confirm_pdf })
    await expect(entry).toContainText('you confirmed the PDF')
    await shot(page, 'J-queue-decided-1440')
    await entry.getByRole('button', { name: /^Undo your decision/ }).click()
    await expect(card(page, TITLES.confirm_pdf)).toHaveCount(1)
    await expect(decided.locator('li', { hasText: TITLES.confirm_pdf })).toHaveCount(0)
  })

  test('the event stream refreshes the open queue and keeps the note being written', async () => {
    const one = card(page, TITLES.find_part)
    await one.getByRole('button', { name: 'Add a note' }).click()
    await one.getByRole('textbox').fill('SYNTHETIC note being written')
    const row = await rowOf(api, rid, 'confirm_pdf')
    expect((await post(api, `/api/researches/${rid}/queue/${row.source_version_id}/decision`, { decision: 'not_sure', note: null, row_token: row.row_token })).ok()).toBe(true)
    await expect(card(page, TITLES.confirm_pdf)).toHaveCount(0)
    await expect(one.getByRole('textbox')).toHaveValue('SYNTHETIC note being written')
  })

  test('the keyboard reaches a card, opens its work and answers; focus goes to the next card', async () => {
    await page.reload()
    await expect(cards(page)).toBeVisible()
    const [firstTitle, nextTitle] = await titlesOf(page)
    const title = card(page, firstTitle).locator('.qcard-title')
    await page.locator('[data-split-panel] #split-panel-title').focus()
    for (let i = 0; i < 30 && !(await title.evaluate(el => el === document.activeElement)); i++) await page.keyboard.press('Tab')
    await expect(title).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(sheet(page)).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(title).toBeFocused()
    const notSure = card(page, firstTitle).getByRole('button', { name: 'Not sure' })
    for (let i = 0; i < 40 && !(await notSure.evaluate(el => el === document.activeElement)); i++) await page.keyboard.press('Tab')
    await expect(notSure).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(card(page, firstTitle)).toHaveCount(0)
    await expect(cards(page).locator(':scope > .qcard')).toHaveCount(1)
    await expect(card(page, nextTitle).locator('.qcard-title')).toBeFocused()
  })

  test('at 390 px the cards stack in one column, the full title shows, nothing scrolls sideways and an answer moves focus on', async ({ browser }) => {
    // Put the answered rows back so the narrow screen has a row of each open kind to show.
    for (const entry of (await (await api.context.get(`/api/researches/${rid}/queue`)).json()).decided as { source_version_id: string; undo_token: string; answer: string }[]) {
      if (entry.answer !== 'include') await post(api, `/api/researches/${rid}/queue/${entry.source_version_id}/undo`, { row_token: entry.undo_token })
    }
    const narrow = await browser.newPage({ viewport: { width: 390, height: 844 } })
    try {
      await openQueue(narrow, server, rid)
      await expect(panel(narrow, PANEL_TITLES.queue)).toBeVisible()
      const one = card(narrow, TITLES.confirm_quote)
      await expect(one.locator('.qcard-title')).toHaveText(TITLES.confirm_quote)
      // The two runs sit one above the other.
      const [a, b] = await one.locator('.queue-run').evaluateAll(els => els.map(el => el.getBoundingClientRect().toJSON() as DOMRect))
      expect(Math.abs(a.x - b.x)).toBeLessThan(1)
      expect(b.y).toBeGreaterThan(a.y)
      expect(await noSideScroll(narrow)).toBe(true)
      await shot(narrow, 'J-queue-cards-390')
      const titles = await titlesOf(narrow)
      const at = titles.indexOf(TITLES.confirm_quote)
      const next = titles[at + 1] ?? titles[at - 1]
      await one.getByRole('button', { name: 'Not sure' }).click()
      await expect(one).toHaveCount(0)
      await expect(card(narrow, next).locator('.qcard-title')).toBeFocused()
    } finally { await narrow.close() }
  })
  test('the audit sample answers an agreeing include, the counts and the override line follow, and undo takes it back', async () => {
    await page.setViewportSize({ width: 1440, height: 1000 })
    // The override line stays in the queue panel; the audit sample is in the Search funnel panel (S14).
    await openQueue(page, server, rid)
    const line = page.locator('.overrides-line')
    const before = (await line.textContent()) ?? ''
    const model = (text: string) => Number(/model runs (\d+)\)/.exec(text)?.[1] ?? 0)
    const audit = await openAudit(page)
    const f1 = audit.locator('.audit-group').first()
    await expect(f1).toContainText('Included by two agreeing runs')
    await expect(f1).toContainText('Current sample: you looked at 0 of 1 rows; you decided differently in 0.')
    const row = f1.locator('.audit-row', { hasText: AGREED })
    await expect(row).toContainText('Does this work meet the criterion?')
    await row.getByRole('button', { name: 'Does not meet the criterion' }).click()
    await expect(page.locator('.toast').last()).toContainText('Your audit answer is recorded as your decision.')
    await expect(f1).toContainText('Current sample: you looked at 1 of 1 rows; you decided differently in 1.')
    await expect(row).toContainText('You answered:')
    await shot(page, 'J-audit-answered-1440')
    await openPanel(page, 'queue')
    await expect.poll(async () => model((await line.textContent()) ?? '')).toBe(model(before) + 1)
    await expect(line).not.toContainText('%')
    // An audit answer is not a queue row and does not show under the queue's own decisions.
    await expect(page.locator('.queue-decided:not(.audit-earlier) li', { hasText: AGREED })).toHaveCount(0)
    const again = await openAudit(page)
    await again.locator('.audit-group').first().locator('.audit-row', { hasText: AGREED }).getByRole('button', { name: `Undo your audit answer on ${AGREED}` }).click()
    await expect(again.locator('.audit-group').first()).toContainText('Current sample: you looked at 0 of 1 rows; you decided differently in 0.')
    await openPanel(page, 'queue')
    await expect.poll(async () => (await line.textContent()) ?? '').toBe(before)
  })
  test('an abstract-stage work of the audit sample is chosen in the source list by its id, not its title', async () => {
    // Two distinct works share the off-topic title; the card sends the person to its own work only.
    type AbstractRow = { work_id: string; source_version_id: string; title: string }
    const sample = (await (await api.context.get(`/api/researches/${rid}/audit`)).json()).abstract.A1.rows as AbstractRow[]
    const twins = sample.filter(r => r.title === OFF_TOPIC)
    expect(twins).toHaveLength(2)
    expect(twins[0].work_id).not.toBe(twins[1].work_id)
    const [target, twin] = twins
    await openAudit(page)
    const cards = page.locator('.audit-abstract .audit-row', { hasText: OFF_TOPIC })
    await expect(cards).toHaveCount(2)
    await expect(cards.first().getByRole('button', { name: 'Include', exact: true })).toHaveCount(0)  // no selection from the card
    await cards.first().scrollIntoViewIfNeeded()
    await shot(page, 'J-audit-abstract-1440')
    await cards.first().getByRole('button', { name: `Find ${OFF_TOPIC} in the source list` }).click()
    await expect(panel(page, 'Sources')).toBeVisible()
    await expect(page.locator('.source-focus')).toContainText('Showing the one work the audit sample sent you to.')
    const source = page.locator('.source-row', { hasText: OFF_TOPIC })
    await expect(page.locator('.source-row')).toHaveCount(1)
    await source.getByRole('button', { name: 'Include', exact: true }).click()
    await expect(source.getByRole('button', { name: 'Include', exact: true })).toHaveAttribute('aria-pressed', 'true')
    // Only the target work's selection changed.
    const state = async (workId: string) => ((await (await api.context.get(`/api/researches/${rid}`)).json()).sources as { work_id: string; version_role: string; selection: { state: string } }[])
      .find(s => s.work_id === workId && s.version_role === 'record')!.selection.state
    expect(await state(target.work_id)).toBe('included')
    expect(await state(twin.work_id)).not.toBe('included')
    // Changing the PDF filter ends the focus: the list follows the filter again and shows both works.
    const focusLine = page.locator('.source-focus')
    const pdfFilter = page.getByRole('combobox', { name: 'Filter sources by PDF availability' })
    await pdfFilter.click()
    await page.getByRole('option', { name: /^No PDF/ }).click()
    await expect(focusLine).toHaveCount(0)
    await expect(page.locator('.source-row', { hasText: OFF_TOPIC })).toHaveCount(2)
    // "Show all sources" clears the search and the PDF filter too, whatever was set before the focus.
    const search = page.getByRole('searchbox', { name: 'Filter sources' })
    await search.fill('SYNTHETIC greedy')
    const follow = async () => {
      await openAudit(page)
      await page.locator('.audit-abstract .audit-row', { hasText: OFF_TOPIC }).first()
        .getByRole('button', { name: `Find ${OFF_TOPIC} in the source list` }).click()
      await expect(focusLine).toBeVisible()
    }
    await follow()
    await focusLine.getByRole('button', { name: 'Show all sources' }).click()
    await expect(focusLine).toHaveCount(0)
    await expect(search).toHaveValue('')
    await expect(pdfFilter).toContainText('PDF: All')
    const total = ((await (await api.context.get(`/api/researches/${rid}`)).json()).sources as { version_role: string }[]).length
    await expect(page.locator('.source-row')).toHaveCount(total)
    // Leaving the Sources tab ends the focus: coming back shows the whole list.
    await follow()
    await showAnswer(page)
    await openPanel(page, 'sources')
    await expect(focusLine).toHaveCount(0)
    await expect(page.locator('.source-row')).toHaveCount(total)
    // The list edit is the person's decision: the target leaves the sample (strata hold no person's work), its twin
    // stays, and the override line counts it on the list path against the model runs' abstract-stage decision.
    await openAudit(page)
    await expect(page.locator('.audit-abstract .audit-row', { hasText: OFF_TOPIC })).toHaveCount(1)
    await openPanel(page, 'queue')
    await expect(page.locator('.overrides-line')).toContainText('model runs 1)')
  })
})
