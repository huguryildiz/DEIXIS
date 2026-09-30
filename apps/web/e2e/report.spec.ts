import { expect, request as apiRequest, test, type APIRequestContext, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

// SYNTHETIC records and a scripted report model exercise the UI, not the quality of a research report.
const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = process.env.DEIXIS_TEST_PYTHON ?? path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

class ReportServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-report-'))
  readonly port = 8801
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
