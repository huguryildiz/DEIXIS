import { expect, test, type Locator, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import type { CandidateCard, CandidateEdit, CandidateListItem, CandidatePlan, Connections, ResearchView, ReviewCard, ReviewDetail, ReviewPreview, ReviewRequest, Run } from '../src/api'
import { nextPort } from './ports'

// SYNTHETIC records and the scripted model only; a separate process, port and data directory.
// These cases check workflow behavior, not scientific review quality. Browser execution is external to the sandbox.
const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = process.env.DEIXIS_TEST_PYTHON ?? path.join(REPO, '.venv/bin/python')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })
class CandidateReviewServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-candidate-review-'))
  readonly port = nextPort()
  readonly url = `http://127.0.0.1:${this.port}`
  readonly releaseFile = path.join(this.dataDir, 'review-release')
  async start() {
    this.proc = spawn(PYTHON, [path.join(REPO, 'tests/acceptance/fixture_server.py'), '--data-dir', this.dataDir, '--port', String(this.port)], {
      cwd: REPO, env: { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: `${REPO}/backend:${REPO}` }, stdio: 'inherit',
    })
    await expect.poll(async () => {
      if (this.proc?.exitCode !== null) throw new Error('SYNTHETIC candidate review server exited before health')
      try { return (await fetch(`${this.url}/api/health`)).ok } catch { return false }
    }).toBe(true)
  }
  hold() { rmSync(this.releaseFile, { force: true }) }
  release() { writeFileSync(this.releaseFile, 'SYNTHETIC release\n') }
  seed(code: string, args: string[]) {
    const result = spawnSync(PYTHON, ['-c', code, path.join(this.dataDir, 'library.sqlite'), ...args],
      { cwd: REPO, env: { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: `${REPO}/backend:${REPO}` }, encoding: 'utf8' })
    expect(result.status, result.stderr).toBe(0)
  }
  async stop() {
    if (!this.proc || this.proc.exitCode !== null) return
    const ended = new Promise(resolve => this.proc?.once('exit', resolve))
    this.proc.kill('SIGTERM'); await ended
  }
}
const server = new CandidateReviewServer()
const pageErrors = new WeakMap<Page, Error[]>()
test.describe.configure({ mode: 'serial', timeout: 120_000 })
test.beforeAll(async () => server.start())
test.afterEach(({ page }) => {
  server.release()
  expect(pageErrors.get(page), 'Uncaught page errors').toEqual([])
})
test.afterAll(async () => server.stop())
test.beforeEach(async ({ page }) => {
  const errors: Error[] = []
  pageErrors.set(page, errors)
  page.on('pageerror', error => errors.push(error))
  server.hold()
  await page.addInitScript(() => { localStorage.setItem('deixis-ui-language', 'en'); localStorage.setItem('deixis-theme', 'system') })
  await page.emulateMedia({ colorScheme: 'light', reducedMotion: 'reduce' })
})
type Fixture = { rid: string; cid: string; vid: string }
const candidates = (page: Page) => page.locator('.candidate-detail')
const sheet = (page: Page) => page.getByRole('dialog', { name: 'Review by another model', exact: true })
const pane = (page: Page) => sheet(page).locator('.review-pane')
const form = (page: Page) => pane(page).locator('.review-request')
const button = (root: Locator, name: string) => root.getByRole('button', { name, exact: true })
const reviewBase = (f: Fixture) => `${server.url}/api/researches/${f.rid}/reviews`
const candidateBase = (f: Fixture) => `${server.url}/api/researches/${f.rid}/candidates/${f.cid}`
const view = async (page: Page, f: Fixture): Promise<ResearchView> => (await page.request.get(`${server.url}/api/researches/${f.rid}`)).json()
const card = async (page: Page, f: Fixture): Promise<CandidateCard> => (await page.request.get(candidateBase(f))).json()
async function headers(page: Page) {
  const csrf = (await page.context().cookies(server.url)).find(c => c.name === 'deixis_csrf')
  expect(csrf).toBeTruthy()
  return { origin: server.url, 'x-deixis-csrf': csrf!.value, 'Idempotency-Key': crypto.randomUUID() }
}
async function fixture(page: Page, held = false): Promise<Fixture> {
  await page.goto(server.url)
  await page.getByLabel('Research question').fill(`SYNTHETIC bounded scheduling [candidate] [review-finding] ${held ? '[review-hold]' : ''}`)
  await page.getByRole('button', { name: 'Start research' }).click()
  await page.waitForURL(/#\/research\//)
  const rid = page.url().split('/research/')[1].split('/')[0]
  await expect.poll(async () => ((await (await page.request.get(`${server.url}/api/researches/${rid}`)).json()) as ResearchView).runs[0]?.status).toBe('completed')
  await page.getByRole('tab', { name: /^Candidates/ }).click()
  await page.getByRole('button', { name: 'Add candidate' }).click()
  await page.getByLabel('Your sentence').fill('SYNTHETIC bounded scheduling reduces delay under bounded arrivals.')
  await page.locator('.candidates-view').getByRole('button', { name: 'Save', exact: true }).click()
  await expect(candidates(page).getByRole('heading', { name: 'Candidate card' })).toBeVisible()
  const rows: CandidateListItem[] = await (await page.request.get(`${server.url}/api/researches/${rid}/candidates`)).json()
  const f = { rid, cid: rows.find(c => c.current_version === 0)!.id, vid: '' }
  await button(candidates(page), 'Break the claim into testable parts').click()
  await expect.poll(async () => (await card(page, f)).current_version).toBe(1)
  await expect.poll(async () => (await view(page, f)).runs.find(r => r.kind === 'claim_decomposition')?.status).toBe('completed')
  f.vid = (await card(page, f)).current_version_id!
  return f
}
async function startSearch(page: Page, f: Fixture) {
  const plan: CandidatePlan = await (await page.request.get(candidateBase(f) + '/kill-search/plan')).json()
  const response = await page.request.post(candidateBase(f) + '/kill-search', { headers: await headers(page), data: { preview_fingerprint: plan.preview_fingerprint } })
  expect(response.status()).toBe(202)
  return (await response.json()) as Run
}
async function search(page: Page, f: Fixture) {
  const run = await startSearch(page, f)
  await expect.poll(async () => (await view(page, f)).runs.find(r => r.id === run.id)?.status).toBe('completed')
  await expect(button(candidates(page), 'Review with another model')).toBeEnabled()
}
async function openRequest(page: Page) {
  await button(candidates(page), 'Review with another model').click()
  await expect(sheet(page)).toBeVisible()
  await expect(form(page)).toContainText('Candidate · version 1')
}
async function preview(page: Page) {
  await expect(button(form(page), 'Preview')).toBeEnabled()
  await button(form(page), 'Preview').click()
  await expect(button(form(page), 'Start review')).toBeEnabled()
}
async function latest(page: Page, f: Fixture) {
  const rows: ReviewCard[] = await (await page.request.get(`${reviewBase(f)}?target_kind=candidate&target_id=${f.vid}`)).json()
  expect(rows.length).toBeGreaterThan(0)
  return (await (await page.request.get(`${reviewBase(f)}/${rows[0].id}`)).json()) as ReviewDetail
}
async function complete(page: Page, f: Fixture) {
  server.release()
  await expect.poll(async () => (await latest(page, f)).state).toBe('completed')
  await expect(pane(page).locator('[data-finding-kind="partially_supported"]')).toBeVisible()
  return latest(page, f)
}
async function tabTo(page: Page, control: Locator) {
  for (let i = 0; i < 80 && !await control.evaluate(el => el === document.activeElement); i++) await page.keyboard.press('Tab')
  await expect(control).toBeFocused()
}
async function close(page: Page) {
  // Escape in a dismiss form cancels the field; wait until it can close the sheet.
  await expect(sheet(page).locator('.review-dismiss')).toHaveCount(0)
  await expect.poll(() => page.evaluate(() => Boolean(document.activeElement?.closest('.review-dismiss')))).toBe(false)
  await page.keyboard.press('Escape')
  await expect(sheet(page)).toHaveCount(0)
}

test('end to end: finished search, disclosure, held progress, frozen anchor and decisions', async ({ page }) => {
  const f = await fixture(page, true)
  const entry = button(candidates(page), 'Review with another model')
  await expect(entry).toBeDisabled()
  await expect(entry).toHaveAttribute('aria-describedby', /candidate-review-reason/)
  await expect(candidates(page)).toContainText('A review reads a finished search of this version. Run the search first.')
  await search(page, f); await openRequest(page); await preview(page)
  for (const label of ['Elements', 'Sources with matrix rows', 'Passages', 'Characters', 'Cost is not estimated.']) await expect(form(page).getByText(label, { exact: true })).toBeVisible()
  await expect(form(page).locator('.review-connection')).toHaveText('Codex')
  await expect(form(page)).toContainText(/logical steps?/)
  await expect(form(page)).toContainText(/at most \d+ model calls?/)
  await button(form(page), 'Start review').click()
  await expect(pane(page).getByRole('status').filter({ hasText: /Reviewing group 1 of/ })).toBeVisible()
  const detail = await complete(page, f)
  const row = detail.findings.find(r => r.finding.kind === 'partially_supported')!
  const finding = pane(page).locator('[data-finding-kind="partially_supported"]')
  await expect(finding.locator('.review-claim')).toHaveText(row.finding.target.text_at_snapshot!)
  await expect(pane(page).getByRole('heading', { name: /^Element e\d+ ·/ })).toBeVisible()
  await expect(finding).toContainText('Located in the passage')
  await expect(pane(page).locator('[data-finding-kind="assumption_unstated"]')).toContainText('Reviewer inference · no located evidence')
  const passageRequests: string[] = []
  page.on('request', request => { if (/\/passages\//.test(request.url())) passageRequests.push(request.url()) })
  await button(finding, 'Open in source').click()
  const evidence = page.getByRole('dialog', { name: 'Evidence shown to the model' })
  const anchor = row.finding.evidence[0]
  const frozen = detail.snapshot.passages!.find(p => p.passage_id === anchor.passage_id)!
  await expect(evidence.locator('.candidate-passage')).toHaveText(frozen.text)
  await expect(evidence.locator('mark')).toHaveCount(1)
  await expect(evidence.locator('mark')).toHaveText(anchor.anchor_text)
  await page.keyboard.press('Escape'); await expect(evidence).toHaveCount(0)
  expect(passageRequests).toEqual([])
  await button(finding, 'Accept').click()
  await expect(page.locator('.toast').filter({ hasText: 'Recorded. No change was made to the candidate.' })).toBeVisible()
  await expect(finding.locator('.review-current')).toHaveText('Accepted')
  await expect(pane(page).getByRole('button', { name: 'Open in editor with this text' })).toHaveCount(0)
  const whole = pane(page).locator('[data-finding-kind="assumption_unstated"]')
  await button(whole, 'Dismiss').click(); await expect(button(whole, 'Save dismissal')).toBeDisabled()
  await whole.getByLabel('Reason for dismissal').fill('SYNTHETIC owner reason'); await button(whole, 'Save dismissal').click()
  await expect.poll(async () => (await latest(page, f)).open_finding_count).toBe(0)
  await expect(whole.locator('.review-current')).toHaveText('Dismissed: SYNTHETIC owner reason')
  await close(page)
  await expect(candidates(page).getByRole('button', { name: /Reviewed by another model: 1 review, 0 open findings/ })).toBeVisible()
})

test('latest paused search overrides an earlier completed search for the entry', async ({ page }) => {
  const f = await fixture(page); await search(page, f)
  const earlier = (await card(page, f)).searches[0]
  // Freeze a newer search through real store methods, then pause it in the same transaction.
  // A run paused before query freeze has no kill_searches row and cannot test the latest-search rule.
  server.seed(`import json, sys
from pathlib import Path
from deixis.storage import db
from deixis.workflow.store import Store
from deixis.workflow.candidates.store import CandidateStore
c=db.connect(Path(sys.argv[1])); s=Store(c); cs=CandidateStore(s)
with db.transaction(c):
 previous=c.execute('SELECT query_block_json, rendered_queries_json, skipped_terms_json, selection_json FROM kill_searches WHERE id = ? AND candidate_version_id = ? AND outcome = ?', (sys.argv[5], sys.argv[4], 'completed')).fetchone()
 assert previous is not None, 'Earlier completed search is missing'
 r=s.create_run(sys.argv[2],'kill_search',{},None,{'candidate_id':sys.argv[3],'candidate_version_id':sys.argv[4]})
 k=cs.start_kill_search(sys.argv[2],sys.argv[4],r['id'],query_block=json.loads(previous['query_block_json']),rendered_queries=json.loads(previous['rendered_queries_json']),skipped_terms=json.loads(previous['skipped_terms_json']),selection=json.loads(previous['selection_json']))
 s.update_run(r['id'],status='paused')
 cs.set_kill_search_state(k['id'],'paused')
c.close()`, [f.rid, f.cid, f.vid, earlier.id])
  const newer = (await card(page, f)).searches.filter(s => s.candidate_version_id === f.vid).sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id))[0]
  expect(newer.id).not.toBe(earlier.id)
  expect(newer.outcome).toBe('paused')
  await expect.poll(async () => (await view(page, f)).runs.find(r => r.id === newer.run_id)?.status).toBe('paused')
  // The external seed does not trigger UI polling once the research has no active run.
  await button(candidates(page), 'Refresh').click()
  await expect(button(candidates(page), 'Review with another model')).toBeDisabled()
  await expect(candidates(page)).toContainText('The latest search of this version has not finished.')
  const connections: Connections = await (await page.request.get(server.url + '/api/connections')).json()
  const model = connections.models.codex.models![0]
  const response = await page.request.post(reviewBase(f) + '/preview', { headers: await headers(page), data: {
    target_kind: 'candidate', target_id: f.vid, focus: 'source_support', owner_note: null,
    connection: 'codex', model: model.id, reasoning_effort: model.default_reasoning_effort ?? null,
  } })
  expect(response.status()).toBe(422)
  expect((await response.json()).code).toBe('not_reviewable')
  expect((await page.request.post(`${server.url}/api/runs/${newer.run_id}/cancel`, { headers: await headers(page) })).ok()).toBe(true)
})

test('stale version and reviewed-version owner status; earlier version remains readable', async ({ page }) => {
  const f = await fixture(page); await search(page, f); await openRequest(page); await preview(page)
  await button(form(page), 'Start review').click(); const before = await complete(page, f)
  const c = await card(page, f), v = c.versions.find(v => v.id === f.vid)!
  const body: CandidateEdit = { claim_statement: 'SYNTHETIC revised candidate statement.', conditions: v.conditions,
    elements: v.elements.map(e => ({ text: e.text, kind: e.kind })), critical_assumption: v.critical_assumption,
    nearest_simple_explanation: v.nearest_simple_explanation, validation_plan: v.validation_plan, expected_version: 1 }
  expect((await page.request.post(candidateBase(f) + '/versions', { headers: await headers(page), data: body })).ok()).toBe(true)
  await expect(pane(page)).toContainText('The candidate changed after this review:')
  await expect(pane(page)).toContainText('a newer candidate version exists · Version 2')
  expect((await page.request.post(`${candidateBase(f)}/versions/${f.vid}/owner-decision`, { headers: await headers(page), data: { status: 'undecided', reason: 'SYNTHETIC reviewed version decision.' } })).ok()).toBe(true)
  await expect(pane(page)).toContainText('the owner status changed')
  expect((await latest(page, f)).snapshot).toEqual(before.snapshot)
  await expect(pane(page).locator('.review-finding')).toHaveCount(2)
  await close(page)
  await candidates(page).getByText('Earlier versions (1)', { exact: true }).click()
  await candidates(page).locator('details').filter({ has: page.getByText('Earlier versions (1)', { exact: true }) }).getByRole('button', { name: /^Reviewed by another model:/ }).click()
  await expect(sheet(page)).toBeVisible()
  await expect(pane(page).getByRole('button', { name: 'Review with another model' })).toHaveCount(0)
  await expect(pane(page).getByRole('button', { name: 'Accept' }).first()).toBeEnabled()
  await close(page)
  await expect(button(candidates(page), 'Review with another model')).toHaveCount(1)
})

test('held review disables a second prepared request; Turkish title and active-run reason', async ({ page }) => {
  const f = await fixture(page, true); await search(page, f); await openRequest(page); await preview(page)
  const request: ReviewRequest = { target_kind: 'candidate', target_id: f.vid, focus: 'source_support', owner_note: null, connection: 'codex', model: 'acceptance-scripted', reasoning_effort: null }
  // Read the actual selected model from the prepared envelope rather than assuming a selector.
  const connections: Connections = await (await page.request.get(server.url + '/api/connections')).json()
  const selectedModel = connections.models.codex.models?.[0]
  expect(selectedModel).toBeTruthy()
  request.model = selectedModel!.id
  request.reasoning_effort = selectedModel!.default_reasoning_effort ?? null
  const result = await page.request.post(reviewBase(f) + '/preview', { headers: await headers(page), data: request })
  expect(result.ok()).toBe(true)
  const shown: ReviewPreview = await result.json()
  expect((await page.request.post(reviewBase(f), { headers: await headers(page), data: { ...request, snapshot_sha256: shown.snapshot_sha256, preview_fingerprint: shown.preview_fingerprint } })).status()).toBe(202)
  await expect(form(page)).toContainText('Another run is active in this research.')
  await expect(button(form(page), 'Start review')).toBeDisabled()
  await close(page)
  await page.getByRole('button', { name: 'Türkçe' }).click()
  await candidates(page).getByRole('button', { name: /^Başka bir model tarafından incelendi:/ }).click()
  await expect(page.getByRole('dialog', { name: 'Başka bir modelin incelemesi' })).toBeVisible()
  await expect(page.getByRole('dialog', { name: 'Başka bir modelin incelemesi' })).toContainText('Bu araştırmada başka bir işlem sürüyor.')
})

test('request and detail: keyboard, axe, reduced motion, themes and narrow screenshots', async ({ page }) => {
  const f = await fixture(page); await search(page, f)
  const entry = button(candidates(page), 'Review with another model')
  await entry.focus(); await page.keyboard.press('Enter'); await expect(sheet(page)).toBeVisible()
  await tabTo(page, button(form(page), 'Preview')); await page.keyboard.press('Enter')
  await expect(button(form(page), 'Start review')).toBeEnabled()
  await tabTo(page, button(form(page), 'Start review'))
  await close(page); await expect(entry).toBeFocused()
  async function capture(screen: 'request' | 'detail') {
    for (const theme of ['light', 'dark'] as const) for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: width === 1280 ? 900 : 844 })
      const dark = await page.locator('html').evaluate(el => el.classList.contains('dark'))
      if (dark !== (theme === 'dark')) await page.getByRole('button', { name: dark ? 'Use light theme' : 'Use dark theme' }).click()
      if (screen === 'request') { await openRequest(page); await preview(page) }
      else await candidates(page).getByRole('button', { name: /^Reviewed by another model:/ }).click()
      await expect(sheet(page)).toBeVisible()
      const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze()
      expect(axe.violations).toEqual([])
      if (width === 390) expect(await sheet(page).evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
      const chrome = await pane(page).evaluate(el => { const clone = el.cloneNode(true) as HTMLElement; clone.querySelectorAll('[data-stored-text],textarea,input').forEach(n => n.remove()); return clone.textContent ?? '' })
      expect(chrome).not.toMatch(/\b(verified|approved|validated|novel|novelty|score)\b|no prior work/i)
      await page.screenshot({ path: path.join(OUT, `candidate-review-${screen}-${theme}-${width}.png`), fullPage: true, animations: 'disabled' })
      await close(page)
    }
  }
  await capture('request')
  await openRequest(page); await preview(page); await tabTo(page, button(form(page), 'Start review')); await page.keyboard.press('Enter')
  await complete(page, f); await close(page); await expect(entry).toBeFocused()
  await capture('detail')
})
