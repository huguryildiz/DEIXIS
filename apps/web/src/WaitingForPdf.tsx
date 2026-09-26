import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react'
import { BookOpen, CircleCheck, CircleDashed, CircleMinus, ExternalLink, FileSearch, Info, RotateCcw, TriangleAlert, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api, ApiError, type AttachOutcome, type PersonFile, type PersonFiles, type ResearchView, type WaitingMatch, type WaitingRow, type WaitingView, type WaitingWork } from './api'
import { pageLocator, personFileStateText, personUnreadText, queueAnswerLabels, queueAnswerOfCode, versionText, versionTones, waitingReasonText } from './labels'
import { Notice } from './Notice'
import { useToast } from './Toast'
import { t } from './i18n'

// The works of an sw research no route found a PDF for (slice 18a, SW10.4–5), in reading order. The person opens a
// link in their own browser (through their institution's proxy when one is set), saves the PDF and drops it here. A
// dropped file is matched to a work; the person picks the version and confirms, and only then is it attached. The
// screen never attaches by itself and never opens more than the one link the person clicks.
//
// Below the list, "Your files" (slice 18b) says what became of each file the person added: waiting to be read, being
// read, and what the reading decided, all from what is stored. A file the model could not read is read again only when
// the person asks; a paused run is resumed or cancelled from here, never stepped around.

type Proposal = { key: string; file: File; match: WaitingMatch | null; workId: string; version: string; busy: boolean; refused: string | null }

const isPdf = (file: File) => file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
const plural = (n: number, one: string, many: string) => t(n === 1 ? one : many, { n })
// Authors (the first two, then how many more) and the year, as the Sources list writes a byline.
const byline = (row: WaitingRow) => [row.authors.slice(0, 2).join(', ') + (row.authors.length > 2 ? ` ${t('and {n} more', { n: row.authors.length - 2 })}` : ''), row.year].filter(Boolean).join(' · ')

export function WaitingForPdf({ researchId, view, busy, incoming, onIncomingTaken, onChanged }: {
  researchId: string; view: ResearchView; busy: boolean
  // Files dropped on the PDF panel above the answer; an sw research matches them here (decision 6).
  incoming: File[] | null; onIncomingTaken: () => void
  // `announced` names a run this view's own toast already announced, so the research does not announce it again.
  onChanged: (announced?: string) => Promise<void>
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
      const { attached, runs } = await api.attachWaiting(researchId, p.file, p.match, work, p.version)
      drop(p.key)
      // The reading run the attach opened is announced by this toast, not by a second "started" one.
      const opened = attached.reading === 'requested' ? runs.find(r => r.kind === 'fulltext_adjudication' && r.status === 'queued') : undefined
      toast('success', `${t('PDF attached to the version you chose. Its text was extracted page by page (no OCR).')} ${attachedText(attached.reading)}`)
      await Promise.all([load(), onChanged(opened?.id)])
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

    {list.files.rows.length > 0 && <YourFiles researchId={researchId} files={list.files} busy={busy} onChanged={async announced => { await Promise.all([load(), onChanged(announced)]) }} />}
  </section>
}

// What the toast adds once a file is attached: what happens to it next (slice 18b).
const attachedText = (reading: AttachOutcome) => t({
  requested: 'The model reads it before the other works waiting to be read.',
  model_off: 'The model does not read it: full-text reading is off, or no criterion is frozen.',
  not_eligible: 'The model does not read it: this work is not in the reading order.',
  decision_stands: 'Your decision about this work stands; the model does not read the file.',
  unreadable: 'It has no text layer, so the work still waits for a PDF with text.',
}[reading])

// The files the person added and what became of each (slice 18b, decision 9).
function YourFiles({ researchId, files, busy, onChanged }: { researchId: string; files: PersonFiles; busy: boolean; onChanged: (announced?: string) => Promise<void> }) {
  const [acting, setActing] = useState<string | null>(null)
  const toast = useToast()
  const act = async (key: string, work: () => Promise<unknown>, done: string) => {
    setActing(key)
    try {
      const result = await work()
      toast('success', t(done))
      // A retry's toast announces the run it opened.
      await onChanged((result as { run?: { id: string } | null } | undefined)?.run?.id)
    } catch (e) {
      toast('error', e instanceof Error ? e.message : String(e))
    } finally { setActing(null) }
  }
  const paused = files.paused_run
  return <section className="person-files" aria-labelledby="person-files-title">
    <h3 id="person-files-title">{t('Your files')}</h3>
    <p className="pdf-ready-hint">{t('What the full-text reading made of each file you added. A quote is shown only where code found it on the page the model was shown; whether it supports the criterion is not checked.')}</p>
    {paused && <Notice tone="attention">
      <p>{t('A paused run holds back the reading of your files. Resume it or cancel it; no other run starts while it is paused.')}</p>
      <span className="person-files-actions">
        <Button size="sm" variant="outline" disabled={busy || acting !== null} onClick={() => { void act('resume', () => api.controlRun(paused.id, 'resume'), 'The paused run was resumed.') }}>{t('Resume the paused run')}</Button>
        <Button size="sm" variant="outline" disabled={busy || acting !== null} onClick={() => { void act('cancel', () => api.controlRun(paused.id, 'cancel'), 'The paused run was cancelled.') }}>{t('Cancel the paused run')}</Button>
      </span>
    </Notice>}
    <ul className="person-files-rows" aria-label={t('Files you added')}>
      {files.rows.map(row => <li key={row.asset_id} className={`is-${row.state}`}>
        <strong className="pdf-ready-title">{row.title}</strong>
        <span className="person-file-facts">
          <span className={`ref-pill is-${versionTones[row.version_label ?? ''] ?? 'unstated'}`}>{versionText(row.version_label)}</span>
          {row.filename && <span className="person-file-name">{row.filename}</span>}
        </span>
        <PersonFileState row={row} researchId={researchId} />
        {row.state === 'included' && row.quotes.length > 0 && <ul className="person-file-quotes" aria-label={t('Quotes code found on their pages')}>
          {row.quotes.map(q => <li key={`${q.part}-${q.quote}`}>
            <blockquote>{q.quote}</blockquote>
            <small>{[q.part, q.page != null ? pageLocator(q.page, q.rendition) : null].filter(Boolean).join(' · ')}</small>
          </li>)}
        </ul>}
        {(row.state === 'unread' || row.state === 'changed') && row.request_id && <span className="person-files-actions">
          <Button size="sm" variant="outline" disabled={busy || acting !== null} onClick={() => { void act(row.request_id!, () => api.retryPersonReading(researchId, row.request_id!), 'The file waits to be read again.') }}>
            <RotateCcw size={14} aria-hidden />{t(acting === row.request_id ? 'Asking…' : 'Read again')}
          </Button>
        </span>}
      </li>)}
    </ul>
  </section>
}

// One file's state as a line of text with its icon; the tone follows the state, never the colour alone.
function PersonFileState({ row, researchId }: { row: PersonFile; researchId: string }) {
  if (row.state === 'reading') return <p className="person-file-state is-live" role="status"><BookOpen size={14} aria-hidden /><span className="shimmer-text">{personFileStateText(row)}</span></p>
  const Icon = row.state === 'included' ? CircleCheck : row.state === 'waiting' ? CircleDashed
    : row.state === 'unread' || row.state === 'changed' || row.state === 'your_decision' ? TriangleAlert : row.state === 'criterion_not_met' ? CircleMinus : Info
  const earlier = row.decided_code ? queueAnswerOfCode[row.decided_code] : undefined
  return <p className="person-file-state">
    <Icon size={14} aria-hidden />
    <span>
      {personFileStateText(row)}
      {row.state === 'decision_stands' && earlier && <> {t('Your answer: {answer}.', { answer: t(queueAnswerLabels[earlier]) })}</>}
      {row.state === 'unread' && row.unread_reason && <> {personUnreadText(row.unread_reason)}</>}
      {row.state === 'your_decision' && <> <a href={`#/research/${researchId}/queue`}>{t('Open it in Awaiting your decision')}</a></>}
    </span>
  </p>
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
    {work && !p.refused && <AttachNote work={work} version={p.version} hasText={m?.has_text_layer ?? null} />}
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

// What confirming leads to, said before the person confirms (slice 18b, decisions 2 and 3): the reading, a decision of
// theirs that stands, reading being off, or a work none of whose versions can take another file here.
function AttachNote({ work, version, hasText }: { work: WaitingWork; version: string; hasText: boolean | null }) {
  if (work.versions.every(v => v.has_pdf)) return <Notice tone="attention">{t('Every version of this work already has a PDF in use. A file is not replaced or removed here, so this work cannot take a new one.')}</Notice>
  const chosen = work.versions.find(v => v.source_version_id === version)
  if (!chosen) return null
  if (hasText === false) return <Notice tone="info">{t('This file has no text layer: it is attached, and the work keeps waiting for a PDF with text.')}</Notice>
  const wrong = work.versions.find(v => v.person_decision === 'human_pdf_wrong')
  switch (chosen.after_attach) {
    case 'requested':
      return wrong && wrong !== chosen
        ? <Notice tone="info">{t('You said the file of the {wrong} version was wrong. This file goes to the {chosen} version and the model reads it; your answer about the {wrong} version stands.', { wrong: versionText(wrong.version_label), chosen: versionText(chosen.version_label) })}</Notice>
        : <p className="pdf-ready-hint">{t('The model reads this file before the other works waiting to be read.')}</p>
    case 'decision_stands':
      return <Notice tone="info">{t(wrong === chosen ? 'You said the file of this version was wrong, and that answer stands. The file is added; the model does not read it.' : 'Your decision about this work stands. The file is added; the model does not read it.')}</Notice>
    case 'model_off':
      return <Notice tone="info">{t('Full-text reading is off, or no criterion is frozen: the file is added and the model does not read it.')}</Notice>
    case 'not_eligible':
      return <Notice tone="info">{t('This work is not in the reading order: the file is added and the model does not read it.')}</Notice>
    default:
      return null
  }
}
