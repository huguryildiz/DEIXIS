import AxeBuilder from '@axe-core/playwright'
import { expect, request, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'
import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import type { ActivityEvent, Asset, AssetText, Passage, RecoveryHistory, ReportDetail, ResearchSummary, ResearchView, Source, TableSummary, TableView, TextRetryOperation } from '../src/api'
import { setUiLanguage, t } from '../src/i18n'

// SYNTHETIC stored inputs and scripted model output. Mocked failures/races do not create backend evidence.
const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = process.env.DEIXIS_TEST_PYTHON ?? path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance', 'reextract-r4')
mkdirSync(OUT, { recursive: true })

class ReextractServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-reextract-r4-'))
  readonly pdfDir = path.join(this.dataDir, 'originals')
  readonly port = 8870
  url() { return `http://127.0.0.1:${this.port}` }
  async start() {
    const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: `${path.join(REPO, 'backend')}:${REPO}`, DEIXIS_FIXTURE_REEXTRACT: 'on' }
    const pdfs = spawnSync(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port), '--write-reextract-pdfs', this.pdfDir], { cwd: REPO, env, encoding: 'utf8' })
    if (pdfs.status !== 0) throw new Error(`Writing synthetic PDFs failed: ${pdfs.stderr}`)
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`${this.url()}/api/health`)).ok) return } catch { /* fixture not ready */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error('Re-extraction fixture server did not start')
  }
  async stop() {
    if (!this.proc || this.proc.exitCode !== null) return
    const exited = new Promise(resolve => this.proc?.once('exit', resolve))
    this.proc.kill('SIGTERM'); await exited
  }
}

const row = (page: Page, title: string) => page.locator('.source-row:not(.is-other-version)').filter({ hasText: title })
const sheet = (page: Page) => page.getByRole('dialog', { name: 'Source details' })
const reportSheet = (page: Page) => page.locator('.report-sheet').last()
const sourcesTab = (page: Page) => page.getByRole('tab', { name: /^Sources/ }).click()
const quiet = async (page: Page) => { for (const button of await page.getByRole('button', { name: 'Dismiss notification' }).all()) await button.click().catch(() => {}) }
const shot = async (page: Page, name: string, record: unknown) => {
  writeFileSync(path.join(OUT, `${name}.json`), JSON.stringify({ evidence: 'synthetic application records; simulated states are labelled', record }, null, 2))
  await page.screenshot({ path: path.join(OUT, `${name}.png`), animations: 'disabled' })
}
async function keyboardTo(page: Page, target: Locator) {
  // Exercise actual Tab navigation, including focusable aria-disabled controls.
  for (let i = 0; i < 240; i++) {
    await page.keyboard.press('Tab')
    if (await target.evaluate(el => el === document.activeElement)) return
  }
  throw new Error('Tab did not reach the recovery control')
}
async function get<T>(api: APIRequestContext, url: string): Promise<T> {
  const response = await api.get(url); expect(response.ok(), url).toBe(true)
  return response.json() as Promise<T>
}

test('R4 synthetic recovery receipts, history and exact cited occurrences', async ({ browser }) => {
  // Includes setup, bilingual simulations and twelve axe runs; individual UI waits stay bounded.
  test.setTimeout(15 * 60_000)
  const started = Date.now()
  const step = (name: string) => console.log(`[R4 +${((Date.now() - started) / 1000).toFixed(1)}s] START ${name}`)
  const server = new ReextractServer()
  let api: APIRequestContext | undefined
  let page: Page | undefined
  try {
    step('fixture server and API session')
    await server.start()
    const session = await request.newContext({ baseURL: server.url(), extraHTTPHeaders: { origin: server.url() } })
    const csrf = (await get<{ csrf_token: string }>(session, '/api/session')).csrf_token
    await session.dispose()
    api = await request.newContext({ baseURL: server.url(), extraHTTPHeaders: { origin: server.url(), 'X-DEIXIS-CSRF': csrf } })
    const client = api
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, colorScheme: 'light' })
    page = await context.newPage()
    const ui = page
    ui.setDefaultTimeout(30_000)
    ui.setDefaultNavigationTimeout(30_000)
    await ui.addInitScript(() => {
      const streams: EventSource[] = []
      Object.assign(window, { __r4Streams: streams })
      const NativeEventSource = window.EventSource
      window.EventSource = class extends NativeEventSource {
        constructor(url: string | URL, options?: EventSourceInit) { super(url, options); streams.push(this) }
      }
    })
    const researches = await get<ResearchSummary[]>(client, '/api/researches')
    const rid = researches.find(r => r.question === 'SYNTHETIC re-extraction research')!.id
    const researchPath = `/api/researches/${rid}`
    const view = () => get<ResearchView>(client, researchPath)
    const events = () => get<ActivityEvent[]>(client, `${researchPath}/events`)
    const source = (v: ResearchView, title: string): Source => v.sources.find(s => s.title === title)!
    const asset = (v: ResearchView, title: string): Asset => source(v, title).access.assets[0]
    const initial = await view()
    const titles = ['SYNTHETIC failed read', 'SYNTHETIC partial legacy read', 'SYNTHETIC locked PDF']
    const a2 = asset(initial, titles[1]), s2 = source(initial, titles[1]).source_version_id
    const retryPath = `${researchPath}/sources/${s2}/assets/${a2.id}/extractions`
    const textPath = `${researchPath}/assets/${a2.id}/text`
    const oldId = a2.text_recovery!.current_extraction_id!
    step('1: initial source controls and interrupted result')
    await ui.goto(`${server.url()}/#/research/${rid}`)
    await sourcesTab(ui)
    await expect(row(ui, titles[0])).toContainText('PDF could not be read')
    await expect(row(ui, titles[0])).toContainText('Text retry was interrupted; no new extraction was published.')
    for (const title of titles.slice(0, 2)) await expect(row(ui, title).getByRole('button', { name: 'Retry text extraction' })).toBeVisible()
    await expect(row(ui, titles[2]).getByRole('button', { name: 'Check PDF text again' })).toBeVisible()
    expect(asset(await view(), titles[0]).text_recovery!.latest_operation!.reason).toBe('process_ended')
    await shot(ui, 'reextract-initial-1280-light', await view())

    step('2a: generate source-linked answer')
    await ui.getByRole('tab', { name: 'Answer', exact: true }).click()
    await ui.getByRole('button', { name: 'Generate source-linked answer', exact: true }).click()
    await expect.poll(async () => (await view()).answers[0]?.status).toBe('structurally_valid')
    const answered = await view()
    const answerEvidence = answered.answers[0].claims.flatMap(c => c.evidence)
    expect(answerEvidence.length).toBeGreaterThan(0)
    const answerPassageId = answerEvidence[0].passage_id
    step('2b: add and fill evidence column')
    await ui.getByRole('tab', { name: /^Evidence/ }).click()
    await ui.getByRole('button', { name: /Add a column/ }).click()
    const editor = ui.getByRole('dialog', { name: 'Add column' })
    await editor.getByLabel('Short name').fill('SYNTHETIC method')
    await editor.getByLabel('Instruction').fill('Record the method named by the source.')
    await editor.getByRole('button', { name: 'Add column', exact: true }).click()
    const summaries = await get<TableSummary[]>(client, `${researchPath}/tables`)
    const tableId = summaries[0].id
    expect((await get<TableView>(client, `${researchPath}/tables/${tableId}`)).columns).toHaveLength(1)
    await ui.getByRole('button', { name: /^Fill empty cells/ }).click()
    await expect(ui.locator('.evidence-toolbar').getByRole('button', { name: 'Write a manuscript draft' })).toBeEnabled({ timeout: 60_000 })
    const table = await get<TableView>(client, `${researchPath}/tables/${tableId}`)
    expect(table.rows.map(r => r.source_version_id)).toEqual([s2])
    const cellPassageId = table.cells[0].current!.evidence[0].passage_id
    step('2c: write report and freeze cited passage IDs')
    await ui.locator('.evidence-toolbar').getByRole('button', { name: 'Write a manuscript draft' }).click()
    await expect.poll(async () => (await view()).reportRuns[0]?.status, { timeout: 60_000 }).toBe('valid')
    const reportId = (await view()).reportRuns[0].id
    const reportPath = `${researchPath}/reports/${reportId}`
    const report = () => get<ReportDetail>(client, reportPath)
    const frozenReport = await report()
    const reportPassageIds = frozenReport.sections.flatMap(s => s.claims.flatMap(c => c.evidence.flatMap(e => e.passage_id ? [e.passage_id] : [])))
    expect(reportPassageIds.length).toBeGreaterThan(0)
    const passageIds = [...new Set([...answerEvidence.map(e => e.passage_id), cellPassageId, ...reportPassageIds])]
    const passage = (pid: string) => get<Passage>(client, `${researchPath}/passages/${pid}`)
    for (const pid of passageIds) {
      const p = await passage(pid)
      expect(p.source.id).toBe(s2); expect(p.physical_page).toBe(1)
      expect(p.occurrence!.is_current).toBe(true)
    }
    step('2d: open current answer citation with exact extraction ID')
    await ui.getByRole('tab', { name: 'Answer', exact: true }).click()
    async function openAnswerCitation() {
      // AnswerBlock renders citations inside its report drawer, opened by the answer artifact.
      await ui.getByRole('button', { name: /^(Open report:|Raporu aç:)/ }).first().click()
      await ui.locator('.report-sheet .legacy-answer .claim .cite-chip').first().click()
    }
    async function closeAnswerCitation() {
      await ui.keyboard.press('Escape')
      await expect(ui.locator('.source-sheet')).toHaveCount(0)
      await ui.keyboard.press('Escape')
      await expect(ui.locator('.report-sheet')).toHaveCount(0)
    }
    const currentRequest = ui.waitForRequest(r => r.url().includes(textPath))
    await openAnswerCitation()
    expect(new URL((await currentRequest).url()).searchParams.get('extraction_id')).toBe(oldId)
    await expect(sheet(ui)).toContainText('SYNTHETIC earlier reading')
    expect((await passage(answerPassageId)).occurrence!.extraction_id).toBe(oldId)
    await closeAnswerCitation()

    // Pre-reservation simulations: no persisted operation, head or event changes.
    step('12a: simulated refusals in English and Turkish')
    await sourcesTab(ui)
    const beforeMocks = { capability: asset(await view(), titles[1]).text_recovery, events: (await events()).length }
    const failures = [
      { status: 409, code: 'file_busy', detail: 'This file is being used by another extraction; try again when it ends.' },
      { status: 409, code: 'run_active', detail: 'A research using this source has an active run; try again when it ends.' },
      { status: 409, code: 'baseline_changed', detail: 'The current extraction changed; read it before retrying.' },
      { status: 422, code: 'not_retryable', detail: 'This extraction is not eligible for a text retry.' },
      { status: 404, code: null, detail: 'File missing' },
      { status: 507, code: 'disk_full', detail: 'DEIXIS could not save because the disk is full. Free some space and try again.' },
    ]
    const retryButton = () => row(ui, titles[1]).getByRole('button', { name: 'Retry text extraction' })
    const mockKeys = new Set<string>()
    for (const failure of failures) {
      // Check the error in both interface languages while the real baseline remains retryable.
      for (const language of ['en', 'tr'] as const) {
        step(`12a: simulated ${failure.code ?? 'file_missing'} / ${language}`)
        setUiLanguage(language)
        await ui.getByRole('button', { name: language === 'tr' ? 'Türkçe' : 'English', exact: true }).click()
        await ui.route(`**${retryPath}`, async route => {
          const body = route.request().postDataJSON() as { mode: string; expected_current_extraction_id: string; idempotency_key: string }
          expect(body.mode).toBe('retry_failed_or_partial'); expect(body.expected_current_extraction_id).toBe(oldId)
          expect(mockKeys.has(body.idempotency_key)).toBe(false); mockKeys.add(body.idempotency_key)
          await route.fulfill({ status: failure.status, contentType: 'application/json', body: JSON.stringify({ detail: failure.detail, ...(failure.code ? { code: failure.code } : {}) }) })
        })
        const target = row(ui, titles[1]).getByRole('button', { name: t('Retry text extraction'), exact: true })
        await target.focus(); await ui.keyboard.press('Enter')
        const message = failure.detail === 'File missing' ? t('The stored PDF is missing; upload it again to restore it.') : t(failure.detail)
        await expect(row(ui, titles[1]).getByRole('alert')).toContainText(message)
        await expect(target).not.toHaveAttribute('aria-disabled', 'true'); await expect(target).toBeFocused()
        const persisted = { capability: asset(await view(), titles[1]).text_recovery, events: (await events()).length }
        expect(persisted).toEqual(beforeMocks)
        await shot(ui, `reextract-simulated-${failure.code ?? 'file-missing'}-${language}`, persisted)
        await ui.unroute(`**${retryPath}`); await quiet(ui)
      }
    }
    step('12b: simulated running receipt, then reload real state')
    setUiLanguage('en'); await ui.getByRole('button', { name: 'English', exact: true }).click()
    const real = await view()
    const running: TextRetryOperation = {
      operation_id: 'simulated_r4_running', asset_id: a2.id, lifecycle: 'running', outcome: null, reason: null, decision_code: null,
      input_observation_id: null, input_integrity: null, candidate_status: null, extraction_id: null, extraction_version: null,
      baseline_extraction_id: oldId, coverage: null, created_at: new Date().toISOString(), finished_at: null,
    }
    await ui.route(`**${retryPath}`, route => route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ ...real, recovery: running }) }))
    await retryButton().click()
    await expect(row(ui, titles[1])).toContainText('Text retry is running…')
    await expect(retryButton()).toHaveAttribute('aria-disabled', 'true')
    expect({ capability: asset(await view(), titles[1]).text_recovery, events: (await events()).length }).toEqual(beforeMocks)
    await shot(ui, 'reextract-simulated-running-1280-light', { persisted: beforeMocks, simulated: running })
    await ui.unroute(`**${retryPath}`); await ui.reload(); await sourcesTab(ui)
    await expect(retryButton()).not.toHaveAttribute('aria-disabled', 'true')

    // Real refusal, restore and promotion; keyboard invokes the real retry.
    step('3: real file-mismatch refusal by keyboard')
    await keyboardTo(ui, retryButton()); await ui.keyboard.press('Enter')
    await expect(row(ui, titles[1])).toContainText('The stored PDF does not match its recorded hash. Upload the same PDF again to restore it, then retry.')
    let recovery = asset(await view(), titles[1]).text_recovery!
    expect(recovery.latest_operation).toMatchObject({ lifecycle: 'completed', outcome: 'refused', reason: 'file_mismatch', decision_code: 'input_not_verified', input_integrity: 'mismatch' })
    expect(recovery.current_extraction_id).toBe(oldId)

    async function replace(title: string, file: string) {
      step(`restore ${title} with ${file}`)
      await quiet(ui)
      const picker = ui.waitForEvent('filechooser')
      await row(ui, title).getByRole('button', { name: 'Replace PDF', exact: true }).click()
      await (await picker).setFiles(path.join(server.pdfDir, file))
      await ui.getByRole('dialog', { name: 'Replace PDF?' }).getByRole('button', { name: 'Replace PDF', exact: true }).click()
      await expect(ui.locator('.toast')).toContainText('File restored. Stored text has not been retried.')
      await expect(ui.locator('.toast')).not.toContainText('PDF replaced')
      await expect(row(ui, title)).toContainText('File restored. Stored text has not been retried.')
      const restored = asset(await view(), title)
      expect(restored.id).toBe(asset(initial, title).id)
      expect(restored.text_recovery!.current_extraction_id).toBe(asset(initial, title).text_recovery!.current_extraction_id)
      expect(restored.text_recovery!.latest_file_restore).toMatchObject({ lifecycle: 'completed', outcome: 'file_restored', before_integrity: 'mismatch', retained: true })
      expect((await events()).some(e => e.type === 'asset_file_restore_finished')).toBe(true)
    }
    step('4: file-only S2 restore')
    await replace(titles[1], 'P2.pdf')
    step('5: S2 text promotion and old occurrence checks')
    await retryButton().click()
    await expect(row(ui, titles[1])).toContainText('File restored. Text extracted again. Future work uses this extraction; earlier evidence keeps its cited text.')
    recovery = asset(await view(), titles[1]).text_recovery!
    expect(recovery.latest_operation).toMatchObject({ lifecycle: 'completed', outcome: 'promoted', decision_code: 'text_updated' })
    expect(recovery.current_extraction_id).not.toBe(oldId)
    await expect(row(ui, titles[1]).locator('.text-recovery-result')).toBeFocused()
    for (const pid of passageIds) {
      const p = await passage(pid); expect(p.evidence_status).toBe('text_superseded'); expect(p.occurrence!.is_current).toBe(false)
    }
    expect((await events()).some(e => e.type === 'asset_text_retried')).toBe(true)
    step('6: S1 restore and failed-read recovery')
    await replace(titles[0], 'P1.pdf')
    await row(ui, titles[0]).getByRole('button', { name: 'Retry text extraction', exact: true }).click()
    await expect(row(ui, titles[0])).toContainText('Text extracted again.')
    expect(asset(await view(), titles[0]).text_recovery!.latest_operation).toMatchObject({ outcome: 'promoted', decision_code: 'recovered_text' })
    step('7: S3 password diagnosis')
    await row(ui, titles[2]).getByRole('button', { name: 'Check PDF text again', exact: true }).click()
    await expect(row(ui, titles[2])).toContainText('This PDF requires a password. Text was not recovered. Replace it with an unlocked copy.')
    expect(asset(await view(), titles[2]).text_recovery).toMatchObject({ diagnostic_only: true, reason: 'password_protected', latest_operation: { outcome: 'diagnosis_updated', decision_code: 'password_diagnosed' } })
    await expect(row(ui, titles[2]).getByRole('button', { name: /Retry text extraction|Check PDF text again|OCR/ })).toHaveCount(0)
    await expect(row(ui, titles[2])).not.toContainText('Text extracted again')

    // Open the exact frozen occurrence from the answer, a cell and the report.
    step('8a: frozen answer citation, current comparison and PDF notice')
    async function assertCited() {
      await expect(sheet(ui)).toContainText('SYNTHETIC earlier reading')
      await expect(sheet(ui)).not.toContainText('NEW2')
      await expect(sheet(ui).locator('mark.citation-highlight').first()).toBeVisible()
      await expect(sheet(ui)).toContainText('This passage comes from an earlier text extraction')
      await expect(sheet(ui)).toContainText('Which bytes this text was read from was not recorded.')
      await expect(sheet(ui)).toContainText('The PDF file was restored after this text was extracted.')
    }
    await ui.getByRole('tab', { name: 'Answer', exact: true }).click()
    const citedRequest = ui.waitForRequest(r => r.url().includes(textPath))
    await openAnswerCitation()
    expect(new URL((await citedRequest).url()).searchParams.get('extraction_id')).toBe(oldId)
    await assertCited()
    await sheet(ui).getByRole('button', { name: 'Show current text', exact: true }).click()
    await expect(sheet(ui)).toContainText('NEW1'); await expect(sheet(ui)).toContainText('NEW2')
    await expect(sheet(ui)).toContainText('not the cited extraction')
    await expect(sheet(ui).locator('mark.citation-highlight')).toHaveCount(0)
    await expect(sheet(ui).locator('.is-cited-page')).toHaveCount(0)
    await sheet(ui).getByRole('button', { name: 'Back to cited text', exact: true }).click(); await assertCited()
    await sheet(ui).getByRole('tab', { name: 'PDF', exact: true }).click()
    await expect(sheet(ui)).toContainText('The PDF shown is the stored file, restored after this text was extracted. It is not necessarily the bytes this text was read from.')
    expect((await passage(answerPassageId)).occurrence!.file_restored_after).toBe(true)
    await closeAnswerCitation()
    step('8b: cell panel Open in source')
    await ui.getByRole('tab', { name: /^Evidence/ }).click()
    await ui.locator('[data-cell="0:0"]').click()
    await ui.getByRole('dialog', { name: 'SYNTHETIC method', exact: true }).getByRole('button', { name: 'Open in source', exact: true }).first().click()
    await assertCited(); expect((await passage(cellPassageId)).evidence_status).toBe('text_superseded')
    await ui.keyboard.press('Escape'); await ui.keyboard.press('Escape')
    step('8c/9: report freshness notice and report citation')
    await ui.getByRole('tab', { name: 'Answer', exact: true }).click()
    await ui.getByRole('button', { name: 'Open evidence report', exact: true }).click()
    const refreshedReport = await report()
    const count = refreshedReport.passage_freshness.affected.filter(p => p.evidence_status === 'text_superseded').length
    expect(count).toBeGreaterThan(0)
    await expect(reportSheet(ui)).toContainText('Passage freshness compared:')
    await expect(reportSheet(ui)).toContainText(`${count} ${count === 1 ? 'passage this report used is' : 'passages this report used are'} no longer`)
    await expect(reportSheet(ui)).toContainText('Semantic support not checked.')
    await reportSheet(ui).getByRole('button', { name: /^Reference \d+:/ }).first().click(); await assertCited()
    expect((await passage(reportPassageIds[0])).evidence_status).toBe('text_superseded')
    await ui.keyboard.press('Escape'); await ui.keyboard.press('Escape')

    step('10: keyboard history disclosure, operation order and Details')
    await sourcesTab(ui)
    const historyControl = row(ui, titles[1]).getByRole('button', { name: /Text recovery history/ })
    await keyboardTo(ui, historyControl); await ui.keyboard.press('Enter')
    await expect(historyControl).toHaveAttribute('aria-expanded', 'true')
    const history = await get<RecoveryHistory>(client, `${researchPath}/sources/${s2}/assets/${a2.id}/recovery-history`)
    expect(history.text_retries.map(r => r.operation.outcome)).toEqual(['promoted', 'refused'])
    expect(history.file_restores[0].outcome).toBe('file_restored')
    const entries = row(ui, titles[1]).locator('.text-recovery-history > li')
    await expect(entries).toHaveCount(3)
    await expect(entries.nth(0)).toContainText('This extraction became current.')
    await expect(entries.nth(1)).toContainText('File restored; this operation did not retry text.')
    await expect(entries.nth(2)).toContainText('Refused:')
    await entries.nth(0).getByText('Details', { exact: true }).click()
    await expect(entries.nth(0)).toContainText(history.text_retries[0].candidate!.extraction_version)
    step('11: translated Activity event labels')
    await ui.getByRole('tab', { name: 'Activity', exact: true }).click()
    await expect(ui.getByText('PDF text retried', { exact: true }).first()).toBeVisible()
    await expect(ui.getByText('PDF file restore', { exact: true }).first()).toBeVisible()
    await expect(ui.locator('.activity-panel')).not.toContainText('asset_text_retried')
    await expect(ui.locator('.activity-panel')).not.toContainText('asset_file_restore_finished')
    expect((await events()).filter(e => ['asset_text_retried', 'asset_file_restore_finished'].includes(e.type)).length).toBeGreaterThanOrEqual(5)

    // Simulated response-identity mismatch must fall back to the stored single passage.
    step('12c: simulated mismatched document identity')
    await ui.getByRole('tab', { name: 'Answer', exact: true }).click()
    const currentText = await get<AssetText>(client, textPath)
    await ui.route(`**${textPath}?extraction_id=*`, route => route.fulfill({ contentType: 'application/json', body: JSON.stringify(currentText) }))
    await openAnswerCitation()
    await expect(sheet(ui)).toContainText('SYNTHETIC earlier reading')
    await expect(sheet(ui)).not.toContainText('NEW1'); await expect(sheet(ui)).not.toContainText('NEW2')
    await expect(sheet(ui).locator('.asset-text-view')).toHaveCount(0)
    expect((await passage(answerPassageId)).occurrence!.extraction_id).toBe(oldId)
    await shot(ui, 'reextract-simulated-identity-race-1280-light', { passage: await passage(answerPassageId), supplied: currentText.occurrence })
    await closeAnswerCitation(); await ui.unroute(`**${textPath}?extraction_id=*`)
    step('12d: simulated stored caption with figure picture withheld')
    const citedText = await get<AssetText>(client, `${textPath}?extraction_id=${oldId}`)
    const simulatedCaption = { ...citedText, passages: citedText.passages.map((p, i) => i === 0 ? { ...p, text: `${p.text}\n\nFig. 1. SYNTHETIC stored caption.` } : p) }
    let currentFigureRequests = 0
    await ui.route(`**${researchPath}/assets/${a2.id}/figures`, async route => {
      currentFigureRequests += 1
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ figures: [{ page: 1, label: '1', width: 100, height: 100 }] }) })
    })
    await ui.route(`**${textPath}?extraction_id=*`, route => route.fulfill({ contentType: 'application/json', body: JSON.stringify(simulatedCaption) }))
    await openAnswerCitation(); await assertCited()
    await expect(sheet(ui)).toContainText('Figure picture not shown: it would be cut from the current file, not the cited extraction.')
    await expect(sheet(ui).locator('.pdf-text-figure img')).toHaveCount(0)
    expect(currentFigureRequests).toBe(0)
    expect((await passage(answerPassageId)).occurrence!.extraction_id).toBe(oldId)
    await shot(ui, 'reextract-simulated-withheld-figure-1280-light', { passage: await passage(answerPassageId), simulatedCaption: 'Fig. 1. SYNTHETIC stored caption.' })
    await closeAnswerCitation()
    await ui.unroute(`**${researchPath}/assets/${a2.id}/figures`); await ui.unroute(`**${textPath}?extraction_id=*`)
    step('12e: delayed cited document across research-view reload')
    let release!: () => void
    const delayed = new Promise<void>(resolve => { release = resolve })
    await ui.route(`**${textPath}?extraction_id=*`, async route => { const response = await route.fetch(); await delayed; await route.fulfill({ response }) })
    const delayedRequest = ui.waitForRequest(r => r.url().includes(textPath))
    await openAnswerCitation(); await delayedRequest
    // Simulate an EventSource notification to trigger the existing view-reload handler. The API returns real state;
    // the notification is not a stored event and is not counted as backend evidence.
    const refreshed = ui.waitForResponse(r => new URL(r.url()).pathname === researchPath)
    await ui.evaluate(() => {
      const streams = (window as unknown as { __r4Streams: EventSource[] }).__r4Streams
      for (const stream of streams) if (stream.readyState === EventSource.OPEN) stream.dispatchEvent(new MessageEvent('message', { data: 'SYNTHETIC UI notification' }))
    })
    await refreshed
    const stateBeforeRelease = await view()
    release(); await assertCited()
    expect(asset(await view(), titles[1]).text_recovery!.current_extraction_id).toBe(asset(stateBeforeRelease, titles[1]).text_recovery!.current_extraction_id)
    await shot(ui, 'reextract-simulated-delayed-document-1280-light', { passage: await passage(answerPassageId), refreshedView: stateBeforeRelease })
    await closeAnswerCitation(); await ui.unroute(`**${textPath}?extraction_id=*`)

    // Rendered evidence surfaces, both sizes/themes, with axe and paired persisted records.
    for (const width of [1280, 390]) for (const theme of ['light', 'dark'] as const) {
      step(`14: results and history ${width}px / ${theme}`)
      await ui.setViewportSize({ width, height: 900 })
      const dark = await ui.locator('html').evaluate(el => el.classList.contains('dark'))
      if (dark !== (theme === 'dark')) await ui.getByRole('button', { name: theme === 'dark' ? 'Use dark theme' : 'Use light theme', exact: true }).click()
      await quiet(ui); await sourcesTab(ui)
      await expect(ui.locator('html')).toHaveClass(theme === 'dark' ? /dark/ : /^(?!.*\bdark\b).*$/)
      await shot(ui, `reextract-results-${width}-${theme}`, await view())
      if (await historyControl.getAttribute('aria-expanded') !== 'true') await historyControl.click()
      await expect(entries).toHaveCount(3)
      await shot(ui, `reextract-history-${width}-${theme}`, history)
      expect((await new AxeBuilder({ page: ui }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()).violations).toEqual([])
      step(`14: cited sheet ${width}px / ${theme}`)
      await ui.getByRole('tab', { name: 'Answer', exact: true }).click()
      await openAnswerCitation(); await assertCited()
      await shot(ui, `reextract-cited-${width}-${theme}`, await passage(answerPassageId))
      expect((await new AxeBuilder({ page: ui }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()).violations).toEqual([])
      step(`14: current comparison ${width}px / ${theme}`)
      await sheet(ui).getByRole('button', { name: 'Show current text', exact: true }).click()
      await expect(sheet(ui)).toContainText('NEW2')
      await expect(sheet(ui).locator('mark.citation-highlight')).toHaveCount(0)
      await shot(ui, `reextract-current-${width}-${theme}`, await get<AssetText>(client, textPath))
      expect((await new AxeBuilder({ page: ui }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()).violations).toEqual([])
      await closeAnswerCitation()
      step(`14: report notice ${width}px / ${theme}`)
      await ui.getByRole('button', { name: 'Open evidence report', exact: true }).click()
      await expect(reportSheet(ui)).toContainText('Passage freshness compared:')
      await shot(ui, `reextract-report-${width}-${theme}`, await report())
      await ui.keyboard.press('Escape')
    }
    step('14: reduced-motion toggle and jump controls')
    await openAnswerCitation(); await assertCited()
    await ui.emulateMedia({ reducedMotion: 'reduce' })
    await sheet(ui).getByRole('button', { name: 'Go to cited text', exact: true }).click()
    await sheet(ui).getByRole('button', { name: 'Show current text', exact: true }).click()
    await expect(sheet(ui)).toContainText('NEW2')
    await sheet(ui).getByRole('button', { name: 'Go to page', exact: true }).click()
    await sheet(ui).getByRole('button', { name: 'Back to cited text', exact: true }).click(); await assertCited()
    expect((await new AxeBuilder({ page: ui }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()).violations).toEqual([])
    expect((await passage(answerPassageId)).evidence_status).toBe('text_superseded')
    await closeAnswerCitation()
    step('13: Turkish results, history and occurrence notice')
    await ui.getByRole('button', { name: 'Türkçe', exact: true }).click()
    await ui.getByRole('tab', { name: /^Kaynaklar/ }).click()
    await expect(row(ui, titles[0])).toContainText('Metin yeniden çıkarıldı.')
    await expect(row(ui, titles[2])).toContainText('Bu PDF parola gerektiriyor.')
    const trHistory = row(ui, titles[1]).getByRole('button', { name: /Metni yeniden okuma geçmişi/ })
    if (await trHistory.getAttribute('aria-expanded') !== 'true') await trHistory.click()
    await expect(entries).toContainText(['Bu çıkarım kullanıma alındı.', 'Dosya geri yüklendi; bu işlem metni yeniden okumadı.', 'Reddedildi:'])
    for (const sentence of ['Text extracted again.', 'File restored.', 'Future work uses this extraction', 'Not measured:', 'Refused:']) await expect(row(ui, titles[1])).not.toContainText(sentence)
    await ui.getByRole('tab', { name: 'Yanıt', exact: true }).click()
    await openAnswerCitation()
    await expect(sheet(ui).or(ui.getByRole('dialog', { name: 'Kaynak ayrıntıları' }))).toContainText('Bu pasaj önceki bir metin çıkarımından geliyor')
    await expect(ui.locator('.source-sheet')).toContainText('Bu metnin hangi baytlardan okunduğu kaydedilmedi.')
    await expect(ui.locator('.source-sheet')).not.toContainText('This passage comes from')
    await shot(ui, 'reextract-turkish-390-dark', { history: await get<RecoveryHistory>(client, `${researchPath}/sources/${s2}/assets/${a2.id}/recovery-history`), passage: await passage(answerPassageId) })
  } finally {
    step('fixture cleanup')
    setUiLanguage('en')
    await page?.context().close(); await api?.dispose(); await server.stop()
  }
})
