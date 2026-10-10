import { expect, test, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'

// Case O: the arXiv source route (slice 22, D104). With DEIXIS_ARXIV_SOURCE=auto and Marker not installed, a PDF that
// is an arXiv version gets the numbered display equations of the authors' LaTeX source of that version placed into
// its page text, matched to the page by their numbers. This checks application behavior with a SYNTHETIC record, a
// SYNTHETIC PDF and a SYNTHETIC source archive (tests/arxiv_helpers.py) and a fake fetch, not real arXiv access or
// matching quality on real papers.
//
// Its own fixture server with DEIXIS_FIXTURE_ARXIV_SOURCE=fake: Settings(arxiv_source="auto"), Marker not installed
// (a fresh temp data directory has no equation-reader environment), and deixis.documents.fetch.fetch_file
// monkeypatched to return the SYNTHETIC source archive instead of a network request. DEIXIS_FIXTURE_FULLTEXT=on: discovery
// fetches and reads the work's PDF, and a table fill reads its equations (the fast path's answer reads none, D253).

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

const TITLE = 'SYNTHETIC signal detection with a molecule counting threshold'

class ArxivSourceServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-arxiv-source-'))
  constructor(readonly port: number) {}

  private env() {  // no real provider keys or user data directory reach the fixture
    return { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend'), DEIXIS_FIXTURE_ARXIV_SOURCE: 'fake', DEIXIS_FIXTURE_FULLTEXT: 'on' }
  }

  async start() {
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env: this.env(), stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`http://127.0.0.1:${this.port}/api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`arXiv source fixture server on ${this.port} did not start`)
  }

  async stop() {
    const proc = this.proc
    if (!proc || proc.exitCode !== null) return
    const exited = new Promise(resolve => proc.once('exit', resolve))
    proc.kill('SIGTERM')
    await exited
  }

  url(hash = '') { return `http://127.0.0.1:${this.port}/${hash}` }
}

const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`), animations: 'disabled' })
const row = (page: Page, title: string) => page.locator('.source-row:not(.is-other-version)', { has: page.getByText(title, { exact: true }) })

async function startResearch(page: Page, server: ArxivSourceServer, question: string) {
  await page.goto(server.url())
  await page.getByLabel('Research question').fill(question)
  await expect(page.locator('.models-summary')).toContainText('fixture-model')
  await page.getByRole('button', { name: 'Start research' }).click()
  await page.waitForURL(/#\/research\//)
}

test.describe.serial('O: the arXiv source route', () => {
  const server = new ArxivSourceServer(nextPort())
  let page: Page

  test.beforeAll(async ({ browser }) => {
    await server.start()
    page = await browser.newPage()
  })
  test.afterAll(async () => { await page?.close(); await server.stop() })

  test('filling a table cell of the arXiv work reads its equations from the arXiv source', async () => {
    // Discovery fetches the open PDF (full-text retrieval on, as the app ships). The fast path's answer reads no
    // equations (D253); a table fill does (D104's table route), so the source row shows nothing until a cell is filled.
    await startResearch(page, server, 'SYNTHETIC signal detection threshold study')
    await expect(page.getByText('Ran search & screening')).toBeVisible({ timeout: 60_000 })
    await page.getByRole('tab', { name: /Sources/ }).click()
    // Both readings include it when its PDF names its DOI; otherwise the person includes it.
    const include = row(page, TITLE).getByRole('button', { name: 'Include' })
    if (await include.isEnabled()) await include.click()
    await expect(include).toBeDisabled()
    await expect(row(page, TITLE).locator('.source-status')).not.toContainText('Equations from the arXiv source')
    await page.getByRole('tab', { name: /Evidence/ }).click()
    await page.getByRole('button', { name: /Add a column/ }).click()
    const editor = page.getByRole('dialog', { name: 'Add column' })
    await editor.getByLabel('Short name').fill('Threshold')
    await editor.getByLabel('Instruction').fill('The detection threshold the source states.')
    await editor.getByRole('button', { name: 'Add column' }).click()
    await expect(editor).toHaveCount(0)
    await page.getByRole('button', { name: /^Fill empty cells/ }).click()
    await expect(page.locator('.evidence-run')).toHaveCount(0, { timeout: 60_000 })
  })

  test('the source row reports equations matched to the page by their numbers, from the arXiv source', async () => {
    await page.getByRole('tab', { name: /Sources/ }).click()
    const source = row(page, TITLE)
    await expect(source).toBeVisible()
    await expect(source.locator('.source-status')).toContainText('Equations from the arXiv source (v2) · 2 matched to 1 page by their numbers', { timeout: 30_000 })
    await source.scrollIntoViewIfNeeded()
    await shot(page, 'O-source-row-desktop')
    await page.setViewportSize({ width: 390, height: 844 })
    await source.scrollIntoViewIfNeeded()
    await shot(page, 'O-source-row-phone')
    await page.setViewportSize({ width: 1280, height: 900 })
  })

  test('a citation of the passage with placed equations shows the "arXiv source" badge, and opening it shows the passage notice with a rendered equation', async () => {
    // The fast answer reads no equations and cites the passages frozen at its read cutoff (D253), read before the table
    // fill placed the equations. So the answer view is served with its first citation pointing at the stored passage the
    // arXiv source route wrote (SYNTHETIC API state); the passage, its equations and every rendering are the app's own.
    const rid = page.url().match(/#\/research\/([^/]+)/)?.[1]
    if (!rid) throw new Error('research id missing from URL')
    const base = server.url(`api/researches/${rid}`)
    const view = await (await page.request.get(base)).json()
    const source = view.sources.find((s: { title: string; access: { assets: unknown[] } }) => s.title === TITLE && s.access.assets.length)
    const text = await (await page.request.get(`${base}/assets/${source.access.assets[0].id}/text`)).json()
    const latex = text.passages.find((p: { text_source: string }) => p.text_source === 'latex_source')
    expect(latex, 'the arXiv source route stored a passage with placed equations').toBeTruthy()
    await page.route(base, async route => {
      const response = await route.fetch()
      const body = await response.json()
      const evidence = body.answers[0].claims[0].evidence
      evidence[0] = { ...evidence[0], passage_id: latex.id, source_version_id: source.source_version_id, title: TITLE,
        source_key: source.source_key ?? evidence[0].source_key, version_label: source.version_label, kind: 'pdf_page',
        reading_depth: 'selected_sections', physical_page: latex.physical_page, printed_label: latex.printed_label,
        text_source: 'latex_source', anchor_text: null }
      await route.fulfill({ response, json: body })
    })
    await page.reload()
    await page.getByRole('tab', { name: /Answer/ }).click()
    const artifact = page.getByRole('button', { name: /Open report:/ })
    await expect(artifact).toBeVisible()
    const dismiss = page.getByRole('button', { name: 'Dismiss notification' })
    if (await dismiss.isVisible()) await dismiss.click()
    await artifact.click()
    const report = page.locator('.report-sheet')
    await expect(report).toBeVisible()
    // The origin is visible on the citation chip itself (Sol r1 finding 5), and named for a screen reader.
    const chip = report.locator('.cite-chip', { has: page.locator('.cite-chip-origin') }).first()
    await expect(chip).toBeVisible()
    await expect(chip.locator('.cite-chip-origin svg')).toBeVisible()
    await expect(chip).toHaveAccessibleName(/arXiv source/)
    await expect(chip).toHaveAttribute('title', /arXiv source/)
    const badge = report.locator('.reference-list .ref-pill', { hasText: 'arXiv source' })
    await expect(badge).toBeVisible()
    await chip.scrollIntoViewIfNeeded()
    await shot(page, 'O-citation-badge-desktop')
    await page.setViewportSize({ width: 390, height: 844 })
    await chip.scrollIntoViewIfNeeded()
    await shot(page, 'O-citation-badge-phone')
    await page.setViewportSize({ width: 1280, height: 900 })

    await chip.click()
    const sheet = page.getByRole('dialog', { name: 'Source details' })
    await expect(sheet).toBeVisible()
    await expect(sheet.locator('.ref-pill', { hasText: 'arXiv source' })).toBeVisible()
    const notice = sheet.locator('.source-notice', { hasText: 'authors’ LaTeX from the arXiv source' })
    await expect(notice).toContainText('Equations (1), (2) in this passage are the authors’ LaTeX from the arXiv source (v2), matched to the page by their numbers.')
    await expect(notice).toContainText('The rest of this passage, including other mathematics, is the PDF’s own text.')
    await expect(sheet.locator('.passage-text .katex').first()).toBeVisible()
    await notice.scrollIntoViewIfNeeded()
    await shot(page, 'O-passage-notice-desktop')
    await page.setViewportSize({ width: 390, height: 844 })
    await notice.scrollIntoViewIfNeeded()
    await shot(page, 'O-passage-notice-phone')
    await page.setViewportSize({ width: 1280, height: 900 })
    await page.keyboard.press('Escape')
  })
})
