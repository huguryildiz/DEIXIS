import { expect, request as apiRequest, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'
import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import type { CandidateCard, CandidateComputed, CandidateEdit, CandidateEvidence, CandidateHit, CandidateListItem, CandidateMatrix, CandidatePlan, CandidateStatus, ResearchView, Run, TableView } from '../src/api'
import { reasonLabels, relationLabels, alignmentLabels, statusLabels, assessmentLabels, depthLabels, kindLabels, outcomeLabels, refusalLabels, runReasonLabels, warningLabels, stepStateLabels, label, reasonText } from '../src/candidate/labels'
import { setUiLanguage } from '../src/i18n'
import { stepLabel } from '../src/labels'
import { nextPort } from './ports'

// Port from nextPort().
// This suite exercises synthetic application behavior only; it makes no real model/provider request.
const PORT = nextPort()
const REPO = path.resolve(process.cwd(), '..', '..')
const SERVER_URL = `http://127.0.0.1:${PORT}`
const PYTHON = process.env.DEIXIS_TEST_PYTHON ?? path.join(REPO, '.venv/bin/python')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
const CLAIM = 'SYNTHETIC novel buffering claim with a gap under bounded arrivals.'
const TITLE_A = 'SYNTHETIC W-A novel buffering and gap conditions'
const QUOTE = 'SYNTHETIC buffering reduces delay under bounded arrivals.'
const ROW_TEXT = '  SYNTHETIC novel gap aspect to investigate.\n'
mkdirSync(OUT, { recursive: true })

class CandidateServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-k4-'))
  async start() {
    this.proc = spawn(PYTHON, [path.join(REPO, 'tests/acceptance/fixture_server.py'), '--data-dir', this.dataDir, '--port', String(PORT)],
      { cwd: REPO, env: { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: `${REPO}/backend:${REPO}` }, stdio: 'inherit' })
    await expect.poll(async () => { try { return (await fetch(`${SERVER_URL}/api/health`)).ok } catch { return false } }).toBe(true)
  }
  async stop() {
    const proc = this.proc
    if (!proc || proc.exitCode !== null) return
    const ended = new Promise(resolve => proc.once('exit', resolve))
    proc.kill('SIGTERM'); await ended
  }
  seed(code: string, args: string[]) {
    const result = spawnSync(PYTHON, ['-c', code, path.join(this.dataDir, 'library.sqlite'), ...args],
      { cwd: REPO, env: { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: `${REPO}/backend:${REPO}` }, encoding: 'utf8' })
    expect(result.status, result.stderr).toBe(0)
  }
}
type Fixture = { rid: string; api: APIRequestContext; headers: Record<string, string>; base: string }
const pane = (page: Page) => page.locator('.candidates-view')
const decision = (page: Page) => pane(page).locator('.candidate-status')
const planPane = (page: Page) => pane(page).locator('.candidate-plan')
const editSheet = (page: Page) => page.getByRole('dialog', { name: 'Write the candidate card' })

async function fixture(page: Page, api: APIRequestContext, marker = '[candidate]'): Promise<Fixture> {
  const csrf = (await (await api.get('/api/session')).json()).csrf_token as string
  await page.goto(SERVER_URL)
  await page.getByLabel('Research question').fill(`SYNTHETIC molecule release scheduling ${marker}`)
  await page.getByRole('button', { name: 'Start research' }).click()
  await page.waitForURL(/#\/research\//)
  const rid = page.url().split('/research/')[1].split('/')[0]
  const f = { rid, api, headers: { 'x-deixis-csrf': csrf }, base: `/api/researches/${rid}/candidates` }
  await expect.poll(async () => (await research(f)).runs[0]?.status).toBe('completed')
  return f
}
const research = async (f: Fixture): Promise<ResearchView> => (await f.api.get(`/api/researches/${f.rid}`)).json()
const card = async (f: Fixture, id: string): Promise<CandidateCard> => (await f.api.get(`${f.base}/${id}`)).json()
async function waitRun(f: Fixture, id: string, status = 'completed') {
  await expect.poll(async () => (await research(f)).runs.find(r => r.id === id)?.status).toBe(status)
}
async function keyboardActivate(control: Locator) { await control.focus(); await expect(control).toBeFocused(); await control.press('Enter') }
async function installResponseBarrier(page: Page, token: string) {
  await page.evaluate(token => {
    const originalFetch = window.fetch.bind(window)
    window.fetch = async (...args) => {
      const response = await originalFetch(...args)
      if (response.headers.get('x-k4-response-barrier') === token) {
        const originalJson = response.json.bind(response)
        response.json = async () => {
          const body = await originalJson()
          // Resolve the application's JSON read, then allow its promise handlers and rendering to finish.
          requestAnimationFrame(() => requestAnimationFrame(() => { document.documentElement.dataset.k4ProcessedResponse = token }))
          return body
        }
      }
      return response
    }
  }, token)
}
async function candidatesTab(page: Page) {
  const tab = page.getByRole('tab', { name: /^Candidates/ })
  // Walk Tab from the tab strip, rather than relying on pointer input.
  await page.getByRole('tab', { name: 'Answer', exact: true }).focus()
  for (let i = 0; i < 15 && !(await tab.evaluate(el => el === document.activeElement)); i++) await page.keyboard.press('Tab')
  await expect(tab).toBeFocused()
  await tab.press('Enter')
  await expect(pane(page)).toBeVisible()
}
async function add(page: Page, f: Fixture, text = CLAIM) {
  await candidatesTab(page)
  await keyboardActivate(pane(page).getByRole('button', { name: 'Add candidate' }))
  await pane(page).getByLabel('Your sentence').fill(`  ${text}  `)
  await pane(page).getByRole('button', { name: 'Save', exact: true }).click()
  await expect(pane(page).getByRole('heading', { name: 'Candidate card' })).toBeFocused()
  await expect(pane(page)).toContainText('This is your sentence, not a finding from the literature.')
  const rows: CandidateListItem[] = await (await f.api.get(f.base)).json()
  return rows.find(r => r.claim_statement === null)!.id
}
function editBody(c: CandidateCard, expected = c.current_version): CandidateEdit {
  const v = c.versions.find(v => v.id === c.current_version_id)!
  return { claim_statement: v.claim_statement, conditions: v.conditions, elements: v.elements.map(e => ({ text: e.text, kind: e.kind })), nearest_simple_explanation: v.nearest_simple_explanation,
    critical_assumption: v.critical_assumption, validation_plan: v.validation_plan, expected_version: expected }
}
async function chromeWords(root: Locator) {
  const text = await root.evaluate(el => {
    const copy = el.cloneNode(true) as HTMLElement
    // Values are user data; labels and fixed select options remain DEIXIS chrome.
    // User-supplied option labels use the same stored-text marker as other stored blocks.
    const stored = 'textarea, input, [data-stored-text]'
    if (copy.matches(stored)) return ''
    copy.querySelectorAll(stored).forEach(e => e.remove())
    return copy.textContent ?? ''
  })
  expect(text).not.toMatch(/\b(novel|novelty|original|originality|unique|gap|foundational|verified|proof|proven|refuted|disproved|score|importance)\b|no prior work|does not exist/i)
}
async function capture(page: Page, name: string, root: Locator, prepare?: () => Promise<void>, close?: () => Promise<void>) {
  async function setTheme(theme: 'light' | 'dark') {
    const dark = await page.locator('html').evaluate(el => el.classList.contains('dark'))
    if (dark === (theme === 'dark')) return
    // Let a just-closed sheet restore focus before temporarily using the header.
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => resolve())))
    const focused = await page.evaluateHandle(() => document.activeElement)
    try {
      await page.evaluate(() => window.scrollTo({ top: 0, left: 0, behavior: 'instant' }))
      const button = page.getByRole('button', { name: dark ? 'Use light theme' : 'Use dark theme' })
      await button.scrollIntoViewIfNeeded()
      await button.click()
      // Theme navigation must not replace the opener focus being asserted by the caller.
      await focused.evaluate(el => { if (el instanceof HTMLElement && el.isConnected) el.focus({ preventScroll: true }) })
    } finally { await focused.dispose() }
  }
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 })
    for (const theme of ['light', 'dark'] as const) {
      await setTheme(theme)
      if (prepare) await prepare()
      await root.scrollIntoViewIfNeeded()
      await chromeWords(root)
      if (width === 390 && await pane(page).isVisible()) await expect.poll(() => pane(page).evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
      await page.screenshot({ path: path.join(OUT, `k4-${name}-${width}-${theme}.png`), animations: 'disabled' })
      if (close) { await close(); await expect(root).toBeHidden() }
    }
  }
  await page.setViewportSize({ width: 1440, height: 1000 })
  await setTheme('light')
  if (!close) await root.scrollIntoViewIfNeeded()
}
async function pauseAndReject(page: Page, f: Fixture, id: string, kind: 'claim_decomposition' | 'kill_search') {
  const line = pane(page).locator('.candidate-run').filter({ hasText: kind === 'claim_decomposition' ? 'Claim breakdown' : 'Prior-art search for a claim' }).last()
  await line.getByRole('button', { name: 'Pause', exact: true }).click()
  const run = (await research(f)).runs.find(r => r.kind === kind && r.target?.candidate_id === id)!
  await waitRun(f, run.id, 'paused')
  await expect(line.getByRole('button', { name: 'Resume' })).toBeVisible()
  await expect(line.getByRole('button', { name: 'Cancel', exact: true })).toBeVisible()
  await expect(pane(page)).toContainText('A run of this candidate is paused: resume or cancel it first')
  const start = pane(page).getByRole('button', { name: kind === 'claim_decomposition' ? 'Break the claim into testable parts' : 'Plan the search' })
  await expect(start).toBeDisabled()
  for (const action of ['decompose', 'kill-search']) {
    const response = await f.api.post(`${f.base}/${id}/${action}`, { headers: { ...f.headers, 'Idempotency-Key': crypto.randomUUID() }, ...(action === 'kill-search' ? { data: { preview_fingerprint: 'a'.repeat(64) } } : {}) })
    expect(response.status()).toBe(409)
    expect((await response.json()).detail).toContain('Resume or cancel paused candidate run')
  }
  await line.getByRole('button', { name: 'Resume' }).click()
  await waitRun(f, run.id)
}

function mockedCandidates(rid: string) {
  const long = 'SYNTHETIC_' + 'x'.repeat(1400), date = '2026-10-02T12:00:00Z'
  const counts = { found: 18, kept: 8, rank_cut: 10, duplicates: 2 }
  const computed: CandidateComputed = { status: 'undecided', reason: 'uncertain_cell', reasons: Object.keys(reasonLabels), warnings: ['merge_missing', 'unmatched_shape:SYNTHETIC'], facts: {
    ...counts, assessed: 3, unread: 15, queries_total: 3, queries_succeeded: 1, queries_failed: 1, queries_unknown: 1,
    reading_depths: { abstract: 3, stored_passages: 3, metadata_only: 2 },
  } }
  const versions: CandidateCard['versions'] = [1, 2, 3].map(n => ({ id: `v${n}`, candidate_id: 'mock_card', version: n,
    claim_statement: CLAIM, conditions: n === 3 ? [] : ['SYNTHETIC bounded arrivals'], nearest_simple_explanation: null,
    critical_assumption: 'SYNTHETIC the input is measurable.', validation_plan: 'SYNTHETIC compare the delays.',
    origin: n === 3 ? 'human_edit' : 'model_decomposition', step_input_id: n === 3 ? null : `si${n}`, created_at: date,
    elements: ['mechanism', 'condition', 'outcome', 'parameter', 'mechanism', 'condition'].map((kind, i) => ({ id: `v${n}e${i}`, candidate_version_id: `v${n}`, position: i + 1, text: `SYNTHETIC element ${i + 1}`, kind: kind as CandidateCard['versions'][number]['elements'][number]['kind'] })),
  }))
  const searches: CandidateCard['searches'] = [
    { id: 'old_search', candidate_version_id: 'v2', run_id: 'old_run', outcome: 'completed', created_at: '2026-10-01T12:00:00Z', version: 2, counts },
    { id: 'current_search', candidate_version_id: 'v3', run_id: 'running_run', outcome: 'running', created_at: date, version: 3, counts },
  ]
  const owners: CandidateCard['owner_decisions'] = Array.from({ length: 10 }, (_, i) => ({ id: `owner${i}`, candidate_version_id: 'v3', status: 'closed', reason: `SYNTHETIC decision ${i} ${long}`, created_at: `2026-10-02T12:${String(i).padStart(2, '0')}:00Z` }))
  const card: CandidateCard = { id: 'mock_card', research_id: rid, origin: 'report_gap', origin_report_id: 'mock_report', origin_gap_row_id: 'mock_row', gap_kind: 'corpus_absence', origin_changed: true,
    current_version: 3, trashed_at: null, origin_text: ROW_TEXT, origin_basis: { basis_cell_ids: ['missing_cell'], basis_passage_ids: ['missing_passage'], basis_claim_keys: ['missing_claim'] },
    origin_basis_view: { basis_cell_ids: [{ id: 'missing_cell', missing: true }, { id: 'c1', text: 'SYNTHETIC novel cell' }], basis_passage_ids: [{ id: 'missing_passage', missing: true }, { id: 'p1', text: 'SYNTHETIC gap passage', source_version_id: 's1' }], basis_claim_keys: [{ id: 'missing_claim', missing: true }, { id: 'cl1', text: 'SYNTHETIC claim' }] },
    origin_provenance: { origin: 'model', section_id: 'VI', step_input_id: 'si1' }, origin_fingerprint: 'a'.repeat(64), created_at: date,
    versions, current_version_id: 'v3', owner_decisions: owners, searches, status: { computed, previous: { ...computed, status: 'narrowed', reason: 'partial_overlap' }, owner: owners[9] },
    active_run: { id: 'running_run', kind: 'kill_search', status: 'running', pause_reason: null, error_code: null },
    runs: [{ id: 'running_run', kind: 'kill_search', status: 'running', pause_reason: null, error_code: null },
      { id: 'paused_run', kind: 'claim_decomposition', status: 'paused', pause_reason: 'user_requested', error_code: null },
      { id: 'failed_run', kind: 'kill_search', status: 'failed', pause_reason: 'query_terms_invalid', error_code: 'query_terms_invalid' },
      { id: 'done_run', kind: 'claim_decomposition', status: 'completed', pause_reason: null, error_code: null },
      { id: 'cancelled_run', kind: 'kill_search', status: 'cancelled', pause_reason: null, error_code: null }],
    decompose_budget: { max_model_calls: 6, max_provider_requests: 0 },
  }
  const plan: CandidatePlan = { candidate_id: card.id, candidate_version_id: 'v3', version: 3, scope_revision: 1, providers: ['openalex'], model: { kill_search_query: ['codex', 'fixture-model', null], claim_assessment: ['codex', 'fixture-model', null] },
    budget: { max_model_calls: 54, max_provider_requests: 12, steps: { kill_search_query: 6, claim_assessment: 48, assessment_works: 8 } },
    transport: { providers: [{ provider: 'openalex', requests_per_search: 2, rate_limit_retries: 1, transient_attempts: 1, per_query: 2 }], max_provider_requests: 12 },
    limits: { queries: 6, records: 20, keep: 8, max_message_chars: 100000, basis_items: 24, basis_text_chars: 2000, abstract_chars: 16000, page_passages: 4, page_text_chars: 12000 },
    skill_package_hash: 'sha256:8e1e4a8453a286ac9da8628dd095dd7796f3a49ae374d7930cb3ef06c546ee76', plan_version: 1, preview_fingerprint: 'b'.repeat(64),
  }
  const states: CandidateHit['assessment_state'][] = ['assessed', 'assessed', 'insufficient_access', 'not_assessed_budget', 'not_assessed_budget', 'not_assessed_budget', 'pending', 'assessed']
  const depths: CandidateHit['reading_depth'][] = ['abstract', 'stored_passages', 'metadata_only', 'abstract', 'stored_passages', 'metadata_only', 'abstract', 'stored_passages']
  const hits: CandidateHit[] = states.map((assessment_state, i) => ({ source_version_id: `work${i}`, rank: i + 1, reading_depth: depths[i], assessment_state, work_relevance: assessment_state === 'assessed' ? i === 1 ? 'unrelated' : i === 7 ? 'uncertain' : 'related' : null,
    note: `SYNTHETIC model note ${i} ${long}`, states_whole_claim: assessment_state === 'assessed' ? false : null,
    source: { title: i === 0 ? TITLE_A : `SYNTHETIC W-${i} ${long}`, year: 2020 + i, venue: 'SYNTHETIC venue', doi: '10.0000/synthetic', version_label: 'SYNTHETIC uploaded copy' } }))
  const cells: CandidateMatrix['cells'] = {}
  for (const hit of hits.filter(h => h.assessment_state === 'assessed')) {
    cells[hit.source_version_id] = {}
    const relations = Object.keys(relationLabels) as (keyof typeof relationLabels)[]
    versions[2].elements.forEach((element, i) => { cells[hit.source_version_id][element.id] = { id: `${hit.source_version_id}${i}`, kill_search_id: 'current_search', source_version_id: hit.source_version_id, element_id: element.id,
      relation: (relations[i % relations.length]) as CandidateMatrix['cells'][string][string]['relation'], condition_alignment: i === 0 || i === 1 ? 'aligned' : i === 2 ? 'different_conditions' : i === 5 ? 'unclear' : null, note: `SYNTHETIC cell ${i} ${long}` } })
  }
  const outcomes = ['assessed', 'assessed', 'insufficient_access', 'invalid_output', 'message_too_large', 'not_reached_budget', 'pending', 'assessed']
  const matrix: CandidateMatrix = { search: { ...counts, id: 'current_search', candidate_version_id: 'v3', run_id: 'running_run', outcome: 'running', hits_recorded: true, created_at: date,
    query_block: { setting: [{ kind: 'setting', term: long, why: 'SYNTHETIC retained term' }], task: [{ kind: 'task', term: 'SYNTHETIC delay', why: 'SYNTHETIC task term' }], setting_backup: [], task_backup: [{ term: 'SYNTHETIC backup' }] },
    rendered_queries: [{ provider_id: 'openalex', query_text: long, rationale: 'SYNTHETIC two blocks', dropped_terms: ['SYNTHETIC omitted'] }], skipped_terms: ['SYNTHETIC omitted'], selection: { model: plan.model, providers: plan.providers, budget: plan.budget, transport: plan.transport } },
    queries: [{ position: 1, provider: 'openalex', query_text: 'SYNTHETIC failed query', status: 'failed', record_count: 0, error_code: 'provider_timeout' },
      { position: 2, provider: 'openalex', query_text: 'SYNTHETIC uncertain delivery', status: 'outcome_unknown', record_count: 0, error_code: 'after_send_unknown' },
      { position: 3, provider: 'openalex', query_text: long, status: 'succeeded', record_count: 18, error_code: null }],
    counts, hits, cells, evidence: [{ id: 'q1', kill_search_id: 'current_search', source_version_id: 'work0', element_id: 'v3e0', matrix_cell_id: 'work00', evidence_kind: 'abstract', passage_id: null, quote: QUOTE }],
    summary: { failure_code: null, counts, queries: [], hits: hits.map((h, i) => ({ source_version_id: h.source_version_id, reading_depth: h.reading_depth, outcome: outcomes[i], reason: i === 2 ? 'no_shown_text' : i === 3 ? 'invalid_model_output' : null, omitted: { page_limit: i, message_size: 1 } })), usage: { model_calls: 5, provider_requests: 3 }, budget: plan.budget, frozen_reading_depth: true },
    search_status: computed, candidate_version_id: 'v3', version: 3, kill_search_id: 'current_search', is_latest_search_of_version: true,
  }
  const evidence: CandidateEvidence = { source: { ...hits[0].source, source_version_id: 'work0' }, passages: [{ passage_id: 'abstract0', source_id: 'work0', text: QUOTE + ' SYNTHETIC novel gap text. ' + long, reading_depth: 'abstract', locator: { kind: 'abstract', physical_page: null, printed_label: null }, abstract_origin: 'provider', text_source: 'provider' }],
    quotes: [...matrix.evidence, { id: 'q2', kill_search_id: 'current_search', source_version_id: 'work0', element_id: null, matrix_cell_id: null, evidence_kind: 'abstract', passage_id: null, quote: 'SYNTHETIC separate quote ' + long }] }
  const item = (c: CandidateCard): CandidateListItem => ({ id: c.id, origin: c.origin, origin_report_id: c.origin_report_id, origin_gap_row_id: c.origin_gap_row_id, gap_kind: c.gap_kind, origin_changed: c.origin_changed, current_version: c.current_version, trashed_at: c.trashed_at, claim_statement: c.versions.find(v => v.id === c.current_version_id)?.claim_statement ?? null, status: c.status?.computed ?? null, owner: c.status?.owner ?? null, active_run_id: c.active_run?.id ?? null })
  const owner: CandidateCard = { ...card, id: 'mock_owner', origin: 'owner_text', origin_text: CLAIM, origin_report_id: null, origin_gap_row_id: null, gap_kind: null, origin_changed: false, origin_basis: {}, origin_basis_view: {}, origin_provenance: {}, origin_fingerprint: null, current_version: 0, current_version_id: null, versions: [], searches: [], runs: [], active_run: null, status: null, owner_decisions: [] }
  return { card, owner, matrix, plan, evidence, long, item }
}

test('candidate copy keeps unknown codes, separate counts, both languages and candidate step names', () => {
  const computed = mockedCandidates('SYNTHETIC').card.status!.computed
  try {
    for (const language of ['en', 'tr'] as const) {
      setUiLanguage(language)
      const maps = [reasonLabels, relationLabels, alignmentLabels, statusLabels, assessmentLabels, depthLabels, kindLabels, outcomeLabels, refusalLabels, runReasonLabels, warningLabels, stepStateLabels]
      for (const map of maps) {
        expect(label(map, 'future_unknown_code')).toBe('future_unknown_code')
        for (const code of Object.keys(map)) {
          const text = label(map, code)
          expect(text).not.toMatch(/\b(novel|novelty|original|originality|unique|gap|foundational|verified|proof|proven|refuted|disproved|score|importance)\b|no prior work|does not exist/i)
          if (language === 'tr') expect(text).not.toBe(map[code])
        }
      }
      const open = reasonText(computed, 'no_match_in_assessed_subset')
      expect(open).toContain('3'); expect(open).toContain('18'); expect(open).toContain('15')
      expect(open).not.toContain('{')
      expect(reasonText(computed, 'future_unknown_reason')).toBe('future_unknown_reason')
      for (const [kind, key] of [['model:claim_decomposition', 'decompose'], ['claim_decomposition_summary', 'claim_decomposition_summary'], ['model:kill_search_query', 'query_terms'], ['kill_search_plan', 'kill_search_plan'], ['model:claim_assessment', 'assess:work0'], ['kill_search_summary', 'kill_search_summary']]) {
        expect(stepLabel(kind, key, true)).not.toMatch(/answer|yanıt/i)
        expect(stepLabel(kind, key, true)).not.toBe(kind)
      }
      expect(stepLabel('provider_search:openalex', 'search:1', true)).toContain('1')
      expect(stepLabel('model:future_task', 'future', true)).toBe('model:future_task')
    }
  } finally { setUiLanguage('en') }
})

test.describe('claim candidates', () => {
  const server = new CandidateServer()
  let api: APIRequestContext
  test.beforeAll(async () => server.start())
  test.afterAll(async () => server.stop())
  test.beforeEach(async () => { api = await apiRequest.newContext({ baseURL: SERVER_URL, extraHTTPHeaders: { origin: SERVER_URL } }) })
  test.afterEach(async () => api.dispose())

  test('owner claim, paused breakdown, versioned edit, confirmed search, matrix, evidence and durable decision', async ({ page }) => {
    test.setTimeout(240_000)
    await page.emulateMedia({ reducedMotion: 'reduce' })
    const f = await fixture(page, api)
    await candidatesTab(page)
    await expect(pane(page)).toContainText('No candidates yet. Use Add candidate')
    await capture(page, 'list', pane(page))
    const id = await add(page, f)
    await expect(pane(page)).toContainText('at most 6 model calls, no provider requests')
    await keyboardActivate(pane(page).getByRole('button', { name: 'Break the claim into testable parts' }))
    await pauseAndReject(page, f, id, 'claim_decomposition')
    await expect(pane(page).getByRole('heading', { name: 'Version 1', exact: true })).toBeVisible()
    await expect(pane(page)).toContainText('model proposal')
    await expect(pane(page)).toContainText('Written by a model from the text above; its structure was checked by code, its scientific content was not.')
    expect((await card(f, id)).versions[0].elements).toHaveLength(3)
    await capture(page, 'card', pane(page))
    await capture(page, 'editor', editSheet(page), async () => {
      await keyboardActivate(pane(page).getByRole('button', { name: 'Edit card' }))
      await expect(editSheet(page).getByLabel('Claim statement', { exact: true })).toHaveValue(CLAIM)
      await expect(editSheet(page).getByLabel('Claim statement', { exact: true })).toBeFocused()
    }, () => page.keyboard.press('Escape'))
    await expect(pane(page).getByRole('button', { name: 'Edit card' })).toBeFocused()
    await keyboardActivate(pane(page).getByRole('button', { name: 'Edit card' }))
    await editSheet(page).getByLabel('Claim statement', { exact: true }).fill(CLAIM + ' Edited.')
    await editSheet(page).getByLabel('Element 2 text').fill('SYNTHETIC different load conditions')
    await editSheet(page).getByRole('button', { name: 'Save', exact: true }).click()
    await expect(pane(page)).toContainText('Saved as version 2.')
    await expect(pane(page).getByRole('button', { name: 'Edit card' })).toBeFocused()
    await expect(pane(page)).toContainText('your edit')
    await pane(page).getByText('Earlier versions (1)', { exact: true }).click()
    await expect(pane(page).getByRole('heading', { name: 'Version 1', exact: true })).toBeVisible()
    await pane(page).getByText('Earlier versions (1)', { exact: true }).click()
    await keyboardActivate(pane(page).getByRole('button', { name: 'Plan the search' }))
    await expect(planPane(page).getByRole('heading', { name: 'Search plan', exact: true })).toBeFocused()
    await expect(planPane(page)).toContainText('Version 2 only; results of other versions are not carried over.')
    await expect(planPane(page)).toContainText('OpenAlex')
    await expect(planPane(page)).toContainText('Model-call ceiling: at most 54 model calls')
    await expect(planPane(page)).toContainText('Provider-request ceiling: at most')
    await expect(planPane(page)).toContainText('At most 6 queries of 20 records each, no paging.')
    await expect(planPane(page)).toContainText('At most 8 works are read.')
    await capture(page, 'plan', planPane(page))
    await keyboardActivate(planPane(page).getByRole('button', { name: 'Start', exact: true }))
    await pauseAndReject(page, f, id, 'kill_search')
    await expect(decision(page)).toContainText('Computed: Narrowed')
    await expect(decision(page)).toContainText('Partial overlap was recorded for the assessed works.')
    await expect(decision(page)).toContainText('kept for assessment 3; assessed 3; not read 0')
    const c = await card(f, id), search = c.searches[c.searches.length - 1]
    const m: CandidateMatrix = await (await api.get(`${f.base}/${id}/kill-searches/${search.id}`)).json()
    expect(m.search_status.status).toBe('narrowed')
    expect(m.hits.map(h => h.source.title)).toEqual([TITLE_A, 'SYNTHETIC W-B unrelated sediment measurements', 'SYNTHETIC W-C unrelated abstract shown'])
    // Five compiled queries; only OpenAlex and bioRxiv return the three DOI-identical works.
    expect(m.counts).toEqual({ found: 6, kept: 3, rank_cut: 0, duplicates: 3 })
    expect(m.hits.map(h => h.rank)).toEqual([1, 2, 3])
    const matrix = pane(page).locator('.candidate-matrix-section')
    await expect(matrix).toContainText('Found 6 results in 5 provider searches; 3 works were kept for assessment, 3 of them were assessed; 0 results ranked lower were not read; 3 duplicates were merged.')
    await expect(matrix.locator('tbody tr')).toHaveCount(3)
    for (const text of ['stated in the text', 'same conditions', 'partly matched', 'different conditions', 'no match in the text shown']) await expect(matrix).toContainText(text)
    await expect(matrix.getByRole('list').first()).toContainText('OpenAlex')
    await matrix.getByText('Search terms the model wrote', { exact: true }).click()
    await expect(matrix).toContainText('kfourclaim')
    await expect(pane(page).locator('.candidate-timeline').filter({ hasText: 'works assessed' })).toContainText('3 of 3 works assessed')
    await capture(page, 'matrix', matrix)
    const work = matrix.getByRole('button', { name: TITLE_A, exact: true })
    await keyboardActivate(work)
    const sheet = page.getByRole('dialog', { name: 'Evidence shown to the model' })
    await expect(sheet).toContainText('These are the exact passages the model was given. Nothing else of this work was read.')
    // The backend stores the located words without the quote's trailing full stop.
    await expect(sheet.locator('mark').first()).toHaveText(QUOTE.replace(/\.$/, ''))
    await expect(sheet).toContainText('Located in the text shown to the model')
    await expect(sheet).toContainText('Semantic support not checked.')
    await chromeWords(sheet)
    await page.keyboard.press('Escape'); await expect(work).toBeFocused()
    await capture(page, 'evidence', sheet, () => keyboardActivate(work), () => page.keyboard.press('Escape'))
    await keyboardActivate(decision(page).getByRole('button', { name: 'Record my decision' }))
    await expect(decision(page).getByLabel('Decision status')).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(decision(page).getByRole('button', { name: 'Record my decision' })).toBeFocused()
    await keyboardActivate(decision(page).getByRole('button', { name: 'Record my decision' }))
    await decision(page).getByLabel('Decision status').selectOption('closed')
    await decision(page).getByLabel('Reason', { exact: true }).fill('   ')
    await decision(page).getByRole('button', { name: 'Save', exact: true }).click()
    await expect(decision(page)).toContainText('Enter a non-blank reason.')
    await decision(page).getByLabel('Reason', { exact: true }).fill('  SYNTHETIC owner reason, not independent evidence.  ')
    await decision(page).getByRole('button', { name: 'Save', exact: true }).click()
    await expect(decision(page)).toContainText('Computed: Narrowed · Yours: closed')
    await expect(decision(page).getByRole('button', { name: 'Record my decision' })).toBeFocused()
    await capture(page, 'status-decision', decision(page))
    await chromeWords(pane(page))
    await expect(pane(page).locator('[data-stored-text]').filter({ hasText: CLAIM }).first()).toHaveText(CLAIM)
    await page.reload(); await candidatesTab(page)
    await keyboardActivate(pane(page).locator('.candidate-list-row').first())
    await expect(decision(page)).toContainText('Computed: Narrowed · Yours: closed')
    await expect(decision(page)).toContainText('SYNTHETIC owner reason, not independent evidence.')
    expect((await card(f, id)).status?.computed.status).toBe('narrowed')
    await pane(page).getByRole('button', { name: 'Candidates', exact: true }).click()
    await expect(pane(page).locator('.candidate-list-row').first()).toBeFocused()
  })

  test('a single search of an earlier version reopens its matrix and evidence after an edit', async ({ page }) => {
    const f = await fixture(page, api), id = await add(page, f)
    await pane(page).getByRole('button', { name: 'Break the claim into testable parts' }).click()
    await expect(pane(page).getByRole('heading', { name: 'Version 1', exact: true })).toBeVisible()
    await pane(page).getByRole('button', { name: 'Plan the search' }).click()
    await expect(planPane(page).getByRole('button', { name: 'Start', exact: true })).toBeEnabled()
    await planPane(page).getByRole('button', { name: 'Start', exact: true }).click()
    await expect(decision(page)).toContainText('Computed: Narrowed')
    expect((await card(f, id)).searches).toHaveLength(1)
    await pane(page).getByRole('button', { name: 'Edit card' }).click()
    await editSheet(page).getByLabel('Claim statement', { exact: true }).fill(CLAIM + ' Version 2.')
    await editSheet(page).getByRole('button', { name: 'Save', exact: true }).click()
    await expect(pane(page)).toContainText('Saved as version 2.')
    // No search belongs to V2, but the one stored V1 search must remain reachable.
    await expect(pane(page).getByRole('button', { name: /^Version 1, not the current version/ })).toBeVisible()
    await page.reload(); await candidatesTab(page)
    await pane(page).locator('.candidate-list-row').first().click()
    await pane(page).getByText('Earlier versions (1)', { exact: true }).click()
    await expect(pane(page).getByRole('heading', { name: 'Version 1', exact: true })).toBeVisible()
    await expect(pane(page)).toContainText('1 searches ran on this version')
    await pane(page).getByRole('button', { name: /^Version 1, not the current version/ }).click()
    const matrix = pane(page).locator('.candidate-matrix-section')
    await expect(matrix).toContainText('Version 1')
    await expect(matrix.locator('tbody tr')).toHaveCount(3)
    await expect(decision(page)).toContainText('Computed status is for version 1; your decisions are for the current version 2.')
    await matrix.getByRole('button', { name: TITLE_A, exact: true }).click()
    const sheet = page.getByRole('dialog', { name: 'Evidence shown to the model' })
    await expect(sheet.locator('mark').first()).toHaveText(QUOTE.replace(/\.$/, ''))
    await expect(sheet).toContainText('These are the exact passages the model was given.')
    await expect(sheet).toContainText('Semantic support not checked.')
  })

  test('a delayed save applies its version without closing a reopened editor or losing its draft', async ({ page }) => {
    const f = await fixture(page, api), id = await add(page, f)
    await pane(page).getByRole('button', { name: 'Break the claim into testable parts' }).click()
    await expect(pane(page).getByRole('heading', { name: 'Version 1', exact: true })).toBeVisible()
    await installResponseBarrier(page, 'late-editor-save')
    let releaseSave: (() => void) | undefined
    let saveStarted: (() => void) | undefined
    const started = new Promise<void>(resolve => { saveStarted = resolve })
    await page.route(`**${f.base}/${id}/versions`, async route => {
      const response = await route.fetch()
      saveStarted?.()
      await new Promise<void>(resolve => { releaseSave = resolve })
      await route.fulfill({ response, headers: { ...response.headers(), 'x-k4-response-barrier': 'late-editor-save' } })
    })
    await pane(page).getByRole('button', { name: 'Edit card' }).click()
    await editSheet(page).getByLabel('Claim statement', { exact: true }).fill('SYNTHETIC first session saved')
    await editSheet(page).getByRole('button', { name: 'Save', exact: true }).click()
    await started
    await editSheet(page).getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(editSheet(page)).toBeHidden()
    await pane(page).getByRole('button', { name: 'Edit card' }).click()
    await editSheet(page).getByLabel('Claim statement', { exact: true }).fill('SYNTHETIC reopened session unsaved draft')
    releaseSave?.()
    await expect(page.locator('html')).toHaveAttribute('data-k4-processed-response', 'late-editor-save')
    await expect(editSheet(page)).toBeVisible()
    await expect(editSheet(page).getByLabel('Claim statement', { exact: true })).toHaveValue('SYNTHETIC reopened session unsaved draft')
    await expect(pane(page)).toContainText('Saved as version 2.')
    expect((await card(f, id)).versions.find(v => v.version === 2)?.claim_statement).toBe('SYNTHETIC first session saved')
  })

  test('stale version keeps typed text; reload permits a new version; non-blank required fields and API 422', async ({ page }) => {
    const f = await fixture(page, api), id = await add(page, f)
    await pane(page).getByRole('button', { name: 'Break the claim into testable parts' }).click()
    await expect(pane(page).getByRole('heading', { name: 'Version 1', exact: true })).toBeVisible()
    await pane(page).getByRole('button', { name: 'Edit card' }).click()
    await editSheet(page).getByLabel('Claim statement', { exact: true }).fill('SYNTHETIC typed text kept after conflict')
    const before = await card(f, id)
    expect((await api.post(`${f.base}/${id}/versions`, { headers: f.headers, data: editBody(before) })).status()).toBe(201)
    await editSheet(page).getByRole('button', { name: 'Save', exact: true }).click()
    await expect(editSheet(page)).toContainText('This card changed since you opened it')
    await editSheet(page).getByRole('button', { name: 'Reload' }).click()
    await expect(editSheet(page).getByLabel('Claim statement', { exact: true })).toHaveValue('SYNTHETIC typed text kept after conflict')
    await editSheet(page).getByLabel('Critical assumption', { exact: true }).fill('   ')
    await expect(editSheet(page).getByRole('button', { name: 'Save', exact: true })).toBeDisabled()
    await editSheet(page).getByLabel('Critical assumption', { exact: true }).fill('SYNTHETIC required assumption')
    await editSheet(page).getByLabel('Claim statement', { exact: true }).fill('   ')
    await editSheet(page).getByRole('button', { name: 'Save', exact: true }).click()
    await expect(editSheet(page)).toContainText('Candidate text must be non-blank and contain no NUL')
    await expect(editSheet(page).getByLabel('Claim statement', { exact: true })).toHaveValue('   ')
    await editSheet(page).getByLabel('Claim statement', { exact: true }).fill('SYNTHETIC stored after reload')
    await editSheet(page).getByRole('button', { name: 'Save', exact: true }).click()
    await expect(pane(page)).toContainText('Saved as version 3.')
  })

  test('access variant shows unavailable text without claiming whether a send happened', async ({ page }) => {
    const f = await fixture(page, api, '[candidate-access]'), id = await add(page, f)
    await pane(page).getByRole('button', { name: 'Break the claim into testable parts' }).click()
    await expect(pane(page).getByRole('heading', { name: 'Version 1', exact: true })).toBeVisible()
    await pane(page).getByRole('button', { name: 'Plan the search' }).click()
    await expect(planPane(page).getByRole('button', { name: 'Start', exact: true })).toBeEnabled()
    await planPane(page).getByRole('button', { name: 'Start', exact: true }).click()
    await expect(decision(page)).toContainText('A work could not be assessed because usable text was unavailable.')
    await expect(decision(page)).toContainText('Computed: Undecided')
    await expect(pane(page).locator('.candidate-matrix-section')).toContainText('Found 8 results in 5 provider searches; 4 works were kept for assessment, 3 of them were assessed; 0 results ranked lower were not read; 4 duplicates were merged.')
    await expect(pane(page).locator('tbody tr')).toHaveCount(4)
    const row = pane(page).locator('tbody tr').filter({ hasText: 'SYNTHETIC W-D metadata only' })
    await expect(row).toHaveCount(1)
    await expect(row).toContainText('Rank 4')
    await expect(row).toContainText('assessment could not be completed: usable text was unavailable')
    await row.getByRole('button', { name: 'Show evidence' }).click()
    const sheet = page.getByRole('dialog', { name: 'Evidence shown to the model' })
    await expect(sheet).toContainText('No assessed passages are stored for this work')
    await expect(sheet).not.toContainText('Nothing else of this work was read')
    await expect(sheet).not.toContainText('never sent')
    await expect(sheet.locator('mark')).toHaveCount(0)
    await chromeWords(sheet)
    const c = await card(f, id)
    expect(c.status?.computed.reasons).toContain('insufficient_access')
    const search = c.searches[c.searches.length - 1]
    const m: CandidateMatrix = await (await api.get(`${f.base}/${id}/kill-searches/${search.id}`)).json()
    expect(m.counts).toEqual({ found: 8, kept: 4, rank_cut: 0, duplicates: 4 })
    expect(m.hits.map(h => h.rank)).toEqual([1, 2, 3, 4])
    expect(m.hits.map(h => h.source.title)).toEqual([TITLE_A, 'SYNTHETIC W-B unrelated sediment measurements', 'SYNTHETIC W-C unrelated abstract shown', 'SYNTHETIC W-D metadata only'])
  })

  test('report VI opens the same stored row twice without changing report text or starting a run', async ({ page }) => {
    test.setTimeout(240_000)
    const f = await fixture(page, api)
    const rv = await research(f), source = rv.sources.find(s => s.title.includes('with bisection'))!
    expect((await api.patch(`/api/researches/${f.rid}/selections/${source.source_version_id}`, { headers: f.headers, data: { state: 'included', expected_version: source.selection.version, reason: 'SYNTHETIC include' } })).ok()).toBe(true)
    const created: TableView = await (await api.post(`/api/researches/${f.rid}/tables`, { headers: f.headers, data: { title: 'SYNTHETIC report table' } })).json()
    const tid = created.table.id, base = `/api/researches/${f.rid}/tables/${tid}`
    const columns = await api.post(`${base}/columns`, { headers: f.headers, data: { name: 'SYNTHETIC method', instruction: 'Record the method.', answer_format: 'text', options: null, allow_multiple: false, unit_hint: null, expected_version: created.table.version } })
    expect(columns.status()).toBe(201)
    const table: TableView = await columns.json()
    const filled: Run = await (await api.post(`${base}/fill`, { headers: f.headers, data: { expected_version: table.table.version } })).json()
    await waitRun(f, filled.id)
    const reportRun: Run = await (await api.post(`/api/researches/${f.rid}/reports`, { headers: f.headers, data: { table_id: tid } })).json()
    await waitRun(f, reportRun.id)
    const reportId = reportRun.target!.report_id!
    const reportPath = `/api/researches/${f.rid}/reports/${reportId}`
    const before = await (await api.get(reportPath)).json()
    // The report fixture produces no report_gaps row. Seed ONE synthetic row only after its run is terminal.
    // This helper writes solely to this spec's temporary SQLite file. The sheet is reopened after the commit.
    server.seed(`import sqlite3,sys,json
c=sqlite3.connect(sys.argv[1]); r=sys.argv[2]
assert c.execute("SELECT status FROM runs WHERE id=(SELECT run_id FROM reports WHERE id=?)",(r,)).fetchone()[0]=='completed'
c.execute("INSERT INTO report_gaps (id,report_id,gap_id,kind,text,basis_json,provenance_json,created_at) VALUES ('gap_k4_seed',?,'g1','corpus_absence',?,?,?,'2026-10-02T12:00:00Z')",(r,sys.argv[3],json.dumps({'basis_cell_ids':[],'basis_passage_ids':[],'basis_claim_keys':[]}),json.dumps({'origin':'code','section_id':'VI','step_input_id':None})))
c.commit(); c.close()`, [reportId, ROW_TEXT])
    const openReport = async () => { await page.getByRole('tab', { name: /^Artifacts/ }).click(); await page.locator('.artifact-list').getByRole('button').filter({ hasText: 'Evidence report' }).first().click(); await expect(page.locator('.candidate-aspects')).toContainText(ROW_TEXT) }
    await page.reload(); await openReport()
    const block = page.locator('.candidate-aspects')
    await expect(block).toContainText('absent from the corpus read')
    await expect(page.locator('.report-sheet')).toContainText('Candidate aspects the model inferred from the evidence table; none was checked by a kill-search.')
    await page.keyboard.press('Escape')
    await capture(page, 'report-vi', block, openReport, () => page.keyboard.press('Escape'))
    await openReport()
    const count = (await research(f)).runs.length
    await keyboardActivate(block.getByRole('button', { name: 'Investigate' }))
    await expect(pane(page)).toContainText('Opened from a report row: absent from the corpus read')
    await expect(pane(page).locator('[data-stored-text]').first()).toHaveText(ROW_TEXT)
    const first = ((await api.get(f.base)).ok() ? await (await api.get(f.base)).json() : []) as CandidateListItem[]
    await openReport()
    await expect(block.getByRole('button', { name: /^Open candidate/ })).toBeVisible()
    await keyboardActivate(block.getByRole('button', { name: 'Investigate' }))
    const second: CandidateListItem[] = await (await api.get(f.base)).json()
    expect(second.map(c => c.id)).toEqual(first.map(c => c.id))
    expect((await research(f)).runs.length).toBe(count)
    const after = await (await api.get(reportPath)).json()
    expect(after.sections.map((s: { claims: unknown }) => s.claims)).toEqual(before.sections.map((s: { claims: unknown }) => s.claims))
    // Mock only the additive read route and VI's status to exercise empty, failed and unvalidated rendering.
    let rows: { id: string; gap_id: string; kind: string; text: string }[] = [], failRows = false
    await page.route(`**${reportPath}`, route => route.fulfill({ json: { ...after, sections: after.sections.map((s: { section_id: string }) => s.section_id === 'VI' ? { ...s, status: 'draft' } : s) } }))
    await page.route(`**${reportPath}/gaps`, route => route.fulfill(failRows ? { status: 500, json: { detail: 'SYNTHETIC aspect fetch failed' } } : { json: rows }))
    await page.getByRole('tab', { name: /^Artifacts/ }).click()
    const reportButton = page.locator('.artifact-list').getByRole('button').filter({ hasText: 'Evidence report' }).first()
    await reportButton.click()
    await expect(block).toContainText('No aspects were recorded for this report.')
    await expect(block).toContainText('This section was not validated; the rows below are what the model proposed')
    await chromeWords(block)
    await page.keyboard.press('Escape')
    failRows = true
    await reportButton.click()
    await expect(block.getByRole('alert')).toContainText('SYNTHETIC aspect fetch failed')
    rows = ['stated_limitation', 'conflicting_evidence', 'corpus_absence', 'SYNTHETIC_kind'].map((kind, i) => ({ id: `row${i}`, gap_id: `g${i}`, kind, text: ROW_TEXT }))
    failRows = false
    await block.getByRole('button', { name: 'Retry' }).click()
    await expect(block.getByRole('button', { name: 'Investigate', exact: true })).toHaveCount(4)
    for (const kind of ['stated limitation', 'conflicting evidence', 'absent from the corpus read', 'SYNTHETIC_kind']) await expect(block).toContainText(kind)
    for (const text of await block.locator('[data-stored-text]').allTextContents()) expect(text).toBe(ROW_TEXT)
    await chromeWords(block)
    await page.keyboard.press('Escape')
    await capture(page, 'mock-report-vi', block, () => reportButton.click(), () => page.keyboard.press('Escape'))
  })

  test('old paused decomposition outside bounded run windows is refused by the API and shown on the card', async ({ page }) => {
    const f = await fixture(page, api), id = await add(page, f)
    await pane(page).getByRole('button', { name: 'Break the claim into testable parts' }).click()
    await pane(page).locator('.candidate-run').getByRole('button', { name: 'Pause', exact: true }).click()
    const paused = (await research(f)).runs.find(r => r.kind === 'claim_decomposition')!
    await waitRun(f, paused.id, 'paused')
    // Synthetic terminal history hides the paused run from both bounded windows. No model call is run.
    // Store.create_run is used solely for fixture history; production start routes refuse this sequence.
    server.seed(`import sys
from pathlib import Path
from deixis.storage import db
from deixis.workflow.store import Store
c=db.connect(Path(sys.argv[1])); s=Store(c)
with db.transaction(c):
 for i in range(11):
  r=s.create_run(sys.argv[2],'claim_decomposition',{},None,{'candidate_id':sys.argv[3]})
  s.update_run(r['id'],status='completed')
c.close()`, [f.rid, id])
    await page.reload(); await candidatesTab(page)
    await pane(page).getByRole('button', { name: CLAIM }).click()
    await expect(pane(page)).toContainText('Showing the last 5 runs')
    await expect(pane(page)).toContainText('bounded views, not a complete history')
    await expect(pane(page).getByRole('button', { name: 'Break the claim into testable parts' })).toBeEnabled()
    await pane(page).getByRole('button', { name: 'Break the claim into testable parts' }).click()
    await expect(pane(page).getByRole('alert')).toContainText(`Resume or cancel paused candidate run ${paused.id} first`)
    // Clean up the synthetic paused run through its real control route before the next test.
    expect((await api.post(`/api/runs/${paused.id}/cancel`, { headers: f.headers })).ok()).toBe(true)
  })

  test('mocked JSON preserves every bounded list, known label, uncertainty and stored text', async ({ page }) => {
    test.setTimeout(240_000)
    await page.emulateMedia({ reducedMotion: 'reduce' })
    const f = await fixture(page, api), mock = mockedCandidates(f.rid)
    let current = mock.card, matrix = mock.matrix, plan = mock.plan
    const planReads: string[] = [], startFingerprints: string[] = []
    let refusePlan: string | null = null, rejectStart = true, rejectDecision = true, failEvidence = false
    let delayNextRead = false
    let releaseRead: (() => void) | undefined
    let readStarted: (() => void) | undefined
    await page.route(`**${f.base}/**`, async route => {
      const pathname = new URL(route.request().url()).pathname, method = route.request().method()
      if (pathname.endsWith('/kill-search/plan')) {
        if (refusePlan) return route.fulfill({ status: 422, json: { detail: refusePlan } })
        expect(method).toBe('GET')
        planReads.push(plan.preview_fingerprint)
        return route.fulfill({ json: plan })
      }
      if (pathname.endsWith('/kill-search') && method === 'POST') {
        startFingerprints.push(route.request().postDataJSON().preview_fingerprint)
        if (rejectStart) { rejectStart = false; plan = { ...plan, preview_fingerprint: 'c'.repeat(64) }; return route.fulfill({ status: 409, json: { detail: 'Kill-search plan changed; preview it again' } }) }
        return route.fulfill({ status: 422, json: { detail: 'SYNTHETIC start refused' } })
      }
      if (pathname.endsWith('/owner-decision')) {
        if (rejectDecision) { rejectDecision = false; return route.fulfill({ status: 422, json: { detail: 'SYNTHETIC reason refused' } }) }
        return route.fulfill({ status: 201, json: current })
      }
      if (pathname.endsWith('/versions') && method === 'POST') {
        const body = route.request().postDataJSON() as CandidateEdit
        const newest = { ...current.versions[2], claim_statement: body.claim_statement, conditions: body.conditions, nearest_simple_explanation: body.nearest_simple_explanation, critical_assumption: body.critical_assumption, validation_plan: body.validation_plan,
          elements: body.elements.map((e, i) => ({ ...e, id: `v4e${i}`, candidate_version_id: 'v4', position: i + 1 })), id: 'v4', version: 4, origin: 'human_edit' as const, step_input_id: null, created_at: '2026-10-02T13:00:00Z' }
        current = { ...current, versions: [...current.versions, newest], current_version: 4, current_version_id: 'v4', status: { computed: { ...matrix.search_status, status: 'not_run', reason: 'not_searched' }, previous: null, owner: null }, owner_decisions: [] }
        return route.fulfill({ status: 201, json: current })
      }
      if (pathname.includes('/hits/')) {
        if (failEvidence) return route.fulfill({ status: 404, json: { detail: 'Not found: SYNTHETIC evidence' } })
        if (pathname.endsWith('/work6')) return route.fulfill({ json: { source: { ...matrix.hits[6].source, source_version_id: 'work6' }, passages: [], quotes: [] } })
        return route.fulfill({ json: mock.evidence })
      }
      if (pathname.endsWith('/old_search')) return route.fulfill({ json: { ...matrix, search: { ...matrix.search, id: 'old_search', candidate_version_id: 'v2', run_id: 'old_run' }, kill_search_id: 'old_search', candidate_version_id: 'v2', version: 2, is_latest_search_of_version: true, search_status: { ...matrix.search_status, status: 'open', reason: 'no_match_in_assessed_subset' }, cells: {} } })
      if (pathname.includes('/kill-searches/')) return route.fulfill({ json: matrix })
      if (pathname.endsWith('/mock_owner')) return route.fulfill({ json: mock.owner })
      if (pathname.endsWith('/mock_card')) {
        const snapshot = structuredClone(current)
        if (delayNextRead) {
          delayNextRead = false; readStarted?.(); await new Promise<void>(resolve => { releaseRead = resolve })
          return route.fulfill({ json: snapshot, headers: { 'x-k4-response-barrier': 'late-card-read' } })
        }
        return route.fulfill({ json: snapshot })
      }
      return route.fallback()
    })
    await page.route(`**${f.base}`, route => route.fulfill({ json: [mock.item(current), mock.item(mock.owner), { ...mock.item(mock.owner), id: 'trashed', claim_statement: 'SYNTHETIC stored trash', trashed_at: '2026-10-01T12:00:00Z' }] }))
    await candidatesTab(page)
    await expect(pane(page).locator('.candidate-list-row')).toHaveCount(2)
    await expect(pane(page)).toContainText('In the Trash')
    await expect(pane(page).getByText('SYNTHETIC stored trash')).toBeVisible()
    await expect(page.getByRole('tab', { name: /^Candidates/ })).toContainText('2')
    await expect(pane(page).locator('.candidate-list-row').last()).toContainText(CLAIM)
    await capture(page, 'mock-list', pane(page))
    await keyboardActivate(pane(page).locator('.candidate-list-row').last())
    await expect(pane(page)).toContainText('This is your sentence, not a finding from the literature.')
    await expect(pane(page)).toContainText('No card yet')
    await keyboardActivate(pane(page).getByRole('button', { name: 'Write the card myself' }))
    await expect(editSheet(page).getByLabel('Critical assumption', { exact: true })).toHaveValue('')
    await expect(editSheet(page).getByRole('button', { name: 'Save', exact: true })).toBeDisabled()
    await expect(editSheet(page)).toContainText('A card needs 2 to 6 elements.')
    await page.keyboard.press('Escape')
    await pane(page).getByRole('button', { name: 'Candidates', exact: true }).click()
    await expect(pane(page).locator('.candidate-list-row').last()).toBeFocused()
    await keyboardActivate(pane(page).locator('.candidate-list-row').first())
    await expect(decision(page)).toContainText('Computed: Undecided')
    await expect(pane(page)).toContainText('A later candidate was opened from the same report row')
    await pane(page).getByText('What it was opened from', { exact: true }).click()
    await expect(pane(page).getByText('no longer available', { exact: true })).toHaveCount(3)
    for (const text of ['SYNTHETIC novel cell', 'SYNTHETIC gap passage', 'SYNTHETIC claim']) await expect(pane(page).getByText(text, { exact: true })).toBeVisible()
    await pane(page).getByText('Earlier versions (2)', { exact: true }).click()
    await expect(pane(page).getByRole('heading', { name: /^Version [123]$/ })).toHaveCount(3)
    await expect(pane(page).getByText('1 searches ran on this version', { exact: true })).toHaveCount(2)
    await expect(decision(page).locator('section[aria-label="Your decision"] ol li')).toHaveCount(10)
    await expect(decision(page)).toContainText('Earlier search: Narrowed')
    await expect(pane(page)).toContainText('Showing the last 5 runs')
    const running = pane(page).locator('.candidate-run').first(), paused = pane(page).locator('.candidate-run').nth(1)
    await expect(pane(page).locator('.candidate-run').nth(2)).not.toContainText('works assessed')
    await expect(pane(page)).not.toContainText('0 of 0 works assessed')
    await expect(running.getByRole('button', { name: 'Pause', exact: true })).toBeVisible()
    await expect(paused.getByRole('button', { name: 'Resume' })).toBeVisible()
    await expect(paused.getByRole('button', { name: 'Cancel', exact: true })).toBeVisible()
    await expect(pane(page).locator('.candidate-run').nth(2).getByRole('button')).toHaveCount(0)
    await expect(pane(page).getByRole('button', { name: 'Plan the search' })).toBeDisabled()
    await expect(pane(page)).toContainText('A run of this candidate is paused: resume or cancel it first')
    await expect(pane(page)).toContainText('The provider did not answer in time.')
    await expect(pane(page)).toContainText('outcome unknown')
    await expect(pane(page)).toContainText('Found 18 results in 3 provider searches; 8 works were kept for assessment, 3 of them were assessed; 10 results ranked lower were not read; 2 duplicates were merged.')
    const table = pane(page).locator('.candidate-matrix')
    await expect(table.locator('tbody tr')).toHaveCount(8)
    for (const text of Object.values(relationLabels)) await expect(table).toContainText(text)
    for (const text of Object.values(alignmentLabels)) await expect(table).toContainText(text)
    for (const text of ['abstract', 'stored passages', 'metadata only', 'no published assessment', 'assessment did not complete', 'the model output was invalid', 'the message was too large', 'assessment was not reached within the run budget', 'No cells are published for this work:']) await expect(table).toContainText(text)
    await pane(page).locator('details').evaluateAll(items => items.forEach(el => (el as HTMLDetailsElement).open = true))
    for (const heading of ['Setting terms', 'Task terms', 'Setting backup terms', 'Task backup terms', 'Cell values', 'Passage texts', 'Claim texts', 'Searches', 'Warnings', 'All status reasons']) await expect(pane(page).getByRole('heading', { name: new RegExp(`^${heading}`) }).first()).toBeVisible()
    await expect(pane(page)).toContainText('Terms omitted from OpenAlex:')
    await expect(pane(page)).toContainText('Skipped terms:')
    await expect(pane(page)).toContainText('None.')
    await chromeWords(pane(page))
    await capture(page, 'mock-matrix', table)
    await capture(page, 'mock-status-history', decision(page))
    const title = table.getByRole('button', { name: TITLE_A, exact: true })
    await capture(page, 'mock-evidence', page.getByRole('dialog', { name: 'Evidence shown to the model' }), () => keyboardActivate(title), () => page.keyboard.press('Escape'))
    failEvidence = true
    await keyboardActivate(title)
    const sheet = page.getByRole('dialog', { name: 'Evidence shown to the model' })
    await expect(sheet.getByRole('alert')).toContainText('Not found: SYNTHETIC evidence')
    failEvidence = false
    await sheet.getByRole('button', { name: 'Retry' }).click()
    await expect(sheet.locator('mark')).toHaveText(QUOTE)
    await expect(sheet.locator('h3.candidate-claim')).toHaveCSS('font-family', '"Newsreader Variable", serif')
    await expect(sheet).toContainText('For the whole claim')
    await expect(sheet).toContainText('not marked: shown separately')
    await expect(sheet).toContainText('SYNTHETIC novel gap text.')
    await chromeWords(sheet)
    await page.keyboard.press('Escape'); await expect(title).toBeFocused()
    await table.locator('tbody tr').nth(6).getByRole('button', { name: 'Show evidence' }).click()
    await expect(sheet).toContainText('No assessed passages are stored for this work')
    await expect(sheet).toContainText('no published assessment')
    await expect(sheet).not.toContainText('Nothing else of this work was read')
    await expect(sheet).not.toContainText('never sent')
    await page.keyboard.press('Escape')
    // All five computed states and every known reason are served independently, rather than inferred from fixtures.
    const statusFor: Record<string, CandidateStatus> = { not_searched: 'not_run', whole_claim_stated: 'closed', partial_overlap: 'narrowed', no_match_in_assessed_subset: 'open' }
    for (const [code, sentence] of Object.entries(reasonLabels)) {
      matrix = { ...matrix, search_status: { ...matrix.search_status, status: statusFor[code] ?? 'undecided', reason: code, reasons: [code] } }
      await pane(page).getByRole('button', { name: 'Refresh' }).click()
      await expect(decision(page)).toContainText(`Computed: ${statusLabels[statusFor[code] ?? 'undecided']}`)
      await expect(decision(page)).toContainText(sentence.replace('{assessed}', '3').replace('{found}', '18').replace('{unread}', '15'))
      await expect(decision(page)).not.toContainText(code)
      await chromeWords(decision(page))
    }
    await pane(page).getByRole('button', { name: /^Version 2, not the current version/ }).click()
    await expect(decision(page)).toContainText('Computed: Open')
    await expect(decision(page)).toContainText('Computed status is for version 2; your decisions are for the current version 3.')
    await expect(decision(page)).not.toContainText('Earlier search:')
    await expect(pane(page).locator('.candidate-matrix-section')).toContainText('Version 2')
    await pane(page).getByRole('button', { name: /^Version 3 ·/ }).click()
    await expect(pane(page).locator('.candidate-matrix-section')).toContainText('Version 3')
    current = { ...current, runs: current.runs.map(r => r.status === 'running' || r.status === 'paused' ? { ...r, status: 'completed', pause_reason: null } : r), active_run: null, searches: current.searches.map(s => ({ ...s, outcome: 'completed' })) }
    await pane(page).getByRole('button', { name: 'Refresh' }).click()
    await expect(pane(page).getByRole('button', { name: 'Plan the search' })).toBeEnabled()
    await keyboardActivate(pane(page).getByRole('button', { name: 'Plan the search' }))
    await expect(planPane(page)).toContainText('Version 3 only')
    await keyboardActivate(planPane(page).getByRole('button', { name: 'Start', exact: true }))
    await expect(planPane(page).getByRole('alert')).toContainText('Kill-search plan changed; preview it again')
    await expect.poll(() => planReads.length).toBe(2)
    expect(planReads).toEqual(['b'.repeat(64), 'c'.repeat(64)])
    await planPane(page).getByRole('button', { name: 'Start', exact: true }).click()
    await expect(planPane(page)).toContainText('SYNTHETIC start refused')
    expect(startFingerprints).toEqual(['b'.repeat(64), 'c'.repeat(64)])
    await chromeWords(planPane(page))
    await planPane(page).getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(pane(page).getByRole('button', { name: 'Plan the search' })).toBeFocused()
    for (const [code, sentence] of [['candidate_not_decomposed', 'Write or break down the claim before planning a search.'], ['no_searchable_provider', 'No selected provider can search this claim.'], ['SYNTHETIC_unknown', 'SYNTHETIC_unknown']]) {
      refusePlan = code
      await pane(page).getByRole('button', { name: 'Plan the search' }).click()
      await expect(planPane(page)).toContainText(sentence)
      await expect(planPane(page).getByRole('button', { name: 'Start', exact: true })).toBeDisabled()
      await planPane(page).getByRole('button', { name: 'Cancel', exact: true }).click()
      // Closing the plan card hands focus back to its opener on the next frame; wait for that before moving on.
      await expect(pane(page).getByRole('button', { name: 'Plan the search' })).toBeFocused()
    }
    await keyboardActivate(decision(page).getByRole('button', { name: 'Record my decision' }))
    await decision(page).getByLabel('Reason', { exact: true }).fill('SYNTHETIC typed reason remains')
    await decision(page).getByRole('button', { name: 'Save', exact: true }).click()
    await expect(decision(page)).toContainText('SYNTHETIC reason refused')
    await expect(decision(page).getByLabel('Reason', { exact: true })).toHaveValue('SYNTHETIC typed reason remains')
    // One deliberately late read cannot overwrite a successful version write (the sub-view ordering guard).
    await installResponseBarrier(page, 'late-card-read')
    await keyboardActivate(pane(page).getByRole('button', { name: 'Edit card' }))
    await editSheet(page).getByLabel('Claim statement', { exact: true }).fill('SYNTHETIC novel gap saved newest')
    const started = new Promise<void>(resolve => { readStarted = resolve })
    delayNextRead = true
    // The editor sheet is modal, so the Refresh button behind it is inert for role queries; click it by text.
    await pane(page).locator('button').filter({ hasText: /^Refresh$/ }).first().evaluate(el => (el as HTMLButtonElement).click())
    await started
    await editSheet(page).getByRole('button', { name: 'Save', exact: true }).click()
    await expect(pane(page)).toContainText('Saved as version 4.')
    await expect(pane(page).getByRole('button', { name: 'Edit card' })).toBeFocused()
    releaseRead?.()
    await expect(page.locator('html')).toHaveAttribute('data-k4-processed-response', 'late-card-read')
    await expect(pane(page).getByRole('heading', { name: 'Version 4', exact: true })).toBeVisible()
    await expect(pane(page)).toContainText('SYNTHETIC novel gap saved newest')
    await chromeWords(pane(page))
  })
})
