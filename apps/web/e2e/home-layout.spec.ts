import { expect, test } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'

// Parity slice S4: the Home composer is the mockup's. Control order, the four menus and the hint lines. The fixture server
// has one connected model ("fixture-model"); every record is SYNTHETIC, so this shows layout and wiring, not search quality.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
mkdirSync(path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance'), { recursive: true })

class HomeServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-home-layout-'))
  constructor(readonly port: number) {}

  async start() {
    const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend') }
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`http://127.0.0.1:${this.port}/api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`home layout fixture server on ${this.port} did not start`)
  }

  async stop() {
    const proc = this.proc
    if (!proc || proc.exitCode !== null) return
    const exited = new Promise(resolve => proc.once('exit', resolve))
    proc.kill('SIGTERM')
    await exited
  }

  url() { return `http://127.0.0.1:${this.port}/` }
}

test.describe.serial('S4: Home layout', () => {
  const server = new HomeServer(nextPort())
  test.beforeAll(async () => { await server.start() })
  test.afterAll(async () => { await server.stop() })

  test('control row order, placeholder and hint line', async ({ page }) => {
    await page.goto(server.url())
    const question = page.getByLabel('Research question')
    await expect(question).toHaveAttribute('placeholder', 'Ask a research question. DEIXIS searches, screens, reads and links every claim to a passage.')
    await expect(page.locator('.models-summary')).toContainText('fixture-model')
    const left = async (locator: ReturnType<typeof page.locator>) => (await locator.boundingBox())!.x
    const add = await left(page.getByLabel('Add sources'))
    const models = await left(page.locator('.models-summary'))
    const depth = await left(page.getByLabel('Research depth'))
    const send = await left(page.getByRole('button', { name: 'Start research' }))
    expect(add).toBeLessThan(models)
    expect(models).toBeLessThan(depth)
    expect(depth).toBeLessThan(send)
    // The scope button sits in the band above the question.
    expect((await page.getByLabel('Source scope').boundingBox())!.y).toBeLessThan((await question.boundingBox())!.y)
    await expect(page.locator('.models-summary')).toHaveText(/^Models/)
    await expect(page.getByRole('button', { name: 'Start research' })).toBeDisabled()
    await expect(page.getByText('⌘ / Ctrl + Enter starts the research · ? shows shortcuts · Nothing is downloaded from paywalled sites')).toBeVisible()
    await expect(page.getByText('Connect a model to start')).toHaveCount(0)
  })

  test('scope menu: three workflows with descriptions and a disabled Systematic review', async ({ page }) => {
    await page.goto(server.url())
    await page.getByLabel('Source scope').click()
    await expect(page.getByText('Workflows', { exact: true })).toBeVisible()
    const options = page.getByRole('option')
    await expect(options).toHaveCount(4)
    await expect(options.nth(0)).toContainText('Academic search')
    await expect(options.nth(1)).toContainText('Attached files')
    await expect(options.nth(2)).toContainText('Files + academic search')
    // The descriptions word for word (COPY_CHANGES scope-academic, scope-attached-detail, scope-pdfs-academic; parity leaves them out of its text check).
    await expect(options.locator('small')).toHaveText([
      'Searches scholarly sources to answer your question.',
      'Only the PDFs and Zotero items you add; no search runs',
      'Searches using your PDFs and your question. Only included sources are used in the answer.',
      'Protocol, two reviewers, PRISMA flow',
    ])
    await expect(options.nth(3)).toContainText('Systematic review')
    await expect(options.nth(3)).toContainText('Later')
    await expect(options.nth(3)).toHaveAttribute('aria-disabled', 'true')
    await options.nth(2).click()
    await expect(page.getByLabel('Source scope')).toContainText('Files + academic search')
  })

  test('add menu: upload, Zotero, and two disabled later rows; no library row', async ({ page }) => {
    await page.goto(server.url())
    await page.getByLabel('Add sources').click()
    const items = page.getByRole('menuitem')
    await expect(items).toHaveCount(4)
    await expect(items.nth(0)).toContainText('Upload PDF')
    await expect(items.nth(1)).toContainText('Zotero collection')
    // The descriptions word for word (COPY_CHANGES add-upload-detail, add-zotero-detail); the Later rows have none.
    await expect(items.locator('small')).toHaveText([
      'From this computer, up to 50 MB each. You can also drop files here.',
      'Read-only, from Zotero on this computer or zotero.org. Imported when the research starts.',
    ])
    await expect(items.nth(2)).toContainText('Import BibTeX or RIS')
    await expect(items.nth(2)).toContainText('Later')
    await expect(items.nth(2)).toHaveAttribute('aria-disabled', 'true')
    await expect(items.nth(3)).toContainText('Add by DOI')
    await expect(items.nth(3)).toHaveAttribute('aria-disabled', 'true')
    await expect(page.getByText('Add from library')).toHaveCount(0)
  })

  test('models menu: one row per role with model and effort; a row opens that role picker', async ({ page }) => {
    await page.goto(server.url())
    await expect(page.locator('.models-summary')).toContainText('fixture-model')
    await page.locator('.models-summary').click()
    await expect(page.getByText('Models', { exact: true }).last()).toBeVisible()
    const items = page.getByRole('menuitem')
    await expect(items).toHaveCount(4)
    await expect(items.nth(0)).toContainText('Literature')
    await expect(items.nth(0)).toContainText('fixture-model')
    await expect(items.nth(1)).toContainText('Answer')
    await expect(items.nth(1)).toContainText('fixture-model')
    await expect(items.nth(2)).toContainText('Reviewer')
    await expect(items.nth(3)).toContainText('Change the defaults in Settings')
    await items.nth(1).click()
    await expect(page.getByRole('combobox', { name: /Search models or providers/ })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('button', { name: 'Answer model' })).toBeVisible()
  })

  test('depth menu lists the three depths with minutes and papers', async ({ page }) => {
    await page.goto(server.url())
    await page.getByLabel('Research depth').click()
    await expect(page.getByText('Depth', { exact: true })).toBeVisible()
    const options = page.getByRole('option')
    await expect(options).toHaveCount(3)
    for (const [i, name] of ['Quick', 'Standard', 'Detailed'].entries()) {
      await expect(options.nth(i)).toContainText(name)
      await expect(options.nth(i)).toContainText(/About \d+ min · up to \d+ papers/)
    }
    await options.nth(2).click()
    await expect(page.getByLabel('Research depth')).toContainText('Detailed')
  })

  test('phone: the file row comes first and the control row wraps', async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } })
    const page = await context.newPage()
    try {
      await page.goto(server.url())
      await expect(page.locator('.models-summary')).toContainText('fixture-model')
      await page.locator('input[type=file]').first().setInputFiles({ name: 'phone-check.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\n%%EOF\n') })
      const chips = await page.locator('.attachments').boundingBox()
      const add = await page.getByLabel('Add sources').boundingBox()
      expect(chips!.y).toBeLessThan(add!.y)
      const box = await page.locator('.composer').boundingBox()
      for (const target of [page.getByLabel('Research depth'), page.locator('.models-summary'), page.getByRole('button', { name: 'Start research' })]) {
        const b = (await target.boundingBox())!
        expect(b.x + b.width).toBeLessThanOrEqual(box!.x + box!.width + 1)
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    } finally { await context.close() }
  })
})
