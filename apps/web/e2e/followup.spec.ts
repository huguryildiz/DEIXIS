import { expect, test, type Locator, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import type { Connections, ResearchSummary, ResearchView, Run, Watch, WatchCheck, WatchItem, WatchPreview } from '../src/api'

// SYNTHETIC records, future dates and the scripted model only. These cases test screen behavior,
// not scientific correctness, coverage or provider recall. Chrome runs outside the writer's sandbox.
const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = process.env.DEIXIS_TEST_PYTHON ?? path.join(REPO, '.venv/bin/python')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })
const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: `${REPO}/backend:${REPO}` }
class FollowUpServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-followup-'))
  readonly url = 'http://127.0.0.1:8838'
  async start() {
    this.proc = spawn(PYTHON, [path.join(REPO, 'tests/acceptance/followup_fixture.py'), '--data-dir', this.dataDir, '--port', '8838'], { cwd: REPO, env, stdio: 'inherit' })
    await expect.poll(async () => {
      if (this.proc?.exitCode !== null) throw new Error('SYNTHETIC follow-up server exited before health')
      try { return (await fetch(`${this.url}/api/health`)).ok } catch { return false }
    }, { timeout: 30_000 }).toBe(true)
  }
  setMode(mode: 'base' | 'new' | 'partial' | 'fail' | 'hold') {
    if (mode === 'hold') {
      rmSync(path.join(this.dataDir, 'followup-release'), { force: true })
      rmSync(path.join(this.dataDir, 'followup-held'), { force: true })
    }
    writeFileSync(path.join(this.dataDir, 'followup-mode'), mode)
  }
  release() { writeFileSync(path.join(this.dataDir, 'followup-release'), 'SYNTHETIC release\n') }
  seed(code: string, args: string[]) {
    const result = spawnSync(PYTHON, ['-c', code, path.join(this.dataDir, 'library.sqlite'), ...args], { cwd: REPO, env, encoding: 'utf8' })
    expect(result.status, result.stderr).toBe(0)
  }
  async stop() {
    if (!this.proc || this.proc.exitCode !== null) return
    const proc = this.proc
    const ended = new Promise<void>(resolve => proc.once('exit', () => resolve()))
    proc.kill('SIGTERM')
    await Promise.race([ended, new Promise<never>((_, reject) => {
      const timer = setTimeout(() => { proc.kill('SIGKILL'); reject(new Error('SYNTHETIC fixture did not stop within 15 s')) }, 15_000)
      ended.then(() => clearTimeout(timer))
    })])
  }
}
const server = new FollowUpServer()
let rid = ''
let queryId = ''
let citingId = ''
let dismissedId = ''
let originalCount = 0
const pageErrors = new WeakMap<Page, Error[]>()
const panel = (page: Page) => page.locator('.followup-view')
const watchSection = (page: Page, wid = queryId) => panel(page).locator(`.followup-watch[data-watch-id="${wid}"]`)
const button = (root: Locator, name: string) => root.getByRole('button', { name, exact: true })
const dialog = (page: Page, schedule = false) => page.getByRole('dialog', { name: schedule ? 'Schedule follow-up' : 'Enable follow-up', exact: true })
const base = () => `${server.url}/api/researches/${rid}`
const readView = async (page: Page): Promise<ResearchView> => (await page.request.get(base())).json()
const watches = async (page: Page): Promise<Watch[]> => (await page.request.get(base() + '/watches')).json()
const items = async (page: Page, status = 'new'): Promise<WatchItem[]> => (await page.request.get(base() + `/watch-items?status=${status}`)).json()
const currentWatch = async (page: Page, id = queryId) => (await watches(page)).find(watch => watch.id === id)!
async function headers(page: Page) {
  await page.request.get(server.url + '/api/session')
  const csrf = (await page.context().cookies(server.url)).find(cookie => cookie.name === 'deixis_csrf')
  expect(csrf).toBeTruthy()
  return { origin: server.url, 'x-deixis-csrf': csrf!.value, 'Idempotency-Key': crypto.randomUUID() }
}
async function openPanel(page: Page) {
  await page.goto(`${server.url}/#/research/${rid}/followup`)
  await expect(panel(page).getByRole('heading', { name: 'Follow-up', exact: true })).toBeVisible()
  await expect(panel(page).getByText('Loading follow-up…', { exact: true })).toHaveCount(0)
}
async function refresh(page: Page) {
  const read = page.waitForResponse(response => response.url() === base() + '/watches' && response.request().method() === 'GET')
  await button(panel(page), 'Refresh').click(); await read
}
async function completed(page: Page, id = queryId, expected: WatchCheck['state'] = 'succeeded') {
  await expect.poll(async () => (await currentWatch(page, id)).last_check?.state, { timeout: 90_000 }).toBe(expected)
  const check = (await currentWatch(page, id)).last_check!
  await expect(watchSection(page, id).locator(`[data-check-id="${check.id}"] .followup-state.is-${expected}`)).toBeVisible()
  await expect(page.locator('.toast', { hasText: 'Follow-up check' })).toHaveCount(0)
  return check
}
async function checkNow(page: Page, mode: 'base' | 'new' | 'partial' | 'fail' | 'hold', id = queryId) {
  server.setMode(mode)
  const previous = (await currentWatch(page, id)).last_check?.id
  await button(watchSection(page, id), 'Check now').click()
  await expect.poll(async () => (await currentWatch(page, id)).last_check?.id).not.toBe(previous)
}
async function counts(page: Page, n: number) {
  await expect(panel(page).getByRole('heading', { name: `New to this research (${n})`, exact: true })).toBeVisible()
  await expect(page.getByRole('tab', { name: /^Follow-up/ }).locator('.research-tab-count')).toHaveText(String(n))
  await expect.poll(async () => {
    const rows: ResearchSummary[] = await (await page.request.get(server.url + '/api/researches')).json()
    return rows.find(row => row.id === rid)?.followup_new
  }).toBe(n)
  const row = page.locator('.recent-row').filter({ has: page.locator(`.recent-open[aria-label*="${(await readView(page)).research.title}"]`) })
  if (n) await expect.poll(async () => row.locator('.followup-sidebar-count').innerText(), { timeout: 15_000 }).toBe(String(n))
  else await expect(row.locator('.followup-sidebar-count')).toBeHidden()
}
async function details(page: Page, id = queryId) {
  const root = watchSection(page, id)
  const disclosure = root.locator('.followup-check > details')
  if (!(await disclosure.evaluate(element => (element as HTMLDetailsElement).open))) await disclosure.getByText('Details', { exact: true }).click()
  return disclosure
}
async function enable(page: Page, kind: Watch['kind']) {
  const label = kind === 'protocol_queries' ? 'Search queries of this research' : 'Works citing the included sources'
  await button(panel(page).locator('.followup-enable-entry').filter({ hasText: label }), 'Follow…').click()
  await expect(dialog(page)).toBeVisible()
  await expect(button(dialog(page), 'Start')).toBeEnabled()
}
async function startEnable(page: Page, kind: Watch['kind']) {
  await button(dialog(page), 'Start').click()
  await expect(dialog(page)).toBeHidden()
  await expect.poll(async () => (await watches(page)).some(watch => watch.enabled && watch.kind === kind)).toBe(true)
  return (await watches(page)).find(watch => watch.enabled && watch.kind === kind)!.id
}
async function pauseHeld(page: Page, id = queryId) {
  await checkNow(page, 'hold', id)
  await expect.poll(async () => (await currentWatch(page, id)).last_check?.state).toBe('running')
  // The page step is started before the held MockTransport request, not before its network answer.
  await expect.poll(async () => {
    const check = (await currentWatch(page, id)).last_check!
    return (await readView(page)).runs.find(run => run.id === check.run_id)?.steps?.some(step => step.kind === 'watch_read' && step.status === 'running')
  }).toBe(true)
  // start_step precedes the host gate and transport; wait until the fixture actually holds the call.
  await expect.poll(() => existsSync(path.join(server.dataDir, 'followup-held')), { timeout: 30_000 }).toBe(true)
  await button(watchSection(page, id), 'Pause').click()
  await expect.poll(async () => (await currentWatch(page, id)).last_check?.state).toBe('pause_requested')
  await expect(watchSection(page, id)).toContainText('Pausing after the current call')
  server.release()
  await expect.poll(async () => (await currentWatch(page, id)).last_check?.state, { timeout: 60_000 }).toBe('paused')
  await expect(button(watchSection(page, id), 'Resume')).toBeVisible()
  await expect(button(watchSection(page, id), 'Cancel')).toBeVisible()
}
const forbidden = /up to date|up-to-date|nothing new|all caught up|güncel durumda|yeni bir şey yok/i
async function copyGuard(root: Locator) {
  const text = await root.evaluate(element => {
    const copy = element.cloneNode(true) as HTMLElement
    copy.querySelectorAll('[data-stored-text]').forEach(node => node.remove())
    return copy.textContent ?? ''
  })
  expect(text).not.toMatch(forbidden)
}
async function tabTo(page: Page, target: Locator) {
  for (let i = 0; i < 140; i++) {
    if (await target.evaluate(element => element === document.activeElement)) {
      const visible = await target.evaluate(element => {
        const css = getComputedStyle(element)
        return (parseFloat(css.outlineWidth) > 0 && css.outlineStyle !== 'none') || css.boxShadow !== 'none'
      })
      expect(visible).toBe(true); return
    }
    await page.keyboard.press('Tab')
  }
  throw new Error('Keyboard did not reach the required follow-up control')
}

test.describe.configure({ mode: 'serial', timeout: 180_000 })
test.beforeAll(async () => server.start())
test.afterAll(async () => server.stop())
test.afterEach(({ page }) => { server.release(); expect(pageErrors.get(page), 'Uncaught page errors').toEqual([]) })
test.beforeEach(async ({ page }) => {
  const errors: Error[] = []; pageErrors.set(page, errors); page.on('pageerror', error => errors.push(error))
  server.setMode('base')
  await page.addInitScript(() => { if (!localStorage.getItem('deixis-ui-language')) localStorage.setItem('deixis-ui-language', 'en'); localStorage.setItem('deixis-theme', 'system') })
  await page.emulateMedia({ colorScheme: 'light', reducedMotion: 'reduce' })
  if (rid) await openPanel(page)
})

test('01 enable manual follow-up and read its bounded first-check facts', async ({ page }) => {
  await page.goto(server.url)
  const connections: Connections = await (await page.request.get(server.url + '/api/connections')).json()
  const models = connections.models.codex.models ?? []
  const model = models.find(model => model.is_default) ?? models[0]
  expect(model).toBeTruthy()
  const response = await page.request.post(server.url + '/api/researches', { headers: await headers(page), data: {
    question: 'SYNTHETIC molecule release scheduling with bisection followup', source_scope: 'academic', effort: 'quick',
    model_connection: 'codex', requested_model: model.id, review_mode: 'off', language_hint: 'en',
  } })
  expect(response.status()).toBe(201)
  const created: ResearchView = await response.json(); rid = created.research.id
  expect(created.scope.providers).toEqual(['openalex']) // The wrapper limits the fixture's configured connections, not watch rows.
  const started = await page.request.post(base() + '/runs', { headers: await headers(page), data: { kind: 'discovery' } })
  expect(started.status()).toBe(202)
  const run: Run = await started.json()
  await expect.poll(async () => (await readView(page)).runs.find(item => item.id === run.id)?.status, { timeout: 90_000 }).toBe('completed')
  const preview: WatchPreview = await (await page.request.post(base() + '/watches/preview', { headers: await headers(page), data: { kind: 'protocol_queries' } })).json()
  expect(preview.units.length).toBeGreaterThan(0)
  expect(preview.units.every(unit => unit.provider_id === 'openalex')).toBe(true)
  await openPanel(page); await enable(page, 'protocol_queries')
  await expect(dialog(page)).toContainText('OpenAlex')
  for (const unit of preview.units) await expect(dialog(page)).toContainText(unit.query_text!)
  await expect(dialog(page).getByRole('radio', { name: 'Manual', exact: true })).toBeChecked()
  await expect(dialog(page)).toContainText('At most 2 pages of 100 records per query, 80 requests and 3000 records per check.')
  queryId = await startEnable(page, 'protocol_queries')
  const check = await completed(page)
  expect(check.config_revision.units.every(unit => unit.baseline && !unit.continuation)).toBe(true)
  await expect(watchSection(page)).toContainText('First check: the records returned within its page budget were recorded and none was announced.')
  await expect(watchSection(page).filter({ hasText: 'No record new to this research in the pages read.' })).toHaveCount(0)
  await expect((await details(page)).filter({ hasText: 'Asked for records since' })).toHaveCount(0)
  await expect(await details(page)).toContainText('First read: no lower date')
  await counts(page, 0)
})

test('02 new records, notices, identity and publication/local dates stay separate', async ({ page, context }) => {
  await checkNow(page, 'new'); const check = await completed(page)
  const found = await items(page)
  const records = found.filter(item => item.kind === 'new_record')
  expect(records).toHaveLength(3); expect(found.filter(item => item.kind === 'notice')).toHaveLength(1)
  expect(check.counts?.new).toBe(3); expect(check.counts?.notices).toBe(1)
  originalCount = records.length
  await counts(page, records.length)
  const dated = records.find(item => item.doi === '10.9999/synthetic.followup.new')!
  const row = panel(page).locator(`[data-item-id="${dated.id}"]`)
  await expect(row).toContainText('Published Oct 3, 2026')
  await expect(row).toContainText('First seen here')
  await expect(row.getByRole('link', { name: 'Open at publisher', exact: true })).toHaveAttribute('href', dated.landing_url!)
  const native = records.find(item => !item.doi)!
  expect(native.identity_uncertain).toBe(true)
  await expect(panel(page).locator(`[data-item-id="${native.id}"]`)).toContainText('Publication date not returned')
  await expect(panel(page)).toContainText('Records without a DOI may be announced again from another provider.')
  const version = records.find(item => item.doi === '10.9999/synthetic.followup.version')!
  expect(version.may_be_version_json.some(relation => relation.relation === 'may_be_version' && relation.against === 'seen')).toBe(true)
  await expect(panel(page).locator(`[data-item-id="${version.id}"]`)).toContainText('May be another version of')
  await panel(page).getByText('Notices (1)', { exact: true }).click()
  await expect(panel(page).locator(`[data-item-id="${found.find(item => item.kind === 'notice')!.id}"]`)).toBeVisible()
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: server.url })
  await button(row, 'Copy DOI').click()
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(dated.doi)
  await expect(page.locator('.toast')).toContainText('DOI copied.')
})

test('03 dismissal records its reason and repeat reads do not reannounce it', async ({ page }) => {
  const dated = (await items(page)).find(item => item.doi === '10.9999/synthetic.followup.new')!
  dismissedId = dated.id
  const row = panel(page).locator(`[data-item-id="${dismissedId}"]`)
  await button(row, 'Dismiss').click(); await row.getByLabel('Reason (optional)').fill('SYNTHETIC outside my followup scope')
  await button(row, 'Confirm').click()
  await expect(row).toHaveCount(0); await counts(page, originalCount - 1)
  await panel(page).getByText('Dismissed', { exact: true }).click()
  await expect(panel(page).locator(`[data-item-id="${dismissedId}"]`)).toContainText('SYNTHETIC outside my followup scope')
  expect((await items(page, 'dismissed')).find(item => item.id === dismissedId)?.dismissed_reason).toBe('SYNTHETIC outside my followup scope')
  await checkNow(page, 'new'); const check = await completed(page)
  expect(check.counts?.new).toBe(0)
  await counts(page, originalCount - 1)
})

test('04 uncertain Check now retries the exact idempotency key and serialized body', async ({ page }) => {
  const previous = (await currentWatch(page)).last_check?.id
  const sent: { key: string | undefined; body: string | null }[] = []
  const route = `**/api/researches/${rid}/watches/${queryId}/checks`
  await page.route(route, async intercepted => {
    sent.push({ key: intercepted.request().headers()['idempotency-key'], body: intercepted.request().postData() })
    if (sent.length === 1) await intercepted.abort('failed'); else await intercepted.continue()
  })
  await button(watchSection(page), 'Check now').click()
  await expect(watchSection(page)).toContainText('The request did not receive an HTTP answer. Retry sends the same command.')
  await button(watchSection(page), 'Retry').click()
  await expect.poll(async () => (await currentWatch(page)).last_check?.id).not.toBe(previous)
  await completed(page)
  expect(sent).toHaveLength(2); expect(sent[0].key).toBeTruthy(); expect(sent[1]).toEqual(sent[0])
  await page.unroute(route)
})

test('05 partial and failed checks show observed coverage and committed counts', async ({ page }) => {
  const boundary = Object.values((await currentWatch(page)).baseline).map(unit => typeof unit === 'number' ? null : unit.success_boundary).filter((date): date is string => Boolean(date))
  expect(boundary.length).toBeGreaterThan(0)
  expect(boundary.every(date => date.slice(0, 10) < '2099-12-30')).toBe(true)
  await checkNow(page, 'partial'); const partial = await completed(page, queryId, 'partial')
  for (const unit of Object.values(partial.observed.units)) {
    expect(unit.oldest_publication_date).toBe('2099-12-30'); expect(unit.exhausted).toBe(false)
    expect(unit.coverage).toBe('coverage_not_reached'); expect(unit.pages_read).toBe(2)
  }
  await expect(watchSection(page).locator('.followup-state')).toContainText('Partial')
  const detail = await details(page)
  await expect(detail).toContainText('not the start of the window')
  await expect(detail).toContainText('The read did not reach the start of the window.')
  await page.screenshot({ path: path.join(OUT, 'followup-partial-details.png'), fullPage: true })
  await checkNow(page, 'fail'); const failed = await completed(page, queryId, 'failed')
  expect(failed.units.length).toBeGreaterThan(0)
  expect(Object.keys(failed.provider_status)).toHaveLength(failed.units.length)
  expect(failed.failure_reason).toBe('no_provider_read'); expect(failed.completed_at).toBeTruthy(); expect(failed.counts).not.toBeNull()
  await expect(watchSection(page).locator('.followup-state.is-failed')).toContainText('No provider read succeeded.')
  await expect(watchSection(page)).toContainText('0 records read in 0 pages')
  await expect(watchSection(page).filter({ hasText: 'First check: the records returned within its page budget were recorded and none was announced.' })).toHaveCount(0)
  await expect(watchSection(page).filter({ hasText: 'No record new to this research in the pages read.' })).toHaveCount(0)
  await expect(watchSection(page).filter({ hasText: 'Counts appear when the check completes.' })).toHaveCount(0)
  await expect(await details(page)).toContainText('No publication date was reached')
  expect(Object.values(failed.observed.units).every(unit => unit.oldest_publication_date === null)).toBe(true)
  for (const status of Object.values(failed.provider_status)) {
    expect(status.provider).toBe('openalex')
    expect(['completed', 'zero_results']).not.toContain(status.status)
    expect(status.status).toBe('failed'); expect(status.error_kind).toBeNull()
  }
  const failedDetails = await details(page)
  await expect(failedDetails).toContainText('OpenAlex')
  await expect(failedDetails.locator('.followup-unit')).toHaveCount(Object.keys(failed.provider_status).length)
  for (const [index, unit] of failed.units.entries()) {
    const rendered = failedDetails.locator('.followup-unit').nth(index)
    await expect(rendered).toContainText(unit.query_text!)
    await expect(rendered).toContainText('Failed · 0 returned · 0 dropped')
  }
})

test('06 Pause requests a checkpoint; Resume completes the same check', async ({ page }) => {
  await pauseHeld(page)
  const paused = await currentWatch(page)
  expect(paused.waiting_reason).toBe('check_paused')
  await expect(button(watchSection(page), 'Check now')).toBeDisabled()
  await expect(watchSection(page).locator('.notice')).toContainText('Resume or cancel this follow-up’s unfinished check first.')
  await button(watchSection(page), 'Resume').click()
  const resumed = await completed(page, queryId, 'partial') // held pages are deliberately non-exhausted and later than the lower boundary
  expect(resumed.id).toBe(paused.last_check!.id)
  expect(resumed.run_id).toBe(paused.last_check!.run_id)
})

test('07 citing works preview shows each cites query and the OpenAlex-id cap', async ({ page }) => {
  const research = await readView(page)
  if (!research.sources.some(source => source.selection.state === 'included')) {
    const source = research.sources.find(source => source.title.includes('bisection')) ?? research.sources[0]
    expect(source, 'The scripted discovery must leave an includable source').toBeTruthy()
    const selected = await page.request.patch(base() + `/selections/${source.source_version_id}`, { headers: await headers(page), data: { state: 'included', expected_version: source.selection.version, reason: 'SYNTHETIC citing seed' } })
    expect(selected.ok()).toBe(true); await refresh(page)
  }
  const response = await page.request.post(base() + '/watches/preview', { headers: await headers(page), data: { kind: 'citing_works' } })
  expect(response.ok()).toBe(true)
  const preview: WatchPreview = await response.json()
  expect(preview.units.some(unit => unit.openalex_id)).toBe(true)
  await enable(page, 'citing_works')
  for (const unit of preview.units.filter(unit => unit.openalex_id)) await expect(dialog(page)).toContainText(unit.query_text!)
  await expect(dialog(page)).toContainText(`at most ${preview.caps.citing_sources} OpenAlex ids are read per check`)
  citingId = await startEnable(page, 'citing_works'); await completed(page, citingId)
})

test('08 interval scheduling requires an explicit catch-up choice', async ({ page }) => {
  await button(watchSection(page), 'Schedule…').click()
  await expect(dialog(page, true)).toContainText('A check already queued or running keeps its settings.')
  await dialog(page, true).getByRole('radio', { name: 'Every 7 days', exact: true }).check()
  await expect(button(dialog(page, true), 'Save')).toBeDisabled()
  await expect(dialog(page, true)).toContainText('Choose Yes or No for catch-up on opening.')
  await expect(dialog(page, true).getByRole('radio', { name: 'Yes', exact: true })).not.toBeChecked()
  await expect(dialog(page, true).getByRole('radio', { name: 'No', exact: true })).not.toBeChecked()
  await dialog(page, true).getByRole('radio', { name: 'Yes', exact: true }).check(); await button(dialog(page, true), 'Save').click()
  await expect(dialog(page, true)).toBeHidden()
  await expect(watchSection(page)).toContainText('Every 7 days · catch-up on opening on')
  await expect(watchSection(page)).toContainText('Next check due')
  await expect(watchSection(page)).toContainText('A due check waits while any run in DEIXIS is queued or running.')
  const saved = await currentWatch(page)
  expect(saved.interval_days).toBe(7); expect(saved.catch_up).toBe(true); expect(saved.next_due_at).toBeTruthy()
})

test('09 a stopped-library missed due time becomes a stored gap after restart', async ({ page }) => {
  await server.stop()
  server.seed(`import sqlite3,sys
from datetime import datetime,timedelta,timezone
with sqlite3.connect(sys.argv[1]) as conn:
 conn.execute("UPDATE watches SET next_due_at=? WHERE id=?", ((datetime.now(timezone.utc)-timedelta(days=15)).isoformat(timespec="milliseconds"),sys.argv[2]))`, [queryId])
  server.setMode('base'); await server.start()
  await expect.poll(async () => (await currentWatch(page)).gaps[0]?.catch_up_queued, { timeout: 90_000 }).toBe(true)
  await refresh(page)
  const watch = await currentWatch(page); const gap = watch.gaps[0]
  expect(gap.catch_up_queued).toBe(true); expect(gap.observed_until).toBeNull()
  const formatted = await page.evaluate(({ from, to }) => {
    const format = (date: string) => new Date(date).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })
    return { from: format(from), to: format(to) }
  }, { from: gap.first_missed_due, to: gap.noticed_at })
  const banner = panel(page).locator('.notice').filter({ has: page.locator(`[data-gap-id="${gap.id}"]`) })
  await expect(banner).toContainText(`Not checked between ${formatted.from} and ${formatted.to}.`)
  await expect(banner).toContainText(`${gap.missed_periods} scheduled checks missed.`)
  await expect(banner).toContainText('One catch-up check was queued.')
  await expect(banner).toContainText('DEIXIS cannot tell whether the computer was closed, asleep or busy before it opened.')
  const check = await completed(page)
  expect(check.trigger).toBe('catch_up'); expect(check.gap?.from).toBe(gap.first_missed_due)
  await expect(watchSection(page)).toContainText('Catch-up check range:')
  await expect(await details(page)).toContainText('Covered back to')
})

test('10 acknowledgement survives tab switching but not a page reload', async ({ page }) => {
  const gap = (await currentWatch(page)).gaps[0]
  await button(panel(page).locator('.notice').filter({ has: page.locator(`[data-gap-id="${gap.id}"]`) }), 'Acknowledge').click()
  await expect(panel(page).locator('.notice [data-gap-id]')).toHaveCount(0)
  await page.getByRole('tab', { name: 'Answer', exact: true }).click(); await page.getByRole('tab', { name: /^Follow-up/ }).click()
  await expect(panel(page).locator('.notice [data-gap-id]')).toHaveCount(0)
  await panel(page).getByText(/^Gaps not checked \(/).click()
  await expect(panel(page).locator(`.followup-gap-row[data-gap-id="${gap.id}"]`)).toContainText('One catch-up check was queued.')
  await page.reload(); await expect(button(panel(page), 'Acknowledge')).toBeVisible()
})

test('11 every stored gap outcome stays readable after an explicit Refresh', async ({ page }) => {
  // SYNTHETIC stored-state rendering only; INSERT retains all parent and immutable-history guards.
  server.seed(`import sqlite3,sys
from datetime import datetime,timedelta,timezone
with sqlite3.connect(sys.argv[1]) as conn:
 watch=conn.execute("SELECT research_id,schedule_version,next_due_at FROM watches WHERE id=?",(sys.argv[2],)).fetchone()
 for i,outcome in enumerate(['catch_up_off','opening_cap','one_per_research','not_eligible','changed_before_record']):
  ts=(datetime.now(timezone.utc)+timedelta(seconds=i)).isoformat(timespec='milliseconds')
  conn.execute("INSERT INTO watch_gaps VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",('SYNTHETIC-gap-'+str(i),sys.argv[2],watch[0],'SYNTHETIC-opening-'+str(i),'2026-01-01T00:00:00+00:00','2026-01-02T00:00:00+00:00',2,None,ts,watch[1],outcome,'check_paused' if outcome=='not_eligible' else None,watch[2],ts))`, [citingId])
  await refresh(page)
  const stored = (await currentWatch(page, citingId)).gaps
  expect(stored).toHaveLength(5)
  await expect(panel(page).locator('.notice [data-gap-id="SYNTHETIC-gap-4"]')).toContainText('The follow-up changed before this gap was recorded.')
  const gapList = panel(page).locator('.followup-gaps').filter({ has: page.locator('[data-gap-id="SYNTHETIC-gap-4"]') }).locator('details')
  await gapList.getByText('Gaps not checked (5)', { exact: true }).click()
  for (const sentence of ['Catch-up on opening is off, so this gap was not checked.', 'Not caught up: at most three researches are caught up each time DEIXIS opens.',
    'Not caught up: one follow-up of each research is caught up when DEIXIS opens, and the other one was chosen.',
    'Not caught up: Resume or cancel this follow-up’s unfinished check first.', 'The follow-up changed before this gap was recorded.']) await expect(gapList).toContainText(sentence)
})

test('12 an earlier-scope follow-up refuses Rebind until discovery freezes a current protocol', async ({ page }) => {
  const research = await readView(page)
  const response = await page.request.post(base() + '/scope', { headers: await headers(page), data: { question: 'SYNTHETIC revised molecule release scheduling with bisection', expected_version: research.research.version } })
  expect(response.ok()).toBe(true)
  await refresh(page)
  await expect(watchSection(page)).toContainText('This follow-up follows an earlier question or protocol.')
  await expect(watchSection(page)).toContainText('The question was revised.')
  await expect(button(watchSection(page), 'Check now')).toBeDisabled()
  await button(watchSection(page), 'Rebind').click()
  const confirmation = page.getByRole('dialog', { name: 'Rebind follow-up?', exact: true })
  await button(confirmation, 'Rebind').click()
  await expect(confirmation).toContainText('Freeze a protocol before following its queries.')
  await button(confirmation, 'Cancel').click()
  const started = await page.request.post(base() + '/runs', { headers: await headers(page), data: { kind: 'discovery' } })
  expect(started.status()).toBe(202); const run: Run = await started.json()
  await expect.poll(async () => (await readView(page)).runs.find(item => item.id === run.id)?.status, { timeout: 90_000 }).toBe('completed')
  await refresh(page)
  const old = queryId
  await button(watchSection(page), 'Rebind').click(); await button(page.getByRole('dialog', { name: 'Rebind follow-up?', exact: true }), 'Rebind').click()
  await expect.poll(async () => (await watches(page)).some(watch => watch.enabled && watch.kind === 'protocol_queries' && watch.id !== old)).toBe(true)
  queryId = (await watches(page)).find(watch => watch.enabled && watch.kind === 'protocol_queries')!.id
  const replacement = await currentWatch(page)
  expect(replacement.scope_revision).toBe((await readView(page)).research.current_scope_revision)
  const protocol = replacement.protocol_record_id; expect(protocol).toBeTruthy()
  // The frozen check must name the replacement's exact current protocol, not the disabled watch's protocol.
  const first = await completed(page)
  expect(first.config_revision.protocol_record_id).toBe(protocol)
  expect((await currentWatch(page, old)).enabled).toBe(false)
  await panel(page).getByText(/^Turned off \(/).click()
  await expect(watchSection(page, old)).toBeVisible()
})

test('13 Turn off preserves items and a disabled watch keeps Cancel for its paused run', async ({ page }) => {
  const before = (await items(page)).map(item => item.id).sort()
  await button(watchSection(page, citingId), 'Turn off').click()
  await button(page.getByRole('dialog', { name: 'Turn off follow-up?', exact: true }), 'Turn off').click()
  await expect.poll(async () => (await currentWatch(page, citingId)).enabled).toBe(false)
  expect((await items(page)).map(item => item.id).sort()).toEqual(before)
  await expect(button(panel(page).locator('.followup-enable-entry').filter({ hasText: 'Works citing the included sources' }), 'Follow…')).toBeVisible()
  // The citing watch follows the old question too. Its replacement is explicitly created under the new scope.
  await enable(page, 'citing_works'); citingId = await startEnable(page, 'citing_works'); await completed(page, citingId)
  await pauseHeld(page, citingId)
  const runId = (await currentWatch(page, citingId)).last_check!.run_id
  await button(watchSection(page, citingId), 'Turn off').click()
  await button(page.getByRole('dialog', { name: 'Turn off follow-up?', exact: true }), 'Turn off').click()
  await panel(page).getByText(/^Turned off \(/).click()
  await expect(button(watchSection(page, citingId), 'Resume')).toHaveCount(0)
  await expect(button(watchSection(page, citingId), 'Cancel')).toBeVisible()
  await button(watchSection(page, citingId), 'Cancel').click()
  await expect.poll(async () => (await readView(page)).runs.find(run => run.id === runId)?.status).toBe('cancelled')
  await expect(watchSection(page, citingId)).toContainText('No counts were recorded for this check.')
  await expect(watchSection(page, citingId).filter({ hasText: 'Counts appear when the check completes.' })).toHaveCount(0)
})

test('14 English and Turkish panel and dialogs keep the coverage limits and copy guard', async ({ page }) => {
  await copyGuard(panel(page))
  await enable(page, 'citing_works'); await copyGuard(dialog(page)); await page.keyboard.press('Escape')
  await button(watchSection(page), 'Schedule…').click(); await copyGuard(dialog(page, true)); await page.keyboard.press('Escape')
  // The single init script supplies a default only; avoid relying on ordering of multiple init scripts.
  await page.evaluate(() => localStorage.setItem('deixis-ui-language', 'tr'))
  await page.reload()
  await expect(panel(page).getByRole('heading', { name: 'Takip', exact: true })).toBeVisible()
  await expect(panel(page)).toContainText('DEIXIS yalnızca çalışırken kontrol yapar.')
  await expect(panel(page)).toContainText('Bir kontrol sınırlı sayıda sayfa okur.')
  await expect(panel(page).getByRole('heading', { name: /^Bu araştırma için yeni \(/ })).toBeVisible()
  await copyGuard(panel(page))
  await panel(page).locator('.followup-enable-entry').getByRole('button', { name: 'Takip et…', exact: true }).click()
  const enableTr = page.getByRole('dialog', { name: 'Takibi aç', exact: true })
  await expect(enableTr).toContainText('DEIXIS yalnızca çalışırken kontrol yapar.'); await copyGuard(enableTr); await page.keyboard.press('Escape')
  await watchSection(page).getByRole('button', { name: 'Zamanlama…', exact: true }).click()
  const scheduleTr = page.getByRole('dialog', { name: 'Takip zamanlaması', exact: true })
  await copyGuard(scheduleTr); await page.keyboard.press('Escape')
})

test('15 desktop/narrow themes, axe, keyboard focus and dialog return focus', async ({ page }) => {
  // Case 12 replaced the watch that owns case 9's real restart gap. This row only exercises
  // rendering/accessibility on the replacement; case 9 remains the scheduler behavior assertion.
  server.seed(`import sqlite3,sys
from datetime import datetime,timezone
with sqlite3.connect(sys.argv[1]) as conn:
 watch=conn.execute("SELECT research_id,schedule_version,next_due_at FROM watches WHERE id=?",(sys.argv[2],)).fetchone()
 ts=datetime.now(timezone.utc).isoformat(timespec='milliseconds')
 conn.execute("INSERT INTO watch_gaps VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",('SYNTHETIC-layout-gap',sys.argv[2],watch[0],'SYNTHETIC-layout-opening','2026-01-01T00:00:00+00:00','2026-01-02T00:00:00+00:00',2,None,ts,watch[1],'opening_cap',None,watch[2],ts))`, [queryId])
  await refresh(page)
  for (const colorScheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' })
    if (colorScheme === 'dark') await expect(page.locator('html')).toHaveClass(/dark/)
    for (const [width, height, size] of [[1280, 900, 'desktop'], [390, 844, 'narrow']] as const) {
      await page.setViewportSize({ width, height })
      const audit = async (selector: string) => {
        const result = await new AxeBuilder({ page }).include(selector).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze()
        expect(result.violations).toEqual([])
      }
      await expect(panel(page)).toContainText('New to this research (')
      await audit('.followup-view')
      await page.screenshot({ path: path.join(OUT, `followup-${size}-${colorScheme}.png`), fullPage: true })
      if (width === 390) {
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
        expect(await panel(page).evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
      }
      // SYNTHETIC stored-value rendering; this does not assert an opening-cap allocation occurred.
      const gap = panel(page).locator('.followup-gaps .notice').first()
      await expect(gap).toContainText('Not checked between')
      await audit('.followup-gaps .notice')
      if (colorScheme === 'light') await page.screenshot({ path: path.join(OUT, `followup-gap-${size}.png`), fullPage: true })
      await enable(page, 'citing_works'); await audit('.followup-dialog')
      if (width === 1280 && colorScheme === 'light') await page.screenshot({ path: path.join(OUT, 'followup-enable-dialog.png'), fullPage: true })
      await page.keyboard.press('Escape')
      await button(watchSection(page), 'Schedule…').click(); await audit('.followup-dialog')
      if (width === 1280 && colorScheme === 'light') await page.screenshot({ path: path.join(OUT, 'followup-schedule-dialog.png'), fullPage: true })
      await page.keyboard.press('Escape')
    }
  }
  await page.setViewportSize({ width: 1280, height: 900 })
  await tabTo(page, button(panel(page).locator('.followup-enable-entry'), 'Follow…'))
  await page.keyboard.press('Enter'); await expect(dialog(page)).toBeVisible()
  await tabTo(page, dialog(page).getByRole('radio', { name: 'Manual', exact: true }))
  await tabTo(page, button(dialog(page), 'Start'))
  await page.keyboard.press('Escape')
  await expect(button(panel(page).locator('.followup-enable-entry'), 'Follow…')).toBeFocused()
  await tabTo(page, button(watchSection(page), 'Check now'))
  await tabTo(page, button(panel(page), 'Acknowledge'))
  await tabTo(page, panel(page).locator('.followup-items').first().getByRole('button', { name: 'Dismiss', exact: true }).first())
  await button(watchSection(page), 'Schedule…').click(); await tabTo(page, button(dialog(page, true), 'Save'))
  await page.keyboard.press('Escape'); await expect(button(watchSection(page), 'Schedule…')).toBeFocused()
})
