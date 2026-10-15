import { useEffect, useState, type ReactNode } from 'react'
import { ArrowRight, Download, FileClock, Pause, Play, ScanText, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api, type OcrTool, type ResearchView, type Source, type ZoteroSource } from './api'
import { ConnectionIcon } from './connectionIcons'
import { fetchReasonText, pdfFailureText } from './labels'
import { OCR_LABEL, ocrOffer } from './ocr'
import { OcrNote } from './OcrNote'
import { t } from './i18n'
import { useToast } from './Toast'
import { includedReading } from './includedReading'

// Between screening and the answer (D49), inside the "Get more full text" panel (UI parity S14, P40): a run that
// collects the open PDFs of the included works, its progress while it runs (or is paused), and the included works that
// still have no PDF, each with its own upload, OCR and the person's Zotero library. The panel around it holds the depth
// boxes, the waiting list, the drop zone and the answer button.

const ACTIVE = new Set(['queued', 'running', 'pause_requested'])

const durationText = (seconds: number) => (seconds < 60 ? t('{s} s', { s: seconds }) : t('{m} min {s} s', { m: Math.floor(seconds / 60), s: seconds % 60 }))
const plural = (n: number, one: string, many: string, vars: Record<string, string | number> = {}) => t(n === 1 ? one : many, { n, ...vars })

export function PdfReadiness({ researchId, view, busy, act, onUpload, ocrTool, onReadWithOcr }: {
  researchId: string; view: ResearchView; busy: boolean
  act: (action: () => Promise<unknown>, success?: string) => Promise<void>
  onUpload: (source: Source) => void
  ocrTool: OcrTool | null; onReadWithOcr: (source: Source, assetId: string) => void
}) {
  const { records, reading, full, missing, unread } = includedReading(view)
  const versionsOf = (record: Source) => view.sources.filter(s => s.work_id === record.work_id && s.source_version_id !== record.source_version_id)
  const pagesOf = (record: Source) => reading(record).access.assets[0]?.page_count ?? 0
  // A PDF with pages without text can be read with OCR (D51); its row names what OCR would read and offers the action.
  const ocrOf = (record: Source) => {
    const asset = reading(record).access.assets[0]
    const offer = asset && ocrOffer(asset, ocrTool, view.runs)
    return asset && offer ? { asset, offer, source: reading(record) } : null
  }
  const ocrAction = (record: Source) => {
    const ocr = ocrOf(record)
    return ocr && ocr.offer.kind !== 'reading' && <Button variant="outline" size="sm" className="ghost" disabled={busy || ocr.offer.kind === 'off' || ocr.offer.blocked} title={ocr.offer.kind === 'off' ? ocr.offer.reason : ocr.offer.blocked ? t('Available when the current run ends') : undefined} onClick={() => onReadWithOcr(ocr.source, ocr.asset.id)}><ScanText size={13} />{t('Read with OCR')}</Button>
  }
  const ocrNote = (record: Source) => { const ocr = ocrOf(record); return ocr && <OcrNote offer={ocr.offer} /> }

  // The latest collection run counts only when no search came after it.
  const collection = view.runs.find(r => r.kind === 'pdf_collection')
  const discovery = view.runs.find(r => r.kind === 'discovery')
  const current = collection && (!discovery || collection.created_at > discovery.created_at) ? collection : undefined
  const collecting = current && (ACTIVE.has(current.status) || current.status === 'paused')

  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!collecting) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [collecting])
  // Rows the user added a PDF to from this panel stay listed, marked as uploaded.
  const [touched, setTouched] = useState<Set<string>>(new Set())
  const touch = (ids: string[]) => setTouched(prev => new Set([...prev, ...ids]))
  const [zoteroSource, setZoteroSource] = useState<ZoteroSource>('local')
  const toast = useToast()

  const total = records.length
  const collect = () => act(() => api.startRun(researchId, 'pdf_collection', crypto.randomUUID()))
  const control = (action: 'pause' | 'resume') => current && act(() => api.controlRun(current.id, action))
  const hint = <span className="foot-note">{t('Tries each source’s open links, then looks once for another open copy. Nothing is downloaded from paywalled sites.')}</span>

  if (!total) return null

  // ---- while collecting (or paused) ------------------------------------------------------
  if (current && collecting) {
    const steps = current.steps ?? []
    const stepsOf = (record: Source) => {
      const ids = new Set([record.source_version_id, ...versionsOf(record).map(v => v.source_version_id)])
      return steps.filter(s => ids.has(s.operation_key.split(':')[1] ?? ''))
    }
    const rowState = (record: Source): 'done' | 'unread' | 'checking' | 'none' | 'queued' => {
      const own = stepsOf(record)
      if (full(record)) return 'done'
      // A running step for another version of the work shows first; otherwise the person's unread PDF is the row's state.
      if (own.some(s => s.status === 'running')) return 'checking'
      if (record.answer_reads_nothing) return 'unread'
      if (own.length || !canTry(record, versionsOf(record))) return 'none'
      return 'queued'
    }
    const states = records.map(r => [r, rowState(r)] as const)
    const count = (state: string) => states.filter(([, s]) => s === state).length
    const seconds = Math.max(0, Math.round(((ACTIVE.has(current.status) ? now : Date.parse(current.updated_at)) - Date.parse(current.created_at)) / 1000))
    const doneSeconds = (record: Source) => {
      const ok = stepsOf(record).find(s => s.status === 'succeeded')
      return ok?.started_at && ok.finished_at ? Math.round((Date.parse(ok.finished_at) - Date.parse(ok.started_at)) / 1000) : null
    }
    return <section className="plist pdf-ready" aria-labelledby="pdf-ready-title">
      <h4><span id="pdf-ready-title">{t(current.status === 'paused' ? 'PDF collection paused' : 'Collecting open-access PDFs')}</span>
        <span className="tnum">{t('{inHand} in hand · {none} checked, none open · {left} still to check', { inHand: records.filter(full).length, none: count('none'), left: count('queued') + count('checking') })}{count('unread') ? ` · ${t('{n} your PDF, not read yet', { n: count('unread') })}` : ''}</span></h4>
      <ul className="pdf-ready-rows">
        {states.map(([record, state]) => <li key={record.source_version_id} className="prow">
          <RowHead record={record} facts={[state === 'checking' ? t(stepsOf(record).some(s => s.kind === 'pdf_other_copy' && s.status === 'running') ? 'looking for another open copy' : 'downloading') : state === 'queued' ? t('waiting') : state === 'done' && pagesOf(record) ? plural(pagesOf(record), '{n} page', '{n} pages') : state === 'none' ? { text: missingReason(record, versionsOf(record)), tone: 'abstract' } : state === 'unread' ? { text: t(UNREAD_FACT), tone: 'abstract' } : '']} />
          <span className="pdf-ready-side">
            {state === 'done' && <span className="pill ok">{doneSeconds(record) === null ? t('PDF') : t('PDF · {time}', { time: durationText(doneSeconds(record)!) })}</span>}
            {state === 'checking' && <span className="pill"><span className="pdf-spin" aria-hidden />{t('Checking')}</span>}
            {state === 'none' && <span className="pill warn">{t('None open')}</span>}
            {state === 'queued' && <span className="pill">{t('Queued')}</span>}
            {state === 'unread' && <span className="pill warn">{t('Not read yet')}</span>}
          </span>
        </li>)}
      </ul>
      <div className="prow pdf-ready-actions">
        {current.status === 'paused'
          ? <Button variant="outline" size="sm" className="ghost" disabled={busy} onClick={() => control('resume')}><Play size={13} />{t('Resume')}</Button>
          : <Button variant="outline" size="sm" className="ghost" disabled={busy || current.status === 'pause_requested'} onClick={() => control('pause')}><Pause size={13} />{t('Pause')}</Button>}
        <span className="foot-note">{t('{time} so far', { time: durationText(seconds) })}</span>
      </div>
    </section>
  }

  const needs = records.filter(r => !r.answer_reads_nothing && (!full(r) || touched.has(r.source_version_id)))
  const readFull = records.filter(full)
  const pages = readFull.reduce((sum, r) => sum + pagesOf(r), 0)
  const fromZotero = () => {
    const before = new Set(missing.map(r => r.source_version_id))
    void act(async () => {
      const result = await api.zoteroPdfs(researchId, zoteroSource)
      const { added, checked, notes } = result.zotero_pdfs
      touch(result.sources.filter(s => before.has(s.source_version_id) && s.has_pdf_text).map(s => s.source_version_id))
      toast(added < checked || notes.length ? 'warning' : 'success', [t('Zotero: {added} of {checked} PDFs added.', { added, checked }), ...notes.map(n => `${n.title}: ${t(n.note, n.vars)}.`)].join(' '))
    })
  }

  return <>
    <div className="acts">
      <Button className="btn-teal" disabled={busy || Boolean(current && collecting) || !missing.length} title={!missing.length ? t('Every included source has its PDF') : undefined} onClick={() => void collect()}><Download size={15} />{t('Collect open-access PDFs')}</Button>
      {hint}
    </div>
    {unread.length > 0 && <section className="plist pdf-unread" aria-labelledby="pdf-unread-title">
      <h4><span className="pdf-unread-title"><FileClock size={14} aria-hidden /><span id="pdf-unread-title">{t('Your PDF, not read yet')}</span></span><span className="pdf-unread-count tnum">{unread.length}</span></h4>
      <UnreadNote n={unread.length} />
      <ul className="pdf-ready-rows" aria-label={t('Your PDF, not read yet')}>
        {unread.map(record => <li key={record.source_version_id} className="prow">
          <RowHead record={record} facts={[]} />
          <span className="pdf-ready-side"><span className="pill warn" title={t(UNREAD_FACT)}>{t('Not read yet')}</span></span>
        </li>)}
      </ul>
    </section>}
    {needs.length > 0 && <section className="plist" aria-labelledby="pdf-needs-title">
      <h4><span id="pdf-needs-title">{t('Included, no PDF yet')}</span><span className="tnum">{missing.length}</span></h4>
      <ul className="pdf-ready-rows">
        {needs.map(record => <li key={record.source_version_id} className="prow">
          <RowHead record={record} facts={[!full(record) && { text: missingReason(record, versionsOf(record)), tone: 'abstract' }]} note={ocrNote(record)} />
          <span className="pdf-ready-side">{ocrAction(record)}{full(record)
            ? <span className="pill ok">{t('Uploaded · {pages}', { pages: plural(pagesOf(record), '{n} page', '{n} pages') })}</span>
            : <Button variant="outline" size="sm" className="ghost" disabled={busy} onClick={() => { touch([record.source_version_id]); onUpload(record) }}><Upload size={13} aria-hidden />{t('Upload PDF')}</Button>}</span>
        </li>)}
      </ul>
      {missing.length > 0 && <div className="prow pdf-ready-zotero">
        <Button variant="outline" size="sm" className="ghost" disabled={busy} onClick={fromZotero}><ConnectionIcon id="zotero" />{t('Add from Zotero')}</Button>
        <select value={zoteroSource} aria-label={t('Zotero library')} onChange={e => setZoteroSource(e.target.value as ZoteroSource)}>
          <option value="local">{t('this computer')}</option>
          <option value="web">zotero.org</option>
        </select>
      </div>}
    </section>}
    {readFull.length > 0 && <details className="plist pdf-ready-full">
      <summary><h4>{t('PDF text in hand')}</h4><small>{t('{n} · {pages}', { n: readFull.length, pages: plural(pages, '{n} page', '{n} pages') })}</small></summary>
      <ul className="pdf-ready-rows">{readFull.map(record => <li key={record.source_version_id} className="prow">
        <RowHead record={record} facts={[pagesOf(record) > 0 && { text: plural(pagesOf(record), '{n} page', '{n} pages'), tone: 'text' }, reading(record).has_ocr_text && { text: t(OCR_LABEL), tone: 'ocr' }]} note={ocrNote(record)} />
        {ocrAction(record) && <span className="pdf-ready-side">{ocrAction(record)}</span>}
      </li>)}</ul>
    </details>}
  </>
}

// A row head in the Sources list style: title, authors · year, the venue in italics, then dotted facts.
type Fact = string | false | { text: string; tone: string }
function RowHead({ record, facts, note }: { record: Source; facts: Fact[]; note?: ReactNode }) {
  const byline = [record.authors.join(', '), record.year].filter(Boolean).join(' · ')
  const shown = facts.filter(Boolean) as Exclude<Fact, false>[]
  return <span className="pdf-ready-head">
    <strong className="pdf-ready-title">{record.title}</strong>
    {(byline || record.venue) && <span className="source-byline">{byline && <span>{byline}</span>}{record.venue && <span><em>{record.venue}</em></span>}</span>}
    {shown.length > 0 && <span className="source-status">{shown.map(f => typeof f === 'string'
      ? <span key={f} className="source-fact is-plain">{f}</span>
      : <span key={f.text} className={`source-fact is-${f.tone}`}>{f.text}</span>)}</span>}
    {note}
  </span>
}

const UNREAD_FACT = 'Your PDF is attached and not read yet: the answer leaves this work out until the model reads it.'

// Where a person's unread file is followed: "Your files", further down this panel, which also offers Read again.
function UnreadNote({ n }: { n: number }) {
  return <p className="prow pdf-ready-lede">
    {plural(n, '{n} source has your PDF, not read yet. The answer leaves it out until the model reads it.', '{n} sources have your PDF, not read yet. The answer leaves them out until the model reads them.')}{' '}
    <a href="#person-files-title" onClick={e => { e.preventDefault(); document.getElementById('person-files-title')?.scrollIntoView({ block: 'start' }) }}>{t('See it in Your files')}<ArrowRight size={13} aria-hidden /></a>
  </p>
}

// Whether a collection run has anything to try for this work: an open link of the record's own version, or of another version.
function canTry(record: Source, versions: Source[]) {
  // A link refused before is not requested again, and its one lookup for another copy is not repeated (D35).
  const settled = (s: Source) => s.access.fetch?.status === 'failed' && (s.access.other_copy !== null || !s.doi)
  return [record, ...versions].some(s => s.origin === 'provider' && s.access.oa_pdf_url && s.access.oa_pdf_version === s.version_label && !s.access.assets.length && !settled(s))
}

// Why a work has no PDF text, from its record first and then its other versions.
function missingReason(record: Source, versions: Source[]): string {
  const asset = record.access.assets[0]
  if (asset?.extraction_status === 'no_text') return t('PDF has no text layer')
  if (asset?.extraction_status === 'failed') return pdfFailureText(asset.extraction_error)
  for (const s of [record, ...versions]) {
    if (s.access.other_copy?.status === 'failed') return t('No open copy found')
    const fetch = s.access.fetch
    if (fetch?.status === 'failed') {
      if (fetch.http_status === 401 || fetch.http_status === 403) return t('Publisher refused ({status})', { status: fetch.http_status })
      if (fetch.http_status === 404 || fetch.http_status === 410) return t('Link had no PDF')
      return fetchReasonText(fetch.error_code, fetch.http_status)
    }
  }
  if (record.access.oa_pdf_url && record.access.oa_pdf_version !== record.version_label) return t('Open copy is another version')
  if (![record, ...versions].some(s => s.access.oa_pdf_url)) return t('No open link listed')
  return t('Not checked yet')
}
