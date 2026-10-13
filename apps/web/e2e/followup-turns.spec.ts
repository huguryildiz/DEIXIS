import { expect, request as apiRequest, test, type APIRequestContext, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'
import { panel } from './panels'

// UI parity S22b: follow-up questions in the thread (R30 composer, R31 turns; D11). A question is sent from the sticky
// composer (⌘/Ctrl + Enter), its two step lines follow the stored run, the published answer cites the passages the call was
// given, a paused turn resumes from its notice, an invalid output shows as an unverified draft, a turn the passages do not
// answer says so, and "Search for new works on this" saves a new question revision without starting a search. Every
// expected value is read from the stored turn or research, never by position.
//
// Every record is SYNTHETIC and the model is the fixture's script ([fu-hold], [fu-not], [fu-invalid] in the follow-up
// question); a passing case shows how the page behaves, not how well a model answers a follow-up.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })
const QUESTION = 'SYNTHETIC: How are molecule release schedules compared?'

class FixtureServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-followup-turns-'))
  constructor(readonly port: number) {}
  async start() {
    const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend') }
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      if (this.proc.exitCode !== null) throw new Error('SYNTHETIC fixture server exited before health')
      try { if ((await fetch(`http://127.0.0.1:${this.port}/api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`follow-up fixture server on ${this.port} did not start`)
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

type Citation = { passage_id: string; title: string }
type Turn = {
  id: string; question: string; status: string; scope_revision: number; passages_given: number | null
  run: { id: string; status: string }; progress: { passages_selected: number | null; answer_step: string | null }
  answer: { outcome: string; claims: { label: string; text: string; citations: Citation[] }[]; unanswered_aspects: string[] } | null
  issues: { code: string; path: string }[]
}
type View = { research: { current_scope_revision: number }; scope: { question: string }; runs: Array<{ id: string; kind: string; status: string }> }
type Api = { context: APIRequestContext; token: string }
const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
const post = (api: Api, url: string, data: unknown, headers: Record<string, string> = {}) => api.context.post(url, { data, headers: { 'x-deixis-csrf': api.token, ...headers } })
const viewOf = async (api: Api, rid: string) => (await (await api.context.get(`/api/researches/${rid}`)).json()) as View
const turnsOf = async (api: Api, rid: string) => (await (await api.context.get(`/api/researches/${rid}/followup-turns`)).json()) as Turn[]
const turnFor = async (api: Api, rid: string, question: string) => (await turnsOf(api, rid)).find(t => t.question === question)
const settled = async (api: Api, rid: string, kinds: string[]) => expect.poll(async () => {
  const view = await viewOf(api, rid)
  return kinds.every(k => view.runs.some(r => r.kind === k)) && !view.runs.some(r => ACTIVE.has(r.status))
}, { timeout: 110_000, intervals: [500] }).toBe(true)
const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`), animations: 'disabled' })
const visit = async (page: Page, url: string) => { await page.goto('about:blank'); await page.goto(url) }
const composer = (page: Page) => page.getByRole('textbox', { name: 'Follow-up question' })
const sendButton = (page: Page) => page.getByRole('button', { name: 'Send follow-up question' })
const turnOn = (page: Page, question: string) => page.locator('.followup-turn').filter({ has: page.locator('.followup-q', { hasText: question }) })
const plural = (n: number, one: string, many: string) => (n === 1 ? one : many).replace('{n}', String(n))

async function newResearch(api: Api, question: string, scope = 'academic') {
  const created = await post(api, '/api/researches', { question, model_connection: 'codex', requested_model: 'fixture-model', effort: 'standard', source_scope: scope })
  expect(created.status()).toBe(201)
  return (await created.json()).research.id as string
}
async function ask(page: Page, question: string) {
  await composer(page).fill(question)
  await composer(page).press('ControlOrMeta+Enter')
}

test.describe.serial('S22b: follow-up questions in the thread', () => {
  test.setTimeout(240_000)
  const server = new FixtureServer(nextPort())
  let api: Api
  let rid = ''
  let page: Page
  const research = (id = rid) => `${server.url()}/#/research/${id}`

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(240_000)
    await server.start()
    const context = await apiRequest.newContext({ baseURL: server.url(), extraHTTPHeaders: { origin: server.url() } })
    api = { context, token: (await (await context.get('/api/session')).json()).csrf_token as string }
    rid = await newResearch(api, QUESTION)
    expect((await post(api, `/api/researches/${rid}/runs`, { kind: 'discovery' }, { 'Idempotency-Key': `fu-discovery-${rid}` })).ok()).toBe(true)
    await settled(api, rid, ['discovery', 'answer'])
    page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  })
  test.afterAll(async () => { await page?.close(); await api?.context.dispose(); await server.stop() })

  test('the composer sticks to the foot of the thread and shows the research depth, not a choice of its own', async () => {
    await visit(page, research())
    const box = page.locator('.followup-compose')
    await expect(composer(page)).toBeVisible()
    await expect(composer(page)).toHaveAttribute('placeholder', 'Ask about the passages this research has read')
    await expect(box).toHaveCSS('position', 'sticky')
    // Scrolled to the top of a thread taller than the window, its bottom is the thread column's bottom: it stays in view
    // while the thread scrolls under it.
    const column = page.locator('.research-thread-col')
    await column.evaluate(node => { node.scrollTop = 0 })
    expect(await column.evaluate(node => node.scrollHeight > node.clientHeight + 200)).toBe(true)
    const frame = await column.boundingBox()
    const own = await box.boundingBox()
    expect(Math.abs((own!.y + own!.height) - (frame!.y + frame!.height))).toBeLessThanOrEqual(2)
    await expect(box.locator('.followup-depth')).toHaveText(/Standard$/)
    await expect(box.locator('.followup-depth button, .followup-depth[role=button]')).toHaveCount(0)
    // "+" opens Get more full text, where PDFs are added to the research's works.
    await page.getByRole('button', { name: 'Add PDFs' }).click()
    await expect(panel(page, 'Get more full text')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(panel(page, 'Get more full text')).toHaveCount(0)
    // An empty question is not sent.
    let posts = 0
    page.on('request', request => { if (request.method() === 'POST' && request.url().includes('/followup-turns')) posts++ })
    await sendButton(page).click()
    await expect(page.locator('.toast', { hasText: 'Type a follow-up question first' })).toBeVisible()
    await expect(composer(page)).toBeFocused()
    expect(posts).toBe(0)
    await shot(page, 's22b-composer')
    // In a window too short to share, the composer stays at the end of the thread instead of covering it.
    await page.setViewportSize({ width: 390, height: 500 })
    await expect(box).toHaveCSS('position', 'static')
    await page.setViewportSize({ width: 1280, height: 900 })
    await expect(box).toHaveCSS('position', 'sticky')
  })

  test('ask by ⌘/Ctrl + Enter: live steps, a pause and its resume, then the answer with its stored citations', async () => {
    const question = '[fu-hold] Which release schedules were compared in SYNTHETIC studies?'
    await visit(page, research())
    await ask(page, question)
    const turn = turnOn(page, question)
    await expect(turn).toBeVisible()
    // The question was queued: the box is empty again and Send waits for the run (one active run per research).
    await expect(composer(page)).toHaveValue('')
    await expect(sendButton(page)).toBeDisabled()
    // While the model holds the call the second line is live; the first line counts the stored selection once it exists.
    await expect(turn.locator('.followup-step.is-running')).toHaveText('Writing a short answer', { timeout: 20_000 })
    const live = await turnFor(api, rid, question)
    expect(live?.status).toBe('pending')
    await expect(turn.locator('.followup-step').first()).toHaveText(plural(live!.progress.passages_selected!, 'Looked in the {n} passage from this research', 'Looked in the {n} passages from this research'))
    await shot(page, 's22b-live')
    // Pause from the topbar while the call is held; the call answers, the run stops before publishing.
    await page.locator('.research-topbar .run-strip-pause').click()
    writeFileSync(path.join(server.dataDir, 'followup-release'), 'release')
    const notice = turn.locator('.followup-notice')
    await expect(notice).toContainText('Paused after the current call.', { timeout: 20_000 })
    await expect(turn.locator('.followup-step').nth(1)).toHaveText('Wrote a short answer; not published')
    await expect(turn.locator('.followup-prose')).toHaveCount(0)
    await notice.getByRole('button', { name: 'Resume run' }).click()
    await expect(turn.locator('.followup-prose')).toBeVisible({ timeout: 20_000 })
    const stored = await turnFor(api, rid, question)
    expect(stored?.status).toBe('answered')
    // The step lines name the passages the call was given (its allowlist) and the written answer.
    await expect(turn.locator('.followup-step')).toHaveText([
      plural(stored!.passages_given!, 'Looked in the {n} passage from this research', 'Looked in the {n} passages from this research'), 'Wrote a short answer'])
    // The prose is the stored claims, each with its chip; the chip opens the Citation panel on the claim's passages.
    const claims = stored!.answer!.claims
    await expect(turn.locator('.followup-prose .claim')).toHaveCount(claims.length)
    const first = claims[0]
    await expect(turn.locator('.followup-prose .claim').first()).toContainText(first.text)
    await turn.locator('.followup-prose .cite-chip').first().click()
    const cite = panel(page, 'Citation')
    await expect(cite).toBeVisible()
    await expect(cite.locator('.cite-entry h3')).toHaveText(first.citations.map(c => c.title))
    await expect(turn.locator('.followup-prose .cite-chip').first()).toHaveAttribute('aria-expanded', 'true')
    await page.keyboard.press('Escape')
    // A follow-up starts no search and writes no answer of the research.
    const view = await viewOf(api, rid)
    expect(view.runs.filter(r => r.kind === 'discovery')).toHaveLength(1)
    await expect(sendButton(page)).toBeEnabled()
    await shot(page, 's22b-answered')
  })

  test('the draft stays when a request fails, and a second press while one runs sends nothing more', async () => {
    const question = 'SYNTHETIC: which molecule counts were reported?'
    await visit(page, research())
    let posts = 0
    await page.route('**/api/researches/*/followup-turns', async route => {
      if (route.request().method() !== 'POST') return route.fallback()
      posts++
      await new Promise(resolve => setTimeout(resolve, 800))
      await route.fulfill({ status: 500, json: { detail: 'SYNTHETIC failure' } })
    })
    await composer(page).fill(question)
    await sendButton(page).click()
    await expect(sendButton(page)).toBeDisabled()
    await composer(page).press('ControlOrMeta+Enter')
    await expect(page.locator('.toast', { hasText: 'The follow-up question was not sent' })).toBeVisible()
    expect(posts).toBe(1)
    await expect(composer(page)).toHaveValue(question)
    await expect(turnOn(page, question)).toHaveCount(0)
    await page.unroute('**/api/researches/*/followup-turns')
  })

  test('a POST response that arrives after the answer never hides it', async () => {
    const question = 'SYNTHETIC: which schedule did the late response ask about?'
    await visit(page, research())
    // The queued turn's response is held until the stored turn is answered, then delivered as it was sent (pending).
    await page.route('**/api/researches/*/followup-turns', async route => {
      if (route.request().method() !== 'POST') return route.fallback()
      const response = await route.fetch()
      const body = await response.json() as Turn
      expect(body.status).toBe('pending')
      await expect.poll(async () => (await turnFor(api, rid, question))?.status, { timeout: 30_000 }).toBe('answered')
      await new Promise(resolve => setTimeout(resolve, 2500))
      await route.fulfill({ response, json: body })
    })
    await ask(page, question)
    const turn = turnOn(page, question)
    await expect(turn.locator('.followup-prose')).toBeVisible({ timeout: 30_000 })
    await expect(composer(page)).toHaveValue('', { timeout: 10_000 })
    // After the late response the answer is still shown (no reload, no new event).
    await page.waitForTimeout(1500)
    await expect(turn.locator('.followup-prose')).toBeVisible()
    await expect(turn.locator('.followup-notice')).toHaveCount(0)
    await page.unroute('**/api/researches/*/followup-turns')
  })

  test('an invalid output is an unverified draft: its issues, no claim and no citation', async () => {
    const question = '[fu-invalid] What did the SYNTHETIC schedules optimise?'
    await visit(page, research())
    await ask(page, question)
    const turn = turnOn(page, question)
    await expect(turn.locator('.followup-notice')).toContainText('The model output did not pass validation, so it is not shown as a cited answer.', { timeout: 30_000 })
    const stored = await turnFor(api, rid, question)
    expect(stored?.status).toBe('unverified_draft')
    await expect(turn.locator('.followup-step').nth(1)).toHaveText('The short answer failed validation')
    await expect(turn.locator('.answer-notice-issues li')).toHaveText(stored!.issues.map(i => `${i.code} at ${i.path}`))
    await expect(turn.locator('.followup-prose, .cite-chip')).toHaveCount(0)
  })

  test('the Next steps row puts the answer’s first unanswered aspect in the composer and sends nothing', async () => {
    const aspect = 'SYNTHETIC: whether release schedules were compared under bounded energy.'
    await page.route(`**/api/researches/${rid}`, async route => {
      const response = await route.fetch()
      const body = await response.json() as { answers: Array<{ unanswered_aspects: string[] }> }
      body.answers.forEach(a => { a.unanswered_aspects = [aspect] })
      await route.fulfill({ response, json: body })
    })
    await visit(page, research())
    let posts = 0
    page.on('request', request => { if (request.method() === 'POST' && request.url().includes('/followup-turns')) posts++ })
    await page.locator('.answer-thread .follow').getByRole('button', { name: `Ask as a follow-up: ${aspect}` }).click()
    await expect(composer(page)).toHaveValue(aspect)
    await expect(composer(page)).toBeFocused()
    expect(posts).toBe(0)
    await page.unroute(`**/api/researches/${rid}`)
  })

  test('a turn the passages do not answer says so; "Search for new works on this" saves a revision and starts no search', async () => {
    const question = '[fu-not] Which SYNTHETIC studies report schedules in hours?'
    await visit(page, research())
    await ask(page, question)
    const turn = turnOn(page, question)
    await expect(turn.locator('.followup-outcome')).toHaveText('The passages in this research do not answer this.', { timeout: 30_000 })
    const stored = await turnFor(api, rid, question)
    expect(stored?.answer?.outcome).toBe('not_answered')
    await expect(turn.locator('.followup-gaps li')).toHaveText(stored!.answer!.unanswered_aspects)
    const before = await viewOf(api, rid)
    await turn.getByRole('button', { name: 'Search for new works on this' }).click()
    const after = before.research.current_scope_revision + 1
    await expect(page.locator('.toast', { hasText: `Saved as revision ${after} of the question. No search has started` })).toBeVisible()
    const view = await viewOf(api, rid)
    expect(view.research.current_scope_revision).toBe(after)
    expect(view.scope.question).toBe(question)
    expect(view.runs.filter(r => r.kind === 'discovery').length).toBe(before.runs.filter(r => r.kind === 'discovery').length)
    expect(view.runs.some(r => ACTIVE.has(r.status))).toBe(false)
    // The turn now belongs to the earlier revision and no longer offers the search.
    await expect(turn.locator('.followup-note')).toContainText(`Asked under revision ${stored!.scope_revision} of the question.`)
    await expect(turn.getByRole('button', { name: 'Search for new works on this' })).toHaveCount(0)
    await shot(page, 's22b-not-answered')
  })

  test('a research with no passage to give answers with no model call and says so', async () => {
    const empty = await newResearch(api, 'SYNTHETIC: what do my attached files say?', 'attached')
    await visit(page, research(empty))
    const question = 'SYNTHETIC: what is reported?'
    await ask(page, question)
    const turn = turnOn(page, question)
    await expect(turn.locator('.followup-step')).toHaveText(['This research held no passage to give'], { timeout: 30_000 })
    await expect(turn.locator('.followup-notice')).toHaveText('This research held no passage to give, so no model was asked and no search was run.')
    expect((await turnFor(api, empty, question))?.status).toBe('no_passages')
    // An attached-files research cannot search providers, so no search is offered.
    await expect(turn.getByRole('button', { name: 'Search for new works on this' })).toHaveCount(0)
  })
})
