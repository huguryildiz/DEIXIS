import { useCallback, useEffect, useState } from 'react'
import { Ban, CircleCheck, CirclePause, CircleX, ChevronRight, FlaskConical, Landmark, LoaderCircle, Menu, Moon, PanelLeftClose, PanelLeftOpen, Plug, Plus, RotateCcw, Search, Settings2, Sun, Trash2, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api, type ResearchSummary, type RunStatus, type TrashedResearch } from './api'
import { runStatusLabels } from './labels'
import { Home } from './Home'
import { ResearchPage } from './ResearchView'
import { ConnectionsPage } from './Connections'
import { SettingsPage } from './Settings'
import { QuickFind } from './QuickFind'
import { ToastProvider } from './Toast'
import { setUiLanguage, t, uiLanguage, type UiLanguage } from './i18n'
import './App.css'
import './LegacyWorkspace.css'
import './workspace.css'

type Route = { view: 'home' } | { view: 'research'; id: string; tab?: string } | { view: 'connections' } | { view: 'settings' } | { view: 'trash' }
type ThemeChoice = 'system' | 'light' | 'dark'

const IS_MAC = /Mac|iPhone|iPad/.test(navigator.userAgent)
const recentStatusIcons: Record<RunStatus, LucideIcon> = {
  queued: LoaderCircle, running: LoaderCircle, pause_requested: LoaderCircle,
  paused: CirclePause, completed: CircleCheck, failed: CircleX, cancelled: Ban,
}
const activeRunStatuses = new Set<RunStatus>(['queued', 'running', 'pause_requested'])

function parseHash(): Route {
  const hash = window.location.hash.replace(/^#\/?/, '')
  if (hash.startsWith('research/')) {
    const [id, tab] = hash.slice('research/'.length).split('/')
    return { view: 'research', id, tab }
  }
  if (hash === 'connections') return { view: 'connections' }
  if (hash === 'settings') return { view: 'settings' }
  if (hash === 'trash') return { view: 'trash' }
  return { view: 'home' }
}

export function go(route: Route) {
  window.location.hash = route.view === 'research' ? `/research/${route.id}${route.tab ? `/${route.tab}` : ''}` : route.view === 'home' ? '/' : `/${route.view}`
}

function readTheme(): ThemeChoice {
  try { const value = localStorage.getItem('deixis-theme'); return value === 'light' || value === 'dark' ? value : 'system' } catch { return 'system' }
}

export default function App() {
  const [route, setRoute] = useState<Route>(parseHash)
  const [researches, setResearches] = useState<ResearchSummary[]>([])
  const [trashed, setTrashed] = useState<TrashedResearch[]>([])
  const [trashLoading, setTrashLoading] = useState(false)
  const [trashError, setTrashError] = useState('')
  const [listError, setListError] = useState('')
  const [actionMessage, setActionMessage] = useState('')
  const [actionBusy, setActionBusy] = useState<string | null>(null)
  const [sidebar, setSidebar] = useState(false)
  const [theme, setTheme] = useState<ThemeChoice>(readTheme)
  const [systemDark, setSystemDark] = useState(() => window.matchMedia('(prefers-color-scheme: dark)').matches)
  const [findOpen, setFindOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem('deixis-sidebar') === 'collapsed' } catch { return false } })
  const [language, setLanguage] = useState<UiLanguage>(uiLanguage)
  const dark = theme === 'dark' || (theme === 'system' && systemDark)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === 'k') { event.preventDefault(); setFindOpen(open => !open) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    const onHash = () => { setRoute(parseHash()); setSidebar(false); window.scrollTo(0, 0) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (event: MediaQueryListEvent) => setSystemDark(event.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])
  useEffect(() => { document.documentElement.classList.toggle('dark', dark) }, [dark])
  useEffect(() => { document.documentElement.lang = language }, [language])

  const refreshList = useCallback(() => {
    api.researches().then(list => { setResearches(list); setListError('') }).catch((error: Error) => setListError(error.message))
  }, [])
  useEffect(() => { refreshList() }, [refreshList, route])
  useEffect(() => {
    const refreshIfVisible = () => { if (!document.hidden) refreshList() }
    const timer = window.setInterval(refreshIfVisible, 5_000)
    document.addEventListener('visibilitychange', refreshIfVisible)
    return () => { window.clearInterval(timer); document.removeEventListener('visibilitychange', refreshIfVisible) }
  }, [refreshList])
  const refreshTrash = useCallback(() => {
    setTrashLoading(true)
    api.trash().then(list => { setTrashed(list); setTrashError('') })
      .catch((error: Error) => setTrashError(error.message))
      .finally(() => setTrashLoading(false))
  }, [])
  useEffect(() => { if (route.view === 'trash') refreshTrash() }, [route, refreshTrash])

  async function moveToTrash(research: ResearchSummary) {
    setActionBusy(research.id)
    setActionMessage('')
    try {
      await api.moveToTrash(research.id)
      setResearches(items => items.filter(item => item.id !== research.id))
      if (activeId === research.id) go({ view: 'home' })
      else refreshList()
      setActionMessage(t('Moved to Trash.'))
    } catch (error) { setActionMessage(t('Could not move to Trash: {message}', { message: (error as Error).message })) }
    finally { setActionBusy(null) }
  }

  async function restoreResearch(research: TrashedResearch) {
    setActionBusy(research.id)
    setActionMessage('')
    try {
      await api.restore(research.id)
      setTrashed(items => items.filter(item => item.id !== research.id))
      refreshList()
      setActionMessage(t('Research restored.'))
    } catch (error) { setActionMessage(t('Could not restore research: {message}', { message: (error as Error).message })) }
    finally { setActionBusy(null) }
  }

  async function deletePermanently(research: TrashedResearch) {
    if (!window.confirm(t('Permanently delete “{title}” and its unshared evidence and files? This cannot be undone.', { title: research.title }))) return
    setActionBusy(research.id)
    setActionMessage('')
    try {
      const result = await api.deletePermanently(research.id)
      setTrashed(items => items.filter(item => item.id !== research.id))
      setActionMessage(result.files_not_removed.length
        ? t('Research deleted, but {n} file(s) could not be removed from disk.', { n: result.files_not_removed.length })
        : t('Research permanently deleted.'))
    } catch (error) { setActionMessage(t('Could not permanently delete research: {message}', { message: (error as Error).message })) }
    finally { setActionBusy(null) }
  }

  // A university VPN can be switched on or off while DEIXIS is open. The backend asks Scopus again only when the network
  // route changed, so this check is local and cheap and repeats every few seconds.
  const [institutional, setInstitutional] = useState(false)
  useEffect(() => {
    const check = () => { api.institutionalAccess().then(result => setInstitutional(result.status === 'institutional')).catch(() => setInstitutional(false)) }
    check()
    const timer = window.setInterval(check, 5_000)
    window.addEventListener('focus', check)
    return () => { window.clearInterval(timer); window.removeEventListener('focus', check) }
  }, [])

  function toggleTheme() {
    const next = dark ? 'light' : 'dark'
    setTheme(next)
    try { localStorage.setItem('deixis-theme', next) } catch { /* the choice still applies for this tab */ }
  }

  // t() reads the module-level language, so it is set before the state change re-renders the tree.
  function chooseLanguage(next: UiLanguage) {
    setUiLanguage(next)
    setLanguage(next)
  }

  function toggleCollapsed() {
    const next = !collapsed
    setCollapsed(next)
    try { localStorage.setItem('deixis-sidebar', next ? 'collapsed' : 'expanded') } catch { /* the choice still applies for this tab */ }
  }

  const activeId = route.view === 'research' ? route.id : null
  const crumb = t(route.view === 'connections' ? 'Connections' : route.view === 'settings' ? 'Settings' : route.view === 'trash' ? 'Trash' : route.view === 'research' ? 'Research' : 'New research')

  return <ToastProvider><div className={`app ${dark ? 'dark' : ''} ${collapsed ? 'sidebar-collapsed' : ''}`}>
    {sidebar && <button className="mobile-scrim" aria-label={t('Close navigation')} onClick={() => setSidebar(false)} />}
    <aside className={`sidebar ${sidebar ? 'is-open' : ''}`}>
      <div className="sidebar-head">
        <button className="brand" aria-label={t('DEIXIS home')} onClick={() => go({ view: 'home' })}><span className="brand-mark" aria-hidden="true" /><span className="sidebar-label">DEIXIS</span></button>
        <Button variant="ghost" size="icon" className="sidebar-toggle" onClick={toggleCollapsed} aria-label={t(collapsed ? 'Expand sidebar' : 'Collapse sidebar')} title={t(collapsed ? 'Expand sidebar' : 'Collapse sidebar')}>{collapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}</Button>
      </div>
      <Button className="new-button" variant="outline" onClick={() => go({ view: 'home' })} title={t('New research')}><Plus size={16} /><span className="sidebar-label">{t('New research')}</span></Button>
      <nav aria-label={t('Main navigation')}>
        <button className={route.view === 'home' || route.view === 'research' ? 'selected' : ''} onClick={() => go({ view: 'home' })} title={t('Research')}><FlaskConical size={17} /> <span className="sidebar-label">{t('Research')}</span></button>
        <button className={route.view === 'connections' ? 'selected' : ''} onClick={() => go({ view: 'connections' })} title={t('Connections')}><Plug size={17} /> <span className="sidebar-label">{t('Connections')}</span></button>
        <button className={route.view === 'settings' ? 'selected' : ''} onClick={() => go({ view: 'settings' })} title={t('Settings')}><Settings2 size={17} /> <span className="sidebar-label">{t('Settings')}</span></button>
        <button className={route.view === 'trash' ? 'selected' : ''} onClick={() => go({ view: 'trash' })} title={t('Trash')}><Trash2 size={17} /> <span className="sidebar-label">{t('Trash')}</span></button>
      </nav>
      <div className="recents-label">{t('RECENT RESEARCH')}</div>
      <div className="recent-list">
        {listError && <p>{t('Local service unavailable: {error}', { error: listError })}</p>}
        {!listError && !researches.length && <p>{t('Your questions will')}<br />{t('find a home here.')}</p>}
        {researches.slice(0, 12).map(r => {
          const StatusIcon = r.last_run_status ? recentStatusIcons[r.last_run_status] : FlaskConical
          const status = t(r.last_run_status ? runStatusLabels[r.last_run_status] : 'No run yet')
          return <div key={r.id} className="recent-row"><button className={r.id === activeId ? 'is-active' : ''} onClick={() => go({ view: 'research', id: r.id })} title={`${r.question} · ${status}`} aria-label={`${r.title} · ${status}`}><span className="recent-status" data-status={r.last_run_status ?? 'none'}><StatusIcon size={14} className={r.last_run_status && activeRunStatuses.has(r.last_run_status) ? 'recent-status-spinning' : undefined} aria-hidden="true" /></span><span className="recent-title">{r.title}</span></button><button className="recent-trash" disabled={actionBusy === r.id} aria-label={t('Move {title} to Trash', { title: r.title })} title={t('Move to Trash')} onClick={() => moveToTrash(r)}><Trash2 size={14} /></button></div>
        })}
      </div>
      {actionMessage && route.view !== 'trash' && <p className="sidebar-action-message" role="status">{actionMessage}</p>}
      <div className="sidebar-divider" aria-hidden="true" />
      {institutional && <span className="access-chip" title={t('Scopus recognizes this network as institutional (campus network or university VPN). Updates when the network changes.')}><Landmark size={13} aria-hidden="true" /><span className="sidebar-label">{t('Institutional access')}</span></span>}
    </aside>
    <div className="main-shell">
      <header>
        <div className="breadcrumb"><Button variant="ghost" size="icon" className="mobile-menu" aria-label={t('Open navigation')} onClick={() => setSidebar(true)}><Menu /></Button><span>{t('Workspace')}</span><ChevronRight size={13} /><strong>{crumb}</strong></div>
        <div className="header-actions"><Button variant="ghost" size="sm" className="find-button" onClick={() => setFindOpen(true)} aria-label={t('Quick find')} aria-keyshortcuts="Meta+K Control+K"><Search size={16} /><span>{t('Find')}</span><kbd>{IS_MAC ? '⌘K' : 'Ctrl K'}</kbd></Button>
          <div className="language-switch" role="group" aria-label={t('Interface language')}>
            <button type="button" lang="tr" aria-label="Türkçe" aria-pressed={language === 'tr'} onClick={() => chooseLanguage('tr')}>TR</button>
            <span aria-hidden="true">/</span>
            <button type="button" lang="en" aria-label="English" aria-pressed={language === 'en'} onClick={() => chooseLanguage('en')}>EN</button>
          </div>
          <Button variant="ghost" size="icon" onClick={toggleTheme} aria-label={t(dark ? 'Use light theme' : 'Use dark theme')}>{dark ? <Sun size={17} /> : <Moon size={17} />}</Button></div>
      </header>
      <main>
        {route.view === 'home' && <Home researches={researches} onCreated={id => { refreshList(); go({ view: 'research', id }) }} />}
        {route.view === 'research' && <ResearchPage key={`${route.id}/${route.tab ?? ''}`} id={route.id} initialTab={route.tab} dark={dark} onChanged={refreshList} />}
        {route.view === 'connections' && <ConnectionsPage dark={dark} />}
        {route.view === 'settings' && <SettingsPage />}
        {route.view === 'trash' && <section className="trash-page"><h1>{t('Trash')}</h1><p className="trash-hint">{t('Restore a research, or permanently delete it and its unshared evidence. Shared sources remain available to other research.')}</p>{actionMessage && <p role="status" className="trash-message">{actionMessage}</p>}{trashError ? <p role="alert">{t('Could not load Trash: {message}', { message: trashError })} <Button variant="outline" onClick={refreshTrash}>{t('Retry')}</Button></p> : trashLoading ? <p role="status">{t('Loading Trash…')}</p> : !trashed.length ? <p>{t('Trash is empty.')}</p> : trashed.map(r => <div className="trash-row" key={r.id}><span title={r.title}>{r.title}</span><div><Button variant="outline" disabled={actionBusy === r.id} onClick={() => restoreResearch(r)}><RotateCcw size={15} />{t('Restore')}</Button><Button variant="outline" disabled={actionBusy === r.id} onClick={() => deletePermanently(r)}><Trash2 size={15} />{t('Delete permanently')}</Button></div></div>)}</section>}
      </main>
      <QuickFind open={findOpen} onOpenChange={setFindOpen} recent={researches} dark={dark} />
      <footer><span>{t('© 2026 DEIXIS · Designed & built by')} <a href="https://huguryildiz.com" target="_blank" rel="noopener noreferrer">Hüseyin Uğur Yıldız</a><a className="footer-github" href="https://github.com/huguryildiz/DEIXIS" target="_blank" rel="noopener noreferrer" aria-label={t('DEIXIS on GitHub')} title={t('DEIXIS on GitHub')}><svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M8 0c4.42 0 8 3.58 8 8a8.013 8.013 0 0 1-5.45 7.59c-.4.08-.55-.17-.55-.38 0-.27.01-1.13.01-2.2 0-.75-.25-1.23-.54-1.48 1.78-.2 3.65-.88 3.65-3.95 0-.88-.31-1.59-.82-2.15.08-.2.36-1.02-.08-2.12 0 0-.67-.22-2.2.82-.64-.18-1.32-.27-2-.27-.68 0-1.36.09-2 .27-1.53-1.03-2.2-.82-2.2-.82-.44 1.1-.16 1.92-.08 2.12-.51.56-.82 1.28-.82 2.15 0 3.06 1.86 3.75 3.64 3.95-.23.2-.44.55-.51 1.07-.46.21-1.61.55-2.33-.66-.15-.24-.6-.83-1.23-.82-.67.01-.27.38.01.53.34.19.73.9.82 1.13.16.45.68 1.31 2.69.94 0 .67.01 1.3.01 1.49 0 .21-.15.45-.55.38A7.995 7.995 0 0 1 0 8c0-4.42 3.58-8 8-8Z" /></svg></a></span></footer>
    </div>
  </div></ToastProvider>
}
