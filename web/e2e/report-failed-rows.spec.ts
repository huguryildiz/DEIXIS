import { expect, request as apiRequest, test, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'
import { openPanel, showAnswer } from './panels'

// Synthetic records and one fixed extraction failure; this tests that failed cells do not stop a report and that the
// report says what it rests on (D68), not model quality.
const REPO = path.resolve(process.cwd(), '..')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
const PORT = nextPort() // P17 has its own server and library.
const URL = `http://127.0.0.1:${PORT}`
const FAILED = 'SYNTHETIC molecule release scheduling with bisection'
const NOTE = '1 of 2 cells has no verified answer.'
const BASIS = 'Basis of this report: 0 of 2 sources were read from full text and 2 from the abstract or metadata only. 1 of 2 table cells could not be verified against a quote'
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
      if (state === 'choice') await openPanel(page, 'table'); else await showAnswer(page)
      if (state === 'sheet') await page.getByRole('button', { name: 'Open evidence report' }).click()
      const surface = state === 'choice' ? page.locator('.notice', { hasText: NOTE }) : page.locator('.report-sheet')
      await expect(surface).toContainText(state === 'choice' ? NOTE : BASIS)
      await surface.scrollIntoViewIfNeeded()
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
      if (state === 'sheet') {
        await expect.poll(() => page.locator('.report-scroll').evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
      }
      await page.screenshot({ path: path.join(OUT, `report-missing-${state}-${width}-${theme}.png`), animations: 'disabled' })
    }
  }
}

test('write a report over a row whose cells failed and name it in the basis note of the sheet and export', async ({ browser }) => {
  const data = mkdtempSync(path.join(tmpdir(), 'deixis-p17-'))
  let proc: ChildProcess | undefined
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const api = await apiRequest.newContext({ baseURL: URL, extraHTTPHeaders: { origin: URL } })
  try {
    proc = spawn(process.env.DEIXIS_TEST_PYTHON ?? path.join(REPO, '.venv/bin/python'),
      [path.join(REPO, 'tests/acceptance/fixture_server.py'), '--data-dir', data, '--port', String(PORT)],
      { cwd: REPO, env: { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: REPO }, stdio: 'inherit' })
    await expect.poll(async () => { try { return (await fetch(`${URL}/api/health`)).ok } catch { return false } }).toBe(true)
        await page.goto(URL)
    await page.getByLabel('Research question').fill('SYNTHETIC: How are molecule release schedules compared? [fill-fails-one-row]')
    await page.getByRole('button', { name: 'Start research' }).click()
    await page.waitForURL(/#\/research\//)
    const rid = page.url().split('/research/')[1].split('/')[0]
    await expect(page.getByText('Ran search & screening')).toBeVisible()
    await openPanel(page, 'sources')
    for (const title of [FAILED, 'SYNTHETIC relay budget allocation']) {
      const row = page.locator('.source-row:not(.is-other-version)').filter({ hasText: title })
      await row.getByRole('button', { name: 'Include' }).click()
      await expect(row.getByRole('button', { name: 'Include' })).toBeDisabled()
    }
    await openPanel(page, 'table')
    await page.getByRole('button', { name: /Add a column/ }).click()
    const editor = page.getByRole('dialog', { name: 'Add column' })
    await editor.getByLabel('Name', { exact: true }).fill('SYNTHETIC method')
    await editor.getByLabel('What should the model look for?').fill('Record the method named by the source.')
    await editor.getByRole('button', { name: 'Add column' }).click()
    await page.getByRole('button', { name: /^Fill empty cells/ }).click()
    const toolbar = page.locator('.evidence-toolbar')
    // No extra choice: the one report button stays, and a plain notice says what the report will lack.
    await expect(toolbar.getByRole('button', { name: 'Write a manuscript draft', exact: true })).toBeEnabled({ timeout: 60_000 })
    await expect(toolbar.getByRole('button', { name: 'Write the report with missing rows' })).toHaveCount(0)
    // The answer's own notices in the thread are .notice too (UI parity S10); this one is the table's.
    await expect(page.locator('.notice', { hasText: NOTE })).toBeVisible()
    const tables = await (await api.get(`/api/researches/${rid}/tables`)).json()
    expect(tables[0].report_ready).toEqual({ ready: true, cells_left: 1, cells_total: 2, included_rows: 2 })
    await screenshots(page, 'choice')
    await toolbar.getByRole('button', { name: 'Write a manuscript draft', exact: true }).click()
    await expect.poll(async () => {
      const view = await (await api.get(`/api/researches/${rid}`)).json()
      return view.runs.find((run: { kind: string }) => run.kind === 'report')?.status
    }, { timeout: 60_000 }).toBe('completed')
    const summaries = await (await api.get(`/api/researches/${rid}/reports`)).json()
    const reportId = summaries[0].id as string
    const report = await (await api.get(`/api/researches/${rid}/reports/${reportId}`)).json()
    expect(report.missing_rows).toBeNull()
    expect(report.basis).toMatchObject({ sources: 2, cells_total: 2, cells_unverified: 1 })
    expect(report.basis.unverified_sources).toHaveLength(1)
    const failed = report.basis.unverified_sources[0]
    expect(failed.title).toBe(FAILED)
    // The failed source stays a row of the report's table.
    expect(report.table_i.rows).toHaveLength(2)
    await showAnswer(page)  // the report card sits on the Answer tab since D230
    await page.getByRole('button', { name: 'Open evidence report' }).click()
    const sheet = page.locator('[data-split-panel]').filter({ has: page.locator('.report-sheet') }).last()
    await expect(sheet.locator('.report-document > .notice').first()).toContainText(BASIS)
    await expect(sheet.locator('.report-document > .notice').first()).toContainText(failed.source_key)
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write'], { origin: URL })
    await sheet.getByRole('button', { name: 'Download report' }).click()
    await page.getByRole('menuitem', { name: /^Copy/ }).click()
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toContain(BASIS)
    const exported = await api.get(`/api/researches/${rid}/reports/${reportId}/export?format=markdown`)
    expect(exported.status()).toBe(200)
    expect(await exported.text()).toContain(`- ${failed.source_key}: 1 of 1 cells not verified`)
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
