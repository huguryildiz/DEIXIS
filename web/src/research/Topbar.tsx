import { useEffect, useRef, useState } from 'react'
import { Lightbulb, Pause, PencilLine, Play, TriangleAlert, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { type Run } from '../lib/api'
import { runKindLabels, runStatusLabels, searchQueryTriesLeft } from '../lib/labels'
import { t } from '../lib/i18n'
import { Elapsed } from '../table/EvidenceTable'

const ACTIVE = new Set(['queued', 'running', 'pause_requested'])

// The research title (mockup `.ttl`, R1): the page's h1 holds one button, the title and a pencil that shows on hover and
// focus; pressing it opens the rename row. A newly arrived title is revealed with the typewriter transition (about 28 ms
// a character, 0.6–2.6 s); with reduced motion it shows at once. The h1 stays focusable from code (`main h1` is where
// focus goes when it is lost), not a tab stop of its own.
export function TitleButton({ text, onStartEdit }: { text: string; onStartEdit: () => void }) {
  const [shown, setShown] = useState(text)
  const previous = useRef(text)

  useEffect(() => {
    if (previous.current === text) return
    previous.current = text
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      const frame = requestAnimationFrame(() => setShown(text))
      return () => cancelAnimationFrame(frame)
    }
    const started = performance.now()
    const duration = Math.min(2600, Math.max(600, text.length * 28))
    let frame = 0
    const write = (now: number) => {
      const count = Math.ceil(Math.min(1, (now - started) / duration) * text.length)
      setShown(text.slice(0, count))
      if (count < text.length) frame = requestAnimationFrame(write)
    }
    frame = requestAnimationFrame(write)
    return () => cancelAnimationFrame(frame)
  }, [text])

  const writing = shown.length < text.length
  return <h1 className="research-title" tabIndex={-1}>
    <button type="button" className="research-title-button" aria-label={text} title={t('Rename')} onClick={onStartEdit}>
      <span className={`research-title-text${writing ? ' is-typing' : ''}`} aria-hidden>{shown}</span>
      <PencilLine size={14} aria-hidden />
    </button>
  </h1>
}

// The rename row (mockup `.ttl-edit`, R2): the field, "Suggest a short title", Save and ✕. Enter saves, Escape cancels.
export function TitleEditRow({ title, busy, canSuggest, onSave, onCancel, onSuggest }: {
  title: string; busy: boolean; canSuggest: boolean
  onSave: (title: string) => void; onCancel: () => void; onSuggest: () => void
}) {
  const [draft, setDraft] = useState(title)
  const field = useRef<HTMLInputElement>(null)
  useEffect(() => { field.current?.focus(); field.current?.select() }, [])
  const save = () => onSave(draft.trim())
  return <div className="research-title-edit">
    <input ref={field} className="research-title-input" aria-label={t('Research title')} value={draft} maxLength={160} spellCheck={false}
      onChange={e => setDraft(e.target.value)}
      onKeyDown={e => {
        if (e.key === 'Enter') { e.preventDefault(); save() }
        else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onCancel() }
      }} />
    <Button variant="ghost" size="sm" className="research-topbar-action research-title-suggest" disabled={busy || !canSuggest} onClick={onSuggest}
      title={t('The model names the research from its question and included sources, in at most 15 words.')}><Lightbulb size={16} className="size-4" aria-hidden /><span className="research-topbar-label">{t('Suggest a short title')}</span></Button>
    <Button size="sm" className="research-title-save" disabled={busy || !draft.trim()} onClick={save}>{t('Save')}</Button>
    <Button variant="ghost" size="icon-sm" className="research-title-cancel" aria-label={t('Cancel')} title={t('Cancel')} onClick={onCancel}><X size={16} aria-hidden /></Button>
  </div>
}

// What the chip says about the research's latest run (mockup `.runchip`, R3–R5): live work with a spinner, a pause the
// person asked for, or a run that stopped on its own (a failure, a limit, a refused search). An answer run that is
// writing says whether a version already exists.
function chipText(run: Run, hasAnswer: boolean) {
  const kind = t(runKindLabels[run.kind])
  if (run.kind === 'answer' && run.status === 'running') return `${kind} · ${t(hasAnswer ? 'Writing a new version' : 'Writing the first version')}`
  if (run.status === 'failed' || (run.status === 'paused' && run.pause_reason !== 'user_requested')) return `${kind} · ${t('Stopped')}`
  return `${kind} · ${t(runStatusLabels[run.status])}`
}

// The chip of the research's latest run and its controls. Pause sits beside a live chip as drawn; Cancel of a live run
// stays beside it (the mockup has no other way to stop a live run; §0 rule 5). A paused or stopped run of the thread is
// resumed or cancelled from the notice under its steps (R18, S9); a run the thread does not show (a title suggestion)
// has no such notice, so its Resume and Cancel stay here. A live run drawn as a card in the thread carries its own Pause
// and Cancel in the card head, so here it keeps only the chip.
export function RunChip({ run, hasAnswer, busy, inThread, controlsInCard = false, onControl }: {
  run: Run; hasAnswer: boolean; busy: boolean; inThread: boolean; controlsInCard?: boolean; onControl: (action: 'pause' | 'resume' | 'cancel') => void
}) {
  const active = ACTIVE.has(run.status)
  const text = chipText(run, hasAnswer)
  if (run.status === 'failed') return <span className="runchip is-warn"><TriangleAlert size={13} aria-hidden /><span className="runchip-text">{text}</span></span>
  const stopped = run.status === 'paused' && run.pause_reason !== 'user_requested'
  return <div className="run-strip">
    <span className={`runchip run-strip-status${active ? ' is-live' : ' is-warn'}`} data-run-id={run.id} tabIndex={-1}>
      {active ? <span className="runchip-dot" aria-hidden /> : stopped ? <TriangleAlert size={13} aria-hidden /> : <Pause size={13} aria-hidden />}
      <span className="runchip-text">{text}</span>
      {active && <Elapsed since={run.created_at} />}
      {active && <span className="runchip-sweep" aria-hidden />}
    </span>
    {active && !controlsInCard && run.status !== 'pause_requested' && <Button variant="ghost" size="sm" className="research-topbar-action run-strip-pause" disabled={busy} onClick={() => onControl('pause')}><Pause size={14} aria-hidden />{t('Pause')}</Button>}
    {!active && !inThread && run.status === 'paused' && !(run.pause_reason === 'search_query_failed' && searchQueryTriesLeft(run) === 0)
      && <Button variant="default" size="sm" disabled={busy} onClick={() => onControl('resume')}><Play size={14} aria-hidden />{t('Resume')}</Button>}
    {((active && !controlsInCard) || !inThread) && <Button variant="destructive" size="sm" className="run-strip-cancel" disabled={busy} onClick={() => onControl('cancel')}><X size={14} aria-hidden />{t('Cancel')}</Button>}
  </div>
}
