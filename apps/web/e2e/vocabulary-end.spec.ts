import { expect, test, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'

// Case T (clean start, decision B): a discovery run whose vocabulary cannot be searched ends with a plain reason.
// Nothing is searched, no approval card waits for the user and Resume is not offered; the way on is to revise the
// question, and the new revision searches as any other does. "[vocab-empty]" makes every count probe answer 0,
// "[vocab-broad]" more than the very-large limit (tests/acceptance/fixture_server.py). Every record is SYNTHETIC and
// the model is scripted: a passing case shows application behavior, not how often this happens with a live provider.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

const QUESTION = 'How is SYNTHETIC molecule release scheduling optimized in relay networks?'
// Every term too common ends the run only when the terms make one block, so that case asks a one-concept question.
const CASES = [
  { question: `${QUESTION} [vocab-empty]`, reason: 'vocabulary_empty',
    text: 'No search term could be built from the question, so nothing was searched.' },
  { question: 'Which relay networks are reported? [vocab-broad]', reason: 'vocabulary_too_broad',
    text: 'Every search term in the question is too common to search on its own, so nothing was searched.' },
]

type RunRow = { id: string, kind: string, status: string, pause_reason: string | null, scope_revision: number }

class Server {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-vocabulary-end-'))
  constructor(readonly port: number) {}

  async start() {
    const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend') }
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`${this.url}/api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`vocabulary-end fixture server on ${this.port} did not start`)
  }

  async stop() {
    const proc = this.proc
    if (!proc || proc.exitCode !== null) return
    const exited = new Promise(resolve => proc.once('exit', resolve))
    proc.kill('SIGTERM')
    await exited
  }

  get url() { return `http://127.0.0.1:${this.port}` }
}

const server = new Server(nextPort())
test.beforeAll(async () => { await server.start() })
test.afterAll(async () => { await server.stop() })

async function headers(page: Page) {
  await page.request.get(`${server.url}/api/session`)
  const csrf = (await page.context().cookies(server.url)).find(cookie => cookie.name === 'deixis_csrf')
  expect(csrf).toBeTruthy()
  return { origin: server.url, 'x-deixis-csrf': csrf!.value }
}

async function view(page: Page, rid: string) {
  return (await (await page.request.get(`${server.url}/api/researches/${rid}`)).json()) as {
    runs: RunRow[], search_runs: unknown[], scope: { revision: number }
  }
}

const noHorizontalScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)

for (const width of [1440, 390]) {
  for (const { question, reason, text } of CASES) {
    test(`T: ${reason} ends the run in plain words and a revised question searches, at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 })
      await page.goto(`${server.url}/`)
      await page.getByLabel('Research question').fill(question)
      await expect(page.locator('.models-summary')).toContainText('fixture-model')
      await page.getByRole('button', { name: 'Start research' }).click()
      await page.waitForURL(/#\/research\//)
      const rid = decodeURIComponent(page.url().split('#/research/')[1].split(/[/?]/)[0])

      // The timeline says why in plain words, and the run's status change is announced.
      const note = page.locator('.chat-note.is-error')
      await expect(note).toContainText(text, { timeout: 60_000 })
      await expect(note).toContainText('Revise the question below')
      await expect(note).not.toContainText(reason)
      await expect(page.locator('.toast.is-error')).toContainText(`Search & screening failed. ${text}`)

      // No approval card or pending approval, and no Resume: the run is over, not waiting.
      await expect(page.locator('.approval-card')).toHaveCount(0)
      await expect(page.getByRole('button', { name: /approve/i })).toHaveCount(0)
      await expect(page.locator('.run-strip')).toHaveCount(0)
      await expect(page.getByRole('button', { name: 'Resume' })).toHaveCount(0)
      let current = await view(page, rid)
      const failed = current.runs.find(r => r.kind === 'discovery')!
      expect([failed.status, failed.pause_reason]).toEqual(['failed', reason])
      expect(current.search_runs).toHaveLength(0)
      expect(current.runs.map(r => r.kind)).toEqual(['discovery'])
      const resume = await page.request.post(`${server.url}/api/runs/${failed.id}/resume`, { headers: await headers(page) })
      expect(resume.status()).toBe(409)
      expect(await noHorizontalScroll(page)).toBe(true)
      await page.screenshot({ path: path.join(OUT, `T-${reason}-${width}.png`), animations: 'disabled', fullPage: true })

      // The user revises the question; the new revision searches and the run goes on without asking.
      await page.getByRole('button', { name: 'Dismiss notification' }).click()
      await page.getByLabel('Revise the question').fill(QUESTION)
      await page.getByRole('button', { name: 'Save revision' }).click()
      await expect(page.locator('.toast')).toContainText('Question revised.')
      await page.getByRole('button', { name: 'Search providers' }).click()
      await expect(page.locator('.approval-card')).toContainText('not reviewed, fast path', { timeout: 60_000 })
      await expect.poll(async () => {
        current = await view(page, rid)
        return current.runs.find(r => r.kind === 'discovery' && r.scope_revision === 2)?.status
      }, { timeout: 60_000 }).toBe('completed')
      expect(current.scope.revision).toBe(2)
      expect(current.search_runs.length).toBeGreaterThan(0)
      // The ended run stays in the history with its reason.
      expect(current.runs.find(r => r.id === failed.id)).toMatchObject({ status: 'failed', pause_reason: reason })
      await expect(page.locator('.chat-note.is-error')).toContainText(text)
      expect(await noHorizontalScroll(page)).toBe(true)
      await page.screenshot({ path: path.join(OUT, `T-${reason}-revised-${width}.png`), animations: 'disabled', fullPage: true })
    })
  }
}
