import { expect, request as apiRequest, test, type APIRequestContext, type Page } from '@playwright/test'
import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import { appendFileSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'
import { openPanel, panel, reportPanel, sourcePanel } from './panels'

// UI parity S12: the report panel (P2, P3), the Citation panel (P11) and Source details (P12-P20). The research is the
// fixture's SYNTHETIC [parity] research with two answer versions. Every count and label the cases expect is computed
// here from the stored answer and sources the API returns, not from the page's code. One case adds a claim review to
// the view the page receives (the fixture has no reviewer model), and says so; the rest read stored records.
// A passing case shows how the panels behave, not the quality of a search or an answer.

const REPO = path.resolve(process.cwd(), '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

const PARITY = '[parity] How has the relationship between k-connectivity, network lifetime and energy consumption been modeled in SYNTHETIC wireless sensor networks?'

class PanelServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-panels-'))
  constructor(readonly port: number) {}
  async start() {
    const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: REPO, DEIXIS_FIXTURE_FULLTEXT: 'on' }
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`http://127.0.0.1:${this.port}/api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`panel fixture server on ${this.port} did not start`)
  }
  async stop() {
    const proc = this.proc
    if (proc && proc.exitCode === null) {
      const exited = new Promise(resolve => proc.once('exit', resolve))
      proc.kill('SIGTERM')
      await exited
    }
    rmSync(this.dataDir, { recursive: true, force: true })
  }
  url() { return `http://127.0.0.1:${this.port}` }
  // A SYNTHETIC one-page PDF from the fixture server ("SYNTHETIC replacement scan: …"), for Replace PDF (D45).
  replacementPdf(name: string) {
    const file = path.join(this.dataDir, '..', `${name}-${this.port}.pdf`)
    const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: REPO }
    spawnSync(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', '0', '--write-replacement-pdf', file], { cwd: REPO, env })
    // A trailing comment after %%EOF makes each file's bytes differ (the backend refuses the file already in use).
    appendFileSync(file, `\n%SYNTHETIC ${name}\n`)
    return file
  }
}

type Evidence = {
  passage_id: string; source_version_id: string; work_id: string; source_key: string | null; kind: string; anchor_text: string | null
  physical_page: number | null; printed_label: string | null; version_label: string | null; rendition?: boolean; title: string; evidence_status: string
}
type Claim = { id: string; section: string | null; text: string; support_type: string; evidence_basis?: string | null; evidence: Evidence[]; review: { verdict: string; reason: string } | null }
type Answer = { id: string; status: string; report_version: number | null; created_at: string; claims: Claim[]; unanswered_aspects: string[] }
type Discovery = { provider: string; status: string; http_status: number | null; error_code: string | null }
type Source = {
  source_version_id: string; work_id: string; title: string; doi: string | null; version_label: string | null; version_role: string
  selection: { state: string; origin: string }; similarity: number | null; provider_records: string[]
  access: { abstract_passage_id: string | null; assets: { id: string; page_count: number | null; rendition?: boolean }[]; pdf_discoveries: Discovery[] }
}
type View = { runs: Array<{ kind: string; status: string }>; answers: Answer[]; sources: Source[] }
type Api = { context: APIRequestContext; token: string }
const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
const post = (api: Api, url: string, data: unknown, headers: Record<string, string> = {}) => api.context.post(url, { data, headers: { 'x-deixis-csrf': api.token, ...headers } })
const viewOf = async (api: Api, rid: string) => (await (await api.context.get(`/api/researches/${rid}`)).json()) as View
const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`), animations: 'disabled' })
const squash = (text: string) => text.replace(/\s+/g, ' ').trim()
const visit = async (page: Page, url: string) => { await page.goto('about:blank'); await page.goto(url) }
const settled = async (api: Api, rid: string, check: (view: View) => boolean) => expect.poll(async () => {
  const view = await viewOf(api, rid)
  return check(view) && !view.runs.some(r => ACTIVE.has(r.status))
}, { timeout: 110_000, intervals: [500] }).toBe(true)
const valid = (view: View) => view.answers.filter(a => a.status === 'structurally_valid')
const locator = (e: Evidence) => e.kind === 'abstract' ? 'Abstract' : e.physical_page ? `PDF p. ${e.physical_page}` : 'Section'
const VERSIONS: Record<string, string> = { publishedVersion: 'published version', acceptedVersion: 'accepted manuscript', submittedVersion: 'submitted manuscript' }
const versionText = (label: string | null) => (label ? VERSIONS[label] ?? label : 'version not stated')
// A lookup recorded without a request (a missing key or contact setting, the closed OpenAlex budget), as the backend's
// acquisition.py writes it; computed here from the stored rows, not from the page's code.
const NOT_SENT_CODES = ['missing_contact_email', 'missing_core_key', 'missing_serpapi_key']
const notSent = (d: Discovery) => NOT_SENT_CODES.includes(d.error_code ?? '') || (d.error_code === 'quota_exhausted' && d.http_status === null)
const listed = (names: string[]) => (names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : names[0])
const PROVIDERS: Record<string, string> = { unpaywall: 'Unpaywall', openalex: 'OpenAlex', crossref: 'Crossref', core: 'CORE', europepmc: 'Europe PMC', web_search: 'Web Search' }

// The cases share one research; each still runs when an earlier one fails, so one run shows every failure.
test.describe('S12: report, Citation and Source details panels', () => {
  test.setTimeout(240_000)
  const server = new PanelServer(nextPort())
  let api: Api
  let rid = ''
  let page: Page
  const research = () => `${server.url()}/#/research/${rid}`

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(240_000)
    await server.start()
    const context = await apiRequest.newContext({ baseURL: server.url(), extraHTTPHeaders: { origin: server.url() } })
    api = { context, token: (await (await context.get('/api/session')).json()).csrf_token as string }
    const created = await post(api, '/api/researches', { question: PARITY, model_connection: 'codex', requested_model: 'fixture-model', effort: 'standard', source_scope: 'academic' })
    expect(created.status()).toBe(201)
    rid = (await created.json()).research.id as string
    expect((await post(api, `/api/researches/${rid}/runs`, { kind: 'discovery' }, { 'Idempotency-Key': `panels-discovery-${rid}` })).ok()).toBe(true)
    await settled(api, rid, view => valid(view).length === 1)
    // Two more answers give the report three versions (V1, V2, V3), as a person's "Generate a new answer" does.
    for (const n of [2, 3]) {
      expect((await post(api, `/api/researches/${rid}/runs`, { kind: 'answer' }, { 'Idempotency-Key': `panels-answer-${n}-${rid}` })).ok()).toBe(true)
      await settled(api, rid, view => valid(view).length === n)
    }
    page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  })
  test.afterAll(async () => { await page?.close(); await api?.context.dispose(); await server.stop() })

  test('the report panel: its head, its meta line, numbered sections, claim badges and the check line', async () => {
    const view = await viewOf(api, rid)
    const [latest] = [...valid(view)].sort((a, b) => (b.report_version ?? 0) - (a.report_version ?? 0))
    expect(valid(view).map(a => a.report_version).sort()).toEqual([1, 2, 3])
    // PATCHED VIEW: the fixture has no reviewer model, so one claim review (SYNTHETIC) is added to the view the page
    // receives, to show the verdict badge and its count. Nothing is stored.
    const reviewed = latest.claims.find(c => c.evidence.length)!
    await page.route(`**/api/researches/${rid}`, async route => {
      const response = await route.fetch()
      const body = await response.json() as View
      for (const answer of body.answers) for (const claim of answer.claims) if (claim.id === reviewed.id) claim.review = { verdict: 'supported', reason: 'SYNTHETIC review reason.' }
      await route.fulfill({ response, json: body })
    })
    try {
      await visit(page, research())
      await page.locator('#research-answer').click()
      const report = reportPanel(page)
      await expect(report).toBeVisible()
      // P2: Version, Show changes (S21, P4), Citation style, Review with another model and Download, in the mockup's order.
      const head = report.locator('.split-panel-actions .report-toolbar-actions > :not(input)')
      await expect(head).toHaveCount(5)
      expect(await head.evaluateAll(els => els.map(el => el.getAttribute('aria-label') ?? el.textContent)))
        .toEqual(['Version', 'Show changes', 'Citation style', 'Review with another model', 'Download report'])
      await expect(report.getByRole('combobox', { name: 'Version' })).toHaveText(/^V3/)
      // P3: the serif title and one meta line from the answer's record: version, date, cited works, the reviews' count.
      const cited = new Set(latest.claims.flatMap(c => c.evidence.map(e => e.work_id))).size
      const meta = report.locator('.report-document-head .meta')
      // The separators are drawn by the layout, so the text is read with one space around each.
      expect(squash((await meta.textContent())!.replace(/\s*·\s*/g, ' · '))).toBe(`Report · V3 · ${new Date(latest.created_at).toLocaleDateString('en', { dateStyle: 'long' })} · ${cited} sources1 supported`)
      await expect(meta.locator('.badge-s.v-ok')).toHaveText('1 supported')
      expect(await report.locator('.report-document-head h1').evaluate(el => getComputedStyle(el).fontFamily)).toMatch(/Source Serif/)
      // Sections: one numbered heading per headed section, in the answer's order.
      const sections: string[] = []
      latest.claims.forEach(c => { if (c.section && sections[sections.length - 1] !== c.section) sections.push(c.section) })
      await expect(report.locator('.report-content .answer-section > h2')).toHaveText(sections.map((s, i) => `${i + 1}. ${s}`))
      const h2 = report.locator('.report-content > h2')
      if (latest.unanswered_aspects.length) {
        await expect(h2.filter({ hasText: 'Not answered by the inspected passages' })).toHaveCount(1)
        await expect(report.locator('.report-content > p.gap')).toHaveCount(latest.unanswered_aspects.length)
      }
      await expect(h2.last()).toHaveText('Cited passages')
      // Each claim's badges: its review, an interpretation, and the depth of what it cites, as the record says.
      const claims = report.locator('.report-content .answer-section .claim')
      await expect(claims).toHaveCount(latest.claims.length)
      for (const [i, claim] of latest.claims.entries()) {
        const row = claims.nth(i)
        const basis = claim.evidence_basis
        await expect(row.locator('.badge-s.v-abs')).toHaveCount(basis === 'abstract' || basis === 'mixed' ? 1 : 0)
        await expect(row.locator('.badge-s.v-full')).toHaveCount(basis === 'full_text' || basis === 'mixed' ? 1 : 0)
        await expect(row.locator('.badge-s.support-badge.v-part')).toHaveCount(claim.support_type === 'analyst_inference' ? 1 : 0)
        await expect(row.locator('.review-badge')).toHaveText(claim.id === reviewed.id ? ['supported'] : [])
      }
      expect(latest.claims.some(c => c.evidence_basis === 'abstract' || c.evidence_basis === 'mixed')).toBe(true)
      expect(latest.claims.some(c => c.evidence_basis === 'full_text' || c.evidence_basis === 'mixed')).toBe(true)
      // The check line carries the bibliography files of this answer's cited sources.
      const check = report.locator('.report-content .check')
      await expect(check).toContainText('Structural check passed: each citation resolves to a stored passage that was given to this step.')
      await expect(check.getByRole('link', { name: '.bib' })).toHaveAttribute('href', new RegExp(`format=bibtex&sources=cited&answer_id=${latest.id}$`))
      await expect(check.getByRole('link', { name: '.ris' })).toHaveAttribute('href', new RegExp(`format=ris&sources=cited&answer_id=${latest.id}$`))
      // Download: Markdown, PDF (the print dialog, S27), Word, and Copy (live, kept with the files).
      await report.getByRole('button', { name: 'Download report' }).click()
      const rows = page.locator('.report-export-menu .research-export-item')
      await expect(rows.locator('b')).toHaveText(['MD', 'PDF', 'DOCX', 'Copy'])
      await expect(rows.locator('span:not([aria-hidden])').filter({ hasText: /\w/ }).last()).toHaveText('Markdown to the clipboard')
      await expect(rows.nth(2)).toHaveAttribute('href', new RegExp(`/answers/${latest.id}/export/docx\\?lang=en&style=apa$`))
      await page.keyboard.press('Escape')
      // Review with another model opens the request dialog over the panel (UI parity S15b, P32); Escape closes only the dialog.
      const review = report.locator('.split-panel-actions').getByRole('button', { name: 'Review with another model' })
      await review.click()
      await expect(page.locator('.review-dialog .review-request')).toBeVisible()
      await page.keyboard.press('Escape')
      await expect(page.locator('.review-dialog')).toHaveCount(0)
      await expect(report).toBeVisible()
      await shot(page, 's12-report-panel')
      await page.keyboard.press('Escape')
      await expect(page.locator('[data-split-panel]')).toHaveCount(0)
    } finally { await page.unrouteAll({ behavior: 'ignoreErrors' }) }
  })

  test('the version select shows each of three versions in the same panel, and Back returns to the version shown', async () => {
    const view = await viewOf(api, rid)
    const byVersion = new Map(valid(view).map(a => [a.report_version!, a]))
    await visit(page, research())
    await page.locator('#research-answer').click()
    const head = page.locator('[data-split-panel] .split-panel-head')
    const meta = () => reportPanel(page).locator('.report-document-head .meta > span').first()
    // One stack entry throughout: no Back button, the report's title stays, the panel never closes.
    const shows = async (v: number) => {
      await expect(meta()).toHaveText(`Report · V${v}${v < 3 ? ' (earlier version)' : ''}`)
      await expect(reportPanel(page).getByRole('combobox', { name: 'Version' })).toHaveText(new RegExp(`^V${v}`))
      await expect(head.getByRole('button', { name: 'Back', exact: true })).toHaveCount(0)
      await expect(reportPanel(page).locator('.report-document-head h1')).toBeVisible()
    }
    const choose = async (v: number) => {
      await reportPanel(page).getByRole('combobox', { name: 'Version' }).click()
      await page.getByRole('option', { name: `V${v}`, exact: true }).click()
      await shows(v)
    }
    await shows(3)
    // Latest to older, older to older, older to latest, latest to older again.
    for (const v of [1, 2, 3, 2]) await choose(v)
    // From V2, a reference opens Source details on top; Back returns to V2's report, not an empty panel.
    const second = byVersion.get(2)!
    const cited = second.claims.flatMap(c => c.evidence)[0]
    await reportPanel(page).locator('.reference-list > li').filter({ hasText: cited.title }).first().getByRole('button').click()
    await expect(sourcePanel(page)).toBeVisible()
    await head.getByRole('button', { name: 'Back', exact: true }).click()
    await shows(2)
    // Back to the latest, then a reference and Back again: still one report entry, now V3.
    await choose(3)
    await reportPanel(page).locator('.reference-list > li').first().getByRole('button').click()
    await expect(sourcePanel(page)).toBeVisible()
    await head.getByRole('button', { name: 'Back', exact: true }).click()
    await shows(3)
    await page.keyboard.press('Escape')
    await expect(page.locator('[data-split-panel]')).toHaveCount(0)
  })

  test('a citation chip opens the Citation panel; each entry opens its passage at the located anchor', async () => {
    const view = await viewOf(api, rid)
    const latest = [...valid(view)].sort((a, b) => (b.report_version ?? 0) - (a.report_version ?? 0))[0]
    await visit(page, research())
    // The thread shows the first two sections; the first claim there that cites is the first chip.
    const sections: Claim[][] = []
    for (const claim of latest.claims) {
      const last = sections[sections.length - 1]
      if (last && last[0].section === claim.section) last.push(claim); else sections.push([claim])
    }
    const claim = sections.slice(0, 2).flat().find(c => c.evidence.length)!
    const chip = page.locator('.answer-thread .answer-prose .cite-chip').first()
    await chip.click()
    const cite = panel(page, 'Citation')
    await expect(cite).toBeVisible()
    await expect(chip).toHaveClass(/is-on/)
    await expect(chip).toHaveAttribute('aria-expanded', 'true')
    // One entry per cited passage, each with its quote around the backend-located anchor, marked.
    const entries = cite.locator('.cite-entry')
    await expect(entries).toHaveCount(claim.evidence.length)
    for (const [i, e] of claim.evidence.entries()) {
      const entry = entries.nth(i)
      const source = view.sources.find(s => s.source_version_id === e.source_version_id)
      await expect(entry.locator('h3')).toHaveText(source?.title ?? e.title)
      expect(e.anchor_text).toBeTruthy()
      const mark = entry.locator('.quote mark.citation-highlight')
      await expect(mark).toHaveCount(1)
      expect(squash(await mark.innerText())).toBe(squash(e.anchor_text!))
      await expect(entry.locator('.loc')).toContainText(locator(e))
      await expect(entry.locator('.loc')).toContainText(versionText(e.version_label))
      await expect(entry.locator('.loc .ok-t')).toHaveText('Located in the passage')
      await expect(entry.locator('.rowacts button').first()).toHaveText(e.kind === 'abstract' ? 'Open the abstract' : 'Open in the full text')
    }
    await shot(page, 's12-citation-panel')
    // An entry opens its passage in Source details at the same anchor; Back returns to the Citation panel.
    const e = claim.evidence[0]
    const opened = page.waitForRequest(r => new URL(r.url()).pathname === `/api/researches/${rid}/passages/${e.passage_id}`)
    await entries.first().locator('.rowacts button').first().click()
    await opened
    const details = sourcePanel(page)
    await expect(details).toBeVisible()
    const mark = details.locator('mark.citation-highlight').first()
    await expect(mark).toBeVisible()
    expect(squash(await mark.innerText())).toBe(squash(e.anchor_text!))
    await page.locator('[data-split-panel]').getByRole('button', { name: 'Back', exact: true }).click()
    await expect(cite).toBeVisible()
    // Show in the PDF opens the PDF view on the cited page.
    const pdfAt = claim.evidence.findIndex(x => x.kind !== 'abstract' && x.evidence_status !== 'pdf_removed')
    if (pdfAt >= 0) {
      await entries.nth(pdfAt).getByRole('button', { name: 'Show in the PDF' }).click()
      await expect(details.getByRole('tab', { name: 'PDF' })).toHaveAttribute('aria-selected', 'true')
      await expect(details.locator('.pdf-viewer canvas')).toHaveAttribute('data-rendered-page', String(claim.evidence[pdfAt].physical_page))
      await page.locator('[data-split-panel]').getByRole('button', { name: 'Back', exact: true }).click()
      await expect(cite).toBeVisible()
    }
    // Escape ends the panels and gives focus back to the chip that opened them.
    await page.keyboard.press('Escape')
    await expect(page.locator('[data-split-panel]')).toHaveCount(0)
    await expect(chip).toBeFocused()
    await expect(chip).not.toHaveClass(/is-on/)
  })

  test('Source details: the work, where it stands, the action row, the three tabs and their empty states', async () => {
    const view = await viewOf(api, rid)
    const latest = [...valid(view)].sort((a, b) => (b.report_version ?? 0) - (a.report_version ?? 0))[0]
    // A cited PDF page: its source opens on Plain text, with the PDF and the abstract as the other tabs.
    const pdfEvidence = latest.claims.flatMap(c => c.evidence).find(e => e.kind !== 'abstract' && e.evidence_status === 'current')!
    const pdfSource = view.sources.find(s => s.source_version_id === pdfEvidence.source_version_id)!
    await visit(page, research())
    await page.locator('#research-answer').click()
    await reportPanel(page).locator('.reference-list > li').filter({ hasText: pdfSource.title }).first().getByRole('button').click()
    const details = sourcePanel(page)
    await expect(details.getByRole('tab')).toHaveText(['Plain text', 'PDF', 'Abstract'])
    await expect(details.getByRole('tab', { name: 'Plain text' })).toHaveAttribute('aria-selected', 'true')
    await expect(details.locator('.dhead h3')).toHaveText(pdfSource.title)
    await expect(details.locator('.dhead .pills .ref-pill').first()).toHaveText(/^PDF text · \d+ pp\.$/)
    await expect(details.locator('.dhead .pills .ref-pill').nth(1)).toHaveText(versionText(pdfSource.version_label))
    // P13: the decision and who made it, the claims of the latest answer that cite this copy, the similarity.
    const citing = latest.claims.filter(c => c.evidence.some(e => e.source_version_id === pdfSource.source_version_id)).length
    const decision = { included: 'Included', excluded: 'Excluded', pending: 'Undecided' }[pdfSource.selection.state]
    const dmeta = details.locator('.dmeta')
    await expect(dmeta.locator('span').first()).toHaveText(decision!)
    await expect(dmeta).toContainText(citing === 1 ? `cited in 1 claim of V${latest.report_version}` : `cited in ${citing} claims of V${latest.report_version}`)
    if (pdfSource.similarity !== null) await expect(dmeta).toContainText(`similarity ${pdfSource.similarity.toFixed(2)}`)
    // P17: the cited place in the text, and the size of the text read.
    await expect(details.locator('.pdf-text-citation')).toContainText('Cited passage')
    await expect(details.locator('.pdf-text-citation')).toContainText('1 / 1')
    await expect(details.locator('.sd-label-meta')).toContainText(/\d+ pages?/)
    await expect(details.locator('#source-text-view mark.citation-highlight').first()).toBeVisible()
    // P14: Open PDF, DOI, Copy citation, ⋯.
    const acts = details.locator('.dacts')
    await expect(acts.locator(':scope > *')).toHaveCount(4)
    await expect(acts.locator('.btn-pri')).toHaveText('Open PDF')
    if (pdfSource.doi) await expect(acts.getByRole('link', { name: 'Open DOI' })).toHaveAttribute('href', `https://doi.org/${pdfSource.doi}`)
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
    await acts.getByRole('button', { name: 'Copy citation' }).click()
    await expect(page.getByRole('status').filter({ hasText: 'Citation copied (APA 7).' })).toBeVisible()
    expect(await page.evaluate(() => navigator.clipboard.readText())).toContain(pdfSource.title)
    await acts.getByRole('button', { name: 'More actions' }).click()
    const menu = page.locator('.source-more-menu [data-slot=dropdown-menu-item]')
    await expect(menu.first()).toContainText('Replace PDF')
    await expect(menu.filter({ hasText: 'Copy as BibTeX' })).toHaveCount(1)
    await expect(menu.last()).toContainText('Remove from research')
    await menu.filter({ hasText: 'Copy as BibTeX' }).click()
    expect(await page.evaluate(() => navigator.clipboard.readText())).toMatch(new RegExp(`^@\\w+\\{[^,]+,\\n  title = \\{${pdfSource.title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\}`))
    await shot(page, 's12-source-details-text')
    await acts.locator('.btn-pri').click()
    await expect(details.getByRole('tab', { name: 'PDF' })).toHaveAttribute('aria-selected', 'true')
    await expect(details.locator('.pdf-viewer canvas')).toHaveAttribute('data-rendered-page', String(pdfEvidence.physical_page))
    await details.getByRole('tab', { name: 'Abstract' }).click()
    await expect(details.locator('#source-abs-view')).toContainText(pdfSource.access.abstract_passage_id ? 'Abstract' : 'No abstract is stored for this source.')
    // P20: where the source came from.
    if (pdfSource.provider_records.length) await expect(details.locator('.foot-note')).toContainText(`Found via${pdfSource.provider_records.map(p => PROVIDERS[p] ?? p).join('')}`)
    await page.keyboard.press('Escape')
    await expect(page.locator('[data-split-panel]')).toHaveCount(0)
  })

  test('a cited abstract opens on its Abstract tab with the anchor marked', async () => {
    const view = await viewOf(api, rid)
    const latest = [...valid(view)].sort((a, b) => (b.report_version ?? 0) - (a.report_version ?? 0))[0]
    // P19: an abstract cited by the answer. The fixture fetches every work's open PDF in the background, so its work
    // has a PDF by now and the abstract is the third tab, chosen because the citation is the abstract.
    const cited = latest.claims.flatMap(c => c.evidence).find(e => e.kind === 'abstract')!
    const source = view.sources.find(s => s.source_version_id === cited.source_version_id)!
    await visit(page, research())
    await page.locator('#research-answer').click()
    await reportPanel(page).locator('.reference-list > li').filter({ hasText: source.title }).filter({ has: page.locator('.ref-pills', { hasText: 'Abstract' }) }).first().getByRole('button').click()
    const details = sourcePanel(page)
    await expect(details.getByRole('tab')).toHaveText(source.access.assets.length ? ['Plain text', 'PDF', 'Abstract'] : ['Abstract', 'Plain text', 'PDF'])
    await expect(details.getByRole('tab', { name: 'Abstract' })).toHaveAttribute('aria-selected', 'true')
    await expect(details.locator('#source-abs-view h3.source-section')).toHaveText('Abstract')
    const mark = details.locator('#source-abs-view mark.citation-highlight')
    await expect(mark).toHaveCount(1)
    expect(squash(await mark.innerText())).toBe(squash(cited.anchor_text!))
    await expect(details.locator('#source-abs-view .foot-note')).toHaveText('Highlighted: the exact text cited in the answer.')
    await shot(page, 's12-source-details-abstract')
    await page.keyboard.press('Escape')
  })

  test('a work with only its abstract: empty Plain text and PDF tabs, and the open-copy lookup with the services it asked', async () => {
    const view = await viewOf(api, rid)
    // A work the answer did not cite and whose PDF was not fetched (the fixture fetches only some of the 412 works).
    const source = view.sources.find(s => !s.access.assets.length && s.doi && s.access.abstract_passage_id && s.version_role !== 'other_version')
    expect(source, 'the [parity] research holds a work with a DOI and no PDF').toBeTruthy()
    await visit(page, research())
    await openPanel(page, 'sources')
    const entry = page.locator('.source-row:not(.is-other-version)', { has: page.getByText(source!.title, { exact: true }) })
    await entry.scrollIntoViewIfNeeded()
    await entry.getByRole('button', { name: 'Read abstract' }).click()
    const details = sourcePanel(page)
    await expect(details.getByRole('tab')).toHaveText(['Abstract', 'Plain text', 'PDF'])
    await expect(details.getByRole('tab', { name: 'Abstract' })).toHaveAttribute('aria-selected', 'true')
    await expect(details.locator('.dhead .pills .ref-pill').first()).toHaveText('Abstract only')
    await expect(details.locator('.dacts .btn-pri')).toHaveText('Find PDF')
    // P18: the empty tabs say what is missing and carry Find PDF and Attach PDF.
    await details.getByRole('tab', { name: 'Plain text' }).click()
    await expect(details.locator('.source-empty h2')).toHaveText('No full text yet')
    await expect(details.locator('.source-empty p')).toHaveText('DEIXIS has only the abstract of this work. Find an open copy or attach the PDF, and the plain text appears here.')
    await expect(details.locator('.source-empty .acts > *')).toHaveText(['Find PDF', 'Attach PDF'])
    await expect(details.locator('.dacts .btn-pri')).toHaveCount(0)
    await details.getByRole('tab', { name: 'PDF' }).click()
    await expect(details.locator('.source-empty h2')).toHaveText('No PDF yet')
    await shot(page, 's12-source-details-empty')
    // P15: while the lookup runs no service is named (it is one request); then what each service it asked answered,
    // from the lookups it recorded, apart from the services it recorded without asking (no key or contact setting in
    // the fixture), and whether a file came. The request is held a moment so the running state can be seen.
    const before = source!.access.pdf_discoveries.length
    await page.route(`**/sources/${source!.source_version_id}/pdf-discovery`, async route => { await new Promise(r => setTimeout(r, 800)); await route.continue() })
    await details.locator('.source-empty .acts').getByRole('button', { name: 'Find PDF' }).click()
    const block = details.locator('.find-block')
    await expect(block).toContainText('Looking for an open copy…')
    await expect(block.locator('.pill')).toHaveCount(0)
    await expect(block).not.toContainText('Looking for an open copy…', { timeout: 30_000 })
    await page.unroute(`**/sources/${source!.source_version_id}/pdf-discovery`)
    const after = (await viewOf(api, rid)).sources.find(s => s.source_version_id === source!.source_version_id)!
    const records = after.access.pdf_discoveries.slice(before)
    const asked = [...new Set(records.filter(d => !notSent(d)).map(d => d.provider))]
    const skipped = [...new Set(records.filter(d => notSent(d)).map(d => d.provider))].filter(p => !asked.includes(p))
    expect(asked.length).toBeGreaterThan(0)
    expect(skipped.length, 'the fixture has services without a key or contact setting').toBeGreaterThan(0)
    await expect(block.locator('.pill')).toHaveText(asked.map(p => PROVIDERS[p] ?? p))
    const notAsked = block.locator('.find-skipped')
    await expect(notAsked).toContainText('Not asked:')
    for (const p of skipped) await expect(notAsked).toContainText(PROVIDERS[p] ?? p)
    if (after.access.assets.length) await expect(block).toContainText('Found an open copy.')
    else {
      await expect(block).toContainText('No open copy found.')
      await expect(block).toContainText(`Checked ${listed(asked.map(p => PROVIDERS[p] ?? p))}.`)
      for (const p of skipped) await expect(block.locator('.notice-body > p').first()).not.toContainText(PROVIDERS[p] ?? p)
      await expect(block.getByRole('button', { name: 'Attach PDF' })).toBeVisible()
    }
    await shot(page, 's12-source-details-find')
    await page.keyboard.press('Escape')
  })

  test('a file kept without text is not shown as text: the badge and the found sentence follow its extraction', async () => {
    const view = await viewOf(api, rid)
    const chosen = view.sources.filter(s => !s.access.assets.length && s.doi && s.access.abstract_passage_id && s.version_role !== 'other_version')
    // Another work than the previous case's (that one may have a file now).
    const source = chosen[chosen.length - 1]
    const kept = { id: 'ast_SYNTHETIC_kept', extraction_status: 'no_text', page_count: 3, origin: 'open_access', byte_size: 1000, original_filename: null }
    // PATCHED VIEW: after the real lookup, the view the page receives holds a kept file with no text layer for this work
    // (the fixture's open PDFs all have text). The lookup rows are the stored ones.
    let found = false
    await page.route(`**/api/researches/${rid}`, async route => {
      const response = await route.fetch()
      const body = await response.json() as View
      if (found) for (const s of body.sources) if (s.source_version_id === source.source_version_id) s.access.assets = [kept as never]
      await route.fulfill({ response, json: body })
    })
    await page.route(`**/sources/${source.source_version_id}/pdf-discovery`, async route => { const response = await route.fetch(); found = true; await route.fulfill({ response }) })
    try {
      await visit(page, research())
      await openPanel(page, 'sources')
      const entry = page.locator('.source-row:not(.is-other-version)', { has: page.getByText(source.title, { exact: true }) })
      await entry.scrollIntoViewIfNeeded()
      await entry.getByRole('button', { name: 'Read abstract' }).click()
      const details = sourcePanel(page)
      await details.locator('.dacts .btn-pri').click()
      const block = details.locator('.find-block')
      await expect(block).toContainText('Found an open copy.', { timeout: 30_000 })
      await expect(block).toContainText('The file is kept, but it has no text layer to extract, so a new answer cannot read it yet.')
      await expect(block).not.toContainText('a new answer can read it')
      await expect(block.getByRole('button', { name: 'Read the plain text' })).toHaveCount(0)
      await expect(details.locator('.dhead .pills .ref-pill').first()).toHaveText('PDF without extracted text')
      await shot(page, 's12-source-details-kept-no-text')
      // A failed extraction reads the same way in the badge.
      kept.extraction_status = 'failed'
      await page.keyboard.press('Escape')
      await visit(page, research())
      await openPanel(page, 'sources')
      await entry.scrollIntoViewIfNeeded()
      await entry.getByRole('button', { name: 'Read abstract' }).click()
      await expect(sourcePanel(page).locator('.dhead .pills .ref-pill').first()).toHaveText('PDF without extracted text')
      await page.keyboard.press('Escape')
    } finally {
      // In-flight handlers of this case end quietly when the next case navigates.
      await page.unrouteAll({ behavior: 'ignoreErrors' })
    }
  })

  test('Find PDF from the Citation panel starts a lookup each time it is chosen', async () => {
    const view = await viewOf(api, rid)
    const latest = [...valid(view)].sort((a, b) => (b.report_version ?? 0) - (a.report_version ?? 0))[0]
    // PATCHED VIEW: the first thread claim whose first citation is an abstract (found in the stored answer, not by the
    // chip's position) has that work shown without its PDF (the fixture fetched one), so its Citation entry offers Find
    // PDF; each lookup request is counted and answered without a change. After the first lookup the page's reload is
    // held until Find PDF has been chosen again, so the second choice always comes while the first lookup still runs.
    const sections: Claim[][] = []
    for (const claim of latest.claims) {
      const last = sections[sections.length - 1]
      if (last && last[0].section === claim.section) last.push(claim); else sections.push([claim])
    }
    // The thread shows the first two sections, one chip per claim that cites anything, in the answer's order.
    const chipped = sections.slice(0, 2).flat().filter(c => c.evidence.length)
    const chip = chipped.findIndex(c => c.evidence[0].kind === 'abstract')
    expect(chip, 'a thread claim whose first citation is an abstract').toBeGreaterThanOrEqual(0)
    const claim = chipped[chip]
    const svid = claim.evidence[0].source_version_id
    expect(claim.evidence[0].kind).toBe('abstract')
    const title = view.sources.find(s => s.source_version_id === svid)!.title
    let lookups = 0
    let release!: () => void
    const held = new Promise<void>(resolve => { release = resolve })
    await page.route(`**/api/researches/${rid}`, async route => {
      const response = await route.fetch()
      const body = await response.json() as View
      for (const s of body.sources) if (s.source_version_id === svid) s.access.assets = []
      if (lookups === 1) await held
      await route.fulfill({ response, json: body })
    })
    await page.route(`**/sources/${svid}/pdf-discovery`, route => { lookups += 1; return route.fulfill({ json: {} }) })
    try {
      await visit(page, research())
      await page.locator('.answer-thread .answer-prose .cite-chip').nth(chip).click()
      const cite = panel(page, 'Citation')
      // The Citation panel lists that claim's citations in its order: the first entry is the abstract citation.
      await expect(cite.locator('.cite-entry')).toHaveCount(claim.evidence.length)
      const head = page.locator('[data-split-panel] .split-panel-head')
      for (const n of [1, 2]) {
        await cite.locator('.cite-entry').first().getByRole('button', { name: 'Find PDF' }).click()
        if (n === 2) {
          // The second opening has loaded its passage while the first lookup still runs; only then is the reload let go.
          await expect(sourcePanel(page).locator('.dhead h3')).toHaveText(title)
          await expect(sourcePanel(page).locator('.find-block')).toContainText('Looking for an open copy…')
          expect(lookups).toBe(1)
          release()
        }
        await expect.poll(() => lookups).toBe(n)
        await expect(sourcePanel(page).locator('.find-block')).toBeVisible()
        await head.getByRole('button', { name: 'Back', exact: true }).click()
        await expect(cite).toBeVisible()
      }
      await page.keyboard.press('Escape')
    } finally {
      release()
      // In-flight handlers of this case end quietly when the next case navigates.
      await page.unrouteAll({ behavior: 'ignoreErrors' })
    }
  })

  test('an earlier lookup that ends first never marks a newer lookup on another work done', async () => {
    const view = await viewOf(api, rid)
    const chosen = view.sources.filter(s => !s.access.assets.length && s.doi && s.access.abstract_passage_id && s.version_role !== 'other_version')
    const [a, b] = [chosen[1], chosen[2]]
    // A's lookup is held 1.5 s, B's until A's has answered and 3 s more: A ends while B still runs.
    let aDone!: () => void
    const aAnswered = new Promise<void>(resolve => { aDone = resolve })
    await page.route(`**/sources/${a.source_version_id}/pdf-discovery`, async route => {
      await new Promise(r => setTimeout(r, 1500)); const response = await route.fetch(); await route.fulfill({ response }); aDone()
    })
    await page.route(`**/sources/${b.source_version_id}/pdf-discovery`, async route => {
      await aAnswered; await new Promise(r => setTimeout(r, 3000)); await route.continue()
    })
    try {
      await visit(page, research())
      await openPanel(page, 'sources')
      const open = async (title: string) => {
        const entry = page.locator('.source-row:not(.is-other-version)', { has: page.getByText(title, { exact: true }) })
        await entry.scrollIntoViewIfNeeded()
        await entry.getByRole('button', { name: 'Read abstract' }).click()
        await expect(sourcePanel(page).locator('.dhead h3')).toHaveText(title)
      }
      const head = page.locator('[data-split-panel] .split-panel-head')
      await open(a.title)
      await sourcePanel(page).locator('.dacts .btn-pri').click()
      await expect(sourcePanel(page).locator('.find-block')).toContainText('Looking for an open copy…')
      await head.getByRole('button', { name: 'Back', exact: true }).click()
      await open(b.title)
      const details = sourcePanel(page)
      await details.locator('.dacts .btn-pri').click()
      const block = details.locator('.find-block')
      await expect(block).toContainText('Looking for an open copy…')
      await aAnswered
      // A answered and the page reloaded; B's panel still shows its own lookup running.
      await expect.poll(async () => (await viewOf(api, rid)).sources.find(s => s.source_version_id === a.source_version_id)!.access.pdf_discoveries.length).toBeGreaterThan(a.access.pdf_discoveries.length)
      await page.waitForTimeout(800)
      await expect(block).toContainText('Looking for an open copy…')
      await expect(block).not.toContainText('No open copy found.')
      await expect(details.locator('.dacts .btn-pri')).toBeDisabled()
      // Then B's own answer: the services it asked, from B's records.
      await expect(block).not.toContainText('Looking for an open copy…', { timeout: 30_000 })
      const after = (await viewOf(api, rid)).sources.find(s => s.source_version_id === b.source_version_id)!
      const asked = [...new Set(after.access.pdf_discoveries.slice(b.access.pdf_discoveries.length).filter(d => !notSent(d)).map(d => d.provider))]
      await expect(block.locator('.pill')).toHaveText(asked.map(p => PROVIDERS[p] ?? p))
      await page.keyboard.press('Escape')
    } finally {
      // In-flight handlers of this case end quietly when the next case navigates.
      await page.unrouteAll({ behavior: 'ignoreErrors' })
    }
  })

  test('a Europe PMC file opened from an abstract is labelled as drawn by DEIXIS in the text and PDF views', async () => {
    const view = await viewOf(api, rid)
    const latest = [...valid(view)].sort((a, b) => (b.report_version ?? 0) - (a.report_version ?? 0))[0]
    const cited = latest.claims.flatMap(c => c.evidence).find(e => e.kind === 'abstract')!
    const source = view.sources.find(s => s.source_version_id === cited.source_version_id)!
    const file = source.access.assets[0]
    expect(file, 'the fixture fetched this work\'s PDF').toBeTruthy()
    // PATCHED VIEW: the work's stored file is marked as Europe PMC's text drawn by DEIXIS (rendition), in the research
    // view and in the file's text, as the backend marks such a file (SW21). The fixture's PDFs are publisher-like.
    await page.route(`**/api/researches/${rid}`, async route => {
      const response = await route.fetch()
      const body = await response.json() as View
      for (const s of body.sources) if (s.source_version_id === source.source_version_id) s.access.assets = s.access.assets.map(x => ({ ...x, rendition: true }))
      await route.fulfill({ response, json: body })
    })
    await page.route(`**/assets/${file.id}/text**`, async route => {
      const response = await route.fetch()
      const body = await response.json() as { asset: Record<string, unknown> }
      await route.fulfill({ response, json: { ...body, asset: { ...body.asset, rendition: true } } })
    })
    try {
      await visit(page, research())
      await page.locator('#research-answer').click()
      await reportPanel(page).locator('.reference-list > li').filter({ hasText: source.title }).filter({ has: page.locator('.ref-pills', { hasText: 'Abstract' }) }).first().getByRole('button').click()
      const details = sourcePanel(page)
      const notice = details.getByText('This PDF was drawn by DEIXIS from Europe PMC’s open-access text. Its pages are not the publisher’s pages.')
      await expect(details.getByRole('tab', { name: 'Abstract' })).toHaveAttribute('aria-selected', 'true')
      await expect(notice).toHaveCount(0)
      await details.getByRole('tab', { name: 'Plain text' }).click()
      await expect(details.locator('.sd-label-meta')).toContainText(/Drawn from Europe PMC · \d+ pages?/)
      await expect(notice).toBeVisible()
      await details.getByRole('tab', { name: 'PDF' }).click()
      await expect(notice).toBeVisible()
      await expect(details.locator('.pdf-viewer canvas')).toHaveAttribute('aria-label', /^Europe PMC text, rendered p\. \d+$/)
      await details.getByRole('tab', { name: 'Abstract' }).click()
      await expect(notice).toHaveCount(0)
      await page.keyboard.press('Escape')
    } finally {
      // In-flight handlers of this case end quietly when the next case navigates.
      await page.unrouteAll({ behavior: 'ignoreErrors' })
    }
  })

  test('after Replace PDF the Plain text of an abstract-opened work reads the new file, and an earlier read never overwrites it', async () => {
    const view = await viewOf(api, rid)
    const latest = [...valid(view)].sort((a, b) => (b.report_version ?? 0) - (a.report_version ?? 0))[0]
    const abstracts = latest.claims.flatMap(c => c.evidence).filter(e => e.kind === 'abstract')
    // Another abstract-cited work than the earlier cases' (its file is replaced twice here).
    const cited = abstracts[abstracts.length - 1]
    const source = view.sources.find(s => s.source_version_id === cited.source_version_id)!
    const first = source.access.assets[0]
    expect(first, 'the fixture fetched this work\'s PDF').toBeTruthy()
    // PATCHED VIEW: the work's first file is marked as Europe PMC's text drawn by DEIXIS, so its replacement (the
    // publisher-like fixture PDF) must change the text view's provenance too. The second file's text read is held 6 s
    // and its text swapped for "SYNTHETIC STALE TEXT", so a late answer for it would show.
    await page.route(`**/api/researches/${rid}`, async route => {
      const response = await route.fetch()
      const body = await response.json() as View
      for (const s of body.sources) for (const x of s.access.assets) if (x.id === first.id) x.rendition = true
      await route.fulfill({ response, json: body })
    })
    let secondId: string | null = null
    let staleDone!: () => void
    const staleAnswered = new Promise<void>(resolve => { staleDone = resolve })
    await page.route('**/assets/*/text**', async route => {
      const id = new URL(route.request().url()).pathname.split('/').at(-2)!
      const response = await route.fetch()
      const body = await response.json() as { asset: Record<string, unknown>; passages: Array<{ text: string }> }
      if (id === first.id) return route.fulfill({ response, json: { ...body, asset: { ...body.asset, rendition: true } } })
      if (secondId === null) secondId = id
      if (id !== secondId) return route.fulfill({ response })
      await new Promise(r => setTimeout(r, 6000))
      await route.fulfill({ response, json: { ...body, passages: body.passages.map(p => ({ ...p, text: 'SYNTHETIC STALE TEXT' })) } }).catch(() => {})
      staleDone()
    })
    const replace = async (name: string) => {
      const details = sourcePanel(page)
      await details.locator('.dacts').getByRole('button', { name: 'More actions' }).click()
      const chooser = page.waitForEvent('filechooser')
      await page.locator('.source-more-menu [data-slot=dropdown-menu-item]').filter({ hasText: 'Replace PDF' }).click()
      await (await chooser).setFiles(server.replacementPdf(name))
      await page.getByRole('dialog', { name: 'Replace PDF?' }).getByRole('button', { name: 'Replace PDF' }).click()
      await expect(page.getByText('PDF replaced.').first()).toBeVisible()
    }
    try {
      await visit(page, research())
      await page.locator('#research-answer').click()
      await reportPanel(page).locator('.reference-list > li').filter({ hasText: source.title }).filter({ has: page.locator('.ref-pills', { hasText: 'Abstract' }) }).first().getByRole('button').click()
      const details = sourcePanel(page)
      const text = details.locator('#source-text-view')
      await details.getByRole('tab', { name: 'Plain text' }).click()
      // The fixture's first file names the work's DOI on its first page.
      await expect(text).toContainText(`https://doi.org/${source.doi}`)
      await expect(details.locator('.sd-label-meta')).toContainText(/Drawn from Europe PMC · \d+ pages?/)
      // The first replacement: its text read is held; the second replacement comes while it still runs.
      await replace('replacement-a')
      await expect(text).toContainText('Loading PDF text…')
      await replace('replacement-b')
      await expect(text).toContainText('SYNTHETIC replacement scan', { timeout: 20_000 })
      await expect(text).not.toContainText(`https://doi.org/${source.doi}`)
      await expect(details.locator('.sd-label-meta')).toContainText('1 page')
      await expect(details.locator('.dhead .pills .ref-pill').first()).toHaveText('PDF text · 1 pp.')
      // The held read for the second file answers now; the third file's text stays.
      await staleAnswered
      await page.waitForTimeout(500)
      await expect(text).not.toContainText('SYNTHETIC STALE TEXT')
      await expect(text).toContainText('SYNTHETIC replacement scan')
      const current = (await viewOf(api, rid)).sources.find(s => s.source_version_id === source.source_version_id)!.access.assets[0]
      expect([first.id, secondId]).not.toContain(current.id)
      await page.keyboard.press('Escape')
    } finally {
      // In-flight handlers of this case end quietly when the next case navigates.
      await page.unrouteAll({ behavior: 'ignoreErrors' })
    }
  })

  test('at 390 px the Citation panel and Source details are dialogs without a horizontal scroll', async ({ browser }) => {
    const narrow = await browser.newPage({ viewport: { width: 390, height: 844 } })
    try {
      await visit(narrow, research())
      await narrow.locator('.answer-thread .answer-prose .cite-chip').first().click()
      const cite = narrow.getByRole('dialog', { name: 'Citation' })
      await expect(cite).toBeVisible()
      const noSideScroll = (selector: string) => narrow.locator(selector).evaluate(el => el.scrollWidth <= el.clientWidth + 1)
      expect(await noSideScroll('[data-split-panel] .split-panel-body')).toBe(true)
      await cite.locator('.cite-entry .rowacts button').first().click()
      await expect(narrow.getByRole('dialog', { name: 'Source details' })).toBeVisible()
      expect(await noSideScroll('[data-split-panel] .split-panel-body')).toBe(true)
      expect(await narrow.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
      await shot(narrow, 's12-source-details-390')
    } finally { await narrow.close() }
  })
})
