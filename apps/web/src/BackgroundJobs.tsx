import { useEffect, useState } from 'react'
import { ArrowRight, ChevronRight, CirclePause, Pause, Play } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { api, type EquationReader, type ResearchSummary, type ResearchView, type Run, type RunStatus, type Source } from './api'
import { PdfReadiness } from './PdfReadiness'
import { ReaderProgress } from './Connections'
import { t } from './i18n'
import { useToast } from './Toast'

// PDF work that keeps going while the user is on another page (PDF collection, OCR, the equation reader over the library): a card at the foot of the sidebar
// and a sheet with each run's detail. The research list names each research's latest run; the views give the progress.

const LIVE = new Set<RunStatus>(['queued', 'running', 'pause_requested', 'paused'])
const JOB_KINDS = new Set(['pdf_collection', 'pdf_ocr', 'fulltext_fetch'])

type Job = { research: ResearchSummary; view: ResearchView; run: Run; label: string; done: number; total: number; extra: number; unit: string }

const reading = (view: ResearchView, record: Source) => (record.answer_reads_version_id ? view.sources.find(s => s.source_version_id === record.answer_reads_version_id) ?? record : record)

function jobOf(research: ResearchSummary, view: ResearchView): Job | null {
  const run = view.runs.find(r => r.kind === research.last_run_kind)
  if (!run || !LIVE.has(run.status)) return null
  const paused = run.status === 'paused'
  const steps = run.steps ?? []
  if (run.kind === 'pdf_ocr') {
    const found = steps.find(s => s.kind === 'ocr_pages')?.output?.image_pages
    return { research, view, run, label: t(paused ? 'OCR reading paused' : 'Reading with OCR'), done: steps.filter(s => s.kind === 'ocr_page' && s.status === 'succeeded').length, total: found ? found.length : 0, extra: 0, unit: t('pages') }
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
  return { research, view, run, label: t(paused ? 'PDF collection paused' : 'Collecting PDFs'), done: inHand, total: records.length, extra: none, unit: '' }
}

const pct = (n: number, total: number) => `${total ? (100 * n) / total : 0}%`

export function BackgroundJobs({ researches, collapsed, dark, onOpenResearch }: {
  researches: ResearchSummary[]; collapsed: boolean; dark: boolean; onOpenResearch: (id: string) => void
}) {
  const [views, setViews] = useState<Record<string, ResearchView>>({})
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  const candidates = researches.filter(r => r.last_run_kind && JOB_KINDS.has(r.last_run_kind) && r.last_run_status && LIVE.has(r.last_run_status))

  // The research list is refreshed every few seconds; each refresh reloads the views of the researches with a PDF run.
  const load = () => Promise.all(candidates.map(r => api.research(r.id).then(view => [r.id, view] as const, () => null)))
    .then(entries => setViews(Object.fromEntries(entries.filter(e => e !== null))))
  const [reader, setReader] = useState<EquationReader | null>(null)
  useEffect(() => {
    if (candidates.length || Object.keys(views).length) void load()
    api.equationReader().then(setReader, () => setReader(null))
  }, [researches]) // eslint-disable-line react-hooks/exhaustive-deps

  const jobs = candidates.flatMap(r => { const view = views[r.id]; const job = view && jobOf(r, view); return job ? [job] : [] })
  // The equation reader works through the library's stored PDFs (D52) while it has one in hand or any waiting.
  const readerPending = reader ? (reader.pdfs.pending ?? 0) + (reader.pdfs.reading ?? 0) : 0
  const readerOn = !!reader?.installed && (!!reader.reading || readerPending > 0)
  const readerDone = reader ? (reader.pdfs.read ?? 0) + (reader.pdfs.no_math ?? 0) + (reader.pdfs.failed ?? 0) : 0
  const readerTotal = readerDone + readerPending
  const count = jobs.length + (readerOn ? 1 : 0)
  if (!count) return null

  const act = async (action: () => Promise<unknown>) => {
    setBusy(true)
    try { await action() } catch (error) { toast('error', (error as Error).message) } finally { setBusy(false); void load() }
  }
  const lead = jobs[0] ?? { label: t('Reading equations'), done: reader?.pdfs.read ?? 0, total: readerTotal }
  const running = (job: Job) => job.run.status !== 'paused'

  return <>
    {collapsed
      ? <button type="button" className="jobs-ring" onClick={() => setOpen(true)} aria-label={t('Background work: {n}', { n: count })} title={`${lead.label} · ${lead.done} / ${lead.total}`}>
        <svg viewBox="0 0 36 36" aria-hidden><circle cx="18" cy="18" r="15" className="jobs-ring-track" /><circle cx="18" cy="18" r="15" className="jobs-ring-fill" strokeDasharray={`${lead.total ? (94.2 * lead.done) / lead.total : 0} 94.2`} /></svg>
        <span className="jobs-ring-count">{count}</span>
      </button>
      : <button type="button" className="jobs-card" onClick={() => setOpen(true)} aria-label={t('Background work: {n}', { n: count })}>
        <span className="jobs-card-head"><span>{t('In the background · {n}', { n: count })}</span><ChevronRight size={14} aria-hidden /></span>
        {jobs.map(job => <span key={job.run.id} className="jobs-card-row">
          <span className="jobs-card-line">{running(job) ? <span className="pdf-spin" aria-hidden /> : <CirclePause size={12} className="jobs-paused" aria-hidden />}<span className="jobs-card-label">{job.label}</span><span className="jobs-card-count">{job.total ? `${job.done} / ${job.total}${job.unit ? ` ${job.unit}` : ''}` : '…'}</span></span>
          <span className="jobs-card-title">{job.research.title}</span>
          <span className="jobs-bar" aria-hidden><i className="is-done" style={{ width: pct(job.done, job.total) }} /><i className="is-checked" style={{ width: pct(job.extra, job.total) }} /></span>
        </span>)}
        {readerOn && reader && <span className="jobs-card-row">
          <span className="jobs-card-line">{reader.reading ? <span className="pdf-spin" aria-hidden /> : <CirclePause size={12} className="jobs-paused" aria-hidden />}<span className="jobs-card-label">{t('Reading equations')}</span><span className="jobs-card-count">{reader.pdfs.read ?? 0} / {readerTotal}</span></span>
          <span className="jobs-card-title">{reader.reading?.title ?? t('PDFs in the library')}</span>
          <span className="jobs-bar" aria-hidden><i className="is-done" style={{ width: pct(readerDone, readerTotal) }} /></span>
        </span>}
      </button>}
    <Sheet open={open && count > 0} onOpenChange={setOpen}>
      <SheetContent className={`detail-sheet jobs-sheet ${dark ? 'dark' : ''}`}>
        <SheetHeader><SheetTitle>{t('Background work')}</SheetTitle><SheetDescription>{t('Keeps running while you are on another page.')}</SheetDescription></SheetHeader>
        <div className="sheet-body jobs-sheet-body">
          {jobs.map(job => <section key={job.run.id} className="jobs-item">
            <div className="jobs-item-head">
              <button type="button" className="jobs-item-research" onClick={() => { setOpen(false); onOpenResearch(job.research.id) }}>{job.research.title}<ArrowRight size={13} aria-hidden /></button>
              {job.run.kind === 'pdf_ocr' && (running(job)
                ? <Button variant="outline" size="sm" disabled={busy || job.run.status === 'pause_requested'} onClick={() => act(() => api.controlRun(job.run.id, 'pause'))}><Pause size={13} />{t('Pause')}</Button>
                : <Button variant="outline" size="sm" disabled={busy} onClick={() => act(() => api.controlRun(job.run.id, 'resume'))}><Play size={13} />{t('Resume')}</Button>)}
            </div>
            {job.run.kind === 'pdf_collection'
              ? <PdfReadiness researchId={job.research.id} view={job.view} busy={busy} hasAcademic={false} act={act} onSearchAgain={() => {}} onAnswer={() => {}} onUpload={() => {}} ocrTool={null} onReadWithOcr={() => {}} />
              : <div className="jobs-ocr">
                <h2>{job.label}</h2>
                <span className="jobs-bar" aria-hidden><i className="is-done" style={{ width: pct(job.done, job.total) }} /></span>
                <p>{job.total ? t('{done} of {total} pages read', { done: job.done, total: job.total }) : t('Finding the pages without text…')}</p>
              </div>}
          </section>)}
          {readerOn && reader && <section className="jobs-item">
            <h2 className="jobs-item-heading">{t('Equation reader (Marker)')}</h2>
            <ReaderProgress reader={reader} />
          </section>}
        </div>
      </SheetContent>
    </Sheet>
  </>
}
