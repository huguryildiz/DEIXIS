import { expect, request as apiRequest, test, type Page } from '@playwright/test'
import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

// Case K: the works of an sw research waiting for the person's PDF (slice 18a). A work no route found a PDF for is
// listed in reading order with its DOI link; the person drops a publisher file, the match names the work by its DOI,
// the person picks the version and confirms, and the work leaves the list.
//
// Its own fixture server, with retrieval and reading on (DEIXIS_FIXTURE_QUEUE) and one more SYNTHETIC work that has no
// open copy (DEIXIS_FIXTURE_WAITING). A passing case shows application behavior; it does not show that a publisher's
// file names its DOI, and no institution proxy is involved (not tried: no institutional account).

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

const PORT = 8783
const URL = `http://127.0.0.1:${PORT}`
const QUESTION = 'How do SYNTHETIC molecular relays and greenhouse irrigation schedule their releases?'
const WAITING_TITLE = 'SYNTHETIC release timing of molecular relays in closed channels'
const ENV = { DEIXIS_SEARCH_WORKFLOW: 'sw', DEIXIS_PROTOCOL_APPROVAL: 'as_proposed', DEIXIS_FIXTURE_QUEUE: 'on', DEIXIS_FIXTURE_WAITING: 'on' }

const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`), animations: 'disabled', fullPage: true })
const rows = (page: Page) => page.getByRole('list', { name: 'Works waiting for your PDF, in reading order' })

// Drops a file on the drop zone the way a browser does, with a DataTransfer holding the PDF.
async function dropFile(page: Page, file: string, name: string) {
  const b64 = readFileSync(file).toString('base64')
  const dataTransfer = await page.evaluateHandle(({ b64, name }) => {
    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0))
    const dt = new DataTransfer()
    dt.items.add(new File([bytes], name, { type: 'application/pdf' }))
    return dt
  }, { b64, name })
  await page.getByTestId('waiting-drop').dispatchEvent('drop', { dataTransfer })
}

test.describe.serial('K: the works waiting for the person’s PDF', () => {
  let proc: ChildProcess | undefined
  let rid = ''
  let page: Page
  const dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-waiting-'))
  const publisherPdf = path.join(dataDir, 'q955-publisher.pdf')

  test.beforeAll(async ({ browser }) => {
    const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend'), ...ENV }
    expect(spawnSync(PYTHON, [SERVER, '--data-dir', dataDir, '--port', String(PORT), '--write-waiting-pdf', publisherPdf], { cwd: REPO, env }).status).toBe(0)
    proc = spawn(PYTHON, [SERVER, '--data-dir', dataDir, '--port', String(PORT)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`${URL}/api/health`)).ok) break } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    const api = await apiRequest.newContext({ baseURL: URL, extraHTTPHeaders: { origin: URL } })
    const token = (await (await api.get('/api/session')).json()).csrf_token as string
    const headers = { 'x-deixis-csrf': token }
    const created = await api.post('/api/researches', { data: { question: QUESTION, model_connection: 'codex', requested_model: 'fixture-model', effort: 'quick' }, headers })
    expect(created.status()).toBe(201)
    rid = (await created.json()).research.id
    expect((await api.post(`/api/researches/${rid}/runs`, { data: { kind: 'discovery' }, headers })).ok()).toBe(true)
    // Discovery (with the fetch inside it) and the reading run settle; the list is read after that.
    await expect.poll(async () => {
      const view = await (await api.get(`/api/researches/${rid}`)).json()
      return view.runs.some((r: { kind: string; status: string }) => r.kind === 'fulltext_adjudication' && r.status === 'completed')
    }, { timeout: 90_000 }).toBe(true)
    const waiting = await (await api.get(`/api/researches/${rid}/waiting`)).json()
    if (!waiting.rows.some((r: { title: string }) => r.title === WAITING_TITLE)) throw new Error('fixture failure: the work with no open copy is not waiting')
    await api.dispose()
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  })
  test.afterAll(async () => {
    await page?.close()
    if (proc && proc.exitCode === null) { const exited = new Promise(resolve => proc!.once('exit', resolve)); proc.kill('SIGTERM'); await exited }
  })

  test('a waiting work is listed in reading order with its DOI link, at desktop and phone width', async () => {
    await page.goto(`${URL}/#/research/${rid}`)
    const tab = page.getByRole('tab', { name: /^Waiting for your PDF/ })
    await expect(tab).toHaveText(/1$/)
    await tab.click()
    await expect(page.getByRole('heading', { name: '1 work waits for your PDF' })).toBeVisible()
    const row = rows(page).getByRole('listitem').filter({ hasText: WAITING_TITLE })
    await expect(row).toContainText('No open copy was found by any route.')
    const doi = row.getByRole('link', { name: /DOI/ })
    await expect(doi).toHaveAttribute('href', 'https://doi.org/10.5555/q955')
    await expect(doi).toHaveAttribute('target', '_blank')
    await expect(doi).toHaveAttribute('rel', 'noopener noreferrer')
    await expect(page.getByText('Links open directly.')).toBeVisible()
    await shot(page, 'K-waiting-list-1440')
  })

  test('at 390 px the row and a dropped file’s version choice fit the width', async ({ browser }) => {
    const narrow = await browser.newPage({ viewport: { width: 390, height: 844 } })
    try {
      await narrow.goto(`${URL}/#/research/${rid}/waiting`)
      await expect(rows(narrow).getByRole('listitem').filter({ hasText: WAITING_TITLE })).toBeVisible()
      await shot(narrow, 'K-waiting-list-390')
      await dropFile(narrow, publisherPdf, 'q955-publisher.pdf')
      const panel = narrow.getByRole('group', { name: 'Where q955-publisher.pdf goes' })
      await expect(panel.getByRole('radio')).toHaveCount(1)
      const overflow = await narrow.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(overflow).toBeLessThanOrEqual(1)
      await shot(narrow, 'K-waiting-match-390')
      // Nothing was confirmed on this page: the file goes nowhere and the work still waits.
      await panel.getByRole('button', { name: 'Do not attach' }).click()
      await expect(panel).toHaveCount(0)
    } finally { await narrow.close() }
  })

  test('a dropped file is matched by its DOI, the person picks the version and confirms, and the work leaves the list', async () => {
    await page.goto('about:blank')
    await page.goto(`${URL}/#/research/${rid}/waiting`)
    const tab = page.getByRole('tab', { name: /^Waiting for your PDF/ })
    await expect(rows(page)).toBeVisible()
    await dropFile(page, publisherPdf, 'q955-publisher.pdf')
    const panel = page.getByRole('group', { name: 'Where q955-publisher.pdf goes' })
    await expect(panel).toContainText('Its first pages name this work’s DOI.')
    await expect(panel).toContainText(WAITING_TITLE)
    await expect(panel).toContainText('2 pages')
    const attach = panel.getByRole('button', { name: 'Attach to this version' })
    // The version is the person's to pick: nothing is chosen for them, so the confirmation waits.
    await expect(attach).toBeDisabled()
    await expect(panel.getByRole('radio')).toHaveCount(1)
    await expect(panel.getByRole('radio')).not.toBeChecked()
    await shot(page, 'K-waiting-match-1440')
    await panel.getByRole('radio').check()
    await attach.click()

    await expect(page.getByText('PDF attached to the version you chose.', { exact: false })).toBeVisible()
    await expect(panel).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'No work waits for your PDF' })).toBeVisible()
    await expect(tab).toHaveText(/0$/)
    await shot(page, 'K-waiting-empty-1440')
  })
})
