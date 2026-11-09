import { useEffect, useState } from 'react'
import { MessageSquarePlus } from 'lucide-react'
import { t } from '../lib/i18n'
import type { FollowupAsk, FollowupAttachmentKind } from '../lib/api'

// "Add to chat": text selected in a written answer (the answer, a follow-up answer, a report sentence) gets a small
// button above the selection that puts it in the follow-up composer as a chip. Text in the composer and in form
// fields is left alone.
//
// The chip carries what it was selected from, not only its text: both ends of the selection must sit in the same
// claim, and that claim's own id travels with the quote so the server can bind the question to the passages that
// sentence rests on. A selection that crosses two claims has no single source, so it goes as a free selection.

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

// The claim both ends of the selection sit in, as the kind and id the server reads. A report sentence is on its own
// surface, so the claim element, not the containing panel, is what decides.
const CLAIM_MARKS: [FollowupAttachmentKind, string][] = [
  ['answer_claim', 'data-answer-claim'], ['followup_claim', 'data-followup-claim'], ['report_claim', 'data-report-claim'],
]

function claimOf(range: Range): { kind: FollowupAttachmentKind; ref_id: string | null } {
  const element = (n: Node) => (n instanceof Element ? n : n.parentElement)
  for (const [kind, attribute] of CLAIM_MARKS) {
    const start = element(range.startContainer)?.closest(`[${attribute}]`)
    const end = element(range.endContainer)?.closest(`[${attribute}]`)
    const id = start && start === end ? start.getAttribute(attribute) : null
    if (id) return { kind, ref_id: id }
  }
  return { kind: 'text', ref_id: null }
}

function selectedIn() {
  const selection = window.getSelection()
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) return null
  const range = selection.getRangeAt(0)
  const node = range.commonAncestorContainer
  const element = node instanceof Element ? node : node.parentElement
  if (!element || element.closest('.followup-compose, input, textarea, [contenteditable="true"], .add-to-chat')) return null
  // Only written prose is quotable: both ends of the selection sit in an answer, a follow-up answer or a report
  // sentence. The surface the prose is on does not matter; the prose does.
  const inProse = (n: Node) => (n instanceof Element ? n : n.parentElement)?.closest('.answer-prose, .followup-prose, .evidence-report-paragraph')
  if (!inProse(range.startContainer) || !inProse(range.endContainer)) return null
  const text = selectionText(range).replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim()
  if (!text) return null
  const rect = range.getBoundingClientRect()
  // The whole chip stays within the server's limit, the ellipsis included.
  const cut = text.length > QUOTE_LIMIT ? `${text.slice(0, QUOTE_LIMIT - 1).trimEnd()}…` : text
  return { ...claimOf(range), text: cut, top: rect.top, left: rect.left + rect.width / 2 }
}

export function AddToChat({ root, disabled, onAdd }: { root: HTMLElement | null; disabled: boolean; onAdd: (pick: FollowupAsk) => void }) {
  const [pick, setPick] = useState<{ kind: FollowupAttachmentKind; ref_id: string | null; text: string; top: number; left: number } | null>(null)
  useEffect(() => {
    const show = () => requestAnimationFrame(() => setPick(selectedIn()))
    const hideWhenEmpty = () => { if (window.getSelection()?.isCollapsed) setPick(null) }
    const hide = () => setPick(null)
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') hide(); else if (e.shiftKey || e.key === 'Shift') show() }
    document.addEventListener('mouseup', show)
    document.addEventListener('keyup', onKey)
    document.addEventListener('selectionchange', hideWhenEmpty)
    root?.addEventListener('scroll', hide, { passive: true })
    window.addEventListener('resize', hide)
    return () => {
      document.removeEventListener('mouseup', show)
      document.removeEventListener('keyup', onKey)
      document.removeEventListener('selectionchange', hideWhenEmpty)
      root?.removeEventListener('scroll', hide)
      window.removeEventListener('resize', hide)
    }
  }, [root])
  if (!pick || disabled) return null
  return <button type="button" className="add-to-chat" style={{ top: Math.max(8, pick.top - 40), left: pick.left }}
    // Pressing the button must not clear the selection before the click lands.
    onMouseDown={e => e.preventDefault()}
    onClick={() => { onAdd({ kind: pick.kind, ref_id: pick.ref_id, text: pick.text }); window.getSelection()?.removeAllRanges(); setPick(null) }}>
    <MessageSquarePlus size={15} aria-hidden />{t('Add to chat')}
  </button>
}
