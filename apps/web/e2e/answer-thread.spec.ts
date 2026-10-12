import { expect, request as apiRequest, test, type APIRequestContext, type Browser, type Page } from '@playwright/test'
import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'
import { PANEL_TITLES, panel, reportPanel, sourcePanel } from './panels'

// UI parity S10: the latest answer in the thread (mockup `answerBlock()`, R22-R29) and the empty research page (R32).
// The card's counts, the prose with its citation chips, the Methods box, the action pills and the Next steps rows read
// the answer's stored record; each answer state has its notice. The states come from the fixture's markers ([parity],
// [no-passages], [no-include], [invent-locator], [answer-hold]); the clarification and a running claim review cannot be
// produced by the backend or held by the fixture, so those two are drawn from a view patched in the browser.
//
// Every record is SYNTHETIC; a passing case shows how the page behaves, not the quality of a search or an answer.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

const PARITY = '[parity] How has the relationship between k-connectivity, network lifetime and energy consumption been modeled in SYNTHETIC wireless sensor networks?'

class ThreadServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-thread-'))
  constructor(readonly port: number) {}
  async start() {
    const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend'), DEIXIS_FIXTURE_FULLTEXT: 'on' }
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`http://127.0.0.1:${this.port}/api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`thread fixture server on ${this.port} did not start`)
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

type Evidence = { passage_id: string; source_version_id: string; source_key: string | null; kind: string }
type Claim = { id: string; section: string | null; evidence: Evidence[] }
type Answer = {
  id: string; run_id: string; status: string; report_version: number | null; applicability: string; source_text_changed: boolean
  claims: Claim[]; inputs_given: { depth?: { pdf: number; abstract: number; metadata: number } } | null
  validation: { reason?: string; issues?: { code: string; path: string }[] }; start_snapshot: { included: number } | null
  review: unknown; clarification: unknown
}
type Source = { source_version_id: string; work_id: string; version_role: string; selection: { state: string; version: number }; cited_in_latest_answer: boolean; access: { assets: { id: string }[] } }
type View = {
  research: { current_scope_revision: number }
  runs: Array<{ id: string; kind: string; status: string; target?: Record<string, unknown> | null }>
  counts: { included: number; cited: number }
  answers: Answer[]
  sources: Source[]
}
type Api = { context: APIRequestContext; token: string }
const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
const post = (api: Api, url: string, data: unknown, headers: Record<string, string> = {}) => api.context.post(url, { data, headers: { 'x-deixis-csrf': api.token, ...headers } })
const viewOf = async (api: Api, rid: string) => (await (await api.context.get(`/api/researches/${rid}`)).json()) as View
const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`), animations: 'disabled' })
const thread = (page: Page) => page.locator('.answer-thread')
const notice = (page: Page, text: string | RegExp) => thread(page).locator('.answer-notice', { hasText: text })
const settled = async (api: Api, rid: string, kinds: string[]) => expect.poll(async () => {
  const view = await viewOf(api, rid)
  return kinds.every(k => view.runs.some(r => r.kind === k)) && !view.runs.some(r => ACTIVE.has(r.status))
}, { timeout: 110_000, intervals: [500] }).toBe(true)
// The works an answer cites, each once over its versions (the view's "cited" count).
const citedWorks = (answer: Answer, view: View) => {
  const workOf = new Map(view.sources.map(s => [s.source_version_id, s.work_id]))
  return new Set(answer.claims.flatMap(c => c.evidence.map(e => workOf.get(e.source_version_id) ?? e.source_version_id))).size
}
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`
// A hash-only change does not load the page again, so every visit starts from a blank page.
const visit = async (page: Page, url: string) => { await page.goto('about:blank'); await page.goto(url) }
// The fixture server writes its SYNTHETIC PDFs and exits (`--write-seed-pdf`, `--write-replacement-pdf`).
const writePdf = (flag: '--write-seed-pdf' | '--write-replacement-pdf', file: string, dataDir: string) =>
  spawnSync(PYTHON, [SERVER, '--data-dir', dataDir, '--port', '0', flag, file], { cwd: REPO, env: { ...process.env, PYTHONPATH: path.join(REPO, 'backend') } }).status

async function newResearch(api: Api, question: string, scope = 'academic') {
  const created = await post(api, '/api/researches', { question, model_connection: 'codex', requested_model: 'fixture-model', effort: 'standard', source_scope: scope })
  expect(created.status()).toBe(201)
  return (await created.json()).research.id as string
}
async function discover(api: Api, rid: string) {
  expect((await post(api, `/api/researches/${rid}/runs`, { kind: 'discovery' }, { 'Idempotency-Key': `thread-discovery-${rid}` })).ok()).toBe(true)
}

test.describe.serial('S10: the answer in the thread', () => {
  test.setTimeout(240_000)
  const server = new ThreadServer(nextPort())
  let api: Api
  let rid = ''
  let page: Page
  const research = (id = rid) => `${server.url()}/#/research/${id}`

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(240_000)
    await server.start()
    const context = await apiRequest.newContext({ baseURL: server.url(), extraHTTPHeaders: { origin: server.url() } })
    api = { context, token: (await (await context.get('/api/session')).json()).csrf_token as string }
    rid = await newResearch(api, PARITY)
    await discover(api, rid)
    await settled(api, rid, ['discovery', 'answer'])
    page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  })
  test.afterAll(async () => { await page?.close(); await api?.context.dispose(); await server.stop() })

  test('the card, the prose and its citation chips read the answer’s stored record', async () => {
    const view = await viewOf(api, rid)
    const answer = view.answers[0]
    expect(answer.status).toBe('structurally_valid')
    await visit(page, research())
    // R22: "Report · Vn · N claims · N sources", the sources counted as works, as the view's Cited count.
    const cited = citedWorks(answer, view)
    expect(cited).toBe(view.counts.cited)
    const card = page.locator('#research-answer')
    await expect(card).toHaveAccessibleName(/^Open report: /)
    await expect(card.locator('.report-artifact-meta')).toHaveText(`Report · V${answer.report_version} · ${plural(answer.claims.length, 'claim', 'claims')} · ${plural(cited, 'source', 'sources')}`)
    // R24/R25: the first sections as paragraphs, one chip per claim that cites, naming its first source and "+N" for
    // the other sources it cites.
    const sections: Claim[][] = []
    for (const claim of answer.claims) {
      const last = sections[sections.length - 1]
      if (last && last[0].section === claim.section) last.push(claim); else sections.push([claim])
    }
    const shown = sections.slice(0, 2).flat()
    const prose = thread(page).locator('.answer-prose')
    await expect(prose.locator(':scope > p')).toHaveCount(Math.min(2, sections.length))
    await expect(prose.locator('.claim')).toHaveCount(shown.length)
    const chips = prose.locator('.cite-chip')
    const labels = shown.filter(c => c.evidence.length).map(c => {
      const others = new Set(c.evidence.map(e => e.source_version_id)).size - 1
      return `${c.evidence[0].source_key}${others > 0 ? ` +${others}` : ''}`
    })
    await expect(chips).toHaveText(labels)
    // The chip opens the first cited passage at its located anchor, in Source details.
    await chips.first().click()
    const source = sourcePanel(page)
    await expect(source).toBeVisible()
    await expect(source.locator('mark.citation-highlight').first()).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.locator('[data-split-panel]')).toHaveCount(0)
    // The card opens the report panel; while it is open the card reads as on (mockup `.art.on`).
    await card.click()
    await expect(reportPanel(page)).toBeVisible()
    await expect(card).toHaveClass(/is-on/)
    await page.keyboard.press('Escape')
    await shot(page, 's10-answer-card-prose')
  })

  test('the Methods box says how the answer was reached from the stored method record', async () => {
    const view = await viewOf(api, rid)
    const answer = view.answers[0]
    const method = await (await api.context.get(`/api/researches/${rid}/answers/${answer.id}/method`)).json() as {
      search: { queries: unknown[]; chaining: { ran: boolean } }; selection: { works_found: number | null; abstract_read: number; full_text_read: number; included: number | null }
    }
    await visit(page, research())
    const methods = thread(page).locator('.methods')
    await expect(methods.locator('h4')).toHaveText('Methods')
    const text = methods.locator(':scope > p')
    await expect(text).toContainText(`${method.search.queries.length} searches were sent to OpenAlex${method.search.chaining.ran ? ', and citation chaining ran.' : '; citation chaining did not run.'}`)
    await expect(text).toContainText(`The model read the abstracts of ${method.selection.abstract_read} of ${method.selection.works_found} works against the criterion (see what was not read).`)
    await expect(text).toContainText(`${method.selection.full_text_read} works were read in their full text (selected pages); included when the answer started: ${method.selection.included}.`)
    const abstractOnly = answer.inputs_given!.depth!.abstract
    expect(abstractOnly).toBeGreaterThan(0)
    await expect(text).toContainText(`${abstractOnly} works were given to the answer from their abstracts only; where cited they are labelled “From abstract”.`)
    await expect(text.locator('.ok')).toHaveText('Every citation resolves to a stored passage given to this step.')
    // No reviewer model is set in the fixture, so no claim review is recorded, and the box says so.
    expect(answer.review).toBeNull()
    await expect(text).toContainText('Claim support was not reviewed by a reviewer model.')
    // "Full method" holds every count and the answer's boundary (§2.2).
    await methods.locator('summary', { hasText: 'Full method' }).click()
    await expect(methods.getByRole('group', { name: 'Flow at the start of this answer' })).toContainText('When the answer started:')
    // "see what was not read" opens the funnel's place (the Sources panel until S14).
    await text.getByRole('button', { name: 'see what was not read' }).click()
    await expect(panel(page, PANEL_TITLES.sources)).toBeVisible()
    await page.keyboard.press('Escape')
  })

  test('the action pills and the Next steps rows open their places, with counts from the record', async () => {
    const view = await viewOf(api, rid)
    const answer = view.answers[0]
    const cited = citedWorks(answer, view)
    await visit(page, research())
    const acts = thread(page).locator('.answer-acts')
    await expect(acts.getByRole('button')).toHaveText([`View ${cited} cited sources`, 'Evidence table', 'Search funnel', '', ''])
    // View N cited sources: the Sources panel on "Cited in answer", one row per cited work.
    await acts.getByRole('button', { name: `View ${cited} cited sources` }).click()
    const sources = panel(page, PANEL_TITLES.sources)
    await expect(sources.getByRole('button', { name: /^Cited in answer/ })).toHaveAttribute('aria-pressed', 'true')
    await expect(sources.getByRole('button', { name: /^Cited in answer/ })).toContainText(String(cited))
    // Each cited work's row, with the other versions that follow it.
    const citedWorkIds = new Set(view.sources.filter(s => s.cited_in_latest_answer).map(s => s.work_id))
    await expect(sources.locator('.source-row')).toHaveCount(view.sources.filter(s => citedWorkIds.has(s.work_id)).length)
    await page.keyboard.press('Escape')
    await acts.getByRole('button', { name: 'Evidence table', exact: true }).click()
    await expect(panel(page, PANEL_TITLES.table)).toBeVisible()
    await page.keyboard.press('Escape')
    await acts.getByRole('button', { name: 'Search funnel' }).click()
    await expect(panel(page, PANEL_TITLES.sources)).toBeVisible()
    await page.keyboard.press('Escape')
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
    await acts.getByRole('button', { name: 'Copy answer' }).click()
    await expect(page.getByRole('status').filter({ hasText: 'Report copied to clipboard.' })).toBeVisible()
    await acts.getByRole('button', { name: 'Download' }).click()
    await expect(page.getByRole('menuitem', { name: /^MD/ }).first()).toBeVisible()
    await page.keyboard.press('Escape')
    // Next steps (R28): review, a table of the included sources, full text for the works read from abstracts only.
    const next = thread(page).locator('.follow')
    await expect(next.locator('h5')).toHaveText('Next steps')
    const abstractOnly = answer.inputs_given!.depth!.abstract
    await expect(next.getByRole('button')).toHaveText([
      'Review the claims with another model',
      `Build an evidence table of the ${view.counts.included} included sources`,
      `Get full text for the ${abstractOnly} works the answer read from their abstracts only`,
    ])
    await next.getByRole('button', { name: /^Get full text for/ }).click()
    await expect(panel(page, PANEL_TITLES.pdfs)).toBeVisible()
    await page.keyboard.press('Escape')
    await next.getByRole('button', { name: 'Review the claims with another model' }).click()
    await expect(reportPanel(page).locator('.review-pane')).toBeVisible()
    await page.keyboard.press('Escape')
    await shot(page, 's10-answer-next-steps')
  })

  test('a replaced PDF and a changed selection mark the answer, with one Generate a new answer', async () => {
    const before = await viewOf(api, rid)
    const answer = before.answers[0]
    // A PDF the answer read, replaced by another file: the answer keeps its quotes and says the text changed.
    const read = answer.claims.flatMap(c => c.evidence).find(e => e.kind === 'pdf_page')!
    const owner = before.sources.find(s => s.source_version_id === read.source_version_id)!
    const pdf = path.join(server.dataDir, 'replacement.pdf')
    expect(writePdf('--write-replacement-pdf', pdf, server.dataDir)).toBe(0)
    const replaced = await api.context.put(`/api/researches/${rid}/sources/${owner.source_version_id}/assets/${owner.access.assets[0].id}`, {
      multipart: { file: { name: 'SYNTHETIC replacement.pdf', mimeType: 'application/pdf', buffer: readFileSync(pdf) } }, headers: { 'x-deixis-csrf': api.token } })
    expect(replaced.ok(), await replaced.text()).toBe(true)
    // An included work excluded after the answer: the answer still uses the old selection.
    const included = before.sources.find(s => s.version_role === 'record' && s.selection.state === 'included' && s.source_version_id !== owner.source_version_id)!
    const patched = await api.context.patch(`/api/researches/${rid}/selections/${included.source_version_id}`,
      { data: { state: 'excluded', expected_version: included.selection.version, reason: 'SYNTHETIC selection change' }, headers: { 'x-deixis-csrf': api.token } })
    expect(patched.ok()).toBe(true)
    const after = (await viewOf(api, rid)).answers[0]
    expect([after.source_text_changed, after.applicability]).toEqual([true, 'stale_selection'])
    await visit(page, research())
    await expect(notice(page, 'A PDF this answer read was replaced')).toContainText('generate a new answer to read the current text')
    await expect(notice(page, 'This answer is out of date.')).toContainText('Your source selection changed after it was written; the answer still uses the old selection.')
    // One "Generate a new answer" on the page: in the first notice; the button under the thread leaves it there.
    await expect(page.getByRole('button', { name: 'Generate a new answer' })).toHaveCount(1)
    await expect(notice(page, 'A PDF this answer read was replaced').getByRole('button', { name: 'Generate a new answer' })).toBeEnabled()
    await notice(page, 'This answer is out of date.').getByRole('button', { name: 'Review the selection' }).click()
    await expect(panel(page, PANEL_TITLES.sources).getByRole('button', { name: /^Included/ })).toHaveAttribute('aria-pressed', 'true')
    await page.keyboard.press('Escape')
    await shot(page, 's10-answer-out-of-date')
  })

  test('a clarification and a running claim review (patched view: the backend stores neither here)', async () => {
    const view = await viewOf(api, rid)
    // SYNTHETIC: no backend path stores a clarification (plan S0 backlog); the page's notice is drawn from a patched view.
    await page.route(`**/api/researches/${rid}`, async route => {
      if (route.request().method() !== 'GET') return route.fallback()
      const response = await route.fetch()
      const body = await response.json() as View
      body.answers[0] = { ...body.answers[0], status: 'clarification', claims: [], clarification: {
        question: 'SYNTHETIC: lifetime until the first node fails, or until the sink is cut off?', ambiguity: 'SYNTHETIC',
        why_it_matters: 'SYNTHETIC: the included works use both definitions.', options: ['SYNTHETIC first node', 'SYNTHETIC sink cut off'] } }
      await route.fulfill({ response, json: body })
    })
    await visit(page, research())
    const clarification = notice(page, 'Clarification needed')
    await expect(clarification.locator('.answer-notice-question')).toHaveText('SYNTHETIC: lifetime until the first node fails, or until the sink is cut off?')
    await expect(clarification.locator('li')).toHaveText(['SYNTHETIC first node', 'SYNTHETIC sink cut off'])
    await expect(clarification).toContainText('Revise the question to continue. No answer was written.')
    await expect(thread(page).locator('#research-answer, .answer-prose, .methods, .follow')).toHaveCount(0)
    await clarification.getByRole('button', { name: 'Revise question' }).click()
    await expect(page.locator('.chat-question.is-editing')).toBeVisible()
    await page.unroute(`**/api/researches/${rid}`)
    // SYNTHETIC: a claim review run of the answer still running (the fixture's review ends within a poll).
    const answer = view.answers[0]
    await page.route(`**/api/researches/${rid}`, async route => {
      if (route.request().method() !== 'GET') return route.fallback()
      const response = await route.fetch()
      const body = await response.json() as View
      body.answers[0] = { ...body.answers[0], review: null }
      body.runs = [{ ...body.runs[0], id: 'run_synthetic_review', kind: 'answer_review', status: 'running', target: { answer_id: answer.id } }, ...body.runs]
      await route.fulfill({ response, json: body })
    })
    await visit(page, research())
    await expect(thread(page).locator('.methods > p')).toContainText('The reviewer model is reviewing claim support.')
    await page.unroute(`**/api/researches/${rid}`)
  })

  test('no included work, no passages and an unverified draft each have their notice', async () => {
    // [no-passages]: the works have no abstract and no open PDF, so the automatic answer has nothing to give the model.
    const bare = await newResearch(api, '[no-passages] How is molecule release scheduled with bisection in relay networks?')
    await discover(api, bare)
    await settled(api, bare, ['discovery', 'answer'])
    const bareAnswer = (await viewOf(api, bare)).answers[0]
    expect([bareAnswer.status, bareAnswer.validation.reason === 'no_includable_source']).toEqual(['no_evidence', false])
    await visit(page, research(bare))
    const noPassages = notice(page, 'No text passages were available for the included sources')
    await expect(noPassages.locator('.src-m')).toHaveText(`Included when the answer started: ${bareAnswer.start_snapshot!.included}`)
    await noPassages.getByRole('button', { name: 'Attach PDFs' }).click()
    await expect(panel(page, PANEL_TITLES.pdfs)).toBeVisible()
    await page.keyboard.press('Escape')
    await shot(page, 's10-answer-no-passages')

    // [no-include]: the answer run waits behind another research's title run while its one included file is excluded.
    const seed = path.join(server.dataDir, 'seed.pdf')
    expect(writePdf('--write-seed-pdf', seed, server.dataDir)).toBe(0)
    const upload = async (id: string, name: string) => {
      const response = await api.context.post(`/api/researches/${id}/uploads`, { multipart: { file: { name, mimeType: 'application/pdf', buffer: readFileSync(seed) } }, headers: { 'x-deixis-csrf': api.token } })
      expect(response.ok(), await response.text()).toBe(true)
      return (await response.json()).uploaded_source_version_id as string
    }
    const hold = await newResearch(api, '[no-include] SYNTHETIC holding research', 'attached')
    await upload(hold, 'SYNTHETIC hold.pdf')
    const none = await newResearch(api, '[no-include] What do SYNTHETIC attached notes say about release timing?', 'attached')
    const file = await upload(none, 'SYNTHETIC notes.pdf')
    expect((await post(api, `/api/researches/${hold}/runs`, { kind: 'research_title' }, { 'Idempotency-Key': `thread-title-${hold}` })).ok()).toBe(true)
    await new Promise(resolve => setTimeout(resolve, 200))
    expect((await post(api, `/api/researches/${none}/runs`, { kind: 'answer' }, { 'Idempotency-Key': `thread-answer-${none}` })).ok()).toBe(true)
    const version = (await viewOf(api, none)).sources.find(s => s.source_version_id === file)!.selection.version
    expect((await api.context.patch(`/api/researches/${none}/selections/${file}`, { data: { state: 'excluded', expected_version: version }, headers: { 'x-deixis-csrf': api.token } })).ok()).toBe(true)
    await settled(api, none, ['answer'])
    const noneAnswer = (await viewOf(api, none)).answers[0]
    expect([noneAnswer.status, noneAnswer.validation.reason]).toEqual(['no_evidence', 'no_includable_source'])
    await visit(page, research(none))
    const noInclude = notice(page, 'No work was included at full text when this answer started')
    await expect(noInclude.locator('.src-m')).toHaveText(/^When the answer started: included 0 · in your queue \d+ · waiting for a PDF \d+ · full text not read \d+ · criterion not met \d+$|^The flow at the start of this answer was not recorded\.$/)
    await noInclude.getByRole('button', { name: 'Get more full text' }).click()
    await expect(panel(page, PANEL_TITLES.pdfs)).toBeVisible()
    await page.keyboard.press('Escape')

    // [invent-locator]: every draft asserts a page, so the answer is an unverified draft, greyed and without citations.
    const invent = await newResearch(api, 'SYNTHETIC [invent-locator] How is molecule release scheduling optimized?')
    await discover(api, invent)
    await settled(api, invent, ['discovery', 'answer'])
    const draft = (await viewOf(api, invent)).answers[0]
    expect(draft.status).toBe('unverified_draft')
    await visit(page, research(invent))
    const failed = notice(page, 'The model output failed validation after one repair attempt')
    await expect(failed).toHaveAttribute('role', 'alert')
    await expect(failed.locator('.answer-notice-issues li')).toHaveText(draft.validation.issues!.map(i => `${i.code} at ${i.path}`))
    await expect(failed.getByRole('button', { name: 'Generate a new answer' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Generate a new answer' })).toHaveCount(1)
    await expect(thread(page).locator('.answer-prose .claim.is-unverified').first()).toBeVisible()
    await expect(thread(page).locator('.cite-chip')).toHaveCount(0)
    await expect(thread(page).locator('.foot-note')).toHaveText('Unverified draft: shown greyed, without citations, so you can see what failed. Do not quote it.')
    await shot(page, 's10-answer-unverified')
  })

  test('a new version is written behind a live card; then V2 is the latest and V1 is kept', async () => {
    // [answer-hold]: the automatic V1 is let through; the next answer waits for the release file.
    const release = path.join(server.dataDir, 'answer-release')
    writeFileSync(release, 'SYNTHETIC release\n')
    const held = await newResearch(api, 'SYNTHETIC [answer-hold]: How is molecule release scheduling optimized?')
    await discover(api, held)
    await settled(api, held, ['discovery', 'answer'])
    const first = (await viewOf(api, held)).answers[0]
    expect([first.status, first.report_version]).toEqual(['structurally_valid', 1])
    rmSync(release, { force: true })
    await visit(page, research(held))
    await expect(page.locator('#research-answer .report-artifact-meta')).toContainText('Report · V1')
    await page.getByRole('button', { name: 'Generate a new answer' }).click()
    const live = thread(page).locator('.report-artifact.is-live')
    await expect(live).toContainText('Writing answer V2…')
    await expect(live).toContainText('V1 stays available')
    await expect(page.locator('#research-answer')).toHaveCount(0)
    await shot(page, 's10-answer-writing')
    writeFileSync(release, 'SYNTHETIC release\n')
    await settled(api, held, ['answer'])
    await expect(page.locator('#research-answer .report-artifact-meta')).toContainText('Report · V2', { timeout: 30_000 })
    const latest = notice(page, 'Answer V2 is the latest.')
    await expect(latest).toContainText('V1 is kept.')
    await latest.getByRole('button', { name: 'Open V1' }).click()
    await expect(reportPanel(page).locator('.report-document-head')).toContainText('Report · V1')
    await page.keyboard.press('Escape')
  })

  test('at 390 px the answer fits without a horizontal scroll', async ({ browser }) => {
    for (const scheme of ['light', 'dark'] as const) {
      const narrow = await (browser as Browser).newPage({ viewport: { width: 390, height: 844 }, colorScheme: scheme })
      try {
        await narrow.goto(research())
        await expect(narrow.locator('.answer-thread .methods')).toBeVisible()
        expect(await narrow.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
        await narrow.locator('.answer-thread').scrollIntoViewIfNeeded()
        await shot(narrow, `s10-answer-390-${scheme}`)
      } finally { await narrow.close() }
    }
  })
})

test.describe('S10: the research page before any research (R32)', () => {
  const server = new ThreadServer(nextPort())
  test.beforeAll(async () => { test.setTimeout(60_000); await server.start() })
  test.afterAll(async () => { await server.stop() })

  test('Current research shows “No research yet” and leads to New research', async ({ page }) => {
    await page.goto(server.url())
    await page.getByRole('button', { name: 'Current research' }).click()
    const empty = page.locator('.research-empty')
    await expect(empty.getByRole('heading', { level: 1 })).toHaveText('No research yet')
    await expect(empty).toContainText('Your questions and their answers will appear here. Set up a model first, then ask a question.')
    await shot(page, 's10-no-research')
    await empty.getByRole('button', { name: 'New research' }).click()
    await expect(page.locator('#research-question')).toBeVisible()
  })
})
