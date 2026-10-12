import { useState } from 'react'
import { ArrowUpDown, Filter, Search } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { type Source } from '../api'
import { t } from '../i18n'
import { SourceRow } from './SourceRow'
import type { OcrContext } from './shared'

type SourceSort = 'found' | 'relevant' | 'cited' | 'newest' | 'oldest' | 'title'
const sourceSorts: Record<SourceSort, string> = { relevant: 'Most relevant', found: 'Order found', cited: 'Most cited', newest: 'Newest first', oldest: 'Oldest first', title: 'Title A–Z' }
// Search position is not comparable across queries: the model's screening verdict decides, then similarity to the question
// when semantic search scored the source (D30), then the best position in the searches that found it.
const verdictOrder: Record<string, number> = { include: 0, uncertain: 1, exclude: 2 }
const verdictRank = (s: Source) => verdictOrder[s.selection.proposal ?? ''] ?? 3
// "Cited in answer" (mockup P5's first tab, opened by the answer's "View N cited sources") lists the works the answer shown
// in the thread cites, from that answer's stored claims (`cited`: the source versions its evidence names). The view's
// `cited_in_latest_answer` flag follows the newest draft, which is not the shown answer after a failed late revision.
// The tab shows once that answer cites any. The other P5 tabs come with S13.
const stateFilters = [['cited', 'Cited in answer'], ['all', 'All'], ['included', 'Included'], ['pending', 'Undecided'], ['excluded', 'Excluded']] as const
export type StateFilter = typeof stateFilters[number][0]
type PdfFilter = 'all' | 'with_pdf' | 'without_pdf'
const pdfFilterLabels: Record<PdfFilter, string> = { all: 'All PDFs', with_pdf: 'PDF attached', without_pdf: 'No PDF attached' }
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

type SourceActions = { onRemoveFromResearch: (source: Source) => void; onSelect: (source: Source, state: Source['selection']['state']) => void; onReason: (source: Source, reason: string) => void; onAbstract: (source: Source) => void; onDiscoverPdf: (source: Source) => void; onAttachPdf: (source: Source) => void; onAttachCandidate: (source: Source, candidateId: string) => void; onOpenPdf: (source: Source, assetId: string) => void; onRemoveAsset: (source: Source, assetId: string) => void; onReplaceAsset: (source: Source, assetId: string) => void; onReextract: (source: Source, assetId: string) => void; onRereadEquations: (source: Source, assetId: string) => void; pdfFinding: string | null; ocr: OcrContext }

export function SourceList({ sources, cited, busy, filter, onFilter, focus, onFocus, picked, onPick, onRemoveFromResearch, onSelect, onReason, onAbstract, onDiscoverPdf, onAttachPdf, onAttachCandidate, onOpenPdf, onRemoveAsset, onReplaceAsset, onReextract, onRereadEquations, pdfFinding, ocr }: { sources: Source[]; cited: ReadonlySet<string>; busy: boolean; filter: StateFilter; onFilter: (filter: StateFilter) => void; focus: string | null; onFocus: (workId: string | null) => void; picked: string[]; onPick: (ids: string[]) => void } & SourceActions) {
  const [pdfFilter, setPdfFilter] = useState<PdfFilter>('all')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<SourceSort>('relevant')
  // Other versions follow their record and move with it; the filter and sort look at the record.
  const families: Source[][] = []
  for (const source of sources) {
    const last = families[families.length - 1]
    if (source.version_role === 'other_version' && last?.[0].work_id === source.work_id) last.push(source)
    else families.push([source])
  }
  const isCited = (family: Source[]) => family.some(source => cited.has(source.source_version_id))
  const counts = { cited: families.filter(isCited).length, all: families.length, included: 0, pending: 0, excluded: 0 }
  families.forEach(([record]) => counts[record.selection.state]++)
  const hasPdf = (family: Source[]) => family.some(source => source.access.assets.length > 0)
  const pdfCounts = { all: families.length, with_pdf: families.filter(hasPdf).length, without_pdf: families.filter(family => !hasPdf(family)).length }
  const needle = query.trim().toLocaleLowerCase()
  const matches = (s: Source) => [s.title, s.venue, s.doi, ...s.authors].some(text => text?.toLocaleLowerCase().includes(needle))
  const focused = focus ? families.filter(f => f[0].work_id === focus) : null
  const shown = focused ?? families.filter(f => (filter === 'all' || (filter === 'cited' ? isCited(f) : f[0].selection.state === filter)) && (pdfFilter === 'all' || (pdfFilter === 'with_pdf' ? hasPdf(f) : !hasPdf(f))) && (!needle || f.some(matches)))
    .sort((a, b) => sourceCompare[sort](a[0], b[0]))
  const shownIds = shown.flat().map(s => s.source_version_id)
  const allShownPicked = shownIds.length > 0 && shownIds.every(sid => picked.includes(sid))
  const togglePick = (sid: string, on: boolean) => onPick(on ? [...picked, sid] : picked.filter(p => p !== sid))
  if (!sources.length) return <p className="empty-inline">{t('No sources yet.')}</p>
  return <>
    {families.length > 1 && <div className="source-toolbar">
      {/* The state filters run as the strip above the toolbar row (mockup .tabs over .toolbar). */}
      <div className="source-filters" role="group" aria-label={t('Show sources')}>
        {stateFilters.filter(([key]) => key !== 'cited' || counts.cited > 0 || filter === 'cited').map(([key, label]) => <button key={key} aria-pressed={!focused && filter === key} onClick={() => { onFocus(null); onFilter(key) }}>{t(label)}<span>{counts[key]}</span></button>)}
      </div>
      <label className="source-pick-all"><input type="checkbox" checked={allShownPicked} disabled={!shownIds.length}
        ref={node => { if (node) node.indeterminate = !allShownPicked && shownIds.some(sid => picked.includes(sid)) }}
        onChange={e => onPick(e.target.checked ? [...new Set([...picked, ...shownIds])] : picked.filter(sid => !shownIds.includes(sid)))} /><span>{t('Select shown')}</span></label>
      <label className="source-search"><Search size={14} aria-hidden /><input type="search" aria-label={t('Filter sources')} placeholder={t('Title, author, venue or DOI')} value={query} onChange={e => { onFocus(null); setQuery(e.target.value) }} /></label>
      <Select value={pdfFilter} onValueChange={value => { if (value) { onFocus(null); setPdfFilter(value as PdfFilter) } }}>
        <SelectTrigger className="source-pdf-filter" aria-label={t('Filter sources by PDF availability')}><SelectValue>{(value: string) => <><Filter size={14} />{t(pdfFilterLabels[value as PdfFilter])}</>}</SelectValue></SelectTrigger>
        <SelectContent className="intake-select-content" align="end" alignItemWithTrigger={false}>
          {(Object.keys(pdfFilterLabels) as PdfFilter[]).map(k => <SelectItem key={k} value={k}><span className="source-filter-option"><span>{t(pdfFilterLabels[k])}</span><small>{pdfCounts[k]}</small></span></SelectItem>)}
        </SelectContent>
      </Select>
      <Select value={sort} onValueChange={value => { if (value) setSort(value as SourceSort) }}>
        <SelectTrigger aria-label={t('Sort sources')}><SelectValue>{(value: string) => <><ArrowUpDown size={14} />{t(sourceSorts[value as SourceSort])}</>}</SelectValue></SelectTrigger>
        <SelectContent className="intake-select-content" align="end" alignItemWithTrigger={false}>
          {(Object.keys(sourceSorts) as SourceSort[]).map(k => <SelectItem key={k} value={k}>{k === 'relevant' ? <span className="sort-option">{t(sourceSorts[k])}<small>{t('Model’s screening verdict first, then similarity to the question, then search position')}</small></span> : t(sourceSorts[k])}</SelectItem>)}
        </SelectContent>
      </Select>
    </div>}
    {focused && <p className="source-focus">{t('Showing the one work the audit sample sent you to.')} <button type="button" onClick={() => { onFocus(null); onFilter('all'); setPdfFilter('all'); setQuery('') }}>{t('Show all sources')}</button></p>}
    <div className={`source-list${picked.length ? ' has-selection-bar' : ''}`}>{shown.flat().map(source => <SourceRow key={source.source_version_id} source={source} busy={busy}
      picked={picked.includes(source.source_version_id)} onPick={on => togglePick(source.source_version_id, on)} onRemoveFromResearch={() => onRemoveFromResearch(source)}
      readsVersion={sources.find(s => s.source_version_id === source.answer_reads_version_id)}
      onSelect={state => onSelect(source, state)} onReason={reason => onReason(source, reason)} onAbstract={() => onAbstract(source)}
      onDiscoverPdf={() => onDiscoverPdf(source)} onAttachPdf={() => onAttachPdf(source)} onAttachCandidate={candidateId => onAttachCandidate(source, candidateId)} onOpenPdf={assetId => onOpenPdf(source, assetId)}
      onRemoveAsset={assetId => onRemoveAsset(source, assetId)} onReplaceAsset={assetId => onReplaceAsset(source, assetId)} onReextract={assetId => onReextract(source, assetId)} onRereadEquations={assetId => onRereadEquations(source, assetId)} finding={pdfFinding === source.source_version_id} ocr={ocr} />)}</div>
    {!shown.length && <p className="empty-inline source-empty">{t('No source matches this filter.')} <button onClick={() => { onFilter('all'); setPdfFilter('all'); setQuery(''); onFocus(null) }}>{t('Show all sources')}</button></p>}
  </>
}
