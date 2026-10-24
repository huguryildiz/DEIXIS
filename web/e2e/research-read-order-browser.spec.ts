import { expect, request as apiRequest, test } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'

// Browser regression (audit F5): two reads of one research overlap and the older one answers last. A rename runs
// `act(...)`, whose own `await load()` starts right after the PUT; the event it records reloads the page a moment later
// through the subscribe effect. The first read is held until the second has been served, and its body is a stale view
// (SYNTHETIC title). The page must keep the newer view.
const REPO = path.resolve(process.cwd(), '..')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? '/tmp/deixis-read-order-acceptance')
const port = nextPort()
const url = `http://127.0.0.1:${port}`
const STALE = 'STALE VIEW SYNTHETIC'
const FRESH = 'Fresh title after rename SYNTHETIC'
let proc: ChildProcess | undefined
let rid = ''

test.beforeAll(async () => {
  mkdirSync(OUT, { recursive: true })
  const data = mkdtempSync(path.join(tmpdir(), 'deixis-read-order-'))
  proc = spawn(path.join(REPO, '.venv/bin/python'), [path.join(REPO, 'tests/acceptance/fixture_server.py'), '--data-dir', data, '--port', String(port)], {
    cwd: REPO, env: { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '' }, stdio: 'inherit',
  })
  await expect.poll(async () => {
    try { return (await fetch(`${url}/api/health`)).ok } catch { return false }
  }, { timeout: 30_000 }).toBe(true)
  // The fixture server starts empty: create a research and let its runs finish, so no run records events during the test.
  const api = await apiRequest.newContext({ baseURL: url, extraHTTPHeaders: { origin: url } })
  const token = (await (await api.get('/api/session')).json()).csrf_token as string
  const post = (to: string, data: unknown) => api.post(to, { data, headers: { 'x-deixis-csrf': token } })
  const created = await post('/api/researches', { question: 'How do SYNTHETIC molecular relays schedule their releases?', model_connection: 'codex', requested_model: 'fixture-model', effort: 'quick' })
  expect(created.status()).toBe(201)
  rid = (await created.json()).research.id
  expect((await post(`/api/researches/${rid}/runs`, { kind: 'discovery' })).ok()).toBe(true)
  const settled = async () => {
    const view = await (await api.get(`/api/researches/${rid}`)).json() as { runs: { kind: string; status: string }[] }
    const done = ['completed', 'failed', 'cancelled', 'paused']
    return view.runs.some(r => r.kind === 'answer') && view.runs.every(r => done.includes(r.status))
  }
  await expect.poll(settled, { timeout: 90_000, intervals: [500] }).toBe(true)
  await api.dispose()
})

test.afterAll(async () => {
  if (proc && proc.exitCode === null) {
    const ended = new Promise(resolve => proc!.once('exit', resolve))
    proc.kill('SIGTERM')
    await ended
  }
})

test('an older read that answers after a newer one cannot bring back a stale view', async ({ page }) => {
  // The question bubble is static text, unlike the heading (a typewriter): the stale view carries a marker there. The page
  // notes if the marker is ever on screen, so a stale view that is shown and replaced again still fails the test.
  await page.addInitScript(marker => {
    const w = window as unknown as { __staleShown: boolean }
    w.__staleShown = false
    new MutationObserver(() => { if (document.querySelector('.chat-question')?.textContent?.includes(marker)) w.__staleShown = true })
      .observe(document, { subtree: true, childList: true, characterData: true })
  }, STALE)
  await page.goto(`${url}/#/research/${rid}`)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  const bubble = page.locator('.chat-question span')
  const question = (await bubble.textContent())!
  expect(question).not.toContain(STALE)

  let reads = 0
  let newerShown!: () => void
  const newerIsOnScreen = new Promise<void>(resolve => { newerShown = resolve })
  let staleSent!: () => void
  const staleIsSent = new Promise<void>(resolve => { staleSent = resolve })
  await page.route(`${url}/api/researches/${rid}`, async route => {
    if (route.request().method() !== 'GET') return route.continue()
    const n = ++reads
    if (n !== 1) return route.continue()
    // The older read: it left first and answers last, with a view from before the rename.
    const response = await route.fetch()
    const view = await response.json()
    view.scope.question = STALE
    await newerIsOnScreen
    await route.fulfill({ response, json: view })
    staleSent()
  })

  await page.locator('h1 .research-title-button').click()
  await page.getByRole('textbox', { name: 'Research title' }).fill(FRESH)
  await page.keyboard.press('Enter')

  // The newer read is on screen (only a read can show the new title) while the older one is still held.
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(FRESH)
  expect(reads).toBeGreaterThanOrEqual(2)
  newerShown()
  // Then the older one answers; give the page the frames it needs to apply it, if it ever would.
  await staleIsSent
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 200)))))

  await expect(bubble).toHaveText(question)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(FRESH)
  expect(await page.evaluate(() => (window as unknown as { __staleShown: boolean }).__staleShown)).toBe(false)
})
