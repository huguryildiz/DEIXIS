import { expect, request as apiRequest, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import type { LineageBaseline, LineageLink, LineagePlan, LineageReason, LineageStepOutcome, LineageView, ResearchView, TableView } from '../src/api'
import { nextPort } from './ports'

// Synthetic application behavior only. Port from nextPort().
const REPO = path.resolve(process.cwd(), '..', '..')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
const PORT = nextPort()
const URL = `http://127.0.0.1:${PORT}`
const TITLES = [
  'SYNTHETIC A foundational release model with fixed pulse spacing', 'SYNTHETIC B adaptive timing for release experiments',
  'SYNTHETIC C interval search for release experiments', 'SYNTHETIC D unrelated sediment sampling in shallow water',
  'SYNTHETIC E isolated sensor measurements in a tank', 'SYNTHETIC F numbered references in pulse experiments',
]
const HEADINGS = ['Development status', 'Lines', 'Independent parallel work', 'Works without a placed link', 'Proposals not accepted',
  'Citation edges without a mention', 'Citation edges into unscanned works', 'Pairs not sent for budget', 'Failed pairs', 'Run outcomes', 'History', 'Counts']
mkdirSync(OUT, { recursive: true })

class LineageServer {
  private proc?: ChildProcess
  async start() {
    const data = mkdtempSync(path.join(tmpdir(), 'deixis-l7-'))
    this.proc = spawn(process.env.DEIXIS_TEST_PYTHON ?? path.join(REPO, '.venv/bin/python'),
      [path.join(REPO, 'tests/acceptance/fixture_server.py'), '--data-dir', data, '--port', String(PORT)],
      { cwd: REPO, env: { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: `${REPO}/backend:${REPO}` }, stdio: 'inherit' })
    await expect.poll(async () => { try { return (await fetch(`${URL}/api/health`)).ok } catch { return false } }).toBe(true)
  }
  async stop() {
    const proc = this.proc
    if (!proc || proc.exitCode !== null) return
    const ended = new Promise(resolve => proc.once('exit', resolve))
    proc.kill('SIGTERM'); await ended
  }
}
type Fixture = { api: APIRequestContext; headers: Record<string, string>; rid: string; tid: string; base: string; ids: string[] }
async function waitRun(api: APIRequestContext, rid: string, kind: string) {
  await expect.poll(async () => { const r: ResearchView = await (await api.get(`/api/researches/${rid}`)).json(); return r.runs.find(r => r.kind === kind)?.status }).toBe('completed')
}
async function fixture(page: Page, api: APIRequestContext, marker = '[lineage]', fill = true): Promise<Fixture> {
  const csrf = (await (await api.get('/api/session')).json()).csrf_token as string
  const headers = { 'x-deixis-csrf': csrf }
  await page.goto(URL)
  await page.getByLabel('Research question').fill(`SYNTHETIC molecule release scheduling ${marker}`)
  await page.getByRole('button', { name: 'Start research' }).click()
  await page.waitForURL(/#\/research\//)
  const rid = page.url().split('/research/')[1].split('/')[0]
  await waitRun(api, rid, 'discovery')
  let research: ResearchView = await (await api.get(`/api/researches/${rid}`)).json()
  expect(research.sources).toHaveLength(6)
  const ids = TITLES.map(title => research.sources.find(s => s.title === title)!.source_version_id)
  for (const id of ids) {
    const source = research.sources.find(s => s.source_version_id === id)!
    const response = await api.patch(`/api/researches/${rid}/selections/${id}`, { headers, data: { state: 'included', expected_version: source.selection.version, reason: 'SYNTHETIC inclusion' } })
    expect(response.ok()).toBe(true)
  }
  const pdfs = await api.post(`/api/researches/${rid}/runs`, { headers, data: { kind: 'pdf_collection' } })
  expect(pdfs.ok()).toBe(true)
  await waitRun(api, rid, 'pdf_collection')
  research = await (await api.get(`/api/researches/${rid}`)).json()
  expect(research.sources.every(s => s.access.assets.length > 0)).toBe(true)
  const created = await api.post(`/api/researches/${rid}/tables`, { headers, data: { title: 'Synthetic development table' } })
  expect(created.status()).toBe(201)
  const table: TableView = await created.json()
  const tid = table.table.id, base = `/api/researches/${rid}/tables/${tid}`
  await page.reload(); await openLines(page)
  await expect(page.locator('.lineage-status')).toContainText('missing:')
  await page.locator('.lineage-view').getByRole('button', { name: 'Add development columns' }).click()
  await expect(page.locator('.lineage-status')).toContainText('columns: present')
  if (fill) {
    const current: TableView = await (await api.get(base)).json()
    const filled = await api.post(`${base}/fill`, { headers, data: { expected_version: current.table.version } })
    expect(filled.status()).toBe(202)
    await waitRun(api, rid, 'table_fill')
    const result: TableView = await (await api.get(base)).json()
    expect(result.cells.filter(c => c.current?.state === 'value')).toHaveLength(18)
    await expect(page.locator('.lineage-status')).toContainText('6 complete nodes')
  }
  return { api, headers, rid, tid, base, ids }
}
async function openLines(page: Page) {
  await page.getByRole('tab', { name: /^Evidence/ }).click()
  await page.getByRole('tab', { name: 'Development lines', exact: true }).click()
  await expect(page.locator('.lineage-status')).toBeVisible()
}
const section = (page: Page, name: string) => page.locator('.lineage-section').filter({ has: page.getByRole('heading', { name: new RegExp(`^${name} ·`) }) }).first()
async function headings(page: Page) { for (const name of HEADINGS) await expect(page.locator('.lineage-view').getByRole('heading', { name: new RegExp(`^${name}( ·|$)`) }).first()).toBeVisible() }
async function chromeWords(page: Page) {
  const text = await page.locator('.lineage-view').evaluate(el => { const copy = el.cloneNode(true) as HTMLElement; copy.querySelectorAll('[data-stored-text]').forEach(e => e.remove()); return copy.textContent ?? '' })
  expect(text).not.toMatch(/\b(foundational|founder|novel|original|continuation|importance|strength|score|verified|proof)\b/i)
  await expect(page.locator('.lineage-view').getByRole('button', { name: TITLES[0], exact: true }).first()).toHaveText(TITLES[0])
}
async function capture(page: Page, state: string, prepare?: () => Promise<void>, close?: () => Promise<void>, focus?: Locator) {
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 })
    for (const theme of ['light', 'dark']) {
      const dark = await page.locator('html').evaluate(el => el.classList.contains('dark'))
      if (dark !== (theme === 'dark')) await page.getByRole('button', { name: dark ? 'Use light theme' : 'Use dark theme' }).click()
      if (prepare) await prepare()
      if (focus) await focus.scrollIntoViewIfNeeded()
      if (width === 390) await expect.poll(() => page.locator('.lineage-view').evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
      await page.screenshot({ path: path.join(OUT, `l7-${state}-${width}-${theme}.png`), animations: 'disabled' })
      if (close) await close()
    }
  }
  await page.setViewportSize({ width: 1440, height: 1000 })
  if (await page.locator('html').evaluate(el => el.classList.contains('dark'))) await page.getByRole('button', { name: 'Use light theme' }).click()
}
async function runLinks(page: Page, f: Fixture) {
  await page.getByRole('button', { name: 'Find development links' }).click()
  await expect(page.locator('.lineage-plan')).toContainText('works will be read')
  await page.locator('.lineage-plan').getByRole('button', { name: 'Start', exact: true }).click()
  await waitRun(f.api, f.rid, 'lineage_links')
  await expect(section(page, 'Lines')).toContainText('Line · 3 members')
}
async function picker(page: Page, from: string, to: string, changed: string, quote: string) {
  const dialog = page.getByRole('dialog', { name: 'Add development link' })
  await dialog.getByLabel('Earlier work').selectOption(from)
  await dialog.getByLabel('Later work').selectOption(to)
  await dialog.getByLabel('What changed').fill(changed)
  await dialog.getByRole('button', { name: /PDF p. 1/ }).click()
  await dialog.getByLabel('Quote 1').fill(quote)
  return dialog
}

function renderingView(f: Fixture): LineageView {
  const reasons: LineageReason[] = ['not_run', 'no_pdf_text', 'no_candidate', 'no_relation', 'insufficient_evidence', 'rejected', 'not_sent_budget', 'step_failed', 'human_removed', 'cross_relation_only', 'stale_only']
  const nodes: LineageView['nodes'] = {}
  for (let i = 0; i < 18; i++) {
    const id = f.ids[i] ?? `srv_mock_${i}`
    nodes[id] = { source_version_id: id, work_id: `wrk_mock_${i}`, title: TITLES[i] ?? `SYNTHETIC reason work ${i} ` + 'LongTitle'.repeat(40),
      source_key: i === 16 ? 'UnbrokenKey'.repeat(45) : `Work${i}`, year: 2010 + i, live: i !== 17,
      position: i, eligible: true, access_level: 'pdf_available', version_label: 'published' }
  }
  const ids = Object.keys(nodes), time = '2026-10-01T12:00:00Z'
  const link = (name: string, from: number, to: number, more: Partial<LineageLink> = {}): LineageLink => ({
    link_id: `lnk_${name}`, revision_id: `llr_${name}`, version: 1, from: ids[from], to: ids[to], relation: 'extends',
    what_changed: `SYNTHETIC foundational change ${name} ` + 'LongChange'.repeat(50), support_type: 'source_stated', author: 'model', human_edited: false,
    note: `SYNTHETIC foundational note ${name}`, edge_state: 'present', unexpected_no_citation_edge: false, year_order_warning: false,
    not_head_ends: [], output_status: 'structurally_valid', scope_revision: 1, run_id: 'run_mock', created_at: time,
    evidence: [{ passage_id: 'psg_mock', anchor_text: 'SYNTHETIC foundational quote exactly kept', anchor_match: 'exact', physical_page: 2, printed_label: 'ii', kind: 'pdf_page' },
      { passage_id: 'psg_mock_2', anchor_text: 'SYNTHETIC second quote', anchor_match: 'exact', physical_page: 3, printed_label: 'iii', kind: 'pdf_page' }], stale_reasons: [], ...more,
  })
  const links = [link('ab', 0, 1, { not_head_ends: ['from'], unexpected_no_citation_edge: true, edge_state: 'absent_in_read_list', year_order_warning: true, output_status: 'unverified_draft' }), link('ac', 0, 2), link('bd', 1, 3), link('cd', 2, 3)]
  const outcomes: LineageStepOutcome[] = ['failed_pair', 'unsent_pair', 'step_failed', 'skipped'].map((kind, i) => ({
    kind: kind as LineageStepOutcome['kind'], from: i < 2 ? ids[0] : null, to: ids[4 + i], key: `chunk_${i}`, pair_fp: null,
    reason: `SYNTHETIC raw reason ${kind}`, run_id: 'run_mock', scope_revision: 1, recorded_at: time,
    current: i === 0 ? true : i === 1 ? false : null, stale_reasons: i === 1 ? ['scope_changed', 'node_changed', 'passage_changed'] : [],
    unchecked: i === 0 ? ['passage_text'] : ['node_snapshots', 'passages'],
  }))
  const unplaceable = reasons.map((reason, i) => ({ source_version_id: ids[i + 4], reasons: i === 0 ? [reason, 'no_pdf_text' as LineageReason] : [reason], last_run: { run_id: 'run_mock', scope_revision: 1, recorded_at: time },
    details: [true, false, null].map(current => ({ reason, from: ids[0], to: ids[i + 4], link_id: null, revision_id: null, run_id: 'run_mock', scope_revision: 1, recorded_at: time,
      current, stale_reasons: current === false ? ['scope_changed' as const, 'node_changed' as const, 'passage_changed' as const] : [], unchecked: current === true ? ['passage_text'] : ['node_snapshots', 'passages'] })) }))
  return {
    table_id: f.tid, table_version: 4, nodes,
    status: { roles: { problem: true, change: true, uncertainty: true }, live_rows: 17, pdf_text_rows: 16, nodes_complete: 10, nodes_partial: 7, missing_cells: 8, placed_rows: 4, unplaced_rows: 13 },
    pair_decisions: links.map(l => ({ link_id: l.link_id, from: l.from, to: l.to, version: 1, current_revision_id: l.revision_id, decision: 'link', author: 'model', disposition: 'accepted' })),
    components: [{ id: 'mock_diamond', members: ids.slice(0, 4), links, roots: [ids[0]], branches: [ids[0]], merges: [ids[3]], has_cycle: true,
      adjacency: [{ source_version_id: ids[0], in_from: [], out_to: [ids[1], ids[2]] }, { source_version_id: ids[1], in_from: [ids[0]], out_to: [ids[3]] }, { source_version_id: ids[2], in_from: [ids[0]], out_to: [ids[3]] }, { source_version_id: ids[3], in_from: [ids[1], ids[2]], out_to: [] }] }],
    cross_relations: [link('parallel', 4, 5, { relation: 'independent_parallel' })], unplaceable,
    not_accepted: ['cycle', 'unknown_rejection_kept'].map((rejection_code, i) => ({ link_id: `lnk_rejected_${i}`, revision_id: `llr_rejected_${i}`, from: ids[1], to: ids[0], rejection_code,
      decision: 'link', relation: 'extends', what_changed: 'SYNTHETIC foundational rejected wording', support_type: 'analyst_inference', note: 'SYNTHETIC foundational rejected note', run_id: 'run_mock', created_at: time,
      superseded: true, pair_state: { decision: 'removed', author: 'human' } })),
    unassessed_edges: [{ from: ids[0], to: ids[5] }], edges_into_unscanned_targets: [{ from: ids[0], to: ids[15], to_reason: 'no_pdf_text' }, { from: ids[0], to: ids[16], to_reason: 'not_run' }],
    step_outcomes: outcomes, failed_pairs: [outcomes[0]], not_sent_budget: [outcomes[1]],
    history: { stale: [link('stale', 0, 15, { stale_reasons: ['evidence_not_current', 'scope_changed', 'node_changed'] })], out_of_scope: [{ ...link('out', 16, 17), not_live_ends: ['to'] }] },
    counts: { components: 1, current_links: 4, cross_relations: 1, history_stale: 1, history_out_of_scope: 1,
      unplaceable: { total: 11, reasons: Object.fromEntries(reasons.map(r => [r, 1])) as Record<LineageReason, number> }, not_accepted: 2, unassessed_edges: 1, edges_into_unscanned_targets: 2,
      not_sent_budget: 1, failed_pairs: 1, step_outcomes: 4, human_edited_links: 0, edge_states: { present: 8, absent_in_read_list: 9, unresolved: 10, not_read: 11 } },
  }
}

test.describe('recorded development lines', () => {
  const server = new LineageServer()
  test.beforeAll(async () => { await server.start() })
  test.afterAll(async () => { await server.stop() })
  let api: APIRequestContext
  test.beforeEach(async () => { api = await apiRequest.newContext({ baseURL: URL, extraHTTPHeaders: { origin: URL } }) })
  test.afterEach(async () => { await api.dispose() })

  test('real scan, branching, located anchors, durable human edits, baseline and keyboard', async ({ page }) => {
    test.setTimeout(240_000)
    const f = await fixture(page, api)
    await headings(page)
    const find = page.getByRole('button', { name: 'Find development links' })
    await page.getByRole('tab', { name: 'Development lines', exact: true }).focus()
    await page.keyboard.press('Tab'); await expect(find).toBeFocused()
    await page.keyboard.press('Enter')
    const plan = page.locator('.lineage-plan')
    await expect(plan).toContainText('6 works will be read')
    await expect(plan).toContainText('3 model calls')
    await expect(plan).toContainText('at most 18 model calls')
    await capture(page, 'plan', undefined, undefined, plan)
    await plan.getByRole('button', { name: 'Start', exact: true }).click()
    await waitRun(api, f.rid, 'lineage_links')
    const result: LineageView = await (await api.get(`${f.base}/lineage`)).json()
    expect(result.components).toHaveLength(1)
    expect(result.components[0].branches).toEqual([f.ids[0]])
    expect(result.components[0].links.map(l => [l.from, l.to])).toEqual([[f.ids[0], f.ids[1]], [f.ids[0], f.ids[2]]])
    expect(result.pair_decisions.filter(p => p.to === f.ids[3]).map(p => p.decision)).toEqual(['no_relation', 'no_relation'])
    expect(result.unplaceable.find(w => w.source_version_id === f.ids[3])!.reasons).toContain('no_relation')
    expect(result.unplaceable.find(w => w.source_version_id === f.ids[4])!.reasons).toContain('no_candidate')
    expect(result.unassessed_edges).toEqual([{ from: f.ids[0], to: f.ids[5] }])
    const lines = section(page, 'Lines')
    await expect(lines).toContainText('Line · 3 members')
    await expect(lines).toContainText('branches at')
    await expect(lines).not.toContainText('merges at None.')
    await expect(lines).toContainText('changes method')
    await expect(lines).toContainText('source stated')
    await expect(lines).toContainText('citation list: present')
    await expect(section(page, 'Works without a placed link')).toContainText('a recorded decision found no relation for the considered pair')
    await expect(section(page, 'Works without a placed link')).toContainText('no earlier work in this table was found mentioned in its stored text')
    await expect(section(page, 'Citation edges without a mention')).toContainText(TITLES[5])
    await headings(page); await chromeWords(page)
    const ab = lines.locator(`[data-link-id="${result.components[0].links[0].link_id}"]`)
    const rowButton = ab.locator('.lineage-link-open')
    await rowButton.focus(); await page.keyboard.press('Enter')
    const source = page.getByRole('dialog', { name: 'Source details' })
    await expect(source).toContainText('PDF p. 1')
    await expect(source.locator('mark.citation-highlight').first()).toHaveText(result.components[0].links[0].evidence[0].anchor_text)
    await page.keyboard.press('Escape'); await expect(source).toHaveCount(0)
    await expect(rowButton).toBeFocused()
    await page.keyboard.press('Tab'); await expect(ab.getByRole('button', { name: TITLES[0], exact: true })).toBeFocused()
    // Source titles remain actual keyboard controls, followed by the separate Edit/Remove actions.
    await ab.getByRole('button', { name: 'Edit', exact: true }).focus(); await page.keyboard.press('Tab'); await expect(ab.getByRole('button', { name: 'Remove', exact: true })).toBeFocused()
    await capture(page, 'lines', undefined, undefined, lines.getByRole('heading', { name: /^Lines/ }))
    await capture(page, 'lists', undefined, undefined, section(page, 'Works without a placed link').getByRole('heading', { name: /^Works without/ }))
    const ac = result.components[0].links[1], acRow = lines.locator(`[data-link-id="${ac.link_id}"]`)
    await acRow.getByRole('button', { name: 'Remove', exact: true }).click()
    const confirmation = page.getByRole('dialog', { name: 'Remove development link?' })
    await confirmation.getByLabel('Note (optional)').fill('SYNTHETIC foundational human note')
    // A concurrent edit changes the dialog's CAS values. Retry must keep the note and use the fresh revision.
    const concurrent = await api.put(`${f.base}/lineage/links/${ac.link_id}`, { headers: f.headers, data: {
      relation: ac.relation, what_changed: 'SYNTHETIC edit while removal is open', support_type: ac.support_type,
      evidence: ac.evidence.map(e => ({ passage_id: e.passage_id, quote: e.anchor_text })), expected_version: ac.version, based_on_revision_id: ac.revision_id,
    } })
    expect(concurrent.status()).toBe(200)
    const updated: LineageView = await concurrent.json()
    const updatedLink = updated.components.flatMap(c => c.links).find(l => l.link_id === ac.link_id)!
    const conflict = page.waitForResponse(r => r.request().method() === 'DELETE' && r.url().includes(`/lineage/links/${ac.link_id}`))
    await confirmation.getByRole('button', { name: 'Remove link', exact: true }).click()
    expect((await conflict).status()).toBe(409)
    await expect(confirmation.getByRole('button', { name: 'Remove link', exact: true })).toBeEnabled()
    await expect(confirmation.getByLabel('Note (optional)')).toHaveValue('SYNTHETIC foundational human note')
    const retried = page.waitForRequest(r => r.method() === 'DELETE' && r.url().includes(`/lineage/links/${ac.link_id}`))
    await confirmation.getByRole('button', { name: 'Remove link', exact: true }).click()
    const params = new globalThis.URL((await retried).url()).searchParams
    expect(params.get('expected_version')).toBe(String(updatedLink.version))
    expect(params.get('based_on_revision_id')).toBe(updatedLink.revision_id)
    expect(params.get('note')).toBe('SYNTHETIC foundational human note')
    await expect(confirmation).toHaveCount(0)
    await expect(lines.locator(`[data-link-id="${ac.link_id}"]`)).toHaveCount(0)
    await expect(section(page, 'Works without a placed link')).toContainText('a human removed a link for this work')
    await page.reload(); await openLines(page)
    await expect(section(page, 'Works without a placed link')).toContainText('a human removed a link for this work')
    const cText = await (await api.get(`/api/researches/${f.rid}/assets/${(await (await api.get(`/api/researches/${f.rid}`)).json()).sources.find((s: { source_version_id: string }) => s.source_version_id === f.ids[2]).access.assets[0].id}/text`)).json()
    const quote: string = cText.passages[0].text
    await capture(page, 'add-sheet', async () => { await page.getByRole('button', { name: 'Add link', exact: true }).click(); await picker(page, f.ids[0], f.ids[2], 'SYNTHETIC foundational human change', quote) }, async () => { await page.keyboard.press('Escape'); await expect(page.getByRole('dialog', { name: 'Add development link' })).toHaveCount(0) })
    await page.getByRole('button', { name: 'Add link', exact: true }).click()
    const add = await picker(page, f.ids[0], f.ids[2], 'SYNTHETIC foundational human change', quote)
    await add.getByLabel('Quote 1').fill('SYNTHETIC quote absent from the passage')
    await add.getByRole('button', { name: 'Save link' }).click()
    await expect(add.getByRole('alert')).toContainText('Every quote must be located')
    await expect(add.getByLabel('What changed')).toHaveValue('SYNTHETIC foundational human change')
    await add.getByLabel('Quote 1').fill(quote)
    await add.getByRole('button', { name: 'Save link' }).click()
    await expect(add).toHaveCount(0)
    await expect(section(page, 'Lines')).toContainText('SYNTHETIC foundational human change')
    await expect(section(page, 'Lines')).toContainText('human decision')
    await page.reload(); await openLines(page)
    await expect(section(page, 'Lines')).toContainText('SYNTHETIC foundational human change')
    const restored: LineageView = await (await api.get(`${f.base}/lineage`)).json()
    const restoredLink = restored.components.flatMap(c => c.links).find(l => l.from === f.ids[0] && l.to === f.ids[2])!
    expect((await api.delete(`${f.base}/lineage/links/${restoredLink.link_id}?expected_version=${restoredLink.version}&based_on_revision_id=${encodeURIComponent(restoredLink.revision_id)}`, { headers: f.headers })).ok()).toBe(true)
    await expect(section(page, 'Lines')).not.toContainText('SYNTHETIC foundational human change')
    await page.getByRole('button', { name: 'Add link', exact: true }).click()
    await picker(page, f.ids[0], f.ids[2], 'SYNTHETIC foundational human change', quote)
    // A second tab updates the pair while the first tab retains its original CAS value and typed text.
    const removed: LineageView = await (await api.get(`${f.base}/lineage`)).json()
    const pd = removed.pair_decisions.find(p => p.from === f.ids[0] && p.to === f.ids[2])!
    const body = { from_source_version_id: f.ids[0], to_source_version_id: f.ids[2], relation: 'extends', what_changed: 'SYNTHETIC concurrent change', support_type: 'source_stated', evidence: [{ passage_id: cText.passages[0].id, quote }], expected_version: pd.version }
    expect((await api.post(`${f.base}/lineage/links`, { headers: f.headers, data: body })).status()).toBe(201)
    await add.getByRole('button', { name: 'Save link' }).click()
    await expect(add).toContainText('This pair changed since you opened it')
    await expect(add.getByLabel('What changed')).toHaveValue('SYNTHETIC foundational human change')
    const reloadedText = page.waitForRequest(r => r.url().includes(`/assets/${cText.asset.id}/text`))
    await add.getByRole('button', { name: 'Reload', exact: true }).click()
    await reloadedText
    await expect(add.getByLabel('Quote 1')).toHaveValue(quote)
    await expect(add).toContainText('This pair already has a link; edit it instead')
    await add.getByRole('button', { name: 'Edit', exact: true }).click()
    const edit = page.getByRole('dialog', { name: 'Edit development link' })
    await edit.getByLabel('What changed').fill('SYNTHETIC foundational edited wording')
    await edit.getByRole('button', { name: 'Save link' }).click()
    await expect(page.locator('.lineage-view')).toContainText('SYNTHETIC foundational edited wording')
    await expect(section(page, 'Lines')).toContainText('human decision')
    await expect(section(page, 'Lines')).toContainText('human edited')
    await page.reload(); await openLines(page)
    await expect(section(page, 'Lines')).toContainText('SYNTHETIC foundational edited wording')
    await page.getByRole('button', { name: 'Field baseline', exact: true }).click()
    const baseline = page.locator('.lineage-baseline')
    await expect(baseline).toContainText('Among the works this research included')
    await expect(baseline).toContainText('1 works have no stored count')
    await baseline.getByRole('button', { name: 'Show all 6' }).click()
    await capture(page, 'baseline', undefined, undefined, baseline.getByRole('heading', { name: 'Field baseline', exact: true }))
    await chromeWords(page)
    await page.emulateMedia({ reducedMotion: 'reduce' })
    const action = page.getByRole('button', { name: 'Add link', exact: true })
    await action.focus(); await page.keyboard.press('Enter')
    await expect(page.getByRole('dialog', { name: 'Add development link' })).toBeVisible()
    await page.keyboard.press('Escape'); await expect(action).toBeFocused()
    await page.getByRole('button', { name: 'Türkçe', exact: true }).click()
    await expect(page.getByRole('tab', { name: 'Gelişim çizgileri' })).toBeVisible()
    await expect(page.locator('.lineage-status')).toContainText('Gelişim durum')
    await expect(page.getByRole('button', { name: 'Gelişim bağlarını bul' })).toBeVisible()
  })

  test('a later real run rejects a reverse candidate as a directed cycle', async ({ page }) => {
    const f = await fixture(page, api, '[lineage-reject]')
    await runLinks(page, f)
    let r: ResearchView = await (await api.get(`/api/researches/${f.rid}`)).json()
    const e = r.sources.find(s => s.source_version_id === f.ids[4])!
    expect((await api.patch(`/api/researches/${f.rid}/selections/${e.source_version_id}`, { headers: f.headers, data: { state: 'excluded', expected_version: e.selection.version, reason: 'SYNTHETIC fingerprint change' } })).ok()).toBe(true)
    r = await (await api.get(`/api/researches/${f.rid}`)).json()
    expect((await api.patch(`/api/researches/${f.rid}/selections/${e.source_version_id}`, { headers: f.headers, data: { state: 'included', expected_version: r.sources.find(s => s.source_version_id === e.source_version_id)!.selection.version, reason: 'SYNTHETIC restore' } })).ok()).toBe(true)
    const preview: LineagePlan = await (await api.get(`${f.base}/lineage/plan`)).json()
    expect(preview.selected.some(t => t.to === f.ids[0])).toBe(true)
    const run = await api.post(`${f.base}/lineage/runs`, { headers: f.headers, data: { preview_fingerprint: preview.preview_fingerprint, retry_failed: false } })
    expect(run.status()).toBe(202)
    await waitRun(api, f.rid, 'lineage_links')
    const view: LineageView = await (await api.get(`${f.base}/lineage`)).json()
    expect(view.not_accepted.find(p => p.from === f.ids[1] && p.to === f.ids[0])?.rejection_code).toBe('cycle')
    await expect(section(page, 'Proposals not accepted')).toContainText('the proposed link would close a directed cycle')
    await expect(section(page, 'Proposals not accepted')).toContainText(TITLES[0])
  })

  test('a later work with PDF text and empty cells is addable; events refresh without a table-version bump', async ({ page }) => {
    const f = await fixture(page, api, '[lineage]', false)
    const r: ResearchView = await (await api.get(`/api/researches/${f.rid}`)).json()
    const c = r.sources.find(s => s.source_version_id === f.ids[2])!
    const text = await (await api.get(`/api/researches/${f.rid}/assets/${c.access.assets[0].id}/text`)).json()
    await page.getByRole('button', { name: 'Add link', exact: true }).click()
    const add = await picker(page, f.ids[0], f.ids[2], 'SYNTHETIC manual link before cells', text.passages[0].text)
    await add.getByRole('button', { name: 'Save link' }).click()
    await expect(section(page, 'Lines')).toContainText('human decision')
    const before: TableView = await (await api.get(f.base)).json()
    const view: LineageView = await (await api.get(`${f.base}/lineage`)).json()
    const link = view.components[0].links[0]
    const changed = await api.put(`${f.base}/lineage/links/${link.link_id}`, { headers: f.headers, data: {
      relation: link.relation, what_changed: 'SYNTHETIC external edit noticed through events', support_type: link.support_type,
      evidence: [{ passage_id: link.evidence[0].passage_id, quote: link.evidence[0].anchor_text }], expected_version: link.version, based_on_revision_id: link.revision_id,
    } })
    expect(changed.status()).toBe(200)
    const after: TableView = await (await api.get(f.base)).json()
    expect(after.table.version).toBe(before.table.version)
    await expect(section(page, 'Lines')).toContainText('SYNTHETIC external edit noticed through events')
  })

  test('mocked read model shows every outcome, merge, warning, history and unchecked input in both narrow themes', async ({ page }) => {
    const f = await fixture(page, api, '[lineage]', false)
    const view = renderingView(f)
    await page.route('**/lineage', async route => { expect(route.request().method()).toBe('GET'); await route.fulfill({ json: view }) })
    await page.getByRole('button', { name: 'Refresh', exact: true }).click()
    await expect(section(page, 'Lines')).toContainText('Line · 4 members')
    await headings(page)
    for (const text of ['contains a cycle among stored links', 'also from Work2', 'this version is not the head of its work', 'the later work does not cite the earlier one', 'the later work has an earlier year', 'draft, not structurally validated']) await expect(section(page, 'Lines')).toContainText(text)
    await expect(section(page, 'Independent parallel work')).toContainText('source stated')
    const unplaced = section(page, 'Works without a placed link')
    await expect(unplaced.locator(':scope > ul > li')).toHaveCount(11)
    for (const text of ['no recorded decision for this work yet', 'this work has no stored PDF text', 'no earlier work in this table was found mentioned in its stored text', 'a recorded decision found no relation', 'insufficient evidence for a link', 'a proposal for this work was not accepted', 'candidates were not sent', 'a model call for this work failed', 'a human removed a link', 'only an independent parallel relation', 'only links whose inputs changed']) await expect(unplaced).toContainText(text)
    for (const disclosure of await unplaced.locator('details').all()) await disclosure.locator('summary').click()
    await expect(unplaced).toContainText('not checked: passage text')
    await expect(unplaced).toContainText('not checked: development cell snapshots, passages')
    const rejected = section(page, 'Proposals not accepted')
    await expect(rejected).toContainText('a later decision exists on this pair')
    await expect(rejected).toContainText('unknown_rejection_kept')
    await expect(rejected).toContainText('Recorded pair decision: removed')
    await expect(rejected.getByRole('button', { name: /Accept/ })).toHaveCount(0)
    await expect(section(page, 'Citation edges into unscanned works')).toContainText('has no stored PDF text')
    await expect(section(page, 'Citation edges into unscanned works')).toContainText('has not been through a run')
    const outcomes = section(page, 'Run outcomes')
    await expect(outcomes.locator(':scope > ul > li')).toHaveCount(4)
    for (const text of ['the model call for this pair failed', 'not sent: the call budget or message size did not allow it', "a model call failed for this work's candidates", 'a chunk was skipped when the run stopped']) await expect(outcomes).toContainText(text)
    await expect(outcomes.locator('.lineage-currency').first()).toHaveText('the inputs that were checked are unchanged since; not checked: passage text')
    for (const currency of await outcomes.locator('.lineage-currency').all()) expect(await currency.textContent()).not.toContain('current')
    const history = page.locator('.lineage-view > .lineage-section').filter({ has: page.getByRole('heading', { name: 'History', exact: true }) })
    await expect(history.locator('summary')).toHaveCount(2)
    for (const disclosure of await history.locator(':scope > details').all()) await disclosure.locator('summary').click()
    await expect(history).toContainText('a cited passage is no longer current')
    await expect(history).toContainText('no longer in this table')
    await expect(history.getByRole('button', { name: 'Edit', exact: true })).toHaveCount(2)
    await expect(history).toContainText(view.history.out_of_scope[0].what_changed)
    await page.locator('[data-link-id="lnk_ab"]').getByRole('button', { name: 'Evidence items · 2' }).click()
    await expect(page.locator('[data-link-id="lnk_ab"] blockquote').first()).toHaveText('SYNTHETIC foundational quote exactly kept')
    await expect(page.locator('[data-link-id="lnk_ab"] .lineage-changed')).toHaveText(view.components[0].links[0].what_changed)
    await expect(page.locator('[data-link-id="lnk_ab"]')).toContainText(view.components[0].links[0].note!)
    await chromeWords(page)
    for (const theme of ['light', 'dark']) {
      await page.setViewportSize({ width: 390, height: 844 })
      const dark = await page.locator('html').evaluate(el => el.classList.contains('dark'))
      if (dark !== (theme === 'dark')) await page.getByRole('button', { name: dark ? 'Use light theme' : 'Use dark theme' }).click()
      await expect.poll(() => page.locator('.lineage-view').evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
      await page.screenshot({ path: path.join(OUT, `l7-mocked-390-${theme}.png`), fullPage: true, animations: 'disabled' })
    }
    // The baseline's two unknown-count causes remain separate and never turn into zero.
    const baseline: LineageBaseline = await (await api.get(`${f.base}/lineage/baseline`)).json()
    baseline.most_cited_in_corpus.entries[0].cited_by_included_works = { count: null, other_works: 5, lists_read: 2, target_resolved: false }
    baseline.most_cited_in_corpus.entries[1].cited_by_included_works = { count: null, other_works: 5, lists_read: 0, target_resolved: true }
    baseline.most_cited_in_corpus.shown = baseline.most_cited_in_corpus.entries.slice(0, 5)
    await page.route('**/lineage/baseline', route => route.fulfill({ json: baseline }))
    await page.getByRole('button', { name: 'Field baseline', exact: true }).click()
    await expect(page.locator('.lineage-baseline')).toContainText('not counted: this work could not be matched')
    await expect(page.locator('.lineage-baseline')).toContainText('not counted: no reference list of the other works was read')
  })

  test('retry is always available, empty previews cannot start, zero-call scans can start, and 409 refreshes the plan', async ({ page }) => {
    const f = await fixture(page, api, '[lineage]', false)
    const real: LineagePlan = await (await api.get(`${f.base}/lineage/plan`)).json()
    let previewRequests = 0
    await page.route('**/lineage/plan?**', async route => {
      previewRequests++
      const retry = new globalThis.URL(route.request().url()).searchParams.get('retry_failed') === 'true'
      await route.fulfill({ json: { ...real, calls: 0, max_model_calls: 0, retry_failed: retry, failed_unchanged: [], selected: retry ? [real.selected[0]] : [],
        preview_fingerprint: `synthetic-preview-${previewRequests}`, not_selected: real.not_selected, not_sent_budget: [], counts: { ...real.counts, selected: retry ? 1 : 0, calls: 0, failed_unchanged: 0 } } })
    })
    await page.getByRole('button', { name: 'Find development links' }).click()
    const plan = page.locator('.lineage-plan')
    await expect(plan.getByRole('button', { name: 'Start', exact: true })).toBeDisabled()
    await expect(plan).toContainText('No targets are selected; there is nothing to assess.')
    await page.getByLabel('Retry failed pairs').check()
    await expect(plan).toContainText('1 works will be read')
    await expect(plan).toContainText('0 model calls; the scan is recorded')
    await expect(plan.getByRole('button', { name: 'Start', exact: true })).toBeEnabled()
    await page.getByRole('button', { name: 'Find development links' }).click()
    await expect.poll(() => previewRequests).toBe(3)
    await expect(plan).toContainText('1 works will be read')
    await expect(plan.getByRole('button', { name: 'Start', exact: true })).toBeEnabled()
    let starts = 0
    await page.route('**/lineage/runs', async route => {
      starts++
      const body = route.request().postDataJSON()
      expect(body.retry_failed).toBe(true)
      expect(body.preview_fingerprint).toBe(`synthetic-preview-${previewRequests}`)
      expect(route.request().headers()['idempotency-key']).toMatch(/^[0-9a-f-]{36}$/)
      await route.fulfill({ status: 409, json: { detail: 'SYNTHETIC plan changed; request a new preview' } })
    })
    await plan.getByRole('button', { name: 'Start', exact: true }).click()
    await expect.poll(() => starts).toBe(1)
    await expect.poll(() => previewRequests).toBe(4)
    await expect(page.getByText('SYNTHETIC plan changed; request a new preview', { exact: true })).toBeVisible()
    await expect(plan.getByRole('button', { name: 'Start', exact: true })).toBeEnabled()
    await plan.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(plan).toHaveCount(0)
  })
})
