import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight, Ellipsis, FileText, FlaskConical, Info, LayoutTemplate, RotateCcw, Search, Table2, Trash2, TriangleAlert, type LucideIcon } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { api, type RemovedSource, type Trash } from './api'
import { tableTitle, versionText } from './labels'
import { PassageSheet } from './PassageSheet'
import { t, uiLocale } from './i18n'

// The Trash page is one list (mockup T1): research, evidence tables, removed sources and table templates, newest first.
// Nothing here expires (T3). Research, tables and templates are deleted one at a time; a removed source can be deleted
// once nothing cites it (D65). Deleting asks inside the row, where the mockup asks.

// The row that is asking: what it says and what a yes does.
// `keys`: the rows a bulk confirmation is about; it lapses when one of them has left the Trash.
type Pending = { key: string; question: string; detail: string; confirm: () => void; from?: 'delete' | 'menu'; keys?: string[] }
type SourceTarget = { researchId: string; versions: RemovedSource[] }
type Sort = 'removed' | 'title' | 'year'
const sortLabels: Record<Sort, string> = { removed: 'Recently removed', title: 'Title', year: 'Year' }
// The row opened in the source sheet, on the abstract this research can still read (D50).
type OpenSource = { key: string; researchId: string; researchTitle: string; passageId: string }
type Entry = {
  key: string; at: string; kind: string; icon: LucideIcon; title: string; titleNode?: ReactNode; note: string
  restore: () => void; remove: Pending | null; deleteTitle?: string
  researchId: string | null; researchTitle: string | null; year: number
  source?: SourceTarget
  more?: { open: (() => void) | null; restoreAll: (() => void) | null; deleteAll: Pending | null }
}
const inspectable = (versions: RemovedSource[]) => versions.find(v => v.abstract_passage_id) ?? null

const dateText = (value: string) => new Date(value).toLocaleDateString(uiLocale(), { dateStyle: 'medium' })
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e))
// A long Trash shows this many rows until the reader asks for the rest, and then can filter them.
const ROW_LIMIT = 50

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

export function TrashPage({ dark, onChanged }: { dark: boolean; onChanged: () => void }) {
  const [trash, setTrash] = useState<Trash | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [pending, setPending] = useState<Pending | null>(null)
  const [query, setQuery] = useState('')
  const [whole, setWhole] = useState(false)
  const [scope, setScope] = useState<'all' | 'deletable' | 'cited'>('all')
  const [onlyResearch, setOnlyResearch] = useState('all')
  const [sort, setSort] = useState<Sort>('removed')
  const [grouped, setGrouped] = useState(false)
  const [folded, setFolded] = useState<Set<string>>(new Set())
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

  // A source an answer quote, a table or a report still cites is not offered for deletion: that evidence must keep opening (D65).
  const deletable = (versions: RemovedSource[]) => versions.every(v => !v.cited)

  const worksOf = (target: SourceTarget) => new Set(target.versions.map(v => v.work_id)).size
  // One call per research. A call that fails stops the rest; what finished stays finished and is said so, with the disk
  // warnings of the calls that did finish, and the page always refreshes.
  async function bulk(key: string, targets: SourceTarget[], verb: 'restore' | 'purge') {
    setBusy(key)
    setMessage('')
    let done = 0
    let files = 0
    let gone = 0  // asked for, but no requested version was changed: no longer in the Trash
    let partial = 0  // a delete took some of a work's requested versions and not the others
    let partialVersions = 0
    const finished = new Set<string>()
    let failure: { target: SourceTarget; message: string } | null = null
    let attempted = 0
    for (const one of targets) {
      attempted += 1
      try {
        const ids = one.versions.map(v => v.source_version_id)
        // What counts as done is what the backend says it changed, never what was asked for.
        let changed: Set<string>
        if (verb === 'purge') {
          const result = await api.purgeSources(one.researchId, ids)
          files += result.files_not_removed.length
          changed = new Set(result.deleted)
        } else changed = new Set((await api.restoreSources(one.researchId, ids)).changed_source_version_ids)
        const works = new Set(one.versions.map(v => v.work_id))
        for (const work of works) {
          const mine = one.versions.filter(v => v.work_id === work)
          const taken = mine.filter(v => changed.has(v.source_version_id)).length
          // A restore brings a work's versions back together, so one returned version means the work is back; a partial
          // restore cannot happen, and no message is written for one. A delete is done only when every requested version
          // went; some of them is partial (what is left is no longer in the Trash), none is unchanged.
          if (taken === 0) gone += 1
          else if (verb === 'restore' || taken === mine.length) { done += 1; finished.add(`${one.researchId}:${work}`) }
          else { partial += 1; partialVersions += taken; finished.add(`${one.researchId}:${work}`) }
        }
      } catch (e) { failure = { target: one, message: errorText(e) }; break }
    }
    const total = targets.reduce((n, one) => n + worksOf(one), 0)
    const diskNote = files ? t('{files} file(s) could not be removed from disk.', { files }) : ''
    if (!failure && gone === 0 && partial === 0) {
      setMessage(verb === 'purge'
        ? (files ? t('{n} source(s) deleted, but {files} file(s) could not be removed from disk.', { n: done, files })
          : t(done === 1 ? 'Source permanently deleted.' : '{n} sources permanently deleted.', { n: done }))
        : t(done === 1 ? 'Source restored.' : '{n} sources restored.', { n: done }))
    } else {
      const skipped = failure ? targets.slice(attempted).reduce((n, one) => n + worksOf(one), 0) : 0
      setMessage([verb === 'purge' ? t('Deleted {done} of {total} sources.', { done, total }) : t('Restored {done} of {total} sources.', { done, total }),
        partial > 0 && t('{n} source(s) partly deleted: {k} of their versions were deleted; the rest were no longer in the Trash.', { n: partial, k: partialVersions }),
        gone > 0 && t('{n} no longer in the Trash, so nothing was changed for them.', { n: gone }),
        failure && t('{n} in “{research}” failed: {message}', { n: worksOf(failure.target), research: failure.target.versions[0].research_title, message: failure.message }),
        skipped > 0 && t('{n} not attempted.', { n: skipped }), diskNote].filter(Boolean).join(' '))
    }
    if (done > 0 || partial > 0 || failure || gone > 0) onChanged()
    setPicked(prev => { const next = new Set(prev); for (const k of finished) next.delete(k); return next })
    setBusy(null)
    await refresh()
  }
  const purgeMany = (key: string, targets: SourceTarget[]) => void bulk(key, targets, 'purge')
  // restoreSources and purgeSources each take one research, so a choice across researches is one call per research.
  const perResearch = (picks: SourceTarget[]): SourceTarget[] => {
    const by = new Map<string, RemovedSource[]>()
    for (const pick of picks) by.set(pick.researchId, [...(by.get(pick.researchId) ?? []), ...pick.versions])
    return [...by].map(([researchId, versions]) => ({ researchId, versions }))
  }
  const toggled = (set: Set<string>, key: string) => { const next = new Set(set); if (!next.delete(key)) next.add(key); return next }
  // Returns focus to the row that asked, once the notice is gone.
  const closeAsk = (target: Pending | null) => {
    setPending(null)
    if (!target) return
    requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-trash-key="${CSS.escape(target.key)}"] ${target.from === 'menu' ? '.trash-sq' : '.trash-delete'}`)?.focus())
  }

  const sourceDetail = (count: number) => t(count === 1
    ? 'The research loses its record of this source, your decision and notes on it. Its library record, passages and PDF go too, unless another research holds it or you saved it to the library. This cannot be undone.'
    : 'The research loses its record of {n} sources, your decisions and notes on them. Their library records, passages and PDFs go too, unless another research holds them or you saved them to the library. This cannot be undone.', { n: count })

  const entries: Entry[] = []
  if (trash) {
    for (const r of trash.researches) {
      entries.push({
        key: r.id, at: r.trashed_at, kind: t('Research'), icon: FlaskConical, title: r.title, researchId: r.id, researchTitle: r.title, year: 0, note: t('Moved to Trash {date}', { date: dateText(r.trashed_at) }),
        restore: () => void run(r.id, async () => { await api.restore(r.id); return t('Research restored.') }, 'Could not restore research: {message}'),
        remove: {
          key: r.id, question: t('Delete “{title}” permanently?', { title: r.title }),
          detail: t('Its answers, decisions, run history, unshared evidence and files go with it. Sources another research holds and items you saved to the library stay. This cannot be undone.'),
          confirm: () => void run(r.id, async () => {
            const result = await api.deletePermanently(r.id)
            return result.files_not_removed.length
              ? t('Research deleted, but {n} file(s) could not be removed from disk.', { n: result.files_not_removed.length })
              : t('Research permanently deleted.')
          }, 'Could not permanently delete research: {message}'),
        },
      })
    }
    for (const table of trash.tables) {
      entries.push({
        key: table.id, at: table.trashed_at, kind: t('Evidence table'), icon: Table2, title: tableTitle(table.title), researchId: table.research_id, researchTitle: table.research_title, year: 0,
        note: [table.research_title, t(table.rows === 1 ? '{n} row' : '{n} rows', { n: table.rows }), t(table.columns === 1 ? '{n} column' : '{n} columns', { n: table.columns }),
          t(table.cells === 1 ? '{n} cell with a value' : '{n} cells with a value', { n: table.cells }),
          table.human_edits > 0 && t(table.human_edits === 1 ? '{n} edit of yours' : '{n} edits of yours', { n: table.human_edits }),
          t('Moved to Trash {date}', { date: dateText(table.trashed_at) })].filter(Boolean).join(' · '),
        restore: () => void run(table.id, async () => { await api.restoreTable(table.research_id, table.id, table.version); return t('Table restored to {research}.', { research: table.research_title }) }, 'Could not restore the table: {message}'),
        remove: {
          key: table.id, question: t('Delete “{title}” permanently?', { title: tableTitle(table.title) }),
          detail: t('Its rows, columns, {cells} cells with a value and {edits} edits of yours are deleted. Passages, files and answers stay. This cannot be undone.', { cells: table.cells, edits: table.human_edits }),
          confirm: () => void run(table.id, async () => { await api.purgeTable(table.id); return t('Table permanently deleted.') }, 'Could not delete the table: {message}'),
        },
      })
    }
    for (const group of sourceGroups(trash.sources)) {
      const deletableWorks = group.works.filter(deletable)
      for (const versions of group.works) {
        const first = versions[0]
        const key = `${group.id}:${first.work_id}`
        const openable = inspectable(versions)
        const canDelete = deletable(versions)
        const quotes = versions.reduce((n, v) => n + v.quotes, 0)
        const cells = versions.reduce((n, v) => n + v.cells, 0)
        const citedText = [quotes > 0 && t(quotes === 1 ? 'cited in {n} answer quote' : 'cited in {n} answer quotes', { n: quotes }),
          cells > 0 && t(cells === 1 ? '{n} table cell' : '{n} table cells', { n: cells })].filter(Boolean).join(', ') || t('still cited')
        const parts = [
          [...new Set(versions.map(v => versionText(v.version_label)))].join(', '),
          first.year !== null && String(first.year),
          t('removed from {research} on {date}', { research: group.title, date: dateText(first.removed_at) }),
          !canDelete && `${citedText}; ${t('deleted with its research')}`,
          versions.some(v => v.found_again_at) && t('found again by a later search'),
          first.removal_note && t('Your note: {note}', { note: first.removal_note }),
        ].filter(Boolean).join(' · ')
        entries.push({
          key, at: first.removed_at, kind: t('Source'), icon: FileText, title: first.title, note: parts, researchId: group.id, researchTitle: group.title, year: first.year ?? 0,
          source: { researchId: group.id, versions },
          titleNode: openable
            ? <button type="button" className="trash-title" title={first.title}
              onClick={() => setOpenSource({ key, researchId: group.id, researchTitle: group.title, passageId: openable.abstract_passage_id as string })}>{first.title}</button>
            : <span title={t('No abstract is stored for this source, so there is nothing to inspect here.')}>{first.title}</span>,
          restore: () => void run(key, async () => { await api.restoreSources(group.id, versions.map(v => v.source_version_id)); return t('Source restored to {research}.', { research: group.title }) }, 'Could not restore the sources: {message}'),
          remove: canDelete ? {
            key, question: t('Delete “{title}” permanently?', { title: first.title }), detail: sourceDetail(1),
            confirm: () => purgeMany(key, [{ researchId: group.id, versions }]), from: 'delete', keys: [key],
          } : null,
          more: {
            open: openable ? () => setOpenSource({ key, researchId: group.id, researchTitle: group.title, passageId: openable.abstract_passage_id as string }) : null,
            restoreAll: group.works.length > 1 ? () => void bulk(`${group.id}:all`, [{ researchId: group.id, versions: group.works.flat() }], 'restore') : null,
            deleteAll: deletableWorks.length > 1 ? {
              key, question: t('Delete {n} sources removed from “{title}” permanently?', { n: deletableWorks.length, title: group.title }), detail: sourceDetail(deletableWorks.length),
              confirm: () => purgeMany(`${group.id}:all`, [{ researchId: group.id, versions: deletableWorks.flat() }]), from: 'menu', keys: deletableWorks.map(v => `${group.id}:${v[0].work_id}`),
            } : null,
          },
        })
      }
    }
    for (const template of trash.templates) {
      entries.push({
        key: template.id, at: template.trashed_at, kind: t('Table template'), icon: LayoutTemplate, title: template.name, researchId: null, researchTitle: null, year: 0,
        note: `${t(template.columns === 1 ? '{n} column' : '{n} columns', { n: template.columns })} · ${t('Moved to Trash {date}', { date: dateText(template.trashed_at) })}`,
        restore: () => void run(template.id, async () => { await api.restoreTemplate(template.id); return t('Template restored.') }, 'Could not restore the template: {message}'),
        remove: {
          key: template.id, question: t('Delete “{title}” permanently?', { title: template.name }),
          detail: t('Its column definitions are deleted. Tables started from it keep their own columns. This cannot be undone.'),
          confirm: () => void run(template.id, async () => { await api.purgeTemplate(template.id); return t('Template permanently deleted.') }, 'Could not delete the template: {message}'),
        },
      })
    }
  }
  const sorters: Record<Sort, (a: Entry, b: Entry) => number> = {
    removed: (a, b) => b.at.localeCompare(a.at),
    title: (a, b) => a.title.localeCompare(b.title, uiLocale()),
    year: (a, b) => b.year - a.year || b.at.localeCompare(a.at),
  }
  const stillCited = entries.filter(e => e.source && !e.remove).length
  const researchOptions = [...new Map(entries.filter(e => e.researchId && e.researchTitle).map(e => [e.researchId as string, e.researchTitle as string])).entries()]

  // A research that has left the list cannot keep filtering it.
  const activeResearch = onlyResearch === 'all' || researchOptions.some(([id]) => id === onlyResearch) ? onlyResearch : 'all'
  const needle = query.trim().toLocaleLowerCase(uiLocale())
  const matching = entries
    .filter(e => (scope === 'all' || (scope === 'deletable') === (e.remove !== null)) && (activeResearch === 'all' || e.researchId === activeResearch)
      && (!needle || `${e.title} ${e.note}`.toLocaleLowerCase(uiLocale()).includes(needle)))
    .sort(sorters[sort])
  const shown = whole || needle ? matching : matching.slice(0, ROW_LIMIT)
  const shownSources = shown.filter(e => e.source)
  // Rows in a folded group are not on screen, so "shown" leaves them out.
  const visibleSources = grouped ? shownSources.filter(e => !folded.has(e.researchId as string)) : shownSources
  const pickedEntries = entries.filter(e => e.source && picked.has(e.key))
  const pickedDeletable = pickedEntries.filter(e => e.remove)
  const decide = (target: Pending) => setPending(target)
  // A confirmation about rows that have since left the Trash (restored elsewhere, deleted) no longer describes it.
  const present = new Set(entries.map(e => e.key))
  const lapsed = pending?.keys ? !pending.keys.every(k => present.has(k)) : false
  const livePending = lapsed ? null : pending

  const rowFor = (entry: Entry) => livePending?.key === entry.key
    ? <div className="trash-row trash-notice" key={entry.key} role="group" aria-label={t('Delete permanently?')} data-trash-key={entry.key}
      onKeyDown={event => { if (event.key === 'Escape') closeAsk(livePending) }}>
      <TriangleAlert size={16} aria-hidden />
      <div className="trash-notice-body"><span>{livePending.question} {livePending.detail}</span>
        <div className="trash-acts">
          <button type="button" className="trash-ghost trash-delete" onClick={() => { const target = livePending; setPending(null); target?.confirm() }}>{t('Delete permanently')}</button>
          <button type="button" className="trash-ghost" autoFocus onClick={() => closeAsk(livePending)}>{t('Cancel')}</button>
        </div></div>
    </div>
    : <div className={`trash-row${picked.has(entry.key) ? ' is-picked' : ''}`} key={entry.key} data-trash-key={entry.key}>
      <b>{entry.source && <input type="checkbox" className="trash-pick" checked={picked.has(entry.key)} aria-label={t('Select {title}', { title: entry.title })}
        onChange={() => setPicked(toggled(picked, entry.key))} />}<span className="trash-kind-icon" aria-hidden><entry.icon size={16} /></span><span className="trash-kind">{entry.kind}</span></b>
      <p><span className="trash-row-title">{entry.titleNode ?? entry.title}</span><span className="trash-row-sep"> · </span><span className="trash-row-note"><span className="trash-row-kind" aria-hidden>{entry.kind}</span> · {entry.note}</span></p>
      <button type="button" className="trash-ghost trash-restore" disabled={busy === entry.key} aria-label={t('Restore {title}', { title: entry.title })} onClick={entry.restore}><RotateCcw size={14} aria-hidden />{t('Restore')}</button>
      <button type="button" className="trash-ghost trash-delete" disabled={busy === entry.key || !entry.remove} aria-label={t('Delete permanently: {title}', { title: entry.title })}
        title={entry.remove ? undefined : t('An answer quote, an evidence table or a report still cites this source. It is deleted with its research.')}
        onClick={() => entry.remove && decide({ ...entry.remove, from: 'delete' })}><Trash2 size={14} aria-hidden />{t('Delete permanently')}</button>
      {entry.more && (entry.more.open || entry.more.restoreAll || entry.more.deleteAll) && <DropdownMenu>
        <DropdownMenuTrigger className="trash-ghost trash-sq" aria-label={t('Actions for {title}', { title: entry.title })} title={t('More actions')}><Ellipsis size={15} aria-hidden /></DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-auto">
          {entry.more.open && <DropdownMenuItem onClick={entry.more.open}>{t('Open source details')}</DropdownMenuItem>}
          {entry.more.restoreAll && <DropdownMenuItem onClick={entry.more.restoreAll}>{t('Restore all from this research')}</DropdownMenuItem>}
          {entry.more.deleteAll && <>
            {(entry.more.open || entry.more.restoreAll) && <DropdownMenuSeparator />}
            <DropdownMenuItem variant="destructive" onClick={() => entry.more?.deleteAll && decide({ ...entry.more.deleteAll, from: 'menu' })}><Trash2 size={15} />{t('Delete all deletable from this research permanently')}</DropdownMenuItem>
          </>}
        </DropdownMenuContent>
      </DropdownMenu>}
    </div>

  // Grouped by research: the sources of one research sit under a head row that folds them and picks them together.
  const loose = grouped ? shown.filter(e => !e.source) : shown
  const groups = grouped ? [...shownSources.reduce((m, e) => m.set(e.researchId as string, [...(m.get(e.researchId as string) ?? []), e]), new Map<string, Entry[]>())] : []

  return <section className="trash-page">
    <h1 tabIndex={-1}>{t('Trash')}</h1>
    <p className="trash-foot trash-sub">{t('Nothing in the Trash expires.')}</p>
    {message && <div className="trash-message" role="status"><Info size={16} aria-hidden />{message}</div>}
    {error ? <p role="alert">{t('Could not load Trash: {message}', { message: error })} <button type="button" className="trash-ghost" onClick={() => { void refresh() }}>{t('Retry')}</button></p>
      : !trash ? <p role="status">{t('Loading Trash…')}</p>
      : entries.length === 0 ? <div className="trash-empty"><div><Trash2 size={16} aria-hidden /><h2>{t('The Trash is empty')}</h2>
        <p>{t('Research and sources you remove wait here until you restore or delete them.')}</p></div></div>
      : <>
        <div className="trash-tools">
          <div className="trash-search" role="search">
            <Search size={15} aria-hidden />
            <input type="search" value={query} onChange={event => setQuery(event.target.value)}
              placeholder={t('Filter by title or research')} aria-label={t('Filter the Trash')} />
          </div>
          <div className="trash-scope" role="group" aria-label={t('Which removed sources to show')}>
            <button type="button" aria-pressed={scope === 'all'} onClick={() => setScope('all')}>{t('All')} {entries.length}</button>
            <button type="button" aria-pressed={scope === 'deletable'} onClick={() => setScope('deletable')}>{t('Deletable')} {entries.length - stillCited}</button>
            <button type="button" aria-pressed={scope === 'cited'} onClick={() => setScope('cited')}>{t('Still cited')} {stillCited}</button>
          </div>
          {(researchOptions.length > 1 || activeResearch !== 'all') && <div className="trash-select">
            <span id="trash-research-filter">{t('Research')}</span>
            <Select value={activeResearch} onValueChange={value => { if (value) setOnlyResearch(value as string) }}>
              <SelectTrigger aria-labelledby="trash-research-filter"><SelectValue>{(value: string) =>
                value === 'all' ? t('All {n} research', { n: researchOptions.length }) : researchOptions.find(([id]) => id === value)?.[1] ?? ''}</SelectValue></SelectTrigger>
              <SelectContent align="end">
                <SelectItem value="all">{t('All {n} research', { n: researchOptions.length })}</SelectItem>
                {researchOptions.map(([id, title]) => <SelectItem key={id} value={id}>{title}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>}
          <div className="trash-select">
            <span id="trash-sort">{t('Sort')}</span>
            <Select value={sort} onValueChange={value => { if (value) setSort(value as Sort) }}>
              <SelectTrigger aria-labelledby="trash-sort"><SelectValue>{(value: string) => t(sortLabels[value as Sort])}</SelectValue></SelectTrigger>
              <SelectContent align="end">
                {(Object.keys(sortLabels) as Sort[]).map(order => <SelectItem key={order} value={order}>{t(sortLabels[order])}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <button type="button" className="trash-ghost" aria-pressed={grouped} onClick={() => setGrouped(!grouped)}>{t('Group by research')}</button>
          {visibleSources.length > 0 && <label className="trash-pick-all"><input type="checkbox" className="trash-pick" aria-label={t('Select the {n} sources shown here', { n: visibleSources.length })}
            checked={visibleSources.every(e => picked.has(e.key))}
            onChange={event => { const next = new Set(picked); for (const e of visibleSources) { if (event.target.checked) next.add(e.key); else next.delete(e.key) } setPicked(next) }} />{t('Select the sources shown')}</label>}
        </div>
        {shown.length === 0 && <p className="trash-foot">{t('No removed source matches this filter.')}</p>}
        {shown.length > 0 && <div className="trash-rows">
          {loose.map(rowFor)}
          {groups.map(([researchId, list]) => {
            const isFolded = folded.has(researchId)
            const title = list[0].researchTitle as string
            return <div className="trash-group" key={researchId}>
              <div className="trash-row trash-group-head">
                <button type="button" className="trash-fold" aria-expanded={!isFolded}
                  aria-label={t(isFolded ? 'Show the sources removed from {research}' : 'Hide the sources removed from {research}', { research: title })}
                  onClick={() => setFolded(toggled(folded, researchId))}>{isFolded ? <ChevronRight size={15} aria-hidden /> : <ChevronDown size={15} aria-hidden />}</button>
                <b>{title}</b>
                <p>{t(list.length === 1 ? '{n} source' : '{n} sources', { n: list.length })}</p>
                <input type="checkbox" className="trash-pick" aria-label={t('Select the {n} sources of {research}', { n: list.length, research: title })}
                  checked={list.every(e => picked.has(e.key))}
                  onChange={event => { const next = new Set(picked); for (const e of list) { if (event.target.checked) next.add(e.key); else next.delete(e.key) } setPicked(next) }} />
              </div>
              {!isFolded && list.map(rowFor)}
            </div>
          })}
        </div>}
        {!whole && !needle && matching.length > ROW_LIMIT && <button type="button" className="trash-ghost trash-showmore" onClick={() => setWhole(true)}>{t('Show {n} more', { n: matching.length - ROW_LIMIT })}</button>}
        {lapsed && <p className="trash-foot" role="status">{t('The sources you chose to delete changed, so nothing was deleted. Choose again.')}</p>}
        {livePending?.key === 'picked' && <div className="trash-notice trash-bar-notice" role="group" aria-label={t('Delete permanently?')}
          onKeyDown={event => { if (event.key === 'Escape') closeAsk(livePending) }}>
          <TriangleAlert size={16} aria-hidden />
          <div className="trash-notice-body"><span>{livePending.question} {livePending.detail}</span>
            <div className="trash-acts">
              <button type="button" className="trash-ghost trash-delete" onClick={() => { const target = livePending; setPending(null); target?.confirm() }}>{t('Delete permanently')}</button>
              <button type="button" className="trash-ghost" autoFocus onClick={() => closeAsk(livePending)}>{t('Cancel')}</button>
            </div></div>
        </div>}
        {pickedEntries.length > 0 && <div className="selection-bar" data-trash-key="picked">
          <strong>{t(pickedEntries.length === 1 ? '{n} source selected' : '{n} sources selected', { n: pickedEntries.length })}
            <span>{[t('{n} deletable', { n: pickedDeletable.length }), t('from {n} research', { n: new Set(pickedEntries.map(e => e.researchId)).size })].join(' · ')}</span></strong>
          <div className="selection-bar-actions">
            <button type="button" className="trash-ghost" disabled={busy === 'picked'} onClick={() => void bulk('picked', perResearch(pickedEntries.map(e => e.source as SourceTarget)), 'restore')}>{t('Restore')}</button>
            <button type="button" className="trash-ghost trash-delete" disabled={busy === 'picked' || pickedDeletable.length === 0}
              title={pickedDeletable.length === 0 ? t('An answer quote, an evidence table or a report still cites this source. It is deleted with its research.') : undefined}
              onClick={() => decide({ key: 'picked', from: 'delete', keys: pickedDeletable.map(e => e.key), question: t('Delete {n} sources permanently?', { n: pickedDeletable.length }), detail: sourceDetail(pickedDeletable.length),
                confirm: () => purgeMany('picked', perResearch(pickedDeletable.map(e => e.source as SourceTarget))) })}>{t('Delete permanently')}</button>
            <button type="button" className="trash-ghost" onClick={() => setPicked(new Set())}>{t('Clear selection')}</button>
          </div>
        </div>}
      </>}
    {openSource && <PassageSheet researchId={openSource.researchId} passageId={openSource.passageId}
      dark={dark} onClose={() => setOpenSource(null)}
      onRestoreSource={sourceVersionId => {
        const target = openSource
        setOpenSource(null)
        void run(target.key, async () => { await api.restoreSources(target.researchId, [sourceVersionId]); return t('Source restored to {research}.', { research: target.researchTitle }) }, 'Could not restore the sources: {message}')
      }} />}
  </section>
}
