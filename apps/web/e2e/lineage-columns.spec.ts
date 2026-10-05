import { expect, request as apiRequest, test, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'

// Synthetic sources and the fixture's scripted adapter only; no cell-quality measurement.
const REPO = path.resolve(process.cwd(), '..', '..')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
const PORT = nextPort()
const URL = `http://127.0.0.1:${PORT}`
const NAMES = ['Problem addressed', 'Established or changed', 'Uncertainty left']
const HINT = 'This column feeds the development lines and stays a text column.'
mkdirSync(OUT, { recursive: true })

class LineageServer {
  private proc?: ChildProcess
  async start() {
    const data = mkdtempSync(path.join(tmpdir(), 'deixis-l1-'))
    this.proc = spawn(process.env.DEIXIS_TEST_PYTHON ?? path.join(REPO, '.venv/bin/python'),
      [path.join(REPO, 'tests/acceptance/fixture_server.py'), '--data-dir', data, '--port', String(PORT)],
      { cwd: REPO, env: { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: `${REPO}/backend:${REPO}` }, stdio: 'inherit' })
    await expect.poll(async () => { try { return (await fetch(`${URL}/api/health`)).ok } catch { return false } }).toBe(true)
  }
  async stop() {
    const proc = this.proc
    if (!proc || proc.exitCode !== null) return
    const ended = new Promise(resolve => proc.once('exit', resolve))
    proc.kill('SIGTERM')
    await ended
  }
}

async function screenshots(page: Page, state: 'toolbar' | 'added' | 'sheet') {
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 })
    for (const theme of ['light', 'dark']) {
      await page.evaluate(theme => localStorage.setItem('deixis-theme', theme), theme)
      await page.reload()
      await page.getByRole('tab', { name: /Evidence/ }).click()
      if (state === 'sheet') {
        await page.locator('.evidence-col-head').filter({ hasText: NAMES[0] }).click()
        await expect(page.getByRole('dialog', { name: 'Edit column' })).toContainText(HINT)
      } else if (state === 'toolbar') {
        await expect(page.getByRole('button', { name: 'Add development columns' })).toBeVisible()
      } else {
        await expect(page.locator('.evidence-col-head')).toHaveCount(4)
        await page.locator('.evidence-col-head').filter({ hasText: NAMES[0] }).scrollIntoViewIfNeeded()
      }
      // The page already scrolls sideways on a phone (long fill-button label, wide grid); only the new control must stay inside the viewport.
      if (state === 'toolbar') {
        await expect.poll(() => page.getByRole('button', { name: 'Add development columns' }).evaluate(el => { const r = el.getBoundingClientRect(); return r.left >= 0 && r.right <= window.innerWidth })).toBe(true)
      }
      if (state === 'sheet') {
        await expect.poll(() => page.locator('.evidence-form').evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
      }
      await page.screenshot({ path: path.join(OUT, `lineage-${state}-${width}-${theme}.png`), animations: 'disabled' })
    }
  }
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.evaluate(() => localStorage.setItem('deixis-theme', 'light'))
  await page.reload()
  await page.getByRole('tab', { name: /Evidence/ }).click()
}

test.describe('explicit development columns', () => {
  const server = new LineageServer()
  test.beforeAll(async () => { await server.start() })
  test.afterAll(async () => { await server.stop() })

  test('toolbar adds persistent roles, hides when complete, returns after removal, and locks the editor format', async ({ page }) => {
    const api = await apiRequest.newContext({ baseURL: URL, extraHTTPHeaders: { origin: URL } })
    try {
      const csrf = (await (await api.get('/api/session')).json()).csrf_token as string
      await page.goto(URL)
      await page.getByLabel('Research question').fill('SYNTHETIC: Which methods schedule molecule releases?')
      await page.getByRole('button', { name: 'Start research' }).click()
      await page.waitForURL(/#\/research\//)
      const rid = page.url().split('/research/')[1].split('/')[0]
      await expect(page.getByText('Ran search & screening')).toBeVisible()
      await page.getByRole('tab', { name: /Sources/ }).click()
      const row = page.locator('.source-row:not(.is-other-version)').filter({ hasText: 'SYNTHETIC molecule release scheduling with bisection' })
      await row.getByRole('button', { name: 'Include' }).click()
      await expect(row.getByRole('button', { name: 'Include' })).toBeDisabled()
      const base = `/api/researches/${rid}/tables`
      const created = await api.post(base, { data: { title: 'Synthetic development' }, headers: { 'x-deixis-csrf': csrf } })
      expect(created.status()).toBe(201)
      const table = await created.json()
      const tableUrl = `${base}/${table.table.id}`
      const initial = await api.post(`${tableUrl}/columns`, { data: { name: 'Synthetic method', instruction: 'Record the method stated by the source.', answer_format: 'text', expected_version: table.table.version }, headers: { 'x-deixis-csrf': csrf } })
      expect(initial.status()).toBe(201)
      await page.reload()
      await page.getByRole('tab', { name: /Evidence/ }).click()
      await screenshots(page, 'toolbar')
      await page.locator('.evidence-toolbar').getByRole('button', { name: 'Add development columns' }).click()
      await expect(page.getByRole('status').filter({ hasText: 'Development columns added.' })).toBeVisible()
      await expect(page.getByRole('button', { name: 'Add development columns' })).toHaveCount(0)
      await expect(page.locator('.evidence-col-head')).toHaveCount(4)
      for (const name of NAMES) await expect(page.locator('.evidence-col-head').filter({ hasText: name })).toHaveCount(1)
      await screenshots(page, 'added')
      await screenshots(page, 'sheet')
      await page.locator('.evidence-col-head').filter({ hasText: NAMES[0] }).click()
      const editor = page.getByRole('dialog', { name: 'Edit column' })
      await expect(editor.getByRole('radio')).toHaveCount(4)
      for (const radio of await editor.getByRole('radio').all()) await expect(radio).toBeDisabled()
      await expect(editor).toContainText(HINT)
      await editor.getByLabel('Short name').fill('Renamed problem')
      await editor.getByLabel('Instruction').fill('Record the problem in the source’s own terms.')
      await editor.getByRole('button', { name: 'Save column' }).click()
      await expect(page.locator('.evidence-col-head').filter({ hasText: 'Renamed problem' })).toBeVisible()
      await page.locator('.evidence-col-head').filter({ hasText: NAMES[2] }).click()
      await page.getByRole('dialog', { name: 'Edit column' }).getByRole('button', { name: 'Remove column' }).click()
      await page.getByRole('dialog', { name: 'Remove column?' }).getByRole('button', { name: 'Remove column', exact: true }).click()
      const button = page.getByRole('button', { name: 'Add development columns' })
      await expect(button).toBeVisible()
      await expect(page.locator('.evidence-col-head')).toHaveCount(3)
      // Reach the returned action by tabbing from its immediately preceding toolbar action.
      await page.locator('.evidence-toolbar').getByRole('button', { name: 'Add column', exact: true }).focus()
      await page.keyboard.press('Tab')
      await expect(button).toBeFocused()
      await page.keyboard.press('Enter')
      await expect(button).toHaveCount(0)
      await expect(page.locator('.evidence-col-head')).toHaveCount(4)
      await page.reload()
      await page.getByRole('tab', { name: /Evidence/ }).click()
      await expect(page.locator('.evidence-col-head')).toHaveCount(4)
      const persisted = await (await api.get(tableUrl)).json()
      expect(persisted.columns.filter((c: { lineage_role: string | null }) => c.lineage_role)).toHaveLength(3)

      const empty = await api.post(base, { data: { title: 'Synthetic empty table' }, headers: { 'x-deixis-csrf': csrf } })
      expect(empty.status()).toBe(201)
      const emptyTable = await empty.json()
      await page.reload()
      await page.getByRole('tab', { name: /Evidence/ }).click()
      await page.getByLabel('Table', { exact: true }).selectOption(emptyTable.table.id)
      await expect(page.locator('.evidence-toolbar').getByRole('button', { name: 'Add development columns' })).toHaveCount(0)
      await page.getByRole('button', { name: 'Add development columns' }).click()
      await expect(page.getByRole('button', { name: 'Add development columns' })).toHaveCount(0)
      await expect(page.locator('.evidence-col-head')).toHaveCount(3)
      for (const name of NAMES) await expect(page.locator('.evidence-col-head').filter({ hasText: name })).toHaveCount(1)
    } finally {
      await api.dispose()
    }
  })
})
