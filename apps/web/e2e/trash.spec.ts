import { expect, request as apiRequest, test, type Page } from '@playwright/test'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { nextPort } from './ports'

// UI parity S26: the Trash page (mockup T1-T3). One bordered list, newest first; a row is the kind, "title · note",
// Restore and Delete permanently; a delete asks inside its row. Every record here is SYNTHETIC. The mixed list comes
// from a mocked /api/trash (a real one needs a finished search for sources and tables); the real server covers a
// research going to the Trash, coming back and being deleted.

const REPO = path.resolve(process.cwd(), '..', '..')
const PYTHON = path.join(REPO, '.venv', 'bin', 'python')
const SERVER = path.join(REPO, 'tests', 'acceptance', 'fixture_server.py')
const OUT = path.resolve(process.env.DEIXIS_ACCEPTANCE_DIR ?? 'test-results/acceptance')
mkdirSync(OUT, { recursive: true })

class TrashServer {
  private proc?: ChildProcess
  readonly dataDir = mkdtempSync(path.join(tmpdir(), 'deixis-trash-'))
  constructor(readonly port: number) {}
  async start() {
    const env = { PATH: process.env.PATH ?? '', HOME: process.env.HOME ?? '', PYTHONPATH: path.join(REPO, 'backend') }
    this.proc = spawn(PYTHON, [SERVER, '--data-dir', this.dataDir, '--port', String(this.port)], { cwd: REPO, env, stdio: 'inherit' })
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`${this.url()}/api/health`)).ok) return } catch { /* not listening yet */ }
      await new Promise(resolve => setTimeout(resolve, 200))
    }
    throw new Error(`trash fixture server on ${this.port} did not start`)
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
}

type Version = { source_version_id: string; work_id: string; title: string; version_label: string | null; year: number | null; research_id: string; research_title: string
  removed_at: string; removal_note: string | null; found_again_at: string | null; quotes: number; cells: number; abstract_passage_id: string | null; cited: number }
const version = (n: number, over: Partial<Version> = {}): Version => ({
  source_version_id: `sv${n}`, work_id: `w${n}`, title: `SYNTHETIC removed source ${n}`, version_label: 'publishedVersion', year: 2020 + n, research_id: 'r-src',
  research_title: 'SYNTHETIC research that lost sources', removed_at: `2026-10-0${n}T10:00:00Z`, removal_note: null, found_again_at: null, quotes: 0, cells: 0,
  abstract_passage_id: `p${n}`, cited: 0, ...over,
})

// A Trash that holds one of each kind, with dates that fix the order: research, source, table, template.
function mixed() {
  return {
    researches: [{ id: 'r1', title: 'SYNTHETIC trashed research', trashed_at: '2026-10-09T10:00:00Z' }],
    tables: [{ id: 't1', title: 'SYNTHETIC trashed table', research_id: 'r-src', research_title: 'SYNTHETIC research that lost sources', version: 3, trashed_at: '2026-10-07T10:00:00Z', rows: 2, columns: 1, cells: 2, human_edits: 1 }],
    sources: [version(1, { removal_note: 'wrong topic', removed_at: '2026-10-08T10:00:00Z' }), version(2, { removed_at: '2026-10-06T09:00:00Z' }),
      version(3, { title: 'SYNTHETIC cited source', quotes: 2, cited: 1, removed_at: '2026-10-05T09:00:00Z', abstract_passage_id: null })],
    templates: [{ id: 'tp1', name: 'SYNTHETIC trashed template', trashed_at: '2026-10-04T10:00:00Z', columns: 3 }],
  }
}

type Seen = { method: string; url: string; body: string | null }
// Serves /api/trash from `data` and records every other call the page makes to a Trash route; a successful one
// removes the item from `data`, as the server would.
async function mockTrash(page: Page, data: ReturnType<typeof mixed>, seen: Seen[]) {
  await page.route('**/api/trash', route => route.fulfill({ json: data }))
  await page.route(/\/api\/(trash\/|researches\/[^/]+\/(sources|tables)|table-templates\/)/, async route => {
    const request = route.request()
    if (request.method() === 'GET') return route.fallback()
    seen.push({ method: request.method(), url: new URL(request.url()).pathname, body: request.postData() })
    const url = new URL(request.url()).pathname
    const ids = (request.postDataJSON()?.source_version_ids ?? []) as string[]
    data.researches = data.researches.filter(r => !url.endsWith(`/trash/${r.id}`) && !url.endsWith(`/trash/${r.id}/restore`))
    data.tables = data.tables.filter(t => !url.includes(`/${t.id}`))
    data.templates = data.templates.filter(t => !url.includes(`/${t.id}`))
    data.sources = data.sources.filter(s => !ids.includes(s.source_version_id))
    await route.fulfill({ json: url.endsWith('/sources/purge') ? { deleted: ids, files_not_removed: [] } : { restored: true, deleted: true, files_not_removed: [], changed_source_version_ids: ids, cells: 0, human_edits: 0, tables_unlinked: 0 } })
  })
}
const rows = (page: Page) => page.locator('.trash-rows > .trash-row')
const open = async (page: Page, base: string) => { await page.goto(`${base}/#/trash`); await expect(page.locator('.trash-page h1')).toBeVisible() }

test.describe('S26: the Trash page', () => {
  const server = new TrashServer(nextPort())
  test.beforeAll(async () => { await server.start() })
  test.afterAll(async () => { await server.stop() })

  test('one list, newest first, in the mockup order of parts', async ({ page }) => {
    await mockTrash(page, mixed(), [])
    await open(page, server.url())
    await expect(page.locator('.trash-page h1')).toHaveText('Trash')
    // Kinds in date order: research, source, table, source, source, template.
    await expect(rows(page).locator('> b')).toHaveText(['Research', 'Source', 'Evidence table', 'Source', 'Source', 'Table template'])
    const first = rows(page).first()
    await expect(first.locator('p')).toHaveText('SYNTHETIC trashed research · Moved to Trash Oct 9, 2026')
    // Restore, then Delete permanently, then (sources only) the ⋯ menu.
    await expect(first.locator('button')).toHaveText(['Restore', 'Delete permanently'])
    await expect(rows(page).nth(1).locator('button').last()).toHaveAccessibleName(/^Actions for SYNTHETIC removed source 1/)
    await expect(rows(page).nth(1).locator('p')).toContainText('removed from SYNTHETIC research that lost sources on Oct 8, 2026 · Your note: wrong topic')
    await expect(rows(page).nth(2).locator('p')).toContainText('2 rows · 1 column · 2 cells with a value · 1 edit of yours')
    await expect(page.locator('.trash-foot')).toHaveText('Nothing in the Trash expires.')
    // Sizes of the mockup: a 760px list, 20px heading, 12px/14px row padding, 13.5px kind and 12.5px note.
    const box = await page.locator('.trash-rows').boundingBox()
    expect(Math.round(box!.width)).toBe(760)
    expect(await page.locator('.trash-page h1').evaluate(e => getComputedStyle(e).fontSize)).toBe('20px')
    expect(await first.evaluate(e => { const s = getComputedStyle(e); return [s.paddingTop, s.paddingLeft, s.columnGap] })).toEqual(['12px', '14px', '12px'])
    expect(await first.locator('b').evaluate(e => [getComputedStyle(e).fontSize, getComputedStyle(e).fontWeight])).toEqual(['13.5px', '500'])
    expect(await first.locator('p').evaluate(e => getComputedStyle(e).fontSize)).toBe('12.5px')
    // Delete permanently is the danger colour; Restore is not.
    const colour = (loc: ReturnType<Page['locator']>) => loc.evaluate(e => getComputedStyle(e).color)
    expect(await colour(first.getByRole('button', { name: /^Delete permanently/ }))).not.toBe(await colour(first.getByRole('button', { name: /^Restore/ })))
    await page.screenshot({ path: path.join(OUT, 'S26-trash-desktop.png'), animations: 'disabled' })
    await page.setViewportSize({ width: 390, height: 844 })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.screenshot({ path: path.join(OUT, 'S26-trash-mobile.png'), animations: 'disabled' })
  })

  test('an empty Trash says so and keeps the foot line', async ({ page }) => {
    await mockTrash(page, { researches: [], tables: [], sources: [], templates: [] }, [])
    await open(page, server.url())
    await expect(page.getByRole('heading', { name: 'The Trash is empty' })).toBeVisible()
    await expect(page.locator('.trash-empty p')).toHaveText('Research and sources you remove wait here until you restore or delete them.')
    await expect(page.locator('.trash-foot')).toHaveText('Nothing in the Trash expires.')
    await expect(rows(page)).toHaveCount(0)
  })

  test('Restore on each kind calls its own route and the row leaves', async ({ page }) => {
    const seen: Seen[] = []
    await mockTrash(page, mixed(), seen)
    await open(page, server.url())
    for (const [kind, title] of [['Research', 'SYNTHETIC trashed research'], ['Evidence table', 'SYNTHETIC trashed table'], ['Table template', 'SYNTHETIC trashed template'], ['Source', 'SYNTHETIC removed source 1']]) {
      const row = rows(page).filter({ has: page.locator('b', { hasText: new RegExp(`^${kind}$`) }), hasText: title })
      await row.getByRole('button', { name: /^Restore/ }).click()
      await expect(row).toHaveCount(0)
    }
    expect(seen.map(s => `${s.method} ${s.url}`)).toEqual([
      'POST /api/trash/r1/restore', 'POST /api/researches/r-src/tables/t1/restore', 'POST /api/table-templates/tp1/restore', 'POST /api/researches/r-src/sources/restore'])
    expect(JSON.parse(seen[3].body ?? '{}')).toEqual({ source_version_ids: ['sv1'] })
  })

  test('Delete permanently asks in the row, says what goes, and Cancel and Escape keep the item', async ({ page }) => {
    const seen: Seen[] = []
    await mockTrash(page, mixed(), seen)
    await open(page, server.url())
    const notice = page.locator('.trash-notice')
    await rows(page).first().getByRole('button', { name: /^Delete permanently/ }).click()
    await expect(notice).toHaveCount(1)
    await expect(rows(page)).toHaveCount(6)  // the row is replaced, not joined by a dialog
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(notice).toContainText('Delete “SYNTHETIC trashed research” permanently?')
    await expect(notice).toContainText('Its answers, decisions, run history, unshared evidence and files go with it.')
    await expect(notice).toContainText('items you saved to the library stay')  // S19a: purging keeps what the person saved
    await expect(notice).toContainText('This cannot be undone.')
    await expect(notice.getByRole('button')).toHaveText(['Delete permanently', 'Cancel'])
    await page.screenshot({ path: path.join(OUT, 'S26-trash-confirm.png'), animations: 'disabled' })
    await notice.getByRole('button', { name: 'Cancel' }).click()
    await expect(notice).toHaveCount(0)
    await rows(page).first().getByRole('button', { name: /^Delete permanently/ }).click()
    await page.keyboard.press('Escape')
    await expect(notice).toHaveCount(0)
    await expect(rows(page).first().locator('b')).toHaveText('Research')
    expect(seen).toEqual([])
  })

  test('each kind is deleted through its own route; a source says its library record goes unless saved', async ({ page }) => {
    const seen: Seen[] = []
    await mockTrash(page, mixed(), seen)
    await open(page, server.url())
    const del = async (kind: string, title: string, extra?: (text: string) => void) => {
      const row = rows(page).filter({ has: page.locator('b', { hasText: new RegExp(`^${kind}$`) }), hasText: title })
      await row.getByRole('button', { name: /^Delete permanently/ }).click()
      const notice = page.locator('.trash-notice')
      extra?.((await notice.textContent()) ?? '')
      await notice.getByRole('button', { name: 'Delete permanently' }).click()
      await expect(page.locator('.trash-notice')).toHaveCount(0)
      await expect(row).toHaveCount(0)
    }
    await del('Research', 'SYNTHETIC trashed research')
    await del('Evidence table', 'SYNTHETIC trashed table', text => expect(text).toContain('Passages, files and answers stay.'))
    await del('Table template', 'SYNTHETIC trashed template', text => expect(text).toContain('Tables started from it keep their own columns.'))
    await del('Source', 'SYNTHETIC removed source 1', text => {
      expect(text).toContain('The research loses its record of this source, your decision and notes on it.')
      expect(text).toContain('unless another research holds it or you saved it to the library')
    })
    expect(seen.map(s => `${s.method} ${s.url}`)).toEqual([
      'DELETE /api/trash/r1', 'DELETE /api/trash/tables/t1', 'DELETE /api/trash/templates/tp1', 'POST /api/researches/r-src/sources/purge'])
    expect(JSON.parse(seen[3].body ?? '{}')).toEqual({ source_version_ids: ['sv1'] })
    await expect(page.locator('.trash-message')).toHaveText('Source permanently deleted.')
  })

  test('a still-cited source cannot be deleted and says why; the ⋯ menu restores or deletes the research\'s sources together', async ({ page }) => {
    const seen: Seen[] = []
    await mockTrash(page, mixed(), seen)
    await open(page, server.url())
    const cited = rows(page).filter({ hasText: 'SYNTHETIC cited source' })
    await expect(cited.locator('p')).toContainText('cited in 2 answer quotes; deleted with its research')
    await expect(cited.getByRole('button', { name: /^Delete permanently/ })).toBeDisabled()
    // The menu of a source offers its tools; the cited one cannot be bulk-deleted.
    await rows(page).filter({ hasText: 'SYNTHETIC removed source 2' }).getByRole('button', { name: /^Actions for/ }).click()
    await expect(page.getByRole('menuitem')).toHaveText(['Open source details', 'Restore all from this research', 'Delete all deletable from this research permanently'])
    await page.getByRole('menuitem', { name: /^Delete all deletable/ }).click()
    const notice = page.locator('.trash-notice')
    await expect(notice).toContainText('Delete 2 sources removed from “SYNTHETIC research that lost sources” permanently?')
    await notice.getByRole('button', { name: 'Delete permanently' }).click()
    await expect(page.locator('.trash-message')).toHaveText('2 sources permanently deleted.')
    expect(JSON.parse(seen[0].body ?? '{}')).toEqual({ source_version_ids: ['sv1', 'sv2'] })
    await expect(rows(page).filter({ hasText: 'SYNTHETIC cited source' })).toHaveCount(1)
  })

  // Two researches lost sources: A has a, b (b cited), B has c. Titles and years fix the sorts.
  const twoResearches = () => {
    const data = mixed()
    data.researches = []; data.tables = []; data.templates = []
    data.sources = [
      version(1, { title: 'Alpha source', year: 2019, research_id: 'rA', research_title: 'SYNTHETIC research A', removed_at: '2026-10-01T10:00:00Z' }),
      version(2, { title: 'Charlie source', year: 2023, research_id: 'rA', research_title: 'SYNTHETIC research A', removed_at: '2026-10-03T10:00:00Z', cited: 1, quotes: 1 }),
      version(3, { title: 'Bravo source', year: 2021, research_id: 'rB', research_title: 'SYNTHETIC research B', removed_at: '2026-10-02T10:00:00Z' }),
    ]
    return data
  }
  const titles = (page: Page) => page.locator('.trash-rows .trash-row:not(.trash-group-head) > p').evaluateAll(ps => ps.map(p => (p.textContent ?? '').split(' · ')[0]))

  test('filter, scope, research and sort narrow the list; the filter field stays while a query applies', async ({ page }) => {
    await mockTrash(page, twoResearches(), [])
    await open(page, server.url())
    expect(await titles(page)).toEqual(['Charlie source', 'Bravo source', 'Alpha source'])  // recently removed
    await page.getByRole('combobox', { name: /Sort/ }).click()
    await page.getByRole('option', { name: 'Title' }).click()
    expect(await titles(page)).toEqual(['Alpha source', 'Bravo source', 'Charlie source'])
    await page.getByRole('combobox', { name: /Sort/ }).click()
    await page.getByRole('option', { name: 'Year' }).click()
    expect(await titles(page)).toEqual(['Charlie source', 'Bravo source', 'Alpha source'])
    await page.getByRole('button', { name: /^Deletable/ }).click()
    expect(await titles(page)).toEqual(['Bravo source', 'Alpha source'])
    await page.getByRole('button', { name: /^Still cited/ }).click()
    expect(await titles(page)).toEqual(['Charlie source'])
    await page.getByRole('button', { name: /^All/ }).click()
    await page.getByRole('combobox', { name: /Research/ }).click()
    await page.getByRole('option', { name: 'SYNTHETIC research B' }).click()
    expect(await titles(page)).toEqual(['Bravo source'])
    await page.getByRole('combobox', { name: /Research/ }).click()
    await page.getByRole('option', { name: /^All 2 research/ }).click()
    await page.getByRole('searchbox', { name: 'Filter the Trash' }).fill('alpha')
    expect(await titles(page)).toEqual(['Alpha source'])
  })

  test('group by research folds a research\'s sources; a choice across researches restores and deletes per research', async ({ page }) => {
    const seen: Seen[] = []
    await mockTrash(page, twoResearches(), seen)
    await open(page, server.url())
    await page.getByRole('button', { name: 'Group by research' }).click()
    await expect(page.locator('.trash-group-head > b')).toHaveText(['SYNTHETIC research A', 'SYNTHETIC research B'])
    await page.getByRole('button', { name: 'Hide the sources removed from SYNTHETIC research A' }).click()
    expect(await titles(page)).toEqual(['Bravo source'])  // A's rows folded away
    await page.getByRole('button', { name: 'Show the sources removed from SYNTHETIC research A' }).click()
    // Pick one source of each research (the cited one too), restore: one call per research.
    await page.getByRole('checkbox', { name: 'Select Alpha source' }).check()
    await page.getByRole('checkbox', { name: 'Select Charlie source' }).check()
    await page.getByRole('checkbox', { name: 'Select Bravo source' }).check()
    const bar = page.locator('.selection-bar')
    await expect(bar).toContainText('3 sources selected')
    await expect(bar).toContainText('2 deletable · from 2 research')
    await bar.getByRole('button', { name: 'Clear selection' }).click()
    await expect(bar).toHaveCount(0)
    await page.getByRole('checkbox', { name: 'Select Alpha source' }).check()
    await page.getByRole('checkbox', { name: 'Select Bravo source' }).check()
    // Delete asks first; Cancel returns focus to the bar's Delete button.
    await bar.getByRole('button', { name: 'Delete permanently' }).click()
    const notice = page.locator('.trash-bar-notice')
    await expect(notice).toContainText('Delete 2 sources permanently?')
    await notice.getByRole('button', { name: 'Cancel' }).click()
    await expect(bar.getByRole('button', { name: 'Delete permanently' })).toBeFocused()
    await bar.getByRole('button', { name: 'Restore' }).click()
    await expect(page.locator('.trash-message')).toHaveText('2 sources restored.')
    expect(seen.map(s => s.url).sort()).toEqual(['/api/researches/rA/sources/restore', '/api/researches/rB/sources/restore'])
    expect(await titles(page)).toEqual(['Charlie source'])
  })

  test('a selection across researches is deleted one call per research', async ({ page }) => {
    const seen: Seen[] = []
    const data = twoResearches()
    data.sources[1].cited = 0
    await mockTrash(page, data, seen)
    await open(page, server.url())
    await page.getByRole('checkbox', { name: 'Select the 3 sources shown here' }).check()
    const bar = page.locator('.selection-bar')
    await bar.getByRole('button', { name: 'Delete permanently' }).click()
    await page.locator('.trash-bar-notice').getByRole('button', { name: 'Delete permanently' }).click()
    await expect(page.locator('.trash-message')).toHaveText('3 sources permanently deleted.')
    expect(seen.map(s => s.url).sort()).toEqual(['/api/researches/rA/sources/purge', '/api/researches/rB/sources/purge'])
    expect(seen.flatMap(s => JSON.parse(s.body ?? '{}').source_version_ids).sort()).toEqual(['sv1', 'sv2', 'sv3'])
  })

  test('Cancel and Escape return focus to the row\'s Delete permanently', async ({ page }) => {
    await mockTrash(page, mixed(), [])
    await open(page, server.url())
    const first = rows(page).first()
    await first.getByRole('button', { name: /^Delete permanently/ }).click()
    await page.locator('.trash-notice').getByRole('button', { name: 'Cancel' }).click()
    await expect(first.getByRole('button', { name: /^Delete permanently/ })).toBeFocused()
    await first.getByRole('button', { name: /^Delete permanently/ }).click()
    await page.keyboard.press('Escape')
    await expect(first.getByRole('button', { name: /^Delete permanently/ })).toBeFocused()
  })

  test('with 51 rows the filter stays after a restore leaves 50 and Show more is gone', async ({ page }) => {
    const data = mixed()
    data.researches = []; data.tables = []; data.sources = []
    data.templates = Array.from({ length: 51 }, (_, i) => ({ id: `tp${i}`, name: `SYNTHETIC template ${String(i).padStart(2, '0')}`, trashed_at: `2026-09-${String((i % 28) + 1).padStart(2, '0')}T10:00:00Z`, columns: 1 }))
    await mockTrash(page, data, [])
    await open(page, server.url())
    await expect(rows(page)).toHaveCount(50)
    await expect(page.getByRole('button', { name: 'Show 1 more' })).toBeVisible()
    const field = page.getByRole('searchbox', { name: 'Filter the Trash' })
    await field.fill('template 0')
    const count = await rows(page).count()
    expect(count).toBe(10)
    await rows(page).first().getByRole('button', { name: /^Restore/ }).click()
    await expect(rows(page)).toHaveCount(9)
    await expect(field).toHaveValue('template 0')
    await field.fill('')
    await expect(rows(page)).toHaveCount(50)
    await expect(page.getByRole('button', { name: /^Show \d+ more/ })).toHaveCount(0)
  })

  test('the Turkish delete confirmation keeps a source when either protection holds', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('deixis-ui-language', 'tr'))
    await mockTrash(page, mixed(), [])
    await open(page, server.url())
    await rows(page).filter({ hasText: 'SYNTHETIC removed source 2' }).locator('.trash-delete').click()
    const text = (await page.locator('.trash-notice').textContent()) ?? ''
    expect(text).toContain('tutmuyorsa ve kütüphaneye kaydetmediyseniz')
    expect(text).not.toContain('ya da kütüphaneye kaydetmediyseniz')
    await page.locator('.trash-notice').getByRole('button', { name: 'İptal et' }).click()
    await rows(page).filter({ hasText: 'SYNTHETIC removed source 2' }).locator('.trash-sq').click()
    await page.getByRole('menuitem', { name: /silinebilir/ }).click()
    expect((await page.locator('.trash-notice').textContent()) ?? '').toContain('tutmuyorsa ve kütüphaneye kaydetmediyseniz')
  })

  test('on the real server a research goes to the Trash, comes back, and is deleted after a Cancel', async ({ page }) => {
    const api = await apiRequest.newContext({ baseURL: server.url(), extraHTTPHeaders: { origin: server.url() } })
    const token = (await (await api.get('/api/session')).json()).csrf_token as string
    const created = await api.post('/api/researches', { data: { question: 'SYNTHETIC trash page research', model_connection: 'codex', requested_model: 'fixture-model', effort: 'quick' }, headers: { 'x-deixis-csrf': token } })
    expect(created.status()).toBe(201)
    const id = (await created.json()).research.id as string
    expect((await api.delete(`/api/researches/${id}`, { headers: { 'x-deixis-csrf': token } })).ok()).toBe(true)
    await open(page, server.url())
    const row = rows(page).filter({ hasText: 'SYNTHETIC trash page research' })
    await expect(row.locator('b')).toHaveText('Research')
    await row.getByRole('button', { name: /^Restore/ }).click()
    await expect(page.locator('.trash-message')).toHaveText('Research restored.')
    await expect(row).toHaveCount(0)
    expect((await api.get(`/api/researches/${id}`)).ok()).toBe(true)
    expect((await api.delete(`/api/researches/${id}`, { headers: { 'x-deixis-csrf': token } })).ok()).toBe(true)
    await page.reload()
    await row.getByRole('button', { name: /^Delete permanently/ }).click()
    await page.locator('.trash-notice').getByRole('button', { name: 'Cancel' }).click()
    await expect(row).toHaveCount(1)
    await row.getByRole('button', { name: /^Delete permanently/ }).click()
    await page.locator('.trash-notice').getByRole('button', { name: 'Delete permanently' }).click()
    await expect(page.locator('.trash-message')).toHaveText('Research permanently deleted.')
    expect((await api.get(`/api/researches/${id}`)).status()).toBe(404)
    await api.dispose()
  })
})
