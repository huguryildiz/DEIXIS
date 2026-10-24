import { useEffect, useState } from 'react'
import { MessageSquarePlus } from 'lucide-react'
import { t } from '../i18n'

// "Add to chat": text selected in the thread (the answer, a follow-up answer) gets a small button above the selection that
// puts it in the follow-up composer as a quote chip. Text in the composer and in form fields is left alone.

const QUOTE_LIMIT = 800

// The selected text with each KaTeX formula written back as its TeX source between $…$ ($$…$$ when displayed). The
// selection's own text spells a formula out one character per line (KaTeX's MathML copy) and loses its structure.
function selectionText(range: Range) {
  const whole = range.cloneRange()
  const formula = (node: Node) => (node instanceof Element ? node : node.parentElement)?.closest('.katex')
  const first = formula(range.startContainer), last = formula(range.endContainer)
  if (first) whole.setStartBefore(first.closest('.katex-display') ?? first)  // a formula is quoted whole or not at all
  if (last) whole.setEndAfter(last.closest('.katex-display') ?? last)
  const holder = document.createElement('div')
  holder.style.cssText = 'position:fixed;left:-99999px;top:0;white-space:pre-line'
  holder.append(whole.cloneContents())
  holder.querySelectorAll('.katex').forEach(el => {
    const tex = el.querySelector('annotation[encoding="application/x-tex"]')?.textContent?.trim()
    const display = el.parentElement?.classList.contains('katex-display')
    const target = display ? el.parentElement! : el
    target.replaceWith(tex ? (display ? `\n$$${tex}$$\n` : `$${tex}$`) : (el.querySelector('.katex-html')?.textContent ?? ''))
  })
  document.body.append(holder)
  const text = holder.innerText  // keeps the paragraph breaks a plain textContent drops
  holder.remove()
  return text
}

function selectedIn(root: HTMLElement) {
  const selection = window.getSelection()
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) return null
  const range = selection.getRangeAt(0)
  const node = range.commonAncestorContainer
  const element = node instanceof Element ? node : node.parentElement
  if (!element || !root.contains(element) || element.closest('.followup-compose, input, textarea, [contenteditable="true"], .add-to-chat')) return null
  // The artifacts rail sits inside the thread column's grid but is not chat text: a selection touching it gets no button.
  const inRail = (n: Node) => (n instanceof Element ? n : n.parentElement)?.closest('.research-rail')
  if (inRail(range.startContainer) || inRail(range.endContainer)) return null
  const text = selectionText(range).replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim()
  if (!text) return null
  const rect = range.getBoundingClientRect()
  return { text: text.length > QUOTE_LIMIT ? `${text.slice(0, QUOTE_LIMIT).trimEnd()}…` : text, top: rect.top, left: rect.left + rect.width / 2 }
}

export function AddToChat({ root, disabled, onAdd }: { root: HTMLElement | null; disabled: boolean; onAdd: (text: string) => void }) {
  const [pick, setPick] = useState<{ text: string; top: number; left: number } | null>(null)
  useEffect(() => {
    if (!root) return
    const show = () => requestAnimationFrame(() => setPick(selectedIn(root)))
    const hideWhenEmpty = () => { if (window.getSelection()?.isCollapsed) setPick(null) }
    const hide = () => setPick(null)
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') hide(); else if (e.shiftKey || e.key === 'Shift') show() }
    document.addEventListener('mouseup', show)
    document.addEventListener('keyup', onKey)
    document.addEventListener('selectionchange', hideWhenEmpty)
    root.addEventListener('scroll', hide, { passive: true })
    window.addEventListener('resize', hide)
    return () => {
      document.removeEventListener('mouseup', show)
      document.removeEventListener('keyup', onKey)
      document.removeEventListener('selectionchange', hideWhenEmpty)
      root.removeEventListener('scroll', hide)
      window.removeEventListener('resize', hide)
    }
  }, [root])
  if (!pick || disabled) return null
  return <button type="button" className="add-to-chat" style={{ top: Math.max(8, pick.top - 40), left: pick.left }}
    // Pressing the button must not clear the selection before the click lands.
    onMouseDown={e => e.preventDefault()}
    onClick={() => { onAdd(pick.text); window.getSelection()?.removeAllRanges(); setPick(null) }}>
    <MessageSquarePlus size={15} aria-hidden />{t('Add to chat')}
  </button>
}
