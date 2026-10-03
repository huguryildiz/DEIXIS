import { useState } from 'react'
import { ChevronDown, ChevronRight, Pause, Play, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api, type ReviewDetail as Detail, type Source } from '../api'
import { pauseReasonText, reviewContextLabels, reviewFocusLabels, runStatusLabels } from '../labels'
import { ModelName } from '../ModelName'
import { useModelText } from '../modelText'
import { Notice } from '../Notice'
import { t, uiLocale } from '../i18n'
import { FindingCard } from './FindingCard'
import { NotReviewed } from './NotReviewed'
import { ReviewEvidence } from './ReviewEvidence'
import { resolvedGroupClaims, resolvedTargetHeading, resolvedTargetLabel, staleLabel } from './labels'

export function ReviewDetail({ researchId, review, sources, sectionLabel, open, refresh, apply }: {
  researchId: string; review: Detail; sources: Source[]; sectionLabel: (ref: string) => string
  open: (id: string, anchor: string) => void; refresh: () => Promise<void>; apply?: (reviewId: string, findingId: string) => Promise<void>
}) {
  const modelText = useModelText()
  const [controlBusy, setControlBusy] = useState(false)
  const [error, setError] = useState('')
  const sourceName = (id: string) => sources.find(s => s.source_version_id === id)?.source_key ?? review.snapshot.sources.find(s => s.source_id === id)?.title ?? t('an item no longer in the review copy')
  const reviewed = review.groups.filter(g => g.coverage === 'reviewed').length
  const nextGroup = review.groups.find(g => g.coverage === 'pending')
  const state = review.state === 'running' ? nextGroup ? t('Reviewing group {i} of {n}', { i: nextGroup.group_index, n: review.groups.length }) : t('Running')
    : review.state === 'partial' ? t(review.groups.length === 1 ? '{k} of {n} group reviewed' : '{k} of {n} groups reviewed', { k: reviewed, n: review.groups.length }) : t(runStatusLabels[review.state])
  const control = async (action: 'pause' | 'resume' | 'cancel') => {
    if (controlBusy) return
    setControlBusy(true); setError('')
    try { await api.controlRun(review.run_id, action); await refresh() }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setControlBusy(false) }
  }
  const targetGroups = new Map<string, Detail['findings']>()
  const rank = (row: Detail['findings'][number]) => {
    const ref = row.finding.target_ref
    if (ref.kind === 'claim') { const index = review.snapshot.claims.findIndex(c => c.claim_ref === ref.ref); return index < 0 ? review.snapshot.claims.length : index }
    if (ref.kind === 'section') { const index = review.snapshot.claims.findIndex(c => c.section_ref === ref.ref); return review.snapshot.claims.length + (index < 0 ? review.snapshot.claims.length : index) }
    return review.snapshot.claims.length * 2 + row.finding.group_index
  }
  for (const row of [...review.findings].sort((a, b) => rank(a) - rank(b) || a.ordinal - b.ordinal)) {
    const label = resolvedTargetLabel(review, row.finding, sectionLabel)
    targetGroups.set(label, [...(targetGroups.get(label) ?? []), row])
  }
  return <section className="review-detail" data-review-id={review.id}>
    <header><h3>{t('Additional model review')}</h3><p><ModelName connection={review.requested_model.connection} text={modelText(review.requested_model.model, review.requested_model.reasoning_effort)} /> · <time>{new Date(review.created_at).toLocaleString(uiLocale())}</time></p><p>{t(reviewFocusLabels[review.focus])}</p>
      {review.owner_note && <p>{t('Your note:')} <span data-stored-text>{review.owner_note}</span></p>}
      <p className="review-muted">{t(review.assessment_notice)}</p>
      <p role="status" className={review.state === 'running' ? 'shimmer-text' : undefined}>{state}</p>
      {review.state === 'paused' && <Notice tone="attention">{pauseReasonText(review.pause_reason)}</Notice>}
      {review.state === 'failed' && <Notice tone="error">{pauseReasonText(review.failure_reason) || t('The run failed.')}</Notice>}
      {review.outcome_unknown && <Notice tone="attention">{t('A model call has an unknown outcome; resuming may repeat it.')}</Notice>}
      <div className="review-actions">
        {review.state === 'running' && <Button type="button" variant="ghost" size="sm" disabled={controlBusy} aria-describedby={controlBusy ? 'review-control-busy' : undefined} onClick={() => void control('pause')}><Pause size={14} aria-hidden />{t('Pause')}</Button>}
        {review.state === 'paused' && <Button type="button" variant="ghost" size="sm" disabled={controlBusy} aria-describedby={controlBusy ? 'review-control-busy' : undefined} onClick={() => void control('resume')}><Play size={14} aria-hidden />{t('Resume')}</Button>}
        {['queued', 'running', 'pause_requested', 'paused'].includes(review.state) && <Button type="button" variant="ghost" size="sm" disabled={controlBusy} aria-describedby={controlBusy ? 'review-control-busy' : undefined} onClick={() => void control('cancel')}><X size={14} aria-hidden />{t('Cancel')}</Button>}
      </div>{controlBusy && <p id="review-control-busy" role="status">{t('Saving…')}</p>}
      <details><summary><ChevronRight size={14} aria-hidden className="closed" /><ChevronDown size={14} aria-hidden className="opened" />{t('Details')}</summary><dl className="review-identity"><dt>{t('Question revision')}</dt><dd>{review.snapshot.scope_revision}</dd><dt>{t('Method package')}</dt><dd><span aria-label={t('Method package: {hash}', { hash: review.skill_package_hash ?? t('not recorded') })}>{review.skill_package_hash ? review.skill_package_hash.replace(/^sha256:/, '').slice(0, 12) : t('not recorded')}</span></dd><dt>{t('Snapshot hash')}</dt><dd>{review.snapshot.content_sha256}</dd><dt>{t('Snapshot time')}</dt><dd>{new Date(review.snapshot.created_at).toLocaleString(uiLocale())}</dd></dl></details>
    </header>
    {error && <Notice tone="error">{error}</Notice>}
    {review.stale_reasons.length > 0 && <Notice tone="attention"><p>{t(review.snapshot.target_kind === 'answer' ? 'The answer changed after this review:' : 'The report changed after this review:')}</p><ul>{review.stale_reasons.map((reason, i) => <li key={i}>{staleLabel(review, reason, sectionLabel, sourceName)}</li>)}</ul><p>{t('Findings stay readable.')}</p></Notice>}
    <details key={`${review.id}:${review.state === 'completed'}`} open={review.state !== 'completed'}><summary><ChevronRight size={14} aria-hidden className="closed" /><ChevronDown size={14} aria-hidden className="opened" />{t('Not reviewed')} ({review.not_reviewed.length})</summary><NotReviewed rows={review.not_reviewed} sectionLabel={sectionLabel} /></details>
    {[...targetGroups].map(([label, rows]) => <section className="review-target" key={label}><h3 data-stored-text>{resolvedTargetHeading(review, rows[0].finding, sectionLabel)}</h3>{rows[0].finding.target_ref.kind === 'whole' && <p className="review-group-refs" data-stored-text>{resolvedGroupClaims(review, rows[0].finding, sectionLabel)}</p>}{rows.map(row => <FindingCard key={row.id} researchId={researchId} review={review} row={row} sourceName={sourceName} open={open} refresh={refresh} apply={review.snapshot.target_kind === 'report' ? apply : undefined} />)}</section>)}
    <details><summary><ChevronRight size={14} aria-hidden className="closed" /><ChevronDown size={14} aria-hidden className="opened" />{t('Supported points ({n})', { n: review.supported_points.length })}</summary><p>{t('Located quotes; whether they support the target was not checked.')}</p>{review.supported_points.map((point, i) => <section key={i}><h4 data-stored-text>{resolvedTargetHeading(review, point, sectionLabel)}</h4>{point.target_ref.kind === 'whole' && <p className="review-group-refs" data-stored-text>{resolvedGroupClaims(review, point, sectionLabel)}</p>}<ReviewEvidence evidence={point.evidence} sourceName={sourceName} open={open} /></section>)}</details>
    <details><summary><ChevronRight size={14} aria-hidden className="closed" /><ChevronDown size={14} aria-hidden className="opened" />{t('Context limits ({n})', { n: review.context_limits.length })}</summary><ul>{review.context_limits.map((limit, i) => <li key={i}>{t(reviewContextLabels[limit.code] ?? limit.code)} · <span data-stored-text>{resolvedTargetLabel(review, limit, sectionLabel)}: {limit.text}</span></li>)}</ul></details>
    <details><summary><ChevronRight size={14} aria-hidden className="closed" /><ChevronDown size={14} aria-hidden className="opened" />{t('Models that answered')}</summary><ul>{review.models_that_answered.map((model, i) => <li key={i}><ModelName connection={model.connection} text={modelText(model.requested_model)} /> · {t('Resolved model')}: {model.resolved_model ? <ModelName connection={model.connection} text={modelText(model.resolved_model)} /> : t('not recorded')} · {t(model.status)}<details><summary><ChevronRight size={14} aria-hidden className="closed" /><ChevronDown size={14} aria-hidden className="opened" />{t('Details')}</summary><span data-stored-text>{model.requested_model} · {model.resolved_model}</span></details></li>)}</ul></details>
  </section>
}
