import AxeBuilder from '@axe-core/playwright'
import { expect, test, type APIRequestContext, type Page, type Route } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'
import { chooseTheme, sourcePanel } from './panels'

// Reverse citation search R3: Home's "Check a statement" mode, the statement check panel in the research thread, the
// fixed note that "not found" is not "contradicts", a stale revision and a recheck, and the exports. The fixture server
// searches its SYNTHETIC records and its scripted model answers each `statement_check` step by the work it reads
// (`statement_answer`): W901 states the whole sentence, W902 its second part, W903 nothing, W904 its first part only
// partly (R4b, D108: support not shown clearly enough, never counted as support), any other work gives an answer that
// is not a check. Passing shows what the screen does with stored rows, not how well a model checks support.
const PORT = nextPort()
const REPO = path.resolve(process.cwd(), '..', '..')
const SERVER_URL = `http://127.0.0.1:${PORT}`
const PYTHON = process.env.DEIXIS_TEST_PYTHON ?? path.join(REPO, '.venv/bin/python')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
const SHOTS = process.env.DEIXIS_R3_SHOTS ? path.resolve(process.env.DEIXIS_R3_SHOTS) : path.join(OUT, 'statement-check')
mkdirSync(SHOTS, { recursive: true })
const SENTENCE = readFileSync(path.join(REPO, 'tests/acceptance/fixture_server.py'), 'utf8').split('STATEMENT_SENTENCE = "')[1].split('"')[0]

let proc: ChildProcess | undefined
test.beforeAll(async () => {
  const dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-r3-'))
  proc = spawn(PYTHON, [path.join(REPO, 'tests/acceptance/fixture_server.py'), '--data-dir', dataDir, '--port', String(PORT)],
    { cwd: REPO, env: { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: `${REPO}/backend:${REPO}` }, stdio: 'inherit' })
  await expect.poll(async () => { try { return (await fetch(`${SERVER_URL}/api/health`)).ok } catch { return false } }, { timeout: 60_000 }).toBe(true)
})
test.afterAll(async () => {
  if (!proc || proc.exitCode !== null) return
  const ended = new Promise(resolve => proc!.once('exit', resolve))
  proc.kill('SIGTERM'); await ended
})

async function headers(api: APIRequestContext) {
  const csrf = (await (await api.get(`${SERVER_URL}/api/session`)).json()).csrf_token as string
  return { origin: SERVER_URL, 'x-deixis-csrf': csrf }
}
// The panel whole: a viewport tall enough for it (the thread scrolls on its own), with the sticky follow-up composer
// and any toast hidden from the picture only.
const HIDE = '.followup-composer, .toast { visibility: hidden !important; }'
async function shot(page: Page, name: string) {
  const size = page.viewportSize()!
  const height = await page.locator('.sc-panel').evaluate(el => el.getBoundingClientRect().height)
  await page.setViewportSize({ width: size.width, height: Math.ceil(height) + 900 })
  for (const value of ['light', 'dark'] as const) {
    await chooseTheme(page, value)
    await page.locator('.sc-panel').screenshot({ path: path.join(SHOTS, `${name}-${value}.png`), animations: 'disabled', style: HIDE })
  }
  await chooseTheme(page, 'light')
  await page.setViewportSize(size)
}
// Holds the first read of one revision's view: fetched from the server at once (so it carries the state of that
// moment), answered only after `release()`. Later reads pass.
async function holdFirst(page: Page, checkId: string) {
  let release!: () => void, fetched!: () => void, done!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  const hold = { release: () => release(), fetched: new Promise<void>(resolve => { fetched = resolve }),
    done: new Promise<void>(resolve => { done = resolve }), stop: () => page.unroute(match, handler) }
  const match = (url: URL) => url.pathname === `/api/statement-checks/${checkId}`
  let held = false
  const handler = async (route: Route) => {
    if (held) return route.continue()
    held = true
    const response = await route.fetch()
    fetched()
    await gate
    await route.fulfill({ response }).catch(() => {})
    done()
  }
  await page.route(match, handler)
  return hold
}
const chip = (page: Page) => page.locator('.mode-chips').getByRole('button', { name: 'Check a statement', exact: true })
const group = (page: Page, key: string) => page.locator(`.sc-group[data-group="${key}"]`)

test.describe.serial('R3: statement check', () => {
  test('Home mode, the panel with each result apart, the note, the quote mark, a stale revision, a recheck and the exports', async ({ page, request }) => {
    test.setTimeout(300_000)
    const h = await headers(request)
    // The discovery-end check runs on the literature model in Settings (D103).
    expect((await request.put(`${SERVER_URL}/api/settings/literature`, { headers: h, data: { model_connection: 'codex', model: 'fixture-model', reasoning_effort: null } })).ok()).toBe(true)

    // Home: the mode, its hint, the 600-character limit and the one-claim hint.
    await page.goto(SERVER_URL)
    await expect(page.locator('.models-summary')).toContainText('fixture-model')
    await chip(page).click()
    await expect(chip(page)).toHaveAttribute('aria-pressed', 'true')
    const box = page.getByLabel('Statement to check')
    await expect(box).toBeFocused()
    await expect(box).toHaveAttribute('placeholder', 'Paste one sentence to check, for example a claim from your draft.')
    await expect(page.locator('.statement-hint')).toContainText('One sentence, up to 600 characters.')
    await box.fill('x'.repeat(601))
    await expect(page.locator('.statement-hint')).toHaveText('A statement to check is at most 600 characters (601 now).')
    await expect(page.getByRole('button', { name: 'Start research' })).toBeDisabled()
    await box.fill('One claim here. Another claim there.')
    await expect(page.locator('.statement-hint')).toContainText('Enter one claim.')
    await box.fill(SENTENCE)
    const created = page.waitForRequest(r => r.method() === 'POST' && new URL(r.url()).pathname === '/api/researches')
    await page.getByRole('button', { name: 'Start research' }).click()
    expect((await created).postDataJSON()).toMatchObject({ intent: 'statement', source_scope: 'academic', question: SENTENCE })
    await expect(page).toHaveURL(/#\/research\//)
    const researchId = page.url().split('#/research/')[1].split(/[/?]/)[0]

    // The panel: the discovery-end check of revision 1, each result in its own group from the stored rows.
    const panel = page.locator('.sc-panel')
    await expect(panel.getByRole('heading', { name: 'Statement check', level: 2 })).toBeVisible()
    await expect(panel).toContainText('Check finished: 3 works completed, 0 could not be checked.', { timeout: 150_000 })
    await expect(panel.locator('.sc-sub')).toContainText('Revision 1')
    await expect(panel.locator('.sc-sub')).toContainText('Current')
    // The sentence the revision checked, as stored with it.
    await expect(panel.locator('.sc-sentence q')).toHaveText(SENTENCE)
    await expect(group(page, 'found_whole')).toContainText('SYNTHETIC molecule release scheduling with bisection')
    await expect(group(page, 'found_whole')).toContainText('Abstract only')
    await expect(group(page, 'found_whole')).toContainText('The model’s assessment; read the passage.')
    // A one-part reading names its part and the model's assessment too.
    await expect(group(page, 'found_whole').locator('.cc-part-h')).toHaveText(`Model: Stated ${SENTENCE}`)
    await expect(group(page, 'found_partial')).toContainText('SYNTHETIC relay budget allocation')
    await expect(group(page, 'found_partial').locator('.cc-part-a')).toHaveText(['Model: Not stated', 'Model: Stated'])
    await expect(group(page, 'found_partial').locator('.cc-quote')).toHaveText(['“Relays share a molecule budget”'])
    const notFound = group(page, 'not_found_in_given')
    await expect(notFound).toContainText('SYNTHETIC molecule schedule letter')
    // An absence is the model's reading of what it was given, never a fact about the work.
    await expect(notFound.locator('.sc-note')).toHaveText('The model did not find this statement in the passages it was given. This does not mean the work contradicts it.')
    await expect(notFound).toContainText('The model’s assessment of the passages it was given.')
    await expect(notFound.locator('.cc-part-a')).toHaveText(['Model: Not stated'])
    await expect(notFound.locator('.cc-quote')).toHaveCount(0)
    await expect(group(page, 'not_checked').locator('.sc-row')).toHaveCount(2)
    await expect(group(page, 'not_checked')).toContainText('Left out at screening')
    await expect(page.locator('.sc-group[data-group="could_not_check"]')).toHaveCount(0)
    await expect(page.locator('.sc-group[data-group="support_not_shown"]')).toHaveCount(0)
    // The counts are the view's own, in a box apart from the search counts.
    const works = panel.getByRole('region', { name: 'Works', exact: true })
    const check = panel.getByRole('region', { name: 'Check', exact: true })
    await expect(works).toContainText('5candidates')
    await expect(works).toContainText('3listed')
    await expect(works).toContainText('2left out with a reason')
    await expect(check).toContainText('3sent to the model')
    await expect(check).toContainText('1support the whole statement')
    await expect(check).toContainText('1support part of it')
    await expect(check).toContainText('0support not shown clearly enough')
    await expect(check).toContainText('1not found in given passages')
    await expect(check).toContainText('0could not be checked')
    await expect(panel.locator('.sc-facts')).toContainText('fixture-model')
    await expect(panel.locator('.sc-facts')).toContainText('Works in this check3 (cap')
    // No result reads as disagreement: "challenges" does not exist before R5.
    await expect(panel).not.toContainText(/challeng|contradicts the statement|disagrees/i)
    expect((await new AxeBuilder({ page }).include('.sc-panel').analyze()).violations).toEqual([])
    await shot(page, '01-current')

    // A located quote opens Source details on its passage alone, with the backend's located words as the only mark.
    await group(page, 'found_whole').locator('.cc-quote').click()
    const sheet = sourcePanel(page)
    await expect(sheet.locator('mark.citation-highlight')).toHaveText('bisection schedule for molecule release')
    await sheet.page().keyboard.press('Escape')

    // The exports: one row per work, status and result apart, with the revision's currency.
    const csvHref = await panel.getByRole('link', { name: 'CSV' }).getAttribute('href')
    const csv = await (await request.get(`${SERVER_URL}${csvHref}`)).text()
    expect(csv.split('\n')[0]).toContain('status,result,support_class,depth,passages_given,passages_not_given')
    expect(csv.split('\n')[0]).toMatch(/,currency,support_rule_version\r?$/)
    expect(csv).toContain('found_whole')
    expect(csv).toContain('not_found_in_given')
    expect(csv).toMatch(/,1,current/)

    // The person includes a work screening left out: revision 1 goes stale (kept, not current) and offers a recheck.
    // Review R3-1: a slow read that saw revision 1 still current answers after a newer read that saw it stale; the
    // older answer is dropped. The first read of revision 1 after a reload is fetched at once and held until released.
    const rev1 = (await (await request.get(`${SERVER_URL}/api/researches/${researchId}/statement-checks`)).json()).latest_check_id as string
    const slow = await holdFirst(page, rev1)
    await page.reload()
    await slow.fetched
    const view = await (await request.get(`${SERVER_URL}/api/researches/${researchId}`)).json()
    const hospital = view.sources.find((s: { title: string }) => s.title.includes('hospital'))
    expect((await request.patch(`${SERVER_URL}/api/researches/${researchId}/selections/${hospital.source_version_id}`,
      { headers: h, data: { state: 'included', expected_version: hospital.selection.version } })).ok()).toBe(true)
    await expect(panel.locator('.sc-sub')).toContainText('Out of date')
    slow.release()
    await slow.done
    await page.waitForTimeout(500)
    await expect(panel.locator('.sc-sub')).toContainText('Out of date')
    await slow.stop()
    await expect(panel.locator('.notice')).toContainText('This check is out of date: you included, excluded or judged a work or file after this check. Its results are kept, but they are not current.')
    await expect(group(page, 'found_whole')).toContainText('SYNTHETIC molecule release scheduling with bisection')
    await shot(page, '02-stale')
    // R4b: the hostile record joins too, so revision 2 has a work whose answer is not a check.
    const hostile = (await (await request.get(`${SERVER_URL}/api/researches/${researchId}`)).json()).sources.find((s: { title: string }) => s.title.includes('hostile'))
    expect((await request.patch(`${SERVER_URL}/api/researches/${researchId}/selections/${hostile.source_version_id}`,
      { headers: h, data: { state: 'included', expected_version: hostile.selection.version } })).ok()).toBe(true)
    const started = page.waitForRequest(r => r.method() === 'POST' && /\/runs$/.test(new URL(r.url()).pathname))
    await panel.locator('.notice').getByRole('button', { name: 'Check again' }).click()
    const body = (await started).postDataJSON()
    expect(body).toEqual({ kind: 'statement_check', expected_scope_revision: 1 })
    await expect(panel.locator('.sc-sub')).toContainText('Revision 2', { timeout: 30_000 })
    await expect(panel).toContainText('Check finished: 4 works completed, 1 could not be checked.', { timeout: 60_000 })
    const cnc = group(page, 'could_not_check')
    await expect(cnc).toContainText('SYNTHETIC hostile abstract record')
    await expect(cnc).toContainText('You included it')
    await expect(cnc).toContainText('The model’s answer did not pass the checks, also after one repair.')
    await expect(cnc.locator('.cc-pill')).toHaveCount(0)
    // R4b: W904's stored result is found_partial with only a partly part; the backend's class puts it in its own group,
    // with its note, its parts and located quote, and its stored result named as the model's, never counted as support.
    const notShown = group(page, 'support_not_shown')
    await expect(notShown.locator('h3')).toHaveText('Support not shown clearly enough 1')
    await expect(notShown.locator('.sc-note')).toHaveText('The model found only partial overlap in the passages it was given and marked no part of the statement as stated, so these works are not counted as support.')
    await expect(notShown).toContainText('SYNTHETIC optimization of hospital visiting hours')
    await expect(notShown).toContainText('You included it')
    await expect(notShown.locator('.cc-pill')).toHaveText('Support not shown clearly enough')
    await expect(notShown).toContainText('Stored result before the support rule: partial overlap')
    await expect(notShown).not.toContainText(/supports? (part|the whole)/i)
    await expect(notShown.locator('.cc-part-a')).toHaveText(['Model: Partly stated', 'Model: Not stated'])
    await expect(notShown.locator('.cc-quote')).toHaveText(['“Visiting hours were improved”'])
    await expect(group(page, 'found_partial').locator('.sc-row')).toHaveCount(1)
    await expect(group(page, 'found_partial')).toContainText('SYNTHETIC relay budget allocation')
    const recheck = panel.getByRole('region', { name: 'Check', exact: true })
    await expect(recheck).toContainText('1could not be checked')
    await expect(recheck).toContainText('1support the whole statement')
    await expect(recheck).toContainText('1support part of it')
    await expect(recheck).toContainText('1support not shown clearly enough')
    await expect(recheck).toContainText('1not found in given passages')
    const csv2 = await (await request.get(`${SERVER_URL}${await panel.getByRole('link', { name: 'CSV' }).getAttribute('href')}`)).text()
    expect(csv2).toMatch(/,found_partial,support_not_shown,abstract,/)
    expect(csv2).toMatch(/,2,current,2\r?\n/)
    expect((await new AxeBuilder({ page }).include('.sc-panel').analyze()).violations).toEqual([])
    await shot(page, '03-recheck')

    // Revision 1 is still there, stale, and opens with a pointer to the latest.
    const revisions = panel.locator('.sc-revisions')
    await revisions.locator('summary').click()
    await expect(revisions.locator('li')).toHaveCount(2)
    await expect(revisions.locator('li').nth(1)).toContainText('Out of date: you included, excluded or judged a work or file after this check')
    await revisions.getByRole('button', { name: 'Revision 1' }).click()
    await expect(panel.locator('.sc-sub')).toContainText('Revision 1')
    await expect(panel).toContainText('This is revision 1; the latest is revision 2.')
    const mdHref = await panel.getByRole('link', { name: 'Markdown' }).getAttribute('href')
    const md = await (await request.get(`${SERVER_URL}${mdHref}`)).text()
    expect(md).toContain('| ordinal | title |')
    expect(md).toMatch(/\| 1 \| stale \|/)
    await panel.getByRole('button', { name: 'Show the latest' }).click()
    await expect(panel.locator('.sc-sub')).toContainText('Revision 2')

    // Review R3-1: revision 1 asked for, its answer slow, then the latest asked for: the page ends on the latest.
    const late = await holdFirst(page, rev1)
    await revisions.getByRole('button', { name: 'Revision 1' }).click()
    await late.fetched
    await revisions.getByRole('button', { name: 'Revision 2' }).click()
    await expect(panel.locator('.sc-sub')).toContainText('Revision 2')
    late.release()
    await late.done
    await page.waitForTimeout(500)
    await expect(panel.locator('.sc-sub')).toContainText('Revision 2')
    await expect(panel).not.toContainText('This is revision 1')
    await late.stop()

    // Review R3-2: the question is revised; revision 2 goes stale and still shows the sentence it checked, apart from
    // the new question.
    const research = (await (await request.get(`${SERVER_URL}/api/researches/${researchId}`)).json()).research
    const revised = 'SYNTHETIC relays share a molecule budget across hops.'
    expect((await request.post(`${SERVER_URL}/api/researches/${researchId}/scope`, { headers: h, data: { question: revised, expected_version: research.version } })).ok()).toBe(true)
    await page.reload()
    await expect(panel.locator('.sc-sub')).toContainText('Out of date')
    await expect(panel.locator('.notice')).toContainText('the question was revised after this check')
    await expect(panel.locator('.sc-sentence q')).toHaveText(SENTENCE)
    await expect(page.getByText(revised).first()).toBeVisible()

    // Phone width: no sideways scroll.
    await page.setViewportSize({ width: 390, height: 844 })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await shot(page, '04-phone')
  })

  test('with attached files only, Home starts the check itself on the question revision it created', async ({ page }) => {
    await page.goto(SERVER_URL)
    await expect(page.locator('.models-summary')).toContainText('fixture-model')
    await page.locator('input[type=file]').first().setInputFiles({ name: 'SYNTHETIC-claim.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\n%%EOF\n') })
    await page.getByLabel('Source scope').click()
    await page.getByRole('option', { name: 'Attached files' }).click()
    await chip(page).click()
    await expect(chip(page)).toHaveAttribute('aria-pressed', 'true')
    await page.getByLabel('Statement to check').fill(SENTENCE)
    const run = page.waitForRequest(r => r.method() === 'POST' && /\/api\/researches\/[^/]+\/runs$/.test(new URL(r.url()).pathname))
    await page.getByRole('button', { name: 'Start research' }).click()
    expect((await run).postDataJSON()).toEqual({ kind: 'statement_check', expected_scope_revision: 1 })
    await expect(page).toHaveURL(/#\/research\//)
    // The file has no readable text, so the check lists it with nothing to read: no model is asked.
    await expect(page.locator('.sc-panel')).toContainText('Check finished: 0 works completed, 0 could not be checked.', { timeout: 60_000 })
    await expect(group(page, 'not_checked')).toContainText('No text to read, so no model was asked')
  })
})
