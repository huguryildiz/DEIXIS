import { expect, request as apiRequest, test, type APIRequestContext, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import type { ResearchView, SnowballRound, SnowballView } from '../src/api'
import { nextPort } from './ports'
import { backPanel, panel, sourcePanel } from './panels'

// Citation snowballing (D91) on SYNTHETIC records: the fixture's "[snowball]" mode gives seed A a reference list of B
// (already in the research) and two outside works, and three citing works (C, already here, and two outside works).
// The outside works answer only once `snowball-open` exists, so discovery never takes them in. The scripted model puts
// the two "off-scope" titles out of scope. This shows the round's bookkeeping and page, not OpenAlex data or model quality.
const REPO = path.resolve(process.cwd(), '..', '..')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
const PORT = nextPort()
const URL = `http://127.0.0.1:${PORT}`
const SEED_TITLE = 'SYNTHETIC A foundational release model with fixed pulse spacing'
const CANDIDATE_TITLES = ['SYNTHETIC snowball backward pulse timing study', 'SYNTHETIC snowball forward pulse spacing extension']
const OUT_OF_SCOPE_TITLES = ['SYNTHETIC snowball backward off-scope soil survey', 'SYNTHETIC snowball forward off-scope bird count']
mkdirSync(OUT, { recursive: true })

class Server {
  private proc?: ChildProcess
  dataDir = ''
  async start() {
    this.dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-snowball-'))
    this.proc = spawn(process.env.DEIXIS_TEST_PYTHON ?? path.join(REPO, '.venv/bin/python'),
      [path.join(REPO, 'tests/acceptance/fixture_server.py'), '--data-dir', this.dataDir, '--port', String(PORT)],
      { cwd: REPO, env: { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: `${REPO}/backend:${REPO}` }, stdio: 'inherit' })
    await expect.poll(async () => { try { return (await fetch(`${URL}/api/health`)).ok } catch { return false } }).toBe(true)
  }
  async stop() {
    const proc = this.proc
    if (!proc || proc.exitCode !== null) return
    const ended = new Promise(resolve => proc.once('exit', resolve))
    proc.kill('SIGTERM'); await ended
  }
}

const ACTIVE = ['queued', 'running', 'pause_requested']
async function settle(api: APIRequestContext, rid: string) {
  await expect.poll(async () => {
    const view: ResearchView = await (await api.get(`/api/researches/${rid}`)).json()
    return view.runs.some(r => r.kind === 'discovery' && r.status === 'completed') && !view.runs.some(r => ACTIVE.includes(r.status))
  }, { timeout: 90_000 }).toBe(true)
}
const included = async (api: APIRequestContext, rid: string) =>
  ((await (await api.get(`/api/researches/${rid}`)).json()) as ResearchView).sources.filter(s => s.selection.state === 'included').length
const box = (page: Page) => panel(page, 'Citation snowballing')
// A row of the round card's counts (<dt> name, <dd> value).
const countRow = (page: Page, name: string) => box(page).locator('.sb-round .sb-counts > div').filter({ has: page.locator('dt', { hasText: new RegExp(`^${name}$`) }) }).locator('dd')

test.describe('citation snowballing', () => {
  const server = new Server()
  test.beforeAll(async () => { await server.start() })
  test.afterAll(async () => { await server.stop() })
  let api: APIRequestContext
  test.beforeEach(async () => { api = await apiRequest.newContext({ baseURL: URL, extraHTTPHeaders: { origin: URL } }) })
  test.afterEach(async () => { await api.dispose() })

  test('a round from the menu: counts match the stored summary, nothing is included, a candidate opens, a second round is offered', async ({ page }) => {
    test.setTimeout(240_000)
    const pageErrors: Error[] = []
    const consoleErrors: string[] = []
    page.on('pageerror', error => pageErrors.push(error))
    page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })

    await page.goto(URL)
    await page.getByLabel('Research question').fill('SYNTHETIC molecule release scheduling [snowball]')
    await page.getByRole('button', { name: 'Start research' }).click()
    await page.waitForURL(/#\/research\//)
    const rid = page.url().split('/research/')[1].split('/')[0]
    await settle(api, rid)
    const before: ResearchView = await (await api.get(`/api/researches/${rid}`)).json()
    expect(before.sources).toHaveLength(6)
    const includedBefore = await included(api, rid)
    // From here OpenAlex answers the seed's outside references and citing works.
    writeFileSync(path.join(server.dataDir, 'snowball-open'), '')

    // The ⋯ menu row opens the panel.
    await page.getByRole('button', { name: 'Research actions' }).click()
    await page.getByRole('menuitem', { name: 'Citation snowballing…' }).click()
    await expect(box(page)).toBeVisible()
    await expect(box(page).getByRole('heading', { name: 'New snowball' })).toBeVisible()
    const start = box(page).getByRole('button', { name: 'Start round 1' })
    await expect(start).toBeDisabled()
    await expect(box(page).locator('#sb-blocked')).toHaveText('Choose at least one seed.')

    // Seed A; both directions are on by default, and turning both off blocks the start.
    await box(page).getByRole('checkbox', { name: new RegExp(`^${SEED_TITLE} \\(2010\\)`) }).check()
    const backward = box(page).getByRole('checkbox', { name: 'Backward: works the seeds cite' })
    const forward = box(page).getByRole('checkbox', { name: 'Forward: works citing the seeds, newest first' })
    await expect(backward).toBeChecked()
    await expect(forward).toBeChecked()
    await backward.uncheck(); await forward.uncheck()
    await expect(box(page).locator('#sb-blocked')).toHaveText('Choose backward, forward or both.')
    await backward.check(); await forward.check()
    await expect(start).toBeEnabled()
    await start.click()
    await expect(page.locator('.toast')).toContainText('The first round started.')

    // Wait for the round's stored summary.
    let round: SnowballRound | undefined
    await expect.poll(async () => {
      const view: SnowballView = await (await api.get(`/api/researches/${rid}/snowball`)).json()
      round = view.series[0]?.rounds[0]
      return round?.status === 'completed' && round.summary !== null
    }, { timeout: 120_000 }).toBe(true)
    const s = round!.summary!
    // The fixture's world, as the summary stored it: one seed, three references (B held, two asked), one citing page of
    // three (C already here), four new works, all read by the model, two candidates.
    expect(s.seeds).toBe(1)
    expect([s.backward_ids, s.held]).toEqual([3, 1])
    expect(s.admissions).toEqual({ new: 4, existing: 1 })
    expect([s.new_works, s.planned_for_screening, s.screening.model_read]).toEqual([4, 4, 4])
    expect(s.candidates).toHaveLength(2)
    const forwardPages = s.requests.filter(q => q.direction === 'forward')
    expect(forwardPages).toHaveLength(1)

    // The round card says what the summary stored, each count apart.
    const card = box(page).locator('.sb-round')
    await expect(card).toHaveCount(1)
    await expect(card.getByRole('heading', { name: 'Round 1' })).toBeVisible()
    await expect(card.locator('.sb-head .pill')).toHaveText('backward + forward')
    await expect(card.locator('.sb-live')).toHaveCount(0)
    const asked = s.requests.filter(q => q.direction === 'backward').reduce((n, q) => n + q.asked, 0)
    expect(asked).toBe(2)
    await expect(countRow(page, 'Seeds')).toHaveText(String(s.seeds))
    await expect(countRow(page, 'Reference ids')).toHaveText(`${s.backward_ids} named · ${s.held} already in this research · ${asked} asked`)
    await expect(countRow(page, 'Citing-work pages')).toHaveText(`1 asked · ${SEED_TITLE}: ${forwardPages[0].provider_total} citing works in OpenAlex`)
    expect(forwardPages[0].provider_total).toBe(3)
    await expect(countRow(page, 'Came back')).toHaveText(`${s.admissions.new} new to this research · ${s.admissions.existing} already held`)
    await expect(countRow(page, 'Abstract screening')).toHaveText(`${s.planned_for_screening} of ${s.new_works} new works planned · ${s.screening.model_read} read by the model`)
    await expect(countRow(page, 'Candidates')).toHaveText(`${s.candidates.length} (two model reads agreed; not included)`)

    // The round's new works: the two candidates carry the pill, the two the model put out of scope carry none.
    const items = card.locator('.sb-items > li')
    await expect(items).toHaveCount(4)
    for (const title of CANDIDATE_TITLES) await expect(items.filter({ hasText: title }).locator('.sb-tags .pill')).toHaveText('Candidate')
    for (const title of OUT_OF_SCOPE_TITLES) await expect(items.filter({ hasText: title }).locator('.sb-tags .pill')).toHaveCount(0)
    await expect(items.filter({ hasText: CANDIDATE_TITLES[0] })).toContainText('cited by a seed')
    await expect(items.filter({ hasText: CANDIDATE_TITLES[1] })).toContainText('cites a seed')
    expect(round!.items.filter(i => i.candidate).map(i => i.title).sort()).toEqual([...CANDIDATE_TITLES].sort())

    // A round includes nothing: the included count is what it was, and no new work is included.
    expect(await included(api, rid)).toBe(includedBefore)
    const after: ResearchView = await (await api.get(`/api/researches/${rid}`)).json()
    expect(after.sources).toHaveLength(10)
    for (const title of [...CANDIDATE_TITLES, ...OUT_OF_SCOPE_TITLES]) expect(after.sources.find(x => x.title === title)?.selection.state).not.toBe('included')

    // A candidate row opens its source; Back returns to the panel.
    await items.filter({ hasText: CANDIDATE_TITLES[0] }).getByRole('button', { name: CANDIDATE_TITLES[0] }).click()
    await expect(sourcePanel(page)).toBeVisible()
    await expect(sourcePanel(page)).toContainText(CANDIDATE_TITLES[0])
    await backPanel(page)
    await expect(box(page)).toBeVisible()

    // A second round in the same series is offered, seeded with the round's candidates.
    const prepare = box(page).locator('.sb-series').getByRole('button', { name: 'Prepare the next round' })
    await expect(prepare).toBeEnabled()
    await prepare.click()
    await expect(box(page).getByRole('heading', { name: 'Next round' })).toBeVisible()
    await expect(box(page).getByRole('button', { name: 'Start the next round' })).toBeEnabled()
    for (const title of CANDIDATE_TITLES) await expect(box(page).getByRole('checkbox', { name: new RegExp(`^${title}`) })).toBeChecked()
    await expect(box(page).getByRole('checkbox', { name: new RegExp(`^${SEED_TITLE}`) })).not.toBeChecked()
    await page.screenshot({ path: path.join(OUT, 'snowball-1280.png'), animations: 'disabled' })

    expect(pageErrors, 'Uncaught page errors').toEqual([])
    expect(consoleErrors, 'Console errors').toEqual([])
  })
})
