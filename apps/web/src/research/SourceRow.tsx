import { useMemo, useState } from 'react'
import { BookOpenText, ChevronRight, FileText, FileUp, Link2, LoaderCircle, Replace, ScanText, Search, Sigma, Trash2, UserPen } from 'lucide-react'
import { Tooltip } from '@/components/ui/tooltip'
import { type Source } from '../api'
import { serviceErrorSentence, serviceKind, accessParts, rereadEquationsLabel, citedText, providerName, retractionNote, queueAnsweredText, versionText, versionTones } from '../labels'
import { TextRecovery } from '../TextRecovery'
import { Elapsed } from '../EvidenceTable'
import { ConnectionIcon } from '../connectionIcons'
import { ocrOffer } from '../ocr'
import { OcrButton, OcrNote } from '../OcrNote'
import { t, uiLocale } from '../i18n'
import { SourceKey } from '../SourceKey'
import type { OcrContext } from './shared'
import { proposalOf } from './sourceProposal'

// The PDF lookup is one request, so this names the services it checks without claiming which one is running.
const PDF_LOOKUP_SERVICES = ['unpaywall', 'openalex', 'crossref']
function PdfSearchStatus() {
  const [since] = useState(() => new Date().toISOString())
  return <p className="pdf-search-status" role="status">
    <span className="sr-only">{t('Checking Unpaywall, OpenAlex and Crossref; Web Search will run if no verified PDF is retrieved…')}</span>
    <span className="pdf-search-head" aria-hidden>
      <LoaderCircle size={14} className="pdf-search-spin" />
      <strong>{t('Finding PDF')}</strong>
      <span className="pdf-search-services" title={PDF_LOOKUP_SERVICES.map(providerName).join(', ')}>{PDF_LOOKUP_SERVICES.map(id => <ConnectionIcon key={id} id={id} />)}</span>
      <Elapsed since={since} />
    </span>
    <span className="pdf-search-detail" aria-hidden>
      <span className="pdf-search-muted">{t('{n} open-access services', { n: PDF_LOOKUP_SERVICES.length })}</span>
      <span className="pdf-search-sep" />
      <span className="pdf-search-muted"><ConnectionIcon id="web_search" />{t('Web Search if needed')}</span>
    </span>
    <span className="runchip-sweep" aria-hidden />
  </p>
}

export type RowActions = { onRemoveFromResearch: () => void; onSelect: (state: Source['selection']['state']) => void; onAskReason: () => void; onOpen: () => void; onAbstract: () => void; onDiscoverPdf: () => void; onAttachPdf: () => void; onAttachCandidate: (candidateId: string) => void; onOpenPdf: (assetId: string) => void; onPlainText: (assetId: string) => void; onRemoveAsset: (assetId: string) => void; onReplaceAsset: (assetId: string) => void; onReextract: (assetId: string) => void; onRereadEquations: (assetId: string) => void }

// One line of the Sources table (mockup P9): checkbox, the source cell (title, meta, pills, notes, row actions), the
// model's proposal and the person's decision. Another version of a work follows its record's line and has no proposal or
// decision of its own. `citedClaims`: how many claims of the shown answer (V`answerVersion`) cite this version.
export function SourceRow({ source, busy, picked, onPick, readsVersion, citedClaims, answerVersion, finding, ocr, asking, ...a }: { source: Source; busy: boolean; picked: boolean; onPick: (on: boolean) => void; readsVersion?: Source; citedClaims: number; answerVersion: number | null; finding: boolean; ocr: OcrContext; asking: boolean } & RowActions) {
  const s = source.selection
  const other = source.version_role === 'other_version'
  const citationDetails = [source.volume && t('vol. {value}', { value: source.volume }), source.issue && t('no. {value}', { value: source.issue }), source.pages && t('pp. {value}', { value: source.pages })].filter(Boolean).join(', ')
  // The citation count keeps its provider, as everywhere else (OpenAlex counts it; it is metadata, not quality).
  const venueLine = [source.venue, source.year, citationDetails, citedText(source.cited_by_count)].filter(Boolean)
  const authors = source.authors.join(', ')
  const retraction = retractionNote(source)
  const discoveries = source.access.pdf_discoveries
  const candidates = source.access.pdf_candidates
  const unusable = candidates.filter(c => c.access_status !== 'downloaded').length
  const lookupSummary = [t('{p} services · {n} checks', { p: new Set(discoveries.map(d => d.provider)).size, n: discoveries.length }), unusable && t(unusable === 1 ? '{n} file not usable' : '{n} files not usable', { n: unusable })].filter(Boolean).join(' · ')
  const ocrOffers = new Map(source.access.assets.map(asset => [asset.id, ocrOffer(asset, ocr.tool, ocr.runs)]))
  // Where each PDF's "Retry text extraction" lands in the row actions (S12 left it to the Sources rows).
  const [slots, setSlots] = useState<Record<string, HTMLElement | null>>({})
  // One stable ref callback per PDF: a new callback each render would detach and attach the slot on every render.
  const assetIds = source.access.assets.map(asset => asset.id).join(' ')
  const slotRefs = useMemo(() => Object.fromEntries(assetIds.split(' ').filter(Boolean).map(id => [id,
    (node: HTMLSpanElement | null) => setSlots(current => current[id] === node ? current : { ...current, [id]: node })])), [assetIds])
  const proposal = other ? null : proposalOf(source)
  const opens = Boolean(source.access.assets.length || source.access.abstract_passage_id)
  return <tr className={`source-row is-${s.state}${other ? ' is-other-version' : ''}${picked ? ' is-picked sel' : ''}`}>
    <td className="cb"><input type="checkbox" checked={picked} onChange={e => onPick(e.target.checked)} aria-label={t('Select {title}', { title: source.title })} /></td>
    <td className="source-cell">
      {other && <span className="version-note">{t('Another version of the record above: {version}. It follows the record’s selection; passages cited from it are labelled with this version.', { version: versionText(source.version_label) })}</span>}
      <strong className="source-title"><SourceKey value={source.source_key} />{opens
        ? <button type="button" className="src-t" onClick={a.onOpen}>{source.title}</button>
        : <span className="src-t">{source.title}</span>}</strong>
      <div className="src-m source-byline">
        {authors || venueLine.length ? <>{authors && <span>{authors}</span>}{venueLine.length > 0 && <span>{venueLine.join(' · ')}</span>}</>
          : <span>{t(source.origin === 'user_upload' ? 'Uploaded PDF' : 'No bibliographic details from the provider')}</span>}
      </div>
      <div className="pills source-status">
        {retraction && <Tooltip content={retraction}><span className="pill source-fact is-retracted" tabIndex={0}>{t('Retracted')}</span></Tooltip>}
        {source.doi && <span className="pill source-fact is-plain"><Link2 size={12} aria-hidden />DOI</span>}
        {source.version_label && <span className={`pill source-fact is-${versionTones[source.version_label] ?? 'unstated'}`}>{versionText(source.version_label)}</span>}
        {accessParts(source).map(part => <span key={part.text} className={`pill source-fact is-${part.tone}`}>{part.text}</span>)}
        {readsVersion && <Tooltip content={t('This record has no PDF text, so answers read the PDF of {version} below. Passages cited from it are labelled with that version; the two are not counted as separate sources.', { version: versionText(readsVersion.version_label) })}><span className="pill source-fact is-plain" tabIndex={0}>{t('answers read {version}', { version: versionText(readsVersion.version_label) })}</span></Tooltip>}
        {citedClaims > 0 && answerVersion !== null && <span className="pill source-fact is-cited">{t(citedClaims === 1 ? 'cited in {n} claim of V{v}' : 'cited in {n} claims of V{v}', { n: citedClaims, v: answerVersion })}</span>}
        {(source.rank !== null || source.similarity !== null) && <Tooltip content={t(source.similarity === null ? 'Its best position in the search results that found it. Used for ordering only; it is not a relevance judgment.' : source.access.abstract_passage_id ? 'Search rank: its best position in the search results that found it. Similarity: embedding similarity between the research question and this source’s title and stored abstract. Both are used for ordering only; neither is a relevance judgment.' : 'Search rank: its best position in the search results that found it. Similarity: embedding similarity between the research question and this source’s title; no abstract was available. Both are used for ordering only; neither is a relevance judgment.')}>
          <span className="pill source-fact is-similarity tnum" tabIndex={0}>{[source.rank !== null && t('search rank {n}', { n: source.rank }), source.similarity !== null && t('similarity {score}', { score: source.similarity.toLocaleString(uiLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }) })].filter(Boolean).join(' · ')}</span>
        </Tooltip>}
      </div>
      {source.applicability === 'stale_scope' && <p className="proposal is-stale">{t(proposal && proposal.tone !== 'none' ? 'Found for question revision {n}; the proposal beside it was made for that question. Search again to screen it for the current question.' : 'Found for question revision {n}. Search again to screen it for the current question.', { n: source.found_in_revision ?? '?' })}</p>}
      {finding && <PdfSearchStatus />}
      {source.access.assets.map(asset => asset.rejected_extraction && !asset.rejected_extraction.extraction_version.includes('+reextract-') && <p key={asset.id} className="proposal"><ScanText size={13} aria-hidden />{t('A later text extraction ({version}) was not used: {reason}. The earlier text stays in use.', { version: asset.rejected_extraction.extraction_version, reason: asset.rejected_extraction.rejection_reason })}</p>)}
      {source.access.assets.map(asset => <TextRecovery key={asset.id} asset={asset} sourceId={source.source_version_id} actionSlot={slots[asset.id] ?? null} />)}
      {[...ocrOffers.entries()].map(([assetId, offer]) => offer && <OcrNote key={assetId} offer={offer} />)}
      {source.access.replaced_assets.length > 0 && <p className="proposal"><Replace size={13} aria-hidden />{t(source.access.replaced_assets[0].original_filename ? 'Previous file {file} replaced on {date}. Evidence that cites it still opens it.' : 'Previous PDF replaced on {date}. Evidence that cites it still opens it.', { file: source.access.replaced_assets[0].original_filename ?? '', date: new Date(source.access.replaced_assets[0].removed_at).toLocaleDateString(uiLocale(), { dateStyle: 'medium' }) })}</p>}
      {!finding && discoveries.length > 0 && <details className="source-provenance">
        <summary><ChevronRight size={14} className="source-provenance-chev" aria-hidden /><strong>{t(source.access.assets.length ? 'PDF attached' : 'No usable PDF found')}</strong><span>{lookupSummary}</span></summary>
        <PdfLookupTable source={source} busy={busy} onAttachCandidate={a.onAttachCandidate} />
      </details>}
      {/* Row actions (mockup .rowacts): with a PDF, Open PDF, Plain text and Replace PDF lead; without one, Find PDF, Attach PDF and Read abstract. The live PDF tools follow their file; Remove PDF is accent like the rest. */}
      <div className="rowacts source-links">
        {source.access.assets.map(asset => <span className="source-asset-actions" key={asset.id}>
          <button type="button" onClick={() => a.onOpenPdf(asset.id)} title={asset.original_filename ?? undefined}><FileText size={14} aria-hidden />{t('Open PDF')}</button>
          <button type="button" onClick={() => a.onPlainText(asset.id)}><BookOpenText size={14} aria-hidden />{t('Plain text')}</button>
          <button type="button" disabled={busy} onClick={() => a.onReplaceAsset(asset.id)} title={t('Use another file for this source version; evidence that cites the current file keeps it')}><FileUp size={14} aria-hidden />{t('Replace PDF')}</button>
          <button type="button" disabled={busy} onClick={() => a.onRemoveAsset(asset.id)} title={asset.original_filename ?? undefined}><Trash2 size={14} aria-hidden />{t('Remove PDF')}</button>
          {asset.current_extraction === false && <button type="button" disabled={busy} onClick={() => a.onReextract(asset.id)} title={t('Text extracted as {version}. Extract it again with the current extractor.', { version: asset.extraction_version ?? '?' })}><ScanText size={14} aria-hidden />{t('Extract text again')}</button>}
          {rereadEquationsLabel(asset.equations) && <button type="button" disabled={busy} onClick={() => a.onRereadEquations(asset.id)} title={asset.equations?.reason ?? undefined}><Sigma size={14} aria-hidden />{rereadEquationsLabel(asset.equations)}</button>}
          {ocrOffers.get(asset.id) && <OcrButton offer={ocrOffers.get(asset.id)!} busy={busy} onRead={() => ocr.onRead(source, asset.id)} />}
          <span className="rowact-slot" ref={slotRefs[asset.id]} />
        </span>)}
        {!source.access.assets.length && source.doi && <button type="button" disabled={busy || finding} onClick={a.onDiscoverPdf}><Search size={14} aria-hidden />{finding ? <span className="shimmer-text">{t('Web Search is running…')}</span> : t('Find PDF')}</button>}
        {!source.access.assets.length && <button type="button" disabled={busy || finding} onClick={a.onAttachPdf}><FileUp size={14} aria-hidden />{t('Attach PDF')}</button>}
        {source.access.abstract_passage_id && <button type="button" onClick={a.onAbstract}><BookOpenText size={14} aria-hidden />{t('Read abstract')}</button>}
        {source.doi && <a href={`https://doi.org/${source.doi}`} target="_blank" rel="noreferrer"><Link2 size={14} aria-hidden />DOI</a>}
        {source.access.assets.length > 0 && source.doi && <button type="button" disabled={busy || finding} onClick={a.onDiscoverPdf}><Search size={14} aria-hidden />{finding ? <span className="shimmer-text">{t('Web Search is running…')}</span> : t('Refresh metadata')}</button>}
        <button type="button" disabled={busy} onClick={a.onRemoveFromResearch} aria-label={t('Remove from research')} title={t('Take this source out of this research; the library record, its PDF and earlier quotes stay')}><Trash2 size={14} aria-hidden />{t('Remove')}</button>
      </div>
    </td>
    <td className="prop-cell">{proposal ? <div className={`prop is-${proposal.tone}`}>
      <b className={`verdict is-${proposal.tone}`}>{proposal.word}</b>{proposal.reason && <> · {proposal.reason}</>}
      {proposal.basis && <div className="src-m">{proposal.basis}</div>}
    </div> : !other && <div className="prop is-none"><b className="verdict is-none">{t('not screened')}</b></div>}</td>
    <td className="decision-cell">{!other && <>
      <div className="seg selection-toggle" role="group" aria-label={t('Selection for {title}', { title: source.title })}>
        {(['included', 'pending', 'excluded'] as const).map(state => <button key={state} type="button" className={`is-${state}`} aria-pressed={s.state === state} disabled={busy || s.state === state} onClick={() => a.onSelect(state)}>{t(state === 'included' ? 'Include' : state === 'excluded' ? 'Exclude' : 'Undecided')}</button>)}
      </div>
      {/* A selection the queue wrote reads as that answer; the backend names it from the stored link, never from the reason text. */}
      {s.origin === 'user' && s.queue_answer && <p className="reason" data-reason-for={source.source_version_id} tabIndex={-1}><UserPen size={13} aria-hidden />{t('Your answer in the queue: {answer}', { answer: t(queueAnsweredText[s.queue_answer]) })}</p>}
      {s.origin === 'user' && !s.queue_answer && s.user_reason && <p className="reason" data-reason-for={source.source_version_id} tabIndex={-1}><b>{t('Your reason:')}</b> {s.user_reason} {!asking && <button type="button" className="link" disabled={busy} onClick={a.onAskReason} aria-label={t('Edit your reason for {title}', { title: source.title })}>{t('Edit')}</button>}</p>}
      {s.origin === 'user' && s.state === 'excluded' && !s.user_reason && !s.queue_answer && !asking && <p className="reason"><button type="button" className="link" disabled={busy} onClick={a.onAskReason} aria-label={t('Add a reason for excluding {title}', { title: source.title })}>{t('Add a reason')}</button></p>}
    </>}</td>
  </tr>
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
