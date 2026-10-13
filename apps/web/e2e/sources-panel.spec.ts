import { expect, request as apiRequest, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'
import { panel } from './panels'

// UI parity S13: the Sources panel (mockup P5, P6, P8, P9, P10). Filter tabs whose counts are the rows each tab lists,
// the toolbar (search, Sort, PDF filter, Download, Save to library), the source table (`tr.source-row`, checkbox,
// title, pills, row actions, Model proposal, the Include / Undecided / Exclude control), the exclusion reason bar and the
// selection bar. Its own fixture server with full-text reading on, so the [parity] research has included, passed-abstract,
// undecided and excluded works. Every record is SYNTHETIC; a passing case shows how the page behaves, not the quality
// of a search or a screening.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

const PARITY = '[parity] How has the relationship between k-connectivity, network lifetime and energy consumption been modeled in SYNTHETIC wireless sensor networks?'

class SourcesServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-sources-'))
  constructor(readonly port: number) {}
  async start() {
    const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend'), DEIXIS_FIXTURE_FULLTEXT: 'on' }
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`http://127.0.0.1:${this.port}/api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`sources fixture server on ${this.port} did not start`)
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
type Source = {
  source_version_id: string; work_id: string; title: string; year: number | null; version_role: string; doi: string | null
  selection: { state: string; origin: string; version: number; user_reason: string | null }
  screening: { stage: string | null; outcome: string | null; passed_abstract: boolean } | null
  access: { assets: unknown[] }
}
type View = {
  runs: Array<{ kind: string; status: string }>
  counts: { included: number; excluded: number; pending: number }
  answers: Array<{ status: string; report_version: number | null; claims: Array<{ evidence: Array<{ work_id: string; source_version_id: string }> }> }>
  sources: Source[]
}
const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
const post = (api: Api, url: string, data: unknown, headers: Record<string, string> = {}) => api.context.post(url, { data, headers: { 'x-deixis-csrf': api.token, ...headers } })
const viewOf = async (api: Api, rid: string) => (await (await api.context.get(`/api/researches/${rid}`)).json()) as View
const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`), animations: 'disabled' })

// The tab each record belongs to, by the rule the panel states (independent of the page's code).
function tabOf(s: Source) {
  if (s.selection.state === 'pending' && s.selection.origin !== 'user' && s.screening?.stage === 'abstract' && s.screening.passed_abstract) return 'Passed abstract'
  return ({ included: 'Included', pending: 'Undecided', excluded: 'Excluded' } as Record<string, string>)[s.selection.state]
}

test.describe.serial('S13: the Sources panel', () => {
  test.setTimeout(240_000)
  const server = new SourcesServer(nextPort())
  let api: Api
  let rid = ''
  let page: Page
  const sourcesUrl = () => `${server.url()}/#/research/${rid}/sources`
  const sources = () => panel(page, 'Sources')
  const tab = (name: string) => sources().locator('.tabs button').filter({ hasText: new RegExp(`^${name}\\d`) })
  const records = () => sources().locator('tr.source-row:not(.is-other-version)')

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(240_000)
    await server.start()
    const context = await apiRequest.newContext({ baseURL: server.url(), extraHTTPHeaders: { origin: server.url() } })
    api = { context, token: (await (await context.get('/api/session')).json()).csrf_token as string }
    const created = await post(api, '/api/researches', { question: PARITY, model_connection: 'codex', requested_model: 'fixture-model', effort: 'standard' })
    expect(created.status()).toBe(201)
    rid = (await created.json()).research.id
    expect((await post(api, `/api/researches/${rid}/runs`, { kind: 'discovery' }, { 'Idempotency-Key': `sources-discovery-${rid}` })).ok()).toBe(true)
    await expect.poll(async () => {
      const view = await viewOf(api, rid)
      return ['discovery', 'answer'].every(k => view.runs.some(r => r.kind === k)) && !view.runs.some(r => ACTIVE.has(r.status))
    }, { timeout: 110_000, intervals: [500] }).toBe(true)
    page = await browser.newPage({ viewport: { width: 1280, height: 900 }, acceptDownloads: true })
  })
  test.afterAll(async () => { await page?.close(); await api?.context.dispose(); await server.stop() })

  test('every tab count is the number of works that tab lists, from the research’s own records', async () => {
    const view = await viewOf(api, rid)
    const recs = view.sources.filter(s => s.version_role === 'record')
    await page.goto(sourcesUrl())
    await expect(sources()).toBeVisible()
    // The mockup's tabs in its order (Not read is wired with the never-screened list, S27).
    await expect(sources().locator('.tabs button')).toHaveText([/^Cited in answer\d+$/, /^Included\d+$/, /^Passed abstract\d+$/, /^Undecided\d+$/, /^Excluded\d+$/, /^All\d+$/])
    const answer = view.answers.filter(a => a.status === 'structurally_valid').sort((a, b) => (b.report_version ?? 0) - (a.report_version ?? 0))[0]
    const cited = new Set(answer.claims.flatMap(c => c.evidence.map(e => e.work_id)))
    const expected: Record<string, number> = {
      'Cited in answer': recs.filter(s => cited.has(s.work_id)).length, All: recs.length,
      Included: 0, 'Passed abstract': 0, Undecided: 0, Excluded: 0,
    }
    recs.forEach(s => { expected[tabOf(s)]++ })
    expect(expected.Included).toBe(view.counts.included)
    expect(expected.Excluded).toBe(view.counts.excluded)
    expect(expected['Passed abstract']).toBeGreaterThan(0)
    expect(expected.Included + expected['Passed abstract'] + expected.Undecided + expected.Excluded).toBe(expected.All)
    for (const [name, n] of Object.entries(expected)) {
      await expect(tab(name).locator('em')).toHaveText(n.toLocaleString())
      await tab(name).click()
      await expect(tab(name)).toHaveAttribute('aria-pressed', 'true')
      await expect(records()).toHaveCount(n)
      await expect(sources().locator('thead th').nth(1)).toHaveText(`Source (${n})`)
    }
    // A Passed abstract row is one whose current abstract-stage decision is a candidate; its proposal says so.
    await tab('Passed abstract').click()
    await expect(records().first().locator('.prop')).toContainText('passed abstract')
    await shot(page, 'S13-sources-tabs')
  })

  test('the table row: checkbox, title, pills, row actions, Model proposal and the decision control', async () => {
    await page.goto(sourcesUrl())
    await tab('Included').click()
    const row = records().first()
    await expect(row).toHaveJSProperty('tagName', 'TR')
    await expect(row.locator('td')).toHaveCount(4)
    await expect(row.getByRole('checkbox')).toBeVisible()
    await expect(row.locator('button.src-t')).toBeVisible()
    await expect(row.locator('.pills .pill').first()).toHaveText('DOI')
    // Included by two agreeing full-text reads: the column names that decision and its basis.
    await expect(row.locator('.prop')).toContainText('include')
    await expect(row.locator('.prop')).toContainText('basis: full text (selected pages) · two reads')
    const decision = row.getByRole('group', { name: /^Selection for / })
    await expect(decision.getByRole('button')).toHaveText(['Include', 'Undecided', 'Exclude'])
    await expect(decision.getByRole('button', { name: 'Include', exact: true })).toHaveAttribute('aria-pressed', 'true')
    // Row actions with a PDF; Remove PDF is accent like the rest, not the danger colour.
    const acts = row.locator('.rowacts')
    for (const name of ['Open PDF', 'Plain text', 'Replace PDF', 'Remove PDF', 'DOI', 'Remove from research']) await expect(acts.getByRole(name === 'DOI' ? 'link' : 'button', { name, exact: true })).toBeVisible()
    const colour = (l: Locator) => l.evaluate(el => getComputedStyle(el).color)
    expect(await colour(acts.getByRole('button', { name: 'Remove PDF', exact: true }))).toBe(await colour(acts.getByRole('button', { name: 'Open PDF', exact: true })))
    // The title opens Source details on that source; Plain text opens its text tab.
    await row.locator('button.src-t').click()
    await expect(panel(page, 'Source details')).toBeVisible()
    await panel(page, 'Source details').getByRole('button', { name: 'Back' }).click()
    await expect(sources()).toBeVisible()
    await records().first().locator('.rowacts').getByRole('button', { name: 'Plain text', exact: true }).click()
    await expect(panel(page, 'Source details').getByRole('tab', { name: 'Plain text', selected: true })).toBeVisible()
    await panel(page, 'Source details').getByRole('button', { name: 'Back' }).click()
    await shot(page, 'S13-sources-row')
  })

  test('sort, search and the PDF filter change the rows; Download writes the rows shown', async () => {
    await page.goto(sourcesUrl())
    await tab('Included').click()
    const titles = () => records().locator('.src-t').allTextContents()
    await sources().getByRole('combobox', { name: 'Sort sources' }).click()
    await page.getByRole('option', { name: 'Title A–Z' }).click()
    await expect(sources().getByRole('combobox', { name: 'Sort sources' })).toContainText('Title A–Z')
    const sorted = await titles()
    expect(sorted).toEqual([...sorted].sort((a, b) => a.localeCompare(b)))
    const view = await viewOf(api, rid)
    const included = view.sources.filter(s => s.version_role === 'record' && s.selection.state === 'included')
    // The search matches title, authors, venue, DOI or year.
    const needle = included[0].title.slice(-9)
    await sources().getByRole('searchbox', { name: 'Filter sources' }).fill(needle)
    await expect(records()).toHaveCount(included.filter(s => s.title.toLowerCase().includes(needle.toLowerCase())).length)
    await sources().getByRole('searchbox', { name: 'Filter sources' }).fill('')
    // PDF: No PDF on All lists the works without a stored PDF.
    await tab('All').click()
    await sources().getByRole('combobox', { name: 'Filter sources by PDF availability' }).click()
    await page.getByRole('option', { name: /^No PDF/ }).click()
    await expect(sources().getByRole('combobox', { name: 'Filter sources by PDF availability' })).toContainText('PDF: No PDF')
    const families = new Map<string, Source[]>()
    view.sources.forEach(s => families.set(s.work_id, [...(families.get(s.work_id) ?? []), s]))
    const withoutPdf = [...families.values()].filter(f => f.some(s => s.version_role === 'record') && !f.some(s => s.access.assets.length)).length
    await expect(records()).toHaveCount(withoutPdf)
    await sources().getByRole('searchbox', { name: 'Filter sources' }).fill('SYNTHETIC no such title anywhere')
    await expect(sources().locator('.more-row')).toContainText('No works match “SYNTHETIC no such title anywhere” with no pdf.')
    await sources().locator('.more-row').getByRole('button', { name: 'Clear search and filter' }).click()
    await expect(sources().getByRole('combobox', { name: 'Filter sources by PDF availability' })).toContainText('PDF: All')
    // Download: one CSV line per row shown, after the header.
    await tab('Included').click()
    const download = page.waitForEvent('download')
    await sources().getByRole('button', { name: 'Download', exact: true }).click()
    const file = await (await download).path()
    const lines = readFileSync(file, 'utf8').replace(/^﻿/, '').trim().split('\r\n')
    expect(lines[0]).toContain('Model proposal')
    expect(lines.length - 1).toBe(await sources().locator('tr.source-row').count())
  })

  test('Exclude opens the reason bar; Skip, Add a reason, Save reason and Edit keep the reason with the choice', async () => {
    await page.goto(sourcesUrl())
    await tab('Included').click()
    const row = records().first()
    const title = (await row.locator('.src-t').textContent())!
    await row.getByRole('button', { name: 'Exclude', exact: true }).click()
    const why = sources().locator('.why-bar')
    await expect(why).toContainText(`${title} excluded. Why exclude it? Optional; kept with your choice.`)
    await expect(why.getByLabel('Reason for excluding this source')).toBeFocused()
    await why.getByRole('button', { name: 'Skip' }).click()
    await expect(why).toHaveCount(0)
    await tab('Excluded').click()
    const excluded = sources().locator('tr.source-row').filter({ hasText: title })
    await excluded.getByRole('button', { name: `Add a reason for excluding ${title}` }).click()
    await why.getByLabel('Reason for excluding this source').fill('SYNTHETIC off-topic network')
    await why.getByRole('button', { name: 'Save reason' }).click()
    await expect(why).toHaveCount(0)
    await expect(excluded.locator('.reason')).toContainText('Your reason: SYNTHETIC off-topic network')
    await excluded.getByRole('button', { name: `Edit your reason for ${title}` }).click()
    await expect(why.getByLabel('Reason for excluding this source')).toHaveValue('SYNTHETIC off-topic network')
    await why.getByLabel('Reason for excluding this source').fill('SYNTHETIC terrestrial only')
    await why.getByRole('button', { name: 'Save reason' }).click()
    await expect(excluded.locator('.reason')).toContainText('Your reason: SYNTHETIC terrestrial only')
    const stored = (await viewOf(api, rid)).sources.find(s => s.title === title && s.version_role === 'record')!
    expect(stored.selection).toMatchObject({ state: 'excluded', origin: 'user', user_reason: 'SYNTHETIC terrestrial only' })
    await shot(page, 'S13-sources-reason')
  })

  test('a citation pill names only the version the answer cites; a formula-like title is written to the CSV as text', async () => {
    // The view as the server sends it, with two SYNTHETIC changes: an uncited copy of a cited record as another version
    // of the same work, and a title that starts like a spreadsheet formula.
    const view = await viewOf(api, rid)
    const answer = view.answers.filter(a => a.status === 'structurally_valid').sort((a, b) => (b.report_version ?? 0) - (a.report_version ?? 0))[0]
    const citedVersions = new Set(answer.claims.flatMap(c => c.evidence.map(e => e.source_version_id)))
    const cited = view.sources.find(s => s.version_role === 'record' && citedVersions.has(s.source_version_id))!
    const formula = '=HYPERLINK("https://example.invalid","SYNTHETIC")'
    await page.route(url => url.pathname === `/api/researches/${rid}`, async route => {
      const body = await (await route.fetch()).json() as View & { sources: Array<Record<string, unknown>> }
      const at = body.sources.findIndex(s => s.source_version_id === cited.source_version_id)
      const copy = { ...body.sources[at], source_version_id: 'sv_synthetic_uncited_copy', version_role: 'other_version', version_label: 'preprint', screening: null, title: `${cited.title} (SYNTHETIC uncited copy)` }
      body.sources.splice(at + 1, 0, copy)
      const included = body.sources.find(s => s.version_role === 'record' && (s.selection as { state: string }).state === 'included' && s.source_version_id !== cited.source_version_id)!
      included.title = formula
      await route.fulfill({ json: body })
    })
    try {
      await page.goto(sourcesUrl())
      await tab('All').click()
      const own = records().filter({ hasText: cited.title }).first()
      await expect(own.locator('.pill.is-cited')).toHaveText(/^cited in \d+ claims? of V\d+$/)
      const copyRow = sources().locator('tr.source-row.is-other-version').filter({ hasText: 'SYNTHETIC uncited copy' })
      await expect(copyRow).toHaveCount(1)
      await expect(copyRow.locator('.pill.is-cited')).toHaveCount(0)
      await tab('Included').click()
      const download = page.waitForEvent('download')
      await sources().getByRole('button', { name: 'Download', exact: true }).click()
      const csv = readFileSync(await (await download).path(), 'utf8')
      expect(csv).toContain(`"'=HYPERLINK(""https://example.invalid"",""SYNTHETIC"")"`)
      expect(csv).not.toMatch(/(^|,)"?=HYPERLINK/m)
    } finally { await page.unrouteAll({ behavior: 'wait' }) }
  })

  test('the selection bar: N chosen, Start table, Add to table, Add to library (the server’s count), Remove, Clear', async () => {
    await page.goto(sourcesUrl())
    await tab('Included').click()
    await records().nth(0).getByRole('checkbox').check()
    await records().nth(1).getByRole('checkbox').check()
    await expect(records().nth(0)).toHaveClass(/\bsel\b/)
    const bar = page.getByRole('region', { name: 'Chosen sources' })
    await expect(bar).toContainText('2 chosen')
    await expect(bar.getByRole('button')).toHaveText(['Start table', 'Add to table', 'Add to library', 'Remove from research', 'Clear'])
    await bar.getByRole('button', { name: 'Add to library' }).click()
    await expect(page.getByText('Saved 2 sources to the Library.')).toBeVisible()
    await bar.getByRole('button', { name: 'Add to library' }).click()
    await expect(page.getByText('2 sources were already in the Library.')).toBeVisible()
    // A failed save names what was left unsaved, never a success.
    await page.route('**/api/library/items', route => route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'SYNTHETIC library failure' }) }))
    await bar.getByRole('button', { name: 'Add to library' }).click()
    await expect(page.getByText(/2 not saved: .*SYNTHETIC library failure/)).toBeVisible()
    await page.unroute('**/api/library/items')
    await shot(page, 'S13-sources-selection')
    await bar.getByRole('button', { name: 'Clear' }).click()
    await expect(bar).toHaveCount(0)
    // The toolbar's Save to library saves the rows shown.
    await sources().getByRole('searchbox', { name: 'Filter sources' }).fill((await records().nth(2).locator('.src-t').textContent())!)
    await expect(records()).toHaveCount(1)
    await sources().getByRole('button', { name: 'Save to library' }).click()
    await expect(page.getByText('Saved 1 source to the Library.')).toBeVisible()
  })
})
