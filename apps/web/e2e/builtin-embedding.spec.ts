import { expect, test, type Page } from '@playwright/test'
import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

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
const semanticSection = (page: Page) => page.locator('section.connections-group', { has: page.getByRole('heading', { name: 'Semantic search' }) })
const option = (page: Page, name: string) => semanticSection(page).locator('.semantic-option', { has: page.locator('strong', { hasText: name }) })

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
  const server = new BuiltinServer(8786)
  let page: Page

  test.beforeAll(async ({ browser }) => {
    await server.start()
    page = await browser.newPage()
  })
  test.afterAll(async () => { await page?.close(); await server.stop() })

  test('Settings lists Gemini, the built-in model, OpenAI, Ollama, LM Studio and Off, with Gemini’s free-key path', async () => {
    await openConnections(page, server)
    await expect(semanticSection(page).locator('.semantic-choice strong')).toHaveText([
      'Gemini', 'This computer · built-in', 'OpenAI', 'This computer · Ollama', 'This computer · LM Studio', 'Off · keyword search only'])
    const gemini = option(page, 'Gemini')
    await expect(gemini).toContainText('Reads the question in any language. Needs a Google AI Studio key; a free key works.')
    await expect(gemini).toContainText('Get a free key: sign in at aistudio.google.com/apikey, create a key, paste it under Cloud models → Gemini.')
    await expect(gemini.getByRole('link', { name: 'aistudio.google.com/apikey' })).toHaveAttribute('href', 'https://aistudio.google.com/apikey')
    await expect(semanticSection(page)).not.toContainText('Recommended')
    const builtin = option(page, 'This computer · built-in')
    await expect(builtin.getByRole('radio')).toBeDisabled()
    await expect(builtin).toContainText('Not downloaded')
    await expect(builtin).toContainText('For semantic search, no text leaves the computer')
    // The fixture's model files are SYNTHETIC and a few bytes long, but the sizes shown are the pinned model's.
    await expect(builtin).toContainText('Needs about 212 MB of disk (runtime about 145 MB installed, model 67 MB), plus about 74 MB if uv has to download Python 3.12, plus uv’s download cache (not measured).')
    await expect(builtin).toContainText('Measured on one Apple M1 Pro: 1,369 records took 51 seconds, 6,696 records about 4 minutes. Other computers were not measured.')
    await builtin.scrollIntoViewIfNeeded()
    await shot(page, 'N-settings-not-downloaded-desktop')
  })

  test('the download asks first with the disk size and the place, shows its steps, then the model is ready and can be chosen', async () => {
    const builtin = option(page, 'This computer · built-in')
    await builtin.getByRole('button', { name: 'Download' }).click()
    const dialog = page.getByRole('alertdialog').or(page.getByRole('dialog'))
    await expect(dialog).toContainText('Download the built-in model?')
    await expect(dialog).toContainText('It takes about 212 MB of disk in the DEIXIS data folder: the runtime (about 145 MB installed) and the model files (67 MB)')
    await expect(dialog).toContainText('The model is downloaded once, from Hugging Face. For semantic search, no text leaves the computer.')
    await expect(dialog).toContainText(path.basename(server.dataDir))
    await shot(page, 'N-download-confirmation-desktop')
    await dialog.getByRole('button', { name: 'Download' }).click()
    await expect(builtin).toContainText(/Step [1-4] of 4:/)
    await builtin.scrollIntoViewIfNeeded()
    await shot(page, 'N-download-progress-desktop')
    await expect(builtin.locator('.semantic-builtin .status-chip')).toContainText('Ready · files checked', { timeout: 60_000 })
    await expect(builtin).toContainText('Files checked at install and each time the model starts.')
    await builtin.getByRole('radio').check()
    await expect(semanticSection(page)).toContainText('For semantic search, no text leaves the computer.')
    await semanticSection(page).getByRole('button', { name: 'Save' }).click()
    await expect(page.getByText('Semantic search setting saved.')).toBeVisible()
    await builtin.scrollIntoViewIfNeeded()
    await shot(page, 'N-settings-ready-desktop')
    await page.setViewportSize({ width: 390, height: 844 })
    await builtin.scrollIntoViewIfNeeded()
    await shot(page, 'N-settings-ready-phone')
    await page.setViewportSize({ width: 1280, height: 900 })
  })

  test('a Turkish question asks for one English sentence in the Sources tab, and the line shows it once saved', async () => {
    await startResearch(page, server, TURKISH)
    await page.getByRole('tab', { name: /Sources/ }).click()
    const notice = page.locator('.english-question')
    await expect(notice).toContainText('The built-in semantic model reads English only. This question is not in English, so the built-in model is off for this research.')
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
    await expect(dialog).toContainText('Similarities it already stored stay and may still be used for the same question revision')
    await dialog.getByRole('button', { name: 'Remove' }).click()
    await expect(builtin).toContainText('Not downloaded')
  })
})

test.describe.serial('N: Gemini’s free tier and the uploaded-PDF line', () => {
  const server = new BuiltinServer(8787, true)
  let page: Page

  test.beforeAll(async ({ browser }) => {
    await server.start()
    page = await browser.newPage()
  })
  test.afterAll(async () => { await page?.close(); await server.stop() })

  test('choosing Gemini says the free tier may use the text and that DEIXIS cannot tell the tier', async () => {
    await openConnections(page, server)
    const gemini = option(page, 'Gemini')
    await expect(gemini).not.toContainText('Get a free key')
    await gemini.getByRole('radio').check()
    await expect(semanticSection(page)).toContainText('Passage text is sent to Google. If your key is on Google’s free tier, Google may use the text you send to improve its products. DEIXIS cannot tell which tier your key is on.')
    await semanticSection(page).getByRole('button', { name: 'Save' }).click()
    await expect(page.getByText('Semantic search setting saved.')).toBeVisible()
    await semanticSection(page).getByRole('button', { name: 'Save' }).scrollIntoViewIfNeeded()
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
  const server = new BuiltinServer(8779, true)
  let page: Page

  test.beforeAll(async ({ browser }) => {
    await server.start()
    page = await browser.newPage()
  })
  test.afterAll(async () => { await page?.close(); await server.stop() })

  test('the semantic line of a failed step keeps the uploaded-PDF line (Sol r4, finding 3)', async () => {
    await openConnections(page, server)
    await option(page, 'Gemini').getByRole('radio').check()
    await semanticSection(page).getByRole('button', { name: 'Save' }).click()
    await expect(page.getByText('Semantic search setting saved.')).toBeVisible()
    await startResearch(page, server, 'SYNTHETIC [embed-fails] comparison of molecular release schedules', 'Files + academic search')
    await expect(page.getByText('Ran search & screening')).toBeVisible({ timeout: 60_000 })
    await page.getByRole('button', { name: 'Generate answer now' }).click()
    await expect(page.getByText('Ran answer generation')).toBeVisible({ timeout: 60_000 })
    await page.getByRole('button', { name: /Ran answer generation/ }).click()
    const line = page.getByText(/Unavailable · continued with keyword search/)
    await expect(line).toContainText('went in a request that brought no vectors back; whether Google received')
    await line.scrollIntoViewIfNeeded()
    await shot(page, 'N-failed-ranking-upload-line-desktop')
  })
})
