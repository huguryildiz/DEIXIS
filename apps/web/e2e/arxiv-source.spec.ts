import { expect, test, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

// Case O: the arXiv source route (slice 22, D104). With DEIXIS_ARXIV_SOURCE=auto and Marker not installed, a PDF that
// is an arXiv version gets the numbered display equations of the authors' LaTeX source of that version placed into
// its page text, matched to the page by their numbers. This checks application behavior with a SYNTHETIC record, a
// SYNTHETIC PDF and a SYNTHETIC source archive (tests/arxiv_helpers.py) and a fake fetch, not real arXiv access or
// matching quality on real papers.
//
// Its own fixture server with DEIXIS_FIXTURE_ARXIV_SOURCE=fake: Settings(arxiv_source="auto"), Marker not installed
// (a fresh temp data directory has no equation-reader environment), and deixis.documents.fetch.fetch_file
// monkeypatched to return the SYNTHETIC source archive instead of a network request.

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
    return { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend'), DEIXIS_FIXTURE_ARXIV_SOURCE: 'fake' }
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
  const server = new ArxivSourceServer(8799)
  let page: Page

  test.beforeAll(async ({ browser }) => {
    await server.start()
    page = await browser.newPage()
  })
  test.afterAll(async () => { await page?.close(); await server.stop() })

  test('generating an answer fetches the PDF and reads its equations from the arXiv source', async () => {
    // The PDF is fetched and its equations are read as part of the answer run's inspection step; the source row
    // shows nothing until then (D104's route runs where equations are read today: background, answer, table, cell).
    await startResearch(page, server, 'SYNTHETIC signal detection threshold study')
    await expect(page.getByText('Ran search & screening')).toBeVisible({ timeout: 60_000 })
    await page.getByRole('tab', { name: /Answer/ }).click()
    await page.getByRole('button', { name: 'Generate answer now' }).click()
    await expect(page.getByText('Ran answer generation')).toBeVisible({ timeout: 60_000 })
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

  test('the answer citation shows the "arXiv source" badge, and opening it shows the passage notice with a rendered equation', async () => {
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
