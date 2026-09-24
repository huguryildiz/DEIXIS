import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react'
import { ExternalLink, FileSearch, RotateCcw, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api, ApiError, type ResearchView, type WaitingMatch, type WaitingRow, type WaitingView, type WaitingWork } from './api'
import { versionText, versionTones, waitingReasonText } from './labels'
import { Notice } from './Notice'
import { useToast } from './Toast'
import { t } from './i18n'

// The works of an sw research no route found a PDF for (slice 18a, SW10.4–5), in reading order. The person opens a
// link in their own browser (through their institution's proxy when one is set), saves the PDF and drops it here. A
// dropped file is matched to a work; the person picks the version and confirms, and only then is it attached. The
// screen never attaches by itself and never opens more than the one link the person clicks.

type Proposal = { key: string; file: File; match: WaitingMatch | null; workId: string; version: string; busy: boolean; refused: string | null }

const isPdf = (file: File) => file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
const plural = (n: number, one: string, many: string) => t(n === 1 ? one : many, { n })
// Authors (the first two, then how many more) and the year, as the Sources list writes a byline.
const byline = (row: WaitingRow) => [row.authors.slice(0, 2).join(', ') + (row.authors.length > 2 ? ` ${t('and {n} more', { n: row.authors.length - 2 })}` : ''), row.year].filter(Boolean).join(' · ')

export function WaitingForPdf({ researchId, view, busy, incoming, onIncomingTaken, onChanged }: {
  researchId: string; view: ResearchView; busy: boolean
  // Files dropped on the PDF panel above the answer; an sw research matches them here (decision 6).
  incoming: File[] | null; onIncomingTaken: () => void
  onChanged: () => Promise<void>
}) {
  const [list, setList] = useState<WaitingView | null>(null)
  const [error, setError] = useState('')
  const [proposals, setProposals] = useState<Proposal[]>([])
  const [matching, setMatching] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [finding, setFinding] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const toast = useToast()

  // Only the newest list request is applied: an older answer arriving late never replaces a newer list.
  const listRequest = useRef(0)
  const load = useCallback(() => {
    const request = ++listRequest.current
    return api.waiting(researchId).then(next => {
      if (request === listRequest.current) { setList(next); setError('') }
    }, e => { if (request === listRequest.current) setError(e instanceof Error ? e.message : String(e)) })
  }, [researchId])
  // The list is derived from stored decisions: read it again whenever the research records something.
  useEffect(() => { void load() }, [load, view.last_event_id])

  // Each file comes back with the work it points at (or none); the person still picks the version.
  const requestMatch = useCallback((pdfs: File[]) => api.matchWaiting(researchId, pdfs).then(({ matches }) => {
    setProposals(old => [...old, ...matches.map((match, i) => ({
      key: `${match.sha256}-${Date.now()}-${i}`, file: pdfs[i], match, workId: match.work?.work_id ?? '', version: '', busy: false, refused: null,
    }))])
  }, e => { toast('error', e instanceof Error ? e.message : String(e)) }), [researchId, toast])

  const matchFiles = (files: File[]) => {
    const pdfs = files.filter(isPdf)
    if (!pdfs.length) { if (files.length) toast('warning', t('Only PDF files can be added.')); return }
    setMatching(true)
    void requestMatch(pdfs).finally(() => setMatching(false))
  }

  // Files dropped on the PDF panel arrive once; they are taken when their match comes back.
  const taken = useRef<File[] | null>(null)
  useEffect(() => {
    if (!incoming?.length || taken.current === incoming) return
    taken.current = incoming
    void requestMatch(incoming.filter(isPdf)).finally(onIncomingTaken)
  }, [incoming, onIncomingTaken, requestMatch])
  const reading = matching || Boolean(incoming?.length)

  const update = (key: string, change: Partial<Proposal>) => setProposals(old => old.map(p => (p.key === key ? { ...p, ...change } : p)))
  const drop = (key: string) => setProposals(old => old.filter(p => p.key !== key))
  const rematch = (p: Proposal) => { drop(p.key); matchFiles([p.file]) }

  // The work a file goes to: the one the match proposed, else the one the person picked among the candidates.
  const workOf = (p: Proposal): WaitingWork | null => {
    if (p.match?.work && p.match.work.work_id === p.workId) return p.match.work
    return p.match?.candidates?.find(w => w.work_id === p.workId) ?? null
  }

  const confirm = async (p: Proposal) => {
    const work = workOf(p)
    if (!p.match || !work || !p.version) return
    update(p.key, { busy: true, refused: null })
    try {
      await api.attachWaiting(researchId, p.file, p.match, work, p.version)
      drop(p.key)
      toast('success', t('PDF attached to the version you chose. Its text was extracted page by page (no OCR).'))
      await Promise.all([load(), onChanged()])
    } catch (e) {
      // A 409 says what moved since the match; the file stays here to be matched again or skipped.
      update(p.key, { busy: false, refused: e instanceof ApiError && e.status === 409 ? e.message : e instanceof Error ? e.message : String(e) })
    }
  }

  const findPdf = async (row: WaitingRow) => {
    if (!row.find_pdf_source_version_id) return
    setFinding(row.work_id)
    try {
      await api.discoverPdf(researchId, row.find_pdf_source_version_id)
      const next = await api.waiting(researchId)
      setList(next)
      const still = next.rows.some(r => r.work_id === row.work_id)
      toast(still ? 'warning' : 'success', t(still ? 'No verified open PDF was attached. A copy whose version needs your check is listed under the source in Sources.' : 'A verified open PDF was found and attached.'))
      await onChanged()
    } catch (e) {
      toast('error', e instanceof Error ? e.message : String(e))
    } finally { setFinding(null) }
  }

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragging(false)
    matchFiles(Array.from(event.dataTransfer.files))
  }

  if (error) return <Notice tone="error">{error}</Notice>
  if (!list) return <p className="legacy-mini-note" role="status">{t('Loading the works waiting for a PDF…')}</p>
  const rows = list.rows

  return <section className="pdf-ready waiting-pdf" aria-labelledby="waiting-title">
    <h2 id="waiting-title">{rows.length ? plural(rows.length, '{n} work waits for your PDF', '{n} works wait for your PDF') : t('No work waits for your PDF')}</h2>
    <p className="pdf-ready-lede">{rows.length
      ? t('No open copy of these works was found. If you can reach one through your library, open its link, save the PDF and drop it here. Nothing is attached until you choose the version and confirm.')
      : list.has_plan ? t('Every work the full-text retrieval tried has its text, or is decided another way.') : t('The full-text retrieval has not run for this question yet.')}</p>
    {rows.length > 0 && <p className="pdf-ready-hint">{list.via_proxy
      ? t('Links open through your institution’s proxy in your browser; DEIXIS sends nothing through it.')
      : <>{t('Links open directly.')} <a href="#/settings/connections">{t('Set your institution’s proxy address')}</a></>}</p>}

    {proposals.map(p => <MatchPanel key={p.key} proposal={p} rows={rows} work={workOf(p)} busy={busy}
      onWork={workId => update(p.key, { workId, version: '', refused: null })} onVersion={version => update(p.key, { version, refused: null })}
      onConfirm={() => { void confirm(p) }} onSkip={() => drop(p.key)} onRematch={() => rematch(p)} />)}

    {list.has_plan && <div className={`pdf-ready-drop${dragging ? ' is-over' : ''}`} data-testid="waiting-drop"
      onDragOver={e => { e.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={onDrop}>
      <span role="status">{t(reading ? 'Reading the files…' : 'Drop PDFs here. Each is matched to a work by the DOI or title on its first pages; you choose the version and confirm.')}</span>
      <span className="pdf-ready-drop-actions">
        <Button variant="outline" size="sm" disabled={busy || reading} onClick={() => fileInput.current?.click()}><Upload size={14} aria-hidden />{t('Choose files')}</Button>
      </span>
      <input ref={fileInput} type="file" accept=".pdf,application/pdf" multiple hidden aria-label={t('Choose PDF files')} onChange={e => { matchFiles(Array.from(e.target.files ?? [])); e.target.value = '' }} />
    </div>}

    {rows.length > 0 && <ol className="pdf-ready-rows waiting-rows" aria-label={t('Works waiting for your PDF, in reading order')}>
      {rows.map(row => <li key={row.work_id}>
        <span className="waiting-place" title={t('Place in the reading order')}>{row.place}</span>
        <span className="pdf-ready-head">
          <strong className="pdf-ready-title">{row.title}</strong>
          {(byline(row) || row.venue) && <span className="source-byline">
            {byline(row) && <span>{byline(row)}</span>}
            {row.venue && <span><em>{row.venue}</em></span>}
          </span>}
          <span className="source-status">
            <span className="source-fact is-abstract">{waitingReasonText(row.reason_code)}</span>
            {row.doi && <span className="source-fact is-plain waiting-doi">{row.doi}</span>}
          </span>
        </span>
        <span className="pdf-ready-side waiting-actions">
          {row.links.doi && <a className="pdf-ready-link waiting-link" href={row.links.doi} target="_blank" rel="noopener noreferrer">{t('DOI')}<ExternalLink size={12} aria-hidden /><span className="sr-only">{t('(opens in a new tab)')}</span></a>}
          {row.links.landing && <a className="pdf-ready-link waiting-link" href={row.links.landing} target="_blank" rel="noopener noreferrer">{t('Publisher page')}<ExternalLink size={12} aria-hidden /><span className="sr-only">{t('(opens in a new tab)')}</span></a>}
          <Button variant="outline" size="sm" disabled={busy || finding !== null || !row.find_pdf_source_version_id}
            title={row.find_pdf_source_version_id ? undefined : t('Find PDF needs a DOI')} onClick={() => { void findPdf(row) }}>
            <FileSearch size={14} aria-hidden />{t(finding === row.work_id ? 'Finding…' : 'Find PDF')}
          </Button>
        </span>
      </li>)}
    </ol>}
  </section>
}

// One dropped file: what the match found, the work it goes to, and the version the person picks before confirming.
function MatchPanel({ proposal: p, rows, work, busy, onWork, onVersion, onConfirm, onSkip, onRematch }: {
  proposal: Proposal; rows: WaitingRow[]; work: WaitingWork | null; busy: boolean
  onWork: (workId: string) => void; onVersion: (version: string) => void; onConfirm: () => void; onSkip: () => void; onRematch: () => void
}) {
  const m = p.match
  const facts = [
    m?.page_count ? plural(m.page_count, '{n} page', '{n} pages') : null,
    m?.has_text_layer === false ? t('no text layer: its pages would need OCR') : m?.has_text_layer ? t('has a text layer') : null,
  ].filter(Boolean).join(' · ')
  const basis = m?.basis === 'doi' ? t('Its first pages name this work’s DOI.') : m?.basis === 'title' ? t('Its first pages carry this work’s title.') : t('Its first pages name no work a file can go to here. Choose the work it belongs to.')
  const name = `version-${p.key}`
  return <div className="waiting-match" role="group" aria-label={t('Where {file} goes', { file: p.file.name })}>
    <p className="waiting-file"><strong>{p.file.name}</strong>{facts && <small>{facts}</small>}</p>
    <p className="waiting-basis">{basis}</p>
    {m?.work
      ? <p className="waiting-work">{m.work.title}</p>
      : <select value={p.workId} aria-label={t('Work for {file}', { file: p.file.name })} onChange={e => onWork(e.target.value)}>
        <option value="">{t('Choose a work')}</option>
        {/* The works waiting for a PDF first, in reading order; then the other works a file may go to here. */}
        {rows.filter(r => m?.candidates?.some(w => w.work_id === r.work_id)).map(r => <option key={r.work_id} value={r.work_id}>{`${r.place}. ${r.title}`}</option>)}
        {(m?.candidates ?? []).filter(w => !rows.some(r => r.work_id === w.work_id)).sort((a, b) => a.title.localeCompare(b.title)).map(w => <option key={w.work_id} value={w.work_id}>{t('{title} (not waiting)', { title: w.title })}</option>)}
      </select>}
    {work && <fieldset className="waiting-versions">
      <legend>{t('Which version is this file? Choose one.')}</legend>
      {work.versions.map(v => <label key={v.source_version_id} className={v.has_pdf ? 'is-disabled' : undefined}>
        <input type="radio" name={name} value={v.source_version_id} checked={p.version === v.source_version_id} disabled={v.has_pdf} onChange={() => onVersion(v.source_version_id)} />
        <span className={`ref-pill is-${versionTones[v.version_label ?? ''] ?? 'unstated'}`}>{versionText(v.version_label)}</span>
        <span className="waiting-version-facts">{[v.year, v.publication_type, v.doi].filter(Boolean).join(' · ')}</span>
        {v.proposed && <small className="waiting-version-note">{t('named by the file')}</small>}
        {v.has_pdf && <small className="waiting-version-note">{t('already has a PDF')}</small>}
      </label>)}
    </fieldset>}
    {p.refused && <Notice tone="attention">{p.refused}</Notice>}
    <div className="pdf-ready-actions">
      {p.refused
        ? <Button size="sm" variant="outline" disabled={busy} onClick={onRematch}><RotateCcw size={14} aria-hidden />{t('Match this file again')}</Button>
        : <Button size="sm" disabled={busy || p.busy || !work || !p.version} onClick={onConfirm}>{t(p.busy ? 'Attaching…' : 'Attach to this version')}</Button>}
      <button type="button" className="pdf-ready-link" onClick={onSkip}>{t('Do not attach')}</button>
      {!p.refused && work && !p.version && <span className="pdf-ready-hint">{t('Choose the version first.')}</span>}
    </div>
  </div>
}
