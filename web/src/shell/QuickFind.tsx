import { useEffect, useRef, useState, type KeyboardEvent, type RefObject } from 'react'
import { Dialog } from '@base-ui/react/dialog'
import { AlignLeft, BookOpen, Check, FileText, Funnel, Inbox, Keyboard, Languages, LibraryBig, Moon, Plus, Search, SlidersHorizontal, VectorSquare, type LucideIcon } from 'lucide-react'
import { api, type QuickFindResult, type ResearchSummary } from '../lib/api'
import { versionText } from '../lib/labels'
import { t, type UiLanguage } from '../lib/i18n'
import type { ResearchPanelName } from './Shortcuts'

// The search palette (mockup `palette`, O1): commands for the page that is open, the recent research and the places to go,
// each with its key. Typing filters the commands and asks /api/search for research and source titles.
export type PaletteCommand = ResearchPanelName | 'theme' | 'keys'
type Group = 'Language' | 'Page' | 'Research' | 'Sources' | 'Pages'
type Item = { key: string; group: Group; label: string; detail?: string; hint?: string; icon: LucideIcon; hash?: string; lang?: UiLanguage; command?: PaletteCommand }

const GROUP_HEADINGS: Record<Group, string> = { Language: 'Language', Page: 'On this page', Research: 'Research', Sources: 'Sources', Pages: 'Go to' }
// The interface language is a command that appears only when the query asks for it, so the default view stays as drawn
// (plan §2.4). The names stay in their own language.
const LANGUAGE_WORDS = ['language', 'dil', 'türkçe', 'turkce', 'turkish', 'english', 'ingilizce']
const LANGUAGES: { lang: UiLanguage; label: string }[] = [{ lang: 'tr', label: 'Türkçe' }, { lang: 'en', label: 'English' }]

export function QuickFind({ open, onOpenChange, recent, dark, returnFocus, language, onLanguage, research, singleKeys, onCommand }: {
  open: boolean; onOpenChange: (open: boolean) => void; recent: ResearchSummary[]; dark: boolean; returnFocus: RefObject<HTMLElement | null>
  language: UiLanguage; onLanguage: (language: UiLanguage) => void
  // The research page that is open (its panels are this page's commands), or null on another page.
  research: { answer: boolean } | null
  singleKeys: boolean; onCommand: (command: PaletteCommand) => void
}) {
  const [query, setQuery] = useState('')
  const [found, setFound] = useState<{ text: string; result: QuickFindResult } | null>(null)
  const [error, setError] = useState('')
  const [active, setActive] = useState(0)
  const text = query.trim()
  const chose = useRef(false)  // choosing a result on another page moves focus to that page; Escape and a same-page choice return it to the opener
  useEffect(() => { if (open) chose.current = false }, [open])

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
  const key = (letter: string) => (singleKeys ? letter : undefined)  // a key that is switched off is not offered
  const page: Item[] = [
    ...(research ? [
      { key: 'cmd-sources', group: 'Page' as const, label: t('Open sources'), icon: BookOpen, command: 'sources' as const, hint: key('S') },
      ...(research.answer ? [{ key: 'cmd-report', group: 'Page' as const, label: t('Open report'), icon: AlignLeft, command: 'report' as const, hint: key('R') }] : []),
      { key: 'cmd-funnel', group: 'Page' as const, label: t('Open search funnel'), icon: Funnel, command: 'funnel' as const, hint: key('F') },
      { key: 'cmd-queue', group: 'Page' as const, label: t('Awaiting your decision'), icon: Inbox, command: 'queue' as const, hint: key('Q') },
      // Mockup "Read more in full": the panel reads selected pages, so it carries the live title (plan §2.3).
      { key: 'cmd-pdfs', group: 'Page' as const, label: t('Get more full text'), icon: FileText, command: 'pdfs' as const, hint: key('P') },
    ] : []),
    { key: 'cmd-theme', group: 'Page', label: t('Toggle dark mode'), icon: Moon, command: 'theme' },
  ]
  const goTo: Item[] = [
    { key: 'page-new', group: 'Pages', label: t('New research'), icon: Plus, hash: '/', hint: key('N') },
    { key: 'page-library', group: 'Pages', label: t('Library'), icon: LibraryBig, hash: '/library', hint: key('L') },
    { key: 'page-settings', group: 'Pages', label: t('Settings'), icon: SlidersHorizontal, hash: '/settings' },
    { key: 'page-keys', group: 'Pages', label: t('Keyboard shortcuts'), icon: Keyboard, command: 'keys', hint: key('?') },
  ]
  const matches = (item: Item) => !lower || item.label.toLowerCase().includes(lower)
  const askedLanguage = lower.length >= 3 && LANGUAGE_WORDS.some(word => word.startsWith(lower) || lower.includes(word))
  const items: Item[] = [
    ...(askedLanguage ? LANGUAGES.map(l => ({ key: `language-${l.lang}`, group: 'Language' as const, label: l.label, icon: Languages, lang: l.lang })) : []),
    ...page.filter(matches),
    ...(text ? result?.researches ?? [] : recent.slice(0, 5)).map(r => ({
      key: `research-${r.id}`, group: 'Research' as const, label: r.title, detail: text && r.question !== r.title ? r.question : undefined,
      icon: VectorSquare, hash: `/research/${r.id}`, hint: t('Research'),
    })),
    ...(text ? result?.sources ?? [] : []).map(s => ({
      key: `source-${s.research_id}-${s.source_version_id}`, group: 'Sources' as const, label: s.title, icon: FileText,
      detail: [s.research_title, s.year, s.version_label && versionText(s.version_label)].filter(Boolean).join(' · '),
      hash: `/research/${s.research_id}/sources`,
    })),
    ...goTo.filter(matches),
  ]
  const current = Math.min(active, items.length - 1)

  function close(next: boolean) {
    if (!next) { setQuery(''); setActive(0) }
    onOpenChange(next)
  }
  function choose(item: Item | undefined) {
    if (!item) return
    if (item.lang) { onLanguage(item.lang); close(false); return }
    if (item.command) {
      const command = item.command
      // A panel or the keys dialog takes focus itself; the theme leaves it where it was.
      chose.current = command !== 'theme'
      close(false)
      // After the palette has gone, so its focus trap does not hold on to the focus the panel or dialog takes.
      window.setTimeout(() => onCommand(command), 0)
      return
    }
    // A new route hands focus to its page's heading (App); choosing the route that is already open changes nothing there, so the opener gets focus back.
    chose.current = `#${item.hash}` !== window.location.hash
    window.location.hash = item.hash ?? '/'
    close(false)
  }
  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (!items.length) return
    if (event.key === 'ArrowDown') { event.preventDefault(); setActive((current + 1) % items.length) }
    if (event.key === 'ArrowUp') { event.preventDefault(); setActive((current - 1 + items.length) % items.length) }
    if (event.key === 'Enter') { event.preventDefault(); choose(items[current]) }
  }

  const searching = Boolean(text) && !result && !error
  const placeholder = t('Search research, library, or type a command…')
  return <Dialog.Root open={open} onOpenChange={close}>
    <Dialog.Portal>
      <Dialog.Backdrop className="quick-find-backdrop" />
      <Dialog.Popup className={`quick-find ${dark ? 'dark' : ''}`} finalFocus={() => chose.current ? false : returnFocus.current?.isConnected ? returnFocus.current : null}>
        <Dialog.Title className="sr-only">{t('Search')}</Dialog.Title>
        <div className="quick-find-field">
          <Search size={16} aria-hidden="true" />
          <input autoFocus role="combobox" aria-expanded="true" aria-controls="quick-find-list" aria-autocomplete="list"
            aria-activedescendant={items[current] ? `qf-${items[current].key}` : undefined} aria-label={placeholder}
            placeholder={placeholder} value={query} onKeyDown={onKeyDown}
            onChange={e => { setQuery(e.target.value); setActive(0) }} />
        </div>
        <div id="quick-find-list" role="listbox" aria-label={t('Results')} className="quick-find-list">
          {(['Language', 'Page', 'Research', 'Sources', 'Pages'] as const).map(group => {
            const entries = items.map((item, index) => ({ item, index })).filter(e => e.item.group === group)
            if (!entries.length) return null
            return <div role="group" aria-labelledby={`qf-group-${group}`} key={group}>
              <div id={`qf-group-${group}`} className="quick-find-group"><span>{t(group === 'Research' && !text ? 'Recent research' : GROUP_HEADINGS[group])}</span></div>
              {entries.map(({ item, index }) => <div key={item.key} id={`qf-${item.key}`} role="option" aria-selected={index === current}
                aria-keyshortcuts={item.hint && item.hint.length === 1 ? item.hint : undefined}
                className="quick-find-option" onMouseMove={() => setActive(index)} onClick={() => choose(item)}>
                <item.icon size={15} aria-hidden="true" />
                <span><strong lang={item.lang}>{item.label}</strong>{item.detail && <small>{item.detail}</small>}</span>
                {item.lang === language && <Check size={15} className="quick-find-current" aria-hidden="true" />}
                {item.hint && <em aria-hidden="true">{item.hint}</em>}
              </div>)}
            </div>
          })}
          {text && !searching && (error || (!items.length)) &&
            <p className="quick-find-empty">{error || t('No research question or source title matches.')}</p>}
        </div>
        <div className="quick-find-foot" aria-hidden="true"><span>↑↓ {t('navigate')}</span><span>↵ {t('open')}</span><span>esc {t('close')}</span></div>
      </Dialog.Popup>
    </Dialog.Portal>
  </Dialog.Root>
}
