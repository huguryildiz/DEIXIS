import { useEffect, useState } from 'react'
import { Library, RotateCw, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { api, type ZoteroCollection, type ZoteroSource } from './api'
import { ConnectionIcon } from './connectionIcons'
import { t } from './i18n'

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e))

// Chooses one collection of the user's Zotero library (D16). Used on a research page and in the home composer,
// which sits inside a form: every button is type="button" so none submits it.
export function ZoteroPanel({ busy, action, onImport, onClose }: {
  busy: boolean; action?: string; onImport: (source: ZoteroSource, key: string, name: string) => void; onClose: () => void
}) {
  const [source, setSource] = useState<ZoteroSource>('local')
  const [collections, setCollections] = useState<ZoteroCollection[] | null>(null)
  const [key, setKey] = useState('')
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const choose = (next: ZoteroSource) => { if (next !== source) { setSource(next); setCollections(null); setKey(''); setError('') } }
  const retry = () => { setCollections(null); setError(''); setAttempt(n => n + 1) }
  useEffect(() => {
    let current = true
    api.zoteroCollections(source)
      .then(result => { if (current) { setCollections(result.collections); setKey(result.collections[0]?.key ?? '') } })
      .catch(e => { if (current) setError(errorText(e)) })
    return () => { current = false }
  }, [source, attempt])
  return <div className="zotero-panel">
    <div className="zotero-panel-head">
      <strong>{t('Add a Zotero collection')}</strong>
      <div className="source-filters" role="group" aria-label={t('Zotero library')}>
        {(['local', 'web'] as const).map(s => <button type="button" key={s} aria-pressed={source === s} onClick={() => choose(s)}>{s === 'local' ? t('Zotero on this computer') : 'zotero.org'}</button>)}
      </div>
      <Button type="button" variant="ghost" size="icon-sm" aria-label={t('Close Zotero import')} onClick={onClose}><X size={14} /></Button>
    </div>
    <p>{t('Read-only: nothing is written to Zotero. The collection’s own items (not its subcollections) and each item’s first PDF are added as sources you included.')}</p>
    {!collections && !error && <p>{t('Reading collections…')}</p>}
    {error && <div className="legacy-boundary">{error}</div>}
    {collections && !collections.length && <div className="zotero-empty">
      <span className="zotero-empty-icon"><ConnectionIcon id="zotero" /></span>
      <div>
        <strong>{t('This library has no collections.')}</strong>
        <p>{t(source === 'local' ? 'Create a collection in Zotero, then check again.' : 'Create a collection on zotero.org, or sync Zotero on this computer, then check again.')}</p>
      </div>
      <Button type="button" variant="outline" size="sm" onClick={retry}><RotateCw size={13} />{t('Check again')}</Button>
    </div>}
    {collections && collections.length > 0 && <div className="zotero-panel-row">
      <Select value={key} onValueChange={value => { if (value) setKey(String(value)) }}>
        <SelectTrigger aria-label={t('Zotero collection')}><SelectValue>{(value: string) => collections.find(c => c.key === value)?.name ?? t('Choose a collection')}</SelectValue></SelectTrigger>
        <SelectContent className="intake-select-content" alignItemWithTrigger={false}>
          {collections.map(c => <SelectItem key={c.key} value={c.key}>{c.name}</SelectItem>)}
        </SelectContent>
      </Select>
      <Button type="button" disabled={busy || !key} onClick={() => onImport(source, key, collections.find(c => c.key === key)?.name ?? key)}>
        <Library size={14} />{action ?? t(busy ? 'Importing…' : 'Import collection')}
      </Button>
    </div>}
  </div>
}
