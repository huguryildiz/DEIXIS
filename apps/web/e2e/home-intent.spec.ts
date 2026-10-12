import { expect, test, type Page, type Request } from '@playwright/test'
import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'

// Parity slice S5b: Home's mode chips (research intent), the Resume and Suggested cards, the first-run setup card and
// the PDF guide rows (D3). The fixture server has one connected model and SYNTHETIC records; routed answers below are
// SYNTHETIC too. Passing shows the page's wiring to the API, not search or model quality.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
mkdirSync(path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance'), { recursive: true })

class HomeServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-home-intent-'))
  constructor(readonly port: number) {}
  private env() { return { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend') } }

  async start() {
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env: this.env(), stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`http://127.0.0.1:${this.port}/api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`home intent fixture server on ${this.port} did not start`)
  }

  async stop() {
    const proc = this.proc
    if (!proc || proc.exitCode !== null) return
    const exited = new Promise(resolve => proc.once('exit', resolve))
    proc.kill('SIGTERM')
    await exited
  }

  /** A SYNTHETIC PDF with text, written by the fixture server (`--write-replacement-pdf` / `--write-hostile-pdf`). */
  pdf(kind: 'replacement' | 'hostile') {
    const file = path.join(this.dataDir, '..', `${kind}-${this.port}.pdf`)
    spawnSync(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', '0', `--write-${kind}-pdf`, file], { cwd: REPO, env: this.env() })
    return file
  }

  url(hash = '') { return `http://127.0.0.1:${this.port}/${hash}` }
}

const tinyPdf = (name: string) => ({ name, mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\n%%EOF\n') })
const chip = (page: Page, name: string) => page.locator('.mode-chips').getByRole('button', { name, exact: true })
const createBody = (request: Request) => request.postDataJSON() as { intent: string; source_scope: string }
const isCreate = (request: Request) => request.method() === 'POST' && new URL(request.url()).pathname === '/api/researches'

test.describe.serial('S5b: Home intent chips, cards, setup card and guide rows', () => {
  const server = new HomeServer(nextPort())
  test.beforeAll(async () => { await server.start() })
  test.afterAll(async () => { await server.stop() })

  test('mode chips: Draft report is on by default, one chip at a time, and the chosen intent is sent', async ({ page }) => {
    await page.goto(server.url())
    await expect(page.locator('.models-summary')).toContainText('fixture-model')
    const names = ['Draft report', 'Find papers', 'Evidence table', 'Compare methods', 'Ask my PDFs']
    await expect(page.locator('.mode-chips .chip')).toHaveText(names)
    await expect(chip(page, 'Draft report')).toHaveAttribute('aria-pressed', 'true')
    // Ask my PDFs needs a PDF; the reason is the button's description.
    await expect(chip(page, 'Ask my PDFs')).toHaveAttribute('aria-disabled', 'true')
    await expect(chip(page, 'Ask my PDFs')).toHaveAccessibleDescription('Add a PDF first')
    await chip(page, 'Evidence table').click()
    await expect(chip(page, 'Evidence table')).toHaveAttribute('aria-pressed', 'true')
    await expect(chip(page, 'Draft report')).toHaveAttribute('aria-pressed', 'false')
    await expect(page.getByLabel('Research question')).toBeFocused()
    await page.getByLabel('Research question').fill('SYNTHETIC evidence table of release schedules')
    const created = page.waitForRequest(isCreate)
    await page.getByRole('button', { name: 'Start research' }).click()
    expect(createBody(await created)).toMatchObject({ intent: 'table', source_scope: 'academic' })
    await expect(page).toHaveURL(/#\/research\//)
  })

  test('Ask my PDFs sets the attached-only scope; another scope turns Draft report back on; Find papers needs a search', async ({ page }) => {
    await page.goto(server.url())
    await expect(page.locator('.models-summary')).toContainText('fixture-model')
    await page.locator('input[type=file]').first().setInputFiles(tinyPdf('SYNTHETIC-ask.pdf'))
    await chip(page, 'Find papers').click()
    await chip(page, 'Ask my PDFs').click()
    await expect(chip(page, 'Ask my PDFs')).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByLabel('Source scope')).toContainText('Attached files')
    await expect(chip(page, 'Find papers')).toHaveAttribute('aria-disabled', 'true')
    await expect(chip(page, 'Find papers')).toHaveAccessibleDescription('Needs academic search')
    // Choosing a scope with a search in the menu leaves "Ask my PDFs": the chip goes back to Draft report.
    await page.getByLabel('Source scope').click()
    await page.getByRole('option', { name: 'Files + academic search' }).click()
    await expect(chip(page, 'Draft report')).toHaveAttribute('aria-pressed', 'true')
    // Choosing the attached scope while "Find papers" is on turns it into Ask my PDFs (finding papers needs a search).
    await chip(page, 'Find papers').click()
    await page.getByLabel('Source scope').click()
    await page.getByRole('option', { name: 'Attached files' }).click()
    await expect(chip(page, 'Ask my PDFs')).toHaveAttribute('aria-pressed', 'true')
    await page.getByLabel('Research question').fill('SYNTHETIC question over my own PDF')
    const created = page.waitForRequest(isCreate)
    await page.getByRole('button', { name: 'Start research' }).click()
    expect(createBody(await created)).toMatchObject({ intent: 'report', source_scope: 'attached' })
  })

  test('Resume card: the latest research, its report version and what waits for the person, kept current by the shell', async ({ page, request }) => {
    const base = server.url()
    const token = (await (await request.get(`${base}api/session`)).json()).csrf_token as string
    const headers = { origin: base.replace(/\/$/, ''), 'x-deixis-csrf': token }
    const title = 'SYNTHETIC resume card research'
    const made = await (await request.post(`${base}api/researches`, { headers, data: { question: title, model_connection: 'codex', requested_model: 'fixture-model', effort: 'quick' } })).json()
    const id = made.research.id as string
    // The list this page receives puts this research first, so the earlier tests' background runs cannot take the
    // card; its awaiting counts are SYNTHETIC (two queue rows and one work waiting for a PDF). Everything else is the
    // server's own list, polled by the shell.
    await page.route('**/api/researches', async route => {
      if (route.request().method() !== 'GET') return route.fallback()
      const response = await route.fetch()
      const list = await response.json() as Array<{ id: string; awaiting: { queue: number; pdf: number } }>
      const mine = list.filter(r => r.id === id).map(r => ({ ...r, awaiting: { queue: 2, pdf: 1 } }))
      await route.fulfill({ response, json: [...mine, ...list.filter(r => r.id !== id)] })
    })
    // Home is open before the answer exists: the card has no report yet and gains it when the shell's poll sees it.
    await page.goto(base)
    const card = page.locator('.home-cards .card').first()
    await expect(card).toContainText('Resume')
    await expect(card.locator('small')).not.toContainText('Report V1')
    await request.post(`${base}api/researches/${id}/runs`, { headers: { ...headers, 'Idempotency-Key': `resume-${id}` }, data: { kind: 'discovery' } })
    await expect(card.locator('small')).toContainText('Report V1 · 3 waiting for you', { timeout: 90_000 })
    await expect(card.locator('p')).not.toHaveText('')
    await expect(card.locator('small')).toContainText('2 in the queue · 1 waiting for your PDF')  // the split, for screen readers
    await card.click()
    await expect(page).toHaveURL(new RegExp(`#/research/${id}$`))
  })

  test('Suggested cards: at most two, labelled only "Suggested", a click fills the composer', async ({ page }) => {
    const suggestion = (n: number) => ({ text: `SYNTHETIC unanswered aspect ${n}`, research_id: `r${n}`, research_title: `SYNTHETIC research ${n}`, answer_id: `a${n}`, created_at: '2026-10-12T10:00:00Z' })
    await page.route('**/api/suggestions', route => route.fulfill({ json: { suggestions: [suggestion(1), suggestion(2), suggestion(3)] } }))
    await page.goto(server.url())
    const cards = page.locator('.home-cards .card', { hasText: 'Suggested' })
    await expect(cards).toHaveCount(2)
    await expect(cards.first().locator('.home-card-tag')).toHaveText('Suggested')
    await expect(cards.first().locator('p')).toHaveText('SYNTHETIC unanswered aspect 1')
    await expect(cards.first().locator('small')).toHaveText('SYNTHETIC research 1')
    await cards.nth(1).click()
    await expect(page.getByLabel('Research question')).toHaveValue('SYNTHETIC unanswered aspect 2')
    await expect(page.getByLabel('Research question')).toBeFocused()
  })

  test('setup card: shown only while no model connection is ready, with the rows of what is set up', async ({ page }) => {
    await page.goto(server.url())
    await expect(page.locator('.models-summary')).toContainText('fixture-model')
    await expect(page.locator('.home-setup')).toHaveCount(0)

    await page.route('**/api/connections**', async route => {
      const response = await route.fetch()
      await route.fulfill({ response, json: { ...(await response.json()), models: {} } })
    })
    await page.reload()
    const setup = page.locator('.home-setup')
    await expect(setup.getByRole('heading', { name: /Set up DEIXIS/ })).toBeVisible()
    await expect(setup).toContainText('Nothing leaves this computer except the searches and the model calls you set up.')
    const rows = setup.locator('.home-setup-row')
    await expect(rows).toHaveCount(3)
    await expect(rows.nth(0)).toContainText('Answer and literature models')
    await expect(rows.nth(1)).toContainText('Scholarly sources')
    await expect(rows.nth(1).locator('.st.ok')).toHaveText('Ready')
    await expect(rows.nth(1)).toContainText('Configured · not tested live.')  // configuration, not a request to the provider
    await expect(rows.nth(2)).toContainText('Lets you open PDFs your library pays for, through its sign-in.')
    await expect(rows.nth(2).getByRole('button', { name: 'Add' })).toBeVisible()
    await expect(page.getByText('Connect a model to start', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Start research' })).toBeDisabled()

    // A saved proxy address is a done step, not a tested one.
    await page.route('**/api/institution-proxy', route => route.request().method() === 'GET'
      ? route.fulfill({ json: { address: 'https://login.proxy.example.edu/login?url=' } }) : route.fallback())
    await page.reload()
    await expect(rows.nth(2).locator('.st')).toHaveText('Address saved')
    await rows.nth(0).getByRole('button', { name: 'Connect' }).click()
    await expect(page).toHaveURL(/#\/settings\/connections$/)
  })

  test('guide rows: one check row per PDF in a mixed search, five at most, and the checked ones guide it (D3)', async ({ page }) => {
    await page.goto(server.url())
    await expect(page.locator('.models-summary')).toContainText('fixture-model')
    await page.getByLabel('Source scope').click()
    await page.getByRole('option', { name: 'Files + academic search' }).click()
    const replacement = server.pdf('replacement'), hostile = server.pdf('hostile')
    await page.locator('input[type=file]').first().setInputFiles([replacement, hostile])
    const guide = page.getByRole('group', { name: 'PDFs guiding the search · their titles, abstracts and references shape the query.' })
    await expect(guide.getByRole('checkbox')).toHaveCount(2)
    await expect(guide.getByRole('radio')).toHaveCount(0)
    for (const box of await guide.getByRole('checkbox').all()) await expect(box).toBeChecked()
    await expect(page.locator('.attachment-chip', { hasText: 'guides the search' })).toHaveCount(2)
    // Unchecked: still attached and read as a source, but its chip no longer says it guides the search.
    await guide.getByRole('checkbox', { name: path.basename(hostile) }).uncheck()
    await expect(page.locator('.attachment-chip', { hasText: path.basename(hostile) })).not.toContainText('guides the search')
    await guide.getByRole('checkbox', { name: path.basename(replacement) }).uncheck()
    await expect(page.getByRole('button', { name: 'Start research' })).toBeDisabled()
    await guide.getByRole('checkbox', { name: path.basename(replacement) }).check()

    // The research is created, both PDFs attached, and only the checked one is sent as the search guide.
    await page.getByLabel('Research question').fill('SYNTHETIC comparison of molecular release schedules')
    const seeds = page.waitForRequest(r => r.method() === 'POST' && /\/api\/researches\/[^/]+\/seed$/.test(new URL(r.url()).pathname))
    // The uploads run one after the other, so their responses arrive in file order.
    const pending: Promise<string>[] = []
    page.on('response', response => {
      if (response.request().method() === 'POST' && /\/uploads$/.test(new URL(response.url()).pathname) && response.ok()) {
        pending.push(response.json().then(body => body.uploaded_source_version_id as string))
      }
    })
    await page.getByRole('button', { name: 'Start research' }).click()
    // Every eligible PDF less the unchecked upload: the backend keeps the choice of five (D3) and its records.
    const body = (await seeds).postDataJSON() as { source_version_ids?: string[]; all_eligible?: boolean; excluded_source_version_ids?: string[] }
    const uploads = await Promise.all(pending)
    expect(uploads).toHaveLength(2)
    expect(body).toMatchObject({ all_eligible: true, excluded_source_version_ids: [uploads[1]] })
    expect(body.source_version_ids).toBeUndefined()
  })

  test('guide rows: six PDFs all stay checked, the page says the backend keeps five, and no exclusion is sent', async ({ page }) => {
    await page.goto(server.url())
    await expect(page.locator('.models-summary')).toContainText('fixture-model')
    await page.getByLabel('Source scope').click()
    await page.getByRole('option', { name: 'Files + academic search' }).click()
    // Six readable SYNTHETIC PDFs: the fixture's replacement file, each copy made distinct by a trailing comment.
    const text = readFileSync(server.pdf('replacement'))
    await page.locator('input[type=file]').first().setInputFiles([1, 2, 3, 4, 5, 6].map(n =>
      ({ name: `SYNTHETIC-${n}.pdf`, mimeType: 'application/pdf', buffer: Buffer.concat([text, Buffer.from(`\n% copy ${n}\n`)]) })))
    const boxes = page.locator('.composer .guide input[type=checkbox]')
    await expect(boxes).toHaveCount(6)
    for (let n = 0; n < 6; n++) { await expect(boxes.nth(n)).toBeChecked(); await expect(boxes.nth(n)).toBeEnabled() }
    const limit = 'Up to five guide the search; DEIXIS keeps the five whose first pages share the most words with your question.'
    await expect(page.locator('.composer .guide')).toContainText(limit)
    await expect(page.locator('.attachment-chip', { hasText: 'may guide the search' })).toHaveCount(6)
    // The person's own uncheck brings it to five: the line goes and the chips say they guide the search.
    await boxes.nth(0).uncheck()
    await expect(page.locator('.composer .guide')).not.toContainText(limit)
    await expect(page.locator('.attachment-chip', { hasText: 'guides the search' })).toHaveCount(5)
    await boxes.nth(0).check()
    // Nothing unchecked: every eligible PDF is sent and the backend makes the cut.
    await page.getByLabel('Research question').fill('SYNTHETIC question with six guiding PDFs')
    const seeds = page.waitForRequest(r => r.method() === 'POST' && /\/api\/researches\/[^/]+\/seed$/.test(new URL(r.url()).pathname))
    await page.getByRole('button', { name: 'Start research' }).click()
    expect((await seeds).postDataJSON()).toEqual(expect.objectContaining({ all_eligible: true }))
    expect((await seeds).postDataJSON()).not.toHaveProperty('excluded_source_version_ids')
  })

  test('guide rows: an unchecked PDF stays unchecked when the other is removed, and the search cannot start unguided', async ({ page }) => {
    await page.goto(server.url())
    await expect(page.locator('.models-summary')).toContainText('fixture-model')
    await page.getByLabel('Source scope').click()
    await page.getByRole('option', { name: 'Files + academic search' }).click()
    await page.locator('input[type=file]').first().setInputFiles([tinyPdf('SYNTHETIC-A.pdf'), tinyPdf('SYNTHETIC-B.pdf')])
    await page.getByLabel('Research question').fill('SYNTHETIC question guided by one PDF')
    const guide = page.locator('.composer .guide')
    await guide.getByRole('checkbox', { name: 'SYNTHETIC-B.pdf' }).uncheck()
    await page.getByRole('button', { name: 'Remove SYNTHETIC-A.pdf' }).click()
    // One PDF left, still unchecked: its row stays so it can be checked again, and nothing guides the search.
    await expect(guide.getByRole('checkbox')).toHaveCount(1)
    await expect(guide.getByRole('checkbox', { name: 'SYNTHETIC-B.pdf' })).not.toBeChecked()
    await expect(guide.getByRole('status')).toHaveText('Choose at least one PDF to guide the search.')
    await expect(page.getByRole('button', { name: 'Start research' })).toBeDisabled()
    await expect(page.locator('.attachment-chip', { hasText: 'SYNTHETIC-B.pdf' })).not.toContainText('guides the search')
    // Checked again, the one PDF guides the search, as a single attached PDF always does; its row is no longer needed.
    await guide.getByRole('checkbox', { name: 'SYNTHETIC-B.pdf' }).click()
    await expect(page.locator('.composer .guide')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Start research' })).toBeEnabled()
  })

  test('two quick adds keep every file and its check mark', async ({ page }) => {
    await page.goto(server.url())
    await page.getByLabel('Source scope').click()
    await page.getByRole('option', { name: 'Files + academic search' }).click()
    const input = page.locator('input[type=file]').first()
    // The second change event fires while the first add is still reading its file headers.
    await Promise.all([input.setInputFiles([tinyPdf('SYNTHETIC-q1.pdf'), tinyPdf('SYNTHETIC-q2.pdf')]), input.setInputFiles(tinyPdf('SYNTHETIC-q3.pdf'))])
    await expect(page.locator('.attachment-chip')).toHaveCount(3)
    const boxes = page.locator('.composer .guide input[type=checkbox]')
    await expect(boxes).toHaveCount(3)
    for (let n = 0; n < 3; n++) await expect(boxes.nth(n)).toBeChecked()
  })
})
