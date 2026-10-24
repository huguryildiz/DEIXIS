import { expect, request as apiRequest, test, type Page } from '@playwright/test'
import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort, readingDone } from './ports'
import { expectMenuCount, openPanel } from './panels'

// Case K: the works of an sw research waiting for the person's PDF (slice 18a). A work no route found a PDF for is
// listed in reading order with its DOI link; the person drops a publisher file, the match names the work by its DOI,
// the person picks the version and confirms, and the work leaves the list.
//
// Case L continues from K's end (slice 18b): the confirmed file waits, the scripted model reads it first, and "Your
// files" shows it included with the quote code found on its page. Its failure script ("[read-fails]", a second
// research on the same server) leaves the file unread until the person asks for it to be read again.
//
// Its own fixture server, with retrieval and reading on (DEIXIS_FIXTURE_QUEUE) and one more SYNTHETIC work that has no
// open copy (DEIXIS_FIXTURE_WAITING). A passing case shows application behavior; it does not show that a publisher's
// file names its DOI, that a model reads a publisher's file well, and no institution proxy is involved (not tried: no
// institutional account).

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

const PORT = nextPort()
const URL = `http://127.0.0.1:${PORT}`
const QUESTION = 'How do SYNTHETIC molecular relays and greenhouse irrigation schedule their releases?'
const WAITING_TITLE = 'SYNTHETIC release timing of molecular relays in closed channels'
const ENV = { DEIXIS_SEARCH_WORKFLOW: 'sw', DEIXIS_FIXTURE_QUEUE: 'on', DEIXIS_FIXTURE_WAITING: 'on' }

// Starts a fixture server on `port` over a fresh data directory and waits until it answers.
async function startServer(dataDir: string, port: number, publisherPdf: string) {
  const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend'), ...ENV }
  expect(spawnSync(PYTHON, [SERVER, '--data-dir', dataDir, '--port', String(port), '--write-waiting-pdf', publisherPdf], { cwd: REPO, env }).status).toBe(0)
  const proc = spawn(PYTHON, [SERVER, '--data-dir', dataDir, '--port', String(port)], { cwd: REPO, env, stdio: 'inherit' })
  for (let i = 0; i < 150; i++) {
    try { if ((await fetch(`http://127.0.0.1:${port}/api/health`)).ok) break } catch { /* not listening yet */ }
    await new Promise(resolve => setTimeout(resolve, 200))
  }
  return proc
}

const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`), animations: 'disabled', fullPage: true })
const rows = (page: Page) => page.getByRole('list', { name: 'Works waiting for your PDF, in reading order' })
const fileRow = (page: Page) => page.getByRole('list', { name: 'Files you added' }).getByRole('listitem').filter({ hasText: WAITING_TITLE }).first()

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

// Creates a research on the server at `base`, runs its discovery and waits for the reading run that follows it.
async function readyResearch(base: string, question: string) {
  const api = await apiRequest.newContext({ baseURL: base, extraHTTPHeaders: { origin: base } })
  const token = (await (await api.get('/api/session')).json()).csrf_token as string
  const headers = { 'x-deixis-csrf': token }
  const created = await api.post('/api/researches', { data: { question, model_connection: 'codex', requested_model: 'fixture-model', effort: 'quick' }, headers })
  expect(created.status()).toBe(201)
  const id = (await created.json()).research.id as string
  expect((await api.post(`/api/researches/${id}/runs`, { data: { kind: 'discovery' }, headers })).ok()).toBe(true)
  await expect.poll(async () => {
    const view = await (await api.get(`/api/researches/${id}`)).json()
    return readingDone(view)
  }, { timeout: 90_000 }).toBe(true)
  await api.dispose()
  return id
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
      return readingDone(view)
    }, { timeout: 90_000 }).toBe(true)
    const waiting = await (await api.get(`/api/researches/${rid}/waiting`)).json()
    if (!waiting.rows.some((r: { title: string }) => r.title === WAITING_TITLE)) throw new Error('fixture failure: the work with no open copy is not waiting')
    await api.dispose()
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  })
  test.afterAll(async () => {
    await page?.close()
    if (proc && proc.exitCode === null) { const exited = new Promise(resolve => proc!.once('exit', resolve)); proc.kill('SIGTERM'); await exited }
    rmSync(dataDir, { recursive: true, force: true })
  })

  test('a waiting work is listed in reading order with its DOI link, at desktop and phone width', async () => {
    await page.goto(`${URL}/#/research/${rid}`)
    await expectMenuCount(page, 'pdfs', 1)
    await openPanel(page, 'pdfs')
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

  test('"Open all links" opens each waiting row’s DOI link in its own tab, only with more than one row (SYNTHETIC API state)', async () => {
    // The fixture lists one work; a second row is added to the response here, so the button appears.
    const waitingApi = /\/api\/researches\/[^/]+\/waiting$/
    await page.route(waitingApi, async route => {
      const body = await (await route.fetch()).json()
      const copy = { ...body.rows[0], work_id: 'wrk_synthetic_second', title: 'SYNTHETIC second waiting work', links: { doi: 'https://doi.org/10.5555/q956', landing: null } }
      await route.fulfill({ json: { ...body, rows: [...body.rows, copy] } })
    })
    const opened: string[] = []
    page.context().on('page', tab => { opened.push(tab.url()) })  // listening before the page loads: a tab opened on load counts
    await page.context().route(/doi\.org/, route => route.fulfill({ body: '' }))
    await page.goto(`${URL}/#/research/${rid}`)
    await page.reload()
    await openPanel(page, 'pdfs')
    await expect(page.getByRole('button', { name: 'Open all 2 links' })).toBeVisible()
    expect(opened).toEqual([])  // nothing opens before the click
    await page.getByRole('button', { name: 'Open all 2 links' }).click()
    await expect.poll(() => opened.length).toBe(2)
    expect(new Set(opened).size).toBe(2)  // one tab per row, each its own link
    expect(opened).toContain('https://doi.org/10.5555/q956')
    await page.unroute(waitingApi)
    for (const tab of page.context().pages()) if (tab !== page) await tab.close()
    await shot(page, 'K-waiting-open-all-1440')
  })

  test('with no reading plan yet, the drop zone opens while a file has a work to go to (SYNTHETIC API state)', async () => {
    // Sol S14 round 1: the zone follows the backend's attach candidates, not the plan alone.
    for (const [candidates, zones] of [[1, 1], [0, 0]] as const) {
      await page.route(`**/api/researches/${rid}/waiting`, async route => {
        const response = await route.fetch()
        const body = await response.json()
        await route.fulfill({ response, json: { ...body, rows: [], count: 0, has_plan: false, attach_candidates: candidates } })
      })
      await page.goto('about:blank')
      await page.goto(`${URL}/#/research/${rid}/waiting`)
      // With no plan the empty box's head says the retrieval has not run (94b25138: the box is one line, its head).
      await expect(page.getByRole('heading', { name: 'The full-text retrieval has not run for this question yet.' })).toBeVisible()
      await expect(page.getByTestId('waiting-drop')).toHaveCount(zones)
      await page.unroute(`**/api/researches/${rid}/waiting`)
    }
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
    await expectMenuCount(page, 'pdfs', 0)
    await shot(page, 'K-waiting-empty-1440')
  })

  test('L: the confirmed file waits, is read by the model first, and is shown included with its quote', async () => {
    const row = fileRow(page)
    await expect(page.getByRole('heading', { name: 'Your files' })).toBeVisible()
    // The reading run was opened with the attach; the scripted model takes a few seconds a call on this file.
    await expect(row).toContainText(/Waiting to be read|The model is reading it…/)
    await expect(row).toContainText('The model is reading it…', { timeout: 15_000 })
    await shot(page, 'L-your-files-reading-1440')
    await expect(row).toContainText('Included: both readings found every required part of the criterion', { timeout: 30_000 })
    const quotes = row.getByRole('list', { name: 'Quotes code found on their pages' })
    await expect(quotes).toContainText('PDF p. 1')
    await expect(quotes).toContainText('Journal of Relay Studies')
    await expect(page.getByText('whether it supports the criterion is not checked', { exact: false })).toBeVisible()
    await shot(page, 'L-your-files-included-1440')
  })

  test('L: the search phase counts the included works beside their source, and the signals are too few to judge', async ({ browser }) => {
    // Slice 19: the included count on the screen is the one the view derives; no work was confirmed by a person.
    const api = await apiRequest.newContext({ baseURL: URL, extraHTTPHeaders: { origin: URL } })
    const view = await (await api.get(`/api/researches/${rid}`)).json()
    await api.dispose()
    const included = view.probes.included_by_agreement as number
    expect(included).toBeGreaterThan(0)
    expect(view.probes.verified).toBe(0)
    for (const width of [1440, 390]) {
      const tab = width === 1440 ? page : await browser.newPage({ viewport: { width, height: 844 } })
      try {
        await tab.goto('about:blank')
        await tab.goto(`${URL}/#/research/${rid}`)
        const toggle = tab.getByRole('button', { name: /Ran search & screening/ })
        if ((await toggle.getAttribute('aria-expanded')) !== 'true') await toggle.click()
        const turn = tab.locator('.chat-turn').filter({ has: toggle })
        await turn.locator('.chat-step-line', { hasText: /^Searched / }).click()
        const arms = turn.locator('.chat-arms').first()
        await expect(arms).toContainText(/\d+ included by two agreeing runs/)
        await expect(arms).not.toContainText('no other source’s search found')
        await expect(arms.locator('li', { hasText: 'Keywords' })).toContainText(`${included} included,`)
        await expect(arms).not.toContainText('Full text not read yet')
        await turn.locator('.chat-step-line', { hasText: /^Screened / }).click()
        await expect(turn).toContainText('Your confirmed works in this ranking: 0')
        await expect(turn).toContainText('Too few to judge a signal by (fewer than 30).')
        await expect(turn).toContainText('their places are not a signal’s success')
        const overflow = await tab.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
        expect(overflow).toBeLessThanOrEqual(1)
        await shot(tab, `L-arms-signals-${width}`)
      } finally { if (tab !== page) await tab.close() }
    }
  })

  test('L: at 390 px the included file and its quote fit the width', async ({ browser }) => {
    const narrow = await browser.newPage({ viewport: { width: 390, height: 844 } })
    try {
      await narrow.goto(`${URL}/#/research/${rid}/waiting`)
      await expect(fileRow(narrow)).toContainText('Included')
      await fileRow(narrow).scrollIntoViewIfNeeded()
      const overflow = await narrow.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(overflow).toBeLessThanOrEqual(1)
      await shot(narrow, 'L-your-files-included-390')
    } finally { await narrow.close() }
  })
})

// Case L's failure script: its own server, so the SYNTHETIC work waits for the person's file in this research alone
// (a file is attached to the library's record, which K's research shares).
test.describe.serial('L failure: a reading that decides nothing', () => {
  const FAIL_PORT = nextPort()
  const FAIL_URL = `http://127.0.0.1:${FAIL_PORT}`
  let proc: ChildProcess | undefined
  let failing = ''
  let page: Page
  const dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-waiting-fail-'))
  const publisherPdf = path.join(dataDir, 'q955-publisher.pdf')

  test.beforeAll(async ({ browser }) => {
    proc = await startServer(dataDir, FAIL_PORT, publisherPdf)
    failing = await readyResearch(FAIL_URL, `${QUESTION} [read-fails]`)
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  })
  test.afterAll(async () => {
    await page?.close()
    if (proc && proc.exitCode === null) { const exited = new Promise(resolve => proc!.once('exit', resolve)); proc.kill('SIGTERM'); await exited }
    rmSync(dataDir, { recursive: true, force: true })
  })

  test('L failure: a reading that decides nothing leaves the file unread until the person asks again (readiness panel: SYNTHETIC API state)', async ({ browser }) => {
    await page.goto('about:blank')
    await page.goto(`${FAIL_URL}/#/research/${failing}/waiting`)
    await expect(rows(page)).toBeVisible()
    await dropFile(page, publisherPdf, 'q955-publisher.pdf')
    const panel = page.getByRole('group', { name: 'Where q955-publisher.pdf goes' })
    await panel.getByRole('radio').check()
    await expect(panel).toContainText('The model reads this file before the other works waiting to be read.')
    await panel.getByRole('button', { name: 'Attach to this version' }).click()
    const row = fileRow(page)
    await expect(row).toContainText('Not read.', { timeout: 30_000 })
    await expect(row).toContainText('The reading run ended without a decision on it.')
    const again = row.getByRole('button', { name: 'Read again' })
    await expect(again).toBeEnabled()
    await shot(page, 'L-your-files-unread-1440')

    // The person includes the work: the included-sources part of the Get more full text panel (S14) says its PDF is
    // theirs and not read yet, that the answer leaves it out until then, and offers no upload for it (its version
    // already holds the file).
    const api = await apiRequest.newContext({ baseURL: FAIL_URL, extraHTTPHeaders: { origin: FAIL_URL } })
    const token = (await (await api.get('/api/session')).json()).csrf_token as string
    const view = await (await api.get(`/api/researches/${failing}`)).json()
    const record = view.sources.find((s: { title: string; version_role: string }) => s.title === WAITING_TITLE && s.version_role === 'record')
    const included = await api.patch(`/api/researches/${failing}/selections/${record.source_version_id}`,
      { data: { state: 'included', expected_version: record.selection.version, reason: 'SYNTHETIC included by the person' }, headers: { 'x-deixis-csrf': token } })
    expect(included.ok()).toBe(true)
    await api.dispose()
    // The panel is read from this research's view served without its answers, so the answer button names the first
    // answer (SYNTHETIC API state).
    const withoutAnswers = (p: Page, change: (view: any) => void = () => {}) => p.route(`**/api/researches/${failing}`, async route => {
      const response = await route.fetch()
      const body = await response.json()
      body.answers = []
      change(body)
      await route.fulfill({ response, json: body })
    })
    const unreadInPanel = async (p: Page, name: string) => {
      await p.unroute(`**/api/researches/${failing}`)
      await withoutAnswers(p)
      await p.goto('about:blank')
      await p.goto(`${FAIL_URL}/#/research/${failing}/waiting`)
      const listed = p.getByRole('list', { name: 'Your PDF, not read yet' }).getByRole('listitem').filter({ hasText: WAITING_TITLE })
      // The reason is said once in the box's lede; each row carries a "Not read yet" pill with the full fact as its title (c0e25cd0).
      await expect(p.locator('section[aria-labelledby="pdf-unread-title"]')).toContainText('1 source has your PDF, not read yet. The answer leaves it out until the model reads it.')
      await expect(listed.locator('.pill.warn')).toHaveText('Not read yet')
      await expect(listed.locator('.pill.warn')).toHaveAttribute('title', 'Your PDF is attached and not read yet: the answer leaves this work out until the model reads it.')
      // The link goes to "Your files" further down the same panel.
      await expect(p.getByRole('link', { name: 'See it in Your files' })).toHaveAttribute('href', '#person-files-title')
      // Listed once, in its own group: not among the works that need a PDF, with no upload and no abstract fallback.
      await expect(listed).toHaveCount(1)
      await expect(listed.getByRole('button', { name: 'Upload PDF' })).toHaveCount(0)
      await expect(p.locator('section[aria-labelledby="pdf-needs-title"]').getByRole('listitem').filter({ hasText: WAITING_TITLE })).toHaveCount(0)
      await shot(p, name)
      expect(await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1)
    }
    await unreadInPanel(page, 'L-pdf-readiness-unread-1440')
    const narrow = await browser.newPage({ viewport: { width: 390, height: 844 } })
    try { await unreadInPanel(narrow, 'L-pdf-readiness-unread-390') } finally { await narrow.close() }

    // The panel's other two states, from this research's view with one change each, served to the page: before a
    // collection with a work still missing its PDF (the four depth boxes on one row at desktop width, two rows of two at phone
    // width, the last one counting the person's unread file), and during a collection (the unread work counted apart,
    // and a running step for it shown first).
    const served = async (p: Page, change: (view: any) => void) => {
      await p.unroute(`**/api/researches/${failing}`)
      await withoutAnswers(p, change)
      await p.goto('about:blank')
      await p.goto(`${FAIL_URL}/#/research/${failing}/waiting`)
    }
    const other = view.sources.find((s: { version_role: string; selection: { state: string }; has_pdf_text: boolean; title: string }) =>
      s.version_role === 'record' && s.selection.state === 'included' && s.has_pdf_text && s.title !== WAITING_TITLE).source_version_id
    const missingOne = (body: any) => { body.sources.find((s: { source_version_id: string }) => s.source_version_id === other).has_pdf_text = false }
    for (const width of [1440, 390]) {
      const p = width === 1440 ? page : await browser.newPage({ viewport: { width, height: 844 } })
      try {
        await served(p, missingOne)
        const cells = p.locator('.pdfs-panel .depth > div')
        await expect(cells).toHaveCount(4)
        await expect(cells.nth(3)).toHaveText('1Your PDFs, not read')
        await expect(p.locator('section[aria-labelledby="pdf-needs-title"]').getByRole('button', { name: 'Upload PDF' }).first()).toBeVisible()
        const tops = await cells.evaluateAll(els => els.map(el => Math.round(el.getBoundingClientRect().top)))
        expect(new Set(tops).size).toBe(width === 1440 ? 1 : 2)  // one row at desktop width, two rows of two at phone width
        await shot(p, `L-pdf-readiness-counters-${width}`)
        expect(await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1)
      } finally { if (p !== page) await p.close() }
    }
    const collecting = (running: boolean) => (body: any) => {
      const discovery = body.runs.find((r: { kind: string }) => r.kind === 'discovery')
      const later = new Date(Date.now() + 60_000).toISOString()
      body.runs.unshift({ ...discovery, id: 'run_SYNTHETIC_collection', kind: 'pdf_collection', status: 'running', stage: 'inspection',
        pause_reason: null, created_at: later, updated_at: later,
        steps: running ? [{ id: 'stp_SYNTHETIC', operation_key: `fetch:${record.source_version_id}`, kind: 'fetch_pdf', status: 'running',
          attempt: 1, delivery_class: null, error_code: null, error: null, started_at: later, finished_at: null, output: null }] : [] })
    }
    const collectionRow = () => page.locator('section.pdf-ready').getByRole('listitem').filter({ hasText: WAITING_TITLE })
    await served(page, collecting(false))
    await expect(page.getByRole('heading', { name: 'Collecting open-access PDFs' })).toBeVisible()
    await expect(page.locator('section.pdf-ready h4')).toContainText('1 your PDF, not read yet')
    await expect(collectionRow()).toContainText('Not read yet')
    await shot(page, 'L-pdf-collection-unread-1440')
    await served(page, collecting(true))
    await expect(collectionRow()).toContainText('Checking')
    await expect(collectionRow()).not.toContainText('Not read yet')
    await expect(page.locator('section.pdf-ready h4')).not.toContainText('your PDF, not read yet')  // it is still to check, counted there
    await page.unroute(`**/api/researches/${failing}`)
    await page.goto(`${FAIL_URL}/#/research/${failing}/waiting`)
    await expect(row).toContainText('Not read.')
    await again.click()
    await expect(page.getByText('The file waits to be read again.')).toBeVisible()
    await expect(row).toContainText('Included: both readings found every required part of the criterion', { timeout: 30_000 })
    await expect(row.getByRole('button', { name: 'Read again' })).toHaveCount(0)
  })

  test('L failure: at 390 px the file read again fits the width', async ({ browser }) => {
    const narrow = await browser.newPage({ viewport: { width: 390, height: 844 } })
    try {
      await narrow.goto(`${FAIL_URL}/#/research/${failing}/waiting`)
      await expect(fileRow(narrow)).toContainText('Included')
      const overflow = await narrow.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(overflow).toBeLessThanOrEqual(1)
    } finally { await narrow.close() }
  })
})
