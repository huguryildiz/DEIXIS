import { expect, request as apiRequest, test, type APIRequestContext, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort, readingDone } from './ports'
import { PANEL_TITLES, panel } from './panels'

// UI parity S8: the research topbar and the question bubble (mockup R1–R9, R12, R13). The title is one button that
// opens the rename row; the run chip says what the latest run is doing; "N waiting for you" opens the queue; the ⋯ menu
// holds Rename, Activity, Candidates, Follow-up and Move to Trash; Export lists the files that can be made now; Revise
// question turns the bubble into the revise form.
//
// Its own fixture server with the queue fixture, so the research has queue rows. Every record is SYNTHETIC; a passing
// case shows how the page behaves, not the quality of a search or an answer.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

const QUESTION = '[queue] How do SYNTHETIC molecular relays and greenhouse irrigation schedule their releases?'
const REVISED = '[queue] How do SYNTHETIC molecular relays schedule their releases?'

class TopbarServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-topbar-'))
  constructor(readonly port: number) {}
  async start() {
    const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend'), DEIXIS_FIXTURE_QUEUE: 'on' }
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`http://127.0.0.1:${this.port}/api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`topbar fixture server on ${this.port} did not start`)
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
type View = { research: { title: string; version: number; current_scope_revision: number }; runs: Array<{ kind: string; status: string }>
  sources: Array<{ source_version_id: string; version_role: string; selection: { state: string } }>; counts: { cited: number; included: number } }
const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
const post = (api: Api, url: string, data: unknown) => api.context.post(url, { data, headers: { 'x-deixis-csrf': api.token } })
const viewOf = async (api: Api, rid: string) => (await (await api.context.get(`/api/researches/${rid}`)).json()) as View
const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`), animations: 'disabled' })
const topbar = (page: Page) => page.locator('.research-topbar')
const chip = (page: Page) => topbar(page).locator('.runchip')

async function create(api: Api, question: string, run = true) {
  const created = await post(api, '/api/researches', { question, model_connection: 'codex', requested_model: 'fixture-model', effort: 'quick' })
  expect(created.status()).toBe(201)
  const rid = (await created.json()).research.id as string
  if (run) expect((await post(api, `/api/researches/${rid}/runs`, { kind: 'discovery' })).ok()).toBe(true)
  return rid
}
const settled = (api: Api, rid: string) => expect.poll(async () => {
  const view = await viewOf(api, rid)
  return readingDone(view) && view.runs.some(r => r.kind === 'answer') && !view.runs.some(r => ACTIVE.has(r.status))
}, { timeout: 90_000 }).toBe(true)

test.describe.serial('S8: research topbar and question bubble', () => {
  const server = new TopbarServer(nextPort())
  let api: Api
  let rid = ''
  let page: Page

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(150_000)
    await server.start()
    const context = await apiRequest.newContext({ baseURL: server.url(), extraHTTPHeaders: { origin: server.url() } })
    api = { context, token: (await (await context.get('/api/session')).json()).csrf_token as string }
    rid = await create(api, QUESTION)
    await settled(api, rid)
    page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  })
  test.afterAll(async () => { await page?.close(); await api?.context.dispose(); await server.stop() })

  test('the topbar holds the title, the waiting chip, Revise question, Export and ⋯ in the mockup order', async () => {
    await page.goto(`${server.url()}/#/research/${rid}`)
    const title = (await viewOf(api, rid)).research.title
    // The h1 is the title; its one button opens the rename row (its tooltip says so); the pencil shows on hover.
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(title)
    const button = page.locator('h1 .research-title-button')
    await expect(button).toHaveAttribute('title', 'Rename')
    await expect(button.locator('svg')).toHaveCSS('opacity', '0')
    await button.hover()
    await expect(button.locator('svg')).toHaveCSS('opacity', '1')
    const order = await topbar(page).evaluate(bar => [...bar.children].map(el => el.className.split(' ').find(c =>
      ['research-title', 'wait-chip', 'research-revise', 'research-export', 'research-more'].includes(c)) ?? el.className))
    expect(order).toEqual(['research-title', 'wait-chip', 'research-revise', 'research-export', 'research-more'])
    // A completed research has no run chip.
    await expect(chip(page)).toHaveCount(0)
    // The question bubble: where DEIXIS looks, the question, and when this revision was saved; no revision line yet.
    const bubble = page.locator('.chat-question')
    await expect(bubble.locator('b')).toHaveText('Academic search')
    await expect(bubble).toContainText(QUESTION)
    await expect(bubble.locator('time')).toHaveText(/· revision 1$/)
    await expect(page.locator('.revline')).toHaveCount(0)
    // The old revision form at the end of the page is gone.
    await expect(page.getByRole('textbox', { name: 'Question', exact: true })).toHaveCount(0)
    await shot(page, 's8-topbar-desktop')
    const wait = topbar(page).locator('.wait-chip')
    await expect(wait).toHaveText(/^\d+ waiting for you$/)
    await wait.click()
    await expect(panel(page, PANEL_TITLES.queue)).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(wait).toBeFocused()
  })

  test('the ⋯ menu lists Rename, Activity, Candidates and Follow-up, the panels, the run actions and Move to Trash', async () => {
    await page.goto(`${server.url()}/#/research/${rid}`)
    const more = page.getByRole('button', { name: 'Research actions' })
    await more.click()
    await expect(page.getByRole('menuitem', { name: 'Move to Trash' })).toBeVisible()
    // A row's count follows its name; the names and details are compared without it.
    const rows = (await page.getByRole('menuitem').allTextContents()).map(text => text.replace(/ \d+/, ''))
    expect(rows).toEqual(['Rename', 'ActivityRuns, status, time and model calls', 'CandidatesClaims you test against the literature',
      'Follow-upNew works after this research ran', 'Sources', 'Awaiting your decision', 'Get more full text', 'Evidence table',
      'Search again', 'Generate a new answer', 'Move to Trash'])
    await shot(page, 's8-research-menu')
    await page.keyboard.press('Escape')
    for (const [row, title] of [[/^Activity/, 'Activity'], [/^Candidates/, 'Candidates'], [/^Follow-up/, 'Follow-up']] as const) {
      await expect(page.getByRole('menu')).toHaveCount(0)
      await more.click()
      await page.getByRole('menuitem', { name: row }).click()
      await expect(panel(page, title)).toBeVisible()
    }
    await page.keyboard.press('Escape')
    await expect(page.locator('[data-split-panel]')).toHaveCount(0)
    await more.click()
    await page.getByRole('menuitem', { name: 'Rename' }).click()
    await expect(page.getByRole('textbox', { name: 'Research title' })).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  })

  test('the title is renamed in its row: Save and Enter save, ✕ and Escape cancel', async () => {
    await page.goto(`${server.url()}/#/research/${rid}`)
    const before = (await viewOf(api, rid)).research.title
    const heading = page.getByRole('heading', { level: 1 })
    await page.locator('h1 .research-title-button').click()
    const field = page.getByRole('textbox', { name: 'Research title' })
    await expect(field).toBeFocused()
    await expect(field).toHaveValue(before)
    // The row holds the field, Suggest a short title, Save and ✕; the chips, Export and ⋯ give way while it is open.
    await expect(topbar(page).getByRole('button', { name: 'Suggest a short title' })).toBeVisible()
    await expect(topbar(page).getByRole('button', { name: 'Save', exact: true })).toBeVisible()
    await expect(topbar(page).getByRole('button', { name: 'Research actions' })).toHaveCount(0)
    await expect(topbar(page).locator('.wait-chip')).toHaveCount(0)
    await shot(page, 's8-title-edit')
    await field.fill('SYNTHETIC title not kept')
    await field.press('Escape')
    await expect(heading).toHaveText(before)
    await expect(page.locator('h1 .research-title-button')).toBeFocused()

    await page.keyboard.press('Enter')
    await field.fill('SYNTHETIC title not kept either')
    await topbar(page).getByRole('button', { name: 'Cancel' }).click()
    await expect(heading).toHaveText(before)

    await page.locator('h1 .research-title-button').click()
    await field.fill('SYNTHETIC renamed from the topbar')
    await topbar(page).getByRole('button', { name: 'Save', exact: true }).click()
    await expect(heading).toHaveText('SYNTHETIC renamed from the topbar')
    await expect.poll(async () => (await viewOf(api, rid)).research.title).toBe('SYNTHETIC renamed from the topbar')

    await page.locator('h1 .research-title-button').click()
    await field.fill('SYNTHETIC renamed with Enter')
    await field.press('Enter')
    await expect(heading).toHaveText('SYNTHETIC renamed with Enter')
    await page.reload()
    await expect(heading).toHaveText('SYNTHETIC renamed with Enter')
  })

  test('Export lists the report and sources files, and a table once one has rows and columns', async () => {
    await page.goto(`${server.url()}/#/research/${rid}`)
    const exportButton = topbar(page).getByRole('button', { name: 'Export' })
    await exportButton.click()
    const menu = page.locator('[data-slot=dropdown-menu-content]')
    await expect(menu.locator('[data-slot=dropdown-menu-label]')).toHaveText(['Report', 'Sources'])
    const rows = menu.locator('.menu-fmt')
    // The [queue] fixture's answer cites works that still wait in the queue: cited sources, none included, so the RIS
    // file (included sources) has no row.
    const counts = (await viewOf(api, rid)).counts
    expect(counts.cited).toBeGreaterThan(0)
    expect(counts.included).toBe(0)
    await expect(rows.locator('b')).toHaveText(['MD', 'DOCX', 'BIB', 'MD', 'JSON'])
    await expect(rows.nth(1)).toHaveAttribute('href', /\/answers\/[^/]+\/export\/docx\?lang=en&style=apa$/)
    await expect(rows.nth(2)).toContainText(/BibTeX · \d+ cited sources?/)
    await expect(rows.nth(3)).toHaveAttribute('href', /prisma-s/i)
    await shot(page, 's8-export-menu')
    const markdown = page.waitForEvent('download')
    await rows.nth(0).click()
    expect((await markdown).suggestedFilename()).toMatch(/-v\d+\.md$/)

    // A table with one row and one column brings the Evidence table group: CSV written here, Excel and Word from the API.
    const view = await viewOf(api, rid)
    const row = view.sources.filter(s => s.version_role === 'record').map(s => s.source_version_id).slice(0, 1)
    let table = await (await post(api, `/api/researches/${rid}/tables`, { title: 'SYNTHETIC topbar table', rows: row })).json()
    table = await (await post(api, `/api/researches/${rid}/tables/${table.table.id}/columns`, { name: 'Sample size', instruction: 'State the sample size.', answer_format: 'text', expected_version: table.table.version })).json()
    await page.reload()
    await exportButton.click()
    await expect(menu.locator('[data-slot=dropdown-menu-label]')).toHaveText(['Report', 'Evidence table', 'Sources'])
    await expect(rows.locator('b')).toHaveText(['MD', 'DOCX', 'CSV', 'XLSX', 'DOCX', 'BIB', 'MD', 'JSON'])
    await expect(rows.nth(3)).toHaveAttribute('href', new RegExp(`/tables/${table.table.id}/export/xlsx`))
    const csv = page.waitForEvent('download')
    await rows.nth(2).click()
    expect((await csv).suggestedFilename()).toMatch(/^synthetic-topbar-table-v\d+\.csv$/)
  })

  test('Revise question turns the bubble into the form; Save writes revision 2 and keeps revision 1 behind Show', async () => {
    await page.goto(`${server.url()}/#/research/${rid}`)
    const revise = topbar(page).getByRole('button', { name: 'Revise question' })
    await revise.click()
    const form = page.getByRole('form', { name: 'Revise question' })
    const question = form.getByRole('textbox', { name: 'Question', exact: true })
    await expect(question).toBeFocused()
    await expect(question).toHaveValue(QUESTION)
    await expect(form.getByLabel('English key terms (optional)')).toBeVisible()
    const save = form.getByRole('button', { name: 'Save revision 2' })
    await expect(save).toBeDisabled()
    await expect(page.locator('.chat-question:not(.is-editing)')).toHaveCount(0)
    await shot(page, 's8-revise-in-bubble')
    await form.getByRole('button', { name: 'Cancel' }).click()
    await expect(form).toHaveCount(0)
    await expect(revise).toBeFocused()

    await revise.click()
    await question.fill(REVISED)
    await save.click()
    await expect(page.locator('.toast')).toContainText('Question revised.')
    await expect(form).toHaveCount(0)
    const bubble = page.locator('.chat-question')
    await expect(bubble).toContainText(REVISED)
    await expect(bubble.locator('time')).toHaveText(/· revision 2$/)
    expect((await viewOf(api, rid)).research.current_scope_revision).toBe(2)
    // The earlier revision is kept and opens read only.
    const line = page.locator('.revline')
    await expect(line).toContainText('Revision 1 and its answer are kept')
    await line.getByRole('button', { name: 'Show' }).click()
    const earlier = page.getByRole('region', { name: 'Revision 1 (read only)' })
    await expect(earlier.locator('.chat-question')).toContainText(QUESTION)
    await expect(earlier.locator('.chat-question time')).toHaveText(/· revision 1$/)
    await expect(earlier.locator('.report-artifact')).toContainText(/Report · V\d+ · earlier/)
    await shot(page, 's8-earlier-revision')
    await line.getByRole('button', { name: 'Hide' }).click()
    await expect(earlier).toHaveCount(0)
  })

  test('a revision saved in another window while the form is open keeps the draft and blocks Save until the draft is based on it', async () => {
    await page.goto(`${server.url()}/#/research/${rid}`)
    const before = await viewOf(api, rid)
    const revision = before.research.current_scope_revision
    await topbar(page).getByRole('button', { name: 'Revise question' }).click()
    const form = page.getByRole('form', { name: 'Revise question' })
    const question = form.getByRole('textbox', { name: 'Question', exact: true })
    const draft = 'SYNTHETIC draft written while another window revised the question?'
    await question.fill(draft)
    // Another window saves a revision with the version this page also holds.
    const other = 'SYNTHETIC question saved in the other window?'
    expect((await post(api, `/api/researches/${rid}/scope`, { question: other, expected_version: before.research.version, key_terms: null })).ok()).toBe(true)
    const conflict = form.getByRole('alert')
    await expect(conflict).toContainText(`Revision ${revision + 1} of this question was saved in another window while you edited.`)
    await expect(conflict).toContainText(other)
    await expect(question).toHaveValue(draft)
    const save = form.getByRole('button', { name: `Save revision ${revision + 2}` })
    await expect(save).toBeDisabled()
    // A submit that bypasses the disabled button is refused too.
    await form.evaluate(f => (f as HTMLFormElement).requestSubmit())
    expect((await viewOf(api, rid)).research.current_scope_revision).toBe(revision + 1)
    await shot(page, 's8-revise-conflict')
    // Asking for the form again only moves focus: the draft and the conflict stay, Save stays blocked.
    await form.getByLabel('English key terms (optional)').focus()
    await topbar(page).getByRole('button', { name: 'Revise question' }).click()
    await expect(question).toBeFocused()
    await expect(conflict).toBeVisible()
    await expect(question).toHaveValue(draft)
    await expect(save).toBeDisabled()
    await conflict.getByRole('button', { name: `Base my draft on revision ${revision + 1}` }).click()
    await expect(conflict).toHaveCount(0)
    await expect(question).toBeFocused()
    await expect(question).toHaveValue(draft)
    await save.click()
    await expect(form).toHaveCount(0)
    await expect(page.locator('.chat-question')).toContainText(draft)
    const after = await viewOf(api, rid)
    expect(after.research.current_scope_revision).toBe(revision + 2)
  })

  test('a revision this page has not received yet is refused by the backend (409) and the draft stays', async () => {
    // The page gets no live updates, so it still holds the research version from before the other window saved.
    await page.route('**/events/stream**', route => route.abort())
    try {
      await page.goto(`${server.url()}/#/research/${rid}`)
      const before = await viewOf(api, rid)
      const revision = before.research.current_scope_revision
      await topbar(page).getByRole('button', { name: 'Revise question' }).click()
      const form = page.getByRole('form', { name: 'Revise question' })
      const question = form.getByRole('textbox', { name: 'Question', exact: true })
      const draft = 'SYNTHETIC draft saved after an update this page never received?'
      await question.fill(draft)
      const other = 'SYNTHETIC question the other window saved first?'
      expect((await post(api, `/api/researches/${rid}/scope`, { question: other, expected_version: before.research.version, key_terms: null })).ok()).toBe(true)
      await form.getByRole('button', { name: `Save revision ${revision + 1}` }).click()
      await expect(page.locator('.toast')).toContainText('Not applied:')
      // The refusal reloads the page's state: the newer revision shows as a conflict over the kept draft.
      await expect(form.getByRole('alert')).toContainText(`Revision ${revision + 1} of this question was saved in another window`)
      await expect(question).toHaveValue(draft)
      const after = await viewOf(api, rid)
      expect(after.research.current_scope_revision).toBe(revision + 1)
      await form.getByRole('button', { name: 'Cancel' }).click()
      await expect(form).toHaveCount(0)
    } finally { await page.unroute('**/events/stream**') }
  })

  test('a rename saved elsewhere within the same revision does not block saving the draft', async () => {
    await page.goto(`${server.url()}/#/research/${rid}`)
    const before = await viewOf(api, rid)
    const revision = before.research.current_scope_revision
    await topbar(page).getByRole('button', { name: 'Revise question' }).click()
    const form = page.getByRole('form', { name: 'Revise question' })
    const draft = 'SYNTHETIC draft kept across a rename made in another window?'
    await form.getByRole('textbox', { name: 'Question', exact: true }).fill(draft)
    const title = 'SYNTHETIC renamed in another window'
    expect((await post(api, `/api/researches/${rid}/title`, { title, expected_version: before.research.version })).ok()).toBe(true)
    await expect(topbar(page).locator('.research-title-button')).toHaveAttribute('aria-label', title)
    await expect(form.getByRole('alert')).toHaveCount(0)
    await form.getByRole('button', { name: `Save revision ${revision + 1}` }).click()
    await expect(form).toHaveCount(0)
    await expect(page.locator('.chat-question')).toContainText(draft)
    expect((await viewOf(api, rid)).research.current_scope_revision).toBe(revision + 1)
  })

  test('the run chip follows the latest run: paused, stopped, failed, and an answer being written', async () => {
    test.setTimeout(240_000)
    // Paused by the person (the fixture asks for the pause in the read stage): amber. Resume run and Cancel run sit in
    // the notice under the steps (S9, R18); the topbar keeps only the chip.
    const paused = await create(api, '[pause-at-read] How is SYNTHETIC molecule release scheduling optimized?')
    await page.goto(`${server.url()}/#/research/${paused}`)
    await expect(chip(page)).toHaveText('Search & screening · Paused', { timeout: 60_000 })
    await expect(chip(page)).toHaveClass(/is-warn/)
    await expect(topbar(page).getByRole('button', { name: /Resume|Cancel/ })).toHaveCount(0)
    const pausedNote = page.locator('.chat-note.notice')
    await expect(pausedNote.getByRole('button', { name: 'Resume run' })).toBeVisible()
    await expect(pausedNote.getByRole('button', { name: 'Cancel run' })).toBeVisible()
    await shot(page, 's8-chip-paused')
    await pausedNote.getByRole('button', { name: 'Resume run' }).click()
    await settled(api, paused)
    await expect(chip(page)).toHaveCount(0, { timeout: 30_000 })

    // Stopped on its own (the model did not answer): amber with the warning icon, still resumable.
    const stopped = await create(api, '[model-down] How is SYNTHETIC molecule release scheduling optimized?')
    await page.goto(`${server.url()}/#/research/${stopped}`)
    await expect(chip(page)).toHaveText('Search & screening · Stopped', { timeout: 60_000 })
    const stoppedNote = page.locator('.chat-note.notice')
    await expect(stoppedNote.getByRole('button', { name: 'Resume run' })).toBeVisible()
    await stoppedNote.getByRole('button', { name: 'Cancel run' }).click()
    await expect(chip(page)).toHaveCount(0, { timeout: 30_000 })

    // Failed before any search (every term too common): the chip says Stopped and offers no Resume.
    const failed = await create(api, '[vocab-broad] How is SYNTHETIC molecule release scheduling optimized?')
    await page.goto(`${server.url()}/#/research/${failed}`)
    await expect(chip(page)).toHaveText('Search & screening · Stopped', { timeout: 60_000 })
    await expect(page.locator('.run-strip')).toHaveCount(0)
    await expect(page.getByRole('button', { name: /^Resume/ })).toHaveCount(0)

    // The automatic answer is held: the chip spins with Pause and says the first version is being written.
    const release = path.join(server.dataDir, 'answer-release')
    rmSync(release, { force: true })
    const held = await create(api, '[answer-hold] How is SYNTHETIC molecule release scheduling optimized?')
    await page.goto(`${server.url()}/#/research/${held}`)
    try {
      await expect(chip(page)).toHaveText('Answer · Writing the first version', { timeout: 60_000 })
      await expect(chip(page)).toHaveClass(/is-live/)
      await expect(topbar(page).getByRole('button', { name: 'Pause' })).toBeVisible()
      // A live run can be cancelled beside Pause (the mockup draws no other way to stop it; §0 rule 5).
      await expect(topbar(page).getByRole('button', { name: 'Cancel', exact: true })).toBeVisible()
      await shot(page, 's8-chip-answer-writing')
    } finally { writeFileSync(release, 'SYNTHETIC release\n') }
    await settled(api, held)
    await expect(chip(page)).toHaveCount(0, { timeout: 30_000 })
  })

  test('Move to Trash leaves the research; Undo restores it', async () => {
    const trashed = await create(api, 'SYNTHETIC research for the trash row', false)
    await page.goto(`${server.url()}/#/research/${trashed}`)
    await page.getByRole('button', { name: 'Research actions' }).click()
    await page.getByRole('menuitem', { name: 'Move to Trash' }).click()
    await expect(page).toHaveURL(/#\/$/)
    const toast = page.locator('.toast', { hasText: 'Moved to Trash.' })
    await expect(toast).toBeVisible()
    expect((await api.context.get(`/api/researches/${trashed}`)).status()).toBe(404)
    await toast.getByRole('button', { name: 'Undo' }).click()
    await expect(page).toHaveURL(new RegExp(`#/research/${trashed}$`))
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('SYNTHETIC research for the trash row')
  })

  test('at 390px the waiting chip gives way, Revise question and Suggest are icons and nothing scrolls sideways', async () => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto(`${server.url()}/#/research/${rid}`)
    await expect(topbar(page).locator('.wait-chip')).toBeHidden()
    const revise = topbar(page).getByRole('button', { name: 'Revise question' })
    await expect(revise).toBeVisible()
    expect((await revise.boundingBox())!.width).toBeLessThanOrEqual(31)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
    await shot(page, 's8-topbar-390')
    // The rename row keeps Suggest a short title as an icon button (its only path), Revise question steps aside.
    await topbar(page).locator('.research-title-button').click()
    const suggest = topbar(page).getByRole('button', { name: 'Suggest a short title' })
    await expect(suggest).toBeVisible()
    expect((await suggest.boundingBox())!.width).toBeLessThanOrEqual(31)
    await expect(revise).toBeHidden()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
    await shot(page, 's8-title-edit-390')
    await page.keyboard.press('Escape')
    await page.setViewportSize({ width: 1280, height: 900 })
  })
})
