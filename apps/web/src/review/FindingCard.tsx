import { useId, useRef, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api, type ReviewDetail, type ReviewFindingRow } from '../api'
import { reviewDecisionLabels, reviewFindingLabels } from '../labels'
import { useToast } from '../Toast'
import { MathText } from '../MathText'
import { Notice } from '../Notice'
import { t, uiLocale } from '../i18n'
import { newCommand, useWriteCommand } from './commands'
import { RetryNotice } from './RetryNotice'
import { ReviewEvidence } from './ReviewEvidence'

export function FindingCard({ researchId, review, row, sourceName, open, refresh, apply }: {
  researchId: string; review: ReviewDetail; row: ReviewFindingRow; sourceName: (id: string) => string
  open: (id: string, anchor: string) => void; refresh: () => Promise<void>; apply?: (reviewId: string, findingId: string) => Promise<void>
}) {
  const toast = useToast()
  const [dismissing, setDismissing] = useState(false)
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [opening, setOpening] = useState(false)
  const dismissKey = useRef('')
  const reasonId = useId()
  const { finding, current_decision: current } = row
  const command = useWriteCommand(`${researchId}:${review.id}:${row.id}:decision`, c => api.decideReview(researchId, review.id, row.id, c.body, c.key), async result => {
    setDismissing(false); setReason(''); setError('')
    toast('success', result.no_change_made ? t(review.snapshot.target_kind === 'candidate' ? 'Recorded. No change was made to the candidate.' : 'Recorded. No change was made to the answer.') : t('Recorded. No text was changed.'))
    await refresh()
  }, async e => {
    dismissKey.current = crypto.randomUUID()
    setError(e.message)
    if (e.code === 'decision_changed') { toast('warning', e.message); await refresh() }
  })
  const decide = (decision: 'accepted' | 'dismissed' | 'deferred', key?: string) => {
    if (command.pending) return
    setError('')
    void command.send(newCommand({ decision, reason: decision === 'dismissed' ? reason.trim() : null, expected_ordinal: current?.ordinal ?? 0 }, key))
  }
  const stateText = !current ? t('Open') : current.decision === 'dismissed' ? t('Dismissed: {reason}', { reason: current.reason ?? '' }) : t(reviewDecisionLabels[current.decision])
  const locked = Boolean(command.pending) || opening
  return <article className="review-finding" data-finding-id={row.id} data-finding-kind={finding.kind} aria-labelledby={`${reasonId}-kind`}>
    <h4 id={`${reasonId}-kind`}>{t(reviewFindingLabels[finding.kind])}</h4>
    {finding.target.text_at_snapshot && <p className="review-claim" data-stored-text><MathText text={finding.target.text_at_snapshot} /></p>}
    {row.written_against_earlier_text && <p className="review-earlier">{t('Written against an earlier text')}</p>}
    {review.focus === 'assumptions_and_consistency' && finding.evidence.length > 0 && <p className="review-muted">{t('Reviewer inference')}</p>}
    {finding.evidence.length > 0 ? <ReviewEvidence evidence={finding.evidence} sourceName={sourceName} open={open} /> : <p className="review-muted">{t('Reviewer inference · no located evidence')}</p>}
    <dl className="review-explanation">{([['Rationale', finding.rationale], ['Possible impact', finding.possible_impact], ['Suggested fix', finding.suggested_fix], ['Uncertainty', finding.uncertainty]] as const).map(([label, text]) => text != null && <div key={label}><dt>{t(label)}</dt><dd data-stored-text><MathText text={text} /></dd></div>)}</dl>
    <p className="review-muted">{t('Group {i} of {n}', { i: finding.group_index, n: finding.group_count })}</p>
    <p className="review-current" data-stored-text={current?.decision === 'dismissed' ? true : undefined}>{stateText}</p>
    <div className="review-actions"><Button type="button" size="sm" variant="outline" disabled={locked} aria-describedby={locked ? `${reasonId}-locked` : undefined} onClick={() => decide('accepted')}>{t('Accept')}</Button><Button type="button" size="sm" variant="ghost" disabled={locked} aria-describedby={locked ? `${reasonId}-locked` : undefined} onClick={() => { dismissKey.current = crypto.randomUUID(); setDismissing(true); setReason('') }}>{t('Dismiss')}</Button><Button type="button" size="sm" variant="ghost" disabled={locked} aria-describedby={locked ? `${reasonId}-locked` : undefined} onClick={() => decide('deferred')}>{t('Defer')}</Button></div>
    {locked && <p id={`${reasonId}-locked`}>{t(command.pending ? 'The last request may or may not have been saved.' : 'Loading current text…')}</p>}
    {dismissing && <form className="review-dismiss" onSubmit={e => { e.preventDefault(); if (reason.trim() && !locked) decide('dismissed', dismissKey.current) }} onKeyDown={e => {
      if (e.key === 'Escape') { e.stopPropagation(); e.preventDefault(); if (!command.pending) setDismissing(false) }
    }}><label>{t('Reason for dismissal')}<textarea maxLength={2000} data-stored-text value={reason} readOnly={locked} onChange={e => setReason(e.target.value)} /></label><div className="review-actions"><Button type="submit" size="sm" disabled={!reason.trim() || locked} aria-describedby={!reason.trim() ? reasonId : locked ? `${reasonId}-locked` : undefined}>{t('Save dismissal')}</Button><Button type="button" size="sm" variant="ghost" disabled={locked} aria-describedby={locked ? `${reasonId}-locked` : undefined} onClick={() => setDismissing(false)}>{t('Cancel')}</Button></div>{!reason.trim() && <p id={reasonId}>{t('Give a reason to dismiss this finding.')}</p>}</form>}
    {command.pending && !command.busy && <RetryNotice busy={command.busy} retry={() => void command.retry()} />}
    {error && <Notice tone="attention">{error}</Notice>}
    {apply && finding.target_ref.kind === 'claim' && current?.decision === 'accepted' && <Button type="button" size="sm" variant="outline" disabled={locked} aria-describedby={locked ? `${reasonId}-locked` : undefined} onClick={() => { setOpening(true); void apply(review.id, row.id).catch(e => setError(e instanceof Error ? e.message : String(e))).finally(() => setOpening(false)) }}>{t('Open in editor with this text')}</Button>}
    <details><summary><ChevronRight size={14} aria-hidden className="closed" /><ChevronDown size={14} aria-hidden className="opened" />{t('Decision history ({n})', { n: row.decision_history.length })}</summary><ol className="review-history">{row.decision_history.map(decision => <li key={decision.id} data-decision-ordinal={decision.ordinal}><span>{t(decision.applied_ref ? 'Accepted and saved through the editor' : reviewDecisionLabels[decision.decision])}</span>{decision.reason && <span data-stored-text>: {decision.reason}</span>}{decision.applied_ref && <span data-stored-text> · {decision.applied_ref}</span>} · <time>{new Date(decision.created_at).toLocaleString(uiLocale())}</time></li>)}</ol></details>
  </article>
}
