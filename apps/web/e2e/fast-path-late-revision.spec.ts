import { expect, test } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'
import { reportPanel } from './panels'

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
    // Each row is read inside its own menu: a closing menu can still be in the DOM when the next one opens.
    await page.locator('.answer-thread .answer-acts').getByRole('button', { name: 'Download' }).click()
    await expectV1Export(await page.getByRole('menu', { name: 'Download' }).getByRole('menuitem', { name: /^BIB/ }).getAttribute('href'))
    await page.keyboard.press('Escape')
    await expect(page.getByRole('menu', { name: 'Download' })).toHaveCount(0)
    if (width >= 1100) {
      await page.getByRole('button', { name: 'Export', exact: true }).click()
      await expectV1Export(await page.getByRole('menu', { name: 'Export' }).getByRole('menuitem', { name: /^BIB/ }).getAttribute('href'))
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
    // "Compare with V1" opens V2's report with its changes (S21); V1's own report is one version choice away.
    await thread.getByRole('button', { name: 'Compare with V1' }).click()
    await expect(page.locator('.report-document-head')).toContainText('Report · V2')
    await reportPanel(page).getByRole('combobox', { name: 'Version' }).click()
    await page.getByRole('option', { name: 'V1', exact: true }).click()
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

// UI parity S21 (P4): the answer diff of V2 against V1, the version its late revision revises. The fixture's scripted
// answers (fixture_server.late_pdf_answer) differ in each way the diff names; every expected mark is built from the two
// stored answers the view returns, so the test checks what the records say, not what the page draws.
type DiffView = { answers: { id: string; report_version: number; claims: { text: string; evidence: { passage_id: string; kind: string; source_key: string | null; title: string }[] }[]; limitations: { kind: string; text: string }[] }[] }
for (const width of [1440, 390]) {
  test(`[late-pdf] Compare with V1: the changes box and the ins/del marks at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const view = await (await fetch(`${url}/api/researches/${rid}`)).json() as DiffView
    const v1 = view.answers.find(a => a.report_version === 1)!
    const v2 = view.answers.find(a => a.report_version === 2)!
    const texts = (a: DiffView['answers'][number]) => a.claims.map(c => c.text)
    const added = texts(v2).filter(t => !texts(v1).includes(t))
    const removed = texts(v1).filter(t => !texts(v2).includes(t))
    const upgraded = v2.claims.find(c => texts(v1).includes(c.text) && c.evidence.some(e => e.kind === 'pdf_page'))!
    const before = v1.claims.find(c => c.text === upgraded.text)!
    const kept = v2.claims.find(c => c !== upgraded && texts(v1).includes(c.text))!
    // The fixture's own shape, so the marks below are not vacuous.
    expect([added.length, removed.length, before.evidence.every(e => e.kind === 'abstract')]).toEqual([1, 1, true])
    const key = upgraded.evidence[0].source_key!
    await page.goto(`${url}/#/research/${rid}`)
    await page.locator('.answer-thread').getByRole('button', { name: 'Compare with V1' }).click()
    const report = reportPanel(page)
    await expect(report.locator('.report-document-head')).toContainText('Report · V2')
    const toggle = report.locator('.split-panel-head .report-compare')
    await expect(toggle).toHaveAccessibleName('Hide changes')
    const box = report.locator('.changes')
    await expect(box.locator('> b')).toHaveText('Changes since V1')
    await expect(box.locator('> ul > li')).toHaveText([
      `Cited from full text in V2, only from abstracts in V1: ${key}`,
      'Badge on 1 claim changed from “From abstract” to “Full text”',
      '1 claim keeps its wording but cites different passages',
      '1 claim added',
      `1 claim of V1 is not in this version:Removed: ${removed[0]}`,
      'Limits updated',
    ])
    await expect(box.locator('.changes-foot')).toHaveText('Compared: claim wording, the passages each claim cites, their reading depth and the limits. Claim reviews are not compared.')
    const content = report.locator('.report-content')
    const claim = (text: string) => content.locator('.claim').filter({ hasText: text })
    // The added claim's text, and nothing else of its claim, is inside one `ins`; the kept claim carries no mark.
    await expect(content.locator('.claim > ins:not(.cite-ins, .badge-s)')).toHaveText([`Added: ${added[0]}`])
    await expect(claim(kept.text).locator('ins, del')).toHaveCount(0)
    // Same wording, other passages: the new citation inside `ins`, the dropped one named inside `del`; the depth badges.
    const upgradedClaim = claim(upgraded.text)
    await expect(upgradedClaim.locator('ins.cite-ins')).toHaveText([`Added citation: ${key}`])
    await expect(upgradedClaim.locator('del.cite-del')).toHaveText([`Removed citation: ${before.evidence[0].source_key}, abstract`])
    await expect(upgradedClaim.locator('del.badge-s')).toHaveText(['Removed: From abstract'])
    await expect(upgradedClaim.locator('ins.badge-s')).toHaveText(['Added: Full text'])
    await expect(content.locator('ins, del')).toHaveCount(7)
    // The limits: V2's new one inside `ins`, V1's dropped one inside `del`.
    await expect(content.locator('.plain-list ins')).toHaveText([`Added: ${v2.limitations[0].kind}: ${v2.limitations[0].text}`])
    await expect(content.locator('.plain-list del')).toHaveText([`Removed: ${v1.limitations[0].kind}: ${v1.limitations[0].text}`])
    // Not by colour alone: an addition is underlined, a removal struck through; the tints are the mockup's --ins/--del.
    const look = (sel: string) => content.locator(sel).first().evaluate(el => { const cs = getComputedStyle(el); return [cs.textDecorationLine, cs.backgroundColor] })
    const dark = await page.evaluate(() => document.documentElement.classList.contains('dark'))
    expect(await look('.claim > ins:not(.cite-ins, .badge-s)')).toEqual(['underline', dark ? 'rgb(29, 51, 38)' : 'rgb(223, 243, 230)'])
    expect(await look('.plain-list del')).toEqual(['line-through', dark ? 'rgb(59, 33, 30)' : 'rgb(251, 227, 224)'])
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
    await page.screenshot({ path: path.join(OUT, `late-pdf-changes-${width}.png`), fullPage: true })
    // The box follows the version shown: V1 has no earlier version, so it says so and nothing is marked.
    await report.getByRole('combobox', { name: 'Version' }).click()
    await page.getByRole('option', { name: 'V1', exact: true }).click()
    await expect(report.locator('.report-document-head')).toContainText('Report · V1')
    await expect(box).toHaveText('ChangesV1 is the first version of this report; there is no earlier version to compare it with.')
    await expect(content.locator('ins, del')).toHaveCount(0)
    await report.getByRole('combobox', { name: 'Version' }).click()
    await page.getByRole('option', { name: 'V2', exact: true }).click()
    await expect(box.locator('> b')).toHaveText('Changes since V1')
    await expect(content.locator('ins, del')).toHaveCount(7)
    // Hide changes: no box, no marks; the report is V2's as stored.
    await toggle.click()
    await expect(toggle).toHaveAccessibleName('Show changes')
    await expect(box).toHaveCount(0)
    await expect(content.locator('ins, del')).toHaveCount(0)
    await expect(content.locator('.claim')).toHaveCount(v2.claims.length)
    // Closing the panel turns the changes off: the card opens the plain report.
    await toggle.click()
    await expect(box).toHaveCount(1)
    await page.keyboard.press('Escape')
    await expect(report).toHaveCount(0)
    await page.locator('#research-answer').click()
    await expect(reportPanel(page).locator('.report-document-head')).toContainText('Report · V2')
    await expect(reportPanel(page).locator('.changes')).toHaveCount(0)
  })
}
