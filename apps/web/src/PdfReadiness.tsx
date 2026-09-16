import { useEffect, useRef, useState, type DragEvent } from 'react'
import { Download, Pause, Play, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api, type PdfMatch, type ResearchView, type Source, type ZoteroSource } from './api'
import { ConnectionIcon } from './connectionIcons'
import { fetchReasonText } from './labels'
import { t } from './i18n'

// Between screening and the answer (D49): how many included works an answer can read in full, a run that collects their
// open PDFs, and ways to add the rest (a PDF per row, several dropped at once, or the user's Zotero library).
// Three states: before collecting, while collecting (or paused), and after.

const ACTIVE = new Set(['queued', 'running', 'pause_requested'])
type Proposal = { file: File; match: PdfMatch; target: string; hasPdf: boolean }

const durationText = (seconds: number) => (seconds < 60 ? t('{s} s', { s: seconds }) : t('{m} min {s} s', { m: Math.floor(seconds / 60), s: seconds % 60 }))
const plural = (n: number, one: string, many: string, vars: Record<string, string | number> = {}) => t(n === 1 ? one : many, { n, ...vars })

export function PdfReadiness({ researchId, view, busy, hasAcademic, act, onSearchAgain, onAnswer, onUpload }: {
  researchId: string; view: ResearchView; busy: boolean; hasAcademic: boolean
  act: (action: () => Promise<unknown>, success?: string) => Promise<void>
  onSearchAgain: () => void; onAnswer: () => void; onUpload: (source: Source) => void
}) {
  const byId = new Map(view.sources.map(s => [s.source_version_id, s]))
  const records = view.sources.filter(s => s.version_role === 'record' && s.selection.state === 'included')
  const versionsOf = (record: Source) => view.sources.filter(s => s.work_id === record.work_id && s.source_version_id !== record.source_version_id)
  // The version an answer reads: the record, or another version with PDF text (D48).
  const reading = (record: Source) => (record.answer_reads_version_id ? byId.get(record.answer_reads_version_id) ?? record : record)
  const full = (record: Source) => reading(record).has_pdf_text
  const pagesOf = (record: Source) => reading(record).access.assets[0]?.page_count ?? 0

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
  const [proposals, setProposals] = useState<Proposal[] | null>(null)
  const [matching, setMatching] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [zoteroSource, setZoteroSource] = useState<ZoteroSource>('local')
  const [zoteroNote, setZoteroNote] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)

  const total = records.length
  const inHand = records.filter(full).length
  const missing = records.filter(r => !full(r))
  const pages = records.filter(full).reduce((sum, r) => sum + pagesOf(r), 0)

  const collect = () => act(() => api.startRun(researchId, 'pdf_collection', crypto.randomUUID()))
  const control = (action: 'pause' | 'resume') => current && act(() => api.controlRun(current.id, action))

  if (!total) return null

  // ---- state 2: collecting ----------------------------------------------------------
  if (current && collecting) {
    const steps = current.steps ?? []
    const stepsOf = (record: Source) => {
      const ids = new Set([record.source_version_id, ...versionsOf(record).map(v => v.source_version_id)])
      return steps.filter(s => ids.has(s.operation_key.split(':')[1] ?? ''))
    }
    const rowState = (record: Source): 'done' | 'checking' | 'none' | 'queued' => {
      const own = stepsOf(record)
      if (full(record)) return 'done'
      if (own.some(s => s.status === 'running')) return 'checking'
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
    const pct = (n: number) => `${total ? (100 * n) / total : 0}%`
    return <section className="pdf-ready" aria-labelledby="pdf-ready-title">
      <h2 id="pdf-ready-title">{t(current.status === 'paused' ? 'PDF collection paused' : 'Collecting open-access PDFs')}</h2>
      <Depth cells={[[inHand, t('PDFs in hand')], [count('none'), t('checked, none open')], [count('queued') + count('checking'), t('still to check')]]} />
      <div className="pdf-ready-bar" aria-hidden><i className="is-pdf" style={{ width: pct(inHand) }} /><i className="is-run" style={{ width: pct(count('none')) }} /></div>
      <ul className="pdf-ready-rows">
        {states.map(([record, state]) => <li key={record.source_version_id}>
          <span className="pdf-ready-title">{record.title}</span>
          <span className="pdf-ready-meta">{[record.venue, state === 'checking' ? t(stepsOf(record).some(s => s.kind === 'pdf_other_copy' && s.status === 'running') ? 'looking for another open copy' : 'downloading') : state === 'queued' ? t('waiting') : state === 'done' && pagesOf(record) ? plural(pagesOf(record), '{n} page', '{n} pages') : state === 'none' ? missingReason(record, versionsOf(record)) : ''].filter(Boolean).join(' · ')}</span>
          <span className="pdf-ready-side">
            {state === 'done' && <span className="pdf-pill is-ok">{doneSeconds(record) === null ? t('PDF') : t('PDF · {time}', { time: durationText(doneSeconds(record)!) })}</span>}
            {state === 'checking' && <span className="pdf-pill is-run"><span className="pdf-spin" aria-hidden />{t('Checking')}</span>}
            {state === 'none' && <span className="pdf-pill is-warn">{t('None open')}</span>}
            {state === 'queued' && <span className="pdf-pill">{t('Queued')}</span>}
          </span>
        </li>)}
      </ul>
      <div className="pdf-ready-actions">
        {current.status === 'paused'
          ? <Button variant="outline" size="sm" disabled={busy} onClick={() => control('resume')}><Play size={13} />{t('Resume')}</Button>
          : <Button variant="outline" size="sm" disabled={busy || current.status === 'pause_requested'} onClick={() => control('pause')}><Pause size={13} />{t('Pause')}</Button>}
        <span className="pdf-ready-hint">{t('{time} so far', { time: durationText(seconds) })}</span>
      </div>
    </section>
  }

  // ---- state 1: before collecting -----------------------------------------------------
  if (!current && missing.length) {
    return <section className="pdf-ready" aria-labelledby="pdf-ready-title">
      <h2 id="pdf-ready-title">{t('Before the answer: how deeply can it read?')}</h2>
      <p className="pdf-ready-lede">{t('Screening read titles and abstracts. The answer can cite only what it reads, so a source without a PDF is cited from its abstract alone.')}</p>
      <Depth cells={[[total, t('included sources')], [inHand, t('PDF already in hand')], [missing.length, t('abstract only for now')]]} />
      <div className="pdf-ready-bar" aria-hidden><i className="is-pdf" style={{ width: `${(100 * inHand) / total}%` }} /></div>
      <div className="pdf-ready-actions">
        <Button disabled={busy} onClick={() => void collect()}><Download size={15} />{t('Collect open-access PDFs')}</Button>
        <button type="button" className="pdf-ready-link" disabled={busy} onClick={onAnswer}>{t('Generate answer now')}</button>
        {hasAcademic && <button type="button" className="pdf-ready-link" disabled={busy} onClick={onSearchAgain}>{t('Search again')}</button>}
      </div>
      <p className="pdf-ready-hint">{t('Tries each source’s open links, then looks once for another open copy. Nothing is downloaded from paywalled sites.')}</p>
    </section>
  }

  // ---- state 3: after collecting, or nothing is missing ---------------------------------
  const needs = records.filter(r => !full(r) || touched.has(r.source_version_id))
  const stillMissing = missing.length
  const readFull = records.filter(full)

  const matchFiles = async (files: File[]) => {
    const pdfs = files.filter(f => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'))
    if (!pdfs.length) return
    setMatching(true)
    try {
      const { matches } = await api.matchUploads(researchId, pdfs)
      // A match to another version of a work is proposed on that work's row.
      const recordOf = (svid: string | null) => (svid ? records.find(r => r.source_version_id === svid || versionsOf(r).some(v => v.source_version_id === svid)) : undefined)
      setProposals(matches.map((match, i) => {
        const record = recordOf(match.source_version_id)
        return { file: pdfs[i], match, target: record && !full(record) ? record.source_version_id : '', hasPdf: Boolean(record && full(record)) }
      }))
    } catch (e) {
      setZoteroNote(e instanceof Error ? e.message : String(e))
    } finally { setMatching(false) }
  }
  const attachProposals = () => {
    const chosen = (proposals ?? []).filter(p => p.target)
    if (!chosen.length) return
    setProposals(null)
    void act(async () => {
      for (const p of chosen) { await api.uploadToSource(researchId, p.target, p.file); touch([p.target]) }
    }, plural(chosen.length, '{n} PDF attached. Its text was extracted page by page (no OCR).', '{n} PDFs attached. Their text was extracted page by page (no OCR).'))
  }
  const fromZotero = () => {
    setZoteroNote('')
    const before = new Set(missing.map(r => r.source_version_id))
    void act(async () => {
      const result = await api.zoteroPdfs(researchId, zoteroSource)
      const { added, checked, notes } = result.zotero_pdfs
      touch(result.sources.filter(s => before.has(s.source_version_id) && s.has_pdf_text).map(s => s.source_version_id))
      setZoteroNote([t('Zotero: {added} of {checked} PDFs added.', { added, checked }), ...notes.map(n => `${n.title}: ${n.note}.`)].join(' '))
    })
  }
  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragging(false)
    void matchFiles(Array.from(event.dataTransfer.files))
  }

  return <section className="pdf-ready" aria-labelledby="pdf-ready-title">
    <h2 id="pdf-ready-title">{stillMissing ? t('{full} of {total} sources will be read in full', { full: inHand, total }) : plural(total, 'The {n} source will be read in full', 'All {n} sources will be read in full')}</h2>
    {stillMissing > 0 && <p className="pdf-ready-lede">{plural(stillMissing, '{n} source still has no PDF. Add it if you have access, or generate the answer and it is cited from its abstract.', '{n} sources still have no PDF. Add the ones you have access to, or generate the answer and those {n} are cited from their abstracts.')}</p>}
    <div className="pdf-ready-bar" aria-hidden><i className="is-pdf" style={{ width: `${(100 * inHand) / total}%` }} /></div>

    {needs.length > 0 && <>
      <div className="pdf-ready-group"><h3>{t('Needs your PDF')}</h3><small>{stillMissing}</small></div>
      <ul className="pdf-ready-rows">
        {needs.map(record => <li key={record.source_version_id}>
          <span className="pdf-ready-title">{record.title}</span>
          <span className="pdf-ready-meta">{[record.venue, record.year].filter(Boolean).join(' · ')}{!full(record) && <span className="pdf-pill is-warn">{missingReason(record, versionsOf(record))}</span>}</span>
          <span className="pdf-ready-side">{full(record)
            ? <span className="pdf-pill is-ok">{t('Uploaded · {pages}', { pages: plural(pagesOf(record), '{n} page', '{n} pages') })}</span>
            : <Button variant="outline" size="sm" disabled={busy} onClick={() => { touch([record.source_version_id]); onUpload(record) }}>{t('Upload PDF')}</Button>}</span>
        </li>)}
      </ul>

      {proposals
        ? <div className="pdf-ready-matches">
          <p>{t('Check where each file goes. Nothing is attached until you confirm.')}</p>
          <ul>{proposals.map((p, i) => <li key={`${p.file.name}-${i}`}>
            <span className="pdf-ready-file">{p.file.name}<small>{t(p.hasPdf ? 'matches a source that already has its PDF' : p.match.basis === 'doi' ? 'matched by DOI' : p.match.basis === 'title' ? 'matched by title' : 'no match found')}</small></span>
            <select value={p.target} aria-label={t('Source for {file}', { file: p.file.name })} onChange={e => setProposals(proposals.map((q, j) => (j === i ? { ...q, target: e.target.value } : q)))}>
              <option value="">{t('Do not attach')}</option>
              {missing.map(r => <option key={r.source_version_id} value={r.source_version_id}>{r.title}</option>)}
            </select>
          </li>)}</ul>
          <div className="pdf-ready-actions">
            <Button size="sm" disabled={busy || !proposals.some(p => p.target)} onClick={attachProposals}>{plural(proposals.filter(p => p.target).length, 'Attach {n} PDF', 'Attach {n} PDFs')}</Button>
            <button type="button" className="pdf-ready-link" onClick={() => setProposals(null)}>{t('Cancel')}</button>
          </div>
        </div>
        : stillMissing > 0 && <div className={`pdf-ready-drop${dragging ? ' is-over' : ''}`} onDragOver={e => { e.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={onDrop}>
          <span>{t(matching ? 'Reading the files…' : 'Drop several PDFs here; each is matched to a source by DOI or title, and you confirm the matches.')}</span>
          <span className="pdf-ready-drop-actions">
            <Button variant="outline" size="sm" disabled={busy || matching} onClick={() => fileInput.current?.click()}>{t('Choose files')}</Button>
            <span className="pdf-ready-zotero">
              <Button variant="outline" size="sm" disabled={busy || matching} onClick={fromZotero}><ConnectionIcon id="zotero" />{t('Add from Zotero')}</Button>
              <select value={zoteroSource} aria-label={t('Zotero library')} onChange={e => setZoteroSource(e.target.value as ZoteroSource)}>
                <option value="local">{t('this computer')}</option>
                <option value="web">zotero.org</option>
              </select>
            </span>
          </span>
          <input ref={fileInput} type="file" accept=".pdf,application/pdf" multiple hidden onChange={e => { void matchFiles(Array.from(e.target.files ?? [])); e.target.value = '' }} />
        </div>}
      {zoteroNote && <p className="pdf-ready-hint">{zoteroNote}</p>}
    </>}

    {readFull.length > 0 && <details className="pdf-ready-full">
      <summary className="pdf-ready-group"><h3>{t('Read in full')}</h3><small>{t('{n} · {pages}', { n: readFull.length, pages: plural(pages, '{n} page', '{n} pages') })}</small></summary>
      <ul className="pdf-ready-rows">{readFull.map(record => <li key={record.source_version_id}>
        <span className="pdf-ready-title">{record.title}</span>
        <span className="pdf-ready-meta">{[record.venue, record.year, pagesOf(record) ? plural(pagesOf(record), '{n} page', '{n} pages') : ''].filter(Boolean).join(' · ')}</span>
      </li>)}</ul>
    </details>}

    <div className="pdf-ready-actions">
      <Button disabled={busy} onClick={onAnswer}><Sparkles size={15} />{t('Generate source-linked answer')}</Button>
      {stillMissing > 0 && <span className="pdf-ready-hint is-warn">{plural(stillMissing, '{n} source from abstract only', '{n} sources from abstract only')}</span>}
      {hasAcademic && <button type="button" className="pdf-ready-link" disabled={busy} onClick={onSearchAgain}>{t('Search again')}</button>}
    </div>
  </section>
}

function Depth({ cells }: { cells: [number, string][] }) {
  return <div className="pdf-ready-depth">{cells.map(([n, label]) => <div key={label}><strong>{n}</strong><span>{label}</span></div>)}</div>
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
