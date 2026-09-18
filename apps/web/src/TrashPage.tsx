import { useCallback, useEffect, useState } from 'react'
import { Check, ChevronDown, ChevronRight, Ellipsis, FlaskConical, Lock, Repeat, RotateCcw, Search, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tooltip } from '@/components/ui/tooltip'
import { ConfirmDialog } from './ConfirmDialog'
import { api, type RemovedSource, type Trash, type TrashedResearch, type TrashedTable, type TrashedTemplate } from './api'
import { versionText, versionTones } from './labels'
import { PassageSheet } from './PassageSheet'
import { t, uiLocale } from './i18n'

// The Trash page groups what was moved to the trash or removed from a research (D50). Nothing here expires. Research,
// tables and templates are deleted one at a time; a removed source can be deleted once nothing cites it (D65).

type PendingItem = { kind: 'research'; item: TrashedResearch } | { kind: 'table'; item: TrashedTable } | { kind: 'template'; item: TrashedTemplate }
// Sources are restored and purged one research at a time, so a pending deletion carries one target per research it touches.
type SourceTarget = { researchId: string; versions: RemovedSource[] }
type PendingSources = { kind: 'sources'; key: string; title: string; count: number; targets: SourceTarget[] }
type Pending = PendingItem | PendingSources
// The row opened in the source sheet, on the abstract this research can still read (D50).
type OpenSource = { key: string; researchId: string; researchTitle: string; passageId: string }
const inspectable = (versions: RemovedSource[]) => versions.find(v => v.abstract_passage_id) ?? null

const dateText = (value: string) => new Date(value).toLocaleDateString(uiLocale(), { dateStyle: 'medium' })
// The ledger repeats the removal date on every row, so it gets the short form and the medium one stays in the summaries.
const shortDateText = (value: string) => new Date(value).toLocaleDateString(uiLocale(), { day: 'numeric', month: 'short', year: 'numeric' })
type SourceSort = 'removed' | 'title' | 'year'
const sortLabels: Record<SourceSort, string> = { removed: 'Recently removed', title: 'Title', year: 'Year' }
const sorters: Record<SourceSort, (a: RemovedSource[], b: RemovedSource[]) => number> = {
  removed: (a, b) => b[0].removed_at.localeCompare(a[0].removed_at),
  title: (a, b) => a[0].title.localeCompare(b[0].title, uiLocale()),
  year: (a, b) => (b[0].year ?? 0) - (a[0].year ?? 0),
}
// One research removed its sources on one day or over a span; the block head says which.
function removedSpan(works: RemovedSource[][]) {
  const days = works.flat().map(v => v.removed_at).sort()
  const first = dateText(days[0])
  const last = dateText(days[days.length - 1])
  return first === last ? t('removed {date}', { date: first }) : t('removed {from} – {to}', { from: first, to: last })
}
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e))

// Versions of one work removed from one research are one item; restoring it brings the versions removed with it.
function sourceGroups(sources: RemovedSource[]) {
  const researches = new Map<string, { id: string; title: string; works: Map<string, RemovedSource[]> }>()
  for (const source of sources) {
    const research = researches.get(source.research_id) ?? { id: source.research_id, title: source.research_title, works: new Map() }
    researches.set(source.research_id, research)
    research.works.set(source.work_id, [...(research.works.get(source.work_id) ?? []), source])
  }
  return [...researches.values()].map(r => ({ ...r, works: [...r.works.values()] }))
}

// A research shows this many removed sources until the reader asks for the rest; the Trash holds hundreds of them.
const ROW_LIMIT = 8

const workKey = (researchId: string, versions: RemovedSource[]) => `${researchId}:${versions[0].work_id}`

function toggled(set: Set<string>, key: string) {
  const next = new Set(set)
  if (!next.delete(key)) next.add(key)
  return next
}

// One call per research: restoreSources and purgeSources each take a single research id.
function targetsOf(picks: SourceTarget[]): SourceTarget[] {
  const byResearch = new Map<string, RemovedSource[]>()
  for (const pick of picks) byResearch.set(pick.researchId, [...(byResearch.get(pick.researchId) ?? []), ...pick.versions])
  return [...byResearch].map(([researchId, versions]) => ({ researchId, versions }))
}

export function TrashPage({ dark, onChanged }: { dark: boolean; onChanged: () => void }) {
  const [trash, setTrash] = useState<Trash | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [pending, setPending] = useState<Pending | null>(null)
  const [query, setQuery] = useState('')
  const [scope, setScope] = useState<'all' | 'deletable' | 'cited'>('all')
  const [onlyResearch, setOnlyResearch] = useState('all')
  const [sort, setSort] = useState<SourceSort>('removed')
  const [foldedGroups, setFoldedGroups] = useState<Set<string>>(new Set())
  const [wholeGroups, setWholeGroups] = useState<Set<string>>(new Set())
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [openSource, setOpenSource] = useState<OpenSource | null>(null)

  const refresh = useCallback(() => api.trash().then(next => { setTrash(next); setError('') }, (e: Error) => setError(e.message)), [])
  useEffect(() => { void refresh() }, [refresh])


  async function run(key: string, action: () => Promise<string>, failure: string) {
    setBusy(key)
    setMessage('')
    try { setMessage(await action()); onChanged() }
    catch (e) { setMessage(t(failure, { message: errorText(e) })) }
    finally { setBusy(null); await refresh() }
  }

  function deletePermanently(target: Pending) {
    setPending(null)
    if (target.kind === 'research') void run(target.item.id, async () => {
      const result = await api.deletePermanently(target.item.id)
      return result.files_not_removed.length
        ? t('Research deleted, but {n} file(s) could not be removed from disk.', { n: result.files_not_removed.length })
        : t('Research permanently deleted.')
    }, 'Could not permanently delete research: {message}')
    else if (target.kind === 'table') void run(target.item.id, async () => { await api.purgeTable(target.item.id); return t('Table permanently deleted.') }, 'Could not delete the table: {message}')
    else if (target.kind === 'template') void run(target.item.id, async () => { await api.purgeTemplate(target.item.id); return t('Template permanently deleted.') }, 'Could not delete the template: {message}')
    else void run(target.key, async () => {
      let deleted = 0
      let files = 0
      for (const one of targetsOf(target.targets)) {
        const result = await api.purgeSources(one.researchId, one.versions.map(v => v.source_version_id))
        deleted += result.deleted.length
        files += result.files_not_removed.length
      }
      setPicked(new Set())
      return files
        ? t('{n} source(s) deleted, but {files} file(s) could not be removed from disk.', { n: deleted, files })
        : t(deleted === 1 ? 'Source permanently deleted.' : '{n} sources permanently deleted.', { n: deleted })
    }, 'Could not delete the sources: {message}')
  }

  const groups = trash ? sourceGroups(trash.sources) : []
  const empty = trash && !trash.researches.length && !trash.tables.length && !trash.sources.length && !trash.templates.length
  const deleteButton = (target: PendingItem) => <Button variant="destructive" className="trash-delete" disabled={busy === target.item.id} onClick={() => setPending(target)}><Trash2 size={15} />{t('Delete permanently')}</Button>
  // A source an answer quote, a table or a report still cites is not offered for deletion: that evidence must keep opening (D65).
  const deletable = (versions: RemovedSource[]) => versions.every(v => !v.cited)
  // The section works on hundreds of rows: filter first, then show part of each research.
  const needle = query.trim().toLocaleLowerCase(uiLocale())
  const allWorks = groups.flatMap(group => group.works)
  const citedWorks = allWorks.filter(versions => !deletable(versions)).length
  const visibleGroups = groups
    .filter(group => onlyResearch === 'all' || group.id === onlyResearch)
    .map(group => ({ ...group, works: group.works.filter(versions => (scope === 'all' || (scope === 'deletable') === deletable(versions))
      && (!needle || versions[0].title.toLocaleLowerCase(uiLocale()).includes(needle) || group.title.toLocaleLowerCase(uiLocale()).includes(needle))).sort(sorters[sort]) }))
    .filter(group => group.works.length > 0)
  const pickedTargets: SourceTarget[] = groups.flatMap(group => group.works
    .filter(versions => picked.has(workKey(group.id, versions)))
    .map(versions => ({ researchId: group.id, versions })))
  const pickedDeletable = pickedTargets.filter(target => deletable(target.versions))
  const pendingTitle = !pending ? '' : pending.kind === 'template' ? pending.item.name : pending.kind === 'sources' ? pending.title : pending.item.title
  const pendingText = !pending ? ''
    : pending.kind === 'sources' ? t(pending.count === 1
        ? 'The research loses its record of this source. Its library record, passages and PDF go too, unless another research holds it. This cannot be undone.'
        : 'The research loses its record of {n} sources. Their library records, passages and PDFs go too, unless another research holds them. This cannot be undone.', { n: pending.count })
    : pending.kind === 'research' ? t('Its unshared evidence and files are removed too. Sources shared with other research stay. This cannot be undone.')
    : pending.kind === 'table' ? t('Its rows, columns, {cells} cells with a value and {edits} edits of yours are deleted. Passages, files and answers stay. This cannot be undone.', { cells: pending.item.cells, edits: pending.item.human_edits })
    : t('Its column definitions are deleted. Tables started from it keep their own columns. This cannot be undone.')

  return <section className="trash-page">
    <h1>{t('Trash')}</h1>
    <p className="trash-hint">{t('Research, evidence tables, templates and sources removed from a research wait here until you restore or delete them. Nothing in the Trash expires.')}</p>
    {trash && !empty && <p className="trash-index">{[
      trash.researches.length > 0 && { href: '#trash-researches', text: t(trash.researches.length === 1 ? '{n} research' : '{n} research', { n: trash.researches.length }) },
      trash.tables.length > 0 && { href: '#trash-tables', text: t(trash.tables.length === 1 ? '{n} evidence table' : '{n} evidence tables', { n: trash.tables.length }) },
      trash.sources.length > 0 && { href: '#trash-sources', text: t(allWorks.length === 1 ? '{n} removed source from {r} research' : '{n} removed sources from {r} research', { n: allWorks.length, r: groups.length }) },
      citedWorks > 0 && { href: '#trash-sources', text: t('{n} still cited, kept until their research is deleted', { n: citedWorks }) },
      trash.templates.length > 0 && { href: '#trash-templates', text: t(trash.templates.length === 1 ? '{n} table template' : '{n} table templates', { n: trash.templates.length }) },
    ].filter(part => part !== false).map((part, index) => <a key={(part as { href: string }).href + index}
      href={(part as { href: string }).href}>{(part as { text: string }).text}</a>)}</p>}
    {message && <p role="status" className="trash-message">{message}</p>}
    {error ? <p role="alert">{t('Could not load Trash: {message}', { message: error })} <Button variant="outline" onClick={() => { void refresh() }}>{t('Retry')}</Button></p>
      : !trash ? <p role="status">{t('Loading Trash…')}</p>
      : empty ? <p>{t('Trash is empty.')}</p>
      : trash && <>
        {trash.researches.length > 0 && <section className="trash-group" aria-labelledby="trash-researches">
          <h2 id="trash-researches">{t('Research')}<span>{trash.researches.length}</span></h2>
          {trash.researches.map(r => <div className="trash-row" key={r.id}>
            <span className="trash-item"><strong title={r.title}>{r.title}</strong><small>{t('Moved to Trash {date}', { date: dateText(r.trashed_at) })}</small></span>
            <div><Button variant="outline" disabled={busy === r.id} onClick={() => run(r.id, async () => { await api.restore(r.id); return t('Research restored.') }, 'Could not restore research: {message}')}><RotateCcw size={15} />{t('Restore')}</Button>{deleteButton({ kind: 'research', item: r })}</div>
          </div>)}
        </section>}
        {trash.tables.length > 0 && <section className="trash-group" aria-labelledby="trash-tables">
          <h2 id="trash-tables">{t('Evidence tables')}<span>{trash.tables.length}</span></h2>
          {trash.tables.map(table => <div className="trash-row" key={table.id}>
            <span className="trash-item"><strong title={table.title}>{table.title}</strong>
              <small>{[table.research_title, t(table.rows === 1 ? '{n} row' : '{n} rows', { n: table.rows }), t(table.columns === 1 ? '{n} column' : '{n} columns', { n: table.columns }),
                t(table.cells === 1 ? '{n} cell with a value' : '{n} cells with a value', { n: table.cells }),
                table.human_edits > 0 && t(table.human_edits === 1 ? '{n} edit of yours' : '{n} edits of yours', { n: table.human_edits }), t('Moved to Trash {date}', { date: dateText(table.trashed_at) })].filter(Boolean).join(' · ')}</small></span>
            <div><Button variant="outline" disabled={busy === table.id} onClick={() => run(table.id, async () => { await api.restoreTable(table.research_id, table.id, table.version); return t('Table restored to {research}.', { research: table.research_title }) }, 'Could not restore the table: {message}')}><RotateCcw size={15} />{t('Restore')}</Button>{deleteButton({ kind: 'table', item: table })}</div>
          </div>)}
        </section>}
        {groups.length > 0 && <section className="trash-group" aria-labelledby="trash-sources">
          <h2 id="trash-sources">{t('Sources removed from a research')}<span>{allWorks.length}</span></h2>
          <p className="trash-group-note">{t('The library record and its PDF were not deleted, and earlier quotes still open. Deleting one permanently also deletes its library record, passages and PDF, unless another research holds the source or evidence still cites it.')}</p>
          <div className="trash-tools">
            <div className="trash-search" role="search">
              <Search size={15} aria-hidden />
              <input type="search" value={query} onChange={event => setQuery(event.target.value)}
                placeholder={t('Filter by title or research')} aria-label={t('Filter the removed sources')} />
            </div>
            <div className="trash-scope" role="group" aria-label={t('Which removed sources to show')}>
              <button type="button" aria-pressed={scope === 'all'} onClick={() => setScope('all')}>{t('All')} {allWorks.length}</button>
              <button type="button" aria-pressed={scope === 'deletable'} onClick={() => setScope('deletable')}>{t('Deletable')} {allWorks.length - citedWorks}</button>
              <button type="button" aria-pressed={scope === 'cited'} onClick={() => setScope('cited')}>{t('Still cited')} {citedWorks}</button>
            </div>
            {groups.length > 1 && <div className="trash-select">
              <span id="trash-research-filter">{t('Research')}</span>
              <Select value={onlyResearch} onValueChange={value => { if (value) setOnlyResearch(value as string) }}>
                <SelectTrigger aria-labelledby="trash-research-filter"><SelectValue>{(value: string) =>
                  value === 'all' ? t('All {n} research', { n: groups.length }) : groups.find(group => group.id === value)?.title ?? ''}</SelectValue></SelectTrigger>
                <SelectContent align="end">
                  <SelectItem value="all">{t('All {n} research', { n: groups.length })}</SelectItem>
                  {groups.map(group => <SelectItem key={group.id} value={group.id}>{group.title}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>}
            <div className="trash-select">
              <span id="trash-sort">{t('Sort')}</span>
              <Select value={sort} onValueChange={value => { if (value) setSort(value as SourceSort) }}>
                <SelectTrigger aria-labelledby="trash-sort"><SelectValue>{(value: string) => t(sortLabels[value as SourceSort])}</SelectValue></SelectTrigger>
                <SelectContent align="end">
                  {(Object.keys(sortLabels) as SourceSort[]).map(order => <SelectItem key={order} value={order}>{t(sortLabels[order])}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
          {visibleGroups.length === 0
            ? <p className="trash-group-note">{t('No removed source matches this filter.')}</p>
            : visibleGroups.map(group => {
            const folded = foldedGroups.has(group.id)
            const shown = folded ? [] : wholeGroups.has(group.id) ? group.works : group.works.slice(0, ROW_LIMIT)
            const hidden = group.works.length - shown.length
            const stillCited = group.works.filter(versions => !deletable(versions)).length
            return <div className="trash-research" key={group.id}>
              <div className="trash-research-head">
                <button type="button" className="trash-fold" aria-expanded={!folded}
                  aria-label={t(folded ? 'Show the sources removed from {research}' : 'Hide the sources removed from {research}', { research: group.title })}
                  onClick={() => setFoldedGroups(toggled(foldedGroups, group.id))}>{folded ? <ChevronRight size={15} aria-hidden /> : <ChevronDown size={15} aria-hidden />}</button>
                <span className="trash-research-mark" aria-hidden><FlaskConical size={14} /></span>
                <div className="trash-research-title">
                  <h3 title={group.title}>{group.title}</h3>
                  <p className="trash-research-count">{[t(group.works.length === 1 ? '{n} source' : '{n} sources', { n: group.works.length }),
                    stillCited === 0 ? t('all deletable') : group.works.length > stillCited && t('{n} deletable', { n: group.works.length - stillCited }),
                    stillCited > 0 && t('{n} still cited', { n: stillCited }),
                    removedSpan(group.works)].filter(Boolean).join(' · ')}</p>
                </div>
                {group.works.length > 1 && <Button variant="ghost" size="sm" disabled={busy === group.id} onClick={() => run(group.id, async () => { await api.restoreSources(group.id, group.works.flat().map(s => s.source_version_id)); return t('{n} sources restored to {research}.', { n: group.works.length, research: group.title }) }, 'Could not restore the sources: {message}')}><RotateCcw size={14} />{t('Restore all')}</Button>}
                <DropdownMenu>
                  <DropdownMenuTrigger className="trash-research-more" aria-label={t('Actions for {title}', { title: group.title })} title={t('More actions')}><Ellipsis size={15} aria-hidden /></DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-auto">
                    <DropdownMenuItem onClick={() => setPicked(new Set([...picked, ...group.works.map(versions => workKey(group.id, versions))]))}><Check size={15} />{t('Select all {n}', { n: group.works.length })}</DropdownMenuItem>
                    {group.works.some(deletable) && <>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem variant="destructive" onClick={() => setPending({ kind: 'sources', key: `${group.id}:all`, title: group.title,
                        count: group.works.filter(deletable).length, targets: [{ researchId: group.id, versions: group.works.filter(deletable).flat() }] })}><Trash2 size={15} />{t('Delete all permanently')}</DropdownMenuItem>
                    </>}
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
              {shown.length > 0 && <div className="trash-ledger">
                <div className="trash-ledger-head">
                  <span><input type="checkbox" aria-label={t('Select the {n} sources shown here', { n: shown.length })}
                    checked={shown.every(versions => picked.has(workKey(group.id, versions)))}
                    onChange={event => {
                      const next = new Set(picked)
                      for (const versions of shown) { if (event.target.checked) next.add(workKey(group.id, versions)); else next.delete(workKey(group.id, versions)) }
                      setPicked(next)
                    }} /></span>
                  <span>{t('Source')}</span>
                  <span>{t('Version and state')}</span>
                  <span>{t('Removed')}</span>
                  <span />
                </div>
              {shown.map(versions => {
                const first = versions[0]
                const quotes = versions.reduce((n, v) => n + v.quotes, 0)
                const cells = versions.reduce((n, v) => n + v.cells, 0)
                const key = workKey(group.id, versions)
                const canDelete = deletable(versions)
                const openable = inspectable(versions)
                const citedText = [quotes > 0 && t(quotes === 1 ? 'cited in {n} answer quote' : 'cited in {n} answer quotes', { n: quotes }),
                  cells > 0 && t(cells === 1 ? '{n} table cell' : '{n} table cells', { n: cells })].filter(Boolean).join(' · ') || t('still cited')
                return <div className={`trash-row${picked.has(key) ? ' is-picked' : ''}`} key={key}>
                  <input type="checkbox" className="trash-pick" checked={picked.has(key)} aria-label={t('Select {title}', { title: first.title })}
                    onChange={() => setPicked(toggled(picked, key))} />
                  <span className="trash-item"><strong>{openable
                    ? <button type="button" className="trash-title" title={first.title}
                      onClick={() => setOpenSource({ key, researchId: group.id, researchTitle: group.title, passageId: openable.abstract_passage_id as string })}>{first.title}</button>
                    : <span title={t('No abstract is stored for this source, so there is nothing to inspect here.')}>{first.title}</span>}</strong>
                    {first.removal_note && <small className="trash-note">{t('Your note: {note}', { note: first.removal_note })}</small>}
                  </span>
                  <small className="trash-facts">
                    {/* The version every row shares is a fact dot, so the rarer versions and the states keep the pills to themselves. */}
                    {versions.map(v => (versionTones[v.version_label ?? ''] ?? 'unstated') === 'published'
                      ? <span key={v.source_version_id} className="source-fact is-published">{versionText(v.version_label)}</span>
                      : <span key={v.source_version_id} className={`ref-pill is-${versionTones[v.version_label ?? ''] ?? 'unstated'}`}>{versionText(v.version_label)}</span>)}
                    {first.year !== null && <span className="trash-year">{first.year}</span>}
                    {!canDelete && <Tooltip content={t('An answer quote, an evidence table or a report still cites this source. It is deleted with its research.')}>
                      <span className="ref-pill is-cited" tabIndex={0}><Lock size={11} aria-hidden />{citedText}</span></Tooltip>}
                    {versions.some(v => v.found_again_at) && <span className="ref-pill is-unstated"><Repeat size={11} aria-hidden />{t('found again by a later search')}</span>}
                  </small>
                  {/* The column head names this cell; where it is hidden, the label comes back through data-label. */}
                  <small className="trash-date" data-label={t('Removed')}>{shortDateText(first.removed_at)}</small>
                  <div className="trash-row-actions">
                    <Button variant="ghost" size="icon" className="trash-icon" disabled={busy === key} title={t('Restore')} aria-label={t('Restore {title}', { title: first.title })}
                      onClick={() => run(key, async () => { await api.restoreSources(group.id, versions.map(v => v.source_version_id)); return t('Source restored to {research}.', { research: group.title }) }, 'Could not restore the sources: {message}')}><RotateCcw size={15} /></Button>
                    <Button variant="ghost" size="icon" className="trash-icon is-delete" disabled={busy === key || !canDelete}
                      title={canDelete ? t('Delete permanently') : t('An answer quote, an evidence table or a report still cites this source. It is deleted with its research.')}
                      aria-label={t('Delete {title} permanently', { title: first.title })}
                      onClick={() => setPending({ kind: 'sources', key, title: first.title, count: 1, targets: [{ researchId: group.id, versions }] })}><Trash2 size={15} /></Button>
                  </div>
                </div>
              })}
              </div>}
              {hidden > 0 && !folded && <button type="button" className="trash-more" onClick={() => setWholeGroups(toggled(wholeGroups, group.id))}>{t('Show {n} more from this research', { n: hidden })}<ChevronDown size={13} aria-hidden /></button>}
            </div>
          })}
          {pickedTargets.length > 0 && <div className="selection-bar">
            <strong>{t(pickedTargets.length === 1 ? '{n} source selected' : '{n} sources selected', { n: pickedTargets.length })}
              <span>{[t('{n} deletable', { n: pickedDeletable.length }),
                t('from {n} research', { n: new Set(pickedTargets.map(target => target.researchId)).size })].join(' · ')}</span></strong>
            <div className="selection-bar-actions">
              <Button variant="outline" size="sm" disabled={busy === 'picked'} onClick={() => run('picked', async () => {
                const restored = pickedTargets.length
                for (const one of targetsOf(pickedTargets)) await api.restoreSources(one.researchId, one.versions.map(v => v.source_version_id))
                setPicked(new Set())
                return t('{n} sources restored.', { n: restored })
              }, 'Could not restore the sources: {message}')}><RotateCcw size={15} />{t('Restore')}</Button>
              <Button variant="outline" size="sm" className="trash-delete" disabled={busy === 'picked' || pickedDeletable.length === 0}
                title={pickedDeletable.length === 0 ? t('An answer quote, an evidence table or a report still cites this source. It is deleted with its research.') : undefined}
                onClick={() => setPending({ kind: 'sources', key: 'picked', title: '', count: pickedDeletable.length, targets: pickedDeletable })}><Trash2 size={15} />{t('Delete permanently')}</Button>
              <Button variant="ghost" size="sm" onClick={() => setPicked(new Set())}>{t('Clear selection')}</Button>
            </div>
          </div>}
        </section>}
        {trash.templates.length > 0 && <section className="trash-group" aria-labelledby="trash-templates">
          <h2 id="trash-templates">{t('Table templates')}<span>{trash.templates.length}</span></h2>
          {trash.templates.map(template => <div className="trash-row" key={template.id}>
            <span className="trash-item"><strong title={template.name}>{template.name}</strong><small>{t(template.columns === 1 ? '{n} column' : '{n} columns', { n: template.columns })} · {t('Moved to Trash {date}', { date: dateText(template.trashed_at) })}</small></span>
            <div><Button variant="outline" disabled={busy === template.id} onClick={() => run(template.id, async () => { await api.restoreTemplate(template.id); return t('Template restored.') }, 'Could not restore the template: {message}')}><RotateCcw size={15} />{t('Restore')}</Button>{deleteButton({ kind: 'template', item: template })}</div>
          </div>)}
        </section>}
      </>}
    {openSource && <PassageSheet researchId={openSource.researchId} passageId={openSource.passageId}
      dark={dark} onClose={() => setOpenSource(null)}
      onRestoreSource={sourceVersionId => {
        const target = openSource
        setOpenSource(null)
        void run(target.key, async () => { await api.restoreSources(target.researchId, [sourceVersionId]); return t('Source restored to {research}.', { research: target.researchTitle }) }, 'Could not restore the sources: {message}')
      }} />}
    <ConfirmDialog open={pending !== null} dark={dark} title={t('Delete permanently?')} description={pendingText} context={pendingTitle}
      confirmLabel={t('Delete permanently')} cancelLabel={t('Cancel')} onConfirm={() => pending && deletePermanently(pending)} onOpenChange={open => { if (!open) setPending(null) }} />
  </section>
}
