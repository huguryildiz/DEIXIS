import { expect, test, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'

// Case T (clean start, decision B): a discovery run whose vocabulary cannot be searched ends with a plain reason.
// Nothing is searched, nothing waits for the user's approval and Resume is not offered; the way on is to rewrite the
// question in the notice under the steps (S9, R21), and Search again saves it as a new revision that searches as any
// other does. "[vocab-empty]" makes every count probe answer 0,
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
    text: 'No search term could be built from the question, so nothing was searched.',
    step: 'Stopped while planning: no search term could be built from the question' },
  { question: 'Which relay networks are reported? [vocab-broad]', reason: 'vocabulary_too_broad',
    text: 'Every search term in the question is too common to search on its own, so nothing was searched.',
    step: 'Stopped while planning: the question is too broad' },
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
  for (const { question, reason, text, step } of CASES) {
    test(`T: ${reason} ends the run in plain words and a revised question searches, at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 })
      await page.goto(`${server.url}/`)
      await page.getByLabel('Research question').fill(question)
      await expect(page.locator('.models-summary')).toContainText('fixture-model')
      await page.getByRole('button', { name: 'Start research' }).click()
      await page.waitForURL(/#\/research\//)
      const rid = decodeURIComponent(page.url().split('#/research/')[1].split(/[/?]/)[0])

      // The steps say where it stopped, the notice under them says why in plain words (mockup's warn notice), and the
      // run's status change is announced.
      const note = page.locator('.chat-note.notice.is-warning')
      await expect(note).toContainText(text, { timeout: 60_000 })
      await expect(note).toContainText('Revise the question above')
      await expect(note).not.toContainText(reason)
      await expect(page.locator('.chat-step.att .chat-step-line')).toHaveText(step)
      await expect(page.locator('.toast.is-error')).toContainText(`Search & screening failed. ${text}`)

      // No plan to approve and no Resume: the run is over, not waiting. Nothing was planned, so no plan step finished.
      await expect(page.locator('.chat-step-line', { hasText: 'Planned the searches' })).toHaveCount(0)
      await expect(page.getByRole('button', { name: /approve/i })).toHaveCount(0)
      await expect(page.locator('.run-strip')).toHaveCount(0)
      await expect(page.getByRole('button', { name: /^Resume/ })).toHaveCount(0)
      let current = await view(page, rid)
      const failed = current.runs.find(r => r.kind === 'discovery')!
      expect([failed.status, failed.pause_reason]).toEqual(['failed', reason])
      expect(current.search_runs).toHaveLength(0)
      expect(current.runs.map(r => r.kind)).toEqual(['discovery'])
      const resume = await page.request.post(`${server.url}/api/runs/${failed.id}/resume`, { headers: await headers(page) })
      expect(resume.status()).toBe(409)
      expect(await noHorizontalScroll(page)).toBe(true)
      await page.screenshot({ path: path.join(OUT, `T-${reason}-${width}.png`), animations: 'disabled', fullPage: true })

      // The user rewrites the question in the notice; Search again saves it as revision 2, which searches without asking.
      await page.getByRole('button', { name: 'Dismiss notification' }).click()
      const rewrite = note.getByRole('textbox', { name: 'Rewrite the question' })
      await expect(rewrite).toHaveValue(question)
      await rewrite.fill(QUESTION)
      await note.getByRole('button', { name: 'Search again' }).click()
      const planned = page.locator('.chat-step-line', { hasText: 'Planned the searches' })
      await expect(planned).toBeVisible({ timeout: 60_000 })
      await planned.click()
      await expect(page.locator('.chat-step.open .chat-step-detail')).toContainText('Nobody reviewed the search vocabulary; the fast path went on without asking.')
      await expect.poll(async () => {
        current = await view(page, rid)
        return current.runs.find(r => r.kind === 'discovery' && r.scope_revision === 2)?.status
      }, { timeout: 60_000 }).toBe('completed')
      expect(current.scope.revision).toBe(2)
      expect(current.search_runs.length).toBeGreaterThan(0)
      // The ended run stays in the history with its reason; its notice no longer offers a rewrite of the old question.
      expect(current.runs.find(r => r.id === failed.id)).toMatchObject({ status: 'failed', pause_reason: reason })
      await expect(page.locator('.chat-note.notice.is-warning')).toContainText(text)
      await expect(page.getByRole('textbox', { name: 'Rewrite the question' })).toHaveCount(0)
      expect(await noHorizontalScroll(page)).toBe(true)
      await page.screenshot({ path: path.join(OUT, `T-${reason}-revised-${width}.png`), animations: 'disabled', fullPage: true })
    })
  }
}

// Stored key terms go into the search ahead of the question, so the rewrite shows them to change: a narrower question
// with the old terms hidden would search the same broad terms again (Sol S9 r1). The fixture cannot end a run on terms a
// person gave (they are searched as given), so the view of the ended revision is shown with stored terms added; what
// Search again sends is the backend's real revision.
test('T: the rewrite shows the stored key terms and searches with the edited ones', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const created = await page.request.post(`${server.url}/api/researches`, { headers: await headers(page), data: {
    question: CASES[1].question, model_connection: 'codex', requested_model: 'fixture-model', effort: 'quick' } })
  expect(created.status()).toBe(201)
  const rid = (await created.json()).research.id as string
  await page.route(url => url.pathname === `/api/researches/${rid}`, async route => {
    const response = await route.fetch()
    const body = await response.json()
    if (body.scope.revision === 1) body.scope.key_terms = 'relay networks'
    await route.fulfill({ response, json: body })
  })
  expect((await page.request.post(`${server.url}/api/researches/${rid}/runs`, { headers: await headers(page), data: { kind: 'discovery' } })).ok()).toBe(true)
  await page.goto(`${server.url}/#/research/${rid}`)
  const note = page.locator('.chat-note.notice.is-warning')
  await expect(note).toContainText(CASES[1].text, { timeout: 60_000 })
  const terms = note.getByRole('textbox', { name: 'English key terms (optional)' })
  await expect(terms).toHaveValue('relay networks')
  await expect(note).toContainText('The search uses these terms ahead of the question.')
  await note.getByRole('textbox', { name: 'Rewrite the question' }).fill(QUESTION)
  await terms.fill('molecule release scheduling')
  await note.getByRole('button', { name: 'Search again' }).click()
  await expect.poll(async () => {
    const current = await (await page.request.get(`${server.url}/api/researches/${rid}`)).json() as { scope: { revision: number; key_terms: string | null } }
    return [current.scope.revision, current.scope.key_terms]
  }, { timeout: 30_000 }).toEqual([2, 'molecule release scheduling'])
  await page.unrouteAll({ behavior: 'wait' })
})
