import { useEffect, useState } from 'react'
import { FolderOpen } from 'lucide-react'
import { ApiError, dataLocationApi, libraryApi, type DataLocation } from './api'
import { ConfirmDialog } from './ConfirmDialog'
import { Notice } from './Notice'
import { useToast } from './Toast'
import { t, uiLocale } from './i18n'

// Where the library lives (D32): the folder, its size by part, the free space on its disk, and a change that takes
// effect the next time DEIXIS starts. DEIXIS never moves the open library while it runs.
const size = (bytes: number) => {
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes, unit = 0
  while (value >= 1000 && unit < units.length - 1) { value /= 1000; unit++ }
  return `${value.toLocaleString(uiLocale(), { maximumFractionDigits: unit && value < 10 ? 1 : 0 })} ${units[unit]}`
}

export function DataLocationCard({ dark }: { dark: boolean }) {
  const toast = useToast()
  const [view, setView] = useState<DataLocation | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [typed, setTyped] = useState<string | null>(null)  // the path field, when this system has no folder chooser
  const [confirm, setConfirm] = useState<{ path: string; hasLibrary: boolean; sync: string | null } | null>(null)
  useEffect(() => {
    let live = true
    dataLocationApi.get().then(v => { if (live) setView(v) }, (e: Error) => { if (live) setError(e.message) })
    return () => { live = false }
  }, [])

  const blocked = !view ? '' : view.set_outside_app ? t('This location is set outside the app.')
    : view.running_runs ? t(view.running_runs === 1 ? '{n} research run still running. Finish or stop it before changing location.' : '{n} research runs still running. Finish or stop them before changing location.', { n: view.running_runs })
    : ''

  const check = (path: string) => {
    setBusy(true); setError('')
    dataLocationApi.check(path).then(r => { setTyped(null); setConfirm({ path: r.path, hasLibrary: r.has_library, sync: r.sync_service }) })
      .catch((e: Error) => setError(e.message)).finally(() => setBusy(false))
  }
  const choose = () => {
    setBusy(true); setError('')
    dataLocationApi.choose().then(r => { setBusy(false); if (r.path) check(r.path) })
      .catch((e: Error) => { setBusy(false); if (e instanceof ApiError && e.status === 501) setTyped(''); else setError(e.message) })
  }
  const save = (path: string) => {
    setBusy(true); setError('')
    dataLocationApi.change(path).then(v => {
      setView(v); setConfirm(null)
      toast('success', v.pending_path ? t('DEIXIS will use the new location after a restart.') : t('DEIXIS keeps its current location.'))
    }).catch((e: Error) => { setConfirm(null); setError(e.message) }).finally(() => setBusy(false))
  }

  // Back up, export and clear: each answers with a toast or the error line under the card.
  const backUp = () => {
    setBusy(true); setError('')
    dataLocationApi.backup().then(v => { setView(v); toast('success', t('Backup written to {path}.', { path: v.last_backup?.path ?? '' })) })
      .catch((e: Error) => setError(e.message)).finally(() => setBusy(false))
  }
  const reveal = () => { dataLocationApi.revealBackup().catch((e: Error) => setError(e.message)) }
  const exportLibrary = async (format: 'bibtex' | 'ris') => {
    setBusy(true); setError('')
    try {
      const { blob, filename } = await libraryApi.bibliography({ format, every_work: true })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      URL.revokeObjectURL(url)
      toast('success', t('{file} saved.', { file: filename }))
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  const clearCache = () => {
    setBusy(true); setError('')
    dataLocationApi.clearCache().then(v => { setView(v); toast('success', t('Download cache cleared.')) })
      .catch((e: Error) => setError(e.message)).finally(() => setBusy(false))
  }

  const parts = view?.breakdown.filter(p => p.bytes > 0) ?? []
  return <div className="data-location" data-group="data-location" data-panel="general">
    <div className="dl-head">
      <FolderOpen size={16} aria-hidden />
      <p><b>{t('Data location')}</b><small>{t('Where DEIXIS keeps your library, PDFs and history on this computer')}</small></p>
      <button type="button" className="ghost" disabled={!view || busy || !!blocked || typed !== null} onClick={choose}>{t('Change location')}</button>
    </div>
    {view && <>
      <code className="dl-path" title={view.path}>{view.path}</code>
      <p className="dl-size tnum">{t(view.is_default ? '{size} on disk · default location' : '{size} on disk · custom location', { size: size(view.size_bytes) })}</p>
      {view.size_bytes > 0 && <span className="dl-bar" aria-hidden>{parts.map(p => <i key={p.key} data-part={p.key} style={{ width: `${(p.bytes / view.size_bytes) * 100}%` }} />)}</span>}
      <ul className="dl-legend">
        {parts.map(p => <li key={p.key} data-part={p.key}><span className="dl-dot" aria-hidden />{t(p.label)}<span className="tnum">{size(p.bytes)}</span></li>)}
      </ul>
      {view.free_bytes !== null && <p className="dl-free">{t('Available on disk')}<span className="tnum">{size(view.free_bytes)}</span></p>}
      {view.pending_path && <Notice tone="attention">{view.move_postponed
        ? t('The library was not moved to {path}: another DEIXIS, a tool install or an equation reading was using {busy}. Close it, then restart DEIXIS to finish the move.', view.move_postponed)
        : t('Restart DEIXIS to use {path}.', { path: view.pending_path })}{' '}
        <button type="button" className="link" disabled={busy} onClick={() => save(view.path)}>{t('Keep current location')}</button></Notice>}
      {blocked && <p className="dl-reason">{blocked}</p>}
    </>}
    {view && <div className="dl-actions">
      <div>
        <p><b>{t('Backup')}</b><small>{view.last_backup ? t('Last backup {time}, in Documents/DEIXIS backups.', { time: new Date(view.last_backup.at).toLocaleString(uiLocale(), { dateStyle: 'medium', timeStyle: 'short' }) })
          : t('A full copy of the library and its PDFs, in Documents/DEIXIS backups.')}</small></p>
        {view.last_backup && <button type="button" className="link" onClick={reveal}>{t('Show in Finder')}</button>}
        <button type="button" className="ghost" disabled={busy} onClick={backUp}>{t('Back up now')}</button>
      </div>
      <div>
        <p><b>{t('Export Library')}</b><small>{t('Every work in the Library as a reference file for Zotero, EndNote or LaTeX.')}</small></p>
        <button type="button" className="ghost" disabled={busy} onClick={() => void exportLibrary('bibtex')}>BibTeX</button>
        <button type="button" className="ghost" disabled={busy} onClick={() => void exportLibrary('ris')}>RIS</button>
      </div>
      <div>
        <p><b>{t('Download cache')}</b><small>{view.cache_bytes ? t('{size} of installer downloads. Installed tools keep working; a later install downloads again.', { size: size(view.cache_bytes) }) : t('Empty. Tool installs keep their downloads here.')}</small></p>
        <button type="button" className="ghost" disabled={busy || view.cache_bytes === 0} onClick={clearCache}>{t('Clear')}</button>
      </div>
    </div>}
    {typed !== null && <form className="dl-typed" onSubmit={e => { e.preventDefault(); if (typed.trim()) check(typed.trim()) }}>
      <label htmlFor="data-location-path">{t('Folder path')}</label>
      <input id="data-location-path" className="field" type="text" spellCheck={false} autoComplete="off" value={typed} disabled={busy}
        placeholder={view?.path} onChange={e => setTyped(e.target.value)} autoFocus />
      <button type="submit" className="ghost" disabled={busy || !typed.trim()}>{t('Use this folder')}</button>
      <button type="button" className="link" disabled={busy} onClick={() => setTyped(null)}>{t('Cancel')}</button>
    </form>}
    {error && <Notice tone="error">{error}</Notice>}
    <ConfirmDialog open={confirm !== null} dark={dark} neutral title={t('Change where DEIXIS keeps its library?')}
      description={confirm?.hasLibrary ? t('That folder already has a DEIXIS library. DEIXIS will open it next time and leave the current one where it is.')
        : t('DEIXIS will move your library to {path} the next time it starts.', { path: confirm?.path ?? '' })}
      context={confirm?.path} confirmLabel={t('Change location')} cancelLabel={t('Cancel')} busy={busy}
      onConfirm={() => confirm && save(confirm.path)} onOpenChange={open => { if (!open) setConfirm(null) }}>
      {confirm?.sync && <Notice tone="attention">{t('{service} syncs this folder. DEIXIS can keep its library here, but syncing may copy the library while it is being written. This warning is no guarantee of safety, and the library must never be open on two computers at once.', { service: confirm.sync })}</Notice>}
    </ConfirmDialog>
  </div>
}
