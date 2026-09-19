import { useCallback, useEffect, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react'
import { Ban, CircleCheck, CirclePause, CircleX, ChevronDown, ChevronRight, Ellipsis, FlaskConical, Landmark, Library, LoaderCircle, Menu, Moon, PanelLeftClose, PanelLeftOpen, Search, Settings2, ShieldAlert, Sun, Trash2, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { api, type InstitutionalAccess, type ResearchSummary, type RunStatus } from './api'
import { runStatusLabels } from './labels'
import { Home } from './Home'
import { ResearchPage } from './ResearchView'
import { SettingsPage } from './Settings'
import { LibraryPage } from './LibraryPage'
import { QuickFind } from './QuickFind'
import { BackgroundJobs } from './BackgroundJobs'
import { useToast } from './Toast'
import { TrashPage } from './TrashPage'
import { setUiLanguage, t, uiLanguage, uiLocale, type UiLanguage } from './i18n'
import './App.css'
import './LegacyWorkspace.css'
import './workspace.css'
import './Trash.css'

type Route = { view: 'home' } | { view: 'research'; id: string; tab?: string } | { view: 'settings'; tab?: 'connections' } | { view: 'trash' } | { view: 'library' }
type ThemeChoice = 'system' | 'light' | 'dark'

const IS_MAC = /Mac|iPhone|iPad/.test(navigator.userAgent)
const recentStatusIcons: Record<RunStatus, LucideIcon> = {
  queued: LoaderCircle, running: LoaderCircle, pause_requested: LoaderCircle,
  paused: CirclePause, completed: CircleCheck, failed: CircleX, cancelled: Ban,
}
const activeRunStatuses = new Set<RunStatus>(['queued', 'running', 'pause_requested'])
const SIDEBAR_MIN = 200
const SIDEBAR_MAX = 420
const clampSidebar = (width: number) => Math.round(Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, width)))

function readSidebarWidth(): number | null {
  try { const value = Number(localStorage.getItem('deixis-sidebar-width')); return value ? clampSidebar(value) : null } catch { return null }
}

function parseHash(): Route {
  const hash = window.location.hash.replace(/^#\/?/, '')
  if (hash.startsWith('research/')) {
    const [id, tab] = hash.slice('research/'.length).split('/')
    return { view: 'research', id, tab }
  }
  // The old standalone Connections page now opens the Connections tab inside Settings.
  if (hash === 'connections') return { view: 'settings', tab: 'connections' }
  if (hash === 'settings/connections') return { view: 'settings', tab: 'connections' }
  if (hash === 'settings') return { view: 'settings' }
  if (hash === 'trash') return { view: 'trash' }
  if (hash === 'library') return { view: 'library' }
  return { view: 'home' }
}

export function go(route: Route) {
  window.location.hash = route.view === 'research' ? `/research/${route.id}${route.tab ? `/${route.tab}` : ''}`
    : route.view === 'home' ? '/'
    : route.view === 'settings' ? `/settings${route.tab ? `/${route.tab}` : ''}`
    : `/${route.view}`
}

function readTheme(): ThemeChoice {
  try { const value = localStorage.getItem('deixis-theme'); return value === 'light' || value === 'dark' ? value : 'system' } catch { return 'system' }
}

// Short "how long ago" for the recent list; anything older than a week shows the date.
function sinceLabel(iso: string): string {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000
  if (seconds < 60) return t('Just now')
  const relative = new Intl.RelativeTimeFormat(uiLocale(), { numeric: 'auto', style: 'narrow' })
  if (seconds < 3600) return relative.format(-Math.floor(seconds / 60), 'minute')
  if (seconds < 86_400) return relative.format(-Math.floor(seconds / 3600), 'hour')
  if (seconds < 7 * 86_400) return relative.format(-Math.floor(seconds / 86_400), 'day')
  return new Date(iso).toLocaleDateString(uiLocale(), { month: 'short', day: 'numeric' })
}

export default function App() {
  const [route, setRoute] = useState<Route>(parseHash)
  const [researches, setResearches] = useState<ResearchSummary[]>([])
  const [listError, setListError] = useState('')
  const [actionMessage, setActionMessage] = useState('')
  const [actionBusy, setActionBusy] = useState<string | null>(null)
  const [sidebar, setSidebar] = useState(false)
  const [theme, setTheme] = useState<ThemeChoice>(readTheme)
  const [systemDark, setSystemDark] = useState(() => window.matchMedia('(prefers-color-scheme: dark)').matches)
  const [findOpen, setFindOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem('deixis-sidebar') === 'collapsed' } catch { return false } })
  const [recentsOpen, setRecentsOpen] = useState(() => { try { return localStorage.getItem('deixis-recents') !== 'closed' } catch { return true } })
  const [sidebarWidth, setSidebarWidth] = useState<number | null>(readSidebarWidth)
  const [resizing, setResizing] = useState(false)
  const asideRef = useRef<HTMLElement>(null)
  const [language, setLanguage] = useState<UiLanguage>(uiLanguage)
  const toast = useToast()
  const dark = theme === 'dark' || (theme === 'system' && systemDark)
  // Which researches exist right now; views with their own data (the Library) reload when this changes.
  const researchKey = researches.map(r => r.id).join(',')

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

  async function moveToTrash(research: ResearchSummary) {
    setActionBusy(research.id)
    setActionMessage('')
    try {
      await api.moveToTrash(research.id)
      setResearches(items => items.filter(item => item.id !== research.id))
      if (activeId === research.id) go({ view: 'home' })
      else refreshList()
      // Undo calls the Trash page's restore (D50).
      toast('success', t('Moved to Trash.'), { label: t('Undo'), run: () => { api.restore(research.id).then(() => { refreshList(); toast('success', t('Research restored.')) }, (error: Error) => toast('error', t('Could not restore research: {message}', { message: error.message }))) } })
    } catch (error) { setActionMessage(t('Could not move to Trash: {message}', { message: (error as Error).message })) }
    finally { setActionBusy(null) }
  }

  // A university VPN can be switched on or off while DEIXIS is open. The backend asks Scopus again only when the network
  // route changed, so this check is local and cheap and repeats every few seconds.
  const [institutionalStatus, setInstitutionalStatus] = useState<InstitutionalAccess['status']>('not_checked')
  useEffect(() => {
    const check = () => { api.institutionalAccess().then(result => setInstitutionalStatus(result.status)).catch(() => setInstitutionalStatus('unknown')) }
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

  // The sidebar starts at the left edge, so the pointer's x position is the new width. Saved once the drag ends.
  useEffect(() => {
    if (resizing) return
    try { if (sidebarWidth === null) localStorage.removeItem('deixis-sidebar-width'); else localStorage.setItem('deixis-sidebar-width', String(sidebarWidth)) } catch { /* the width still applies for this tab */ }
  }, [sidebarWidth, resizing])

  function startResize(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return
    event.preventDefault()
    const handle = event.currentTarget
    handle.setPointerCapture(event.pointerId)
    setResizing(true)
    const move = (moveEvent: PointerEvent) => setSidebarWidth(clampSidebar(moveEvent.clientX))
    const end = () => {
      handle.removeEventListener('pointermove', move)
      handle.removeEventListener('pointerup', end)
      handle.removeEventListener('pointercancel', end)
      setResizing(false)
    }
    handle.addEventListener('pointermove', move)
    handle.addEventListener('pointerup', end)
    handle.addEventListener('pointercancel', end)
  }

  function resizeByKey(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    const current = sidebarWidth ?? asideRef.current?.offsetWidth ?? SIDEBAR_MIN
    setSidebarWidth(clampSidebar(current + (event.key === 'ArrowRight' ? 16 : -16)))
  }

  function toggleRecents() {
    const next = !recentsOpen
    setRecentsOpen(next)
    try { localStorage.setItem('deixis-recents', next ? 'open' : 'closed') } catch { /* the choice still applies for this tab */ }
  }

  const activeId = route.view === 'research' ? route.id : null
  const crumb = t(route.view === 'settings' ? 'Settings' : route.view === 'trash' ? 'Trash' : route.view === 'research' ? 'Research' : route.view === 'library' ? 'Library' : 'New research')

  return <div className={`app ${dark ? 'dark' : ''} ${collapsed ? 'sidebar-collapsed' : ''} ${sidebarWidth !== null ? 'sidebar-resized' : ''} ${resizing ? 'sidebar-resizing' : ''}`} style={sidebarWidth !== null ? { '--sidebar-width': `${sidebarWidth}px` } as CSSProperties : undefined}>
    {sidebar && <button className="mobile-scrim" aria-label={t('Close navigation')} onClick={() => setSidebar(false)} />}
    <aside ref={asideRef} className={`sidebar ${sidebar ? 'is-open' : ''}`}>
      <div className="sidebar-head">
        <button className="brand" aria-label={t('DEIXIS home')} onClick={() => go({ view: 'home' })}><span className="brand-mark" aria-hidden="true" /><span className="sidebar-label">DEIXIS</span></button>
        <Button variant="ghost" size="icon" className="sidebar-toggle" onClick={toggleCollapsed} aria-label={t(collapsed ? 'Expand sidebar' : 'Collapse sidebar')} title={t(collapsed ? 'Expand sidebar' : 'Collapse sidebar')}>{collapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}</Button>
      </div>
      <button type="button" className="sidebar-find" onClick={() => setFindOpen(true)} aria-label={t('Quick find')} aria-keyshortcuts="Meta+K Control+K" title={t('Quick find')}><Search size={16} /><span className="sidebar-label sidebar-find-label">{t('Search')}</span><kbd className="sidebar-label">{IS_MAC ? '⌘K' : 'Ctrl K'}</kbd></button>
      <nav aria-label={t('Main navigation')}>
        <button className={route.view === 'home' || route.view === 'research' ? 'selected' : ''} onClick={() => go({ view: 'home' })} title={t('Research')}><FlaskConical size={17} /> <span className="sidebar-label">{t('Research')}</span></button>
        <button className={route.view === 'library' ? 'selected' : ''} onClick={() => go({ view: 'library' })} title={t('Library')}><Library size={17} /> <span className="sidebar-label">{t('Library')}</span></button>
        <button className={route.view === 'settings' ? 'selected' : ''} onClick={() => go({ view: 'settings' })} title={t('Settings')}><Settings2 size={17} /> <span className="sidebar-label">{t('Settings')}</span></button>
        <button className={route.view === 'trash' ? 'selected' : ''} onClick={() => go({ view: 'trash' })} title={t('Trash')}><Trash2 size={17} /> <span className="sidebar-label">{t('Trash')}</span></button>
      </nav>
      <div className="recents-label">
        <button type="button" className="recents-toggle" aria-expanded={recentsOpen} aria-controls="recent-list" onClick={toggleRecents}>{t('Recent research')}<ChevronDown size={15} aria-hidden="true" /></button>
      </div>
      <div id="recent-list" className="recent-list" hidden={!recentsOpen}>
        {listError && <p>{t('Local service unavailable: {error}', { error: listError })}</p>}
        {!listError && !researches.length && <p>{t('Your questions will')}<br />{t('find a home here.')}</p>}
        {researches.slice(0, 12).map(r => {
          const StatusIcon = r.last_run_status ? recentStatusIcons[r.last_run_status] : FlaskConical
          const status = t(r.last_run_status ? runStatusLabels[r.last_run_status] : 'No run yet')
          return <div key={r.id} className={`recent-row ${r.id === activeId ? 'is-active' : ''}`}><button className="recent-open" onClick={() => go({ view: 'research', id: r.id })} title={`${r.question} · ${status}`} aria-label={`${r.title} · ${status}`}><span className="recent-status" data-status={r.last_run_status ?? 'none'}><StatusIcon size={16} className={r.last_run_status && activeRunStatuses.has(r.last_run_status) ? 'recent-status-spinning' : undefined} aria-hidden="true" /></span><span className="recent-title">{r.title}</span><time className="recent-time" dateTime={r.updated_at}>{sinceLabel(r.updated_at)}</time></button>
            <DropdownMenu><DropdownMenuTrigger className="recent-more" disabled={actionBusy === r.id} aria-label={t('Actions for {title}', { title: r.title })} title={t('More actions')}><Ellipsis size={16} /></DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-auto"><DropdownMenuItem variant="destructive" onClick={() => moveToTrash(r)}><Trash2 size={15} />{t('Move to Trash')}</DropdownMenuItem></DropdownMenuContent></DropdownMenu></div>
        })}
      </div>
      {actionMessage && route.view !== 'trash' && <p className="sidebar-action-message" role="status">{actionMessage}</p>}
      <div className="sidebar-divider" aria-hidden="true" />
      <BackgroundJobs researches={researches} collapsed={collapsed} dark={dark} onOpenResearch={id => go({ view: 'research', id })} />
      <div className="access-status">
        <span className={`access-chip ${institutionalStatus === 'institutional' ? '' : institutionalStatus === 'none' ? 'is-unavailable' : 'is-uncertain'}`} title={t(institutionalStatus === 'institutional' ? 'Scopus recognizes this network as institutional (campus network or university VPN). Updates when the network changes.' : institutionalStatus === 'none' ? 'University VPN or campus network is not detected. Turn it on to access institutional Scopus coverage.' : 'Institutional access status is not available yet. DEIXIS will check again when the network changes.')}>
          {institutionalStatus === 'institutional' ? <Landmark size={13} aria-hidden="true" /> : <ShieldAlert size={13} aria-hidden="true" />}
          <span className="sidebar-label">{t(institutionalStatus === 'institutional' ? 'Institutional access' : institutionalStatus === 'none' ? 'VPN required' : institutionalStatus === 'unknown' ? 'Access uncertain' : 'Checking access…')}</span>
        </span>
        {!collapsed && <span className="access-chip-note">{t(institutionalStatus === 'institutional' ? 'Campus network or university VPN detected.' : institutionalStatus === 'none' ? 'Turn on the university VPN for institutional Scopus access.' : institutionalStatus === 'unknown' ? 'Institutional access could not be verified.' : 'Checking the current network access.')}</span>}
      </div>
      {!collapsed && <div className="sidebar-resizer" role="separator" aria-orientation="vertical" tabIndex={0} aria-label={t('Resize sidebar')} title={t('Drag to resize · double-click to reset')} aria-valuemin={SIDEBAR_MIN} aria-valuemax={SIDEBAR_MAX} aria-valuenow={sidebarWidth ?? undefined} onPointerDown={startResize} onKeyDown={resizeByKey} onDoubleClick={() => setSidebarWidth(null)} />}
    </aside>
    <div className="main-shell">
      <header>
        <div className="breadcrumb"><Button variant="ghost" size="icon" className="mobile-menu" aria-label={t('Open navigation')} onClick={() => setSidebar(true)}><Menu /></Button><span>{t('Workspace')}</span><ChevronRight size={13} /><strong>{crumb}</strong></div>
        <div className="header-actions"><div className="language-switch" role="group" aria-label={t('Interface language')}>
            <button type="button" lang="tr" aria-label="Türkçe" aria-pressed={language === 'tr'} onClick={() => chooseLanguage('tr')}>TR</button>
            <span aria-hidden="true">/</span>
            <button type="button" lang="en" aria-label="English" aria-pressed={language === 'en'} onClick={() => chooseLanguage('en')}>EN</button>
          </div>
          <Button variant="ghost" size="icon" onClick={toggleTheme} aria-label={t(dark ? 'Use light theme' : 'Use dark theme')}>{dark ? <Sun size={17} /> : <Moon size={17} />}</Button></div>
      </header>
      <main>
        {route.view === 'home' && <Home onCreated={id => { refreshList(); go({ view: 'research', id }) }} />}
        {route.view === 'research' && <ResearchPage key={`${route.id}/${route.tab ?? ''}`} id={route.id} initialTab={route.tab} dark={dark} onChanged={refreshList} />}
        {route.view === 'library' && <LibraryPage dark={dark} researchKey={researchKey} onChanged={refreshList} onOpenResearch={id => go({ view: 'research', id })} onStartResearch={() => go({ view: 'home' })} />}
        {route.view === 'settings' && <SettingsPage key={route.tab ?? 'defaults'} dark={dark} tab={route.tab ?? 'defaults'} onTab={tab => go({ view: 'settings', tab: tab === 'connections' ? 'connections' : undefined })} />}
        {route.view === 'trash' && <TrashPage dark={dark} onChanged={refreshList} />}
      </main>
      <QuickFind open={findOpen} onOpenChange={setFindOpen} recent={researches} dark={dark} />
      <footer><span>{t('© 2026 DEIXIS · Designed & built by')} <a href="https://huguryildiz.com" target="_blank" rel="noopener noreferrer">Hüseyin Uğur Yıldız</a><a className="footer-github" href="https://github.com/huguryildiz/DEIXIS" target="_blank" rel="noopener noreferrer" aria-label={t('DEIXIS on GitHub')} title={t('DEIXIS on GitHub')}><svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M8 0c4.42 0 8 3.58 8 8a8.013 8.013 0 0 1-5.45 7.59c-.4.08-.55-.17-.55-.38 0-.27.01-1.13.01-2.2 0-.75-.25-1.23-.54-1.48 1.78-.2 3.65-.88 3.65-3.95 0-.88-.31-1.59-.82-2.15.08-.2.36-1.02-.08-2.12 0 0-.67-.22-2.2.82-.64-.18-1.32-.27-2-.27-.68 0-1.36.09-2 .27-1.53-1.03-2.2-.82-2.2-.82-.44 1.1-.16 1.92-.08 2.12-.51.56-.82 1.28-.82 2.15 0 3.06 1.86 3.75 3.64 3.95-.23.2-.44.55-.51 1.07-.46.21-1.61.55-2.33-.66-.15-.24-.6-.83-1.23-.82-.67.01-.27.38.01.53.34.19.73.9.82 1.13.16.45.68 1.31 2.69.94 0 .67.01 1.3.01 1.49 0 .21-.15.45-.55.38A7.995 7.995 0 0 1 0 8c0-4.42 3.58-8 8-8Z" /></svg></a></span></footer>
    </div>
  </div>
}
