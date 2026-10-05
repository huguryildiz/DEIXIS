import { expect, test, type Locator, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import type { EditCheck, ReportClaim, ReportDetail, ResearchView } from '../src/api'
import { nextPort } from './ports'

// Synthetic records, scripted model and mocked OpenAlex only.
const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = process.env.DEIXIS_TEST_PYTHON ?? path.join(REPO, '.venv/bin/python')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

class ReportServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-report-edit-'))
  readonly port = nextPort()
  async start() {
    this.proc = spawn(PYTHON, [path.join(REPO, 'tests/acceptance/fixture_server.py'), '--data-dir', this.dataDir, '--port', String(this.port)], {
      cwd: REPO, env: { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: `${REPO}/backend:${REPO}` }, stdio: 'inherit',
    })
    await expect.poll(async () => {
      if (this.proc?.exitCode !== null) throw new Error('E3 fixture process exited before health was ready')
      try { return (await fetch(`${this.url()}/api/health`)).ok } catch { return false }
    }).toBe(true)
  }
  async stop() {
    if (!this.proc || this.proc.exitCode !== null) return
    const exited = new Promise(resolve => this.proc?.once('exit', resolve))
    this.proc.kill('SIGTERM'); await exited
  }
  url() { return `http://127.0.0.1:${this.port}` }
}
const server = new ReportServer()
test.beforeAll(async () => { await server.start() })
test.afterAll(async () => { await server.stop() })

const sheet = (page: Page) => page.locator('.report-sheet').last()
const panel = (page: Page) => sheet(page).locator('.evidence-report-edit-check')
const meta = (page: Page, key: string) => sheet(page).locator(`[data-claim-key="${key}"]`)
const claimByKey = (report: ReportDetail, key: string) => report.sections.flatMap(s => s.claims).find(c => c.claim_key === key)!
const reading = (page: Page, key: string) => meta(page, key).locator('..').locator('.evidence-report-paragraph').first()
const readingClaim = (page: Page, key: string) => reading(page, key).locator(':scope > span').nth(Number(key.split('.').at(-1)) - 1)
// The app shows one toast at a time and a later toast replaces it, so a transient notice can vanish within a poll gap when an
// unrelated, event-driven toast lands right after it. This records text present at a mutation callback;
// it does not prove how long the toast stayed visible. The init script runs on every navigation.
async function watchToasts(page: Page) {
  await page.addInitScript(() => {
    const seen: string[] = []; (window as unknown as { __toasts: string[] }).__toasts = seen
    let previous: Element | null = null, previousText: string | null = null
    new MutationObserver(() => {
      const toast = document.querySelector('.toast'), text = toast?.textContent ?? null
      if (text && (toast !== previous || text !== previousText)) seen.push(text)
      previous = toast; previousText = text
    })
      .observe(document, { childList: true, subtree: true, characterData: true })
  })
}
const toastCursor = (page: Page) => page.evaluate(() => (window as unknown as { __toasts: string[] }).__toasts.length)
const toastSeen = (page: Page, cursor: number, pattern: RegExp) => expect.poll(async () => (await page.evaluate(() => (window as unknown as { __toasts: string[] }).__toasts)).slice(cursor).some(text => pattern.test(text)), { message: `a toast matching ${pattern} after cursor ${cursor}` }).toBe(true)
const dismissToasts = async (page: Page) => { for (const button of await page.getByRole('button', { name: 'Dismiss notification' }).all()) await button.click().catch(() => {}) }

// Copied workflow, not imported from another spec: an included source and a filled column precede the report.
async function readyResearch(page: Page, question: string) {
  await page.goto(server.url())
  await page.getByLabel('Research question').fill(question)
  await page.getByRole('button', { name: 'Start research' }).click()
  await page.waitForURL(/#\/research\//)
  const rid = page.url().split('/research/')[1].split('/')[0]
  await expect(page.getByText('Ran search & screening')).toBeVisible()
  await page.getByRole('tab', { name: /Sources/ }).click()
  const source = page.locator('.source-row:not(.is-other-version)').filter({ hasText: 'SYNTHETIC molecule release scheduling with bisection' })
  await source.getByRole('button', { name: 'Include' }).click()
  await expect(source.getByRole('button', { name: 'Include' })).toBeDisabled()
  await page.getByRole('tab', { name: /Evidence/ }).click()
  await page.getByRole('button', { name: /Add a column/ }).click()
  const editor = page.getByRole('dialog', { name: 'Add column' })
  await editor.getByLabel('Short name').fill('SYNTHETIC method')
  await editor.getByLabel('Instruction').fill('Record the method named by the source.')
  await editor.getByRole('button', { name: 'Add column' }).click()
  await page.getByRole('button', { name: /^Fill empty cells/ }).click()
  await expect(page.locator('.evidence-toolbar').getByRole('button', { name: 'Write a manuscript draft' })).toBeEnabled({ timeout: 60_000 })
  return rid
}
type Fixture = { rid: string; url: string; headers: Record<string, string>; read: () => Promise<ReportDetail> }
// The token is the cookie's value (double submit). Calling /api/session again would rotate it under the page's cached copy.
async function csrfCookie(page: Page) {
  const cookie = (await page.context().cookies(server.url())).find(item => item.name === 'deixis_csrf')
  expect(cookie, 'the page has loaded its session').toBeTruthy()
  return cookie!.value
}
async function fixture(page: Page): Promise<Fixture> {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await watchToasts(page)
  const rid = await readyResearch(page, 'SYNTHETIC: How are molecule release schedules compared? [report-two-citations]')
  await page.locator('.evidence-toolbar').getByRole('button', { name: 'Write a manuscript draft' }).click()
  await page.getByRole('tab', { name: 'Answer' }).click()
  await expect.poll(async () => {
    const view: ResearchView = await (await page.request.get(`${server.url()}/api/researches/${rid}`)).json()
    return view.runs.find(r => r.kind === 'report')?.status
  }, { timeout: 60_000 }).toBe('completed')
  const summaries: { id: string }[] = await (await page.request.get(`${server.url()}/api/researches/${rid}/reports`)).json()
  const url = `${server.url()}/api/researches/${rid}/reports/${summaries[0].id}`
  const read = async (): Promise<ReportDetail> => (await page.request.get(url)).json()
  const report = await read()
  expect(report.status).toBe('valid')
  const two = report.sections.flatMap(s => s.claims).find(c => c.evidence.length === 2)
  expect(two, 'marker must produce two effective links before the UI uses them').toBeTruthy()
  expect(new Set(two!.evidence.map(e => e.link_id)).size).toBe(2)
  expect(new Set(two!.evidence.map(e => e.source_version_id)).size).toBe(1)
  expect(new Set(two!.evidence.map(e => e.ref_number)).size).toBe(1)
  expect(two!.evidence.filter(e => e.cell_id !== null)).toHaveLength(1)
  expect(two!.evidence.filter(e => e.passage_id !== null)).toHaveLength(1)
  expect(two!.evidence.every(e => e.anchor_match !== null)).toBe(true)
  const csrf_token = await csrfCookie(page)
  await page.getByRole('button', { name: 'Open evidence report' }).click()
  await expect(sheet(page).getByRole('heading', { name: 'III. Background and Taxonomy' })).toBeVisible()
  await dismissToasts(page)
  return { rid, url, read, headers: { origin: server.url(), 'x-deixis-csrf': csrf_token } }
}
async function shotThemes(page: Page, locator: Locator, name: string) {
  for (const scheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme: scheme })
    await locator.scrollIntoViewIfNeeded()
    await page.screenshot({ path: path.join(OUT, `${name}-${scheme}.png`), animations: 'disabled' })
  }
  await page.emulateMedia({ colorScheme: 'light' })
}
async function openEvidence(page: Page) {
  const button = sheet(page).getByRole('button', { name: 'Evidence view', exact: true })
  if (await button.getAttribute('aria-pressed') !== 'true') await button.click()
}
async function openEdit(page: Page, key: string) {
  await openEvidence(page)
  await meta(page, key).getByRole('button', { name: 'Edit', exact: true }).click()
  const form = meta(page, key).locator('.evidence-report-edit')
  await expect(form.getByLabel('Claim text')).toBeFocused()
  return form
}
async function saveText(page: Page, key: string, text: string) {
  const form = await openEdit(page, key)
  await form.getByLabel('Claim text').fill(text)
  const cursor = await toastCursor(page)
  await form.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(form).toHaveCount(0)
  await expect(meta(page, key).getByRole('button', { name: 'Edit', exact: true })).toBeFocused()
  await expect(meta(page, key).getByRole('button', { name: 'Edit', exact: true })).toBeEnabled()
  return cursor
}
async function chromeText(root: Locator) {
  return root.evaluate(el => {
    const copy = el.cloneNode(true) as HTMLElement
    copy.querySelectorAll('[data-stored-text], textarea, input').forEach(node => node.remove())
    return copy.textContent ?? ''
  })
}
async function forbiddenWords(root: Locator) {
  expect(await chromeText(root)).not.toMatch(/\b(verified|validated|confirmed|approved|clean|passed|correct)\b|no problems/i)
}
async function noOverflow(page: Page, ...roots: Locator[]) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  for (const root of roots) expect(await root.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
}
async function reopen(page: Page) {
  await page.keyboard.press('Escape')
  await expect(sheet(page)).toHaveCount(0)
  await page.getByRole('button', { name: 'Open evidence report' }).click()
}
async function captureCheck(page: Page) {
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 })
    for (const dark of [false, true]) {
      await page.keyboard.press('Escape')
      const currentDark = await page.locator('html').evaluate(el => el.classList.contains('dark'))
      if (currentDark !== dark) await page.getByRole('button', { name: dark ? 'Use dark theme' : 'Use light theme' }).click()
      await page.getByRole('button', { name: 'Open evidence report' }).click()
      await panel(page).scrollIntoViewIfNeeded()
      await forbiddenWords(panel(page))
      if (width === 390) await noOverflow(page, panel(page))
      await page.screenshot({ path: path.join(OUT, `report-edit-check-${width === 1440 ? 'desktop' : '390'}${dark ? '-dark' : ''}.png`), animations: 'disabled' })
    }
  }
}

test('edited text check records errors, stays visible when stale and lists skipped rules', async ({ page }) => {
  const f = await fixture(page)
  await saveText(page, 'III.1', 'SYNTHETIC this is a research gap.')
  await expect(panel(page).getByRole('status')).toHaveText('Edited by hand after version 1; edited text was not checked again.')
  const checkButton = panel(page).getByRole('button', { name: 'Check edited text', exact: true })
  await expect(checkButton).toBeEnabled()
  const checkCursor = await toastCursor(page)
  await checkButton.click()
  await expect(panel(page).getByText('Current', { exact: true })).toBeVisible()
  const checked = (await f.read()).edit_check!
  const counts = `${checked.errors} ${checked.errors === 1 ? 'error' : 'errors'}, ${checked.warnings} ${checked.warnings === 1 ? 'warning' : 'warnings'}`
  await expect(panel(page).getByRole('status')).toContainText(counts)
  await toastSeen(page, checkCursor, new RegExp(`^Check recorded: ${counts}\\. Whether the cited evidence supports each sentence was not checked\\.$`))
  const item = panel(page).locator('.evidence-report-check-items li').filter({ hasText: 'banned word' })
  await expect(item).toContainText('Error')
  await expect(item).toContainText('III. Background and Taxonomy')
  await expect(item).not.toContainText('ERROR: ')
  await expect(panel(page).getByRole('button', { name: 'Check again', exact: true })).toBeDisabled()
  await expect(panel(page)).toContainText('This check covers the current text and citations.')
  await forbiddenWords(panel(page))
  await captureCheck(page)
  await saveText(page, 'III.1', 'SYNTHETIC the source states the scheduling method.')
  await expect(panel(page).getByText('Out of date', { exact: true })).toBeVisible()
  await expect(panel(page)).toContainText('This is an earlier check; edits or other inputs changed since.')
  await expect(panel(page).locator('.evidence-report-check-items')).toContainText('banned word')
  await expect(panel(page).getByRole('button', { name: 'Check again', exact: true })).toBeEnabled()
  await panel(page).getByRole('button', { name: 'Check again', exact: true }).click()
  await expect(panel(page)).toContainText('The rules that ran reported no error or warning.')
  await panel(page).locator('summary').filter({ hasText: 'Rules that did not run' }).click()
  await expect(panel(page)).toContainText('III.1 · III. Background and Taxonomy · required phrase frames: edited text: required phrase frames are not checked')
  await expect(panel(page).locator('.evidence-report-fine')).toHaveCount(1)
  await expect(panel(page).locator('.evidence-report-fine')).toHaveText('Not checked: whether the cited evidence supports each sentence, numbers written as words, passages.')
  await expect(panel(page).getByRole('button', { name: 'Check again', exact: true })).toBeDisabled()
  const headers = { origin: f.headers.origin, 'x-deixis-csrf': await csrfCookie(page) }
  const a = await page.request.post(`${f.url}/check-edits`, { headers })
  const b = await page.request.post(`${f.url}/check-edits`, { headers })
  expect(a.status()).toBe(200); expect(b.status()).toBe(200)
  expect((await a.json()).edit_check.id).toBe((await b.json()).edit_check.id)
  await forbiddenWords(panel(page))
})

test('two same-source citations are edited per link, restored with history and omitted from text-only requests', async ({ page }) => {
  const f = await fixture(page), report = await f.read()
  const claim = report.sections.flatMap(s => s.claims).find(c => c.evidence.length === 2)!
  const bodies: Record<string, unknown>[] = []
  page.on('request', req => { if (req.method() === 'PUT' && req.url().startsWith(`${f.url}/claims/`)) bodies.push(req.postDataJSON()) })
  const form = await openEdit(page, claim.claim_key)
  await expect(form.getByRole('checkbox')).toHaveCount(2)
  for (const box of await form.getByRole('checkbox').all()) await expect(box).toBeChecked()
  await expect(form).toContainText('2 of 2 citations kept')
  await expect(form.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()
  await expect(form).toContainText('Change the text or remove a citation to save.')
  await form.getByRole('checkbox').first().uncheck()
  await expect(form).toContainText('Will be removed when you save.')
  await expect(form).toContainText('1 of 2 citations kept')
  await expect(form.getByRole('button', { name: 'Save', exact: true })).toBeEnabled()
  await forbiddenWords(form)
  await shotThemes(page, form, 'report-edit-form-desktop')
  const saveCursor = await toastCursor(page)
  await form.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(form).toHaveCount(0)
  await toastSeen(page, saveCursor, /^Claim saved\. 1 citation removed from this sentence; the edit was not checked\.$/)
  expect(bodies[0]).not.toHaveProperty('text')
  expect(bodies[0].link_ids).toEqual([claim.evidence[1].link_id])
  let current = claimByKey(await f.read(), claim.claim_key)
  expect(current.evidence).toHaveLength(1); expect(current.removed_links).toHaveLength(1)
  await expect(meta(page, claim.claim_key).locator('button[data-link-id]')).toHaveCount(1)
  await expect(readingClaim(page, claim.claim_key).locator('.cite-chip')).toHaveCount(1)
  const history = meta(page, claim.claim_key).locator('.evidence-report-history')
  await history.locator('summary').click()
  await expect(history).toContainText('Citations: from 2 to 1')
  await dismissToasts(page)
  await shotThemes(page, history, 'report-edit-history-desktop')
  await expect(history.locator('li').first().getByRole('button', { name: 'Restore', exact: true })).toBeVisible()
  await forbiddenWords(history)
  const restoreCursor = await toastCursor(page)
  await history.locator('li').first().getByRole('button', { name: 'Restore', exact: true }).click()
  await expect(meta(page, claim.claim_key).getByRole('button', { name: 'Edit', exact: true })).toBeFocused()
  await toastSeen(page, restoreCursor, /^Version restored with its text and citations\.$/)
  current = claimByKey(await f.read(), claim.claim_key)
  expect(current.evidence).toHaveLength(2); expect(current.removed_links).toEqual([])
  await expect(history.locator('li').first().getByRole('button', { name: 'Restore', exact: true })).toHaveCount(0)
  const textCursor = await saveText(page, claim.claim_key, 'SYNTHETIC revised cell statement.')
  expect(bodies.at(-1)).toHaveProperty('text', 'SYNTHETIC revised cell statement.')
  expect(bodies.at(-1)).not.toHaveProperty('link_ids')
  await toastSeen(page, textCursor, /^Claim saved\. The new text was not checked\.$/)
  const combined = await openEdit(page, claim.claim_key)
  await combined.getByLabel('Claim text').fill('SYNTHETIC changed text and evidence.')
  for (const box of await combined.getByRole('checkbox').all()) await box.uncheck()
  await expect(combined).toContainText('No citation will remain on this sentence.')
  const combinedCursor = await toastCursor(page)
  await combined.getByRole('button', { name: 'Save', exact: true }).click()
  await toastSeen(page, combinedCursor, /^Claim saved\. text changed and 2 citations removed from this sentence; the edit was not checked\.$/)
})

test('removing every citation labels owner removals and leaves a never-cited claim distinct', async ({ page }) => {
  const f = await fixture(page)
  expect(claimByKey(await f.read(), 'III.1').evidence).toHaveLength(1)
  const form = await openEdit(page, 'III.1')
  await form.getByRole('checkbox').uncheck()
  await expect(form).toContainText('No citation will remain on this sentence.')
  await forbiddenWords(form)
  await form.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(meta(page, 'III.1')).toContainText('Stated by the source (type as the model wrote it; its citations were removed)')
  await expect(meta(page, 'III.1')).toContainText('No direct citation.')
  await expect(reading(page, 'III.1')).toContainText('(no direct citation)')
  await dismissToasts(page)
  await shotThemes(page, meta(page, 'III.1'), 'report-edit-nocitation-desktop')
  // III.2 shares the paragraph; III.1's span alone no longer has a chip.
  await expect(reading(page, 'III.1').locator(':scope > span').first().locator('.cite-chip')).toHaveCount(0)
  const removed = meta(page, 'III.1').locator('.evidence-report-removed')
  await removed.locator('summary').click()
  const current = claimByKey(await f.read(), 'III.1')
  await expect(removed).toContainText(current.removed_links[0].anchor_text!)
  await expect(removed).toContainText('History can bring them back.')
  await expect(removed.getByRole('button')).toHaveCount(0)
  await expect(reading(page, 'VIII.1')).not.toContainText('(no direct citation)')
  await expect(meta(page, 'VIII.1')).toContainText('No direct citation.')
  await expect(meta(page, 'VIII.1')).not.toContainText('type as the model wrote it')
  await expect(meta(page, 'VIII.1').locator('.evidence-report-removed')).toHaveCount(0)
  const history = meta(page, 'III.1').locator('.evidence-report-history')
  await history.locator('summary').click()
  await forbiddenWords(history)
  await history.locator('li').first().getByRole('button', { name: 'Restore', exact: true }).click()
  await expect(meta(page, 'III.1').getByRole('button', { name: 'Edit', exact: true })).toBeFocused()
  await expect(reading(page, 'III.1').locator(':scope > span').first().locator('.cite-chip')).toHaveCount(1)
  await expect(meta(page, 'III.1')).not.toContainText('type as the model wrote it')
})

async function apiEdit(page: Page, f: Fixture, claim: ReportClaim, body: Record<string, unknown>) {
  const response = await page.request.put(`${f.url}/claims/${claim.id}`, { data: { expected_version: claim.version, ...body }, headers: { ...f.headers, 'Idempotency-Key': crypto.randomUUID() } })
  expect(response.status()).toBe(200)
  const report: ReportDetail = await response.json()
  return report
}
function barrier() {
  let release!: () => void
  const promise = new Promise<void>(resolve => { release = resolve })
  return { promise, release }
}

test('a citation that returns after another write is offered as kept, not as still removed', async ({ page }) => {
  const f = await fixture(page), claim = (await f.read()).sections.flatMap(s => s.claims).find(c => c.evidence.length === 2)!
  const form = await openEdit(page, claim.claim_key)
  await form.getByRole('checkbox').first().uncheck()
  await apiEdit(page, f, claim, { link_ids: [claim.evidence[1].link_id] })
  await expect(form.getByRole('checkbox')).toHaveCount(1)
  await apiEdit(page, f, claimByKey(await f.read(), claim.claim_key), { restore_from: 'model' })
  await expect(form.getByRole('checkbox')).toHaveCount(2)
  for (const box of await form.getByRole('checkbox').all()) await expect(box).toBeChecked()
  await expect(form).toContainText('2 of 2 citations kept')
})

test('the form is locked while a save is in flight, so a later change cannot be lost silently', async ({ page }) => {
  const f = await fixture(page), claim = (await f.read()).sections.flatMap(s => s.claims).find(c => c.evidence.length === 2)!
  const started = barrier(), held = barrier()
  await page.route(`${f.url}/claims/${claim.id}`, async route => {
    if (route.request().method() !== 'PUT') return route.fallback()
    started.release(); await held.promise
    await route.fulfill({ response: await route.fetch() })
  })
  const form = await openEdit(page, claim.claim_key)
  await form.getByRole('checkbox').first().uncheck()
  try {
    await form.getByRole('button', { name: 'Save', exact: true }).click(); await started.promise
    await expect(form.getByLabel('Claim text')).toHaveAttribute('readonly', '')
    await expect(form.getByLabel('Edit note (optional)')).toHaveAttribute('readonly', '')
    const second = form.getByRole('checkbox').nth(1)
    await expect(second).toHaveAttribute('aria-disabled', 'true')
    await second.click({ force: true })  // aria-disabled controls are not clickable for Playwright; the page must still ignore it
    await expect(second).toBeChecked()
  } finally { held.release() }
  await expect(form).toHaveCount(0)
  expect(claimByKey(await f.read(), claim.claim_key).evidence.map(link => link.link_id)).toEqual([claim.evidence[1].link_id])
})

test('conflicting save preserves the typed draft and unchecked intent; keyboard shares the save gate', async ({ page }) => {
  const f = await fixture(page), claim = (await f.read()).sections.flatMap(s => s.claims).find(c => c.evidence.length === 2)!
  const bodies: unknown[] = []
  page.on('request', req => { if (req.method() === 'PUT' && req.url().startsWith(`${f.url}/claims/`)) bodies.push(req.postDataJSON()) })
  const form = await openEdit(page, claim.claim_key)
  await form.getByLabel('Claim text').press('ControlOrMeta+Enter')
  expect(bodies).toHaveLength(0)
  await form.getByLabel('Claim text').fill(' ')
  await expect(form.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()
  await expect(form).toContainText('Write the sentence or cancel.')
  await form.getByLabel('Claim text').press('ControlOrMeta+Enter')
  expect(bodies).toHaveLength(0)
  await form.getByLabel('Claim text').fill('SYNTHETIC draft retained.')
  await form.getByRole('checkbox').first().uncheck()
  await apiEdit(page, f, claim, { text: 'SYNTHETIC another tab wrote this.' })
  const conflictCursor = await toastCursor(page)
  await form.getByRole('button', { name: 'Save', exact: true }).click()
  await toastSeen(page, conflictCursor, /^Not applied:/)
  await expect(form).toHaveAttribute('data-expected-version', String(claim.version + 1))
  await expect(form.getByLabel('Claim text')).toHaveValue('SYNTHETIC draft retained.')
  await expect(form.getByRole('checkbox').first()).not.toBeChecked()
  await expect(form).toContainText('1 of 2 citations kept')
  const delayed = barrier(), started = barrier()
  await page.route(`${f.url}/claims/${claim.id}`, async route => {
    if (route.request().method() !== 'PUT') return route.fallback()
    const response = await route.fetch(); started.release(); await delayed.promise; await route.fulfill({ response })
  })
  await form.getByLabel('Claim text').press('ControlOrMeta+Enter')
  await started.promise
  await expect(form.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()
  await expect(form).toContainText('Saving…')
  const count = bodies.length
  await form.getByLabel('Claim text').press('ControlOrMeta+Enter')
  await page.waitForTimeout(100)
  expect(bodies).toHaveLength(count)
  delayed.release()
  await expect(form).toHaveCount(0)
  await expect(meta(page, claim.claim_key).getByRole('button', { name: 'Edit', exact: true })).toBeFocused()
  const stored = claimByKey(await f.read(), claim.claim_key)
  expect(stored.text).toBe('SYNTHETIC draft retained.'); expect(stored.evidence).toHaveLength(1)
})

function mockCheck(patch: Partial<EditCheck> = {}): EditCheck {
  return { id: 'synthetic-check', created_at: '2026-10-02T09:00:00Z', checker_version: 'edit-check-1', current: true,
    errors: 0, warnings: 0, skipped: 2, edited_claims: 1, items: [], rules_run: ['banned_words', 'counts'],
    skipped_rules: [{ rule: 'phrase_frames', section_id: 'III', claim_key: 'III.1', reason: 'human_text' },
      { rule: 'count_text_not_checked', section_id: 'V', claim_key: 'V.1', reason: 'no_integer_in_text' }],
    not_checked: ['semantic_support', 'numbers_written_as_words', 'passages'], ...patch }
}

test('mocked report views render check boundaries, fallbacks, basis notes, histories and draft edits', async ({ page }) => {
  const f = await fixture(page), base = await f.read()
  let current = structuredClone(base)
  current.has_human_edits = true; current.edited_after_version = 1; current.edit_check = mockCheck()
  await page.route(f.url, route => route.fulfill({ json: current }))
  const show = async () => { await reopen(page); await expect(panel(page)).toBeVisible(); await openEvidence(page) }
  await show()
  await expect(panel(page)).toContainText('The rules that ran reported no error or warning.')
  await panel(page).locator('summary').filter({ hasText: 'Rules that ran' }).click()
  await expect(panel(page)).toContainText('banned words')
  await panel(page).locator('summary').filter({ hasText: 'Rules that did not run' }).click()
  await expect(panel(page)).toContainText('no whole number in the text to compare')
  await forbiddenWords(panel(page))
  current.edit_check = mockCheck({ skipped: 0, skipped_rules: [] })
  await show()
  await expect(panel(page).locator('summary').filter({ hasText: 'Rules that did not run' })).toHaveCount(0)
  await expect(panel(page).locator('summary').filter({ hasText: 'Rules that ran' })).toHaveCount(1)
  await panel(page).locator('summary').filter({ hasText: 'Rules that ran' }).click()
  await expect(panel(page)).toContainText('banned words')
  await expect(panel(page)).toContainText('counts')
  current.edit_check = mockCheck({ current: false, errors: 1, warnings: 1, items: [
    { rule: 'unexpected_rule_code', section_id: 'III', severity: 'error', detail: 'SYNTHETIC unprefixed detail, correct as stored.' },
    { rule: 'math_not_well_formed', section_id: 'V', severity: 'warning', detail: 'WARNING: SYNTHETIC formula detail.' },
  ], skipped_rules: [{ rule: 'unexpected_skip_code', section_id: 'III', claim_key: 'III.1', reason: 'unexpected_reason_code' }], not_checked: ['unknown_not_checked'] })
  await show()
  await expect(panel(page).getByRole('status')).toContainText('does not cover the current inputs')
  await expect(panel(page).getByText('Out of date', { exact: true })).toBeVisible()
  await expect(panel(page)).toContainText('unexpected rule code')
  await expect(panel(page)).toContainText('SYNTHETIC unprefixed detail, correct as stored.')
  await expect(panel(page)).toContainText('malformed math')
  await expect(panel(page)).not.toContainText('WARNING: ')
  await panel(page).locator('summary').filter({ hasText: 'Rules that did not run' }).click()
  await expect(panel(page)).toContainText('unexpected skip code: unexpected reason code')
  await expect(panel(page)).toContainText('Not checked: unknown_not_checked.')
  await forbiddenWords(panel(page))
  current = structuredClone(base); current.has_human_edits = true; current.edited_after_version = null; current.edit_check = mockCheck()
  current.status = 'draft'; current.report_version = null
  const iii = claimByKey(current, 'III.1')
  iii.edited_basis = ['IV.1']
  current.edit_check = null
  await show()
  await expect(panel(page).getByRole('status')).toHaveText('Edited by hand; edited text was not checked again.')
  current.edit_check = mockCheck()
  await show()
  await expect(panel(page).getByRole('status')).toContainText('Edited by hand; the edited text was checked by code rules')
  await expect(panel(page).getByRole('status')).not.toContainText('after version')
  await expect(meta(page, 'III.1')).toContainText('Rests on edited claim IV.1. This sentence was not changed.')
  iii.edited_basis = ['IV.1', 'V.1']; iii.text = 'SYNTHETIC edited dependent text.'; iii.edited = true
  await show()
  await expect(meta(page, 'III.1')).toContainText('Rests on edited claims IV.1, V.1.')
  await expect(meta(page, 'III.1')).not.toContainText('This sentence was not changed.')
  await expect(readingClaim(page, 'III.1')).not.toContainText('Rests on edited')
  iii.text = iii.model_text
  await show()
  await expect(meta(page, 'III.1')).toContainText('This sentence was not changed.')
  iii.evidence = []; iii.evidence_basis = 'none'; iii.support_type_note = null; iii.original_evidence_count = 0; iii.removed_links = []
  await show()
  await expect(readingClaim(page, 'III.1')).not.toContainText('(no direct citation)')
  await expect(meta(page, 'III.1')).toContainText('No direct citation.')
  const form = await openEdit(page, 'III.1')
  await expect(form).toContainText('This sentence has no citations to keep.')
  await expect(form).not.toContainText('History can bring')
  await form.getByRole('button', { name: 'Cancel', exact: true }).click()
  iii.original_evidence_count = 2
  iii.revisions = [
    { id: 'legacy', kind: 'human_edit', restored_from: null, text: 'SYNTHETIC legacy text.', note: 'SYNTHETIC approved note, shown as stored.', created_at: base.created_at, warnings: [], link_count: null, link_ids: null, changes_current: true },
    { id: 'zero', kind: 'human_edit', restored_from: null, text: iii.text, note: null, created_at: base.created_at, warnings: [], link_count: 0, link_ids: [], changes_current: false },
    { id: 'zero-again', kind: 'human_restore', restored_from: 'zero', text: iii.text, note: null, created_at: base.created_at, warnings: [], link_count: 0, link_ids: [], changes_current: false },
  ]
  await show()
  const history = meta(page, 'III.1').locator('.evidence-report-history')
  await history.locator('summary').click()
  await expect(history.locator('li').nth(0)).toContainText('2 citations')
  await expect(history.locator('li').nth(1)).toContainText('2 citations')
  await expect(history.locator('li').nth(2)).toContainText('Citations: from 2 to 0')
  await expect(history.locator('li').nth(3)).toContainText('No citations')
  await expect(history.locator('li').nth(1).getByRole('button', { name: 'Restore', exact: true })).toBeVisible()
  await expect(history.locator('li').nth(2).getByRole('button', { name: 'Restore', exact: true })).toHaveCount(0)
  await forbiddenWords(history)
  current.run = { id: base.run!.id, status: 'running', pause_reason: null }
  await show()
  await expect(panel(page).getByRole('button', { name: 'Check again', exact: true })).toBeDisabled()
  await expect(panel(page)).toContainText('A report can be checked once its run has finished.')
  await expect(meta(page, 'III.1').getByRole('button', { name: 'Edit', exact: true })).toBeDisabled()
  await expect(meta(page, 'III.1')).toContainText('A report can be edited once its run has finished.')
  current.run = base.run; current.has_human_edits = false
  await reopen(page)
  await expect(panel(page)).toHaveCount(0)
})

test('mocked provenance distinguishes complete removal, singular removal, no links and model-base review', async ({ page }) => {
  const f = await fixture(page), base = await f.read()
  let current = structuredClone(base)
  await page.route(f.url, route => route.fulfill({ json: current }))
  const provenance = sheet(page).locator('.evidence-report-provenance')
  const reviewed: ReportDetail['review'] = { status: 'reviewed', step_input_id: 'synthetic', sections_reviewed: ['III'], sections_not_reviewed: [], findings: [], notes: '', reverted: [], not_reverted: [] }
  current.review = reviewed
  await reopen(page)
  await expect(provenance).toContainText("The review covers the model's base version; human edits were not reviewed.")
  const withLinks = current.sections.flatMap(s => s.claims).filter(c => c.evidence.length)
  for (const claim of withLinks) {
    claim.removed_links = claim.evidence.map(link => ({ ...link, source_key: 'SYNTHETIC source' }))
    claim.evidence = []; claim.evidence_basis = 'none'; claim.support_type_note = 'model_written_type'
  }
  await reopen(page)
  await expect(provenance).toContainText('No citation anchors remain after citations were removed by hand.')
  await expect(provenance).toContainText(`${withLinks.length} claims have no direct citations after citations were removed by hand.`)
  for (const claim of withLinks.slice(1)) claim.support_type_note = null
  await reopen(page)
  await expect(provenance).toContainText('1 claim has no direct citation after citations were removed by hand.')
  for (const claim of withLinks) { claim.support_type_note = null; claim.removed_links = []; claim.original_evidence_count = 0 }
  await reopen(page)
  await expect(provenance).toContainText('Anchors were located in the cited passages or cells.')
  await expect(provenance).not.toContainText('after citations were removed by hand')
  current.review = { status: 'not_reviewed', reason: 'nothing_to_review', detail: null, sections_reviewed: [], sections_not_reviewed: [], findings: [], notes: '', reverted: [], not_reverted: [] }
  await reopen(page)
  await expect(provenance).not.toContainText('The review covers')
  current.review = reviewed
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Türkçe', exact: true }).click()
  await page.getByRole('button', { name: 'Kanıt raporunu aç' }).click()
  await expect(provenance).toContainText('İnceleme modelin temel sürümünü kapsar; insan düzenlemeleri incelenmedi.')
})

test('Turkish current check and citation form have translated UI text', async ({ page }) => {
  const f = await fixture(page)
  await saveText(page, 'III.1', 'SYNTHETIC edited sentence.')
  await panel(page).getByRole('button', { name: 'Check edited text', exact: true }).click()
  await expect(panel(page).getByText('Current', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Türkçe', exact: true }).click()
  await page.getByRole('button', { name: 'Kanıt raporunu aç' }).click()
  await expect(panel(page).getByRole('status')).toContainText('1. sürümden sonra elle düzenlendi; düzenlenen metin kod kurallarıyla denetlendi')
  await expect(panel(page).getByRole('status')).toContainText('atıf yapılan kanıtın her cümleyi destekleyip desteklemediği denetlenmedi.')
  await expect(panel(page).getByRole('button', { name: 'Yeniden denetle', exact: true })).toBeDisabled()
  await sheet(page).getByRole('button', { name: 'Kanıt görünümü', exact: true }).click()
  await meta(page, 'III.1').getByRole('button', { name: 'Düzenle', exact: true }).click()
  const form = meta(page, 'III.1').locator('.evidence-report-edit')
  await expect(form.locator('legend')).toHaveText('Tutulacak atıflar')
  await shotThemes(page, panel(page), 'report-edit-turkish-desktop')
  for (const root of [panel(page), form]) expect(await chromeText(root)).not.toMatch(/Check|citation|Error/)
  await form.getByRole('button', { name: 'İptal et', exact: true }).click()
  await expect(meta(page, 'III.1').getByRole('button', { name: 'Düzenle', exact: true })).toBeFocused()
  expect((await f.read()).edit_check!.current).toBe(true)
})

async function bumpEvent(page: Page, f: Fixture) {
  const view: ResearchView = await (await page.request.get(`${server.url()}/api/researches/${f.rid}`)).json()
  const response = await page.request.post(`${server.url()}/api/researches/${f.rid}/title`, {
    data: { title: `SYNTHETIC event ${view.research.version}`, expected_version: view.research.version }, headers: f.headers,
  })
  expect(response.status()).toBe(200)
}
async function responseMarkers(page: Page) {
  await page.evaluate(() => {
    const original = window.fetch.bind(window)
    window.fetch = async (...args) => {
      const response = await original(...args), token = response.headers.get('x-e3-response-barrier')
      if (token) {
        const json = response.json.bind(response)
        response.json = async () => {
          const value = await json()
          requestAnimationFrame(() => requestAnimationFrame(() => { document.documentElement.dataset.e3Processed = token }))
          return value
        }
      }
      return response
    }
  })
}
async function processed(page: Page, token: string) {
  await expect.poll(() => page.locator('html').getAttribute('data-e3-processed')).toBe(token)
}
async function delayedRead(page: Page, f: Fixture, stale: ReportDetail, token: string) {
  const started = barrier(), held = barrier()
  let first = true
  await page.route(f.url, async route => {
    if (!first) return route.fallback()
    first = false; started.release(); await held.promise
    await route.fulfill({ json: stale, headers: { 'x-e3-response-barrier': token } })
  })
  return { started: started.promise, release: held.release }
}

test('GET begun before a PUT completes cannot overwrite the completed mutation', async ({ page }) => {
  const f = await fixture(page), stale = await f.read()
  await responseMarkers(page)
  const form = await openEdit(page, 'III.1')
  await form.getByLabel('Claim text').fill('SYNTHETIC newer mutation text.')
  const old = await delayedRead(page, f, stale, 'old-before-put')
  try {
    await bumpEvent(page, f); await old.started
    await form.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(meta(page, 'III.1')).toContainText('SYNTHETIC newer mutation text.')
    await expect(meta(page, 'III.1').getByRole('button', { name: 'Edit', exact: true })).toBeFocused()
    old.release(); await processed(page, 'old-before-put')
    await expect(readingClaim(page, 'III.1')).toContainText(claimByKey(await f.read(), 'III.1').text)
    await expect(readingClaim(page, 'III.1')).toContainText('SYNTHETIC newer mutation text.')
  } finally { old.release() }
})

test('GET begun during a write is discarded when its stale body arrives after the mutation response', async ({ page }) => {
  const f = await fixture(page), stale = await f.read(), claim = claimByKey(stale, 'III.1')
  await responseMarkers(page)
  const responseHeld = barrier(), putStarted = barrier()
  await page.route(`${f.url}/claims/${claim.id}`, async route => {
    if (route.request().method() !== 'PUT') return route.fallback()
    // Keep the write in flight before forwarding; a read during this interval sees the old state.
    putStarted.release(); await responseHeld.promise
    await route.fulfill({ response: await route.fetch() })
  })
  const form = await openEdit(page, 'III.1')
  await form.getByLabel('Claim text').fill('SYNTHETIC write after read started.')
  await form.getByRole('button', { name: 'Save', exact: true }).click(); await putStarted.promise
  const old = await delayedRead(page, f, stale, 'read-during-put')
  try {
    await bumpEvent(page, f); await old.started
    responseHeld.release()
    await expect(meta(page, 'III.1').getByRole('button', { name: 'Edit', exact: true })).toBeFocused()
    old.release(); await processed(page, 'read-during-put')
    await expect(readingClaim(page, 'III.1')).toContainText('SYNTHETIC write after read started.')
  } finally { responseHeld.release(); old.release() }
})

test('a delayed PUT response converges through the confirming GET after another tab wrote', async ({ page }) => {
  const f = await fixture(page), claim = claimByKey(await f.read(), 'III.1')
  const completed = barrier(), held = barrier()
  await page.route(`${f.url}/claims/${claim.id}`, async route => {
    if (route.request().method() !== 'PUT') return route.fallback()
    const response = await route.fetch(); completed.release(); await held.promise
    await route.fulfill({ response })
  })
  const form = await openEdit(page, 'III.1')
  await form.getByLabel('Claim text').fill('SYNTHETIC this tab wrote first.')
  await form.getByRole('button', { name: 'Save', exact: true }).click()
  try {
    await completed.promise
    const latest = claimByKey(await f.read(), 'III.1')
    await apiEdit(page, f, latest, { text: 'SYNTHETIC another tab wrote later.' })
    await expect(readingClaim(page, 'III.1')).toContainText('SYNTHETIC another tab wrote later.')
    held.release()
    await expect(meta(page, 'III.1').getByRole('button', { name: 'Edit', exact: true })).toBeFocused()
    const serverState = claimByKey(await f.read(), 'III.1')
    await expect(readingClaim(page, 'III.1')).toHaveText(serverState.text + `[${serverState.evidence[0].ref_number}]`)
    expect(serverState.text).toBe('SYNTHETIC another tab wrote later.')
  } finally { held.release() }
})

test('409 recovery is not overwritten by an older GET and keeps the draft version tied to the shown read', async ({ page }) => {
  const f = await fixture(page), stale = await f.read(), claim = claimByKey(stale, 'III.1')
  await responseMarkers(page)
  const form = await openEdit(page, 'III.1')
  await form.getByLabel('Claim text').fill('SYNTHETIC draft after stale read.')
  const old = await delayedRead(page, f, stale, 'old-after-conflict')
  try {
    await bumpEvent(page, f); await old.started
    await apiEdit(page, f, claim, { text: 'SYNTHETIC recovery text.' })
    const conflictCursor = await toastCursor(page)
    await form.getByRole('button', { name: 'Save', exact: true }).click()
    await toastSeen(page, conflictCursor, /^Not applied:/)
    await expect(form).toHaveAttribute('data-expected-version', String(claim.version + 1))
    await expect(readingClaim(page, 'III.1')).toContainText('SYNTHETIC recovery text.')
    old.release(); await processed(page, 'old-after-conflict')
    await expect(readingClaim(page, 'III.1')).toContainText(claimByKey(await f.read(), 'III.1').text)
    await expect(form.getByLabel('Claim text')).toHaveValue('SYNTHETIC draft after stale read.')
    await expect(form).toHaveAttribute('data-expected-version', String(claim.version + 1))
  } finally { old.release() }
})

test('check and acknowledge each discard old reads, confirm outcomes, and reads do not make a GET loop', async ({ page }) => {
  const f = await fixture(page), base = await f.read()
  await responseMarkers(page)
  let current = structuredClone(base), gets = 0, researchGets = 0
  current.has_human_edits = true; current.edited_after_version = 1
  current.sections.find(s => s.section_id === 'III')!.evidence_changes.open = [{ key: 'synthetic-open', kind: 'cell_changed', via: 'citation' }]
  page.on('request', req => { if (req.method() === 'GET' && req.url() === `${server.url()}/api/researches/${f.rid}`) researchGets++ })
  await page.route(f.url, route => { gets++; return route.fulfill({ json: current }) })
  await page.route(`${f.url}/check-edits`, route => {
    current = { ...current, edit_check: mockCheck() }
    return route.fulfill({ json: current })
  })
  await page.route(`${f.url}/sections/III/acknowledge-changes`, route => {
    current.sections.find(s => s.section_id === 'III')!.evidence_changes = { open: [], acknowledged_count: 1, unresolved_refs: 0 }
    return route.fulfill({ json: current })
  })
  await reopen(page); await openEvidence(page)
  await page.waitForTimeout(700)
  for (const action of ['check', 'acknowledge']) {
    const token = `old-${action}`, old = await delayedRead(page, f, structuredClone(current), token)
    try {
      await bumpEvent(page, f); await old.started
      const before = gets
      if (action === 'check') await panel(page).getByRole('button', { name: 'Check edited text', exact: true }).click()
      else await sheet(page).locator('.evidence-report-section').filter({ has: page.getByRole('heading', { name: 'III. Background and Taxonomy', exact: true }) }).getByRole('button', { name: 'Keep as is' }).click()
      await expect.poll(() => gets).toBe(before + 1)
      if (action === 'check') await expect(panel(page).getByText('Current', { exact: true })).toBeVisible()
      else await expect(sheet(page).getByRole('button', { name: 'Keep as is' })).toHaveCount(0)
      old.release(); await processed(page, token)
      if (action === 'check') await expect(panel(page).getByText('Current', { exact: true })).toBeVisible()
      else await expect(sheet(page).getByRole('button', { name: 'Keep as is' })).toHaveCount(0)
      const quietGets = gets, quietResearch = researchGets
      await page.waitForTimeout(1000)
      expect(gets).toBe(quietGets); expect(researchGets).toBe(quietResearch)
    } finally { old.release() }
  }
  // No server event is generated by these mocked failures: the sole read is the confirming GET.
  current.edit_check = null
  await reopen(page)
  for (const status of [409, 500]) {
    await page.route(`${f.url}/check-edits`, route => route.fulfill({ status, json: { detail: 'SYNTHETIC check refusal' } }))
    // Let reads still in flight from the reopen or the previous refusal land first; they are not the confirming GET counted below.
    for (let seen = -1; seen !== gets;) { seen = gets; await page.waitForTimeout(700) }
    const before = gets
    const checkCursor = await toastCursor(page)
    await panel(page).getByRole('button', { name: 'Check edited text', exact: true }).click()
    await expect.poll(() => gets).toBe(before + 1)
    await toastSeen(page, checkCursor, status === 409 ? /^Not applied: SYNTHETIC check refusal/ : /^SYNTHETIC check refusal$/)
    await dismissToasts(page)
    await page.waitForTimeout(1000)
    expect(gets).toBe(before + 1) // the refusal caused exactly the confirming read, no second one
  }
})

test('an isolated 422 form error preserves typed input without a report recovery read', async ({ page }) => {
  const f = await fixture(page), claim = claimByKey(await f.read(), 'III.1')
  await openEvidence(page)
  await page.waitForTimeout(700)
  let gets = 0
  page.on('request', req => { if (req.method() === 'GET' && req.url() === f.url) gets++ })
  await page.route(`${f.url}/claims/${claim.id}`, route => route.fulfill({ status: 422, json: { detail: 'SYNTHETIC text refused' } }))
  const form = await openEdit(page, 'III.1')
  await form.getByLabel('Claim text').fill('SYNTHETIC typed draft stays.')
  const before = gets
  await form.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(form.getByRole('alert')).toHaveText('SYNTHETIC text refused')
  await expect(form.getByLabel('Claim text')).toHaveValue('SYNTHETIC typed draft stays.')
  await page.waitForTimeout(1000)
  expect(gets).toBe(before)
})

async function tabTo(page: Page, target: Locator) {
  for (let i = 0; i < 200; i++) {
    if (await target.evaluate(el => el === document.activeElement)) return
    await page.keyboard.press('Tab')
  }
  throw new Error('The target was not reachable by Tab within the report sheet')
}
test('keyboard editing returns focus and narrow panels, citation forms and histories wrap in both themes', async ({ page }) => {
  const f = await fixture(page)
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const evidence = sheet(page).getByRole('button', { name: 'Evidence view', exact: true })
  await tabTo(page, evidence); await expect(evidence).toBeFocused(); await page.keyboard.press('Enter')
  const edit = meta(page, 'III.1').getByRole('button', { name: 'Edit', exact: true })
  await tabTo(page, edit); await expect(edit).toBeFocused(); await page.keyboard.press('Enter')
  const form = meta(page, 'III.1').locator('.evidence-report-edit')
  const text = form.getByLabel('Claim text')
  await expect(text).toBeFocused(); await text.fill('SYNTHETIC keyboard research gap.')
  const box = form.getByRole('checkbox')
  await tabTo(page, box); await expect(box).toBeFocused()
  await page.keyboard.press('Space'); await expect(box).not.toBeChecked()
  await page.keyboard.press('Space'); await expect(box).toBeChecked()
  await page.keyboard.press('ControlOrMeta+Enter')
  await expect(edit).toBeFocused()
  await expect(edit).toBeEnabled()
  const check = panel(page).getByRole('button', { name: 'Check edited text', exact: true })
  await tabTo(page, check); await expect(check).toBeFocused(); await page.keyboard.press('Enter')
  await expect(panel(page).getByText('Current', { exact: true })).toBeVisible()
  await expect(edit).toBeEnabled()
  await tabTo(page, edit); await page.keyboard.press('Enter')
  await expect(text).toBeFocused(); await page.keyboard.press('Escape'); await expect(edit).toBeFocused()
  await expect(sheet(page)).toBeVisible()
  let current = await f.read()
  const long = 'SYNTHETIC_' + 'x'.repeat(900)
  current.edit_check = mockCheck({ errors: 12, items: Array.from({ length: 12 }, (_, i) => ({ rule: 'banned_word', section_id: 'III', severity: 'error', detail: `ERROR: ${i} ${long}` })) })
  claimByKey(current, 'III.1').evidence[0].anchor_text = long
  await page.route(f.url, route => route.fulfill({ json: current }))
  for (const dark of [false, true]) {
    await page.keyboard.press('Escape')
    const currentDark = await page.locator('html').evaluate(el => el.classList.contains('dark'))
    if (currentDark !== dark) await page.getByRole('button', { name: dark ? 'Use dark theme' : 'Use light theme' }).click()
    await page.setViewportSize({ width: 390, height: 844 })
    await page.getByRole('button', { name: 'Open evidence report' }).click()
    const form = await openEdit(page, 'III.1'), history = meta(page, 'III.1').locator('.evidence-report-history')
    await history.locator('summary').click()
    await expect(form.getByRole('button', { name: 'Show more', exact: true })).toHaveAttribute('aria-expanded', 'false')
    await form.getByRole('button', { name: 'Show more', exact: true }).click()
    await expect(form.getByRole('button', { name: 'Show less', exact: true })).toHaveAttribute('aria-expanded', 'true')
    await expect(form).toContainText(long)
    await noOverflow(page, panel(page), form, history)
    for (const root of [panel(page), form, history]) await forbiddenWords(root)
    await form.scrollIntoViewIfNeeded()
    await page.screenshot({ path: path.join(OUT, `report-edit-form-390${dark ? '-dark' : ''}.png`), animations: 'disabled' })
    await form.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(edit).toBeFocused()
  }
})
