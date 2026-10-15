import { expect, request as apiRequest, test, type APIRequestContext, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import type { CitationMap, ResearchView } from '../src/api'
import { nextPort } from './ports'
import { chooseLanguage } from './language'
import { backPanel, chooseTheme, openPanel, panel, sourcePanel } from './panels'

// The citation map panel (D42, slice 4) on SYNTHETIC records: the fixture's "[citemap]" works A–F cite each other as
// the development-line works do (B, C, F → A; D → B), and B and C also cite the outside work W979, whose record only an
// id lookup made after `citemap-describe` exists returns. Shows workflow behaviour, not live OpenAlex data.
const REPO = path.resolve(process.cwd(), '..', '..')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
const PORT = nextPort()
const URL = `http://127.0.0.1:${PORT}`
const OUTSIDE_TITLE = 'SYNTHETIC outside pulse spacing model cited by two sources'
const A_TITLE = 'SYNTHETIC A foundational release model with fixed pulse spacing'
const B_TITLE = 'SYNTHETIC B adaptive timing for release experiments'
mkdirSync(OUT, { recursive: true })

class Server {
  private proc?: ChildProcess
  dataDir = ''
  async start() {
    this.dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-citemap-'))
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

// SYNTHETIC map reads in the shape of GET /citation-map, built with a fixed-seed generator.
type MapNode = CitationMap['nodes'][number]
type MapOutside = CitationMap['outside'][number]
function synthNode(i: number, state: MapNode['state'], year: number): MapNode {
  return { work_id: `wrk_synth_${i}`, source_version_id: `srv_synth_${i}`, openalex_ids: [`W${100000 + i}`], title: `SYNTHETIC work ${i}`,
    authors: [`Author${i} Synth`], authors_short: `Synth${i}`, year, venue: 'Synthetic Journal', doi: null, cited_by_count: i, state, references_read: i % 50 !== 0 }
}
function synthOutside(i: number, citedBy: string[]): MapOutside {
  return { openalex_id: `W${900000 + i}`, cited_by: citedBy, in_count: citedBy.length, source_version_id: null, title: i % 4 ? `SYNTHETIC outside work ${i}` : null,
    authors: i % 4 ? [`Outside${i} Synth`] : [], authors_short: i % 4 ? `Outside${i}` : '', year: i % 4 ? 1990 + i : null, venue: null, doi: null, cited_by_count: null, removed_from_research: false }
}
function bigMap(): CitationMap {
  let seed = 7
  const next = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648
  const nodes = Array.from({ length: 669 }, (_, i) => synthNode(i, i < 200 ? 'included' : i < 600 ? 'pending' : 'excluded', 1990 + Math.floor(next() * 36)))
  const pairs = new Set<string>()
  while (pairs.size < 4614) {
    const a = Math.floor(next() * 669), b = Math.floor(next() ** 2 * 669)
    if (a !== b) pairs.add(`${a}>${b}`)
  }
  const edges = [...pairs].map(p => { const [a, b] = p.split('>'); return { from: `wrk_synth_${a}`, to: `wrk_synth_${b}` } })
  const outside = Array.from({ length: 40 }, (_, i) => synthOutside(i, Array.from({ length: 2 + (39 - i) % 12 }, (_, k) => `wrk_synth_${(i * 13 + k * 7) % 600}`)))
  return { nodes, edges, outside, counts: { works: 669, edges: edges.length, unread_references: nodes.filter(n => !n.references_read).length, no_openalex_id: 0, outside_total: 1840, outside_threshold: 2, outside_without_metadata: 10 } }
}
function singleMap(): CitationMap {
  const outside = [0, 1, 2].map(i => synthOutside(i + 1, ['wrk_synth_0']))
  return { nodes: [synthNode(0, 'included', 2022)], edges: [], outside, counts: { works: 1, edges: 0, unread_references: 0, no_openalex_id: 0, outside_total: 3, outside_threshold: 1, outside_without_metadata: 0 } }
}

const ACTIVE = ['queued', 'running', 'pause_requested']
async function settle(api: APIRequestContext, rid: string) {
  await expect.poll(async () => {
    const view: ResearchView = await (await api.get(`/api/researches/${rid}`)).json()
    return view.runs.some(r => r.kind === 'discovery' && r.status === 'completed') && !view.runs.some(r => ACTIVE.includes(r.status))
  }, { timeout: 90_000 }).toBe(true)
}
const map = (page: Page) => page.locator('.citemap')
const node = (page: Page, name: RegExp) => map(page).locator('svg').getByRole('button', { name })
const detailTitle = (page: Page) => map(page).locator('.cm-detail h3')
const outsideList = (page: Page) => map(page).locator('.cm-cols section').filter({ hasText: 'Often-cited works outside this research' })

test.describe('citation map', () => {
  const server = new Server()
  test.beforeAll(async () => { await server.start() })
  test.afterAll(async () => { await server.stop() })
  let api: APIRequestContext
  test.beforeEach(async () => { api = await apiRequest.newContext({ baseURL: URL, extraHTTPHeaders: { origin: URL } }) })
  test.afterEach(async () => { await api.dispose() })

  test('opens from the menu, reads the missing record, selects works, adds and undoes an outside work', async ({ page }) => {
    test.setTimeout(240_000)
    const csrf = (await (await api.get('/api/session')).json()).csrf_token as string
    const headers = { 'x-deixis-csrf': csrf }
    await page.goto(URL)
    await page.getByLabel('Research question').fill('SYNTHETIC molecule release scheduling [citemap]')
    await page.getByRole('button', { name: 'Start research' }).click()
    await page.waitForURL(/#\/research\//)
    const rid = page.url().split('/research/')[1].split('/')[0]
    await settle(api, rid)
    const research: ResearchView = await (await api.get(`/api/researches/${rid}`)).json()
    expect(research.sources).toHaveLength(6)
    // A and B included, the others left as the screening left them.
    for (const title of [A_TITLE, B_TITLE]) {
      const source = research.sources.find(s => s.title === title)!
      const changed = await api.patch(`/api/researches/${rid}/selections/${source.source_version_id}`, { headers, data: { state: 'included', expected_version: source.selection.version, reason: 'SYNTHETIC inclusion' } })
      expect(changed.ok()).toBe(true)
    }
    await page.reload()

    // The ⋯ menu row opens the panel (a §2.2 placement row).
    await page.getByRole('button', { name: 'Research actions' }).click()
    await page.getByRole('menuitem', { name: 'Source citation map' }).click()
    await expect(panel(page, 'Source citation map')).toBeVisible()
    await expect(page).toHaveURL(new RegExp(`#/research/${rid}/citemap$`))
    // Six works and the one outside work; the stored lists give B, C, F → A, D → B and B, C → W979.
    await expect(map(page).locator('svg g.n')).toHaveCount(7)
    await expect(map(page).locator('svg path.e')).toHaveCount(6)
    await expect(map(page).locator('.cm-sum p')).toHaveText('6 sources · 6 citation links · 1 work outside this research is cited by at least 2 sources')
    await expect(map(page).getByRole('button', { name: /^Not in this research 1$/ })).toHaveAttribute('aria-pressed', 'true')
    await expect(outsideList(page).locator('.cm-row')).toHaveCount(1)
    await expect(outsideList(page).locator('.cm-row')).toContainText('W979')
    await expect(outsideList(page).locator('.cm-row')).toContainText('title unknown')

    // The plan row says what a reading run would ask; adding the work before its record is read is refused plainly.
    const plan = map(page).locator('.cm-plan')
    await expect(plan).toContainText('1 work outside this research has no title yet · 1 OpenAlex request · no model call')
    await outsideList(page).getByRole('button', { name: 'Add to candidates' }).click()
    await expect(page.locator('.toast')).toContainText('Run “Read reference lists” first')
    writeFileSync(path.join(server.dataDir, 'citemap-describe'), '')
    await plan.getByRole('button', { name: 'Read reference lists' }).click()
    await expect(outsideList(page).getByRole('button', { name: OUTSIDE_TITLE })).toBeVisible({ timeout: 60_000 })
    await expect(plan).toHaveCount(0)
    const view: ResearchView = await (await api.get(`/api/researches/${rid}`)).json()
    const mapRun = view.runs.find(r => r.kind === 'citation_map')!
    expect(mapRun.status).toBe('completed')
    expect(mapRun.usage.model_calls ?? 0).toBe(0)

    // Choosing a node changes the detail; its lists are the stored links.
    await node(page, /^Arden 2010,/).click()
    await expect(detailTitle(page)).toHaveText(A_TITLE)
    await expect(map(page).locator('.cm-lst').nth(1)).toContainText('Works citing it · 3')
    await expect(map(page).locator('svg g.n.sel')).toHaveCount(1)
    // By keyboard: a node is a button; Enter chooses it.
    await node(page, /^Barton 2011,/).focus()
    await page.keyboard.press('Enter')
    await expect(detailTitle(page)).toHaveText(B_TITLE)
    await expect(map(page).locator('.cm-lst').first()).toContainText('Works it cites · 2')
    // Search marks the matches.
    await map(page).getByLabel('Search the map for a source').fill('Outis')
    await expect(map(page).locator('svg g.n.hit')).toHaveCount(1)
    await map(page).getByLabel('Search the map for a source').fill('')
    // The network layout draws the same works.
    await map(page).getByRole('button', { name: 'Network', exact: true }).click()
    await expect(map(page).locator('svg g.n')).toHaveCount(7)
    await map(page).getByRole('button', { name: 'Timeline', exact: true }).click()

    // Add to candidates: the work joins as Undecided; Undo takes it out again.
    await outsideList(page).getByRole('button', { name: 'Add to candidates' }).click()
    await expect(page.locator('.toast')).toContainText('Outis 2008 was added to the candidates')
    await expect(detailTitle(page)).toHaveText(OUTSIDE_TITLE)
    await expect(map(page).locator('.cm-detail .cm-pill').first()).toHaveText('Undecided')
    await expect(outsideList(page).locator('.cm-row')).toHaveCount(0)
    await expect.poll(async () => ((await (await api.get(`/api/researches/${rid}`)).json()) as ResearchView).sources.some(s => s.title === OUTSIDE_TITLE)).toBe(true)
    await page.locator('.toast').getByRole('button', { name: 'Undo' }).click()
    await expect(page.locator('.toast')).toContainText('Source removed from this research.')
    await expect(outsideList(page).getByRole('button', { name: 'Add to candidates' })).toBeVisible()
    await expect(outsideList(page).locator('.cm-row')).toContainText('Removed from this research earlier')

    // Open source stacks Source details on the map; Back returns to it.
    await node(page, /^Arden 2010,/).click()
    await map(page).getByRole('button', { name: 'Open source' }).click()
    await expect(sourcePanel(page)).toBeVisible()
    await backPanel(page)
    await expect(panel(page, 'Source citation map')).toBeVisible()

    // The URL reopens the panel; the Sources panel opens it too.
    await page.reload()
    await expect(panel(page, 'Source citation map')).toBeVisible()
    await expect(map(page).locator('svg g.n')).toHaveCount(7)
    await openPanel(page, 'sources')
    await page.locator('.sources-panel-box').getByRole('button', { name: 'Source citation map' }).click()
    await expect(panel(page, 'Source citation map')).toBeVisible()

    // A SYNTHETIC map of a real research's size (669 works, 4,614 links, 40 outside works), read from a mocked route,
    // with a citation map run paused on OpenAlex's spent daily budget: the default view, Show all, both layouts, the band.
    await page.route(`**/api/researches/${rid}/citation-map`, route => route.fulfill({ json: bigMap() }))
    await page.route(`**/api/researches/${rid}/citation-map/prepare`, route => route.fulfill({ json: { works_to_resolve: 0, sources_to_read: 12, outside_to_describe: 0, requests: 1, unresolvable_without_doi: 0 } }))
    await page.route(`**/api/researches/${rid}`, async route => {
      const response = await route.fetch()
      const body = await response.json() as ResearchView
      body.runs = [{ ...body.runs[0], id: 'run_synthetic_citemap', kind: 'citation_map', status: 'paused', pause_reason: 'openalex_budget_exhausted', error: { reset_at: '2026-10-17T00:00:00Z' }, steps: [], target: null }, ...body.runs]
      await route.fulfill({ response, json: body })
    })
    await page.reload()
    await expect(panel(page, 'Source citation map')).toBeVisible()
    await expect(map(page).locator('.cm-banner')).toContainText('OpenAlex’s daily quota is used up. The reference lists of 12 sources could not be read')
    await expect(map(page).locator('.cm-plan')).toHaveCount(0)
    // 200 included + the 30 most-cited of 400 undecided + 69 excluded + 40 outside.
    await expect(map(page).locator('svg g.n')).toHaveCount(339)
    let started = Date.now()
    await map(page).getByRole('button', { name: 'Show all', exact: true }).click()
    await expect(map(page).locator('svg g.n')).toHaveCount(709)
    console.log(`citemap: Show all (709 nodes, timeline) ${Date.now() - started} ms`)
    started = Date.now()
    await map(page).getByRole('button', { name: 'Network', exact: true }).click()
    await expect(map(page).locator('svg g.n')).toHaveCount(709)
    console.log(`citemap: network layout (709 nodes) ${Date.now() - started} ms`)
    started = Date.now()
    // At this density nodes overlap in the network layout, so the click goes to the node itself.
    await map(page).locator('svg g.n').nth(5).dispatchEvent('click')
    await expect(map(page).locator('svg g.n.sel')).toHaveCount(1)
    console.log(`citemap: select a node (709 nodes) ${Date.now() - started} ms`)
    await map(page).getByRole('button', { name: 'Timeline', exact: true }).click()
    await map(page).getByRole('button', { name: 'Show the 30 most cited' }).click()
    await expect(map(page).locator('svg g.n')).toHaveCount(339)
    await expect(map(page).locator('svg g.n.included').first()).toBeVisible()
    await page.screenshot({ path: path.join(OUT, 'citemap-large-1440.png'), animations: 'disabled' })
    // One source: the map shows its reference list and the note says why there are no links between sources.
    await page.unroute(`**/api/researches/${rid}/citation-map`)
    await page.unroute(`**/api/researches/${rid}`)
    await page.route(`**/api/researches/${rid}/citation-map`, route => route.fulfill({ json: singleMap() }))
    await page.route(`**/api/researches/${rid}/citation-map/prepare`, route => route.fulfill({ json: { works_to_resolve: 0, sources_to_read: 0, outside_to_describe: 0, requests: 0, unresolvable_without_doi: 0 } }))
    await page.reload()
    await expect(map(page).locator('.cm-note')).toContainText('Links between sources need at least two sources in the research')
    await expect(map(page).locator('.cm-sum p')).toHaveText('1 source · 3 works from its reference list matched in OpenAlex')
    await expect(map(page).locator('svg g.n')).toHaveCount(4)
    await expect(map(page).getByRole('heading', { name: 'The core of this research' })).toHaveCount(0)
    await page.screenshot({ path: path.join(OUT, 'citemap-single-1440.png'), animations: 'disabled' })
    await page.unrouteAll()
    await page.reload()
    await expect(map(page).locator('svg g.n')).toHaveCount(7)

    // Both themes, desktop and phone width; the panel keeps its content inside the screen.
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 })
      for (const theme of ['light', 'dark'] as const) {
        await chooseTheme(page, theme)
        await expect(map(page).locator('svg g.n')).toHaveCount(7)
        await expect.poll(() => page.locator('.citemap').evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
        await page.screenshot({ path: path.join(OUT, `citemap-${width}-${theme}.png`), fullPage: false, animations: 'disabled' })
      }
    }
    // In Turkish the panel reads as the mockup does.
    await page.setViewportSize({ width: 1440, height: 1000 })
    await chooseTheme(page, 'light')
    await chooseLanguage(page, 'tr')
    await expect(panel(page, 'Atıf haritası')).toBeVisible()
    await expect(map(page).getByRole('heading', { name: 'Bu araştırmanın çekirdeği' })).toBeVisible()
    await expect(map(page).getByRole('heading', { name: 'Araştırmada olmayan, sık anılan işler' })).toBeVisible()
    await expect(map(page).locator('.cm-sum p')).toHaveText('6 kaynak · 6 atıf bağı · araştırmada olmayan 1 iş en az 2 kaynak tarafından anılıyor')
    await page.screenshot({ path: path.join(OUT, 'citemap-1440-tr.png'), animations: 'disabled' })
    await chooseLanguage(page, 'en')
  })
})
