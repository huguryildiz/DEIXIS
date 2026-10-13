import { useEffect, useRef, useState } from 'react'
import { ArrowUp, Plus, type LucideIcon } from 'lucide-react'
import { useToast } from '../Toast'
import { t } from '../i18n'

// The sticky follow-up composer at the foot of the thread (mockup `.foot-compose` / `.mini`, R30, UI parity S22b). It asks
// one follow-up question, answered only from the passages this research already holds (D11); it starts no search. "+"
// opens Get more full text, where PDFs are added to the research's works. A follow-up has no depth of its own: it reads at
// most the passage limit of the research's depth, so the depth is shown as the research's, not as a choice (§2.3).
// ⌘/Ctrl + Enter sends. Sending is locked while a request runs; the draft stays when the request fails and is cleared
// only when the server has queued the question.

export type FollowupFill = { text: string; request: number }

export function FollowupComposer({ disabledReason, sending, depthIcon: DepthIcon, depthLabel, fill, onSend, onAddPdfs }: {
  // Why a question cannot be sent now (a run of this research is active), or null.
  disabledReason: string | null
  sending: boolean
  depthIcon: LucideIcon
  depthLabel: string
  // Text another control puts in the box ("Next steps" row): each new request replaces the draft and focuses the box.
  fill: FollowupFill | null
  onSend: (question: string, idempotencyKey: string) => Promise<boolean>
  onAddPdfs: (opener: HTMLElement) => void
}) {
  const toast = useToast()
  const [draft, setDraft] = useState('')
  const field = useRef<HTMLTextAreaElement>(null)
  const box = useRef<HTMLDivElement>(null)
  // One key per question text: a retry of the same text after a failed request is the same request to the server.
  const key = useRef<{ text: string; key: string } | null>(null)

  const [filled, setFilled] = useState(fill)
  if (filled !== fill) {
    setFilled(fill)
    if (fill) setDraft(fill.text)
  }
  useEffect(() => {
    if (!fill) return
    const node = field.current
    if (node) { node.focus(); requestAnimationFrame(() => node.setSelectionRange(node.value.length, node.value.length)) }
  }, [fill])

  // The thread keeps a focused control above the sticky composer when it scrolls it into view (WCAG 2.4.11): its scroll
  // padding at the bottom is the composer's height.
  useEffect(() => {
    const node = box.current
    const column = node?.closest<HTMLElement>('.research-thread-col')
    if (!node || !column) return
    const observer = new ResizeObserver(() => column.style.setProperty('--followup-compose-h', `${node.offsetHeight}px`))
    observer.observe(node)
    return () => { observer.disconnect(); column.style.removeProperty('--followup-compose-h') }
  }, [])

  const send = async () => {
    if (sending) return
    const question = draft.trim()
    if (!question) { toast('warning', t('Type a follow-up question first')); field.current?.focus(); return }
    if (disabledReason) { toast('warning', disabledReason); return }
    if (key.current?.text !== question) key.current = { text: question, key: crypto.randomUUID() }
    if (await onSend(question, key.current.key)) {
      key.current = null
      setDraft(current => (current.trim() === question ? '' : current))
    }
  }

  return <div className="followup-compose" ref={box}>
    <div className="followup-composer">
      <textarea ref={field} aria-label={t('Follow-up question')} placeholder={t('Ask about the passages this research has read')} value={draft} maxLength={2000}
        onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void send() } }} />
      <div className="followup-composer-row">
        <button type="button" className="followup-add" aria-label={t('Add PDFs')} title={t('Add PDFs in Get more full text')} onClick={e => onAddPdfs(e.currentTarget)}><Plus size={16} aria-hidden /></button>
        <span className="followup-spacer" />
        <span className="followup-depth" title={t('A follow-up reads at most the passage limit of this research’s depth.')}><DepthIcon size={15} aria-hidden /><span className="sr-only">{t('Research depth')}: </span>{depthLabel}</span>
        <button type="button" className="followup-send" aria-label={t('Send follow-up question')} title={disabledReason ?? t('Send follow-up question')}
          disabled={sending || Boolean(disabledReason)} aria-busy={sending || undefined} onClick={() => { void send() }}><ArrowUp size={16} aria-hidden /></button>
      </div>
    </div>
  </div>
}
