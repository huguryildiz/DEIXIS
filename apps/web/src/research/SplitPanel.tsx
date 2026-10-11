import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { ChevronLeft, Maximize2, Minimize2, X, type LucideIcon } from 'lucide-react'
import { t } from '../i18n'
import { usePanels, type PanelStack } from './usePanelStack'

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"]),summary'

// The panel frame (mockup `.panel`, P1): a 46px head with Back (when a panel is stacked), the panel's own heading and
// actions, Full width and Close, then a scrolling body. The open panel's content is placed into the two slots by its
// StackPanel. On a desktop it is a labelled region beside the thread, which stays usable; at 820px and below it covers
// the screen as a modal dialog that keeps focus inside.
export function SplitPanel({ stack, phone }: { stack: PanelStack; phone: boolean }) {
  const root = useRef<HTMLElement>(null)
  const head = useRef<HTMLDivElement>(null)
  const body = useRef<HTMLDivElement>(null)
  const { setSlots, current } = stack
  useLayoutEffect(() => {
    if (head.current && body.current) setSlots({ head: head.current, body: body.current })
    return () => setSlots(null)
  }, [setSlots])
  // Each panel opens at its top (mockup `openPanel` resets `.p-body`).
  useLayoutEffect(() => { if (body.current) body.current.scrollTop = 0 }, [current])

  // As a dialog the panel is the only thing that answers: the shell's sidebar and phone bar sit outside the research view.
  useEffect(() => {
    if (!phone) return
    const outside = Array.from(document.querySelectorAll<HTMLElement>('.app > .sidebar, .main-shell > .mobilebar'))
    outside.forEach(el => { el.inert = true })
    return () => outside.forEach(el => { el.inert = false })
  }, [phone])

  // The content is portalled in from elsewhere in the React tree, so its keys reach the panel only through the DOM. The
  // listener sits on the document, after React's own: an Escape a field or a widget already used (preventDefault) stays
  // its own, any other Escape inside the panel closes it. Keys in a menu or dialog opened from the panel are outside it.
  const { close } = stack
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const el = root.current
      if (!el || event.defaultPrevented || event.isComposing || !el.contains(event.target as Node)) return
      if (event.key === 'Escape') { event.preventDefault(); close(); return }
      if (event.key !== 'Tab' || !phone) return
      const items = Array.from(el.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(item => item.getClientRects().length > 0)
      if (!items.length) return
      const first = items[0], last = items[items.length - 1]
      if (event.shiftKey && (document.activeElement === first || !items.includes(document.activeElement as HTMLElement))) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [close, phone])

  const wideLabel = t(stack.wide ? 'Exit full width' : 'Full width')
  return <section ref={root} data-split-panel className={`split-panel${stack.wide ? ' is-wide' : ''}`}
    role={phone ? 'dialog' : 'region'} aria-modal={phone || undefined} aria-labelledby="split-panel-title">
    <div className="split-panel-head">
      {stack.entries.length > 1 && <button type="button" className="split-panel-icon" aria-label={t('Back')} title={t('Back')} onClick={stack.back}><ChevronLeft size={16} aria-hidden /></button>}
      <div ref={head} className="split-panel-head-slot" />
      <button type="button" className="split-panel-icon split-panel-wide" aria-label={wideLabel} title={wideLabel} onClick={() => stack.setWide(!stack.wide)}>{stack.wide ? <Minimize2 size={15} aria-hidden /> : <Maximize2 size={15} aria-hidden />}</button>
      <button type="button" className="split-panel-icon" aria-label={t('Close')} title={t('Close')} onClick={stack.close}><X size={16} aria-hidden /></button>
    </div>
    <div ref={body} className="split-panel-body" />
  </section>
}

// One panel's content. It renders into the frame while it is the open panel. `keepMounted` keeps the content alive
// while another panel or none is open (its count, its requests, a draft being typed): the content always renders into
// the same detached element, which the frame takes in while the panel is open, so React never mounts it anew.
// A panel with `open` belongs to a target its owner holds (a source, a report): opening the target opens the panel,
// and closing the panel clears the target.
export function StackPanel({ name, title, icon: Icon, actions, className, open, onClose, keepMounted = false, children }: {
  name: string; title: ReactNode; icon: LucideIcon; actions?: ReactNode; className?: string
  open?: boolean; onClose?: () => void; keepMounted?: boolean; children: ReactNode
}) {
  const stack = usePanels()
  const current = stack?.current === name
  const inStack = Boolean(stack?.entries.some(entry => entry.name === name))
  // The content's own element, created once; it moves between the frame and nowhere.
  const [box] = useState(() => document.createElement('div'))
  const boxClass = `split-panel-content${className ? ` ${className}` : ''}`
  useLayoutEffect(() => { box.setAttribute('class', boxClass) }, [box, boxClass])

  // The owner's target and the stack follow each other: a target set opens the panel, one cleared removes it, and a
  // panel the stack let go of (Close, Back, Escape, another panel opened fresh) clears the target.
  const openStack = stack?.open, removeFromStack = stack?.remove
  useEffect(() => {
    if (open === undefined || !openStack || !removeFromStack) return
    if (open) openStack(name)
    else removeFromStack(name)
  }, [open, name, openStack, removeFromStack])
  const wasInStack = useRef(false)
  useEffect(() => {
    if (wasInStack.current && !inStack && open) onClose?.()
    wasInStack.current = inStack
  }, [inStack, open, onClose])

  const slots = current ? stack?.slots : null
  const takeFocus = stack?.takeFocus
  useLayoutEffect(() => {
    if (!slots) return
    slots.body.replaceChildren(box)
    if (takeFocus?.()) document.getElementById('split-panel-title')?.focus({ preventScroll: true })
    return () => { box.remove() }
  }, [slots, box, takeFocus])

  if (!stack) return null
  return <>
    {slots && createPortal(<div className="split-panel-head-main"><h2 id="split-panel-title" tabIndex={-1}><Icon size={16} aria-hidden /><span>{title}</span></h2>
      {actions && <div className="split-panel-actions">{actions}</div>}</div>, slots.head)}
    {(slots || keepMounted) && createPortal(children, box)}
  </>
}
