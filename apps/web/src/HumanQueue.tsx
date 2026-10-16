import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, ChevronRight, CircleCheck, ExternalLink, Eye, Info, NotebookPen, RotateCcw, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { api, ApiError, type QueueAnswer, type QueueDecided, type QueueDetail, type QueueKind, type QueuePart, type QueueRow, type QueueRowView, type QueueRun, type QueueView, type ResearchView } from './api'
import { pageLocator, partLabelText, queueAnsweredText, queueAnswerLabels, queueAnswerOfCode, queueKindLabels, queueReasonText, queueStateOf, versionText, versionTones } from './labels'
import { PassageSheet } from './PassageSheet'
import type { CitationLabels } from './PdfTextDocument'
import { ConnectionIcon } from './connectionIcons'
import { Notice } from './Notice'
import { OverridesLine } from './FlowReport'
import { useToast } from './Toast'
import { t, uiLocale } from './i18n'

// The human queue of an sw research (SW11.6, slice 17, D97): a list of the works that wait for a person, one row's
// question and what the two reading runs said, and five answers. Everything shown is what the backend read; the screen
// marks only the page text a verified quote was found as, and it never says an answer is right.

const KIND_ORDER = Object.keys(queueKindLabels) as Exclude<QueueKind, 'look_again'>[]
const ANSWERS: QueueAnswer[] = ['include', 'criterion_not_met', 'not_sure', 'pdf_wrong']
// The one question of a row is "Is this paper a source for the question?": yes records `include`, no records
// `criterion_not_met` (the button says so). A PDF-identity row keeps the original labels. The answers keep their stored meaning; only the words on the buttons are the question's.
const answerWords: Record<QueueAnswer, string> = { ...queueAnswerLabels, include: 'Yes', criterion_not_met: 'No, it does not meet the criterion' }
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

const keyOf = (row: QueueRow) => `${row.source_version_id}:${row.row_token}`
const MARK_NAME = 'The model’s quote, as found in the page text'
// A look_again row names the earlier answer beside its label (decision 5): the person sees it without opening the row.
const kindText = (row: QueueRow) => {
  if (row.kind !== 'look_again') return t(queueKindLabels[row.kind])
  const earlier = queueAnswerOfCode[row.reason_code]
  return earlier ? `${t('Decided under an earlier question')} · ${t(queueAnsweredText[earlier])}` : t('Decided under an earlier question')
}
const dateText = (iso: string) => new Date(iso).toLocaleString(uiLocale(), { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
// Each card's head (mockup `.qcard header`): a short name of the kind and what came up. The words name the step that
// raised the row: these rows come from the full-text reading, not from abstract screening.
const CARD_HEADS: Record<QueueKind, [string, string]> = {
  confirm_quote: ['Quote check', 'a quote was not found on its page'],
  choose_run: ['Reading', 'the two reading runs disagreed'],
  choose_version: ['Version', 'two versions of this work; they are different sources, not interchangeable'],
  confirm_pdf: ['PDF check', 'is this the right file?'],
  confirm_absent: ['Missing part', 'both runs read a required part as absent'],
  find_part: ['Missing part', 'the runs did not find this part'],
  confirm_results: ['Protocol', 'results, or only a plan?'],
  look_again: ['Look again', 'you decided this under an earlier question'],
}
// What each answer does, under its label (mockup `.qopts small`), in the words of the toast it leads to.
const ANSWER_NOTES: Partial<Record<QueueAnswer, string>> = {
  include: 'Recorded as your own selection in the sources',
  not_sure: 'Leaves it awaiting a decision; it does not come back by itself',
  pdf_wrong: 'The work moves to those waiting for a PDF',
  pdf_confirmed: 'The next reading run reads this work; no run starts by itself',
}
const ANSWER_ICONS: Record<QueueAnswer, typeof Check> = { include: Check, criterion_not_met: X, not_sure: Info, pdf_wrong: X, pdf_confirmed: Check }
const PAGE = 20  // cards shown at once; the rest come with "Show more"
const IN_FLIGHT = 2  // row details read at a time

type Note = { text: string; open: boolean }

export function HumanQueue({ researchId, view, dark, onChanged }: { researchId: string; view: ResearchView; dark: boolean; onChanged: () => Promise<void> }) {
  const toast = useToast()
  const [queue, setQueue] = useState<QueueView | null>(null)
  const [error, setError] = useState('')
  // Details by row and token. The token also moves with the file's text (a new extraction or OCR), so a detail kept
  // under the list's token shows the passages that token was computed from.
  const [details, setDetails] = useState<Record<string, QueueRowView>>({})
  const [detailErrors, setDetailErrors] = useState<Record<string, string>>({})
  const [unsettled, setUnsettled] = useState<Set<string>>(new Set())  // rows whose detail kept disagreeing with the list
  const [kindFilter, setKindFilter] = useState<'all' | QueueKind>('all')
  const [reasonFilter, setReasonFilter] = useState('all')
  const [limit, setLimit] = useState(PAGE)
  // A note belongs to the work it was written for and stays with it across refreshes.
  const [notes, setNotes] = useState<Record<string, Note>>({})
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<{ work: string; text: string } | null>(null)
  // A 409: whether the row left the queue, and the note that was being written for it, which is kept.
  const [conflict, setConflict] = useState<{ work: string; gone: boolean; title: string; note: string } | null>(null)
  const [sheet, setSheet] = useState<SheetTarget | null>(null)
  const sheetOpener = useRef<HTMLElement | null>(null)
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
      // A detail that failed to load is tried again with the next list read, not held back by its old error.
      setDetailErrors({})
      // A kind or reason filter whose rows are all gone falls back to every row, so no filter is left with nothing to
      // show and no control to clear it (the chips hide when one kind is left).
      const open = next.rows.filter(r => r.kind !== 'look_again')
      setKindFilter(kind => kind === 'all' || open.some(r => r.kind === kind) ? kind : 'all')
      setReasonFilter(code => code === 'all' || open.some(r => r.reason_code === code) ? code : 'all')
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
  const shown = ordered.slice(0, limit)
  const shownOpenCards = shown.filter(r => r.kind !== 'look_again')
  const shownLookAgain = shown.filter(r => r.kind === 'look_again')

  // The details of the cards on screen, two at a time, in card order.
  const inflight = useRef(new Set<string>())
  const fetchDetail = useCallback(async (row: QueueRow) => {
    const key = keyOf(row)
    if (inflight.current.has(key)) return
    inflight.current.add(key)
    try {
      const value = await api.queueRow(researchId, row.source_version_id)
      setDetails(prev => ({ ...prev, [key]: value }))
      setDetailErrors(prev => { const { [key]: _, ...rest } = prev; return rest })
      if (value.row?.row_token === row.row_token) { mismatches.current.delete(key); return }
      // The row moved between the list and its detail: the list is read again and the detail with it, twice at most;
      // a row that still disagrees says so and waits for the person to read it again.
      const tries = (mismatches.current.get(key) ?? 0) + 1
      mismatches.current.set(key, tries)
      if (tries > 2) { setUnsettled(prev => new Set(prev).add(key)); return }
      await load()
      setDetails(prev => Object.fromEntries(Object.entries(prev).filter(([k]) => k !== key)))
    } catch (e) {
      setDetailErrors(prev => ({ ...prev, [key]: e instanceof Error ? e.message : String(e) }))
    } finally { inflight.current.delete(key) }
  }, [researchId, load])
  const shownKeys = shown.map(keyOf).join('|')
  useEffect(() => {
    const waiting = shown.filter(r => !details[keyOf(r)] && !detailErrors[keyOf(r)] && !unsettled.has(keyOf(r)) && !inflight.current.has(keyOf(r)))
    waiting.slice(0, Math.max(0, IN_FLIGHT - inflight.current.size)).forEach(row => { void fetchDetail(row) })
  }, [shownKeys, details, detailErrors, unsettled, fetchDetail])  // eslint-disable-line react-hooks/exhaustive-deps

  const openPage = (row: QueueRow, found: QueueDetail, opener: HTMLElement) => {
    const choice = rowPage(row, found)
    if (!choice) return
    sheetOpener.current = opener
    setSheet({ passageId: choice.passageId, assetId: choice.passageId ? null : found.asset_id, page: choice.page, view: 'pdf',
      anchor: choice.anchor, expect: choice.kind !== 'cue' && choice.kind !== 'page', labels: labelsFor(choice.kind, choice.page, choice.rendition) })
  }
  const openPart = (part: QueuePart, opener: HTMLElement) => {
    sheetOpener.current = opener
    if (part.quote_verified && part.page !== null && part.passage_id) {
      setSheet({ passageId: part.passage_id, assetId: null, page: part.page, view: 'text', anchor: part.anchor_text, expect: true, labels: labelsFor('quote', part.page, part.rendition) })
    } else if (part.closest?.passage_id) {
      setSheet({ passageId: part.closest.passage_id, assetId: null, page: part.closest.page, view: 'text', anchor: null, expect: true, labels: labelsFor('closest', part.closest.page, part.closest.rendition) })
    } else if (part.passage_id) {
      const text = t('The model’s quote was not found in the text of the page it named, so nothing is marked. Check the page in the PDF.')
      setSheet({ passageId: part.passage_id, assetId: null, page: 1, view: 'text', anchor: null, expect: true, labels: { marked: text, unmarked: text, mark: t(MARK_NAME) } })
    }
  }
  const openSource = (sourceVersionId: string, opener: HTMLElement) => { sheetOpener.current = opener; setSheet({ source: sourceVersionId }) }

  async function reloadAll() {
    const [next] = await Promise.all([load(), onChanged()])
    return next
  }
  // After an answer, focus goes to the title of the card that took the answered one's place, else to the panel heading.
  const focusCard = (workId: string | null) => requestAnimationFrame(() => {
    const target = (workId && document.querySelector<HTMLElement>(`#queue-row-${CSS.escape(workId)} .qcard-title`)) || document.getElementById('split-panel-title')
    target?.focus({ preventScroll: false })
  })

  async function answer(row: QueueRow, choice: QueueAnswer) {
    const rowView = details[keyOf(row)]
    // An answer is sent only on a detail whose row and token are the ones the list shows.
    if (rowView?.row?.row_token !== row.row_token) return
    const token = row.row_token
    const written = notes[row.work_id]?.text ?? ''
    const index = ordered.findIndex(r => r.work_id === row.work_id)
    const after = ordered[index + 1] ?? ordered[index - 1] ?? null
    setBusy(true)
    setActionError(null)
    try {
      const result = await api.answerQueueRow(researchId, row.source_version_id, choice, token, written.trim() || null)
      const next = await reloadAll()
      setConflict(null)
      setNotes(prev => { const { [row.work_id]: _, ...rest } = prev; return rest })
      const target = next?.rows.find(r => r.work_id === after?.work_id) ?? null
      toast('success', t(toastText[choice]), { label: t('Undo'), run: () => { void undo(row.source_version_id, result.undo_token) } })
      focusCard(target?.work_id ?? null)
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // The row moved between showing and answering: the queue, its detail and the research view are read again.
        const next = await reloadAll()
        const still = next?.rows.some(r => r.work_id === row.work_id) ?? false
        // The note stays with its work: under its card while the card is there, in the notice when it left.
        setConflict({ work: row.work_id, gone: !still, title: row.title, note: written.trim() })
        if (!still) setNotes(prev => { const { [row.work_id]: _, ...rest } = prev; return rest })
      } else setActionError({ work: row.work_id, text: e instanceof Error ? e.message : String(e) })
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

  if (error && !queue) return <Notice tone="error">{t('Could not load the queue: {error}', { error })}</Notice>
  if (!queue) return <p className="empty-inline" role="status">{t('Loading the queue…')}</p>

  const counts = queue.counts
  // The inclusion criterion the open rows are current under (P39's criterion line), from the frozen protocol record the
  // queue route reads. A look-again row was decided under an earlier criterion, so it does not show this one.
  const criterion = queue.criterion ?? null
  const decidedCount = Object.values(counts.decided).reduce((sum, n) => sum + n, 0)
  const kindCount = (kind: QueueKind) => counts.by_kind[kind] ?? 0
  const reasons = Object.keys(counts.by_reason)
  const emptyFacts = [decidedCount > 0 && t(decidedCount === 1 ? 'You decided {n} work' : 'You decided {n} works', { n: decidedCount }),
    counts.user_selected > 0 && t(counts.user_selected === 1 ? 'you chose {n} work from the sources' : 'you chose {n} works from the sources', { n: counts.user_selected })].filter(Boolean)
  const card = (row: QueueRow) => {
    const key = keyOf(row)
    return <QueueCard key={row.work_id} row={row} criterion={criterion} rowView={details[key]} detailError={detailErrors[key] ?? ''} unsettled={unsettled.has(key)} busy={busy}
      note={notes[row.work_id] ?? { text: '', open: false }} onNote={note => setNotes(prev => ({ ...prev, [row.work_id]: note }))}
      conflict={conflict && conflict.work === row.work_id && !conflict.gone} actionError={actionError?.work === row.work_id ? actionError.text : ''}
      onReadAgain={() => { mismatches.current.delete(key); setUnsettled(prev => { const next = new Set(prev); next.delete(key); return next }); setDetails(prev => Object.fromEntries(Object.entries(prev).filter(([k]) => k !== key))); setDetailErrors(prev => { const { [key]: _, ...rest } = prev; return rest }) }}
      onAnswer={choice => void answer(row, choice)} onOpenPage={opener => { const d = details[key]?.detail; if (d) openPage(row, d, opener) }}
      onOpenPart={openPart} onOpenSource={opener => openSource(row.source_version_id, opener)}
      onOpenCue={(passageId, page, rendition, opener) => { sheetOpener.current = opener; setSheet({ passageId, assetId: null, page, view: 'text', anchor: null, expect: false, labels: labelsFor('cue', page, rendition) }) }} />
  }

  return <div className="mock-pad queue-panel">
    {rows.length > 0 && <p>{t('These came up while DEIXIS worked. Your answer is recorded as your decision and can be taken back; nothing here was decided for you.')}</p>}
    <OverridesLine overrides={view.counts.overrides} />
    {error && <Notice tone="error">{t('Could not load the queue: {error}', { error })}</Notice>}
    {conflict && conflict.gone && <Notice tone="attention">{t('The row you answered left the queue after it was shown. Your answer was not saved.')}
      {conflict.note && <p className="queue-kept-note">{t('Your note for “{title}” is kept here:', { title: conflict.title })} <q>{conflict.note}</q></p>}</Notice>}
    {!rows.length ? <div className="empty queue-empty"><div>
      <CircleCheck size={22} aria-hidden />
      <h2>{t('Nothing is waiting for you')}</h2>
      <p>{t('No row waits for your decision. Your answers are kept with this research.')}</p>
      {emptyFacts.length > 0 && <p>{`${emptyFacts.join('; ')}.`}</p>}
    </div></div> : <>
      {(KIND_ORDER.filter(kind => kindCount(kind) > 0).length > 1 || reasons.length > 1 || kindFilter !== 'all' || reasonFilter !== 'all') && <div className="queue-filters">
        <div className="queue-chips" role="group" aria-label={t('Show rows')}>
          <button type="button" aria-pressed={kindFilter === 'all'} onClick={() => setKindFilter('all')}>{t('All')}<span>{open.length}</span></button>
          {KIND_ORDER.filter(kind => kindCount(kind) > 0).map(kind => <button key={kind} type="button" aria-pressed={kindFilter === kind} onClick={() => setKindFilter(kind)}>{t(queueKindLabels[kind])}<span>{kindCount(kind)}</span></button>)}
        </div>
        {(reasons.length > 1 || reasonFilter !== 'all') && <Select value={reasonFilter} onValueChange={value => { if (value) setReasonFilter(String(value)) }}>
          <SelectTrigger className="queue-reason-filter" aria-label={t('Filter rows by why they are here')}><SelectValue>{(value: string) => value === 'all' ? t('Every reason') : queueReasonText(value)}</SelectValue></SelectTrigger>
          <SelectContent className="intake-select-content" align="start" alignItemWithTrigger={false}>
            <SelectItem value="all">{t('Every reason')}</SelectItem>
            {reasons.map(code => <SelectItem key={code} value={code}><span className="source-filter-option"><span>{queueReasonText(code)}</span><small>{counts.by_reason[code]}</small></span></SelectItem>)}
          </SelectContent>
        </Select>}
      </div>}
      {shownOpenCards.length > 0 ? <div className="queue-cards" role="list" aria-label={t('Rows awaiting your decision')}>{shownOpenCards.map(card)}</div>
        : !shownLookAgain.length && <p className="empty-inline queue-filter-empty">{t('No row matches this filter.')}</p>}
      {shownLookAgain.length > 0 && <section className="queue-cards" aria-labelledby="queue-look-again">
        <h3 id="queue-look-again" className="queue-group-head">{t('Decided under an earlier question; look again')}</h3>
        <div role="list" className="queue-cards">{shownLookAgain.map(card)}</div>
      </section>}
      {ordered.length > shown.length && <button type="button" className="ghost queue-more" onClick={() => setLimit(n => n + PAGE)}>{t('Show {n} more', { n: Math.min(PAGE, ordered.length - shown.length) })}</button>}
      <p className="foot-note">{t('Semantic support not checked. Your answer is recorded as your decision; DEIXIS does not say whether it is right.')}</p>
    </>}

    {queue.decided.length > 0 && <Decided entries={queue.decided} busy={busy} onUndo={entry => { if (entry.undo_token) void undo(entry.source_version_id, entry.undo_token) }} onOpen={(svid, opener) => openSource(svid, opener)} />}

    {sheet && <PassageSheet researchId={researchId} dark={dark} sources={view.sources}
      passageId={'source' in sheet ? null : sheet.passageId} assetId={'source' in sheet ? null : sheet.assetId}
      sourceVersionId={'source' in sheet ? sheet.source : null} initialView={'source' in sheet ? 'text' : sheet.view}
      initialPage={'source' in sheet ? 1 : sheet.page} highlightTexts={'source' in sheet || !sheet.anchor ? [] : [sheet.anchor]}
      expectHighlight={'source' in sheet ? false : sheet.expect} citationLabels={'source' in sheet ? undefined : sheet.labels}
      onClose={() => { setSheet(null); const opener = sheetOpener.current; requestAnimationFrame(() => { if (opener?.isConnected) opener.focus() }) }} />}
  </div>
}

function QueueCard({ row, criterion, rowView, detailError, unsettled, busy, note, onNote, conflict, actionError, onReadAgain, onAnswer, onOpenPage, onOpenPart, onOpenSource, onOpenCue }: {
  row: QueueRow; criterion: string | null; rowView: QueueRowView | undefined; detailError: string; unsettled: boolean; busy: boolean
  note: Note; onNote: (note: Note) => void; conflict: boolean | null; actionError: string; onReadAgain: () => void
  onAnswer: (choice: QueueAnswer) => void; onOpenPage: (opener: HTMLElement) => void; onOpenPart: (part: QueuePart, opener: HTMLElement) => void
  onOpenSource: (opener: HTMLElement) => void; onOpenCue: (passageId: string, page: number, rendition: boolean | undefined, opener: HTMLElement) => void
}) {
  const detail = rowView?.detail
  const answerable = rowView?.row?.row_token === row.row_token
  const choice = detail ? rowPage(row, detail) : null
  const part = row.question?.part
  const [head, about] = CARD_HEADS[row.kind]
  const earlier = row.kind === 'look_again' ? queueAnswerOfCode[row.reason_code] : undefined
  // One question for every paper; the part, the protocol title or the versions the reading stopped at come second.
  const question = row.kind === 'confirm_pdf' ? t('Is this PDF the work named here?') : t('Is this paper a source for the question?')
  const context = row.question
    ? t('The reading could not settle the part “{part}”.', { part: row.question.part })
    : row.kind === 'confirm_results' ? t('The title names a study protocol. Does this paper report results for every part, rather than only planning to measure them?')
    : row.kind === 'choose_version' ? t('The versions of this work were read to opposite decisions. Which one holds?')
    : row.kind === 'look_again' ? t('You decided this work under an earlier question. Does your decision still hold?')
    : null
  const unverified = detail ? detail.runs.flatMap(run => run.parts.filter(p => p.part === part && p.label === 'present' && p.quote_verified === false && p.quote)
    .map(p => ({ run: run.run_no, part: p }))) : []
  const answers = row.kind === 'confirm_pdf' ? ['pdf_confirmed' as const, ...ANSWERS] : ANSWERS
  const words = row.kind === 'confirm_pdf' ? queueAnswerLabels : answerWords
  const titleId = `queue-title-${row.work_id}`
  return <article id={`queue-row-${row.work_id}`} className="qcard" role="listitem" aria-labelledby={titleId}>
    <header><b>{t(head)}</b><span>· {t(about)}{earlier ? ` · ${t(queueAnsweredText[earlier])}` : ''}</span></header>
    <div className="qb">
      <h4 id={titleId}><button type="button" className="qcard-title" onClick={e => onOpenSource(e.currentTarget)}>{row.title}</button></h4>
      <div className="au">
        <span className={`ref-pill is-${versionTones[row.version_label ?? ''] ?? 'unstated'}`}>{versionText(row.version_label)}</span>
        {[row.year, row.place !== null && t('No. {n} in the order', { n: row.place }), row.arm === 'chain' && t('from the citation chain'), kindText(row)].filter(Boolean).map((fact, i) => <span key={i}>{fact}</span>)}
        {row.doi && <a className="source-link-chip" href={`https://doi.org/${row.doi}`} target="_blank" rel="noreferrer"><ConnectionIcon id="doi" /><span>{row.doi}</span><ExternalLink size={12} aria-hidden /></a>}
      </div>
      {context && <div className="queue-focus">
        <span className="queue-focus-text">{context}</span>
        {row.question?.definition && <span className="queue-focus-definition">{row.question.definition}</span>}
        {row.question?.disputed && <span className="queue-focus-definition">{typeof row.question.page === 'number'
          ? t('Both reads saw this passage and disagreed (p. {page}).', { page: row.question.page })
          : t('Both reads saw this passage and disagreed.')}</span>}
      </div>}
      {conflict && <Notice tone="attention">{t('This row changed after it was shown; its current state is loaded. Your answer was not saved.')}</Notice>}
      {rowView && !answerable && !detailError && (unsettled
        ? <Notice tone="attention">{t('This row kept changing while it was read, so it cannot be answered yet.')}{' '}
          <button type="button" className="queue-link" onClick={onReadAgain}>{t('Read it again')}</button></Notice>
        : <p className="queue-muted" role="status">{t('Reading this row again…')}</p>)}
      {detailError ? <Notice tone="error">{t('Could not load this row: {error}', { error: detailError })}{' '}
          <button type="button" className="queue-link" onClick={onReadAgain}>{t('Read it again')}</button></Notice>
        : !rowView ? <p className="queue-muted" role="status">{t('Loading this row…')}</p>
        : !detail ? <Notice tone="attention">{t('This row changed while it was loading; the queue is being read again.')}</Notice>
        : <>
          {detail.identity && <section className="queue-identity" aria-label={t('The PDF and the work')}>
            <div><h5>{t('First page of the PDF')}</h5><div className="queue-first-page">{detail.identity.first_page ?? t('No text was extracted from the first page.')}</div></div>
            <div><h5>{t('The work this PDF was fetched for')}</h5><p className="queue-serif">{detail.identity.work_title}</p>
              {detail.identity.work_doi && <a className="source-link-chip" href={`https://doi.org/${detail.identity.work_doi}`} target="_blank" rel="noreferrer"><ConnectionIcon id="doi" /><span>{detail.identity.work_doi}</span><ExternalLink size={12} aria-hidden /></a>}</div>
          </section>}
          {detail.versions ? <section className="queue-runs is-versions" aria-label={t('What each version was read as')}>
            {detail.versions.map(version => <div key={version.source_version_id} className="queue-run">
              <b><span className={`ref-pill is-${versionTones[version.version_label ?? ''] ?? 'unstated'}`}>{versionText(version.version_label)}</span> {t(version.decision.outcome === 'include' ? 'read as included' : version.decision.outcome === 'criterion_not_met' ? 'read as not meeting the criterion' : 'read as unresolved')}</b>
              {version.runs.map(run => <RunParts key={run.run_no} run={run} part={part} onOpenPart={onOpenPart} />)}
            </div>)}
          </section> : detail.runs.length > 0 && <section className="reads queue-runs" aria-label={t('What the two runs said')}>
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
            <h5>{t('Sentences with this part’s phrases')}</h5>
            {detail.cues.sentences.length ? <>
              <ul>{detail.cues.sentences.map((cue, i) => <li key={i}><p className="queue-serif">{cue.sentence}</p>
                {cue.passage_id && <button type="button" className="queue-page-link" onClick={e => onOpenCue(cue.passage_id!, cue.page, cue.rendition, e.currentTarget)}>{pageLocator(cue.page, cue.rendition)}<ChevronRight size={13} aria-hidden /></button>}</li>)}</ul>
              {detail.cues.total > detail.cues.sentences.length && <p className="queue-muted">{t('{shown} of {total} sentences shown', { shown: detail.cues.sentences.length, total: detail.cues.total })}</p>}
            </> : <p className="queue-muted">{t('This part’s phrases do not occur in the text.')}</p>}
          </section>}
        </>}
      <div className="queue-decide">
      <div className="lbl queue-question">
        <span className="queue-question-text">{question}</span>
        {criterion && row.kind !== 'look_again' && <span className="queue-criterion">{t('Criterion: {text}', { text: criterion })}</span>}
        <span className="queue-why">{t('Why it is here:')} {queueReasonText(row.reason_code)} <code>{row.reason_code}</code></span>
      </div>
      {choice && <button type="button" className="ghost queue-open-page" onClick={e => onOpenPage(e.currentTarget)}><Eye size={14} aria-hidden />{t('Open page {page} in the PDF', { page: choice.page })}</button>}
      {actionError && <Notice tone="error">{actionError}</Notice>}
      <div className="qopts" role="group" aria-label={question}>
        {answers.map(choice => {
          const Icon = ANSWER_ICONS[choice]
          const label = t(words[choice])
          return <button key={choice} type="button" aria-label={label} disabled={busy || !answerable} onClick={() => onAnswer(choice)}>
            <Icon size={16} aria-hidden /><span>{label}{ANSWER_NOTES[choice] && <small>{t(ANSWER_NOTES[choice]!)}</small>}</span>
          </button>
        })}
      </div>
      {note.open || note.text ? <label className="queue-note"><span>{t('Note')}<small>{t('{n} of 1000 characters', { n: note.text.length })}</small></span>
        <textarea value={note.text} maxLength={1000} rows={2} onChange={e => onNote({ text: e.target.value, open: true })} /></label>
        : <button type="button" className="queue-note-toggle" onClick={() => onNote({ text: '', open: true })}><NotebookPen size={14} aria-hidden />{t('Add a note')}</button>}
      </div>
    </div>
  </article>
}

function RunParts({ run, part, onOpenPart }: { run: QueueRun; part: string | undefined; onOpenPart: (part: QueuePart, opener: HTMLElement) => void }) {
  return <>
    <h5 className="queue-run-head">{t('Run {n}', { n: run.run_no })}<small>{run.shown_pages.length ? t('pages shown: {pages}', { pages: run.shown_pages.join(', ') }) : t('no pages shown')}</small></h5>
    {run.parts.map(p => <div key={p.part} className={`queue-part${p.part === part ? ' is-question' : ''}`}>
      <p className="queue-part-head"><span>{p.part}</span><span className={`ref-pill queue-part-label is-${p.label}`}>{partLabelText(p.label)}</span>{p.part === part && <small className="queue-part-asked">{t('this row’s question')}</small>}</p>
      {p.quote && <blockquote className="queue-quote">{p.quote}</blockquote>}
      {p.label === 'present' && <p className="queue-part-note">{p.quote_verified ? t('Found on the page.') : t('Not found in the text.')}
        {(p.passage_id || p.closest?.passage_id) && <button type="button" className="queue-page-link" onClick={e => onOpenPart(p, e.currentTarget)}>{p.quote_verified && p.page !== null ? pageLocator(p.page, p.rendition) : t('Open the page')}<ChevronRight size={13} aria-hidden /></button>}</p>}
      {p.rationale && <p className="queue-rationale">{p.rationale}</p>}
    </div>)}
  </>
}

function Decided({ entries, busy, onUndo, onOpen }: { entries: QueueDecided[]; busy: boolean; onUndo: (entry: QueueDecided) => void; onOpen: (sourceVersionId: string, opener: HTMLElement) => void }) {
  return <details className="queue-decided">
    <summary><ChevronRight size={14} aria-hidden className="queue-decided-chevron" />{t('Your decisions ({n})', { n: entries.length })}</summary>
    <ul>{entries.map(entry => <li key={entry.work_id}>
      <div>
        <button type="button" className="queue-decided-title" onClick={e => onOpen(entry.source_version_id, e.currentTarget)}>{entry.title}</button>
        <p className="queue-muted">{[queueStateOf(entry.answer), t(queueAnsweredText[entry.answer]), dateText(entry.created_at)].join(' · ')}</p>
        {entry.note && <p className="queue-decided-note">{entry.note}</p>}
      </div>
      {entry.undo_token
        ? <Button variant="ghost" size="sm" disabled={busy} onClick={() => onUndo(entry)} aria-label={t('Undo your decision on {title}', { title: entry.title })}><RotateCcw size={14} aria-hidden />{t('Undo')}</Button>
        : <p className="queue-muted">{t('The reading has begun, so this can no longer be taken back.')}</p>}
    </li>)}</ul>
  </details>
}
