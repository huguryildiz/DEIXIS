import { expect, request as apiRequest, test, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

// Synthetic records and one fixed extraction failure; this tests the report boundary, not model quality.
const REPO = path.resolve(process.cwd(), '..', '..')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
const PORT = 8804 // Existing specs use 8777–8799 and 8801–8803; P17 has its own server and library.
const URL = `http://127.0.0.1:${PORT}`
const FAILED = 'SYNTHETIC molecule release scheduling with bisection'
const NOTE = '1 of 2 sources did not complete the table (missing cells: 1).'
mkdirSync(OUT, { recursive: true })

async function screenshots(page: Page, state: 'choice' | 'sheet') {
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 })
    for (const theme of ['light', 'dark']) {
      await page.evaluate(theme => {
        localStorage.setItem('deixis-theme', theme)
        document.documentElement.classList.toggle('dark', theme === 'dark')
        document.querySelector('.app')?.classList.toggle('dark', theme === 'dark')
      }, theme)
      // Reload applies the actual theme prop to portaled sheets too.
      await page.reload()
      await page.getByRole('tab', { name: 'Answer' }).click()
      if (state === 'sheet') await page.getByRole('button', { name: 'Open evidence report' }).click()
      const surface = state === 'choice' ? page.locator('.report-ready') : page.locator('.report-sheet')
      await expect(surface).toContainText(NOTE)
      await surface.scrollIntoViewIfNeeded()
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
      if (state === 'sheet') {
        await expect.poll(() => page.locator('.report-scroll').evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
      }
      await page.screenshot({ path: path.join(OUT, `report-missing-${state}-${width}-${theme}.png`), animations: 'disabled' })
    }
  }
}

test('explicitly write a report with a recorded failed row and disclose it in the sheet and export', async ({ browser }) => {
  const data = mkdtempSync(path.join(tmpdir(), 'deixis-p17-'))
  let proc: ChildProcess | undefined
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const api = await apiRequest.newContext({ baseURL: URL, extraHTTPHeaders: { origin: URL } })
  try {
    proc = spawn(process.env.DEIXIS_TEST_PYTHON ?? path.join(REPO, '.venv/bin/python'),
      [path.join(REPO, 'tests/acceptance/fixture_server.py'), '--data-dir', data, '--port', String(PORT)],
      { cwd: REPO, env: { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: `${REPO}/backend:${REPO}` }, stdio: 'inherit' })
    await expect.poll(async () => { try { return (await fetch(`${URL}/api/health`)).ok } catch { return false } }).toBe(true)
    const csrf = (await (await api.get('/api/session')).json()).csrf_token as string
    await page.goto(URL)
    await page.getByLabel('Research question').fill('SYNTHETIC: How are molecule release schedules compared? [fill-fails-one-row]')
    await page.getByRole('button', { name: 'Start research' }).click()
    await page.waitForURL(/#\/research\//)
    const rid = page.url().split('/research/')[1].split('/')[0]
    await expect(page.getByText('Ran search & screening')).toBeVisible()
    await page.getByRole('tab', { name: /Sources/ }).click()
    for (const title of [FAILED, 'SYNTHETIC relay budget allocation']) {
      const row = page.locator('.source-row:not(.is-other-version)').filter({ hasText: title })
      await row.getByRole('button', { name: 'Include' }).click()
      await expect(row.getByRole('button', { name: 'Include' })).toBeDisabled()
    }
    await page.getByRole('tab', { name: /Evidence/ }).click()
    await page.getByRole('button', { name: /Add a column/ }).click()
    const editor = page.getByRole('dialog', { name: 'Add column' })
    await editor.getByLabel('Short name').fill('SYNTHETIC method')
    await editor.getByLabel('Instruction').fill('Record the method named by the source.')
    await editor.getByRole('button', { name: 'Add column' }).click()
    await page.getByRole('button', { name: /^Fill empty cells/ }).click()
    const toolbar = page.locator('.evidence-toolbar')
    await expect(toolbar.getByRole('button', { name: 'Write the report with missing rows' })).toBeEnabled({ timeout: 60_000 })
    await expect(toolbar.getByRole('button', { name: 'Write report', exact: true })).toHaveCount(0)
    await expect(page.locator('.notice')).toContainText(NOTE)
    const tables = await (await api.get(`/api/researches/${rid}/tables`)).json()
    const tableId = tables[0].id as string
    expect(tables[0].report_ready).toMatchObject({ ready: false, can_continue_with_failed: true, failed_rows: 1, failed_cells: 1, included_rows: 2 })
    const refused = await api.post(`/api/researches/${rid}/reports`, { data: { table_id: tableId }, headers: { 'x-deixis-csrf': csrf } })
    expect(refused.status()).toBe(409)
    expect(await refused.text()).toContain('Include sources and fill every active evidence-table column before starting a report')
    await page.getByRole('tab', { name: 'Answer' }).click()
    const panel = page.locator('.report-ready')
    await expect(panel).toContainText(NOTE)
    await expect(panel.getByRole('button', { name: 'Write report', exact: true })).toHaveCount(0)
    await screenshots(page, 'choice')
    await panel.getByRole('button', { name: 'Write the report with missing rows' }).click()
    await expect.poll(async () => {
      const view = await (await api.get(`/api/researches/${rid}`)).json()
      return view.runs.find((run: { kind: string }) => run.kind === 'report')?.status
    }, { timeout: 60_000 }).toBe('completed')
    const summaries = await (await api.get(`/api/researches/${rid}/reports`)).json()
    const reportId = summaries[0].id as string
    const report = await (await api.get(`/api/researches/${rid}/reports/${reportId}`)).json()
    expect(report.missing_rows.counts).toEqual({ included: 2, completed: 1, failed: 1, cells_total: 2, cells_missing: 1 })
    expect(report.missing_rows.failed_rows[0].title).toBe(FAILED)
    expect(report.table_i.rows.filter((row: { failed?: boolean }) => row.failed)).toHaveLength(1)
    await page.getByRole('button', { name: 'Open evidence report' }).click()
    const sheet = page.locator('.report-sheet')
    await expect(sheet.locator('.report-document > .notice').first()).toContainText(NOTE)
    await expect(sheet.locator('.report-document > .notice').first()).toContainText(report.missing_rows.failed_rows[0].source_key)
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write'], { origin: URL })
    await sheet.getByRole('button', { name: 'Copy Markdown' }).click()
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toContain(NOTE)
    const exported = await api.get(`/api/researches/${rid}/reports/${reportId}/export?format=markdown`)
    expect(exported.status()).toBe(200)
    expect(await exported.text()).toContain(report.missing_rows.failed_rows[0].source_key)
    expect(await exported.text()).toContain('invalid model output')
    await screenshots(page, 'sheet')
  } finally {
    await page.close()
    await api.dispose()
    if (proc && proc.exitCode === null) {
      const ended = new Promise(resolve => proc?.once('exit', resolve))
      proc.kill('SIGTERM')
      await ended
    }
  }
})
