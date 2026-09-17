import { useCallback, useEffect, useState } from 'react'
import { RotateCcw, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from './ConfirmDialog'
import { api, type RemovedSource, type Trash, type TrashedResearch, type TrashedTable, type TrashedTemplate } from './api'
import { versionText } from './labels'
import { t, uiLocale } from './i18n'

// The Trash page groups what was moved to the trash or removed from a research (D50). Nothing here expires. Tables and
// templates can be deleted one at a time; a removed source is deleted permanently only with its research.

type Pending = { kind: 'research'; item: TrashedResearch } | { kind: 'table'; item: TrashedTable } | { kind: 'template'; item: TrashedTemplate }

const dateText = (value: string) => new Date(value).toLocaleDateString(uiLocale(), { dateStyle: 'medium' })
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

export function TrashPage({ dark, onChanged }: { dark: boolean; onChanged: () => void }) {
  const [trash, setTrash] = useState<Trash | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [pending, setPending] = useState<Pending | null>(null)

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
    else void run(target.item.id, async () => { await api.purgeTemplate(target.item.id); return t('Template permanently deleted.') }, 'Could not delete the template: {message}')
  }

  const groups = trash ? sourceGroups(trash.sources) : []
  const empty = trash && !trash.researches.length && !trash.tables.length && !trash.sources.length && !trash.templates.length
  const deleteButton = (target: Pending) => <Button variant="destructive" className="trash-delete" disabled={busy === target.item.id} onClick={() => setPending(target)}><Trash2 size={15} />{t('Delete permanently')}</Button>
  const pendingTitle = pending ? (pending.kind === 'template' ? pending.item.name : pending.item.title) : ''
  const pendingText = !pending ? ''
    : pending.kind === 'research' ? t('Its unshared evidence and files are removed too. Sources shared with other research stay. This cannot be undone.')
    : pending.kind === 'table' ? t('Its rows, columns, {cells} cells with a value and {edits} edits of yours are deleted. Passages, files and answers stay. This cannot be undone.', { cells: pending.item.cells, edits: pending.item.human_edits })
    : t('Its column definitions are deleted. Tables started from it keep their own columns. This cannot be undone.')

  return <section className="trash-page">
    <h1>{t('Trash')}</h1>
    <p className="trash-hint">{t('Research, evidence tables, templates and sources removed from a research wait here until you restore or delete them. Nothing in the Trash expires.')}</p>
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
          <h2 id="trash-sources">{t('Sources removed from a research')}<span>{groups.reduce((n, g) => n + g.works.length, 0)}</span></h2>
          <p className="trash-group-note">{t('The library record and its PDF were not deleted, and earlier quotes still open. A removed source is deleted permanently only with its research.')}</p>
          {groups.map(group => <div className="trash-research" key={group.id}>
            <div className="trash-research-head"><h3 title={group.title}>{group.title}</h3>
              {group.works.length > 1 && <Button variant="ghost" size="sm" disabled={busy === group.id} onClick={() => run(group.id, async () => { await api.restoreSources(group.id, group.works.flat().map(s => s.source_version_id)); return t('{n} sources restored to {research}.', { n: group.works.length, research: group.title }) }, 'Could not restore the sources: {message}')}><RotateCcw size={14} />{t('Restore all')}</Button>}
            </div>
            {group.works.map(versions => {
              const first = versions[0]
              const quotes = versions.reduce((n, v) => n + v.quotes, 0)
              const cells = versions.reduce((n, v) => n + v.cells, 0)
              const key = `${group.id}:${first.work_id}`
              return <div className="trash-row" key={key}>
                <span className="trash-item"><strong title={first.title}>{first.title}</strong>
                  <small>{[versions.map(v => versionText(v.version_label)).join(', '), first.year, t('Removed {date}', { date: dateText(first.removed_at) }),
                    quotes > 0 && t(quotes === 1 ? 'cited in {n} answer quote' : 'cited in {n} answer quotes', { n: quotes }),
                    cells > 0 && t(cells === 1 ? '{n} table cell' : '{n} table cells', { n: cells }),
                    versions.some(v => v.found_again_at) && t('found again by a later search')].filter(Boolean).join(' · ')}</small>
                  {first.removal_note && <small className="trash-note">{t('Your note: {note}', { note: first.removal_note })}</small>}
                </span>
                <div><Button variant="outline" disabled={busy === key} onClick={() => run(key, async () => { await api.restoreSources(group.id, versions.map(v => v.source_version_id)); return t('Source restored to {research}.', { research: group.title }) }, 'Could not restore the sources: {message}')}><RotateCcw size={15} />{t('Restore')}</Button></div>
              </div>
            })}
          </div>)}
        </section>}
        {trash.templates.length > 0 && <section className="trash-group" aria-labelledby="trash-templates">
          <h2 id="trash-templates">{t('Table templates')}<span>{trash.templates.length}</span></h2>
          {trash.templates.map(template => <div className="trash-row" key={template.id}>
            <span className="trash-item"><strong title={template.name}>{template.name}</strong><small>{t(template.columns === 1 ? '{n} column' : '{n} columns', { n: template.columns })} · {t('Moved to Trash {date}', { date: dateText(template.trashed_at) })}</small></span>
            <div><Button variant="outline" disabled={busy === template.id} onClick={() => run(template.id, async () => { await api.restoreTemplate(template.id); return t('Template restored.') }, 'Could not restore the template: {message}')}><RotateCcw size={15} />{t('Restore')}</Button>{deleteButton({ kind: 'template', item: template })}</div>
          </div>)}
        </section>}
      </>}
    <ConfirmDialog open={pending !== null} dark={dark} title={t('Delete permanently?')} description={pendingText} context={pendingTitle}
      confirmLabel={t('Delete permanently')} cancelLabel={t('Cancel')} onConfirm={() => pending && deletePermanently(pending)} onOpenChange={open => { if (!open) setPending(null) }} />
  </section>
}
