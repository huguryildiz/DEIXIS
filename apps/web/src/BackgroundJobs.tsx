import { useEffect, useState } from 'react'
import { Check, Circle, CirclePause, Clock, Pause, Play, TriangleAlert } from 'lucide-react'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { api, type EquationReader, type ResearchSummary, type ResearchView, type Run, type RunStatus, type Source } from './api'
import { t } from './i18n'
import { useToast } from './Toast'

// PDF work that keeps going while the user is on another page (PDF collection, OCR, the equation reader over the library): a card at the foot of the sidebar
// and a 420px sheet with one line per job. The research list names each research's latest run; the views give the progress.

const LIVE = new Set<RunStatus>(['queued', 'running', 'pause_requested', 'paused'])
const JOB_KINDS = new Set(['pdf_collection', 'pdf_ocr', 'fulltext_fetch', 'fulltext_adjudication'])

type Job = { key: string; research: ResearchSummary | null; run: Run | null; label: string; done: number; total: number; extra: number; unit: string; sub: string; paused: boolean }
// How a job that left the running list ended: its own run's stored status, looked up by the run id, or `unknown` when
// that read failed. The equation reader ends when a read of it shows nothing reading or waiting.
type Outcome = RunStatus | 'unknown'
type Ended = { key: string; label: string; sub: string; detail: string; outcome: Outcome }
const TERMINAL = new Set<RunStatus>(['completed', 'failed', 'cancelled'])

const reading = (view: ResearchView, record: Source) => (record.answer_reads_version_id ? view.sources.find(s => s.source_version_id === record.answer_reads_version_id) ?? record : record)

function jobOf(research: ResearchSummary, view: ResearchView): Job | null {
  const run = view.runs.find(r => r.kind === research.last_run_kind)
  if (!run || !LIVE.has(run.status)) return null
  const paused = run.status === 'paused'
  const steps = run.steps ?? []
  if (run.kind === 'pdf_ocr') {
    // Pages come from the run's own steps: the page list found first, then one step per page read.
    const found = steps.find(s => s.kind === 'ocr_pages')?.output?.image_pages
    return { key: run.id, research, run, label: t(paused ? 'OCR reading paused' : 'Reading with OCR'), done: steps.filter(s => s.kind === 'ocr_page' && s.status === 'succeeded').length, total: found ? found.length : 0, extra: 0, unit: t('pages'), sub: research.title, paused }
  }
  // PDF collection: sources whose PDF is in hand, and sources already checked without an open copy.
  const records = view.sources.filter(s => s.version_role === 'record' && s.selection.state === 'included')
  let inHand = 0, none = 0
  for (const record of records) {
    if (reading(view, record).has_pdf_text) { inHand++; continue }
    const ids = new Set(view.sources.filter(s => s.work_id === record.work_id).map(s => s.source_version_id))
    const own = steps.filter(s => ids.has(s.operation_key.split(':')[1] ?? ''))
    if (own.length && !own.some(s => s.status === 'running' || s.status === 'queued')) none++
  }
  return { key: run.id, research, run, label: t(paused ? 'PDF collection paused' : 'Collecting PDFs'), done: inHand, total: records.length, extra: none, unit: t('sources'), sub: research.title, paused }
}

const pct = (n: number, total: number) => `${total ? (100 * n) / total : 0}%`
const progress = (job: { done: number; total: number; unit: string }) => job.total ? t('{done} of {total} {unit}', { done: job.done, total: job.total, unit: job.unit }) : '…'

export function BackgroundJobs({ researches, dark, onOpenResearch }: {
  researches: ResearchSummary[]; dark: boolean; onOpenResearch: (id: string) => void
}) {
  const [views, setViews] = useState<Record<string, ResearchView>>({})
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [seen, setSeen] = useState<Record<string, Job>>({})
  const toast = useToast()
  const candidates = researches.filter(r => r.last_run_kind && JOB_KINDS.has(r.last_run_kind) && r.last_run_status && LIVE.has(r.last_run_status))

  // The research list is refreshed every few seconds; each refresh reloads the views of the researches with a PDF run.
  const load = () => Promise.all(candidates.map(r => api.research(r.id).then(view => [r.id, view] as const, () => null)))
    .then(entries => setViews(Object.fromEntries(entries.filter(e => e !== null))))
  // A failed read of the equation reader keeps the last answer and marks it stale: its job is then of unknown status, never finished.
  const [reader, setReader] = useState<EquationReader | null>(null)
  const [readerFailed, setReaderFailed] = useState(false)
  const [outcomes, setOutcomes] = useState<Record<string, Outcome>>({})
  useEffect(() => {
    if (candidates.length || Object.keys(views).length) void load()
    api.equationReader().then(value => { setReader(value); setReaderFailed(false) }, () => setReaderFailed(true))
  }, [researches]) // eslint-disable-line react-hooks/exhaustive-deps

  const runJobs = candidates.flatMap(r => { const view = views[r.id]; const job = view && jobOf(r, view); return job ? [job] : [] })
  // The equation reader works through the library's stored PDFs (D52) while it has one in hand or any waiting.
  const readerPending = reader ? (reader.pdfs.pending ?? 0) + (reader.pdfs.reading ?? 0) : 0
  const readerOn = !readerFailed && !!reader?.installed && (!!reader.reading || readerPending > 0)
  const readerDone = reader ? (reader.pdfs.read ?? 0) + (reader.pdfs.no_math ?? 0) + (reader.pdfs.failed ?? 0) : 0
  const readerJob: Job | null = readerOn && reader ? { key: 'equation-reader', research: null, run: null, label: t('Reading equations'), done: readerDone, total: readerDone + readerPending, extra: 0, unit: t('PDFs'), sub: reader.reading?.title ?? t('PDFs in the library'), paused: !reader.reading } : null
  const jobs = readerJob ? [...runJobs, readerJob] : runJobs

  // A job that leaves the running list is looked up by its own run id; only that run's stored terminal status says how it
  // ended. The last progress seen is kept for this session only.
  if (jobs.some(job => { const old = seen[job.key]; return !old || old.done !== job.done || old.total !== job.total })) setSeen(old => ({ ...old, ...Object.fromEntries(jobs.map(job => [job.key, job])) }))
  const liveKeys = new Set(jobs.map(job => job.key))
  const left = Object.values(seen).filter(job => !liveKeys.has(job.key))
  const unresolved = left.filter(job => job.run && job.research && (outcomes[job.key] ?? 'unknown') === 'unknown').map(job => `${job.research!.id}/${job.key}`).join(' ')
  useEffect(() => {
    if (!unresolved) return
    for (const pair of unresolved.split(' ')) {
      const [researchId, runId] = pair.split('/')
      api.research(researchId).then(view => {
        const status = view.runs.find(run => run.id === runId)?.status
        if (!status || TERMINAL.has(status)) setOutcomes(old => ({ ...old, [runId]: status ?? 'unknown' }))
      }, () => setOutcomes(old => ({ ...old, [runId]: 'unknown' })))
    }
  }, [unresolved, researches])
  const labelOf = (job: Job) => job.run?.kind === 'pdf_ocr' ? t('Reading with OCR') : job.run ? t('Collecting PDFs') : t('Reading equations')
  const ended: Ended[] = left.flatMap(job => {
    if (job.run) {
      const outcome = outcomes[job.key]
      return outcome ? [{ key: job.key, label: labelOf(job), sub: job.sub, detail: `${job.total} ${job.unit}`, outcome }] : []
    }
    if (readerFailed || !reader) return [{ key: job.key, label: labelOf(job), sub: job.sub, detail: '', outcome: 'unknown' as const }]
    if (readerPending > 0 || reader.reading) return []
    return [{ key: job.key, label: labelOf(job), sub: job.sub, outcome: 'completed' as const,
      detail: t('{read} read · {none} without equations · {failed} failed', { read: reader.pdfs.read ?? 0, none: reader.pdfs.no_math ?? 0, failed: reader.pdfs.failed ?? 0 }) }]
  })
  const finished = ended.filter(item => item.outcome === 'completed')
  const unconfirmed = ended.filter(item => item.outcome !== 'completed')
  const outcomeText = (outcome: Outcome) => outcome === 'failed' ? t('Failed') : outcome === 'cancelled' ? t('Cancelled') : t('Status unknown')

  if (!jobs.length) return null

  const act = async (action: () => Promise<unknown>) => {
    setBusy(true)
    try { await action() } catch (error) { toast('error', (error as Error).message) } finally { setBusy(false); void load() }
  }
  const title = t('In the background · {n}', { n: jobs.length })

  return <>
    <button type="button" className="bgcard" onClick={() => setOpen(true)}>
      <b><span className="spin" aria-hidden="true" />{title}</b>
      <small>{jobs.map(job => `${job.label} ${job.done}/${job.total}`).join(' · ')}</small>
    </button>
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetContent className={`detail-sheet jobs-sheet ${dark ? 'dark' : ''}`}>
        <SheetHeader><SheetTitle><Clock size={16} aria-hidden="true" /><span>{title}</span></SheetTitle></SheetHeader>
        <div className="jobs-body">
          {jobs.map(job => <div key={job.key} className="job">
            <b>{job.paused ? <CirclePause size={14} className="jobs-paused" aria-hidden="true" /> : <span className="spin" aria-hidden="true" />}<span className="job-name">{job.label}</span>
              <span className="job-count">{progress(job)}</span>
              {job.run && (job.run.status !== 'paused'
                ? <button type="button" className="job-action" disabled={busy || job.run.status === 'pause_requested'} onClick={() => act(() => api.controlRun(job.run!.id, 'pause'))}><Pause size={13} aria-hidden="true" />{t('Pause')}</button>
                : <button type="button" className="job-action" disabled={busy} onClick={() => act(() => api.controlRun(job.run!.id, 'resume'))}><Play size={13} aria-hidden="true" />{t('Resume')}</button>)}
            </b>
            {job.research
              ? <small><button type="button" className="job-research" onClick={() => { setOpen(false); onOpenResearch(job.research!.id) }}>{job.sub}</button></small>
              : <small>{job.sub}</small>}
            <div className="job-bar" aria-hidden="true"><i className="is-done" style={{ width: pct(job.done, job.total) }} />{job.extra > 0 && <i className="is-checked" style={{ width: pct(job.extra, job.total) }} />}</div>
          </div>)}
          {finished.length > 0 && <>
            <h3>{t('Finished')}</h3>
            {finished.map(item => <div key={item.key} className="job"><b><Check size={14} aria-hidden="true" />{item.label}</b><small>{item.sub} · {item.detail}</small></div>)}
          </>}
          {unconfirmed.length > 0 && <>
            <h3>{t('Not confirmed as finished')}</h3>
            {unconfirmed.map(item => <div key={item.key} className="job">
              <b>{item.outcome === 'unknown' ? <Circle size={14} aria-hidden="true" /> : <TriangleAlert size={14} aria-hidden="true" />}{item.label}<span className="job-count">{outcomeText(item.outcome)}</span></b>
              <small>{item.detail ? `${item.sub} · ${item.detail}` : item.sub}</small>
            </div>)}
          </>}
          <p className="foot-note">{t('Keeps running while you are on another page. Text read in the background can be used in the next answer if it qualifies.')}</p>
        </div>
      </SheetContent>
    </Sheet>
  </>
}
