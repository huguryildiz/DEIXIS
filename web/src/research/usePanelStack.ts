import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'

// The research page's side panel (mockup `openPanel`, R10/P1): one panel shows at a time, opening another from an open
// panel stacks it so Back returns, and Close or Escape ends the whole stack and hands focus back to the control that
// opened the first panel.
// `opener` is the control outside the panels that opened the stack; `returnTo` is the control inside the panel below that opened this
// stacked panel (a citation chip, a row), which Back focuses again while it is still there.
type PanelEntry = { name: string; opener: HTMLElement | null; returnTo?: HTMLElement | null }
type PanelSlots = { head: HTMLElement; body: HTMLElement }
export type PanelStack = {
  entries: PanelEntry[]
  current: string | null
  wide: boolean
  slots: PanelSlots | null
  // `fresh` starts a new stack instead of stacking on the open panel (mockup `openPanel(…, false)`).
  open: (name: string, options?: { fresh?: boolean; opener?: HTMLElement | null }) => void
  back: () => void
  close: () => void
  // A panel its owner closed (its target cleared) leaves the stack without being the one asked for.
  remove: (name: string) => void
  // The panel `from` shows other content under the name `to` in the same place of the stack (a report's version
  // select): no entry is added or left behind, and Back still returns to the panel below.
  replace: (from: string, to: string) => void
  setWide: (wide: boolean) => void
  setSlots: (slots: PanelSlots | null) => void
  // Set once after an open or back: the panel that shows next moves focus to its heading, or after Back to the control that opened the panel above it.
  takeFocus: () => boolean | HTMLElement
}

// The URL names a panel with the mockup's names; the research tabs' old segments stay as aliases (plan §2.1).
export const PANEL_ALIASES: Record<string, string | null> = {
  sources: 'sources', queue: 'queue', pdfs: 'pdfs', waiting: 'pdfs', table: 'table', evidence: 'table', funnel: 'funnel',
  watch: 'watch', followup: 'watch', cands: 'cands', candidates: 'cands', activity: 'activity', plan: 'plan', citemap: 'citemap', snowball: 'snowball', artifacts: null, answer: null,
}
export const URL_PANELS = new Set(['sources', 'queue', 'pdfs', 'funnel', 'table', 'watch', 'cands', 'activity', 'plan', 'citemap', 'snowball'])
export const panelFromSegment = (segment: string | undefined) => (segment ? PANEL_ALIASES[segment] ?? null : null)

const outsidePanel = (el: Element | null): HTMLElement | null =>
  el instanceof HTMLElement && el !== document.body && !el.closest('[data-split-panel]') ? el : null

function returnFocus(opener: HTMLElement | null) {
  requestAnimationFrame(() => {
    const active = document.activeElement
    // A control the person moved to meanwhile keeps focus; only a focus lost with the panel goes back.
    if (active && active !== document.body && active.isConnected && !active.closest('[data-split-panel]')) return
    const target = opener?.isConnected && !opener.matches(':disabled') ? opener : document.querySelector<HTMLElement>('main h1')
    target?.focus({ preventScroll: false })
  })
}

export function usePanelStack(initial: string | null): PanelStack {
  const [entries, setEntries] = useState<PanelEntry[]>(() => (initial ? [{ name: initial, opener: null }] : []))
  const [wide, setWide] = useState(false)
  const [slots, setSlots] = useState<PanelSlots | null>(null)
  const pendingFocus = useRef<boolean | HTMLElement>(Boolean(initial))
  const entriesRef = useRef(entries)
  const commit = useCallback((next: PanelEntry[]) => { entriesRef.current = next; setEntries(next) }, [])

  const open = useCallback((name: string, options?: { fresh?: boolean; opener?: HTMLElement | null }) => {
    const opener = options?.opener ?? outsidePanel(document.activeElement)
    const list = entriesRef.current
    // The panel already open only takes focus back to its heading.
    if (list.length && list[list.length - 1].name === name && (!options?.fresh || list.length === 1)) {
      requestAnimationFrame(() => document.getElementById('split-panel-title')?.focus({ preventScroll: true }))
      return
    }
    pendingFocus.current = true
    const inside = document.activeElement instanceof HTMLElement && document.activeElement !== document.body && document.activeElement.closest('[data-split-panel]') ? document.activeElement : null
    commit(!list.length || options?.fresh ? [{ name, opener: opener ?? list[0]?.opener ?? null }] : [...list, { name, opener, returnTo: inside }])
  }, [commit])
  const back = useCallback(() => {
    const list = entriesRef.current
    pendingFocus.current = list.length > 1 && list[list.length - 1].returnTo || true
    if (list.length > 1) commit(list.slice(0, -1))
  }, [commit])
  const close = useCallback(() => {
    const list = entriesRef.current
    if (!list.length) return
    commit([])
    setWide(false)
    returnFocus(list[0].opener)
  }, [commit])
  const remove = useCallback((name: string) => {
    const list = entriesRef.current
    if (!list.some(entry => entry.name === name)) return
    const next = list.filter(entry => entry.name !== name)
    if (!next.length) { setWide(false); returnFocus(list[0].opener) }
    else if (list[list.length - 1].name === name) pendingFocus.current = true
    commit(next)
  }, [commit])
  const replace = useCallback((from: string, to: string) => {
    const list = entriesRef.current
    if (from === to || !list.some(entry => entry.name === from)) return
    commit(list.filter(entry => entry.name !== to).map(entry => (entry.name === from ? { ...entry, name: to } : entry)))
  }, [commit])
  const takeFocus = useCallback(() => {
    const pending = pendingFocus.current
    pendingFocus.current = false
    return pending
  }, [])

  const current = entries.length ? entries[entries.length - 1].name : null
  return useMemo(() => ({ entries, current, wide, slots, open, back, close, remove, replace, setWide, setSlots, takeFocus }),
    [entries, current, wide, slots, open, back, close, remove, replace, takeFocus])
}

export const PanelStackContext = createContext<PanelStack | null>(null)
export function usePanels(): PanelStack | null {
  return useContext(PanelStackContext)
}

// At this width and below the panel covers the screen as a modal dialog (mockup `.panel` at 820px).
const PANEL_PHONE_QUERY = '(max-width: 820px)'
export function usePhone() {
  const [phone, setPhone] = useState(() => window.matchMedia(PANEL_PHONE_QUERY).matches)
  useEffect(() => {
    const media = window.matchMedia(PANEL_PHONE_QUERY)
    const onChange = () => setPhone(media.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])
  return phone
}
