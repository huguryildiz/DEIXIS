import { useCallback, useEffect, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent } from 'react'
import { Check, Circle, Clock, Ellipsis, Inbox, Keyboard, LibraryBig, Menu, Moon, PanelLeft, Pause, PencilLine, Plus, Search, SlidersHorizontal, Sun, Trash2, TriangleAlert } from 'lucide-react'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { api, ApiError, shellApi, type InstitutionalAccess, type Profile, type ProxySettings, type ResearchSummary, type RunStatus } from './api'
import { runStatusLabels } from './labels'
import { Home } from './Home'
import { EmptyResearch, ResearchPage } from './ResearchView'
import { SettingsPage } from './Settings'
import { LibraryPage } from './LibraryPage'
import { QuickFind, type PaletteCommand } from './QuickFind'
import { KeysDialog } from './KeysDialog'
import { IS_MAC, readSingleKeys, requestResearchPanel, useShortcuts, writeSingleKeys } from './Shortcuts'
import { BackgroundJobs } from './BackgroundJobs'
import { useToast } from './Toast'
import { focusWhenLost } from './focus'
import { TrashPage } from './TrashPage'
import { setUiLanguage, t, uiLanguage, type UiLanguage } from './i18n'
import './App.css'
import './Home.css'
import './LegacyWorkspace.css'
import './workspace.css'
// The research page's rules, split from workspace.css (S0b). The cascade depends on this order; keep it.
import './research/thread.css'
import './research/table.css'
import './research/panels.css'
import './research/rail.css'
import './research/sources.css'
import './research/queue.css'
import './research/followup.css'
import './Trash.css'

type Route = { view: 'home' } | { view: 'research'; id: string; tab?: string } | { view: 'settings'; tab?: 'connections' | 'access' } | { view: 'trash' } | { view: 'library' }
type ThemeChoice = 'system' | 'light' | 'dark'

const activeRunStatuses = new Set<RunStatus>(['queued', 'running', 'pause_requested'])
const SIDEBAR_MIN = 200
const SIDEBAR_MAX = 420
// Quick find and the keys dialog may open by a key, so the control that had focus when they opened is remembered and handed back on Escape.
const rememberFocus = (ref: { current: HTMLElement | null }) => { const active = document.activeElement; if (active instanceof HTMLElement && !active.closest('.quick-find, .keys-dialog')) ref.current = active }
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
  if (hash === 'settings/access') return { view: 'settings', tab: 'access' }
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

// Short "how long ago" for the recent list (mockup: 5m 2h 1d 1w 1mo); a research with a live run shows "now".
function shortAgo(iso: string, live: boolean): string {
  if (live) return t('now')
  const minutes = Math.max(0, (Date.now() - new Date(iso).getTime()) / 60_000)
  if (minutes < 60) return t('{n}m', { n: Math.max(1, Math.floor(minutes)) })
  const hours = minutes / 60
  if (hours < 24) return t('{n}h', { n: Math.floor(hours) })
  const days = hours / 24
  if (days < 7) return t('{n}d', { n: Math.floor(days) })
  if (days < 30) return t('{n}w', { n: Math.floor(days / 7) })
  if (days < 365) return t('{n}mo', { n: Math.floor(days / 30) })
  return t('{n}y', { n: Math.floor(days / 365) })
}

// The recent row's status icon (mockup): check when finished, pause, warn for failed and cancelled, a spinner while live.
function RecentStatus({ status }: { status: RunStatus | null }) {
  const live = status !== null && activeRunStatuses.has(status)
  return <span className="recent-status" data-status={status ?? 'none'}>
    {live ? <span className="spin" aria-hidden="true" />
      : status === 'completed' ? <Check size={14} aria-hidden="true" />
      : status === 'paused' ? <Pause size={14} aria-hidden="true" />
      : status === 'failed' || status === 'cancelled' ? <TriangleAlert size={14} aria-hidden="true" />
      : <Circle size={14} aria-hidden="true" />}
  </span>
}

// The shell's phone layout (App.css, mockup v24): the sidebar becomes a drawer at this width.
const PHONE_QUERY = '(max-width: 820px)'

function readCurrent(): string | null {
  try { return localStorage.getItem('deixis-current') } catch { return null }
}

// The DEIXIS mark in the ink of the brand text, so it follows the theme.
const brandLogo = <svg className="brand-logo" viewBox="3 0 64 64" fill="none" aria-hidden="true"><path d="M17 52V12H29C42.255 12 53 20.954 53 32S42.255 52 32 52C28.5 52 27 50 27 46.5V42" stroke="currentColor" strokeWidth="6" /><circle cx="27" cy="34" r="5" fill="currentColor" /></svg>

export default function App() {
  const [route, setRoute] = useState<Route>(parseHash)
  const [researches, setResearches] = useState<ResearchSummary[]>([])
  const [listError, setListError] = useState('')
  const [actionMessage, setActionMessage] = useState('')
  const [actionBusy, setActionBusy] = useState<string | null>(null)
  // Renaming a recent research from the sidebar; the field is opened by a double click or by the row's Rename action.
  const [renameId, setRenameId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const renameInput = useRef<HTMLInputElement>(null)
  const renameDone = useRef(true)
  // A row opens on a single click and is renamed on a double click, so the navigation waits for the second click to miss.
  const openTimer = useRef<number | null>(null)
  const [sidebar, setSidebar] = useState(false)
  const [theme, setTheme] = useState<ThemeChoice>(readTheme)
  const [systemDark, setSystemDark] = useState(() => window.matchMedia('(prefers-color-scheme: dark)').matches)
  const [findOpen, setFindOpen] = useState(false)
  const findOpener = useRef<HTMLElement | null>(null)
  const [keysOpen, setKeysOpen] = useState(false)
  const keysOpener = useRef<HTMLElement | null>(null)
  // Single-key shortcuts are on until the keys dialog's switch turns them off (WCAG 2.1.4); kept across reloads.
  const [singleKeys, setSingleKeys] = useState(readSingleKeys)
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem('deixis-sidebar') === 'collapsed' } catch { return false } })
  const [sidebarWidth, setSidebarWidth] = useState<number | null>(readSidebarWidth)
  const [resizing, setResizing] = useState(false)
  const asideRef = useRef<HTMLElement>(null)
  const [asideWidth, setAsideWidth] = useState(SIDEBAR_MIN)
  const [language, setLanguage] = useState<UiLanguage>(uiLanguage)
  // The research opened last, for "Current research" (kept across reloads).
  const [currentId, setCurrentId] = useState<string | null>(() => { const first = parseHash(); return first.view === 'research' && first.id ? first.id : readCurrent() })
  const [profile, setProfile] = useState<Profile | null>(null)
  const toast = useToast()
  const dark = theme === 'dark' || (theme === 'system' && systemDark)
  // Which researches exist right now; views with their own data (the Library) reload when this changes.
  const researchKey = researches.map(r => r.id).join(',')

  useEffect(() => {
    const onHash = () => { const next = parseHash(); setRoute(next); if (next.view === 'research' && next.id) setCurrentId(next.id); setSidebar(false); window.scrollTo(0, 0) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  // A new route (the composer's Start research, a quick find result, the browser's back button) hands focus to the page's heading when focus has been lost, which is
  // the case when the control that led there has gone. Not on the first load, and not when focus is on a control that is still there (the sidebar button that was used).
  const shownRoute = useRef(route)
  useEffect(() => {
    if (shownRoute.current === route) return
    shownRoute.current = route
    return focusWhenLost(() => document.querySelector<HTMLElement>('main h1'), 5000)
  }, [route])
  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (event: MediaQueryListEvent) => setSystemDark(event.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])
  useEffect(() => { document.documentElement.classList.toggle('dark', dark) }, [dark])
  useEffect(() => { document.documentElement.lang = language }, [language])
  useEffect(() => {
    if (!currentId) return
    try { localStorage.setItem('deixis-current', currentId) } catch { /* still kept for this tab */ }
  }, [currentId])
  useEffect(() => { shellApi.profile().then(setProfile, () => setProfile(null)) }, [])

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

  function beginRename(research: ResearchSummary) {
    setRenameDraft(research.title)
    renameDone.current = false
    setRenameId(research.id)
  }

  function cancelRename() {
    renameDone.current = true
    setRenameId(null)
  }

  async function commitRename(research: ResearchSummary) {
    if (renameDone.current) return
    renameDone.current = true
    const next = renameDraft.trim()
    setRenameId(null)
    if (!next || next === research.title) return
    setActionBusy(research.id)
    setActionMessage('')
    try {
      const renamed = await api.renameResearch(research.id, next, research.version)
      setResearches(items => items.map(item => (item.id === research.id ? { ...item, title: renamed.research.title } : item)))
      refreshList()
      toast('success', t('Research title saved.'))
    } catch (error) {
      // 409 means the research changed since this list was read (a scope revision renames it); the list is reloaded below.
      setActionMessage(t('Could not save the title: {message}', { message: (error as Error).message }))
      if (error instanceof ApiError && error.status === 409) refreshList()
    }
    finally { setActionBusy(null) }
  }

  // The field appears in the same commit as the menu that closed, so focus is taken once Radix has returned it to the trigger.
  useEffect(() => {
    if (!renameId) return
    const timer = window.setTimeout(() => { renameInput.current?.focus(); renameInput.current?.select() }, 0)
    return () => window.clearTimeout(timer)
  }, [renameId])

  useEffect(() => () => { if (openTimer.current !== null) window.clearTimeout(openTimer.current) }, [])

  const clearOpenTimer = () => {
    if (openTimer.current === null) return
    window.clearTimeout(openTimer.current)
    openTimer.current = null
  }

  function openRecent(event: ReactMouseEvent<HTMLButtonElement>, id: string) {
    // The second click of a double click must not navigate again; it opens the title for editing instead.
    if (event.detail > 1) { clearOpenTimer(); return }
    clearOpenTimer()
    openTimer.current = window.setTimeout(() => { openTimer.current = null; go({ view: 'research', id }) }, 220)
  }

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

  // Two facts for the access line, each named by what was measured (plan §2.3): the institution proxy's host answered
  // (article access is never tried), and Scopus grants its full view on this network. The backend asks Scopus again only
  // when the network route changed, so both reads are local and cheap and repeat every few seconds. The proxy is tested
  // again when its test is missing or no longer matches the address or the network route.
  const [institutionalStatus, setInstitutionalStatus] = useState<InstitutionalAccess['status'] | null>(null)
  const [proxy, setProxy] = useState<ProxySettings | null>(null)
  const proxyTesting = useRef(false)
  // A failed read of the settings, or a test request that itself failed, is shown as "could not run" with Check again;
  // a failed test is retried on its own after a minute, not on every poll.
  const proxyFailedAt = useRef<{ address: string; at: number } | null>(null)
  const [proxyFailed, setProxyFailed] = useState<string | null>(null)
  const [proxyReadFailed, setProxyReadFailed] = useState(false)
  const [proxyBusy, setProxyBusy] = useState(false)
  // One test at a time, shared by the automatic check and Settings' Test: a test asked while one runs starts after it,
  // so it measures the address saved by then. The address a failed request was for is remembered for the retry wait.
  const proxyFlight = useRef<Promise<ProxySettings | null> | null>(null)
  const proxyAddress = useRef<string | null>(null)
  // Reads, saves, removals and tests of the proxy share one version: a save or a test moves it on, so a read that was
  // started before it, or while it ran, never replaces what the save or the test produced (success or error). A test's
  // answer counts only when no save or removal happened while it ran; otherwise it is dropped and the setting read again.
  const proxyVersion = useRef(0)
  const proxyWriteVersion = useRef(0)
  const proxyRead = useRef(0)
  const proxyWrites = useRef(0)
  const proxyReread = useRef<() => void>(() => {})
  const runProxyTest = useCallback((address?: string): Promise<ProxySettings | null> => {
    const start = () => {
      if (address) proxyAddress.current = address
      proxyTesting.current = true
      proxyVersion.current++
      const written = proxyWriteVersion.current
      let stale = false
      setProxyBusy(true)
      const flight: Promise<ProxySettings | null> = shellApi.testProxy().then(result => {
        if (written !== proxyWriteVersion.current) { stale = true; return null }
        proxyVersion.current++
        proxyFailedAt.current = null; setProxyFailed(null); setProxy(result); proxyAddress.current = result.address
        return result
      }, (error: Error) => {
        if (written !== proxyWriteVersion.current) { stale = true; return null }
        const address = proxyAddress.current
        if (address) { proxyFailedAt.current = { address, at: Date.now() }; setProxyFailed(address) }
        throw error
      }).finally(() => {
        if (proxyFlight.current === flight) { proxyFlight.current = null; proxyTesting.current = false; setProxyBusy(false) }
        if (stale) proxyReread.current()
      })
      proxyFlight.current = flight
      return flight
    }
    const running = proxyFlight.current
    return running ? running.then(start, start) : start()
  }, [])
  const checkAccess = useCallback(() => {
    api.institutionalAccess().then(result => setInstitutionalStatus(result.status)).catch(() => setInstitutionalStatus('unknown'))
    const n = ++proxyRead.current, version = proxyVersion.current, busy = proxyWrites.current > 0 || proxyTesting.current
    const current = () => n === proxyRead.current && version === proxyVersion.current && !busy
    shellApi.proxySettings().then(settings => {
      if (!current()) return
      setProxy(settings)
      setProxyReadFailed(false)
      if (!proxyTesting.current) proxyAddress.current = settings.address
      const failed = proxyFailedAt.current
      if (!settings.address || (settings.test && settings.test_is_current) || proxyTesting.current) return
      if (failed && failed.address === settings.address && Date.now() - failed.at < 60_000) return
      runProxyTest().catch(() => undefined)
    }, () => { if (current()) setProxyReadFailed(true) })
  }, [runProxyTest])
  useEffect(() => { proxyReread.current = checkAccess }, [checkAccess])
  // Saves (or, with '', removes) the address. The read that follows starts after the save, so it holds the new address.
  const saveProxy = useCallback(async (address: string) => {
    const written = ++proxyWriteVersion.current
    proxyVersion.current++
    proxyWrites.current++
    try {
      const saved = await api.saveInstitutionProxy(address)
      if (written === proxyWriteVersion.current) {
        proxyVersion.current++
        proxyAddress.current = saved.address
        setProxyReadFailed(false)
        setProxy(old => old && { ...old, address: saved.address, test: saved.address ? old.test : null, test_is_current: false })
      }
    } finally { proxyWrites.current-- }
    checkAccess()
  }, [checkAccess])
  const retryAccess = () => { proxyFailedAt.current = null; setProxyFailed(null); setProxyReadFailed(false); checkAccess() }
  useEffect(() => {
    const check = checkAccess
    check()
    const timer = window.setInterval(check, 5_000)
    window.addEventListener('focus', check)
    return () => { window.clearInterval(timer); window.removeEventListener('focus', check) }
  }, [checkAccess])

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

  // The phone drawer closes with its own button or Escape, and hands focus back to the menu button. While it is closed
  // it is inert (out of the tab order and the accessibility tree); opened, focus moves to its close button.
  const menuButton = useRef<HTMLButtonElement>(null)
  const drawerClose = useRef<HTMLButtonElement>(null)
  const [phone, setPhone] = useState(() => window.matchMedia(PHONE_QUERY).matches)
  useEffect(() => {
    const media = window.matchMedia(PHONE_QUERY)
    const onChange = () => setPhone(media.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])
  const closeDrawer = useCallback(() => { setSidebar(false); menuButton.current?.focus() }, [])
  useEffect(() => {
    if (!sidebar) return
    drawerClose.current?.focus()
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape' && !event.defaultPrevented) closeDrawer() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [sidebar, closeDrawer])

  function toggleCollapsed() {
    const next = !collapsed
    setCollapsed(next)
    try { localStorage.setItem('deixis-sidebar', next ? 'collapsed' : 'expanded') } catch { /* the choice still applies for this tab */ }
  }

  // A separator that can be focused needs its current value; with no width set by hand it is the rendered one.
  useEffect(() => {
    const node = asideRef.current
    if (!node) return
    const observer = new ResizeObserver(() => setAsideWidth(Math.round(node.offsetWidth)))
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

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

  const activeId = route.view === 'research' ? route.id : null
  useShortcuts({
    palette: () => { if (findOpen) setFindOpen(false); else openSearch() },
    keys: () => openKeys(),
    home: () => go({ view: 'home' }),
    library: () => go({ view: 'library' }),
    sidebar: () => { if (!phone) toggleCollapsed() },
    onResearch: route.view === 'research' && Boolean(route.id),
    singleKeys,
  })
  // The research opened last in this browser; until one has been opened, Current research shows "No research yet" (R32).
  const currentResearch = currentId && researches.some(r => r.id === currentId) ? currentId : null
  // "Awaiting you": open queue rows and works waiting for the person's PDF over every research, the two kept apart in the tooltip.
  const awaitingQueue = researches.reduce((sum, r) => sum + r.awaiting.queue, 0)
  const awaitingPdf = researches.reduce((sum, r) => sum + r.awaiting.pdf, 0)
  const awaitingTotal = awaitingQueue + awaitingPdf
  const awaitingDetail = t('{queue} awaiting your decision · {pdf} waiting for your PDF', { queue: awaitingQueue, pdf: awaitingPdf })
  const awaitingTarget = researches.find(r => r.id === currentResearch) ?? researches.find(r => r.awaiting.queue + r.awaiting.pdf > 0) ?? null
  const openAwaiting = () => {
    if (!awaitingTarget) return
    const { queue, pdf } = awaitingTarget.awaiting
    go({ view: 'research', id: awaitingTarget.id, tab: queue === 0 && pdf > 0 ? 'waiting' : 'queue' })
  }
  const awaitingOpen = route.view === 'research' && (route.tab === 'queue' || route.tab === 'waiting')
  const openSearch = () => { rememberFocus(findOpener); setKeysOpen(false); setFindOpen(true) }
  const openKeys = (opener?: HTMLElement | null) => { if (opener !== undefined) keysOpener.current = opener; else rememberFocus(keysOpener); setFindOpen(false); setKeysOpen(true) }
  const chooseSingleKeys = (on: boolean) => { setSingleKeys(on); writeSingleKeys(on) }
  const openResearch = researches.find(r => r.id === activeId)
  // A palette command: the research page opens its panel (the palette's opener gets focus back when it closes), the theme
  // changes, or the keys dialog opens in the palette's place.
  const runCommand = (command: PaletteCommand) => {
    if (command === 'theme') toggleTheme()
    else if (command === 'keys') openKeys(findOpener.current)
    else requestResearchPanel({ name: command, opener: findOpener.current })
  }
  const themeName = t(dark ? 'Switch to light mode' : 'Switch to dark mode')

  // The proxy line states only that the host answered; the Scopus line is the separate full-view check (plan §2.3).
  const proxyLabel = proxy?.label ?? proxy?.label_default ?? ''
  const proxyCurrent = !!proxy?.test && proxy.test_is_current
  const accessFailed = proxyReadFailed || (!proxyBusy && !proxyCurrent && !!proxy?.address && proxyFailed === proxy.address)
  const proxyState: { tone: 'ok' | 'warn' | 'unc' | 'checking'; text: string } =
    proxyReadFailed ? { tone: 'unc', text: t('Access check could not run') }
    : !proxy ? { tone: 'checking', text: t('Checking access…') }
    : !proxy.address ? { tone: 'unc', text: t('No institutional access set up') }
    : accessFailed ? { tone: 'unc', text: t('Proxy check could not run') }
    : proxyBusy || !proxy.test || !proxy.test_is_current ? { tone: 'checking', text: t('Checking access…') }
    : proxy.test.proxy_reachable ? { tone: 'ok', text: t('Proxy reachable · article access not checked') }
    : { tone: 'warn', text: t('Proxy did not answer') }
  const scopusState: { tone: 'ok' | 'warn' | 'unc'; text: string } | null =
    institutionalStatus === 'institutional' ? { tone: 'ok', text: t('Scopus full view confirmed') }
    : institutionalStatus === 'none' ? { tone: 'warn', text: t('Scopus full view not confirmed') }
    : institutionalStatus === 'unknown' ? { tone: 'unc', text: t('Scopus check could not run') }
    : null  // not configured, or not read yet
  const accessName = [proxy?.address ? `${t('Institutional access · {label}', { label: proxyLabel })}: ${proxyState.text}` : proxyState.text, scopusState?.text].filter(Boolean).join('. ')

  return <div className={`app ${dark ? 'dark' : ''} ${collapsed ? 'sidebar-collapsed' : ''} ${sidebarWidth !== null ? 'sidebar-resized' : ''} ${resizing ? 'sidebar-resizing' : ''}`} style={sidebarWidth !== null ? { '--sidebar-width': `${sidebarWidth}px` } as CSSProperties : undefined}>
    <aside ref={asideRef} className={`sidebar ${sidebar ? 'is-open' : ''}`} inert={phone && !sidebar}>
      <div className="sidebar-head">
        <button className="brand" aria-label={t('DEIXIS home')} onClick={() => go({ view: 'home' })}><span className="brand-mark" aria-hidden="true">{brandLogo}</span><span className="sidebar-label">DEIXIS</span></button>
        {/* On a phone the drawer's own button closes it (mockup: no scrim). */}
        <button type="button" ref={drawerClose} className="sidebar-toggle" onClick={sidebar ? closeDrawer : toggleCollapsed} aria-label={t(sidebar ? 'Close navigation' : collapsed ? 'Expand sidebar' : 'Collapse sidebar')} title={t(sidebar ? 'Close navigation' : collapsed ? 'Expand sidebar' : 'Collapse sidebar')}><PanelLeft size={16} aria-hidden="true" /></button>
      </div>
      <nav aria-label={t('Main navigation')}>
        <button className={route.view === 'home' ? 'selected' : ''} onClick={() => go({ view: 'home' })} title={t('New research')}><Plus size={16} aria-hidden="true" /><span className="sidebar-label">{t('New research')}</span></button>
        <button className="sidebar-find" onClick={openSearch} aria-label={t('Search')} aria-keyshortcuts="Meta+K Control+K" title={t('Search')}><Search size={16} aria-hidden="true" /><span className="sidebar-label">{t('Search')}</span><kbd className="sidebar-label">{IS_MAC ? '⌘K' : 'Ctrl K'}</kbd></button>
        <button className={route.view === 'research' && !awaitingOpen ? 'selected' : ''} onClick={() => go({ view: 'research', id: currentResearch ?? '' })} title={t(currentResearch ? 'Current research' : 'No research opened yet')}><Clock size={16} aria-hidden="true" /><span className="sidebar-label">{t('Current research')}</span></button>
        <button className={awaitingOpen ? 'selected' : ''} disabled={!awaitingTarget} onClick={openAwaiting} aria-label={awaitingTotal ? `${t('Awaiting you')}: ${awaitingDetail}` : t('Awaiting you')} title={awaitingTotal ? `${t('Awaiting you')} · ${awaitingDetail}` : t('Awaiting you')}><Inbox size={16} aria-hidden="true" /><span className="sidebar-label">{t('Awaiting you')}</span>{awaitingTotal > 0 && <span className="nav-count" aria-hidden="true">{awaitingTotal}</span>}</button>
        <button className={route.view === 'library' ? 'selected' : ''} onClick={() => go({ view: 'library' })} title={t('Library')}><LibraryBig size={16} aria-hidden="true" /><span className="sidebar-label">{t('Library')}</span></button>
        <button className={route.view === 'settings' ? 'selected' : ''} onClick={() => go({ view: 'settings' })} title={t('Settings')}><SlidersHorizontal size={16} aria-hidden="true" /><span className="sidebar-label">{t('Settings')}</span></button>
        <button className={route.view === 'trash' ? 'selected' : ''} onClick={() => go({ view: 'trash' })} title={t('Trash')}><Trash2 size={16} aria-hidden="true" /><span className="sidebar-label">{t('Trash')}</span></button>
      </nav>
      <div className="recents-label" id="recent-label"><span>{t('Recent research')}</span></div>
      <div id="recent-list" className="recent-list" role="group" aria-labelledby="recent-label">
        {listError && <p>{t('Local service unavailable: {error}', { error: listError })}</p>}
        {!listError && !researches.length && <p>{t('Your questions will find a home here.')}</p>}
        {researches.slice(0, 12).map(r => {
          const status = t(r.last_run_status ? runStatusLabels[r.last_run_status] : 'No run yet')
          const live = r.last_run_status !== null && activeRunStatuses.has(r.last_run_status)
          const followupText = r.followup_new > 0 ? `, ${t(r.followup_new === 1 ? '{n} new follow-up record' : '{n} new follow-up records', { n: r.followup_new })}` : ''
          return <div key={r.id} className={`recent-row ${r.id === activeId ? 'is-active' : ''}`}>
            {renameId === r.id
              ? <div className="recent-open is-renaming"><RecentStatus status={r.last_run_status} /><input
                ref={renameInput}
                className="recent-title-input"
                aria-label={t('Research title')}
                value={renameDraft}
                maxLength={160}
                spellCheck={false}
                onChange={event => setRenameDraft(event.target.value)}
                onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); void commitRename(r) } else if (event.key === 'Escape') { event.preventDefault(); cancelRename() } }}
                onBlur={() => void commitRename(r)}
              /></div>
              : <button className="recent-open" onClick={event => openRecent(event, r.id)} onDoubleClick={() => beginRename(r)} title={`${r.question} · ${status}${followupText}`} aria-label={`${r.title} · ${status}${followupText}`}><RecentStatus status={r.last_run_status} /><span className="recent-title">{r.title}</span><span className="followup-sidebar-count" hidden={!r.followup_new} aria-label={followupText.slice(2)}>{r.followup_new}</span><time className="recent-time" dateTime={r.updated_at}>{shortAgo(r.updated_at, live)}</time></button>}
            <DropdownMenu><DropdownMenuTrigger className="recent-more" disabled={actionBusy === r.id} aria-label={t('Actions for {title}', { title: r.title })} title={t('More actions')}><Ellipsis size={16} /></DropdownMenuTrigger>
              <DropdownMenuContent align="start" sideOffset={6}><DropdownMenuItem onClick={() => beginRename(r)}><PencilLine size={15} />{t('Rename')}</DropdownMenuItem><DropdownMenuItem variant="destructive" onClick={() => moveToTrash(r)}><Trash2 size={15} />{t('Move to Trash')}</DropdownMenuItem></DropdownMenuContent></DropdownMenu></div>
        })}
      </div>
      {actionMessage && route.view !== 'trash' && <p className="sidebar-action-message" role="status">{actionMessage}</p>}
      <div className="sidebar-foot">
        <BackgroundJobs researches={researches} dark={dark} onOpenResearch={id => go({ view: 'research', id })} />
        {/* The foot keeps one DOM shape while its reads arrive (profile, proxy, Scopus): only text, inline style and data attributes change. */}
        <button type="button" className="access" onClick={() => go({ view: 'settings', tab: 'access' })} aria-label={accessName} title={t('Institutional access settings')}>
          <span className="access-label" style={proxy?.address ? undefined : { display: 'none' }}>{proxy?.address ? t('Institutional access · {label}', { label: proxyLabel }) : ''}</span>
          <span className="access-line"><i className="access-dot" data-tone={proxyState.tone} aria-hidden="true" /><span>{proxyState.text}</span></span>
          <span className="access-line" style={scopusState ? undefined : { display: 'none' }}><i className="access-dot" data-tone={scopusState?.tone ?? 'unc'} aria-hidden="true" /><span>{scopusState?.text ?? ''}</span></span>
        </button>
        <button type="button" className="access-retry" onClick={retryAccess} style={accessFailed ? undefined : { display: 'none' }}>{t('Check again')}</button>
        <div className="user">
          <span className="avatar" aria-hidden="true" style={profile ? undefined : { visibility: 'hidden' }}>{profile?.initials ?? ''}</span>
          <span className="user-name" title={profile?.full_name}>{profile?.full_name ?? ''}</span>
          <button type="button" className="keys-toggle" onClick={() => openKeys()} aria-label={t('Shortcuts')} aria-keyshortcuts={singleKeys ? '?' : undefined} title={`${t('Shortcuts')} (?)`}><Keyboard size={16} aria-hidden="true" /></button>
          <button type="button" className="theme-toggle" onClick={toggleTheme} aria-label={themeName} title={t(dark ? 'Light mode' : 'Dark mode')}>{dark ? <Sun size={16} aria-hidden="true" /> : <Moon size={16} aria-hidden="true" />}</button>
        </div>
      </div>
      {!collapsed && <div className="sidebar-resizer" role="separator" aria-orientation="vertical" tabIndex={0} aria-label={t('Resize sidebar')} title={t('Drag to resize · double-click to reset')} aria-valuemin={SIDEBAR_MIN} aria-valuemax={SIDEBAR_MAX} aria-valuenow={sidebarWidth ?? asideWidth} onPointerDown={startResize} onKeyDown={resizeByKey} onDoubleClick={() => setSidebarWidth(null)} />}
    </aside>
    <div className="main-shell">
      <div className="mobilebar">
        <button type="button" ref={menuButton} className="mobile-menu" aria-label={t('Open navigation')} onClick={() => setSidebar(true)}><Menu size={16} aria-hidden="true" /></button>
        <b className="mobilebar-brand" aria-hidden="true">DEIXIS</b>
      </div>
      <main>
        {route.view === 'home' && <Home researches={researches} onCreated={id => { refreshList(); go({ view: 'research', id }) }} />}
        {route.view === 'research' && (route.id ? <ResearchPage key={`${route.id}/${route.tab ?? ''}`} id={route.id} initialTab={route.tab} dark={dark} onChanged={refreshList} />
          : <EmptyResearch opened={researches.length > 0} />)}
        {route.view === 'library' && <LibraryPage dark={dark} researchKey={researchKey} onChanged={refreshList} onOpenResearch={id => go({ view: 'research', id })} onStartResearch={() => go({ view: 'home' })} />}
        {route.view === 'settings' && <SettingsPage key={route.tab ?? 'page'} dark={dark} section={route.tab} language={language} onLanguage={chooseLanguage}
          access={{ proxy, readFailed: proxyReadFailed, testing: proxyBusy, testFailed: !!proxy?.address && proxyFailed === proxy.address, scopus: institutionalStatus,
            test: runProxyTest, save: saveProxy, reload: checkAccess }} />}
        {route.view === 'trash' && <TrashPage dark={dark} onChanged={refreshList} />}
      </main>
      <QuickFind open={findOpen} onOpenChange={setFindOpen} recent={researches} dark={dark} returnFocus={findOpener} language={language} onLanguage={chooseLanguage}
        research={route.view === 'research' && route.id ? { answer: (openResearch?.answer_count ?? 0) > 0 } : null} singleKeys={singleKeys} onCommand={runCommand} />
      <KeysDialog open={keysOpen} onOpenChange={setKeysOpen} returnFocus={keysOpener} singleKeys={singleKeys} onSingleKeys={chooseSingleKeys} />
    </div>
  </div>
}
