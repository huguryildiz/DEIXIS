import { expect, test, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'

// The jobs sheet (parity S1, plan S13): an open sheet stays when its last job ends, and shows how it ended from stored
// state only. The research list, the research view and the equation model are SYNTHETIC route answers that change
// while the sheet is open; a passing case shows the sheet's states, not real PDF work.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')

class Server {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-jobs-'))
  readonly port = nextPort()
  url() { return `http://127.0.0.1:${this.port}/` }
  async start() {
    const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend') }
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`${this.url()}api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`jobs fixture server on ${this.port} did not start`)
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
}

const MODEL_BASE = { switch: 'on', ready: true, reason: null, model: { connection: 'openai', model: 'syn-model', reasoning_effort: null }, model_refused: false, mathpix_first: false,
  monthly_budget: 500, month_requests: 3, per_pdf_limit: 60, month_cost: { usd: 0, calls_without_cost: 0 } }
const READING = { ...MODEL_BASE, reading: { asset_id: 'ast_jobs', title: 'SYNTHETIC library PDF', pages: 3, started_at: new Date().toISOString(), route: 'model' }, pdfs: { read: 4, reading: 1, pending: 1 } }
const READ_ALL = { ...MODEL_BASE, reading: null, pdfs: { read: 5, no_math: 1, failed: 0 } }
const NO_READER = { ...MODEL_BASE, ready: false, reason: 'no_answer_model', model: null, reading: null, pdfs: {} }

const now = new Date().toISOString()
const summary = (status: string) => ({
  id: 'res_jobs', title: 'SYNTHETIC OCR research', question: 'SYNTHETIC question about OCR?', version: 1, source_scope: 'academic', effort: 'standard',
  last_run_status: status, last_run_kind: 'pdf_ocr', answer_count: 0, followup_new: 0, created_at: now, updated_at: now, awaiting: { queue: 0, pdf: 0 }, intent: 'report',
})
const view = (status: string) => ({
  runs: [{ id: 'run_jobs', kind: 'pdf_ocr', status, steps: [
    { kind: 'ocr_pages', status: 'succeeded', operation_key: 'ocr_pages:run_jobs', output: { image_pages: [1, 2, 3] } },
    { kind: 'ocr_page', status: 'succeeded', operation_key: 'ocr_page:1', output: null },
  ] }],
  sources: [],
})

const server = new Server()
test.beforeAll(async () => { await server.start() })
test.afterAll(async () => { await server.stop() })

async function openSheet(page: Page) {
  await page.goto(server.url())
  await page.locator('.sidebar-foot .bgcard').click()
  await expect(page.locator('.jobs-sheet')).toBeVisible()
}

const UNKNOWN = 'Background work could not be read; its status is unknown.'

// The sheet after its only job has left the list: no card in the sidebar, the sheet still open, and "Nothing is
// running" only when every read answered (otherwise the unknown sentence).
async function expectEnded(page: Page, readsAnswered = true) {
  await expect(page.locator('.sidebar-foot .bgcard')).toHaveCount(0, { timeout: 15_000 })
  await expect(page.locator('.jobs-sheet')).toBeVisible()
  await expect(page.locator('.jobs-sheet')).toContainText(readsAnswered ? 'Nothing is running.' : UNKNOWN)
  await expect(page.locator('.jobs-sheet')).not.toContainText(readsAnswered ? UNKNOWN : 'Nothing is running.')
}

test('the equation reading finishes while the sheet is open: it stays, with the read, no-equation and failed counts under Finished', async ({ page }) => {
  let reader: object = READING
  await page.route('**/api/equation-model', route => route.fulfill({ json: reader }))
  await openSheet(page)
  await expect(page.locator('.jobs-sheet .job')).toContainText('Reading equations')
  reader = READ_ALL
  await expectEnded(page)
  const done = page.locator('.jobs-sheet .job', { hasText: 'Reading equations' })
  await expect(page.locator('.jobs-sheet h3')).toHaveText(['Finished'])
  await expect(done).toContainText('5 read · 1 without equations · 0 failed')
  await expect(done.locator('svg.lucide-check')).toHaveCount(1)
})

test('the equation model cannot be read any more: the sheet stays and the job is "Status unknown", never finished', async ({ page }) => {
  let failing = false
  await page.route('**/api/equation-model', route => failing ? route.fulfill({ status: 500, json: { detail: 'SYNTHETIC failure' } }) : route.fulfill({ json: READING }))
  await openSheet(page)
  failing = true
  await expectEnded(page, false)
  await expect(page.locator('.jobs-sheet h3')).toHaveText(['Not confirmed as finished'])
  await expect(page.locator('.jobs-sheet .job', { hasText: 'Reading equations' })).toContainText('Status unknown')
  await expect(page.locator('.jobs-sheet svg.lucide-check')).toHaveCount(0)
})

test('an OCR run fails while the sheet is open: its own run status is shown as Failed, not Finished', async ({ page }) => {
  let status = 'running'
  await page.route('**/api/equation-model', route => route.fulfill({ json: NO_READER }))
  await page.route('**/api/researches', route => route.fulfill({ json: [summary(status)] }))
  await page.route('**/api/researches/res_jobs', route => route.fulfill({ json: view(status) }))
  await openSheet(page)
  await expect(page.locator('.jobs-sheet .job')).toContainText('1 of 3 pages')
  status = 'failed'
  await expectEnded(page)
  await expect(page.locator('.jobs-sheet h3')).toHaveText(['Not confirmed as finished'])
  await expect(page.locator('.jobs-sheet .job', { hasText: 'Reading with OCR' })).toContainText('Failed')
  // Closing the sheet hands focus to the sidebar's Search, since the card that opened it has gone.
  await page.keyboard.press('Escape')
  await expect(page.locator('.jobs-sheet')).toHaveCount(0)
  await expect(page.locator('.sidebar-find')).toBeFocused()
})

test('the research view cannot be read while an OCR run is listed: the sheet says the state is unknown, not that nothing runs', async ({ page }) => {
  let failing = false
  await page.route('**/api/equation-model', route => route.fulfill({ json: NO_READER }))
  await page.route('**/api/researches', route => route.fulfill({ json: [summary('running')] }))
  await page.route('**/api/researches/res_jobs', route => failing ? route.fulfill({ status: 500, json: { detail: 'SYNTHETIC failure' } }) : route.fulfill({ json: view('running') }))
  await openSheet(page)
  await expect(page.locator('.jobs-sheet .job')).toContainText('1 of 3 pages')
  failing = true
  await expectEnded(page, false)
  await expect(page.locator('.jobs-sheet .job', { hasText: 'Reading with OCR' })).toContainText('Status unknown')
  await expect(page.locator('.jobs-sheet svg.lucide-check')).toHaveCount(0)
})

test('a sidebar collapsed on the desktop still shows the background card in the phone drawer', async ({ page }) => {
  await page.route('**/api/equation-model', route => route.fulfill({ json: READING }))
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto(server.url())
  await expect(page.locator('.sidebar-foot .bgcard')).toBeVisible()
  await page.getByRole('button', { name: 'Collapse sidebar' }).click()
  await expect(page.locator('.sidebar-foot .bgcard')).toBeHidden()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Open navigation' }).click()
  await expect(page.locator('.sidebar-foot .bgcard')).toBeVisible()
  await expect(page.locator('.sidebar-foot .bgcard')).toContainText('Reading equations')
})
