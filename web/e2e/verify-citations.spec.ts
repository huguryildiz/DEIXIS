import AxeBuilder from '@axe-core/playwright'
import { expect, request as apiRequest, test, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'
import { chooseTheme } from './panels'

// Verify citations V4: the Library tool's screen against the fixture server's `DEIXIS_FIXTURE_CITATION=on` mode, where
// OpenAlex answers five SYNTHETIC works and the scripted model answers each pair by its sentence. Nothing here calls a
// real model or provider; it shows what the screen does with stored rows, not how well a model checks a citation.
const PORT = nextPort()
const REPO = path.resolve(process.cwd(), '..')
const SERVER_URL = `http://127.0.0.1:${PORT}`
const PYTHON = process.env.DEIXIS_TEST_PYTHON ?? path.join(REPO, '.venv/bin/python')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
const SHOTS = process.env.DEIXIS_VC_SHOTS ? path.resolve(process.env.DEIXIS_VC_SHOTS) : path.join(OUT, 'verify-citations')
mkdirSync(SHOTS, { recursive: true })

// The fixture's draft and bibliography, read from the server file so the two never drift apart.
const FIXTURE = readFileSync(path.join(REPO, 'tests/acceptance/fixture_server.py'), 'utf8')
const BIB = FIXTURE.split('CITATION_BIB = """')[1].split('"""')[0]
const DRAFT = FIXTURE.split('CITATION_DRAFT = (')[1].split(')\n')[0].split('\n').map(line => line.trim().replace(/^"|"$/g, '')).join('').replaceAll('\\\\', '\\')

let proc: ChildProcess | undefined
test.beforeAll(async () => {
  const dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-vc-'))
  proc = spawn(PYTHON, [path.join(REPO, 'tests/acceptance/fixture_server.py'), '--data-dir', dataDir, '--port', String(PORT)],
    { cwd: REPO, env: { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: REPO, DEIXIS_FIXTURE_CITATION: 'on' }, stdio: 'inherit' })
  await expect.poll(async () => { try { return (await fetch(`${SERVER_URL}/api/health`)).ok } catch { return false } }, { timeout: 60_000 }).toBe(true)
})
test.afterAll(async () => {
  if (!proc || proc.exitCode !== null) return
  const ended = new Promise(resolve => proc!.once('exit', resolve))
  proc.kill('SIGTERM'); await ended
})

// A modal sheet makes the sidebar inert, so with one open the theme button is pressed directly.
async function theme(page: Page, value: 'light' | 'dark') {
  if (await page.getByRole('dialog').count() === 0) { await chooseTheme(page, value); return }
  const dark = await page.locator('html').evaluate(el => el.classList.contains('dark'))
  if (dark !== (value === 'dark')) await page.locator(`button[aria-label="${dark ? 'Switch to light mode' : 'Switch to dark mode'}"]`).first().evaluate(el => (el as HTMLElement).click())
}
async function shot(page: Page, name: string) {
  for (const value of ['light', 'dark'] as const) {
    await theme(page, value)
    await page.screenshot({ path: path.join(SHOTS, `${name}-${value}.png`), animations: 'disabled', fullPage: true })
  }
  await theme(page, 'light')
}
const row = (page: Page, pair: number) => page.locator(`.cc-table tr[data-pair="${pair}"]`)

test('a draft and its bibliography go from parse to results, with each count, state and quote from the stored rows', async ({ page }) => {
  test.setTimeout(300_000)
  expect(DRAFT).toContain('\\cite{a}')
  await page.goto(`${SERVER_URL}/#/library`)
  await page.getByRole('button', { name: 'Verify citations' }).first().click()
  await expect(page).toHaveURL(/#\/library\/verify$/)
  await expect(page.getByRole('heading', { name: 'Verify citations', level: 1 })).toBeVisible()
  await expect(page.getByText('No check yet.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Choose draft file' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Choose bibliography file' })).toBeVisible()
  await shot(page, '01-start')

  // Start: pasted text and a BibTeX file. Code reads the markers; nothing is looked up yet.
  await page.getByLabel('Paste the draft').fill(DRAFT)
  await page.getByLabel('Bibliography file').setInputFiles({ name: 'refs.bib', mimeType: 'application/x-bibtex', buffer: Buffer.from(BIB) })
  await expect(page.getByText('refs.bib')).toBeVisible()
  await page.getByRole('button', { name: 'Read the citations' }).click()
  await expect(page).toHaveURL(/#\/library\/verify\/cdr_/)
  const counters = page.locator('.cc-counters')
  await expect(counters.getByRole('region', { name: 'In the draft' })).toContainText('8citations')
  await expect(counters.getByRole('region', { name: 'In the draft' })).toContainText('1not read')
  await expect(page.locator('.cc-table tbody[data-marker="8"]')).toContainText('Marker not read')
  await expect(page.locator('.cc-table tbody[data-marker="8"] .cc-marker')).toHaveText('[ibid]')
  await expect(row(page, 8)).toContainText('No bibliography entry has zz.')
  await expect(row(page, 1)).toContainText('Not looked up yet')
  await expect(row(page, 1)).toContainText('Checked as:')
  await expect(page.locator('.cc-entries li')).toHaveCount(5)
  await expect(page.locator('.cc-step')).toContainText('Step 1 of 4')
  await shot(page, '02-parsed')

  // Look up, then fetch the text: entries carry their link and the text read; e has metadata only.
  await page.getByRole('button', { name: 'Look up entries' }).click()
  await expect(page.locator('.cc-entries li[data-resolution="resolved"]')).toHaveCount(5)
  await expect(page.locator('.cc-entries li[data-entry="a"]')).toContainText('Linked by DOI')
  await page.getByRole('button', { name: 'Get the text' }).click()
  await expect(page.locator('.cc-entries li[data-entry="a"]')).toContainText('Full text from an open-access copy')
  await expect(page.locator('.cc-entries li[data-entry="e"]')).toContainText('Metadata only')
  await shot(page, '03-text')

  // A cited work's PDF still waiting for the equation reader (D105): the view says so and the freeze is not offered.
  // The fixture server has no such reader, so the view's answer is changed here; the page reads the view again every
  // five seconds and offers the freeze once nothing waits.
  const step = page.locator('.cc-step')
  const viewUrl = /\/api\/citation-checks\/cdr_[A-Za-z0-9]+$/
  await page.route(viewUrl, async route => {
    if (route.request().method() !== 'GET') return route.continue()
    const response = await route.fetch()
    await route.fulfill({ response, json: { ...(await response.json()), reextraction_waiting: [{ entry_id: 'cbe_SYNTHETIC', entry_ordinal: 1, asset_id: 'ast_SYNTHETIC', state: 'failed', next_at: '2026-10-18T10:10:00.000+00:00' }] } })
  })
  await page.reload()
  await expect(step).toContainText('Wait for re-extraction: the PDFs of entries 1 are being read again')
  await expect(step).toContainText('The next try is at')
  await expect(page.getByRole('button', { name: 'Wait for re-extraction' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Freeze the plan' })).toHaveCount(0)
  await shot(page, '03b-reextraction')
  await page.unroute(viewUrl)
  await expect(page.getByRole('button', { name: 'Freeze the plan' })).toBeVisible({ timeout: 15_000 })

  // Freeze, then the preview: no literature model in Settings, so the cost is unknown (never 0) and Start waits.
  await page.getByRole('button', { name: 'Freeze the plan' }).click()
  await expect(step).toContainText('Step 4 of 4')
  await expect(step.locator('.cc-facts')).toContainText('Unknown (no model is chosen)')
  await expect(step.locator('.cc-facts')).toContainText('6, in draft order')
  await expect(step.locator('.cc-facts')).toContainText('0 (cap 200)')
  await expect(step).toContainText('No literature model is chosen.')
  await expect(page.getByRole('button', { name: 'Start the check' })).toBeDisabled()
  await expect(counters.getByRole('region', { name: 'Pairs' })).toContainText('6in the plan')
  await expect(counters.getByRole('region', { name: 'Pairs' })).toContainText('–sent to the model')
  await expect(row(page, 7)).toContainText('No text to read')
  await shot(page, '04-preview-no-model')

  // Settings names a model; the preview is read again for it and Start sends that previewed revision and model.
  const api = await apiRequest.newContext({ baseURL: SERVER_URL, extraHTTPHeaders: { origin: SERVER_URL } })
  const csrf = (await (await api.get('/api/session')).json()).csrf_token as string
  expect((await api.put('/api/settings/literature', { headers: { 'x-deixis-csrf': csrf }, data: { model_connection: 'codex', model: 'fixture-model', reasoning_effort: null } })).ok()).toBe(true)
  await page.getByRole('button', { name: 'Preview again' }).click()
  await expect(step.locator('.cc-facts')).toContainText('fixture-model')
  await expect(step.locator('.cc-facts')).toContainText('No cost per call: the model runs on a subscription')
  await expect(step.locator('details.cc-list ol li')).toHaveCount(6)
  await shot(page, '05-preview')

  await page.getByRole('button', { name: 'Start the check' }).click()
  await expect(page.getByText('Checking the citations')).toBeVisible()
  await expect(page.getByRole('progressbar', { name: 'Pairs ended' })).toBeVisible()
  await page.screenshot({ path: path.join(SHOTS, '06-running-light.png'), animations: 'disabled' })
  await expect(step).toContainText('Check finished', { timeout: 60_000 })

  // Results: each result and status in its own column, the counts apart.
  // "What was read" names only what was given, the same way for every row; the result and each quote's origin sit in
  // the Result cell (review round 1, high 2).
  const read = (pair: number) => row(page, pair).locator('.cc-read')
  await expect(row(page, 1).locator('.cc-pill')).toHaveText('Found whole')
  await expect(read(1)).toHaveText('Full text · 5 of 5 passages given')
  await expect(row(page, 1).locator('.cc-origin')).toHaveText('Quote from the PDF text')
  await expect(row(page, 2).locator('.cc-pill')).toHaveText('Found partly')
  await expect(read(2)).toHaveText('Abstract only')
  await expect(row(page, 2).locator('.cc-origin')).toHaveText('Quote from the abstract')
  await expect(row(page, 2).locator('.cc-parts li')).toHaveCount(2)
  await expect(row(page, 2).locator('.cc-parts')).toContainText('halves the energy use.')  // no space before the period
  await expect(row(page, 3).locator('.cc-pill')).toHaveText('Not found in the given passages')
  await expect(read(3)).toHaveText('Abstract only')
  await expect(row(page, 4)).toContainText('Could not be checked')
  await expect(read(4)).toHaveText('Abstract only')
  await expect(row(page, 4).locator('.cc-pill')).toHaveCount(0)
  await expect(page.locator('.cc-table tbody[data-marker="5"] tr')).toHaveCount(2)  // one sub-row per cited work
  // Every passage of work a was given (its abstract and PDF pages), and this quote came from the abstract.
  await expect(read(5)).toHaveText('Full text · 5 of 5 passages given')
  await expect(row(page, 5).locator('.cc-origin')).toHaveText('Quote from the abstract')
  for (const cell of await page.locator('.cc-table .cc-read').allTextContents()) expect(cell).not.toMatch(/found/i)
  const pairs = counters.getByRole('region', { name: 'Pairs' })
  for (const text of ['6sent to the model', '5completed', '3passage found', '2not found in given passages', '1could not be checked']) await expect(pairs).toContainText(text)
  await shot(page, '07-results')
  const scan = await new AxeBuilder({ page }).include('.cc-page').withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze()
  expect(scan.violations.map(v => `${v.id}: ${v.nodes.length}`)).toEqual([])

  // A located quote opens Source details on that passage with exactly the backend-located words marked. The same page
  // says "x > 5" earlier in another passage; a mark that ignored the sign would land there (review round 1, high 1).
  await row(page, 1).getByRole('button', { name: '“packet delivery rises when x < 5 over many trials”' }).click()
  const sheet = page.getByRole('dialog')
  const marks = sheet.locator('mark.citation-highlight')
  await expect(marks).toHaveCount(1)
  await expect(marks).toHaveText('packet delivery rises when x < 5 over many trials')
  await expect(sheet.getByText('x > 5', { exact: false })).toHaveCount(0)  // the passage alone, not the page re-searched
  await expect(sheet).toContainText('Located quote')
  await expect(sheet).toContainText('SYNTHETIC depth based routing for acoustic sensor fields')
  await shot(page, '08-passage')
  await page.keyboard.press('Escape')
  await expect(sheet).toHaveCount(0)
  // A quote from the abstract opens the abstract with its own words marked.
  await row(page, 5).getByRole('button', { name: '“routing and void handling both shorten paths”' }).click()
  await expect(sheet.locator('mark.citation-highlight')).toHaveText('routing and void handling both shorten paths')
  await page.keyboard.press('Escape')
  await expect(sheet).toHaveCount(0)

  // The exports are the stored rows, the pair that could not be checked included.
  const [csv] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: 'Export CSV' }).click()])
  const csvText = readFileSync(await csv.path(), 'utf8')
  expect(csvText.split('\n')[0]).toContain('pair,marker,sentence,claim,target')
  expect(csvText).toContain('could_not_check')
  expect(csvText).toContain('found_partial')
  const [md] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: 'Export Markdown' }).click()])
  expect(md.suggestedFilename()).toMatch(/\.md$/)
  expect(readFileSync(await md.path(), 'utf8')).toContain('| pair | marker |')

  // Phone width: one card per citation, nothing scrolls sideways.
  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await shot(page, '09-results-phone')
  await page.goto(`${SERVER_URL}/#/library/verify`)
  await expect(page.locator('.cc-drafts li')).toHaveCount(1)
  await expect(page.locator('.cc-drafts li')).toContainText('Completed')
  // Completed and could-not-be-checked pairs are listed apart (review round 1, high 3).
  await expect(page.locator('.cc-drafts li')).toContainText('5 completed · 1 could not be checked')
  await shot(page, '10-start-phone')
})
