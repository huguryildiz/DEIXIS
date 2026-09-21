import { expect, test, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

// Case H: an sw discovery run stops before its first search until the user has approved or corrected the search
// terms and the inclusion criterion (D80, slice 08b).
//
// It runs against its own fixture server: the same application as cases A–G, started with the sw workflow and the
// `ask` approval mode, on its own port and data directory. A–G keep the server they always had.
// Every record is SYNTHETIC and the model is scripted: a passing case shows application behavior, not model quality.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

const QUESTION = 'How is SYNTHETIC molecule release scheduling optimised in relay networks with bisection search to improve bit error probability?'

class SwFixtureServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-sw-approval-'))
  constructor(readonly port: number) {}

  async start() {
    const env = {  // no provider keys or user data directory reach the fixture
      PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend'),
      DEIXIS_SEARCH_WORKFLOW: 'sw', DEIXIS_PROTOCOL_APPROVAL: 'ask',
    }
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`http://127.0.0.1:${this.port}/api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`sw fixture server on ${this.port} did not start`)
  }

  async stop() {
    const proc = this.proc
    if (!proc || proc.exitCode !== null) return
    const exited = new Promise(resolve => proc.once('exit', resolve))
    proc.kill('SIGTERM')
    await exited
  }

  url() { return `http://127.0.0.1:${this.port}/` }
}

const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`), animations: 'disabled', fullPage: true })
const card = (page: Page) => page.locator('.approval-card')
const block = (page: Page, name: string) => page.locator('.approval-block', { has: page.getByText(name, { exact: true }) })
const termRow = (page: Page, phrase: string) => page.locator('.approval-term', { has: page.locator('.approval-phrase', { hasText: phrase }) })
const suggestions = (page: Page) => block(page, 'Other names for these terms')
// Scoped rows: once the model has proposed names, a phrase can be in both a searched block and the proposals list.
const suggestionRow = (page: Page, phrase: string) => suggestions(page).locator('.approval-term', { has: page.locator('.approval-phrase', { hasText: phrase }) })
const blockRow = (page: Page, name: string, phrase: string) => block(page, name).locator('.approval-term', { has: page.locator('.approval-phrase', { hasText: phrase }) })

async function startResearch(page: Page, server: SwFixtureServer, question: string) {
  await page.goto(server.url())
  await page.getByLabel('Research question').fill(question)
  await expect(page.locator('.models-summary')).toContainText('fixture-model')
  await page.getByRole('button', { name: 'Start research' }).click()
  await page.waitForURL(/#\/research\//)
}

test.describe.serial('H: the protocol approval of an sw discovery run', () => {
  const server = new SwFixtureServer(8789)
  let page: Page

  test.beforeAll(async ({ browser }) => {
    await server.start()
    page = await browser.newPage()
  })
  test.afterAll(async () => { await page?.close(); await server.stop() })

  test('the run stops before its first search and shows what it would search with', async () => {
    await startResearch(page, server, QUESTION)
    await expect(card(page)).toBeVisible({ timeout: 60_000 })
    await expect(page.locator('.chat-note.is-warning')).toContainText('This run has not searched yet.')
    // Nothing has been searched: no query was sent, no candidate was written.
    await expect(page.locator('.chat-step', { hasText: 'Provider searches' })).toContainText('Waiting')
    await expect(page.locator('.chat-list code')).toHaveCount(0)
    await page.getByRole('tab', { name: /^Sources/ }).click()
    await expect(page.locator('.source-row')).toHaveCount(0)
    await page.getByRole('tab', { name: 'Answer' }).click()

    // The proposal is on the screen with its blocks, counts and origins.
    await expect(termRow(page, 'relay networks')).toContainText('from the question')
    await expect(block(page, 'Setting')).toContainText('relay networks')
    await expect(block(page, 'Claim under test')).toContainText('bisection search')
    await expect(card(page)).toContainText('SYNTHETIC: the paper puts forward a method of its own')
    // There is no plain Resume on a run that waits for the approval.
    await expect(page.locator('.run-strip')).toBeVisible()
    await expect(page.locator('.run-strip').getByRole('button', { name: 'Resume' })).toHaveCount(0)
    await shot(page, 'H-approval-waiting-desktop')
  })

  test('a correction is drafted, counted in the summary, and a repeated term is refused in place', async () => {
    await termRow(page, 'bit error probability').getByRole('button', { name: 'Remove' }).click()
    await expect(termRow(page, 'bit error probability')).toContainText('removed by you')

    await block(page, 'Setting').getByLabel('Add a term to Setting').fill('molecular communication')
    await block(page, 'Setting').getByRole('button', { name: 'Add' }).click()
    await expect(termRow(page, 'molecular communication')).toContainText('will be counted after approval')

    const moving = termRow(page, 'relay networks')
    await moving.getByLabel('Block of “relay networks”').click()
    await page.getByRole('option', { name: 'Claim under test' }).click()
    await expect(block(page, 'Claim under test')).toContainText('relay networks')
    await expect(termRow(page, 'relay networks')).toContainText('moved by you')

    await card(page).getByLabel('Criterion').fill('SYNTHETIC: the paper reports a measured release schedule of its own.')
    await expect(page.locator('.approval-summary')).toContainText('1 term removed · 1 term added · 1 term moved · criterion corrected')

    // A term the proposal already holds is refused where it was typed, and the draft above stays as it is.
    await block(page, 'Task').getByLabel('Add a term to Task').fill('Relay Networks')
    await block(page, 'Task').getByRole('button', { name: 'Add' }).click()
    await expect(block(page, 'Task').locator('.approval-row-error')).toContainText('“relay networks” is already in the search terms.')
    await expect(page.locator('.approval-summary')).toContainText('1 term removed · 1 term added · 1 term moved · criterion corrected')
    await shot(page, 'H-approval-error-desktop')
  })

  test('a correction the backend refuses names the fault and keeps the draft', async () => {
    // The criterion is emptied: a fault only the backend can name, so the 422 path is the one under test.
    await card(page).getByLabel('Criterion').fill('')
    await card(page).getByRole('button', { name: 'Approve and search' }).click()
    await expect(page.locator('.approval-errors')).toContainText('The criterion is empty')
    await expect(page.locator('.approval-errors')).toContainText('Nothing was sent to a provider.')
    // The draft above is untouched: the term operations and the removed row are still there.
    await expect(page.locator('.approval-summary')).toContainText('1 term removed · 1 term added · 1 term moved · criterion corrected')
    await expect(termRow(page, 'relay networks')).toContainText('moved by you')
    await shot(page, 'H-approval-refused-desktop')
    await card(page).getByLabel('Criterion').fill('SYNTHETIC: the paper reports a measured release schedule of its own.')
  })

  test('the model is asked for other names and the draft correction survives the round trip', async () => {
    await card(page).getByRole('button', { name: 'Ask the model for other names' }).click()
    // The proposals arrive after one model call and one count request per proposal code did not drop.
    await expect(suggestions(page)).toContainText('another name for', { timeout: 60_000 })
    await expect(suggestionRow(page, 'synthetic release timing')).toContainText('800 records hold this name')
    await expect(suggestionRow(page, 'synthetic release timing')).toContainText('suggested by the model')
    // The draft correction is where it was, and nothing has been searched.
    await expect(page.locator('.approval-summary')).toContainText('1 term removed · 1 term added · 1 term moved · criterion corrected')
    await expect(blockRow(page, 'Claim under test', 'relay networks')).toContainText('moved by you')
    await expect(page.locator('.chat-step', { hasText: 'Provider searches' })).toContainText('Waiting')
    await shot(page, 'H-suggestions-ready-desktop')
  })

  test('a proposal no record holds and a repeated one are faded with their reason and cannot be added', async () => {
    const unheld = suggestionRow(page, 'synthetic unheld name')
    await expect(unheld).toContainText('cannot be added: no record holds it')
    await expect(unheld.getByRole('button', { name: 'Add' })).toHaveCount(0)
    const repeated = suggestionRow(page, 'relay networks')
    await expect(repeated).toContainText('cannot be added: already one of the terms above')
    await expect(repeated.getByRole('button', { name: 'Add' })).toHaveCount(0)
    // The button is gone: the model is asked once per question.
    await expect(card(page).getByRole('button', { name: 'Ask the model for other names' })).toHaveCount(0)
  })

  test('an added proposal joins the draft and the change summary counts it apart', async () => {
    await suggestionRow(page, 'synthetic release timing').getByRole('button', { name: 'Add' }).click()
    await expect(block(page, 'Setting')).toContainText('synthetic release timing')
    await expect(page.locator('.approval-summary')).toContainText('2 terms added · 1 of them proposed by the model')
    await expect(suggestions(page)).toContainText('added to the Setting block above')
  })

  test('approving sends the corrected protocol and the run searches with it', async () => {
    await card(page).getByRole('button', { name: 'Approve and search' }).click()
    // The card says "approved" only once the view does; the run then searches. (The "correction recorded" toast is
    // not asserted: the scripted run finishes fast enough to replace it with its own.)
    await expect(page.locator('.approval-card.is-approved')).toBeVisible({ timeout: 60_000 })
    await expect(page.locator('.approval-toggle')).toContainText('You approved these search terms and this criterion.')
    await expect(page.locator('.chat-step', { hasText: 'Conducted' })).toBeVisible({ timeout: 60_000 })
    await page.getByRole('tab', { name: /^Sources/ }).click()
    await expect(page.locator('.source-row').first()).toBeVisible({ timeout: 60_000 })
    await page.getByRole('tab', { name: 'Answer' }).click()
  })

  test('the folded summary opens on the difference between what was proposed and what was searched', async () => {
    await page.locator('.approval-toggle').click()
    const diff = page.locator('.approval-diff')
    await expect(diff).toContainText('Removed terms')
    await expect(diff.locator('.approval-diff-group', { hasText: /^Removed terms/ })).toContainText('bit error probability')
    await expect(diff.locator('.approval-diff-group', { hasText: /^Added terms/ })).toContainText('molecular communication')
    await expect(diff.locator('.approval-diff-group', { hasText: /^Moved terms/ })).toContainText('Setting → Claim under test')
    await expect(diff.locator('.approval-diff-group', { hasText: /^Criterion/ })).toContainText('SYNTHETIC: the paper reports a measured release schedule of its own.')
    // The term the user added really entered the query, by the root word the rebuild chose for it.
    await expect(diff.locator('.approval-diff-group', { hasText: /^Queries sent/ }).locator('code').first()).toContainText('molecular')
    await shot(page, 'H-approval-approved-desktop')
  })

  test('the approved summary badges the added proposal and lists the ones that were not added', async () => {
    const diff = page.locator('.approval-diff')
    const addedGroup = diff.locator('.approval-diff-group', { hasText: /^Added terms/ })
    await expect(addedGroup.locator('li', { hasText: 'synthetic release timing' })).toContainText('suggested by the model')
    await expect(addedGroup.locator('li', { hasText: 'molecular communication' })).toContainText('added by you')
    const open = diff.locator('.approval-diff-group', { hasText: /^Proposed, not added/ })
    await expect(open).toContainText('synthetic unheld name')
    await expect(open).toContainText('dropped: no record holds it')
    await shot(page, 'H-suggestions-approved-desktop')
  })

  test('a failed request shows its reason and a retry, and the run can be approved without proposals', async ({ browser }) => {
    const down = await browser.newPage()
    try {
      await startResearch(down, server, `${QUESTION} [suggest-down]`)
      await expect(card(down)).toBeVisible({ timeout: 60_000 })
      await card(down).getByRole('button', { name: 'Ask the model for other names' }).click()
      await expect(suggestions(down)).toContainText('The model call did not complete', { timeout: 60_000 })
      await expect(suggestions(down).getByRole('button', { name: 'Try again' })).toBeVisible()
      await shot(down, 'H-suggestions-failed-desktop')
      await down.getByRole('button', { name: 'Use dark theme' }).click()
      await shot(down, 'H-suggestions-failed-desktop-dark')
      await down.setViewportSize({ width: 390, height: 844 })
      await shot(down, 'H-suggestions-failed-mobile-dark')
      // Nothing was proposed, so approving is still one click.
      await card(down).getByRole('button', { name: 'Approve and search' }).click()
      await expect(down.locator('.approval-card.is-approved')).toBeVisible({ timeout: 60_000 })
    } finally { await down.close() }
  })

  test('the waiting card reads in dark theme and at 390 px', async ({ browser }) => {
    const narrow = await browser.newPage({ viewport: { width: 390, height: 844 } })
    try {
      await startResearch(narrow, server, `${QUESTION} A second SYNTHETIC research.`)
      await expect(card(narrow)).toBeVisible({ timeout: 60_000 })
      await shot(narrow, 'H-approval-waiting-mobile')
      await narrow.getByRole('button', { name: 'Use dark theme' }).click()
      await shot(narrow, 'H-approval-waiting-mobile-dark')
      // The proposals list in the theme and the width it is hardest to read in.
      await card(narrow).getByRole('button', { name: 'Ask the model for other names' }).click()
      await expect(suggestions(narrow)).toContainText('another name for', { timeout: 60_000 })
      await shot(narrow, 'H-suggestions-ready-mobile-dark')
      await narrow.setViewportSize({ width: 1280, height: 900 })
      await shot(narrow, 'H-approval-waiting-desktop-dark')
      await shot(narrow, 'H-suggestions-ready-desktop-dark')
    } finally { await narrow.close() }
  })

  test('an approval with no correction goes on in one click', async ({ browser }) => {
    const other = await browser.newPage()
    try {
      await startResearch(other, server, `${QUESTION} A third SYNTHETIC research.`)
      await expect(card(other)).toBeVisible({ timeout: 60_000 })
      await expect(other.locator('.approval-summary')).toContainText('No change: the proposal is approved as it stands.')
      await card(other).getByRole('button', { name: 'Approve and search' }).click()
      await expect(other.locator('.approval-card.is-approved')).toBeVisible({ timeout: 60_000 })
      await expect(other.locator('.approval-toggle')).toContainText('approved as proposed')
      await expect(other.locator('.chat-step', { hasText: 'Conducted' })).toBeVisible({ timeout: 60_000 })
    } finally { await other.close() }
  })
})
