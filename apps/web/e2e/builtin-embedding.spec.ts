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
// The Settings page is one column since S24: the semantic choices are one radio group, each row named by its label.
const semanticSection = (page: Page) => page.getByRole('radiogroup', { name: 'Semantic search provider' })
const ROWS: Record<string, string> = { 'This computer · built-in': 'builtin', 'OpenAI embeddings': 'openai', 'Gemini embeddings': 'gemini', 'Local model server': 'server', Off: 'off' }
const option = (page: Page, name: string) => semanticSection(page).locator(`.semantic-option[data-row="${ROWS[name]}"]`)
const privacyNote = (page: Page) => page.locator('.semantic-privacy')

async function openConnections(page: Page, server: BuiltinServer) {
  await page.goto(server.url('#/settings/connections'))
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

  test('Settings lists Gemini, the built-in model, OpenAI, a local model server and Off (the order embeddings.chosen picks a default in), with Gemini’s free-key path', async () => {
    await openConnections(page, server)
    await expect(semanticSection(page).locator('.semantic-option > label > span:not(.st):not(.spin):not(.connection-icon)')).toHaveText([
      /^Gemini embeddings/, /^This computer · built-in/, /^OpenAI embeddings/, /^Local model server/, /^Off/])
    const gemini = option(page, 'Gemini embeddings')
    await expect(gemini).toContainText('Reads the question in any language. Needs a Google AI Studio key; a free key works.')
    await expect(gemini).toContainText('Get a free key: sign in at aistudio.google.com/apikey, create a key, paste it under Model connections → Gemini.')
    await expect(gemini.getByRole('link', { name: 'aistudio.google.com/apikey' })).toHaveAttribute('href', 'https://aistudio.google.com/apikey')
    await expect(semanticSection(page)).not.toContainText('Recommended')
    const builtin = option(page, 'This computer · built-in')
    await expect(builtin.getByRole('radio')).toBeDisabled()
    await expect(builtin.locator('label .st')).toHaveText('Not downloaded')
    // A row that cannot be chosen says what it needs, from the options' own state (no key set in this fixture).
    await expect(option(page, 'Gemini embeddings').locator('label .st')).toHaveText('Needs a Google AI key')
    await expect(option(page, 'OpenAI embeddings').locator('label .st')).toHaveText('Needs an OpenAI key')
    await expect(option(page, 'Off').locator('label .st')).toHaveCount(0)
    // The fixture's model files are SYNTHETIC and a few bytes long, but the sizes shown are the pinned model's.
    await expect(builtin).toContainText('Needs about 212 MB of disk, plus about 74 MB if Python 3.12 has to be downloaded, plus room for a download cache.')
    await builtin.scrollIntoViewIfNeeded()
    await shot(page, 'N-settings-not-downloaded-desktop')
  })

  test('the download asks first with the disk size and the place, shows its steps, then the model is ready and can be chosen', async () => {
    const builtin = option(page, 'This computer · built-in')
    await builtin.getByRole('button', { name: 'Download' }).click()
    const dialog = page.getByRole('alertdialog').or(page.getByRole('dialog'))
    await expect(dialog).toContainText('Download the built-in model?')
    await expect(dialog).toContainText('The model is downloaded once from Hugging Face and takes about 212 MB in the DEIXIS data folder, plus about 74 MB if Python 3.12 has to be downloaded.')
    await expect(dialog).toContainText('After that, semantic search sends no text off this computer.')
    await expect(dialog).toContainText(path.basename(server.dataDir))
    await shot(page, 'N-download-confirmation-desktop')
    await dialog.getByRole('button', { name: 'Download' }).click()
    await expect(builtin).toContainText(/Step [1-4] of 4:/)
    await builtin.scrollIntoViewIfNeeded()
    await shot(page, 'N-download-progress-desktop')
    await expect(builtin.locator('.semantic-builtin .status-chip')).toContainText('Ready · files checked', { timeout: 60_000 })
    await expect(builtin).toContainText('Files checked at install and each time the model starts.')
    // A choice is saved at once; the note under the rows follows the saved setting.
    // A ready built-in model can be the default with nothing saved yet; click (check() skips a checked radio) saves it.
    await builtin.getByRole('radio').click()
    await expect(builtin.getByRole('radio')).toBeChecked()
    await expect(page.getByText('Semantic search setting saved.')).toBeVisible()
    await expect(privacyNote(page)).toHaveText('For semantic search, no text leaves the computer.')
    await expect(builtin.locator('label .st')).toHaveCount(0)
    await builtin.scrollIntoViewIfNeeded()
    await shot(page, 'N-settings-ready-desktop')
    await page.setViewportSize({ width: 390, height: 844 })
    await builtin.scrollIntoViewIfNeeded()
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
    const builtin = option(page, 'This computer · built-in')
    await builtin.getByRole('button', { name: 'Remove' }).click()
    const dialog = page.getByRole('alertdialog').or(page.getByRole('dialog'))
    await expect(dialog).toContainText('Scores it already gave are kept; sources not yet scored are ranked without it until you download it again.')
    await dialog.getByRole('button', { name: 'Remove' }).click()
    await expect(builtin).toContainText('Not downloaded')
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
    const gemini = option(page, 'Gemini embeddings')
    await expect(gemini).not.toContainText('Get a free key')
    await expect(gemini.locator('label .st')).toHaveCount(0)
    // Gemini is the default with a Google key and nothing saved yet; choosing it saves it (check() would skip a checked radio).
    await expect(gemini.getByRole('radio')).toBeChecked()
    await gemini.getByRole('radio').click()
    await expect(page.getByText('Semantic search setting saved.')).toBeVisible()
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
    await option(page, 'Gemini embeddings').getByRole('radio').click()
    await expect(page.getByText('Semantic search setting saved.')).toBeVisible()
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
