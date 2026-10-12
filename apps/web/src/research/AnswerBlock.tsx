import { useRef, useState } from 'react'
import { ArrowUpRight, BadgeCheck, BookOpenText, FileText, Info, ListMinus, ScanText, Sigma, Quote, ShieldCheck, Sparkles, Upload } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { type Answer, type Limitation, type Source, type ValidationIssue, type Verdict } from '../api'
import { locatorText, pauseReasonText, verdictLabels, versionText, versionTones } from '../labels'
import { LATE_REVISION_LABEL, LATE_REVISION_DETAIL, LATE_REVISION_PENDING } from '../labels'
import { MathText } from '../MathText'
import { ReviewSummary } from '../review/ReviewSummary'
import { useReviewList } from '../review/useReviewList'
import { useToast } from '../Toast'
import { ModelName } from '../ModelName'
import { useModelText } from '../modelText'
import { Option } from '../Home'
import { citationStyles, formatReference, type CitationStyle } from '../citations'
import { OCR_LABEL } from '../ocr'
import { t } from '../i18n'
import { SourceKey } from '../SourceKey'
import { Notice } from '../Notice'
import { AnswerFlowNote } from '../FlowReport'
import { MethodBox } from '../MethodBox'
import { ExportLinks } from './ExportMenu'
import { ReportSheet } from './ReportSheet'
import { downloadReportMarkdown, reportMarkdown, reportParts } from './reportMarkdown'

async function writeClipboard(text: string) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text)
  const field = document.createElement('textarea')
  field.value = text
  field.style.position = 'fixed'
  field.style.opacity = '0'
  document.body.appendChild(field)
  field.select()
  const copied = document.execCommand('copy')
  field.remove()
  if (!copied) throw new Error('copy failed')
}

export function AnswerBlock({ researchId, title, version, answer, sources, busy, dark, reportOpen, onReportOpenChange, showCard = true, onOpen, onAttachPdf, eventCursor, runActive }: { researchId: string; title: string; version: number; answer: Answer; sources: Source[]; busy: boolean; dark: boolean; reportOpen: boolean; onReportOpenChange: (open: boolean) => void; showCard?: boolean; onOpen: (passageId: string, highlightText: string | null) => void; onAttachPdf: (source: Source) => void; eventCursor: number; runActive: boolean }) {
  const modelText = useModelText()
  const [style, setStyle] = useState<CitationStyle>(() => { try { const saved = localStorage.getItem('deixis-citation-style'); return saved && Object.keys(citationStyles).includes(saved) ? saved as CitationStyle : 'apa' } catch { return 'apa' } })
  const [copied, setCopied] = useState(false)
  const toast = useToast()
  const [reviewMode, setReviewMode] = useState(false)
  const [requestReview, setRequestReview] = useState(false)
  const reviewList = useReviewList(researchId, 'answer', answer.id, eventCursor, answer.status === 'structurally_valid')
  const reviewsButton = useRef<HTMLButtonElement>(null), scrollRoot = useRef<HTMLDivElement>(null), documentScroll = useRef(0)
  const mode = (on: boolean, request = false) => {
    if (on && !reviewMode) documentScroll.current = scrollRoot.current?.scrollTop ?? 0
    setReviewMode(on); setRequestReview(request)
    requestAnimationFrame(() => {
      if (scrollRoot.current) scrollRoot.current.scrollTop = on ? 0 : documentScroll.current
      if (!on) reviewsButton.current?.focus({ preventScroll: true })
    })
  }
  const openReviews = (request = false) => { mode(true, request); onReportOpenChange(true) }
  const chooseStyle = (next: CitationStyle) => { setStyle(next); try { localStorage.setItem('deixis-citation-style', next) } catch { /* the choice still applies for this tab */ } }
  const latePending = showCard && answer.late_revision_status && ['waiting_fetch', 'reading', 'answering'].includes(answer.late_revision_status.status)
    ? <p className="legacy-mini-note" role="status">{t(LATE_REVISION_PENDING)}</p> : null
  if (answer.status === 'clarification' && answer.clarification) {
    return <div className="legacy-answer"><div className="section-label">{t('Clarification needed')}</div><h2>{answer.clarification.question}</h2><p>{answer.clarification.why_it_matters}</p>{answer.clarification.options.length > 0 && <ul className="plain-list">{answer.clarification.options.map(o => <li key={o}>{o}</li>)}</ul>}<p className="legacy-mini-note">{t('Revise the question above to continue.')}</p></div>
  }
  if (answer.status === 'no_evidence' && answer.validation.reason === 'no_includable_source') {
    return <><Notice tone="attention">{t('No work was included at full text when this answer started, so no answer was written and no model was asked. The line below says where the works stand.')}</Notice><AnswerFlowNote answer={answer} /></>
  }
  if (answer.status === 'no_evidence') {
    return <><Notice tone="attention">{t('No text passages were available for the included sources (no abstract, no retrievable PDF text). No answer was generated.')}</Notice><AnswerFlowNote answer={answer} />{latePending}</>
  }
  if (answer.status === 'unverified_draft') {
    return <div className="legacy-answer"><Notice tone="error">{t('The model output failed validation after one repair attempt, so it is not shown as a cited answer.')}<ul className="plain-list">{answer.validation.issues?.map(i => <li key={`${i.code}${i.path}`}>{t('{code} at {path}', { code: i.code, path: i.path })}</li>)}</ul></Notice>
      {answer.unverified_draft?.claims?.map(c => <p className="claim is-unverified" key={c.claim_label}><MathText text={c.text} /></p>)}<AnswerFlowNote answer={answer} />{latePending}</div>
  }
  const { refs, citeLabel, sections, suggestion, limits } = reportParts(answer, sources)
  const markdown = () => reportMarkdown(answer, sources, title, version, style)
  const copyReport = async () => {
    try { await writeClipboard(markdown()); setCopied(true); toast('success', t('Report copied to clipboard.')) }
    catch { toast('error', t('Could not copy the report.')) }
  }
  const downloadReport = () => downloadReportMarkdown(answer, sources, title, version, style)
  const preview = answer.claims.slice(0, 2).map(claim => claim.text).join(' ')
  const report = <div className="legacy-answer report-content">
    <div className="section-label">{t('Source-linked answer')}{answer.applicability === 'stale_scope' ? ` · ${t('earlier question revision')}` : answer.applicability === 'stale_selection' ? ` · ${t('earlier source selection')}` : ''}</div>
    {answer.late_revision && <p className="legacy-mini-note"><span className="support-badge">{t(LATE_REVISION_LABEL)}</span> {answer.late_revision.base_report_version !== null && t(LATE_REVISION_DETAIL, { n: answer.late_revision.upgraded_sources, v: answer.late_revision.base_report_version })}</p>}
    {answer.applicability === 'stale_scope' && <Notice tone="attention">{t('This answer was produced for revision {n} of the question and is not applied to the current revision.', { n: answer.scope_revision })}</Notice>}
    {answer.applicability === 'stale_selection' && <Notice tone="attention">{t('Your source selection changed after this answer was generated. It is kept, but it may cite sources you have since excluded or miss ones you added.')}</Notice>}
    {answer.source_text_changed && <Notice tone="attention">{t('A PDF this answer read was replaced, removed or had its text extracted again after the answer was generated. Its quotes still open the text that was read; generate a new answer to read the current text.')}</Notice>}
    {answer.capability_notice && <Notice tone="info">{answer.capability_notice}</Notice>}
    {/* A section is one paragraph led by its main point in bold, as the answer method asks (D230); its label names a topic, not a finding. */}
    {sections.map(({ heading, claims }, index) => <section className="answer-section" key={index}><p className="answer-paragraph">
      {heading && <strong className="answer-lead">{heading}</strong>}
      {claims.map(claim => <span className="claim" key={claim.id}>
        <MathText text={claim.text} />{claim.support_type === 'analyst_inference' && <span className="support-badge">{t('interpretation')}</span>}
        {claim.evidence_basis === 'abstract' && <span className="support-badge">{t('From abstract')}</span>}
        {claim.evidence.map(e => <button key={e.passage_id} className="cite-chip" title={[e.title, versionText(e.version_label), locatorText(e), e.text_source === 'ocr' && t(OCR_LABEL), e.text_source === 'latex_source' && t('arXiv source'), e.removed_from_research && t('Removed from this research')].filter(Boolean).join(' · ')} onClick={() => onOpen(e.passage_id, e.anchor_text)}>{e.source_key ? citeLabel(claim, e) : `[${refs.get(e.passage_id)?.n}]`}{e.text_source === 'latex_source' && <span className="cite-chip-origin"><Sigma size={10} aria-hidden /><span className="sr-only">{t('arXiv source')}</span></span>}</button>)}
        {claim.review && <span className={`review-badge is-${claim.review.verdict}`} title={t('Reviewer: {reason}', { reason: claim.review.reason })}><ShieldCheck size={11} aria-hidden />{t(verdictLabels[claim.review.verdict])}</span>}
        {claim.review && claim.review.verdict !== 'supported' && <small className="review-reason">{t('Reviewer: {reason}', { reason: claim.review.reason })}</small>}
      </span>)}
    </p></section>)}
    {!answer.claims.length && <p>{t('No claim could be linked to the passages given to the model.')}</p>}
    {answer.unanswered_aspects.length > 0 && <><h3>{t('Not answered by the inspected passages')}</h3><ul className="plain-list">{answer.unanswered_aspects.map(a => <li key={a}><MathText text={a} /></li>)}</ul></>}
    {limits.length > 0 && <><h3>{t('Limits')}</h3><ul className="plain-list">{limits.map((l, i) => <li key={i}><em>{t(l.kind.replace('_', ' '))}:</em> <MathText text={l.text} /></li>)}</ul></>}
    {refs.size > 0 && <>
      <div className="reference-head"><h3>{t('Cited passages')}</h3>
        <div className="reference-tools"><ExportLinks researchId={researchId} sources="cited" />
        <Select value={style} onValueChange={value => { if (value) chooseStyle(value as CitationStyle) }}>
          <SelectTrigger aria-label={t('Citation style')} title={t('How the cited sources are written')}><SelectValue>{(value: string) => <><Quote size={14} />{t(citationStyles[value as CitationStyle].label)}</>}</SelectValue></SelectTrigger>
          <SelectContent className="intake-select-content has-details" align="end" alignItemWithTrigger={false}>
            <div className="intake-select-heading" aria-hidden="true">{t('Citation style')}</div>
            {(Object.keys(citationStyles) as CitationStyle[]).map(k => <SelectItem key={k} value={k}><Option icon={Quote} title={t(citationStyles[k].label)} detail={t(citationStyles[k].detail)} /></SelectItem>)}
          </SelectContent>
        </Select></div>
      </div>
      <ol className="reference-list">{[...refs.values()].map(({ n, e }) => {
        const source = sources.find(s => s.source_version_id === e.source_version_id)
        const locator = locatorText(e)
        return <li key={e.passage_id}><button onClick={() => onOpen(e.passage_id, e.anchor_text)}>
          {e.source_key ? <SourceKey value={e.source_key} className="ref-key" /> : <span className="ref-num">[{n}]</span>}
          <span className="ref-body">
            <span className="ref-text">{source ? formatReference(style, source) : e.title}</span>
            <span className="ref-pills">
              <span className={`ref-pill ${e.kind === 'abstract' ? 'is-abstract' : 'is-text'}`}>{e.kind === 'abstract' ? <BookOpenText size={12} aria-hidden /> : <FileText size={12} aria-hidden />}{locator.charAt(0).toUpperCase() + locator.slice(1)}</span>
              <span className={`ref-pill is-${versionTones[e.version_label ?? ''] ?? 'unstated'}`}><BadgeCheck size={12} aria-hidden />{versionText(e.version_label)}</span>
              {e.text_source === 'ocr' && <span className="ref-pill is-ocr"><ScanText size={12} aria-hidden />{t(OCR_LABEL)}</span>}
              {e.text_source === 'latex_source' && <span className="ref-pill is-text"><Sigma size={12} aria-hidden />{t('arXiv source')}</span>}
              {e.removed_from_research && <span className="ref-pill is-removed"><ListMinus size={12} aria-hidden />{t('Removed from this research')}</span>}
            </span>
          </span>
        </button></li>
      })}</ol>
    </>}
    {answer.status === 'structurally_valid' && answer.start_snapshot !== undefined && <MethodBox key={answer.id} researchId={researchId} answerId={answer.id} />}
    <p className="legacy-mini-note">{t('Structural check passed: each citation resolves to a stored passage that was given to this step. Semantic support is not checked.')} {answer.model && <>{t('Model')}: <ModelName connection={answer.model.connection} text={modelText(answer.model.resolved_model ?? answer.model.requested_model ?? t('unknown'))} />.</>} {answer.inputs_given ? t('{passages} passages from {sources} sources were provided.', { passages: answer.inputs_given.passages, sources: answer.inputs_given.sources }) : ''}</p>
    <AnswerFlowNote answer={answer} />
    <ReviewNote review={answer.review} />
    <ChecksNote warnings={answer.validation.warnings} />
    {suggestion && <PdfSuggestions notes={suggestion.notes} sources={suggestion.sources} busy={busy} onAttachPdf={onAttachPdf} />}
  </div>
  return <>
    {/* The "Cited" count above the tabs scrolls here: the answer card is where the citations live. */}
    {showCard && <button type="button" id="research-answer" className="report-artifact" onClick={() => onReportOpenChange(true)} aria-label={t('Open report: {title}', { title })}>
      <span className="report-artifact-preview" aria-hidden="true"><strong>{title}</strong><span>{preview}</span></span>
      <span className="report-artifact-copy">
        <span className="report-artifact-meta"><Sparkles size={13} strokeWidth={1.8} aria-hidden />{t('Report')} · V{version}{answer.late_revision ? ` · ${t(LATE_REVISION_LABEL)}` : ''}</span>
        <strong>{title}</strong>
      </span>
      <span className="report-artifact-open" aria-hidden="true"><ArrowUpRight size={16} /></span>
    </button>}
    {showCard && <AnswerFlowNote answer={answer} />}
    {latePending}
    {showCard && <><ReviewSummary reviews={reviewList.reviews} open={() => openReviews()} /><button type="button" className="review-entry" onClick={() => openReviews(true)}>{t('Review with another model')}</button></>}
    <ReportSheet open={reportOpen} onOpenChange={open => { onReportOpenChange(open); if (!open) { setCopied(false); setReviewMode(false); setRequestReview(false) } }} dark={dark} title={title} version={version} researchId={researchId} answer={answer} sources={sources}
      eventCursor={eventCursor} runActive={runActive} reviewMode={reviewMode} requestReview={requestReview} copied={copied} reviewCount={reviewList.reviews.length} reviewsButton={reviewsButton} scrollRoot={scrollRoot}
      onToggleReviews={() => mode(!reviewMode)} onCopy={() => { void copyReport() }} onDownload={downloadReport} onOpenPassage={onOpen} onReviewsChanged={async () => { await reviewList.refresh() }}>
      {report}
    </ReportSheet>
  </>
}

// Sources the answer could read only from their abstracts and that still have no PDF. The model's access limitations name
// them and say what their full text would settle; an answer without such a limitation lists its cited sources that lack a PDF.
function PdfSuggestions({ notes, sources, busy, onAttachPdf }: { notes: Limitation[]; sources: Source[]; busy: boolean; onAttachPdf: (source: Source) => void }) {
  const tip = t('Sources the answer read only from their abstracts and that have no PDF yet. An attached PDF is read page by page (no OCR).')
  return <section className="pdf-suggest" aria-labelledby="pdf-suggest-title">
    <div className="pdf-suggest-head">
      <Upload size={18} aria-hidden />
      <div>
        <strong id="pdf-suggest-title">{t('PDF uploads suggested')}<span className="pdf-suggest-info" title={tip}><Info size={14} aria-hidden /><span className="sr-only">{tip}</span></span></strong>
        <small>{t('Attached PDFs stay with this research; generate a new answer to use their text.')}</small>
      </div>
    </div>
    <div className="pdf-suggest-body">
      {notes.length ? notes.map((l, i) => <p key={i}><MathText text={l.text} /></p>)
        : <p>{t('The answer cited these sources from their abstracts only. Their full text can add details the abstracts leave out.')}</p>}
      <ul className="pdf-suggest-list">{sources.map(source => {
        const href = source.doi ? `https://doi.org/${source.doi}` : source.landing_url
        return <li key={source.source_version_id}>
          <SourceKey value={source.source_key} />
          <span className="pdf-suggest-title" title={source.title}>{source.title}</span>
          <span className="pdf-suggest-actions">
            {href && <a href={href} target="_blank" rel="noreferrer" title={t('Opens the source page in a new tab')}><ArrowUpRight size={14} aria-hidden />{t('Get PDF')}</a>}
            <button type="button" disabled={busy} onClick={() => onAttachPdf(source)} aria-label={t('Attach a PDF to {title}', { title: source.title })}><Upload size={14} aria-hidden />{t('Attach PDF')}</button>
          </span>
        </li>
      })}</ul>
    </div>
  </section>
}

const phrasingCodes = new Set(['sentence_without_phrasebank_frame', 'own_work_phrase_in_claim', 'plural_sources_for_one_source'])
const mathLabels: Record<string, string> = {
  math_not_well_formed: 'Math is not well formed',
  math_without_full_text: 'Math cites abstract text only',
  ocr_numbers_unchecked: 'Number or equation read only from OCR text',
  anchor_not_in_passage: 'Citation opens without a highlight',
  missing_citation_anchor: 'Citation opens without a highlight',
  citation_anchor_salvaged: 'Citation cleanup removed an anchor, link or claim without a located citation',
}
const checkCodes = new Set([...phrasingCodes, ...Object.keys(mathLabels)])

// Prose and math findings are listed with the answer; they never reject it (D19).
function ChecksNote({ warnings }: { warnings?: ValidationIssue[] }) {
  const found = (warnings ?? []).filter(w => checkCodes.has(w.code))
  if (!found.length) return null
  const phrasingOnly = found.every(w => phrasingCodes.has(w.code))
  const summary = phrasingOnly
    ? (found.length === 1 ? 'Phrasing check: {n} finding. It does not reject the answer.' : 'Phrasing check: {n} findings. They do not reject the answer.')
    : (found.length === 1 ? 'Answer checks: {n} finding. It does not reject the answer.' : 'Answer checks: {n} findings. They do not reject the answer.')
  return <details className="legacy-mini-note phrasing-note">
    <summary>{t(summary, { n: found.length })}</summary>
    <ul className="plain-list">{found.map((w, i) => <li key={i}>{mathLabels[w.code] && <strong>{t(mathLabels[w.code])}: </strong>}{w.message}</li>)}</ul>
  </details>
}


function ReviewNote({ review }: { review: Answer['review'] }) {
  const modelText = useModelText()
  if (!review) return null
  const model = review.model ? <> · <ModelName connection={review.model.connection} text={modelText(review.model.resolved_model ?? review.model.requested_model)} /></> : null
  if (review.status === 'failed') {
    return <p className="legacy-mini-note review-summary"><ShieldCheck size={13} aria-hidden /><span>{model && <strong>{t('Claim check (automatic)')}{model}:</strong>} {t('The reviewer did not produce a usable review.')} {pauseReasonText(review.failure_reason)} {t('The answer is unchanged.')}</span></p>
  }
  const counts = (Object.keys(verdictLabels) as Verdict[]).map(v => [v, review.reviews.filter(r => r.verdict === v).length] as const).filter(([, n]) => n > 0)
  return <p className="legacy-mini-note review-summary"><ShieldCheck size={13} aria-hidden /><span><strong>{t('Claim check (automatic)')}{model}:</strong> {counts.map(([v, n]) => `${n} ${t(verdictLabels[v])}`).join(' · ')}. {review.notes && `${review.notes} `}{t('This is an additional model’s reading of each claim against its cited passages. It does not change the answer and is not independent verification.')}</span></p>
}
