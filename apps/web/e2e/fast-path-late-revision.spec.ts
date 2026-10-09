import { expect, test } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'

// Stored synthetic [late-pdf] scenario; the Python fixture executes D255 with FakeAdapter.
const REPO = path.resolve(process.cwd(), '..', '..')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? '/tmp/deixis-fp6-acceptance')
const port = nextPort()
const url = `http://127.0.0.1:${port}`
let proc: ChildProcess | undefined
let rid = ''

test.beforeAll(async () => {
  mkdirSync(OUT, { recursive: true })
  const data = mkdtempSync(path.join(tmpdir(), 'deixis-fp6-browser-'))
  proc = spawn(path.join(REPO, '.venv/bin/python'), [path.join(REPO, 'tests/acceptance/fixture_server.py'), '--data-dir', data, '--port', String(port)], {
    cwd: REPO, env: { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', DEIXIS_FIXTURE_LATE_REVISION: 'on' }, stdio: 'inherit',
  })
  await expect.poll(async () => {
    try { return (await fetch(`${url}/api/health`)).ok } catch { return false }
  }, { timeout: 30_000 }).toBe(true)
  const records = await (await fetch(`${url}/api/researches`)).json()
  rid = records[0].id
})

test.afterAll(async () => {
  if (proc && proc.exitCode === null) {
    const ended = new Promise(resolve => proc!.once('exit', resolve))
    proc.kill('SIGTERM')
    await ended
  }
})

for (const width of [1440, 390]) {
  test(`[late-pdf] unverified revision keeps V1 as the main answer at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.route(`${url}/api/researches/${rid}`, async route => {
      const response = await route.fetch()
      const view = await response.json()
      // Synthetic API state: the backend regression separately exercises failed validation.
      view.answers[0].status = 'unverified_draft'
      view.answers[0].review = null
      view.answers[1].late_revision_status.status = 'failed'
      view.answers[1].late_revision_status.skip_reason = 'revision_unverified'
      await route.fulfill({ response, json: view })
    })
    await page.goto(`${url}/#/research/${rid}`)
    await expect(page.locator('#research-answer')).toContainText('V1')
    await expect(page.locator('#research-answer')).not.toContainText('Updated with full text')
    await page.locator('#research-answer').click()
    await expect(page.locator('.report-content')).toBeVisible()
    await expect(page.locator('.report-content')).not.toContainText('Full text added for')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
    await page.screenshot({ path: path.join(OUT, `late-pdf-unverified-${width}.png`), fullPage: true })
  })

  test(`[late-pdf] revision label and previous artifact at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto(`${url}/#/research/${rid}`)
    await expect(page.locator('#research-answer')).toContainText('Updated with full text')
    await page.locator('#research-answer').click()
    await expect(page.locator('.report-content')).toContainText('Full text added for 1 sources since V1.')
    await expect(page.locator('.report-content .support-badge').filter({ hasText: 'Updated with full text' })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
    await page.screenshot({ path: path.join(OUT, `late-pdf-${width}.png`), fullPage: true })
    const view = await (await fetch(`${url}/api/researches/${rid}`)).json()
    expect(view.answers).toHaveLength(2)
    expect(view.answers.map((a: { report_version: number }) => a.report_version)).toEqual([2, 1])
    expect(view.answers[0].review).not.toBeNull()
  })
}
