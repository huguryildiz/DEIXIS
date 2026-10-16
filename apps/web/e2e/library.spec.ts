import { expect, request as apiRequest, test, type APIRequestContext, type Page, type Route } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'

// UI parity S25: the Library page (mockup `.lib`, plan L1-L10). Three panes (All works and the researches, the table,
// New from selection with the reading-depth box), the toolbar (search, Sort, PDF filter), the row menu, the actions on a
// selection, and the imports. Every count is checked against /api/library, the list the page reads; every result line
// against what the server stored. All records are SYNTHETIC: the fixture's scripted model and mocked OpenAlex. Zotero has
// no fixture, so its collections and the import answer are mocked (this checks what the page reports, not Zotero access).

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

class LibraryServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-library-'))
  constructor(readonly port: number) {}
  async start() {
    const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend') }
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`${this.url()}/api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`library fixture server on ${this.port} did not start`)
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

type Research = { id: string; title: string }
type Entry = { work_id: string; title: string; authors: string[]; year: number | null; access_level: 'pdf_available' | 'abstract' | 'metadata'; doi: string | null; researches: Research[]; versions: { source_version_id: string }[] }
type Library = { entries: Entry[]; researches: Research[] }
type View = { research: { id: string; title: string }; scope: { source_scope: string }; runs: { kind: string; status: string }[]; sources: { source_version_id: string; selection: { state: string } }[] }

// The same tiny PDF tests/support/helpers.py::make_pdf writes: one page of Helvetica text.
function makePdf(text: string): Buffer {
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>']
  const ops = `BT /F1 11 Tf 72 720 Td 14 TL (${text}) Tj T* ET`
  objects.push(`<< /Length ${ops.length} >>\nstream\n${ops}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
  let out = '%PDF-1.4\n'
  const offsets: number[] = []
  objects.forEach((body, i) => { offsets.push(out.length); out += `${i + 1} 0 obj\n${body}\nendobj\n` })
  const xref = out.length
  out += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.map(o => `${String(o).padStart(10, '0')} 00000 n \n`).join('')}`
  out += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`
  return Buffer.from(out, 'latin1')
}

const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
const server = new LibraryServer(nextPort())
let api: APIRequestContext
let token = ''
let A: Research, B: Research, C: Research

async function post(url: string, data: unknown, headers: Record<string, string> = {}) {
  const response = await api.post(url, { data, headers: { 'x-deixis-csrf': token, ...headers } })
  expect(response.ok(), `${url}: ${await response.text()}`).toBe(true)
  return response.json()
}
const library = async () => (await (await api.get('/api/library')).json()) as Library
const view = async (id: string) => (await (await api.get(`/api/researches/${id}`)).json()) as View
const settled = (id: string) => expect.poll(async () => {
  const v = await view(id)
  return v.runs.length > 0 && !v.runs.some(r => ACTIVE.has(r.status))
}, { timeout: 110_000, intervals: [500] }).toBe(true)
const holding = (lib: Library, id: string) => lib.entries.filter(e => e.researches.some(r => r.id === id))

async function open(page: Page) {
  await page.goto(`${server.url()}/#/library`)
  await expect(page.locator('.lib-table tbody tr .src-t').first()).toBeVisible()
}
const rows = (page: Page) => page.locator('.lib-table tbody tr:not(.more-row)')
const row = (page: Page, title: string) => rows(page).filter({ has: page.locator('.src-t', { hasText: new RegExp(`^${title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`) }) })
const left = (page: Page) => page.locator('.lib-left .cols-list')
const toast = (page: Page) => page.locator('.toast')
const result = (page: Page) => page.locator('.lib-result')
// The work shows on the first page of All works only if it is among the 25 newest; searching its title brings it up.
async function find(page: Page, title: string) {
  await page.getByLabel('Search the library').fill(title)
  await expect(row(page, title)).toHaveCount(1)
}
async function clearSearch(page: Page) { await page.getByLabel('Search the library').fill('') }

test.describe.serial('S25: the Library page', () => {
  test.beforeAll(async () => {
    test.setTimeout(240_000)
    await server.start()
    api = await apiRequest.newContext({ baseURL: server.url(), extraHTTPHeaders: { origin: server.url() } })
    token = (await (await api.get('/api/session')).json()).csrf_token as string
    const make = async (question: string, scope: 'academic' | 'attached') => {
      const created = await post('/api/researches', { question, source_scope: scope, model_connection: 'codex', requested_model: 'fixture-model', effort: 'quick' })
      return created.research.id as string
    }
    const a = await make('SYNTHETIC: How are molecule release schedules compared?', 'academic')
    await post(`/api/researches/${a}/runs`, { kind: 'discovery' }, { 'Idempotency-Key': `lib-a-${a}` })
    await settled(a)
    const b = await make('SYNTHETIC: How is molecule release scheduling optimized?', 'academic')
    await post(`/api/researches/${b}/runs`, { kind: 'discovery' }, { 'Idempotency-Key': `lib-b-${b}` })
    await settled(b)
    const c = await make('SYNTHETIC empty research that takes Library works', 'attached')
    const lib = await library()
    const title = (id: string) => lib.researches.find(r => r.id === id)!.title
    A = { id: a, title: title(a) }; B = { id: b, title: title(b) }; C = { id: c, title: title(c) }
    expect(holding(lib, a).length).toBeGreaterThan(1)
    expect(holding(lib, c).length).toBe(0)
  })
  test.afterAll(async () => { await api?.dispose(); await server.stop() })

  test('panes: All works and each research count the works /api/library lists; a research shows exactly its works', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await open(page)
    const lib = await library()
    await expect(page.locator('.lib-head h1')).toHaveText('Library / All')
    await expect(page.locator('.lib-head > button')).toHaveText(['Import from Zotero', 'Upload PDF'])
    await expect(left(page).locator('button').first()).toHaveText(`All works${lib.entries.length}`)
    await expect(left(page).locator('h6')).toHaveText('Research')
    for (const r of lib.researches) await expect(left(page).locator(`button[data-research="${r.id}"]`)).toHaveText(`${r.title}${holding(lib, r.id).length}`)
    // The depth box counts every work by its stored reading depth.
    const depth = (level: Entry['access_level']) => lib.entries.filter(e => e.access_level === level).length
    await expect(page.locator('.lib-right .box h5')).toHaveText('Reading depth, all works')
    await expect(page.locator('.lib-right .box .legend span')).toHaveText([`PDF ${depth('pdf_available')}`, `Abstract ${depth('abstract')}`, `Metadata ${depth('metadata')}`])
    await expect(page.locator('.lib-table thead th')).toHaveText(['', 'Title', 'Year', 'Reading depth', 'Research', ''])
    await expect(rows(page)).toHaveCount(Math.min(25, lib.entries.length))
    // A work held by two researches names the newest one and "+1 more"; one held by none says None.
    const both = lib.entries.find(e => e.researches.length === 2)!
    await find(page, both.title)
    await expect(row(page, both.title).locator('td').nth(4)).toHaveText(`${both.researches[0].title}+1 more`)
    await expect(row(page, both.title).locator('td').nth(3)).toHaveText({ pdf_available: 'PDF text', abstract: 'Abstract only', metadata: 'Metadata only' }[both.access_level])
    await clearSearch(page)
    // Choosing research A: the head names it and the table lists exactly the works A holds.
    await left(page).locator(`button[data-research="${A.id}"]`).click()
    await expect(page.locator('.lib-head h1')).toHaveText(`Library / ${A.title}`)
    const titles = holding(lib, A.id).map(e => e.title).sort()
    expect(titles.length).toBeLessThanOrEqual(25)
    await expect(rows(page)).toHaveCount(titles.length)
    expect((await rows(page).locator('.src-t').allTextContents()).sort()).toEqual(titles)
    // Panes: 200 / table / 260 at 1280; two panes below 1100; one pane and a research select on a phone, no side scroll.
    expect(Math.round((await page.locator('.lib-left').boundingBox())!.width)).toBe(200)
    expect(Math.round((await page.locator('.lib-right').boundingBox())!.width)).toBe(260)
    await page.screenshot({ path: path.join(OUT, 'S25-library-desktop.png'), animations: 'disabled' })
    await page.setViewportSize({ width: 1024, height: 800 })
    await expect(page.locator('.lib-right')).toBeHidden()
    expect(Math.round((await page.locator('.lib-left').boundingBox())!.width)).toBe(180)
    await page.setViewportSize({ width: 390, height: 844 })
    await expect(page.locator('.lib-left')).toBeHidden()
    await expect(page.locator('.lib-project-select')).toBeVisible()
    await expect(page.locator('.lib-project-select')).toHaveValue(A.id)
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.screenshot({ path: path.join(OUT, 'S25-library-phone.png'), animations: 'disabled' })
    await page.locator('.lib-project-select').selectOption('')
    await expect(page.locator('.lib-head h1')).toHaveText('Library / All')
  })

  test('toolbar: search, PDF filter (with its counts) and sort narrow and order the stored list', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await open(page)
    const lib = await library()
    const target = lib.entries.find(e => e.access_level === 'pdf_available') ?? lib.entries[0]
    await find(page, target.title)
    await page.getByLabel('Search the library').fill('SYNTHETIC no such title zzz')
    await expect(page.locator('.lib-nomatch')).toHaveText('No works match “SYNTHETIC no such title zzz”. Clear search and filter')
    await page.locator('.lib-nomatch').getByRole('button', { name: 'Clear search and filter' }).click()
    await expect(rows(page)).toHaveCount(Math.min(25, lib.entries.length))
    // PDF filter: each option shows how many works it keeps; Abstract only lists exactly the abstract-only works.
    const count = (level: Entry['access_level']) => lib.entries.filter(e => e.access_level === level).length
    const filter = page.getByRole('button', { name: 'Filter works by PDF text' })
    await filter.click()
    await expect(page.getByRole('menuitem')).toHaveText([`All${lib.entries.length}`, `PDF text${count('pdf_available')}`, `No PDF text${lib.entries.length - count('pdf_available')}`,
      `Abstract only${count('abstract')}`, `Metadata only${count('metadata')}`])
    await page.getByRole('menuitem', { name: /^Abstract only/ }).click()
    await expect(filter).toHaveText('PDF: Abstract only')
    await expect(rows(page)).toHaveCount(Math.min(25, count('abstract')))
    for (const label of await rows(page).locator('td:nth-child(4)').allTextContents()) expect(label).toBe('Abstract only')
    await filter.click()
    await page.getByRole('menuitem', { name: /^PDF text/ }).click()
    if (count('pdf_available') === 0) {
      await expect(page.locator('.lib-nomatch')).toHaveText('No works match with PDF text. Clear search and filter')
      await page.locator('.lib-nomatch').getByRole('button', { name: 'Clear search and filter' }).click()
    } else {
      await expect(rows(page)).toHaveCount(Math.min(25, count('pdf_available')))
      await filter.click()
      await page.getByRole('menuitem', { name: /^All/ }).click()
    }
    await expect(filter).toHaveText('PDF: All')
    // Sort Title A–Z orders the rows by title.
    await page.getByRole('button', { name: 'Sort works' }).click()
    await expect(page.getByRole('menuitem')).toHaveText(['Recently added', 'First added', 'Most cited', 'Newest first', 'Oldest first', 'Title A–Z'])
    await page.getByRole('menuitem', { name: 'Title A–Z' }).click()
    const sorted = lib.entries.map(e => e.title).sort((x, y) => x.localeCompare(y, 'en')).slice(0, 25)
    await expect(rows(page).locator('.src-t')).toHaveText(sorted)
    await page.getByRole('button', { name: 'Sort works' }).click()
    await page.getByRole('menuitem', { name: 'Recently added' }).click()
  })

  test('row menu: Already in it from stored membership, add, Open in research, and Remove from this research (membership only, with Undo)', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await open(page)
    let lib = await library()
    const work = lib.entries.find(e => e.researches.length === 1 && e.researches[0].id === A.id) ?? lib.entries.find(e => e.researches.some(r => r.id === A.id) && !e.researches.some(r => r.id === C.id))!
    await find(page, work.title)
    await row(page, work.title).getByRole('button', { name: /^More for/ }).click()
    const menu = page.getByRole('menu')
    await expect(menu.locator('.lib-menu-h')).toHaveText('Add to a research')
    for (const r of lib.researches) {
      const item = menu.locator(`[data-research="${r.id}"]`)
      if (work.researches.some(h => h.id === r.id)) { await expect(item).toBeDisabled(); await expect(item).toContainText('Already in it') }
      else await expect(item).not.toContainText('Already in it')
    }
    await expect(menu.getByRole('menuitem', { name: /^Open in research/ })).toBeEnabled()
    await expect(menu.getByRole('menuitem', { name: /^Remove from every research/ })).toContainText('Stays in All works')
    await menu.locator(`[data-research="${C.id}"]`).click()
    await expect(toast(page)).toContainText(`Added to ${C.title.length > 70 ? C.title.slice(0, 69) + '…' : C.title} as a source you included`)
    lib = await library()
    expect(lib.entries.find(e => e.work_id === work.work_id)!.researches.map(r => r.id)).toContain(C.id)
    await expect(row(page, work.title).locator('td').nth(4)).toContainText('+')
    await clearSearch(page)
    // Remove from C: the work leaves C's list, stays in All works; Undo puts it back.
    const all = lib.entries.length
    await left(page).locator(`button[data-research="${C.id}"]`).click()
    await expect(rows(page)).toHaveCount(1)
    await row(page, work.title).getByRole('button', { name: /^More for/ }).click()
    await page.getByRole('menuitem', { name: /^Remove from this research/ }).click()
    const dialog = page.getByRole('dialog', { name: 'Remove from this research?' })
    await expect(dialog).toContainText('The work stays in All works')
    await dialog.getByRole('button', { name: 'Remove' }).click()
    await expect(toast(page)).toContainText(`removed from ${C.title.length > 70 ? C.title.slice(0, 69) + '…' : C.title}. It stays in All works.`)
    await expect(page.locator('.lib-nomatch')).toHaveText('No work of this research is in the Library now.')
    lib = await library()
    expect(lib.entries.length).toBe(all)
    expect(lib.entries.find(e => e.work_id === work.work_id)!.researches.map(r => r.id)).not.toContain(C.id)
    await expect(left(page).locator('button').first()).toHaveText(`All works${all}`)
    await toast(page).getByRole('button', { name: 'Undo' }).click()
    await expect.poll(async () => (await library()).entries.find(e => e.work_id === work.work_id)!.researches.map(r => r.id)).toContain(C.id)
    await expect(rows(page)).toHaveCount(1)
    // Open in research goes to the research's Sources panel.
    await row(page, work.title).getByRole('button', { name: /^More for/ }).click()
    await page.getByRole('menuitem', { name: /^Open in research/ }).click()
    await expect.poll(() => page.evaluate(() => location.hash)).toBe(`#/research/${C.id}/sources`)
  })

  test('New from selection: Add to a research says Already in it, Export writes the chosen records, Ask and Start evidence table report what the server did', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await open(page)
    const lib = await library()
    const pane = page.locator('.lib-right')
    await expect(pane.locator('.pane-h')).toHaveText('New from selection')
    await expect(pane.locator('.newsel > button')).toHaveText(['Start evidence table', 'Ask about these works', 'Add to a research', 'Export .bib / .ris'])
    for (const button of await pane.locator('.newsel > button').all()) await expect(button).toBeDisabled()
    await expect(pane.locator('.foot-note')).toHaveText('Select works to start from them.')
    // Two works of A, chosen from A's list.
    const pick = holding(lib, A.id).slice(0, 2)
    await left(page).locator(`button[data-research="${A.id}"]`).click()
    for (const e of pick) await row(page, e.title).getByRole('checkbox').check()
    await expect(pane.locator('.pane-h')).toHaveText('New from selection · 2')
    await pane.getByRole('button', { name: 'Add to a research' }).click()
    const aItem = page.getByRole('menu').locator(`[data-research="${A.id}"]`)
    await expect(aItem).toBeDisabled()
    await expect(aItem).toContainText('Already in it')
    await page.keyboard.press('Escape')
    // Export .bib: a real file of the chosen records.
    await pane.getByRole('button', { name: 'Export .bib / .ris' }).click()
    const download = page.waitForEvent('download')
    await page.getByRole('menuitem', { name: 'BibTeX (.bib)' }).click()
    const file = readFileSync(await (await download).path(), 'utf8')
    expect(file.match(/^@\w+\{/gm)?.length).toBe(2)
    await expect(result(page)).toContainText('deixis-library.bib saved with 2 records, one per chosen work (2 chosen).')
    // Ask about these works: a new attached research with the two works, and its answer started.
    await pane.getByRole('button', { name: 'Ask about these works' }).click()
    const ask = page.getByRole('dialog', { name: 'Ask about these works' })
    await expect(ask).toContainText('A new research holds the 2 chosen works as its only sources')
    await expect(ask.locator('.lib-models')).toContainText('Answer model: ')
    await expect(ask.getByRole('button', { name: 'Start' })).toBeDisabled()
    await ask.getByLabel('Your question').fill('SYNTHETIC: what do these two works report?')
    const runAnswer = page.waitForResponse(r => r.request().method() === 'POST' && /\/api\/researches\/[^/]+\/runs$/.test(new URL(r.url()).pathname))
    await ask.getByRole('button', { name: 'Start' }).click()
    await expect(result(page)).toContainText('created with 2 works from the Library.')
    // The line names the status of the run the server returned (queued, not "started").
    const runStatus = ((await (await runAnswer).json()) as { status: string }).status
    await expect(result(page)).toContainText(runStatus === 'queued' ? 'The answer is queued; the research page shows its steps.' : `The answer run is ${runStatus}; the research page shows its steps.`)
    const asked = (await library()).researches.find(r => !lib.researches.some(x => x.id === r.id))!
    const askedView = await view(asked.id)
    expect(askedView.scope.source_scope).toBe('attached')
    expect(askedView.sources.filter(s => s.selection.state === 'included').length).toBe(2)
    expect(askedView.runs.some(r => r.kind === 'answer')).toBe(true)
    await expect(pane.locator('.pane-h')).toHaveText('New from selection')  // the picks are cleared after it started
    // Start evidence table: a new research whose study table holds the two works, then column suggestions.
    for (const e of pick) await row(page, e.title).getByRole('checkbox').check()
    await pane.getByRole('button', { name: 'Start evidence table' }).click()
    const table = page.getByRole('dialog', { name: 'Start evidence table' })
    await table.getByLabel('What should the table compare?').fill('SYNTHETIC: compare the release schedules')
    const suggest = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/column-suggestions'))
    await table.getByRole('button', { name: 'Start' }).click()
    await expect(result(page)).toContainText('Its study table holds 2 rows.')
    const suggestStatus = ((await (await suggest).json()) as { status: string }).status
    await expect(result(page)).toContainText(suggestStatus === 'queued' ? 'Column suggestions are queued' : `Column suggestions are ${suggestStatus}`)
    const before = new Set([...lib.researches.map(r => r.id), asked.id])
    const tabled = (await library()).researches.find(r => !before.has(r.id))!
    const tables = (await (await api.get(`/api/researches/${tabled.id}/tables`)).json()) as { rows: number }[]
    expect(tables.map(item => item.rows)).toEqual([2])
    await result(page).getByRole('button', { name: 'Open research' }).click()
    await expect.poll(() => page.evaluate(() => location.hash)).toBe(`#/research/${tabled.id}/table`)
  })

  test('Upload PDF reports saved, already saved and refused files from the server; Zotero reports the import answer', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await open(page)
    const before = (await library()).entries.length
    const input = page.locator('.library-page input[type=file]')
    await input.setInputFiles({ name: 'SYNTHETIC-library-upload.pdf', mimeType: 'application/pdf', buffer: makePdf('SYNTHETIC library upload study') })
    await expect(result(page)).toContainText('1 PDF saved to the Library; it is listed in All works.')
    await expect.poll(async () => (await library()).entries.length).toBe(before + 1)
    await expect(left(page).locator('button').first()).toHaveText(`All works${before + 1}`)
    await input.setInputFiles({ name: 'SYNTHETIC-library-upload-again.pdf', mimeType: 'application/pdf', buffer: makePdf('SYNTHETIC library upload study') })
    await expect(result(page)).toContainText('Already saved in the Library, nothing added: SYNTHETIC-library-upload-again.pdf.')
    expect((await library()).entries.length).toBe(before + 1)
    await input.setInputFiles({ name: 'SYNTHETIC-notes.txt', mimeType: 'text/plain', buffer: Buffer.from('SYNTHETIC plain text') })
    await expect(result(page)).toContainText('Not saved · SYNTHETIC-notes.txt:')
    // Zotero: the dialog says where items go, and the notice reports the server's answer.
    await page.route('**/api/zotero/collections**', route => route.fulfill({ json: { source: 'local', collections: [{ key: 'SYNZ', name: 'SYNTHETIC reading list', items: 3, parent: null }] } }))
    let answer: 'ok' | 'fail' = 'ok'
    await page.route('**/api/library/zotero-imports', async (route: Route) => {
      if (answer === 'fail') return route.fulfill({ status: 502, json: { detail: 'SYNTHETIC Zotero did not answer' } })
      const current = await (await api.get('/api/library')).json()
      return route.fulfill({ status: 201, json: { library: current, zotero_import: { items: 3, pdfs_added: 1, notes: [{ title: 'SYNTHETIC item', note: 'No PDF attachment' }], saved: ['sv1', 'sv2'], already_saved: ['sv3'] } } })
    })
    await page.getByRole('button', { name: 'Import from Zotero' }).click()
    const dialog = page.getByRole('dialog', { name: 'Import from Zotero' })
    await expect(dialog).toContainText('Items are added to All works in the Library.')
    await dialog.getByRole('button', { name: 'Import 3 items' }).click()
    await expect(dialog).toHaveCount(0)
    await expect(result(page)).toContainText('“SYNTHETIC reading list”: 3 Zotero items read. 2 saved to the Library and listed in All works; 1 were already saved.')
    await expect(result(page)).toContainText('1 PDFs added. The titles, authors and years are Zotero’s, not checked against a provider.')
    await expect(result(page)).toContainText('SYNTHETIC item: No PDF attachment.')
    answer = 'fail'
    // The list reads after the failed import are held: until one is on screen the line says the list is being read.
    let releaseReads: () => void = () => {}
    const readsHeld = new Promise<void>(resolve => { releaseReads = resolve })
    await page.route('**/api/library', async route => {
      if (route.request().method() !== 'GET') return route.fallback()
      await readsHeld
      return route.fallback()
    })
    await page.getByRole('button', { name: 'Import from Zotero' }).click()
    await page.getByRole('dialog', { name: 'Import from Zotero' }).getByRole('button', { name: 'Import 3 items' }).click()
    // An error does not prove nothing was saved (the import saves item by item): the page says the result is not confirmed.
    await expect(result(page)).toContainText('The Zotero import could not be confirmed: SYNTHETIC Zotero did not answer')
    await expect(result(page)).toContainText('Some items may have been saved before the error; reading the list again…')
    await expect(result(page)).not.toContainText('the list was read again')
    releaseReads()
    await expect(result(page)).toContainText('Some items may have been saved before the error; the list was read again')
    await page.unroute('**/api/library')
    await expect(result(page)).not.toContainText('Nothing was imported')
  })

  test('an empty Library offers Upload PDF, Import from Zotero and Start a research', async ({ page }) => {
    await page.route('**/api/library', route => route.fulfill({ json: { entries: [], researches: [], counts: { works: 0, versions: 0, researches: 0 } } }))
    await page.goto(`${server.url()}/#/library`)
    await expect(page.getByRole('heading', { name: 'No saved works yet' })).toBeVisible()
    await expect(page.locator('.lib-empty p')).toHaveText('The sources of every research land here. You can also upload PDFs or import a Zotero collection.')
    await expect(page.locator('.lib-empty .acts button')).toHaveText(['Upload PDF', 'Import from Zotero'])
    await expect(page.locator('.lib-empty .lib-start')).toHaveText('Start a research')
    await page.locator('.lib-empty').getByRole('button', { name: 'Start a research' }).click()
    await expect.poll(() => page.evaluate(() => location.hash)).toBe('#/')
  })

  test('View menu: compact rows and By research grouping are kept choices; each work is listed once under its newest research', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await open(page)
    const lib = await library()
    const viewMenu = page.getByRole('button', { name: 'View options' })
    await viewMenu.click()
    await expect(page.getByRole('menu').locator('.lib-menu-h')).toHaveText(['Rows', 'Group works'])
    await expect(page.getByRole('menuitem')).toHaveText(['Comfortable', 'Compact', 'By research', 'All works'])
    await page.getByRole('menuitem', { name: 'Compact' }).click()
    await expect(page.locator('.lib')).toHaveAttribute('data-density', 'compact')
    await viewMenu.click()
    await page.getByRole('menuitem', { name: 'By research' }).click()
    await expect(page.locator('.lib')).toHaveAttribute('data-grouping', 'research')
    // Page size 100 so every work is on one page; the bands follow the research list, each with the works it owns.
    await page.reload()
    await expect(page.locator('.lib')).toHaveAttribute('data-density', 'compact')
    await expect(page.locator('.lib')).toHaveAttribute('data-grouping', 'research')
    const owner = (e: Entry) => (lib.researches.some(r => r.id === e.researches[0]?.id) ? e.researches[0].id : '')
    const bands = [...lib.researches.map(r => r.id), ''].filter(id => lib.entries.some(e => owner(e) === id))
    const firstPage = page.locator('.lib-table tbody tr.lib-band')
    const shownBands = await firstPage.evaluateAll(trs => trs.map(tr => (tr as HTMLElement).dataset.band ?? ''))
    // The first page shows a prefix of the band order.
    expect(shownBands).toEqual(bands.map(id => id || 'none').slice(0, shownBands.length))
    const first = bands[0]
    const firstTitle = first ? lib.researches.find(r => r.id === first)!.title : 'No research'
    await expect(firstPage.first()).toHaveText(`${firstTitle}${lib.entries.filter(e => owner(e) === first).length}`)
    // A chosen research is one group already: no band rows.
    await left(page).locator(`button[data-research="${A.id}"]`).click()
    await expect(page.locator('.lib-table tbody tr.lib-band')).toHaveCount(0)
    await left(page).locator('button').first().click()
    await viewMenu.click()
    await page.getByRole('menuitem', { name: 'Comfortable' }).click()
    await viewMenu.click()
    await page.getByRole('menuitem', { name: 'All works' }).click()
    await expect(page.locator('.lib')).toHaveAttribute('data-grouping', 'none')
    await expect(page.locator('.lib')).toHaveAttribute('data-density', 'comfortable')
    await expect(page.locator('.lib-table tbody tr.lib-band')).toHaveCount(0)
  })

  test('a Settings read error stays visible and Start waits until Settings is read or the connections’ defaults are chosen', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await open(page)
    const lib = await library()
    let failSettings = true
    await page.route('**/api/settings', route => (failSettings && route.request().method() === 'GET'
      ? route.fulfill({ status: 500, json: { detail: 'SYNTHETIC settings read failure' } }) : route.fallback()))
    await left(page).locator(`button[data-research="${A.id}"]`).click()
    await row(page, holding(lib, A.id)[0].title).getByRole('checkbox').check()
    await page.locator('.lib-right').getByRole('button', { name: 'Ask about these works' }).click()
    const ask = page.getByRole('dialog', { name: 'Ask about these works' })
    await ask.getByLabel('Your question').fill('SYNTHETIC: a question that is never sent')
    await expect(ask.getByRole('alert')).toContainText('Could not read the default models in Settings: SYNTHETIC settings read failure')
    await expect(ask.getByRole('button', { name: 'Start' })).toBeDisabled()
    await expect(ask).not.toContainText('Settings has none')
    await ask.getByRole('button', { name: 'Use the connections’ default models' }).click()
    await expect(ask.locator('.lib-models')).toContainText('(the connection’s default; Settings could not be read)')
    await expect(ask.getByRole('button', { name: 'Start' })).toBeEnabled()
    // Cancel and open again: the choice is asked again; Try again reads Settings once it answers.
    await ask.getByRole('button', { name: 'Cancel' }).click()
    await page.locator('.lib-right').getByRole('button', { name: 'Ask about these works' }).click()
    await expect(ask.getByRole('alert')).toContainText('Could not read the default models in Settings')
    failSettings = false
    await ask.getByRole('button', { name: 'Try again' }).click()
    await expect(ask.getByRole('alert')).toHaveCount(0)
    await expect(ask.locator('.lib-models')).toContainText('Answer model: ')
    await expect(ask.locator('.lib-models')).not.toContainText('Settings could not be read')
    await ask.getByRole('button', { name: 'Cancel' }).click()
  })

  test('a failed study table read keeps the created research and requests no column suggestions; a failed add keeps its work chosen', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await open(page)
    const lib = await library()
    await page.route('**/api/researches/*/tables', route => (route.request().method() === 'GET'
      ? route.fulfill({ status: 500, json: { detail: 'SYNTHETIC tables read failure' } }) : route.fallback()))
    let suggestions = 0
    page.on('request', r => { if (r.url().endsWith('/column-suggestions')) suggestions++ })
    await left(page).locator(`button[data-research="${A.id}"]`).click()
    const two = holding(lib, A.id).slice(0, 2)
    for (const e of two) await row(page, e.title).getByRole('checkbox').check()
    await page.locator('.lib-right').getByRole('button', { name: 'Start evidence table' }).click()
    const dialog = page.getByRole('dialog', { name: 'Start evidence table' })
    await dialog.getByLabel('What should the table compare?').fill('SYNTHETIC: a table whose read fails')
    await dialog.getByRole('button', { name: 'Start' }).click()
    await expect(result(page)).toContainText('created with 2 works from the Library.')
    await expect(result(page)).toContainText('Could not read its study table (SYNTHETIC tables read failure), so the table state is not confirmed and column suggestions were not requested.')
    await expect(result(page)).not.toContainText('No study table was made')
    expect(suggestions).toBe(0)
    const made = (await library()).researches.find(r => !lib.researches.some(x => x.id === r.id))!
    expect(made).toBeTruthy()
    await page.unroute('**/api/researches/*/tables')
    // Two works to C, one refused by the server: that one stays chosen, the added one is not.
    await left(page).locator(`button[data-research="${A.id}"]`).click()
    const fresh = await library()
    const pair = holding(fresh, A.id).filter(e => !e.researches.some(r => r.id === B.id)).slice(0, 2)
    const target = pair.length === 2 ? B : C
    const both = pair.length === 2 ? pair : holding(fresh, A.id).filter(e => !e.researches.some(r => r.id === C.id)).slice(0, 2)
    expect(both.length).toBe(2)
    const refused = both[1]
    await page.route(`**/api/researches/${target.id}/library-sources`, async route => {
      if ((route.request().postDataJSON() as { work_id: string }).work_id === refused.work_id) return route.fulfill({ status: 500, json: { detail: 'SYNTHETIC add refused' } })
      return route.fallback()
    })
    for (const e of both) await row(page, e.title).getByRole('checkbox').check()
    await page.locator('.lib-right').getByRole('button', { name: 'Add to a research' }).click()
    await page.getByRole('menu').locator(`[data-research="${target.id}"]`).click()
    await expect(toast(page)).toContainText('1 could not be added: SYNTHETIC add refused')
    await expect(page.locator('.lib-right .pane-h')).toHaveText('New from selection · 1')
    await expect(row(page, refused.title).getByRole('checkbox')).toBeChecked()
    await expect(row(page, both[0].title).getByRole('checkbox')).not.toBeChecked()
  })

  test('Undo of a removal from two researches waits for both restores and reports the one that failed', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await open(page)
    const lib = await library()
    const work = lib.entries.find(e => e.researches.length >= 2)!
    const [failing, slow] = work.researches
    await find(page, work.title)
    await row(page, work.title).getByRole('button', { name: /^More for/ }).click()
    await page.getByRole('menuitem', { name: /^Remove from every research/ }).click()
    await page.getByRole('dialog', { name: 'Remove from every research?' }).getByRole('button', { name: 'Remove' }).click()
    await expect(toast(page)).toContainText('removed from every research that held it')
    await expect(row(page, work.title).locator('td').nth(4)).toHaveText('None')
    // The first research's restore fails at once; the second is held for 1.5 s, past the moment the failure is known.
    await page.route(`**/api/researches/${failing.id}/sources/restore`, route => route.fulfill({ status: 500, json: { detail: 'SYNTHETIC restore refused' } }))
    await page.route(`**/api/researches/${slow.id}/sources/restore`, async route => {
      await new Promise(resolve => setTimeout(resolve, 1500))
      return route.fallback()
    })
    const slowDone = page.waitForResponse(r => r.url().includes(`/api/researches/${slow.id}/sources/restore`))
    await toast(page).getByRole('button', { name: 'Undo' }).click()
    await slowDone
    await expect(toast(page)).toContainText(`Put back in ${work.researches.length - 1} of ${work.researches.length} researches; not in`, { timeout: 10_000 })
    await expect(toast(page)).toContainText('SYNTHETIC restore refused')
    // Read once after a pause: the list must show the restore that finished after the failure.
    await page.waitForTimeout(800)
    const cell = await row(page, work.title).locator('td').nth(4).textContent()
    const stored = (await library()).entries.find(e => e.work_id === work.work_id)!.researches
    expect(stored.map(r => r.id)).toContain(slow.id)
    expect(stored.map(r => r.id)).not.toContain(failing.id)
    expect(cell).toBe(`${stored[0].title}${stored.length > 1 ? `+${stored.length - 1} more` : ''}`)
  })

  // S24 lesson: a read that started before a write must not undo the write's screen, on success or on error. The held
  // read's answer is the list before the write; the screen is read once after a pause (no polling retries).
  for (const outcome of ['stale list', 'error'] as const) {
    test(`a Library read held across an add (${outcome}) does not replace the added state`, async ({ page }) => {
      await page.setViewportSize({ width: 1280, height: 900 })
      await open(page)
      const lib = await library()
      // The work held by the fewest researches, and one research that does not hold it yet.
      const work = [...lib.entries].sort((x, y) => x.researches.length - y.researches.length)[0]
      const target = lib.researches.find(r => [A.id, B.id, C.id].includes(r.id) && !work.researches.some(h => h.id === r.id))!
      await find(page, work.title)
      const before = await row(page, work.title).locator('td').nth(4).textContent()
      let release: () => void = () => {}
      const held = new Promise<void>(resolve => { release = resolve })
      let seen = 0
      await page.route('**/api/library', async route => {
        if (route.request().method() !== 'GET' || seen++) return route.fallback()
        const stale = await route.fetch()
        const body = await stale.text()
        await held
        if (outcome === 'error') return route.fulfill({ status: 500, json: { detail: 'SYNTHETIC read failure' } })
        return route.fulfill({ status: 200, contentType: 'application/json', body })
      })
      // A new research makes the shell's 5 s poll change the research list, which reads the Library again: that read is held.
      await post('/api/researches', { question: `SYNTHETIC research made during a read ${outcome}`, source_scope: 'attached', model_connection: 'codex', requested_model: 'fixture-model', effort: 'quick' })
      await expect.poll(() => seen, { timeout: 15_000 }).toBeGreaterThan(0)
      await row(page, work.title).getByRole('button', { name: /^More for/ }).click()
      await page.getByRole('menu').locator(`[data-research="${target.id}"]`).click()
      await expect(toast(page)).toContainText('as a source you included')
      release()
      await page.waitForTimeout(800)
      const research = await row(page, work.title).locator('td').nth(4).textContent()
      const notice = await page.locator('.lib-notice').count()
      const stored = (await library()).entries.find(e => e.work_id === work.work_id)!.researches
      expect(stored.map(r => r.id)).toContain(target.id)
      expect(research).not.toBe(before)
      expect(research).toBe(`${stored[0].title}${stored.length > 1 ? `+${stored.length - 1} more` : ''}`)
      expect(notice).toBe(0)
    })
  }
  // Sol S25 round 2: two reads with no write between them; the older one answers last and must not replace the newer list.
  test('an older Library read that answers after a newer read does not replace it', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await open(page)
    const lib = await library()
    const work = [...lib.entries].sort((x, y) => x.researches.length - y.researches.length)[0]
    const target = lib.researches.find(r => [A.id, B.id, C.id].includes(r.id) && !work.researches.some(h => h.id === r.id))!
    await find(page, work.title)
    const cell = row(page, work.title).locator('td').nth(4)
    let release: () => void = () => {}
    const held = new Promise<void>(resolve => { release = resolve })
    let seen = 0
    let fetched = false
    await page.route('**/api/library', async route => {
      if (route.request().method() !== 'GET' || seen++) return route.fallback()
      const stale = await route.fetch()
      const body = await stale.text()
      fetched = true
      await held
      return route.fulfill({ status: 200, contentType: 'application/json', body })
    })
    // A new research makes the shell's poll read the Library: that first read takes the list before the change, and is held.
    await post('/api/researches', { question: 'SYNTHETIC research made before an older read', source_scope: 'attached', model_connection: 'codex', requested_model: 'fixture-model', effort: 'quick' })
    await expect.poll(() => fetched, { timeout: 15_000 }).toBe(true)
    // The change happens on the server, not through the page, so no write runs; a second research makes a newer read.
    await post(`/api/researches/${target.id}/library-sources`, { work_id: work.work_id })
    await post('/api/researches', { question: 'SYNTHETIC research made for a newer read', source_scope: 'attached', model_connection: 'codex', requested_model: 'fixture-model', effort: 'quick' })
    const stored = (await library()).entries.find(e => e.work_id === work.work_id)!.researches
    const expected = `${stored[0].title}${stored.length > 1 ? `+${stored.length - 1} more` : ''}`
    await expect(cell).toHaveText(expected, { timeout: 15_000 })
    release()
    await page.waitForTimeout(800)
    expect(await cell.textContent()).toBe(expected)
  })
})
