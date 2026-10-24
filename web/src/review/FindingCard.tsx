import { useId, useRef, useState } from 'react'
import { Check, ChevronRight, TriangleAlert, X } from 'lucide-react'
import { api, type ReviewDetail, type ReviewFindingRow } from '../api'
import { reviewDecisionLabels, reviewFindingLabels } from '../labels'
import { useToast } from '../Toast'
import { MathText } from '../MathText'
import { t, uiLocale } from '../i18n'
import { newCommand, useWriteCommand } from './commands'
import { RetryNotice } from './RetryNotice'
import { ReviewEvidence } from './ReviewEvidence'

// One finding (mockup `.finding`): its kind and target, the reviewer's reasoning and the located quote. It stays a
// proposal until the person accepts, dismisses (with a reason) or defers it; the decision is recorded on its own and
// changes no text. A report claim's accepted fix opens in the editor, where only saving changes the report.
export function FindingCard({ researchId, review, row, heading, group, sourceName, open, refresh, apply }: {
  researchId: string; review: ReviewDetail; row: ReviewFindingRow; heading: string; group: string; sourceName: (id: string) => string
  open: (id: string, anchor: string) => void; refresh: () => Promise<void>; apply?: (reviewId: string, findingId: string) => Promise<void>
}) {
  const toast = useToast()
  const [dismissing, setDismissing] = useState(false)
  const [changing, setChanging] = useState(false)
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [opening, setOpening] = useState(false)
  const dismissKey = useRef('')
  const reasonId = useId()
  const { finding, current_decision: current } = row
  const candidate = review.snapshot.target_kind === 'candidate'
  const command = useWriteCommand(`${researchId}:${review.id}:${row.id}:decision`, c => api.decideReview(researchId, review.id, row.id, c.body, c.key), async result => {
    setDismissing(false); setChanging(false); setReason(''); setError('')
    toast('success', result.no_change_made ? t(candidate ? 'Recorded. No change was made to the candidate.' : 'Recorded. No change was made to the answer.') : t('Recorded. No text was changed.'))
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
  const locked = Boolean(command.pending) || opening
  const lockedBy = locked ? `${reasonId}-locked` : undefined
  const inference = review.focus === 'assumptions_and_consistency' || finding.evidence.length === 0
  const decided = current && !changing
  const stateText = !current ? '' : current.decision === 'dismissed' ? t('Dismissed: {reason}', { reason: current.reason ?? '' })
    : current.decision === 'deferred' ? t('Deferred.') : current.applied_ref ? t('Saved through the editor. The finding is recorded as accepted with this revision.')
      : t(candidate ? 'Accepted. Recorded. No change was made to the candidate.' : review.snapshot.target_kind === 'answer' ? 'Accepted. Recorded. No change was made to the answer.' : 'Accepted. Recorded. No text was changed.')
  const canApply = apply && finding.target_ref.kind === 'claim' && current?.decision === 'accepted'
  return <article className={`finding${decided ? ' done' : ''}`} data-finding-id={row.id} data-finding-kind={finding.kind} aria-labelledby={`${reasonId}-kind`}>
    <header><h4 id={`${reasonId}-kind`}>{t(reviewFindingLabels[finding.kind])}</h4><span data-stored-text>· {heading}</span><span className="spacer" />
      {inference && <span className="pill">{finding.evidence.length ? t('Reviewer inference') : t('Reviewer inference · no located evidence')}</span>}</header>
    {group && <p className="foot-note review-group-refs" data-stored-text>{group}</p>}
    <p data-stored-text><MathText text={finding.rationale} /></p>
    {finding.target.text_at_snapshot && <p className="foot-note">{t('Text at review time')}: <span className="review-claim" data-stored-text><MathText text={finding.target.text_at_snapshot} /></span></p>}
    {row.written_against_earlier_text && <p className="foot-note review-earlier"><TriangleAlert size={12} aria-hidden />{t('Written against an earlier text')}</p>}
    {finding.evidence.length > 0 && <ReviewEvidence evidence={finding.evidence} sourceName={sourceName} open={open} />}
    <dl className="kv2 review-explanation">{([['Possible impact', finding.possible_impact], ['Suggested fix', finding.suggested_fix], ['Uncertainty', finding.uncertainty]] as const).map(([label, text]) => text != null && <div key={label} className="kv2-row"><dt>{t(label)}</dt><dd data-stored-text><MathText text={text} /></dd></div>)}</dl>
    {decided ? <p className="foot-note review-decided"><span className="review-current" data-stored-text={current.decision === 'dismissed' ? true : undefined}>{stateText}</span>
      {canApply && <> <button type="button" className="link" disabled={locked} aria-describedby={lockedBy} onClick={() => { setOpening(true); void apply(review.id, row.id).catch(e => setError(e instanceof Error ? e.message : String(e))).finally(() => setOpening(false)) }}>{t('Open in editor with this text')}</button></>}
      {!current.applied_ref && <> <button type="button" className="link" disabled={locked} aria-describedby={lockedBy} onClick={() => setChanging(true)}>{t('Change')}</button></>}</p>
      : dismissing ? <form className="why-f review-dismiss" onSubmit={e => { e.preventDefault(); if (reason.trim() && !locked) decide('dismissed', dismissKey.current) }} onKeyDown={e => {
        if (e.key === 'Escape') { e.stopPropagation(); e.preventDefault(); if (!command.pending) setDismissing(false) }
      }}><label className="lbl">{t('Reason for dismissal')}<input className="field" maxLength={2000} data-stored-text value={reason} readOnly={locked} autoFocus aria-describedby={!reason.trim() ? reasonId : undefined} onChange={e => setReason(e.target.value)} /></label>
        <button type="submit" className="btn-pri" disabled={!reason.trim() || locked} aria-describedby={!reason.trim() ? reasonId : lockedBy}>{t('Save dismissal')}</button>
        <button type="button" className="ghost" disabled={locked} aria-describedby={lockedBy} onClick={() => setDismissing(false)}>{t('Cancel')}</button>
        {!reason.trim() && <p id={reasonId} className="foot-note">{t('Give a reason to dismiss this finding.')}</p>}</form>
        : <div className="acts">
          <button type="button" className="ghost" disabled={locked} aria-describedby={lockedBy} onClick={() => decide('accepted')}><Check aria-hidden />{t('Accept')}</button>
          <button type="button" className="ghost" disabled={locked} aria-describedby={lockedBy} onClick={() => { dismissKey.current = crypto.randomUUID(); setDismissing(true); setReason('') }}><X aria-hidden />{t('Dismiss')}</button>
          <button type="button" className="ghost" disabled={locked} aria-describedby={lockedBy} onClick={() => decide('deferred')}>{t('Defer')}</button>
          {current && <button type="button" className="link" disabled={locked} onClick={() => setChanging(false)}>{t('Keep {decision}', { decision: t(reviewDecisionLabels[current.decision]).toLocaleLowerCase(uiLocale()) })}</button>}
        </div>}
    {locked && <p id={`${reasonId}-locked`} className="foot-note">{command.pending ? t('The last request may or may not have been saved.') : <span className="shimmer-text">{t('Loading current text…')}</span>}</p>}
    {command.pending && !command.busy && <RetryNotice busy={command.busy} retry={() => void command.retry()} />}
    {error && <div className="notice warn"><TriangleAlert aria-hidden /><span>{error}</span></div>}
    {row.decision_history.length > 0 && <details><summary><ChevronRight size={14} aria-hidden />{t('Decision history ({n})', { n: row.decision_history.length })}</summary><ol className="review-history">{row.decision_history.map(decision => <li key={decision.id} data-decision-ordinal={decision.ordinal}><span>{t(decision.applied_ref ? 'Accepted and saved through the editor' : reviewDecisionLabels[decision.decision])}</span>{decision.reason && <span data-stored-text>: {decision.reason}</span>}{decision.applied_ref && <span data-stored-text> · {decision.applied_ref}</span>} · <time>{new Date(decision.created_at).toLocaleString(uiLocale())}</time></li>)}</ol></details>}
  </article>
}
