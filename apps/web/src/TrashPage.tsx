import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Ellipsis, Info, Search, Trash2, TriangleAlert } from 'lucide-react'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { api, type RemovedSource, type Trash } from './api'
import { versionText } from './labels'
import { PassageSheet } from './PassageSheet'
import { t, uiLocale } from './i18n'

// The Trash page is one list (mockup T1): research, evidence tables, removed sources and table templates, newest first.
// Nothing here expires (T3). Research, tables and templates are deleted one at a time; a removed source can be deleted
// once nothing cites it (D65). Deleting asks inside the row, where the mockup asks.

// The row that is asking: what it says and what a yes does.
type Pending = { key: string; question: string; detail: string; confirm: () => void }
// The row opened in the source sheet, on the abstract this research can still read (D50).
type OpenSource = { key: string; researchId: string; researchTitle: string; passageId: string }
type Entry = {
  key: string; at: string; kind: string; title: string; titleNode?: ReactNode; note: string
  restore: () => void; remove: Pending | null; deleteTitle?: string
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

  function purgeSources(key: string, groupSources: RemovedSource[][], researchId: string) {
    const versions = groupSources.flat()
    void run(key, async () => {
      const result = await api.purgeSources(researchId, versions.map(v => v.source_version_id))
      return result.files_not_removed.length
        ? t('{n} source(s) deleted, but {files} file(s) could not be removed from disk.', { n: result.deleted.length, files: result.files_not_removed.length })
        : t(result.deleted.length === 1 ? 'Source permanently deleted.' : '{n} sources permanently deleted.', { n: result.deleted.length })
    }, 'Could not delete the sources: {message}')
  }

  const sourceDetail = (count: number) => t(count === 1
    ? 'The research loses its record of this source, your decision and notes on it. Its library record, passages and PDF go too, unless another research holds it or you saved it to the library. This cannot be undone.'
    : 'The research loses its record of {n} sources, your decisions and notes on them. Their library records, passages and PDFs go too, unless another research holds them or you saved them to the library. This cannot be undone.', { n: count })

  const entries: Entry[] = []
  if (trash) {
    for (const r of trash.researches) {
      entries.push({
        key: r.id, at: r.trashed_at, kind: t('Research'), title: r.title, note: t('Moved to Trash {date}', { date: dateText(r.trashed_at) }),
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
        key: table.id, at: table.trashed_at, kind: t('Evidence table'), title: table.title,
        note: [table.research_title, t(table.rows === 1 ? '{n} row' : '{n} rows', { n: table.rows }), t(table.columns === 1 ? '{n} column' : '{n} columns', { n: table.columns }),
          t(table.cells === 1 ? '{n} cell with a value' : '{n} cells with a value', { n: table.cells }),
          table.human_edits > 0 && t(table.human_edits === 1 ? '{n} edit of yours' : '{n} edits of yours', { n: table.human_edits }),
          t('Moved to Trash {date}', { date: dateText(table.trashed_at) })].filter(Boolean).join(' · '),
        restore: () => void run(table.id, async () => { await api.restoreTable(table.research_id, table.id, table.version); return t('Table restored to {research}.', { research: table.research_title }) }, 'Could not restore the table: {message}'),
        remove: {
          key: table.id, question: t('Delete “{title}” permanently?', { title: table.title }),
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
          key, at: first.removed_at, kind: t('Source'), title: first.title, note: parts,
          titleNode: openable
            ? <button type="button" className="trash-title" title={first.title}
              onClick={() => setOpenSource({ key, researchId: group.id, researchTitle: group.title, passageId: openable.abstract_passage_id as string })}>{first.title}</button>
            : <span title={t('No abstract is stored for this source, so there is nothing to inspect here.')}>{first.title}</span>,
          restore: () => void run(key, async () => { await api.restoreSources(group.id, versions.map(v => v.source_version_id)); return t('Source restored to {research}.', { research: group.title }) }, 'Could not restore the sources: {message}'),
          remove: canDelete ? {
            key, question: t('Delete “{title}” permanently?', { title: first.title }), detail: sourceDetail(1),
            confirm: () => purgeSources(key, [versions], group.id),
          } : null,
          more: {
            open: openable ? () => setOpenSource({ key, researchId: group.id, researchTitle: group.title, passageId: openable.abstract_passage_id as string }) : null,
            restoreAll: group.works.length > 1 ? () => void run(`${group.id}:all`, async () => { await api.restoreSources(group.id, group.works.flat().map(s => s.source_version_id)); return t('{n} sources restored to {research}.', { n: group.works.length, research: group.title }) }, 'Could not restore the sources: {message}') : null,
            deleteAll: deletableWorks.length > 1 ? {
              key, question: t('Delete {n} sources removed from “{title}” permanently?', { n: deletableWorks.length, title: group.title }), detail: sourceDetail(deletableWorks.length),
              confirm: () => purgeSources(`${group.id}:all`, deletableWorks, group.id),
            } : null,
          },
        })
      }
    }
    for (const template of trash.templates) {
      entries.push({
        key: template.id, at: template.trashed_at, kind: t('Table template'), title: template.name,
        note: `${t(template.columns === 1 ? '{n} column' : '{n} columns', { n: template.columns })} · ${t('Moved to Trash {date}', { date: dateText(template.trashed_at) })}`,
        restore: () => void run(template.id, async () => { await api.restoreTemplate(template.id); return t('Template restored.') }, 'Could not restore the template: {message}'),
        remove: {
          key: template.id, question: t('Delete “{title}” permanently?', { title: template.name }),
          detail: t('Its column definitions are deleted. Tables started from it keep their own columns. This cannot be undone.'),
          confirm: () => void run(template.id, async () => { await api.purgeTemplate(template.id); return t('Template permanently deleted.') }, 'Could not delete the template: {message}'),
        },
      })
    }
    entries.sort((a, b) => b.at.localeCompare(a.at))
  }

  const needle = query.trim().toLocaleLowerCase(uiLocale())
  const matching = needle ? entries.filter(e => `${e.title} ${e.note}`.toLocaleLowerCase(uiLocale()).includes(needle)) : entries
  const shown = whole || needle ? matching : matching.slice(0, ROW_LIMIT)
  const decide = (target: Pending) => { setPending(target) }

  return <section className="trash-page">
    <h1 tabIndex={-1}>{t('Trash')}</h1>
    {message && <div className="trash-message" role="status"><Info size={16} aria-hidden />{message}</div>}
    {error ? <p role="alert">{t('Could not load Trash: {message}', { message: error })} <button type="button" className="trash-ghost" onClick={() => { void refresh() }}>{t('Retry')}</button></p>
      : !trash ? <p role="status">{t('Loading Trash…')}</p>
      : entries.length === 0 ? <div className="trash-empty"><div><Trash2 size={16} aria-hidden /><h2>{t('The Trash is empty')}</h2>
        <p>{t('Research and sources you remove wait here until you restore or delete them.')}</p></div></div>
      : <>
        {entries.length > ROW_LIMIT && <div className="trash-search" role="search">
          <Search size={15} aria-hidden />
          <input type="search" value={query} onChange={event => setQuery(event.target.value)}
            placeholder={t('Filter by title or research')} aria-label={t('Filter the Trash')} />
        </div>}
        <div className="trash-rows">
          {shown.map(entry => pending?.key === entry.key
            ? <div className="trash-row trash-notice" key={entry.key} role="group" aria-label={t('Delete permanently?')}
              onKeyDown={event => { if (event.key === 'Escape') setPending(null) }}>
              <TriangleAlert size={16} aria-hidden />
              <div className="trash-notice-body"><span>{pending.question} {pending.detail}</span>
                <div className="trash-acts">
                  <button type="button" className="trash-ghost trash-delete" onClick={() => { const target = pending; setPending(null); target.confirm() }}>{t('Delete permanently')}</button>
                  <button type="button" className="trash-ghost" autoFocus onClick={() => setPending(null)}>{t('Cancel')}</button>
                </div></div>
            </div>
            : <div className="trash-row" key={entry.key}>
              <b>{entry.kind}</b>
              <p>{entry.titleNode ?? entry.title} · {entry.note}</p>
              <button type="button" className="trash-ghost trash-restore" disabled={busy === entry.key} aria-label={t('Restore {title}', { title: entry.title })} onClick={entry.restore}>{t('Restore')}</button>
              <button type="button" className="trash-ghost trash-delete" disabled={busy === entry.key || !entry.remove} aria-label={t('Delete permanently: {title}', { title: entry.title })}
                title={entry.remove ? undefined : t('An answer quote, an evidence table or a report still cites this source. It is deleted with its research.')}
                onClick={() => entry.remove && decide(entry.remove)}>{t('Delete permanently')}</button>
              {entry.more && (entry.more.open || entry.more.restoreAll || entry.more.deleteAll) && <DropdownMenu>
                <DropdownMenuTrigger className="trash-ghost trash-sq" aria-label={t('Actions for {title}', { title: entry.title })} title={t('More actions')}><Ellipsis size={15} aria-hidden /></DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-auto">
                  {entry.more.open && <DropdownMenuItem onClick={entry.more.open}>{t('Open source details')}</DropdownMenuItem>}
                  {entry.more.restoreAll && <DropdownMenuItem onClick={entry.more.restoreAll}>{t('Restore all from this research')}</DropdownMenuItem>}
                  {entry.more.deleteAll && <>
                    {(entry.more.open || entry.more.restoreAll) && <DropdownMenuSeparator />}
                    <DropdownMenuItem variant="destructive" onClick={() => entry.more?.deleteAll && decide(entry.more.deleteAll)}><Trash2 size={15} />{t('Delete all deletable from this research permanently')}</DropdownMenuItem>
                  </>}
                </DropdownMenuContent>
              </DropdownMenu>}
            </div>)}
        </div>
        {!whole && !needle && matching.length > ROW_LIMIT && <button type="button" className="trash-ghost trash-showmore" onClick={() => setWhole(true)}>{t('Show {n} more', { n: matching.length - ROW_LIMIT })}</button>}
        {needle && matching.length === 0 && <p className="trash-foot">{t('No removed source matches this filter.')}</p>}
      </>}
    <p className="trash-foot">{t('Nothing in the Trash expires.')}</p>
    {openSource && <PassageSheet researchId={openSource.researchId} passageId={openSource.passageId}
      dark={dark} onClose={() => setOpenSource(null)}
      onRestoreSource={sourceVersionId => {
        const target = openSource
        setOpenSource(null)
        void run(target.key, async () => { await api.restoreSources(target.researchId, [sourceVersionId]); return t('Source restored to {research}.', { research: target.researchTitle }) }, 'Could not restore the sources: {message}')
      }} />}
  </section>
}
