import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type RefObject } from 'react'
import { ArrowLeft, ChevronRight, ExternalLink, FileText, NotebookPen, RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { api, ApiError, type QueueAnswer, type QueueDecided, type QueueDetail, type QueueKind, type QueuePart, type QueueRow, type QueueRowView, type QueueRun, type QueueView, type ResearchView } from './api'
import { pageLocator, partLabelText, queueAnsweredText, queueAnswerLabels, queueAnswerOfCode, queueKindLabels, queueReasonText, queueStateOf, versionText, versionTones } from './labels'
import { PassageSheet } from './PassageSheet'
import type { CitationLabels } from './PdfTextDocument'
import { ConnectionIcon } from './connectionIcons'
import { Notice } from './Notice'
import { AuditSample } from './AuditSample'
import { OverridesLine } from './FlowReport'
import { useToast } from './Toast'
import { t, uiLocale } from './i18n'
import { scrollBehavior } from './motion'

// The human queue of an sw research (SW11.6, slice 17, D97): a list of the works that wait for a person, one row's
// question and what the two reading runs said, and five answers. Everything shown is what the backend read; the screen
// marks only the page text a verified quote was found as, and it never says an answer is right.

const KIND_ORDER = Object.keys(queueKindLabels) as Exclude<QueueKind, 'look_again'>[]
const ANSWERS: QueueAnswer[] = ['include', 'criterion_not_met', 'not_sure', 'pdf_wrong']
const toastText: Record<QueueAnswer, string> = {
  include: 'Included. Your choice shows in the sources as your own selection.',
  criterion_not_met: 'Recorded as not meeting the criterion.',
  not_sure: 'Left as awaiting a decision; it does not come back to the queue by itself.',
  pdf_wrong: 'PDF marked as wrong; the work moved to those waiting for a PDF.',
  pdf_confirmed: 'PDF confirmed; the next reading run reads this work. No run starts by itself.',
}

// Where a row opens: the page its question points at, found in the order of decision 2.
type PageChoice = { page: number; passageId: string | null; anchor: string | null; kind: 'quote' | 'closest' | 'cue' | 'page'; rendition?: boolean }
type SheetTarget = { passageId: string | null; assetId: string | null; page: number; view: 'text' | 'pdf'; anchor: string | null; expect: boolean; labels: CitationLabels } | { source: string }

function questionParts(runs: QueueRun[], part: string | undefined) {
  return runs.map(run => run.parts.find(p => p.part === part)).filter((p): p is QueuePart => Boolean(p))
}

function rowPage(row: QueueRow, detail: QueueDetail): PageChoice | null {
  if (row.kind === 'confirm_pdf') return detail.asset_id ? { page: 1, passageId: null, anchor: null, kind: 'page', rendition: detail.rendition } : null
  const parts = questionParts(detail.runs, row.question?.part)
  const quoted = parts.find(p => p.quote_verified && p.page !== null && p.passage_id)
  if (quoted) return { page: quoted.page!, passageId: quoted.passage_id, anchor: quoted.anchor_text, kind: 'quote', rendition: quoted.rendition }
  const near = parts.find(p => p.closest?.passage_id)?.closest
  if (near) return { page: near.page, passageId: near.passage_id, anchor: null, kind: 'closest', rendition: near.rendition }
  const cue = detail.cues.sentences.find(s => s.passage_id)
  if (cue) return { page: cue.page, passageId: cue.passage_id, anchor: null, kind: 'cue', rendition: cue.rendition }
  const shown = detail.runs[0]?.shown_pages[0]
  return detail.asset_id ? { page: shown ?? 1, passageId: null, anchor: null, kind: 'page', rendition: detail.rendition } : null
}

// The strip over the plain text says why the page was opened and whether anything is marked.
function labelsFor(kind: PageChoice['kind'], page: number, rendition?: boolean): CitationLabels {
  const mark = t(MARK_NAME)
  const locator = pageLocator(page, rendition)
  if (kind === 'quote') return {
    marked: t('The model’s quote, found in the text of {locator}. Only the text found on the page is marked.', { locator }),
    unmarked: t('The quote could not be marked exactly in the text of {locator}, so nothing is marked. Check the page in the PDF.', { locator }),
    mark,
  }
  if (kind === 'closest') {
    const text = t('The model’s quote was not found in the text, so nothing on {locator} is marked. Check the page in the PDF.', { locator })
    return { marked: text, unmarked: text, mark }
  }
  const text = t(kind === 'cue' ? '{locator}: a sentence on this page holds a phrase of this part. Nothing is marked.' : '{locator}. Nothing is marked.', { locator })
  return { marked: text, unmarked: text, mark }
}

function useNarrow() {
  const query = '(max-width: 760px)'
  const [narrow, setNarrow] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const list = window.matchMedia(query)
    const change = () => setNarrow(list.matches)
    list.addEventListener('change', change)
    return () => list.removeEventListener('change', change)
  }, [])
  return narrow
}

const keyOf = (row: QueueRow) => `${row.source_version_id}:${row.row_token}`
const MARK_NAME = 'The model’s quote, as found in the page text'
// A look_again row names the earlier answer beside its label (decision 5): the person sees it without opening the row.
const kindText = (row: QueueRow) => {
  if (row.kind !== 'look_again') return t(queueKindLabels[row.kind])
  const earlier = queueAnswerOfCode[row.reason_code]
  return earlier ? `${t('Decided under an earlier question')} · ${t(queueAnsweredText[earlier])}` : t('Decided under an earlier question')
}
const dateText = (iso: string) => new Date(iso).toLocaleString(uiLocale(), { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

export function HumanQueue({ researchId, view, dark, onChanged, onShowInSources }: { researchId: string; view: ResearchView; dark: boolean; onChanged: () => Promise<void>; onShowInSources: (workId: string) => void }) {
  const toast = useToast()
  const narrow = useNarrow()
  const [queue, setQueue] = useState<QueueView | null>(null)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<string | null>(null)  // a work id: its version may change under it
  // Details by row and token. The token also moves with the file's text (a new extraction or OCR), so a detail kept
  // under the list's token shows the passages that token was computed from.
  const [details, setDetails] = useState<Record<string, QueueRowView>>({})
  const [unsettled, setUnsettled] = useState<string | null>(null)  // a row whose detail kept disagreeing with the list
  const [detailError, setDetailError] = useState('')
  const [kindFilter, setKindFilter] = useState<'all' | QueueKind>('all')
  const [reasonFilter, setReasonFilter] = useState('all')
  const [showDetail, setShowDetail] = useState(false)  // at 760 px and below the detail takes the list's place
  const [note, setNote] = useState<{ work: string | null; text: string; open: boolean }>({ work: null, text: '', open: false })
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  // A 409: whether the row left the queue, and the note that was being written for it, which is kept.
  const [conflict, setConflict] = useState<{ work: string; gone: boolean; title: string; note: string } | null>(null)
  const [sheet, setSheet] = useState<SheetTarget | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const titleRef = useRef<HTMLHeadingElement>(null)
  const openWhenLoaded = useRef<string | null>(null)  // the row (and token) Enter was pressed on while it loaded
  const listRequest = useRef(0)
  const latest = useRef<Promise<QueueView | null>>(Promise.resolve(null))
  const mismatches = useRef(new Map<string, number>())

  // Only the newest list request is applied, and a caller whose request was overtaken gets the newest list, not its own.
  const load = useCallback((): Promise<QueueView | null> => {
    const request = ++listRequest.current
    const reading: Promise<QueueView | null> = api.queue(researchId).then(next => {
      if (request !== listRequest.current) return latest.current
      setQueue(next)
      setError('')
      const live = new Set(next.rows.map(keyOf))
      setDetails(prev => Object.fromEntries(Object.entries(prev).filter(([key]) => live.has(key))))
      return next
    }, e => {
      if (request !== listRequest.current) return latest.current
      setError(e instanceof Error ? e.message : String(e))
      return null
    })
    latest.current = reading
    return reading
  }, [researchId])
  // Every recorded event can add or take a row: a reading run in flight writes decisions, another tab answers one.
  useEffect(() => { void load() }, [load, view.last_event_id])

  const rows = queue?.rows ?? []
  const open = rows.filter(r => r.kind !== 'look_again')
  const lookAgain = rows.filter(r => r.kind === 'look_again')
  const shownOpen = open.filter(r => (kindFilter === 'all' || r.kind === kindFilter) && (reasonFilter === 'all' || r.reason_code === reasonFilter))
  const ordered = [...shownOpen, ...(kindFilter === 'all' && reasonFilter === 'all' ? lookAgain : [])]
  // Until a row is chosen the first one is, except at 760 px and below, where the list comes first.
  const selectedWork = selected ?? (narrow ? null : ordered[0]?.work_id ?? null)
  const current = rows.find(r => r.work_id === selectedWork) ?? null
  const currentView = current ? details[keyOf(current)] : undefined
  const detail = currentView?.detail
  // An answer is sent only on a detail whose row and token are the ones the list shows.
  const answerable = Boolean(current && currentView?.row?.row_token === current.row_token)
  const gone = Boolean(selected && queue && !current)
  // The active row stays in view while the arrow keys move through a long list.
  useEffect(() => {
    if (selectedWork) document.getElementById(`queue-row-${selectedWork}`)?.scrollIntoView({ block: 'nearest', behavior: scrollBehavior() })
  }, [selectedWork])

  // The selected row's detail, then the next row's in the background: one row ahead, so the next answer does not wait.
  const inflight = useRef(new Set<string>())
  const drop = (key: string) => setDetails(prev => Object.fromEntries(Object.entries(prev).filter(([k]) => k !== key)))
  const fetchDetail = useCallback(async (row: QueueRow) => {
    const key = keyOf(row)
    if (inflight.current.has(key)) return
    inflight.current.add(key)
    try {
      const value = await api.queueRow(researchId, row.source_version_id)
      setDetails(prev => ({ ...prev, [key]: value }))
      if (value.row?.row_token === row.row_token) { mismatches.current.delete(key); return }
      // The row moved between the list and its detail: the list is read again and the detail with it, twice at most;
      // a row that still disagrees says so and waits for the person to read it again.
      const tries = (mismatches.current.get(key) ?? 0) + 1
      mismatches.current.set(key, tries)
      if (tries > 2) { setUnsettled(key); return }
      await load()
      setDetails(prev => Object.fromEntries(Object.entries(prev).filter(([k]) => k !== key)))
    } finally { inflight.current.delete(key) }
  }, [researchId, load])
  const currentKey = current ? keyOf(current) : null
  const nextRow = current ? ordered[ordered.findIndex(r => r.work_id === current.work_id) + 1] : undefined
  const nextKey = nextRow ? keyOf(nextRow) : null
  useEffect(() => {
    if (!current || !currentKey) return
    if (!details[currentKey]) fetchDetail(current).catch(e => setDetailError(e instanceof Error ? e.message : String(e)))
    else if (nextRow && nextKey && !details[nextKey]) void fetchDetail(nextRow).catch(() => undefined)
  }, [currentKey, nextKey, details, fetchDetail])  // eslint-disable-line react-hooks/exhaustive-deps

  const choose = (work: string | null) => {
    setSelected(work)
    setActionError('')
    setDetailError('')
    if (conflict && !conflict.gone && conflict.work !== work) setConflict(null)  // a kept note stays until the next answer
    // A note belongs to the work it was written for; it is kept while that work stays selected, across refreshes.
    setNote(prev => (prev.work === work ? prev : { work, text: '', open: false }))
  }

  const openPage = useCallback((row: QueueRow, found: QueueDetail, view: 'text' | 'pdf') => {
    const choice = rowPage(row, found)
    if (!choice) return
    setSheet({ passageId: choice.passageId, assetId: choice.passageId ? null : found.asset_id, page: choice.page, view,
      anchor: choice.anchor, expect: choice.kind !== 'cue' && choice.kind !== 'page', labels: labelsFor(choice.kind, choice.page, choice.rendition) })
  }, [])
  // Enter on a row whose detail is still loading opens that row's page once its detail arrives, and no other row's.
  useEffect(() => {
    if (!openWhenLoaded.current || openWhenLoaded.current !== currentKey || !current || !detail || !answerable) return
    openWhenLoaded.current = null
    openPage(current, detail, 'pdf')
  }, [currentKey, current, detail, answerable, openPage])

  const openPart = (part: QueuePart) => {
    if (part.quote_verified && part.page !== null && part.passage_id) {
      setSheet({ passageId: part.passage_id, assetId: null, page: part.page, view: 'text', anchor: part.anchor_text, expect: true, labels: labelsFor('quote', part.page, part.rendition) })
    } else if (part.closest?.passage_id) {
      setSheet({ passageId: part.closest.passage_id, assetId: null, page: part.closest.page, view: 'text', anchor: null, expect: true, labels: labelsFor('closest', part.closest.page, part.closest.rendition) })
    } else if (part.passage_id) {
      const text = t('The model’s quote was not found in the text of the page it named, so nothing is marked. Check the page in the PDF.')
      setSheet({ passageId: part.passage_id, assetId: null, page: 1, view: 'text', anchor: null, expect: true, labels: { marked: text, unmarked: text, mark: t(MARK_NAME) } })
    }
  }

  const focusList = () => requestAnimationFrame(() => listRef.current?.focus({ preventScroll: false }))

  async function reloadAll() {
    const [next] = await Promise.all([load(), onChanged()])
    return next
  }

  async function answer(row: QueueRow, choice: QueueAnswer) {
    if (!answerable) return
    const token = row.row_token
    const written = note.work === row.work_id ? note.text : ''
    const index = ordered.findIndex(r => r.work_id === row.work_id)
    const after = ordered[index + 1] ?? ordered[index - 1] ?? null
    setBusy(true)
    setActionError('')
    try {
      const result = await api.answerQueueRow(researchId, row.source_version_id, choice, token, written.trim() || null)
      const next = await reloadAll()
      const target = next?.rows.find(r => r.work_id === after?.work_id) ?? next?.rows[0] ?? null
      setConflict(null)
      setNote({ work: target?.work_id ?? null, text: '', open: false })
      setSelected(target?.work_id ?? null)
      if (!target && narrow) setShowDetail(false)
      toast('success', t(toastText[choice]), { label: t('Undo'), run: () => { void undo(row.source_version_id, result.undo_token) } })
      if (narrow && target) requestAnimationFrame(() => titleRef.current?.focus())
      else focusList()
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // The row moved between showing and answering: the queue, its detail and the research view are read again.
        const next = await reloadAll()
        const still = next?.rows.some(r => r.work_id === row.work_id) ?? false
        setConflict({ work: row.work_id, gone: !still, title: row.title, note: written.trim() })
        if (!still) {
          // The selection moves on; the note stays with its work, shown in the notice rather than under another row.
          const target = (next?.rows.find(r => r.work_id === after?.work_id) ?? next?.rows[0])?.work_id ?? null
          setSelected(target)
          setNote({ work: target, text: '', open: false })
        }
      } else setActionError(e instanceof Error ? e.message : String(e))
    } finally { setBusy(false) }
  }

  async function undo(sourceVersionId: string, token: string) {
    setBusy(true)
    try {
      await api.undoQueueDecision(researchId, sourceVersionId, token)
      await reloadAll()
      toast('success', t('Your decision was taken back.'))
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        await reloadAll()
        toast('warning', e.reason === 'reading_started'
          ? t('The reading has begun, so this confirmation can no longer be taken back; you can decide about the work instead.')
          : t('This decision changed after it was shown, so it was not taken back. The latest state is loaded.'))
      } else toast('error', e instanceof Error ? e.message : String(e))
    } finally { setBusy(false) }
  }

  const onListKey = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!ordered.length) return
    const index = Math.max(0, ordered.findIndex(r => r.work_id === selectedWork))
    const move = (to: number) => { event.preventDefault(); choose(ordered[Math.min(ordered.length - 1, Math.max(0, to))].work_id) }
    if (event.key === 'ArrowDown') move(selectedWork === null ? 0 : index + 1)
    else if (event.key === 'ArrowUp') move(index - 1)
    else if (event.key === 'Home') move(0)
    else if (event.key === 'End') move(ordered.length - 1)
    else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      if (!current) { choose(ordered[index].work_id); return }
      if (narrow) { setShowDetail(true); requestAnimationFrame(() => titleRef.current?.focus()); return }
      if (detail && answerable) openPage(current, detail, 'pdf')
      else openWhenLoaded.current = currentKey
    }
  }
  const onRowClick = (row: QueueRow) => {
    choose(row.work_id)
    if (narrow) { setShowDetail(true); requestAnimationFrame(() => titleRef.current?.focus()) }
  }
  const backToList = () => { setShowDetail(false); focusList() }

  if (error && !queue) return <Notice tone="error">{t('Could not load the queue: {error}', { error })}</Notice>
  if (!queue) return <p className="empty-inline" role="status">{t('Loading the queue…')}</p>

  const counts = queue.counts
  const decidedCount = Object.values(counts.decided).reduce((sum, n) => sum + n, 0)
  const kindCount = (kind: QueueKind) => counts.by_kind[kind] ?? 0
  const reasons = Object.keys(counts.by_reason)
  const emptyFacts = [decidedCount > 0 && t(decidedCount === 1 ? 'You decided {n} work' : 'You decided {n} works', { n: decidedCount }),
    counts.user_selected > 0 && t(counts.user_selected === 1 ? 'you chose {n} work from the sources' : 'you chose {n} works from the sources', { n: counts.user_selected })].filter(Boolean)
  const option = (row: QueueRow) => {
    const kind = kindText(row)
    return <div key={row.work_id} id={`queue-row-${row.work_id}`} role="option" aria-selected={row.work_id === selectedWork}
      aria-label={`${row.title}. ${kind}. ${t('Awaiting a decision')}`}
      className={`queue-row${row.work_id === selectedWork ? ' is-selected' : ''}`} onClick={() => onRowClick(row)}>
      <span className="queue-row-place" aria-hidden>{row.place ?? '–'}</span>
      <span className="queue-row-main" aria-hidden>
        <span className="queue-row-title">{row.title}</span>
        <span className="queue-row-facts">
          <span className={`ref-pill is-${versionTones[row.version_label ?? ''] ?? 'unstated'}`}>{versionText(row.version_label)}</span>
          <span>{kind}</span>
          {row.arm === 'chain' && <span className="queue-row-chain">{t('from the citation chain')}</span>}
        </span>
      </span>
    </div>
  }

  return <section className="queue-panel" aria-labelledby="queue-heading">
    <div className="workspace-pane-head"><div><h2 id="queue-heading">{t('Awaiting your decision')}</h2>
      <p>{t('Works the reading could not settle. Each row asks one question; your answer is recorded as your decision and can be taken back.')}</p></div></div>
    <OverridesLine overrides={view.counts.overrides} />
    {error && <Notice tone="error">{t('Could not load the queue: {error}', { error })}</Notice>}
    {!rows.length ? <div className="queue-empty">
      <p className="empty-inline">{t('No rows in the queue.')}</p>
      {emptyFacts.length > 0 && <p className="empty-inline">{`${emptyFacts.join('; ')}.`}</p>}
    </div> : <div className={`queue-layout${narrow && showDetail ? ' is-detail' : ''}`}>
      <div className="queue-list-pane">
        <div className="queue-filters">
          <div className="queue-chips" role="group" aria-label={t('Show rows')}>
            <button type="button" aria-pressed={kindFilter === 'all'} onClick={() => setKindFilter('all')}>{t('All')}<span>{open.length}</span></button>
            {KIND_ORDER.filter(kind => kindCount(kind) > 0).map(kind => <button key={kind} type="button" aria-pressed={kindFilter === kind} onClick={() => setKindFilter(kind)}>{t(queueKindLabels[kind])}<span>{kindCount(kind)}</span></button>)}
          </div>
          {reasons.length > 1 && <Select value={reasonFilter} onValueChange={value => { if (value) setReasonFilter(String(value)) }}>
            <SelectTrigger className="queue-reason-filter" aria-label={t('Filter rows by why they are here')}><SelectValue>{(value: string) => value === 'all' ? t('Every reason') : queueReasonText(value)}</SelectValue></SelectTrigger>
            <SelectContent className="intake-select-content" align="start" alignItemWithTrigger={false}>
              <SelectItem value="all">{t('Every reason')}</SelectItem>
              {reasons.map(code => <SelectItem key={code} value={code}><span className="source-filter-option"><span>{queueReasonText(code)}</span><small>{counts.by_reason[code]}</small></span></SelectItem>)}
            </SelectContent>
          </Select>}
        </div>
        <div ref={listRef} className="queue-list" role="listbox" tabIndex={0} aria-label={t('Rows awaiting your decision')}
          aria-activedescendant={current && ordered.includes(current) ? `queue-row-${current.work_id}` : undefined} onKeyDown={onListKey}>
          {shownOpen.length > 0 && <div role="group" aria-label={t('Awaiting your decision')}>{shownOpen.map(option)}</div>}
          {!shownOpen.length && <p className="empty-inline queue-filter-empty">{t('No row matches this filter.')}</p>}
          {kindFilter === 'all' && reasonFilter === 'all' && lookAgain.length > 0 && <div role="group" aria-labelledby="queue-look-again">
            <p id="queue-look-again" className="queue-group-head">{t('Decided under an earlier question; look again')}</p>
            {lookAgain.map(option)}
          </div>}
        </div>
        <p className="queue-keys" aria-hidden>{t('↑↓ choose a row · Enter opens its page in the PDF')}</p>
      </div>

      <div className="queue-detail" aria-labelledby={current ? 'queue-detail-title' : undefined}>
        {narrow && <button type="button" className="queue-back" onClick={backToList}><ArrowLeft size={15} aria-hidden />{t('Back to the list')}</button>}
        {conflict && conflict.work === selectedWork && !conflict.gone && <Notice tone="attention">{t('This row changed after it was shown; its current state is loaded. Your answer was not saved.')}</Notice>}
        {conflict && conflict.gone && <Notice tone="attention">{t('The row you answered left the queue after it was shown. Your answer was not saved.')}
          {conflict.note && <p className="queue-kept-note">{t('Your note for “{title}” is kept here:', { title: conflict.title })} <q>{conflict.note}</q></p>}</Notice>}
        {gone && !conflict && <Notice tone="attention">{t('This work is no longer in the queue. Nothing was saved; your note is kept below.')}</Notice>}
        {current && currentView && !answerable && !detailError && (unsettled === currentKey
          ? <Notice tone="attention">{t('This row kept changing while it was read, so it cannot be answered yet.')}{' '}
            <button type="button" className="queue-link" onClick={() => { mismatches.current.delete(currentKey!); setUnsettled(null); drop(currentKey!) }}>{t('Read it again')}</button></Notice>
          : <p className="queue-muted" role="status">{t('Reading this row again…')}</p>)}
        {current ? <RowDetail row={current} rowView={currentView} detailError={detailError} titleRef={titleRef}
          onOpenPage={() => detail && openPage(current, detail, 'pdf')} onOpenPart={openPart}
          onOpenSource={() => setSheet({ source: current.source_version_id })}
          onOpenCue={(passageId, page, rendition) => setSheet({ passageId, assetId: null, page, view: 'text', anchor: null, expect: false, labels: labelsFor('cue', page, rendition) })} />
          : !gone && <p className="empty-inline">{t('Choose a row to see its question.')}</p>}
        {(current || (gone && note.text)) && <footer className="queue-foot">
          {actionError && <Notice tone="error">{actionError}</Notice>}
          {note.open || note.text ? <label className="queue-note"><span>{t('Note')}<small>{t('{n} of 1000 characters', { n: note.text.length })}</small></span>
            <textarea value={note.text} maxLength={1000} rows={2} onChange={e => setNote({ work: selectedWork, text: e.target.value, open: true })} /></label>
            : <button type="button" className="queue-note-toggle" onClick={() => setNote({ work: selectedWork, text: '', open: true })}><NotebookPen size={14} aria-hidden />{t('Add a note')}</button>}
          {current && <div className="queue-answers" role="group" aria-label={t('Your answer')}>
            {(current.kind === 'confirm_pdf' ? ['pdf_confirmed' as const, ...ANSWERS] : ANSWERS).map(choice =>
              <Button key={choice} variant={choice === 'pdf_confirmed' ? 'default' : 'outline'} disabled={busy || !answerable} onClick={() => void answer(current, choice)}>{t(queueAnswerLabels[choice])}</Button>)}
          </div>}
          <p className="queue-foot-note">{t('Semantic support not checked. Your answer is recorded as your decision; DEIXIS does not say whether it is right.')}</p>
        </footer>}
      </div>
    </div>}

    {queue.decided.length > 0 && <Decided entries={queue.decided} busy={busy} onUndo={entry => { if (entry.undo_token) void undo(entry.source_version_id, entry.undo_token) }} onOpen={svid => setSheet({ source: svid })} />}

    <AuditSample researchId={researchId} lastEvent={view.last_event_id} onChanged={onChanged} onOpenSource={svid => setSheet({ source: svid })} onShowInSources={onShowInSources} />

    {sheet && <PassageSheet researchId={researchId} dark={dark} sources={view.sources}
      passageId={'source' in sheet ? null : sheet.passageId} assetId={'source' in sheet ? null : sheet.assetId}
      sourceVersionId={'source' in sheet ? sheet.source : null} initialView={'source' in sheet ? 'text' : sheet.view}
      initialPage={'source' in sheet ? 1 : sheet.page} highlightTexts={'source' in sheet || !sheet.anchor ? [] : [sheet.anchor]}
      expectHighlight={'source' in sheet ? false : sheet.expect} citationLabels={'source' in sheet ? undefined : sheet.labels}
      onClose={() => { setSheet(null); if (!narrow) focusList() }} />}
  </section>
}

function RowDetail({ row, rowView, detailError, titleRef, onOpenPage, onOpenPart, onOpenSource, onOpenCue }: {
  row: QueueRow; rowView: QueueRowView | undefined; detailError: string; titleRef: RefObject<HTMLHeadingElement | null>
  onOpenPage: () => void; onOpenPart: (part: QueuePart) => void; onOpenSource: () => void; onOpenCue: (passageId: string, page: number, rendition?: boolean) => void
}) {
  const detail = rowView?.detail
  const choice = detail ? rowPage(row, detail) : null
  const kind = kindText(row)
  const part = row.question?.part
  const question = row.question
    ? t('Does this paper have the part “{part}”?', { part: row.question.part })
    : row.kind === 'confirm_pdf' ? t('Is this PDF the work named here?')
    : row.kind === 'choose_version' ? t('The versions of this work were read to opposite decisions. Which one holds?')
    : t('You decided this work under an earlier question. Does your decision still hold?')
  const unverified = detail ? detail.runs.flatMap(run => run.parts.filter(p => p.part === part && p.label === 'present' && p.quote_verified === false && p.quote)
    .map(p => ({ run: run.run_no, part: p }))) : []
  return <>
    <div className="queue-detail-head">
      <p className="queue-detail-meta">{[row.place !== null && t('No. {n} in the order', { n: row.place }), t('Awaiting a decision'), kind, row.arm === 'chain' && t('from the citation chain')].filter(Boolean).join(' · ')}</p>
      <h3 id="queue-detail-title" ref={titleRef} tabIndex={-1} className="queue-detail-title"><button type="button" onClick={onOpenSource}>{row.title}</button></h3>
      <div className="source-chips">
        <span className={`ref-pill is-${versionTones[row.version_label ?? ''] ?? 'unstated'}`}>{versionText(row.version_label)}</span>
        {row.year && <span className="ref-pill">{row.year}</span>}
        {row.doi && <a className="source-link-chip" href={`https://doi.org/${row.doi}`} target="_blank" rel="noreferrer"><ConnectionIcon id="doi" /><span>{row.doi}</span><ExternalLink size={12} aria-hidden /></a>}
      </div>
      {choice && <Button variant="outline" size="sm" className="queue-open-page" onClick={onOpenPage}><FileText size={14} aria-hidden />{t('Open page {page} in the PDF', { page: choice.page })}</Button>}
    </div>
    <section className="queue-question">
      <p className="queue-question-text">{question}</p>
      {row.question?.definition && <p className="queue-question-definition">{row.question.definition}</p>}
      <p className="queue-why"><span>{t('Why it is here:')}</span> {queueReasonText(row.reason_code)} <code>{row.reason_code}</code></p>
    </section>
    {detailError ? <Notice tone="error">{t('Could not load this row: {error}', { error: detailError })}</Notice>
      : !rowView ? <p className="empty-inline" role="status">{t('Loading this row…')}</p>
      : !detail ? <Notice tone="attention">{t('This row changed while it was loading; the queue is being read again.')}</Notice>
      : <>
        {detail.identity && <section className="queue-identity" aria-label={t('The PDF and the work')}>
          <div><h4>{t('First page of the PDF')}</h4><div className="queue-first-page">{detail.identity.first_page ?? t('No text was extracted from the first page.')}</div></div>
          <div><h4>{t('The work this PDF was fetched for')}</h4><p className="queue-serif">{detail.identity.work_title}</p>
            {detail.identity.work_doi && <a className="source-link-chip" href={`https://doi.org/${detail.identity.work_doi}`} target="_blank" rel="noreferrer"><ConnectionIcon id="doi" /><span>{detail.identity.work_doi}</span><ExternalLink size={12} aria-hidden /></a>}</div>
        </section>}
        {detail.versions ? <section className="queue-runs" aria-label={t('What each version was read as')}>
          {detail.versions.map(version => <div key={version.source_version_id} className="queue-run">
            <h4><span className={`ref-pill is-${versionTones[version.version_label ?? ''] ?? 'unstated'}`}>{versionText(version.version_label)}</span> {t(version.decision.outcome === 'include' ? 'read as included' : version.decision.outcome === 'criterion_not_met' ? 'read as not meeting the criterion' : 'read as unresolved')}</h4>
            {version.runs.map(run => <RunParts key={run.run_no} run={run} part={part} onOpenPart={onOpenPart} />)}
          </div>)}
        </section> : detail.runs.length > 0 && <section className="queue-runs" aria-label={t('What the two runs said')}>
          {detail.runs.map(run => <div key={run.run_no} className="queue-run"><RunParts run={run} part={part} onOpenPart={onOpenPart} /></div>)}
        </section>}
        {unverified.length > 0 && <section className="queue-closest" aria-label={t('The closest text')}>
          {unverified.map(({ run, part: p }) => <div key={run}>
            <Notice tone="attention">{p.closest
              ? t('Run {run}: the model’s quote was not found in the text. The closest text is beside it; match ratio {ratio}.', { run, ratio: p.closest.ratio.toLocaleString(uiLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }) })
              : t('Run {run}: the model’s quote was not found in the text, and the pages this run was shown hold no close text.', { run })}</Notice>
            {p.closest && <div className="queue-pair">
              <div><h5>{t('The model’s quote')}</h5><blockquote className="queue-quote">{p.quote}</blockquote></div>
              <div><h5>{t('The closest text · {locator}', { locator: pageLocator(p.closest.page, p.closest.rendition) })}</h5><blockquote className="queue-quote">{p.closest.text}</blockquote></div>
            </div>}
          </div>)}
        </section>}
        {row.question && <section className="queue-cues">
          <h4>{t('Sentences with this part’s phrases')}</h4>
          {detail.cues.sentences.length ? <>
            <ul>{detail.cues.sentences.map((cue, i) => <li key={i}><p className="queue-serif">{cue.sentence}</p>
              {cue.passage_id && <button type="button" className="queue-page-link" onClick={() => onOpenCue(cue.passage_id!, cue.page, cue.rendition)}>{pageLocator(cue.page, cue.rendition)}<ChevronRight size={13} aria-hidden /></button>}</li>)}</ul>
            {detail.cues.total > detail.cues.sentences.length && <p className="queue-muted">{t('{shown} of {total} sentences shown', { shown: detail.cues.sentences.length, total: detail.cues.total })}</p>}
          </> : <p className="queue-muted">{t('This part’s phrases do not occur in the text.')}</p>}
        </section>}
      </>}
  </>
}

function RunParts({ run, part, onOpenPart }: { run: QueueRun; part: string | undefined; onOpenPart: (part: QueuePart) => void }) {
  return <>
    <h5 className="queue-run-head">{t('Run {n}', { n: run.run_no })}<small>{run.shown_pages.length ? t('pages shown: {pages}', { pages: run.shown_pages.join(', ') }) : t('no pages shown')}</small></h5>
    {run.parts.map(p => <div key={p.part} className={`queue-part${p.part === part ? ' is-question' : ''}`}>
      <p className="queue-part-head"><span>{p.part}</span><span className="ref-pill">{partLabelText(p.label)}</span>{p.part === part && <small className="queue-part-asked">{t('this row’s question')}</small>}</p>
      {p.quote && <blockquote className="queue-quote">{p.quote}</blockquote>}
      {p.label === 'present' && <p className="queue-part-note">{p.quote_verified ? t('Found on the page.') : t('Not found in the text.')}
        {(p.passage_id || p.closest?.passage_id) && <button type="button" className="queue-page-link" onClick={() => onOpenPart(p)}>{p.quote_verified && p.page !== null ? pageLocator(p.page, p.rendition) : t('Open the page')}<ChevronRight size={13} aria-hidden /></button>}</p>}
      {p.rationale && <p className="queue-rationale">{p.rationale}</p>}
    </div>)}
  </>
}

function Decided({ entries, busy, onUndo, onOpen }: { entries: QueueDecided[]; busy: boolean; onUndo: (entry: QueueDecided) => void; onOpen: (sourceVersionId: string) => void }) {
  return <details className="queue-decided">
    <summary><ChevronRight size={14} aria-hidden className="queue-decided-chevron" />{t('Your decisions ({n})', { n: entries.length })}</summary>
    <ul>{entries.map(entry => <li key={entry.work_id}>
      <div>
        <button type="button" className="queue-decided-title" onClick={() => onOpen(entry.source_version_id)}>{entry.title}</button>
        <p className="queue-muted">{[queueStateOf(entry.answer), t(queueAnsweredText[entry.answer]), dateText(entry.created_at)].join(' · ')}</p>
        {entry.note && <p className="queue-decided-note">{entry.note}</p>}
      </div>
      {entry.undo_token
        ? <Button variant="ghost" size="sm" disabled={busy} onClick={() => onUndo(entry)} aria-label={t('Undo your decision on {title}', { title: entry.title })}><RotateCcw size={14} aria-hidden />{t('Undo')}</Button>
        : <p className="queue-muted">{t('The reading has begun, so this can no longer be taken back.')}</p>}
    </li>)}</ul>
  </details>
}
