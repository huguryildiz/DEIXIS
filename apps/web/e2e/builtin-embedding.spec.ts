import { expect, test, type Page } from '@playwright/test'
import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'
import { openPanel } from './panels'

// Case N: the built-in embedding model in Settings (slice 21). Order of the choices, the download confirmation with
// disk sizes, the install's steps, ready with the file check, choosing it; Gemini's free-key path and free-tier
// sentence; a Turkish question's English sentence in the Sources tab; the conditional uploaded-PDF line under the
// answer button while Gemini ranks passages.
//
// Its own fixture server with DEIXIS_FIXTURE_BUILTIN_EMBEDDING=fake: a fake uv, SYNTHETIC model files and a fake
// runner. Nothing is downloaded and no model runs, so a passing case shows the interface and its states, not the model.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

const TURKISH = 'Kablosuz algılayıcı ağlarında paket boyutunun enerji tüketimine etkisi nedir?'
const SENTENCE = 'The effect of packet size on energy consumption in wireless sensor networks.'

class BuiltinServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-builtin-'))
  constructor(readonly port: number, readonly geminiKey = false) {}

  private env() {  // no real provider keys or user data directory reach the fixture
    return {
      PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend'),
      DEIXIS_FIXTURE_BUILTIN_EMBEDDING: 'fake', ...(this.geminiKey ? { GEMINI_API_KEY: 'SYNTHETIC-key' } : {}),
    }
  }

  async start() {
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env: this.env(), stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`http://127.0.0.1:${this.port}/api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`built-in embedding fixture server on ${this.port} did not start`)
  }

  async stop() {
    const proc = this.proc
    if (!proc || proc.exitCode !== null) return
    const exited = new Promise(resolve => proc.once('exit', resolve))
    proc.kill('SIGTERM')
    await exited
  }

  replacementPdf() {
    const file = path.join(this.dataDir, '..', `builtin-upload-${this.port}.pdf`)
    spawnSync(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', '0', '--write-replacement-pdf', file], { cwd: REPO, env: this.env() })
    return file
  }

  url(hash = '') { return `http://127.0.0.1:${this.port}/${hash}` }
}

const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`), animations: 'disabled' })
// The semantic choices are model-style cards (Local models, API models, Off); a card opens a sheet that holds its details
// and the button that chooses it.
const semanticSection = (page: Page) => page.locator('div.choice-groups[data-group="semantic"]')
const card = (page: Page, name: string) => semanticSection(page).locator('.co-card').filter({ has: page.locator('.co-name b', { hasText: new RegExp(`^${name}$`) }) })
const sheetOf = (page: Page, name: string) => page.getByRole('dialog', { name, exact: true })
async function openSheet(page: Page, name: string) {
  await card(page, name).click()
  const sheet = sheetOf(page, name)
  await expect(sheet).toBeVisible()
  return sheet
}
async function closeSheet(page: Page, name: string) {
  await page.keyboard.press('Escape')
  await expect(sheetOf(page, name)).toHaveCount(0)
}
const privacyNote = (page: Page) => page.locator('.semantic-privacy')

async function openConnections(page: Page, server: BuiltinServer) {
  await page.goto(server.url('#/settings/search'))
  await expect(semanticSection(page)).toBeVisible()
}

async function startResearch(page: Page, server: BuiltinServer, question: string, scope?: string) {
  await page.goto(server.url())
  await page.getByLabel('Research question').fill(question)
  if (scope) {
    await page.getByLabel('Source scope').click()
    await page.getByRole('option', { name: scope }).click()
    await page.locator('input[type=file]').first().setInputFiles(server.replacementPdf())
    await expect(page.getByLabel('PDFs to attach')).toContainText('builtin-upload-')
  }
  await expect(page.locator('.models-summary')).toContainText('fixture-model')
  await page.getByRole('button', { name: 'Start research' }).click()
  await page.waitForURL(/#\/research\//)
}

test.describe.serial('N: the built-in embedding model', () => {
  const server = new BuiltinServer(nextPort())
  let page: Page

  test.beforeAll(async ({ browser }) => {
    await server.start()
    page = await browser.newPage()
  })
  test.afterAll(async () => { await page?.close(); await server.stop() })

  test('Settings lists the built-in model, Gemini, OpenAI, Voyage AI and Off as cards (a local model server only when saved), with Gemini’s key section and link in its sheet', async () => {
    await openConnections(page, server)
    await expect(semanticSection(page).locator('.choice-head')).toHaveText(['Local models', 'API models'])
    await expect(semanticSection(page).locator('.co-card .co-name b')).toHaveText([
      'This computer · built-in', 'Gemini embeddings', 'OpenAI embeddings', 'Voyage AI embeddings', 'Cohere embeddings', 'Off'])
    await expect(semanticSection(page)).not.toContainText('Recommended')
    // A card that cannot be chosen says what it needs, from the options' own state (no key set in this fixture).
    await expect(card(page, 'This computer · built-in').locator('.st')).toHaveText('Not downloaded')
    await expect(card(page, 'Gemini embeddings').locator('.st')).toHaveText('Needs a Google AI key')
    await expect(card(page, 'OpenAI embeddings').locator('.st')).toHaveText('Needs an OpenAI key')
    await expect(card(page, 'Voyage AI embeddings').locator('.st')).toHaveText('Needs a Voyage AI key')
    await expect(card(page, 'Cohere embeddings').locator('.st')).toHaveText('Needs a Cohere key')
    await expect(card(page, 'Off').locator('.st')).toHaveText('In use')
    // Reranking: built-in under Local models; the API rerankers in order, each saying a key is needed; Off last.
    const rerank = page.locator('div.choice-groups[data-group="reranking"]')
    await expect(rerank.locator('.co-card .co-name b')).toHaveText([
      'This computer · built-in', 'Voyage AI reranker', 'Cohere reranker', 'Jina AI reranker', 'ZeroEntropy reranker', 'Off'])
    for (const name of ['Voyage AI reranker', 'Cohere reranker', 'Jina AI reranker', 'ZeroEntropy reranker'])
      await expect(rerank.locator('.co-card').filter({ has: page.locator('.co-name b', { hasText: new RegExp(`^${name}$`) }) }).locator('.st')).toHaveText('Key needed')
    await expect(card(page, 'Off')).toHaveClass(/\bon\b/)
    await shot(page, 'N-settings-not-downloaded-desktop')
    const gemini = await openSheet(page, 'Gemini embeddings')
    await expect(gemini).toContainText('Reads the question in any language. Needs a Google AI Studio key; a free key works.')
    const key = gemini.locator('section.way[aria-label="With an API key"]')
    await expect(key).toContainText('No key entered')
    await expect(key.getByRole('link', { name: 'aistudio.google.com/apikey' })).toHaveAttribute('href', 'https://aistudio.google.com/apikey')
    await expect(gemini.getByRole('button', { name: 'Use for semantic search' })).toBeDisabled()
    await closeSheet(page, 'Gemini embeddings')
    const builtin = await openSheet(page, 'This computer · built-in')
    await expect(builtin.getByRole('button', { name: 'Use for semantic search' })).toBeDisabled()
    // The fixture's model files are SYNTHETIC and a few bytes long, but the sizes shown are the pinned model's.
    await expect(builtin).toContainText(/Needs about \d+ MB of disk, plus about 74 MB if Python 3\.12 has to be downloaded, plus room for a download cache\./)
    await shot(page, 'N-settings-not-downloaded-sheet-desktop')
    await closeSheet(page, 'This computer · built-in')
  })

  test('the download asks first with the disk size and the place, shows its steps, then the model is ready and can be chosen', async () => {
    const builtin = await openSheet(page, 'This computer · built-in')
    await builtin.getByRole('button', { name: 'Download', exact: true }).click()
    const dialog = page.getByRole('alertdialog').or(page.getByRole('dialog')).filter({ hasText: 'Download the built-in model?' })
    await expect(dialog).toContainText('Download the built-in model?')
    await expect(dialog).toContainText(/The model is downloaded once from Hugging Face and takes about \d+ MB in the DEIXIS data folder, plus about 74 MB if Python 3\.12 has to be downloaded\./)
    await expect(dialog).toContainText('After that, semantic search sends no text off this computer.')
    await expect(dialog).toContainText(path.basename(server.dataDir))
    await shot(page, 'N-download-confirmation-desktop')
    await dialog.getByRole('button', { name: 'Download', exact: true }).click()
    await expect(builtin).toContainText(/Step [1-4] of 4:/)
    await shot(page, 'N-download-progress-desktop')
    const files = builtin.locator('section.semantic-builtin[aria-label="Model files"]')
    await expect(files.locator('.way-head')).toContainText('Ready', { timeout: 60_000 })
    await expect(files).toContainText(/Files checked .+, at install and each time the model starts\./)
    // A choice is saved at once; the note under the rows follows the saved setting.
    // A ready built-in model can be the default with nothing saved yet; the sheet button saves it.
    await builtin.getByRole('button', { name: 'Use for semantic search' }).click()
    await expect(page.getByText('Semantic search setting saved.')).toBeVisible()
    await expect(builtin.getByRole('button', { name: 'Use for semantic search' })).toHaveCount(0)
    await closeSheet(page, 'This computer · built-in')
    await expect(privacyNote(page)).toHaveText('For semantic search, no text leaves the computer.')
    await expect(card(page, 'This computer · built-in').locator('.st')).toHaveText('In use')
    await expect(card(page, 'This computer · built-in')).toHaveClass(/\bon\b/)
    await card(page, 'This computer · built-in').scrollIntoViewIfNeeded()
    await shot(page, 'N-settings-ready-desktop')
    await page.setViewportSize({ width: 390, height: 844 })
    await card(page, 'This computer · built-in').scrollIntoViewIfNeeded()
    await shot(page, 'N-settings-ready-phone')
    await page.setViewportSize({ width: 1280, height: 900 })
  })

  test('a Turkish question asks for one English sentence in the Sources panel, and the line shows it once saved', async () => {
    await startResearch(page, server, TURKISH)
    await openPanel(page, 'sources')
    const notice = page.locator('.english-question')
    await expect(notice).toContainText('The built-in model reads English only, so it is off for this research.')
    await expect(notice.getByRole('button', { name: 'The question is already in English' })).toBeVisible()
    await shot(page, 'N-english-sentence-form-desktop')
    await page.setViewportSize({ width: 390, height: 844 })
    await notice.scrollIntoViewIfNeeded()
    await shot(page, 'N-english-sentence-form-phone')
    await page.setViewportSize({ width: 1280, height: 900 })
    await page.getByLabel('English sentence for the built-in model').fill(SENTENCE)
    await notice.getByRole('button', { name: 'Save' }).click()
    await expect(page.locator('.english-question-line')).toHaveText(`Built-in model uses: ${SENTENCE}`)
    await expect(page.locator('.english-question')).toHaveCount(0)
    await shot(page, 'N-english-sentence-saved-desktop')
  })

  test('removing the model is confirmed and leaves it not downloaded', async () => {
    await openConnections(page, server)
    const builtin = await openSheet(page, 'This computer · built-in')
    await builtin.getByRole('button', { name: 'Remove', exact: true }).click()
    const dialog = page.getByRole('alertdialog').or(page.getByRole('dialog')).filter({ hasText: 'Scores it already gave are kept' })
    await expect(dialog).toContainText('Scores it already gave are kept; sources not yet scored are ranked without it until you download it again.')
    await dialog.getByRole('button', { name: 'Remove', exact: true }).click()
    await expect(builtin).toContainText('Not downloaded')
    await closeSheet(page, 'This computer · built-in')
    await expect(card(page, 'This computer · built-in').locator('.st')).toHaveText('Not downloaded')
  })
})

test.describe.serial('N: Gemini’s free tier and the uploaded-PDF line', () => {
  const server = new BuiltinServer(nextPort(), true)
  let page: Page

  test.beforeAll(async ({ browser }) => {
    await server.start()
    page = await browser.newPage()
  })
  test.afterAll(async () => { await page?.close(); await server.stop() })

  test('choosing Gemini says the free tier may use the text and that DEIXIS cannot tell the tier', async () => {
    await openConnections(page, server)
    // Gemini is the default with a Google key and nothing saved yet; choosing it in its sheet saves it.
    await expect(card(page, 'Gemini embeddings').locator('.st')).toHaveText('In use')
    await expect(card(page, 'Gemini embeddings')).toHaveClass(/\bon\b/)
    const gemini = await openSheet(page, 'Gemini embeddings')
    await expect(gemini.locator('section.way[aria-label="With an API key"]')).toContainText('Ready')
    await gemini.getByRole('button', { name: 'Use for semantic search' }).click()
    await expect(page.getByText('Semantic search setting saved.')).toBeVisible()
    await closeSheet(page, 'Gemini embeddings')
    await expect(privacyNote(page)).toHaveText('Passage text is sent to Google. If your key is on Google’s free tier, which DEIXIS cannot detect, Google may use that text to improve its products.')
    await privacyNote(page).scrollIntoViewIfNeeded()
    await shot(page, 'N-gemini-free-tier-desktop')
  })

  test('under the answer button a research with an uploaded PDF reads the conditional line, with no count', async () => {
    await startResearch(page, server, 'SYNTHETIC comparison of molecular release schedules', 'Files + academic search')
    await expect(page.getByText('Ran search & screening')).toBeVisible({ timeout: 60_000 })
    const note = page.locator('.semantic-upload-note').first()
    await expect(note).toHaveText('If the included sources have PDFs you uploaded, their text is sent to Google to rank passages. On Google’s free tier, Google may use it to improve its products.')
    await note.scrollIntoViewIfNeeded()
    await shot(page, 'N-uploaded-pdf-line-desktop')
    await page.setViewportSize({ width: 390, height: 844 })
    await note.scrollIntoViewIfNeeded()
    await shot(page, 'N-uploaded-pdf-line-phone')
  })
})

test.describe.serial('N: a failed passage ranking still says where uploaded text went', () => {
  const server = new BuiltinServer(nextPort(), true)
  let page: Page

  test.beforeAll(async ({ browser }) => {
    await server.start()
    page = await browser.newPage()
  })
  test.afterAll(async () => { await page?.close(); await server.stop() })

  test('the semantic line of a failed step keeps the uploaded-PDF line (Sol r4, finding 3)', async () => {
    await openConnections(page, server)
    const gemini = await openSheet(page, 'Gemini embeddings')
    await gemini.getByRole('button', { name: 'Use for semantic search' }).click()
    await expect(page.getByText('Semantic search setting saved.')).toBeVisible()
    await closeSheet(page, 'Gemini embeddings')
    // The fast path's own answer ranks passages by keyword alone (fast_path_lexical). The answer of an attached-files
    // research still ranks the attached PDF's passages by meaning, so a failed ranking is shown there.
    await startResearch(page, server, 'SYNTHETIC [embed-fails] comparison of molecular release schedules', 'Attached files')
    await page.getByRole('button', { name: 'Generate source-linked answer' }).click()
    await expect(page.getByText('Ran answer generation')).toBeVisible({ timeout: 60_000 })
    // The latest answer's steps stay open (S9), so the ranking line is in view without a click.
    await expect(page.getByRole('button', { name: /Ran answer generation/ })).toHaveAttribute('aria-expanded', 'true')
    const line = page.getByText(/Unavailable · continued with keyword search/)
    await expect(line).toContainText('went in a request that brought no vectors back; whether Google received')
    await line.scrollIntoViewIfNeeded()
    await shot(page, 'N-failed-ranking-upload-line-desktop')
  })
})
