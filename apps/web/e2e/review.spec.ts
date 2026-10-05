import { expect, test, type Locator, type Page, type Route } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import type { Connections, ReportDetail, ResearchView, ReviewCard, ReviewDetail, ReviewPreview, ReviewRequest } from '../src/api'
import { nextPort } from './ports'

// SYNTHETIC records and the scripted model only. No live providers, models or library; own process.
const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = process.env.DEIXIS_TEST_PYTHON ?? path.join(REPO, '.venv/bin/python')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })
class ReviewServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-review-b3-'))
  readonly releaseFile = path.join(this.dataDir, 'review-release')
  readonly port = nextPort()
  readonly url = `http://127.0.0.1:${this.port}`
  async start() {
    this.proc = spawn(PYTHON, [path.join(REPO, 'tests/acceptance/fixture_server.py'), '--data-dir', this.dataDir, '--port', String(this.port)], {
      cwd: REPO, env: { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: `${REPO}/backend:${REPO}` }, stdio: 'inherit',
    })
    await expect.poll(async () => {
      if (this.proc?.exitCode !== null) throw new Error('B3 synthetic fixture exited before health was ready')
      try { return (await fetch(`${this.url}/api/health`)).ok } catch { return false }
    }).toBe(true)
  }
  hold() { rmSync(this.releaseFile, { force: true }) }
  release() { writeFileSync(this.releaseFile, 'SYNTHETIC release\n') }
  async stop() {
    if (!this.proc || this.proc.exitCode !== null) return
    const exited = new Promise(resolve => this.proc?.once('exit', resolve))
    this.proc.kill('SIGTERM'); await exited
  }
}
const server = new ReviewServer()
test.beforeAll(async () => { await server.start() })
test.afterEach(() => { server.release() })
test.afterAll(async () => { await server.stop() })
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('deixis-theme', 'system')
    localStorage.setItem('deixis-ui-language', 'en')
  })
  await page.emulateMedia({ colorScheme: 'light', reducedMotion: 'reduce' })
})

const sheet = (page: Page) => page.locator('.report-sheet').last()
const pane = (page: Page) => sheet(page).locator('.review-pane')
const requestForm = (page: Page) => pane(page).locator('.review-request')
const finding = (page: Page, kind = 'overstated') => pane(page).locator(`[data-finding-kind="${kind}"]`).first()
const button = (root: Locator, name: string) => root.getByRole('button', { name, exact: true })
const view = async (page: Page, rid: string): Promise<ResearchView> => (await page.request.get(`${server.url}/api/researches/${rid}`)).json()
type Target = { rid: string; kind: 'report' | 'answer'; id: string; readReport: () => Promise<ReportDetail> }
const base = (f: Target) => `${server.url}/api/researches/${f.rid}/reviews`
const reviews = async (page: Page, f: Target): Promise<ReviewCard[]> => (await page.request.get(`${base(f)}?target_kind=${f.kind}&target_id=${f.id}`)).json()
const readReview = async (page: Page, f: Target, id: string): Promise<ReviewDetail> => (await page.request.get(`${base(f)}/${id}`)).json()
async function latest(page: Page, f: Target) { return readReview(page, f, (await reviews(page, f))[0].id) }
async function headers(page: Page) {
  // Double submit cookie; do not rotate the page's cached token by calling /api/session again.
  const token = (await page.context().cookies(server.url)).find(c => c.name === 'deixis_csrf')
  expect(token).toBeTruthy()
  return { origin: server.url, 'x-deixis-csrf': token!.value }
}
async function dismissToasts(page: Page) {
  // A modal can hide the portaled toast from the accessibility tree while it is still painted.
  for (const close of await page.getByRole('button', { name: 'Dismiss notification', includeHidden: true }).all()) {
    await close.evaluate(el => (el as HTMLButtonElement).click())
  }
  await expect(page.locator('.toast')).toHaveCount(0)
}
async function includedResearch(page: Page, marker: string) {
  await page.goto(server.url)
  await page.getByLabel('Research question').fill(`SYNTHETIC: How are molecule release schedules compared? [review-finding] ${marker}`)
  await page.getByRole('button', { name: 'Start research' }).click()
  await page.waitForURL(/#\/research\//)
  const rid = page.url().split('/research/')[1].split('/')[0]
  await expect(page.getByText('Ran search & screening')).toBeVisible()
  await page.getByRole('tab', { name: /Sources/ }).click()
  const source = page.locator('.source-row:not(.is-other-version)').filter({ hasText: 'SYNTHETIC molecule release scheduling with bisection' })
  await source.getByRole('button', { name: 'Include' }).click()
  await expect(source.getByRole('button', { name: 'Include' })).toBeDisabled()
  return rid
}
async function reportFixture(page: Page, held = false): Promise<Target> {
  const rid = await includedResearch(page, held ? '[review-hold]' : '')
  await page.getByRole('tab', { name: /Evidence/ }).click()
  await page.getByRole('button', { name: /Add a column/ }).click()
  const editor = page.getByRole('dialog', { name: 'Add column' })
  await editor.getByLabel('Short name').fill('SYNTHETIC method')
  await editor.getByLabel('Instruction').fill('Record the method named by the source.')
  await editor.getByRole('button', { name: 'Add column' }).click()
  await page.getByRole('button', { name: /^Fill empty cells/ }).click()
  await expect(page.locator('.evidence-toolbar').getByRole('button', { name: 'Write a manuscript draft' })).toBeEnabled({ timeout: 60_000 })
  await page.locator('.evidence-toolbar').getByRole('button', { name: 'Write a manuscript draft' }).click()
  await page.getByRole('tab', { name: 'Answer' }).click()
  await expect.poll(async () => (await view(page, rid)).runs.find(r => r.kind === 'report')?.status, { timeout: 60_000 }).toBe('completed')
  const reports: { id: string }[] = await (await page.request.get(`${server.url}/api/researches/${rid}/reports`)).json()
  const id = reports[0].id
  const readReport = async (): Promise<ReportDetail> => (await page.request.get(`${server.url}/api/researches/${rid}/reports/${id}`)).json()
  expect((await readReport()).status).toBe('valid')
  await page.getByRole('button', { name: 'Open evidence report' }).click()
  await expect(sheet(page).getByRole('heading', { name: 'III. Background and Taxonomy' })).toBeVisible()
  await dismissToasts(page)
  return { rid, kind: 'report', id, readReport }
}
async function openReviews(page: Page) {
  const toggle = sheet(page).getByRole('button', { name: /^Reviews/ })
  if (await toggle.getAttribute('aria-pressed') !== 'true') await toggle.click()
  await expect(pane(page).getByRole('heading', { name: 'Review by another model', exact: true })).toBeFocused()
}
async function newRequest(page: Page) {
  await button(pane(page), 'Review with another model').click()
  await expect(requestForm(page)).toBeVisible()
  await expect(requestForm(page).getByRole('button', { name: 'Review model' })).toBeVisible()
}
async function preview(page: Page) {
  await button(requestForm(page), 'Preview').click()
  await expect(requestForm(page).getByRole('heading', { name: 'What will be sent' })).toBeFocused()
  await expect(button(requestForm(page), 'Start review')).toBeEnabled()
}
async function start(page: Page, held = false) {
  if (held) server.hold()
  await button(requestForm(page), 'Start review').click()
  await expect(pane(page).getByRole('heading', { name: 'Additional model review' })).toBeVisible()
}
async function completed(page: Page, f: Target, id?: string) {
  await expect.poll(async () => (id ? await readReview(page, f, id) : await latest(page, f)).state, { timeout: 60_000 }).toMatch(/^(completed|partial)$/)
  await expect(finding(page)).toBeVisible()
  return id ? readReview(page, f, id) : latest(page, f)
}
async function reviewFixture(page: Page) {
  const f = await reportFixture(page)
  await openReviews(page); await newRequest(page); await preview(page); await start(page)
  return { f, review: await completed(page, f) }
}
async function apiRequest(page: Page, f: Target): Promise<ReviewRequest> {
  const connections: Connections = await (await page.request.get(`${server.url}/api/connections`)).json()
  const choices = connections.models.codex.models ?? []
  const choice = choices.find(m => m.is_default) ?? choices[0]
  expect(choice).toBeTruthy()
  return { target_kind: f.kind, target_id: f.id, focus: 'source_support', owner_note: null, connection: 'codex', model: choice.id, reasoning_effort: choice.default_reasoning_effort ?? null }
}
async function apiStart(page: Page, f: Target, held = false) {
  const data = await apiRequest(page, f)
  const p = await page.request.post(`${base(f)}/preview`, { headers: await headers(page), data })
  expect(p.ok()).toBe(true)
  const numbers: ReviewPreview = await p.json()
  if (held) server.hold()
  const response = await page.request.post(base(f), { headers: { ...await headers(page), 'Idempotency-Key': crypto.randomUUID() }, data: { ...data, snapshot_sha256: numbers.snapshot_sha256, preview_fingerprint: numbers.preview_fingerprint } })
  expect(response.status()).toBe(202)
  return response.json() as Promise<{ review: { id: string }; run: { id: string } }>
}
async function refreshByTitleEvent(page: Page, f: Target, title: string) {
  const research = await view(page, f.rid)
  const url = `${server.url}/api/researches/${f.rid}`
  // Unlike finding decisions, rename_research writes an events row, waking the research poller.
  const refreshed = page.waitForResponse(async response => response.url() === url && response.request().method() === 'GET'
    && (await response.json()).last_event_id > research.last_event_id, { timeout: 10_000 })
  const changed = await page.request.post(`${url}/title`, { headers: await headers(page), data: { title, expected_version: research.research.version } })
  expect(changed.ok()).toBe(true)
  await refreshed
  // Let React commit the fetched view before checking requests or the newly rendered state.
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
}
type Captured = { key: string; body: string }
async function loseFirstResponse(page: Page, url: string) {
  const calls: Captured[] = []
  const handler = async (route: Route) => {
    if (route.request().method() !== 'POST') { await route.continue(); return }
    calls.push({ key: route.request().headers()['idempotency-key'], body: route.request().postData()! })
    if (calls.length === 1) {
      const accepted = await route.fetch()
      expect(accepted.ok(), 'server accepted the command before the browser loses its response').toBe(true)
      await route.abort('failed')
    } else await route.continue()
  }
  await page.route(url, handler)
  return { calls, finish: () => page.unroute(url, handler) }
}
async function retry(page: Page, root: Locator, replay: { calls: Captured[] }) {
  await expect(root.getByText('The last request may or may not have been saved.').first()).toBeVisible()
  await button(root, 'Retry').click()
  await expect.poll(() => replay.calls.length).toBe(2)
  expect(replay.calls[1]).toEqual(replay.calls[0])
  expect(replay.calls[0].key).toBeTruthy()
}
async function paneChrome(page: Page) {
  return pane(page).evaluate(el => {
    const copy = el.cloneNode(true) as HTMLElement
    copy.querySelectorAll('[data-stored-text],textarea,input').forEach(n => n.remove())
    return copy.textContent ?? ''
  })
}

test('1 report review: disclosure, held progress, timeline and exact located evidence', async ({ page }) => {
  const f = await reportFixture(page, true)
  await openReviews(page); await newRequest(page)
  await expect(button(requestForm(page), 'Start review')).toBeDisabled()
  await expect(requestForm(page).getByText('Preview the review first.')).toBeVisible()
  await requestForm(page).getByRole('radio', { name: /^Assumptions and consistency:/ }).check()
  await requestForm(page).getByLabel('Note (optional)').fill('SYNTHETIC owner instruction.')
  await preview(page)
  for (const label of ['Claims', 'Passages', 'Characters', 'Cost is not estimated.']) await expect(requestForm(page).getByText(label, { exact: true })).toBeVisible()
  await expect(requestForm(page).locator('.review-connection')).toHaveText('Codex')
  await expect(requestForm(page).getByText(/at most \d+ model calls?/)).toBeVisible()
  await expect(requestForm(page).getByText(/logical steps?/)).toBeVisible()
  await requestForm(page).getByLabel('Note (optional)').fill('SYNTHETIC changed instruction.')
  await expect(button(requestForm(page), 'Start review')).toBeDisabled()
  await preview(page); await start(page, true)
  await expect(pane(page).getByRole('status').filter({ hasText: /Reviewing group 1 of/ })).toBeVisible()
  const running = await latest(page, f)
  await page.keyboard.press('Escape')
  await expect(sheet(page)).toHaveCount(0)
  await expect(page.locator('.chat').getByText('Review by another model', { exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: 'Open evidence report' }).click(); await openReviews(page)
  await expect(pane(page).locator('.review-detail')).toHaveAttribute('data-review-id', running.id)
  server.release()
  const review = await completed(page, f, running.id)
  const row = review.findings.find(r => r.finding.kind === 'overstated')!
  await expect(finding(page).locator('.review-claim')).toHaveText(row.finding.target.text_at_snapshot!)
  await expect(finding(page).getByText('Located in the passage', { exact: false }).first()).toBeVisible()
  await expect(finding(page, 'assumption_unstated').getByText('Reviewer inference · no located evidence')).toBeVisible()
  expect(await paneChrome(page)).not.toMatch(/\b(verified|approved|validated)\b|\bscore\b/i)
  await button(finding(page), 'Open in source').first().click()
  const marks = page.locator('.source-sheet mark')
  await expect(marks).toHaveCount(1)
  await expect(marks).toHaveText(row.finding.evidence[0].anchor_text)
})

test('2 decisions: dismissal, history, stale ordinal and identical Start/decision retries', async ({ page }) => {
  const { f, review } = await reviewFixture(page)
  const row = review.findings.find(r => r.finding.kind === 'overstated')!
  const card = finding(page)
  await button(card, 'Dismiss').click()
  await expect(button(card, 'Save dismissal')).toBeDisabled()
  await expect(card.getByText('Give a reason to dismiss this finding.')).toBeVisible()
  await card.getByLabel('Reason for dismissal').fill('SYNTHETIC reason retained.')
  await button(card, 'Save dismissal').click()
  await expect(card.getByText('Dismissed: SYNTHETIC reason retained.', { exact: true })).toBeVisible()
  await button(card, 'Defer').click(); await expect(card.locator('.review-current')).toHaveText('Deferred')
  await card.locator('summary').click()
  await expect(card.locator('.review-history li')).toHaveCount(2)
  await expect(card.locator('.review-history li').nth(0)).toContainText('Dismissed')
  await expect(card.locator('.review-history li').nth(1)).toContainText('Deferred')
  const whole = review.findings.find(r => r.finding.kind === 'assumption_unstated')!
  await expect(finding(page, 'assumption_unstated').locator('.review-current')).toHaveText('Open')
  const apiDecision = await page.request.post(`${base(f)}/${review.id}/findings/${whole.id}/decisions`, {
    headers: { ...await headers(page), 'Idempotency-Key': crypto.randomUUID() }, data: { decision: 'accepted', reason: null, expected_ordinal: 0 },
  })
  expect(apiDecision.ok()).toBe(true)
  await button(finding(page, 'assumption_unstated'), 'Defer').click()
  await expect(page.getByText("The finding's decision changed. Read it again before deciding.").first()).toBeVisible()
  await expect(finding(page, 'assumption_unstated').locator('.review-current')).toHaveText('Accepted')
  const decisionReplay = await loseFirstResponse(page, `${base(f)}/${review.id}/findings/${row.id}/decisions`)
  await button(card, 'Accept').click(); await retry(page, card, decisionReplay)
  await expect.poll(async () => (await readReview(page, f, review.id)).findings.find(r => r.id === row.id)!.decision_history.length).toBe(3)
  await decisionReplay.finish()
  await sheet(page).getByRole('button', { name: /^Reviews/ }).click()
  await expect(sheet(page).locator('.review-target-line')).toContainText('0 open findings')
  await openReviews(page); await newRequest(page); await preview(page)
  const beforeReviews = (await reviews(page, f)).length
  const beforeRuns = (await view(page, f.rid)).runs.filter(r => r.kind === 'review').length
  const startReplay = await loseFirstResponse(page, base(f))
  await button(requestForm(page), 'Start review').click(); await retry(page, requestForm(page), startReplay)
  await expect.poll(async () => (await reviews(page, f)).length).toBe(beforeReviews + 1)
  expect((await view(page, f.rid)).runs.filter(r => r.kind === 'review')).toHaveLength(beforeRuns + 1)
  await startReplay.finish()
})

test('3 apply: checked editor save, dependency recovery and identical retry without another revision', async ({ page }) => {
  const { f, review } = await reviewFixture(page)
  const row = review.findings.find(r => r.finding.kind === 'overstated')!
  const claimId = row.finding.target.record_id!
  const claimUrl = `${server.url}/api/researches/${f.rid}/reports/${f.id}/claims/${claimId}`
  const applyUrl = `${base(f)}/${review.id}/findings/${row.id}/apply`
  let ordinaryPuts = 0
  page.on('request', req => { if (req.method() === 'PUT' && /\/claims\//.test(req.url())) ordinaryPuts++ })
  await button(finding(page), 'Accept').click()
  await expect(button(finding(page), 'Open in editor with this text')).toBeVisible()
  await button(finding(page), 'Open in editor with this text').click()
  let editor = sheet(page).locator('.review-apply-editor')
  await expect(editor.getByLabel('Claim text')).toHaveValue(row.finding.suggested_fix!)
  await expect(editor.getByText('Text at review time', { exact: true })).toBeVisible()
  await expect(editor.locator('.review-editor-context .review-claim').first()).toHaveText(row.finding.target.text_at_snapshot!)
  const sent = page.waitForRequest(req => req.url() === applyUrl && req.method() === 'POST')
  await button(editor, 'Save').click()
  const apply = await sent
  expect(apply.postDataJSON().dependency_fingerprint).toMatch(/^[0-9a-f]{64}$/)
  await expect(editor).toHaveCount(0)
  expect(ordinaryPuts).toBe(0)
  const after = await readReview(page, f, review.id)
  const history = after.findings.find(r => r.id === row.id)!.decision_history
  expect(history.map(d => d.decision)).toEqual(['accepted', 'accepted'])
  expect(history[0].applied_ref).toBeNull()
  expect(history[1].applied_ref).toBeTruthy()
  const meta = sheet(page).locator(`[data-claim-key="${row.finding.target_ref.ref}"]`)
  await meta.locator('.evidence-report-history summary').click()
  await expect(meta.getByText('Your edit', { exact: false }).first()).toBeVisible()
  await openReviews(page)
  await expect(pane(page).getByText('The report changed after this review:')).toBeVisible()
  await expect(pane(page).getByText(new RegExp(`claim edited.*${row.finding.target_ref.ref!.replace('.', '\\.')}`))).toBeVisible()
  await expect(finding(page).getByText('Written against an earlier text')).toBeVisible()
  await finding(page).locator('summary').click()
  await expect(finding(page).getByText('Accepted and saved through the editor', { exact: true })).toBeVisible()
  await expect(finding(page).getByText(history[1].applied_ref!, { exact: false })).toBeVisible()
  await button(finding(page), 'Open in editor with this text').click()
  editor = sheet(page).locator('.review-apply-editor')
  await expect(button(editor, 'Save')).toBeDisabled()
  const draft = 'SYNTHETIC: retained owner draft after concurrent edit.'
  await editor.getByLabel('Claim text').fill(draft)
  const live = (await f.readReport()).sections.flatMap(s => s.claims).find(c => c.id === claimId)!
  const changed = await page.request.put(claimUrl, { headers: await headers(page), data: { text: 'SYNTHETIC: separately edited current text.', expected_version: live.version } })
  expect(changed.ok()).toBe(true)
  await button(editor, 'Save').click()
  await expect(editor.getByText('The claim or its evidence dependencies changed. Reopen the editor before saving.')).toBeVisible()
  await button(editor, 'Reopen with current text').click()
  await expect(editor.getByLabel('Claim text')).toHaveValue(draft)
  await expect(editor.getByText('Current text', { exact: true })).toBeVisible()
  const revisionCount = async () => {
    return (await f.readReport()).sections.flatMap(s => s.claims).find(c => c.id === claimId)!.revisions.length
  }
  const before = await revisionCount()
  const replay = await loseFirstResponse(page, applyUrl)
  await button(editor, 'Save').click(); await retry(page, editor, replay)
  await expect(editor).toHaveCount(0)
  expect(await revisionCount()).toBe(before + 1)
  await replay.finish()
  expect(ordinaryPuts, 'only apply, never the ordinary editor PUT, came from this page').toBe(0)
})

test('4 source-linked answer review records acceptance without an editor', async ({ page }) => {
  const rid = await includedResearch(page, '')
  await page.getByRole('tab', { name: 'Answer' }).click()
  await page.getByRole('button', { name: 'Generate answer now' }).click()
  await expect(page.getByText('Ran answer generation')).toBeVisible({ timeout: 60_000 })
  const research = await view(page, rid)
  const answer = research.answers[0]
  expect(answer.claims.some(c => c.evidence.length > 0)).toBe(true)
  const f: Target = { rid, kind: 'answer', id: answer.id, readReport: async () => { throw new Error('answer has no report editor') } }
  await page.getByRole('button', { name: /Open report:/ }).click()
  await openReviews(page); await newRequest(page); await preview(page); await start(page)
  await completed(page, f)
  await button(finding(page), 'Accept').click()
  await expect(page.getByText('Recorded. No change was made to the answer.')).toBeVisible()
  await expect(button(finding(page), 'Open in editor with this text')).toHaveCount(0)
  await page.keyboard.press('Escape')
  const line = page.locator('.review-target-line').filter({ hasText: 'Reviewed by another model:' })
  await expect(line).toBeVisible()
  await line.click(); await expect(pane(page)).toBeVisible()
})

test('5 active-run and nothing-reviewable refusals retain their codes and rows in English and Turkish', async ({ page }) => {
  test.setTimeout(240_000)
  const f = await reportFixture(page, true)
  await openReviews(page); await newRequest(page); await preview(page); await start(page, true)
  await expect(pane(page).getByRole('status').filter({ hasText: /Reviewing group/ })).toBeVisible()
  const first = await latest(page, f)
  await newRequest(page)
  await button(requestForm(page), 'Preview').click()
  await expect(requestForm(page).getByText('Another run is active in this research.')).toBeVisible()
  await expect(button(requestForm(page), 'Start review')).toBeDisabled()
  server.release()
  await expect.poll(async () => (await readReview(page, f, first.id)).state, { timeout: 60_000 }).toMatch(/^(completed|partial)$/)
  for (const language of ['en', 'tr'] as const) {
    await page.keyboard.press('Escape')
    if (language === 'tr') await page.getByRole('button', { name: 'Türkçe' }).click()
    await page.getByRole('button', { name: language === 'en' ? 'Open evidence report' : 'Kanıt raporunu aç' }).click()
    await sheet(page).getByRole('button', { name: language === 'en' ? /^Reviews/ : /^İncelemeler/ }).click()
    await button(pane(page), language === 'en' ? 'Review with another model' : 'Başka bir modelle incele').click()
    await button(requestForm(page), language === 'en' ? 'Preview' : 'Önizleme').click()
    await expect(button(requestForm(page), language === 'en' ? 'Start review' : 'İncelemeyi başlat')).toBeEnabled()
    const frozen = await view(page, f.rid)
    const url = `${server.url}/api/researches/${f.rid}`
    await page.route(url, route => route.request().method() === 'GET' ? route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(frozen) }) : route.continue())
    const held = await apiStart(page, f, true)
    await button(requestForm(page), language === 'en' ? 'Start review' : 'İncelemeyi başlat').click()
    await expect(requestForm(page).getByText(language === 'en' ? 'This research has an active run. Wait for it to stop before starting a review.' : 'Bu araştırmada etkin bir işlem var. İncelemeyi başlatmadan önce işlemin durmasını bekleyin.')).toBeVisible()
    server.release()
    await expect.poll(async () => (await readReview(page, f, held.review.id)).state, { timeout: 60_000 }).toMatch(/^(completed|partial)$/)
    await page.unroute(url)
    // SYNTHETIC 422, exactly B2's envelope. Fixture claims are too short to trigger this bound themselves.
    const omitted = { detail: 'No claim fits the review input bounds.', code: 'nothing_reviewable', not_reviewed: [{ claim_ref: 'III.1', section_ref: 'III', reason: 'claim_text_too_long', request_chars: 130_000 }] }
    await page.route(`${base(f)}/preview`, route => route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify(omitted) }), { times: 1 })
    await button(requestForm(page), language === 'en' ? 'Preview' : 'Önizleme').click()
    await expect(requestForm(page).getByText(language === 'en' ? omitted.detail : 'Hiçbir iddia inceleme girdisinin sınırlarına sığmıyor.')).toBeVisible()
    await expect(requestForm(page).getByText(language === 'en' ? /claim text is too long/ : /iddia metni çok uzun/)).toBeVisible()
    await expect(requestForm(page).locator('.review-coverage')).toContainText('III.1')
    await page.keyboard.press('Escape')
    await page.reload()
    // beforeEach's init script is intentionally English; restore the actual UI preference for the next round.
    if (language === 'tr') await page.getByRole('button', { name: 'Türkçe' }).click()
    await page.getByRole('button', { name: language === 'en' ? 'Open evidence report' : 'Kanıt raporunu aç' }).click()
  }
})

async function tabTo(page: Page, target: Locator, backwards = false) {
  for (let i = 0; i < 70; i++) {
    if (await target.evaluate(el => el === document.activeElement)) return
    await page.keyboard.press(backwards ? 'Shift+Tab' : 'Tab')
  }
  await expect(target).toBeFocused()
}
async function look(page: Page, screen: 'request' | 'detail' | 'editor', root: Locator) {
  for (const width of [1280, 390]) for (const theme of ['light', 'dark'] as const) {
    await page.setViewportSize({ width, height: width === 1280 ? 900 : 844 })
    await page.emulateMedia({ colorScheme: theme, reducedMotion: 'reduce' })
    await expect.poll(async () => page.locator('html').evaluate(el => el.classList.contains('dark'))).toBe(theme === 'dark')
    await dismissToasts(page)
    await root.evaluate(el => el.scrollIntoView({ block: 'start', behavior: 'instant' }))
    if (screen === 'detail') {
      const heading = await root.getByRole('heading', { name: 'Additional model review', exact: true }).boundingBox()
      const state = await root.locator('header > [role="status"]').boundingBox()
      const coverage = await root.getByText(/^Not reviewed \(/).boundingBox()
      expect(heading).not.toBeNull(); expect(state).not.toBeNull(); expect(coverage).not.toBeNull()
      expect(heading!.width, `detail heading width at ${width}`).toBeGreaterThan(200)
      expect(heading!.y + heading!.height, 'heading is above the state line').toBeLessThanOrEqual(state!.y)
      expect(state!.y + state!.height, 'state is above Not reviewed').toBeLessThanOrEqual(coverage!.y)
      const group = root.getByRole('heading', { name: 'Claims sent in group 1 of 1', exact: true }).locator('..')
      await expect(group.locator('.review-group-refs')).toContainText('III.1 · III. Background and Taxonomy')
      await expect(group.locator('.review-group-refs')).toHaveCSS('font-size', '13px')
      await expect(group.locator('.review-group-refs')).toHaveCSS('font-weight', '400')
    }
    const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze()
    expect(result.violations, `${screen} ${theme} ${width}`).toEqual([])
    if (width === 390) {
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
      expect(await root.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
    }
    await dismissToasts(page)
    await page.screenshot({ path: path.join(OUT, `review-${screen}-${theme}-${width}.png`), fullPage: false, animations: 'disabled' })
  }
}
test('6 request, findings and apply editor: twelve theme/viewport scans and keyboard operation', async ({ page }) => {
  test.setTimeout(300_000)
  const f = await reportFixture(page)
  const toggle = sheet(page).getByRole('button', { name: /^Reviews/ })
  await tabTo(page, toggle); await page.keyboard.press('Space')
  await expect(pane(page).getByRole('heading', { name: 'Review by another model', exact: true })).toBeFocused()
  await tabTo(page, toggle, true); await page.keyboard.press('Enter')
  await expect(toggle).toBeFocused()
  await page.keyboard.press('Space')
  const entry = button(pane(page), 'Review with another model')
  await tabTo(page, entry); await page.keyboard.press('Enter')
  const radio = requestForm(page).getByRole('radio', { name: /^Source support:/ })
  await tabTo(page, radio); await page.keyboard.press('Space')
  const model = requestForm(page).getByRole('button', { name: 'Review model' })
  await expect(model).toHaveCSS('min-height', '38px')
  await expect(model).toHaveCSS('border-top-width', '1px')
  await expect(model.locator('.model-role-name')).toBeHidden()
  await tabTo(page, model); await page.keyboard.press('Enter')
  await expect(page.getByRole('option').first()).toBeVisible()
  await page.keyboard.press('Enter')
  const previewButton = button(requestForm(page), 'Preview')
  await tabTo(page, previewButton); await page.keyboard.press('Enter')
  await expect(requestForm(page).getByRole('heading', { name: 'What will be sent' })).toBeFocused()
  await expect(button(requestForm(page), 'Start review')).toBeEnabled()
  await look(page, 'request', requestForm(page))
  await tabTo(page, button(requestForm(page), 'Start review')); await page.keyboard.press('Enter')
  await completed(page, f)
  await button(finding(page), 'Dismiss').click()
  await finding(page).getByLabel('Reason for dismissal').press('Escape')
  await expect(pane(page)).toBeVisible()
  await expect(finding(page).getByLabel('Reason for dismissal')).toHaveCount(0)
  await look(page, 'detail', pane(page).locator('.review-detail'))
  await button(finding(page), 'Accept').click()
  await button(finding(page), 'Open in editor with this text').click()
  const editor = sheet(page).locator('.review-apply-editor')
  await expect(editor.getByLabel('Claim text')).toBeFocused()
  await look(page, 'editor', editor)
})

test('7 transcript uses derived review state and does not relist a found run on research events', async ({ page }) => {
  test.setTimeout(90_000)
  const check = expect.configure({ timeout: 10_000 })
  const f = await reportFixture(page)
  await page.keyboard.press('Escape')
  let listCalls = 0
  await page.route(`${base(f)}?*`, async route => {
    listCalls++
    const response = await route.fetch()
    const cards: ReviewCard[] = await response.json()
    // SYNTHETIC derived partial state despite the completed run status.
    await route.fulfill({ response, json: cards.map(card => ({ ...card, state: 'partial' })) })
  })
  let state: ReviewDetail['state'] = 'partial'
  let failure: string | null = null
  await page.route(`${base(f)}/*`, async route => {
    if (route.request().method() !== 'GET') { await route.continue(); return }
    const response = await route.fetch()
    const detail: ReviewDetail = await response.json()
    await route.fulfill({ response, json: { ...detail, state, failure_reason: failure } })
  })
  const opened = await apiStart(page, f)
  await check.poll(async () => (await readReview(page, f, opened.review.id)).state).toBe('completed')
  const heading = page.locator('.chat-toggle').filter({ hasText: 'Review by another model' })
  await check(heading).toContainText('Partial')
  await check(heading).not.toContainText('Completed')
  const research = await view(page, f.rid)
  expect(research.answers).toHaveLength(0) // No answer summary is refreshing this route independently.
  const before = listCalls
  await refreshByTitleEvent(page, f, 'SYNTHETIC: event refresh with unchanged review run')
  await check(heading).toContainText('Partial')
  expect(listCalls).toBe(before)
  // A run-status change refreshes the known review alone and displays its failure reason.
  state = 'failed'; failure = 'nothing_reviewed'
  await page.route(`${server.url}/api/researches/${f.rid}`, async route => {
    const response = await route.fetch()
    const next: ResearchView = await response.json()
    await route.fulfill({ response, json: { ...next, runs: next.runs.map(run => run.id === opened.run.id ? { ...run, status: 'failed' } : run) } })
  })
  await refreshByTitleEvent(page, f, 'SYNTHETIC: event refresh with changed review run status')
  await check(heading).toContainText('Failed · No group was reviewed.')
  expect(listCalls).toBe(before)
})

test('8 report eligibility and missing failure reasons are visible in both languages', async ({ page }) => {
  test.setTimeout(90_000)
  const check = expect.configure({ timeout: 10_000 })
  const { f, review } = await reviewFixture(page)
  await page.keyboard.press('Escape')
  await check(sheet(page)).toHaveCount(0)
  const report = await f.readReport()
  expect(report.run).not.toBeNull()
  let eligibility = { status: report.status, run: report.run }
  const reportUrl = `${server.url}/api/researches/${f.rid}/reports/${f.id}`
  await page.route(reportUrl, route => route.fulfill({ json: { ...report, ...eligibility } }))
  await page.route(`${base(f)}/${review.id}`, async route => {
    const response = await route.fetch()
    const detail = await response.json()
    await route.fulfill({ response, json: { ...detail, state: 'failed', failure_reason: null } })
  })
  for (const language of ['en', 'tr'] as const) {
    if (language === 'tr') await page.getByRole('button', { name: 'Türkçe' }).click()
    const entryName = language === 'en' ? 'Review with another model' : 'Başka bir modelle incele'
    const previewName = language === 'en' ? 'Preview' : 'Önizleme'
    const reason = language === 'en' ? 'A report can be reviewed once its run has finished.' : 'Bir rapor, yazım işlemi bittikten sonra incelenebilir.'
    const openSheet = async () => {
      await page.getByRole('button', { name: language === 'en' ? 'Open evidence report' : 'Kanıt raporunu aç' }).click()
      await check(sheet(page).locator('.review-entry')).toBeVisible()
    }
    const closeSheet = async () => { await page.keyboard.press('Escape'); await check(sheet(page)).toHaveCount(0) }
    const toggle = () => sheet(page).getByRole('button', { name: language === 'en' ? 'Reviews, 1' : 'İncelemeler, 1', exact: true })
    for (const [status, runStatus] of [['in_progress', 'running'], ['valid', 'running'], ['in_progress', 'failed']] as const) {
      const ineligible = { status, run: { ...report.run!, status: runStatus } }
      // The mock is installed before opening; each variant gets a fresh ReportView read.
      eligibility = ineligible
      await openSheet()
      await check(sheet(page).locator('.review-entry')).toBeDisabled()
      await check(sheet(page).locator('.report-document-head').getByText(reason, { exact: true })).toBeVisible()
      await check(toggle().locator('.research-tab-count')).toHaveText('1')
      await toggle().click()
      await check(button(pane(page), entryName)).toBeDisabled()
      await check(pane(page).getByText(reason, { exact: true })).toBeVisible()
      await check(pane(page).locator('.review-detail [role="alert"]')).toContainText(language === 'en' ? 'The run failed.' : 'İşlem başarısız oldu.')
      await closeSheet()

      // A disabled entry cannot open a form. Open while eligible, then change eligibility
      // via a real research event to check the already-open form's Preview guard.
      eligibility = { status: 'valid', run: report.run }
      await openSheet()
      await check(sheet(page).locator('.review-entry')).toBeEnabled()
      await sheet(page).locator('.review-entry').click()
      await check(button(requestForm(page), previewName)).toBeEnabled()
      eligibility = ineligible
      await refreshByTitleEvent(page, f, `SYNTHETIC: ${language} eligibility ${status} ${runStatus}`)
      await check(button(requestForm(page), previewName)).toBeDisabled()
      await check(requestForm(page).getByText(reason, { exact: true })).toBeVisible()
      await check(button(pane(page), entryName)).toBeDisabled()
      await closeSheet()
    }
    eligibility = { status: 'draft', run: report.run }
    await openSheet()
    await check(sheet(page).locator('.review-entry')).toBeEnabled()
    await sheet(page).locator('.review-entry').click()
    await check(button(pane(page), entryName)).toBeEnabled()
    await check(button(requestForm(page), previewName)).toBeEnabled()
    await closeSheet()
  }
})
