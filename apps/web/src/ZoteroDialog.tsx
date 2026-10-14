import { useEffect, useState, type CSSProperties, type RefObject } from 'react'
import { Dialog } from '@base-ui/react/dialog'
import { Folder, Library, RotateCw, X } from 'lucide-react'
import { api, type ZoteroCollection, type ZoteroSource } from './api'
import { ConnectionIcon } from './connectionIcons'
import { t } from './i18n'
import { Notice } from './Notice'
import './ZoteroDialog.css'

export type ZoteroDestination = 'home' | 'library'
export type ZoteroChoice = { source: ZoteroSource; key: string; name: string; items: number | null }
type Row = ZoteroCollection & { depth: number; label: string }

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e))

// Parents first, each followed by its sub-collections (the server's name order among siblings). A collection is named
// by its path ("Thesis / Chapter 2"); under its parent only its own name is shown. A parent the list does not hold, or
// a loop, leaves the collection at the top level.
function collectionTree(collections: ZoteroCollection[]): Row[] {
  const byKey = new Map(collections.map(c => [c.key, c]))
  const children = new Map<string | null, ZoteroCollection[]>()
  for (const c of collections) {
    const parent = c.parent && c.parent !== c.key && byKey.has(c.parent) ? c.parent : null
    children.set(parent, [...(children.get(parent) ?? []), c])
  }
  const out: Row[] = []
  const seen = new Set<string>()
  const walk = (parent: string | null, depth: number) => {
    for (const c of children.get(parent) ?? []) {
      if (seen.has(c.key)) continue
      seen.add(c.key)
      const prefix = parent ? `${byKey.get(parent)!.name} / ` : ''
      out.push({ ...c, depth, label: prefix && c.name.startsWith(prefix) ? c.name.slice(prefix.length) : c.name })
      walk(c.key, depth + 1)
    }
  }
  walk(null, 0)
  for (const c of collections) if (!seen.has(c.key)) { seen.add(c.key); out.push({ ...c, depth: 0, label: c.name }) }
  return out
}

const itemsText = (n: number) => t(n === 1 ? '{n} item' : '{n} items', { n })

// The Zotero dialog (mockup "Import from Zotero"): one collection of the user's Zotero library, read-only (D16). Home
// stores the choice and imports it when the research starts; the Library (S25) imports into All works. `items` is
// Zotero's own count of the collection's items; when Zotero did not send it, no number is shown.
export function ZoteroDialog({ open, onOpenChange, destination, busy = false, initial, returnFocus, onImport }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  destination: ZoteroDestination
  busy?: boolean
  initial?: { source: ZoteroSource; key: string } | null
  returnFocus?: RefObject<HTMLElement | null>
  onImport: (choice: ZoteroChoice) => void
}) {
  return <Dialog.Root open={open} onOpenChange={next => { if (!busy || next) onOpenChange(next) }}>
    <Dialog.Portal>
      <Dialog.Backdrop className="zotero-dialog-backdrop" />
      <Dialog.Popup className="zotero-dialog" finalFocus={returnFocus}>
        <ZoteroDialogContent destination={destination} busy={busy} initial={initial} onImport={onImport} />
      </Dialog.Popup>
    </Dialog.Portal>
  </Dialog.Root>
}

// Mounted on each opening (the popup leaves the DOM when closed), so every opening reads the library again and a
// collection made in Zotero meanwhile shows up.
function ZoteroDialogContent({ destination, busy, initial, onImport }: {
  destination: ZoteroDestination; busy: boolean; initial?: { source: ZoteroSource; key: string } | null; onImport: (choice: ZoteroChoice) => void
}) {
  const [source, setSource] = useState<ZoteroSource>(initial?.source ?? 'local')
  const [rows, setRows] = useState<Row[] | null>(null)
  const [key, setKey] = useState(initial?.key ?? '')
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let current = true
    api.zoteroCollections(source)
      .then(result => {
        if (!current) return
        const tree = collectionTree(result.collections)
        setRows(tree)
        setKey(old => tree.some(r => r.key === old) ? old : tree[0]?.key ?? '')
      })
      .catch(e => { if (current) setError(errorText(e)) })
    return () => { current = false }
  }, [source, attempt])
  const choose = (next: ZoteroSource) => { if (next !== source) { setSource(next); setRows(null); setError(''); setKey('') } }
  const retry = () => { setRows(null); setError(''); setAttempt(n => n + 1) }
  const chosen = rows?.find(r => r.key === key)
  const label = chosen && chosen.items !== null
    ? t(chosen.items === 1 ? 'Import {n} item' : 'Import {n} items', { n: chosen.items })
    : t('Import items')
  const note = [
    t(source === 'local' ? 'Reads Zotero on this computer through its local API · read-only.' : 'Reads your zotero.org library · read-only.'),
    // The count is Zotero's `numItems`; the import skips standalone notes and attachments that are not PDFs (zotero.collection_items).
    t('Counts are Zotero’s own; standalone notes and non-PDF attachments are skipped, so fewer items may be added.'),
    t(destination === 'home' ? 'Items are imported when the research starts and join it as included sources.' : 'Items are added to All works in the Library.'),
  ].join(' ')

  return <>
    <div className="zotero-dialog-head">
      <Library size={16} aria-hidden />
      <Dialog.Title className="zotero-dialog-title">{t('Import from Zotero')}</Dialog.Title>
      <Dialog.Close type="button" className="zotero-dialog-close" aria-label={t('Close')}><X size={16} aria-hidden /></Dialog.Close>
    </div>
    <div className="zotero-dialog-body">
      <Dialog.Description className="zotero-dialog-lead">{t('Choose a collection. DEIXIS reads its own items (not its sub-collections) and each item’s first readable PDF; it never changes your Zotero library.')}</Dialog.Description>
      <div className="zotero-source" role="group" aria-label={t('Zotero library')}>
        {(['local', 'web'] as const).map(s => <button type="button" key={s} aria-pressed={source === s} onClick={() => choose(s)}>{s === 'local' ? t('Zotero on this computer') : 'zotero.org'}</button>)}
      </div>
      {!rows && !error && <p className="zotero-dialog-status" role="status">{t('Reading collections…')}</p>}
      {error && <Notice tone="error">{error}</Notice>}
      {rows && !rows.length && <div className="zotero-empty">
        <span className="zotero-empty-icon"><ConnectionIcon id="zotero" /></span>
        <div>
          <strong>{t('This library has no collections.')}</strong>
          <p>{t(source === 'local' ? 'Create a collection in Zotero, then check again.' : 'Create a collection on zotero.org, or sync Zotero on this computer, then check again.')}</p>
        </div>
        <button type="button" className="zotero-dialog-ghost" onClick={retry}><RotateCw size={13} aria-hidden />{t('Check again')}</button>
      </div>}
      {rows && rows.length > 0 && <div className="zotero-cols" role="radiogroup" aria-label={t('Zotero collection')}>
        {rows.map(row => <label key={row.key} className={row.depth ? 'sub' : undefined} style={row.depth > 1 ? { '--zotero-depth': row.depth } as CSSProperties : undefined} title={row.name}>
          <input type="radio" name="zotero-collection" value={row.key} checked={row.key === key} onChange={() => setKey(row.key)} />
          <Folder size={16} aria-hidden />
          <span className="zotero-col-name">{row.label}</span>
          {row.items !== null && <em>{itemsText(row.items)}</em>}
        </label>)}
      </div>}
      <p className="zotero-dialog-note">{note}</p>
    </div>
    <div className="zotero-dialog-foot">
      <Dialog.Close type="button" className="zotero-dialog-ghost" disabled={busy}>{t('Cancel')}</Dialog.Close>
      <button type="button" className="zotero-dialog-primary" disabled={busy || !chosen || chosen.items === 0}
        onClick={() => chosen && onImport({ source, key: chosen.key, name: chosen.name, items: chosen.items })}>{label}</button>
    </div>
  </>
}
