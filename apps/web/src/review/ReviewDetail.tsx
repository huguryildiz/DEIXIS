import { useState } from 'react'
import { ChevronRight, CircleX, Pause, Play, TriangleAlert, X } from 'lucide-react'
import { api, type ReviewDetail as Detail, type Source } from '../api'
import { pauseReasonText, reviewContextLabels, reviewFocusLabels, runStatusLabels } from '../labels'
import { ModelName } from '../ModelName'
import { useModelText } from '../modelText'
import { t, uiLocale } from '../i18n'
import { FindingCard } from './FindingCard'
import { NotReviewed } from './NotReviewed'
import { ReviewEvidence } from './ReviewEvidence'
import { resolvedGroupClaims, resolvedTargetHeading, resolvedTargetLabel, staleLabel } from './labels'

const more = <ChevronRight size={14} aria-hidden />

// One review (mockup `reviewPanel`): what was reviewed, with which focus and model; its state; a warning when the
// target changed after it; the findings, each a proposal until the person decides; then what it did not cover.
export function ReviewDetail({ researchId, review, sources, sectionLabel, open, refresh, apply }: {
  researchId: string; review: Detail; sources: Source[]; sectionLabel: (ref: string) => string
  open: (id: string, anchor: string) => void; refresh: () => Promise<void>; apply?: (reviewId: string, findingId: string) => Promise<void>
}) {
  const modelText = useModelText()
  const [controlBusy, setControlBusy] = useState(false)
  const [error, setError] = useState('')
  const kind = review.snapshot.target_kind
  const sourceName = (id: string) => sources.find(s => s.source_version_id === id)?.source_key ?? review.snapshot.sources.find(s => s.source_id === id)?.title ?? t('an item no longer in the review copy')
  const reviewed = review.groups.filter(g => g.coverage === 'reviewed').length
  const nextGroup = review.groups.find(g => g.coverage === 'pending')
  const running = review.state === 'running'
  const state = running ? nextGroup ? t('Reviewing group {i} of {n}… Findings stay readable.', { i: nextGroup.group_index, n: review.groups.length }) : t('Running')
    : review.state === 'partial' ? t(review.groups.length === 1 ? '{k} of {n} group reviewed' : '{k} of {n} groups reviewed', { k: reviewed, n: review.groups.length }) : t(runStatusLabels[review.state])
  const control = async (action: 'pause' | 'resume' | 'cancel') => {
    if (controlBusy) return
    setControlBusy(true); setError('')
    try { await api.controlRun(review.run_id, action); await refresh() }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setControlBusy(false) }
  }
  const rank = (row: Detail['findings'][number]) => {
    const ref = row.finding.target_ref
    if (kind === 'candidate') return ref.kind === 'candidate_element' ? review.snapshot.elements?.find(e => e.element_ref === ref.ref)?.position ?? 999 : 1000 + row.finding.group_index
    if (ref.kind === 'claim') { const index = review.snapshot.claims.findIndex(c => c.claim_ref === ref.ref); return index < 0 ? review.snapshot.claims.length : index }
    if (ref.kind === 'section') { const index = review.snapshot.claims.findIndex(c => c.section_ref === ref.ref); return review.snapshot.claims.length + (index < 0 ? review.snapshot.claims.length : index) }
    return review.snapshot.claims.length * 2 + row.finding.group_index
  }
  const findings = [...review.findings].sort((a, b) => rank(a) - rank(b) || a.ordinal - b.ordinal)
  // The answer's or report's version comes from the stored snapshot, not from what is current now.
  const reportVersion = review.snapshot.report_version
  const target = kind === 'candidate' ? t('Candidate · Version {n}', { n: review.snapshot.candidate_version ?? '' })
    : kind === 'answer' ? (reportVersion ? `${t('Answer')} · V${reportVersion}` : t('Answer'))
    : reportVersion ? t('Evidence report · V{n}', { n: reportVersion }) : t('Evidence report')
  const finished = ['completed', 'partial'].includes(review.state)
  const live = ['queued', 'running', 'pause_requested', 'paused'].includes(review.state)
  const models = [...new Set(review.models_that_answered.map(m => modelText(m.resolved_model ?? m.requested_model)))].join(', ')
  return <section className="review-detail" data-review-id={review.id}>
    <p className="dmeta"><span>{target}</span><span>{t(reviewFocusLabels[review.focus])}</span><span><ModelName connection={review.requested_model.connection} text={modelText(review.requested_model.model, review.requested_model.reasoning_effort)} /></span><span><time>{new Date(review.created_at).toLocaleString(uiLocale())}</time></span>{!running && <span role="status" className="review-state">{state}</span>}</p>
    {review.owner_note && <p className="foot-note">{t('Your note:')} <span data-stored-text>{review.owner_note}</span></p>}
    <p className="foot-note">{t(review.assessment_notice)}</p>
    {running && <div className="notice info"><span className="spin" aria-hidden /><span role="status">{state}</span></div>}
    {review.state === 'paused' && <div className="notice warn"><Pause aria-hidden /><span>{pauseReasonText(review.pause_reason)}</span></div>}
    {review.state === 'failed' && <div className="notice bad" role="alert"><CircleX aria-hidden /><span>{pauseReasonText(review.failure_reason) || t('The run failed.')}</span></div>}
    {review.outcome_unknown && <div className="notice warn"><TriangleAlert aria-hidden /><span>{t('A model call has an unknown outcome; resuming may repeat it.')}</span></div>}
    {live && <div className="acts">
      {review.state === 'running' && <button type="button" className="ghost" disabled={controlBusy} aria-describedby={controlBusy ? 'review-control-busy' : undefined} onClick={() => void control('pause')}><Pause aria-hidden />{t('Pause')}</button>}
      {review.state === 'paused' && <button type="button" className="ghost" disabled={controlBusy} aria-describedby={controlBusy ? 'review-control-busy' : undefined} onClick={() => void control('resume')}><Play aria-hidden />{t('Resume')}</button>}
      <button type="button" className="ghost" disabled={controlBusy} aria-describedby={controlBusy ? 'review-control-busy' : undefined} onClick={() => void control('cancel')}><X aria-hidden />{t('Cancel')}</button>
      {controlBusy && <span id="review-control-busy" role="status" className="foot-note">{t('Saving…')}</span>}
    </div>}
    {error && <div className="notice bad" role="alert"><CircleX aria-hidden /><span>{error}</span></div>}
    {review.stale_reasons.length > 0 && <div className="notice warn review-stale"><TriangleAlert aria-hidden /><span>{t(kind === 'candidate' ? 'Written against an earlier candidate: {reasons}. The findings are kept as they were.' : kind === 'answer' ? 'Written against an earlier answer: {reasons}. The findings are kept as they were.' : 'Written against an earlier report: {reasons}. The findings are kept as they were.', {
      reasons: review.stale_reasons.map(reason => staleLabel(review, reason, sectionLabel, sourceName)).join('; '),
    })}</span></div>}
    {review.not_reviewed.length > 0 && <details key={`${review.id}:${finished}`} className="review-coverage-more" open={!finished}><summary>{more}{t('Not reviewed')} ({review.not_reviewed.length})</summary><NotReviewed rows={review.not_reviewed} sourceName={sourceName} sectionLabel={sectionLabel} /></details>}
    {findings.map(row => <FindingCard key={row.id} researchId={researchId} review={review} row={row} heading={resolvedTargetHeading(review, row.finding, sectionLabel)} group={resolvedGroupClaims(review, row.finding, sectionLabel)}
      sourceName={sourceName} open={open} refresh={refresh} apply={kind === 'report' ? apply : undefined} />)}
    {finished && findings.length === 0 && <p className="foot-note">{t('The review raised no finding.')}</p>}
    {finished && <p className="foot-note review-foot">{t('Supported points ({n})', { n: review.supported_points.length })} · {t('Not reviewed')} ({review.not_reviewed.length}) · {t('Models that answered')}: {models || t('none')} · {t('Question revision, method package and snapshot hash are recorded with the review.')}</p>}
    <details className="mk-more"><summary>{more}{t('Details')}</summary><dl className="kv2 review-identity"><dt>{t('Question revision')}</dt><dd>{review.snapshot.scope_revision}</dd><dt>{t('Method package')}</dt><dd><span aria-label={t('Method package: {hash}', { hash: review.skill_package_hash ?? t('not recorded') })}>{review.skill_package_hash ? review.skill_package_hash.replace(/^sha256:/, '').slice(0, 12) : t('not recorded')}</span></dd><dt>{t('Snapshot hash')}</dt><dd>{review.snapshot.content_sha256}</dd><dt>{t('Snapshot time')}</dt><dd>{new Date(review.snapshot.created_at).toLocaleString(uiLocale())}</dd></dl>
      <details><summary>{more}{t('Supported points ({n})', { n: review.supported_points.length })}</summary><p className="foot-note">{t('Located quotes; whether they support the target was not checked.')}</p>{review.supported_points.map((point, i) => <div key={i} className="review-point"><b data-stored-text>{resolvedTargetHeading(review, point, sectionLabel)}</b>{point.target_ref.kind === 'whole' && <p className="review-group-refs" data-stored-text>{resolvedGroupClaims(review, point, sectionLabel)}</p>}<ReviewEvidence evidence={point.evidence} sourceName={sourceName} open={open} /></div>)}</details>
      <details><summary>{more}{t('Context limits ({n})', { n: review.context_limits.length })}</summary><ul>{review.context_limits.map((limit, i) => <li key={i}>{t(reviewContextLabels[limit.code] ?? limit.code)} · <span data-stored-text>{resolvedTargetLabel(review, limit, sectionLabel)}: {limit.text}</span></li>)}</ul></details>
      <details><summary>{more}{t('Models that answered')}</summary><ul>{review.models_that_answered.map((model, i) => <li key={i}><ModelName connection={model.connection} text={modelText(model.requested_model)} /> · {t('Resolved model')}: {model.resolved_model ? <ModelName connection={model.connection} text={modelText(model.resolved_model)} /> : t('not recorded')} · {t(model.status)} · <span data-stored-text>{model.requested_model} · {model.resolved_model}</span></li>)}</ul></details>
    </details>
  </section>
}
