import { useCallback, useEffect, useState } from 'react'
import { ChevronRight, FlaskConical, Menu, Moon, Plus, Search, Settings2, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api, type ResearchSummary } from './api'
import { Home } from './Home'
import { ResearchPage } from './ResearchView'
import { ConnectionsPage } from './Connections'
import { QuickFind } from './QuickFind'
import './App.css'
import './LegacyWorkspace.css'
import './workspace.css'

type Route = { view: 'home' } | { view: 'research'; id: string; tab?: string } | { view: 'connections' }
type ThemeChoice = 'system' | 'light' | 'dark'

const IS_MAC = /Mac|iPhone|iPad/.test(navigator.userAgent)

function parseHash(): Route {
  const hash = window.location.hash.replace(/^#\/?/, '')
  if (hash.startsWith('research/')) {
    const [id, tab] = hash.slice('research/'.length).split('/')
    return { view: 'research', id, tab }
  }
  if (hash === 'connections') return { view: 'connections' }
  return { view: 'home' }
}

export function go(route: Route) {
  window.location.hash = route.view === 'research' ? `/research/${route.id}${route.tab ? `/${route.tab}` : ''}` : route.view === 'connections' ? '/connections' : '/'
}

function readTheme(): ThemeChoice {
  try { const value = localStorage.getItem('deixis-theme'); return value === 'light' || value === 'dark' ? value : 'system' } catch { return 'system' }
}

export default function App() {
  const [route, setRoute] = useState<Route>(parseHash)
  const [researches, setResearches] = useState<ResearchSummary[]>([])
  const [listError, setListError] = useState('')
  const [sidebar, setSidebar] = useState(false)
  const [theme, setTheme] = useState<ThemeChoice>(readTheme)
  const [systemDark, setSystemDark] = useState(() => window.matchMedia('(prefers-color-scheme: dark)').matches)
  const [findOpen, setFindOpen] = useState(false)
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

  const refreshList = useCallback(() => {
    api.researches().then(list => { setResearches(list); setListError('') }).catch((error: Error) => setListError(error.message))
  }, [])
  useEffect(() => { refreshList() }, [refreshList, route])

  function toggleTheme() {
    const next = dark ? 'light' : 'dark'
    setTheme(next)
    try { localStorage.setItem('deixis-theme', next) } catch { /* the choice still applies for this tab */ }
  }

  const activeId = route.view === 'research' ? route.id : null
  const crumb = route.view === 'connections' ? 'Connections' : route.view === 'research' ? 'Research' : 'New research'

  return <div className={`app ${dark ? 'dark' : ''}`}>
    {sidebar && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setSidebar(false)} />}
    <aside className={`sidebar ${sidebar ? 'is-open' : ''}`}>
      <button className="brand" aria-label="DEIXIS home" onClick={() => go({ view: 'home' })}><span className="brand-mark" aria-hidden="true" /><span>DEIXIS</span></button>
      <Button className="new-button" variant="outline" onClick={() => go({ view: 'home' })}><Plus size={16} />New research</Button>
      <nav aria-label="Main navigation">
        <button className={route.view !== 'connections' ? 'selected' : ''} onClick={() => go({ view: 'home' })}><FlaskConical size={17} /> Research</button>
        <button className={route.view === 'connections' ? 'selected' : ''} onClick={() => go({ view: 'connections' })}><Settings2 size={17} /> Connections</button>
      </nav>
      <div className="recents-label">RECENT RESEARCH</div>
      <div className="recent-list">
        {listError && <p>Local service unavailable: {listError}</p>}
        {!listError && !researches.length && <p>Your questions will<br />find a home here.</p>}
        {researches.slice(0, 12).map(r => <button key={r.id} className={r.id === activeId ? 'is-active' : ''} onClick={() => go({ view: 'research', id: r.id })} title={r.question}>{r.title}</button>)}
      </div>
      <div className="sidebar-bottom"><span className="local-dot" /> Local workspace</div>
    </aside>
    <div className="main-shell">
      <header>
        <div className="breadcrumb"><Button variant="ghost" size="icon" className="mobile-menu" aria-label="Open navigation" onClick={() => setSidebar(true)}><Menu /></Button><span>Workspace</span><ChevronRight size={13} /><strong>{crumb}</strong></div>
        <div className="header-actions"><Button variant="ghost" size="sm" className="find-button" onClick={() => setFindOpen(true)} aria-label="Quick find" aria-keyshortcuts="Meta+K Control+K"><Search size={16} /><span>Find</span><kbd>{IS_MAC ? '⌘K' : 'Ctrl K'}</kbd></Button><Button variant="ghost" size="icon" onClick={toggleTheme} aria-label={dark ? 'Use light theme' : 'Use dark theme'}>{dark ? <Sun size={17} /> : <Moon size={17} />}</Button></div>
      </header>
      <main>
        {route.view === 'home' && <Home researches={researches} onCreated={id => { refreshList(); go({ view: 'research', id }) }} />}
        {route.view === 'research' && <ResearchPage key={`${route.id}/${route.tab ?? ''}`} id={route.id} initialTab={route.tab} dark={dark} onChanged={refreshList} />}
        {route.view === 'connections' && <ConnectionsPage />}
      </main>
      <QuickFind open={findOpen} onOpenChange={setFindOpen} recent={researches} dark={dark} />
      <footer><span>DEIXIS — Every cell points to its source.</span><span>Local web · first slice</span></footer>
    </div>
  </div>
}
