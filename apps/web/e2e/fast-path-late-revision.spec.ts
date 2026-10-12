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

type Bib = { answers: { id: string; report_version: number; claims: { evidence: { source_version_id: string }[] }[] }[]; sources: { source_version_id: string; work_id: string; title: string }[] }
// A cited-sources export link names V1's answer and downloads the sources V1's claims cite (titles from the records).
async function expectV1Export(href: string | null) {
  const view = await (await fetch(`${url}/api/researches/${rid}`)).json() as Bib
  const v1 = view.answers.find(a => a.report_version === 1)!
  expect(href).toContain(`answer_id=${v1.id}`)
  const response = await fetch(new URL(href!, url))
  expect(response.status).toBe(200)
  const text = await response.text()
  const cited = new Set(v1.claims.flatMap(c => c.evidence.map(e => e.source_version_id)))
  const listed = view.sources.filter(s => cited.has(s.source_version_id))
  expect(listed.length).toBeGreaterThan(0)
  expect(text.match(/^@\w+\{/gm) ?? text.match(/^TY {2}- /gm)).toHaveLength(listed.length)
  for (const source of listed) expect(text).toContain(source.title.slice(0, 30))
}

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
      // As the backend stores it: the unverified draft keeps no claims, and the sources' "cited in latest answer" flags
      // follow that newest, citation-less draft.
      view.answers[0].claims = []
      for (const source of view.sources) source.cited_in_latest_answer = false
      view.counts.cited = 0
      view.answers[1].late_revision_status.status = 'failed'
      view.answers[1].late_revision_status.skip_reason = 'revision_unverified'
      await route.fulfill({ response, json: view })
    })
    await page.goto(`${url}/#/research/${rid}`)
    await expect(page.locator('#research-answer')).toContainText('Report · V1')
    await expect(page.locator('.answer-thread')).not.toContainText('A late full text produced answer')
    // V1's "View N cited sources" lists the works V1 cites, from its own claims, not the draft's empty flags.
    const view = await (await fetch(`${url}/api/researches/${rid}`)).json() as { answers: { report_version: number; claims: { evidence: { source_version_id: string }[] }[] }[]; sources: { source_version_id: string; work_id: string }[] }
    const v1 = view.answers.find(a => a.report_version === 1)!
    const workOf = new Map(view.sources.map(s => [s.source_version_id, s.work_id]))
    const citedWorks = new Set(v1.claims.flatMap(c => c.evidence.map(e => workOf.get(e.source_version_id))))
    expect(citedWorks.size).toBeGreaterThan(0)
    // The facts strip's Cited number, and from 1100px the rail's Cited bar, count the same works.
    await expect(page.locator('.research-facts button', { hasText: 'Cited' }).locator('strong')).toHaveText(String(citedWorks.size))
    if (width >= 1100) await expect(page.locator('.rail .fun button', { hasText: 'Cited' }).locator('.rail-data')).toHaveText(String(citedWorks.size))
    await page.locator('.answer-thread .answer-acts').getByRole('button', { name: /^View \d+ cited sources?$/ }).click()
    const sources = page.locator('[data-split-panel]')
    await expect(sources.getByRole('button', { name: /^Cited in answer/ })).toHaveAttribute('aria-pressed', 'true')
    await expect(sources.getByRole('button', { name: /^Cited in answer/ })).toContainText(String(citedWorks.size))
    await expect(sources.locator('.source-row')).toHaveCount(view.sources.filter(s => citedWorks.has(s.work_id)).length)
    await page.keyboard.press('Escape')
    await expect(page.locator('[data-split-panel]')).toHaveCount(0)
    // The cited-sources exports follow V1 too: the thread's Download menu row, the topbar Export row (from 1100px, where
    // the topbar shows it) and the report's .bib and .ris links.
    await page.locator('.answer-thread .answer-acts').getByRole('button', { name: 'Download' }).click()
    await expectV1Export(await page.getByRole('menuitem', { name: /^BIB/ }).getAttribute('href'))
    await page.keyboard.press('Escape')
    if (width >= 1100) {
      await page.getByRole('button', { name: 'Export', exact: true }).click()
      await expectV1Export(await page.getByRole('menuitem', { name: /^BIB/ }).getAttribute('href'))
      await page.keyboard.press('Escape')
    }
    await page.locator('#research-answer').click()
    await expect(page.locator('.report-content')).toBeVisible()
    for (const format of ['.bib', '.ris']) await expectV1Export(await page.locator('.report-content .export-links a', { hasText: format }).getAttribute('href'))
    await expect(page.locator('.report-content')).not.toContainText('Full text added for')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
    await page.screenshot({ path: path.join(OUT, `late-pdf-unverified-${width}.png`), fullPage: true })
  })

  test(`[late-pdf] revision label and previous artifact at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto(`${url}/#/research/${rid}`)
    // The thread names the late revision in its notice (UI parity S10, R29); the card reads as any report card.
    const thread = page.locator('.answer-thread')
    await expect(page.locator('#research-answer')).toContainText(/Report · V2 · \d+ claims? · \d+ sources?$/)
    await expect(thread.locator('.answer-notice')).toContainText('A late full text produced answer V2. Full text for 1 source arrived after V1 was written; V2 reads it (selected pages). This happens once per answer. V1 is kept.')
    await thread.getByRole('button', { name: 'Open V1' }).click()
    await expect(page.locator('.report-document-head')).toContainText('Report · V1')
    // The old report's cited-sources links export V1's sources, not V2's.
    for (const format of ['.bib', '.ris']) await expectV1Export(await page.locator('.report-content .export-links a', { hasText: format }).getAttribute('href'))
    await page.keyboard.press('Escape')
    await expect(page.locator('.report-document-head')).toHaveCount(0)
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
