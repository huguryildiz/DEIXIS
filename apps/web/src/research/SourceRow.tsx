import { useEffect, useRef, useState } from 'react'
import { BookOpenText, ChevronRight, FileText, FileUp, ListMinus, LoaderCircle, Replace, ScanText, Sigma, Search, Trash2, UserPen } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tooltip } from '@/components/ui/tooltip'
import { type Source } from '../api'
import { serviceErrorSentence, serviceKind, accessParts, citedText, providerName, queueAnsweredText, versionText, versionTones } from '../labels'
import { TextRecovery } from '../TextRecovery'
import { Elapsed } from '../EvidenceTable'
import { ConnectionIcon } from '../connectionIcons'
import { ocrOffer } from '../ocr'
import { OcrButton, OcrNote } from '../OcrNote'
import { t, uiLocale } from '../i18n'
import { focusWhenLost } from '../focus'
import { SourceKey } from '../SourceKey'
import type { OcrContext } from './shared'

// The reason field takes focus only if focus is still on the Exclude control or has fallen to the page body; it is not taken from another control.
function ReasonForm({ busy, onSave, focusOnOpen }: { busy: boolean; onSave: (reason: string) => void; focusOnOpen: HTMLElement | null }) {
  const [text, setText] = useState('')
  const field = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (focusOnOpen && (document.activeElement === focusOnOpen || document.activeElement === document.body)) field.current?.focus()
  }, [focusOnOpen])
  return <form className="reason-form" onSubmit={e => { e.preventDefault(); if (text.trim()) onSave(text.trim()) }}>
    <input ref={field} aria-label={t('Reason for excluding this source')} placeholder={t('Why exclude it? Optional; kept with your choice.')} maxLength={1000} value={text} onChange={e => setText(e.target.value)} />
    <Button type="submit" variant="outline" size="sm" disabled={busy || !text.trim()}>{t('Save reason')}</Button>
  </form>
}

// The PDF lookup is one request, so this names the services it checks without claiming which one is running.
const PDF_LOOKUP_SERVICES = ['unpaywall', 'openalex', 'crossref']
function PdfSearchStatus() {
  const [since] = useState(() => new Date().toISOString())
  return <p className="pdf-search-status" role="status">
    <span className="sr-only">{t('Checking Unpaywall, OpenAlex and Crossref; Web Search will run if no verified PDF is retrieved…')}</span>
    <LoaderCircle size={14} className="pdf-search-spin" aria-hidden />
    <strong aria-hidden>{t('Finding PDF')}</strong>
    <span className="pdf-search-services" title={PDF_LOOKUP_SERVICES.map(providerName).join(', ')} aria-hidden>{PDF_LOOKUP_SERVICES.map(id => <ConnectionIcon key={id} id={id} />)}</span>
    <span className="pdf-search-muted" aria-hidden>{t('{n} open-access services', { n: PDF_LOOKUP_SERVICES.length })}</span>
    <span className="pdf-search-sep" aria-hidden />
    <span className="pdf-search-muted" aria-hidden><ConnectionIcon id="web_search" />{t('Web Search if needed')}</span>
    <Elapsed since={since} />
  </p>
}

export function SourceRow({ source, busy, picked, onPick, onRemoveFromResearch, readsVersion, onSelect, onReason, onAbstract, onDiscoverPdf, onAttachPdf, onAttachCandidate, onOpenPdf, onRemoveAsset, onReplaceAsset, onReextract, onRereadEquations, finding, ocr }: { source: Source; busy: boolean; picked: boolean; onPick: (on: boolean) => void; onRemoveFromResearch: () => void; onSelect: (state: Source['selection']['state']) => void; onReason: (reason: string) => void; onAbstract: () => void; onDiscoverPdf: () => void; onAttachPdf: () => void; onAttachCandidate: (candidateId: string) => void; onOpenPdf: (assetId: string) => void; onRemoveAsset: (assetId: string) => void; onReplaceAsset: (assetId: string) => void; onReextract: (assetId: string) => void; onRereadEquations: (assetId: string) => void; finding: boolean; ocr: OcrContext; readsVersion?: Source }) {
  const s = source.selection
  const other = source.version_role === 'other_version'
  const authors = source.authors.join(', ')
  const citationDetails = [source.volume && t('vol. {value}', { value: source.volume }), source.issue && t('no. {value}', { value: source.issue }), source.pages && t('pp. {value}', { value: source.pages })].filter(Boolean).join(', ')
  // A citation-style byline: who and when, then where it appeared and how often OpenAlex counts it cited.
  const byline = [authors, source.year].filter(Boolean).join(' · ')
  const venueLine = [citationDetails, citedText(source.cited_by_count)].filter(Boolean)
  const discoveries = source.access.pdf_discoveries
  const candidates = source.access.pdf_candidates
  const unusable = candidates.filter(c => c.access_status !== 'downloaded').length
  const lookupSummary = [t('{p} services · {n} checks', { p: new Set(discoveries.map(d => d.provider)).size, n: discoveries.length }), unusable && t(unusable === 1 ? '{n} file not usable' : '{n} files not usable', { n: unusable })].filter(Boolean).join(' · ')
  const primaryAction = source.access.assets.length ? 'pdf' : 'abstract'
  // Exclude and Save reason each end by removing the control they were pressed with; focus goes on to the field and then to the saved reason.
  const [askedReason, setAskedReason] = useState<HTMLElement | null>(null)
  const reasonNote = useRef<HTMLParagraphElement>(null)
  const ocrOffers = new Map(source.access.assets.map(asset => [asset.id, ocrOffer(asset, ocr.tool, ocr.runs)]))
  return <div className={`source-row has-pick is-${s.state}${other ? ' is-other-version' : ''}${picked ? ' is-picked' : ''}`}>
    <input type="checkbox" className="source-pick" checked={picked} onChange={e => onPick(e.target.checked)} aria-label={t('Select {title}', { title: source.title })} />
    <div className="source-main">
      {other && <span className="version-note">{t('Another version of the record above: {version}. It follows the record’s selection; passages cited from it are labelled with this version.', { version: versionText(source.version_label) })}</span>}
      <strong className="source-title"><SourceKey value={source.source_key} /><span>{source.title}</span></strong>
      {byline || source.venue || venueLine.length ? <div className="source-byline">
        {byline && <span>{byline}</span>}
        {(source.venue || venueLine.length > 0) && <span>{source.venue && <em>{source.venue}</em>}{source.venue && venueLine.length > 0 && ' · '}{venueLine.join(' · ')}</span>}
      </div> : <div className="source-byline"><span>{t(source.origin === 'user_upload' ? 'Uploaded PDF' : 'No bibliographic details from the provider')}</span></div>}
      <div className="source-status">
        {source.version_label && <span className={`source-fact is-${versionTones[source.version_label] ?? 'unstated'}`}>{versionText(source.version_label)}</span>}
        {accessParts(source).map(part => <span key={part.text} className={`source-fact is-${part.tone}`}>{part.text}</span>)}
        {readsVersion && <Tooltip content={t('This record has no PDF text, so answers read the PDF of {version} below. Passages cited from it are labelled with that version; the two are not counted as separate sources.', { version: versionText(readsVersion.version_label) })}><span className="source-fact is-plain" tabIndex={0}>{t('answers read {version}', { version: versionText(readsVersion.version_label) })}</span></Tooltip>}
        {source.cited_in_latest_answer && <span className="source-fact is-cited">{t('cited in the latest answer')}</span>}
        {source.similarity !== null && <Tooltip content={t(source.access.abstract_passage_id ? 'Embedding similarity between the research question and this source’s title and stored abstract. Used for ordering only; it is not a relevance judgment.' : 'Embedding similarity between the research question and this source’s title. No abstract was available. Used for ordering only; it is not a relevance judgment.')}><span className="source-fact is-similarity" tabIndex={0}>{t('Similarity {score}', { score: source.similarity.toLocaleString(uiLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }) })}</span></Tooltip>}
        {source.provider_records.length > 0 && <span className="source-fact is-plain">{t('Found in {providers}', { providers: source.provider_records.map(providerName).join(', ') })}</span>}
      </div>
      {source.applicability === 'stale_scope' && <p className="proposal is-stale">{t(s.proposal ? 'Found for question revision {n}; the proposal below was made for that question. Search again to screen it for the current question.' : 'Found for question revision {n}. Search again to screen it for the current question.', { n: source.found_in_revision ?? '?' })}</p>}
      {s.proposal && !other && <p className="proposal is-model"><span className="proposal-tag">{t('Model proposal:')}</span> <span><em className={`verdict is-${s.proposal}`}>{t(s.proposal)}</em> — {s.proposal_reason} <span>({t(s.proposal_basis?.replaceAll('_', ' ') ?? '')})</span>{s.origin === 'user' ? ` ${t('· overridden by you')}` : ''}</span></p>}
      {/* A selection the queue wrote reads as that answer; the backend names it from the stored link, never from the reason text. */}
      {s.origin === 'user' && (s.queue_answer || s.user_reason) && <p className="proposal" ref={reasonNote} tabIndex={-1}><UserPen size={13} aria-hidden />{s.queue_answer
        ? t('Your answer in the queue: {answer}', { answer: t(queueAnsweredText[s.queue_answer]) })
        : t('Your reason: {reason}', { reason: s.user_reason ?? '' })}</p>}
      {s.origin === 'user' && s.state === 'excluded' && !s.user_reason && <ReasonForm busy={busy} focusOnOpen={askedReason} onSave={reason => { setAskedReason(null); onReason(reason); focusWhenLost(() => reasonNote.current) }} />}
      {finding && <PdfSearchStatus />}
      {source.access.assets.map(asset => asset.rejected_extraction && !asset.rejected_extraction.extraction_version.includes('+reextract-') && <p key={asset.id} className="proposal"><ScanText size={13} aria-hidden />{t('A later text extraction ({version}) was not used: {reason}. The earlier text stays in use.', { version: asset.rejected_extraction.extraction_version, reason: asset.rejected_extraction.rejection_reason })}</p>)}
      {source.access.assets.map(asset => <TextRecovery key={asset.id} asset={asset} sourceId={source.source_version_id} />)}
      {[...ocrOffers.entries()].map(([assetId, offer]) => offer && <OcrNote key={assetId} offer={offer} />)}
      {source.access.replaced_assets.length > 0 && <p className="proposal"><Replace size={13} aria-hidden />{t(source.access.replaced_assets[0].original_filename ? 'Previous file {file} replaced on {date}. Evidence that cites it still opens it.' : 'Previous PDF replaced on {date}. Evidence that cites it still opens it.', { file: source.access.replaced_assets[0].original_filename ?? '', date: new Date(source.access.replaced_assets[0].removed_at).toLocaleDateString(uiLocale(), { dateStyle: 'medium' }) })}</p>}
      <div className="source-foot">
        {!finding && discoveries.length > 0 && <details className="source-provenance">
          <summary><ChevronRight size={14} className="source-provenance-chev" aria-hidden /><strong>{t(source.access.assets.length ? 'PDF attached' : 'No usable PDF found')}</strong><span>{lookupSummary}</span></summary>
          <PdfLookupTable source={source} busy={busy} onAttachCandidate={onAttachCandidate} />
        </details>}
        <div className="source-links">
          {source.access.assets.map(asset => <span className="source-asset-actions" key={asset.id}>
            <button type="button" className="is-primary" onClick={() => onOpenPdf(asset.id)} title={asset.original_filename ?? undefined}><FileText size={14} aria-hidden />{t('Open PDF')}</button>
            <button disabled={busy} onClick={() => onReplaceAsset(asset.id)} title={t('Use another file for this source version; evidence that cites the current file keeps it')}><Replace size={14} aria-hidden />{t('Replace PDF')}</button>
            {asset.current_extraction === false && <button disabled={busy} onClick={() => onReextract(asset.id)} title={t('Text extracted as {version}. Extract it again with the current extractor.', { version: asset.extraction_version ?? '?' })}><ScanText size={14} aria-hidden />{t('Extract text again')}</button>}
            {asset.equations?.state === 'failed' && <button disabled={busy} onClick={() => onRereadEquations(asset.id)} title={asset.equations.reason ?? undefined}><Sigma size={14} aria-hidden />{t('Read equations again')}</button>}
            {ocrOffers.get(asset.id) && <OcrButton offer={ocrOffers.get(asset.id)!} busy={busy} onRead={() => ocr.onRead(source, asset.id)} />}
            <button className="is-destructive" disabled={busy} onClick={() => onRemoveAsset(asset.id)} title={asset.original_filename ?? undefined}><Trash2 size={14} aria-hidden />{t('Remove PDF')}</button>
          </span>)}
          {source.access.abstract_passage_id && <button className={primaryAction === 'abstract' ? 'is-primary' : undefined} onClick={onAbstract}><BookOpenText size={14} aria-hidden />{t('Read abstract')}</button>}
          {source.doi && <a href={`https://doi.org/${source.doi}`} target="_blank" rel="noreferrer"><ConnectionIcon id="doi" />DOI</a>}
          {source.doi && <button disabled={busy || finding} onClick={onDiscoverPdf}><Search size={14} aria-hidden />{finding ? <span className="shimmer-text">{t('Web Search is running…')}</span> : t(source.access.assets.length ? 'Refresh metadata' : 'Find PDF')}</button>}
          {!source.access.assets.length && <button disabled={busy || finding} onClick={onAttachPdf}><FileUp size={14} aria-hidden />{t('Attach PDF')}</button>}
          <button disabled={busy} onClick={onRemoveFromResearch} title={t('Take this source out of this research; the library record, its PDF and earlier quotes stay')}><ListMinus size={14} aria-hidden />{t('Remove from research')}</button>
        </div>
      </div>
    </div>
    {!other && <div className="selection-toggle" role="group" aria-label={t('Selection for {title}', { title: source.title })}>
      {(['included', 'pending', 'excluded'] as const).map(state => <button key={state} className={`is-${state}`} aria-pressed={s.state === state} disabled={busy || s.state === state} onClick={e => { setAskedReason(state === 'excluded' ? e.currentTarget : null); onSelect(state) }}>{t(state === 'included' ? 'Include' : state === 'excluded' ? 'Exclude' : 'Undecided')}</button>)}
    </div>}
  </div>
}

// One row per lookup service: its checks collapse into a try count, and the files it offered sit in its row.
function PdfLookupTable({ source, busy, onAttachCandidate }: { source: Source; busy: boolean; onAttachCandidate: (candidateId: string) => void }) {
  const discoveries = source.access.pdf_discoveries
  const candidates = source.access.pdf_candidates
  const providers = [...new Set([...discoveries.map(d => d.provider), ...candidates.map(c => c.provider)])]
  return <div className="pdf-lookup-wrap"><table className="pdf-lookup">
    <thead><tr><th scope="col">{t('Service')}</th><th scope="col">{t('Result')}</th><th scope="col">{t('Checks')}</th><th scope="col">{t('Detail')}</th></tr></thead>
    <tbody>{providers.map(provider => {
      const checks = discoveries.filter(d => d.provider === provider)
      const files = candidates.filter(c => c.provider === provider)
      const last = checks[checks.length - 1]
      const result = files.some(c => c.access_status === 'downloaded') ? { tone: 'ok', text: t('PDF retrieved') }
        : files.length ? { tone: 'warn', text: t(files.length === 1 ? '{n} file not usable' : '{n} files not usable', { n: files.length }) }
        : last?.status === 'zero_results' ? { tone: '', text: t('No match') }
        : last?.status === 'completed' ? { tone: '', text: t('completed') }
        : { tone: 'bad', text: t((last?.status ?? 'failed').replaceAll('_', ' ')) }
      const otherTitles = Math.max(0, ...checks.map(d => d.other_title_count ?? 0))
      const notes = [...new Set(checks.filter(d => !['completed', 'zero_results'].includes(d.status)).map(d => serviceErrorSentence({ kind: serviceKind(d.error_code ?? d.status, d.http_status), service: providerName(provider), resetAt: d.retry_after, effect: 'lookup' }) + (d.http_status ? ` · HTTP ${d.http_status}` : '')).filter(Boolean))]
      if (otherTitles) notes.unshift(t(otherTitles === 1 ? '{n} result under another title, not kept' : '{n} results under other titles, not kept', { n: otherTitles }))
      return <tr key={provider}>
        <td className="pdf-lookup-service"><ConnectionIcon id={provider} />{providerName(provider)}</td>
        <td className={result.tone && `is-${result.tone}`}>{result.text}</td>
        <td className="pdf-lookup-count">{checks.length}</td>
        <td>{files.length ? files.map(candidate => <span className="pdf-lookup-file" key={candidate.id}>
          {t(candidate.version_status === 'match' ? 'version verified' : candidate.version_status === 'different' ? 'different version' : 'version uncertain')} · {candidate.access_status === 'http_error' ? `HTTP ${candidate.http_status ?? '?'}` : t(candidate.access_status.replace('_', ' '))}{candidate.identity_status === 'unverified' && ` · ${t('title does not match')}`}{' · '}<a href={candidate.candidate_url} target="_blank" rel="noreferrer">{t('Open file')}</a>{candidate.version_status === 'uncertain' && candidate.provider !== 'europepmc' && (candidate.identity_status === 'doi_verified' || candidate.identity_status === 'title_verified') && !source.access.assets.length && <>{' · '}<button disabled={busy} onClick={() => onAttachCandidate(candidate.id)} title={t('Open the file first and check that it is this version of the work, not a preprint or another edition. An attached file’s pages can be cited in answers.')}>{t('Same version, attach')}</button></>}
        </span>) : notes.join('; ')}</td>
      </tr>
    })}</tbody>
  </table></div>
}
