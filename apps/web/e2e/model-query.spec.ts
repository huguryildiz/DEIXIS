import { expect, test, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

// Case I: a model writes the sw discovery run's search query, the approval card shows it with the query built from
// the question's words beside it, and a failed model stops the run until the user says what to search with (D92).
//
// Its own fixture server: the application of case H started with the model-written query. The model is scripted and
// every record SYNTHETIC, so a passing case shows application behavior, not whether a model writes a good query.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

const QUESTION = 'How is SYNTHETIC molecule release scheduling optimised in relay networks with bisection search to improve bit error probability?'

class ModelQueryServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-model-query-'))
  constructor(readonly port: number) {}

  async start() {
    const env = {  // no provider keys or user data directory reach the fixture
      PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend'),
      DEIXIS_SEARCH_WORKFLOW: 'sw', DEIXIS_PROTOCOL_APPROVAL: 'ask', DEIXIS_SEARCH_QUERY: 'model',
    }
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`http://127.0.0.1:${this.port}/api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`model query fixture server on ${this.port} did not start`)
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
const termRow = (page: Page, phrase: string) => page.locator('.approval-term', { has: page.locator('.approval-phrase', { hasText: phrase }) })

async function startResearch(page: Page, server: ModelQueryServer, question: string) {
  await page.goto(server.url())
  await page.getByLabel('Research question').fill(question)
  await expect(page.locator('.models-summary')).toContainText('fixture-model')
  await page.getByRole('button', { name: 'Start research' }).click()
  await page.waitForURL(/#\/research\//)
}

test.describe.serial('I: the model-written search query of an sw discovery run', () => {
  const server = new ModelQueryServer(8790)
  let page: Page

  test.beforeAll(async ({ browser }) => {
    await server.start()
    page = await browser.newPage()
  })
  test.afterAll(async () => { await page?.close(); await server.stop() })

  test('the card shows the model query, what the model said of each term, and the code query beside it', async () => {
    await startResearch(page, server, QUESTION)
    await expect(card(page)).toBeVisible({ timeout: 60_000 })
    await expect(card(page)).toContainText('A model wrote these search terms from the question.')
    await expect(termRow(page, 'molecule release')).toContainText('written by the model')
    await expect(termRow(page, 'molecule release')).toContainText('topic')
    await expect(termRow(page, 'bisection search')).toContainText('method')
    await expect(termRow(page, 'molecule release')).toContainText('with the other block')
    const queries = card(page).locator('.approval-queries')
    await expect(queries).toContainText('"relay networks" AND ("molecule release" OR "bisection search")')
    await expect(queries.getByRole('checkbox')).toBeChecked()
    await shot(page, 'I-model-query-desktop')
  })

  test('switching the code query off is a correction, and only the model query is searched', async () => {
    await card(page).locator('.approval-queries').getByRole('checkbox').uncheck()
    await expect(page.locator('.approval-summary')).toContainText('the code’s query switched off')
    await card(page).getByRole('button', { name: 'Approve and search' }).click()
    await expect(page.locator('.approval-card.is-approved')).toBeVisible({ timeout: 60_000 })
    await expect(page.locator('.approval-card.is-approved')).toContainText('corrected before searching')
    await page.locator('.approval-toggle').click()
    const sent = page.locator('.approval-diff-group', { hasText: 'Queries sent' }).locator('li')
    await expect(sent.first()).toContainText('"relay networks" AND ("molecule release" OR "bisection search")')
    await expect(page.locator('.approval-diff-group', { hasText: 'Queries sent' })).not.toContainText('from the question’s words')
    await shot(page, 'I-model-query-approved-desktop')
  })

  test('a failed model stops the run, and the code query is searched only when the user chooses it', async () => {
    await startResearch(page, server, `${QUESTION} [query-down]`)
    const note = page.locator('.chat-note.is-warning')
    await expect(note).toContainText('The model could not write the search query', { timeout: 60_000 })
    // Nothing was searched, and no approval card was opened for a query nobody wrote.
    await expect(card(page)).toHaveCount(0)
    await expect(page.locator('.run-strip').getByRole('button', { name: 'Resume' })).toBeVisible()
    await shot(page, 'I-model-query-failed-desktop')
    await note.getByRole('button', { name: 'Search with the query built from the question’s words' }).click()
    await expect(card(page)).toBeVisible({ timeout: 60_000 })
    await expect(card(page)).toContainText('You chose the query DEIXIS built from the question’s words.')
    await expect(termRow(page, 'relay networks')).toContainText('from the question')
    await expect(card(page).locator('.approval-queries')).toHaveCount(0)
    await shot(page, 'I-model-query-code-only-desktop')
  })
})
