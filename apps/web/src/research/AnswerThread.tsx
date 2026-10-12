import { useRef, useState, type ReactNode } from 'react'
import { ArrowUp, ArrowUpRight, BadgeCheck, BookOpen, BookOpenText, Copy, Eye, FileText, Filter, Info, ListChecks, ListMinus, PencilLine, RotateCw, ScanText, Sigma, Quote, ShieldCheck, Table2, TriangleAlert, Upload, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { type Answer, type Claim, type Limitation, type Source, type ValidationIssue, type Verdict } from '../api'
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
import { t, uiLocale } from '../i18n'
import { SourceKey } from '../SourceKey'
import { Notice } from '../Notice'
import { AnswerFlowNote } from '../FlowReport'
import { MethodBox } from '../MethodBox'
import { ExportLinks } from './ExportMenu'
import { ReportSheet } from './ReportSheet'
import { downloadReportMarkdown, reportMarkdown, reportParts } from './reportMarkdown'

// The latest answer in the thread (mockup `answerBlock()`, R22-R29): the notices of its state, the report card (or the
// live card while a new version is written), the first paragraphs of its claims with their citations, the Methods box,
// the action pills and the Next steps box. Every number is the answer's own stored record or the view's count. The full
// report opens as a side panel (ReportSheet); an older version opens the same panel without the thread part.

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

const count = (n: number) => new Intl.NumberFormat(uiLocale()).format(n)
// The thread shows the answer's first sections as paragraphs (mockup `.prose`, two of them); the report has every one.
const PROSE_SECTIONS = 2

// What the thread needs from the research page: the run writing the next version, the earlier version of the same
// question revision, a running claim review, and the ways into the panels.
export type AnswerThreadContext = {
  writing: { next: number; late: boolean } | null
  previous: { id: string; version: number } | null
  reviewPending: boolean
  included: number
  hasTable: boolean
  canNewAnswer: boolean
  downloadMenu: ReactNode
  onPanel: (name: 'table' | 'pdfs' | 'funnel', opener: HTMLElement) => void
  onShowSources: (filter: 'cited' | 'included', opener: HTMLElement) => void
  onRevise: () => void
  onNewAnswer: () => void
  onOpenReport: (answerId: string) => void
}

// A notice in the mockup's `.notice` form: an icon, the sentences, then the actions.
function AnswerNotice({ tone, icon, actions, children }: { tone: 'info' | 'attention' | 'error'; icon?: LucideIcon; actions?: ReactNode; children: ReactNode }) {
  const Icon = icon ?? (tone === 'info' ? Info : TriangleAlert)
  return <div className={`notice answer-notice is-${tone}`} role={tone === 'error' ? 'alert' : undefined}>
    <Icon size={16} aria-hidden />
    <div className="notice-body">{children}{actions && <div className="notice-actions">{actions}</div>}</div>
  </div>
}

// Where the works stood when the answer started, in one line (mockup `.src-m` under the no-include notice).
function startLine(answer: Answer) {
  const five = answer.start_snapshot?.flow.five
  if (!five) return t('The flow at the start of this answer was not recorded.')
  return t('When the answer started: included {included} · in your queue {queued} · waiting for a PDF {waiting} · full text not read {notRead} · criterion not met {notMet}', {
    included: count(five.included), queued: count(five.queued), waiting: count(five.waiting_for_pdf), notRead: count(five.not_read), notMet: count(five.not_met) })
}

// The works an answer cites, each counted once over its versions (as the view's "cited" count does).
function citedWorks(answer: Answer, sources: Source[]) {
  const workOf = new Map(sources.map(s => [s.source_version_id, s.work_id]))
  return new Set(answer.claims.flatMap(c => c.evidence.map(e => workOf.get(e.source_version_id) ?? e.source_version_id))).size
}

export function AnswerThread({ researchId, title, version, answer, sources, busy, dark, reportOpen, onReportOpenChange, showCard = true, onOpen, onAttachPdf, eventCursor, runActive, thread, reviewPending = false }: { researchId: string; title: string; version: number; answer: Answer; sources: Source[]; busy: boolean; dark: boolean; reportOpen: boolean; onReportOpenChange: (open: boolean) => void; showCard?: boolean; onOpen: (passageId: string, highlightText: string | null) => void; onAttachPdf: (source: Source) => void; eventCursor: number; runActive: boolean; thread?: AnswerThreadContext; reviewPending?: boolean }) {
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
  const ctx = showCard ? thread : undefined
  const latePending = ctx && answer.late_revision_status && ['waiting_fetch', 'reading', 'answering'].includes(answer.late_revision_status.status)
    ? <p className="foot-note answer-late-pending" role="status">{t(LATE_REVISION_PENDING)}</p> : null
  const newAnswer = ctx && <Button size="sm" disabled={!ctx.canNewAnswer} onClick={ctx.onNewAnswer}><RotateCw size={14} aria-hidden />{t('Generate a new answer')}</Button>
  if (answer.status === 'clarification' && answer.clarification) {
    if (!ctx) return null
    const clarification = answer.clarification
    return <div className="answer-thread"><AnswerNotice tone="info" actions={<Button size="sm" onClick={ctx.onRevise}><PencilLine size={14} aria-hidden />{t('Revise question')}</Button>}>
      <p><b>{t('Clarification needed')}</b></p>
      <p className="answer-notice-question">{clarification.question}</p>
      <p>{clarification.why_it_matters}</p>
      {clarification.options.length > 0 && <ul className="answer-notice-list">{clarification.options.map(o => <li key={o}>{o}</li>)}</ul>}
      <p>{t('Revise the question to continue. No answer was written.')}</p>
    </AnswerNotice></div>
  }
  if (answer.status === 'no_evidence') {
    if (!ctx) return null
    const noInclude = answer.validation.reason === 'no_includable_source'
    const included = answer.start_snapshot?.included
    return <div className="answer-thread">
      {noInclude
        ? <AnswerNotice tone="attention" actions={<Button variant="outline" size="sm" className="notice-ghost" onClick={e => ctx.onPanel('pdfs', e.currentTarget)}><FileText size={14} aria-hidden />{t('Get more full text')}</Button>}>
          <p>{t('No work was included at full text when this answer started, so no answer was written and no model was asked. The line below says where the works stand.')}</p>
          <p className="src-m">{startLine(answer)}</p>
        </AnswerNotice>
        : <AnswerNotice tone="attention" actions={<Button variant="outline" size="sm" className="notice-ghost" onClick={e => ctx.onPanel('pdfs', e.currentTarget)}><Upload size={14} aria-hidden />{t('Attach PDFs')}</Button>}>
          <p>{t('No text passages were available for the included sources (no abstract, no retrievable PDF text). No answer was generated.')}</p>
          {included !== undefined && <p className="src-m">{t('Included when the answer started: {n}', { n: count(included) })}</p>}
        </AnswerNotice>}
      {latePending}
    </div>
  }
  if (answer.status === 'unverified_draft') {
    if (!ctx) return null
    const claims = answer.unverified_draft?.claims ?? []
    return <div className="answer-thread">
      <AnswerNotice tone="error" actions={newAnswer}>
        <p>{t('The model output failed validation after one repair attempt, so it is not shown as a cited answer.')}</p>
        {(answer.validation.issues?.length ?? 0) > 0 && <ul className="answer-notice-issues">{answer.validation.issues!.map(i => <li key={`${i.code}${i.path}`}>{t('{code} at {path}', { code: i.code, path: i.path })}</li>)}</ul>}
      </AnswerNotice>
      {claims.length > 0 && <><div className="prose answer-prose">{claims.map(c => <p className="claim is-unverified" key={c.claim_label}><MathText text={c.text} /></p>)}</div>
        <p className="foot-note">{t('Unverified draft: shown greyed, without citations, so you can see what failed. Do not quote it.')}</p></>}
      {latePending}
    </div>
  }
  const { refs, citeLabel, sections, suggestion, limits } = reportParts(answer, sources)
  const markdown = () => reportMarkdown(answer, sources, title, version, style)
  const copyReport = async () => {
    try { await writeClipboard(markdown()); setCopied(true); toast('success', t('Report copied to clipboard.')) }
    catch { toast('error', t('Could not copy the report.')) }
  }
  const downloadReport = () => downloadReportMarkdown(answer, sources, title, version, style)
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
    {/* An earlier report has no thread part, so its own method record (with Full method) stays in its report (§0.5). */}
    {!ctx && answer.status === 'structurally_valid' && answer.start_snapshot !== undefined && <MethodBox key={answer.id} researchId={researchId} answer={answer} reviewPending={reviewPending} inReport />}
    <p className="legacy-mini-note">{t('Structural check passed: each citation resolves to a stored passage that was given to this step. Semantic support is not checked.')} {answer.model && <>{t('Model')}: <ModelName connection={answer.model.connection} text={modelText(answer.model.resolved_model ?? answer.model.requested_model ?? t('unknown'))} />.</>} {answer.inputs_given ? t('{passages} passages from {sources} sources were provided.', { passages: answer.inputs_given.passages, sources: answer.inputs_given.sources }) : ''}</p>
    <AnswerFlowNote answer={answer} />
    <ReviewNote review={answer.review} />
    <ChecksNote warnings={answer.validation.warnings} />
    {suggestion && <PdfSuggestions notes={suggestion.notes} sources={suggestion.sources} busy={busy} onAttachPdf={onAttachPdf} />}
  </div>
  // The thread's citation chip (mockup `.cite`): one per claim, naming its first source and "+N" for the others it cites;
  // with keyless sources the numbers of the cited passages. It opens the first cited passage at its located anchor; the
  // report lists every passage of the claim.
  const chip = (claim: Claim) => {
    if (!claim.evidence.length) return null
    const first = claim.evidence[0]
    const others = new Set(claim.evidence.map(e => e.source_version_id)).size - 1
    const label = first.source_key ? `${first.source_key}${others > 0 ? ` +${others}` : ''}` : `[${[...new Set(claim.evidence.map(e => refs.get(e.passage_id)?.n))].join(', ')}]`
    const titleText = claim.evidence.map(e => [e.title, versionText(e.version_label), locatorText(e), e.text_source === 'ocr' && t(OCR_LABEL), e.removed_from_research && t('Removed from this research')].filter(Boolean).join(' · ')).join('\n')
    return <button type="button" className="cite-chip thread-cite" title={titleText} onClick={() => onOpen(first.passage_id, first.anchor_text)}>{label}</button>
  }
  const cited = citedWorks(answer, sources)
  const abstractOnly = answer.inputs_given?.depth?.abstract ?? 0
  const stale = answer.applicability === 'stale_selection'
  const late = answer.late_revision && answer.late_revision.base_report_version !== null ? answer.late_revision : null
  const go = <span className="go" aria-hidden><ArrowUp size={14} /></span>
  const threadPart = ctx && answer.status === 'structurally_valid' && <div className="answer-thread">
    {answer.applicability === 'stale_scope' && <AnswerNotice tone="attention"><p>{t('This answer was produced for revision {n} of the question and is not applied to the current revision.', { n: answer.scope_revision })}</p></AnswerNotice>}
    {answer.source_text_changed && <AnswerNotice tone="attention" icon={FileText} actions={newAnswer}>
      <p>{t('A PDF this answer read was replaced, removed or had its text extracted again after the answer was generated. Its quotes still open the text that was read; generate a new answer to read the current text.')}</p>
    </AnswerNotice>}
    {stale && <AnswerNotice tone="attention" actions={<>{!answer.source_text_changed && newAnswer}
      <Button variant="outline" size="sm" className="notice-ghost" onClick={e => ctx.onShowSources('included', e.currentTarget)}>{t('Review the selection')}</Button></>}>
      <p><b>{t('This answer is out of date.')}</b> {t('Your source selection changed after it was written; the answer still uses the old selection.')}</p>
    </AnswerNotice>}
    {/* "Compare with Vn" needs the answer diff (P4, S21); until then the earlier version opens on its own. */}
    {!ctx.writing && !stale && (late
      ? <AnswerNotice tone="info" icon={FileText} actions={<Button variant="outline" size="sm" className="notice-ghost" onClick={() => ctx.onOpenReport(late.base_answer_id)}><Eye size={14} aria-hidden />{t('Open V{n}', { n: late.base_report_version! })}</Button>}>
        <p><b>{t('A late full text produced answer V{v}.', { v: version })}</b> {t(late.upgraded_sources === 1 ? 'Full text for {n} source arrived after V{base} was written; V{v} reads it (selected pages). This happens once per answer. V{base} is kept.' : 'Full text for {n} sources arrived after V{base} was written; V{v} reads them (selected pages). This happens once per answer. V{base} is kept.', { n: count(late.upgraded_sources), base: late.base_report_version!, v: version })}</p>
      </AnswerNotice>
      : ctx.previous && <AnswerNotice tone="info" actions={<Button variant="outline" size="sm" className="notice-ghost" onClick={() => ctx.onOpenReport(ctx.previous!.id)}><Eye size={14} aria-hidden />{t('Open V{n}', { n: ctx.previous.version })}</Button>}>
        <p><b>{t('Answer V{v} is the latest.', { v: version })}</b> {t('V{n} is kept.', { n: ctx.previous.version })}</p>
      </AnswerNotice>)}
    {latePending}
    {ctx.writing
      ? <div className="report-artifact is-live" role="status">
        <span className="report-artifact-preview" aria-hidden="true" />
        <span className="report-artifact-copy"><strong className="shimmer-text">{t('Writing answer V{n}…', { n: ctx.writing.next })}</strong>
          <span className="report-artifact-meta">{t(ctx.writing.late ? 'Reading the full texts that arrived late · V{v} stays available' : 'V{v} stays available', { v: version })}</span></span>
      </div>
      // The "Cited" count above the thread scrolls here: the answer card is where the citations live.
      : <button type="button" id="research-answer" className={`report-artifact${reportOpen ? ' is-on' : ''}`} onClick={() => onReportOpenChange(true)} aria-label={t('Open report: {title}', { title })}>
        <span className="report-artifact-preview" aria-hidden="true"><strong>{title}</strong></span>
        <span className="report-artifact-copy"><strong>{title}</strong>
          <span className="report-artifact-meta">{t('Report')} · V{version} · {t(answer.claims.length === 1 ? '{n} claim' : '{n} claims', { n: count(answer.claims.length) })} · {t(cited === 1 ? '{n} source' : '{n} sources', { n: count(cited) })}</span></span>
      </button>}
    {sections.length > 0 && <div className="prose answer-prose">{sections.slice(0, PROSE_SECTIONS).map(({ claims }, index) => <p key={index}>
      {claims.map(claim => <span className="claim" key={claim.id}><MathText text={claim.text} />
        {claim.support_type === 'analyst_inference' && <span className="support-badge">{t('interpretation')}</span>}
        {claim.evidence_basis === 'abstract' && <span className="support-badge">{t('From abstract')}</span>}
        {chip(claim)}</span>)}
    </p>)}</div>}
    {answer.start_snapshot !== undefined && <MethodBox key={answer.id} researchId={researchId} answer={answer} reviewPending={ctx.reviewPending} onShowFunnel={opener => ctx.onPanel('funnel', opener)} />}
    <div className="answer-acts">
      {cited > 0 && <Button variant="outline" size="sm" className="answer-pill" onClick={e => ctx.onShowSources('cited', e.currentTarget)}><BookOpen size={15} aria-hidden />{t(cited === 1 ? 'View {n} cited source' : 'View {n} cited sources', { n: count(cited) })}</Button>}
      <Button variant="outline" size="sm" className="answer-pill" onClick={e => ctx.onPanel('table', e.currentTarget)}><Table2 size={15} aria-hidden />{t('Evidence table')}</Button>
      <Button variant="outline" size="sm" className="answer-pill" onClick={e => ctx.onPanel('funnel', e.currentTarget)}><Filter size={15} aria-hidden />{t('Search funnel')}</Button>
      <Button variant="ghost" size="icon-sm" className="answer-ib" aria-label={t('Copy answer')} title={t('Copy answer')} onClick={() => { void copyReport() }}><Copy size={16} aria-hidden /></Button>
      {ctx.downloadMenu}
    </div>
    <ReviewSummary reviews={reviewList.reviews} open={() => openReviews()} />
    <section className="follow" aria-labelledby={`next-steps-${answer.id}`}>
      <h5 id={`next-steps-${answer.id}`}>{t('Next steps')}</h5>
      <button type="button" className="first" onClick={() => openReviews(true)}><ListChecks size={16} aria-hidden /><span>{t('Review the claims with another model')}</span>{go}</button>
      {ctx.included > 0 && <button type="button" onClick={e => ctx.onPanel('table', e.currentTarget)}><Table2 size={16} aria-hidden />
        <span>{ctx.hasTable ? t('Open the evidence table') : t(ctx.included === 1 ? 'Build an evidence table of the {n} included source' : 'Build an evidence table of the {n} included sources', { n: count(ctx.included) })}</span>{go}</button>}
      {abstractOnly > 0 && <button type="button" onClick={e => ctx.onPanel('pdfs', e.currentTarget)}><Upload size={16} aria-hidden />
        <span>{t(abstractOnly === 1 ? 'Get full text for the {n} work the answer read from its abstract only' : 'Get full text for the {n} works the answer read from their abstracts only', { n: count(abstractOnly) })}</span>{go}</button>}
    </section>
  </div>
  return <>
    {threadPart}
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
