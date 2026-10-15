import { useEffect, useRef, useState } from 'react'
import { ArrowUpDown, Download, Filter, Info, LibraryBig, ListChecks, ListMinus, ListPlus, Search, Table2 } from 'lucide-react'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from '@/components/ui/select'
import { api, type Effort, type EffortLimits, type Source, type TableSummary, type UnscreenedWork } from '../api'
import { accessParts, tableTitle, versionText } from '../labels'
import { t, uiLocale } from '../i18n'
import { useToast } from '../Toast'
import { effortLabels } from '../Home'
import { SCREEN_MORE_SIZE, useScreenMore, useUnscreened } from './unscreened'
import { focusWhenLost } from '../focus'
import { SourceRow } from './SourceRow'
import { proposalOf } from './sourceProposal'
import type { OcrContext } from './shared'

// The Sources panel (mockup P5, P6, P8, P9, P10; UI parity S13): filter tabs with counts, the toolbar, the exclusion
// reason bar, the source table and the selection bar. Rows, counts and the CSV all come from `sources`, the list the
// view holds: every tab count is the number of works that tab lists. Other versions of a work follow their record's line
// and count with it (versions of one work count once). "Not read" (P5, P7; S27) lists the never-screened works of the
// ranked list from their own route, in that list's order, and its count is that route's total; its notice queues
// "Screen N more", which never includes a source by itself.
type SourceSort = 'relevant' | 'found' | 'cited' | 'newest' | 'oldest' | 'title'
const sourceSorts: Record<SourceSort, string> = { relevant: 'Most relevant', found: 'Order found', cited: 'Most cited', newest: 'Newest first', oldest: 'Oldest first', title: 'Title A–Z' }
// Search position is not comparable across queries: the model's screening verdict decides, then similarity to the question
// when semantic search scored the source (D30), then the best position in the searches that found it.
const verdictOrder: Record<string, number> = { include: 0, passed: 1, uncertain: 2, none: 3, exclude: 4 }
const verdictRank = (s: Source) => verdictOrder[proposalOf(s)?.tone ?? 'none'] ?? 3
// "Cited in answer" lists the works the answer shown in the thread cites, from that answer's stored claims. A cited work
// since removed from the research is not in `sources`, so the tab says how many it leaves out. "Passed abstract" holds the
// undecided works whose current decision is the abstract stage's `candidate` (the funnel's rule) and that no person set;
// "Undecided" holds the other undecided works, so Included, Passed abstract, Undecided and Excluded add up to All.
const stateFilters = [['cited', 'Cited in answer'], ['included', 'Included'], ['passed', 'Passed abstract'], ['pending', 'Undecided'], ['excluded', 'Excluded'], ['notread', 'Not read'], ['all', 'All']] as const
export type StateFilter = typeof stateFilters[number][0]
type PdfFilter = 'all' | 'with_pdf' | 'without_pdf'
const pdfFilterLabels: Record<PdfFilter, string> = { all: 'All', with_pdf: 'PDF attached', without_pdf: 'No PDF' }
// Sources without the value (no year, no citation count) go last in either direction.
const byNumber = (a: number | null, b: number | null, dir: 1 | -1) => a === null ? (b === null ? 0 : 1) : b === null ? -1 : dir * (a - b)
const sourceCompare: Record<SourceSort, (a: Source, b: Source) => number> = {
  found: () => 0,
  relevant: (a, b) => verdictRank(a) - verdictRank(b) || byNumber(a.similarity, b.similarity, -1) || byNumber(a.rank, b.rank, 1),
  cited: (a, b) => byNumber(a.cited_by_count, b.cited_by_count, -1),
  newest: (a, b) => byNumber(a.year, b.year, -1),
  oldest: (a, b) => byNumber(a.year, b.year, 1),
  title: (a, b) => a.title.localeCompare(b.title),
}
const passedAbstract = (s: Source) => s.selection.state === 'pending' && s.selection.origin !== 'user' && s.screening?.stage === 'abstract' && s.screening.passed_abstract
const tabOf = (s: Source): Exclude<StateFilter, 'cited' | 'all' | 'notread'> => passedAbstract(s) ? 'passed' : s.selection.state

export type SourceActions = { onRemoveFromResearch: (source: Source) => void; onSelect: (source: Source, state: Source['selection']['state']) => void; onReason: (source: Source, reason: string) => Promise<boolean>; onOpen: (source: Source) => void; onAbstract: (source: Source) => void; onDiscoverPdf: (source: Source) => void; onAttachPdf: (source: Source) => void; onAttachCandidate: (source: Source, candidateId: string) => void; onOpenPdf: (source: Source, assetId: string) => void; onPlainText: (source: Source, assetId: string) => void; onRemoveAsset: (source: Source, assetId: string) => void; onReplaceAsset: (source: Source, assetId: string) => void; onReextract: (source: Source, assetId: string) => void; onRereadEquations: (source: Source, assetId: string) => void; pdfFinding: string[]; ocr: OcrContext }
type BarActions = { researchId: string; active: boolean; onStartTable: (ids: string[]) => void; onAddToTable: (table: TableSummary, ids: string[]) => void; onRemove: (ids: string[]) => void; onSaveToLibrary: (ids: string[]) => Promise<void> }

// A text cell that starts like a formula (= + - @ tab CR) gets a leading ' so a spreadsheet shows it as text, never runs it.
const csvQuote = (v: string | number | null | undefined) => { const text = v == null ? '' : typeof v === 'string' && /^[=+\-@\t\r]/.test(v) ? `'${v}` : String(v); return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text }
const stateWords: Record<Source['selection']['state'], string> = { included: 'Included', pending: 'Undecided', excluded: 'Excluded' }
// The rows shown, as a CSV a spreadsheet opens (BOM for UTF-8): one line per row, versions on their own lines.
function downloadCsv(rows: Source[]) {
  const head = [t('Key'), t('Title'), t('Authors'), t('Year'), t('Venue'), t('DOI'), t('Version'), t('Access'), t('Model proposal'), t('Your decision'), t('Your reason')]
  const lines = rows.map(s => { const p = proposalOf(s); return [s.source_key ?? '', s.title, s.authors.join('; '), s.year, s.venue, s.doi, versionText(s.version_label), accessParts(s).map(part => part.text).join(' · '),
    p ? [p.word, p.reason].filter(Boolean).join(' · ') : '', s.version_role === 'other_version' ? '' : t(stateWords[s.selection.state]), s.selection.user_reason ?? ''] })
  const url = URL.createObjectURL(new Blob([`﻿${[head, ...lines].map(line => line.map(csvQuote).join(',')).join('\r\n')}\r\n`], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = 'deixis-sources.csv'
  link.click()
  URL.revokeObjectURL(url)
}

export function SourcesPanel({ sources, cited, citedVersions, answerVersion, busy, filter, onFilter, focus, onFocus, picked, onPick, bar, cursor, effort, onChanged, ...a }: { sources: Source[]; cited: ReadonlyMap<string, number>; citedVersions: ReadonlyMap<string, number>; answerVersion: number | null; busy: boolean; filter: StateFilter; onFilter: (filter: StateFilter) => void; focus: string | null; onFocus: (workId: string | null) => void; picked: string[]; onPick: (ids: string[]) => void; bar: BarActions
  cursor: number; effort: Effort; onChanged: () => Promise<unknown> } & SourceActions) {
  const toast = useToast()
  const unscreened = useUnscreened(bar.researchId, cursor)
  const { screening, screenMore } = useScreenMore(bar.researchId, toast, () => Promise.all([onChanged(), unscreened.reload()]))
  const [limits, setLimits] = useState<EffortLimits | null>(null)
  useEffect(() => { api.effortLimits().then(setLimits, () => setLimits(null)) }, [])
  const [pdfFilter, setPdfFilter] = useState<PdfFilter>('all')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<SourceSort>('relevant')
  // The exclusion reason bar (mockup .why-bar): one source at a time, opened by Exclude, "Add a reason" or Edit.
  const [asking, setAsking] = useState<{ id: string; text: string; opener: HTMLElement | null } | null>(null)
  const [saving, setSaving] = useState(false)
  const field = useRef<HTMLInputElement>(null)
  // Other versions follow their record and move with it; the filter and sort look at the record.
  const families: Source[][] = []
  for (const source of sources) {
    const last = families[families.length - 1]
    if (source.version_role === 'other_version' && last?.[0].work_id === source.work_id) last.push(source)
    else families.push([source])
  }
  const isCited = (family: Source[]) => cited.has(family[0].work_id)
  const counts: Record<Exclude<StateFilter, 'notread'>, number> = { cited: families.filter(isCited).length, included: 0, passed: 0, pending: 0, excluded: 0, all: families.length }
  families.forEach(([record]) => counts[tabOf(record)]++)
  const citedRemoved = Math.max(0, cited.size - counts.cited)
  const hasPdf = (family: Source[]) => family.some(source => source.access.assets.length > 0)
  const pdfCounts = { all: families.length, with_pdf: families.filter(hasPdf).length, without_pdf: families.filter(family => !hasPdf(family)).length }
  const needle = query.trim().toLocaleLowerCase()
  const matches = (s: Source) => [s.title, s.venue, s.doi, s.year === null ? null : String(s.year), ...s.authors].some(text => text?.toLocaleLowerCase().includes(needle))
  const focused = focus ? families.filter(f => f[0].work_id === focus) : null
  const passes = (f: Source[]) => (pdfFilter === 'all' || (pdfFilter === 'with_pdf' ? hasPdf(f) : !hasPdf(f))) && (!needle || f.some(matches))
  // "Not read": the route's rows in the ranked list's order (the sort does not apply), each the work's family in this
  // research; a listed work this page does not hold (removed since) is shown from the route's own fields.
  const byWork = new Map(families.map(f => [f[0].work_id, f]))
  const notRead = filter === 'notread' && !focused
  const notReadRows = notRead ? unscreened.items.map(item => ({ item, family: byWork.get(item.work_id) ?? null }))
    .filter(({ item, family }) => family ? passes(family) : (pdfFilter !== 'with_pdf' && (!needle || [item.title, item.venue, item.doi].some(text => text?.toLocaleLowerCase().includes(needle))))) : []
  const shown = focused ?? (notRead ? notReadRows.flatMap(row => row.family ? [row.family] : [])
    : families.filter(f => (filter === 'all' || (filter === 'cited' ? isCited(f) : tabOf(f[0]) === filter)) && passes(f)).sort((x, y) => sourceCompare[sort](x[0], y[0])))
  const shownRows = shown.flat()
  const shownIds = shownRows.map(s => s.source_version_id)
  const allShownPicked = shownIds.length > 0 && shownIds.every(sid => picked.includes(sid))
  const togglePick = (sid: string, on: boolean) => onPick(on ? [...picked, sid] : picked.filter(p => p !== sid))
  const askedSource = asking ? sources.find(s => s.source_version_id === asking.id) : undefined
  // The bar shows only while its source is one you excluded (not after another decision, a removal or a failed request).
  const barShown = Boolean(asking && askedSource?.selection.origin === 'user' && askedSource.selection.state === 'excluded')
  // The field takes focus only if focus is still on the control that opened it or has fallen to the page body (the
  // Exclude button is disabled once the choice is saved); it is never taken from another control.
  const opener = asking?.opener
  useEffect(() => {
    if (barShown && (document.activeElement === opener || document.activeElement === document.body || !document.activeElement)) field.current?.focus()
  }, [barShown, opener])
  const clearAll = () => { onFilter('all'); setPdfFilter('all'); setQuery(''); onFocus(null) }
  const select = (source: Source, state: Source['selection']['state'], button: HTMLElement) => {
    // A new choice is saved without a reason (an earlier reason does not carry over), so Exclude always asks for one.
    if (state === 'excluded') setAsking({ id: source.source_version_id, text: '', opener: button })
    else if (asking?.id === source.source_version_id) setAsking(null)
    a.onSelect(source, state)
  }
  const saveReason = async () => {
    if (!askedSource || !asking?.text.trim()) return
    const id = askedSource.source_version_id
    setSaving(true)
    try {
      if (await a.onReason(askedSource, asking.text.trim())) {
        setAsking(null)
        focusWhenLost(() => document.querySelector<HTMLElement>(`[data-reason-for="${CSS.escape(id)}"]`))
      }
    } finally { setSaving(false) }
  }
  if (!sources.length) return <p className="empty-inline sources-empty">{t('No sources yet.')}</p>
  return <div className="sources-table-block">
    {/* Filter tabs (mockup .tabs): an underline strip, one count per tab. */}
    <div className="tabs source-filters" role="group" aria-label={t('Show sources')}>
      {stateFilters.map(([key, label]) => <button key={key} type="button" aria-pressed={!focused && filter === key} className={!focused && filter === key ? 'on' : undefined} onClick={() => { onFocus(null); onFilter(key) }}>{t(label)}<em className="tnum" title={key === 'notread' && !unscreened.page ? t('Not known: the never-screened list is not read') : undefined}>{key === 'notread' ? (unscreened.page ? unscreened.page.total.toLocaleString() : '–') : counts[key]}</em></button>)}
    </div>
    {/* Toolbar (mockup .toolbar): search, Sort, PDF filter, Download, Save to library. */}
    <div className="toolbar source-toolbar">
      <label className="search source-search"><Search size={14} aria-hidden /><input type="search" aria-label={t('Filter sources')} placeholder={t('Search…')} value={query} onChange={e => { onFocus(null); setQuery(e.target.value) }} /></label>
      {/* "Not read" keeps the ranked list's stored order, so Sort is off there and says which order is shown. */}
      <Select value={sort} disabled={notRead} onValueChange={value => { if (value) setSort(value as SourceSort) }}>
        <SelectTrigger className={`ghost source-sort${sort !== 'relevant' && !notRead ? ' tint' : ''}`} aria-label={t('Sort sources')} title={notRead ? t('The never-screened works keep the ranked list’s stored order; sorting does not apply to them.') : undefined}><SelectValue>{(value: string) => <><ArrowUpDown size={14} aria-hidden />{notRead ? t('Ranked list order') : t(sourceSorts[value as SourceSort])}</>}</SelectValue></SelectTrigger>
        <SelectContent className="source-menu" align="start" alignItemWithTrigger={false}>
          <SelectGroup><SelectLabel>{t('Sort')}</SelectLabel>
            {(Object.keys(sourceSorts) as SourceSort[]).map(k => <SelectItem key={k} value={k}>{k === 'relevant' ? <span className="sort-option">{t(sourceSorts[k])}<small>{t('Screening result first, then similarity to the question, then search position')}</small></span> : t(sourceSorts[k])}</SelectItem>)}
          </SelectGroup>
        </SelectContent>
      </Select>
      <Select value={pdfFilter} onValueChange={value => { if (value) { onFocus(null); setPdfFilter(value as PdfFilter) } }}>
        <SelectTrigger className={`ghost source-pdf-filter${pdfFilter !== 'all' ? ' tint' : ''}`} aria-label={t('Filter sources by PDF availability')}><SelectValue>{(value: string) => <><Filter size={14} aria-hidden />{t('PDF: {filter}', { filter: t(pdfFilterLabels[value as PdfFilter]) })}</>}</SelectValue></SelectTrigger>
        <SelectContent className="source-menu" align="start" alignItemWithTrigger={false}>
          <SelectGroup><SelectLabel>PDF</SelectLabel>
            {(Object.keys(pdfFilterLabels) as PdfFilter[]).map(k => <SelectItem key={k} value={k}><span className="source-filter-option"><span>{t(pdfFilterLabels[k])}</span><small className="tnum">{pdfCounts[k]}</small></span></SelectItem>)}
          </SelectGroup>
        </SelectContent>
      </Select>
      <button type="button" className="ghost" disabled={!shownRows.length} onClick={() => downloadCsv(shownRows)} title={t(shownRows.length === 1 ? 'Download the {n} row shown as CSV' : 'Download the {n} rows shown as CSV', { n: shownRows.length })}><Download size={14} aria-hidden />{t('Download')}</button>
      <button type="button" className="ghost" disabled={busy || !shownRows.length} onClick={() => { void bar.onSaveToLibrary(shownIds) }} title={t(shownRows.length === 1 ? 'Save the {n} row shown to the Library' : 'Save the {n} rows shown to the Library', { n: shownRows.length })}><LibraryBig size={14} aria-hidden />{t('Save to library')}</button>
    </div>
    {notRead && <NotReadNotice unscreened={unscreened} effort={effort} limits={limits} busy={busy} active={bar.active} screening={screening} onScreenMore={() => { void screenMore() }} />}
    {!focused && filter === 'cited' && citedRemoved > 0 && <p className="source-focus source-cited-scope">{t(citedRemoved === 1 ? 'The answer also cites {n} work since removed from this research. It is not listed here; its quotes still open from the report.' : 'The answer also cites {n} works since removed from this research. They are not listed here; their quotes still open from the report.', { n: citedRemoved })}</p>}
    {focused && <p className="source-focus">{t('Showing the one work the audit sample sent you to.')} <button type="button" onClick={clearAll}>{t('Show all sources')}</button></p>}
    {/* The exclusion reason bar (mockup .why-bar), above the table. */}
    {barShown && asking && askedSource && <form className="why-bar" onSubmit={e => { e.preventDefault(); void saveReason() }}>
      <div className="why-f">
        <label className="lbl"><span><b>{askedSource.title}</b> {t('excluded. Why exclude it? Optional; kept with your choice.')}</span>
          <input ref={field} className="field" aria-label={t('Reason for excluding this source')} maxLength={1000} value={asking.text} onChange={e => setAsking({ ...asking, text: e.target.value })} /></label>
        <button type="submit" className="btn-pri" disabled={busy || saving || !asking.text.trim()}>{t('Save reason')}</button>
        <button type="button" className="ghost" onClick={() => setAsking(null)}>{t('Skip')}</button>
      </div>
    </form>}
    {/* Chrome leaves a partly visible focused control where it is; the whole control comes into the table's view. */}
    <div className="tbl-wrap" onFocus={e => e.target.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })}><table className="source-table">
      <thead><tr>
        <th className="cb"><input type="checkbox" aria-label={t('Select all shown')} checked={allShownPicked} disabled={!shownIds.length}
          ref={node => { if (node) node.indeterminate = !allShownPicked && shownIds.some(sid => picked.includes(sid)) }}
          onChange={e => onPick(e.target.checked ? [...new Set([...picked, ...shownIds])] : picked.filter(sid => !shownIds.includes(sid)))} /></th>
        <th scope="col">{t('Source')} <span className="th-count tnum">({shown.length})</span></th>
        <th scope="col">{t('Model proposal')}</th>
        <th scope="col">{t('Your decision')}</th>
      </tr></thead>
      <tbody>
        {shownRows.map(source => <SourceRow key={source.source_version_id} source={source} busy={busy} asking={asking?.id === source.source_version_id}
          picked={picked.includes(source.source_version_id)} onPick={on => togglePick(source.source_version_id, on)}
          readsVersion={sources.find(s => s.source_version_id === source.answer_reads_version_id)}
          citedClaims={citedVersions.get(source.source_version_id) ?? 0} answerVersion={answerVersion} finding={a.pdfFinding.includes(source.source_version_id)} ocr={a.ocr}
          onRemoveFromResearch={() => a.onRemoveFromResearch(source)} onSelect={state => select(source, state, document.activeElement as HTMLElement)}
          onAskReason={() => setAsking({ id: source.source_version_id, text: source.selection.user_reason ?? '', opener: document.activeElement as HTMLElement })}
          onOpen={() => a.onOpen(source)} onAbstract={() => a.onAbstract(source)} onDiscoverPdf={() => a.onDiscoverPdf(source)} onAttachPdf={() => a.onAttachPdf(source)}
          onAttachCandidate={candidateId => a.onAttachCandidate(source, candidateId)} onOpenPdf={assetId => a.onOpenPdf(source, assetId)} onPlainText={assetId => a.onPlainText(source, assetId)}
          onRemoveAsset={assetId => a.onRemoveAsset(source, assetId)} onReplaceAsset={assetId => a.onReplaceAsset(source, assetId)} onReextract={assetId => a.onReextract(source, assetId)} onRereadEquations={assetId => a.onRereadEquations(source, assetId)} />)}
        {notReadRows.filter(row => !row.family).map(({ item }) => <UnlistedRow key={item.work_id} item={item} />)}
        {notRead && unscreened.page && unscreened.items.length < unscreened.page.total && <tr className="source-more"><td colSpan={4}>
          <button type="button" className="link" disabled={unscreened.loadingMore} aria-busy={unscreened.loadingMore} onClick={unscreened.more}>{t('Show {n} more', { n: Math.min(50, unscreened.page.total - unscreened.items.length).toLocaleString() })}</button>
          {unscreened.moreFailed && <span className="source-more-error" role="alert">{t('The next works could not be read.')}</span>}</td></tr>}
        {!shown.length && !(notRead && (notReadRows.length > 0 || unscreened.status !== 'ready' || !unscreened.page?.total)) && <tr className="more-row"><td colSpan={4}>{needle || pdfFilter !== 'all'
          ? t(needle && pdfFilter !== 'all' ? 'No works match “{q}” with {pdf}.' : needle ? 'No works match “{q}”.' : 'No works match with {pdf}.', { q: query.trim(), pdf: t(pdfFilterLabels[pdfFilter]).toLocaleLowerCase() })
          : t('No source matches this filter.')} <button type="button" className="link" onClick={clearAll}>{t(needle || pdfFilter !== 'all' ? 'Clear search and filter' : 'Show all sources')}</button></td></tr>}
      </tbody>
    </table></div>
    {picked.length > 0 && <SelectionBar ids={picked} busy={busy} {...bar} onClear={() => onPick([])} />}
  </div>
}

// The bar under the table while sources are chosen (mockup .selbar, D50): a table from them, rows for a table, the
// Library, removal from the research, or Clear.
function SelectionBar({ ids, busy, researchId, active, onStartTable, onAddToTable, onRemove, onSaveToLibrary, onClear }: { ids: string[]; busy: boolean; onClear: () => void } & BarActions) {
  const [tables, setTables] = useState<TableSummary[] | null>(null)
  useEffect(() => { api.tables(researchId).then(setTables, () => setTables([])) }, [researchId])
  return <div className="selbar" role="region" aria-label={t('Chosen sources')}>
    <b aria-live="polite">{t('{n} chosen', { n: ids.length })}</b>
    <span className="spacer" />
    <div className="selection-bar-actions">
      <button type="button" className="ghost" disabled={busy} onClick={() => onStartTable(ids)}><Table2 size={14} aria-hidden />{t('Start table')}</button>
      <DropdownMenu>
        <DropdownMenuTrigger disabled={busy || !tables?.length} render={<button type="button" className="ghost selbar-add-table" />} title={tables && !tables.length ? t('This research has no table yet') : undefined}><ListPlus size={14} aria-hidden />{t('Add to table')}</DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-auto">{(tables ?? []).map(table => <DropdownMenuItem key={table.id} onClick={() => onAddToTable(table, ids)}><Table2 size={15} />{tableTitle(table.title)}</DropdownMenuItem>)}</DropdownMenuContent>
      </DropdownMenu>
      <button type="button" className="ghost" disabled={busy} onClick={() => { void onSaveToLibrary(ids) }}><LibraryBig size={14} aria-hidden />{t('Add to library')}</button>
      <button type="button" className="ghost selbar-remove" disabled={busy || active} title={active ? t('Available when the active run finishes') : undefined} onClick={() => onRemove(ids)}><ListMinus size={14} aria-hidden />{t('Remove from research')}</button>
      <button type="button" className="ghost" onClick={onClear}>{t('Clear')}</button>
    </div>
  </div>
}

// The "Not read" notice (mockup P7): what the list is, and "Screen N more" with the number the next run would read.
function NotReadNotice({ unscreened, effort, limits, busy, active, screening, onScreenMore }: {
  unscreened: ReturnType<typeof useUnscreened>; effort: Effort; limits: EffortLimits | null; busy: boolean; active: boolean; screening: boolean; onScreenMore: () => void
}) {
  const { page, status } = unscreened
  const number = (n: number) => n.toLocaleString(uiLocale())
  if (status === 'loading' && !page) return <div className="notice source-notread"><Info size={16} aria-hidden /><div className="nb"><span>{t('Reading the works found but never screened…')}</span></div></div>
  if (status === 'none') return <div className="notice source-notread"><Info size={16} aria-hidden /><div className="nb"><span>{t('This research has no completed search with a ranked list, so no work is listed as never screened.')}</span></div></div>
  if (status === 'failed' || !page) return <div className="notice warn source-notread" role="alert"><Info size={16} aria-hidden /><div className="nb"><span>{t('The works found but never screened could not be read.')}</span>
    <div className="acts"><button type="button" className="ghost" onClick={() => { void unscreened.reload() }}>{t('Try again')}</button></div></div></div>
  if (!page.total) return <div className="notice source-notread"><Info size={16} aria-hidden /><div className="nb"><span>{t('No unscreened works left to list.')}</span></div></div>
  const papers = limits?.efforts[effort]?.papers
  const next = Math.min(SCREEN_MORE_SIZE, page.screenable)
  return <div className="notice source-notread"><Info size={16} aria-hidden /><div className="nb">
    <span>{papers !== undefined
      ? t('These works were found but never screened: {depth} depth screens the top {n} of the ranked list. {total} works sit below that line, listed here in its order; {screenable} of them have an abstract to read.', { depth: t(effortLabels[effort]), n: number(papers), total: number(page.total), screenable: number(page.screenable) })
      : t('These works were found but never screened. {total} works sit below the part of the ranked list that was screened, listed here in its order; {screenable} of them have an abstract to read.', { total: number(page.total), screenable: number(page.screenable) })}
      {' '}{t('Rank and similarity are the signals the list was ordered by, not relevance.')}</span>
    {next > 0 && <div className="acts"><button type="button" className="ghost source-screen-more" disabled={busy || active || screening} aria-busy={screening} title={active ? t('Available when the current run ends') : t('Reads the abstracts of the next {n} works twice; it never includes a source by itself.', { n: number(next) })} onClick={onScreenMore}><ListChecks size={14} aria-hidden />{t('Screen {n} more', { n: number(next) })}</button></div>}
  </div></div>
}

// A listed never-screened work that is no longer among this research's sources: its stored fields, no actions.
function UnlistedRow({ item }: { item: UnscreenedWork }) {
  return <tr className="source-row source-unlisted">
    <td className="cb" />
    <td><span className="src-t">{item.title ?? t('Untitled record')}</span>
      <span className="src-m">{[item.year, item.venue, t('rank {n}', { n: item.signals.rank })].filter(Boolean).join(' · ')}</span></td>
    <td><span className="prop">{t('not screened')}</span></td>
    <td />
  </tr>
}
