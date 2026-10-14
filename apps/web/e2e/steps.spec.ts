import { expect, request as apiRequest, test, type APIRequestContext, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'
import { PANEL_TITLES, closePanel, openPlanPanel, panel } from './panels'

// UI parity S9: the steps list (mockup R14-R16, R18). One line per phase with an 18px icon: the phase's icon once done,
// a spinner and shimmering words while live, the warning sign where the run stopped; a chevron takes the icon's place
// on hover and while the details are open. The details of each phase come from stored records (R15); a live run names
// what follows in one "Next: … · stage N of M" line (R16); a stopped run carries Resume run and Cancel run in the
// notice under its steps (R18).
//
// Its own fixture server with full-text reading on, so the [parity] research reads full texts as the mockup's does.
// Every record is SYNTHETIC; a passing case shows how the page behaves, not the quality of a search or an answer.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

const PARITY = '[parity] How has the relationship between k-connectivity, network lifetime and energy consumption been modeled in SYNTHETIC wireless sensor networks?'
const MOLECULE = 'How is SYNTHETIC molecule release scheduling optimized?'

class StepsServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-steps-'))
  constructor(readonly port: number) {}
  async start() {
    const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend'), DEIXIS_FIXTURE_FULLTEXT: 'on',
      // A second SYNTHETIC model, so the model-down notice's "Choose another model" has one to move to (S27).
      DEIXIS_FIXTURE_SECOND_MODEL: 'on' }
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`http://127.0.0.1:${this.port}/api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`steps fixture server on ${this.port} did not start`)
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
type Funnel = { retrieved: number; chained: number; unique: number; abstracts_read: number; candidates: number }
type View = {
  runs: Array<{ id: string; kind: string; status: string; budget: { fast_path?: { K?: number }; max_model_calls?: number }; steps?: Array<{ kind: string; status: string; operation_key: string }>
    approval?: { approved: { terms: Array<{ phrase: string; dropped: string | null; searched?: boolean | null; left_out?: string | null }> } } | null }>
  scope: { literature_model: string | null }
  model_changes?: Array<{ role: string; from: { model: string | null }; to: { model: string | null }; changed_at: string }>
  counts: { queue: number; funnel?: Funnel | null; flow?: { five: { not_read_not_tried: number }; buckets: { not_screened: number; out_of_scope_model: number; out_of_scope_code: number } } | null }
  answers: Array<{ run_id: string; claims: Array<{ evidence: Array<{ passage_id: string; source_version_id: string }> }>; inputs_given: { sources: number; passages: number } | null }>
}
const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
const post = (api: Api, url: string, data: unknown) => api.context.post(url, { data, headers: { 'x-deixis-csrf': api.token } })
const viewOf = async (api: Api, rid: string) => (await (await api.context.get(`/api/researches/${rid}`)).json()) as View
const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`), animations: 'disabled', fullPage: true })
const line = (page: Page, text: string | RegExp) => page.locator('.chat-step-line', { hasText: text })
const step = (page: Page, text: string | RegExp) => page.locator('.chat-step', { has: line(page, text) })
// The lucide name of the icon a step line shows first (the phase's icon, the spinner or the warning sign).
const iconOf = (page: Page, text: string | RegExp) => step(page, text).locator('.chat-step-icon > :first-child').evaluate(el =>
  [...el.classList].find(c => c.startsWith('lucide-'))?.slice('lucide-'.length) ?? el.className)

async function create(api: Api, question: string, effort = 'quick') {
  const created = await post(api, '/api/researches', { question, model_connection: 'codex', requested_model: 'fixture-model', effort })
  expect(created.status()).toBe(201)
  const rid = (await created.json()).research.id as string
  expect((await post(api, `/api/researches/${rid}/runs`, { kind: 'discovery' })).ok()).toBe(true)
  return rid
}
const settled = (api: Api, rid: string) => expect.poll(async () => {
  const view = await viewOf(api, rid)
  return view.runs.some(r => r.kind === 'discovery' && r.status === 'completed') && view.runs.some(r => r.kind === 'answer') && !view.runs.some(r => ACTIVE.has(r.status))
}, { timeout: 110_000 }).toBe(true)

test.describe.serial('S9: the steps list', () => {
  const server = new StepsServer(nextPort())
  let api: Api
  let page: Page
  let parityRid = ''

  test.beforeAll(async ({ browser }) => {
    await server.start()
    const context = await apiRequest.newContext({ baseURL: server.url(), extraHTTPHeaders: { origin: server.url() } })
    api = { context, token: (await (await context.get('/api/session')).json()).csrf_token as string }
    page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  })
  test.afterAll(async () => { await page?.close(); await api?.context.dispose(); await server.stop() })

  test('a finished research reads as seven phase lines, from the plan to the citation check, each with its icon', async () => {
    test.setTimeout(180_000)
    const rid = await create(api, PARITY, 'standard')
    parityRid = rid
    await settled(api, rid)
    const view = await viewOf(api, rid)
    const funnel = view.counts.funnel!
    const answer = view.answers[0]
    const evidence = answer.claims.flatMap(c => c.evidence)
    const cited = new Set(evidence.map(e => e.source_version_id)).size
    await page.goto(`${server.url()}/#/research/${rid}`)
    const lines = page.locator('.chat-steps .chat-step-line')
    await expect(lines).toHaveCount(7)
    // The words are the mockup's, with the counts the research recorded (§2.3: "read in full" names the selected pages).
    await expect(lines).toHaveText([
      'Planned the searches from the question’s words',
      `Searched OpenAlex · ${funnel.unique} unique works`,
      new RegExp(`^Followed one round of citations · \\d+ works? added, ${funnel.unique} in the pool$`),
      `Screened ${funnel.abstracts_read} abstracts twice · ${funnel.candidates} passed the abstract stage, ${view.counts.flow!.buckets.out_of_scope_model + view.counts.flow!.buckets.out_of_scope_code} out of scope`,
      new RegExp(`^Read \\d+ works in their full text \\(selected pages\\) · ${view.counts.flow!.five.not_read_not_tried} passed the abstract stage, full text not tried$`),
      `Wrote a source-linked answer · ${answer.claims.length} claims from ${cited} sources`,
      `Checked citations · ${evidence.length} of ${evidence.length} anchors located in their passages`,
    ])
    const icons = []
    for (const text of ['Planned', 'Searched', 'Followed', 'Screened', /^Read \d+ works/, 'Wrote', 'Checked']) icons.push(await iconOf(page, text))
    expect(icons).toEqual(['pencil-line', 'search', 'waypoints', 'list-checks', 'book-open', 'file-text', 'shield-check'])
    // A finished run shows no spinner and no "Next:" line; the models and Usage follow the steps.
    await expect(page.locator('.chat-steps .step-spin')).toHaveCount(0)
    await expect(page.locator('.chat-steps-next')).toHaveCount(0)
    await expect(page.locator('.usage-line').first()).toContainText('fixture-model')
    // Hover puts the chevron in the icon's place; opened, it stays and turns down.
    const plan = line(page, 'Planned')
    await expect(plan.locator('.chev')).toBeHidden()
    await plan.hover()
    await expect(plan.locator('.chev')).toBeVisible()
    await expect(plan.locator('.base')).toBeHidden()
    await page.mouse.move(0, 0)
    await shot(page, 's9-steps-done')
  })

  test('each phase opens to details from stored records', async () => {
    test.setTimeout(120_000)
    const rid = page.url().split('#/research/')[1].split('/')[0]
    const view = await viewOf(api, rid)
    const funnel = view.counts.funnel!
    const answer = view.answers[0]
    const detail = (text: string | RegExp) => step(page, text).locator('.chat-step-detail')
    const open = async (text: string | RegExp) => {
      await line(page, text).click()
      await expect(line(page, text)).toHaveAttribute('aria-expanded', 'true')
      await expect(step(page, text)).toHaveClass(/\bopen\b/)
      return detail(text)
    }
    // Plan: the search words, each query with who wrote it, the criterion, and that nobody reviewed the vocabulary.
    const plan = await open('Planned')
    await expect(plan).toContainText('Search words:')
    await expect(plan.locator('code').first()).toBeVisible()
    await expect(plan.locator('.step-row', { hasText: 'Query 1' })).toBeVisible()
    await expect(plan.locator('.step-row', { hasText: 'Inclusion criterion' })).toContainText('SYNTHETIC')
    await expect(plan).toContainText('Nobody reviewed the search vocabulary; the fast path went on without asking.')
    await expect(plan.locator('.step-row', { hasText: 'Time taken' })).toBeVisible()
    // D26: a word the frozen plan records as carried by no sent query is struck through and named with its stored reason
    // (the [parity] research's sixth task word is cut from the one OpenAlex keyword query a Standard run sends).
    const terms = view.runs.find(r => r.kind === 'discovery')!.approval!.approved.terms.filter(t => !t.dropped)
    const unsearched = terms.filter(t => t.searched === false)
    expect(unsearched.map(t => [t.phrase, t.left_out])).toEqual([['modeled', 'query_limit']])
    const words = plan.locator(':scope > div', { hasText: /^Search words:/ })
    await expect(words.locator('code.word-unsearched')).toHaveText(unsearched.map(t => t.phrase))
    await expect(words.locator('code:not(.word-unsearched)')).toHaveText(terms.filter(t => t.searched === true).map(t => t.phrase))
    await expect(plan.locator('.step-row', { hasText: 'Words not searched' })).toContainText('modeled: cut to keep the query within its length and syntax limits')
    // The Search plan panel marks the same stored word on its chip and names it under the blocks.
    const planned = await openPlanPanel(page)
    await expect(planned.locator('.kw > span.word-unsearched')).toHaveText(['modeled'])
    await expect(planned.locator('.plan-unsearched')).toHaveText('Words the frozen plan did not search: modeled: cut to keep the query within its length and syntax limits')
    await shot(page, 'p1-plan-unsearched')
    await closePanel(page)
    // Search: one row per query with what was taken of what the provider reported, and the merge by DOI.
    const search = await open('Searched')
    await expect(search.locator('.step-row', { hasText: 'OpenAlex · semantic' })).toContainText(/\d+ of \d+ taken/)
    await expect(search.locator('.step-row', { hasText: 'OpenAlex · keyword, query 1' })).toContainText(/\d+ of \d+ taken/)
    // The kind comes from the step's operation key, and the text each request sent is shown under its row.
    await expect(search.locator('.step-row', { hasText: 'OpenAlex · keyword, query 1' }).locator('.step-row-query')).not.toBeEmpty()
    await expect(search.locator('.step-row', { hasText: 'OpenAlex · semantic' }).locator('.step-row-query')).not.toBeEmpty()
    await expect(search.locator('.step-row', { hasText: 'Records merged by DOI' })).toContainText(`${funnel.retrieved} → ${funnel.unique}`)
    // Chaining: the seeds' reference lists and citing works, as records returned, and the requests the chain sent.
    const chain = await open('Followed')
    await expect(chain.locator('.step-row', { hasText: /Reference lists of \d+ seed works/ })).toContainText(/records? returned/)
    await expect(chain.locator('.step-row', { hasText: 'Works citing the seeds' })).toContainText(/records? returned/)
    await expect(chain).toContainText(/\d+ requests? sent/)
    // How the seeds are chosen and which works are kept before the cutoff, as the approval record said it before S9.
    await expect(chain).toContainText('Works you verified are not used as seeds.')
    await expect(chain).toContainText('its reply arrives a few seconds before the ranking stage ends')
    // Screening: read twice, how many were read and not, how many passed, and the queue, which opens its panel.
    const screen = await open('Screened')
    await expect(screen).toContainText('Each batch is read twice by the literature model. An abstract alone never includes a work.')
    await expect(screen.locator('.step-row', { hasText: `${funnel.abstracts_read} of the ranking read` })).toContainText(`${view.counts.flow!.buckets.not_screened} not read`)
    await expect(screen.locator('.step-row', { hasText: 'Passed the abstract stage' })).toContainText(String(funnel.candidates))
    await expect(screen.locator('.step-row', { hasText: 'Waiting for your decision' })).toContainText(String(view.counts.queue))
    await screen.getByRole('button', { name: 'Open' }).click()
    await expect(panel(page, PANEL_TITLES.queue)).toBeVisible()
    await page.keyboard.press('Escape')
    // Reading: what was retrieved and read (selected pages), what passed without a try, and the depth's limit.
    const read = await open(/^Read \d+ works/)
    await expect(read.locator('.step-row', { hasText: 'Full text read (selected pages)' })).toContainText(/\d+/)
    await expect(read.locator('.step-row', { hasText: 'Passed the abstract stage, full text not tried' })).toContainText(String(view.counts.flow!.five.not_read_not_tried))
    await expect(read.locator('.step-row', { hasText: 'Full-text limit at Standard depth' })).toContainText(String(view.runs.find(r => r.kind === 'discovery')!.budget.fast_path!.K))
    await read.getByRole('button', { name: 'Get more full text' }).click()
    await expect(panel(page, PANEL_TITLES.pdfs)).toBeVisible()
    await page.keyboard.press('Escape')
    // Answer: the passages given (given, not "inspected"), the passages cited, the model, and the flow when it started.
    const written = await open('Wrote')
    await expect(written.locator('.step-row', { hasText: 'Passages given to the model' })).toContainText(`${answer.inputs_given!.passages} from ${answer.inputs_given!.sources} sources`)
    await expect(written.locator('.step-row', { hasText: 'Passages cited' })).toContainText(String(new Set(answer.claims.flatMap(c => c.evidence.map(e => e.passage_id))).size))
    await expect(written.locator('.step-row', { hasText: 'Answer model' })).toContainText('fixture-model')
    await expect(written).toContainText('When the answer started:')
    // Check: every anchor located in code, and no claim review recorded for an answer no reviewer model read.
    const checked = await open('Checked')
    await expect(checked).toContainText('Each cited quote was found in a stored passage that was given to this step.')
    await expect(checked.locator('.step-row', { hasText: 'Claim review' })).toContainText('Not recorded for this answer')
    await shot(page, 's9-steps-details')
    // Closing a phase folds its details again.
    await line(page, 'Checked').click()
    await expect(detail('Checked')).toHaveCount(0)
  })

  test('a full-text pass that failed or has an unknown outcome leaves its work out of the read count', async () => {
    const rid = page.url().split('#/research/')[1].split('/')[0]
    const view = await viewOf(api, rid)
    const discovery = view.runs.find(r => r.kind === 'discovery')!
    const workOf = (key: string) => key.replace(/^fulltext_adjudication:/, '').replace(/:[^:]*$/, '')
    const passes = (discovery.steps ?? []).filter(s => s.kind === 'model:fulltext_adjudication' && s.status === 'succeeded')
    const read = [...new Set(passes.map(s => workOf(s.operation_key)))].filter(w => passes.filter(s => workOf(s.operation_key) === w).length >= 2)
    expect(read.length).toBeGreaterThanOrEqual(2)
    await expect(line(page, /^Read \d+ works/)).toContainText(`Read ${read.length} works`)
    // The view as it would be if one pass of one work had failed and one pass of another had no known outcome.
    const changed = new Map([[read[0], 'failed'], [read[1], 'outcome_unknown']])
    await page.route(url => url.pathname === `/api/researches/${rid}`, async route => {
      const response = await route.fetch()
      const body = await response.json()
      const run = body.runs.find((r: { id: string }) => r.id === discovery.id)
      const done = new Set<string>()
      for (const s of run.steps) {
        const work = workOf(s.operation_key)
        if (s.kind === 'model:fulltext_adjudication' && changed.has(work) && !done.has(work)) { s.status = changed.get(work); done.add(work) }
      }
      await route.fulfill({ response, json: body })
    })
    await page.reload()
    const reading = line(page, /^Read \d+ works?/)
    await expect(reading).toContainText(`Read ${read.length - 2} work`)
    await reading.click()
    const detail = step(page, /^Read \d+ works?/).locator('.chat-step-detail')
    await expect(detail.locator('.step-row', { hasText: 'Full text read (selected pages)' })).toContainText(String(read.length - 2))
    await expect(detail.locator('.step-row', { hasText: 'Not read: a call failed or its outcome is unknown' })).toContainText('2')
    await page.unrouteAll({ behavior: 'wait' })
  })

  test('a live phase spins and shimmers, does not open, and the Next line names what follows', async () => {
    test.setTimeout(150_000)
    const release = path.join(server.dataDir, 'answer-release')
    rmSync(release, { force: true })
    const rid = await create(api, `[answer-hold] ${MOLECULE}`)
    try {
      await page.goto(`${server.url()}/#/research/${rid}`)
      const writing = line(page, 'Writing a source-linked answer…')
      await expect(writing).toBeVisible({ timeout: 60_000 })
      await expect(writing).toBeDisabled()
      await expect(writing.locator('.step-spin')).toBeVisible()
      await expect(writing.locator('.shimmer-text')).toHaveText('Writing a source-linked answer…')
      // The answer continues the count of the discovery it answers from: its stage is the one before the last.
      const next = page.locator('.chat-steps-next')
      await expect(next).toHaveText(/^Next: check citations · stage \d+ of \d+$/)
      const [stage, total] = ((await next.textContent()) ?? '').match(/stage (\d+) of (\d+)/)!.slice(1).map(Number)
      expect([stage, total]).toEqual([total - 1, total])
      expect(total).toBeGreaterThanOrEqual(6)
      // While it runs, Pause and Cancel sit beside the chip in the topbar.
      await expect(page.locator('.research-topbar').getByRole('button', { name: 'Pause' })).toBeVisible()
      await shot(page, 's9-steps-live')
    } finally { writeFileSync(release, 'SYNTHETIC release\n') }
    await settled(api, rid)
    await expect(line(page, /^Wrote /)).toBeEnabled({ timeout: 30_000 })
    await expect(page.locator('.chat-steps-next')).toHaveCount(0)
  })

  test('a paused run marks its phase and carries Resume run and Cancel run in the notice under the steps', async () => {
    test.setTimeout(180_000)
    const rid = await create(api, `[pause-at-read] ${MOLECULE}`)
    await page.goto(`${server.url()}/#/research/${rid}`)
    const stopped = page.locator('.chat-step.att')
    await expect(stopped.locator('.chat-step-line')).toHaveText('Paused while screening', { timeout: 60_000 })
    expect(await stopped.locator('.chat-step-icon > :first-child').evaluate(el => el.classList.contains('lucide-triangle-alert'))).toBe(true)
    const note = page.locator('.chat-note.notice.is-warning')
    await expect(note).toContainText('Paused after the current call. Nothing was lost: the finished steps are kept and will not run again.')
    await expect(note.getByRole('button', { name: 'Resume run' })).toBeVisible()
    await expect(note.getByRole('button', { name: 'Cancel run' })).toBeVisible()
    await expect(page.locator('.research-topbar').getByRole('button', { name: /Resume|Cancel/ })).toHaveCount(0)
    await shot(page, 's9-steps-paused')
    await note.getByRole('button', { name: 'Resume run' }).click()
    await settled(api, rid)
    await expect(page.locator('.chat-note.notice')).toHaveCount(0, { timeout: 30_000 })
    await expect(page.locator('.chat-step.att')).toHaveCount(0)
    await expect(line(page, /^Screened /)).toBeVisible()
  })

  test('a run the model stopped reads "Stopped while", with the reason and Cancel run in the error notice', async () => {
    test.setTimeout(150_000)
    const rid = await create(api, `[model-down] ${MOLECULE}`)
    await page.goto(`${server.url()}/#/research/${rid}`)
    await expect(page.locator('.chat-step.att .chat-step-line')).toHaveText('Stopped while screening', { timeout: 60_000 })
    const note = page.locator('.chat-note.notice.is-error')
    await expect(note).toContainText('DEIXIS could not reach Codex.')
    await expect(note.getByRole('button', { name: 'Retry this step' })).toBeVisible()
    await shot(page, 's9-steps-stopped')
    await note.getByRole('button', { name: 'Cancel run' }).click()
    await expect.poll(async () => (await viewOf(api, rid)).runs.find(r => r.kind === 'discovery')?.status, { timeout: 30_000 }).toBe('cancelled')
    await expect(page.getByRole('button', { name: 'Retry this step' })).toHaveCount(0)
  })

  test('S27 (R17): the Usage box splits the run’s stored model calls by role and gives OpenAlex’s last stored budget', async () => {
    const view = await viewOf(api, parityRid)
    const discovery = view.runs.find(r => r.kind === 'discovery')!
    const usage = await (await api.context.get(`/api/usage?period=run&run_id=${discovery.id}`)).json() as { total: number; roles: Array<{ role: string; calls: number }> }
    const budget = await (await api.context.get('/api/openalex/budget-today')).json() as { remaining: number | null }
    expect(usage.total).toBeGreaterThan(0)
    await page.goto(`${server.url()}/#/research/${parityRid}`)
    const toggle = page.locator(`.chat-toggle[data-run-id="${discovery.id}"]`)
    const turn = page.locator('.chat-turn', { has: toggle })
    if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click()
    await turn.getByRole('button', { name: 'Usage', exact: true }).click()
    const box = turn.locator('.usage-box')
    // The calls and the roles they are split into come from one stored answer (model sessions by Settings role).
    const limit = discovery.budget.max_model_calls ?? 0
    const split = usage.roles.filter(r => r.calls > 0).map(r => `${r.role} ${r.calls}`).join(', ')
    await expect(box.locator('span').first()).toHaveText(limit && usage.total <= limit
      ? `The models were asked ${usage.total} times (limit ${limit}): ${split}.` : `The models were asked ${usage.total} times: ${split}.`)
    // The fixture's OpenAlex sends no rate-limit header: no figure is stored, so the budget reads as not known, never 0.
    await expect(box.locator('span').nth(1)).toHaveText(budget.remaining === null
      ? 'OpenAlex: no budget figure is stored since the daily reset (midnight UTC), so today’s budget is not known.'
      : /^OpenAlex: .* in its last stored response \(\d/)
    await shot(page, 's27-usage-box')
  })

  // S28 (R19), Sol round 1: "[oa-quota-first]" makes OpenAlex refuse its semantic request as a spent daily budget (HTTP
  // 429); the keyword request that follows is then closed in the app before sending. The expectation comes from what
  // the provider answered (a stored HTTP 429), not from the page's own rule: exactly one refusal, the rest not sent.
  type Search = { step_id: string; error: { service_kind?: string; http_status?: number | null } | null }
  type RunView = { runs: Array<{ id: string; kind: string; status: string; pause_reason?: string | null; steps?: Array<{ id: string; kind: string; status: string }> }>; search_runs: Search[] }
  const quotaCounts = async (rid: string) => {
    const stored = (await (await api.context.get(`/api/researches/${rid}`)).json()) as RunView
    const discovery = stored.runs.find(r => r.kind === 'discovery')!
    const searchSteps = (discovery.steps ?? []).filter(s => s.kind.startsWith('provider_search'))
    const rowOf = (id: string) => stored.search_runs.find(row => row.step_id === id)
    const refusedByProvider = searchSteps.filter(s => rowOf(s.id)?.error?.http_status === 429).length
    const closedInApp = searchSteps.filter(s => rowOf(s.id)?.error?.service_kind === 'quota_exhausted' && rowOf(s.id)?.error?.http_status == null).length
    return { discovery, refusedByProvider, closedInApp, finished: searchSteps.filter(s => s.status === 'succeeded').length }
  }

  test('S28 (R19): a completed run counts the budget refusal apart from the searches never sent; Retry and Add an OpenAlex key', async () => {
    test.setTimeout(150_000)
    const rid = await create(api, `[oa-quota-first] ${MOLECULE}`, 'detailed')
    await settled(api, rid)
    const { discovery, refusedByProvider, closedInApp, finished } = await quotaCounts(rid)
    expect(discovery.status).toBe('completed')
    expect(refusedByProvider).toBe(1)
    expect(closedInApp).toBeGreaterThan(0)
    expect(finished).toBeGreaterThan(0)
    await page.goto(`${server.url()}/#/research/${rid}`)
    const notice = page.locator('.chat-note.quota-notice')
    const notSent = closedInApp === 1 ? '1 search was not sent' : `${closedInApp} searches were not sent`
    await expect(notice.locator('p')).toHaveText(`1 search was refused (OpenAlex budget). ${notSent} after the OpenAlex budget ran out. The run went on with the ${finished} that finished.`)
    // The notice carries the retry, so the run foot does not repeat it.
    await expect(page.locator('.chat-run-foot').getByRole('button', { name: 'Retry failed searches' })).toHaveCount(0)
    await shot(page, 's28-quota-notice')
    // Retry failed searches queues the failed requests again on the same run.
    const control = page.waitForRequest(r => r.method() === 'POST' && r.url().endsWith(`/api/runs/${discovery.id}/retry_failed`))
    await notice.getByRole('button', { name: 'Retry failed searches' }).click()
    await control
    await expect(page.locator('.toast')).toContainText('Failed searches queued again.')
    // Add an OpenAlex key opens Settings with the OpenAlex sheet open.
    await notice.getByRole('button', { name: 'Add an OpenAlex key' }).click()
    await expect(page).toHaveURL(/#\/settings\/openalex$/)
    await expect(page.getByRole('dialog', { name: 'OpenAlex' })).toBeVisible()
    // Let the queued retry settle before the next test reuses the server.
    await expect.poll(async () => (await viewOf(api, rid)).runs.some(r => ACTIVE.has(r.status)), { timeout: 90_000 }).toBe(false)
  })

  test('S28 (R19): a run paused on the budget names the refusal and the searches not sent and offers Add an OpenAlex key', async () => {
    test.setTimeout(150_000)
    const rid = await create(api, `[oa-quota-first] ${MOLECULE}`)
    await expect.poll(async () => (await viewOf(api, rid)).runs.find(r => r.kind === 'discovery')?.status, { timeout: 90_000 }).toBe('paused')
    const { discovery, refusedByProvider, closedInApp } = await quotaCounts(rid)
    expect(discovery.pause_reason).toBe('provider_quota_exhausted')
    expect(refusedByProvider).toBe(1)
    expect(closedInApp).toBeGreaterThan(0)
    await page.goto(`${server.url()}/#/research/${rid}`)
    const notice = page.locator('.chat-note.notice', { has: page.locator('.quota-lines') })
    const notSent = closedInApp === 1 ? '1 search was not sent' : `${closedInApp} searches were not sent`
    await expect(notice.locator('.quota-lines')).toHaveText(`1 search was refused (OpenAlex budget). ${notSent} after the OpenAlex budget ran out.`)
    // Nothing went on: no "the run went on" sentence and no completed-run notice.
    await expect(notice).not.toContainText('The run went on')
    await expect(page.locator('.chat-note.quota-notice')).toHaveCount(0)
    await expect(notice.getByRole('button', { name: 'Resume run' })).toBeVisible()
    await shot(page, 's28-quota-paused')
    await notice.getByRole('button', { name: 'Add an OpenAlex key' }).click()
    await expect(page).toHaveURL(/#\/settings\/openalex$/)
    await expect(page.getByRole('dialog', { name: 'OpenAlex' })).toBeVisible()
    expect((await post(api, `/api/runs/${discovery.id}/cancel`, {})).ok()).toBe(true)
    await expect.poll(async () => (await viewOf(api, rid)).runs.some(r => ACTIVE.has(r.status)), { timeout: 60_000 }).toBe(false)
  })

  // Sol round 2: a retried search keeps its earlier search rows; the notice reads the step's latest stored failure.
  // "[oa-quota-net]" / "[oa-net-quota]" flip OpenAlex's semantic request between a spent budget and a refused
  // connection once `oa-flip` exists in the fixture data directory, so the retry fails the other way.
  type Attempts = { runs: Array<{ id: string; kind: string; status: string; steps?: Array<{ id: string; kind: string; status: string; error: { http_status?: number | null; service_kind?: string } | null }> }>; search_runs: Array<{ step_id: string; query_text: string; error: { http_status?: number | null; service_kind?: string } | null }> }
  const semanticAttempts = async (rid: string) => {
    const stored = (await (await api.context.get(`/api/researches/${rid}`)).json()) as Attempts
    const discovery = stored.runs.find(r => r.kind === 'discovery')!
    const ids = new Set((discovery.steps ?? []).filter(s => s.kind === 'provider_search:openalex').map(s => s.id))
    // The semantic request searches the question itself (its query text starts with the marker); the keyword query does not.
    const rows = stored.search_runs.filter(row => ids.has(row.step_id))
    const stepId = rows.find(row => row.query_text.startsWith('[oa-'))?.step_id ?? ''
    return { discovery, rows: rows.filter(row => row.step_id === stepId), step: (discovery.steps ?? []).find(s => s.id === stepId) }
  }
  const flip = path.join(server.dataDir, 'oa-flip')
  const retryAndSettle = async (rid: string, runId: string) => {
    writeFileSync(flip, '')
    const control = page.waitForRequest(r => r.method() === 'POST' && r.url().endsWith(`/api/runs/${runId}/retry_failed`))
    await page.locator('.chat-run-foot').getByRole('button', { name: 'Retry failed searches' }).click()
    await control
    await expect.poll(async () => { const v = await viewOf(api, rid); return v.runs.find(r => r.kind === 'discovery')?.status === 'completed' && !v.runs.some(r => ACTIVE.has(r.status)) }, { timeout: 90_000 }).toBe(true)
  }

  test('S28 (R19, Sol r2): a budget refusal retried into a refused connection is no longer counted as a budget stop', async () => {
    test.setTimeout(180_000)
    try {
      const rid = await create(api, `[oa-quota-net] ${MOLECULE}`)
      await expect.poll(async () => (await viewOf(api, rid)).runs.find(r => r.kind === 'discovery')?.status, { timeout: 90_000 }).toBe('paused')
      const before = (await semanticAttempts(rid)).discovery
      await page.goto(`${server.url()}/#/research/${rid}`)
      await expect(page.locator('.quota-lines')).toContainText('1 search was refused (OpenAlex budget).')
      await retryAndSettle(rid, before.id)
      const { rows, step } = await semanticAttempts(rid)
      // Stored: the first attempt was the provider's budget refusal, the latest a connection that never answered.
      expect(rows.map(row => row.error?.http_status ?? null)).toEqual([429, null])
      expect(step?.status).toBe('failed')
      expect(step?.error?.http_status ?? null).toBeNull()
      await page.reload()
      await expect(page.locator('.chat-run-foot').getByRole('button', { name: 'Retry failed searches' })).toBeVisible()
      await expect(page.locator('.chat-note.quota-notice')).toHaveCount(0)
      await expect(page.locator('.quota-lines')).toHaveCount(0)
      await expect(page.locator('.research-thread, main').first()).not.toContainText('budget ran out')
    } finally { rmSync(flip, { force: true }) }
  })

  test('S28 (R19, Sol r2): a refused connection retried into a budget refusal opens the notice with Add an OpenAlex key', async () => {
    test.setTimeout(180_000)
    try {
      const rid = await create(api, `[oa-net-quota] ${MOLECULE}`)
      await settled(api, rid)
      const before = (await semanticAttempts(rid)).discovery
      expect(before.status).toBe('completed')
      await page.goto(`${server.url()}/#/research/${rid}`)
      await expect(page.locator('.chat-note.quota-notice')).toHaveCount(0)
      await retryAndSettle(rid, before.id)
      const { discovery, rows, step } = await semanticAttempts(rid)
      // Stored: the first attempt never reached the provider, the latest is its budget refusal.
      expect(rows.map(row => row.error?.http_status ?? null)).toEqual([null, 429])
      expect(step?.error?.http_status).toBe(429)
      const finished = (discovery.steps ?? []).filter(s => s.kind.startsWith('provider_search') && s.status === 'succeeded').length
      await page.reload()
      const notice = page.locator('.chat-note.quota-notice')
      await expect(notice.locator('p')).toHaveText(`1 search was refused (OpenAlex budget). The run went on with the ${finished} that finished.`)
      await expect(notice.getByRole('button', { name: 'Add an OpenAlex key' })).toBeVisible()
    } finally { rmSync(flip, { force: true }) }
  })

  test('S27 (R20): Choose another model moves the stopped step’s role, recorded and shown; Retry this step sends it there', async () => {
    test.setTimeout(150_000)
    const rid = await create(api, `[model-down] ${MOLECULE}`)
    await page.goto(`${server.url()}/#/research/${rid}`)
    await expect(page.locator('.chat-step.att .chat-step-line')).toHaveText('Stopped while screening', { timeout: 60_000 })
    const note = page.locator('.chat-note.notice.is-error')
    await expect(note.getByRole('button')).toHaveText(['Retry this step', 'Choose another model', 'Cancel run'])
    // The model line names the model the planning calls went to, from their stored sessions (D15).
    const literature = page.locator('.chat-run-models').first().locator('.chat-run-model').filter({ hasText: /^Literature/ })
    await expect(literature).toHaveText(['Literature · Codex · fixture-model'])
    await note.getByRole('button', { name: 'Choose another model' }).click()
    const dialog = page.getByRole('dialog', { name: 'Choose another model' })
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText('Steps that already finished keep the model they ran on, and nothing is sent until you retry the step.')
    // The stopped step is abstract screening, run by the literature model.
    await expect(dialog.getByRole('combobox', { name: 'Role' })).toHaveText(/^Literature/)
    const use = dialog.getByRole('button', { name: 'Use this model' })
    await expect(use).toBeDisabled()
    await dialog.getByRole('combobox', { name: 'Model' }).click()
    await page.getByRole('option', { name: 'Codex · fixture-model-b' }).click()
    await use.click()
    await expect(dialog).toHaveCount(0)
    // The change the server recorded is the one the page reports; the run is still stopped: nothing was sent.
    const after = await viewOf(api, rid)
    const change = after.model_changes?.at(-1)
    expect(change).toMatchObject({ role: 'literature', from: { model: 'fixture-model' }, to: { model: 'fixture-model-b' } })
    expect(after.runs.find(r => r.kind === 'discovery')?.status).toBe('paused')
    await expect(page.locator('.toast').filter({ hasText: 'Literature model changed from fixture-model to fixture-model-b for this research.' })).toBeVisible()
    await expect(note.locator('.notice-model-change')).toContainText('You moved the literature role from fixture-model to fixture-model-b')
    // The finished planning step still names fixture-model; the new choice is named apart, as where the next calls go.
    await expect(literature).toHaveText(['Literature · Codex · fixture-model', 'Literature, set for the next calls · Codex · fixture-model-b'])
    await note.getByRole('button', { name: 'Retry this step' }).click()
    await expect.poll(async () => (await viewOf(api, rid)).runs.find(r => r.kind === 'discovery')?.status, { timeout: 60_000 }).toBe('completed')
    expect((await viewOf(api, rid)).scope.literature_model).toBe('fixture-model-b')
    await expect(page.locator('.chat-note.notice.is-error')).toHaveCount(0)
    // Both models ran in this run, each named once: planning on fixture-model, screening after the retry on fixture-model-b.
    await expect(literature).toHaveText(['Literature · Codex · fixture-model', 'Literature · Codex · fixture-model-b'])
  })

  test('S27 (R20, Sol r2): a model changed while full text was being read is named for the full-text phase; the run names both, the new one with the effort its calls were sent with (D25)', async () => {
    test.setTimeout(180_000)
    const rid = await create(api, `[read-down] ${MOLECULE}`)
    await page.goto(`${server.url()}/#/research/${rid}`)
    const note = page.locator('.chat-note.notice.is-error')
    await expect(note.getByRole('button', { name: 'Choose another model' })).toBeVisible({ timeout: 90_000 })
    type Steps = { steps?: Array<{ kind: string; status: string; models?: Array<{ connection: string; model: string | null; effort?: string | null }> }> }
    const discovery = async () => (await viewOf(api, rid)).runs.find(r => r.kind === 'discovery') as unknown as Steps & { status: string }
    // The run stopped at a full-text reading call; screening already ran on fixture-model.
    const stoppedAt = [...((await discovery()).steps ?? [])].reverse().find(s => s.kind.startsWith('model:') && s.status !== 'succeeded')
    expect(stoppedAt?.kind).toBe('model:fulltext_adjudication')
    await note.getByRole('button', { name: 'Choose another model' }).click()
    const dialog = page.getByRole('dialog', { name: 'Choose another model' })
    await expect(dialog.getByRole('combobox', { name: 'Role' })).toHaveText(/^Literature/)
    await dialog.getByRole('combobox', { name: 'Model' }).click()
    await page.getByRole('option', { name: 'Codex · fixture-model-b' }).click()
    await dialog.getByRole('combobox', { name: 'Reasoning effort' }).click()
    await page.getByRole('option', { name: 'High' }).click()
    await dialog.getByRole('button', { name: 'Use this model' }).click()
    await expect(dialog).toHaveCount(0)
    // Nothing was sent at the new effort yet (the full-text phase has no role entry, so no "set for the next calls" line).
    const literature = page.locator('.chat-run-models').first().locator('.chat-run-model').filter({ hasText: /^Literature/ })
    await expect(literature).toHaveText(['Literature · Codex · fixture-model'])
    await note.getByRole('button', { name: 'Retry this step' }).click()
    await expect.poll(async () => (await discovery()).status, { timeout: 90_000 }).toBe('completed')
    // The full-text reads that ran after the retry went to fixture-model-b; screening keeps fixture-model.
    const done = (await discovery()).steps ?? []
    const reads = done.filter(s => s.kind === 'model:fulltext_adjudication' && s.status === 'succeeded')
    expect(reads.length).toBeGreaterThan(0)
    // Each stored session keeps the effort it was sent with: high after the change, none before it (none was chosen).
    expect(reads.every(s => s.models?.at(-1)?.model === 'fixture-model-b' && s.models?.at(-1)?.effort === 'high')).toBe(true)
    expect(done.filter(s => s.kind === 'model:abstract_screening').every(s => s.models?.every(m => m.model === 'fixture-model' && m.effort === null))).toBe(true)
    await expect(literature).toHaveText(['Literature · Codex · fixture-model', 'Literature · Codex · fixture-model-b · High'])
  })
})
