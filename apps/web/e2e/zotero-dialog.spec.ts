import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'

// Parity slice S6: the Home Zotero dialog (H17). The fixture server has no Zotero, so the collection list and the import
// answer are routed in the page; every collection is SYNTHETIC. This shows the dialog's layout, wiring and keyboard
// behaviour, not access to a real Zotero library.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
mkdirSync(path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance'), { recursive: true })

const COLLECTIONS = [
  { key: 'SYNA', name: 'SYNTHETIC UWSN reliability', items: 24, parent: null },
  { key: 'SYNB', name: 'SYNTHETIC UWSN reliability / k-connectivity', items: 11, parent: 'SYNA' },
  { key: 'SYNG', name: 'SYNTHETIC UWSN reliability / k-connectivity / Bounds', items: 1, parent: 'SYNB' },
  { key: 'SYND', name: 'SYNTHETIC IRS and RIS', items: 31, parent: null },
  { key: 'SYNE', name: 'SYNTHETIC Quantum networks', items: null, parent: null },
  { key: 'SYNZ', name: 'SYNTHETIC Empty', items: 0, parent: null },
]

class HomeServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-zotero-dialog-'))
  constructor(readonly port: number) {}
  async start() {
    const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend') }
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`http://127.0.0.1:${this.port}/api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`zotero dialog fixture server on ${this.port} did not start`)
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
  url() { return `http://127.0.0.1:${this.port}/` }
}

async function routeCollections(page: Page, web: { status: number; body: unknown } = { status: 200, body: { source: 'web', collections: [] } }) {
  await page.route('**/api/zotero/collections**', route => {
    const source = new URL(route.request().url()).searchParams.get('source')
    if (source === 'web') return route.fulfill({ status: web.status, json: web.body })
    return route.fulfill({ json: { source: 'local', collections: COLLECTIONS } })
  })
}

async function openDialog(page: Page) {
  await page.getByLabel('Add sources').click()
  await page.getByRole('menuitem', { name: /Zotero collection/ }).click()
  const dialog = page.getByRole('dialog', { name: 'Import from Zotero' })
  await expect(dialog).toBeVisible()
  await expect(dialog.locator('.zotero-cols label')).toHaveCount(COLLECTIONS.length)
  return dialog
}

test.describe.serial('S6: Zotero dialog on Home', () => {
  const server = new HomeServer(nextPort())
  test.beforeAll(async () => { await server.start() })
  test.afterAll(async () => { await server.stop() })

  test('collections with counts, sub-collections indented under their parent, an unknown count shows no number', async ({ page }) => {
    await routeCollections(page)
    await page.goto(server.url())
    const dialog = await openDialog(page)
    const rows = dialog.locator('.zotero-cols label')
    // Parents first, each followed by its sub-collections; under a parent only the collection's own name.
    await expect(rows.locator('.zotero-col-name')).toHaveText(['SYNTHETIC UWSN reliability', 'k-connectivity', 'Bounds', 'SYNTHETIC IRS and RIS', 'SYNTHETIC Quantum networks', 'SYNTHETIC Empty'])
    await expect(rows.nth(0).locator('em')).toHaveText('24 items')
    await expect(rows.nth(1).locator('em')).toHaveText('11 items')
    await expect(rows.nth(2).locator('em')).toHaveText('1 item')
    await expect(rows.nth(4).locator('em')).toHaveCount(0)
    await expect(rows.nth(4)).not.toContainText(/\d/)
    await expect(rows.nth(5).locator('em')).toHaveText('0 items')
    const x = async (i: number) => (await rows.nth(i).locator('svg').boundingBox())!.x
    expect(await x(1)).toBeGreaterThan(await x(0))
    expect(await x(2)).toBeGreaterThan(await x(1))
    expect(await x(3)).toBe(await x(0))
    await expect(rows.nth(1)).toHaveClass(/sub/)
    await expect(rows.nth(3)).not.toHaveClass(/sub/)
    // The first collection is chosen; the button carries its count, none when the count is unknown, and 0 cannot import.
    const primary = dialog.locator('.zotero-dialog-primary')
    await expect(dialog.getByRole('radio', { name: /SYNTHETIC UWSN reliability/ })).toBeChecked()
    await expect(primary).toHaveText('Import 24 items')
    await dialog.getByRole('radio', { name: /k-connectivity/ }).check()
    await expect(primary).toHaveText('Import 11 items')
    await dialog.getByRole('radio', { name: /Bounds/ }).check()
    await expect(primary).toHaveText('Import 1 item')
    await dialog.getByRole('radio', { name: /Quantum networks/ }).check()
    await expect(primary).toHaveText('Import items')
    await expect(primary).toBeEnabled()
    await dialog.getByRole('radio', { name: /Empty/ }).check()
    await expect(primary).toHaveText('Import 0 items')
    await expect(primary).toBeDisabled()
    await expect(dialog).toContainText('Choose a collection. DEIXIS reads its own items (not its sub-collections) and each item’s first readable PDF; it never changes your Zotero library.')
    await expect(dialog).toContainText('Reads Zotero on this computer through its local API · read-only. Counts are Zotero’s own; standalone notes and non-PDF attachments are skipped, so fewer items may be added. Items are imported when the research starts and join it as included sources.')
    const axe = await new AxeBuilder({ page }).include('.zotero-dialog').analyze()
    expect(axe.violations.filter(v => v.impact === 'serious' || v.impact === 'critical').map(v => `${v.id}: ${v.help}`)).toEqual([])
  })

  test('Escape closes, focus returns to Add sources; Tab stays inside the dialog; Cancel closes too', async ({ page }) => {
    await routeCollections(page)
    await page.goto(server.url())
    const dialog = await openDialog(page)
    expect(await dialog.evaluate(el => el.contains(document.activeElement))).toBe(true)
    // Six stops (Close, the two library buttons, the chosen radio, Cancel, Import): twelve presses wrap twice.
    for (let i = 0; i < 12; i++) {
      await page.keyboard.press('Tab')
      await page.waitForTimeout(25)  // a Base UI focus guard at the edge forwards focus into the dialog
      expect(await dialog.evaluate(el => el.contains(document.activeElement)), `Tab ${i + 1} stayed inside`).toBe(true)
    }
    // Arrow keys move the choice inside the radio group.
    await dialog.getByRole('radio', { name: /SYNTHETIC UWSN reliability/ }).focus()
    await page.keyboard.press('ArrowDown')
    await expect(dialog.getByRole('radio', { name: /k-connectivity/ })).toBeChecked()
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    await expect(page.getByLabel('Add sources')).toBeFocused()
    await openDialog(page)
    await page.getByRole('button', { name: 'Cancel' }).click()
    await expect(page.getByRole('dialog', { name: 'Import from Zotero' })).toHaveCount(0)
    await expect(page.locator('.attachment-chip')).toHaveCount(0)
  })

  test('zotero.org not configured shows the server message; an empty library offers Check again', async ({ page }) => {
    const message = 'The zotero.org library is not set up.'
    await routeCollections(page, { status: 422, body: { detail: message } })
    await page.goto(server.url())
    const dialog = await openDialog(page)
    await dialog.getByRole('button', { name: 'zotero.org' }).click()
    await expect(dialog.getByRole('button', { name: 'zotero.org' })).toHaveAttribute('aria-pressed', 'true')
    await expect(dialog).toContainText(message)
    await expect(dialog.locator('.zotero-dialog-primary')).toHaveText('Import items')
    await expect(dialog.locator('.zotero-dialog-primary')).toBeDisabled()
    await expect(dialog).toContainText('Reads your zotero.org library · read-only.')
    await page.unroute('**/api/zotero/collections**')
    await routeCollections(page, { status: 200, body: { source: 'web', collections: [] } })
    await dialog.getByRole('button', { name: 'Zotero on this computer' }).click()
    await expect(dialog.locator('.zotero-cols label')).toHaveCount(COLLECTIONS.length)
    await dialog.getByRole('button', { name: 'zotero.org' }).click()
    await expect(dialog).toContainText('This library has no collections.')
    await expect(dialog.getByRole('button', { name: 'Check again' })).toBeVisible()
  })

  test('Import keeps the collection for the research: chip, scope, and the import request after the research is created', async ({ page }) => {
    await routeCollections(page)
    const imports: Array<{ source: string; collection_key: string }> = []
    await page.route('**/api/researches/*/zotero-imports', async route => {
      imports.push(route.request().postDataJSON())
      const id = new URL(route.request().url()).pathname.split('/')[3]
      const view = await (await page.request.get(`${server.url()}api/researches/${id}`)).json()
      await route.fulfill({ status: 201, json: { ...view, zotero_import: { items: 11, pdfs_added: 0, notes: [] } } })
    })
    await page.goto(server.url())
    await expect(page.locator('.models-summary')).toContainText('fixture-model')
    const dialog = await openDialog(page)
    await dialog.getByRole('radio', { name: /k-connectivity/ }).check()
    await dialog.getByRole('button', { name: 'Import 11 items' }).click()
    await expect(dialog).toHaveCount(0)
    await expect(page.locator('.attachment-chip')).toContainText('SYNTHETIC UWSN reliability / k-connectivity')
    await expect(page.getByLabel('Source scope')).toContainText('Files + academic search')
    await expect(page.getByLabel('Add sources')).toBeFocused()
    // Reopening keeps the choice.
    const again = await openDialog(page)
    await expect(again.getByRole('radio', { name: /k-connectivity/ })).toBeChecked()
    await page.keyboard.press('Escape')
    expect(imports).toEqual([])
    await page.getByLabel('Research question').fill('SYNTHETIC How is k-connectivity modelled in underwater sensor networks?')
    await page.getByRole('button', { name: 'Start research' }).click()
    await expect(page).toHaveURL(/#\/research\//, { timeout: 60_000 })
    expect(imports).toEqual([{ source: 'local', collection_key: 'SYNB' }])
  })
})
