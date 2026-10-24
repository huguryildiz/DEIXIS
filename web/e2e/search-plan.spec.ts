import { expect, request as apiRequest, test, type APIRequestContext, type Page } from '@playwright/test'
import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'
import { closePanel, openPlanPanel, planPanel } from './panels'

// UI parity S23b: the Search plan panel (P42, D12). It opens from "Edit plan" in the plan step and shows the plan the
// server stores for the revision it names: the words of each block, the stored queries, the criterion and the providers,
// OpenAlex ticked and locked, Crossref's PDF-link note. A refused plan keeps the draft and names its rules; Cancel sends
// nothing; "Search again with this plan" saves a new revision and starts its search, both read back from the server; a
// revision saved elsewhere while editing shows a conflict that keeps the draft; a changed seed PDF is accepted from the
// thread and makes a new revision. Every expected value is read from the stored plan or research, never by position.
//
// Every record is SYNTHETIC and the model is the fixture's script; a passing case shows how the page behaves, not whether
// an edited plan finds better works (D12's limits).

const REPO = path.resolve(process.cwd(), '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })
const QUESTION = 'SYNTHETIC: How is molecule release scheduling optimized?'

class FixtureServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-search-plan-'))
  constructor(readonly port: number) {}
  async start() {
    const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: REPO }
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      if (this.proc.exitCode !== null) throw new Error('SYNTHETIC fixture server exited before health')
      try { if ((await fetch(`http://127.0.0.1:${this.port}/api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`search plan fixture server on ${this.port} did not start`)
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

type Provider = { provider_id: string; required: boolean; checked: boolean; in_scope: boolean; configured: boolean; not_covered: string[] }
type Plan = {
  setting: { term: string }[]; task: { term: string }[]; setting_backup: { term: string }[]; task_backup: { term: string }[]
  criterion: { text: string; parts: { name: string }[] } | null; providers: string[]
}
type PlanView = {
  expected_version: number; scope_revision: number; origin: string | null; based_on: { scope_revision: number } | null
  plan: Plan | null; issues: { code: string; path: string }[]; queries: { label: string; origin: string; query_text: string }[]
  queries_preview: boolean; providers: Provider[]
}
type View = {
  research: { version: number; current_scope_revision: number; next_scope_revision: number }
  scope: { seed_status: string; seeds: { source_version_id: string; title: string }[] }
  runs: Array<{ id: string; kind: string; status: string; scope_revision: number }>
}
type Api = { context: APIRequestContext; token: string }
const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
const NAMES: Record<string, string> = { openalex: 'OpenAlex', semantic_scholar: 'Semantic Scholar', crossref: 'Crossref', scopus: 'Scopus' }
const post = (api: Api, url: string, data: unknown, headers: Record<string, string> = {}) => api.context.post(url, { data, headers: { 'x-deixis-csrf': api.token, ...headers } })
const viewOf = async (api: Api, rid: string) => (await (await api.context.get(`/api/researches/${rid}`)).json()) as View
const planOf = async (api: Api, rid: string) => (await (await api.context.get(`/api/researches/${rid}/search-plan`)).json()) as PlanView
const settled = async (api: Api, rid: string, kinds: string[], revision?: number) => expect.poll(async () => {
  const view = await viewOf(api, rid)
  return kinds.every(k => view.runs.some(r => r.kind === k && (revision === undefined || r.scope_revision === revision))) && !view.runs.some(r => ACTIVE.has(r.status))
}, { timeout: 120_000, intervals: [500] }).toBe(true)
const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`), animations: 'disabled' })
const visit = async (page: Page, url: string) => { await page.goto('about:blank'); await page.goto(url) }
const chips = (page: Page, block: 'setting' | 'task') => planPanel(page).locator(`.kw[data-block="${block}"] > span`)
const searchButton = (page: Page) => planPanel(page).getByRole('button', { name: 'Search again with this plan' })
const addWord = async (page: Page, block: 'Field or setting' | 'What is looked for', word: string) => {
  await planPanel(page).getByLabel('Add to').selectOption({ label: block })
  await planPanel(page).getByRole('textbox', { name: 'Add a word' }).fill(word)
  await planPanel(page).getByRole('textbox', { name: 'Add a word' }).press('Enter')
}
// The note under each provider, from the stored provider row (S23b copy).
const providerNote = (p: Provider) => p.required ? 'semantic and keyword · required: the search and the citation chain run on OpenAlex'
  : !p.in_scope ? 'not among this research’s sources' : !p.configured ? 'not set up · needs a key in Settings'
  : p.provider_id === 'semantic_scholar' ? 'abstracts, and one bulk query at Detailed depth' : p.provider_id === 'scopus' ? 'abstracts, once its full view is confirmed' : 'abstracts'

async function newResearch(api: Api, question: string, scope = 'academic') {
  const created = await post(api, '/api/researches', { question, model_connection: 'codex', requested_model: 'fixture-model', effort: 'standard', source_scope: scope })
  expect(created.status()).toBe(201)
  return (await created.json()).research.id as string
}

test.describe.serial('S23b: the Search plan panel', () => {
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
    expect((await post(api, `/api/researches/${rid}/runs`, { kind: 'discovery' }, { 'Idempotency-Key': `plan-discovery-${rid}` })).ok()).toBe(true)
    await settled(api, rid, ['discovery', 'answer'])
    page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  })
  test.afterAll(async () => { await page?.close(); await api?.context.dispose(); await server.stop() })

  test('Edit plan opens the stored plan of the revision it names: words, queries, criterion and sources', async () => {
    const stored = await planOf(api, rid)
    expect(stored.plan).not.toBeNull()
    const plan = stored.plan!
    await visit(page, research())
    const opened = await openPlanPanel(page)
    await expect(page).toHaveURL(/\/plan$/)
    await expect(opened.getByRole('heading', { name: 'Search plan' })).toBeFocused()
    // Where the plan came from and which revision it belongs to, from the stored view.
    const origin = stored.origin === 'model' ? 'The fast path wrote this plan from your question and ran it without asking.'
      : 'Code built this plan from the question’s words and ran it without asking.'
    await expect(opened.locator('.plan-panel > p').first()).toHaveText(`${origin} Plan frozen for revision ${stored.based_on!.scope_revision}. Change anything and search again: saving makes revision ${stored.scope_revision + 1}; the current answer stays with revision ${stored.scope_revision}.`)
    // The words of each block, as stored.
    await expect(chips(page, 'setting')).toHaveText(plan.setting.map(row => row.term))
    await expect(chips(page, 'task')).toHaveText(plan.task.map(row => row.term))
    // The stored queries, read only, in their order.
    const queries = opened.locator('textarea.mono')
    await expect(queries).toHaveCount(stored.queries.length)
    for (const [i, query] of stored.queries.entries()) {
      await expect(queries.nth(i)).toHaveValue(query.query_text)
      await expect(queries.nth(i)).toHaveAttribute('readonly', '')
    }
    // The criterion, editable; its parts are kept as stored and named.
    await expect(opened.getByRole('textbox', { name: 'Inclusion criterion' })).toHaveValue(plan.criterion!.text)
    await expect(opened).toContainText(`Its parts and their phrases stay as stored: ${plan.criterion!.parts.map(part => part.name).join(', ')}.`)
    // Sources: OpenAlex ticked and locked with its reason; each other provider as the server reports it; a source that
    // cannot run is not offered.
    for (const provider of stored.providers) {
      const box = opened.getByRole('checkbox', { name: new RegExp(`^${NAMES[provider.provider_id]} `) })
      await expect(box).toBeChecked({ checked: provider.required || provider.checked })
      if (provider.required || !(provider.in_scope && provider.configured)) await expect(box).toBeDisabled()
      else await expect(box).toBeEnabled()
      await expect(opened.locator('.provs label', { hasText: NAMES[provider.provider_id] }).locator('small')).toHaveText(providerNote(provider))
    }
    await expect(opened).toContainText('Crossref is still asked for PDF links when full text is fetched, even when it is unticked here.')
    // The English sentence the semantic search sends for this revision, when one is stored (§2.2).
    const english = ((await (await api.context.get(`/api/researches/${rid}`)).json()) as { semantic?: { english_question: { text: string } | null } }).semantic?.english_question?.text
    if (english) await expect(opened.locator('.plan-english')).toHaveText(`English question for the semantic search${english}`)
    else await expect(opened.locator('.plan-english')).toHaveCount(0)
    // A rule the stored plan breaks is named before anything is sent.
    if (stored.issues.length) await expect(opened.locator('.plan-issues')).toContainText('This plan breaks a rule, so it cannot be saved until you change it:')
    await shot(page, 's23b-plan-panel')
  })

  test('a refused plan keeps the draft and names each rule; nothing is saved', async () => {
    const before = await viewOf(api, rid)
    const opened = await openPlanPanel(page)
    // A word for each block, one of them written with query syntax, which the term rules refuse.
    await addWord(page, 'Field or setting', 'release timing')
    await addWord(page, 'What is looked for', '"release" timing')
    const refused = page.waitForResponse(r => r.url().endsWith('/search-plan') && r.request().method() === 'POST')
    await searchButton(page).click()
    expect((await refused).status()).toBe(422)
    const issues = opened.locator('.plan-issues')
    await expect(issues).toContainText('Not saved. The plan breaks these rules:')
    await expect(issues).toContainText('“"release" timing” holds quotation marks, brackets or AND, OR, NOT.')
    // The draft is still on screen, no search was asked for and no revision was made.
    await expect(chips(page, 'task').last()).toHaveText('"release" timing')
    await expect(chips(page, 'setting').last()).toHaveText('release timing')
    expect((await viewOf(api, rid)).research.current_scope_revision).toBe(before.research.current_scope_revision)
    expect((await viewOf(api, rid)).runs.filter(r => r.kind === 'discovery')).toHaveLength(before.runs.filter(r => r.kind === 'discovery').length)
    // Changing the draft clears the refusal; Cancel drops the draft.
    await opened.getByRole('button', { name: 'Remove "release" timing' }).click()
    await expect(opened.locator('.plan-issues')).toHaveCount(0)
    await opened.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(planPanel(page)).toHaveCount(0)
  })

  test('Cancel drops the draft and sends nothing', async () => {
    const before = await viewOf(api, rid)
    await openPlanPanel(page)
    let posts = 0
    const count = (request: { method: () => string; url: () => string }) => { if (request.method() === 'POST' && request.url().includes(`/api/researches/${rid}/`)) posts++ }
    page.on('request', count)
    await addWord(page, 'Field or setting', 'cancelled word')
    await expect(chips(page, 'setting').last()).toHaveText('cancelled word')
    await planPanel(page).getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(planPanel(page)).toHaveCount(0)
    page.off('request', count)
    expect(posts).toBe(0)
    expect((await viewOf(api, rid)).research.current_scope_revision).toBe(before.research.current_scope_revision)
    await openPlanPanel(page)
    await expect(chips(page, 'setting')).not.toContainText(['cancelled word'])
    await closePanel(page)
  })

  test('words, criterion and a provider edited, then Search again saves a new revision and starts its search', async () => {
    const stored = await planOf(api, rid)
    const plan = stored.plan!
    const opened = await openPlanPanel(page)
    // One word added to each block that needs it, one stored task word removed, the criterion reworded, one optional
    // provider that can run unticked.
    await addWord(page, 'Field or setting', 'molecular communication')
    const dropped = plan.task.at(-1)!.term
    if (plan.task.length > 1) await opened.getByRole('button', { name: `Remove ${dropped}`, exact: true }).click()
    const criterion = `${plan.criterion!.text} SYNTHETIC: edited by the person.`
    await opened.getByRole('textbox', { name: 'Inclusion criterion' }).fill(criterion)
    const optional = stored.providers.find(p => !p.required && p.checked && p.in_scope && p.configured)!
    await opened.getByRole('checkbox', { name: new RegExp(`^${NAMES[optional.provider_id]} `) }).uncheck()
    await expect(opened).toContainText('The queries above are the stored ones; the edited words are compiled into a new query when the search starts.')
    const saved = page.waitForResponse(r => r.url().endsWith('/search-plan') && r.request().method() === 'POST')
    const started = page.waitForResponse(r => r.url().endsWith(`/api/researches/${rid}/runs`) && r.request().method() === 'POST')
    // The panel's message is the only start announcement; the fixture's run can finish within seconds, after which the
    // page announces the finished search, so the message is caught as it appears.
    const toastText = page.waitForFunction(() => [...document.querySelectorAll('.toast')].map(el => el.textContent ?? '').find(text => text.includes('Plan saved as revision')) ?? false, null, { polling: 50 })
    await searchButton(page).click()
    const savedView = await (await saved).json() as PlanView
    expect((await started).ok()).toBe(true)
    const revision = savedView.scope_revision
    expect(revision).toBe(stored.scope_revision + 1)
    expect(await (await toastText).jsonValue()).toContain(`Plan saved as revision ${revision} of the question. The search started.`)
    await expect(page.locator('.toast', { hasText: 'Search & screening started.' })).toHaveCount(0)
    await expect(planPanel(page)).toHaveCount(0)
    // What the server stored is the edited plan, as the person's, for the new revision.
    const now = await planOf(api, rid)
    expect(now.scope_revision).toBe(revision)
    expect(now.origin).toBe('user')
    expect(now.plan!.setting.map(row => row.term)).toEqual([...plan.setting.map(row => row.term), 'molecular communication'])
    expect(now.plan!.task.map(row => row.term)).toEqual(plan.task.length > 1 ? plan.task.slice(0, -1).map(row => row.term) : plan.task.map(row => row.term))
    expect(now.plan!.criterion!.text).toBe(criterion)
    expect(now.plan!.providers).not.toContain(optional.provider_id)
    expect(now.plan!.providers).toContain('openalex')
    // The run the server started searches that revision.
    const view = await viewOf(api, rid)
    expect(view.runs.some(r => r.kind === 'discovery' && r.scope_revision === revision)).toBe(true)
    await settled(api, rid, ['discovery'], revision)
    await visit(page, research())
    await expect(page.locator('.chat-step-line', { hasText: 'Planned the searches from your saved plan' })).toBeVisible()
    const reopened = await openPlanPanel(page)
    await expect(reopened.locator('.plan-panel > p').first()).toContainText(`This plan was saved by you. Saved for revision ${revision} and frozen by its search.`)
    await expect(reopened.locator('label', { hasText: 'Query 1 · your plan' })).toBeVisible()
    await expect(chips(page, 'setting')).toHaveText(now.plan!.setting.map(row => row.term))
    await expect(reopened.getByRole('checkbox', { name: new RegExp(`^${NAMES[optional.provider_id]} `) })).not.toBeChecked()
    await closePanel(page)
  })

  test('a revision saved elsewhere while editing shows a conflict and keeps the draft', async () => {
    const opened = await openPlanPanel(page)
    await addWord(page, 'What is looked for', 'draft word')
    // Another window saves a plan: the research moves to the next revision.
    const other = await planOf(api, rid)
    const response = await post(api, `/api/researches/${rid}/search-plan`, { expected_version: other.expected_version, plan: { ...other.plan, criterion: { ...other.plan!.criterion, text: `${other.plan!.criterion!.text} Other window.` } } })
    expect(response.ok(), await response.text()).toBe(true)
    const next = ((await response.json()) as PlanView).scope_revision
    const conflict = opened.locator('.notice', { hasText: `Revision ${next} of this research was saved while you edited` })
    await expect(conflict).toBeVisible()
    await expect(chips(page, 'task').last()).toHaveText('draft word')
    await expect(searchButton(page)).toBeDisabled()
    await conflict.getByRole('button', { name: `Base my draft on revision ${next}` }).click()
    await expect(conflict).toHaveCount(0)
    await expect(chips(page, 'task').last()).toHaveText('draft word')
    await expect(searchButton(page)).toBeEnabled()
    await planPanel(page).getByRole('button', { name: 'Cancel', exact: true }).click()
    expect((await viewOf(api, rid)).research.current_scope_revision).toBe(next)
  })

  test('a revision saved between the save and the start: the server refuses the start, the conflict shows and the draft stays', async () => {
    await visit(page, research())
    // The ⋯ menu's "Search plan" row opens the panel whatever the plan step shows.
    await page.getByRole('button', { name: 'Research actions' }).click()
    await page.getByRole('menuitem', { name: 'Search plan' }).click()
    const opened = planPanel(page)
    await expect(opened).toBeVisible()
    await addWord(page, 'What is looked for', 'raced word')
    const discoveries = (await viewOf(api, rid)).runs.filter(r => r.kind === 'discovery').length
    // Another window saves a plan after this panel's save and before its start request reaches the server.
    let other = 0
    await page.route(`**/api/researches/${rid}/runs`, async route => {
      if (route.request().method() !== 'POST') return route.fallback()
      const shown = await planOf(api, rid)
      const saved = await post(api, `/api/researches/${rid}/search-plan`, { expected_version: shown.expected_version, plan: { ...shown.plan, criterion: { ...shown.plan!.criterion, text: `${shown.plan!.criterion!.text} Raced.` } } })
      expect(saved.ok(), await saved.text()).toBe(true)
      other = ((await saved.json()) as PlanView).scope_revision
      await route.continue()
    })
    const saved = page.waitForResponse(r => r.url().endsWith('/search-plan') && r.request().method() === 'POST')
    const start = page.waitForResponse(r => r.url().endsWith(`/api/researches/${rid}/runs`) && r.request().method() === 'POST')
    await searchButton(page).click()
    const mine = ((await (await saved).json()) as PlanView).scope_revision
    expect((await start).status()).toBe(409)
    await page.unroute(`**/api/researches/${rid}/runs`)
    expect(other).toBe(mine + 1)
    await expect(page.locator('.toast', { hasText: `Plan saved as revision ${mine} of the question. The search did not start:` })).toBeVisible()
    await expect(opened.locator('.notice', { hasText: `Revision ${other} of this research was saved while you edited` })).toBeVisible()
    await expect(chips(page, 'task').last()).toHaveText('raced word')
    await expect(searchButton(page)).toBeDisabled()
    // No run was created for either revision.
    expect((await viewOf(api, rid)).runs.filter(r => r.kind === 'discovery')).toHaveLength(discoveries)
    // The other window's plan (it started from the plan this panel saved, with its own criterion) replaces the draft on request.
    await opened.getByRole('button', { name: `Show the plan of revision ${other}` }).click()
    await expect(opened.locator('.notice', { hasText: 'was saved while you edited' })).toHaveCount(0)
    await expect(opened.getByRole('textbox', { name: 'Inclusion criterion' })).toHaveValue(/ Raced\.$/)
    await closePanel(page)
  })

  test('a read of the plan that fails after the first one is shown with Try again, and the draft stays', async () => {
    // The current revision was saved by another window and has not searched: the ⋯ menu opens the panel.
    await page.getByRole('button', { name: 'Research actions' }).click()
    await page.getByRole('menuitem', { name: 'Search plan' }).click()
    const opened = planPanel(page)
    await expect(opened).toBeVisible()
    await addWord(page, 'What is looked for', 'kept word')
    let fail = true
    await page.route(`**/api/researches/${rid}/search-plan`, route => (route.request().method() === 'GET' && fail
      ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'SYNTHETIC outage' }) }) : route.fallback()))
    // A rename in another window moves the research's version, so the panel reads its plan again.
    const view = await viewOf(api, rid)
    expect((await post(api, `/api/researches/${rid}/title`, { title: 'SYNTHETIC renamed research', expected_version: view.research.version })).ok()).toBe(true)
    const notice = opened.locator('.plan-refresh')
    await expect(notice).toContainText('Could not read the search plan again: SYNTHETIC outage. The plan shown is the one last read; your draft is kept.')
    await expect(chips(page, 'task').last()).toHaveText('kept word')
    fail = false
    await notice.getByRole('button', { name: 'Try again' }).click()
    await expect(opened.locator('.plan-refresh')).toHaveCount(0)
    await expect(chips(page, 'task').last()).toHaveText('kept word')
    await page.unroute(`**/api/researches/${rid}/search-plan`)
    await planPanel(page).getByRole('button', { name: 'Cancel', exact: true }).click()
  })

  test('a changed seed PDF is accepted from the thread and makes a new revision; the PDFs are chosen in the panel', async () => {
    const seed = path.join(server.dataDir, 'seed.pdf')
    expect(spawnSync(PYTHON, [SERVER, '--data-dir', server.dataDir, '--port', '0', '--write-seed-pdf', seed], { cwd: REPO, env: { ...process.env, PYTHONPATH: REPO } }).status).toBe(0)
    const sid = await newResearch(api, '[stale-seed] SYNTHETIC: How do k-connected sensor networks trade lifetime for energy?', 'attached_and_academic')
    const uploaded = await api.context.post(`/api/researches/${sid}/uploads`, { multipart: { file: { name: 'SYNTHETIC seed.pdf', mimeType: 'application/pdf', buffer: readFileSync(seed) } }, headers: { 'x-deixis-csrf': api.token } })
    expect(uploaded.ok(), await uploaded.text()).toBe(true)
    const file = (await uploaded.json()).uploaded_source_version_id as string
    const chosen = await post(api, `/api/researches/${sid}/seed`, { source_version_ids: [file], expected_version: (await viewOf(api, sid)).research.version })
    expect(chosen.ok(), await chosen.text()).toBe(true)
    expect((await post(api, `/api/researches/${sid}/runs`, { kind: 'discovery' }, { 'Idempotency-Key': `plan-seed-${sid}` })).ok()).toBe(true)
    await settled(api, sid, ['discovery', 'answer'])
    // [stale-seed] replaces the seed's file once the answer is written.
    await expect.poll(async () => (await viewOf(api, sid)).scope.seed_status, { timeout: 60_000 }).toBe('stale')
    // A second readable PDF, so the choice can change after the changed text is accepted.
    const second = path.join(server.dataDir, 'second.pdf')
    expect(spawnSync(PYTHON, [SERVER, '--data-dir', server.dataDir, '--port', '0', '--write-replacement-pdf', second], { cwd: REPO, env: { ...process.env, PYTHONPATH: REPO } }).status).toBe(0)
    const added = await api.context.post(`/api/researches/${sid}/uploads`, { multipart: { file: { name: 'SYNTHETIC second.pdf', mimeType: 'application/pdf', buffer: readFileSync(second) } }, headers: { 'x-deixis-csrf': api.token } })
    expect(added.ok(), await added.text()).toBe(true)
    const before = (await viewOf(api, sid)).research.current_scope_revision
    await visit(page, research(sid))
    const line = page.locator('.research-seed')
    await expect(line.locator('.notice')).toHaveText('A selected PDF changed or was removed. Select the current PDFs again before searching.')
    // The PDFs guiding the search and their choice sit in the Search plan panel.
    await line.getByRole('button', { name: 'Choose PDFs' }).click()
    const seeds = planPanel(page).locator('.plan-seeds')
    await expect(seeds).toBeVisible()
    const title = (await viewOf(api, sid)).scope.seeds[0].title
    await expect(seeds.getByRole('checkbox', { name: title, exact: true })).toBeChecked()
    await shot(page, 's23b-plan-seeds-stale')
    await closePanel(page)
    const accepted = page.waitForResponse(r => r.url().endsWith(`/api/researches/${sid}/seed`) && r.request().method() === 'POST')
    await line.getByRole('button', { name: 'Use current PDF text' }).click()
    expect((await accepted).ok()).toBe(true)
    await expect.poll(async () => { const v = await viewOf(api, sid); return [v.research.current_scope_revision, v.scope.seed_status] }).toEqual([before + 1, 'ready'])
    // The new revision has not searched, so it has no plan step: the line stays, without the notice, and still opens the
    // panel, where the choice of PDFs can change before the next search.
    await expect(line.locator('.notice')).toHaveCount(0)
    await expect(line.getByRole('button', { name: 'Use current PDF text' })).toHaveCount(0)
    await line.getByRole('button', { name: 'Choose PDFs' }).click()
    const choice = planPanel(page).locator('.plan-seeds')
    const candidates = choice.getByRole('checkbox')
    await expect(candidates).toHaveCount(2)
    const unticked = choice.locator('label', { has: page.locator('input:not(:checked)') })
    await expect(unticked).toHaveCount(1)
    await unticked.getByRole('checkbox').check()
    const chosen2 = page.waitForResponse(r => r.url().endsWith(`/api/researches/${sid}/seed`) && r.request().method() === 'POST')
    await choice.getByRole('button', { name: 'Use selected PDFs' }).click()
    expect((await chosen2).ok()).toBe(true)
    await expect.poll(async () => { const v = await viewOf(api, sid); return [v.research.current_scope_revision, v.scope.seeds.length] }).toEqual([before + 2, 2])
    await expect(choice.getByRole('checkbox', { checked: true })).toHaveCount(2)
    await closePanel(page)
  })

  test('at 390 px the panel is a dialog and fits the screen', async () => {
    await page.setViewportSize({ width: 390, height: 844 })
    await visit(page, `${research()}/plan`)
    const opened = page.getByRole('dialog', { name: 'Search plan' })
    await expect(opened).toBeVisible()
    await expect(opened.getByRole('button', { name: 'Search again with this plan' })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    expect(await opened.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
    await shot(page, 's23b-plan-panel-390')
    await page.setViewportSize({ width: 1280, height: 900 })
  })

  test('after a withdrawn revision the panel names the next free number, not the current one plus one (D67)', async () => {
    await settled(api, rid, ['discovery', 'answer'])
    const before = await viewOf(api, rid)
    const revised = await post(api, `/api/researches/${rid}/scope`, { question: 'SYNTHETIC write the report from the full texts', expected_version: before.research.version, key_terms: null })
    expect(revised.ok(), await revised.text()).toBe(true)
    const opened = (await revised.json()) as View
    const withdrawn = await post(api, `/api/researches/${rid}/scope/withdraw`, { expected_version: opened.research.version, revision: opened.research.current_scope_revision })
    expect(withdrawn.ok(), await withdrawn.text()).toBe(true)
    const after = (await withdrawn.json()) as View
    expect(after.research.current_scope_revision).toBe(before.research.current_scope_revision)
    expect(after.research.next_scope_revision).toBe(before.research.current_scope_revision + 2)
    await visit(page, `${research()}/plan`)
    await expect(planPanel(page).locator('.plan-panel > p').first()).toContainText(`saving makes revision ${after.research.next_scope_revision}`)
  })
})
