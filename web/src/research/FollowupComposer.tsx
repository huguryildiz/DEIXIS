import { useEffect, useRef, useState } from 'react'
import { ArrowUp, Plus, Search, X, type LucideIcon } from 'lucide-react'
import { useToast } from '../components/Toast'
import { t } from '../lib/i18n'
import type { FollowupAsk } from '../lib/api'

// The sticky follow-up composer at the foot of the thread (mockup `.foot-compose` / `.mini`, R30, UI parity S22b). It asks
// one follow-up question, answered from the passages this research already holds. "Also search for new works" asks
// for works it does not hold: the question is answered from what is here first, the search runs next, and what it
// finds is answered again in a turn of its own. Left off, the question starts no search. "+"
// opens Get more full text, where PDFs are added to the research's works. A follow-up has no depth of its own: it reads at
// most the passage limit of the research's depth, so the depth is shown as the research's, not as a choice (§2.3).
// ⌘/Ctrl + Enter sends. Sending is locked while a request runs; the draft stays when the request fails and is cleared
// only when the server has queued the question.

export type FollowupFill = { text: string; request: number }
// A selection "Add to chat" sent, with the request counter that makes each click its own.
export type FollowupPick = FollowupAsk & { request: number }

// The server's limit on a follow-up question (`followup.MAX_QUESTION_CHARS`). A selection no longer counts against
// it: it travels beside the question as its own record (`followup_attachments`), with the source it came from.
const MAX_CHARS = 2000
// The server's limits on the selections one question carries (`followup_attachments`).
const MAX_ATTACHMENTS = 4

export function FollowupComposer({ disabledReason, sending, depthIcon: DepthIcon, depthLabel, fill, quote, onSend,
                                   onAddPdfs, searchDisabledReason = null }: {
  // Why a question cannot be sent now (a run of this research is active), or null.
  disabledReason: string | null
  sending: boolean
  depthIcon: LucideIcon
  depthLabel: string
  // Text another control puts in the box ("Next steps" row): each new request replaces the draft and focuses the box.
  fill: FollowupFill | null
  // Text chosen with "Add to chat": each new request adds it as a chip above the box and focuses the box. The chip
  // keeps what it was selected from, so the question reaches the server bound to that source.
  quote: FollowupPick | null
  onSend: (question: string, idempotencyKey: string, attachments: FollowupAsk[], search: boolean) => Promise<boolean>
  onAddPdfs: (opener: HTMLElement) => void
  // Why a search cannot be asked for with this question (no search provider is set up, say), or null.
  searchDisabledReason?: string | null
}) {
  const toast = useToast()
  const [draft, setDraft] = useState('')
  // Off by default: a question is answered from what this research holds unless the person asks for more.
  const [search, setSearch] = useState(false)
  const field = useRef<HTMLTextAreaElement>(null)
  const box = useRef<HTMLDivElement>(null)
  // One key per question text: a retry of the same text after a failed request is the same request to the server.
  const key = useRef<{ text: string; key: string } | null>(null)

  const [filled, setFilled] = useState(fill)
  if (filled !== fill) {
    setFilled(fill)
    if (fill) setDraft(fill.text)
  }
  const [quotes, setQuotes] = useState<FollowupAsk[]>([])
  const [quoted, setQuoted] = useState(quote)
  if (quoted !== quote) {
    setQuoted(quote)
    const same = (a: FollowupAsk, b: FollowupAsk) => a.kind === b.kind && a.ref_id === b.ref_id && a.text === b.text
    if (quote && !quotes.some(item => same(item, quote))) {
      if (quotes.length >= MAX_ATTACHMENTS) toast('warning', t('A question carries at most {n} selections; remove one first.', { n: MAX_ATTACHMENTS }))
      else setQuotes([...quotes, { kind: quote.kind, ref_id: quote.ref_id, text: quote.text }])
    }
  }
  useEffect(() => { if (quote) field.current?.focus() }, [quote])
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
    const sent = quotes
    if (question.length > MAX_CHARS) { toast('warning', t('The question is too long; shorten it.')); return }
    // One key per question and its selections: a retry of the same request after a failure is the same request.
    const asked = search && !searchDisabledReason
    const signature = JSON.stringify([question, sent, asked])
    if (key.current?.text !== signature) key.current = { text: signature, key: crypto.randomUUID() }
    if (await onSend(question, key.current.key, sent, asked)) {
      key.current = null
      setDraft(current => (current.trim() === question ? '' : current))
      setQuotes(current => current.filter(q => !sent.includes(q)))
      setSearch(false)
    }
  }

  return <div className="followup-compose" ref={box}>
    <div className="followup-composer">
      {quotes.length > 0 && <ul className="followup-quotes" aria-label={t('Quoted text')}>{quotes.map(q => <li className="followup-quote-chip" key={`${q.kind}:${q.ref_id ?? ''}:${q.text}`}>
        <span title={q.text}>{q.text}</span>
        {/* A selection code could not bind to a source is still sent, as the person's own words. */}
        <span className="followup-quote-kind">{t(q.kind === 'text' ? 'free selection' : 'from a source')}</span>
        <button type="button" aria-label={t('Remove quote')} onClick={() => { setQuotes(list => list.filter(item => item !== q)); field.current?.focus() }}><X size={14} aria-hidden /></button>
      </li>)}</ul>}
      <textarea ref={field} aria-label={t('Follow-up question')} placeholder={t('Ask about the passages this research has read')} value={draft} maxLength={2000}
        onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void send() } }} />
      <div className="followup-composer-row">
        <button type="button" className="followup-add" aria-label={t('Add PDFs')} title={t('Add PDFs in Get more full text')} onClick={e => onAddPdfs(e.currentTarget)}><Plus size={16} aria-hidden /></button>
        {/* The person's own ask for works this research does not hold; the answer from what it holds comes first. */}
        <label className={`followup-search-ask${search ? ' is-on' : ''}`} title={searchDisabledReason ?? t('The question is answered from this research first; then a search for new works runs and answers it again.')}>
          <input type="checkbox" checked={search && !searchDisabledReason} disabled={Boolean(searchDisabledReason)}
            onChange={e => setSearch(e.target.checked)} />
          <Search size={14} aria-hidden />{t('Also search for new works')}
        </label>
        <span className="followup-spacer" />
        <span className="followup-depth" title={t('A follow-up reads at most the passage limit of this research’s depth.')}><DepthIcon size={15} aria-hidden /><span className="sr-only">{t('Research depth')}: </span>{depthLabel}</span>
        <button type="button" className="followup-send" aria-label={t('Send follow-up question')} title={disabledReason ?? t('Send follow-up question')}
          disabled={sending || Boolean(disabledReason)} aria-busy={sending || undefined} onClick={() => { void send() }}><ArrowUp size={16} aria-hidden /></button>
      </div>
    </div>
  </div>
}
