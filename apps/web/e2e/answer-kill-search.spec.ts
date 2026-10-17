import { expect, request as apiRequest, test, type Locator, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import type { AnswerCandidates, ResearchView } from '../src/api'
import { label, statusLabels } from '../src/candidate/labels'
import { setUiLanguage } from '../src/i18n'
import { nextPort } from './ports'
import { chooseTheme, closePanel, panel } from './panels'
import { chooseLanguage } from './language'

// Kill search from the answer's Next steps (D98), against the fixture server's "[candidate]" scripted model with
// "[candidate-thread]" aspects. Synthetic application behaviour only: no real model or provider request, and nothing
// here says whether a kill search finds prior work.
const PORT = nextPort()
const REPO = path.resolve(process.cwd(), '..', '..')
const SERVER_URL = `http://127.0.0.1:${PORT}`
const PYTHON = process.env.DEIXIS_TEST_PYTHON ?? path.join(REPO, '.venv/bin/python')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
const SHOTS = process.env.DEIXIS_KS_SHOTS ? path.resolve(process.env.DEIXIS_KS_SHOTS) : path.join(OUT, 'answer-kill-search')
const ASPECTS = ['SYNTHETIC release spacing under bounded arrivals in the same simulation setting.', 'SYNTHETIC energy figures for buffered release under mobile relays.']
const CLAIM = 'SYNTHETIC buffering reduces delay under bounded arrivals.'
mkdirSync(SHOTS, { recursive: true })

let proc: ChildProcess | undefined
test.beforeAll(async () => {
  const dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-ks-'))
  proc = spawn(PYTHON, [path.join(REPO, 'tests/acceptance/fixture_server.py'), '--data-dir', dataDir, '--port', String(PORT)],
    { cwd: REPO, env: { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: `${REPO}/backend:${REPO}` }, stdio: 'inherit' })
  await expect.poll(async () => { try { return (await fetch(`${SERVER_URL}/api/health`)).ok } catch { return false } }, { timeout: 60_000 }).toBe(true)
})
test.afterAll(async () => {
  if (!proc || proc.exitCode !== null) return
  const ended = new Promise(resolve => proc!.once('exit', resolve))
  proc.kill('SIGTERM'); await ended
})

const next = (page: Page) => page.locator('.follow')
const summaries = (page: Page) => page.locator('.ksum-list .ksum')
const dialog = (page: Page) => page.getByRole('dialog', { name: /^(Search earlier work for a claim|Bir iddia için önceki çalışmaları ara)$/ })
// A modal dialog makes the sidebar inert, so the theme button is pressed directly while one is open.
// In Turkish the button carries its Turkish name.
async function theme(page: Page, value: 'light' | 'dark') {
  const turkish = await page.locator('html').getAttribute('lang') === 'tr'
  if (!turkish && await page.getByRole('dialog').count() === 0) { await chooseTheme(page, value); return }
  const dark = await page.locator('html').evaluate(el => el.classList.contains('dark'))
  const names = dark ? ['Switch to light mode', 'Açık moda geç'] : ['Switch to dark mode', 'Koyu moda geç']
  if (dark !== (value === 'dark')) await page.locator(names.map(n => `button[aria-label="${n}"]`).join(', ')).first().evaluate(el => (el as HTMLElement).click())
}
async function shotBoth(page: Page, name: string, target?: Locator) {
  if (target) await target.evaluate(el => el.scrollIntoView({ block: 'center' }))
  for (const value of ['light', 'dark'] as const) {
    await theme(page, value)
    await page.screenshot({ path: path.join(SHOTS, `${name}-${value}.png`), animations: 'disabled' })
  }
  await theme(page, 'light')
}

test('status labels have their own keys: the status "open" reads Açık while the verb keeps Aç', () => {
  try {
    setUiLanguage('tr')
    expect(label(statusLabels, 'open')).toBe('Açık')
    expect(label(statusLabels, 'not_run')).toBe('Aranmadı')
  } finally { setUiLanguage('en') }
  expect(label(statusLabels, 'open')).toBe('Open')
})

test('an answer aspect becomes a claim only through the person, and its search result sits under Next steps', async ({ page }) => {
  test.setTimeout(420_000)
  await page.setViewportSize({ width: 1440, height: 1000 })
  const api = await apiRequest.newContext({ baseURL: SERVER_URL, extraHTTPHeaders: { origin: SERVER_URL } })
  const csrf = (await (await api.get(`${SERVER_URL}/api/session`)).json()).csrf_token as string
  const headers = { 'x-deixis-csrf': csrf }
  await page.goto(SERVER_URL)
  await page.getByLabel('Research question').fill('SYNTHETIC molecule release scheduling [candidate] [candidate-thread]')
  await page.getByRole('button', { name: 'Start research' }).click()
  await page.waitForURL(/#\/research\//)
  const rid = page.url().split('/research/')[1].split('/')[0]
  const view = async (): Promise<ResearchView> => (await api.get(`${SERVER_URL}/api/researches/${rid}`)).json()
  await expect.poll(async () => (await view()).answers[0]?.status, { timeout: 90_000 }).toBe('structurally_valid')
  const answer = (await view()).answers[0]
  expect(answer.unanswered_aspects).toEqual(ASPECTS)
  const list = async (): Promise<AnswerCandidates> => (await api.get(`${SERVER_URL}/api/researches/${rid}/answers/${answer.id}/candidates`)).json()

  // The box: the first rows unchanged, the aspects in one disclosure row, the new entry last (always enabled).
  await expect(next(page).locator('h5')).toHaveText('Next steps')
  const group = next(page).locator('details.follow-group')
  await expect(group.locator('summary')).toHaveText(`Topics the answer did not answer (${ASPECTS.length})`)
  await expect(next(page).locator(':scope > button').first()).toHaveText('Review the claims with another model')
  await expect(next(page).locator(':scope > button').last()).toHaveText('Search earlier work for a claim')
  await expect(next(page).locator(':scope > button').last()).toBeEnabled()
  await expect(group.getByRole('button', { name: 'Prepare a follow-up question' })).toBeHidden()
  await shotBoth(page, '01-next-steps-collapsed', next(page))
  await group.locator('summary').click()
  const aspects = group.locator('.follow-aspects li')
  await expect(aspects).toHaveCount(2)
  await expect(aspects.nth(0).locator('q')).toHaveText(ASPECTS[0])
  await shotBoth(page, '02-next-steps-expanded', next(page))

  // "Prepare a follow-up question" fills the composer; nothing is sent.
  await aspects.nth(1).getByRole('button', { name: 'Prepare a follow-up question' }).click()
  await expect(page.getByRole('textbox', { name: 'Follow-up question' })).toHaveValue(ASPECTS[1])
  await page.getByRole('textbox', { name: 'Follow-up question' }).fill('')

  // The claim dialog shows the aspect read-only above an empty box; saving needs a sentence.
  await aspects.nth(0).getByRole('button', { name: 'Write a claim about this topic' }).click()
  await expect(dialog(page)).toBeVisible()
  await expect(dialog(page).locator('.claim-dialog-context')).toContainText(ASPECTS[0])
  const box = dialog(page).getByLabel('Claim')
  await expect(box).toHaveValue('')
  await expect(dialog(page).getByRole('button', { name: 'Save and break into parts' })).toBeDisabled()
  await expect(dialog(page)).toContainText('Enter a sentence to save.')
  await expect(dialog(page)).toContainText(/Breaking into parts: .* at most \d+ model calls \(retries included\) · no search/)
  await box.fill(CLAIM)
  await shotBoth(page, '03-claim-dialog')
  await dialog(page).getByRole('button', { name: 'Save and break into parts' }).click()
  await expect(dialog(page)).toHaveCount(0)
  // The Candidates panel opens at the new candidate; the breakdown runs, the search does not.
  await expect(panel(page, 'Candidates · Your sentence from an answer')).toBeVisible()
  await expect(page.locator('.candidate-detail .sentence')).toHaveText(CLAIM)
  await expect(page.locator('.candidate-detail')).toContainText(ASPECTS[0])
  await expect.poll(async () => (await list()).candidates[0]?.current_version, { timeout: 30_000 }).toBe(1)
  let rows = (await list()).candidates
  expect(rows).toHaveLength(1)
  expect(rows[0]).toMatchObject({ aspect_index: 0, origin_text: CLAIM, search: null })
  expect((await view()).runs.filter(r => r.kind === 'kill_search')).toHaveLength(0)
  await closePanel(page)
  await expect(summaries(page)).toHaveCount(1)
  await expect(summaries(page).first()).toContainText('Card V1 is ready; nothing has been searched.')

  // The second write from the same aspect, through the API, reopens the same candidate.
  const again = await api.post(`${SERVER_URL}/api/researches/${rid}/answers/${answer.id}/candidates`, { headers: { ...headers, 'Idempotency-Key': crypto.randomUUID() }, data: { aspect_index: 0, text: 'SYNTHETIC other words' } })
  expect(again.status()).toBe(201)
  expect((await again.json()).reused).toBe(true)

  // The search starts only from the panel. Pause it while it runs, then resume from the summary.
  await summaries(page).first().getByRole('button', { name: 'Open in the Candidates panel' }).click()
  const detail = page.locator('.candidate-detail')
  await detail.getByRole('button', { name: 'Plan the search' }).click()
  await detail.locator('.candidate-plan').getByRole('button', { name: 'Search for prior art on this claim' }).click()
  await expect.poll(async () => (await list()).candidates[0].run?.kind).toBe('kill_search')
  const runId = (await list()).candidates[0].run!.id
  await closePanel(page)
  await expect(summaries(page).first().locator('.ksum-verdict')).toContainText(/Preparing the search terms…|Searching · /)
  await shotBoth(page, '04-summary-running', summaries(page).first())
  expect((await api.post(`${SERVER_URL}/api/runs/${runId}/pause`, { headers })).ok()).toBe(true)
  await expect.poll(async () => (await view()).runs.find(r => r.id === runId)?.status, { timeout: 30_000 }).toBe('paused')
  await expect(summaries(page).first().getByRole('button', { name: 'Resume' })).toBeVisible()
  await expect(summaries(page).first()).toContainText('It can resume where it stopped.')
  await shotBoth(page, '05-summary-paused', summaries(page).first())
  await summaries(page).first().getByRole('button', { name: 'Resume' }).click()
  await expect.poll(async () => (await view()).runs.find(r => r.id === runId)?.status, { timeout: 60_000 }).toBe('completed')
  await expect.poll(async () => (await list()).candidates[0].search?.outcome).toBe('completed')

  // The completed summary: model-attributed sentence, execution and reading lines, top works, the caveat.
  const done = (await list()).candidates[0].search!
  const summary = summaries(page).first()
  await expect(summary.locator('.ksum-verdict')).toContainText(done.status.status === 'narrowed'
    ? `The model found partial overlap or inference-based support in ${done.execution.works_with_support} of the ${done.execution.assessed} works assessed.` : /./)
  await expect(summary).toContainText(`Execution: ${done.execution.queries_succeeded} of ${done.execution.queries_planned} queries completed`)
  await expect(summary).toContainText('Given to the model:')
  await expect(summary).toContainText('no full text')
  await expect(summary).toContainText('This search can miss related works; finding no match is not evidence of originality.')
  await expect(summary.locator('.ksum-works li')).toHaveCount(done.top_works.length)
  expect(await summary.evaluate(el => {
    const copy = el.cloneNode(true) as HTMLElement
    copy.querySelectorAll('[data-stored-text]').forEach(e => e.remove())
    return copy.textContent ?? ''
  })).not.toMatch(/\b(novel|novelty|gap|unique)\b/i)
  await shotBoth(page, '06-summary-completed', summary)

  // After a reload the aspect shows its candidate's status instead of the write link; it opens that candidate.
  await page.reload()
  await page.locator('details.follow-group summary').click()
  const pill = page.locator('.follow-aspects li').nth(0).locator('.follow-pill')
  await expect(pill).toHaveText(`Claim written · Card V1 · ${label(statusLabels, done.status.status)}`)
  await expect(page.locator('.follow-aspects li').nth(0).getByRole('button', { name: 'Write a claim about this topic' })).toHaveCount(0)
  await pill.click()
  await expect(page.locator('.candidate-detail .sentence')).toHaveText(CLAIM)
  await closePanel(page)

  // The card changes after its search: the summary keeps the V1 result and says V2 has none.
  const card = await (await api.get(`${SERVER_URL}/api/researches/${rid}/candidates/${rows[0].candidate_id}`)).json()
  const v1 = card.versions[0]
  const edited = await api.post(`${SERVER_URL}/api/researches/${rid}/candidates/${card.id}/versions`, { headers, data: {
    claim_statement: v1.claim_statement, conditions: v1.conditions, elements: v1.elements.map((e: { text: string; kind: string }) => ({ text: e.text, kind: e.kind })),
    nearest_simple_explanation: v1.nearest_simple_explanation, critical_assumption: v1.critical_assumption, validation_plan: `${v1.validation_plan} SYNTHETIC edit`, expected_version: 1 } })
  expect(edited.status(), await edited.text()).toBe(201)
  await expect(summaries(page).first()).toContainText('Card V2 has no search yet · V1 result:')
  await shotBoth(page, '07-summary-card-changed', summaries(page).first())

  // The summary's links open the search it describes: V1's matrix and V1's evidence while V2 has no search.
  const matrixHeading = page.locator('.candidate-detail h4[id^="candidate-matrix-"]')
  await summaries(page).first().getByRole('button', { name: 'Open the claim matrix' }).click()
  await expect(matrixHeading).toHaveText('Claim matrix · Version 1')
  await closePanel(page)
  expect(done.top_works.length).toBeGreaterThan(0)
  await summaries(page).first().locator('.ksum-works .ksum-title').first().click()
  await expect(page.locator('.candidate-evidence .venue')).toContainText('Version 1')
  // Escape ends the whole stack: the evidence and the Candidates panel under it.
  await page.keyboard.press('Escape')
  await expect(page.locator('[data-split-panel]')).toHaveCount(0)
  // The matrix behind an evidence link fails once: the link stays pending, and after Retry the evidence opens.
  const matrixRoute = `**/api/researches/${rid}/candidates/${rows[0].candidate_id}/kill-searches/*`
  let failMatrix = true
  await page.route(matrixRoute, async route => {
    if (!failMatrix || route.request().method() !== 'GET') return route.fallback()
    failMatrix = false
    await route.fulfill({ status: 500, json: { detail: 'SYNTHETIC matrix failure' } })
  })
  await summaries(page).first().locator('.ksum-works .ksum-title').first().click()
  await page.locator('.candidate-detail').getByRole('button', { name: 'Retry' }).click()
  await expect(page.locator('.candidate-evidence .venue')).toContainText('Version 1')
  await page.unroute(matrixRoute)
  await page.keyboard.press('Escape')
  await expect(page.locator('[data-split-panel]')).toHaveCount(0)
  // Once V2 is searched, the same link opens V2's matrix.
  await summaries(page).first().getByRole('button', { name: 'Open the claim matrix' }).click()
  await detail.getByRole('button', { name: 'Plan the search' }).click()
  await detail.locator('.candidate-plan').getByRole('button', { name: 'Search for prior art on this claim' }).click()
  await expect.poll(async () => { const r = (await list()).candidates[0]; return r.current_version_searched && r.search?.version === 2 && r.search.outcome }, { timeout: 60_000 }).toBe('completed')
  await closePanel(page)
  await expect(summaries(page).first()).not.toContainText('Card V2 has no search yet')
  await summaries(page).first().getByRole('button', { name: 'Open the claim matrix' }).click()
  await expect(matrixHeading).toHaveText('Claim matrix · Version 2')
  await closePanel(page)

  // The generic entry by keyboard: no aspect context, Escape closes it and focus returns to the opener.
  const generic = next(page).locator(':scope > button').last()
  await generic.focus()
  await page.keyboard.press('Enter')
  await expect(dialog(page)).toBeVisible()
  await expect(dialog(page).locator('.claim-dialog-context')).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect(dialog(page)).toHaveCount(0)
  await expect(generic).toBeFocused()
  // The first save is committed but its response is lost; the retry sends the same key and gets the same candidate.
  const keys: string[] = []
  let lose = true
  const postRoute = `**/api/researches/${rid}/answers/${answer.id}/candidates`
  await page.route(postRoute, async route => {
    if (route.request().method() !== 'POST') return route.fallback()
    keys.push(route.request().headers()['idempotency-key'])
    if (!lose) return route.fallback()
    lose = false
    await route.fetch()
    await route.abort('connectionreset')
  })
  const tabToButton = async (name: string) => {
    for (let i = 0; i < 10 && await page.evaluate(() => document.activeElement?.textContent ?? '') !== name; i++) await page.keyboard.press('Tab')
    expect(await page.evaluate(() => document.activeElement?.textContent)).toBe(name)
  }
  await page.keyboard.press('Enter')
  await expect(dialog(page)).toBeVisible()
  await page.keyboard.type('SYNTHETIC second claim written by hand.')
  await tabToButton('I will write the card myself')
  await page.keyboard.press('Enter')
  await expect(dialog(page).getByRole('alert')).toBeVisible()
  await tabToButton('I will write the card myself')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog', { name: 'Write the candidate card' })).toBeVisible()
  expect(keys).toHaveLength(2)
  expect(keys[1]).toBe(keys[0])
  await page.unroute(postRoute)
  await page.keyboard.press('Escape')
  rows = (await list()).candidates
  expect(rows.map(r => r.aspect_index)).toEqual([0, null])
  expect((await (await api.get(`${SERVER_URL}/api/researches/${rid}/candidates`)).json()).filter((c: { origin: string }) => c.origin === 'answer_thread')).toHaveLength(2)
  await closePanel(page)
  await expect(summaries(page)).toHaveCount(2)

  // Turkish: the status pill and the summary in Turkish, light and dark.
  await chooseLanguage(page, 'tr')
  await expect(page.locator('.follow h5')).toHaveText('Sonraki adımlar')
  await expect(summaries(page).first()).toContainText('Önceki çalışma araması')
  await expect(summaries(page).first()).toContainText('Bu arama ilgili çalışmaları kaçırabilir; eşleşme bulunmaması özgünlük kanıtı değildir.')
  await page.locator('details.follow-group summary').click()
  await shotBoth(page, '08-tr-next-steps', next(page))
  await shotBoth(page, '09-tr-summary', summaries(page).first())
  await chooseLanguage(page, 'en')

  // With no model chosen, "Save and break into parts" stays disabled and says why; writing the card stays possible.
  const listRoute = /\/api\/researches\/[^/]+\/answers\/[^/]+\/candidates$/
  await page.route(listRoute, async route => {
    if (route.request().method() !== 'GET') return route.fallback()
    const response = await route.fetch()
    const body = await response.json() as AnswerCandidates
    await route.fulfill({ response, json: { ...body, decompose: { ...body.decompose, model: null } } })
  })
  await page.reload()
  await next(page).locator(':scope > button').last().click()
  await dialog(page).getByLabel('Claim').fill('SYNTHETIC third claim.')
  await expect(dialog(page).getByRole('button', { name: 'Save and break into parts' })).toBeDisabled()
  await expect(dialog(page).getByRole('button', { name: 'Save and break into parts' })).toHaveAccessibleDescription(/No model is chosen for this research, so the claim cannot be broken into parts here\./)
  await expect(dialog(page).getByRole('button', { name: 'I will write the card myself' })).toBeEnabled()
  await page.keyboard.press('Escape')
  await page.unroute(listRoute)

  // A new answer replaces the one on screen. While its list loads, and after that load fails, nothing of the old
  // answer's candidates shows on the new one.
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route(listRoute, async route => {
    if (route.request().method() !== 'GET' || route.request().url().includes(answer.id)) return route.fallback()
    await gate
    await route.fulfill({ status: 500, json: { detail: 'SYNTHETIC list failure' } })
  })
  // A save on the old answer is still in flight when the new answer takes its place.
  let releaseSave!: () => void
  const saveGate = new Promise<void>(resolve => { releaseSave = resolve })
  await page.route(postRoute, async route => {
    if (route.request().method() !== 'POST') return route.fallback()
    await saveGate
    await route.fallback()
  })
  await next(page).locator(':scope > button').last().click()
  await dialog(page).getByLabel('Claim').fill('SYNTHETIC claim saved while the answer is replaced.')
  await dialog(page).getByRole('button', { name: 'I will write the card myself' }).click()
  await expect(dialog(page).getByRole('button', { name: 'I will write the card myself' })).toBeDisabled()
  const started = await api.post(`${SERVER_URL}/api/researches/${rid}/runs`, { headers: { ...headers, 'Idempotency-Key': crypto.randomUUID() }, data: { kind: 'answer' } })
  expect(started.ok(), await started.text()).toBe(true)
  await expect.poll(async () => (await view()).answers.find(a => a.id !== answer.id)?.status, { timeout: 90_000 }).toBe('structurally_valid')
  const fresh = page.locator('.follow').last()
  await expect(fresh.locator('details.follow-group summary')).toBeVisible({ timeout: 30_000 })
  await expect(dialog(page)).toHaveCount(0)
  await fresh.locator('details.follow-group summary').click()
  const freshAspects = fresh.locator('.follow-aspects li')
  await expect(freshAspects.nth(0).getByRole('button', { name: 'Write a claim about this topic' })).toBeVisible()
  // The new answer's dialog opens; the old save then completes and must neither close it nor open its candidate.
  await freshAspects.nth(0).getByRole('button', { name: 'Write a claim about this topic' }).click()
  await expect(dialog(page).locator('.claim-dialog-context')).toContainText(ASPECTS[0])
  const saved = page.waitForResponse(r => r.request().method() === 'POST' && r.url().includes(`/answers/${answer.id}/candidates`))
  releaseSave()
  expect((await saved).status()).toBe(201)
  await page.waitForTimeout(500)
  await expect(dialog(page).locator('.claim-dialog-context')).toContainText(ASPECTS[0])
  await expect(page.locator('[data-split-panel]')).toHaveCount(0)
  await page.keyboard.press('Escape')
  await page.unroute(postRoute)
  expect((await list()).candidates.map(r => r.aspect_index)).toEqual([0, null, null])
  await expect(fresh.locator('.follow-pill')).toHaveCount(0)
  await expect(summaries(page)).toHaveCount(0)
  release()
  await expect(page.locator('.ksum-error')).toContainText('The earlier-work searches of this answer could not be read')
  await expect(fresh.locator('.follow-pill')).toHaveCount(0)
  await expect(summaries(page)).toHaveCount(0)
  await page.unroute(listRoute)
  await api.dispose()
})
