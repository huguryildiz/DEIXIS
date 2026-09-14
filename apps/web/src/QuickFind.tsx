import { useEffect, useState, type KeyboardEvent } from 'react'
import { Dialog } from '@base-ui/react/dialog'
import { FileText, FlaskConical, Plus, Search, Settings2 } from 'lucide-react'
import { api, type QuickFindResult, type ResearchSummary } from './api'
import { versionText } from './labels'
import { t } from './i18n'

type Item = { key: string; group: 'Pages' | 'Research' | 'Sources'; label: string; detail?: string; hash: string }

// Built on each render so page names follow the interface language.
const pages = (): Item[] => [
  { key: 'page-new', group: 'Pages', label: t('New research'), hash: '/' },
  { key: 'page-connections', group: 'Pages', label: t('Connections'), detail: t('Model and academic source connections'), hash: '/connections' },
]
const ICONS = { Pages: Settings2, Research: FlaskConical, Sources: FileText }
const GROUP_HEADINGS = { Pages: 'PAGES', Research: 'RESEARCH', Sources: 'SOURCES' }

export function QuickFind({ open, onOpenChange, recent, dark }: {
  open: boolean; onOpenChange: (open: boolean) => void; recent: ResearchSummary[]; dark: boolean
}) {
  const [query, setQuery] = useState('')
  const [found, setFound] = useState<{ text: string; result: QuickFindResult } | null>(null)
  const [error, setError] = useState('')
  const [active, setActive] = useState(0)
  const text = query.trim()

  useEffect(() => {
    if (!text) return
    let cancelled = false
    const timer = setTimeout(() => {
      api.search(text)
        .then(result => { if (!cancelled) { setFound({ text, result }); setError('') } })
        .catch((e: Error) => { if (!cancelled) setError(t('Search is unavailable: {message}', { message: e.message })) })
    }, 120)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [text])

  const result = found && found.text === text ? found.result : null
  const lower = text.toLowerCase()
  const items: Item[] = [
    ...pages().filter(p => !lower || p.label.toLowerCase().includes(lower)),
    ...(text ? result?.researches ?? [] : recent.slice(0, 6)).map(r => ({
      key: `research-${r.id}`, group: 'Research' as const, label: r.title, detail: r.question !== r.title ? r.question : undefined, hash: `/research/${r.id}`,
    })),
    ...(text ? result?.sources ?? [] : []).map(s => ({
      key: `source-${s.research_id}-${s.source_version_id}`, group: 'Sources' as const, label: s.title,
      detail: [s.research_title, s.year, s.version_label && versionText(s.version_label)].filter(Boolean).join(' · '),
      hash: `/research/${s.research_id}/sources`,
    })),
  ]
  const current = Math.min(active, items.length - 1)

  function close(next: boolean) {
    if (!next) { setQuery(''); setActive(0) }
    onOpenChange(next)
  }
  function choose(item: Item | undefined) {
    if (!item) return
    window.location.hash = item.hash
    close(false)
  }
  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (!items.length) return
    if (event.key === 'ArrowDown') { event.preventDefault(); setActive((current + 1) % items.length) }
    if (event.key === 'ArrowUp') { event.preventDefault(); setActive((current - 1 + items.length) % items.length) }
    if (event.key === 'Enter') { event.preventDefault(); choose(items[current]) }
  }

  const searching = Boolean(text) && !result && !error
  return <Dialog.Root open={open} onOpenChange={close}>
    <Dialog.Portal>
      <Dialog.Backdrop className="quick-find-backdrop" />
      <Dialog.Popup className={`quick-find ${dark ? 'dark' : ''}`}>
        <Dialog.Title className="sr-only">{t('Quick find')}</Dialog.Title>
        <div className="quick-find-field">
          <Search size={16} aria-hidden="true" />
          <input autoFocus role="combobox" aria-expanded="true" aria-controls="quick-find-list" aria-autocomplete="list"
            aria-activedescendant={items[current] ? `qf-${items[current].key}` : undefined} aria-label={t('Find research, sources or pages')}
            placeholder={t('Find research, sources or pages')} value={query} onKeyDown={onKeyDown}
            onChange={e => { setQuery(e.target.value); setActive(0) }} />
          <kbd>Esc</kbd>
        </div>
        <div id="quick-find-list" role="listbox" aria-label={t('Results')} className="quick-find-list">
          {(['Pages', 'Research', 'Sources'] as const).map(group => {
            const entries = items.map((item, index) => ({ item, index })).filter(e => e.item.group === group)
            if (!entries.length) return null
            const Icon = ICONS[group]
            return <div role="group" aria-labelledby={`qf-group-${group}`} key={group}>
              <div id={`qf-group-${group}`} className="quick-find-group">{t(group === 'Research' && !text ? 'RECENT RESEARCH' : GROUP_HEADINGS[group])}</div>
              {entries.map(({ item, index }) => <div key={item.key} id={`qf-${item.key}`} role="option" aria-selected={index === current}
                className="quick-find-option" onMouseMove={() => setActive(index)} onClick={() => choose(item)}>
                {item.key === 'page-new' ? <Plus size={15} aria-hidden="true" /> : <Icon size={15} aria-hidden="true" />}
                <span><strong>{item.label}</strong>{item.detail && <small>{item.detail}</small>}</span>
              </div>)}
            </div>
          })}
          {text && !searching && (error || (result && !result.researches.length && !result.sources.length)) &&
            <p className="quick-find-empty">{error || t('No research question or source title matches.')}</p>}
        </div>
        <p className="quick-find-note">{t('Matches research titles, questions and source titles in this workspace. Passage text is not searched.')}</p>
      </Dialog.Popup>
    </Dialog.Portal>
  </Dialog.Root>
}
