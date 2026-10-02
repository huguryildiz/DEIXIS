import { expect, request as apiRequest, test, type APIRequestContext, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { failedSectionReasonText, reportAssemblyDraftText } from '../src/labels'
import { setUiLanguage } from '../src/i18n'

// SYNTHETIC records and a scripted report model exercise the UI, not the quality of a research report.
const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = process.env.DEIXIS_TEST_PYTHON ?? path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

class ReportServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-report-'))
  constructor(readonly port = 8801) {}
  async start() {
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], {
      cwd: REPO, env: { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend') }, stdio: 'inherit',
    })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`${this.url()}/api/health`)).ok) return } catch { /* waiting for the fixture */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error('Report fixture server did not start')
  }
  async stop() {
    if (!this.proc || this.proc.exitCode !== null) return
    const exited = new Promise(resolve => this.proc?.once('exit', resolve))
    this.proc.kill('SIGTERM')
    await exited
  }
  url() { return `http://127.0.0.1:${this.port}` }
}

const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`), animations: 'disabled' })
const reportSheet = (page: Page) => page.locator('.report-sheet').last()
const section = (page: Page, number: string) => reportSheet(page).locator('.evidence-report-section', { has: page.getByRole('heading', { name: new RegExp(`^${number}\\.`) }) })

const toastsOff = async (target: Page) => { for (const b of await target.getByRole('button', { name: 'Dismiss notification' }).all()) await b.click().catch(() => {}) }

const readyResearch = async (page: Page, server: ReportServer, question: string) => {
  await page.goto(server.url())
  await page.getByLabel('Research question').fill(question)
  await page.getByRole('button', { name: 'Start research' }).click()
  await page.waitForURL(/#\/research\//)
  const researchId = page.url().split('/research/')[1].split('/')[0]
  await expect(page.getByText('Ran search & screening')).toBeVisible()
  await page.getByRole('tab', { name: /Sources/ }).click()
  const source = page.locator('.source-row:not(.is-other-version)').filter({ hasText: 'SYNTHETIC molecule release scheduling with bisection' })
  await source.getByRole('button', { name: 'Include' }).click()
  await expect(source.getByRole('button', { name: 'Include' })).toBeDisabled()
  await page.getByRole('tab', { name: /Evidence/ }).click()
  await page.getByRole('button', { name: /Add a column/ }).click()
  const editor = page.getByRole('dialog', { name: 'Add column' })
  await editor.getByLabel('Short name').fill('SYNTHETIC method')
  await editor.getByLabel('Instruction').fill('Record the method named by the source.')
  await editor.getByRole('button', { name: 'Add column' }).click()
  await page.getByRole('button', { name: /^Fill empty cells/ }).click()
  await expect(page.locator('.evidence-toolbar').getByRole('button', { name: 'Write report' })).toBeEnabled({ timeout: 60_000 })
  await page.getByRole('tab', { name: 'Answer' }).click()
  await expect(page.locator('.report-ready').getByRole('button', { name: 'Write report' })).toBeEnabled()
  return researchId
}

test('write, read, edit, restore and acknowledge an evidence report', async ({ browser }) => {
  const server = new ReportServer()
  await server.start()
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const api: APIRequestContext = await apiRequest.newContext({ baseURL: server.url(), extraHTTPHeaders: { origin: server.url() } })
  try {
    const csrf = (await (await api.get('/api/session')).json()).csrf_token as string
    await page.goto(server.url())
    await page.getByLabel('Research question').fill('SYNTHETIC: How are molecule release schedules compared?')
    await page.getByRole('button', { name: 'Start research' }).click()
    await page.waitForURL(/#\/research\//)
    const researchId = page.url().split('/research/')[1].split('/')[0]
    await expect(page.getByText('Ran search & screening')).toBeVisible()
    await page.getByRole('tab', { name: /Sources/ }).click()
    const source = page.locator('.source-row:not(.is-other-version)').filter({ hasText: 'SYNTHETIC molecule release scheduling with bisection' })
    await source.getByRole('button', { name: 'Include' }).click()
    await expect(source.getByRole('button', { name: 'Include' })).toBeDisabled()
    await page.getByRole('tab', { name: /Evidence/ }).click()
    await page.getByRole('button', { name: /Add a column/ }).click()
    const editor = page.getByRole('dialog', { name: 'Add column' })
    await editor.getByLabel('Short name').fill('SYNTHETIC method')
    await editor.getByLabel('Instruction').fill('Record the method named by the source.')
    await editor.getByRole('button', { name: 'Add column' }).click()
    await page.getByRole('button', { name: /^Fill empty cells/ }).click()
    await expect(page.locator('.evidence-grid tbody tr .evidence-cell').first()).toContainText('Model', { timeout: 60_000 })
    await expect(page.locator('.evidence-toolbar').getByRole('button', { name: 'Write report' })).toBeEnabled({ timeout: 60_000 })
    const tables = await (await api.get(`/api/researches/${researchId}/tables`)).json() as { id: string }[]
    const tableId = tables[0].id
    await page.getByRole('tab', { name: 'Answer' }).click()
    await expect(page.locator('.report-ready').getByRole('button', { name: 'Write report' })).toBeEnabled()
    await toastsOff(page)
    await page.locator('.report-ready').scrollIntoViewIfNeeded()
    await shot(page, 'report-readiness-desktop')
    await page.locator('.report-ready').getByRole('button', { name: 'Write report' }).click()
    await expect(page.getByText(/Writing sections|Wrote the sections|Report sections/)).toBeVisible({ timeout: 60_000 })
    await expect(page.getByRole('button', { name: 'Open evidence report' })).toContainText('Evidence report · V1', { timeout: 60_000 })
    const summaries = await (await api.get(`/api/researches/${researchId}/reports`)).json() as { id: string }[]
    const reportId = summaries[0].id
    await page.getByRole('button', { name: 'Open evidence report' }).click()
    const sheet = reportSheet(page)
    await expect(sheet.getByRole('heading', { name: 'II. Review Methodology' })).toBeVisible()
    await expect(sheet.getByRole('heading', { name: 'IX. Conclusion' })).toBeVisible()
    await expect(sheet.locator('.evidence-report-section').first()).toContainText('Abstract')
    await expect(section(page, 'VIII')).toContainText('Recall was not measured against a known source set.')
    await expect(sheet).toContainText('TABLE I')
    await expect(sheet.locator('.cite-chip').first()).toContainText('[1]')
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write'], { origin: server.url() })
    await sheet.getByRole('button', { name: 'Copy Markdown' }).click()
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toContain('## References')
    const downloaded = page.waitForEvent('download')
    await sheet.getByRole('button', { name: 'Download .md' }).click()
    const file = await downloaded
    expect(file.suggestedFilename()).toMatch(/^report-.*-v1\.md$/)
    expect(readFileSync(await file.path(), 'utf8')).toMatch(/^# /)
    const exportPath = `**/api/researches/${researchId}/reports/${reportId}/export?format=markdown`
    let unexpectedDownloads = 0
    page.on('download', () => { unexpectedDownloads += 1 })
    await page.route(exportPath, route => route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: 'The report is still being written' }) }))
    await sheet.getByRole('button', { name: 'Download .md' }).click()
    await expect(page.getByText('The report is still being written')).toBeVisible()
    expect(unexpectedDownloads).toBe(0)
    await page.unroute(exportPath)
    await toastsOff(page)

    // LaTeX export (D160): a zip download, one toast that carries the note count, no download on an error.
    const latexPath = `**/api/researches/${researchId}/reports/${reportId}/export?format=latex`
    const latexResponse = page.waitForResponse(response => response.url().includes('format=latex'))
    const latexDownload = page.waitForEvent('download')
    await sheet.getByRole('button', { name: 'Download LaTeX' }).click()
    const latexFile = await latexDownload
    expect(latexFile.suggestedFilename()).toMatch(/^report-.*-v1-latex\.zip$/)
    expect(readFileSync(await latexFile.path()).subarray(0, 2).toString('latin1')).toBe('PK')
    const realNotes = (await latexResponse).headers()['x-deixis-export-notes']
    expect(realNotes).toMatch(/^\d+$/)
    if (Number(realNotes) === 0) await expect(page.locator('.toast.is-success')).toContainText('LaTeX downloaded: a zip with the .tex and .bib files.')
    else await expect(page.locator('.toast.is-warning')).toContainText('export note')
    await toastsOff(page)
    for (const [notes, text] of [['3', 'LaTeX downloaded with 3 export notes. They are listed in a comment block at the top of the .tex file.'],
      ['1', 'LaTeX downloaded with 1 export note. It is listed in a comment block at the top of the .tex file.'],
      ['25', 'LaTeX downloaded with 25 export notes. The first 20 are listed in a comment block at the top of the .tex file.']]) {
      await page.route(latexPath, async route => {
        const response = await route.fetch()
        await route.fulfill({ response, headers: { ...response.headers(), 'x-deixis-export-notes': notes } })
      })
      const counted = page.waitForEvent('download')
      await sheet.getByRole('button', { name: 'Download LaTeX' }).click()
      expect((await counted).suggestedFilename()).toMatch(/^report-.*-v1-latex\.zip$/)
      await expect(page.locator('.toast')).toHaveCount(1)
      await expect(page.locator('.toast.is-warning')).toHaveText(text)
      await page.unroute(latexPath)
      await toastsOff(page)
    }
    const downloadsBefore409 = unexpectedDownloads
    await page.route(latexPath, route => route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: 'The report is still being written' }) }))
    await sheet.getByRole('button', { name: 'Download LaTeX' }).click()
    await expect(page.locator('.toast.is-error')).toHaveText('The report is still being written')
    expect(unexpectedDownloads).toBe(downloadsBefore409)
    await page.unroute(latexPath)
    await toastsOff(page)
    const report = await (await api.get(`/api/researches/${researchId}/reports/${reportId}`)).json()
    expect(report.review.status).toBe('reviewed')
    const reviewed = report.review.sections_reviewed.length
    const total = reviewed + report.review.sections_not_reviewed.length
    const provenance = sheet.locator('.evidence-report-provenance')
    await expect(provenance).toContainText(`A model read the claims of ${reviewed} of ${total} sections against their cited passages and cells in an extra review call using the same model that wrote the report, and flagged 0 possible problems. That is a model’s reading, not peer review, and it can miss errors; whether each passage supports its claim was not checked by code.`)
    if (report.review.sections_not_reviewed.length) {
      const names: Record<string, string> = { abstract: 'Abstract', I: 'I. Introduction', III: 'III. Background and Taxonomy',
        IV: 'IV. Literature Synthesis', V: 'V. Comparative Findings', VI: 'VI. Candidate Unanswered Aspects',
        VII: 'VII. Future Directions', VIII: 'VIII. Limitations and Threats to Validity', IX: 'IX. Conclusion',
        index_terms: 'Index Terms' }
      await expect(provenance).toContainText(`Not read: ${report.review.sections_not_reviewed.map((s: { section_id: string }) => names[s.section_id]).join(', ')}.`)
    }
    await page.keyboard.press('Escape')
    const reportPath = `/api/researches/${researchId}/reports/${reportId}`
    await page.route(`**${reportPath}`, route => route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ ...report, review: { status: 'not_reviewed', reason: 'budget_exhausted', detail: null,
        sections_reviewed: [], sections_not_reviewed: report.sections.filter((s: { section_id: string }) => s.section_id !== 'II').map((s: { section_id: string }) => ({ section_id: s.section_id, reason: 'budget_exhausted' })),
        findings: [], notes: '', reverted: [], not_reverted: [] } }),
    }))
    await page.getByRole('button', { name: 'Open evidence report' }).click()
    await expect(reportSheet(page).locator('.evidence-report-provenance')).toContainText('No accepted review result exists for this report (the model-call budget was exhausted); whether the model read it in part is not established by this record.')
    await page.keyboard.press('Escape')
    await page.unroute(`**${reportPath}`)
    await page.route(`**${reportPath}`, route => route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ ...report, review: null }),
    }))
    await page.getByRole('button', { name: 'Open evidence report' }).click()
    await expect(reportSheet(page).locator('.evidence-report-provenance')).toContainText('No model or person review is recorded for this report; whether each passage supports its claim was not checked by code.')
    await page.keyboard.press('Escape')
    await page.unroute(`**${reportPath}`)
    await page.route(`**${reportPath}`, route => route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ ...report, review: { ...report.review, findings: [{ claim_key: null, sentence_id: null,
        section_id: null, code: 'abstract_body_mismatch', text: 'SYNTHETIC report-level mismatch.' }] } }),
    }))
    await page.getByRole('button', { name: 'Open evidence report' }).click()
    await expect(reportSheet(page).locator('.evidence-report-provenance')).toContainText(`A model read the claims of ${reviewed} of ${total} sections against their cited passages and cells in an extra review call using the same model that wrote the report, and flagged 1 possible problem. That is a model’s reading, not peer review, and it can miss errors; whether each passage supports its claim was not checked by code.`)
    await reportSheet(page).locator('.evidence-report-history summary').filter({ hasText: 'Review findings (1)' }).click()
    await expect(reportSheet(page)).toContainText('Report · Abstract and body differ · SYNTHETIC report-level mismatch.')
    await page.keyboard.press('Escape')
    await page.unroute(`**${reportPath}`)
    await page.getByRole('button', { name: 'Open evidence report' }).click()
    await expect(sheet.locator('.evidence-report-references')).toContainText(report.references[0].title)
    await sheet.locator('.cite-chip').first().click()
    await expect(page.getByRole('dialog', { name: 'Source details' })).toBeVisible()
    await expect(page.getByRole('dialog', { name: 'Source details' }).locator('mark').first()).toBeVisible()
    await page.keyboard.press('Escape')
    await toastsOff(page)
    await shot(page, 'report-view-desktop')
    await page.setViewportSize({ width: 390, height: 844 })
    await shot(page, 'report-view-390')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
    await page.setViewportSize({ width: 1440, height: 900 })
    await sheet.getByText('TABLE I', { exact: false }).first().scrollIntoViewIfNeeded()
    await shot(page, 'report-view-table-desktop')
    // The sheet is modal, so the header's theme switch is reached with the sheet closed.
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'Use dark theme' }).click()
    await page.getByRole('button', { name: 'Open evidence report' }).click()
    await expect(reportSheet(page).getByRole('heading', { name: 'II. Review Methodology' })).toBeVisible()
    await toastsOff(page)
    await shot(page, 'report-view-dark-desktop')
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'Use light theme' }).click()
    await page.getByRole('button', { name: 'Open evidence report' }).click()

    await sheet.getByRole('button', { name: 'Evidence view' }).click()
    const iii = section(page, 'III')
    await iii.getByRole('button', { name: 'Edit', exact: true }).first().click()
    const form = iii.locator('.evidence-report-edit')
    await form.getByLabel('Claim text').fill('SYNTHETIC edited background claim.')
    await form.getByRole('button', { name: 'Save' }).click()
    await expect(iii).toContainText('SYNTHETIC edited background claim.')
    await expect(iii).toContainText('Edited by you')
    await expect(sheet).toContainText('Edited by hand after version 1')
    await toastsOff(page)
    await iii.scrollIntoViewIfNeeded()
    await shot(page, 'report-edited-desktop')

    await iii.getByRole('button', { name: 'Edit', exact: true }).first().click()
    await form.getByLabel('Claim text').fill('SYNTHETIC draft kept after conflict.')
    const current = await (await api.get(`/api/researches/${researchId}/reports/${reportId}`)).json()
    const claim = current.sections.find((item: { section_id: string }) => item.section_id === 'III').claims[0]
    const competing = await api.put(`/api/researches/${researchId}/reports/${reportId}/claims/${claim.id}`, {
      data: { text: 'SYNTHETIC competing edit.', expected_version: claim.version },
      headers: { 'x-deixis-csrf': csrf, 'Idempotency-Key': crypto.randomUUID() },
    })
    expect(competing.status()).toBe(200)
    await form.getByRole('button', { name: 'Save' }).click()
    await expect(page.getByText(/Not applied:/)).toBeVisible()
    await expect(form.getByLabel('Claim text')).toHaveValue('SYNTHETIC draft kept after conflict.')
    await form.getByRole('button', { name: 'Cancel' }).click()
    await iii.locator('.evidence-report-history summary').first().click()
    await iii.getByRole('button', { name: 'Restore' }).first().click()
    await expect(iii).toContainText(claim.model_text)

    const cell = report.table_i.cells.find((item: { cell_id: string }) => report.sections.some((s: { claims: { evidence: { cell_id: string | null }[] }[] }) => s.claims.some(c => c.evidence.some(link => link.cell_id === item.cell_id))))
    expect(cell).toBeTruthy()
    const cellUrl = `/api/researches/${researchId}/tables/${tableId}/cells/${cell.column_id}/${cell.source_version_id}`
    const liveCell = await (await api.get(cellUrl)).json()
    const editedCell = await api.put(cellUrl, { data: { state: 'not_verified', value: { text: 'SYNTHETIC revised cell' }, note: null,
      keep_evidence_from: null, expected_version: liveCell.version }, headers: { 'x-deixis-csrf': csrf, 'Idempotency-Key': crypto.randomUUID() } })
    expect(editedCell.status()).toBe(200)
    await page.keyboard.press('Escape')
    await page.reload()
    await page.getByRole('button', { name: 'Open evidence report' }).click()
    await expect(reportSheet(page)).toContainText('Evidence changed after this report:')
    // The fixture cites the cell in every section it writes; pin one section so the locator does not move on.
    const changed = section(page, 'IV')
    await expect(changed).toContainText('This section rests on evidence that changed after this report:')
    await expect(changed).toBeVisible()
    await changed.getByRole('button', { name: 'Keep as is' }).click()
    await expect(changed).not.toContainText('This section rests on evidence that changed after this report:')
    await expect(reportSheet(page)).toContainText('Evidence changed after this report:')
    await toastsOff(page)
    await reportSheet(page).locator('.evidence-report-head, header').first().scrollIntoViewIfNeeded()
    await shot(page, 'report-stale-desktop')
    await page.setViewportSize({ width: 390, height: 844 })
    await shot(page, 'report-stale-390')
  } finally { await api.dispose(); await page.close(); await server.stop() }
})

test('a scripted report review finding appears as a model flag', async ({ browser }) => {
  const server = new ReportServer()
  await server.start()
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const api = await apiRequest.newContext({ baseURL: server.url(), extraHTTPHeaders: { origin: server.url() } })
  try {
    await page.goto(server.url())
    await page.getByLabel('Research question').fill('SYNTHETIC: How are molecule release schedules compared? [report-review-finding]')
    await page.getByRole('button', { name: 'Start research' }).click()
    await page.waitForURL(/#\/research\//)
    const researchId = page.url().split('/research/')[1].split('/')[0]
    await expect(page.getByText('Ran search & screening')).toBeVisible()
    await page.getByRole('tab', { name: /Sources/ }).click()
    const source = page.locator('.source-row:not(.is-other-version)').filter({ hasText: 'SYNTHETIC molecule release scheduling with bisection' })
    await source.getByRole('button', { name: 'Include' }).click()
    await expect(source.getByRole('button', { name: 'Include' })).toBeDisabled()
    await page.getByRole('tab', { name: /Evidence/ }).click()
    await page.getByRole('button', { name: /Add a column/ }).click()
    const editor = page.getByRole('dialog', { name: 'Add column' })
    await editor.getByLabel('Short name').fill('SYNTHETIC method')
    await editor.getByLabel('Instruction').fill('Record the method named by the source.')
    await editor.getByRole('button', { name: 'Add column' }).click()
    await page.getByRole('button', { name: /^Fill empty cells/ }).click()
    await expect(page.locator('.evidence-toolbar').getByRole('button', { name: 'Write report' })).toBeEnabled({ timeout: 60_000 })
    await page.getByRole('tab', { name: 'Answer' }).click()
    await page.locator('.report-ready').getByRole('button', { name: 'Write report' }).click()
    await expect(page.getByRole('button', { name: 'Open evidence report' })).toContainText('Evidence report · V1', { timeout: 60_000 })
    const summaries = await (await api.get(`/api/researches/${researchId}/reports`)).json() as { id: string }[]
    const report = await (await api.get(`/api/researches/${researchId}/reports/${summaries[0].id}`)).json()
    expect(report.review.findings).toHaveLength(1)
    await page.getByRole('button', { name: 'Open evidence report' }).click()
    const sheet = reportSheet(page)
    const reviewed = report.review.sections_reviewed.length
    const total = reviewed + report.review.sections_not_reviewed.length
    await expect(sheet.locator('.evidence-report-provenance')).toContainText(`A model read the claims of ${reviewed} of ${total} sections against their cited passages and cells in an extra review call using the same model that wrote the report, and flagged 1 possible problem. That is a model’s reading, not peer review, and it can miss errors; whether each passage supports its claim was not checked by code.`)
    await sheet.locator('.evidence-report-history summary').filter({ hasText: 'Review findings (1)' }).click()
    await expect(sheet).toContainText('Model findings')
    await expect(sheet).toContainText('SYNTHETIC: the cited wording may need another reading.')
    const review = sheet.locator('.evidence-report-provenance')
    await review.scrollIntoViewIfNeeded()
    await shot(page, 'report-review-desktop')
    await page.emulateMedia({ colorScheme: 'dark' })
    await review.scrollIntoViewIfNeeded()
    await shot(page, 'report-review-dark-desktop')
    await page.emulateMedia({ colorScheme: 'light' })
    await page.setViewportSize({ width: 390, height: 844 })
    await review.scrollIntoViewIfNeeded()
    await shot(page, 'report-review-390')
  } finally { await api.dispose(); await page.close(); await server.stop() }
})

test('a banned word leaves the assembled report as an exportable draft', async ({ browser }) => {
  const server = new ReportServer(8802)
  await server.start()
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const api = await apiRequest.newContext({ baseURL: server.url(), extraHTTPHeaders: { origin: server.url() } })
  try {
    const researchId = await readyResearch(page, server, 'SYNTHETIC: How are molecule release schedules compared? [report-banned-word]')
    await page.locator('.report-ready').getByRole('button', { name: 'Write report' }).click()
    const researchPath = `/api/researches/${researchId}`
    await expect.poll(async () => {
      const view = await (await api.get(researchPath)).json()
      return view.runs.find((run: { kind: string }) => run.kind === 'report')?.status
    }, { timeout: 60_000 }).toBe('completed')
    const view = await (await api.get(researchPath)).json()
    const run = view.runs.find((item: { kind: string }) => item.kind === 'report')
    expect(run.error).toEqual(expect.arrayContaining([expect.objectContaining({ rule: 'banned_word', section_id: 'IV' })]))
    const summaries = await (await api.get(`/api/researches/${researchId}/reports`)).json() as { id: string; status: string }[]
    expect(summaries[0].status).toBe('draft')
    const reportId = summaries[0].id
    const report = await (await api.get(`/api/researches/${researchId}/reports/${reportId}`)).json()
    expect(report.status).toBe('draft')
    expect(report.report_version).toBeNull()
    const entry = page.getByRole('button', { name: 'Open evidence report' })
    await expect(entry).toContainText('Evidence report · draft')
    await expect(entry).not.toContainText(/Evidence report · V\d+/)
    await entry.click()
    const sheet = reportSheet(page)
    const header = sheet.locator('.report-document-head')
    await expect(header.locator('p').first()).toContainText(/^DRAFT/)
    await expect(header.locator('p').first()).toHaveText('DRAFT: the assembly check refused the report (banned word)')
    await expect(header).not.toContainText(/Evidence report · V\d+/)
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write'], { origin: server.url() })
    await sheet.getByRole('button', { name: 'Copy Markdown' }).click()
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText().then(text => text.split('\n').find(line => line.trim()) ?? ''))).toBe('> DRAFT: the assembly check refused the report (banned word).')
    const downloaded = page.waitForEvent('download')
    await sheet.getByRole('button', { name: 'Download .md' }).click()
    const file = await downloaded
    expect(file.suggestedFilename()).toMatch(/^report-.*-draft\.md$/)
    expect(file.suggestedFilename()).not.toContain('-v1')
    const downloadedLatex = page.waitForEvent('download')
    await sheet.getByRole('button', { name: 'Download LaTeX' }).click()
    expect((await downloadedLatex).suggestedFilename()).toMatch(/^report-.*-draft-latex\.zip$/)
    await toastsOff(page)
    await header.scrollIntoViewIfNeeded()
    await shot(page, 'report-draft-desktop')
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'Use dark theme' }).click()
    await entry.click()
    await header.scrollIntoViewIfNeeded()
    await shot(page, 'report-draft-dark-desktop')
    await page.setViewportSize({ width: 390, height: 844 })
    await header.scrollIntoViewIfNeeded()
    await shot(page, 'report-draft-dark-390')
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'Use light theme' }).click()
    await entry.click()
    await header.scrollIntoViewIfNeeded()
    await shot(page, 'report-draft-390')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  } finally { await api.dispose(); await page.close(); await server.stop() }
})

test('an empty section pauses the report and can be cancelled', async ({ browser }) => {
  const server = new ReportServer(8803)
  await server.start()
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const api = await apiRequest.newContext({ baseURL: server.url(), extraHTTPHeaders: { origin: server.url() } })
  try {
    const researchId = await readyResearch(page, server, 'SYNTHETIC: How are molecule release schedules compared? [report-empty-section]')
    await page.locator('.report-ready').getByRole('button', { name: 'Write report' }).click()
    const researchPath = `/api/researches/${researchId}`
    await expect.poll(async () => {
      const view = await (await api.get(researchPath)).json()
      return view.runs.find((run: { kind: string }) => run.kind === 'report')?.status
    }, { timeout: 60_000 }).toBe('paused')
    const view = await (await api.get(researchPath)).json()
    const run = view.runs.find((item: { kind: string }) => item.kind === 'report')
    expect(run.pause_reason).toBe('section_must_be_rewritten')
    expect(run.error).toEqual({ sections: ['IV'], reasons: [{ section_id: 'IV', code: 'empty_section', detail: 'section has no claims or insufficient-evidence entries' }] })
    await expect(page.getByText('Report paused').first()).toBeVisible()
    await page.getByRole('button', { name: 'Report sections' }).click()
    await expect(page.getByText('IV: must be written again: the section had no claims or explanation of missing evidence')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Resume' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Cancel', exact: true })).toBeVisible()
    const summaries = await (await api.get(`/api/researches/${researchId}/reports`)).json() as { id: string; status: string }[]
    expect(summaries[0].status).toBe('in_progress')
    const reportId = summaries[0].id
    const entry = page.getByRole('button', { name: 'Open evidence report' })
    await expect(entry).not.toContainText(/Evidence report · V\d+/)
    await toastsOff(page)
    await page.getByText('IV: must be written again: the section had no claims or explanation of missing evidence').scrollIntoViewIfNeeded()
    await shot(page, 'report-paused-desktop')
    await page.emulateMedia({ colorScheme: 'dark' })
    await shot(page, 'report-paused-dark-desktop')
    await entry.click()
    const sheet = reportSheet(page)
    await expect(sheet.locator('.report-document-head')).toContainText('Paused: A section must be written again.')
    await expect(section(page, 'IV')).toContainText('This section was not validated and must be written again: the section had no claims or explanation of missing evidence.')
    await expect(sheet.getByRole('button', { name: 'Copy Markdown' })).toBeDisabled()
    await expect(sheet.getByRole('button', { name: 'Download .md' })).toBeDisabled()
    await expect(sheet.getByRole('button', { name: 'Download LaTeX' })).toBeDisabled()
    const exportResponse = await api.get(`/api/researches/${researchId}/reports/${reportId}/export?format=markdown`)
    expect(exportResponse.status()).toBe(409)
    await section(page, 'IV').scrollIntoViewIfNeeded()
    await shot(page, 'report-paused-sheet-dark-desktop')
    await page.keyboard.press('Escape')
    await page.emulateMedia({ colorScheme: 'light' })
    await entry.click()
    await expect(reportSheet(page).locator('.report-document-head')).toContainText('Paused: A section must be written again.')
    await section(page, 'IV').scrollIntoViewIfNeeded()
    await shot(page, 'report-paused-sheet-desktop')
    await page.keyboard.press('Escape')
    await page.setViewportSize({ width: 390, height: 844 })
    await page.getByText('IV: must be written again: the section had no claims or explanation of missing evidence').scrollIntoViewIfNeeded()
    await shot(page, 'report-paused-390')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
    await page.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect.poll(async () => {
      const next = await (await api.get(researchPath)).json()
      return next.runs.find((item: { id: string }) => item.id === run.id)?.status
    }).toBe('cancelled')
    await expect(page.getByRole('button', { name: /^Report cancelled/ })).toBeVisible()
    const after = await (await api.get(`/api/researches/${researchId}/reports`)).json() as { id: string; status: string }[]
    expect(after[0].status).not.toBe('valid')
  } finally { await api.dispose(); await page.close(); await server.stop() }
})

test('report failure labels use codes only in English and Turkish, with bounded assembly rules', () => {
  try {
    for (const language of ['en', 'tr'] as const) {
      setUiLanguage(language)
      expect(failedSectionReasonText('anchor_not_in_cell_evidence')).toBe(language === 'en'
        ? 'a cited quote was not found in that table cell’s stored evidence'
        : 'atıf yapılan alıntı o tablo hücresinin saklı kanıtında bulunamadı')
      expect(failedSectionReasonText('unknown_future_code')).toBe('unknown future code')
      for (const code of ['anchor_not_in_passage', 'unknown_passage_id', 'unknown_cell_id', 'unknown_source_id',
        'unknown_column_id', 'empty_section', 'model_mismatch', 'invalid_model_output', 'schema_invalid', 'invalid_json', 'envelope_mismatch']) {
        expect(failedSectionReasonText(code)).not.toContain('_')
      }
      const entries = ['banned_word', 'banned_word', 'empty_section', 'unknown_rule', 'fourth_rule', 'fifth_rule']
        .map(rule => ({ rule, section_id: 'IV', detail: 'SYNTHETIC model text cel_REALSECRET psg_REALSECRET' }))
      entries.unshift({ rule: 'equation_text_source_warning', section_id: 'IV', detail: 'WARNING: secret' })
      const header = reportAssemblyDraftText(entries)
      expect(header).toContain(language === 'en' ? 'banned word, empty section, unknown rule and 2 more' : 'yasak sözcük, boş bölüm, unknown rule ve 2 kural daha')
      expect(header).not.toMatch(/secret|SYNTHETIC|REALSECRET|warning|fourth|fifth/)
      expect(reportAssemblyDraftText(null)).toBe('')
      expect(reportAssemblyDraftText({ reasons: [] })).toBe('')
      expect(reportAssemblyDraftText([entries[0]])).toBe('')
      // A warning-shaped rule without the recorded WARNING: prefix is still an error.
      expect(reportAssemblyDraftText([{ rule: 'odd_warning', detail: 'ERROR: secret' }])).toContain('odd warning')
    }
  } finally { setUiLanguage('en') }
})

test('a bad cell anchor fails after one repair and displays only the stored reason code', async ({ browser }) => {
  const server = new ReportServer(8804)
  await server.start()
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const api = await apiRequest.newContext({ baseURL: server.url(), extraHTTPHeaders: { origin: server.url() } })
  const reason = 'a cited quote was not found in that table cell’s stored evidence'
  try {
    const researchId = await readyResearch(page, server, 'SYNTHETIC: How are molecule release schedules compared? [report-bad-anchor]')
    await page.locator('.report-ready').getByRole('button', { name: 'Write report' }).click()
    const researchPath = `/api/researches/${researchId}`
    await expect.poll(async () => {
      const view = await (await api.get(researchPath)).json()
      return view.runs.find((run: { kind: string }) => run.kind === 'report')?.status
    }, { timeout: 60_000 }).toBe('paused')
    const view = await (await api.get(researchPath)).json()
    const run = view.runs.find((item: { kind: string }) => item.kind === 'report')
    expect(run.pause_reason).toBe('section_failed')
    expect(run.error.reasons[0]).toMatchObject({ section_id: 'IV', code: 'anchor_not_in_cell_evidence' })
    await page.getByRole('button', { name: 'Report sections' }).click()
    const timeline = page.getByText(`IV failed: ${reason}`, { exact: true })
    await expect(timeline).toBeVisible()
    const summaries = await (await api.get(`/api/researches/${researchId}/reports`)).json()
    const reportPath = `/api/researches/${researchId}/reports/${summaries[0].id}`
    const report = await (await api.get(reportPath)).json()
    const iv = report.sections.find((item: { section_id: string }) => item.section_id === 'IV')
    expect(iv.validation.issues[0].code).toBe('anchor_not_in_cell_evidence')
    expect(iv.claims).toEqual([])
    const secret = 'SYNTHETIC model-written detail cel_REALSECRET psg_REALSECRET'
    iv.validation.issues[0] = { ...iv.validation.issues[0], message: secret, detail: secret }
    await page.route(`**${reportPath}`, route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(report) }))
    const entry = page.getByRole('button', { name: 'Open evidence report' })
    for (const dark of [false, true]) {
      if (dark) await page.getByRole('button', { name: 'Use dark theme' }).click()
      for (const width of [1440, 390]) {
        await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
        await timeline.scrollIntoViewIfNeeded()
        await expect(timeline).not.toContainText(/REALSECRET|missing anchor|cel_|psg_|not found in one stored/)
        await shot(page, `report-bad-anchor-timeline-${dark ? 'dark' : 'light'}-${width}`)
        await entry.click()
        const notice = section(page, 'IV').locator('.notice')
        await expect(section(page, 'IV')).toContainText(`This section was not validated and must be written again: ${reason}.`)
        await expect(section(page, 'IV')).not.toContainText(/REALSECRET|missing anchor|cel_|psg_|model-written/)
        await expect(reportSheet(page).getByRole('button', { name: 'Copy Markdown' })).toBeDisabled()
        await expect(reportSheet(page).getByRole('button', { name: 'Download .md' })).toBeDisabled()
        await notice.scrollIntoViewIfNeeded()
        await shot(page, `report-bad-anchor-sheet-${dark ? 'dark' : 'light'}-${width}`)
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
        await page.keyboard.press('Escape')
      }
      await page.setViewportSize({ width: 1440, height: 900 })
    }
    // Historical sections without reasons retain the original notice.
    iv.validation = { issues: [] }
    await entry.click()
    await expect(section(page, 'IV')).toContainText('This section was not validated and must be written again.')
    await page.keyboard.press('Escape')
    const historicalView = { ...view, runs: view.runs.map((item: { id: string; error: unknown }) => item.id === run.id
      ? { ...item, error: { sections: ['IV'] } } : item) }
    await page.route(`**${researchPath}`, route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(historicalView) }))
    await page.reload()
    await page.getByRole('button', { name: 'Report sections' }).click()
    await expect(page.getByText('IV failed', { exact: true })).toBeVisible()
    expect((await api.get(`${reportPath}/export?format=markdown`)).status()).toBe(409)
    expect((await (await api.get(researchPath)).json()).runs.find((item: { id: string }) => item.id === run.id).status).toBe('paused')
  } finally { await api.dispose(); await page.close(); await server.stop() }
})
