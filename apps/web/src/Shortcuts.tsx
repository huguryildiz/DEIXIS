import { useEffect, useRef } from 'react'

// The shortcut layer (mockup keydown handler, UI parity S3): ⌘K / Ctrl K opens the search palette; the single keys
// S R T F Q P open a research page's panels, N and L go to New research and the Library, `[` shows or hides the sidebar,
// `?` opens the keys dialog, Esc closes the open panel. Single keys are off inside text fields and while a dialog or menu
// is open, and the keys dialog has an off switch for them (WCAG 2.1.4); ⌘K and Esc are not single character keys.
// The mockup's "Send follow-up" key is left out until that exists.

export const IS_MAC = /Mac|iPhone|iPad/.test(navigator.userAgent)

// A research page answers these requests (S R T F Q P and the palette's "On this page" rows); `null` closes its open panel.
export type ResearchPanelName = 'sources' | 'report' | 'table' | 'funnel' | 'queue' | 'pdfs'
export type ResearchPanelRequest = { name: ResearchPanelName | null; opener?: HTMLElement | null }
export const RESEARCH_PANEL_EVENT = 'deixis:research-panel'
export function requestResearchPanel(request: ResearchPanelRequest) {
  window.dispatchEvent(new CustomEvent<ResearchPanelRequest>(RESEARCH_PANEL_EVENT, { detail: request }))
}

const RESEARCH_KEYS: Record<string, ResearchPanelName> = { s: 'sources', r: 'report', t: 'table', f: 'funnel', q: 'queue', p: 'pdfs' }

const STORAGE_KEY = 'deixis-single-keys'
export function readSingleKeys(): boolean {
  try { return localStorage.getItem(STORAGE_KEY) !== 'off' } catch { return true }
}
export function writeSingleKeys(on: boolean) {
  try { localStorage.setItem(STORAGE_KEY, on ? 'on' : 'off') } catch { /* the choice still applies for this tab */ }
}

// The keys dialog's rows, in the mockup's order. `single` marks a key the off switch turns off.
export type KeyRow = { label: string; keys: string[]; single?: boolean }
export const KEY_SECTIONS: { heading: string; rows: KeyRow[] }[] = [
  { heading: 'Anywhere', rows: [
    { label: 'Search and commands', keys: [IS_MAC ? '⌘' : 'Ctrl', 'K'] },
    { label: 'Keyboard shortcuts', keys: ['?'], single: true },
    { label: 'New research', keys: ['N'], single: true },
    { label: 'Library', keys: ['L'], single: true },
    { label: 'Show or hide the sidebar', keys: ['['], single: true },
    { label: 'Close panel or dialog', keys: ['Esc'] },
  ] },
  { heading: 'On a research', rows: [
    { label: 'Sources', keys: ['S'], single: true },
    { label: 'Report', keys: ['R'], single: true },
    { label: 'Evidence table', keys: ['T'], single: true },
    { label: 'Search funnel', keys: ['F'], single: true },
    { label: 'Awaiting your decision', keys: ['Q'], single: true },
    // Mockup "Read more in full": the panel reads selected pages, so it carries the live title (plan §2.3).
    { label: 'Get more full text', keys: ['P'], single: true },
  ] },
  { heading: 'In a text box', rows: [
    { label: 'Start research (home)', keys: [IS_MAC ? '⌘' : 'Ctrl', '↵'] },
  ] },
]

const inTextField = (target: EventTarget | null) =>
  target instanceof HTMLElement && (target.isContentEditable || Boolean(target.closest('input, textarea, select')))
// A dialog, sheet or menu keeps every key while it is open (not while it is closing), and so does the phone drawer. The
// research panel is a dialog only at phone width, and it is not one of these: the keys switch panels there as on a desktop.
const overlayOpen = () => Boolean(document.querySelector(':is([role="dialog"]:not([data-split-panel]), [role="alertdialog"], [role="menu"]):not([data-ending-style]), .sidebar.is-open'))

export type ShortcutActions = {
  palette: () => void
  keys: () => void
  home: () => void
  library: () => void
  sidebar: () => void
  onResearch: boolean
  singleKeys: boolean
}

export function useShortcuts(actions: ShortcutActions) {
  const latest = useRef(actions)
  useEffect(() => { latest.current = actions })
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const act = latest.current
      if (event.isComposing) return
      const modified = event.metaKey || event.ctrlKey
      if (modified && !event.altKey && event.key.toLowerCase() === 'k') { event.preventDefault(); act.palette(); return }
      if (event.defaultPrevented || modified || event.altKey || inTextField(event.target) || overlayOpen()) return
      if (event.key === 'Escape') {
        // Inside the panel its own handler already closed it (SplitPanel); this is the Escape pressed in the thread.
        const target = event.target instanceof Element ? event.target : null
        if (act.onResearch && document.querySelector('[data-split-panel]') && !target?.closest('[data-split-panel]')) {
          event.preventDefault()
          requestResearchPanel({ name: null })
        }
        return
      }
      if (!act.singleKeys || event.repeat) return
      const key = event.key.length === 1 ? event.key.toLowerCase() : ''
      if (key === '?') { event.preventDefault(); act.keys() }
      else if (key === 'n') { event.preventDefault(); act.home() }
      else if (key === 'l') { event.preventDefault(); act.library() }
      else if (key === '[') { event.preventDefault(); act.sidebar() }
      else if (RESEARCH_KEYS[key] && act.onResearch) { event.preventDefault(); requestResearchPanel({ name: RESEARCH_KEYS[key] }) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}
